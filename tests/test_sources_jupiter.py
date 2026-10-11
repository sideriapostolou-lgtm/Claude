"""Jupiter client: Ultra order/execute/holdings/shield, tokens v2, price v3."""

from __future__ import annotations

import os

import pytest

from nightcrawler.config import Secret
from nightcrawler.http import HttpClient, HttpError
from nightcrawler.models import SOL_MINT, Balances
from nightcrawler.sources._parse import parse_ts
from nightcrawler.sources.jupiter import (
    KEYED_BASE_URL,
    LITE_BASE_URL,
    PRICE_BATCH,
    JupiterClient,
    JupiterError,
    quote_from_order,
    token_to_candidate,
    tokens_to_candidates,
)

HIGGS = "DoVAVzViX8Bjy3r15nwikSaSbzE6dV4ovd28aWpJpump"
GARY = "8ZCmwpW3MtC5UpNcZf7U4HMvRNTo71syU11BDiAFpump"
TAKER = "FBZ4MxMyVYrba5JyJCAqLS5B5p2wjw5fykTXBTU8gA1o"


@pytest.fixture
def client(http_client: HttpClient) -> JupiterClient:
    return JupiterClient(http_client)


def _order(**overrides) -> dict:
    resp = {"inputMint": SOL_MINT, "outputMint": "TOKEN", "inAmount": "1000", "outAmount": "2000"}
    resp.update(overrides)
    return resp


# --------------------------------------------------------------------------- Ultra /order


def test_ultra_order_buy_without_taker(client, fake_http, fake_clock):
    fake_http.register_fixture("/ultra/v1/order", "jup_ultra_order_buy")

    quote = client.ultra_order(SOL_MINT, HIGGS, 100_000_000)

    call = fake_http.calls[0]
    assert call.url == f"{LITE_BASE_URL}/ultra/v1/order"
    assert call.params == {"inputMint": SOL_MINT, "outputMint": HIGGS, "amount": "100000000"}
    assert "x-api-key" not in call.headers
    assert (quote.side, quote.input_mint, quote.output_mint, quote.token_mint) == ("buy", SOL_MINT, HIGGS, HIGGS)
    assert (quote.in_amount, quote.out_amount, quote.other_amount_threshold) == (100_000_000, 16_239_400_281,
                                                                                  16_239_400_281)
    assert quote.price_impact_pct == pytest.approx(2.1957373766982126)  # "-0.0219..." fraction -> +2.19 %
    assert quote.fee_bps == 10 and quote.route_labels == ["Pump.fun Amm"] and quote.router == "metis"
    assert quote.request_id == "01a11c56-cfde-72ec-a552-db4ef3aa8c67"
    assert quote.transaction_b64 is None and not quote.executable
    assert quote.quoted_at == fake_clock.now()
    assert (quote.in_usd, quote.out_usd) == pytest.approx((10.885650682171027, 10.646630381445794))
    assert quote.usd_value_loss_pct == pytest.approx(2.1957, abs=1e-3)
    assert quote.error is None and quote.error_code is None and quote.slippage_bps == 0
    assert (quote.signature_fee_lamports, quote.prioritization_fee_lamports, quote.rent_fee_lamports) == (0, 0, 0)
    assert quote.raw["requestId"] == quote.request_id


def test_ultra_order_insufficient_funds_keeps_valid_amounts(client, fake_http):
    fake_http.register_fixture("/ultra/v1/order", "jup_ultra_order_buy_insufficient_funds")

    quote = client.ultra_order(SOL_MINT, HIGGS, 100_000_000, taker=TAKER)

    assert fake_http.calls[0].params["taker"] == TAKER
    assert quote.error == "Insufficient funds" and quote.error_code == 1 and quote.is_insufficient_funds
    assert quote.transaction_b64 is None  # "" upstream
    assert quote.out_amount == 16_239_400_280 and quote.other_amount_threshold == 16_031_535_956
    assert quote.slippage_bps == 128 and quote.price_impact_pct == pytest.approx(2.195737382720869)


