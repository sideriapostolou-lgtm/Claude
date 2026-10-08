"""PaperBroker: fills priced from Jupiter Ultra quotes, exact fee/rent model, persistence.

Also hosts :class:`FakeLedger`, an in-memory stand-in that follows the
``nightcrawler.ledger.Ledger`` contract (signatures checked against the real
class below); ``test_broker_live`` and ``test_risk`` import it from here.
"""

from __future__ import annotations

import contextlib
import copy
import inspect
import json
import threading
from typing import Any, Iterator

import pytest

from fakes import FakeClock, load_fixture
from nightcrawler.broker.base import (
    Broker,
    InsufficientBalance,
    QuoteRejected,
    SolPriceCache,
    implied_sol_usd,
    swap_mints,
)
from nightcrawler.broker.paper import (
    BASE_FEE_LAMPORTS,
    MAX_PAPER_NETWORK_FEE_LAMPORTS,
    PRIORITY_FEE_REFRESH_S,
    SWAP_COMPUTE_UNITS,
    PaperBroker,
)
from nightcrawler.clock import RealClock
from nightcrawler.hashing import GENESIS_HASH, normalize_payload, receipt_hash, verify_receipts
from nightcrawler.http import HttpClient, HttpError
from nightcrawler.ledger import Ledger, LedgerError
from nightcrawler.models import (
    LAMPORTS_PER_SOL,
    SOL_MINT,
    TOKEN_ACCOUNT_RENT_LAMPORTS,
    EquityPoint,
    Fill,
    Position,
    Receipt,
    effective_price_usd,
)
from nightcrawler.sources.jupiter import JupiterClient, quote_from_order
from nightcrawler.sources.solana_rpc import (
    JUPITER_PROGRAM_ID,
    PUMPSWAP_PROGRAM_ID,
    SWAP_FEE_ACCOUNT_KEYS,
    RpcError,
    SolanaRpc,
)

HIGGS = "DoVAVzViX8Bjy3r15nwikSaSbzE6dV4ovd28aWpJpump"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_USD = 108.31695332710045  # jup_price_v3.json
BUY_IN, BUY_OUT = 100_000_000, 16_239_400_281  # jup_ultra_order_buy.json
SELL_OUT = 98_445_289  # jup_ultra_order_sell.json (sells BUY_OUT tokens)
FEE = 300_000  # NETWORK_FEE_SOL default 0.0003
RESERVE = 20_000_000  # SOL_RESERVE default 0.02


# --------------------------------------------------------------------------- fake ledger


