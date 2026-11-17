"""Lab 5 engine: the crypto price-market specialist (research/lab5/PLAN.md).

Pure functions over lab 4's market list and tapes, lab 5's Gamma rules and Binance 1 s klines (research/lab5/data.py).
Nothing here talks to the network or to the bot.

* :func:`parse_market`: a crypto market's question + rules -> its contract: terminal (above / below / between a
  strike at a Binance 1-minute close), touch (a Binance 1-minute high or low reaching a barrier inside a period) or
  window (up-or-down between two instants, on Binance candles or on a Chainlink stream, spot or TWAP).
* :class:`Spot`: one symbol's 1 s klines as arrays indexed by second. Everything a decision at time ``t`` reads is
  built from candles that CLOSED at or before ``t`` (a 1 s candle opening at ``u`` closes at ``u + 1``): the price
  is the close of candle ``t - 1``, the realized variance uses the 1-minute returns of minutes that ended by ``t``,
  the running extreme uses candles ``[P0, t)``.
* :func:`p_terminal`, :func:`p_touch`, :func:`p_window`: the fair value (zero drift: the price is a martingale,
  log-price drift ``-v/2``; ``v`` the per-second variance).
* :func:`market_candidates`: every buyable print of one market with the model probability of the side it could buy
  (decision time ``ts - LAG_S``), the execution price (print + one tick) and the fee; :func:`first_entries` turns
  them into one bet per market per cell.
* :func:`summarize`, :func:`qualifies` (identical to lab 4's bar), :func:`calibration_placebo`, :func:`record_run`.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import ndtr

HERE = Path(__file__).resolve().parent
LEDGER = HERE / "trials.json"
SIBLING_LEDGERS = (
    HERE.parent / "lab2" / "trials.json",
    HERE.parent / "lab3" / "trials.json",
    HERE.parent / "lab4" / "trials.json",
)

# PLAN §1: lab 4's splits on closedTime (UTC), half-open [start, end).
SPLITS: dict[str, tuple[str, str]] = {
    "train": ("2026-07-01", "2026-08-16"),
    "val": ("2026-08-16", "2026-09-16"),
    "test": ("2026-09-16", "2026-10-09"),
}
MIN_FILLS = 50  # lab 4's universe rule
TICKET_USD = 20.0
SLIP = 0.01  # PLAN §3: one tick of the standard price grid
MAX_PRICE = 0.999
LAG_S = 10  # PLAN §2: the decision reads spot as of the print time minus this
LATENCY_S = 10  # PLAN §5 latency stress: lab 4's execution rule
EXEC_WINDOW_S = 600
BOOTSTRAP_B = 2000
ET_OFFSET_S = 4 * 3600  # EDT (UTC-4) for the whole study period (DST 2026-03-08 .. 2026-11-01)
SPOT_BASE = int(datetime(2026, 6, 1, tzinfo=UTC).timestamp())
VOL_MIN_COVERAGE = 0.8

# Lab 4 Amendment 1: polymarket.com taker fee shares x rate x p x (1 - p); crypto family 0.07.
FEE_RATES = {
    "crypto": 0.07,
    "sports": 0.05,
    "culture": 0.05,
    "economics": 0.05,
    "weather": 0.05,
    "politics": 0.04,
    "finance": 0.04,
    "mentions": 0.04,
    "tech": 0.04,
    "geopolitics": 0.0,
    "zero": 0.0,
}
UNKNOWN_RATE = 0.07
US_RATE = 0.0695  # Polymarket US feeCoefficient (lab 4 Amendment 2), for the re-costing reading

SYMBOL_OF = {
    "bitcoin": "BTCUSDT",
    "btc": "BTCUSDT",
    "ethereum": "ETHUSDT",
    "eth": "ETHUSDT",
    "solana": "SOLUSDT",
    "sol": "SOLUSDT",
    "xrp": "XRPUSDT",
}
MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        1,
    )
}
WINDOW_KINDS = {300: "5m", 900: "15m", 3600: "1h", 14400: "4h", 86400: "1d"}


# --------------------------------------------------------------------------------------------- fees and splits


def fee_rate(fee_type: str | None, fees_enabled: bool) -> float:
    """Lab 4's family table: 'crypto_fees_v2' -> 0.07; fees off -> 0; an unknown family pays the most expensive."""
    if not fees_enabled:
        return 0.0
    if not fee_type:
        return UNKNOWN_RATE
    return FEE_RATES.get(str(fee_type).split("_")[0].lower(), UNKNOWN_RATE)


def fee_per_share(price: float | np.ndarray, rate: float) -> float | np.ndarray:
    return rate * price * (1.0 - price)


def check_split_allowed(split: str) -> None:
    if split == "test" and os.environ.get("LAB5_ALLOW_TEST") != "1":
        raise PermissionError("TEST is a one-look split: set LAB5_ALLOW_TEST=1 to read it (PLAN §1)")


def split_bounds(split: str) -> tuple[float, float]:
    a, b = SPLITS[split]

    def f(s: str) -> float:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()

    return f(a), f(b)


def split_of(closed_time: float) -> str | None:
    for name in SPLITS:
        lo, hi = split_bounds(name)
        if lo <= closed_time < hi:
            return name
    return None


# --------------------------------------------------------------------------------------------- parsing


