"""F3 lifecycle: exploratory event study on TRAIN only (every cut is logged and counted as a look).

For each coin and each check time T (minutes after the graduation bar), features use bars <= i only;
the forward GROSS return is open[i+1] -> close[i+1+H] (no costs). Descriptive; feeds hypotheses only.

    python research/lab/f3_eda.py checkpoints
    python research/lab/f3_eda.py count
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from harness import LAB, load_coins  # noqa: E402

OUT = LAB / "f3"
OUT.mkdir(parents=True, exist_ok=True)
LOG = OUT / "eda_log.jsonl"


def grad_index(c) -> int:
    return int(np.searchsorted(c.ts + c.dur, c.graduated_ts, side="left"))


def log(cut: str, rows: dict) -> None:
    with LOG.open("a") as fh:
        fh.write(json.dumps({"cut": cut, **rows}, default=float) + "\n")


def fwd(c, i: int, h: int) -> tuple[float, float] | None:
    """gross return open[i+1] -> close[i+1+h], and min low / entry over the window."""
    if i + 1 + h >= c.n:
        return None
    e = c.o[i + 1]
    return c.c[i + 1 + h] / e - 1, c.l[i + 1:i + 2 + h].min() / e - 1


def summarize(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    a = np.asarray(xs)
    return {"n": len(a), "mean": round(100 * a.mean(), 2), "median": round(100 * np.median(a), 2),
            "win": round(100 * (a > 0).mean(), 1), "p10": round(100 * np.percentile(a, 10), 1),
            "p90": round(100 * np.percentile(a, 90), 1)}


def features(c, g: int, i: int) -> dict:
    s = slice(g, i + 1)
    peak = c.h[s].max()
    gc = c.c[g]
    v15 = c.v[max(g, i - 14):i + 1].sum()
    v60 = c.v[max(g, i - 59):i + 1].sum()
    first15 = c.v[g:g + 15].sum()
    w = slice(max(g, i - 29), i + 1)
    rng30 = c.h[w].max() / max(c.l[w].min(), 1e-18)
    return {"rel_peak": c.c[i] / peak, "rel_grad": c.c[i] / gc, "v15": v15, "v60": v60,
            "decay": v15 / max(first15, 1.0), "rng30": rng30, "mcap": c.c[i] * c.supply,
            "instant": (c.graduated_ts - c.created_ts) < 5}


def checkpoints(split: str = "train") -> None:
    cs = load_coins(split=split)
    T_list = [15, 30, 60, 120, 240]
    H = 60
    for T in T_list:
        groups: dict[str, list[float]] = {}
        for c in cs:
            g = grad_index(c)
            i = g + T
            r = fwd(c, i, H)
            if r is None:
                continue
            f = features(c, g, i)
            alive = f["v15"] >= 1500 and f["mcap"] >= 6000
            key_alive = "alive" if alive else "dead"
            groups.setdefault(f"all", []).append(r[0])
            groups.setdefault(key_alive, []).append(r[0])
            if alive:
                kind = "inst" if f["instant"] else "org"
                groups.setdefault(f"alive_{kind}", []).append(r[0])
                rp = "rp<0.3" if f["rel_peak"] < 0.3 else "rp0.3-0.7" if f["rel_peak"] < 0.7 else "rp>=0.7"
                groups.setdefault(f"alive_{rp}", []).append(r[0])
                rc = "rng30<1.3" if f["rng30"] < 1.3 else "rng30<2" if f["rng30"] < 2 else "rng30>=2"
                groups.setdefault(f"alive_{rc}", []).append(r[0])
                dc = "decay<0.1" if f["decay"] < 0.1 else "decay<0.5" if f["decay"] < 0.5 else "decay>=0.5"
                groups.setdefault(f"alive_{dc}", []).append(r[0])
        rows = {k: summarize(v) for k, v in sorted(groups.items())}
        log(f"checkpoint T={T} H={H} split={split}", {"groups": rows})
        print(f"--- T={T}min after grad, gross fwd {H}min (open[i+1] -> close[i+1+H])")
        for k, v in rows.items():
            print(f"   {k:16s} {v}")


def count() -> None:
    n_cuts, n_groups = 0, 0
    for line in LOG.read_text().splitlines() if LOG.exists() else []:
        r = json.loads(line)
        n_cuts += 1
        n_groups += len(r.get("groups", {})) or 1
    print({"eda_cuts": n_cuts, "eda_groups_looked_at": n_groups})




# --------------------------------------------------------------------------- event scans (TRAIN)

def scan(cs, cond, horizons=(15, 30, 60, 120), spacing=30, first_only=False, max_age=None, min_age=20):
    """Events where cond(c, g, i) is True (decided at bar i close). Returns {H: [ret]}, {H: [minlow]}, events."""
    out = {h: [] for h in horizons}
    lows = {h: [] for h in horizons}
    ev = []
    for c in cs:
        g = grad_index(c)
        last = -10**9
        hi = c.n - 1 if max_age is None else min(c.n - 1, g + max_age)
        for i in range(g + min_age, hi):
            if i - last < spacing:
                continue
            if cond(c, g, i):
                last = i
                ev.append((c.symbol, i - g, c.c[i] * c.supply, (c.graduated_ts - c.created_ts) < 5))
                for h in horizons:
                    r = fwd(c, i, h)
                    if r is not None:
                        out[h].append(r[0])
                        lows[h].append(r[1])
                if first_only:
                    break
    return out, lows, ev


def second_leg_cond(D=0.6, W=30, R=1.6, k=2.0, vmin=3000, mc_lo=8000, inst=None):
    def cond(c, g, i):
        if inst is not None and ((c.graduated_ts - c.created_ts) < 5) != inst:
            return False
        if c.c[i] * c.supply < mc_lo:
            return False
        w0 = i - W
        if w0 <= g:
            return False
        pk_idx = g + int(np.argmax(c.h[g:w0 + 1]))
        peak = c.h[pk_idx]
        if c.l[pk_idx:i + 1].min() > peak * (1 - D):
            return False
        hh, ll = c.h[w0:i].max(), c.l[w0:i].min()
        if hh / max(ll, 1e-18) > R:
            return False
        vw = c.v[w0:i]
        if vw.sum() < vmin:
            return False
        return c.c[i] > hh and c.v[i] >= k * max(vw.mean(), 1e-9)
    return cond


def revival_cond(dorm=60, dorm_v=500, spike_v=3000, up=0.1, mc_lo=3000):
    def cond(c, g, i):
        if i - dorm <= g or c.c[i] * c.supply < mc_lo:
            return False
        if c.v[i - dorm:i].sum() > dorm_v:
            return False
        return c.v[i] >= spike_v and c.c[i] >= c.o[i] * (1 + up)
    return cond


def events() -> None:
    cs = load_coins(split="train")
    cuts = {
        "second_leg D0.6 W30 R1.6 k2 all": second_leg_cond(),
        "second_leg D0.6 W30 R1.6 k2 org": second_leg_cond(inst=False),
        "second_leg D0.6 W30 R1.6 k2 inst": second_leg_cond(inst=True),
        "second_leg D0.5 W60 R2.0 k2 all": second_leg_cond(D=0.5, W=60, R=2.0),
        "second_leg D0.7 W60 R2.0 k3 all": second_leg_cond(D=0.7, W=60, R=2.0, k=3.0),
        "revival dorm60 v500 spike3000 up10": revival_cond(),
        "revival dorm120 v300 spike2000 up5": revival_cond(dorm=120, dorm_v=300, spike_v=2000, up=0.05),
    }
    for name, cond in cuts.items():
        out, lows, ev = scan(cs, cond)
        rows = {f"H{h}": summarize(v) for h, v in out.items()}
        rows.update({f"minlow_H{h}": summarize(v) for h, v in lows.items() if h == 60})
        n_coins = len({e[0] for e in ev})
        log(f"event {name} split=train", {"groups": rows, "coins": n_coins})
        print(f"--- {name}: {len(ev)} events on {n_coins} coins; inst share "
              f"{np.mean([e[3] for e in ev]) if ev else 0:.2f}; med age {np.median([e[1] for e in ev]) if ev else 0}")
        for k_, v in rows.items():
            print(f"   {k_:12s} {v}")

def coin_class(c, g) -> str:
    inst = (c.graduated_ts - c.created_ts) < 5
    gm = c.c[g] * c.supply
    b = "lt100k" if gm < 1e5 else "lt1M" if gm < 1e6 else "ge1M"
    return ("inst_" if inst else "org_") + b


def drift_map(split: str = "train", step: int = 15, H: int = 30) -> None:
    cs = load_coins(split=split)
    ages = [(0, 10), (10, 30), (30, 60), (60, 120), (120, 240), (240, 480), (480, 2000)]
    groups: dict[str, list[float]] = {}
    coins_in: dict[str, set] = {}
    for c in cs:
        g = grad_index(c)
        cl = coin_class(c, g)
        for i in range(g + 1, c.n - 1, step):
            a = i - g
            f = features(c, g, i)
            if not (f["v15"] >= 1500 and f["mcap"] >= 6000):
                continue
            r = fwd(c, i, H)
            if r is None:
                continue
            ab = next(f"{lo}-{hi}" for lo, hi in ages if lo <= a < hi) if a < 2000 else "2000+"
            for key in (f"{cl}|{ab}", f"ALL|{ab}", f"{cl}|ALL"):
                groups.setdefault(key, []).append(r[0])
                coins_in.setdefault(key, set()).add(c.mint)
    rows = {k: {**summarize(v), "coins": len(coins_in[k])} for k, v in sorted(groups.items())}
    log(f"drift_map step={step} H={H} split={split}", {"groups": rows})
    for k, v in rows.items():
        print(f"   {k:24s} {v}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "checkpoints"
    {"checkpoints": checkpoints, "count": count, "events": events, "drift": drift_map}[cmd]()
