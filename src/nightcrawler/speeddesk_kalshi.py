"""Public, read-only Kalshi adapter for the practice speed desk.

Current KXBTC15M rules and https://kalshi.com/docs/kalshi-fee-schedule.pdf
(effective July 7, 2026) were checked against public responses on October 12.
REST prints are actual trades, never inferred from price touches. Coinbase
ticks come from the shared feed adapter.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any, TypeGuard
from urllib.parse import urlencode

from .config import Settings
from .speeddesk_feeds import number, thread_session, timestamp
from .speeddesk_kalshi_ws import KalshiMarketWS
from .speeddesk_model import Book, Level, Trade, Window

log = logging.getLogger("nightcrawler.speeddesk_kalshi")
API = "https://api.elections.kalshi.com/trade-api/v2"
SERIES = "KXBTC15M"


def valid_ticker(value: Any, series: str = SERIES) -> TypeGuard[str]:
    return isinstance(value, str) and re.fullmatch(re.escape(series) + r"-[A-Z0-9]+-[0-9]{2}", value) is not None


def parse_window(raw: Any, series: Any, now: float, *, name: str = SERIES, index: str = "brti") -> Window | None:
    """One verified 15-minute window of the ``name`` series, settled on CF Benchmarks' ``index``."""
    if not isinstance(raw, dict) or not isinstance(series, dict):
        return None
    slug = raw.get("ticker")
    start, end = timestamp(raw.get("open_time")), timestamp(raw.get("close_time"))
    rules = str(raw.get("rules_primary") or "").lower()
    multiplier = number(series.get("fee_multiplier"))
    fee_type = series.get("fee_type")
    if (not valid_ticker(slug, name) or start is None or end is None or end - start != 900
            or start not in (math.floor(now / 900) * 900, math.floor(now / 900) * 900 + 900)
            or series.get("ticker") != name or series.get("frequency") != "fifteen_min"
            or raw.get("market_type") != "binary" or raw.get("notional_value_dollars") != "1.0000"
            or raw.get("status") not in ("active", "initialized")
            or raw.get("strike_type") not in (None, "greater_or_equal")
            or f"cf benchmarks' {index}" not in rules or "simple average of the sixty seconds" not in rules
            or "is at least" not in rules or "resolves to yes" not in rules
            or multiplier is None or not 0 <= multiplier <= 10
            or fee_type not in ("quadratic", "quadratic_with_maker_fees")):
        return None
    ranges = raw.get("price_ranges")
    # A penny grid is valid in each observed band, including the finer .001
    # tails. Using this subset avoids inventing a price outside the venue grid.
    if not isinstance(ranges, list) or not ranges:
        return None
    for band in ranges:
        step = number(band.get("step")) if isinstance(band, dict) else None
        if step is None or step <= 0 or abs(0.01 / step - round(0.01 / step)) > 1e-7:
            return None
    strike = number(raw.get("floor_strike"))
    shard = raw.get("exchange_index")
    shard = shard if type(shard) is int and shard >= 0 else None
    return Window(slug=slug, start=start, end=end, start_price=None,
                  venue_start_price=strike if strike and strike > 0 else None,
                  taker_coefficient=0.07 * multiplier,
                  maker_coefficient=0.0175 * multiplier if fee_type == "quadratic_with_maker_fees" else 0.0,
                  tick_size=0.01, min_trade_qty=0.01, fee_rounding="kalshi", venue="kalshi",
                  exchange_index=shard)


def _levels(raw: Any) -> tuple[Level, ...] | None:
    if not isinstance(raw, list):
        return None
    levels: dict[float, float] = {}
    for row in raw:
        if not isinstance(row, list) or len(row) != 2:
            return None
        price, size = number(row[0]), number(row[1])
        if (price is None or size is None or not 0 < price < 1 or size < 0
                or abs(size * 100 - round(size * 100)) > 1e-6):
            return None
        if size:
            levels[price] = levels.get(price, 0.0) + size
    return tuple(Level(price, size) for price, size in sorted(levels.items(), reverse=True))


def parse_books(reply: Any, ticker: str, received_at: float, *, series: str = SERIES) -> tuple[Book, ...]:
    raw = reply.get("orderbook_fp") if isinstance(reply, dict) else None
    if not valid_ticker(ticker, series) or not isinstance(raw, dict):
        return ()
    yes, no = _levels(raw.get("yes_dollars")), _levels(raw.get("no_dollars"))
    if yes is None or no is None:
        return ()
    if yes and no and yes[0].price + no[0].price >= 1:
        yes, no = (), ()
    sequence = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return (
        Book(ticker, "up", yes, tuple(Level(round(1 - row.price, 8), row.size) for row in no),
             received_at, sequence, None, "rest"),
        Book(ticker, "down", no, tuple(Level(round(1 - row.price, 8), row.size) for row in yes),
             received_at, sequence, None, "rest"),
    )


