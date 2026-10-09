"""Wave-2 lab: the shared, leak-proof foundation every trade-flow hypothesis uses.

Research only. Nothing here is wired into the bot and nothing may be imported from ``src/``.
Data: the CryptoHouse Parquet tables in ``FLOW`` (``research/flow/README.md``), read-only.

THE CONTRACT (read this before writing a hypothesis)
====================================================
* **Splits** are by coin creation time, never shuffled (:data:`SPLIT_BOUNDS`)::

      confirm  2026-09-16 00:00 -> 10-01 00:00   one run per hypothesis, never searched (env LAB2_ALLOW_CONFIRM=1)
      train    2026-10-01 00:00 -> 10-05 00:00   all searching
      val      2026-10-05 00:00 -> 10-06 12:00   <= 2 configs per hypothesis, from a shortlist written BEFORE
                                                 the first VAL run (:func:`write_shortlist`)
      test     2026-10-06 12:00 -> 10-07 19:37:30  one run per hypothesis (env LAB2_ALLOW_TEST=1)
      final_*  the census day, split into the lab's thirds (research/lab/splits.json):
               final_train = DEBUG ONLY (never choose parameters on it); final_val / final_test / final
               are a one-shot holdout (env LAB2_ALLOW_FINAL=1).

  A graduate whose CreateEvent was not scanned (``has_create = 0``) gets its creation time from the census when
  it is a census coin, otherwise its latest possible creation time ``g_ts - 1800`` (the curve scan looks back
  30 min before its chunk). That can only move a coin into a LATER split, never an earlier one.
* **Universe** (:func:`load`): tradeable = SOL-quoted, not Mayhem (derived: CreateEvent flag OR real SOL at
  completion < 80), virtual reserve known; plus data quality: a B2 row for the canonical pool and every chain
  hour of [g, g + 180 min) present in ``b2_bars``. Every exclusion is counted in ``Dataset.coverage``.
* **No lookahead** (:class:`AsOf`): a decision at time ``t`` sees events with time <= ``tau = t - 20 s`` only.

  - a minute bar is visible only once its minute ended (``minute_ts + 60 <= tau``);
  - ``w120_*`` from ``tau >= g + 120`` (t >= g + 140), ``w300_*`` from ``tau >= g + 300``;
  - AGENT identity (``agent_present``, ``agent_wallet`` ...) from ``tau >= agent_known_at`` (its 4th buy) or,
    when there is no agent, from the end of the AGENT window (g + 420 s); window totals (``agent_sol``,
    ``agent_slices``, ``w120_top5_share_ex_agent`` ...) only after the window AND known_at. The causal flag
    ``agent_detected`` (= known_at <= tau) is always legal;
  - the per-minute ``agent_buy_sol`` column is NaN before ``agent_known_at``;
  - forbidden as features (they encode the future or our collection): ``n_chunks``, ``n_pools``, ``virt_sol``,
    ``w_exact``, ``virt_known``, ``price_repaired``, current-state census fields, split/universe flags. Any column
    without a legality rule is forbidden too (fail closed). Access raises :class:`ForbiddenFeature`; a field that
    is legal later raises :class:`NotYetKnown`;
  - NULL is ``None``, never 0: graduates without creation data have NULL launch / bundle / sniper / creator /
    curve-life columns and ``grad_delay_s`` (use ``grad_delay_lb_s``, a lower bound). ``None >= x`` raises.
* **Fills** (:func:`simulate_buy`, :func:`simulate_sell`): PumpSwap constant product on the PRICING reserve
  X = x + v (real + virtual quote reserve; X = close * y_close exactly in B2), k = X * y from the state at the
  start of the fill minute, fees from ``research/lab/costs.py`` (pool tier by market cap AS OF THE TRADE DATE
  via :func:`fee_bps_at`, + Jupiter Ultra 10 bps, + 20 bps paper slippage/MEV haircut), network fee per swap,
  optional token-account rent. Identical to ``costs.CostModel`` for the same k (tested).
* **Minute-bar fill modes** (:class:`FillConfig`, default ``"worst"``, PLAN 3.3 wick_fill="worst"): decisions
  happen on a grid ``t = minute boundary + 20 s``; the order lands at ``t + latency_s`` (30 s) in the next bar.
  Entry fills at max(open, high) of that bar; exits (signal, time, stop, trail) at min(open, low); a
  take-profit at the level only if the bar closed above it, else at the body top. Stops are checked on the
  entry bar too (high first, then low). ``"open"`` mode is the optimistic reference. X1 will replace this.
* **Backtest** (:func:`backtest`): at most ONE entry per coin per rule; per-trade records
  (mint, t_in, t_out, ret_net, reason ...); a matched-timing random-entry PLACEBO (20 draws per signal, a random
  eligible coin of the same split, decision age within +-120 s, same exit rule); a costs x1.5 stress run on
  every guarded split; every non-debug run is logged in ``research/lab2/trials.json`` and every distinct
  (hypothesis, params) is a TRIAL for the deflated Sharpe ratio (baseline: the lab's 2,575 logged configs).
* **Stats and verdicts**: :func:`describe` (mean, median, win rate, coin-bootstrap CIs, top-coin share,
  mean without the top 2 trades, halves), :func:`deflated_sharpe`, :func:`portfolio_sim` ($100, 5 slots),
  :func:`verdict_entry` (PLAN 3.5: PASS / FAIL / UNDERPOWERED / INCOMPLETE) and :func:`auto_rejections`
  (PLAN 3.6), :func:`verdict_veto`.

Minimal hypothesis::

    from common import backtest, Enter, Exit, ExitSpec, SKIP

    def strat(snap, p, pos):
        if pos is None:
            if snap.age_s < p["age_min"] * 60:
                return None
            if not snap.alive():
                return SKIP                      # never trade this coin
            return Enter(exits=ExitSpec(stop_pct=0.25, max_hold_s=1800))
        return None                              # exits: mechanical only

    res = backtest(strat, "train", {"age_min": 10}, hypothesis="demo")
    print(res.summary())
"""

from __future__ import annotations

import calendar
import contextlib
import dataclasses
import fcntl
import gzip
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from statistics import NormalDist
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
_SCRATCH = Path("/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad")


