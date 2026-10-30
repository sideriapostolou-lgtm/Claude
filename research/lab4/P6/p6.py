"""Lab 4 P6 (PLAN.md Amendment 5): sport by sport, the live desk's in-play rule on lab 4's cached Polymarket tapes.

The question (the owner, 2026-10-10): which sports' near-certain in-play favourites lose more often than their price
says. The rule tested is the Polymarket US desk's own sports rule, as close as the tape allows:

* universe: binary, single-winner markets whose Gamma ``sportsMarketType`` is ``moneyline`` (the game winner: a
  two-sided match winner, or one side / the draw of a three-way game), of a sport by :mod:`sports`, with the game's
  start (``startTime``) and end (``finishedTimestamp``) known (:mod:`meta`), and >= 50 fills;
* buy: the first BUYABLE print (Amendment 3) at or above ``theta`` for an allowed outcome while the game is in play
  (``startTime <= t < finishedTimestamp``), executed at the first buyable print for the same outcome 10 s later
  (within 600 s, still in play); the YES side only in a Yes/No market (the venue prices every order on YES), either
  team in a two-team market; one trade per market; hold to resolution;
* cost: Polymarket US's taker fee ``0.0695 x shares x p x (1 - p)`` (selects) and polymarket.com's family fee
  (reported); $20 tickets as everywhere in lab 4, so ``net`` is per $1 at risk;
* readings per sport and per league; the event bootstrap (a game's markets are one draw).

TRAIN classifies each sport at theta 0.97 (ALLOWED / BLOCKED / NOT ALLOWED); VAL confirms the pooled ALLOWED set
(lab bar + calibration placebo); TEST is one look at the same pooled set. CLI::

    python research/lab4/P6/p6.py --stage train
    python research/lab4/P6/p6.py --stage val
    LAB4_ALLOW_TEST=1 python research/lab4/P6/p6.py --stage test      # once, only after VAL passes
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
for _p in (str(LAB), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import core as C
import run as R
from sports import SPORTS, league_of, sport_of

import data as D

HYP = "P6"
TITLE = "sport by sport: in-play game winners at 97c+ (the live desk's rule)"
PLAN_VERSION = "lab4-v1 + Amendments 1-5"
US_RATE = 0.0695
THETA = 0.97
THETAS = (0.97, 0.98, 0.99)
MIN_EVENTS = 30
MIN_N_POOLED = 100
PLACEBO_PCT = 95.0
WINNER_TYPES = ("moneyline",)
META_NAME = "p6_meta.parquet"
NEVER_ALLOWED = ("other",)  # a mixed bucket is not a sport the desk can name
# Amendment 5 (b): a game whose end Gamma does not record (or records outside [start, closedTime]) gets the fallback
# end closedTime - L, L = the 90th percentile of (closedTime - finishedTimestamp) on TRAIN games of that sport that
# have a valid end (structure only, measured 2026-10-10 before any return); 139 min (all sports) where none has one.
FALLBACK_LAG_MIN: dict[str, float] = {
    "tennis": 38.0,
    "baseball": 20.0,
    "basketball": 42.0,
    "soccer": 172.0,
    "cricket": 238.0,
    "american football": 94.0,
}
FALLBACK_LAG_DEFAULT_MIN = 139.0
WHISTLE, FALLBACK = "final whistle", "fallback end"
# The leagues of the real desk's losses on 2026-10-09/10 (codes as the venues spell them): does history cover them?
DESK_LEAGUES = {
    "ebfsa": "e-soccer eBattles Serie A",
    "del": "German DEL ice hockey",
    "setkameua": "Setka Cup Ukraine table tennis",
    "wta": "WTA tennis",
    "atp": "ATP tennis (incl. Challengers on polymarket.com)",
}

TRADE_COLUMNS = [
    "id",
    "event",
    "family",
    "sport",
    "league",
    "question",
    "closed_time",
    "end_date",
    "outcome",
    "t_signal",
    "p_signal",
    "day",
    "missed",
    "t_exec",
    "p_exec",
    "won",
    "net",
    "net_com",
    "fee_usd",
    "pnl_usd",
    "cents_per_contract",
    "lock_h",
    "min_after_start",
    "min_before_end",
    "score",
    "end_kind",
    "after_whistle",
    "old_rule_bid_side",
]


# ---------------------------------------------------------------------------------------------------------- universe
def load_meta(out_dir: Path) -> pd.DataFrame:
    meta = pd.read_parquet(out_dir / META_NAME)
    meta = meta[meta["fetched"].astype(bool)].drop_duplicates("id", keep="last")
    meta["id"] = meta["id"].astype(str)
    return meta


def with_game_facts(markets: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    """The split's markets joined to their game facts, with sport, league, start and end."""
    cols = [
        "id",
        "sports_market_type",
        "game_start",
        "event_start",
        "event_finished",
        "event_score",
        "description",
    ]
    m = markets.merge(meta[cols], on="id", how="inner")
    m["sport"] = [sport_of(s) for s in m["event_slug"]]
    m["league"] = [league_of(s) for s in m["event_slug"]]
    m["start"] = m["event_start"].where(m["event_start"].notna(), m["game_start"])
    m["finished"] = m["event_finished"]
    valid = (
        m["finished"].notna()
        & m["start"].notna()
        & (m["finished"] > m["start"])
        & (m["finished"] <= m["closed_time"])
    )
    lag = (
        m["sport"].map(lambda sp: FALLBACK_LAG_MIN.get(sp, FALLBACK_LAG_DEFAULT_MIN))
        * 60.0
    )
    m["end"] = m["finished"].where(valid, m["closed_time"] - lag)
    m["end_kind"] = np.where(valid, WHISTLE, FALLBACK)
    return m


