"""Backtester with NO lookahead (owner: O3).

Input file format (``data/samples/*.json``, ``DATA_DIR/dataset/*.json``)::

    {"coin": str, "mint": str, "pool": str, "supply": float (whole tokens, for mcap),
     "candles": [[ts, o, h, l, c, v], ...]   # 1m, ascending, USD per whole token, v in USD
     ... any other keys (name, created_utc, patches, ...) are ignored}

Simulation rules (the contract):

* Walk candles in order. At candle ``i`` (closed at ``ts_i + 60``) the strategy
  sees ONLY candles ``[0..i]`` and ``now = ts_i + 60`` (``entry_signal`` with
  ``snapshot=None``).
* Entry fills at the NEXT candle's open (``i+1``), adjusted by the cost model:
  ``fill = open * (1 + (fee_bps_per_side + impact_bps) / 1e4)`` where
  ``impact_bps = impact_bps_per_1k_usd * size_usd / 1000``; plus
  ``network_fee_usd_per_side`` deducted from cash. No fill if there is no next candle.
* Missing minutes between candles are filled with flat zero-volume candles
  (:func:`nightcrawler.models.fill_gaps`), exactly like the live GeckoTerminal
  client does, so a gap breaks a green run in both.
* Exits are evaluated intrabar on each later candle with ``strategy.exit_levels``
  in PESSIMISTIC order: (1) gap: if open <= stop -> exit at open; (2) stop if
  ``low <= stop``; (3) take-profit if ``high >= tp`` AND the candle closes at or
  above it (partial, once); (4) trailing stop if ``low <= peak*(1-trail)`` (peak
  updated with the CLOSES of previous candles only, then this candle's close
  after the checks); (5) time stop at the candle where ``ts >= opened_at +
  max_hold``. If stop and TP are both inside one candle -> STOP first. Stops fill
  at ``min(level, close)`` (a 10 s poller never gets the exact level of a candle
  that closed below it; open on a gap); sells are then charged
  ``(1 - (fee_bps + impact_bps)/1e4)``. This FILL MODEL is part of
  :class:`CostModel` (``stop_fill``, ``tp_needs_close``, ``peak_from``; the legacy
  optimistic model is ``"level", False, "high"``) and reported in every result.
* Sizing: ``risk.size_position_usd(equity_usd, POSITION_PCT, MIN, MAX)`` with
  equity starting at ``start_usd`` (default 100); one position at a time per
  series; COOLDOWN_MIN after an exit.
* An open position at the end of data is closed at the last close (reason ``end_of_data``).

Clarifications of the rules above (all deterministic, all documented in results):

* "Later candle" includes the fill candle itself: everything inside candle
  ``i+1`` happens after its open, so an adverse move there can stop us out.
* Checks AT THE OPEN (price = open, in ``strategy.exit_signal`` order): stop
  gap -> stop_loss at open; ``ts >= opened_at + max_hold`` -> time_stop at
  open; trailing gap -> trailing_stop at open. Then intrabar: stop on the low
  at the stop level, take-profit on the high at ``max(open, tp)``, trailing
  stop on the low at ``min(open, trail)``. After a partial in a candle the
  trail (from the previous peak) is checked in the same candle (pessimistic).
* The fill candle's entry price includes costs, exactly like a live
  ``Position.entry_price_usd`` (effective fill price), so stop/TP levels are
  measured from the real cost basis.
* Universe filter (mirrors the crawler prefilter): no entry unless the token
  age (from meta ``created_utc``, else the first candle) is within
  ``[MIN_AGE_MIN, MAX_AGE_H]`` and, when ``supply`` is known, ``close * supply``
  is within ``[MIN_MCAP_USD, MAX_MCAP_USD]``. With ``watch_ttl_h`` set
  (:meth:`Backtester.from_settings` uses WATCHLIST_TTL_H) the backtest mirrors
  how the live bot meets a FRESH launch: it is prefiltered once at maturity
  (``MIN_AGE_MIN``; mcap outside the window then -> the series is never traded)
  and watched for ``watch_ttl_h`` hours, so entries stop at age ``MIN_AGE_MIN +
  watch_ttl_h``. ``watch_ttl_h=None`` (the constructor default, CLI
  ``--any-age``) allows any age up to MAX_AGE_H - right for coins that keep
  trending (the live crawler re-discovers them every 6 h) and for research. Liquidity is unknown here and
  NOT checked (documented optimism, like the skipped buy/sell ratio, radar,
  judge and cocoon - the backtest only measures the price setup).
* Optional trading window (``run(..., trade_from=, trade_until=)``): entries
  only when the decision time ``now`` is inside ``[trade_from, trade_until)``;
  candles before it still feed the strategy (rolling high), an open position
  keeps being managed after it. The equity curve covers the window and any
  time a position stays open after it.
* ``fees_usd`` = everything lost to costs: fee + impact on both sides and
  network fees. ``pnl_pct`` is percent of ``size_usd``; ``exposure_pct`` is
  the share of marked candles with a position open.

Metrics (per series and aggregated): ``trades, wins, losses, win_rate_pct,
total_return_pct, net_pnl_usd, avg_trade_pct, median_trade_pct,
max_drawdown_pct, profit_factor, fees_usd, exposure_pct, best_trade_pct,
worst_trade_pct``. Values that are undefined (no trades, no losing trade for
``profit_factor``) are ``None``. Aggregates add ``series``,
``series_with_trades``, ``profitable_series`` and ``series_skipped``
(unloadable / empty files).
"""

