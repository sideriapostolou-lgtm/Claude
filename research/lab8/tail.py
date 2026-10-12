"""Lab 8 tail table: how often a price that is FAR from a level with LITTLE time left still ends on the other side.

Research only, design evidence only. Nothing here trades, reads a key or touches production. The data lies OUTSIDE
every lab split (labs 4-8 read 2026-06-01 onward; this reads Binance spot 2019-01-01 .. 2026-05-31).

The owner's hypothesis (2026-10-12): "this is like 100 %, there's no way bitcoin drops below that and our bot got it
at 99 cents ... if you backtest ones like these it's probably 100 % when it's that far out". A YES "BTC at or above
K at time T" contract bought at a checkpoint m minutes before T while spot S sits z volatility units above K loses
exactly when the price falls more than z units in those m minutes. This script measures that miss rate on seven and
a half years of Binance 1-minute closes, with no prediction market involved.

Definitions (FIXED before any table was computed):

* Klines: Binance spot 1-minute klines, monthly archives
  ``https://data.binance.vision/data/spot/monthly/klines/<SYM>/1m/<SYM>-1m-<YYYY-MM>.zip``, sha256 checked against
  the ``.CHECKSUM`` file next to each archive. Close of a candle = the price at the END of its minute.
* Targets T: every top-of-hour (the close of the minute ending at T, the 1-minute proxy of the US venue's "60 BRTI
  seconds before T"), 2019-01-01 01:00 .. 2026-05-31 23:00 UTC; separately every noon ET (polymarket.com's noon
  ladder: the close of the 1-minute candle that OPENS at 12:00 ET, so T = 12:01 ET; DST from America/New_York).
* Checkpoints m in M_GRID minutes before T: S = the close of the minute ending at T - m.
* Volatility sigma (per sqrt(minute)) = sqrt(mean of squared 1-minute log returns) over the trailing 60 minutes and,
  separately, the trailing 1 day (1,440 minutes), both ENDING at the checkpoint (the last return is the one into S);
  at least 80 % of the window's returns present (lab 5's rule). Nothing after the checkpoint is read.
* move = ln(close_T / S) / (sigma * sqrt(m)). Miss of a YES-above contract with spot z units above K: move < -z.
  The other side (spot z units BELOW a level, buying "below" / the No of "above"): move >= z, reported as ``up``.
* Percent distance d (spot d above the level, K = S / (1 + d)): miss iff ln(close_T / S) < -ln(1 + d); ``up``: >=.
* Per cell (symbol, target set, vol, m, level, side): n hours, misses, rate, the normal-theory value (Phi(-z); with
  the 60-minute vol also Student t with 60 df, the exact null when sigma is estimated from 60 returns), a one-sided
  95 % exact binomial (Clopper-Pearson) upper bound (hours are the independent unit: one observation per hour per
  cell, cells at different m of one hour are NOT independent and are never pooled), a day-cluster bootstrap 95th
  percentile (B = 2000, seed 8; a cluster = the UTC day of the settling minute), and the days with a miss.
* Break-even at price p with the US taker fee 0.0695 p (1 - p) per contract: miss_be(p) = 1 - p - fee =
  (1 - p)(1 - 0.0695 p). A cell CLEARS price p WITH ROOM when max(binomial upper, bootstrap upper) < miss_be(p).

Stages (run with ``python -I``, it reads downloaded files)::

    python -I research/lab8/tail.py --stage fetch     # ~495 MB of archives, sha256 checked, kept as small parquet
    python -I research/lab8/tail.py --stage check     # coverage, the 1 s convention check, a synthetic self-test
    python -I research/lab8/tail.py --stage table     # all cells -> research/lab8/tail_2019_2025_cells.csv + .json
    python -I research/lab8/tail.py --stage report    # the generated half of research/lab8/tail_2019_2025.md

Data stays out of git under ``$LAB8_KLINES`` (default ``$SCRATCH/lab8/klines``): ``<SYM>/<YYYY-MM>.parquet``
(ts = candle open, unix s; close) with a ``.json`` sidecar (sha256, bytes, rows). Archives are deleted once checked
and parsed (disk is tight); their sha256 stays in the sidecar.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy import stats

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


D5 = _load("lab5_data", HERE.parent / "lab5" / "data.py")  # parse_klines, _get (backoff), SCRATCH

KL = Path(os.environ.get("LAB8_KLINES", str(D5.SCRATCH / "lab8" / "klines")))
MONTHLY = "https://data.binance.vision/data/spot/monthly/klines"
DAILY = "https://data.binance.vision/data/spot/daily/klines"
FIRST_MONTH = {"BTCUSDT": "2019-01", "ETHUSDT": "2019-01", "SOLUSDT": "2020-08"}  # SOL listed 2020-08 (inventory probe)
LAST_MONTH = "2026-05"
SYMBOLS = tuple(FIRST_MONTH)
START = int(datetime(2019, 1, 1, tzinfo=UTC).timestamp())  # first candle open on the grid
END = int(datetime(2026, 6, 1, tzinfo=UTC).timestamp())  # exclusive: lab splits start here
NMIN = (END - START) // 60
NY = ZoneInfo("America/New_York")

M_GRID = (1, 2, 5, 10, 15, 20, 30, 45, 60)
Z_GRID = (1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0)
D_GRID = (0.0025, 0.005, 0.01, 0.015, 0.02)
VOLS = {"60m": 60, "1d": 1440}
MIN_COVER = 0.8
PRICES = (0.95, 0.96, 0.97, 0.98, 0.99)
FEE_RATE = 0.0695  # Polymarket US taker fee coefficient (us_venue.md)
B = 2000
SEED = 8
CRASH_DAYS = ("2020-03-12", "2021-05-19", "2022-06-13", "2022-11-08", "2024-08-05")
N_DROPS_2025 = 5  # 2025's big drops are picked from the data: the days with the largest 60-minute BTC falls
EXAMPLE = {"m": 24, "z": (3.7, 4.0), "d": (0.0067, 0.0117)}  # the owner's 13:36 UTC buy (inventory.md, us_venue.md)

CELLS_CSV = HERE / "tail_2019_2025_cells.csv"
OUT_JSON = HERE / "tail_2019_2025.json"
OUT_MD = HERE / "tail_2019_2025.md"
MARKER = "<!-- everything below this line is generated by research/lab8/tail.py --stage report; do not edit -->"


# --------------------------------------------------------------------------------------------- fetch


def months(a: str, b: str) -> list[str]:
    y, m = map(int, a.split("-"))
    y1, m1 = map(int, b.split("-"))
    out = []
    while (y, m) <= (y1, m1):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def fetch_month(sym: str, mo: str) -> dict[str, Any]:
    """Download one monthly archive into its own new directory, check sha256, keep (ts, close) as parquet."""
    pq = KL / sym / f"{mo}.parquet"
    side = pq.with_suffix(".json")
    if pq.exists() and side.exists():
        return json.loads(side.read_text())
    url = f"{MONTHLY}/{sym}/1m/{sym}-1m-{mo}.zip"
    raw_dir = KL / "raw" / f"{sym}-1m-{mo}"
    shutil.rmtree(raw_dir, ignore_errors=True)
    raw_dir.mkdir(parents=True)
    raw = D5._get(url, as_json=False)
    published = D5._get(url + ".CHECKSUM", as_json=False).decode().split()[0]
    (raw_dir / f"{sym}-1m-{mo}.zip").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != published:
        raise RuntimeError(f"{sym} {mo}: sha256 {digest[:12]} != published {published[:12]}")
    df = D5.parse_klines(raw)[["ts", "close"]]
    pq.parent.mkdir(parents=True, exist_ok=True)
    tmp = pq.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(pq)
    info = {
        "symbol": sym,
        "month": mo,
        "url": url,
        "sha256": digest,
        "sha256_ok": True,
        "zip_bytes": len(raw),
        "rows": int(len(df)),
        "first_ts": int(df["ts"].iloc[0]),
        "last_ts": int(df["ts"].iloc[-1]),
    }
    side.write_text(json.dumps(info) + "\n")
    shutil.rmtree(raw_dir)
    return info


def stage_fetch(workers: int = 4) -> list[dict[str, Any]]:
    jobs = [(s, mo) for s in SYMBOLS for mo in months(FIRST_MONTH[s], LAST_MONTH)]
    done: list[dict[str, Any]] = []
    t0 = time.time()
    with ThreadPoolExecutor(workers) as ex:
        for k, info in enumerate(ex.map(lambda j: fetch_month(*j), jobs), 1):
            done.append(info)
            if k % 20 == 0 or k == len(jobs):
                mb = sum(d["zip_bytes"] for d in done) / 1e6
                print(f"  fetch {k}/{len(jobs)} {info['symbol']} {info['month']} ({mb:.0f} MB, {time.time() - t0:.0f}s)", flush=True)
    return done


def load_close(sym: str) -> np.ndarray:
    """Close on the full minute grid (index i = candle opening at START + 60 i); NaN where Binance has no candle."""
    df = pd.concat([pd.read_parquet(p) for p in sorted((KL / sym).glob("*.parquet"))], ignore_index=True)
    df = df.sort_values("ts").drop_duplicates("ts", keep="last")
    ts = df["ts"].to_numpy(np.int64)
    if (ts % 60).any():
        raise RuntimeError(f"{sym}: {int((ts % 60 != 0).sum())} candle open times not on a minute")
    i = (ts - START) // 60
    keep = (i >= 0) & (i < NMIN)
    c = np.full(NMIN, np.nan)
    c[i[keep]] = df["close"].to_numpy(float)[keep]
    if (c[np.isfinite(c)] <= 0).any():
        raise RuntimeError(f"{sym}: non-positive close")
    return c


# --------------------------------------------------------------------------------------------- core (vectorized)


def sigmas(c: np.ndarray) -> dict[str, np.ndarray]:
    """sigma[name][i] = sqrt(mean r^2) over the returns of candles i-w+1 .. i (closes i-w .. i), NaN under 80 %."""
    lc = np.log(c)
    r = np.full(len(c), np.nan)
    r[1:] = lc[1:] - lc[:-1]
    ok = np.isfinite(r)
    cs = np.concatenate([[0.0], np.cumsum(np.where(ok, r * r, 0.0))])
    cn = np.concatenate([[0], np.cumsum(ok)])
    out = {}
    for name, w in VOLS.items():
        s = np.full(len(c), np.nan)
        i = np.arange(w - 1, len(c))
        tot = cs[i + 1] - cs[i + 1 - w]
        cnt = cn[i + 1] - cn[i + 1 - w]
        good = cnt >= MIN_COVER * w
        s[i[good]] = np.sqrt(np.maximum(tot[good], 0.0) / cnt[good])
        out[name] = s
    return out


def hourly_targets() -> tuple[np.ndarray, np.ndarray]:
    """T (unix s, the end of the settling minute) and iT (grid index of the candle that closes at T)."""
    T = np.arange(START + 3600, END, 3600, dtype=np.int64)
    return T, (T - 60 - START) // 60


def noon_targets() -> tuple[np.ndarray, np.ndarray]:
    """T = 12:01 ET (the close of the candle opening at 12:00 ET), every day 2019-01-01 .. 2026-05-31."""
    days = pd.date_range("2019-01-01", "2026-05-31", freq="D")
    noon = np.array([int(datetime(d.year, d.month, d.day, 12, tzinfo=NY).timestamp()) for d in days], dtype=np.int64)
    return noon + 60, (noon - START) // 60


def observations(c: np.ndarray, sig: dict[str, np.ndarray], iT: np.ndarray, ms: tuple[int, ...]) -> dict[str, np.ndarray]:
    """lr[k, h] = ln(close_T / S) for checkpoint ms[k]; move[vol][k, h]; r1[k, h] = the log return of the minute
    right after the checkpoint (used only by the adverse-fill stress); NaN where any input is missing."""
    lr = np.full((len(ms), len(iT)), np.nan)
    r1 = np.full((len(ms), len(iT)), np.nan)
    mv = {v: np.full((len(ms), len(iT)), np.nan) for v in VOLS}
    cT = c[iT]
    for k, m in enumerate(ms):
        ic = iT - m  # the candle that closes at T - m minutes
        okc = ic >= 0
        S = np.full(len(iT), np.nan)
        S[okc] = c[ic[okc]]
        lr[k] = np.log(cT / S)
        r1[k] = np.log(c[iT - m + 1] / S)
        for v in VOLS:
            s = np.full(len(iT), np.nan)
            s[okc] = sig[v][ic[okc]]
            s[s <= 0] = np.nan
            mv[v][k] = lr[k] / (s * np.sqrt(m))
    return {"lr": lr, "r1": r1, **{f"move_{v}": mv[v] for v in VOLS}}


def cp_upper(k: np.ndarray, n: np.ndarray, conf: float = 0.95) -> np.ndarray:
    """One-sided exact binomial (Clopper-Pearson) upper bound; NaN when n = 0."""
    k = np.asarray(k, float)
    n = np.asarray(n, float)
    out = np.full(k.shape, np.nan)
    ok = n > 0
    full = ok & (k >= n)
    part = ok & ~full
    out[full] = 1.0
    out[part] = stats.beta.ppf(conf, k[part] + 1, n[part] - k[part])
    return out


def be_miss(p: float, fee_rate: float = FEE_RATE) -> float:
    return 1.0 - p - fee_rate * p * (1.0 - p)


def fee_rounded_10(p: float) -> float:
    """Fee per contract on a 10-contract fill, rounded to the cent per fill with banker's rounding (us_venue.md)."""
    f = Decimal(str(FEE_RATE)) * 10 * Decimal(str(p)) * (1 - Decimal(str(p)))
    return float(f.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)) / 10


