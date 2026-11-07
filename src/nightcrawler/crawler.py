"""Multi-source token discovery (owner: O2).

``Crawler.poll()`` merges several free feeds into deduplicated
:class:`~nightcrawler.models.TokenCandidate` objects and applies CHEAP
prefilters (no extra HTTP calls per token). Expensive safety checks happen
later in :mod:`nightcrawler.cocoon`.

Per poll (HTTP budget ~4 calls; the engine polls every DISCOVERY_INTERVAL_S):

1. Jupiter ``tokens/v2/recent`` -> ``source="jupiter_recent"``
2. Jupiter ``tokens/v2/toptrending/1h`` -> ``source="jupiter_trending_1h"``
3. OPTIONAL (``DISCOVER_GT_NEW_POOLS``, off by default): GeckoTerminal
   ``new_pools`` pages 1-2 -> ``source="gt_new_pools"``, the lowest-priority
   feed. GeckoTerminal's free budget is the scarcest one (429s on shared IPs
   such as Railway's), so by default it is reserved for candles and the radar.
   A 429 skips the remaining pages and pauses the feed for :data:`GT_FEED_PAUSE_S`.
4. DexScreener ``token-boosts/latest`` + ``token-profiles/latest`` (Solana only)
   -> only used to set ``paid_promo=True`` (and add ``"dexscreener_boost"`` /
   ``"dexscreener_profile"`` to ``sources``) on candidates found by 1-3; they
   never create candidates on their own. Promoted mints are remembered for
   :data:`SEEN_TTL_S`, so a nursery candidate that was boosted while it
   matured is still flagged when it is finally emitted.

LAUNCHPAD DEPLOYERS (RT-11): some launchpads and launch services deploy every
coin from ONE shared address, so Jupiter's ``dev`` is the platform and
``audit.devMints`` counts the whole platform (100k+ coins), not one person's
history. :func:`launchpad_deployer` recognises them (:data:`KNOWN_LAUNCHPAD_DEPLOYERS`,
or a coin WITH a launchpad whose deployer minted at least
:data:`FACTORY_DEV_MINTS_MIN` tokens); the serial-launcher prefilter applies only to
individual creators, and such a candidate's platform count is filed under
``audit["deployerMints"]`` (``raw["deployer"]`` names the platform) so the
cocoon's ``devMints`` rule does not misfire on it either.

TESTED UNIVERSE (G01 + N3): every result we have (lab census, CryptoHouse, lab2, the Coach replay)
covers pump.fun graduates quoted in SOL that are not Mayhem coins, so the bot trades only those:
:func:`universe_problem` refuses another launchpad (bags.fun, launch services ...), a coin without one
and a known non-SOL launch quote; the cocoon refuses Mayhem coins (their on-chain supply is 2e9).
These are permanent, so they run right after the audit checks.

AGE FROM GRADUATION (G12): ``MIN_AGE_MIN`` counts from creation, so a slow graduate created long ago
could be bought the minute it graduated (inside the BOOST bid and the lab's 30-min ban). Now a coin also
needs ``MIN_AGE_SINCE_GRAD_MIN`` since its graduation (:func:`graduated_at`: Jupiter ``graduatedAt``; for
a graduate Jupiter reported without one, ONE GeckoTerminal token lookup, ``launchpad.completed_at``, at most
:data:`GRADUATION_LOOKUPS_PER_POLL` per poll and once per :data:`GRADUATION_RETRY_S` per mint). A coin too
young since graduation, still on its bonding curve, or whose graduation time is not known yet WAITS in the
nursery (never traded blind, never marked seen); its maturity is its ELIGIBLE time, the later of creation
+ ``MIN_AGE_MIN`` and graduation + ``MIN_AGE_SINCE_GRAD_MIN``. The engine's entry check and the Coach replay
apply the same window (``engine._universe_problem``, ``learn/replay.py``).

PERSISTENCE (RT-14): :meth:`Crawler.export_nursery` / :meth:`Crawler.restore_nursery`
let the engine keep the nursery in the ledger kv across redeploys (bounded by
:data:`NURSERY_MAX`; entries too old to mature are dropped on restore).

Merging: same mint from several feeds -> one candidate; ``sources`` is the
union (stable order); for each field prefer the first non-None value in the
order Jupiter search/recent > Jupiter trending > GeckoTerminal.

NURSERY (why): the "recent"/"new_pools" feeds only cover the last few
minutes, but entries need ``age >= MIN_AGE_MIN`` (60 min). Too-young
candidates (and the other waits above) therefore go into :attr:`Crawler.nursery` instead of being
forgotten (their Jupiter ``stats`` are dropped there: they would be an hour
stale by the time the token matures). On every poll, nursery entries that
have matured (their eligible time has come) are refreshed with ONE
DexScreener batch (<= 60 mints per poll = 2 calls), their
mcap/liquidity/price/pool updated from the snapshot, and prefiltered again:
pass -> emitted; fail (or DexScreener does not know the mint: ``"no market
data"``) -> dropped and marked seen. If the refresh call itself fails the
entries stay for the next poll. Entries still in the nursery once
``NURSERY_GRACE_MIN`` past their eligible time or beyond :data:`NURSERY_MAX` (oldest
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
from nightcrawler.costs import SOL_QUOTE
from nightcrawler.http import HttpError
from nightcrawler.logging_setup import get_logger
from nightcrawler.models import SOL_MINT, MarketSnapshot, TokenCandidate
from nightcrawler.sources import Sources
from nightcrawler.sources._parse import parse_ts, to_float
from nightcrawler.sources.geckoterminal import graduation_time, pool_to_candidate
from nightcrawler.sources.jupiter import token_to_candidate

__all__ = [
    "Crawler",
    "SEEN_TTL_S",
    "NURSERY_MAX",
    "NURSERY_GRACE_MIN",
    "NURSERY_REFRESH_PER_POLL",
    "IGNORED_MINTS",
    "CURVE_DEXES",
    "GT_FEED_PAUSE_S",
    "KNOWN_LAUNCHPAD_DEPLOYERS",
    "FACTORY_DEV_MINTS_MIN",
    "TESTED_LAUNCHPADS",
    "SOL_QUOTE_MINTS",
    "GRADUATION_LOOKUPS_PER_POLL",
    "GRADUATION_RETRY_S",
    "NOT_GRADUATED",
    "GRADUATION_UNKNOWN",
    "launchpad_deployer",
    "universe_problem",
    "graduated_at",
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
#: After a GeckoTerminal 429 the optional new_pools feed is skipped for this long (seconds).
GT_FEED_PAUSE_S = 300.0

#: Shared deployer addresses of launchpads / launch services (Jupiter tokens/v2 ``dev``), seen live
#: 2026-10-08 as the ``dev`` of many unrelated trending coins, with 170k-191k ``devMints`` each.
KNOWN_LAUNCHPAD_DEPLOYERS: Final[dict[str, str]] = {
    "BAGSB9TpGrZxQbEsrEznv5jXXdwyP6AXerN8aVRiAmcv": "bags.fun",  # 190,960 coins
    "bwamJzztZsepfkteWRChggmXuiiCQvpLqPietdNfSXa": "launch service (pump.fun, stonkfun)",  # 169,827 coins
}
#: A coin WITH a launchpad whose deployer minted at least this many tokens came from a platform
#: (factory) deployer, not a person: individual creators measured live 2026-10-08 topped out near
#: 22k (bots included), shared deployers started above 150k.
FACTORY_DEV_MINTS_MIN = 100_000
#: The only launchpad whose graduates any test covered (G01, N3; lower case, as Jupiter's ``launchpad``).
TESTED_LAUNCHPADS: Final = frozenset({"pump.fun"})
#: Launch quotes that are SOL: wrapped SOL (pool quote) and the pump.fun census's native-SOL marker.
SOL_QUOTE_MINTS: Final = frozenset({SOL_MINT, SOL_QUOTE})
#: GeckoTerminal token lookups per poll for a graduation time Jupiter did not send (GT is the scarcest budget).
GRADUATION_LOOKUPS_PER_POLL = 2
#: A mint GeckoTerminal could not date is asked again at most this often (seconds; < GT_FEED_PAUSE_S).
GRADUATION_RETRY_S = 120.0
TRENDING_WINDOW: Final = "1h"
TOO_YOUNG = "too young"
NOT_GRADUATED = "not graduated yet"
GRADUATION_UNKNOWN = "graduation time unknown"
#: Prefilter reasons that mean "not yet": the candidate waits in the nursery instead of being rejected.
_WAITS = (TOO_YOUNG, NOT_GRADUATED, GRADUATION_UNKNOWN)
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
        #: every candidate the last poll fetched (merged, before the prefilter; seen ones too)
        self.last_fetched: list[TokenCandidate] = []
        self._promoted: dict[str, dict[str, float]] = {}  # mint -> {source label: last seen ts}
        self._polls = 0
        self._emitted = 0
        self._rejected = 0
        self._feed_errors: Counter[str] = Counter()
        self._gt_paused_until = 0.0
        self._graduation_tried: dict[str, float] = {}  # mint -> last GeckoTerminal graduation lookup
        self._graduation_lookups_left = 0

    # ------------------------------------------------------------------ poll
    def poll(self) -> list[TokenCandidate]:
        """Fetch all feeds once and return NEWLY discovered candidates that pass :meth:`prefilter`.

        * A mint already in ``seen`` (within TTL) is not returned again,
          whether it passed or failed before. Emitted and rejected mints are
          marked seen - EXCEPT "too young" ones, which go to the nursery and
          are re-checked when they mature (see module docstring).
        * ``last_rejected`` holds this poll's NEW rejections only (each mint
          once until it leaves ``seen``), so logs are not spammed;
          ``last_fetched`` every merged candidate the feeds returned (the
          engine shows them all to the cocoon's copycat check).
        * SOL / USDC / USDT mints and invalid addresses are dropped silently.
        * Output order: by ``created_at`` descending (newest first), None last.
        * Never raises on a source failure (logs a warning per failed feed).
        """
        now = self.clock.now()
        self._polls += 1
        self.last_rejected = []
        self._graduation_lookups_left = GRADUATION_LOOKUPS_PER_POLL
        self.expire_seen(now)
        self._remember_promotions(now)

        emitted: list[TokenCandidate] = []
        fresh = self.merge(self._fetch_candidates(now))
        self.last_fetched = list(fresh)
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
        """Prefilter one candidate: emit it, park it in the nursery (a wait, :data:`_WAITS`), or reject it.
        A graduate without a graduation time gets one GeckoTerminal lookup first (bounded, see the docstring)."""
        self._apply_promotion(candidate)
        _file_platform_mints(candidate)
        ok, reason = self.prefilter(candidate, now)
        if reason == GRADUATION_UNKNOWN and self._lookup_graduation(candidate, now):
            ok, reason = self.prefilter(candidate, now)
        if ok:
            self.seen[candidate.mint] = now
            emitted.append(candidate)
        elif reason.startswith(_WAITS):
            candidate.stats = {}
            self.nursery[candidate.mint] = candidate
        else:
            self._reject(candidate, reason, now)

    def _lookup_graduation(self, c: TokenCandidate, now: float) -> bool:
        """G12 fallback: GeckoTerminal's ``launchpad.completed_at`` for a graduate Jupiter sent no ``graduatedAt``
        for. True when ``c`` now carries a graduation time. Bounded per poll and per mint, paused with the rest of
        the crawler's GeckoTerminal calls after a 429, skipped when the source has no ``token`` lookup."""
        lookup = getattr(self.sources.gecko, "token", None)
        last = self._graduation_tried.get(c.mint)
        if (lookup is None or self._graduation_lookups_left <= 0 or now < self._gt_paused_until
                or (last is not None and now - last < GRADUATION_RETRY_S)):
            return False
        self._graduation_lookups_left -= 1
        self._graduation_tried[c.mint] = now
        limited: list[bool] = []
        found = self._fetch("gt_graduation", lambda: [lookup(c.mint)], limited)
        if limited:
            self._gt_paused_until = now + GT_FEED_PAUSE_S
            log.warning("crawler_gt_paused seconds=%.0f: GeckoTerminal rate limit on a graduation lookup",
                        GT_FEED_PAUSE_S)
        when = graduation_time(found[0]) if found else None
        if when is None:
            log.info("crawler_graduation_unknown mint=%s: waiting (never traded blind)", c.mint)
            return False
        c.raw = {**c.raw, "graduated_at": when, "graduated_at_source": "geckoterminal"}
        c.graduated = True
        self._graduation_tried.pop(c.mint, None)
        return True

    def _reject(self, candidate: TokenCandidate, reason: str, now: float) -> None:
        self.seen[candidate.mint] = now
        self.last_rejected.append((candidate, reason))

    # ------------------------------------------------------------------ feeds
    def _fetch_candidates(self, now: float) -> list[TokenCandidate]:
        """All feed items as candidates, in merge-precedence order (Jupiter recent, trending, GT last)."""
        jupiter = self.sources.jupiter
        out: list[TokenCandidate] = []
        out += self._convert(self._fetch("jupiter_recent", jupiter.tokens_recent),
                             lambda t: token_to_candidate(t, now, "jupiter_recent"))
        out += self._convert(self._fetch("jupiter_trending_1h", lambda: jupiter.top_trending(TRENDING_WINDOW)),
                             lambda t: token_to_candidate(t, now, "jupiter_trending_1h"))
        if self.settings.discover_gt_new_pools and now >= self._gt_paused_until:
            out += self._fetch_gt_new_pools(now)
        return [c for c in out if _is_tradable_mint(c.mint)]

    def _fetch_gt_new_pools(self, now: float) -> list[TokenCandidate]:
        """The optional, lowest-priority GeckoTerminal feed; a 429 pauses it (see module docstring)."""
        out: list[TokenCandidate] = []
        for page in GT_NEW_POOL_PAGES:
            limited: list[bool] = []
            items = self._fetch(f"gt_new_pools_p{page}", partial(self.sources.gecko.new_pools, page), limited)
            out += self._convert(items, lambda pool: pool_to_candidate(pool, now, "gt_new_pools"))
            if limited:
                self._gt_paused_until = now + GT_FEED_PAUSE_S
                log.warning("crawler_gt_feed_paused seconds=%.0f: GeckoTerminal rate limit; its budget is kept "
                            "for candles and the radar", GT_FEED_PAUSE_S)
                break
        return out

    def _fetch(self, feed: str, call: Callable[[], Iterable[Any] | None],
               rate_limited: list[bool] | None = None) -> list[Any]:
        """Run one feed call; on any failure log it, count it and return ``[]`` (an HTTP 429 is
        also flagged in ``rate_limited`` when given)."""
        try:
            return list(call() or [])
        except Exception as exc:  # one broken feed must never stop discovery
            self._feed_errors[feed] += 1
            log.warning("crawler_feed_failed feed=%s error=%s: %s", feed, type(exc).__name__, exc)
            if rate_limited is not None and isinstance(exc, HttpError) and exc.status == 429:
                rate_limited.append(True)
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

    def _eligible_at(self, c: TokenCandidate) -> float | None:
        """When ``c`` may first be traded: creation + ``MIN_AGE_MIN``, or graduation + ``MIN_AGE_SINCE_GRAD_MIN``
        when that is later (G12). None without a creation time (such an entry never matures)."""
        created = _created_at(c)
        if created is None:
            return None
        eligible = created + self.settings.min_age_min * 60
        graduated = graduated_at(c)
        if graduated is not None:
            eligible = max(eligible, graduated + self.settings.min_age_since_grad_min * 60)
        return eligible

    def _matured(self, now: float, skip: set[str]) -> list[TokenCandidate]:
        """Nursery entries whose eligible time has come, the longest waiting first, at most
        :data:`NURSERY_REFRESH_PER_POLL`."""
        ready: list[tuple[float, TokenCandidate]] = []
        for mint, candidate in self.nursery.items():
            eligible = self._eligible_at(candidate)
            if mint not in skip and eligible is not None and now >= eligible:
                ready.append((eligible, candidate))
        ready.sort(key=lambda pair: pair[0])
        return [candidate for _, candidate in ready[:NURSERY_REFRESH_PER_POLL]]

    def _prune_nursery(self, now: float) -> None:
        """Drop entries ``NURSERY_GRACE_MIN`` past their eligible time, then the oldest beyond :data:`NURSERY_MAX`."""
        grace_s = NURSERY_GRACE_MIN * 60
        stale = [m for m, c in self.nursery.items()
                 if (eligible := self._eligible_at(c)) is not None and now - eligible > grace_s]
        for mint in stale:
            del self.nursery[mint]
        overflow = len(self.nursery) - NURSERY_MAX
        if overflow > 0:
            oldest = sorted(self.nursery.values(), key=lambda c: _created_at(c) or 0.0)[:overflow]
            for candidate in oldest:
                del self.nursery[candidate.mint]
        if stale or overflow > 0:
            log.info("crawler_nursery_pruned stale=%d overflow=%d", len(stale), max(overflow, 0))

    def export_nursery(self) -> list[dict[str, Any]]:
        """The nursery as compact JSON-native dicts (unset fields omitted), newest first, at most
        :data:`NURSERY_MAX` - what the engine stores in the ledger kv across redeploys."""
        ordered = sorted(self.nursery.values(), key=_newest_first_key)[:NURSERY_MAX]
        return [{k: v for k, v in c.to_dict().items() if v not in (None, "", [], {}) and k != "stats"}
                for c in ordered]

    def restore_nursery(self, items: Any, now: float) -> int:
        """Load :meth:`export_nursery` output saved before a restart; returns how many were restored.

        Garbage, invalid or ignored mints, entries without a creation time (they could never
        mature), mints already known (nursery or seen) and entries more than ``NURSERY_GRACE_MIN``
        past their eligible time are skipped; the result is bounded like the live
        nursery (:data:`NURSERY_MAX`, oldest dropped).
        """
        grace_s = NURSERY_GRACE_MIN * 60
        added: list[str] = []
        for item in items if isinstance(items, (list, tuple)) else []:
            if not isinstance(item, dict):
                continue
            try:
                candidate = TokenCandidate.from_dict(item)
            except (TypeError, ValueError, KeyError, AttributeError):
                continue
            created = parse_ts(candidate.created_at)
            if created is None or not _is_tradable_mint(candidate.mint):
                continue
            candidate.created_at, candidate.stats = created, {}
            eligible = self._eligible_at(candidate)
            if (eligible is None or now - eligible > grace_s
                    or candidate.mint in self.nursery or candidate.mint in self.seen):
                continue
            self.nursery[candidate.mint] = candidate
            added.append(candidate.mint)
        self._prune_nursery(now)
        restored = sum(1 for m in added if m in self.nursery)
        log.info("crawler_nursery_restored entries=%d offered=%d", restored,
                 len(items) if isinstance(items, (list, tuple)) else 0)
        return restored

    # ------------------------------------------------------------------ prefilter
    def prefilter(self, c: TokenCandidate, now: float) -> tuple[bool, str]:
        """Cheap checks on data already in the candidate. Returns ``(ok, reason)``.

        Reject when (each a distinct reason string, e.g. ``"too young: 12.0 min"``):
        * ``audit.isSus`` is True;
        * Jupiter ``audit.mintAuthorityDisabled is False`` or
          ``audit.freezeAuthorityDisabled is False`` (explicitly not renounced);
        * Jupiter ``audit.devMints > COCOON_DEV_MINTS_MAX`` (serial launcher; the
          cocoon would hard-fail it anyway, so it is rejected for free here) -
          individual creators only: a launchpad's shared deployer
          (:func:`launchpad_deployer`) says nothing about the coin's creator;
        * outside the tested universe (:func:`universe_problem`, G01): another launchpad, none, or a
          known non-SOL launch quote;
        * age known and ``age_min < MIN_AGE_MIN`` or ``age_min > MAX_AGE_H*60``
          (age is measured at ``now`` from ``created_at`` when known);
        * graduation time known (:func:`graduated_at`) and less than ``MIN_AGE_SINCE_GRAD_MIN`` ago
          (``"too young: 12.0 min since graduation"``, G12);
        * mcap known and outside ``[MIN_MCAP_USD, MAX_MCAP_USD]``;
        * liquidity known and ``< MIN_LIQUIDITY_USD`` (unknown liquidity, e.g.
          bonding curve, passes here - Cocoon/Quote impact decide later);
        * ``organic_score`` known and ``< MIN_ORGANIC_SCORE`` (when that setting > 0);
        * graduation time unknown: :data:`NOT_GRADUATED` while the coin is still on its bonding curve
          (``graduated is False``), else :data:`GRADUATION_UNKNOWN` (the caller may ask GeckoTerminal).
        Unknown MARKET values never reject; an unknown universe never passes (fail closed). ``reason`` is
        ``"ok"`` when passing. The permanent checks (audit, universe) run before the age checks, so a
        "too young" verdict means the token is worth re-checking later; "too young", :data:`NOT_GRADUATED` and
        :data:`GRADUATION_UNKNOWN` are waits (:meth:`poll` keeps such candidates in the nursery).
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
        if dev_mints is not None and dev_mints > s.cocoon_dev_mints_max and launchpad_deployer(c) is None:
            return False, f"serial launcher: dev minted {dev_mints:.0f} tokens"
        outside = universe_problem(c)
        if outside is not None:
            return False, outside
        age_min = _age_min(c, now)
        if age_min is not None:
            if age_min < s.min_age_min:
                return False, f"{TOO_YOUNG}: {age_min:.1f} min"
            if age_min > s.max_age_h * 60:
                return False, f"too old: {age_min / 60:.1f} h"
        graduated = graduated_at(c)
        if graduated is not None and (now - graduated) / 60 < s.min_age_since_grad_min:
            return False, f"{TOO_YOUNG}: {(now - graduated) / 60:.1f} min since graduation"
        if c.mcap_usd is not None:
            if c.mcap_usd < s.min_mcap_usd:
                return False, f"mcap too low: ${c.mcap_usd:,.0f}"
            if c.mcap_usd > s.max_mcap_usd:
                return False, f"mcap too high: ${c.mcap_usd:,.0f}"
        if c.liquidity_usd is not None and c.liquidity_usd < s.min_liquidity_usd:
            return False, f"liquidity too low: ${c.liquidity_usd:,.0f}"
        if s.min_organic_score > 0 and c.organic_score is not None and c.organic_score < s.min_organic_score:
            return False, f"organic score too low: {c.organic_score:.1f}"
        if graduated is None:
            return False, (f"{NOT_GRADUATED}: still on the bonding curve" if c.graduated is False
                           else GRADUATION_UNKNOWN)
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
        self._graduation_tried = {m: ts for m, ts in self._graduation_tried.items() if now - ts < GRADUATION_RETRY_S}
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


def launchpad_deployer(c: TokenCandidate) -> str | None:
    """Label of the launchpad / launch service whose SHARED deployer launched ``c``, or None when
    ``c.dev`` is (as far as we can tell) an individual creator.

    Platform deployers: an address in :data:`KNOWN_LAUNCHPAD_DEPLOYERS`, or - for a coin whose
    ``launchpad`` field is set - a deployer that minted at least :data:`FACTORY_DEV_MINTS_MIN`
    tokens. A candidate already classified (``raw["deployer"]``) keeps its label.
    """
    known = c.raw.get("deployer") if isinstance(c.raw, dict) else None
    if isinstance(known, dict) and known.get("label"):
        return str(known["label"])
    if c.dev and c.dev in KNOWN_LAUNCHPAD_DEPLOYERS:
        return KNOWN_LAUNCHPAD_DEPLOYERS[c.dev]
    mints = to_float((c.audit or {}).get("devMints"))
    if c.launchpad and mints is not None and mints >= FACTORY_DEV_MINTS_MIN:
        return f"{c.launchpad} platform deployer"
    return None


def universe_problem(c: TokenCandidate) -> str | None:
    """Why ``c`` is outside the universe every test covered (G01 + N3), or None.

    The universe is pump.fun graduates quoted in SOL, not Mayhem: another launchpad (``"untested launchpad:
    bags.fun"``) or none at all (``"not a pump.fun launch: ..."``: Jupiter names no launchpad, or only a
    GeckoTerminal pool reported the coin) is outside it, and so is a known non-SOL launch quote
    (``raw["quote_mint"]``, stated by a pump.fun curve pool). Mayhem coins are refused by the cocoon, which
    reads the mint's on-chain supply. The engine runs the same check before every entry.
    """
    raw = c.raw if isinstance(c.raw, dict) else {}
    quote = raw.get("quote_mint")
    if quote and quote not in SOL_QUOTE_MINTS:
        return f"not SOL-quoted: quote mint {str(quote)[:44]}"
    launchpad = str(c.launchpad or "").strip()
    if not launchpad:
        return "not a pump.fun launch: no launchpad reported"
    if launchpad.lower() not in TESTED_LAUNCHPADS:
        return f"untested launchpad: {launchpad[:40]}"
    return None


def graduated_at(c: TokenCandidate) -> float | None:
    """When ``c`` left its bonding curve (epoch s): ``raw["graduated_at"]``, from Jupiter's ``graduatedAt`` or the
    GeckoTerminal fallback (``raw["graduated_at_source"] == "geckoterminal"``); None when unknown (G12)."""
    raw = c.raw if isinstance(c.raw, dict) else {}
    return parse_ts(raw.get("graduated_at"))


def _file_platform_mints(c: TokenCandidate) -> None:
    """For a launchpad-deployed candidate, move the PLATFORM's mint count out of ``audit.devMints``
    (into ``audit.deployerMints``) and name the platform in ``raw["deployer"]`` - so no serial
    launcher rule (prefilter or cocoon) reads a platform's history as the creator's."""
    label = launchpad_deployer(c)
    if label is None:
        return
    audit = dict(c.audit or {})
    if "devMints" in audit:
        audit["deployerMints"] = audit.pop("devMints")
    c.audit = audit
    c.raw = {**c.raw, "deployer": {"address": c.dev, "label": label}}


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
