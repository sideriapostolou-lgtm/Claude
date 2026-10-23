"""GeckoTerminal client: pool normalization, trades, OHLCV pagination, token endpoints."""

from __future__ import annotations

import time

import pytest

from fakes import FakeRequest
from nightcrawler.http import HttpClient, HttpError
from nightcrawler.models import SOL_MINT
from nightcrawler.sources._parse import parse_ts
from nightcrawler.sources.geckoterminal import (
    HEADERS,
    OHLCV_MAX_LIMIT,
    GeckoTerminalClient,
    graduation_time,
    normalize_pool,
    pool_to_candidate,
)

GARY = "8ZCmwpW3MtC5UpNcZf7U4HMvRNTo71syU11BDiAFpump"
GARY_POOL = "2uZuTQEjcXcR1ESwMdGTpqEwM5PCekEwrSNVRPc1EhS1"
HIGGS_POOL = "BFrSZakeqNzVtM3EFhroo4eRhagmmWN8BRntiQKFH6Ru"
BASE = "https://api.geckoterminal.com/api/v2/networks/solana"
END = 1_791_475_200  # minute-aligned "now" of the fake clock


@pytest.fixture
def client(http_client: HttpClient) -> GeckoTerminalClient:
    return GeckoTerminalClient(http_client)


def _ohlcv_body(rows: list) -> dict:
    return {"data": {"attributes": {"ohlcv_list": rows}}}


def _paginating_ohlcv(created_ts: int, interval_s: int = 60):
    """Responder emulating GT: rows NEWEST FIRST, before_timestamp exclusive, nothing before pool creation."""

    def respond(req: FakeRequest) -> dict:
        before, limit = int(req.params["before_timestamp"]), int(req.params["limit"])
        rows, ts = [], (before - 1) // interval_s * interval_s
        while ts >= created_ts and len(rows) < limit:
            rows.append([ts, "1.0", "1.2", "0.9", "1.1", "10.5"])
            ts -= interval_s
        return _ohlcv_body(rows)

    return respond


def _gt_boundary_ohlcv(closes: dict[int, float]):
    """Responder with GT's live-verified quirk: a page starts at the newest TRADED minute before
    ``before_timestamp`` and fills empty minutes only between traded ones (``closes``: ts -> close)."""
    traded = sorted(closes)

    def respond(req: FakeRequest) -> dict:
        before, limit = int(req.params["before_timestamp"]), int(req.params["limit"])
        newer = [ts for ts in traded if ts < before]
        rows, ts = [], (newer[-1] if newer else traded[0] - 60)
        while ts >= traded[0] and len(rows) < limit:
            close = closes[max(t for t in traded if t <= ts)]
            rows.append([ts, close, close, close, close, 5.0 if ts in closes else 0.0])
            ts -= 60
        return _ohlcv_body(rows)

    return respond


# --------------------------------------------------------------------------- pools


def test_new_pools_normalizes_every_pool(client, fake_http):
    fake_http.register_fixture("/new_pools", "gt_new_pools")

    pools = client.new_pools(1)

    assert [p["dex"] for p in pools] == ["meteora-dbc", "meteora-damm-v2", "meteora-dbc"]
    curve = pools[0]
    assert curve["pool"] == "DyJZSeSDqeHv3yCAYKEt9eNRe3Xody6BpZL85S1qyXBU"
    assert curve["base_mint"] == "5wjVDmEnfayycCSihhx1hU2qG3mRSkSkxxqU5KRTMvdt" and curve["quote_mint"] == SOL_MINT
    assert (curve["base_symbol"], curve["base_name"], curve["base_decimals"]) == ("Altruists", "The Altruists", 6)
    assert curve["created_at"] == parse_ts("2026-10-08T15:31:31Z")
    assert curve["reserve_usd"] is None  # "0.0" on a bonding curve means unknown, not zero
    assert curve["fdv_usd"] == pytest.approx(25421.1981111165) and curve["mcap_usd"] is None
    assert curve["price_usd"] == pytest.approx(3.36975402892e-05)
    assert curve["volume_usd"]["m5"] == pytest.approx(753.2656440488)
    assert curve["txns"]["h1"] == {"buys": 7, "sells": 0, "buyers": 7, "sellers": 0}
    assert curve["price_change_pct"]["m5"] == pytest.approx(89.686)
    assert pools[1]["reserve_usd"] == pytest.approx(1.30974124283537)
    call = fake_http.calls[0]
    assert call.url == f"{BASE}/new_pools"
    assert call.params == {"include": "base_token,quote_token,dex", "page": 1}
    assert call.headers["Accept"] == HEADERS["Accept"]


