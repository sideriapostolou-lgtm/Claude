"""Report cards (docs/EXPERIENCE.md §5): one per team member, as the ``/api/page.experience`` member dict (§9). Pure.

Inputs are journal rows (§4.6 frozen columns: ``mint, source, host, created_ts, first_seen_ts, t_dec, t_in, t_out,
exit_reason, speed, age_band, crawler_ok, cocoon, cocoon_rules, cocoon_ts, radar_pre, jev, x, x_raw, crash50,
t_crash, dead, label_ready_ts`` ...), plus ``operator`` (creator, else ticker family; a coin is its own operator when
absent) and, optionally, ``day``. Only FORWARD rows set a label (X4): rows of coins created after the member
version's ``t0`` whose labels are ready at ``now`` (:class:`CardContext`, :func:`forward_rows`).

Three kinds (§5.1). VS CHANCE (Cocoon, Strategy, Radar, Jev): the primary statistic per closed day block, rescaled
into [-1, 1] (VV / 2, EE / 2, DS_net / 4), gets the always-valid band at the version's α_v; "Skill shown" needs the
whole band above 0 AND the stability veto, "Worse than chance" the whole band below 0, and every card first needs its
minimum and >= 7 distinct UTC days. VS BAR (Crawler, Broker, Risk): a written standard; Broker on paper is always
"Not measured" and Risk stays "Collecting" until its phase-2 ruin card. SELF-CHECK (Coach, Receipts): grey "Checks
pass" or red "Check failed", never green. Secondary metrics carry a 95 % block-bootstrap rough range and never set a
label. Metric values are in points (pp) unless their ``unit`` says otherwise; every string comes from
:mod:`~nightcrawler.experience.texts`.
"""

from __future__ import annotations

import functools
import math
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from nightcrawler.experience import stats, texts
from nightcrawler.experience.constants import (
    BLOCK_MIN_COINS,
    BLOCK_MIN_TRADES,
    BROKER_MIN_FILLS,
    BROKER_TOL_PP,
    CHANCE_MEMBERS,
    COACH_COVERAGE_TARGET,
    COACH_COVERAGE_TOL,
    COCOON_MIN,
    COVERAGE_BAR,
    COVERAGE_WINDOWS_MIN,
    CRAWLER_GATE_MIN,
    EARLY_WARNING_SHARE,
    EE_AGE_WINDOWS_S,
    EE_DAY_WINDOW,
    EE_MIN_CONTROLS,
    JEV_MIN_DECISIONS,
    JEV_MIN_NO,
    MEMBER_KIND,
    MEMBERS,
    MIN_DAYS,
    PER_RULE_MIN_BLOCKS,
    PLACEBO_MAX_MEAN,
    PLACEBO_WINDOW,
    RADAR_MIN_CRASHES,
    RADAR_MIN_EXITS,
    SKILLS_MEASURABLE,
    STRATEGY_MIN_COINS,
    STRATEGY_MIN_TRADES,
)
from nightcrawler.experience.stats import Block, alpha_v
from nightcrawler.experience.texts import say
from nightcrawler.learn.labels import is_bad

__all__ = [
    "CardContext",
    "ZERO_LESSONS",
    "metric",
    "empty_card",
    "forward_rows",
    "veto_value",
    "veto_stats",
    "cocoon_card",
    "cocoon_rules",
    "ControlIndex",
    "control_index",
    "match_controls",
    "strategy_card",
    "placebo_tau",
    "radar_card",
    "jev_card",
    "crawler_card",
    "broker_card",
    "risk_card",
    "coach_card",
    "receipts_card",
    "team_summary",
    "empty_state",
]

ZERO_LESSONS = {"open": 0, "testing": 0, "adopted": 0, "rejected": 0}
_DAY_S = 86400.0


@dataclass(frozen=True)
class CardContext:
    """What a card needs besides its rows: the member version's α_v and ``t0`` (from :func:`stats.alpha_ledger`),
    ``now`` (labels not ready by then are not read), the mode, and pass-through display fields."""

    alpha: float = alpha_v(1)
    t0: float | None = None
    now: float | None = None
    paper: bool = True
    budget_left: float | None = None
    exam: Mapping[str, Any] | None = None
    version_line: str = ""
    independent: str = ""
    lessons: Mapping[str, int] | None = None
    practised: int | None = None
    #: The member's data source exists (e.g. PR-E's tape rows; for Jev: the judge is on). False -> "Not measured".
    source_ready: bool = True


def metric(name: str, value: float | None, lo: float | None, hi: float | None, baseline: float | None, unit: str,
           text: str) -> dict[str, Any]:
    """One metric row (§9): ``unit`` is ``pp | share | ratio | count | s``."""
    return {"name": name, "value": _num(value), "lo": _num(lo), "hi": _num(hi), "baseline": _num(baseline),
            "unit": unit, "text": text}


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _pp(v: float | None) -> float | None:
    return None if v is None else 100.0 * v


def _points(value: float | None, lo: float | None, hi: float | None) -> str:
    """A fraction-valued estimate and range as ``+1.2 pts [-0.4, +2.8]``."""
    return say("t_points", v_pp=_pp(value), lo_pp=_pp(lo), hi_pp=_pp(hi))


