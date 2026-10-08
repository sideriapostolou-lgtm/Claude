"""Lookahead-proof research simulator for the strategy lab.

THE CONTRACT
============
* A strategy is called once per bar, at the bar's CLOSE: ``on_candle(i, view, position)``.
  ``view`` exposes ONLY bars ``0..i`` (read-only numpy slices) and launch-time metadata.
  ``view.now`` = close time of bar ``i``. There is no way to reach bar ``i+1`` from ``view``.
* Orders decided at the close of bar ``i`` fill at the OPEN of bar ``i + entry_delay_bars``
  (default ``i+1``) through ``costs.py`` (pool fee by market-cap tier + Ultra 10 bps + MEV buffer
  + constant-product impact + network fee). No next bar -> no fill.
* Entries are refused before the coin's graduation is observable (``view.now < graduated_ts``):
  the universe is "coins that graduated", so buying on the bonding curve would use the
  future knowledge that the coin graduates. ``view.graduated_ts`` is None until then.
* Exits set with ``Exits`` are managed INSIDE later bars, pessimistically:
  1. at the open (not on the fill bar): open <= stop -> sell at open; bar ts >= time stop ->
     sell at open; open <= trail level -> sell at open;
  2. stop before take-profit when both are inside one bar;
  3. take-profit (``tp_fraction`` of the position, once), then the trail is checked in the same
     bar against the PREVIOUS peak (pessimistic);
  4. the trail uses only peaks of earlier bars (the entry mid counts as the first peak);
  5. wick fills (``wick_fill``): "touch" = at the level; "half" (DEFAULT) = stops/trails fill
     halfway between the level and the bar low, take-profits fill at the level only if the bar
     closed at/above it, else halfway between the level and the body top; "worst" = stops at the
     low, take-profits at the body top. Memecoin wicks are often ONE transaction - a bot that
     reacts to it lands seconds later.
* ``Sell(fraction)`` from the strategy fills at the next bar's open, like a buy.
* Per-coin mode (``run_per_coin``): every coin independent, fixed size (default $20),
  no portfolio limits -> clean per-trade statistics.
* Portfolio mode (``run_portfolio``): all coins merged chronologically; $100 start; size =
  ``nightcrawler.risk.size_position_usd(equity, 0.20, 5, 25)`` capped by free cash; max 3
  concurrent positions (pending buys count); one position per coin; per-coin cooldown after a
  full exit; compounding; equity marked at mid every minute. Simultaneous buy requests are
  served by ``Buy.priority`` (desc), then coin creation time, then mint.

Allowed metadata (``view.meta``): mint, symbol, name, created_ts, supply, launch flags fixed at
creation (quote mint, mayhem opt-in, socials present, description length, token program ...).
NOT exposed: coverage/end of data, last trade time, census outcome fields, pool reserves, k.

Default universe: SOL-paired coins whose bars are all 1-minute (983 of 1,070). Splits: see
``splits.json``; the TEST split is refused unless env ``LAB_ALLOW_TEST=1``.

Minimal strategy (buy 2 minutes after graduation, 25 % stop, 50 % take-profit, 60 min max)::

    from harness import Strategy, Buy, Exits, run_per_coin, run_portfolio, load_coins, metrics

    class Grad2(Strategy):
        name = "grad2"
        horizon_s = 3 * 3600               # stop calling me 3 h after graduation when flat
        def on_coin_start(self, meta):
            self.done = False
        def on_candle(self, i, view, position):
            if self.done or position is not None or not view.graduated:
                return None
            if view.now - view.graduated_ts >= 120:
                self.done = True
                return Buy(exits=Exits(stop_pct=0.25, take_profit_pct=0.50, max_hold_s=3600))
            return None

    coins = load_coins(split="train")
    res = run_portfolio(Grad2, coins)
    print(res.summary())
"""

from __future__ import annotations

import dataclasses
import heapq
import json
import math
import os
import random
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, NamedTuple, Sequence

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_SRC = HERE.parent.parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import costs as _costs  # noqa: E402
from costs import CoinCostContext, CostModel, SolUsd, context_for_coin  # noqa: E402

try:  # reuse the live bot's sizing rule when the package is importable
    from nightcrawler.risk import size_position_usd as _nc_size  # type: ignore
except Exception:  # pragma: no cover - fallback keeps the lab independent of src/
    _nc_size = None

LAB = Path(os.environ.get(
    "LAB_DATA", "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad/lab"))
SPLITS = HERE / "splits.json"
TEST_ENV = "LAB_ALLOW_TEST"


def size_position_usd(equity_usd: float, pct: float, lo: float, hi: float) -> float:
    """nightcrawler.risk.size_position_usd (identical fallback if src/ is not importable)."""
    if _nc_size is not None:
        return _nc_size(equity_usd, pct, lo, hi)
    if equity_usd <= 0 or pct <= 0:
        return 0.0
    target = min(equity_usd * pct, hi)
    return target if target + 1e-4 >= lo else 0.0


# =========================================================================== data


class Bar(NamedTuple):
    ts: int
    o: float
    h: float
    l: float  # noqa: E741
    c: float
    v: float
    dur: int


def _ro(a: np.ndarray) -> np.ndarray:
    a.setflags(write=False)
    return a