from __future__ import annotations

import bisect
import dataclasses
import itertools
import json
import math
import os
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from nightcrawler import risk
from nightcrawler.logging_setup import get_logger
from nightcrawler.models import Candle, Position, StrategyParams, fill_gaps
from nightcrawler.sources._parse import parse_ts, to_float
from nightcrawler.strategy import CANDLE_INTERVAL_S, entry_signal, exit_levels

__all__ = [
    "CostModel",
    "BacktestTrade",
    "BacktestResult",
    "SweepResult",
    "Backtester",
    "load_series",
    "format_table",
    "aggregate_metrics",
]

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CostModel:
    """Per-side trading costs and the intrabar fill model. Defaults are deliberately pessimistic
    for a $100 bankroll and a live bot that polls prices every ~10 s (see the module docstring)."""

    fee_bps_per_side: float = 100.0  # pool + platform fees (pump AMMs 0.3-1.25 %, Ultra 0.1 %)
    impact_bps_per_1k_usd: float = 150.0  # linear price-impact model
    network_fee_usd_per_side: float = 0.05  # base + priority fee (+ rent amortized)
    stop_fill: str = "close"  # "close": min(stop level, candle close); "level": exactly the stop level
    tp_needs_close: bool = True  # the take-profit fills only when the candle CLOSES at/above it (no wick fills)
    peak_from: str = "close"  # trailing-stop peak from candle "close"s or (optimistic) "high"s

    def cost_bps(self, size_usd: float) -> float:
        """Fee + linear impact (bps) for one side of ``size_usd``."""
        return self.fee_bps_per_side + self.impact_bps_per_1k_usd * size_usd / 1000.0

    def buy_fill(self, price: float, size_usd: float) -> float:
        """Effective USD per token paid when buying ``size_usd`` at mid ``price``."""
        return price * (1.0 + self.cost_bps(size_usd) / 1e4)

    def sell_fill(self, price: float, size_usd: float) -> float:
        """Effective USD per token received when selling ``size_usd`` worth at ``price`` (never < 0)."""
        return max(0.0, price * (1.0 - self.cost_bps(size_usd) / 1e4))


@dataclass(slots=True)
class BacktestTrade:
    """One simulated round trip (partial exits aggregated). Prices USD per whole token."""

    coin: str
    entry_ts: int
    entry_price: float
    exit_ts: int
    exit_price: float  # size-weighted average of all exit fills
    size_usd: float
    pnl_usd: float
    pnl_pct: float  # percent of size_usd
    fees_usd: float
    exit_reason: str
    partial_taken: bool
    signal_metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BacktestResult:
    coin: str
    mint: str | None
    trades: list[BacktestTrade]
    metrics: dict[str, float]
    equity_curve: list[tuple[int, float]]  # (candle ts, equity_usd marked at that candle's close)
    params: dict[str, Any] = field(default_factory=dict)
    cost_model: dict[str, Any] = field(default_factory=dict)
    span: dict[str, Any] = field(default_factory=dict)  # trade window + first/last marked candle ts

    def to_dict(self, include_equity_curve: bool = False) -> dict[str, Any]:
        """JSON-native dict; the (long) equity curve only on request."""
        out = dataclasses.asdict(self)
        if not include_equity_curve:
            out.pop("equity_curve")
        return out


