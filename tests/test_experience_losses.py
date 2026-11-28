"""Loss types (docs/EXPERIENCE.md §6.3, §6.4, §11 ``test_losses``): descriptive only, never evidence of a mistake.

Each type fires on its constructed case and ``variance`` otherwise; ``pipeline_fault`` is always primary; otherwise
the most negative magnitude wins, ties in table order; every flag is kept; the taxonomy hash is pinned; the luck base
rates come from R-host rows only; the weekly line puts each count next to its expected count.
"""

from __future__ import annotations

from typing import Any

import pytest

from nightcrawler.experience import losses
from nightcrawler.experience.constants import LOSS_TYPES, TAXONOMY_VERSION
from nightcrawler.models import Candle

#: Pinned: changing a loss type, a threshold, a nomination or the feature catalogue changes it (and re-opens lesson
#: groups), which must be a deliberate, reviewed change.
PINNED_TAXONOMY = "0cdd6315dc47ef7cc99846ad40fda14a99a53c9e1ba9c9c68520d80f9257b5c4"

PARTS = {"market": -0.02, "cell_choice": 0.0, "selection": 0.0, "timing": 0.0, "exit": 0.0, "delay": 0.0,
         "costs": -0.01}


def trade(**over: Any) -> dict[str, Any]:
    """A plain losing trade where nothing in particular happened."""
    base = {"host": "S", "x": -0.03, "x_raw": -0.03, "g": -0.02, "cost": 0.01, "parts": dict(PARTS), "t_in": 1000.0,
            "t_out": 4000.0, "exit_reason": "time", "crash50": False, "t_crash": None, "mfe": 0.05,
            "stop_loss_pct": 0.18, "size_usd": 20.0, "dollar_pnl": -0.6, "equity_usd": 100.0, "rebound": 0.02,
            "regime_pct": 0.5, "hour_gap": 0.0, "cost_model": 0.012, "faults": []}
    base.update(over)
    return base


def types(t: dict[str, Any]) -> set[str]:
    return {f["type"] for f in losses.classify(t)}


def test_the_taxonomy_hash_is_pinned() -> None:
    assert TAXONOMY_VERSION == PINNED_TAXONOMY


def test_nothing_unusual_is_variance() -> None:
    flags = losses.classify(trade())
    assert flags == [{"type": "variance", "magnitude": None}] and losses.primary(flags) == "variance"


@pytest.mark.parametrize("name, over, magnitude", [
    ("rug_missed", {"crash50": True, "t_crash": 2000.0, "g": -0.9, "x": -0.92}, -0.72),
    ("regime", {"regime_pct": 0.05, "hour_gap": -0.08, "parts": {**PARTS, "market": -0.07}}, -0.07),
    ("oversize", {"dollar_pnl": -8.0, "equity_usd": 100.0, "size_usd": 20.0, "x": -0.4}, -0.15),
    ("late_entry", {"parts": {**PARTS, "delay": -0.03}}, -0.03),
    ("bad_entry", {"parts": {**PARTS, "selection": -0.04, "timing": -0.02}}, -0.06),
    ("early_exit", {"rebound": 0.35, "exit_reason": "stop"}, -0.20),
    ("late_exit", {"mfe": 0.30, "x": -0.05}, -0.35),
    ("cost_eaten", {"g": 0.01, "x": -0.01, "parts": {**PARTS, "costs": -0.02}}, -0.02),
    ("missed_winner", {"vetoed": True, "x_cf": 0.12}, -0.12),
])
def test_each_type_fires_on_its_constructed_case(name: str, over: dict[str, Any], magnitude: float) -> None:
    flags = {f["type"]: f for f in losses.classify(trade(**over))}
    assert name in flags and "variance" not in flags
    assert flags[name]["magnitude"] == pytest.approx(magnitude)


def test_early_exit_marks_stop_regret() -> None:
    flags = {f["type"]: f for f in losses.classify(trade(rebound=0.5, exit_reason="stop_loss"))}
    assert flags["early_exit"]["stop_regret"] is True and flags["early_exit"]["magnitude"] == pytest.approx(-0.2)
    assert losses.classify(trade(rebound=0.5, exit_reason="trail"))[0].get("stop_regret") is False


def test_costs_far_above_the_model_are_cost_eaten_even_on_a_gain() -> None:
    assert "cost_eaten" in types(trade(g=0.10, x=0.05, cost=0.05, cost_model=0.012))


