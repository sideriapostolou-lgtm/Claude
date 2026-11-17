"""The desks' risk manager, the statistics alone (nightcrawler.deskguard): the verdicts on synthetic records shaped
like the near-certain grind (many small wins, rare large losses), the bounds' accuracy, why the method was chosen
(measured on seeded Monte Carlo records), events (correlated settlements are one draw), the return per dollar at
risk, the early stop, the wording of small numbers, the documented error rates on the desk's own payoff shape, and
the pause's lifecycle."""

from __future__ import annotations

import json
import math
import random
import re
from statistics import NormalDist
from typing import Any

import pytest

from nightcrawler import deskguard as G

#: Exact one-sided Student-t quantiles (scipy.stats.t.ppf), so the check runs without scipy.
T_EXACT = {(10, 0.95): 1.812461, (29, 0.95): 1.699127, (99, 0.95): 1.660391, (999, 0.95): 1.646379,
           (10, 0.99): 2.763769, (29, 0.99): 2.462021, (99, 0.99): 2.364606, (999, 0.99): 2.330083,
           (9, 0.95): 1.833113, (1, 0.99): 31.820516}
#: Many small wins, rare big losses: nine +$0.40 settlements then one -$20 (90 % won, and still losing money).
GRIND = ([0.40] * 9 + [-20.0]) * 6
#: The Polymarket desk's own payoff: a $20 paper ticket bought at 0.975, the venue's taker fee paid.
TICKET, PRICE = 20.0, 0.975
SHARES = TICKET / PRICE
FEE = SHARES * 0.0695 * PRICE * (1 - PRICE)
WIN, LOSS = SHARES - FEE - TICKET, -FEE - TICKET  # +$0.48, -$20.03


def two_point(rng: random.Random, n: int, p_loss: float, win: float, loss: float) -> list[float]:
    return [loss if rng.random() < p_loss else win for _ in range(n)]


def p_loss_for(edge: float) -> float:
    """The loss rate at which the desk's ticket makes ``edge`` (a share of the ticket) a draw on average."""
    return 1.0 - (edge * TICKET - LOSS) / (WIN - LOSS)


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
    assert (v.mean, v.lower, v.upper) == (None, None, None) and not v.early
    assert G.judge([5.0] * 29).verdict == "learning"  # 29 wins prove nothing either
    assert G.judge([-20.0] * 9).verdict == "learning"  # under 10: nothing at all, even 9 straight losses
    assert G.judge([]).verdict == "learning" and G.judge([]).reason.startswith("0 of 30")
    assert G.judge(GRIND[:20], min_n=10).verdict != "learning"  # N is the caller's
    json.dumps(v.to_dict(), allow_nan=False)


def test_many_small_wins_with_rare_big_losses_is_losing() -> None:
    """90 % of the settlements won, and the desk loses money: the verdict reads the money, not the win rate."""
    v = G.judge(GRIND)
    assert sum(x > 0 for x in GRIND) / len(GRIND) == 0.9
    assert v.verdict == "losing" and v.upper is not None and v.upper < 0 and v.losses == 6
    assert v.reason == "60 settled, 6 lost, -$98.40 in all; even at best -$0.31 a settlement (95 % sure)"
    assert v.summary == "60 settled, 6 lost, -$98.40 in all" and v.settled == 60 and v.unit == "usd"
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
    assert G.judge(mild * 10, min_n=150, win_n=100).win_n == 150  # a WIN_N below MIN_N is raised to it


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


# --------------------------------------------------------------------------- events: one draw per outcome


def test_settlements_of_one_event_are_one_draw() -> None:
    """A game's three markets (long the leader, short the draw, short the trailer) settle on one result: one draw.
    n and the losses count events, the reason says so, and the money total stays the plain sum."""
    pnls = [0.5, 0.5, 0.5, -20.0, 0.4, -19.0]
    groups = ["g1", "g1", "g1", "g2", "g2", None]  # None: a draw of its own
    v = G.judge(pnls, groups=groups, min_n=2, early_n=2)
    assert (v.n, v.settled, v.losses, v.per) == (3, 6, 2, "event") and v.total == pytest.approx(-37.1)
    assert v.mean == pytest.approx((1.5 - 19.6 - 19.0) / 3)
    assert v.summary == "3 events (6 settled), 2 lost, -$37.10 in all" and "an event" in v.reason
    assert G.judge(pnls[:4], groups=groups[:4]).reason == "2 of 30 events needed before judging; so far -$18.50, 1 lost"
    with pytest.raises(ValueError, match="groups needs one value per settlement"):
        G.judge(pnls, groups=["g1"])
    # without groups every settlement is its own draw (the old reading)
    assert G.judge(pnls, min_n=2, early_n=2).n == 6
    # a junk settlement is dropped with its group key, the rest of the group stays
    junk = G.judge([0.5, float("nan"), -20.0], groups=["a", "a", "b"], min_n=2, early_n=2)
    assert (junk.n, junk.settled, junk.total) == (2, 2, -19.5)


