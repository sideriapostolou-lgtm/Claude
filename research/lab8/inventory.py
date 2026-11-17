"""Lab 8 inventory: what the cached data can support for a DISTANCE-filtered grind backtest (no return computed).

Research only; the live bot never reads this, nothing here trades, no key is used. Every stage counts things; no stage
reads an outcome except lab 5's universe rule (binary, exactly one winner), and no stage computes a win rate, a
price-vs-outcome comparison or a P&L.

The question lab 8 will test (owner, 2026-10-12): buy a 0.95-0.99 outcome of a crypto price market in its last hour
only when spot is FAR from the strike in volatility units. Before any rule is written, this script measures what the
data can carry:

* ``tapes``: for every BTC / ETH / SOL / XRP price market in lab 4's polymarket.com cache (lab 5's universe plus the
  Chainlink windows without a ``priceToBeat``), the tape prints of the last 60 minutes before settlement, the BUYABLE
  ones (lab 4 Amendment 3) at a price >= 0.95 for the side bought, by price band, their dollar notional, and, at the
  first such print, the distance of spot from the strike in volatility units (``z = Phi^-1(q)``, ``q`` = lab 5's
  fixed fair value of that side read 10 s before the print) and the Binance 1 s coverage at the decision second.
* ``spot-gaps``: missing seconds in lab 5's Binance 1 s klines (2026-06-01 .. 2026-10-08).
* ``gamma-hourly``: Gamma's listing of polymarket.com's hourly strike series (``bitcoin-multi-strikes-hourly``,
  ``ethereum-multi-strikes-hourly``), the family closest to the owner's Polymarket US example, which lab 4's $20,000
  volume floor left almost entirely out of the cache. Listing fields only (no outcome prices kept).
* ``hourly-sample``: the fill tapes of those hourly strike markets on a few sample days (data API, public), counted the
  same way as ``tapes``.
* ``binance-probe``: HEAD of every monthly 1-minute kline archive for BTCUSDT / ETHUSDT / SOLUSDT, 2019-01 .. 2026-05,
  and one month downloaded, checksummed and parsed to measure the full download.
* ``report``: ``research/lab8/inventory.json`` and ``inventory.md``.

Data stays out of git under ``$LAB8_DATA`` (default ``$SCRATCH/lab8/inv``). Run with ``python -I`` (it reads
downloaded files)::

    python -I research/lab8/inventory.py --stage tapes --procs 4
    python -I research/lab8/inventory.py --stage spot-gaps
    python -I research/lab8/inventory.py --stage gamma-hourly
    python -I research/lab8/inventory.py --stage hourly-sample --days 2026-07-15 2026-08-25 2026-09-25
    python -I research/lab8/inventory.py --stage binance-probe
    python -I research/lab8/inventory.py --stage report
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import multiprocessing as mp
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
LAB4_DIR = HERE.parent / "lab4"
LAB5_DIR = HERE.parent / "lab5"
sys.path.insert(0, str(LAB5_DIR))  # lab 5's run.py imports its siblings as ``core`` and ``data``

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402
from scipy.special import ndtri  # noqa: E402

import core as C5  # noqa: E402  (research/lab5/core.py)
import data as D5  # noqa: E402  (research/lab5/data.py)


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R5 = _load("lab5_run", LAB5_DIR / "run.py")
D4 = _load("lab4_data", LAB4_DIR / "data.py")

OUT = Path(os.environ.get("LAB8_DATA", str(D5.SCRATCH / "lab8" / "inv")))
LAST_S = 3600  # the owner's window: the last hour before settlement
BANDS = ((0.95, 0.97), (0.97, 0.99), (0.99, 1.0))
THETA = 0.95
THETAS = (0.95, 0.97, 0.99)  # price floors for the market counts by distance
Z_GRID = (2.0, 3.0, 4.0, 5.0)  # distance floors (volatility units) for the market counts
Z_EDGES = (-np.inf, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, np.inf)
Z_LABELS = ("<0", "0-1", "1-2", "2-3", "3-4", "4-5", "5-6", ">=6")
TAU_EDGES = (0, 300, 900, 1800, 3601)
TAU_LABELS = ("0-5 min", "5-15 min", "15-30 min", "30-60 min")
COVER = ("exact", "stale<=5s", "stale>5s", "none")
LAG_S = C5.LAG_S  # lab 5: spot read 10 s before the print
SIGMA_B = 7.54e-5  # lab 5 structure stage: Chainlink basis noise (TRAIN), used as lab 5 does
VOL_OF = {"terminal": 86400, "touch": 86400, "window": 3600}  # lab 5's primary vol windows
SPLIT_NAMES = ("train", "val", "test")
UA = {"User-Agent": "nightcrawler-research/lab8 (+https://github.com/sideriapostolou-lgtm/Claude)"}
GAMMA_HOURLY = {"BTC": 11372, "ETH": 11373}  # Gamma series ids, read 2026-10-12 from /series?slug=...
BINANCE_MONTHLY = "https://data.binance.vision/data/spot/monthly/klines"

_SPOTS: dict[str, C5.Spot] = {}
_LASTP: dict[str, np.ndarray] = {}


# --------------------------------------------------------------------------------------------- universe


def family_of(row: dict[str, Any]) -> str:
    """A short family label: terminal noon / hourly strike (by op), window by length, touch by period."""
    if row["kind"] is None or (isinstance(row["kind"], float) and np.isnan(row["kind"])):
        return "window no-ptb (chainlink)"
    c = json.loads(row["contract"])
    h = R5.horizon_label(row, c)
    if c["kind"] == "terminal":
        return f"terminal {'hourly' if h == '1h close' else 'noon ET'} {c['op']}"
    if c["kind"] == "window":
        return f"up/down {c['sub']} ({c['source']})"
    return f"touch {h}"


def lab8_universe() -> pd.DataFrame:
    """Lab 5's universe (binary, one winner, a parsed contract on BTC / ETH / SOL / XRP, a split) plus the Chainlink
    windows lab 5 dropped for want of a ``priceToBeat`` (counted, never modelled)."""
    cat = R5.catalogue()
    u = R5.universe(cat)
    noptb = cat[
        (cat["why"] == "no priceToBeat")
        & (cat["n_outcomes"] == 2)
        & cat["winner"].isin([0, 1])
        & cat["symbol"].isin(list(D5.SYMBOLS))
        & cat["split"].notna()
    ]
    u = pd.concat([u, noptb], ignore_index=True)
    u["kind"] = u["kind"].where(u["kind"].notna(), None)
    u["family"] = [family_of(r) for r in u.to_dict("records")]
    return u.drop(columns=["winner"])  # nothing below reads an outcome


def settle_instant(row: dict[str, Any]) -> float:
    if not row["contract"]:
        return float(row["end_date"])
    c = json.loads(row["contract"])
    return float(c["p1"] if c["kind"] == "touch" else c["t_final"])


def cluster_of(row: dict[str, Any]) -> str:
    if not row["contract"]:
        return "W:" + datetime.fromtimestamp(float(row["end_date"]) - 1, UTC).strftime("%Y-%m-%dT%H")
    return R5._cluster(json.loads(row["contract"]))


# --------------------------------------------------------------------------------------------- tapes stage


def _coverage(sym: str, t_d: np.ndarray) -> np.ndarray:
    """Binance 1 s coverage of the candle a decision at ``t_d`` reads (the one opening at ``t_d - 1``)."""
    sp = _SPOTS.get(sym)
    out = np.full(len(t_d), "none", dtype=object)
    if sp is None:
        return out
    i = np.asarray(t_d, dtype=np.int64) - 1 - sp.base
    ok = (i >= 0) & (i < len(sp.present))
    ii = i[ok]
    lp = _LASTP[sym][ii]
    lab = np.where(sp.present[ii], "exact", np.where(lp < 0, "none", np.where(ii - lp <= 5, "stale<=5s", "stale>5s")))
    out[ok] = lab
    return out


def count_market(row: dict[str, Any]) -> dict[str, Any]:
    """Counts for one market's last 60 minutes (see the module docstring). No outcome is read."""
    rec: dict[str, Any] = {"id": row["id"], "family": row["family"], "symbol": row["symbol"], "split": row["split"]}
    path = D5.LAB4 / "trades" / f"{row['id']}.parquet"
    if not path.exists():
        return {**rec, "fills": -1}
    tape = R5.load_tape(path)
    t_settle = settle_instant(row)
    hi = min(t_settle, float(row["closed_time"]))
    rec["fills"] = int(len(tape))
    last = tape[(tape["ts"] >= t_settle - LAST_S) & (tape["ts"] < hi)].reset_index(drop=True)
    rec["prints_last60"] = int(len(last))
    side = np.where(last["buy0"].to_numpy(dtype=bool), 0, 1)
    p0 = last["p0"].to_numpy(dtype=float)
    p_side = np.where(side == 0, p0, 1.0 - p0)
    size = last["size"].to_numpy(dtype=float)
    sel = p_side >= THETA
    rec["buy95"] = int(sel.sum())
    for a, b in BANDS:
        rec[f"band_{a:.2f}"] = int(((p_side >= a) & (p_side < b)).sum())
    rec["usd95"] = float((size[sel] * p_side[sel]).sum())
    rec["shares95"] = float(size[sel].sum())
    rec["cluster"] = cluster_of(row)
    if not sel.any():
        return rec
    ts = last["ts"].to_numpy(dtype=np.int64)
    i95 = int(np.argmax(sel))
    sel97 = p_side >= 0.97
    rec["first95_tau"] = float(t_settle - ts[i95])
    rec["first95_price"] = float(p_side[i95])
    rec["first97_tau"] = float(t_settle - ts[int(np.argmax(sel97))]) if sel97.any() else None
    # distance in volatility units at each >= 0.95 print: z = Phi^-1(q of the side bought), lab 5's model
    z = np.full(len(last), np.nan)
    vol_ok = np.zeros(len(last), dtype=bool)
    if row["contract"]:
        m = R5.to_market({**row, "winner": -1})  # winner is never read by the candidate builder
        vol = VOL_OF[m.contract["kind"]]
        cand = C5.market_candidates(m, last, _SPOTS[row["symbol"]], [vol], SIGMA_B, LAG_S)
        q = cand[f"q{vol}"].to_numpy(dtype=float)
        if len(q) == len(last):
            with np.errstate(divide="ignore", invalid="ignore"):
                z = ndtri(np.clip(q, 0.0, 1.0))
            z = np.where(np.isposinf(z), 99.0, np.where(np.isneginf(z), -99.0, z))  # q = 1 / 0 (barrier already hit)
            v = _SPOTS[row["symbol"]].var_per_s(ts - LAG_S, vol)
            vol_ok = np.isfinite(v)
    zs = z[sel]
    zlab = pd.cut(pd.Series(zs), bins=list(Z_EDGES), labels=list(Z_LABELS), right=False)
    counts = zlab.value_counts()
    usd = pd.Series(size[sel] * p_side[sel]).groupby(zlab.values, observed=False).sum()
    for lab in Z_LABELS:
        rec[f"z95_{lab}"] = int(counts.get(lab, 0))
        rec[f"usd95_{lab}"] = float(usd.get(lab, 0.0))
    for th in THETAS:  # the farthest distance seen at a buyable print at or above each price threshold
        mt = (p_side >= th) & ~np.isnan(z)
        rec[f"maxz_{th:.2f}"] = float(z[mt].max()) if mt.any() else None
    rec["z95_na"] = int(np.isnan(zs).sum())
    rec["first95_z"] = float(z[i95]) if not np.isnan(z[i95]) else None
    if sel97.any():
        i97 = int(np.argmax(sel97))
        rec["first97_z"] = float(z[i97]) if not np.isnan(z[i97]) else None
    cov = _coverage(row["symbol"], ts[sel] - LAG_S)
    for k in COVER:
        rec[f"cov95_{k}"] = int((cov == k).sum())
    rec["vol95_ok"] = int(vol_ok[sel].sum())
    return rec


