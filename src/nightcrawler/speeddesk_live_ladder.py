"""The Kalshi companion's earned-growth ladder: a bigger window only after the bot has earned it.

Owner, 2026-10-13 ~18:40 UTC, after Claude proposed this rule: "Max $50,000 a window build the ladder".

Rung r sizes a window at the configured SPEEDDESK_KALSHI_WINDOW_USD (the owner's floor, $10 on Railway) plus $5 a
rung, up to $50,000 (or SPEEDDESK_KALSHI_LADDER_MAX_WINDOW_USD when lower). At every rung the open budget is twice
the window, the contract cap (so the first buy) is half the window in contracts (5 at $10, never below 1) and the
daily stop is 60 % of the window ($6 at $10). Rung 0 is exactly the configured limits, and no rung goes below them.
The lifetime stop never scales: real money still switches off at -$10 total since launch. No rung goes above the
risk book's own ceilings (the LiveLimits clamp: $20 a window, $40 open, $12 a day, 25 contracts today): the top is
the last rung the risk book keeps unchanged (rung 2 from $10 until those ceilings are raised).

Promotion, one rung at a time, needs all five since the current rung began:
1. at least 96 settled windows traded at this rung;
2. gain G (the settled P&L of this rung's windows, less what is still at risk) of at least 2 sigma sqrt(n), where
   sigma is the larger of the realized per-window SD at this rung and 10.5 % of the rung's window;
3. house money: total P&L + $10, less money at risk (and less a resume anchor above zero), at least 3 x 0.55 x the
   next rung's window (the worst replayed window at the next size is at most a third of the room above the stop);
4. no stop of any kind in the last 24 hours and none now: a reconciliation error, the total stop, the daily stop
   (its flag, a daily loss within $1 of it, or even a one-contract buy refused by the day or total stop);
5. available cash (cash less pending reservations and unconfirmed spending) of at least the next rung's open budget.
Promotion also waits while the worst case (total P&L less money at risk) is at or below the demotion line.
Demotion, one rung and never below 0: total P&L at or below its peak at this rung less 60 % of the rung's window.

A decision takes effect at the next window boundary, for windows that start at or after it: a window that has begun
keeps the limits it started with. A promotion is only provisional until then: the rung in force keeps its counters,
its demotion line and its limits, any stop cancels it, and at the first look at or after the boundary all five
conditions and the demotion line are checked again (with money still at risk counted as lost) before any order in
the new window; it is cancelled if any fails or if a window from the boundary on has already traded. The counters
(n, G, the peak) cover only windows that start at or after the rung began: an earlier rung's window that settles
later moves the starting P&L and the peak with it. Pure logic: no network, no credentials, no orders.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from itertools import islice
from typing import Any, Literal

from .speeddesk_live_model import LiveLimits, LiveRiskBook
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
# One contract never costs more than $1 with its fee: a daily stop with less than this left has tripped.
ONE_CONTRACT_USD = 1.0
# Per-window results written to the saved state; the books keep every one and rebuild the full list on restart.
KEPT_RESULTS = 192
STATE_VERSION = 2

Action = Literal["promote", "confirm", "demote", "cancel"]


def _numbers(base: LiveLimits, rung: int, max_window_usd: float) -> tuple[float, float, float, float]:
    """A rung's window, open budget, daily stop and contract cap as the rule writes them, before any clamp."""
    window = max(base.window_usd, min(base.window_usd + STEP_USD * rung, max_window_usd, CEILING_USD))
    return (window, max(base.open_usd, 2 * window), max(base.day_loss_usd, round(DAY_STOP_SHARE * window, 6)),
            max(base.clip, float(max(1, math.floor(window / 2 + 1e-9)))))


def rung_limits(base: LiveLimits, rung: int, max_window_usd: float = CEILING_USD) -> LiveLimits:
    """One rung's limits. Rung 0 is the configured limits; no rung goes below them or above the ceilings."""
    if rung <= 0:
        return base
    window, open_usd, day_loss, clip = _numbers(base, rung, max_window_usd)
    # LiveLimits clamps again to the risk book's own ceilings (window, open, day, contract cap and the $10 total).
    return replace(base, window_usd=window, open_usd=open_usd, day_loss_usd=day_loss, clip=clip)


