"""The town's money details come from validated saved real books, never a client."""

from __future__ import annotations

import copy
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from nightcrawler import moneyconnections as C
from nightcrawler.speeddesk_live_model import (
    ActualFill,
    LiveLimits,
    LiveRiskBook,
    OrderSnapshot,
)
from nightcrawler.speeddesk_model import Window


def ts(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


NOW = ts("2026-10-13T03:00:00Z")
START = ts("2026-10-12T07:00:00Z")
WINDOW = "KXBTC15M-TEST-PARTIAL"


def text(value: Any, limit: int = 300) -> str:
    return str(value)[:limit]


def kalshi_state(book: LiveRiskBook, *, now: float = NOW) -> dict[str, Any]:
    """Same durable book envelope as the companion checkpoint, with fake cash."""
    return {"version": 1, "started_at": START - 1000, "updated_at": now,
            "book": json.loads(json.dumps(book.to_state())), "intents": {},
            "latest_events": [], "panel": {"as_of": now, "cash_at": now, "cash_usd": 25,
                                           "mode": "paper", "authenticated": False}}


def partial_book(*, now: float = NOW) -> LiveRiskBook:
    book = LiveRiskBook(LiveLimits(fee_precision=.0001))
    book.add_window(Window(WINDOW, now - 100, now + 800, 100,
                           taker_coefficient=.07, maker_coefficient=0, venue="kalshi"))
    book.update_cash(25, now - 90)
    intent = book.reserve_intent(WINDOW, "up", "take", .4, 2, now - 90,
                                 "nc-speed-test-partial", .6)
    assert book.record_fill(ActualFill("test-fill", "test-order", intent.client_order_id,
                                      WINDOW, "up", .4, .5, .007, now - 89, True))
    book.request_cancel(intent.client_order_id)
    book.mark_uncertain(intent.client_order_id, "cancel_timeout")
    # Validate fixtures independently: rebuilding never talks to the exchange.
    LiveRiskBook.from_state(book.to_state())
    return book


def add_settlement(book: LiveRiskBook, index: int, at: float, *, won: bool = True) -> None:
    slug = f"KXBTC15M-TEST-SETTLED-{index}"
    book.add_window(Window(slug, at - 900, at, 100,
                           taker_coefficient=.07, maker_coefficient=0, venue="kalshi"))
    book.update_cash(25, at - 890)
    intent = book.reserve_intent(slug, "up", "take", .4, 1, at - 890,
                                 f"nc-speed-settled-{index}", .6)
    assert book.record_fill(ActualFill(f"fill-{index}", f"order-{index}", intent.client_order_id,
                                      slug, "up", .4, 1, .0168, at - 889))
    assert book.settle(slug, won, at, f"settlement-{index}") is not None


def pm_row(slug: str, *, now: float = NOW, **extra: Any) -> dict[str, Any]:
    return {"slug": slug, "question": f"Will {slug} win?", "live": True, "rule": "crypto",
            "side": "long", "shares": 2, "p_in": .97, "cost_usd": 1.94,
            "fee_usd": .004045, "t_in": now - 100, "end_ts": now + 900,
            "order_id": f"order-{slug}", **extra}


def pm_state(rows: list[dict[str, Any]] | None = None, *, now: float = NOW) -> dict[str, Any]:
    rows = rows or []
    days: dict[str, Any] = {}
    for row in rows:
        if row.get("live") is not True or row.get("owner") or row.get("rule") == "owner" or row.get("unresolved"):
            continue
        day = datetime.fromtimestamp(row["settled_at"], UTC).date().isoformat()
        rec = days.setdefault(day, {"settled": 0, "pnl_usd": 0.0})
        rec["settled"] += 1
        rec["pnl_usd"] += row["pnl_usd"]
    return {"version": 1, "owner_migrated": True, "last_ok": now, "last_poll": now,
            "mode": "live", "live_status": None, "positions": {}, "pending_orders": {},
            "closed": rows, "live_days": days, "balance": {"cash": 14.39, "at": now},
            "exchange": {"at": now, "positions": 0}}


def persist(root: Path, relative: str, value: Any) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def test_partial_real_fill_and_cancel_uncertainty_stay_separate_from_paper_mode() -> None:
    raw = kalshi_state(partial_book())
    before = copy.deepcopy(raw)
    got = C.kalshi_connection(raw, NOW, text)
    assert raw == before
    assert got["status"] == "ok" and not got["stale"]
    assert got["venue_positions_at"] is None
    assert got["as_of"] == NOW and got["cash_at"] == NOW
    assert len(got["positions"]) == len(got["orders"]) == 1
    position = got["positions"][0]
    assert position["scope"] == "bot" and position["side"] == "YES"
    assert position["quantity"] == .5 and position["price"] == .4
    assert position["cost_usd"] == pytest.approx(.2) and position["fee_usd"] == .007
    order = got["orders"][0]
    assert order["cancel_requested"] is True and order["reservation_active"] is True
    assert got["open_cost_usd"] == pytest.approx(.207)
    assert got["reserved_usd"] == pytest.approx(.63)
    assert got["at_risk_usd"] == pytest.approx(.837)
    fills = [event for event in got["events"] if event["type"] == "fill"]
    assert len(fills) == 1
    assert fills[0]["quantity"] == .5 and fills[0]["fee_usd"] == .007
    assert fills[0]["ts"] == NOW - 89 and fills[0]["pnl_usd"] is None
    assert fills[0]["real"] is True and fills[0]["scope"] == "bot"


def test_confirmed_partial_cancel_clears_only_the_order_and_retains_actual_holding() -> None:
    book = partial_book()
    intent = next(iter(book.intents.values()))
    assert book.reconcile_order(OrderSnapshot(intent.client_order_id, "test-order", "canceled", .5, 0, NOW),
                                fills_complete=True)
    got = C.kalshi_connection(kalshi_state(book), NOW, text)
    assert got["positions"][0]["quantity"] == .5
    assert not any(order["reservation_active"] for order in got["orders"])


def test_repeated_terminal_order_reads_do_not_become_new_cancellation_events() -> None:
    book = partial_book()
    intent = next(iter(book.intents.values()))
    assert book.reconcile_order(OrderSnapshot(intent.client_order_id, "test-order", "canceled", .5, 0, NOW - 10),
                                fills_complete=True)
    first = C.kalshi_connection(kalshi_state(book, now=NOW - 10), NOW, text)
    # Production assigns the observation clock on every fully paginated order
    # read; an old cancellation can therefore have a brand-new last_snapshot_at.
    assert book.reconcile_order(OrderSnapshot(intent.client_order_id, "test-order", "canceled", .5, 0, NOW),
                                fills_complete=True)
    second = C.kalshi_connection(kalshi_state(book), NOW, text)
    assert not any(event["type"] == "cancel" for event in first["events"] + second["events"])
    assert {(row["id"], row["ts"]) for row in first["events"]} == {
        (row["id"], row["ts"]) for row in second["events"]}
    assert any("no retained event time" in issue for issue in second["issues"])
    assert second["orders"] == [] and second["positions"][0]["quantity"] == .5


@pytest.mark.parametrize("state", ["requested; reservation retained until fills reconcile",
                                  "not resting on Kalshi (404); reservation retained until reconciled"])
def test_cancel_request_receipt_never_claims_or_animates_terminal_confirmation(state: str) -> None:
    book = partial_book()
    intent = next(iter(book.intents.values()))
    raw = kalshi_state(book)
    raw["latest_events"] = [{"event": "speeddesk_live_cancel", "client_order_id": intent.client_order_id,
                             "at": NOW - 5, "state": state}]
    before = copy.deepcopy(raw)
    got = C.kalshi_connection(raw, NOW, text)
    cancel, = [event for event in got["events"] if event["type"] == "cancel"]
    assert cancel["ts"] == NOW - 5 and cancel["qualified"] is False
    assert "requested" in cancel["text"] and "request" in cancel["time_source"]
    assert got["orders"][0]["reservation_active"] is True
    assert got["reserved_usd"] == pytest.approx(.63) and raw == before
    # A later terminal snapshot can release the reserve, but cannot turn that
    # earlier request timestamp into a terminal-event timestamp.
    assert book.reconcile_order(OrderSnapshot(intent.client_order_id, "test-order", "canceled", .5, 0, NOW),
                                fills_complete=True)
    raw["book"] = book.to_state()
    after = C.kalshi_connection(raw, NOW, text)
    assert [event for event in after["events"] if event["type"] == "cancel"] == [cancel]


@pytest.mark.parametrize("outcome", [True, False, None])
def test_ended_mixed_account_window_remains_visible_without_claiming_current_exposure(outcome: bool | None) -> None:
    book = partial_book(now=NOW - 1800)
    intent = next(iter(book.intents.values()))
    assert book.reconcile_order(OrderSnapshot(intent.client_order_id, "test-order", "canceled", .5, 0, NOW),
                                fills_complete=True)
    raw = kalshi_state(book)
    raw.update(foreign_windows=[WINDOW], final_outcomes={WINDOW: outcome})
    raw["panel"]["positions"] = 0  # aggregate account count is not a row-level reconciliation receipt
    before = copy.deepcopy(raw)
    got = C.kalshi_connection(raw, NOW, text)
    holding, = got["positions"]
    assert holding["quantity"] == .5 and holding["cost_usd"] == .2
    assert holding["current_position_verified"] is False and holding["mixed_account_activity"] is True
    assert holding["end_at"] == NOW - 1000
    assert holding["status"] == ("finalized_unreconciled" if outcome is not None else "ended_unreconciled")
    expected_outcome = ("YES" if outcome else "NO") if outcome is not None else None
    assert holding["final_outcome"] == expected_outcome
    assert "account position" in holding["status_note"]
    assert any("Ended windows" in issue for issue in got["issues"])
    assert got["open_cost_usd"] == pytest.approx(.207) and got["at_risk_usd"] == pytest.approx(.207)
    assert not any(event["type"] == "settlement" for event in got["events"])
    assert raw == before


def test_settled_mixed_account_window_does_not_leave_gross_holdings_in_open_rows() -> None:
    book = LiveRiskBook(LiveLimits(fee_precision=.0001))
    add_settlement(book, 0, NOW - 1)
    raw = kalshi_state(book)
    slug = next(iter(book.settled))
    raw.update(foreign_windows=[slug], final_outcomes={slug: True})
    got = C.kalshi_connection(raw, NOW, text)
    assert got["positions"] == [] and got["open_cost_usd"] == 0
    assert len([event for event in got["events"] if event["type"] == "settlement"]) == 1


def test_live_lock_orders_and_reset_approval_restore_read_only() -> None:
    book = LiveRiskBook(LiveLimits(fee_precision=.0001))
    book.add_window(Window(WINDOW, NOW - 700, NOW + 200, 100,
                           taker_coefficient=.07, maker_coefficient=0, venue="kalshi"))
    book.update_cash(25, NOW - 690)
    first = book.reserve_intent(WINDOW, "up", "take", .4, 1, NOW - 690, "nc-speed-before-lock", .6)
    assert book.record_fill(ActualFill("first-fill", "first-order", first.client_order_id,
                                      WINDOW, "up", .4, 1, .0168, NOW - 689))
    book.update_cash(25, NOW - 10)
    book.reserve_intent(WINDOW, "down", "take", .55, 1, NOW - 10, "nc-speed-display-lock", lock=True)
    raw = kalshi_state(book)
    before = copy.deepcopy(raw)
    got = C.kalshi_connection(raw, NOW, text)
    assert got["status"] == "ok" and got["orders"][0]["lock"] is True
    assert got["reserved_usd"] > 0 and got["at_risk_usd"] == book.open_loss_usd
    assert raw == before

    book.integrity_error = "settlement_net_payout_mismatch"
    assert book.arm_integrity_reset("fake-owner-reset-for-projection-test") == "armed"
    raw = kalshi_state(book)
    before = copy.deepcopy(raw)
    got = C.kalshi_connection(raw, NOW, text)
    assert raw == before and raw["book"]["integrity_reset_armed"] == "settlement_net_payout_mismatch"
    assert got["status"] == "incomplete" and got["today_pacific"]["pnl_usd"] is None
    assert not any(event["qualified"] for event in got["events"])


def test_display_restore_does_not_share_mutable_execution_book_dictionaries() -> None:
    book = LiveRiskBook(LiveLimits(fee_precision=.0001))
    add_settlement(book, 0, NOW - 1)
    raw = book.to_state()
    before = copy.deepcopy(raw)
    restored = C._kalshi_book(raw, NOW)
    restored.day_pnl.clear()
    restored.bootstrap_order.clear()
    assert raw == before


@pytest.mark.parametrize("corruption", ["inventory", "filled_size", "fill_fee", "realized", "day"])
def test_inconsistent_kalshi_book_never_emits_money_events_or_a_partial_profit(corruption: str) -> None:
    book = LiveRiskBook(LiveLimits(fee_precision=.0001))
    add_settlement(book, 0, START + 1800)
    raw = kalshi_state(book)
    durable = raw["book"]
    if corruption == "inventory":
        next(iter(durable["inventory"].values()))["up"]["shares"] += 1
    elif corruption == "filled_size":
        next(iter(durable["intents"].values()))["filled_size"] += 1
    elif corruption == "fill_fee":
        next(iter(durable["fills"].values()))["fee_usd"] += .01
    elif corruption == "realized":
        durable["realized_pnl"] += .01
    else:
        durable["day_pnl"]["2026-10-12"] += .01
    got = C.kalshi_connection(raw, NOW, text)
    assert got["status"] == "incomplete" and got["issues"]
    assert got["events"] == [] and got["positions"] == []
    assert got["today_pacific"]["status"] != "ok"
    assert got["today_pacific"]["pnl_usd"] is None


def test_kalshi_pacific_total_uses_full_book_and_fees_once_even_when_events_are_capped() -> None:
    book = LiveRiskBook(LiveLimits(fee_precision=.0001))
    # Seventy completed real windows in this Pacific day; display lists retain at most fifty.
    for index in range(70):
        add_settlement(book, index, START + 1000 + index * 900)
    raw = kalshi_state(book)
    got = C.kalshi_connection(raw, NOW, text)
    assert got["today_pacific"]["status"] == "ok"
    assert got["today_pacific"]["settled"] == 70
    assert got["today_pacific"]["pnl_usd"] == pytest.approx(70 * (1 - .4 - .0168))
    assert len(got["events"]) <= 50 and got["truncated"]
    assert got["positions"] == []
    assert raw["book"]["day_pnl"] == book.to_state()["day_pnl"]


def test_kalshi_pacific_profit_crosses_utc_midnight_and_excludes_prior_local_day() -> None:
    book = LiveRiskBook(LiveLimits(fee_precision=.0001))
    add_settlement(book, 0, START - 1)
    add_settlement(book, 1, START + 1000)
    add_settlement(book, 2, ts("2026-10-13T01:00:00Z"), won=False)
    got = C.kalshi_connection(kalshi_state(book), NOW, text)["today_pacific"]
    assert got["date"] == "2026-10-12" and got["settled"] == 2
    assert got["pnl_usd"] == pytest.approx(.5832 - .4168)


def test_same_fill_keeps_stable_id_across_reload_and_row_reordering() -> None:
    book = LiveRiskBook(LiveLimits(fee_precision=.0001))
    add_settlement(book, 0, START + 1000)
    add_settlement(book, 1, START + 2000)
    raw = kalshi_state(book)
    first = C.kalshi_connection(raw, NOW, text)["events"]
    reordered = json.loads(json.dumps(raw))
    for key in ("fills", "settled", "intents", "inventory", "windows"):
        reordered["book"][key] = dict(reversed(list(reordered["book"][key].items())))
    second = C.kalshi_connection(reordered, NOW + 1, text)["events"]
    assert {event["id"] for event in first} == {event["id"] for event in second}
    assert len({event["id"] for event in first}) == len(first)
    assert all(event["id"] not in {"fill-0", "fill-1", "settlement-0", "settlement-1"} for event in first)


def test_stale_kalshi_snapshot_keeps_evidence_age_but_cannot_qualify_fresh_animation() -> None:
    raw = kalshi_state(partial_book(now=NOW - 7200), now=NOW - 7200)
    got = C.kalshi_connection(raw, NOW, text)
    assert got["stale"] and got["as_of"] == NOW - 7200
    assert all(event["qualified"] is False for event in got["events"])


def test_zero_net_kalshi_position_still_shows_both_actual_gross_holdings() -> None:
    book = LiveRiskBook(LiveLimits(fee_precision=.0001))
    book.add_window(Window(WINDOW, NOW - 100, NOW + 800, 100,
                           taker_coefficient=.07, maker_coefficient=0, venue="kalshi"))
    book.update_cash(25, NOW - 90)
    for side in ("up", "down"):
        intent = book.reserve_intent(WINDOW, side, "take", .4, 1, NOW - 90,
                                     f"nc-speed-paired-{side}", .6)
        assert book.record_fill(ActualFill(f"fill-{side}", f"order-{side}", intent.client_order_id,
                                          WINDOW, side, .4, 1, .0168, NOW - 89))
    assert book.expected_position(WINDOW) == 0
    got = C.kalshi_connection(kalshi_state(book), NOW, text)
    assert len(got["positions"]) == 2
    assert {row["side"] for row in got["positions"]} == {"YES", "NO"}
    assert sum(row["quantity"] for row in got["positions"]) == 2
    assert got["today_pacific"]["pnl_usd"] == 0
    assert all(event["pnl_usd"] is None for event in got["events"])


def test_pm_owner_and_paper_stay_out_of_bot_events_and_profit() -> None:
    rows = [pm_row("bot-done", settled_at=START + 1000, pnl_usd=.056),
            pm_row("owner-done", settled_at=START + 2000, pnl_usd=100, owner=True, rule="owner"),
            pm_row("paper-done", settled_at=START + 3000, pnl_usd=200, live=False)]
    raw = pm_state(rows)
    raw["positions"] = {"bot": pm_row("bot"), "owner": pm_row("owner", owner=True, rule="owner"),
                        "paper": pm_row("paper", live=False)}
    before = copy.deepcopy(raw)
    got = C.polymarket_connection(raw, NOW, text)
    assert raw == before
    assert got["status"] == "ok"
    assert {row["scope"] for row in got["positions"]} == {"bot", "owner"}
    assert len(got["positions"]) == 2
    assert got["today_pacific"]["pnl_usd"] == .056 and got["today_pacific"]["settled"] == 1
    assert all(event["scope"] == "bot" and event["real"] is True for event in got["events"])
    assert not any("owner" in event["market"] or "paper" in event["market"] for event in got["events"])


def test_populated_pm_lists_are_bounded_without_losing_full_source_counts() -> None:
    raw = pm_state()
    raw["positions"] = {f"held-{index}": pm_row(f"held-{index}", now=NOW - index) for index in range(70)}
    raw["pending_orders"] = {
        f"pending-{index}": {"contracts": 2, "limit": .97, "fee_coef": .0695,
                             "t_in": NOW - index - 1, "order_id": f"pending-order-{index}",
                             "rule": "crypto", "question": f"Pending market {index}"}
        for index in range(70)
    }
    got = C.polymarket_connection(raw, NOW, text)
    assert got["status"] == "ok"
    for name in ("positions", "orders", "events"):
        assert len(got[name]) == C.MAX_ROWS
        assert got["truncated"][name] is True
    assert got["counts"] == {"positions": 70, "orders": 70, "events": 140}
    assert got["today_pacific"]["status"] == "ok" and got["today_pacific"]["pnl_usd"] == 0


def test_pm_booked_profit_is_not_charged_the_estimated_fill_fee_twice() -> None:
    raw = pm_state([pm_row("settled", settled_at=NOW - 10, pnl_usd=.055955)])
    got = C.polymarket_connection(raw, NOW, text)
    settlement = next(event for event in got["events"] if event["type"] == "settlement")
    assert settlement["pnl_usd"] == .055955
    assert got["today_pacific"]["pnl_usd"] == .055955


def test_pm_moving_a_confirmed_fill_to_closed_does_not_invent_a_second_fill_identity() -> None:
    position = pm_row("lineage")
    before = pm_state()
    before["positions"] = {"lineage": position}
    first = C.polymarket_connection(before, NOW, text)
    after = pm_state([{**position, "settled_at": NOW, "pnl_usd": .055955}], now=NOW + 1)
    second = C.polymarket_connection(after, NOW + 1, text)
    first_ids = {event["id"] for event in first["events"] if event["type"] == "fill"}
    second_ids = {event["id"] for event in second["events"] if event["type"] == "fill"}
    assert first_ids and first_ids == second_ids
    assert len([event for event in second["events"] if event["type"] == "settlement"]) == 1


def test_partial_cashout_preserves_holding_and_booked_profit_without_inventing_original_fill_size() -> None:
    original = pm_row("split-order")
    initial = pm_state()
    initial["positions"] = {"split-order": original}
    before = C.polymarket_connection(initial, NOW, text)
    original_fill_id = next(event["id"] for event in before["events"] if event["type"] == "fill")

    fragment = {**original, "shares": 1, "cost_usd": .97, "fee_usd": .0020225}
    raw = pm_state([{**fragment, "sold_in_app": True, "sale_id": "fake-partial-sale",
                     "settled_at": NOW - 10, "pnl_usd": .0279775}])
    raw["positions"] = {"split-order": fragment}
    got = C.polymarket_connection(raw, NOW, text)

    assert got["status"] == "ok"
    assert len(got["positions"]) == 1 and got["positions"][0]["quantity"] == 1
    fills = [event for event in got["events"] if event["type"] == "fill"]
    assert len(fills) == 1 and fills[0]["id"] == original_fill_id
    assert fills[0]["qualified"] is False
    assert fills[0]["quantity"] is None and fills[0]["fee_usd"] is None
    assert "not verified" in fills[0]["text"]
    settlements = [event for event in got["events"] if event["type"] == "settlement"]
    assert len(settlements) == 1 and settlements[0]["pnl_usd"] == .0279775
    assert got["today_pacific"]["pnl_usd"] == .0279775


def test_pm_missing_retained_result_does_not_look_like_complete_pacific_profit() -> None:
    raw = pm_state([pm_row("one", settled_at=START + 1000, pnl_usd=.02),
                    pm_row("missing", settled_at=START + 2000, pnl_usd=.03)])
    raw["closed"].pop()
    got = C.polymarket_connection(raw, NOW, text)
    assert got["today_pacific"]["status"] == "incomplete"
    assert got["today_pacific"]["pnl_usd"] is None


@pytest.mark.parametrize("field,value", [
    ("live", "true"), ("live", 1), ("owner", "false"),
    ("shares", True), ("shares", math.nan), ("shares", -1), ("fee_usd", math.inf),
])
def test_malformed_pm_real_holding_cannot_become_a_qualified_fill(field: str, value: Any) -> None:
    raw = pm_state()
    raw["positions"] = {"invalid": pm_row("invalid", **{field: value})}
    got = C.polymarket_connection(raw, NOW, text)
    assert not any(event["type"] == "fill" and event["qualified"] for event in got["events"])


def test_pm_tracked_positions_do_not_claim_the_aggregate_exchange_timestamp_as_row_proof() -> None:
    raw = pm_state()
    raw["positions"] = {"bot": pm_row("bot")}
    raw["exchange"]["at"] = NOW - 1200
    got = C.polymarket_connection(raw, NOW, text)
    assert got["venue_positions_at"] == NOW - 1200
    assert got["positions_basis"] and got["source_note"]
    assert got["positions"][0]["opened_at"] == NOW - 100


def test_polymarket_normal_ninety_second_poll_interval_does_not_flicker_stale() -> None:
    # POLYDESK_POLL_S defaults to 90 seconds; the existing town PM threshold is 600.
    got = C.polymarket_connection(pm_state(now=NOW - 90), NOW, text)
    assert got["as_of"] == NOW - 90 and got["stale"] is False
    assert C.polymarket_connection(pm_state(now=NOW - 601), NOW, text)["stale"] is True
    kalshi = kalshi_state(partial_book(now=NOW - 90), now=NOW - 90)
    assert C.kalshi_connection(kalshi, NOW, text)["stale"] is True


def test_pending_order_cost_overflow_never_reaches_the_json_response_as_infinity() -> None:
    raw = pm_state()
    raw["pending_orders"] = {"invalid": {"contracts": 1e308, "limit": .97, "fee_coef": 1e308,
                                         "t_in": NOW - 1, "question": "Invalid retained amount"}}
    got = C.polymarket_connection(raw, NOW, text)
    json.dumps(got, allow_nan=False)
    assert got["status"] != "ok"
    assert not any(event["qualified"] for event in got["events"])


@pytest.mark.parametrize("builder", [C.kalshi_connection, C.polymarket_connection])
@pytest.mark.parametrize("stamp", [None, False, NOW + 1000, math.inf, math.nan])
def test_invalid_source_timestamp_never_qualifies_financial_animation(builder: Any, stamp: Any) -> None:
    raw = kalshi_state(partial_book()) if builder is C.kalshi_connection else pm_state()
    if builder is C.kalshi_connection:
        raw["updated_at"] = stamp
        raw["panel"]["as_of"] = stamp
    else:
        raw["last_ok"] = stamp
    got = builder(raw, NOW, text)
    assert got["stale"]
    assert all(event["qualified"] is False for event in got["events"])


@pytest.mark.parametrize("iso,hours,start,end", [
    ("2026-03-08T20:00:00Z", 23, "2026-03-08T08:00:00Z", "2026-03-09T07:00:00Z"),
    ("2026-11-01T20:00:00Z", 25, "2026-11-01T07:00:00Z", "2026-11-02T08:00:00Z"),
])
def test_both_connections_respect_pacific_dst_days(iso: str, hours: int, start: str, end: str) -> None:
    now = ts(iso)
    book = LiveRiskBook(LiveLimits(fee_precision=.0001))
    for got in (C.polymarket_connection(pm_state(now=now), now, text),
                C.kalshi_connection(kalshi_state(book, now=now), now, text)):
        day = got["today_pacific"]
        assert day["status"] == "ok" and day["pnl_usd"] == 0
        assert day["start"] == ts(start) and day["end"] == ts(end)
        assert day["end"] - day["start"] == hours * 3600


def test_loader_reads_only_saved_sources_and_never_rewrites_them(tmp_path: Path) -> None:
    first = persist(tmp_path, "polydesk/state.json", pm_state())
    second = persist(tmp_path, "speeddesk/kalshi_live/state.json", kalshi_state(partial_book()))
    original = {path: path.read_bytes() for path in (first, second)}
    got = C.load_connections(tmp_path, NOW, text)
    assert got["version"] == 1
    assert got["polymarket_us"]["status"] == got["kalshi"]["status"] == "ok"
    assert {path: path.read_bytes() for path in original} == original


def test_loader_observes_each_checkpoint_after_reading_during_a_page_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = NOW
    read_saved = C._read_saved
    reads: list[Path] = []
    clock_reads: list[float] = []

    def checkpoint_then_read(path: Path) -> tuple[Any, str | None]:
        nonlocal observed
        # Another thread completes a checkpoint after the page request starts.
        observed += 1
        if "polydesk" in path.parts:
            state = pm_state(now=observed)
        else:
            book = partial_book(now=observed)
            intent = next(iter(book.intents.values()))
            assert book.reconcile_order(OrderSnapshot(intent.client_order_id, "test-order", "canceled",
                                                      .5, 0, observed), fills_complete=True)
            state = kalshi_state(book, now=observed)
        persist(tmp_path, str(path.relative_to(tmp_path)), state)
        reads.append(path)
        return read_saved(path)

    def read_clock() -> float:
        assert len(reads) == len(clock_reads) + 1
        clock_reads.append(observed)
        return observed

    monkeypatch.setattr(C, "_read_saved", checkpoint_then_read)
    got = C.load_connections(tmp_path, NOW, text, read_clock=read_clock)
    assert clock_reads == [NOW + 1, NOW + 2]
    for venue, stamp in (("polymarket_us", NOW + 1), ("kalshi", NOW + 2)):
        assert got[venue]["status"] == "ok" and not got[venue]["stale"]
        assert got[venue]["as_of"] == got[venue]["cash_at"] == stamp
    assert got["kalshi"]["positions"][0]["quantity"] == .5


def test_loader_still_rejects_source_and_order_times_beyond_the_observation(tmp_path: Path) -> None:
    future = NOW + 2.001
    persist(tmp_path, "polydesk/state.json", pm_state(now=future))
    book = partial_book(now=future)
    intent = next(iter(book.intents.values()))
    assert book.reconcile_order(OrderSnapshot(intent.client_order_id, "test-order", "canceled", .5, 0, future),
                                fills_complete=True)
    persist(tmp_path, "speeddesk/kalshi_live/state.json", kalshi_state(book, now=future))
    got = C.load_connections(tmp_path, NOW, text, read_clock=lambda: NOW + 2)
    for venue in ("polymarket_us", "kalshi"):
        assert got[venue]["as_of"] is None and got[venue]["stale"]
        assert not any(event["qualified"] for event in got[venue]["events"])
    assert got["kalshi"]["status"] == "incomplete" and got["kalshi"]["positions"] == []


def test_loader_observation_time_ages_old_checkpoints_without_freshening_them(tmp_path: Path) -> None:
    pm_at, kalshi_at = NOW - 590, NOW - 40
    persist(tmp_path, "polydesk/state.json", pm_state(now=pm_at))
    persist(tmp_path, "speeddesk/kalshi_live/state.json", kalshi_state(partial_book(now=kalshi_at), now=kalshi_at))
    initial = C.load_connections(tmp_path, NOW, text)
    observed = C.load_connections(tmp_path, NOW, text, read_clock=lambda: NOW + 30)
    for venue, stamp in (("polymarket_us", pm_at), ("kalshi", kalshi_at)):
        assert initial[venue]["stale"] is False and observed[venue]["stale"] is True
        assert observed[venue]["as_of"] == observed[venue]["cash_at"] == stamp
        assert not any(event["qualified"] for event in observed[venue]["events"])


@pytest.mark.parametrize("stamp", [NOW - 1, math.nan, math.inf, -math.inf, False, None, "invalid"])
def test_invalid_read_clock_falls_back_to_request_time_without_relabeling_sources(tmp_path: Path, stamp: Any) -> None:
    persist(tmp_path, "polydesk/state.json", pm_state())
    persist(tmp_path, "speeddesk/kalshi_live/state.json", kalshi_state(partial_book()))
    assert C.load_connections(tmp_path, NOW, text, read_clock=lambda: stamp) == C.load_connections(tmp_path, NOW, text)


def test_default_loader_does_not_advance_the_callers_clock_for_newer_checkpoints(tmp_path: Path) -> None:
    persist(tmp_path, "polydesk/state.json", pm_state(now=NOW + 1))
    got = C.load_connections(tmp_path, NOW, text)
    assert got["polymarket_us"]["as_of"] is None and got["polymarket_us"]["stale"]


def test_missing_sources_are_unknown_instead_of_empty_real_accounts(tmp_path: Path) -> None:
    got = C.load_connections(tmp_path, NOW, text)
    for venue in ("kalshi", "polymarket_us"):
        assert got[venue]["status"] == "unavailable"
        assert got[venue]["events"] == got[venue]["positions"] == []
        assert got[venue]["today_pacific"]["pnl_usd"] is None


def test_later_read_clock_cannot_establish_an_empty_account_from_missing_sources(tmp_path: Path) -> None:
    got = C.load_connections(tmp_path, NOW, text, read_clock=lambda: NOW + 2)
    for venue in ("kalshi", "polymarket_us"):
        assert got[venue]["status"] == "unavailable" and got[venue]["as_of"] is None
        assert got[venue]["positions"] == got[venue]["events"] == []
        assert got[venue]["cash_usd"] is None and got[venue]["today_pacific"]["pnl_usd"] is None


def test_prior_pacific_day_snapshot_does_not_establish_a_new_day_zero() -> None:
    before = ts("2026-10-13T06:59:59Z")
    after = before + 1
    empty = LiveRiskBook(LiveLimits(fee_precision=.0001))
    for connection in (C.kalshi_connection(kalshi_state(empty, now=before), after, text),
                       C.polymarket_connection(pm_state(now=before), after, text)):
        assert connection["today_pacific"]["status"] != "ok"
        assert connection["today_pacific"]["pnl_usd"] is None


@pytest.mark.parametrize("content", ["{", "[]", "null", '{"version": 987}'])
def test_corrupt_source_cannot_create_money_events(tmp_path: Path, content: str) -> None:
    for relative in ("polydesk/state.json", "speeddesk/kalshi_live/state.json"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    got = C.load_connections(tmp_path, NOW, text)
    for venue in ("kalshi", "polymarket_us"):
        assert got[venue]["status"] != "ok"
        assert got[venue]["events"] == []
        assert got[venue]["today_pacific"]["pnl_usd"] is None


def test_oversized_source_is_rejected_before_its_contents_are_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for relative in ("polydesk/state.json", "speeddesk/kalshi_live/state.json"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as stream:
            stream.truncate(C.MAX_SOURCE_BYTES + 1)

    def forbidden_read(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("An oversized financial snapshot must not be opened")

    monkeypatch.setattr(Path, "open", forbidden_read)
    got = C.load_connections(tmp_path, NOW, text)
    for venue in ("kalshi", "polymarket_us"):
        assert got[venue]["status"] != "ok"
        assert got[venue]["events"] == [] and got[venue]["today_pacific"]["pnl_usd"] is None


@pytest.mark.parametrize("depth", [650, 1500])
def test_deeply_nested_corrupt_source_cannot_break_the_other_connection(tmp_path: Path, depth: int) -> None:
    persist(tmp_path, "speeddesk/kalshi_live/state.json", kalshi_state(partial_book()))
    path = tmp_path / "polydesk/state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = json.dumps(pm_state())[:-1]
    path.write_text(prefix + ', "unused_nested":' + '[' * depth + '0' + ']' * depth + '}')
    got = C.load_connections(tmp_path, NOW, text)
    assert got["kalshi"]["status"] == "ok"
    assert got["polymarket_us"]["status"] != "ok"
    assert got["polymarket_us"]["events"] == []


def test_displayed_market_and_event_text_use_the_supplied_sanitizer() -> None:
    marker = "redact-this-test-marker"

    def scrub(value: Any, limit: int = 300) -> str:
        return str(value).replace(marker, "[redacted]")[:limit]

    raw = pm_state([pm_row(marker, settled_at=NOW - 10, pnl_usd=.02)])
    raw["positions"] = {marker: pm_row(marker)}
    got = C.polymarket_connection(raw, NOW, scrub)
    encoded = json.dumps(got)
    assert marker not in encoded and "[redacted]" in encoded
