"""Y5: a causal calendar gate (UTC session and day type) on two simple hosts. Expected: no edge.

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/Y5/PREREG.md``.

Mechanism (PREREG 1): new marginal buyers of a fresh graduate are people on a regional clock, so if graduation supply
does not scale one-for-one with the cohort that is awake, the per-coin buyer arrival rate -- and the drift after
g + 30 min -- differs by UTC session. The gate reads ONLY the clock at the decision time t (always known; no market
data, no lookahead). It is a FILTER: when the host enters outside the config's session set the coin is skipped, never
re-entered later, so a gated config's trades are exactly its host's trades whose decision lies in the set.

Hosts: ``R30`` (enter at the first decision >= g + 30 min if the coin is alive; catastrophe stop -50 %, 60 min hold)
and ``M1`` (``m1.strategy`` pinned at m1-v1, m = 1, ``rhythm+prec``: version, params hash and m1.py's sha256; refused
if any changes; an M1-host pair never looks at VAL / TEST / CONFIRM / FINAL before M1's own look there, reviews Y5-1
and Y5-3). Sessions: ASIA [00, 08), EU [08, 16), US [16, 24) UTC. Day type (Sat/Sun = WEEKEND) is a TRAIN
conditioning check, not a gate: VAL, TEST and FINAL hold no weekend coin. Every FEATURE the hosts read goes through
:class:`common.AsOf`.

CLI::

    python research/lab2/y5.py --debug                         # census TRAIN third: counts only, no returns
    python research/lab2/y5.py --stage train [--allow-partial] [--rerun-reason TEXT]
    python research/lab2/y5.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/y5.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/y5.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/y5.py --stage final
    python research/lab2/y5.py --stage val --check             # prerequisites only

Each stage writes ``Y5/<stage>.json`` and ``Y5/<stage>.md`` and REFUSES to run when its prerequisites are missing (no
VAL without the written shortlist, TEST / CONFIRM / FINAL once each, never CONFIRM or FINAL before TEST, PLAN 8 data
gates V1-V4, PREREG frozen after the first official TRAIN run, the M1 host unchanged, an M1-host pair never ahead of
M1's own look).
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import common as C  # noqa: E402
import m1 as M1  # noqa: E402

VERSION = "y5-v1"
OUT_DIR = HERE / "Y5"
HYP = "Y5"
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {"debug": "final_train", "train": "train", "val": "val", "test": "test", "confirm": "confirm",
               "final": "final"}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}

# =========================================================================== pre-registered constants (PREREG 2-8)
SESSIONS = ("ASIA", "EU", "US")
SESSION_HOURS = {"ASIA": (0, 8), "EU": (8, 16), "US": (16, 24)}     # UTC hours [lo, hi) of the decision time t
WEEKEND_WDAY = (5, 6)                                                # time.gmtime().tm_wday: Saturday, Sunday
DAY_TYPES = ("WEEKDAY", "WEEKEND")
# R30 host
R30_AGE_S = 1800.0
ALIVE_VOL_USD_15M, ALIVE_MCAP_USD = 1500.0, 6000.0
R30_STOP_PCT = 0.50                    # PLAN X1 exit 6 (G1's R0 host): catastrophe stop -50 % + 60 min
R30_MAX_HOLD_S = 3600.0
EXIT_BY_AGE_S = 178 * 60.0             # registered deadline inside the data (never binds for R30)
R30_PARAMS = {"host": "R30", "rule": "alive at the first decision >= g + 30 min, else never", "age_s": R30_AGE_S,
              "alive_vol_usd_15m": ALIVE_VOL_USD_15M, "alive_mcap_usd": ALIVE_MCAP_USD, "stop_pct": R30_STOP_PCT,
              "max_hold_s": R30_MAX_HOLD_S, "exit_by_age_s": EXIT_BY_AGE_S}
# M1 host (pinned: PREREG 3.2)
M1_HOST_M, M1_HOST_EXIT = 1.0, "rhythm+prec"
M1_REG_VERSION, M1_REG_HASH = "m1-v1", "9c0a14afb895"
# review Y5-3: m1.py itself (the host's code: entries, the MECH-bar detector, exits, classes, clusters)
M1_REG_SHA256 = "b5489ac2686d66970fe93715a69dda4a38dc6395e4a48e80295859c4d289ac7a"
M1_FAMILY = C.hypothesis_family(M1.HYP)          # review Y5-1: whose sealed looks an M1-host pair must not pre-empt
X5_TRADES = HERE / "X5" / "train_trades.csv"     # review Y5-2: X5 gates the same pinned M1 host (counts only)
SIZE_USD = 20.0
FILL = C.FillConfig(exit_delay_bars=1)   # worst fills; stops / time exits fill on the NEXT bar at min(open, low)
# the grid (PREREG 6)
R30_SETS = (("ASIA",), ("EU",), ("US",), ("ASIA", "EU"), ("ASIA", "US"), ("EU", "US"), SESSIONS)
M1_SETS = (("ASIA",), ("EU",), ("US",), SESSIONS)
# selection and verdict bars
TRAIN_MIN_TRADES, TRAIN_MIN_COINS, TRAIN_MIN_CLUSTERS = 60, 40, 3
DAYTYPE_MIN_TRADES = 20
MAX_CENSORED = C.MAX_CENSORED_SHARE
VAL_MIN_SIGN, VAL_MIN_TRADES = 5, 15
TEST_NO_EVIDENCE_N = 5
PASS_MIN_MEAN = 0.03                   # PLAN 3.5 item 2
HOST_REL_MARGIN = 0.06                 # Y5.1: PLAN 3.5 item 5's margin, against the host's own out-of-set trades
SESSION_DAY_MIN_TRADES = 10            # Y5.2
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED")
PRED_SESSION_PREMIUM = 0.06            # PREREG 12 P2

FIXED = {
    "version": VERSION, "session_hours_utc": {s: list(v) for s, v in SESSION_HOURS.items()},
    "clock": "UTC time of the decision t (always known)",
    "day_type": "WEEKEND = Sat/Sun (UTC date of t): TRAIN conditioning check, not a gate",
    "gate": "filter: SKIP the coin when the host enters outside the session set (never a delayed entry)",
    "size_usd": SIZE_USD,
    "fill": "common.FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar stop checks, next-bar exits",
}


def _norm_sessions(sessions: Sequence[str]) -> tuple[str, ...]:
    s = list(sessions)
    if not s or len(s) != len(set(s)) or not set(s) <= set(SESSIONS):
        raise ValueError(f"session set {sessions!r} is not a subset of {SESSIONS}")
    return tuple(x for x in SESSIONS if x in set(s))


def m1_host_params() -> dict:
    return M1.make_params(M1_HOST_M, M1_HOST_EXIT)


def make_params(host: str, sessions: Sequence[str]) -> dict:
    """One registered config (PREREG 6). Anything outside the grid raises."""
    ss = _norm_sessions(sessions)
    allowed = {"R30": R30_SETS, "M1": M1_SETS}.get(host)
    if allowed is None or ss not in allowed:
        raise ValueError(f"({host!r}, {ss}) is not in the pre-registered grid")
    hp = dict(R30_PARAMS) if host == "R30" else m1_host_params()
    hv = VERSION if host == "R30" else M1.VERSION
    pin = {} if host == "R30" else {"host_code_sha256": M1_REG_SHA256}
    return {**FIXED, "host": host, "host_params": hp, "host_version": hv, **pin, "sessions": list(ss)}


GRID = [make_params("R30", s) for s in R30_SETS] + [make_params("M1", s) for s in M1_SETS]
assert len(GRID) == 11          # PREREG 6 (<= 12 configs)


def config_key(p: Mapping[str, Any]) -> str:
    ss = list(p["sessions"])
    return f"{p['host']}|{'ALL' if len(ss) == len(SESSIONS) else '+'.join(ss)}"


def is_candidate(p: Mapping[str, Any]) -> bool:
    """The ungated hosts are comparators, never candidates (PREREG 6)."""
    return len(p["sessions"]) < len(SESSIONS)


def host_config(p: Mapping[str, Any]) -> dict:
    """The ungated config of ``p``'s host."""
    return make_params(p["host"], SESSIONS)