def parse_trades(rows: Any, ticker: str, received_at: float, *, series: str = SERIES) -> tuple[Trade, ...]:
    if not isinstance(rows, list) or not valid_ticker(ticker, series):
        return ()
    out: list[Trade] = []
    for raw in rows:
        if (not isinstance(raw, dict) or raw.get("ticker") != ticker
                or raw.get("is_block_trade") is not False or not isinstance(raw.get("trade_id"), str)
                or not raw["trade_id"]):
            continue
        yes, no, size = (number(raw.get(key)) for key in ("yes_price_dollars", "no_price_dollars", "count_fp"))
        at = timestamp(raw.get("created_time"))
        direction = raw.get("taker_outcome_side")
        book_side = raw.get("taker_book_side")
        if (yes is None or no is None or size is None or at is None or not 0 < yes < 1
                or not 0 < no < 1 or abs(yes + no - 1) > 1e-7 or size <= 0
                or abs(size * 100 - round(size * 100)) > 1e-6
                or (direction, book_side) not in (("yes", "bid"), ("no", "ask"))):
            continue
        # Official OpenAPI: yes/bid = buy-yes or sell-no; no/ask = buy-no or sell-yes.
        identity = "kalshi:" + raw["trade_id"]
        out.extend((Trade(ticker, "up", yes, size, at, identity + ":up",
                          "buy" if direction == "yes" else "sell", received_at),
                    Trade(ticker, "down", no, size, at, identity + ":down",
                          "sell" if direction == "yes" else "buy", received_at)))
    return tuple(sorted(out, key=lambda trade: (trade.at, trade.trade_id)))


def _public_get(path: str) -> Any:
    response = thread_session().get(API + path, timeout=8)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


