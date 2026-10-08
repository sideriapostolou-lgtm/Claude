"""Cocoon: every hard-fail rule, every warning, fail-closed degradation and caching (offline).

The unit tests feed hand-built :class:`RugReport` objects whose values are
copied from ``tests/fixtures/rugcheck_report*.json`` so they do not depend on
O1's parser; ``test_fixture_reports_through_real_clients`` runs the same
fixtures through O1's real clients over FakeHttp.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

import pytest

from fakes import FakeClock
from nightcrawler.cocoon import UNAVAILABLE_CACHE_S, Cocoon
from nightcrawler.http import HttpError
from nightcrawler.models import SafetyReport, TokenCandidate
from nightcrawler.sources import Sources, build_sources
from nightcrawler.sources.rugcheck import ReportUnavailable, RugReport
from nightcrawler.sources.solana_rpc import RpcError

MIN = 60.0

# ---- rugcheck_report.json: "Gary the Cat", graduated to PumpSwap, clean ----
CLEAN_MINT = "8ZCmwpW3MtC5UpNcZf7U4HMvRNTo71syU11BDiAFpump"
CLEAN_POOL = "2uZuTQEjcXcR1ESwMdGTpqEwM5PCekEwrSNVRPc1EhS1"  # pump_fun_amm market, also topHolders[0].owner
CLEAN_CREATOR = "G7YaEzm4c1aMQcn1SQLUPHYnoUNE7bG4XwQ4nxyYydn"
HOLDER_A = "JGF53sgRBQZLNaqbqPeD3NQaRErRDSY2ibc72GD8wMc"
HOLDER_B = "Gpfac83Y3DF67YjWwvvY3tPboi7J7gVRyds5KLz1YFwp"

# ---- rugcheck_report_risky.json: "NWO", still on the pump.fun curve ----
RISKY_MINT = "EDQRk4ETkyb4qkcGfeVMxK3FsFXava7Q3HFxmpJXpump"
RISKY_CURVE = "EA2y1S4Up5KerH2Vn2arxcwsGt84R38KQEyb3a3UbG5y"  # pump_fun market + knownAccounts AMM
RISKY_WHALE = "BwWK17cbHxwWBKZkUYvzxLcNQ1YVyaFezduWbtm2de6s"
RISKY_CREATOR = "7WKdcCiZ3yrutfGrShz35bmTc4Jk3sikaMzJLaxRpjkw"

ALL_RULES = {"mint_authority", "freeze_authority", "token2022_ext", "rugged", "rugcheck_danger", "top10",
             "single_holder", "creator_holding", "insiders", "serial_launcher", "shield", "lp_unlocked"}


def holder(owner: str, pct: float, *, excluded: str | None = None, insider: bool = False) -> dict[str, Any]:
    return {"address": f"acct-{owner[:8]}", "owner": owner, "pct": pct, "insider": insider,
            "excluded": excluded is not None, "excluded_reason": excluded}


def market(pubkey: str, market_type: str, lp_locked_pct: float | None, lp_locked_usd: float | None) -> dict[str, Any]:
    return {"pubkey": pubkey, "market_type": market_type, "lp_locked_pct": lp_locked_pct,
            "lp_locked_usd": lp_locked_usd}


def clean_report(**changes: Any) -> RugReport:
    """``rugcheck_report.json`` as O1's parse_report should normalize it (pool account excluded)."""
    rr = RugReport(
        mint=CLEAN_MINT, mint_authority=None, freeze_authority=None, mutable_metadata=False,
        supply=994092192206734, decimals=6, extensions=["metadataPointer", "tokenMetadata"],
        risks=[], danger_risks=[], warn_risks=[], score=1, score_normalised=1.0, rugged=False,
        creator=CLEAN_CREATOR, creator_pct=0.0, creator_tokens_count=None, creator_rug_history=False,
        total_holders=3090,
        top_holders=[holder(CLEAN_POOL, 5.436474347966708, excluded="market"),
                     holder(HOLDER_A, 0.25816173798921577), holder(HOLDER_B, 0.22341887357195106)],
        top10_pct=0.48158061156116683, max_holder_pct=0.25816173798921577, insider_holder_pct=0.0,
        graph_insiders=0, insider_networks=[], insider_network_pct=None,
        markets=[market(CLEAN_POOL, "pump_fun_amm", 100.0, 74193.83161390272)], lp_locked_pct=100.0,
        total_market_liquidity_usd=74193.83161390272,
    )
    return dataclasses.replace(rr, **changes)