def test_a_crash_after_the_exit_is_not_a_missed_rug() -> None:
    assert "rug_missed" not in types(trade(crash50=True, t_crash=5000.0))


@pytest.mark.parametrize("over", [{"faults": ["replay_disagrees"]}, {"candle_lag_s": 900.0},
                                  {"fill_quote_err": 0.02}])
def test_a_pipeline_fault_is_always_primary(over: dict[str, Any]) -> None:
    flags = losses.classify(trade(crash50=True, t_crash=2000.0, g=-0.95, x=-0.97, **over))
    assert {"pipeline_fault", "rug_missed"} <= {f["type"] for f in flags}
    assert losses.primary(flags) == "pipeline_fault"


def test_the_most_negative_magnitude_is_primary_ties_in_table_order() -> None:
    flags = losses.classify(trade(parts={**PARTS, "delay": -0.06, "selection": -0.03, "timing": -0.03}))
    assert {f["type"] for f in flags} == {"late_entry", "bad_entry"}
    assert losses.primary(flags) == "late_entry"  # -0.06 each: late_entry comes first in the table
    flags = losses.classify(trade(parts={**PARTS, "delay": -0.03, "selection": -0.05, "timing": -0.03}))
    assert losses.primary(flags) == "bad_entry"
    assert LOSS_TYPES.index("late_entry") < LOSS_TYPES.index("bad_entry")


def test_random_entries_get_bad_entry_on_selection_only() -> None:
    parts = {**PARTS, "selection": -0.04, "timing": -0.04}
    assert "bad_entry" in types(trade(parts=parts))
    assert "bad_entry" not in types(trade(host="R", parts=parts))
    assert "bad_entry" in types(trade(host="R", parts={**parts, "selection": -0.06}))


def test_rebound_after_reads_closes_within_an_hour_of_the_exit() -> None:
    bars = [Candle(60 * i, 1.0, 1.0, 1.0, p, 1.0) for i, p in enumerate([1.0] * 10 + [1.3] * 30 + [2.0] * 60)]
    assert losses.rebound_after(bars, 600.0, exit_price=1.0) == pytest.approx(1.0)
    assert losses.rebound_after(bars, 600.0, exit_price=1.0, window_s=1800) == pytest.approx(0.3)
    assert losses.rebound_after(bars, 600.0) == pytest.approx(1.0)  # exit price defaults to the close at the exit
    assert losses.rebound_after(bars[:20], 600.0) is None  # the hour after the exit is not covered


def r_row(primary: str, **over: Any) -> dict[str, Any]:
    row = {"host": "R", "speed": "fast", "age_band": "30-120", "mcap_tier": "<100k", "day": "2026-10-05",
           "primary": primary}
    row.update(over)
    return row


def test_luck_rates_come_from_random_entries_only() -> None:
    rows = [r_row("rug_missed")] * 3 + [r_row("variance")] * 7
    rates = losses.luck_rates(rows)
    key = losses.rate_key(rows[0])
    assert rates[key]["rug_missed"] == pytest.approx(0.3) and rates[key]["variance"] == pytest.approx(0.7)
    team = [{**r_row("bad_entry"), "host": "S"}] * 50 + [{**r_row("bad_entry"), "host": "paper"}] * 5
    assert losses.luck_rates(rows + team) == rates
    assert "pipeline_fault" not in rates[key]  # no base rate for types random entries cannot show


def test_the_week_summary_sets_counts_next_to_luck() -> None:
    rates = losses.luck_rates([r_row("rug_missed")] * 2 + [r_row("bad_entry")] + [r_row("variance")] * 7)
    pms = [{**r_row("rug_missed"), "host": "S"}] * 4 + [{**r_row("bad_entry"), "host": "S"}] * 6 \
        + [{**r_row("oversize"), "host": "paper"}]
    items = losses.week_summary(pms, rates)
    assert [i["type"] for i in items] == ["bad_entry", "rug_missed", "oversize"]
    assert items[0]["n"] == 6 and items[0]["expected"] == pytest.approx(11 * 0.1)
    assert items[1]["expected"] == pytest.approx(11 * 0.2) and items[2]["expected"] is None
    assert items[0]["text"] == "bad entry 6 (random entries in the same situations: 1.1 expected)"
    assert items[1]["text"] == "rug missed 4 (2.2 expected)"