class FakeLedger:
    """In-memory ledger with the contract's semantics: JSON kv, hash-chained receipts,
    atomic (rollback-on-error) transactions, fills, positions and equity points.

    ``fail_next[method] = exc`` makes the next call of ``method`` raise ``exc``.
    """

    def __init__(self, path: Any = ":memory:", clock: Any | None = None) -> None:
        self.clock = clock if clock is not None else FakeClock()
        self.fail_next: dict[str, BaseException] = {}
        self._lock = threading.RLock()
        self._depth = 0
        self._kv: dict[str, str] = {}
        self._receipts: list[Receipt] = []
        self._fills: dict[str, Fill] = {}
        self._positions: dict[str, Position] = {}
        self._equity: list[EquityPoint] = []

    def _maybe_fail(self, method: str) -> None:
        exc = self.fail_next.pop(method, None)
        if exc is not None:
            raise exc

    def close(self) -> None:
        pass

    # kv ------------------------------------------------------------------
    def get_kv(self, key: str, default: Any = None) -> Any:
        return json.loads(self._kv[key]) if key in self._kv else default

    def set_kv(self, key: str, value: Any) -> None:
        self._maybe_fail("set_kv")
        self._kv[key] = json.dumps(value)

    @contextlib.contextmanager
    def transaction(self) -> Iterator[FakeLedger]:
        with self._lock:
            outer = self._depth == 0
            state = ("_kv", "_receipts", "_fills", "_positions", "_equity")
            snapshot = {name: copy.deepcopy(getattr(self, name)) for name in state} if outer else None
            self._depth += 1
            try:
                yield self
            except BaseException:
                if snapshot is not None:
                    for name, value in snapshot.items():
                        setattr(self, name, value)
                raise
            finally:
                self._depth -= 1

    # receipts --------------------------------------------------------------
    def append_receipt(self, kind: str, payload: dict[str, Any], ts: float | None = None) -> Receipt:
        with self._lock:
            payload = normalize_payload(payload)
            ts = round(self.clock.now() if ts is None else ts, 3)
            seq, prev = self.head()
            receipt = Receipt(seq + 1, ts, kind, payload, prev, receipt_hash(prev, seq + 1, ts, kind, payload))
            self._receipts.append(receipt)
            return receipt

    def head(self) -> tuple[int, str]:
        return (self._receipts[-1].seq, self._receipts[-1].hash) if self._receipts else (0, GENESIS_HASH)

    def receipt_count(self) -> int:
        return len(self._receipts)

    def receipts(self, after_seq: int = 0, limit: int | None = None) -> list[Receipt]:
        out = [r for r in self._receipts if r.seq > after_seq]
        return out[:limit] if limit is not None else out

    def verify_chain(self) -> tuple[bool, int | None]:
        return verify_receipts(self._receipts)

    # records -----------------------------------------------------------------
    def record_fill(self, fill: Fill) -> Fill:
        with self.transaction():
            self._maybe_fail("record_fill")
            if fill.id in self._fills:
                raise LedgerError(f"duplicate fill id {fill.id}")
            receipt = self.append_receipt("fill", fill.to_dict(), ts=fill.ts)
            stored = Fill.from_dict({**fill.to_dict(), "receipt_hash": receipt.hash})
            self._fills[fill.id] = stored
            return stored

    def record_swap_failure(self, payload: dict[str, Any]) -> Receipt:
        return self.append_receipt("swap_failed", payload)

    def fills(self, limit: int | None = 50, mint: str | None = None, since: float | None = None,
              position_id: str | None = None) -> list[Fill]:
        out = [f for f in reversed(self._fills.values())
               if (mint is None or f.mint == mint) and (since is None or f.ts >= since)
               and (position_id is None or f.position_id == position_id)]
        return out[:limit] if limit is not None else out

    def upsert_position(self, position: Position) -> None:
        self._positions[position.id] = copy.deepcopy(position)

    def open_positions(self, mode: str | None = None) -> list[Position]:
        return sorted((p for p in self._positions.values() if p.is_open and (mode is None or p.mode == mode)),
                      key=lambda p: p.opened_at)

    def last_closed_at(self, mint: str) -> float | None:
        closed = [p.closed_at for p in self._positions.values() if p.mint == mint and p.closed_at is not None]
        return max(closed) if closed else None

    def record_equity(self, point: EquityPoint) -> None:
        self._equity.append(point)
        self._equity.sort(key=lambda p: p.ts)

    def equity_series(self, since: float | None = None, limit: int | None = None) -> list[EquityPoint]:
        out = [p for p in self._equity if since is None or p.ts >= since]
        return out[:limit] if limit is not None else out

    def latest_equity(self) -> EquityPoint | None:
        return self._equity[-1] if self._equity else None


FAKE_LEDGER_METHODS = (
    "get_kv", "set_kv", "transaction", "append_receipt", "head", "receipt_count", "receipts", "verify_chain",
    "record_fill", "record_swap_failure", "fills", "upsert_position", "open_positions", "last_closed_at",
    "record_equity", "equity_series", "latest_equity",
)


def test_fake_ledger_matches_the_ledger_contract() -> None:
    for name in FAKE_LEDGER_METHODS:
        real = list(inspect.signature(getattr(Ledger, name)).parameters)
        fake = list(inspect.signature(getattr(FakeLedger, name)).parameters)
        assert fake == real, name


def test_fake_ledger_transaction_rolls_back_everything() -> None:
    ledger = FakeLedger()
    ledger.set_kv("a", 1)
    with pytest.raises(RuntimeError), ledger.transaction():
        ledger.set_kv("a", 2)
        ledger.append_receipt("note", {"x": 1})
        raise RuntimeError("boom")
    assert ledger.get_kv("a") == 1
    assert ledger.head() == (0, GENESIS_HASH)


# --------------------------------------------------------------------------- helpers


