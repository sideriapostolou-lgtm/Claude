"""Cocoon: the hard rug filter (owner: O2). FAIL CLOSED.

``Cocoon.check(candidate)`` gathers evidence from RugCheck (report), Solana RPC
(mint account) and Jupiter (audit fields already on the candidate + Shield),
and returns a
:class:`~nightcrawler.models.SafetyReport`.

HARD FAILS (``passed=False``; one reason string each, stable wording so the
dashboard can group them - start each with the rule id shown in brackets):

* ``[mint_authority]`` mint authority not renounced (RPC ``mintAuthority`` not null,
  or RugCheck ``mintAuthority`` not null, or Jupiter ``audit.mintAuthorityDisabled`` False).
* ``[freeze_authority]`` freeze authority set (same three sources).
* ``[token2022_ext]`` dangerous Token-2022 extension present: any of
  :data:`DANGEROUS_EXTENSIONS`; ``defaultAccountState`` only when its state is
  ``frozen`` (or cannot be read).
* ``[rugged]`` RugCheck ``rugged`` true.
* ``[rugcheck_danger]`` any RugCheck risk with level ``danger`` (name listed).
* ``[top10]`` top-10 holder share (AMM/curve/locker excluded) >
  ``COCOON_TOP10_MAX_PCT`` (30 %), or unknown (no holder data).
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
  (Live 2026-10-08: Shield rates ``HAS_MINT_AUTHORITY`` only ``info``, which is
  why the mint-authority rule reads the RPC/RugCheck instead.)
* ``[lp_unlocked]`` graduated AMM pool (not a bonding curve) with LP
  locked/burned < ``COCOON_LP_LOCKED_MIN_PCT`` (90 %), or unknown. Pump.fun
  graduated pools (pumpswap) burn LP; trust RugCheck ``markets[].lp.lpLockedPct``.
  The market whose pubkey is the candidate's ``pool`` decides; otherwise
  RugCheck's best non-curve market (``RugReport.lp_locked_pct``).
  Concentrated-liquidity pools (DLMM/CLMM) report 0 % - their liquidity can be
  withdrawn at any time, so they fail this rule by design.

WARNINGS (not fatal; each starts with a bracketed id too): mutable metadata,
no socials, paid promotion (DexScreener boost/profile), holder count <
``COCOON_MIN_HOLDERS``, holder stats unavailable (fresh token), RugCheck
``warn``-level risks, unknown creator holding or insider share.

ORDER (rate budgets are tight): Jupiter audit (no HTTP) -> RugCheck report ->
RPC mint account -> Jupiter Shield. Checking stops at the first stage that
produced a hard fail (it already decides ``passed=False``), so later sources
are not called for doomed tokens.

DEGRADATION: if a REQUIRED source fails (RugCheck report, RPC mint info,
Jupiter Shield), add ``"source unavailable: <name>"`` to ``hard_fail_reasons``
and the source name to ``unverified`` -> ``passed=False``. RugCheck
``ReportUnavailable`` (too new) -> ``"source unavailable: rugcheck (not ready)"``
and the report is NOT cached, so the next check retries. A mint account the
RPC does not know -> ``"source unavailable: rpc (mint account not found)"``.
GeckoTerminal token info is NOT called (GT is the scarcest budget).

CACHE: reports are cached per mint for ``COCOON_CACHE_MIN`` (30) minutes;
``check(..., force=True)`` bypasses it. Failed-closed reports caused by an
unavailable source (or an unexpected error) are cached for at most 2 minutes.

``metrics`` keys written: ``top10_pct, max_holder_pct, creator_pct,
insider_pct, graph_insiders, dev_mints, lp_locked_pct, holder_count,
rugcheck_score_normalised, mint_authority, freeze_authority, extensions,
shield_warnings, program, decimals`` (only for the stages that ran).
"""

from __future__ import annotations

from typing import Any

from nightcrawler.clock import Clock
from nightcrawler.config import Settings
from nightcrawler.logging_setup import get_logger
from nightcrawler.models import SafetyReport, TokenCandidate
from nightcrawler.sources import Sources
from nightcrawler.sources._parse import to_float, to_int
from nightcrawler.sources.rugcheck import CURVE_MARKET_TYPES, ReportUnavailable, RugReport

