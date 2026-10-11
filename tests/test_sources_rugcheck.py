"""RugCheck client: retry-later mapping, AMM/curve exclusion, insider networks, LP lock."""

from __future__ import annotations

import pytest

from nightcrawler.http import HttpClient, HttpError
from nightcrawler.sources.rugcheck import ReportUnavailable, RugCheckClient, RugReport, parse_report

GARY = "8ZCmwpW3MtC5UpNcZf7U4HMvRNTo71syU11BDiAFpump"
GARY_POOL = "2uZuTQEjcXcR1ESwMdGTpqEwM5PCekEwrSNVRPc1EhS1"
RISKY = "EDQRk4ETkyb4qkcGfeVMxK3FsFXava7Q3HFxmpJXpump"
RISKY_CURVE = "EA2y1S4Up5KerH2Vn2arxcwsGt84R38KQEyb3a3UbG5y"
BASE = "https://api.rugcheck.xyz/v1"

#: Trimmed from the live report of HMYd9tosnUXuNHmq7pXmoePRVBLBBjA3JBfydq6upump (2026-10-08): the
#: biggest "network" claims ~207 % of supply, so the derived share must be clamped.
LIVE_INSIDER_SAMPLE = {
    "mint": "HMYd9tosnUXuNHmq7pXmoePRVBLBBjA3JBfydq6upump",
    "token": {"supply": 989097105537566, "decimals": 6},
    "graphInsidersDetected": 263,
    "insiderNetworks": [
        {"id": "loud-sepia-alpaca", "size": 254, "type": "transfer", "tokenAmount": 2064855283515594,
         "currentHolding": 2049557357015376, "activeAccounts": 254},
        {"id": "vivid-aqua-woodpecker", "size": 7, "type": "transfer", "tokenAmount": 34740826897681,
         "currentHolding": 34740826897681, "activeAccounts": 7},
    ],
}


@pytest.fixture
def client(http_client: HttpClient) -> RugCheckClient:
    return RugCheckClient(http_client)


# --------------------------------------------------------------------------- client


def test_report_returns_raw_json(client, fake_http, load_fixture):
    fake_http.register_fixture(f"/tokens/{GARY}/report", "rugcheck_report")

    assert client.report(GARY) == load_fixture("rugcheck_report")
    assert fake_http.calls[0].url == f"{BASE}/tokens/{GARY}/report"


def test_report_too_new_raises_report_unavailable_without_retry(client, fake_http):
    fake_http.register_fixture("/report", "rugcheck_report_unavailable_400", status=400)

    with pytest.raises(ReportUnavailable) as info:
        client.report("NEWMINT")

    assert info.value.mint == "NEWMINT" and info.value.detail == "unable to generate report"
    assert len(fake_http.calls) == 1


@pytest.mark.parametrize("status", [400, 404])  # live 2026-10-08: /report on a 6 s old mint -> 400 "not found"
def test_report_not_indexed_yet_raises_report_unavailable(client, fake_http, status):
    fake_http.register_fixture("/report", "rugcheck_report_not_found_400", status=status)

    with pytest.raises(ReportUnavailable, match="not found") as info:
        client.report("FRESH")
    assert info.value.detail == "not found" and len(fake_http.calls) == 1


def test_report_empty_body_raises_report_unavailable(client, fake_http):
    fake_http.register("/report", None)

    with pytest.raises(ReportUnavailable, match="empty report"):
        client.report("M")


def test_report_other_400_is_an_http_error(client, fake_http):
    fake_http.register("/report", {"error": "invalid mint address"}, status=400)

    with pytest.raises(HttpError) as info:
        client.report("bad")
    assert info.value.status == 400 and not isinstance(info.value, ReportUnavailable)


def test_report_400_text_body_mentioning_not_ready_is_mapped(client, fake_http):
    fake_http.register("/report", "Unable to generate report (try later)", status=400)

    with pytest.raises(ReportUnavailable):
        client.report("M")


def test_report_server_error_raises_http_error_after_retries(client, fake_http):
    fake_http.register("/report", {"error": "boom"}, status=502)

    with pytest.raises(HttpError):
        client.report("M")
    assert len(fake_http.calls) == 5


