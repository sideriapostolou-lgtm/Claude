"""K1: the Desk. A Claude panel reads an as-of brief about each alive coin at g + 30 min and decides buy / skip,
stop and holding time; the lab scores those decisions like any other strategy (worst fills, next-bar exits, costs,
matched random control, counted trials).

Research only (wave-2 lab). Nothing here is wired into the bot. Pre-registration: ``research/lab2/K1/PREREG.md``.
Core (brief, prompts, panel, cache, budget): ``research/lab2/desk_core.py``.

Why a back-test is legitimate: the models' knowledge ends before any lab coin existed; the brief holds only fields
legal at the decision time (:class:`common.AsOf`); no tools, web or memory; creator text is sanitized. Decisions are
cached per (prompt version, config, brief hash) under ``K1/decisions/``: a stage re-run makes no API call, and the
exam is reproducible (temperature 0). A stage REFUSES to run while any alive coin at its decision time has no cached
decision and no client is available (an incomplete exam is never scored).

Configs (PREREG 5, FIXED): ``solo-haiku``, ``solo-sonnet``, ``panel``. Grid = 3 counted trials.

CLI::

    python research/lab2/k1.py --debug --fake-client               # census TRAIN third: counts only, fake desk
    python research/lab2/k1.py --stage train                       # needs ANTHROPIC_API_KEY (budget PREREG 7)
    python research/lab2/k1.py --stage val
    LAB2_ALLOW_TEST=1 python research/lab2/k1.py --stage test
    LAB2_ALLOW_CONFIRM=1 python research/lab2/k1.py --stage confirm
    LAB2_ALLOW_FINAL=1 python research/lab2/k1.py --stage final
    python research/lab2/k1.py --stage val --check                 # prerequisites only
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
import desk_core as D  # noqa: E402

VERSION = "k1-v1"
OUT_DIR = HERE / "K1"
HYP = "K1"
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

# =========================================================================== pre-registered constants (PREREG 3-7)
DECISION_AGE_S = 1800.0  # one decision per coin: the first grid time at or after g + 30 min
ALIVE_VOL_USD_15M = 1500.0  # PLAN R0 alive rule; a dead coin is never briefed
ALIVE_MCAP_USD = 6000.0
EXIT_BY_AGE_S = 178 * 60.0  # registered deadline: sell by g + 178 min
SIZE_USD = 20.0  # v1: every buy is a $20 ticket (the desk's size_usd is recorded, not applied)
CONFIG_ORDER = ("panel", "solo-sonnet", "solo-haiku")  # tie-break order (most capable first), PREREG 5
BUDGET_USD = {"debug": 2.0, "train": 40.0, "val": 15.0, "test": 15.0, "confirm": 40.0, "final": 15.0}
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
    "uses_llm_decisions": True,
    "llm_prompt_version": D.PROMPT_VERSION,
}

FIXED = {
    "version": VERSION,
    "prompt_version": D.PROMPT_VERSION,
    "decision_age_s": DECISION_AGE_S,
    "alive_vol_usd_15m": ALIVE_VOL_USD_15M,
    "alive_mcap_usd": ALIVE_MCAP_USD,
    "exit_by_age_s": EXIT_BY_AGE_S,
    "size_usd": SIZE_USD,
    "exits": "the desk's stop_pct in [0.20, 0.50] and max_hold_min in [15, 120], clamped",
    "placebo": "judged control: same timing on ANY alive coin (20 draws per signal); no class matching",
    "fill": "common.FillConfig(exit_delay_bars=1): worst, latency 30 s, entry-bar exits, next-bar exits",
    "temperature": D.TEMPERATURE,
}


def make_params(config: str) -> dict:
    if config not in D.CONFIGS:
        raise ValueError(f"desk config {config!r} not in {tuple(D.CONFIGS)}")
    cfg = D.CONFIGS[config]
    return {
        **FIXED,
        "config": config,
        "roles": list(cfg["roles"]),
        "role_model": cfg.get("role_model"),
        "decider_model": cfg["decider_model"],
    }


GRID = [make_params(c) for c in CONFIG_ORDER]
PRIMARY_PARAMS = make_params("panel")


class K1Refused(RuntimeError):
    """A stage was asked for while its prerequisites are missing."""


def config_key(p: Mapping[str, Any]) -> str:
    return str(p["config"])


# =========================================================================== decision time, brief, strategy

CACHE = D.DecisionCache(OUT_DIR / "decisions")  # the real desk's decisions: the exam record
FAKE_CACHE = D.DecisionCache(OUT_DIR / "decisions_fake")  # the fake desk's (debug, tests): never the exam's
_ACTIVE: list[D.DecisionCache] = [CACHE]  # the cache the strategy reads; run_stage swaps it for --fake-client


@contextlib.contextmanager
def using_cache(cache: D.DecisionCache):
    """Route strategy() reads to ``cache`` for the duration (fake decisions must never pollute the real cache)."""
    prev = _ACTIVE[0]
    _ACTIVE[0] = cache
    try:
        yield cache
    finally:
        _ACTIVE[0] = prev


_UNDECIDED: set[tuple[str, str]] = set()  # (config, mint) the strategy met without a cached decision


def alive(snap: C.AsOf) -> bool:
    return bool(snap.alive(ALIVE_VOL_USD_15M, ALIVE_MCAP_USD))


def decision_time(cd: C.CoinData) -> float:
    """The first grid decision time (minute boundary + GRID_OFFSET_S) with age >= DECISION_AGE_S."""
    j = math.ceil((cd.g + DECISION_AGE_S - C.GRID_OFFSET_S - cd.m0) / 60.0)
    return cd.m0 + 60.0 * j + C.GRID_OFFSET_S


def speed_of(snap: C.AsOf) -> str:
    d = snap.get("grad_delay_s")
    if d is None:
        d = snap.get("grad_delay_lb_s")
    if d is None:
        return "unknown"
    return "instant" if float(d) <= 5.0 else "slow"


def strategy(snap: C.AsOf, p: Mapping[str, Any], pos: C.PositionView | None):
    """K1 for common.backtest: at the first decision at or after g + 30 min, enter iff the coin is alive AND the
    cached desk decision for this exact brief says buy; exits are the desk's. One decision per coin."""
    if pos is not None:
        return None
    if snap.age_s < DECISION_AGE_S:
        return None
    if not alive(snap):
        return C.SKIP
    brief = D.build_brief(snap)
    d = _ACTIVE[0].get(p["config"], D.brief_hash(brief))
    if d is None:
        _UNDECIDED.add((p["config"], snap.mint))
        return C.SKIP
    if not d.buy:
        return C.SKIP
    return C.Enter(
        exits=C.ExitSpec(
            stop_pct=float(d.stop_pct), max_hold_s=60.0 * float(d.max_hold_min), exit_by_age_s=EXIT_BY_AGE_S
        ),
        tag=str(brief.get("class")),
        state={"confidence": d.confidence, "size_usd": d.size_usd, "speed": speed_of(snap)},
    )


