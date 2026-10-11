"""ACC-8: paper and live book token-account rent identically.

The same buy / partial sell / full sell / re-buy runs through ``PaperBroker.execute`` and
``LiveBroker.execute`` (real signing, simulation and Ultra execute over FakeHttp), with Ultra
answering as it does for a real wallet: ``rentFeeLamports`` > 0 only on the buy that creates the
token account, and 0 afterwards, because Ultra's full-balance sell leaves the (empty) account open
(verified 2026-10-08 on a live /order: the sell transaction closes only its temporary wSOL account).
Both brokers must put the same ``rent_lamports`` on the same fills.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from solders.keypair import Keypair

from fakes import load_fixture
from nightcrawler.base58 import b58encode
from nightcrawler.broker.base import token_rent_lamports
from nightcrawler.broker.live import LiveBroker
from nightcrawler.broker.paper import PaperBroker
from nightcrawler.broker.wallet import load_keypair
from nightcrawler.config import LIVE_CONFIRM_PHRASE
from nightcrawler.models import SOL_MINT, TOKEN_ACCOUNT_RENT_LAMPORTS, Fill, Position, Quote
from nightcrawler.sources.jupiter import JupiterClient
from nightcrawler.sources.solana_rpc import SolanaRpc
from test_broker_live import unsigned_tx_b64
from test_broker_paper import BUY_IN, HIGGS, FakeLedger

OPENING_RENT = 2_976_880  # what Ultra reported for a new pump.fun (Token-2022) account on 2026-10-08


class UltraForOneWallet:
    """Scripted Ultra over FakeHttp that answers like it would for one real wallet: the token account
    exists after the first buy and is never closed by a sell. Execute lands exactly the quote."""

    def __init__(self, fake_http, rpc_url: str, keypair: Keypair) -> None:
        self.account_open = False
        self.transaction = unsigned_tx_b64(keypair.pubkey())
        self.last_order: dict[str, Any] = {}
        fake_http.register_fixture("/price/v3", "jup_price_v3")
        fake_http.register_fixture("/ultra/v1/holdings/", "jup_ultra_holdings_empty")
        fake_http.register(f"inputMint={SOL_MINT}", self._order("jup_ultra_order_buy"))
        fake_http.register(f"outputMint={SOL_MINT}", self._order("jup_ultra_order_sell"))
        fake_http.register(rpc_url, self._rpc, method="POST")
        fake_http.register("/ultra/v1/execute", self._execute, method="POST")

    def _order(self, fixture: str):
        base = load_fixture(fixture)

        def respond(request) -> dict[str, Any]:
            amount = int(request.params["amount"])
            out = int(base["outAmount"]) * amount // int(base["inAmount"])
            opens = request.params["inputMint"] == SOL_MINT and not self.account_open
            self.last_order = {**base, "inAmount": str(amount), "outAmount": str(out),
                               "otherAmountThreshold": str(out), "transaction": self.transaction,
                               "taker": request.params.get("taker"), "signatureFeeLamports": 5_000,
                               "prioritizationFeeLamports": 10_000, "rentFeeLamports": OPENING_RENT if opens else 0}
            return self.last_order

        return respond

    @staticmethod
    def _rpc(request) -> dict[str, Any]:
        body = request.json
        assert body["method"] == "simulateTransaction", body["method"]
        return {"jsonrpc": "2.0", "id": body["id"],
                "result": {"context": {"slot": 1}, "value": {"err": None, "logs": [], "unitsConsumed": 1}}}

    def _execute(self, request) -> dict[str, Any]:
        order = self.last_order
        self.account_open = True  # a buy creates it; a sell (even of everything) leaves it open
        return {"status": "Success", "signature": f"sig-{request.json['requestId']}", "code": 0,
                "inputAmountResult": order["inAmount"], "outputAmountResult": order["outAmount"]}

    def mark_paper(self) -> None:
        """Paper's virtual wallet starts without the account too (same Ultra script, fresh)."""
        self.account_open = False


@pytest.fixture
def keypair() -> Keypair:
    return Keypair()  # fresh, never funded


def _brokers(make_settings, fake_http, http_client, fake_clock, keypair) -> tuple[Any, PaperBroker, LiveBroker]:
    wallet = load_keypair(b58encode(bytes(keypair)))
    live_settings = make_settings(TRADING_MODE="live", LIVE_CONFIRM=LIVE_CONFIRM_PHRASE,
                                  BOT_WALLET_SECRET=wallet.secret_base58(), DASHBOARD_HOST="127.0.0.1",
                                  PAPER_SLIPPAGE_BPS=0)
    paper_settings = make_settings(PAPER_SLIPPAGE_BPS=0)
    ultra = UltraForOneWallet(fake_http, live_settings.solana_rpc_url, keypair)
    jupiter = JupiterClient(http_client, base_url=live_settings.jupiter_base_url)
    paper = PaperBroker(jupiter, FakeLedger(clock=fake_clock), paper_settings, fake_clock, taker=wallet.pubkey())
    live = LiveBroker(jupiter, SolanaRpc(http_client, url=live_settings.solana_rpc_url), wallet,
                      FakeLedger(clock=fake_clock), live_settings, fake_clock)
    return ultra, paper, live