def _init_pool() -> None:
    pass


def stage_tapes(procs: int = 4) -> pd.DataFrame:
    u = lab8_universe()
    t0 = time.time()
    syms = sorted(u["symbol"].dropna().unique())
    _SPOTS.clear()
    _SPOTS.update(R5.load_spots(syms))
    for s, sp in _SPOTS.items():
        idx = np.where(sp.present, np.arange(len(sp.present), dtype=np.int64), -1)
        _LASTP[s] = np.maximum.accumulate(idx)
    print(f"lab8 tapes: {len(u)} markets, spots {sorted(_SPOTS)} loaded in {time.time() - t0:.0f}s", flush=True)
    rows = u.to_dict("records")
    out: list[dict[str, Any]] = []
    with mp.get_context("fork").Pool(procs, initializer=_init_pool) as pool:
        for k, r in enumerate(pool.imap(count_market, rows, chunksize=32), 1):
            out.append(r)
            if k % 2000 == 0:
                print(f"  {k}/{len(rows)} markets, {time.time() - t0:.0f}s", flush=True)
    df = pd.DataFrame(out)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT / "tape_counts.parquet", index=False)
    print(f"lab8 tapes: done in {time.time() - t0:.0f}s -> {OUT / 'tape_counts.parquet'}", flush=True)
    return df


