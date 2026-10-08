"""F2 momentum parameter search (TRAIN), shortlist check (VALIDATION) and robustness.

    python research/lab/f2_momentum_search.py stage1          # entry screening on TRAIN
    python research/lab/f2_momentum_search.py stage2          # exit refinement around the top TRAIN entries
    python research/lab/f2_momentum_search.py shortlist       # rank TRAIN (with neighbour stability)
    python research/lab/f2_momentum_search.py validate        # shortlist -> VALIDATION
    python research/lab/f2_momentum_search.py robust ID ...   # robustness of finalists on VALIDATION

Every configuration evaluated is appended to LAB/f2/runs.jsonl with its split, so the total number of
configurations tried is auditable (``python ... count``). TEST is never touched (the harness locks it).
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.util
import itertools
import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from harness import LAB, SimConfig, load_coins, run_per_coin, run_portfolio, audit_lookahead  # noqa: E402
from costs import CostModel  # noqa: E402


def load_f2():
    name = "f2_momentum"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / "strategies" / "f2-momentum.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


F2 = load_f2()
P = F2.F2Params
OUT = LAB / "f2"
OUT.mkdir(parents=True, exist_ok=True)
RUNS = OUT / "runs.jsonl"

EXITS = {
    "T": dict(stop_pct=0.10, trail_pct=0.10, max_hold_min=30),
    "M": dict(stop_pct=0.15, trail_pct=0.20, max_hold_min=60),
    "L": dict(stop_pct=0.30, trail_pct=0.30, max_hold_min=180),
}

SLIM = ["trades", "coins_traded", "win_rate_pct", "avg_ret_pct", "median_ret_pct", "profit_factor", "net_pnl_usd",
        "expectancy_usd", "exp_ci95_pct", "best_coin_pnl_usd", "best_coin_share_pct", "top3_share_pct",
        "pnl_without_best_coin_usd", "pnl_without_top3_usd", "exit_reasons", "avg_hold_min", "costs_usd",
        "total_return_pct", "final_equity_usd", "max_drawdown_pct"]


def cid(params: dict) -> str:
    return hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:10]


def slim(m: dict) -> dict:
    return {k: m.get(k) for k in SLIM if k in m}


# --------------------------------------------------------------------------- grids


def stage1_grid() -> list[tuple[str, dict]]:
    g: list[tuple[str, dict]] = []
    ages = {"a0-30": (0, 30), "a30-240": (30, 240), "a240-1440": (240, 1440)}
    # breakout: 2*2*2*3*3*2*3 = 432
    for lb, vm, mv, (ak, (a0, a1)), mc, gk, ek in itertools.product(
            (15, 60), (2.0, 5.0), (2_000.0, 10_000.0), ages.items(), (20_000.0, 200_000.0, 1_000_000.0),
            ("any", "organic"), EXITS):
        g.append(("breakout", dict(entry="breakout", lookback=lb, vol_mult=vm, min_vol_usd=mv, min_age_min=a0,
                                   max_age_min=a1, mc_lo=mc, grad_kind=gk, max_entries=3, **EXITS[ek])))
    # early strength: 4*2*2*2*2*3 = 192
    for cm, rel, dd, mv, gk, ek in itertools.product((15, 30, 60, 120), (0.5, 1.5), (0.25, 0.5), (5_000.0, 25_000.0),
                                                     ("any", "organic"), EXITS):
        g.append(("early", dict(entry="early", check_min=cm, min_age_min=0, max_age_min=cm + 5, min_rel_grad=rel,
                                max_dd=dd, min_vol_usd=mv, vol_win=15, grad_kind=gk, **EXITS[ek])))
    # squeeze: 2*2*2*2*2*3 = 96
    for w, rng, vm, mc, gk, ek in itertools.product((15, 30), (0.15, 0.30), (2.0, 4.0), (20_000.0, 200_000.0),
                                                    ("any", "organic"), EXITS):
        g.append(("squeeze", dict(entry="squeeze", squeeze_win=w, squeeze_range=rng, squeeze_active=w // 2,
                                  vol_mult=vm, min_vol_usd=2_000.0, min_age_min=15, max_age_min=1440, mc_lo=mc,
                                  grad_kind=gk, max_entries=3, **EXITS[ek])))
    return g


STAGE2_EXITS = [
    dict(stop_pct=0.08, trail_pct=0.08, max_hold_min=20),
    dict(stop_pct=0.10, trail_pct=0.15, max_hold_min=60),
    dict(stop_pct=0.15, trail_pct=0.10, max_hold_min=30),
    dict(stop_pct=0.20, trail_pct=0.25, max_hold_min=120),
    dict(stop_pct=0.25, trail_pct=0.40, max_hold_min=240),
    dict(stop_pct=0.15, trail_pct=None, trail_atr_mult=2.0, max_hold_min=60),
    dict(stop_pct=0.15, trail_pct=None, trail_atr_mult=4.0, max_hold_min=60),
    dict(stop_pct=0.25, trail_pct=None, trail_atr_mult=4.0, max_hold_min=180),
    dict(stop_pct=0.15, trail_pct=0.20, max_hold_min=60, fail_bars=5, fail_ret=0.0),
    dict(stop_pct=0.25, trail_pct=0.30, max_hold_min=180, fail_bars=10, fail_ret=0.05),
    dict(stop_pct=0.15, trail_pct=0.15, max_hold_min=120, tp_pct=0.5, tp_fraction=0.5, trail_after_tp=True),
    dict(stop_pct=0.20, trail_pct=0.20, max_hold_min=180, tp_pct=1.0, tp_fraction=0.5, trail_after_tp=True),
    dict(stop_pct=0.10, trail_pct=None, max_hold_min=15, tp_pct=0.15),
    dict(stop_pct=0.20, trail_pct=None, max_hold_min=60, tp_pct=0.30),
    dict(stop_pct=None, trail_pct=None, max_hold_min=10),
    dict(stop_pct=None, trail_pct=None, max_hold_min=60),
]
EXIT_KEYS = ("stop_pct", "trail_pct", "trail_atr_mult", "max_hold_min", "fail_bars", "fail_ret", "tp_pct",
             "tp_fraction", "trail_after_tp")


# --------------------------------------------------------------------------- running

_COINS: dict[str, list] = {}


def coins_for(split: str):
    if split not in _COINS:
        _COINS[split] = load_coins(split=split)
    return _COINS[split]


def evaluate(params: dict, split: str, cfg: SimConfig | None = None, coins=None, boot: int = 1000) -> dict:
    coins = coins if coins is not None else coins_for(split)
    fac = F2.factory(P(**params))
    pc = run_per_coin(fac, coins, cfg)
    pf = run_portfolio(fac, coins, cfg)
    return {"per_coin": slim(pc.metrics(boot)), "portfolio": slim(pf.metrics(boot)),
            "portfolio_rejected": pf.rejected}


def _job(args):
    stage, family, params, split = args
    t0 = time.time()
    res = evaluate(params, split)
    return {"id": cid(params), "stage": stage, "family": family, "split": split, "params": params,
            "secs": round(time.time() - t0, 2), **res}


def done_keys() -> set[tuple[str, str]]:
    out = set()
    if RUNS.exists():
        for line in RUNS.read_text().splitlines():
            r = json.loads(line)
            out.add((r["id"], r["split"], r.get("variant", "base")))
    return out


def run_batch(stage: str, grid: list[tuple[str, dict]], split: str, procs: int = 4) -> None:
    seen = done_keys()
    jobs = [(stage, fam, prm, split) for fam, prm in grid if (cid(prm), split, "base") not in seen]
    print(f"{stage}: {len(grid)} configs, {len(jobs)} to run on {split}")
    coins_for(split)  # load before forking
    t0 = time.time()
    with mp.get_context("fork").Pool(procs) as pool, RUNS.open("a") as fh:
        for k, row in enumerate(pool.imap_unordered(_job, jobs, chunksize=2)):
            fh.write(json.dumps(row, default=str) + "\n")
            fh.flush()
            if (k + 1) % 50 == 0:
                print(f"  {k + 1}/{len(jobs)}  {time.time() - t0:.0f}s")


def load_runs(split: str | None = None, variant: str = "base") -> list[dict]:
    rows = [json.loads(x) for x in RUNS.read_text().splitlines()] if RUNS.exists() else []
    return [r for r in rows if (split is None or r["split"] == split) and r.get("variant", "base") == variant]


# --------------------------------------------------------------------------- scoring


def score(r: dict, min_trades: int = 15, min_coins: int = 10) -> float | None:
    """TRAIN score = coin-bootstrap lower 95 % bound of the per-coin mean return (pct).
    None when the sample is too small to say anything."""
    m = r["per_coin"]
    if (m.get("trades") or 0) < min_trades or (m.get("coins_traded") or 0) < min_coins or not m.get("exp_ci95_pct"):
        return None
    return m["exp_ci95_pct"][0]


def entry_part(params: dict) -> dict:
    return {k: v for k, v in params.items() if k not in EXIT_KEYS}


def stage2_grid(top_n: int = 12) -> list[tuple[str, dict]]:
    rows = [r for r in load_runs("train") if r["stage"] == "stage1"]
    best: dict[str, tuple[float, dict]] = {}
    for r in rows:
        m = r["per_coin"]
        if (m.get("trades") or 0) < 15 or (m.get("coins_traded") or 0) < 10:
            continue
        e = entry_part(r["params"])
        k = json.dumps(e, sort_keys=True)
        s = m["avg_ret_pct"]
        if k not in best or s > best[k][0]:
            best[k] = (s, e)
    ranked = sorted(best.values(), key=lambda t: -t[0])[:top_n]
    print("stage2 entries (best stage-1 per-coin avg ret % over the 3 exit templates):")
    for s, e in ranked:
        print(f"  {s:7.2f}  {e}")
    g = []
    for _, e in ranked:
        for ex in STAGE2_EXITS:
            prm = dict(e)
            for k in EXIT_KEYS:
                prm.pop(k, None)
            prm.update({"trail_pct": None} | ex)
            g.append((e["entry"], prm))
    return g


def neighbours(rows: list[dict]) -> dict[str, list[float]]:
    """For each config: scores of configs that differ in exactly ONE parameter (grid neighbours)."""
    by_entry = {}
    for r in rows:
        by_entry.setdefault(r["params"]["entry"], []).append(r)
    out: dict[str, list[float]] = {}
    for fam, rs in by_entry.items():
        for a in rs:
            pa = a["params"]
            vals = []
            for b in rs:
                if b is a:
                    continue
                pb = b["params"]
                keys = set(pa) | set(pb)
                diff = [k for k in keys if pa.get(k) != pb.get(k)]
                if len(diff) == 1 or (len(diff) == 2 and set(diff) <= {"min_age_min", "max_age_min"}):
                    vals.append(b["per_coin"].get("avg_ret_pct") if b["per_coin"].get("trades") else None)
            out[a["id"]] = [v for v in vals if v is not None]
    return out


def shortlist(n: int = 15) -> list[dict]:
    rows = load_runs("train")
    nb = neighbours(rows)
    cands = []
    for r in rows:
        s = score(r)
        if s is None:
            continue
        nbv = nb.get(r["id"], [])
        nb_med = sorted(nbv)[len(nbv) // 2] if nbv else None
        cands.append((s, nb_med, r))
    cands.sort(key=lambda t: -t[0])
    print(f"{len(rows)} TRAIN configs; {len(cands)} with >= 15 trades on >= 10 coins")
    print("top by TRAIN lower CI of per-coin mean return:")
    for s, nbm, r in cands[:40]:
        m, q = r["per_coin"], r["portfolio"]
        print(f"  {r['id']} lo={s:7.2f} avg={m['avg_ret_pct']:7.2f} n={m['trades']:3d}/{m['coins_traded']:3d} "
              f"nb_med={nbm if nbm is None else round(nbm, 2)} pf_ret={q.get('total_return_pct', 0):7.1f} "
              f"dd={q.get('max_drawdown_pct', 0):5.1f} -best={m['pnl_without_best_coin_usd']:.1f} "
              f"-top3={m['pnl_without_top3_usd']:.1f} {F2.F2Params(**r['params']).key()}")
    # shortlist: positive per-coin mean on train, ranked by lower CI, then neighbour median as tiebreak
    sl = [r for s, nbm, r in cands if r["per_coin"]["avg_ret_pct"] > 0][:n]
    return sl


# --------------------------------------------------------------------------- validation + robustness


def validate(ids: list[str] | None = None, n: int = 15) -> None:
    sl = shortlist(n) if not ids else [r for r in load_runs("train") if r["id"] in ids]
    seen = done_keys()
    print(f"\nVALIDATION of {len(sl)} shortlisted configs")
    with RUNS.open("a") as fh:
        for r in sl:
            if (r["id"], "validation", "base") in seen:
                continue
            row = _job(("validate", r["family"], r["params"], "validation"))
            fh.write(json.dumps(row, default=str) + "\n")
    vals = {r["id"]: r for r in load_runs("validation")}
    for r in sl:
        v = vals[r["id"]]
        m, q = v["per_coin"], v["portfolio"]
        print(f"  {r['id']} TRAIN avg={r['per_coin']['avg_ret_pct']:6.2f} | VAL n={m['trades']}/{m['coins_traded']} "
              f"avg={m.get('avg_ret_pct')} ci={m.get('exp_ci95_pct')} pf_ret={q.get('total_return_pct')} "
              f"dd={q.get('max_drawdown_pct')} -best={m.get('pnl_without_best_coin_usd')} "
              f"{F2.F2Params(**r['params']).key()}")


def robustness(params: dict, split: str = "validation") -> dict:
    coins = coins_for(split)
    out = {}
    variants = {
        "base": SimConfig(),
        "costs_x1.5": SimConfig(cost=CostModel().stressed(1.5)),
        "costs_x2": SimConfig(cost=CostModel().stressed(2.0)),
        "latency_+1bar": SimConfig(entry_delay_bars=2),
        "wick_worst": SimConfig(wick_fill="worst"),
        "wick_touch": SimConfig(wick_fill="touch"),
        "size_$10": SimConfig(fixed_usd=10.0, max_usd=10.0, min_usd=5.0),
        "size_$40": SimConfig(fixed_usd=40.0, max_usd=40.0, position_pct=0.40),
    }
    for k, cfg in variants.items():
        out[k] = evaluate(params, split, cfg, coins)
    # without the single best coin (per-coin P&L) / first vs second half of the split (by creation time)
    base_pc = run_per_coin(F2.factory(P(**params)), coins)
    by = {}
    for t in base_pc.trades:
        by[t.mint] = by.get(t.mint, 0.0) + t.pnl_usd
    if by:
        best = max(by, key=by.get)
        rest = [c for c in coins if c.mint != best]
        out["without_best_coin"] = evaluate(params, split, None, rest)
        out["without_best_coin"]["removed"] = next(c.symbol for c in coins if c.mint == best)
    half = len(coins) // 2
    out["first_half"] = evaluate(params, split, None, coins[:half])
    out["second_half"] = evaluate(params, split, None, coins[half:])
    return out


ZERO_COST = CostModel(ultra_bps=0, mev_bps=0, fee_mult=0, impact_mult=1e-9, priority_sol=0, base_fee_lamports=0)


def gross(top: int = 20, split: str = "train") -> None:
    """Diagnostic: do the best TRAIN configs have a GROSS edge (zero costs, touch wicks)? Logged as
    variant rows (same config id) so they do not inflate the config count."""
    rows = [r for r in load_runs("train") if (r["per_coin"].get("trades") or 0) >= 15]
    rows.sort(key=lambda r: -r["per_coin"]["avg_ret_pct"])
    coins = coins_for(split)
    with RUNS.open("a") as fh:
        for r in rows[:top]:
            fac = F2.factory(P(**r["params"]))
            out = {}
            for lab, cfg in {"zero_cost": SimConfig(cost=ZERO_COST),
                             "zero_cost_touch": SimConfig(cost=ZERO_COST, wick_fill="touch")}.items():
                m = run_per_coin(fac, coins, cfg).metrics(500)
                out[lab] = slim(m)
            row = {"id": r["id"], "stage": "gross", "family": r["family"], "split": split, "variant": "gross",
                   "params": r["params"], **out}
            fh.write(json.dumps(row, default=str) + "\n")
            zc, zt = out["zero_cost"], out["zero_cost_touch"]
            print(f"{r['id']} net={r['per_coin']['avg_ret_pct']:6.2f} gross={zc['avg_ret_pct']:6.2f} "
                  f"gross_touch={zt['avg_ret_pct']:6.2f} ci={zc['exp_ci95_pct']} n={zc['trades']} "
                  f"{F2.F2Params(**r['params']).key()}")


def count() -> dict:
    rows = load_runs(None)
    by = {}
    for r in rows:
        by.setdefault((r["split"], r["stage"]), set()).add(r["id"])
    return {f"{k[0]}/{k[1]}": len(v) for k, v in sorted(by.items())} | {
        "unique_train_configs": len({r["id"] for r in rows if r["split"] == "train"}),
        "unique_validation_configs": len({r["id"] for r in rows if r["split"] == "validation"})}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "count"
    if cmd == "stage1":
        run_batch("stage1", stage1_grid(), "train")
    elif cmd == "stage2":
        run_batch("stage2", stage2_grid(), "train")
    elif cmd == "shortlist":
        shortlist()
    elif cmd == "validate":
        validate(sys.argv[2:] or None)
    elif cmd == "gross":
        gross()
    elif cmd == "count":
        print(json.dumps(count(), indent=1))
    else:
        raise SystemExit(f"unknown command {cmd}")