@pytest.mark.parametrize("page", [0, 11, -1])
def test_new_pools_rejects_pages_outside_1_to_10(client, fake_http, page):
    with pytest.raises(ValueError):
        client.new_pools(page)
    assert fake_http.calls == []


def test_trending_pools_sends_duration_and_validates_it(client, fake_http):
    fake_http.register_fixture("/trending_pools", "gt_trending_pools")

    pools = client.trending_pools(page=2, duration="6h")

    assert len(pools) == 3 and pools[0]["dex"] == "pumpswap"
    assert fake_http.calls[0].params["duration"] == "6h" and fake_http.calls[0].params["page"] == 2
    with pytest.raises(ValueError):
        client.trending_pools(duration="2h")  # type: ignore[arg-type]


def test_pool_normalizes_single_resource(client, fake_http):
    fake_http.register_fixture(f"/pools/{GARY_POOL}", "gt_pool")

    pool = client.pool(GARY_POOL)

    assert pool["pool"] == GARY_POOL and pool["dex"] == "pumpswap" and pool["base_mint"] == GARY
    assert pool["base_decimals"] == 6 and pool["txns"]["m5"]["buys"] == 115


def test_pool_is_none_on_404_but_other_errors_raise(client, fake_http):
    fake_http.register("/pools/MISSING", {"errors": [{"status": "404"}]}, status=404)
    fake_http.register("/pools/BAD", {"errors": [{"status": "400"}]}, status=400)

    assert client.pool("MISSING") is None
    with pytest.raises(HttpError) as info:
        client.pool("BAD")
    assert info.value.status == 400


def test_normalize_pool_without_included_falls_back_to_name():
    pool = normalize_pool({"attributes": {"name": "WIF / SOL", "reserve_in_usd": "1000.5"},
                           "relationships": {"base_token": {"data": {"id": "solana_MINT"}}}})

    assert pool["base_mint"] == "MINT" and pool["base_symbol"] == "WIF"
    assert pool["base_name"] is None and pool["base_decimals"] is None
    assert pool["reserve_usd"] == 1000.5


def test_normalize_pool_never_raises_on_empty_input():
    pool = normalize_pool({})

    assert pool["pool"] is None and pool["dex"] is None and pool["base_mint"] is None
    assert pool["name"] == "" and pool["base_symbol"] is None and pool["created_at"] is None
    assert pool["volume_usd"]["h24"] is None and pool["txns"]["m5"]["buys"] is None


def test_pool_to_candidate_maps_dex_and_curve_status(client, fake_http, fake_clock):
    fake_http.register_fixture("/new_pools", "gt_new_pools")
    now = fake_clock.now()

    curve, damm, _ = [pool_to_candidate(p, now) for p in client.new_pools(1)]

    assert curve.mint == "5wjVDmEnfayycCSihhx1hU2qG3mRSkSkxxqU5KRTMvdt" and curve.symbol == "Altruists"
    assert curve.dex == "meteoradbc" and curve.graduated is False
    assert curve.created_at == parse_ts("2026-10-08T15:31:31Z")
    assert curve.age_min == pytest.approx((now - curve.created_at) / 60)
    assert curve.mcap_usd == pytest.approx(25421.1981111165)  # market_cap null -> fdv
    assert curve.liquidity_usd is None and curve.decimals == 6
    assert curve.sources == ["gt_new_pools"] and curve.discovered_at == now
    assert curve.raw == {"gt_pool": "DyJZSeSDqeHv3yCAYKEt9eNRe3Xody6BpZL85S1qyXBU"}
    assert damm.dex == "meteoradammv2" and damm.graduated is None


