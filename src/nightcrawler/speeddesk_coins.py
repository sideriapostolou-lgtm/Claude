"""Practice-only Kalshi 15-minute desks for coins other than Bitcoin.

Owner, 2026-10-13: "I wanna scale by tonight to other markets but let's perfect it first". Each coin first
earns a practice record here; real money on a coin needs a shared account controller and the owner's numbers.

Nothing in this module can place a real order: it has no account client, key or order path. Each coin reads
public Kalshi market data (no websocket, slow polls) and public Coinbase trades, and runs its own paper desk
with its own ledger, budget and report under DATA_DIR/speeddesk/coins/<coin>. All coins share one thread and
event loop of their own, so the real-money Bitcoin desk never waits on them and keeps nearly all of Kalshi's
request budget.

Three differences from the Bitcoin practice desk, because these coins trade far less often on Coinbase
(2026-10-13 03:51 UTC: a print in about 28 % of seconds for ETH, 22 % SOL, 32 % XRP, 3 % DOGE):
- the opening price is Kalshi's own strike, the 60-second index average each window settles against,
  never a Coinbase print in the start second;
- volatility is the realized variance of consecutive prints per elapsed second over the trailing hour, which
  needs no print every second (on Bitcoin's dense tape it matches the one-second estimate);
- the last price print may be older (``Coin.price_stale_s``); books keep the usual 3-second freshness.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, cast

from .config import Settings
from .ledger import Ledger
from .speeddesk import _atomic_json, practice_config
from .speeddesk_feeds import COINBASE_WS, number, timestamp
from .speeddesk_kalshi import KalshiFeeds
from .speeddesk_model import BitcoinTape, Book, Decision, PracticeDesk, Trade, Window

log = logging.getLogger("nightcrawler.speeddesk_coins")
STATE_KEY = "speeddesk_coin_state"
# A print older than this when it arrives is a replay, not news.
TICK_MAX_DELAY_S = 3.0
# Slow public polls per coin: about one Kalshi request a second for each coin in all.
BOOK_INTERVAL_S, TRADE_INTERVAL_S, METADATA_INTERVAL_S = 2.0, 4.0, 30.0
# Consecutive-print pairs needed in the trailing hour for a volatility estimate (about 1 / sqrt(2n) = 6 %).
SIGMA_MIN_PAIRS = 120
# The Bitcoin desk shares the process: these desks step and save less often to leave it the CPU.
STEP_S, CHECKPOINT_S = 0.5, 15.0


@dataclass(frozen=True)
class Coin:
    key: str
    name: str
    series: str
    index: str  # CF Benchmarks index named in the market rules, lowercase
    product: str  # Coinbase product
    price_stale_s: float


COINS: dict[str, Coin] = {coin.key: coin for coin in (
    Coin("eth", "Ether", "KXETH15M", "ethusdrti", "ETH-USD", 15.0),
    Coin("sol", "Solana", "KXSOL15M", "solusdrti", "SOL-USD", 15.0),
    Coin("xrp", "XRP", "KXXRP15M", "xrpusdrti", "XRP-USD", 15.0),
    Coin("doge", "Dogecoin", "KXDOGE15M", "dogeusdrti", "DOGE-USD", 30.0),
)}


def selected_coins(value: str) -> list[Coin]:
    """The configured coins in a fixed order; unknown names are refused by the settings check."""
    keys = {part.strip().lower() for part in value.split(",") if part.strip()}
    return [coin for key, coin in COINS.items() if key in keys]


class SparseTape(BitcoinTape):
    """A price tape for a coin that does not print every second."""

    def sigma(self, now: float, minimum: int = 100, warmup_s: float = 3600.0) -> float | None:
        if self.started_at is None or now - self.started_at < warmup_s:
            return None
        last_complete = int(now) - 1
        seconds = sorted(second for second in self.prices if last_complete - 3599 <= second <= last_complete)
        pairs = list(itertools.pairwise(seconds))
        elapsed = sum(later - earlier for earlier, later in pairs)
        if len(pairs) < minimum or elapsed <= 0:
            return None
        variance = sum(math.log(self.prices[later] / self.prices[earlier]) ** 2 for earlier, later in pairs)
        return math.sqrt(variance / elapsed)


class CoinDesk(PracticeDesk):
    """The Bitcoin practice desk's rules, with the opening taken from Kalshi's strike only."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.tape = SparseTape()

    def add_window(self, window: Window) -> None:
        existing = self.windows.get(window.slug)
        if window.start_price is None:
            window.start_price = (existing.start_price if existing and existing.start_price is not None
                                  else window.venue_start_price)
        super().add_window(window)

    def tick_btc(self, price: float, at: float) -> None:
        self.tape.tick(price, at)  # never an opening: a Coinbase print is not the settlement index


