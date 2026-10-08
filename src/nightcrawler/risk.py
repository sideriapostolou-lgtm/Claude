"""Risk guardrails (owner: O5). Decides IF and HOW MUCH, never what.

Limits are measured in SOL (lamports), not USD: the bot trades memecoins
against SOL, and SOL/USD moves are not its decisions. The dashboard shows both.

Equity (lamports) = free SOL + open positions marked at mid price (see
``models.EquityPoint``). The engine writes an equity snapshot every
``EQUITY_INTERVAL_S`` via ``ledger.record_equity``; RiskManager reads them.
Only snapshots of the CURRENT ``TRADING_MODE`` count (a paper history on the
same ledger never sets the peak or the day start of a live wallet).

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
8. ``[wallet_cap]`` live only: wallet value USD > MAX_WALLET_USD (an unknown
   wallet value also refuses - fail closed).
Returns ``(True, "ok")`` when all pass.
"""

from __future__ import annotations

from typing import Any, Sequence, cast

from nightcrawler.clock import Clock
from nightcrawler.config import Settings
from nightcrawler.logging_setup import get_logger
from nightcrawler.models import LAMPORTS_PER_SOL, OPENING_RENT_RESERVE_LAMPORTS, KillMode, Position, lamports_to_sol

__all__ = ["RiskManager", "size_position_usd", "KILL_WORDS"]

log = get_logger(__name__)

KILL_WORDS: tuple[str, ...] = ("off", "stop", "sell_all")
KV_HALTED = "risk.halted"
KV_PEAK_RESET_TS = "risk.peak_reset_ts"
_SECONDS_PER_DAY = 86_400
#: Tolerance for float noise in USD comparisons (a hundredth of a cent).
_USD_EPS = 1e-4


def size_position_usd(equity_usd: float, position_pct: float, min_position_usd: float,
                      max_position_usd: float) -> float:
    """PURE sizing shared with the backtester.

    ``target = equity_usd * position_pct`` clamped to ``max_position_usd``;
    returns 0.0 if the target is below ``min_position_usd`` (never rounds UP
    to the minimum - too small to be worth the fees). Negative/zero equity -> 0.0.
    """
    if equity_usd <= 0 or position_pct <= 0:
        return 0.0
    target = min(equity_usd * position_pct, max_position_usd)
    return target if target + _USD_EPS >= min_position_usd else 0.0


def _sol(lamports: float) -> str:
    return f"{lamports_to_sol(int(lamports)):.4f} SOL"


