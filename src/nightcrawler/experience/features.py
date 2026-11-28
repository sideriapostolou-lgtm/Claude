"""What was knowable at a decision, and the weekly lesson test (docs/EXPERIENCE.md §4.2, §4.6, §6.5). Pure.

AS OF ``t`` (X3): everything here reads a coin through ``TapeView`` (candle minute m visible from ``m + 60 + L_obs``,
state rows from their fetch time) and engine decision rows with ``ts <= t``; nothing after ``t`` can change a result
(``tests/test_experience_asof.py`` replaces it with garbage).

* :func:`cell_at` - the cell (speed, age band, market-cap tier) of a coin at ``t``.
* :func:`verdicts_at` - the gatekeepers' real verdicts at ``t``: the Cocoon's ``watch`` (pass) and ``reject_cocoon``
  (fail) rows, the Radar's ``reject_radar`` (flag; a later-stage row means it passed), Jev's verdict (``n/a`` while
  the judge is off). A verdict decided after ``t`` does not exist yet: the member is ``unchecked`` / ``n/a``.
* :func:`features_at` - every feature of the catalogue (``constants.FEATURES``): ``{value, first_flag_ts}`` with
  value True / False / None (unknown at t, or history-only). ``first_flag_ts`` is when the current run of True
  became visible.

LESSONS (:func:`weekly_lessons`): each nominated feature f and cell family c is one group. Its statistic runs over
EVERY trade in c, winners included: ``VV_f = mean(x | not f) - mean(x | all)`` per day block, stratified by cell
(speed x age band) so that a feature that only marks a worse cell is not credited (G51), as ``y = VV_f / 2``. Each
group's betting e-process (H0: VV_f <= 0) feeds a weekly e-BH at q = 10 %; a selected group opens a lesson only with
>= 10 flagged losing trades from >= 5 operators on >= 3 days (folklore features: >= 7 days) and the same sign in both
halves of its record, once per taxonomy version, at most 3 a week. A lesson is a HYPOTHESIS DRAFT for the outbox -
never a change to Settings, specs, the playbook or code - and its effect is marked "selected (biased upward)".
Rows may come only from forward/paper data and the ``train`` history split (:class:`SplitLocked` otherwise).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from nightcrawler.experience import stats
from nightcrawler.experience.constants import (
    AGE_BAND_NAMES,
    AGE_BANDS_MIN,
    BLOCK_MIN_COINS,
    BLOCK_MIN_TRADES,
    CELL_FAMILIES,
    FEATURE_IDS,
    FEATURE_THRESHOLDS,
    FOLKLORE_FEATURES,
    FOLKLORE_MIN_DAYS,
    LESSON_MIN_DAYS,
    LESSON_MIN_FLAGGED_LOSERS,
    LESSON_MIN_OPERATORS,
    LESSON_Q,
    LESSON_SPLITS,
    LESSON_WEEKLY_CAP,
    MCAP_TIER_NAMES,
    MCAP_TIERS_USD,
    NOMINATES,
    SPEED_FAST_FORWARD_S,
    SPEED_FAST_HISTORY_S,
    TAXONOMY_VERSION,
    UNKNOWN,
    WARN_IDS,
)
from nightcrawler.learn import evidence as ev
from nightcrawler.learn.tape import TapeView
from nightcrawler.models import Candle

__all__ = [
    "SplitLocked",
    "speed_of",
    "age_band",
    "mcap_tier",
    "cell_at",
    "cell_family",
    "rule_id",
    "verdicts_at",
    "features_at",
    "nominated",
    "check_lesson_rows",
    "group_record",
    "lesson_id",
    "weekly_lessons",
]

_MINUTE = 60
_RADAR_PASSED = ("enter", "reject_judge", "reject_quote")


class SplitLocked(PermissionError):
    """Lessons may not be mined from this split (only forward/paper rows and history ``train``)."""


# --------------------------------------------------------------------------- cells


def speed_of(created_ts: float | None, graduated_ts: float | None, *, source: str = "forward") -> str:
    """``fast`` / ``slow`` / ``unknown``. Forward ``graduated_ts`` is first_seen (a proxy); history uses g."""
    if created_ts is None or graduated_ts is None:
        return UNKNOWN
    limit = SPEED_FAST_HISTORY_S if source == "history" else SPEED_FAST_FORWARD_S
    return "fast" if graduated_ts - created_ts <= limit else "slow"


def age_band(age_s: float | None) -> str:
    if age_s is None or not math.isfinite(age_s) or age_s < 0:
        return UNKNOWN
    minutes = age_s / _MINUTE
    for edge, name in zip(AGE_BANDS_MIN, AGE_BAND_NAMES, strict=False):
        if minutes < edge:
            return name
    return AGE_BAND_NAMES[-1]


def mcap_tier(mcap_usd: float | None) -> str:
    if mcap_usd is None or not math.isfinite(mcap_usd):
        return UNKNOWN
    for edge, name in zip(MCAP_TIERS_USD, MCAP_TIER_NAMES, strict=False):
        if mcap_usd < edge:
            return name
    return MCAP_TIER_NAMES[-1]


def _visible(view: TapeView, t: float) -> list[Candle]:
    if t > view.as_of:
        raise ValueError("a view cannot answer for a time after its as_of")
    return [c for c in view.candles() if c.ts + _MINUTE + view.l_obs <= t]


def _supply(view: TapeView) -> float | None:
    supply = (view.launch or {}).get("supply")
    return float(supply) if isinstance(supply, (int, float)) and supply > 0 else None


def cell_at(view: TapeView, t: float) -> dict[str, str]:
    """``{speed, age_band, mcap_tier}`` at ``t`` (all ``unknown`` before the coin was first seen graduated)."""
    seen = view.first_seen_ts
    if seen is None or t < seen:
        return {"speed": UNKNOWN, "age_band": UNKNOWN, "mcap_tier": UNKNOWN}
    bars, supply = _visible(view, t), _supply(view)
    mcap = bars[-1].c * supply if bars and supply else None
    return {"speed": speed_of(view.created_ts, seen), "age_band": age_band(t - seen), "mcap_tier": mcap_tier(mcap)}


def cell_family(row: Mapping[str, Any]) -> str | None:
    """``"<speed>|<age band>"`` of a journal row, None when either is unknown."""
    speed, band = row.get("speed"), row.get("age_band")
    return f"{speed}|{band}" if speed in ("fast", "slow") and band in AGE_BAND_NAMES else None


# --------------------------------------------------------------------------- verdicts


def rule_id(reason: str) -> str:
    """``"[top10] top 10 hold 52%"`` -> ``"top10"``; ``"source unavailable: rugcheck (..)"`` ->
    ``"source_unavailable:rugcheck"``."""
    text = str(reason).strip()
    if text.startswith("[") and "]" in text:
        return text[1:text.index("]")]
    if text.lower().startswith("source unavailable:"):
        source = text.split(":", 1)[1].strip().split(" ", 1)[0]
        return f"source_unavailable:{source}"
    return text.split(" ", 1)[0].lower()


def verdicts_at(evals: Iterable[Mapping[str, Any]], t: float) -> dict[str, Any]:
    """The member verdicts of one coin's decision rows as of ``t`` (see the module docstring)."""
    out: dict[str, Any] = {"cocoon": "unchecked", "cocoon_rules": [], "cocoon_ts": None, "radar_pre": "n/a",
                           "jev": "n/a"}
    rows = sorted((r for r in evals if float(r.get("ts", math.inf)) <= t), key=lambda r: float(r["ts"]))
    for row in rows:
        decision = row.get("decision")
        if decision == "watch":
            out.update(cocoon="pass", cocoon_rules=[], cocoon_ts=float(row["ts"]))
        elif decision == "reject_cocoon":
            safety = row.get("safety") or {}
            out.update(cocoon="fail", cocoon_ts=float(row["ts"]),
                       cocoon_rules=[rule_id(r) for r in safety.get("hard_fail_reasons") or ()])
        if decision == "reject_radar":
            out["radar_pre"] = "flag"
        elif decision in _RADAR_PASSED:
            out["radar_pre"] = "pass"
        verdict = row.get("verdict")
        if decision == "reject_judge":
            out["jev"] = "no"
        elif isinstance(verdict, Mapping):
            out["jev"] = "n/a" if verdict.get("source") == "rules" else \
                ("yes" if verdict.get("decision") == "yes" else "no")
    return out