# --------------------------------------------------------------------------------------------- check


def coverage(sym: str, c: np.ndarray) -> dict[str, Any]:
    first = datetime.strptime(FIRST_MONTH[sym], "%Y-%m").replace(tzinfo=UTC).timestamp()
    i0 = int((first - START) // 60)
    have = np.isfinite(c[i0:])
    miss = ~have
    edges = np.flatnonzero(np.diff(np.concatenate([[0], miss.astype(np.int8), [0]])))
    runs = list(zip(edges[::2], edges[1::2]))  # [start, end) of each run of missing minutes
    longest, at = max(((int(b - a), int(a)) for a, b in runs), default=(0, None))
    gaps_ge_10 = sum(1 for a, b in runs if b - a >= 10)
    return {
        "first_month": FIRST_MONTH[sym],
        "minutes_expected": int(len(have)),
        "minutes_present": int(have.sum()),
        "minutes_missing": int(miss.sum()),
        "gaps_10min_or_more": gaps_ge_10,
        "longest_gap_min": longest,
        "longest_gap_start_utc": datetime.fromtimestamp(START + 60 * (i0 + at), UTC).isoformat(timespec="minutes") if at is not None else None,
    }


def convention_check(day: str = "2026-05-31", sym: str = "BTCUSDT") -> dict[str, Any]:
    """The 1-minute close of the candle opening at t equals the 1-second close of the candle opening at t + 59
    (a day outside every split, from the daily 1 s archive, sha256 checked)."""
    url = f"{DAILY}/{sym}/1s/{sym}-1s-{day}.zip"
    raw_dir = KL / "raw" / f"{sym}-1s-{day}"
    shutil.rmtree(raw_dir, ignore_errors=True)
    raw_dir.mkdir(parents=True)
    raw = D5._get(url, as_json=False)
    published = D5._get(url + ".CHECKSUM", as_json=False).decode().split()[0]
    (raw_dir / f"{sym}-1s-{day}.zip").write_bytes(raw)
    ok = hashlib.sha256(raw).hexdigest() == published
    s1 = D5.parse_klines(raw).set_index("ts")
    shutil.rmtree(raw_dir)
    m1 = pd.read_parquet(KL / sym / f"{day[:7]}.parquet")
    d0 = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC).timestamp())
    m1 = m1[(m1["ts"] >= d0) & (m1["ts"] < d0 + 86400)]
    last_sec = s1["close"].reindex(m1["ts"].to_numpy() + 59).to_numpy()
    eq = np.isclose(m1["close"].to_numpy(), last_sec, rtol=0, atol=1e-9)
    first_sec = s1["close"].reindex(m1["ts"].to_numpy()).to_numpy()  # the close of the minute's FIRST second
    return {
        "day": day,
        "symbol": sym,
        "sha256_ok": bool(ok),
        "minutes": int(len(m1)),
        "close_equals_last_second": int(eq.sum()),
        "close_equals_first_second": int(np.isclose(m1["close"].to_numpy(), first_sec, rtol=0, atol=1e-9).sum()),
    }