def risky_report() -> RugReport:
    """``rugcheck_report_risky.json`` as O1's parse_report should normalize it (curve account excluded)."""
    danger = ["Creator history of rugged tokens", "Single holder ownership"]
    return RugReport(
        mint=RISKY_MINT, mutable_metadata=False, supply=2_000_000_000_000_000, decimals=6,
        extensions=["metadataPointer", "tokenMetadata"],
        risks=[{"name": n, "level": "danger"} for n in danger], danger_risks=danger, score=24186,
        score_normalised=62.0, creator=RISKY_CREATOR, creator_pct=0.10908313898665, creator_tokens_count=3,
        creator_rug_history=True, total_holders=3,
        top_holders=[holder(RISKY_CURVE, 50.03368985861175, excluded="market"),
                     holder(RISKY_WHALE, 49.8572270024016), holder(RISKY_CREATOR, 0.10908313898665)],
        top10_pct=49.96631014138825, max_holder_pct=49.8572270024016, insider_holder_pct=0.0,
        markets=[market(RISKY_CURVE, "pump_fun", 100.0, 677.7192136543553)], lp_locked_pct=None,
        total_market_liquidity_usd=677.7192136543553,
    )


def clean_mint_info(**changes: Any) -> dict[str, Any]:
    """``rpc_getAccountInfo_mint.json`` as O1's SolanaRpc.mint_info returns it."""
    info = {"mint": CLEAN_MINT, "mint_authority": None, "freeze_authority": None, "decimals": 6,
            "supply": 994092192206734, "program": "spl-token-2022",
            "extensions": ["metadataPointer", "tokenMetadata"],
            "extension_states": {"metadataPointer": {}, "tokenMetadata": {}}}
    info.update(changes)
    return info


def clean_candidate(**changes: Any) -> TokenCandidate:
    """Jupiter tokens/v2 search fixture for the same token."""
    c = TokenCandidate(mint=CLEAN_MINT, symbol="Gary", pool=CLEAN_POOL, dex="pumpswap", graduated=True,
                       dev=CLEAN_CREATOR, holder_count=2988, mcap_usd=603_658.0, liquidity_usd=33_279.0,
                       audit={"mintAuthorityDisabled": True, "freezeAuthorityDisabled": True,
                              "topHoldersPercentage": 2.15, "devMigrations": 1, "devMints": 2},
                       socials={"twitter": "https://x.com/i/communities/1"}, sources=["jupiter_recent"])
    return dataclasses.replace(c, **changes)


class FakeRugCheck:
    def __init__(self, report: Any = None) -> None:
        self.report = report
        self.error: BaseException | None = None
        self.calls: list[str] = []

    def report_parsed(self, mint: str) -> Any:
        self.calls.append(mint)
        if self.error is not None:
            raise self.error
        return self.report


class FakeRpc:
    def __init__(self, info: dict[str, Any] | None) -> None:
        self.info = info
        self.error: BaseException | None = None
        self.calls: list[str] = []

    def mint_info(self, mint: str) -> dict[str, Any] | None:
        self.calls.append(mint)
        if self.error is not None:
            raise self.error
        return self.info


class FakeShield:
    def __init__(self) -> None:
        self.warnings: dict[str, list[dict[str, Any]]] = {}
        self.error: BaseException | None = None
        self.calls: list[list[str]] = []

    def shield(self, mints: list[str]) -> dict[str, list[dict[str, Any]]]:
        self.calls.append(list(mints))
        if self.error is not None:
            raise self.error
        return {m: list(self.warnings.get(m, [])) for m in mints}


@dataclasses.dataclass
class World:
    rugcheck: FakeRugCheck
    rpc: FakeRpc
    jupiter: FakeShield
    clock: FakeClock
    cocoon: Cocoon

    def calls(self) -> tuple[int, int, int]:
        return len(self.rugcheck.calls), len(self.rpc.calls), len(self.jupiter.calls)


def build_world(settings, clock: FakeClock, report: Any = None, info: dict[str, Any] | None = None) -> World:
    rugcheck = FakeRugCheck(report if report is not None else clean_report())
    rpc = FakeRpc(info if info is not None else clean_mint_info())
    jupiter = FakeShield()
    sources = Sources(dexscreener=None, gecko=None, rugcheck=rugcheck,  # type: ignore[arg-type]
                      jupiter=jupiter, rpc=rpc)
    return World(rugcheck, rpc, jupiter, clock, Cocoon(sources, settings, clock))


@pytest.fixture
def world(settings, fake_clock: FakeClock) -> World:
    return build_world(settings, fake_clock)


def rule_ids(report: SafetyReport) -> set[str]:
    return {m.group(1) for r in report.hard_fail_reasons if (m := re.match(r"\[(\w+)\]", r))}


def warning_ids(report: SafetyReport) -> set[str]:
    return {m.group(1) for r in report.warnings if (m := re.match(r"\[(\w+)\]", r))}


def http_error(status: int = 503) -> HttpError:
    return HttpError(f"HTTP {status}", url="https://example.invalid/x", status=status, retryable=True)


# --------------------------------------------------------------------------- the two real fixtures


