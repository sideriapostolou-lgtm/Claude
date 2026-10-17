"""Pure window-cohort measurements; no trading, activation or account access.

Callers must isolate a venue and ledger scope. ``coverage=True`` certifies both
the full discovered-window observation interval and its complete local fill
history. Known stale/no-buy intervals are observed states, not missing history;
market availability is reported separately. A
separate day certificate covers discovery/recording gaps between windows; a
list of observed windows alone cannot prove a complete day.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any

SCOPES = {"real", "practice", "practice_twin"}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _bounds(day: str) -> tuple[float, float]:
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC)
    if start.strftime("%Y-%m-%d") != day:
        raise ValueError("Invalid UTC scorecard day")
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def window_scorecard(day: str, *, windows: Sequence[Mapping[str, Any]], fills: Sequence[Mapping[str, Any]],
                     settlements: Sequence[Mapping[str, Any]], coverage: Mapping[str, bool | None],
                     scope: str, as_of: float, day_coverage_complete: bool = False) -> dict[str, Any]:
    """Measure the UTC day containing each window's end, including quiet windows.

    Reported trading statistics use fully observed windows only. Unknown or
    partial windows remain counted separately. Settlement dates never move a
    window into another cohort; an unsettled traded window makes cohort P&L
    unknown while its known settled subtotal remains visible.
    """
    begin, end = _bounds(day)
    if scope not in SCOPES or _number(as_of) is None:
        raise ValueError("Invalid scorecard scope or observation clock")
    cohort: dict[str, Mapping[str, Any]] = {}
    conflicting_windows: set[str] = set()
    venues: set[str] = set()
    invalid_windows = 0
    for window in windows:
        slug, start, finish = window.get("slug"), _number(window.get("start")), _number(window.get("end"))
        if not isinstance(slug, str) or not slug or start is None or finish is None or start >= finish:
            invalid_windows += 1
            continue
        if not begin <= finish < end:
            continue
        venue = window.get("venue")
        if not isinstance(venue, str) or not venue:
            invalid_windows += 1
            continue
        venues.add(venue)
        if slug in cohort and dict(cohort[slug]) != dict(window):
            invalid_windows += 1
            conflicting_windows.add(slug)
        cohort[slug] = window
    if len(venues) > 1:
        raise ValueError("Scorecard venues must remain separate")

    by_window: dict[str, list[dict[str, Any]]] = {slug: [] for slug in cohort}
    bad_fills: set[str] = set()
    seen: dict[str, dict[str, Any]] = {}
    for raw in fills:
        slug = raw.get("window")
        if slug not in cohort:
            continue
        side, price, size, fee, at = (raw.get("side"), _number(raw.get("price")), _number(raw.get("size")),
                                     _number(raw.get("fee_usd")), _number(raw.get("at")))
        window = cohort[slug]
        if (side not in ("up", "down") or price is None or not 0 < price < 1
                or size is None or size <= 0 or fee is None or (fee < 0 and scope == "real") or at is None
                or not float(window["start"]) <= at <= float(window["end"]) or at > as_of
                or raw.get("action", "buy") != "buy"):
            bad_fills.add(slug)
            continue
        role = raw.get("is_taker")
        fill = {"window": slug, "side": side, "price": price, "size": size, "fee_usd": fee,
                "at": at, "is_taker": role if isinstance(role, bool) else None}
        identity = raw.get("fill_id")
        if isinstance(identity, str) and identity:
            previous = seen.get(identity)
            if previous is not None:
                economic = ("window", "side", "price", "size", "fee_usd", "at")
                if any(previous[key] != fill[key] for key in economic):
                    bad_fills.update((str(previous["window"]), slug))
                elif not previous.get("role_conflict"):
                    if previous["is_taker"] is None:
                        previous["is_taker"] = fill["is_taker"]
                    elif fill["is_taker"] is not None and previous["is_taker"] != fill["is_taker"]:
                        previous["is_taker"], previous["role_conflict"] = None, True
                continue
            seen[identity] = fill
        by_window[slug].append(fill)

    settled: dict[str, dict[str, float]] = {}
    bad_settlements: set[str] = set()
    for raw in settlements:
        slug = raw.get("window")
        if slug not in cohort:
            continue
        at = _number(raw.get("at"))
        locked, direction, pnl = (_number(raw.get("locked_usd")),
                                  _number(raw.get("direction_usd", raw.get("directional_usd"))),
                                  _number(raw.get("pnl_usd")))
        if (at is None or not float(cohort[slug]["end"]) <= at <= as_of
                or locked is None or direction is None or pnl is None
                or not math.isclose(locked + direction, pnl, abs_tol=1e-7)):
            bad_settlements.add(slug)
            continue
        value = {"locked_usd": locked, "directional_usd": direction, "pnl_usd": pnl}
        if slug in settled and settled[slug] != value:
            bad_settlements.add(slug)
        settled[slug] = value

    for slug, result in settled.items():
        if not by_window[slug] and any(abs(value) > 1e-7 for value in result.values()):
            # Nonzero money cannot coexist with certified empty fill history.
            bad_fills.add(slug)

    complete = [slug for slug, window in cohort.items()
                if coverage.get(slug) is True and float(window["end"]) <= as_of
                and slug not in bad_fills and slug not in conflicting_windows]
    traded = [slug for slug in complete if by_window[slug]]
    rows = [fill for slug in complete for fill in by_window[slug]]
    both = 0
    imbalances: list[float] = []
    pairs = pair_cost = pair_fees = total_fees = 0.0
    for slug in complete:
        quantity = {side: sum(row["size"] for row in by_window[slug] if row["side"] == side)
                    for side in ("up", "down")}
        cost = {side: sum(row["size"] * row["price"] + row["fee_usd"]
                          for row in by_window[slug] if row["side"] == side) for side in quantity}
        fees = {side: sum(row["fee_usd"] for row in by_window[slug] if row["side"] == side) for side in quantity}
        total_fees += sum(fees.values())
        total = sum(quantity.values())
        if total:
            imbalances.append(abs(quantity["up"] - quantity["down"]) / total)
        matched = min(quantity.values())
        if matched:
            both += 1
            pairs += matched
            pair_cost += matched * sum(cost[side] / quantity[side] for side in quantity)
            pair_fees += matched * sum(fees[side] / quantity[side] for side in quantity)
    known_roles = [row for row in rows if row["is_taker"] is not None]
    takers = sum(row["is_taker"] is True for row in known_roles)
    missing_settlements = [slug for slug in traded if slug not in settled or slug in bad_settlements]
    known_results = [settled[slug] for slug in traded if slug in settled and slug not in bad_settlements]
    # A certified window with no buys has no exposure and a genuinely zero result.
    invalid_results = bool(bad_settlements.intersection(complete))
    pnl_known = bool(complete) and not missing_settlements and not invalid_results
    totals = {key: sum(item[key] for item in known_results)
              for key in ("locked_usd", "directional_usd", "pnl_usd")}
    fully_observed = bool(cohort) and len(complete) == len(cohort) and not invalid_windows
    day_complete = (day_coverage_complete is True and as_of >= end and fully_observed and pnl_known)
    reasons = []
    if as_of < end:
        reasons.append("UTC day is still open")
    if day_coverage_complete is not True:
        reasons.append("Full-day discovery and recording coverage is not certified")
    if not fully_observed:
        reasons.append("Some window coverage or fill history is missing or invalid")
    if missing_settlements:
        reasons.append("Traded windows are awaiting verified settlement")
    if invalid_results:
        reasons.append("Settlement evidence is invalid or contradictory")
    if not cohort:
        reasons.append("No eligible windows are known")
    worst = min((item["pnl_usd"] for item in known_results), default=None)
    unmatched_fees = total_fees - pair_fees
    return {"version": 1, "scope": scope, "venue": next(iter(venues), None), "day": day,
            "cohort": "window end UTC day", "population": "fully observed windows with complete fill history",
            "coverage_basis": "complete window discovery and recorded ledger history; market availability reported separately",
            "status": "complete" if day_complete else "partial", "day_complete": day_complete,
            "utc_day_ended": as_of >= end,
            "reasons": reasons, "eligible_windows": len(cohort), "complete_windows": len(complete),
            "unknown_coverage_windows": sum(coverage.get(slug) is None for slug in cohort),
            "gap_windows": sum(coverage.get(slug) is False for slug in cohort),
            "invalid_windows": invalid_windows, "invalid_fill_windows": len(bad_fills),
            "invalid_settlement_windows": len(bad_settlements), "traded_windows": len(traded),
            "zero_fill_windows": len(complete) - len(traded), "fills": len(rows),
            "fills_per_window": len(rows) / len(complete) if complete else None,
            "fills_per_traded_window": len(rows) / len(traded) if traded else None,
            "both_sides_windows": both, "both_sides_share": both / len(complete) if complete else None,
            "both_sides_traded_share": both / len(traded) if traded else None,
            "median_imbalance": statistics.median(imbalances) if imbalances else None,
            "imbalance_basis": "final quantity imbalance in traded fully observed windows",
            "taker_fill_share": takers / len(rows) if rows and len(known_roles) == len(rows) else None,
            "known_role_taker_share": takers / len(known_roles) if known_roles else None,
            "role_coverage": len(known_roles) / len(rows) if rows else None,
            "unknown_role_fills": len(rows) - len(known_roles), "matched_pairs": pairs,
            "matched_pair_cost_usd": pair_cost / pairs if pairs else None,
            "matched_pair_fees_usd": pair_fees if complete else None,
            "unmatched_fees_usd": (0.0 if abs(unmatched_fees) < 1e-12 else unmatched_fees) if complete else None,
            "fees_usd": total_fees if complete else None,
            "settled_traded_windows": len(known_results), "unsettled_traded_windows": len(missing_settlements),
            "settled_pnl_usd": totals["pnl_usd"] if known_results else None,
            **{key: value if pnl_known else None for key, value in totals.items()},
            "pnl_per_window_usd": totals["pnl_usd"] / len(complete) if pnl_known else None,
            "worst_window_usd": worst, "worst_window_basis": "settled traded fully observed windows",
            "full_cohort_worst_usd": worst if pnl_known else None,
            "cap_change_allowed": False, "automatic_promotion": False}


def cap_review_eligibility(cards: Sequence[Mapping[str, Any]], *, match: Mapping[str, Any]) -> dict[str, Any]:
    """Informational review criterion only; this function cannot authorize money.

    Match coverage must be validated for an untouched held-out evaluation with
    one-to-one anti-spam matching. Missing validation cannot qualify, even if a
    displayed recall is high. Three latest consecutive complete UTC days must
    each be positive after actual fees, within one real-money venue/scope.
    """
    ordered = sorted((row for row in cards if row.get("utc_day_ended") is True),
                     key=lambda row: str(row.get("day", "")))
    recent = ordered[-3:]
    reasons = []
    if len(recent) < 3:
        reasons.append("Three complete consecutive UTC days are required")
    elif (len({row.get("day") for row in recent}) != 3
          or len({(row.get("venue"), row.get("scope")) for row in recent}) != 1
          or any(row.get("scope") != "real" or row.get("venue") != "kalshi" or row.get("day_complete") is not True
                 or (_number(row.get("pnl_usd")) or 0) <= 0 for row in recent)):
        reasons.append("Three Kalshi real-money days must each be complete and positive after fees")
    else:
        try:
            dates = [_bounds(str(row["day"]))[0] for row in recent]
            if any(later - earlier != 86400 for earlier, later in pairwise(dates)):
                reasons.append("Positive complete days must be consecutive")
        except ValueError:
            reasons.append("Invalid UTC day history")
    recall = _number(match.get("recall_lower_bound"))
    precision = _number(match.get("precision_lower_bound"))
    false_positives = _number(match.get("false_positives"))
    predicates = ("held_out", "timing_validated", "identity_validated", "coverage_validated", "one_to_one",
                  "anti_spam_passed", "baseline_passed", "causal_before_event", "all_source_fills_denominator",
                  "strict_gate_passed")
    verified = (all(match.get(key) is True for key in predicates)
                and match.get("protocol") == "skipwatch-execution-v3"
                and _number(match.get("time_tolerance_s")) == 5
                and _number(match.get("price_tolerance_usd")) == .02
                and recall is not None and .70 <= recall <= 1
                and precision is not None and 0 <= precision <= 1
                and false_positives is not None and false_positives >= 0
                and false_positives.is_integer())
    if not verified:
        reasons.append("The validated execution protocol must pass held-out recall/precision, timing, identity and anti-spam checks")
    return {"eligible_for_owner_review": not reasons, "reasons": reasons,
            "days_considered": [row.get("day") for row in recent],
            "informational_only": True, "cap_change_allowed": False, "automatic_promotion": False}