class RiskManager:
    """Stateful guardrails backed by the ledger (equity history, positions, kv)."""

    def __init__(self, settings: Settings, ledger: Any, clock: Clock) -> None:
        self.settings = settings
        self.ledger = ledger
        self.clock = clock
        # Incremental peak cache: max equity seen since ``_peak_reset_ts`` up to ``_peak_scanned_ts``.
        self._peak: int | None = None
        self._peak_reset_ts: float | None = None
        self._peak_scanned_ts: float | None = None

    # ------------------------------------------------------------------ sizing
    def size_position(self, equity_lamports: int, sol_usd: float, available_lamports: int | None = None, *,
                      network_fee_lamports: int | None = None) -> int:
        """Lamports to spend on a new position (0 = skip).

        ``size_position_usd(equity_usd, POSITION_PCT, MIN_POSITION_USD,
        MAX_POSITION_USD)`` converted to lamports, then capped so that
        ``available_lamports - SOL_RESERVE - NETWORK_FEE - OPENING_RENT_RESERVE``
        stays >= 0; if the cap pushes it below ``MIN_POSITION_USD`` -> 0.
        ``available_lamports`` defaults to ``equity_lamports``. ``sol_usd <= 0`` -> 0.
        NETWORK_FEE is ``network_fee_lamports`` (what the broker charges now, e.g. paper's
        Helius estimate) when given, never below ``NETWORK_FEE_SOL``. OPENING_RENT_RESERVE is the most
        the brokers book as rent for a new token account (Ultra's Token-2022 figure).
        """
        if sol_usd <= 0:
            return 0
        s = self.settings
        equity_usd = lamports_to_sol(equity_lamports) * sol_usd
        target_usd = size_position_usd(equity_usd, s.position_pct, s.min_position_usd, s.max_position_usd)
        target = int(target_usd / sol_usd * LAMPORTS_PER_SOL)
        available = equity_lamports if available_lamports is None else available_lamports
        fee = max(s.network_fee_lamports, network_fee_lamports or 0)
        spendable = available - s.sol_reserve_lamports - fee - OPENING_RENT_RESERVE_LAMPORTS
        if spendable >= target:
            return target
        capped = max(spendable, 0)
        if lamports_to_sol(capped) * sol_usd + _USD_EPS < s.min_position_usd:
            return 0
        return capped

    # ------------------------------------------------------------------ gate
    def can_open(self, mint: str, open_positions: Sequence[Position], equity_lamports: int,
                 wallet_usd: float | None = None) -> tuple[bool, str]:
        """Entry gate; see module docstring for order and reason strings."""
        reason = (self._kill_rule()
                  or self._halted_rule()
                  or self._drawdown_rule(equity_lamports)
                  or self._daily_loss_rule(equity_lamports)
                  or self._positions_rules(mint, open_positions)
                  or self._cooldown_rule(mint)
                  or self._wallet_cap_rule(wallet_usd))
        return (False, reason) if reason else (True, "ok")

    def _kill_rule(self) -> str | None:
        mode = self.kill_mode()
        return f"[kill] kill switch is {mode}" if mode != "off" else None

    def _halted_rule(self) -> str | None:
        halted, reason = self.is_halted()
        return f"[halted] {reason}; entries stay halted until a manual reset" if halted else None

    def _drawdown_rule(self, equity_lamports: int) -> str | None:
        peak = self.peak_equity()
        limit = self.settings.max_drawdown_halt_pct
        if peak is None or peak <= 0 or equity_lamports >= peak * (1 - limit):
            return None
        reason = (f"equity {_sol(equity_lamports)} is {1 - equity_lamports / peak:.1%} below the peak "
                  f"{_sol(peak)} (MAX_DRAWDOWN_HALT_PCT {limit:.0%})")
        self.halt(reason)
        return f"[drawdown] {reason}; entries halted until a manual reset"

    def _daily_loss_rule(self, equity_lamports: int) -> str | None:
        start = self.day_start_equity()
        start = equity_lamports if start is None else start
        limit = self.settings.daily_loss_limit_pct
        if start <= 0 or equity_lamports >= start * (1 - limit):
            return None
        return (f"[daily_loss] equity {_sol(equity_lamports)} is {1 - equity_lamports / start:.1%} below today's "
                f"start {_sol(start)} (DAILY_LOSS_LIMIT_PCT {limit:.0%}); resumes next UTC day")

    def _positions_rules(self, mint: str, open_positions: Sequence[Position]) -> str | None:
        open_now = [p for p in open_positions if p.is_open]
        if len(open_now) >= self.settings.max_open_positions:
            return f"[max_positions] {len(open_now)} open (MAX_OPEN_POSITIONS {self.settings.max_open_positions})"
        if any(p.mint == mint for p in open_now):
            return "[already_open] a position in this mint is already open"
        return None

    def _cooldown_rule(self, mint: str) -> str | None:
        closed_at = self.ledger.last_closed_at(mint)
        if closed_at is None:
            return None
        ago_min = (self.clock.now() - closed_at) / 60
        if ago_min >= self.settings.cooldown_min:
            return None
        return f"[cooldown] closed {ago_min:.1f} min ago (COOLDOWN_MIN {self.settings.cooldown_min:g})"

    def _wallet_cap_rule(self, wallet_usd: float | None) -> str | None:
        if not self.settings.is_live:
            return None
        if wallet_usd is None:
            return "[wallet_cap] wallet value unknown; refusing new live entries"
        if wallet_usd > self.settings.max_wallet_usd:
            return (f"[wallet_cap] wallet worth ${wallet_usd:.2f} > MAX_WALLET_USD "
                    f"${self.settings.max_wallet_usd:.2f}; is this really the dedicated bot wallet?")
        return None

    # ------------------------------------------------------------------ kill switch
    def kill_mode(self) -> KillMode:
        """Most severe of env ``KILL_SWITCH`` and the ``DATA_DIR/KILL`` file.

        File contents are stripped/lower-cased (``-`` and spaces read as ``_``):
        ``off`` / ``stop`` / ``sell_all``; an EMPTY, unreadable or unrecognized
        file means ``stop`` (fail safe). Severity: sell_all > stop > off.
        Missing file = off.
        """
        modes = (self.settings.kill_switch, self._kill_file_mode())
        return cast(KillMode, max(modes, key=KILL_WORDS.index))  # .index rejects any other word

    def _kill_file_mode(self) -> str:
        try:
            text = self.settings.kill_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return "off"
        except (OSError, UnicodeDecodeError):
            return "stop"
        word = "_".join(text.strip().lower().replace("-", " ").split())
        return word if word in KILL_WORDS else "stop"

    # ------------------------------------------------------------------ halt
    def is_halted(self) -> tuple[bool, str]:
        """``(True, reason)`` while the drawdown halt is engaged (kv ``risk.halted``)."""
        state = self.ledger.get_kv(KV_HALTED)
        if isinstance(state, dict) and state.get("halted"):
            return True, str(state.get("reason") or "halted")
        return False, ""

    def halt(self, reason: str) -> None:
        """Engage the halt: kv ``risk.halted = {"halted": true, "reason", "ts"}`` + ``halt`` receipt."""
        now = self.clock.now()
        with self.ledger.transaction():
            self.ledger.set_kv(KV_HALTED, {"halted": True, "reason": reason, "ts": now})
            self.ledger.append_receipt("halt", {"reason": reason}, ts=now)
        log.warning("risk_halt reason=%s", reason)

    def reset_halt(self, note: str = "manual reset") -> None:
        """Clear the halt AND restart the equity peak from now (kv ``risk.peak_reset_ts``) + ``reset`` receipt."""
        now = self.clock.now()
        with self.ledger.transaction():
            self.ledger.set_kv(KV_HALTED, {"halted": False, "reason": note, "ts": now})
            self.ledger.set_kv(KV_PEAK_RESET_TS, now)
            self.ledger.append_receipt("reset", {"note": note, "peak_reset_ts": now}, ts=now)
        log.warning("risk_reset note=%s", note)

    # ------------------------------------------------------------------ equity history
    def day_start_equity(self, now: float | None = None) -> int | None:
        """Start-of-UTC-day equity in lamports (see rule 4), or None without snapshots."""
        now = self.clock.now() if now is None else now
        midnight = now - now % _SECONDS_PER_DAY
        mode = self.settings.trading_mode
        today = [p for p in self.ledger.equity_series(since=midnight) if p.ts <= now and p.mode == mode]
        if today:
            return today[0].equity_lamports
        latest = self.ledger.latest_equity()
        if latest is None or latest.mode != mode:
            return None
        return latest.equity_lamports if latest.ts < midnight else None

    def peak_equity(self) -> int | None:
        """Max equity (lamports) since ``risk.peak_reset_ts`` (or ever), or None.

        Scans only snapshots newer than the previous call (the reset timestamp
        is re-read every time, so a reset from another process is honoured).
        """
        reset_ts = self.ledger.get_kv(KV_PEAK_RESET_TS)
        if reset_ts != self._peak_reset_ts:
            self._peak, self._peak_reset_ts, self._peak_scanned_ts = None, reset_ts, reset_ts
        mode = self.settings.trading_mode
        for point in self.ledger.equity_series(since=self._peak_scanned_ts):
            if (reset_ts is not None and point.ts < reset_ts) or point.mode != mode:
                continue
            self._peak = point.equity_lamports if self._peak is None else max(self._peak, point.equity_lamports)
            self._peak_scanned_ts = point.ts if self._peak_scanned_ts is None else max(self._peak_scanned_ts,
                                                                                         point.ts)
        return self._peak
