"""Build the strategy-lab dataset: census of pump.fun graduates + candles per coin.

Usage (resumable; every step skips work already on disk unless --force)::

    python research/lab/fetch.py all          # census -> pools -> sol -> candles -> build
    python research/lab/fetch.py census       # LAB/census.json  (every raw field + fetch time)
    python research/lab/fetch.py pools        # LAB/pools.json   (GeckoTerminal pool_created_at + reserves)
    python research/lab/fetch.py sol          # LAB/sol_usd.json (SOL/USD 1m, Orca SOL/USDC pool)
    python research/lab/fetch.py candles      # LAB/raw/<mint>_1m.json (+ _5m.json when 1m is truncated)
    python research/lab/fetch.py gt1m         # LAB/raw/<mint>_gt1m.json: true 1m bars (GeckoTerminal curve +
                                              #   pool) for the part a truncated 1m response misses
    python research/lab/fetch.py build        # LAB/coins/<mint>.json (nightcrawler backtest format)

``LAB`` = env ``LAB_DATA`` or the session scratchpad ``.../scratchpad/lab``.

Universe (see DATASET.md): every coin returned by
``frontend-api-v3.pump.fun/coins?sort=created_timestamp&order=DESC&complete=true&includeNsfw=true``.
The API stops at offset 1000 (limit <= 70), i.e. the newest ~1,070 graduates (~22-23 h).
No other sort/filter reaches older graduates without survivor bias (ASC returns the 2024
coins; market_cap / ath sorts are survivor-ranked; time filters are ignored).

Candles: ``swap-api.pump.fun/v1/coins/{mint}/candles?interval=1m&limit=1000`` returns the
LATEST <= 1000 minutes that had trades (bonding-curve AND PumpSwap trades, USD price per
whole token, USD volume - verified against GeckoTerminal). If those 1000 minutes do not
reach back to creation, the 5m response (which covers the whole life of any coin < 83 h old)
supplies the earlier part at 5-minute resolution (``coverage.source = "5m+1m"``).

Coin file::

    {"coin": symbol, "name", "mint", "pool": pump_swap_pool, "supply": whole tokens,
     "created_ts": s, "graduated_ts": s (pool creation), "graduated_src": "geckoterminal"|"candles"|"created",
     "launch": {creation-time flags only}, "cost": {k estimate, ONLY for costs.py},
     "candles": [[ts, o, h, l, c, vol_usd], ...]   # ascending, gap-filled, flat to fetch time
     "coverage": {"first_ts", "last_trade_ts", "end_ts", "first_1m_ts", "bar_s_before_1m": 300,
                  "complete_from_creation", "source", "n_candles", "n_synthetic", "fetched_ts"}}

Candles with ``ts < coverage.first_1m_ts`` are 5-minute bars; the rest are 1-minute bars.
Missing bars inside the covered range (no trades) are flat zero-volume bars at the previous
close; after the last trade the series is extended flat until the fetch minute (an AMM price
does not move without trades). ``n_synthetic`` counts them.

Outcome-only census fields (ath_*, last_trade_timestamp, market caps, reserves, complete,
is_banned, reply_count, mayhem_state ...) stay in census.json and are NEVER copied into a coin
file's ``launch``/``candles``. Current pool reserves are used only to sanity-check the
constant-product k that costs.py uses (see costs.py).
"""

from __future__ import annotations

import argparse
import calendar
import concurrent.futures as cf
import json
import math
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

import requests

LAB = Path(os.environ.get(
    "LAB_DATA", "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/lab"))
RAW = LAB / "raw"
COINS = LAB / "coins"

CENSUS_URL = "https://frontend-api-v3.pump.fun/coins"
CANDLES_URL = "https://swap-api.pump.fun/v1/coins/{mint}/candles"
GT = "https://api.geckoterminal.com/api/v2/networks/solana"
SOL_USDC_POOL = "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE"  # Orca SOL/USDC, deepest SOL pool
SOL_MINT_NATIVE = "11111111111111111111111111111111"  # pump.fun quote_mint for SOL-paired coins
CENSUS_PAGE = 70  # API maximum limit
CENSUS_MAX_OFFSET = 1000  # offset 1001+ returns []
UA = {"User-Agent": "nightcrawler-research/0.1", "Accept": "application/json"}

