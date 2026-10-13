"""The Kalshi companion's earned-growth ladder: a bigger window only after the bot has earned it.

Owner, 2026-10-13 ~18:40 UTC, after Claude proposed this rule: "Max $50,000 a window build the ladder".

Rung r sizes a window at the configured SPEEDDESK_KALSHI_WINDOW_USD (the owner's floor, $10 on Railway) plus $5 a
rung, up to $50,000 (or SPEEDDESK_KALSHI_LADDER_MAX_WINDOW_USD when lower). At every rung the open budget is twice
the window, the contract cap (so the first buy) is half the window in contracts (5 at $10, never below 1) and the
daily stop is 60 % of the window ($6 at $10). Rung 0 is exactly the configured limits, and no rung goes below them.
The lifetime stop never scales: real money still switches off at -$10 total since launch. No rung goes above the
risk book's own ceilings (speeddesk_live_model.HARD_*: $20 a window, $40 open, $12 a day): until those are raised,
the ladder's top is the rung whose window reaches $20 (rung 2 from $10).

Promotion, one rung at a time, needs all five since the current rung began:
1. at least 96 settled windows traded at this rung;
2. gain G (total P&L now minus total P&L when the rung began) of at least 2 sigma sqrt(n), where sigma is the
   larger of the realized per-window SD at this rung and 10.5 % of the rung's window;
3. house money: total P&L + $10 at least 3 x 0.55 x the next rung's window (the worst replayed window at the next
   size is at most a third of the room above the lifetime stop);
4. no reconciliation stop and no stop of any kind (total, daily, reconciliation) in the last 24 hours;
5. available cash (cash less pending reservations and unconfirmed spending) of at least the next rung's open budget.
Demotion, one rung and never below 0: total P&L at or below its peak at this rung less 60 % of the rung's window.
A stop of any kind while a promotion still waits for its boundary cancels it. Counters restart after any change.

A change takes effect at the next window boundary, for windows that start at or after it: a window that has
begun keeps the limits it started with. Pure logic: no network, no credentials, no orders.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from itertools import islice
from typing import Any, Literal

from .speeddesk_live_model import HARD_WINDOW_USD, LiveLimits, LiveRiskBook
from .speeddesk_model import EPSILON

STEP_USD = 5.0
CEILING_USD = 50_000.0
PROMOTE_WINDOWS = 96
SIGMA_FLOOR = 0.105
HOUSE_MULTIPLE = 1.65  # 3 x 0.55: the worst replayed window is about 55 % of the window
GIVEBACK = 0.6
DAY_STOP_SHARE = 0.6
QUIET_S = 86_400.0
BOUNDARY_S = 900.0
# Cash older than this cannot support a promotion (the live loop reads it about once a second).
CASH_MAX_AGE_S = 60.0
# Per-window results written to the saved state; the books keep every one and rebuild the full list on restart.
KEPT_RESULTS = 192
STATE_VERSION = 1


def max_rung(base_window_usd: float, max_window_usd: float) -> int:
    """The highest rung whose window stays within the ceilings and the configured maximum."""
    ceiling = min(max_window_usd, CEILING_USD, HARD_WINDOW_USD)
    if not math.isfinite(ceiling) or ceiling <= base_window_usd + EPSILON:
        return 0
    return math.floor((ceiling - base_window_usd) / STEP_USD + 1e-9)


def rung_limits(base: LiveLimits, rung: int, max_window_usd: float = CEILING_USD) -> LiveLimits:
    """One rung's limits. Rung 0 is the configured limits; no rung goes below them or above the ceilings."""
    if rung <= 0:
        return base
    window = max(base.window_usd, min(base.window_usd + STEP_USD * rung, max_window_usd, CEILING_USD,
                                      HARD_WINDOW_USD))
    # LiveLimits clamps again to the risk book's own ceilings (window, open, day and the $10 total).
    return replace(base, window_usd=window, open_usd=max(base.open_usd, 2 * window),
                   day_loss_usd=max(base.day_loss_usd, round(DAY_STOP_SHARE * window, 6)),
                   clip=max(base.clip, float(max(1, math.floor(window / 2 + 1e-9)))))


def limits_view(limits: LiveLimits) -> dict[str, float]:
    return {"window_usd": limits.window_usd, "open_usd": limits.open_usd, "day_stop_usd": limits.day_loss_usd,
            "clip": limits.clip, "total_stop_usd": limits.total_loss_usd}


def next_boundary(book: LiveRiskBook, now: float) -> float:
    """The first window boundary after now: the close of every window already open (or opening before the next
    quarter hour), so no window that has begun changes its limits."""
    boundary = (math.floor(now / BOUNDARY_S) + 1) * BOUNDARY_S
    ends = [spec.end for spec in book.windows.values() if spec.start < boundary and spec.end > now]
    return max([boundary, *ends])