def _load_module(name: str, path: Path):
    """Import a research module by file path under a unique name (``costs``/``features``/``stats`` are generic)."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lab_costs = _load_module("lab2_lab_costs", RESEARCH / "lab" / "costs.py")
flow_features = _load_module("lab2_flow_features", RESEARCH / "flow" / "features.py")
CostModel = lab_costs.CostModel
SolUsd = lab_costs.SolUsd


def flow_dir() -> Path:
    return Path(os.environ.get("LAB2_FLOW", str(_SCRATCH / "flow")))


def lab_data_dir() -> Path:
    return Path(os.environ.get("LAB_DATA", str(_SCRATCH / "lab")))


def trials_path() -> Path:
    return Path(os.environ.get("LAB2_TRIALS", str(HERE / "trials.json")))


def shortlist_dir() -> Path:
    return Path(os.environ.get("LAB2_SHORTLISTS", str(HERE / "shortlists")))


LAB_SPLITS_JSON = RESEARCH / "lab" / "splits.json"


def utc_ts(s: str) -> int:
    """'YYYY-MM-DD[ HH:MM[:SS]]' (UTC) -> epoch seconds."""
    fmt = {10: "%Y-%m-%d", 16: "%Y-%m-%d %H:%M", 19: "%Y-%m-%d %H:%M:%S"}[len(s)]
    return calendar.timegm(time.strptime(s, fmt))


def utc_str(ts: float | None) -> str | None:
    if ts is None or (isinstance(ts, float) and math.isnan(ts)):
        return None
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(float(ts)))


# =========================================================================== constants

DECISION_LAG_S = 20          # PLAN 3.2: features use events with time <= tau = t - 20 s
GRID_OFFSET_S = 20           # decisions at minute boundary + 20 s -> the bar that just ended is visible
N_BARS = 180                 # dense minute index 0..179: [m0, m0 + 10800) lies inside the B2 window [g, g + 180 min)
AGENT_WINDOW_S = int(flow_features.AGENT_WINDOW_S)   # 420 s (audit fix 2)
W120_S, W300_S = 120, 300
TOKEN_SUPPLY = 1_000_000_000  # pump.fun market cap = price x 1e9 tokens
WSOL = "So11111111111111111111111111111111111111112"
MAYHEM_RSOL = 80.0
SLOW_CREATE_LOOKBACK_S = 1800  # has_create = 0  =>  created < g_ts - 1800 (curve scan lookback)
PLACEBO_AGE_TOL_S = 120        # PLAN 3.4: random entry within +-2 min of the same age
B2_HORIZON_S = 60 * N_BARS     # backfill.HORIZON_S: B2 holds [g, g + 180 min) of every pool
V_MIGRATION_SOL = 17.584505289  # PumpSwap virtual quote reserve of 2026-10 migration pools (fallback only)
BLOCK_S = 6 * 3600             # PLAN 3.4 day-block bootstrap: 6-hour blocks (TEST / VAL span only 1.3-1.5 days)
MAX_CENSORED_SHARE = 0.10      # a verdict cannot PASS when more trades than this end at the data horizon

# Pooled program accounts that appear as the event `user` but sign for many people (audit 3.6). Exclude them
# from wallet features, repeat-buyer counts, orphan / TRANSFEREE logic. Extend via research/lab2/pooled_accounts.json.
POOLED_ACCOUNTS = frozenset({"ARu4n5mFdZogZAravu7CcizaojWnS6oqka37gdLT5SZn"})
# Never the signer, one wallet signs for it: probably ONE bot's PDA (an entity, not pooled). Not excluded by default.
SUSPECT_PDA_ACCOUNTS = frozenset({"BwWK17cbHxwWBKZkUYvzxLcNQ1YVyaFezduWbtm2de6s"})

# PLAN 3.4 variant limits per hypothesis (a warning + ledger flag when exceeded)
VARIANT_LIMITS = {"G1": 3, "S1": 8, "D1": 6, "M1": 4, "H1": 2}
# wave-1 lab configurations logged (research/lab/RESULTS.md 2.5; the PLAN quotes "about 2,300")
BASELINE_TRIALS = {"lab_wave1_logged_configs": 2575}

# PLAN minimum samples (used for the UNDERPOWERED flags)
PLAN_MIN = {
    "entry_test_trades": 60, "entry_test_coins": 40,      # 3.5.1
    "x1_train_r0_trades": 500, "x1_val_r0_trades": 200,   # 4.1 (R0 = 1 entry / coin / seed, 5 seeds)
    "g1_val_flagged_coins": 200,                          # 4.2
    "m1_train_trades": 60,                                # 4.5
    "veto_val_flagged": 30,                               # 3.5 veto bar needs a CI: lab2 floor, not PLAN
}


def _lab_splits() -> dict:
    try:
        return json.loads(LAB_SPLITS_JSON.read_text())
    except (OSError, ValueError):
        return {}


_LS = _lab_splits()
FINAL_LO = int((_LS.get("bounds_created_ts") or {}).get("train", [1791401850])[0])   # first census coin, 10-07 19:37:30
SPLIT_BOUNDS: dict[str, tuple[int, int]] = {
    "confirm": (utc_ts("2026-09-16"), utc_ts("2026-10-01")),
    "train": (utc_ts("2026-10-01"), utc_ts("2026-10-05")),
    "val": (utc_ts("2026-10-05"), utc_ts("2026-10-06 12:00")),
    "test": (utc_ts("2026-10-06 12:00"), FINAL_LO),
}
FINAL_SPLITS = ("final_train", "final_val", "final_test")
ALL_SPLITS = ("confirm", "train", "val", "test", *FINAL_SPLITS)
DEBUG_SPLITS = frozenset({"final_train"})
GUARD_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL",
             "final_val": "LAB2_ALLOW_FINAL", "final_test": "LAB2_ALLOW_FINAL", "val": "LAB2_ALLOW_VAL"}
ONE_RUN_SPLITS = frozenset({"test", "confirm", "final", "final_val", "final_test"})


class SplitLocked(PermissionError):
    """A guarded split was requested without its permission (env flag, shortlist or one-run rule)."""


class DataNotReady(SplitLocked):
    """The data a run would use breaks the data contract (SOL/USD lookahead, mid-run hours, stop rule 1)."""


class ForbiddenFeature(KeyError):
    """A column that encodes the future (or our data collection) was used as a feature."""


class NotYetKnown(KeyError):
    """A legal field was read before the time it becomes knowable."""


# =========================================================================== fees by date

# (effective_from_ts, SOL tier table [(upper mcap in SOL, total bps)], source). costs.py holds the page
# "Last Updated 20 May 2026"; the lens reports cite a 2026-10-08 update whose quoted totals (1.25 % < 420 SOL,
# 1.20 % to 1,470 SOL, 0.30 % >= 98,240 SOL) match it. Add a row when a real diff is found (PLAN 3.1).
FEE_SCHEDULES: tuple[tuple[int, tuple, str], ...] = (
    (utc_ts("2026-05-20"), lab_costs.PUMPSWAP_SOL_TIERS, "pump.fun/docs/fees 'Last Updated 20 May 2026' (costs.py)"),
)


def fee_schedule_at(ts: float) -> tuple:
    best = None
    for frm, tiers, _src in FEE_SCHEDULES:
        if ts >= frm and (best is None or frm >= best[0]):
            best = (frm, tiers)
    if best is None:
        raise ValueError(f"no PumpSwap fee schedule known for {utc_str(ts)}")
    return best[1]


def fee_bps_at(ts: float, mcap_sol: float) -> float:
    """Canonical PumpSwap SOL-pool fee (total bps, one side) at market cap ``mcap_sol`` as of ``ts``."""
    for upper, bps in fee_schedule_at(ts):
        if mcap_sol < upper:
            return float(bps)
    return 30.0


# =========================================================================== price / fill helpers


def pool_price(x_real: float, v_virtual: float, y_tokens: float) -> float:
    """PumpSwap price in SOL per whole token: (x + v) / y. Ignoring v under-prices fresh pools."""
    return (x_real + v_virtual) / y_tokens


def reserves_at_price(k: float, price: float) -> tuple[float, float]:
    """(X, y) on the curve X * y = k at ``price`` = X / y. X is the PRICING reserve (real + virtual)."""
    return math.sqrt(k * price), math.sqrt(k / price)


def side_bps(ts: float, mcap_sol: float, cost: CostModel) -> float:
    """Fee-like bps for one side: pool tier (by date) x fee_mult + Ultra + paper slippage/MEV haircut."""
    return cost.fee_mult * fee_bps_at(ts, mcap_sol) + cost.ultra_bps + cost.mev_bps


def network_sol(cost: CostModel) -> float:
    """SOL per swap transaction (base + priority); rent is separate (FillConfig.rent_usd)."""
    return cost.base_fee_lamports / 1e9 + cost.priority_sol


def simulate_buy(sol_in: float, price: float, k: float, ts: float, cost: CostModel | None = None) -> tuple[float, dict]:
    """Spend ``sol_in`` SOL (network fee excluded) at pool price ``price`` on a pool with invariant ``k`` (X*y).

    Same math as ``costs.CostModel.buy`` with the pool's own k: fee-like bps come off the input, then
    constant-product impact on (X / impact_mult, y / impact_mult). Returns (tokens, breakdown)."""
    cost = cost or CostModel()
    if sol_in <= 0 or price <= 0 or k <= 0:
        return 0.0, {"fee_sol": 0.0, "impact_sol": 0.0, "fee_bps": 0.0, "X": 0.0}
    bps = side_bps(ts, price * TOKEN_SUPPLY, cost)
    net = sol_in * (1.0 - bps / 1e4)
    X, _ = reserves_at_price(k, price)
    X /= cost.impact_mult
    y = X / price
    tokens = y * net / (X + net)
    return tokens, {"fee_sol": sol_in - net, "impact_sol": net - tokens * price, "fee_bps": bps, "X": X}


def simulate_sell(tokens: float, price: float, k: float, ts: float, cost: CostModel | None = None) -> tuple[float, dict]:
    """Sell ``tokens`` at pool price ``price`` (invariant ``k``) -> (SOL out before the network fee, breakdown)."""
    cost = cost or CostModel()
    if tokens <= 0 or price <= 0 or k <= 0:
        return 0.0, {"fee_sol": 0.0, "impact_sol": 0.0, "fee_bps": 0.0, "X": 0.0}
    bps = side_bps(ts, price * TOKEN_SUPPLY, cost)
    X, _ = reserves_at_price(k, price)
    X /= cost.impact_mult
    y = X / price
    gross = X * tokens / (y + tokens)
    out = gross * (1.0 - bps / 1e4)
    return out, {"fee_sol": gross - out, "impact_sol": tokens * price - gross, "fee_bps": bps, "X": X}


def round_trip_pct(sol_in: float, price: float, k: float, ts: float, cost: CostModel | None = None,
                   rent_sol: float = 0.0) -> float:
    """% of ``sol_in`` lost buying then selling at an unchanged price (incl. 2 network fees and rent)."""
    cost = cost or CostModel()
    tok, _ = simulate_buy(sol_in, price, k, ts, cost)
    back, _ = simulate_sell(tok, price, k, ts, cost)
    return (sol_in - back + 2 * network_sol(cost) + rent_sol) / sol_in * 100.0


# =========================================================================== field legality

CREATE_COLS = ("name", "symbol", "uri", "creator", "create_user", "token_program", "is_mayhem",
               "curve_quote_mint", "vsol0", "c_slot", "c_ts")
LAUNCH_PREFIXES = ("l_", "z_", "sn60_")
CURVE_LIFE_COLS = ("curve_buy_sol", "curve_sell_sol", "curve_buy_tok", "curve_sell_tok", "curve_n_buys",
                   "curve_n_sells", "curve_n_buyers", "curve_n_sellers", "curve_top1_buy_sol", "curve_top3_buy_sol",
                   "completer_sol", "completer30")
G_COLS = ("g_slot", "g_ts", "completer", "rsol_complete", "grad_delay_s", "grad_delay_lb_s", "mayhem",
          "has_create", "curve_partial", "created_exact", "created_ts")
G_PREFIXES = ("creator_", "first20_")
POOL_COLS = ("pool", "pool_slot", "pool_ts", "pool_creator")          # known once the pool exists (g + 0-6 s)
# the migration's initial reserves and quote follow from the completed curve: known at g
G_COLS = G_COLS + ("pool_base0", "pool_quote0", "pool_quote_mint", "sol_quoted")
W120_COLS = ("w120_buy_sol", "w120_sell_sol", "w120_n_buyers", "w120_n_sellers", "w120_top10")
W300_COLS = ("w300_buy_sol", "w300_sell_sol", "w300_n_buyers", "w300_n_sellers", "w300_top10")
AGENT_ID_COLS = ("agent_present", "agent_wallet", "agent_known_at", "agent_first_offset_s")
AGENT_WIN_COLS = ("agent_slices", "agent_sol", "agent_median_gap", "agent_gap_cv", "agent_gap_band_share",
                  "agent_plan_rule", "w120_top5_share_ex_agent")
FORBIDDEN = frozenset({
    # encode survival, later pools, later chunks or our collection (README 8, audit 3.8)
    "n_chunks", "n_pools", "virt_sol", "virt_max_sol", "w_exact", "virt_known", "price_repaired", "n_trades",
    "first_m", "last_m", "truncated", "minute_idx",
    # universe / split bookkeeping (derived partly from forbidden columns)
    "split", "tradeable", "usable", "exclude_reason", "created_for_split", "created_ub_ts", "in_census",
    "b2_complete", "census_split",
    # current-state fields (PLAN 3.6): census / RugCheck / Jupiter / DexScreener snapshots
    "market_cap", "usd_market_cap", "ath_market_cap", "ath_market_cap_timestamp", "reply_count", "last_reply",
    "is_currently_live", "last_trade_timestamp", "complete", "real_sol_reserves", "real_token_reserves",
    "virtual_sol_reserves", "virtual_token_reserves", "updated_at", "livestream_ban_expiry", "is_banned",
    "hide_banner", "king_of_the_hill_timestamp", "rugcheck_score", "organic_score", "organicScore",
    "holder_count", "holderCount", "numNetBuyers", "dexscreener_boost", "dexscreener_profile",
})


def _legal_from(name: str, row: Mapping[str, Any], g: float) -> float | None:
    """Earliest tau at which ``name`` may be read for this coin; None = forbidden / no rule (fail closed)."""
    if name in FORBIDDEN:
        return None
    if name == "mint":
        return -math.inf
    created = row.get("created_ts")
    exact = bool(row.get("created_exact")) and created is not None and not _isnan(created)
    if name in CREATE_COLS:
        return float(created) if exact else g
    if name.startswith(LAUNCH_PREFIXES):
        return min(float(created) + 120.0, g) if exact else g
    if name in G_COLS or name in CURVE_LIFE_COLS or name.startswith(G_PREFIXES):
        return g
    if name in POOL_COLS:
        pt = row.get("pool_ts")
        return float(pt) if pt is not None and not _isnan(pt) else g
    if name in W120_COLS:
        return g + W120_S
    if name in W300_COLS:
        return g + W300_S
    known = row.get("agent_known_at")
    present = bool(row.get("agent_present")) and known is not None and not _isnan(known)
    if name in AGENT_ID_COLS:
        return float(known) if present else g + AGENT_WINDOW_S
    if name in AGENT_WIN_COLS:
        return max(g + AGENT_WINDOW_S, float(known)) if present else g + AGENT_WINDOW_S
    return None


def _isnan(v: Any) -> bool:
    return isinstance(v, float) and math.isnan(v)


def _clean(v: Any) -> Any:
    """NaN / NA -> None (so arithmetic on a missing value raises instead of silently passing)."""
    if v is None or v is pd.NA:
        return None
    if isinstance(v, (float, np.floating)) and math.isnan(float(v)):
        return None
    if isinstance(v, np.generic):
        return v.item()
    return v


# =========================================================================== data loading

_CACHE: dict[tuple, pd.DataFrame] = {}


def _read_parquet(path: Path) -> pd.DataFrame:
    """Read a Parquet table, cached by (path, mtime, size); retries once if a consolidation is mid-write."""
    for attempt in range(3):
        try:
            st = path.stat()
            key = (str(path), st.st_mtime_ns, st.st_size)
            if key not in _CACHE:
                _CACHE.clear() if len(_CACHE) > 8 else None
                _CACHE[key] = pd.read_parquet(path)
            return _CACHE[key]
        except Exception as e:  # pyarrow raises ArrowInvalid on a half-written file
            if attempt == 2:
                raise
            warnings.warn(f"retrying read of {path.name}: {e}")
            time.sleep(2.0)
    raise RuntimeError("unreachable")


@dataclass(frozen=True)
class Census:
    split_of: Mapping[str, str]          # mint -> final_train | final_val | final_test
    created_ts: Mapping[str, float]      # mint -> creation time (exact, from the census)
    started_ts: float
    created_max_ts: float
    train_hi: float
    val_hi: float

    @classmethod
    def load(cls, lab: Path | None = None, splits: dict | None = None) -> "Census":
        splits = splits if splits is not None else _LS
        split_of: dict[str, str] = {}
        for lab_name, name in (("train", "final_train"), ("validation", "final_val"), ("test", "final_test")):
            for m in splits.get(lab_name, []):
                split_of[m] = name
        created: dict[str, float] = {}
        started, cmax = math.inf, math.inf
        try:
            cen = json.loads(((lab or lab_data_dir()) / "census.json").read_text())
            created = {c["mint"]: c["created_timestamp"] / 1000.0 for c in cen["coins"]}
            started, cmax = float(cen["census_started_ts"]), float(cen["created_max_ts"])
        except (OSError, ValueError, KeyError):
            warnings.warn("census.json not found: census creation times unavailable")
        b = splits.get("bounds_created_ts") or {}
        return cls(split_of=MappingProxyType(split_of), created_ts=MappingProxyType(created), started_ts=started,
                   created_max_ts=cmax, train_hi=float((b.get("train") or [0, FINAL_LO])[1]),
                   val_hi=float((b.get("validation") or [0, FINAL_LO])[1]))

    @classmethod
    def empty(cls) -> "Census":
        return cls(MappingProxyType({}), MappingProxyType({}), math.inf, math.inf, float(FINAL_LO), float(FINAL_LO))


def assign_split(created_ts: float | None, g_ts: float, mint: str, census: Census) -> tuple[str, float, bool]:
    """-> (split, created_ts used for the split, created_exact).

    Rules (see module doc): census coins -> their lab third; created unknown -> latest possible creation
    (g - 1800); a non-census coin that graduated after the census started -> final_test; a non-census coin whose
    creation is unknown, graduated before the census, and could only lie in FINAL by its upper bound must
    have been created before the census window (else the census would hold it) -> test (sealed)."""
    exact = created_ts is not None and not _isnan(created_ts) and created_ts > 0
    if mint in census.created_ts:
        c, exact = float(census.created_ts[mint]), True
    elif exact:
        c = float(created_ts)
    else:
        c = float(g_ts) - SLOW_CREATE_LOOKBACK_S
    if mint in census.split_of:
        return census.split_of[mint], c, exact
    if c >= FINAL_LO:
        if g_ts >= census.started_ts or c > census.created_max_ts:
            return "final_test", c, exact
        if not exact:
            return "test", c, exact
        if c <= census.train_hi:
            return "final_train", c, exact
        if c <= census.val_hi:
            return "final_val", c, exact
        return "final_test", c, exact
    for name, (lo, hi) in SPLIT_BOUNDS.items():
        if lo <= c < hi:
            return name, c, exact
    return "out", c, exact


def _normalize_graduates(g: pd.DataFrame, census: Census) -> pd.DataFrame:
    """Derived flags, exact-or-bounded creation time, NULL (never 0) for unobserved launch / curve-life columns."""
    g = g.copy()
    hc = g["has_create"].astype(bool) if "has_create" in g else pd.Series(True, index=g.index)
    g["sol_quoted"] = g["pool_quote_mint"] == WSOL
    is_m = g["is_mayhem"].fillna(0).astype(bool) & hc if "is_mayhem" in g else False
    g["mayhem"] = is_m | (g["sol_quoted"] & (g["rsol_complete"].fillna(0) < MAYHEM_RSOL))
    g["curve_partial"] = ~hc
    null_cols = [c for c in g.columns if c in CREATE_COLS or c in CURVE_LIFE_COLS
                 or c.startswith(LAUNCH_PREFIXES) or c.startswith(G_PREFIXES)]
    for c in null_cols:
        if pd.api.types.is_numeric_dtype(g[c]) or pd.api.types.is_bool_dtype(g[c]):
            g[c] = g[c].astype("float64")
        else:
            g[c] = g[c].astype(object)
        g.loc[~hc, c] = np.nan if g[c].dtype == "float64" else None
    rows = [assign_split(ct if h else None, gt, m, census)
            for ct, gt, m, h in zip(g["c_ts"].fillna(0).to_numpy(float), g["g_ts"].to_numpy(float),
                                    g["mint"].to_numpy(object), hc.to_numpy(bool))]
    g["split"] = [r[0] for r in rows]
    g["created_for_split"] = [r[1] for r in rows]
    g["created_exact"] = [r[2] for r in rows]
    g["created_ts"] = np.where(g["created_exact"], g["created_for_split"], np.nan)
    g["created_ub_ts"] = g["created_for_split"]
    g["in_census"] = g["mint"].isin(list(census.split_of))
    g["grad_delay_s"] = np.where(g["created_exact"], g["g_ts"] - g["created_ts"], np.nan)
    g["grad_delay_lb_s"] = np.where(g["created_exact"], g["grad_delay_s"], float(SLOW_CREATE_LOOKBACK_S))
    return g


BAR_ARRAYS = ("o", "h", "l", "c", "X", "y", "x_real", "buy_sol", "sell_sol", "buy_tok", "sell_tok", "n_buys",
              "n_sells", "n_dust", "n_buyers", "n_sellers", "top5_buy_sol", "agent_buy_sol", "traded")
_FLOW_SRC = {"buy_sol": "buy_sol", "sell_sol": "sell_sol", "buy_tok": "buy_tok", "sell_tok": "sell_tok",
             "n_buys": "n_buys", "n_sells": "n_sells", "n_dust": "n_dust", "n_buyers": "n_buyers",
             "n_sellers": "n_sellers", "top5_buy_sol": "top5_buy_sol", "agent_buy_sol": "agent_buy_sol"}


@dataclass
class CoinData:
    """One coin: static row, dense per-minute arrays (read-only), legality table. Never handed to strategies."""

    mint: str
    pool: str
    g: float
    m0: int
    row: Mapping[str, Any]
    arr: Mapping[str, np.ndarray]
    agent_nan: np.ndarray
    init_X: float                # pricing reserve before the first pool trade: pool_quote0 + virtual reserve
    init_y: float
    legal: Mapping[str, float]
    split: str
    trades: pd.DataFrame | None = None

    @property
    def n(self) -> int:
        return N_BARS

    def k_before(self, j: int) -> float:
        """Pool invariant X*y at the START of bar j (state after the last trade before it)."""
        if j <= 0:
            return self.init_X * self.init_y
        return float(self.arr["X"][j - 1] * self.arr["y"][j - 1])

    def bar_of(self, ts: float) -> int:
        return int((ts - self.m0) // 60)

    def bar_start(self, j: int) -> int:
        return self.m0 + 60 * j


def _dense(bars: pd.DataFrame, m0: int, init_X: float, init_y: float) -> dict[str, np.ndarray]:
    """Dense per-minute arrays. ``init_X`` is the PRICING reserve before the first pool trade (x0 + v).

    B2 prices the pool's first trade(s) without the virtual reserve: the first traded bar's ``open`` is x0 / y0 and
    its ``low`` mixes no-v prices (both ~17 % low on the census day; closes are exact). That bar's open is therefore
    rebuilt from the initial reserves and its low is cut to the body (min(open, close)): no wick information."""
    out = {k: np.zeros(N_BARS) for k in BAR_ARRAYS}
    idx = ((bars["minute_ts"].to_numpy(np.int64) - m0) // 60).astype(np.int64)
    ok = (idx >= 0) & (idx < N_BARS)
    idx = idx[ok]
    b = bars.loc[ok]
    for k, src in _FLOW_SRC.items():
        if src in b:
            out[k][idx] = b[src].fillna(0).to_numpy(float)
    traded = np.zeros(N_BARS, bool)
    traded[idx] = True
    o = np.full(N_BARS, np.nan)
    h, l, c = o.copy(), o.copy(), o.copy()
    xr, yc = o.copy(), o.copy()
    o[idx], h[idx], l[idx], c[idx] = (b[f].to_numpy(float) for f in ("open", "high", "low", "close"))
    xr[idx], yc[idx] = b["x_close"].to_numpy(float), b["y_close"].to_numpy(float)
    last_c, last_y, last_x = init_X / init_y, init_y, None
    X = np.empty(N_BARS)
    first = True
    for i in range(N_BARS):
        if traded[i] and np.isfinite(c[i]) and np.isfinite(yc[i]) and yc[i] > 0:
            last_c, last_y, last_x = c[i], yc[i], xr[i]
            if first:                       # the pre-first-trade price is the initial pool (see docstring)
                o[i] = init_X / init_y
                l[i] = min(o[i], c[i])
                first = False
            if not np.isfinite(o[i]):
                o[i] = c[i]
            h[i] = max(h[i], o[i], c[i]) if np.isfinite(h[i]) else max(o[i], c[i])
            l[i] = min(l[i], o[i], c[i]) if np.isfinite(l[i]) else min(o[i], c[i])
        else:
            traded[i] = False
            o[i] = h[i] = l[i] = c[i] = last_c
            yc[i] = last_y
            xr[i] = last_x if last_x is not None else np.nan
        X[i] = c[i] * yc[i]   # pricing reserve x + v (exact: close = (x + v) / y)
    out.update({"o": o, "h": h, "l": l, "c": c, "X": X, "y": yc, "x_real": xr, "traded": traded.astype(float)})
    for v in out.values():
        v.setflags(write=False)
    return out


def _b2_hours(bars: pd.DataFrame) -> set[int]:
    return set((bars["minute_ts"].to_numpy(np.int64) // 3600 * 3600).tolist()) if len(bars) else set()


def _hours_needed(g: float) -> list[int]:
    m0 = int(g) // 60 * 60
    return list(range(m0 // 3600 * 3600, (m0 + 60 * N_BARS - 1) // 3600 * 3600 + 1, 3600))


# =========================================================================== completeness of the Parquet snapshot


@dataclass(frozen=True)
class Completeness:
    """Which B2 (pool, chain hour) cells and which curve hours the Parquet snapshot holds COMPLETELY.

    ``source="raw_chunks"`` (:func:`completeness_from_flow`): a cell is ``ok`` only when B2 chunks consolidated into
    the Parquet (file mtime <= the Parquet's) cover the whole hour for that pool. The backfill splits timed-out hours
    into halves and stops between them, and marks pools done WITH an error ("timeout at minimum chunk", "too large
    for one pool"), so "some bar exists in this hour" does not mean every pool's hour is there; a missing half would
    otherwise become frozen, zero-volume bars. ``source="bars_only"`` (synthetic frames, :meth:`from_bars`) keeps
    the old hour-level rule: an hour with any bar is complete for every pool."""

    source: str
    bar_hours: frozenset                       # chain hours with >= 1 bar in the Parquet
    cells: frozenset | None                    # {(pool, hour)} fully covered; None = hour-level rule
    errors: Mapping                            # {(pool, hour): message} the backfill gave up on
    curve_hours: frozenset | None              # fully scanned curve hours; None = hours holding a graduate
    b2_fetched: Mapping                        # chain hour -> newest consolidated B2 chunk fetch time (epoch s)
    snapshot_utc: str | None

    @classmethod
    def from_bars(cls, b2_bars: pd.DataFrame) -> "Completeness":
        return cls(source="bars_only", bar_hours=frozenset(_b2_hours(b2_bars)), cells=None, errors={},
                   curve_hours=None, b2_fetched={}, snapshot_utc=None)

    def cell(self, pool: str, hour: int) -> str:
        """``ok`` | ``error`` (the backfill gave up on this pool-hour) | ``missing`` (not, or not yet, consolidated)."""
        if self.cells is None:
            return "ok" if hour in self.bar_hours else "missing"
        if (pool, hour) in self.errors:
            return "error"
        return "ok" if (pool, hour) in self.cells and hour in self.bar_hours else "missing"

    def hour_status(self, hour: int, active_pools: Iterable[str]) -> str:
        """``done`` (every pool active in the hour is ok or errored, and its graduates are known), ``partial``
        (mid-run: some pools are in, others not yet) or ``absent``."""
        if self.cells is None:
            return "done" if hour in self.bar_hours else "absent"
        st = [self.cell(p, hour) for p in active_pools]
        any_ok = any(x == "ok" for x in st)
        if self.curve_hours is not None and any(h not in self.curve_hours
                                                for h in range(hour - B2_HORIZON_S // 3600 * 3600, hour + 3600, 3600)):
            return "partial" if any_ok else "absent"     # graduates of the hour not all known yet
        if all(x != "missing" for x in st):
            return "done"
        return "partial" if any_ok else "absent"


def _cache_dir() -> Path:
    return Path(os.environ.get("LAB2_CACHE", str(_SCRATCH / "lab2_cache")))


_CHUNK_MEM: dict[str, list] = {}


def _b2_chunk_meta(paths: Sequence[Path]) -> dict[str, tuple[int, int, tuple, float]]:
    """name -> (t0, t1, pools, mtime) of B2 raw chunks; parsed once per (name, mtime, size), cached on disk."""
    cache_p = _cache_dir() / "b2_chunk_index.json"
    disk: dict[str, list] = {}
    try:
        disk = json.loads(cache_p.read_text())
    except (OSError, ValueError):
        pass
    out, keep, dirty = {}, {}, False
    for p in paths:
        st = p.stat()
        key = f"{p.name}|{st.st_mtime_ns}|{st.st_size}"
        m = _CHUNK_MEM.get(key) or disk.get(key)
        if m is None:
            with gzip.open(p, "rt") as fh:
                d = json.load(fh)
            m = [int(d["t0"]), int(d["t1"]), sorted({str(a[0]) for a in (d.get("params") or {}).get("act") or []})]
            dirty = True
        _CHUNK_MEM[key] = keep[key] = m
        out[p.name] = (int(m[0]), int(m[1]), tuple(m[2]), st.st_mtime)
    if dirty:
        with contextlib.suppress(OSError):
            cache_p.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_p.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(keep))
            os.replace(tmp, cache_p)
    return out


def _covers(intervals: list[tuple[int, int]], lo: int, hi: int) -> bool:
    x = lo
    for a, b in sorted(intervals):
        if a > x:
            return False
        x = max(x, b)
        if x >= hi:
            return True
    return x >= hi


def completeness_from_flow(flow: Path | None = None, with_bar_hours: bool = True) -> Completeness:
    """Completeness of the CURRENT Parquet snapshot in ``flow`` from the backfill's raw chunks (``raw/b2``,
    ``raw/curve``) and ``state.json`` errors. Chunks fetched after the Parquet was written are not in it (the
    backfill keeps fetching while the snapshot stays put), so they never count; ``state.json`` alone would."""
    f = Path(flow or flow_dir())
    snap_b2 = (f / "b2_bars.parquet").stat().st_mtime if (f / "b2_bars.parquet").exists() else math.inf
    snap_g = (f / "graduates.parquet").stat().st_mtime if (f / "graduates.parquet").exists() else math.inf
    cover: dict[tuple[str, int], list] = {}
    fetched: dict[int, float] = {}
    meta = _b2_chunk_meta(sorted((f / "raw" / "b2").glob("*.json.gz"))) if (f / "raw" / "b2").exists() else {}
    for t0, t1, pools, mt in meta.values():
        if mt > snap_b2:
            continue
        hour = t0 // 3600 * 3600
        fetched[hour] = max(fetched.get(hour, 0.0), mt)
        for pl in pools:
            cover.setdefault((pl, hour), []).append((t0, t1))
    cells = frozenset(k for k, iv in cover.items() if _covers(iv, k[1], k[1] + 3600))
    curve_iv: dict[int, list] = {}
    if (f / "raw" / "curve").exists():
        for p in (f / "raw" / "curve").glob("*.json.gz"):
            try:
                a, b = (int(x) for x in p.name.split(".")[0].split("-")[:2])
            except ValueError:
                continue
            if p.stat().st_mtime > snap_g:
                continue
            for h in range(a // 3600 * 3600, b, 3600):
                curve_iv.setdefault(h, []).append((max(a, h), min(b, h + 3600)))
    curve = frozenset(h for h, iv in curve_iv.items() if _covers(iv, h, h + 3600))
    errors: dict[tuple[str, int], str] = {}
    try:
        state = json.loads((f / "state.json").read_text())
        for h, st in (state.get("b2") or {}).items():
            for pl, msg in (st.get("errors") or {}).items():
                errors[(str(pl), int(h))] = str(msg)
    except (OSError, ValueError):
        pass
    bar_hours = frozenset(fetched)
    if with_bar_hours and (f / "b2_bars.parquet").exists():
        bar_hours = frozenset(_b2_hours(_read_parquet(f / "b2_bars.parquet")))
    return Completeness(source="raw_chunks", bar_hours=bar_hours, cells=cells, errors=errors, curve_hours=curve,
                        b2_fetched=fetched, snapshot_utc=utc_str(snap_b2) if snap_b2 < math.inf else None)


def _active_pools(g_all: pd.DataFrame) -> Callable[[int], list[str]]:
    """hour -> pools whose B2 window [g, g + 180 min) overlaps the hour (backfill.b2_pools_for)."""
    has = g_all[g_all["pool"].notna()] if "pool" in g_all else g_all.iloc[0:0]
    gt = has["g_ts"].to_numpy(float) if len(has) else np.zeros(0)
    pools = has["pool"].to_numpy(object) if len(has) else np.zeros(0, object)

    def at(hour: int) -> list[str]:
        sel = (gt < hour + 3600) & (gt + B2_HORIZON_S > hour)
        return [str(x) for x in pools[sel]]
    return at


@dataclass
class Dataset:
    """One split: usable coins (``coins``), sparse bars (``bars``), per-coin dense data, a coverage report."""

    split: str
    coins: pd.DataFrame
    bars: pd.DataFrame
    excluded: pd.DataFrame
    coverage: dict
    debug_only: bool
    sol: SolUsd
    _cd: dict[str, CoinData] = field(default_factory=dict, repr=False)

    @property
    def mints(self) -> list[str]:
        return list(self.coins["mint"])

    def coin(self, mint: str) -> CoinData:
        return self._cd[mint]

    def asof(self, mint: str, t: float) -> "AsOf":
        return AsOf(self._cd[mint], t, self.sol)

    def __len__(self) -> int:
        return len(self.coins)

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_frames(cls, split: str, graduates: pd.DataFrame, b2_coins: pd.DataFrame, b2_bars: pd.DataFrame,
                    census: Census | None = None, sol: SolUsd | None = None, trades: pd.DataFrame | None = None,
                    guard: bool = True, _internal: bool = False, extra_pooled: Iterable[str] = (),
                    completeness: Completeness | None = None) -> "Dataset":
        """``completeness`` (from :func:`completeness_from_flow`) decides which (pool, hour) cells are really in
        the tables; without it (synthetic frames) any bar in an hour makes the hour complete."""
        names = ALL_SPLITS + ("final",)
        if split not in names:
            raise ValueError(f"unknown split {split!r}; one of {names}")
        if guard:
            _check_load_guard(split, _internal)
        census = census if census is not None else Census.load()
        sol = sol or load_sol_usd()
        g = _normalize_graduates(graduates, census)
        want = set(FINAL_SPLITS) if split == "final" else {split}
        gs = g[g["split"].isin(want)].copy()
        b2c = b2_coins.drop(columns=[c for c in ("g_ts", "grad_delay_s", "sol_quoted", "mayhem") if c in b2_coins])
        gs = gs.merge(b2c, on=["mint", "pool"], how="left", indicator="b2_merge")
        comp = completeness or Completeness.from_bars(b2_bars)
        reasons = []
        for r in gs.itertuples(index=False):
            cells = [comp.cell(str(r.pool), h) for h in _hours_needed(r.g_ts)] if r.b2_merge == "both" else []
            if not r.sol_quoted:
                reasons.append("not_sol_quoted")
            elif r.mayhem:
                reasons.append("mayhem")
            elif r.b2_merge != "both":
                reasons.append("no_b2_row")
            elif not _virt_known(r):
                reasons.append("virt_unknown")
            elif "error" in cells:
                reasons.append("b2_pool_error")
            elif "missing" in cells:
                reasons.append("b2_window_incomplete")
            elif bool(getattr(r, "truncated", False) or False):
                reasons.append("truncated")
            else:
                reasons.append("")
        gs["exclude_reason"] = reasons
        gs["tradeable"] = ~gs["exclude_reason"].isin(["not_sol_quoted", "mayhem", "virt_unknown"])
        usable = gs[gs["exclude_reason"] == ""].drop(columns=["b2_merge"]).sort_values(["created_for_split", "mint"])
        excluded = gs[gs["exclude_reason"] != ""][["mint", "g_ts", "created_for_split", "exclude_reason"]]
        bars = b2_bars[b2_bars["pool"].isin(set(usable["pool"]))]
        pooled = set(POOLED_ACCOUNTS) | set(extra_pooled) | _pooled_from_file()
        cds = {}
        by_mint = {m: d for m, d in bars.groupby("mint", sort=False)}
        tr_by = {m: d for m, d in trades.groupby("mint", sort=False)} if trades is not None and len(trades) else {}
        for r in usable.to_dict("records"):
            cds[r["mint"]] = _make_coin(r, by_mint.get(r["mint"], bars.iloc[0:0]), tr_by.get(r["mint"]), pooled)
        cov = coverage_report(split, g, gs, usable, b2_bars, sol, comp)
        return cls(split=split, coins=usable.reset_index(drop=True), bars=bars, excluded=excluded.reset_index(drop=True),
                   coverage=cov, debug_only=split in DEBUG_SPLITS, sol=sol, _cd=cds)


def _virt_known(r: Any) -> bool:
    vk = getattr(r, "virt_known", None)
    if vk is not None and not _isnan(vk):
        return bool(vk)
    v = getattr(r, "virt_sol", None)
    return v is not None and not _isnan(v) and v > 0


def _pooled_from_file() -> set[str]:
    p = HERE / "pooled_accounts.json"
    try:
        return set(json.loads(p.read_text()))
    except (OSError, ValueError):
        return set()


def _make_coin(r: dict, bars: pd.DataFrame, trades: pd.DataFrame | None, pooled: set[str]) -> CoinData:
    g = float(r["g_ts"])
    m0 = int(g) // 60 * 60
    y0 = float(r.get("pool_base0") or 0) or 206.9e6
    v0 = r.get("virt_sol")
    v0 = float(v0) if v0 is not None and not _isnan(v0) and float(v0) > 0 else V_MIGRATION_SOL
    X0 = (float(r.get("pool_quote0") or 0) or 84.990359 - V_MIGRATION_SOL) + v0   # PRICING reserve x0 + v
    arr = _dense(bars, m0, X0, y0)
    agent_nan = np.full(N_BARS, np.nan)
    agent_nan.setflags(write=False)
    row = {k: _clean(v) for k, v in r.items()}
    for key in ("w120_top10", "w300_top10"):
        if isinstance(row.get(key), str):
            try:
                lst = json.loads(row[key]) or []
            except ValueError:
                lst = None
            row[key] = None if lst is None else tuple(tuple(w) for w in lst if w and w[0] not in pooled)
    legal = {}
    for name in row:
        lf = _legal_from(name, row, g)
        if lf is not None:
            legal[name] = lf
    tr = None
    if trades is not None:
        tr = trades.sort_values([c for c in ("slot", "tx_idx", "pix", "ix") if c in trades]).reset_index(drop=True)
    return CoinData(mint=row["mint"], pool=row["pool"], g=g, m0=m0, row=MappingProxyType(row),
                    arr=MappingProxyType(arr), agent_nan=agent_nan, init_X=X0, init_y=y0,
                    legal=MappingProxyType(legal), split=row["split"], trades=tr)


def _check_split_env(split: str) -> None:
    """Env guard of a one-run split, enforced by the engine itself whatever Dataset is passed (val: shortlist)."""
    env = GUARD_ENV.get(split)
    if env is not None and split != "val" and os.environ.get(env) != "1":
        raise SplitLocked(f"split {split!r} is locked: needs env {env}=1 (only the judge sets it)")


def _check_sol_coverage(ds: "Dataset") -> None:
    sol = ds.coverage.get("sol_usd") or {}
    if sol.get("lookahead_coins"):
        raise DataNotReady(f"SOL/USD series starts {(sol.get('series_utc') or ['?'])[0]}: {sol['lookahead_coins']} "
                           f"coins of {ds.split!r} would use a later (future) SOL price; extend it (LAB2_SOL_USD)")
    if sol.get("constant_fallback") and ds.coverage.get("from_flow"):
        raise DataNotReady("no SOL/USD series loaded for real data: refusing a constant SOL price")


def _check_load_guard(split: str, internal: bool) -> None:
    env = GUARD_ENV.get(split)
    if env is None:
        return
    if split == "val" and internal:
        return   # backtest() enforces the shortlist rule for VAL
    if os.environ.get(env) != "1":
        hint = "VAL runs go through backtest() with a shortlist" if split == "val" else "only the judge sets it"
        raise SplitLocked(f"split {split!r} is locked: needs env {env}=1 ({hint})")


def load(split: str, *, flow: Path | None = None, census: Census | None = None, sol: SolUsd | None = None,
         _internal: bool = False) -> Dataset:
    """Load one split of the CryptoHouse tables with the tradeable-universe filters and a coverage report.

    ``split`` in confirm | train | val | test | final_train (debug only) | final_val | final_test | final.
    Guards: test/confirm/final* need their env flag; val is reachable only through :func:`backtest`
    (or env LAB2_ALLOW_VAL=1 for the judge)."""
    _check_load_guard(split, _internal)
    f = flow or flow_dir()
    for _ in range(3):
        stamp = [(f / n).stat().st_mtime_ns for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet")]
        g = _read_parquet(f / "graduates.parquet")
        c = _read_parquet(f / "b2_coins.parquet")
        b = _read_parquet(f / "b2_bars.parquet")
        tr = _read_parquet(f / "b1_trades.parquet") if (f / "b1_trades.parquet").exists() else None
        if tr is not None and (f / "wallet_dict.parquet").exists():
            wd = _read_parquet(f / "wallet_dict.parquet")
            pooled = set(POOLED_ACCOUNTS) | _pooled_from_file()
            ph = set(wd.loc[wd.iloc[:, 1].isin(pooled), wd.columns[0]])
            tr = tr.assign(pooled=tr["wallet_h"].isin(ph))     # exclude from wallet features (audit 3.6)
        comp = completeness_from_flow(f)
        if stamp ==[(f / n).stat().st_mtime_ns for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet")]:
            break
        warnings.warn("FLOW tables changed while loading (re-consolidation?): reloading")
    ds = Dataset.from_frames(split, g, c, b, census=census, sol=sol or load_sol_usd(), trades=tr, guard=False,
                             completeness=comp)
    ds.coverage["from_flow"] = True
    ds.coverage["data_files"] = {n: utc_str((f / n).stat().st_mtime) for n in
                                 ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet")}
    return ds


def load_sol_usd(lab: Path | None = None) -> SolUsd:
    """SOL/USD minute closes: LAB/sol_usd.json (10-07 08:57 -> 10-08 18:15 today) merged with the optional
    extension file ``LAB2_SOL_USD`` (default scratchpad/lab2_data/sol_usd_ext.json, same {"candles": [...]} format)
    that must cover the EXT splits before any EXT stage runs (see :func:`coverage_problems`)."""
    rows: dict[int, list] = {}
    for path in ((lab or lab_data_dir()) / "sol_usd.json",
                 Path(os.environ.get("LAB2_SOL_USD", str(_SCRATCH / "lab2_data" / "sol_usd_ext.json")))):
        try:
            for r in json.loads(Path(path).read_text())["candles"]:
                rows.setdefault(int(r[0]), r)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return SolUsd(list(rows.values())) if rows else SolUsd()


def coverage_summary(flow: Path | None = None, census: Census | None = None) -> dict[str, dict]:
    """Coverage reports (counts only: no prices, no returns) for every split, guarded ones included."""
    f = Path(flow or flow_dir())
    g, c, b = (_read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    census = census if census is not None else Census.load()
    comp, sol = completeness_from_flow(f), load_sol_usd()
    out = {}
    for s in ALL_SPLITS:
        cov = Dataset.from_frames(s, g, c, b, census=census, sol=sol, guard=False, completeness=comp).coverage
        out[s] = {k: v for k, v in cov.items()} | {"from_flow": True}
    return out


def coverage_report(split: str, g_all: pd.DataFrame, g_split: pd.DataFrame, usable: pd.DataFrame,
                    bars: pd.DataFrame, sol: SolUsd, comp: Completeness | None = None) -> dict:
    """Which days exist, which are partial or mid-run, SOL/USD coverage, and whether the split can reach the PLAN
    minimum samples. Counts only (no prices, no returns)."""
    comp = comp or Completeness.from_bars(bars)
    curve_hours = set(comp.curve_hours) if comp.curve_hours is not None else \
        set((g_all["g_ts"].to_numpy(np.int64) // 3600 * 3600).tolist())
    active = _active_pools(g_all)
    if split in SPLIT_BOUNDS:
        lo, hi = SPLIT_BOUNDS[split]
    else:
        sub = g_split["created_for_split"]
        lo = int(sub.min()) if len(sub) else FINAL_LO
        hi = int(sub.max()) + 1 if len(sub) else FINAL_LO
    hours = list(range(lo // 3600 * 3600, hi, 3600))
    # B2 hours: creation hours of the split plus every hour a tradeable coin of the split needs
    trad_split = g_split[g_split["tradeable"]] if "tradeable" in g_split else g_split
    need = set(hours)
    for gt in trad_split["g_ts"].to_numpy(float) if len(trad_split) else []:
        need.update(_hours_needed(gt))
    status = {h: comp.hour_status(h, active(h)) for h in sorted(need)}
    b2h = {h for h, v in status.items() if v == "done"}
    midrun = sorted(h for h, v in status.items() if v == "partial")
    days = []
    gs = g_split.assign(day=pd.to_datetime(g_split["created_for_split"], unit="s").dt.strftime("%Y-%m-%d"))
    us = set(usable["mint"])
    for d in sorted({utc_str(h)[:10] for h in hours}):
        dlo = utc_ts(d)
        dh = [h for h in range(dlo, dlo + 86400, 3600) if lo // 3600 * 3600 <= h < hi]
        sub = gs[gs["day"] == d]
        trad = sub[sub["tradeable"]] if "tradeable" in sub else sub
        n_use = int(sub["mint"].isin(us).sum())
        ch = sum(h in curve_hours for h in dh)
        bh = sum(h in b2h for h in dh)
        frac = n_use / len(trad) if len(trad) else 0.0
        days.append({"day": d, "hours_in_split": len(dh), "curve_hours": ch, "b2_hours": bh,
                     "b2_hours_midrun": sum(status.get(h) == "partial" for h in dh),
                     "coins_created": int(len(sub)), "tradeable": int(len(trad)), "usable": n_use,
                     "usable_frac": round(frac, 3),
                     "partial": bool(ch < len(dh) or bh < len(dh) or frac < 0.95 or len(sub) == 0)})
    n_use = int(len(usable))
    reasons = g_split["exclude_reason"].value_counts().to_dict() if "exclude_reason" in g_split else {}
    reasons.pop("", None)
    # SOL/USD: a price lookup before the series starts returns its FIRST price, i.e. a later (future) price
    sol_info: dict[str, Any] = {"series_utc": [utc_str(sol.ts[0]), utc_str(sol.ts[-1])] if sol.ts else None,
                                "constant_fallback": not sol.ts, "lookahead_coins": 0, "stale_coins": 0}
    in_sol = 0
    if n_use and sol.ts:
        gu = usable["g_ts"].to_numpy(float)
        sol_info["lookahead_coins"] = int((gu - 120 < sol.ts[0]).sum())
        sol_info["stale_coins"] = int((gu + B2_HORIZON_S > sol.ts[-1] + 60).sum())
        in_sol = n_use - int(((gu - 120 < sol.ts[0]) | (gu + B2_HORIZON_S > sol.ts[-1] + 60)).sum())
    power = {
        "entry_bar_coins": {"need": PLAN_MIN["entry_test_coins"], "have_usable_coins": n_use,
                            "ok": n_use >= PLAN_MIN["entry_test_coins"]},
        "x1_r0_trades_5_seeds": {"need": PLAN_MIN["x1_train_r0_trades"] if split == "train" else PLAN_MIN["x1_val_r0_trades"],
                                 "max_possible": 5 * n_use,
                                 "ok": 5 * n_use >= (PLAN_MIN["x1_train_r0_trades"] if split == "train" else PLAN_MIN["x1_val_r0_trades"])},
        "g1_flagged_coins_val": {"need": PLAN_MIN["g1_val_flagged_coins"], "max_possible": n_use,
                                 "ok": n_use >= PLAN_MIN["g1_val_flagged_coins"]},
    }
    hours_frac = sum(h in curve_hours for h in hours) / len(hours) if hours else 0.0
    notes = []
    if any(d["partial"] for d in days):
        notes.append("partial days present: results cover only the hours with data (see days[])")
    if hours_frac < 0.999:
        notes.append(f"only {hours_frac:.1%} of the split's chain hours have graduates scanned (backfill in progress?)")
    if midrun:
        notes.append(f"{len(midrun)} B2 hour(s) are mid-run (some pools consolidated, others not yet), first "
                     f"{utc_str(midrun[0])}: their coins are excluded")
    if sol_info["lookahead_coins"]:
        notes.append(f"SOL/USD series starts {sol_info['series_utc'][0]}: {sol_info['lookahead_coins']}/{n_use} coins "
                     "would get a LATER (future) SOL price for $20 sizing and the USD filters")
    elif n_use and in_sol < n_use:
        notes.append(f"SOL/USD series covers {in_sol}/{n_use} coins; {sol_info['stale_coins']} use its last (stale) "
                     "price after it ends (affects only $->SOL sizing and the alive filter's USD volume)")
    nc = int((~g_split["created_exact"]).sum()) if "created_exact" in g_split else 0
    return {
        "split": split, "bounds_utc": [utc_str(lo), utc_str(hi)], "debug_only": split in DEBUG_SPLITS,
        "graduates_in_split": int(len(g_split)), "tradeable": int(g_split["tradeable"].sum()) if "tradeable" in g_split else None,
        "usable": n_use, "excluded": {k: int(v) for k, v in reasons.items()},
        "created_inexact": nc, "has_create0": int(g_split["curve_partial"].sum()) if "curve_partial" in g_split else None,
        "chain_hours_scanned_frac": round(hours_frac, 4), "days": days,
        "days_expected": round((hi - lo) / 86400, 2), "days_full": sum(1 for d in days if not d["partial"]),
        "curve_span_utc": [utc_str(min(curve_hours)), utc_str(max(curve_hours) + 3600)] if curve_hours else None,
        "b2_span_utc": [utc_str(min(b2h)), utc_str(max(b2h) + 3600)] if b2h else None,
        "completeness_source": comp.source, "parquet_snapshot_utc": comp.snapshot_utc,
        "b2_hours_needed": len(need), "b2_hours_done": len(b2h), "b2_hours_midrun": [utc_str(h) for h in midrun],
        "sol_usd": sol_info,
        "power": power, "underpowered": n_use < PLAN_MIN["entry_test_coins"],
        "complete": bool(days) and not any(d["partial"] for d in days) and hours_frac >= 0.999 and not midrun,
        "notes": notes,
    }


def coverage_problems(cov: Mapping[str, Any], max_missing_frac: float = 0.05) -> list[str]:
    """Data-contract problems that make every non-debug stage refuse (shared by G1 / S1 / D1 / M1):

    * B2 hours mid-run (a time-split hour with one half consolidated, pools still to come);
    * coins missing B2 (no row, incomplete window, or a pool the backfill gave up on) > 5 % of tradeable;
    * SOL/USD: coins that would read a price from before the series starts (= a later price), or no series at all
      on real data (a constant)."""
    out = []
    mr = cov.get("b2_hours_midrun") or []
    if mr:
        out.append(f"{len(mr)} B2 hour(s) mid-run (first {mr[0]}): wait for the backfill to finish them")
    ex = cov.get("excluded") or {}
    miss = sum(int(ex.get(k, 0)) for k in ("b2_window_incomplete", "no_b2_row", "b2_pool_error"))
    trad = int(cov.get("tradeable") or 0)
    if trad and miss / trad > max_missing_frac:
        out.append(f"{miss}/{trad} tradeable coins lack a complete B2 window (incl. {int(ex.get('b2_pool_error', 0))} "
                   "pools the backfill gave up on: the most active coins, not a random loss)")
    sol = cov.get("sol_usd") or {}
    if sol.get("lookahead_coins"):
        out.append(f"SOL/USD series starts {(sol.get('series_utc') or ['?'])[0]}: {sol['lookahead_coins']} coins would "
                   "use a later SOL price (lookahead); extend the series (LAB2_SOL_USD) first")
    if sol.get("constant_fallback") and cov.get("from_flow"):
        out.append("no SOL/USD series loaded: every USD conversion would use a constant")
    return out


def _split_hours(split: str) -> tuple[int, int]:
    """Creation-time bounds of a split for the data gates (FINAL: the census day)."""
    if split in SPLIT_BOUNDS:
        return SPLIT_BOUNDS[split]
    cen = Census.load() if (lab_data_dir() / "census.json").exists() else Census.empty()
    hi = cen.created_max_ts + 1 if math.isfinite(cen.created_max_ts) else FINAL_LO + 86400
    return FINAL_LO, int(hi)


def _v_ok(rec: Mapping[str, Any], name: str) -> bool:
    v = rec.get(name)
    if not isinstance(v, Mapping):
        return False
    if name == "V2" and "transitions" in v:
        return v.get("chain_ok", 0) / max(v.get("transitions", 0), 1) >= 0.99
    if name == "V3" and "coin_windows" in v:
        return v.get("both", 0) / max(v.get("coin_windows", 0), 1) >= 0.95
    return v.get("pass") is True


def validation_gates(split: str, flow: Path | None = None) -> tuple[bool, list[str]]:
    """PLAN 8 stop rule 1 (data first) for ONE split: V1 labels, V2 reserve chain >= 99 %, V4 ordering on raw trades
    FROM THE SPLIT'S DATES, validated after the data they cover was fetched, plus V3 cross-source (only possible on
    the census-day launch sample).

    ``FLOW/validation.json`` holds the census-day run of ``research/flow/validate.py`` (no date ranges: it covers
    the census day only, validated at ``generated_utc`` or the file's mtime). Other dates need range records,
    in ``validation.json["ranges"]`` or ``FLOW/validation_ranges.json`` (a list), each
    ``{"lo_utc", "hi_utc", "validated_utc", "V1": {"pass"}, "V2": {"chain_ok", "transitions"}, "V4": {"pass"}}``.
    A range validated BEFORE the newest B2 chunk of an hour it covers was fetched is stale for that hour."""
    f = Path(flow or flow_dir())
    try:
        v = json.loads((f / "validation.json").read_text())
    except (OSError, ValueError):
        return False, ["FLOW/validation.json missing: run research/flow/validate.py first"]
    bad = [f"{k} failed" for k in ("V1", "V2", "V3", "V4") if not _v_ok(v, k)]
    ranges = list(v.get("ranges") or [])
    with contextlib.suppress(OSError, ValueError, TypeError):
        ranges += list(json.loads((f / "validation_ranges.json").read_text()))
    recs = []
    for r in ranges:
        try:
            recs.append((utc_ts(r["lo_utc"][:19]), utc_ts(r["hi_utc"][:19]), utc_ts(r["validated_utc"][:19]),
                         all(_v_ok(r, k) for k in ("V1", "V2", "V4"))))
        except (KeyError, TypeError, ValueError):
            bad.append(f"unreadable validation range {r!r:.80}")
    gen = v.get("generated_utc")
    v_ts = utc_ts(gen[:19]) if isinstance(gen, str) else (f / "validation.json").stat().st_mtime
    recs.append((FINAL_LO // 3600 * 3600, FINAL_LO + 86400 + 4 * 3600, v_ts,
                 all(_v_ok(v, k) for k in ("V1", "V2", "V4"))))         # the census-day record itself
    lo, hi = _split_hours(split)
    comp = completeness_from_flow(f, with_bar_hours=False) if (f / "raw" / "b2").exists() else None
    uncovered, stale = [], []
    for h in range(lo // 3600 * 3600, hi, 3600):
        ok_recs = [r for r in recs if r[3] and r[0] <= h and h + 3600 <= r[1]]
        if not ok_recs:
            uncovered.append(h)
            continue
        fetched = (comp.b2_fetched.get(h) if comp is not None else None) or 0.0
        if fetched and max(r[2] for r in ok_recs) < fetched:
            stale.append((h, fetched, max(r[2] for r in ok_recs)))
    if uncovered:
        bad.append(f"validation does not cover {len(uncovered)} chain hour(s) of split {split!r} (first "
                   f"{utc_str(uncovered[0])}): run V1/V2/V4 on raw trades from those dates")
    if stale:
        h, fe, va = stale[0]
        bad.append(f"validation of {len(stale)} hour(s) of split {split!r} predates their data (first {utc_str(h)}: "
                   f"validated {utc_str(va)}, B2 fetched {utc_str(fe)}): re-run it on the current data")
    return not bad, bad


def coverage_dataset(split: str, flow: Path | None = None, census: Census | None = None,
                     sol: SolUsd | None = None) -> "Dataset":
    """Counts-only view of one split of the real tables, with the raw-chunk completeness and SOL/USD series that
    :func:`load` uses (no guard: never hand it to a strategy on a guarded split)."""
    f = Path(flow or flow_dir())
    g, c, b = (_read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    ds = Dataset.from_frames(split, g, c, b, census=census if census is not None else Census.load(),
                             sol=sol or load_sol_usd(), guard=False, completeness=completeness_from_flow(f))
    ds.coverage["from_flow"] = True
    return ds


# =========================================================================== the as-of accessor


class Bars:
    """Completed minute bars of one coin at tau (read-only numpy views). Index 0 = graduation minute (partial).

    Dense: minutes without trades carry the last close (o = h = l = c) and have zero flow; ``traded`` marks
    minutes with >= 1 trade. ``X`` = pricing reserve (x + v), ``y`` = token reserve, both after the minute.
    ``agent_buy_sol`` is NaN before the AGENT is knowable."""

    __slots__ = ("_a", "_k", "_agent", "minute_ts")

    def __init__(self, cd: CoinData, k: int, agent_visible: bool) -> None:
        self._a, self._k = cd.arr, k
        self._agent = cd.arr["agent_buy_sol"][:k] if agent_visible else cd.agent_nan[:k]
        mt = cd.m0 + 60 * np.arange(k, dtype=np.int64)
        mt.setflags(write=False)
        self.minute_ts = mt

    def __len__(self) -> int:
        return self._k

    def __getattr__(self, name: str) -> np.ndarray:
        if name == "agent_buy_sol":
            return self._agent
        if name in BAR_ARRAYS:
            return self._a[name][: self._k]
        raise AttributeError(name)

    def as_frame(self) -> pd.DataFrame:
        d = {k: getattr(self, k) for k in BAR_ARRAYS}
        d["minute_ts"] = self.minute_ts
        return pd.DataFrame(d)


class AsOf:
    """Everything a strategy may know about one coin at decision time ``t`` (cutoff ``tau = t - 20 s``).

    ``snap[name]`` -> value (None = NULL) or raises ForbiddenFeature / NotYetKnown / KeyError.
    ``snap.features()`` -> dict of every field legal at tau. ``snap.bars`` -> completed minute bars.
    """

    __slots__ = ("_cd", "t", "tau", "g", "age_s", "mint", "k", "_sol")

    def __init__(self, cd: CoinData, t: float, sol: SolUsd | None = None) -> None:
        self._cd, self.t, self.tau = cd, float(t), float(t) - DECISION_LAG_S
        self.g, self.mint = cd.g, cd.mint
        self.age_s = self.t - cd.g
        self.k = int(min(max((self.tau - cd.m0) // 60, 0), N_BARS))
        self._sol = sol

    # ------------------------------------------------------------------ static fields
    def __getitem__(self, name: str) -> Any:
        if name == "agent_detected":
            return self.agent_detected
        if name in FORBIDDEN:
            raise ForbiddenFeature(f"{name!r} encodes the future or our data collection: never a feature")
        lf = self._cd.legal.get(name)
        if lf is None:
            if name in self._cd.row:
                raise ForbiddenFeature(f"{name!r} has no legality rule in common.py (fail closed); add one")
            raise KeyError(name)
        if self.tau < lf:
            raise NotYetKnown(f"{name!r} is knowable from {utc_str(lf)} (tau = {utc_str(self.tau)})")
        return self._cd.row[name]

    def get(self, name: str, default: Any = None) -> Any:
        """Like ``[]`` but returns ``default`` for NotYetKnown / missing columns. Forbidden still raises."""
        try:
            v = self[name]
        except NotYetKnown:
            return default
        except ForbiddenFeature:
            raise
        except KeyError:
            return default
        return v

    def legal_from(self, name: str) -> float | None:
        return self._cd.legal.get(name)

    def features(self) -> dict[str, Any]:
        out = {n: self._cd.row[n] for n, lf in self._cd.legal.items() if self.tau >= lf}
        out["agent_detected"] = self.agent_detected
        out["age_s"] = self.age_s
        return out

    @property
    def agent_detected(self) -> bool:
        """Causal: True once the AGENT's 4th buy is at or before tau."""
        ka = self._cd.row.get("agent_known_at")
        return bool(self._cd.row.get("agent_present")) and ka is not None and ka <= self.tau

    @property
    def agent_resolved(self) -> bool:
        """True when AGENT presence is decided (detected, or the 420 s window is over)."""
        return self.agent_detected or self.tau >= self.g + AGENT_WINDOW_S

    # ------------------------------------------------------------------ bars and bar-derived helpers
    @property
    def bars(self) -> Bars:
        return Bars(self._cd, self.k, self.agent_detected)

    @property
    def price(self) -> float:
        """Pool price (SOL per whole token) at the end of the last completed minute (initial pool price if none)."""
        return float(self._cd.arr["c"][self.k - 1]) if self.k > 0 else self._cd.init_X / self._cd.init_y

    @property
    def mcap_sol(self) -> float:
        return self.price * TOKEN_SUPPLY

    @property
    def sol_usd(self) -> float:
        """SOL/USD of the last minute that ended before tau."""
        return (self._sol or SolUsd()).at(self.tau - 60)

    @property
    def mcap_usd(self) -> float:
        return self.mcap_sol * self.sol_usd

    def _win(self, window_s: float) -> slice:
        # completed bars whose END lies in (tau - window, tau]: end_i = m0 + 60 (i + 1) > tau - window
        first = max(0, int(math.floor((self.tau - window_s - self._cd.m0) / 60.0)))
        return slice(min(first, self.k), self.k)

    def vol_sol(self, window_s: float) -> float:
        s = self._win(window_s)
        a = self._cd.arr
        return float(a["buy_sol"][s].sum() + a["sell_sol"][s].sum())

    def vol_usd(self, window_s: float) -> float:
        return self.vol_sol(window_s) * self.sol_usd

    def net_flow_sol(self, window_s: float) -> float:
        s = self._win(window_s)
        a = self._cd.arr
        return float(a["buy_sol"][s].sum() - a["sell_sol"][s].sum())

    def non_agent_buy_sol(self, window_s: float) -> float | None:
        """Buy SOL minus the AGENT's, or None while AGENT presence is undecided. NOT 'organic' (bots, wash,
        pooled accounts and MECH are still inside minute bars: wallet roles need B1 trades)."""
        if not self.agent_resolved:
            return None
        s = self._win(window_s)
        a = self._cd.arr
        ag = a["agent_buy_sol"][s].sum() if self.agent_detected else 0.0
        return float(a["buy_sol"][s].sum() - ag)

    def ret(self, window_s: float) -> float:
        """Price change over the last ``window_s`` seconds of completed bars (close / earlier close - 1)."""
        j = int(math.floor((self.tau - window_s - self._cd.m0) / 60.0)) - 1
        p0 = float(self._cd.arr["c"][j]) if j >= 0 else self._cd.init_X / self._cd.init_y
        return self.price / p0 - 1.0

    def max_high(self, window_s: float) -> float:
        s = self._win(window_s)
        h = self._cd.arr["h"][s]
        return float(h.max()) if len(h) else self.price

    def alive(self, vol_usd_15m: float = 1500.0, mcap_usd_min: float = 6000.0) -> bool:
        """PLAN / F3 'alive': USD volume over 15 min >= $1.5k and market cap >= $6k."""
        return self.vol_usd(900) >= vol_usd_15m and self.mcap_usd >= mcap_usd_min

    def top_buyers(self, window: str = "w120", exclude_agent: bool = True) -> tuple | None:
        """Top-10 buyers [(wallet, buy_sol, sell_sol)] of the early window, pooled accounts removed and the
        AGENT removed when ``exclude_agent`` (then legal only once AGENT presence is decided)."""
        lst = self[f"{window}_top10"]
        if lst is None:
            return None
        if exclude_agent:
            if not self.agent_resolved:
                raise NotYetKnown("AGENT presence is undecided at tau; cannot exclude it yet")
            aw = self._cd.row.get("agent_wallet") if self.agent_detected else None
            lst = tuple(w for w in lst if w[0] != aw)
        return lst

    def top_share(self, window: str = "w120", k: int = 5, exclude_agent: bool = True) -> float | None:
        """Top-k buyers' share of the window's buy SOL (G1 ``amm_top5_share_2m``), pooled accounts never counted
        as one buyer (their SOL stays in the denominator: it is real flow by many users), the AGENT removed from
        both sides when ``exclude_agent`` (only possible when it is in the stored top-10 list, as in
        research/flow/features.top_share). None when the window total is unknown or zero."""
        lst = self.top_buyers(window, exclude_agent=exclude_agent)
        total = self[f"{window}_buy_sol"]
        if lst is None or total is None:
            return None
        if exclude_agent and self.agent_detected:
            aw = self._cd.row.get("agent_wallet")
            raw = self[f"{window}_top10"] or ()
            total = total - sum(w[1] for w in raw if w[0] == aw)
        if total <= 0:
            return None
        return float(sum(sorted((w[1] for w in lst), reverse=True)[:k]) / total)

    # ------------------------------------------------------------------ B1 trades (when b1_trades.parquet exists)
    @property
    def trades(self) -> pd.DataFrame | None:
        """Raw non-dust trades with ts <= tau (B1, PLAN 6.5), or None when B1 is not loaded."""
        tr = self._cd.trades
        if tr is None:
            return None
        n = int(np.searchsorted(tr["ts"].to_numpy(), self.tau, side="right"))
        return tr.iloc[:n]


# =========================================================================== strategy API


@dataclass(frozen=True)
class ExitSpec:
    """Mechanical exits, relative to the ENTRY FILL PRICE (worst mode: the bar high-side) and landing time."""

    stop_pct: float | None = None
    take_profit_pct: float | None = None
    trail_pct: float | None = None
    max_hold_s: float | None = None
    exit_by_age_s: float | None = None    # time exit at coin age g + this (a registered deadline inside the data)


@dataclass(frozen=True)
class Enter:
    exits: ExitSpec = ExitSpec()
    tag: str = ""
    state: Mapping[str, Any] = field(default_factory=dict)   # handed back in PositionView.state (not to placebos)


@dataclass(frozen=True)
class Exit:
    reason: str = "signal"


class _Skip:
    def __repr__(self) -> str:
        return "SKIP"


SKIP = _Skip()   # return from strategy_fn to stop considering this coin (saves time)


@dataclass(frozen=True)
class PositionView:
    mint: str
    t_dec: float
    t_in: float
    entry_price: float
    tokens: float
    sol_in: float
    peak: float                 # max(entry price, highs of completed bars after the entry bar)
    bars_held: int
    unrealized: float           # last completed close / entry price - 1 (before exit costs)
    exits: ExitSpec
    state: Mapping[str, Any]
    is_placebo: bool


@dataclass(frozen=True)
class FillConfig:
    size_usd: float = 20.0
    latency_s: float = 30.0          # order lands at t + latency (PLAN L = 30 s polling; 5 s websocket)
    entry_fill: str = "worst"        # worst: max(open, high) of the landing bar | open
    exit_fill: str = "worst"         # worst: min(open, low) | open (stops at the level)
    cost: CostModel = field(default_factory=CostModel)
    rent_usd: float = 0.0            # PLAN 3.3 stress: +$0.22 per coin until C1 confirms the account is closed
    entry_bar_exits: bool = True     # check stop/trail against the ENTRY bar's low too (harness-compatible, harsh:
                                     # with the entry at the high this assumes high-then-low inside one minute)
    exit_delay_bars: int = 0         # 0: a stop/trail/TP triggered in bar j fills in bar j (harness);
                                     # 1: fills at the adverse side of bar j + 1 (30 s polling + 30 s landing)

    def stressed(self, factor: float = 1.5, rent_usd: float | None = None) -> "FillConfig":
        """Every cost component x ``factor`` (pool fee, Ultra, slippage haircut, network, impact)."""
        return dataclasses.replace(self, cost=self.cost.stressed(factor),
                                   rent_usd=self.rent_usd * factor if rent_usd is None else rent_usd)


StrategyFn = Callable[[AsOf, Mapping[str, Any], "PositionView | None"], Any]


# =========================================================================== engine


def _resolve_exits(ex: ExitSpec, price: float, t_land: float, g: float | None = None) -> dict:
    ts = [t for t in (t_land + ex.max_hold_s if ex.max_hold_s is not None else None,
                      g + ex.exit_by_age_s if ex.exit_by_age_s is not None and g is not None else None)
          if t is not None]
    return {"stop": price * (1 - ex.stop_pct) if ex.stop_pct is not None else None,
            "tp": price * (1 + ex.take_profit_pct) if ex.take_profit_pct is not None else None,
            "trail": ex.trail_pct, "tstop": min(ts) if ts else None}


def _simulate_coin(cd: CoinData, sol: SolUsd, cfg: FillConfig, strategy_fn: StrategyFn, params: Mapping,
                   forced: tuple[int, Enter] | None = None, forced_is_placebo: bool = True) -> dict | None:
    """Run one coin; at most one trade. ``forced`` = (decision index k, Enter) for placebo / control entries."""
    a = cd.arr
    o, h, l, c = a["o"], a["h"], a["l"], a["c"]
    worst_in, worst_out = cfg.entry_fill == "worst", cfg.exit_fill == "worst"
    is_placebo = forced is not None and forced_is_placebo
    pend_in = pend_out = None
    pos = None
    done = False
    for j in range(N_BARS):
        # ---- fills landing in bar j
        if pend_in is not None and pend_in[0] == j:
            _, order, t_dec = pend_in
            pend_in = None
            t_land = t_dec + cfg.latency_s
            p_in = max(o[j], h[j]) if worst_in else o[j]
            s_usd = sol.at(t_land - 60)
            sol_in = cfg.size_usd / s_usd
            tokens, br = simulate_buy(sol_in, p_in, cd.k_before(j), t_land, cfg.cost)
            pos = {"j_in": j, "t_dec": t_dec, "t_in": t_land, "p_in": p_in, "tokens": tokens, "sol_in": sol_in,
                   "sol_usd": s_usd, "fee_in": br["fee_bps"], "peak": p_in, "order": order,
                   "ex": _resolve_exits(order.exits, p_in, t_land, cd.g)}
        if pos is not None:
            closed = None
            if pend_out is not None and pend_out[0] == j:
                p = min(o[j], l[j]) if worst_out else o[j]
                closed = (p, pend_out[1], pend_out[2])
                pend_out = None
            elif pend_out is None and (cfg.entry_bar_exits or j > pos["j_in"]):
                closed = _mechanical(pos, j, cd, worst_out)
                if closed is not None and cfg.exit_delay_bars > 0 and j + cfg.exit_delay_bars < N_BARS:
                    jd = j + cfg.exit_delay_bars
                    pend_out = (jd, closed[1], float(cd.bar_start(jd) + 30))
                    closed = None
            if closed is None and j == N_BARS - 1:
                closed = (min(o[j], l[j]) if worst_out else c[j], "horizon", float(cd.bar_start(j) + 59))
            if closed is not None:
                closed = (closed[0], closed[1], max(closed[2], pos["t_in"]))
                return _close(pos, closed, j, cd, cfg, is_placebo)
            pos["peak"] = max(pos["peak"], h[j]) if j > pos["j_in"] else pos["peak"]
        if done:
            break
        # ---- decision at the end of bar j (tau = end of bar j)
        t = cd.bar_start(j + 1) + GRID_OFFSET_S
        if pos is None and pend_in is None:
            if forced is not None:
                if j + 1 == forced[0]:
                    order = forced[1]
                else:
                    continue
            else:
                order = strategy_fn(AsOf(cd, t, sol), params, None)
            if order is SKIP:
                break
            if isinstance(order, Enter):
                jf = cd.bar_of(t + cfg.latency_s)
                if jf >= N_BARS - 1:      # no room left to hold: never enter on the last bar
                    break
                pend_in = (jf, order, t)
            elif order is not None and not isinstance(order, Exit):
                raise TypeError(f"strategy returned {order!r}; expected Enter, SKIP or None when flat")
        elif pos is not None and pend_out is None:
            pv = PositionView(mint=cd.mint, t_dec=pos["t_dec"], t_in=pos["t_in"], entry_price=pos["p_in"],
                              tokens=pos["tokens"], sol_in=pos["sol_in"], peak=pos["peak"],
                              bars_held=j - pos["j_in"] + 1, unrealized=float(c[j]) / pos["p_in"] - 1.0,
                              exits=pos["order"].exits, state={} if is_placebo else dict(pos["order"].state),
                              is_placebo=is_placebo)
            act = strategy_fn(AsOf(cd, t, sol), params, pv)
            if isinstance(act, Exit):
                jf = cd.bar_of(t + cfg.latency_s)
                pend_out = (min(jf, N_BARS - 1), "signal:" + act.reason, t + cfg.latency_s)
    return None


def _mechanical(pos: dict, j: int, cd: CoinData, worst: bool) -> tuple[float, str, float] | None:
    a = cd.arr
    o, h, l, c = float(a["o"][j]), float(a["h"][j]), float(a["l"][j]), float(a["c"][j])
    ex = pos["ex"]
    first = j == pos["j_in"]
    t_bar = float(cd.bar_start(j))
    t_mid = t_bar + 30.0
    adverse = min(o, l)
    trail_lvl = pos["peak"] * (1 - ex["trail"]) if ex["trail"] is not None else None
    if not first:
        if ex["tstop"] is not None and t_bar >= ex["tstop"]:
            return (adverse if worst else o, "time", max(t_bar, ex["tstop"]))
        if ex["stop"] is not None and o <= ex["stop"]:
            return (adverse if worst else o, "stop", t_bar)
        if trail_lvl is not None and o <= trail_lvl:
            return (adverse if worst else o, "trail", t_bar)
    if ex["stop"] is not None and l <= ex["stop"]:
        return (adverse if worst else ex["stop"], "stop", t_mid)
    if ex["tp"] is not None and h >= ex["tp"]:
        if o >= ex["tp"] and not first:
            p = o
        elif c >= ex["tp"] or not worst:
            p = ex["tp"]
        else:
            p = max(o, c)
        return (p, "take_profit", t_mid)
    if trail_lvl is not None and l <= trail_lvl:
        return (adverse if worst else trail_lvl, "trail", t_mid)
    return None


def _close(pos: dict, closed: tuple[float, str, float], j: int, cd: CoinData, cfg: FillConfig,
           is_placebo: bool) -> dict:
    p_out, reason, t_out = closed
    sol_out, br = simulate_sell(pos["tokens"], p_out, cd.k_before(j), t_out, cfg.cost)
    net = 2 * network_sol(cfg.cost)
    rent = cfg.rent_usd / pos["sol_usd"]
    ret = (sol_out - pos["sol_in"] - net - rent) / pos["sol_in"]
    ex = pos["order"].exits
    return {"mint": cd.mint, "split": cd.split, "g_ts": cd.g, "t_dec": pos["t_dec"], "t_in": pos["t_in"],
            "t_out": t_out, "age_in_s": pos["t_in"] - cd.g, "age_dec_s": pos["t_dec"] - cd.g,
            "entry_price": pos["p_in"], "exit_price": p_out, "mcap_in_sol": pos["p_in"] * TOKEN_SUPPLY,
            "sol_in": pos["sol_in"], "sol_out": sol_out, "ret_net": ret, "ret_mid": p_out / pos["p_in"] - 1.0,
            "reason": reason, "tag": pos["order"].tag, "bars_held": j - pos["j_in"] + 1,
            "fee_bps_in": pos["fee_in"], "fee_bps_out": br["fee_bps"], "is_placebo": is_placebo,
            "stop_pct": ex.stop_pct, "take_profit_pct": ex.take_profit_pct, "trail_pct": ex.trail_pct,
            "max_hold_s": ex.max_hold_s, "exit_by_age_s": ex.exit_by_age_s}


TRADE_COLS = ("mint", "split", "g_ts", "t_dec", "t_in", "t_out", "age_in_s", "age_dec_s", "entry_price",
              "exit_price", "mcap_in_sol", "sol_in", "sol_out", "ret_net", "ret_mid", "reason", "tag",
              "bars_held", "fee_bps_in", "fee_bps_out", "is_placebo", "stop_pct", "take_profit_pct", "trail_pct",
              "max_hold_s", "exit_by_age_s")


def _spec_of(row: Any) -> ExitSpec:
    def f(v):
        return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)
    return ExitSpec(stop_pct=f(row.stop_pct), take_profit_pct=f(row.take_profit_pct), trail_pct=f(row.trail_pct),
                    max_hold_s=f(row.max_hold_s), exit_by_age_s=f(getattr(row, "exit_by_age_s", None)))


