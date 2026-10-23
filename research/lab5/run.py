"""Lab 5 stages (research/lab5/PLAN.md): the crypto price-market specialist.

* ``inventory``: the crypto price markets of lab 4's cache by type, underlying, horizon, resolution source and split,
  and how many have usable prints (no return is computed). Writes ``inventory.json`` / ``inventory.md``.
* ``structure`` (TRAIN only, no return computed): the settlement replicated from Binance against the venue's
  outcome, the Chainlink basis (``priceToBeat`` / ``finalPrice`` against the Binance proxy; its residual sd is the
  model's basis noise), and the timing of print prices against spot. Writes ``structure.json`` / ``structure.md``.
* ``train`` (every cell of S1-S3, shortlist one per hypothesis), ``val`` (the shortlist, placebo, latency stress,
  selection), ``test`` (the selected cell, one look, refuses without ``LAB5_ALLOW_TEST=1``). Each writes
  ``<HYP>/<stage>.json`` and ``.md`` and refreshes ``RESULTS.md``.

CLI::

    python research/lab5/run.py --stage inventory
    python research/lab5/run.py --stage structure
    python research/lab5/run.py --stage train
    python research/lab5/run.py --stage val
    LAB5_ALLOW_TEST=1 python research/lab5/run.py --stage test
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing as mp
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import core as C
import numpy as np
import pandas as pd

import data as D

HERE = Path(__file__).resolve().parent
PLAN = HERE / "PLAN.md"
STRUCTURE = HERE / "structure.json"
PLAN_VERSION = "lab5-v1"
MIN_N = 100
PLACEBO_PCT = 95.0

# PLAN §3: the grid. Margins and windows per hypothesis; vol windows in seconds (primary first).
HYPOTHESES: dict[str, dict[str, Any]] = {
    "S1": {
        "title": "threshold / range at a Binance close (above, below, between)",
        "kind": "terminal",
        "margins": [0.02, 0.05, 0.10],
        "windows": ["near", "far"],
        "vols": [86400, 7 * 86400],
    },
    "S2": {
        "title": "up-or-down windows (5m, 15m, 1h, 4h, 1d)",
        "kind": "window",
        "margins": [0.02, 0.05, 0.10],
        "windows": ["early", "late"],
        "vols": [3600, 86400],
    },
    "S3": {
        "title": "touch: reach / dip to a barrier inside a period",
        "kind": "touch",
        "margins": [0.02, 0.05, 0.10],
        "windows": ["near", "far"],
        "vols": [86400, 7 * 86400],
    },
}

_SPOTS: dict[str, C.Spot] = {}
_CTX: dict[str, Any] = {}


def prereg_sha256() -> str:
    return hashlib.sha256(PLAN.read_bytes()).hexdigest() if PLAN.exists() else "none"


def cell_key(margin: float, window: str, vol_s: int) -> str:
    vol = f"{vol_s // 86400}d" if vol_s % 86400 == 0 else f"{vol_s // 3600}h"
    return f"m{margin:g}|{window}|vol{vol}"


def basis_sd() -> float:
    """The Chainlink basis noise measured by the structure stage on TRAIN (PLAN §2); 0 before it exists."""
    if STRUCTURE.exists():
        return float(json.loads(STRUCTURE.read_text()).get("basis", {}).get("sigma_b") or 0.0)
    return 0.0


# --------------------------------------------------------------------------------------------- universe


def load_tape(path: Path) -> pd.DataFrame:
    """Lab 4's tape transformation: valid prints only, the price of outcome 0 and whether the print was BUYABLE for
    outcome 0 (a BUY on token 0 or a SELL on token 1; lab 4 Amendment 3)."""
    t = pd.read_parquet(path, columns=["ts", "price", "size", "side", "outcome_index"])
    t = t[(t["ts"] > 0) & (t["price"] > 0) & (t["price"] < 1) & t["outcome_index"].isin([0, 1])]
    oi = t["outcome_index"].to_numpy()
    side = t["side"].astype(str).str.upper().to_numpy()
    p0 = np.where(oi == 0, t["price"].to_numpy(), 1.0 - t["price"].to_numpy())
    buy0 = ((oi == 0) & (side == "BUY")) | ((oi == 1) & (side == "SELL"))
    return (
        pd.DataFrame({"ts": t["ts"].to_numpy(), "p0": p0, "buy0": buy0, "size": t["size"].to_numpy()})
        .sort_values("ts", kind="stable")
        .reset_index(drop=True)
    )


def _cluster(contract: dict[str, Any]) -> str:
    """PLAN §4 bootstrap clusters: one price draw settles every bet in a cluster."""
    if contract["kind"] == "terminal":
        return "T:" + C.et_day(contract["t_final"] - 61)
    if contract["kind"] == "touch":
        return "X:" + C.et_day(contract["p1"] - 1)
    return "W:" + datetime.fromtimestamp(contract["t_final"] - 1, UTC).strftime("%Y-%m-%dT%H")


def catalogue(lab4: Path = D.LAB4, lab5: Path = D.OUT) -> pd.DataFrame:
    """Every crypto-family market of lab 4 with its rules, contract and split (no tape read)."""
    m = pd.read_parquet(lab4 / "markets.parquet")
    m = m[m["fee_type"].fillna("").str.startswith("crypto")].copy()
    rules = pd.read_parquet(lab5 / "rules.parquet")
    m = m.merge(rules, on="id", how="left")
    rows = []
    for r in m.to_dict("records"):
        c = C.parse_market(r)
        rows.append(
            {
                "id": r["id"],
                "question": r["question"],
                "kind": c.get("kind"),
                "why": c.get("why"),
                "symbol": c.get("symbol"),
                "source": c.get("source"),
                "sub": c.get("sub") or c.get("op"),
                "contract": json.dumps(c) if c.get("kind") else "",
                "winner": int(r["winner_index"]),
                "n_outcomes": int(r["n_outcomes"]),
                "closed_time": float(r["closed_time"]),
                "end_date": float(r["end_date"]) if r["end_date"] is not None and not pd.isna(r["end_date"]) else None,
                "start_date": float(r["start_date"]) if r["start_date"] is not None and not pd.isna(r["start_date"]) else None,
                "rate": C.fee_rate(r["fee_type"], bool(r["fees_enabled"])),
                "split": C.split_of(float(r["closed_time"])),
                "volume": float(r["volume"]),
                "price_to_beat": r.get("price_to_beat"),
                "final_price": r.get("final_price"),
                "has_rules": isinstance(r.get("description"), str) and bool(r.get("description")),
            }
        )
    return pd.DataFrame(rows)


def horizon_label(row: dict[str, Any], c: dict[str, Any]) -> str:
    if c["kind"] == "window":
        return c["sub"]
    if c["kind"] == "touch":
        days = (c["p1"] - c["p0"]) / 86400.0
        return "day" if days <= 1.01 else ("week" if days <= 7.01 else "month")
    return "1h close" if "PM ET?" in row["question"] or "AM ET?" in row["question"] else "noon ET close"


def to_market(row: dict[str, Any]) -> C.Market:
    c = json.loads(row["contract"])
    return C.Market(
        id=row["id"],
        contract=c,
        winner=int(row["winner"]),
        closed_time=float(row["closed_time"]),
        end_date=float(row["end_date"] or row["closed_time"]),
        rate=float(row["rate"]),
        cluster=_cluster(c),
        split=row["split"],
    )


def load_spots(symbols: list[str], out: Path = D.OUT) -> dict[str, C.Spot]:
    spots = {}
    for s in symbols:
        files = sorted((out / "spot" / s).glob("*.parquet"))
        if not files:
            continue
        df = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)
        spots[s] = C.Spot.from_frame(s, df)
        del df
    return spots


# --------------------------------------------------------------------------------------------- per-market worker


def _work(row: dict[str, Any]) -> dict[str, Any]:
    """One market: candidates, every cell's first entry (with settlement, latency stress and US re-costing), and one
    diagnostic print per entry window for the Brier comparison."""
    hyp = _CTX["hyp_of"][row["kind"]]
    h = HYPOTHESES[hyp]
    m = to_market(row)
    spot = _SPOTS[m.contract["symbol"]]
    tape = load_tape(D.LAB4 / "trades" / f"{m.id}.parquet")
    if len(tape) < C.MIN_FILLS:
        return {"id": m.id, "skip": "fewer than 50 fills", "trades": [], "diag": []}
    cand = C.market_candidates(m, tape, spot, h["vols"], _CTX["basis_sd"], _CTX["lag_s"])
    trades, diag = [], []
    sub = m.contract.get("sub") or m.contract.get("op")
    for w in h["windows"]:
        mask = C.entry_mask(cand, m, w, _CTX["lag_s"])
        qprim = f"q{h['vols'][0]}"
        ok = mask & np.isfinite(cand[qprim].to_numpy())
        if ok.any():
            i = int(np.argmax(ok))
            side = int(cand["side"].iat[i])
            diag.append(
                {
                    "id": m.id,
                    "window": w,
                    "q_side": float(cand[qprim].iat[i]),
                    "p_side": float(cand["p_print"].iat[i]),
                    "won": int(m.winner == side),
                    "sub": sub,
                }
            )
        for vol in h["vols"]:
            qcol = f"q{vol}"
            for margin in h["margins"]:
                i = C.first_entries(cand, mask, qcol, margin)
                if i is None:
                    continue
                side = int(cand["side"].iat[i])
                p_x = float(cand["p_x"].iat[i])
                s = C.settle(m, side, p_x)
                us = C.settle(m, side, p_x, rate=C.US_RATE)
                j = C.latency_exec(cand, i)
                lat = None
                if j is not None:
                    lat = C.settle(m, side, float(cand["p_x"].iat[j]))["net"]
                trades.append(
                    {
                        "id": m.id,
                        "cell": cell_key(margin, w, vol),
                        "cluster": m.cluster,
                        "sub": sub,
                        "symbol": m.contract.get("symbol"),
                        "t_entry": int(cand["ts"].iat[i]),
                        "tau_s": float(cand["tau"].iat[i]),
                        "side": side,
                        "p_print": float(cand["p_print"].iat[i]),
                        "p_x": p_x,
                        "q": float(cand[qcol].iat[i]),
                        "fee_ps": float(cand["fee_ps"].iat[i]),
                        **s,
                        "us_net": us["net"],
                        "lat_net": lat,
                    }
                )
    return {"id": m.id, "skip": None, "trades": trades, "diag": diag}


def _init(ctx: dict[str, Any]) -> None:
    _CTX.update(ctx)


def run_markets(rows: list[dict[str, Any]], spots: dict[str, C.Spot], lag_s: int, bsd: float, procs: int = 4) -> list[dict[str, Any]]:
    _SPOTS.clear()
    _SPOTS.update(spots)
    ctx = {"hyp_of": {h["kind"]: k for k, h in HYPOTHESES.items()}, "basis_sd": bsd, "lag_s": lag_s}
    _init(ctx)
    if procs <= 1:
        return [_work(r) for r in rows]
    with mp.get_context("fork").Pool(procs, initializer=_init, initargs=(ctx,)) as pool:
        return list(pool.imap(_work, rows, chunksize=64))


# --------------------------------------------------------------------------------------------- inventory


def universe(cat: pd.DataFrame, split: str | None = None) -> pd.DataFrame:
    """PLAN §1 universe: binary, single winner, a parsed contract on BTC / ETH / SOL / XRP, a split."""
    u = cat[(cat["n_outcomes"] == 2) & cat["winner"].isin([0, 1]) & cat["kind"].notna() & cat["symbol"].isin(list(D.SYMBOLS)) & cat["split"].notna()]
    return u[u["split"] == split] if split else u


def _inv_work(row: dict[str, Any]) -> tuple[str, int, int]:
    """Fills in the tape and buyable prints inside an entry window with a model value (primary vol); no return."""
    m = to_market(row)
    h = HYPOTHESES[_CTX["hyp_of"][m.contract["kind"]]]
    p = D.LAB4 / "trades" / f"{m.id}.parquet"
    if not p.exists():
        return (m.id, 0, 0)
    tape = load_tape(p)
    cand = C.market_candidates(m, tape, _SPOTS[m.contract["symbol"]], [h["vols"][0]], 0.0, _CTX["lag_s"])
    q = np.isfinite(cand[f"q{h['vols'][0]}"].to_numpy())
    n_win = 0
    for w in h["windows"]:
        n_win = max(n_win, int((C.entry_mask(cand, m, w, _CTX["lag_s"]) & q).sum()))
    return (m.id, len(tape), n_win)


def stage_inventory(here: Path = HERE, procs: int = 4) -> dict[str, Any]:
    cat = catalogue()
    u = universe(cat)
    lag = int(json.loads(STRUCTURE.read_text())["lag_s"]) if STRUCTURE.exists() else C.LAG_S
    _SPOTS.clear()
    _SPOTS.update(load_spots(sorted(u["symbol"].dropna().unique())))
    ctx = {"hyp_of": {h["kind"]: k for k, h in HYPOTHESES.items()}, "basis_sd": 0.0, "lag_s": lag}
    _init(ctx)
    with mp.get_context("fork").Pool(procs, initializer=_init, initargs=(ctx,)) as pool:
        res = list(pool.imap(_inv_work, u.to_dict("records"), chunksize=64))
    usable = {i: (f, w) for i, f, w in res}
    u = u.assign(
        fills=[usable[i][0] for i in u["id"]],
        in_window=[usable[i][1] for i in u["id"]],
    )
    u = u.assign(usable=(u["fills"] >= C.MIN_FILLS) & (u["in_window"] > 0))
    u["horizon"] = [horizon_label(r, json.loads(r["contract"])) for r in u.to_dict("records")]
    excluded = cat[~cat["id"].isin(u["id"])]
    why = excluded.assign(
        reason=np.where(
            excluded["kind"].isna(),
            excluded["why"].fillna("unparsed"),
            np.where(
                ~excluded["symbol"].isin(list(D.SYMBOLS)),
                "underlying not on the Binance list",
                np.where(excluded["split"].isna(), "closed after 2026-10-08 (shadow set)", "split resolution / not binary"),
            ),
        )
    )
    hyp_of = {h["kind"]: k for k, h in HYPOTHESES.items()}
    u["hyp"] = u["kind"].map(hyp_of)
    table = (
        u.groupby(["hyp", "kind", "sub", "symbol", "source", "horizon", "split"])
        .agg(markets=("id", "size"), usable=("usable", "sum"))
        .reset_index()
    )
    per_hyp = u.groupby(["hyp", "split"]).agg(markets=("id", "size"), usable=("usable", "sum")).reset_index()
    doc = {
        "utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "crypto_family_markets": len(cat),
        "with_rules": int(cat["has_rules"].sum()),
        "universe": len(u),
        "usable": int(u["usable"].sum()),
        "per_hyp": per_hyp.to_dict("records"),
        "table": table.to_dict("records"),
        "excluded": why["reason"].value_counts().to_dict(),
        "excluded_examples": {k: g["question"].head(3).tolist() for k, g in why.groupby("reason")},
        "lag_s": lag,
    }
    (here / "inventory.json").write_text(json.dumps(doc, indent=1, sort_keys=True, default=str) + "\n")
    lines = [
        "# Lab 5 inventory: crypto price markets in lab 4's cache",
        "",
        f"Run {doc['utc']}. Crypto-family markets in lab 4's cache: {doc['crypto_family_markets']} "
        f"(Gamma rules fetched for {doc['with_rules']}). In the lab 5 universe (binary, one winner, a parsed price "
        f"contract on BTC / ETH / SOL / XRP, closed 2026-07-01 .. 2026-10-08): {doc['universe']}; usable "
        f"(>= {C.MIN_FILLS} fills and >= 1 buyable print inside an entry window with a model value): {doc['usable']}.",
        "",
        "## Per hypothesis and split",
        "",
        "| hyp | split | markets | usable |",
        "|---|---|---|---|",
    ]
    for r in doc["per_hyp"]:
        lines.append(f"| {r['hyp']} | {r['split']} | {r['markets']} | {r['usable']} |")
    lines += ["", "## By type, underlying, horizon and resolution source", "", "| hyp | kind | type | underlying | source | horizon | split | markets | usable |", "|---|---|---|---|---|---|---|---|---|"]
    for r in doc["table"]:
        lines.append(
            f"| {r['hyp']} | {r['kind']} | {r['sub']} | {r['symbol']} | {r['source']} | {r['horizon']} | {r['split']} | {r['markets']} | {r['usable']} |"
        )
    lines += ["", "## Excluded crypto-family markets", "", "| reason | markets | example |", "|---|---|---|"]
    for k, v in sorted(doc["excluded"].items(), key=lambda kv: -kv[1]):
        ex = (doc["excluded_examples"].get(k) or [""])[0]
        lines.append(f"| {k} | {v} | {ex} |")
    lines.append("")
    (here / "inventory.md").write_text("\n".join(lines))
    return doc


# --------------------------------------------------------------------------------------------- structure


def stage_structure(here: Path = HERE, lags: tuple[int, ...] = (-10, -5, -2, 0, 2, 5, 10, 20, 30)) -> dict[str, Any]:
    """TRAIN only, no return computed (PLAN §2): replication, Chainlink basis, print timing vs spot."""
    cat = catalogue()
    u = universe(cat, "train")
    spots = load_spots(sorted(u["symbol"].dropna().unique()))
    rep: dict[str, dict[str, int]] = {}
    basis_rows = []
    for r in u.to_dict("records"):
        m = to_market(r)
        c = m.contract
        sp = spots[c["symbol"]]
        y = C.outcome_event(m, sp)
        venue_event = int(m.winner == c["event_outcome"])
        key = f"{c['kind']}:{c.get('sub') or c.get('op')}:{c['source']}"
        d = rep.setdefault(key, {"n": 0, "match": 0, "unreplicable": 0})
        if y is None:
            d["unreplicable"] += 1
        else:
            d["n"] += 1
            d["match"] += int(y == venue_event)
        if c["kind"] == "window" and c["ref_rule"] == "chainlink":
            fin = r.get("final_price")
            ref = c["ref_value"]
            proxy_t0, proxy_T = C.window_ref_final_binance(c, sp)
            meta_event = int(fin >= ref) if fin is not None and not pd.isna(fin) else None
            basis_rows.append(
                {
                    "sub": c["sub"],
                    "twap_s": c["twap_s"],
                    "meta_match": None if meta_event is None else int(meta_event == venue_event),
                    "e_final": math.log(fin / (ref / proxy_t0 * proxy_T)) if fin and proxy_t0 > 0 and proxy_T > 0 else None,
                    "e_ref": math.log(ref / proxy_t0) if proxy_t0 > 0 else None,
                }
            )
    b = pd.DataFrame(basis_rows)
    e = b["e_final"].dropna().to_numpy() if len(b) else np.array([])
    basis = {
        "n_windows": int(len(b)),
        "meta_match_rate": float(b["meta_match"].dropna().mean()) if len(b) else None,
        "sigma_b": float(np.std(e)) if len(e) else 0.0,
        "e_final_quantiles": {str(qq): float(np.quantile(e, qq)) for qq in (0.01, 0.05, 0.5, 0.95, 0.99)} if len(e) else {},
        "ref_basis_median": float(b["e_ref"].dropna().median()) if len(b) else None,
        "ref_basis_sd": float(b["e_ref"].dropna().std()) if len(b) else None,
    }
    # Timing: how old is the information in a print price? For TRAIN windows, the mean squared gap between the
    # print's price of outcome 0 and the model's value of outcome 0 with spot read at ts - k, for each k.
    rng = np.random.default_rng(0)
    w = u[u["kind"] == "window"]
    pick = w.iloc[rng.permutation(len(w))[:3000]]
    timing: dict[str, list[float]] = {}
    for r in pick.to_dict("records"):
        m = to_market(r)
        sp = spots[m.contract["symbol"]]
        p = D.LAB4 / "trades" / f"{m.id}.parquet"
        if not p.exists():
            continue
        tape = load_tape(p)
        ts = tape["ts"].to_numpy(dtype=np.int64)
        inside = (ts - 30 >= m.contract["ref_known"]) & (ts + 30 < m.contract["t_final"])
        if inside.sum() < 5:
            continue
        p0 = tape["p0"].to_numpy()[inside]
        for k in lags:
            q = C.q_event(m, sp, ts[inside] - k, 3600, basis["sigma_b"])
            ok = np.isfinite(q)
            if ok.any():
                timing.setdefault(str(k), []).append(float(np.mean((p0[ok] - q[ok]) ** 2)))
    timing_mse = {k: float(np.mean(v)) for k, v in timing.items()}
    best_k = int(min(timing_mse, key=lambda k: timing_mse[k])) if timing_mse else 0
    lag_s = max(C.LAG_S, best_k + 5)
    doc = {
        "utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "split": "train",
        "replication": {k: {**v, "rate": (v["match"] / v["n"]) if v["n"] else None} for k, v in sorted(rep.items())},
        "basis": basis,
        "timing_mse_by_k": timing_mse,
        "timing_best_k": best_k,
        "timing_markets": int(len(next(iter(timing.values()), []))),
        "lag_s": int(lag_s),
    }
    STRUCTURE.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    lines = [
        "# Lab 5 structure checks (TRAIN only; no return computed)",
        "",
        f"Run {doc['utc']}.",
        "",
        "## Settlement replicated from Binance 1 s klines vs the venue's outcome",
        "",
        "| contract | replicated | match rate | not replicable |",
        "|---|---|---|---|",
    ]
    for k, v in doc["replication"].items():
        rate = "-" if v["rate"] is None else f"{100 * v['rate']:.2f} %"
        lines.append(f"| {k} | {v['n']} | {rate} | {v['unreplicable']} |")
    meta = "-" if basis["meta_match_rate"] is None else f"{100 * basis['meta_match_rate']:.2f} %"
    quant = json.dumps({k: round(v, 6) for k, v in basis["e_final_quantiles"].items()})
    lines += [
        "",
        "Chainlink rows replicate with the BINANCE PROXY (the basis error rate); the bets settle on the venue's outcome.",
        "",
        "## Chainlink basis (5m / 15m / 4h windows)",
        "",
        f"Windows {basis['n_windows']}; venue outcome = (finalPrice >= priceToBeat) in "
        f"{meta} of them. "
        f"Residual log basis of the final value after scaling Binance by priceToBeat / Binance-at-open: sd "
        f"{basis['sigma_b']:.6f} (quantiles {quant}); "
        f"Chainlink / Binance at the open: median {basis['ref_basis_median']}, sd {basis['ref_basis_sd']}.",
        "",
        "## Print timing against spot",
        "",
        "Mean squared gap between a print's price of outcome 0 and the model value of outcome 0 with spot read k seconds "
        f"before the print timestamp ({doc['timing_markets']} TRAIN windows, primary vol):",
        "",
        "| k (s) | MSE |",
        "|---|---|",
    ]
    for k in sorted(timing_mse, key=int):
        lines.append(f"| {k} | {timing_mse[k]:.5f} |")
    lines += ["", f"Best k = {best_k} s; decision lag LAG_S = max(10, best k + 5) = {lag_s} s (PLAN §2).", ""]
    (here / "structure.md").write_text("\n".join(lines))
    return doc


# --------------------------------------------------------------------------------------------- stages


def _trades_frame(results: list[dict[str, Any]]) -> pd.DataFrame:
    rows = [t for r in results for t in r["trades"]]
    return pd.DataFrame(rows)


def evaluate_split(split: str, hyps: list[str], procs: int = 4) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    C.check_split_allowed(split)
    cat = catalogue()
    u = universe(cat, split)
    kinds = [HYPOTHESES[h]["kind"] for h in hyps]
    u = u[u["kind"].isin(kinds)]
    st = json.loads(STRUCTURE.read_text())
    spots = load_spots(sorted(u["symbol"].dropna().unique()))
    res = run_markets(u.to_dict("records"), spots, int(st["lag_s"]), float(st["basis"]["sigma_b"]), procs)
    trades = _trades_frame(res)
    diag = pd.DataFrame([d for r in res for d in r["diag"]])
    cov = {
        "markets": int(len(u)),
        "evaluated": int(sum(1 for r in res if r["skip"] is None)),
        "skipped_few_fills": int(sum(1 for r in res if r["skip"])),
        "by_kind": u["kind"].value_counts().to_dict(),
    }
    if len(trades):
        hyp_of = {h["kind"]: k for k, h in HYPOTHESES.items()}
        kind_of = dict(zip(u["id"], u["kind"], strict=True))
        trades["hyp"] = trades["id"].map(kind_of).map(hyp_of)
    if len(diag):
        diag["hyp"] = diag["id"].map(dict(zip(u["id"], u["kind"], strict=True))).map({h["kind"]: k for k, h in HYPOTHESES.items()})
    return trades, diag, cov


def _diag_summary(diag: pd.DataFrame, hyp: str) -> dict[str, Any]:
    if len(diag) == 0 or "hyp" not in diag:
        return {}
    out = {}
    for w, g in diag[diag["hyp"] == hyp].groupby("window"):
        out[str(w)] = {
            "n": int(len(g)),
            "brier_model": C.brier(g["q_side"], g["won"]),
            "brier_market": C.brier(g["p_side"], g["won"]),
        }
    return out


def decide_train(cells: list[dict[str, Any]]) -> dict[str, Any] | None:
    ok = [c for c in cells if C.qualifies(c["summary"], MIN_N)]
    if not ok:
        return None
    best = max(ok, key=lambda c: c["summary"]["mean_net"])
    return {"key": best["key"], "margin": best["margin"], "window": best["window"], "vol_s": best["vol_s"]}


def decide_val(cell: dict[str, Any]) -> bool:
    s, p = cell["summary"], cell.get("placebo") or {}
    beats = p.get("real_percentile") is not None and p["real_percentile"] >= PLACEBO_PCT
    lat_ok = s["latency"]["mean_net"] is not None and s["latency"]["mean_net"] > 0
    return C.qualifies(s, MIN_N) and beats and lat_ok


def _fmt(v: Any, nd: int = 3) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "-"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _md(hyp: str, stage: str, doc: dict[str, Any]) -> str:
    h = HYPOTHESES[hyp]
    lines = [
        f"# {hyp} {h['title']}: {stage.upper()} ({doc['split']}, {PLAN_VERSION})",
        "",
        f"Run {doc['utc']}; PLAN.md sha256 {doc['prereg_sha256'][:12]}; markets {doc['coverage'].get('by_kind', {}).get(h['kind'], 0)} "
        f"in the split; decision lag {doc['lag_s']} s; Chainlink basis sd {doc['sigma_b']:.6f}; trials so far across labs 2-5: "
        f"{doc['n_trials_total']}.",
        "",
        "| cell | n | clusters | /day | win rate | losses | mean price paid | mean model q | mean model edge | mean net | CI95 (clusters) | "
        "worst case (rule of 3) | $/bet | $/day | worst $ | latency-stress net (n) | US-fee net |",
        "|" + "---|" * 17,
    ]
    for c in doc["cells"]:
        s = c["summary"]
        ci = s["ci95"]
        lat = s.get("latency") or {}
        lines.append(
            f"| {c['key']} | {s['n']} | {s.get('n_clusters', '-')} | {_fmt(s['bets_per_day'], 2)} | {_fmt(s['win_rate'])} | "
            f"{s.get('losses', '-')} | {_fmt(s['mean_p_exec'])} | {_fmt(s['mean_q'])} | {_fmt(s['mean_edge'])} | "
            f"{_fmt(s['mean_net'], 4)} | [{_fmt(ci[0], 4)}, {_fmt(ci[1], 4)}] | {_fmt(s.get('worst_case_net'), 4)} | "
            f"{_fmt(s['mean_pnl_usd'], 2)} | {_fmt(s['usd_per_day'], 2)} | {_fmt(s['worst_pnl_usd'], 2)} | "
            f"{_fmt(lat.get('mean_net'), 4)} ({lat.get('n', 0)}) | {_fmt(s.get('us_mean_net'), 4)} |"
        )
        if c.get("placebo"):
            p = c["placebo"]
            lines.append(
                f"|  placebo (market price is the truth) | | | | | | | | | mean {_fmt(p['mean'], 4)}, p95 {_fmt(p['p95'], 4)}; real at "
                f"percentile {_fmt(p['real_percentile'], 1)} | | | | | | | |"
            )
    lines += ["", f"**Decision:** {doc['decision']}"]
    if doc.get("selected"):
        lines.append(f"Selected cell: `{doc['selected']['key']}`.")
    if doc.get("diagnostic"):
        lines += ["", "Who knows better (PLAN §4; one print per market, the first in the entry window with a model value):", ""]
        lines += ["| window | markets | Brier model | Brier market price |", "|---|---|---|---|"]
        for w, d in doc["diagnostic"].items():
            lines.append(f"| {w} | {d['n']} | {_fmt(d['brier_model'], 4)} | {_fmt(d['brier_market'], 4)} |")
    kinds: dict[str, dict[str, Any]] = {}
    for c in doc["cells"]:
        for k, v in (c["summary"].get("by_kind") or {}).items():
            kinds.setdefault(c["key"], {})[k] = v
    if kinds:
        lines += ["", "Per contract type (breakdown, not a cell):", "", "| cell | type | n | win rate | mean price | mean q | mean net | total $ |", "|---|---|---|---|---|---|---|---|"]
        for key, ks in kinds.items():
            for k, v in ks.items():
                lines.append(
                    f"| {key} | {k} | {v['n']} | {_fmt(v['win_rate'])} | {_fmt(v['mean_p_exec'])} | {_fmt(v['mean_q'])} | "
                    f"{_fmt(v['mean_net'], 4)} | {_fmt(v['total_usd'], 2)} |"
                )
    lines += [
        "",
        "Readings per PLAN §4. One bet per market per cell: the first buyable print inside the entry window whose model "
        "edge (model probability of that side minus the price paid, print + 0.01, minus the taker fee per share) exceeds "
        "the margin; $20 tickets held to settlement; 'net' = profit per $1 staked after fees; CI by cluster bootstrap "
        "(bets settled by one price draw resample together); 'latency stress' = the same signal executed at lab 4's rule "
        "(first buyable print for the side >= 10 s later, + 0.01); 'US-fee net' = re-costed at Polymarket US's 0.0695. "
        "Nothing here is a live trade.",
        "",
    ]
    return "\n".join(lines)


def run_stage(stage: str, hyps: list[str] | None = None, B: int = C.BOOTSTRAP_B, procs: int = 4, here: Path = HERE) -> dict[str, Any]:
    split = stage
    C.check_split_allowed(split)
    hyps = hyps or list(HYPOTHESES)
    st = json.loads(STRUCTURE.read_text())
    if stage == "train":
        todo = hyps
        specs: dict[str, list[str] | None] = dict.fromkeys(hyps)
    else:
        prev = "train" if stage == "val" else "val"
        specs = {}
        for hyp in hyps:
            p = here / hyp / f"{prev}.json"
            d = json.loads(p.read_text()) if p.exists() else None
            sel = (d or {}).get("selected" if stage == "val" else "final")
            specs[hyp] = [sel["key"]] if sel else []
        todo = [h for h in hyps if specs[h]]
    trades, diag, cov = evaluate_split(split, todo, procs) if todo else (pd.DataFrame(), pd.DataFrame(), {})
    results: dict[str, Any] = {}
    for hyp in hyps:
        h = HYPOTHESES[hyp]
        hdir = here / hyp
        hdir.mkdir(exist_ok=True)
        cells = []
        if hyp in todo:
            tt = trades[trades["hyp"] == hyp] if len(trades) else trades
            keys = specs[hyp] or [cell_key(mg, w, v) for w in h["windows"] for v in h["vols"] for mg in h["margins"]]
            for key in keys:
                mg_s, w, vol_s = key.split("|")
                vol = int(vol_s[3:-1]) * (86400 if vol_s.endswith("d") else 3600)
                ct = tt[tt["cell"] == key] if len(tt) else tt
                cell = {
                    "key": key,
                    "margin": float(mg_s[1:]),
                    "window": w,
                    "vol_s": vol,
                    "summary": C.summarize(ct, split, B=B) if len(ct) else C.summarize(pd.DataFrame(columns=["t_entry"]), split, B=B),
                }
                if stage != "train":
                    cell["placebo"] = C.calibration_placebo(ct, draws=B) if len(ct) else C.calibration_placebo(pd.DataFrame())
                cells.append(cell)
        n_total = C.trials_count()
        for c in cells:
            n_total = C.record_run(
                {"lab": "lab5", "hyp": hyp, "cell": c["key"], "split": split, "stage": stage, "n": c["summary"]["n"], "mean_net": c["summary"]["mean_net"], "kind": "cell"}
            )
        selected = None
        if stage == "train":
            selected = decide_train(cells)
            decision = f"SHORTLISTED {selected['key']} for VAL" if selected else "NO EDGE on TRAIN (no cell qualifies)"
        elif stage == "val":
            if not cells:
                decision = "NOT RUN: TRAIN shortlisted no cell"
            else:
                ok = decide_val(cells[0])
                selected = {"key": cells[0]["key"]} if ok else None
                decision = f"PASSES VAL {cells[0]['key']}" if ok else f"FAIL on VAL ({cells[0]['key']})"
        else:
            if not cells:
                decision = "NOT RUN: VAL selected no cell"
            else:
                ok = decide_val(cells[0])
                decision = f"PASS on TEST ({cells[0]['key']})" if ok else f"FAIL on TEST ({cells[0]['key']})"
        doc = {
            "hyp": hyp,
            "stage": stage,
            "split": split,
            "utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "decision": decision,
            "cells": cells,
            "selected": selected,
            "prereg_sha256": prereg_sha256(),
            "coverage": cov,
            "lag_s": int(st["lag_s"]),
            "sigma_b": float(st["basis"]["sigma_b"]),
            "n_trials_total": n_total,
            "diagnostic": _diag_summary(diag, hyp) if hyp in todo else {},
        }
        (hdir / f"{stage}.json").write_text(json.dumps(doc, indent=1, sort_keys=True, default=str) + "\n")
        (hdir / f"{stage}.md").write_text(_md(hyp, stage, doc))
        if len(trades) and hyp in todo:
            trades[trades["hyp"] == hyp].to_parquet(D.OUT / f"trades_{hyp}_{stage}.parquet", index=False)
        results[hyp] = doc
        print(f"{hyp} {stage}: {decision}", flush=True)
    if stage == "val":
        _select_final(here)
    _results_md(here)
    return results


def _select_final(here: Path = HERE) -> None:
    """PLAN §3: among the VAL passes, the one cell with the highest VAL CI95 lower bound goes to TEST."""
    passes = []
    for hyp in HYPOTHESES:
        p = here / hyp / "val.json"
        if p.exists():
            d = json.loads(p.read_text())
            if d.get("selected") and d["cells"]:
                passes.append((d["cells"][0]["summary"]["ci95"][0], hyp, d))
    best = max(passes, key=lambda x: x[0]) if passes else None
    for hyp in HYPOTHESES:
        p = here / hyp / "val.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        d["final"] = {"key": d["cells"][0]["key"]} if best and best[1] == hyp else None
        if d.get("selected"):
            d["decision"] = (
                f"SELECTED {d['cells'][0]['key']} for TEST" if best and best[1] == hyp else "passes VAL but another hypothesis has the higher CI lower bound"
            )
        p.write_text(json.dumps(d, indent=1, sort_keys=True, default=str) + "\n")
        (here / hyp / "val.md").write_text(_md(hyp, "val", d))


def _results_md(here: Path = HERE) -> None:
    rows = [
        "# Lab 5 results (the crypto price-market specialist)",
        "",
        "| hyp | title | TRAIN | VAL | TEST |",
        "|---|---|---|---|---|",
    ]
    for hyp, h in HYPOTHESES.items():
        cells = []
        for stage in ("train", "val", "test"):
            p = here / hyp / f"{stage}.json"
            cells.append(json.loads(p.read_text())["decision"] if p.exists() else "-")
        rows.append(f"| {hyp} | {h['title']} | {cells[0]} | {cells[1]} | {cells[2]} |")
    rows += ["", "Decisions per research/lab5/PLAN.md; per-stage tables in each hypothesis folder; inventory.md, structure.md. Paper only.", ""]
    (here / "RESULTS.md").write_text("\n".join(rows))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lab 5 stages")
    ap.add_argument("--stage", choices=["inventory", "structure", "train", "val", "test"], required=True)
    ap.add_argument("--hyp", nargs="*", default=None)
    ap.add_argument("--B", type=int, default=C.BOOTSTRAP_B)
    ap.add_argument("--procs", type=int, default=4)
    a = ap.parse_args(argv)
    if a.stage == "inventory":
        doc = stage_inventory()
        print(json.dumps({k: doc[k] for k in ("crypto_family_markets", "universe", "usable", "per_hyp")}, indent=1, default=str))
    elif a.stage == "structure":
        doc = stage_structure()
        print(json.dumps({k: doc[k] for k in ("replication", "basis", "timing_mse_by_k", "lag_s")}, indent=1))
    else:
        run_stage(a.stage, a.hyp, B=a.B, procs=a.procs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
