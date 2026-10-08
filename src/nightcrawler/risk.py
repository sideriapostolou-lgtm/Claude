"""Risk guardrails (owner: O5). Decides IF and HOW MUCH, never what.

Limits are measured in SOL (lamports), not USD: the bot trades memecoins
against SOL, and SOL/USD moves are not its decisions. The dashboard shows both.

Equity (lamports) = free SOL + open positions marked at mid price (see
``models.EquityPoint``). The engine writes an equity snapshot every
``EQUITY_INTERVAL_S`` via ``ledger.record_equity``; RiskManager reads them.

``can_open`` checks, in this order (first failure is the returned reason;
reason strings start with the rule id in brackets):

1. ``[kill]`` kill switch != off (env ``KILL_SWITCH`` or ``DATA_DIR/KILL`` file).
2. ``[halted]`` drawdown halt engaged (persisted in kv ``risk.halted``; only
   :meth:`RiskManager.reset_halt` clears it).
3. ``[drawdown]`` equity < peak * (1 - MAX_DRAWDOWN_HALT_PCT) -> ENGAGE the halt
   (kv + ``halt`` receipt) and refuse. Peak = max equity since the last reset.
4. ``[daily_loss]`` equity < start-of-UTC-day equity * (1 - DAILY_LOSS_LIMIT_PCT)
   (start-of-day = first snapshot at/after 00:00 UTC today, else the last
   one before it, else current equity). Resets automatically next UTC day.
5. ``[max_positions]`` open positions >= MAX_OPEN_POSITIONS.
6. ``[already_open]`` a position in this mint is open.
7. ``[cooldown]`` this mint was closed less than COOLDOWN_MIN ago.
8. ``[wallet_cap]`` live only: wallet value USD > MAX_WALLET_USD.
Returns ``(True, "ok")`` when all pass.
"""

from __future__ import annotations

from typing import Any, Sequence

from nightcrawler.clock import Clock
from nightcrawler.config import Settings
from nightcrawler.models import KillMode, Position

__all__ = ["RiskManager", "size_position_usd", "KILL_WORDS"]

KILL_WORDS: tuple[str, ...] = ("off", "stop", "sell_all")


def size_position_usd(equity_usd: float, position_pct: float, min_position_usd: float,
                      max_position_usd: float) -> float:
    """PURE sizing shared with the backtester.

    ``target = equity_usd * position_pct`` clamped to ``max_position_usd``;
    returns 0.0 if the target is below ``min_position_usd`` (never rounds UP
    to the minimum - too small to be worth the fees). Negative/zero equity -> 0.0.
    """
    raise NotImplementedError


class RiskManager:
    """Stateful guardrails backed by the ledger (equity history, positions, kv)."""

    def __init__(self, settings: Settings, ledger: Any, clock: Clock) -> None:
        self.settings = settings
        self.ledger = ledger
        self.clock = clock

    def size_position(self, equity_lamports: int, sol_usd: float, available_lamports: int | None = None) -> int:
        """Lamports to spend on a new position (0 = skip).

        ``size_position_usd(equity_usd, POSITION_PCT, MIN_POSITION_USD,
        MAX_POSITION_USD)`` converted to lamports, then capped so that
        ``available_lamports - SOL_RESERVE - NETWORK_FEE - TOKEN_ACCOUNT_RENT``
        stays >= 0; if the cap pushes it below ``MIN_POSITION_USD`` -> 0.
        ``available_lamports`` defaults to ``equity_lamports``. ``sol_usd <= 0`` -> 0.
        """
        raise NotImplementedError

    def can_open(self, mint: str, open_positions: Sequence[Position], equity_lamports: int,
                 wallet_usd: float | None = None) -> tuple[bool, str]:
        """Entry gate; see module docstring for order and reason strings."""
        raise NotImplementedError

    def kill_mode(self) -> KillMode:
        """Most severe of env ``KILL_SWITCH`` and the ``DATA_DIR/KILL`` file.

        File contents are stripped/lower-cased: ``off`` / ``stop`` /
        ``sell_all``; an EMPTY or unrecognized file means ``stop`` (fail safe).
        Severity: sell_all > stop > off. Missing file = off.
        """
        raise NotImplementedError

    def is_halted(self) -> tuple[bool, str]:
        """``(True, reason)`` while the drawdown halt is engaged (kv ``risk.halted``)."""
        raise NotImplementedError

    def halt(self, reason: str) -> None:
        """Engage the halt: kv ``risk.halted = {"halted": true, "reason", "ts"}`` + ``halt`` receipt."""
        raise NotImplementedError

    def reset_halt(self, note: str = "manual reset") -> None:
        """Clear the halt AND restart the equity peak from now (kv ``risk.peak_reset_ts``) + ``reset`` receipt."""
        raise NotImplementedError

    def day_start_equity(self, now: float | None = None) -> int | None:
        """Start-of-UTC-day equity in lamports (see rule 4), or None without snapshots."""
        raise NotImplementedError

    def peak_equity(self) -> int | None:
        """Max equity (lamports) since ``risk.peak_reset_ts`` (or ever), or None."""
        raise NotImplementedError