def _card(member: str, label: str, ctx: CardContext, *, line: str = "", graded: int | None = None,
          days: int | None = None, metrics: Sequence[Mapping[str, Any]] = (), coverage: str = "") -> dict[str, Any]:
    return {"kind": MEMBER_KIND[member], "label": label, "chip": texts.chip_word(member, label, paper=ctx.paper),
            "line": line, "graded": graded, "days": days, "practised": ctx.practised, "metrics": list(metrics)[:3],
            "exam": dict(ctx.exam) if ctx.exam else None, "trend": [], "version_line": ctx.version_line,
            "independent": ctx.independent, "lessons": dict(ctx.lessons or ZERO_LESSONS), "coverage": coverage,
            "budget_left": _num(ctx.budget_left)}


def empty_card(member: str, ctx: CardContext | None = None) -> dict[str, Any]:
    """A member with no data source yet: ``not_measured`` (``not_built`` for a self-check)."""
    ctx = ctx or CardContext()
    label = "not_built" if MEMBER_KIND[member] == "self_check" else "not_measured"
    return _card(member, label, ctx, line=texts.label_text(member, label, paper=ctx.paper))


def _no_rows(member: str, ctx: CardContext) -> dict[str, Any]:
    """Nothing graded yet: "Collecting" when the data source exists, else "Not measured"."""
    if not ctx.source_ready:
        return empty_card(member, ctx)
    return _card(member, "not_enough", ctx, line=texts.label_text(member, "not_enough"), graded=0, days=0)


def forward_rows(rows: Iterable[Mapping[str, Any]], ctx: CardContext, *, host: str | None = None,
                 labelled: bool = True) -> list[Mapping[str, Any]]:
    """Rows that may set a label: forward or paper, of the host, created after ``t0``, with ``x`` known and (when
    ``labelled``) labels ready at ``now``."""
    out = []
    for r in rows:
        if r.get("source") not in stats.FORWARD_SOURCES or (host is not None and r.get("host") != host):
            continue
        if ctx.t0 is not None and not (_num(r.get("created_ts")) or -math.inf) > ctx.t0:
            continue
        if _num(r.get("x")) is None:
            continue
        ready = _num(r.get("label_ready_ts"))
        if labelled and ctx.now is not None and ready is not None and ready > ctx.now:
            continue
        out.append(r)
    return out


def _blocks(units: Sequence[Mapping[str, Any]], min_units: int) -> list[Block[Mapping[str, Any]]]:
    return stats.day_blocks(units, day=stats.row_day, operator=stats.row_operator, key=stats.row_key,
                            min_units=min_units)


def _days(units: Iterable[Mapping[str, Any]]) -> int:
    return len({stats.row_day(u) for u in units})


def _band(points: Sequence[tuple[str, float]], alpha: float,
          scale: float) -> tuple[float | None, float | None, float | None, bool]:
    """(value, lo, hi) in metric units (y x scale) and the stability veto, from block points (day, y)."""
    if not points:
        return None, None, None, False
    ys = [y for _, y in points]
    lo, hi = stats.band(ys, alpha)
    return math.fsum(ys) / len(ys) * scale, lo * scale, hi * scale, stats.stable(points)


def _rough(blocks: Sequence[Sequence[float]], seed: str) -> tuple[float | None, float | None]:
    """Rough range of the mean of per-unit values, resampling whole blocks (as per-block sums and counts)."""
    def stat(sample: Sequence[tuple[float, int]]) -> float | None:
        count = sum(n for _, n in sample)
        return sum(s for s, _ in sample) / count if count else None
    return stats.rough_range([(math.fsum(b), len(b)) for b in blocks if b], stat, seed=seed)


def _points_mean(points: Sequence[tuple[str, float]], seed: str) -> tuple[float | None, float | None, float | None]:
    """A secondary veto value in fraction units (2 y) with its rough range."""
    def stat(sample: Sequence[tuple[str, float]]) -> float | None:
        return stats.mean(2.0 * y for _, y in sample)
    lo, hi = stats.rough_range(points, stat, seed=seed)
    return stat(points), lo, hi


# --------------------------------------------------------------------------- the veto statistic (§5.1)


def veto_value(rows: Sequence[Mapping[str, Any]], passed: Callable[[Mapping[str, Any]], bool], *,
               min_units: int = BLOCK_MIN_COINS) -> list[tuple[str, float]]:
    """Per closed day block ``(last day, VV_b / 2)``, ``VV_b = mean(x | pass) - mean(x | all)`` over the rows a member
    checked. A block where nothing passed carries no value and is skipped (a decision-only rule)."""
    points = []
    for block in _blocks(rows, min_units):
        xs = [float(r["x"]) for r in block.units]
        kept = [float(r["x"]) for r in block.units if passed(r)]
        if kept:
            points.append((block.last_day, (math.fsum(kept) / len(kept) - math.fsum(xs) / len(xs)) / 2.0))
    return points