def test_ultra_order_sell_round_trip_loses_about_1_6_percent(client, fake_http):
    fake_http.register_fixture("/ultra/v1/order", "jup_ultra_order_sell")

    sell = client.ultra_order(HIGGS, SOL_MINT, 16_239_400_281)

    assert sell.side == "sell" and sell.token_mint == HIGGS
    assert (sell.in_amount, sell.out_amount) == (16_239_400_281, 98_445_289)
    assert sell.price_impact_pct == pytest.approx(0.02230429442084727) and sell.route_labels == ["Meteora DLMM"]
    assert sell.out_amount / 100_000_000 - 1 == pytest.approx(-0.0155, abs=1e-3)


def test_ultra_order_with_transaction_is_executable(client, fake_http, load_fixture):
    fake_http.register("/ultra/v1/order", {**load_fixture("jup_ultra_order_buy"), "transaction": "AQID"})

    quote = client.ultra_order(SOL_MINT, HIGGS, 100_000_000, taker=TAKER)

    assert quote.transaction_b64 == "AQID" and quote.executable


def test_api_key_is_sent_as_header_on_the_keyed_host(http_client, fake_http):
    fake_http.register("/ultra/v1/order", _order(outputMint=HIGGS))
    client = JupiterClient(http_client, base_url=KEYED_BASE_URL + "/", api_key=Secret("k-123"))

    client.ultra_order(SOL_MINT, HIGGS, 1000)

    assert fake_http.calls[0].url == f"{KEYED_BASE_URL}/ultra/v1/order"
    assert fake_http.calls[0].headers["x-api-key"] == "k-123"
    assert "k-123" not in repr(client.api_key)


@pytest.mark.parametrize("inp,out", [(SOL_MINT, SOL_MINT), ("A", "B")])
def test_ultra_order_requires_exactly_one_sol_side(client, fake_http, inp, out):
    with pytest.raises(ValueError):
        client.ultra_order(inp, out, 1000)
    assert fake_http.calls == []


@pytest.mark.parametrize("amount", [0, -5, 1.5, True, "1000", None])
def test_ultra_order_requires_positive_int_amount(client, fake_http, amount):
    with pytest.raises(ValueError):
        client.ultra_order(SOL_MINT, HIGGS, amount)
    assert fake_http.calls == []


def test_ultra_order_without_amounts_raises_jupiter_error(client, fake_http):
    fake_http.register("/ultra/v1/order", {"errorCode": 2, "error": "No routes found"})

    with pytest.raises(JupiterError, match="No routes found"):
        client.ultra_order(SOL_MINT, HIGGS, 1000)


def test_ultra_order_non_object_response_raises_jupiter_error(client, fake_http):
    fake_http.register("/ultra/v1/order", [])

    with pytest.raises(JupiterError):
        client.ultra_order(SOL_MINT, HIGGS, 1000)


def test_ultra_order_http_errors_propagate(client, fake_http):
    fake_http.register("/ultra/v1/order", {"error": "bad request"}, status=400)

    with pytest.raises(HttpError):
        client.ultra_order(SOL_MINT, HIGGS, 1000)


# --------------------------------------------------------------------------- quote_from_order


@pytest.mark.parametrize("fields,expected", [
    ({"priceImpactPct": "0.01"}, 1.0),
    ({"priceImpactPct": "-0.25", "priceImpact": -99}, 25.0),
    ({"priceImpact": -2.5}, 2.5),
    ({"priceImpactPct": None, "priceImpact": "1.5"}, 1.5),
    ({}, 0.0),
])
def test_quote_price_impact_is_a_non_negative_percent(fields, expected):
    quote = quote_from_order(_order(**fields), "buy", quoted_at=1.0)

    assert quote.price_impact_pct == pytest.approx(expected)