def placebo_ok(snap: C.AsOf) -> bool:
    """Judged control universe: ANY alive coin at the matched age."""
    return alive(snap)


# =========================================================================== deliberation (the only API calls)


def client_from_env(fake: bool, env: Mapping[str, str]) -> Any:
    if fake:
        return D.FakeDeskClient()
    key = env.get("ANTHROPIC_API_KEY")
    return D.RealDeskClient(api_key=key) if key else None


def deliberate_split(
    ds: C.Dataset, configs: list[str], client: Any, budget: D.Budget, cache: D.DecisionCache = CACHE
) -> dict[str, Any]:
    """Make sure every alive coin at its decision time has a cached decision for every config. Returns counts; raises
    D.BudgetExceeded (decisions so far stay cached) or re-raises an API error after retries."""
    out: dict[str, Any] = {
        "coins": len(ds),
        "alive_at_decision": 0,
        "decided": 0,
        "undecided": 0,
        "new_calls": 0,
        "spent_usd": 0.0,
        "buys": {c: 0 for c in configs},
    }
    for m in ds.mints:
        cd = ds.coin(m)
        t = decision_time(cd)
        if t > cd.m0 + 60 * C.N_BARS:
            continue
        snap = ds.asof(m, t)
        if not alive(snap):
            continue
        out["alive_at_decision"] += 1
        brief = D.build_brief(snap)
        for c in configs:
            before = budget.calls
            d = D.decide_cached(brief, c, cache, client, budget)
            if d is None:
                out["undecided"] += 1
                continue
            out["decided"] += 1
            out["new_calls"] += budget.calls - before
            if d.buy:
                out["buys"][c] += 1
    out["spent_usd"] = round(budget.spent_usd, 4)
    return out


# =========================================================================== evaluation


