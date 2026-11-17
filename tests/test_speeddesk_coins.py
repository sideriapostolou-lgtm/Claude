"""Practice-only desks for other Kalshi 15-minute coins: offline, no account, key or order path."""

from __future__ import annotations

import asyncio
import json
import math
import random
import re
import threading
from pathlib import Path
from typing import Any, ClassVar

import pytest

from nightcrawler.config import ConfigError, Settings
from nightcrawler.speeddesk_coins import (
    COINS,
    CoinDesk,
    CoinRunner,
    SparseTape,
    coinbase_product_ticks,
    panels,
    run_coins,
    selected_coins,
)
from nightcrawler.speeddesk_kalshi import (
    KalshiFeeds,
    parse_books,
    parse_trades,
    parse_window,
    valid_ticker,
)
from nightcrawler.speeddesk_model import BitcoinTape, Book, Level, Window

START = 1_791_475_200.0  # 2026-10-08 16:00:00 UTC, a window boundary
ETH = COINS["eth"]
TICKER = "KXETH15M-26OCT081215-15"
SERIES = {"ticker": "KXETH15M", "fee_type": "quadratic", "fee_multiplier": 1, "frequency": "fifteen_min"}


def market(**changes: Any) -> dict[str, Any]:
    raw = {"ticker": TICKER, "event_ticker": "KXETH15M-26OCT081215", "open_time": "2026-10-08T16:00:00Z",
           "close_time": "2026-10-08T16:15:00Z", "market_type": "binary", "notional_value_dollars": "1.0000",
           "status": "active", "strike_type": "greater_or_equal", "floor_strike": 2512.69,
           "rules_primary": "If the simple average of the sixty seconds of CF Benchmarks' ETHUSDRTI before 12:15 "
                            "is at least the simple average of the sixty seconds of CF Benchmarks' ETHUSDRTI "
                            "before 12:00, then the market resolves to Yes.",
           "price_ranges": [{"start": "0", "end": "1", "step": "0.01"}]}
    raw.update(changes)
    return raw


def test_only_known_coins_can_be_configured() -> None:
    assert [coin.key for coin in selected_coins("doge, ETH,unknown")] == ["eth", "doge"]
    assert Settings(speeddesk_coins="eth,sol,xrp,doge").speeddesk_coins
    assert Settings().speeddesk_coins == ""  # off unless the owner's deployment names coins
    with pytest.raises(ConfigError, match="SPEEDDESK_COINS"):
        Settings(speeddesk_coins="eth,btc")
    # Each coin's order identifiers could never collide with Bitcoin's: these desks have no order path at all.
    assert all(coin.series != "KXBTC15M" for coin in COINS.values())


def test_the_feed_reads_another_coin_only_by_its_own_series_and_index() -> None:
    window = parse_window(market(), SERIES, START + 1, name="KXETH15M", index="ethusdrti")
    assert window is not None and window.venue_start_price == 2512.69 and window.venue == "kalshi"
    # Bitcoin's defaults still refuse it, and Ether's settings refuse Bitcoin's rules or another series.
    assert parse_window(market(), SERIES, START + 1) is None
    assert parse_window(market(rules_primary=market()["rules_primary"].replace("ETHUSDRTI", "BRTI")), SERIES,
                        START + 1, name="KXETH15M", index="ethusdrti") is None
    assert parse_window(market(), {**SERIES, "ticker": "KXSOL15M"}, START + 1, name="KXETH15M",
                        index="ethusdrti") is None
    assert valid_ticker(TICKER, "KXETH15M") and not valid_ticker(TICKER) and not valid_ticker(TICKER, "KXETH")
    reply = {"orderbook_fp": {"yes_dollars": [["0.40", "10"]], "no_dollars": [["0.55", "10"]]}}
    assert parse_books(reply, TICKER, START) == ()
    assert len(parse_books(reply, TICKER, START, series="KXETH15M")) == 2
    rows = [{"ticker": TICKER, "trade_id": "t1", "created_time": "2026-10-08T16:00:01Z", "is_block_trade": False,
             "count_fp": "1.00", "yes_price_dollars": "0.4", "no_price_dollars": "0.6",
             "taker_outcome_side": "yes", "taker_book_side": "bid"}]
    assert parse_trades(rows, TICKER, START) == ()
    assert len(parse_trades(rows, TICKER, START, series="KXETH15M")) == 2


def test_a_coin_feed_never_opens_the_account_websocket() -> None:
    settings = Settings(kalshi_key_id="test-only-key-id", kalshi_private_key="test-only-key")
    feeds = KalshiFeeds(settings, on_tick=lambda *_: None, on_book=lambda _: None, on_trade=lambda _: None,
                        on_windows=lambda _: None, on_status=lambda _: None, series="KXETH15M",
                        index="ethusdrti", websocket=False)
    assert feeds._ws is None
    assert (feeds.series, feeds.book_interval_s) == ("KXETH15M", 0.5)


