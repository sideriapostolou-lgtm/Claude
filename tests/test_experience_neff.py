"""Counting practice honestly (docs/EXPERIENCE.md §4.7, G53, A9): day blocks and independent situations.

* Day blocks merge consecutive judged days by COUNTS only (never outcomes), cap any operator at 30 % of a block
  (the excess dropped in hash order) and only ever return closed blocks, so a block never changes later.
* ``n_eff = n / (1 + (m_day - 1) rho_day + (m_op - 1) rho_op)``, with the ICCs estimated from forward rows only and
  shown ("about N independent situations (estimated)") only after 15 forward days.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from nightcrawler.experience import stats, texts
from nightcrawler.experience.constants import CLUSTER_MAX_SHARE, N_EFF_MIN_DAYS

DAY0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def day(i: int) -> str:
    return (DAY0 + timedelta(days=i)).strftime("%Y-%m-%d")


def units(counts: list[int], operators: int = 1000, seed: int = 0) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    return [{"mint": f"M{d}-{i}", "day": day(d), "operator": f"op{rng.randrange(operators)}", "x": rng.random()}
            for d, n in enumerate(counts) for i in range(n)]


def blocks_of(rows: list[dict[str, Any]], min_units: int = 20) -> list[stats.Block[dict[str, Any]]]:
    return stats.day_blocks(rows, day=lambda u: u["day"], operator=lambda u: u["operator"], key=lambda u: u["mint"],
                            min_units=min_units)


def test_days_are_merged_until_a_block_is_big_enough_and_open_blocks_are_not_returned() -> None:
    blocks = blocks_of(units([5, 10, 7, 30, 3, 4]))
    assert [b.days for b in blocks] == [(day(0), day(1), day(2)), (day(3),)]
    assert [len(b.units) for b in blocks] == [22, 30]  # days 4-5 (7 units) are still open


def test_blocks_depend_on_counts_only_never_on_outcomes() -> None:
    rows = units([12, 9, 25, 4, 19, 8])
    flipped = [{**r, "x": -r["x"] * 99} for r in rows]
    assert [b.days for b in blocks_of(rows)] == [b.days for b in blocks_of(flipped)]


def test_closed_blocks_never_change_as_days_arrive() -> None:
    rows = units([7, 11, 30, 2, 9, 14, 40, 3])
    for k in range(1, 9):
        prefix = [r for r in rows if r["day"] < day(k)]
        assert [b.units for b in blocks_of(prefix)] == [b.units for b in blocks_of(rows)][:len(blocks_of(prefix))]


def test_no_operator_keeps_more_than_its_share_dropped_in_hash_order() -> None:
    rows = [{"mint": f"F{i}", "day": day(0), "operator": "farm", "x": 0.0} for i in range(30)]
    rows += [{"mint": f"O{i}", "day": day(0), "operator": f"o{i}", "x": 0.0} for i in range(20)]
    (block,) = blocks_of(rows)
    farm = [u for u in block.units if u["operator"] == "farm"]
    assert len(farm) == int(CLUSTER_MAX_SHARE * 50) and block.dropped == 30 - len(farm)
    kept = sorted(f"F{i}" for i in range(30))
    kept.sort(key=stats.hash_key)
    assert sorted(u["mint"] for u in farm) == sorted(kept[:len(farm)])
    one_farm = [{"mint": f"F{i}", "day": day(d), "operator": "farm", "x": 0.0} for d in range(3) for i in range(30)]
    assert blocks_of(one_farm) == [] or all(len(b.units) >= 20 for b in blocks_of(one_farm))


def test_the_icc_estimator_recovers_a_known_clustering() -> None:
    rng = random.Random(1)
    for rho in (0.0, 0.13, 0.5):
        groups = []
        for _ in range(400):
            centre = rng.gauss(0, rho ** 0.5)
            groups.append([centre + rng.gauss(0, (1 - rho) ** 0.5) for _ in range(16)])
        assert stats.icc(groups) == pytest.approx(rho, abs=0.05)
    assert stats.icc([[1.0, 2.0]]) is None and stats.icc([[1.0], [2.0]]) is None
    assert stats.icc([[1.0, 1.0], [1.0, 1.0]]) == 0.0


def test_n_eff_matches_the_census_example() -> None:
    """DP fact 3: coin ICC 0.13 makes 16 random entries of a coin worth about 5.4 independent ones."""
    assert stats.n_eff(16, m_day=16, rho_day=0.13) == pytest.approx(16 / (1 + 15 * 0.13))
    assert stats.n_eff(16, m_day=16, rho_day=0.13) == pytest.approx(5.42, abs=0.01)
    assert stats.n_eff(100, m_day=1, rho_day=0.9, m_op=1, rho_op=0.9) == 100
    assert stats.n_eff(100, m_day=10, rho_day=0.1, m_op=5, rho_op=0.25) == pytest.approx(100 / (1 + 0.9 + 1.0))


def _forward(days: int, per_day: int, rho_day: float, seed: int = 2) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    rows = []
    for d in range(days):
        shift = rng.gauss(0, rho_day ** 0.5)
        for i in range(per_day):
            rows.append({"mint": f"M{d}-{i}", "source": "forward", "day": day(d), "operator": f"o{d}-{i}",
                         "x": shift + rng.gauss(0, (1 - rho_day) ** 0.5)})
    return rows


def _n(rows: list[dict[str, Any]]) -> float | None:
    return stats.independent_situations(rows, value=lambda r: r["x"], day=stats.row_day, operator=stats.row_operator)


def test_independent_situations_need_fifteen_forward_days_and_use_forward_rows_only() -> None:
    assert _n(_forward(N_EFF_MIN_DAYS - 1, 40, 0.2)) is None
    rows = _forward(40, 40, 0.2)
    n = _n(rows)
    assert n is not None and n < 0.5 * len(rows)  # day clustering costs most of the sample
    assert n == pytest.approx(len(rows) / (1 + 39 * 0.2), rel=0.5)
    history = [{**r, "source": "history", "split": "train", "x": 5.0 * (i % 7)} for i, r in enumerate(rows)]
    assert _n(rows + history) == n  # train and sealed splits never estimate a correlation
    assert _n(history) is None


def test_the_independent_line_is_empty_until_there_is_an_estimate() -> None:
    from nightcrawler.experience.cards import CardContext, cocoon_card
    assert texts.independent_line(_n(_forward(N_EFF_MIN_DAYS - 1, 40, 0.2))) == ""
    assert cocoon_card([], CardContext())["independent"] == ""
    line = texts.independent_line(1234.4)
    assert line == "about 1,234 independent situations (estimated)"
    assert cocoon_card([], CardContext(independent=line))["independent"] == line
