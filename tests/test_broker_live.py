"""LiveBroker: construction guards, real ed25519 signing of genuine v0 transactions,
simulate-before-send, Ultra execute outcomes, never retrying a swap, wallet cap.

Every key here is generated fresh per test (never funded); no request leaves the
machine (FakeHttp) except in the opt-in ``live`` smoke test, which only quotes.
"""

from __future__ import annotations

import base64
import logging
import sys
from typing import Any

import pytest
import requests
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import MessageV0, to_bytes_versioned
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction

from fakes import load_fixture
from nightcrawler.base58 import b58encode
from nightcrawler.broker.base import (
    Broker,
    LiveNotAllowed,
    QuoteRejected,
    SwapFailed,
    SwapUnknown,
    require_solders,
)
from nightcrawler.broker.live import LiveBroker, missing_signatures
from nightcrawler.broker.paper import PaperBroker
from nightcrawler.broker.wallet import Wallet, load_keypair
from nightcrawler.clock import RealClock
from nightcrawler.config import LIVE_CONFIRM_PHRASE
from nightcrawler.http import HttpClient
from nightcrawler.models import SOL_MINT, Position
from nightcrawler.sources.jupiter import JupiterClient
from nightcrawler.sources.solana_rpc import SolanaRpc
from test_broker_paper import BUY_IN, HIGGS, SOL_USD, USDC, FakeLedger

ACTUAL_OUT = 16_200_000_000  # jup_ultra_execute_success_synthetic.json
QUOTED_OUT = 16_239_400_281  # jup_ultra_order_buy.json
REQUEST_ID = "01a11c56-cfde-72ec-a552-db4ef3aa8c67"


# --------------------------------------------------------------------------- transactions


def unsigned_tx_b64(*signers: Pubkey) -> str:
    """A genuine unsigned v0 transaction (system transfer) needing ``signers`` (fee payer first)."""
    payer, owner = signers[0], signers[-1]
    ix = transfer(TransferParams(from_pubkey=owner, to_pubkey=Pubkey.new_unique(), lamports=1_000))
    message = MessageV0.try_compile(payer, [ix], [], Hash.new_unique())
    tx = VersionedTransaction.populate(message, [Signature.default()] * len(signers))
    return base64.b64encode(bytes(tx)).decode()


def decode(tx_b64: str) -> VersionedTransaction:
    return VersionedTransaction.from_bytes(base64.b64decode(tx_b64))


def simulation_result(err: Any) -> dict[str, Any]:
    """JSON-RPC body of ``simulateTransaction`` (minus id) with the given ``err``."""
    return {"result": {"context": {"slot": 1}, "value": {"err": err, "logs": ["ok"], "unitsConsumed": 1_000}}}


# --------------------------------------------------------------------------- fixtures


@pytest.fixture
def keypair() -> Keypair:
    return Keypair()  # fresh, never funded


@pytest.fixture
def wallet(keypair: Keypair) -> Wallet:
    return load_keypair(b58encode(bytes(keypair)))


@pytest.fixture
def live_settings(make_settings, wallet):
    def _make(**overrides: Any):
        return make_settings(TRADING_MODE="live", LIVE_CONFIRM=LIVE_CONFIRM_PHRASE,
                             BOT_WALLET_SECRET=wallet.secret_base58(), **overrides)

    return _make


