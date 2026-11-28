"""Independent public BTC/USD research feeds; never a financial signal source.

Kraken v2 trade and Gemini v0.10.7 trade-stream contracts checked 2026-10-12.
Only public trade subscriptions are sent. Source clocks are not calibrated;
apparent source age is not one-way latency or evidence of price leadership.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from websockets.asyncio.client import connect

from .speeddesk_feeds import number, timestamp

SOURCES = ("coinbase", "kraken", "gemini")
KRAKEN = "wss://ws.kraken.com/v2"
GEMINI = "wss://ws.gemini.com"
MAX_HISTORY = 20_000
HISTORY_S = 120
AGE_LIMIT_S = 3


class BitcoinFeedError(ValueError):
    """Fixed public-feed failure reason, without arbitrary frame contents."""


def _positive(value: Any) -> float:
    result = number(value)
    if result is None or result <= 0:
        raise BitcoinFeedError("invalid_positive_amount")
    return result


def _identity(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value) or len(str(value)) > 128:
        raise BitcoinFeedError("missing_trade_identity")
    return str(value)


def iso_precision(value: str) -> float:
    """Wire decimal precision; clock accuracy remains unknown."""
    fraction = value.split(".", 1)[-1] if "." in value else ""
    digits = 0
    for character in fraction:
        if not character.isdigit():
            break
        digits += 1
    return 10.0 ** -digits


def _tick(source: str, symbol: str, price: Any, quantity: Any, identity: Any, at: float,
          raw_time: str, precision: float, received_at: float, monotonic_ns: int, clock_id: str,
          generation: int, **extra: Any) -> dict[str, Any]:
    if not math.isfinite(at) or at <= 0:
        raise BitcoinFeedError("invalid_source_timestamp")
    return {"source": source, "symbol": symbol, "base": "BTC", "quote": "USD",
            "price": _positive(price), "quantity": _positive(quantity), "trade_id": _identity(identity),
            "exchange_at": at, "exchange_timestamp_raw": raw_time,
            "exchange_timestamp_domain": f"{source}_trade_event", "timestamp_precision_s": precision,
            "received_at": received_at, "received_monotonic_ns": monotonic_ns, "receipt_clock_id": clock_id,
            "receipt_clock": "application_receive", "connection_generation": generation,
            "snapshot": False, "source_clock_accuracy": "unknown", **extra}


def kraken_ticks(raw: Any, received_at: float, monotonic_ns: int, clock_id: str,
                 generation: int) -> list[dict[str, Any]]:
    if not isinstance(raw, dict) or raw.get("channel") != "trade":
        return []
    if raw.get("type") == "snapshot":
        raise BitcoinFeedError("historical_snapshot_not_requested")
    rows = raw.get("data")
    if raw.get("type") != "update" or not isinstance(rows, list) or not rows:
        raise BitcoinFeedError("invalid_trade_batch")
    out = []
    for row in rows:
        if not isinstance(row, dict) or row.get("symbol") != "BTC/USD" or row.get("side") not in ("buy", "sell"):
            raise BitcoinFeedError("unexpected_trade_symbol_or_side")
        at = timestamp(row.get("timestamp"))
        identity = row.get("trade_id")
        if at is None or not isinstance(identity, int) or isinstance(identity, bool) or identity <= 0:
            raise BitcoinFeedError("invalid_trade_time_or_sequence")
        out.append(_tick("kraken", "BTC/USD", row.get("price"), row.get("qty"), identity, at,
                         row["timestamp"], iso_precision(row["timestamp"]), received_at, monotonic_ns, clock_id, generation,
                         aggressor=row["side"], sequence=identity, sequence_scope="trade_id_per_book",
                         sequence_available=True, continuity_guarantee="observed_trade_id_continuity"))
    return out


def gemini_ticks(raw: Any, received_at: float, monotonic_ns: int, clock_id: str,
                 generation: int) -> list[dict[str, Any]]:
    if not isinstance(raw, dict) or "s" not in raw:
        return []
    if raw.get("s") != "btcusd" or not isinstance(raw.get("m"), bool):
        raise BitcoinFeedError("unexpected_trade_symbol_or_side")
    event_ns, identity = raw.get("E"), raw.get("t")
    if (not isinstance(event_ns, int) or isinstance(event_ns, bool) or event_ns <= 0
            or not isinstance(identity, int) or isinstance(identity, bool) or identity <= 0):
        raise BitcoinFeedError("invalid_trade_time_or_identity")
    return [_tick("gemini", "btcusd", raw.get("p"), raw.get("q"), identity, event_ns / 1_000_000_000,
                  str(event_ns), 1e-9, received_at, monotonic_ns, clock_id, generation,
                  aggressor="sell" if raw["m"] else "buy", sequence=None, sequence_available=False,
                  sequence_scope="none", continuity_guarantee="transport_only_no_contiguous_sequence")]


class PublicBitcoinFeeds:
    def __init__(self, *, on_event: Callable[[str, dict[str, Any], float], None], receipt_clock_id: str,
                 clock: Callable[[], float] = time.time, monotonic_ns: Callable[[], int] = time.monotonic_ns,
                 connectors: dict[str, Callable[..., Any]] | None = None) -> None:
        self.on_event, self.clock, self.monotonic_ns = on_event, clock, monotonic_ns
        self.clock_id, self.connectors = receipt_clock_id, connectors or {}
        self.generation = dict.fromkeys(("kraken", "gemini"), 0)
        self.last_id: int | None = None
        self.seen: dict[str, set[str]] = {source: set() for source in self.generation}
        self.seen_order: dict[str, deque[str]] = {source: deque() for source in self.generation}
        self.last_health: dict[str, tuple[str, str, float]] = {}
        self.has_trade: dict[str, bool] = dict.fromkeys(self.generation, False)

    def health(self, source: str, status: str, *, reason: str = "", force: bool = False) -> None:
        now = self.clock()
        old = self.last_health.get(source)
        if not force and old and old[:2] == (status, reason) and now - old[2] < 30:
            return
        self.last_health[source] = (status, reason, now)
        self.on_event("bitcoin_exchange_health", {"source": source, "status": status, "reason": reason,
                      "received_at": now, "received_monotonic_ns": self.monotonic_ns(),
                      "receipt_clock_id": self.clock_id, "connection_generation": self.generation[source],
                      "sequence_available": source == "kraken", "public_only": True}, now)

    def message(self, source: str, raw: Any, received_at: float, monotonic_ns: int) -> None:
        if not isinstance(raw, dict):
            raise BitcoinFeedError("invalid_frame")
        if source == "kraken":
            if raw.get("channel") == "status":
                rows = raw.get("data")
                if (not isinstance(rows, list) or not rows or not isinstance(rows[0], dict)
                        or rows[0].get("system") != "online"):
                    raise BitcoinFeedError("exchange_not_online")
                return
            if raw.get("method") == "subscribe":
                result = raw.get("result")
                if (raw.get("success") is not True or raw.get("req_id") != 1 or not isinstance(result, dict)
                        or result.get("channel") != "trade" or result.get("symbol") != "BTC/USD"
                        or result.get("snapshot") is not False):
                    raise BitcoinFeedError("subscription_rejected")
                self.health(source, "subscribed")
                return
            if raw.get("channel") == "heartbeat":
                self.health(source, "connected" if self.has_trade[source] else "subscribed")
                return
            ticks = kraken_ticks(raw, received_at, monotonic_ns, self.clock_id, self.generation[source])
        else:
            if "id" in raw:
                if raw.get("id") != 1 or raw.get("status") != 200 or "error" in raw:
                    raise BitcoinFeedError("subscription_rejected")
                self.health(source, "subscribed")
                return
            ticks = gemini_ticks(raw, received_at, monotonic_ns, self.clock_id, self.generation[source])
        if not ticks:
            raise BitcoinFeedError("unexpected_public_frame")
        discontinuity = False
        for tick in ticks:
            identity = tick["trade_id"]
            if identity in self.seen[source]:
                continue
            if source == "kraken":
                current = int(identity)
                if self.last_id is not None and current != self.last_id + 1:
                    discontinuity = True
                    self.health(source, "gap", reason="trade_id_discontinuity", force=True)
                self.last_id = current
            tick["continuity_valid"] = not discontinuity
            self.seen[source].add(identity)
            self.seen_order[source].append(identity)
            while len(self.seen_order[source]) > MAX_HISTORY:
                self.seen[source].discard(self.seen_order[source].popleft())
            self.has_trade[source] = True
            if not discontinuity:
                self.health(source, "connected")
            self.on_event("bitcoin_exchange_tick", tick, received_at)
        if discontinuity:
            raise BitcoinFeedError("trade_id_discontinuity")

    async def _source(self, source: str) -> None:
        url = KRAKEN if source == "kraken" else GEMINI
        request = ({"method": "subscribe", "params": {"channel": "trade", "symbol": ["BTC/USD"],
                                                       "snapshot": False}, "req_id": 1}
                   if source == "kraken" else {"id": 1, "method": "subscribe", "params": ["btcusd@trade"]})
        delay = 5.0
        while True:
            self.generation[source] += 1
            self.has_trade[source] = False
            if source == "kraken":
                self.last_id = None
            self.health(source, "connecting", force=True)
            try:
                async with self.connectors.get(source, connect)(url, open_timeout=10, close_timeout=2,
                                                               ping_interval=10, ping_timeout=5,
                                                               max_queue=32, max_size=1_000_000) as ws:
                    await ws.send(json.dumps(request))
                    while True:
                        try:
                            payload = await asyncio.wait_for(ws.recv(), timeout=5)
                        except TimeoutError:
                            pong = await ws.ping()
                            await asyncio.wait_for(pong, timeout=5)
                            self.health(source, "connected" if self.has_trade[source] else "subscribed")
                            continue
                        received_at, mono = self.clock(), self.monotonic_ns()
                        self.message(source, json.loads(payload), received_at, mono)
                        if self.has_trade[source]:
                            delay = 5.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — only fixed type/reason; no credentials or private calls exist.
                status = getattr(getattr(exc, "response", None), "status_code", None)
                reason = str(exc) if isinstance(exc, BitcoinFeedError) else type(exc).__name__
                self.health(source, "blocked" if status in (401, 403, 451) else "gap", reason=reason, force=True)
                if status in (401, 403, 451):
                    # No hostname/proxy/jurisdiction workaround and no retry loop.
                    await asyncio.Future()
                if status in (429, 503):
                    retry = getattr(getattr(exc, "response", None), "headers", {}).get("Retry-After")
                    seconds = number(retry)
                    if seconds is None and isinstance(retry, str):
                        try:
                            seconds = parsedate_to_datetime(retry).timestamp() - self.clock()
                        except (ValueError, TypeError, OverflowError):
                            seconds = None
                    delay = max(delay, seconds or 0)
            await asyncio.sleep(delay)
            delay = min(30.0, delay * 2)

    async def run(self) -> None:
        tasks = [asyncio.create_task(self._source(source)) for source in self.generation]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for source in self.generation:
                self.health(source, "stopped", force=True)


@dataclass(frozen=True, slots=True)
class BitcoinSample:
    price: float
    exchange_at: float
    received_at: float
    observed_at: float
    monotonic_ns: int | None
    clock_id: str | None
    trade_id: str | None
    symbol: str
    generation: int | None
    valid: bool


class BitcoinObservations:
    """Bounded receiver-time features. Raw events remain in the durable journal."""

    def __init__(self) -> None:
        self.epoch: float | None = None
        self.ticks: dict[str, deque[BitcoinSample]] = {source: deque(maxlen=MAX_HISTORY) for source in SOURCES}
        self.health: dict[str, deque[tuple[float, str, str]]] = {source: deque(maxlen=2048) for source in SOURCES}
        self.days: dict[str, dict[str, int]] = {}
        self.first_seen: dict[str, float] = {}
        self.last_receipt: dict[str, BitcoinSample] = {}
        self.seen: dict[str, set[str]] = {source: set() for source in SOURCES}
        self.seen_order: dict[str, deque[str]] = {source: deque() for source in SOURCES}

    def ingest(self, kind: str, data: dict[str, Any], observed_at: float) -> None:
        if kind == "gap":
            gap_source = data.get("source")
            targets = SOURCES if gap_source in (None, "runtime", "storage", "clock") else (
                (gap_source,) if gap_source in SOURCES else ())
            for source in targets:
                self.health[source].append((observed_at, "gap", str(data.get("reason", "observation_gap"))))
            return
        if kind == "bitcoin_feature_epoch":
            if data.get("version") == 1 and self.epoch is None:
                self.epoch = observed_at
            return
        raw_source = data.get("source", "coinbase" if kind == "bitcoin_tick" else None)
        if not isinstance(raw_source, str) or raw_source not in SOURCES:
            return
        source = raw_source
        if kind in ("health", "bitcoin_exchange_health"):
            self.health[source].append((observed_at, str(data.get("status", "unknown")),
                                        str(data.get("reason", data.get("error", "")))))
            return
        if kind not in ("bitcoin_tick", "bitcoin_exchange_tick") or self.epoch is None:
            return
        if data.get("snapshot") is True:
            return  # Historical initial snapshots are not prospective trade ticks.
        price, at = number(data.get("price")), number(data.get("exchange_at"))
        received_at = number(data.get("received_at"))
        if price is None or price <= 0 or at is None or received_at is None:
            self.health[source].append((observed_at, "gap", "unverified_trade_time_or_price"))
            return
        mono, clock_id, identity = (data.get(key) for key in ("received_monotonic_ns", "receipt_clock_id", "trade_id"))
        if (not isinstance(identity, str) or not identity or (number(data.get("quantity")) or 0) <= 0
                or data.get("base") != "BTC" or data.get("quote") != "USD"):
            self.health[source].append((observed_at, "gap", "unverified_trade_identity_or_quote"))
            return  # Legacy/ambiguous rows cannot supply identified USD trades.
        if isinstance(identity, str):
            if identity in self.seen[source]:
                return
            self.seen[source].add(identity)
            self.seen_order[source].append(identity)
            while len(self.seen_order[source]) > MAX_HISTORY:
                self.seen[source].discard(self.seen_order[source].popleft())
        generation = data.get("connection_generation")
        clock_valid = (isinstance(mono, int) and not isinstance(mono, bool) and mono >= 0
                       and isinstance(clock_id, str) and bool(clock_id)
                       and isinstance(generation, int) and not isinstance(generation, bool) and generation >= 0)
        previous = self.last_receipt.get(source)
        if clock_valid and previous and previous.clock_id == clock_id and previous.monotonic_ns is not None:
            assert isinstance(mono, int)
            mono_delta = (mono - previous.monotonic_ns) / 1e9
            wall_delta = received_at - previous.received_at
            if mono_delta < 0 or wall_delta < 0 or abs(mono_delta - wall_delta) > .25:
                clock_valid = False
                self.health[source].append((observed_at, "gap", "receipt_clock_discontinuity"))
        valid = (data.get("quote") == "USD" and data.get("base") == "BTC"
                 and isinstance(identity, str) and bool(identity) and data.get("snapshot") is False
                 and (number(data.get("quantity")) or 0) > 0
                 and data.get("continuity_valid", True) is True and clock_valid
                 and 0 <= received_at - at <= AGE_LIMIT_S and received_at <= observed_at)
        if previous and at < previous.exchange_at:
            valid = False
            self.health[source].append((observed_at, "gap", "source_clock_reversed"))
        elif not valid:
            reason = ("source_time_future" if at > received_at else
                      "source_trade_stale" if received_at - at > AGE_LIMIT_S else
                      "receive_after_dispatch" if received_at > observed_at else
                      "unverified_clock_or_continuity")
            self.health[source].append((observed_at, "gap", reason))
        sample = BitcoinSample(price, at, received_at, observed_at, mono if isinstance(mono, int) else None,
                               clock_id if isinstance(clock_id, str) else None,
                               identity if isinstance(identity, str) else None, str(data.get("symbol", "")),
                               generation if isinstance(generation, int) else None, valid)
        self.last_receipt[source] = sample
        self.ticks[source].append(sample)
        self.first_seen.setdefault(source, observed_at)
        day = datetime.fromtimestamp(received_at, UTC).date().isoformat()
        counts = self.days.setdefault(day, dict.fromkeys(SOURCES, 0))
        counts[source] += 1
        self.days = {key: self.days[key] for key in sorted(self.days)[-31:]}
        for history in self.ticks.values():
            while history and history[0].received_at < observed_at - HISTORY_S:
                history.popleft()

    def _before(self, source: str, at: float) -> BitcoinSample | None:
        return next((tick for tick in reversed(self.ticks[source])
                     if tick.observed_at <= at and tick.received_at <= at), None)

    def features(self, at: float) -> dict[str, dict[str, Any]]:
        out = {}
        for source in SOURCES:
            tick = self._before(source, at)
            status, reason = next(((state, reason) for when, state, reason in reversed(self.health[source])
                                   if when <= at), ("unknown", ""))
            connected = status == "connected"
            fresh = bool(self.epoch is not None and self.epoch <= at and tick and tick.valid
                         and connected and 0 <= at - tick.received_at <= AGE_LIMIT_S
                         and 0 <= at - tick.exchange_at <= AGE_LIMIT_S)
            item: dict[str, Any] = {"price": tick.price if tick else None, "fresh": fresh, "connected": connected,
                "status": status, "reason": reason,
                "quote": "USD", "symbol": tick.symbol if tick else None,
                "trade_id": tick.trade_id if tick else None, "exchange_at": tick.exchange_at if tick else None,
                "received_at": tick.received_at if tick else None,
                "observed_at": tick.observed_at if tick else None,
                "received_monotonic_ns": tick.monotonic_ns if tick else None,
                "receipt_clock_id": tick.clock_id if tick else None,
                "connection_generation": tick.generation if tick else None,
                "receipt_age_ms": (at - tick.received_at) * 1000 if tick else None,
                "apparent_source_age_ms": (tick.received_at - tick.exchange_at) * 1000 if tick else None,
                "source_clock_accuracy": "unknown", "sequence_available": source != "gemini"}
            for seconds in (1, 5, 30):
                prior = self._before(source, at - seconds)
                crossed_gap = any(start <= at and start >= (prior.received_at if prior else at)
                                  and status != "connected" for start, status, _ in self.health[source])
                eligible = bool(fresh and prior and prior.valid and at - seconds - prior.received_at <= AGE_LIMIT_S
                                and 0 <= at - seconds - prior.exchange_at <= AGE_LIMIT_S
                                and tick and prior.clock_id == tick.clock_id and prior.clock_id is not None
                                and prior.generation == tick.generation
                                and not crossed_gap)
                item[f"move_{seconds}s"] = math.log(tick.price / prior.price) if eligible and tick and prior else None
            out[source] = item
        return out

    def summary(self, now: float) -> dict[str, Any]:
        venues = self.features(now)
        for source, row in venues.items():
            recent = [tick for tick in self.ticks[source]
                      if now - HISTORY_S <= tick.received_at <= now and tick.observed_at <= now][-2048:]
            ages = sorted((tick.received_at - tick.exchange_at) * 1000 for tick in recent)
            middle = len(ages) // 2
            row.update(first_seen_at=self.first_seen.get(source), age_samples=len(ages),
                       apparent_source_age_median_ms=((ages[middle] if len(ages) % 2 else
                                                      (ages[middle - 1] + ages[middle]) / 2) if ages else None),
                       apparent_source_age_p95_ms=ages[math.ceil(len(ages) * .95) - 1] if ages else None,
                       future_clock_samples=sum(age < 0 for age in ages),
                       age_scope="latest at most 2048 observed trades within retained 120s/20000-tick history")
        return {"feature_epoch_started_at": self.epoch, "venues": venues, "daily_observed_ticks": self.days,
                "daily_counts_are_partial": True, "leadership_status": "not_established",
                "method": "Local receipt-time features; no source timestamp or apparent age ranks leaders",
                "limitation": "Source clock error, venue price basis and trade batching are unknown; USD trades are not oracle prices"}