@dataclass
class Coin:
    """One coin's bars + metadata. Arrays are read-only."""

    mint: str
    symbol: str
    name: str | None
    created_ts: float
    graduated_ts: float
    supply: float
    launch: Mapping[str, Any]
    ts: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray  # noqa: E741
    c: np.ndarray
    v: np.ndarray
    dur: np.ndarray
    cost_ctx: CoinCostContext
    coverage: Mapping[str, Any]  # harness-only (outcome info: end of data etc.) - never shown to strategies

    @property
    def n(self) -> int:
        return len(self.ts)

    @classmethod
    def from_doc(cls, doc: Mapping[str, Any], k_policy: str = "grad") -> "Coin":
        rows = np.asarray(doc["candles"], dtype=float)
        cov = doc.get("coverage") or {}
        ts = rows[:, 0].astype(np.int64)
        first_1m = int(cov.get("first_1m_ts", ts[0]))
        dur = np.where(ts < first_1m, int(cov.get("bar_s_before_1m", 300)), 60).astype(np.int64)
        return cls(
            mint=doc["mint"], symbol=str(doc.get("coin") or doc["mint"][:6]), name=doc.get("name"),
            created_ts=float(doc.get("created_ts") or ts[0]),
            graduated_ts=float(doc.get("graduated_ts") or doc.get("created_ts") or ts[0]),
            supply=float(doc.get("supply") or 1e9), launch=MappingProxyType(dict(doc.get("launch") or {})),
            ts=_ro(ts), o=_ro(rows[:, 1].copy()), h=_ro(rows[:, 2].copy()), l=_ro(rows[:, 3].copy()),
            c=_ro(rows[:, 4].copy()), v=_ro(rows[:, 5].copy()), dur=_ro(dur),
            cost_ctx=context_for_coin(dict(doc), k_policy), coverage=MappingProxyType(dict(cov)),
        )

    @classmethod
    def from_rows(cls, rows: Sequence[Sequence[float]], mint: str = "TEST", created_ts: float | None = None,
                  graduated_ts: float | None = None, supply: float = 1e9, launch: Mapping | None = None,
                  cost_ctx: CoinCostContext | None = None) -> "Coin":
        """Build a coin from [[ts,o,h,l,c,v],...] 1m rows (tests / synthetic data)."""
        doc = {"mint": mint, "coin": mint, "candles": [list(r) for r in rows],
               "created_ts": created_ts if created_ts is not None else rows[0][0],
               "graduated_ts": graduated_ts if graduated_ts is not None else rows[0][0], "supply": supply,
               "launch": dict(launch or {"quote_is_sol": True}),
               "coverage": {"first_1m_ts": rows[0][0], "source": "1m"}}
        coin = cls.from_doc(doc)
        if cost_ctx is not None:
            coin.cost_ctx = cost_ctx
        return coin


def coin_paths(lab: Path | None = None) -> list[Path]:
    return sorted(((lab or LAB) / "coins").glob("*.json"))


def in_default_universe(doc_or_coin: Any) -> bool:
    """SOL-paired coins whose bars are all 1-minute (launch-time + data-quality filter)."""
    if isinstance(doc_or_coin, Coin):
        launch, cov = doc_or_coin.launch, doc_or_coin.coverage
    else:
        launch, cov = doc_or_coin.get("launch") or {}, doc_or_coin.get("coverage") or {}
    return bool(launch.get("quote_is_sol")) and cov.get("source", "1m") in ("1m", "gt1m+1m")


# --------------------------------------------------------------------------- splits


def make_splits(lab: Path | None = None, out: Path = SPLITS, fracs: tuple[float, float] = (0.6, 0.2)) -> dict:
    """Split ALL census coins by created_ts: oldest 60 % TRAIN, next 20 % VALIDATION, newest 20 % TEST."""
    lab = lab or LAB
    cen = json.loads((lab / "census.json").read_text())
    coins = sorted(cen["coins"], key=lambda c: (c["created_timestamp"], c["mint"]))
    n = len(coins)
    a, b = int(round(n * fracs[0])), int(round(n * (fracs[0] + fracs[1])))
    parts = {"train": coins[:a], "validation": coins[a:b], "test": coins[b:]}
    doc = {
        "rule": "census coins sorted by created_timestamp: oldest 60% train, next 20% validation, newest 20% test",
        "census_started_utc": cen.get("census_started_utc"), "n": n,
        "bounds_created_ts": {k: [v[0]["created_timestamp"] / 1000, v[-1]["created_timestamp"] / 1000]
                              for k, v in parts.items()},
        "train": [c["mint"] for c in parts["train"]],
        "validation": [c["mint"] for c in parts["validation"]],
        "test": [c["mint"] for c in parts["test"]],
    }
    out.write_text(json.dumps(doc, indent=1))
    return doc


class TestSplitLocked(PermissionError):
    pass


def _test_allowed() -> bool:
    return os.environ.get(TEST_ENV) == "1"


def load_split(name: str, path: Path = SPLITS) -> list[str]:
    """Mints of a split. "test" raises TestSplitLocked unless env LAB_ALLOW_TEST=1."""
    if name not in ("train", "validation", "test"):
        raise ValueError(f"unknown split {name!r}")
    if name == "test" and not _test_allowed():
        raise TestSplitLocked("the TEST split is locked: only the judge sets LAB_ALLOW_TEST=1")
    return list(json.loads(path.read_text())[name])


def _test_mints(path: Path = SPLITS) -> set[str]:
    try:
        return set(json.loads(path.read_text())["test"])
    except (OSError, ValueError, KeyError):
        return set()


def guard_coins(coins: Iterable[Coin], path: Path = SPLITS) -> None:
    """Refuse to simulate any TEST coin unless LAB_ALLOW_TEST=1."""
    if _test_allowed():
        return
    test = _test_mints(path)
    bad = [c.mint for c in coins if c.mint in test]
    if bad:
        raise TestSplitLocked(f"{len(bad)} coin(s) belong to the locked TEST split (e.g. {bad[0]})")