def _frame(rows: list[dict], extra: Sequence[str] = ()) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=list(TRADE_COLS) + list(extra))


def _engine_trades(ds: Dataset, strategy_fn: StrategyFn, params: Mapping, cfg: FillConfig,
                   mints: Iterable[str] | None = None) -> pd.DataFrame:
    rows = []
    for m in (mints if mints is not None else ds.mints):
        r = _simulate_coin(ds.coin(m), ds.sol, cfg, strategy_fn, params)
        if r is not None:
            rows.append(r)
    return _frame(rows)


def _guarded_look(ds: Dataset, hypothesis: str | None, params: Mapping, ledger_path: Path | None,
                  shortlist_path: Path | None, what: str) -> bool:
    """Guards for a low-level run on ``ds.split``; True when the look is logged (a hypothesis was named on a
    non-debug split). A guarded split REQUIRES the hypothesis: no unlogged look at VAL / TEST / CONFIRM / FINAL."""
    if ds.split not in GUARD_ENV:
        return bool(hypothesis) and ds.split not in DEBUG_SPLITS
    if not hypothesis:
        raise SplitLocked(f"{what} on guarded split {ds.split!r} needs hypothesis= (every look there is logged)")
    _check_split_env(ds.split)
    _check_run_allowed(hypothesis, params, ds.split, ledger_path, shortlist_path)
    _check_sol_coverage(ds)
    return True


