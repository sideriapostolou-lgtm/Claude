"""Differential practice persistence against immutable pre-cache methods (f77e1ad)."""

from __future__ import annotations

import copy
import hashlib
import sqlite3
import threading
from collections import Counter
from contextlib import ExitStack
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fakes import FakeClock
from test_speeddesk_runtime import LocalFeeds
from test_speeddesk_snapshot_cache import Companion

import nightcrawler.speeddesk as sd
from nightcrawler.config import Settings
from nightcrawler.ledger import LedgerError
from nightcrawler.speeddesk_model import (
    Holding,
    Inventory,
    PracticeOrder,
    Settlement,
    Window,
    utc_day,
)

BASELINE_SOURCE = 'def summary(self, day: str, venue: str | None = None) -> dict[str, Any]:\n    report = self.desk.daily_summary(day, venue=venue)\n    latency = self.feed_latency.get(day, [0.0, 0.0])\n    report.update(observed_seconds=self.observed.get(day, 0.0),\n                  avg_bitcoin_feed_latency_ms=latency[0] / latency[1] if latency[1] else None,\n                  bitcoin_feed_latency_scope="shared Coinbase feed",\n                  latency_definition="decision to simulated fill; maker includes resting time")\n    for prefix in ("take", "maker"):\n        attempts = report["take_attempts" if prefix == "take" else "maker_orders"]\n        fills = report[f"{prefix}_fills"]\n        report[f"{prefix}_fill_rate_pct"] = 100 * fills / attempts if attempts and fills is not None else None\n    if venue is None:\n        report["venues"] = {name: self.summary(day, name) for name in VENUES}\n    else:\n        report["latency"] = self.metrics.report(day, venue)\n        windows = [asdict(window) for window in self.desk.windows.values()\n                   if window.venue == venue and window.end <= self.clock.now()]\n        report["scorecard"] = window_scorecard(\n            day, windows=windows, fills=self.evidence.fills, settlements=[asdict(row) for row in self.desk.closed],\n            coverage=self.evidence.coverage(windows), scope="practice", as_of=self.clock.now(),\n            day_coverage_complete=self.evidence.complete_kalshi_day(day, windows, self.clock.now())\n            if venue == "kalshi" else False)\n        report["scorecard"].update(self.evidence.availability(\n            [window for window in windows if utc_day(window["end"]) == day]))\n        if day < utc_day(self.clock.now() - 30 * 86400):\n            # Detailed evidence is bounded; preserve an already published\n            # older report instead of revising known history into no data.\n            previous = self.reports.get(day, {}).get("venues", {}).get(venue, {})\n            for key in ("latency", "scorecard"):\n                if key in previous:\n                    report[key] = previous[key]\n        coverage = self.venue_coverage.get(day, {}).get(venue, {})\n        # No backfilling coverage from combined uptime on upgrade.\n        predates_coverage = day < utc_day(self.venue_reporting_started_at)\n        fresh = None if predates_coverage else coverage.get("fresh_data_seconds", 0.0)\n        report.update(venue=venue, enabled=venue in self.enabled_venues if day == utc_day(self.clock.now()) else None,\n                      reporting_started_at=self.venue_reporting_started_at,\n                      coverage_started_at=self.venue_reporting_started_at,\n                      fresh_data_seconds=fresh,\n                      maker_data_seconds=None if predates_coverage else coverage.get("maker_data_seconds", 0.0),\n                      partial_day=fresh is None or fresh < 86395,\n                      coverage_definition="fresh Bitcoin and both books of at least one active venue window; "\n                      "maker coverage also requires its verified trade stream; warm-up is included")\n    return report\n\n@observed("practice_checkpoint")\ndef checkpoint(self, now: float) -> None:\n    self.daily_reports(now)\n    with work_span(self.work_trace, "practice_state"):\n        state = {"version": 1, "mode": "practice", "started_at": self.started_at, "updated_at": now,\n                 "model": self.desk.to_state(), "reports": self.reports, "observed_seconds": self.observed,\n                 "feed_latency": self.feed_latency, "opening_logged": sorted(self.opening_logged),\n                 "latency_metrics": self.metrics.state(),\n                 "window_evidence": self.evidence.state(),\n                 "venue_reporting_started_at": self.venue_reporting_started_at,\n                 "venue_coverage": self.venue_coverage,\n                 "panel": self.panel(now)}\n    with work_span(self.work_trace, "practice_ledger"):\n        first = not self._first_save_synced\n        if first:\n            self.ledger.set_synchronous(True)  # the ledger state is on disk before the display copy can be\n        with self.ledger.transaction():\n            for kind, payload in self.pending:\n                self.ledger.append_receipt(kind, payload, ts=payload.get("at", now))\n            self.ledger.set_kv(STATE_KEY, state)\n        if first:\n            self.ledger.set_synchronous(False)\n            self._first_save_synced = True\n    with work_span(self.work_trace, "practice_logs"):\n        for kind, payload in self.pending:\n            log.info("%s %s", kind, json.dumps(payload, allow_nan=False, separators=(",", ":")))\n        self.pending.clear()\n    # A mirror failure halts practice, but the committed ledger survives it. A display copy: not synced.\n    with work_span(self.work_trace, "practice_mirror"):\n        _atomic_json(self.path, state, durable=False)\n    self.last_checkpoint = now\n'
BASELINE_SHA256 = "13f100736176090f4bd997a3f7cada06cea3d7ba7fcb0f3f1f4bbd4f0bdf9570"
assert hashlib.sha256(BASELINE_SOURCE.encode()).hexdigest() == BASELINE_SHA256
_baseline_namespace = dict(vars(sd))
exec(  # noqa: S102 - pinned local source, no external input.
    compile(BASELINE_SOURCE, "<immutable-f77e1ad-methods>", "exec"), _baseline_namespace
)