def test_quote_fee_bps_falls_back_to_platform_fee():
    assert quote_from_order(_order(platformFee={"feeBps": 20}), "buy", 0.0).fee_bps == 20
    assert quote_from_order(_order(), "buy", 0.0).fee_bps == 0


def test_quote_error_code_without_message_is_never_executable():
    quote = quote_from_order(_order(errorCode=3, transaction="AQID"), "buy", 0.0)

    assert quote.error == "Ultra errorCode 3" and quote.error_code == 3 and not quote.executable
    assert quote_from_order(_order(errorCode=0, transaction="AQID"), "buy", 0.0).executable


def test_quote_route_labels_skip_steps_without_label():
    plan = [{"swapInfo": {"label": "Raydium"}}, {"swapInfo": {}}, "junk", {"swapInfo": {"label": "Orca"}}]

    assert quote_from_order(_order(routePlan=plan), "buy", 0.0).route_labels == ["Raydium", "Orca"]


def test_quote_uses_fallback_mints_and_checks_side():
    resp = {"inAmount": "5", "outAmount": "6"}

    quote = quote_from_order(resp, "sell", 0.0, input_mint="TOKEN", output_mint=SOL_MINT)

    assert (quote.input_mint, quote.output_mint) == ("TOKEN", SOL_MINT)
    with pytest.raises(JupiterError):
        quote_from_order(resp, "sell", 0.0)  # mints unknown
    with pytest.raises(JupiterError):
        quote_from_order(_order(), "sell", 0.0)  # SOL in is a buy


# --------------------------------------------------------------------------- Ultra /execute


def test_ultra_execute_posts_signed_tx_and_parses_success(client, fake_http):
    fake_http.register_fixture("/ultra/v1/execute", "jup_ultra_execute_success_synthetic", method="POST")

    result = client.ultra_execute("SIGNED_B64", "req-1")

    call = fake_http.calls[0]
    assert call.method == "POST" and call.url == f"{LITE_BASE_URL}/ultra/v1/execute"
    assert call.json == {"signedTransaction": "SIGNED_B64", "requestId": "req-1"}
    assert result["status"] == "Success" and result["signature"].startswith("5ynthetic1")
    assert result["slot"] == 454_600_000 and result["code"] == 0 and result["error"] is None
    assert (result["input_amount"], result["output_amount"]) == (100_000_000, 16_200_000_000)
    assert result["raw"]["swapEvents"][0]["outputAmount"] == "16200000000"


def test_ultra_execute_parses_failure(client, fake_http):
    fake_http.register_fixture("/ultra/v1/execute", "jup_ultra_execute_failed_synthetic")

    result = client.ultra_execute("SIGNED_B64", "req-1")

    assert result["status"] == "Failed" and result["error"] == "Transaction expired" and result["code"] == -1005
    assert result["input_amount"] is None and result["output_amount"] is None


def test_ultra_execute_falls_back_to_total_amounts_and_passes_unknown_status(client, fake_http):
    fake_http.register("/ultra/v1/execute", {"totalInputAmount": "5", "totalOutputAmount": "7"})

    result = client.ultra_execute("S", "r")

    assert result["status"] is None and (result["input_amount"], result["output_amount"]) == (5, 7)


@pytest.mark.parametrize("status", [429, 503])
def test_ultra_execute_is_never_retried(client, fake_http, status):
    fake_http.register("/ultra/v1/execute", {"error": "busy"}, status=status)

    with pytest.raises(HttpError):
        client.ultra_execute("S", "r")
    assert len(fake_http.calls) == 1


# --------------------------------------------------------------------------- holdings / shield


def test_holdings_sums_token_accounts(client, fake_http):
    fake_http.register_fixture(f"/ultra/v1/holdings/{TAKER}", "jup_ultra_holdings_synthetic")

    assert client.holdings(TAKER) == Balances(sol_lamports=250_000_000, tokens={HIGGS: 16_200_000_000})


def test_holdings_empty_wallet(client, fake_http):
    fake_http.register_fixture("/ultra/v1/holdings/", "jup_ultra_holdings_empty")

    assert client.holdings(TAKER) == Balances(sol_lamports=0, tokens={})