class Venue:
    """Scripted Jupiter Ultra + Solana RPC over FakeHttp; records what was sent."""

    def __init__(self, fake_http, settings, keypair: Keypair) -> None:
        self.http = fake_http
        self.rpc_url = settings.solana_rpc_url
        self.transaction = unsigned_tx_b64(keypair.pubkey())
        self.order_overrides: dict[str, Any] = {"signatureFeeLamports": 5_000, "prioritizationFeeLamports": 10_000,
                                                "rentFeeLamports": 2_039_280}
        self.simulation: dict[str, Any] = simulation_result(None)
        self.executed: list[dict[str, Any]] = []
        self.simulated: list[list[Any]] = []
        fake_http.register_fixture("/price/v3", "jup_price_v3")
        fake_http.register_fixture("/ultra/v1/holdings/", "jup_ultra_holdings_empty")
        fake_http.register(f"inputMint={SOL_MINT}", self._order("jup_ultra_order_buy"))
        fake_http.register(f"outputMint={SOL_MINT}", self._order("jup_ultra_order_sell"))
        fake_http.register(self.rpc_url, self._rpc, method="POST")
        self.execute_with("jup_ultra_execute_success_synthetic")

    def _order(self, fixture: str):
        def respond(request) -> dict[str, Any]:
            body = {**load_fixture(fixture), "transaction": self.transaction, "taker": request.params.get("taker")}
            return {**body, **self.order_overrides}

        return respond

    def _rpc(self, request) -> dict[str, Any]:
        body = request.json
        if body["method"] == "simulateTransaction":
            self.simulated.append(body["params"])
            return {"jsonrpc": "2.0", "id": body["id"], **self.simulation}
        if body["method"] == "getAccountInfo":
            return {**load_fixture("rpc_getAccountInfo_mint"), "id": body["id"]}
        raise AssertionError(f"unexpected RPC {body['method']}")

    def execute_with(self, response: Any, status: int = 200) -> None:
        body = load_fixture(response) if isinstance(response, str) else response

        def respond(request):
            self.executed.append(request.json)
            if isinstance(body, BaseException):
                raise body
            return body

        self.http.register("/ultra/v1/execute", respond, status=status, method="POST")


@pytest.fixture
def venue(fake_http, live_settings, keypair) -> Venue:
    return Venue(fake_http, live_settings(), keypair)


@pytest.fixture
def ledger(fake_clock) -> FakeLedger:
    return FakeLedger(clock=fake_clock)


@pytest.fixture
def make_broker(venue, http_client, wallet, ledger, fake_clock, live_settings):
    def _make(**overrides: Any) -> LiveBroker:
        s = live_settings(**overrides)
        jupiter = JupiterClient(http_client, base_url=s.jupiter_base_url)
        return LiveBroker(jupiter, SolanaRpc(http_client, url=s.solana_rpc_url), wallet, ledger, s, fake_clock)

    return _make


@pytest.fixture
def broker(make_broker) -> LiveBroker:
    return make_broker()


def receipts_of(ledger: FakeLedger, kind: str):
    return [r for r in ledger.receipts() if r.kind == kind]


# --------------------------------------------------------------------------- construction guards


def test_refuses_unless_trading_mode_is_live(make_settings, http_client, wallet, ledger, fake_clock) -> None:
    with pytest.raises(LiveNotAllowed, match="TRADING_MODE"):
        LiveBroker(object(), object(), wallet, ledger, make_settings(), fake_clock)


def test_refuses_without_the_exact_confirmation(live_settings, wallet, ledger, fake_clock) -> None:
    settings = live_settings()
    object.__setattr__(settings, "live_confirm", "i accept real money risk")  # bypass config validation
    with pytest.raises(LiveNotAllowed, match="LIVE_CONFIRM"):
        LiveBroker(object(), object(), wallet, ledger, settings, fake_clock)


def test_refuses_without_a_wallet(live_settings, ledger, fake_clock) -> None:
    with pytest.raises(LiveNotAllowed, match="wallet"):
        LiveBroker(object(), object(), None, ledger, live_settings(), fake_clock)


def test_refuses_without_solders(live_settings, wallet, ledger, fake_clock, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "solders", None)
    with pytest.raises(LiveNotAllowed, match=r"nightcrawler\[live\]"):
        require_solders()
    with pytest.raises(LiveNotAllowed, match=r"nightcrawler\[live\]"):
        LiveBroker(object(), object(), wallet, ledger, live_settings(), fake_clock)