class BaselineRunner(sd.SpeedRunner):
    summary = _baseline_namespace["summary"]
    checkpoint = _baseline_namespace["checkpoint"]


class PaperCompanion(Companion):
    def panel(self):
        return {"mode": "paper", "authenticated": False, "real_orders_available": False}


class ScriptClock(FakeClock):
    def __init__(self, now):
        super().__init__(now)
        self.script = []
        self.trace = []
        self.script_now = None

    def now(self):
        if self.script:
            self.script_now = self.script.pop(0)
        value = super().now() if self.script_now is None else self.script_now
        self.trace.append(value)
        return value


BASE = datetime(2026, 8, 1, tzinfo=UTC).timestamp()


def make_runner(path, cls, days=3):
    clock = ScriptClock(BASE)
    settings = Settings(
        data_dir=path,
        kalshi_arena_enabled=False,
        speeddesk_kalshi_enabled=True,
        trading_mode="paper",
        polydesk_mode="paper",
        speeddesk_kalshi_mode="paper",
    )
    runner = cls(
        settings,
        threading.Event(),
        clock=clock,
        feed_factory=LocalFeeds,
        live_factory=PaperCompanion,
    )
    for day in range(days):
        key = utc_day(BASE + day * 86400)
        runner.observed[key] = 400.0
        runner.venue_coverage[key] = {
            v: {"fresh_data_seconds": 200.0, "maker_data_seconds": 100.0}
            for v in ("kalshi", "polymarket_us")
        }
        for venue in ("polymarket_us", "kalshi"):
            start = BASE + day * 86400 + 100
            w = Window(
                f"{venue}-{day}",
                start,
                start + 900,
                80000,
                maker_coefficient=0.02,
                venue_start_price=80000 if venue == "kalshi" else None,
                venue=venue,
            )
            runner.desk.add_window(w)
            runner.desk.inventory[w.slug] = Inventory(
                Holding(0.75, 0.3, 0.0036), Holding(0.25, 0.15, 0.002)
            )
            if day != days - 1:
                result = runner.desk.settle(w.slug, day % 2 == 0, w.end + 1)
                runner.record("speeddesk_window", asdict(result))
            runner.evidence.first_seen[w.slug] = start
            runner.evidence.seconds[w.slug] = 450.0
            runner.evidence.fresh_seconds[w.slug] = 200.0
    clock.set(BASE + days * 86400 + 3600)
    clock.trace.clear()
    return runner, clock


def snapshot(runner, clock):
    conn = runner.ledger._conn
    row = conn.execute("SELECT value FROM kv WHERE key=?", (sd.STATE_KEY,)).fetchone()
    return {
        "kv": row[0] if row else None,
        "mirror": runner.path.read_bytes() if runner.path.exists() else None,
        "receipts": [asdict(r) for r in runner.ledger.receipts()],
        "pending": copy.deepcopy(runner.pending),
        "reports": copy.deepcopy(runner.reports),
        "last_checkpoint": runner.last_checkpoint,
        "first_synced": runner._first_save_synced,
        "clock_trace": list(clock.trace),
        "chain": runner.ledger.verify_chain(),
        "sync": conn.execute("PRAGMA synchronous").fetchone()[0],
    }