def test_holdings_multiple_accounts_and_missing_amounts(client, fake_http):
    fake_http.register("/ultra/v1/holdings/", {"amount": "5", "tokens": {
        "A": [{"amount": "10"}, {"amount": "15"}, {"uiAmount": 3.0}, "junk"],
        "B": {"amount": "7"},
        SOL_MINT: [{"amount": "1"}],
    }})

    assert client.holdings(TAKER) == Balances(sol_lamports=5, tokens={"A": 25, "B": 7, SOL_MINT: 1})


def test_shield_returns_every_requested_mint(client, fake_http):
    fake_http.register_fixture("/ultra/v1/shield", "jup_ultra_shield")

    warnings = client.shield([HIGGS, SOL_MINT, "UNLISTED", HIGGS])

    assert fake_http.calls[0].params == {"mints": f"{HIGGS},{SOL_MINT},UNLISTED"}
    assert warnings == {
        HIGGS: [{"type": "NOT_VERIFIED", "severity": "info",
                 "message": "This token is not verified, make sure the mint address is correct before trading"}],
        SOL_MINT: [],
        "UNLISTED": [],
    }


def test_shield_lowercases_severity_and_batches(client, fake_http):
    fake_http.register("/ultra/v1/shield", {"warnings": {"M0": [{"type": "X", "severity": "CRITICAL"}]}})

    warnings = client.shield([f"M{i}" for i in range(51)])

    assert warnings["M0"] == [{"type": "X", "message": None, "severity": "critical"}]
    assert len(warnings) == 51 and len(fake_http.calls) == 2
    assert client.shield([]) == {} and len(fake_http.calls) == 2


# --------------------------------------------------------------------------- tokens


def test_tokens_recent_search_and_trending(client, fake_http):
    fake_http.register_fixture("/tokens/v2/recent", "jup_tokens_v2_recent")
    fake_http.register_fixture("/tokens/v2/search", "jup_tokens_v2_search")
    fake_http.register_fixture("/tokens/v2/toptrending/1h", "jup_tokens_v2_toptrending")

    assert len(client.tokens_recent()) == 3
    assert client.token_search(GARY)["symbol"] == "Gary"
    assert client.token_search("SOMETHING_ELSE") is None  # results must match the exact mint
    assert [t["symbol"] for t in client.top_trending("1h", limit=3)][0] == "PUMP"
    assert fake_http.calls_to("/search")[0].params == {"query": GARY}
    assert fake_http.calls_to("/toptrending/1h")[0].params == {"limit": 3}


def test_top_trending_rejects_unknown_window(client, fake_http):
    with pytest.raises(ValueError):
        client.top_trending("2h")  # type: ignore[arg-type]
    assert fake_http.calls == []


def test_token_lists_ignore_non_dict_items(client, fake_http):
    fake_http.register("/tokens/v2/recent", [{"id": "A"}, None, "x"])
    fake_http.register("/tokens/v2/search", {"not": "a list"})

    assert client.tokens_recent() == [{"id": "A"}]
    assert client.token_search("A") is None


