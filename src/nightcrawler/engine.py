"""The scheduler that ties everything together (owner: Integrator).

``Engine.tick(now)`` runs whichever stages are due; ``run_forever`` loops
``tick`` with ~1 s sleeps on the clock until stopped (SIGTERM/SIGINT set the
stop event). EVERY stage is wrapped: an exception is logged, stored in kv
``engine.last_error`` and receipted as kind ``error`` - the loop never dies.

Stages (intervals from Settings):

``discover`` (DISCOVERY_INTERVAL_S)
    ``crawler.poll()`` -> for each new candidate (at most 5 cocoon checks per
    tick; the rest wait in a FIFO queue): ``ledger.record_candidate``;
    ``cocoon.check`` -> ``ledger.record_safety``; failed ->
    ``Decision(action="reject_cocoon")`` receipt; passed -> watchlist
    (max WATCHLIST_MAX, oldest evicted) + ``Decision("watch")``.

``watch`` (WATCH_INTERVAL_S)
    Expire items older than WATCHLIST_TTL_H or whose snapshot mcap/liquidity
    left the window (``Decision("unwatch")``). ``crawler.refresh`` (DexScreener
    batch) for all items; fetch CANDLE_WINDOW_MIN 1m candles (GeckoTerminal)
    for at most MAX_CANDLE_FETCH_PER_TICK items per tick (GT budget), chosen
    in this priority: never fetched yet; then items whose current snapshot
    price is >= DIP_PCT/2 below the rolling high of their last fetched
    candles (deepest drawdown first); then least recently fetched.
    ``strategy.entry_signal`` -> if ``enter``: ``radar.scan`` (reject on flag
    or error) -> ``judge.decide(build_features(...))`` (required mode: "no"
    rejects; advisory: logged only) -> ``risk.can_open`` + ``risk.size_position``
    -> ``broker.quote("buy")`` -> ``Decision("enter")`` receipt (inputs:
    signal metrics, verdict, size, quote summary) -> ``broker.execute`` ->
    new Position (``ledger.upsert_position``). Rejections at each step get a
    ``reject_*`` decision receipt.

``positions`` (POSITION_INTERVAL_S)
    Mark open positions with Jupiter price v3 (one batched call), update
    ``peak_price_usd``/``last_price_usd``; every RADAR_INTERVAL_S also
    ``radar.scan`` them. ``strategy.exit_signal`` -> on exit: quote the sell of
    ``floor(token_amount * fraction)`` (all tokens when fraction == 1),
    ``Decision("exit"|"exit_partial")`` receipt -> ``broker.execute`` ->
    update/close the Position. Failed sells are retried next interval with a
    fresh quote (never blindly).

``kill`` (every tick)
    ``risk.kill_mode()``: ``stop`` -> no new entries; ``sell_all`` -> exit every
    position (reason ``kill_switch``) then behave like ``stop``. Mode changes
    are receipted (kind ``kill``) and stored in kv ``engine.kill_mode``.

``equity`` (EQUITY_INTERVAL_S)
    ``EquityPoint`` from broker balances + marked positions -> ``ledger.record_equity``;
    kv ``engine.heartbeat`` = now.

ORDERING GUARANTEE: a Decision/Fill receipt is appended before the engine
fetches any newer price, so recorded intent can never be edited with hindsight.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from nightcrawler.clock import Clock
from nightcrawler.config import Settings
from nightcrawler.models import Candle, MarketSnapshot, SafetyReport, TokenCandidate

__all__ = ["WatchItem", "Engine", "build_engine", "MAX_COCOON_PER_TICK", "MAX_CANDLE_FETCH_PER_TICK"]

MAX_COCOON_PER_TICK = 5
MAX_CANDLE_FETCH_PER_TICK = 3


@dataclass(slots=True)
class WatchItem:
    """A token that passed Cocoon and is being watched for an entry setup."""

    candidate: TokenCandidate
    safety: SafetyReport
    added_at: float
    snapshot: MarketSnapshot | None = None
    candles: list[Candle] = field(default_factory=list)
    candles_at: float | None = None
    last_signal_reason: str | None = None


class Engine:
    """Owns the loop; all dependencies injected (tests pass fakes)."""

    def __init__(self, settings: Settings, *, clock: Clock, ledger: Any, crawler: Any, cocoon: Any,
                 radar: Any, judge: Any, risk: Any, broker: Any, sources: Any | None = None) -> None:
        self.settings = settings
        self.clock = clock
        self.ledger = ledger
        self.crawler = crawler
        self.cocoon = cocoon
        self.radar = radar
        self.judge = judge
        self.risk = risk
        self.broker = broker
        self.sources = sources
        self.watchlist: dict[str, WatchItem] = {}
        self.stop_event = threading.Event()
        self._last_run: dict[str, float] = {}

    def tick(self, now: float) -> dict[str, Any]:
        """Run every due stage once. Returns ``{stage: "ok"|"skipped"|"error: ..."}``. Never raises."""
        raise NotImplementedError

    def run_forever(self) -> None:
        """Write a ``boot`` receipt (version, mode, public settings), then loop ``tick`` until
        :attr:`stop_event` is set. Installs SIGTERM/SIGINT handlers when on the main thread."""
        raise NotImplementedError

    def stop(self) -> None:
        """Request a graceful stop (finishes the current stage)."""
        self.stop_event.set()

    def discover(self, now: float) -> None:
        raise NotImplementedError

    def watch(self, now: float) -> None:
        raise NotImplementedError

    def manage_positions(self, now: float) -> None:
        raise NotImplementedError

    def handle_kill(self, now: float) -> str:
        """Apply the kill switch; returns the active mode."""
        raise NotImplementedError

    def snapshot_equity(self, now: float) -> None:
        raise NotImplementedError

    def sell_all(self, reason: str = "manual") -> list[Any]:
        """Exit every open position now (used by kill sell_all and the ``sell-all`` CLI). Returns fills."""
        raise NotImplementedError


def build_engine(settings: Settings, clock: Clock | None = None) -> Engine:
    """Wire real dependencies: HttpClient.from_settings -> Sources -> Crawler/Cocoon/Radar,
    Ledger(settings.db_path), Judge, RiskManager, PaperBroker or LiveBroker (by TRADING_MODE)."""
    raise NotImplementedError