def test_clean_fixture_passes_with_full_evidence(world: World) -> None:
    report = world.cocoon.check(clean_candidate())
    assert report.passed is True
    assert report.hard_fail_reasons == [] and report.unverified == []
    assert report.checked_at == world.clock.now()
    assert world.calls() == (1, 1, 1)
    assert report.creator == CLEAN_CREATOR
    assert report.top_holders == [HOLDER_A, HOLDER_B]  # the PumpSwap pool account is not a holder
    assert report.insiders == []
    m = report.metrics
    assert m["top10_pct"] == pytest.approx(0.4816, abs=1e-4) and m["max_holder_pct"] == pytest.approx(0.2582, abs=1e-4)
    assert (m["creator_pct"], m["insider_pct"], m["graph_insiders"], m["dev_mints"]) == (0.0, 0.0, 0, 2)
    assert (m["lp_locked_pct"], m["holder_count"], m["rugcheck_score_normalised"]) == (100.0, 3090, 1.0)
    assert (m["mint_authority"], m["freeze_authority"], m["program"]) == (None, None, "spl-token-2022")
    assert m["extensions"] == ["metadataPointer", "tokenMetadata"] and m["shield_warnings"] == []
    assert report.warnings == []


def test_risky_fixture_fails_for_the_right_reasons(settings, fake_clock) -> None:
    w = build_world(settings, fake_clock, report=risky_report())
    candidate = TokenCandidate(mint=RISKY_MINT, symbol="NWO", pool=RISKY_CURVE, dex="pumpfun", graduated=False,
                               audit={"mintAuthorityDisabled": True, "freezeAuthorityDisabled": True, "devMints": 3})
    report = w.cocoon.check(candidate)
    assert report.passed is False and report.unverified == []
    assert rule_ids(report) == {"rugcheck_danger", "top10", "single_holder", "serial_launcher"}
    assert "[top10] top-10 holders own 50.0% (max 30%)" in report.hard_fail_reasons
    assert "[single_holder] one holder owns 49.9% (max 10%)" in report.hard_fail_reasons
    assert report.metrics["creator_pct"] == pytest.approx(0.109, abs=1e-3)  # creator sold almost all: not a fail
    assert report.metrics["lp_locked_pct"] is None  # still on the curve: the LP rule does not apply
    assert report.top_holders == [RISKY_WHALE, RISKY_CREATOR]  # curve account excluded
    assert w.calls() == (1, 0, 0)  # RugCheck already decided: RPC and Shield budgets are spared


# --------------------------------------------------------------------------- hard-fail rules, one at a time


def _rug(**changes: Any):
    return lambda w, c: setattr(w.rugcheck, "report", clean_report(**changes)) or c


def _rpc(**changes: Any):
    return lambda w, c: setattr(w.rpc, "info", clean_mint_info(**changes)) or c


def _audit(**changes: Any):
    return lambda w, c: dataclasses.replace(c, audit={**c.audit, **changes})


def _shield(*warnings: dict[str, Any]):
    return lambda w, c: w.jupiter.warnings.update({CLEAN_MINT: list(warnings)}) or c


def _cand(**changes: Any):
    return lambda w, c: dataclasses.replace(c, **changes)


def _ext(name: str, state: dict[str, Any] | None = None):
    states = {"metadataPointer": {}, "tokenMetadata": {}, name: state or {}}
    return _rpc(extensions=["metadataPointer", "tokenMetadata", name], extension_states=states)


AMM_POOL = "AmmPool1111111111111111111111111111111111111"
DLMM_POOL = "DlmmPool111111111111111111111111111111111111"