def replay_pair(tmp_path, action, days=3):
    results = []
    for label, cls in (("baseline", BaselineRunner), ("candidate", sd.SpeedRunner)):
        runner, clock = make_runner(tmp_path / label, cls, days)
        try:
            result = action(runner, clock)
            assert runner._settlement_cache is None
            results.append((result, snapshot(runner, clock)))
        finally:
            runner.close()
    assert results[0] == results[1]
    return results[1]


@pytest.mark.parametrize(
    "offsets",
    [
        [-1, 0, 1, 2],
        [0, 86400, 86400.1, -86400],
        [-30 * 86400 - 1, -30 * 86400, -30 * 86400 + 1, 0],
        [1, 0, -1, -2, 2],
    ],
)
def test_advancing_clocks_and_reversal_preserve_every_call_and_byte(tmp_path, offsets):
    def action(r, clock):
        now = clock.now()
        # Two windows straddle successive close checks; no prefiltered universe.
        for i, venue in enumerate(("polymarket_us", "kalshi")):
            r.desk.add_window(
                Window(f"boundary-{i}", now - 900, now + i, 80000, venue=venue)
            )
        r.checkpoint(now)
        clock.script = [now + offset for offset in offsets] * 60
        r.checkpoint(now)
        r.checkpoint(now)
        return r.summary(utc_day(now))

    replay_pair(tmp_path, action)


@pytest.mark.parametrize(
    "mutation",
    [
        "replace",
        "same_object",
        "zero_sign",
        "type",
        "append",
        "reverse",
        "rebind",
        "duplicate",
    ],
)
def test_each_row_visit_detects_changes_without_deduplication(tmp_path, mutation):
    def action(r, clock):
        original = r.evidence.coverage
        changed = False

        def coverage(windows):
            nonlocal changed
            result = original(windows)
            if not changed:
                changed = True
                row = r.desk.closed[0]
                if mutation == "replace":
                    r.desk.closed[0] = replace(row, pnl_usd=-7.0)
                elif mutation == "same_object":
                    object.__setattr__(row, "pnl_usd", -7.0)
                elif mutation == "zero_sign":
                    object.__setattr__(row, "fee_usd", -0.0)
                elif mutation == "type":
                    object.__setattr__(row, "up_shares", 1)
                elif mutation == "append":
                    r.desk.closed.append(replace(row, window="extra"))
                elif mutation == "reverse":
                    r.desk.closed.reverse()
                elif mutation == "rebind":
                    r.desk.closed = list(reversed(r.desk.closed))
                elif mutation == "duplicate":
                    r.desk.closed = [row, row, *r.desk.closed[1:]]
            return result

        with patch.object(r.evidence, "coverage", coverage):
            r.checkpoint(clock.now())
        r.checkpoint(clock.now())

    replay_pair(tmp_path, action)


@dataclass(frozen=True)
class SettlementChild(Settlement):
    extra: str = "retained"


class ExplosiveFloat(float):
    def __deepcopy__(self, _memo):
        raise ValueError("original exotic deepcopy")


@pytest.mark.parametrize(
    "kind", ["subclass", "exotic", "missing", "not_dataclass", "exotic_repairs_later"]
)
def test_original_asdict_fallback_and_exception_order(tmp_path, kind):
    def action(r, clock):
        first = r.desk.closed[0]
        if kind == "subclass":
            r.desk.closed[0] = SettlementChild(**asdict(first))
        elif kind == "exotic":
            object.__setattr__(first, "at", ExplosiveFloat(first.at))
        elif kind == "missing":
            object.__delattr__(first, "pnl_usd")
        elif kind == "not_dataclass":
            r.desk.closed[0] = object()
        elif kind == "exotic_repairs_later":

            class RepairFloat(float):
                def __deepcopy__(self, _memo):
                    object.__setattr__(first, "pnl_usd", 2.5)
                    return float(self)

            object.__setattr__(first, "at", RepairFloat(first.at))
            object.__delattr__(first, "pnl_usd")
        try:
            r.checkpoint(clock.now())
        except (ValueError, AttributeError, TypeError) as exc:
            return type(exc).__name__, str(exc)
        return "passed"

    replay_pair(tmp_path, action)


