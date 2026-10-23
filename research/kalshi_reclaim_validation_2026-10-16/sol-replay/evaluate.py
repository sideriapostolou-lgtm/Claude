"""Frozen pooled research screen; never select the best secondary policy."""

from __future__ import annotations

from decimal import Decimal as D
from typing import Any

from run_partition import summarize


def screen(pooled: dict[str, Any], confirmation: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "pooled_known_net_positive": D(pooled["net_known_pnl"]) > 0,
        "confirmation_known_net_positive": D(confirmation["net_known_pnl"]) > 0,
        "at_least_30_known_fills": pooled["known_filled_windows"] >= 30,
        "at_least_7_traded_utc_days": len(pooled["distinct_filled_open_days"]) >= 7,
        "no_unresolved_entered_outcomes": pooled["unknown_entered_outcomes"] == 0,
        "unknown_entry_bound_positive_or_none": (
            pooled["unknown_attempted_entries"] == 0
            or (
                D(pooled["all_attempt_lower_pnl"]) > 0
                and D(confirmation["all_attempt_lower_pnl"]) > 0
            )
        ),
    }
    verdict = "POSITIVE_RESEARCH_SCREEN" if all(checks.values()) else "INSUFFICIENT"
    if (
        D(pooled["all_attempt_upper_pnl"]) < 0
        or D(confirmation["all_attempt_upper_pnl"]) < 0
    ):
        verdict = "NEGATIVE_TESTED_PROXY"
    return {
        "verdict": verdict,
        "checks": checks,
        "failed_checks": [k for k, v in checks.items() if not v],
        "scope": "Local historical sampled-taker proxy, not actual GTC execution or live-profitability proof.",
    }


def combine(
    val: list[dict[str, Any]], confirmation: list[dict[str, Any]]
) -> dict[str, Any]:
    for rows in (val, confirmation):
        if len({r["ticker"] for r in rows}) != len(rows) or len(
            {r["open_ms"] for r in rows}
        ) != len(rows):
            raise ValueError("Duplicate market/window within partition")
        if any(
            r.get("cell") != "1000ms_current_targets" or r.get("delay_ms") != 1000
            for r in rows
        ):
            raise ValueError("Only preregistered primary cell may be screened")
    if {r["ticker"] for r in val} & {r["ticker"] for r in confirmation}:
        raise ValueError("Partitions overlap")
    val_days = [f"2026-10-{day:02}" for day in range(4, 10)]
    conf_days = [f"2026-10-{day:02}" for day in range(10, 13)]
    if not {r["open_day_utc"] for r in val} <= set(val_days):
        raise ValueError("Validation calendar violation")
    if not {r["open_day_utc"] for r in confirmation} <= set(conf_days):
        raise ValueError("Confirmation calendar violation")
    pooled = summarize(val + confirmation, 864, val_days + conf_days)
    conf = summarize(confirmation, 288, conf_days)
    return {
        "pooled": pooled,
        "confirmation": conf,
        "research_screen": screen(pooled, conf),
    }