HARD_FAIL_CASES = [
    ("mint_authority/rugcheck", _rug(mint_authority="TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM"), "mint_authority"),
    ("mint_authority/rpc", _rpc(mint_authority="TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM"), "mint_authority"),
    ("mint_authority/jupiter_audit", _audit(mintAuthorityDisabled=False), "mint_authority"),
    ("freeze_authority/rugcheck", _rug(freeze_authority="FrzAuth1111111111111111111111111111111111111"),
     "freeze_authority"),
    ("freeze_authority/rpc", _rpc(freeze_authority="FrzAuth1111111111111111111111111111111111111"),
     "freeze_authority"),
    ("freeze_authority/jupiter_audit", _audit(freezeAuthorityDisabled=False), "freeze_authority"),
    ("token2022/transferFeeConfig", _ext("transferFeeConfig"), "token2022_ext"),
    ("token2022/permanentDelegate", _ext("permanentDelegate"), "token2022_ext"),
    ("token2022/transferHook", _ext("transferHook"), "token2022_ext"),
    ("token2022/pausableConfig", _ext("pausableConfig"), "token2022_ext"),
    ("token2022/nonTransferable", _ext("nonTransferable"), "token2022_ext"),
    ("token2022/defaultAccountState_frozen", _ext("defaultAccountState", {"accountState": "frozen"}),
     "token2022_ext"),
    ("token2022/defaultAccountState_unreadable", _ext("defaultAccountState", {}), "token2022_ext"),
    ("token2022/rugcheck_extension", _rug(extensions=["metadataPointer", "permanentDelegate"]), "token2022_ext"),
    ("token2022/rugcheck_default_frozen", _rug(extensions=["defaultAccountState"], default_account_state="frozen"),
     "token2022_ext"),
    ("token2022/rugcheck_default_unknown", _rug(extensions=["defaultAccountState"], default_account_state="unknown"),
     "token2022_ext"),
    ("rugged", _rug(rugged=True), "rugged"),
    ("rugcheck_danger", _rug(danger_risks=["Freeze Authority still enabled"]), "rugcheck_danger"),
    ("top10/over", _rug(top10_pct=30.01), "top10"),
    ("top10/unknown", _rug(top10_pct=None, max_holder_pct=None), "top10"),
    ("single_holder", _rug(top10_pct=15.0, max_holder_pct=10.01), "single_holder"),
    ("creator_holding/rugcheck", _rug(creator_pct=5.01), "creator_holding"),
    ("creator_holding/jupiter_fallback", lambda w, c: _audit(devBalancePercentage=7.5)(w, _rug(creator_pct=None)(w, c)),
     "creator_holding"),
    ("insiders/network_share", _rug(graph_insiders=5, insider_network_pct=15.01), "insiders"),
    ("insiders/holder_share_fallback", _rug(graph_insiders=9, insider_network_pct=None, insider_holder_pct=20.0),
     "insiders"),
    ("serial_launcher/jupiter_dev_mints", _audit(devMints=21), "serial_launcher"),
    ("serial_launcher/rug_history", _rug(creator_rug_history=True), "serial_launcher"),
    ("shield/warning", _shield({"type": "HAS_FREEZE_AUTHORITY", "message": "m", "severity": "warning"}), "shield"),
    ("shield/critical", _shield({"type": "1%_TRANSFER_FEES", "message": "m", "severity": "critical"}), "shield"),
    ("lp_unlocked/main_pool", _rug(markets=[market(CLEAN_POOL, "pump_fun_amm", 50.0, 37_000.0)]), "lp_unlocked"),
    ("lp_unlocked/main_pool_unknown", _rug(markets=[market(CLEAN_POOL, "pump_fun_amm", None, None)]),
     "lp_unlocked"),
    ("lp_unlocked/concentrated_liquidity_main_pool",
     lambda w, c: _cand(pool=DLMM_POOL)(w, _rug(markets=[market(DLMM_POOL, "meteoraDlmm", 0.0, 0.0),
                                                          market(AMM_POOL, "meteora_damm_v2", 100.0, 150.0)],
                                                 lp_locked_pct=100.0)(w, c)), "lp_unlocked"),
    ("lp_unlocked/unmatched_pool_uses_best_amm",
     lambda w, c: _cand(pool=None)(w, _rug(markets=[market(AMM_POOL, "raydium_cpmm", 80.0, 9_000.0)],
                                            lp_locked_pct=80.0)(w, c)), "lp_unlocked"),
    ("lp_unlocked/amm_without_known_lock",
     lambda w, c: _cand(pool=None)(w, _rug(markets=[market(AMM_POOL, "raydium_cpmm", None, None)],
                                            lp_locked_pct=None)(w, c)), "lp_unlocked"),
]


@pytest.mark.parametrize("mutate,expected", [c[1:] for c in HARD_FAIL_CASES], ids=[c[0] for c in HARD_FAIL_CASES])
def test_each_hard_fail_rule(world: World, mutate, expected: str) -> None:
    candidate = mutate(world, clean_candidate())
    report = world.cocoon.check(candidate)
    assert report.passed is False
    assert rule_ids(report) == {expected}
    assert report.unverified == []
    (reason,) = report.hard_fail_reasons
    assert reason.startswith(f"[{expected}] ") and len(reason) > len(expected) + 3


PASS_CASES = [
    ("top10_at_limit", _rug(top10_pct=30.0)),
    ("single_holder_at_limit", _rug(top10_pct=20.0, max_holder_pct=10.0)),
    ("creator_at_limit", _rug(creator_pct=5.0)),
    ("insider_share_at_limit", _rug(graph_insiders=5, insider_network_pct=15.0)),
    ("insiders_below_graph_threshold", _rug(graph_insiders=4, insider_network_pct=60.0)),
    ("dev_mints_at_limit", _audit(devMints=20)),
    ("shield_info_only", _shield({"type": "NOT_VERIFIED", "message": "m", "severity": "info"},
                                 {"type": "HAS_MINT_AUTHORITY", "message": "m", "severity": "info"})),
    ("default_account_state_initialized", _ext("defaultAccountState", {"accountState": "initialized"})),
    ("rugcheck_default_initialized", _rug(extensions=["defaultAccountState"], default_account_state="initialized")),
    ("harmless_extensions", _ext("interestBearingConfig")),
    ("lp_at_limit", _rug(markets=[market(CLEAN_POOL, "pump_fun_amm", 90.0, 60_000.0)])),
    ("curve_pool_rule_not_applicable",
     lambda w, c: _cand(pool=RISKY_CURVE, dex="pumpfun", graduated=False)(
         w, _rug(markets=[market(RISKY_CURVE, "pump_fun", None, None)], lp_locked_pct=None)(w, c))),
    ("curve_only_markets_unmatched_pool",
     lambda w, c: _cand(pool=None)(w, _rug(markets=[market(RISKY_CURVE, "pump_fun", 0.0, 0.0)],
                                            lp_locked_pct=None)(w, c))),
    ("main_pool_locked_beats_unlocked_side_pool",
     _rug(markets=[market(DLMM_POOL, "meteoraDlmm", 0.0, 0.0), market(CLEAN_POOL, "pump_fun_amm", 100.0, 70_000.0)],
          lp_locked_pct=100.0)),
]