def coinbase_product_ticks(reply: Any, products: frozenset[str]) -> list[tuple[str, float, float]]:
    """(product, price, exchange time) for each trade of a wanted product, oldest first."""
    if not isinstance(reply, dict) or reply.get("channel") != "market_trades":
        return []
    rows: list[tuple[str, float, float]] = []
    events = reply.get("events")
    for event in events if isinstance(events, list) else []:
        trades = event.get("trades") if isinstance(event, dict) else None
        for trade in trades if isinstance(trades, list) else []:
            product = trade.get("product_id") if isinstance(trade, dict) else None
            if product not in products:
                continue
            price, at = number(trade.get("price")), timestamp(trade.get("time"))
            if price is not None and price > 0 and at is not None:
                rows.append((product, price, at))
    return sorted(rows, key=lambda row: row[2])


class CoinbaseTrades:
    """One public Coinbase connection for every practice coin; separate from the Bitcoin feed."""

    def __init__(self, products: frozenset[str], on_tick: Callable[[str, float, float, float], None], *,
                 clock: Callable[[], float] = time.time, connect: Any = None) -> None:
        self.products, self.on_tick, self._clock, self._connect = products, on_tick, clock, connect
        self.connected = False

    async def run(self, stop: threading.Event) -> None:
        from websockets.asyncio.client import connect

        connect_ws = self._connect or connect
        while not stop.is_set():
            try:
                async with connect_ws(COINBASE_WS, open_timeout=10, ping_interval=20, ping_timeout=10) as ws:
                    for channel in ("market_trades", "heartbeats"):
                        await ws.send(json.dumps({"type": "subscribe", "product_ids": sorted(self.products),
                                                  "channel": channel}))
                    self.connected = True
                    log.info("speeddesk_coins_coinbase_connected products=%s", ",".join(sorted(self.products)))
                    while not stop.is_set():
                        reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                        received_at = self._clock()
                        for product, price, at in coinbase_product_ticks(reply, self.products):
                            self.on_tick(product, price, at, received_at)
            except Exception as exc:  # noqa: BLE001 — reconnect on any transport or protocol failure.
                self.connected = False
                log.warning("speeddesk_coins_coinbase_disconnected error=%s", type(exc).__name__)
                await asyncio.sleep(2)


class _Clock:
    def __init__(self, now: Callable[[], float]) -> None:
        self.now = now