# --------------------------------------------------------------------------------------------- spot gaps


def stage_spot_gaps() -> dict[str, Any]:
    """Missing seconds per symbol and split in lab 5's 1 s klines, and the longest gaps."""
    lo = int(datetime(2026, 6, 1, tzinfo=UTC).timestamp())
    hi = int(datetime(2026, 10, 9, tzinfo=UTC).timestamp())
    doc: dict[str, Any] = {"range": ["2026-06-01", "2026-10-08"], "seconds_expected": hi - lo, "symbols": {}}
    bounds = {s: C5.split_bounds(s) for s in SPLIT_NAMES}
    for sym in D5.SYMBOLS:
        files = sorted((D5.OUT / "spot" / sym).glob("*.parquet"))
        ts = np.concatenate([pd.read_parquet(p, columns=["ts"])["ts"].to_numpy(dtype=np.int64) for p in files])
        present = np.zeros(hi - lo, dtype=bool)
        k = ts - lo
        present[k[(k >= 0) & (k < hi - lo)]] = True
        miss = ~present
        # runs of missing seconds
        d = np.diff(np.concatenate([[0], miss.astype(np.int8), [0]]))
        starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
        lens = ends - starts
        top = np.argsort(-lens)[:5]
        per_split = {}
        for s, (a, b) in bounds.items():
            ia, ib = int(a) - lo, int(b) - lo
            per_split[s] = {"missing_s": int(miss[ia:ib].sum()), "pct": float(miss[ia:ib].mean() * 100)}
        doc["symbols"][sym] = {
            "days": len(files),
            "rows": int(len(ts)),
            "duplicates": int(len(ts) - len(np.unique(ts))),
            "missing_s": int(miss.sum()),
            "missing_pct": float(miss.mean() * 100),
            "gaps_ge2s": int((lens >= 2).sum()),
            "gaps_ge10s": int((lens >= 10).sum()),
            "gaps_ge60s": int((lens >= 60).sum()),
            "gaps_ge600s": int((lens >= 600).sum()),
            "longest": [
                {"start_utc": datetime.fromtimestamp(lo + int(starts[j]), UTC).isoformat(timespec="seconds"), "seconds": int(lens[j])}
                for j in top
                if len(lens)
            ],
            "per_split": per_split,
        }
        print(f"  {sym}: {doc['symbols'][sym]['missing_s']} missing s", flush=True)
    # BTC volatility scale for the worked example (median 1-day realized variance per second over the cache)
    df = pd.concat([pd.read_parquet(p) for p in sorted((D5.OUT / "spot" / "BTCUSDT").glob("*.parquet"))], ignore_index=True)
    sp = C5.Spot.from_frame("BTCUSDT", df)
    t = np.arange(lo + 86400, hi, 3600)
    v = sp.var_per_s(t, 86400)
    doc["btc_v1d_per_s"] = {
        "median": float(np.nanmedian(v)),
        "p10": float(np.nanpercentile(v, 10)),
        "p90": float(np.nanpercentile(v, 90)),
        "n_hours": int(np.isfinite(v).sum()),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "spot_gaps.json").write_text(json.dumps(doc, indent=1) + "\n")
    return doc


# --------------------------------------------------------------------------------------------- Gamma hourly strikes


def _get_json(url: str, params: Any = None, tries: int = 6) -> Any:
    last = "no response"
    for attempt in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=90)
            if r.status_code == 429:
                time.sleep(10.0 * (attempt + 1))
                last = "429"
                continue
            if r.status_code >= 500:
                time.sleep(3.0 * (attempt + 1))
                last = str(r.status_code)
                continue
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = repr(e)
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed: {last}")