def test_standalone_summary_and_consumer_containers_remain_fresh(tmp_path):
    def action(r, clock):
        original = sd.window_scorecard
        seen = []

        def scorecard(*args, **kwargs):
            rows = kwargs["settlements"]
            seen.append(copy.deepcopy(rows))
            result = original(*args, **kwargs)
            if rows:
                rows[0]["pnl_usd"] = 999
            rows.append({"poison": True})
            return result

        # The copied baseline function resolves globals in its private namespace.
        with (
            patch.object(sd, "window_scorecard", scorecard),
            patch.dict(_baseline_namespace, window_scorecard=scorecard),
        ):
            r.checkpoint(clock.now())
            before = r.summary(utc_day(clock.now()))
            object.__setattr__(r.desk.closed[0], "pnl_usd", -3.0)
            after = r.summary(utc_day(clock.now()))
        assert all(not any("poison" in row for row in rows) for rows in seen)
        return before, after, seen

    replay_pair(tmp_path, action)


@pytest.mark.parametrize("nested_failure", [False, True])
def test_nested_checkpoint_restores_outer_context_and_observes_mutation(
    tmp_path, nested_failure
):
    def action(r, clock):
        original = r.evidence.coverage
        entered = False

        def coverage(windows):
            nonlocal entered
            if not entered:
                entered = True
                outer = r._settlement_cache
                if nested_failure:
                    with (
                        patch.object(
                            r.desk, "to_state", side_effect=RuntimeError("nested state")
                        ),
                        pytest.raises(RuntimeError, match="nested state"),
                    ):
                        r.checkpoint(clock.now())
                else:
                    r.checkpoint(clock.now())
                assert r._settlement_cache is outer
                object.__setattr__(r.desk.closed[0], "pnl_usd", -2.0)
            return original(windows)

        with patch.object(r.evidence, "coverage", coverage):
            r.checkpoint(clock.now())

    replay_pair(tmp_path, action)


class CommitFailure:
    def __init__(self, conn):
        self.conn = conn

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def execute(self, sql, *args):
        if sql == "COMMIT":
            raise sqlite3.OperationalError("injected commit")
        return self.conn.execute(sql, *args)


@pytest.mark.parametrize(
    "stage",
    [
        "daily",
        "model",
        "metrics",
        "panel",
        "full",
        "receipt",
        "kv",
        "commit",
        "normal",
        "logs",
        "mirror",
        "replace",
    ],
)
def test_failure_boundaries_cleanup_and_retry_match_original(tmp_path, stage):
    def action(r, clock):
        def fail(*args, **kwargs):
            raise RuntimeError(f"injected {stage}")

        with ExitStack() as stack:
            if stage == "daily":
                original = r.summary

                def summary(day, venue=None):
                    if day == utc_day(BASE + 86400):
                        fail()
                    return original(day, venue)

                stack.enter_context(patch.object(r, "summary", summary))
            elif stage == "model":
                stack.enter_context(patch.object(r.desk, "to_state", fail))
            elif stage == "metrics":
                stack.enter_context(patch.object(r.metrics, "state", fail))
            elif stage == "panel":
                stack.enter_context(patch.object(r, "panel", fail))
            elif stage in {"full", "normal"}:
                original_sync = r.ledger.set_synchronous

                def sync(full):
                    if full == (stage == "full"):
                        fail()
                    return original_sync(full)

                stack.enter_context(patch.object(r.ledger, "set_synchronous", sync))
            elif stage == "receipt":
                stack.enter_context(patch.object(r.ledger, "append_receipt", fail))
            elif stage == "kv":
                original_kv = r.ledger.set_kv

                def kv(*args):
                    original_kv(*args)
                    fail()

                stack.enter_context(patch.object(r.ledger, "set_kv", kv))
            elif stage == "commit":
                stack.enter_context(
                    patch.object(r.ledger, "_conn", CommitFailure(r.ledger._conn))
                )
            elif stage == "logs":
                stack.enter_context(patch.object(sd.log, "info", fail))
            elif stage == "mirror":
                stack.enter_context(patch.object(sd, "_atomic_json", fail))
                stack.enter_context(patch.dict(_baseline_namespace, _atomic_json=fail))
            elif stage == "replace":
                stack.enter_context(patch.object(sd.os, "replace", fail))
            with pytest.raises((RuntimeError, LedgerError), match="injected"):
                r.checkpoint(clock.now())
        assert r._settlement_cache is None
        failed = snapshot(r, clock)
        r.checkpoint(clock.now())
        return failed

    replay_pair(tmp_path, action)