def is_universe(m: pd.DataFrame) -> pd.Series:
    return (
        m["sports_market_type"].isin(WINNER_TYPES)
        & m["start"].notna()
        & (m["end"] > m["start"])
    )


def funnel(markets: pd.DataFrame, meta: pd.DataFrame) -> dict[str, dict[str, int]]:
    """Per sport: game-winner markets in the split, and how many have a known start and end (structure only)."""
    m = with_game_facts(markets, meta)
    gw = m[m["sports_market_type"].isin(WINNER_TYPES)]
    out: dict[str, dict[str, int]] = {}
    for sport in SPORTS:
        g = gw[gw["sport"] == sport]
        ok = g[is_universe(g)]
        out[sport] = {
            "game_winner_markets": len(g),
            "no_start": int(g["start"].isna().sum()),
            "whistle_end": int((ok["end_kind"] == WHISTLE).sum()),
            "fallback_end": int((ok["end_kind"] == FALLBACK).sum()),
            "in_universe": len(ok),
            "events": int(ok["event_slug"].nunique()),
        }
    return out


def load_split(split: str, out_dir: Path = D.OUT) -> tuple[C.Dataset, dict[str, Any]]:
    meta = load_meta(out_dir)

    def select(markets: pd.DataFrame) -> pd.DataFrame:
        m = with_game_facts(markets, meta)
        return m[is_universe(m)].reset_index(drop=True)

    ds = C.Dataset.load(split, out_dir, select=select)
    fun = funnel(
        C.Dataset.eligible(pd.read_parquet(out_dir / "markets.parquet"), split), meta
    )
    for sport in SPORTS:
        fun[sport]["with_tape_50_fills"] = int((ds.markets["sport"] == sport).sum())
    return ds, fun


# ------------------------------------------------------------------------------------------------------------- trades
def allowed_outcomes(outcomes_json: Any, first_only: bool = False) -> tuple[int, ...]:
    """YES only in a Yes/No market; either side of a two-team market (``first_only``: the listed-first side, the
    side Polymarket US calls long)."""
    try:
        outs = [str(o).strip().lower() for o in json.loads(outcomes_json)]
    except (TypeError, ValueError):
        outs = []
    if outs == ["yes", "no"]:
        return (0,)
    if outs == ["no", "yes"]:
        return (1,)
    return (0,) if first_only else (0, 1)


