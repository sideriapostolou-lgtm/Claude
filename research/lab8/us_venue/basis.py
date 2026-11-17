"""Raw BRTI (gateway 1-minute closes: the last raw index tick of each minute) against raw Binance BTCUSDT (lab 5's
1 s klines: the close of the kline opening at the same second).

usage: python -I basis.py LAB5_SPOT_DIR OUT.json
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gw  # noqa: E402

spot_dir = Path(sys.argv[1])
start = int(datetime(2026, 10, 5, 15, 30, tzinfo=UTC).timestamp())
end = int(datetime(2026, 10, 9, 0, 0, tzinfo=UTC).timestamp())
brti = {}
t = start
while t < end:
    r = gw.get("/asset-prices/history", {"assets": "crypto:btc", "from": t, "to": min(t + 3540 * 60, end),
                                          "bucket": "ASSET_PRICE_BUCKET_1M"})
    for c in (r.get("series") or [{}])[0].get("candles") or []:
        if c.get("tickCount"):
            brti[c["timestamp"] + 60] = float(c["close"])  # value at the boundary that closes this minute
    t += 3540 * 60
days = sorted({datetime.fromtimestamp(x, UTC).strftime("%Y-%m-%d") for x in range(start - 86400, end, 86400)})
bn = pd.concat([pd.read_parquet(spot_dir / f"{d}.parquet") for d in days if (spot_dir / f"{d}.parquet").exists()])
bn = bn.set_index("ts")["close"].sort_index()
roll = bn  # raw Binance: close of the 1 s kline opening at T-1 (BRTI 1M close is the raw tick at T-1)
rows = []
for T, v in sorted(brti.items()):
    k = T - 1
    if k in roll.index and not np.isnan(roll.loc[k]):
        rows.append((T, v, float(roll.loc[k])))
df = pd.DataFrame(rows, columns=["T", "brti", "binance"])
df["bp"] = (df.brti / df.binance - 1) * 1e4
q = df.bp.quantile([0.001, 0.01, 0.05, 0.5, 0.95, 0.99, 0.999]).round(2).to_dict()
res = {"n_minutes": int(len(df)), "from": datetime.fromtimestamp(int(df["T"].min()), UTC).isoformat(),
       "to": datetime.fromtimestamp(int(df["T"].max()), UTC).isoformat(), "bp_mean": round(df.bp.mean(), 2),
       "bp_sd": round(df.bp.std(), 2), "bp_quantiles": q, "abs_bp_max": round(df.bp.abs().max(), 2),
       "demeaned_sd_bp": round((df.bp - df.bp.mean()).std(), 2)}
print(json.dumps(res, indent=1))
Path(sys.argv[2]).write_text(json.dumps(res, indent=1))