__all__ = [
    "Cocoon",
    "DANGEROUS_EXTENSIONS",
    "UNAVAILABLE_CACHE_S",
    "SHIELD_FAIL_SEVERITIES",
    "MAX_TOP_HOLDERS",
]

log = get_logger(__name__)

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
#: Jupiter Shield severities that hard-fail (``info`` only informs).
SHIELD_FAIL_SEVERITIES = frozenset({"warning", "critical"})
#: Max holder wallets handed to the radar.
MAX_TOP_HOLDERS = 20

#: defaultAccountState values that are safe; anything else (frozen, unknown, unreadable) fails.
_SAFE_ACCOUNT_STATES = frozenset({"initialized", "uninitialized", "0", "1"})
_NOT_READY = "source unavailable: rugcheck (not ready)"
_ERROR_PREFIX = "error: "


class Cocoon:
    """Rug filter with a per-mint TTL cache. Thread-compatible (engine calls it from one thread)."""

    def __init__(self, sources: Sources, settings: Settings, clock: Clock) -> None:
        self.sources = sources
        self.settings = settings
        self.clock = clock
        self._cache: dict[str, tuple[float, SafetyReport]] = {}  # mint -> (expires_at, report)

    # ------------------------------------------------------------------ public
    def check(self, candidate: TokenCandidate, *, force: bool = False) -> SafetyReport:
        """Evaluate ``candidate`` and return a :class:`SafetyReport` (never raises).

        ``passed`` is True only when ``hard_fail_reasons`` and ``unverified``
        are both empty. ``checked_at`` = ``clock.now()``. Fills ``creator``,
        ``top_holders`` (non-excluded owner wallets, largest first, max 20) and
        ``insiders`` for the radar. Any unexpected exception becomes a
        fail-closed report with reason ``"error: <ExceptionType>"``.
        """
        if not force:
            hit = self.cached(candidate.mint)
            if hit is not None:
                return hit
        now = self.clock.now()
        try:
            report = self._evaluate(candidate, now)
        except Exception as exc:  # fail closed on any bug or malformed evidence
            log.warning("cocoon_error mint=%s error=%s: %s", candidate.mint, type(exc).__name__, exc)
            report = SafetyReport(mint=candidate.mint, passed=False, checked_at=now,
                                  hard_fail_reasons=[f"{_ERROR_PREFIX}{type(exc).__name__}"])
        self._store(report, now)
        log.info("cocoon_check mint=%s passed=%s fails=%d unverified=%s", report.mint, report.passed,
                 len(report.hard_fail_reasons), ",".join(report.unverified) or "-")
        return report

    def invalidate(self, mint: str) -> None:
        """Drop the cached report for ``mint`` (no-op if absent)."""
        self._cache.pop(mint, None)

    def cached(self, mint: str) -> SafetyReport | None:
        """Cached, still-fresh report for ``mint`` or None."""
        hit = self._cache.get(mint)
        if hit is None:
            return None
        expires_at, report = hit
        if self.clock.now() >= expires_at:
            del self._cache[mint]
            return None
        return report

    # ------------------------------------------------------------------ cache
    def _store(self, report: SafetyReport, now: float) -> None:
        ttl = self._ttl_s(report)
        for mint in [m for m, (expires_at, _) in self._cache.items() if expires_at <= now]:
            del self._cache[mint]
        if ttl > 0:
            self._cache[report.mint] = (now + ttl, report)
        else:
            self._cache.pop(report.mint, None)

    def _ttl_s(self, report: SafetyReport) -> float:
        if _NOT_READY in report.hard_fail_reasons:
            return 0.0
        full = self.settings.cocoon_cache_min * 60
        degraded = report.unverified or any(r.startswith(_ERROR_PREFIX) for r in report.hard_fail_reasons)
        return min(full, UNAVAILABLE_CACHE_S) if degraded else full

    # ------------------------------------------------------------------ evaluation
    def _evaluate(self, c: TokenCandidate, now: float) -> SafetyReport:
        report = SafetyReport(mint=c.mint, passed=False, checked_at=now, creator=c.dev)
        self._check_jupiter_audit(c, report)
        for stage in (self._check_rugcheck, self._check_mint_account, self._check_shield):
            if report.hard_fail_reasons:
                break
            stage(c, report)
        self._add_candidate_warnings(c, report)
        report.passed = not report.hard_fail_reasons and not report.unverified
        return report

    def _check_jupiter_audit(self, c: TokenCandidate, report: SafetyReport) -> None:
        """Rules on the Jupiter ``audit`` dict the crawler already fetched (no HTTP)."""
        audit = c.audit or {}
        dev_mints = to_int(audit.get("devMints"))
        report.metrics["dev_mints"] = dev_mints
        if audit.get("mintAuthorityDisabled") is False:
            _fail(report, "mint_authority", "mint authority not renounced (Jupiter audit)")
        if audit.get("freezeAuthorityDisabled") is False:
            _fail(report, "freeze_authority", "freeze authority set (Jupiter audit)")
        if dev_mints is not None and dev_mints > self.settings.cocoon_dev_mints_max:
            _fail(report, "serial_launcher",
                  f"creator launched {dev_mints} tokens (max {self.settings.cocoon_dev_mints_max})")

    def _check_rugcheck(self, c: TokenCandidate, report: SafetyReport) -> None:
        try:
            rr = self.sources.rugcheck.report_parsed(c.mint)
        except ReportUnavailable:
            _unavailable(report, "rugcheck", "not ready")
            return
        except Exception as exc:
            _unavailable(report, "rugcheck", exc=exc)
            return
        self._apply_rug_report(c, rr, report)

    def _apply_rug_report(self, c: TokenCandidate, rr: RugReport, report: SafetyReport) -> None:
        report.metrics.update({
            "top10_pct": rr.top10_pct,
            "max_holder_pct": rr.max_holder_pct,
            "graph_insiders": rr.graph_insiders,
            "rugcheck_score_normalised": rr.score_normalised,
            "mint_authority": rr.mint_authority,
            "freeze_authority": rr.freeze_authority,
            "extensions": list(rr.extensions),
        })
        if rr.total_holders is not None:
            report.metrics["holder_count"] = rr.total_holders
        _fill_wallets(c, rr, report)

        if rr.mint_authority:
            _fail(report, "mint_authority", "mint authority not renounced (RugCheck)")
        if rr.freeze_authority:
            _fail(report, "freeze_authority", "freeze authority set (RugCheck)")
        dangerous = _dangerous_extensions(rr.extensions, rr.default_account_state)
        if dangerous:
            _fail(report, "token2022_ext", "dangerous Token-2022 extensions: " + ", ".join(dangerous))
        if rr.rugged:
            _fail(report, "rugged", "RugCheck marks this token as rugged")
        if rr.danger_risks:
            _fail(report, "rugcheck_danger", "RugCheck danger: " + ", ".join(rr.danger_risks))
        self._check_concentration(rr, report)
        self._check_creator(c, rr, report)
        self._check_insiders(rr, report)
        if rr.creator_rug_history:
            _fail(report, "serial_launcher", "creator has a history of rugged tokens (RugCheck)")
        self._check_lp(c, rr, report)
        if rr.mutable_metadata:
            _warn(report, "mutable_metadata", "token metadata can still be changed")
        for name in rr.warn_risks:
            _warn(report, "rugcheck_warn", name)

    def _check_concentration(self, rr: RugReport, report: SafetyReport) -> None:
        s = self.settings
        if rr.top10_pct is None:
            _fail(report, "top10", "holder concentration unknown (no holder data)")
            return
        if rr.top10_pct > s.cocoon_top10_max_pct:
            _fail(report, "top10", f"top-10 holders own {rr.top10_pct:.1f}% (max {s.cocoon_top10_max_pct:g}%)")
        if rr.max_holder_pct is not None and rr.max_holder_pct > s.cocoon_single_holder_max_pct:
            _fail(report, "single_holder",
                  f"one holder owns {rr.max_holder_pct:.1f}% (max {s.cocoon_single_holder_max_pct:g}%)")

    def _check_creator(self, c: TokenCandidate, rr: RugReport, report: SafetyReport) -> None:
        pct = rr.creator_pct
        if pct is None:
            pct = to_float((c.audit or {}).get("devBalancePercentage"))
        report.metrics["creator_pct"] = pct
        limit = self.settings.cocoon_creator_max_pct
        if pct is None:
            _warn(report, "creator_unknown", "creator holding unknown")
        elif pct > limit:
            _fail(report, "creator_holding", f"creator still holds {pct:.1f}% (max {limit:g}%)")

    def _check_insiders(self, rr: RugReport, report: SafetyReport) -> None:
        s = self.settings
        share = rr.insider_network_pct if rr.insider_network_pct is not None else rr.insider_holder_pct
        report.metrics["insider_pct"] = share
        if rr.graph_insiders < s.cocoon_graph_insiders_min:
            return
        if share is None:
            _warn(report, "insiders_unknown", f"{rr.graph_insiders} insider wallets detected, share unknown")
        elif share > s.cocoon_insider_max_pct:
            _fail(report, "insiders",
                  f"{rr.graph_insiders} insider wallets hold {share:.1f}% (max {s.cocoon_insider_max_pct:g}%)")

    def _check_lp(self, c: TokenCandidate, rr: RugReport, report: SafetyReport) -> None:
        pct, applies = _lp_locked_pct(c, rr)
        report.metrics["lp_locked_pct"] = pct
        if not applies:
            return
        limit = self.settings.cocoon_lp_locked_min_pct
        if pct is None:
            _fail(report, "lp_unlocked", "LP lock unknown on an AMM pool")
        elif pct < limit:
            _fail(report, "lp_unlocked", f"only {pct:.0f}% of LP locked/burned (min {limit:g}%)")

    def _check_mint_account(self, c: TokenCandidate, report: SafetyReport) -> None:
        """On-chain mint account via RPC (authoritative for authorities and extensions)."""
        try:
            info = self.sources.rpc.mint_info(c.mint)
        except Exception as exc:
            _unavailable(report, "rpc", exc=exc)
            return
        if info is None:
            _unavailable(report, "rpc", "mint account not found")
            return
        extensions = list(info.get("extensions") or [])
        report.metrics.update({
            "mint_authority": info.get("mint_authority"),
            "freeze_authority": info.get("freeze_authority"),
            "program": info.get("program"),
            "extensions": extensions,
            "decimals": info.get("decimals"),
        })
        if info.get("mint_authority"):
            _fail(report, "mint_authority", "mint authority not renounced (on-chain)")
        if info.get("freeze_authority"):
            _fail(report, "freeze_authority", "freeze authority set (on-chain)")
        states = info.get("extension_states") or {}
        dangerous = _dangerous_extensions(extensions, states.get("defaultAccountState"))
        if dangerous:
            _fail(report, "token2022_ext", "dangerous Token-2022 extensions: " + ", ".join(dangerous))

    def _check_shield(self, c: TokenCandidate, report: SafetyReport) -> None:
        try:
            warnings = self.sources.jupiter.shield([c.mint]) or {}
        except Exception as exc:
            _unavailable(report, "jupiter_shield", exc=exc)
            return
        items = [w for w in warnings.get(c.mint) or [] if isinstance(w, dict)]
        report.metrics["shield_warnings"] = [{"type": w.get("type"), "severity": w.get("severity")} for w in items]
        bad = [w for w in items if str(w.get("severity") or "").lower() in SHIELD_FAIL_SEVERITIES]
        if bad:
            _fail(report, "shield", "Jupiter Shield: " + ", ".join(f"{w.get('type')} ({w.get('severity')})"
                                                                   for w in bad))

    def _add_candidate_warnings(self, c: TokenCandidate, report: SafetyReport) -> None:
        if not c.socials:
            _warn(report, "no_socials", "no website/twitter/telegram listed")
        if c.paid_promo:
            _warn(report, "paid_promo", "paid DexScreener promotion (boost/profile)")
        holders = report.metrics.get("holder_count")
        if holders is None:
            holders = c.holder_count
            report.metrics["holder_count"] = holders
        if holders is None:
            _warn(report, "holders_unknown", "holder stats unavailable")
        elif holders < self.settings.cocoon_min_holders:
            _warn(report, "low_holders", f"{holders} holders (< {self.settings.cocoon_min_holders})")


