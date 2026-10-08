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
        overrides.setdefault("DASHBOARD_HOST", "127.0.0.1")  # live needs a token unless bound to loopback
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
    """No NEW swap is ever sent for an unknown outcome. Only the identical signed transaction (same
    signature and requestId) may be re-posted to learn its status, which Ultra documents as safe."""
    from nightcrawler.broker.live import EXECUTE_REPOLLS

    venue.execute_with(response, status=status)
    quote = broker.quote("buy", HIGGS, BUY_IN, 6)
    with pytest.raises(SwapUnknown, match="reconcile"):
        broker.execute(quote, None)
    posts = list(venue.executed)
    assert 1 <= len(posts) <= 1 + EXECUTE_REPOLLS and all(p == posts[0] for p in posts)
    (failure,) = receipts_of(ledger, "swap_failed")
    assert failure.payload["outcome"] == "unknown"
    with pytest.raises(QuoteRejected):
        broker.execute(quote, None)
    assert venue.executed == posts


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
                             BOT_WALLET_SECRET=wallet.secret_base58(), DASHBOARD_HOST="127.0.0.1")
    clock = RealClock()
    http = HttpClient.from_settings(settings, clock=clock)
    jupiter = JupiterClient(http, base_url=settings.jupiter_base_url, api_key=settings.jupiter_api_key)
    broker = LiveBroker(jupiter, SolanaRpc(http, url=settings.solana_rpc_url), wallet, FakeLedger(clock=clock),
                        settings, clock)
    assert broker.wallet_value_usd() == 0.0
    with pytest.raises(QuoteRejected, match="(?i)insufficient funds|no transaction"):
        broker.quote("buy", USDC, 10_000_000, 6)


# --------------------------------------------------------------------------- review fixes


def execute_sequence(venue: Venue, *responses: Any) -> None:
    """/execute answers ``responses`` in order (an exception instance is raised), the last one forever."""
    queue = list(responses)

    def respond(request):
        venue.executed.append(request.json)
        body = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(body, BaseException):
            raise body
        return load_fixture(body) if isinstance(body, str) else body

    venue.http.register("/ultra/v1/execute", respond, method="POST")


def test_a_ledger_failure_after_a_landed_swap_is_an_unknown_outcome(broker, venue, ledger) -> None:
    from nightcrawler.ledger import LedgerError

    ledger.fail_next["record_fill"] = LedgerError("sqlite error: database is locked")
    with pytest.raises(SwapUnknown, match="not recorded") as ei:
        broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert len(venue.executed) == 1  # the swap WAS sent and landed
    assert ei.value.fill is not None and ei.value.fill.token_amount == ACTUAL_OUT  # actual amounts kept
    assert ledger.fills() == []


def test_on_fill_runs_in_the_fill_transaction_and_its_failure_rolls_both_back(broker, venue, ledger) -> None:
    seen: list[Any] = []

    def apply(fill):
        seen.append(fill)
        ledger.set_kv("applied", fill.id)

    fill = broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None, on_fill=apply)
    assert seen == [fill] and ledger.get_kv("applied") == fill.id and ledger.fills() == [fill]

    def boom(_fill):
        ledger.set_kv("half", True)
        raise RuntimeError("position write failed")

    with pytest.raises(SwapUnknown) as ei:
        broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None, on_fill=boom)
    assert ledger.get_kv("half") is None and len(ledger.fills()) == 1  # rolled back together
    assert ei.value.fill is not None


@pytest.mark.parametrize("code", [-1000, -1001, -1006, -2000, -2001, -2005, None])
def test_an_ambiguous_ultra_failure_is_unknown_not_failed(broker, venue, ledger, code) -> None:
    execute_sequence(venue, {"status": "Failed", "signature": "5igSIG", "code": code, "error": "Transaction timed out"})
    quote = broker.quote("buy", HIGGS, BUY_IN, 6)
    with pytest.raises(SwapUnknown):
        broker.execute(quote, None)
    # only the IDENTICAL signed transaction is ever re-posted (Ultra: safe, same signature)
    assert 1 <= len(venue.executed) <= 3 and all(e == venue.executed[0] for e in venue.executed)
    assert receipts_of(ledger, "swap_failed")[-1].payload["outcome"] == "unknown"


@pytest.mark.parametrize("code,signature", [(-2, None), (-1005, None), (-1003, None), (-2003, None),
                                            (6001, "5igSIG")])
def test_a_definite_ultra_failure_stays_failed(broker, venue, code, signature) -> None:
    execute_sequence(venue, {"status": "Failed", "signature": signature, "code": code, "error": "nope"})
    with pytest.raises(SwapFailed):
        broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert len(venue.executed) == 1


def test_a_transport_error_re_polls_the_same_transaction_and_books_the_real_fill(broker, venue, ledger) -> None:
    execute_sequence(venue, requests.Timeout("read timed out"), "jup_ultra_execute_success_synthetic")
    fill = broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert len(venue.executed) == 2 and venue.executed[0] == venue.executed[1]
    assert fill.token_amount == ACTUAL_OUT and fill.signature
    assert receipts_of(ledger, "swap_failed") == []