def veto_stats(rows: Sequence[Mapping[str, Any]], passed: Callable[[Mapping[str, Any]], bool]) -> dict[str, Any]:
    """RC (rugs blocked), FB (good coins wrongly blocked), the block share and the lift over a coin flip blocking
    the same share."""
    bad = [r for r in rows if is_bad(r.get("crash50"), r.get("dead")) is True]
    good = [r for r in rows if float(r["x"]) > 0]
    blocked = [r for r in rows if not passed(r)]
    share = len(blocked) / len(rows) if rows else None
    rc = sum(not passed(r) for r in bad) / len(bad) if bad else None
    fb = sum(not passed(r) for r in good) / len(good) if good else None
    return {"n": len(rows), "blocked": len(blocked), "passed": len(rows) - len(blocked), "bad": len(bad),
            "good": len(good), "block_share": share, "rc": rc, "fb": fb,
            "lift": rc / share if rc is not None and share else None}


# --------------------------------------------------------------------------- Cocoon (vs chance)


def _cocoon_checked(row: Mapping[str, Any]) -> bool:
    """A verdict counts for an entry only if it was decided at or before the entry's t_dec (else ``unchecked``)."""
    ts, t_dec = _num(row.get("cocoon_ts")), _num(row.get("t_dec"))
    return row.get("cocoon") in ("pass", "fail") and ts is not None and t_dec is not None and ts <= t_dec


def _cocoon_pass(row: Mapping[str, Any]) -> bool:
    return row.get("cocoon") == "pass"


def cocoon_card(rows: Iterable[Mapping[str, Any]], ctx: CardContext | None = None) -> dict[str, Any]:
    """The engine's real Cocoon verdicts graded on the R host (random entries in the bot's window)."""
    ctx = ctx or CardContext()
    graded = forward_rows(rows, ctx, host="R")
    if not graded:
        return _no_rows("cocoon", ctx)
    checked = [r for r in graded if _cocoon_checked(r)]
    vs = veto_stats(checked, _cocoon_pass)
    days = _days(checked)
    value, lo, hi, stable_ok = _band(veto_value(checked, _cocoon_pass), ctx.alpha, 2.0)
    enough = days >= MIN_DAYS and all(vs[k] >= COCOON_MIN[k] for k in COCOON_MIN)
    label = stats.chance_label(measured=True, enough=enough, lo=lo, hi=hi, stable_ok=stable_ok)
    unavailable = [r for r in checked if any(str(x).startswith("source_unavailable") for x in r.get("cocoon_rules")
                                             or ())]
    kept_mean = stats.mean(float(r["x"]) for r in checked if _cocoon_pass(r))
    line = say("cocoon", n=len(checked), days=days, lift_x=vs["lift"], rc_10=vs["rc"], block_10=vs["block_share"],
               fb_k=vs["fb"], vv_pp=_pp(value), lo_pp=_pp(lo), hi_pp=_pp(hi),
               still_lose_txt=say("still_lose") if kept_mean is not None and kept_mean < 0 else "",
               label_txt=texts.label_text("cocoon", label, alpha=ctx.alpha))
    metrics = [
        metric(say("m_after_blocks"), _pp(value), _pp(lo), _pp(hi), 0.0, "pp", _points(value, lo, hi)),
        metric(say("m_rugs_blocked"), vs["lift"], None, None, 1.0, "ratio",
               say("t_lift", lift_x=vs["lift"], rc_10=vs["rc"], block_10=vs["block_share"])),
        metric(say("m_false_blocks"), vs["fb"], None, None, vs["block_share"], "share",
               say("t_one_in", share_k=vs["fb"])),
    ]
    coverage = say("coverage", checked_pct=len(checked) / len(graded),
                   unavailable_pct=len(unavailable) / len(checked) if checked else None)
    return _card("cocoon", label, ctx, line=line, graded=len(checked), days=days, metrics=metrics, coverage=coverage)


def cocoon_rules(rows: Iterable[Mapping[str, Any]], ctx: CardContext | None = None) -> list[dict[str, Any]]:
    """Per rule id that was the FIRST reason of a block (G08): its block count and its VV as the veto (pp) with a
    rough range; ``no_value`` once it has >= 200 blocks and its range lies at or below 0. Details only: the flag
    nominates a lesson, it never demotes a rule."""
    ctx = ctx or CardContext()
    checked = [r for r in forward_rows(rows, ctx, host="R") if _cocoon_checked(r)]

    def first(r: Mapping[str, Any]) -> str:
        return str((r.get("cocoon_rules") or ["?"])[0])

    out = []
    for rule in sorted({first(r) for r in checked if r.get("cocoon") == "fail"}):
        def passed(r: Mapping[str, Any], rule: str = rule) -> bool:
            return not (r.get("cocoon") == "fail" and first(r) == rule)
        n = sum(not passed(r) for r in checked)
        vv, lo, hi = _points_mean(veto_value(checked, passed), f"cocoon-rule:{rule}")
        out.append({"rule": rule, "blocks": n, "vv_pp": _pp(vv), "lo_pp": _pp(lo), "hi_pp": _pp(hi),
                    "no_value": n >= PER_RULE_MIN_BLOCKS and hi is not None and hi <= 0})
    return out


# --------------------------------------------------------------------------- Strategy (vs chance)