def run_trades(ds: Dataset, strategy_fn: StrategyFn, params: Mapping, cfg: FillConfig,
               mints: Iterable[str] | None = None, *, hypothesis: str | None = None, ledger_path: Path | None = None,
               shortlist_path: Path | None = None) -> pd.DataFrame:
    """Per-trade records of ``strategy_fn`` on every usable coin of ``ds`` (no placebo).

    On a guarded split (val / test / confirm / final*) it is a logged look like :func:`backtest`: env flag,
    shortlist / one-run rules, and a ledger entry whose identity includes ``cfg`` and ``mints``."""
    mints = list(mints) if mints is not None else None
    log = _guarded_look(ds, hypothesis, params, ledger_path, shortlist_path, "run_trades")
    t = _engine_trades(ds, strategy_fn, params, cfg, mints)
    if log:
        r = t["ret_net"].to_numpy(float)
        record_run(hypothesis, params, ds.split, {"n": int(len(r)), "mean": float(r.mean()) if len(r) else None},
                   ledger_path, cfg=cfg, mints=mints, kind="run_trades")
    return t


def run_entries(ds: Dataset, strategy_fn: StrategyFn, params: Mapping, cfg: FillConfig,
                entries: Iterable[tuple[str, float, Enter]], *, hypothesis: str | None = None,
                ledger_path: Path | None = None, shortlist_path: Path | None = None) -> pd.DataFrame:
    """Trades entered at GIVEN (mint, decision time t on the grid, Enter) -- e.g. a control "the same coins at the
    same t" -- with the strategy's exit logic and the order's mechanical exits; several entries per coin allowed.
    Guarded and logged like :func:`run_trades` (one look)."""
    entries = list(entries)
    log = _guarded_look(ds, hypothesis, params, ledger_path, shortlist_path, "run_entries")
    rows = []
    for m, t, order in entries:
        cd = ds.coin(m)
        k = int(round((float(t) - GRID_OFFSET_S - cd.m0) / 60.0))
        if abs(cd.bar_start(k) + GRID_OFFSET_S - float(t)) > 1e-6:
            raise ValueError(f"{m}: entry time {t} is not on the decision grid (minute boundary + {GRID_OFFSET_S} s)")
        r = _simulate_coin(cd, ds.sol, cfg, strategy_fn, params, forced=(k, order), forced_is_placebo=False)
        if r is not None:
            rows.append(r)
    out = _frame(rows)
    if log:
        r = out["ret_net"].to_numpy(float)
        record_run(hypothesis, params, ds.split, {"n": int(len(r)), "mean": float(r.mean()) if len(r) else None},
                   ledger_path, cfg=cfg, kind="run_entries")
    return out