def test_summary_uses_the_same_error_mapping(client, fake_http, load_fixture):
    fake_http.register_fixture(f"/tokens/{GARY}/report/summary", "rugcheck_summary")
    fake_http.register_fixture("/tokens/NEW/report/summary", "rugcheck_report_unavailable_400", status=400)

    assert client.summary(GARY) == load_fixture("rugcheck_summary")
    with pytest.raises(ReportUnavailable):
        client.summary("NEW")


def test_report_parsed_falls_back_to_requested_mint(client, fake_http):
    fake_http.register("/report", {"token": {"supply": "1000", "decimals": 6}})

    rep = client.report_parsed("REQUESTED")

    assert isinstance(rep, RugReport) and rep.mint == "REQUESTED" and rep.supply == 1000


# --------------------------------------------------------------------------- parse_report


def test_parse_clean_report_excludes_the_pool_account(load_fixture):
    rep = parse_report(load_fixture("rugcheck_report"))

    pool_holder = rep.top_holders[0]
    assert pool_holder["owner"] == GARY_POOL and pool_holder["excluded"] and pool_holder["excluded_reason"] == "market"
    counted = [h for h in rep.top_holders if not h["excluded"]]
    assert all(h["owner"] != GARY_POOL for h in counted)
    assert rep.top10_pct == pytest.approx(0.25816173798921577 + 0.22341887357195106)
    assert rep.max_holder_pct == pytest.approx(0.25816173798921577)
    assert rep.insider_holder_pct == 0.0 and isinstance(rep.insider_holder_pct, float)
    assert (rep.mint, rep.supply, rep.decimals) == (GARY, 994092192206734, 6)
    assert rep.mint_authority is None and rep.freeze_authority is None and rep.mutable_metadata is False
    assert rep.extensions == ["metadataPointer", "tokenMetadata"] and rep.default_account_state is None
    assert rep.risks == [] and rep.danger_risks == [] and rep.warn_risks == []
    assert (rep.score, rep.score_normalised, rep.rugged) == (1, 1.0, False)
    assert rep.creator == "G7YaEzm4c1aMQcn1SQLUPHYnoUNE7bG4XwQ4nxyYydn" and rep.creator_pct == 0.0
    assert rep.creator_tokens_count is None and rep.creator_rug_history is False
    assert rep.total_holders == 3090 and rep.graph_insiders == 0
    assert rep.insider_networks == [] and rep.insider_network_pct is None
    assert rep.markets == [{"pubkey": GARY_POOL, "market_type": "pump_fun_amm", "lp_locked_pct": 100.0,
                            "lp_locked_usd": pytest.approx(74193.83161390272)}]
    assert rep.lp_locked_pct == 100.0  # pump_fun_amm is the graduated AMM, not a curve
    assert rep.total_market_liquidity_usd == pytest.approx(74193.83161390272)
    assert rep.known_accounts[GARY_POOL]["type"] == "AMM"


def test_parse_risky_report_flags_danger_and_excludes_curve(load_fixture):
    rep = parse_report(load_fixture("rugcheck_report_risky"))

    curve = next(h for h in rep.top_holders if h["owner"] == RISKY_CURVE)
    assert curve["excluded"] and curve["pct"] == pytest.approx(50.03368985861175)
    assert rep.max_holder_pct == pytest.approx(49.8572270024016)
    assert rep.top10_pct == pytest.approx(49.8572270024016 + 0.10908313898665)
    assert rep.danger_risks == ["Creator history of rugged tokens", "Single holder ownership"]
    assert rep.risks[1] == {"name": "Single holder ownership", "level": "danger", "score": 4985.0,
                            "value": "49.86%", "description": "One user holds a large amount of the token supply"}
    assert rep.creator_rug_history is True and rep.creator_tokens_count == 3
    assert rep.creator_pct == pytest.approx(2181662779733 / 2e15 * 100)
    assert rep.score_normalised == 62.0 and rep.total_holders == 3
    assert rep.lp_locked_pct is None  # only a pump_fun bonding curve: no AMM LP to judge