def _age(row: Mapping[str, Any]) -> float | None:
    t = _num(row.get("t_in", row.get("t_dec")))
    start = _num(row.get("first_seen_ts", row.get("created_ts")))
    return None if t is None or start is None else t - start


@functools.lru_cache(maxsize=4096)
def _day_number(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() // _DAY_S)


#: (speed, day number) -> [(entry age, R row)]: random entries the Crawler's rules passed as of entry.
ControlIndex = Mapping[tuple[str, int], Sequence[tuple[float | None, Mapping[str, Any]]]]


def control_index(r_rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, int], list[tuple[float | None,
                                                                                            Mapping[str, Any]]]]:
    """Index R rows for :func:`match_controls` (only rows with ``crawler_ok`` True: the same eligible set)."""
    index: dict[tuple[str, int], list[tuple[float | None, Mapping[str, Any]]]] = defaultdict(list)
    for r in r_rows:
        if r.get("crawler_ok") is True:
            index[(str(r.get("speed")), _day_number(stats.row_day(r)))].append((_age(r), r))
    return index


def match_controls(trade: Mapping[str, Any], index: ControlIndex) -> list[Mapping[str, Any]]:
    """Matched random entries for one S trade: the same eligible set, the same speed class, the same UTC day +-1,
    an entry age within +-5 min - widened to +-15 min, then to the same age band, while fewer than 5 are found."""
    age = _age(trade)
    if age is None:
        return []
    speed, day = str(trade.get("speed")), _day_number(stats.row_day(trade))
    pool = [c for d in range(day - EE_DAY_WINDOW, day + EE_DAY_WINDOW + 1) for c in index.get((speed, d), ())]
    for window in EE_AGE_WINDOWS_S:
        found = [r for a, r in pool if a is not None and abs(a - age) <= window]
        if len(found) >= EE_MIN_CONTROLS:
            return found
    return [r for _, r in pool if r.get("age_band") == trade.get("age_band")]


def strategy_card(s_rows: Iterable[Mapping[str, Any]], r_rows: Iterable[Mapping[str, Any]],
                  ctx: CardContext | None = None, *, stop_loss_pct: float | None = None,
                  exit_placebo: Mapping[str, float] | None = None) -> dict[str, Any]:
    """Entry edge EE against matched random entries (S trades: the benchmark replay and paper trades), per trade
    ``x_S - mean(x of its matched R entries)``. ``exit_placebo``: ``{row_key: x with placebo exits}`` for the exit
    skill secondary (G36); without it, the stop-gap ratio (KP-5) when ``stop_loss_pct`` is given."""
    ctx = ctx or CardContext()
    trades = forward_rows(s_rows, ctx, host="S")
    if not trades:
        return _no_rows("strategy", ctx)
    controls = control_index(forward_rows(r_rows, ctx, host="R"))
    matched = []
    for trade in trades:
        found = match_controls(trade, controls)
        if found:
            matched.append({**trade, "_ee": float(trade["x"]) - math.fsum(float(c["x"]) for c in found) / len(found)})
    blocks = _blocks(matched, BLOCK_MIN_TRADES)
    points = [(b.last_day, math.fsum(u["_ee"] for u in b.units) / len(b.units) / 2.0) for b in blocks]
    value, lo, hi, stable_ok = _band(points, ctx.alpha, 2.0)
    coins = len({t.get("mint") for t in matched})
    days = _days(matched)
    enough = len(matched) >= STRATEGY_MIN_TRADES and coins >= STRATEGY_MIN_COINS and days >= MIN_DAYS
    label = stats.chance_label(measured=True, enough=enough, lo=lo, hi=hi, stable_ok=stable_ok)
    mean_x = stats.mean(float(t["x"]) for t in matched)
    m_lo, m_hi = _rough([[float(u["x"]) for u in b.units] for b in blocks], "strategy:mean")
    metrics = [metric(say("m_entries"), _pp(value), _pp(lo), _pp(hi), 0.0, "pp", _points(value, lo, hi)),
               metric(say("m_mean"), _pp(mean_x), _pp(m_lo), _pp(m_hi), 0.0, "pp", _points(mean_x, m_lo, m_hi))]
    if exit_placebo:
        es_blocks = [[float(u["x"]) - float(exit_placebo[stats.row_key(u)]) for u in b.units
                      if stats.row_key(u) in exit_placebo] for b in blocks]
        es = stats.mean(v for block in es_blocks for v in block)
        es_lo, es_hi = _rough(es_blocks, "strategy:exit")
        metrics.append(metric(say("m_exits"), _pp(es), _pp(es_lo), _pp(es_hi), 0.0, "pp", _points(es, es_lo, es_hi)))
    elif stop_loss_pct:
        gap = stats.mean(-float(t.get("x_raw", t["x"])) / stop_loss_pct for t in matched
                         if str(t.get("exit_reason") or "").startswith("stop"))
        metrics.append(metric(say("m_stop_gap"), gap, None, None, 1.0, "ratio", say("t_stop_gap", gap_x=gap)))
    line = say("strategy", n=len(matched), coins_n=coins, days=days, ee_pp=_pp(value), lo_pp=_pp(lo), hi_pp=_pp(hi),
               mean_pp=_pp(mean_x), label_txt=texts.label_text("strategy", label, alpha=ctx.alpha))
    return _card("strategy", label, ctx, line=line, graded=len(matched), days=days, metrics=metrics,
                 coverage=say("matched", k_n=len(matched), n=len(trades)))


