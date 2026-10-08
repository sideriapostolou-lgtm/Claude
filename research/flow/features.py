"""Offline helpers that turn raw CryptoHouse chunk outputs into research tables (no network).

Leakage rule for strategy code: everything here is *descriptive storage*. Features for a decision at
time t must be recomputed from events with timestamp <= t - 20 s (PLAN 3.2). In particular
``detect_agent`` reports ``known_at`` (the AGENT's 4th buy) and must not be used before that time, and
the per-minute bars are only complete for minutes that ended before the decision.
"""

from __future__ import annotations

import math
from statistics import median
from typing import Iterable

# B2 bar tuple layout (see sql/b2.sql)
BAR_FIELDS = (
    "minute_ts", "n_buys", "n_sells", "n_dust", "buy_sol", "sell_sol", "buy_tok", "sell_tok",
    "n_buyers", "n_sellers", "top5_buy_sol", "open", "high", "low", "close", "x_close", "y_close",
)

AGENT_WINDOW_S = 330
AGENT_MIN_BUYS = 4
AGENT_GAP_RANGE = (11.0, 13.0)
AGENT_MAX_CV = 0.15


def merge_agent_candidates(chunks: Iterable[list]) -> dict[str, dict]:
    """Merge per-chunk AGENT candidate tuples (wallet, [ts], [sol], n_sells) by wallet."""
    out: dict[str, dict] = {}
    for cands in chunks:
        for c in cands or []:
            w, ts, sol = c[0], list(c[1]), list(c[2])
            sells = c[3] if len(c) > 3 else 0
            d = out.setdefault(w, {"ts": [], "sol": [], "sells": 0})
            d["ts"].extend(ts)
            d["sol"].extend(sol)
            d["sells"] += int(sells or 0)
    for d in out.values():
        order = sorted(range(len(d["ts"])), key=lambda i: d["ts"][i])
        d["ts"] = [d["ts"][i] for i in order]
        d["sol"] = [d["sol"][i] for i in order]
    return out


def agent_stats(ts: list[int], sol: list[float]) -> dict | None:
    if len(ts) < 2:
        return None
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    mg = median(gaps)
    mean = sum(gaps) / len(gaps)
    sd = math.sqrt(sum((g - mean) ** 2 for g in gaps) / len(gaps)) if len(gaps) > 1 else 0.0
    cv = sd / mean if mean > 0 else float("inf")
    return {"n_slices": len(ts), "sol": float(sum(sol)), "median_gap": float(mg), "gap_cv": float(cv)}


def detect_agent(cands: dict[str, dict], g_ts: int) -> dict | None:
    """PLAN 3.2 AGENT (BOOST): >= 4 buys in [g, g+330 s], 0 sells, median gap in [11, 13] s, gap CV < 0.15.

    Returns the best-matching wallet with ``known_at`` = time of its 4th buy (first moment the role is
    knowable), or None.
    """
    best = None
    for w, d in cands.items():
        if d["sells"]:
            continue
        idx = [i for i, t in enumerate(d["ts"]) if g_ts <= t < g_ts + AGENT_WINDOW_S]
        ts = [d["ts"][i] for i in idx]
        sol = [d["sol"][i] for i in idx]
        if len(ts) < AGENT_MIN_BUYS:
            continue
        st = agent_stats(ts, sol)
        if not st or not (AGENT_GAP_RANGE[0] <= st["median_gap"] <= AGENT_GAP_RANGE[1]) or st["gap_cv"] >= AGENT_MAX_CV:
            continue
        st.update({"wallet": w, "first_offset_s": ts[0] - g_ts, "last_offset_s": ts[-1] - g_ts,
                   "known_at": ts[AGENT_MIN_BUYS - 1], "buy_ts": ts, "buy_sol": sol})
        if best is None or st["sol"] > best["sol"]:
            best = st
    return best


def bars_to_dicts(bars: list[list]) -> list[dict]:
    return [dict(zip(BAR_FIELDS, b)) for b in bars]


def repair_prices(bars: list[dict], virt_sol: float | None) -> list[dict]:
    """Recompute close from the real reserves with the pool's virtual quote reserve.

    Chunks where the pool had no Buy event report virt = 0 (Sell events do not carry it), so their
    prices are (x / y) instead of ((x + v) / y). Close is exact after repair; open/high/low are scaled
    by the close's correction factor (approximate) and flagged.
    """
    if not virt_sol:
        return bars
    out = []
    for b in bars:
        b = dict(b)
        x, y = b.get("x_close"), b.get("y_close")
        if x is not None and y and y > 0:
            true_close = (x + virt_sol) / y
            if b["close"] and abs(true_close / b["close"] - 1) > 1e-4:
                f = true_close / b["close"]
                b["open"], b["high"], b["low"] = b["open"] * f, b["high"] * f, b["low"] * f
                b["close"] = true_close
                b["price_repaired"] = 1
        out.append(b)
    return out


def merge_b2(rows: list[dict]) -> dict:
    """Merge B2 rows of one pool from several chunks into one coin record."""
    rows = sorted(rows, key=lambda r: (r.get("first_m") or 0))
    virts = [r.get("virt_sol") for r in rows if r.get("virt_sol")]
    virt = median(virts) if virts else 0.0
    bars: dict[int, dict] = {}
    for r in rows:
        chunk_virt = r.get("virt_sol") or 0.0
        bd = bars_to_dicts(r.get("bars") or [])
        if virt and not chunk_virt:
            bd = repair_prices(bd, virt)
        for b in bd:
            bars[b["minute_ts"]] = b  # chunks are disjoint clock hours; last wins on overlap
    complete = [r for r in rows if r.get("w_complete")]
    wsrc = complete[0] if complete else (rows[0] if rows else {})
    wkeys = ("w120_buy_sol", "w120_sell_sol", "w120_n_buyers", "w120_n_sellers",
             "w300_buy_sol", "w300_sell_sol", "w300_n_buyers", "w300_n_sellers", "w120_top10", "w300_top10")
    win = {k: wsrc.get(k) for k in wkeys}
    if not complete and len(rows) > 1:
        # window straddles a chunk boundary: sums add exactly, counts/top lists are approximate
        for k in ("w120_buy_sol", "w120_sell_sol", "w300_buy_sol", "w300_sell_sol"):
            win[k] = sum(float(r.get(k) or 0) for r in rows)
        for k in ("w120_n_buyers", "w120_n_sellers", "w300_n_buyers", "w300_n_sellers"):
            win[k] = max(int(r.get(k) or 0) for r in rows)
    first = rows[0] if rows else {}
    agent = detect_agent(merge_agent_candidates(r.get("agent_cands") for r in rows), int(first.get("g_ts") or 0))
    return {
        "pool": first.get("pool"), "mint": first.get("mint"), "g_ts": first.get("g_ts"),
        "virt_sol": virt, "n_chunks": len(rows), "w_exact": bool(complete), **win,
        "bars": [bars[k] for k in sorted(bars)], "agent": agent,
    }


def agent_sol_by_minute(agent: dict | None) -> dict[int, float]:
    if not agent:
        return {}
    out: dict[int, float] = {}
    for t, s in zip(agent["buy_ts"], agent["buy_sol"]):
        m = (t // 60) * 60
        out[m] = out.get(m, 0.0) + s
    return out


def top_share(top: list | None, total: float | None, k: int = 5, exclude: str | None = None) -> float | None:
    if not top or not total:
        return None
    vals = [t[1] for t in top if t[0] != exclude]
    tot = total - sum(t[1] for t in top if t[0] == exclude)
    return sum(sorted(vals, reverse=True)[:k]) / tot if tot > 0 else None