def test_parse_report_excludes_vaults_vault_owners_and_lockers_but_not_creator():
    report = {
        "token": {"supply": 1000, "decimals": 0},
        "markets": [{"pubkey": "POOL", "marketType": "raydium", "liquidityA": "VAULT_A", "liquidityB": "VAULT_B",
                     "liquidityAAccount": {"owner": "AMM_AUTHORITY"}}],
        "knownAccounts": {"LOCKER_OWNER": {"name": "Streamflow", "type": "LOCKER"},
                          "CREATOR": {"name": "Creator", "type": "CREATOR"}, "BAD": "not-a-dict"},
        "topHolders": [
            {"address": "VAULT_A", "owner": "SOMEONE", "pct": 40},
            {"address": "ACC1", "owner": "AMM_AUTHORITY", "pct": 20},
            {"address": "ACC2", "owner": "LOCKER_OWNER", "pct": 15},
            {"address": "ACC3", "owner": "CREATOR", "pct": "4.5", "insider": True},
            {"address": "ACC4", "owner": "W1", "pct": 3, "insider": "true"},
            {"address": "ACC5", "owner": "W2", "pct": None},
        ],
    }

    rep = parse_report(report)

    reasons = {h["address"]: h["excluded_reason"] for h in rep.top_holders}
    assert reasons == {"VAULT_A": "market vault", "ACC1": "market vault owner", "ACC2": "locker",
                       "ACC3": None, "ACC4": None, "ACC5": None}
    assert rep.top10_pct == pytest.approx(7.5) and rep.max_holder_pct == 4.5
    assert rep.insider_holder_pct == pytest.approx(7.5)
    assert [h["pct"] for h in rep.top_holders] == [40, 20, 15, 4.5, 3, 0.0]  # sorted, missing pct -> 0
    assert "BAD" not in rep.known_accounts


def test_parse_report_top10_counts_only_ten_largest_counted_holders():
    holders = [{"address": f"A{i}", "owner": f"W{i}", "pct": 2.0} for i in range(15)]

    rep = parse_report({"topHolders": holders})

    assert rep.top10_pct == pytest.approx(20.0)


def test_parse_report_all_holders_excluded_gives_zero_not_none():
    rep = parse_report({"markets": [{"pubkey": "POOL"}], "topHolders": [{"owner": "POOL", "pct": 90}]})

    assert (rep.top10_pct, rep.max_holder_pct, rep.insider_holder_pct) == (0.0, 0.0, 0.0)


def test_parse_report_insider_networks_are_clamped_to_100_percent():
    rep = parse_report(LIVE_INSIDER_SAMPLE)

    assert rep.graph_insiders == 263
    big, small = rep.insider_networks
    assert big["pct"] == pytest.approx(207.21, abs=0.01)  # what RugCheck really reports
    assert small == {"id": "vivid-aqua-woodpecker", "type": "transfer", "size": 7, "active_accounts": 7,
                     "token_amount": 34740826897681, "current_holding": 34740826897681,
                     "pct": pytest.approx(3.5124, abs=1e-3)}
    assert rep.insider_network_pct == 100.0


def test_parse_report_insider_network_pct_sums_and_falls_back_to_token_amount():
    rep = parse_report({"token": {"supply": 1_000_000}, "insiderNetworks": [
        {"id": "a", "tokenAmount": 50_000, "currentHolding": 20_000},  # current holding preferred: 2 %
        {"id": "b", "tokenAmount": 30_000},                              # fallback: 3 %
        {"id": "c"},                                                     # unknown amount: ignored
    ]})

    assert [n["pct"] for n in rep.insider_networks] == [pytest.approx(2.0), pytest.approx(3.0), None]
    assert rep.insider_network_pct == pytest.approx(5.0)


def test_parse_report_insider_networks_without_supply_are_unknown():
    rep = parse_report({"insiderNetworks": [{"id": "a", "tokenAmount": 5}]})

    assert rep.insider_networks[0]["pct"] is None and rep.insider_network_pct is None