def p6_trades(
    ds: C.Dataset,
    theta: float,
    first_only: bool = False,
    ticket: float = C.TICKET_USD,
    latency_s: int = C.LATENCY_S,
    ignore_end: bool = False,
) -> pd.DataFrame:
    """One trade per market: the first buyable print at or above ``theta`` for an allowed outcome while the game is
    in play, executed at the first buyable print for that outcome ``latency_s`` later (within EXEC_WINDOW_S and
    still in play); held to resolution; US taker fee in ``net``, polymarket.com's family fee in ``net_com``.
    ``ignore_end``: the window runs to closedTime instead of the game's end (only to measure how many first prints
    would have come after the final whistle; never a trading reading)."""
    rows: list[dict[str, Any]] = []
    for m in ds.markets.itertuples(index=False):
        tape = ds.tapes[m.id]
        ts = tape["ts"].to_numpy(dtype=float)
        p0 = tape["p0"].to_numpy(dtype=float)
        buy0 = tape["buy0"].to_numpy(dtype=bool)
        start, closed = float(m.start), float(m.closed_time)
        end_bound = closed if ignore_end else min(float(m.end), closed)
        window = (ts >= start) & (ts < end_bound)
        if not window.any():
            continue
        best: tuple[int, int] | None = None  # (signal index, outcome)
        for o in allowed_outcomes(m.outcomes, first_only):
            buyable = buy0 if o == 0 else ~buy0
            price = p0 if o == 0 else 1.0 - p0
            cand = window & buyable & (price >= theta - 1e-12)
            if cand.any():
                i = int(np.argmax(cand))
                if best is None or i < best[0]:
                    best = (i, o)
        if best is None:
            continue
        i, o = best
        buyable = buy0 if o == 0 else ~buy0
        price = p0 if o == 0 else 1.0 - p0
        t_signal = float(ts[i])
        row = {
            "id": m.id,
            "event": m.event_slug,
            "family": m.family,
            "sport": m.sport,
            "league": m.league,
            "question": m.question,
            "closed_time": closed,
            "end_date": m.end_date,
            "outcome": o,
            "t_signal": t_signal,
            "p_signal": float(price[i]),
            "day": datetime.fromtimestamp(closed, UTC).strftime("%Y-%m-%d"),
            "min_after_start": (t_signal - start) / 60.0,
            "min_before_end": (float(m.end) - t_signal) / 60.0,
            "end_kind": m.end_kind,
            "after_whistle": bool(m.end_kind == WHISTLE and t_signal >= float(m.end)),
            "score": m.event_score,
            "old_rule_bid_side": False,
        }
        j = int(np.searchsorted(ts, t_signal + latency_s, side="left"))
        while (
            j < len(ts)
            and ts[j] - t_signal <= C.EXEC_WINDOW_S
            and ts[j] < end_bound
            and not buyable[j]
        ):
            j += 1
        if j >= len(ts) or ts[j] - t_signal > C.EXEC_WINDOW_S or ts[j] >= end_bound:
            rows.append(
                {
                    **row,
                    "missed": True,
                    "t_exec": None,
                    "p_exec": None,
                    "won": None,
                    "net": None,
                    "net_com": None,
                    "fee_usd": None,
                    "pnl_usd": None,
                    "cents_per_contract": None,
                    "lock_h": None,
                }
            )
            continue
        p_exec = min(float(price[j]), C.MAX_PRICE)
        if p_exec <= 0.0:
            continue
        shares = ticket / p_exec
        fee_us = C.taker_fee(shares, p_exec, US_RATE)
        fee_com = C.taker_fee(shares, p_exec, float(m.rate))
        won = int(m.winner_index) == o
        pay = shares if won else 0.0
        pnl = pay - fee_us - ticket
        rows.append(
            {
                **row,
                "missed": False,
                "t_exec": float(ts[j]),
                "p_exec": p_exec,
                "won": bool(won),
                "net": pnl / ticket,
                "net_com": (pay - fee_com - ticket) / ticket,
                "fee_usd": fee_us,
                "pnl_usd": pnl,
                "cents_per_contract": 100.0
                * ((1.0 if won else 0.0) - p_exec - US_RATE * p_exec * (1.0 - p_exec)),
                "lock_h": (closed - float(ts[j])) / 3600.0,
            }
        )
    return pd.DataFrame(rows, columns=TRADE_COLUMNS)


# ----------------------------------------------------------------------------------------------------------- readings
def reading(trades: pd.DataFrame, split: str, B: int = C.BOOTSTRAP_B) -> dict[str, Any]:
    """core.summarize (US fee) plus the calibration gap's event-bootstrap CI, the polymarket.com-fee net and the
    loss rates."""
    s = C.summarize(trades, split, B=B)
    s.pop("by_family", None)
    s["signals"] = len(trades)
    filled = trades[~trades["missed"].astype(bool)] if len(trades) else trades
    if len(filled) == 0:
        s.update(
            {
                "gap_ci95": [None, None],
                "mean_net_com": None,
                "ci95_com": [None, None],
                "loss_rate": None,
                "implied_loss_rate": None,
                "cents_per_contract": None,
                "total_cents": 0.0,
                "median_min_before_end": None,
            }
        )
        return s
    groups = filled["event"].fillna(filled["id"]).to_numpy()
    won = filled["won"].to_numpy(dtype=bool).astype(float)
    p = filled["p_exec"].to_numpy(dtype=float)
    net_com = filled["net_com"].to_numpy(dtype=float)
    gap_ci = C.event_bootstrap_ci(won - p, groups, B=B)
    com_ci = C.event_bootstrap_ci(net_com, groups, B=B)
    s.update(
        {
            "gap_ci95": [gap_ci[0], gap_ci[1]],
            "mean_net_com": float(net_com.mean()),
            "ci95_com": [com_ci[0], com_ci[1]],
            "loss_rate": float(1.0 - won.mean()),
            "implied_loss_rate": float(1.0 - p.mean()),
            "cents_per_contract": float(filled["cents_per_contract"].mean()),
            "total_cents": float(filled["cents_per_contract"].sum()),
            "median_min_before_end": float(filled["min_before_end"].median()),
        }
    )
    return s


def _proven_loser(s: dict[str, Any] | None) -> bool:
    if not s or int(s.get("n_events") or 0) < MIN_EVENTS:
        return False
    gap_hi = (s.get("gap_ci95") or [None, None])[1]
    return gap_hi is not None and gap_hi < 0


def classify(
    sport: str, s: dict[str, Any] | None, s_fallback: dict[str, Any] | None = None
) -> str:
    """Amendment 5 (c): the TRAIN verdict of one sport at theta 0.97 from its games with a recorded end (``s``); its
    games without one (``s_fallback``, rough timing) can add a proven-loser block, never an ALLOWED."""
    s = s or {}
    if sport in NEVER_ALLOWED:
        return "NOT ALLOWED: mixed bucket of other sports (reported only)"
    if _proven_loser(s):
        return "BLOCKED: proven loser (loses more often than the price says)"
    if _proven_loser(s_fallback):
        return (
            "BLOCKED: proven loser (in its games without a recorded end; rough timing)"
        )
    if int(s.get("n_events") or 0) < MIN_EVENTS:
        return f"BLOCKED: no proof (fewer than {MIN_EVENTS} games with a recorded end)"
    if C.qualifies(s, min_n=1):
        return "ALLOWED"
    return "NOT ALLOWED: unknown (enough games, no proof either way)"


