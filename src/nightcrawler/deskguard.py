"""The desks' risk manager: an honest verdict on a desk's settled record, in plain words (owner: O5).

:func:`judge` is PURE (no clock, no files, no network, no randomness): give it one desk's per-settlement P&L for
the CURRENT rule only (paper and real money judged apart, never added) and it says one of four things:

* ``learning``: fewer than ``min_n`` settlements (default :data:`MIN_N` = 30). Nothing is claimed either way.
* ``losing``: the one-sided 95 % UPPER bound on the mean P&L per settlement is below the benchmark: even the
  best case the record allows loses money. A desk stops new buys on this (:func:`pause_step`).
* ``winning``: the one-sided 99 % LOWER bound is above the benchmark AND at least ``win_n`` settlements (default
  :data:`WIN_N` = 100) AND at least ``min_losses`` losses seen (default :data:`MIN_LOSSES` = 3) AND the record
  survives the loss stress test below. Only ever a CANDIDATE for real money: the owner decides; nothing here (or in
  any caller) switches real money on.
* ``unclear``: anything else, with the reason it is not proven.

Every verdict carries ``reason``: the count, the losses, the money and the bounds, so a person can check it.

WHY THIS METHOD (the payoffs are skewed). A near-certain grind (lab 4, ``research/lab4/READING.md``) wins a few
cents to a dollar on most settlements and loses most of a ticket on a few: many small wins, rare large losses. The
textbook intervals behave very differently in the two directions on such a record:

1. The Student-t bound ``mean +/- t(n-1) x s / sqrt(n)``. With rare large losses the sample mean and the sample
   spread move together: a sample that happened to meet few losses has a HIGH mean and a SMALL spread, so its t
   statistic runs high; one that met extra losses has a low mean but a LARGE spread, so its t statistic is muted.
   Hence the t bound is CONSERVATIVE for "losing" (one look at a desk whose true mean is exactly zero calls it
   losing 0.4-3 % of the time, under the nominal 5 %): a pause needs strong evidence. And it is OPTIMISTIC for
   "winning": 30 wins of +$0.30 and no loss have zero spread, so the lower bound is +$0.30, although one -$20 loss
   in 30 settlements is a desk that loses $0.37 a settlement (a bare t lower bound calls such a desk proven 40 % of
   the time at 30 settlements).
2. A bootstrap of the mean has the same blind spot (it only resamples the outcomes seen: a record without a loss
   never produces one), needs random numbers, and is costly every round, so it is not used.

So "losing" is the t upper bound (honest to pause on), and "winning" adds what the skew hides: a minimum count
of settlements, a minimum count of losses (a record that has not lost yet proves nothing), and a STRESS test: the
loss rate is raised to its one-sided upper bound (the Wilson score bound; with no loss in ``n`` it is about
``2.7 / n`` at 95 %, lab 4's "rule of three" worst case) and the mean is recomputed with the average win and the
average loss as seen; it must still beat the benchmark.

WHY 95 % TO PAUSE BUT 99 % TO PROMOTE (the desk looks every round). A verdict that is re-checked as the record
grows gets many chances to be wrong. Measured on synthetic skewed records checked after every settlement
(``tests/test_deskguard.py`` re-measures smaller versions):

* the 95 % pause stops a desk with exactly zero edge at some point in about 15-19 % of 1,000-2,000-settlement
  runs, a desk that truly makes money in under 1 %, and a desk that loses 1.5 % of its ticket a settlement in
  96 % by 1,000 settlements. Stopping a no-edge PAPER desk costs nothing (a rule without an edge after fees is not
  worth running), so the pause keeps the plain 95 % bar;
* the winning flag is the costly mistake (it points real money at a desk), so it uses the stricter 99 % bar for
  both the bound and the stress test: a zero-edge desk watched for 1,000-2,000 settlements is flagged in 2-5 % of
  runs (the 95 % bar: about 20 %), a losing one never, and a desk that truly makes about 0.9 % of its ticket a
  settlement in about 80 % by 1,000 settlements.

``benchmark`` (optional): ``None`` or a number is a hurdle per settlement (0: "makes money"); a list of the same
length is a paired benchmark (e.g. what holding would have made on the same trade) and the excess is judged. A
"loss" is then a settlement behind the benchmark. Non-finite values are dropped.

FOR ANOTHER DESK (e.g. a trend desk): keep each settled trade's P&L per rule version and book, call
``judge(pnls_of_the_current_rule)`` every round, and feed the verdict to :func:`pause_step` with that desk's own
pause record; refuse new buys while the pause is set, let open positions settle, and never let a verdict switch
real money on (a winning verdict is a flag for the owner, nothing more).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from statistics import NormalDist
from typing import Any

__all__ = [
    "CONFIDENCE",
    "LEARNING",
    "LOSING",
    "MIN_LOSSES",
    "MIN_N",
    "PHRASES",
    "UNCLEAR",
    "VERDICTS",
    "WINNING",
    "WIN_CONFIDENCE",
    "WIN_N",
    "Verdict",
    "judge",
    "loss_rate_upper",
    "pause_step",
    "t_quantile",
]

LEARNING = "learning"
LOSING = "losing"
WINNING = "winning"
UNCLEAR = "unclear"
VERDICTS = (LEARNING, LOSING, WINNING, UNCLEAR)
#: The verdicts in the owner's words (the page's line).
PHRASES = {LEARNING: "still learning", LOSING: "losing", WINNING: "winning", UNCLEAR: "not proven yet"}
MIN_N = 30  # settlements before any verdict
WIN_N = 100  # settlements before a record can be "winning"
MIN_LOSSES = 3  # losses seen before a record can be "winning"
CONFIDENCE = 0.95  # one-sided: the bounds shown, and the pause
WIN_CONFIDENCE = 0.99  # one-sided: the bar a record must clear to be "winning" (the module docstring says why)
#: Exact one-sided Student-t quantiles for 1..9 degrees of freedom (the expansion is used from 10 on).
_T_SMALL = {
    0.95: (6.313752, 2.919986, 2.353363, 2.131847, 2.015048, 1.943180, 1.894579, 1.859548, 1.833113),
    0.99: (31.820516, 6.964557, 4.540703, 3.746947, 3.364930, 3.142668, 2.997952, 2.896459, 2.821438),
}


@dataclass(frozen=True, slots=True)
class Verdict:
    """One desk book's verdict. Money is in the caller's unit (USD for the Polymarket desk). ``mean``, ``lower``
    and ``upper`` (the one-sided 95 % bounds), ``win_lower`` (the 99 % lower bound) and ``stressed`` (the mean
    with the loss rate at its 99 % upper bound, ``loss_rate_hi``) are per settlement and relative to the benchmark
    (the excess); ``total`` is the plain sum of the P&L; ``benchmark`` the mean hurdle per settlement."""

    verdict: str
    reason: str
    n: int
    losses: int
    total: float
    mean: float | None
    lower: float | None
    upper: float | None
    win_lower: float | None
    stressed: float | None
    loss_rate_hi: float | None
    benchmark: float
    min_n: int
    win_n: int

    @property
    def phrase(self) -> str:
        return PHRASES[self.verdict]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def t_quantile(df: int, confidence: float = CONFIDENCE) -> float:
    """The one-sided ``confidence`` quantile of Student's t with ``df`` degrees of freedom: a table for 1-9 (95 %
    and 99 % only), then the Cornish-Fisher expansion in the normal quantile (Abramowitz & Stegun 26.7.5; within
    1e-4 of the exact value from df 10 on at both levels)."""
    if df < 1:
        raise ValueError("df must be at least 1")
    if df < 10:
        if confidence not in _T_SMALL:
            raise ValueError("below 10 degrees of freedom only the 95 % and 99 % quantiles are known")
        return _T_SMALL[confidence][df - 1]
    z, v = NormalDist().inv_cdf(confidence), float(df)
    g1 = (z**3 + z) / 4.0
    g2 = (5 * z**5 + 16 * z**3 + 3 * z) / 96.0
    g3 = (3 * z**7 + 19 * z**5 + 17 * z**3 - 15 * z) / 384.0
    g4 = (79 * z**9 + 776 * z**7 + 1482 * z**5 - 1920 * z**3 - 945 * z) / 92160.0
    return z + g1 / v + g2 / v**2 + g3 / v**3 + g4 / v**4


def loss_rate_upper(losses: int, n: int, confidence: float = CONFIDENCE) -> float:
    """One-sided upper bound on the share of losses after ``losses`` in ``n`` (Wilson score bound; with no loss
    it is ``z^2 / (n + z^2)``: about 2.7 / n at 95 %, the rule of three)."""
    if n <= 0:
        return 1.0
    z = NormalDist().inv_cdf(confidence)
    p, z2 = losses / n, z * z
    centre = p + z2 / (2 * n)
    half = z * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n))
    return min(1.0, (centre + half) / (1.0 + z2 / n))


def _usd(value: float) -> str:
    cents = round(value, 2)
    if cents == 0:
        return "$0.00"
    return ("-" if cents < 0 else "+") + f"${abs(cents):,.2f}"


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _clean(pnls: Iterable[Any], benchmark: float | Sequence[float] | None) -> tuple[list[float], list[float], float]:
    """``(pnl, excess, mean benchmark)``: finite values only; a paired benchmark drops a pair with a bad side."""
    raw = list(pnls)
    if benchmark is None or isinstance(benchmark, (int, float)):
        hurdle = float(benchmark or 0.0)
        if not math.isfinite(hurdle):
            raise ValueError("benchmark must be a finite number")
        kept = [float(x) for x in raw if _finite(x)]
        return kept, [x - hurdle for x in kept], hurdle
    bench = list(benchmark)
    if len(bench) != len(raw):
        raise ValueError(f"a paired benchmark needs one value per settlement ({len(bench)} for {len(raw)})")
    pairs = [(float(a), float(b)) for a, b in zip(raw, bench) if _finite(a) and _finite(b)]
    kept = [a for a, _ in pairs]
    return kept, [a - b for a, b in pairs], (sum(b for _, b in pairs) / len(pairs) if pairs else 0.0)


def judge(pnls: Iterable[float], benchmark: float | Sequence[float] | None = None, *, min_n: int = MIN_N,
          win_n: int = WIN_N, min_losses: int = MIN_LOSSES) -> Verdict:
    """The verdict on one book's settled record (module docstring). ``pnls``: the P&L of every settlement of the
    current rule (one book: paper or real), any order. Pure; junk values are dropped, never raised on; only a
    paired benchmark of the wrong length raises."""
    min_n = max(2, int(min_n))
    win_n = max(min_n, int(win_n))
    min_losses = max(1, int(min_losses))
    kept, excess, bench = _clean(pnls, benchmark)
    n = len(kept)
    losses = sum(1 for x in excess if x < 0)
    total = sum(kept)
    plain = benchmark is None or (isinstance(benchmark, (int, float)) and benchmark == 0)
    lost = "lost" if plain else "behind the benchmark"
    per = "a settlement" if plain else "a settlement above the benchmark"
    head = f"{n} settled, {losses} {lost}, {_usd(total)} in all"

    def verdict(word: str, reason: str, **stats: float | None) -> Verdict:
        return Verdict(word, reason, n, losses, total, stats.get("mean"), stats.get("lower"), stats.get("upper"),
                       stats.get("win_lower"), stats.get("stressed"), stats.get("loss_rate_hi"), bench, min_n, win_n)

    if n < min_n:
        return verdict(LEARNING, f"{n} of {min_n} settlements needed before judging; so far {_usd(total)}, "
                                 f"{losses} {lost}")
    mean = sum(excess) / n
    se = math.sqrt(sum((x - mean) ** 2 for x in excess) / (n - 1) / n)
    lower, upper = mean - t_quantile(n - 1) * se, mean + t_quantile(n - 1) * se
    win_lower = mean - t_quantile(n - 1, WIN_CONFIDENCE) * se
    rate = loss_rate_upper(losses, n, WIN_CONFIDENCE)
    stressed = None
    if losses:
        ok = [x for x in excess if x >= 0]
        bad = [x for x in excess if x < 0]
        stressed = (sum(ok) / len(ok) if ok else 0.0) * (1.0 - rate) + sum(bad) / len(bad) * rate
    stats = {"mean": mean, "lower": lower, "upper": upper, "win_lower": win_lower, "stressed": stressed,
             "loss_rate_hi": rate}
    if upper < 0:
        return verdict(LOSING, f"{head}; even at best {_usd(upper)} {per} (95 % sure)", **stats)
    times = rate / (losses / n) if losses else 0.0
    if win_lower > 0 and n >= win_n and losses >= min_losses and stressed is not None and stressed > 0:
        return verdict(WINNING, f"{head}; at worst {_usd(win_lower)} {per} (99 % sure), ahead even with "
                                f"{times:.1f}x the losses", **stats)
    if lower <= 0:
        why = "not proven either way"
    elif n < win_n:
        why = f"needs {win_n} settled to count as proven"
    elif losses < min_losses:
        why = f"only {losses} {lost}: too few losses to trust the record"
    elif win_lower <= 0:
        why = "not yet 99 % sure, the bar for real money"
    else:
        why = f"losses {times:.1f}x as often would wipe it out"
    return verdict(UNCLEAR, f"{head}; between {_usd(lower)} and {_usd(upper)} {per} (95 % sure); {why}", **stats)


def pause_step(paused: Mapping[str, Any] | None, verdict: Verdict, *, rule: str, now: float, on: bool = True,
               what: str = "the desk") -> tuple[dict[str, Any] | None, str | None]:
    """One round of a book's pause, PURE: ``(the pause now, an event to record or None)``. ``paused`` is the
    book's pause record (``{at, reason, rule}``) or None; ``rule`` the desk's current rule version; ``on`` the
    owner's switch (off: never paused); ``what`` names the book in the event ("the desk", "real buys").

    * the switch is off: no pause (the event says a pause was lifted, when there was one);
    * a pause of an older rule: lifted (a changed rule starts a fresh record);
    * ``losing`` and not paused: paused, with the verdict's reason;
    * otherwise unchanged: a pause STICKS for its rule (a few lucky settlements after the evidence do not undo it;
      a changed rule or the owner's switch does). A pause only ever stops buying; nothing here starts any."""
    current = dict(paused) if isinstance(paused, Mapping) else None
    if not on:
        return None, (f"Risk manager switched off by the owner: the pause on {what} is lifted" if current else None)
    lifted = None
    if current is not None and current.get("rule") != rule:
        current = None
        lifted = f"Risk manager lifted the pause on {what}: the rule changed, its record starts from zero"
    if current is None and verdict.verdict == LOSING:
        return {"at": now, "reason": verdict.reason, "rule": rule}, f"Risk manager paused {what}: {verdict.reason}"
    return current, lifted
