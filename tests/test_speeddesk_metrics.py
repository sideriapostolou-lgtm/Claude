"""Timing is evidence only: fake clocks/transports, no private account requests."""
from __future__ import annotations

import asyncio
import math
from dataclasses import asdict, replace
from datetime import UTC, datetime

import pytest
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_speeddesk_kalshi_client import Transport, client, create
from test_speeddesk_live import TICKER, make_desk
from test_speeddesk_snapshot_cache import make_runner

from nightcrawler.clock import FakeClock
from nightcrawler.speeddesk_kalshi_client import KalshiClientError
from nightcrawler.speeddesk_live_model import ActualFill
from nightcrawler.speeddesk_metrics import (
    MAX_SAMPLES,
    LatencyMetrics,
    TickReceipt,
    tick_timings,
)
from nightcrawler.speeddesk_model import Book, Level, Window, utc_day

AT = datetime(2026, 10, 12, tzinfo=UTC).timestamp()


def test_tick_input_age_is_monotonic_and_does_not_claim_a_trigger_or_use_current_wall_clock():
    tick = TickReceipt(AT, AT + .2, 50)
    got = tick_timings(tick, 50.3)
    assert got["btc_receipt_to_decision"][0] == pytest.approx(300)
    assert got["btc_exchange_to_decision"][0] == pytest.approx(500, abs=.001)
    assert tick_timings(None, 50)["btc_receipt_to_decision"] == (None, "missing")
    assert tick_timings(tick, 49)["btc_receipt_to_decision"] == (None, "invalid")
    assert tick_timings(replace(tick, exchange_at=AT + 1), 50.3)["btc_exchange_to_decision"] == (None, "invalid")
    assert tick_timings(replace(tick, exchange_at=math.nan), 50.3)["btc_exchange_to_decision"] == (None, "invalid")


def test_exact_percentiles_separate_failure_and_missing_counts_and_survive_restore():
    metrics = LatencyMetrics(AT)
    for value in (0, 20, 40, 100):
        metrics.observe("real_kalshi", "decision_to_ack", AT + 1, value)
    for status in ("error", "timeout", "missing", "invalid"):
        metrics.observe("real_kalshi", "decision_to_ack", AT + 2, None, status)
    restored = LatencyMetrics(AT + 10, metrics.state())
    report = restored.report(utc_day(AT), "real_kalshi", real=True)["decision_to_ack"]
    assert report["observations"] == 8 and report["samples"] == 4
    assert report["errors"] == 2 and report["timeouts"] == 1
    assert report["missing"] == report["invalid"] == 1
    assert report["median_ms"] == 30 and report["p95_ms"] == 100
    assert report["started_at"] == AT and report["complete"]
    empty = restored.report(utc_day(AT), "practice_twin")["decision_to_ack"]
    assert not empty["applicable"] and empty["samples"] == 0 and empty["median_ms"] is None
    old = restored.report(utc_day(AT - 86400), "real_kalshi", real=True)["decision_to_ack"]
    assert old["samples"] is None and not old["complete"] and old["p95_ms"] is None


def test_bounded_samples_never_turn_into_a_biased_daily_percentile():
    metrics = LatencyMetrics(AT)
    for value in range(MAX_SAMPLES + 1):
        metrics.observe("real_kalshi", "decision_to_ack", AT, float(value))
    row = metrics.report(utc_day(AT), "real_kalshi", real=True)["decision_to_ack"]
    assert row["samples"] == MAX_SAMPLES + 1 and row["overflow"]
    assert row["median_ms"] is row["p95_ms"] is None and not row["complete"]
    assert len(metrics.days[utc_day(AT)]["real_kalshi"]["decision_to_ack"]["values"]) == MAX_SAMPLES
    broken = LatencyMetrics(AT, {"version": 1, "started_at": AT, "days": {"bad": {}}})
    assert broken.restore_error and broken.days == {}