def registry_index(p: Mapping[str, Any]) -> int:
    return [config_key(q) for q in GRID].index(config_key(p))


class Y5Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing (or a stop rule fired)."""


# =========================================================================== the calendar (the only thing the gate reads)


def session_of(t: float) -> str:
    """Session of the UTC time ``t`` (PREREG 2)."""
    h = int((float(t) % 86400.0) // 3600.0)
    for s, (lo, hi) in SESSION_HOURS.items():
        if lo <= h < hi:
            return s
    raise ValueError(f"hour {h} outside every session")          # unreachable: the sessions partition 0-24


def day_type(t: float) -> str:
    return "WEEKEND" if time.gmtime(float(t)).tm_wday in WEEKEND_WDAY else "WEEKDAY"


def utc_date(t: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(float(t)))


def utc_hour(t: float) -> int:
    return int((float(t) % 86400.0) // 3600.0)


# =========================================================================== hosts and the gated strategy


def host_r30(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
    """R30: at the first decision >= g + 30 min, enter if alive, else never trade the coin (PREREG 3.1)."""
    if pos is not None:
        return None                     # mechanical exits only
    if snap.age_s < p["age_s"]:
        return None
    if snap.alive(p["alive_vol_usd_15m"], p["alive_mcap_usd"]):
        return C.Enter(exits=C.ExitSpec(stop_pct=p["stop_pct"], max_hold_s=p["max_hold_s"],
                                        exit_by_age_s=p["exit_by_age_s"]), tag="R30")
    return C.SKIP


def host_m1(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
    """M1 as registered (m1-v1): entries, mechanical exits and the rhythm / precursor exits."""
    return M1.strategy(snap, p, pos)


HOST_FN = {"R30": host_r30, "M1": host_m1}


def strategy(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
    """The gated host for common.backtest: the host's own decision, and SKIP when it enters outside the set."""
    act = HOST_FN[p["host"]](snap, p["host_params"], pos)
    if pos is None and isinstance(act, C.Enter) and session_of(snap.t) not in p["sessions"]:
        return C.SKIP
    return act


def placebo_alive(snap: C.AsOf) -> bool:
    return snap.alive(ALIVE_VOL_USD_15M, ALIVE_MCAP_USD)


def placebo_spec(host: str) -> dict:
    """R30: alive coins at any clock time (the calendar null). M1: M1's class-matched control (+ unmatched)."""
    if host == "R30":
        return {"eligible": placebo_alive, "strata": None, "controls": {}}
    return {"eligible": M1.placebo_ok, "strata": M1.placebo_stratum, "controls": M1.PLACEBO_CONTROLS}


STRESS = {"costs_x1.5": FILL.stressed(1.5), "rent_0.22": dataclasses.replace(FILL, rent_usd=0.22),
          "same_bar_exits": dataclasses.replace(FILL, exit_delay_bars=0),
          "open_fills": dataclasses.replace(FILL, entry_fill="open", exit_fill="open")}
DECL = {"uses_organic_flow": False, "uses_wallet_reputation": False, "uses_truncated_windows": False,
        "uses_current_state_fields": False}


def m1_code_sha256() -> str:
    return hashlib.sha256(Path(M1.__file__).read_bytes()).hexdigest()


def common_sha256() -> str:
    """common.py (the engine every host and hypothesis runs on): recorded and flagged, never pinned (PREREG 3.2)."""
    return hashlib.sha256(Path(C.__file__).read_bytes()).hexdigest()


def host_problems() -> list[str]:
    """The M1 host must be the registered one (PREREG 3.2): version, params hash and m1.py's sha256 (review Y5-3)."""
    out = []
    if M1.VERSION != M1_REG_VERSION:
        out.append(f"m1.VERSION is {M1.VERSION!r}, Y5 registered {M1_REG_VERSION!r}")
    h = C.params_hash(m1_host_params())
    if h != M1_REG_HASH:
        out.append(f"the M1 host params hash is {h}, Y5 registered {M1_REG_HASH}")
    sha = m1_code_sha256()
    if sha != M1_REG_SHA256:
        out.append(f"m1.py sha256 is {sha[:12]}, Y5 registered {M1_REG_SHA256[:12]} (the host's code changed: "
                   "re-register it before Y5's PREREG lock, or a new Y5 version after it)")
    return out


def _m1_never_spends(stage: str, m1_out_dir: Path) -> str | None:
    """Why M1's own written decisions forbid M1 ``stage`` (mirrors m1.check_prereqs), or None."""
    tr = _read_json(m1_out_dir / "train.json")
    if not tr or tr.get("provisional"):
        return None                                  # M1 has no official TRAIN decision yet: it may still go on
    tv = (tr.get("decision") or {}).get("verdict")
    if tv != "SHORTLISTED":
        return f"M1's TRAIN decision is {tv}"
    if stage == "val":
        return None
    va = _read_json(m1_out_dir / "val.json")
    vv = (va or {}).get("decision", {}).get("verdict") if va else None
    if va and vv not in M1.PROCEED_VAL:
        return f"M1's VAL decision is {vv}"
    te = _read_json(m1_out_dir / "test.json")
    if stage == "confirm" and te and not M1.confirm_allowed(te)[0]:
        return f"M1's TEST closed its CONFIRM ({M1.confirm_allowed(te)[1]})"
    return None


def m1_host_gate(stage: str, ledger_path: Path | None = None, m1_out_dir: Path | None = None) -> str | None:
    """PREREG 3.2 (review Y5-1). Y5's M1 host is M1's own candidate whenever M1's TRAIN picks m* = 1, and common's
    one-look rules count per family, so an M1-host pair could disclose M1's sealed VAL / TEST / CONFIRM / FINAL before
    M1 spends its one look there. It may run on such a split only after the M1 family spent that split group in the
    canonical trials ledger, or when M1's own written decisions forbid M1 that stage. Returns the refusal reason, or
    None when the pair may run."""
    if stage not in ("val", "test", "confirm", "final"):
        return None
    grp = C.split_group(STAGE_SPLIT[stage])
    with C._ledger(ledger_path, write=False) as led:
        if C._family_looks(led, M1_FAMILY, grp):
            return None
    if _m1_never_spends(stage, Path(m1_out_dir or M1.OUT_DIR)):
        return None
    return (f"M1 has not spent its own {grp} look, and may still: an M1-host pair would show M1's candidate "
            f"(m = 1, rhythm+prec) on {grp} first (review Y5-1). Run M1's {stage.upper()} first")


def m1_host_gate_note(stage: str, ledger_path: Path | None, m1_out_dir: Path | None) -> str:
    grp = C.split_group(STAGE_SPLIT[stage])
    with C._ledger(ledger_path, write=False) as led:
        if C._family_looks(led, M1_FAMILY, grp):
            return f"M1 spent its own {grp} look first (trials ledger)"
    why = _m1_never_spends(stage, Path(m1_out_dir or M1.OUT_DIR))
    return f"M1 never spends {grp}: {why}"


