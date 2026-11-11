"""Lab 4 recorder: the live books of Polymarket US non-sports markets near their end, from the public gateway.

Why: the owner's venue is Polymarket US (gateway.polymarket.us, public market data, no key). Its stored price
history is coarse for anything older than a day, so a paper desk that must fill at THAT venue's printed prices
needs its own tape. This recorder polls, once a minute, the best bid / offer of every open non-sports market whose
``endDate`` is within :data:`HORIZON_H` hours, and records each market's settlement price once it closes. Sports
(the owner can trade them): the moneyline markets of games in progress (events with a live period), capped at
:data:`SPORTS_CAP`. Research only; nothing here trades.

Layout (``$SCRATCH/lab4/us`` by default)::

    bbo/YYYY-MM-DD.csv       ts, slug, category, best_bid, best_ask, last, end_ts, fee_coef  (one row per poll)
    markets.json             slug -> {question, category, end_ts, fee_coef, tick, min_qty, first_seen, status}
    settlements.json         slug -> {settlement, closed_at, first_seen}

CLI::

    python research/lab4/recorder.py            # run forever (Ctrl-C to stop)
    python research/lab4/recorder.py --once     # one poll
    python research/lab4/recorder.py --status
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

GATEWAY = "https://gateway.polymarket.us/v1"
SCRATCH = Path(
    os.environ.get(
        "CLAUDE_SCRATCHPAD",
        "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad",
    )
)
OUT = Path(os.environ.get("LAB4_US_DATA", str(SCRATCH / "lab4" / "us")))
EXCLUDE_CATEGORIES = {"sports"}
#: The gateway lists thousands of open sports markets first, so the watch list is built per non-sports category.
CATEGORIES = (
    "climate",
    "weather",
    "crypto",
    "politics",
    "culture",
    "finance",
    "technology",
    "macro",
    "geopolitics",
    "science",
    "economics",
    "mentions",
    "tech",
)
HORIZON_H = 48.0  # record non-sports markets ending within two days
SPORTS_CAP = 150  # live games: their moneyline markets only, at most this many at a time (rate limit)
SPORTS_LOOKBACK_H = 12.0  # a game that started this long ago is treated as over
#: Match-winner markets (the venue's enums SPORTS_MARKET_TYPE_MONEYLINE, SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME).
WINNER_KINDS = ("MONEYLINE", "DRAWABLE_OUTCOME")
NOT_LIVE_PERIODS = {"NS", "", "CAN", "SUS", "PST", "FT", "AOT", "FINAL", "ENDED"}
POLL_S = 60.0
REQ_SLEEP_S = 0.05  # per request per thread
THREADS = 8  # BBO polls in parallel: ~600 markets in well under a minute, still under the 20 req/s public limit
PAGE = 100
UA = {"User-Agent": "nightcrawler-research/lab4-recorder"}
BBO_FIELDS = [
    "ts",
    "slug",
    "category",
    "best_bid",
    "best_ask",
    "last",
    "end_ts",
    "fee_coef",
]


def _get(path: str, params: dict[str, Any] | None = None, tries: int = 4) -> Any:
    last: Exception | None = None
    for attempt in range(tries):
        try:
            r = requests.get(f"{GATEWAY}{path}", params=params, headers=UA, timeout=30)
            if r.status_code == 429:
                time.sleep(3.0 * (attempt + 1))
                continue
            if r.status_code >= 500:
                time.sleep(1.5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = e
            time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"GET {path} failed: {last}")


def parse_iso(value: Any) -> float | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _num(v: Any) -> float | None:
    if isinstance(v, dict):
        v = v.get("value")
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def open_markets(
    now: float, horizon_h: float = HORIZON_H, max_pages: int = 20
) -> list[dict[str, Any]]:
    """Open, non-sports markets ending within ``horizon_h`` hours, paged per category (the default listing is
    thousands of sports markets deep before anything else appears)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cat in CATEGORIES:
        for page in range(max_pages):
            reply = _get(
                "/markets",
                {
                    "limit": PAGE,
                    "offset": page * PAGE,
                    "closed": "false",
                    "categories": cat,
                },
            )
            ms = reply.get("markets") if isinstance(reply, dict) else None
            if not ms:
                break
            for m in ms:
                if (m.get("category") or "").lower() in EXCLUDE_CATEGORIES or m[
                    "slug"
                ] in seen:
                    continue
                end_ts = parse_iso(m.get("endDate"))
                if (
                    end_ts is None
                    or end_ts < now - 3600
                    or end_ts > now + horizon_h * 3600
                ):
                    continue
                seen.add(m["slug"])
                out.append(
                    {
                        "slug": m["slug"],
                        "question": m.get("question"),
                        "category": (m.get("category") or "").lower(),
                        "end_ts": end_ts,
                        "fee_coef": _num(m.get("feeCoefficient")),
                        "tick": _num(m.get("orderPriceMinTickSize")),
                        "min_qty": _num(m.get("minimumTradeQty")),
                        "status": m.get("status"),
                    }
                )
            if len(ms) < PAGE:
                break
            time.sleep(REQ_SLEEP_S)
        time.sleep(REQ_SLEEP_S)
    out.sort(key=lambda m: m["end_ts"])
    return out