def test_token_to_candidate_graduated_token(load_fixture, fake_clock):
    token = load_fixture("jup_tokens_v2_search")[0]
    now = fake_clock.now()

    cand = token_to_candidate(token, now, "jupiter_search")

    assert (cand.mint, cand.symbol, cand.name, cand.decimals) == (GARY, "Gary", "Gary the Cat", 6)
    assert cand.pool == "2uZuTQEjcXcR1ESwMdGTpqEwM5PCekEwrSNVRPc1EhS1" and cand.graduated is True
    assert cand.created_at == parse_ts("2026-10-08T13:28:26Z")
    assert cand.age_min == pytest.approx((now - cand.created_at) / 60)
    assert cand.mcap_usd == pytest.approx(603658.3857636394) and cand.liquidity_usd == pytest.approx(33279.655184)
    assert cand.price_usd == pytest.approx(0.0006072458776922986) and cand.holder_count == 2988
    assert cand.dev == "G7YaEzm4c1aMQcn1SQLUPHYnoUNE7bG4XwQ4nxyYydn" and cand.launchpad == "pump.fun"
    assert set(cand.stats) == {"5m", "1h", "6h", "24h"} and cand.stats["5m"]["numBuys"] == 374
    assert cand.audit == token["audit"] and cand.audit is not token["audit"]
    assert cand.organic_score == 0.0 and cand.socials == {}
    assert cand.sources == ["jupiter_search"] and cand.discovered_at == now
    # G12: Jupiter's graduation time is kept (the crawler and the engine measure age from it)
    assert cand.raw == {"jupiter_id": GARY, "graduated_at": parse_ts("2026-10-08T13:28:26Z")}


def test_token_to_candidate_curve_and_unknown_launchpad(load_fixture, fake_clock):
    unknown, curve, _ = load_fixture("jup_tokens_v2_recent")

    c = token_to_candidate(curve, fake_clock.now(), "jupiter_recent")
    u = token_to_candidate(unknown, fake_clock.now(), "jupiter_recent")

    assert c.graduated is False and c.pool == curve["firstPool"]["id"]
    assert c.socials == {"twitter": curve["twitter"], "website": curve["website"]}
    assert u.graduated is None and u.audit["isSus"] is True and u.launchpad is None


def test_token_to_candidate_maps_graduated_at_only_when_jupiter_sends_it(load_fixture, fake_clock):
    """``graduatedAt`` (documented, never mapped before G12) lands in ``raw["graduated_at"]`` as epoch seconds; a
    curve coin, an unparsable value or a missing field leaves it out (unknown, never invented)."""
    unknown, curve, _ = load_fixture("jup_tokens_v2_recent")
    assert "graduated_at" not in token_to_candidate(curve, fake_clock.now(), "jupiter_recent").raw
    assert "graduated_at" not in token_to_candidate(unknown, fake_clock.now(), "jupiter_recent").raw
    late = {"id": "M", "launchpad": "pump.fun", "graduatedPool": "P", "graduatedAt": "2026-10-08T15:00:00Z",
            "firstPool": {"id": "C", "createdAt": "2026-10-08T12:00:00Z"}}
    cand = token_to_candidate(late, 0.0, "s")
    assert cand.raw["graduated_at"] == parse_ts("2026-10-08T15:00:00Z") and cand.graduated is True
    assert cand.created_at == parse_ts("2026-10-08T12:00:00Z")  # creation stays the first pool's time
    garbled = token_to_candidate({**late, "graduatedAt": "soon"}, 0.0, "s")
    assert "graduated_at" not in garbled.raw and garbled.graduated is True  # the pool alone still says graduated


def test_token_to_candidate_minimal_token_uses_created_at_fallback():
    cand = token_to_candidate({"id": "M", "createdAt": "2026-10-08T15:00:00Z", "twitter": ""}, 0.0, "s")

    assert cand.created_at == parse_ts("2026-10-08T15:00:00Z") and cand.pool is None
    assert cand.mcap_usd is None and cand.holder_count is None and cand.graduated is None
    assert cand.audit == {} and cand.stats == {} and cand.socials == {} and cand.symbol == ""


def test_token_without_id_raises_and_list_helper_skips_it():
    with pytest.raises(ValueError):
        token_to_candidate({"symbol": "X"}, 0.0, "s")

    cands = tokens_to_candidates([{"symbol": "X"}, {"id": "A"}, None], 0.0, "s")  # type: ignore[list-item]

    assert [c.mint for c in cands] == ["A"]


# --------------------------------------------------------------------------- prices