def by_group(
    trades: pd.DataFrame, key: str, split: str, B: int
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if len(trades) == 0:
        return out
    for name, g in trades.groupby(key):
        r = reading(g, split, B=B)
        if key == "league":
            r["sport"] = str(g["sport"].iloc[0])
        out[str(name)] = r
    return out


# ------------------------------------------------------------------------------------------------------------ tennis
_SET = re.compile(r"(\d+)\s*-\s*(\d+)")


def tennis_finish(score: Any) -> str:
    """'completed', 'unfinished' (retirement, default or abandonment: the last set is not a finished set, or the
    score says so) or 'unknown', from the event's score string (e.g. '6-4, 6-7(5-7), 7-6(7-3)')."""
    if not isinstance(score, str) or not score.strip():
        return "unknown"
    low = score.lower()
    if any(w in low for w in ("ret", "w/o", "walkover", "def", "abd", "abandon")):
        return "unfinished"
    sets = []
    for part in score.split(","):
        part = re.sub(r"\(.*?\)", "", part)
        mt = _SET.search(part)
        if mt:
            sets.append((int(mt.group(1)), int(mt.group(2))))
    if not sets:
        return "unknown"

    def done(a: int, b: int, last: bool) -> bool:
        hi, lo = max(a, b), min(a, b)
        if hi >= 6 and hi - lo >= 2:
            return True
        if hi == 7 and lo in (5, 6):
            return True
        return (
            last and hi >= 10 and hi - lo >= 2
        )  # a match tie-break in place of a third set

    won_a = sum(
        1 for k, (a, b) in enumerate(sets) if done(a, b, k == len(sets) - 1) and a > b
    )
    won_b = sum(
        1 for k, (a, b) in enumerate(sets) if done(a, b, k == len(sets) - 1) and b > a
    )
    a, b = sets[-1]
    if not done(a, b, True) or max(won_a, won_b) < 2:
        return "unfinished"
    return "completed"


def retirement_rules(markets: pd.DataFrame) -> dict[str, Any]:
    """What the rules text of the tennis game-winner markets says about a retirement (counts of the sentences)."""
    t = markets[markets["sport"] == "tennis"]
    counts: dict[str, int] = {}
    for d in t["description"].fillna(""):
        sent = [x.strip() for x in re.split(r"(?<=\.)\s+", d) if "retire" in x.lower()]
        key = sent[0] if sent else "(no sentence about retirement)"
        counts[key] = counts.get(key, 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:4]
    return {"markets": len(t), "sentences": [{"text": k, "markets": v} for k, v in top]}


def tennis_section(trades: pd.DataFrame) -> dict[str, Any]:
    f = (
        trades[(~trades["missed"].astype(bool)) & (trades["sport"] == "tennis")]
        if len(trades)
        else trades
    )
    out: dict[str, Any] = {}
    if len(f) == 0:
        return out
    kinds = f["score"].map(tennis_finish)
    for k in ("completed", "unfinished", "unknown"):
        g = f[kinds == k]
        out[k] = {
            "trades": len(g),
            "losses": int((~g["won"].astype(bool)).sum()) if len(g) else 0,
        }
    return out


# ------------------------------------------------------------------------------------------------------------ stages
def _cell(
    tr: pd.DataFrame, theta: float, selectable: bool, split: str, B: int, full: bool
) -> dict[str, Any]:
    """One cell: the games with a recorded end decide (``sports``); the games without one are read apart
    (``sports_fallback``)."""
    w = tr[tr["end_kind"] == WHISTLE]
    fb = tr[tr["end_kind"] == FALLBACK]
    return {
        "theta": theta,
        "selectable": selectable,
        "pooled": reading(w, split, B=B),
        "pooled_fallback": reading(fb, split, B=B),
        "sports": by_group(w, "sport", split, B),
        "sports_fallback": by_group(fb, "sport", split, B),
        "leagues": by_group(w, "league", split, B) if full else {},
        "leagues_fallback": by_group(fb, "league", split, B) if full else {},
        "tennis": {WHISTLE: tennis_section(w), FALLBACK: tennis_section(fb)}
        if full
        else {},
        "_trades": w,
    }


def postgame_share(ds: C.Dataset, theta: float = THETA) -> dict[str, Any]:
    """Games with a recorded end: how many first prints at >= theta after the start would have come AFTER the final
    whistle had the window run to closedTime (the buys the desk cannot make; why the end bound exists)."""
    tr = p6_trades(ds, theta, ignore_end=True)
    w = tr[tr["end_kind"] == WHISTLE]
    out: dict[str, Any] = {}
    for sport, g in [("all sports", w), *list(w.groupby("sport"))]:
        out[str(sport)] = {
            "signals": len(g),
            "after_whistle": int(g["after_whistle"].astype(bool).sum()),
            "share": float(g["after_whistle"].astype(bool).mean()) if len(g) else None,
        }
    return out


def _cells(ds: C.Dataset, split: str, B: int) -> dict[str, Any]:
    cells: dict[str, Any] = {}
    for theta in THETAS:
        cells[f"theta{theta:g}"] = _cell(
            p6_trades(ds, theta), theta, theta == THETA, split, B, theta == THETA
        )
    cells["theta0.97|first-listed side only"] = _cell(
        p6_trades(ds, THETA, first_only=True), THETA, False, split, B, False
    )
    return cells


def _record(
    split: str, stage: str, cells: dict[str, Any], pooled_key: str | None = None
) -> int:
    n_total = C.trials_count()
    for ck, c in cells.items():
        for sport, s in c["sports"].items():
            n_total = C.record_run(
                {
                    "lab": "lab4",
                    "hyp": HYP,
                    "cell": f"{ck}|{sport}",
                    "split": split,
                    "stage": stage,
                    "n": s["n"],
                    "mean_net": s["mean_net"],
                    "kind": "cell" if c["selectable"] else "reported",
                }
            )
        if pooled_key:
            pooled = c.get("pooled_allowed") or c["pooled"]
            n_total = C.record_run(
                {
                    "lab": "lab4",
                    "hyp": HYP,
                    "cell": f"{ck}|{pooled_key}",
                    "split": split,
                    "stage": stage,
                    "n": pooled["n"],
                    "mean_net": pooled["mean_net"],
                    "kind": "cell" if c["selectable"] else "reported",
                }
            )
    return n_total


def _strip(cells: dict[str, Any]) -> dict[str, Any]:
    return {
        k: {kk: vv for kk, vv in v.items() if kk != "_trades"} for k, v in cells.items()
    }


def run_train(
    out_dir: Path = D.OUT, B: int = C.BOOTSTRAP_B, here: Path = HERE
) -> dict[str, Any]:
    split = "train"
    ds, fun = load_split(split, out_dir)
    _check_coverage(ds)
    cells = _cells(ds, split, B)
    sel = cells[f"theta{THETA:g}"]
    verdicts = {
        sport: classify(
            sport, sel["sports"].get(sport), sel["sports_fallback"].get(sport)
        )
        for sport in SPORTS
    }
    allowed = [s for s, v in verdicts.items() if v == "ALLOWED"]
    blocked = [s for s, v in verdicts.items() if v.startswith("BLOCKED")]
    n_total = _record(split, "train", cells, pooled_key="all sports (context)")
    decision = (
        f"ALLOWED on TRAIN: {', '.join(allowed)} (pooled set goes to VAL)"
        if allowed
        else "NO SPORT ALLOWED on TRAIN (no sport shows proof); VAL not needed"
    )
    doc = _doc(split, "train", ds, fun, cells, n_total, decision)
    doc.update({"verdicts": verdicts, "allowed": allowed, "blocked": blocked})
    doc["tennis_rules"] = retirement_rules(ds.markets)
    doc["postgame_share"] = postgame_share(ds)
    _write(here, "train", doc)
    return doc


def run_holdout(
    stage: str, out_dir: Path = D.OUT, B: int = C.BOOTSTRAP_B, here: Path = HERE
) -> dict[str, Any]:
    split = stage
    C.check_split_allowed(split)
    prev_name = "train" if stage == "val" else "val"
    prev_path = here / f"{prev_name}.json"
    prev = json.loads(prev_path.read_text()) if prev_path.exists() else {}
    allowed = list(prev.get("allowed") or [])
    if stage == "test":
        if (here / "test.json").exists():
            raise RuntimeError(
                "P6 TEST has been read once already (one look, PLAN §1); refusing a second look"
            )
        if not str(prev.get("decision", "")).startswith("PASS on VAL"):
            allowed = []
    if not allowed:
        doc = {
            "hyp": HYP,
            "title": TITLE,
            "stage": stage,
            "split": split,
            "utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "decision": f"NOT RUN: {prev_name.upper()} passed no sport",
            "allowed": [],
            "prereg_sha256": R.prereg_sha256(),
            "n_trials_total": C.trials_count(),
        }
        _write(here, stage, doc)
        return doc
    ds, fun = load_split(split, out_dir)
    _check_coverage(ds)
    cells = _cells(ds, split, B)
    pooled: dict[str, Any] = {}
    for ck, c in cells.items():
        tr = c["_trades"]
        a = tr[tr["sport"].isin(allowed)]
        s = reading(a, split, B=B)
        pooled[ck] = {
            "summary": s,
            "placebo": C.calibration_placebo(a, draws=B) if c["selectable"] else None,
        }
        c["pooled_allowed"] = s
    main = pooled[f"theta{THETA:g}"]
    beats = (main["placebo"] or {}).get("real_percentile")
    ok = (
        C.qualifies(main["summary"], MIN_N_POOLED)
        and beats is not None
        and beats >= PLACEBO_PCT
    )
    name = "VAL" if stage == "val" else "TEST"
    decision = (
        f"PASS on {name} (allowed set: {', '.join(allowed)})"
        if ok
        else f"FAIL on {name} (allowed set: {', '.join(allowed)})"
    )
    n_total = _record(split, stage, cells, pooled_key="allowed set")
    doc = _doc(split, stage, ds, fun, cells, n_total, decision)
    doc.update(
        {
            "allowed": allowed if ok else [],
            "allowed_tested": allowed,
            "pooled_allowed": pooled,
        }
    )
    _write(here, stage, doc)
    return doc


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=TRADE_COLUMNS)