def test_runner_preserves_accepted_tick_provenance_and_records_practice_intent_only(tmp_path):
    clock = FakeClock(AT + 102.5)
    runner = make_runner(tmp_path, clock)
    mono = [50.0]
    runner.monotonic = lambda: mono[0]
    try:
        runner.desk.config = replace(runner.desk.config, sigma_min_samples=1, sigma_warmup_s=0)
        window = Window("KXBTC15M-cache", AT + 100, AT + 1000, 80000, venue="kalshi", maker_coefficient=0)
        runner.on_windows([window])
        runner.on_tick(79990, AT + 100, clock.now())
        runner.on_tick(80000, AT + 101, clock.now())
        accepted = runner.tick_receipt
        mono[0] += .125
        runner.on_tick(81000, AT + 100.9, clock.now())
        assert runner.tick_receipt is accepted and runner.live_snapshot().tick_receipt is accepted
        for side in ("up", "down"):
            runner.on_book(Book(window.slug, side, (Level(.3, 2),), (Level(.6, 10),), clock.now(), "1"))
        event = runner.desk.place(window.slug, "up", "rest", .4, 1, .5, clock.now())
        assert event.event == "speeddesk_rest"
        runner.decisions([event])
        row = runner.summary(utc_day(clock.now()), "kalshi")["latency"]
        assert row["btc_receipt_to_decision"]["median_ms"] == 125
        assert row["btc_exchange_to_decision"]["median_ms"] == 1625
        assert row["decision_to_ack"]["samples"] == 0
        saved = runner.ledger.get_kv("speeddesk_state")
        assert saved["latency_metrics"]["days"]
    finally:
        runner.close()


def test_live_ack_timing_uses_monotonic_and_acceptance_never_books_a_fill(tmp_path):
    desk, account, clock = make_desk(tmp_path)
    mono = [50.0]
    desk.monotonic = lambda: mono[0]
    snapshot = replace(desk.snapshot(), tick_receipt=TickReceipt(clock.now() - .1, clock.now(), 49.8))
    desk.snapshot = lambda: snapshot
    original = account.create_order
    day = utc_day(clock.now())

    def measured(**kwargs):
        reply = original(**kwargs)
        mono[0] += .25
        clock.advance(30)  # UTC jumps cannot become order RTT.
        return reply

    account.create_order = measured
    try:
        asyncio.run(desk.step())
        row = desk.metrics.report(day, "real_kalshi", real=True)
        assert len(account.creates) == 1 and not desk.book.fills
        assert row["decision_to_ack"]["samples"] == 1
        assert row["decision_to_ack"]["median_ms"] == 250
        assert row["btc_receipt_to_decision"]["median_ms"] == pytest.approx(200)
        assert desk.metrics.report(day, "practice_twin")["decision_to_ack"]["samples"] == 0
    finally:
        desk.close()


@pytest.mark.parametrize("timeout", [True, False])
def test_uncertain_error_never_contributes_successful_ack_or_releases_reservation(tmp_path, timeout):
    desk, account, clock = make_desk(tmp_path)
    account.create_error = KalshiClientError("create_order", "transport failure", uncertain=True, timed_out=timeout)
    try:
        asyncio.run(desk.step())
        row = desk.metrics.report(utc_day(clock.now()), "real_kalshi", real=True)["decision_to_ack"]
        assert row["samples"] == 0 and row["median_ms"] is None
        assert row["errors"] == 1 and row["timeouts"] == int(timeout)
        assert desk.book.reserved_usd > 0 and len(account.creates) == 1
    finally:
        desk.close()


def test_client_classifies_timeout_without_changing_uncertainty_or_exposing_transport_text():
    transport = Transport(requests.Timeout("never print transport material"))
    with pytest.raises(KalshiClientError) as caught:
        create(client(Ed25519PrivateKey.generate(), transport))
    assert caught.value.timed_out and caught.value.uncertain
    assert len(transport.calls) == 1 and "material" not in str(caught.value)


def test_real_gate_rechecks_source_age_at_last_send_guard_even_with_fresh_receipt(tmp_path):
    desk, account, clock = make_desk(tmp_path)
    snapshot = desk.snapshot()
    snapshot = replace(snapshot, books={key: replace(book, source="websocket", requested_at=None,
                                                    exchange_at=clock.now() - 2.99)
                                        for key, book in snapshot.books.items()})
    desk.snapshot = lambda: snapshot
    original = account.create_order

    def delayed(**kwargs):
        clock.advance(.02)  # worker/rate wait: receipt is fresh, exchange input is now >3 seconds old.
        return original(**kwargs)

    account.create_order = delayed
    try:
        asyncio.run(desk.step())
        assert not account.creates
        assert desk.book.reserved_usd == 0  # definite guard rejection, no request left the fake transport
        assert desk._feed_reason(snapshot.windows[0], snapshot, clock.now()) == "Kalshi book stale"
    finally:
        desk.close()