def _apply(position: Position | None, fill: Fill) -> Position:
    """The engine's bookkeeping, reduced to what rent needs (amounts and locked rent per position)."""
    if position is None:
        position = Position(id=f"pos-{fill.mode}", mint=fill.mint, symbol="HIGGS", pool=None, opened_at=fill.ts,
                            token_decimals=fill.token_decimals)
    position.token_amount += fill.token_amount if fill.side == "buy" else -fill.token_amount
    position.rent_lamports += fill.rent_lamports
    if position.token_amount == 0:
        position.status = "closed"
    return position


def _trade(broker: Any) -> list[tuple[Fill, Position]]:
    """Buy, sell half, sell the rest (full exit), buy again, sell everything again."""
    out: list[tuple[Fill, Position]] = []
    position: Position | None = None
    for step in ("buy", "half", "rest", "buy", "rest"):
        if step == "buy":
            position = None
            fill = broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
        else:
            assert position is not None
            amount = position.token_amount // 2 if step == "half" else position.token_amount
            fill = broker.execute(broker.quote("sell", HIGGS, amount, 6), position)
        position = _apply(position, fill)
        out.append((fill, Position.from_dict(position.to_dict())))
    return out


def test_paper_and_live_book_token_account_rent_identically(make_settings, fake_http, http_client, fake_clock,
                                                            keypair) -> None:
    ultra, paper, live = _brokers(make_settings, fake_http, http_client, fake_clock, keypair)
    live_run = _trade(live)
    ultra.mark_paper()
    paper_run = _trade(paper)

    expected = [OPENING_RENT, 0, 0, 0, 0]  # opening buy only; the account outlives the exit
    assert [f.rent_lamports for f, _ in live_run] == expected
    assert [f.rent_lamports for f, _ in paper_run] == expected
    for (pf, pp), (lf, lp) in zip(paper_run, live_run, strict=True):
        assert (pf.side, pf.sol_lamports, pf.token_amount, pf.rent_lamports) == \
               (lf.side, lf.sol_lamports, lf.token_amount, lf.rent_lamports)
        assert (pp.token_amount, pp.rent_lamports, pp.status) == (lp.token_amount, lp.rent_lamports, lp.status)
        assert pf.fees_lamports >= lf.fees_lamports  # paper's network fee is the conservative floor
    # the closed first position carries its rent as a cost in both modes (P&L counts locked rent)
    assert paper_run[2][1].rent_lamports == live_run[2][1].rent_lamports == OPENING_RENT
    assert paper.ledger.get_kv("paper.rent") == {HIGGS: OPENING_RENT}


def _quote(side: str, rent: int) -> Quote:
    return Quote(side=side, input_mint=SOL_MINT if side == "buy" else HIGGS,  # type: ignore[arg-type]
                 output_mint=HIGGS if side == "buy" else SOL_MINT, in_amount=1, out_amount=1, price_impact_pct=0.0,
                 fee_bps=10, route_labels=[], request_id="r", transaction_b64=None, quoted_at=0.0, in_usd=None,
                 out_usd=None, rent_fee_lamports=rent)


@pytest.mark.parametrize("side, rent, account_open, expected", [
    ("buy", 2_976_880, False, 2_976_880),  # Ultra's figure for a new account
    ("buy", 0, False, TOKEN_ACCOUNT_RENT_LAMPORTS),  # Ultra could not tell (no taker): the model value
    ("buy", 2_976_880, True, 0),  # the account already exists
    ("buy", 0, True, 0),
    ("sell", 0, True, 0),  # a sell, even of everything, never refunds: the account stays open
    ("sell", 123, True, 0),
])
def test_the_shared_rent_rule(side: str, rent: int, account_open: bool, expected: int) -> None:
    assert token_rent_lamports(_quote(side, rent), account_open=account_open) == expected


@pytest.mark.parametrize("rent", [OPENING_RENT, 0])
def test_a_buy_sized_to_all_the_spendable_sol_still_fits_the_rent_the_broker_books(make_settings, fake_clock,
                                                                                 rent: int) -> None:
    """Sizing must leave room for the rent the brokers really book: Ultra's ``rentFeeLamports`` for a new
    Token-2022 (pump.fun) account is above the 165-byte model. A buy capped by the available SOL still
    fits in the paper wallet (else InsufficientBalance) - and live, it never eats into SOL_RESERVE."""
    from nightcrawler.broker.paper import _PaperWallet
    from nightcrawler.models import LAMPORTS_PER_SOL
    from nightcrawler.risk import RiskManager

    settings = make_settings()
    available = (settings.sol_reserve_lamports + settings.network_fee_lamports + TOKEN_ACCOUNT_RENT_LAMPORTS
                 + 50_000_000)  # the SOL left caps the size
    size = RiskManager(settings, None, fake_clock).size_position(10 * LAMPORTS_PER_SOL, 150.0,
                                                                 available_lamports=available)
    assert size > 0
    wallet = _PaperWallet(sol_lamports=available, tokens={}, rent={})
    quote = dataclasses.replace(_quote("buy", rent), in_amount=size, out_amount=10**9)
    booked = wallet.buy(quote, 10**9, settings.network_fee_lamports, settings.sol_reserve_lamports)
    assert booked == token_rent_lamports(quote, account_open=False)
    assert wallet.sol_lamports >= settings.sol_reserve_lamports