def load_coins(split: str | None = None, mints: Iterable[str] | None = None, universe: str = "default",
               lab: Path | None = None, k_policy: str = "grad", limit: int | None = None) -> list[Coin]:
    """Load coin files. ``split`` in train|validation|test (test guarded); ``universe``:
    "default" (SOL-paired, all-1m) or "all". Sorted by created_ts."""
    lab = lab or LAB
    want = set(load_split(split)) if split else (set(mints) if mints is not None else None)
    if want is not None and not _test_allowed():
        locked = want & _test_mints()
        if locked and split != "test":
            raise TestSplitLocked(f"{len(locked)} requested mint(s) belong to the locked TEST split")
    out = []
    for p in coin_paths(lab):
        mint = p.stem
        if want is not None and mint not in want:
            continue
        if want is None and not _test_allowed() and mint in _test_mints():
            continue  # loading "everything" silently leaves the locked test coins out
        doc = json.loads(p.read_text())
        if universe == "default" and not in_default_universe(doc):
            continue
        out.append(Coin.from_doc(doc, k_policy))
        if limit and len(out) >= limit:
            break
    out.sort(key=lambda c: (c.created_ts, c.mint))
    return out


# =========================================================================== strategy API


class View:
    """Read-only window on bars 0..i of one coin at the close of bar i."""

    __slots__ = ("_coin", "i", "n", "now", "_meta", "_sol")

    def __init__(self, coin: Coin, i: int, meta: Mapping[str, Any], sol: SolUsd | None = None) -> None:
        if not 0 <= i < coin.n:
            raise IndexError(i)
        self._coin = coin
        self.i = i
        self.n = i + 1
        self.now = float(coin.ts[i] + coin.dur[i])
        self._meta = meta
        self._sol = sol

    # bars 0..i (read-only numpy views)
    @property
    def ts(self) -> np.ndarray:
        return self._coin.ts[:self.n]

    @property
    def o(self) -> np.ndarray:
        return self._coin.o[:self.n]

    @property
    def h(self) -> np.ndarray:
        return self._coin.h[:self.n]

    @property
    def l(self) -> np.ndarray:  # noqa: E743
        return self._coin.l[:self.n]

    @property
    def c(self) -> np.ndarray:
        return self._coin.c[:self.n]

    @property
    def v(self) -> np.ndarray:
        return self._coin.v[:self.n]

    @property
    def dur(self) -> np.ndarray:
        return self._coin.dur[:self.n]

    def bar(self, k: int = -1) -> Bar:
        """Bar ``k`` (negative = from the end, -1 = bar i). Never beyond i."""
        j = self.i + 1 + k if k < 0 else k
        if not 0 <= j <= self.i:
            raise IndexError(f"bar {k} is outside 0..{self.i}")
        cn = self._coin
        return Bar(int(cn.ts[j]), float(cn.o[j]), float(cn.h[j]), float(cn.l[j]), float(cn.c[j]), float(cn.v[j]),
                   int(cn.dur[j]))

    @property
    def meta(self) -> Mapping[str, Any]:
        return self._meta

    @property
    def graduated(self) -> bool:
        return self.now >= self._coin.graduated_ts

    @property
    def graduated_ts(self) -> float | None:
        """Graduation time once it has happened (None before - it is future information)."""
        return self._coin.graduated_ts if self.graduated else None

    @property
    def age_s(self) -> float:
        return self.now - self._coin.created_ts

    @property
    def supply(self) -> float:
        return self._coin.supply

    def mcap(self, k: int = -1) -> float:
        """Close of bar k x supply (USD)."""
        return self.bar(k).c * self._coin.supply

    @property
    def sol_usd(self) -> float:
        """SOL/USD at ``now`` (public, known at the time)."""
        return self._sol.at(self.now) if self._sol is not None else _costs.FALLBACK_SOL_USD


@dataclass(frozen=True)
class Exits:
    """Exit plan. Absolute USD prices and/or relative values resolved at the fill against the
    entry MID price (open of the fill bar) and fill time. None = not used."""

    stop_price: float | None = None
    take_profit_price: float | None = None
    tp_fraction: float = 1.0
    trail_pct: float | None = None
    time_stop_ts: float | None = None
    trail_after_tp: bool = False  # trail only once the partial take-profit was taken (nightcrawler style)
    stop_pct: float | None = None  # e.g. 0.25 -> stop at entry_mid * 0.75
    take_profit_pct: float | None = None  # e.g. 0.5 -> tp at entry_mid * 1.5
    max_hold_s: float | None = None

    def resolve(self, entry_mid: float, entry_ts: float) -> "Exits":
        stop = self.stop_price
        if self.stop_pct is not None:
            stop = entry_mid * (1 - self.stop_pct)
        tp = self.take_profit_price
        if self.take_profit_pct is not None:
            tp = entry_mid * (1 + self.take_profit_pct)
        tstop = self.time_stop_ts
        if self.max_hold_s is not None:
            tstop = entry_ts + self.max_hold_s
        return Exits(stop_price=stop, take_profit_price=tp, tp_fraction=self.tp_fraction, trail_pct=self.trail_pct,
                     time_stop_ts=tstop, trail_after_tp=self.trail_after_tp)


@dataclass(frozen=True)
class Buy:
    usd: float | None = None  # None = harness sizing (portfolio rule / fixed per-coin size)
    exits: Exits | None = None
    priority: float = 0.0
    tag: str = ""


@dataclass(frozen=True)
class Sell:
    fraction: float = 1.0
    reason: str = "signal"


@dataclass(frozen=True)
class SetExits:
    exits: Exits  # replaces the whole plan; relative fields resolve against the original entry


Action = Buy | Sell | SetExits | None


@dataclass(frozen=True)
class PositionView:
    """Snapshot of the open position at the close of bar i (read-only)."""

    mint: str
    entry_ts: float  # open time of the fill bar
    entry_price: float  # mid price at the fill (open of the fill bar)
    cost_basis: float  # USD spent (incl. fees/impact, excl. network) per token held at entry
    size_usd: float
    tokens: float
    peak: float  # max high since entry, bars <= i (entry mid included)
    bars_held: int
    exits: Exits
    partial_taken: bool
    unrealized_pct: float  # close[i] / entry_price - 1 (mid, before exit costs)