def test_a_sell_is_sent_unsimulated_when_the_rpc_is_down_but_a_buy_is_not(broker, venue) -> None:
    venue.simulation = {"error": {"code": -32005, "message": "node is behind"}}
    venue.execute_with({"status": "Success", "signature": "sig", "inputAmountResult": "16239400281",
                        "outputAmountResult": "98000000"})
    position = Position(id="pos_1", mint=HIGGS, symbol="HIGGS", pool=None, opened_at=0.0, token_decimals=6,
                        token_amount=QUOTED_OUT)
    fill = broker.execute(broker.quote("sell", HIGGS, QUOTED_OUT, 6, max_impact_pct=25.0), position)
    assert fill.side == "sell" and len(venue.executed) == 1
    with pytest.raises(SwapFailed, match="simulation unavailable"):
        broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert len(venue.executed) == 1


def test_a_sell_with_a_definite_simulation_error_is_still_not_sent(broker, venue) -> None:
    venue.simulation = simulation_result({"InstructionError": [2, {"Custom": 6001}]})
    position = Position(id="pos_1", mint=HIGGS, symbol="HIGGS", pool=None, opened_at=0.0, token_decimals=6,
                        token_amount=QUOTED_OUT)
    with pytest.raises(SwapFailed, match="simulation failed"):
        broker.execute(broker.quote("sell", HIGGS, QUOTED_OUT, 6), position)
    assert venue.executed == []


def test_quote_age_is_checked_again_right_before_sending(broker, venue, fake_clock) -> None:
    original = venue._rpc

    def slow_rpc(request):
        fake_clock.advance(60)  # rate-limited RPC retries/backoff during the simulation
        return original(request)

    venue.http.register(venue.rpc_url, slow_rpc, method="POST")
    with pytest.raises(QuoteRejected, match="stale"):
        broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert venue.executed == []


# --------------------------------------------------------------------------- the signature of an unknown swap (F5)


def test_an_unknown_outcome_carries_the_signature_of_the_signed_transaction(broker, venue, ledger) -> None:
    """The fee payer's signature IS the transaction id: the engine can ask the chain for the status of
    exactly this transaction instead of waiting blind."""
    venue.execute_with(requests.ConnectionError("connection reset"))
    with pytest.raises(SwapUnknown) as ei:
        broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    expected = str(decode(venue.executed[0]["signedTransaction"]).signatures[0])
    assert ei.value.signature == expected
    assert receipts_of(ledger, "swap_failed")[-1].payload["signature"] == expected


def test_an_unknown_outcome_prefers_the_signature_ultra_reported(broker, venue) -> None:
    execute_sequence(venue, {"status": "Failed", "signature": "5igSIG", "code": -1000, "error": "timed out"})
    with pytest.raises(SwapUnknown) as ei:
        broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert ei.value.signature == "5igSIG"


def test_a_gasless_unknown_outcome_has_no_signature_of_ours_to_check(broker, venue, keypair) -> None:
    venue.transaction = unsigned_tx_b64(Keypair().pubkey(), keypair.pubkey())  # Ultra pays and signs first
    venue.execute_with(requests.ConnectionError("connection reset"))
    with pytest.raises(SwapUnknown) as ei:
        broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert ei.value.signature is None


def test_a_landed_but_unrecorded_swap_carries_its_signature(broker, venue, ledger) -> None:
    from nightcrawler.ledger import LedgerError

    ledger.fail_next["record_fill"] = LedgerError("sqlite error: database is locked")
    with pytest.raises(SwapUnknown) as ei:
        broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert ei.value.signature == ei.value.fill.signature == load_fixture("jup_ultra_execute_success_synthetic")[
        "signature"]


def test_on_signed_reports_the_signature_before_anything_is_sent(broker, venue) -> None:
    """The engine stores it in its in-flight marker, so even a process killed mid-swap can ask the chain."""
    seen: list[tuple[Any, int]] = []
    broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None,
                   on_signed=lambda signature: seen.append((signature, len(venue.executed))))
    assert seen == [(str(decode(venue.executed[0]["signedTransaction"]).signatures[0]), 0)]
    assert broker.reports_signature is True


def test_a_failing_on_signed_callback_never_blocks_the_swap(broker, venue) -> None:
    def broken(_signature: Any) -> None:
        raise RuntimeError("ledger busy")

    fill = broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None, on_signed=broken)
    assert fill.token_amount == ACTUAL_OUT and len(venue.executed) == 1


@pytest.mark.parametrize("value,expected", [
    (None, None),  # the cluster does not know the signature (yet, or any more)
    ({"slot": 1, "confirmations": 0, "err": None, "confirmationStatus": "processed"}, None),  # not final
    ({"slot": 1, "confirmations": 3, "err": None, "confirmationStatus": "confirmed"}, "landed"),
    ({"slot": 1, "confirmations": None, "err": None, "confirmationStatus": "finalized"}, "landed"),
    ({"slot": 1, "confirmations": None, "err": {"InstructionError": [2, {"Custom": 6001}]},
      "confirmationStatus": "finalized"}, "failed"),
    ({"slot": 1, "confirmations": 5, "err": {"InstructionError": [2, {"Custom": 6001}]},
      "confirmationStatus": "confirmed"}, "failed"),
])
def test_swap_status_reads_get_signature_statuses(broker, venue, value, expected) -> None:
    asked: list[Any] = []

    def rpc(request):
        body = request.json
        if body["method"] != "getSignatureStatuses":
            return venue._rpc(request)
        asked.append(body["params"])
        return {"jsonrpc": "2.0", "id": body["id"], "result": {"context": {"slot": 9}, "value": [value]}}

    venue.http.register(venue.rpc_url, rpc, method="POST")
    assert broker.swap_status("5igSIG") == expected
    assert asked == [[["5igSIG"], {"searchTransactionHistory": True}]]
