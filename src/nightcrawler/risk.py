"""Risk guardrails (owner: O5). Decides IF and HOW MUCH, never what.

Limits are measured in SOL (lamports), not USD: the bot trades memecoins
against SOL, and SOL/USD moves are not its decisions. The dashboard shows both.

Equity (lamports) = free SOL + open positions marked at mid price (see
``models.EquityPoint``). The engine writes an equity snapshot every
``EQUITY_INTERVAL_S`` via ``ledger.record_equity``; RiskManager reads them.
Only snapshots of the CURRENT ``TRADING_MODE`` count (a paper history on the
same ledger never sets the peak or the day start of a live wallet).

GAP RISK (G23): a stop-loss does not bound a loss - every measured rug was one sell that took 84-97 %. So
every risk sum counts what a position can lose in one rug, :data:`L_MAX` (0.95, a code constant, never a
setting) x the larger of its ticket (the SOL its remaining tokens cost) and its marked value
(:func:`position_at_risk_lamports`), never ticket x stop distance. :func:`risk_room` turns the limits
below into the worst-case loss a NEW ticket may still add; :meth:`RiskManager.size_position` (given the
open positions) caps the ticket at ``room / L_MAX`` - at 20 % sizing a $100 account gets a $15.79 first
ticket, because $20 x 0.95 is more than the 15 % daily budget - and ``can_open`` refuses when not even a
``MIN_POSITION_USD`` ticket fits. Here day loss = start-of-day equity - equity (realized + marked) and
at risk = the sum over open positions:

* daily loss (G23): day loss + at risk + new x L_MAX <= DAILY_LOSS_LIMIT_PCT x start of day;
* daily budget (G38): the same sum <= DAILY_RISK_BUDGET_PCT x start of day (today's gains count as room);
* cushion (G38): at risk + new x L_MAX <= equity - (1 - MAX_DRAWDOWN_HALT_PCT) x peak, so even if every
  open ticket rugs the account stays above the halt's floor (the 50 % cliff alone could end ~78 % down:
  three tickets opened at 49 %);
* total at risk (G38): at risk + new x L_MAX <= MAX_AT_RISK_PCT x equity (alongside MAX_OPEN_POSITIONS).

These limits only ever refuse or shrink an entry; exits are never affected.

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
   Also refused when the WORST CASE breaks the limit: day loss + at risk + a
   ``MIN_POSITION_USD`` ticket x L_MAX (no minimum ticket without ``sol_usd``).
5. ``[risk_budget]``, ``[cushion]``, ``[at_risk]``: the same worst case against the
   daily budget, the drawdown cushion and the total-at-risk cap.
6. ``[max_positions]`` open positions >= MAX_OPEN_POSITIONS.
7. ``[already_open]`` a position in this mint is open.
8. ``[cooldown]`` this mint was closed less than COOLDOWN_MIN ago.
9. ``[wallet_cap]`` live only: wallet value USD > MAX_WALLET_USD (an unknown
   wallet value also refuses - fail closed).
Returns ``(True, "ok")`` when all pass.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence, cast

from nightcrawler.clock import Clock
from nightcrawler.config import Settings
from nightcrawler.logging_setup import get_logger
from nightcrawler.models import LAMPORTS_PER_SOL, OPENING_RENT_RESERVE_LAMPORTS, KillMode, Position, lamports_to_sol

__all__ = ["RiskManager", "RiskRoom", "size_position_usd", "position_at_risk_lamports", "risk_room", "KILL_WORDS",
           "L_MAX"]

log = get_logger(__name__)

KILL_WORDS: tuple[str, ...] = ("off", "stop", "sell_all")
KV_HALTED = "risk.halted"
KV_PEAK_RESET_TS = "risk.peak_reset_ts"
_SECONDS_PER_DAY = 86_400
#: Tolerance for float noise in USD comparisons (a hundredth of a cent).
_USD_EPS = 1e-4
#: What one position can lose in one rug, as a fraction of its ticket or value (G23). A CODE constant
#: (human-reviewed, never a setting, never learnable): the 9 measured rugs were single sells that took
#: 84-97 %, so the -18 % stop says nothing about the loss.
L_MAX = 0.95
#: ``RiskRoom`` budgets in ``can_open`` order: (field, rule id).
_BUDGET_RULES = (("daily_loss", "daily_loss"), ("daily_budget", "risk_budget"), ("cushion", "cushion"),
                 ("total", "at_risk"))


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


def position_at_risk_lamports(position: Position, sol_usd: float | None = None) -> int:
    """PURE: what ``position`` can lose in one rug, ``ceil(L_MAX x max(ticket, marked value))`` in lamports.

    ticket = the SOL its remaining tokens cost (``cost_lamports`` pro rata after partial sells); marked value
    = its tokens at ``last_price_usd`` (needs ``sol_usd``). Never less than ticket x L_MAX, and a position that
    went up risks its gain too. A closed or empty position risks 0.
    """
    if not position.is_open or position.token_amount <= 0:
        return 0
    ticket = position.cost_lamports
    if position.initial_token_amount > 0:
        ticket = position.cost_lamports * min(position.token_amount, position.initial_token_amount) \
            // position.initial_token_amount
    marked = 0
    if position.last_price_usd and position.last_price_usd > 0 and sol_usd and sol_usd > 0:
        marked = position.value_lamports(position.last_price_usd, sol_usd)
    return math.ceil(L_MAX * max(ticket, marked))


@dataclass(frozen=True, slots=True)
class RiskRoom:
    """Worst-case loss (lamports, float) a NEW ticket may still add under each budget (module docstring).

    ``at_risk``: what the open positions can already lose in rugs. A negative room means the budget is
    already broken by what is lost and at risk. ``day_start`` and ``peak`` are the inputs it was built on.
    """

    at_risk: float
    daily_loss: float
    daily_budget: float
    cushion: float
    total: float
    day_start: float
    peak: float

    @property
    def smallest(self) -> float:
        return min(getattr(self, name) for name, _ in _BUDGET_RULES)

    @property
    def binding(self) -> str:
        """The budget with the least room (``daily_loss``, ``daily_budget``, ``cushion`` or ``total``)."""
        return min((getattr(self, name), i, name) for i, (name, _) in enumerate(_BUDGET_RULES))[2]

    def max_ticket(self) -> int | None:
        """The largest new ticket (lamports) whose rug still fits every budget: ``room / L_MAX`` (>= 0);
        None (no cap) only if L_MAX is not positive."""
        if L_MAX <= 0:
            return None
        return max(0, int(self.smallest / L_MAX))


def risk_room(*, equity: float, day_start: float, peak: float, at_risk: float, daily_loss_limit_pct: float,
              daily_risk_budget_pct: float, max_drawdown_pct: float, max_at_risk_pct: float) -> RiskRoom:
    """PURE: the :class:`RiskRoom` of an account (any one unit: lamports for the bot, dollars in simulations).

    ``day_start``: start-of-UTC-day equity; ``peak``: the equity peak; ``at_risk``: sum of
    :func:`position_at_risk_lamports` of the open positions.
    """
    lost_today = day_start - equity  # realized + marked (negative on a winning day)
    return RiskRoom(at_risk=at_risk,
                    daily_loss=daily_loss_limit_pct * day_start - lost_today - at_risk,
                    daily_budget=daily_risk_budget_pct * day_start - lost_today - at_risk,
                    cushion=equity - (1.0 - max_drawdown_pct) * peak - at_risk,
                    total=max_at_risk_pct * equity - at_risk, day_start=day_start, peak=peak)


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
                      network_fee_lamports: int | None = None,
                      open_positions: Sequence[Position] | None = None) -> int:
        """Lamports to spend on a new position (0 = skip).

        ``size_position_usd(equity_usd, POSITION_PCT, MIN_POSITION_USD,
        MAX_POSITION_USD)`` converted to lamports; with ``open_positions`` (the engine always passes
        them) capped at :meth:`RiskRoom.max_ticket` (a rug of the new ticket must fit every budget, see the
        module docstring), then capped so that
        ``available_lamports - SOL_RESERVE - NETWORK_FEE - OPENING_RENT_RESERVE``
        stays >= 0; if a cap pushes it below ``MIN_POSITION_USD`` -> 0.
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
        if open_positions is not None and target > 0:
            cap = self.risk_room(open_positions, equity_lamports, sol_usd).max_ticket()
            if cap is not None and cap < target:
                if lamports_to_sol(cap) * sol_usd + _USD_EPS < s.min_position_usd:
                    return 0
                target = cap
        available = equity_lamports if available_lamports is None else available_lamports
        fee = max(s.network_fee_lamports, network_fee_lamports or 0)
        spendable = available - s.sol_reserve_lamports - fee - OPENING_RENT_RESERVE_LAMPORTS
        if spendable >= target:
            return target
        capped = max(spendable, 0)
        if lamports_to_sol(capped) * sol_usd + _USD_EPS < s.min_position_usd:
            return 0
        return capped

    def risk_room(self, open_positions: Sequence[Position], equity_lamports: int,
                  sol_usd: float | None = None) -> RiskRoom:
        """:func:`risk_room` of this account now: today's start (rule 4; current equity without snapshots),
        the peak (never below current equity) and the open positions of ``open_positions`` at L_MAX."""
        s = self.settings
        start = self.day_start_equity()
        peak = self.peak_equity()
        at_risk = sum(position_at_risk_lamports(p, sol_usd) for p in open_positions if p.is_open)
        return risk_room(equity=equity_lamports, day_start=equity_lamports if start is None else start,
                         peak=equity_lamports if peak is None else max(peak, equity_lamports), at_risk=at_risk,
                         daily_loss_limit_pct=s.daily_loss_limit_pct, daily_risk_budget_pct=s.daily_risk_budget_pct,
                         max_drawdown_pct=s.max_drawdown_halt_pct, max_at_risk_pct=s.max_at_risk_pct)

    # ------------------------------------------------------------------ gate
    def can_open(self, mint: str, open_positions: Sequence[Position], equity_lamports: int,
                 wallet_usd: float | None = None, *, sol_usd: float | None = None) -> tuple[bool, str]:
        """Entry gate; see module docstring for order and reason strings. ``sol_usd`` values the open
        positions' marks and the ``MIN_POSITION_USD`` ticket the budgets must still have room for."""
        reason = (self._kill_rule()
                  or self._halted_rule()
                  or self._drawdown_rule(equity_lamports)
                  or self._daily_loss_rule(equity_lamports)
                  or self._budget_rules(open_positions, equity_lamports, sol_usd)
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

    def _budget_rules(self, open_positions: Sequence[Position], equity_lamports: int,
                      sol_usd: float | None) -> str | None:
        """Rules 4 (worst case) and 5: refused when a ``MIN_POSITION_USD`` ticket's rug does not fit a budget."""
        s = self.settings
        room = self.risk_room(open_positions, equity_lamports, sol_usd)
        need = L_MAX * s.min_position_usd / sol_usd * LAMPORTS_PER_SOL if sol_usd and sol_usd > 0 else 0.0
        start = room.day_start
        n_open = sum(1 for p in open_positions if p.is_open)
        rugs = f"{n_open} open position(s) can lose {_sol(room.at_risk)} in rugs (L_MAX {L_MAX:.0%} each)"
        new = f"a new ${s.min_position_usd:g} ticket's rug" if need > 0 else "a new ticket"
        for name, rule in _BUDGET_RULES:
            left = getattr(room, name)
            if left >= need or (rule == "daily_loss" and room.at_risk + need <= 0):
                continue  # (with nothing at risk and no ticket to price, rule 4's own check is the daily loss)
            if rule == "daily_loss" or rule == "risk_budget":
                pct = s.daily_loss_limit_pct if rule == "daily_loss" else s.daily_risk_budget_pct
                knob = "DAILY_LOSS_LIMIT_PCT" if rule == "daily_loss" else "DAILY_RISK_BUDGET_PCT"
                lost = start - equity_lamports
                worst = (lost + room.at_risk) / start if start > 0 else math.inf
                return (f"[{rule}] worst case today {worst:.1%} of today's start {_sol(start)}: "
                        f"{'down' if lost >= 0 else 'up'} {abs(lost) / start if start > 0 else 0:.1%} and {rugs}; "
                        f"no room for {new} ({knob} {pct:.0%}); waits for open positions to close or the next "
                        "UTC day")
            if rule == "cushion":
                floor = (1.0 - s.max_drawdown_halt_pct) * room.peak
                return (f"[cushion] equity {_sol(equity_lamports)} is only {_sol(equity_lamports - floor)} above the "
                        f"drawdown floor {_sol(floor)} (1 - MAX_DRAWDOWN_HALT_PCT {s.max_drawdown_halt_pct:.0%} "
                        f"of the peak {_sol(room.peak)}) and {rugs}: no room for {new}")
            return (f"[at_risk] {rugs}, {room.at_risk / equity_lamports if equity_lamports > 0 else 0:.1%} of "
                    f"equity {_sol(equity_lamports)}: no room for {new} (MAX_AT_RISK_PCT {s.max_at_risk_pct:.0%})")
        return None

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