class CoinRunner:
    """One coin's paper desk: its own ledger, state mirror, budget, report and public Kalshi feed."""

    def __init__(self, settings: Settings, coin: Coin, *, clock: Callable[[], float] = time.time,
                 feed_factory: Callable[..., Any] = KalshiFeeds) -> None:
        self.coin, self.clock = coin, clock
        self.directory = settings.data_dir / "speeddesk" / "coins" / coin.key
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "state.json"
        self.ledger = Ledger(self.directory / "receipts.db", _Clock(clock))
        self.pending: list[tuple[str, dict[str, Any]]] = []
        self.feed_status: dict[str, Any] = {"markets": "connecting", "trade_stream": False, "maker_windows": []}
        self.last_checkpoint = self.last_heartbeat = -math.inf
        self.problem: str | None = None
        config = replace(practice_config(settings), sigma_min_samples=SIGMA_MIN_PAIRS)
        try:
            saved = self.ledger.get_kv(STATE_KEY)
            if saved is None and self.path.exists():
                raise ValueError("Coin practice ledger missing beside an existing report")
            if saved is not None:
                if saved.get("version") != 1 or saved.get("coin") != coin.key:
                    raise ValueError("Unsupported coin practice state")
                self.desk = cast(CoinDesk, CoinDesk.from_state(saved["model"], config))
                self.started_at = float(saved["started_at"])
                for order in saved["model"].get("orders", []):
                    self.record("speeddesk_cancel", {**order, "at": clock(), "reason": "restart"})
            else:
                self.desk = CoinDesk(config)
                self.started_at = clock()
            self.desk.price_stale_s = coin.price_stale_s
            self.feeds = feed_factory(settings, on_tick=lambda *_: None, on_book=self.on_book,
                                      on_trade=self.on_trade, on_windows=self.on_windows,
                                      on_status=self.on_status, clock=clock, series=coin.series,
                                      index=coin.index, websocket=False, book_interval_s=BOOK_INTERVAL_S,
                                      trade_interval_s=TRADE_INTERVAL_S, metadata_interval_s=METADATA_INTERVAL_S)
        except BaseException:
            self.ledger.close()
            raise

    def record(self, kind: str, payload: dict[str, Any]) -> None:
        self.pending.append((kind, {"mode": "practice", "coin": self.coin.key, "venue": "kalshi", **payload}))

    def decisions(self, events: list[Decision]) -> None:
        for event in events:
            if event.event != "speeddesk_skip":
                self.record(event.event, asdict(event))

    def on_tick(self, price: float, event_at: float, received_at: float) -> None:
        if 0 <= received_at - event_at <= TICK_MAX_DELAY_S:
            self.desk.tick_btc(price, event_at)

    def on_book(self, book: Book) -> None:
        if self.desk.on_book(book):
            self.decisions(self.desk.advance(self.clock()))

    def on_trade(self, trade: Trade) -> None:
        if self.feed_status.get("trade_stream") and trade.window in set(self.feed_status.get("maker_windows", [])):
            self.decisions(self.desk.on_trade(trade, self.clock()))

    def on_windows(self, windows: list[Window]) -> None:
        for window in windows:
            previous = self.desk.windows.get(window.slug)
            terms = ("taker_coefficient", "maker_coefficient", "tick_size", "min_trade_qty", "fee_rounding")
            if previous is not None and any(getattr(previous, key) != getattr(window, key) for key in terms):
                self.decisions(self.desk.cancel(self.clock(), window.slug, "venue_terms_changed"))
                self.desk.books = {key: book for key, book in self.desk.books.items() if key[0] != window.slug}
            self.desk.add_window(window)

    def on_status(self, status: dict[str, Any]) -> None:
        self.feed_status.update(status)

    def step(self, now: float) -> None:
        makers = set(self.feed_status.get("maker_windows", [])) if self.feed_status.get("trade_stream") else set()
        self.decisions(self.desk.evaluate(now, makers_enabled=bool(makers), maker_windows=makers))
        if now - self.last_heartbeat >= 60:
            self.record("speeddesk_coin_status", {"at": now, **self.panel(now)})
            self.last_heartbeat = now
        if now - self.last_checkpoint >= CHECKPOINT_S or any(
                kind in ("speeddesk_take", "speeddesk_fill", "speeddesk_window") for kind, _ in self.pending):
            self.checkpoint(now)

    async def settle_closed(self) -> None:
        closed = {item.window for item in self.desk.closed}
        for window in list(self.desk.windows.values()):
            if window.slug in closed or self.clock() < window.end:
                continue
            outcome = await self.feeds.settlement(window.slug)
            if outcome not in (0.0, 1.0):
                continue
            now = self.clock()
            self.decisions(self.desk.cancel(now, window.slug, "settled"))
            result = self.desk.settle(window.slug, outcome == 1.0, now)
            if result is not None:
                self.record("speeddesk_window", {**asdict(result), "at": now})
                self.checkpoint(now)

    def _totals(self) -> dict[str, float]:
        days = self.desk.venue_days.get("kalshi", {}).values()
        return {key: sum(day.get(source, 0.0) for day in days) for key, source in (
            ("pnl_usd", "pnl_usd"), ("locked_usd", "locked_usd"), ("directional_usd", "direction_usd"),
            ("settled_windows", "windows"), ("windows", "windows_traded"), ("fills", "fills"))}

    def panel(self, now: float) -> dict[str, Any]:
        tape = self.desk.tape
        age = None if tape.last_at is None else max(0.0, now - tape.last_at)
        sigma = tape.sigma(now, self.desk.config.sigma_min_samples, self.desk.config.sigma_warmup_s)
        current = [window for window in self.desk.windows.values() if window.start <= now < window.end]
        reason = self.desk.last_reason.get(current[0].slug, "") if current else "No current window"
        if self.problem:
            status = self.problem
        elif sigma is None:
            status = "Warming up volatility (needs an hour of prices)"
        else:
            status = "Practice running"
        return {"coin": self.coin.key, "name": self.coin.name, "series": self.coin.series, "mode": "practice",
                "real_orders": False, "as_of": now, "started_at": self.started_at, "status": status,
                "reason": reason, "price": tape.price, "price_age_s": age, "volatility_ready": sigma is not None,
                "markets": self.feed_status.get("markets"), "trade_stream": bool(self.feed_status.get("trade_stream")),
                "today": self.desk.daily_summary(now, venue="kalshi"), "total": self._totals()}

    def checkpoint(self, now: float) -> None:
        state = {"version": 1, "mode": "practice", "coin": self.coin.key, "started_at": self.started_at,
                 "updated_at": now, "model": self.desk.to_state(), "panel": self.panel(now)}
        with self.ledger.transaction():
            for kind, payload in self.pending:
                self.ledger.append_receipt(kind, payload, ts=payload.get("at", now))
            self.ledger.set_kv(STATE_KEY, state)
        for kind, payload in self.pending:
            if kind not in ("speeddesk_coin_status", "speeddesk_rest", "speeddesk_cancel"):
                log.info("%s %s", kind, json.dumps(payload, allow_nan=False, separators=(",", ":")))
        self.pending.clear()
        _atomic_json(self.path, state)
        self.last_checkpoint = now

    def close(self) -> None:
        self.ledger.close()


