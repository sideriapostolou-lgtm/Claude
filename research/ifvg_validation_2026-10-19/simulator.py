"""Offline OWNER_SWEEP_IFVG_MNQ_v1 OHLC simulation, never an execution adapter.

Only finalized, *start stamped*, UTC one-minute bars are accepted. Prices are
integer quarter-point ticks. An integer timestamp means minutes since Unix
epoch, not seconds. Integer fees mean cents; Decimal fees mean USD per side.
Calendar REGULAR is a caller attestation, not an exchange-calendar lookup.
Actual-contract identity, licensing and dataset/split qualification belong to
the caller; this module never labels supplied bars verified market data.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import TypedDict
from zoneinfo import ZoneInfo

VERSION = "OWNER_SWEEP_IFVG_MNQ_v1"
NY = ZoneInfo("America/New_York")
MINUTE = timedelta(minutes=1)
TICK_USD = Decimal("0.50")
# Preserve every predeclared sensitivity case; these are hypothetical costs.
COST_SCENARIOS = tuple(
    {"fee_per_side_cents": fee, "friction_ticks": friction}
    for fee in (50, 100, 150)
    for friction in (1, 2, 4)
)


class GapRecord(TypedDict):
    a_timestamp: str
    b_timestamp: str
    c_timestamp: str
    kind: str
    lower_ticks: int
    upper_ticks: int


class AttemptRecord(TypedDict):
    sweep_timestamp: str
    direction: str
    swept_levels: list[str]
    gap: GapRecord | None
    confirmation_timestamp: str | None


@dataclass(frozen=True)
class Bar:
    timestamp: datetime | int
    open: int
    high: int
    low: int
    close: int


def _timestamp(value: datetime | int) -> datetime:
    if type(value) is int:
        try:
            return datetime(1970, 1, 1, tzinfo=UTC) + value * MINUTE
        except (OverflowError, ValueError) as exc:
            raise ValueError("epoch-minute timestamp outside datetime range") from exc
    if not isinstance(value, datetime):
        raise TypeError("timestamp must be an aware UTC datetime or integer epoch-minute")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("datetime timestamp must be aware UTC")
    if value.second or value.microsecond:
        raise ValueError("bar timestamp must be aligned to a minute start")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _money(value: Decimal) -> str:
    return format(value, ".2f")


def _slots(start: datetime, end: datetime) -> list[datetime]:
    """Elapsed UTC minutes between NY boundaries, including historical DST."""
    result = []
    current = start.astimezone(UTC)
    while current < end.astimezone(UTC):
        result.append(current)
        current += MINUTE
    return result


def simulate_day(
    bars: Iterable[Bar],
    session_date: date | str,
    fee_per_side: Decimal | int = 100,
    friction_ticks: int = 2,
    calendar_status: str = "REGULAR",
) -> dict:
    """Return one JSON-serializable simulation decision, with exact USD strings.

    Missing required slots stop inference at the first incomplete phase. Known
    terminal decisions require no later bars. Malformed input raises ValueError/TypeError
    rather than being silently coerced into a no-trade or research result.
    """
    if isinstance(session_date, str):
        session_date = date.fromisoformat(session_date)
    if type(session_date) is not date:
        raise ValueError("session_date must be a date or ISO date, not datetime")
    if type(friction_ticks) is not int or friction_ticks not in (1, 2, 4):
        raise ValueError("friction_ticks must be one of the frozen cases 1, 2, 4")
    if type(fee_per_side) is int:
        fee = Decimal(fee_per_side) / 100
    elif isinstance(fee_per_side, Decimal):
        fee = fee_per_side
    else:
        raise ValueError("fee_per_side must be Decimal USD or integer cents")
    if not fee.is_finite() or fee not in (Decimal("0.50"), Decimal(1), Decimal("1.50")):
        raise ValueError("fee must be a frozen per-side case: $0.50, $1.00, $1.50")
    if calendar_status not in ("REGULAR", "SHORTENED", "CLOSED", "UNKNOWN", "INCOMPLETE"):
        raise ValueError("unrecognized independently supplied calendar status")

    indexed: dict[datetime, Bar] = {}
    for bar in bars:
        if not isinstance(bar, Bar):
            raise TypeError("every input row must be a Bar")
        stamp = _timestamp(bar.timestamp)
        if any(type(value) is not int for value in (bar.open, bar.high, bar.low, bar.close)):
            raise ValueError("OHLC must contain integer ticks, without floats or bools")
        if not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high:
            raise ValueError("OHLC extrema do not contain open/close")
        if stamp in indexed:
            raise ValueError(f"duplicate minute timestamp: {_iso(stamp)}")
        indexed[stamp] = bar

    result: dict[str, object] = {
        "schema_version": 1,
        "strategy_version": VERSION,
        "mode": "SIMULATION_ONLY",
        "session_date": session_date.isoformat(),
        "calendar_status": calendar_status,
        "cost_scenario": {
            "fee_per_side_usd": _money(fee),
            "friction_ticks": friction_ticks,
            "spread_included_in_friction": True,
            "hypothetical": True,
        },
        "decision": None,
        "reason": None,
        "reference_levels": None,
        "attempt": None,
        "trade": None,
        "gross_usd": None,
        "fees_usd": None,
        "net_usd": None,
        "ambiguous": False,
        "required_missing": [],
        "coverage": {},
    }
    required: set[datetime] = set()
    phases: dict[str, set[datetime]] = {}

    def need(stamps: Iterable[datetime], phase: str) -> bool:
        stamps = set(stamps)
        required.update(stamps)
        phases.setdefault(phase, set()).update(stamps)
        return all(stamp in indexed for stamp in stamps)

    def finish(decision: str, reason: str) -> dict:
        missing = sorted(required - indexed.keys())
        result["decision"] = decision
        result["reason"] = reason
        result["required_missing"] = [_iso(stamp) for stamp in missing]
        result["coverage"] = {
            "complete": not missing and decision != "UNRESOLVED",
            "required_count": len(required),
            "present_count": len(required & indexed.keys()),
            "required_missing": result["required_missing"],
            "phases": {
                name: {
                    "required_count": len(stamps),
                    "present_count": len(stamps & indexed.keys()),
                    "required_missing": [_iso(stamp) for stamp in sorted(stamps - indexed.keys())],
                }
                for name, stamps in phases.items()
            },
        }
        if decision in ("REJECTED", "NO_TRADE", "EXCLUDED"):
            result.update(gross_usd="0.00", fees_usd="0.00", net_usd="0.00")
        return result

    if calendar_status in ("SHORTENED", "CLOSED"):
        return finish("EXCLUDED", f"CALENDAR_{calendar_status}")
    if calendar_status != "REGULAR":
        return finish("UNRESOLVED", f"CALENDAR_{calendar_status}")

    def local(hour: int, minute: int = 0, day: date = session_date) -> datetime:
        return datetime.combine(day, time(hour, minute), NY).astimezone(UTC)

    asian = _slots(local(20, day=session_date - timedelta(days=1)), local(0))
    london = _slots(local(2), local(5))
    asia_ok = need(asian, "asian_reference")
    london_ok = need(london, "london_reference")
    if not (asia_ok and london_ok):
        return finish("UNRESOLVED", "MISSING_REFERENCE")
    levels = {
        "ASIAN_HIGH": max(indexed[stamp].high for stamp in asian),
        "ASIAN_LOW": min(indexed[stamp].low for stamp in asian),
        "LONDON_HIGH": max(indexed[stamp].high for stamp in london),
        "LONDON_LOW": min(indexed[stamp].low for stamp in london),
    }
    result["reference_levels"] = levels

    def sweeps(bar: Bar) -> tuple[list[str], list[str]]:
        highs = [name for name, level in levels.items()
                 if name.endswith("HIGH") and bar.high >= level + 1 and bar.close <= level]
        lows = [name for name, level in levels.items()
                if name.endswith("LOW") and bar.low <= level - 1 and bar.close >= level]
        return highs, lows

    sweep = None
    attempt: AttemptRecord | None = None
    direction = 0
    for stamp in _slots(local(9, 30), local(11)):
        if not need([stamp], "observation"):
            return finish("UNRESOLVED", "MISSING_OBSERVATION")
        highs, lows = sweeps(indexed[stamp])
        if highs or lows:
            sweep = stamp
            direction = -1 if highs else 1
            attempt = {
                "sweep_timestamp": _iso(stamp),
                "direction": "SHORT" if direction == -1 else "LONG",
                "swept_levels": highs + lows,
                "gap": None,
                "confirmation_timestamp": None,
            }
            result["attempt"] = attempt
            # Coverage is required even for an ambiguous or later-rejected sweep.
            if not need(_slots(stamp - 12 * MINUTE, stamp), "pre_gap"):
                return finish("UNRESOLVED", "MISSING_PRE_GAP")
            if highs and lows:
                result["ambiguous"] = True
                return finish("REJECTED", "BOTH_DIRECTION_SWEEP")
            break
    if sweep is None:
        return finish("NO_TRADE", "NO_SWEEP")
    assert attempt is not None

    chosen: GapRecord | None = None
    for age in range(1, 11):
        c_stamp = sweep - age * MINUTE
        a = indexed[c_stamp - 2 * MINUTE]
        c = indexed[c_stamp]
        lower, upper = (a.high, c.low) if direction == -1 else (c.high, a.low)
        if upper - lower < 1:
            continue
        inverted = any(
            indexed[stamp].close < lower if direction == -1 else indexed[stamp].close > upper
            for stamp in _slots(c_stamp + MINUTE, sweep)
        )
        if not inverted:
            chosen = {
                "a_timestamp": _iso(c_stamp - 2 * MINUTE),
                "b_timestamp": _iso(c_stamp - MINUTE),
                "c_timestamp": _iso(c_stamp),
                "kind": "BULLISH" if direction == -1 else "BEARISH",
                "lower_ticks": lower,
                "upper_ticks": upper,
            }
            break
    if chosen is None:
        return finish("REJECTED", "NO_ELIGIBLE_GAP")
    attempt["gap"] = chosen

    confirmation = None
    adverse = indexed[sweep].high if direction == -1 else indexed[sweep].low
    for offset in range(11):
        stamp = sweep + offset * MINUTE
        if stamp + MINUTE >= local(11):
            return finish("REJECTED", "ENTRY_CUTOFF")
        if not need([stamp], "confirmation"):
            return finish("UNRESOLVED", "MISSING_CONFIRMATION")
        bar = indexed[stamp]
        adverse = max(adverse, bar.high) if direction == -1 else min(adverse, bar.low)
        highs, lows = sweeps(bar)
        if (direction == -1 and lows) or (direction == 1 and highs):
            return finish("REJECTED", "OPPOSITE_SWEEP")
        if (bar.close < chosen["lower_ticks"] if direction == -1
                else bar.close > chosen["upper_ticks"]):
            confirmation = stamp
            attempt["confirmation_timestamp"] = _iso(stamp)
            break
    if confirmation is None:
        return finish("REJECTED", "NO_INVERSION")

    entry_stamp = confirmation + MINUTE
    if not need([entry_stamp], "entry"):
        return finish("UNRESOLVED", "MISSING_ENTRY")
    stop = adverse - direction
    raw_entry = indexed[entry_stamp].open
    entry = raw_entry + direction * friction_ticks
    risk = direction * (entry - stop)
    if direction * (raw_entry - stop) <= 0 or risk <= 0:
        return finish("REJECTED", "ENTRY_AT_OR_BEYOND_STOP")
    target = entry + direction * 2 * risk
    trade = {
        "direction": "SHORT" if direction == -1 else "LONG",
        "contracts": 1,
        "entry_timestamp": _iso(entry_stamp),
        "entry_open_ticks": raw_entry,
        "entry_ticks": entry,
        "stop_ticks": stop,
        "risk_ticks": risk,
        "target_ticks": target,
        "entry_fee_usd": _money(fee),
        "exit_timestamp": None,
        "exit_time_basis": None,
        "exit_interval_end": None,
        "exit_ticks": None,
        "exit_reason": None,
        "ambiguous": False,
        "gross_ticks": None,
        "gross_usd": None,
        "fees_usd": None,
        "net_usd": None,
    }
    result["trade"] = trade

    def close(stamp: datetime, price: int, reason: str, ambiguous: bool = False,
              time_basis: str = "OPEN") -> dict:
        gross_ticks = direction * (price - entry)
        gross = gross_ticks * TICK_USD
        fees = 2 * fee
        trade.update(
            exit_timestamp=_iso(stamp), exit_ticks=price, exit_reason=reason,
            exit_time_basis=time_basis,
            exit_interval_end=_iso(stamp + MINUTE) if time_basis == "INTRABAR_INTERVAL" else None,
            ambiguous=ambiguous, gross_ticks=gross_ticks,
            gross_usd=_money(gross), fees_usd=_money(fees), net_usd=_money(gross - fees),
        )
        result.update(
            ambiguous=ambiguous, gross_usd=_money(gross),
            fees_usd=_money(fees), net_usd=_money(gross - fees),
        )
        return finish("TRADE", f"CLOSED_{reason}")

    for stamp in _slots(entry_stamp, local(11, 30) + MINUTE):
        if not need([stamp], "outcome"):
            return finish("UNRESOLVED", "MISSING_OUTCOME")
        bar = indexed[stamp]
        if direction * (bar.open - stop) <= 0:
            # Opening price already beyond stop is more adverse than the stop.
            return close(stamp, bar.open - direction * friction_ticks, "STOP")
        if direction * (bar.open - target) >= 1:
            return close(stamp, target, "TARGET")
        if stamp == local(11, 30):
            return close(stamp, bar.open - direction * friction_ticks, "TIME")
        stop_hit = bar.high >= stop if direction == -1 else bar.low <= stop
        target_hit = bar.low <= target - 1 if direction == -1 else bar.high >= target + 1
        if stop_hit:
            return close(stamp, stop - direction * friction_ticks, "STOP", target_hit,
                         "INTRABAR_INTERVAL")
        if target_hit:
            return close(stamp, target, "TARGET", time_basis="INTRABAR_INTERVAL")
    raise AssertionError("11:30 outcome must terminate simulation")