def test_prices_parses_fixture_and_omits_unknown(client, fake_http):
    fake_http.register_fixture("/price/v3", "jup_price_v3")

    prices = client.prices([SOL_MINT, HIGGS, "UNKNOWN"])

    assert prices == {SOL_MINT: pytest.approx(108.31695332710045), HIGGS: pytest.approx(0.0008559214683299623)}
    assert fake_http.calls[0].params == {"ids": f"{SOL_MINT},{HIGGS},UNKNOWN"}


def test_prices_batches_dedupes_and_drops_zero(client, fake_http):
    fake_http.register("/price/v3", {"M000": {"usdPrice": 0}, "M001": {"usdPrice": "2.5"}, "M002": None})
    mints = [f"M{i:03d}" for i in range(2 * PRICE_BATCH + 1)] + ["M001"]

    prices = client.prices(mints)

    assert prices == {"M001": 2.5}
    assert [len(c.params["ids"].split(",")) for c in fake_http.calls] == [PRICE_BATCH, PRICE_BATCH, 1]
    assert client.prices([]) == {} and len(fake_http.calls) == 3


def test_sol_price_usd(client, fake_http):
    fake_http.register_fixture("/price/v3", "jup_price_v3")

    assert client.sol_price_usd() == pytest.approx(108.31695332710045)


def test_sol_price_usd_missing_raises(client, fake_http):
    fake_http.register("/price/v3", {})

    with pytest.raises(JupiterError):
        client.sol_price_usd()


# --------------------------------------------------------------------------- live


@pytest.mark.live
def test_live_jupiter_smoke():
    jup = JupiterClient(HttpClient(), base_url=os.environ.get("JUPITER_BASE_URL") or LITE_BASE_URL)

    buy = jup.ultra_order(SOL_MINT, HIGGS, 10_000_000)  # 0.01 SOL, no taker
    assert buy.side == "buy" and buy.in_amount == 10_000_000 and buy.out_amount > 0
    assert buy.price_impact_pct >= 0 and buy.request_id and buy.route_labels and buy.fee_bps >= 0
    sell = jup.ultra_order(HIGGS, SOL_MINT, buy.out_amount)
    assert sell.side == "sell" and 0 < sell.out_amount < buy.in_amount * 1.05
    assert jup.sol_price_usd() > 1
    recent = tokens_to_candidates(jup.tokens_recent(), 0.0, "jupiter_recent")
    assert recent and all(c.mint for c in recent)
    assert isinstance(jup.shield([HIGGS])[HIGGS], list)


# --------------------------------------------------------------------------- review fixes


@pytest.mark.parametrize("fields", [{}, {"priceImpactPct": "NaN"}, {"priceImpactPct": None, "priceImpact": "inf"}])
def test_missing_or_non_finite_impact_is_marked_unknown(fields):
    quote = quote_from_order(_order(**fields), "buy", quoted_at=1.0)
    assert quote.price_impact_pct == 0.0 and quote.price_impact_known is False
    assert quote_from_order(_order(priceImpactPct="-0.01"), "buy", quoted_at=1.0).price_impact_known is True


def test_ultra_execute_waits_long_enough_for_ultra_to_confirm(client, fake_http):
    """Ultra /execute polls for confirmation itself; a 10 s client timeout turned slow-but-landed swaps
    into 'unknown' outcomes with estimated fills."""
    fake_http.register_fixture("/ultra/v1/execute", "jup_ultra_execute_success_synthetic", method="POST")
    client.ultra_execute("SIGNED_B64", "req-1")
    assert fake_http.calls[0].timeout >= 30


@pytest.mark.parametrize("body", [{"error": "internal: shield temporarily unavailable"}, {"warnings": None},
                                  {"warnings": []}, []])
def test_shield_without_a_warnings_object_fails_closed(client, fake_http, body):
    fake_http.register("/ultra/v1/shield", body)
    with pytest.raises(JupiterError, match="warnings"):
        client.shield([HIGGS])


def test_shield_with_an_empty_warnings_object_is_a_clean_answer(client, fake_http):
    fake_http.register("/ultra/v1/shield", {"warnings": {}})
    assert client.shield([HIGGS]) == {HIGGS: []}
