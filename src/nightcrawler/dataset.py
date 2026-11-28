"""Unbiased multi-coin dataset collector (owner: O3).

Builds backtest files for pools sampled WITHOUT looking at their outcome:
every pool GeckoTerminal lists in ``new_pools`` is recorded, including the
ones that later rugged or died - never filter by survival, that would be
survivorship bias.

Why a census (verified live 2026-10-08): ``new_pools`` pages 1..10 hold only
the ~200 newest Solana pools, i.e. the last ~3 MINUTES of launches. A pool
that is already ``min_age_h`` old is never in the live listing. So each
:func:`collect` call does two things:

1. **Census**: append every pool from ``new_pools`` pages 1..``max_pages``
   to ``out_dir/census.jsonl`` (one normalized pool per line, plus
   ``discovered_at``; first sighting wins). The census is the sampling frame:
   pools enter it at birth, before anything about their future is known.
2. **Download**: from the census, :func:`select_pools` keeps pools at least
   ``min_age_h`` old (so the first ``hours`` of history exist), newest first,
   at most ``n_pools``; for each, 1m candles (``include_empty_intervals=true``)
   from pool creation for up to ``hours`` hours are written to
   ``out_dir/<pool>.json`` in the backtest format::

    {"coin": symbol, "name": str, "mint": str, "pool": str, "dex": str,
     "supply": float|null, "created_utc": iso, "collected_utc": iso,
     "discovered_utc": iso, "source": "geckoterminal ohlcv/minute aggregate=1 currency=usd token=base",
     "candles": [[ts, o, h, l, c, v], ...]}

   ``supply`` (whole tokens, for market cap) = ``fdv_usd / price_usd`` at
   discovery. A pool that never traded is written with ``"candles": []`` so
   it is not retried (the backtester skips it; it could not be traded).

Run it periodically (e.g. hourly): the census grows by up to ~200 pools per
call and pools are downloaded once they are old enough. Systematic sampling
in time is unbiased; a single call right after the first one finds nothing
old enough yet - that is expected, not an error.

Resumable: an existing file for a pool is skipped (``resume=True``). A pool
younger than ``hours`` gets only the closed history that exists and is not
re-downloaded later, so keep ``min_age_h >= hours`` (the defaults) for complete windows.
Rate budget: all calls go through the shared HttpClient (GT 20/min); a call
costs ``max_pages`` listing requests + ~1 OHLCV request per 1000 candles per pool.
Progress is reported through the optional ``progress(done, total, pool)`` callback.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from nightcrawler.clock import Clock, RealClock, iso_utc, minute_floor
from nightcrawler.logging_setup import get_logger
from nightcrawler.models import SOL_MINT, Candle

__all__ = [
    "CENSUS_FILE",
    "EXCLUDED_BASE_MINTS",
    "SOURCE_NOTE",
    "CollectSummary",
    "collect",
    "select_pools",
    "load_census",
    "update_census",
]

log = get_logger(__name__)

CENSUS_FILE = "census.jsonl"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
#: Base tokens that are quote assets, not launches.
EXCLUDED_BASE_MINTS = frozenset({SOL_MINT, USDC_MINT, USDT_MINT})
SOURCE_NOTE = "geckoterminal ohlcv/minute aggregate=1 currency=usd token=base"
#: Normalized pool keys kept in the census (small, JSON-native).
_CENSUS_KEYS = ("pool", "name", "dex", "base_mint", "quote_mint", "base_symbol", "base_name", "created_at",
                "price_usd", "fdv_usd", "reserve_usd")


@dataclass(slots=True)
class CollectSummary:
    out_dir: str
    considered: int = 0  # pools in the census after this call's listing
    written: list[str] = field(default_factory=list)
    skipped_existing: int = 0
    skipped_young: int = 0
    failed: dict[str, str] = field(default_factory=dict)  # pool (or "new_pools p<N>") -> error
    census_added: int = 0
    empty: int = 0  # written with no candles (never traded)


def select_pools(pools: list[dict[str, Any]], now: float, min_age_h: float, n_pools: int) -> list[dict[str, Any]]:
    """PURE: from normalized GT pools keep those with ``created_at <= now - min_age_h*3600``,
    excluding pools whose base token is SOL/USDC/USDT, dedupe by pool, newest first, at most ``n_pools``.

    Pools without ``pool`` / ``created_at`` are dropped (age unknown). The first
    occurrence of a duplicated pool wins.
    """
    cutoff = now - min_age_h * 3600
    seen: set[str] = set()
    kept = []
    for p in pools:
        address, created = p.get("pool"), p.get("created_at")
        if not address or created is None or address in seen:
            continue
        seen.add(address)
        if created <= cutoff and p.get("base_mint") not in EXCLUDED_BASE_MINTS:
            kept.append(p)
    kept.sort(key=lambda p: p["created_at"], reverse=True)
    return kept[:max(0, n_pools)]


def load_census(out_dir: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Census records in discovery order (first sighting per pool wins); [] if none.

    Unparseable lines (e.g. a write cut short by a crash) are skipped.
    """
    path = Path(out_dir) / CENSUS_FILE
    if not path.is_file():
        return []
    records: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("pool") and rec["pool"] not in records:
            records[rec["pool"]] = rec
    return list(records.values())


