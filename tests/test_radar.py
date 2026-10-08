"""Radar: attribution of big sells to creator / insiders / top holders, flags, caching, failures (offline)."""

from __future__ import annotations

import copy
import dataclasses
from typing import Any

import pytest

from fakes import FakeClock
from nightcrawler.http import HttpError
from nightcrawler.models import SafetyReport
from nightcrawler.radar import RADAR_CACHE_S, Radar
from nightcrawler.sources import Sources, build_sources

NOW = 1_791_475_200.0  # conftest.FIXED_NOW
GT_TRADES_NEWEST_TS = 1_791_473_530.0  # gt_trades.json newest block_timestamp, 2026-10-08T15:32:10Z
MINT = "8ZCmwpW3MtC5UpNcZf7U4HMvRNTo71syU11BDiAFpump"
POOL = "2uZuTQEjcXcR1ESwMdGTpqEwM5PCekEwrSNVRPc1EhS1"
CREATOR = "G7YaEzm4c1aMQcn1SQLUPHYnoUNE7bG4XwQ4nxyYydn"
INSIDER = "Insider11111111111111111111111111111111111111"
WHALE = "JGF53sgRBQZLNaqbqPeD3NQaRErRDSY2ibc72GD8wMc"
STRANGER = "AyHpWYkG4znPnXjtrDyR7qJ8ZeYL8S9Ef9StkePxKRKN"


def trade(wallet: str | None, usd: float | None, ago_s: float, kind: str = "sell", tx: str = "") -> dict[str, Any]:
    """A trade as ``GeckoTerminalClient.trades`` normalizes it."""
    return {"ts": NOW - ago_s, "tx_hash": tx or f"tx-{wallet}-{ago_s}",
            "wallet": wallet, "kind": kind, "volume_usd": usd, "price_usd": 0.0007, "token_amount": 1000.0,
            "block_number": 454585783}


DEFAULTS = dict(now=NOW, window_min=15.0, creator=CREATOR, top_holders={WHALE, INSIDER, CREATOR},
                insiders={INSIDER}, liquidity_usd=50_000.0, min_trade_usd=300.0, insider_sell_usd=500.0,
                big_sell_liq_pct=10.0, mint=MINT)


def evaluate(trades: list[dict[str, Any]], **changes: Any):
    return Radar.evaluate(trades, **{**DEFAULTS, **changes})


# --------------------------------------------------------------------------- pure evaluation

EVALUATE_CASES = [
    # id, trades, overrides, flagged, reasons, (big_sells, insider_sells, creator_sold)
    ("no_trades", [], {}, False, [], (0.0, 0.0, False)),
    ("creator_sells_once", [trade(CREATOR, 400.0, 60)], {}, True, ["creator sold $400"], (400.0, 400.0, True)),
    ("insider_plus_whale_reach_threshold", [trade(INSIDER, 300.0, 60), trade(WHALE, 300.0, 120)], {}, True,
     ["insiders sold $600"], (600.0, 600.0, False)),
    ("whale_below_insider_threshold", [trade(WHALE, 400.0, 60)], {}, False, [], (400.0, 400.0, False)),
    ("creator_and_insiders", [trade(CREATOR, 300.0, 30), trade(WHALE, 250.0 + 300.0, 40)], {}, True,
     ["creator sold $300", "insiders sold $850"], (850.0, 850.0, True)),
    ("strangers_dump_vs_liquidity", [trade(STRANGER, 3_000.0, 60), trade(STRANGER, 2_000.0, 90)], {}, True,
     ["big sells $5,000 = 10.0% of liquidity"], (5_000.0, 0.0, False)),
    ("strangers_below_liquidity_share", [trade(STRANGER, 4_999.0, 60)], {}, False, [], (4_999.0, 0.0, False)),
    ("liquidity_unknown_curve", [trade(STRANGER, 50_000.0, 60)], {"liquidity_usd": None}, False, [],
     (50_000.0, 0.0, False)),
    ("liquidity_zero", [trade(STRANGER, 50_000.0, 60)], {"liquidity_usd": 0.0}, False, [], (50_000.0, 0.0, False)),
    ("zero_thresholds_need_a_sell", [], {"insider_sell_usd": 0.0, "big_sell_liq_pct": 0.0}, False, [],
     (0.0, 0.0, False)),
    ("outside_window_ignored", [trade(CREATOR, 900.0, 15 * 60 + 1)], {}, False, [], (0.0, 0.0, False)),
    ("window_edge_included", [trade(CREATOR, 900.0, 15 * 60)], {}, True, ["creator sold $900", "insiders sold $900"],
     (900.0, 900.0, True)),
    ("buys_ignored", [trade(CREATOR, 9_000.0, 60, kind="buy")], {}, False, [], (0.0, 0.0, False)),
    ("small_sells_ignored", [trade(CREATOR, 299.99, 60)], {}, False, [], (0.0, 0.0, False)),
    ("malformed_trades_ignored", [trade(CREATOR, None, 60), {**trade(CREATOR, 900.0, 60), "ts": None},
                                  {**trade(CREATOR, 900.0, 60), "kind": None}], {}, False, [], (0.0, 0.0, False)),
    ("no_wallet_sets", [trade(CREATOR, 900.0, 60)], {"creator": None, "top_holders": set(), "insiders": set()}, False,
     [], (900.0, 0.0, False)),
]