def x5_overlap_counts(path: Path | None = None) -> dict:
    """PREREG 3.4 (review Y5-2), counts only: X5's M1-host TRAIN trades (the same pinned host, gated by a market regime
    that leans to the US / late-UTC hours) by X5 state (each signal at q = 0.5) and Y5 session of the decision. Read
    from X5's own trades file; returns are never read into the result."""
    p = Path(path or X5_TRADES)
    if not p.exists():
        return {"available": False, "note": f"{p.name} not written (X5 has not run an official TRAIN)"}
    t = pd.read_csv(p, usecols=lambda c: c in ("role", "t_dec") or (c.startswith("st_") and c.endswith("_q0.5")))
    h = t[t["role"] == "host-M1"] if "role" in t else t.iloc[0:0]
    sess = [session_of(x) for x in h["t_dec"]] if len(h) else []
    out = {}
    for col in sorted(c for c in h.columns if c.startswith("st_")):
        tab: dict[str, dict[str, int]] = {}
        for s_, v in zip(sess, h[col].fillna("UNKNOWN").astype(str)):
            tab.setdefault(v, {x: 0 for x in SESSIONS})[s_] += 1
        out[col] = tab
    return {"available": True, "file": str(p), "n_host_trades": int(len(h)), "by_state_and_session": out}


# =========================================================================== trade tables (outcomes; never features)


def with_calendar(t: pd.DataFrame) -> pd.DataFrame:
    """Trades + the calendar of their DECISION time (session, day type, UTC date, UTC hour)."""
    tt = t["t_dec"].to_numpy(float) if len(t) else np.zeros(0)
    return t.assign(session=[session_of(x) for x in tt], day_type=[day_type(x) for x in tt],
                    date=[utc_date(x) for x in tt], hour=[utc_hour(x) for x in tt])


def signal_diffs(trades: pd.DataFrame, placebo: pd.DataFrame) -> np.ndarray:
    """Per trade: ret_net minus the mean of ITS placebo draws (NaN when it has none). Placebo ``signal`` = row index."""
    out = np.full(len(trades), np.nan)
    if len(trades) and len(placebo):
        pm = placebo.groupby("signal")["ret_net"].mean()
        idx = pm.index.to_numpy(int)
        ok = (idx >= 0) & (idx < len(trades))
        out[idx[ok]] = trades["ret_net"].to_numpy(float)[idx[ok]] - pm.to_numpy(float)[ok]
    return out


def _nanmean(x: np.ndarray) -> float | None:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    return float(x.mean()) if len(x) else None


def group_table(t: pd.DataFrame, diffs: np.ndarray, key: str, levels: Sequence[str]) -> dict:
    """{level: {n, n_coins, mean, placebo_diff, n_matched}} over the trades' ``key`` column."""
    out = {}
    r = t["ret_net"].to_numpy(float) if len(t) else np.zeros(0)
    col = t[key].to_numpy(object) if len(t) else np.zeros(0, object)
    for lv in levels:
        m = col == lv
        out[lv] = {"n": int(m.sum()), "n_coins": int(t.loc[m, "mint"].nunique()) if m.any() else 0,
                   "mean": float(r[m].mean()) if m.any() else None, "placebo_diff": _nanmean(diffs[m]),
                   "n_matched": int(np.isfinite(diffs[m]).sum())}
    return out


def session_days(t: pd.DataFrame, diffs: np.ndarray, min_trades: int = SESSION_DAY_MIN_TRADES) -> dict:
    """Y5.2: per UTC date of the decision, n, mean and the per-signal placebo diff; pass = None when < 2 dates hold
    >= ``min_trades`` trades, else positive diff on >= ceil(2 D / 3) of them."""
    rows = []
    if len(t):
        for d in sorted(set(t["date"])):
            m = (t["date"] == d).to_numpy(bool)
            rows.append({"date": d, "n": int(m.sum()), "mean": float(t.loc[m, "ret_net"].mean()),
                         "placebo_diff": _nanmean(diffs[m])})
    q = [r for r in rows if r["n"] >= min_trades and r["placebo_diff"] is not None]
    D = len(q)
    pos = sum(1 for r in q if r["placebo_diff"] > 0)
    need = math.ceil(2 * D / 3) if D else None
    return {"days": rows, "qualifying_days": D, "positive_days": pos, "need_positive": need,
            "pass": None if D < 2 else bool(pos >= need)}


def _diff_ci(a: np.ndarray, ga: Sequence[Any], b: np.ndarray, gb: Sequence[Any], B: int) -> tuple | None:
    """95 % CI of mean(a) - mean(b), resampling the coins of each (disjoint) group independently."""
    if len(set(ga)) < 2 or len(set(gb)) < 2:
        return None
    ma = C.coin_bootstrap_means(a, ga, B, seed=0)
    mb = C.coin_bootstrap_means(b, gb, B, seed=1)
    d = ma - mb
    return float(np.quantile(d, 0.025)), float(np.quantile(d, 0.975))


def host_rel(t: pd.DataFrame, host_t: pd.DataFrame | None, sessions: Sequence[str], B: int) -> dict | None:
    """PREREG 7.2: the config's mean minus its host's mean OUTSIDE the session set (None without host trades)."""
    if host_t is None or not len(t):
        return None
    out = host_t[~host_t["session"].isin(list(sessions))]
    if not len(out):
        return {"n_out": 0, "mean_out": None, "diff": None, "diff_ci95": None}
    a, b = t["ret_net"].to_numpy(float), out["ret_net"].to_numpy(float)
    return {"n_out": int(len(out)), "mean_out": float(b.mean()), "diff": float(a.mean() - b.mean()),
            "diff_ci95": _diff_ci(a, t["mint"].to_numpy(object), b, out["mint"].to_numpy(object), B)}


def veto_report(host_t: pd.DataFrame, sessions_flagged: Sequence[str], oos: pd.DataFrame | None = None) -> dict:
    """PREREG 7.3 (reported, never decisive for EDGE): common.verdict_veto with flagged = the host's trades in
    ``sessions_flagged`` (``oos`` = the out-of-sample host trades for criterion 2)."""
    f = host_t["session"].isin(list(sessions_flagged)).to_numpy(bool)
    kw = {}
    if oos is not None and len(oos):
        kw = {"oos_host": oos, "oos_flagged": oos["session"].isin(list(sessions_flagged)).to_numpy(bool)}
    try:
        return {"flagged_sessions": list(sessions_flagged), **C.verdict_veto(host_t, f, B=2000, **kw)}
    except (ValueError, IndexError) as e:            # an empty side: nothing to compare
        return {"flagged_sessions": list(sessions_flagged), "verdict": "UNDERPOWERED", "error": str(e)}


# =========================================================================== evaluation


