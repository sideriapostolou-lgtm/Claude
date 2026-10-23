"""The page cannot turn explicitly incomparable practice results into live-policy evidence."""

from copy import deepcopy

import pytest

from nightcrawler.pagestate import _kalshi_pull


def test_new_pair_policy_hides_current_comparison_but_retains_original_history():
    raw = {"enabled": True, "pair_policy_comparable": False,
           "comparison_gap": "untrusted arbitrary payload",
           "since_pull": {"live_pnl_usd": -4, "twin_pnl_usd": 8, "live_minus_twin_usd": -12},
           "week_before": {"live_pnl_usd": -3, "twin_pnl_usd": 1}}
    before = deepcopy(raw)
    page = _kalshi_pull(raw, "2026-10-16")
    assert page is not None
    assert page["since_pull"] is None
    assert page["pair_policy_comparable"] is False
    assert "do not fully model" in page["comparison_gap"]
    assert "untrusted" not in page["comparison_gap"]
    assert page["week_before"]["live_pnl_usd"] == -3
    assert raw == before


@pytest.mark.parametrize("marker", [None, "false", 0, 1, True])
def test_legacy_comparison_is_not_rewritten_and_nonbooleans_do_not_assert_comparability(marker):
    raw = {"pair_policy_comparable": marker, "since_pull": {"live_pnl_usd": -4}}
    page = _kalshi_pull(raw, "2026-10-16")
    assert page is not None
    assert page["since_pull"]["live_pnl_usd"] == -4
    assert page["pair_policy_comparable"] is (True if marker is True else None)
    assert page["comparison_gap"] is None