def test_optional_actual_role_never_guesses_from_intent_or_changes_economic_equality():
    row = ActualFill("fill", "order", "client", TICKER, "up", .4, 1, .01, AT)
    assert row.is_taker is None
    known = replace(row, is_taker=True)
    assert row == known  # old missing evidence must not create a false changed-fill financial halt
    assert asdict(known)["is_taker"] is True
    assert row != replace(known, price=.41)  # economic integrity checks remain exact


def test_window_evidence_cannot_invent_coverage_across_gap_restart_or_midwindow_start():
    from nightcrawler.speeddesk_metrics import WindowEvidence

    windows = [{"slug": "w", "start": AT + 1, "end": AT + 3, "venue": "kalshi"}]
    evidence = WindowEvidence(AT)
    evidence.advance(AT + .5, windows, {"w"})
    for offset in (1, 1.5, 2, 2.5, 3):
        evidence.advance(AT + offset, windows, {"w"})
    assert evidence.coverage(windows) == {"w": True}
    restored = WindowEvidence(AT + 3, evidence.state())
    assert restored.coverage(windows) == {"w": True} and not restored.last_fresh
    gap = WindowEvidence(AT)
    gap.advance(AT + .5, windows, {"w"})
    gap.advance(AT + 3, windows, {"w"})
    assert gap.coverage(windows) == {"w": False}
    assert WindowEvidence(AT + 2).coverage(windows) == {"w": None}
    broken = WindowEvidence(AT + 2, {"started_at": "invalid"})
    assert broken.coverage(windows) == {"w": None}


def test_complete_kalshi_day_needs_all_96_windows_not_only_traded_or_discovered_subset():
    from nightcrawler.speeddesk_metrics import WindowEvidence

    windows = [{"slug": f"w{i}", "start": AT - 900 + i * 900, "end": AT + i * 900, "venue": "kalshi"}
               for i in range(96)]
    evidence = WindowEvidence(AT - 1000)
    evidence.discover(windows, AT - 1000)
    evidence.seconds = {window["slug"]: 900 for window in windows}
    assert evidence.complete_kalshi_day(utc_day(AT), windows, AT + 86400)
    assert not evidence.complete_kalshi_day(utc_day(AT), windows[:-1], AT + 86400)
    assert not evidence.complete_kalshi_day(utc_day(AT), windows, AT + 86000)
    evidence.seconds["w20"] = 899
    assert not evidence.complete_kalshi_day(utc_day(AT), windows, AT + 86400)


def test_default_paper_market_observation_is_independent_of_account_loop(tmp_path):
    desk, account, clock = make_desk(tmp_path, mode="paper", confirm=None)
    try:
        start = clock.now()
        snapshot = desk.snapshot()
        window = replace(snapshot.windows[0], start=start + 1, end=start + 3)
        desk.snapshot = lambda: replace(snapshot, windows=(window,), bitcoin_at=clock.now(),
                                        books={key: replace(book, at=clock.now(), requested_at=clock.now())
                                               for key, book in snapshot.books.items()})
        # These public observation callbacks continue even while an account
        # coroutine is waiting; they never construct a client or place an order.
        for _ in range(13):
            desk.observe_market(clock.now())
            clock.advance(.25)
        assert desk.evidence.coverage([asdict(window)])[TICKER] is True
        assert desk.client is None and account.reads == 0 and not account.creates
    finally:
        desk.close()


def test_window_clock_rollback_never_double_counts_the_recovered_interval():
    from nightcrawler.speeddesk_metrics import WindowEvidence

    windows = [{"slug": "w", "start": 1000, "end": 1900, "venue": "kalshi"}]
    evidence = WindowEvidence(1000)
    for now in (1000, 1001, 1000.5, 1001, 1002):
        evidence.advance(now, windows, {"w"})
    assert evidence.seconds["w"] == 2
    assert evidence.clock_reversals == 1
    assert evidence.coverage(windows) == {"w": False}