def evaluate(res: C.Result, host_t: pd.DataFrame | None, clusters: Mapping[str, str] | None, *, B: int, hide: bool,
             n_trials_total: int | None) -> dict:
    """Per-config report. On the debug split: counts only (n, coins, sessions, day types, dates, hours, placebo and
    control counts) -- never returns, exit reasons, fills, placebo outcomes or cluster outcomes."""
    p = res.meta["params"]
    t = with_calendar(res.trades)
    base = {"config": config_key(p), "params_hash": C.params_hash(p), "hypothesis": res.meta["hypothesis"],
            "host": p["host"], "sessions": list(p["sessions"]), "candidate": is_candidate(p),
            "n": int(len(t)), "n_coins": int(t["mint"].nunique()) if len(t) else 0,
            "by_session_n": {s: int((t["session"] == s).sum()) for s in SESSIONS} if len(t) else {},
            "by_day_type_n": {d: int((t["day_type"] == d).sum()) for d in DAY_TYPES} if len(t) else {},
            "by_date_n": t["date"].value_counts().sort_index().to_dict() if len(t) else {},
            "by_hour_n": {int(k): int(v) for k, v in t["hour"].value_counts().sort_index().items()} if len(t) else {},
            "by_tag_n": t["tag"].value_counts().to_dict() if len(t) else {},
            "n_placebo": int(len(res.placebo)), "n_controls": {k: int(len(v)) for k, v in res.controls.items()},
            "horizon_exits": int((t["reason"] == "horizon").sum()) if len(t) else 0,
            "trial": {k: res.meta.get(k) for k in ("config", "new_trial", "n_trials_total")}}
    if p["host"] == "M1" and clusters is not None:
        base["n_clusters"] = int(t["mint"].map(clusters).fillna(t["mint"]).nunique()) if len(t) else 0
    if hide:
        base["returns"] = "hidden on the debug split (never choose parameters on FINAL data)"
        return base
    base["reasons"] = t["reason"].value_counts().to_dict() if len(t) else {}
    d = C.describe(t, B=B, n_trials_total=n_trials_total)
    base.update({k: d.get(k) for k in ("mean", "median", "win_rate", "sd", "ci90", "ci95", "ci90_block", "ci95_block",
                                        "n_blocks", "censored_share", "top_coin_share", "top3_coin_share",
                                        "mean_without_top2", "halves", "mean_hold_min", "deflated_sharpe")})
    if len(t):
        mid, net = t["ret_mid"].to_numpy(float), t["ret_net"].to_numpy(float)
        base["cost_decomposition"] = {"mean_gross_move_worst_fills": float(mid.mean()),
                                      "mean_cost": float((mid - net).mean())}
    base["placebo"] = C.placebo_compare(t, res.placebo, B=B) if len(res.placebo) and len(t) else None
    base["controls"] = {k: C.placebo_compare(t, v, B=B) for k, v in res.controls.items() if len(v) and len(t)}
    base["stress"] = {k: C.describe(v, B=200).get("mean") for k, v in res.stress.items()}
    base["portfolio"] = {k: v for k, v in C.portfolio_sim(t).items() if k != "skipped_mints"}
    diffs = signal_diffs(t, res.placebo)
    base["by_session"] = group_table(t, diffs, "session", SESSIONS)
    base["by_day_type"] = group_table(t, diffs, "day_type", DAY_TYPES)
    base["session_days"] = session_days(t, diffs)
    base["host_rel"] = host_rel(t, host_t, p["sessions"], B) if is_candidate(p) else None
    if p["host"] == "M1" and clusters is not None:
        base["clusters"] = M1._cluster_stats(t, clusters, B)
    return base


def y5_extras(ev: Mapping[str, Any]) -> list[dict]:
    """PREREG 8 TEST extras Y5.1-Y5.3."""
    hr = (ev.get("host_rel") or {}).get("diff")
    sd = ev.get("session_days") or {}
    out = [{"id": "Y5.1", "name": f"host-relative diff >= {HOST_REL_MARGIN:+.2f}", "pass": None if hr is None else
            bool(hr >= HOST_REL_MARGIN), "value": hr},
           {"id": "Y5.2", "name": f"not one session-day: >= 2 UTC dates with >= {SESSION_DAY_MIN_TRADES} trades, "
            "placebo diff > 0 on >= 2/3 of them", "pass": sd.get("pass"),
            "value": {k: sd.get(k) for k in ("qualifying_days", "positive_days", "need_positive")}}]
    if ev.get("host") == "M1":
        cl = ev.get("clusters") or {}
        nc, mw = cl.get("n_clusters"), cl.get("mean_without_largest")
        out.append({"id": "Y5.3", "name": f">= {TRAIN_MIN_CLUSTERS} operator clusters and mean > 0 without the "
                    "largest", "pass": None if nc is None or mw is None else bool(nc >= TRAIN_MIN_CLUSTERS and mw > 0),
                    "value": {"n_clusters": nc, "mean_without_largest": mw}})
    else:
        out.append({"id": "Y5.3", "name": "operator clusters (M1 host only)", "pass": None,
                    "value": "not applicable (R30 host)", "blocking_when_none": False})
    return out


def combine_verdict(base: Mapping[str, Any], extras: list[dict]) -> str:
    """PLAN 3.5 items 1-8 and 10 + 3.6 (common.verdict_entry) + the Y5 extras. Item 9 (FINAL mean > 0) is judged in the
    overall verdict once FINAL ran, so a missing FINAL never makes TEST / CONFIRM 'INCOMPLETE'."""
    if base.get("auto_rejections"):
        return "REJECTED"
    crit = {c["id"]: c["pass"] for c in base["criteria"] if c["id"] != 9}
    censored_ok = crit.pop(10, True)
    if not crit.get(1):
        return "UNDERPOWERED"
    rest = [v for k, v in crit.items() if k != 1]
    if any(v is False for v in rest) or any(e["pass"] is False for e in extras):
        return "FAIL"
    if any(v is None for v in rest) or censored_ok is not True or any(
            e["pass"] is None and e.get("blocking_when_none", True) for e in extras):
        return "INCOMPLETE"
    return "PASS"


# =========================================================================== pre-registered decisions


def train_row(p: Mapping[str, Any], e: Mapping[str, Any]) -> dict:
    """PREREG 8 TRAIN qualification of one candidate config."""
    pc = (e.get("placebo") or {}).get("mean_diff")
    hr = (e.get("host_rel") or {}).get("diff")
    cs = e.get("censored_share")
    powered = e["n"] >= TRAIN_MIN_TRADES and e["n_coins"] >= TRAIN_MIN_COINS
    if p["host"] == "M1":
        powered = powered and (e.get("n_clusters") or 0) >= TRAIN_MIN_CLUSTERS
    dts = e.get("by_day_type") or {}
    day_ok = {d: bool((dts.get(d) or {}).get("n", 0) >= DAYTYPE_MIN_TRADES
                      and (dts.get(d) or {}).get("placebo_diff") is not None and dts[d]["placebo_diff"] > 0)
              for d in DAY_TYPES}
    good = (powered and e.get("mean") is not None and e["mean"] > 0
            and e.get("mean_without_top2") is not None and e["mean_without_top2"] > 0
            and pc is not None and pc > 0 and hr is not None and hr > 0 and all(day_ok.values())
            and cs is not None and cs <= MAX_CENSORED)
    ci = e.get("ci90")
    return {"config": config_key(p), "host": p["host"], "sessions": list(p["sessions"]), "powered": bool(powered),
            "qualifies": bool(good), "n": e["n"], "coins": e["n_coins"], "clusters": e.get("n_clusters"),
            "mean": e.get("mean"), "mean_without_top2": e.get("mean_without_top2"), "ci90_lo": ci[0] if ci else None,
            "placebo_diff": pc, "host_rel_diff": hr, "day_type_ok": day_ok, "censored_share": cs,
            "registry_index": registry_index(p)}


def decide_train(evals: Mapping[str, Mapping[str, Any]]) -> dict:
    """PREREG 8: qualifiers ranked by the coin-bootstrap 90 % CI lower bound (then mean, then registry order);
    shortlist = the pair (rank-1 candidate, its ungated host)."""
    rows = [train_row(p, evals[config_key(p)]) for p in GRID if is_candidate(p)]
    q = sorted((r for r in rows if r["qualifies"]),
               key=lambda r: (-(r["ci90_lo"] if r["ci90_lo"] is not None else -math.inf), -r["mean"],
                              r["registry_index"]))
    if q:
        best = q[0]
        cand = make_params(best["host"], best["sessions"])
        sl = [cand, host_config(cand)]
        return {"verdict": "SHORTLISTED", "rows": rows, "ranked": [r["config"] for r in q], "candidate": best["config"],
                "shortlist": sl, "shortlist_hashes": [C.params_hash(x) for x in sl]}
    if any(r["powered"] for r in rows):
        v, why = "NO_CONFIG", "a powered candidate failed the mean / top-2 / control / host-relative / day-type bars"
    else:
        v = "UNDERPOWERED_TRAIN"
        why = (f"no candidate reached >= {TRAIN_MIN_TRADES} trades from >= {TRAIN_MIN_COINS} coins (M1 host: and >= "
               f"{TRAIN_MIN_CLUSTERS} clusters); best {max(r['n'] for r in rows)} trades")
    return {"verdict": v, "reason": why, "rows": rows, "ranked": [], "candidate": None, "shortlist": [],
            "shortlist_hashes": []}


