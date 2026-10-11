"""O1: operator-backed graduates. Buy, late and only, the coins whose first two post-migration minutes were bought
by an OPERATOR (G1's class: >= 500 SOL of non-agent buying from <= 30 buyers), at a fixed or random age after
graduation; learn whether operator support beats the market's ~-20 % per-trade drift for an outside buyer.

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/O1/PREREG.md``.

PROVENANCE (PREREG 1). This hypothesis was written AFTER G1's TRAIN and VAL reports showed the R0 random-entry host's
mean by G1 class (OPERATOR: TRAIN -3.0 % [-6.5, +0.4] n 233; VAL +23.3 % [-10.1, +84.7] n 79). O1's TRAIN and VAL
are therefore NOT clean searches: they only pick <= 2 of 6 pre-registered configs. The first unseen looks are TEST
and CONFIRM; FINAL is judged on the census VAL / TEST thirds only. A TEST pass alone never puts real money in.

Every FEATURE is read through :class:`common.AsOf` (cutoff tau = t - 20 s; completed minute bars only; NULL stays
None). The class is :func:`g1.classify` on :func:`g1.g1_features` (registry-free: OPERATOR needs only the first-120-s
pool window, legal from g + 120 s). Data: graduates + b2_coins + b2_bars only.

CLI::

    python research/lab2/o1.py --debug                         # census TRAIN third: counts only, no returns
    python research/lab2/o1.py --stage train [--allow-partial] [--rerun-reason TEXT]
    python research/lab2/o1.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/o1.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/o1.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/o1.py --stage final
    python research/lab2/o1.py --stage val --check             # prerequisites only

Each stage writes ``O1/<stage>.json`` and ``O1/<stage>.md`` and REFUSES to run when its prerequisites are missing.
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
from typing import Any, Mapping

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import common as C  # noqa: E402
import g1 as G  # noqa: E402  (class rules only: g1_features + classify, registry-free)

VERSION = "o1-v1"
OUT_DIR = HERE / "O1"
HYP = "O1"
STAGES = ("train", "val", "test", "confirm", "final")
STAGE_SPLIT = {
    "debug": "final_train",
    "train": "train",
    "val": "val",
    "test": "test",
    "confirm": "confirm",
    "final": "final",
}
STAGE_ENV = {"test": "LAB2_ALLOW_TEST", "confirm": "LAB2_ALLOW_CONFIRM", "final": "LAB2_ALLOW_FINAL"}

# =========================================================================== pre-registered constants (PREREG 2-7)
CLASS = "OPERATOR"  # G1 class at the decision (g1.classify; thresholds are G1's, not re-tuned)
ALIVE_VOL_USD_15M = 1500.0  # PLAN R0 alive rule (same as G1's R0 host)
ALIVE_MCAP_USD = 6000.0
AGE_LO_MIN, AGE_HI_MIN = 30.0, 115.0  # the R0 random-age window (seed 0 = G1's R0 draws)
R0_SEED = 0
EXIT_BY_AGE_S = 178 * 60.0  # registered deadline: sell by g + 178 min (inside the B2 window)
INSTANT_MAX_DELAY_S = 5.0  # report tag only: instant vs slow graduate
SIZE_USD = 20.0
TIMING_GRID = ("t30", "t60", "r0")  # fixed age 30 min | fixed age 60 min | R0 random age in [30, 115] min
EXIT_GRID = ("r0exit", "tight")  # stop 50 % + 60 min (PLAN R0 exit) | stop 35 % + 30 min
EXITS = {"r0exit": {"stop_pct": 0.50, "max_hold_s": 3600.0}, "tight": {"stop_pct": 0.35, "max_hold_s": 1800.0}}
PRIMARY = {"timing": "r0", "exit": "r0exit"}  # the config that re-reads G1's seen class cell (PREREG 1)
# selection and verdict bars
TRAIN_MIN_TRADES = 30
DIRECTION_MIN_N = 30
VAL_MIN_SIGN, VAL_MIN_TRADES = 5, 15
TEST_NO_EVIDENCE_N = 5
PASS_MIN_MEAN = 0.03  # PLAN 3.5 default
PROCEED_VAL = ("SELECTED", "SELECTED_UNDERPOWERED")

FILL = C.FillConfig(exit_delay_bars=1)  # worst fills, next-bar exits (PLAN 3.3, craft rule G22)
STRESS = {
    "costs_x1.5": FILL.stressed(1.5),
    "rent_0.22": dataclasses.replace(FILL, rent_usd=0.22),
    "same_bar_exits": C.FillConfig(),
    "no_entry_bar_exits": dataclasses.replace(FILL, entry_bar_exits=False),
}
DECL = {
    "uses_organic_flow": False,
    "uses_wallet_reputation": False,
    "uses_truncated_windows": False,
    "uses_current_state_fields": False,
}

FIXED = {
    "version": VERSION,
    "class": CLASS,
    "class_rule": "g1.classify(g1.g1_features(snap)) at the decision",
    "alive_vol_usd_15m": ALIVE_VOL_USD_15M,
    "alive_mcap_usd": ALIVE_MCAP_USD,
    "age_lo_min": AGE_LO_MIN,
    "age_hi_min": AGE_HI_MIN,
    "r0_seed": R0_SEED,
    "exit_by_age_s": EXIT_BY_AGE_S,
    "size_usd": SIZE_USD,
    "placebo": "judged control: same timing on ANY alive coin (class unmatched); diagnostic: class-matched",
    "fill": "common.FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar exits, next-bar exits",
}


def make_params(timing: str, exit_set: str) -> dict:
    if timing not in TIMING_GRID:
        raise ValueError(f"timing {timing!r} not in {TIMING_GRID}")
    if exit_set not in EXIT_GRID:
        raise ValueError(f"exit set {exit_set!r} not in {EXIT_GRID}")
    return {**FIXED, "timing": timing, "exit": exit_set, **EXITS[exit_set]}


GRID = [make_params(t, e) for t in TIMING_GRID for e in EXIT_GRID]
PRIMARY_PARAMS = make_params(PRIMARY["timing"], PRIMARY["exit"])


class O1Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing."""