def _kept(base: LiveLimits, rung: int, max_window_usd: float) -> bool:
    limits = rung_limits(base, rung, max_window_usd)
    return (limits.window_usd, limits.open_usd, limits.day_loss_usd, limits.clip) == _numbers(base, rung,
                                                                                            max_window_usd)


def max_rung(base: LiveLimits, max_window_usd: float) -> int:
    """The highest rung whose window stays within the configured maximum and $50,000, and whose limits the risk
    book's own clamp leaves unchanged (the ladder never names those ceilings: it asks the clamp)."""
    ceiling = min(max_window_usd, CEILING_USD)
    if not math.isfinite(ceiling) or ceiling <= base.window_usd + EPSILON:
        return 0
    low, high = 0, math.floor((ceiling - base.window_usd) / STEP_USD + 1e-9)
    while low < high:  # every number grows with the rung and the clamp is fixed: the kept rungs are a prefix
        middle = (low + high + 1) // 2
        if _kept(base, middle, ceiling):
            low = middle
        else:
            high = middle - 1
    return low


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
    # Windows that start at or after rung_from use `rung` (a promotion: only once confirmed); earlier windows keep
    # `prior_rung`.
    rung: int = 0
    prior_rung: int = 0
    rung_from: float = 0.0
    # False while a promotion waits for its re-check at the boundary.
    confirmed: bool = True
    # The counters cover windows that start at or after counted_from, the start of the rung they count (the rung in
    # force while a promotion waits): since when, the total P&L they start from and its peak since then.
    counted_from: float = 0.0
    started_at: float = 0.0
    start_pnl: float = 0.0
    peak_pnl: float = 0.0
    last_stop_at: float | None = None
    # Settled windows traded at the counted rung: each one's P&L, in settlement order.
    results: dict[str, float] = field(default_factory=dict)
    last_change: dict[str, Any] | None = None
    # The configured limits the rungs were earned on (limits_view): other limits start again at rung 0.
    floor: dict[str, float] = field(default_factory=dict)

    @property
    def waiting(self) -> bool:
        """A promotion is decided but not yet re-checked at its boundary."""
        return self.rung > self.prior_rung and not self.confirmed

    @property
    def counted_rung(self) -> int:
        return self.prior_rung if self.waiting else self.rung

    def to_state(self) -> dict[str, Any]:
        kept = dict(reversed(list(islice(reversed(self.results.items()), KEPT_RESULTS))))
        return {"version": STATE_VERSION, "rung": self.rung, "prior_rung": self.prior_rung,
                "rung_from": self.rung_from, "confirmed": self.confirmed, "counted_from": self.counted_from,
                "started_at": self.started_at, "start_pnl": self.start_pnl, "peak_pnl": self.peak_pnl,
                "last_stop_at": self.last_stop_at, "windows": len(self.results), "results": kept,
                "last_change": self.last_change, "floor": self.floor}

    @classmethod
    def from_state(cls, saved: Any) -> LadderState:
        if not isinstance(saved, dict) or saved.get("version") != STATE_VERSION:
            raise ValueError("Unsupported ladder state")
        results, last_change, floor = saved.get("results", {}), saved.get("last_change"), saved["floor"]
        if not isinstance(results, dict) or any(not isinstance(key, str) for key in results):
            raise ValueError("Invalid persisted ladder results")
        if last_change is not None and not isinstance(last_change, dict):
            raise ValueError("Invalid persisted ladder change")
        if not isinstance(saved["confirmed"], bool) or not isinstance(floor, dict) or any(
                not isinstance(key, str) for key in floor):
            raise ValueError("Invalid persisted ladder flags")
        last_stop = saved.get("last_stop_at")
        return cls(rung=_rung(saved["rung"]), prior_rung=_rung(saved["prior_rung"]),
                   rung_from=_number(saved["rung_from"]), confirmed=saved["confirmed"],
                   counted_from=_number(saved["counted_from"]), started_at=_number(saved["started_at"]),
                   start_pnl=_number(saved["start_pnl"]), peak_pnl=_number(saved["peak_pnl"]),
                   last_stop_at=None if last_stop is None else _number(last_stop),
                   results={key: _number(value) for key, value in results.items()}, last_change=last_change,
                   floor={key: _number(value) for key, value in floor.items()})