def stage_gamma_hourly(since: str = "2026-07-01", until: str = "2026-10-08") -> pd.DataFrame:
    """Every closed market of polymarket.com's BTC / ETH hourly strike series whose event ended in [since, until],
    one Gamma events call per series and day. Listing fields only."""
    d0 = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=UTC)
    d1 = datetime.strptime(until, "%Y-%m-%d").replace(tzinfo=UTC)
    rows: list[dict[str, Any]] = []
    nbytes = 0
    for coin, sid in GAMMA_HOURLY.items():
        d = d0
        while d <= d1:
            params = {
                "series_id": sid,
                "closed": "true",
                "limit": 100,
                "end_date_min": d.strftime("%Y-%m-%dT00:00:00Z"),
                "end_date_max": (d + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z"),
            }
            evs = _get_json(f"{D5.API_GAMMA}/events", params)
            nbytes += len(json.dumps(evs))
            for e in evs if isinstance(evs, list) else []:
                for mk in e.get("markets") or []:
                    rows.append(
                        {
                            "coin": coin,
                            "event_id": str(e.get("id")),
                            "event_title": e.get("title"),
                            "id": str(mk.get("id")),
                            "condition_id": mk.get("conditionId"),
                            "question": mk.get("question"),
                            "slug": mk.get("slug"),
                            "end_date": D4.parse_time(mk.get("endDate") or e.get("endDate")),
                            "closed_time": D4.parse_time(mk.get("closedTime")),
                            "volume": float(mk.get("volumeNum") or mk.get("volume") or 0.0),
                            "fees_enabled": bool(mk.get("feesEnabled")),
                            "fee_type": mk.get("feeType"),
                            "resolution_status": mk.get("umaResolutionStatus"),
                            "resolution_source": mk.get("resolutionSource") or e.get("resolutionSource"),
                        }
                    )
            time.sleep(0.35)
            d += timedelta(days=1)
        print(f"  {coin}: {sum(r['coin'] == coin for r in rows)} markets listed", flush=True)
    df = pd.DataFrame(rows).drop_duplicates("id")
    t = df["closed_time"].fillna(df["end_date"])
    df["split"] = [C5.split_of(float(x)) if pd.notna(x) else None for x in t]
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT / "gamma_hourly.parquet", index=False)
    (OUT / "gamma_hourly_meta.json").write_text(json.dumps({"json_bytes_decoded": nbytes, "utc": datetime.now(UTC).isoformat(timespec="seconds")}) + "\n")
    print(f"lab8 gamma-hourly: {len(df)} markets, ~{nbytes / 1e6:.0f} MB of JSON decoded", flush=True)
    return df


def _count_hourly_tape(tape_raw: pd.DataFrame, t_settle: float, closed_time: float) -> dict[str, Any]:
    """The ``tapes`` counts for a freshly fetched hourly strike tape (same transform as lab 5's load_tape)."""
    t = tape_raw[(tape_raw["ts"] > 0) & (tape_raw["price"] > 0) & (tape_raw["price"] < 1) & tape_raw["outcome_index"].isin([0, 1])]
    oi = t["outcome_index"].to_numpy()
    sd = t["side"].astype(str).str.upper().to_numpy()
    p0 = np.where(oi == 0, t["price"].to_numpy(), 1.0 - t["price"].to_numpy())
    buy0 = ((oi == 0) & (sd == "BUY")) | ((oi == 1) & (sd == "SELL"))
    ts = t["ts"].to_numpy(dtype=np.int64)
    w = (ts >= t_settle - LAST_S) & (ts < min(t_settle, closed_time))
    p_side = np.where(buy0, p0, 1.0 - p0)[w]
    size = t["size"].to_numpy(dtype=float)[w]
    sel = p_side >= THETA
    rec = {"fills": int(len(t)), "prints_last60": int(w.sum()), "buy95": int(sel.sum()), "usd95": float((size[sel] * p_side[sel]).sum())}
    for a, b in BANDS:
        rec[f"band_{a:.2f}"] = int(((p_side >= a) & (p_side < b)).sum())
    return rec


def stage_hourly_sample(days: list[str], coin: str = "BTC") -> pd.DataFrame:
    """Fetch (data API, public) and count the tapes of one coin's hourly strike markets with volume > 0 on the
    sample days; raw tapes saved under ``$LAB8_DATA/hourly_sample/``."""
    g = pd.read_parquet(OUT / "gamma_hourly.parquet")
    g = g[(g["coin"] == coin) & (g["volume"] > 0)]
    day_of = pd.to_datetime(g["end_date"], unit="s", utc=True).dt.strftime("%Y-%m-%d")
    g = g[day_of.isin(days)]
    tdir = OUT / "hourly_sample"
    tdir.mkdir(parents=True, exist_ok=True)
    out = []
    t0 = time.time()
    for k, r in enumerate(g.to_dict("records"), 1):
        p = tdir / f"{r['id']}.parquet"
        end = float(r["end_date"])
        if p.exists():
            tape = pd.read_parquet(p)
        else:
            tape = D4.fetch_trades(r["condition_id"], int(end - 3 * 86400), int(end + 3600))
            tape.to_parquet(p, index=False)
        ct = float(r["closed_time"]) if pd.notna(r["closed_time"]) else end + 3600
        out.append({"id": r["id"], "day": datetime.fromtimestamp(end, UTC).strftime("%Y-%m-%d"), "split": r["split"], "volume": r["volume"], "bytes": p.stat().st_size, **_count_hourly_tape(tape, end, ct)})
        if k % 50 == 0:
            print(f"  {k}/{len(g)} tapes, {time.time() - t0:.0f}s", flush=True)
    df = pd.DataFrame(out)
    df.to_parquet(OUT / "hourly_sample_counts.parquet", index=False)
    print(f"lab8 hourly-sample: {len(df)} tapes in {time.time() - t0:.0f}s", flush=True)
    return df


# --------------------------------------------------------------------------------------------- Binance monthly 1m


