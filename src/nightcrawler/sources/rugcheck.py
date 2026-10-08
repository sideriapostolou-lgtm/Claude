"""RugCheck client (owner: O1). No auth for GETs; stay <= 1 req/s.

Base ``https://api.rugcheck.xyz/v1``.

* ``/tokens/{mint}/report`` - full report (the one we use). Fields:
  ``mintAuthority`` / ``freezeAuthority`` (null = renounced),
  ``token.{supply,decimals}``, ``token_extensions`` (dict of extension ->
  config|null|false), ``tokenMeta.mutable``, ``topHolders[20]{address,
  owner, pct (PERCENT), insider}``, ``totalHolders``,
  ``risks[]{name, level 'danger'|'warn', score, value, description}``,
  ``score``, ``score_normalised`` (0-100), ``markets[]{pubkey, marketType,
  liquidityA, liquidityB, lp.{lpLockedPct, lpLockedUSD}}``,
  ``totalMarketLiquidity``, ``creator``, ``creatorBalance`` (base units),
  ``creatorTokens`` (list|null), ``graphInsidersDetected`` (int),
  ``insiderNetworks`` (list|null of ``{id, size, type, tokenAmount,
  currentHolding, activeAccounts}``, amounts in base units),
  ``knownAccounts{addr: {name, type: AMM|CREATOR|LOCKER}}``, ``rugged``.
* Very new mints -> retry later. Verified live 2026-10-08 on a 6-second-old
  mint: ``/report`` answers HTTP 400 ``{"error": "not found"}`` and
  ``/report/summary`` answers HTTP 400 ``{"error": "unable to generate report"}``.

GOTCHAS (must be handled in :func:`parse_report`):

* Pool / bonding-curve accounts appear in ``topHolders``. Exclude holders
  whose ``owner`` (or ``address``) is a ``markets[].pubkey``, or is a
  ``knownAccounts`` entry of type ``AMM`` or ``LOCKER``, before computing
  concentration. The pool's token vaults (``markets[].liquidityA/B``) and
  their owners are excluded too.
* The summary's ``lpLockedPct`` is unreliable; use ``report.markets[].lp``.
* Insider network amounts can exceed the supply (seen live 2026-10-08: one
  254-wallet network "holding" 207 % of supply), so the derived share is
  clamped to 100 %.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nightcrawler.http import HttpClient, HttpError
from nightcrawler.sources._parse import first_not_none, get_path, to_bool, to_float, to_int

__all__ = ["BASE_URL", "CURVE_MARKET_TYPES", "ReportUnavailable", "RugReport", "RugCheckClient", "parse_report"]

BASE_URL = "https://api.rugcheck.xyz/v1"
#: RugCheck ``marketType`` values of bonding curves (not AMM pools; no LP to lock).
#: ``pump_fun_amm`` is the graduated PumpSwap pool and is NOT a curve.
#: ``raydium_launchlab`` (Raydium LaunchLab bonding curve) seen in live reports 2026-10-08.
CURVE_MARKET_TYPES = frozenset({"pump_fun", "meteora_dbc", "raydium_launchlab"})
#: Lower-case HTTP 400 error texts that mean "not indexed yet, retry later".
_NOT_READY_HINTS = ("unable to generate report", "not found")
_RUG_HISTORY_RISK = "creator history of rugged tokens"
#: Token-2022 AccountState enum (defaultAccountState may arrive as a number).
_ACCOUNT_STATES = {0: "uninitialized", 1: "initialized", 2: "frozen"}


class ReportUnavailable(Exception):
    """RugCheck cannot produce a report yet (400 'unable to generate report' / 'not found', or 404). Retry later."""

    def __init__(self, mint: str, detail: str = "") -> None:
        self.mint = mint
        self.detail = detail
        super().__init__(f"rugcheck report unavailable for {mint}: {detail}".rstrip(": "))


@dataclass(slots=True)
class RugReport:
    """Normalized RugCheck report. Percent fields are PERCENT (0-100); None = unknown.

    * ``top_holders``: every ``topHolders`` item as ``{"address", "owner",
      "pct", "insider": bool, "excluded": bool, "excluded_reason": str|None}``
      (excluded = AMM / curve / locker account), sorted by pct desc.
    * ``top10_pct``: sum of pct of the 10 largest NON-excluded holders.
    * ``max_holder_pct``: largest NON-excluded holder pct.
    * ``insider_holder_pct``: sum of pct of non-excluded holders with ``insider``.
    * ``insider_network_pct``: token share held by detected insider networks
      when computable from ``insiderNetworks`` (sum of each network's token
      amount / supply * 100), else None.
    * ``creator_pct``: ``creatorBalance / token.supply * 100`` (None if unknown).
    * ``creator_rug_history``: True if any risk name contains
      "Creator history of rugged tokens".
    * ``extensions``: names of ``token_extensions`` keys whose value is truthy
      (e.g. ``["metadataPointer", "tokenMetadata"]``), plus
      ``default_account_state`` = the defaultAccountState value if present.
    * ``markets``: ``[{"pubkey", "market_type", "lp_locked_pct", "lp_locked_usd"}]``.
    * ``lp_locked_pct``: lp_locked_pct of the market with the largest
      ``lp_locked_usd`` among non-curve markets (marketType not starting with
      ``pump_fun``/``meteora_dbc`` curve types), else None.

    Implementation notes: the curve types are exactly :data:`CURVE_MARKET_TYPES`
    (``pump_fun_amm`` counts as an AMM). ``insider_networks`` items are
    ``{"id", "type", "size", "active_accounts", "token_amount",
    "current_holding", "pct"}`` where ``pct`` uses ``currentHolding`` (falling
    back to ``tokenAmount``) / supply; ``insider_network_pct`` is their sum
    clamped to 100. ``top10_pct`` / ``max_holder_pct`` / ``insider_holder_pct``
    are None when RugCheck listed no holders at all, 0.0 when every listed
    holder is excluded. ``default_account_state`` is normalized to a lower-case
    state name (``"frozen"``, ``"initialized"``).
    """

    mint: str
    mint_authority: str | None = None
    freeze_authority: str | None = None
    mutable_metadata: bool | None = None
    supply: int | None = None
    decimals: int | None = None
    extensions: list[str] = field(default_factory=list)
    default_account_state: str | None = None
    risks: list[dict[str, Any]] = field(default_factory=list)
    danger_risks: list[str] = field(default_factory=list)
    warn_risks: list[str] = field(default_factory=list)
    score: int | None = None
    score_normalised: float | None = None
    rugged: bool = False
    creator: str | None = None
    creator_pct: float | None = None
    creator_tokens_count: int | None = None
    creator_rug_history: bool = False
    total_holders: int | None = None
    top_holders: list[dict[str, Any]] = field(default_factory=list)
    top10_pct: float | None = None
    max_holder_pct: float | None = None
    insider_holder_pct: float | None = None
    graph_insiders: int = 0
    insider_networks: list[dict[str, Any]] = field(default_factory=list)
    insider_network_pct: float | None = None
    markets: list[dict[str, Any]] = field(default_factory=list)
    lp_locked_pct: float | None = None
    total_market_liquidity_usd: float | None = None
    known_accounts: dict[str, dict[str, Any]] = field(default_factory=dict)


class RugCheckClient:
    """Thin client. All failures other than "not ready yet" raise ``HttpError``."""

    def __init__(self, http: HttpClient, base_url: str = BASE_URL) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")

    def report(self, mint: str) -> dict[str, Any]:
        """Raw ``/tokens/{mint}/report`` JSON.

        Raises :class:`ReportUnavailable` on HTTP 400 whose body mentions
        "unable to generate report" or "not found" (what ``/report`` answers
        for a mint RugCheck has not indexed yet), on 404, and when the body is
        empty or not a JSON object; other failures raise
        :class:`nightcrawler.http.HttpError`.
        """
        return self._get_report(mint, f"/tokens/{mint}/report")

    def report_parsed(self, mint: str) -> RugReport:
        """``parse_report(self.report(mint))`` (same exceptions)."""
        return parse_report(self.report(mint), mint=mint)

    def summary(self, mint: str) -> dict[str, Any]:
        """Raw ``/tokens/{mint}/report/summary`` (risks, score, score_normalised).

        Same error mapping as :meth:`report`. Not used for LP lock (unreliable).
        """
        return self._get_report(mint, f"/tokens/{mint}/report/summary")

    def _get_report(self, mint: str, path: str) -> dict[str, Any]:
        try:
            resp = self.http.get_json(f"{self.base_url}{path}")
        except HttpError as exc:
            detail = _not_ready_detail(exc)
            if detail is None:
                raise
            raise ReportUnavailable(mint, detail) from exc
        if not isinstance(resp, dict):
            raise ReportUnavailable(mint, "empty report")
        return resp


def parse_report(report: dict[str, Any], *, mint: str = "") -> RugReport:
    """Normalize a raw report into :class:`RugReport` (see field docs). Never raises on missing fields.

    ``mint`` is used only when the report itself has no ``mint`` field.
    """
    raw_token = report.get("token")
    token: dict[str, Any] = raw_token if isinstance(raw_token, dict) else {}
    supply = to_int(token.get("supply"))
    risks = [_risk(r) for r in _dicts(report.get("risks"))]
    holders = _holders(report)
    counted = [h for h in holders if not h["excluded"]]
    networks = [_network(n, supply) for n in _dicts(report.get("insiderNetworks"))]
    network_pcts = [n["pct"] for n in networks if n["pct"] is not None]
    extensions, default_state = _extensions(report.get("token_extensions"))
    markets = [_market(m) for m in _dicts(report.get("markets"))]
    creator_tokens = report.get("creatorTokens")
    return RugReport(
        mint=report.get("mint") or mint,
        mint_authority=first_not_none(report.get("mintAuthority"), token.get("mintAuthority")),
        freeze_authority=first_not_none(report.get("freezeAuthority"), token.get("freezeAuthority")),
        mutable_metadata=to_bool(get_path(report, "tokenMeta.mutable")),
        supply=supply,
        decimals=to_int(token.get("decimals")),
        extensions=extensions,
        default_account_state=default_state,
        risks=risks,
        danger_risks=[r["name"] for r in risks if r["level"] == "danger"],
        warn_risks=[r["name"] for r in risks if r["level"] == "warn"],
        score=to_int(report.get("score")),
        score_normalised=to_float(report.get("score_normalised")),
        rugged=bool(to_bool(report.get("rugged"), False)),
        creator=report.get("creator") or None,
        creator_pct=_pct_of_supply(to_int(report.get("creatorBalance")), supply),
        creator_tokens_count=len(creator_tokens) if isinstance(creator_tokens, list) else None,
        creator_rug_history=any(_RUG_HISTORY_RISK in r["name"].lower() for r in risks),
        total_holders=to_int(report.get("totalHolders")),
        top_holders=holders,
        top10_pct=sum((h["pct"] for h in counted[:10]), 0.0) if holders else None,
        max_holder_pct=(counted[0]["pct"] if counted else 0.0) if holders else None,
        insider_holder_pct=sum((h["pct"] for h in counted if h["insider"]), 0.0) if holders else None,
        graph_insiders=to_int(report.get("graphInsidersDetected"), 0),
        insider_networks=networks,
        insider_network_pct=min(100.0, sum(network_pcts, 0.0)) if network_pcts else None,
        markets=markets,
        lp_locked_pct=_amm_lp_locked_pct(markets),
        total_market_liquidity_usd=to_float(report.get("totalMarketLiquidity")),
        known_accounts=_known_accounts(report.get("knownAccounts")),
    )


# --------------------------------------------------------------------------- helpers


def _dicts(items: Any) -> list[dict[str, Any]]:
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _not_ready_detail(exc: HttpError) -> str | None:
    """Why the report is not ready yet, or None when ``exc`` is a real failure."""
    if exc.status == 404:
        return "not found"
    if exc.status != 400:
        return None
    payload_error = exc.payload.get("error") if isinstance(exc.payload, dict) else None
    text = str(payload_error or exc.body or "").lower()
    return next((hint for hint in _NOT_READY_HINTS if hint in text), None)


def _pct_of_supply(amount: int | None, supply: int | None) -> float | None:
    if amount is None or not supply or supply <= 0:
        return None
    return amount / supply * 100.0


def _risk(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(raw.get("name") or ""),
        "level": str(raw.get("level") or "").lower(),
        "score": to_float(raw.get("score")),
        "value": raw.get("value"),
        "description": raw.get("description"),
    }


def _excluded_accounts(report: dict[str, Any]) -> dict[str, str]:
    """``{address: reason}`` of accounts that are pools, pool vaults, curves or lockers (not holders)."""
    excluded: dict[str, str] = {}
    for market in _dicts(report.get("markets")):
        for key, reason in (("pubkey", "market"), ("liquidityA", "market vault"), ("liquidityB", "market vault")):
            if market.get(key):
                excluded.setdefault(market[key], reason)
        for key in ("liquidityAAccount", "liquidityBAccount"):
            owner = get_path(market, (key, "owner"))
            if owner:
                excluded.setdefault(owner, "market vault owner")
    for address, info in _known_accounts(report.get("knownAccounts")).items():
        kind = str(info.get("type") or "").upper()
        if kind in ("AMM", "LOCKER"):
            excluded.setdefault(address, kind.lower())
    return excluded


def _known_accounts(raw: Any) -> dict[str, dict[str, Any]]:
    """``knownAccounts`` with dict values only (``{}`` when missing)."""
    return {k: v for k, v in raw.items() if isinstance(v, dict)} if isinstance(raw, dict) else {}


def _holders(report: dict[str, Any]) -> list[dict[str, Any]]:
    """``topHolders`` normalized with exclusion flags, largest first."""
    excluded = _excluded_accounts(report)
    holders: list[dict[str, Any]] = []
    for raw in _dicts(report.get("topHolders")):
        address: Any = raw.get("address")  # raw JSON values, looked up as they are
        owner: Any = raw.get("owner")
        reason = excluded.get(owner) or excluded.get(address)
        holders.append({
            "address": address,
            "owner": owner,
            "pct": to_float(raw.get("pct"), 0.0),
            "insider": bool(to_bool(raw.get("insider"), False)),
            "excluded": reason is not None,
            "excluded_reason": reason,
        })
    holders.sort(key=lambda h: h["pct"], reverse=True)
    return holders


def _network(raw: dict[str, Any], supply: int | None) -> dict[str, Any]:
    token_amount = to_int(raw.get("tokenAmount"))
    current = to_int(raw.get("currentHolding"))
    return {
        "id": raw.get("id"),
        "type": raw.get("type"),
        "size": to_int(raw.get("size")),
        "active_accounts": to_int(raw.get("activeAccounts")),
        "token_amount": token_amount,
        "current_holding": current,
        "pct": _pct_of_supply(first_not_none(current, token_amount), supply),
    }


def _extensions(raw: Any) -> tuple[list[str], str | None]:
    """(names of present Token-2022 extensions, default account state name or None)."""
    if not isinstance(raw, dict):
        return [], None
    names = [name for name, value in raw.items() if value]
    return names, _account_state(raw.get("defaultAccountState"))


def _account_state(value: Any) -> str | None:
    """defaultAccountState as a lower-case state name, whatever shape RugCheck uses.

    Accepts a name (``"frozen"``), the enum number (``2``), a dict holding either,
    or ``true`` (present but unspecified -> ``"unknown"``); absent/false -> None.
    """
    if isinstance(value, dict):
        value = first_not_none(*(value.get(k) for k in ("accountState", "state", "defaultState")))
    if value is True:
        return "unknown"
    if value is None or value is False or value == "":
        return None
    if isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit()):
        return _ACCOUNT_STATES.get(int(value), str(int(value)))
    return str(value).strip().lower()


def _market(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "pubkey": raw.get("pubkey"),
        "market_type": raw.get("marketType"),
        "lp_locked_pct": to_float(get_path(raw, "lp.lpLockedPct")),
        "lp_locked_usd": to_float(get_path(raw, "lp.lpLockedUSD")),
    }


def _amm_lp_locked_pct(markets: list[dict[str, Any]]) -> float | None:
    """LP locked % of the biggest (by locked USD) non-curve market with a known lock percentage."""
    amm = [m for m in markets if m["market_type"] not in CURVE_MARKET_TYPES and m["lp_locked_pct"] is not None]
    if not amm:
        return None
    return max(amm, key=lambda m: m["lp_locked_usd"] or 0.0)["lp_locked_pct"]