def direction(ev: Mapping[str, Any]) -> str:
    """PREREG 4: BEATS_RANDOM / WORSE_THAN_RANDOM / NEITHER from the judged control's diff 95 % CI."""
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
    conf = t["confidence"].to_numpy(float) if ("confidence" in t and len(t)) else np.zeros(0)
    base["confidence_corr"] = (
        float(np.corrcoef(conf, t["ret_net"].to_numpy(float))[0, 1]) if len(conf) >= 10 and np.std(conf) > 0 else None
    )
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
    return (-r["ci90_lo"], -r["mean"], CONFIG_ORDER.index(r["config"]))


def decide_train(evals: Mapping[str, Mapping[str, Any]]) -> dict:
    """PREREG 6 TRAIN: qualify (n >= 30, mean > 0, mean w/o top 2 > 0, judged-control diff > 0); rank by the coin
    90 % CI lower bound, then mean, then CONFIG_ORDER (panel, solo-sonnet, solo-haiku); shortlist = the top 2."""
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
        sl = [make_params(r["config"]) for r in top]
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
    return False, f"TEST mean {mean} <= 0 on {n} trades: K1 failed TEST, CONFIRM not spent"


FINAL_JUDGED = ("final_val", "final_test")
FINAL_DEBUG = "final_train"


def final_decision(t: pd.DataFrame) -> dict:
    """PLAN 3.5 item 9 on the census thirds K1 never touched; the debug third is reported apart."""
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
    """Raise :class:`K1Refused` when ``stage`` may not run. Read-only."""
    env = os.environ if env is None else env
    out_dir = Path(out_dir)
    if stage not in STAGES + ("debug",):
        raise K1Refused(f"unknown stage {stage!r}")
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise K1Refused(f"{prereg} missing: pre-register before any run")
    lock = _read_json(out_dir / "prereg.lock")
    # The first TRAIN run of ANY kind freezes PREREG.md: a provisional run shows TRAIN returns too. A train_prelim.json
    # without a lock (written before that rule) pins the sha it recorded.
    frozen = (lock or {}).get("sha256") or (_read_json(out_dir / "train_prelim.json") or {}).get("prereg_sha256")
    if frozen and frozen != _sha(prereg):
        raise K1Refused(
            "PREREG.md changed after the first TRAIN run (provisional runs included); record changes in "
            "K1/AMENDMENTS.md as a new version instead"
        )
    ok, bad = C.validation_gates(STAGE_SPLIT[stage], flow)
    if not ok and stage != "debug":
        raise K1Refused("PLAN 8 rule 1 (data first): " + "; ".join(bad))
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
            raise K1Refused(
                "TRAIN already ran on complete data (K1/train.json); its decision is final. A re-run needs "
                "--rerun-reason naming the data correction that justifies it"
            )
        return info
    if not train:
        raise K1Refused("no TRAIN result (K1/train.json): run --stage train first")
    if train.get("provisional"):
        raise K1Refused("TRAIN ran on partial data (provisional): re-run --stage train on complete TRAIN data")
    tv = (train.get("decision") or {}).get("verdict")
    if tv != "SHORTLISTED":
        raise K1Refused(f"TRAIN decision {tv}: K1 stopped before VAL")
    sl = _shortlist(shortlist_path)
    if not sl:
        raise K1Refused("no VAL shortlist for K1 (written by a complete --stage train)")
    if sorted(sl.get("hashes", [])) != sorted(train["decision"].get("shortlist_hashes", [])):
        raise K1Refused("the K1 shortlist on disk differs from the one TRAIN wrote")
    split = STAGE_SPLIT[stage]
    if stage == "val":
        if (out_dir / "val.json").exists():
            raise K1Refused("VAL already ran (K1/val.json exists): VAL is evaluated once")
        return info
    val = _read_json(out_dir / "val.json")
    if stage == "test":
        if not val:
            raise K1Refused("no VAL result (K1/val.json): TEST needs a VAL decision first")
        vv = (val.get("decision") or {}).get("verdict")
        if vv not in PROCEED_VAL:
            raise K1Refused(f"VAL decision {vv}: K1 stopped (PLAN 8 rule 7 input); TEST is not spent")
    test = _read_json(out_dir / "test.json")
    if stage in ("confirm", "final") and not test:
        raise K1Refused(f"never {stage.upper()} before TEST: run --stage test first")
    if stage == "confirm":
        ok2, why = confirm_allowed(test)
        if not ok2:
            raise K1Refused(why)
    if (out_dir / f"{stage}.json").exists():
        raise K1Refused(f"{stage.upper()} already ran (K1/{stage}.json exists): one run per hypothesis")
    grp = C.split_group(split)
    if any(
        C.hypothesis_family(r.get("hypothesis", "")) == HYP
        and C.split_group(r.get("split", "")) == grp
        and not r.get("debug")
        for r in _runs(ledger_path)
    ):
        raise K1Refused(f"{HYP} already had its one {grp} run (trials ledger)")
    if env.get(STAGE_ENV[stage]) != "1":
        raise K1Refused(f"{stage.upper()} is locked: set {STAGE_ENV[stage]}=1 (the judge's flag)")
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


