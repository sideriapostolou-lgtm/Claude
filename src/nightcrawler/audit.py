"""Reconciliation and P&L reporting (owner: O6).

``Auditor.reconcile()`` recomputes what the wallet SHOULD hold from the ledger's
fills and compares it with what the broker says it holds:

* expected SOL = start lamports (kv ``paper.start_lamports`` /
  ``live.start_lamports``) + sum(``fill.sol_delta_lamports()``);
* expected tokens[mint] = sum(``fill.token_delta()``) per mint;
* drift = broker - expected. Paper: any drift is a bug (``ok=False``).
  Live: token drift beyond 1 base unit -> ``ok=False``; SOL drift is reported
  (deposits/withdrawals and unmodelled fees cause it) but only flags when
  negative beyond ``SOL_DRIFT_TOLERANCE_LAMPORTS``.

It also builds per-trade P&L (realized, fees, impact) and a daily summary.
All amounts lamports unless named ``*_usd``; ``*_pct`` are percent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nightcrawler.models import Fill, Position

__all__ = ["SOL_DRIFT_TOLERANCE_LAMPORTS", "TradePnL", "DailySummary", "AuditReport", "Auditor",
           "trade_pnl", "daily_summaries"]

SOL_DRIFT_TOLERANCE_LAMPORTS = 100_000  # 0.0001 SOL


@dataclass(slots=True)
class TradePnL:
    """Realized result of one position (open positions: realized part only)."""

    position_id: str
    mint: str
    symbol: str
    opened_at: float
    closed_at: float | None
    status: str
    cost_lamports: int
    proceeds_lamports: int
    fees_lamports: int
    rent_lamports: int
    realized_lamports: int
    realized_pct: float | None  # percent of cost
    avg_price_impact_pct: float | None  # mean over the position's fills
    exit_reason: str | None
    fills: int


@dataclass(slots=True)
class DailySummary:
    """Per UTC day (by close time for realized P&L)."""

    day: str
    trades_closed: int
    wins: int
    losses: int
    realized_lamports: int
    fees_lamports: int
    realized_usd: float | None  # at each fill's sol_usd


@dataclass(slots=True)
class AuditReport:
    ok: bool
    mode: str
    checked_at: float
    expected_sol_lamports: int | None
    broker_sol_lamports: int | None
    sol_drift_lamports: int | None
    token_drift: dict[str, dict[str, int]] = field(default_factory=dict)  # {mint: {expected, actual, drift}}
    issues: list[str] = field(default_factory=list)
    trades: list[TradePnL] = field(default_factory=list)
    daily: list[DailySummary] = field(default_factory=list)
    totals: dict[str, Any] = field(default_factory=dict)  # realized_lamports, fees_lamports, trades, win_rate_pct
    chain_ok: bool | None = None
    chain_first_bad_seq: int | None = None


def trade_pnl(position: Position, fills: list[Fill]) -> TradePnL:
    """PURE: P&L of one position from its fills (fills not belonging to it are ignored)."""
    raise NotImplementedError


def daily_summaries(trades: list[TradePnL], fills: list[Fill]) -> list[DailySummary]:
    """PURE: group closed trades by UTC day of ``closed_at`` (ascending days)."""
    raise NotImplementedError


class Auditor:
    """Reconciles ledger vs broker; also verifies the receipt chain."""

    def __init__(self, ledger: Any, broker: Any, clock: Any | None = None) -> None:
        self.ledger = ledger
        self.broker = broker
        self.clock = clock

    def reconcile(self, verify_chain: bool = True) -> AuditReport:
        """Build an :class:`AuditReport` (never raises on drift; raises only on storage errors).

        ``broker`` may be None (offline report): balance comparison is skipped
        and noted in ``issues``.
        """
        raise NotImplementedError

    @staticmethod
    def format_text(report: AuditReport) -> str:
        """Human-readable multi-line summary for ``nightcrawler report`` (SOL with 4 decimals)."""
        raise NotImplementedError
