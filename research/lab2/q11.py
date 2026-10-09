"""Q11: the value of speed (a measurement, not a strategy). For every recorded coin with a per-trade tape, a $20 buy
at graduation + L seconds held H seconds, after real costs and a priority tip, over a grid of L and H. Output: the
latency x hold surface of mean returns with coin-bootstrap CIs, the edge frontier per hold, the value of one minute
of latency, and a post-hoc breakdown by G1 class. Pre-registration: ``research/lab2/Q11/PREREG.md``.

Research only, TRAIN only (nothing is selected, so nothing is validated). Nothing here is wired into the bot.

    python research/lab2/q11.py --debug          # first 40 coins, counts only
    python research/lab2/q11.py --stage train
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import common as C  # noqa: E402
import g1 as G  # noqa: E402

VERSION = "q11-v1"
HYP = "Q11"
OUT_DIR = HERE / "Q11"
LATS = (1, 2, 5, 10, 20, 30, 60, 120, 300, 900)  # seconds after graduation
HOLDS = (5, 15, 30, 60, 120, 300, 900, 1800)  # seconds held
TIPS = (0.0, 0.001, 0.01)  # SOL per entry (priority / Jito tip)
PRIMARY_TIP = 0.001
SIZE_USD = 20.0
SLIP_S = 1.0  # stress: one second later on both fills
TOKEN_DECIMALS = 1e6


# =========================================================================== tape


@dataclass
class Tape:
    """Pool trades of one coin, oldest first: the pricing reserve X (SOL) and token reserve y (tokens) BEFORE each
    trade, plus the trade itself, so the state after any time can be reconstructed."""

    ts: np.ndarray  # float seconds
    X: np.ndarray  # SOL, pricing reserve before the trade (x0 + virtual)
    y: np.ndarray  # tokens before the trade
    is_buy: np.ndarray  # bool
    tok: np.ndarray  # tokens traded
    init_X: float
    init_y: float

    @classmethod
    def from_trades(cls, trades: pd.DataFrame, init_X: float, init_y: float) -> "Tape":
        p = trades[trades["venue"] == 1]
        p = p.sort_values(["ts", "slot", "tx_idx", "ix"], kind="stable")
        X = (p["x0"].to_numpy(np.float64) + p["virt_ksol"].to_numpy(np.float64) * 1000.0) / 1e9
        y = p["y0"].to_numpy(np.float64) / TOKEN_DECIMALS
        return cls(
            ts=p["ts"].to_numpy(np.float64),
            X=X,
            y=y,
            is_buy=p["is_buy"].to_numpy(bool),
            tok=p["tok"].to_numpy(np.float64) / TOKEN_DECIMALS,
            init_X=float(init_X),
            init_y=float(init_y),
        )

    @property
    def end(self) -> float:
        return float(self.ts[-1]) if len(self.ts) else float("-inf")

    def _after(self, i: int) -> tuple[float, float]:
        """State after trade i (constant product on the pricing reserve)."""
        X, y = float(self.X[i]), float(self.y[i])
        k = X * y
        y2 = y - float(self.tok[i]) if self.is_buy[i] else y + float(self.tok[i])
        if y2 <= 0 or not np.isfinite(y2):
            return X, y
        return k / y2, y2

    def state_at(self, t: float) -> tuple[float, float]:
        """(X, y) in force at time t: the reserves before the first trade after t; the initial pool state before any
        trade; the after-state of the last trade when t is past the tape."""
        if not len(self.ts):
            return self.init_X, self.init_y
        i = int(np.searchsorted(self.ts, t, side="right"))
        if i < len(self.ts):
            return float(self.X[i]), float(self.y[i])
        return self._after(len(self.ts) - 1)


# =========================================================================== one trade


def simulate_trade(
    tape: Tape,
    g: float,
    L: float,
    H: float,
    tip_sol: float,
    sol_usd: float,
    cost: C.CostModel | None = None,
    slip_s: float = 0.0,
    size_usd: float = SIZE_USD,
) -> dict | None:
    """Buy at g + L (+ slip), sell at g + L + H (+ slip); None when the exit lies past the tape (censored)."""
    cost = cost or C.CostModel()
    t_in, t_out = g + L + slip_s, g + L + H + slip_s
    if t_out > tape.end or not len(tape.ts):
        return None
    X, y = tape.state_at(t_in)
    if X <= 0 or y <= 0:
        return None
    p_in = X / y
    sol_in = size_usd / sol_usd
    tokens, br_in = C.simulate_buy(sol_in, p_in, X * y, t_in, cost)
    if tokens <= 0:
        return None
    Xe, ye = tape.state_at(t_out)
    if Xe <= 0 or ye <= 0:
        return None
    p_out = Xe / ye
    sol_out, br_out = C.simulate_sell(tokens, p_out, Xe * ye, t_out, cost)
    net = 2 * C.network_sol(cost)
    ret = (sol_out - sol_in - net - tip_sol) / sol_in
    return {
        "L": L,
        "H": H,
        "tip": tip_sol,
        "slip_s": slip_s,
        "t_in": t_in,
        "t_out": t_out,
        "p_in": p_in,
        "p_out": p_out,
        "ret_mid": p_out / p_in - 1.0,
        "ret_net": ret,
        "sol_in": sol_in,
        "mcap_in_sol": p_in * C.TOKEN_SUPPLY,
        "fee_bps_in": br_in["fee_bps"],
        "fee_bps_out": br_out["fee_bps"],
        "depth_in_sol": X,
    }


# =========================================================================== the study


def coin_class(ds: C.Dataset, m: str, cd: C.CoinData) -> str:
    try:
        snap = ds.asof(m, cd.g + 1800.0 + C.DECISION_LAG_S)
        return str(G.classify(G.g1_features(snap, None))["g1_class"])
    except Exception:  # noqa: BLE001 (diagnostic only)
        return "UNKNOWN"


def run_rows(
    ds: C.Dataset,
    tips=TIPS,
    lats=LATS,
    holds=HOLDS,
    slips=(0.0, SLIP_S),
    max_coins: int | None = None,
    cost: C.CostModel | None = None,
) -> pd.DataFrame:
    rows: list[dict] = []
    n_coins = n_tape = 0
    for m in ds.mints:
        cd = ds.coin(m)
        if cd.trades is None or not len(cd.trades):
            continue
        n_coins += 1
        if max_coins and n_coins > max_coins:
            break
        tape = Tape.from_trades(cd.trades, cd.init_X, cd.init_y)
        if not len(tape.ts):
            continue
        n_tape += 1
        sol_usd = float(ds.asof(m, cd.g + 1800.0 + C.DECISION_LAG_S).sol_usd)
        cls = coin_class(ds, m, cd)
        for slip in slips:
            for L in lats:
                for H in holds:
                    for tip in tips:
                        r = simulate_trade(tape, cd.g, L, H, tip, sol_usd, cost, slip)
                        if r is None:
                            rows.append(
                                {"mint": m, "L": L, "H": H, "tip": tip, "slip_s": slip, "censored": True, "cls": cls}
                            )
                            continue
                        rows.append({"mint": m, "cls": cls, "censored": False, **r})
    return pd.DataFrame(rows)


def _ci(r: np.ndarray, coins: np.ndarray, B: int) -> tuple[float, float] | None:
    return C.coin_bootstrap_ci(r, coins, 0.95, B)


def summarize(rows: pd.DataFrame, B: int = 2000, hide: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "n_coins": int(rows["mint"].nunique()),
        "cells": {},
        "frontier": {},
        "value_of_speed": {},
        "by_class": {},
        "tips": list(TIPS),
        "primary_tip": PRIMARY_TIP,
    }
    if hide:
        out["counts"] = {
            f"L{L}|H{H}": int(
                ((rows.L == L) & (rows.H == H) & (rows.tip == PRIMARY_TIP) & (rows.slip_s == 0) & ~rows.censored).sum()
            )
            for L in LATS
            for H in HOLDS
        }
        out["returns"] = "hidden (debug)"
        return out
    base = rows[~rows.censored]
    for tip in TIPS:
        for slip in sorted(rows.slip_s.unique()):
            sub = base[(base.tip == tip) & (base.slip_s == slip)]
            for L in LATS:
                for H in HOLDS:
                    c = sub[(sub.L == L) & (sub.H == H)]
                    key = f"tip{tip}|slip{int(slip)}|L{L}|H{H}"
                    if not len(c):
                        out["cells"][key] = {"n": 0}
                        continue
                    r = c["ret_net"].to_numpy(float)
                    out["cells"][key] = {
                        "n": int(len(c)),
                        "mean": float(r.mean()),
                        "median": float(np.median(r)),
                        "ci95": _ci(r, c["mint"].to_numpy(object), B),
                        "share_pos": float((r > 0).mean()),
                        "mean_ret_mid": float(c["ret_mid"].mean()),
                        "mean_mcap_in_sol": float(c["mcap_in_sol"].mean()),
                        "censored": int(
                            (
                                (rows.L == L)
                                & (rows.H == H)
                                & (rows.tip == tip)
                                & (rows.slip_s == slip)
                                & rows.censored
                            ).sum()
                        ),
                    }
    prim = base[(base.tip == PRIMARY_TIP) & (base.slip_s == 0)]
    for H in HOLDS:
        best = None
        for L in LATS:
            cell = out["cells"].get(f"tip{PRIMARY_TIP}|slip0|L{L}|H{H}") or {}
            ci = cell.get("ci95")
            if cell.get("n", 0) >= 30 and (cell.get("mean") or 0) > 0 and ci and ci[0] > 0:
                best = L
        out["frontier"][f"H{H}"] = best
        a = prim[(prim.L == 1) & (prim.H == H)].set_index("mint")["ret_net"]
        b = prim[(prim.L == 60) & (prim.H == H)].set_index("mint")["ret_net"]
        both = a.index.intersection(b.index)
        if len(both) >= 30:
            d = (a.loc[both] - b.loc[both]).to_numpy(float)
            out["value_of_speed"][f"H{H}"] = {
                "n": int(len(both)),
                "mean_diff_1s_vs_60s": float(d.mean()),
                "ci95": _ci(d, both.to_numpy(object), B),
            }
    for cls, grp in prim.groupby("cls"):
        out["by_class"][cls] = {
            f"L{L}|H{H}": {"n": int(len(c)), "mean": float(c["ret_net"].mean())}
            for (L, H), c in grp.groupby(["L", "H"])
            if (L, H) in ((1, 60), (5, 60), (30, 60), (1, 300), (30, 300), (60, 1800))
        }
    return out


# =========================================================================== report


def _pct(x: Any) -> str:
    return "n/a" if x is None else f"{100 * x:+.1f}%"


def render_md(doc: Mapping[str, Any]) -> str:
    s = doc["summary"]
    L_ = [
        f"# Q11 {doc['stage']}: the value of speed",
        "",
        f"- Split `{doc['split']}`; coins with a pool tape: {s['n_coins']}; written {doc['utc']} UTC; runtime "
        f"{doc['runtime_s']} s; PREREG sha256 `{doc['prereg_sha256'][:12]}`; "
        f"trials in the ledger: {doc.get('n_trials_total')}.",
        "",
    ]
    if doc.get("debug_only"):
        L_ += [
            "**Debug: counts only, returns hidden.**",
            "",
            f"- cells (coins with an uncensored trade): {s['counts']}",
            "",
        ]
        return "\n".join(L_)
    for tip in TIPS:
        L_ += [
            f"## Mean net return, tip {tip} SOL, exact fills (rows: latency L after graduation; columns: hold H)",
            "",
            "| L \\ H | " + " | ".join(f"{H}s" for H in HOLDS) + " |",
            "|---|" + "---:|" * len(HOLDS),
        ]
        for L in LATS:
            cells = [s["cells"].get(f"tip{tip}|slip0|L{L}|H{H}") or {} for H in HOLDS]
            L_.append(
                f"| {L}s | "
                + " | ".join(
                    f"{_pct(c.get('mean'))} [{_pct((c.get('ci95') or (None, None))[0])}, "
                    f"{_pct((c.get('ci95') or (None, None))[1])}] n{c.get('n', 0)}"
                    if c.get("n")
                    else "-"
                    for c in cells
                )
                + " |"
            )
        L_.append("")
    L_ += [
        "## One second slower (tip 0.001 SOL, fills one second late)",
        "",
        "| L \\ H | " + " | ".join(f"{H}s" for H in HOLDS) + " |",
        "|---|" + "---:|" * len(HOLDS),
    ]
    for L in LATS:
        cells = [s["cells"].get(f"tip{PRIMARY_TIP}|slip1|L{L}|H{H}") or {} for H in HOLDS]
        L_.append(f"| {L}s | " + " | ".join(_pct(c.get("mean")) if c.get("n") else "-" for c in cells) + " |")
    L_ += [
        "",
        "## Readings (PREREG 3, tip 0.001 SOL)",
        "",
        f"- Edge frontier (largest L with mean > 0 and CI95 > 0, n >= 30), per hold: {s['frontier']}",
        "- Value of one minute of latency (mean return at 1 s minus at 60 s, paired by coin):",
    ]
    for k, v in s["value_of_speed"].items():
        L_.append(
            f"  - {k}: {_pct(v['mean_diff_1s_vs_60s'])} CI95 [{_pct(v['ci95'][0]) if v['ci95'] else 'n/a'}, "
            f"{_pct(v['ci95'][1]) if v['ci95'] else 'n/a'}] (n {v['n']})"
        )
    L_ += ["- By G1 class (post hoc, diagnostic):"]
    for cls, d in s["by_class"].items():
        L_.append(f"  - {cls}: " + ", ".join(f"{k} {_pct(v['mean'])} (n{v['n']})" for k, v in d.items()))
    L_.append("")
    return "\n".join(L_)


# =========================================================================== CLI


def run(
    stage: str,
    *,
    out_dir: Path = OUT_DIR,
    ds: C.Dataset | None = None,
    B: int = 2000,
    ledger_path: Path | None = None,
    max_coins: int | None = None,
) -> dict:
    t0 = time.time()
    debug = stage == "debug"
    split = "final_train" if debug else "train"
    prereg = out_dir / "PREREG.md"
    if not prereg.exists():
        raise RuntimeError(f"{prereg} missing: pre-register before any run")
    if ds is None:
        ds = C.load(split)
    rows = run_rows(ds, max_coins=max_coins or (40 if debug else None))
    summary = summarize(rows, B=B, hide=debug)
    n_tr = None
    if not debug:
        for L in LATS:
            for H in HOLDS:
                info = C.record_run(
                    HYP,
                    {"version": VERSION, "L": L, "H": H, "tip": PRIMARY_TIP, "kind": "measurement"},
                    split,
                    {
                        "n": summary["cells"][f"tip{PRIMARY_TIP}|slip0|L{L}|H{H}"].get("n", 0),
                        "mean": summary["cells"][f"tip{PRIMARY_TIP}|slip0|L{L}|H{H}"].get("mean"),
                    },
                    ledger_path,
                    debug=False,
                    kind="measurement",
                )
                n_tr = info.get("n_trials_total")
    doc = {
        "hypothesis": HYP,
        "version": VERSION,
        "stage": stage,
        "split": split,
        "debug_only": debug,
        "utc": C.utc_str(time.time()),
        "prereg_sha256": C.hashlib.sha256(prereg.read_bytes()).hexdigest(),
        "n_rows": int(len(rows)),
        "summary": summary,
        "n_trials_total": n_tr,
        "runtime_s": round(time.time() - t0, 1),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{stage}.json").write_text(json.dumps(doc, indent=1, default=str))
    (out_dir / f"{stage}.md").write_text(render_md(doc))
    if not debug:
        rows.to_parquet(out_dir / "train_rows.parquet", index=False)
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Q11 the value of speed; see research/lab2/Q11/PREREG.md")
    ap.add_argument("--stage", choices=("train",))
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--B", type=int, default=2000)
    a = ap.parse_args(argv)
    if not a.stage and not a.debug:
        ap.error("--stage train or --debug")
    doc = run("debug" if a.debug else a.stage, B=a.B)
    print(f"wrote {OUT_DIR}/{doc['stage']}.json and .md; frontier: {doc['summary'].get('frontier')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