# --------------------------------------------------------------------------- features


def _item(value: bool | None, first: float | None = None) -> dict[str, Any]:
    return {"value": value, "first_flag_ts": first if value else None}


def _pair_m5(snap: Mapping[str, Any]) -> tuple[float, float, float] | None:
    pair = snap.get("pair") or {}
    try:
        txns = pair["txns"]["m5"]
        return float(txns["buys"]), float(txns["sells"]), float((pair.get("volume") or {})["m5"])
    except (KeyError, TypeError, ValueError):
        return None


def _small_trades(m5: tuple[float, float, float]) -> bool | None:
    buys, sells, volume = m5
    return None if buys + sells <= 0 else volume / (buys + sells) < FEATURE_THRESHOLDS["small_trade_usd"]


def _ratio_paint(m5: tuple[float, float, float]) -> bool:
    buys, sells, _ = m5
    return buys > 0 if sells <= 0 else buys / sells >= FEATURE_THRESHOLDS["ratio_paint"]


def _run(points: Sequence[tuple[float, bool | None]]) -> tuple[bool | None, float | None]:
    """The newest value of time-ordered (visible_ts, flag) points, and when its trailing run of True began."""
    if not points or points[-1][1] is None:
        return None, None
    if not points[-1][1]:
        return False, None
    first = points[-1][0]
    for ts, flag in reversed(points):
        if not flag:
            break
        first = ts
    return True, first


