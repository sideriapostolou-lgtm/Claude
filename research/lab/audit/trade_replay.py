"""Trade-by-trade replay of the F4 finalist's trades (auditor).

The lab's backtest only has 1-minute candles, so a stop that triggers inside a rug candle is booked at an
assumed price ("half": halfway between the stop and the bar low). This script fetches the actual swaps
(swap-api.pump.fun/v2/coins/{mint}/trades, newest-first pages, cursor = "<22 zeros>-<end_ms>") around every
F4 trade and replays the same rules on the real trade sequence with a reaction latency L:

* entry: decision at the bar close T; the buy lands at T + L and fills at the pool price after the last
  swap at or before T + L;
* stop / take-profit: the first swap whose price crosses the level at time t*; the sell lands at t* + L
  and fills at the pool price after the last swap at or before t* + L;
* time stop: the pool price at entry + 15 min + L.

Prices are swap-api's per-swap ``priceUsd`` (checked against ``fillPriceUsd``); costs are the auditor's
cost model (indep_f4.Costs). Network etiquette: <= 120 requests/min (limit 1000/min), backoff on 429.

    python research/lab/audit/trade_replay.py fetch LAB/audit/indep_test_q98.json [more.json ...]
    python research/lab/audit/trade_replay.py replay LAB/audit/indep_test_q98.json [--lat 2]
"""

from __future__ import annotations

import gzip
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indep_f4 as I  # noqa: E402

URL = "https://swap-api.pump.fun/v2/coins/{mint}/trades"
DIR = I.OUT / "trades"
_next = [0.0]