@dataclass(slots=True)
class SweepResult:
    """Grid search with an out-of-sample split by token launch time."""

    rows: list[dict[str, Any]]  # {params..., train: metrics, test: metrics}
    best_params: dict[str, Any]
    train_coins: list[str]
    test_coins: list[str]


class Backtester:
    """Replays candles through ``strategy`` with the cost model (see module docstring)."""

    def __init__(self, params: StrategyParams, cost_model: CostModel | None = None, start_usd: float = 100.0,
                 position_pct: float = 0.20, min_position_usd: float = 5.0, max_position_usd: float = 25.0,
                 watch_ttl_h: float | None = None) -> None:
        self.params = params
        self.cost_model = cost_model or CostModel()
        self.start_usd = start_usd
        self.position_pct = position_pct
        self.min_position_usd = min_position_usd
        self.max_position_usd = max_position_usd
        #: None = any age; else entries only within ``watch_ttl_h`` of maturity (see module docstring).
        self.watch_ttl_h = watch_ttl_h

    @classmethod
    def from_settings(cls, settings: Any, cost_model: CostModel | None = None, *,
                      any_age: bool = False) -> "Backtester":
        """Backtester mirroring the live bot: strategy params, PAPER_START_USD, position sizing and the
        watch window (WATCHLIST_TTL_H) from Settings; ``any_age=True`` lifts the watch window."""
        return cls(settings.strategy_params(), cost_model, settings.paper_start_usd, settings.position_pct,
                   settings.min_position_usd, settings.max_position_usd,
                   None if any_age else settings.watchlist_ttl_h)

    def run(self, candles: Sequence[Candle], meta: Mapping[str, Any], *, trade_from: float | None = None,
            trade_until: float | None = None) -> BacktestResult:
        """Simulate one series (``candles`` ascending 1m). ``meta`` = the file's non-candle keys.

        ``trade_from`` / ``trade_until`` (epoch s) limit ENTRY decisions to a window.
        """
        return _SeriesRun(self, candles, meta, trade_from, trade_until).run()

    def run_many(self, paths: Iterable[str | os.PathLike[str]]) -> tuple[list[BacktestResult], dict[str, float]]:
        """Run every file; returns (per-series results, aggregate metrics over all trades).

        Each series starts from ``start_usd`` independently (no compounding across coins).
        Files that fail :func:`load_series` (empty / invalid) are skipped and
        counted in ``series_skipped``.
        """
        series, skipped = _load_all(paths)
        results = [self.run(candles, meta) for candles, meta in series]
        return results, aggregate_metrics(results, self.start_usd, skipped)

    def sweep(self, param_grid: Mapping[str, Sequence[Any]], paths: Iterable[str | os.PathLike[str]],
              train_frac: float = 0.6) -> SweepResult:
        """Grid search. Series sorted by first candle ts (launch time); the first
        ``train_frac`` are TRAIN, the rest TEST. ``best_params`` maximize train
        ``total_return_pct`` (ties: fewer trades); TEST metrics are reported for
        every row so overfitting is visible. Needs >= 2 series (ValueError)."""
        unknown = set(param_grid) - {f.name for f in dataclasses.fields(StrategyParams)}
        if unknown:
            raise ValueError(f"unknown strategy params in grid: {', '.join(sorted(unknown))}")
        series, _ = _load_all(paths)
        if len(series) < 2:
            raise ValueError("sweep needs at least 2 series (train and test)")
        series.sort(key=lambda s: s[0][0].ts)
        n_train = min(len(series) - 1, max(1, round(len(series) * train_frac)))
        train, test = series[:n_train], series[n_train:]
        names = list(param_grid)
        rows = []
        for values in itertools.product(*(param_grid[name] for name in names)):
            combo = dict(zip(names, values, strict=True))
            tester = self._with_params(dataclasses.replace(self.params, **combo))
            rows.append({**combo, "train": tester._aggregate(train), "test": tester._aggregate(test)})
        if not rows:
            raise ValueError("param grid has an empty value list")
        best = max(rows, key=lambda r: (r["train"]["total_return_pct"], -r["train"]["trades"]))
        return SweepResult(rows=rows, best_params={name: best[name] for name in names},
                           train_coins=[str(m["coin"]) for _, m in train],
                           test_coins=[str(m["coin"]) for _, m in test])

    def _with_params(self, params: StrategyParams) -> "Backtester":
        return Backtester(params, self.cost_model, self.start_usd, self.position_pct, self.min_position_usd,
                          self.max_position_usd, self.watch_ttl_h)

    def _aggregate(self, series: Sequence[tuple[list[Candle], dict[str, Any]]]) -> dict[str, float]:
        return aggregate_metrics([self.run(c, m) for c, m in series], self.start_usd)

    def size_usd(self, cash_usd: float) -> float:
        """Position size for a flat book holding ``cash_usd`` (risk sizing, fee-aware, 0 = skip)."""
        size = risk.size_position_usd(cash_usd, self.position_pct, self.min_position_usd, self.max_position_usd)
        size = min(size, cash_usd - self.cost_model.network_fee_usd_per_side)
        return size if size >= self.min_position_usd else 0.0