def test_live_broker_implements_the_broker_protocol(broker, wallet) -> None:
    assert isinstance(broker, Broker)
    assert broker.mode == "live" and broker.pubkey == wallet.pubkey()


# --------------------------------------------------------------------------- quoting


def test_paper_and_live_send_the_identical_ultra_order(broker, venue, http_client, ledger, fake_clock,
                                                       make_settings, wallet) -> None:
    s = make_settings()
    paper = PaperBroker(JupiterClient(http_client, base_url=s.jupiter_base_url), ledger, s, fake_clock,
                        taker=wallet.pubkey())
    paper.quote("buy", HIGGS, BUY_IN, 6)
    broker.quote("buy", HIGGS, BUY_IN, 6)
    paper_call, live_call = venue.http.calls_to("/ultra/v1/order")
    assert paper_call.full_url == live_call.full_url
    assert live_call.params["taker"] == wallet.pubkey()


def test_quote_without_a_transaction_is_rejected(broker, fake_http) -> None:
    fake_http.register_fixture(f"inputMint={SOL_MINT}", "jup_ultra_order_buy_insufficient_funds")
    with pytest.raises(QuoteRejected, match="Insufficient funds"):
        broker.quote("buy", HIGGS, BUY_IN, 6)


def test_quote_with_an_empty_transaction_and_no_error_is_rejected(broker, venue) -> None:
    venue.transaction = ""
    with pytest.raises(QuoteRejected, match="no transaction"):
        broker.quote("buy", HIGGS, BUY_IN, 6)


def test_wallet_value_counts_sol_and_priced_tokens(broker, fake_http) -> None:
    fake_http.register_fixture("/ultra/v1/holdings/", "jup_ultra_holdings_synthetic")
    sol_part = 0.25 * SOL_USD
    token_part = 16_200 * 0.0008559214683299623  # decimals 6 from the mint account (RPC)
    assert broker.wallet_value_usd() == pytest.approx(sol_part + token_part)


def test_buy_quote_refused_when_wallet_exceeds_the_cap(make_broker, fake_http, venue) -> None:
    fake_http.register_fixture("/ultra/v1/holdings/", "jup_ultra_holdings_synthetic")  # ~ $41
    with pytest.raises(QuoteRejected, match=r"\[wallet_cap\] wallet worth \$40\.95"):
        make_broker(MAX_WALLET_USD=30).quote("buy", HIGGS, BUY_IN, 6)
    assert venue.http.calls_to("/ultra/v1/order") == []
    assert make_broker(MAX_WALLET_USD=150).quote("buy", HIGGS, BUY_IN, 6).out_amount == QUOTED_OUT


def test_buy_quote_fails_closed_when_wallet_value_is_unknown(broker, fake_http) -> None:
    fake_http.register("/ultra/v1/holdings/", {"error": "nope"}, status=400)
    with pytest.raises(QuoteRejected, match=r"\[wallet_cap\] wallet value unavailable"):
        broker.quote("buy", HIGGS, BUY_IN, 6)


def test_bad_arguments_fail_before_any_request(broker, fake_http) -> None:
    for side, amount, decimals in (("buy", 0, 6), ("buy", BUY_IN, -1), ("buy", 1.5, 6), ("swap", BUY_IN, 6)):
        with pytest.raises(ValueError):
            broker.quote(side, HIGGS, amount, decimals)  # type: ignore[arg-type]
    assert fake_http.calls == []


def test_sell_quotes_skip_the_wallet_cap(make_broker, fake_http) -> None:
    fake_http.register_fixture("/ultra/v1/holdings/", "jup_ultra_holdings_synthetic")
    assert make_broker(MAX_WALLET_USD=1).quote("sell", HIGGS, QUOTED_OUT, 6).side == "sell"


# --------------------------------------------------------------------------- execution


