"""Bounded evidence only: fakes, no account/network, no simulated-fill changes."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from test_speeddesk_live import TICKER, fill_order, make_desk

from nightcrawler.speeddesk_model import Decision, PracticeOrder
from nightcrawler.speeddesk_twin_trace import (
    MAX_PENDING,
    MAX_TERMINAL,
    TwinTrace,
    capture,
)


def order(order_id: int = 1, remaining: float = 5) -> PracticeOrder:
    return PracticeOrder(
        order_id, TICKER, "up", "rest", 0.3, 5, remaining, 100, 100.25, 0.5, 0, 10
    )


def event(name: str = "speeddesk_rest", order_id: int = 1, size: float = 5) -> Decision:
    return Decision(
        name,
        TICKER,
        "up",
        0.3,
        size,
        reason="fake_reason",
        order_id=order_id,
        at=101,
        kind="rest",
    )


def real(
    trace: TwinTrace, twin_id: int = 1, current: PracticeOrder | None = None
) -> dict[str, Any]:
    trace.real_fill(
        client_id="client",
        twin_id=twin_id,
        window=TICKER,
        side="up",
        fill_id="fill",
        venue_fill_at=101,
        observed_at=105,
        current=current,
    )
    return trace.drain()[-1]


def test_copy_and_skip_report_exact_identity_and_current_initial_queue() -> None:
    trace = TwinTrace("session")
    trace.event(
        event(), order(), parent_client_id="client", parent_twin_id=1, scope="real_copy"
    )
    trace.event(
        event("speeddesk_skip", 0),
        None,
        parent_client_id="refused",
        parent_twin_id=0,
        scope="real_copy",
    )
    copied, skipped = trace.drain()
    assert copied["parent_client_order_id"] == "client"
    assert copied["twin_queue_ahead"] == 10 and copied["twin_active_at"] == 100.25
    assert (
        skipped["practice_event"] == "speeddesk_skip" and skipped["twin_order_id"] == 0
    )
    assert skipped["reason"] == "fake_reason" and skipped["twin_queue_ahead"] is None


def test_cancel_reports_actual_pre_removal_state_and_origin_not_nearest_side() -> None:
    trace = TwinTrace("session")
    before = capture(order(2, 3))
    trace.event(
        event("speeddesk_cancel", 2, 3),
        None,
        before=before,
        parent_client_id="other-real-side",
        parent_twin_id=1,
        scope="window_except_kept",
    )
    row = trace.drain()[0]
    assert row["parent_twin_order_id"] == 1 and row["twin_order_id"] == 2
    assert (
        row["scope"] == "window_except_kept" and row["snapshot_basis"] == "pre_removal"
    )
    assert row["twin_remaining"] == 3 and row["twin_queue_ahead"] == 10
    cached = real(trace, 2)
    assert (
        cached["twin_state"] == "observed_terminal"
        and cached["terminal_state"] == "cancelled"
    )


def test_bulk_removed_cancel_has_unknown_queue_not_initial_queue() -> None:
    trace = TwinTrace("session")
    trace.event(event(), order())
    trace.event(event("speeddesk_cancel", size=3), None)
    row = real(trace)
    assert row["twin_remaining"] == 3 and row["twin_queue_ahead"] is None
    assert row["terminal_snapshot_basis"] == "event_only"


def test_partial_fill_is_not_terminal_and_full_fill_is_actual_terminal() -> None:
    trace = TwinTrace("session")
    trace.event(event("speeddesk_fill", size=2), order(remaining=3))
    assert not trace.terminal
    row = real(trace, current=order(remaining=3))
    assert row["twin_state"] == "current_order" and row["twin_remaining"] == 3
    trace.event(event("speeddesk_fill", size=3), None)
    row = real(trace)
    assert (
        row["terminal_state"] == "terminal_after_fill" and row["twin_remaining"] is None
    )
    assert (
        row["twin_queue_ahead"] is None
    )  # Never infer post-removal queue from fill quantity.


def test_real_snapshot_is_current_reconcile_clock_not_venue_execution_time() -> None:
    row = real(TwinTrace("session"), current=order(remaining=4))
    assert row["at"] == 105 and row["venue_fill_at"] == 101
    assert row["observation_basis"] == "snapshot_during_reconcile_not_venue_fill_time"
    assert (
        row["clock_basis"] == "fills_batch_return"
        and row["snapshot_time_exact"] is False
    )


@pytest.mark.parametrize("twin_id", [0, 1, 999])
def test_unmapped_absent_and_restart_mapping_remain_unknown(twin_id: int) -> None:
    row = real(TwinTrace("new-session"), twin_id)
    assert row["twin_state"] == "unknown_absent_or_unmapped"
    assert "terminal_reason" not in row and row["twin_remaining"] is None


def test_same_number_wrong_window_never_links_current_or_terminal_order() -> None:
    trace = TwinTrace("session")
    trace.event(replace(event("speeddesk_cancel"), window="other"), None)
    row = real(trace, current=replace(order(), window="other"))
    assert row["twin_state"] == "unknown_absent_or_unmapped"


def test_caches_and_emission_are_independently_bounded_with_explicit_loss_counts() -> (
    None
):
    trace = TwinTrace("session")
    for key in range(1, MAX_TERMINAL + 6):
        trace.event(event("speeddesk_cancel", key), None)
    assert len(trace.terminal) == MAX_TERMINAL
    assert len(trace.pending) == MAX_PENDING
    assert trace.terminal_evicted == 5
    assert trace.pending_dropped == MAX_TERMINAL + 5 - MAX_PENDING
    assert real(trace, 1)["twin_state"] == "unknown_absent_or_unmapped"
    assert not trace.pending


def test_oversized_identity_is_omitted_and_nonfinite_snapshot_never_enters_buffer() -> (
    None
):
    trace = TwinTrace("session")
    trace.event(event(), order(), parent_client_id="x" * 1000)
    row = trace.drain()[0]
    assert row["parent_client_order_id"] is None and row["identities_omitted"] == 1
    with pytest.raises(ValueError, match="nonfinite"):
        trace.event(event(), replace(order(), queue_ahead=float("nan")))
    with pytest.raises(ValueError, match="nonfinite"):
        trace.event(event("speeddesk_cancel", size=float("nan")), None)
    assert not trace.pending and not trace.terminal


def test_scalar_rows_are_small_json_and_diagnostic_drain_has_no_own_clock() -> None:
    trace = TwinTrace("session")
    trace.event(event(), order(), parent_client_id="client", parent_twin_id=1)
    with patch("time.time", side_effect=AssertionError("no clock")):
        row = trace.drain()[0]
    assert len(json.dumps(row, allow_nan=False)) < 1500
    assert all(
        value is None or isinstance(value, (str, int, float, bool))
        for value in row.values()
    )


def test_enabled_and_disabled_keep_real_calls_financial_state_and_regular_receipts(
    tmp_path: Path,
) -> None:
    def run(path: Path, enabled: bool) -> dict[str, Any]:
        desk, account, clock = make_desk(path)
        try:
            if not enabled:
                desk.twin_trace = None
            asyncio.run(desk.step())
            intent = next(iter(desk.intents.values()))
            asyncio.run(desk._cancel(intent, "reprice"))
            desk.checkpoint()
            receipts = [
                (row.kind, dict(row.payload))
                for row in desk.ledger.iter_receipts()
                if row.kind
                in {
                    "speeddesk_live_order",
                    "speeddesk_live_cancel",
                    "speeddesk_twin",
                    "speeddesk_live_fill",
                    "speeddesk_live_settlement",
                }
            ]
            # Only generated identities and existing measured wall timings vary between separate runs.
            for _, row in receipts:
                row.pop("timing", None)
                row.pop("stages", None)
                if "client_order_id" in row:
                    row["client_order_id"] = "generated-client"
            for create in account.creates:
                create["client_order_id"] = "generated-client"
            return {
                "creates": account.creates,
                "cancels": account.cancels,
                "risk": desk.book.risk_status(clock.now()),
                "twin": desk.twin.to_state(),
                "receipts": receipts,
            }
        finally:
            desk.close()

    enabled, disabled = (
        run(tmp_path / "enabled", True),
        run(tmp_path / "disabled", False),
    )
    # Financial state contains generated IDs too; compare exact financial quantities after removing those maps.
    assert (
        enabled["creates"] == disabled["creates"]
        and enabled["cancels"] == disabled["cancels"]
    )
    assert enabled["twin"] == disabled["twin"]
    assert enabled["risk"] == disabled["risk"]
    assert enabled["receipts"] == disabled["receipts"]


def test_extraction_or_observer_failure_cannot_block_original_cancel_or_receipt(
    tmp_path: Path,
) -> None:
    desk, account, _ = make_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        intent = next(iter(desk.intents.values()))
        with (
            patch(
                "nightcrawler.speeddesk_live.capture_twin_order",
                side_effect=RuntimeError("fake"),
            ),
            patch.object(TwinTrace, "event", side_effect=RuntimeError("fake")),
        ):
            asyncio.run(desk._cancel(intent, "reprice"))
        assert account.cancels == [intent.order_id]
        assert not desk.twin.orders
        assert desk.twin_trace_failures >= 2
        assert any(kind == "speeddesk_live_cancel" for kind, _ in desk.pending)
        assert any(
            kind == "speeddesk_twin" and row["event"] == "speeddesk_cancel"
            for kind, row in desk.pending
        )
    finally:
        desk.close()


def test_diagnostics_alone_do_not_schedule_save_or_displace_latest_events(
    tmp_path: Path,
) -> None:
    desk, _, _ = make_desk(tmp_path)
    try:
        assert desk.twin_trace is not None
        pending, latest, dirty = (
            list(desk.pending),
            list(desk.latest_events),
            desk.dirty,
        )
        desk.twin_trace.event(event(), order())
        assert (
            desk.pending == pending
            and desk.latest_events == latest
            and desk.dirty == dirty
        )
        with patch.object(desk, "clock", side_effect=AssertionError("no added clock")):
            desk._twin_trace_flush()
        assert desk.latest_events == latest
        assert any(kind == "speeddesk_twin_trace" for kind, _ in desk.pending)
    finally:
        desk.close()


def test_fill_notes_only_new_real_fill_and_cache_is_not_persistent(
    tmp_path: Path,
) -> None:
    desk, account, clock = make_desk(tmp_path)
    try:
        asyncio.run(desk.step())
        fill_order(account, clock, 0, side="up", price=0.4, size=1)
        account.account_positions = [{"ticker": TICKER, "position_fp": "1.00"}]
        asyncio.run(desk._reconcile())
        asyncio.run(desk._reconcile())
        desk.checkpoint()
        traced = [
            row.payload
            for row in desk.ledger.iter_receipts()
            if row.kind == "speeddesk_twin_trace"
            and row.payload["action"] == "real_fill_reconcile"
        ]
        assert len(traced) == 1
        assert traced[0]["venue_fill_at"] <= traced[0]["at"]
        state = desk.ledger.get_kv("kalshi_live_state")
        assert state is not None and "twin_trace" not in state
    finally:
        desk.close()


@pytest.mark.parametrize(
    "bad",
    [
        iter([None]),
        [{"at": 100, "bad": object()}],
        [{}],
        [{"at": float("nan")}],
        [{"at": 100}] * (MAX_PENDING + 1),
    ],
)
def test_malformed_observer_batch_cannot_enter_financial_pending(
    tmp_path: Path, bad: object
) -> None:
    desk, _, _ = make_desk(tmp_path)
    try:
        original = list(desk.pending)
        with patch.object(TwinTrace, "drain", return_value=bad):
            desk._twin_trace_flush()
        assert desk.pending == original
        assert desk.twin_trace_failures >= 1
        desk.checkpoint()  # Original state/financial persistence remains usable.
    finally:
        desk.close()


def test_malformed_observer_status_is_diagnostic_only(tmp_path: Path) -> None:
    desk, _, _ = make_desk(tmp_path)
    try:
        with patch.object(TwinTrace, "status", return_value=42):
            assert desk._twin_trace_panel()["helper_error"] == "ValueError"
        desk.checkpoint()
    finally:
        desk.close()


def test_repeated_failed_checkpoint_flushes_cannot_accumulate_diagnostics(
    tmp_path: Path,
) -> None:
    desk, _, _ = make_desk(tmp_path)
    try:
        assert desk.twin_trace is not None
        original = list(desk.pending)
        for _ in range(3 * MAX_PENDING):
            desk.twin_trace.event(event(), order())
        desk._twin_trace_flush()
        for _ in range(100):
            desk.twin_trace.event(event(), order())
            desk._twin_trace_flush()  # Prior checkpoint's pending rows have not committed/cleared.
        assert (
            len([kind for kind, _ in desk.pending if kind == "speeddesk_twin_trace"])
            == MAX_PENDING
        )
        assert desk.pending[: len(original)] == original
        assert len(desk.twin_trace.pending) <= MAX_PENDING
        desk.checkpoint()
        assert not desk._twin_trace_in_pending
    finally:
        desk.close()


def test_snapshot_requires_exact_order_number_even_if_terms_match() -> None:
    row = real(TwinTrace("session"), twin_id=1, current=order(2))
    assert row["twin_state"] == "unknown_absent_or_unmapped"
