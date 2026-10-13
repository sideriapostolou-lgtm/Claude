"""The Kalshi arena: a town of practice Kalshi Bitcoin desks that must pay rent or be evicted (PRACTICE money only).

The owner's ask, 2026-10-13: "Give our bots the incentive they're giving Grok bots: make money or die." A program does
not feel the threat, but a population can be selected by it. The arena is that selection, run on the live Kalshi
Bitcoin 15-minute windows (``KXBTC15M``) the real desk trades:

* :data:`POPULATION` residents, each a practice speed desk (:class:`~nightcrawler.speeddesk_model.PracticeDesk`) with
  its own *genes* (:data:`NUMBERS` and :data:`SWITCHES`: its bid discount, first-buy size, pair cap, imbalance limit,
  when it may open a window, when buying stops and its pair lock starts, a protective stop, fresh rounds after a
  complete pair, and a slot for signal filters, :data:`FILTERS`). Each starts with :data:`START_CASH` of practice
  money, the real account's size as the owner gave it.
* One resident, the CONTROL, always runs the live rules (:func:`live_genes`, from the deployed settings and
  ``LiveLimits``' own clamps). It is never evicted and every comparison is against it, window by window.
* Rent: the first window settled on a new UTC day charges every resident :data:`RENT_USD`, about the whole Railway
  bill ($5 a month) EACH, so every resident must earn the town's cost on its own. A resident that cannot pay is
  EVICTED; so is one whose money falls under :data:`BROKE_USD` (it could not fund a window at the live $10), and one
  that :func:`nightcrawler.deskguard.judge` calls ``losing`` on its traded windows. The graveyard keeps the record.
* Births: every empty home goes at once to a child of one of the richest residents (the top half by money, control
  included, the richer more often): each number nudged by up to :data:`MUTATE` of its range, sometimes redrawn.
* CANDIDATE: a challenger whose traded record ``judge`` calls ``winning`` (100 or more windows) AND whose paired
  per-window difference against the control on the same windows has t >= :data:`CANDIDATE_T` over at least
  :data:`CANDIDATE_WINDOWS` windows. It is SHOWN to the owner, a lead for a pre-registered test and not proof: many
  challengers watched after every window will throw up lucky ones. Nothing here changes a live setting.

PRACTICE ONLY. This module holds no client, no key, no Settings object after :func:`arena_config`, and no order path:
its residents trade pretend money against the same public books and prints the live desk sees, each filling on its
own (no resident competes with another or with the real desk). It writes ``DATA_DIR/kalshi_arena/state.json`` and a
small ``panel.json`` for the page.

SPEED. The live desk's event loop is latency-critical. It only appends each Kalshi book and print to a bounded queue
(:class:`ArenaFeed`: one ``deque.append``, never a lock, drops counted when full); prices, volatility, windows and
outcomes are read from the speed desk's own immutable snapshot. Everything else runs in this module's daemon thread,
in work slices of about :data:`SLICE_S` followed by a :data:`REST_S` sleep, so the thread never holds Python's lock
long enough to delay the live loop. A failing town halts itself after :data:`HALT_AFTER` errors in a row; it never
stops the speed desk. The ``kalshi_arena_status`` line reports the queue, drops, slice times and duty.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import random
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from .deskguard import LOSING, PHRASES, WINNING, judge
from .speeddesk_live_model import LiveLimits
from .speeddesk_model import (
    BitcoinTape,
    Book,
    PracticeDesk,
    Side,
    SpeedConfig,
    Trade,
    Window,
)

if TYPE_CHECKING:
    from .config import Settings

log = logging.getLogger("nightcrawler.kalshi_arena")

STATE_VERSION = 1
LABEL = "Practice (pretend money)"
SERIES = "KXBTC15M-"
START_CASH = 50.0  # the real Kalshi account's size, as the owner gave it on 2026-10-13
RENT_USD = 0.20  # per resident per UTC day: Railway's ~$5 a month (~$0.17 a day) for the whole service, plus 20 %
BROKE_USD = 10.0  # under this a resident cannot fund one window at the live $10 budget: evicted
POPULATION = 12  # the control is one of them
RECORD_KEEP = 960  # windows of record per resident (10 days); the verdict reads them
GRAVE_KEEP = 40
EVENTS_KEEP = 60
CANDIDATE_WINDOWS = 100  # paired windows against the control before a challenger can be a candidate
CANDIDATE_T = 2.0
MUTATE = 0.12  # a child's number moves by up to this share of its range
NEW_VALUE_P = 0.1  # ... or is redrawn anywhere in its range this often
FLIP_P = 0.1  # a child's switch (and each registered filter) flips this often
SEED = 20261013
# The feed and the scheduler (module docstring, SPEED).
QUEUE_MAX = 8192  # books and prints waiting for the arena; beyond it new ones are dropped and counted
DRAIN_MAX = 512  # events handled per pass
POLL_S = 0.1  # a pass of the town
EVAL_S = 0.25  # each resident decides at most this often (the live desk's IDLE_STEP_S)
SLICE_S = 0.0002  # a work slice, then a rest: the live loop never waits long for Python's lock
REST_S = 0.002
SLICES_KEEP = 2048  # recent slice durations for the status line
TRADE_LATE_S = 3.0  # a print older than this when the arena reads it is too late for a practice fill (counted)
VOID_AFTER_S = 7200.0  # a window with no outcome this long after its close is void for everyone
SAVE_EVERY_S = 60.0
SAVE_SOON_S = 10.0  # after a birth, an eviction or a flag, a save at most this soon
STATUS_EVERY_S = 300.0
HALT_AFTER = 5  # failed passes in a row before the town halts itself
SETTLED_KEEP = 200  # settled windows remembered, so none is ever added again
TERMS = ("taker_coefficient", "maker_coefficient", "tick_size", "min_trade_qty", "fee_rounding")
NOTE = ("Practice town: every resident fills on its own against the same live Kalshi prints; the control runs the live "
        "rules as the practice model simulates them, so the comparison is against it. A candidate is a lead for a "
        "pre-registered test, not proof; real money changes only on the owner's word.")
NAMES = ("Ada", "Bo", "Cy", "Dex", "Eve", "Fin", "Gus", "Hal", "Ivy", "Jax", "Kai", "Lux", "Mae", "Nox", "Oz", "Pip",
         "Quin", "Rex", "Sol", "Tex", "Uma", "Vic", "Wren", "Xia", "Yul", "Zed", "Ari", "Bex", "Cal", "Dot", "Echo",
         "Fox", "Gem", "Hex", "Ink", "Jet", "Kit", "Lev", "Moe", "Nia")


@dataclass(frozen=True)
class Gene:
    """A number gene's range and grid."""

    lo: float
    hi: float
    step: float
    what: str