def test_success_signs_simulates_sends_once_and_records_actual_amounts(broker, venue, ledger, keypair) -> None:
    quote = broker.quote("buy", HIGGS, BUY_IN, 6)
    fill = broker.execute(quote, None, symbol="HIGGS")

    (sent,) = venue.executed
    assert sent["requestId"] == REQUEST_ID
    signed = decode(sent["signedTransaction"])
    assert signed.verify_with_results() == [True]
    assert signed.signatures[0].verify(keypair.pubkey(), to_bytes_versioned(signed.message))
    assert bytes(signed) == bytes(VersionedTransaction(decode(venue.transaction).message, [keypair]))

    (simulated,) = venue.simulated
    assert simulated[0] == sent["signedTransaction"]
    assert simulated[1]["sigVerify"] is True

    assert (fill.mode, fill.side, fill.symbol) == ("live", "buy", "HIGGS")
    assert (fill.sol_lamports, fill.token_amount) == (BUY_IN, ACTUAL_OUT)
    assert fill.expected_out_amount == QUOTED_OUT
    assert fill.signature == load_fixture("jup_ultra_execute_success_synthetic")["signature"]
    assert fill.fees_lamports == 15_000 and fill.rent_lamports == 2_039_280
    assert fill.sol_usd == pytest.approx(SOL_USD)
    assert fill.receipt_hash == receipts_of(ledger, "fill")[0].hash
    assert ledger.verify_chain() == (True, None)


def test_sell_fill_maps_actual_input_to_tokens_and_output_to_sol(broker, venue) -> None:
    venue.execute_with({"status": "Success", "signature": "sig", "inputAmountResult": "16239400281",
                        "outputAmountResult": "98000000"})
    position = Position(id="pos_1", mint=HIGGS, symbol="HIGGS", pool=None, opened_at=0.0, token_decimals=6,
                        token_amount=QUOTED_OUT)
    fill = broker.execute(broker.quote("sell", HIGGS, QUOTED_OUT, 6), position)
    assert (fill.token_amount, fill.sol_lamports, fill.rent_lamports) == (QUOTED_OUT, 98_000_000, 0)
    assert fill.position_id == "pos_1" and fill.symbol == "HIGGS"


def test_simulation_error_aborts_before_sending(broker, venue, ledger) -> None:
    venue.simulation = simulation_result({"InstructionError": [2, {"Custom": 6001}]})
    with pytest.raises(SwapFailed, match="simulation failed"):
        broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert venue.executed == []
    (failure,) = receipts_of(ledger, "swap_failed")
    assert failure.payload["stage"] == "simulate" and failure.payload["outcome"] == "failed"
    assert receipts_of(ledger, "fill") == []


def test_unreachable_simulation_rpc_fails_closed(broker, venue) -> None:
    venue.simulation = {"error": {"code": -32005, "message": "node is behind"}}
    with pytest.raises(SwapFailed, match="simulation unavailable"):
        broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert venue.executed == []


def test_simulation_can_be_disabled(make_broker, venue) -> None:
    broker = make_broker(SIMULATE_BEFORE_SEND=False)
    broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert venue.simulated == [] and len(venue.executed) == 1


def test_failed_status_records_a_failure_and_changes_nothing(broker, venue, ledger) -> None:
    venue.execute_with("jup_ultra_execute_failed_synthetic")
    quote = broker.quote("buy", HIGGS, BUY_IN, 6)
    with pytest.raises(SwapFailed, match="Transaction expired"):
        broker.execute(quote, None)
    (failure,) = receipts_of(ledger, "swap_failed")
    assert failure.payload["outcome"] == "failed" and failure.payload["code"] == -1005
    assert failure.payload["request_id"] == REQUEST_ID
    assert receipts_of(ledger, "fill") == [] and ledger.fills() == []
    with pytest.raises(QuoteRejected, match="already executed"):
        broker.execute(quote, None)
    assert len(venue.executed) == 1