# ---------------------------------------------------------------------- helpers


def _fail(report: SafetyReport, rule: str, detail: str) -> None:
    """Add a hard-fail reason ``"[rule] detail"`` (one per rule id)."""
    tag = f"[{rule}]"
    if not any(r.startswith(tag) for r in report.hard_fail_reasons):
        report.hard_fail_reasons.append(f"{tag} {detail}")


def _warn(report: SafetyReport, rule: str, detail: str) -> None:
    reason = f"[{rule}] {detail}"
    if reason not in report.warnings:
        report.warnings.append(reason)


def _unavailable(report: SafetyReport, source: str, detail: str | None = None,
                 exc: BaseException | None = None) -> None:
    """Fail closed: the source could not be consulted."""
    if exc is not None:
        log.warning("cocoon_source_unavailable mint=%s source=%s error=%s: %s",
                    report.mint, source, type(exc).__name__, exc)
    reason = f"source unavailable: {source}" + (f" ({detail})" if detail else "")
    report.hard_fail_reasons.append(reason)
    if source not in report.unverified:
        report.unverified.append(source)


def _holder_wallet(holder: dict[str, Any]) -> str | None:
    return holder.get("owner") or holder.get("address")


def _fill_wallets(c: TokenCandidate, rr: RugReport, report: SafetyReport) -> None:
    """Creator, largest non-excluded holder wallets and insider wallets for the radar."""
    report.creator = rr.creator or c.dev
    holders = sorted((h for h in rr.top_holders if not h.get("excluded")),
                     key=lambda h: to_float(h.get("pct")) or 0.0, reverse=True)
    wallets = [w for h in holders if (w := _holder_wallet(h))]
    report.top_holders = list(dict.fromkeys(wallets))[:MAX_TOP_HOLDERS]
    insiders = [w for h in holders if h.get("insider") and (w := _holder_wallet(h))]
    report.insiders = list(dict.fromkeys(insiders))


