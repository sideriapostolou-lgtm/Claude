"""Pull the Kalshi companion's resting bids the moment its fair value moves.

Owner, 2026-10-13 ~20:15 UTC: "Pulling bids the instant price moves ... test with our current bot cause it's
something that we will for sure have, just gotta make it good". Evidence (replay of "pull all bids for 5 s after the
quoted side's fair moves >= 1c within 5 s"): +28.1c a window on strict fills, -8.7c on touch fills, 60 s markout
+24-28c, 18% fewer fills; the best of 68 variants, not proven. So it runs on real money with the practice twin as its
control: the twin keeps the rule without the pull on the same windows (speeddesk_live.py, docs/SPEEDDESK_SPEC.md 9.3).

This module only keeps the books of the rule; it sends nothing. The companion samples its Up fair value on every
Bitcoin tick and every cancel check, asks whether a window is held, and cancels through its own cancel path (one
cancel per order, never re-sent once Kalshi accepted it, the write budget unchanged). A cancel never adds risk.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from .speeddesk_model import utc_day

EPS = 1e-8
DAYS_KEPT = 31


def _moment(value: Any) -> float | None:
    """A saved epoch-seconds value, or None for anything else."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


@dataclass(frozen=True)
class PullRule:
    """SPEEDDESK_KALSHI_PULL, _PULL_MOVE, _PULL_LOOKBACK_S and _PULL_HOLD_S (validated in config.py)."""

    enabled: bool = True
    move: float = 0.01
    lookback_s: float = 5.0
    hold_s: float = 5.0

    @classmethod
    def from_settings(cls, settings: Any) -> PullRule:
        return cls(enabled=settings.speeddesk_kalshi_pull, move=settings.speeddesk_kalshi_pull_move,
                   lookback_s=settings.speeddesk_kalshi_pull_lookback_s, hold_s=settings.speeddesk_kalshi_pull_hold_s)


@dataclass
class _Fairs:
    """One window's Up fair over the lookback as running extremes: ``low`` keeps rising values (its first is the
    lowest fair in the lookback), ``high`` falling ones (its first is the highest). Each sample enters and leaves each
    at most once, so a sample costs O(1) on average whatever the lookback; nothing is cut short by a count."""

    low: deque[tuple[float, float]] = field(default_factory=deque)
    high: deque[tuple[float, float]] = field(default_factory=deque)
    last_at: float = -math.inf


@dataclass
class _Pull:
    """One pull, from its first trigger until its hold ends (each later trigger extends it)."""

    window: str
    started_at: float
    move: float
    held_until: float
    counted: bool
    bids: int = 0