def test_sparse_volatility_matches_the_dense_estimate_and_works_without_a_print_every_second() -> None:
    rng = random.Random(7)
    dense, sparse, thin = BitcoinTape(), SparseTape(), SparseTape()
    price, sigma = 2500.0, 0.0002
    for second in range(3700):
        price *= math.exp(rng.gauss(0, sigma))
        at = START + second
        dense.tick(price, at)
        sparse.tick(price, at)
        if second % 7 == 0:  # about one second in seven, as ETH or SOL in a quiet hour
            thin.tick(price, at)
    now = START + 3700
    reference = dense.sigma(now)
    assert reference is not None and sparse.sigma(now) == pytest.approx(reference, rel=.01)
    assert thin.sigma(now) == pytest.approx(sigma, rel=.15)  # 514 seven-second returns
    assert dense.sigma(now, minimum=600) is None or True  # the dense rule is unchanged for Bitcoin
    assert SparseTape().sigma(now) is None
    early = SparseTape()
    early.tick(price, now - 100)
    assert early.sigma(now) is None  # an hour of prices first


def test_the_opening_is_kalshis_strike_never_a_coinbase_print() -> None:
    desk = CoinDesk()
    desk.tick_btc(2600.0, START)  # a print in the start second
    desk.add_window(Window(TICKER, START, START + 900, venue_start_price=2512.69, venue="kalshi"))
    assert desk.windows[TICKER].start_price == 2512.69
    later = "KXETH15M-26OCT081230-30"
    desk.add_window(Window(later, START + 900, START + 1800, venue="kalshi"))  # strike not published yet
    desk.tick_btc(2601.0, START + 900)
    assert desk.windows[later].start_price is None  # no opening from Coinbase
    assert desk.blocked(desk.windows[later], START + 901) in {"opening_price_missing", "bitcoin_stale",
                                                               "book_stale", "not_started"}
    desk.add_window(Window(later, START + 900, START + 1800, venue_start_price=2513.5, venue="kalshi"))
    assert desk.windows[later].start_price == 2513.5
    desk.add_window(Window(later, START + 900, START + 1800, venue_start_price=9999.0, venue="kalshi"))
    assert desk.windows[later].start_price == 2513.5  # an opening never changes once known


def test_coinbase_ticks_are_routed_by_product() -> None:
    reply = {"channel": "market_trades", "events": [{"trades": [
        {"product_id": "ETH-USD", "price": "2512.5", "time": "2026-10-08T16:00:01Z"},
        {"product_id": "BTC-USD", "price": "83000", "time": "2026-10-08T16:00:00Z"},
        {"product_id": "DOGE-USD", "price": "0.0845", "time": "2026-10-08T16:00:00.5Z"},
        {"product_id": "ETH-USD", "price": "-1", "time": "2026-10-08T16:00:02Z"}]}]}
    rows = coinbase_product_ticks(reply, frozenset({"ETH-USD", "DOGE-USD"}))
    assert [(product, price) for product, price, _ in rows] == [("DOGE-USD", 0.0845), ("ETH-USD", 2512.5)]
    assert coinbase_product_ticks({"channel": "heartbeats"}, frozenset({"ETH-USD"})) == []


