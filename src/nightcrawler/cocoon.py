"""Cocoon: the hard rug filter (owner: O2). FAIL CLOSED.

``Cocoon.check(candidate)`` gathers evidence from RugCheck (report), Solana RPC
(mint account) and Jupiter (audit fields already on the candidate + Shield),
and returns a
:class:`~nightcrawler.models.SafetyReport`.

HARD FAILS (``passed=False``; one reason string each, stable wording so the
dashboard can group them - start each with the rule id shown in brackets):

* ``[mint_authority]`` mint authority not renounced (RPC ``mintAuthority`` not null,
  or RugCheck ``mintAuthority`` not null).
* ``[freeze_authority]`` freeze authority set.
* ``[token2022_ext]`` dangerous Token-2022 extension present: any of
  :data:`DANGEROUS_EXTENSIONS`; ``defaultAccountState`` only when its state is
  ``frozen``.
* ``[rugged]`` RugCheck ``rugged`` true.
* ``[rugcheck_danger]`` any RugCheck risk with level ``danger`` (name listed).
* ``[top10]`` top-10 holder share (AMM/curve/locker excluded) >
  ``COCOON_TOP10_MAX_PCT`` (30 %).
* ``[single_holder]`` one non-AMM holder > ``COCOON_SINGLE_HOLDER_MAX_PCT`` (10 %).
* ``[creator_holding]`` creator still holds > ``COCOON_CREATOR_MAX_PCT`` (5 %)
  (RugCheck creator_pct; fallback Jupiter ``audit.devBalancePercentage`` or GT
  ``developer_holding_pct``).
* ``[insiders]`` ``graphInsidersDetected >= COCOON_GRAPH_INSIDERS_MIN`` AND
  insider share (insider network pct, else insider-flagged holder pct) >
  ``COCOON_INSIDER_MAX_PCT`` (15 %).
* ``[serial_launcher]`` Jupiter ``audit.devMints > COCOON_DEV_MINTS_MAX`` (20) or
  RugCheck risk "Creator history of rugged tokens".
* ``[shield]`` Jupiter Shield warning with severity ``warning`` or ``critical``.
* ``[lp_unlocked]`` graduated AMM pool (not a bonding curve) with LP
  locked/burned < ``COCOON_LP_LOCKED_MIN_PCT`` (90 %). Pump.fun graduated
  pools (pumpswap) burn LP; trust RugCheck ``markets[].lp.lpLockedPct``.

WARNINGS (not fatal): mutable metadata, no socials, paid promotion
(DexScreener boost/profile), holder count < ``COCOON_MIN_HOLDERS``, holder
stats unavailable (fresh token).

DEGRADATION: if a REQUIRED source fails (RugCheck report, RPC mint info,
Jupiter Shield), add ``"source unavailable: <name>"`` to ``hard_fail_reasons``
and the source name to ``unverified`` -> ``passed=False``. RugCheck
``ReportUnavailable`` (too new) -> ``"source unavailable: rugcheck (not ready)"``
and the report is NOT cached, so the next check retries. GeckoTerminal token
info is NOT called by default (GT is the scarcest budget); if an implementer
adds it as a cross-check, its failure may only add a warning.

CACHE: reports are cached per mint for ``COCOON_CACHE_MIN`` (30) minutes;
``check(..., force=True)`` bypasses it. Failed-closed reports caused by an
unavailable source are cached for at most 2 minutes.

``metrics`` keys written: ``top10_pct, max_holder_pct, creator_pct,
insider_pct, graph_insiders, dev_mints, lp_locked_pct, holder_count,
rugcheck_score_normalised, mint_authority, freeze_authority, extensions,
shield_warnings, program``.
"""

from __future__ import annotations

from nightcrawler.clock import Clock
from nightcrawler.config import Settings
from nightcrawler.models import SafetyReport, TokenCandidate
from nightcrawler.sources import Sources

__all__ = ["Cocoon", "DANGEROUS_EXTENSIONS", "UNAVAILABLE_CACHE_S"]

#: Token-2022 extensions that let someone tax, seize, block or freeze holders.
DANGEROUS_EXTENSIONS = frozenset({
    "transferFeeConfig",
    "permanentDelegate",
    "transferHook",
    "pausableConfig",
    "nonTransferable",
    "defaultAccountState",  # only when the default state is "frozen"
})
UNAVAILABLE_CACHE_S = 120


class Cocoon:
    """Rug filter with a per-mint TTL cache. Thread-compatible (engine calls it from one thread)."""

    def __init__(self, sources: Sources, settings: Settings, clock: Clock) -> None:
        self.sources = sources
        self.settings = settings
        self.clock = clock
        self._cache: dict[str, tuple[float, SafetyReport]] = {}

    def check(self, candidate: TokenCandidate, *, force: bool = False) -> SafetyReport:
        """Evaluate ``candidate`` and return a :class:`SafetyReport` (never raises).

        ``passed`` is True only when ``hard_fail_reasons`` and ``unverified``
        are both empty. ``checked_at`` = ``clock.now()``. Fills ``creator``,
        ``top_holders`` (non-excluded owner wallets, largest first, max 20) and
        ``insiders`` for the radar. Any unexpected exception becomes a
        fail-closed report with reason ``"error: <ExceptionType>"``.
        """
        raise NotImplementedError

    def invalidate(self, mint: str) -> None:
        """Drop the cached report for ``mint`` (no-op if absent)."""
        raise NotImplementedError

    def cached(self, mint: str) -> SafetyReport | None:
        """Cached, still-fresh report for ``mint`` or None."""
        raise NotImplementedError