#: The number genes. A resident's value sits on the grid; the control's (the live rules) may lie outside a range,
#: and its children are clamped into it.
NUMBERS: dict[str, Gene] = {
    "make_edge": Gene(0.020, 0.060, 0.005, "resting bid this far below fair value"),
    "starter": Gene(2, 10, 1, "contracts in a window's first buy (and in each round's)"),
    "pair_cap": Gene(0.95, 0.99, 0.005, "most a matched pair may cost, fees included"),
    "max_imbalance": Gene(0.10, 0.25, 0.01, "most one side may exceed the other, as a share of all contracts"),
    "starter_delay_s": Gene(0, 180, 5, "no first buy in a window's first seconds"),
    "starter_stop_s": Gene(0, 600, 10, "no first buy in a window's last seconds"),
    "close_s": Gene(120, 300, 5, "buying stops, and the lock starts, this long before the close"),
    "lock_max": Gene(0.90, 0.99, 0.01, "most a lock (or stop) pays per contract"),
    "stop_s": Gene(300, 840, 10, "the protective stop watches from this long before the close"),
    "stop_cost": Gene(1.05, 1.25, 0.01, "... and completes the pair once completing would cost this a pair"),
}
#: The on/off genes.
SWITCHES: dict[str, str] = {
    "lock": "complete a half-filled pair at the ask from close_s before the close (the live rule)",
    "stop": "the protective stop",
    "rounds": "a fresh first-size buy after each complete pair",
}
#: The values that reproduce the practice desk's plain behaviour, for a gene a saved resident does not carry yet.
GENE_DEFAULTS: dict[str, Any] = {"make_edge": 0.03, "starter": 5, "pair_cap": 0.99, "max_imbalance": 0.25,
                                 "starter_delay_s": 0, "starter_stop_s": 0, "close_s": 240, "lock_max": 0.97,
                                 "stop_s": 570, "stop_cost": 1.15, "lock": True, "stop": False, "rounds": False,
                                 "filters": []}
#: What every resident shares with the live desk when no settings are given: production's values on 2026-10-13
#: (takes off, 5-contract clip, $10 a window, $20 open, $6 day stop).
DEFAULT_FIXED: dict[str, Any] = {"take_edge": 1.0, "clip": 5.0, "window_usd": 10.0, "open_usd": 20.0,
                                 "day_stop_usd": 6.0, "latency_ms": 250.0, "whole_contracts": True}


class MarketView(Protocol):
    """What the arena reads from the speed desk's published snapshot (``speeddesk_live.LiveSnapshot``)."""

    @property
    def windows(self) -> tuple[Window, ...]: ...

    @property
    def books(self) -> Mapping[tuple[str, Side], Book]: ...

    @property
    def bitcoin_price(self) -> float | None: ...

    @property
    def bitcoin_at(self) -> float | None: ...

    @property
    def sigma(self) -> float | None: ...

    @property
    def maker_windows(self) -> frozenset[str]: ...

    @property
    def outcomes(self) -> Mapping[str, bool]: ...


#: A signal filter: True lets a window's starter go. The slot ships empty; a filter is one entry here plus its own
#: lab test, and a resident uses it only when its genes name it (``genes["filters"]``).
SignalFilter = Callable[[Window, float, MarketView], bool]
FILTERS: dict[str, SignalFilter] = {}


# ---------------------------------------------------------------------- genes
def _grid(name: str, value: float) -> float:
    gene = NUMBERS[name]
    value = min(gene.hi, max(gene.lo, value))
    return round(gene.lo + round((value - gene.lo) / gene.step) * gene.step, 6)


def _draw(name: str, rng: random.Random) -> float:
    gene = NUMBERS[name]
    return round(gene.lo + rng.randint(0, round((gene.hi - gene.lo) / gene.step)) * gene.step, 6)


def random_genes(rng: random.Random) -> dict[str, Any]:
    genes: dict[str, Any] = {name: _draw(name, rng) for name in NUMBERS}
    genes.update({name: rng.random() < 0.5 for name in SWITCHES})
    genes["filters"] = []
    return genes


def child_genes(parent: Mapping[str, Any], rng: random.Random) -> dict[str, Any]:
    """The parent's genes, each number nudged by up to :data:`MUTATE` of its range (kept inside it and on its grid),
    redrawn one time in ten; each switch, and each registered filter, flips one time in ten."""
    genes: dict[str, Any] = {}
    for name, gene in NUMBERS.items():
        base = parent.get(name)
        if not isinstance(base, (int, float)) or isinstance(base, bool) or rng.random() < NEW_VALUE_P:
            genes[name] = _draw(name, rng)
        else:
            genes[name] = _grid(name, float(base) + rng.uniform(-MUTATE, MUTATE) * (gene.hi - gene.lo))
    for name in SWITCHES:
        value = parent.get(name)
        genes[name] = (rng.random() < 0.5) if not isinstance(value, bool) else (value != (rng.random() < FLIP_P))
    filters = {str(name) for name in parent.get("filters") or [] if name in FILTERS}
    for name in sorted(FILTERS):
        if rng.random() < FLIP_P:
            filters ^= {name}
    genes["filters"] = sorted(filters)
    return genes


def _limits(settings: Settings) -> LiveLimits:
    """The live companion's limits from the deployed settings, with LiveLimits' own clamps (speeddesk_live)."""
    return LiveLimits(window_usd=settings.speeddesk_kalshi_window_usd, open_usd=settings.speeddesk_kalshi_open_usd,
                      day_loss_usd=settings.speeddesk_kalshi_day_stop_usd,
                      total_loss_usd=settings.speeddesk_kalshi_total_stop_usd, pair_cap=settings.speeddesk_pair_cap,
                      max_imbalance=settings.speeddesk_max_imbalance, clip=settings.speeddesk_kalshi_clip,
                      cutoff_s=settings.speeddesk_kalshi_cutoff_s, lock_s=settings.speeddesk_kalshi_lock_s,
                      lock_max_price=settings.speeddesk_kalshi_lock_max_price)


def live_genes(settings: Settings) -> dict[str, Any]:
    """The control's genes: the live rules. Its first buy is the clip (live's clip caps every order), buying stops
    and the lock starts at LiveLimits.lock_s, and nothing live lacks (stop, rounds, waits, filters) is on."""
    limits = _limits(settings)
    return {**GENE_DEFAULTS, "make_edge": float(settings.speeddesk_make_edge),
            "starter": math.floor(limits.clip + 1e-9), "pair_cap": limits.pair_cap,
            "max_imbalance": limits.max_imbalance, "close_s": limits.lock_s, "lock_max": limits.lock_max_price,
            "lock": True, "stop": False, "rounds": False, "starter_delay_s": 0, "starter_stop_s": 0, "filters": []}


def fixed_config(settings: Settings) -> dict[str, Any]:
    """What every resident shares with the live desk (SpeedConfig fields): takes, the clip, budgets, latency."""
    limits = _limits(settings)
    return {"take_edge": float(settings.speeddesk_take_edge), "clip": float(math.floor(limits.clip + 1e-9)),
            "window_usd": limits.window_usd, "open_usd": limits.open_usd, "day_stop_usd": limits.day_loss_usd,
            "latency_ms": float(settings.speeddesk_latency_ms), "whole_contracts": True}


