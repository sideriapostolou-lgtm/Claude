"""The desks' risk manager, the statistics alone (nightcrawler.deskguard): the verdicts on synthetic records shaped
like the near-certain grind (many small wins, rare large losses), the bounds' accuracy, why the method was chosen
(measured on seeded Monte Carlo records, small enough to run in about a second), and the pause's lifecycle."""

from __future__ import annotations

import json
import math
import random

import pytest

from nightcrawler import deskguard as G

#: Exact one-sided Student-t quantiles (scipy.stats.t.ppf), so the check runs without scipy.
T_EXACT = {(10, 0.95): 1.812461, (29, 0.95): 1.699127, (99, 0.95): 1.660391, (999, 0.95): 1.646379,
           (10, 0.99): 2.763769, (29, 0.99): 2.462021, (99, 0.99): 2.364606, (999, 0.99): 2.330083,
           (9, 0.95): 1.833113, (1, 0.99): 31.820516}
#: Many small wins, rare big losses: nine +$0.40 settlements then one -$20 (90 % won, and still losing money).
GRIND = ([0.40] * 9 + [-20.0]) * 6


def two_point(rng: random.Random, n: int, p_loss: float, win: float, loss: float) -> list[float]:
    return [loss if rng.random() < p_loss else win for _ in range(n)]


# --------------------------------------------------------------------------- the bounds


def test_the_t_quantile_and_the_loss_rate_bound_are_accurate() -> None:
    for (df, conf), exact in T_EXACT.items():
        assert G.t_quantile(df, conf) == pytest.approx(exact, abs=1e-4), (df, conf)
    with pytest.raises(ValueError):
        G.t_quantile(0)
    with pytest.raises(ValueError):
        G.t_quantile(5, 0.9)  # small samples: only the two levels the guard uses are tabled
    # no loss in n: the rule of three (about 2.7 / n at 95 %); the bound grows with the losses seen
    assert G.loss_rate_upper(0, 100) == pytest.approx(1.645 ** 2 / (100 + 1.645 ** 2), rel=1e-3)
    assert 0.025 < G.loss_rate_upper(0, 100) < 0.03 and G.loss_rate_upper(0, 0) == 1.0
    assert G.loss_rate_upper(3, 100) < G.loss_rate_upper(6, 100) < G.loss_rate_upper(6, 100, 0.99)
    assert G.loss_rate_upper(10, 100) > 0.10  # an UPPER bound sits above the share seen


def test_the_t_quantile_matches_scipy_everywhere_the_guard_uses_it() -> None:
    stats = pytest.importorskip("scipy.stats")
    for conf in (0.95, 0.99):
        worst = max(abs(G.t_quantile(df, conf) - float(stats.t.ppf(conf, df))) for df in range(1, 2000))
        assert worst < 1e-4, conf


# --------------------------------------------------------------------------- the verdicts


def test_tiny_samples_are_learning_whatever_they_show() -> None:
    v = G.judge(GRIND[:20])
    assert v.verdict == "learning" and v.phrase == "still learning" and v.n == 20 and v.losses == 2
    assert v.reason == "20 of 30 settlements needed before judging; so far -$32.80, 2 lost"
    assert (v.mean, v.lower, v.upper) == (None, None, None)
    assert G.judge([5.0] * 29).verdict == "learning"  # 29 wins prove nothing either
    assert G.judge([]).verdict == "learning" and G.judge([]).reason.startswith("0 of 30")
    assert G.judge(GRIND[:20], min_n=10).verdict != "learning"  # N is the caller's
    json.dumps(v.to_dict(), allow_nan=False)


def test_many_small_wins_with_rare_big_losses_is_losing() -> None:
    """90 % of the settlements won, and the desk loses money: the verdict reads the money, not the win rate."""
    v = G.judge(GRIND)
    assert sum(x > 0 for x in GRIND) / len(GRIND) == 0.9
    assert v.verdict == "losing" and v.upper is not None and v.upper < 0 and v.losses == 6
    assert v.reason == "60 settled, 6 lost, -$98.40 in all; even at best -$0.31 a settlement (95 % sure)"
    # 2026-10-09's paper day in shape: 114 settlements, 46 lost
    day = G.judge([0.3] * 68 + [-20.0] * 46)
    assert day.verdict == "losing" and day.reason.startswith("114 settled, 46 lost, -$899.60 in all; even at best")
    # the order of the settlements does not matter
    backwards = G.judge(list(reversed(GRIND)))
    assert backwards.verdict == "losing" and backwards.reason == v.reason and backwards.upper == pytest.approx(v.upper)


