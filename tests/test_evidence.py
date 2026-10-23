"""Pure statistics of docs/LEARNING.md §5.1 on a committed fixture of 500 REAL lab TRAIN/VAL returns,
zero-centred: the null false-crossing rate, power on a planted edge, order invariance, lower-bound
coverage, futility, CUSUM, proof and ETA."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

import pytest

from nightcrawler.learn import evidence as ev
from nightcrawler.learn.gate import CUSUM_REF, FUTILITY_E, FUTILITY_M, PAPER_ALPHA, PAPER_THRESHOLD

FIXTURE = Path(__file__).parent / "fixtures" / "learn_trainval_returns.json"
POOL = json.loads(FIXTURE.read_text(encoding="utf-8"))["returns"]
LOG_THR = math.log(PAPER_THRESHOLD)


def stream(rng: random.Random, n: int, shift: float = 0.0) -> list[float]:
    return [ev.clip(rng.choice(POOL) + shift) for _ in range(n)]


def first_crossing(xs: list[float], log_threshold: float, step=ev.step_up, **kw) -> int | None:
    """1-based index of the first trade after which log E >= log_threshold (checked after EVERY trade)."""
    logw = ev.start()
    for i, x in enumerate(xs, 1):
        logw = step(logw, x, **kw)
        if max(logw) >= log_threshold and ev.logmeanexp(logw) >= log_threshold:
            return i
    return None


def test_the_fixture_is_real_zero_centred_and_in_range() -> None:
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(POOL) == 500 and abs(sum(POOL) / len(POOL)) < 1e-9
    assert all(-1.0 <= x <= 1.0 for x in POOL)
    assert doc["raw_mean"] < 0 and 0.15 < doc["raw_sd"] < 0.3  # the lab's random entries lose before centring


def test_null_streams_cross_the_paper_threshold_no_more_than_alpha() -> None:
    """400 null streams x 1,500 trades, checked after every trade: crossings <= alpha + 3 SE (Ville)."""
    rng = random.Random(1)
    crossings = sum(first_crossing(stream(rng, 1500), LOG_THR) is not None for _ in range(400))
    se = math.sqrt(PAPER_ALPHA * (1 - PAPER_ALPHA) / 400)
    assert crossings / 400 <= PAPER_ALPHA + 3 * se


def test_a_planted_8pct_edge_reaches_200_within_400_trades() -> None:
    rng = random.Random(2)
    hits = [first_crossing(stream(rng, 400, shift=0.08), LOG_THR) for _ in range(200)]
    assert sum(h is not None for h in hits) / 200 >= 0.90


def test_the_e_value_does_not_depend_on_the_order() -> None:
    rng = random.Random(3)
    xs = stream(rng, 300, shift=0.03)
    shuffled = list(xs)
    rng.shuffle(shuffled)
    for m in (0.0, 0.02, -0.05):
        assert ev.log_e_up(xs, m) == pytest.approx(ev.log_e_up(shuffled, m), abs=1e-9)
        assert ev.log_e_up(xs, m) == pytest.approx(ev.log_e_up(list(reversed(xs)), m), abs=1e-9)
    assert ev.log_e_down(xs, FUTILITY_M) == pytest.approx(ev.log_e_down(shuffled, FUTILITY_M), abs=1e-9)


def test_the_running_lower_bound_covers_the_true_mean() -> None:
    """The always-valid LB (running max over looks) stays below the true mean in >= 1 - alpha of streams."""
    rng, alpha, mu = random.Random(4), 0.10, 0.02
    misses, lbs = 0, []
    for _ in range(100):
        xs = stream(rng, 300, shift=mu)
        lb = max(ev.lower_bound(xs[:n], alpha) for n in (100, 200, 300))
        lbs.append(lb)
        misses += lb > mu
    assert misses / 100 <= alpha + 3 * math.sqrt(alpha * (1 - alpha) / 100)
    assert sorted(lbs)[50] > -0.15  # and it is informative, not just -100 %


def test_lower_bound_edges() -> None:
    assert ev.lower_bound([], 0.05) == -1.0
    assert ev.lower_bound([1.0] * 200, 0.05) > 0.5
    assert ev.lower_bound([-1.0] * 50, 0.05) == -1.0
    xs = stream(random.Random(5), 400, shift=0.05)
    assert ev.lower_bound(xs, 0.05) < sum(xs) / len(xs)


def test_futility_retires_a_losing_stream_but_rarely_a_winner() -> None:
    rng, log_fut = random.Random(6), math.log(FUTILITY_E)
    losers = [first_crossing(stream(rng, 500, shift=-0.06), log_fut, step=ev.step_down, m=FUTILITY_M)
              for _ in range(100)]
    assert sum(h is not None for h in losers) >= 95
    assert sorted(h for h in losers if h)[len(losers) // 2] < 200  # spec simulation: a median of 93 trades
    winners = [first_crossing(stream(rng, 1000, shift=0.05), log_fut, step=ev.step_down, m=FUTILITY_M)
               for _ in range(100)]
    assert sum(h is not None for h in winners) <= 5  # Ville: P(ever >= 20) <= 1/20 under H0 E[x] >= 0.02


def test_steps_match_the_spec_formulas() -> None:
    w = ev.start()
    assert w == [0.0] * len(ev.LAMBDAS) and ev.LAMBDAS == (0.05, 0.10, 0.20, 0.35, 0.50, 0.70)
    up = ev.step_up(w, 0.1, m=0.02)
    assert up == pytest.approx([math.log1p(lam / 1.02 * 0.08) for lam in ev.LAMBDAS])
    down = ev.step_down(w, -0.1, m=0.02)
    assert down == pytest.approx([math.log1p(lam / 0.98 * 0.12) for lam in ev.LAMBDAS])
    assert ev.step_paired(w, 0.5) == pytest.approx([math.log1p(lam / 2 * 0.5) for lam in ev.LAMBDAS])
    assert ev.logmeanexp([0.0, math.log(3)]) == pytest.approx(math.log(2))
    assert ev.logmeanexp([1000.0, 1000.0]) == pytest.approx(1000.0)  # no overflow


def test_cusum_proof_and_eta() -> None:
    s = 0.0
    for x in (0.05, -0.2, -0.3, 0.1):
        s = ev.cusum_step(s, x)
    # S = max(0, S + (ref - x)), ref = -1 %: 0 -> 0 -> 0.19 -> 0.48 -> 0.37
    assert CUSUM_REF == -0.01 and s == pytest.approx(0.37)
    assert ev.proof(math.log(200), PAPER_THRESHOLD) == 1.0 and ev.proof(-3.0, PAPER_THRESHOLD) == 0.0
    assert ev.proof(math.log(200) / 2, PAPER_THRESHOLD) == pytest.approx(0.5)
    per_trade = 0.05 ** 2 / (2 * 0.22 ** 2)
    assert ev.eta_trades(0.0, PAPER_THRESHOLD, mean=0.05, sd=0.22) == pytest.approx(LOG_THR / per_trade)
    assert ev.eta_trades(0.0, PAPER_THRESHOLD, mean=-0.01, sd=0.22) is None
    assert ev.eta_trades(LOG_THR + 1, PAPER_THRESHOLD, mean=0.05, sd=0.22) == 0.0


def test_score_summarizes_a_stream() -> None:
    xs = stream(random.Random(7), 120, shift=0.04)
    s = ev.score(xs, threshold=PAPER_THRESHOLD, alpha=PAPER_ALPHA)
    assert s["n"] == 120 and s["sum_x"] == pytest.approx(sum(xs))
    assert s["sum_x2"] == pytest.approx(sum(x * x for x in xs)) and s["mean"] == pytest.approx(sum(xs) / 120)
    assert s["log_e"] == pytest.approx(ev.log_e_up(xs))
    assert s["log_e_fut"] == pytest.approx(ev.log_e_down(xs, FUTILITY_M))
    assert s["proof"] == pytest.approx(ev.proof(s["log_e"], PAPER_THRESHOLD))
    assert s["lb"] == pytest.approx(ev.lower_bound(xs, PAPER_ALPHA))
    assert ev.score(xs, threshold=PAPER_THRESHOLD, alpha=PAPER_ALPHA, prev_lb=0.9)["lb"] == 0.9  # running max
    empty = ev.score([], threshold=PAPER_THRESHOLD, alpha=PAPER_ALPHA)
    assert empty["n"] == 0 and empty["log_e"] == 0.0 and empty["mean"] is None and empty["eta_trades"] is None