def speed_config(genes: Mapping[str, Any], fixed: Mapping[str, Any]) -> SpeedConfig:
    """A resident's practice desk. Like live, the first buy is also held to whole pairs at the pair cap."""
    pair_cap = float(genes["pair_cap"])
    starter = min(float(genes["starter"]), math.floor(float(fixed["window_usd"]) / pair_cap + 1e-9))
    close_s = float(genes["close_s"])
    return SpeedConfig(**{**fixed, "make_edge": float(genes["make_edge"]), "pair_cap": pair_cap,
                          "max_imbalance": float(genes["max_imbalance"]), "cutoff_s": close_s,
                          "starter_clip": max(1.0, starter), "starter_delay_s": float(genes["starter_delay_s"]),
                          "starter_stop_s": float(genes["starter_stop_s"]), "rounds": bool(genes["rounds"]),
                          "lock_s": close_s if genes["lock"] else 0.0, "lock_max_price": float(genes["lock_max"]),
                          "stop_s": float(genes["stop_s"]) if genes["stop"] else 0.0,
                          "stop_pair_cost": float(genes["stop_cost"]) if genes["stop"] else 0.0})


def rule_id(genes: Mapping[str, Any]) -> str:
    """Twelve hex characters that change whenever any gene changes."""
    return hashlib.sha256(json.dumps(dict(genes), sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


def adoptable(genes: Mapping[str, Any], clip: float) -> dict[str, Any]:
    """How a candidate's genes could reach the live desk: the settings that express them today, and what would need
    new code (and the owner's word) first. Shown only; nothing reads it back."""
    close_s = int(genes["close_s"])
    settings = {"SPEEDDESK_MAKE_EDGE": genes["make_edge"], "SPEEDDESK_PAIR_CAP": genes["pair_cap"],
                "SPEEDDESK_MAX_IMBALANCE": genes["max_imbalance"], "SPEEDDESK_KALSHI_CUTOFF_S": close_s,
                "SPEEDDESK_KALSHI_LOCK_S": close_s, "SPEEDDESK_KALSHI_LOCK_MAX_PRICE": genes["lock_max"]}
    needs: list[str] = []
    if not genes["lock"]:
        needs.append("no end lock (the live lock cannot be switched off)")
    if int(genes["starter"]) != int(clip):
        needs.append(f"a first buy of {int(genes['starter'])} contracts while later orders stay at {int(clip)} "
                     "(SPEEDDESK_KALSHI_CLIP caps every order)")
    if genes["stop"]:
        needs.append(f"a protective stop from {int(genes['stop_s'])} s before the close at ${genes['stop_cost']:.2f} "
                     "a pair")
    if genes["rounds"]:
        needs.append("rounds: a fresh first buy after each complete pair")
    if genes["starter_delay_s"]:
        needs.append(f"no first buy in a window's first {int(genes['starter_delay_s'])} s")
    if genes["starter_stop_s"] > close_s:
        needs.append(f"no first buy in a window's last {int(genes['starter_stop_s'])} s")
    if genes["filters"]:
        needs.append("signal filters: " + ", ".join(genes["filters"]))
    return {"settings": settings, "needs_code": needs}


def style(genes: Mapping[str, Any]) -> str:
    """A resident's way of trading in a few words: 'edge 0.035, first 4, cap 0.980, imb 0.20, close 240s, lock@0.97'."""
    parts = [f"edge {float(genes['make_edge']):.3f}", f"first {int(genes['starter'])}",
             f"cap {float(genes['pair_cap']):.3f}", f"imb {float(genes['max_imbalance']):.2f}",
             f"close {int(genes['close_s'])}s"]
    parts.append(f"lock@{float(genes['lock_max']):.2f}" if genes["lock"] else "no lock")
    if genes["stop"]:
        parts.append(f"stop {int(genes['stop_s'])}s@{float(genes['stop_cost']):.2f}")
    if genes["rounds"]:
        parts.append("rounds")
    if genes["starter_delay_s"]:
        parts.append(f"wait {int(genes['starter_delay_s'])}s")
    if genes["starter_stop_s"] > float(genes["close_s"]):
        parts.append(f"no first buy last {int(genes['starter_stop_s'])}s")
    parts.extend(f"filter {name}" for name in genes["filters"])
    return ", ".join(parts)


# ---------------------------------------------------------------------- configuration
@dataclass(frozen=True, eq=False)
class ArenaConfig:
    """Everything the town needs: numbers, a path and two gene tables. It holds no Settings and no secret."""

    data_dir: Path
    population: int = POPULATION
    rent_usd: float = RENT_USD
    broke_usd: float = BROKE_USD
    start_cash: float = START_CASH
    control: dict[str, Any] = field(default_factory=lambda: dict(GENE_DEFAULTS))
    fixed: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_FIXED))


def arena_config(settings: Settings) -> ArenaConfig:
    """The only reader of Settings: practice numbers plus the live rules the control copies."""
    return ArenaConfig(data_dir=Path(settings.data_dir), population=int(settings.kalshi_arena_population),
                       rent_usd=float(settings.kalshi_arena_rent_usd), broke_usd=float(settings.kalshi_arena_broke_usd),
                       start_cash=START_CASH, control=live_genes(settings), fixed=fixed_config(settings))


# ---------------------------------------------------------------------- the feed
class FedTape(BitcoinTape):
    """The speed desk's own Bitcoin price, time and volatility (the sigma the live desk decides with), shared by
    every resident; nothing is recomputed per desk. A Kalshi window opens on the venue's strike, never a print."""

    def __init__(self) -> None:
        super().__init__()
        self.fed_sigma: float | None = None

    def feed(self, price: float | None, at: float | None, sigma: float | None) -> None:
        if price is not None and at is not None and self.tick(price, at):
            self.fed_sigma = sigma

    def tick(self, price: float, at: float) -> bool:
        if not math.isfinite(price) or price <= 0 or not math.isfinite(at):
            return False
        if self.last_at is not None and at < self.last_at:
            return False
        if self.started_at is None:
            self.started_at = at
        self.last_at, self.price = at, price
        return True

    def sigma(self, now: float, minimum: int = 1500, warmup_s: float = 3600.0) -> float | None:
        return self.fed_sigma

    def opening(self, start: float) -> float | None:
        return None


class ArenaFeed:
    """A bounded hand-off from the live loop: :meth:`put` is one ``deque.append`` (no lock, never waits, never
    raises); a full or closed queue drops the event and counts it. The arena's thread drains it."""

    def __init__(self, max_items: int = QUEUE_MAX) -> None:
        self.max_items = max_items
        self.queue: deque[tuple[Any, ...]] = deque()
        self.puts = 0
        self.dropped = 0
        self.closed = False

    def put(self, item: tuple[Any, ...]) -> None:
        try:
            if self.closed or len(self.queue) >= self.max_items:
                self.dropped += 1
                return
            self.queue.append(item)
            self.puts += 1
        except Exception:  # noqa: BLE001, S110 - the live loop must never see a practice error
            pass

    def drain(self, max_items: int) -> list[tuple[Any, ...]]:
        out: list[tuple[Any, ...]] = []
        queue = self.queue
        while queue and len(out) < max_items:
            out.append(queue.popleft())
        return out

    def __len__(self) -> int:
        return len(self.queue)


# ---------------------------------------------------------------------- residents
@dataclass(eq=False)
class Resident:
    """A resident's record (saved) and its practice desk (rebuilt from its genes at each start, never saved)."""

    row: dict[str, Any]
    desk: PracticeDesk
    last_eval: float = -math.inf

    @property
    def id(self) -> str:
        return str(self.row["id"])

    @property
    def control(self) -> bool:
        return bool(self.row.get("control"))


def _day(now: float) -> str:
    return datetime.fromtimestamp(now, UTC).date().isoformat()


