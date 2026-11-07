"""Independent re-implementation of finalist F4-#1 / F4-#2 (auditor's code).

Deliberately does NOT import harness.py, costs.py or strategies/f4-learned.py. Everything that decides a
trade is re-written here from the written spec (DATASET.md, the F4 report) and from first principles:

* coin files and SOL/USD are read straight from JSON;
* the 39 features are computed row by row from ``bars[:i+1]`` only (plain loops, no vectorised
  rolling helpers), so a row physically cannot see bar i+1;
* the gate, entry rule and exits follow the frozen parameters in judge/frozen_finalists.json;
* costs are rebuilt from the pump.fun fee page (tiers), the Jupiter Ultra fee, the MEV buffer, x*y=k
  impact with the migration k, and the network fee.

The only shared artefact is the frozen model pickle (sha256 checked). It references
``f4_learned.FoldEnsemble``; a custom unpickler maps that to a local stub, so f4-learned.py is never
executed. Output: one JSON file of trades per run, compared with the judge by ``compare``.

    python research/lab/audit/indep_f4.py run test  --q 0.98 [--mints a,b,c] [--delay 1] [--out f.json]
    python research/lab/audit/indep_f4.py compare LAB/audit/indep_test_q98.json
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
import pickle
import sys
from pathlib import Path

import numpy as np

LAB = Path(os.environ.get(
    "LAB_DATA", "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/lab"))
LABDIR = Path(__file__).resolve().parents[1]
FROZEN = LABDIR / "judge" / "frozen_finalists.json"
OUT = LAB / "audit"

# ----------------------------------------------------------------------------- constants (own derivation)
SOL_NATIVE_QUOTE = "11111111111111111111111111111111"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
# migration: the completed curve holds 115.005359057 SOL virtual = 85.005359057 real; pump.fun keeps a
# 0.015 SOL graduation fee; 1e9 - 793.1M curve tokens = 206.9M tokens go to the pool.
POOL_SOL0 = 85.005359057 - 0.015
POOL_TOK0 = 1_000_000_000 - 793_100_000
K_MIGRATION = POOL_SOL0 * POOL_TOK0
GRAD_LEVEL_SOL = POOL_SOL0 / POOL_TOK0 * 1e9  # ~410.8 SOL; the strategy uses the rounded 411
# pump.fun/docs/fees snapshot (LAB/pumpfun_fees_snapshot.html), SOL-paired PumpSwap pools: total fee by
# market cap in SOL. Re-typed from the page, not copied from costs.py.
FEE_TIERS_SOL = [(420, 1.25), (1470, 1.20), (2460, 1.15), (3440, 1.10), (4420, 1.05), (9820, 1.00),
                 (14740, 0.95), (19650, 0.90), (24560, 0.85), (29470, 0.80), (34380, 0.75), (39300, 0.70),
                 (44210, 0.65), (49120, 0.60), (54030, 0.55), (58940, 0.525), (63860, 0.50), (68770, 0.475),
                 (73681, 0.45), (78590, 0.425), (83500, 0.40), (88400, 0.375), (93330, 0.35), (98240, 0.325)]
ULTRA_PCT = 0.10
MEV_PCT = 0.20
NETWORK_SOL = 5000 / 1e9 + 0.0002


def pool_fee_pct(mcap_sol: float) -> float:
    for upper, pct in FEE_TIERS_SOL:
        if mcap_sol < upper:
            return pct
    return 0.30


class Costs:
    """Per-side costs. ``mult`` scales every component (stress); ``side_pct_override`` replaces
    pool+Ultra+MEV with a measured per-side percentage (live-quote re-run)."""

    def __init__(self, mult: float = 1.0, side_pct_override: float | None = None, impact_k_mult: float = 1.0):
        self.mult = mult
        self.override = side_pct_override
        self.k = K_MIGRATION * impact_k_mult

    def side_pct(self, price_usd: float, sol: float) -> float:
        if self.override is not None:
            return self.override
        return self.mult * (pool_fee_pct(price_usd * 1e9 / sol) + ULTRA_PCT + MEV_PCT)

    def quote_reserve_usd(self, price_usd: float, sol: float) -> float:
        if self.mult <= 0:
            return math.inf  # zero-cost bound: no impact either
        p_sol = price_usd / sol
        return math.sqrt(self.k * p_sol) * sol / self.mult

    def network_usd(self, sol: float) -> float:
        return self.mult * NETWORK_SOL * sol

    def buy(self, usd: float, price: float, sol: float) -> float:
        net = usd * (1 - self.side_pct(price, sol) / 100)
        x = self.quote_reserve_usd(price, sol)
        return net / price if math.isinf(x) else net / price * x / (x + net)  # tokens out of x*y=k

    def sell(self, tokens: float, price: float, sol: float) -> float:
        val = tokens * price
        x = self.quote_reserve_usd(price, sol)
        gross = val if math.isinf(x) else val * x / (x + val)
        return gross * (1 - self.side_pct(price, sol) / 100)


# ----------------------------------------------------------------------------- data
class Sol:
    def __init__(self, shift_s: float = 0.0) -> None:
        self.shift = shift_s  # 60 = use only SOL minutes that have CLOSED by ts (audit of the 1-min SOL lookahead)
        rows = json.loads((LAB / "sol_usd.json").read_text())["candles"]
        rows.sort(key=lambda r: r[0])
        self.t = [int(r[0]) for r in rows]
        self.c = [float(r[4]) for r in rows]

    def at(self, ts: float) -> float:
        """Close of the last SOL minute whose START is <= ts (same convention as the lab, see audit notes)."""
        k = bisect.bisect_right(self.t, ts - self.shift) - 1
        return self.c[max(k, 0)]


def load_coin(mint: str) -> dict:
    d = json.loads((LAB / "coins" / f"{mint}.json").read_text())
    a = np.asarray(d["candles"], dtype=float)
    cov = d.get("coverage") or {}
    first_1m = cov.get("first_1m_ts", a[0, 0])
    dur = np.where(a[:, 0] < first_1m, cov.get("bar_s_before_1m", 300), 60).astype(float)
    return {"mint": mint, "symbol": d.get("coin"), "created": float(d["created_ts"]),
            "grad": float(d["graduated_ts"]), "launch": d.get("launch") or {}, "cov": cov,
            "ts": a[:, 0], "o": a[:, 1], "h": a[:, 2], "l": a[:, 3], "c": a[:, 4], "v": a[:, 5], "dur": dur}


def in_universe(coin: dict) -> bool:
    lf = coin["launch"]
    return lf.get("quote_mint") == SOL_NATIVE_QUOTE and not lf.get("mayhem") \
        and coin["cov"].get("source", "1m") in ("1m", "gt1m+1m")


def split_mints(split: str) -> list[str]:
    return list(json.loads((LABDIR / "splits.json").read_text())[split])


# ----------------------------------------------------------------------------- model (stub unpickler)
class _Ens:
    def __setstate__(self, st):
        self.__dict__.update(st)


class _Unpickler(pickle.Unpickler):
    def find_class(self, module, name):
        if module == "f4_learned" and name == "FoldEnsemble":
            return _Ens
        return super().find_class(module, name)


def load_model(path: Path, sha: str) -> _Ens:
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sha, "model hash differs from the frozen one"
    import io
    return _Unpickler(io.BytesIO(raw)).load()


def model_score(ens: _Ens, row: np.ndarray) -> float:
    x = np.clip(np.nan_to_num(row, nan=0.0, posinf=0.0, neginf=0.0), -50, 50)[None, ens.cols]
    if ens.kind == "gbt_reg":
        return float(np.mean([m.predict(x)[0] for m in ens.models]))
    return float(np.mean([m.predict_proba(x)[0, 1] for m in ens.models]))


# ----------------------------------------------------------------------------- features, row by row
NAMES = ["r1", "r5", "r15", "r60", "dd_hi15", "dd_hi60", "dd_hi_grad", "reb_lo15", "reb_lo60", "lv1", "lv5",
         "lv60", "lv_grad", "vratio_5_60", "vratio_1_15", "rv15", "rv60", "worst_drop15", "body", "upper_wick",
         "lower_wick", "body5", "green15", "zero15", "zero60", "age_min_log", "since_grad_log", "grad_delay_log",
         "since_high_log", "mcap_log10", "dist_grad_level", "rel_grad_close", "peak_rel_grad", "has_twitter",
         "has_website", "has_telegram", "desc_len_log", "cashback", "token2022"]


def _win(seq: list, i: int, w: int, pad):
    """seq[i-w+1..i], front-padded with ``pad`` when i-w+1 < 0."""
    lo = i - w + 1
    if lo >= 0:
        return seq[lo:i + 1]
    return [pad] * (-lo) + seq[:i + 1]


def feature_row(cn: dict, i: int, sol_now: float) -> tuple[dict, float, int | None]:
    """Features at the close of bar i from bars 0..i ONLY (the arrays are cut before anything else)."""
    ts, o, h, l, c, v, dur = (list(cn[k][:i + 1]) for k in ("ts", "o", "h", "l", "c", "v", "dur"))
    tiny = 1e-18
    lc = [math.log(max(x, tiny)) for x in c]
    lh = [math.log(max(x, tiny)) for x in h]
    ll = [math.log(max(x, tiny)) for x in l]
    f = {}
    for k in (1, 5, 15, 60):
        f[f"r{k}"] = lc[i] - lc[max(i - k, 0)]
    f["dd_hi15"] = lc[i] - max(lh[max(0, i - 14):])
    f["dd_hi60"] = lc[i] - max(lh[max(0, i - 59):])
    f["reb_lo15"] = lc[i] - min(ll[max(0, i - 14):])
    f["reb_lo60"] = lc[i] - min(ll[max(0, i - 59):])
    v5, v15, v60 = sum(_win(v, i, 5, 0.0)), sum(_win(v, i, 15, 0.0)), sum(_win(v, i, 60, 0.0))
    f["lv1"], f["lv5"], f["lv60"] = math.log1p(v[i]), math.log1p(v5), math.log1p(v60)
    f["vratio_5_60"] = math.log((v5 / 5 + 1) / (v60 / 60 + 1))
    f["vratio_1_15"] = math.log((v[i] + 1) / (v15 / 15 + 1))
    r1 = [0.0] + [lc[k] - lc[k - 1] for k in range(1, i + 1)]
    f["rv15"] = float(np.std(_win(r1, i, 15, 0.0)))
    f["rv60"] = float(np.std(_win(r1, i, 60, 0.0)))
    drop = [0.0] + [ll[k] - lc[k - 1] for k in range(1, i + 1)]
    f["worst_drop15"] = min(min(_win(drop, i, 15, 0.0)), 0.0)

    def parts(k):
        rg = h[k] - l[k]
        if rg <= 0:
            return 0.0, 0.0, 0.0
        return (c[k] - o[k]) / rg, (h[k] - max(o[k], c[k])) / rg, (min(o[k], c[k]) - l[k]) / rg

    f["body"], f["upper_wick"], f["lower_wick"] = parts(i)
    bodies = [parts(k)[0] for k in range(i + 1)]
    f["body5"] = sum(_win(bodies, i, 5, 0.0)) / 5
    f["green15"] = sum(_win([1.0 if c[k] > o[k] else 0.0 for k in range(i + 1)], i, 15, 0.0)) / 15
    zeros = [1.0 if v[k] <= 0 else 0.0 for k in range(i + 1)]
    f["zero15"] = sum(_win(zeros, i, 15, 0.0)) / 15
    f["zero60"] = sum(_win(zeros, i, 60, 0.0)) / 60
    now = ts[i] + dur[i]
    f["age_min_log"] = math.log1p(max(now - cn["created"], 0) / 60)
    f["grad_delay_log"] = math.log1p(max(cn["grad"] - cn["created"], 0))
    mcap = c[i] * 1e9
    f["mcap_log10"] = math.log10(max(mcap, 1e-9))
    f["dist_grad_level"] = math.log(max(mcap / sol_now, tiny) / 411.0)
    gi = next((k for k in range(i + 1) if ts[k] + dur[k] >= cn["grad"]), None)
    nanf = float("nan")
    if gi is None:
        for k in ("since_grad_log", "dd_hi_grad", "since_high_log", "rel_grad_close", "peak_rel_grad", "lv_grad"):
            f[k] = nanf
    else:
        f["since_grad_log"] = math.log1p(max(now - cn["grad"], 0) / 60)
        run, last_hi = -math.inf, gi
        for k in range(gi, i + 1):
            if lh[k] >= run:
                run, last_hi = lh[k], k
        f["dd_hi_grad"] = lc[i] - run
        f["since_high_log"] = math.log1p(i - last_hi)
        f["rel_grad_close"] = lc[i] - lc[gi]
        f["peak_rel_grad"] = run - lc[gi]
        f["lv_grad"] = math.log1p(sum(v[gi:i + 1]))
    lf = cn["launch"]
    f["has_twitter"] = float(bool(lf.get("has_twitter")))
    f["has_website"] = float(bool(lf.get("has_website")))
    f["has_telegram"] = float(bool(lf.get("has_telegram")))
    f["desc_len_log"] = math.log1p(float(lf.get("description_len") or 0))
    f["cashback"] = float(bool(lf.get("is_cashback_enabled")))
    f["token2022"] = float(lf.get("token_program") == TOKEN_2022)
    v10 = sum(v[max(0, i - 9):])
    return f, v10, gi


def gate_ok(f: dict, v10: float, mcap_sol: float, max_age_min=360.0, min_v10=1000.0, min_mcap_sol=30.0) -> bool:
    if math.isnan(f["since_grad_log"]):
        return False
    return math.expm1(f["since_grad_log"]) <= max_age_min and v10 >= min_v10 and mcap_sol >= min_mcap_sol


# ----------------------------------------------------------------------------- simulation
def simulate_exit(cn: dict, j0: int, tp: float, sl: float, hold_s: float, wick: str = "half",
                  rug_aware: bool = False) -> tuple[int, float, str]:
    """Exit bar, exit mid price and reason for a position bought at the OPEN of bar j0."""
    o, h, l, c, ts = cn["o"], cn["h"], cn["l"], cn["c"], cn["ts"]
    mid = o[j0]
    stop, tpp, tstop = mid * (1 - sl), mid * (1 + tp), ts[j0] + hold_s
    for j in range(j0, len(ts)):
        if j != j0:
            if o[j] <= stop:
                return j, o[j], "stop_gap"
            if ts[j] >= tstop:
                return j, o[j], "time_stop"
        if l[j] <= stop:
            lvl = min(stop, o[j])
            px = lvl if wick == "touch" else l[j] if wick == "worst" else (lvl + l[j]) / 2
            if rug_aware:
                px = min(px, max(c[j], l[j]))
            return j, px, "stop"
        if h[j] >= tpp:
            if o[j] >= tpp:
                px = o[j]
            elif wick == "touch" or c[j] >= tpp:
                px = tpp
            else:
                top = max(o[j], c[j])
                px = top if wick == "worst" else (tpp + top) / 2
            return j, px, "take_profit"
    return len(ts) - 1, c[-1], "end_of_data"


def execute(cn: dict, j0: int, sp: dict, costs: Costs, sol: Sol, wick: str = "half", rug_aware: bool = False,
            usd: float = 20.0) -> dict:
    """Buy ``usd`` at the open of bar j0, exit by the frozen rules, net of costs."""
    mid = cn["o"][j0]
    s0 = sol.at(cn["ts"][j0])
    tokens = costs.buy(usd, mid, s0)
    jx, px, why = simulate_exit(cn, j0, sp["tp"], sp["sl"], sp["hold_min"] * 60, wick, rug_aware)
    s1 = sol.at(cn["ts"][jx])
    back = costs.sell(tokens, px, s1)
    pnl = back - costs.network_usd(s1) - usd - costs.network_usd(s0)
    return {"entry_bar": j0, "entry_ts": float(cn["ts"][j0]), "entry_mid": float(mid),
            "entry_mcap_usd": float(mid * 1e9), "exit_bar": jx, "exit_ts": float(cn["ts"][jx]),
            "exit_mid": float(px), "exit_reason": why, "ret_pct": 100 * pnl / usd, "pnl_usd": pnl,
            "min_after_grad": (cn["ts"][j0] - cn["grad"]) / 60,
            "entry_bar_volume": float(cn["v"][j0]), "exit_bar_volume": float(cn["v"][jx]),
            "exit_bar_close": float(cn["c"][jx]), "exit_bar_low": float(cn["l"][jx])}


def frozen_params(q: float) -> dict:
    frozen = json.loads(FROZEN.read_text())
    return next(x for x in frozen["finalists"] if x["strategy_class"] == "F4Learned" and x["params"]["q"] == q)


def run(split: str, q: float, mints: list[str] | None = None, delay: int = 1, costs: Costs | None = None,
        wick: str = "half", rug_aware: bool = False, usd: float = 20.0, signals_only: bool = False,
        sol_shift_s: float = 0.0) -> dict:
    frozen = json.loads(FROZEN.read_text())
    fin = next(x for x in frozen["finalists"] if x["strategy_class"] == "F4Learned" and x["params"]["q"] == q)
    sp = fin["params"]["strategy"]
    ens = load_model(LAB / fin["params"]["model_file"][4:], fin["model_sha256"])
    sol = Sol(sol_shift_s)
    costs = costs or Costs()
    mints = mints or split_mints(split)
    trades, scored, n_univ = [], 0, 0
    for mint in mints:
        p = LAB / "coins" / f"{mint}.json"
        if not p.exists():
            continue
        cn = load_coin(mint)
        if not in_universe(cn):
            continue
        n_univ += 1
        n = len(cn["ts"])
        for i in range(n):
            now = cn["ts"][i] + cn["dur"][i]
            if now < cn["grad"]:
                continue
            if (now - cn["grad"]) / 60 > sp["max_age_min"] + 1:
                break
            s_now = sol.at(now)
            f, v10, gi = feature_row(cn, i, s_now)
            if not gate_ok(f, v10, cn["c"][i] * 1e9 / s_now, sp["max_age_min"], sp["min_vol10_usd"], sp["min_mcap_sol"]):
                continue
            if i + 1 >= n:
                break
            scored += 1
            score = model_score(ens, np.array([f[k] for k in NAMES]))
            if score <= sp["threshold"]:
                continue
            # one signal per coin; fill at the open of bar i + delay
            j0 = i + delay
            rec = {"mint": mint, "symbol": cn["symbol"], "decision_bar": i, "decision_ts": now, "score": score,
                   "features": {k: f[k] for k in NAMES}}
            if j0 < n and not signals_only:
                rec.update(execute(cn, j0, sp, costs, sol, wick, rug_aware, usd))
            trades.append(rec)
            break
    return {"split": split, "q": q, "threshold": sp["threshold"], "coins_in_universe": n_univ,
            "rows_scored": scored, "trades": trades}


def compare(path: Path) -> None:
    mine = json.loads(path.read_text())
    res = json.loads((LAB / "judge" / ("test_results.json" if mine["split"] == "test" else "validation_dryrun.json"))
                     .read_text())
    name = next(k for k in res["finalists"] if k.endswith(f"q{int(round(mine['q'] * 100))}"))
    judge = {t["mint"]: t for t in res["finalists"][name]["trades_per_coin"]}
    want = set(json.loads((LABDIR / "splits.json").read_text())[mine["split"]])
    mine_t = {t["mint"]: t for t in mine["trades"] if "entry_ts" in t}
    covered = [m for m in judge if m in mine_t or m in {t["mint"] for t in mine["trades"]}]
    print(f"{name}: judge {len(judge)} trades, independent {len(mine_t)} trades (coins in universe "
          f"{mine['coins_in_universe']}, rows scored {mine['rows_scored']})")
    worst = 0.0
    for m in sorted(set(judge) | set(mine_t), key=lambda m: (judge.get(m) or mine_t.get(m))["entry_ts"]):
        a, b = judge.get(m), mine_t.get(m)
        if a and b:
            d = abs(a["ret_pct"] - b["ret_pct"])
            worst = max(worst, d)
            same = a["entry_ts"] == b["entry_ts"] and a["exit_ts"] == b["exit_ts"] and a["exit_reason"] == b["exit_reason"]
            print(f"  {b['symbol']:10s} entry {a['entry_ts']:.0f}/{b['entry_ts']:.0f} exit {a['exit_reason']}/"
                  f"{b['exit_reason']} ret {a['ret_pct']:+.3f}/{b['ret_pct']:+.3f}  {'MATCH' if same and d < 0.01 else 'DIFF'}")
        else:
            print(f"  ONLY {'judge' if a else 'independent'}: {(a or b)['symbol']} {m}")
    print(f"  max |ret diff| on matched trades: {worst:.5f} pct points; covered {len(covered)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "compare"])
    ap.add_argument("arg")
    ap.add_argument("--q", type=float, default=0.98)
    ap.add_argument("--mints", default="")
    ap.add_argument("--delay", type=int, default=1)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if a.cmd == "compare":
        compare(Path(a.arg))
        return
    mints = [m for m in a.mints.split(",") if m] or None
    res = run(a.arg, a.q, mints, a.delay)
    OUT.mkdir(parents=True, exist_ok=True)
    out = Path(a.out) if a.out else OUT / f"indep_{a.arg}_q{int(round(a.q * 100))}{'_sub' if mints else ''}.json"
    out.write_text(json.dumps(res, indent=1))
    t = [x for x in res["trades"] if "ret_pct" in x]
    print(f"{a.arg} q={a.q}: {len(t)} trades, mean {np.mean([x['ret_pct'] for x in t]) if t else float('nan'):+.3f}% "
          f"-> {out}")


if __name__ == "__main__":
    sys.exit(main())
