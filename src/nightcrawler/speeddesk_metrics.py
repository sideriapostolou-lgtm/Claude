"""Bounded, additive timing evidence; no network, account access or trading decisions."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

MAX_SAMPLES = 4096
MAX_DAYS = 31
METRICS = ("btc_exchange_to_decision", "btc_receipt_to_decision", "decision_to_ack")
Status = Literal["ok", "missing", "invalid", "error", "timeout"]


@dataclass(frozen=True)
class TickReceipt:
    exchange_at: float
    received_at: float
    monotonic_at: float


def tick_timings(tick: TickReceipt | None, decision_mono: float) -> dict[str, tuple[float | None, Status]]:
    """Age of the exact accepted input, not proof that this tick triggered the decision."""
    names = METRICS[:2]
    if tick is None:
        return {name: (None, "missing") for name in names}
    if not all(math.isfinite(value) for value in
               (tick.exchange_at, tick.received_at, tick.monotonic_at, decision_mono)):
        return {name: (None, "invalid") for name in names}
    elapsed = decision_mono - tick.monotonic_at
    if elapsed < 0:
        return {name: (None, "invalid") for name in names}
    wire_age = tick.received_at - tick.exchange_at
    return {names[0]: ((wire_age + elapsed) * 1000, "ok") if wire_age >= 0 else (None, "invalid"),
            names[1]: (elapsed * 1000, "ok")}


class LatencyMetrics:
    """Exact bounded daily samples; overflow makes percentiles unknown, never biased tails.

    Elapsed values are durable; process-local monotonic anchors are never restored.
    Counts describe instrumented intent cohorts, not every public tick or book update.
    """

    def __init__(self, now: float, saved: dict[str, Any] | None = None) -> None:
        self.started_at = now
        self.days: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        self.restore_error = False
        self.evicted_before = 0.0
        if saved is not None:
            try:
                if saved.get("version") != 1 or not math.isfinite(float(saved["started_at"])):
                    raise ValueError("Invalid timing state")
                days = saved["days"]
                if not isinstance(days, dict) or len(days) > MAX_DAYS:
                    raise ValueError("Invalid timing days")
                for day, scopes in days.items():
                    datetime.strptime(day, "%Y-%m-%d")
                    for metrics in scopes.values():
                        for name, bucket in metrics.items():
                            if name not in METRICS or len(bucket["values"]) > MAX_SAMPLES:
                                raise ValueError("Invalid timing bucket")
                            for value in bucket["values"]:
                                if not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
                                    raise ValueError("Invalid timing sample")
                            for key in ("observations", "samples", "missing", "invalid", "errors", "timeouts"):
                                if type(bucket[key]) is not int or bucket[key] < 0:
                                    raise ValueError("Invalid timing counter")
                            if bucket["samples"] < len(bucket["values"]):
                                raise ValueError("Invalid sample count")
                            if (sum(bucket[key] for key in ("samples", "missing", "invalid", "errors"))
                                    != bucket["observations"] or bucket["timeouts"] > bucket["errors"]):
                                raise ValueError("Inconsistent timing counters")
                evicted = float(saved.get("evicted_before", 0.0))
                if not math.isfinite(evicted) or evicted < 0:
                    raise ValueError("Invalid timing retention")
                self.started_at, self.days, self.evicted_before = float(saved["started_at"]), days, evicted
            except (KeyError, TypeError, ValueError, AttributeError):
                # Optional telemetry cannot invalidate a sound financial ledger.
                self.restore_error = True

    def state(self) -> dict[str, Any]:
        return {"version": 1, "started_at": self.started_at, "days": self.days,
                "evicted_before": self.evicted_before}

    def observe(self, scope: str, name: str, at: float, value: float | None,
                status: Status = "ok") -> dict[str, Any]:
        if name not in METRICS:
            raise ValueError("Unknown timing metric")
        if status == "ok" and (value is None or not math.isfinite(value) or value < 0):
            status, value = "invalid", None
        day = datetime.fromtimestamp(at, UTC).date().isoformat()
        scopes = self.days.setdefault(day, {})
        bucket = scopes.setdefault(scope, {}).setdefault(name, {
            "values": [], "observations": 0, "samples": 0, "missing": 0,
            "invalid": 0, "errors": 0, "timeouts": 0})
        bucket["observations"] += 1
        if status == "ok":
            bucket["samples"] += 1
            if len(bucket["values"]) < MAX_SAMPLES:
                bucket["values"].append(value)
        elif status == "timeout":
            bucket["errors"] += 1
            bucket["timeouts"] += 1
        else:
            bucket[{"missing": "missing", "invalid": "invalid", "error": "errors"}[status]] += 1
        for old in sorted(self.days)[:-MAX_DAYS]:
            del self.days[old]
            self.evicted_before = max(self.evicted_before,
                                      datetime.strptime(old, "%Y-%m-%d").replace(tzinfo=UTC).timestamp() + 86400)
        return {"metric": name, "scope": scope, "at": at, "value_ms": value if status == "ok" else None,
                "status": status}

    def decision(self, scope: str, at: float, tick: TickReceipt | None,
                 decision_mono: float) -> list[dict[str, Any]]:
        return [self.observe(scope, name, at, value, status)
                for name, (value, status) in tick_timings(tick, decision_mono).items()]

    def report(self, day: str, scope: str, *, real: bool = False) -> dict[str, Any]:
        midnight = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()
        historical = midnight + 86400 <= max(self.started_at, self.evicted_before)
        partial = midnight < self.started_at
        out: dict[str, Any] = {}
        for name in METRICS:
            bucket = self.days.get(day, {}).get(scope, {}).get(name, {})
            values = sorted(bucket.get("values", []))
            samples = bucket.get("samples", 0)
            overflow = samples > len(values)
            applicable = name != "decision_to_ack" or real
            limit = ("Age of accepted Coinbase input; exchange/local clock uncertainty remains"
                     if name == "btc_exchange_to_decision" else
                     "Age since strategy callback receipt; not pure computation or proven trigger reaction"
                     if name == "btc_receipt_to_decision" else
                     "Decision to observed validated exchange acknowledgement; includes journal, queue and HTTP time")
            out[name] = {
                "unit": "ms", "scope": scope, "cohort": "intents_created_on_utc_day",
                "started_at": self.started_at, "complete": not historical and not overflow and not self.restore_error,
                "partial_day": partial, "applicable": applicable,
                **{key: None if historical else bucket.get(key, 0)
                   for key in ("observations", "samples", "missing", "invalid", "errors", "timeouts")},
                "overflow": overflow, "median_ms": statistics.median(values) if values and not overflow else None,
                "p95_ms": values[math.ceil(.95 * len(values)) - 1] if values and not overflow else None,
                "limitation": limit,
            }
            if name == "decision_to_ack" and real and not historical:
                # A persisted intent can outlive an interrupted HTTP worker or
                # the process. No response/reconciliation timestamp can repair
                # its lost monotonic acknowledgement; keep the deficit visible.
                decisions = self.days.get(day, {}).get(scope, {}).get("btc_receipt_to_decision", {})
                missing = max(0, decisions.get("observations", 0) - bucket.get("observations", 0))
                out[name]["observations"] += missing
                out[name]["missing"] += missing
                out[name]["pending_or_lost_ack"] = missing
        return out


class WindowEvidence:
    """Track complete observation/capture separately from market availability.

    A known stale/no-buy interval is observed history. An unobserved interval,
    late market discovery or restart gap is not. Financial ledgers are separate.
    """

    def __init__(self, now: float, saved: dict[str, Any] | None = None) -> None:
        self.started_at = now
        self.fills: list[dict[str, Any]] = []
        self.seconds: dict[str, float] = {}
        self.fresh_seconds: dict[str, float] = {}
        self.first_seen: dict[str, float] = {}
        self.restore_error = False
        self.clock_reversals = 0
        high_water = now
        if saved:
            try:
                started = float(saved["started_at"])
                fills = saved["fills"]
                maps = [saved[key] for key in ("seconds", "fresh_seconds", "first_seen")]
                if (saved.get("version") != 2 or not math.isfinite(started) or not isinstance(fills, list)
                        or any(not isinstance(row, dict) or not isinstance(row.get("window"), str) for row in fills)
                        or any(not isinstance(values, dict) or any(
                            not isinstance(slug, str) or not isinstance(value, (int, float))
                            or not math.isfinite(value) or value < 0 for slug, value in values.items()) for values in maps)):
                    raise ValueError("Invalid observation evidence")
                previous = float(saved.get("last_observed_at", now))
                if not math.isfinite(previous):
                    raise ValueError("Invalid observation clock")
                self.started_at, self.fills = started, list(fills)
                self.seconds, self.fresh_seconds, self.first_seen = (dict(values) for values in maps)
                high_water = max(now, previous)
            except (KeyError, TypeError, ValueError, OverflowError):
                self.restore_error = True
        self.last_at = high_water
        self.last_fresh: set[str] = set()

    def state(self) -> dict[str, Any]:
        return {"version": 2, "started_at": self.started_at, "fills": self.fills, "seconds": self.seconds,
                "fresh_seconds": self.fresh_seconds, "first_seen": self.first_seen,
                "last_observed_at": self.last_at}

    def fill(self, row: dict[str, Any]) -> None:
        self.fills.append({key: row.get(key) for key in
                           ("window", "side", "price", "size", "fee_usd", "at", "is_taker")})

    def discover(self, windows: list[dict[str, Any]], now: float) -> None:
        for window in windows:
            self.first_seen.setdefault(window["slug"], now)

    def advance(self, now: float, windows: list[dict[str, Any]], fresh: set[str]) -> None:
        if now < self.last_at:
            # Keep a wall-clock high-water mark: returning to a previously
            # observed second must never credit that interval twice.
            self.last_fresh.clear()
            self.clock_reversals += 1
            return
        self.discover(windows, now)
        start = max(self.last_at, now - 1.0)
        for window in windows:
            slug = window["slug"]
            duration = max(0.0, min(now, window["end"]) - max(start, window["start"], self.first_seen[slug]))
            if duration:
                self.seconds[slug] = self.seconds.get(slug, 0.0) + duration
                if slug in fresh and slug in self.last_fresh:
                    self.fresh_seconds[slug] = self.fresh_seconds.get(slug, 0.0) + duration
        self.last_at, self.last_fresh = now, fresh
        retained = {window["slug"] for window in windows if window["end"] >= now - MAX_DAYS * 86400}
        self.fills = [row for row in self.fills if row["window"] in retained]
        self.seconds = {slug: seconds for slug, seconds in self.seconds.items() if slug in retained}
        self.fresh_seconds = {slug: seconds for slug, seconds in self.fresh_seconds.items() if slug in retained}
        self.first_seen = {slug: at for slug, at in self.first_seen.items() if slug in retained}

    def coverage(self, windows: list[dict[str, Any]]) -> dict[str, bool | None]:
        return {window["slug"]: None if window["start"] < self.started_at or
                self.first_seen.get(window["slug"], math.inf) > window["start"] else
                self.seconds.get(window["slug"], 0.0) >= window["end"] - window["start"] - 1e-6
                for window in windows}

    def availability(self, windows: list[dict[str, Any]]) -> dict[str, Any]:
        observed = sum(self.seconds.get(window["slug"], 0.0) for window in windows)
        fresh = sum(self.fresh_seconds.get(window["slug"], 0.0) for window in windows)
        return {"observed_window_seconds": observed, "fresh_market_window_seconds": fresh,
                "fresh_market_fraction": fresh / observed if observed else None,
                "availability_basis": "window-seconds; fresh BTC, both books and verified trades; known stale intervals retained",
                "evidence_started_at": self.started_at,
                "evidence_restore_error": self.restore_error, "clock_reversals": self.clock_reversals}

    def complete_kalshi_day(self, day: str, windows: list[dict[str, Any]], now: float) -> bool:
        """Only the fixed 96-window verified 15m universe can certify a calendar cohort."""
        start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()
        if now < start + 86400 or self.started_at > start - 900:
            return False
        coverage = self.coverage(windows)
        actual: list[float] = []
        for window in windows:
            if window.get("venue") != "kalshi" or not start <= window["end"] < start + 86400:
                continue
            if not coverage.get(window["slug"]) or not math.isclose(window["end"] - window["start"], 900):
                return False
            actual.append(window["end"])
        return sorted(actual) == [start + index * 900 for index in range(96)]


def fresh_window_slugs(windows: list[dict[str, Any]], books: dict[Any, Any], bitcoin_at: float | None,
                       makers: set[str] | frozenset[str], now: float) -> set[str]:
    """Report-only full data availability; no strategy or risk permission is implied."""
    if bitcoin_at is None or not 0 <= now - bitcoin_at <= 3:
        return set()
    fresh = set()
    for window in windows:
        slug = window["slug"]
        if slug not in makers:
            continue
        sides = [books.get((slug, side)) for side in ("up", "down")]
        if all(book is not None and 0 <= now - book.at <= 3
               and (book.source != "rest" or book.requested_at is not None and 0 <= now - book.requested_at <= 3)
               and (book.requested_at is None or 0 <= book.at - book.requested_at <= 3)
               and (book.source == "rest" or book.exchange_at is not None and 0 <= now - book.exchange_at <= 3)
               for book in sides):
            fresh.add(slug)
    return fresh