class KalshiFeeds:
    """Public REST plus optional authenticated market WS; no account/order client."""

    def __init__(self, settings: Settings, *, on_tick: Callable[[float, float, float], None],
                 on_book: Callable[[Book], None], on_trade: Callable[[Trade], None],
                 on_windows: Callable[[list[Window]], None], on_status: Callable[[dict[str, Any]], None],
                 clock: Callable[[], float] = time.time, rest_get: Callable[[str], Any] | None = None,
                 ws_connect: Callable[..., Any] | None = None, series: str = SERIES, index: str = "brti",
                 websocket: bool = True, book_interval_s: float = 0.5, trade_interval_s: float = 1.0,
                 metadata_interval_s: float = 15.0) -> None:
        # Another coin's practice feed passes its own series and index, no websocket and slower polls, so the
        # real-money Bitcoin desk keeps the account's websocket and nearly all of Kalshi's request budget.
        self.series, self.index = series, index
        self.book_interval_s, self.trade_interval_s = book_interval_s, trade_interval_s
        self.metadata_interval_s = metadata_interval_s
        self.on_book, self.on_trade = on_book, on_trade
        self.on_windows, self.on_status = on_windows, on_status
        self._clock, self._get = clock, rest_get or _public_get
        self.windows: dict[str, Window] = {}
        self._last_book = -math.inf
        self._last_trades = -math.inf
        self._book_index = 0
        self._tape_since: dict[str, float] = {}
        self._rest_trade_at: dict[str, float] = {}
        self._transport: dict[str, str] = {}
        self._ws_status: dict[str, Any] = {}
        self._ws: KalshiMarketWS | None = None
        if (websocket and settings.speeddesk_kalshi_ws_enabled and settings.kalshi_key_id
                and settings.kalshi_private_key):
            self._ws = KalshiMarketWS(settings, tickers=lambda: frozenset(self.windows), on_book=self._ws_book,
                                     on_trade=self.on_trade, on_status=self._ws_report, clock=clock,
                                     ws_connect=ws_connect)
        self._status: dict[str, Any] = {"markets": "connecting_public_rest", "trade_stream": False,
                                       "venue": "kalshi", "transport": "public_rest"}

    def _report(self, **changes: Any) -> None:
        changes.setdefault("gap_windows", [])
        self._status.update(changes)
        self.on_status(dict(self._status))

    def _publish(self, **changes: Any) -> None:
        now = self._clock()
        rest = {slug for slug, at in self._rest_trade_at.items()
                if slug in self.windows and self._transport.get(slug) != "websocket" and 0 <= now - at <= 3}
        websocket = set(self._ws_status.get("ws_maker_windows", [])) & set(self.windows)
        makers = sorted(rest | websocket)
        self._report(**{**self._ws_status, "maker_windows": makers, "trade_stream": bool(makers),
                        "transport": "market_websocket" if self._ws_status.get("ws_books") else "public_rest",
                        "gap_windows": [], **changes})

    def _ws_report(self, status: dict[str, Any]) -> None:
        self._ws_status = {key: value for key, value in status.items() if key != "gap_windows"}
        gaps = status.get("gap_windows", [])
        for ticker in gaps:
            self._rest_trade_at.pop(ticker, None)
        self._publish(gap_windows=gaps)

    def _deliver_book(self, book: Book) -> None:
        if book.window not in self.windows:
            return
        previous = self._transport.get(book.window)
        if previous is not None and previous != book.source:
            # A fresh REST view or reconnect cannot carry old queue priority
            # across a transport gap, even when the prices happen to match.
            self._rest_trade_at.pop(book.window, None)
            self._publish(gap_windows=[book.window])
        self._transport[book.window] = book.source
        self.on_book(book)

    def _ws_book(self, book: Book) -> None:
        if book.window in self.windows:
            self._deliver_book(book)

    async def refresh_windows(self) -> None:
        now = self._clock()
        current = int(now // 900) * 900
        query = urlencode({"series_ticker": self.series, "min_close_ts": current + 1,
                           "max_close_ts": current + 1800, "limit": 100})
        try:
            series_reply, reply = await asyncio.gather(
                asyncio.to_thread(self._get, f"/series/{self.series}"),
                asyncio.to_thread(self._get, f"/markets?{query}"))
            series = series_reply.get("series") if isinstance(series_reply, dict) else None
            rows = reply.get("markets") if isinstance(reply, dict) and not reply.get("cursor") else None
            if not isinstance(rows, list):
                raise TypeError("Incomplete market discovery")
            windows: dict[str, Window] = {}
            for raw in rows:
                window = parse_window(raw, series, now, name=self.series, index=self.index)
                if window is None:
                    continue
                event = raw.get("event_ticker")
                if not isinstance(event, str) or not re.fullmatch(re.escape(self.series) + r"-[A-Z0-9]+", event):
                    continue
                # Unknown event overrides must not silently inherit a cheaper
                # series fee. The current public series has no such overrides.
                fees = await asyncio.to_thread(self._get, "/events/fee_changes?" + urlencode({"event_ticker": event}))
                if (not isinstance(fees, dict) or fees.get("cursor")
                        or fees.get("event_fee_changes") != []):
                    log.warning("speeddesk_feed_kalshi_fee_override_unverified window=%s", window.slug)
                    continue
                windows[window.slug] = window
            if set(windows) != set(self.windows):
                self._rest_trade_at.clear()
                self._report(trade_stream=False, maker_windows=[], gap_windows=sorted(self.windows))
            self.windows = windows
            self.on_windows(list(windows.values()))
            self._report(markets="public_rest" if windows else "no_verified_windows")
        except Exception as exc:  # noqa: BLE001 — failed metadata disables this venue; no fabricated rules.
            self._rest_trade_at.clear()
            self._report(markets="metadata_unavailable", trade_stream=False, maker_windows=[],
                         gap_windows=sorted(self.windows))
            self.windows = {}
            self.on_windows([])
            log.warning("speeddesk_feed_kalshi_metadata_failed error=%s", type(exc).__name__)

    async def poll_book(self) -> bool:
        now = self._clock()
        current = [window for window in self.windows.values() if window.start <= now < window.end]
        fresh = self._ws.fresh_books() if self._ws else frozenset()
        current = [window for window in current if window.slug not in fresh]
        if now - self._last_book < self.book_interval_s or not current:
            return False
        window = current[self._book_index % len(current)]
        self._book_index += 1
        self._last_book = now

        def fetch() -> tuple[Any, float]:
            requested_at = self._clock()
            self._last_book = requested_at
            return self._get(f"/markets/{window.slug}/orderbook"), requested_at

        try:
            reply, requested_at = await asyncio.to_thread(fetch)
            books = parse_books(reply, window.slug, self._clock(), series=self.series)
            if not books:
                raise ValueError("Invalid book")
            # An older REST request must not replace a newer WS snapshot.
            if self._ws is None or window.slug not in self._ws.fresh_books():
                for book in books:
                    self._deliver_book(replace(book, requested_at=requested_at))
        except Exception as exc:  # noqa: BLE001 — gaps cancel simulated makers and retain unknown depth.
            # A pending fallback failure cannot invalidate a retired window or
            # a fresh WS book already delivered for this same ticker.
            active = window.slug in self.windows and not (
                self._transport.get(window.slug) == "websocket" and self._ws is not None
                and window.slug in self._ws.fresh_books())
            if active:
                self._rest_trade_at.pop(window.slug, None)
                self._publish(markets="book_unavailable", gap_windows=[window.slug])
            log.warning("speeddesk_feed_kalshi_book_failed error=%s invalidated=%s", type(exc).__name__, active)
        return True

    async def poll_trades(self) -> bool:
        now = self._clock()
        current = [window for window in self.windows.values() if window.start <= now < window.end]
        current = [window for window in current if window.slug not in self._ws_status.get("ws_maker_windows", [])]
        if now - self._last_trades < self.trade_interval_s or not current:
            return False
        self._last_trades = now
        window = current[0]
        since = self._tape_since.get(window.slug, now - 1)
        params: dict[str, Any] = {"ticker": window.slug, "min_ts": int(since) - 1,
                                  "max_ts": int(now), "limit": 1000}
        rows: list[Any] = []
        try:
            for _ in range(5):
                reply = await asyncio.to_thread(self._get, "/markets/trades?" + urlencode(params))
                if not isinstance(reply, dict) or not isinstance(reply.get("trades"), list):
                    raise TypeError("Invalid tape")
                rows.extend(reply["trades"])
                cursor = reply.get("cursor")
                if not cursor:
                    break
                params["cursor"] = cursor
            else:
                raise ValueError("Tape pagination gap")
            received_at = self._clock()
            if window.slug not in self.windows:
                return True
            trades = parse_trades(rows, window.slug, received_at, series=self.series)
            # Missing prints cannot be reconstructed. New queue positions are
            # enabled only after a complete poll contains an actual fresh print.
            if any(received_at - 3 <= trade.at <= received_at for trade in trades):
                self._rest_trade_at[window.slug] = max(trade.at for trade in trades)
            self._publish(markets="market_websocket" if self._ws_status.get("ws_books") else "public_rest")
            for trade in trades:
                self.on_trade(trade)
            self._tape_since[window.slug] = float(int(now))
            self._tape_since = {slug: stamp for slug, stamp in self._tape_since.items() if slug in self.windows}
        except Exception as exc:  # noqa: BLE001 — never fill makers across an incomplete tape.
            # Tape recovery needs both the delivered WS book and a real recent
            # print. Cached status cannot prove either remains fresh now.
            active = window.slug in self.windows and not (
                self._transport.get(window.slug) == "websocket" and self._ws is not None
                and window.slug in self._ws.fresh_maker_windows())
            if active:
                self._tape_since[window.slug] = now
                self._rest_trade_at.pop(window.slug, None)
                self._publish(markets="trade_tape_gap", gap_windows=[window.slug])
            log.warning("speeddesk_feed_kalshi_trade_gap error=%s invalidated=%s", type(exc).__name__, active)
        return True

    async def settlement(self, slug: str) -> float | None:
        if not valid_ticker(slug, self.series):
            return None
        try:
            reply = await asyncio.to_thread(self._get, f"/markets/{slug}")
        except Exception as exc:  # noqa: BLE001 — await an explicit venue finalization.
            log.warning("speeddesk_feed_kalshi_settlement_failed error=%s", type(exc).__name__)
            return None
        raw = reply.get("market") if isinstance(reply, dict) else None
        if not isinstance(raw, dict) or raw.get("ticker") != slug or raw.get("status") != "finalized":
            return None
        result, value = raw.get("result"), number(raw.get("settlement_value_dollars"))
        if result not in ("yes", "no") or value != (1.0 if result == "yes" else 0.0):
            return None
        return value

    async def run(self, stop: threading.Event) -> None:
        log.info("speeddesk_feed_kalshi_started mode=MARKET_DATA series=%s websocket=%s books_max_hz=%s",
                 self.series, self._ws is not None, round(1 / self.book_interval_s, 2))

        async def metadata() -> None:
            while True:
                await self.refresh_windows()
                await asyncio.sleep(self.metadata_interval_s)

        async def books() -> None:
            while True:
                await self.poll_book()
                await asyncio.sleep(0.05)

        async def trades() -> None:
            while True:
                await self.poll_trades()
                await asyncio.sleep(0.1)

        tasks = [asyncio.create_task(job()) for job in (metadata, books, trades)]
        if self._ws is not None:
            tasks.append(asyncio.create_task(self._ws.run(stop)))
        try:
            while not stop.is_set():
                for task in tasks:
                    if task.done() and task.exception() is not None:
                        raise RuntimeError("Kalshi feed task stopped") from task.exception()
                await asyncio.sleep(0.1)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._report(markets="stopped", trade_stream=False, maker_windows=[], gap_windows=sorted(self.windows))