@pytest.mark.parametrize("raw,expected", [
    ("frozen", "frozen"), ("Initialized", "initialized"), ({"accountState": "frozen"}, "frozen"),
    ({"state": 2}, "frozen"), (1, "initialized"), ("2", "frozen"), (True, "unknown"),
    (None, None), (False, None), ({}, None),
])
def test_parse_report_default_account_state_shapes(raw, expected):
    rep = parse_report({"token_extensions": {"defaultAccountState": raw}})

    assert rep.default_account_state == expected
    assert ("defaultAccountState" in rep.extensions) is bool(raw)


def test_parse_report_lists_only_present_extensions():
    rep = parse_report({"token_extensions": {
        "transferFeeConfig": {"withheldAmount": 0}, "permanentDelegate": None, "nonTransferable": True,
        "transferHook": False, "metadataPointer": {"authority": None},
    }})

    assert rep.extensions == ["transferFeeConfig", "nonTransferable", "metadataPointer"]


def test_parse_report_lp_lock_uses_largest_non_curve_market():
    rep = parse_report({"markets": [
        {"pubkey": "CURVE", "marketType": "pump_fun", "lp": {"lpLockedPct": 100, "lpLockedUSD": 1e9}},
        {"pubkey": "SMALL", "marketType": "raydium", "lp": {"lpLockedPct": 10, "lpLockedUSD": 1000}},
        {"pubkey": "BIG", "marketType": "meteora_damm_v2", "lp": {"lpLockedPct": "95.5", "lpLockedUSD": "5000"}},
        {"pubkey": "UNKNOWN", "marketType": "orca", "lp": {"lpLockedUSD": 1e8}},
        {"pubkey": "DBC", "marketType": "meteora_dbc", "lp": {"lpLockedPct": 100, "lpLockedUSD": 1e9}},
        {"pubkey": "LL", "marketType": "raydium_launchlab", "lp": {"lpLockedPct": 100, "lpLockedUSD": 1e9}},
    ]})

    assert rep.lp_locked_pct == 95.5
    assert [m["pubkey"] for m in rep.markets] == ["CURVE", "SMALL", "BIG", "UNKNOWN", "DBC", "LL"]


def test_parse_report_authorities_fall_back_to_token_section():
    rep = parse_report({"mintAuthority": None, "token": {"mintAuthority": "AUTH", "freezeAuthority": "FRZ"}})

    assert rep.mint_authority == "AUTH" and rep.freeze_authority == "FRZ"


@pytest.mark.parametrize("report", [
    {},
    {"token": "bad", "topHolders": "x", "markets": None, "risks": [None, 3, {"level": "DANGER"}],
     "token_extensions": [], "knownAccounts": [], "insiderNetworks": {}, "creatorTokens": "x",
     "rugged": "yes", "graphInsidersDetected": None, "tokenMeta": None},
])
def test_parse_report_never_raises_on_missing_or_malformed_fields(report):
    rep = parse_report(report, mint="FALLBACK")

    assert rep.mint == "FALLBACK"
    assert rep.top_holders == [] and rep.top10_pct is None and rep.max_holder_pct is None
    assert rep.extensions == [] and rep.markets == [] and rep.lp_locked_pct is None
    assert rep.graph_insiders == 0 and rep.creator_pct is None and rep.creator_tokens_count is None
    assert rep.rugged is (report.get("rugged") == "yes")


def test_parse_report_rugged_and_warn_levels():
    rep = parse_report({"rugged": True, "risks": [{"name": "Low liquidity", "level": "warn", "score": "100"},
                                                  {"name": "Mutable metadata", "level": "WARN"}]})

    assert rep.rugged is True and rep.warn_risks == ["Low liquidity", "Mutable metadata"]
    assert rep.danger_risks == [] and rep.risks[0]["score"] == 100.0


# --------------------------------------------------------------------------- live


@pytest.mark.live
def test_live_rugcheck_smoke():
    rep = RugCheckClient(HttpClient()).report_parsed(GARY)

    assert rep.mint == GARY and rep.supply and rep.decimals == 6
    assert rep.mint_authority is None and rep.freeze_authority is None
    assert rep.top_holders and any(h["excluded"] for h in rep.top_holders)  # the AMM pool holds tokens
    assert rep.top10_pct is not None and 0 <= rep.top10_pct <= 100
    assert rep.markets and rep.lp_locked_pct is not None