#: creation-time fields copied into coin files (pump.fun metadata is immutable IPFS at launch).
LAUNCH_FIELDS = ("name", "symbol", "creator", "program", "protocol", "token_program", "quote_mint",
                 "base_decimals", "quote_decimals", "nsfw", "is_cashback_enabled", "transfer_fee_bps")


# --------------------------------------------------------------------------- http


class Throttle:
    """Simple shared min-interval limiter (thread safe)."""

    def __init__(self, per_minute: float) -> None:
        self.interval = 60.0 / per_minute
        self.lock = threading.Lock()
        self.next_at = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            delay = self.next_at - now
            self.next_at = max(now, self.next_at) + self.interval
        if delay > 0:
            time.sleep(delay)


PUMP_FRONT = Throttle(50)  # limit 60/min
PUMP_SWAP = Throttle(400)  # limit 1000/min
GECKO = Throttle(12)  # nominal ~30/min, 429s are frequent


def get_json(url: str, params: dict | None, throttle: Throttle, tries: int = 8) -> Any:
    """GET with throttle + exponential backoff on 429/5xx/network errors (honours Retry-After)."""
    backoff = 5.0
    for attempt in range(tries):
        throttle.wait()
        try:
            r = requests.get(url, params=params, headers=UA, timeout=40)
        except requests.RequestException as exc:
            print(f"  net error {exc!r}; retry in {backoff:.0f}s", file=sys.stderr)
            time.sleep(backoff)
            backoff = min(backoff * 2, 120)
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504, 520, 522, 524):
            ra = r.headers.get("Retry-After")
            wait = max(backoff, float(ra)) if ra and ra.replace(".", "", 1).isdigit() else backoff
            print(f"  {r.status_code} on {url.split('?')[0][-60:]}; retry in {wait:.0f}s", file=sys.stderr)
            time.sleep(wait)
            backoff = min(backoff * 2, 120)
            continue
        raise RuntimeError(f"GET {url} {params} -> {r.status_code}: {r.text[:200]}")
    raise RuntimeError(f"GET {url} {params}: gave up after {tries} tries")


def dump(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- census


def census(force: bool = False) -> dict:
    path = LAB / "census.json"
    if path.exists() and not force:
        print(f"census: exists ({path})")
        return load(path)
    started = time.time()
    coins: dict[str, dict] = {}
    pages = []
    for offset in [*range(0, CENSUS_MAX_OFFSET, CENSUS_PAGE), CENSUS_MAX_OFFSET]:
        rows = get_json(CENSUS_URL, {"offset": offset, "limit": CENSUS_PAGE, "sort": "created_timestamp",
                                     "order": "DESC", "includeNsfw": "true", "complete": "true"}, PUMP_FRONT)
        fetched = time.time()
        pages.append({"offset": offset, "n": len(rows), "fetched_ts": fetched})
        for row in rows:
            row["_fetched_ts"] = fetched
            coins.setdefault(row["mint"], row)  # DESC paging: new graduates shift rows down -> dupes, no gaps
        print(f"census offset {offset}: {len(rows)} rows, {len(coins)} unique")
        if not rows:
            break
    finished = time.time()
    created = [c["created_timestamp"] / 1000 for c in coins.values()]
    doc = {
        "census_started_ts": started, "census_finished_ts": finished,
        "census_started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "query": {"url": CENSUS_URL, "sort": "created_timestamp", "order": "DESC", "complete": "true",
                  "includeNsfw": "true", "limit": CENSUS_PAGE, "max_offset": CENSUS_MAX_OFFSET},
        "pages": pages, "n": len(coins),
        "created_min_ts": min(created), "created_max_ts": max(created),
        "coins": sorted(coins.values(), key=lambda c: c["created_timestamp"]),
    }
    dump(path, doc)
    print(f"census: {len(coins)} coins created {time.strftime('%m-%d %H:%M', time.gmtime(min(created)))}"
          f" .. {time.strftime('%m-%d %H:%M', time.gmtime(max(created)))} UTC")
    return doc


# --------------------------------------------------------------------------- pools (GeckoTerminal)