def _is_frozen_state(state: Any) -> bool:
    """True unless a defaultAccountState value is a known safe state (fail closed on unknown shapes)."""
    if isinstance(state, dict):
        state = state.get("accountState", state.get("state"))
    text = "" if state is None else str(state).strip().lower()
    return text not in _SAFE_ACCOUNT_STATES


def _dangerous_extensions(names: list[str], default_state: Any) -> list[str]:
    """Dangerous extension names present (``defaultAccountState`` only when frozen/unknown)."""
    found = sorted(n for n in set(names) if n in DANGEROUS_EXTENSIONS and n != "defaultAccountState")
    if "defaultAccountState" in names and _is_frozen_state(default_state):
        found.append("defaultAccountState(frozen)")
    return found


def _is_curve_market(market: dict[str, Any]) -> bool:
    """Bonding-curve market per RugCheck ``marketType`` (``pump_fun_amm`` = PumpSwap is an AMM)."""
    return market.get("market_type") in CURVE_MARKET_TYPES


def _lp_locked_pct(c: TokenCandidate, rr: RugReport) -> tuple[float | None, bool]:
    """``(lp_locked_pct, rule_applies)`` for the pool that matters.

    The RugCheck market matching the candidate's pool decides when present
    (a curve -> rule does not apply). Otherwise the rule applies whenever any
    non-curve market exists, using RugCheck's best non-curve market.
    """
    markets = rr.markets or []
    main = next((m for m in markets if c.pool and m.get("pubkey") == c.pool), None)
    if main is not None:
        if _is_curve_market(main):
            return None, False
        return to_float(main.get("lp_locked_pct")), True
    has_amm = any(not _is_curve_market(m) for m in markets)
    return rr.lp_locked_pct, has_amm