def order_route(fixture: str, **overrides: Any):
    """FakeHttp responder: the Ultra fixture re-scaled to the requested amount (+ overrides)."""
    base = load_fixture(fixture)

    def respond(request) -> dict[str, Any]:
        amount = int(request.params["amount"])
        body = {**base, **overrides}
        body["inAmount"] = str(amount)
        body["outAmount"] = str(int(base["outAmount"]) * amount // int(base["inAmount"]))
        if "otherAmountThreshold" not in overrides:  # keep Ultra's min-out consistent with the scaled amount
            body["otherAmountThreshold"] = str(int(base["otherAmountThreshold"]) * amount // int(base["inAmount"]))
        return body

    return respond


@pytest.fixture
def ledger(fake_clock: FakeClock) -> FakeLedger:
    return FakeLedger(clock=fake_clock)


@pytest.fixture
def jupiter_http(fake_http):
    fake_http.register_fixture("/price/v3", "jup_price_v3")
    fake_http.register(f"inputMint={SOL_MINT}", order_route("jup_ultra_order_buy"))
    fake_http.register(f"outputMint={SOL_MINT}", order_route("jup_ultra_order_sell"))
    return fake_http


@pytest.fixture
def make_broker(jupiter_http, http_client, ledger, fake_clock, make_settings):
    def _make(taker: str | None = None, rpc: Any = None, **settings: Any) -> PaperBroker:
        settings.setdefault("PAPER_SLIPPAGE_BPS", 0)  # these tests pin the exact fee/rent model
        s = make_settings(**settings)
        jupiter = JupiterClient(http_client, base_url=s.jupiter_base_url)
        return PaperBroker(jupiter, ledger, s, fake_clock, taker=taker, rpc=rpc)

    return _make


@pytest.fixture
def broker(make_broker) -> PaperBroker:
    return make_broker()


def start_lamports(usd: float = 100.0) -> int:
    return int(usd / SOL_USD * LAMPORTS_PER_SOL)


def fill_receipts(ledger: FakeLedger) -> list[Receipt]:
    return [r for r in ledger.receipts() if r.kind == "fill"]


def open_position(fill: Fill, decimals: int = 6) -> Position:
    return Position(id="pos_1", mint=fill.mint, symbol="HIGGS", pool=None, opened_at=fill.ts,
                    token_decimals=decimals, token_amount=fill.token_amount)


# --------------------------------------------------------------------------- tests


def test_paper_broker_implements_the_broker_protocol(broker) -> None:
    assert isinstance(broker, Broker)
    assert broker.mode == "paper"


def test_first_start_converts_paper_start_usd_at_live_sol_price(broker, ledger) -> None:
    balances = broker.balances()
    assert balances.sol_lamports == start_lamports()
    assert balances.tokens == {}
    assert ledger.get_kv("paper.start_lamports") == start_lamports()
    assert ledger.get_kv("paper.start_sol_usd") == pytest.approx(SOL_USD)
    (note,) = ledger.receipts()
    assert note.kind == "note" and note.payload["event"] == "paper_start"
    assert note.payload["start_lamports"] == start_lamports()


def test_buy_fills_exactly_at_the_quote_with_network_fee_and_rent(broker, ledger) -> None:
    quote = broker.quote("buy", HIGGS, BUY_IN, 6)
    fill = broker.execute(quote, None, symbol="HIGGS")

    assert (fill.sol_lamports, fill.token_amount) == (BUY_IN, BUY_OUT)
    assert fill.expected_out_amount == BUY_OUT
    assert fill.fees_lamports == FEE
    assert fill.rent_lamports == TOKEN_ACCOUNT_RENT_LAMPORTS
    assert fill.platform_fee_bps == 10
    assert fill.price_impact_pct == pytest.approx(2.1957373766982126)
    assert fill.price_usd == pytest.approx(effective_price_usd(BUY_IN, BUY_OUT, 6, SOL_USD))
    assert (fill.mode, fill.side, fill.mint, fill.symbol) == ("paper", "buy", HIGGS, "HIGGS")
    assert fill.signature is None
    assert fill.request_id == "01a11c56-cfde-72ec-a552-db4ef3aa8c67"
    assert fill.position_id is None

    balances = broker.balances()
    assert balances.sol_lamports == start_lamports() - BUY_IN - FEE - TOKEN_ACCOUNT_RENT_LAMPORTS
    assert balances.tokens == {HIGGS: BUY_OUT}
    assert ledger.get_kv("paper.rent") == {HIGGS: TOKEN_ACCOUNT_RENT_LAMPORTS}

    (receipt,) = fill_receipts(ledger)
    assert fill.receipt_hash == receipt.hash == ledger.head()[1]
    assert receipt.payload["id"] == fill.id and receipt.payload["receipt_hash"] is None
    assert ledger.verify_chain() == (True, None)


def test_round_trip_keeps_the_rent_locked_like_live_and_costs_fees_spread_and_rent(broker, ledger) -> None:
    """ACC-8: Ultra's full-balance sell does NOT close the token account (verified 2026-10-08: its
    transaction closes only the temporary wSOL account), so live never gets the rent back on an exit.
    Paper books exactly what live books: rent on the opening buy, nothing back on the sell."""
    buy = broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    sell = broker.execute(broker.quote("sell", HIGGS, BUY_OUT, 6), open_position(buy))

    assert (sell.sol_lamports, sell.token_amount) == (SELL_OUT, BUY_OUT)
    assert sell.rent_lamports == 0
    assert sell.position_id == "pos_1" and sell.symbol == "HIGGS"
    final = broker.balances()
    assert final.tokens == {}
    assert final.sol_lamports == start_lamports() - BUY_IN - 2 * FEE - TOKEN_ACCOUNT_RENT_LAMPORTS + SELL_OUT
    assert final.sol_lamports - start_lamports() == buy.sol_delta_lamports() + sell.sol_delta_lamports()
    assert ledger.get_kv("paper.rent") == {HIGGS: TOKEN_ACCOUNT_RENT_LAMPORTS}  # the empty account holds it


def test_partial_and_full_sells_book_no_rent(broker) -> None:
    buy = broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    half = BUY_OUT // 2
    first = broker.execute(broker.quote("sell", HIGGS, half, 6), open_position(buy))
    assert first.rent_lamports == 0
    assert broker.balances().tokens == {HIGGS: BUY_OUT - half}

    rest = broker.execute(broker.quote("sell", HIGGS, BUY_OUT - half, 6), None)
    assert rest.rent_lamports == 0
    assert broker.balances().tokens == {}


def test_rebuying_a_mint_whose_account_is_still_open_pays_no_new_rent(broker, ledger) -> None:
    buy = broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    broker.execute(broker.quote("sell", HIGGS, BUY_OUT, 6), open_position(buy))
    again = broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert again.rent_lamports == 0  # live: the account still exists, Ultra reports no rent
    assert ledger.get_kv("paper.rent") == {HIGGS: TOKEN_ACCOUNT_RENT_LAMPORTS}
    assert broker.balances().tokens == {HIGGS: BUY_OUT}


def test_opening_buy_books_the_rent_ultra_reports(broker, jupiter_http, ledger) -> None:
    """With a taker, Ultra reports what opening the account really costs (Token-2022 accounts are bigger
    than the 165-byte model); paper books that, like live. Without it, the model value."""
    jupiter_http.register(f"inputMint={SOL_MINT}", order_route("jup_ultra_order_buy", rentFeeLamports=2_976_880))
    buy = broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert buy.rent_lamports == 2_976_880
    assert ledger.get_kv("paper.rent") == {HIGGS: 2_976_880}
    assert broker.balances().sol_lamports == start_lamports() - BUY_IN - FEE - 2_976_880
    add = broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert add.rent_lamports == 0  # the account exists in the virtual wallet: nothing to open


def test_adding_to_a_held_mint_pays_no_second_rent(broker) -> None:
    broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    add = broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert add.rent_lamports == 0
    assert broker.balances().tokens == {HIGGS: 2 * BUY_OUT}


def test_insufficient_funds_quote_is_still_valid_for_paper(make_broker, jupiter_http) -> None:
    jupiter_http.register(f"inputMint={SOL_MINT}", order_route("jup_ultra_order_buy_insufficient_funds"))
    broker = make_broker()
    quote = broker.quote("buy", HIGGS, BUY_IN, 6)
    assert quote.is_insufficient_funds
    assert broker.execute(quote, None).token_amount == 16_239_400_280


def test_any_other_ultra_error_rejects_the_quote(broker, jupiter_http) -> None:
    jupiter_http.register(f"inputMint={SOL_MINT}", order_route(
        "jup_ultra_order_buy", errorCode=3, errorMessage="No routes found", error="No routes found"))
    with pytest.raises(QuoteRejected, match="No routes found"):
        broker.quote("buy", HIGGS, BUY_IN, 6)


def test_price_impact_above_the_limit_is_rejected(make_broker) -> None:
    broker = make_broker(MAX_PRICE_IMPACT_PCT=2.0)
    with pytest.raises(QuoteRejected, match=r"price impact 2\.20% > max 2\.00%"):
        broker.quote("buy", HIGGS, BUY_IN, 6)
    # a per-call override (e.g. an emergency exit) can loosen the cap explicitly
    assert broker.quote("buy", HIGGS, BUY_IN, 6, max_impact_pct=5.0).out_amount == BUY_OUT


def test_buy_may_spend_down_to_exactly_the_sol_reserve_but_never_into_it(broker, ledger) -> None:
    broker.balances()
    exact = BUY_IN + FEE + TOKEN_ACCOUNT_RENT_LAMPORTS + RESERVE
    ledger.set_kv("paper.sol_lamports", exact - 1)
    with pytest.raises(InsufficientBalance, match="reserve"):
        broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert broker.balances().sol_lamports == exact - 1
    assert fill_receipts(ledger) == []

    ledger.set_kv("paper.sol_lamports", exact)
    broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert broker.balances().sol_lamports == RESERVE


def test_small_bankroll_cannot_buy_through_the_reserve(make_broker, ledger) -> None:
    broker = make_broker(PAPER_START_USD=12)  # ~0.11 SOL: 0.1 SOL + reserve + fee + rent does not fit
    with pytest.raises(InsufficientBalance):
        broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert broker.balances().sol_lamports == start_lamports(12)


def test_selling_more_than_held_is_refused(broker) -> None:
    broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    with pytest.raises(InsufficientBalance):
        broker.execute(broker.quote("sell", HIGGS, BUY_OUT + 1, 6), None)
    assert broker.balances().tokens == {HIGGS: BUY_OUT}


def test_stale_quote_is_rejected_without_state_change(broker, fake_clock) -> None:
    quote = broker.quote("buy", HIGGS, BUY_IN, 6)
    before = broker.balances()
    fake_clock.advance(15.5)
    with pytest.raises(QuoteRejected, match="stale quote"):
        broker.execute(quote, None)
    assert broker.balances() == before


def test_a_quote_fills_at_most_once(broker, ledger) -> None:
    quote = broker.quote("buy", HIGGS, BUY_IN, 6)
    broker.execute(quote, None)
    with pytest.raises(QuoteRejected, match="already executed"):
        broker.execute(quote, None)
    assert len(fill_receipts(ledger)) == 1


def test_quotes_not_issued_by_the_broker_are_refused(broker, fake_clock) -> None:
    foreign = quote_from_order(load_fixture("jup_ultra_order_buy"), "buy", fake_clock.now())
    with pytest.raises(QuoteRejected, match="not issued by this broker"):
        broker.execute(foreign, None)


def test_position_for_another_mint_is_refused(broker) -> None:
    buy = broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    wrong = open_position(buy)
    wrong.mint = USDC
    with pytest.raises(QuoteRejected, match="is for"):
        broker.execute(broker.quote("sell", HIGGS, BUY_OUT, 6), wrong)


def test_restart_resumes_virtual_balances_without_network(make_broker, jupiter_http) -> None:
    first = make_broker()
    first.execute(first.quote("buy", HIGGS, BUY_IN, 6), None)
    expected = first.balances()

    jupiter_http.reset_calls()
    second = make_broker()  # same ledger, fresh process
    assert second.balances() == expected
    assert jupiter_http.calls == []


def test_balances_and_fill_are_written_atomically(broker, ledger) -> None:
    before, head = broker.balances(), ledger.head()
    quote = broker.quote("buy", HIGGS, BUY_IN, 6)
    ledger.fail_next["set_kv"] = RuntimeError("disk full")
    with pytest.raises(RuntimeError, match="disk full"):
        broker.execute(quote, None)
    assert broker.balances() == before
    assert ledger.head() == head
    assert ledger.fills() == []
    # nothing was consumed: the same (still fresh) quote can be retried once storage works
    assert broker.execute(quote, None).token_amount == BUY_OUT


def test_quotes_use_the_configured_taker(make_broker, jupiter_http) -> None:
    make_broker(taker="FBZ4MxMyVYrba5JyJCAqLS5B5p2wjw5fykTXBTU8gA1o").quote("buy", HIGGS, BUY_IN, 6)
    make_broker().quote("buy", HIGGS, BUY_IN, 6)
    with_taker, without = jupiter_http.calls_to("/ultra/v1/order")
    assert with_taker.params["taker"] == "FBZ4MxMyVYrba5JyJCAqLS5B5p2wjw5fykTXBTU8gA1o"
    assert "taker" not in without.params
    assert with_taker.params["amount"] == str(BUY_IN)


def test_sol_price_is_cached_for_sixty_seconds(broker, jupiter_http, fake_clock) -> None:
    assert broker.sol_price_usd() == pytest.approx(SOL_USD)
    fake_clock.advance(60)
    broker.sol_price_usd()
    assert len(jupiter_http.calls_to("/price/v3")) == 1
    fake_clock.advance(1)
    broker.sol_price_usd()
    assert len(jupiter_http.calls_to("/price/v3")) == 2


def test_fill_uses_the_quote_sol_valuation_when_the_price_feed_is_down(broker, jupiter_http, fake_clock) -> None:
    broker.balances()
    fake_clock.advance(61)
    jupiter_http.register("/price/v3", {"error": "bad request"}, status=400)
    quote = broker.quote("buy", HIGGS, BUY_IN, 6)
    fill = broker.execute(quote, None)
    assert fill.sol_usd == pytest.approx(implied_sol_usd(quote)) == pytest.approx(108.85650682171027)


def test_reset_starts_over_and_puts_it_on_the_receipt_chain(broker, ledger) -> None:
    broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    balances = broker.reset(50)
    assert balances.sol_lamports == start_lamports(50) and balances.tokens == {}
    note = ledger.receipts()[-1]
    assert note.kind == "note" and note.payload["event"] == "paper_reset"
    assert note.payload["previous"]["tokens"] == {HIGGS: BUY_OUT}
    assert ledger.verify_chain() == (True, None)


def test_bad_inputs_fail_before_any_request(broker, jupiter_http) -> None:
    with pytest.raises(ValueError):
        broker.quote("buy", HIGGS, BUY_IN, -1)
    with pytest.raises(ValueError):
        broker.quote("hold", HIGGS, BUY_IN, 6)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        broker.quote("buy", SOL_MINT, BUY_IN, 9)
    assert jupiter_http.calls_to("/ultra/v1/order") == []


def test_shared_helpers() -> None:
    assert swap_mints("buy", HIGGS) == (SOL_MINT, HIGGS)
    assert swap_mints("sell", HIGGS) == (HIGGS, SOL_MINT)
    sell = quote_from_order(load_fixture("jup_ultra_order_sell"), "sell", 0.0)
    assert implied_sol_usd(sell) == pytest.approx(10.713814630989086 / (SELL_OUT / LAMPORTS_PER_SOL))

    class CountingJupiter:
        calls = 0

        def sol_price_usd(self) -> float:
            self.calls += 1
            return 100.0

    clock, jupiter = FakeClock(), CountingJupiter()
    cache = SolPriceCache(jupiter, clock, ttl_s=10)
    assert cache.get() == cache.get() == 100.0 and jupiter.calls == 1


@pytest.mark.live
def test_live_smoke_paper_round_trip_on_real_ultra_quotes(make_settings) -> None:
    """Opt-in (NIGHTCRAWLER_LIVE_TESTS=1): real Ultra quotes, virtual money only."""
    settings = make_settings()
    clock = RealClock()
    http = HttpClient.from_settings(settings, clock=clock)
    jupiter = JupiterClient(http, base_url=settings.jupiter_base_url, api_key=settings.jupiter_api_key)
    broker = PaperBroker(jupiter, FakeLedger(clock=clock), settings, clock)

    buy = broker.execute(broker.quote("buy", USDC, 10_000_000, 6), None)  # 0.01 SOL -> USDC
    sell = broker.execute(broker.quote("sell", USDC, buy.token_amount, 6), None)
    round_trip = (buy.sol_lamports - sell.sol_lamports) / buy.sol_lamports
    paper_haircut = 2 * settings.paper_slippage_bps / 10_000  # PAPER_SLIPPAGE_BPS on each side
    # ~0.2 % Ultra fees on a deep pool plus the deliberate paper haircut, before network fees
    assert paper_haircut <= round_trip < paper_haircut + 0.01
    assert broker.balances().tokens == {}


# --------------------------------------------------------------------------- review fixes: quote sanity


def test_quote_for_another_mint_or_amount_than_requested_is_rejected(broker, jupiter_http) -> None:
    other = "So1anaOtherMint1111111111111111111111111111"
    jupiter_http.register(f"inputMint={SOL_MINT}", order_route("jup_ultra_order_buy", outputMint=other))
    with pytest.raises(QuoteRejected, match="does not match the request"):
        broker.quote("buy", HIGGS, BUY_IN, 6)
    bigger = load_fixture("jup_ultra_order_buy") | {"inAmount": str(BUY_IN * 5)}
    jupiter_http.register(f"inputMint={SOL_MINT}", bigger)
    with pytest.raises(QuoteRejected, match="does not match the request"):
        broker.quote("buy", HIGGS, BUY_IN, 6)


@pytest.mark.parametrize("field", ["outAmount", "inAmount"])
def test_quote_with_a_zero_amount_is_rejected(broker, jupiter_http, field) -> None:
    body = load_fixture("jup_ultra_order_buy") | {field: "0"}
    jupiter_http.register(f"inputMint={SOL_MINT}", body)
    with pytest.raises(QuoteRejected):
        broker.quote("buy", HIGGS, BUY_IN if field == "outAmount" else BUY_IN, 6)


def test_buy_quote_without_any_price_impact_field_fails_closed(broker, jupiter_http) -> None:
    body = {k: v for k, v in load_fixture("jup_ultra_order_buy").items() if k not in ("priceImpactPct", "priceImpact")}
    jupiter_http.register(f"inputMint={SOL_MINT}", body)
    with pytest.raises(QuoteRejected, match="price impact unknown"):
        broker.quote("buy", HIGGS, BUY_IN, 6)
    jupiter_http.register(f"inputMint={SOL_MINT}", body | {"priceImpactPct": "NaN"})
    with pytest.raises(QuoteRejected, match="price impact unknown"):
        broker.quote("buy", HIGGS, BUY_IN, 6)


def test_buy_quote_losing_more_usd_value_than_the_cap_is_rejected(broker, jupiter_http) -> None:
    body = load_fixture("jup_ultra_order_buy")
    lossy = body | {"priceImpactPct": "-0.00001", "priceImpact": -0.001, "outUsdValue": body["inUsdValue"] * 0.8}
    jupiter_http.register(f"inputMint={SOL_MINT}", lossy)
    with pytest.raises(QuoteRejected, match=r"USD value lost 20\.00%"):
        broker.quote("buy", HIGGS, BUY_IN, 6)


def test_buy_with_a_wide_ultra_min_out_is_rejected_but_a_forced_sell_is_not(make_broker, jupiter_http) -> None:
    broker = make_broker(MAX_SLIPPAGE_PCT=3.0)
    base = load_fixture("jup_ultra_order_buy")
    wide = base | {"slippageBps": 500, "otherAmountThreshold": str(int(int(base["outAmount"]) * 0.95))}
    jupiter_http.register(f"inputMint={SOL_MINT}", wide)
    with pytest.raises(QuoteRejected, match=r"slippage 5\.00% > MAX_SLIPPAGE_PCT 3\.00%"):
        broker.quote("buy", HIGGS, BUY_IN, 6)
    sell = load_fixture("jup_ultra_order_sell")
    jupiter_http.register(f"outputMint={SOL_MINT}",
                          sell | {"slippageBps": 500, "otherAmountThreshold": str(int(int(sell["outAmount"]) * 0.95))})
    assert broker.quote("sell", HIGGS, BUY_OUT, 6, max_impact_pct=25.0).side == "sell"
    # Ultra's usual taker slippage (1.28 % in the captured fixture) passes the default cap
    assert make_broker().settings.max_slippage_pct == 3.0


def test_on_fill_failure_rolls_back_the_whole_paper_swap(broker, ledger) -> None:
    """The engine's position write runs inside the fill transaction: if it fails, no orphan fill
    and no balance change remain (the next tick simply sees nothing happened)."""
    before = broker.balances()
    quote = broker.quote("buy", HIGGS, BUY_IN, 6)

    def boom(_fill: Fill) -> None:
        raise RuntimeError("position write failed")

    with pytest.raises(RuntimeError, match="position write failed"):
        broker.execute(quote, None, on_fill=boom)
    assert broker.balances() == before and ledger.fills() == [] and fill_receipts(ledger) == []
    applied: list[Fill] = []
    fill = broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None, on_fill=applied.append)
    assert applied == [fill] and ledger.fills() == [fill]


def test_paper_fills_receive_the_configured_slippage_below_the_quote(make_broker, ledger) -> None:
    """Paper must not be the best case: live swaps land below the quote (Ultra slippage, latency,
    MEV). The haircut is visible on the books as ``expected_out_amount`` vs the filled amount."""
    assert make_broker(PAPER_SLIPPAGE_BPS=None).settings.paper_slippage_bps == 100  # the default
    broker = make_broker(PAPER_SLIPPAGE_BPS=100)
    buy = broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert buy.token_amount == BUY_OUT * 9_900 // 10_000 and buy.expected_out_amount == BUY_OUT
    assert broker.balances().tokens[HIGGS] == buy.token_amount
    sold = broker.execute(broker.quote("sell", HIGGS, buy.token_amount, 6), open_position(buy))
    quoted = SELL_OUT * buy.token_amount // BUY_OUT
    assert sold.expected_out_amount == quoted and sold.sol_lamports == quoted * 9_900 // 10_000


# --------------------------------------------------------------------------- network fee from live priority fees

HELIUS_URL = "https://mainnet.helius-rpc.com/?api-key=0123456789abcdef0123"


class FakeFeeRpc:
    """``SolanaRpc.priority_fee_levels`` stand-in: scripted levels (micro-lamports per CU) or an exception."""

    def __init__(self, high: Any = 2_000_000.0) -> None:
        self.answer: Any = {"low": 10.0, "medium": 1_000.0, "high": high, "veryHigh": 9e9}
        self.calls: list[tuple[str, ...]] = []

    def priority_fee_levels(self, account_keys: Any = SWAP_FEE_ACCOUNT_KEYS) -> dict[str, float]:
        self.calls.append(tuple(account_keys))
        if isinstance(self.answer, BaseException):
            raise self.answer
        return dict(self.answer)


def test_paper_network_fee_is_the_floor_without_a_helius_rpc(make_broker) -> None:
    rpc = FakeFeeRpc()
    broker = make_broker(rpc=rpc)  # public mainnet RPC: no getPriorityFeeEstimate there
    buy = broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert buy.fees_lamports == FEE and rpc.calls == []
    assert make_broker(SOLANA_RPC_URL=HELIUS_URL).network_fee_lamports() == FEE  # Helius but no rpc wired


def test_helius_high_priority_fee_sets_the_paper_network_fee(make_broker) -> None:
    rpc = FakeFeeRpc(high=2_000_000.0)  # micro-lamports per CU
    broker = make_broker(rpc=rpc, SOLANA_RPC_URL=HELIUS_URL)
    expected = BASE_FEE_LAMPORTS + 2_000_000 * SWAP_COMPUTE_UNITS // 1_000_000  # 5_000 + 600_000
    assert expected == 605_000 > FEE
    buy = broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None)
    assert buy.fees_lamports == expected
    assert broker.balances().sol_lamports == start_lamports() - BUY_IN - expected - TOKEN_ACCOUNT_RENT_LAMPORTS
    assert rpc.calls == [(PUMPSWAP_PROGRAM_ID, JUPITER_PROGRAM_ID)]
    sell = broker.execute(broker.quote("sell", HIGGS, BUY_OUT, 6), open_position(buy))
    assert sell.fees_lamports == expected and len(rpc.calls) == 1