def _paired(stats: Mapping[str, Any] | None) -> dict[str, Any]:
    """Running paired statistics as the page shows them: windows, mean $ a window against the control, and t."""
    if not isinstance(stats, Mapping):
        return {"n": 0, "mean_usd": None, "t": None}
    n, total, squares = int(stats.get("n") or 0), float(stats.get("sum") or 0.0), float(stats.get("sumsq") or 0.0)
    if n < 1:
        return {"n": 0, "mean_usd": None, "t": None}
    mean = total / n
    t = None
    if n >= 2:
        variance = max(0.0, (squares - n * mean * mean) / (n - 1))
        t = round(mean / math.sqrt(variance / n), 3) if variance > 1e-18 else None
    return {"n": n, "mean_usd": round(mean, 4), "t": t}


def _add(stats: dict[str, Any], value: float) -> None:
    stats["n"] = int(stats.get("n") or 0) + 1
    stats["sum"] = float(stats.get("sum") or 0.0) + value
    stats["sumsq"] = float(stats.get("sumsq") or 0.0) + value * value


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise TypeError("not a finite number")
    return float(value)


def _clean_genes(raw: Any) -> dict[str, Any]:
    """A saved resident's genes, checked; a gene added since it was saved takes its plain default."""
    if not isinstance(raw, Mapping):
        raise TypeError("genes must be a mapping")
    genes: dict[str, Any] = {}
    for name in NUMBERS:
        genes[name] = _number(raw[name]) if name in raw else GENE_DEFAULTS[name]
    for name in SWITCHES:
        value = raw.get(name, GENE_DEFAULTS[name])
        if not isinstance(value, bool):
            raise TypeError("a switch gene must be true or false")
        genes[name] = value
    filters = raw.get("filters", [])
    if not isinstance(filters, list) or not all(isinstance(name, str) for name in filters):
        raise TypeError("filters must be a list of names")
    genes["filters"] = sorted(set(filters))
    speed_config(genes, {"window_usd": 10.0})  # raises on values no desk accepts
    return genes


