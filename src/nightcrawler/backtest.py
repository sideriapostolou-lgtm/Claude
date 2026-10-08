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
* Exits are evaluated intrabar on each later candle with ``strategy.exit_levels``
  in PESSIMISTIC order: (1) gap: if open <= stop -> exit at open; (2) stop if
  ``low <= stop``; (3) take-profit if ``high >= tp`` (partial, once); (4) trailing
  stop if ``low <= peak*(1-trail)`` (peak updated with highs of PREVIOUS candles
  only, then this candle's high after the checks); (5) time stop at the candle
  where ``ts >= opened_at + max_hold``. If stop and TP are both inside one
  candle -> STOP first. Sells fill at the level (or open on a gap) times
  ``(1 - (fee_bps + impact_bps)/1e4)``.
* Sizing: ``risk.size_position_usd(equity_usd, POSITION_PCT, MIN, MAX)`` with
  equity starting at ``start_usd`` (default 100); one position at a time per
  series; COOLDOWN_MIN after an exit.
* An open position at the end of data is closed at the last close (reason ``end_of_data``).

Metrics (per series and aggregated): ``trades, wins, losses, win_rate_pct,
total_return_pct, net_pnl_usd, avg_trade_pct, median_trade_pct,
max_drawdown_pct, profit_factor, fees_usd, exposure_pct, best_trade_pct,
worst_trade_pct``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from nightcrawler.models import Candle, StrategyParams

__all__ = [
    "CostModel",
    "BacktestTrade",
    "BacktestResult",
    "SweepResult",
    "Backtester",
    "load_series",
    "format_table",
]


@dataclass(frozen=True, slots=True)
class CostModel:
    """Per-side trading costs. Defaults are deliberately pessimistic for a $100 bankroll."""

    fee_bps_per_side: float = 100.0  # pool + platform fees (pump AMMs 0.3-1.25 %, Ultra 0.1 %)
    impact_bps_per_1k_usd: float = 150.0  # linear price-impact model
    network_fee_usd_per_side: float = 0.05  # base + priority fee (+ rent amortized)


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
    equity_curve: list[tuple[int, float]]  # (ts, equity_usd)
    params: dict[str, Any] = field(default_factory=dict)
    cost_model: dict[str, Any] = field(default_factory=dict)


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
                 position_pct: float = 0.20, min_position_usd: float = 5.0, max_position_usd: float = 25.0) -> None:
        self.params = params
        self.cost_model = cost_model or CostModel()
        self.start_usd = start_usd
        self.position_pct = position_pct
        self.min_position_usd = min_position_usd
        self.max_position_usd = max_position_usd

    def run(self, candles: Sequence[Candle], meta: Mapping[str, Any]) -> BacktestResult:
        """Simulate one series (``candles`` ascending 1m). ``meta`` = the file's non-candle keys."""
        raise NotImplementedError

    def run_many(self, paths: Iterable[str | os.PathLike[str]]) -> tuple[list[BacktestResult], dict[str, float]]:
        """Run every file; returns (per-series results, aggregate metrics over all trades).

        Each series starts from ``start_usd`` independently (no compounding across coins).
        """
        raise NotImplementedError

    def sweep(self, param_grid: Mapping[str, Sequence[Any]], paths: Iterable[str | os.PathLike[str]],
              train_frac: float = 0.6) -> SweepResult:
        """Grid search. Series sorted by first candle ts (launch time); the first
        ``train_frac`` are TRAIN, the rest TEST. ``best_params`` maximize train
        ``total_return_pct`` (ties: fewer trades); TEST metrics are reported for
        every row so overfitting is visible. Needs >= 2 series (ValueError)."""
        raise NotImplementedError


def load_series(path: str | os.PathLike[str]) -> tuple[list[Candle], dict[str, Any]]:
    """Read a backtest JSON file -> (ascending candles, meta without ``candles``).

    Rows are parsed with ``Candle.from_row``, sorted by ts, duplicate ts keep
    the last row. Raises ``ValueError`` on an empty/invalid file.
    """
    raise NotImplementedError


def format_table(results: Sequence[BacktestResult], aggregate: Mapping[str, float] | None = None) -> str:
    """Fixed-width human table: one row per series (+ TOTAL), key metrics only."""
    raise NotImplementedError