def test_network_fee_floor_keeps_paper_conservative(make_broker) -> None:
    rpc = FakeFeeRpc(high=100.0)  # 5_000 + 30 lamports: far below NETWORK_FEE_SOL
    broker = make_broker(rpc=rpc, SOLANA_RPC_URL=HELIUS_URL)
    assert broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None).fees_lamports == FEE
    assert make_broker(rpc=FakeFeeRpc(high=100.0), SOLANA_RPC_URL=HELIUS_URL,
                       NETWORK_FEE_SOL=0.000001).network_fee_lamports() == 5_030


def test_priority_fee_is_fetched_at_most_once_per_five_minutes(make_broker, fake_clock) -> None:
    rpc = FakeFeeRpc(high=2_000_000.0)
    broker = make_broker(rpc=rpc, SOLANA_RPC_URL=HELIUS_URL)
    assert broker.network_fee_lamports() == 605_000
    rpc.answer = {"high": 4_000_000.0}
    fake_clock.advance(PRIORITY_FEE_REFRESH_S - 1)
    assert broker.network_fee_lamports() == 605_000 and len(rpc.calls) == 1
    fake_clock.advance(1)
    assert broker.network_fee_lamports() == 1_205_000 and len(rpc.calls) == 2


@pytest.mark.parametrize("answer", [
    RpcError(-32601, "Method not found", "getPriorityFeeEstimate"),
    HttpError("HTTP 503", url=HELIUS_URL, status=503, retryable=True),
    RuntimeError("anything else"),
    {"low": 1.0, "medium": 2.0},  # no "high" level
    {"high": "garbage"},
    {"high": float("inf")},
    {"high": -5.0},
])
def test_priority_fee_errors_fall_back_to_the_floor_and_wait(make_broker, fake_clock, answer: Any) -> None:
    rpc = FakeFeeRpc()
    rpc.answer = answer
    broker = make_broker(rpc=rpc, SOLANA_RPC_URL=HELIUS_URL)
    assert broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None).fees_lamports == FEE
    assert broker.network_fee_lamports() == FEE and len(rpc.calls) == 1  # an outage costs one call per 5 min
    rpc.answer = {"high": 2_000_000.0}
    fake_clock.advance(PRIORITY_FEE_REFRESH_S)
    assert broker.network_fee_lamports() == 605_000  # recovers on the next refresh


def test_an_absurd_priority_fee_is_capped(make_broker) -> None:
    broker = make_broker(rpc=FakeFeeRpc(high=1e12), SOLANA_RPC_URL=HELIUS_URL)
    assert broker.network_fee_lamports() == MAX_PAPER_NETWORK_FEE_LAMPORTS == 10_000_000  # 0.01 SOL


def test_paper_fee_through_the_real_rpc_client(make_broker, fake_http, http_client) -> None:
    fake_http.register("helius-rpc.com", {"jsonrpc": "2.0", "id": 1,
                                          "result": {"priorityFeeLevels": {"high": 1_500_000.0}}}, method="POST")
    broker = make_broker(rpc=SolanaRpc(http_client, url=HELIUS_URL), SOLANA_RPC_URL=HELIUS_URL)
    assert broker.execute(broker.quote("buy", HIGGS, BUY_IN, 6), None).fees_lamports == 5_000 + 450_000
    (call,) = fake_http.calls_to("helius-rpc.com")
    assert call.json["method"] == "getPriorityFeeEstimate"