def config_key(p: Mapping[str, Any]) -> str:
    return f"{p['timing']}|{p['exit']}"


# =========================================================================== class gate and timing (AsOf only)


def coin_class(snap: C.AsOf) -> str:
    """G1's class at ``snap.tau`` from as-of features only (no registry: serial / repeat fields stay None, which
    cannot make or unmake OPERATOR)."""
    return G.classify(G.g1_features(snap, None))["g1_class"]


def target_age_s(mint: str, timing: str) -> float:
    if timing == "t30":
        return 30.0 * 60.0
    if timing == "t60":
        return 60.0 * 60.0
    return G.r0_target_age_s(mint, {"seed": R0_SEED, "age_lo_min": AGE_LO_MIN, "age_hi_min": AGE_HI_MIN})


def speed_of(snap: C.AsOf) -> str:
    """instant (grad_delay_s <= 5 s) | slow; NULL delay uses the lower bound; else unknown. Report tag only."""
    d = snap.get("grad_delay_s")
    if d is None:
        d = snap.get("grad_delay_lb_s")
    if d is None:
        return "unknown"
    return "instant" if float(d) <= INSTANT_MAX_DELAY_S else "slow"


def alive(snap: C.AsOf) -> bool:
    return bool(snap.alive(ALIVE_VOL_USD_15M, ALIVE_MCAP_USD))


# =========================================================================== strategy