def _check_coverage(ds: C.Dataset) -> None:
    cov = ds.coverage
    if cov.get("share", 1.0) < 1.0 and os.environ.get("LAB4_ALLOW_PARTIAL") != "1":
        raise RuntimeError(
            f"{ds.split.upper()} tapes incomplete: {cov['with_tape']} of {cov['eligible']} P6 markets have a tape "
            "(Amendment 3 refuses a partial run)"
        )


def _doc(
    split: str,
    stage: str,
    ds: C.Dataset,
    fun: dict[str, Any],
    cells: dict[str, Any],
    n_total: int,
    decision: str,
) -> dict[str, Any]:
    desk = {}
    for code, label in DESK_LEAGUES.items():
        desk[code] = {
            "label": label,
            "markets_in_universe": int((ds.markets["league"] == code).sum()),
        }
    return {
        "hyp": HYP,
        "title": TITLE,
        "stage": stage,
        "split": split,
        "utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "decision": decision,
        "prereg_sha256": R.prereg_sha256(),
        "plan_version": PLAN_VERSION,
        "coverage": ds.coverage,
        "funnel": fun,
        "n_markets": len(ds.markets),
        "n_events": int(ds.markets["event_slug"].nunique()),
        "cells": _strip(cells),
        "desk_leagues": desk,
        "n_trials_total": n_total,
    }