class Strategy:
    """Subclass and implement ``on_candle``. One instance per coin (the factory is called per coin)."""

    name = "strategy"
    #: when flat and ``now - graduated_ts > horizon_s`` the harness stops calling on_candle (speed only)
    horizon_s: float | None = None

    def on_coin_start(self, meta: Mapping[str, Any]) -> None:  # noqa: B027 - optional hook
        pass

    def on_candle(self, i: int, view: View, position: PositionView | None) -> Action:
        raise NotImplementedError


# =========================================================================== engine


@dataclass
class SimConfig:
    start_usd: float = 100.0
    position_pct: float = 0.20
    min_usd: float = 5.0
    max_usd: float = 25.0
    max_concurrent: int = 3
    cooldown_s: float = 1800.0
    fixed_usd: float = 20.0  # per-coin mode
    cost: CostModel = field(default_factory=CostModel)
    wick_fill: str = "half"  # touch | half | worst
    entry_delay_bars: int = 1
    allow_pre_graduation: bool = False
    stop_on_ruin_usd: float = 5.0  # portfolio: no new entries once free cash < min size


@dataclass
class Fill:
    ts: float
    side: str
    mid: float
    tokens: float
    usd: float  # spent (buy, excl. network) or received (sell, excl. network)
    fee_usd: float
    impact_usd: float
    network_usd: float
    reason: str


@dataclass
class Trade:
    mint: str
    symbol: str
    decision_ts: float
    entry_ts: float
    entry_mid: float
    size_usd: float
    tokens: float
    fills: list[Fill] = field(default_factory=list)
    exit_ts: float | None = None
    exit_reason: str | None = None
    tag: str = ""
    created_ts: float = 0.0
    graduated_ts: float = 0.0

    @property
    def closed(self) -> bool:
        return self.exit_ts is not None

    @property
    def proceeds_usd(self) -> float:
        return sum(f.usd for f in self.fills if f.side == "sell")

    @property
    def network_usd(self) -> float:
        return sum(f.network_usd for f in self.fills)

    @property
    def pnl_usd(self) -> float:
        return self.proceeds_usd - self.size_usd - self.network_usd

    @property
    def ret(self) -> float:
        return self.pnl_usd / self.size_usd if self.size_usd else 0.0

    @property
    def costs_usd(self) -> float:
        return sum(f.fee_usd + f.impact_usd + f.network_usd for f in self.fills)

    @property
    def exit_mid_avg(self) -> float:
        sells = [f for f in self.fills if f.side == "sell"]
        tok = sum(f.tokens for f in sells)
        return sum(f.mid * f.tokens for f in sells) / tok if tok else 0.0

    def to_dict(self) -> dict:
        return {"mint": self.mint, "symbol": self.symbol, "decision_ts": self.decision_ts, "entry_ts": self.entry_ts,
                "entry_mid": self.entry_mid, "size_usd": round(self.size_usd, 4), "exit_ts": self.exit_ts,
                "exit_reason": self.exit_reason, "exit_mid_avg": self.exit_mid_avg,
                "pnl_usd": round(self.pnl_usd, 4), "ret_pct": round(self.ret * 100, 3),
                "costs_usd": round(self.costs_usd, 4), "hold_min": round(((self.exit_ts or self.entry_ts)
                                                                          - self.entry_ts) / 60, 1),
                "min_after_grad": round((self.entry_ts - self.graduated_ts) / 60, 1), "tag": self.tag,
                "fills": [dataclasses.asdict(f) for f in self.fills]}


@dataclass
class _Pos:
    trade: Trade
    tokens: float
    exits: Exits
    raw_exits: Exits
    peak: float
    fill_index: int
    partial_taken: bool = False