def strategy(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
    """O1 for common.backtest: at the first decision at or after the target age, enter if the coin is alive AND
    its G1 class is OPERATOR; else never (one decision per coin, like PLAN R0)."""
    if pos is not None:
        return None
    if snap.age_s < target_age_s(snap.mint, p["timing"]):
        return None
    if not alive(snap):
        return C.SKIP
    if coin_class(snap) != CLASS:
        return C.SKIP
    return C.Enter(
        exits=C.ExitSpec(stop_pct=float(p["stop_pct"]), max_hold_s=float(p["max_hold_s"]), exit_by_age_s=EXIT_BY_AGE_S),
        tag=speed_of(snap),
        state={"class": CLASS},
    )


def placebo_ok(snap: C.AsOf) -> bool:
    """Judged control universe: ANY alive coin at the matched age (class unmatched: the test is the class)."""
    return alive(snap)


def placebo_class_ok(snap: C.AsOf) -> bool:
    """Diagnostic control: alive AND OPERATOR (isolates timing; should sit near the strategy itself)."""
    return alive(snap) and coin_class(snap) == CLASS


PLACEBO_CONTROLS = {"class_matched": {"eligible": placebo_class_ok, "strata": None}}


# =========================================================================== evaluation


def direction(ev: Mapping[str, Any]) -> str:
    """PREREG 8: BEATS_RANDOM / WORSE_THAN_RANDOM / NEITHER from the judged (class-unmatched) control's diff 95 % CI."""
    if ev.get("n", 0) < DIRECTION_MIN_N:
        return "UNDERPOWERED"
    ci = (ev.get("placebo") or {}).get("diff_ci95")
    if not ci:
        return "NEITHER"
    if ci[0] > 0:
        return "BEATS_RANDOM"
    if ci[1] < 0:
        return "WORSE_THAN_RANDOM"
    return "NEITHER"


def evaluate(res: C.Result, *, B: int, hide: bool, n_trials_total: int | None) -> dict:
    """Per-config report. On the debug split: counts only (n, coins, strata, placebo n, horizon exits)."""
    t = res.trades
    cens = (t["reason"] == "horizon").to_numpy(bool) if len(t) else np.zeros(0, bool)
    base = {
        "config": config_key(res.meta["params"]),
        "params_hash": C.params_hash(res.meta["params"]),
        "hypothesis": res.meta["hypothesis"],
        "n": int(len(t)),
        "n_coins": int(t["mint"].nunique()) if len(t) else 0,
        "by_stratum_n": t["tag"].value_counts().to_dict() if len(t) else {},
        "n_placebo": int(len(res.placebo)),
        "horizon_exits": int(cens.sum()),
        "trial": {k: res.meta.get(k) for k in ("config", "new_trial", "n_trials_total")},
    }
    if hide:
        base["returns"] = "hidden on the debug split (never choose parameters on FINAL data)"
        return base
    base["reasons"] = t["reason"].value_counts().to_dict() if len(t) else {}
    d = C.describe(t, B=B, n_trials_total=n_trials_total)
    base.update(
        {
            k: d.get(k)
            for k in (
                "mean",
                "median",
                "win_rate",
                "sd",
                "ci90",
                "ci95",
                "ci90_block",
                "ci95_block",
                "n_blocks",
                "censored_share",
                "top_coin_share",
                "top3_coin_share",
                "mean_without_top2",
                "halves",
                "mean_hold_min",
                "deflated_sharpe",
            )
        }
    )
    base["placebo"] = C.placebo_compare(t, res.placebo, B=B) if len(res.placebo) and len(t) else None
    pu = res.controls.get("class_matched") if res.controls else None
    base["placebo_class_matched"] = C.placebo_compare(t, pu, B=B) if pu is not None and len(pu) and len(t) else None
    base["stress"] = {k: C.describe(v, B=200).get("mean") for k, v in res.stress.items()}
    base["portfolio"] = {k: v for k, v in C.portfolio_sim(t).items() if k != "skipped_mints"}
    base["by_stratum"] = (
        {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for s, g in t.groupby("tag")} if len(t) else {}
    )
    base["direction"] = direction(base)
    return base


def combine_verdict(base: Mapping[str, Any]) -> str:
    """PLAN 3.5 items 1-8 + 10 from common.verdict_entry. Item 9 (FINAL mean > 0) is judged in the overall verdict
    once FINAL ran, so a missing FINAL never makes TEST / CONFIRM 'INCOMPLETE'."""
    if base.get("auto_rejections"):
        return "REJECTED"
    crit = {c["id"]: c["pass"] for c in base["criteria"] if c["id"] != 9}
    censored_ok = crit.pop(10, True)
    if not crit.get(1):
        return "UNDERPOWERED"
    rest = [v for k, v in crit.items() if k != 1]
    if any(v is False for v in rest):
        return "FAIL"
    if any(v is None for v in rest) or censored_ok is not True:
        return "INCOMPLETE"
    return "PASS"


# =========================================================================== pre-registered decisions


def _rank_key(r: Mapping[str, Any]) -> tuple:
    return (-r["ci90_lo"], -r["mean"], TIMING_GRID.index(r["timing"]), EXIT_GRID.index(r["exit"]))


def decide_train(evals: Mapping[str, Mapping[str, Any]]) -> dict:
    """PREREG 9 TRAIN: qualify (n >= 30, mean > 0, mean w/o top 2 > 0, judged-control diff > 0); rank by the coin
    90 % CI lower bound, then mean, then timing order t30 < t60 < r0, then r0exit before tight; shortlist = top 2."""
    rows = []
    for p in GRID:
        e = evals[config_key(p)]
        pc = (e.get("placebo") or {}).get("mean_diff")
        powered = e["n"] >= TRAIN_MIN_TRADES
        ci = e.get("ci90")
        good = (
            powered
            and e.get("mean") is not None
            and e["mean"] > 0
            and e.get("mean_without_top2") is not None
            and e["mean_without_top2"] > 0
            and pc is not None
            and pc > 0
            and ci is not None
        )
        rows.append(
            {
                "config": config_key(p),
                "timing": p["timing"],
                "exit": p["exit"],
                "powered": powered,
                "qualifies": bool(good),
                "n": e["n"],
                "mean": e.get("mean"),
                "ci90_lo": ci[0] if ci else None,
                "placebo_diff": pc,
                "direction": e.get("direction"),
            }
        )
    prim = evals.get(config_key(PRIMARY_PARAMS), {})
    out = {
        "rows": rows,
        "primary_direction": {"config": config_key(PRIMARY_PARAMS), "direction": prim.get("direction")},
    }
    q = sorted([r for r in rows if r["qualifies"]], key=_rank_key)
    if q:
        top = q[:2]
        sl = [make_params(r["timing"], r["exit"]) for r in top]
        return {
            **out,
            "verdict": "SHORTLISTED",
            "shortlist": sl,
            "shortlist_hashes": [C.params_hash(p) for p in sl],
            "shortlist_keys": [config_key(p) for p in sl],
        }
    if any(r["powered"] for r in rows):
        v, why = "NO_CONFIG", "a powered config failed the mean / top-2 / judged-control bars"
    else:
        v = "UNDERPOWERED_TRAIN"
        why = f"no config reached >= {TRAIN_MIN_TRADES} trades (best: {max(r['n'] for r in rows)})"
    return {**out, "verdict": v, "reason": why, "shortlist": [], "shortlist_hashes": [], "shortlist_keys": []}


def decide_val(evals: Mapping[str, Mapping[str, Any]], roles: list[str]) -> dict:
    """PREREG 9 VAL: candidate = the shortlisted config with the higher VAL mean (ties: TRAIN rank = role order);
    the decision is on the candidate only."""

    def m(r):
        v = evals[r].get("mean")
        return -math.inf if v is None else v

    cand = sorted(roles, key=lambda r: (-m(r), roles.index(r)))[0]
    twin = next((r for r in roles if r != cand), None)
    e = evals[cand]
    n, mean, mw2 = e["n"], e.get("mean"), e.get("mean_without_top2")
    if n < VAL_MIN_SIGN:
        v = "UNDERPOWERED_VAL"
    elif not (mean is not None and mean > 0 and (mw2 is None or mw2 > 0)):
        v = "FAIL_VAL"
    elif n < VAL_MIN_TRADES:
        v = "SELECTED_UNDERPOWERED"
    else:
        v = "SELECTED"
    return {
        "verdict": v,
        "candidate_role": cand,
        "twin_role": twin,
        "candidate_hash": e["params_hash"],
        "twin_hash": evals[twin]["params_hash"] if twin else None,
        "candidate_config": e["config"],
        "n": n,
        "mean": mean,
        "mean_without_top2": mw2,
        "proceed": v in PROCEED_VAL,
    }


def confirm_allowed(test_doc: Mapping[str, Any]) -> tuple[bool, str]:
    """PREREG 9: CONFIRM is spent when TEST is not REJECTED and (TEST mean > 0 or TEST n < 5 = no evidence)."""
    v = test_doc.get("verdict") or {}
    c = (test_doc.get("configs") or {}).get("candidate") or {}
    if v.get("verdict") == "REJECTED":
        return False, "TEST was REJECTED (PLAN 3.6)"
    n, mean = c.get("n", 0), c.get("mean")
    if n < TEST_NO_EVIDENCE_N or (mean is not None and mean > 0):
        return True, "ok"
    return False, f"TEST mean {mean} <= 0 on {n} trades: O1 failed TEST, CONFIRM not spent"


FINAL_JUDGED = ("final_val", "final_test")
FINAL_DEBUG = "final_train"


def final_decision(t: pd.DataFrame) -> dict:
    """PLAN 3.5 item 9 on the census thirds O1 never touched; the debug third is reported apart."""
    judged = t[t["split"].isin(FINAL_JUDGED)] if len(t) else t
    dbg = t[t["split"] == FINAL_DEBUG] if len(t) else t
    per = {s: {"n": int(len(g)), "mean": float(g["ret_net"].mean())} for s, g in t.groupby("split")} if len(t) else {}
    return {
        "verdict": "REPORTED",
        "judged_on": list(FINAL_JUDGED),
        "n": int(len(judged)),
        "mean": float(judged["ret_net"].mean()) if len(judged) else None,
        "mean_positive": None if not len(judged) else bool(judged["ret_net"].mean() > 0),
        "per_third": per,
        "debug_third": {
            "n": int(len(dbg)),
            "mean": float(dbg["ret_net"].mean()) if len(dbg) else None,
            "note": "census TRAIN third: hosted the debug run (PREREG 13), not judged",
        },
    }


# =========================================================================== stage prerequisites


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return None


def coverage_check(cov: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Every chain hour of the split scanned (curve AND B2), no mid-run hour, <= 5 % tradeable coins missing B2,
    SOL/USD covering the split."""
    if not cov.get("usable"):
        return False, ["no usable coins: the backfill has not reached this split yet"]
    notes = []
    if cov.get("chain_hours_scanned_frac", 0) < 0.999:
        notes.append(f"only {cov.get('chain_hours_scanned_frac', 0):.1%} of chain hours scanned")
    for d in cov.get("days", []):
        if d["curve_hours"] < d["hours_in_split"] or d["b2_hours"] < d["hours_in_split"]:
            notes.append(
                f"{d['day']}: curve {d['curve_hours']}/{d['hours_in_split']} h, "
                f"B2 {d['b2_hours']}/{d['hours_in_split']} h"
            )
    notes += C.coverage_problems(cov)
    return not notes, notes


def _runs(ledger_path: Path | None) -> list[dict]:
    with C._ledger(ledger_path, write=False) as led:
        return list(led.get("runs", []))


def _shortlist(shortlist_path: Path | None) -> dict | None:
    return _read_json(Path(shortlist_path or C.shortlist_dir()) / f"{HYP}.json")


def stage_configs(stage: str, out_dir: Path, shortlist_path: Path | None = None) -> list[tuple[str, dict]]:
    """[(role, params)] the stage runs. VAL: the shortlist in TRAIN rank order (roles sl1, sl2). TEST / CONFIRM /
    FINAL: the VAL candidate and its twin."""
    if stage in ("debug", "train"):
        return [(config_key(p), p) for p in GRID]
    sl = _shortlist(shortlist_path)
    if not sl:
        return []
    cfgs = list(sl.get("configs") or [])
    if stage == "val":
        return [(f"sl{i + 1}", c) for i, c in enumerate(cfgs)]
    dec = (_read_json(Path(out_dir) / "val.json") or {}).get("decision") or {}
    by_hash = {C.params_hash(c): c for c in cfgs}
    out = [("candidate", by_hash.get(dec.get("candidate_hash")))]
    if dec.get("twin_hash"):
        out.append(("twin", by_hash.get(dec["twin_hash"])))
    return out


def check_prereqs(
    stage: str,
    out_dir: Path = OUT_DIR,
    *,
    flow: Path | None = None,
    ledger_path: Path | None = None,
    shortlist_path: Path | None = None,
    env: Mapping[str, str] | None = None,
    rerun_reason: str | None = None,
) -> dict:
    """Raise :class:`O1Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise O1Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise O1Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    # The first TRAIN run of ANY kind freezes PREREG.md: a provisional run shows TRAIN returns too. A train_prelim.json
    # without a lock (written before that rule) pins the sha it recorded.
    frozen = (lock or {}).get("sha256") or (_read_json(out_dir / "train_prelim.json") or {}).get("prereg_sha256")
    if frozen and frozen != _sha(prereg):
        raise O1Refused(
            "PREREG.md changed after the first TRAIN run (provisional runs included); record changes in "
            "O1/AMENDMENTS.md as a new version instead"
        )
    ok, bad = C.validation_gates(STAGE_SPLIT[stage], flow)
    if not ok and stage != "debug":
        raise O1Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
    info = {
        "stage": stage,
        "prereg_sha256": _sha(prereg),
        "prereg_locked": bool(frozen),
        "data_gates": {"ok": ok, "problems": bad},
    }
    if stage == "debug":
        return info
    train = _read_json(out_dir / "train.json")
    if stage == "train":
        if train and not train.get("provisional") and not rerun_reason:
            raise O1Refused(
                "TRAIN already ran on complete data (O1/train.json); its decision is final. A re-run needs "
                "--rerun-reason naming the data correction that justifies it"
            )
        return info
    if not train:
        raise O1Refused("no TRAIN result (O1/train.json): run --stage train first")
    if train.get("provisional"):
        raise O1Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    tv = (train.get("decision") or {}).get("verdict")
    if tv != "SHORTLISTED":
        raise O1Refused(f"TRAIN decision {tv}: O1 stopped before VAL")
    sl = _shortlist(shortlist_path)
    if not sl:
        raise O1Refused("no VAL shortlist for O1 (written by a complete --stage train)")
    if sorted(sl.get("hashes", [])) != sorted(train["decision"].get("shortlist_hashes", [])):
        raise O1Refused("the O1 shortlist on disk differs from the one TRAIN wrote")
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise O1Refused("VAL already ran (O1/val.json exists): VAL is evaluated once")
        return info
    val = _read_json(out_dir / "val.json")
    if stage == "test":
        if not val:
            raise O1Refused("no VAL result (O1/val.json): TEST needs a VAL decision first")
        vv = (val.get("decision") or {}).get("verdict")
        if vv not in PROCEED_VAL:
            raise O1Refused(f"VAL decision {vv}: O1 stopped (PLAN 8 rule 7 input); TEST is not spent")
    test = _read_json(out_dir / "test.json")
    if stage in ("confirm", "final") and not test:
        raise O1Refused(f"never {stage.upper()} before TEST: run --stage test first")
    if stage == "confirm":
        ok2, why = confirm_allowed(test)
        if not ok2:
            raise O1Refused(why)
    if (out_dir / f"{stage}.json").exists():
        raise O1Refused(f"{stage.upper()} already ran (O1/{stage}.json exists): one run per hypothesis")
    grp = C.split_group(split)
    if any(
        C.hypothesis_family(r.get("hypothesis", "")) == HYP
        and C.split_group(r.get("split", "")) == grp
        and not r.get("debug")
        for r in _runs(ledger_path)
    ):
        raise O1Refused(f"{HYP} already had its one {grp} run (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise O1Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
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


def event_counts(ds: C.Dataset) -> dict:
    """Counts only (no prices, no returns): G1 classes at g + 140 s, and per timing how many coins are alive and
    OPERATOR at the decision (= would be entered)."""
    out: dict[str, Any] = {"coins": len(ds), "class_at_140s": {}, "per_timing": {}}
    alive_n = {t: 0 for t in TIMING_GRID}
    enter_n = {t: 0 for t in TIMING_GRID}
    speed: dict[str, dict[str, int]] = {t: {} for t in TIMING_GRID}
    for m in ds.mints:
        cd = ds.coin(m)
        try:
            c140 = coin_class(ds.asof(m, cd.g + 140.0 + C.DECISION_LAG_S))
        except (C.NotYetKnown, C.ForbiddenFeature):
            c140 = "UNRESOLVED"
        out["class_at_140s"][c140] = out["class_at_140s"].get(c140, 0) + 1
        for t in TIMING_GRID:
            age = target_age_s(m, t)
            t_dec = cd.g + age + C.DECISION_LAG_S
            if t_dec > cd.m0 + 60 * C.N_BARS:
                continue
            snap = ds.asof(m, t_dec)
            if not alive(snap):
                continue
            alive_n[t] += 1
            if coin_class(snap) == CLASS:
                enter_n[t] += 1
                sp = speed_of(snap)
                speed[t][sp] = speed[t].get(sp, 0) + 1
    for t in TIMING_GRID:
        out["per_timing"][t] = {"alive_at_decision": alive_n[t], "alive_and_operator": enter_n[t], "speed": speed[t]}
    return out


def run_stage(
    stage: str,
    *,
    out_dir: Path = OUT_DIR,
    allow_partial: bool = False,
    rerun_reason: str | None = None,
    ds: C.Dataset | None = None,
    census: C.Census | None = None,
    flow: Path | None = None,
    ledger_path: Path | None = None,
    shortlist_path: Path | None = None,
    B: int = 10_000,
    n_placebo: int = 20,
    env: Mapping[str, str] | None = None,
    _skip_coverage: bool = False,
) -> dict:
    """Run one stage end to end and write O1/<stage>.json + .md (``ds`` injection is for tests)."""
    t0 = time.time()
    out_dir = Path(out_dir)
    debug = stage == "debug"
    split = STAGE_SPLIT[stage]
    info = check_prereqs(
        stage,
        out_dir,
        flow=flow,
        ledger_path=ledger_path,
        shortlist_path=shortlist_path,
        env=env,
        rerun_reason=rerun_reason,
    )
    if debug and ledger_path is None:
        ledger_path = C._SCRATCH / "lab2_debug" / "o1_debug_trials.json"  # debug never reaches the real ledger
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    provisional = False
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise O1Refused(
                    f"{split} data incomplete: "
                    + "; ".join(notes[:6])
                    + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else "")
                )
    covs = list(cov.values()) if (split == "final" and "split" not in cov) else [cov]
    hard = [] if debug else [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
    if hard:
        raise O1Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_configs(stage, out_dir, shortlist_path)
    if not configs or any(p is None for _, p in configs):
        raise O1Refused("no configs to run (shortlist or VAL decision missing or malformed)")

    def _execute(ds: C.Dataset | None) -> dict:
        if not debug:  # commit: every config is allowed BEFORE any data is read
            try:
                for _, p in configs:
                    C._check_run_allowed(HYP, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise O1Refused(str(e)) from e
        if stage == "train":
            out_dir.mkdir(parents=True, exist_ok=True)
            if not (out_dir / "prereg.lock").exists():  # the first TRAIN run, provisional or not, locks PREREG
                (out_dir / "prereg.lock").write_text(
                    json.dumps(
                        {
                            "sha256": info["prereg_sha256"],
                            "locked_utc": C.utc_str(time.time()),
                            "locked_by": "provisional TRAIN" if provisional else "TRAIN",
                        },
                        indent=1,
                    )
                )
            if not provisional and rerun_reason and (out_dir / "train.json").exists():
                stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
                for ext in ("json", "md"):
                    p = out_dir / f"train.{ext}"
                    if p.exists():
                        p.rename(out_dir / f"train_prev_{stamp}.{ext}")
        if ds is None:
            ds = C.load(split, flow=flow, census=census, _internal=(split == "val"))
        if not debug:
            C.check_sol_coverage(ds)
        doc: dict[str, Any] = {
            "hypothesis": HYP,
            "version": VERSION,
            "stage": stage,
            "split": split,
            "utc": C.utc_str(time.time()),
            "provisional": provisional,
            "debug_only": debug,
            "prereg_sha256": info["prereg_sha256"],
            "rerun_reason": rerun_reason,
            "coverage": cov,
            "n_coins": len(ds),
            "span_days": _span_days(ds),
        }
        if debug:
            doc["event_counts"] = event_counts(ds)
        results: dict[str, C.Result] = {}
        for role, p in configs:
            results[role] = C.backtest(
                strategy,
                split,
                p,
                hypothesis=HYP,
                ds=ds,
                cfg=FILL,
                placebo=True,
                n_placebo=n_placebo,
                placebo_eligible=placebo_ok,
                placebo_strata=None,
                placebo_controls=PLACEBO_CONTROLS,
                stress=STRESS,
                declarations=DECL,
                ledger_path=ledger_path,
                shortlist_path=shortlist_path,
            )
        n_tr = C.n_trials(ledger_path)
        evals = {role: evaluate(r, B=B, hide=debug, n_trials_total=n_tr) for role, r in results.items()}
        doc["configs"] = evals
        if not debug:
            _write_trades(out_dir, stage, provisional, results)
        if debug:
            days = doc["span_days"]
            doc["entries_per_day"] = {
                k: (e["n"] / days if days == days and days > 0 else None) for k, e in evals.items()
            }
            doc["decision"] = {"verdict": "DEBUG", "note": "mechanics and counts only; returns hidden"}
        elif stage == "train":
            dec = decide_train(evals)
            dec["shortlist_written"] = False
            if dec["verdict"] == "SHORTLISTED" and not provisional:
                C.write_shortlist(
                    HYP,
                    dec["shortlist"],
                    path=shortlist_path,
                    ledger_path=ledger_path,
                    note=f"{VERSION}: PREREG 9 top-2 rule: {dec['shortlist_keys']}",
                )
                dec["shortlist_written"] = True
            doc["decision"] = dec
        elif stage == "val":
            doc["decision"] = decide_val(evals, [r for r, _ in configs])
        elif stage in ("test", "confirm"):
            val_dec = (_read_json(out_dir / "val.json") or {}).get("decision") or {}
            val_t = _read_trades(out_dir, "val", val_dec.get("candidate_role"))
            val_res = C.Result(trades=val_t, placebo=C._frame([]), stress={}, meta={}) if val_t is not None else None
            base = C.verdict_entry(results["candidate"], val=val_res, min_mean=PASS_MIN_MEAN, B=B)
            doc["verdict"] = {"verdict": combine_verdict(base), "base": base}
            doc["decision"] = doc["verdict"]
        elif stage == "final":
            doc["decision"] = final_decision(results["candidate"].trades)
        return _finish(doc, out_dir, stage, provisional, t0, ledger_path)

    session = (
        C.one_shot_session(HYP, split, ledger_path, note=f"o1 --stage {stage}")
        if split in C.ONE_RUN_SPLITS
        else contextlib.nullcontext()
    )
    try:
        with session:
            return _execute(ds)
    except C.SplitLocked as e:
        raise O1Refused(str(e)) from e


def _trades_path(out_dir: Path, stage: str, provisional: bool) -> Path:
    return out_dir / f"{stage}{'_prelim' if provisional else ''}_trades.csv"


def _write_trades(out_dir: Path, stage: str, provisional: bool, results: Mapping[str, C.Result]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = [
        r.trades.assign(role=role, config=config_key(r.meta["params"]), params_hash=C.params_hash(r.meta["params"]))
        for role, r in results.items()
    ]
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


def render_md(doc: Mapping[str, Any]) -> str:
    st = doc["stage"]
    L = [
        f"# O1 {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}",
        "",
        f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days.",
        f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
        f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}.",
        f"- **Overall O1 status:** {doc.get('overall')}.",
        "",
    ]
    if doc.get("debug_only"):
        L += [
            "**Debug run on the census TRAIN third: mechanics and counts only. Returns, exit reasons and placebo "
            "outcomes are hidden, and no parameter was chosen here.**",
            "",
        ]
    ec = doc.get("event_counts")
    if ec:
        L += [
            "## Event counts (no returns)",
            "",
            f"- Coins: {ec['coins']}; G1 class at g + 140 s: {ec['class_at_140s']}.",
            "",
        ]
        L += ["| timing | alive at the decision | alive and OPERATOR (entered) | speed |", "|---|---:|---:|---|"]
        for k, v in ec["per_timing"].items():
            L.append(f"| {k} | {v['alive_at_decision']} | {v['alive_and_operator']} | {v['speed']} |")
        L.append("")
    cf = doc.get("configs") or {}
    if cf:
        L += ["## Configs", ""]
        if doc.get("debug_only"):
            L += [
                "| config | trades | coins | strata | placebo trades | horizon exits | entries/day |",
                "|---|---:|---:|---|---:|---:|---:|",
            ]
            for k, e in cf.items():
                epd = (doc.get("entries_per_day") or {}).get(k)
                L.append(
                    f"| {e['config']} | {e['n']} | {e['n_coins']} | {e['by_stratum_n']} | {e['n_placebo']} | "
                    f"{e['horizon_exits']} | {'n/a' if epd is None else f'{epd:.1f}'} |"
                )
        else:
            L += [
                "| role | config | n | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | placebo diff (matched) | "
                "diff 95% CI | placebo diff (class-matched) | costs ×1.5 | direction |",
                "|---|---|---:|---:|---|---|---:|---:|---|---:|---:|---|",
            ]
            for k, e in cf.items():
                pl = e.get("placebo") or {}
                pu = (e.get("placebo_class_matched") or {}).get("mean_diff")
                L.append(
                    f"| {k} | {e['config']} | {e['n']} | {_pct(e.get('mean'))} | {_ci(e.get('ci90'))} | "
                    f"{_ci(e.get('ci90_block'))} | {_pct(e.get('mean_without_top2'))} | {_pct(pl.get('mean_diff'))} | "
                    f"{_ci(pl.get('diff_ci95'))} | {_pct(pu)} | {_pct((e.get('stress') or {}).get('costs_x1.5'))} | "
                    f"{e.get('direction')} |"
                )
        L.append("")
    dec = doc.get("decision") or {}
    L += ["## Decision", "", f"- **{dec.get('verdict')}**."]
    for r in dec.get("rows") or []:
        L.append(
            f"- {r['config']}: n {r['n']}, mean {_pct(r['mean'])}, 90% CI low {_pct(r['ci90_lo'])}, placebo diff "
            f"{_pct(r['placebo_diff'])}, direction {r['direction']}, qualifies {r['qualifies']}."
        )
    if dec.get("primary_direction"):
        L.append(f"- Primary direction reading (PREREG 8): {dec['primary_direction']}.")
    if "shortlist_written" in dec:
        L.append(f"- Shortlist written: {dec['shortlist_written']} {dec.get('shortlist_keys')}.")
    if dec.get("candidate_role"):
        L.append(
            f"- VAL candidate: {dec['candidate_role']} ({dec.get('candidate_config')}); twin {dec.get('twin_role')}."
        )
    if dec.get("base"):
        for c in dec["base"]["criteria"]:
            L.append(f"- PLAN 3.5 #{c['id']} {c['name']}: {c['pass']} (value {c['value']}, need {c['need']}).")
        if dec["base"].get("auto_rejections"):
            L.append(f"- Auto-rejections: {dec['base']['auto_rejections']}.")
        L.append("- PLAN 3.5 #9 (FINAL mean > 0) is judged in the overall verdict after the FINAL stage.")
    for key in ("reason", "note"):
        if dec.get(key):
            L.append(f"- {dec[key]}")
    if dec.get("per_third"):
        L.append(f"- FINAL per census third: {dec['per_third']}.")
    L.append("")
    return "\n".join(L)


# =========================================================================== CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="O1 operator-backed graduates: pre-registered stages; see research/lab2/O1/PREREG.md"
    )
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
        doc = run_stage(stage, allow_partial=a.allow_partial, rerun_reason=a.rerun_reason, B=a.B, n_placebo=a.n_placebo)
    except O1Refused as e:
        print(f"REFUSED ({stage}): {e}", file=sys.stderr)
        return 2
    name = stage + ("_prelim" if doc.get("provisional") else "")
    print(
        f"wrote {OUT_DIR / (name + '.json')} and .md; decision: {(doc.get('decision') or {}).get('verdict')}; "
        f"overall: {doc.get('overall')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
