"""Read-only Pacific-day view of the Polymarket desk's recorded bot results.

The retained closed rows include cash-outs and later corrections, attributed to their
original ``settled_at``. They are usable only when their count AND P&L reconcile to
every UTC day book touched by the current Pacific day. This proves coverage of the
recorded book, not of all venue activity. It never changes the UTC risk books.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from nightcrawler.recap import day_window

PACIFIC_TZ = "America/Los_Angeles"


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def pacific_booked_day(state: Any, now: float) -> dict[str, Any]:
    """The current Pacific calendar day's recorded real bot P&L, or an honest unknown.

    ``start``/``end`` bound the full local day, including 23/25-hour DST days;
    ``as_of`` is the desk's last completed poll. ``status`` is ``ok``, ``incomplete``
    or ``unavailable``. A same-day old snapshot can remain ``ok``: callers must show
    its age separately. An absent or prior-day snapshot never establishes today's
    zero. ``settled`` counts booked results, including cash-outs, not unique markets.

    The input must be the loaded persisted desk state, with owner migration already
    applied. The function performs no I/O and does not mutate that state.
    """
    out: dict[str, Any] = {"date": None, "tz": PACIFIC_TZ, "start": None, "end": None,
                           "as_of": None, "status": "unavailable", "pnl_usd": None,
                           "settled": None, "reason": "missing_snapshot", "reconciliation": []}
    current = _number(now)
    if current is None or current <= 0:
        out["reason"] = "invalid_now"
        return out
    try:
        date, start, end, zone = day_window(current, PACIFIC_TZ, days_back=0)
    except (OSError, OverflowError, ValueError):
        out["reason"] = "invalid_window"
        return out
    if zone != PACIFIC_TZ:
        # day_window's UTC fallback is useful elsewhere, never a Pacific total.
        out["reason"] = "timezone_unavailable"
        return out
    out.update(date=date, start=start, end=end)
    if not isinstance(state, Mapping):
        return out
    as_of = _number(state.get("last_ok"))
    if as_of is None or as_of <= 0 or as_of > current:
        return out
    out["as_of"] = as_of
    if as_of < start:
        out["reason"] = "snapshot_before_day"
        return out

    out["status"] = "incomplete"
    if state.get("last_poll") is not None:
        last_poll = _number(state["last_poll"])
        if last_poll is None or last_poll <= 0 or last_poll != as_of:
            # Failed polls can save partially changed rows/day books, including a
            # correction whose original settled_at still predates last_ok.
            out["reason"] = "unfinished_poll"
            return out
    closed, days = state.get("closed"), state.get("live_days")
    if not isinstance(closed, list) or not isinstance(days, Mapping):
        out["reason"] = "missing_book"
        return out

    first = datetime.fromtimestamp(start, UTC).date()
    last = datetime.fromtimestamp(current, UTC).date()
    dates = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
    amounts: dict[str, list[float]] = {day: [] for day in dates}
    selected: list[float] = []
    for row in closed:
        out["reason"] = "invalid_result"
        if not isinstance(row, Mapping):
            return out
        if row.get("live") is False or row.get("owner") is True or row.get("rule") == "owner":
            continue
        if row.get("live") is not True:
            return out
        if any(key in row and not isinstance(row[key], bool) for key in ("owner", "unresolved")):
            return out
        if row.get("unresolved") is True:
            continue
        at = _number(row.get("settled_at"))
        if at is None or at <= 0 or at > as_of:
            return out
        day = datetime.fromtimestamp(at, UTC).date().isoformat()
        if day not in amounts:
            continue
        pnl = _number(row.get("pnl_usd"))
        if pnl is None:
            return out
        amounts[day].append(pnl)
        if start <= at < end:
            selected.append(pnl)

    mismatch = False
    for day in dates:
        out["reason"] = "invalid_day_book"
        rec = days.get(day, {"settled": 0, "pnl_usd": 0.0})
        if not isinstance(rec, Mapping):
            return out
        count, pnl = _number(rec.get("settled")), _number(rec.get("pnl_usd"))
        if count is None or count < 0 or not count.is_integer() or pnl is None:
            return out
        try:
            total = math.fsum(amounts[day])
        except (OverflowError, ValueError):
            return out
        matches = count == len(amounts[day]) and math.isclose(total, pnl, rel_tol=0.0, abs_tol=1e-8)
        # Bounded aggregate diagnostics explain an unavailable figure without
        # publishing private order identifiers or passing off a partial sum as profit.
        out["reconciliation"].append({"day_utc": day, "book_results": int(count),
                                      "retained_results": len(amounts[day]), "book_pnl_usd": pnl,
                                      "retained_pnl_usd": total, "matches": matches})
        mismatch = mismatch or not matches
    if mismatch:
        out["reason"] = "day_book_mismatch"
        return out
    try:
        total = math.fsum(selected)
    except (OverflowError, ValueError):
        out["reason"] = "invalid_result"
        return out
    out.update(status="ok", pnl_usd=total, settled=len(selected), reason=None)
    return out