@pytest.mark.parametrize("mutate", [c[1] for c in PASS_CASES], ids=[c[0] for c in PASS_CASES])
def test_boundaries_and_non_fatal_evidence_pass(world: World, mutate) -> None:
    report = world.cocoon.check(mutate(world, clean_candidate()))
    assert report.hard_fail_reasons == []
    assert report.passed is True


def test_insider_wallets_are_handed_to_the_radar(world: World) -> None:
    world.rugcheck.report = clean_report(top_holders=[
        holder(CLEAN_POOL, 5.4, excluded="market"), holder(HOLDER_B, 0.3, insider=True), holder(HOLDER_A, 0.9),
        holder(HOLDER_B, 0.1, insider=True), holder("LockerVault1111111111111111111111111111111", 3.0,
                                                    excluded="locker", insider=True)])
    report = world.cocoon.check(clean_candidate())
    assert report.top_holders == [HOLDER_A, HOLDER_B]  # sorted by pct, de-duplicated, exclusions dropped
    assert report.insiders == [HOLDER_B]


def test_short_circuit_after_the_free_jupiter_audit(world: World) -> None:
    report = world.cocoon.check(clean_candidate(audit={"devMints": 7306}))
    assert rule_ids(report) == {"serial_launcher"} and world.calls() == (0, 0, 0)
    assert report.creator == CLEAN_CREATOR  # from the candidate's dev field


def test_short_circuit_after_the_rpc(world: World) -> None:
    world.rpc.info = clean_mint_info(freeze_authority="FrzAuth1111111111111111111111111111111111111")
    world.cocoon.check(clean_candidate())
    assert world.calls() == (1, 1, 0)


# --------------------------------------------------------------------------- warnings


WARNING_CASES = [
    ("mutable_metadata", _rug(mutable_metadata=True)),
    ("no_socials", _cand(socials={})),
    ("paid_promo", _cand(paid_promo=True)),
    ("low_holders", _rug(total_holders=99)),
    ("holders_unknown", lambda w, c: _cand(holder_count=None)(w, _rug(total_holders=None)(w, c))),
    ("rugcheck_warn", _rug(warn_risks=["Low Liquidity"])),
    ("creator_unknown", _rug(creator_pct=None)),
    ("insiders_unknown", _rug(graph_insiders=6, insider_network_pct=None, insider_holder_pct=None)),
]


@pytest.mark.parametrize("mutate,expected", [(c[1], c[0]) for c in WARNING_CASES], ids=[c[0] for c in WARNING_CASES])
def test_each_warning_is_not_fatal(world: World, mutate, expected: str) -> None:
    report = world.cocoon.check(mutate(world, clean_candidate()))
    assert report.passed is True
    assert warning_ids(report) == {expected}


def test_warning_texts(world: World) -> None:
    world.rugcheck.report = clean_report(total_holders=42, warn_risks=["Low Liquidity"], mutable_metadata=True)
    report = world.cocoon.check(clean_candidate(socials={}, paid_promo=True))
    assert report.warnings == ["[mutable_metadata] token metadata can still be changed",
                               "[rugcheck_warn] Low Liquidity",
                               "[no_socials] no website/twitter/telegram listed",
                               "[paid_promo] paid DexScreener promotion (boost/profile)",
                               "[low_holders] 42 holders (< 100)"]


def test_holder_count_falls_back_to_the_candidate(world: World) -> None:
    world.rugcheck.report = clean_report(total_holders=None)
    report = world.cocoon.check(clean_candidate(holder_count=2988))
    assert report.metrics["holder_count"] == 2988 and report.warnings == []


# --------------------------------------------------------------------------- fail closed


DEGRADED_CASES = [
    ("rugcheck_http", lambda w: setattr(w.rugcheck, "error", http_error()), "source unavailable: rugcheck",
     "rugcheck", (1, 0, 0)),
    ("rugcheck_not_ready",
     lambda w: setattr(w.rugcheck, "error", ReportUnavailable(CLEAN_MINT, "unable to generate report")),
     "source unavailable: rugcheck (not ready)", "rugcheck", (1, 0, 0)),
    ("rpc_error", lambda w: setattr(w.rpc, "error", RpcError(-32005, "node is behind", "getAccountInfo")),
     "source unavailable: rpc", "rpc", (1, 1, 0)),
    ("rpc_http", lambda w: setattr(w.rpc, "error", http_error(429)), "source unavailable: rpc", "rpc", (1, 1, 0)),
    ("rpc_mint_missing", lambda w: setattr(w.rpc, "info", None), "source unavailable: rpc (mint account not found)",
     "rpc", (1, 1, 0)),
    ("shield_http", lambda w: setattr(w.jupiter, "error", http_error()), "source unavailable: jupiter_shield",
     "jupiter_shield", (1, 1, 1)),
]


