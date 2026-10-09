"""Z4: theme momentum -- buy a fresh graduate at g + 30 min when other deployers' coins that share a theme token with
it graduated in the previous N hours and did well (outcomes resolved before t). The inverse, theme EXHAUSTION ("new
members of a theme that just ran are exit liquidity"), is tested as a veto on the same observable.

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/Z4/PREREG.md``.

Every FEATURE is read through :class:`common.AsOf` (cutoff tau = t - 20 s). The registry is cross-coin (like Y1):

* **Structure** (names, never outcomes): every graduate of the stage's structural pool, its ``name`` / ``symbol`` /
  ``creator`` read through AsOf at g + 20 s, used only for a coin with g_p < g of the coin being decided (< tau).
* **Records** (outcomes of OTHER coins): r(p) = AsOf(p, t_end).price / AsOf(p, t_ref).price - 1 for a usable earlier
  graduate p, t_ref = first grid time >= g_p + 420 s, t_end = t_ref + 30 min. It counts at decision t only when
  t_end <= t (every bar it reads ended before tau) and g_p < g; never the traded mint. History splits per stage are
  fixed (:data:`HISTORY_SPLITS`).
* **Members** of coin i at t: structural graduates with g_p in [t - N, g_i), a known creator != i's creator, and a
  shared theme token (:func:`theme_tokens`: NFKD-folded letter/digit runs and their camelCase parts, stop words
  removed). ``heat`` = mean record of the 3 most recent resolved members.

Entry (PREREG 4): one decision at the first grid time >= g + 30 min. MOM(N, theta) enters an alive eligible member
with heat >= theta; HOST(N) enters every alive eligible member. EXH (PREREG 6): on HOST trades, flag = heat >= 0.25;
PLAN 3.5 veto bar via ``common.verdict_veto``. Exits: 60-minute time exit, -50 % stop, worst fills, next-bar exits.

CLI::

    python research/lab2/z4.py --debug                         # census TRAIN third: counts only, no returns
    python research/lab2/z4.py --stage train [--allow-partial] [--rerun-reason TEXT]
    python research/lab2/z4.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/z4.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/z4.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/z4.py --stage final
    python research/lab2/z4.py --stage val --check             # prerequisites only

Each stage writes ``Z4/<stage>.json`` and ``Z4/<stage>.md`` and REFUSES to run when its prerequisites are missing
(no VAL without the written shortlists, TEST / CONFIRM / FINAL once each and only for live branches, never CONFIRM or
FINAL before TEST, PLAN 8 data gates V1-V4, PREREG frozen after the first official TRAIN run).
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import math
import os
import re
import sys
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import common as C  # noqa: E402

VERSION = "z4-v1"
OUT_DIR = HERE / "Z4"
HYP, HYP_HOST, HYP_EXH = "Z4", "Z4-host", "Z4-exh"
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"debug": "final_train", "train": "train", "val": "val", "test": "test", "confirm": "confirm",
               "final": "final"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}
# PREREG 2.1: outcome records come only from splits earlier in time and already open at the stage
HISTORY_SPLITS = {"debug": ("final_train",), "train": ("train",), "val": ("train", "val"),
                  "test": ("train", "val", "test"), "confirm": ("confirm",),
                  "final": ("train", "val", "test", "final_train", "final_val", "final_test")}
BRANCHES = ("mom", "exh")

# =========================================================================== pre-registered constants (PREREG 2-9)
DEC_AGE_S = 1800.0                  # the one decision: first grid time >= g + 30 min
REF_AGE_S = float(C.AGENT_WINDOW_S)  # a record starts post-BOOST (first grid time >= g + 420 s)
H_REC_S = 1800.0                    # a record is the next 30 minutes' mid change
REC_K = 3                           # heat = mean of the 3 most recent resolved members
N_GRID_H = (3, 12)                  # lookback N in hours
THETA_GRID = (0.25, 1.0)            # MOM heat thresholds
HOT_THETA = 0.25                    # the exhaustion flag (the lower theta; no new threshold)
CROWD_K = 3                         # diagnostic: k >= 3 members = crowded theme
STOP_PCT = 0.50                     # catastrophe stop
HOLD_S = 3600.0                     # time exit after the entry fill
EXIT_BY_AGE_S = 178 * 60.0          # registered deadline inside the B2 window (never binds)
SIZE_USD = 20.0
INSTANT_DELAY_S = 5.0               # diagnostic: graduated <= 5 s after creation
MIN_TOKEN_ASCII, MIN_TOKEN_OTHER = 3, 2
# selection and verdict bars
TRAIN_MIN_TRADES, TRAIN_MIN_KEYS = 30, 10
VAL_MIN_SIGN, VAL_MIN_TRADES = 5, 15
VETO_MIN = int(C.PLAN_MIN["veto_val_flagged"])        # 30 flagged and 30 unflagged
TEST_NO_EVIDENCE_N = 5
PASS_MIN_MEAN = 0.03                                  # PLAN 3.5 item 2
PASS_MIN_TRADES, PASS_MIN_KEYS, PASS_MIN_PROFIT_KEYS = 60, 10, 5
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED")
FINAL_JUDGED = ("final_val", "final_test")
FINAL_DESIGN = "final_train"

# PREREG 2.3: frozen a priori (generic English, crypto boilerplate, hype words, launch venues); never from data
STOPWORDS = frozenset("""
the and for but not you your are was were will can has have had with this that these those from into onto over
all any its his her him she they them our out off get got just now new one two who why what how when where here
there than then very more most much many some only also too yes let lets like make made back big top best real
true first last next ever never every day today time year world life way thing really still
coin coins token tokens sol solana crypto pump pumpfun pumpswap fun meme memes memecoin memecoins inu official
community cto dao launch swap dex chain onchain mint holder holders airdrop presale wallet
moon lambo wagmi ngmi degen gem gems send based alpha ath rich money cash buy sell hold hodl bull bear
fomo family bags bonk letsbonk raydium jupiter
""".split())
STOP_SHA1 = hashlib.sha1(" ".join(sorted(STOPWORDS)).encode()).hexdigest()[:12]

FILL = C.FillConfig(exit_delay_bars=1)  # worst fills; every triggered exit fills in the next bar (PREREG 5)
STRESS = {"costs_x1.5": FILL.stressed(1.5), "rent_0.22": dataclasses.replace(FILL, rent_usd=0.22),
          "same_bar_exits": C.FillConfig()}

FIXED = {
    "version": VERSION, "dec_age_s": DEC_AGE_S, "ref_age_s": REF_AGE_S, "h_rec_s": H_REC_S, "rec_k": REC_K,
    "record": "mid change t_ref -> t_ref + 30 min, t_ref = first grid time >= g + 420 s; usable members, resolved "
              "(t_end <= t), g_p < g",
    "members": "structural graduates with g_p in [t - N, g), known creator != own creator, shared theme token",
    "tokens": "NFKD fold, letter/digit runs + camelCase/digit parts, casefold, >= 3 chars ASCII / >= 2 other, "
              "not all digits, not a stop word",
    "stopwords_sha1": STOP_SHA1, "hot_theta": HOT_THETA, "crowd_k": CROWD_K,
    "history_splits": {k: list(v) for k, v in HISTORY_SPLITS.items()}, "stop_pct": STOP_PCT, "hold_s": HOLD_S,
    "exit_by_age_s": EXIT_BY_AGE_S, "size_usd": SIZE_USD, "alive": "AsOf.alive() defaults",
    "placebo": "eligible-member stratum at the draw's time, alive; unmatched control reported",
    "fill": "common.FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar stops, exits in the next bar",
}


def make_params(rule: str, n_h: int, theta: float | None = None) -> dict:
    if n_h not in N_GRID_H:
        raise ValueError(f"lookback {n_h!r} h not in {N_GRID_H}")
    base = {**FIXED, "lookback_h": int(n_h), "lookback_s": float(n_h) * 3600.0}
    if rule == "mom":
        if theta not in THETA_GRID:
            raise ValueError(f"theta {theta!r} not in {THETA_GRID}")
        return {**base, "rule": "mom", "theta": float(theta)}
    if rule == "host":
        return {**base, "rule": "host"}
    raise ValueError(f"unknown rule {rule!r}")


GRID_MOM = [make_params("mom", n, th) for n in N_GRID_H for th in THETA_GRID]
GRID_HOST = [make_params("host", n) for n in N_GRID_H]
GRID = GRID_MOM + GRID_HOST
VETO_RULE = f"heat >= {HOT_THETA} at the host entry (tag 'hot')"


def veto_params(n_h: int) -> dict:
    return {"version": VERSION, "test": "veto", "flag": VETO_RULE, "host": make_params("host", n_h)}


DECL = {"uses_wallet_reputation": True, "reputation_excludes_traded_coin": True, "uses_organic_flow": False,
        "uses_truncated_windows": False, "uses_current_state_fields": False,
        "note": "the 'reputation' is a theme token's record built from OTHER coins' resolved outcomes"}


class Z4Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing (or a stop rule fired)."""


def config_key(p: Mapping[str, Any]) -> str:
    return f"mom|N{p['lookback_h']}h|th{p['theta']:g}" if p["rule"] == "mom" else f"host|N{p['lookback_h']}h"


def hyp_of(p: Mapping[str, Any]) -> str:
    return HYP if p["rule"] == "mom" else HYP_HOST