def test_a_record_that_only_looks_proven_because_its_markets_move_together() -> None:
    """The same 100 settlements: as independent draws the record clears the winning bar; as the 50 two-market
    events they really are, it is not proven (and with one result per event, it cannot be)."""
    mild = [1.0] * 9 + [-3.0]
    pairs = [x for x in mild * 5 for _ in (0, 1)]
    assert G.judge(pairs).verdict == "winning"
    grouped = G.judge(pairs, groups=[i // 2 for i in range(100)])
    assert grouped.verdict == "unclear" and grouped.n == 50 and grouped.reason.endswith("needs 100 events to count as "
                                                                                         "proven")


def test_a_zero_edge_record_in_pairs_is_rarely_flagged_over_2000_settlements() -> None:
    """Seeded: a desk with no edge on its own payoff shape, every event two markets settling on one result, watched
    every 100 events up to 1,000 events (2,000 settlements). Judged per event it is flagged winning at most 5 % of
    the time (judged per settlement, the same records are flagged 12-18 %; see the next test)."""
    rng = random.Random(20261009)
    flagged = paused = 0
    paths = 150
    keys = [i // 2 for i in range(2000)]
    for _ in range(paths):
        events = two_point(rng, 1000, p_loss_for(0.0), WIN, LOSS)
        pnls = [x for x in events for _ in (0, 1)]
        seen = {G.judge(pnls[:2 * k], groups=keys[:2 * k], stakes=[TICKET] * (2 * k)).verdict
                for k in range(100, 1001, 100)}
        flagged += "winning" in seen
        paused += "losing" in seen
    assert flagged / paths <= 0.05 and paused / paths < 0.20


# --------------------------------------------------------------------------- the return per dollar at risk


def test_stakes_judge_the_return_per_dollar_so_a_ticket_change_never_mixes_scales() -> None:
    returns = ([0.025] * 39 + [-1.0]) * 3  # a ticket returns +2.5 % or loses it all: about no edge a settlement
    small = G.judge([r * 20 for r in returns], stakes=[20.0] * 120)
    mixed_stakes = [20.0] * 60 + [1000.0] * 60  # the owner raised the ticket half way
    mixed = G.judge([r * s for r, s in zip(returns, mixed_stakes)], stakes=mixed_stakes)
    assert (mixed.mean, mixed.lower, mixed.upper) == pytest.approx((small.mean, small.lower, small.upper))
    assert mixed.unit == "stake" and mixed.verdict == small.verdict == "unclear"
    assert mixed.total == pytest.approx(sum(r * s for r, s in zip(returns, mixed_stakes)))  # the money, in USD
    assert mixed.reason == ("120 settled, 3 lost, -$540.50 in all; between -2.49 % and +2.37 % of the stake a "
                            "settlement (95 % sure); not proven either way")
    # judged in dollars instead, the $1,000 tickets drown the $20 ones: one scale per test, never two
    dollars = G.judge([r * s for r, s in zip(returns, mixed_stakes)])
    assert dollars.unit == "usd" and dollars.upper is not None and dollars.upper > 10 * abs(mixed_stakes[0] * mixed.upper)
    # a group's draw is its return on the money it put at risk
    ev = G.judge([10.0, -5.0, 1.0], groups=["a", "a", "b"], stakes=[100.0, 100.0, 50.0], min_n=2, early_n=2)
    assert ev.mean == pytest.approx((5.0 / 200.0 + 1.0 / 50.0) / 2) and ev.unit == "stake"
    # a stake that is not a positive number drops its settlement
    assert G.judge([1.0, 2.0, 3.0], stakes=[1.0, 0.0, float("nan")], min_n=2).settled == 1
    with pytest.raises(ValueError, match="stakes needs one value per settlement"):
        G.judge([1.0, 2.0], stakes=[1.0])


# --------------------------------------------------------------------------- the early stop


def test_the_early_stop_calls_a_clear_loser_from_ten_draws() -> None:
    v = G.judge([-20.0] * 10)
    assert v.verdict == "losing" and v.early and v.n == 10
    assert v.reason == "10 settled, 10 lost, -$200.00 in all; even at best -$20.00 a settlement (99 % sure, early stop)"
    case = G.judge([-20.0] * 29)  # 29 straight losses: no longer "still learning"
    assert case.verdict == "losing" and case.early and case.reason.endswith("(99 % sure, early stop)")
    assert not G.judge([-20.0] * 30).early  # from MIN_N the full verdict
    assert G.judge([-20.0] * 12, early_n=15).verdict == "learning"  # the caller's
    # a 50 % loss rule: losing early; a usual grind's first 10-29 draws: learning
    assert G.judge(([0.48] + [-20.03]) * 5).verdict == "losing"
    assert G.judge(([0.48] * 8 + [-20.03] * 2) * 2).verdict == "learning"


def test_the_early_stop_never_fires_on_a_fair_grind_and_always_on_a_disaster() -> None:
    """Seeded, the desk's own payoffs, checked at every draw from 10 to 29: a zero-edge or a +0.9 % desk is never
    stopped early; a rule that loses 60 % of its tickets (the 2026-10-09 day) is stopped every time, soon."""
    rng = random.Random(3)
    for edge in (0.0, 0.009):
        for _ in range(300):
            xs = two_point(rng, 29, p_loss_for(edge), WIN, LOSS)
            assert not any(G.judge(xs[:n]).verdict == "losing" for n in range(10, 30)), edge
    stopped_at = []
    for _ in range(300):
        xs = two_point(rng, 29, 0.6, WIN, LOSS)
        stopped_at.append(next(n for n in range(10, 30) if G.judge(xs[:n]).verdict == "losing"))
    assert sorted(stopped_at)[150] <= 12 and max(stopped_at) <= 29


# --------------------------------------------------------------------------- small numbers


def test_a_bound_under_a_cent_is_never_shown_as_zero() -> None:
    zero = re.compile(r"\$0\.00(?!\d)")
    v = G.judge([-0.001] * 30)
    assert v.verdict == "losing" and not zero.search(v.reason)
    assert v.reason == "30 settled, 30 lost, -$0.03 in all; even at best -$0.001 a settlement (95 % sure)"
    assert G._usd(-0.003) == "-$0.003" and G._usd(0.0004) == "+$0.0004" and G._usd(0.00001234) == "+$0.000012"
    assert G._usd(0.0) == "$0.00" and G._usd(0.005) == "+$0.01" and G._usd(-1234.5) == "-$1,234.50"
    assert G._pct(-0.0123) == "-1.23 %" and G._pct(0.00001) == "+0.001 %" and G._pct(0.0) == "0.00 %"
    small = G.judge([0.001] * 97 + [-0.002] * 3)
    assert small.verdict == "winning" and not zero.search(small.reason) and "at worst +$0.0" in small.reason


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
    """Paths watched every 8 settlements up to 400, on a milder shape than the desk's (+$1 or -$19, +$0.50 or -$10;
    the desk's own shape is measured below): a zero-edge desk is rarely flagged a candidate for real money (the
    costly mistake); a desk with a real edge is almost never paused; a losing one is not flagged in these runs."""
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


def _replica(np: Any, xs: Any) -> tuple[Any, Any]:
    """judge()'s verdicts on every prefix of each row of ``xs`` (draws, one per event), vectorised: ``(losing,
    winning)`` boolean arrays. Checked against judge() itself before any rate is read."""
    w = xs.shape[1]
    ns = np.arange(1, w + 1)
    t95 = np.array([np.nan] + [G.t_quantile(n - 1, G.CONFIDENCE) for n in range(2, w + 1)])
    t99 = np.array([np.nan] + [G.t_quantile(n - 1, G.WIN_CONFIDENCE) for n in range(2, w + 1)])
    mean = np.cumsum(xs, 1) / ns
    var = np.maximum(np.cumsum(xs * xs, 1) - ns * mean * mean, 0) / np.maximum(ns - 1, 1)
    se = np.sqrt(var / ns)
    lost = xs < 0
    losses = np.cumsum(lost, 1)
    z, p = NormalDist().inv_cdf(G.WIN_CONFIDENCE), losses / ns
    rate = np.minimum(1.0, (p + z * z / (2 * ns) + z * np.sqrt(p * (1 - p) / ns + z * z / (4 * ns * ns)))
                      / (1 + z * z / ns))
    avg_win = np.cumsum(np.where(lost, 0, xs), 1) / np.maximum(ns - losses, 1)
    avg_loss = np.cumsum(np.where(lost, xs, 0), 1) / np.maximum(losses, 1)
    stressed = avg_win * (1 - rate) + avg_loss * rate
    early = (ns >= G.EARLY_N) & (ns < G.MIN_N) & (mean + t99 * se < 0)
    losing = early | ((ns >= G.MIN_N) & (mean + t95 * se < 0))
    winning = (ns >= G.WIN_N) & ~losing & (mean - t99 * se > 0) & (losses >= G.MIN_LOSSES) & (stressed > 0)
    return losing, winning


def test_the_documented_error_rates_on_the_desks_own_payoff_shape() -> None:
    """The module docstring's numbers, re-measured: $20 tickets at 0.975 (+$0.48 / -$20.03), the verdict re-checked
    after every draw as the desk does every round, 2,000 seeded paths. A vectorised copy of the method is checked
    against judge() itself (events of two markets, stakes) on random prefixes first; then the rates are read."""
    np = pytest.importorskip("numpy")
    rng = np.random.default_rng(20261009)

    def draws(edge: float, paths: int, n: int) -> Any:
        return np.where(rng.random((paths, n)) < p_loss_for(edge), LOSS, WIN) / TICKET  # the return on the stake

    def watched(xs: Any, *horizons: int) -> list[tuple[float, float]]:
        """(paused, flagged before any pause) by each horizon, the verdict re-checked after every draw."""
        losing, winning = _replica(np, xs)
        out = []
        for h in horizons or (xs.shape[1],):
            lo, wi = losing[:, :h], winning[:, :h]
            first_pause = np.where(lo.any(1), lo.argmax(1), h)
            first_flag = np.where(wi.any(1), wi.argmax(1), h)
            out.append((float((first_pause < h).mean()), float(((first_flag < first_pause) & (first_flag < h)).mean())))
        return out

    sample = draws(0.0, 30, 300)
    losing, winning = _replica(np, sample)
    pick = random.Random(1)
    for i in range(30):
        for n in pick.sample(range(5, 301), 8):
            pnls = [float(x) * TICKET / 2 for x in sample[i, :n] for _ in (0, 1)]  # each event: two half tickets
            v = G.judge(pnls, groups=[j // 2 for j in range(2 * n)], stakes=[TICKET / 2] * (2 * n))
            assert (v.verdict == "losing", v.verdict == "winning") == (losing[i, n - 1], winning[i, n - 1]), (i, n)
    (paused_1k, flagged_1k), (paused_2k, flagged_2k) = watched(draws(0.0, 2000, 2000), 1000, 2000)
    assert 0.11 <= paused_1k <= 0.16 and 0.15 <= paused_2k <= 0.20  # docstring: 13-14 % / 17-18 %
    assert 0.015 <= flagged_1k <= 0.035 and 0.025 <= flagged_2k <= 0.05  # docstring: 2.6-2.7 % / 3.8-4.4 %
    ((edge_paused, edge_flagged),) = watched(draws(0.009, 2000, 1000))
    assert edge_paused <= 0.015 and 0.36 <= edge_flagged <= 0.48  # docstring: under 1 %, 42 %
    assert watched(draws(-0.005, 2000, 1000))[0][1] <= 0.012  # docstring: 0.3-0.6 %, not never
    # two markets an event: per settlement (the old reading) the same zero-edge records look proven far more often
    events = draws(0.0, 1000, 1000)
    assert watched(np.repeat(events, 2, axis=1))[0][1] >= 0.12  # docstring: 17.5 %
    assert watched(events)[0][1] <= 0.05  # per event: 2.5 %


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