@pytest.mark.parametrize("breakage,reason,source,calls", [c[1:] for c in DEGRADED_CASES],
                         ids=[c[0] for c in DEGRADED_CASES])
def test_unavailable_source_fails_closed(settings, fake_clock, breakage, reason, source, calls) -> None:
    w = build_world(settings, fake_clock)
    breakage(w)
    report = w.cocoon.check(clean_candidate())
    assert report.passed is False
    assert report.hard_fail_reasons == [reason]
    assert report.unverified == [source]
    assert w.calls() == calls


def test_unexpected_error_fails_closed(world: World) -> None:
    world.rugcheck.report = object()  # not a RugReport -> AttributeError inside the rules
    report = world.cocoon.check(clean_candidate())
    assert report.passed is False and report.hard_fail_reasons == ["error: AttributeError"]
    assert report.mint == CLEAN_MINT and report.checked_at == world.clock.now()


# --------------------------------------------------------------------------- cache


def test_reports_are_cached_for_cocoon_cache_min(world: World) -> None:
    first = world.cocoon.check(clean_candidate())
    world.clock.advance(30 * MIN - 1)
    assert world.cocoon.check(clean_candidate()) is first and world.calls() == (1, 1, 1)
    assert world.cocoon.cached(CLEAN_MINT) is first
    world.clock.advance(1)
    assert world.cocoon.cached(CLEAN_MINT) is None
    assert world.cocoon.check(clean_candidate()) is not first and world.calls() == (2, 2, 2)


def test_failed_reports_are_cached_too(settings, fake_clock) -> None:
    w = build_world(settings, fake_clock, report=risky_report())
    w.cocoon.check(TokenCandidate(mint=RISKY_MINT))
    fake_clock.advance(29 * MIN)
    w.cocoon.check(TokenCandidate(mint=RISKY_MINT))
    assert len(w.rugcheck.calls) == 1


def test_force_and_invalidate_bypass_the_cache(world: World) -> None:
    world.cocoon.check(clean_candidate())
    world.cocoon.check(clean_candidate(), force=True)
    assert world.calls() == (2, 2, 2)
    world.cocoon.invalidate(CLEAN_MINT)
    world.cocoon.invalidate("never-checked")  # no-op
    assert world.cocoon.cached(CLEAN_MINT) is None
    world.cocoon.check(clean_candidate())
    assert world.calls() == (3, 3, 3)


def test_unavailable_reports_are_cached_at_most_two_minutes(world: World) -> None:
    world.rugcheck.error = http_error()
    world.cocoon.check(clean_candidate())
    world.clock.advance(UNAVAILABLE_CACHE_S - 1)
    world.cocoon.check(clean_candidate())
    assert len(world.rugcheck.calls) == 1
    world.clock.advance(1)
    world.rugcheck.error = None
    assert world.cocoon.check(clean_candidate()).passed is True
    assert len(world.rugcheck.calls) == 2


def test_errors_are_cached_at_most_two_minutes(world: World) -> None:
    world.rugcheck.report = object()
    world.cocoon.check(clean_candidate())
    world.rugcheck.report = clean_report()
    world.clock.advance(UNAVAILABLE_CACHE_S)
    assert world.cocoon.check(clean_candidate()).passed is True


def test_not_ready_reports_are_never_cached(world: World) -> None:
    world.rugcheck.error = ReportUnavailable(CLEAN_MINT, "unable to generate report")
    world.cocoon.check(clean_candidate())
    world.cocoon.check(clean_candidate())
    assert len(world.rugcheck.calls) == 2 and world.cocoon.cached(CLEAN_MINT) is None


def test_cache_can_be_disabled(make_settings, fake_clock) -> None:
    w = build_world(make_settings(COCOON_CACHE_MIN=0), fake_clock)
    w.cocoon.check(clean_candidate())
    w.cocoon.check(clean_candidate())
    assert w.calls() == (2, 2, 2)


def test_thresholds_come_from_settings(make_settings, fake_clock) -> None:
    w = build_world(make_settings(COCOON_TOP10_MAX_PCT=0.4, COCOON_SINGLE_HOLDER_MAX_PCT=0.2,
                                  COCOON_LP_LOCKED_MIN_PCT=100), fake_clock,
                    report=clean_report(markets=[market(CLEAN_POOL, "pump_fun_amm", 99.0, 1.0)]))
    assert rule_ids(w.cocoon.check(clean_candidate())) == {"top10", "single_holder", "lp_unlocked"}


# --------------------------------------------------------------------------- with O1's real clients


