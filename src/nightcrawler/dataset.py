"""Unbiased multi-coin dataset collector (owner: O3).

Pulls recent Solana pools from GeckoTerminal ``new_pools`` pages 1..10
(INCLUDING ones that later rugged or died - never filter by survival, that
would be survivorship bias), keeps pools at least ``min_age_h`` old (so the
first ``hours`` of history exist), downloads 1m candles
(``include_empty_intervals=true``) from pool creation for up to ``hours``
hours, and writes one JSON per pool in the backtest format to
``out_dir/<pool>.json``::

    {"coin": symbol, "name": str, "mint": str, "pool": str, "dex": str,
     "supply": float|null, "created_utc": iso, "collected_utc": iso,
     "source": "geckoterminal ohlcv/minute aggregate=1 currency=usd token=base",
     "candles": [[ts, o, h, l, c, v], ...]}

Resumable: an existing file for a pool is skipped (``resume=True``).
Rate budget: all calls go through the shared HttpClient (GT 20/min); a
100-pool, 24 h collection needs ~2 OHLCV pages per pool + 10 list pages.
Progress is reported through the optional ``progress(done, total, pool)`` callback.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from nightcrawler.clock import Clock

__all__ = ["CollectSummary", "collect", "select_pools"]


@dataclass(slots=True)
class CollectSummary:
    out_dir: str
    considered: int = 0
    written: list[str] = field(default_factory=list)
    skipped_existing: int = 0
    skipped_young: int = 0
    failed: dict[str, str] = field(default_factory=dict)  # pool -> error


def select_pools(pools: list[dict[str, Any]], now: float, min_age_h: float, n_pools: int) -> list[dict[str, Any]]:
    """PURE: from normalized GT pools keep those with ``created_at <= now - min_age_h*3600``,
    excluding pools whose base token is SOL/USDC/USDT, dedupe by pool, newest first, at most ``n_pools``."""
    raise NotImplementedError


def collect(gecko: Any, out_dir: str | os.PathLike[str] | Path, n_pools: int = 100, min_age_h: float = 24.0,
            hours: float = 24.0, clock: Clock | None = None, resume: bool = True,
            progress: Callable[[int, int, str], None] | None = None) -> CollectSummary:
    """Collect the dataset (see module docstring). Never raises for a single pool's failure
    (recorded in ``failed``); raises only if the pool listing itself fails completely."""
    raise NotImplementedError