def pools(force: bool = False) -> dict:
    """pool_created_at (graduation time) + current reserves for every pump_swap_pool (30 per call)."""
    path = LAB / "pools.json"
    have: dict[str, Any] = load(path)["pools"] if path.exists() and not force else {}
    cen = load(LAB / "census.json")
    todo = [c["pump_swap_pool"] for c in cen["coins"] if c.get("pump_swap_pool") and c["pump_swap_pool"] not in have]
    for i in range(0, len(todo), 30):
        chunk = todo[i:i + 30]
        doc = get_json(f"{GT}/pools/multi/{','.join(chunk)}", None, GECKO)
        now = time.time()
        for p in doc.get("data", []):
            a = p["attributes"]
            have[a["address"]] = {
                "pool_created_at": a.get("pool_created_at"),
                "reserve_in_usd": a.get("reserve_in_usd"),
                "base_token_price_usd": a.get("base_token_price_usd"),
                "base_token_price_quote_token": a.get("base_token_price_quote_token"),
                "quote_token_price_usd": a.get("quote_token_price_usd"),
                "dex": p.get("relationships", {}).get("dex", {}).get("data", {}).get("id"),
                "fetched_ts": now,
            }
        for addr in chunk:
            have.setdefault(addr, {"missing": True, "fetched_ts": now})
        dump(path, {"pools": have})
        print(f"pools: {min(i + 30, len(todo))}/{len(todo)}")
    if not todo:
        print("pools: nothing to do")
    return {"pools": have}


# --------------------------------------------------------------------------- SOL/USD


def sol(force: bool = False) -> list:
    path = LAB / "sol_usd.json"
    if path.exists() and not force:
        print("sol: exists")
        return load(path)["candles"]
    cen = load(LAB / "census.json")
    start = int(cen["created_min_ts"]) - 3 * 3600
    rows: dict[int, list] = {}
    before = int(time.time()) + 60
    while before > start:
        doc = get_json(f"{GT}/pools/{SOL_USDC_POOL}/ohlcv/minute",
                       {"aggregate": 1, "limit": 1000, "currency": "usd", "token": "base",
                        "before_timestamp": before}, GECKO)
        lst = doc["data"]["attributes"]["ohlcv_list"]
        if not lst:
            break
        for r in lst:
            rows[int(r[0])] = [int(r[0]), *map(float, r[1:6])]
        before = min(rows)
        print(f"sol: {len(rows)} minutes back to {time.strftime('%m-%d %H:%M', time.gmtime(before))}")
    out = [rows[t] for t in sorted(rows)]
    dump(path, {"pool": SOL_USDC_POOL, "source": "GeckoTerminal ohlcv minute currency=usd", "candles": out,
                "fetched_ts": time.time()})
    return out


# --------------------------------------------------------------------------- candles


def _fetch_raw(mint: str, interval: str) -> dict:
    rows = get_json(CANDLES_URL.format(mint=mint), {"interval": interval, "limit": 1000}, PUMP_SWAP)
    return {"mint": mint, "interval": interval, "fetched_ts": time.time(), "rows": rows}


def needs_5m(raw1: dict, created_ts: float) -> bool:
    rows = raw1["rows"]
    if not rows:
        return False
    first = int(rows[0]["timestamp"]) // 1000
    return len(rows) >= 1000 and first > created_ts + 60


def _candles_one(coin: dict, force: bool) -> str:
    mint = coin["mint"]
    p1, p5 = RAW / f"{mint}_1m.json", RAW / f"{mint}_5m.json"
    if force or not p1.exists():
        dump(p1, _fetch_raw(mint, "1m"))
    raw1 = load(p1)
    if needs_5m(raw1, coin["created_timestamp"] / 1000) and (force or not p5.exists()):
        dump(p5, _fetch_raw(mint, "5m"))
        return "1m+5m"
    return "1m"


def candles(force: bool = False, workers: int = 4) -> None:
    cen = load(LAB / "census.json")
    todo = cen["coins"]
    done = 0
    with cf.ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(_candles_one, c, force): c["mint"] for c in todo}
        for fut in cf.as_completed(futs):
            done += 1
            try:
                fut.result()
            except Exception as exc:  # keep going; a rerun retries the missing ones
                print(f"  candles {futs[fut]} failed: {exc}", file=sys.stderr)
            if done % 100 == 0:
                print(f"candles: {done}/{len(todo)}")
    print(f"candles: {done}/{len(todo)} done")


# --------------------------------------------------------------------------- GeckoTerminal 1m splice