def score_predictions(evals: Mapping[str, Mapping[str, Any]]) -> dict:
    """PREREG 12 predictions (reports, never decisive)."""
    cand = {k: e for k, e in evals.items() if e.get("candidate")}
    means = {k: e.get("mean") for k, e in cand.items()}
    single = [config_key(make_params("R30", (s,))) for s in SESSIONS]
    prem = {k: (evals[k].get("host_rel") or {}).get("diff") for k in single if k in evals}
    signs = {}
    for k in single:
        dt = (evals.get(k) or {}).get("by_day_type") or {}
        signs[k] = {d: (None if (dt.get(d) or {}).get("placebo_diff") is None else
                        bool(dt[d]["placebo_diff"] > 0)) for d in DAY_TYPES}
    flat = [v for s in signs.values() for v in s.values()]
    p3_violated = bool(flat and all(v is not None for v in flat) and len(set(flat)) == 1)
    return {"P1_no_candidate_mean_net_above_0": {"held": all(v is None or v <= 0 for v in means.values()),
                                                 "values": means},
            "P2_r30_session_premium_within_6pts": {"held": all(v is None or abs(v) < PRED_SESSION_PREMIUM
                                                               for v in prem.values()), "values": prem},
            "P3_no_stable_sign_across_sessions_and_day_types": {"held": not p3_violated, "signs": signs},
            "note": "predictions are reports (PREREG 12); the TRAIN decision is decide_train's"}


def decide_val(ev: Mapping[str, Any]) -> dict:
    n = ev["n"]
    mean, mw2 = ev.get("mean"), ev.get("mean_without_top2")
    hr = (ev.get("host_rel") or {}).get("diff")
    if n < VAL_MIN_SIGN:
        v = "UNDERPOWERED_VAL"
    elif not (mean is not None and mean > 0 and (mw2 is None or mw2 > 0) and hr is not None and hr > 0):
        v = "FAIL_VAL"
    elif n < VAL_MIN_TRADES:
        v = "SELECTED_UNDERPOWERED"
    else:
        v = "SELECTED"
    return {"verdict": v, "n": n, "mean": mean, "mean_without_top2": mw2, "host_rel_diff": hr,
            "proceed": v in PROCEED_VAL}


def confirm_allowed(test_doc: Mapping[str, Any]) -> tuple[bool, str]:
    """PREREG 8: CONFIRM is spent when TEST is not REJECTED and (TEST mean > 0 or TEST n < 5 = no evidence)."""
    v = test_doc.get("verdict") or {}
    c = (test_doc.get("configs") or {}).get("candidate") or {}
    if v.get("verdict") == "REJECTED":
        return False, "TEST was REJECTED (PLAN 3.6)"
    n, mean = c.get("n", 0), c.get("mean")
    if n < TEST_NO_EVIDENCE_N or (mean is not None and mean > 0):
        return True, "ok"
    return False, f"TEST mean {mean} <= 0 on {n} trades: Y5 failed TEST, CONFIRM not spent"


FINAL_JUDGED = ("final_val", "final_test")
FINAL_DEBUG = "final_train"


def final_decision(t: pd.DataFrame) -> dict:
    """PLAN 3.5 item 9 on the census thirds Y5 never looked at (the TRAIN third hosted the debug run: reported apart)."""
    judged = t[t["split"].isin(FINAL_JUDGED)] if len(t) else t
    dbg = t[t["split"] == FINAL_DEBUG] if len(t) else t
    per = {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for s, g in t.groupby("split")} if len(t) else {}
    return {"verdict": "REPORTED", "judged_on": list(FINAL_JUDGED), "n": int(len(judged)),
            "mean": float(judged["ret_net"].mean()) if len(judged) else None,
            "mean_positive": None if not len(judged) else bool(judged["ret_net"].mean() > 0), "per_third": per,
            "debug_third": {"n": int(len(dbg)), "mean": float(dbg["ret_net"].mean()) if len(dbg) else None,
                            "note": "census TRAIN third: hosted the debug run (PREREG 13), not judged"}}


# =========================================================================== stage prerequisites


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return None