def test_a_genuinely_positive_skewed_record_wins_only_after_enough_settlements_and_losses() -> None:
    """19 wins of +$1 then one -$10 loss, over and over: +$0.45 a settlement, a real edge with rare big losses."""
    block = [1.0] * 19 + [-10.0]
    early = G.judge(block * 5)  # 100 settled, 5 lost: the 99 % bar is not met yet
    assert early.verdict == "unclear" and early.lower is not None and early.lower > 0
    assert early.reason.endswith("not yet 99 % sure, the bar for real money")
    mid = G.judge(block * 10)  # 200 settled: sure of the mean, but losses twice as often would erase it
    assert mid.verdict == "unclear" and mid.win_lower is not None and mid.win_lower > 0
    assert mid.reason.endswith("losses 2.0x as often would wipe it out")
    late = G.judge(block * 20)
    assert late.verdict == "winning" and late.phrase == "winning"
    assert late.reason == ("400 settled, 20 lost, +$180.00 in all; at worst +$0.17 a settlement (99 % sure), ahead "
                           "even with 1.6x the losses")
    assert late.stressed is not None and late.stressed > 0 and late.loss_rate_hi is not None
    assert late.loss_rate_hi > 20 / 400
    # a milder skew proves itself sooner, but never before WIN_N settlements
    mild = [1.0] * 9 + [-3.0]
    assert G.judge(mild * 9).verdict == "unclear" and G.judge(mild * 9).reason.endswith("needs 100 settled to count "
                                                                                          "as proven")
    assert G.judge(mild * 10).verdict == "winning"
    assert G.judge(mild * 10, win_n=200).verdict == "unclear"  # M is the caller's


def test_a_record_that_has_not_lost_yet_proves_nothing() -> None:
    v = G.judge([0.5] * 150)
    assert v.lower == pytest.approx(0.5) and v.win_lower == pytest.approx(0.5)  # no spread: a "certain" +$0.50
    assert v.verdict == "unclear" and v.reason.endswith("only 0 lost: too few losses to trust the record")
    two = G.judge([0.5] * 148 + [-1.0, -1.0])
    assert two.verdict == "unclear" and two.reason.endswith("only 2 lost: too few losses to trust the record")
    assert G.judge([0.5] * 148 + [-1.0, -1.0], min_losses=2).verdict == "winning"


def test_benchmarks_and_junk() -> None:
    record = [1.0] * 9 + [-3.0]
    # a hurdle per settlement: +$0.60 a settlement does not beat a $0.70 hurdle
    hurdle = G.judge(record * 10, 0.70)
    assert hurdle.verdict != "winning" and hurdle.benchmark == 0.70 and "behind the benchmark" in hurdle.reason
    assert "above the benchmark" in hurdle.reason and hurdle.total == pytest.approx(60.0)
    # a paired benchmark: the excess over what holding made on the same trade is judged
    held = [0.9] * 100
    paired = G.judge(record * 10, held)
    assert paired.benchmark == pytest.approx(0.9) and paired.verdict == "losing"  # -$0.30 a settlement behind it
    with pytest.raises(ValueError):
        G.judge([1.0, 2.0], [1.0])
    # junk values are dropped, never raised on
    v = G.judge(GRIND + [float("nan"), float("inf"), None, "x", True])  # type: ignore[list-item]
    assert v.n == 60 and v.verdict == "losing"
    json.dumps(G.judge([1.0] * 40).to_dict(), allow_nan=False)  # zero spread: finite bounds


# --------------------------------------------------------------------------- why this method (measured)