def live_sports_markets(now: float, cap: int = SPORTS_CAP) -> list[dict[str, Any]]:
    """The moneyline markets of sports games in progress: events that started within SPORTS_LOOKBACK_H and
    report a live period (not scheduled, cancelled, suspended or finished), newest start first, capped."""
    start_min = datetime.fromtimestamp(now - SPORTS_LOOKBACK_H * 3600, UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    start_max = datetime.fromtimestamp(now + 300, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: list[dict[str, Any]] = []
    for page in range(5):
        reply = _get(
            "/events",
            {
                "limit": PAGE,
                "offset": page * PAGE,
                "closed": "false",
                "categories": "sports",
                "startDateMin": start_min,
                "startDateMax": start_max,
            },
        )
        evs = reply.get("events") if isinstance(reply, dict) else None
        if not evs:
            break
        for ev in evs:
            started = parse_iso(ev.get("startTime") or ev.get("startDate"))
            period = str(ev.get("period") or "").upper()
            if started is None or started > now or period in NOT_LIVE_PERIODS:
                continue
            for m in ev.get("markets") or []:
                kind = str(
                    m.get("sportsMarketTypeV2") or m.get("marketType") or ""
                ).upper()
                if not any(w in kind for w in WINNER_KINDS) or m.get("closed"):
                    continue
                out.append(
                    {
                        "slug": m["slug"],
                        "question": m.get("question"),
                        "category": "sports",
                        "end_ts": parse_iso(m.get("endDate")) or started + 6 * 3600,
                        "fee_coef": _num(m.get("feeCoefficient")),
                        "tick": _num(m.get("orderPriceMinTickSize")),
                        "min_qty": _num(m.get("minimumTradeQty")),
                        "status": m.get("status"),
                        "game_start": started,
                        "period": period,
                        "event": ev.get("slug"),
                    }
                )
        if len(evs) < PAGE:
            break
        time.sleep(REQ_SLEEP_S)
    out.sort(key=lambda m: -m["game_start"])
    return out[:cap]


def bbo(slug: str) -> dict[str, float | None]:
    reply = _get(f"/markets/{slug}/bbo")
    md = reply.get("marketData", reply) if isinstance(reply, dict) else {}
    return {
        "best_bid": _num(md.get("bestBid")),
        "best_ask": _num(md.get("bestAsk")),
        "last": _num(md.get("lastTradePx")),
    }


def settlement(slug: str) -> float | None:
    reply = _get(f"/markets/{slug}/settlement")
    return _num(reply.get("settlement")) if isinstance(reply, dict) else None


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _load(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except ValueError:
            return {}
    return {}


def poll(out: Path = OUT, now: float | None = None) -> dict[str, int]:
    """One round: refresh the watch list, record every watched market's BBO, settle the ones that closed."""
    t_start = time.time()
    now = time.time() if now is None else now
    out.mkdir(parents=True, exist_ok=True)
    (out / "bbo").mkdir(exist_ok=True)
    markets = _load(out / "markets.json")
    settled = _load(out / "settlements.json")
    fresh = open_markets(now)
    try:
        fresh += live_sports_markets(now)
    except RuntimeError:
        pass  # a sports listing hiccup must not stop the non-sports poll
    for m in fresh:
        rec = markets.setdefault(m["slug"], {**m, "first_seen": now})
        rec.update(
            {
                k: m[k]
                for k in (
                    "end_ts",
                    "fee_coef",
                    "tick",
                    "min_qty",
                    "status",
                    "category",
                    "question",
                )
            }
        )
        for k in ("period", "game_start", "event"):
            if k in m:
                rec[k] = m[k]
    day = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")
    path = out / "bbo" / f"{day}.csv"
    new_file = not path.exists()

    def _quote(m: dict[str, Any]) -> dict[str, Any] | None:
        try:
            q = bbo(m["slug"])
        except RuntimeError:
            return None
        time.sleep(REQ_SLEEP_S)
        return {
            "ts": int(now),
            "slug": m["slug"],
            "category": m["category"],
            "best_bid": q["best_bid"],
            "best_ask": q["best_ask"],
            "last": q["last"],
            "end_ts": int(m["end_ts"]),
            "fee_coef": m["fee_coef"],
        }

    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        quotes = [q for q in pool.map(_quote, fresh) if q is not None]
    n_rows = 0
    with path.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=BBO_FIELDS)
        if new_file:
            w.writeheader()
        for q in quotes:
            w.writerow(q)
            n_rows += 1
    # markets we watched that are no longer open: fetch their settlement once
    fresh_slugs = {m["slug"] for m in fresh}
    n_settled = 0
    for slug, rec in markets.items():
        if slug in fresh_slugs or slug in settled:
            continue
        if rec["end_ts"] > now and rec.get("category") != "sports":
            continue  # non-sports settle after their end; a game leaves the live list first
        try:
            s = settlement(slug)
        except RuntimeError:
            continue
        if s is not None:
            settled[slug] = {
                "settlement": s,
                "closed_at": now,
                "first_seen": rec.get("first_seen"),
                "category": rec.get("category"),
            }
            n_settled += 1
        time.sleep(REQ_SLEEP_S)
    _write_atomic(out / "markets.json", json.dumps(markets, indent=0, sort_keys=True))
    _write_atomic(
        out / "settlements.json", json.dumps(settled, indent=0, sort_keys=True)
    )
    return {
        "watched": len(fresh),
        "rows": n_rows,
        "settled_now": n_settled,
        "settled_total": len(settled),
        "secs": round(time.time() - t_start, 1),
    }


def status(out: Path = OUT) -> None:
    markets = _load(out / "markets.json")
    settled = _load(out / "settlements.json")
    days = (
        sorted(p.name for p in (out / "bbo").glob("*.csv"))
        if (out / "bbo").exists()
        else []
    )
    rows = (
        sum(max(0, sum(1 for _ in p.open()) - 1) for p in (out / "bbo").glob("*.csv"))
        if days
        else 0
    )
    cats: dict[str, int] = {}
    for m in markets.values():
        cats[m.get("category", "?")] = cats.get(m.get("category", "?"), 0) + 1
    print(
        f"lab4 US recorder: {len(markets)} markets seen {cats}, {len(settled)} settled, {rows} BBO rows over {len(days)} day files"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Polymarket US non-sports book recorder (public gateway)"
    )
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--poll-s", type=float, default=POLL_S)
    a = ap.parse_args(argv)
    if a.status:
        status()
        return 0
    while True:
        t0 = time.time()
        try:
            r = poll()
            print(f"{datetime.now(UTC).isoformat(timespec='seconds')} {r}", flush=True)
        except Exception as e:  # noqa: BLE001 (a recorder keeps going)
            print(
                f"{datetime.now(UTC).isoformat(timespec='seconds')} poll failed: {e}",
                flush=True,
            )
        if a.once:
            return 0
        time.sleep(max(1.0, a.poll_s - (time.time() - t0)))


if __name__ == "__main__":
    sys.exit(main())