class Ladder:
    """The rung schedule and its promotion and demotion rules; the risk book asks it for each window's limits."""

    def __init__(self, base: LiveLimits, *, enabled: bool = True, max_window_usd: float = CEILING_USD,
                 windows_needed: int = PROMOTE_WINDOWS) -> None:
        self.base = base
        self.enabled = enabled
        # The setting (the owner's maximum is $50,000) and the highest window the risk book's ceilings allow today.
        self.configured_max_window_usd = min(max_window_usd, CEILING_USD)
        self.reach = max_rung(base, self.configured_max_window_usd)
        self.max_window_usd = rung_limits(base, self.reach, self.configured_max_window_usd).window_usd
        self.top = self.reach if enabled else 0
        self.windows_needed = windows_needed
        self.state = LadderState(floor=self._floor())
        self._limits: dict[int, LiveLimits] = {}
        self._seen = 0  # settled windows already walked, in the book's settlement order
        self._stats: tuple[int, float, float] = (0, 0.0, 0.0)  # windows, mean and SD of their P&L

    def _floor(self) -> dict[str, float]:
        return limits_view(self.base)

    # ---- start and restore --------------------------------------------------------------------------------
    def attach(self, book: LiveRiskBook) -> None:
        """The book asks the ladder for each window's limits and tells it the moment a loss stop binds."""
        book.window_limits = self.limits_for_start
        book.stop_listener = self.note_stop

    def start(self, book: LiveRiskBook, now: float, saved: Any = None) -> str:
        """Restore a saved ladder, or begin at rung 0; returns what happened ("new", "restored", "rebased",
        "clamped", "off", "reset_off" or "unreadable"). Anything doubtful starts again at rung 0 (the configured
        limits), or at the top when the configured maximum was lowered below the saved rung."""
        note, state = "new", None
        if saved is not None:
            try:
                state = LadderState.from_state(saved)
                self._check(state, book, now)
                note = "restored"
            except (KeyError, TypeError, ValueError):
                note, state = "unreadable", None
        last_stop = state.last_stop_at if state is not None else None
        rung = 0
        if state is not None and not self._same_floor(state.floor):
            note, state = "rebased", None  # the rungs were earned on other configured limits
        if not self.enabled:
            note = "reset_off" if state is not None and max(state.rung, state.prior_rung) > 0 else "off"
            state = None
        elif state is not None and max(state.rung, state.prior_rung) > self.top:  # the maximum was lowered
            note, rung, state = "clamped", self.top, None
        self.state = state if state is not None else self._fresh(book, now, rung, last_stop)
        # The books are saved in the same write as the ladder and are the authority: the counters are rebuilt from
        # them, so a saved list or starting P&L can never inflate them.
        self._recount(book)
        return note

    def _check(self, state: LadderState, book: LiveRiskBook, now: float) -> None:
        """A saved schedule this code could have written: one rung per boundary, nothing beyond the next one."""
        latest = next_boundary(book, now) + EPSILON
        if (abs(state.rung - state.prior_rung) > 1 or state.rung_from > latest or state.counted_from > latest
                or (not state.confirmed and state.rung <= state.prior_rung)
                or (state.rung > state.prior_rung and state.confirmed and state.rung_from > now + EPSILON)):
            raise ValueError("Impossible persisted ladder schedule")

    def _same_floor(self, floor: dict[str, float]) -> bool:
        mine = self._floor()
        return set(floor) == set(mine) and all(math.isclose(floor[key], mine[key], abs_tol=1e-9) for key in mine)

    def _fresh(self, book: LiveRiskBook, now: float, rung: int = 0, last_stop_at: float | None = None) -> LadderState:
        boundary = next_boundary(book, now)
        return LadderState(rung=rung, prior_rung=rung, rung_from=boundary, counted_from=boundary, started_at=now,
                           start_pnl=book.realized_pnl, peak_pnl=book.realized_pnl, last_stop_at=last_stop_at,
                           floor=self._floor())

    def _recount(self, book: LiveRiskBook) -> None:
        """The counted rung's windows from the books (they hold all of them, archive included): the count, the
        results, the P&L the rung starts from and its peak, in settlement order."""
        state = self.state
        traded = {fill.window for fill in book.fills.values()}
        state.results, running, best = {}, 0.0, 0.0
        for slug, result in book.settled.items():
            if self._counted(book, slug):
                running += result.pnl_usd
                best = max(best, running)
                if slug in traded:
                    state.results[slug] = result.pnl_usd
        state.start_pnl = book.realized_pnl - running
        state.peak_pnl = state.start_pnl + best
        self._seen = len(book.settled)
        self._refresh_stats()

    def _counted(self, book: LiveRiskBook, slug: str) -> bool:
        spec = book.windows.get(slug)
        return spec is not None and spec.start >= self.state.counted_from - EPSILON

    def _fold(self, book: LiveRiskBook) -> None:
        """Walk windows settled since the last look, in settlement order. A window of the counted rung adds to its
        count and its peak; an earlier rung's window (it began before the rung) moves the start and the peak with
        it, so neither its gain nor its loss is this rung's."""
        settled = book.settled
        if len(settled) == self._seen:
            return
        if len(settled) < self._seen:  # never expected: the books only grow; recount from them
            self._recount(book)
            return
        state = self.state
        traded = {fill.window for fill in book.fills.values()}
        new = list(settled)[self._seen:]
        running = book.realized_pnl - sum(settled[slug].pnl_usd for slug in new)
        for slug in new:
            pnl = settled[slug].pnl_usd
            running += pnl
            if self._counted(book, slug):
                state.peak_pnl = max(state.peak_pnl, running)
                if slug in traded:
                    state.results.setdefault(slug, pnl)
            else:
                state.start_pnl += pnl
                state.peak_pnl += pnl
        self._seen = len(settled)
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
        state = self.state
        if start < state.rung_from - EPSILON or state.waiting:  # a promotion applies only once re-checked
            rung = state.prior_rung
        else:
            rung = state.rung
        return max(0, min(rung, self.top))

    def limits_at_rung(self, rung: int) -> LiveLimits:
        rung = max(0, min(rung, self.reach))  # never a rung the risk book's ceilings would change
        cached = self._limits.get(rung)
        if cached is None:
            if len(self._limits) > 64:
                self._limits.clear()
            cached = self._limits[rung] = rung_limits(self.base, rung, self.configured_max_window_usd)
        return cached

    def limits_for_start(self, start: float) -> LiveLimits:
        return self.limits_at_rung(self.rung_for(start))

    # ---- stops ------------------------------------------------------------------------------------------------
    def note_stop(self, at: float) -> None:
        """A loss stop bound at `at` (the risk book calls this the moment it happens)."""
        if math.isfinite(at):
            last = self.state.last_stop_at
            self.state.last_stop_at = at if last is None else max(last, at)

    @staticmethod
    def _stop_now(risk: dict[str, Any]) -> bool:
        """A stop in force: a reconciliation error, the total stop, or the daily stop (its flag, or less than one
        contract's cost of it left after today's settled loss)."""
        day_stop = risk["limits"]["day_loss_usd"]
        return bool(risk["halted"] or risk["integrity_error"] or risk["day_stopped"]
                    or risk["day_loss_usd"] + ONE_CONTRACT_USD >= day_stop - EPSILON)

    def observe(self, book: LiveRiskBook, now: float) -> dict[str, Any]:
        """Bring the counters up to date and note any stop in force (also before a resume or reset token clears
        one at startup); returns the book's risk status."""
        self._fold(book)
        risk = book.risk_status(now)
        if self._stop_now(risk):
            self.note_stop(now)
        if book.stop_hit_at is not None:
            self.note_stop(book.stop_hit_at)
        return risk

    def due(self, now: float) -> bool:
        """A waiting promotion has reached its boundary: look now, before any order in the new window."""
        return self.enabled and self.state.waiting and now >= self.state.rung_from - EPSILON

    # ---- promotion and demotion ---------------------------------------------------------------------------
    def evaluate(self, book: LiveRiskBook, now: float) -> dict[str, Any] | None:
        """Bring the counters up to date; returns the record of a decision (promote, confirm, demote, cancel)."""
        risk = self.observe(book, now)
        if not self.enabled:
            return None
        state = self.state
        if state.waiting:
            # The rung in force keeps its own demotion line until the bigger windows begin.
            if self.demotion(book)["due"]:
                return self._change("demote", state.prior_rung - 1, book, now, risk)
            at_boundary = now >= state.rung_from - EPSILON
            check = self.promotion(book, now, risk, confirming=at_boundary)
            if at_boundary:
                return self._change("confirm" if check["ready"] else "cancel", state.rung, book, now, risk, check)
            if "stops" in check["blocked"]:  # condition 4 broke before the bigger windows began
                return self._change("cancel", state.rung, book, now, risk, check)
            return None
        if now < state.rung_from - EPSILON and state.rung != state.prior_rung:
            return None  # a demotion already waits for its boundary: one rung per boundary
        if self.demotion(book)["due"]:
            return self._change("demote", state.rung - 1, book, now, risk)
        if state.rung >= self.top:
            return None
        check = self.promotion(book, now, risk)
        return self._change("promote", state.rung + 1, book, now, risk, check) if check["ready"] else None

    def demotion(self, book: LiveRiskBook) -> dict[str, Any]:
        """The counted rung's demotion line (the rung in force while a promotion waits)."""
        self._fold(book)
        rung = self.state.counted_rung
        limit = GIVEBACK * self.limits_at_rung(rung).window_usd
        line = self.state.peak_pnl - limit
        return {"due": rung > 0 and book.realized_pnl <= line + EPSILON, "rung": rung,
                "peak_pnl_usd": self.state.peak_pnl, "total_pnl_usd": book.realized_pnl,
                "giveback_usd": max(0.0, self.state.peak_pnl - book.realized_pnl), "giveback_limit_usd": limit,
                "line_usd": line if rung > 0 else None, "at_floor": rung == 0}

    def promotion(self, book: LiveRiskBook, now: float, risk: dict[str, Any] | None = None, *,
                  confirming: bool = False) -> dict[str, Any]:
        """Progress toward the next rung: each condition with its number and what it needs. `confirming` is the
        re-check of a waiting promotion at its boundary."""
        self._fold(book)
        risk = risk if risk is not None else book.risk_status(now)
        state = self.state
        rung = state.counted_rung
        count, _mean, sd = self._stats
        current = self.limits_at_rung(rung)
        following = self.limits_at_rung(rung + 1) if self.enabled and rung < self.top else None
        at_risk = risk["at_risk_usd"]
        sigma = max(sd, SIGMA_FLOOR * current.window_usd)
        gain = book.realized_pnl - state.start_pnl
        gain_counted = gain - at_risk  # what is still open can still be lost
        gain_needed = 2 * sigma * math.sqrt(count)
        # The room above the lifetime stop: total P&L + $10, less a resume anchor above zero and what is at risk.
        room = book.realized_pnl + self.base.total_loss_usd - max(0.0, book.stop_anchor) - at_risk
        room_needed = HOUSE_MULTIPLE * following.window_usd if following else None
        line = state.peak_pnl - GIVEBACK * current.window_usd if rung > 0 else None
        cash, cash_at = risk["available_cash_usd"], risk["cash_at"]
        cash_fresh = cash is not None and cash_at is not None and 0 <= now - cash_at <= CASH_MAX_AGE_S
        cash_needed = following.open_usd if following else None
        quiet_since = None if state.last_stop_at is None else state.last_stop_at + QUIET_S
        started = confirming and self._traded_from(book, state.rung_from)
        blocked: list[str] = []
        if not self.enabled:
            blocked.append("ladder_off")
        if following is None:
            blocked.append("at_ceiling")
        if (state.waiting and not confirming) or (not state.waiting and now < state.rung_from - EPSILON
                                                  and state.rung != state.prior_rung):
            blocked.append("change_pending")
        if count < self.windows_needed:
            blocked.append("windows")
        if gain_counted + EPSILON < gain_needed or count == 0:
            blocked.append("gain")
        if room_needed is not None and room + EPSILON < room_needed:
            blocked.append("house_money")
        if self._stop_now(risk) or (quiet_since is not None and now < quiet_since):
            blocked.append("stops")
        if cash_needed is not None and not (cash_fresh and cash is not None and cash + EPSILON >= cash_needed):
            blocked.append("cash")
        if line is not None and book.realized_pnl - at_risk <= line + EPSILON:
            blocked.append("giveback")  # what is open could cross the demotion line
        if started:
            blocked.append("window_started")  # a window from the boundary on already traded at the old limits
        return {"ready": not blocked, "blocked": blocked, "rung": rung, "next_rung": rung + 1 if following else None,
                "next_limits": limits_view(following) if following else None,
                "windows": count, "windows_needed": self.windows_needed,
                "gain_usd": gain, "at_risk_usd": at_risk, "gain_counted_usd": gain_counted,
                "gain_needed_usd": gain_needed, "sigma_usd": sigma, "sd_usd": sd,
                "room_usd": room, "room_needed_usd": room_needed,
                "available_cash_usd": cash if cash_fresh else None, "cash_needed_usd": cash_needed,
                "last_stop_at": state.last_stop_at, "quiet_from": quiet_since, "recheck": confirming}

    @staticmethod
    def _traded_from(book: LiveRiskBook, start: float) -> bool:
        """Any order or fill in a window that starts at or after `start`."""
        windows = {intent.window for intent in book.intents.values()} | {fill.window for fill in book.fills.values()}
        return any((spec := book.windows.get(slug)) is not None and spec.start >= start - EPSILON for slug in windows)

    def _change(self, action: Action, target: int, book: LiveRiskBook, now: float, risk: dict[str, Any],
                check: dict[str, Any] | None = None) -> dict[str, Any]:
        old = self.state
        in_force = self.rung_for(now)
        target = max(0, min(target, self.top))
        if action == "promote":
            # Provisional: the rung in force keeps its counters, its demotion line and its limits until the re-check.
            boundary = next_boundary(book, now)
            new = replace(old, rung=target, prior_rung=old.rung, rung_from=boundary, confirmed=False)
            from_rung, state_text = old.rung, (f"decided; re-checked at {_utc(boundary)} before any order in the new "
                                               "window, and cancelled by any stop until then")
        elif action == "confirm":
            boundary = old.rung_from
            new = replace(old, confirmed=True, counted_from=boundary, started_at=now, results={})
            from_rung, state_text = old.prior_rung, (f"re-checked and applied: windows starting {_utc(boundary)} "
                                                     "on use these limits")
        elif action == "cancel":
            # The rung in force never changed: it keeps its counters and its demotion line.
            boundary = old.rung_from
            target = old.prior_rung
            new = replace(old, rung=target, confirmed=True)
            reasons = ", ".join(check["blocked"]) if check else "stop"
            from_rung, state_text = old.rung, f"waiting promotion cancelled ({reasons}); the limits stay as they are"
        else:
            boundary = next_boundary(book, now)
            from_rung = old.counted_rung
            new = LadderState(rung=target, prior_rung=from_rung, rung_from=boundary, counted_from=boundary,
                              started_at=now, last_stop_at=old.last_stop_at, floor=old.floor)
            state_text = ("down one rung" + (f", dropping the waiting promotion to rung {old.rung}" if old.waiting
                                             else "")
                          + f"; windows starting {_utc(boundary)} on use these limits; the window under way keeps "
                            "its own")
        record: dict[str, Any] = {
            "action": action, "from_rung": from_rung, "to_rung": target, "rung_in_force": in_force,
            "effective_from": boundary, "effective_from_utc": _utc(boundary),
            "limits_before": limits_view(self.limits_at_rung(from_rung)),
            "limits_after": limits_view(self.limits_at_rung(target)),
            "rung_started_at": old.started_at, "start_pnl_usd": old.start_pnl,
            "promotion": check if check is not None else self.promotion(book, now, risk),
            "demotion": self.demotion(book), "state": state_text}
        new.last_change = {key: record[key] for key in ("action", "from_rung", "to_rung", "effective_from")} | {
            "at": now}
        self.state = new
        if action in ("confirm", "demote"):
            self._recount(book)  # the new rung counts only windows from its boundary on
        return record

    # ---- what the panel and the status line show -------------------------------------------------------
    def panel(self, book: LiveRiskBook, now: float, risk: dict[str, Any] | None = None) -> dict[str, Any]:
        risk = risk if risk is not None else book.risk_status(now)
        state = self.state
        in_force = self.rung_for(now)
        pending = state.rung != state.prior_rung and (state.waiting or now < state.rung_from - EPSILON)
        return {"enabled": self.enabled, "rung": in_force, "ladder_rung": state.rung,
                "max_window_usd": self.max_window_usd, "configured_max_window_usd": self.configured_max_window_usd,
                "top_rung": self.top,
                "limits": limits_view(self.limits_at_rung(in_force)),
                "change_pending": pending, "recheck_pending": state.waiting,
                "effective_from": state.rung_from if pending else None,
                "pending_limits": limits_view(self.limits_at_rung(state.rung)) if pending else None,
                "rung_started_at": state.started_at, "start_pnl_usd": state.start_pnl,
                "promotion": self.promotion(book, now, risk), "demotion": self.demotion(book),
                "last_change": state.last_change}

    def to_state(self) -> dict[str, Any]:
        return self.state.to_state()