def test_why_t_plus_a_loss_count_one_look_on_seeded_skewed_records() -> None:
    """One look at many seeded records. (1) A desk with exactly zero edge (+$1 or -$19 at 5 %) is called losing
    well under 5 % of the time: the t bound is conservative for the pause on these payoffs. (2) A desk that loses
    $0.31 a settlement (+$0.30, or -$20 at 3 %) looks proven by a bare t lower bound in about 40 % of 30-settlement
    records (no loss met yet: no spread), and the guard never calls it winning."""
    rng = random.Random(20261009)
    for n in (30, 100):
        records = [two_point(rng, n, 0.05, 1.0, -19.0) for _ in range(600)]
        losing = sum(G.judge(r).verdict == "losing" for r in records) / len(records)
        assert losing < 0.05, (n, losing)
    loser = [two_point(rng, 30, 0.03, 0.3, -20.0) for _ in range(600)]
    bare_t = sum(G.judge(r).lower > 0 for r in loser) / len(loser)  # type: ignore[operator]
    assert bare_t > 0.25 and not any(G.judge(r).verdict == "winning" for r in loser)
    loser100 = [two_point(rng, 100, 0.03, 0.3, -20.0) for _ in range(300)]
    assert not any(G.judge(r).verdict == "winning" for r in loser100)


def test_why_95_to_pause_and_99_to_promote_when_the_desk_looks_every_round() -> None:
    """Paths watched every 8 settlements up to 400: a zero-edge desk is rarely flagged a candidate for real money
    (the costly mistake); a desk with a real edge is almost never paused; a losing one is never flagged."""
    rng = random.Random(7)

    def watched(p_loss: float, win: float, loss: float, paths: int) -> tuple[float, float]:
        paused = flagged = 0
        for _ in range(paths):
            xs = two_point(rng, 400, p_loss, win, loss)
            seen = {G.judge(xs[:i]).verdict for i in range(32, 401, 8)}
            paused += "losing" in seen
            flagged += "winning" in seen
        return paused / paths, flagged / paths

    zero_paused, zero_flagged = watched(0.05, 1.0, -19.0, 120)
    assert zero_flagged <= 0.05 and zero_paused < 0.25  # a no-edge paper desk may be stopped: that costs nothing
    edge_paused, _ = watched(0.03, 0.5, -10.0, 80)  # +$0.19 a settlement
    assert edge_paused <= 0.03
    _, loser_flagged = watched(0.03, 0.3, -20.0, 80)
    assert loser_flagged == 0


# --------------------------------------------------------------------------- the pause


def test_the_pause_lifecycle_is_pure_and_only_ever_stops_buying() -> None:
    losing, unclear, learning = G.judge(GRIND), G.judge([1.0] * 9 + [-3.0] * 1 + [0.1] * 30), G.judge([])
    assert unclear.verdict == "unclear"
    paused, text = G.pause_step(None, losing, rule="r1", now=100.0)
    assert paused == {"at": 100.0, "reason": losing.reason, "rule": "r1"}
    assert text == f"Risk manager paused the desk: {losing.reason}"
    # a pause sticks for its rule: a better verdict after the evidence does not undo it, and nothing is repeated
    assert G.pause_step(paused, unclear, rule="r1", now=200.0) == (paused, None)
    assert G.pause_step(paused, losing, rule="r1", now=200.0) == (paused, None)
    # a changed rule: a fresh record, the pause is lifted
    assert G.pause_step(paused, learning, rule="r2", now=300.0) == (
        None, "Risk manager lifted the pause on the desk: the rule changed, its record starts from zero")
    again, text = G.pause_step({"at": 1.0, "reason": "old", "rule": "r0"}, losing, rule="r2", now=300.0, what="real buys")
    assert again == {"at": 300.0, "reason": losing.reason, "rule": "r2"} and text.startswith("Risk manager paused real buys")
    # the owner's switch
    assert G.pause_step(paused, losing, rule="r1", now=400.0, on=False) == (
        None, "Risk manager switched off by the owner: the pause on the desk is lifted")
    assert G.pause_step(None, losing, rule="r1", now=400.0, on=False) == (None, None)
    # winning and learning never pause and never "unpause" into anything else
    assert G.pause_step(None, G.judge(([1.0] * 9 + [-3.0]) * 10), rule="r1", now=1.0) == (None, None)
    assert G.pause_step(None, learning, rule="r1", now=1.0) == (None, None)
    assert math.isfinite(losing.upper or 0.0)