def event_counts(ds: C.Dataset, delib: Mapping[str, Any] | None = None) -> dict:
    """Counts only (no prices, no returns): coins alive at the decision time, decisions cached per config, buys."""
    out: dict[str, Any] = {"coins": len(ds), "alive_at_decision": 0, "per_config": {}}
    for m in ds.mints:
        cd = ds.coin(m)
        t = decision_time(cd)
        if t <= cd.m0 + 60 * C.N_BARS and alive(ds.asof(m, t)):
            out["alive_at_decision"] += 1
    for c in CONFIG_ORDER:
        out["per_config"][c] = {"cached": _ACTIVE[0].count(c), "buys": (delib or {}).get("buys", {}).get(c)}
    if delib:
        out["deliberation"] = {k: v for k, v in delib.items() if k != "buys"}
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
    fake_client: bool = False,
    client: Any = None,
    budget_usd: float | None = None,
    decision_cache: D.DecisionCache | None = None,
) -> dict:
    """Run one stage end to end and write K1/<stage>.json + .md (``ds`` injection is for tests)."""
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
        ledger_path = C._SCRATCH / "lab2_debug" / "k1_debug_trials.json"  # debug never reaches the real ledger
    cov = ds.coverage if ds is not None else _coverage_counts(split, flow, census)
    provisional = False
    if not (debug or _skip_coverage or stage == "final"):
        ok, notes = coverage_check(cov)
        if not ok:
            if stage == "train" and allow_partial and cov.get("usable"):
                provisional = True
            else:
                raise K1Refused(
                    f"{split} data incomplete: "
                    + "; ".join(notes[:6])
                    + (" (TRAIN only: --allow-partial for a provisional run)" if stage == "train" else "")
                )
    covs = list(cov.values()) if (split == "final" and "split" not in cov) else [cov]
    hard = [] if debug else [x for cv in covs for x in C.coverage_problems(cv, provisional=True)]
    if hard:
        raise K1Refused(f"{split} data not usable: " + "; ".join(hard))
    configs = stage_configs(stage, out_dir, shortlist_path)
    if not configs or any(p is None for _, p in configs):
        raise K1Refused("no configs to run (shortlist or VAL decision missing or malformed)")

    def _execute(ds: C.Dataset | None) -> dict:
        if not debug:  # commit: every config is allowed BEFORE any data is read
            try:
                for _, p in configs:
                    C._check_run_allowed(HYP, p, split, ledger_path, shortlist_path)
            except C.SplitLocked as e:
                raise K1Refused(str(e)) from e
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
        # the desk deliberates FIRST (stage runs read the cache only); an incomplete exam is never scored
        if fake_client and not debug:
            raise K1Refused("--fake-client is for --debug and tests only: official stages need the real desk")
        cli = client if client is not None else client_from_env(fake_client, os.environ if env is None else env)
        # fake decisions live in their own cache: the real exam's cache only ever holds the real desk's answers
        cache = decision_cache
        if cache is None:
            cache = FAKE_CACHE if (fake_client or isinstance(cli, D.FakeDeskClient)) else CACHE
        cap = BUDGET_USD[stage] if budget_usd is None else min(float(budget_usd), BUDGET_USD[stage])
        budget = D.Budget(max_usd=cap)
        try:
            delib = deliberate_split(ds, [p["config"] for _, p in configs], cli, budget, cache)
        except D.BudgetExceeded as e:
            raise K1Refused(f"{e}; decisions so far are cached, re-run to resume") from e
        doc["deliberation"] = {
            **delib,
            "budget_usd": cap,
            "client": type(cli).__name__ if cli else None,
            "cache": str(cache.root.relative_to(HERE)) if cache.root.is_relative_to(HERE) else str(cache.root),
        }
        if delib["undecided"] and not debug:
            raise K1Refused(
                f"{delib['undecided']} alive coins have no desk decision and no client is available "
                "(set ANTHROPIC_API_KEY in the environment): the exam is incomplete"
            )
        with using_cache(cache):
            _UNDECIDED.clear()
            if debug:
                doc["event_counts"] = event_counts(ds, delib)
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
                    placebo_controls=None,
                    stress=STRESS,
                    declarations=DECL,
                    ledger_path=ledger_path,
                    shortlist_path=shortlist_path,
                )
            n_tr = C.n_trials(ledger_path)
            evals = {role: evaluate(r, B=B, hide=debug, n_trials_total=n_tr) for role, r in results.items()}
            doc["configs"] = evals
        if _UNDECIDED:  # must be empty: the strategy met a brief the deliberation pass never produced
            doc["undecided_in_backtest"] = sorted(_UNDECIDED)
            if not debug:
                raise K1Refused(f"{len(_UNDECIDED)} strategy decisions had no cached desk decision (brief mismatch)")
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
        C.one_shot_session(HYP, split, ledger_path, note=f"k1 --stage {stage}")
        if split in C.ONE_RUN_SPLITS
        else contextlib.nullcontext()
    )
    try:
        with session:
            return _execute(ds)
    except C.SplitLocked as e:
        raise K1Refused(str(e)) from e


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
        f"# K1 {st}{' (PROVISIONAL: partial data)' if doc.get('provisional') else ''}",
        "",
        f"- **Split:** `{doc['split']}`; usable coins: {doc['n_coins']}; span: {doc.get('span_days') or 0:.2f} days.",
        f"- **Written:** {doc['utc']} UTC; runtime {doc.get('runtime_s')} s; PREREG sha256 "
        f"`{(doc.get('prereg_sha256') or '')[:12]}`; trials in the ledger: {doc.get('n_trials_total')}.",
        f"- **Overall K1 status:** {doc.get('overall')}.",
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
            f"- Coins: {ec['coins']}; alive at the decision time: "
            f"{ec['alive_at_decision']}; deliberation: {ec.get('deliberation')}.",
            "",
        ]
        L += ["| config | decisions cached | buys |", "|---|---:|---:|"]
        for k, v in ec["per_config"].items():
            L.append(f"| {k} | {v['cached']} | {v['buys']} |")
        L.append("")
    dl = doc.get("deliberation")
    if dl and not ec:
        L += [
            f"- **Desk:** {dl.get('decided')} decisions ({dl.get('new_calls')} new API calls, "
            f"${dl.get('spent_usd', 0):.2f} of ${dl.get('budget_usd', 0):.0f}); buys per config {dl.get('buys')}.",
            "",
        ]
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
                "diff 95% CI | confidence~return corr | costs ×1.5 | direction |",
                "|---|---|---:|---:|---|---|---:|---:|---|---:|---:|---|",
            ]
            for k, e in cf.items():
                pl = e.get("placebo") or {}
                pu = e.get("confidence_corr")
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
    ap = argparse.ArgumentParser(description="K1 the Desk: pre-registered stages; see research/lab2/K1/PREREG.md")
    ap.add_argument("--stage", choices=STAGES)
    ap.add_argument("--debug", action="store_true", help="census TRAIN third: mechanics and counts only")
    ap.add_argument("--check", action="store_true", help="check the stage's prerequisites and exit")
    ap.add_argument("--allow-partial", action="store_true", help="TRAIN only: provisional run on partial data")
    ap.add_argument("--rerun-reason", help="TRAIN only: re-run an official TRAIN after a data correction")
    ap.add_argument("--B", type=int, default=10_000, help="bootstrap draws")
    ap.add_argument("--n-placebo", type=int, default=20)
    ap.add_argument("--fake-client", action="store_true", help="debug/tests only: the deterministic fake desk")
    ap.add_argument("--budget-usd", type=float, default=None, help="lower this stage's PREREG budget")
    a = ap.parse_args(argv)
    if not a.stage and not a.debug:
        ap.error("--stage or --debug is required")
    stage = "debug" if a.debug else a.stage
    try:
        if a.check:
            print(json.dumps(check_prereqs(stage, rerun_reason=a.rerun_reason), indent=1))
            return 0
        doc = run_stage(
            stage,
            allow_partial=a.allow_partial,
            rerun_reason=a.rerun_reason,
            B=a.B,
            n_placebo=a.n_placebo,
            fake_client=a.fake_client,
            budget_usd=a.budget_usd,
        )
    except K1Refused as e:
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