def panels(data_dir: Path) -> list[dict[str, Any]]:
    """The saved report of each practice coin, for the page; a missing or broken one is left out."""
    out: list[dict[str, Any]] = []
    for coin in COINS.values():
        try:
            state = json.loads((data_dir / "speeddesk" / "coins" / coin.key / "state.json").read_text("utf-8"))
        except (OSError, ValueError):
            continue
        panel = state.get("panel") if isinstance(state, dict) else None
        if isinstance(panel, dict) and state.get("coin") == coin.key and state.get("mode") == "practice":
            out.append(panel)
    return out


async def run_coins(runners: list[CoinRunner], stop: threading.Event, *,
                    clock: Callable[[], float] = time.time, coinbase: CoinbaseTrades | None = None) -> None:
    by_product = {runner.coin.product: runner for runner in runners}

    def on_tick(product: str, price: float, at: float, received_at: float) -> None:
        runner = by_product.get(product)
        if runner is not None:
            runner.on_tick(price, at, received_at)

    feed = coinbase or CoinbaseTrades(frozenset(by_product), on_tick, clock=clock)
    for runner in runners:
        runner.record("speeddesk_coin_started", {"at": clock(), "real_orders": False, "series": runner.coin.series,
                                                 "config": asdict(runner.desk.config)})
        runner.checkpoint(clock())

    async def settlements() -> None:
        while not stop.is_set():
            for runner in runners:
                await runner.settle_closed()
            await asyncio.sleep(15)

    tasks = [asyncio.create_task(feed.run(stop)), asyncio.create_task(settlements()),
             *(asyncio.create_task(runner.feeds.run(stop)) for runner in runners)]
    try:
        while not stop.is_set():
            for task in tasks:
                if task.done():
                    task.result()
                    if not stop.is_set():
                        raise RuntimeError("Coin practice background task exited")
            now = clock()
            for runner in runners:
                runner.step(now)
            await asyncio.sleep(STEP_S)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for runner in runners:
            runner.decisions(runner.desk.cancel(clock(), reason="shutdown"))
            runner.checkpoint(clock())


def run_coin_desks(settings: Settings, stop: threading.Event) -> None:
    """Engine thread entry point. A practice fault here never touches the Bitcoin desk or real money."""
    runners: list[CoinRunner] = []
    try:
        runners = [CoinRunner(settings, coin) for coin in selected_coins(settings.speeddesk_coins)]
        if runners:
            log.info("speeddesk_coins_started mode=PRACTICE coins=%s", ",".join(r.coin.key for r in runners))
            asyncio.run(run_coins(runners, stop))
    except Exception as exc:  # noqa: BLE001 — isolate practice; log no exception text.
        log.error("speeddesk_coins_halted mode=PRACTICE error=%s", type(exc).__name__)
        for runner in runners:
            runner.problem = "Practice desk halted; inspect speeddesk_coins logs"
            try:
                runner.checkpoint(time.time())
            except Exception:  # noqa: BLE001 — keep the original durable state if storage failed.
                log.error("speeddesk_coins_state_unavailable coin=%s", runner.coin.key)
    finally:
        for runner in runners:
            runner.close()