@pytest.mark.parametrize("gt_dex,expected", [("pump-fun", "pumpfun"), ("pumpswap", "pumpswap"),
                                             ("raydium-clmm", "raydiumclmm"), (None, None)])
def test_pool_to_candidate_dex_ids(gt_dex, expected):
    cand = pool_to_candidate({"base_mint": "M", "dex": gt_dex, "pool": "P"}, now=100.0, source="gt_trending")

    assert cand.dex == expected and cand.sources == ["gt_trending"]
    assert cand.graduated is (False if gt_dex == "pump-fun" else None)
    assert cand.age_min is None and cand.symbol == ""
    # G01: only pump.fun's own bonding curve proves the launchpad (anyone can open a PumpSwap pool)
    assert cand.launchpad == ("pump.fun" if gt_dex == "pump-fun" else None)


def test_a_pump_fun_curve_pool_states_the_coins_launch_quote():
    """The curve's quote is the coin's launch quote (G01: SOL-quoted only); another pool's quote proves nothing."""
    usdc = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    curve = pool_to_candidate({"base_mint": "M", "quote_mint": usdc, "dex": "pump-fun", "pool": "P"}, now=0.0)
    assert curve.raw == {"gt_pool": "P", "quote_mint": usdc}
    amm = pool_to_candidate({"base_mint": "M", "quote_mint": usdc, "dex": "pumpswap", "pool": "P"}, now=0.0)
    assert amm.raw == {"gt_pool": "P"}
    unknown = pool_to_candidate({"base_mint": "M", "dex": "pump-fun", "pool": "P"}, now=0.0)
    assert unknown.raw == {"gt_pool": "P"}


def test_graduation_time_is_the_launchpads_completed_at(client, fake_http):
    """G12 fallback: GeckoTerminal's ``launchpad_details.completed_at`` when the curve completed, else None."""
    fake_http.register_fixture(f"/tokens/{GARY}", "gt_token")
    assert graduation_time(client.token(GARY)) == parse_ts("2026-10-08T13:28:26Z")
    curve = {"launchpad": {"graduation_percentage": -0.08, "completed": False, "completed_at": None}}
    assert graduation_time(curve) is None
    contradictory = {"launchpad": {"completed": False, "completed_at": 1_791_466_106.0}}
    assert graduation_time(contradictory) is None  # never trust a time GeckoTerminal itself calls unfinished
    assert graduation_time({"launchpad": {"completed": None, "completed_at": 1_791_466_106.0}}) == 1_791_466_106.0
    for nothing in (None, {}, {"launchpad": None}, {"launchpad": "x"}, "garbage"):
        assert graduation_time(nothing) is None


@pytest.mark.parametrize("base", [None, "", SOL_MINT])
def test_pool_to_candidate_skips_missing_or_sol_base(base):
    assert pool_to_candidate({"base_mint": base}, now=0.0) is None


# --------------------------------------------------------------------------- trades


def test_trades_parse_fixture_with_side_specific_fields(client, fake_http):
    fake_http.register_fixture(f"/pools/{GARY_POOL}/trades", "gt_trades")

    trades = client.trades(GARY_POOL, min_usd=300)

    assert fake_http.calls[0].params == {"trade_volume_in_usd_greater_than": "300"}
    buy, sell = trades[0], trades[1]
    assert buy["kind"] == "buy" and buy["ts"] == parse_ts("2026-10-08T15:32:10Z")
    assert buy["wallet"] == "AyHpWYkG4znPnXjtrDyR7qJ8ZeYL8S9Ef9StkePxKRKN"
    assert buy["price_usd"] == pytest.approx(0.000702723257694776) and buy["token_amount"] == 570.242485
    assert buy["volume_usd"] == pytest.approx(0.4007226567) and buy["block_number"] == 454585783
    assert sell["kind"] == "sell" and sell["price_usd"] == pytest.approx(0.000694287932879591)
    assert sell["token_amount"] == 1255.639495
    assert sell["tx_hash"].startswith("3DhmWhh4")
    assert [t["ts"] for t in trades] == sorted((t["ts"] for t in trades), reverse=True)  # newest first kept