def _write(here: Path, stage: str, doc: dict[str, Any]) -> None:
    here.mkdir(parents=True, exist_ok=True)
    (here / f"{stage}.json").write_text(
        json.dumps(doc, indent=1, sort_keys=True, default=_jsonable) + "\n"
    )
    (here / f"{stage}.md").write_text(render_md(doc))
    R._results_md(here.parent)


def _jsonable(v: Any) -> Any:
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return str(v)


# ---------------------------------------------------------------------------------------------------------- markdown
def _f(v: Any, nd: int = 3) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "-"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _pct(v: Any) -> str:
    return "-" if v is None else f"{100.0 * float(v):.1f} %"


def _ci(ci: Any, nd: int = 4) -> str:
    ci = ci or [None, None]
    return f"[{_f(ci[0], nd)}, {_f(ci[1], nd)}]"


HEAD = (
    "| {k} | buys | games | missed | win rate | mean price | gap | loss rate (price says) | net per $ (US fee) | "
    "CI95 (games) | gap CI95 | net per $ (.com fee) | cents per contract | losses | worst case (rule of 3) |{v}"
)


def _row(name: str, s: dict[str, Any], verdict: str | None = None) -> str:
    return (
        f"| {name} | {s['n']} | {s.get('n_events', 0)} | {s['missed']} | {_pct(s['win_rate'])} | "
        f"{_f(s['mean_p_exec'])} | {_f(s['calibration_gap'], 4)} | {_pct(s.get('loss_rate'))} "
        f"({_pct(s.get('implied_loss_rate'))}) | {_f(s['mean_net'], 4)} | {_ci(s['ci95'])} | "
        f"{_ci(s.get('gap_ci95'))} | {_f(s.get('mean_net_com'), 4)} | {_f(s.get('cents_per_contract'), 2)} | "
        f"{s.get('losses', 0)} | {_f(s.get('worst_case_net'), 4)} |"
        + (f" {verdict} |" if verdict is not None else "")
    )


def _table(
    title: str,
    rows: dict[str, dict[str, Any]],
    order: list[str],
    key: str,
    verdicts: dict[str, str] | None,
) -> list[str]:
    lines = [f"### {title}", ""]
    lines.append(HEAD.format(k=key, v=" verdict |" if verdicts is not None else ""))
    lines.append("|" + "---|" * (15 + (1 if verdicts is not None else 0)))
    for name in order:
        s = rows.get(name)
        if s is None:
            if verdicts is not None:
                lines.append(
                    f"| {name} | 0 | 0 | 0 | - | - | - | - | - | - | - | - | - | 0 | - | {verdicts.get(name, '-')} |"
                )
            continue
        lines.append(
            _row(name, s, verdicts.get(name, "-") if verdicts is not None else None)
        )
    lines.append("")
    return lines


