"""DexScreener client: chain filtering, batching, top-pair choice, snapshot parsing."""

from __future__ import annotations

import time

import pytest

from nightcrawler.http import HttpClient, HttpError
from nightcrawler.sources.dexscreener import MAX_BATCH, DexScreenerClient, pair_socials, pair_to_snapshot

HIGGS = "DoVAVzViX8Bjy3r15nwikSaSbzE6dV4ovd28aWpJpump"
TAYLOR = "B9CiaENLsnu48MJTdeQBzT6Nuaw51uavLL5DgQ9ij7f5"
FIFTH = "7qCo5pmqU4UmxN2EBzDE1FFLhot9NNi91wSvnjYFiFTH"
HIGGS_PAIR = "BFrSZakeqNzVtM3EFhroo4eRhagmmWN8BRntiQKFH6Ru"


@pytest.fixture
def client(http_client: HttpClient) -> DexScreenerClient:
    return DexScreenerClient(http_client)


def _pair(mint: str, liquidity: float | None = None, volume_h24: float | None = None, **extra) -> dict:
    pair = {"chainId": "solana", "baseToken": {"address": mint}, "pairAddress": f"pair-{liquidity}-{volume_h24}"}
    if liquidity is not None:
        pair["liquidity"] = {"usd": liquidity}
    if volume_h24 is not None:
        pair["volume"] = {"h24": volume_h24}
    pair.update(extra)
    return pair


# --------------------------------------------------------------------------- feeds


def test_token_profiles_latest_keeps_solana_items_only(client, fake_http):
    fake_http.register_fixture("/token-profiles/latest/v1", "dexs_token_profiles_latest")

    profiles = client.token_profiles_latest()

    assert [p["mint"] for p in profiles] == [TAYLOR, FIFTH]
    assert fake_http.calls[0].url == "https://api.dexscreener.com/token-profiles/latest/v1"
    first = profiles[0]
    assert first["description"] is None  # "" upstream
    assert first["url"].startswith("https://dexscreener.com/solana/")
    assert first["links"][1] == {"type": "twitter", "url": "https://x.com/Polymarket/status/2108217383206760828"}
    assert first["links"][0]["label"] == "Website"


def test_token_profiles_skip_items_without_address_or_links(client, fake_http):
    fake_http.register("/token-profiles/latest/v1", [
        {"chainId": "solana"},
        {"chainId": "solana", "tokenAddress": "MINT", "links": [{"label": "no url"}, "junk"]},
        "not-a-dict",
    ])

    assert client.token_profiles_latest() == [{"mint": "MINT", "url": None, "description": None, "links": []}]


def test_token_boosts_latest_parses_amounts_and_filters_chain(client, fake_http):
    fake_http.register_fixture("/token-boosts/latest/v1", "dexs_boosts_latest")

    boosts = client.token_boosts_latest()

    assert [b["mint"] for b in boosts] == ["7nLukVng5teXze14rum9v57juXLjUp7JJnCveko1pump",
                                           "Bz6wXonBzHNLqLr4v8FaqtfEtSfr27iua7YeM6Qgpump"]
    assert boosts[0]["amount"] == 10.0 and boosts[0]["total_amount"] == 10.0


def test_feed_endpoint_that_returns_an_object_yields_nothing(client, fake_http):
    fake_http.register("/token-boosts/latest/v1", {"unexpected": True})

    assert client.token_boosts_latest() == []


def test_search_keeps_solana_pairs_and_sends_query(client, fake_http):
    fake_http.register_fixture("/latest/dex/search", "dexs_search")

    pairs = client.search("HIGGS")

    assert len(pairs) == 2 and all(p["chainId"] == "solana" for p in pairs)
    assert fake_http.calls[0].params == {"q": "HIGGS"}


# --------------------------------------------------------------------------- tokens / snapshots


