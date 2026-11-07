"""Authenticated Kalshi *market data* only; no trading client or account channels.

Protocol checked against Kalshi's quick_start_websockets, websocket-connection,
orderbook-updates and public-trades documentation on 2026-10-12. Authentication
is needed even for these public market channels. Only Ed25519 handshake signing
is implemented here; a market-data connection does not authorize an order.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import os
import threading
import time
from bisect import bisect_left
from collections.abc import Callable
from itertools import count
from typing import Any, TypeGuard

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from websockets.asyncio.client import connect

from .config import Settings
from .speeddesk_feeds import number
from .speeddesk_model import Book, Level, Trade
from .speeddesk_worktrace import WorkTrace, work_span
from .speeddesk_ws_timing import TimingClientConnection

URL = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
PATH = "/trade-api/ws/v2"
STALE_S = 3.0
# From Virginia, Kalshi is about a millisecond away, so its clock routinely reads
# 0-7 ms ahead of ours (2026-10-12). Up to this much "future" is clock difference,
# not bad data; such a time is clamped to receipt so nothing downstream sees it.
CLOCK_SKEW_S = 0.25
log = logging.getLogger("nightcrawler.speeddesk_kalshi_ws")
# The websocket library's DEBUG handshake log includes authentication headers.
# Keep its transport logger disabled even when application diagnostics are on.
_transport_log = logging.getLogger("nightcrawler.kalshi_market_transport")
_transport_log.disabled = True
_reader_ids = count(1)


class MarketDataGap(ValueError):
    """Fixed, nonsecret protocol reason: discard this connection's state."""


