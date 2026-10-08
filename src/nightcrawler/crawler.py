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
   never create candidates on their own. Promoted mints are remembered for
   :data:`SEEN_TTL_S`, so a nursery candidate that was boosted while it
   matured is still flagged when it is finally emitted.

Merging: same mint from several feeds -> one candidate; ``sources`` is the
union (stable order); for each field prefer the first non-None value in the
order Jupiter search/recent > Jupiter trending > GeckoTerminal.

NURSERY (why): the "recent"/"new_pools" feeds only cover the last few
minutes, but entries need ``age >= MIN_AGE_MIN`` (60 min). Too-young
candidates therefore go into :attr:`Crawler.nursery` instead of being
forgotten (their Jupiter ``stats`` are dropped there: they would be an hour
stale by the time the token matures). On every poll, nursery entries that
have matured (``now - created_at >= MIN_AGE_MIN*60``) are refreshed with ONE
DexScreener batch (<= 60 mints per poll = 2 calls), their
mcap/liquidity/price/pool updated from the snapshot, and prefiltered again:
pass -> emitted; fail (or DexScreener does not know the mint: ``"no market
data"``) -> dropped and marked seen. If the refresh call itself fails the
entries stay for the next poll. Entries still in the nursery once older than
``MIN_AGE_MIN + NURSERY_GRACE_MIN`` or beyond :data:`NURSERY_MAX` (oldest
first) are dropped (not marked seen).

Live measurement (2026-10-08): Jupiter ``recent`` lists ~70-80 new tokens per
minute, so roughly 2-4 thousand young candidates wait in the nursery at any
time; :data:`NURSERY_MAX` is sized for that.

A failing feed is logged and skipped (other feeds still count); the poll
never raises because one source is down.
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from functools import partial
from typing import Any, Callable, Final, Iterable, Sequence, TypeGuard

from nightcrawler.base58 import is_pubkey
from nightcrawler.clock import Clock
from nightcrawler.config import Settings
from nightcrawler.logging_setup import get_logger
from nightcrawler.models import SOL_MINT, MarketSnapshot, TokenCandidate
from nightcrawler.sources import Sources
from nightcrawler.sources._parse import to_float
from nightcrawler.sources.geckoterminal import pool_to_candidate
from nightcrawler.sources.jupiter import token_to_candidate

__all__ = [
    "Crawler",
    "SEEN_TTL_S",
    "NURSERY_MAX",
    "NURSERY_GRACE_MIN",
    "NURSERY_REFRESH_PER_POLL",
    "IGNORED_MINTS",
    "CURVE_DEXES",
]

log = get_logger(__name__)

#: How long a mint stays "seen" (not re-emitted by poll). 6 h = watchlist TTL.
SEEN_TTL_S = 6 * 3600
#: Max too-young candidates remembered for a later re-check (sized for ~80 new tokens/min).
NURSERY_MAX = 5000
#: Extra minutes a nursery entry may wait past MIN_AGE_MIN before it is dropped.
NURSERY_GRACE_MIN = 120
#: Max matured nursery mints refreshed per poll (2 DexScreener calls).
NURSERY_REFRESH_PER_POLL = 60

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
#: Quote/base assets that are never candidates.
IGNORED_MINTS = frozenset({SOL_MINT, USDC_MINT, USDT_MINT})
#: DexScreener dex ids of bonding curves (not yet graduated to an AMM pool).
CURVE_DEXES = frozenset({"pumpfun", "meteoradbc"})

GT_NEW_POOL_PAGES = (1, 2)
TRENDING_WINDOW: Final = "1h"
TOO_YOUNG = "too young"
NO_MARKET_DATA = "no market data"


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
        self._promoted: dict[str, dict[str, float]] = {}  # mint -> {source label: last seen ts}
        self._polls = 0
        self._emitted = 0
        self._rejected = 0
        self._feed_errors: Counter[str] = Counter()

    # ------------------------------------------------------------------ poll
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
        now = self.clock.now()
        self._polls += 1
        self.last_rejected = []
        self.expire_seen(now)
        self._remember_promotions(now)

        emitted: list[TokenCandidate] = []
        fresh = self.merge(self._fetch_candidates(now))
        for candidate in fresh:
            if candidate.mint in self.seen:
                continue
            older = self.nursery.pop(candidate.mint, None)
            if older is not None:
                candidate = self.merge([candidate, older])[0]
            self._decide(candidate, now, emitted)

        fresh_mints = {c.mint for c in fresh}
        self._mature_nursery(now, fresh_mints, emitted)
        self._prune_nursery(now)

        emitted.sort(key=_newest_first_key)
        self._emitted += len(emitted)
        self._rejected += len(self.last_rejected)
        log.info("crawler_poll fetched=%d emitted=%d rejected=%d nursery=%d seen=%d",
                 len(fresh), len(emitted), len(self.last_rejected), len(self.nursery), len(self.seen))
        return emitted

    def _decide(self, candidate: TokenCandidate, now: float, emitted: list[TokenCandidate]) -> None:
        """Prefilter one candidate: emit it, park it in the nursery, or reject it."""
        self._apply_promotion(candidate)
        ok, reason = self.prefilter(candidate, now)
        if ok:
            self.seen[candidate.mint] = now
            emitted.append(candidate)
        elif reason.startswith(TOO_YOUNG):
            candidate.stats = {}
            self.nursery[candidate.mint] = candidate
        else:
            self._reject(candidate, reason, now)

    def _reject(self, candidate: TokenCandidate, reason: str, now: float) -> None:
        self.seen[candidate.mint] = now
        self.last_rejected.append((candidate, reason))

    # ------------------------------------------------------------------ feeds
    def _fetch_candidates(self, now: float) -> list[TokenCandidate]:
        """All feed items as candidates, in merge-precedence order (Jupiter recent, trending, GT)."""
        jupiter = self.sources.jupiter
        gecko = self.sources.gecko
        out: list[TokenCandidate] = []
        out += self._convert(self._fetch("jupiter_recent", jupiter.tokens_recent),
                             lambda t: token_to_candidate(t, now, "jupiter_recent"))
        out += self._convert(self._fetch("jupiter_trending_1h", lambda: jupiter.top_trending(TRENDING_WINDOW)),
                             lambda t: token_to_candidate(t, now, "jupiter_trending_1h"))
        for page in GT_NEW_POOL_PAGES:
            out += self._convert(self._fetch(f"gt_new_pools_p{page}", partial(gecko.new_pools, page)),
                                 lambda pool: pool_to_candidate(pool, now, "gt_new_pools"))
        return [c for c in out if _is_tradable_mint(c.mint)]

    def _fetch(self, feed: str, call: Callable[[], Iterable[Any] | None]) -> list[Any]:
        """Run one feed call; on any failure log it, count it and return ``[]``."""
        try:
            return list(call() or [])
        except Exception as exc:  # one broken feed must never stop discovery
            self._feed_errors[feed] += 1
            log.warning("crawler_feed_failed feed=%s error=%s: %s", feed, type(exc).__name__, exc)
            return []

    @staticmethod
    def _convert(items: Iterable[Any], convert: Callable[[Any], TokenCandidate | None]) -> list[TokenCandidate]:
        """Convert raw feed items, skipping (and logging) items the converter cannot handle."""
        out = []
        for item in items:
            try:
                candidate = convert(item)
            except (TypeError, ValueError, KeyError, AttributeError) as exc:
                log.debug("crawler_item_skipped error=%s: %s", type(exc).__name__, exc)
                continue
            if candidate is not None:
                out.append(candidate)
        return out

    def _remember_promotions(self, now: float) -> None:
        """Record this poll's DexScreener boosts/profiles (Solana only, mints only)."""
        dex = self.sources.dexscreener
        feeds = (("dexscreener_boost", dex.token_boosts_latest), ("dexscreener_profile", dex.token_profiles_latest))
        for label, call in feeds:
            for item in self._fetch(label, call):
                mint = item.get("mint") if isinstance(item, dict) else None
                if _is_tradable_mint(mint):
                    self._promoted.setdefault(mint, {})[label] = now

    def _apply_promotion(self, candidate: TokenCandidate) -> None:
        labels = self._promoted.get(candidate.mint)
        if not labels:
            return
        candidate.paid_promo = True
        for label in sorted(labels):
            if label not in candidate.sources:
                candidate.sources.append(label)

    # ------------------------------------------------------------------ nursery
    def _mature_nursery(self, now: float, skip: set[str], emitted: list[TokenCandidate]) -> None:
        """Refresh matured nursery entries with one DexScreener batch and re-run the prefilter."""
        matured = self._matured(now, skip)
        if not matured:
            return
        mints = [c.mint for c in matured]
        try:
            snapshots = self.sources.dexscreener.snapshots(mints, now)
        except Exception as exc:  # keep the entries; retry on the next poll
            self._feed_errors["dexscreener_refresh"] += 1
            log.warning("crawler_nursery_refresh_failed mints=%d error=%s: %s", len(mints), type(exc).__name__, exc)
            return
        for candidate in matured:
            del self.nursery[candidate.mint]
            snapshot = snapshots.get(candidate.mint)
            if snapshot is None:
                self._apply_promotion(candidate)
                self._reject(candidate, NO_MARKET_DATA, now)
                continue
            _apply_snapshot(candidate, snapshot, now)
            self._decide(candidate, now, emitted)

    def _matured(self, now: float, skip: set[str]) -> list[TokenCandidate]:
        """Nursery entries at least ``MIN_AGE_MIN`` old, oldest first, at most :data:`NURSERY_REFRESH_PER_POLL`."""
        min_age_s = self.settings.min_age_min * 60
        ready: list[tuple[float, TokenCandidate]] = []
        for mint, candidate in self.nursery.items():
            created = _created_at(candidate)
            if mint not in skip and created is not None and now - created >= min_age_s:
                ready.append((created, candidate))
        ready.sort(key=lambda pair: pair[0])
        return [candidate for _, candidate in ready[:NURSERY_REFRESH_PER_POLL]]

    def _prune_nursery(self, now: float) -> None:
        """Drop entries past ``MIN_AGE_MIN + NURSERY_GRACE_MIN``, then the oldest beyond :data:`NURSERY_MAX`."""
        max_age_s = (self.settings.min_age_min + NURSERY_GRACE_MIN) * 60
        stale = [m for m, c in self.nursery.items()
                 if (created := _created_at(c)) is not None and now - created > max_age_s]
        for mint in stale:
            del self.nursery[mint]
        overflow = len(self.nursery) - NURSERY_MAX
        if overflow > 0:
            oldest = sorted(self.nursery.values(), key=lambda c: _created_at(c) or 0.0)[:overflow]
            for candidate in oldest:
                del self.nursery[candidate.mint]
        if stale or overflow > 0:
            log.info("crawler_nursery_pruned stale=%d overflow=%d", len(stale), max(overflow, 0))

    # ------------------------------------------------------------------ prefilter
    def prefilter(self, c: TokenCandidate, now: float) -> tuple[bool, str]:
        """Cheap checks on data already in the candidate. Returns ``(ok, reason)``.

        Reject when (each a distinct reason string, e.g. ``"too young: 12.0 min"``):
        * ``audit.isSus`` is True;
        * Jupiter ``audit.mintAuthorityDisabled is False`` or
          ``audit.freezeAuthorityDisabled is False`` (explicitly not renounced);
        * Jupiter ``audit.devMints > COCOON_DEV_MINTS_MAX`` (serial launcher; the
          cocoon would hard-fail it anyway, so it is rejected for free here);
        * age known and ``age_min < MIN_AGE_MIN`` or ``age_min > MAX_AGE_H*60``
          (age is measured at ``now`` from ``created_at`` when known);
        * mcap known and outside ``[MIN_MCAP_USD, MAX_MCAP_USD]``;
        * liquidity known and ``< MIN_LIQUIDITY_USD`` (unknown liquidity, e.g.
          bonding curve, passes here - Cocoon/Quote impact decide later);
        * ``organic_score`` known and ``< MIN_ORGANIC_SCORE`` (when that setting > 0).
        Unknown values never reject. ``reason`` is ``"ok"`` when passing.
        The permanent checks (audit) run before the age check, so a
        "too young" verdict means the token is worth re-checking later.
        """
        s = self.settings
        audit = c.audit or {}
        if audit.get("isSus") is True:
            return False, "suspicious: Jupiter audit.isSus"
        if audit.get("mintAuthorityDisabled") is False:
            return False, "mint authority not renounced"
        if audit.get("freezeAuthorityDisabled") is False:
            return False, "freeze authority set"
        dev_mints = to_float(audit.get("devMints"))
        if dev_mints is not None and dev_mints > s.cocoon_dev_mints_max:
            return False, f"serial launcher: dev minted {dev_mints:.0f} tokens"
        age_min = _age_min(c, now)
        if age_min is not None:
            if age_min < s.min_age_min:
                return False, f"{TOO_YOUNG}: {age_min:.1f} min"
            if age_min > s.max_age_h * 60:
                return False, f"too old: {age_min / 60:.1f} h"
        if c.mcap_usd is not None:
            if c.mcap_usd < s.min_mcap_usd:
                return False, f"mcap too low: ${c.mcap_usd:,.0f}"
            if c.mcap_usd > s.max_mcap_usd:
                return False, f"mcap too high: ${c.mcap_usd:,.0f}"
        if c.liquidity_usd is not None and c.liquidity_usd < s.min_liquidity_usd:
            return False, f"liquidity too low: ${c.liquidity_usd:,.0f}"
        if s.min_organic_score > 0 and c.organic_score is not None and c.organic_score < s.min_organic_score:
            return False, f"organic score too low: {c.organic_score:.1f}"
        return True, "ok"

    # ------------------------------------------------------------------ snapshots
    def refresh(self, mints: Sequence[str]) -> dict[str, MarketSnapshot]:
        """Current :class:`MarketSnapshot` per mint via DexScreener ``/tokens/v1`` (30 per call).

        Mints DexScreener does not return are absent. On HTTP failure returns
        ``{}`` (logged) - the engine treats missing snapshots as "no data".
        """
        unique = list(dict.fromkeys(m for m in mints if m))
        if not unique:
            return {}
        try:
            return dict(self.sources.dexscreener.snapshots(unique, self.clock.now()))
        except Exception as exc:  # the engine treats missing snapshots as "no data"
            self._feed_errors["dexscreener_refresh"] += 1
            log.warning("crawler_refresh_failed mints=%d error=%s: %s", len(unique), type(exc).__name__, exc)
            return {}

    # ------------------------------------------------------------------ memory
    def forget(self, mint: str) -> None:
        """Remove ``mint`` from ``seen`` so a later poll may emit it again."""
        self.seen.pop(mint, None)

    def expire_seen(self, now: float) -> int:
        """Drop ``seen`` entries older than :data:`SEEN_TTL_S`; return how many were dropped.

        Remembered DexScreener promotions older than the same TTL are dropped too.
        """
        cutoff = now - SEEN_TTL_S
        expired = [m for m, ts in self.seen.items() if ts < cutoff]
        for mint in expired:
            del self.seen[mint]
        for mint in list(self._promoted):
            labels = {k: ts for k, ts in self._promoted[mint].items() if ts >= cutoff}
            if labels:
                self._promoted[mint] = labels
            else:
                del self._promoted[mint]
        return len(expired)

    @staticmethod
    def merge(candidates: Sequence[TokenCandidate]) -> list[TokenCandidate]:
        """Merge candidates by mint (see module docstring for precedence); order of first appearance.

        Returns NEW objects (inputs are not mutated): scalar fields take the
        first value that is not None/"" (earlier items win), ``sources`` is an
        ordered union, dict fields (``audit``, ``stats``, ``socials``, ``raw``)
        are merged key-wise with earlier items winning, ``paid_promo`` is OR-ed.
        Exception: ``created_at`` is the EARLIEST known value (a token is as old
        as its first pool; a GeckoTerminal graduation pool is younger than the
        token) and ``age_min`` is recomputed from it at ``discovered_at``.
        """
        groups: dict[str, list[TokenCandidate]] = {}
        for c in candidates:
            groups.setdefault(c.mint, []).append(c)
        return [_merge_group(group) for group in groups.values()]

    def stats(self) -> dict[str, Any]:
        """Counters for the dashboard/logs: ``{"polls", "seen", "emitted", "rejected", "feed_errors": {feed: n}}``.

        Also ``"nursery"``: current number of young candidates waiting.
        """
        return {
            "polls": self._polls,
            "seen": len(self.seen),
            "emitted": self._emitted,
            "rejected": self._rejected,
            "nursery": len(self.nursery),
            "feed_errors": dict(self._feed_errors),
        }


# ---------------------------------------------------------------------- helpers


def _is_tradable_mint(mint: Any) -> TypeGuard[str]:
    return isinstance(mint, str) and mint not in IGNORED_MINTS and is_pubkey(mint)


def _created_at(c: TokenCandidate) -> float | None:
    """Token creation time: ``created_at``, else derived from ``discovered_at - age_min``."""
    if c.created_at is not None:
        return c.created_at
    if c.discovered_at is not None and c.age_min is not None:
        return c.discovered_at - c.age_min * 60
    return None


def _age_min(c: TokenCandidate, now: float) -> float | None:
    created = _created_at(c)
    return (now - created) / 60 if created is not None else c.age_min


def _newest_first_key(c: TokenCandidate) -> tuple[bool, float]:
    created = _created_at(c)
    return (created is None, -(created or 0.0))


def _apply_snapshot(c: TokenCandidate, snap: MarketSnapshot, now: float) -> None:
    """Overwrite a matured nursery entry's stale market fields with a fresh DexScreener snapshot."""
    c.raw = {**c.raw, "nursery_since": c.discovered_at}
    c.mcap_usd = snap.mcap_usd
    c.liquidity_usd = snap.liquidity_usd
    c.price_usd = snap.price_usd
    if snap.fdv_usd is not None:
        c.fdv_usd = snap.fdv_usd
    if snap.pool:
        c.pool = snap.pool
    if snap.dex:
        c.dex = snap.dex
        if c.graduated is False and snap.dex not in CURVE_DEXES:
            c.graduated = True
    c.discovered_at = now
    age = _age_min(c, now)
    if age is not None:
        c.age_min = age


def _first_present(values: list[Any]) -> Any:
    return next((v for v in values if v is not None and v != ""), values[0])


def _ordered_union(lists: list[list[Any]]) -> list[Any]:
    return list(dict.fromkeys(item for items in lists for item in items))


def _merge_dicts(dicts: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for d in reversed(dicts):  # earlier dicts win
        out.update(d)
    return out


def _merge_group(group: list[TokenCandidate]) -> TokenCandidate:
    merged: dict[str, Any] = {}
    for f in dataclasses.fields(TokenCandidate):
        values = [getattr(c, f.name) for c in group]
        if f.name == "paid_promo":
            merged[f.name] = any(values)
        elif isinstance(values[0], list):
            merged[f.name] = _ordered_union(values)
        elif isinstance(values[0], dict):
            merged[f.name] = _merge_dicts(values)
        else:
            merged[f.name] = _first_present(values)
    created = [c.created_at for c in group if c.created_at is not None]
    if created:
        merged["created_at"] = min(created)
        if merged["discovered_at"] is not None:
            merged["age_min"] = (merged["discovered_at"] - merged["created_at"]) / 60
    return TokenCandidate(**merged)
