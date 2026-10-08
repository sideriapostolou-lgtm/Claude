"""RugCheck client (owner: O1). No auth for GETs; stay <= 1 req/s.

Base ``https://api.rugcheck.xyz/v1``.

* ``/tokens/{mint}/report`` - full report (the one we use). Fields:
  ``mintAuthority`` / ``freezeAuthority`` (null = renounced),
  ``token.{supply,decimals}``, ``token_extensions`` (dict of extension ->
  config|null|false), ``tokenMeta.mutable``, ``topHolders[20]{address,
  owner, pct (PERCENT), insider}``, ``totalHolders``,
  ``risks[]{name, level 'danger'|'warn', score, value, description}``,
  ``score``, ``score_normalised`` (0-100), ``markets[]{pubkey, marketType,
  lp.{lpLockedPct, lpLockedUSD}}``, ``totalMarketLiquidity``, ``creator``,
  ``creatorBalance`` (base units), ``creatorTokens`` (list|null),
  ``graphInsidersDetected`` (int), ``insiderNetworks`` (list|null),
  ``knownAccounts{addr: {name, type: AMM|CREATOR|LOCKER}}``, ``rugged``.
* ``/tokens/{mint}/report/summary`` may answer HTTP 400
  ``{"error": "unable to generate report"}`` for very new mints -> retry later.

GOTCHAS (must be handled in :func:`parse_report`):

* Pool / bonding-curve accounts appear in ``topHolders``. Exclude holders
  whose ``owner`` (or ``address``) is a ``markets[].pubkey``, or is a
  ``knownAccounts`` entry of type ``AMM`` or ``LOCKER``, before computing
  concentration.
* The summary's ``lpLockedPct`` is unreliable; use ``report.markets[].lp``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nightcrawler.http import HttpClient

__all__ = ["BASE_URL", "ReportUnavailable", "RugReport", "RugCheckClient", "parse_report"]

BASE_URL = "https://api.rugcheck.xyz/v1"


class ReportUnavailable(Exception):
    """RugCheck cannot produce a report yet (400 'unable to generate report' or 404). Retry later."""

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
        "unable to generate report" and on 404; other failures raise
        :class:`nightcrawler.http.HttpError`.
        """
        raise NotImplementedError

    def report_parsed(self, mint: str) -> RugReport:
        """``parse_report(self.report(mint))`` (same exceptions)."""
        raise NotImplementedError

    def summary(self, mint: str) -> dict[str, Any]:
        """Raw ``/tokens/{mint}/report/summary`` (risks, score, score_normalised).

        Same error mapping as :meth:`report`. Not used for LP lock (unreliable).
        """
        raise NotImplementedError


def parse_report(report: dict[str, Any]) -> RugReport:
    """Normalize a raw report into :class:`RugReport` (see field docs). Never raises on missing fields."""
    raise NotImplementedError