def _utc(value: float | None) -> str | None:
    return None if value is None else datetime.fromtimestamp(value, UTC).isoformat(timespec="seconds")


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Invalid persisted ladder number")
    return float(value)


def _rung(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Invalid persisted ladder rung")
    return value


@dataclass
class LadderState:
    # Windows that start at or after rung_from use `rung`; earlier windows keep `prior_rung`.
    rung: int = 0
    prior_rung: int = 0
    rung_from: float = 0.0
    # When the current rung's counters began, and the total P&L and its peak since then.
    started_at: float = 0.0
    start_pnl: float = 0.0
    peak_pnl: float = 0.0
    last_stop_at: float | None = None
    # Settled windows traded at this rung: each one's P&L, in settlement order.
    results: dict[str, float] = field(default_factory=dict)
    last_change: dict[str, Any] | None = None

    def to_state(self) -> dict[str, Any]:
        kept = dict(reversed(list(islice(reversed(self.results.items()), KEPT_RESULTS))))
        return {"version": STATE_VERSION, "rung": self.rung, "prior_rung": self.prior_rung,
                "rung_from": self.rung_from, "started_at": self.started_at, "start_pnl": self.start_pnl,
                "peak_pnl": self.peak_pnl, "last_stop_at": self.last_stop_at, "windows": len(self.results),
                "results": kept, "last_change": self.last_change}

    @classmethod
    def from_state(cls, saved: Any) -> LadderState:
        if not isinstance(saved, dict) or saved.get("version") != STATE_VERSION:
            raise ValueError("Unsupported ladder state")
        results = saved.get("results", {})
        last_change = saved.get("last_change")
        if not isinstance(results, dict) or any(not isinstance(key, str) for key in results):
            raise ValueError("Invalid persisted ladder results")
        if last_change is not None and not isinstance(last_change, dict):
            raise ValueError("Invalid persisted ladder change")
        last_stop = saved.get("last_stop_at")
        return cls(rung=_rung(saved["rung"]), prior_rung=_rung(saved["prior_rung"]),
                   rung_from=_number(saved["rung_from"]), started_at=_number(saved["started_at"]),
                   start_pnl=_number(saved["start_pnl"]), peak_pnl=_number(saved["peak_pnl"]),
                   last_stop_at=None if last_stop is None else _number(last_stop),
                   results={key: _number(value) for key, value in results.items()}, last_change=last_change)


class Ladder:
    """The rung schedule and its promotion and demotion rules; the risk book asks it for each window's limits."""

    def __init__(self, base: LiveLimits, *, enabled: bool = True, max_window_usd: float = CEILING_USD,
                 windows_needed: int = PROMOTE_WINDOWS) -> None:
        self.base = base
        self.enabled = enabled
        # The setting (the owner's maximum is $50,000) and what the code ceilings let the ladder reach today.
        self.configured_max_window_usd = min(max_window_usd, CEILING_USD)
        self.max_window_usd = min(max_window_usd, CEILING_USD, HARD_WINDOW_USD)
        self.top = max_rung(base.window_usd, self.max_window_usd) if enabled else 0
        self.windows_needed = windows_needed
        self.state = LadderState()
        self._limits: dict[int, LiveLimits] = {}
        self._seen = 0  # settled windows already walked, in the book's settlement order
        self._stats: tuple[int, float, float] = (0, 0.0, 0.0)  # windows, mean and SD of their P&L

    # ---- start and restore --------------------------------------------------------------------------------
    def start(self, book: LiveRiskBook, now: float, saved: Any = None) -> str:
        """Restore a saved ladder, or begin at rung 0; returns what happened ("new", "restored", "clamped",
        "off", "reset_off" or "unreadable"). Anything doubtful starts again at rung 0, the configured limits."""
        note = "new"
        state: LadderState | None = None
        if saved is not None:
            try:
                state = LadderState.from_state(saved)
                note = "restored"
            except (KeyError, TypeError, ValueError):
                note = "unreadable"
        if not self.enabled:
            note = "reset_off" if state is not None and max(state.rung, state.prior_rung) > 0 else "off"
            state = None
        if state is None:
            self.state = self._fresh(book, now)
        else:
            if max(state.rung, state.prior_rung) > self.top:  # the configured maximum was lowered
                state.rung, state.prior_rung = min(state.rung, self.top), min(state.prior_rung, self.top)
                note = "clamped"
            # The books are saved in the same write as the ladder and are the authority: the count is rebuilt
            # from them, so the saved results (only the latest, for the record) can never inflate it.
            state.results = {}
            self.state = state
        self._rebuild(book)
        return note

    def _fresh(self, book: LiveRiskBook, now: float) -> LadderState:
        return LadderState(rung_from=next_boundary(book, now), started_at=now, start_pnl=book.realized_pnl,
                           peak_pnl=book.realized_pnl)

    def _rebuild(self, book: LiveRiskBook) -> None:
        """Count every settled window of this rung from the books (they hold all of them, archive included)."""
        traded = {fill.window for fill in book.fills.values()}
        for slug, result in book.settled.items():
            self._count(book, slug, result.pnl_usd, traded)
        self._seen = len(book.settled)
        self.state.peak_pnl = max(self.state.peak_pnl, book.realized_pnl)
        self._refresh_stats()

    def _count(self, book: LiveRiskBook, slug: str, pnl: float, traded: set[str]) -> None:
        spec = book.windows.get(slug)
        if spec is not None and spec.start >= self.state.rung_from - EPSILON and slug in traded:
            self.state.results.setdefault(slug, pnl)

    def _fold(self, book: LiveRiskBook) -> None:
        """Walk windows settled since the last look, in settlement order, for the count and the peak."""
        settled = book.settled
        if len(settled) == self._seen:
            return
        if len(settled) < self._seen:  # never expected: the books only grow; recount from them
            self._rebuild(book)
            return
        traded = {fill.window for fill in book.fills.values()}
        new = list(settled)[self._seen:]
        running = book.realized_pnl - sum(settled[slug].pnl_usd for slug in new)
        for slug in new:
            running += settled[slug].pnl_usd
            self.state.peak_pnl = max(self.state.peak_pnl, running)
            self._count(book, slug, settled[slug].pnl_usd, traded)
        self._seen = len(settled)
        self.state.peak_pnl = max(self.state.peak_pnl, book.realized_pnl)
        self._refresh_stats()

    def _refresh_stats(self) -> None:
        values = list(self.state.results.values())
        count = len(values)
        mean = sum(values) / count if count else 0.0
        sd = math.sqrt(sum((value - mean) ** 2 for value in values) / (count - 1)) if count > 1 else 0.0
        self._stats = (count, mean, sd)

    # ---- the limits each window uses --------------------------------------------------------------------
    def rung_for(self, start: float) -> int:
        """The rung of a window that starts at `start` (also the rung in force at a time `start`)."""
        if not self.enabled:
            return 0
        rung = self.state.rung if start >= self.state.rung_from - EPSILON else self.state.prior_rung
        return max(0, min(rung, self.top))

    def limits_at_rung(self, rung: int) -> LiveLimits:
        cached = self._limits.get(rung)
        if cached is None:
            if len(self._limits) > 64:
                self._limits.clear()
            cached = self._limits[rung] = rung_limits(self.base, rung, self.max_window_usd)
        return cached

    def limits_for_start(self, start: float) -> LiveLimits:
        return self.limits_at_rung(self.rung_for(start))

    # ---- promotion and demotion ---------------------------------------------------------------------------
    def evaluate(self, book: LiveRiskBook, now: float) -> dict[str, Any] | None:
        """Bring the counters up to date; returns the record of a promotion or demotion when one is decided."""
        self._fold(book)
        risk = book.risk_status(now)
        stopped = bool(risk["halted"] or risk["integrity_error"] or risk["day_stopped"])
        if stopped:
            self.state.last_stop_at = now
        if not self.enabled:
            return None
        rung, prior, pending = self.state.rung, self.state.prior_rung, now < self.state.rung_from
        if pending and rung > prior and stopped:  # condition 4 broke before the bigger windows began
            return self._change("cancel", prior, book, now, risk)
        demotion = self.demotion(book)
        if demotion["due"]:
            if pending and rung < prior:
                return None  # a demotion already waits for its boundary: one rung per boundary
            return self._change("demote", prior if pending and rung > prior else rung - 1, book, now, risk)
        if pending or rung >= self.top:
            return None
        check = self.promotion(book, now, risk)
        return self._change("promote", rung + 1, book, now, risk) if check["ready"] else None

    def demotion(self, book: LiveRiskBook) -> dict[str, Any]:
        self._fold(book)
        window = self.limits_at_rung(self.state.rung).window_usd
        limit = GIVEBACK * window
        line = self.state.peak_pnl - limit
        return {"due": self.state.rung > 0 and book.realized_pnl <= line + EPSILON,
                "peak_pnl_usd": self.state.peak_pnl, "total_pnl_usd": book.realized_pnl,
                "giveback_usd": max(0.0, self.state.peak_pnl - book.realized_pnl), "giveback_limit_usd": limit,
                "line_usd": line if self.state.rung > 0 else None, "at_floor": self.state.rung == 0}

    def promotion(self, book: LiveRiskBook, now: float, risk: dict[str, Any] | None = None) -> dict[str, Any]:
        """Progress toward the next rung: each of the five conditions with its number and what it needs."""
        self._fold(book)
        risk = risk if risk is not None else book.risk_status(now)
        rung = self.state.rung
        count, _mean, sd = self._stats
        current = self.limits_at_rung(rung)
        following = self.limits_at_rung(rung + 1) if self.enabled and rung < self.top else None
        sigma = max(sd, SIGMA_FLOOR * current.window_usd)
        gain = book.realized_pnl - self.state.start_pnl
        gain_needed = 2 * sigma * math.sqrt(count)
        room = book.realized_pnl + self.base.total_loss_usd
        room_needed = HOUSE_MULTIPLE * following.window_usd if following else None
        cash, cash_at = risk["available_cash_usd"], risk["cash_at"]
        cash_fresh = cash is not None and cash_at is not None and 0 <= now - cash_at <= CASH_MAX_AGE_S
        cash_needed = following.open_usd if following else None
        quiet_since = None if self.state.last_stop_at is None else self.state.last_stop_at + QUIET_S
        blocked: list[str] = []
        if not self.enabled:
            blocked.append("ladder_off")
        if following is None:
            blocked.append("at_ceiling")
        if now < self.state.rung_from:
            blocked.append("change_pending")
        if count < self.windows_needed:
            blocked.append("windows")
        if gain + EPSILON < gain_needed or count == 0:
            blocked.append("gain")
        if room_needed is not None and room + EPSILON < room_needed:
            blocked.append("house_money")
        if (risk["integrity_error"] or risk["halted"] or risk["day_stopped"]
                or (quiet_since is not None and now < quiet_since)):
            blocked.append("stops")
        if cash_needed is not None and not (cash_fresh and cash is not None and cash + EPSILON >= cash_needed):
            blocked.append("cash")
        return {"ready": not blocked, "blocked": blocked, "next_rung": rung + 1 if following else None,
                "next_limits": limits_view(following) if following else None,
                "windows": count, "windows_needed": self.windows_needed,
                "gain_usd": gain, "gain_needed_usd": gain_needed, "sigma_usd": sigma, "sd_usd": sd,
                "room_usd": room, "room_needed_usd": room_needed,
                "available_cash_usd": cash if cash_fresh else None, "cash_needed_usd": cash_needed,
                "last_stop_at": self.state.last_stop_at, "quiet_from": quiet_since}

    def _change(self, action: Literal["promote", "demote", "cancel"], target: int, book: LiveRiskBook, now: float,
                risk: dict[str, Any]) -> dict[str, Any]:
        old = self.state
        pending = now < old.rung_from
        boundary = old.rung_from if pending else next_boundary(book, now)
        prior = old.prior_rung if pending else old.rung
        target = max(0, min(target, self.top))
        record: dict[str, Any] = {
            "action": action, "from_rung": old.rung, "to_rung": target, "rung_in_force": prior,
            "effective_from": boundary, "effective_from_utc": _utc(boundary),
            "limits_before": limits_view(self.limits_at_rung(old.rung)),
            "limits_after": limits_view(self.limits_at_rung(target)),
            "rung_started_at": old.started_at, "start_pnl_usd": old.start_pnl,
            "promotion": self.promotion(book, now, risk), "demotion": self.demotion(book),
            "state": {"promote": "up one rung", "demote": "down one rung",
                      "cancel": "waiting promotion cancelled by a stop"}[action]
                     + f"; windows starting {_utc(boundary)} on use these limits; the window under way keeps its own"}
        self.state = LadderState(rung=target, prior_rung=prior, rung_from=boundary, started_at=now,
                                 start_pnl=book.realized_pnl, peak_pnl=book.realized_pnl,
                                 last_stop_at=old.last_stop_at,
                                 last_change={key: record[key] for key in
                                              ("action", "from_rung", "to_rung", "effective_from")} | {"at": now})
        self._refresh_stats()
        return record

    # ---- what the panel and the status line show -------------------------------------------------------
    def panel(self, book: LiveRiskBook, now: float, risk: dict[str, Any] | None = None) -> dict[str, Any]:
        risk = risk if risk is not None else book.risk_status(now)
        in_force = self.rung_for(now)
        pending = now < self.state.rung_from and self.state.rung != self.state.prior_rung
        return {"enabled": self.enabled, "rung": in_force, "ladder_rung": self.state.rung,
                "max_window_usd": self.max_window_usd, "configured_max_window_usd": self.configured_max_window_usd,
                "top_rung": self.top,
                "limits": limits_view(self.limits_at_rung(in_force)),
                "change_pending": pending, "effective_from": self.state.rung_from if pending else None,
                "pending_limits": limits_view(self.limits_at_rung(self.state.rung)) if pending else None,
                "rung_started_at": self.state.started_at, "start_pnl_usd": self.state.start_pnl,
                "promotion": self.promotion(book, now, risk), "demotion": self.demotion(book),
                "last_change": self.state.last_change}

    def to_state(self) -> dict[str, Any]:
        return self.state.to_state()