def selftest() -> dict[str, Any]:
    """Synthetic random walk on the real grid (constant sigma, 0.5 % minutes missing). Checks: (1) the vectorized S,
    sigma and move equal a direct slice computation on 2,000 random (hour, m); (2) changing every close after a cut
    leaves every sigma and S at or before the cut unchanged (no look-ahead); (3) the miss rates match theory:
    1-day vol -> Phi(-z), 60-minute vol -> Student t with 60 df (within 4 binomial sd)."""
    rng = np.random.default_rng(80)
    c = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 1e-3, NMIN)))
    c[rng.random(NMIN) < 0.005] = np.nan
    sig = sigmas(c)
    T, iT = hourly_targets()
    obs = observations(c, sig, iT, M_GRID)
    lc = np.log(c)
    r = np.full(NMIN, np.nan)
    r[1:] = lc[1:] - lc[:-1]
    worst = 0.0
    for _ in range(2000):
        h = int(rng.integers(30, len(iT)))
        k = int(rng.integers(0, len(M_GRID)))
        m = M_GRID[k]
        ic = iT[h] - m
        for v, w in VOLS.items():
            win = r[ic - w + 1 : ic + 1]
            good = np.isfinite(win)
            s = np.sqrt(np.mean(win[good] ** 2)) if good.sum() >= MIN_COVER * w else np.nan
            direct = np.log(c[iT[h]] / c[ic]) / (s * np.sqrt(m))
            got = obs[f"move_{v}"][k, h]
            if np.isnan(direct) != np.isnan(got):
                raise AssertionError(f"selftest: NaN mismatch at h={h} m={m} vol={v}")
            if np.isfinite(direct):
                worst = max(worst, abs(direct - got) / max(1.0, abs(direct)))
    if worst > 1e-8:
        raise AssertionError(f"selftest: vectorized move differs from direct by {worst:.2e}")
    cut = NMIN // 2
    c2 = c.copy()
    c2[cut + 1 :] = c2[cut + 1 :] * np.exp(rng.normal(0, 0.05, NMIN - cut - 1))
    sig2 = sigmas(c2)
    for v in VOLS:
        a, b = sig[v][: cut + 1], sig2[v][: cut + 1]
        if not np.array_equal(np.isnan(a), np.isnan(b)) or not np.allclose(a[np.isfinite(a)], b[np.isfinite(b)], rtol=1e-12, atol=0):
            raise AssertionError(f"selftest: sigma before the cut changed ({v})")
    rows = []
    for k, m in enumerate(M_GRID):
        for v in VOLS:
            mv = obs[f"move_{v}"][k]
            mv = mv[np.isfinite(mv)]
            for z in (1.0, 2.0, 3.0):
                theory = float(stats.norm.cdf(-z)) if v == "1d" else float(stats.t.cdf(-z, df=60))
                got = float((mv < -z).mean())
                sd = np.sqrt(theory * (1 - theory) / len(mv))
                rows.append({"m": m, "vol": v, "z": z, "n": int(len(mv)), "rate": got, "theory": theory, "sd": float(sd), "ok": bool(abs(got - theory) <= 4 * sd)})
    bad = [r_ for r_ in rows if not r_["ok"]]
    return {"direct_max_rel_err": worst, "no_lookahead": True, "rate_checks": len(rows), "rate_checks_failed": len(bad), "failed": bad}