def _money(s: str) -> float:
    return float(s.replace("$", "").replace(",", ""))


def _et_midnight(year: int, month: int, day: int) -> float:
    """00:00 ET of a calendar day, as unix seconds (EDT throughout the study)."""
    return datetime(year, month, day, tzinfo=UTC).timestamp() + ET_OFFSET_S


def _year_of(ts: float | None) -> int:
    return datetime.fromtimestamp(ts or 0.0, UTC).year


def _symbol(question: str) -> str | None:
    head = re.match(r"^(?:Will (?:the price of )?)?([A-Za-z]+)", question.strip())
    return SYMBOL_OF.get(head.group(1).lower()) if head else None


def _period(text: str, year: int) -> tuple[float, float] | None:
    """'on August 19' | 'August 17-23' | 'July 27-August 2' | 'in August' -> [P0, P1) in unix s (ET days)."""
    t = text.strip().rstrip("?").strip()
    m = re.fullmatch(r"on ([A-Za-z]+) (\d{1,2})", t)
    if m and m.group(1).lower() in MONTHS:
        p0 = _et_midnight(year, MONTHS[m.group(1).lower()], int(m.group(2)))
        return p0, p0 + 86400.0
    m = re.fullmatch(r"([A-Za-z]+) (\d{1,2})-(?:([A-Za-z]+) )?(\d{1,2})", t)
    if m and m.group(1).lower() in MONTHS:
        mo1 = MONTHS[m.group(1).lower()]
        mo2 = MONTHS[m.group(3).lower()] if m.group(3) and m.group(3).lower() in MONTHS else mo1
        p0 = _et_midnight(year, mo1, int(m.group(2)))
        p1 = _et_midnight(year, mo2, int(m.group(4))) + 86400.0
        return (p0, p1) if p1 > p0 else None
    m = re.fullmatch(r"in ([A-Za-z]+)", t)
    if m and m.group(1).lower() in MONTHS:
        mo = MONTHS[m.group(1).lower()]
        p0 = _et_midnight(year, mo, 1)
        nxt = (year + 1, 1) if mo == 12 else (year, mo + 1)
        return p0, _et_midnight(nxt[0], nxt[1], 1)
    return None


def _noon_et(text: str, year: int) -> float | None:
    m = re.fullmatch(r"on ([A-Za-z]+) (\d{1,2})", text.strip().rstrip("?").strip())
    if not m or m.group(1).lower() not in MONTHS:
        return None
    return _et_midnight(year, MONTHS[m.group(1).lower()], int(m.group(2))) + 12 * 3600.0