def test_late_settlement_and_carry_first_partial_revise_same_day_receipts(tmp_path):
    def action(r, clock):
        last = list(r.desk.windows.values())[-1]
        midnight = BASE + 3 * 86400
        carry = Window(
            "carry", midnight - 1, midnight + 900, 80000, maker_coefficient=0.02
        )
        r.desk.add_window(carry)
        order = PracticeOrder(
            123,
            carry.slug,
            "up",
            "rest",
            0.4,
            1,
            1,
            midnight - 0.5,
            midnight,
            0.5,
            0.02,
        )
        r.desk.orders[123] = order
        r.desk._count(order.placed_at, "rest_orders", window=carry.slug)
        r.checkpoint(clock.now())
        fill = r.desk._fill(order, 0.25, midnight + 0.5)
        r.evidence.fill({**asdict(fill), "is_taker": False})
        r.record(fill.event, asdict(fill))
        result = r.desk.settle(last.slug, False, clock.now())
        r.record("speeddesk_window", asdict(result))
        r.checkpoint(clock.now())
        assert (
            Counter(x.kind for x in r.ledger.receipts())["speeddesk_daily_correction"]
            >= 1
        )
        return r.summary(utc_day(clock.now()))

    replay_pair(tmp_path, action)


def test_exotic_metaclass_hash_is_never_evaluated_by_native_guard(tmp_path):
    hash_calls = []

    class HostileMeta(type):
        def __hash__(cls):
            hash_calls.append("hash")
            return type.__hash__(cls)

        def __eq__(cls, other):
            raise AssertionError("extra metaclass equality")

    class Exotic(metaclass=HostileMeta):
        def __deepcopy__(self, memo):
            return 0.25

    def action(r, clock):
        hash_calls.clear()
        object.__setattr__(r.desk.closed[0], "fee_usd", Exotic())
        r.checkpoint(clock.now())
        return list(hash_calls)

    replay_pair(tmp_path, action)


def test_native_field_guard_tracks_canonical_dataclass_order():
    from dataclasses import fields

    assert sd._SETTLEMENT_FIELDS == tuple(field.name for field in fields(Settlement))


@pytest.mark.parametrize("count", [0, 1])
def test_zero_and_one_settlement_history(tmp_path, count):
    def action(r, clock):
        r.desk.closed = r.desk.closed[:count]
        r.checkpoint(clock.now())
        r.checkpoint(clock.now())
        return r.summary(utc_day(clock.now()))

    replay_pair(tmp_path, action)


@pytest.mark.parametrize("boundary", ["close", "midnight", "thirty_days"])
def test_exact_close_midnight_and_retention_boundaries(tmp_path, boundary):
    def action(r, clock):
        now = clock.now()
        if boundary == "close":
            r.desk.windows = {
                slug: Window(slug, now - 900, now, 80000)
                for slug in ("first-close", "second-close")
            }
            clock.script = [now - 0.01, now + 0.01] + [now] * 200
        elif boundary == "midnight":
            midnight = BASE + 4 * 86400
            clock.script = [midnight - 0.01, midnight, midnight + 0.01] * 80
        else:
            # First publish real prior reports; later calculations must preserve
            # prior old-report values only after the exact day cutoff crosses.
            r.checkpoint(now)
            threshold = BASE + 31 * 86400
            clock.script = [threshold - 0.01, threshold, threshold + 0.01] * 80
        seen = []
        original = sd.window_scorecard

        def scorecard(*args, **kwargs):
            seen.append(
                (args[0], tuple(w["slug"] for w in kwargs["windows"]), kwargs["as_of"])
            )
            return original(*args, **kwargs)

        with (
            patch.object(sd, "window_scorecard", scorecard),
            patch.dict(_baseline_namespace, window_scorecard=scorecard),
        ):
            r.checkpoint(now)
        if boundary == "close":
            assert "first-close" not in seen[0][1]
            assert "second-close" in seen[0][1]
        if boundary == "midnight":
            assert BASE + 4 * 86400 - 0.01 in clock.trace
            assert BASE + 4 * 86400 in clock.trace
        if boundary == "thirty_days":
            assert BASE + 31 * 86400 - 0.01 in clock.trace
            assert BASE + 31 * 86400 + 0.01 in clock.trace
        return seen

    replay_pair(tmp_path, action)