class CoinEngine:
    """State machine for one coin. The runner calls ``open_bar(j)`` then ``close_bar(j)``."""

    def __init__(self, coin: Coin, strategy: Strategy, cfg: SimConfig, sol: SolUsd, book: "Book") -> None:
        self.coin = coin
        self.strategy = strategy
        self.cfg = cfg
        self.sol = sol
        self.book = book
        self.meta = MappingProxyType({"mint": coin.mint, "symbol": coin.symbol, "name": coin.name,
                                      "created_ts": coin.created_ts, "supply": coin.supply,
                                      "launch": coin.launch})
        self.pos: _Pos | None = None
        self.pending_buy: tuple[int, Buy, float, float] | None = None  # (fill index, order, usd, decision ts)
        self.pending_sell: tuple[int, float, str] | None = None
        self.cooldown_until = -math.inf
        self.trades: list[Trade] = []
        self.decisions: list[tuple[int, str]] = []  # (bar index, action repr) - for invariance tests
        self.finished = False
        strategy.on_coin_start(self.meta)

    # ---------------------------------------------------------------- fills
    def _curve(self, ts: float) -> bool:
        return ts < self.coin.graduated_ts

    def _buy(self, j: int, order: Buy, usd: float, decision_ts: float) -> None:
        cn = self.coin
        mid = float(cn.o[j])
        ts = float(cn.ts[j])
        sol = self.sol.at(ts)
        tokens, br = self.cfg.cost.buy(usd, mid, cn.cost_ctx, sol, curve=self._curve(ts))
        net = self.cfg.cost.network_usd(sol)
        if tokens <= 0:
            self.book.release(self, usd + net)
            return
        trade = Trade(mint=cn.mint, symbol=cn.symbol, decision_ts=decision_ts, entry_ts=ts, entry_mid=mid,
                      size_usd=usd, tokens=tokens, tag=order.tag, created_ts=cn.created_ts,
                      graduated_ts=cn.graduated_ts)
        trade.fills.append(Fill(ts, "buy", mid, tokens, usd, br["fee_usd"], br["impact_usd"], net, "entry"))
        raw = order.exits or Exits()
        self.pos = _Pos(trade=trade, tokens=tokens, exits=raw.resolve(mid, ts), raw_exits=raw, peak=mid, fill_index=j)
        self.book.on_filled(self, usd + net)

    def _sell(self, j: int, tokens: float, price: float, reason: str) -> None:
        pos = self.pos
        assert pos is not None
        cn = self.coin
        ts = float(cn.ts[j])
        tokens = min(tokens, pos.tokens)
        sol = self.sol.at(ts)
        usd, br = self.cfg.cost.sell(tokens, price, cn.cost_ctx, sol, curve=self._curve(ts))
        net = self.cfg.cost.network_usd(sol)
        pos.trade.fills.append(Fill(ts, "sell", price, tokens, usd, br["fee_usd"], br["impact_usd"], net, reason))
        pos.tokens -= tokens
        self.book.on_proceeds(self, usd - net)
        if pos.tokens <= pos.trade.tokens * 1e-9:
            pos.trade.exit_ts = ts
            pos.trade.exit_reason = reason
            self.trades.append(pos.trade)
            self.pos = None
            self.cooldown_until = ts + self.cfg.cooldown_s
            self.book.on_closed(self)

    def _down_fill(self, level: float, o: float, low: float) -> float:
        lvl = min(level, o)
        if self.cfg.wick_fill == "touch":
            return lvl
        if self.cfg.wick_fill == "worst":
            return low
        return (lvl + low) / 2.0

    def _up_fill(self, level: float, o: float, c: float) -> float:
        if o >= level:
            return o
        if self.cfg.wick_fill == "touch" or c >= level:
            return level
        body_top = max(o, c)
        return body_top if self.cfg.wick_fill == "worst" else (level + body_top) / 2.0

    # ---------------------------------------------------------------- bar open (fills + intrabar exits)
    def open_bar(self, j: int) -> None:
        cn = self.coin
        if self.pending_sell is not None and self.pending_sell[0] == j:
            _, frac, reason = self.pending_sell
            self.pending_sell = None
            if self.pos is not None:
                self._sell(j, self.pos.tokens * min(max(frac, 0.0), 1.0), float(cn.o[j]), reason)
        if self.pending_buy is not None and self.pending_buy[0] == j:
            _, order, usd, dts = self.pending_buy
            self.pending_buy = None
            if self.pos is None:
                self._buy(j, order, usd, dts)
            else:
                self.book.release(self, usd + self.cfg.cost.network_usd(self.sol.at(float(cn.ts[j]))))
        if self.pos is not None:
            self._intrabar(j)

    def _intrabar(self, j: int) -> None:
        pos = self.pos
        assert pos is not None
        cn = self.coin
        o, h, low, c, ts = float(cn.o[j]), float(cn.h[j]), float(cn.l[j]), float(cn.c[j]), float(cn.ts[j])
        ex = pos.exits
        prior_peak = pos.peak

        def trail_level() -> float | None:
            if ex.trail_pct is None or (ex.trail_after_tp and not pos.partial_taken):
                return None
            return prior_peak * (1 - ex.trail_pct)

        trail_lvl = trail_level()
        if j != pos.fill_index:  # checks AT the open (we bought at this open on the fill bar)
            if ex.stop_price is not None and o <= ex.stop_price:
                return self._sell(j, pos.tokens, o, "stop_gap")
            if ex.time_stop_ts is not None and ts >= ex.time_stop_ts:
                return self._sell(j, pos.tokens, o, "time_stop")
            if trail_lvl is not None and o <= trail_lvl:
                return self._sell(j, pos.tokens, o, "trail_gap")
        if ex.stop_price is not None and low <= ex.stop_price:
            return self._sell(j, pos.tokens, self._down_fill(ex.stop_price, o, low), "stop")
        if ex.take_profit_price is not None and not pos.partial_taken and h >= ex.take_profit_price:
            price = self._up_fill(ex.take_profit_price, o, c)
            frac = min(max(ex.tp_fraction, 0.0), 1.0)
            if frac >= 1.0 - 1e-12:
                return self._sell(j, pos.tokens, price, "take_profit")
            self._sell(j, pos.tokens * frac, price, "take_profit_partial")
            if self.pos is None:
                return
            pos.partial_taken = True
            trail_lvl = trail_level()  # checked in the same bar against the PREVIOUS peak (pessimistic)
        if trail_lvl is not None and low <= trail_lvl:
            return self._sell(j, pos.tokens, self._down_fill(trail_lvl, o, low), "trail")
        pos.peak = max(prior_peak, h)

    # ---------------------------------------------------------------- bar close (strategy decision)
    def close_bar(self, j: int) -> Buy | None:
        """Call the strategy at the close of bar j. Returns a Buy request for the runner (or None)."""
        cn = self.coin
        now = float(cn.ts[j] + cn.dur[j])
        if self.pos is None and self.pending_buy is None and self.strategy.horizon_s is not None \
                and now - cn.graduated_ts > self.strategy.horizon_s:
            self.finished = True
            return None
        view = View(cn, j, self.meta, self.sol)
        pv = self._pos_view(j) if self.pos is not None else None
        action = self.strategy.on_candle(j, view, pv)
        if action is None:
            return None
        self.decisions.append((j, repr(action)))
        nxt = j + self.cfg.entry_delay_bars
        if isinstance(action, Buy):
            if self.pos is not None or self.pending_buy is not None or now < self.cooldown_until:
                return None
            if not self.cfg.allow_pre_graduation and now < cn.graduated_ts:
                return None
            if nxt >= cn.n:
                return None
            return action
        if isinstance(action, Sell):
            if self.pos is not None and nxt < cn.n:
                self.pending_sell = (nxt, action.fraction, action.reason)
            return None
        if isinstance(action, SetExits):
            if self.pos is not None:
                self.pos.raw_exits = action.exits
                self.pos.exits = action.exits.resolve(self.pos.trade.entry_mid, self.pos.trade.entry_ts)
            return None
        raise TypeError(f"strategy returned {action!r}; expected Buy, Sell, SetExits or None")

    def accept_buy(self, j: int, order: Buy, usd: float, decision_ts: float) -> None:
        self.pending_buy = (j + self.cfg.entry_delay_bars, order, usd, decision_ts)

    def _pos_view(self, j: int) -> PositionView:
        pos = self.pos
        assert pos is not None
        t = pos.trade
        return PositionView(mint=t.mint, entry_ts=t.entry_ts, entry_price=t.entry_mid,
                            cost_basis=t.size_usd / t.tokens, size_usd=t.size_usd, tokens=pos.tokens,
                            peak=pos.peak, bars_held=j - pos.fill_index + 1, exits=pos.exits,
                            partial_taken=pos.partial_taken,
                            unrealized_pct=float(self.coin.c[j]) / t.entry_mid - 1.0)

    def end(self) -> None:
        """End of data: close an open position at the last close (reason end_of_data)."""
        if self.pending_buy is not None:
            _, _, usd, _ = self.pending_buy
            self.pending_buy = None
            self.book.release(self, usd + self.cfg.cost.network_usd(self.sol.at(float(self.coin.ts[-1]))))
        if self.pos is not None:
            j = self.coin.n - 1
            self._sell(j, self.pos.tokens, float(self.coin.c[j]), "end_of_data")

    def mark_value(self, j: int) -> float:
        return self.pos.tokens * float(self.coin.c[j]) if self.pos is not None else 0.0


