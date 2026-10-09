"""Loss types (docs/EXPERIENCE.md §6.3): fixed, versioned and DESCRIPTIVE. Pure.

A loss type says how a trade ended; it is never, by itself, evidence that anything was a mistake (A1). Each type
that random entries can show also gets a LUCK base rate - the R-host rate in the same cell and ISO week - so the owner
sees "rug missed 4 (random entries in the same situations: 3.8 expected)", never a "Mistakes" list. Only the weekly
feature test (``features.weekly_lessons``) can turn a gap into a lesson; only a ``pipeline_fault`` is acted on after
a single instance (it is a bug).

:func:`classify` takes a post-mortem's inputs (all optional; a type whose inputs are missing does not fire):

* ``x``, ``g``, ``cost`` (fractions), ``parts`` (attribution), ``host``;
* ``t_in``, ``t_out``, ``exit_reason``, ``crash50``, ``t_crash``, ``mfe``, ``stop_loss_pct``;
* ``size_usd``, ``dollar_pnl``, ``equity_usd`` (equity at entry);
* ``rebound`` (:func:`rebound_after`), ``regime_pct`` (the regime score's as-of percentile at t_in), ``hour_gap``
  (same-hour R trades minus their cells' as-of means), ``cost_model`` (the modelled cost fraction);
* ``faults`` (named pipeline faults: replay disagreement, fill outside the quote, risk-limit breach, lookahead trip,
  price or reserve anomaly), ``candle_lag_s``, ``fill_quote_err``; ``vetoed`` and ``x_cf`` for vetoed signals.

Magnitudes are signed so that MORE NEGATIVE = COSTLIER (pp of the trade as fractions); the primary type is
``pipeline_fault`` whenever it fires, else the most negative magnitude, ties in table order. Every flag is kept.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from nightcrawler.experience import stats
from nightcrawler.experience.constants import BASE_RATE_TYPES, LOSS_THRESHOLDS, LOSS_TYPES
from nightcrawler.experience.texts import LOSS_NAMES, say
from nightcrawler.learn.labels import Bar, BarSeries

__all__ = ["faults_of", "classify", "primary", "rebound_after", "rate_key", "luck_rates", "week_summary"]

_TH = LOSS_THRESHOLDS


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def faults_of(trade: Mapping[str, Any]) -> list[str]:
    """The pipeline faults of a trade: the named ones plus stale candles and fill-vs-quote errors."""
    found = [str(f) for f in trade.get("faults") or ()]
    lag = _num(trade.get("candle_lag_s"))
    if lag is not None and lag > _TH["candle_max_lag_s"]:
        found.append("stale_candles")
    err = _num(trade.get("fill_quote_err"))
    if err is not None and abs(err) > _TH["fill_quote_max_err"]:
        found.append("fill_vs_quote")
    return found


def _magnitudes(trade: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    raw_parts = trade.get("parts")
    parts: Mapping[str, Any] = raw_parts if isinstance(raw_parts, Mapping) else {}
    x, g = _num(trade.get("x")), _num(trade.get("g"))
    t_in, t_out, t_crash = _num(trade.get("t_in")), _num(trade.get("t_out")), _num(trade.get("t_crash"))
    faults = faults_of(trade)
    if faults:
        out["pipeline_fault"] = {"magnitude": None, "faults": faults}
    crashed_in_hold = t_in is not None and t_out is not None and t_crash is not None and t_in < t_crash <= t_out
    if trade.get("crash50") is True and crashed_in_hold:
        stop = _num(trade.get("stop_loss_pct")) or 0.0
        out["rug_missed"] = {"magnitude": None if g is None else g + stop}
    regime, gap = _num(trade.get("regime_pct")), _num(trade.get("hour_gap"))
    if x is not None and x < 0 and regime is not None and gap is not None and regime <= _TH["regime_decile"] \
            and gap <= _TH["regime_hour_gap"]:
        out["regime"] = {"magnitude": _num(parts.get("market")) if parts.get("market") is not None else gap}
    pnl, equity, size = _num(trade.get("dollar_pnl")), _num(trade.get("equity_usd")), _num(trade.get("size_usd"))
    if pnl is not None and equity and size and -pnl > _TH["oversize_equity_share"] * equity:
        out["oversize"] = {"magnitude": (pnl + _TH["oversize_equity_share"] * equity) / size}
    delay = _num(parts.get("delay"))
    if delay is not None and delay <= _TH["late_entry_delay"]:
        out["late_entry"] = {"magnitude": delay}
    selection = _num(parts.get("selection"))
    if selection is not None:
        entry = selection + (0.0 if trade.get("host") == "R" else (_num(parts.get("timing")) or 0.0))
        if entry <= _TH["bad_entry"]:
            out["bad_entry"] = {"magnitude": entry}
    rebound = _num(trade.get("rebound"))
    if rebound is not None and rebound >= _TH["early_exit_rebound"]:
        out["early_exit"] = {"magnitude": -min(rebound, _TH["early_exit_cap"]),
                             "stop_regret": str(trade.get("exit_reason") or "").startswith("stop")}
    mfe = _num(trade.get("mfe"))
    if mfe is not None and x is not None and mfe >= _TH["late_exit_mfe"] and x <= 0:
        out["late_exit"] = {"magnitude": -(mfe - x)}
    cost, model = _num(trade.get("cost")), _num(trade.get("cost_model"))
    if (g is not None and x is not None and g >= 0 > x) or (cost is not None and model
                                                           and cost > _TH["cost_eaten_model_x"] * model):
        costs = _num(parts.get("costs"))
        out["cost_eaten"] = {"magnitude": costs if costs is not None else (None if cost is None else -cost)}
    x_cf = _num(trade.get("x_cf"))
    if trade.get("vetoed") and x_cf is not None and x_cf > _TH["missed_winner_x"]:
        out["missed_winner"] = {"magnitude": -x_cf}
    return out


def classify(trade: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every loss type that fires, in table order, as ``{type, magnitude, ...}``; ``variance`` when none does."""
    found = _magnitudes(trade)
    flags = [{"type": t, **found[t]} for t in LOSS_TYPES if t in found]
    return flags or [{"type": "variance", "magnitude": None}]