def test_known_stale_or_quiet_rollover_is_observed_but_not_market_freshness():
    from nightcrawler.speeddesk_metrics import WindowEvidence

    windows = [{"slug": "w", "start": AT + 1, "end": AT + 3, "venue": "kalshi"}]
    evidence = WindowEvidence(AT)
    evidence.discover(windows, AT)
    # A discovered future window's books can be absent at the exact rollover.
    # We still observed the strategy skip rather than losing its quiet window.
    for offset in (.5, 1, 1.5, 2, 2.5, 3):
        evidence.advance(AT + offset, windows, set())
    assert evidence.coverage(windows) == {"w": True}
    row = evidence.availability(windows)
    assert row["observed_window_seconds"] == 2 and row["fresh_market_window_seconds"] == 0
    assert row["fresh_market_fraction"] == 0
    late = WindowEvidence(AT)
    late.advance(AT + 1.5, windows, set())
    late.advance(AT + 2, windows, set())
    late.advance(AT + 3, windows, set())
    assert late.seconds["w"] == 1.5 and late.coverage(windows) == {"w": None}


def test_restart_keeps_discovered_history_but_does_not_credit_offline_gap():
    from nightcrawler.speeddesk_metrics import WindowEvidence

    windows = [{"slug": "w", "start": AT, "end": AT + 3, "venue": "kalshi"}]
    evidence = WindowEvidence(AT)
    evidence.discover(windows, AT)
    evidence.advance(AT + 1, windows, set())
    restored = WindowEvidence(AT + 2, evidence.state())
    restored.advance(AT + 3, windows, set())
    assert restored.seconds["w"] == 2 and restored.coverage(windows) == {"w": False}


def test_unresolved_real_intent_cannot_be_reported_as_quiet_zero_window(tmp_path):
    desk, account, clock = make_desk(tmp_path)
    account.create_error = KalshiClientError("create_order", "transport failure", uncertain=True)
    try:
        asyncio.run(desk.step())
        window = desk.book.windows[TICKER]
        desk.evidence.started_at = window.start - 1
        desk.evidence.first_seen[TICKER] = window.start - 1
        desk.evidence.seconds[TICKER] = window.end - window.start
        clock.advance(window.end - clock.now() + 1)
        report = desk.scorecard(utc_day(window.end))
        assert report["complete_windows"] == 0 and report["unknown_coverage_windows"] == 1
        assert report["pnl_usd"] is None and report["zero_fill_windows"] == 0
        assert desk.book.reserved_usd > 0
    finally:
        desk.close()


def test_companion_daily_reports_are_persisted_and_do_not_repeat_unchanged_history(tmp_path):
    desk, account, clock = make_desk(tmp_path, mode="paper", confirm=None)
    try:
        day = utc_day(clock.now())
        clock.advance(86400)
        desk.checkpoint()
        saved = desk.ledger.get_kv("kalshi_live_state")
        report = saved["reports"][day]
        assert report["real"]["scorecard"]["scope"] == "real"
        assert report["practice_twin"]["scorecard"]["scope"] == "practice_twin"
        assert report["real"]["latency"]["decision_to_ack"]["samples"] == 0
        before = dict(desk.reports)
        clock.advance(10)
        desk.checkpoint()
        assert desk.reports == before and not account.creates and account.reads == 0
    finally:
        desk.close()


@pytest.mark.parametrize("exchange_age", [None, -1.0, 3.01])
def test_missing_future_or_stale_websocket_proof_never_passes_real_gate(tmp_path, exchange_age):
    from nightcrawler.speeddesk_metrics import fresh_window_slugs

    desk, account, clock = make_desk(tmp_path)
    original = desk.snapshot()
    snapshot = replace(original, books={key: replace(book, source="websocket", requested_at=None,
                                                    exchange_at=None if exchange_age is None else clock.now() - exchange_age)
                                        for key, book in original.books.items()})
    desk.snapshot = lambda: snapshot
    try:
        asyncio.run(desk.step())
        assert not account.creates
        assert desk._feed_reason(snapshot.windows[0], snapshot, clock.now()) == "Kalshi book stale"
        assert not fresh_window_slugs([asdict(window) for window in snapshot.windows], snapshot.books,
                                      snapshot.bitcoin_at, snapshot.maker_windows, clock.now())
    finally:
        desk.close()