def test_trades_skip_unparseable_items_and_omit_filter_by_default(client, fake_http):
    fake_http.register("/pools/P/trades", {"data": [
        {"attributes": {"block_timestamp": "garbage", "kind": "buy"}},
        {"attributes": {"block_timestamp": "2026-10-08T15:00:00Z", "kind": "transfer"}},
        {"attributes": {"block_timestamp": "2026-10-08T15:00:00Z", "kind": "SELL"}},
        "junk",
    ]})

    trades = client.trades("P")

    assert fake_http.calls[0].params is None
    assert len(trades) == 1 and trades[0]["kind"] == "sell"
    assert trades[0]["volume_usd"] == 0.0 and trades[0]["price_usd"] is None and trades[0]["wallet"] is None


def test_trades_min_usd_is_sent_as_plain_number(client, fake_http):
    fake_http.register("/pools/P/trades", {"data": []})

    client.trades("P", min_usd=2_500_000)
    client.trades("P", min_usd=0.5)

    assert [c.params["trade_volume_in_usd_greater_than"] for c in fake_http.calls] == ["2500000", "0.5"]


# --------------------------------------------------------------------------- ohlcv


def test_ohlcv_page_returns_ascending_candles_and_sends_required_params(client, fake_http):
    fake_http.register_fixture(f"/pools/{GARY_POOL}/ohlcv/minute", "gt_ohlcv_minute")

    candles = client.ohlcv_page(GARY_POOL, aggregate=1, limit=10, before=1_791_473_580)

    assert [c.ts for c in candles] == list(range(1_791_472_980, 1_791_473_521, 60))
    newest = candles[-1]
    assert (newest.o, newest.c, newest.v) == pytest.approx((0.0006948176003330752, 0.0007000674153187269,
                                                            148.3869517775002))
    assert fake_http.calls[0].params == {"aggregate": 1, "limit": 10, "currency": "usd", "token": "base",
                                         "include_empty_intervals": "true", "before_timestamp": 1_791_473_580}


def test_ohlcv_page_without_before_omits_the_param(client, fake_http):
    fake_http.register("/ohlcv/minute", _ohlcv_body([]))

    assert client.ohlcv_page("P", aggregate=15, limit=5) == []
    assert "before_timestamp" not in fake_http.calls[0].params and fake_http.calls[0].params["aggregate"] == 15


@pytest.mark.parametrize("kwargs", [{"aggregate": 7}, {"aggregate": 60}, {"limit": 0}, {"limit": OHLCV_MAX_LIMIT + 1}])
def test_ohlcv_page_validates_aggregate_and_limit(client, fake_http, kwargs):
    with pytest.raises(ValueError):
        client.ohlcv_page("P", **kwargs)
    assert fake_http.calls == []


def test_ohlcv_page_skips_bad_rows_and_keeps_last_duplicate(client, fake_http):
    fake_http.register("/ohlcv/minute", _ohlcv_body([
        [180, "1", "2", "0.5", "1.5", "7"],
        [120, 1, 1, 1, 1, None],          # missing volume -> 0.0
        [60, None, 1, 1, 1, 1],           # bad open -> skipped
        ["abc", 1, 1, 1, 1, 1],           # bad ts -> skipped
        [0, 1, 1],                        # short row -> skipped
        "junk",
        [180, "9", "9", "9", "9", "9"],   # duplicate ts -> last one wins
    ]))

    candles = client.ohlcv_page("P")

    assert [c.ts for c in candles] == [120, 180]
    assert candles[0].v == 0.0 and candles[1].o == 9.0


def test_ohlcv_paginates_backwards_until_the_window_is_covered(client, fake_http):
    fake_http.register("/ohlcv/minute", _paginating_ohlcv(created_ts=END - 30 * 86_400))

    candles = client.ohlcv("P", minutes=2500, before=END)

    assert len(candles) == 2500
    assert [c.ts for c in candles] == list(range(END - 2500 * 60, END, 60))
    pages = [(c.params["before_timestamp"], c.params["limit"]) for c in fake_http.calls]
    assert pages == [(END, 1000), (END - 60_000, 1000), (END - 120_000, 501)]