def coverage_check(cov: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Every chain hour of the split scanned (curve AND B2) and <= 5 % of tradeable coins missing B2 data."""
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


def _shortlist(shortlist_path: Path | None) -> dict | None:
    return _read_json(Path(shortlist_path or C.shortlist_dir()) / f"{HYP}.json")


def _pair(sl: Mapping[str, Any]) -> tuple[dict | None, dict | None]:
    cands = [c for c in sl.get("configs", []) if is_candidate(c)]
    hosts = [c for c in sl.get("configs", []) if not is_candidate(c)]
    return (cands[0] if len(cands) == 1 else None), (hosts[0] if len(hosts) == 1 else None)


def stage_configs(stage: str, out_dir: Path, shortlist_path: Path | None = None) -> list[tuple[str, dict | None]]:
    """[(role, params)]: the grid (debug / train), else the shortlisted pair (candidate, host)."""
    if stage in ("debug", "train"):
        return [(config_key(p), p) for p in GRID]
    sl = _shortlist(shortlist_path)
    if not sl:
        return []
    cand, host = _pair(sl)
    return [("candidate", cand), ("host", host)]


def check_prereqs(stage: str, out_dir: Path = OUT_DIR, *, flow: Path | None = None, ledger_path: Path | None = None,
                  shortlist_path: Path | None = None, env: Mapping[str, str] | None = None,
                  rerun_reason: str | None = None, m1_out_dir: Path | None = None) -> dict:
    """Raise :class:`Y5Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise Y5Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise Y5Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    if lock and lock.get("sha256") != _sha(prereg):
        raise Y5Refused("PREREG.md changed after the first official TRAIN run; record changes in Y5/AMENDMENTS.md "
                        "as a new version instead")
    hp = host_problems()
    if hp:
        raise Y5Refused("the M1 host is not the registered one (a new Y5 version is needed): " + "; ".join(hp))
    ok, bad = C.validation_gates(STAGE_SPLIT[stage], flow)
    if not ok and stage != "debug":         # debug checks mechanics only; every real stage needs stop rule 1
        raise Y5Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {"stage": stage, "prereg_sha256": _sha(prereg), "prereg_locked": bool(lock),
            "data_gates": {"ok": ok, "problems": bad}}
    if stage == "debug":
        return info
    train = _read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise Y5Refused("TRAIN already ran on complete data (Y5/train.json); its decision is final. A re-run needs "
                            "--rerun-reason naming the data correction that justifies it")
        return info
    if not train:
        raise Y5Refused("no TRAIN result (Y5/train.json): run --stage train first")
    if train.get("provisional"):
        raise Y5Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    tv = (train.get("decision") or {}).get("verdict")
    if tv != "SHORTLISTED":
        raise Y5Refused(f"TRAIN decision {tv}: Y5 stopped before VAL")
    sl = _shortlist(shortlist_path)
    if not sl:
        raise Y5Refused("no VAL shortlist for Y5 (written by a complete --stage train)")
    if list(sl.get("hashes", [])) != list(train["decision"].get("shortlist_hashes", [])):
        raise Y5Refused("the Y5 shortlist on disk differs from the one TRAIN wrote")
    if any(p is None for p in _pair(sl)):
        raise Y5Refused("the Y5 shortlist is not a (candidate, ungated host) pair")
    if _pair(sl)[0]["host"] == "M1":                 # review Y5-1: never M1's sealed split before M1 itself
        why = m1_host_gate(stage, ledger_path, m1_out_dir)
        if why:
            raise Y5Refused(why)
        info["m1_host_gate"] = m1_host_gate_note(stage, ledger_path, m1_out_dir)
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise Y5Refused("VAL already ran (Y5/val.json exists): VAL is evaluated once")
        return info
    val = _read_json(out_dir / "val.json")
    if not val:
        raise Y5Refused(f"no VAL result (Y5/val.json): {stage.upper()} needs a VAL decision first")
    vv = (val.get("decision") or {}).get("verdict")
    if vv not in PROCEED_VAL:
        raise Y5Refused(f"VAL decision {vv}: Y5 stopped (PLAN 8 rule 7 input); {stage.upper()} is not spent")
    test = _read_json(out_dir / "test.json")
    if stage in ("confirm", "final") and not test:
        raise Y5Refused(f"never {stage.upper()} before TEST: run --stage test first")
    if stage == "confirm":
        ok_c, why = confirm_allowed(test)
        if not ok_c:
            raise Y5Refused(why)
    if (out_dir / f"{stage}.json").exists():
        raise Y5Refused(f"{stage.upper()} already ran (Y5/{stage}.json exists): one run per hypothesis")
    if any(C.hypothesis_family(r.get("hypothesis", "")) == HYP and C.split_group(r.get("split", "")) ==
           C.split_group(split) and not r.get("debug") for r in _runs(ledger_path)):
        raise Y5Refused(f"{HYP} already had its one {split} look (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise Y5Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
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


def r30_decision_time(cd: C.CoinData) -> float:
    """The R30 decision: the first grid time (minute boundary + 20 s) at or after g + 30 min."""
    j = max(0, math.ceil((cd.g + R30_AGE_S - C.GRID_OFFSET_S - cd.m0) / 60.0))
    return float(cd.bar_start(j) + C.GRID_OFFSET_S)


def session_exposure_h(lo: float, hi: float) -> dict[str, float]:
    """Hours of [lo, hi) that fall in each session (for per-session-day rates)."""
    out = {s: 0.0 for s in SESSIONS}
    t = float(lo)
    while t < hi:
        nxt = min(hi, (math.floor(t / 3600.0) + 1) * 3600.0)
        out[session_of(t)] += (nxt - t) / 3600.0
        t = nxt
    return out


def event_counts(ds: C.Dataset) -> dict:
    """Counts only (no outcomes): the R30 decision of every coin by session, day type and UTC hour; how many are alive
    then (= R30 host entries); the exposure hours of each session in the split's creation window shifted to g + 30."""
    n_dec = {s: 0 for s in SESSIONS}
    n_alive = {s: 0 for s in SESSIONS}
    by_day = {d: 0 for d in DAY_TYPES}
    by_hour: dict[int, int] = {}
    for m in ds.mints:
        cd = ds.coin(m)
        t = r30_decision_time(cd)
        s = session_of(t)
        n_dec[s] += 1
        by_day[day_type(t)] += 1
        by_hour[utc_hour(t)] = by_hour.get(utc_hour(t), 0) + 1
        if placebo_alive(ds.asof(m, t)):
            n_alive[s] += 1
    c = ds.coins["created_for_split"].to_numpy(float) if len(ds) else np.zeros(0)
    expo = session_exposure_h(float(c.min()) + R30_AGE_S, float(c.max()) + R30_AGE_S) if len(c) else {}
    return {"coins": len(ds), "span_days": _span_days(ds), "r30_decisions_by_session": n_dec,
            "r30_alive_by_session": n_alive, "r30_decisions_by_day_type": by_day,
            "r30_decisions_by_hour": dict(sorted(by_hour.items())),
            "creation_window_plus_30min_utc": [C.utc_str(float(c.min()) + R30_AGE_S),
                                               C.utc_str(float(c.max()) + R30_AGE_S)] if len(c) else None,
            "session_exposure_h": expo}


def per_session_day(n_by_session: Mapping[str, int], expo: Mapping[str, float], min_h: float = 2.0) -> dict:
    """Entries per 8-hour session-day ~ n / exposure hours x 8 (None when the session was observed < ``min_h``)."""
    return {s: (8.0 * n_by_session.get(s, 0) / expo[s] if expo.get(s, 0.0) >= min_h else None) for s in SESSIONS}


def run_stage(stage: str, *, out_dir: Path = OUT_DIR, allow_partial: bool = False, rerun_reason: str | None = None,
              ds: C.Dataset | None = None, census: C.Census | None = None, flow: Path | None = None,
              ledger_path: Path | None = None, shortlist_path: Path | None = None, B: int = 10_000,
              n_placebo: int = 20, env: Mapping[str, str] | None = None, _skip_coverage: bool = False,
              m1_out_dir: Path | None = None) -> dict:
    """Run one stage end to end and write Y5/<stage>.json + .md (``ds`` injection is for tests)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(stage, out_dir, flow=flow, ledger_path=ledger_path, shortlist_path=shortlist_path, env=env,
                         rerun_reason=rerun_reason, m1_out_dir=m1_out_dir)
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "y5_debug_trials.json"   # debug never reaches the real ledger
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    provisional = False
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise Y5Refused(f"{split} data incomplete: " + "; ".join(notes[:6])
                                + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else ""))
    covs = list(cov.values()) if (split == "final" and "split" not in cov) else [cov]
    hard = [] if debug else [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
    if hard:                                    # never allowed, not even provisionally (a future SOL price)
        raise Y5Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_configs(stage, out_dir, shortlist_path)
    if not configs or any(p is None for _, p in configs):
        raise Y5Refused("no configs to run (shortlist missing or not a candidate / host pair)")

    def _execute(ds: C.Dataset | None) -> dict:
        if not debug:   # commit: every config is allowed BEFORE any data is read
            try:
                for _, p in configs:
                    C._check_run_allowed(HYP, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise Y5Refused(str(e)) from e
        if stage == "train" and not provisional:
            out_dir.mkdir(parents=True, exist_ok=True)
            if not (out_dir / "prereg.lock").exists():
                (out_dir / "prereg.lock").write_text(json.dumps({"sha256": info["prereg_sha256"],
                                                                 "locked_utc": C.utc_str(time.time())}, indent=1))
            if rerun_reason and (out_dir / "train.json").exists():      # archive, never overwrite, an official run
                stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
                for ext in ("json", "md"):
                    p = out_dir / f"train.{ext}"
                    if p.exists():
                        p.rename(out_dir / f"train_prev_{stamp}.{ext}")
        if ds is None:
            ds = C.load(split, flow=flow, census=census, _internal=(split == "val"))
        if not debug:
            C.check_sol_coverage(ds)
        doc: dict[str, Any] = {"hypothesis": HYP, "version": VERSION, "stage": stage, "split": split,
                               "utc": C.utc_str(time.time()), "provisional": provisional, "debug_only": debug,
                               "prereg_sha256": info["prereg_sha256"], "rerun_reason": rerun_reason,
                               "coverage": cov, "n_coins": len(ds), "span_days": _span_days(ds),
                               "m1_host": {"version": M1.VERSION, "params_hash": C.params_hash(m1_host_params()),
                                           "code_sha256": m1_code_sha256()},
                               "m1_host_gate": info.get("m1_host_gate"), "common_sha256": common_sha256()}
        tr_doc = _read_json(out_dir / "train.json") if stage in ("val", "test", "confirm", "final") else None
        if tr_doc and tr_doc.get("common_sha256"):     # review Y5-3: engine changes are flagged, never silent
            doc["common_changed_since_train"] = tr_doc["common_sha256"] != doc["common_sha256"]
        if debug:
            doc["event_counts"] = event_counts(ds)
        clusters = M1.clusters_for(ds) if any(p["host"] == "M1" for _, p in configs) else None
        results: dict[str, C.Result] = {}
        for role, p in configs:
            ps = placebo_spec(p["host"])
            results[role] = C.backtest(strategy, split, p, hypothesis=HYP, ds=ds, cfg=FILL, placebo=True,
                                       n_placebo=n_placebo, placebo_eligible=ps["eligible"], placebo_strata=ps["strata"],
                                       placebo_controls=ps["controls"], stress=STRESS, declarations=DECL,
                                       ledger_path=ledger_path, shortlist_path=shortlist_path)
        n_tr = C.n_trials(ledger_path)
        host_t = {}
        for role, p in configs:
            if not is_candidate(p):
                host_t[p["host"]] = with_calendar(results[role].trades)
        evals = {role: evaluate(r, host_t.get(r.meta["params"]["host"]), clusters, B=B, hide=debug,
                                n_trials_total=n_tr) for role, r in results.items()}
        doc["configs"] = evals
        doc["n_trials_total"] = n_tr
        if not debug:
            _write_trades(out_dir, stage, provisional, results)
        if debug:
            days = doc["span_days"]
            expo = doc["event_counts"]["session_exposure_h"]
            doc["entries_per_day"] = {k: (e["n"] / days if math.isfinite(days) and days > 0 else None)
                                      for k, e in evals.items()}
            doc["entries_per_session_day"] = {k: per_session_day(e["by_session_n"], expo) for k, e in evals.items()}
            doc["decision"] = {"verdict": "DEBUG", "note": "mechanics and counts only; returns hidden"}
        elif stage == "train":
            dec = decide_train(evals)
            dec["shortlist_written"] = False
            if dec["verdict"] == "SHORTLISTED" and not provisional:
                C.write_shortlist(HYP, dec["shortlist"], path=shortlist_path, ledger_path=ledger_path,
                                  note=f"{VERSION}: PREREG 8 pair rule, candidate {dec['candidate']}")
                dec["shortlist_written"] = True
            doc["decision"] = dec
            doc["predictions"] = score_predictions(evals)
            doc["x5_overlap"] = x5_overlap_counts()
            doc["veto_by_product"] = {h: {s: veto_report(t, [s]) for s in SESSIONS} for h, t in host_t.items()}
        elif stage == "val":
            doc["decision"] = decide_val(evals["candidate"])
            cand = configs[0][1]
            avoid = [s for s in SESSIONS if s not in cand["sessions"]]
            doc["veto_by_product"] = veto_report(host_t[cand["host"]], avoid)
        elif stage in ("test", "confirm"):
            val_t = _read_trades(out_dir, "val", "candidate")
            val_res = C.Result(trades=val_t, placebo=C._frame([]), stress={}, meta={}) if val_t is not None else None
            base = C.verdict_entry(results["candidate"], val=val_res, min_mean=PASS_MIN_MEAN, B=B)
            extras = y5_extras(evals["candidate"])
            doc["verdict"] = {"verdict": combine_verdict(base, extras), "base": base, "y5_extras": extras}
            doc["decision"] = doc["verdict"]
            cand = configs[0][1]
            avoid = [s for s in SESSIONS if s not in cand["sessions"]]
            val_h = _read_trades(out_dir, "val", "host")
            if stage == "test" and val_h is not None and len(val_h):
                doc["veto_by_product"] = veto_report(with_calendar(val_h), avoid, oos=host_t[cand["host"]])
            else:
                doc["veto_by_product"] = veto_report(host_t[cand["host"]], avoid)
        elif stage == "final":
            doc["decision"] = final_decision(results["candidate"].trades)
        return _finish(doc, out_dir, stage, provisional, t0, ledger_path)

    session = (C.one_shot_session(HYP, split, ledger_path, note=f"y5 --stage {stage}")
               if split in C.ONE_RUN_SPLITS else contextlib.nullcontext())
    try:
        with session:           # TEST / CONFIRM / FINAL: the family's ONE look (candidate + host inside it)
            return _execute(ds)
    except C.SplitLocked as e:
        raise Y5Refused(str(e)) from e


def _trades_path(out_dir: Path, stage: str, provisional: bool) -> Path:
    return out_dir / f"{stage}{'_prelim' if provisional else ''}_trades.csv"


def _write_trades(out_dir: Path, stage: str, provisional: bool, results: Mapping[str, C.Result]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = [with_calendar(r.trades).assign(role=role, config=config_key(r.meta["params"]))
              for role, r in results.items()]
    pd.concat(frames, ignore_index=True).to_csv(_trades_path(out_dir, stage, provisional), index=False)


def _read_trades(out_dir: Path, stage: str, role: str | None) -> pd.DataFrame | None:
    p = _trades_path(out_dir, stage, False)
    if role is None or not p.exists():
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
    """The hypothesis-level status from every stage written so far (``pending`` = the stage being written)."""
    def doc(s):
        if pending is not None and pending.get("stage") == s and not pending.get("provisional"):
            return pending
        return _read_json(Path(out_dir) / f"{s}.json")

    tr = doc("train")
    if not tr or tr.get("provisional"):
        return "PENDING (no official TRAIN run)"
    tv = (tr.get("decision") or {}).get("verdict")
    if tv == "UNDERPOWERED_TRAIN":
        return "UNDERPOWERED (TRAIN)"
    if tv == "NO_CONFIG":
        return "NO EDGE (nothing qualified on TRAIN)"
    va = doc("val")
    if not va:
        return "PENDING VAL"
    vv = (va.get("decision") or {}).get("verdict")
    if vv == "FAIL_VAL":
        return "NO EDGE (failed VAL; PLAN 8 rule 7 input)"
    if vv == "UNDERPOWERED_VAL":
        return "UNDERPOWERED (VAL)"
    te = doc("test")
    if not te:
        return "PENDING TEST"
    ok, why = confirm_allowed(te)
    if not ok:
        return f"NO EDGE ({why})"
    co = doc("confirm")
    if not co:
        return "PENDING CONFIRM"
    cv = (co.get("verdict") or {}).get("verdict")
    if cv == "UNDERPOWERED":
        return "UNDERPOWERED (CONFIRM)"
    if cv != "PASS":
        return f"NO EDGE (CONFIRM {cv})"
    fi = doc("final")
    if not fi:
        return "PENDING FINAL"
    return "EDGE" if (fi.get("decision") or {}).get("mean_positive") else "NO EDGE (FINAL mean <= 0)"


# =========================================================================== markdown


def _pct(x: Any, nd: int = 1) -> str:
    return "n/a" if x is None else f"{100 * float(x):+.{nd}f}%"


def _ci(ci: Any) -> str:
    return "n/a" if not ci else f"[{100 * ci[0]:+.1f}, {100 * ci[1]:+.1f}]"


def _num(x: Any, nd: int = 1) -> str:
    return "n/a" if x is None else f"{float(x):.{nd}f}"


def render_md(doc: Mapping[str, Any]) -> str:
    st = doc["stage"]
    L = [f"# Y5 {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}", "",
         f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days.",
         f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
         f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}; M1 host "
         f"{(doc.get('m1_host') or {}).get('version')} `{(doc.get('m1_host') or {}).get('params_hash')}`, m1.py "
         f"`{((doc.get('m1_host') or {}).get('code_sha256') or '')[:12]}`; common.py "
         f"`{(doc.get('common_sha256') or '')[:12]}`.",
         f"- **Overall Y5 status:** {doc.get('overall')}.", ""]
    if doc.get("common_changed_since_train"):
        L.insert(-2, "- **Warning: common.py changed since TRAIN** (the engine every host runs on; flagged, not refused: "
                     "PREREG 3.2). Read this stage against the TRAIN selection with that in mind.")
    if doc.get("m1_host_gate"):
        L.insert(-2, f"- **M1-host pair gate** (PREREG 3.2): {doc['m1_host_gate']}.")
    if doc.get("debug_only"):
        L += ["**Debug run on the census TRAIN third: mechanics and counts only. Returns are hidden and no parameter "
              "was chosen here.**", ""]
    ec = doc.get("event_counts")
    if ec:
        L += ["## Event counts (no outcomes)", "",
              f"- Coins {ec['coins']}; creation window shifted to g + 30 min: {ec.get('creation_window_plus_30min_utc')}"
              f"; session exposure hours {ec.get('session_exposure_h')}.",
              f"- R30 decisions (g + 30 min) by session {ec['r30_decisions_by_session']}; alive (= R30 entries) "
              f"{ec['r30_alive_by_session']}; by day type {ec['r30_decisions_by_day_type']}.",
              f"- R30 decisions by UTC hour: {ec['r30_decisions_by_hour']}.", ""]
    cf = doc.get("configs") or {}
    if cf:
        L += ["## Configs", ""]
        if doc.get("debug_only"):
            L += ["| config | trades | coins | by session | by day type | placebo | controls | horizon exits | "
                  "entries/day | entries per session-day |", "|---|---:|---:|---|---|---:|---|---:|---:|---|"]
            for k, e in cf.items():
                epd = (doc.get("entries_per_day") or {}).get(k)
                eps = (doc.get("entries_per_session_day") or {}).get(k) or {}
                L.append(f"| {e['config']} | {e['n']} | {e['n_coins']} | {e['by_session_n']} | {e['by_day_type_n']} | "
                         f"{e['n_placebo']} | {e['n_controls']} | {e['horizon_exits']} | "
                         f"{'n/a' if epd is None else f'{epd:.1f}'} | "
                         f"{ {s: (None if v is None else round(v, 1)) for s, v in eps.items()} } |")
        else:
            L += ["| role | config | n | coins | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | placebo diff | "
                  "host-rel diff [95% CI] | costs ×1.5 | open fills | gross move | cost | censored |",
                  "|---|---|---:|---:|---:|---|---|---:|---:|---|---:|---:|---:|---:|---:|"]
            for k, e in cf.items():
                cd = e.get("cost_decomposition") or {}
                hr = e.get("host_rel") or {}
                L.append(f"| {k} | {e['config']} | {e['n']} | {e['n_coins']} | {_pct(e.get('mean'))} | "
                         f"{_ci(e.get('ci90'))} | {_ci(e.get('ci90_block'))} | {_pct(e.get('mean_without_top2'))} | "
                         f"{_pct((e.get('placebo') or {}).get('mean_diff'))} | "
                         f"{_pct(hr.get('diff'))} {_ci(hr.get('diff_ci95'))} | "
                         f"{_pct((e.get('stress') or {}).get('costs_x1.5'))} | "
                         f"{_pct((e.get('stress') or {}).get('open_fills'))} | "
                         f"{_pct(cd.get('mean_gross_move_worst_fills'))} | {_pct(cd.get('mean_cost'))} | "
                         f"{_pct(e.get('censored_share'), 0)} |")
            L += ["", "### By session and day type (mean | placebo diff | n)", ""]
            for k, e in cf.items():
                bs = e.get("by_session") or {}
                bd = e.get("by_day_type") or {}
                cells = [f"{g}: {_pct(v.get('mean'))} | {_pct(v.get('placebo_diff'))} | {v.get('n')}"
                         for g, v in list(bs.items()) + list(bd.items()) if v.get("n")]
                L.append(f"- {e['config']}: " + "; ".join(cells))
        L.append("")
    pr = doc.get("predictions")
    if pr:
        L += ["## Pre-registered predictions (PREREG 12; reports, never decisive)", ""]
        for key in ("P1_no_candidate_mean_net_above_0", "P2_r30_session_premium_within_6pts",
                    "P3_no_stable_sign_across_sessions_and_day_types"):
            L.append(f"- {key}: held = {pr[key]['held']}.")
        L.append("")
    xo = doc.get("x5_overlap")
    if xo:
        L += ["## Overlap with X5 (PREREG 3.4; counts only, never decisive)", ""]
        if not xo.get("available"):
            L.append(f"- {xo.get('note')}.")
        else:
            L.append(f"- X5's M1-host TRAIN trades (the same pinned host): {xo['n_host_trades']}. By X5 state (q = 0.5) "
                     "and Y5 session of the decision:")
            for col, tab in xo["by_state_and_session"].items():
                L.append(f"  - {col}: {tab}")
        L += ["- A Y5 M1-host result and an X5 M1-host result are not independent evidence of a timing effect.", ""]
    vb = doc.get("veto_by_product")
    if vb:
        L += ["## Veto by-product (PLAN 3.5 veto bar; reported, never decisive for EDGE)", ""]
        items = vb.items() if "verdict" not in vb else [("candidate host", {"avoided": vb})]
        for h, per in items:
            for v in per.values():
                L.append(f"- {h} / flagged {v.get('flagged_sessions')}: {v.get('verdict')} (flagged {v.get('n_flagged')}"
                         f", unflagged {v.get('n_unflagged')}).")
        L.append("")
    dec = doc.get("decision") or {}
    L += ["## Decision", "", f"- **{dec.get('verdict')}**."]
    for r in dec.get("rows") or []:
        L.append(f"- {r['config']}: n {r['n']}, coins {r['coins']}, mean {_pct(r['mean'])}, 90% CI low "
                 f"{_pct(r['ci90_lo'])}, placebo diff {_pct(r['placebo_diff'])}, host-rel diff "
                 f"{_pct(r['host_rel_diff'])}, day types {r['day_type_ok']}, qualifies {r['qualifies']}.")
    if "shortlist_written" in dec:
        L.append(f"- Shortlist written: {dec['shortlist_written']} (candidate {dec.get('candidate')}; ranked "
                 f"{dec.get('ranked')}).")
    if dec.get("base"):
        for c in dec["base"]["criteria"]:
            L.append(f"- PLAN 3.5 #{c['id']} {c['name']}: {c['pass']} (value {c['value']}, need {c['need']}).")
        for c in dec.get("y5_extras", []):
            L.append(f"- {c['id']} {c['name']}: {c['pass']} (value {c['value']}).")
        if dec["base"].get("auto_rejections"):
            L.append(f"- Auto-rejections: {dec['base']['auto_rejections']}.")
        L.append("- PLAN 3.5 #9 (FINAL mean > 0) is judged in the overall verdict after the FINAL stage.")
    if dec.get("host_rel_diff") is not None or "proceed" in dec:
        L.append(f"- VAL candidate: n {dec.get('n')}, mean {_pct(dec.get('mean'))}, host-relative diff "
                 f"{_pct(dec.get('host_rel_diff'))}.")
    if dec.get("reason"):
        L.append(f"- Reason: {dec['reason']}.")
    if dec.get("note"):
        L.append(f"- {dec['note']}")
    if dec.get("per_third"):
        L.append(f"- FINAL per census third: {dec['per_third']}.")
    L.append("")
    return "\n".join(L)


# =========================================================================== CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Y5 calendar gate: pre-registered stages; see research/lab2/Y5/PREREG.md")
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
    except Y5Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(f"wrote {OUT_DIR / (name + '.json')} and .md; decision: {(doc.get('decision') or {}).get('verdict')}; "
          f"overall: {doc.get('overall')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