def test_tokens_returns_one_top_pair_per_requested_mint(client, fake_http):
    fake_http.register_fixture("/tokens/v1/solana/", "dexs_tokens_batch")

    pairs = client.tokens([HIGGS, TAYLOR, FIFTH])

    assert set(pairs) == {HIGGS, TAYLOR, FIFTH}
    assert pairs[HIGGS]["pairAddress"] == HIGGS_PAIR
    assert fake_http.calls[0].url == f"https://api.dexscreener.com/tokens/v1/solana/{HIGGS},{TAYLOR},{FIFTH}"


def test_tokens_batches_by_30_and_requests_duplicates_once(client, fake_http):
    fake_http.register("/tokens/v1/solana/", [])
    mints = [f"M{i:03d}" for i in range(61)] + ["M000"]

    assert client.tokens(mints) == {}

    batches = [c.url.rsplit("/", 1)[1].split(",") for c in fake_http.calls]
    assert [len(b) for b in batches] == [MAX_BATCH, MAX_BATCH, 1]
    assert sum(batches, []) == [f"M{i:03d}" for i in range(61)]


def test_tokens_with_no_mints_makes_no_request(client, fake_http):
    assert client.tokens([]) == {}
    assert client.snapshots([], now=1.0) == {}
    assert fake_http.calls == []


def test_tokens_picks_highest_liquidity_then_volume_and_ignores_unrequested(client, fake_http):
    fake_http.register("/tokens/v1/solana/", [
        _pair("A", liquidity=100, volume_h24=999),
        _pair("A", liquidity=200, volume_h24=1),
        _pair("B", volume_h24=5),  # missing liquidity counts as 0
        _pair("B", liquidity=0, volume_h24=50),
        _pair("NOT_REQUESTED", liquidity=1e9),
        _pair("A", liquidity=1e9, chainId="ethereum"),
    ])

    pairs = client.tokens(["A", "B"])

    assert set(pairs) == {"A", "B"}
    assert pairs["A"]["liquidity"]["usd"] == 200
    assert pairs["B"]["volume"]["h24"] == 50


def test_snapshots_convert_fixture_pairs(client, fake_http, fake_clock):
    fake_http.register_fixture("/tokens/v1/solana/", "dexs_tokens_batch")

    snaps = client.snapshots([HIGGS, TAYLOR], now=fake_clock.now())

    higgs = snaps[HIGGS]
    assert higgs.ts == fake_clock.now()
    assert higgs.price_usd == pytest.approx(0.0008832)
    assert higgs.mcap_usd == 855186 and higgs.fdv_usd == 855167
    assert higgs.liquidity_usd == pytest.approx(119336.33)
    assert (higgs.buys_m5, higgs.sells_m5, higgs.buys_h1, higgs.sells_h1) == (3, 4, 76, 57)
    assert higgs.volume_m5 == pytest.approx(1343.43) and higgs.volume_h1 == pytest.approx(11146.98)
    assert higgs.price_change_m5 == pytest.approx(-4.83) and higgs.price_change_h1 == pytest.approx(-2.1)
    assert higgs.pool == HIGGS_PAIR and higgs.dex == "pumpswap"
    assert higgs.pair_created_at == 1_791_117_376.0  # ms -> s
    curve = snaps[TAYLOR]
    assert curve.dex == "pumpfun" and curve.liquidity_usd is None  # bonding curve: no liquidity field
    assert curve.mcap_usd == pytest.approx(8526.48)


def test_pair_to_snapshot_defaults_for_missing_fields():
    snap = pair_to_snapshot({"baseToken": {"address": "M"}}, ts=5.0)

    assert snap is not None and snap.mint == "M" and snap.ts == 5.0
    assert snap.price_usd is None and snap.mcap_usd is None and snap.liquidity_usd is None
    assert (snap.buys_m5, snap.sells_m5, snap.volume_m5, snap.volume_h1) == (0, 0, 0.0, 0.0)
    assert snap.price_change_m5 is None and snap.pair_created_at is None and snap.pool is None