def _integer(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _quantity(value: Any, *, signed: bool = False) -> float:
    parsed = number(value)
    if (parsed is None or (not signed and parsed < 0)
            or abs(parsed * 100 - round(parsed * 100)) > 1e-6):
        raise MarketDataGap("invalid_quantity")
    return parsed


def _price(value: Any) -> float:
    parsed = number(value)
    if parsed is None or not 0 < parsed < 1:
        raise MarketDataGap("invalid_price")
    return parsed


def _fresh_ms(value: Any, now: float, domain: str) -> float:
    if not _integer(value):
        raise MarketDataGap(f"timestamp_missing_or_stale:{domain}:missing_or_invalid")
    age = now - value / 1000
    if not -CLOCK_SKEW_S <= age <= STALE_S:
        # Only a fixed timestamp domain and numeric age: never frame contents,
        # credentials, headers or arbitrary server exception text.
        raise MarketDataGap(f"timestamp_missing_or_stale:{domain}:age_s={age:.3f}")
    return float(min(value / 1000, now))


class MarketHandshake:
    """Narrow signer: its only possible signed request is the market WS GET."""

    def __init__(self, settings: Settings) -> None:
        if not settings.kalshi_key_id or not settings.kalshi_private_key:
            raise ValueError("market_credentials_missing")
        self._key_id = settings.kalshi_key_id.reveal()
        key = load_pem_private_key(settings.kalshi_private_key.reveal().replace("\\n", "\n").encode(), None)
        if not isinstance(key, Ed25519PrivateKey):
            raise TypeError("market_key_must_be_ed25519")
        self._key = key

    def headers(self, now: float) -> dict[str, str]:
        stamp = str(int(now * 1000))
        signature = self._key.sign((stamp + "GET" + PATH).encode())
        return {"KALSHI-ACCESS-KEY": self._key_id, "KALSHI-ACCESS-TIMESTAMP": stamp,
                "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode()}


class MarketState:
    """One connection's SID sequences and books, reset after any discontinuity."""

    def __init__(self, tickers: frozenset[str]) -> None:
        self.tickers = tickers
        self.channels: dict[int, str] = {}
        self.sequences: dict[int, int] = {}
        self.depth: dict[str, dict[str, dict[float, float]]] = {}
        self.bids: dict[str, dict[str, tuple[Level, ...]]] = {}
        self.asks: dict[str, dict[str, tuple[Level, ...]]] = {}
        self.book_at: dict[str, float] = {}
        self.trade_at: dict[str, float] = {}
        self.exchange_at: dict[str, float] = {}
        self.unproven: set[str] = set()

    def _snapshot_levels(self, ticker: str) -> None:
        self.bids[ticker], self.asks[ticker] = {}, {}
        for side, levels in self.depth[ticker].items():
            ordered = sorted(levels.items(), reverse=True)
            self.bids[ticker][side] = tuple(Level(price, size) for price, size in ordered)
            self.asks[ticker][side] = tuple(Level(round(1 - price, 8), size) for price, size in ordered)

    def _changed_level(self, ticker: str, side: str, price: float, size: float) -> None:
        """Reuse immutable levels; one delta never rebuilds every other price."""
        bids, asks = self.bids[ticker][side], self.asks[ticker][side]
        index = bisect_left(bids, -price, key=lambda level: -level.price)
        present = index < len(bids) and bids[index].price == price
        if (present and bids[index].size == size) or (not present and size == 0):
            return
        after = index + int(present)
        self.bids[ticker][side] = bids[:index] + ((Level(price, size),) if size else ()) + bids[after:]
        self.asks[ticker][side] = asks[:index] + ((Level(round(1 - price, 8), size),) if size else ()) + asks[after:]

    def apply(self, raw: Any, now: float) -> tuple[tuple[Book, ...], tuple[Trade, ...]]:
        if not isinstance(raw, dict) or not isinstance(raw.get("msg"), dict):
            raise MarketDataGap("invalid_frame")
        kind, msg = raw.get("type"), raw["msg"]
        if kind == "subscribed":
            sid, channel = msg.get("sid"), msg.get("channel")
            identity = raw.get("id")
            expected = {1: "orderbook_delta", 2: "trade"}.get(identity) if _integer(identity) else None
            if (not _integer(sid) or channel != expected or expected is None
                    or sid in self.channels or channel in self.channels.values()):
                raise MarketDataGap("unexpected_subscription")
            self.channels[sid] = channel
            return (), ()
        if kind not in ("orderbook_snapshot", "orderbook_delta", "trade"):
            raise MarketDataGap("unexpected_message")
        sid, seq = raw.get("sid"), raw.get("seq")
        expected = "trade" if kind == "trade" else "orderbook_delta"
        if (not _integer(sid) or not _integer(seq) or self.channels.get(sid) != expected
                or (sid in self.sequences and seq != self.sequences[sid] + 1)):
            raise MarketDataGap("sequence_gap")
        self.sequences[sid] = seq
        ticker = msg.get("market_ticker")
        if ticker not in self.tickers:
            raise MarketDataGap("unexpected_market")
        # Sending time is explicitly optional in Kalshi's schema. Genuine
        # source time can prove a delta/trade fresh without it. Local receipt
        # NEVER supplies the missing post-delay evidence.
        if "sending_ts_ms" in raw:
            _fresh_ms(raw["sending_ts_ms"], now, f"{kind}_network")
        at: float | None
        if kind == "trade":
            at = _fresh_ms(msg.get("ts_ms"), now, "trade_engine")
            yes, no, size = _price(msg.get("yes_price_dollars")), _price(msg.get("no_price_dollars")), _quantity(msg.get("count_fp"))
            side, book_side = msg.get("taker_outcome_side"), msg.get("taker_book_side")
            identity = msg.get("trade_id")
            if (abs(yes + no - 1) > 1e-7 or size <= 0 or not isinstance(identity, str) or not identity
                    or (side, book_side) not in (("yes", "bid"), ("no", "ask"))
                    or ("taker_side" in msg and msg["taker_side"] != side)
                    or not isinstance(msg.get("is_block_trade"), bool)):
                raise MarketDataGap("ambiguous_trade")
            if msg["is_block_trade"]:
                return (), ()
            # An out-of-order print must not consume a new order's queue.
            if at < self.trade_at.get(ticker, -math.inf):
                raise MarketDataGap("trade_time_reversed")
            self.trade_at[ticker] = at
            return (), (Trade(ticker, "up", yes, size, at, "kalshi:" + identity + ":up",
                               "buy" if side == "yes" else "sell", now),
                        Trade(ticker, "down", no, size, at, "kalshi:" + identity + ":down",
                              "sell" if side == "yes" else "buy", now))
        # Snapshot sending_ts_ms is network publication time, not when the
        # underlying book was captured. It cannot prove post-delay liquidity.
        # Also, comparing it with a later delta's earlier engine timestamp
        # falsely reports a reversal despite a valid increasing sequence.
        at = None
        if kind == "orderbook_snapshot":
            depth: dict[str, dict[float, float]] = {"yes": {}, "no": {}}
            for side in ("yes", "no"):
                rows = msg.get(side + "_dollars_fp", [])
                if not isinstance(rows, list):
                    raise MarketDataGap("invalid_snapshot")
                for row in rows:
                    if not isinstance(row, list) or len(row) != 2:
                        raise MarketDataGap("invalid_snapshot")
                    price, size = _price(row[0]), _quantity(row[1])
                    # Explicit use_yes_price=true affects NO snapshots too.
                    price = round(1 - price, 8) if side == "no" else price
                    if price in depth[side]:
                        raise MarketDataGap("duplicate_price")
                    if size:
                        depth[side][price] = size
            self.depth[ticker] = depth
            self._snapshot_levels(ticker)
        else:
            if ticker not in self.depth:
                raise MarketDataGap("snapshot_required")
            if "ts_ms" in msg:
                at = _fresh_ms(msg["ts_ms"], now, "book_engine")
            side = msg.get("side")
            if side not in ("yes", "no"):
                raise MarketDataGap("invalid_book_side")
            price, change = _price(msg.get("price_dollars")), _quantity(msg.get("delta_fp"), signed=True)
            price = round(1 - price, 8) if side == "no" else price
            level = self.depth[ticker][side]
            size = round(level.get(price, 0.0) + change, 2)
            if size < 0:
                raise MarketDataGap("negative_depth")
            if size:
                level[price] = size
            else:
                level.pop(price, None)
            self._changed_level(ticker, side, price, size)
        yes_levels, no_levels = self.bids[ticker]["yes"], self.bids[ticker]["no"]
        if yes_levels and no_levels and yes_levels[0].price + no_levels[0].price >= 1:
            raise MarketDataGap("crossed_book")
        if at is None:
            # The documented initial snapshot still seeds sequence-consistent
            # depth. Until a timestamped delta arrives, use public REST books.
            self.unproven.add(ticker)
            self.exchange_at.pop(ticker, None)
            self.book_at.pop(ticker, None)
            return (), ()
        if at < self.exchange_at.get(ticker, -math.inf):
            raise MarketDataGap("book_time_reversed")
        self.unproven.discard(ticker)
        self.exchange_at[ticker], self.book_at[ticker] = at, now
        sequence = f"kalshi-ws:{sid}:{seq}"
        return (Book(ticker, "up", yes_levels, self.asks[ticker]["no"],
                     now, sequence, at),
                Book(ticker, "down", no_levels, self.asks[ticker]["yes"],
                     now, sequence, at)), ()


class KalshiMarketWS:
    """Reconnects a market-only reader; REST remains independent and public."""

    def __init__(self, settings: Settings, *, tickers: Callable[[], frozenset[str]],
                 on_book: Callable[[Book], None], on_trade: Callable[[Trade], None],
                 on_status: Callable[[dict[str, Any]], None], clock: Callable[[], float] = time.time,
                 ws_connect: Callable[..., Any] | None = None) -> None:
        self.work_trace: WorkTrace | None = None
        self._settings, self._tickers = settings, tickers
        self._on_book, self._on_trade, self._on_status = on_book, on_trade, on_status
        self._clock, self._connect = clock, ws_connect or connect
        self.state = MarketState(frozenset())
        self.connected = False
        self._last_status: dict[str, Any] = {}
        self._timestamp_notice = False
        self._timing_session = 0
        # WeatherWS inherits this receiver on another thread/process. A session
        # number alone is not an identity and must not mix its evidence with BTC.
        self._timing_reader = {"kind": "speeddesk" if type(self) is KalshiMarketWS else "derived_market_reader",
                               "instance": next(_reader_ids), "process": os.getpid()}
        self._timing_gap: dict[str, Any] | None = None

    def _flush_timing_gap(self, ws: Any) -> None:
        context, self._timing_gap = self._timing_gap, None
        if context is not None:
            self._timing_report(ws, event="gap", **context)

    def _timing_report(self, ws: Any, *, event: str, call_mono: float,
                       returned_mono: float, apply_mono: float, apply_wall: float,
                       raw: Any, previous: tuple[float, float] | None) -> None:
        """Observe a message without supplying timestamps to freshness or trading.

        Protocol acceptance is later than socket/kernel arrival. Its residence
        is a local lower bound, never an estimate of provider/network delay.
        A missing stamp remains unknown; no local time replaces a source time.
        """
        try:
            receipt = ws.last_receipt if isinstance(ws, TimingClientConnection) else None
            msg = raw.get("msg") if isinstance(raw, dict) else None
            kind = raw.get("type") if isinstance(raw, dict) else None
            kind = kind if isinstance(kind, str) and kind in {"subscribed", "orderbook_snapshot", "orderbook_delta", "trade"} else "other"
            sending = raw.get("sending_ts_ms") if isinstance(raw, dict) else None
            engine = msg.get("ts_ms") if isinstance(msg, dict) else None
            payload: dict[str, Any] = {
                "reader": dict(self._timing_reader),
                "session": self._timing_session, "event": event, "kind": kind,
                "recv_call_mono": call_mono, "recv_return_mono": returned_mono,
                "apply_mono": apply_mono, "apply_wall": apply_wall,
                "recv_wait_ms": max(0.0, returned_mono - call_mono) * 1000,
                "return_to_apply_ms": max(0.0, apply_mono - returned_mono) * 1000,
                "sending_ts_ms": sending if _integer(sending) else None,
                "engine_ts_ms": engine if _integer(engine) else None,
                "receipt": None if receipt is None else receipt.as_dict(),
                "connection": ws.timing_status() if isinstance(ws, TimingClientConnection) else None,
                "previous_message": None if previous is None else {
                    "processing_ms": previous[0], "yield_resume_ms": previous[1]},
                "basis": "complete frame protocol acceptance to public recv; excludes earlier local and network delay",
            }
            if (receipt is not None and receipt.status == "known"
                    and receipt.accepted_monotonic is not None
                    and self.work_trace is not None and event == "gap"):
                payload["local_work"] = self.work_trace.overlap(receipt.accepted_monotonic, apply_mono, max_spans=8)
            log.info("speeddesk_feed_kalshi_ws_timing %s", json.dumps(payload, allow_nan=False, separators=(",", ":")))
        except Exception:  # noqa: BLE001 - observation cannot change message processing or gap handling.
            try:
                log.info("speeddesk_feed_kalshi_ws_timing_unavailable")
            except Exception:  # noqa: BLE001, S110 - a broken log sink cannot break market-data invalidation.
                pass

    def fresh_books(self, *, now: float | None = None) -> frozenset[str]:
        now = self._clock() if now is None else now
        return frozenset(ticker for ticker, at in self.state.book_at.items()
                         if self.connected and 0 <= now - at <= STALE_S
                         and 0 <= now - self.state.exchange_at[ticker] <= STALE_S)

    def fresh_maker_windows(self, *, now: float | None = None) -> frozenset[str]:
        now = self._clock() if now is None else now
        fresh = self.fresh_books(now=now)
        return frozenset(ticker for ticker in fresh
                         if 0 <= now - self.state.trade_at.get(ticker, -math.inf) <= STALE_S)

    def _report(self, reason: str = "market_websocket", *, invalidate: bool = False) -> None:
        now = self._clock()
        fresh = self.fresh_books(now=now)
        if self.connected and self.state.unproven:
            if not self._timestamp_notice:
                log.info("speeddesk_feed_kalshi_ws_waiting reason=missing_book_source_timestamp fallback=public_rest")
                self._timestamp_notice = True
            if not fresh and reason == "market_websocket":
                reason = "waiting_timestamped_book_public_rest_fallback"
        maker = sorted(self.fresh_maker_windows(now=now))
        old = set(self._last_status.get("ws_books", [])) | set(self._last_status.get("ws_maker_windows", []))
        gap = sorted(self.state.tickers if invalidate else old - fresh | (set(self._last_status.get("ws_maker_windows", [])) - set(maker)))
        status = {"ws_connected": self.connected, "ws_books": sorted(fresh), "ws_maker_windows": maker,
                  "ws_status": reason, "gap_windows": gap}
        if status != self._last_status or gap:
            self._last_status = status
            self._on_status(dict(status))

    async def run(self, stop: threading.Event) -> None:
        delay = 1.0
        while not stop.is_set():
            tickers = self._tickers()
            if not tickers:
                await asyncio.sleep(0.2)
                continue
            self.state = MarketState(tickers)
            session_before = self._timing_session
            try:
                signer = MarketHandshake(self._settings)
                async with self._connect(URL, additional_headers=signer.headers(self._clock()),
                                         open_timeout=8, close_timeout=2, ping_interval=10,
                                         ping_timeout=10, max_queue=16, max_size=1_000_000,
                                         create_connection=TimingClientConnection,
                                         logger=_transport_log) as ws:
                    self.connected = True
                    try:
                        await self._session(ws, tickers, stop)
                    finally:
                        # Clear data BEFORE awaiting the close handshake, which
                        # can take seconds on a broken connection.
                        self.connected = False
                        self._report("reconnecting_public_rest_fallback", invalidate=True)
                        # Existing cancellation/invalidation callbacks run first.
                        # A diagnostic must not delay clearing a rejected book.
                        self._flush_timing_gap(ws)
                        if self.state.book_at:
                            delay = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — never log headers, key material or server payloads.
                reason = str(exc) if isinstance(exc, MarketDataGap) else type(exc).__name__
                log.warning("speeddesk_feed_kalshi_ws_gap reason=%s reader_kind=%s reader_instance=%s reader_process=%s reader_session=%s",
                            reason, self._timing_reader["kind"], self._timing_reader["instance"],
                            self._timing_reader["process"],
                            self._timing_session if self._timing_session != session_before else None)
            finally:
                self.connected = False
                self._report("reconnecting_public_rest_fallback")
                self.state = MarketState(frozenset())
            if not stop.is_set():
                await asyncio.sleep(delay)
                delay = min(30.0, delay * 2)

    async def _session(self, ws: Any, tickers: frozenset[str], stop: threading.Event) -> None:
        self._timing_session += 1
        self._timing_gap = None
        last_report = -math.inf
        previous: tuple[float, float] | None = None
        yielded_at: float | None = None
        for identity, channel in ((1, "orderbook_delta"), (2, "trade")):
            params: dict[str, Any] = {"channels": [channel], "market_tickers": sorted(tickers)}
            if channel == "orderbook_delta":
                params["use_yes_price"] = True
            await ws.send(json.dumps({"id": identity, "cmd": "subscribe", "params": params}))
        self._report()
        while not stop.is_set():
            resumed_at = time.monotonic()
            if previous is not None and yielded_at is not None:
                previous = (previous[0], max(0.0, resumed_at - yielded_at) * 1000)
                yielded_at = None
            if self._tickers() != tickers:
                raise MarketDataGap("market_set_changed")
            call_mono = time.monotonic()
            try:
                payload = await asyncio.wait_for(ws.recv(), timeout=0.2)
            except TimeoutError:
                self._report()
                continue
            returned_mono = time.monotonic()
            with work_span(self.work_trace, "kalshi_decode_apply"):
                raw = json.loads(payload)
                apply_wall = self._clock()
                apply_mono = time.monotonic()
                try:
                    books, trades = self.state.apply(raw, apply_wall)
                except MarketDataGap:
                    # Retain only allowlisted public timing fields, never the
                    # frame, headers or exception text. Publish after invalidation.
                    msg = raw.get("msg") if isinstance(raw, dict) else None
                    kind = raw.get("type") if isinstance(raw, dict) else None
                    sending = raw.get("sending_ts_ms") if isinstance(raw, dict) else None
                    engine = msg.get("ts_ms") if isinstance(msg, dict) else None
                    safe_raw = {"type": kind if isinstance(kind, str) and kind in {"subscribed", "orderbook_snapshot", "orderbook_delta", "trade"} else "other",
                                "sending_ts_ms": sending if _integer(sending) else None,
                                "msg": {"ts_ms": engine if _integer(engine) else None}}
                    self._timing_gap = {"call_mono": call_mono, "returned_mono": returned_mono,
                                        "apply_mono": apply_mono, "apply_wall": apply_wall,
                                        "raw": safe_raw, "previous": previous}
                    raise
            self._report()
            for book in books:
                self._on_book(book)
            for trade in trades:
                self._on_trade(trade)
            if returned_mono - last_report >= 60:
                self._timing_report(ws, event="status", call_mono=call_mono, returned_mono=returned_mono,
                                    apply_mono=apply_mono, apply_wall=apply_wall, raw=raw, previous=previous)
                last_report = returned_mono
            yielded_at = time.monotonic()
            previous = (max(0.0, yielded_at - returned_mono) * 1000, 0.0)
            # A buffered recv can finish inline. Give ready account work a turn
            # only after every callback from this message has completed.
            await asyncio.sleep(0)