# --------------------------------------------------------------------------- Radar (vs chance)


def placebo_tau(mint: str, t_in: float, delays_s: Sequence[float]) -> float | None:
    """A hash-seeded exit delay drawn from the Radar's own exit-time-from-entry distribution (None without one)."""
    if not delays_s:
        return None
    ordered = sorted(float(d) for d in delays_s)
    return ordered[int(stats.hash_key(f"radar-placebo:{mint}:{t_in}"), 16) % len(ordered)]


def radar_card(positions: Iterable[Mapping[str, Any]], ctx: CardContext | None = None, *,
               s_rows: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Danger-exit saving net of placebo exits. ``positions``: paper positions with ``x_hold`` (the position continued
    under its other exits), ``radar_exit`` (bool), ``x_radar`` and ``radar_exit_ts`` when the Radar pulled out,
    ``x_placebo`` (exiting at entry + :func:`placebo_tau`; None when it had closed before then) and the labels
    ``crash50`` / ``t_crash``. Per block, ``DS = mean(x_radar - x_hold)`` over radar exits minus
    ``DS_pl = mean(x_placebo - x_hold)`` over the positions still open at their placebo time, ``y = DS_net / 4``:
    early exits on a down-drifting tape save as much at random times, so only the difference counts (A4)."""
    ctx = ctx or CardContext()
    graded = [p for p in forward_rows(positions, ctx) if _num(p.get("x_hold")) is not None]
    if not graded:
        return _no_rows("radar", ctx)
    points = []
    for block in _blocks(graded, BLOCK_MIN_TRADES):
        saved = [float(p["x_radar"]) - float(p["x_hold"]) for p in block.units
                 if p.get("radar_exit") and _num(p.get("x_radar")) is not None]
        placebo = [float(p["x_placebo"]) - float(p["x_hold"]) for p in block.units
                   if _num(p.get("x_placebo")) is not None]
        if saved and placebo:
            points.append((block.last_day, (math.fsum(saved) / len(saved) - math.fsum(placebo) / len(placebo)) / 4.0))
    value, lo, hi, stable_ok = _band(points, ctx.alpha, 4.0)
    exits = [p for p in graded if p.get("radar_exit") and _num(p.get("x_radar")) is not None]
    days = _days(graded)
    label = stats.chance_label(measured=True, enough=len(exits) >= RADAR_MIN_EXITS and days >= MIN_DAYS, lo=lo, hi=hi,
                               stable_ok=stable_ok)
    crashes = [p for p in exits if p.get("crash50") is True and _num(p.get("t_crash")) is not None
               and _num(p.get("radar_exit_ts")) is not None]
    early = stats.mean(1.0 if float(p["radar_exit_ts"]) < float(p["t_crash"]) else 0.0 for p in crashes)
    early_shown = early if len(crashes) >= RADAR_MIN_CRASHES else None
    metrics = [metric(say("m_saved"), _pp(value), _pp(lo), _pp(hi), 0.0, "pp", _points(value, lo, hi)),
               metric(say("m_early"), early_shown, None, None, EARLY_WARNING_SHARE, "share",
                      say("t_crashes", n=len(crashes)))]
    signals = [r for r in forward_rows(s_rows, ctx, host="S") if r.get("radar_pre") in ("pass", "flag")]
    if signals:
        vv, v_lo, v_hi = _points_mean(veto_value(signals, lambda r: r.get("radar_pre") == "pass",
                                                 min_units=BLOCK_MIN_TRADES), "radar:pre")
        metrics.append(metric(say("m_pre_buy"), _pp(vv), _pp(v_lo), _pp(v_hi), 0.0, "pp", _points(vv, v_lo, v_hi)))
    else:
        false_alarms = stats.mean(1.0 if float(p["x_hold"]) >= float(p["x_radar"]) else 0.0 for p in exits)
        metrics.append(metric(say("m_false_alarms"), false_alarms, None, None, None, "share",
                              say("t_one_in", share_k=false_alarms)))
    line = say("radar", n=len(graded), days=days, ds_pp=_pp(value), lo_pp=_pp(lo), hi_pp=_pp(hi), early_10=early_shown,
               label_txt=texts.label_text("radar", label, alpha=ctx.alpha))
    return _card("radar", label, ctx, line=line, graded=len(graded), days=days, metrics=metrics,
                 coverage=say("radar_exits", k_n=len(exits), n=len(graded)))


# --------------------------------------------------------------------------- Jev (vs chance)


def jev_card(s_rows: Iterable[Mapping[str, Any]], ctx: CardContext | None = None, *,
             api_usd: float | None = None) -> dict[str, Any]:
    """VV of Jev's "no" on S signals that passed every deterministic rule, against a random no at the same rate
    (G47); ``not_measured`` ("Jev is off") while the judge is off."""
    ctx = ctx or CardContext()
    decided = [r for r in forward_rows(s_rows, ctx, host="S") if r.get("jev") in ("yes", "no")
               and r.get("cocoon") != "fail" and r.get("radar_pre") != "flag"]
    if not decided:
        return _no_rows("judge", ctx)

    def passed(r: Mapping[str, Any]) -> bool:
        return r.get("jev") == "yes"

    value, lo, hi, stable_ok = _band(veto_value(decided, passed, min_units=BLOCK_MIN_TRADES), ctx.alpha, 2.0)
    no = sum(not passed(r) for r in decided)
    days = _days(decided)
    enough = len(decided) >= JEV_MIN_DECISIONS and no >= JEV_MIN_NO and days >= MIN_DAYS
    label = stats.chance_label(measured=True, enough=enough, lo=lo, hi=hi, stable_ok=stable_ok)
    cost = api_usd / (100.0 * value * no) if api_usd is not None and value is not None and value > 0 and no else None
    metrics = [metric(say("m_after_no"), _pp(value), _pp(lo), _pp(hi), 0.0, "pp", _points(value, lo, hi)),
               metric(say("m_no_votes"), no, None, None, None, "count", say("t_of", k_n=no, n=len(decided))),
               metric(say("m_cost_point"), cost, None, None, None, "ratio", say("t_usd", v_usd=cost))]
    line = say("jev", n=len(decided), days=days, vv_pp=_pp(value), lo_pp=_pp(lo), hi_pp=_pp(hi), cost_usd=cost,
               label_txt=texts.label_text("judge", label, alpha=ctx.alpha))
    return _card("judge", label, ctx, line=line, graded=len(decided), days=days, metrics=metrics)


# --------------------------------------------------------------------------- Crawler (vs bar)


def _lag(coin: Mapping[str, Any]) -> float | None:
    seen = _num(coin.get("seen_ts"))
    return None if seen is None else max(0.0, seen - float(coin["eligible_ts"]))


def _recall(window_min: float, coins: Iterable[Mapping[str, Any]]) -> float | None:
    return stats.mean(1.0 if (x := _lag(c)) is not None and x <= window_min * 60 else 0.0 for c in coins)


def crawler_card(coins: Iterable[Mapping[str, Any]], ctx: CardContext | None = None, *,
                 w_rows: Iterable[Mapping[str, Any]] = (), r_rows: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Coverage of tradeable graduates. ``coins``: one per graduate with ``eligible_ts`` (max(recorder first_seen,
    created + MIN_AGE_MIN)), ``seen_ts`` (the Crawler's first sighting, None if never), ``mint``, ``source``, the day
    and operator. recall_15 per block is mapped to ``y = 2 r - 1`` for the band; the bar is 0.90 on its lower bound.
    The gate check (KP-1, W host) and the missed-coin parity (R host) are details, never a label."""
    ctx = ctx or CardContext()
    units = [c for c in coins if c.get("source") in stats.FORWARD_SOURCES and _num(c.get("eligible_ts")) is not None
             and (ctx.t0 is None or (_num(c.get("created_ts")) or -math.inf) > ctx.t0)]
    if not units:
        return _no_rows("crawler", ctx)
    blocks = stats.day_blocks(units, day=stats.row_day, operator=stats.row_operator,
                              key=lambda c: str(c.get("mint")), min_units=BLOCK_MIN_COINS)
    points = [(b.last_day, 2.0 * (_recall(15.0, b.units) or 0.0) - 1.0) for b in blocks]
    value = lo = hi = None
    stable_ok = False
    if points:
        ys = [y for _, y in points]
        y_lo, y_hi = stats.band(ys, ctx.alpha)
        value, lo, hi = (math.fsum(ys) / len(ys) + 1) / 2, (y_lo + 1) / 2, (y_hi + 1) / 2
        stable_ok = stats.stable(points, 2 * COVERAGE_BAR - 1)
    days = _days(units)
    label = stats.bar_label(measured=True, enough=days >= MIN_DAYS, lo=lo, hi=hi, bar=COVERAGE_BAR,
                            stable_ok=stable_ok)
    lags = sorted(x for c in units if (x := _lag(c)) is not None)
    r5, r15, r60 = (_recall(m, units) for m in COVERAGE_WINDOWS_MIN)
    metrics = [metric(say("m_seen15"), value, lo, hi, COVERAGE_BAR, "share", say("t_recall", recall_10=value)),
               metric(say("m_lag"), statistics.median(lags) if lags else None, None, None, None, "s",
                      say("t_lags", r5_pct=r5, r15_pct=r15, r60_pct=r60))]
    gate = ""
    w = forward_rows(w_rows, ctx, host="W")
    inside = sum(r.get("crawler_ok") is True for r in w)
    if inside >= CRAWLER_GATE_MIN and len(w) - inside >= CRAWLER_GATE_MIN:
        g_value, g_lo, g_hi, _ = _band(veto_value(w, lambda r: r.get("crawler_ok") is True), ctx.alpha, 2.0)
        gate = say("gate", vv_pp=_pp(g_value), lo_pp=_pp(g_lo), hi_pp=_pp(g_hi))
        metrics.append(metric(say("m_gate"), _pp(g_value), _pp(g_lo), _pp(g_hi), 0.0, "pp", gate))
    r_by_mint = {r.get("mint"): float(r["x"]) for r in forward_rows(r_rows, ctx, host="R")}
    missed = [r_by_mint[c["mint"]] for c in units if c.get("mint") in r_by_mint and (_lag(c) or math.inf) > 900]
    seen = [r_by_mint[c["mint"]] for c in units if c.get("mint") in r_by_mint and (_lag(c) or math.inf) <= 900]
    parity = None if not missed or not seen else math.fsum(missed) / len(missed) - math.fsum(seen) / len(seen)
    line = say("crawler", recall_10=value) + (" " + gate if gate else "")
    return _card("crawler", label, ctx, line=line, graded=len(units), days=days, metrics=metrics,
                 coverage="" if parity is None else say("missed_parity", v_pp=_pp(parity)))


# --------------------------------------------------------------------------- Broker (vs bar)


def broker_card(fills: Iterable[Mapping[str, Any]], ctx: CardContext | None = None, *,
                shortfalls: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Latency (a number, no label) from fills ``{ts, decision_ts}``. On paper ALWAYS ``not_measured``: a paper fill
    is the quote minus 100 bps and the cost model holds the same 100 bps, so the comparison is fixed by construction
    (A5). Live: ``shortfalls`` rows with ``x`` = implementation shortfall minus the pinned cost model (a fraction per
    round trip); "Meets the bar" when the band's upper bound is <= +0.5 pp."""
    ctx = ctx or CardContext()
    delays = sorted(float(f["ts"]) - float(f["decision_ts"]) for f in fills
                    if _num(f.get("ts")) is not None and _num(f.get("decision_ts")) is not None)
    p50 = statistics.median(delays) if delays else None
    p90 = delays[min(len(delays) - 1, math.ceil(0.9 * len(delays)) - 1)] if delays else None
    latency = metric(say("m_latency"), p50, None, p90, None, "s", say("t_latency", p50_s=p50, p90_s=p90))
    if ctx.paper:
        return _card("broker", "not_measured", ctx, line=say("broker_paper", p50_s=p50, p90_s=p90),
                     graded=len(delays), metrics=[latency])
    rows = [r for r in shortfalls if _num(r.get("x")) is not None]
    points = [(b.last_day, math.fsum(float(u["x"]) for u in b.units) / len(b.units) / 2.0)
              for b in _blocks(rows, BLOCK_MIN_TRADES)]
    value, lo, hi, _ = _band(points, ctx.alpha, 2.0)
    stable_ok = bool(points) and stats.stable(points, BROKER_TOL_PP / 200.0, higher_is_better=False)
    days = _days(rows) if rows else 0
    label = stats.bar_label(measured=bool(rows), enough=len(rows) >= BROKER_MIN_FILLS and days >= MIN_DAYS,
                            lo=_pp(lo), hi=_pp(hi), bar=BROKER_TOL_PP, higher_is_better=False, stable_ok=stable_ok)
    line = say("broker_live", p50_s=p50, p90_s=p90, sf_pp=_pp(value), lo_pp=_pp(lo), hi_pp=_pp(hi),
               label_txt=texts.label_text("broker", label, paper=False))
    sf = metric(say("m_shortfall"), _pp(value), _pp(lo), _pp(hi), BROKER_TOL_PP, "pp", _points(value, lo, hi))
    return _card("broker", label, ctx, line=line, graded=len(rows), days=days, metrics=[sf, latency])


# --------------------------------------------------------------------------- Risk (vs bar)


def risk_card(trades: Iterable[Mapping[str, Any]], ctx: CardContext | None = None, *,
              daily_limit_pct: float | None = None, equity_days: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Phase 1: the per-rug hit (ticket x realized loss / equity at entry, for paper trades with a ``crash50`` during
    the hold), the worst day against the daily limit (``equity_days``: ``{day, start_equity, end_equity}``) and the
    trades taken - always shown, so fewer trades never reads as better protection. The label stays "Collecting"
    until the phase-2 ruin card; risk limits themselves are never learnable."""
    ctx = ctx or CardContext()
    paper = [t for t in trades if t.get("source") in stats.FORWARD_SOURCES and _num(t.get("x")) is not None]
    hits = [float(t["size_usd"]) * -min(0.0, float(t.get("x_raw", t["x"]))) / float(t["equity_usd"]) for t in paper
            if t.get("crash50") is True and (_num(t.get("t_crash")) or math.inf) <= (_num(t.get("t_out")) or -math.inf)
            and (_num(t.get("size_usd")) or 0) > 0 and (_num(t.get("equity_usd")) or 0) > 0]
    rug = stats.mean(hits)
    worst, past = None, 0
    for d in equity_days:
        start, end = _num(d.get("start_equity")), _num(d.get("end_equity"))
        if start and end is not None:
            loss = max(0.0, 1.0 - end / start)
            worst = loss if worst is None else max(worst, loss)
            past += daily_limit_pct is not None and loss > daily_limit_pct
    days = _days(paper) if paper else 0
    metrics = [metric(say("m_rug"), rug, None, None, None, "share", say("t_rugs", n=len(hits))),
               metric(say("m_worst_day"), worst, None, None, daily_limit_pct, "share",
                      say("worst_day", worst_pct=worst, limit_pct=daily_limit_pct, days=past)),
               metric(say("m_trades"), len(paper), None, None, None, "count", say("t_trades", n=len(paper)))]
    return _card("risk", "not_enough", ctx, line=say("risk", n=len(paper), days=days, rug_pct=rug),
                 graded=len(paper), days=days, metrics=metrics)


# --------------------------------------------------------------------------- self-checks


def coach_card(placebo_xs: Sequence[float], coverage_hits: Sequence[bool], ctx: CardContext | None = None, *,
               min_coverage_n: int = 100) -> dict[str, Any]:
    """Self-check: the placebo keeps losing (mean of the last 300 placebo trades <= -1 %) and the situation tables'
    [q10, q90] hold 80 % +- 5 of outcomes. No forecaster yet (phases 1-2), so never green."""
    ctx = ctx or CardContext()
    recent = [float(x) for x in placebo_xs][-PLACEBO_WINDOW:]
    placebo_mean = stats.mean(recent)
    cover = stats.mean(1.0 if h else 0.0 for h in coverage_hits)
    checks = []
    if len(recent) >= PLACEBO_WINDOW and placebo_mean is not None:
        checks.append(placebo_mean <= PLACEBO_MAX_MEAN)
    if len(coverage_hits) >= min_coverage_n and cover is not None:
        checks.append(abs(cover - COACH_COVERAGE_TARGET) <= COACH_COVERAGE_TOL)
    label = "not_built" if not checks else "checks_pass" if all(checks) else "check_failed"
    metrics = [metric(say("m_placebo"), _pp(placebo_mean), None, None, _pp(PLACEBO_MAX_MEAN), "pp",
                      say("t_placebo", n=len(recent))),
               metric(say("m_ranges"), cover, None, None, COACH_COVERAGE_TARGET, "share",
                      say("t_outcomes", n=len(coverage_hits))),
               metric(say("m_forecaster"), None, None, None, None, "count", say("t_no_forecaster"))]
    losing = placebo_mean is None or placebo_mean <= PLACEBO_MAX_MEAN
    line = say("coach_ok" if losing else "coach_bad", pl_pp=_pp(placebo_mean), cov_10=cover)
    return _card("coach", label, ctx, line=line, graded=len(recent), metrics=metrics)


def receipts_card(checks: Mapping[str, bool | None], ctx: CardContext | None = None) -> dict[str, Any]:
    """Integrity only (chain verified; tape, journal and cell roots and pack hashes receipted; the last verify): not
    a skill, not counted."""
    ctx = ctx or CardContext()
    known = [v for v in checks.values() if v is not None]
    label = "not_built" if not known else "checks_pass" if all(known) else "check_failed"
    failed = sorted(k for k, v in checks.items() if v is False)
    line = texts.label_text("receipts", label)
    if failed:
        line += " " + say("checks_failed", names_txt=", ".join(failed))
    return _card("receipts", label, ctx, line=line, graded=len(known))


# --------------------------------------------------------------------------- the team (§8.2, §9)


def team_summary(members: Mapping[str, Mapping[str, Any]], *, graded: int | None, days: int | None,
                 practised: int | None, practised_window: str = "first_3h", practised_days: int | None = None,
                 coach_state: str | None = None, updated_at: float | None = None) -> dict[str, Any]:
    """The headline lines, the bars line, the money line, the caveat and ``team`` of ``/api/page.experience``."""
    labels = {m: str(c.get("label")) for m, c in members.items()}
    words = {m: str(members[m].get("chip") or "") for m in ("crawler", "broker", "risk") if m in members}
    return {
        "headline": texts.headline_lines(graded=graded, days=days, practised=practised,
                                         practised_window=practised_window, practised_days=practised_days,
                                         labels=labels),
        "bars_line": texts.bars_line(words), "money_line": texts.money_line(coach_state), "caveat": texts.CAVEAT,
        "team": {"graded": graded, "days": days, "practised": practised,
                 "practised_window": texts.PRACTICE_WINDOWS.get(practised_window, ""),
                 "skills_shown": sum(labels.get(m) == "skilled" for m in CHANCE_MEMBERS),
                 "skills_measurable": SKILLS_MEASURABLE,
                 "collecting": sum(labels.get(m, "not_enough") == "not_enough" for m in CHANCE_MEMBERS),
                 "not_measured": [m for m in CHANCE_MEMBERS if labels.get(m) == "not_measured"],
                 "updated_at": updated_at},
    }


def empty_state(source: str = "missing") -> dict[str, Any]:
    """The whole ``/api/page.experience`` value (§9) with every key present and nothing measured yet."""
    members = {m: empty_card(m) for m, _, _ in MEMBERS}
    summary = team_summary(members, graded=None, days=None, practised=None)
    return {"source": source, **summary, "members": members, "loss_types_week": [], "lessons": [],
            "playbook": {"validated": 0, "rejected": 0, "in_bot_contradicted": 0, "in_bot_unsupported": 0,
                         "testing": 0, "false_keep_bound": "1 in 10"}}