def test_pair_to_snapshot_mcap_falls_back_to_fdv_and_parses_strings():
    snap = pair_to_snapshot({"baseToken": {"address": "M"}, "fdv": "1234.5", "priceUsd": "0.01",
                             "txns": {"m5": {"buys": "7", "sells": None}}}, ts=0.0)

    assert snap.mcap_usd == 1234.5 and snap.price_usd == 0.01
    assert snap.buys_m5 == 7 and snap.sells_m5 == 0


@pytest.mark.parametrize("pair", [{}, {"baseToken": {}}, {"baseToken": None}, None, "x"])
def test_pair_to_snapshot_without_mint_is_none(pair):
    assert pair_to_snapshot(pair, ts=0.0) is None


# --------------------------------------------------------------------------- pairs


def test_token_pairs_returns_solana_pairs(client, fake_http):
    fake_http.register_fixture(f"/token-pairs/v1/solana/{HIGGS}", "dexs_token_pairs")

    pairs = client.token_pairs(HIGGS)

    assert [p["dexId"] for p in pairs] == ["pumpswap", "pumpfun"]


def test_pair_returns_the_pair_object(client, fake_http):
    fake_http.register_fixture(f"/latest/dex/pairs/solana/{HIGGS_PAIR}", "dexs_pair")

    assert client.pair(HIGGS_PAIR)["pairAddress"] == HIGGS_PAIR


def test_pair_falls_back_to_pairs_list(client, fake_http):
    fake_http.register("/latest/dex/pairs/solana/P", {"pairs": [_pair("M")], "pair": None})

    assert client.pair("P")["baseToken"]["address"] == "M"


@pytest.mark.parametrize("status,body", [(200, {"schemaVersion": "1.0.0", "pairs": None, "pair": None}),
                                         (404, {"error": "not found"})])
def test_pair_not_found_is_none(client, fake_http, status, body):
    fake_http.register("/latest/dex/pairs/solana/P", body, status=status)

    assert client.pair("P") is None


def test_server_errors_raise_http_error_after_retries(client, fake_http):
    fake_http.register("/latest/dex/pairs/solana/P", {"error": "boom"}, status=503)

    with pytest.raises(HttpError) as info:
        client.pair("P")
    assert info.value.status == 503
    assert len(fake_http.calls) == 5  # 1 attempt + 4 retries


# --------------------------------------------------------------------------- socials


def test_pair_socials_from_fixture(load_fixture):
    pair = load_fixture("dexs_tokens_batch")[0]

    assert pair_socials(pair) == {"website": "https://higgspad.com/", "twitter": "https://x.com/higgspad"}


def test_pair_socials_normalizes_types_and_first_url_wins():
    pair = {"info": {
        "websites": [{"label": "Docs"}, {"url": "https://a.example"}, {"url": "https://b.example"}],
        "socials": [{"type": "X", "url": "https://x.com/one"}, {"type": "twitter", "url": "https://x.com/two"},
                    {"platform": "telegram", "handle": "tgchan"}, {"type": "discord"}, "junk"],
    }}

    assert pair_socials(pair) == {"website": "https://a.example", "twitter": "https://x.com/one",
                                  "telegram": "tgchan"}


@pytest.mark.parametrize("pair", [{}, {"info": None}, {"info": {"websites": None, "socials": "x"}}])
def test_pair_socials_missing_info_is_empty(pair):
    assert pair_socials(pair) == {}


# --------------------------------------------------------------------------- live


@pytest.mark.live
def test_live_dexscreener_smoke():
    client = DexScreenerClient(HttpClient())

    boosts = client.token_boosts_latest()
    assert all(isinstance(b["mint"], str) and b["mint"] for b in boosts)
    snaps = client.snapshots([HIGGS] + [b["mint"] for b in boosts[:5]], now=time.time())
    higgs = snaps[HIGGS]
    assert higgs.price_usd and higgs.price_usd > 0
    assert higgs.pool and higgs.dex and higgs.pair_created_at and higgs.pair_created_at < time.time()
    pairs = client.token_pairs(HIGGS)
    assert pairs and all(p["chainId"] == "solana" for p in pairs)