def _months(a: str, b: str) -> list[str]:
    y, m = map(int, a.split("-"))
    y1, m1 = map(int, b.split("-"))
    out = []
    while (y, m) <= (y1, m1):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def stage_binance_probe(symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT"), first: str = "2019-01", last: str = "2026-05", sample: tuple[str, ...] = ("BTCUSDT-2026-05", "BTCUSDT-2019-01")) -> dict[str, Any]:
    """HEAD every monthly 1m archive (size, status) and download + checksum + parse the sample months."""
    heads = []
    for sym in symbols:
        for mo in _months(first, last):
            url = f"{BINANCE_MONTHLY}/{sym}/1m/{sym}-1m-{mo}.zip"
            for attempt in range(4):
                try:
                    r = requests.head(url, headers=UA, timeout=60, allow_redirects=True)
                    break
                except requests.RequestException:
                    time.sleep(2.0 * (attempt + 1))
            else:
                heads.append({"symbol": sym, "month": mo, "status": -1, "bytes": None})
                continue
            n = r.headers.get("Content-Length")
            heads.append({"symbol": sym, "month": mo, "status": r.status_code, "bytes": int(n) if n and r.status_code == 200 else None, "last_modified": r.headers.get("Last-Modified")})
            time.sleep(0.1)
        print(f"  HEAD {sym}: {sum(1 for h in heads if h['symbol'] == sym and h['status'] == 200)} months present", flush=True)
    samples = {}
    for key in sample:
        sym, mo = key.split("-", 1)
        url = f"{BINANCE_MONTHLY}/{sym}/1m/{sym}-1m-{mo}.zip"
        ddir = OUT / "binance_probe" / f"{sym}-1m-{mo}"  # one new directory per downloaded archive
        ddir.mkdir(parents=True, exist_ok=True)
        raw = requests.get(url, headers=UA, timeout=300).content
        chk = requests.get(url + ".CHECKSUM", headers=UA, timeout=60).text.split()[0]
        (ddir / f"{sym}-1m-{mo}.zip").write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        df = D5.parse_klines(raw)
        pq = ddir / f"{sym}-1m-{mo}.parquet"
        df.to_parquet(pq, index=False)
        span = (int(df["ts"].iloc[0]), int(df["ts"].iloc[-1]))
        expected = (span[1] - span[0]) // 60 + 1
        steps = np.diff(df["ts"].to_numpy())
        samples[key] = {
            "zip_bytes": len(raw),
            "sha256_ok": digest == chk,
            "rows": int(len(df)),
            "first_utc": datetime.fromtimestamp(span[0], UTC).isoformat(timespec="seconds"),
            "last_utc": datetime.fromtimestamp(span[1], UTC).isoformat(timespec="seconds"),
            "rows_expected_in_span": int(expected),
            "missing_minutes": int(expected - len(np.unique(df["ts"]))),
            "non_60s_steps": int((steps != 60).sum()),
            "parquet_bytes_ohlc": pq.stat().st_size,
        }
        print(f"  sample {key}: {samples[key]}", flush=True)
    doc = {"utc": datetime.now(UTC).isoformat(timespec="seconds"), "heads": heads, "samples": samples}
    (OUT / "binance_probe.json").write_text(json.dumps(doc, indent=1) + "\n")
    return doc


# --------------------------------------------------------------------------------------------- Polymarket US


US_GATEWAY = "https://gateway.polymarket.us/v1"
EXAMPLE_SLUG = "cpc-btc-above-hr-2026-10-12-1400z-81900"  # the owner's example (bought 10 @ 0.99, 13:36 UTC)


def _us_family(slug: str) -> str:
    import re

    fam = re.sub(r"-\d{4}-\d{2}-\d{2}.*", "", slug)
    fam = re.sub(r"-\d{1,2}-\d{1,2}-\d{4}.*", "", fam)
    return re.sub(r"-\d+k$", "", fam)


def stage_us_venue(max_pages: int = 60, name: str = "us_closed_summary.json") -> dict[str, Any]:
    """The US gateway's crypto events (public, no key): every closed and open page, summarized per slug family
    (events, markets, first / last endDate). No raw page, price or outcome is kept."""
    udir = OUT / "us"
    udir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {}
    for state in ("closed", "open"):
        fam_ev: dict[str, set[str]] = {}
        fam_mk: dict[str, int] = {}
        fam_end: dict[str, list[str]] = {}
        nbytes = 0
        for pg in range(max_pages):
            params = {"limit": 100, "offset": pg * 100, "closed": "true" if state == "closed" else "false", "categories": "crypto"}
            reply = _get_json(f"{US_GATEWAY}/events", params)
            evs = reply.get("events") or [] if isinstance(reply, dict) else []
            nbytes += len(json.dumps(reply))
            for e in evs:
                for m in e.get("markets") or []:
                    fam = _us_family(str(m.get("slug") or ""))
                    fam_ev.setdefault(fam, set()).add(str(e.get("id")))
                    fam_mk[fam] = fam_mk.get(fam, 0) + 1
                    fam_end.setdefault(fam, []).append(str(m.get("endDate") or ""))
            time.sleep(0.5)
            if len(evs) < 100:
                break
        summary[state] = {
            "json_bytes": nbytes,
            "families": {
                f: {"events": len(fam_ev[f]), "markets": fam_mk[f], "first_end": min(x for x in fam_end[f] if x), "last_end": max(x for x in fam_end[f] if x)}
                for f in sorted(fam_mk, key=lambda k: -fam_mk[k])
            },
        }
    summary["utc"] = datetime.now(UTC).isoformat(timespec="seconds")
    (udir / name).write_text(json.dumps(summary, indent=1) + "\n")
    return summary


def stage_example() -> dict[str, Any]:
    """The owner's example in volatility units: the US book's lifetime stats and settlement, and Coinbase BTC-USD
    1-minute candles (a public USD proxy; BRTI itself is not public) for the 24 h before the buy and to settlement."""
    import math

    udir = OUT / "us"
    udir.mkdir(parents=True, exist_ok=True)
    book = _get_json(f"{US_GATEWAY}/markets/{EXAMPLE_SLUG}/book")
    settle = _get_json(f"{US_GATEWAY}/markets/{EXAMPLE_SLUG}/settlement")
    t_buy = int(datetime(2026, 10, 12, 13, 36, tzinfo=UTC).timestamp())
    t_set = int(datetime(2026, 10, 12, 14, 0, tzinfo=UTC).timestamp())
    rows: dict[int, list[float]] = {}
    a = t_buy - 86400
    while a < t_set + 60:
        b = min(a + 299 * 60, t_set + 60)
        part = _get_json(
            "https://api.exchange.coinbase.com/products/BTC-USD/candles",
            {"granularity": 60, "start": datetime.fromtimestamp(a, UTC).isoformat(), "end": datetime.fromtimestamp(b, UTC).isoformat()},
        )
        for r in part if isinstance(part, list) else []:
            rows[int(r[0])] = [float(x) for x in r]  # [time, low, high, open, close, volume]; time = minute start
        a = b + 60
        time.sleep(0.5)
    (udir / "example_coinbase.json").write_text(json.dumps({str(k): v for k, v in sorted(rows.items())}))
    ts = np.array(sorted(rows))
    close = np.array([rows[t][4] for t in ts])
    past = close[ts + 60 <= t_buy][-1441:]
    r = np.diff(np.log(past))
    v = float(np.mean(r * r)) / 60.0
    s_buy = float(close[ts == t_buy - 60][0])  # the 13:35 minute's close = the last price known at 13:36:00
    tau = t_set - t_buy
    after = (ts >= t_buy) & (ts < t_set)
    strike = 81900.0
    doc = {
        "slug": EXAMPLE_SLUG,
        "book_stats": (book.get("marketData") or {}).get("stats"),
        "settlement": settle,
        "coinbase_at_buy": s_buy,
        "distance_usd": s_buy - strike,
        "distance_pct": 100 * math.log(s_buy / strike),
        "v_per_s_24h": v,
        "ann_vol_pct": 100 * math.sqrt(v * 365 * 86400),
        "tau_s": tau,
        "z_24h_vol": (math.log(s_buy / strike) - 0.5 * v * tau) / math.sqrt(v * tau),
        "min_low_after_buy": float(min(rows[t][1] for t in ts[after])),
        "close_1355": float(close[ts == t_set - 300][0]),
        "close_1359": float(close[ts == t_set - 60][0]),
    }
    (udir / "example.json").write_text(json.dumps(doc, indent=1) + "\n")
    return doc


# --------------------------------------------------------------------------------------------- report


FAMILY_ORDER = [
    "terminal hourly above",
    "terminal noon ET above",
    "terminal noon ET below",
    "terminal noon ET between",
    "up/down 5m (chainlink)",
    "window no-ptb (chainlink)",
    "up/down 15m (chainlink)",
    "up/down 1h (binance)",
    "up/down 4h (chainlink)",
    "up/down 1d (binance)",
    "touch day",
    "touch week",
    "touch month",
]


def _fmt_int(x: Any) -> str:
    return f"{int(x):,}" if x is not None and not (isinstance(x, float) and np.isnan(x)) else "-"


def _fmt_usd(x: Any) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "-"
    return f"${x / 1e6:,.2f}M" if x >= 1e6 else (f"${x / 1e3:,.0f}k" if x >= 1e3 else f"${x:,.0f}")


def _table_main(t: pd.DataFrame) -> tuple[list[dict[str, Any]], list[str]]:
    rows, lines = [], []
    lines.append("| family | split | markets | with >= 50 fills | prints, last 60 min | buyable prints >= 0.95 | 0.95-0.97 | 0.97-0.99 | >= 0.99 | markets with a >= 0.95 print | with a >= 0.97 print | clusters (>= 0.95) | $ notional >= 0.95 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    fams = [f for f in FAMILY_ORDER if f in set(t["family"])] + sorted(set(t["family"]) - set(FAMILY_ORDER))
    for fam in fams:
        for sp in SPLIT_NAMES:
            g = t[(t["family"] == fam) & (t["split"] == sp)]
            if not len(g):
                continue
            u = g[g["fills"] >= C5.MIN_FILLS]
            sig = u[u["buy95"] > 0]
            r = {
                "family": fam,
                "split": sp,
                "markets": len(g),
                "fills50": len(u),
                "prints_last60": int(u["prints_last60"].sum()),
                "buy95": int(u["buy95"].sum()),
                "b95": int(u["band_0.95"].sum()),
                "b97": int(u["band_0.97"].sum()),
                "b99": int(u["band_0.99"].sum()),
                "mk95": len(sig),
                "mk97": int((u["band_0.97"] + u["band_0.99"] > 0).sum()),
                "clusters95": int(sig["cluster"].nunique()),
                "usd95": float(u["usd95"].sum()),
            }
            rows.append(r)
            lines.append(
                f"| {fam} | {sp} | {_fmt_int(r['markets'])} | {_fmt_int(r['fills50'])} | {_fmt_int(r['prints_last60'])} | {_fmt_int(r['buy95'])} | "
                f"{_fmt_int(r['b95'])} | {_fmt_int(r['b97'])} | {_fmt_int(r['b99'])} | {_fmt_int(r['mk95'])} | {_fmt_int(r['mk97'])} | "
                f"{_fmt_int(r['clusters95'])} | {_fmt_usd(r['usd95'])} |"
            )
    return rows, lines


def stage_report() -> dict[str, Any]:
    t = pd.read_parquet(OUT / "tape_counts.parquet")
    for col in ["buy95", "band_0.95", "band_0.97", "band_0.99", "usd95", "prints_last60"]:
        t[col] = t[col].fillna(0)
    doc: dict[str, Any] = {"utc": datetime.now(UTC).isoformat(timespec="seconds"), "theta": THETA, "last_s": LAST_S, "lag_s": LAG_S}
    main_rows, main_lines = _table_main(t)
    doc["main"] = main_rows
    u = t[(t["fills"] >= C5.MIN_FILLS) & (t["buy95"] > 0)].copy()
    # symbols
    sym = u.groupby(["family", "symbol", "split"]).size().unstack("split", fill_value=0)
    doc["by_symbol"] = {f"{a}|{b}": {k: int(v) for k, v in r.items()} for (a, b), r in sym.iterrows()}
    # distance at the first >= 0.95 print
    zc = pd.cut(u["first95_z"].astype(float), bins=list(Z_EDGES), labels=list(Z_LABELS), right=False)
    u["zb"] = zc.astype(object).where(zc.notna(), "n/a")
    zt = u.groupby(["family", "split", "zb"]).size().unstack("zb", fill_value=0)
    doc["first95_z"] = {f"{a}|{b}": {k: int(v) for k, v in r.items()} for (a, b), r in zt.iterrows()}
    # all >= 0.95 prints by z
    zall = u.groupby(["family", "split"])[[f"z95_{z}" for z in Z_LABELS] + ["z95_na"]].sum()
    doc["all95_z"] = {f"{a}|{b}": {k: int(v) for k, v in r.items()} for (a, b), r in zall.iterrows()}
    # minutes left at the first >= 0.95 print
    tb = pd.cut(u["first95_tau"].astype(float), bins=list(TAU_EDGES), labels=list(TAU_LABELS), right=False)
    u["tb"] = tb.astype(object)
    tt = u.groupby(["family", "split", "tb"]).size().unstack("tb", fill_value=0)
    doc["first95_tau"] = {f"{a}|{b}": {k: int(v) for k, v in r.items()} for (a, b), r in tt.iterrows()}
    # coverage
    cov = u.groupby(["family", "split"])[[f"cov95_{k}" for k in COVER] + ["vol95_ok", "buy95"]].sum()
    doc["coverage"] = {f"{a}|{b}": {k: int(v) for k, v in r.items()} for (a, b), r in cov.iterrows()}
    doc["skipped"] = {"no_tape": int((t["fills"] < 0).sum()), "under_50_fills": int(((t["fills"] >= 0) & (t["fills"] < C5.MIN_FILLS)).sum())}
    # the power grid: markets (and clusters) with a buyable print >= theta at distance z >= k in the last hour
    grid_lines = ["| family | split | " + " | ".join(f">= {th:.2f} & z >= {k:g}" for th in THETAS for k in Z_GRID) + " |", "|---|---|" + "---|" * (len(THETAS) * len(Z_GRID))]
    grid = []
    fams = [f for f in FAMILY_ORDER if f in set(u["family"])]
    for fam in fams:
        for sp in SPLIT_NAMES:
            g = u[(u["family"] == fam) & (u["split"] == sp)]
            if not len(g) or fam.startswith("window no-ptb"):
                continue
            cells = {}
            for th in THETAS:
                mz = g[f"maxz_{th:.2f}"].astype(float)
                for k in Z_GRID:
                    hit = g[mz >= k]
                    cells[f"{th:.2f}|{k:g}"] = {"markets": len(hit), "clusters": int(hit["cluster"].nunique())}
            grid.append({"family": fam, "split": sp, "cells": cells})
            grid_lines.append(f"| {fam} | {sp} | " + " | ".join(f"{cells[f'{th:.2f}|{k:g}']['markets']:,} ({cells[f'{th:.2f}|{k:g}']['clusters']:,})" for th in THETAS for k in Z_GRID) + " |")
    doc["grid"] = grid
    (OUT / "grid_table.md").write_text("\n".join(grid_lines) + "\n")
    print("\n".join(grid_lines))
    usdz = u.groupby(["family", "split"])[[f"usd95_{z}" for z in Z_LABELS]].sum()
    doc["usd95_by_z"] = {f"{a}|{b}": {k: float(v) for k, v in r.items()} for (a, b), r in usdz.iterrows()}
    for name in ("spot_gaps.json", "binance_probe.json", "gamma_hourly_meta.json", "us/us_venue.json", "us/example.json"):
        p = OUT / name
        if p.exists():
            doc[name.split("/")[-1].split(".")[0]] = json.loads(p.read_text())
    if (OUT / "gamma_hourly.parquet").exists():
        g = pd.read_parquet(OUT / "gamma_hourly.parquet")
        gh = []
        for (coin, sp), x in g.groupby(["coin", "split"]):
            gh.append({
                "coin": coin, "split": sp, "events": int(x["event_id"].nunique()), "markets": len(x),
                "vol_gt0": int((x["volume"] > 0).sum()), "vol_ge1k": int((x["volume"] >= 1000).sum()),
                "vol_ge20k": int((x["volume"] >= 20000).sum()), "volume_total": float(x["volume"].sum()),
                "volume_median_traded": float(x.loc[x["volume"] > 0, "volume"].median()) if (x["volume"] > 0).any() else 0.0,
                "fees_on": int(x["fees_enabled"].sum()),
            })
        doc["gamma_hourly"] = gh
    if (OUT / "hourly_sample_counts.parquet").exists():
        hs = pd.read_parquet(OUT / "hourly_sample_counts.parquet")
        doc["hourly_sample"] = [
            {"day": d, "split": x["split"].iloc[0], "markets": len(x), "fills": int(x["fills"].sum()), "fills_median": float(x["fills"].median()),
             "ge50_fills": int((x["fills"] >= 50).sum()), "buy95": int(x["buy95"].sum()), "mk95": int((x["buy95"] > 0).sum()),
             "mk95_ge50": int(((x["buy95"] > 0) & (x["fills"] >= 50)).sum()), "usd95": float(x["usd95"].sum()), "bytes": int(x["bytes"].sum())}
            for d, x in hs.groupby("day")
        ]
    (HERE / "inventory.json").write_text(json.dumps(doc, indent=1, sort_keys=True, default=str) + "\n")
    (OUT / "main_table.md").write_text("\n".join(main_lines) + "\n")
    print("\n".join(main_lines))
    print(stage_tables(doc))
    return doc


def _md_table(head: list[str], rows: list[list[Any]]) -> list[str]:
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]


def stage_tables(doc: dict[str, Any]) -> str:
    """Every table of inventory.md, generated from the saved counts (written to $LAB8_DATA/tables.md)."""
    t = pd.read_parquet(OUT / "tape_counts.parquet")
    t["buy95"] = t["buy95"].fillna(0)
    u = t[(t["fills"] >= C5.MIN_FILLS) & (t["buy95"] > 0)].copy()
    fams = [f for f in FAMILY_ORDER if f in set(t["family"])]
    out: list[str] = []
    # T2 per symbol
    out += ["", "### T2. Markets per underlying (TRAIN / VAL / TEST): all, and with a buyable print >= 0.95 in the last 60 min", ""]
    rows = []
    for fam in fams:
        for sym in D5.SYMBOLS:
            g = t[(t["family"] == fam) & (t["symbol"] == sym)]
            if not len(g):
                continue
            a = [int((g["split"] == s).sum()) for s in SPLIT_NAMES]
            b = [int(((u["family"] == fam) & (u["symbol"] == sym) & (u["split"] == s)).sum()) for s in SPLIT_NAMES]
            rows.append([fam, sym.replace("USDT", ""), " / ".join(f"{x:,}" for x in a), " / ".join(f"{x:,}" for x in b)])
    out += _md_table(["family", "coin", "markets", "with a >= 0.95 print"], rows)
    # T4 z at first print
    out += ["", "### T4. Distance at the FIRST buyable >= 0.95 print of each market (markets by z = Phi^-1(q), lab 5's model, spot 10 s old)", ""]
    zc = pd.cut(u["first95_z"].astype(float), bins=list(Z_EDGES), labels=list(Z_LABELS), right=False)
    u["zb"] = zc.astype(object).where(zc.notna(), "n/a")
    rows = []
    for fam in fams:
        for sp in SPLIT_NAMES:
            g = u[(u["family"] == fam) & (u["split"] == sp)]
            if len(g):
                rows.append([fam, sp] + [int((g["zb"] == z).sum()) for z in (*Z_LABELS, "n/a")])
    out += _md_table(["family", "split", *[f"z {z}" for z in Z_LABELS], "no model"], rows)
    # T5 minutes left
    out += ["", "### T5. Time left at the first buyable >= 0.95 print (markets)", ""]
    tb = pd.cut(u["first95_tau"].astype(float), bins=list(TAU_EDGES), labels=list(TAU_LABELS), right=False).astype(object)
    rows = []
    for fam in fams:
        for sp in SPLIT_NAMES:
            m = (u["family"] == fam) & (u["split"] == sp)
            if m.any():
                rows.append([fam, sp] + [int((tb[m] == lab).sum()) for lab in TAU_LABELS] + [f"{u.loc[m, 'first95_tau'].median() / 60:.0f}"])
    out += _md_table(["family", "split", *TAU_LABELS, "median min left"], rows)
    # T6 notional by z (all >= 0.95 prints)
    out += ["", "### T6. Dollar notional of buyable >= 0.95 prints in the last 60 min, by distance z at the print", ""]
    rows = []
    for fam in fams:
        for sp in SPLIT_NAMES:
            g = u[(u["family"] == fam) & (u["split"] == sp)]
            if not len(g):
                continue
            usd = {z: float(g[f"usd95_{z}"].sum()) for z in Z_LABELS}
            lo = usd["<0"] + usd["0-1"] + usd["1-2"]
            hi5 = usd["5-6"] + usd[">=6"]
            na = float(g["usd95"].sum()) - sum(usd.values())
            rows.append([fam, sp, _fmt_usd(lo), _fmt_usd(usd["2-3"]), _fmt_usd(usd["3-4"]), _fmt_usd(usd["4-5"]), _fmt_usd(hi5), _fmt_usd(max(na, 0.0))])
    out += _md_table(["family", "split", "z < 2", "z 2-3", "z 3-4", "z 4-5", "z >= 5", "no model"], rows)
    # T7 coverage
    out += ["", "### T7. Binance 1 s coverage at the decision second (spot read 10 s before each buyable >= 0.95 print), all splits", ""]
    rows = []
    for fam in fams:
        g = u[u["family"] == fam]
        if not len(g):
            continue
        rows.append([fam, f"{int(g['buy95'].sum()):,}"] + [f"{int(g[f'cov95_{k}'].sum()):,}" for k in COVER] + [f"{int(g['vol95_ok'].sum()):,}"])
    out += _md_table(["family", "buyable >= 0.95 prints", "exact 1 s candle", "stale <= 5 s", "stale > 5 s", "no spot", "volatility defined"], rows)
    text = "\n".join(out) + "\n"
    (OUT / "tables.md").write_text(text)
    return text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--stage", required=True, choices=["tapes", "spot-gaps", "gamma-hourly", "hourly-sample", "binance-probe", "us-venue", "example", "report"])
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--days", nargs="*", default=["2026-07-15", "2026-08-25", "2026-09-25"])
    ap.add_argument("--max-pages", type=int, default=60, help="us-venue: pages of 100 events per state")
    ap.add_argument("--name", default="us_closed_summary.json", help="us-venue: summary file name")
    a = ap.parse_args(argv)
    if a.stage == "tapes":
        stage_tapes(a.procs)
    elif a.stage == "spot-gaps":
        print(json.dumps(stage_spot_gaps(), indent=1)[:4000])
    elif a.stage == "gamma-hourly":
        stage_gamma_hourly()
    elif a.stage == "hourly-sample":
        stage_hourly_sample(a.days)
    elif a.stage == "binance-probe":
        stage_binance_probe()
    elif a.stage == "us-venue":
        print(json.dumps(stage_us_venue(a.max_pages, a.name), indent=1))
    elif a.stage == "example":
        print(json.dumps(stage_example(), indent=1))
    else:
        stage_report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