def primary(flags: Sequence[Mapping[str, Any]]) -> str:
    """``pipeline_fault`` whenever present; else the most negative magnitude, ties in table order."""
    names = [str(f["type"]) for f in flags]
    if "pipeline_fault" in names:
        return "pipeline_fault"
    ranked = sorted(((f["magnitude"], LOSS_TYPES.index(f["type"])) for f in flags if f.get("magnitude") is not None))
    if ranked:
        return LOSS_TYPES[ranked[0][1]]
    return names[0] if names else "variance"


def rebound_after(bars: Sequence[Bar], t_out: float, exit_price: float | None = None, *,
                  window_s: float = LOSS_THRESHOLDS["early_exit_window_s"]) -> float | None:
    """The best close within ``window_s`` after the exit over the exit price, minus 1 (None when not covered)."""
    series = BarSeries(bars)
    price = exit_price if exit_price is not None else series.close_at(t_out)
    if price is None or price <= 0 or series.end < t_out + window_s:
        return None
    closes = [float(b.c) for b, closed in zip(series.bars, series.closes_at, strict=True)
              if t_out < closed <= t_out + window_s]
    return max(closes) / price - 1.0 if closes else 0.0


def rate_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    """(speed, age band, market-cap tier, ISO week): where luck base rates are compared."""
    return (str(row.get("speed")), str(row.get("age_band")), str(row.get("mcap_tier")),
            stats.iso_week(stats.row_day(row)))


def _primary_of(row: Mapping[str, Any]) -> str:
    return str(row.get("primary") or primary(classify(row)))


def luck_rates(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str, str, str], dict[str, float]]:
    """``{rate_key: {type: share}}`` of the primary types of RANDOM entries (host R only; other rows are ignored),
    for the types random entries can show."""
    counts: dict[tuple[str, str, str, str], Counter[str]] = defaultdict(Counter)
    for row in rows:
        if row.get("host") == "R":
            counts[rate_key(row)][_primary_of(row)] += 1
    return {key: {t: c[t] / sum(c.values()) for t in BASE_RATE_TYPES} for key, c in counts.items()}


def week_summary(pm_rows: Sequence[Mapping[str, Any]], rates: Mapping[tuple[str, str, str, str], Mapping[str, float]],
                 top: int = 3) -> list[dict[str, Any]]:
    """The week's primary types, most frequent first: ``{type, n, expected, text}`` where ``expected`` sums the luck
    rate of the type over each trade's cell and week (None for a type random entries cannot show)."""
    counts = Counter(_primary_of(r) for r in pm_rows)
    ranked = sorted(counts, key=lambda t: (-counts[t], LOSS_TYPES.index(t) if t in LOSS_TYPES else len(LOSS_TYPES)))
    items = []
    for i, t in enumerate(ranked[:top]):
        known = [rates[k][t] for k in map(rate_key, pm_rows) if k in rates and t in rates[k]]
        expected = math.fsum(known) if known else None
        text = say("loss_first" if i == 0 else "loss_next", name_txt=LOSS_NAMES.get(t, "other"), n=counts[t],
                   e_x=expected)
        items.append({"type": t, "n": counts[t], "expected": expected, "text": text})
    return items