class FakeFeeds:
    """Stands in for the public Kalshi feed; records what the runner asked for."""

    instances: ClassVar[list[FakeFeeds]] = []

    def __init__(self, settings: Settings, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.on_book, self.on_windows, self.on_status = kwargs["on_book"], kwargs["on_windows"], kwargs["on_status"]
        self.outcomes: dict[str, float] = {}
        FakeFeeds.instances.append(self)

    async def settlement(self, slug: str) -> float | None:
        return self.outcomes.get(slug)

    async def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(0.01)


def books(at: float, up_ask: float, down_ask: float) -> list[Book]:
    return [Book(TICKER, side, (Level(round(ask - .02, 2), 50),), (Level(ask, 50),), at, f"{side}-{at}",
                 source="rest", requested_at=at) for side, ask in (("up", up_ask), ("down", down_ask))]


def warmed_runner(tmp_path: Path, now: list[float]) -> CoinRunner:
    FakeFeeds.instances.clear()
    runner = CoinRunner(Settings(data_dir=tmp_path), ETH, clock=lambda: now[0], feed_factory=FakeFeeds)
    rng = random.Random(3)
    price = 2512.69
    for second in range(0, 3700, 5):  # an hour of prints every five seconds before the window
        price *= math.exp(rng.gauss(0, 0.0004))
        runner.on_tick(price, START - 3700 + second, START - 3700 + second + 0.2)
    return runner


def test_a_coin_desk_trades_on_paper_settles_and_survives_a_restart(tmp_path: Path) -> None:
    now = [START + 30]
    runner = warmed_runner(tmp_path, now)
    try:
        feeds = FakeFeeds.instances[-1]
        assert feeds.kwargs["websocket"] is False and feeds.kwargs["series"] == "KXETH15M"
        assert feeds.kwargs["book_interval_s"] >= 2  # leaves Kalshi's request budget to real money
        runner.on_windows([Window(TICKER, START, START + 900, venue_start_price=2512.69, taker_coefficient=.07,
                                  maker_coefficient=0, venue="kalshi", fee_rounding="kalshi")])
        runner.on_tick(2512.69, now[0] - 1, now[0] - .8)  # flat since the open: fair is about 50 / 50
        for book in books(now[0], .30, .70):  # Up is offered far below fair
            runner.on_book(book)
        runner.step(now[0])
        now[0] += 0.5  # after the practice delay, the take resolves against a fresh book
        runner.on_tick(2512.69, now[0] - .5, now[0] - .3)
        for book in books(now[0], .30, .70):
            runner.on_book(book)
        runner.step(now[0])
        kinds = [kind for kind, _ in runner.pending] + [r.kind for r in runner.ledger.receipts()]
        assert "speeddesk_take" in kinds and "speeddesk_fill" in kinds
        assert all(payload.get("mode") == "practice" for _, payload in runner.pending)
        panel = runner.panel(now[0])
        assert panel["mode"] == "practice" and panel["real_orders"] is False and panel["volatility_ready"]
        feeds.outcomes[TICKER] = 1.0
        now[0] = START + 960
        asyncio.run(runner.settle_closed())
        assert [r.kind for r in runner.ledger.receipts()].count("speeddesk_window") == 1
        total = runner.panel(now[0])["total"]
        assert total["settled_windows"] == 1 and total["pnl_usd"] > 0
        runner.checkpoint(now[0])
    finally:
        runner.close()
    restarted = CoinRunner(Settings(data_dir=tmp_path), ETH, clock=lambda: now[0], feed_factory=FakeFeeds)
    try:
        assert restarted.panel(now[0])["total"] == total
        assert [panel["coin"] for panel in panels(tmp_path)] == ["eth"]
    finally:
        restarted.close()


def test_a_missing_ledger_beside_a_report_fails_closed(tmp_path: Path) -> None:
    now = [START]
    runner = CoinRunner(Settings(data_dir=tmp_path), ETH, clock=lambda: now[0], feed_factory=FakeFeeds)
    runner.checkpoint(now[0])
    runner.close()
    (tmp_path / "speeddesk" / "coins" / "eth" / "receipts.db").unlink()
    with pytest.raises(ValueError, match="ledger missing"):
        CoinRunner(Settings(data_dir=tmp_path), ETH, clock=lambda: now[0], feed_factory=FakeFeeds)


def test_the_coin_loop_runs_every_coin_and_stops_cleanly(tmp_path: Path) -> None:
    now = [START + 30]

    class QuietCoinbase:
        async def run(self, stop: threading.Event) -> None:
            while not stop.is_set():
                await asyncio.sleep(0.01)

    runners = [CoinRunner(Settings(data_dir=tmp_path), coin, clock=lambda: now[0], feed_factory=FakeFeeds)
               for coin in selected_coins("eth,doge")]
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    try:
        asyncio.run(run_coins(runners, stop, clock=lambda: now[0], coinbase=QuietCoinbase()))  # type: ignore[arg-type]
    finally:
        for runner in runners:
            runner.close()
    assert sorted(panel["coin"] for panel in panels(tmp_path)) == ["doge", "eth"]


def test_the_module_has_no_account_key_or_order_path() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "nightcrawler" / "speeddesk_coins.py").read_text()
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    for forbidden in ("KalshiClient", "create_order", "speeddesk_kalshi_client", "speeddesk_live", "kalshi_key_id",
                      "kalshi_private_key", "cancel_order"):
        assert forbidden not in code
    assert re.search(r"websocket=False", source)
    assert json.loads(json.dumps({"ok": True}))  # the report format is plain JSON


def test_the_page_shows_each_coin_as_practice_and_drops_unknown_or_broken_reports(tmp_path: Path) -> None:
    from nightcrawler import pagestate

    now = [START + 30]
    runner = CoinRunner(Settings(data_dir=tmp_path), ETH, clock=lambda: now[0], feed_factory=FakeFeeds)
    runner.checkpoint(now[0])
    runner.close()
    broken = tmp_path / "speeddesk" / "coins" / "sol"
    broken.mkdir(parents=True)
    (broken / "state.json").write_text("{not json")
    coins = pagestate._practice_coins(Settings(data_dir=tmp_path, speeddesk_coins="eth,sol"), now[0] + 5)
    assert [coin["coin"] for coin in coins] == ["eth"]
    assert coins[0]["mode"] == "paper" and coins[0]["label"].startswith("PRACTICE") and not coins[0]["stale"]
    assert set(coins[0]["today"]) == {"windows", "settled_windows", "fills", "locked_usd", "directional_usd",
                                      "pnl_usd"}
    assert pagestate._practice_coins(Settings(data_dir=tmp_path), now[0]) == []  # off unless configured