# --------------------------------------------------------------------------- one series


@dataclass(slots=True)
class _OpenTrade:
    position: Position  # strategy view: entry price (with costs), peak, partial flag, opened_at
    tokens: float  # whole tokens still held
    size_usd: float
    invested_usd: float  # size + entry network fee
    fees_usd: float
    metrics: dict[str, Any]
    proceeds_usd: float = 0.0  # net of exit costs and network fees
    sold_tokens: float = 0.0
    sold_value_usd: float = 0.0  # sum(tokens * net fill price)


class _SeriesRun:
    """State machine for one series; see the module docstring for every rule."""

    def __init__(self, bt: Backtester, candles: Sequence[Candle], meta: Mapping[str, Any],
                 trade_from: float | None, trade_until: float | None) -> None:
        self.bt = bt
        self.p = bt.params
        self.costs = bt.cost_model
        self.candles = fill_gaps(list(candles), CANDLE_INTERVAL_S)  # what the live candle client returns
        self.ts = [c.ts for c in self.candles]
        self.meta = meta
        self.coin = str(meta.get("coin") or meta.get("mint") or "?")
        self.trade_from = -math.inf if trade_from is None else trade_from
        self.trade_until = math.inf if trade_until is None else trade_until
        self.created_ts = parse_ts(meta.get("created_utc")) or (self.ts[0] if self.ts else 0)
        self.supply = to_float(meta.get("supply"))
        self.watch_until = (math.inf if bt.watch_ttl_h is None
                            else self.created_ts + self.p.min_age_min * 60 + bt.watch_ttl_h * 3600)
        self.ever_watched = bt.watch_ttl_h is None or self._passes_maturity_prefilter()
        self.cash = bt.start_usd
        self.trades: list[BacktestTrade] = []
        self.curve: list[tuple[int, float]] = []
        self.open: _OpenTrade | None = None
        self.pending: tuple[dict[str, Any], float] | None = None  # (signal metrics, size_usd)
        self.cooldown_until = -math.inf
        self.exposed = 0

    def run(self) -> BacktestResult:
        for i, c in enumerate(self.candles):
            busy = self.pending is not None or self.open is not None  # a position lives in this candle
            if self.pending is not None:
                metrics, size = self.pending
                self.pending = None
                self._fill_entry(c, metrics, size)
            if self.open is not None:
                self._manage(self.open, c)
            now = c.ts + CANDLE_INTERVAL_S
            if now < self.trade_from:
                continue
            if now >= self.trade_until and not busy:
                break
            self._mark(c)
            if self.open is None and now < self.trade_until:
                self._consider_entry(i, now)
        if self.open is not None:
            last = self.candles[-1]
            self._close(self.open, last.ts, last.c, "end_of_data")
            self.curve[-1] = (self.curve[-1][0], self.cash)
        return self._result()

    # ---------------------------------------------------------------- entries
    def _consider_entry(self, i: int, now: float) -> None:
        if now < self.cooldown_until or not self._in_universe(self.candles[i], now):
            return
        lo = bisect.bisect_left(self.ts, now - self.p.dip_lookback_h * 3600)
        signal = entry_signal(self.candles[lo:i + 1], None, self.p, now)
        if signal.kind != "enter":
            return
        size = self.bt.size_usd(self.cash)
        if size > 0:
            self.pending = (signal.metrics, size)

    def _passes_maturity_prefilter(self) -> bool:
        """The crawler's mcap window at maturity (``MIN_AGE_MIN``), on the last candle at/before it.
        Unknown supply or no candle that early -> not checked (documented optimism)."""
        if not self.supply:
            return True
        maturity = self.created_ts + self.p.min_age_min * 60
        i = bisect.bisect_right(self.ts, maturity) - 1
        if i < 0:
            return True
        return self.p.min_mcap_usd <= self.candles[i].c * self.supply <= self.p.max_mcap_usd

    def _in_universe(self, c: Candle, now: float) -> bool:
        if not self.ever_watched or now > self.watch_until:
            return False
        age_min = (now - self.created_ts) / 60
        if not self.p.min_age_min <= age_min <= self.p.max_age_h * 60:
            return False
        if self.supply:
            return self.p.min_mcap_usd <= c.c * self.supply <= self.p.max_mcap_usd
        return True

    def _fill_entry(self, c: Candle, metrics: dict[str, Any], size: float) -> None:
        network = self.costs.network_fee_usd_per_side
        price = self.costs.buy_fill(c.o, size)
        tokens = size / price
        self.cash -= size + network
        position = Position(id=f"bt_{self.coin}_{c.ts}", mint=str(self.meta.get("mint") or ""), symbol=self.coin,
                            pool=self.meta.get("pool"), opened_at=float(c.ts), token_decimals=0,
                            entry_price_usd=price, peak_price_usd=price)
        self.open = _OpenTrade(position=position, tokens=tokens, size_usd=size, invested_usd=size + network,
                               fees_usd=size - tokens * c.o + network, metrics=metrics)

    # ---------------------------------------------------------------- exits
    def _manage(self, trade: _OpenTrade, c: Candle) -> None:
        if not self._exit_at_open(trade, c):
            self._exit_intrabar(trade, c)
        if self.open is trade:
            seen = c.h if self.costs.peak_from == "high" else c.c
            trade.position.peak_price_usd = max(trade.position.peak_price_usd, seen)

    def _exit_at_open(self, trade: _OpenTrade, c: Candle) -> bool:
        """Gap / time checks at the open (exit_signal order). True if the position was closed."""
        lv = exit_levels(trade.position, self.p)
        if c.o <= lv.stop:
            reason = "stop_loss"
        elif c.ts >= lv.time_stop_ts:
            reason = "time_stop"
        elif lv.trail is not None and c.o <= lv.trail:
            reason = "trailing_stop"
        else:
            return False
        self._close(trade, c.ts, c.o, reason)
        return True

    def _exit_intrabar(self, trade: _OpenTrade, c: Candle) -> None:
        pos = trade.position
        lv = exit_levels(pos, self.p)
        if c.l <= lv.stop:  # pessimistic: the stop beats a take-profit in the same candle
            self._close(trade, c.ts, self._stop_price(lv.stop, c), "stop_loss")
            return
        if (lv.take_profit is not None and c.h >= lv.take_profit
                and (not self.costs.tp_needs_close or c.c >= lv.take_profit)):
            price = max(c.o, lv.take_profit)
            if self.p.partial_tp_fraction >= 1.0:
                self._close(trade, c.ts, price, "take_profit_partial")
                return
            self._sell(trade, trade.tokens * self.p.partial_tp_fraction, price)
            pos.partial_taken = True
            lv = exit_levels(pos, self.p)
        if lv.trail is not None and c.l <= lv.trail:
            self._close(trade, c.ts, min(c.o, self._stop_price(lv.trail, c)), "trailing_stop")

    def _stop_price(self, level: float, c: Candle) -> float:
        """Where a stop inside candle ``c`` fills: the level, or (default) the close when it closed below."""
        return level if self.costs.stop_fill == "level" else min(level, c.c)

    def _sell(self, trade: _OpenTrade, tokens: float, price: float) -> None:
        gross = tokens * price
        net_price = self.costs.sell_fill(price, gross)
        network = self.costs.network_fee_usd_per_side
        proceeds = tokens * net_price - network
        self.cash += proceeds
        trade.tokens -= tokens
        trade.proceeds_usd += proceeds
        trade.sold_tokens += tokens
        trade.sold_value_usd += tokens * net_price
        trade.fees_usd += gross - tokens * net_price + network

    def _close(self, trade: _OpenTrade, ts: int, price: float, reason: str) -> None:
        self._sell(trade, trade.tokens, price)
        pnl = trade.proceeds_usd - trade.invested_usd
        self.trades.append(BacktestTrade(
            coin=self.coin,
            entry_ts=int(trade.position.opened_at),
            entry_price=trade.position.entry_price_usd,
            exit_ts=ts,
            exit_price=trade.sold_value_usd / trade.sold_tokens if trade.sold_tokens else 0.0,
            size_usd=trade.size_usd,
            pnl_usd=pnl,
            pnl_pct=pnl / trade.size_usd * 100.0,
            fees_usd=trade.fees_usd,
            exit_reason=reason,
            partial_taken=trade.position.partial_taken,
            signal_metrics=trade.metrics,
        ))
        self.open = None
        self.cooldown_until = ts + self.p.cooldown_min * 60

    # ---------------------------------------------------------------- bookkeeping
    def _mark(self, c: Candle) -> None:
        held = self.open.tokens * c.c if self.open is not None else 0.0
        self.curve.append((c.ts, self.cash + held))
        self.exposed += self.open is not None

    def _result(self) -> BacktestResult:
        metrics = {
            **_trade_stats(self.trades),
            "total_return_pct": (self.cash - self.bt.start_usd) / self.bt.start_usd * 100.0,
            "net_pnl_usd": self.cash - self.bt.start_usd,
            "max_drawdown_pct": _max_drawdown_pct([e for _, e in self.curve]),
            "exposure_pct": 100.0 * self.exposed / len(self.curve) if self.curve else 0.0,
        }
        span = {
            "trade_from": None if math.isinf(self.trade_from) else self.trade_from,
            "trade_until": None if math.isinf(self.trade_until) else self.trade_until,
            "first_ts": self.curve[0][0] if self.curve else None,
            "last_ts": self.curve[-1][0] if self.curve else None,
            "candles_marked": len(self.curve),
        }
        return BacktestResult(coin=self.coin, mint=self.meta.get("mint"), trades=self.trades,
                              metrics=_rounded(metrics), equity_curve=self.curve, params=self.p.to_dict(),
                              cost_model=dataclasses.asdict(self.costs), span=span)