@pytest.mark.parametrize("trades,overrides,flagged,reasons,amounts", [c[1:] for c in EVALUATE_CASES],
                         ids=[c[0] for c in EVALUATE_CASES])
def test_evaluate_rules(trades, overrides, flagged, reasons, amounts) -> None:
    sig = evaluate(trades, **overrides)
    assert sig.flagged is flagged
    assert sig.reasons == reasons
    assert (sig.big_sells_usd, sig.insider_sell_usd, sig.creator_sold) == pytest.approx(amounts)
    assert sig.error is None


def test_evaluate_attributes_each_sell_with_role_precedence() -> None:
    trades = [trade(STRANGER, 300.0, 10, tx="t0"), trade(CREATOR, 301.0, 20, tx="t1"),
              trade(INSIDER, 302.0, 30, tx="t2"), trade(WHALE, 303.0, 40, tx="t3"),
              trade(WHALE, 50_000.0, 50, kind="buy", tx="t4")]
    sig = evaluate(trades)
    # CREATOR is also in top_holders and INSIDER is also in top_holders: creator > insider > top_holder
    assert sig.top_holder_sells == [
        {"wallet": CREATOR, "usd": 301.0, "ts": NOW - 20, "tx_hash": "t1", "role": "creator"},
        {"wallet": INSIDER, "usd": 302.0, "ts": NOW - 30, "tx_hash": "t2", "role": "insider"},
        {"wallet": WHALE, "usd": 303.0, "ts": NOW - 40, "tx_hash": "t3", "role": "top_holder"},
    ]
    assert sig.trades_seen == 5  # every returned trade, any side
    assert sig.big_sells_usd == pytest.approx(1206.0) and sig.insider_sell_usd == pytest.approx(906.0)
    assert (sig.mint, sig.window_min, sig.checked_at, sig.liquidity_usd) == (MINT, 15.0, NOW, 50_000.0)


def test_insider_in_both_sets_is_reported_as_insider() -> None:
    sig = evaluate([trade(INSIDER, 600.0, 60)], creator=None)
    assert [s["role"] for s in sig.top_holder_sells] == ["insider"]
    assert sig.reasons == ["insiders sold $600"]


# --------------------------------------------------------------------------- scan


class FakeGecko:
    def __init__(self) -> None:
        self.trades_result: list[dict[str, Any]] = []
        self.error: BaseException | None = None
        self.calls: list[tuple[str, float | None]] = []

    def trades(self, pool: str, min_usd: float | None = None) -> list[dict[str, Any]]:
        self.calls.append((pool, min_usd))
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.trades_result)


@dataclasses.dataclass
class World:
    gecko: FakeGecko
    clock: FakeClock
    radar: Radar


@pytest.fixture
def world(settings, fake_clock: FakeClock) -> World:
    gecko = FakeGecko()
    sources = Sources(dexscreener=None, gecko=gecko, rugcheck=None, jupiter=None, rpc=None)  # type: ignore[arg-type]
    return World(gecko, fake_clock, Radar(sources, settings, fake_clock))


def safety(**changes: Any) -> SafetyReport:
    report = SafetyReport(mint=MINT, passed=True, creator=CREATOR, top_holders=[WHALE], insiders=[INSIDER])
    return dataclasses.replace(report, **changes)


def test_scan_queries_big_trades_and_uses_safety_wallets(world: World) -> None:
    world.gecko.trades_result = [trade(CREATOR, 700.0, 60), trade(STRANGER, 900.0, 30, kind="buy")]
    sig = world.radar.scan(MINT, POOL, safety(), liquidity_usd=80_000.0)
    assert world.gecko.calls == [(POOL, 300.0)]
    assert sig.flagged and sig.reasons == ["creator sold $700", "insiders sold $700"]
    assert sig.window_min == 15.0 and sig.trades_seen == 2 and sig.liquidity_usd == 80_000.0
    assert sig.checked_at == world.clock.now() and sig.error is None


def test_scan_without_safety_report_only_uses_liquidity_rule(world: World) -> None:
    world.gecko.trades_result = [trade(CREATOR, 900.0, 60)]
    quiet = world.radar.scan(MINT, POOL, None, liquidity_usd=100_000.0)
    assert not quiet.flagged and quiet.top_holder_sells == [] and quiet.insider_sell_usd == 0.0
    loud = world.radar.scan(MINT, POOL, None, liquidity_usd=5_000.0)
    assert loud.reasons == ["big sells $900 = 18.0% of liquidity"]


