"""Crawler: feed merging, prefilter rules, seen-TTL dedupe, nursery, refresh (offline).

O1's converters (``token_to_candidate`` / ``pool_to_candidate``) are replaced
by contract doubles written from their docstrings, so these tests do not
depend on O1's progress. ``test_poll_with_real_o1_clients`` exercises the
real clients over FakeHttp fixtures and is skipped until O1 lands.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import Any

import pytest

from fakes import FakeClock
from nightcrawler import crawler as crawler_mod
from nightcrawler.base58 import b58encode
from nightcrawler.crawler import Crawler
from nightcrawler.http import HttpError
from nightcrawler.models import SOL_MINT, MarketSnapshot, TokenCandidate
from nightcrawler.sources import Sources, build_sources
from nightcrawler.sources._parse import get_path, parse_ts, to_float, to_int

NOW = 1_791_475_200.0  # conftest.FIXED_NOW (2026-10-08T16:00:00Z)
MIN = 60.0
HOUR = 3600.0


def mint(i: int) -> str:
    """Deterministic valid base58 pubkey."""
    return b58encode(bytes([i]) * 32)


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- contract doubles for O1


def jup_token_to_candidate(token: dict[str, Any], now: float, source: str) -> TokenCandidate:
    """Double of ``sources.jupiter.token_to_candidate`` written from its docstring."""
    created = parse_ts(get_path(token, "firstPool.createdAt")) or parse_ts(token.get("createdAt"))
    return TokenCandidate(
        mint=token["id"],
        symbol=token.get("symbol") or "",
        name=token.get("name") or "",
        pool=token.get("graduatedPool") or get_path(token, "firstPool.id"),
        sources=[source],
        created_at=created,
        age_min=(now - created) / 60 if created else None,
        mcap_usd=to_float(token.get("mcap")),
        fdv_usd=to_float(token.get("fdv")),
        liquidity_usd=to_float(token.get("liquidity")),
        price_usd=to_float(token.get("usdPrice")),
        holder_count=to_int(token.get("holderCount")),
        dev=token.get("dev"),
        launchpad=token.get("launchpad"),
        graduated=True if token.get("graduatedPool") else (False if token.get("launchpad") else None),
        organic_score=to_float(token.get("organicScore")),
        audit=dict(token.get("audit") or {}),
        stats={w: token[f"stats{w}"] for w in ("5m", "1h", "6h", "24h") if token.get(f"stats{w}")},
        socials={k: token[k] for k in ("twitter", "website", "telegram") if token.get(k)},
        raw={"jupiter_id": token["id"]},
        discovered_at=now,
    )


def gt_pool_to_candidate(pool: dict[str, Any], now: float, source: str = "gt_new_pools") -> TokenCandidate | None:
    """Double of ``sources.geckoterminal.pool_to_candidate`` written from its docstring."""
    base = pool.get("base_mint")
    if not base or base == SOL_MINT:
        return None
    created = pool.get("created_at")
    gt_dex = pool.get("dex") or ""
    dex = {"pump-fun": "pumpfun", "meteora-dbc": "meteoradbc"}.get(gt_dex, gt_dex.replace("-", ""))
    return TokenCandidate(
        mint=base, symbol=pool.get("base_symbol") or "", pool=pool["pool"], dex=dex or None, sources=[source],
        created_at=created, age_min=(now - created) / 60 if created else None,
        mcap_usd=pool.get("mcap_usd") or pool.get("fdv_usd"), liquidity_usd=pool.get("reserve_usd"),
        price_usd=pool.get("price_usd"), graduated=False if dex in ("pumpfun", "meteoradbc") else None,
        raw={"gt_pool": pool["pool"]}, discovered_at=now,
    )


@pytest.fixture(autouse=True)
def contract_converters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crawler_mod, "token_to_candidate", jup_token_to_candidate)
    monkeypatch.setattr(crawler_mod, "pool_to_candidate", gt_pool_to_candidate)


# --------------------------------------------------------------------------- fake feeds


def jup_token(m: str, *, age_min: float = 90.0, now: float = NOW, mcap: float | None = 500_000.0,
              liquidity: float | None = 60_000.0, audit: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    token = {
        "id": m, "symbol": "TKN", "name": "Token",
        "firstPool": {"id": f"pool-{m[:6]}", "createdAt": iso(now - age_min * MIN)},
        "mcap": mcap, "liquidity": liquidity, "usdPrice": 0.0005, "holderCount": 800, "launchpad": "pump.fun",
        "audit": {"mintAuthorityDisabled": True, "freezeAuthorityDisabled": True, "devMints": 1, **(audit or {})},
        "twitter": "https://x.com/tkn", "stats1h": {"numBuys": 120, "numSells": 80},
    }
    token.update(extra)
    return token


def gt_pool(m: str, *, age_min: float = 90.0, now: float = NOW, fdv: float | None = 400_000.0,
            reserve: float | None = 50_000.0, dex: str = "pumpswap") -> dict[str, Any]:
    return {"pool": f"gtpool-{m[:6]}", "base_mint": m, "quote_mint": SOL_MINT, "base_symbol": "GT", "dex": dex,
            "created_at": now - age_min * MIN, "price_usd": 0.0004, "fdv_usd": fdv, "mcap_usd": None,
            "reserve_usd": reserve}


def snapshot(m: str, *, mcap: float | None = 300_000.0, liquidity: float | None = 45_000.0,
             pool: str | None = None, dex: str | None = "pumpswap") -> MarketSnapshot:
    return MarketSnapshot(mint=m, ts=NOW, price_usd=0.0003, mcap_usd=mcap, liquidity_usd=liquidity,
                          pool=pool or f"dexpool-{m[:6]}", dex=dex, fdv_usd=mcap)


def boom(name: str) -> HttpError:
    return HttpError("HTTP 503", url=f"https://example.invalid/{name}", status=503, retryable=True)


class FakeJupiter:
    def __init__(self) -> None:
        self.recent: list[dict[str, Any]] | Exception = []
        self.trending: list[dict[str, Any]] | Exception = []
        self.trending_windows: list[str] = []

    def tokens_recent(self) -> list[dict[str, Any]]:
        if isinstance(self.recent, Exception):
            raise self.recent
        return list(self.recent)

    def top_trending(self, window: str = "1h", limit: int = 50) -> list[dict[str, Any]]:
        self.trending_windows.append(window)
        if isinstance(self.trending, Exception):
            raise self.trending
        return list(self.trending)


class FakeGecko:
    def __init__(self) -> None:
        self.pages: dict[int, list[dict[str, Any]] | Exception] = {}
        self.pages_requested: list[int] = []

    def new_pools(self, page: int = 1) -> list[dict[str, Any]]:
        self.pages_requested.append(page)
        result = self.pages.get(page, [])
        if isinstance(result, Exception):
            raise result
        return list(result)


class FakeDexScreener:
    def __init__(self) -> None:
        self.boosts: list[dict[str, Any]] | Exception = []
        self.profiles: list[dict[str, Any]] | Exception = []
        self.known: dict[str, MarketSnapshot] = {}
        self.snapshot_error: Exception | None = None
        self.snapshot_calls: list[list[str]] = []

    def token_boosts_latest(self) -> list[dict[str, Any]]:
        if isinstance(self.boosts, Exception):
            raise self.boosts
        return list(self.boosts)

    def token_profiles_latest(self) -> list[dict[str, Any]]:
        if isinstance(self.profiles, Exception):
            raise self.profiles
        return list(self.profiles)

    def snapshots(self, mints: list[str], now: float) -> dict[str, MarketSnapshot]:
        self.snapshot_calls.append(list(mints))
        if self.snapshot_error is not None:
            raise self.snapshot_error
        return {m: dataclasses.replace(self.known[m], ts=now) for m in mints if m in self.known}


@dataclasses.dataclass
class World:
    jupiter: FakeJupiter
    gecko: FakeGecko
    dex: FakeDexScreener
    clock: FakeClock
    crawler: Crawler


def make_world(settings: Any, fake_clock: FakeClock) -> World:
    jupiter, gecko, dex = FakeJupiter(), FakeGecko(), FakeDexScreener()
    sources = Sources(dexscreener=dex, gecko=gecko, rugcheck=None, jupiter=jupiter, rpc=None)  # type: ignore[arg-type]
    return World(jupiter, gecko, dex, fake_clock, Crawler(sources, settings, fake_clock))


@pytest.fixture
def world(make_settings, fake_clock: FakeClock) -> World:
    """Every feed on, GeckoTerminal new_pools included (off by default; see the GT tests below)."""
    return make_world(make_settings(DISCOVER_GT_NEW_POOLS=True), fake_clock)


@pytest.fixture
def default_world(settings, fake_clock: FakeClock) -> World:
    """Default settings: discovery without GeckoTerminal."""
    return make_world(settings, fake_clock)


def mints_of(candidates: list[TokenCandidate]) -> list[str]:
    return [c.mint for c in candidates]


# --------------------------------------------------------------------------- prefilter


def base_candidate(**changes: Any) -> TokenCandidate:
    c = TokenCandidate(mint=mint(1), created_at=NOW - 90 * MIN, age_min=90.0, mcap_usd=500_000.0,
                       liquidity_usd=60_000.0, organic_score=40.0, discovered_at=NOW,
                       audit={"mintAuthorityDisabled": True, "freezeAuthorityDisabled": True, "devMints": 1})
    return dataclasses.replace(c, **changes)


PREFILTER_CASES = [
    ("passes", {}, {}, "ok"),
    ("unknowns_never_reject", dict(created_at=None, age_min=None, mcap_usd=None, liquidity_usd=None,
                                   organic_score=None, audit={}), {}, "ok"),
    ("is_sus", dict(audit={"isSus": True}), {}, "suspicious: Jupiter audit.isSus"),
    ("mint_authority", dict(audit={"mintAuthorityDisabled": False}), {}, "mint authority not renounced"),
    ("freeze_authority", dict(audit={"freezeAuthorityDisabled": False}), {}, "freeze authority set"),
    ("serial_launcher", dict(audit={"devMints": 21}), {}, "serial launcher: dev minted 21 tokens"),
    ("dev_mints_at_limit", dict(audit={"devMints": 20}), {}, "ok"),
    ("too_young", dict(created_at=NOW - 59 * MIN), {}, "too young: 59.0 min"),
    ("age_exactly_min", dict(created_at=NOW - 60 * MIN), {}, "ok"),
    ("too_old", dict(created_at=NOW - 48 * HOUR - MIN), {}, "too old: 48.0 h"),
    ("age_field_without_created_at", dict(created_at=None, age_min=30.0, discovered_at=NOW - 10 * MIN), {},
     "too young: 40.0 min"),
    ("age_field_only", dict(created_at=None, age_min=30.0, discovered_at=None), {}, "too young: 30.0 min"),
    ("mcap_low", dict(mcap_usd=99_999.0), {}, "mcap too low: $99,999"),
    ("mcap_at_min", dict(mcap_usd=100_000.0), {}, "ok"),
    ("mcap_high", dict(mcap_usd=5_000_001.0), {}, "mcap too high: $5,000,001"),
    ("liquidity_low", dict(liquidity_usd=29_999.0), {}, "liquidity too low: $29,999"),
    ("liquidity_unknown_curve", dict(liquidity_usd=None), {}, "ok"),
    ("organic_ignored_when_disabled", dict(organic_score=1.0), {}, "ok"),
    ("organic_low", dict(organic_score=10.0), {"MIN_ORGANIC_SCORE": 50}, "organic score too low: 10.0"),
    ("organic_unknown", dict(organic_score=None), {"MIN_ORGANIC_SCORE": 50}, "ok"),
    ("permanent_checks_before_age", dict(audit={"isSus": True}, created_at=NOW - 5 * MIN), {},
     "suspicious: Jupiter audit.isSus"),
    ("age_before_market_checks", dict(created_at=NOW - 5 * MIN, mcap_usd=1_000.0), {}, "too young: 5.0 min"),
]


@pytest.mark.parametrize("changes,env,expected", [c[1:] for c in PREFILTER_CASES], ids=[c[0] for c in PREFILTER_CASES])
def test_prefilter_rules(make_settings, fake_clock, changes, env, expected) -> None:
    crawler = Crawler(Sources(None, None, None, None, None), make_settings(**env), fake_clock)  # type: ignore[arg-type]
    ok, reason = crawler.prefilter(base_candidate(**changes), NOW)
    assert reason == expected
    assert ok is (expected == "ok")


# --------------------------------------------------------------------------- merge


def test_merge_precedence_union_and_order() -> None:
    a, b = mint(1), mint(2)
    recent = TokenCandidate(mint=a, symbol="", mcap_usd=1.0, sources=["jupiter_recent"], audit={"k": 1},
                            socials={"twitter": "t1"}, discovered_at=NOW)
    other = TokenCandidate(mint=b, sources=["gt_new_pools"])
    trending = TokenCandidate(mint=a, symbol="AAA", mcap_usd=2.0, liquidity_usd=5.0, sources=["jupiter_trending_1h"],
                              audit={"k": 2, "j": 2}, graduated=False)
    gt = TokenCandidate(mint=a, pool="gtpool", sources=["gt_new_pools", "jupiter_recent"], paid_promo=True,
                        raw={"gt_pool": "gtpool"})
    merged = Crawler.merge([recent, other, trending, gt])
    assert mints_of(merged) == [a, b]
    m = merged[0]
    assert (m.symbol, m.mcap_usd, m.liquidity_usd, m.pool, m.graduated) == ("AAA", 1.0, 5.0, "gtpool", False)
    assert m.sources == ["jupiter_recent", "jupiter_trending_1h", "gt_new_pools"]
    assert m.audit == {"k": 1, "j": 2} and m.socials == {"twitter": "t1"} and m.raw == {"gt_pool": "gtpool"}
    assert m.paid_promo is True
    # inputs untouched, outputs are new objects
    assert recent.sources == ["jupiter_recent"] and recent.audit == {"k": 1} and m is not recent


def test_merge_takes_earliest_created_at_and_recomputes_age() -> None:
    a = mint(1)
    graduation_pool = TokenCandidate(mint=a, created_at=NOW - 5 * MIN, age_min=5.0, discovered_at=NOW)
    first_pool = TokenCandidate(mint=a, created_at=NOW - 70 * MIN, age_min=70.0, discovered_at=NOW)
    m = Crawler.merge([graduation_pool, first_pool])[0]
    assert m.created_at == NOW - 70 * MIN and m.age_min == pytest.approx(70.0)


# --------------------------------------------------------------------------- poll


def test_poll_merges_feeds_and_emits_newest_first(world: World) -> None:
    a, b, c, d = mint(1), mint(2), mint(3), mint(4)
    world.jupiter.recent = [jup_token(a, age_min=90), jup_token(b, age_min=120, mcap=300_000)]
    world.jupiter.trending = [jup_token(b, age_min=120, mcap=999_999), jup_token(c, age_min=600)]
    world.gecko.pages = {1: [gt_pool(d, age_min=70)], 2: [gt_pool(a, age_min=90)]}

    out = world.crawler.poll()

    assert mints_of(out) == [d, a, b, c]
    by_mint = {x.mint: x for x in out}
    assert by_mint[b].sources == ["jupiter_recent", "jupiter_trending_1h"]
    assert by_mint[b].mcap_usd == 300_000  # Jupiter recent wins over trending
    assert by_mint[a].sources == ["jupiter_recent", "gt_new_pools"]
    assert by_mint[a].pool == f"pool-{a[:6]}"  # Jupiter wins over GeckoTerminal
    assert by_mint[d].dex == "pumpswap" and by_mint[d].sources == ["gt_new_pools"]
    assert world.gecko.pages_requested == [1, 2] and world.jupiter.trending_windows == ["1h"]
    assert set(world.crawler.seen) == {a, b, c, d} and world.crawler.last_rejected == []


def test_poll_dedupes_with_seen_ttl(world: World) -> None:
    a, bad = mint(1), mint(2)
    world.jupiter.recent = [jup_token(a), jup_token(bad, mcap=1_000)]
    assert mints_of(world.crawler.poll()) == [a]
    assert [(c.mint, r) for c, r in world.crawler.last_rejected] == [(bad, "mcap too low: $1,000")]

    world.clock.advance(10 * MIN)
    world.jupiter.recent = [jup_token(a, now=world.clock.now() - 10 * MIN), jup_token(bad, mcap=1_000)]
    assert world.crawler.poll() == []
    assert world.crawler.last_rejected == []  # each rejection is reported once

    world.clock.advance(crawler_mod.SEEN_TTL_S)  # both forgotten: re-evaluated once more
    assert mints_of(world.crawler.poll()) == [a]
    assert [c.mint for c, _ in world.crawler.last_rejected] == [bad]


def test_poll_rediscovers_after_ttl(world: World) -> None:
    a = mint(1)
    world.jupiter.trending = [jup_token(a, age_min=120)]
    assert mints_of(world.crawler.poll()) == [a]
    world.clock.advance(crawler_mod.SEEN_TTL_S + 1)
    world.jupiter.trending = [jup_token(a, age_min=120, now=world.clock.now())]
    assert mints_of(world.crawler.poll()) == [a]


def test_poll_drops_quote_assets_and_invalid_mints_silently(world: World) -> None:
    good = mint(9)
    world.jupiter.recent = [jup_token(SOL_MINT), jup_token(crawler_mod.USDC_MINT), jup_token(crawler_mod.USDT_MINT),
                            jup_token("not-a-mint"), jup_token(good)]
    world.dex.boosts = [{"mint": "0xethereum"}, {"mint": None}]
    out = world.crawler.poll()
    assert mints_of(out) == [good]
    assert world.crawler.last_rejected == [] and set(world.crawler.seen) == {good}


def test_poll_survives_a_failing_feed(world: World) -> None:
    a = mint(1)
    world.jupiter.recent = boom("recent")
    world.jupiter.trending = [jup_token(a)]
    world.gecko.pages = {1: boom("gt"), 2: []}
    world.dex.boosts = boom("boosts")
    assert mints_of(world.crawler.poll()) == [a]
    assert world.crawler.stats()["feed_errors"] == {"jupiter_recent": 1, "gt_new_pools_p1": 1,
                                                    "dexscreener_boost": 1}


def test_poll_with_every_feed_down_returns_empty(world: World) -> None:
    world.jupiter.recent = world.jupiter.trending = boom("jup")
    world.gecko.pages = {1: boom("gt1"), 2: boom("gt2")}
    world.dex.boosts = world.dex.profiles = boom("dex")
    assert world.crawler.poll() == []
    assert sum(world.crawler.stats()["feed_errors"].values()) == 6


def test_poll_skips_items_the_converter_cannot_parse(world: World) -> None:
    a = mint(1)
    broken = jup_token(mint(2))
    del broken["id"]  # the converter raises KeyError for this one item
    world.jupiter.recent = [broken, jup_token(a)]
    assert mints_of(world.crawler.poll()) == [a]
    assert world.crawler.stats()["feed_errors"] == {}


def test_dexscreener_promotions_flag_candidates_but_never_create_them(world: World) -> None:
    a, b, c = mint(1), mint(2), mint(3)
    world.jupiter.recent = [jup_token(a), jup_token(b)]
    world.dex.boosts = [{"mint": a, "amount": 10.0}, {"mint": c, "amount": 50.0}]
    world.dex.profiles = [{"mint": a}, {"mint": b}]
    out = {x.mint: x for x in world.crawler.poll()}
    assert set(out) == {a, b}  # c is boosted but no feed found it
    assert out[a].paid_promo and out[a].sources == ["jupiter_recent", "dexscreener_boost", "dexscreener_profile"]
    assert out[b].paid_promo and out[b].sources == ["jupiter_recent", "dexscreener_profile"]


# --------------------------------------------------------------------------- nursery


def test_young_candidates_wait_in_the_nursery(world: World) -> None:
    a = mint(1)
    world.jupiter.recent = [jup_token(a, age_min=5, mcap=4_000, liquidity=3_000)]
    assert world.crawler.poll() == []
    assert world.crawler.last_rejected == [] and a not in world.crawler.seen
    assert world.crawler.nursery[a].stats == {}  # stale stats are dropped
    assert world.crawler.stats()["nursery"] == 1


def test_matured_nursery_entry_is_refreshed_and_emitted(world: World) -> None:
    a = mint(1)
    world.jupiter.recent = [jup_token(a, age_min=5, mcap=4_000, liquidity=3_000)]
    world.crawler.poll()
    world.jupiter.recent = []
    world.clock.advance(54 * MIN)  # 59 min old: not mature yet, no refresh call
    assert world.crawler.poll() == [] and world.dex.snapshot_calls == []

    world.clock.advance(1 * MIN)
    world.dex.known[a] = snapshot(a, mcap=350_000, liquidity=40_000, pool="graduated-pool", dex="pumpswap")
    out = world.crawler.poll()

    assert mints_of(out) == [a] and world.dex.snapshot_calls == [[a]]
    c = out[0]
    assert (c.mcap_usd, c.liquidity_usd, c.pool, c.dex, c.graduated) == (350_000, 40_000, "graduated-pool",
                                                                         "pumpswap", True)
    assert c.discovered_at == world.clock.now() and c.age_min == pytest.approx(60.0)
    assert c.raw["nursery_since"] == NOW and a in world.crawler.seen and not world.crawler.nursery


def test_matured_nursery_entry_failing_prefilter_is_rejected(world: World) -> None:
    a, b = mint(1), mint(2)
    world.jupiter.recent = [jup_token(a, age_min=5), jup_token(b, age_min=5)]
    world.crawler.poll()
    world.jupiter.recent = []
    world.clock.advance(56 * MIN)
    world.dex.known[a] = snapshot(a, mcap=6_000)
    assert world.crawler.poll() == []
    reasons = {c.mint: r for c, r in world.crawler.last_rejected}
    assert reasons == {a: "mcap too low: $6,000", b: crawler_mod.NO_MARKET_DATA}
    assert {a, b} <= set(world.crawler.seen) and not world.crawler.nursery


def test_nursery_refresh_failure_keeps_entries_for_the_next_poll(world: World) -> None:
    a = mint(1)
    world.jupiter.recent = [jup_token(a, age_min=5)]
    world.crawler.poll()
    world.jupiter.recent = []
    world.clock.advance(60 * MIN)
    world.dex.known[a] = snapshot(a)
    world.dex.snapshot_error = boom("tokens")
    assert world.crawler.poll() == [] and a in world.crawler.nursery
    assert world.crawler.stats()["feed_errors"] == {"dexscreener_refresh": 1}
    world.dex.snapshot_error = None
    world.clock.advance(30)
    assert mints_of(world.crawler.poll()) == [a]


def test_nursery_entries_expire_after_the_grace_period(world: World) -> None:
    a = mint(1)
    world.jupiter.recent = [jup_token(a, age_min=5)]
    world.crawler.poll()
    world.jupiter.recent = []
    world.dex.snapshot_error = boom("tokens")
    world.clock.advance((60 + crawler_mod.NURSERY_GRACE_MIN - 5) * MIN)  # exactly MIN_AGE + GRACE old
    world.crawler.poll()
    assert a in world.crawler.nursery
    world.clock.advance(1)
    world.crawler.poll()
    assert a not in world.crawler.nursery and a not in world.crawler.seen


def test_nursery_overflow_drops_the_oldest(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crawler_mod, "NURSERY_MAX", 2)
    a, b, c = mint(1), mint(2), mint(3)
    world.jupiter.recent = [jup_token(a, age_min=20), jup_token(b, age_min=10), jup_token(c, age_min=15)]
    world.crawler.poll()
    assert set(world.crawler.nursery) == {b, c}


def test_nursery_refresh_is_one_bounded_batch_oldest_first(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crawler_mod, "NURSERY_REFRESH_PER_POLL", 2)
    a, b, c = mint(1), mint(2), mint(3)
    world.jupiter.recent = [jup_token(a, age_min=8), jup_token(b, age_min=10), jup_token(c, age_min=9)]
    world.crawler.poll()
    world.jupiter.recent = []
    world.dex.known = {m: snapshot(m) for m in (a, b, c)}
    world.clock.advance(55 * MIN)
    assert mints_of(world.crawler.poll()) == [c, b]  # emitted newest first
    assert world.dex.snapshot_calls == [[b, c]] and set(world.crawler.nursery) == {a}
    world.clock.advance(30)
    assert mints_of(world.crawler.poll()) == [a]


def test_nursery_entry_seen_again_with_fresh_data_is_evaluated_directly(world: World) -> None:
    a = mint(1)
    world.jupiter.recent = [jup_token(a, age_min=5, mcap=4_000)]
    world.crawler.poll()
    world.clock.advance(61 * MIN)
    # trending now reports it; its firstPool time is the same token creation time
    world.jupiter.recent = []
    world.jupiter.trending = [jup_token(a, age_min=66, now=world.clock.now(), mcap=800_000)]
    out = world.crawler.poll()
    assert mints_of(out) == [a] and out[0].mcap_usd == 800_000
    assert out[0].sources == ["jupiter_trending_1h", "jupiter_recent"]
    assert world.dex.snapshot_calls == [] and not world.crawler.nursery


def test_promotion_seen_while_in_the_nursery_is_kept(world: World) -> None:
    a = mint(1)
    world.jupiter.recent = [jup_token(a, age_min=5)]
    world.dex.boosts = [{"mint": a}]
    world.crawler.poll()
    world.jupiter.recent, world.dex.boosts = [], []
    world.dex.known[a] = snapshot(a)
    world.clock.advance(60 * MIN)
    (c,) = world.crawler.poll()
    assert c.paid_promo and "dexscreener_boost" in c.sources


# --------------------------------------------------------------------------- refresh / memory / stats


def test_refresh_batches_dedupes_and_survives_failure(world: World) -> None:
    a, b = mint(1), mint(2)
    world.dex.known = {a: snapshot(a)}
    snaps = world.crawler.refresh([a, b, a, ""])
    assert list(snaps) == [a] and snaps[a].ts == world.clock.now()
    assert world.dex.snapshot_calls == [[a, b]]
    assert world.crawler.refresh([]) == {} and len(world.dex.snapshot_calls) == 1
    world.dex.snapshot_error = boom("tokens")
    assert world.crawler.refresh([a]) == {}
    assert world.crawler.stats()["feed_errors"] == {"dexscreener_refresh": 1}


def test_forget_allows_reemission(world: World) -> None:
    a = mint(1)
    world.jupiter.trending = [jup_token(a)]
    assert mints_of(world.crawler.poll()) == [a]
    assert world.crawler.poll() == []
    world.crawler.forget(a)
    world.crawler.forget("unknown-mint")  # no-op
    assert mints_of(world.crawler.poll()) == [a]


def test_expire_seen_counts_dropped_entries(world: World) -> None:
    world.crawler.seen = {mint(1): NOW - crawler_mod.SEEN_TTL_S - 1, mint(2): NOW - 10, mint(3): NOW - 7 * HOUR}
    assert world.crawler.expire_seen(NOW) == 2
    assert list(world.crawler.seen) == [mint(2)]


def test_stats_counts_polls_emissions_and_rejections(world: World) -> None:
    world.jupiter.recent = [jup_token(mint(1)), jup_token(mint(2), mcap=10), jup_token(mint(3), age_min=1)]
    world.crawler.poll()
    world.crawler.poll()
    assert world.crawler.stats() == {"polls": 2, "seen": 2, "emitted": 1, "rejected": 1, "nursery": 1,
                                     "feed_errors": {}}


# --------------------------------------------------------------------------- GeckoTerminal is optional (RT-13)


def test_geckoterminal_new_pools_are_off_by_default(default_world: World) -> None:
    a, d = mint(1), mint(4)
    default_world.jupiter.recent = [jup_token(a)]
    default_world.gecko.pages = {1: [gt_pool(d, age_min=70)]}
    assert mints_of(default_world.crawler.poll()) == [a]
    assert default_world.gecko.pages_requested == []  # GT budget kept for candles and the radar


def test_a_geckoterminal_429_pauses_the_optional_feed(world: World) -> None:
    a, d = mint(1), mint(4)
    world.jupiter.recent = [jup_token(a)]
    world.gecko.pages = {1: HttpError("HTTP 429", url="https://api.geckoterminal.com/x", status=429,
                                      retryable=True), 2: [gt_pool(d)]}
    assert mints_of(world.crawler.poll()) == [a]
    assert world.gecko.pages_requested == [1]  # page 2 is not even tried after a rate limit
    world.gecko.pages = {1: [gt_pool(d)]}
    world.clock.advance(crawler_mod.GT_FEED_PAUSE_S - 1)
    world.crawler.poll()
    assert world.gecko.pages_requested == [1]  # still paused
    world.clock.advance(1)
    assert mints_of(world.crawler.poll()) == [d]
    assert world.gecko.pages_requested == [1, 1, 2]


# --------------------------------------------------------------------------- launchpad deployers (RT-11)

BAGS_DEPLOYER = "BAGSB9TpGrZxQbEsrEznv5jXXdwyP6AXerN8aVRiAmcv"
LAUNCH_SERVICE = "bwamJzztZsepfkteWRChggmXuiiCQvpLqPietdNfSXa"
PERSON = mint(77)

DEPLOYER_CASES = [
    # (id, dev, launchpad, devMints, expected prefilter reason)
    ("person_serial_on_pumpfun", PERSON, "pump.fun", 21, "serial launcher: dev minted 21 tokens"),
    ("person_bot_on_pumpfun", PERSON, "pump.fun", 7_306, "serial launcher: dev minted 7306 tokens"),
    ("person_at_the_limit", PERSON, "pump.fun", 20, "ok"),
    ("person_without_launchpad", PERSON, None, 21, "serial launcher: dev minted 21 tokens"),
    ("known_bags_deployer", BAGS_DEPLOYER, "bags.fun", 190_960, "ok"),
    ("known_launch_service_on_pumpfun", LAUNCH_SERVICE, "pump.fun", 169_827, "ok"),
    ("known_deployer_without_launchpad_field", LAUNCH_SERVICE, None, 169_827, "ok"),
    ("platform_scale_deployer_with_launchpad", PERSON, "stonkfun", crawler_mod.FACTORY_DEV_MINTS_MIN, "ok"),
    ("just_below_platform_scale", PERSON, "stonkfun", crawler_mod.FACTORY_DEV_MINTS_MIN - 1,
     f"serial launcher: dev minted {crawler_mod.FACTORY_DEV_MINTS_MIN - 1} tokens"),
    ("platform_scale_without_launchpad", PERSON, None, crawler_mod.FACTORY_DEV_MINTS_MIN,
     f"serial launcher: dev minted {crawler_mod.FACTORY_DEV_MINTS_MIN} tokens"),
]


@pytest.mark.parametrize("dev,launchpad,dev_mints,expected", [c[1:] for c in DEPLOYER_CASES],
                         ids=[c[0] for c in DEPLOYER_CASES])
def test_launchpad_deployers_are_not_serial_launchers(make_settings, fake_clock, dev, launchpad, dev_mints,
                                                      expected) -> None:
    crawler = Crawler(Sources(None, None, None, None, None), make_settings(), fake_clock)  # type: ignore[arg-type]
    c = base_candidate(dev=dev, launchpad=launchpad,
                       audit={"mintAuthorityDisabled": True, "freezeAuthorityDisabled": True, "devMints": dev_mints})
    assert crawler.prefilter(c, NOW) == (expected == "ok", expected)
    assert (crawler_mod.launchpad_deployer(c) is not None) is (expected == "ok" and dev_mints > 20)


def test_a_launchpad_deployed_candidate_reaches_the_cocoon_without_the_platform_mint_count(world: World) -> None:
    """The cocoon's serial-launcher rule reads ``audit.devMints``: for a shared deployer that number
    counts the whole platform, so the crawler files it under ``deployerMints`` instead."""
    a, b = mint(1), mint(2)
    world.jupiter.trending = [jup_token(a, dev=BAGS_DEPLOYER, launchpad="bags.fun", audit={"devMints": 190_960}),
                              jup_token(b, dev=PERSON, audit={"devMints": 7})]
    out = {c.mint: c for c in world.crawler.poll()}
    assert set(out) == {a, b}
    assert "devMints" not in out[a].audit and out[a].audit["deployerMints"] == 190_960
    assert out[a].raw["deployer"] == {"address": BAGS_DEPLOYER, "label": "bags.fun"}
    assert out[a].dev == BAGS_DEPLOYER  # what Jupiter reported stays visible
    assert out[b].audit["devMints"] == 7 and "deployer" not in out[b].raw  # a person's history still counts


# --------------------------------------------------------------------------- nursery persistence (RT-14)


def test_nursery_export_and_restore_resume_the_young_candidates(world: World, make_settings) -> None:
    a, b = mint(1), mint(2)
    world.jupiter.recent = [jup_token(a, age_min=5), jup_token(b, age_min=30)]
    world.dex.boosts = [{"mint": a}]
    world.crawler.poll()
    saved = world.crawler.export_nursery()
    assert {item["mint"] for item in saved} == {a, b}
    assert all("stats" not in item for item in saved)

    restarted = make_world(make_settings(DISCOVER_GT_NEW_POOLS=True), world.clock)  # a redeploy
    assert restarted.crawler.restore_nursery(saved, world.clock.now()) == 2
    assert set(restarted.crawler.nursery) == {a, b}
    assert restarted.crawler.nursery[a].paid_promo and restarted.crawler.nursery[a].created_at == NOW - 5 * MIN

    restarted.dex.known = {a: snapshot(a), b: snapshot(b)}
    world.clock.advance(55 * MIN)  # both mature now: emitted from the restored nursery
    assert mints_of(restarted.crawler.poll()) == [a, b]


def test_nursery_restore_expires_old_entries_and_skips_garbage(world: World) -> None:
    a, b = mint(1), mint(2)
    saved = [{"mint": a, "created_at": NOW - 5 * MIN},
             {"mint": b, "created_at": NOW - (60 + crawler_mod.NURSERY_GRACE_MIN - 1) * MIN},
             {"mint": "not-a-mint", "created_at": NOW}, {"symbol": "no mint"}, "junk",
             {"mint": mint(3)},  # no creation time: it could never mature
             {"mint": mint(4), "created_at": "yesterday"}]
    world.clock.advance(2 * MIN)  # the bot was down for 2 min: b is past MIN_AGE + GRACE now
    assert world.crawler.restore_nursery(saved, world.clock.now()) == 1
    assert set(world.crawler.nursery) == {a}


def test_nursery_restore_is_bounded(world: World, make_settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crawler_mod, "NURSERY_MAX", 2)
    saved = [{"mint": mint(i), "created_at": NOW - (10 + i) * MIN} for i in range(1, 6)]
    assert world.crawler.restore_nursery(saved, NOW) == 2
    assert set(world.crawler.nursery) == {mint(1), mint(2)}  # the newest, like the in-memory overflow rule


# --------------------------------------------------------------------------- with O1's real clients


def test_poll_with_real_o1_clients(monkeypatch, fake_http, http_client, make_settings, fake_clock,
                                  load_fixture) -> None:
    """End-to-end over FakeHttp fixtures with O1's real clients/converters (skipped until O1 lands)."""
    from nightcrawler.sources.geckoterminal import pool_to_candidate
    from nightcrawler.sources.jupiter import token_to_candidate

    settings = make_settings(DISCOVER_GT_NEW_POOLS=True)

    monkeypatch.setattr(crawler_mod, "token_to_candidate", token_to_candidate)
    monkeypatch.setattr(crawler_mod, "pool_to_candidate", pool_to_candidate)
    fake_http.register_fixture("/tokens/v2/recent", "jup_tokens_v2_recent")
    fake_http.register_fixture("/tokens/v2/toptrending/1h", "jup_tokens_v2_toptrending")
    fake_http.register_fixture("/networks/solana/new_pools", "gt_new_pools")
    fake_http.register_fixture("/token-boosts/latest/v1", "dexs_boosts_latest")
    fake_http.register_fixture("/token-profiles/latest/v1", "dexs_token_profiles_latest")
    fake_http.register_fixture("/tokens/v1/solana/", "dexs_tokens_batch")
    sources = build_sources(settings, http_client)
    try:
        sources.jupiter.tokens_recent()
        sources.jupiter.top_trending("1h")
        token_to_candidate(load_fixture("jup_tokens_v2_recent")[0], NOW, "probe")
        for pool in sources.gecko.new_pools(1):
            pool_to_candidate(pool, NOW)
        sources.dexscreener.token_boosts_latest()
        sources.dexscreener.token_profiles_latest()
    except NotImplementedError:
        pytest.skip("O1 source clients not implemented yet")

    crawler = Crawler(sources, settings, fake_clock)
    assert crawler.poll() == []
    assert crawler.stats()["feed_errors"] == {}
    reasons = {c.mint: r for c, r in crawler.last_rejected}
    assert reasons["8RScxJmdMU58Kt1WiYM6jx7wvZXtXwfqY8ZZceAcCKJL"].startswith("suspicious")
    assert reasons["G5pUPqCZBzYVpSCwSE1b1JvhTjdGAMepJUhmDMpPn2ES"].startswith("serial launcher")
    assert reasons["pumpCmXqMfrsAkQ5r49WcJnRayYRqmXz6ae8H7H9Dfn"].startswith("too old")
    gt_bases = {"5wjVDmEnfayycCSihhx1hU2qG3mRSkSkxxqU5KRTMvdt", "E7VTCpUtES5uQX2FkWgLDn7TkqLutZeThFoxCYBHpqD4",
                "EkKg6JJyjsoQhYDyt6DC5mUvgq3kpWZYkyTD2hRXpump"}
    assert set(crawler.nursery) == gt_bases  # ~29 min old at 16:00Z

    fake_clock.advance(61 * MIN)  # same feeds again: the GT pools are mature now, their fresh data decides
    assert crawler.poll() == []
    assert {m for m in gt_bases if reasons.get(m) is None} == gt_bases
    assert {c.mint for c, r in crawler.last_rejected if r.startswith("mcap too low")} == gt_bases
    assert not crawler.nursery


@pytest.mark.live
def test_live_poll_smoke(settings) -> None:
    """Opt-in (NIGHTCRAWLER_LIVE_TESTS=1): one real poll against all free feeds."""
    from nightcrawler.clock import RealClock
    from nightcrawler.http import HttpClient

    clock = RealClock()
    crawler = Crawler(build_sources(settings, HttpClient.from_settings(settings, clock=clock)), settings, clock)
    emitted = crawler.poll()
    stats = crawler.stats()
    assert sum(stats["feed_errors"].values()) < 6, stats  # at least one feed answered
    assert len(crawler.nursery) + len(emitted) + len(crawler.last_rejected) > 0
    assert all(c.mint not in crawler_mod.IGNORED_MINTS for c in emitted)