def test_ohlcv_fills_no_trade_minutes_lost_at_a_page_boundary(client, fake_http):
    hole = range(END - 60_420, END - 60_000, 60)  # 7 quiet minutes right before page 1's oldest row
    closes = {ts: ts / 1e6 for ts in range(END - 2000 * 60, END, 60) if ts not in hole}
    fake_http.register("/ohlcv/minute", _gt_boundary_ohlcv(closes))

    candles = client.ohlcv("P", minutes=1500, before=END)

    assert [c.ts for c in candles] == list(range(END - 90_000, END, 60))
    filled = [c for c in candles if c.ts in hole]
    last_close = closes[END - 60_480]
    assert len(filled) == 7 and all((c.o, c.h, c.l, c.c, c.v) == (last_close,) * 4 + (0.0,) for c in filled)
    assert fake_http.calls[1].params["before_timestamp"] == END - 60_000


def test_ohlcv_never_invents_candles_after_the_newest_trade(client, fake_http):
    closes = {ts: 1.0 for ts in range(END - 3600, END - 600, 60)}  # quiet for the last 10 minutes
    fake_http.register("/ohlcv/minute", _gt_boundary_ohlcv(closes))

    candles = client.ohlcv("P", minutes=30, before=END)

    assert candles[-1].ts == END - 660 and candles[0].ts == END - 1800


def test_ohlcv_stops_at_pool_creation(client, fake_http):
    fake_http.register("/ohlcv/minute", _paginating_ohlcv(created_ts=END - 100 * 60))

    candles = client.ohlcv("P", minutes=180, before=END)

    assert len(fake_http.calls) == 1 and len(candles) == 100
    assert candles[0].ts == END - 100 * 60


def test_ohlcv_defaults_end_to_clock_and_trims_unaligned_window(client, fake_http, fake_clock):
    fake_clock.advance(30)  # now = END + 30: the END candle is still open but inside the window
    fake_http.register("/ohlcv/minute", _paginating_ohlcv(created_ts=END - 86_400))

    candles = client.ohlcv("P", minutes=10)

    assert fake_http.calls[0].params["before_timestamp"] == END + 30
    assert [c.ts for c in candles] == list(range(END - 540, END + 1, 60))


def test_ohlcv_supports_5_minute_aggregation(client, fake_http):
    fake_http.register("/ohlcv/minute", _paginating_ohlcv(created_ts=END - 86_400, interval_s=300))

    candles = client.ohlcv("P", minutes=60, aggregate=5, before=END)

    assert len(candles) == 12 and fake_http.calls[0].params["limit"] == 13


def test_ohlcv_stops_when_the_api_makes_no_progress(client, fake_http):
    full_page = [[END - 60 * i, 1, 1, 1, 1, 1] for i in range(1, 1001)]
    fake_http.register("/ohlcv/minute", _ohlcv_body(full_page))  # ignores before_timestamp

    candles = client.ohlcv("P", minutes=5000, before=END)

    assert len(fake_http.calls) == 2 and len(candles) == 1000


def test_ohlcv_with_no_minutes_makes_no_request(client, fake_http):
    assert client.ohlcv("P", minutes=0) == []
    assert fake_http.calls == []


def test_ohlcv_http_400_surfaces_as_http_error(client, fake_http):
    fake_http.register_fixture("/ohlcv/minute", "gt_ohlcv_invalid_aggregate_400", status=400)

    with pytest.raises(HttpError) as info:
        client.ohlcv("P", minutes=5, before=END)
    assert info.value.status == 400 and "Invalid aggregate" in info.value.body
    assert len(fake_http.calls) == 1  # 4xx is not retried


# --------------------------------------------------------------------------- tokens