def features_at(view: TapeView, t: float, *, evals: Iterable[Mapping[str, Any]] = (),
                context: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Every catalogue feature of the coin at ``t`` (see the module docstring). ``context`` carries the as-of
    market values the caller computed from other coins: ``heat_high`` (bool), ``breadth_m15`` (median 15-min
    return of coins aged 1-6 h), ``sol_usd_now`` and ``sol_usd_15m``."""
    out = {f: _item(None) for f in FEATURE_IDS}
    seen = view.first_seen_ts
    if seen is None or t < seen:
        return out
    age_s = t - seen
    speed = speed_of(view.created_ts, seen)
    out["fast"] = _item(None if speed == UNKNOWN else speed == "fast", seen)
    out["young"] = _item(age_s < FEATURE_THRESHOLDS["young_min"] * _MINUTE, seen)
    out["boost_window"] = _item(age_s < FEATURE_THRESHOLDS["boost_window_min"] * _MINUTE, seen)

    supply = _supply(view)
    if supply:
        limit = FEATURE_THRESHOLDS["low_mcap_usd"]
        out["low_mcap"] = _item(*_run([(c.ts + _MINUTE + view.l_obs, c.c * supply < limit) for c in _visible(view, t)]))

    snaps = sorted((s for s in view.state("snaps") if float(s["ts"]) <= t), key=lambda s: float(s["ts"]))
    m5 = [(float(s["ts"]), _pair_m5(s)) for s in snaps]
    out["small_trades"] = _item(*_run([(ts, None if v is None else _small_trades(v)) for ts, v in m5]))
    out["ratio_paint"] = _item(*_run([(ts, None if v is None else _ratio_paint(v)) for ts, v in m5]))

    ctx = context or {}
    if isinstance(ctx.get("heat_high"), bool):
        out["heat_high"] = _item(ctx["heat_high"])
    breadth = ctx.get("breadth_m15")
    if isinstance(breadth, (int, float)) and math.isfinite(breadth):
        out["breadth_low"] = _item(breadth <= FEATURE_THRESHOLDS["breadth_drop"])
    now, before = ctx.get("sol_usd_now"), ctx.get("sol_usd_15m")
    if isinstance(now, (int, float)) and isinstance(before, (int, float)) and before > 0 and now > 0:
        out["sol_drop"] = _item(now / before - 1.0 <= FEATURE_THRESHOLDS["sol_drop"])

    checked = [r for r in evals if float(r.get("ts", math.inf)) <= t and isinstance(r.get("safety"), Mapping)]
    if checked:
        for w in WARN_IDS:
            tag = f"[{w}]"
            hits = [float(r["ts"]) for r in checked if any(str(x).startswith(tag) for x in r["safety"].get("warnings")
                                                            or ())]
            out[f"warn:{w}"] = _item(bool(hits), min(hits) if hits else None)
    return out


# --------------------------------------------------------------------------- lessons


def nominated(types: Iterable[str]) -> tuple[str, ...]:
    """The catalogue features the given loss types nominate (catalogue order)."""
    wanted = {f for t in types for f in NOMINATES.get(t, ())}
    return tuple(f for f in FEATURE_IDS if f in wanted)


def check_lesson_rows(rows: Iterable[Mapping[str, Any]]) -> None:
    """Raise :class:`SplitLocked` unless every row is forward/paper or history of ``train`` (X5, A2)."""
    for row in rows:
        source = row.get("source")
        if source in stats.FORWARD_SOURCES:
            continue
        if source == "history" and row.get("split") in LESSON_SPLITS:
            continue
        raise SplitLocked(f"lessons are never mined from {source}/{row.get('split')} rows")


def _flag(row: Mapping[str, Any], feature: str) -> bool | None:
    value = (row.get("features") or {}).get(feature)
    if isinstance(value, Mapping):
        value = value.get("value")
    return value if isinstance(value, bool) else None


def _in_family(row: Mapping[str, Any], family: str) -> bool:
    return family == "all" or cell_family(row) == family


def _block_vv(units: Sequence[tuple[Mapping[str, Any], bool]]) -> float | None:
    """``mean(x | not f) - mean(x | all)`` within each stratum (speed x age band), weighted by stratum size."""
    strata: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for row, flag in units:
        strata[f"{row.get('speed')}|{row.get('age_band')}"].append((float(row["x"]), flag))
    total, weighted = 0, 0.0
    for items in strata.values():
        clean = [x for x, flag in items if not flag]
        if not clean:
            continue
        weighted += len(items) * (math.fsum(clean) / len(clean) - math.fsum(x for x, _ in items) / len(items))
        total += len(items)
    return weighted / total if total else None


def group_record(rows: Sequence[Mapping[str, Any]], feature: str, family: str, *, host: str = "R") -> dict[str, Any]:
    """One (feature, family) group on ``host`` rows: its day-block values, e-value and the opening-bar counts."""
    units = [(r, flag) for r in rows if r.get("host") == host and isinstance(r.get("x"), (int, float))
             and _in_family(r, family) and (flag := _flag(r, feature)) is not None]
    min_units = BLOCK_MIN_COINS if host in ("R", "W") else BLOCK_MIN_TRADES
    blocks = stats.day_blocks(units, day=lambda u: stats.row_day(u[0]), operator=lambda u: stats.row_operator(u[0]),
                              key=lambda u: stats.row_key(u[0]), min_units=min_units)
    points: list[tuple[str, float]] = []
    kept: list[tuple[Mapping[str, Any], bool]] = []
    for block in blocks:
        vv = _block_vv(block.units)
        if vv is not None:
            points.append((block.last_day, vv / 2.0))
            kept.extend(block.units)
    ys = [y for _, y in points]
    log_e = ev.log_e_up(ys) if ys else 0.0
    half = len(ys) // 2
    halves_ok = half >= 1 and all(math.fsum(part) > 0 for part in (ys[:half], ys[half:]))
    losers = [r for r, flag in kept if flag and float(r["x"]) < 0]
    bad_known = [(bool(r.get("bad")), flag) for r, flag in kept if isinstance(r.get("bad"), bool)]
    base = stats.mean(1.0 if b else 0.0 for b, _ in bad_known)
    precision = stats.mean(1.0 if b else 0.0 for b, flag in bad_known if flag)
    winners = [flag for r, flag in kept if float(r["x"]) > 0]
    return {
        "feature": feature, "family": family, "host": host, "blocks": len(ys), "n": len(kept),
        "vv_pp": None if not ys else 200.0 * math.fsum(ys) / len(ys), "log_e": log_e, "e": math.exp(min(log_e, 700.0)),
        "halves_same_sign": halves_ok, "flagged_losers": len(losers),
        "operators": len({stats.row_operator(r) for r in losers}), "days": len({stats.row_day(r) for r in losers}),
        "precision": precision, "base_rate": base,
        "lift": precision / base if precision is not None and base else None,
        "winners_share": stats.mean(1.0 if f else 0.0 for f in winners),
        "mined_from": sorted({str(r.get("split") or r.get("source")) for r, _ in kept}),
    }


def lesson_id(feature: str, family: str, host: str, taxonomy_ver: str = TAXONOMY_VERSION) -> str:
    """One id per group and taxonomy version: a group opens at most once per version."""
    return stats.hash_key(f"lesson|{taxonomy_ver}|{host}|{feature}|{family}")[:16]


def weekly_lessons(rows: Sequence[Mapping[str, Any]], *, features: Sequence[str], opened: Iterable[str] = (),
                   host: str = "R", nominated_by: Mapping[str, Sequence[str]] | None = None,
                   taxonomy_ver: str = TAXONOMY_VERSION, q: float = LESSON_Q,
                   cap: int = LESSON_WEEKLY_CAP) -> dict[str, Any]:
    """One weekly lesson run (see the module docstring). ``opened``: lesson ids already receipted. Returns
    ``{"examined": K, "selected": [...], "opened": [outbox payloads]}``; it writes nothing."""
    rows = list(rows)
    check_lesson_rows(rows)
    already = set(opened)
    records = {(f, c): group_record(rows, f, c, host=host) for f in features for c in CELL_FAMILIES}
    examined = {g: r for g, r in records.items() if r["blocks"] > 0}
    selected = stats.ebh({g: r["e"] for g, r in examined.items()}, q)
    drafts: list[dict[str, Any]] = []
    for group in selected:
        feature, family = group
        r = records[group]
        lid = lesson_id(feature, family, host, taxonomy_ver)
        min_days = FOLKLORE_MIN_DAYS if feature in FOLKLORE_FEATURES else LESSON_MIN_DAYS
        if lid in already or not r["halves_same_sign"] or r["flagged_losers"] < LESSON_MIN_FLAGGED_LOSERS \
                or r["operators"] < LESSON_MIN_OPERATORS or r["days"] < min_days:
            continue
        evidence = {k: r[k] for k in ("blocks", "n", "vv_pp", "log_e", "flagged_losers", "operators", "days",
                                      "precision", "base_rate", "lift", "winners_share", "mined_from")}
        evidence.update(selected_biased_upward=True, examined_groups=len(examined),
                        power_plan_pp=None if r["vv_pp"] is None else r["vv_pp"] / 2.0,
                        nominated_by=sorted((nominated_by or {}).get(feature, ())),
                        test_on="forward coins created after this receipt")
        drafts.append({"lesson_id": lid, "group": {"feature": feature, "family": family, "host": host},
                       "evidence": evidence, "taxonomy_ver": taxonomy_ver})
        if len(drafts) >= cap:
            break
    return {"examined": len(examined), "selected": [{"feature": f, "family": c} for f, c in selected],
            "opened": drafts}
