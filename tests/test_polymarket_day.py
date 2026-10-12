"""Pacific booked P&L is available only with complete retained-day evidence."""

from __future__ import annotations

import copy
import math
from datetime import UTC, datetime
from typing import Any

import pytest

from nightcrawler import polymarket_day as D


def ts(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


NOW = ts("2026-10-13T03:00:00Z")  # October 12, 8 p.m. Pacific; two UTC books are needed.
START = ts("2026-10-12T07:00:00Z")


def result(at: float, pnl: float, **extra: Any) -> dict[str, Any]:
    return {"slug": "bitcoin", "live": True, "settled_at": at, "pnl_usd": pnl, **extra}


def book(rows: list[dict[str, Any]], now: float = NOW) -> dict[str, Any]:
    days: dict[str, Any] = {}
    for row in rows:
        if not row.get("live") or row.get("owner") or row.get("rule") == "owner" or row.get("unresolved"):
            continue
        day = datetime.fromtimestamp(row["settled_at"], UTC).date().isoformat()
        rec = days.setdefault(day, {"settled": 0, "pnl_usd": 0.0})
        rec["settled"] += 1
        rec["pnl_usd"] += row["pnl_usd"]
    return {"last_ok": now, "last_poll": now, "closed": rows, "live_days": days}


def test_reconciles_both_full_utc_days_then_selects_since_pacific_midnight_without_mutation() -> None:
    rows = [result(START - 1, 12), result(START, 0.19), result(START + 3600, -0.04, sold_in_app=True),
            result(ts("2026-10-13T01:00:00Z"), 0.13), result(NOW, 0.0)]
    st = book(rows)
    original = copy.deepcopy(st)
    got = D.pacific_booked_day(st, NOW)
    assert got == {"date": "2026-10-12", "tz": D.PACIFIC_TZ, "start": START,
                   "end": ts("2026-10-13T07:00:00Z"), "as_of": NOW, "status": "ok",
                   "pnl_usd": pytest.approx(0.28), "settled": 4, "reason": None}
    assert st == original


def test_cashout_corrections_keep_the_original_booking_date_not_correction_receipt_date() -> None:
    old = result(START - 1, -3.84, sold_in_app=True, sale_id="old-sale")
    current = result(START + 1, -5.54, sold_in_app=True, sale_id="current-sale")
    # Both are already corrected, as persisted by _correct_booking; no receipt-time reassignment.
    got = D.pacific_booked_day(book([old, current]), NOW)
    assert got["status"] == "ok" and got["settled"] == 1 and got["pnl_usd"] == -5.54


def test_owner_paper_and_unresolved_do_not_enter_the_bot_result() -> None:
    rows = [result(START + 1, 0.19), result(START + 2, 999, owner=True),
            result(START + 3, -999, rule="owner"), result(START + 4, 888, live=False),
            {"live": True, "unresolved": True, "pnl_usd": None, "settled_at": START + 5}]
    got = D.pacific_booked_day(book(rows), NOW)
    assert got["status"] == "ok" and got["settled"] == 1 and got["pnl_usd"] == 0.19


def test_missing_daily_keys_are_known_zero_only_in_a_current_valid_book() -> None:
    got = D.pacific_booked_day(book([]), NOW)
    assert got["status"] == "ok" and got["pnl_usd"] == 0.0 and got["settled"] == 0
    st = book([result(START, 0.0)])
    st["live_days"] = {}
    assert D.pacific_booked_day(st, NOW)["status"] == "incomplete"


@pytest.mark.parametrize("removed", [[0.0], [0.2, -0.2], [0.3]])
def test_missing_rows_never_become_a_partial_total_even_if_their_net_is_zero(removed: list[float]) -> None:
    st = book([result(START + 1, pnl) for pnl in [0.1, *removed]])
    st["closed"] = st["closed"][:1]
    got = D.pacific_booked_day(st, NOW)
    assert got["status"] == "incomplete" and got["reason"] == "day_book_mismatch"
    assert got["pnl_usd"] is None and got["settled"] is None


def test_missing_pre_midnight_row_also_invalidates_partial_utc_day_coverage() -> None:
    st = book([result(START - 1, 0.1), result(START + 1, 0.2)])
    st["closed"].pop(0)
    assert D.pacific_booked_day(st, NOW)["status"] == "incomplete"


def test_retention_limit_itself_is_not_incompleteness_if_all_touched_books_match() -> None:
    st = book([result(START + i, 0.01) for i in range(200)])
    got = D.pacific_booked_day(st, NOW)
    assert got["status"] == "ok" and got["settled"] == 200 and got["pnl_usd"] == 2.0


@pytest.mark.parametrize("key,value", [("pnl_usd", None), ("pnl_usd", "0.1"), ("pnl_usd", True),
                                     ("pnl_usd", math.nan), ("pnl_usd", math.inf), ("settled_at", None),
                                     ("settled_at", False), ("settled_at", -1), ("settled_at", NOW + 1),
                                     ("settled_at", math.inf), ("live", "true"), ("owner", "false")])
def test_malformed_potential_bot_rows_fail_closed(key: str, value: Any) -> None:
    st = book([result(START + 1, 0.1)])
    st["closed"][0][key] = value
    got = D.pacific_booked_day(st, NOW)
    assert got["status"] == "incomplete" and got["pnl_usd"] is None


@pytest.mark.parametrize("key,value", [("pnl_usd", None), ("pnl_usd", math.inf), ("pnl_usd", True),
                                     ("pnl_usd", "0.1"), ("pnl_usd", 0.101), ("settled", 1.5),
                                     ("settled", -1), ("settled", True), ("settled", None)])
def test_malformed_or_mismatched_daily_books_fail_closed(key: str, value: Any) -> None:
    st = book([result(START, 0.1)])
    st["live_days"]["2026-10-12"][key] = value
    got = D.pacific_booked_day(st, NOW)
    assert got["status"] == "incomplete" and got["pnl_usd"] is None


@pytest.mark.parametrize("value", [None, False, 0, "1", math.nan, math.inf, NOW + 1, START - 1])
def test_missing_invalid_or_prior_pacific_day_snapshot_never_establishes_today_zero(value: Any) -> None:
    st = book([])
    st["last_ok"] = value
    got = D.pacific_booked_day(st, NOW)
    assert got["status"] == "unavailable" and got["pnl_usd"] is None and got["settled"] is None


def test_stale_same_day_snapshot_keeps_its_original_age_for_the_callers_stale_label() -> None:
    st = book([result(START + 1, 0.2)], now=START + 3600)
    got = D.pacific_booked_day(st, NOW)
    assert got["status"] == "ok" and got["pnl_usd"] == 0.2 and got["as_of"] == START + 3600


def test_failed_later_poll_can_change_old_corrections_so_is_not_a_completed_snapshot() -> None:
    st = book([result(START + 1, -1.0, sold_in_app=True)], now=NOW - 60)
    st["last_poll"] = NOW
    got = D.pacific_booked_day(st, NOW)
    assert got["status"] == "incomplete" and got["reason"] == "unfinished_poll" and got["pnl_usd"] is None


def test_result_newer_than_completed_snapshot_is_not_silently_included() -> None:
    st = book([result(NOW, 0.1)], now=NOW - 1)
    got = D.pacific_booked_day(st, NOW)
    assert got["status"] == "incomplete" and got["pnl_usd"] is None


@pytest.mark.parametrize("state", [None, [], {}, {"last_ok": NOW},
                                  {"last_ok": NOW, "closed": [], "live_days": None},
                                  {"last_ok": NOW, "closed": [None], "live_days": {}},
                                  {"last_ok": NOW, "closed": [], "live_days": {"2026-10-12": None}}])
def test_missing_or_malformed_state_is_unknown(state: Any) -> None:
    got = D.pacific_booked_day(state, NOW)
    assert got["status"] != "ok" and got["pnl_usd"] is None and got["settled"] is None


@pytest.mark.parametrize("iso,hours,start_iso,end_iso", [
    ("2026-03-08T20:00:00Z", 23, "2026-03-08T08:00:00Z", "2026-03-09T07:00:00Z"),
    ("2026-11-01T20:00:00Z", 25, "2026-11-01T07:00:00Z", "2026-11-02T08:00:00Z"),
])
def test_pacific_calendar_days_follow_dst(iso: str, hours: int, start_iso: str, end_iso: str) -> None:
    now = ts(iso)
    got = D.pacific_booked_day(book([], now=now), now)
    assert got["status"] == "ok" and got["start"] == ts(start_iso) and got["end"] == ts(end_iso)
    assert got["end"] - got["start"] == hours * 3600


def test_next_pacific_midnight_requires_a_new_current_day_snapshot() -> None:
    next_day = ts("2026-10-13T07:00:00Z")
    st = book([result(next_day - 1, 0.1)], now=next_day - 1)
    assert D.pacific_booked_day(st, next_day)["status"] == "unavailable"
    st["last_ok"] = st["last_poll"] = next_day
    got = D.pacific_booked_day(st, next_day)
    assert got["status"] == "ok" and got["pnl_usd"] == 0 and got["settled"] == 0


def test_timezone_failure_is_not_silently_a_utc_total(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(D, "day_window", lambda *args, **kw: ("2026-10-13", NOW - 1, NOW + 1, "UTC"))
    got = D.pacific_booked_day(book([]), NOW)
    assert got["status"] == "unavailable" and got["reason"] == "timezone_unavailable"
    assert got["pnl_usd"] is None and got["start"] is None and got["date"] is None