def _get(mint: str, cursor: str) -> dict:
    back = 5.0
    for _ in range(8):
        wait = _next[0] - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _next[0] = time.monotonic() + 0.5  # <= 120 req/min
        r = requests.get(URL.format(mint=mint), params={"limit": 100, "cursor": cursor}, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            ra = r.headers.get("Retry-After")
            time.sleep(float(ra) + 1 if ra and ra.isdigit() else back)
            back = min(back * 2, 120)
            continue
        raise RuntimeError(f"{mint}: HTTP {r.status_code} {r.text[:200]}")
    raise RuntimeError(f"{mint}: gave up")


def _ts(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def fetch_window(mint: str, start: float, end: float, max_pages: int = 60) -> tuple[list[dict], bool]:
    cursor = f"0000000000000000000000-{int(end * 1000)}"
    out = []
    for _ in range(max_pages):
        page = _get(mint, cursor)
        batch = page.get("trades") or []
        for t in batch:
            ts = _ts(t["timestamp"])
            if ts < start:
                return out, True
            if ts < end:
                out.append(t)
        pg = page.get("pagination") or {}
        if not batch or not pg.get("hasMore"):
            return out, True
        cursor = pg["nextCursor"]
    return out, False


def fetch(paths: list[str]) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    for p in paths:
        for t in json.loads(Path(p).read_text())["trades"]:
            if "entry_ts" not in t:
                continue
            f = DIR / f"{t['mint']}_{int(t['entry_ts'])}.json.gz"
            if f.exists():
                continue
            start, end = t["decision_ts"] - 120, t["entry_ts"] + 15 * 60 + 180
            rows, complete = fetch_window(t["mint"], start, end)
            rows.sort(key=lambda r: r.get("slotIndexId") or "")
            with gzip.open(f, "wt") as fh:
                json.dump({"mint": t["mint"], "symbol": t["symbol"], "start": start, "end": end,
                           "complete": complete, "trades": rows}, fh)
            print(f"{t['symbol']:10s} {len(rows):5d} swaps complete={complete}", flush=True)


def _series(doc: dict) -> list[tuple[float, float, dict]]:
    """(ts, pool price after the swap, swap) in chain order."""
    out = []
    for r in doc["trades"]:
        out.append((_ts(r["timestamp"]), float(r["priceUsd"]), r))
    return out


def price_at(series, t: float) -> float | None:
    """Pool price after the last swap at or before t (None before the first swap)."""
    px = None
    for ts, p, _ in series:
        if ts > t:
            break
        px = p
    return px


def replay(path: str, lat: float = 2.0, tp: float = 0.30, sl: float = 0.15, hold_s: float = 900.0) -> dict:
    sol = I.Sol()
    cost = I.Costs()
    rows = []
    for t in json.loads(Path(path).read_text())["trades"]:
        if "entry_ts" not in t:
            continue
        f = DIR / f"{t['mint']}_{int(t['entry_ts'])}.json.gz"
        doc = json.loads(gzip.open(f, "rt").read())
        s = _series(doc)
        T = t["decision_ts"]
        entry = price_at(s, T + lat)
        last_before = price_at(s, T)
        stop, tpp = entry * (1 - sl), entry * (1 + tp)
        why, t_x, px = None, None, None
        for ts, p, r in s:
            if ts <= T + lat:
                continue
            if ts >= T + lat + hold_s:
                break
            if p <= stop:
                why, t_x = "stop", ts
                break
            if p >= tpp:
                why, t_x = "take_profit", ts
                break
        if why is None:
            why, t_x = "time_stop", T + lat + hold_s - lat
        px = price_at(s, t_x + lat)
        s0, s1 = sol.at(T), sol.at(t_x)
        tok = cost.buy(20.0, entry, s0)
        back = cost.sell(tok, px, s1)
        ret = (back - cost.network_usd(s1) - 20 - cost.network_usd(s0)) / 20 * 100
        # what was the biggest single swap in the crossing second (rug signature)?
        crash = None
        if why == "stop":
            sec = [r for ts, p, r in s if abs(ts - t_x) < 1.0 and r["type"] == "sell"]
            big = max(sec, key=lambda r: float(r["amountUsd"])) if sec else None
            if big:
                crash = {"largest_sell_usd": round(float(big["amountUsd"]), 0), "wallet": big["userAddress"],
                         "sells_in_that_second": len(sec),
                         "price_before": price_at(s, t_x - 1), "price_after_second": price_at(s, t_x + 1)}
        rows.append({"symbol": t["symbol"], "mint": t["mint"], "candle_entry": t["entry_mid"],
                     "trade_entry": entry, "last_swap_before_decision": last_before,
                     "entry_slip_pct": round(100 * (entry / t["entry_mid"] - 1), 3),
                     "candle_exit": t["exit_reason"], "candle_ret_pct": round(t["ret_pct"], 2),
                     "trade_exit": why, "trade_exit_px_vs_entry_pct": round(100 * (px / entry - 1), 2),
                     "trade_ret_pct": round(ret, 2), "hold_s": round(t_x + lat - T - lat), "n_swaps": len(s),
                     "complete": doc["complete"], "crash": crash})
    import numpy as np
    out = {"source": path, "latency_s": lat, "n": len(rows),
           "mean_candle_ret_pct": round(float(np.mean([r["candle_ret_pct"] for r in rows])), 2),
           "mean_trade_ret_pct": round(float(np.mean([r["trade_ret_pct"] for r in rows])), 2),
           "rows": rows}
    return out


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "fetch":
        fetch(sys.argv[2:])
    elif cmd == "replay":
        lat = float(sys.argv[sys.argv.index("--lat") + 1]) if "--lat" in sys.argv else 2.0
        res = replay(sys.argv[2], lat)
        for r in res["rows"]:
            print({k: r[k] for k in ("symbol", "entry_slip_pct", "candle_exit", "candle_ret_pct", "trade_exit",
                                      "trade_ret_pct", "hold_s", "n_swaps", "complete")}, r["crash"] or "")
        print(f"mean candle {res['mean_candle_ret_pct']}%  mean trade-level {res['mean_trade_ret_pct']}%  (lat {lat}s)")
        name = Path(sys.argv[2]).stem + f"_replay_lat{lat:g}.json"
        (I.OUT / name).write_text(json.dumps(res, indent=1))