class Book:
    """Cash accounting interface (per-coin mode: unlimited; portfolio: shared)."""

    def release(self, eng: CoinEngine, usd: float) -> None: ...
    def on_filled(self, eng: CoinEngine, usd: float) -> None: ...
    def on_proceeds(self, eng: CoinEngine, usd: float) -> None: ...
    def on_closed(self, eng: CoinEngine) -> None: ...


class _Unlimited(Book):
    pass


class _Portfolio(Book):
    def __init__(self, cfg: SimConfig) -> None:
        self.cfg = cfg
        self.cash = cfg.start_usd
        self.reserved: dict[str, float] = {}
        self.open: set[str] = set()

    def busy(self) -> int:
        return len(self.open) + len(self.reserved)

    def reserve(self, eng: CoinEngine, usd: float) -> None:
        self.cash -= usd
        self.reserved[eng.coin.mint] = usd

    def release(self, eng: CoinEngine, usd: float) -> None:
        self.cash += self.reserved.pop(eng.coin.mint, usd)

    def on_filled(self, eng: CoinEngine, usd: float) -> None:
        self.reserved.pop(eng.coin.mint, None)  # cash already deducted at reservation
        self.open.add(eng.coin.mint)

    def on_proceeds(self, eng: CoinEngine, usd: float) -> None:
        self.cash += usd

    def on_closed(self, eng: CoinEngine) -> None:
        self.open.discard(eng.coin.mint)


# =========================================================================== runners


@dataclass
class Result:
    name: str
    mode: str
    trades: list[Trade]
    equity: list[tuple[float, float]]
    cfg: SimConfig
    n_coins: int
    decisions: dict[str, list] = field(default_factory=dict)
    rejected: dict[str, int] = field(default_factory=dict)

    def metrics(self, bootstrap: int = 2000, seed: int = 7) -> dict:
        return metrics(self.trades, self.equity if self.mode == "portfolio" else None,
                       self.cfg.start_usd if self.mode == "portfolio" else None, bootstrap, seed,
                       n_coins=self.n_coins)

    def summary(self, bootstrap: int = 2000) -> str:
        m = self.metrics(bootstrap)
        keys = ["trades", "coins_traded", "win_rate_pct", "avg_ret_pct", "median_ret_pct", "profit_factor",
                "expectancy_usd", "exp_ci95_pct", "total_return_pct", "max_drawdown_pct", "best_coin_share_pct",
                "top3_share_pct", "costs_usd"]
        parts = [f"{self.name} [{self.mode}, {self.n_coins} coins]"]
        for k in keys:
            if k in m and m[k] is not None:
                v = m[k]
                parts.append(f"{k}={v if not isinstance(v, float) else round(v, 3)}")
        if self.rejected:
            parts.append(f"rejected={self.rejected}")
        return "  ".join(parts)


def _factory(strategy: Callable[[], Strategy] | type) -> Callable[[], Strategy]:
    return strategy  # a class or a zero-arg callable


def run_per_coin(strategy: Callable[[], Strategy], coins: Sequence[Coin], cfg: SimConfig | None = None,
                 sol: SolUsd | None = None, keep_decisions: bool = False) -> Result:
    """Every coin simulated independently with a fixed ``cfg.fixed_usd`` per entry."""
    cfg = cfg or SimConfig()
    guard_coins(coins)
    sol = sol or SolUsd.from_lab()
    book = _Unlimited()
    trades, decisions, name = [], {}, None
    for coin in coins:
        strat = strategy()
        name = name or getattr(strat, "name", type(strat).__name__)
        eng = CoinEngine(coin, strat, cfg, sol, book)
        for j in range(coin.n):
            eng.open_bar(j)
            if eng.finished:
                if eng.pos is None and eng.pending_buy is None and eng.pending_sell is None:
                    break
                continue
            req = eng.close_bar(j)
            if req is not None:
                usd = req.usd if req.usd is not None else cfg.fixed_usd
                eng.accept_buy(j, req, usd, float(coin.ts[j] + coin.dur[j]))
        eng.end()
        trades.extend(eng.trades)
        if keep_decisions:
            decisions[coin.mint] = list(eng.decisions)
    return Result(name or "strategy", "per_coin", trades, [], cfg, len(coins), decisions)