# --------------------------------------------------------------------------- metrics


def _trade_stats(trades: Sequence[BacktestTrade]) -> dict[str, Any]:
    """Trade-level metrics shared by single series and aggregates (None when undefined)."""
    pcts = [t.pnl_pct for t in trades]
    gross_win = sum(t.pnl_usd for t in trades if t.pnl_usd > 0)
    gross_loss = -sum(t.pnl_usd for t in trades if t.pnl_usd <= 0)
    wins = sum(1 for t in trades if t.pnl_usd > 0)
    return {
        "trades": len(trades),
        "wins": wins,
        "losses": len(trades) - wins,
        "win_rate_pct": 100.0 * wins / len(trades) if trades else None,
        "avg_trade_pct": statistics.fmean(pcts) if pcts else None,
        "median_trade_pct": statistics.median(pcts) if pcts else None,
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else None,
        "fees_usd": math.fsum(t.fees_usd for t in trades),
        "best_trade_pct": max(pcts) if pcts else None,
        "worst_trade_pct": min(pcts) if pcts else None,
    }


def _max_drawdown_pct(equity: Sequence[float]) -> float:
    """Largest peak-to-trough fall of ``equity`` in percent of the peak (0 if it never falls)."""
    peak, worst = -math.inf, 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak * 100.0)
    return worst


