"""Live Jupiter Ultra round-trip cost check at the F4 finalist's position size and market cap (auditor).

Quotes only: GET lite-api.jup.ag/ultra/v1/order without a taker, nothing is signed or sent.
For each coin: buy $20 of SOL -> token, then quote selling the quoted token amount back -> SOL.
measured round trip = 1 - SOL back / SOL in. The model side uses the auditor's own cost code
(indep_f4.Costs, no MEV buffer and no network fee, because quotes carry neither).

    python research/lab/audit/live_costs.py MINT[,MINT...]  -> LAB/audit/live_costs.json
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indep_f4 as I  # noqa: E402  (auditor's own module; no harness/costs import)

SOL_MINT = "So11111111111111111111111111111111111111112"
ULTRA = "https://lite-api.jup.ag/ultra/v1/order"


def get(url: str, params: dict) -> dict:
    for attempt in range(6):
        r = requests.get(url, params=params, timeout=30)
        time.sleep(1.1)  # ~1 req/s etiquette
        if r.status_code == 200:
            return r.json()
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{url} {params}: {r.status_code} {r.text[:200]}")


def main(mints: list[str], usd: float = 20.0) -> list[dict]:
    sol_px = float(get("https://lite-api.jup.ag/price/v3", {"ids": SOL_MINT})[SOL_MINT]["usdPrice"])
    lamports = int(usd / sol_px * 1e9)
    model = I.Costs()
    rows = []
    for mint in mints:
        # forward (buy then sell) and reverse (sell then buy) round trips, twice: a price drift between
        # the two quotes biases the forward and reverse legs in opposite directions, the mean cancels it.
        fw, rv, routes, fees = [], [], set(), set()
        for _ in range(2):
            buy = get(ULTRA, {"inputMint": SOL_MINT, "outputMint": mint, "amount": lamports})
            tok = int(buy["outAmount"])
            sell = get(ULTRA, {"inputMint": mint, "outputMint": SOL_MINT, "amount": tok})
            back = int(sell["outAmount"])
            fw.append(1 - back / lamports)
            sell2 = get(ULTRA, {"inputMint": mint, "outputMint": SOL_MINT, "amount": tok})
            lam2 = int(sell2["outAmount"])
            buy2 = get(ULTRA, {"inputMint": SOL_MINT, "outputMint": mint, "amount": lam2})
            rv.append(1 - int(buy2["outAmount"]) / tok)
            for q in (buy, sell, sell2, buy2):
                routes.add(" > ".join(h["swapInfo"]["label"] for h in q.get("routePlan", [])))
                fees.add(q.get("feeBps"))
        measured = 100 * (sum(fw) + sum(rv)) / (len(fw) + len(rv))
        # mid from the last buy/sell pair (geometric mean of the effective prices), 6 decimals
        p_sol = math.sqrt((lamports / tok) * (back / tok)) * 1e6 / 1e9
        price_usd = p_sol * sol_px
        mcap = price_usd * 1e9
        side = I.pool_fee_pct(mcap / sol_px) + I.ULTRA_PCT  # quotes carry no MEV buffer
        x = model.quote_reserve_usd(price_usd, sol_px)
        net = usd * (1 - side / 100)
        tokens = net / price_usd * x / (x + net)
        val = tokens * price_usd
        back_model = val * x / (x + val) * (1 - side / 100)
        model_rt = (1 - back_model / usd) * 100
        full = I.Costs()
        t2 = full.buy(usd, price_usd, sol_px)
        full_rt = (usd - full.sell(t2, price_usd, sol_px) + 2 * full.network_usd(sol_px)) / usd * 100
        row = {"mint": mint, "mcap_usd": round(mcap), "mcap_sol": round(mcap / sol_px), "sol_usd": sol_px,
               "routes": sorted(routes), "ultra_fee_bps": sorted(fees, key=str),
               "forward_rt_pct": [round(100 * x, 3) for x in fw], "reverse_rt_pct": [round(100 * x, 3) for x in rv],
               "measured_rt_pct": round(measured, 3), "model_rt_pct_no_mev_no_network": round(model_rt, 3),
               "model_rt_pct_full": round(full_rt, 3), "diff_pp": round(measured - model_rt, 3),
               "ts": time.time()}
        rows.append(row)
        print(json.dumps(row), flush=True)
    out = I.OUT / "live_costs.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"usd": usd, "sol_usd": sol_px, "rows": rows}, indent=1))
    return rows


if __name__ == "__main__":
    main(sys.argv[1].split(","))