def test_fixture_reports_through_real_clients(fake_http, http_client, settings, fake_clock, load_fixture) -> None:
    """rugcheck_report.json passes and rugcheck_report_risky.json fails via O1's real parser and clients."""
    fake_http.register_fixture(f"/tokens/{CLEAN_MINT}/report", "rugcheck_report")
    fake_http.register_fixture(f"/tokens/{RISKY_MINT}/report", "rugcheck_report_risky")
    fake_http.register_fixture("api.mainnet-beta.solana.com", "rpc_getAccountInfo_mint", method="POST")
    fake_http.register_fixture("/ultra/v1/shield", "jup_ultra_shield")
    sources = build_sources(settings, http_client)
    try:
        sources.rugcheck.report_parsed(CLEAN_MINT)
        sources.rpc.mint_info(CLEAN_MINT)
        sources.jupiter.shield([CLEAN_MINT])
    except NotImplementedError:
        pytest.skip("O1 source clients not implemented yet")
    fake_http.reset_calls()
    cocoon = Cocoon(sources, settings, fake_clock)

    clean = cocoon.check(clean_candidate())
    assert clean.passed is True, clean.hard_fail_reasons
    assert clean.top_holders == [HOLDER_A, HOLDER_B]  # pool account excluded by the parser
    assert clean.metrics["lp_locked_pct"] == 100.0 and clean.metrics["program"] == "spl-token-2022"

    risky = cocoon.check(TokenCandidate(mint=RISKY_MINT, pool=RISKY_CURVE, dex="pumpfun",
                                        socials={"twitter": "x"}))
    assert risky.passed is False
    assert rule_ids(risky) == {"rugcheck_danger", "top10", "single_holder", "serial_launcher"}
    assert RISKY_CURVE not in risky.top_holders
    assert len(fake_http.calls) == 4  # clean: rugcheck+rpc+shield; risky: rugcheck only


@pytest.mark.live
def test_live_check_smoke(settings) -> None:
    """Opt-in (NIGHTCRAWLER_LIVE_TESTS=1): HIGGS (data/samples) through the real RugCheck, RPC and Shield."""
    from nightcrawler.clock import RealClock
    from nightcrawler.http import HttpClient

    clock = RealClock()
    cocoon = Cocoon(build_sources(settings, HttpClient.from_settings(settings, clock=clock)), settings, clock)
    higgs = TokenCandidate(mint="DoVAVzViX8Bjy3r15nwikSaSbzE6dV4ovd28aWpJpump",
                           pool="BFrSZakeqNzVtM3EFhroo4eRhagmmWN8BRntiQKFH6Ru", dex="pumpswap")
    report = cocoon.check(higgs)
    assert not any(r.startswith("error:") for r in report.hard_fail_reasons), report.hard_fail_reasons
    assert report.passed == (not report.hard_fail_reasons and not report.unverified)
    if "rugcheck" not in report.unverified:
        assert report.metrics["top10_pct"] is not None and report.creator


def test_a_malformed_shield_answer_fails_closed_through_the_real_client(fake_http, http_client, settings,
                                                                        fake_clock) -> None:
    """A 200 Shield body without ``warnings`` must not read as "no warnings" (required source)."""
    fake_http.register_fixture(f"/tokens/{CLEAN_MINT}/report", "rugcheck_report")
    fake_http.register_fixture("api.mainnet-beta.solana.com", "rpc_getAccountInfo_mint", method="POST")
    fake_http.register("/ultra/v1/shield", {"error": "internal: shield temporarily unavailable"})
    report = Cocoon(build_sources(settings, http_client), settings, fake_clock).check(clean_candidate())
    assert report.passed is False and "jupiter_shield" in report.unverified
    assert any(r.startswith("source unavailable: jupiter_shield") for r in report.hard_fail_reasons)


# --------------------------------------------------------------------------- copycat tickers / impersonation (warnings)

COPY_MINT = "CoPYcAt1111111111111111111111111111111pump"
COPY_MINT_2 = "CoPYcAt2222222222222222222222222222222pump"


def test_a_ticker_seen_on_another_coin_within_the_window_is_a_copycat_warning(world: World) -> None:
    first = world.cocoon.check(clean_candidate())  # "Gary"
    assert "copycat" not in warning_ids(first) and first.metrics["copycat_count"] == 0
    world.clock.advance(5 * 3600)
    copy = world.cocoon.check(clean_candidate(mint=COPY_MINT, symbol=" $gary "))
    assert copy.passed is True  # a warning, never a hard fail
    assert warning_ids(copy) == {"copycat"}
    assert copy.warnings == ["[copycat] ticker shared with 1 other coin seen in the last 6h"]
    assert copy.metrics["copycat_count"] == 1
    assert world.cocoon.counters["copycat"] == 1


@pytest.mark.parametrize("symbol", ["GARY", "gary", "$Gary", "G.A.R.Y", "ＧＡＲＹ",
                                    "GΑRY", "Gаry"])  # full-width; Greek Alpha; Cyrillic a
def test_copycat_tickers_are_normalized(world: World, symbol: str) -> None:
    world.cocoon.check(clean_candidate())
    assert "copycat" in warning_ids(world.cocoon.check(clean_candidate(mint=COPY_MINT, symbol=symbol)))


@pytest.mark.parametrize("symbol", ["GARY2", "GARRY", "GAR", "", "$"])
def test_other_tickers_are_not_copycats(world: World, symbol: str) -> None:
    world.cocoon.check(clean_candidate())
    report = world.cocoon.check(clean_candidate(mint=COPY_MINT, symbol=symbol))
    assert "copycat" not in warning_ids(report) and report.metrics["copycat_count"] == 0