def render_md(doc: dict[str, Any]) -> str:
    stage = doc["stage"]
    lines = [
        f"# P6 {doc['title']}: {stage.upper()} ({doc['split']}, {doc.get('plan_version', PLAN_VERSION)})",
        "",
        f"Run {doc['utc']}; PLAN.md sha256 {doc['prereg_sha256'][:12]}; trials so far across labs 2-4: "
        f"{doc['n_trials_total']}.",
        "",
        f"**Decision:** {doc['decision']}",
        "",
    ]
    if "cells" not in doc:
        lines.append("Nothing was computed on this split (Amendment 5 (d)/(e)).")
        return "\n".join(lines) + "\n"
    sel = doc["cells"][f"theta{THETA:g}"]
    verdicts = doc.get("verdicts")
    lines += _plain(doc)
    cov = doc.get("coverage") or {}
    lines += [
        "## Universe",
        "",
        f"Game-winner markets of sports with a known start and a tape: {doc['n_markets']} markets with >= 50 fills "
        f"in {doc['n_events']} games; tape coverage {cov.get('with_tape')} of {cov.get('eligible')} "
        f"({100 * float(cov.get('share') or 0):.1f} %). 'recorded end' = Gamma's finishedTimestamp of the game "
        "(these games decide); 'fallback end' = no valid finishedTimestamp, the window ends at closedTime minus the "
        "sport's resolution lag (rough timing: read apart, can only add a block).",
        "",
        "| sport | game-winner markets | no start time | recorded end | fallback end | games | with >= 50 fills |",
        "|---|---|---|---|---|---|---|",
    ]
    for sport in SPORTS:
        f = doc["funnel"].get(sport, {})
        lines.append(
            f"| {sport} | {f.get('game_winner_markets', 0)} | {f.get('no_start', 0)} | {f.get('whistle_end', 0)} | "
            f"{f.get('fallback_end', 0)} | {f.get('events', 0)} | {f.get('with_tape_50_fills', 0)} |"
        )
    lines.append("")
    pg = doc.get("postgame_share") or {}
    if pg:
        allp = pg.get("all sports", {})
        lines += [
            "Why the window stops at the final whistle: in the games with a recorded end, "
            f"{allp.get('after_whistle', 0)} of {allp.get('signals', 0)} first prints at >= 0.97 after the start "
            f"({_pct(allp.get('share'))}) would have come AFTER the game was over had the window run to the "
            "market's resolution; those are buys the desk cannot make (it stops at a final period) and they almost "
            "always win. Per sport: "
            + "; ".join(
                f"{k} {_pct(v.get('share'))}"
                for k, v in pg.items()
                if k != "all sports" and v.get("signals")
            )
            + ".",
            "",
        ]
    lines += _table(
        "Per sport, theta 0.97, games with a recorded end (the desk's rule; this table decides)",
        sel["sports"],
        list(SPORTS),
        "sport",
        verdicts if verdicts is not None else {s: "reported" for s in SPORTS},
    )
    lines.append(_row("**all sports (context)**", sel["pooled"]))
    lines.append("")
    lines += _table(
        "Per sport, theta 0.97, games WITHOUT a recorded end (fallback end; can only add a block)",
        sel.get("sports_fallback") or {},
        [sp for sp in SPORTS if sp in (sel.get("sports_fallback") or {})],
        "sport",
        None,
    )
    lines.append(_row("**all sports (fallback end)**", sel["pooled_fallback"]))
    lines.append("")
    if stage != "train" and "pooled_allowed" in doc:
        pa = doc["pooled_allowed"][f"theta{THETA:g}"]
        p = pa.get("placebo") or {}
        lines += [
            f"### The pooled ALLOWED set ({', '.join(doc.get('allowed_tested') or [])}) on {stage.upper()}",
            "",
            HEAD.format(k="set", v=""),
            "|" + "---|" * 15,
            _row("allowed set", pa["summary"]),
            "",
            f"Calibration placebo (outcomes redrawn at the price paid, 2000 draws): mean {_f(p.get('mean'), 4)}, "
            f"95th percentile {_f(p.get('p95'), 4)}; the real mean sits at percentile "
            f"{_f(p.get('real_percentile'), 1)}. Bar: n >= {MIN_N_POOLED}, mean > 0, CI95 lower > 0, the loss "
            "guards of Amendment 3, and the real mean at or above the placebo's 95th percentile.",
            "",
        ]
    for ck in ("theta0.98", "theta0.99", "theta0.97|first-listed side only"):
        c = doc["cells"].get(ck)
        if c:
            lines += _table(
                f"Per sport, {ck}, games with a recorded end (reported only)",
                c["sports"],
                list(SPORTS),
                "sport",
                None,
            )
            lines.append(_row("**all sports**", c["pooled"]))
            lines.append("")
    for key, title in (
        ("leagues", "games with a recorded end"),
        ("leagues_fallback", "games without a recorded end (fallback end)"),
    ):
        leagues = sel.get(key) or {}
        order = sorted(leagues, key=lambda k, lg=leagues: (-lg[k]["n"], k))
        lines += [
            f"### Per league, theta 0.97, {title} (reported only; league = the event slug's first word)",
            "",
        ]
        lines.append(HEAD.format(k="league (sport)", v=""))
        lines.append("|" + "---|" * 15)
        for k in order:
            lines.append(_row(f"{k} ({leagues[k].get('sport')})", leagues[k]))
        lines.append("")
    lines += _tennis_md(doc)
    lines += ["### The real desk's losing leagues: does this history cover them?", ""]
    lines += [
        "| league code | what it is | game-winner markets in this split's universe |",
        "|---|---|---|",
    ]
    for code, d in (doc.get("desk_leagues") or {}).items():
        lines.append(f"| {code} | {d['label']} | {d['markets_in_universe']} |")
    lines += [
        "",
        "## How to read this",
        "",
        "One buy per market: the first price a buyer could actually pay (a buy print, Amendment 3) at or above the "
        "threshold while the game was in play (from Gamma's startTime of the game to its finishedTimestamp), filled "
        "at the next buyable print 10 seconds later; the YES side only in a Yes/No market, either team in a two-team "
        "market. 'gap' = win rate minus the price paid (below zero: the favourite lost more often than its price "
        "said). 'net per $' = profit per dollar at risk after Polymarket US's taker fee (0.0695 x shares x p x "
        "(1 - p)); the '.com fee' column uses polymarket.com's own fee family (sports 0.05, NFL / college football "
        "0), lower than the US fee, so the US column is the stricter one. 'cents per contract' = the same in cents "
        "per one-dollar contract, the desk's ticket. CI95 by resampling games, not markets (a game's markets are one "
        "draw). 'worst case' = the rule-of-three bound (1 - 3/n) x mean win - 3/n. The tape has no order book: the "
        "desk's 'bid and ask within 0.03' check cannot be applied, a buy print stands in for the ask; startTime is "
        "the scheduled start, so a delayed start can let a pre-match print in. History is polymarket.com, markets "
        "with >= $20,000 volume (lab 4's collection); Polymarket US lists many smaller leagues that are not in it. "
        "Nothing here is a live trade.",
        "",
    ]
    return "\n".join(lines) + "\n"


