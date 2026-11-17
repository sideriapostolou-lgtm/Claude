"""F3 lifecycle search: TRAIN grid -> pre-declared shortlist -> VALIDATION -> robustness.

Every configuration evaluated is appended to LAB/f3/runs.jsonl (id, stage, split, variant, params,
per-coin and portfolio metrics). ``count`` reproduces the number of configurations tried.

    python research/lab/f3_lifecycle_search.py stage1     # TRAIN grid (all entry families)
    python research/lab/f3_lifecycle_search.py stage2     # exit refinement + neighbours of the best
    python research/lab/f3_lifecycle_search.py shortlist  # pre-declared rule, TRAIN only
    python research/lab/f3_lifecycle_search.py validate   # shortlist -> VALIDATION
    python research/lab/f3_lifecycle_search.py robust ID [ID...]
    python research/lab/f3_lifecycle_search.py count

Shortlist rule (declared before any VALIDATION run): TRAIN per-coin >= 15 trades on >= 10 coins,
mean > 0, portfolio return > 0; ranked by the coin-bootstrap CI low; at most 4 per entry family and
12 in total; stability = median per-coin mean of the one-parameter neighbours (reported, and a config
whose neighbour median is <= 0 is flagged as a spike).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import itertools
import json
import multiprocessing as mp
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from costs import CostModel  # noqa: E402
from harness import LAB, SimConfig, load_coins, run_per_coin, run_portfolio  # noqa: E402


def load_f3():
    name = "f3_lifecycle"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / "strategies" / "f3-lifecycle.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


F3 = load_f3()
P = F3.F3Params
OUT = LAB / "f3"
OUT.mkdir(parents=True, exist_ok=True)
RUNS = OUT / "runs.jsonl"

SLIM_KEYS = ("trades", "coins_traded", "win_rate_pct", "avg_ret_pct", "median_ret_pct", "profit_factor",
             "net_pnl_usd", "expectancy_usd", "exp_ci95_pct", "costs_usd", "best_coin_pnl_usd",
             "best_coin_share_pct", "top3_share_pct", "pnl_without_best_coin_usd", "pnl_without_top3_usd",
             "exit_reasons", "avg_hold_min", "total_return_pct", "final_equity_usd", "max_drawdown_pct")


def slim(m: dict) -> dict:
    return {k: m.get(k) for k in SLIM_KEYS if k in m}


# --------------------------------------------------------------------------- grids

EXITS_RUNNER = {
    "s30_tr30_h120": dict(stop_pct=0.30, trail_pct=0.30, max_hold_min=120),
    "s20_tp50_h60": dict(stop_pct=0.20, tp_pct=0.50, max_hold_min=60),
    "nostop_h30": dict(stop_pct=None, max_hold_min=30),
}
EXITS_LEG = {
    "struct_tr20_h120": dict(struct_stop=True, stop_pct=None, trail_pct=0.20, max_hold_min=120),
    "s15_tp30_h60": dict(stop_pct=0.15, tp_pct=0.30, max_hold_min=60),
}
EXITS_BOUNCE = {
    "struct_tpTop_h60": dict(struct_stop=True, stop_pct=None, tp_base_top=True, max_hold_min=60),
    "struct_tp15_h30": dict(struct_stop=True, stop_pct=None, tp_pct=0.15, max_hold_min=30),
}
EXITS_DRIFT = {
    "s10_h120": dict(stop_pct=0.10, max_hold_min=120),
    "s10_h360": dict(stop_pct=0.10, max_hold_min=360),
    "s20_tr10_h360": dict(stop_pct=0.20, trail_pct=0.10, max_hold_min=360),
}
EXITS_DIP = {
    "nc_default": dict(stop_pct=0.18, tp_pct=0.40, tp_fraction=0.5, trail_pct=0.15, trail_after_tp=True,
                       max_hold_min=120),
    "s30_tp20_h60": dict(stop_pct=0.30, tp_pct=0.20, max_hold_min=60),
}


def stage1_grid() -> list[tuple[str, dict]]:
    g: list[tuple[str, dict]] = []
    # A. runner: survivors of the first-hour die-off (one entry per coin)
    for cls, (t_lo, t_hi), (rp_lo, rp_hi), v15, ex in itertools.product(
            ("org", "any"), ((10, 30), (30, 60), (60, 120), (120, 360)), ((0.0, 1.0), (0.0, 0.4), (0.7, 1.0)),
            (1500.0, 5000.0), EXITS_RUNNER.values()):
        g.append(("runner", dict(entry="runner", cls=cls, t_lo=t_lo, t_hi=t_hi, rp_lo=rp_lo, rp_hi=rp_hi,
                                 v15_min=v15, **ex)))
    # B. second leg: breakout from a post-dump base
    for dump, W, rng, vk, t_lo, ex in itertools.product((0.5, 0.7), (20, 45), (1.4, 2.0), (1.5, 3.0), (30, 120),
                                                        EXITS_LEG.values()):
        g.append(("second_leg", dict(entry="second_leg", dump=dump, W=W, rng=rng, vk=vk, t_lo=t_lo, vmin=3000.0,
                                     max_entries=3, **ex)))
    # C. base bounce: range trading inside the post-dump base
    for dump, W, rng, q, t_lo, ex in itertools.product((0.5, 0.7), (20, 45), (1.3, 1.6, 2.0), (0.2, 0.35), (30, 120),
                                                       EXITS_BOUNCE.values()):
        g.append(("base_bounce", dict(entry="base_bounce", dump=dump, W=W, rng=rng, q=q, t_lo=t_lo, vmin=3000.0,
                                      max_entries=3, **ex)))
    # D. drifter: late steady phase of instant graduates
    for gm_lo, t_lo, rng, ex, me in itertools.product((1e6, 5e6), (60, 120, 240), (1.03, 1.08), EXITS_DRIFT.values(),
                                                      (1, 4)):
        g.append(("drifter", dict(entry="drifter", cls="inst", gm_lo=gm_lo, t_lo=t_lo, W=60, rng=rng, vmin=2000.0,
                                  mc_lo=1e5, max_entries=me, **ex)))
    # E. lifecycle-gated nightcrawler dip-rebound
    for cls, (t_lo, t_hi), mc_lo, decay, ex in itertools.product(
            ("org", "any"), ((30, 240), (60, 600), (120, 1440)), (6000.0, 1e5), (0.0, 0.2), EXITS_DIP.values()):
        g.append(("gated_dip", dict(entry="gated_dip", cls=cls, t_lo=t_lo, t_hi=t_hi, mc_lo=mc_lo, mc_hi=5e6,
                                    decay_min=decay, max_entries=3, **ex)))
    return g


SMOKE = [
    ("runner", dict(entry="runner", cls="org", t_lo=30, t_hi=60, gm_hi=1e5, stop_pct=0.3, trail_pct=0.3,
                    max_hold_min=120)),
    ("second_leg", dict(entry="second_leg", dump=0.6, W=30, rng=1.6, struct_stop=True, stop_pct=None,
                        trail_pct=0.2, max_hold_min=120, max_entries=3)),
    ("base_bounce", dict(entry="base_bounce", dump=0.6, W=30, rng=1.6, struct_stop=True, stop_pct=None,
                         tp_base_top=True, max_hold_min=60, max_entries=3)),
    ("drifter", dict(entry="drifter", cls="inst", gm_lo=1e6, t_lo=120, W=60, rng=1.05, vmin=3000, stop_pct=0.1,
                     max_hold_min=240)),
    ("gated_dip", dict(entry="gated_dip", cls="org", t_lo=30, t_hi=360, mc_lo=6000, stop_pct=0.18, tp_pct=0.4,
                       tp_fraction=0.5, trail_pct=0.15, trail_after_tp=True, max_hold_min=120, max_entries=3)),
]



def stage2_grid() -> list[tuple[str, dict]]:
    """Declared after stage 1 (TRAIN only): one-parameter neighbourhoods around the two drifter centres,
    a falsification test of the 'calm late base' on ORGANIC coins, and a dying-volume exit on the best
    non-drifter configs."""
    g: list[tuple[str, dict]] = []
    centres = [
        dict(entry="drifter", cls="inst", gm_lo=5e6, t_lo=240, W=60, rng=1.03, vmin=2000.0, mc_lo=1e5,
             stop_pct=0.10, max_hold_min=120),  # 6f57468754
        dict(entry="drifter", cls="inst", gm_lo=5e6, t_lo=120, W=60, rng=1.08, vmin=2000.0, mc_lo=1e5,
             stop_pct=0.10, max_hold_min=360),  # d51828bc55
    ]
    axes = {
        "gm_lo": (1e6, 2e6, 3e6, 5e6, 1e7),
        "t_lo": (120, 180, 240, 300, 360, 480),
        "rng": (1.02, 1.03, 1.05, 1.08),
        "W": (30, 60, 120),
        "vmin": (1000.0, 2000.0, 5000.0),
        "max_hold_min": (60, 120, 180, 240, 360),
        "stop_pct": (0.05, 0.10, 0.20, None),
        "max_entries": (1, 2, 4),
    }
    for c in centres:
        g.append(("drifter", dict(c)))
        for k, vals in axes.items():
            for v in vals:
                if c.get(k, getattr(P(), k)) == v:
                    continue
                g.append(("drifter", {**c, k: v}))
        g.append(("drifter", {**c, "dead_n": 30, "dead_v": 1000.0}))
    # falsification: the same calm late base on organic graduates (no clone cluster)
    for mc_lo, t_lo, rng in itertools.product((2e4, 1e5), (120, 240), (1.1, 1.2)):
        g.append(("drifter", dict(entry="drifter", cls="org", gm_lo=0.0, t_lo=t_lo, W=60, rng=rng, vmin=2000.0,
                                  mc_lo=mc_lo, stop_pct=0.10, max_hold_min=120)))
    # dying-volume exit on the best non-drifter TRAIN configs
    rows = [r for r in load_runs("train") if r["family"] in ("runner", "gated_dip")
            and r["stage"] in ("smoke", "stage1") and (r["per_coin"].get("trades") or 0) >= 15]
    rows.sort(key=lambda r: -r["per_coin"]["avg_ret_pct"])
    for r in rows[:4]:
        for dn, dv in ((10, 500.0), (30, 2000.0)):
            g.append((r["family"], {**r["params"], "dead_n": dn, "dead_v": dv}))
    return g

# --------------------------------------------------------------------------- running

_COINS: dict[str, list] = {}


def coins_for(split: str):
    if split not in _COINS:
        _COINS[split] = load_coins(split=split)
    return _COINS[split]


def cid(params: dict) -> str:
    return P(**params).cid()


def farm_share(trades, coins) -> dict:
    """P&L split by launch cluster: brand-ticker farm (instant, grad mcap $250-500k), ticker clones
    (instant, grad mcap >= $1M), other instant, organic. Descriptive only (uses the grad-bar close)."""
    import numpy as np
    info = {}
    for c in coins:
        g = int(np.searchsorted(c.ts + c.dur, c.graduated_ts, side="left"))
        inst = (c.graduated_ts - c.created_ts) < 5
        gm = float(c.c[g]) * c.supply
        info[c.mint] = ("farm_250k_500k" if inst and 2.5e5 <= gm < 5e5 else "clone_1M+" if inst and gm >= 1e6
                        else "inst_other" if inst else "organic")
    out: dict[str, dict] = {}
    for t in trades:
        k = info.get(t.mint, "?")
        d = out.setdefault(k, {"trades": 0, "pnl_usd": 0.0})
        d["trades"] += 1
        d["pnl_usd"] = round(d["pnl_usd"] + t.pnl_usd, 3)
    return out


def evaluate(params: dict, split: str, cfg: SimConfig | None = None, coins=None, boot: int = 1000,
             detail: bool = False) -> dict:
    coins = coins if coins is not None else coins_for(split)
    fac = F3.factory(P(**params))
    pc = run_per_coin(fac, coins, cfg)
    pf = run_portfolio(fac, coins, cfg)
    out = {"per_coin": slim(pc.metrics(boot)), "portfolio": slim(pf.metrics(boot)), "portfolio_rejected": pf.rejected}
    if detail:
        out["per_coin_clusters"] = farm_share(pc.trades, coins)
        out["portfolio_clusters"] = farm_share(pf.trades, coins)
        out["per_coin_trades"] = [t.to_dict() | {"fills": None} for t in pc.trades]
    return out


def _job(args):
    stage, family, params, split = args
    t0 = time.time()
    res = evaluate(params, split)
    return {"id": cid(params), "stage": stage, "family": family, "split": split, "variant": "base",
            "params": params, "secs": round(time.time() - t0, 2), **res}


def done_keys() -> set:
    out = set()
    if RUNS.exists():
        for line in RUNS.read_text().splitlines():
            r = json.loads(line)
            out.add((r["id"], r["split"], r.get("variant", "base")))
    return out


def run_batch(stage: str, grid: list[tuple[str, dict]], split: str = "train", procs: int = 4) -> None:
    seen = done_keys()
    uniq, jobs = set(), []
    for fam, prm in grid:
        k = cid(prm)
        if (k, split, "base") in seen or k in uniq:
            continue
        uniq.add(k)
        jobs.append((stage, fam, prm, split))
    print(f"{stage}: {len(grid)} configs, {len(jobs)} new to run on {split}")
    coins_for(split)
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


# --------------------------------------------------------------------------- selection (TRAIN only)

def eligible(r: dict, min_trades: int = 15, min_coins: int = 10) -> bool:
    m, q = r["per_coin"], r["portfolio"]
    return ((m.get("trades") or 0) >= min_trades and (m.get("coins_traded") or 0) >= min_coins
            and (m.get("avg_ret_pct") or -1) > 0 and (q.get("total_return_pct") or -1) > 0
            and m.get("exp_ci95_pct") is not None)


def neighbours(rows: list[dict]) -> dict[str, list[float]]:
    """per-coin mean of every config that differs from a config in exactly one parameter (same family)."""
    by_fam: dict[str, list[dict]] = {}
    for r in rows:
        by_fam.setdefault(r["family"], []).append(r)
    out: dict[str, list[float]] = {}
    for fam, rs in by_fam.items():
        full = [(r, dataclasses.asdict(P(**r["params"]))) for r in rs]
        for r, a in full:
            nb = []
            for r2, b in full:
                if r2 is r:
                    continue
                diff = [k for k in a if a[k] != b[k]]
                if len(diff) == 1 and r2["per_coin"].get("avg_ret_pct") is not None:
                    nb.append(r2["per_coin"]["avg_ret_pct"])
            out[r["id"]] = nb
    return out


def shortlist(per_family: int = 4, total: int = 12, verbose: bool = True) -> list[dict]:
    rows = load_runs("train")
    nb = neighbours(rows)
    el = [r for r in rows if eligible(r)]
    el.sort(key=lambda r: -r["per_coin"]["exp_ci95_pct"][0])
    picked, per = [], {}
    for r in el:
        if per.get(r["family"], 0) >= per_family:
            continue
        per[r["family"]] = per.get(r["family"], 0) + 1
        picked.append(r)
        if len(picked) >= total:
            break
    if verbose:
        print(f"TRAIN configs: {len(rows)}; eligible (>=15 trades/10 coins, mean>0, portfolio>0): {len(el)}; "
              f"CI low > 0: {sum(1 for r in el if r['per_coin']['exp_ci95_pct'][0] > 0)}")
        for r in picked:
            m, q = r["per_coin"], r["portfolio"]
            n = nb.get(r["id"], [])
            med = statistics.median(n) if n else None
            print(f"  {r['id']} {r['family']:11s} n={m['trades']}/{m['coins_traded']} avg={m['avg_ret_pct']:6.2f} "
                  f"ci={m['exp_ci95_pct']} pf={q['total_return_pct']:6.1f}% dd={q['max_drawdown_pct']:4.1f} "
                  f"best%={m.get('best_coin_share_pct') and round(m['best_coin_share_pct'])} "
                  f"-top3={m.get('pnl_without_top3_usd') and round(m['pnl_without_top3_usd'], 1)} "
                  f"nb_med={med and round(med, 2)} (n={len(n)})  {P(**r['params']).key()}")
    return picked


def validate(ids: list[str] | None = None) -> None:
    rows = {r["id"]: r for r in load_runs("train")}
    sl = [rows[i] for i in ids] if ids else shortlist(verbose=False)
    seen = done_keys()
    coins_for("validation")
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
        print(f"  {r['id']} {r['family']:11s} TRAIN avg={r['per_coin']['avg_ret_pct']:6.2f} "
              f"ci={r['per_coin']['exp_ci95_pct']} | VAL n={m['trades']}/{m['coins_traded']} avg={m.get('avg_ret_pct')} "
              f"ci={m.get('exp_ci95_pct')} pf_ret={q.get('total_return_pct')} dd={q.get('max_drawdown_pct')} "
              f"-best={m.get('pnl_without_best_coin_usd')}")


# --------------------------------------------------------------------------- robustness

class rug_aware_fills:
    """Stress (this process only): a stop/trail that wicks through fills at min(harness fill, bar close).
    Same rule as f2_momentum_search.rug_aware_fills, re-implemented to keep the families independent."""

    def __enter__(self):
        import harness as Hm
        self.Hm = Hm
        self.oi, self.od = Hm.CoinEngine._intrabar, Hm.CoinEngine._down_fill
        oi, od = self.oi, self.od

        def intrabar(eng, j):
            eng._cur_close = float(eng.coin.c[j])
            return oi(eng, j)

        def down_fill(eng, level, o, low):
            f = od(eng, level, o, low)
            c = getattr(eng, "_cur_close", None)
            return min(f, max(c, low)) if c is not None else f

        Hm.CoinEngine._intrabar, Hm.CoinEngine._down_fill = intrabar, down_fill
        return self

    def __exit__(self, *a):
        self.Hm.CoinEngine._intrabar, self.Hm.CoinEngine._down_fill = self.oi, self.od


def robustness(params: dict, split: str = "validation") -> dict:
    coins = coins_for(split)
    out: dict = {}
    variants = {
        "base": SimConfig(),
        "costs_x1.5": SimConfig(cost=CostModel().stressed(1.5)),
        "costs_x2": SimConfig(cost=CostModel().stressed(2.0)),
        "latency_+1bar": SimConfig(entry_delay_bars=2),
        "wick_worst": SimConfig(wick_fill="worst"),
        "wick_touch": SimConfig(wick_fill="touch"),
        "size_$10": SimConfig(fixed_usd=10.0, max_usd=10.0, min_usd=5.0, position_pct=0.10),
        "size_$40": SimConfig(fixed_usd=40.0, max_usd=40.0, position_pct=0.40),
    }
    for k, cfg in variants.items():
        out[k] = evaluate(params, split, cfg, coins, detail=(k == "base"))
    with rug_aware_fills():
        out["rug_aware_fills"] = evaluate(params, split, None, coins)
    base_pc = run_per_coin(F3.factory(P(**params)), coins)
    by: dict[str, float] = {}
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


def robust_cmd(ids: list[str], split: str = "validation") -> None:
    rows = {r["id"]: r for r in load_runs("train")}
    res = {}
    for i in ids:
        r = rows[i]
        t0 = time.time()
        res[i] = {"params": r["params"], "family": r["family"], split: robustness(r["params"], split)}
        print(f"{i} robustness on {split} in {time.time() - t0:.0f}s")
        for k, v in res[i][split].items():
            m, q = v["per_coin"], v["portfolio"]
            print(f"   {k:16s} n={m.get('trades')} avg={m.get('avg_ret_pct') and round(m['avg_ret_pct'], 2)} "
                  f"ci={m.get('exp_ci95_pct')} pf_ret={q.get('total_return_pct') and round(q['total_return_pct'], 1)} "
                  f"dd={q.get('max_drawdown_pct') and round(q['max_drawdown_pct'], 1)}")
    path = OUT / f"robustness_{split}.json"
    old = json.loads(path.read_text()) if path.exists() else {}
    old.update(res)
    path.write_text(json.dumps(old, indent=1, default=str))


def count() -> dict:
    rows = [json.loads(x) for x in RUNS.read_text().splitlines()] if RUNS.exists() else []
    train = {r["id"] for r in rows if r["split"] == "train" and r.get("variant", "base") == "base"}
    val = {r["id"] for r in rows if r["split"] == "validation" and r.get("variant", "base") == "base"}
    fams: dict[str, int] = {}
    for r in rows:
        if r["split"] == "train" and r.get("variant", "base") == "base":
            fams[r["family"]] = fams.get(r["family"], 0) + 1
    out = {"train_configs": len(train), "validation_configs": len(val), "train_by_family": fams}
    print(out)
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "count"
    if cmd == "smoke":
        run_batch("smoke", SMOKE)
    elif cmd == "stage1":
        run_batch("stage1", stage1_grid())
    elif cmd == "stage2":
        run_batch("stage2", stage2_grid())
    elif cmd == "shortlist":
        shortlist()
    elif cmd == "validate":
        validate(sys.argv[2:] or None)
    elif cmd == "robust":
        robust_cmd(sys.argv[2:])
    elif cmd == "count":
        count()
    else:
        raise SystemExit(f"unknown command {cmd}")
