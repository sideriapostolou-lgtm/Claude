"""Synthetic but recorder-shaped tapes for the learning tests (import as ``from learn_world import ...``).

``record_coin`` turns a 1m candle series into exactly the rows the recorder writes: a ``universe`` row
from a census row and one ``candles`` row per scheduled fetch (pump.fun returns only the minutes WITH
trades, newest ``limit`` of them, the newest possibly still open), chained through ``candle_mark``.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from nightcrawler.costs import SOL_QUOTE
from nightcrawler.learn.store import LearnStore
from nightcrawler.learn.tape import TapeWriter, candle_fetch_row, candle_mark, tape_day, universe_row
from nightcrawler.learn.variants import VariantSpec
from nightcrawler.models import Candle

#: Thursday 2026-10-08 00:00:00 UTC
DAY0 = 1_791_417_600
SOL_USD = 106.0


def census_row(mint: str, created_ts: float, *, symbol: str = "TST", quote_mint: str = SOL_QUOTE,
               mayhem: bool = False) -> dict[str, Any]:
    row = {"mint": mint, "name": symbol.title(), "symbol": symbol, "creator": "Creator" + mint[:8],
           "created_timestamp": int(created_ts * 1000), "complete": True, "quote_mint": quote_mint,
           "base_decimals": 6, "quote_decimals": 9, "total_supply": 1_000_000_000_000_000, "program": "pump",
           "pump_swap_pool": "Pool" + mint[:8], "market_cap": 3000.0, "usd_market_cap": 3000.0 * SOL_USD,
           "last_trade_timestamp": int(created_ts * 1000) + 60_000}
    if mayhem:
        row["mayhem_state"] = "completed"
    return row


def api_rows(candles: list[Candle]) -> list[dict[str, Any]]:
    """Candles WITH trades as pump.fun serves them (ms timestamps, decimal strings)."""
    return [{"timestamp": c.ts * 1000, "open": repr(c.o), "high": repr(c.h), "low": repr(c.l), "close": repr(c.c),
             "volume": repr(c.v)} for c in candles if c.v > 0]


def record_coin(mint: str, created_ts: float, candles: list[Candle], *, first_seen_ts: float | None = None,
                fetch_after_h: tuple[float, ...] = (3, 12, 50), limit: int = 1000,
                **census: Any) -> dict[str, list[dict[str, Any]]]:
    """The tape rows the recorder would write for this coin."""
    seen = created_ts + 600 if first_seen_ts is None else first_seen_ts
    universe = universe_row(census_row(mint, created_ts, **census), fetched_ts=seen, offset=0, late=False)
    fetches, mark = [], None
    for k, hours in enumerate(fetch_after_h, 1):
        fetched = seen + hours * 3600
        served = api_rows([c for c in candles if c.ts <= fetched])[-limit:]  # newest minute may be open
        row = candle_fetch_row(mint, served, fetched_ts=fetched, previous=mark, limit=limit, fetch_no=k)
        mark = candle_mark(row, mark)
        fetches.append(row)
    return {"universe": [universe], "candles": fetches, "snaps": []}


def dip_rebound_series(created_ts: float, rng: random.Random, minutes: int = 480) -> list[Candle]:
    """Pump, dump of ~60-75 %, a base with green attempts, then a random walk; ~8 % no-trade minutes."""
    ts0 = int(created_ts) // 60 * 60
    price = rng.uniform(2.6e-4, 3.6e-4)
    pump_end, dump_end = rng.randint(30, 50), rng.randint(110, 150)
    out = []
    for i in range(minutes):
        if i < pump_end:
            drift = 0.025
        elif i < dump_end:
            drift = -0.013
        elif i < dump_end + 60:
            drift = 0.004 if rng.random() < 0.5 else -0.003
        else:
            drift = rng.choice((0.01, -0.01, 0.0))
        ts = ts0 + 60 * i
        if rng.random() < 0.08:  # nobody traded this minute
            out.append(Candle(ts, price, price, price, price, 0.0))
            continue
        o = price
        c = max(1.2e-4, o * (1 + drift + rng.gauss(0, 0.012)))
        h = max(o, c) * (1 + rng.uniform(0, 0.01))
        low = min(o, c) * (1 - rng.uniform(0, 0.01))
        out.append(Candle(ts, o, h, low, c, rng.uniform(200.0, 6000.0)))
        price = c
    return out


def make_coins(n: int, seed: int, start: float, spacing_s: float = 1800.0, **kw: Any) -> dict[str, dict]:
    """``{mint: {"created_ts", "candles", "rows"}}`` for ``n`` coins created ``spacing_s`` apart from ``start``."""
    rng = random.Random(seed)
    coins = {}
    for i in range(n):
        mint = f"Mint{seed:03d}{i:03d}" + "x" * 30
        created = start + i * spacing_s + rng.uniform(0, 59)
        candles = dip_rebound_series(created, rng)
        coins[mint] = {"created_ts": created, "candles": candles, "rows": record_coin(mint, created, candles, **kw)}
    return coins


def write_day(root: Path, store: LearnStore, coins: dict, *, incomplete: int = 0) -> str:
    """Put ``coins`` (:func:`make_coins`) on the tape at ``root`` and in ``store``, every one finished:
    the first ``incomplete`` as ``incomplete``, the rest ``closed``. Returns their first-seen day."""
    day = tape_day(next(iter(coins.values()))["created_ts"] + 600)
    with TapeWriter(root) as w:
        for i, (mint, coin) in enumerate(coins.items()):
            for stream, rows in coin["rows"].items():
                for row in rows:
                    w.append(stream, day, row)
            store.add_coin(mint, created_ts=coin["created_ts"], first_seen_ts=coin["created_ts"] + 600, day=day)
            store.set_coin_status(mint, "incomplete" if i < incomplete else "closed")
    return day


def freeze(store: LearnStore, spec: VariantSpec, t0: float) -> str:
    """Register ``spec`` and mark its ``register`` row receipted at ``t0``, as the engine does."""
    store.add_variant(spec.hash, family=spec.family, params=spec.params, source="seed", alpha=0.005,
                      threshold=200.0, promotable=spec.promotable, name=spec.name, now=t0)
    row = next(o for o in store.outbox(pending=True)
               if o["event"] == "register" and o["payload"]["variant_hash"] == spec.hash)
    store.mark_outbox(row["id"], 1, t0)
    return spec.hash
