"""365-day check of the owner's distance rule on Binance BTCUSDT 1-minute closes (2025-10-12 .. 2026-10-11)."""
import io, sys, zipfile, math
from pathlib import Path
import numpy as np, pandas as pd, requests
S = Path(sys.argv[1]); K = S / "klines" / "BTCUSDT"; Y = S / "year"
def month_zip(ym):
    f = Y / f"{ym}.parquet"
    if f.exists(): return pd.read_parquet(f)
    u = f"https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-{ym}.zip"
    r = requests.get(u, timeout=60); r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content)); raw = z.read(z.namelist()[0])
    d = pd.read_csv(io.BytesIO(raw), header=None, usecols=[0, 4]); d.columns = ["ts", "close"]
    d["ts"] = d["ts"].astype("int64"); d["ts"] = np.where(d["ts"] > 1e14, d["ts"] // 1_000_000, d["ts"] // 1000)
    d.to_parquet(f); return d
def day_zip(day):
    f = Y / f"{day}.parquet"
    if f.exists(): return pd.read_parquet(f)
    u = f"https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1m/BTCUSDT-1m-{day}.zip"
    r = requests.get(u, timeout=60)
    if r.status_code != 200: return None
    z = zipfile.ZipFile(io.BytesIO(r.content)); raw = z.read(z.namelist()[0])
    d = pd.read_csv(io.BytesIO(raw), header=None, usecols=[0, 4]); d.columns = ["ts", "close"]
    d["ts"] = d["ts"].astype("int64"); d["ts"] = np.where(d["ts"] > 1e14, d["ts"] // 1_000_000, d["ts"] // 1000)
    d.to_parquet(f); return d
parts = [pd.read_parquet(K / f"{ym}.parquet") for ym in ["2025-09","2025-10","2025-11","2025-12","2026-01","2026-02","2026-03","2026-04","2026-05"]]
parts += [month_zip(ym) for ym in ["2026-06","2026-07","2026-08","2026-09"]]
for dd in range(1, 12):
    x = day_zip(f"2026-10-{dd:02d}")
    if x is not None: parts.append(x)
d = pd.concat(parts).drop_duplicates("ts").sort_values("ts")
close = pd.Series(d["close"].to_numpy(float), index=d["ts"].to_numpy("int64"))
start = int(pd.Timestamp("2025-10-12", tz="UTC").timestamp()); end = int(close.index.max()) - 60
print("data", pd.to_datetime(close.index.min(), unit="s"), "->", pd.to_datetime(close.index.max(), unit="s"), len(close))
# close of the minute ENDING at t = close of candle opening at t-60
c_end = close.copy(); c_end.index = c_end.index + 60
lr = np.log(c_end).diff()
idx = c_end.index
rows = []
for T in range(start - start % 3600 + 3600, end, 3600):
    if T not in c_end.index: continue
    fin = c_end.loc[T]
    for m in (10, 20, 30, 45):
        t0 = T - 60 * m
        if t0 not in c_end.index: continue
        win = lr.loc[t0 - 59 * 60: t0].dropna()
        if len(win) < 50: continue
        sig = math.sqrt(float((win ** 2).mean()))
        if sig <= 0: continue
        mv = math.log(fin / c_end.loc[t0]) / (sig * math.sqrt(m))
        rows.append((T, m, mv, sig))
r = pd.DataFrame(rows, columns=["T", "m", "move", "sig"])
r.to_parquet(Y / "moves.parquet")
print("hours", r["T"].nunique())
for m in (10, 20, 30, 45):
    x = r[r.m == m]
    for z in (3, 4, 5):
        miss = (x.move < -z).sum()
        print(f"m={m:2d} z>={z}: n={len(x)} misses={miss} rate={miss/len(x):.4%}")
w = r[(r.move < -4)].sort_values("move").head(15)
w["when"] = pd.to_datetime(w["T"], unit="s")
print(w[["when", "m", "move"]].to_string(index=False))