def parse_market(r: dict[str, Any]) -> dict[str, Any]:
    """The contract of one crypto market, or ``{"kind": None, "why": ...}``.

    Input keys: question, description, resolution_source, outcomes (JSON list), end_date, event_start, twap_s,
    price_to_beat. Output (``kind`` in terminal / touch / window): ``symbol``; ``event_outcome`` = the index of the
    outcome that pays when the event holds (Yes / Up); ``source`` (binance / chainlink); terminal: ``op`` (above /
    below / between), ``k_lo``, ``k_hi``, ``t_final`` (the instant whose price settles it: the close of candle
    ``t_final - 1``); touch: ``op`` (up / down), ``barrier``, ``p0``, ``p1``; window: ``sub`` (5m ... 1d),
    ``t0``, ``t_final``, ``ref_known`` (first instant the reference is public), ``twap_s``, ``ref_rule``,
    ``strict`` (up needs final > ref instead of >=)."""
    q = str(r.get("question") or "")
    desc = str(r.get("description") or "")
    src = str(r.get("resolution_source") or "")
    end = r.get("end_date")
    year = _year_of(end)
    sym = _symbol(q)
    try:
        outcomes = [str(o).lower() for o in json.loads(r.get("outcomes") or "[]")]
    except ValueError:
        outcomes = []
    if len(outcomes) != 2:
        return {"kind": None, "why": "not binary"}
    base = {"symbol": sym, "question": q}
    if "chainlink" in desc.lower() or "chain.link" in src:
        source = "chainlink"
    elif "binance" in desc.lower() or "binance.com" in src:
        source = "binance"
    else:
        source = "other"
    base["source"] = source

    if "up or down" in q.lower():
        if outcomes != ["up", "down"]:
            return {"kind": None, "why": "unexpected outcomes"}
        t0, t1 = r.get("event_start"), end
        if t0 is None or t1 is None or pd.isna(t0) or pd.isna(t1):
            return {**base, "kind": None, "why": "window instants missing"}
        dur = int(round(float(t1) - float(t0)))
        sub = WINDOW_KINDS.get(dur)
        if sub is None:
            return {**base, "kind": None, "why": f"window length {dur} s"}
        out = {**base, "kind": "window", "sub": sub, "t0": float(t0), "event_outcome": 0}
        if source == "chainlink":
            twap = r.get("twap_s")
            if twap is None or pd.isna(twap):
                m = re.search(r"twap-(\d+)s", src)
                twap = float(m.group(1)) if m else (None if "twap" in desc.lower() else 0.0)
            if twap is None:
                return {**out, "kind": None, "why": "TWAP length unknown"}
            ptb = r.get("price_to_beat")
            if ptb is None or pd.isna(ptb) or float(ptb) <= 0:
                return {**out, "kind": None, "why": "no priceToBeat"}
            return {
                **out,
                "t_final": float(t1),
                "ref_known": float(t0),
                "twap_s": float(twap),
                "ref_rule": "chainlink",
                "ref_value": float(ptb),
                "strict": False,
            }
        if source == "binance" and sub == "1h":
            # "close >= open of the 1H candle that begins at t0": open = open of the 1 s candle at t0.
            return {**out, "t_final": float(t1), "ref_known": float(t0) + 1.0, "twap_s": 0.0, "ref_rule": "open_t0", "strict": False}
        if source == "binance" and sub == "1d":
            # close of the 1-minute candle opening at noon ET on day 1 vs on day 2; Up iff day 2 is HIGHER.
            return {
                **out,
                "t_final": float(t1) + 60.0,
                "ref_known": float(t0) + 60.0,
                "twap_s": 0.0,
                "ref_rule": "close_t0_plus_60",
                "strict": True,
            }
        return {**out, "kind": None, "why": f"window {sub} on {source}"}

    if outcomes != ["yes", "no"]:
        return {**base, "kind": None, "why": "unexpected outcomes"}
    if sym is None:
        return {**base, "kind": None, "why": "underlying not in BTC/ETH/SOL/XRP"}
    if source != "binance":
        return {**base, "kind": None, "why": f"source {source}"}
    m = re.match(r"^Will the price of \w+ be (above|less than|greater than) (\$[\d,.]+) (on .+)$", q)
    if m:
        t_noon = _noon_et(m.group(3), year)
        if t_noon is None:
            return {**base, "kind": None, "why": "date unparsed"}
        op = {"above": "above", "greater than": "above", "less than": "below"}[m.group(1)]
        k = _money(m.group(2))
        return {
            **base,
            "kind": "terminal",
            "op": op,
            "k_lo": k,
            "k_hi": k,
            "t_final": t_noon + 60.0,  # the close of the 1-minute candle that OPENS at noon ET
            "event_outcome": 0,
        }
    m = re.match(r"^Will the price of \w+ be between (\$[\d,.]+) and (\$[\d,.]+) (on .+)$", q)
    if m:
        t_noon = _noon_et(m.group(3), year)
        if t_noon is None:
            return {**base, "kind": None, "why": "date unparsed"}
        return {
            **base,
            "kind": "terminal",
            "op": "between",
            "k_lo": _money(m.group(1)),
            "k_hi": _money(m.group(2)),
            "t_final": t_noon + 60.0,
            "event_outcome": 0,
        }
    m = re.match(r"^\w+ above ([\d,.]+) on [A-Za-z]+ \d{1,2}, \d{1,2}[AP]M ET\?$", q)
    if m and end is not None:
        # "Close of the 1 hour candle that ENDS at the time": the close of 1 s candle end - 1.
        k = _money(m.group(1))
        return {**base, "kind": "terminal", "op": "above", "k_lo": k, "k_hi": k, "t_final": float(end), "event_outcome": 0}
    m = re.match(r"^Will \w+ (reach|dip to) (\$[\d,.]+) (.+)$", q)
    if m:
        per = _period(m.group(3), year)
        if per is None:
            return {**base, "kind": None, "why": "touch period unparsed"}
        p0 = per[0]
        if "creation of this market" in desc:
            # monthly rules: "from the creation of this market through 11:59 PM ET on the last day of the month"
            created = r.get("start_date")
            if created is None or pd.isna(created):
                return {**base, "kind": None, "why": "touch creation time missing"}
            p0 = max(p0, float(created))
        return {
            **base,
            "kind": "touch",
            "op": "up" if m.group(1) == "reach" else "down",
            "barrier": _money(m.group(2)),
            "p0": p0,
            "p1": per[1],
            "event_outcome": 0,
        }
    return {**base, "kind": None, "why": "not a price-level question"}


# --------------------------------------------------------------------------------------------- spot