def _rounded(metrics: dict[str, Any], digits: int = 4) -> dict[str, Any]:
    return {k: round(v, digits) if isinstance(v, float) else v for k, v in metrics.items()}


def aggregate_metrics(results: Sequence[BacktestResult], start_usd: float, skipped: int = 0) -> dict[str, Any]:
    """Metrics over ALL trades of ``results`` (each series started from ``start_usd``).

    ``total_return_pct`` = summed net P&L / (``start_usd`` x series);
    ``max_drawdown_pct`` = the worst series; ``exposure_pct`` = mean over series.
    """
    trades = [t for r in results for t in r.trades]
    net = sum(r.metrics["net_pnl_usd"] for r in results)
    metrics = {
        "series": len(results),
        "series_with_trades": sum(1 for r in results if r.trades),
        "profitable_series": sum(1 for r in results if r.metrics["net_pnl_usd"] > 0),
        "series_skipped": skipped,
        **_trade_stats(trades),
        "total_return_pct": net / (start_usd * len(results)) * 100.0 if results else 0.0,
        "net_pnl_usd": net,
        "max_drawdown_pct": max((r.metrics["max_drawdown_pct"] for r in results), default=0.0),
        "exposure_pct": statistics.fmean(r.metrics["exposure_pct"] for r in results) if results else 0.0,
    }
    return _rounded(metrics)