class PullGuard:
    """Per window: the Up fair over the last ``lookback_s``, when the move last reached ``move``, and the hold.

    A window is held from a trigger until ``hold_s`` after the last one; a trigger is any sample whose fair is at least
    ``move`` from some fair in the lookback, either direction (Up and Down move by the same amount). A resting bid
    decided at or before the last trigger is pulled. ``held`` and ``blocks`` only read, so the send guard may call them
    from the HTTP worker thread; everything else runs on the event loop.
    """

    def __init__(self, rule: PullRule, now: float, saved: Any = None) -> None:
        self.rule = rule
        self.fairs: dict[str, _Fairs] = {}
        self.last_trigger: dict[str, float] = {}
        self.active: set[str] = set()  # windows whose latest sample was a trigger
        self.range: dict[str, tuple[float, float, float]] = {}  # lowest and highest fair in the lookback, and when
        self.open: dict[str, _Pull] = {}
        self.days: dict[str, dict[str, int]] = {}
        self.since: float | None = None
        # When the guard first went live, kept when a setting changes, so the "week before" baseline never covers
        # days the pull was already on (review, 2026-10-13).
        self.first_live: float | None = None
        if isinstance(saved, Mapping) and saved.get("version") == 1:
            days = saved.get("days")
            if isinstance(days, Mapping) and all(
                    isinstance(day, str) and isinstance(row, Mapping)
                    and all(isinstance(row.get(key), int) and not isinstance(row.get(key), bool) and row[key] >= 0
                            for key in ("pulls", "bids")) for day, row in days.items()):
                self.days = {day: {"pulls": row["pulls"], "bids": row["bids"]} for day, row in days.items()}
            since = _moment(saved.get("since"))
            # The A/B runs from the moment the guard went live with these settings; a changed setting starts it again.
            if rule.enabled and saved.get("rule") == asdict(rule) and since is not None and since <= now:
                self.since = since
            first, earlier = _moment(saved.get("first_live")), saved.get("rule")
            if first is None and isinstance(earlier, Mapping) and earlier.get("enabled") is True:
                first = since  # saved before first_live existed: the guard was live from its since
            self.first_live = first if first is not None and first <= now else None
            # A hold survives a restart: a window pulled just before it stays held until its hold ends.
            held = saved.get("held")
            if rule.enabled and isinstance(held, Mapping):
                for window, last in held.items():
                    moment = _moment(last)
                    if isinstance(window, str) and moment is not None and moment <= now <= moment + rule.hold_s:
                        self.last_trigger[window] = moment
        if rule.enabled and self.since is None:
            self.since = now
        if self.since is not None and (self.first_live is None or self.since < self.first_live):
            self.first_live = self.since

    def _day(self, now: float) -> dict[str, int]:
        return self.days.setdefault(utc_day(now), {"pulls": 0, "bids": 0})

    def observe(self, window: str, up: float, now: float, *, count: bool) -> None:
        """One sample of the bot's Up fair in ``window``. ``count``: a new pull counts (live switches on, bids allowed)."""
        if not self.rule.enabled or not math.isfinite(up) or not math.isfinite(now):
            return
        fairs = self.fairs.setdefault(window, _Fairs())
        if now < fairs.last_at:
            # The clock went back: start the history again rather than misdate a move, and keep a hold no longer
            # than hold_s from now (it would otherwise last the size of the step).
            fairs.low.clear()
            fairs.high.clear()
            self.active.discard(window)
            if window in self.last_trigger:
                self.last_trigger[window] = min(self.last_trigger[window], now)
            if window in self.open:
                self.open[window].held_until = min(self.open[window].held_until, now + self.rule.hold_s)
        fairs.last_at = now
        horizon = now - self.rule.lookback_s - EPS
        for line in (fairs.low, fairs.high):
            while line and line[0][0] < horizon:
                line.popleft()
        while fairs.low and fairs.low[-1][1] >= up:
            fairs.low.pop()  # never the lowest again while this sample is in the lookback
        fairs.low.append((now, up))
        while fairs.high and fairs.high[-1][1] <= up:
            fairs.high.pop()
        fairs.high.append((now, up))
        low, high = fairs.low[0][1], fairs.high[0][1]
        self.range[window] = (low, high, now)
        move = max(up - low, high - up)
        if move + EPS < self.rule.move:
            self.active.discard(window)
            return
        self.last_trigger[window] = now
        self.active.add(window)
        pull = self.open.get(window)
        if pull is None:
            self.open[window] = _Pull(window, now, move, now + self.rule.hold_s, count)
            if count:
                self._day(now)["pulls"] += 1
        else:
            pull.move, pull.held_until = max(pull.move, move), now + self.rule.hold_s

    def held(self, window: str, now: float) -> bool:
        """No new resting bid in ``window``: its latest sample is a trigger, or the last one was under hold_s ago."""
        last = self.last_trigger.get(window)
        if not self.rule.enabled or last is None:
            return False
        return now <= last + self.rule.hold_s + EPS or (window in self.active and now <= last + self.rule.lookback_s)

    def pulled_since(self, window: str, decided_at: float) -> bool:
        """A resting bid decided at ``decided_at`` was up (or on its way) when the fair last moved: pull it."""
        last = self.last_trigger.get(window)
        return self.rule.enabled and last is not None and decided_at <= last + EPS

    def blocks(self, window: str, up: float, now: float) -> bool:
        """The send guard's last check for a resting bid: held, or the fresh fair is already a trigger."""
        if not self.rule.enabled:
            return False
        if self.held(window, now):
            return True
        recent = self.range.get(window)
        return (recent is not None and now - recent[2] <= self.rule.lookback_s
                and max(up - recent[0], recent[1] - up) + EPS >= self.rule.move)

    def note_bid(self, window: str, now: float) -> None:
        """A real resting bid cancelled by a pull (counted once per bid)."""
        self._day(now)["bids"] += 1
        if window in self.open:
            self.open[window].bids += 1

    def expire(self, now: float, *, everything: bool = False) -> list[dict[str, Any]]:
        """Close each pull whose hold has ended and return the counted ones' log lines; forget idle windows."""
        finished: list[dict[str, Any]] = []
        for window, pull in list(self.open.items()):
            if everything or now > pull.held_until + EPS and not self.held(window, now):
                del self.open[window]
                if pull.counted:
                    finished.append({"window": window, "move": round(pull.move, 4),
                                     "started_at": round(pull.started_at, 3), "held_until": round(pull.held_until, 3),
                                     "bids_pulled": pull.bids})
        horizon = self.rule.lookback_s + self.rule.hold_s
        for window in set(self.fairs) | set(self.last_trigger):
            sampled = self.fairs[window].last_at if window in self.fairs else -math.inf
            if window not in self.open and max(sampled, self.last_trigger.get(window, -math.inf)) < now - horizon:
                self.fairs.pop(window, None)
                self.last_trigger.pop(window, None)
                self.range.pop(window, None)
                self.active.discard(window)
        if len(self.days) > DAYS_KEPT:
            self.days = {day: self.days[day] for day in sorted(self.days)[-DAYS_KEPT:]}
        return finished

    def to_state(self) -> dict[str, Any]:
        return {"version": 1, "rule": asdict(self.rule), "since": self.since, "first_live": self.first_live,
                "days": self.days, "held": dict(self.last_trigger)}

    def panel(self, now: float) -> dict[str, Any]:
        today = self.days.get(utc_day(now), {"pulls": 0, "bids": 0})
        total = {key: sum(row[key] for row in self.days.values()) for key in ("pulls", "bids")}
        return {"enabled": self.rule.enabled, "move": self.rule.move, "lookback_s": self.rule.lookback_s,
                "hold_s": self.rule.hold_s, "since": self.since, "first_live": self.first_live,
                "day": utc_day(now),
                "held": {window: round(self.last_trigger[window] + self.rule.hold_s, 3)
                         for window in sorted(self.last_trigger) if self.held(window, now)},
                "pulls_today": today["pulls"], "bids_pulled_today": today["bids"],
                "pulls_31d": total["pulls"], "bids_pulled_31d": total["bids"]}