def test_scan_error_is_reported_not_flagged_and_not_cached(world: World) -> None:
    world.gecko.error = HttpError("HTTP 429", url="https://api.geckoterminal.com/api/v2/x", status=429, retryable=True)
    sig = world.radar.scan(MINT, POOL, safety(), liquidity_usd=1_000.0)
    assert sig.flagged is False and sig.error and sig.error.startswith("HttpError: HTTP 429")
    assert (sig.mint, sig.window_min, sig.liquidity_usd, sig.checked_at) == (MINT, 15.0, 1_000.0, world.clock.now())
    world.gecko.error = None
    assert world.radar.scan(MINT, POOL, safety()).error is None
    assert len(world.gecko.calls) == 2


def test_scan_caches_trades_per_pool_but_re_evaluates(world: World) -> None:
    world.gecko.trades_result = [trade(STRANGER, 2_000.0, 15 * 60 - 15)]
    first = world.radar.scan(MINT, POOL, safety(), liquidity_usd=50_000.0)
    assert not first.flagged
    world.clock.advance(10)
    # same cached trades, new liquidity: re-evaluated without another GT call
    second = world.radar.scan(MINT, POOL, safety(), liquidity_usd=10_000.0)
    assert second.reasons == ["big sells $2,000 = 20.0% of liquidity"] and len(world.gecko.calls) == 1
    world.clock.advance(10)  # the sell is now older than the 15-min window; the cache is still warm
    assert world.radar.scan(MINT, POOL, safety(), liquidity_usd=10_000.0).big_sells_usd == 0.0
    assert len(world.gecko.calls) == 1
    world.radar.scan(MINT, "OtherPool", safety())
    assert len(world.gecko.calls) == 2
    world.clock.advance(RADAR_CACHE_S)
    world.radar.scan(MINT, POOL, safety())
    assert len(world.gecko.calls) == 3


def test_scan_respects_settings(make_settings, fake_clock) -> None:
    gecko = FakeGecko()
    gecko.trades_result = [trade(WHALE, 150.0, 25 * 60)]
    settings = make_settings(RADAR_MIN_TRADE_USD=100, RADAR_WINDOW_MIN=30, RADAR_INSIDER_SELL_USD=150)
    radar = Radar(Sources(None, gecko, None, None, None), settings, fake_clock)  # type: ignore[arg-type]
    sig = radar.scan(MINT, POOL, safety())
    assert gecko.calls == [(POOL, 100.0)] and sig.window_min == 30.0
    assert sig.reasons == ["insiders sold $150"]


# --------------------------------------------------------------------------- with O1's real client


def test_scan_through_real_geckoterminal_client(fake_http, http_client, settings, fake_clock, load_fixture) -> None:
    """``gt_trades.json`` with one sell re-attributed to the creator, parsed by O1's real client."""
    payload = load_fixture("gt_trades")
    sell = next(item for item in payload["data"] if item["attributes"]["kind"] == "sell")
    sell["attributes"].update(tx_from_address=CREATOR, volume_in_usd="1250.5")
    fake_http.register(f"/pools/{POOL}/trades", payload)
    sources = build_sources(settings, http_client)
    try:
        sources.gecko.trades(POOL, min_usd=300.0)
    except NotImplementedError:
        pytest.skip("O1 GeckoTerminal client not implemented yet")
    fake_http.reset_calls()

    stale = Radar(sources, settings, fake_clock).scan(MINT, POOL, safety())  # FIXED_NOW: trades ~28 min old
    assert stale.flagged is False and stale.trades_seen == 3

    soon_after = FakeClock(GT_TRADES_NEWEST_TS + 5 * 60)
    sig = Radar(sources, settings, soon_after).scan(MINT, POOL, safety(), liquidity_usd=60_000.0)
    assert sig.flagged and sig.creator_sold and sig.reasons == ["creator sold $1,250", "insiders sold $1,250"]
    assert sig.top_holder_sells[0]["tx_hash"] == sell["attributes"]["tx_hash"]
    assert "trade_volume_in_usd_greater_than=300" in fake_http.calls[0].full_url


@pytest.mark.live
def test_live_scan_smoke(settings) -> None:
    """Opt-in (NIGHTCRAWLER_LIVE_TESTS=1): HIGGS pool big trades from the real GeckoTerminal."""
    from nightcrawler.clock import RealClock
    from nightcrawler.http import HttpClient

    clock = RealClock()
    radar = Radar(build_sources(settings, HttpClient.from_settings(settings, clock=clock)), settings, clock)
    sig = radar.scan("DoVAVzViX8Bjy3r15nwikSaSbzE6dV4ovd28aWpJpump", "BFrSZakeqNzVtM3EFhroo4eRhagmmWN8BRntiQKFH6Ru",
                     None, liquidity_usd=100_000.0)
    assert sig.error is None and sig.trades_seen > 0
    assert sig.big_sells_usd >= 0 and sig.checked_at > 0