def _gt_minutes(address: str, before: int, since: int) -> list[list]:
    """GeckoTerminal 1m OHLCV of ``address`` in [since, before), oldest first; duplicate-ts rows merged."""
    got: dict[int, list] = {}
    cursor = before
    for _ in range(5):
        doc = get_json(f"{GT}/pools/{address}/ohlcv/minute",
                       {"aggregate": 1, "limit": 1000, "currency": "usd", "token": "base",
                        "before_timestamp": cursor}, GECKO)
        lst = doc.get("data", {}).get("attributes", {}).get("ohlcv_list") or []
        if not lst:
            break
        for r in lst:  # rows sharing a ts are listed in chronological order
            t = int(r[0])
            if t >= before or t < since - 60:
                continue
            o, h, low, c, v = map(float, r[1:6])
            if t in got:
                g = got[t]
                got[t] = [t, g[1], max(g[2], h), min(g[3], low), c, g[5] + v]
            else:
                got[t] = [t, o, h, low, c, v]
        oldest = min(int(r[0]) for r in lst)
        if oldest <= since or len(lst) < 1000:
            break
        cursor = oldest
    return [got[t] for t in sorted(got)]


def gt1m(force: bool = False) -> None:
    """For coins whose swap-api 1m history does not reach creation, fetch true 1m bars from
    GeckoTerminal: the bonding-curve 'pool' (creation -> graduation) and the PumpSwap pool
    (graduation -> first swap-api 1m bar). Saved as raw/<mint>_gt1m.json."""
    cen = load(LAB / "census.json")
    pinfo = load(LAB / "pools.json")["pools"]
    for coin in cen["coins"]:
        mint = coin["mint"]
        p1, out = RAW / f"{mint}_1m.json", RAW / f"{mint}_gt1m.json"
        if not p1.exists() or (out.exists() and not force):
            continue
        raw1 = load(p1)
        created = coin["created_timestamp"] / 1000
        if not needs_5m(raw1, created):
            continue
        first_1m = int(raw1["rows"][0]["timestamp"]) // 1000
        pool = coin["pump_swap_pool"]
        grad = pinfo.get(pool, {}).get("pool_created_at")
        grad_ts = calendar.timegm(time.strptime(grad, "%Y-%m-%dT%H:%M:%SZ")) if grad else created
        pool_rows = _gt_minutes(pool, first_1m, int(grad_ts) // 60 * 60)
        curve_rows = []
        if grad_ts - created > 30:
            curve_rows = _gt_minutes(coin["bonding_curve"], int(grad_ts) // 60 * 60 + 60, int(created) // 60 * 60)
        dump(out, {"mint": mint, "pool_rows": pool_rows, "curve_rows": curve_rows, "first_1m_ts": first_1m,
                   "graduated_ts": grad_ts, "fetched_ts": time.time()})
        print(f"gt1m {coin['symbol']}: pool {len(pool_rows)} bars, curve {len(curve_rows)} bars")


def _gt_splice(gt: dict, rows5: list[list], first_1m: int) -> tuple[list[list], float] | None:
    """GeckoTerminal 1m rows before ``first_1m`` rescaled to swap-api's USD basis.

    Scale = median(swap 5m close / GT close at the same 5m bar end) over the GT span (SOL/USD
    conversions differ by ~0.1-1 %). Curve and pool rows in the same minute are merged.
    """
    merged: dict[int, list] = {}
    for r in sorted(gt["curve_rows"] + gt["pool_rows"], key=lambda r: r[0]):
        t = r[0]
        if t >= first_1m:
            continue
        if t in merged:
            g = merged[t]
            merged[t] = [t, g[1], max(g[2], r[2]), min(g[3], r[3]), r[4], g[5] + r[5]]
        else:
            merged[t] = list(r)
    if not merged:
        return None
    rows = [merged[t] for t in sorted(merged)]
    by5 = {r[0]: r for r in rows5}
    last_close_in: dict[int, float] = {}
    for r in rows:
        last_close_in[r[0] // 300 * 300] = r[4]
    ratios = sorted(by5[b][4] / c for b, c in last_close_in.items() if b in by5 and c > 0)
    scale = ratios[len(ratios) // 2] if ratios else 1.0
    if not 0.8 < scale < 1.25:
        scale = 1.0
    return [[r[0], r[1] * scale, r[2] * scale, r[3] * scale, r[4] * scale, r[5]] for r in rows], scale


# --------------------------------------------------------------------------- build


def _row(x: dict) -> list | None:
    """API row -> [ts, o, h, l, c, v]; None for rows with missing/non-positive prices."""
    try:
        r = [int(x["timestamp"]) // 1000, float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]),
             float(x["volume"] or 0.0)]
    except (TypeError, ValueError, KeyError):
        return None
    return r if min(r[1:5]) > 0 and all(math.isfinite(v) for v in r[1:]) else None


def _rows(raw_rows: list) -> list[list]:
    """Parsed, de-duplicated (last wins), ascending rows."""
    return sorted({r[0]: r for r in map(_row, raw_rows) if r is not None}.values())


def _fill(rows: list[list], step: int, start: int, end_excl: int, prev_close: float | None) -> tuple[list, int]:
    """Grid [start, end_excl) with ``step``; missing slots -> flat zero-volume bars at prev close."""
    by_ts = {r[0]: r for r in rows}
    out, synth = [], 0
    t = start
    while t < end_excl:
        r = by_ts.get(t)
        if r is not None:
            out.append(r)
            prev_close = r[4]
        elif prev_close is not None:
            out.append([t, prev_close, prev_close, prev_close, prev_close, 0.0])
            synth += 1
        t += step
    return out, synth


def _round(r: list) -> list:
    return [r[0], *(float(f"{x:.9g}") for x in r[1:5]), round(r[5], 4)]


def build_coin(coin: dict, pool_info: dict | None, census_doc: dict, sol_usd: "SolPrice | None" = None) -> dict | None:
    mint = coin["mint"]
    p1, p5 = RAW / f"{mint}_1m.json", RAW / f"{mint}_5m.json"
    if not p1.exists():
        return None
    raw1 = load(p1)
    rows1 = _rows(raw1["rows"])
    if not rows1:
        return None
    created_ts = coin["created_timestamp"] / 1000
    fetched = raw1["fetched_ts"]
    rows1 = [r for r in rows1 if r[0] + 60 <= fetched]  # drop the minute still open at fetch time
    if not rows1:
        return None
    end_excl = int(fetched // 60) * 60  # bars up to the last minute fully closed at fetch time
    source, synth = "1m", 0
    complete = not needs_5m(raw1, created_ts)
    pre: list[list] = []
    first_1m = rows1[0][0]
    pg = RAW / f"{mint}_gt1m.json"
    splice_scale = None
    if not complete and pg.exists() and p5.exists():
        rows5 = _rows(load(p5)["rows"])
        spliced = _gt_splice(load(pg), rows5, first_1m)
        if spliced is not None:
            gt_rows, splice_scale = spliced
            rows1 = gt_rows + rows1
            source = "gt1m+1m"
            complete = gt_rows[0][0] <= created_ts + 120
            first_1m = rows1[0][0]
    if source == "1m" and not complete:
        if not p5.exists():
            return None
        rows5 = _rows(load(p5)["rows"])
        boundary = int(math.ceil(first_1m / 300) * 300)
        rows5 = [r for r in rows5 if r[0] + 300 <= boundary]
        if rows5:
            pre, s5 = _fill(rows5, 300, rows5[0][0], boundary, None)
            synth += s5
            source = "5m+1m"
            complete = rows5[0][0] <= created_ts + 300
        rows1 = [r for r in rows1 if r[0] >= boundary]
        first_1m = boundary
    prev = pre[-1][4] if pre else None
    main, s1 = _fill(rows1, 60, first_1m if pre else rows1[0][0], end_excl, prev)
    synth += s1
    bars = [_round(r) for r in pre + main]
    supply = int(coin["total_supply"]) / 10 ** int(coin.get("base_decimals") or 6)
    grad_ts, grad_src = _graduation(coin, pool_info, bars, first_1m, sol_usd)
    launch = {k: coin.get(k) for k in LAUNCH_FIELDS}
    launch.update({
        "quote_is_sol": coin.get("quote_mint") == SOL_MINT_NATIVE,
        "mayhem": coin.get("mayhem_state") is not None,  # opt-in at launch; its CURRENT state is outcome-only
        "has_twitter": bool(coin.get("twitter")), "has_website": bool(coin.get("website")),
        "has_telegram": bool(coin.get("telegram")),
        "description_len": len(coin.get("description") or ""),
    })
    return {
        "coin": coin.get("symbol") or mint[:6], "name": coin.get("name"), "mint": mint,
        "pool": coin.get("pump_swap_pool"), "supply": supply, "created_ts": created_ts,
        "graduated_ts": grad_ts, "graduated_src": grad_src,
        "launch": launch,
        "cost": _cost_meta(coin, pool_info),
        "coverage": {
            "first_ts": bars[0][0], "last_trade_ts": max(r[0] for r in pre + main if r[5] > 0) if any(
                r[5] > 0 for r in pre + main) else bars[0][0],
            "end_ts": bars[-1][0], "first_1m_ts": first_1m, "bar_s_before_1m": 300,
            "complete_from_creation": bool(complete), "source": source, "n_candles": len(bars),
            "n_synthetic": synth, "fetched_ts": fetched, "gt_splice_scale": splice_scale, "census_finished_ts": census_doc["census_finished_ts"],
        },
        "candles": bars,
    }


#: pump.fun bonding curve at completion: 115.005 virtual SOL / 279.9M virtual tokens (SOL-quoted coins).
CURVE_END_PRICE_SOL = 115.005359057 / 279_900_000


class SolPrice:
    """SOL/USD close per minute (as-of lookup: last minute at or before ts)."""

    def __init__(self, rows: list) -> None:
        self.ts = [int(r[0]) for r in rows]
        self.px = [float(r[4]) for r in rows]

    def at(self, ts: float) -> float:
        import bisect
        i = bisect.bisect_right(self.ts, ts) - 1
        return self.px[max(i, 0)]


def _graduation(coin: dict, pool_info: dict | None, bars: list, first_1m: int,
                sol_usd: "SolPrice | None") -> tuple[float, str]:
    """Pool creation time from GeckoTerminal; else the END of the first bar whose high reached 97 %
    of the curve's completion price (conservative); else created_ts."""
    if pool_info and pool_info.get("pool_created_at"):
        ts = calendar.timegm(time.strptime(pool_info["pool_created_at"], "%Y-%m-%dT%H:%M:%SZ"))
        return float(ts), "geckoterminal"
    if sol_usd is not None and coin.get("quote_mint") == SOL_MINT_NATIVE:
        for r in bars:
            if r[2] >= 0.97 * CURVE_END_PRICE_SOL * sol_usd.at(r[0]):
                return float(r[0] + (300 if r[0] < first_1m else 60)), "candles"
    return float(coin["created_timestamp"] / 1000), "created"


def _cost_meta(coin: dict, pool_info: dict | None) -> dict:
    """Inputs for costs.py ONLY (never a strategy input). See costs.k_for_coin."""
    out = {"quote_mint": coin.get("quote_mint"), "quote_is_sol": coin.get("quote_mint") == SOL_MINT_NATIVE}
    if pool_info and not pool_info.get("missing"):
        try:
            res_usd = float(pool_info["reserve_in_usd"])
            p_quote = float(pool_info["base_token_price_quote_token"])  # quote per token
            q_usd = float(pool_info["quote_token_price_usd"])
            quote_res = res_usd / 2 / q_usd  # constant-product pools hold equal value on both sides
            base_res = quote_res / p_quote
            out.update({"k_now_quote_token": quote_res * base_res, "quote_reserve_now": quote_res,
                        "quote_price_usd_now": q_usd, "reserves_fetched_ts": pool_info["fetched_ts"]})
        except (TypeError, ValueError, ZeroDivisionError, KeyError):
            pass
    return out


def build(force: bool = False) -> None:
    cen = load(LAB / "census.json")
    pinfo = load(LAB / "pools.json")["pools"] if (LAB / "pools.json").exists() else {}
    sol_usd = SolPrice(load(LAB / "sol_usd.json")["candles"]) if (LAB / "sol_usd.json").exists() else None
    COINS.mkdir(parents=True, exist_ok=True)
    n = skipped = 0
    for coin in cen["coins"]:
        out = COINS / f"{coin['mint']}.json"
        if out.exists() and not force:
            n += 1
            continue
        doc = build_coin(coin, pinfo.get(coin.get("pump_swap_pool") or ""), cen, sol_usd)
        if doc is None:
            skipped += 1
            continue
        dump(out, doc)
        n += 1
    print(f"build: {n} coin files, {skipped} skipped (no candles)")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=["all", "census", "pools", "sol", "candles", "gt1m", "build"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    LAB.mkdir(parents=True, exist_ok=True)
    steps = ["census", "pools", "sol", "candles", "gt1m", "build"] if a.step == "all" else [a.step]
    for step in steps:
        if step == "candles":
            candles(a.force, a.workers)
        else:
            globals()[step](a.force)


if __name__ == "__main__":
    main()
