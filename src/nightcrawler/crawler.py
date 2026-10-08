"""Multi-source token discovery (owner: O2).

``Crawler.poll()`` merges several free feeds into deduplicated
:class:`~nightcrawler.models.TokenCandidate` objects and applies CHEAP
prefilters (no extra HTTP calls per token). Expensive safety checks happen
later in :mod:`nightcrawler.cocoon`.

Per poll (HTTP budget ~5 calls; the engine polls every DISCOVERY_INTERVAL_S):

1. Jupiter ``tokens/v2/recent`` -> ``source="jupiter_recent"``
2. Jupiter ``tokens/v2/toptrending/1h`` -> ``source="jupiter_trending_1h"``
3. GeckoTerminal ``new_pools`` pages 1-2 -> ``source="gt_new_pools"``
4. DexScreener ``token-boosts/latest`` + ``token-profiles/latest`` (Solana only)
   -> only used to set ``paid_promo=True`` (and add ``"dexscreener_boost"`` /
   ``"dexscreener_profile"`` to ``sources``) on candidates found by 1-3; they
   never create candidates on their own.

Merging: same mint from several feeds -> one candidate; ``sources`` is the
union (stable order); for each field prefer the first non-None value in the
order Jupiter search/recent > Jupiter trending > GeckoTerminal.

NURSERY (why): the "recent"/"new_pools" feeds only cover the last few
minutes, but entries need ``age >= MIN_AGE_MIN`` (60 min). Too-young
candidates therefore go into :attr:`Crawler.nursery` instead of being
forgotten. On every poll, nursery entries that have matured (``now -
created_at >= MIN_AGE_MIN*60``) are refreshed with ONE DexScreener batch
(<= 60 mints per poll = 2 calls), their mcap/liquidity/price updated from
the snapshot, and prefiltered again: pass -> emitted; fail -> dropped and
marked seen. Entries still unmatured after ``MIN_AGE_MIN + NURSERY_GRACE_MIN``
or beyond :data:`NURSERY_MAX` (oldest first) are dropped.

A failing feed is logged and skipped (other feeds still count); the poll
never raises because one source is down.
"""

from __future__ import annotations

from typing import Any, Sequence

from nightcrawler.clock import Clock
from nightcrawler.config import Settings
from nightcrawler.models import MarketSnapshot, TokenCandidate
from nightcrawler.sources import Sources

__all__ = ["Crawler", "SEEN_TTL_S", "NURSERY_MAX", "NURSERY_GRACE_MIN", "NURSERY_REFRESH_PER_POLL"]

#: How long a mint stays "seen" (not re-emitted by poll). 6 h = watchlist TTL.
SEEN_TTL_S = 6 * 3600
#: Max too-young candidates remembered for a later re-check.
NURSERY_MAX = 1000
#: Extra minutes a nursery entry may wait past MIN_AGE_MIN before it is dropped.
NURSERY_GRACE_MIN = 120
#: Max matured nursery mints refreshed per poll (2 DexScreener calls).
NURSERY_REFRESH_PER_POLL = 60


class Crawler:
    """Discovery + cheap prefilters + snapshot refresh.

    Attributes:
        last_rejected: ``[(candidate, reason)]`` from the most recent ``poll``
            (prefilter rejections) so the engine can log/receipt a summary.
        seen: ``{mint: first_seen_ts}`` TTL memory (entries older than
            :data:`SEEN_TTL_S` are forgotten and may be re-discovered).
        nursery: ``{mint: TokenCandidate}`` too-young candidates awaiting
            maturity (see module docstring).
    """

    def __init__(self, sources: Sources, settings: Settings, clock: Clock) -> None:
        self.sources = sources
        self.settings = settings
        self.clock = clock
        self.seen: dict[str, float] = {}
        self.nursery: dict[str, TokenCandidate] = {}
        self.last_rejected: list[tuple[TokenCandidate, str]] = []

    def poll(self) -> list[TokenCandidate]:
        """Fetch all feeds once and return NEWLY discovered candidates that pass :meth:`prefilter`.

        * A mint already in ``seen`` (within TTL) is not returned again,
          whether it passed or failed before. Emitted and rejected mints are
          marked seen - EXCEPT "too young" ones, which go to the nursery and
          are re-checked when they mature (see module docstring).
        * ``last_rejected`` holds this poll's NEW rejections only (each mint
          once until it leaves ``seen``), so logs are not spammed.
        * SOL / USDC / USDT mints and invalid addresses are dropped silently.
        * Output order: by ``created_at`` descending (newest first), None last.
        * Never raises on a source failure (logs a warning per failed feed).
        """
        raise NotImplementedError

    def prefilter(self, c: TokenCandidate, now: float) -> tuple[bool, str]:
        """Cheap checks on data already in the candidate. Returns ``(ok, reason)``.

        Reject when (each a distinct reason string, e.g. ``"too young: 12.0 min"``):
        * age known and ``age_min < MIN_AGE_MIN`` or ``age_min > MAX_AGE_H*60``;
        * mcap known and outside ``[MIN_MCAP_USD, MAX_MCAP_USD]``;
        * liquidity known and ``< MIN_LIQUIDITY_USD`` (unknown liquidity, e.g.
          bonding curve, passes here - Cocoon/Quote impact decide later);
        * ``audit.isSus`` is True;
        * Jupiter ``audit.mintAuthorityDisabled is False`` or
          ``audit.freezeAuthorityDisabled is False`` (explicitly not renounced);
        * ``organic_score`` known and ``< MIN_ORGANIC_SCORE`` (when that setting > 0).
        Unknown values never reject. ``reason`` is ``"ok"`` when passing.
        """
        raise NotImplementedError

    def refresh(self, mints: Sequence[str]) -> dict[str, MarketSnapshot]:
        """Current :class:`MarketSnapshot` per mint via DexScreener ``/tokens/v1`` (30 per call).

        Mints DexScreener does not return are absent. On HTTP failure returns
        ``{}`` (logged) - the engine treats missing snapshots as "no data".
        """
        raise NotImplementedError

    def forget(self, mint: str) -> None:
        """Remove ``mint`` from ``seen`` so a later poll may emit it again."""
        raise NotImplementedError

    def expire_seen(self, now: float) -> int:
        """Drop ``seen`` entries older than :data:`SEEN_TTL_S`; return how many were dropped."""
        raise NotImplementedError

    @staticmethod
    def merge(candidates: Sequence[TokenCandidate]) -> list[TokenCandidate]:
        """Merge candidates by mint (see module docstring for precedence); order of first appearance."""
        raise NotImplementedError

    def stats(self) -> dict[str, Any]:
        """Counters for the dashboard/logs: ``{"polls", "seen", "emitted", "rejected", "feed_errors": {feed: n}}``."""
        raise NotImplementedError