def test_copycat_window_expires_and_the_same_mint_is_not_its_own_copycat(world: World) -> None:
    world.cocoon.check(clean_candidate())
    world.cocoon.check(clean_candidate(), force=True)
    assert world.cocoon.check(clean_candidate(), force=True).metrics["copycat_count"] == 0
    world.clock.advance(6 * 3600 + 1)
    assert world.cocoon.check(clean_candidate(mint=COPY_MINT)).metrics["copycat_count"] == 0
    world.clock.advance(60)
    report = world.cocoon.check(clean_candidate(mint=COPY_MINT_2))
    assert report.metrics["copycat_count"] == 1
    assert report.warnings == ["[copycat] ticker shared with 1 other coin seen in the last 6h"]


def test_observed_coins_count_as_seen_even_without_a_check(world: World) -> None:
    world.cocoon.observe(TokenCandidate(mint=COPY_MINT, symbol="GARY"))
    world.cocoon.observe(TokenCandidate(mint=COPY_MINT_2, symbol="gary"))
    report = world.cocoon.check(clean_candidate())
    assert report.metrics["copycat_count"] == 2
    assert "[copycat] ticker shared with 2 other coins seen in the last 6h" in report.warnings
    assert world.calls() == (1, 1, 1)  # observing is free


def test_copycat_check_can_be_disabled(make_settings, fake_clock) -> None:
    w = build_world(make_settings(COCOON_COPYCAT_WINDOW_H=0), fake_clock)
    w.cocoon.check(clean_candidate())
    report = w.cocoon.check(clean_candidate(mint=COPY_MINT))
    assert "copycat" not in warning_ids(report) and "copycat_count" not in report.metrics
    assert w.cocoon.tracked_tickers() == 0


def test_copycat_memory_is_bounded(world: World, monkeypatch) -> None:
    import nightcrawler.cocoon as cocoon_module

    monkeypatch.setattr(cocoon_module, "COPYCAT_MAX_TRACKED", 5)
    for i in range(50):
        world.cocoon.observe(TokenCandidate(mint=f"M{i:03d}" + "1" * 39, symbol=f"T{i}"))
        world.clock.advance(1)
    assert world.cocoon.tracked_tickers() <= 5
    world.cocoon.observe(TokenCandidate(mint=COPY_MINT, symbol="T49"))  # the newest are kept
    assert world.cocoon.check(clean_candidate(mint=COPY_MINT_2, symbol="T49")).metrics["copycat_count"] == 2


@pytest.mark.parametrize("name, symbol, brand", [
    ("Elon Musk Inu", "EMI", "Elon Musk"),
    ("ElonMuskDoge", "EMD", "Elon Musk"),
    ("Baby Elon", "BELON", "Elon"),
    ("Official TRUMP", "OT", "Trump"),
    ("whatever", "TRUMPCOIN", "Trump"),
    ("Ｔｅｓｌａ Cat", "TC", "Tesla"),  # full-width letters
    ("Tеsla Moon", "TM", "Tesla"),  # Cyrillic e
    ("M​rBeast Coin", "MBC", "MrBeast"),  # zero-width space
    ("Meta Cat", "MC", "Meta"),
])
def test_impersonating_names_are_a_warning(world: World, name: str, symbol: str, brand: str) -> None:
    report = world.cocoon.check(clean_candidate(name=name, symbol=symbol))
    assert report.passed is True
    assert warning_ids(report) == {"impersonation"}
    assert report.warnings == [f"[impersonation] name or ticker imitates {brand!r}"]
    assert report.metrics["impersonates"] == brand
    assert world.cocoon.counters["impersonation"] == 1


@pytest.mark.parametrize("name, symbol", [("Gary the Cat", "Gary"), ("Metaverse Frog", "MVF"),
                                          ("Elongated Dog", "ELD"), ("", "")])
def test_ordinary_names_are_not_impersonation(world: World, name: str, symbol: str) -> None:
    report = world.cocoon.check(clean_candidate(name=name, symbol=symbol))
    assert "impersonation" not in warning_ids(report) and report.metrics["impersonates"] is None


def test_the_impersonation_list_is_configurable(make_settings, fake_clock) -> None:
    w = build_world(make_settings(COCOON_IMPERSONATION_NAMES="Gary, Acme Corp"), fake_clock)
    assert w.cocoon.check(clean_candidate()).metrics["impersonates"] == "Gary"
    trump = clean_candidate(mint=COPY_MINT, name="Trump", symbol="TRUMP")
    assert w.cocoon.check(trump).metrics["impersonates"] is None
    off = build_world(make_settings(COCOON_IMPERSONATION_NAMES="none"), fake_clock)
    report = off.cocoon.check(clean_candidate(name="Elon Musk", symbol="ELON"))
    assert "impersonation" not in warning_ids(report) and report.metrics["impersonates"] is None