def stage_check() -> dict[str, Any]:
    out: dict[str, Any] = {"utc": datetime.now(UTC).isoformat(timespec="seconds"), "archives": {}, "coverage": {}}
    for sym in SYMBOLS:
        sides = [json.loads(p.read_text()) for p in sorted((KL / sym).glob("*.json"))]
        expected = months(FIRST_MONTH[sym], LAST_MONTH)
        out["archives"][sym] = {
            "months_expected": len(expected),
            "months_present": len(sides),
            "missing_months": sorted(set(expected) - {s["month"] for s in sides}),
            "sha256_ok": int(sum(1 for s in sides if s["sha256_ok"])),
            "zip_mb": round(sum(s["zip_bytes"] for s in sides) / 1e6, 1),
            "rows": int(sum(s["rows"] for s in sides)),
        }
        out["coverage"][sym] = coverage(sym, load_close(sym))
        print(f"  {sym}: {out['archives'][sym]} {out['coverage'][sym]}", flush=True)
    out["convention"] = convention_check()
    print(f"  convention: {out['convention']}", flush=True)
    out["selftest"] = selftest()
    print(f"  selftest: max rel err {out['selftest']['direct_max_rel_err']:.1e}, rate checks failed {out['selftest']['rate_checks_failed']}/{out['selftest']['rate_checks']}", flush=True)
    (KL / "check.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


# --------------------------------------------------------------------------------------------- table


def _cell_columns(obs: dict[str, np.ndarray]) -> tuple[list[dict[str, Any]], list[np.ndarray], list[np.ndarray]]:
    """Every cell's metadata, its miss indicator and its validity mask over the targets.

    Tails: ``down`` (spot above the level), ``up`` (spot below it), and ``adverse`` = the down tail kept only for
    hours where the minute AFTER the checkpoint moved toward the level (r1 <= 0): the latency / adverse-fill stress
    "the order only fills one minute late, and only when the price is coming at you". Not defined for m = 1 (the
    minute after the checkpoint is the settling minute itself)."""
    meta, miss, valid = [], [], []
    for k, m in enumerate(M_GRID):
        r1 = obs["r1"][k]
        adv = (r1 <= 0) & np.isfinite(r1) & (m > 1)
        for v in VOLS:
            mv = obs[f"move_{v}"][k]
            ok = np.isfinite(mv)
            for z in Z_GRID:
                for side, hit, base in (("down", mv < -z, ok), ("up", mv >= z, ok), ("adverse", mv < -z, ok & adv)):
                    meta.append({"kind": "z", "vol": v, "m": m, "level": z, "side": side})
                    miss.append(hit & base)
                    valid.append(base)
        lr = obs["lr"][k]
        ok = np.isfinite(lr)
        for d in D_GRID:
            thr = np.log1p(d)
            for side, hit, base in (("down", lr < -thr, ok), ("up", lr >= thr, ok), ("adverse", lr < -thr, ok & adv)):
                meta.append({"kind": "pct", "vol": "", "m": m, "level": d, "side": side})
                miss.append(hit & base)
                valid.append(base)
    return meta, miss, valid


def cells_for(sym: str, target: str, c: np.ndarray, sig: dict[str, np.ndarray]) -> tuple[pd.DataFrame, dict[str, Any]]:
    T, iT = hourly_targets() if target == "hourly" else noon_targets()
    obs = observations(c, sig, iT, M_GRID)
    day = (T - 60 - START) // 86400
    nd = int(day.max()) + 1
    meta, miss, valid = _cell_columns(obs)
    K = np.stack([np.bincount(day, weights=x.astype(float), minlength=nd) for x in miss], axis=1)
    N = np.stack([np.bincount(day, weights=x.astype(float), minlength=nd) for x in valid], axis=1)
    rng = np.random.default_rng(SEED)
    W = rng.multinomial(nd, np.full(nd, 1.0 / nd), size=B).astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        boot = (W @ K) / (W @ N)
    k = K.sum(axis=0)
    n = N.sum(axis=0)
    df = pd.DataFrame(meta)
    df.insert(0, "target", target)
    df.insert(0, "symbol", sym)
    df["n"] = n.astype(int)
    df["misses"] = k.astype(int)
    df["rate"] = np.where(n > 0, k / np.maximum(n, 1), np.nan)
    df["cp95"] = cp_upper(k, n)
    with warnings.catch_warnings():  # the adverse cells at m = 1 are empty by definition (all-NaN columns)
        warnings.simplefilter("ignore", RuntimeWarning)
        df["boot95"] = np.nanpercentile(boot, 95, axis=0)
    df["days_with_miss"] = (K > 0).sum(axis=0).astype(int)
    df["upper"] = np.fmax(df["cp95"], df["boot95"])
    # theory: Phi(-z) for z cells (t60 too with the 60-minute vol); for percent cells the 1-day-vol normal model averaged
    df["normal"] = np.nan
    df["t60"] = np.nan
    zc = df["kind"] == "z"
    df.loc[zc, "normal"] = stats.norm.cdf(-df.loc[zc, "level"].to_numpy(float))
    z60 = zc & (df["vol"] == "60m")
    df.loc[z60, "t60"] = stats.t.cdf(-df.loc[z60, "level"].to_numpy(float), df=60)
    for kk, m in enumerate(M_GRID):
        lr = obs["lr"][kk]
        s1d = np.full(len(iT), np.nan)
        ic = iT - m
        s1d[ic >= 0] = sig["1d"][ic[ic >= 0]]
        ok = np.isfinite(lr) & np.isfinite(s1d) & (s1d > 0)
        for d in D_GRID:
            sel = (df["kind"] == "pct") & (df["m"] == m) & (df["level"] == d)
            df.loc[sel, "normal"] = float(stats.norm.cdf(-np.log1p(d) / (s1d[ok] * np.sqrt(m))).mean())
    for p in PRICES:
        df[f"room_{p:.2f}"] = df["upper"] < be_miss(p)
    return df, {"T": T, "iT": iT, "obs": obs, "day": day}


def worst_misses(sym: str, T: np.ndarray, obs: dict[str, np.ndarray], vol: str, top: int = 20) -> list[dict[str, Any]]:
    mv = obs[f"move_{vol}"]
    has = np.isfinite(mv).any(axis=0)
    filled = np.where(np.isfinite(mv), mv, np.inf)
    kmin = filled.argmin(axis=0)
    vmin = filled[kmin, np.arange(mv.shape[1])]
    order = [h for h in np.argsort(vmin) if has[h]][:top]
    out = []
    for h in order:
        k = int(kmin[h])
        t = int(T[h])
        out.append({
            "symbol": sym,
            "vol": vol,
            "T_utc": datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d %H:%M"),
            "T_et": datetime.fromtimestamp(t, NY).strftime("%Y-%m-%d %H:%M"),
            "m": M_GRID[k],
            "z": float(-vmin[h]),
            "pct_move": float(np.expm1(obs["lr"][k, h]) * 100),
            "sigma_pct_per_hour": float(abs(obs["lr"][k, h]) / (-vmin[h]) / np.sqrt(M_GRID[k]) * np.sqrt(60) * 100),
            "normal_miss": float(stats.norm.cdf(vmin[h])),
        })
    return out


def drop_days_2025(c: np.ndarray, top: int = N_DROPS_2025) -> list[dict[str, Any]]:
    """The 2025 UTC days with the largest close-to-close 60-minute fall of BTCUSDT (picked from the data)."""
    lc = np.log(c)
    a = int((datetime(2025, 1, 1, tzinfo=UTC).timestamp() - START) // 60)
    b = int((datetime(2026, 1, 1, tzinfo=UTC).timestamp() - START) // 60)
    fall = lc[a:b] - lc[a - 60 : b - 60]
    day = (np.arange(a, b) * 60 + 60) // 86400  # UTC day of the candle's close, relative to START
    df = pd.DataFrame({"i": np.arange(a, b), "fall": fall, "day": day}).dropna()
    best = df.loc[df.groupby("day")["fall"].idxmin()].nsmallest(top, "fall")
    return [{
        "day": datetime.fromtimestamp(START + 60 * int(r.i) + 60, UTC).strftime("%Y-%m-%d"),
        "minute_utc": datetime.fromtimestamp(START + 60 * int(r.i) + 60, UTC).strftime("%H:%M"),
        "fall_60m_pct": float(np.expm1(r.fall) * 100),
    } for r in best.itertuples()]


def crash_rows(sym: str, ctx: dict[str, Any], days: list[str]) -> list[dict[str, Any]]:
    T, obs = ctx["T"], ctx["obs"]
    dkey = np.array([datetime.fromtimestamp(int(t) - 60, UTC).strftime("%Y-%m-%d") for t in T])
    out = []
    k60 = M_GRID.index(60)
    for d in days:
        h = np.flatnonzero(dkey == d)
        h = h[np.isfinite(obs["lr"][k60, h])]  # hours with data (SOL before its listing has none)
        row: dict[str, Any] = {"symbol": sym, "day": d, "hours": int(len(h))}
        if not len(h):
            out.append(row)
            continue
        row["worst_final_hour_pct"] = float(np.min(np.expm1(obs["lr"][k60, h])) * 100)
        for v in VOLS:
            mv = obs[f"move_{v}"][:, h]
            for z in (3.0, 4.0, 5.0):
                row[f"hours_miss_z{z:g}_{v}"] = int(((mv < -z).any(axis=0)).sum())
            if np.isfinite(mv).any():
                kk, hh = np.unravel_index(np.nanargmin(mv), mv.shape)
                row[f"worst_z_{v}"] = float(-mv[kk, hh])
                row[f"worst_m_{v}"] = int(M_GRID[kk])
                row[f"worst_at_{v}"] = datetime.fromtimestamp(int(T[h[hh]]), UTC).strftime("%H:%M")
        out.append(row)
    return out


def share_on_days(ctx: dict[str, Any], days: list[str]) -> dict[str, Any]:
    """Of all (hour, m) misses at z = 3, 4, 5 over the whole period, how many fall on the listed days."""
    T, obs = ctx["T"], ctx["obs"]
    dkey = np.array([datetime.fromtimestamp(int(t) - 60, UTC).strftime("%Y-%m-%d") for t in T])
    on = np.isin(dkey, days)
    res = {}
    for v in VOLS:
        mv = obs[f"move_{v}"]
        for z in (3.0, 4.0, 5.0):
            hit = mv < -z
            res[f"z{z:g}_{v}"] = {"all": int(hit.sum()), "on_days": int(hit[:, on].sum()), "hours_all": int(hit.any(axis=0).sum()), "hours_on_days": int(hit[:, on].any(axis=0).sum())}
    return res


def per_year(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    T, obs = ctx["T"], ctx["obs"]
    yr = np.array([datetime.fromtimestamp(int(t) - 60, UTC).year for t in T])
    out = []
    picks = (("1d", 15, 3.0), ("1d", 15, 4.0), ("1d", 30, 3.0), ("1d", 30, 4.0), ("60m", 30, 3.0), ("60m", 30, 4.0))
    for y in sorted(set(yr)):
        sel = yr == y
        row: dict[str, Any] = {"year": int(y)}
        for v, m, z in picks:
            mv = obs[f"move_{v}"][M_GRID.index(m), sel]
            ok = np.isfinite(mv)
            row[f"{v}_m{m}_z{z:g}"] = [int((mv[ok] < -z).sum()), int(ok.sum())]
        lr = obs["lr"][M_GRID.index(30), sel]
        ok = np.isfinite(lr)
        row["pct1_m30"] = [int((lr[ok] < -np.log1p(0.01)).sum()), int(ok.sum())]
        out.append(row)
    return out


def example_cells(c: np.ndarray, sig: dict[str, np.ndarray]) -> list[dict[str, Any]]:
    """The owner's buy: 24 minutes left, spot 3.7-4.0 one-day-vol units (0.67 %) above the strike; the owner's
    reading (1.17 %) too. Off the M_GRID, labelled as such."""
    T, iT = hourly_targets()
    m = EXAMPLE["m"]
    obs = observations(c, sig, iT, (m,))
    out = []
    for v in VOLS:
        mv = obs[f"move_{v}"][0]
        ok = np.isfinite(mv)
        for z in EXAMPLE["z"]:
            k = int((mv[ok] < -z).sum())
            out.append({"m": m, "kind": "z", "vol": v, "level": z, "n": int(ok.sum()), "misses": k, "rate": k / ok.sum(), "cp95": float(cp_upper(np.array([k]), np.array([ok.sum()]))[0]), "normal": float(stats.norm.cdf(-z))})
    lr = obs["lr"][0]
    ok = np.isfinite(lr)
    for d in EXAMPLE["d"]:
        k = int((lr[ok] < -np.log1p(d)).sum())
        out.append({"m": m, "kind": "pct", "vol": "", "level": d, "n": int(ok.sum()), "misses": k, "rate": k / ok.sum(), "cp95": float(cp_upper(np.array([k]), np.array([ok.sum()]))[0]), "normal": None})
    return out


def stage_table() -> dict[str, Any]:
    t0 = time.time()
    frames = []
    doc: dict[str, Any] = {"utc": datetime.now(UTC).isoformat(timespec="seconds"), "worst": {}, "crash": [], "share_on_crash_days": {}, "per_year": {}}
    btc = load_close("BTCUSDT")
    drops = drop_days_2025(btc)
    doc["drops_2025"] = drops
    crash_list = list(CRASH_DAYS) + [d["day"] for d in drops if d["day"] not in CRASH_DAYS]
    doc["crash_days"] = crash_list
    for sym in SYMBOLS:
        c = btc if sym == "BTCUSDT" else load_close(sym)
        sig = sigmas(c)
        for target in ("hourly", "noon_et"):
            df, ctx = cells_for(sym, target, c, sig)
            frames.append(df)
            if target == "hourly":
                for v in VOLS:
                    doc["worst"][f"{sym}_{v}"] = worst_misses(sym, ctx["T"], ctx["obs"], v)
                doc["crash"].extend(crash_rows(sym, ctx, crash_list))
                doc["share_on_crash_days"][sym] = share_on_days(ctx, crash_list)
                doc["per_year"][sym] = per_year(ctx)
            print(f"  {sym} {target}: {len(df)} cells, {time.time() - t0:.0f}s", flush=True)
        if sym == "BTCUSDT":
            doc["example"] = example_cells(c, sig)
    cells = pd.concat(frames, ignore_index=True)
    cells.to_csv(CELLS_CSV, index=False, float_format="%.6g")
    doc["break_even"] = [{"p": p, "fee": FEE_RATE * p * (1 - p), "be_miss": be_miss(p), "fee_10_rounded": fee_rounded_10(p), "be_miss_10_rounded": 1 - p - fee_rounded_10(p)} for p in PRICES]
    chk = KL / "check.json"
    doc["check"] = json.loads(chk.read_text()) if chk.exists() else None
    OUT_JSON.write_text(json.dumps(doc, indent=1) + "\n")
    print(f"lab8 tail: {len(cells)} cells -> {CELLS_CSV.name}, {OUT_JSON.name} ({time.time() - t0:.0f}s)", flush=True)
    return doc


# --------------------------------------------------------------------------------------------- report


def _pct(x: float, digits: int = 3) -> str:
    if x is None or not np.isfinite(x):
        return "-"
    return f"{100 * x:.{digits}f} %"


def _fmt_level(kind: str, x: float) -> str:
    return f"z={x:g}" if kind == "z" else f"{100 * x:g} %"


def _matrix(cells: pd.DataFrame, sym: str, target: str, kind: str, vol: str, side: str, what: str) -> list[str]:
    sub = cells[(cells["symbol"] == sym) & (cells["target"] == target) & (cells["kind"] == kind) & (cells["vol"] == vol) & (cells["side"] == side)]
    levels = Z_GRID if kind == "z" else D_GRID
    head = "| m | n | " + " | ".join(_fmt_level(kind, x) for x in levels) + " |"
    lines = [head, "|" + "---|" * (len(levels) + 2)]
    for m in M_GRID:
        row = sub[sub["m"] == m].set_index("level")
        cellv = []
        for x in levels:
            r = row.loc[x]
            if r["n"] == 0:
                cellv.append("-")
            elif what == "rate":
                cellv.append(f"{_pct(r['rate'])} ({int(r['misses'])})")
            elif what == "upper":
                cellv.append(_pct(r["upper"]))
            elif what == "room":
                ok = [p for p in PRICES if r[f"room_{p:.2f}"]]
                cellv.append(f"{max(ok):.2f}" if ok else ("none" if r["rate"] < be_miss(PRICES[0]) else "above"))
        n = int(row["n"].max())
        lines.append(f"| {m} | {n:,} | " + " | ".join(cellv) + " |")
    if what == "rate":
        th = sub[sub["m"] == M_GRID[0]].set_index("level")
        if kind == "z":
            lines.append("| normal Phi(-z) | | " + " | ".join(_pct(th.loc[x, "normal"], 4) for x in levels) + " |")
            if vol == "60m":
                lines.append("| Student t, 60 df | | " + " | ".join(_pct(th.loc[x, "t60"], 4) for x in levels) + " |")
    return lines


def _pct_theory(cells: pd.DataFrame, sym: str, target: str, side: str) -> list[str]:
    sub = cells[(cells["symbol"] == sym) & (cells["target"] == target) & (cells["kind"] == "pct") & (cells["side"] == side)]
    lines = ["| m | " + " | ".join(_fmt_level("pct", d) for d in D_GRID) + " |", "|" + "---|" * (len(D_GRID) + 1)]
    for m in M_GRID:
        row = sub[sub["m"] == m].set_index("level")
        lines.append(f"| {m} | " + " | ".join(_pct(row.loc[d, "normal"], 4) for d in D_GRID) + " |")
    return lines


def stage_report() -> None:
    cells = pd.read_csv(CELLS_CSV, keep_default_na=False, na_values=[""])
    cells["vol"] = cells["vol"].fillna("")
    doc = json.loads(OUT_JSON.read_text())
    L: list[str] = [MARKER, "", "## G. Generated tables", ""]
    chk = doc.get("check") or {}
    L += ["### G1. Data and checks", "", "| symbol | months (sha256 ok / expected) | zip MB | minutes present | missing | gaps >= 10 min | longest gap |", "|---|---|---|---|---|---|---|"]
    for sym in SYMBOLS:
        a = chk.get("archives", {}).get(sym, {})
        cv = chk.get("coverage", {}).get(sym, {})
        L.append(f"| {sym} (from {FIRST_MONTH[sym]}) | {a.get('sha256_ok')} / {a.get('months_expected')} | {a.get('zip_mb')} | {cv.get('minutes_present', 0):,} | {cv.get('minutes_missing', 0):,} | {cv.get('gaps_10min_or_more')} | {cv.get('longest_gap_min')} min from {cv.get('longest_gap_start_utc')} |")
    cv = chk.get("convention", {})
    st = chk.get("selftest", {})
    L += ["", f"Convention check ({cv.get('symbol')} {cv.get('day')}, 1 s archive sha256 ok: {cv.get('sha256_ok')}): the 1-minute close equals the close of the minute's LAST second in {cv.get('close_equals_last_second')} of {cv.get('minutes')} minutes (its first second: {cv.get('close_equals_first_second')}).",
          f"Synthetic self-test: vectorized move vs direct slice max relative error {st.get('direct_max_rel_err', float('nan')):.1e}; no look-ahead (sigma and S before a cut unchanged when every later close is rewritten); {st.get('rate_checks', 0) - st.get('rate_checks_failed', 0)} of {st.get('rate_checks')} theory checks within 4 sd (1-day vol vs Phi(-z), 60-minute vol vs Student t 60 df).", ""]
    L += ["### G2. Break-even miss rate with the US fee", "", "| price p | fee 0.0695 p (1-p) | break-even win rate | break-even miss rate | gain per $1 if never wrong | wins to pay for one loss | 10-contract ticket, fee rounded to the cent: break-even miss |", "|---|---|---|---|---|---|---|"]
    for r in doc["break_even"]:
        p, fee, be = r["p"], r["fee"], r["be_miss"]
        L.append(f"| {p:.2f} | {fee:.5f} | {_pct(1 - be, 3)} | {_pct(be, 3)} | {_pct(be / (p + fee), 2)} | {(p + fee) / be:.1f} | {_pct(r['be_miss_10_rounded'], 2)} |")
    L.append("")
    sec = 3
    for sym in SYMBOLS:
        for target in ("hourly", "noon_et"):
            if sym != "BTCUSDT" and target == "noon_et":
                continue
            tname = "top-of-hour closes" if target == "hourly" else "noon-ET closes (12:01 ET)"
            for v in VOLS:
                L += [f"### G{sec}. {sym}, {tname}, z with the trailing {v} vol: miss rate P(move < -z) (misses)", ""]
                L += _matrix(cells, sym, target, "z", v, "down", "rate") + [""]
                if sym == "BTCUSDT":
                    L += [f"95 % upper bound (the larger of exact binomial and day-cluster bootstrap):", ""]
                    L += _matrix(cells, sym, target, "z", v, "down", "upper") + [""]
                L += ["Highest price 0.95-0.99 the cell clears WITH ROOM (upper bound below break-even); 'none' = point below break-even at 0.95 but no room; 'above' = point at or above it:", ""]
                L += _matrix(cells, sym, target, "z", v, "down", "room") + [""]
                sec += 1
            L += [f"### G{sec}. {sym}, {tname}, percent distance: miss rate P(close_T < S / (1 + d)) (misses)", ""]
            L += _matrix(cells, sym, target, "pct", "", "down", "rate") + [""]
            if sym == "BTCUSDT":
                L += ["Normal model with the trailing 1-day vol, averaged over the same hours:", ""] + _pct_theory(cells, sym, target, "down") + [""]
                L += ["95 % upper bound:", ""] + _matrix(cells, sym, target, "pct", "", "down", "upper") + [""]
            L += ["Highest price cleared with room:", ""] + _matrix(cells, sym, target, "pct", "", "down", "room") + [""]
            sec += 1
    L += [f"### G{sec}. The other side (spot BELOW the level, miss = close_T at or above it), BTCUSDT top-of-hour", ""]
    for v in VOLS:
        L += [f"Trailing {v} vol, P(move >= z) (misses):", ""] + _matrix(cells, "BTCUSDT", "hourly", "z", v, "up", "rate") + [""]
    L += ["Percent distance, P(close_T >= S (1 + d)) (misses):", ""] + _matrix(cells, "BTCUSDT", "hourly", "pct", "", "up", "rate") + [""]
    sec += 1
    L += [f"### G{sec}. Latency / adverse-fill stress, BTCUSDT top-of-hour: the signal at checkpoint m, kept only when the NEXT minute moved toward the level (the order fills late, and only when the price is coming at you); the strike stays where the signal put it", ""]
    for v in VOLS:
        L += [f"Trailing {v} vol, P(move < -z | next minute <= 0) (misses):", ""] + _matrix(cells, "BTCUSDT", "hourly", "z", v, "adverse", "rate") + [""]
        L += ["Highest price cleared with room:", ""] + _matrix(cells, "BTCUSDT", "hourly", "z", v, "adverse", "room") + [""]
    L += ["Percent distance (misses):", ""] + _matrix(cells, "BTCUSDT", "hourly", "pct", "", "adverse", "rate") + [""]
    L += ["Highest price cleared with room:", ""] + _matrix(cells, "BTCUSDT", "hourly", "pct", "", "adverse", "room") + [""]
    sec += 1
    L += [f"### G{sec}. The worst misses (per hour, the checkpoint with the most negative move)", ""]
    for key, top in (("BTCUSDT_1d", 20), ("BTCUSDT_60m", 20), ("ETHUSDT_1d", 10), ("SOLUSDT_1d", 10)):
        rows = doc["worst"][key][:top]
        sym, v = key.split("_")
        L += [f"{sym}, trailing {v} vol, top {top}:", "", "| T (UTC) | T (ET) | m | z (units of fall) | % move in the last m min | vol (% per hour) | normal-theory chance |", "|---|---|---|---|---|---|---|"]
        for r in rows:
            L.append(f"| {r['T_utc']} | {r['T_et']} | {r['m']} | {r['z']:.2f} | {r['pct_move']:+.2f} % | {r['sigma_pct_per_hour']:.2f} | {r['normal_miss']:.1e} |")
        L.append("")
    sec += 1
    drops = ", ".join(f"{d['day']} ({d['fall_60m_pct']:+.2f} % in the 60 min to {d['minute_utc']} UTC)" for d in doc["drops_2025"])
    L += [f"### G{sec}. Known crash days (UTC) and 2025's five largest 60-minute BTC falls ({drops})", "",
          "Hours of the day (top-of-hour targets) with a miss at some checkpoint, by vol window; worst = the largest z that still missed that day.", "",
          "| symbol | day | hours | final-hour worst % | 60m vol: hours missing at z=3 / 4 / 5 | worst z (m, T) | 1d vol: hours missing at z=3 / 4 / 5 | worst z (m, T) |", "|---|---|---|---|---|---|---|---|"]
    for r in doc["crash"]:
        if r["hours"] == 0:
            L.append(f"| {r['symbol']} | {r['day']} | 0 | - | - | - | - | - |")
            continue
        a = f"{r['hours_miss_z3_60m']} / {r['hours_miss_z4_60m']} / {r['hours_miss_z5_60m']}"
        b = f"{r['hours_miss_z3_1d']} / {r['hours_miss_z4_1d']} / {r['hours_miss_z5_1d']}"
        L.append(f"| {r['symbol']} | {r['day']} | {r['hours']} | {r['worst_final_hour_pct']:+.2f} % | {a} | {r.get('worst_z_60m', float('nan')):.2f} ({r.get('worst_m_60m')}, {r.get('worst_at_60m')}) | {b} | {r.get('worst_z_1d', float('nan')):.2f} ({r.get('worst_m_1d')}, {r.get('worst_at_1d')}) |")
    L += ["", "Share of ALL (hour, checkpoint) misses of the whole period that fell on these days:", "", "| symbol | cell | misses (all m) | on these days | hours with a miss | on these days |", "|---|---|---|---|---|---|"]
    for sym, d in doc["share_on_crash_days"].items():
        for key, s in d.items():
            L.append(f"| {sym} | {key} | {s['all']:,} | {s['on_days']:,} | {s['hours_all']:,} | {s['hours_on_days']:,} |")
    sec += 1
    L += ["", f"### G{sec}. BTCUSDT by year (misses / hours)", ""]
    keys = [k for k in doc["per_year"]["BTCUSDT"][0] if k != "year"]
    L += ["| year | " + " | ".join(keys) + " |", "|" + "---|" * (len(keys) + 1)]
    for r in doc["per_year"]["BTCUSDT"]:
        L.append(f"| {r['year']} | " + " | ".join(f"{r[k][0]} / {r[k][1]:,} ({_pct(r[k][0] / r[k][1] if r[k][1] else float('nan'), 2)})" for k in keys) + " |")
    sec += 1
    L += ["", f"### G{sec}. The owner's buy, re-asked of history (m = 24, off the grid)", "", "| distance | vol | hours | misses | rate | 95 % binomial upper | normal |", "|---|---|---|---|---|---|---|"]
    for r in doc["example"]:
        lvl = f"z = {r['level']:g}" if r["kind"] == "z" else f"{100 * r['level']:.2f} %"
        L.append(f"| {lvl} | {r['vol'] or '-'} | {r['n']:,} | {r['misses']} | {_pct(r['rate'])} | {_pct(r['cp95'])} | {_pct(r['normal'], 4) if r['normal'] is not None else '-'} |")
    L.append("")
    head = OUT_MD.read_text().split(MARKER)[0].rstrip() + "\n\n" if OUT_MD.exists() else "# Lab 8 tail table (2019-2025)\n\n(reading to be written)\n\n"
    OUT_MD.write_text(head + "\n".join(L) + "\n")
    print(f"wrote {OUT_MD}", flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--stage", choices=("fetch", "check", "table", "report", "all"), required=True)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    if a.stage in ("fetch", "all"):
        stage_fetch(a.workers)
    if a.stage in ("check", "all"):
        stage_check()
    if a.stage in ("table", "all"):
        stage_table()
    if a.stage in ("report", "all"):
        stage_report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
