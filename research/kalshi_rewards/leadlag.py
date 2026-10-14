"""Does Pyth move before Kalshi's FX market makers reprice? The lead-lag analyzer of PREREG.md (read it first).

Research only: it reads the public Kalshi recorder's files (Kalshi LIP books and book calls, liquidity programs,
market rows, and the Pyth prices the recorder received) through :mod:`nightcrawler.lip_feed`. No network, no key,
no order path.

Every definition is PREREG.md's (sections 2 to 6), fixed before this file existed:

* a **Pyth event** is the first update whose log move from the price 1 s earlier (D) reaches k bp, then nothing on
  that symbol for 5 s (R); our receive time is the event time (the free 1 s series: label + 1 s);
* the **response** is the first later Kalshi poll whose mid differs from the baseline (the newest poll answered by
  t - D), within H = 10 s: ``same``, ``opposite`` or ``none``;
* the **warning** is interval-censored: ``W_lo = requested_at(last stale poll) - t``, ``W_hi = received_at(response
  poll) - t``; ``warn05`` is ``W_lo >= 0.5 s``;
* **S** = the share of ``same`` events with ``warn05``, pooled over the five FX pairs, with a cluster bootstrap over
  market-windows (B = 2,000, seed 20261014); the primary cell is FX, k = 1 bp;
* the **decision** (TEST only, primary cell): enough data (300 same events in 100 windows), Kalshi follows Pyth
  (lower bound of P_same >= 0.55), then CONTINUE (lower bound of S >= 0.50), STOP (upper bound < 0.25 on a source
  whose median update interval is at most 250 ms), else MARGINAL.

Usage::

    python3 research/kalshi_rewards/leadlag.py days --recorder-dir DIR --source pyth_hermes
    python3 research/kalshi_rewards/leadlag.py run --recorder-dir DIR --source pyth_hermes --phase TRAIN [--out F]
    python3 research/kalshi_rewards/leadlag.py run --recorder-dir DIR --source kalshi_live_data --start ISO --end ISO

``--phase TEST`` runs only with ``leadlag/FREEZE.json`` (PREREG.md section 5) and only once.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import itertools
import json
import math
import random
import statistics
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from nightcrawler.lip_feed import (
    ALL_LANES,
    FX,
    FX_SERIES,
    LIP_LANES,
    METAL_GAS,
    SERIES,
    SYMBOL_SERIES,
    MarketFacts,
    book_from_record,
    call_from_record,
    live_points_from_record,
    market_rows_from_record,
    parse_pyth,
    programs_from_record,
    read_records,
    series_of,
)

HERE = Path(__file__).resolve().parent
PREREG = HERE / "PREREG.md"
PREREG_SHA = HERE / "PREREG.sha256"
FREEZE = HERE / "leadlag" / "FREEZE.json"
TEST_RESULT = HERE / "leadlag" / "TEST_RESULT.json"

LOOKBACK_S = 1.0  # D
REFRACTORY_S = 5.0  # R
HORIZON_S = 10.0  # H
WARN_S = 0.5
EDGE_START_S = 30.0
EDGE_END_S = 60.0
MAX_POLL_GAP_S = 2.5
MID_LOW, MID_HIGH = 5.0, 95.0  # cents
K_GRID = {FX: (0.5, 1.0, 2.0), METAL_GAS: (1.0, 2.0, 5.0)}
PRIMARY_K = 1.0
BOOTSTRAP_B = 2000
SEED = 20261014
MIN_SAME, MIN_WINDOWS = 300, 100
P_SAME_FLOOR = 0.55
CONTINUE_LOW = 0.50
STOP_HIGH = 0.25
FAST_SOURCE_MS = 250.0
FX_DAY_MINUTES = 12 * 60
SPLIT = {"TRAIN": (0, 2), "VAL": (2, 4), "TEST": (4, 8)}
SOURCES = ("pyth_hermes", "kalshi_pyth_value", "pyth_pro", "kalshi_live_data", "pyth")
LIVE_SOURCE = "kalshi_live_data"
QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90)
HIST_EDGES = (-math.inf, -1.0, -0.5, 0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, math.inf)


# ---------------------------------------------------------------------- New York time (no tz database needed)
def _second_sunday_march(year: int) -> datetime:
    first = datetime(year, 3, 1, tzinfo=UTC)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7)


def _first_sunday_november(year: int) -> datetime:
    first = datetime(year, 11, 1, tzinfo=UTC)
    return first + timedelta(days=(6 - first.weekday()) % 7)


def new_york(at: float) -> datetime:
    """Eastern time (US rules since 2007: daylight time from 2:00 am on March's second Sunday to 2:00 am on
    November's first Sunday) as a naive datetime."""
    moment = datetime.fromtimestamp(at, UTC)
    start = _second_sunday_march(moment.year) + timedelta(hours=7)  # 2:00 EST
    end = _first_sunday_november(moment.year) + timedelta(hours=6)  # 2:00 EDT
    offset = -4 if start <= moment < end else -5
    return (moment + timedelta(hours=offset)).replace(tzinfo=None)


def maintenance(at: float) -> bool:
    """Kalshi's weekly pause: Thursday 3:00 to 5:00 am ET."""
    local = new_york(at)
    return local.weekday() == 3 and 3 <= local.hour < 5


def fx_hours(at: float) -> bool:
    """Pyth's FX schedule (Sunday 17:00 to Friday 17:00 ET), minus Kalshi's Thursday pause."""
    local = new_york(at)
    weekday, hour = local.weekday(), local.hour
    if weekday == 5 or (weekday == 4 and hour >= 17) or (weekday == 6 and hour < 17):
        return False
    return not maintenance(at)


# ---------------------------------------------------------------------- the data
@dataclass
class Polls:
    """One market's polls: request and receive times and the mid (cents; None with an empty side)."""

    requested: list[float] = field(default_factory=list)
    received: list[float] = field(default_factory=list)
    mid: list[float | None] = field(default_factory=list)

    def add(self, requested: float, received: float, mid: float | None) -> None:
        if self.received and received < self.received[-1]:
            return
        self.requested.append(requested)
        self.received.append(received)
        self.mid.append(mid)


@dataclass(frozen=True)
class MarketWindow:
    ticker: str
    series: str
    start: float
    end: float


@dataclass
class Data:
    windows: dict[str, list[MarketWindow]] = field(default_factory=dict)  # series -> windows, by start
    polls: dict[str, Polls] = field(default_factory=dict)  # ticker -> polls
    ticks: dict[str, dict[str, list[tuple[float, float]]]] = field(default_factory=dict)  # source -> symbol -> ticks

    def window_at(self, series: str, at: float) -> MarketWindow | None:
        for window in self.windows.get(series, []):
            if window.start <= at < window.end:
                return window
        return None


def load(records: Iterable[Mapping[str, Any]]) -> Data:
    """The analysis inputs from recorder records in ``(at, seq)`` order."""
    data = Data()
    rows = list(records)
    calls_seen = any(row.get("kind") == "book_call" for row in rows)
    latest: dict[str, Any] = {}
    programs: dict[str, MarketWindow] = {}
    facts: dict[str, MarketFacts] = {}
    for record in rows:
        kind = record.get("kind")
        if kind == "book":
            book = book_from_record(record)
            if book is None or series_of(book.ticker) is None:
                continue
            latest[book.ticker] = book
            if not calls_seen:
                data.polls.setdefault(book.ticker, Polls()).add(book.requested_at, book.received_at, book.mid)
            continue
        if kind == "book_call":
            call = call_from_record(record)
            if call is None or not call.ok:
                continue
            for ticker in call.changed + call.unchanged:
                snap = latest.get(ticker)
                if snap is not None:
                    data.polls.setdefault(ticker, Polls()).add(call.requested_at, call.received_at, snap.mid)
            continue
        for program in programs_from_record(record):
            series = series_of(program.ticker)
            if series is not None:
                programs[program.ticker] = MarketWindow(program.ticker, series, program.start, program.end)
        for ticker, row in market_rows_from_record(record):
            if series_of(ticker) is not None:
                facts.setdefault(ticker, MarketFacts(ticker)).merge(row)
        for tick in parse_pyth(record):
            data.ticks.setdefault(tick.source, {}).setdefault(tick.symbol, []).append((tick.at, tick.price))
        for point in live_points_from_record(record):
            symbol = SERIES[point.series].pyth_symbol
            if symbol is not None:
                data.ticks.setdefault(LIVE_SOURCE, {}).setdefault(symbol, []).append(
                    (point.label + 1.0, point.value))
    for ticker, fact in facts.items():
        series = series_of(ticker)
        if ticker not in programs and series and fact.open_ts is not None and fact.close_ts is not None:
            programs[ticker] = MarketWindow(ticker, series, fact.open_ts, fact.close_ts)
    for window in programs.values():
        data.windows.setdefault(window.series, []).append(window)
    for windows in data.windows.values():
        windows.sort(key=lambda item: item.start)
    for symbols in data.ticks.values():
        for symbol, ticks in symbols.items():
            ticks.sort()
            clean: list[tuple[float, float]] = []
            for at, price in ticks:
                if clean and (at <= clean[-1][0] or (at == clean[-1][0] and price == clean[-1][1])):
                    continue  # duplicates and out-of-order updates are dropped
                clean.append((at, price))
            symbols[symbol] = clean
    return data


# ---------------------------------------------------------------------- events and responses
@dataclass(frozen=True)
class Event:
    series: str
    symbol: str
    at: float
    direction: int  # +1 up, -1 down
    move_bps: float
    price: float


def pyth_events(ticks: Sequence[tuple[float, float]], series: str, symbol: str, k: float,
                lookback: float = LOOKBACK_S, refractory: float = REFRACTORY_S) -> list[Event]:
    """PREREG section 3: the first update whose move from the price ``lookback`` earlier reaches ``k`` bp."""
    times = [at for at, _ in ticks]
    out: list[Event] = []
    quiet_until = -math.inf
    for index, (at, price) in enumerate(ticks):
        if at < quiet_until or price <= 0:
            continue
        ref = bisect.bisect_right(times, at - lookback, 0, index) - 1
        if ref < 0 or ticks[ref][1] <= 0:
            continue
        move = 1e4 * math.log(price / ticks[ref][1])
        if abs(move) >= k:
            out.append(Event(series, symbol, at, 1 if move > 0 else -1, move, price))
            quiet_until = at + refractory
    return out


def measure(event: Event, window: MarketWindow | None, polls: Polls | None, ticks: Sequence[tuple[float, float]],
            times: Sequence[float] | None = None, horizon: float = HORIZON_S,
            lookback: float = LOOKBACK_S) -> dict[str, Any]:
    """One event's response (PREREG section 3): its class, warning bounds, or the reason it was excluded.
    ``times`` are the ticks' times (pass them once per symbol; computed when absent)."""
    row: dict[str, Any] = {"series": event.series, "at": event.at, "direction": event.direction,
                           "move_bps": round(event.move_bps, 4), "hour": datetime.fromtimestamp(event.at, UTC).hour}
    t = event.at
    if window is None:
        return {**row, "excluded": "no_window"}
    row["window"] = window.ticker
    if t < window.start + EDGE_START_S or t > window.end - EDGE_END_S:
        return {**row, "excluded": "window_edge"}
    if maintenance(t):
        return {**row, "excluded": "maintenance"}
    if polls is None or not polls.received:
        return {**row, "excluded": "no_baseline"}
    base = bisect.bisect_right(polls.received, t - lookback) - 1
    if base < 0 or polls.received[base] < window.start:
        return {**row, "excluded": "no_baseline"}
    m0 = polls.mid[base]
    if m0 is None or not MID_LOW <= m0 <= MID_HIGH:
        return {**row, "excluded": "baseline_extreme"}
    row["m0"] = m0
    # coverage: no two consecutive polls more than 2.5 s apart in [t - D - 2.5, t + H], and a poll past t + H
    low = bisect.bisect_left(polls.received, t - lookback - MAX_POLL_GAP_S)
    span = [polls.received[i] for i in range(max(0, low - 1), len(polls.received))
            if polls.received[i] <= t + horizon + MAX_POLL_GAP_S]
    if not span or span[-1] < t + horizon or any(b - a > MAX_POLL_GAP_S for a, b in itertools.pairwise(span)):
        return {**row, "excluded": "coverage"}
    last_stale = base
    for index in range(base + 1, len(polls.received)):
        if polls.requested[index] > t + horizon:
            break
        mid = polls.mid[index]
        if mid is None:
            return {**row, "excluded": "one_sided_book"}
        if mid == m0:
            last_stale = index
            continue
        same = (mid - m0) * event.direction > 0
        w_lo = polls.requested[last_stale] - t
        w_hi = polls.received[index] - t
        stamps = times if times is not None else [at for at, _ in ticks]
        at_response = bisect.bisect_right(stamps, polls.received[index]) - 1
        moved = (1e4 * math.log(ticks[at_response][1] / event.price) * event.direction
                 if at_response >= 0 and ticks[at_response][1] > 0 else None)
        return {**row, "excluded": None, "response": "same" if same else "opposite", "w_lo": round(w_lo, 4),
                "w_hi": round(w_hi, 4), "warn05": w_lo >= WARN_S, "kalshi_first": w_hi <= 0,
                "mid_move": mid - m0, "pyth_move_at_response_bps": None if moved is None else round(moved, 4)}
    return {**row, "excluded": None, "response": "none"}


def measure_all(data: Data, source: str, k: float, family: str) -> list[dict[str, Any]]:
    out = []
    symbols = data.ticks.get(source, {})
    for series, info in SERIES.items():
        if info.group != family or info.pyth_symbol is None:
            continue
        ticks = symbols.get(info.pyth_symbol, [])
        times = [at for at, _ in ticks]
        for event in pyth_events(ticks, series, info.pyth_symbol, k):
            window = data.window_at(series, event.at)
            polls = data.polls.get(window.ticker) if window is not None else None
            out.append(measure(event, window, polls, ticks, times))
    return out


# ---------------------------------------------------------------------- statistics
def _quantiles(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {f"p{int(q * 100)}": None for q in QUANTILES}
    ordered = sorted(values)
    return {f"p{int(q * 100)}": round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 4) for q in QUANTILES}


def _histogram(values: Sequence[float]) -> list[dict[str, Any]]:
    out = []
    for low, high in itertools.pairwise(HIST_EDGES):
        out.append({"from": None if math.isinf(low) else low, "to": None if math.isinf(high) else high,
                    "n": sum(1 for value in values if low <= value < high)})
    return out


def cluster_bootstrap(rows: Sequence[Mapping[str, Any]], numerator: str, denominator: str,
                      b: int = BOOTSTRAP_B, seed: int = SEED) -> tuple[float | None, float | None, float | None]:
    """``(estimate, 2.5 %, 97.5 %)`` of ``sum(numerator) / sum(denominator)`` resampling market-windows."""
    clusters: dict[str, list[float]] = {}
    for row in rows:
        acc = clusters.setdefault(str(row.get("window")), [0.0, 0.0])
        acc[0] += float(row.get(numerator) or 0.0)
        acc[1] += float(row.get(denominator) or 0.0)
    items = list(clusters.values())
    total_num, total_den = sum(item[0] for item in items), sum(item[1] for item in items)
    if total_den <= 0:
        return None, None, None
    rng = random.Random(seed)
    draws = []
    for _ in range(b):
        num = den = 0.0
        for _ in range(len(items)):
            pick = items[rng.randrange(len(items))]
            num += pick[0]
            den += pick[1]
        if den > 0:
            draws.append(num / den)
    draws.sort()
    if not draws:
        return total_num / total_den, None, None
    return (total_num / total_den, draws[int(0.025 * (len(draws) - 1))], draws[math.ceil(0.975 * (len(draws) - 1))])


def summarize(rows: Sequence[Mapping[str, Any]], *, bootstrap: bool = True) -> dict[str, Any]:
    """Every reading PREREG section 3 lists for one cell."""
    excluded: dict[str, int] = {}
    for row in rows:
        if row.get("excluded"):
            excluded[str(row["excluded"])] = excluded.get(str(row["excluded"]), 0) + 1
    kept = [row for row in rows if not row.get("excluded")]
    same = [row for row in kept if row.get("response") == "same"]
    opposite = [row for row in kept if row.get("response") == "opposite"]
    marked = [{"window": row.get("window"), "same": 1.0 if row.get("response") == "same" else 0.0,
               "decided": 1.0 if row.get("response") in ("same", "opposite") else 0.0,
               "warn": 1.0 if row.get("warn05") else 0.0} for row in kept]
    s_est = s_lo = s_hi = p_est = p_lo = p_hi = None
    if bootstrap:
        s_est, s_lo, s_hi = cluster_bootstrap([row for row in marked if row["same"]], "warn", "same")
        p_est, p_lo, p_hi = cluster_bootstrap(marked, "same", "decided")
    elif same:
        s_est = sum(1 for row in same if row.get("warn05")) / len(same)
    w_lo = [float(row["w_lo"]) for row in same]
    w_hi = [float(row["w_hi"]) for row in same]
    moves = [abs(float(row["move_bps"])) for row in kept]
    responses = [float(row["pyth_move_at_response_bps"]) for row in same
                 if row.get("pyth_move_at_response_bps") is not None]
    return {
        "events": len(rows), "kept": len(kept), "excluded": dict(sorted(excluded.items())),
        "same": len(same), "opposite": len(opposite), "none": len(kept) - len(same) - len(opposite),
        "windows_with_same": len({row.get("window") for row in same}),
        "P_same": _r(p_est), "P_same_range95": [_r(p_lo), _r(p_hi)],
        "S": _r(s_est), "S_range95": [_r(s_lo), _r(s_hi)],
        "kalshi_first_share": _r(sum(1 for row in same if row.get("kalshi_first")) / len(same) if same else None),
        "w_lo": _quantiles(w_lo), "w_hi": _quantiles(w_hi), "w_lo_histogram": _histogram(w_lo),
        "move_bps": _quantiles(moves), "pyth_move_at_response_bps": _quantiles(responses),
    }


def _r(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def source_intervals(data: Data, source: str, start: float = -math.inf, end: float = math.inf) -> dict[str, Any]:
    """Each symbol's update interval (ms): median and 90 %, inside FX hours for FX symbols."""
    out: dict[str, Any] = {}
    for symbol, ticks in sorted(data.ticks.get(source, {}).items()):
        series = SYMBOL_SERIES.get(symbol)
        fx = series is not None and SERIES[series].group == FX
        gaps = [1000.0 * (b[0] - a[0]) for a, b in itertools.pairwise(ticks)
                if start <= a[0] <= end and (not fx or (fx_hours(a[0]) and fx_hours(b[0]))) and b[0] - a[0] < 60]
        out[symbol] = {"updates": len(ticks), "median_ms": _r(statistics.median(gaps) if gaps else None, 1),
                       "p90_ms": _r(sorted(gaps)[int(0.9 * (len(gaps) - 1))] if gaps else None, 1)}
    return out


def decide(primary: Mapping[str, Any], intervals: Mapping[str, Any], source: str) -> dict[str, Any]:
    """PREREG section 6 on the primary cell."""
    fx_medians = [info["median_ms"] for symbol, info in intervals.items()
                  if SYMBOL_SERIES.get(symbol) in FX_SERIES and info.get("median_ms") is not None]
    fast = bool(fx_medians) and statistics.median(fx_medians) <= FAST_SOURCE_MS
    base = {"source": source, "source_median_ms": _r(statistics.median(fx_medians), 1) if fx_medians else None,
            "source_can_stop": fast and source != LIVE_SOURCE, "source_can_continue": source != LIVE_SOURCE}
    if source == LIVE_SOURCE:
        return {**base, "verdict": "DESCRIPTIVE", "why": "the free 1 s series decides nothing (PREREG section 2)"}
    if primary["same"] < MIN_SAME or primary["windows_with_same"] < MIN_WINDOWS:
        return {**base, "verdict": "INSUFFICIENT",
                "why": f"{primary['same']} same events in {primary['windows_with_same']} windows; need "
                       f"{MIN_SAME} in {MIN_WINDOWS}: extend by whole FX days"}
    p_low = primary["P_same_range95"][0]
    if p_low is None or p_low < P_SAME_FLOOR:
        return {**base, "verdict": "INCONCLUSIVE", "why": f"P_same lower bound {p_low} < {P_SAME_FLOOR}"}
    s_low, s_high = primary["S_range95"]
    if s_low is not None and s_low >= CONTINUE_LOW:
        return {**base, "verdict": "CONTINUE",
                "why": f"S lower bound {s_low} >= {CONTINUE_LOW}: a necessary condition only; next, the practice "
                       "desk's Pyth policy against the playbook's go/no-go bar"}
    if s_high is not None and s_high < STOP_HIGH:
        if fast:
            return {**base, "verdict": "STOP", "why": f"S upper bound {s_high} < {STOP_HIGH}: 0.5 s warning is rare"}
        return {**base, "verdict": "STOP_THIS_SOURCE_ONLY",
                "why": f"S upper bound {s_high} < {STOP_HIGH}, but the source is slower than {FAST_SOURCE_MS} ms"}
    return {**base, "verdict": "MARGINAL", "why": f"S range {s_low}..{s_high} meets neither bar"}


# ---------------------------------------------------------------------- days and the split
def fx_days(data: Data, source: str) -> list[dict[str, Any]]:
    """PREREG section 5: UTC days with at least 12 hours of FX trading minutes covered by the source on all five FX
    symbols and by Kalshi polls of all five FX markets."""
    minutes: dict[str, set[int]] = {}
    ticks = data.ticks.get(source, {})
    for series in FX_SERIES:
        symbol = SERIES[series].pyth_symbol
        minutes[f"pyth:{series}"] = {int(at // 60) for at, _ in ticks.get(symbol or "", [])}
        polled: set[int] = set()
        for window in data.windows.get(series, []):
            polls = data.polls.get(window.ticker)
            if polls is not None:
                polled |= {int(at // 60) for at in polls.received if window.start <= at < window.end}
        minutes[f"kalshi:{series}"] = polled
    sets = list(minutes.values())
    covered = set.intersection(*sets) if sets and all(sets) else set()
    by_day: dict[str, int] = {}
    for minute in covered:
        if fx_hours(minute * 60.0 + 30.0):
            day = datetime.fromtimestamp(minute * 60, UTC).date().isoformat()
            by_day[day] = by_day.get(day, 0) + 1
    return [{"day": day, "fx_minutes": count, "fx_day": count >= FX_DAY_MINUTES}
            for day, count in sorted(by_day.items())]


def split(days: Sequence[Mapping[str, Any]], test_days: int = 4) -> dict[str, list[str]]:
    """TRAIN = the first 2 FX days, VAL = the next 2, TEST = the next ``test_days`` (4, or more when TEST was
    extended on counts alone)."""
    good = [str(row["day"]) for row in days if row["fx_day"]]
    bounds = {**SPLIT, "TEST": (SPLIT["TEST"][0], SPLIT["TEST"][0] + max(4, test_days))}
    return {phase: good[low:high] for phase, (low, high) in bounds.items()}


def frozen_days(freeze: Path = FREEZE) -> list[str]:
    if not freeze.exists():
        return []
    raw = json.loads(freeze.read_text(encoding="utf-8"))
    return [str(day) for day in raw.get("test_days") or []]


def _day_bounds(day: str) -> tuple[float, float]:
    start = datetime.fromisoformat(day).replace(tzinfo=UTC).timestamp()
    return start, start + 86_400.0


# ---------------------------------------------------------------------- the freeze (TEST is one look)
def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prereg_hash_ok() -> bool:
    recorded = PREREG_SHA.read_text(encoding="utf-8").split()[2] if PREREG_SHA.exists() else ""
    return bool(recorded) and _sha(PREREG) == recorded


def check_freeze(source: str, test_days: Sequence[str], freeze: Path = FREEZE, result: Path = TEST_RESULT) -> list[str]:
    """Why TEST may not run (empty: it may)."""
    problems = []
    if result.exists():
        problems.append(f"{result.name} exists: TEST was already looked at once")
    if not prereg_hash_ok():
        problems.append("PREREG.md does not match PREREG.sha256")
    if not freeze.exists():
        return [*problems, f"{freeze} is missing"]
    raw = json.loads(freeze.read_text(encoding="utf-8"))
    if raw.get("prereg_sha256") != _sha(PREREG):
        problems.append("FREEZE.json names another PREREG.md")
    if raw.get("leadlag_sha256") != _sha(Path(__file__).resolve()):
        problems.append("leadlag.py changed since the freeze")
    if raw.get("source") != source:
        problems.append(f"FREEZE.json names source {raw.get('source')!r}")
    frozen = [str(day) for day in raw.get("test_days") or []]
    if frozen != list(test_days) or len(frozen) < 4:
        problems.append(f"FREEZE.json TEST days {frozen} are not the data's TEST days {list(test_days)}")
    return problems


# ---------------------------------------------------------------------- the report
def analyze(data: Data, source: str, start: float, end: float, *, bootstrap: bool = True) -> dict[str, Any]:
    """Every cell of the grid, the per-series and per-hour tables, the source's update intervals and the decision
    rule applied to the primary cell."""
    cells: dict[str, Any] = {}
    primary: dict[str, Any] | None = None
    tables: dict[str, Any] = {}
    for family, grid in K_GRID.items():
        for k in grid:
            rows = [row for row in measure_all(data, source, k, family) if start <= row["at"] < end]
            name = f"{family}|k{k:g}"
            cells[name] = summarize(rows, bootstrap=bootstrap)
            if family == FX and k == PRIMARY_K:
                primary = cells[name]
                for series in FX_SERIES:
                    tables.setdefault("by_series", {})[series] = summarize(
                        [row for row in rows if row["series"] == series], bootstrap=False)
                for hour in range(24):
                    part = [row for row in rows if row["hour"] == hour]
                    if part:
                        tables.setdefault("by_hour_utc", {})[str(hour)] = summarize(part, bootstrap=False)
    intervals = source_intervals(data, source, start, end)
    assert primary is not None
    return {"prereg_sha256": _sha(PREREG), "source": source, "start": start, "end": end,
            "primary_cell": f"{FX}|k{PRIMARY_K:g}", "cells": cells, "tables": tables, "intervals": intervals,
            "rule": decide(primary, intervals, source)}


def _read(recorder_dir: Path, start: float, end: float, lanes: Sequence[str] = LIP_LANES) -> Data:
    margin = 86_400.0  # programs are listed ahead of their windows
    return load(read_records(recorder_dir, lanes, start=start - margin, end=end + HORIZON_S + 60.0))


def _iso(text: str) -> float:
    value = datetime.fromisoformat(text)
    return (value if value.tzinfo is not None else value.replace(tzinfo=UTC)).timestamp()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pyth lead-lag analyzer (PREREG.md); research only")
    sub = parser.add_subparsers(dest="command", required=True)
    days = sub.add_parser("days", help="list the FX days and the TRAIN/VAL/TEST split for a source")
    days.add_argument("--recorder-dir", required=True)
    days.add_argument("--source", required=True, choices=SOURCES)
    run = sub.add_parser("run", help="measure a phase (or a span) and apply the pre-registered rule")
    run.add_argument("--recorder-dir", required=True)
    run.add_argument("--source", required=True, choices=SOURCES)
    run.add_argument("--phase", choices=("TRAIN", "VAL", "TEST"))
    run.add_argument("--start")
    run.add_argument("--end")
    run.add_argument("--out")
    for command in (days, run):
        command.add_argument("--all-lanes", action="store_true",
                             help="also read Family A's lanes (a recording made before the recorder's LIP lanes)")
    args = parser.parse_args(argv)
    recorder = Path(args.recorder_dir)
    lanes = ALL_LANES if args.all_lanes else LIP_LANES
    if args.command == "days":
        data = load(read_records(recorder, lanes))
        listing = fx_days(data, args.source)
        print(json.dumps({"days": listing, "split": split(listing)}, indent=1))
        return 0
    if args.phase:
        everything = load(read_records(recorder, lanes))
        extended = len(frozen_days()) if args.phase == "TEST" else 4
        chosen = split(fx_days(everything, args.source), extended)[args.phase]
        need = max(4, extended) if args.phase == "TEST" else SPLIT[args.phase][1] - SPLIT[args.phase][0]
        if len(chosen) < need:
            print(f"{args.phase}: only {len(chosen)} of {need} FX days recorded so far ({chosen})")
            return 2
        if args.phase == "TEST":
            problems = check_freeze(args.source, chosen)
            if problems:
                print("TEST refused: " + "; ".join(problems))
                return 3
        start, end = _day_bounds(chosen[0])[0], _day_bounds(chosen[-1])[1]
        data = everything
    else:
        start = _iso(args.start) if args.start else -math.inf
        end = _iso(args.end) if args.end else math.inf
        data = _read(recorder, start, end, lanes)
    if args.phase == "TEST":
        counts = analyze(data, args.source, start, end, bootstrap=False)
        primary = counts["cells"][counts["primary_cell"]]
        if primary["same"] < MIN_SAME or primary["windows_with_same"] < MIN_WINDOWS:
            print(f"TEST counts only: {primary['same']} same events in {primary['windows_with_same']} windows "
                  f"(need {MIN_SAME} in {MIN_WINDOWS}); extend TEST by whole FX days in FREEZE.json")
            return 4
    report = analyze(data, args.source, start, end)
    report["phase"] = args.phase
    if args.phase != "TEST":
        report["rule"]["note"] = "a reading only: only TEST decides (PREREG section 5)"
    text = json.dumps(report, indent=1, allow_nan=False)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    if args.phase == "TEST":
        TEST_RESULT.parent.mkdir(parents=True, exist_ok=True)
        TEST_RESULT.write_text(text, encoding="utf-8")
    primary = report["cells"][report["primary_cell"]]
    print(f"{report['primary_cell']} source {args.source}: events {primary['events']} kept {primary['kept']} "
          f"same {primary['same']} opposite {primary['opposite']} none {primary['none']}; P_same {primary['P_same']} "
          f"{primary['P_same_range95']}; S {primary['S']} {primary['S_range95']}; W_lo median "
          f"{primary['w_lo']['p50']} s; rule: {report['rule']['verdict']} ({report['rule']['why']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