def host_role(n_h: int) -> str:
    return f"host_{int(n_h)}h"


# =========================================================================== small helpers


def _nz(v: Any) -> Any:
    """NULL-like -> None (empty strings and NaN included); NULL is never a value."""
    if v is None or v is pd.NA:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, str) and not v.strip():
        return None
    return v


def grid_time_from(cd: C.CoinData, t_min: float) -> float:
    """The first decision-grid time (minute boundary + 20 s) at or after ``t_min``."""
    j = math.ceil((t_min - C.GRID_OFFSET_S - cd.m0) / 60.0 - 1e-9)
    return float(cd.m0 + 60 * j + C.GRID_OFFSET_S)


def _rank_avg(x: np.ndarray) -> np.ndarray:
    order = np.argsort(x, kind="mergesort")
    sx = x[order]
    r = np.empty(len(x))
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and sx[j + 1] == sx[i]:
            j += 1
        r[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return r


def spearman(a: Sequence[float], b: Sequence[float]) -> float | None:
    """Spearman rank correlation (ties averaged); None when undefined (< 3 pairs or a constant series)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if len(a) < 3:
        return None
    ra, rb = _rank_avg(a), _rank_avg(b)
    sa, sb = ra.std(), rb.std()
    if sa == 0 or sb == 0:
        return None
    return float(((ra - ra.mean()) * (rb - rb.mean())).mean() / (sa * sb))


# =========================================================================== theme tokens (PREREG 2.3)

_RUN_RE = re.compile(r"[^\W_]+")
_PART_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+|[^\x00-\x7f]+")


def _fold(s: str) -> str:
    """NFKD and drop combining marks: accents fold to ASCII (Pokémon -> Pokemon), full-width letters to ASCII."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))


def _keep(tok: str) -> bool:
    if not tok or tok.isdigit() or tok in STOPWORDS:
        return False
    return len(tok) >= (MIN_TOKEN_ASCII if tok.isascii() else MIN_TOKEN_OTHER)


def theme_tokens(name: Any, symbol: Any) -> frozenset:
    """Theme tokens of a coin from its name and symbol (NULL / empty -> nothing)."""
    out: set[str] = set()
    for s in (name, symbol):
        s = _nz(s)
        if s is None:
            continue
        for run in _RUN_RE.findall(_fold(str(s))):
            cands = {run.casefold()}
            cands.update(p.casefold() for p in _PART_RE.findall(run))
            out.update(t for t in cands if _keep(t))
    return frozenset(out)


def symbol_norm(symbol: Any) -> str | None:
    """Case-folded alphanumeric symbol, for the exact-clone diagnostic."""
    s = _nz(symbol)
    if s is None:
        return None
    n = "".join(ch for ch in _fold(str(s)).casefold() if ch.isalnum())
    return n or None


# =========================================================================== the registry (cross-coin, causal)


@dataclass(frozen=True)
class Member:
    mint: str
    g: float
    creator: str
    tokens: frozenset
    sym: str | None


@dataclass
class Themes:
    """Structure only: token -> structural graduates carrying it, sorted by g. A query sees g < g_i (< tau) only."""

    by_token: dict[str, tuple[np.ndarray, list[Member]]] = field(default_factory=dict)
    n_coins: int = 0
    n_named: int = 0
    first_g: float | None = None

    @classmethod
    def from_rows(cls, rows: Iterable[Mapping[str, Any]]) -> "Themes":
        by: dict[str, list[Member]] = defaultdict(list)
        seen: set[str] = set()
        first, named = None, 0
        for r in rows:
            if r["mint"] in seen:
                continue
            seen.add(r["mint"])
            g = float(r["g"])
            first = g if first is None else min(first, g)
            cr = _nz(r.get("creator"))
            toks = theme_tokens(r.get("name"), r.get("symbol"))
            if cr is None or not toks:
                continue
            named += 1
            m = Member(mint=str(r["mint"]), g=g, creator=str(cr), tokens=toks, sym=symbol_norm(r.get("symbol")))
            for tok in toks:
                by[tok].append(m)
        packed = {}
        for tok, lst in by.items():
            lst.sort(key=lambda m: (m.g, m.mint))
            packed[tok] = (np.array([m.g for m in lst], float), lst)
        return cls(by_token=packed, n_coins=len(seen), n_named=named, first_g=first)

    def members(self, tokens: Iterable[str], lo: float, hi: float, mint: str, creator: str) -> dict[str, list[Member]]:
        """token -> members with g in [lo, hi), another (known) creator, never ``mint``."""
        out: dict[str, list[Member]] = {}
        for tok in tokens:
            ev = self.by_token.get(tok)
            if ev is None:
                continue
            gs, lst = ev
            a, b = int(np.searchsorted(gs, lo, side="left")), int(np.searchsorted(gs, hi, side="left"))
            sel = [m for m in lst[a:b] if m.mint != mint and m.creator != creator]
            if sel:
                out[tok] = sel
        return out


@dataclass(frozen=True)
class Prior:
    """The outcome record of one graduate (a LABEL of that coin, used only as history for later coins)."""

    mint: str
    g: float
    t_ref: float
    t_end: float
    ret: float


def record_window(cd: C.CoinData) -> tuple[float, float]:
    t_ref = grid_time_from(cd, cd.g + REF_AGE_S)
    return t_ref, t_ref + H_REC_S


def prior_of(ds: C.Dataset, mint: str) -> Prior | None:
    """r(p) through AsOf at t_ref and t_end (PREREG 2.2); None when the window leaves the data or a price is bad."""
    cd = ds.coin(mint)
    t_ref, t_end = record_window(cd)
    if t_end - C.DECISION_LAG_S > cd.m0 + 60 * C.N_BARS:
        return None
    p0, p1 = ds.asof(mint, t_ref).price, ds.asof(mint, t_end).price
    if not (np.isfinite(p0) and np.isfinite(p1) and p0 > 0 and p1 > 0):
        return None
    return Prior(mint=mint, g=cd.g, t_ref=t_ref, t_end=t_end, ret=float(p1 / p0 - 1.0))


@dataclass
class Records:
    by_mint: dict[str, Prior] = field(default_factory=dict)
    n_coins: int = 0

    @classmethod
    def from_datasets(cls, datasets: Iterable[C.Dataset]) -> "Records":
        by: dict[str, Prior] = {}
        seen: set[str] = set()
        for ds in datasets:
            for m in ds.mints:
                if m in seen:
                    continue
                seen.add(m)
                p = prior_of(ds, m)
                if p is not None:
                    by[m] = p
        return cls(by_mint=by, n_coins=len(seen))


@dataclass
class Registry:
    themes: Themes
    records: Records
    _cache: dict = field(default_factory=dict, repr=False)

    def state(self, snap: C.AsOf, lookback_s: float) -> dict:
        """status: unknown | solo | pending | eligible (PREREG 3), with heat, crowding k, primary key, exact clone."""
        ck = (snap.mint, float(snap.t), float(lookback_s))
        hit = self._cache.get(ck)
        if hit is not None:
            return hit
        cr = _nz(snap.get("creator"))
        toks = theme_tokens(snap.get("name"), snap.get("symbol"))
        if cr is None or not toks:
            out = {"status": "unknown", "k": 0}
            self._cache[ck] = out
            return out
        lo = snap.t - float(lookback_s)
        by_tok = self.themes.members(toks, lo, snap.g, snap.mint, str(cr))
        mem: dict[str, Member] = {}
        for lst in by_tok.values():
            for m in lst:
                mem[m.mint] = m
        k = len(mem)
        first_g = self.themes.first_g
        warm = bool(first_g is not None and lo < first_g)
        if k == 0:
            out = {"status": "solo", "k": 0, "warmup": warm}
            self._cache[ck] = out
            return out
        key = sorted(by_tok, key=lambda t: (-len(by_tok[t]), t))[0]
        own_sym = symbol_norm(snap.get("symbol"))
        exact = bool(own_sym is not None and any(m.sym == own_sym for m in mem.values()))
        res = sorted((self.records.by_mint[m] for m in mem if m in self.records.by_mint
                      and self.records.by_mint[m].t_end <= snap.t), key=lambda p: (p.g, p.mint))
        base = {"k": k, "key": key, "exact_clone": exact, "warmup": warm, "n_resolved": len(res)}
        if not res:
            out = {"status": "pending", **base}
        else:
            last = res[-REC_K:]
            out = {"status": "eligible", **base, "heat": float(np.mean([p.ret for p in last]))}
        self._cache[ck] = out
        return out


def _structure_of(cd: C.CoinData, sol: C.SolUsd | None = None) -> dict:
    """(name, symbol, creator) read through AsOf at g + 20 s (all legal from creation or g)."""
    s = C.AsOf(cd, cd.g + C.DECISION_LAG_S, sol)
    return {"mint": cd.mint, "g": cd.g, "creator": _nz(s.get("creator")), "name": _nz(s.get("name")),
            "symbol": _nz(s.get("symbol"))}


def structure_rows_from_frames(graduates: pd.DataFrame, census: C.Census, lo: float, hi: float) -> list[dict]:
    """Structural pool (PREREG 2.1): every graduate (any quote / Mayhem) created in [lo, hi), read through AsOf."""
    g = C._normalize_graduates(graduates, census)
    g = g[(g["created_for_split"] >= lo) & (g["created_for_split"] < hi)]
    pooled = set(C.POOLED_ACCOUNTS) | C._pooled_from_file()
    empty = pd.DataFrame(columns=["minute_ts", "open", "high", "low", "close", "x_close", "y_close"])
    return [_structure_of(C._make_coin(r, empty, None, pooled)) for r in g.to_dict("records")]


def structure_rows_from_datasets(datasets: Iterable[C.Dataset]) -> list[dict]:
    return [_structure_of(ds.coin(m), ds.sol) for ds in datasets for m in ds.mints]


def build_registry(history: Sequence[C.Dataset], structure_rows: Iterable[Mapping[str, Any]] | None = None) -> Registry:
    """Records from the history datasets; structure from ``structure_rows`` (production: every graduate of the
    structural pool) or, without them, from the history datasets' usable coins."""
    rows = list(structure_rows) if structure_rows is not None else structure_rows_from_datasets(history)
    return Registry(themes=Themes.from_rows(rows), records=Records.from_datasets(history))


# =========================================================================== strategy, placebo


EXITS = C.ExitSpec(stop_pct=STOP_PCT, max_hold_s=HOLD_S, exit_by_age_s=EXIT_BY_AGE_S)


def tag_of(st: Mapping[str, Any]) -> str:
    hot = st.get("heat") is not None and st["heat"] >= HOT_THETA
    return f"{'hot' if hot else 'cold'}|{'crowd' if st.get('k', 0) >= CROWD_K else 'few'}"


def make_strategy(reg: Registry):
    """The Z4 strategy for common.backtest: one decision per coin at the first grid time >= g + 30 min."""

    def z4_strategy(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
        if pos is not None:
            return None                       # exits are mechanical only
        if snap.age_s < DEC_AGE_S:
            return None
        if not snap.alive():
            return C.SKIP
        st = reg.state(snap, p["lookback_s"])
        if st["status"] != "eligible":
            return C.SKIP
        if p["rule"] == "host" or st["heat"] >= float(p["theta"]):
            return C.Enter(exits=EXITS, tag=tag_of(st), state={"heat": st["heat"], "k": st["k"], "key": st["key"]})
        return C.SKIP

    return z4_strategy


def placebo_eligible(snap: C.AsOf) -> bool:
    """Placebo entries are alive, like the signals."""
    return snap.alive()


def make_stratum(reg: Registry, lookback_s: float):
    def eligible_member(snap: C.AsOf) -> str:
        """The judged placebo draws only eligible theme members (at the draw's own time, same N)."""
        return "eligible" if reg.state(snap, lookback_s)["status"] == "eligible" else "other"
    return eligible_member


PLACEBO_CONTROLS = {"unmatched": {"eligible": placebo_eligible, "strata": None}}


# =========================================================================== scans (counts only), trade info


def scan_coins(ds: C.Dataset, reg: Registry) -> pd.DataFrame:
    """Per coin at its decision time (first grid time >= g + 30 min): alive, and per N the status, crowding, heat
    flags, primary key, exact clone and warm-up. Heat VALUES are never returned (only the pre-registered flags)."""
    rows = []
    for m in ds.mints:
        cd = ds.coin(m)
        snap = ds.asof(m, grid_time_from(cd, cd.g + DEC_AGE_S))
        d = snap.get("grad_delay_s")
        row: dict[str, Any] = {"mint": m, "alive": bool(snap.alive()),
                               "instant": None if d is None else bool(d <= INSTANT_DELAY_S)}
        for n in N_GRID_H:
            st = reg.state(snap, n * 3600.0)
            h = st.get("heat")
            row.update({f"status_{n}": st["status"], f"k_{n}": st.get("k", 0), f"key_{n}": st.get("key"),
                        f"exact_{n}": st.get("exact_clone"), f"warm_{n}": st.get("warmup"),
                        **{f"ge{th:g}_{n}": (None if h is None else bool(h >= th)) for th in THETA_GRID}})
        rows.append(row)
    return pd.DataFrame(rows)


def event_counts(scan: pd.DataFrame, span_days: float) -> dict:
    """Counts only (no prices, no returns, no record values)."""
    per_day = (lambda x: x / span_days if span_days == span_days and span_days > 0 else None)
    out: dict[str, Any] = {"coins": int(len(scan)), "alive_at_decision": int(scan["alive"].sum()) if len(scan) else 0,
                           "by_N": {}}
    for n in N_GRID_H:
        if not len(scan):
            out["by_N"][f"{n}h"] = {}
            continue
        st = scan[f"status_{n}"]
        el = (st == "eligible") & scan["alive"]
        sub = scan[el]
        keys = sub[f"key_{n}"].value_counts()
        d = {"status_all": {str(k): int(v) for k, v in st.value_counts().items()},
             "member_any": int((scan[f"k_{n}"] > 0).sum()),
             "host_entries": int(el.sum()), "host_per_day": per_day(int(el.sum())),
             "host_crowd": int((sub[f"k_{n}"] >= CROWD_K).sum()),
             "host_exact_clone": int(sub[f"exact_{n}"].fillna(False).astype(bool).sum()),
             "host_instant": int(sub["instant"].fillna(False).astype(bool).sum()),
             "host_warmup": int(sub[f"warm_{n}"].fillna(False).astype(bool).sum()),
             "host_keys": int(len(keys)), "top_keys": {str(k): int(v) for k, v in keys.head(12).items()}}
        for th in THETA_GRID:
            c = int(sub[f"ge{th:g}_{n}"].fillna(False).astype(bool).sum())
            d[f"mom_th{th:g}_entries"] = c
            d[f"mom_th{th:g}_per_day"] = per_day(c)
        out["by_N"][f"{n}h"] = d
    return out


def trade_info(trades: pd.DataFrame, ds: C.Dataset, reg: Registry, lookback_s: float) -> pd.DataFrame:
    """Per trade (aligned): primary key, heat, k, exact clone, instant, warm-up -- the registry state at t_dec."""
    rows = []
    for r in trades.itertuples(index=False):
        snap = ds.asof(r.mint, float(r.t_dec))
        st = reg.state(snap, lookback_s)
        d = snap.get("grad_delay_s")
        rows.append({"key": st.get("key") or f"m:{r.mint}", "heat": st.get("heat"), "k": st.get("k", 0),
                     "exact_clone": bool(st.get("exact_clone")), "warmup": bool(st.get("warmup")),
                     "instant": None if d is None else bool(d <= INSTANT_DELAY_S)})
    return pd.DataFrame(rows, columns=["key", "heat", "k", "exact_clone", "warmup", "instant"])


# =========================================================================== evaluation


def _key_stats(t: pd.DataFrame, keys: Sequence[Any], B: int) -> dict:
    if not len(t):
        return {"n_keys": 0, "ci90_key": None, "best_key": None, "mean_without_best_key": None,
                "n_profitable_keys": 0}
    r = t["ret_net"].to_numpy(float)
    k = np.asarray(list(keys), object)
    prof = pd.Series(r).groupby(k).sum()
    best = sorted(prof.index, key=lambda x: (-float(prof[x]), str(x)))[0]
    rest = r[k != best]
    return {"n_keys": int(len(prof)), "ci90_key": C.coin_bootstrap_ci(r, k, 0.90, B),
            "best_key": {"key": str(best), "trades": int((k == best).sum()), "profit": float(prof[best])},
            "mean_without_best_key": float(rest.mean()) if len(rest) else None,
            "n_profitable_keys": int((prof > 0).sum())}


def _means_by(t: pd.DataFrame, labels: Sequence[Any]) -> dict:
    if not len(t):
        return {}
    s = pd.Series(t["ret_net"].to_numpy(float)).groupby(np.asarray(list(labels), object))
    return {str(k): {"n": int(len(g)), "mean": float(g.mean())} for k, g in s}


def evaluate(res: C.Result, info: pd.DataFrame, *, B: int, hide: bool, n_trials_total: int | None) -> dict:
    """Per-config report. Debug split: counts only (n, coins, keys, tags, placebo draws, horizon exits)."""
    t = res.trades
    p = res.meta["params"]
    cens = (t["reason"] == "horizon").to_numpy(bool) if len(t) else np.zeros(0, bool)
    base = {"config": config_key(p), "params_hash": C.params_hash(p), "hypothesis": res.meta["hypothesis"],
            "n": int(len(t)), "n_coins": int(t["mint"].nunique()) if len(t) else 0,
            "n_keys": int(info["key"].nunique()) if len(info) else 0,
            "tags": t["tag"].value_counts().to_dict() if len(t) else {},
            "n_exact_clone": int(info["exact_clone"].sum()) if len(info) else 0,
            "n_instant": int(info["instant"].fillna(False).astype(bool).sum()) if len(info) else 0,
            "n_warmup": int(info["warmup"].sum()) if len(info) else 0,
            "n_placebo": int(len(res.placebo)),
            "placebo_draws_per_signal": float(len(res.placebo) / len(t)) if len(t) else None,
            "horizon_exits": int(cens.sum()),
            "trial": {k: res.meta.get(k) for k in ("config", "new_trial", "n_trials_total")}}
    if hide:
        base["returns"] = "hidden on the debug split (never choose parameters on FINAL data)"
        return base
    base["reasons"] = t["reason"].value_counts().to_dict() if len(t) else {}
    d = C.describe(t, B=B, n_trials_total=n_trials_total)
    base.update({k: d.get(k) for k in ("mean", "median", "win_rate", "sd", "ci90", "ci95", "ci90_block", "ci95_block",
                                        "n_blocks", "censored_share", "top_coin_share", "top3_coin_share",
                                        "mean_without_top2", "halves", "mean_hold_min", "deflated_sharpe")})
    base["placebo"] = C.placebo_compare(t, res.placebo, B=B) if len(res.placebo) and len(t) else None
    pu = res.controls.get("unmatched") if res.controls else None
    base["placebo_unmatched"] = C.placebo_compare(t, pu, B=B) if pu is not None and len(pu) and len(t) else None
    base["stress"] = {k: C.describe(v, B=200).get("mean") for k, v in res.stress.items()}
    base["portfolio"] = {k: v for k, v in C.portfolio_sim(t).items() if k != "skipped_mints"}
    base["keys"] = _key_stats(t, info["key"], B)
    base["diagnostics"] = {
        "by_tag": _means_by(t, t["tag"]) if len(t) else {},
        "by_link": _means_by(t, np.where(info["exact_clone"].to_numpy(bool), "exact_clone", "token_only")) if len(t) else {},
        "by_speed": _means_by(t, info["instant"].map({True: "instant", False: "slow"}).fillna("unknown")) if len(t) else {},
        "by_warmup": _means_by(t, np.where(info["warmup"].to_numpy(bool), "warmup", "full_lookback")) if len(t) else {},
        "top_keys": dict(sorted(_means_by(t, info["key"]).items(), key=lambda kv: (-kv[1]["n"], kv[0]))[:10]),
        "dose_spearman_heat_ret": spearman(info["heat"].astype(float), t["ret_net"]) if len(t) else None,
    }
    return base


def veto_eval(host: pd.DataFrame, *, B: int, hide: bool, oos: pd.DataFrame | None = None,
              oos_is_self: bool = False) -> dict:
    """The exhaustion veto on HOST trades (PREREG 6): flagged = tag 'hot'. ``oos`` = out-of-sample host trades
    (criterion 2); ``oos_is_self`` (CONFIRM) uses the same never-searched trades for every criterion."""
    def flags(t):
        return t["tag"].astype(str).str.startswith("hot").to_numpy(bool) if len(t) else np.zeros(0, bool)
    f = flags(host)
    out: dict[str, Any] = {"flag": VETO_RULE, "n_host": int(len(host)), "n_flagged": int(f.sum()),
                           "n_unflagged": int((~f).sum())}
    if hide:
        return out
    r = host["ret_net"].to_numpy(float) if len(host) else np.zeros(0)
    out["flagged_mean"] = float(r[f].mean()) if f.any() else None
    out["unflagged_mean"] = float(r[~f].mean()) if (~f).any() else None
    if len(host):
        crowd = host["tag"].astype(str).str.endswith("crowd").to_numpy(bool)
        out["by_crowding"] = {
            lab: {"flagged_mean": float(r[f & sel].mean()) if (f & sel).any() else None, "n_flagged": int((f & sel).sum()),
                  "unflagged_mean": float(r[~f & sel].mean()) if (~f & sel).any() else None,
                  "n_unflagged": int((~f & sel).sum())}
            for lab, sel in (("few", ~crowd), ("crowd", crowd))}
    if oos_is_self:
        oos = host
    of = None if oos is None else flags(oos)
    if oos is not None and not oos_is_self:
        out["n_oos"], out["n_oos_flagged"] = int(len(oos)), int(of.sum())
    out["verdict"] = C.verdict_veto(host, f, oos_host=oos, oos_flagged=of, B=B) if len(host) else \
        {"verdict": "UNDERPOWERED", "n_flagged": 0, "n_unflagged": 0, "criteria": []}
    return out


def _veto_crit1(ve: Mapping[str, Any]) -> dict | None:
    for c in ((ve.get("verdict") or {}).get("criteria") or []):
        if c.get("id") == 1:
            return c
    return None


def z4_extras(ev: Mapping[str, Any]) -> list[dict]:
    ks = ev.get("keys") or {}
    out = [{"id": "Z4.1", "name": f"power: >= {PASS_MIN_TRADES} trades from >= {PASS_MIN_KEYS} theme keys",
            "pass": bool(ev["n"] >= PASS_MIN_TRADES and ev["n_keys"] >= PASS_MIN_KEYS),
            "value": {"n": ev["n"], "keys": ev["n_keys"]}}]
    ci = ks.get("ci90_key")
    out.append({"id": "Z4.2", "name": "90% CI lower bound > 0 resampling theme keys",
                "pass": None if not ci else bool(ci[0] > 0), "value": ci})
    mw = ks.get("mean_without_best_key")
    out.append({"id": "Z4.3", "name": "mean > 0 without the most profitable key",
                "pass": None if mw is None else bool(mw > 0), "value": mw})
    npk = ks.get("n_profitable_keys")
    out.append({"id": "Z4.4", "name": f">= {PASS_MIN_PROFIT_KEYS} keys with positive summed net profit",
                "pass": None if npk is None else bool(npk >= PASS_MIN_PROFIT_KEYS), "value": npk})
    return out


def combine_verdict(base: Mapping[str, Any], extras: list[dict]) -> str:
    """PLAN 3.5 items 1-8 + 10 (common.verdict_entry) and the Z4 extras. Item 9 (FINAL) is judged after FINAL."""
    if base.get("auto_rejections"):
        return "REJECTED"
    crit = {c["id"]: c["pass"] for c in base["criteria"] if c["id"] != 9}
    censored_ok = crit.pop(10, True)
    if not crit.get(1) or extras[0]["pass"] is False:
        return "UNDERPOWERED"
    rest = [v for k, v in crit.items() if k != 1]
    if any(v is False for v in rest) or any(e["pass"] is False for e in extras[1:]):
        return "FAIL"
    if any(v is None for v in rest) or censored_ok is not True or any(e["pass"] is None for e in extras[1:]):
        return "INCOMPLETE"
    return "PASS"


# =========================================================================== pre-registered decisions


def decide_train(evals: Mapping[str, Mapping[str, Any]], vetoes: Mapping[str, Mapping[str, Any]]) -> dict:
    """PREREG 9 TRAIN, two branches. MOM: qualify configs, pick the highest theme-key 90 % CI lower bound. EXH: the
    N whose powered TRAIN veto passes criterion 1 with the lower CI upper bound. Shortlists: Z4 = [MOM choice],
    Z4-host = [HOST(N) for each chosen N]."""
    mom_rows = []
    for p in GRID_MOM:
        e = evals[config_key(p)]
        pc = (e.get("placebo") or {}).get("mean_diff")
        powered = e["n"] >= TRAIN_MIN_TRADES and e["n_keys"] >= TRAIN_MIN_KEYS
        good = (powered and e.get("mean") is not None and e["mean"] > 0
                and e.get("mean_without_top2") is not None and e["mean_without_top2"] > 0
                and pc is not None and pc > 0)
        ci = (e.get("keys") or {}).get("ci90_key")
        mom_rows.append({"config": config_key(p), "lookback_h": p["lookback_h"], "theta": p["theta"],
                         "powered": powered, "qualifies": bool(good), "n": e["n"], "keys": e["n_keys"],
                         "mean": e.get("mean"), "ci90_key_lo": ci[0] if ci else None, "placebo_diff": pc})
    exh_rows = []
    for n in N_GRID_H:
        ve = vetoes[config_key(make_params("host", n))]
        powered = ve["n_flagged"] >= VETO_MIN and ve["n_unflagged"] >= VETO_MIN
        c1 = _veto_crit1(ve)
        ci = (c1 or {}).get("ci95")
        exh_rows.append({"lookback_h": n, "powered": powered, "qualifies": bool(powered and c1 and c1["pass"]),
                         "n_flagged": ve["n_flagged"], "n_unflagged": ve["n_unflagged"],
                         "flagged_mean": ve.get("flagged_mean"), "unflagged_mean": ve.get("unflagged_mean"),
                         "diff": (c1 or {}).get("value"), "ci95_hi": ci[1] if ci else None})
    dec: dict[str, Any] = {"mom_rows": mom_rows, "exh_rows": exh_rows, "branches": [], "mom": None, "exh": None}
    q = [r for r in mom_rows if r["qualifies"]]
    if q:
        best = sorted(q, key=lambda r: (-(r["ci90_key_lo"] if r["ci90_key_lo"] is not None else -math.inf),
                                        -r["mean"], -r["theta"], N_GRID_H.index(r["lookback_h"])))[0]
        dec["mom"] = {"chosen": best["config"], "lookback_h": best["lookback_h"], "theta": best["theta"]}
        dec["branches"].append("mom")
    qe = [r for r in exh_rows if r["qualifies"]]
    if qe:
        best = sorted(qe, key=lambda r: (r["ci95_hi"], N_GRID_H.index(r["lookback_h"])))[0]
        dec["exh"] = {"lookback_h": best["lookback_h"]}
        dec["branches"].append("exh")
    if dec["branches"]:
        sl_m = [make_params("mom", dec["mom"]["lookback_h"], dec["mom"]["theta"])] if dec["mom"] else []
        ns = []
        for b in ("mom", "exh"):
            if dec[b] and dec[b]["lookback_h"] not in ns:
                ns.append(dec[b]["lookback_h"])
        sl_h = [make_params("host", n) for n in ns]
        dec["verdict"] = "SHORTLISTED"
        dec["shortlist"] = {HYP: sl_m, HYP_HOST: sl_h}
        dec["shortlist_hashes"] = {HYP: [C.params_hash(p) for p in sl_m], HYP_HOST: [C.params_hash(p) for p in sl_h]}
        return dec
    if any(r["powered"] for r in mom_rows) or any(r["powered"] for r in exh_rows):
        dec["verdict"], dec["reason"] = "NO_CONFIG", "powered MOM configs / vetoes failed their TRAIN bars"
    else:
        dec["verdict"] = "UNDERPOWERED_TRAIN"
        dec["reason"] = (f"no MOM config reached >= {TRAIN_MIN_TRADES} trades from >= {TRAIN_MIN_KEYS} keys and no veto "
                         f">= {VETO_MIN} flagged and unflagged (best MOM: {max(r['n'] for r in mom_rows)} trades)")
    dec["shortlist"], dec["shortlist_hashes"] = {}, {}
    return dec


def decide_val(ev_cand: Mapping[str, Any]) -> dict:
    n = ev_cand["n"]
    mean, mw2 = ev_cand.get("mean"), ev_cand.get("mean_without_top2")
    if n < VAL_MIN_SIGN:
        v = "UNDERPOWERED_VAL"
    elif not (mean is not None and mean > 0 and (mw2 is None or mw2 > 0)):
        v = "FAIL_VAL"
    elif n < VAL_MIN_TRADES:
        v = "SELECTED_UNDERPOWERED"
    else:
        v = "SELECTED"
    return {"verdict": v, "n": n, "mean": mean, "mean_without_top2": mw2, "proceed": v in PROCEED_VAL}


def decide_val_exh(ve: Mapping[str, Any]) -> dict:
    nf, nu = ve["n_flagged"], ve["n_unflagged"]
    fm, um = ve.get("flagged_mean"), ve.get("unflagged_mean")
    if nf < VAL_MIN_SIGN or fm is None or um is None:
        v = "UNDERPOWERED_VAL"
    elif fm >= um:
        v = "FAIL_VAL"
    elif nf < VETO_MIN or nu < VETO_MIN:
        v = "SELECTED_UNDERPOWERED"
    else:
        c1 = _veto_crit1(ve)
        v = "SELECTED" if (c1 and c1["pass"]) else "FAIL_VAL"
    return {"verdict": v, "n_flagged": nf, "n_unflagged": nu, "flagged_mean": fm, "unflagged_mean": um,
            "proceed": v in PROCEED_VAL}


def mom_alive_after_test(test_doc: Mapping[str, Any]) -> tuple[bool, str]:
    """CONFIRM is spent on MOM when TEST is not REJECTED and (TEST mean > 0 or TEST n < 5 = no evidence)."""
    m = (test_doc.get("decision") or {}).get("mom")
    if not m:
        return False, "MOM did not run on TEST"
    if m.get("verdict") == "REJECTED":
        return False, "TEST was REJECTED (PLAN 3.6)"
    c = (test_doc.get("configs") or {}).get("candidate") or {}
    n, mean = c.get("n", 0), c.get("mean")
    if n < TEST_NO_EVIDENCE_N or (mean is not None and mean > 0):
        return True, "ok"
    return False, f"TEST mean {mean} <= 0 on {n} trades: MOM failed TEST"


def exh_alive_after_test(test_doc: Mapping[str, Any]) -> tuple[bool, str]:
    e = (test_doc.get("decision") or {}).get("exh")
    if not e:
        return False, "EXH did not run on TEST"
    v = (e.get("verdict") or {}).get("verdict")
    return (v != "FAIL", "ok" if v != "FAIL" else "the TEST veto verdict is FAIL")


def final_decision(t: pd.DataFrame) -> dict:
    """MOM: PLAN 3.5 item 9 on the census thirds Z4 never looked at; the debug third is reported apart."""
    judged = t[t["split"].isin(FINAL_JUDGED)] if len(t) else t
    design = t[t["split"] == FINAL_DESIGN] if len(t) else t
    per = {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for s, g in t.groupby("split")} if len(t) else {}
    return {"verdict": "REPORTED", "judged_on": list(FINAL_JUDGED), "n": int(len(judged)),
            "mean": float(judged["ret_net"].mean()) if len(judged) else None,
            "mean_positive": None if not len(judged) else bool(judged["ret_net"].mean() > 0), "per_third": per,
            "design_third": {"n": int(len(design)), "mean": float(design["ret_net"].mean()) if len(design) else None,
                             "note": "census TRAIN third: the debug third, not judged"}}


def final_exh(t: pd.DataFrame) -> dict:
    """EXH on FINAL: flagged mean < unflagged mean on the judged thirds."""
    judged = t[t["split"].isin(FINAL_JUDGED)] if len(t) else t
    f = judged["tag"].astype(str).str.startswith("hot").to_numpy(bool) if len(judged) else np.zeros(0, bool)
    r = judged["ret_net"].to_numpy(float) if len(judged) else np.zeros(0)
    fm = float(r[f].mean()) if f.any() else None
    um = float(r[~f].mean()) if (~f).any() else None
    return {"verdict": "REPORTED", "judged_on": list(FINAL_JUDGED), "n_flagged": int(f.sum()),
            "n_unflagged": int((~f).sum()), "flagged_mean": fm, "unflagged_mean": um,
            "flagged_worse": None if fm is None or um is None else bool(fm < um)}


# =========================================================================== stage prerequisites


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return None


def coverage_check(cov: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Every chain hour of the split scanned (curve AND B2) and the common data-contract problems."""
    if not cov.get("usable"):
        return False, ["no usable coins: the backfill has not reached this split yet"]
    notes = []
    if cov.get("chain_hours_scanned_frac", 0) < 0.999:
        notes.append(f"only {cov.get('chain_hours_scanned_frac', 0):.1%} of chain hours scanned")
    for d in cov.get("days", []):
        if d["curve_hours"] < d["hours_in_split"] or d["b2_hours"] < d["hours_in_split"]:
            notes.append(f"{d['day']}: curve {d['curve_hours']}/{d['hours_in_split']} h, "
                         f"B2 {d['b2_hours']}/{d['hours_in_split']} h")
    notes += C.coverage_problems(cov)
    return not notes, notes


def _runs(ledger_path: Path | None) -> list[dict]:
    with C._ledger(ledger_path, write=False) as led:
        return list(led.get("runs", []))


def _shortlist(h: str, shortlist_path: Path | None) -> dict | None:
    return _read_json(Path(shortlist_path or C.shortlist_dir()) / f"{h}.json")


def live_branches(out_dir: Path, stage: str) -> dict[str, str | None]:
    """branch -> None when it may run at ``stage``, else the reason it stopped (from the docs written before it)."""
    out_dir = Path(out_dir)
    tr = _read_json(out_dir / "train.json")
    if not tr or tr.get("provisional") or (tr.get("decision") or {}).get("verdict") != "SHORTLISTED":
        return {b: "no SHORTLISTED official TRAIN" for b in BRANCHES}
    live: dict[str, str | None] = {b: (None if b in tr["decision"].get("branches", []) else
                                       "did not qualify on TRAIN") for b in BRANCHES}
    if stage == "val":
        return live
    va = _read_json(out_dir / "val.json")
    for b in BRANCHES:
        if live[b] is None:
            d = ((va or {}).get("decision") or {}).get(b)
            if not va:
                live[b] = "no VAL result"
            elif not d or not d.get("proceed"):
                live[b] = f"VAL decision {(d or {}).get('verdict')}"
    if stage == "test":
        return live
    te = _read_json(out_dir / "test.json")
    for b, fn in (("mom", mom_alive_after_test), ("exh", exh_alive_after_test)):
        if live[b] is None:
            if not te:
                live[b] = "no TEST result"
            else:
                ok, why = fn(te)
                live[b] = None if ok else why
    if stage == "confirm":
        return live
    co = _read_json(out_dir / "confirm.json")
    if co:
        dm, de = (co.get("decision") or {}).get("mom"), (co.get("decision") or {}).get("exh")
        if live["mom"] is None and (dm or {}).get("verdict") != "PASS":
            live["mom"] = f"CONFIRM {(dm or {}).get('verdict')}"
        if live["exh"] is None and ((de or {}).get("verdict") or {}).get("verdict") != "PASS":
            live["exh"] = f"CONFIRM veto {((de or {}).get('verdict') or {}).get('verdict')}"
    return live


def stage_configs(stage: str, out_dir: Path = OUT_DIR, shortlist_path: Path | None = None) -> list[tuple[str, str, dict]]:
    """[(role, hypothesis, params)] the stage runs (later stages: the live branches' shortlisted configs)."""
    if stage in ("debug", "train"):
        return [(config_key(p), hyp_of(p), p) for p in GRID]
    tr = _read_json(Path(out_dir) / "train.json") or {}
    dec = tr.get("decision") or {}
    live = live_branches(out_dir, stage)
    sl_m, sl_h = _shortlist(HYP, shortlist_path), _shortlist(HYP_HOST, shortlist_path)
    hosts = {int(c["lookback_h"]): c for c in (sl_h or {}).get("configs", [])}
    out: list[tuple[str, str, dict]] = []
    ns: list[int] = []
    if live["mom"] is None and dec.get("mom"):
        if not sl_m:
            return []
        out.append(("candidate", HYP, sl_m["configs"][0]))
        ns.append(int(dec["mom"]["lookback_h"]))
    if live["exh"] is None and dec.get("exh") and int(dec["exh"]["lookback_h"]) not in ns:
        ns.append(int(dec["exh"]["lookback_h"]))
    for n in ns:
        out.append((host_role(n), HYP_HOST, hosts.get(n)))
    return out


def check_prereqs(stage: str, out_dir: Path = OUT_DIR, *, flow: Path | None = None, ledger_path: Path | None = None,
                  shortlist_path: Path | None = None, env: Mapping[str, str] | None = None,
                  rerun_reason: str | None = None) -> dict:
    """Raise :class:`Z4Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise Z4Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise Z4Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    if lock and lock.get("sha256") != _sha(prereg):
        raise Z4Refused("PREREG.md changed after the first official TRAIN run; record changes in Z4/AMENDMENTS.md "
                        "as a new version instead")
    ok, bad = C.validation_gates(STAGE_SPLIT[stage], flow)
    if not ok and stage != "debug":
        raise Z4Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {"stage": stage, "prereg_sha256": _sha(prereg), "prereg_locked": bool(lock),
            "data_gates": {"ok": ok, "problems": bad}}
    if stage == "debug":
        return info
    train = _read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise Z4Refused("TRAIN already ran on complete data (Z4/train.json); its decision is final. A re-run needs "
                            "--rerun-reason naming the data correction that justifies it")
        return info
    if not train:
        raise Z4Refused("no TRAIN result (Z4/train.json): run --stage train first")
    if train.get("provisional"):
        raise Z4Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    dec = train.get("decision") or {}
    if dec.get("verdict") != "SHORTLISTED":
        raise Z4Refused(f"TRAIN decision {dec.get('verdict')}: Z4 stopped before VAL")
    want = dec.get("shortlist_hashes") or {}
    for h in (HYP, HYP_HOST):
        if not want.get(h):
            continue
        sl = _shortlist(h, shortlist_path)
        if not sl:
            raise Z4Refused(f"no VAL shortlist for {h} (written by a complete --stage train)")
        if sorted(sl.get("hashes", [])) != sorted(want.get(h, [])):
            raise Z4Refused(f"the {h} shortlist on disk differs from the one TRAIN wrote")
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise Z4Refused("VAL already ran (Z4/val.json exists): VAL is evaluated once")
        info["live_branches"] = live_branches(out_dir, "val")
        return info
    if stage == "test" and not (out_dir / "val.json").exists():
        raise Z4Refused("no VAL result (Z4/val.json): TEST needs a VAL decision first")
    if stage in ("confirm", "final") and not (out_dir / "test.json").exists():
        raise Z4Refused(f"never {stage.upper()} before TEST: run --stage test first")
    live = live_branches(out_dir, stage)
    if all(v is not None for v in live.values()):
        raise Z4Refused(f"no live branch for {stage.upper()}: " + "; ".join(f"{b}: {v}" for b, v in live.items()))
    if (out_dir / f"{stage}.json").exists():
        raise Z4Refused(f"{stage.upper()} already ran (Z4/{stage}.json exists): one run per hypothesis")
    for h in (HYP, HYP_HOST):
        if any(r.get("hypothesis") == h and C.split_group(r.get("split", "")) == C.split_group(split)
               and not r.get("debug") for r in _runs(ledger_path)):
            raise Z4Refused(f"{h} already had its one {split} run (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise Z4Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
    info["live_branches"] = live
    return info


# =========================================================================== stage runner


def _jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (float, np.floating)):
        x = float(o)
        return None if math.isnan(x) or math.isinf(x) else x
    if o is pd.NA:
        return None
    return o


def _coverage_counts(split: str, flow: Path | None, census: C.Census | None) -> dict:
    if split == "final":
        return {s: C.coverage_dataset(s, flow, census).coverage for s in C.FINAL_SPLITS}
    return C.coverage_dataset(split, flow, census).coverage


def _span_days(ds: C.Dataset) -> float:
    c = ds.coins["created_for_split"] if len(ds) else pd.Series(dtype=float)
    if ds.split in C.SPLIT_BOUNDS and ds.coverage.get("complete"):
        lo, hi = C.SPLIT_BOUNDS[ds.split]
        return (hi - lo) / 86400.0
    return max((float(c.max()) - float(c.min())) / 86400.0, 1e-9) if len(c) else float("nan")


def _hist_bounds(stage: str, census: C.Census) -> tuple[float, float]:
    """[first history split start, stage split end): the structural pool's creation range (PREREG 2.1)."""
    lo = math.inf
    for s in HISTORY_SPLITS[stage]:
        lo = min(lo, float(C.SPLIT_BOUNDS[s][0]) if s in C.SPLIT_BOUNDS else float(C.FINAL_LO))
    split = STAGE_SPLIT[stage]
    if split in C.SPLIT_BOUNDS:
        hi = float(C.SPLIT_BOUNDS[split][1])
    elif split == "final_train":
        hi = float(census.train_hi) + 1.0
    else:
        hi = math.inf
    return lo, hi


def history_datasets(stage: str, ds: C.Dataset, flow: Path | None, census: C.Census | None,
                     history: Sequence[C.Dataset] | None = None) -> list[C.Dataset]:
    """The stage's own dataset plus the other history splits (PREREG 2.1), read for OUTCOME records only through a
    counts-level loader (never handed to a strategy); each is earlier in time and already open at this stage."""
    if history is not None:
        return [ds] + list(history)
    own = set(C.FINAL_SPLITS) if ds.split == "final" else {ds.split}
    out = [ds]
    for s in HISTORY_SPLITS[stage]:
        if s not in own:
            out.append(C.coverage_dataset(s, flow, census))
    return out


def run_stage(stage: str, *, out_dir: Path = OUT_DIR, allow_partial: bool = False, rerun_reason: str | None = None,
              ds: C.Dataset | None = None, history: Sequence[C.Dataset] | None = None,
              structure_rows: Sequence[Mapping[str, Any]] | None = None, census: C.Census | None = None,
              flow: Path | None = None, ledger_path: Path | None = None, shortlist_path: Path | None = None,
              B: int = 10_000, n_placebo: int = 20, env: Mapping[str, str] | None = None,
              _skip_coverage: bool = False) -> dict:
    """Run one stage end to end and write Z4/<stage>.json + .md (``ds`` / ``history`` / ``structure_rows``
    injection is for tests: without ``structure_rows`` an injected run builds the structure from the history)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(stage, out_dir, flow=flow, ledger_path=ledger_path, shortlist_path=shortlist_path, env=env,
                         rerun_reason=rerun_reason)
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "z4_debug_trials.json"   # debug never reaches the real ledger
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    provisional = False
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise Z4Refused(f"{split} data incomplete: " + "; ".join(notes[:6])
                                + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else ""))
    covs = list(cov.values()) if (split == "final" and "split" not in cov) else [cov]
    hard = [] if debug else [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
    if hard:
        raise Z4Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_configs(stage, out_dir, shortlist_path)
    if not configs or any(p is None for _, _, p in configs):
        raise Z4Refused("no configs to run (shortlist missing or malformed, or no live branch)")

    def _execute(ds: C.Dataset | None) -> dict:
        if not debug:   # commit: every (hypothesis, config) is allowed BEFORE any data is read
            try:
                for _, h, p in configs:
                    C._check_run_allowed(h, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise Z4Refused(str(e)) from e
        if stage == "train" and not provisional:
            out_dir.mkdir(parents=True, exist_ok=True)
            if not (out_dir / "prereg.lock").exists():
                (out_dir / "prereg.lock").write_text(json.dumps({"sha256": info["prereg_sha256"],
                                                                 "locked_utc": C.utc_str(time.time())}, indent=1))
            if rerun_reason and (out_dir / "train.json").exists():
                stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
                for ext in ("json", "md"):
                    p = out_dir / f"train.{ext}"
                    if p.exists():
                        p.rename(out_dir / f"train_prev_{stamp}.{ext}")
        cen = census if census is not None else (C.Census.load() if ds is None else C.Census.empty())
        injected = ds is not None
        if ds is None:
            ds = C.load(split, flow=flow, census=cen, _internal=(split == "val"))
        if not debug:
            C.check_sol_coverage(ds)
        hist = history_datasets(stage, ds, flow, cen, history if history is not None else ([] if injected else None))
        rows = structure_rows
        if rows is None and not injected:
            lo, hi = _hist_bounds(stage, cen)
            f = Path(flow or C.flow_dir())
            rows = structure_rows_from_frames(C._read_parquet(f / "graduates.parquet"), cen, lo, hi)
        reg = build_registry(hist, rows)
        span = _span_days(ds)
        scan = scan_coins(ds, reg)
        doc: dict[str, Any] = {"hypothesis": HYP, "version": VERSION, "stage": stage, "split": split,
                               "utc": C.utc_str(time.time()), "provisional": provisional, "debug_only": debug,
                               "prereg_sha256": info["prereg_sha256"], "rerun_reason": rerun_reason,
                               "coverage": cov, "n_coins": len(ds), "span_days": span,
                               "live_branches": info.get("live_branches"),
                               "history": {"splits": [h.split for h in hist], "record_coins": reg.records.n_coins,
                                           "records": len(reg.records.by_mint),
                                           "structure_coins": reg.themes.n_coins,
                                           "structure_named": reg.themes.n_named,
                                           "tokens": len(reg.themes.by_token),
                                           "first_structure_g_utc": C.utc_str(reg.themes.first_g)},
                               "event_counts": event_counts(scan, span)}
        strategy = make_strategy(reg)
        results: dict[str, C.Result] = {}
        infos: dict[str, pd.DataFrame] = {}
        for role, h, p in configs:
            results[role] = C.backtest(strategy, split, p, hypothesis=h, ds=ds, cfg=FILL, placebo=True,
                                       n_placebo=n_placebo, placebo_eligible=placebo_eligible,
                                       placebo_strata=make_stratum(reg, p["lookback_s"]),
                                       placebo_controls=PLACEBO_CONTROLS, stress=STRESS, declarations=DECL,
                                       ledger_path=ledger_path, shortlist_path=shortlist_path)
            infos[role] = trade_info(results[role].trades, ds, reg, p["lookback_s"])
        n_tr = C.n_trials(ledger_path)
        evals = {role: evaluate(r, infos[role], B=B, hide=debug, n_trials_total=n_tr) for role, r in results.items()}
        doc["configs"] = evals
        if debug:
            doc["entries_per_day"] = {k: (e["n"] / span if span == span and span > 0 else None) for k, e in evals.items()}
        else:
            _write_trades(out_dir, stage, provisional, results, infos)
        dec_tr = ((_read_json(out_dir / "train.json") or {}).get("decision") or {}) if stage not in ("train", "debug") \
            else {}
        n_exh = (dec_tr.get("exh") or {}).get("lookback_h")
        live = info.get("live_branches") or {}
        # ---- the exhaustion veto (PREREG 6)
        if stage in ("train", "debug"):
            doc["veto"] = {}
            for n in N_GRID_H:
                k = config_key(make_params("host", n))
                ve = veto_eval(results[k].trades, B=min(B, 4000), hide=debug)
                ve["trial"] = C.record_run(HYP_EXH, veto_params(n), split, {"n": ve["n_host"], "mean": None},
                                           ledger_path, debug=debug)
                doc["veto"][k] = ve
        elif live.get("exh") is None and n_exh is not None:
            host_t = results[host_role(n_exh)].trades
            if stage == "val":
                doc["veto"] = veto_eval(host_t, B=min(B, 4000), hide=False)
            elif stage == "test":
                val_host = _read_trades(out_dir, "val", host_role(n_exh))
                doc["veto"] = veto_eval(val_host if val_host is not None else C._frame([]), B=min(B, 4000), hide=False,
                                        oos=host_t)
            elif stage == "confirm":
                doc["veto"] = veto_eval(host_t, B=min(B, 4000), hide=False, oos_is_self=True)
        # ---- decisions
        if debug:
            doc["decision"] = {"verdict": "DEBUG", "note": "mechanics and counts only; returns hidden"}
        elif stage == "train":
            dec = decide_train(evals, doc["veto"])
            dec["shortlist_written"] = False
            if dec["verdict"] == "SHORTLISTED" and not provisional:
                for h in (HYP, HYP_HOST):
                    if dec["shortlist"].get(h):
                        C.write_shortlist(h, dec["shortlist"][h], path=shortlist_path, ledger_path=ledger_path,
                                          note=f"{VERSION}: PREREG 9 rule, branches {dec['branches']}")
                dec["shortlist_written"] = True
            doc["decision"] = dec
        elif stage == "val":
            dm = decide_val(evals["candidate"]) if "candidate" in evals else None
            de = decide_val_exh(doc["veto"]) if "veto" in doc else None
            doc["decision"] = {"verdict": "VAL", "mom": dm, "exh": de,
                               "proceed": bool((dm or {}).get("proceed") or (de or {}).get("proceed"))}
        elif stage in ("test", "confirm"):
            dm = None
            if "candidate" in results:
                val_t = _read_trades(out_dir, "val", "candidate")
                val_res = C.Result(trades=val_t, placebo=C._frame([]), stress={}, meta={}) if val_t is not None else None
                base = C.verdict_entry(results["candidate"], val=val_res, min_mean=PASS_MIN_MEAN, B=B)
                extras = z4_extras(evals["candidate"])
                dm = {"verdict": combine_verdict(base, extras), "base": base, "z4_extras": extras}
            de = doc.get("veto")
            doc["decision"] = {"verdict": f"MOM {(dm or {}).get('verdict')}; EXH "
                                          f"{((de or {}).get('verdict') or {}).get('verdict')}", "mom": dm, "exh": de}
        elif stage == "final":
            dm = final_decision(results["candidate"].trades) if "candidate" in results else None
            de = final_exh(results[host_role(n_exh)].trades) if (live.get("exh") is None and n_exh is not None) else None
            doc["decision"] = {"verdict": "REPORTED", "mom": dm, "exh": de}
        return _finish(doc, out_dir, stage, provisional, t0, ledger_path)

    session = (C.one_shot_session(HYP, split, ledger_path, note=f"z4 --stage {stage}")
               if split in C.ONE_RUN_SPLITS else contextlib.nullcontext())
    try:
        with session:
            return _execute(ds)
    except C.SplitLocked as e:
        raise Z4Refused(str(e)) from e


def _trades_path(out_dir: Path, stage: str, provisional: bool) -> Path:
    return out_dir / f"{stage}{'_prelim' if provisional else ''}_trades.csv"


def _write_trades(out_dir: Path, stage: str, provisional: bool, results: Mapping[str, C.Result],
                  infos: Mapping[str, pd.DataFrame]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = [r.trades.reset_index(drop=True).assign(role=role, config=config_key(r.meta["params"]),
                                                     hypothesis=r.meta["hypothesis"],
                                                     key=infos[role]["key"].to_numpy(object),
                                                     heat=infos[role]["heat"].to_numpy(object))
              for role, r in results.items()]
    pd.concat(frames, ignore_index=True).to_csv(_trades_path(out_dir, stage, provisional), index=False)


def _read_trades(out_dir: Path, stage: str, role: str) -> pd.DataFrame | None:
    p = _trades_path(out_dir, stage, False)
    if not p.exists():
        return None
    t = pd.read_csv(p)
    return t[t["role"] == role].reset_index(drop=True)


def _finish(doc: dict, out_dir: Path, stage: str, provisional: bool, t0: float, ledger_path: Path | None) -> dict:
    doc["runtime_s"] = round(time.time() - t0, 1)
    doc["n_trials_total"] = C.n_trials(ledger_path)
    doc["overall"] = overall_verdict(out_dir, pending=doc)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = stage + ("_prelim" if provisional else "")
    doc = _jsonable(doc)
    (out_dir / f"{name}.json").write_text(json.dumps(doc, indent=1, sort_keys=False))
    (out_dir / f"{name}.md").write_text(render_md(doc))
    return doc


def overall_verdict(out_dir: Path, pending: Mapping[str, Any] | None = None) -> str:
    """The hypothesis-level status per branch from every stage written so far (``pending`` = the stage being
    written)."""
    def doc(s):
        if pending is not None and pending.get("stage") == s and not pending.get("provisional"):
            return pending
        return _read_json(Path(out_dir) / f"{s}.json")

    tr = doc("train")
    if not tr or tr.get("provisional"):
        return "PENDING (no official TRAIN run)"
    dec = tr.get("decision") or {}
    tv = dec.get("verdict")
    if tv == "UNDERPOWERED_TRAIN":
        return "UNDERPOWERED (TRAIN)"
    if tv == "NO_CONFIG":
        return "NO EDGE (nothing qualified on TRAIN: neither momentum nor exhaustion)"
    out = []
    for b, good, bad in (("mom", "EDGE", "NO EDGE"), ("exh", "VETO", "NO VETO")):
        lab = b.upper()
        if b not in dec.get("branches", []):
            out.append(f"{lab}: {bad} (did not qualify on TRAIN)")
            continue
        va = doc("val")
        if not va:
            out.append(f"{lab}: PENDING VAL")
            continue
        vv = ((va.get("decision") or {}).get(b) or {}).get("verdict")
        if vv == "FAIL_VAL":
            out.append(f"{lab}: {bad} (failed VAL)")
            continue
        if vv == "UNDERPOWERED_VAL" or vv is None:
            out.append(f"{lab}: UNDERPOWERED (VAL)")
            continue
        te = doc("test")
        if not te:
            out.append(f"{lab}: PENDING TEST")
            continue
        ok, why = (mom_alive_after_test if b == "mom" else exh_alive_after_test)(te)
        if not ok:
            out.append(f"{lab}: {bad} ({why})")
            continue
        co = doc("confirm")
        if not co:
            out.append(f"{lab}: PENDING CONFIRM")
            continue
        d = (co.get("decision") or {}).get(b) or {}
        cv = d.get("verdict") if b == "mom" else (d.get("verdict") or {}).get("verdict")
        if cv == "UNDERPOWERED":
            out.append(f"{lab}: UNDERPOWERED (CONFIRM)")
            continue
        if cv != "PASS":
            out.append(f"{lab}: {bad} (CONFIRM {cv})")
            continue
        fi = doc("final")
        if not fi:
            out.append(f"{lab}: PENDING FINAL")
            continue
        fd = (fi.get("decision") or {}).get(b) or {}
        ok_final = fd.get("mean_positive") if b == "mom" else fd.get("flagged_worse")
        out.append(f"{lab}: {good}" if ok_final else f"{lab}: {bad} (FINAL)")
    return "; ".join(out)


# =========================================================================== markdown


def _pct(x: Any, nd: int = 1) -> str:
    return "n/a" if x is None else f"{100 * float(x):+.{nd}f}%"


def _ci(ci: Any) -> str:
    return "n/a" if not ci else f"[{100 * ci[0]:+.1f}, {100 * ci[1]:+.1f}]"


def _num(x: Any, nd: int = 1) -> str:
    return "n/a" if x is None else f"{float(x):.{nd}f}"


def render_md(doc: Mapping[str, Any]) -> str:
    st = doc["stage"]
    h = doc.get("history") or {}
    L = [f"# Z4 {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}", "",
         f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days.",
         f"- **History:** outcome records from splits {h.get('splits')} ({h.get('records')} records of "
         f"{h.get('record_coins')} usable coins); structural pool {h.get('structure_coins')} graduates "
         f"({h.get('structure_named')} with a creator and a theme token, {h.get('tokens')} distinct tokens); first "
         f"structural graduation {h.get('first_structure_g_utc')} UTC.",
         f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
         f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}.",
         f"- **Overall Z4 status:** {doc.get('overall')}.", ""]
    if doc.get("live_branches"):
        L += [f"- **Live branches at this stage:** {doc['live_branches']} (None = live).", ""]
    if doc.get("debug_only"):
        L += ["**Debug run on the census TRAIN third: mechanics and counts only. Returns, exit reasons, record values "
              "and placebo outcomes are hidden, and no parameter was chosen here.**", ""]
    ec = doc.get("event_counts")
    if ec:
        L += ["## Event counts at the decision (first grid time ≥ g + 30 min; no returns)", "",
              f"- Coins: {ec['coins']}; alive at the decision: {ec['alive_at_decision']}.", "",
              "| N | status (all coins) | coins with ≥ 1 member | HOST entries (eligible, alive) | per day | "
              "MOM θ=0.25 | MOM θ=1 | crowded (k ≥ 3) | exact clone | instant | warm-up | keys |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for n, d in (ec.get("by_N") or {}).items():
            if not d:
                continue
            L.append(f"| {n} | {d['status_all']} | {d['member_any']} | {d['host_entries']} | "
                     f"{_num(d['host_per_day'])} | {d['mom_th0.25_entries']} | {d['mom_th1_entries']} | "
                     f"{d['host_crowd']} | {d['host_exact_clone']} | {d['host_instant']} | {d['host_warmup']} | "
                     f"{d['host_keys']} |")
        L.append("")
        for n, d in (ec.get("by_N") or {}).items():
            if d:
                L.append(f"- Top primary keys of HOST entries, N = {n}: {d['top_keys']}.")
        L.append("")
    cf = doc.get("configs") or {}
    if cf:
        L += ["## Configs", ""]
        if doc.get("debug_only"):
            L += ["| config | trades | coins | keys | tags | exact clone | instant | placebo draws/signal | "
                  "horizon exits | entries/day |",
                  "|---|---:|---:|---:|---|---:|---:|---:|---:|---:|"]
            for k, e in cf.items():
                epd = (doc.get("entries_per_day") or {}).get(k)
                L.append(f"| {e['config']} | {e['n']} | {e['n_coins']} | {e['n_keys']} | {e['tags']} | "
                         f"{e['n_exact_clone']} | {e['n_instant']} | {_num(e.get('placebo_draws_per_signal'))} | "
                         f"{e['horizon_exits']} | {_num(epd)} |")
        else:
            L += ["| role | config | n | keys | mean | 90% CI coin | 90% CI 6-h block | 90% CI key | w/o top 2 | "
                  "w/o best key | placebo diff (members) | placebo diff (unmatched) | costs ×1.5 | ρ(heat, ret) |",
                  "|---|---|---:|---:|---:|---|---|---|---:|---:|---:|---:|---:|---:|"]
            for k, e in cf.items():
                ks = e.get("keys") or {}
                pc = (e.get("placebo") or {}).get("mean_diff")
                pu = (e.get("placebo_unmatched") or {}).get("mean_diff")
                rho = (e.get("diagnostics") or {}).get("dose_spearman_heat_ret")
                L.append(f"| {k} | {e['config']} | {e['n']} | {e['n_keys']} | {_pct(e.get('mean'))} | "
                         f"{_ci(e.get('ci90'))} | {_ci(e.get('ci90_block'))} | {_ci(ks.get('ci90_key'))} | "
                         f"{_pct(e.get('mean_without_top2'))} | {_pct(ks.get('mean_without_best_key'))} | {_pct(pc)} | "
                         f"{_pct(pu)} | {_pct((e.get('stress') or {}).get('costs_x1.5'))} | {_num(rho, 3)} |")
            L.append("")
            for k, e in cf.items():
                dg = e.get("diagnostics") or {}
                L.append(f"- {k} diagnostics: by tag {dg.get('by_tag')}; by link {dg.get('by_link')}; by speed "
                         f"{dg.get('by_speed')}; warm-up {dg.get('by_warmup')}.")
        L.append("")
    ve = doc.get("veto")
    if ve:
        L += ["## Exhaustion veto (the inverse, PREREG 6)", ""]
        items = ve.items() if "flag" not in ve else [("host", ve)]
        for k, v in items:
            line = f"- {k}: host trades {v['n_host']}, flagged (hot) {v['n_flagged']}, unflagged {v['n_unflagged']}"
            if "verdict" in v:
                line += (f"; flagged mean {_pct(v.get('flagged_mean'))}, unflagged mean {_pct(v.get('unflagged_mean'))}; "
                         f"by crowding {v.get('by_crowding')}; verdict **{v['verdict'].get('verdict')}**")
            L.append(line + ".")
        L.append("")
    dec = doc.get("decision") or {}
    L += ["## Decision", "", f"- **{dec.get('verdict')}**."]
    for r in dec.get("mom_rows") or []:
        L.append(f"- MOM {r['config']}: n {r['n']}, keys {r['keys']}, mean {_pct(r['mean'])}, 90% CI key low "
                 f"{_pct(r['ci90_key_lo'])}, placebo diff {_pct(r['placebo_diff'])}, qualifies {r['qualifies']}.")
    for r in dec.get("exh_rows") or []:
        L.append(f"- EXH N = {r['lookback_h']} h: flagged {r['n_flagged']}, unflagged {r['n_unflagged']}, flagged "
                 f"{_pct(r['flagged_mean'])} vs unflagged {_pct(r['unflagged_mean'])}, CI95 hi {_pct(r['ci95_hi'])}, "
                 f"qualifies {r['qualifies']}.")
    if "shortlist_written" in dec:
        L.append(f"- Shortlists written: {dec['shortlist_written']} (branches {dec.get('branches')}).")
    for b in BRANCHES:
        d = dec.get(b) if isinstance(dec.get(b), dict) else None
        if not d or stage_is_train(st):
            continue
        if "base" in d:
            L.append(f"- MOM verdict **{d['verdict']}**:")
            for c in d["base"]["criteria"]:
                L.append(f"  - PLAN 3.5 #{c['id']} {c['name']}: {c['pass']} (value {c['value']}, need {c['need']}).")
            for c in d.get("z4_extras", []):
                L.append(f"  - {c['id']} {c['name']}: {c['pass']} (value {c['value']}).")
            if d["base"].get("auto_rejections"):
                L.append(f"  - Auto-rejections: {d['base']['auto_rejections']}.")
            L.append("  - PLAN 3.5 #9 (FINAL mean > 0) is judged in the overall verdict after the FINAL stage.")
        elif "flag" in d:
            L.append(f"- EXH veto verdict **{(d.get('verdict') or {}).get('verdict')}** "
                     f"(criteria {(d.get('verdict') or {}).get('criteria')}).")
        else:
            L.append(f"- {b.upper()}: {d}.")
    for key in ("reason", "note"):
        if dec.get(key):
            L.append(f"- {dec[key]}")
    L.append("")
    return "\n".join(L)


def stage_is_train(stage: str) -> bool:
    return stage in ("train", "debug")


# =========================================================================== CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Z4 theme momentum / exhaustion: pre-registered stages; "
                                             "see research/lab2/Z4/PREREG.md")
    ap.add_argument("--stage", choices=STAGES)
    ap.add_argument("--debug", action="store_true", help="census TRAIN third: mechanics and counts only")
    ap.add_argument("--check", action="store_true", help="check the stage's prerequisites and exit")
    ap.add_argument("--allow-partial", action="store_true", help="TRAIN only: provisional run on partial data")
    ap.add_argument("--rerun-reason", help="TRAIN only: re-run an official TRAIN after a data correction")
    ap.add_argument("--B", type=int, default=10_000, help="bootstrap draws")
    ap.add_argument("--n-placebo", type=int, default=20)
    a = ap.parse_args(argv)
    if not a.stage and not a.debug:
        ap.error("--stage or --debug is required")
    stage = "debug" if a.debug else a.stage
    try:
        if a.check:
            print(json.dumps(check_prereqs(stage, rerun_reason=a.rerun_reason), indent=1))
            return 0
        doc = run_stage(stage, allow_partial=a.allow_partial, rerun_reason=a.rerun_reason, B=a.B,
                        n_placebo=a.n_placebo)
    except Z4Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(f"wrote {OUT_DIR / (name + '.json')} and .md; decision: {(doc.get('decision') or {}).get('verdict')}; "
          f"overall: {doc.get('overall')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