def test_token_normalizes_launchpad_and_top_pools(client, fake_http):
    fake_http.register_fixture(f"/tokens/{GARY}", "gt_token")

    token = client.token(GARY)

    assert fake_http.calls[0].params == {"include": "top_pools"}
    assert (token["mint"], token["symbol"], token["decimals"]) == (GARY, "Gary", 6)
    assert token["price_usd"] == pytest.approx(0.0006507656584) and token["mcap_usd"] is None
    assert token["total_supply"] == pytest.approx(994092212.949025)
    assert token["reserve_usd"] == pytest.approx(37803.3838833828)
    assert token["volume_h24_usd"] == pytest.approx(972218.92195391)
    assert token["launchpad"] == {"graduation_percentage": 100.0, "completed": True,
                                  "completed_at": parse_ts("2026-10-08T13:28:26Z"), "migrated_pool": GARY_POOL}
    assert token["top_pools"] == [GARY_POOL, "FLhP2iCq9TNSxtUhE2aVs3DHnh9ihkJCzXaY2nePkeLu"]


def test_token_and_token_info_are_none_on_404(client, fake_http):
    fake_http.register("/tokens/", {"errors": [{"status": "404", "title": "Not Found"}]}, status=404)

    assert client.token("MISSING") is None
    assert client.token_info("MISSING") is None


def test_token_info_graduated_token(client, fake_http):
    fake_http.register_fixture(f"/tokens/{GARY}/info", "gt_token_info")

    info = client.token_info(GARY)

    assert info["mint"] == GARY and info["holders_count"] == 3058
    assert info["top10_pct"] == pytest.approx(7.3843)
    assert info["holders_updated_at"] == parse_ts("2026-10-08T15:20:59Z")
    assert info["mint_authority_enabled"] is False and info["freeze_authority_enabled"] is False
    assert info["developer"] == "G7YaEzm4c1aMQcn1SQLUPHYnoUNE7bG4XwQ4nxyYydn"
    assert info["developer_holding_pct"] == pytest.approx(5.05) and info["gt_score"] == pytest.approx(72.987, abs=1e-3)
    assert info["websites"] == [] and info["twitter"] is None and info["telegram"] is None
    assert info["is_honeypot"] == "unknown" and info["launchpad"]["completed"] is True


def test_token_info_fresh_curve_token_has_null_holder_stats(client, fake_http):
    fake_http.register_fixture("/info", "gt_token_info_bondingcurve")

    info = client.token_info("EDQRk4ETkyb4qkcGfeVMxK3FsFXava7Q3HFxmpJXpump")

    assert info["holders_count"] is None and info["top10_pct"] is None and info["holders_updated_at"] is None
    assert info["launchpad"] == {"graduation_percentage": -0.08, "completed": False, "completed_at": None,
                                 "migrated_pool": None}


def test_token_info_accepts_website_dicts_and_handles(client, fake_http):
    fake_http.register("/info", {"data": {"id": "solana_M", "attributes": {
        "websites": ["https://a.example", {"url": "https://b.example"}, None],
        "twitter_handle": "gary", "telegram_handle": "garytg", "mint_authority": "yes",
    }}})

    info = client.token_info("M")

    assert info["mint"] == "M" and info["websites"] == ["https://a.example", "https://b.example"]
    assert (info["twitter"], info["telegram"], info["mint_authority_enabled"]) == ("gary", "garytg", True)
    assert info["freeze_authority_enabled"] is None and info["launchpad"] is None


# --------------------------------------------------------------------------- live


@pytest.mark.live
def test_live_geckoterminal_smoke():
    gt = GeckoTerminalClient(HttpClient())

    pools = gt.new_pools(1)
    assert pools and all(p["pool"] and p["created_at"] for p in pools)
    end = int(time.time()) // 60 * 60
    candles = gt.ohlcv(HIGGS_POOL, minutes=1100, before=end)  # 2 pages: checks the boundary gap fill
    newest = candles[-1].ts
    assert newest >= end - 600 and [c.ts for c in candles] == list(range(end - 66_000, newest + 1, 60))
    assert all(c.l <= min(c.o, c.c) and c.h >= max(c.o, c.c) for c in candles)
    trades = gt.trades(HIGGS_POOL, min_usd=20)
    assert all(t["kind"] in ("buy", "sell") and t["volume_usd"] >= 20 and t["wallet"] for t in trades)