def update_census(out_dir: str | os.PathLike[str], pools: Iterable[dict[str, Any]], now: float) -> int:
    """Append pools not yet in the census (with ``discovered_at = now``); returns how many were added."""
    known = {rec["pool"] for rec in load_census(out_dir)}
    lines = []
    for p in pools:
        address = p.get("pool")
        if not address or address in known:
            continue
        known.add(address)
        rec = {k: p.get(k) for k in _CENSUS_KEYS}
        rec["discovered_at"] = now
        lines.append(json.dumps(rec, sort_keys=True))
    if lines:
        path = Path(out_dir) / CENSUS_FILE
        torn = path.is_file() and not path.read_bytes().endswith(b"\n")  # a crash cut the last line
        with path.open("a", encoding="utf-8") as fh:
            fh.write(("\n" if torn else "") + "\n".join(lines) + "\n")
    return len(lines)


def collect(gecko: Any, out_dir: str | os.PathLike[str] | Path, n_pools: int = 100, min_age_h: float = 24.0,
            hours: float = 24.0, clock: Clock | None = None, resume: bool = True,
            progress: Callable[[int, int, str], None] | None = None, max_pages: int = 10) -> CollectSummary:
    """Update the census, then download candles for old-enough census pools (see module docstring).

    ``gecko``: a :class:`~nightcrawler.sources.geckoterminal.GeckoTerminalClient`
    (``new_pools(page)``, ``ohlcv(pool, minutes, aggregate, before)``).
    Never raises for a single pool's failure (recorded in ``failed``); raises
    :class:`RuntimeError` only if every listing page fails AND the census is
    empty (nothing to work on).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    clock = clock or getattr(gecko, "clock", None) or RealClock()
    now = clock.now()
    summary = CollectSummary(out_dir=str(out))

    listed, errors = _list_new_pools(gecko, max_pages)
    summary.failed.update(errors)
    summary.census_added = update_census(out, listed, now)
    census = load_census(out)
    summary.considered = len(census)
    if not census and errors and not listed:
        raise RuntimeError(f"GeckoTerminal new_pools listing failed: {'; '.join(errors.values())}")

    selected = select_pools(census, now, min_age_h, n_pools)
    cutoff = now - min_age_h * 3600
    summary.skipped_young = sum(1 for p in census if p.get("created_at") is not None and p["created_at"] > cutoff)
    for done, pool in enumerate(selected, start=1):
        _collect_one(gecko, out, pool, now, hours, resume, summary)
        if progress is not None:
            progress(done, len(selected), pool["pool"])
    log.info("dataset_collect out=%s census=%d added=%d written=%d existing=%d young=%d failed=%d",
             out, summary.considered, summary.census_added, len(summary.written), summary.skipped_existing,
             summary.skipped_young, len(summary.failed))
    return summary


def _list_new_pools(gecko: Any, max_pages: int) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Pools from ``new_pools`` pages 1..max_pages (stops at an empty page); per-page errors collected."""
    pools: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for page in range(1, max_pages + 1):
        try:
            batch = gecko.new_pools(page)
        except Exception as exc:  # one bad page must not lose the others
            errors[f"new_pools p{page}"] = f"{type(exc).__name__}: {exc}"
            continue
        if not batch:
            break
        pools.extend(batch)
    return pools, errors


def _collect_one(gecko: Any, out: Path, pool: dict[str, Any], now: float, hours: float, resume: bool,
                 summary: CollectSummary) -> None:
    address = pool["pool"]
    path = out / f"{address}.json"
    if resume and path.exists():
        summary.skipped_existing += 1
        return
    try:
        candles = _download_candles(gecko, address, pool["created_at"], now, hours)
    except Exception as exc:  # recorded, the next pool still runs
        summary.failed[address] = f"{type(exc).__name__}: {exc}"
        log.warning("dataset_pool_failed pool=%s error=%s", address, type(exc).__name__)
        return
    _write_json(path, _series_doc(pool, candles, now))
    summary.written.append(address)
    if not candles:
        summary.empty += 1


def _download_candles(gecko: Any, pool: str, created_at: float, now: float, hours: float) -> list[Candle]:
    """Closed 1m candles in ``[minute(created_at), min(created + hours, minute(now)))``."""
    start = minute_floor(created_at)
    end = min(minute_floor(now), start + int(hours * 3600))
    if end <= start:
        return []
    return gecko.ohlcv(pool, (end - start) // 60, aggregate=1, before=end)


def _series_doc(pool: dict[str, Any], candles: list[Candle], now: float) -> dict[str, Any]:
    price, fdv = pool.get("price_usd"), pool.get("fdv_usd")
    return {
        "coin": pool.get("base_symbol") or "",
        "name": pool.get("base_name") or "",
        "mint": pool.get("base_mint"),
        "pool": pool["pool"],
        "dex": pool.get("dex"),
        "supply": fdv / price if price and fdv else None,
        "created_utc": iso_utc(pool["created_at"]),
        "collected_utc": iso_utc(now),
        "discovered_utc": iso_utc(pool.get("discovered_at")),
        "source": SOURCE_NOTE,
        "candles": [c.to_row() for c in candles],
    }


def _write_json(path: Path, doc: dict[str, Any]) -> None:
    """Atomic write (temp file + rename) so an interrupted run never leaves a half file to 'resume' past."""
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)