def run_portfolio(strategy: Callable[[], Strategy], coins: Sequence[Coin], cfg: SimConfig | None = None,
                  sol: SolUsd | None = None, keep_decisions: bool = False) -> Result:
    """All coins merged chronologically with a shared bankroll (see module docstring)."""
    cfg = cfg or SimConfig()
    guard_coins(coins)
    sol = sol or SolUsd.from_lab()
    book = _Portfolio(cfg)
    engines: list[CoinEngine] = []
    name = None
    heap: list[tuple[float, int, int, int]] = []  # (time, kind 0=close 1=open, coin idx, bar idx)
    for k, coin in enumerate(coins):
        strat = strategy()
        name = name or getattr(strat, "name", type(strat).__name__)
        engines.append(CoinEngine(coin, strat, cfg, sol, book))
        heapq.heappush(heap, (float(coin.ts[0]), 1, k, 0))
    last_j = [-1] * len(coins)
    equity: list[tuple[float, float]] = []
    rejected: dict[str, int] = defaultdict(int)
    done = [False] * len(coins)

    index = {c.mint: k for k, c in enumerate(coins)}

    def mark(t: float) -> None:
        val = book.cash + sum(book.reserved.values())
        for mint in book.open:
            k2 = index[mint]
            if last_j[k2] >= 0:
                val += engines[k2].mark_value(last_j[k2])
        if equity and equity[-1][0] == t:
            equity[-1] = (t, val)
        else:
            equity.append((t, val))

    while heap:
        t, kind, _, _ = heap[0]
        batch = []
        while heap and heap[0][0] == t and heap[0][1] == kind:
            batch.append(heapq.heappop(heap))
        if kind == 1:  # opens
            for _, _, k, j in batch:
                eng = engines[k]
                eng.open_bar(j)
                cn = eng.coin
                heapq.heappush(heap, (float(cn.ts[j] + cn.dur[j]), 0, k, j))
            continue
        # closes: decisions, then serve buy requests in priority order
        requests = []
        for _, _, k, j in batch:
            eng = engines[k]
            last_j[k] = j
            req = None
            if not eng.finished:
                req = eng.close_bar(j)
            if req is not None:
                requests.append((-req.priority, eng.coin.created_ts, eng.coin.mint, k, j, req))
            nxt = j + 1
            idle = eng.finished and eng.pos is None and eng.pending_buy is None and eng.pending_sell is None
            if nxt < eng.coin.n and not idle:
                heapq.heappush(heap, (float(eng.coin.ts[nxt]), 1, k, nxt))
            elif not done[k]:
                done[k] = True
                eng.end()
        requests.sort(key=lambda r: r[:3])
        mark(t)
        equity_now = equity[-1][1]
        for *_, k, j, req in requests:
            eng = engines[k]
            if book.busy() >= cfg.max_concurrent:
                rejected["max_concurrent"] += 1
                continue
            net = cfg.cost.network_usd(sol.at(t))
            size = size_position_usd(equity_now, cfg.position_pct, cfg.min_usd, cfg.max_usd)
            if req.usd is not None:
                size = min(size, req.usd) if size > 0 else 0.0
            size = min(size, book.cash - 2 * net)  # keep the exit's network fee
            if size < cfg.min_usd - 1e-9:
                rejected["cash"] += 1
                continue
            book.reserve(eng, size + net)
            eng.accept_buy(j, req, size, t)
    for k, eng in enumerate(engines):
        if not done[k]:
            eng.end()
    if equity:
        equity.append((equity[-1][0] + 60, book.cash))
    trades = sorted((t for e in engines for t in e.trades), key=lambda t: t.entry_ts)
    decisions = {e.coin.mint: list(e.decisions) for e in engines} if keep_decisions else {}
    return Result(name or "strategy", "portfolio", trades, equity, cfg, len(coins), decisions, dict(rejected))


# =========================================================================== lookahead audit


def truncate(coin: Coin, last: int) -> Coin:
    """Copy of ``coin`` holding only bars 0..last (the future does not exist in the copy)."""
    sl = slice(0, last + 1)
    return dataclasses.replace(coin, ts=_ro(coin.ts[sl].copy()), o=_ro(coin.o[sl].copy()), h=_ro(coin.h[sl].copy()),
                               l=_ro(coin.l[sl].copy()), c=_ro(coin.c[sl].copy()), v=_ro(coin.v[sl].copy()),
                               dur=_ro(coin.dur[sl].copy()))


def audit_lookahead(strategy: Callable[[], Strategy], coins: Sequence[Coin], cuts_per_coin: int = 3,
                    seed: int = 0, cfg: SimConfig | None = None, sol: SolUsd | None = None) -> list[str]:
    """Run each coin in full and truncated at random bars; every decision taken at a bar <= cut
    and every fill at a bar <= cut must be identical. Catches ANY peek at the future (including
    reaching into private attributes), because the truncated copy has no future. Returns the
    list of mismatches (empty = clean)."""
    cfg = cfg or SimConfig()
    rng = random.Random(seed)
    sol = sol or SolUsd.from_lab()
    problems = []
    for coin in coins:
        full = run_per_coin(strategy, [coin], cfg, sol, keep_decisions=True)
        fd = full.decisions.get(coin.mint, [])
        ffills = [(f.ts, f.side, round(f.mid, 12), f.reason) for t in full.trades for f in t.fills]
        for _ in range(cuts_per_coin):
            if coin.n < 3:
                break
            cut = rng.randrange(1, coin.n - 1)
            part = run_per_coin(strategy, [truncate(coin, cut)], cfg, sol, keep_decisions=True)
            pd_ = [d for d in part.decisions.get(coin.mint, []) if d[0] <= cut]
            fd_ = [d for d in fd if d[0] <= cut]
            if pd_ != fd_:
                problems.append(f"{coin.symbol} cut {cut}: decisions differ")
            limit = float(coin.ts[cut])
            pf = [(f.ts, f.side, round(f.mid, 12), f.reason) for t in part.trades for f in t.fills
                  if f.ts <= limit and f.reason != "end_of_data"]
            ff = [x for x in ffills if x[0] <= limit and x[3] != "end_of_data"]
            if pf != ff:
                problems.append(f"{coin.symbol} cut {cut}: fills differ")
    return problems