def _clean_row(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise TypeError("a resident must be a mapping")
    pnl = raw.get("pnl", [])
    if not isinstance(pnl, list) or any(value is not None and not isinstance(value, (int, float)) for value in pnl):
        raise TypeError("pnl must be numbers or nulls")
    row: dict[str, Any] = {
        "id": str(raw["id"]), "name": str(raw["name"])[:24], "control": bool(raw.get("control", False)),
        "gen": int(_number(raw.get("gen", 1))), "parent": None if raw.get("parent") is None else str(raw["parent"]),
        "born": _number(raw["born"]), "genes": _clean_genes(raw["genes"]),
        "equity_usd": _number(raw["equity_usd"]), "rent_paid": _number(raw.get("rent_paid", 0.0)),
        "pnl": [None if value is None else _number(value) for value in pnl][-RECORD_KEEP:],
        "windows": int(_number(raw.get("windows", 0))), "traded": int(_number(raw.get("traded", 0))),
        "wins": int(_number(raw.get("wins", 0))), "losses": int(_number(raw.get("losses", 0))),
        "pnl_usd": _number(raw.get("pnl_usd", 0.0)),
        "paired": {key: _number(value) for key, value in dict(raw.get("paired") or {}).items()
                   if key in ("n", "sum", "sumsq")},
        "verdict": {key: str(value)[:300] for key, value in dict(raw.get("verdict") or {}).items()
                    if key in ("word", "phrase", "reason")},
        "candidate": dict(raw["candidate"]) if isinstance(raw.get("candidate"), Mapping) else None,
        "candidate_now": bool(raw.get("candidate_now", False)),
        "since_flag": ({key: _number(value) for key, value in dict(raw["since_flag"]).items()
                        if key in ("n", "sum", "sumsq")} if isinstance(raw.get("since_flag"), Mapping) else None),
    }
    return row


def _write(path: Path, text: str) -> None:
    """Atomic: a temporary sibling, then a rename. No fsync: a display copy must never compete with the ledgers."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


# ---------------------------------------------------------------------- the town
class KalshiArena:
    """The town's runtime: one daemon thread ("kalshi-arena"). PRACTICE ONLY: no client, no key, no order path.

    The live loop calls only :meth:`feed_book`, :meth:`feed_trade` and :meth:`feed_gap`; :meth:`step` is one pass of
    the town (public for tests); :meth:`start` and :meth:`stop` never block."""

    def __init__(self, config: ArenaConfig, snapshot: Callable[[], MarketView], *,
                 clock: Callable[[], float] = time.time, perf: Callable[[], float] = time.perf_counter,
                 sleep: Callable[[float], None] = time.sleep, poll_s: float = POLL_S) -> None:
        if not 2 <= int(config.population) <= 24:
            raise ValueError("The Kalshi arena holds 2 to 24 residents")
        self.config = config
        self._snapshot = snapshot
        self.clock, self.perf, self._sleep, self.poll_s = clock, perf, sleep, poll_s
        self.directory = Path(config.data_dir) / "kalshi_arena"
        self.path = self.directory / "state.json"
        self.panel_path = self.directory / "panel.json"
        self.feed = ArenaFeed(QUEUE_MAX)
        self.tape = FedTape()
        self.residents: dict[str, Resident] = {}
        self.windows: dict[str, Window] = {}
        self.members: dict[str, set[str]] = {}
        self.settled: deque[str] = deque(maxlen=SETTLED_KEEP)
        self.skipped: deque[str] = deque(maxlen=SETTLED_KEEP)
        self.grave: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.town: dict[str, Any] = {"born": 0, "evicted": 0, "windows": 0, "void_windows": 0, "rent_paid": 0.0,
                                     "candidates": 0, "rent_days": 0}
        self.next_id = 1
        self.seq = 0
        self.rent_day: str | None = None
        self.problem: str | None = None
        self.late = 0
        self.errors = 0
        self.lag_s = 0.0
        self.slices: deque[float] = deque(maxlen=SLICES_KEEP)
        self.busy_s = 0.0
        self.busy_since = perf()
        self.started_at = clock()
        self.saved_at = -math.inf
        self.status_at = clock()
        self.dirty = True
        self.snap: MarketView | None = None
        self._seen_windows: tuple[Window, ...] | None = None
        self._last_pass: float | None = None
        self._feed_status = (False, False)
        self._slice_at = perf()
        self._stop = threading.Event()
        self._outer: threading.Event | None = None
        self._thread: threading.Thread | None = None
        self.control_verdict = ""
        self.control_rule = rule_id(config.control)
        self._load(clock())
        self.rng = random.Random(SEED + self.next_id)
        self._populate(clock())

    # ------------------------------------------------------------------ the live loop's side (O(1), never raises)
    def feed_book(self, book: Book) -> None:
        self.feed.put(("book", book))

    def feed_trade(self, trade: Trade) -> None:
        self.feed.put(("trade", trade))

    def feed_gap(self, gap_windows: tuple[str, ...], trade_stream: bool, coinbase_connected: bool) -> None:
        self.feed.put(("gap", gap_windows, trade_stream, coinbase_connected))

    # ------------------------------------------------------------------ lifecycle
    def start(self, stop: threading.Event | None = None) -> None:
        if self._thread is not None:
            return
        self._outer = stop
        self._thread = threading.Thread(target=self._loop, name="kalshi-arena", daemon=True)
        self._thread.start()
        log.info("kalshi_arena_started population=%d rent_usd=%.2f broke_usd=%.2f control_rule=%s (practice only)",
                 self.config.population, self.config.rent_usd, self.config.broke_usd, self.control_rule)

    def stop(self) -> None:
        """Ask the thread to finish its pass and exit; never waits for it."""
        self._stop.set()

    def _stopping(self) -> bool:
        return self._stop.is_set() or (self._outer is not None and self._outer.is_set())

    def _loop(self) -> None:
        failures = 0
        while not self._stopping():
            try:
                self.step(self.clock())
                failures = 0
            except Exception as exc:  # noqa: BLE001 - a practice town never stops the speed desk
                failures += 1
                self.errors += 1
                log.warning("kalshi_arena_step_failed error=%s", type(exc).__name__)
                if failures >= HALT_AFTER:
                    self._halt(exc)
                    return
            self._stop.wait(self.poll_s)
        try:
            self._save(self.clock())
        except Exception as exc:  # noqa: BLE001 - shutting down; the previous save stands
            log.warning("kalshi_arena_save_failed error=%s", type(exc).__name__)

    def _halt(self, exc: BaseException) -> None:
        self.problem = "Practice town halted after repeated errors; the live desk is unaffected"
        self.feed.closed = True
        self.feed.queue.clear()
        log.error("kalshi_arena_halted error=%s", type(exc).__name__)
        try:
            self._save(self.clock())
        except Exception:  # noqa: BLE001, S110 - the halt is already logged
            pass

    # ------------------------------------------------------------------ the scheduler
    def _yield(self) -> None:
        """End the work slice once it has run SLICE_S: record it and sleep, releasing Python's lock."""
        elapsed = self.perf() - self._slice_at
        if elapsed >= SLICE_S:
            self.slices.append(elapsed)
            self.busy_s += elapsed
            self._sleep(REST_S)
            self._slice_at = self.perf()

    def _end_slice(self) -> None:
        elapsed = self.perf() - self._slice_at
        self.slices.append(elapsed)
        self.busy_s += elapsed

    # ------------------------------------------------------------------ one pass
    def step(self, now: float) -> None:
        self._slice_at = self.perf()
        snap = self._snapshot()
        self.snap = snap
        self._windows(snap, now)
        self.tape.feed(snap.bitcoin_price, snap.bitcoin_at, snap.sigma)
        # Books and prints drained now may be newer than the pass's start: the rest of the pass uses the clock after
        # them, so none looks like it came from the future.
        now = max(self._drain(now), self.clock())
        self._settle(snap, now)
        self._voids(now)
        self._evaluate(snap, now)
        if (self.dirty and now - self.saved_at >= SAVE_SOON_S) or now - self.saved_at >= SAVE_EVERY_S:
            self._save(now)
        if now - self.status_at >= STATUS_EVERY_S:
            self._status(now)
        self._end_slice()

    def _holders(self, slug: str) -> list[Resident]:
        return [self.residents[rid] for rid in self.members.get(slug, ()) if rid in self.residents]

    def _windows(self, snap: MarketView, now: float) -> None:
        if snap.windows is self._seen_windows:
            return
        self._seen_windows = snap.windows
        settled = set(self.settled)
        for index, window in enumerate(snap.windows):
            if index % 64 == 63:
                self._yield()
            slug = window.slug
            if not slug.startswith(SERIES) or window.venue != "kalshi" or slug in settled:
                continue
            known = self.windows.get(slug)
            if known is None:
                if window.end <= now or slug in self.skipped:
                    continue
                if window.start < self.started_at:
                    # The town (re)started inside this window: its desks are fresh, so it is void for everyone.
                    self.skipped.append(slug)
                    self.town["void_windows"] += 1
                    continue
                self.windows[slug] = replace(window)
                self.members[slug] = set()
                for res in self.residents.values():
                    if float(res.row["born"]) <= window.start:
                        res.desk.add_window(replace(window))
                        self.members[slug].add(res.id)
                self._yield()
            elif known != window:
                changed = any(getattr(known, key) != getattr(window, key) for key in TERMS)
                for res in self._holders(slug):
                    if changed:  # the speed desk's own rule (SpeedRunner.on_windows)
                        res.desk.cancel(now, slug, "venue_terms_changed")
                        res.desk.books = {key: book for key, book in res.desk.books.items() if key[0] != slug}
                    res.desk.add_window(replace(window))
                self.windows[slug] = replace(window)
                self._yield()

    def _drain(self, now: float) -> float:
        """Apply queued books, prints and gaps in arrival order, each at the time it is read; returns that time."""
        lag = 0.0
        for item in self.feed.drain(DRAIN_MAX):
            now = max(now, self.clock())
            kind = item[0]
            if kind == "book":
                book: Book = item[1]
                lag = max(lag, now - book.at)
                for res in self._holders(book.window):
                    if res.desk.on_book(book):
                        res.desk.advance(now)
            elif kind == "trade":
                trade: Trade = item[1]
                if now - trade.at > TRADE_LATE_S:
                    self.late += 1
                for res in self._holders(trade.window):
                    res.desk.on_trade(trade, now)
            elif kind == "gap":
                self._gap(item[1], bool(item[2]), bool(item[3]), now)
            self._yield()
        self.lag_s = max(0.0, lag)
        return now

    def _gap(self, gap_windows: Sequence[str], trade_stream: bool, coinbase: bool, now: float) -> None:
        """The speed desk's own feed-gap rule (SpeedRunner.on_status): a lost stream cancels everything."""
        old_stream, old_coinbase = self._feed_status
        self._feed_status = (trade_stream, coinbase)
        if (old_stream and not trade_stream) or (old_coinbase and not coinbase):
            for res in self.residents.values():
                res.desk.cancel(now, reason="feed_gap")
                res.desk.books.clear()
            return
        for slug in gap_windows:
            for res in self._holders(slug):
                res.desk.cancel(now, slug, "venue_feed_gap")
                res.desk.books = {key: book for key, book in res.desk.books.items() if key[0] != slug}

    def _evaluate(self, snap: MarketView, now: float) -> None:
        """Each resident decides about every EVAL_S, the longest-waiting first, and a pass takes only its share
        (the residents fall out of step, so no pass carries all twelve); a slow pass means less often, never a
        longer slice."""
        makers = set(snap.maker_windows)
        elapsed = EVAL_S if self._last_pass is None else max(0.0, now - self._last_pass)
        self._last_pass = now
        share = max(1, math.ceil(len(self.residents) * elapsed / EVAL_S))
        due = sorted((res for res in self.residents.values() if now - res.last_eval >= EVAL_S),
                     key=lambda res: res.last_eval)
        for res in due[:share]:
            res.last_eval = now
            res.desk.evaluate(now, makers_enabled=bool(makers), maker_windows=makers)
            self._yield()

    def _forget_window(self, slug: str) -> None:
        self.windows.pop(slug, None)
        self.members.pop(slug, None)
        self.settled.append(slug)

    def _voids(self, now: float) -> None:
        for slug, window in list(self.windows.items()):
            if now - window.end <= VOID_AFTER_S:
                continue
            for res in self._holders(slug):
                res.desk.cancel(now, slug, "void")
                res.desk.forget(slug, void=True)
            self._forget_window(slug)
            self.town["void_windows"] += 1
            self._event(now, "Town", f"Window {slug[-12:]} never settled: void for everyone (no record, no money).",
                        "neutral", "void")
            self.dirty = True

    # ------------------------------------------------------------------ settlement and the town's rules
    def _settle(self, snap: MarketView, now: float) -> None:
        for slug in [slug for slug in self.windows if slug in snap.outcomes]:
            window = self.windows[slug]
            if now < window.end:
                continue
            up_wins = bool(snap.outcomes[slug])
            results: dict[str, float | None] = {}
            for res in self._holders(slug):
                if slug not in res.desk.windows:
                    continue  # never expected; one resident's gap must not stop the town's settlement
                res.desk.cancel(now, slug, "settled")
                result = res.desk.settle(slug, up_wins, now)
                res.desk.forget(slug)
                if result is not None:
                    traded = result.up_shares + result.down_shares > 0
                    results[res.id] = round(result.pnl_usd, 4) if traded else None
                self._yield()
            self._forget_window(slug)
            self._after_window(window, results, now)

    def _after_window(self, window: Window, results: Mapping[str, float | None], now: float) -> None:
        """Book one settled window for every resident that held it, then rent, evictions, births and flags."""
        self.town["windows"] += 1
        self.seq += 1
        control = self._control()
        # The control holds every window a challenger can be compared on (it is never evicted).
        benchmark = control is not None and control.id in results
        control_pnl = (results.get(control.id) or 0.0) if control is not None else 0.0
        for rid, pnl in results.items():
            res = self.residents.get(rid)
            if res is None:
                continue
            row = res.row
            row["pnl"].append(pnl)
            del row["pnl"][:-RECORD_KEEP]
            row["windows"] += 1
            if pnl is not None:
                row["traded"] += 1
                row["wins"] += int(pnl > 0)
                row["losses"] += int(pnl < 0)
                row["pnl_usd"] = round(float(row["pnl_usd"]) + pnl, 6)
                row["equity_usd"] = round(float(row["equity_usd"]) + pnl, 6)
            if not res.control and benchmark:
                difference = (pnl or 0.0) - control_pnl  # a skipped losing window is part of an edge
                _add(row["paired"], difference)
                if row["since_flag"] is not None:
                    _add(row["since_flag"], difference)
        self._rent(window, now)
        for rid in results:
            res = self.residents.get(rid)
            if res is not None:
                self._judge(res, now)
                self._yield()
        for res in list(self.residents.values()):
            if res.control:
                continue
            why = ""
            if float(res.row["equity_usd"]) < self.config.broke_usd:
                why = "went broke"
            elif res.row["verdict"].get("word") == LOSING:
                why = "losing: " + str(res.row["verdict"].get("reason", ""))[:120]
            if why:
                self._evict(res, why, now)
        self._births(now)
        for rid in results:
            res = self.residents.get(rid)
            if res is not None and not res.control:
                self._candidate(res, now)
        self.dirty = True

    def _rent(self, window: Window, now: float) -> None:
        """The first window settled on a new UTC day charges every resident the rent (none on the town's first day);
        a challenger that cannot pay it is evicted instead."""
        day = _day(window.end)
        if self.rent_day is None:
            self.rent_day = day
            return
        if day <= self.rent_day:
            return
        self.rent_day = day
        rent = self.config.rent_usd
        paid = 0
        for res in list(self.residents.values()):
            if not res.control and float(res.row["equity_usd"]) < rent:
                self._evict(res, "could not pay the rent", now)
                continue
            res.row["equity_usd"] = round(float(res.row["equity_usd"]) - rent, 6)
            res.row["rent_paid"] = round(float(res.row["rent_paid"]) + rent, 6)
            self.town["rent_paid"] = round(float(self.town["rent_paid"]) + rent, 6)
            paid += 1
        self.town["rent_days"] += 1
        if paid:
            self._event(now, "Town", f"Rent day {day}: {paid} residents paid ${rent:.2f} each (practice).", "neutral",
                        "rent")

    def _judge(self, res: Resident, now: float) -> None:
        traded = [value for value in res.row["pnl"] if value is not None]
        verdict = judge(traded)
        reason = verdict.reason + (f" (of the last {RECORD_KEEP} windows)" if res.row["windows"] > RECORD_KEEP else "")
        res.row["verdict"] = {"word": verdict.verdict, "phrase": PHRASES[verdict.verdict], "reason": reason[:300]}
        if res.control and verdict.verdict != self.control_verdict:
            if verdict.verdict == LOSING or self.control_verdict == LOSING:
                log.info('kalshi_arena_control verdict=%s reason="%s" (practice; live unchanged)', verdict.verdict,
                         reason[:160])
                words = ("The live rules lose in practice" if verdict.verdict == LOSING
                         else f"The live rules are now {PHRASES[verdict.verdict]} in practice")
                self._event(now, res.row["name"], f"{words}: {reason[:110]} (live unchanged).",
                            "bad" if verdict.verdict == LOSING else "neutral", "control")
            self.control_verdict = verdict.verdict

    def _candidate(self, res: Resident, now: float) -> None:
        row = res.row
        paired = _paired(row["paired"])
        t = paired["t"]
        holds = (row["verdict"].get("word") == WINNING and paired["n"] >= CANDIDATE_WINDOWS
                 and t is not None and t >= CANDIDATE_T)
        row["candidate_now"] = holds
        if not holds or row["candidate"] is not None:
            return
        row["candidate"] = {"at": now, "n": paired["n"], "t": t, "mean_usd": paired["mean_usd"],
                            "verdict_reason": str(row["verdict"].get("reason", ""))[:300],
                            "adopt": adoptable(row["genes"], float(self.config.fixed.get("clip", 5.0)))}
        row["since_flag"] = {"n": 0, "sum": 0.0, "sumsq": 0.0}
        self.town["candidates"] += 1
        log.info("kalshi_arena_candidate resident=%s windows=%d paired_n=%d paired_t=%.2f vs_control_usd=%+.3f "
                 "(practice only; nothing changed live)", row["name"], row["traded"], paired["n"], t,
                 paired["mean_usd"] or 0.0)
        self._event(now, row["name"], f"{row['name']} is a CANDIDATE: winning on {row['traded']} windows and "
                    f"{paired['mean_usd'] or 0:+.3f} $ a window ahead of the live rules (t {t:.2f}). A lead for a "
                    "pre-registered test, not proof.", "good", "candidate")

    def _evict(self, res: Resident, why: str, now: float) -> None:
        row = res.row
        self.residents.pop(res.id, None)
        for members in self.members.values():
            members.discard(res.id)
        days = max(0.0, (now - float(row["born"])) / 86_400.0)
        verdict = row.get("verdict") or {}
        self.grave.insert(0, {
            "id": row["id"], "name": row["name"], "gen": row["gen"], "parent": row["parent"], "born": row["born"],
            "died": now, "days": round(days, 2), "windows": row["windows"], "traded": row["traded"],
            "pnl_usd": round(float(row["pnl_usd"]), 4), "equity_usd": round(float(row["equity_usd"]), 4),
            "rent_paid": round(float(row["rent_paid"]), 4), "why": why[:160], "verdict": verdict.get("word"),
            "genes": row["genes"], "style": style(row["genes"]), "vs_control": _paired(row["paired"])})
        del self.grave[GRAVE_KEEP:]
        self.town["evicted"] += 1
        self.dirty = True
        log.info("kalshi_arena_evicted resident=%s why=%s windows=%d pnl_usd=%.2f equity_usd=%.2f days=%.1f",
                 row["name"], why.split(":")[0].replace(" ", "_"), row["traded"], float(row["pnl_usd"]),
                 float(row["equity_usd"]), days)
        self._event(now, row["name"], f"{row['name']} was evicted: {why[:90]} after {days:.1f} days "
                    f"({row['traded']} windows traded, {float(row['pnl_usd']):+.2f} $).", "bad", "evicted")

    def _control(self) -> Resident | None:
        return next((res for res in self.residents.values() if res.control), None)

    # ------------------------------------------------------------------ births
    def _desk(self, genes: Mapping[str, Any]) -> PracticeDesk:
        desk = PracticeDesk(speed_config(genes, self.config.fixed))
        desk.tape = self.tape
        names = [str(name) for name in genes.get("filters") or []]
        if names:
            desk.starter_gate = self._gate(names)
        return desk

    def _gate(self, names: list[str]) -> Callable[[Window, float], str]:
        def gate(window: Window, now: float) -> str:
            snap = self.snap
            for name in names:
                check = FILTERS.get(name)
                if check is None or snap is None:
                    return "filter_missing"
                try:
                    if not check(window, now, snap):
                        return f"filter_{name}"[:40]
                except Exception:  # noqa: BLE001 - a broken filter only blocks that resident's starter
                    return "filter_error"
            return ""
        return gate

    def _new_resident(self, genes: dict[str, Any], now: float, *, parent: Resident | None = None,
                      control: bool = False) -> Resident:
        rid = self.next_id
        self.next_id += 1
        name = "Live" if control else f"{NAMES[(rid - 1) % len(NAMES)]}-{rid}"
        row = {"id": str(rid), "name": name, "control": control, "gen": int(parent.row["gen"]) + 1 if parent else 1,
               "parent": parent.id if parent else None, "born": now, "genes": genes,
               "equity_usd": float(self.config.start_cash), "rent_paid": 0.0, "pnl": [], "windows": 0, "traded": 0,
               "wins": 0, "losses": 0, "pnl_usd": 0.0, "paired": {"n": 0, "sum": 0.0, "sumsq": 0.0},
               "verdict": {"word": "learning", "phrase": PHRASES["learning"], "reason": ""}, "candidate": None,
               "candidate_now": False, "since_flag": None}
        res = Resident(row, self._desk(genes))
        self.residents[res.id] = res
        # A newborn joins the next window: every known window that has not started yet.
        for slug, window in self.windows.items():
            if window.start >= now:
                res.desk.add_window(replace(window))
                self.members.setdefault(slug, set()).add(res.id)
        self.town["born"] += 1
        self.dirty = True
        who = f" a child of {parent.row['name']}" if parent else (" the control: the live rules" if control else
                                                                  " a newcomer")
        log.info('kalshi_arena_born resident=%s parent=%s gen=%d style="%s"', name,
                 parent.row["name"] if parent else "-", row["gen"], style(genes))
        self._event(now, name, f"{name} moved in,{who}: {style(genes)}.", "good", "born")
        return res

    def _populate(self, now: float) -> None:
        """The first town (the control, children of the control for a local search, newcomers for a global one),
        then any empty home; a population that fell on restart sends the poorest challengers away."""
        if self._control() is None:
            self._new_resident(dict(self.config.control), now, control=True)
            if len(self.residents) == 1:
                control = self._control()
                for _ in range((self.config.population - 1) // 2):
                    self._new_resident(child_genes(self.config.control, self.rng), now, parent=control)
                while len(self.residents) < self.config.population:
                    self._new_resident(random_genes(self.rng), now)
        while len(self.residents) > self.config.population:
            poorest = min((res for res in self.residents.values() if not res.control),
                          key=lambda res: float(res.row["equity_usd"]))
            self._evict(poorest, "the town shrank", now)
        self._births(now)

    def _births(self, now: float) -> None:
        while len(self.residents) < self.config.population:
            ranked = sorted(self.residents.values(), key=lambda res: -float(res.row["equity_usd"]))
            parents = ranked[:max(1, len(ranked) // 2)]
            parent = parents[min(len(parents) - 1, int(self.rng.random() ** 2 * len(parents)))]
            self._new_resident(child_genes(parent.row["genes"], self.rng), now, parent=parent)

    # ------------------------------------------------------------------ the story, the panel and the files
    def _event(self, now: float, who: str, text: str, tone: str, kind: str) -> None:
        self.events.insert(0, {"ts": now, "who": who[:24], "text": text[:160], "tone": tone, "kind": kind})
        del self.events[EVENTS_KEEP:]

    def telemetry(self, now: float) -> dict[str, Any]:
        """The feed and the scheduler since the last status line: queue, drops, slice times, duty."""
        slices = sorted(self.slices)
        elapsed = max(1e-9, self.perf() - self.busy_since)

        def ms(q: float) -> float | None:
            return round(slices[min(len(slices) - 1, int(q * len(slices)))] * 1000, 3) if slices else None

        return {"queue": len(self.feed), "put": self.feed.puts, "dropped": self.feed.dropped, "late": self.late,
                "slice_p50_ms": ms(0.5), "slice_p99_ms": ms(0.99), "slice_max_ms": ms(1.0),
                "duty_pct": round(100 * self.busy_s / elapsed, 2), "lag_s": round(self.lag_s, 3),
                "errors": self.errors}

    def _resident_row(self, res: Resident, now: float) -> dict[str, Any]:
        row = res.row
        return {"id": row["id"], "name": row["name"], "control": res.control, "gen": row["gen"],
                "parent": row["parent"], "days": round(max(0.0, now - float(row["born"])) / 86_400.0, 2),
                "equity_usd": round(float(row["equity_usd"]), 2),
                "profit_usd": round(float(row["equity_usd"]) - float(self.config.start_cash), 2),
                "windows": row["windows"], "traded": row["traded"], "wins": row["wins"], "losses": row["losses"],
                "verdict": row["verdict"].get("word"), "phrase": row["verdict"].get("phrase"),
                "style": style(row["genes"]), "vs_control": None if res.control else _paired(row["paired"]),
                "candidate": row["candidate"] is not None, "candidate_now": bool(row["candidate_now"])}

    def panel(self, now: float) -> dict[str, Any]:
        """The page's compact view (``money.kalshi_arena``), built a row per slice."""
        rows = []
        for res in self.residents.values():
            rows.append(self._resident_row(res, now))
            self._yield()
        rows.sort(key=lambda row: -row["equity_usd"])
        feed = self.telemetry(now)
        self._yield()
        control = self._control()
        candidates = []
        for res in self.residents.values():
            flag = res.row["candidate"]
            if flag is not None:
                candidates.append({"name": res.row["name"], "at": flag.get("at"), "n": flag.get("n"),
                                   "t": flag.get("t"), "mean_usd": flag.get("mean_usd"),
                                   "since_flag": _paired(res.row["since_flag"]), "adopt": flag.get("adopt"),
                                   "candidate_now": bool(res.row["candidate_now"]),
                                   "note": "A lead for a pre-registered test, not proof."})
        candidates.sort(key=lambda row: -(row["t"] or 0))
        return {"label": LABEL, "as_of": now, "problem": self.problem, "population": len(self.residents),
                "rent_usd": self.config.rent_usd, "broke_usd": self.config.broke_usd,
                "start_cash": self.config.start_cash, "note": NOTE,
                "control": None if control is None else {
                    "name": control.row["name"], "equity_usd": round(float(control.row["equity_usd"]), 2),
                    "windows": control.row["windows"], "traded": control.row["traded"],
                    "pnl_usd": round(float(control.row["pnl_usd"]), 2), "verdict": control.row["verdict"].get("word"),
                    "phrase": control.row["verdict"].get("phrase"),
                    "reason": control.row["verdict"].get("reason", ""), "genes_line": style(control.row["genes"])},
                "residents": rows[:24], "candidates": candidates[:5],
                "grave": [{key: value for key, value in row.items() if key != "genes"} for row in self.grave[:5]],
                "events": self.events[:24], "town": dict(self.town), "feed": feed}

    def state(self, now: float) -> dict[str, Any]:
        return {"version": STATE_VERSION, "label": LABEL, "saved_at": now, "started_at": self.started_at,
                "settings": {"population": self.config.population, "rent_usd": self.config.rent_usd,
                             "broke_usd": self.config.broke_usd, "start_cash": self.config.start_cash},
                "control_rule": self.control_rule, "next_id": self.next_id, "seq": self.seq,
                "rent_day": self.rent_day, "active_windows": sorted(self.windows),
                "residents": [res.row for res in self.residents.values()], "grave": self.grave,
                "events": self.events, "town": self.town,
                "feed": {"put": self.feed.puts, "dropped": self.feed.dropped, "late": self.late,
                         "errors": self.errors}, "problem": self.problem}

    def _save(self, now: float) -> None:
        """state.json, then panel.json. The long lists are serialized one row at a time, each in its own slice, so
        no single ``json.dumps`` holds Python's lock for long."""
        self.directory.mkdir(parents=True, exist_ok=True)
        state = self.state(now)
        lists = {key: state.pop(key) for key in ("residents", "grave", "events")}
        text = json.dumps(state, allow_nan=False, separators=(",", ":"))[:-1]
        for key, rows in lists.items():
            parts = []
            for row in rows:
                parts.append(json.dumps(row, allow_nan=False, separators=(",", ":")))
                self._yield()
            text += f',"{key}":[' + ",".join(parts) + "]"
        _write(self.path, text + "}")
        self._yield()
        panel = self.panel(now)
        self._yield()
        text = json.dumps(panel, allow_nan=False, separators=(",", ":"))
        self._yield()
        _write(self.panel_path, text)
        self.saved_at = now
        self.dirty = False

    def _status(self, now: float) -> None:
        self.status_at = now
        feed = self.telemetry(now)
        log.info("kalshi_arena_status residents=%d windows=%d void=%d queue=%d dropped=%d late=%d slice_p99_ms=%s "
                 "slice_max_ms=%s duty_pct=%.2f lag_s=%.2f errors=%d", len(self.residents), self.town["windows"],
                 self.town["void_windows"], feed["queue"], feed["dropped"], feed["late"], feed["slice_p99_ms"],
                 feed["slice_max_ms"], feed["duty_pct"], feed["lag_s"], feed["errors"])
        self.slices.clear()
        self.busy_s, self.busy_since = 0.0, self.perf()

    def _load(self, now: float) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            self._reset(exc)
            return
        try:
            self._restore(raw, now)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            self.residents.clear()
            self.grave, self.events, self.next_id, self.seq, self.rent_day = [], [], 1, 0, None
            self.town = {key: 0.0 if key == "rent_paid" else 0 for key in self.town}
            self._reset(exc)

    def _reset(self, exc: BaseException) -> None:
        """A bad file moves aside (kept for a person to read) and the town starts fresh."""
        log.warning("kalshi_arena_state_reset error=%s", type(exc).__name__)
        try:
            os.replace(self.path, self.path.with_name(f"state.json.bad-{int(time.time())}"))
        except OSError:
            pass

    def _restore(self, raw: Any, now: float) -> None:
        if not isinstance(raw, Mapping) or raw.get("version") != STATE_VERSION:
            raise ValueError("unsupported Kalshi arena state")
        rows = [_clean_row(item) for item in raw["residents"]]
        if sum(row["control"] for row in rows) > 1 or len({row["id"] for row in rows}) != len(rows):
            raise ValueError("one control and unique residents")
        self.next_id = max([int(_number(raw["next_id"]))] + [int(row["id"]) + 1 for row in rows if row["id"].isdigit()])
        self.seq = int(_number(raw.get("seq", 0)))
        rent_day = raw.get("rent_day")
        self.rent_day = rent_day if isinstance(rent_day, str) and len(rent_day) == 10 else None
        town = raw.get("town") or {}
        for key in self.town:
            if key in town:
                self.town[key] = _number(town[key]) if key == "rent_paid" else int(_number(town[key]))
        self.grave = [dict(item) for item in raw.get("grave") or [] if isinstance(item, Mapping)][:GRAVE_KEEP]
        self.events = [dict(item) for item in raw.get("events") or [] if isinstance(item, Mapping)][:EVENTS_KEEP]
        saved_rule = raw.get("control_rule")
        for row in rows:
            if row["control"] and saved_rule != self.control_rule:
                # The live rules changed: the benchmark's record and every comparison with it start again.
                log.info("kalshi_arena_control_changed old=%s new=%s", saved_rule, self.control_rule)
                row.update(genes=dict(self.config.control), pnl=[], windows=0, traded=0, wins=0, losses=0,
                           pnl_usd=0.0, equity_usd=float(self.config.start_cash), rent_paid=0.0, born=now,
                           verdict={"word": "learning", "phrase": PHRASES["learning"], "reason": ""})
                for other in rows:
                    other["paired"] = {"n": 0, "sum": 0.0, "sumsq": 0.0}
                    if other["since_flag"] is not None:
                        other["since_flag"] = {"n": 0, "sum": 0.0, "sumsq": 0.0}
                self._event(now, row["name"], f"The live rules changed ({saved_rule} -> {self.control_rule}): the "
                            "control's record and every comparison start again.", "neutral", "control")
            elif row["control"]:
                row["genes"] = dict(self.config.control)
        for row in rows:
            self.residents[row["id"]] = Resident(row, self._desk(row["genes"]))
        control = self._control()
        if control is not None:
            self.control_verdict = str(control.row["verdict"].get("word", ""))
        active = raw.get("active_windows") or []
        # A window open at the last save was open across the restart: void for everyone (fresh desks, equal for all).
        self.skipped.extend(str(slug) for slug in active if isinstance(slug, str))
        self.town["void_windows"] += sum(isinstance(slug, str) for slug in active)


# ---------------------------------------------------------------------- the panel
def panel_state(data_dir: Path | str, now: float) -> dict[str, Any]:
    """What the page shows (``money.kalshi_arena``), from ``panel.json`` only (never the larger state file)."""
    raw = json.loads((Path(data_dir) / "kalshi_arena" / "panel.json").read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("label") != LABEL:
        raise ValueError("Invalid Kalshi arena panel")
    return raw