def compare(starts: Mapping[str, float], live: Mapping[str, float], twin: Mapping[str, float],
            live_maker: Iterable[tuple[str, float]], twin_maker: Iterable[tuple[str, float]],
            live_locks: Iterable[tuple[str, float, float]] = (),
            *, start: float, end: float = math.inf) -> dict[str, Any]:
    """Real companion against its practice twin over settled windows that started in [start, end).

    ``live`` and ``twin`` map each settled window that one of them traded (bought at least one contract) to its result
    in USD; ``starts`` gives each window's start. P&L is shown two ways: over the windows both traded, and over the
    windows either traded with a side that did not trade counted as 0 (a pull that keeps the real bot out of a window
    shows there). Maker fills (rows and contracts filled at a resting bid) and the real lock buys (``live_locks``:
    window, contracts, cost in USD; the twin never locks) count the windows either traded.
    """
    def inside(window: str) -> bool:
        return start <= starts.get(window, -math.inf) < end

    both = sorted(window for window in live if window in twin and inside(window))
    either = {window for window in (*live, *twin) if inside(window)}
    out: dict[str, Any] = {"windows_both_traded": len(both),
                           "live_pnl_usd": round(sum(live[window] for window in both), 4),
                           "twin_pnl_usd": round(sum(twin[window] for window in both), 4)}
    out["live_minus_twin_usd"] = round(out["live_pnl_usd"] - out["twin_pnl_usd"], 4)
    out["windows_either_traded"] = len(either)
    out["live_pnl_either_usd"] = round(sum(live.get(window, 0.0) for window in either), 4)
    out["twin_pnl_either_usd"] = round(sum(twin.get(window, 0.0) for window in either), 4)
    out["live_minus_twin_either_usd"] = round(out["live_pnl_either_usd"] - out["twin_pnl_either_usd"], 4)
    for name, rows in (("live", live_maker), ("twin", twin_maker)):
        sizes = [size for window, size in rows if window in either]
        out[f"{name}_maker_fills"] = len(sizes)
        out[f"{name}_maker_contracts"] = round(sum(sizes), 4)
        out[f"{name}_maker_fills_per_window"] = round(len(sizes) / len(either), 4) if either else None
    locks = [(size, cost) for window, size, cost in live_locks if window in either]
    out["live_locks"] = len(locks)
    out["live_lock_contracts"] = round(sum(size for size, _ in locks), 4)
    out["live_lock_cost_usd"] = round(sum(cost for _, cost in locks), 4)
    out["live_locks_per_window"] = round(len(locks) / len(either), 4) if either else None
    return out