# =========================================================================== metrics


def _max_dd(values: Sequence[float]) -> float:
    peak, worst = -math.inf, 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = max(worst, (peak - v) / peak * 100)
    return worst


def bootstrap_ci(trades: Sequence[Trade], b: int = 2000, seed: int = 7, stat: str = "ret") -> tuple[float, float] | None:
    """Coin-level bootstrap 95 % CI of the mean per-trade return (stat="ret") or P&L (stat="pnl"):
    resample COINS with replacement, pool their trades, take the mean."""
    by: dict[str, list[float]] = defaultdict(list)
    for t in trades:
        by[t.mint].append(t.ret if stat == "ret" else t.pnl_usd)
    groups = list(by.values())
    if len(groups) < 2:
        return None
    rng = random.Random(seed)
    sums = [sum(g) for g in groups]
    lens = [len(g) for g in groups]
    n = len(groups)
    means = []
    for _ in range(b):
        s = cnt = 0
        for _ in range(n):
            i = rng.randrange(n)
            s += sums[i]
            cnt += lens[i]
        means.append(s / cnt)
    means.sort()
    return means[int(0.025 * b)], means[int(0.975 * b) - 1]


def metrics(trades: Sequence[Trade], equity: Sequence[tuple[float, float]] | None = None,
            start_usd: float | None = None, bootstrap: int = 2000, seed: int = 7, n_coins: int | None = None) -> dict:
    trades = [t for t in trades if t.closed]
    rets = [t.ret for t in trades]
    pnls = [t.pnl_usd for t in trades]
    gw = sum(p for p in pnls if p > 0)
    gl = -sum(p for p in pnls if p <= 0)
    by_coin: dict[str, float] = defaultdict(float)
    for t in trades:
        by_coin[t.mint] += t.pnl_usd
    total = sum(pnls)
    ranked = sorted(by_coin.values(), reverse=True)
    ci = bootstrap_ci(trades, bootstrap, seed) if bootstrap and trades else None
    out: dict[str, Any] = {
        "coins": n_coins, "trades": len(trades), "coins_traded": len(by_coin),
        "win_rate_pct": 100 * sum(1 for p in pnls if p > 0) / len(pnls) if pnls else None,
        "avg_ret_pct": 100 * statistics.fmean(rets) if rets else None,
        "median_ret_pct": 100 * statistics.median(rets) if rets else None,
        "profit_factor": gw / gl if gl > 0 else None,
        "net_pnl_usd": total,
        "expectancy_usd": total / len(trades) if trades else None,
        "exp_ci95_pct": (round(100 * ci[0], 3), round(100 * ci[1], 3)) if ci else None,
        "costs_usd": sum(t.costs_usd for t in trades),
        "best_coin_pnl_usd": ranked[0] if ranked else None,
        # share of NET profit from the single best / top-3 coins (>100 % = the rest lost money)
        "best_coin_share_pct": 100 * ranked[0] / total if ranked and total > 0 else None,
        "top3_share_pct": 100 * sum(ranked[:3]) / total if ranked and total > 0 else None,
        "pnl_without_best_coin_usd": total - ranked[0] if ranked else None,
        "pnl_without_top3_usd": total - sum(ranked[:3]) if ranked else None,
        "exit_reasons": dict(sorted(_count(t.exit_reason or "?" for t in trades).items())),
        "avg_hold_min": statistics.fmean((t.exit_ts - t.entry_ts) / 60 for t in trades) if trades else None,
    }
    if equity:
        vals = [e for _, e in equity]
        start = start_usd if start_usd is not None else vals[0]
        out["total_return_pct"] = (vals[-1] - start) / start * 100
        out["final_equity_usd"] = vals[-1]
        out["max_drawdown_pct"] = _max_dd([start, *vals])
    hours: dict[int, list[Trade]] = defaultdict(list)
    for t in trades:
        hours[int(t.entry_ts // 3600 % 24)].append(t)
    out["by_hour_utc"] = {h: {"trades": len(ts_), "avg_ret_pct": round(100 * statistics.fmean(x.ret for x in ts_), 3),
                              "pnl_usd": round(sum(x.pnl_usd for x in ts_), 3)} for h, ts_ in sorted(hours.items())}
    return out


def _count(items: Iterable[str]) -> dict[str, int]:
    d: dict[str, int] = defaultdict(int)
    for x in items:
        d[x] += 1
    return dict(d)


def print_report(res: Result, bootstrap: int = 2000, hours: bool = False) -> dict:
    m = res.metrics(bootstrap)
    print(res.summary(bootstrap))
    print(f"    exits: {m['exit_reasons']}  pnl w/o best coin: {m['pnl_without_best_coin_usd']}  "
          f"w/o top3: {m['pnl_without_top3_usd']}")
    if hours:
        print("    by hour:", m["by_hour_utc"])
    return m


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "splits":
        d = make_splits()
        print({k: len(d[k]) for k in ("train", "validation", "test")}, d["bounds_created_ts"])