# --------------------------------------------------------------------------- files & output


def load_series(path: str | os.PathLike[str]) -> tuple[list[Candle], dict[str, Any]]:
    """Read a backtest JSON file -> (ascending candles, meta without ``candles``).

    Rows are parsed with ``Candle.from_row``, sorted by ts, duplicate ts keep
    the last row. Raises ``ValueError`` on an empty/invalid file. ``meta["coin"]``
    defaults to the file name stem.
    """
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{path}: not valid JSON ({exc})") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("candles"), list):
        raise ValueError(f"{path}: expected an object with a 'candles' list")
    by_ts: dict[int, Candle] = {}
    for n, row in enumerate(doc["candles"]):
        try:
            candle = Candle.from_row(row)
        except (TypeError, ValueError, IndexError):
            raise ValueError(f"{path}: bad candle row {n}: {row!r}") from None
        if not all(math.isfinite(x) for x in (candle.o, candle.h, candle.l, candle.c, candle.v)):
            raise ValueError(f"{path}: non-finite value in candle row {n}")
        by_ts[candle.ts] = candle
    if not by_ts:
        raise ValueError(f"{path}: no candles")
    meta = {k: v for k, v in doc.items() if k != "candles"}
    meta.setdefault("coin", Path(path).stem)
    return [by_ts[ts] for ts in sorted(by_ts)], meta


def _load_all(paths: Iterable[str | os.PathLike[str]]) -> tuple[list[tuple[list[Candle], dict[str, Any]]], int]:
    """Load every path; invalid/empty files are logged and counted, not fatal."""
    series, skipped = [], 0
    for path in paths:
        try:
            series.append(load_series(path))
        except ValueError as exc:
            skipped += 1
            log.warning("backtest_skip_file %s", exc)
    return series, skipped


_TABLE_COLUMNS: tuple[tuple[str, str, int, str], ...] = (
    # (header, metric key, width, format)
    ("trades", "trades", 6, "d"),
    ("win%", "win_rate_pct", 6, ".1f"),
    ("return%", "total_return_pct", 8, ".2f"),
    ("net $", "net_pnl_usd", 10, ",.2f"),
    ("avg%", "avg_trade_pct", 7, ".2f"),
    ("med%", "median_trade_pct", 7, ".2f"),
    ("maxDD%", "max_drawdown_pct", 7, ".2f"),
    ("PF", "profit_factor", 6, ".2f"),
    ("fees $", "fees_usd", 9, ",.2f"),
    ("expo%", "exposure_pct", 6, ".1f"),
)


def format_table(results: Sequence[BacktestResult], aggregate: Mapping[str, float] | None = None) -> str:
    """Fixed-width human table: one row per series (+ TOTAL), key metrics only."""
    name_w = max([len("series"), len("TOTAL"), *(len(r.coin) for r in results)])
    header = "series".ljust(name_w) + "".join(f" {h:>{w}}" for h, _, w, _ in _TABLE_COLUMNS)
    lines = [header, "-" * len(header)]
    rows: list[tuple[str, Mapping[str, float]]] = [(r.coin, r.metrics) for r in results]
    if aggregate is not None:
        rows.append(("TOTAL", aggregate))
    for name, metrics in rows:
        cells = "".join(f" {_cell(metrics.get(key), fmt):>{w}}" for _, key, w, fmt in _TABLE_COLUMNS)
        lines.append(name.ljust(name_w) + cells)
    return "\n".join(lines)


def _cell(value: Any, fmt: str) -> str:
    return "-" if value is None else format(value, fmt)