@dataclass
class Spot:
    """One symbol's 1 s klines as dense arrays from ``base`` (unix s, candle open times), gaps forward-filled for
    prices (and left NaN for highs / lows), plus the cumulative squared 1-minute log returns."""

    symbol: str
    base: int
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    cum_r2: np.ndarray  # cum_r2[k] = sum of r^2 over minutes 0 .. k-1 (minute j = seconds [60 j, 60 j + 60) from base)
    cum_n: np.ndarray  # count of valid minute returns, same indexing
    present: np.ndarray  # bool per second: a real candle (not a fill)

    @classmethod
    def from_frame(cls, symbol: str, df: pd.DataFrame, base: int = SPOT_BASE, end: int | None = None) -> Spot:
        ts = df["ts"].to_numpy(dtype=np.int64)
        if end is None:
            end = int(ts.max()) + 1 if len(ts) else base
        n = max(0, int(end) - base)
        n = (n + 59) // 60 * 60
        idx = ts - base
        ok = (idx >= 0) & (idx < n)
        arrs = {}
        for col in ("open", "high", "low", "close"):
            a = np.full(n, np.nan)
            a[idx[ok]] = df[col].to_numpy(dtype=float)[ok]
            arrs[col] = a
        present = np.zeros(n, dtype=bool)
        present[idx[ok]] = True
        close = pd.Series(arrs["close"]).ffill().to_numpy()
        opn = np.where(np.isnan(arrs["open"]), close, arrs["open"])
        minute_close = close[59::60]  # price at the end of each minute
        mvalid = present.reshape(-1, 60).any(axis=1) if n else np.zeros(0, dtype=bool)
        r = np.full(len(minute_close), np.nan)
        if len(minute_close) > 1:
            r[1:] = np.log(minute_close[1:] / minute_close[:-1])
            r[1:][~(mvalid[1:] & mvalid[:-1])] = np.nan
        good = np.isfinite(r)
        cum_r2 = np.concatenate([[0.0], np.cumsum(np.where(good, r * r, 0.0))])
        cum_n = np.concatenate([[0], np.cumsum(good.astype(np.int64))])
        return cls(symbol, base, opn, arrs["high"], arrs["low"], close, cum_r2, cum_n, present)

    def _i(self, t: np.ndarray | float) -> np.ndarray:
        return np.asarray(t, dtype=np.int64) - self.base

    def price_at(self, t: np.ndarray | float) -> np.ndarray:
        """The last price known at integer time ``t``: the close of the 1 s candle that opened at ``t - 1``."""
        i = self._i(t) - 1
        out = np.full(np.shape(i), np.nan)
        ok = (i >= 0) & (i < len(self.close))
        out[ok] = self.close[i[ok]]
        return out

    def open_of(self, t: float) -> float:
        """The open of the 1 s candle that opens at ``t`` (known from ``t + 1``)."""
        i = int(t) - self.base
        return float(self.open[i]) if 0 <= i < len(self.open) else float("nan")

    def close_of(self, t: float) -> float:
        """The close of the 1 s candle that opens at ``t`` (known from ``t + 1``)."""
        i = int(t) - self.base
        return float(self.close[i]) if 0 <= i < len(self.close) else float("nan")

    def twap(self, a: float, b: float) -> float:
        """Mean of the 1 s closes of candles opening in [a, b) (known from ``b``)."""
        i0, i1 = int(a) - self.base, int(b) - self.base
        if i0 < 0 or i1 > len(self.close) or i1 <= i0:
            return float("nan")
        return float(self.close[i0:i1].mean())

    def var_per_s(self, t: np.ndarray | float, window_s: int) -> np.ndarray:
        """Realized variance per second over the ``window_s`` before ``t`` from 1-minute log returns of minutes that
        ENDED by ``t`` (minute j ends at base + 60 (j + 1)); NaN under VOL_MIN_COVERAGE of the minutes."""
        k_end = np.floor((np.asarray(t, dtype=float) - self.base) / 60.0).astype(np.int64)  # minutes complete by t
        w = int(window_s // 60)
        k_start = k_end - w
        out = np.full(np.shape(k_end), np.nan)
        ok = (k_start >= 0) & (k_end < len(self.cum_r2))
        s = self.cum_r2[k_end[ok]] - self.cum_r2[k_start[ok]]
        c = self.cum_n[k_end[ok]] - self.cum_n[k_start[ok]]
        v = np.where(c >= VOL_MIN_COVERAGE * w, s / np.maximum(c, 1) / 60.0, np.nan)
        out[ok] = v
        return out

    def running_extreme(self, p0: float, t: np.ndarray, up: bool) -> np.ndarray:
        """Max high (up) or min low over candles opening in [p0, t) for each ``t`` (NaN when t <= p0)."""
        t = np.asarray(t, dtype=np.int64)
        i0 = int(p0) - self.base
        i1 = min(int(t.max()) - self.base, len(self.high)) if len(t) else i0
        out = np.full(len(t), np.nan)
        if len(t) == 0 or i1 <= i0 or i0 < 0:
            return out
        seg = self.high[i0:i1] if up else self.low[i0:i1]
        seg = np.where(np.isnan(seg), -np.inf if up else np.inf, seg)
        acc = np.maximum.accumulate(seg) if up else np.minimum.accumulate(seg)
        j = t - self.base - i0 - 1  # last candle opening before t
        ok = (j >= 0) & (j < len(acc))  # beyond the data: unknown, never extrapolated
        out[ok] = acc[j[ok]]
        out[np.isinf(out)] = np.nan
        return out


# --------------------------------------------------------------------------------------------- fair value


def p_terminal(s: np.ndarray, k_lo: float, k_hi: float, op: str, var_tau: np.ndarray) -> np.ndarray:
    """P(final price above k / below k / in [k_lo, k_hi)) for a zero-drift lognormal price:
    ln S_T ~ N(ln s - V/2, V) with V = v x tau."""
    s = np.asarray(s, dtype=float)
    sd = np.sqrt(np.maximum(var_tau, 1e-18))

    def above(k: float) -> np.ndarray:
        return ndtr((np.log(s / k) - 0.5 * var_tau) / sd)

    if op == "above":
        return above(k_lo)
    if op == "below":
        return 1.0 - above(k_lo)
    if op == "between":
        return np.clip(above(k_lo) - above(k_hi), 0.0, 1.0)
    raise ValueError(op)


def p_touch(s: np.ndarray, barrier: float, up: bool, var_tau: np.ndarray, extreme: np.ndarray) -> np.ndarray:
    """P(the price touches ``barrier`` before the period ends): 1 if the running extreme already reached it, else
    the reflection principle for a driftless log price, 2 x P(ln S_T beyond ln B) = 2 Phi(-|ln(B / s)| / sqrt(V))."""
    s = np.asarray(s, dtype=float)
    sd = np.sqrt(np.maximum(var_tau, 1e-18))
    dist = np.log(barrier / s) if up else np.log(s / barrier)
    p = np.minimum(1.0, 2.0 * ndtr(-np.maximum(dist, 0.0) / sd))
    hit = (extreme >= barrier) if up else (extreme <= barrier)
    return np.where(np.nan_to_num(hit, nan=0.0).astype(bool), 1.0, p)


def twap_moments(
    t: np.ndarray, t_final: float, twap_s: float, s_now: np.ndarray, known_sum: np.ndarray, v: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Mean and variance of F = the average of the 1 s price over [t_final - L, t_final) seen at time ``t`` with
    price ``s_now`` and the seconds of that window already elapsed summing to ``known_sum``. Arithmetic Brownian
    approximation: with g = seconds until the window starts and l = seconds of it still to come,
    Var F = s^2 v (l^2 g + l^3 / 3) / L^2 (the average of a Brownian path over l seconds after a g-second gap).
    L = 0 is the spot case: F = S_{t_final}, mean s, variance s^2 v (t_final - t)."""
    t = np.asarray(t, dtype=float)
    if twap_s <= 0:
        tau = np.maximum(t_final - t, 0.0)
        return s_now, s_now * s_now * v * tau
    L = float(twap_s)
    a = np.maximum(t, t_final - L)
    l_rem = np.maximum(t_final - a, 0.0)
    g = np.maximum(t_final - L - t, 0.0)
    mean = known_sum / L + s_now * l_rem / L
    var = s_now * s_now * v * (l_rem * l_rem * g + l_rem**3 / 3.0) / (L * L)
    return mean, var


def p_window(mean: np.ndarray, var: np.ndarray, ref: float, strict: bool = False) -> np.ndarray:
    """P(F >= ref) (or > ref) for F ~ N(mean, var); a certain F (var 0) is decided by the comparison."""
    sd = np.sqrt(np.maximum(var, 0.0))
    z = np.where(sd > 0, (mean - ref) / np.where(sd > 0, sd, 1.0), np.where(mean > ref, np.inf, np.where(mean < ref, -np.inf, 0.0)))
    p = ndtr(z)
    if not strict:
        p = np.where((sd == 0) & (mean == ref), 1.0, p)
    else:
        p = np.where((sd == 0) & (mean == ref), 0.0, p)
    return p


def p_lognormal_window(s_ref_scaled: np.ndarray, ref: float, var_tau: np.ndarray) -> np.ndarray:
    """Spot-settled window (L = 0): P(S_T >= ref) with ln S_T ~ N(ln s - V/2, V)."""
    return p_terminal(s_ref_scaled, ref, ref, "above", var_tau)


# --------------------------------------------------------------------------------------------- per market


@dataclass
class Market:
    """One market of the universe: lab 4's row + the parsed contract + the fee rate."""

    id: str
    contract: dict[str, Any]
    winner: int
    closed_time: float
    end_date: float
    rate: float
    cluster: str
    split: str


def outcome_event(m: Market, spot: Spot) -> int | None:
    """The settlement replicated from Binance (1 = the event held, 0 = not, None = cannot replicate). For Chainlink
    windows this is the Binance PROXY outcome (a basis reading, never used to settle a bet)."""
    c = m.contract
    if c["kind"] == "terminal":
        x = spot.close_of(c["t_final"] - 1)
        if not math.isfinite(x):
            return None
        if c["op"] == "above":
            return int(x > c["k_lo"])
        if c["op"] == "below":
            return int(x < c["k_lo"])
        return int(c["k_lo"] <= x < c["k_hi"])
    if c["kind"] == "touch":
        ext = spot.running_extreme(c["p0"], np.array([c["p1"]]), c["op"] == "up")[0]
        if not math.isfinite(ext):
            return None
        return int(ext >= c["barrier"]) if c["op"] == "up" else int(ext <= c["barrier"])
    if c["kind"] == "window":
        ref, fin = window_ref_final_binance(c, spot)
        if not (math.isfinite(ref) and math.isfinite(fin)):
            return None
        return int(fin > ref) if c["strict"] else int(fin >= ref)
    return None


def window_ref_binance(c: dict[str, Any], spot: Spot) -> float:
    """Binance's value of a window's reference, public at ``ref_known`` (exact for Binance windows; for Chainlink
    windows the proxy of the stream at t0: the price at t0, or the TWAP of the L seconds before t0)."""
    if c["ref_rule"] == "open_t0":
        return spot.open_of(c["t0"])
    if c["ref_rule"] == "close_t0_plus_60":
        return spot.close_of(c["ref_known"] - 1)
    L = c["twap_s"]
    return spot.twap(c["t0"] - L, c["t0"]) if L > 0 else spot.close_of(c["t0"] - 1)


def window_final_binance(c: dict[str, Any], spot: Spot) -> float:
    """Binance's value of a window's settlement (a SETTLEMENT reading: never used by a decision)."""
    if c["ref_rule"] in ("open_t0", "close_t0_plus_60"):
        return spot.close_of(c["t_final"] - 1)
    L = c["twap_s"]
    return spot.twap(c["t_final"] - L, c["t_final"]) if L > 0 else spot.close_of(c["t_final"] - 1)


def window_ref_final_binance(c: dict[str, Any], spot: Spot) -> tuple[float, float]:
    return window_ref_binance(c, spot), window_final_binance(c, spot)


def q_event(
    m: Market, spot: Spot, t: np.ndarray, vol_window_s: int, basis_sd: float = 0.0
) -> np.ndarray:
    """Model probability that the market's event holds, decided at integer times ``t`` (already lagged): NaN where
    the model is undefined (before the reference is public, at or after settlement, outside a touch period, no
    spot or no variance)."""
    c = m.contract
    t = np.asarray(t, dtype=np.int64)
    s = spot.price_at(t)
    v = spot.var_per_s(t, vol_window_s)
    out = np.full(len(t), np.nan)
    if c["kind"] == "terminal":
        tau = c["t_final"] - t
        ok = (tau > 0) & np.isfinite(s) & np.isfinite(v)
        out[ok] = p_terminal(s[ok], c["k_lo"], c["k_hi"], c["op"], v[ok] * tau[ok])
        return out
    if c["kind"] == "touch":
        tau = c["p1"] - t
        ok = (t > c["p0"]) & (tau > 0) & np.isfinite(s) & np.isfinite(v)
        if ok.any():
            ext = spot.running_extreme(c["p0"], t[ok], c["op"] == "up")
            out[ok] = p_touch(s[ok], c["barrier"], c["op"] == "up", v[ok] * tau[ok], ext)
        return out
    if c["kind"] == "window":
        ok = (t >= c["ref_known"]) & (t < c["t_final"]) & np.isfinite(s) & np.isfinite(v)
        if not ok.any():
            return out
        if c["ref_rule"] == "chainlink":
            ref = c["ref_value"]
            L = c["twap_s"]
            proxy_t0 = spot.twap(c["t0"] - L, c["t0"]) if L > 0 else spot.close_of(c["t0"] - 1)
            if not (math.isfinite(proxy_t0) and proxy_t0 > 0):
                return out
            kappa = ref / proxy_t0  # Chainlink / Binance at the window open (both public at t0)
        else:
            ref = window_ref_binance(c, spot)
            L = 0.0
            kappa = 1.0
            if not math.isfinite(ref):
                return out
        if c["ref_rule"] != "chainlink":
            basis_sd = 0.0  # Binance windows settle on the very data the model reads: no basis
        tt = t[ok]
        s_now = kappa * s[ok]
        if L > 0:
            # seconds of the averaging window already elapsed by tt: candles opening in [t_final - L, tt)
            a = int(c["t_final"] - L) - spot.base
            cs = np.concatenate([[0.0], np.cumsum(spot.close[a : int(c["t_final"]) - spot.base])])
            n_known = np.clip(tt - (c["t_final"] - L), 0, L).astype(np.int64)
            known_sum = kappa * cs[n_known]
            mean, var = twap_moments(tt, c["t_final"], L, s_now, known_sum, v[ok])
            var = var + (ref * basis_sd) ** 2
            out[ok] = p_window(mean, var, ref, c["strict"])
        else:
            var_tau = v[ok] * (c["t_final"] - tt) + basis_sd**2
            p = p_lognormal_window(s_now, ref, var_tau)
            out[ok] = p
        return out
    return out


CANDIDATE_COLUMNS = ["ts", "side", "p_print", "p_x", "fee_ps", "tau"]


def market_candidates(m: Market, tape: pd.DataFrame, spot: Spot, vol_windows: list[int], basis_sd: float = 0.0, lag_s: int = LAG_S) -> pd.DataFrame:
    """Every buyable print of the market before settlement, as seen by the specialist: the side it could buy
    (0 / 1), the print price of that side, the execution price (print + SLIP, capped at MAX_PRICE), the fee per share,
    the seconds left to settlement, and for each vol window ``q<W>`` = the model probability of THAT side won at a
    decision time ``ts - lag_s``. ``tape`` columns: ts, p0 (price of outcome 0), buy0 (buyable for outcome 0)."""
    c = m.contract
    t_settle = c["t_final"] if c["kind"] in ("terminal", "window") else c["p1"]
    tape = tape[tape["ts"] < min(t_settle, m.closed_time)]
    ts = tape["ts"].to_numpy(dtype=np.int64)
    side = np.where(tape["buy0"].to_numpy(dtype=bool), 0, 1)
    p0 = tape["p0"].to_numpy(dtype=float)
    p_side = np.where(side == 0, p0, 1.0 - p0)
    p_x = np.minimum(p_side + SLIP, MAX_PRICE)
    out = pd.DataFrame(
        {
            "ts": ts,
            "side": side,
            "p_print": p_side,
            "p_x": p_x,
            "fee_ps": fee_per_share(p_x, m.rate),
            "tau": t_settle - ts,
        }
    )
    ev = int(c["event_outcome"])
    for w in vol_windows:
        qe = q_event(m, spot, ts - lag_s, w, basis_sd)
        q0 = qe if ev == 0 else 1.0 - qe
        out[f"q{w}"] = np.where(side == 0, q0, 1.0 - q0)
    return out


def entry_mask(cand: pd.DataFrame, m: Market, window: str, lag_s: int = LAG_S) -> np.ndarray:
    """PLAN §3 entry windows. terminal / touch: 'near' = 5 min <= tau < 24 h, 'far' = 24 h <= tau < 7 d (touch: and
    the decision falls inside the period). window: 'early' = decision in the first half of [ref_known, t_final),
    'late' = the second half, never in the last 5 s."""
    c = m.contract
    tau = cand["tau"].to_numpy(dtype=float)
    td = cand["ts"].to_numpy(dtype=float) - lag_s
    if c["kind"] in ("terminal", "touch"):
        inside = np.ones(len(td), dtype=bool) if c["kind"] == "terminal" else (td > c["p0"])
        if window == "near":
            return inside & (tau >= 300) & (tau < 86400)
        if window == "far":
            return inside & (tau >= 86400) & (tau < 7 * 86400)
        raise ValueError(window)
    a, b = c["ref_known"], c["t_final"]
    mid = a + (b - a) / 2.0
    if window == "early":
        return (td >= a) & (td < mid) & (tau >= 5)
    if window == "late":
        return (td >= mid) & (td < b) & (tau >= 5)
    raise ValueError(window)


def first_entries(cand: pd.DataFrame, mask: np.ndarray, qcol: str, margin: float) -> int | None:
    """Row index of the first print in ``mask`` whose edge q - p_x - fee per share exceeds ``margin``; None if none."""
    q = cand[qcol].to_numpy(dtype=float)
    edge = q - cand["p_x"].to_numpy(dtype=float) - cand["fee_ps"].to_numpy(dtype=float)
    hit = mask & np.isfinite(edge) & (edge > margin)
    if not hit.any():
        return None
    return int(np.argmax(hit))


def settle(m: Market, side: int, p_x: float, rate: float | None = None, ticket: float = TICKET_USD) -> dict[str, float]:
    """$20 ticket at ``p_x``: shares = 20 / p_x, fee = shares x rate x p x (1 - p), payout = shares if ``side`` won."""
    r = m.rate if rate is None else rate
    shares = ticket / p_x
    fee = shares * fee_per_share(p_x, r)
    won = int(m.winner) == int(side)
    pnl = (shares if won else 0.0) - fee - ticket
    return {"won": bool(won), "fee_usd": float(fee), "pnl_usd": float(pnl), "net": float(pnl / ticket)}


def latency_exec(cand: pd.DataFrame, i: int, latency_s: int = LATENCY_S) -> int | None:
    """Lab 4's execution rule for the latency stress: the first buyable print for the SAME side at or after
    ts_i + latency_s, within EXEC_WINDOW_S and before settlement; None when there is none."""
    ts = cand["ts"].to_numpy(dtype=np.int64)
    side = cand["side"].to_numpy()
    t_i = ts[i]
    ok = (ts >= t_i + latency_s) & (ts <= t_i + EXEC_WINDOW_S) & (side == side[i])
    if not ok.any():
        return None
    return int(np.argmax(ok))


# --------------------------------------------------------------------------------------------- readings


def cluster_bootstrap_ci(values: np.ndarray, groups: np.ndarray, B: int = BOOTSTRAP_B, seed: int = 0) -> tuple[float, float]:
    """95 % interval of the mean under resampling of CLUSTERS (PLAN §4: bets settled by one price draw are one)."""
    if len(values) == 0:
        return (float("nan"), float("nan"))
    keys, inv = np.unique(groups.astype(str), return_inverse=True)
    sums = np.bincount(inv, weights=values, minlength=len(keys))
    counts = np.bincount(inv, minlength=len(keys)).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(keys), size=(B, len(keys)))
    means = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def summarize(trades: pd.DataFrame, split: str, B: int = BOOTSTRAP_B) -> dict[str, Any]:
    """PLAN §4 readings for one cell: n, losses, win rate vs mean price vs mean model probability, mean net per $
    with the cluster bootstrap CI, the rule-of-three worst case, $ per $20 ticket, bets per day, the latency stress,
    the Polymarket US re-costing and the per-kind breakdown."""
    lo, hi = split_bounds(split)
    days = max(1.0, (hi - lo) / 86400.0)
    n = len(trades)
    base: dict[str, Any] = {"n": n, "bets_per_day": n / days}
    if n == 0:
        return {
            **base,
            "n_clusters": 0,
            "losses": 0,
            "win_rate": None,
            "mean_p_exec": None,
            "mean_q": None,
            "mean_edge": None,
            "mean_net": None,
            "ci95": [None, None],
            "worst_case_net": None,
            "mean_pnl_usd": None,
            "total_usd": 0.0,
            "usd_per_day": 0.0,
            "worst_pnl_usd": None,
            "latency": {"n": 0, "mean_net": None},
            "us_mean_net": None,
            "by_kind": {},
        }
    t = trades.sort_values("t_entry")
    net = t["net"].to_numpy(dtype=float)
    won = t["won"].to_numpy(dtype=bool)
    groups = t["cluster"].astype(str).to_numpy()
    ci = cluster_bootstrap_ci(net, groups, B=B)
    losses = int((~won).sum())
    mean_win = float(net[won].mean()) if won.any() else 0.0
    worst = (1.0 - 3.0 / n) * mean_win - 3.0 / n
    lat = t[t["lat_net"].notna()] if "lat_net" in t else t.iloc[0:0]
    by_kind = {}
    for k, g in t.groupby("sub"):
        by_kind[str(k)] = {
            "n": len(g),
            "win_rate": float(g["won"].mean()),
            "mean_p_exec": float(g["p_x"].mean()),
            "mean_q": float(g["q"].mean()),
            "mean_net": float(g["net"].mean()),
            "total_usd": float(g["pnl_usd"].sum()),
        }
    return {
        **base,
        "n_clusters": int(len(np.unique(groups))),
        "losses": losses,
        "win_rate": float(won.mean()),
        "mean_p_exec": float(t["p_x"].mean()),
        "mean_q": float(t["q"].mean()),
        "mean_edge": float((t["q"] - t["p_x"] - t["fee_ps"]).mean()),
        "mean_net": float(net.mean()),
        "ci95": [ci[0], ci[1]],
        "worst_case_net": float(worst),
        "mean_pnl_usd": float(t["pnl_usd"].mean()),
        "total_usd": float(t["pnl_usd"].sum()),
        "usd_per_day": float(t["pnl_usd"].sum() / days),
        "worst_pnl_usd": float(t["pnl_usd"].min()),
        "latency": {
            "n": int(len(lat)),
            "missed": int(n - len(lat)),
            "mean_net": float(lat["lat_net"].mean()) if len(lat) else None,
        },
        "us_mean_net": float(t["us_net"].mean()) if "us_net" in t else None,
        "by_kind": by_kind,
    }


def calibration_placebo(trades: pd.DataFrame, draws: int = BOOTSTRAP_B, seed: int = 1) -> dict[str, Any]:
    """Lab 4's placebo: outcomes redrawn as Bernoulli(p_exec) (the market price is the truth); the mean net of
    the same bets under that null, and where the real mean sits in it."""
    if len(trades) == 0:
        return {"draws": 0, "p95": None, "mean": None, "real_percentile": None}
    p = trades["p_x"].to_numpy(dtype=float)
    fee = trades["fee_usd"].to_numpy(dtype=float)
    shares = TICKET_USD / p
    rng = np.random.default_rng(seed)
    wins = rng.random((draws, len(p))) < p
    pnl = np.where(wins, shares, 0.0) - fee - TICKET_USD
    means = pnl.mean(axis=1) / TICKET_USD
    real = float(trades["net"].mean())
    return {
        "draws": draws,
        "p95": float(np.percentile(means, 95)),
        "mean": float(means.mean()),
        "real_percentile": float((means < real).mean() * 100.0),
    }


def brier(q: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((np.asarray(q, dtype=float) - np.asarray(y, dtype=float)) ** 2)) if len(q) else float("nan")


def qualifies(s: dict[str, Any], min_n: int = 100) -> bool:
    """Lab 4's bar, unchanged (PLAN §3 + Amendment 3 of lab 4): n >= min_n, mean > 0, CI lower bound > 0, at least
    one observed loss, and with fewer than five losses the rule-of-three worst case must still be positive."""
    if s["n"] < min_n or s["mean_net"] is None or s["ci95"][0] is None:
        return False
    if not (s["mean_net"] > 0 and s["ci95"][0] > 0):
        return False
    losses = int(s.get("losses") or 0)
    if losses < 1:
        return False
    if losses < 5 and not (s.get("worst_case_net") is not None and s["worst_case_net"] > 0):
        return False
    return True


# --------------------------------------------------------------------------------------------- ledger


def _ledger_size(doc: Any) -> int:
    if isinstance(doc, list):
        return len(doc)
    if isinstance(doc, dict):
        if isinstance(doc.get("n_trials_total"), int):
            return int(doc["n_trials_total"])
        for key in ("trials", "runs"):
            if isinstance(doc.get(key), list):
                return len(doc[key])
    return 0


def trials_count(ledger: Path = LEDGER) -> int:
    """Trials across labs 2-5 (each ledger read in its own format)."""
    n = 0
    for path in (*SIBLING_LEDGERS, ledger):
        if path.exists():
            try:
                n += _ledger_size(json.loads(path.read_text()))
            except ValueError:
                continue
    return n


def record_run(entry: dict[str, Any], ledger: Path = LEDGER) -> int:
    """Upsert one trial in research/lab5/trials.json keyed on (lab, hyp, cell, split, stage); returns the running
    count across labs 2-5."""
    rows = json.loads(ledger.read_text()) if ledger.exists() else []
    key = tuple(entry.get(k) for k in ("lab", "hyp", "cell", "split", "stage"))
    rows = [e for e in rows if tuple(e.get(k) for k in ("lab", "hyp", "cell", "split", "stage")) != key]
    rows.append({**entry, "utc": datetime.now(UTC).isoformat(timespec="seconds"), "t": time.time()})
    ledger.write_text(json.dumps(rows, indent=1, sort_keys=True) + "\n")
    return trials_count(ledger)


def et_day(ts: float) -> str:
    return (datetime.fromtimestamp(ts, UTC) - timedelta(seconds=ET_OFFSET_S)).strftime("%Y-%m-%d")