@pytest.mark.parametrize("response,status", [
    (requests.ConnectionError("connection reset"), 200),
    ({"error": "upstream timeout"}, 503),
    ({"status": "Pending", "signature": "sig"}, 200),
])
def test_unknown_outcome_is_never_retried(broker, venue, ledger, response, status) -> None:
    venue.execute_with(response, status=status)
    quote = broker.quote("buy", HIGGS, BUY_IN, 6)
    with pytest.raises(SwapUnknown, match="reconcile"):
        broker.execute(quote, None)
    assert len(venue.executed) == 1
    (failure,) = receipts_of(ledger, "swap_failed")
    assert failure.payload["outcome"] == "unknown"
    with pytest.raises(QuoteRejected):
        broker.execute(quote, None)
    assert len(venue.executed) == 1


def test_stale_quote_is_never_signed_or_sent(broker, venue, fake_clock) -> None:
    quote = broker.quote("buy", HIGGS, BUY_IN, 6)
    fake_clock.advance(16)
    with pytest.raises(QuoteRejected, match="stale"):
        broker.execute(quote, None)
    assert venue.simulated == [] and venue.executed == []


def test_transaction_for_another_wallet_is_refused(broker, venue) -> None:
    venue.transaction = unsigned_tx_b64(Keypair().pubkey())
    with pytest.raises(QuoteRejected, match="does not require this wallet"):
        broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert venue.simulated == [] and venue.executed == []


def test_gasless_transaction_gets_only_our_signature_and_skips_simulation(broker, venue, keypair) -> None:
    fee_payer = Keypair().pubkey()  # Ultra's co-signer on gasless swaps
    venue.transaction = unsigned_tx_b64(fee_payer, keypair.pubkey())
    broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    signed = decode(venue.executed[0]["signedTransaction"])
    assert signed.verify_with_results() == [False, True]
    assert signed.signatures[0] == Signature.default()
    assert missing_signatures(venue.executed[0]["signedTransaction"]) == 1
    assert venue.simulated == []


def test_balances_come_from_ultra_holdings(broker, fake_http, wallet) -> None:
    fake_http.register_fixture("/ultra/v1/holdings/", "jup_ultra_holdings_synthetic")
    balances = broker.balances()
    assert balances.sol_lamports == 250_000_000 and balances.tokens == {HIGGS: 16_200_000_000}
    assert fake_http.calls_to(f"/ultra/v1/holdings/{wallet.pubkey()}")


def test_the_secret_never_reaches_logs_or_receipts(broker, venue, ledger, wallet, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    venue.execute_with("jup_ultra_execute_failed_synthetic")
    with pytest.raises(SwapFailed):
        broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    secret = wallet.secret_base58()
    assert secret not in caplog.text
    assert all(secret not in str(r.payload) for r in ledger.receipts())


@pytest.mark.live
def test_live_smoke_unfunded_wallet_quotes_but_never_trades(make_settings) -> None:
    """Opt-in (NIGHTCRAWLER_LIVE_TESTS=1): a fresh EMPTY wallet against real Jupiter.

    The cap check reads real (empty) holdings; Ultra answers "Insufficient funds"
    without a transaction, so the broker refuses - nothing can be signed or sent.
    """
    wallet = load_keypair(b58encode(bytes(Keypair())))
    settings = make_settings(TRADING_MODE="live", LIVE_CONFIRM=LIVE_CONFIRM_PHRASE,
                             BOT_WALLET_SECRET=wallet.secret_base58())
    clock = RealClock()
    http = HttpClient.from_settings(settings, clock=clock)
    jupiter = JupiterClient(http, base_url=settings.jupiter_base_url, api_key=settings.jupiter_api_key)
    broker = LiveBroker(jupiter, SolanaRpc(http, url=settings.solana_rpc_url), wallet, FakeLedger(clock=clock),
                        settings, clock)
    assert broker.wallet_value_usd() == 0.0
    with pytest.raises(QuoteRejected, match="(?i)insufficient funds|no transaction"):
        broker.quote("buy", USDC, 10_000_000, 6)