def _plain(doc: dict[str, Any]) -> list[str]:
    sel = doc["cells"][f"theta{THETA:g}"]
    out = ["## In plain words", ""]
    verdicts = doc.get("verdicts")
    if verdicts is not None:
        allowed = doc.get("allowed") or []
        groups = [
            (
                "Sports where history shows the 97c+ in-play favourite reliably pays after the fee",
                allowed,
            ),
            (
                "Sports where it loses more often than the price says (proven on history)",
                [s for s, v in verdicts.items() if v.startswith("BLOCKED: proven")],
            ),
            (
                "Sports with too few games in history to tell (blocked for real money)",
                [s for s, v in verdicts.items() if v.startswith("BLOCKED: no proof")],
            ),
            (
                "Sports with enough games but no proof either way (not allowed for real money)",
                [
                    s
                    for s, v in verdicts.items()
                    if v.startswith("NOT ALLOWED: unknown")
                ],
            ),
        ]
        for label, names in groups:
            out.append(f"- {label}: " + (", ".join(names) if names else "none") + ".")
        for sport in SPORTS:
            s = sel["sports"].get(sport)
            if s and s["n"]:
                out.append(
                    f"  - {sport}: {s['n']} buys in {s['n_events']} games, lost {s['losses']} "
                    f"({_pct(s.get('loss_rate'))}; the price said {_pct(s.get('implied_loss_rate'))}); "
                    f"{_f(s.get('cents_per_contract'), 2)} cents per contract on average."
                )
    else:
        out.append(f"- {doc['decision']}.")
    out.append("")
    return out


def _tennis_md(doc: dict[str, Any]) -> list[str]:
    sel = doc["cells"][f"theta{THETA:g}"]
    t = sel.get("tennis") or {}
    rules = doc.get("tennis_rules") or {}
    out = ["### Tennis: retirements", ""]
    if rules:
        out.append(
            f"Rules text of the {rules.get('markets', 0)} tennis game-winner markets in this split: the sentence about "
            "a retirement and how many markets carry it:"
        )
        out.append("")
        for r in rules.get("sentences", []):
            out.append(f'- ({r["markets"]} markets) "{r["text"]}"')
        out.append("")
    if any(t.values()):
        out.append(
            "Tennis buys at 0.97 by how the match ended (from the event's final score; 'unfinished' = the last set "
            "is not a finished set or the score says retired / walkover: a heuristic, not the official record):"
        )
        out.append("")
        out.append("| games | match ended | buys | losses |")
        out.append("|---|---|---|---|")
        for kind, tk in t.items():
            for k in ("completed", "unfinished", "unknown"):
                if k in tk:
                    out.append(
                        f"| {kind} | {k} | {tk[k]['trades']} | {tk[k]['losses']} |"
                    )
        out.append("")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lab 4 P6: sport by sport")
    ap.add_argument("--stage", choices=["train", "val", "test"], required=True)
    ap.add_argument("--B", type=int, default=C.BOOTSTRAP_B)
    a = ap.parse_args(argv)
    doc = run_train(B=a.B) if a.stage == "train" else run_holdout(a.stage, B=a.B)
    print(f"P6 {a.stage}: {doc['decision']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