def run_placebo(ds: Dataset, strategy_fn: StrategyFn, params: Mapping, cfg: FillConfig, signals: pd.DataFrame,
                n_draws: int = 20, seed: int = 0, eligible: Callable[[AsOf], bool] | None = None,
                max_tries: int = 200, strata: Callable[[AsOf], Any] | None = None) -> pd.DataFrame:
    """Matched-timing random entries (PLAN 3.4): for each signal, ``n_draws`` entries in random eligible coins of
    the same split at a decision age within +-120 s of the signal's, with the same exits (the signal's mechanical
    ExitSpec + the strategy's exit logic, called with ``pos.is_placebo = True`` and an empty state).
    ``eligible(snap)`` optionally restricts placebo entries (e.g. alive coins only); ``strata(snap)`` matches them
    on a class: a draw counts only when its stratum equals the signal's (evaluated at the signal's decision)."""
    mints = ds.mints
    rows = []
    for si, sig in enumerate(signals.itertuples(index=False)):
        ex = _spec_of(sig)
        rng = np.random.default_rng([seed, si])
        a = float(sig.age_dec_s)
        want = strata(AsOf(ds.coin(sig.mint), float(sig.t_dec), ds.sol)) if strata is not None else None
        got = tries = 0
        while got < n_draws and tries < max_tries:
            tries += 1
            cd = ds.coin(mints[int(rng.integers(len(mints)))])
            ks = np.arange(1, N_BARS)
            ages = cd.m0 + 60 * ks + GRID_OFFSET_S - cd.g
            ok = np.abs(ages - a) <= PLACEBO_AGE_TOL_S
            ok &= ((60 * ks + GRID_OFFSET_S + cfg.latency_s) // 60) < N_BARS - 1
            cand = ks[ok]
            if not len(cand):
                continue
            k = int(cand[int(rng.integers(len(cand)))])
            t = cd.bar_start(k) + GRID_OFFSET_S
            snap = AsOf(cd, t, ds.sol)
            if eligible is not None and not eligible(snap):
                continue
            if strata is not None and strata(snap) != want:
                continue
            r = _simulate_coin(cd, ds.sol, cfg, strategy_fn, params, forced=(k, Enter(exits=ex, tag="placebo")))
            if r is None:
                continue
            r["signal"] = si
            r["signal_mint"] = sig.mint
            rows.append(r)
            got += 1
    return _frame(rows, extra=("signal", "signal_mint"))


# =========================================================================== trials ledger, shortlists, guards


def params_hash(params: Mapping | None) -> str:
    s = json.dumps(params or {}, sort_keys=True, default=repr, separators=(",", ":"))
    return hashlib.sha1(s.encode()).hexdigest()[:12]


def _empty_ledger() -> dict:
    return {"version": 1, "note": "every distinct (hypothesis, params) is one trial for the deflated Sharpe ratio",
            "baseline": dict(BASELINE_TRIALS), "configs": {}, "runs": [], "val_shortlists": {},
            "n_trials_total": sum(BASELINE_TRIALS.values())}


@contextlib.contextmanager
def _ledger(path: Path | None = None, write: bool = True):
    path = Path(path or trials_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    with open(lock, "a+") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            led = json.loads(path.read_text()) if path.exists() and path.stat().st_size else _empty_ledger()
            yield led
            if write:
                led["n_trials_total"] = sum(led["baseline"].values()) + len(led["configs"])
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(led, indent=1, default=str))
                os.replace(tmp, path)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def n_trials(path: Path | None = None) -> int:
    """Total trials so far: the lab's wave-1 configurations + every distinct wave-2 (hypothesis, params) look."""
    with _ledger(path, write=False) as led:
        return sum(led["baseline"].values()) + len(led["configs"])


def hypothesis_family(hypothesis: str) -> str:
    """'M1-twin', 'G1.dip', 'S1-control1' -> 'M1', 'G1', 'S1': the one-run rules count per family."""
    return re.split(r"[-.]", str(hypothesis), maxsplit=1)[0]


def split_group(split: str) -> str:
    """'final' consumes 'final_val' and 'final_test' (and vice versa): ONE look at the census holdout."""
    return "final" if split in ("final", "final_val", "final_test") else split


def _ledger_key(path: Path | None) -> str:
    return str(Path(path or trials_path()).resolve())


_SESSIONS: dict[tuple[str, str, str], str] = {}     # (family, split group, ledger) -> open one-shot session id


def _check_canonical_ledger(split: str, ledger_path: Path | None) -> None:
    if (split in ONE_RUN_SPLITS or split == "val") and ledger_path is not None \
            and _ledger_key(ledger_path) != _ledger_key(None):
        raise SplitLocked(f"{split!r} looks are logged in the canonical ledger {trials_path()} (env LAB2_TRIALS), "
                          f"not {ledger_path}")


def _family_looks(led: Mapping, family: str, group: str) -> list[str]:
    out = [f"session {x.get('session')} ({x.get('opened_utc')})" for x in led.get("one_shot_sessions", [])
           if x.get("family") == family and x.get("split_group") == group]
    out += [f"run {r.get('hypothesis')} on {r.get('split')} ({r.get('utc')})" for r in led.get("runs", [])
            if not r.get("debug") and hypothesis_family(r.get("hypothesis", "")) == family
            and split_group(r.get("split", "")) == group]
    return out


@contextlib.contextmanager
def one_shot_session(hypothesis: str, split: str, ledger_path: Path | None = None, note: str = ""):
    """The ONE look of a hypothesis family at a one-run split (TEST / CONFIRM / FINAL). Inside the session the family
    may run several logged configs (candidate, twin, controls, sensitivity); before or after it, none. Refused when
    the family already had a session or any run on that split group."""
    if split not in ONE_RUN_SPLITS:
        raise ValueError(f"{split!r} is not a one-run split")
    _check_split_env(split)
    _check_canonical_ledger(split, ledger_path)
    fam, grp = hypothesis_family(hypothesis), split_group(split)
    key = (fam, grp, _ledger_key(ledger_path))
    if key in _SESSIONS:
        raise SplitLocked(f"a {fam} session on {grp} is already open")
    sid = hashlib.sha1(f"{fam}|{grp}|{time.time()}|{os.getpid()}".encode()).hexdigest()[:12]
    with _ledger(ledger_path) as led:
        prior = _family_looks(led, fam, grp)
        if prior:
            raise SplitLocked(f"{fam} already had its one {grp} look: {prior[0]}")
        led.setdefault("one_shot_sessions", []).append({"family": fam, "split_group": grp, "split": split,
                                                        "session": sid, "opened_utc": utc_str(time.time()),
                                                        "note": note})
    _SESSIONS[key] = sid
    try:
        yield sid
    finally:
        _SESSIONS.pop(key, None)
        with _ledger(ledger_path) as led:
            for x in led.get("one_shot_sessions", []):
                if x.get("session") == sid:
                    x["closed_utc"] = utc_str(time.time())


def _cfg_dict(cfg: "FillConfig") -> dict:
    d = dataclasses.asdict(cfg)
    return json.loads(json.dumps(d, default=repr))


def _look_id(cfg: "FillConfig | None", mints: Sequence[str] | None) -> str:
    """'' for the default fills on every coin (ids stay as before); else the cfg / mints hashes, so the same params
    under other fills or on a hand-picked subset are distinct trials."""
    parts = []
    if cfg is not None and _cfg_dict(cfg) != _cfg_dict(FillConfig()):
        parts.append("cfg:" + params_hash(_cfg_dict(cfg)))
    if mints is not None:
        parts.append("mints:" + hashlib.sha1(",".join(sorted(map(str, mints))).encode()).hexdigest()[:12])
    return ("|" + "|".join(parts)) if parts else ""


def record_run(hypothesis: str, params: Mapping | None, split: str, summary: Mapping | None = None,
               path: Path | None = None, debug: bool = False, cfg: "FillConfig | None" = None,
               mints: Sequence[str] | None = None, kind: str = "backtest") -> dict:
    """Log one run. A new (hypothesis, params, fills, coin subset) is a new trial (debug runs never are). Debug runs
    store no mean: they ran on the census TRAIN third, which is FINAL data."""
    cid = f"{hypothesis}|{params_hash(params)}{_look_id(cfg, mints)}"
    fam = hypothesis_family(hypothesis)
    with _ledger(path) as led:
        new = False
        if not debug:
            if cid not in led["configs"]:
                new = True
                led["configs"][cid] = {"hypothesis": hypothesis, "params": json.loads(json.dumps(params or {}, default=repr)),
                                       "first_seen_utc": utc_str(time.time()), "splits": {}}
                if cfg is not None and _look_id(cfg, None):
                    led["configs"][cid]["cfg"] = _cfg_dict(cfg)
                if mints is not None:
                    led["configs"][cid]["n_mints"] = len(mints)
            sp = led["configs"][cid]["splits"]
            sp[split] = sp.get(split, 0) + 1
            if split == "val":
                vl = led.setdefault("val_looks", {})
                vl[fam] = vl.get(fam, 0) + 1
        n_h = sum(1 for v in led["configs"].values() if v["hypothesis"] == hypothesis)
        lim = VARIANT_LIMITS.get(hypothesis)
        over = lim is not None and n_h > lim
        led["runs"].append({"utc": utc_str(time.time()), "hypothesis": hypothesis, "config": cid, "split": split,
                            "debug": debug, "n": (summary or {}).get("n"),
                            "mean": None if debug else (summary or {}).get("mean"), "over_variant_limit": over,
                            "kind": kind, "session": _SESSIONS.get((fam, split_group(split), _ledger_key(path)))})
        total = sum(led["baseline"].values()) + len(led["configs"])
        val_looks = (led.get("val_looks") or {}).get(fam, 0)
    if over:
        warnings.warn(f"{hypothesis}: {n_h} distinct configs > PLAN 3.4 limit {lim} (flagged in the ledger)")
    return {"config": cid, "new_trial": new, "n_trials_total": total, "hypothesis_configs": n_h,
            "over_variant_limit": over, "family_val_looks": val_looks}


def write_shortlist(hypothesis: str, configs: Sequence[Mapping], path: Path | None = None,
                    ledger_path: Path | None = None, note: str = "") -> Path:
    """Write the VAL shortlist (<= 2 configs) BEFORE the first VAL run of ``hypothesis``; frozen afterwards."""
    if not 1 <= len(configs) <= 2:
        raise ValueError("a VAL shortlist holds 1 or 2 configs (PLAN 3.1)")
    with _ledger(ledger_path, write=False) as led:
        if any(r["hypothesis"] == hypothesis and r["split"] == "val" for r in led["runs"]):
            raise SplitLocked(f"{hypothesis} already ran on VAL: its shortlist is frozen")
    d = Path(path or shortlist_dir())
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{hypothesis}.json"
    p.write_text(json.dumps({"hypothesis": hypothesis, "written_utc": utc_str(time.time()), "note": note,
                             "configs": [json.loads(json.dumps(c, default=repr)) for c in configs],
                             "hashes": [params_hash(c) for c in configs]}, indent=1, sort_keys=True))
    return p


def _check_run_allowed(hypothesis: str, params: Mapping | None, split: str, ledger_path: Path | None,
                       shortlist_path: Path | None) -> None:
    _check_canonical_ledger(split, ledger_path)
    if split == "val":
        p = Path(shortlist_path or shortlist_dir()) / f"{hypothesis}.json"
        if not p.exists():
            raise SplitLocked(f"no VAL shortlist for {hypothesis}: call write_shortlist() first")
        raw = p.read_bytes()
        sl = json.loads(raw)
        sha = hashlib.sha1(raw).hexdigest()
        if params_hash(params) not in sl["hashes"]:
            raise SplitLocked(f"params {params_hash(params)} not in the {hypothesis} VAL shortlist {sl['hashes']}")
        with _ledger(ledger_path) as led:
            seen = led["val_shortlists"].get(hypothesis)
            if seen is None:
                led["val_shortlists"][hypothesis] = {"sha": sha, "first_val_run_utc": utc_str(time.time())}
            elif seen["sha"] != sha:
                raise SplitLocked(f"the {hypothesis} shortlist changed after its first VAL run")
    if split in ONE_RUN_SPLITS:
        fam, grp = hypothesis_family(hypothesis), split_group(split)
        if (fam, grp, _ledger_key(ledger_path)) in _SESSIONS:
            return                      # inside the family's one-shot session: every look is logged with it
        with _ledger(ledger_path, write=False) as led:
            prior = _family_looks(led, fam, grp)
        if prior:
            raise SplitLocked(f"{hypothesis} (family {fam}) already had its one {grp} look: {prior[0]}")


# =========================================================================== backtest


@dataclass
class Result:
    trades: pd.DataFrame
    placebo: pd.DataFrame
    stress: dict[str, pd.DataFrame]
    meta: dict
    controls: dict[str, pd.DataFrame] = field(default_factory=dict)   # extra placebo controls (diagnostics)

    def summary(self, B: int = 10_000, reveal: bool = False) -> dict:
        """Stats of the run. On a debug split returns only counts unless ``reveal`` (debugging code, not params):
        no exit-reason counts either (stops vs take-profits reveal the outcome direction)."""
        if self.meta.get("debug_only") and not reveal:
            t = self.trades
            return {"split": self.meta["split"], "debug_only": True, "n": int(len(t)),
                    "n_coins": int(t["mint"].nunique()) if len(t) else 0, "n_placebo": int(len(self.placebo)),
                    "horizon_exits": int((t["reason"] == "horizon").sum()) if len(t) else 0,
                    "returns": "hidden on the debug split (never choose parameters on FINAL data)"}
        out = describe(self.trades, B=B, n_trials_total=self.meta.get("n_trials_total"))
        out["split"], out["hypothesis"], out["params"] = self.meta["split"], self.meta["hypothesis"], self.meta["params"]
        out["placebo"] = placebo_compare(self.trades, self.placebo, B=B) if len(self.placebo) else None
        out["controls"] = {k: placebo_compare(self.trades, v, B=B) for k, v in self.controls.items() if len(v)}
        out["stress"] = {k: describe(v, B=B) for k, v in self.stress.items()}
        out["portfolio"] = portfolio_sim(self.trades)
        out["n_eligible_coins"] = self.meta.get("n_coins")
        return out

    def verdict(self, val: "Result | None" = None, final: "Result | None" = None, **kw) -> dict:
        return verdict_entry(self, val=val, final=final, **kw)


def backtest(strategy_fn: StrategyFn, split: str, params: Mapping | None = None, *, hypothesis: str,
             ds: Dataset | None = None, cfg: FillConfig | None = None, placebo: bool = True, n_placebo: int = 20,
             placebo_eligible: Callable[[AsOf], bool] | None = None, stress: Mapping[str, FillConfig] | None = None,
             seed: int = 0, declarations: Mapping[str, Any] | None = None, ledger_path: Path | None = None,
             shortlist_path: Path | None = None, mints: Iterable[str] | None = None,
             placebo_strata: Callable[[AsOf], Any] | None = None,
             placebo_controls: Mapping[str, Mapping[str, Any]] | None = None) -> Result:
    """Run ``strategy_fn(snap, params, pos)`` on every usable coin of ``split``.

    * one entry per coin; decisions on the minute grid (boundary + 20 s); fills per ``cfg`` (default worst);
    * placebo (matched timing, ``n_placebo`` per signal) and stress runs (default on guarded splits:
      costs x1.5) come from the SAME call, so a one-shot TEST run carries everything the verdict needs;
    * VAL needs the params in the hypothesis's shortlist; TEST / CONFIRM / FINAL run once per hypothesis;
    * every non-debug run is logged in the trials ledger (identity: hypothesis, params, fills, coin subset);
      ``declarations`` feed :func:`auto_rejections` (e.g. {"uses_wallet_reputation": True,
      "reputation_excludes_traded_coin": True, "organic_excludes": ["AGENT", "BOT", "WASH", "DUST", "MECH"]});
    * ``placebo_strata(snap)`` matches the placebo on a class (each draw has the signal's stratum);
      ``placebo_controls`` = {name: {"eligible": fn | None, "strata": fn | None}} adds diagnostic controls
      (``Result.controls``), e.g. the unmatched control next to a class-matched one.
    """
    params = dict(params or {})
    mints = list(mints) if mints is not None else None
    cfg = cfg or FillConfig()
    debug = split in DEBUG_SPLITS
    if not debug:
        _check_split_env(split)
        _check_run_allowed(hypothesis, params, split, ledger_path, shortlist_path)
    if ds is None:
        ds = load(split, _internal=True)
    elif ds.split != split:
        raise ValueError(f"dataset is {ds.split!r}, backtest asked for {split!r}")
    if not debug:
        _check_sol_coverage(ds)
    trades = _engine_trades(ds, strategy_fn, params, cfg, mints)
    pl = _frame([], extra=("signal", "signal_mint"))
    controls: dict[str, pd.DataFrame] = {}
    if placebo and len(trades):
        pl = run_placebo(ds, strategy_fn, params, cfg, trades, n_placebo, seed, placebo_eligible,
                         strata=placebo_strata)
        for name, spec in (placebo_controls or {}).items():
            controls[name] = run_placebo(ds, strategy_fn, params, cfg, trades, n_placebo, seed,
                                         spec.get("eligible"), strata=spec.get("strata"))
    if stress is None:
        stress = {"costs_x1.5": cfg.stressed(1.5)} if (split in ONE_RUN_SPLITS or split == "val") else {}
    st = {k: _engine_trades(ds, strategy_fn, params, c, mints) for k, c in stress.items()}
    meta = {"hypothesis": hypothesis, "params": params, "split": split, "debug_only": debug,
            "cfg": {"size_usd": cfg.size_usd, "latency_s": cfg.latency_s, "entry_fill": cfg.entry_fill,
                    "exit_fill": cfg.exit_fill, "rent_usd": cfg.rent_usd, "entry_bar_exits": cfg.entry_bar_exits,
                    "exit_delay_bars": cfg.exit_delay_bars, "cost": dataclasses.asdict(cfg.cost)},
            "n_coins": len(ds), "coverage_underpowered": ds.coverage.get("underpowered"),
            "declarations": dict(declarations or {}), "seed": seed, "utc": utc_str(time.time())}
    rets = trades["ret_net"].to_numpy(float)
    info = record_run(hypothesis, params, split, {"n": int(len(rets)), "mean": float(rets.mean()) if len(rets) else None},
                      ledger_path, debug=debug, cfg=cfg, mints=mints)
    meta.update(info)
    meta["placebo_strata"] = getattr(placebo_strata, "__name__", None) if placebo_strata is not None else None
    return Result(trades=trades, placebo=pl, stress=st, meta=meta, controls=controls)


# =========================================================================== statistics


def coin_bootstrap_means(values: np.ndarray, groups: Sequence[Any], B: int = 10_000, seed: int = 0) -> np.ndarray:
    """B bootstrap means of per-trade ``values``, resampling COINS (groups) with replacement."""
    values = np.asarray(values, float)
    codes, _ = pd.factorize(pd.Series(list(groups)))
    sums = np.bincount(codes, weights=values)
    cnts = np.bincount(codes).astype(float)
    n = len(sums)
    rng = np.random.default_rng(seed)
    out = np.empty(B)
    step = max(1, int(4_000_000 // max(n, 1)))
    for s in range(0, B, step):
        e = min(B, s + step)
        idx = rng.integers(0, n, size=(e - s, n))
        out[s:e] = sums[idx].sum(1) / cnts[idx].sum(1)
    return out


def coin_bootstrap_ci(values: np.ndarray, groups: Sequence[Any], level: float = 0.95, B: int = 10_000,
                      seed: int = 0) -> tuple[float, float] | None:
    if len(set(groups)) < 2:
        return None
    m = coin_bootstrap_means(values, groups, B, seed)
    a = (1 - level) / 2
    return float(np.quantile(m, a)), float(np.quantile(m, 1 - a))


def block_bootstrap_means(values: np.ndarray, groups: Sequence[Any], blocks: Sequence[Any], B: int = 5_000,
                          seed: int = 0) -> np.ndarray | None:
    """PLAN 3.4 day-block bootstrap, two levels: resample time BLOCKS with replacement, then the coins inside each
    drawn block with replacement (coins of the same hours share SOL moves and the pump.fun regime, so a coin-only
    bootstrap treats correlated coins as independent). None with fewer than 2 blocks."""
    v = np.asarray(values, float)
    df = pd.DataFrame({"v": v, "c": list(groups), "b": list(blocks)})
    if df["b"].nunique() < 2:
        return None
    unit = df.groupby(["b", "c"], sort=True)["v"].agg(["sum", "size"]).reset_index()
    per = [(g["sum"].to_numpy(float), g["size"].to_numpy(float)) for _, g in unit.groupby("b", sort=True)]
    nb = len(per)
    rng = np.random.default_rng(seed)
    out = np.empty(B)
    for i in range(B):
        S = N = 0.0
        for bi in rng.integers(0, nb, nb):
            su, n = per[bi]
            idx = rng.integers(0, len(su), len(su))
            S += su[idx].sum()
            N += n[idx].sum()
        out[i] = S / N
    return out


def block_bootstrap_ci(values: np.ndarray, groups: Sequence[Any], blocks: Sequence[Any], level: float = 0.90,
                       B: int = 5_000, seed: int = 0) -> tuple[float, float] | None:
    m = block_bootstrap_means(values, groups, blocks, B, seed)
    if m is None:
        return None
    a = (1 - level) / 2
    return float(np.quantile(m, a)), float(np.quantile(m, 1 - a))


def trade_blocks(trades: pd.DataFrame) -> np.ndarray:
    """6-hour block of each trade's ENTRY time (BLOCK_S): trades held in the same hours share the market."""
    return (trades["t_in"].to_numpy(float) // BLOCK_S).astype(np.int64)


def censored_share(trades: pd.DataFrame) -> float | None:
    """Share of trades closed by the DATA horizon (g + 179 min) instead of their own rule: their outcome after
    that point is unknown, so a rule with many of them is not the rule that was simulated."""
    if not len(trades):
        return None
    return float((trades["reason"] == "horizon").mean())


def deflated_sharpe(rets: np.ndarray, n_trials_total: int, sr_var_trials: float | None = None) -> dict:
    """Deflated Sharpe ratio (Bailey & Lopez de Prado 2014) of per-trade returns.

    SR0 = sqrt(V) * ((1 - g) * Z^-1(1 - 1/N) + g * Z^-1(1 - 1/(N e))), with V the variance of SR across trials
    (default: the null estimator variance 1/(T - 1)); DSR = Z((SR - SR0) sqrt(T - 1) / sqrt(1 - s SR + (k - 1)/4 SR^2))."""
    r = np.asarray(rets, float)
    T = len(r)
    if T < 3 or r.std(ddof=1) == 0:
        return {"sr": None, "sr0": None, "dsr": None, "n_trials": int(n_trials_total), "T": T}
    sd = r.std(ddof=1)
    sr = r.mean() / sd
    z = (r - r.mean()) / r.std(ddof=0)
    skew, kurt = float((z ** 3).mean()), float((z ** 4).mean())
    N = max(int(n_trials_total), 2)
    V = sr_var_trials if sr_var_trials is not None else 1.0 / (T - 1)
    nd, gam = NormalDist(), 0.5772156649
    sr0 = math.sqrt(V) * ((1 - gam) * nd.inv_cdf(1 - 1 / N) + gam * nd.inv_cdf(1 - 1 / (N * math.e)))
    den = 1 - skew * sr + (kurt - 1) / 4 * sr ** 2
    dsr = nd.cdf((sr - sr0) * math.sqrt(T - 1) / math.sqrt(max(den, 1e-12)))
    return {"sr": float(sr), "sr0": float(sr0), "dsr": float(dsr), "n_trials": N, "T": T,
            "skew": skew, "kurtosis": kurt}


def describe(trades: pd.DataFrame, B: int = 10_000, seed: int = 0, n_trials_total: int | None = None) -> dict:
    """Per-trade stats: n, coins, mean, median, win rate, sd, coin-bootstrap 90/95 % CIs, top-coin share of net
    profit, mean without the top 2 trades, chronological halves, exit reasons, deflated Sharpe."""
    n = int(len(trades))
    if n == 0:
        return {"n": 0, "n_coins": 0, "mean": None}
    r = trades["ret_net"].to_numpy(float)
    coins = trades["mint"].to_numpy(object)
    by_coin = trades.groupby("mint")["ret_net"].sum().sort_values(ascending=False)
    total = float(r.sum())
    top2 = np.sort(r)[:-2] if n > 2 else np.array([])
    order = np.argsort(trades["t_in"].to_numpy(float), kind="stable")
    h1, h2 = r[order[: n // 2]], r[order[n // 2:]]
    ci90 = coin_bootstrap_ci(r, coins, 0.90, B, seed)
    ci95 = coin_bootstrap_ci(r, coins, 0.95, B, seed)
    blocks = trade_blocks(trades)
    bm = block_bootstrap_means(r, coins, blocks, min(B, 5_000), seed)
    ci90_b = None if bm is None else (float(np.quantile(bm, 0.05)), float(np.quantile(bm, 0.95)))
    ci95_b = None if bm is None else (float(np.quantile(bm, 0.025)), float(np.quantile(bm, 0.975)))
    out = {
        "n": n, "n_coins": int(len(by_coin)), "mean": float(r.mean()), "median": float(np.median(r)),
        "win_rate": float((r > 0).mean()), "sd": float(r.std(ddof=1)) if n > 1 else None,
        "ci90": ci90, "ci95": ci95, "ci90_block": ci90_b, "ci95_block": ci95_b,
        "n_blocks": int(len(set(blocks.tolist()))), "censored_share": censored_share(trades),
        "top_coin_share": float(by_coin.iloc[0] / total) if total > 0 else None,
        "top3_coin_share": float(by_coin.iloc[:3].sum() / total) if total > 0 else None,
        "mean_without_top2": float(top2.mean()) if len(top2) else None,
        "halves": {"first": float(h1.mean()) if len(h1) else None, "second": float(h2.mean()) if len(h2) else None,
                   "consistent": bool(len(h1) and len(h2) and h1.mean() > 0 and h2.mean() > 0)},
        "reasons": trades["reason"].value_counts().to_dict(),
        "mean_hold_min": float(((trades["t_out"] - trades["t_in"]) / 60).mean()),
    }
    if n_trials_total:
        out["deflated_sharpe"] = deflated_sharpe(r, n_trials_total)
    return out


def placebo_compare(trades: pd.DataFrame, placebo: pd.DataFrame, B: int = 10_000, seed: int = 0) -> dict:
    """Signal minus its matched-placebo mean, per signal, with a coin-bootstrap CI (paired by signal)."""
    pm = placebo.groupby("signal")["ret_net"].mean()
    t = trades.reset_index(drop=True)
    have = t.index.isin(pm.index)
    d = t.loc[have, "ret_net"].to_numpy(float) - pm.reindex(t.index[have]).to_numpy(float)
    return {"placebo_mean": float(placebo["ret_net"].mean()), "n_placebo": int(len(placebo)),
            "n_signals_matched": int(have.sum()), "mean_diff": float(d.mean()) if len(d) else None,
            "diff_ci95": coin_bootstrap_ci(d, t.loc[have, "mint"].to_numpy(object), 0.95, B, seed) if len(d) else None}


def portfolio_sim(trades: pd.DataFrame, start_usd: float = 100.0, max_open: int = 5, size_usd: float = 20.0) -> dict:
    """PLAN 3.4: $100, at most 5 open positions, fixed $20 tickets, every skipped signal logged.
    Positions are carried at cost until they close (realized equity)."""
    import heapq

    if not len(trades):
        return {"final_equity": start_usd, "max_dd_pct": 0.0, "taken": 0, "skipped": 0, "skipped_mints": []}
    t = trades.sort_values(["t_in", "mint"])
    cash, open_, eq, skipped = start_usd, [], [start_usd], []
    for r in t.itertuples(index=False):
        while open_ and open_[0][0] <= r.t_in:
            _, _, back = heapq.heappop(open_)
            cash += back
            eq.append(cash + size_usd * len(open_))
        if len(open_) >= max_open or cash < size_usd:
            skipped.append(r.mint)
            continue
        cash -= size_usd
        heapq.heappush(open_, (float(r.t_out), len(eq) + len(skipped) + len(open_), size_usd * (1 + float(r.ret_net))))
    while open_:
        _, _, back = heapq.heappop(open_)
        cash += back
        eq.append(cash + size_usd * len(open_))
    peak, dd = -math.inf, 0.0
    for v in eq:
        peak = max(peak, v)
        dd = max(dd, (peak - v) / peak * 100 if peak > 0 else 0.0)
    return {"final_equity": float(cash), "max_dd_pct": float(dd), "taken": int(len(t) - len(skipped)),
            "skipped": int(len(skipped)), "skipped_mints": skipped[:50]}


# =========================================================================== verdicts (PLAN 3.5, 3.6)


def auto_rejections(res: Result) -> list[str]:
    """PLAN 3.6 automatic rejections that the data can check, plus declared ones."""
    t, d = res.trades, res.meta.get("declarations") or {}
    out = []
    if len(t) > 2:
        r = np.sort(t["ret_net"].to_numpy(float))
        if r.mean() > 0 and r[:-2].mean() <= 0:
            out.append("disappears when the top 2 trades are removed")
    if len(t) and (t["t_in"] < t["g_ts"]).any():
        out.append("entries during the curve phase on a graduates-only set")
    if d.get("uses_wallet_reputation") and not d.get("reputation_excludes_traded_coin"):
        out.append("scores wallets with their trades in the coin being traded (declared)")
    if d.get("uses_organic_flow"):
        need = {"AGENT", "BOT", "WASH", "DUST", "MECH"}
        missing = need - set(d.get("organic_excludes") or [])
        if missing:
            out.append(f"counts {sorted(missing)} as organic (declared)")
    if d.get("uses_truncated_windows"):
        out.append("uses windows that hit a page or byte cap")
    if d.get("uses_current_state_fields"):
        out.append("uses current-state fields on historical coins")
    if res.meta.get("over_variant_limit"):
        out.append("more variants than the PLAN 3.4 limit for this hypothesis")
    return out


def verdict_entry(test: Result, *, val: Result | None = None, final: Result | None = None, min_mean: float = 0.03,
                  control_margin: float = 0.06, B: int = 10_000) -> dict:
    """PLAN 3.5 entry-rule bar on a TEST result. UNDERPOWERED when < 60 trades or < 40 coins (never PASS/FAIL);
    INCOMPLETE when an input is missing (VAL sign, placebo, stress); REJECTED on any 3.6 auto-rejection."""
    t = test.trades
    s = describe(t, B=B)
    crit = []

    def add(cid, name, ok, value, need):
        crit.append({"id": cid, "name": name, "pass": None if ok is None else bool(ok), "value": value, "need": need})

    n, nc = s["n"], s["n_coins"]
    add(1, "sample", n >= PLAN_MIN["entry_test_trades"] and nc >= PLAN_MIN["entry_test_coins"],
        {"trades": n, "coins": nc}, ">= 60 trades from >= 40 coins")
    add(2, "mean net", None if s["mean"] is None else s["mean"] >= min_mean, s["mean"], f">= {min_mean:+.3f}")
    c3 = None if not s.get("ci90") or not s.get("ci90_block") else (s["ci90"][0] > 0 and s["ci90_block"][0] > 0)
    add(3, "90% CI lower bound (coin AND 6-h block bootstrap)", c3, {"coin": s.get("ci90"), "block": s.get("ci90_block")},
        "> 0 under both")
    add(4, "mean without top 2 trades", None if s.get("mean_without_top2") is None else s["mean_without_top2"] > 0,
        s.get("mean_without_top2"), "> 0")
    pc = placebo_compare(t, test.placebo, B=B) if len(test.placebo) else None
    add(5, "beats matched random control", None if not pc or pc["mean_diff"] is None else pc["mean_diff"] >= control_margin,
        pc and pc["mean_diff"], f">= {control_margin:+.3f}")
    vm = describe(val.trades, B=200)["mean"] if val is not None and len(val.trades) else None
    add(6, "VAL and TEST same sign", None if vm is None or s["mean"] is None else (vm > 0) == (s["mean"] > 0),
        {"val": vm, "test": s["mean"]}, "same sign")
    sm = None
    if test.stress:
        k = next((k for k in test.stress if "1.5" in k), next(iter(test.stress)))
        sm = describe(test.stress[k], B=200)["mean"]
    add(7, "survives costs x1.5", None if sm is None else sm > 0, sm, "> 0")
    pf = portfolio_sim(t)
    add(8, "portfolio $100", pf["final_equity"] > 100 and pf["max_dd_pct"] < 50,
        {"final_equity": pf["final_equity"], "max_dd_pct": pf["max_dd_pct"]}, "> $100 and DD < 50 %")
    fm = describe(final.trades, B=200) if final is not None else None
    add(9, "FINAL mean > 0", None if not fm or fm["mean"] is None else fm["mean"] > 0,
        fm and {"mean": fm["mean"], "n": fm["n"]}, "> 0 (n reported)")
    cs = s.get("censored_share")
    add(10, "trades closed by the data horizon (censored)", None if cs is None else cs <= MAX_CENSORED_SHARE, cs,
        f"<= {MAX_CENSORED_SHARE:.0%} (else the simulated rule is not the registered one: INCOMPLETE)")
    rej = auto_rejections(test)
    judged = [c for c in crit[1:] if c["id"] != 10]
    if rej:
        v = "REJECTED"
    elif not crit[0]["pass"]:
        v = "UNDERPOWERED"
    elif any(c["pass"] is False for c in judged):
        v = "FAIL"
    elif any(c["pass"] is None for c in judged) or crit[-1]["pass"] is not True:
        v = "INCOMPLETE"
    else:
        v = "PASS"
    return {"verdict": v, "criteria": crit, "auto_rejections": rej, "split": test.meta.get("split"),
            "hypothesis": test.meta.get("hypothesis"), "censored_share": cs}


def verdict_veto(host: pd.DataFrame, flagged: Sequence[bool], *, oos_host: pd.DataFrame | None = None,
                 oos_flagged: Sequence[bool] | None = None, B: int = 10_000) -> dict:
    """PLAN 3.5 veto / exit bar. ``host`` = host-rule trades on VAL, ``flagged`` = the veto fires on them.
    (1) flagged mean <= unflagged mean - 10 points with the coin-bootstrap CI of the difference excluding 0;
    (2) out of sample, removing flagged trades raises net profit; (3) it removes < 25 % of the host's winning
    profit. UNDERPOWERED when fewer than 30 flagged or unflagged trades."""
    f = np.asarray(flagged, bool)
    r = host["ret_net"].to_numpy(float)
    coins = host["mint"].to_numpy(object)
    nf, nu = int(f.sum()), int((~f).sum())
    crit = []
    if nf < PLAN_MIN["veto_val_flagged"] or nu < PLAN_MIN["veto_val_flagged"]:
        return {"verdict": "UNDERPOWERED", "n_flagged": nf, "n_unflagged": nu, "criteria": crit}
    diff = r[f].mean() - r[~f].mean()
    rng = np.random.default_rng(0)
    codes, _ = pd.factorize(pd.Series(list(coins)))
    ncoin = codes.max() + 1
    diffs = []
    for _ in range(min(B, 4000)):
        w = np.bincount(rng.integers(0, ncoin, ncoin), minlength=ncoin)[codes]
        a, b = (w * f).sum(), (w * ~f).sum()
        if a and b:
            diffs.append((w * f * r).sum() / a - (w * ~f * r).sum() / b)
    lo, hi = np.quantile(diffs, [0.025, 0.975])
    crit.append({"id": 1, "pass": bool(diff <= -0.10 and hi < 0), "value": float(diff), "ci95": (float(lo), float(hi))})
    wins = r[r > 0].sum()
    removed = r[f & (r > 0)].sum() / wins if wins > 0 else 0.0
    crit.append({"id": 3, "pass": bool(removed < 0.25), "value": float(removed)})
    if oos_host is not None and oos_flagged is not None:
        of = np.asarray(oos_flagged, bool)
        ro = oos_host["ret_net"].to_numpy(float)
        crit.append({"id": 2, "pass": bool(ro[~of].sum() > ro.sum()), "value": {"with": float(ro[~of].sum()),
                                                                              "without_veto": float(ro.sum())}})
    v = "PASS" if all(c["pass"] for c in crit) and len(crit) == 3 else (
        "FAIL" if any(not c["pass"] for c in crit) else "INCOMPLETE")
    return {"verdict": v, "n_flagged": nf, "n_unflagged": nu, "criteria": crit}
