"""Lab 4 recorder: the live books of Polymarket US non-sports markets near their end, from the public gateway.

Why: the owner's venue is Polymarket US (gateway.polymarket.us, public market data, no key). Its stored price
history is coarse for anything older than a day, so a paper desk that must fill at THAT venue's printed prices
needs its own tape. This recorder polls, once a minute, the best bid / offer of every open non-sports market whose
``endDate`` is within :data:`HORIZON_H` hours, and records each market's settlement price once it closes.
Research only; nothing here trades.

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
HORIZON_H = 48.0  # record markets ending within two days
POLL_S = 60.0
REQ_SLEEP_S = 0.08  # the gateway's public limit is 20 req/s per IP; we stay far below
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
    now: float, horizon_h: float = HORIZON_H, max_pages: int = 60
) -> list[dict[str, Any]]:
    """Open, non-sports markets ending within ``horizon_h`` hours (the gateway has no category exclusion, so
    every open market is paged and filtered here)."""
    out: list[dict[str, Any]] = []
    for page in range(max_pages):
        reply = _get(
            "/markets", {"limit": PAGE, "offset": page * PAGE, "closed": "false"}
        )
        ms = reply.get("markets") if isinstance(reply, dict) else None
        if not ms:
            break
        for m in ms:
            if (m.get("category") or "").lower() in EXCLUDE_CATEGORIES:
                continue
            end_ts = parse_iso(m.get("endDate"))
            if end_ts is None or end_ts < now - 3600 or end_ts > now + horizon_h * 3600:
                continue
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
    return out


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


def _load(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except ValueError:
            return {}
    return {}


def poll(out: Path = OUT, now: float | None = None) -> dict[str, int]:
    """One round: refresh the watch list, record every watched market's BBO, settle the ones that closed."""
    now = time.time() if now is None else now
    out.mkdir(parents=True, exist_ok=True)
    (out / "bbo").mkdir(exist_ok=True)
    markets = _load(out / "markets.json")
    settled = _load(out / "settlements.json")
    fresh = open_markets(now)
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
    day = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")
    path = out / "bbo" / f"{day}.csv"
    new_file = not path.exists()
    n_rows = 0
    with path.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=BBO_FIELDS)
        if new_file:
            w.writeheader()
        for m in fresh:
            try:
                q = bbo(m["slug"])
            except RuntimeError:
                continue
            w.writerow(
                {
                    "ts": int(now),
                    "slug": m["slug"],
                    "category": m["category"],
                    "best_bid": q["best_bid"],
                    "best_ask": q["best_ask"],
                    "last": q["last"],
                    "end_ts": int(m["end_ts"]),
                    "fee_coef": m["fee_coef"],
                }
            )
            n_rows += 1
            time.sleep(REQ_SLEEP_S)
    # markets we watched that are no longer open: fetch their settlement once
    fresh_slugs = {m["slug"] for m in fresh}
    n_settled = 0
    for slug, rec in markets.items():
        if slug in fresh_slugs or slug in settled or rec["end_ts"] > now:
            continue
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
    (out / "markets.json").write_text(json.dumps(markets, indent=0, sort_keys=True))
    (out / "settlements.json").write_text(json.dumps(settled, indent=0, sort_keys=True))
    return {
        "watched": len(fresh),
        "rows": n_rows,
        "settled_now": n_settled,
        "settled_total": len(settled),
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