def test_interrupted_or_restored_intent_keeps_lost_ack_timing_visible_without_invention():
    metrics = LatencyMetrics(AT)
    metrics.decision("real_kalshi", AT, TickReceipt(AT, AT, 50), 50.1)
    restored = LatencyMetrics(AT + 5, metrics.state())
    row = restored.report(utc_day(AT), "real_kalshi", real=True)["decision_to_ack"]
    assert row["observations"] == row["missing"] == row["pending_or_lost_ack"] == 1
    assert row["samples"] == 0 and row["median_ms"] is None
    metrics.observe("real_kalshi", "decision_to_ack", AT, 200)  # original still-running worker returns
    row = metrics.report(utc_day(AT), "real_kalshi", real=True)["decision_to_ack"]
    assert row["observations"] == row["samples"] == 1 and row["missing"] == 0


def test_restart_during_clock_rollback_cannot_credit_previously_recorded_seconds_twice():
    from nightcrawler.speeddesk_metrics import WindowEvidence

    windows = [{"slug": "w", "start": 1000, "end": 1900, "venue": "kalshi"}]
    evidence = WindowEvidence(1000)
    evidence.discover(windows, 1000)
    evidence.advance(1001, windows, set())
    evidence.advance(1002, windows, set())
    restored = WindowEvidence(1001, evidence.state())
    restored.advance(1001.5, windows, set())
    restored.advance(1002, windows, set())
    restored.advance(1003, windows, set())
    assert restored.seconds["w"] == 3


def test_companion_retains_published_oldest_daily_card_after_raw_evidence_eviction(tmp_path):
    desk, _account, clock = make_desk(tmp_path, mode="paper", confirm=None)
    try:
        day = utc_day(clock.now())
        published = {"pnl_usd": .42, "day_complete": True}
        latency = {"decision_to_ack": {"samples": 1, "median_ms": 120}}
        desk.reports[day] = {"day": day, "real": {"scorecard": published, "latency": latency},
                             "practice_twin": {"scorecard": published, "latency": latency}}
        clock.advance(31 * 86400 + 3600)
        desk.checkpoint()
        assert len(desk.reports) == 31
        for scope in ("real", "practice_twin"):
            assert desk.reports[day][scope]["scorecard"] == published
            assert desk.reports[day][scope]["latency"] == latency
        assert desk.reports[day]["real"]["pnl_usd"] == 0  # canonical financial ledger remains authoritative
    finally:
        desk.close()


def test_real_gate_rechecks_entire_rest_request_age_at_last_send_guard(tmp_path):
    desk, account, clock = make_desk(tmp_path)
    original = desk.snapshot()
    snapshot = replace(original, books={key: replace(book, at=clock.now() - .1,
                                                    requested_at=clock.now() - 2.99)
                                        for key, book in original.books.items()})
    desk.snapshot = lambda: snapshot
    create_order = account.create_order

    def delayed(**kwargs):
        clock.advance(.02)  # response still fresh, but request began more than 3 seconds ago
        return create_order(**kwargs)

    account.create_order = delayed
    try:
        assert not desk._feed_reason(snapshot.windows[0], snapshot, clock.now())
        asyncio.run(desk.step())
        assert not account.creates and desk.book.reserved_usd == 0
        assert desk._feed_reason(snapshot.windows[0], snapshot, clock.now()) == "Kalshi book stale"
    finally:
        desk.close()


@pytest.mark.parametrize("requested_age", [None, -1.0, 5.9])
def test_missing_future_or_old_rest_request_proof_is_not_fresh_even_when_response_is(tmp_path, requested_age):
    from nightcrawler.speeddesk_metrics import fresh_window_slugs

    desk, account, clock = make_desk(tmp_path)
    original = desk.snapshot()
    snapshot = replace(original, books={key: replace(book, at=clock.now() - 2.95,
                                                    requested_at=None if requested_age is None else clock.now() - requested_age)
                                        for key, book in original.books.items()})
    desk.snapshot = lambda: snapshot
    try:
        asyncio.run(desk.step())
        assert not account.creates
        assert desk._feed_reason(snapshot.windows[0], snapshot, clock.now()) == "Kalshi book stale"
        assert not fresh_window_slugs([asdict(window) for window in snapshot.windows], snapshot.books,
                                      snapshot.bitcoin_at, snapshot.maker_windows, clock.now())
    finally:
        desk.close()
