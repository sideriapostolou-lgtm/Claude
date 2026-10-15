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
  ``LiveLimits``' own clamps, plus the live risk book's stops, order expiry and fee check: :func:`fixed_config`). It
  is never evicted and every comparison is against it, window by window.
* Rent: the first window settled on a new UTC day charges every resident :data:`RENT_USD` for each day since the last
  rent, about the whole Railway bill ($5 a month) EACH, so every resident must earn the town's cost on its own. A
  resident that cannot pay is EVICTED; so is one whose money falls under :data:`BROKE_USD` (it could not fund a window
  at the live $10), and one that :func:`nightcrawler.deskguard.judge` calls ``losing`` on its traded windows. The
  graveyard keeps the record.
* Births: every empty home goes at once to a child of one of the richest residents with a record (the top half by
  money of those with :data:`PARENT_MIN_TRADED` traded windows, control always included, the richer more often):
  each number nudged by up to :data:`MUTATE` of its range, sometimes redrawn.
* CANDIDATE: a challenger whose traded record ``judge`` calls ``winning`` (100 or more windows) AND whose paired
  per-window difference against the control on the same windows has t >= :data:`CANDIDATE_T` over at least
  :data:`CANDIDATE_WINDOWS` windows. It is SHOWN to the owner, a lead for a pre-registered test and not proof: many
  challengers watched after every window will throw up lucky ones. Nothing here changes a live setting.

PRACTICE ONLY. This module holds no client, no key, no Settings object after :func:`arena_config`, and no order path:
its residents trade pretend money against the same public books and prints the live desk sees, each filling on its
own (no resident competes with another or with the real desk). It writes ``DATA_DIR/kalshi_arena/state.json`` and a
small ``panel.json`` for the page.

SPEED: THE TOWN RUNS IN ITS OWN PROCESS. The live desk's event loop is latency-critical, and a thread would share
Python's lock (and its garbage collector) with it: a busy or stuck town could delay every live decision. So the live
loop only holds an :class:`ArenaLink`: each Kalshi book and print is one bounded FIFO append; once per runner
step (every 50 ms) :meth:`ArenaLink.flush` encodes a time-bounded slice plus the market facts that changed (windows,
price, sigma, maker windows, outcomes) into ONE frame and hands it to a non-blocking socket. A full socket leaves
the frame and following events queued, never waits, and never replaces a book with a later book. Queue overflow
is counted; the affected windows are void, as are events read more than 3 s late. The town
(:class:`KalshiArena`) runs in a child Python process started with
an empty environment (no ``KALSHI_*`` key ever reaches it), at the lowest CPU priority, first in line for the
out-of-memory killer, under a memory limit, without core dumps, and killed by the kernel if one pass hangs for
:data:`HANG_S` or spends :data:`PASS_CPU_S` of CPU (it logs what of this took effect: :func:`report_hardening`). It
reads the frames, and a window whose feed was incomplete (frames dropped, or events older than the desks' 3 s freshness
when read) is void for every resident. The child exits when the pipe closes (the live desk stopped or died), after a
final save. A child that dies is logged (``kalshi_arena_exited``); the live desk never notices.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import logging
import marshal
import math
import os
import random
import signal
import socket
import struct
import subprocess
import sys
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, fields, replace
from datetime import UTC, date, datetime
from itertools import compress, count
from operator import is_not
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from .deskguard import LOSING, PHRASES, WINNING, judge
from .kalshi_online_learning import OnlineLearning
from .speeddesk_model import (
    BitcoinTape,
    Book,
    Level,
    PracticeDesk,
    Side,
    SpeedConfig,
    Trade,
    Window,
)

if TYPE_CHECKING:
    from .config import Settings
    from .speeddesk_live_model import LiveLimits

log = logging.getLogger("nightcrawler.kalshi_arena")

STATE_VERSION = 1
LABEL = "Practice (pretend money)"
SERIES = "KXBTC15M-"
START_CASH = 50.0  # the real Kalshi account's size, as the owner gave it on 2026-10-13
RENT_USD = 0.20  # per resident per UTC day: Railway's ~$5 a month (~$0.17 a day) for the whole service, plus 20 %
RENT_CATCHUP_DAYS = 7  # a town that was down for days pays each missed day's rent, at most this many at once
BROKE_USD = 10.0  # under this a resident cannot fund one window at the live $10 budget: evicted
POPULATION = 12  # the control is one of them
RECORD_KEEP = 960  # windows of record per resident (10 days); the verdict reads them
GRAVE_KEEP = 40
EVENTS_KEEP = 60
EVENT_TEXT = 160  # characters in one line of the town's story
CANDIDATE_WINDOWS = 100  # paired windows against the control before a challenger can be a candidate
CANDIDATE_T = 2.0
MUTATE = 0.12  # a child's number moves by up to this share of its range
NEW_VALUE_P = 0.1  # ... or is redrawn anywhere in its range this often
FLIP_P = 0.1  # a child's switch (and each registered filter) flips this often
PARENT_MIN_TRADED = 20  # traded windows before a challenger can be a parent (a newborn's $50 is not a record)
SEED = 20261013
# The town's own process (module docstring, SPEED).
POLL_S = 0.1  # a pass of the town
EVAL_S = 0.25  # each resident decides at most this often (the live desk's IDLE_STEP_S)
LATE_S = 3.0  # an event read later than this after it arrived (the desks' stale_s) leaves its window incomplete
SEEN_PRINTS = 20_000  # prints the town remembers for de-duplication, once for all residents
RESIDENT_TRADE_MEMORY = 256  # ... so each resident's own memory stays small
PASSES_KEEP = 2048  # recent pass CPU times for the status line
VOID_AFTER_S = 7200.0  # a window with no outcome this long after its close is void for everyone
SAVE_EVERY_S = 60.0
SAVE_SOON_S = 10.0  # after a birth, an eviction or a flag, a save at most this soon
STATUS_EVERY_S = 300.0
STATUS_TROUBLE_S = 60.0  # ... every minute while the feed lags or drops
HALT_AFTER = 5  # failed passes in a row before the town halts itself (the process exits)
HANG_S = 120  # a pass (or a read) that takes longer than this is killed by the kernel (SIGALRM, no handler)
# ... and one that spends this much CPU (user time, ITIMER_VIRTUAL: SIGVTALRM, no handler): a spinning pass dies after
# 5 s of CPU, never two minutes of a core; a town merely starved of CPU (its idle class) spends none and lives on.
PASS_CPU_S = 5.0
MEMORY_BYTES = 1 << 30  # the town's address-space limit: a runaway town fails alone
SETTLED_KEEP = 200  # settled windows remembered, so none is ever added again
FRAME_MAX = 64 << 20  # a frame larger than this is a broken stream
EXIT_HALTED = 3
EXIT_BUSY = 4  # another town already holds DATA_DIR/kalshi_arena/town.lock
LOCK_WAIT_S = 5.0  # ... after waiting this long for it (an old town's final save)
# The panel (panel.json; pagestate.kalshi_arena_block whitelists it into the page's top-level ``kalshi_arena``).
PANEL_SCHEMA = 1  # bumped on a change an old reader would misread
PANEL_RESIDENTS = 24  # every resident (a town holds at most 24)
PANEL_GRAVE = 5  # of the GRAVE_KEEP kept; ``counts.grave`` is every eviction
PANEL_CANDIDATES = 5
PANEL_EVENTS = 24  # of the EVENTS_KEEP kept; ``counts.events`` is every event this town recorded
PANEL_MAX_BYTES = 256 << 10  # a panel is about 20-30 KiB; the page refuses a larger file before reading it
FILL = "speeddesk_fill"  # the practice desk's fill decision
# The live loop's side (ArenaLink).
PENDING_MAX = 16_384  # bounded burst buffer; every book/print keeps its place (late events still void a window)
FLUSH_MAX = 1024  # absolute event limit as well as the encoding time budget below
FLUSH_BUDGET_NS = 4_000_000  # own-thread CPU, not wall time; deep books must drain even when steps are delayed
# A saturated flush may cost several milliseconds plus marshal/send. The prior 400 us wall budget could not keep
# up with production's 111/168-level books at roughly 3-4 flushes/s; a GIL pause also exhausted that wall budget.
FLUSH_CHUNK = 16  # check the encoding budget every small chunk, never after an entire backlog
SEND_BYTES = 1 << 20  # the socket's send buffer (best effort; Linux caps it at net.core.wmem_max)
READ_MAX = 8 << 20  # the town reads at most this much before a pass
CHECK_S = 5.0  # how often the live loop asks whether the town's process still runs (one waitpid)
RECENT_S = VOID_AFTER_S + 900.0  # windows that closed longer ago than this are never sent (the town voided them)
LINK_STATUS_S = 300.0
EXIT_WAIT_S = 1.0  # at shutdown, after the live companion stopped: time for the town's final save
TERMS = ("taker_coefficient", "maker_coefficient", "tick_size", "min_trade_qty", "fee_rounding")
# The control (and every resident) runs the CONFIGURED live limits, which are the earned-growth ladder's rung 0: the
# town reads Settings once and never the ladder (speeddesk_live_ladder), so after a live promotion live trades a bigger
# window than the town. The page says so (the note, at most pagestate's 400 characters).
NOTE = ("Practice town: every resident fills on its own against the same live Kalshi prints; the control runs the live "
        "rules as the practice model simulates them, at the configured limits (the live ladder's rung 0; it does not "
        "follow a promotion), so the comparison is against it. A candidate is a lead for a pre-registered test, not "
        "proof; real money changes only on the owner's word.")
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
    "lock_max": Gene(0.90, 0.99, 0.01, "most a lock pays per contract"),
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
#: (takes off, 5-contract clip, $10 a window, $20 open, $6 day stop, a direct account's $0.0001 fee grid) and the
#: live risk book's ways of applying them (the stops count money at risk, a resting bid expires after 30 s, the edge
#: survives the rounded fee reserve).
DEFAULT_FIXED: dict[str, Any] = {"take_edge": 1.0, "clip": 5.0, "window_usd": 10.0, "open_usd": 20.0,
                                 "day_stop_usd": 6.0, "latency_ms": 250.0, "whole_contracts": True,
                                 "day_stop_counts_risk": True, "hedged_open_budget": True, "rest_ttl_s": 30.0,
                                 "edge_fee_precision": 0.0001}
#: How long a live resting bid lives (``speeddesk_live._submit``: ``expiration_ts = int(now) + 30``).
LIVE_REST_TTL_S = 30.0


class MarketView(Protocol):
    """What the arena reads about the market: the speed desk's published facts, as the link sends them."""

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
    """The live companion's limits from the deployed settings, with LiveLimits' own clamps (speeddesk_live). Only
    the live process calls this (arena_config), so the town's own process never imports a speeddesk_live module."""
    from .speeddesk_live_model import LiveLimits

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
    """What every resident shares with the live desk (SpeedConfig fields): takes, the clip, budgets, latency, and the
    live risk book's way of applying them: the day stop and open budget count money at risk
    (``LiveRiskBook.can_buy``), a resting bid expires after 30 s, and the edge must survive the fee reserve rounded to
    the account's grid (``speeddesk_live._send``; an account not attested ``direct`` reserves a whole cent per
    .01-contract fill, so live, and with it the whole town, then sends nothing). Live's lifetime total stop is not
    copied: it halts the account until the owner resumes it, and a benchmark frozen that way would compare nothing."""
    limits = _limits(settings)
    direct = settings.speeddesk_kalshi_account_type == "direct"
    return {"take_edge": float(settings.speeddesk_take_edge), "clip": float(math.floor(limits.clip + 1e-9)),
            "window_usd": limits.window_usd, "open_usd": limits.open_usd, "day_stop_usd": limits.day_loss_usd,
            "latency_ms": float(settings.speeddesk_latency_ms), "whole_contracts": True,
            "day_stop_counts_risk": True, "hedged_open_budget": True, "rest_ttl_s": LIVE_REST_TTL_S,
            "edge_fee_precision": 0.0001 if direct else 0.01}


def speed_config(genes: Mapping[str, Any], fixed: Mapping[str, Any]) -> SpeedConfig:
    """A resident's practice desk. Like live, the first buy is also held to whole pairs at the pair cap."""
    pair_cap = float(genes["pair_cap"])
    if not 0 < pair_cap <= 1:
        raise ValueError("Invalid pair cap")
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
    """Twelve hex characters that change whenever any gene (or shared limit) changes."""
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


def config_wire(config: ArenaConfig) -> dict[str, Any]:
    """The configuration as the child process receives it: plain numbers, names and a path."""
    return {"data_dir": str(config.data_dir), "population": int(config.population),
            "rent_usd": float(config.rent_usd), "broke_usd": float(config.broke_usd),
            "start_cash": float(config.start_cash), "control": dict(config.control), "fixed": dict(config.fixed)}


def config_from_wire(raw: Mapping[str, Any]) -> ArenaConfig:
    return ArenaConfig(data_dir=Path(str(raw["data_dir"])), population=int(raw["population"]),
                       rent_usd=float(raw["rent_usd"]), broke_usd=float(raw["broke_usd"]),
                       start_cash=float(raw["start_cash"]), control=dict(raw["control"]), fixed=dict(raw["fixed"]))


# ---------------------------------------------------------------------- the wire (live loop -> town)
_WINDOW_FIELDS = tuple(item.name for item in fields(Window))


def _levels(levels: Sequence[Level]) -> tuple[tuple[float, float], ...]:
    return tuple([(level.price, level.size) for level in levels])


def ladder_change(sent: tuple[Level, ...] | None, levels: tuple[Level, ...]) -> tuple[Any, ...] | None:
    """A book's bids (or asks) as a change to the ladder last sent for that window and side: None when it is the
    same ladder, else ``(start, stop, levels)``, meaning the sent ladder's ``[start:stop]`` is replaced (``stop``
    None: the whole ladder). The Kalshi socket rebuilds a ladder around the one level a delta changes and reuses
    every other level (``speeddesk_kalshi_ws.MarketState._changed_level``), so this is usually one level."""
    if levels is sent:
        return None
    if sent is None:
        return (0, None, _levels(levels))
    size, old = len(levels), len(sent)
    limit = min(size, old)
    # The first and last levels that are not the very same objects, scanned in C (a Python loop costs 2-3x more).
    start = next(compress(count(), map(is_not, levels, sent)), limit)
    end = min(limit - start, next(compress(count(), map(is_not, reversed(levels), reversed(sent))), limit))
    return (start, old - end, _levels(levels[start:size - end]))


def apply_ladder(sent: tuple[Level, ...] | None, change: Sequence[Any] | None) -> tuple[Level, ...]:
    if change is None:
        if sent is None:
            raise LookupError("no ladder to keep")
        return sent
    start, stop, levels = change
    fresh = tuple(Level(price, size) for price, size in levels)
    if stop is None:
        return fresh
    if sent is None:
        raise LookupError("no ladder to change")
    return sent[:start] + fresh + sent[stop:]


def book_wire(book: Book, sent: tuple[tuple[Level, ...], tuple[Level, ...]] | None = None) -> tuple[Any, ...]:
    """A book as a record: each ladder as a change to ``sent`` (the ladders last sent for its window and side)."""
    bids, asks = (None, None) if sent is None else sent
    return ("b", book.window, book.side, ladder_change(bids, book.bids), ladder_change(asks, book.asks), book.at,
            book.sequence, book.exchange_at, book.source, book.requested_at)


def trade_wire(trade: Trade) -> tuple[Any, ...]:
    return ("t", trade.window, trade.side, trade.price, trade.size, trade.at, trade.trade_id, trade.aggressor,
            trade.received_at)


def window_wire(window: Window) -> tuple[Any, ...]:
    return tuple(getattr(window, name) for name in _WINDOW_FIELDS)


def book_from_wire(record: Sequence[Any], ladders: dict[tuple[str, str], tuple[tuple[Level, ...], tuple[Level, ...]]]
                   ) -> Book:
    """The book a record carries, rebuilt on ``ladders`` (the ladders last received for each window and side, which
    it updates)."""
    _, window, side, bid_change, ask_change, at, sequence, exchange_at, source, requested_at = record
    sent = ladders.get((window, side))
    bids = apply_ladder(sent[0] if sent else None, bid_change)
    asks = apply_ladder(sent[1] if sent else None, ask_change)
    ladders[(window, side)] = (bids, asks)
    return Book(window, side, bids, asks, at, sequence, exchange_at, source, requested_at)


def trade_from_wire(record: Sequence[Any]) -> Trade:
    _, window, side, price, size, at, trade_id, aggressor, received_at = record
    return Trade(window, side, price, size, at, trade_id, aggressor, received_at)


def frame(value: Any) -> bytes:
    """One length-prefixed frame. ``marshal`` (format 2) carries only tuples, lists, dicts, text and numbers here."""
    payload = marshal.dumps(value, 2)
    return struct.pack("<I", len(payload)) + payload


class FrameReader:
    """Length-prefixed frames from the link's socket (the town's side). It never waits on the socket: the town
    sleeps on its own timer and then takes whatever arrived, so a write by the live loop never wakes a process (a
    woken process can take the live loop's CPU on the spot: measured p99 8 ms a write with a waiting reader, 0.1 ms
    without)."""

    def __init__(self, fd: int) -> None:
        self.fd = fd
        os.set_blocking(fd, False)
        self.buffer = bytearray()
        self.eof = False

    def drain(self) -> list[Any]:
        taken = 0
        while not self.eof and taken < READ_MAX:
            try:
                chunk = os.read(self.fd, 1 << 20)
            except BlockingIOError:
                break
            if not chunk:
                self.eof = True
                break
            self.buffer += chunk
            taken += len(chunk)
        out = []
        while len(self.buffer) >= 4:
            (size,) = struct.unpack_from("<I", self.buffer)
            if size > FRAME_MAX:
                raise ValueError("Kalshi arena frame too large")
            if len(self.buffer) < 4 + size:
                break
            out.append(marshal.loads(bytes(self.buffer[4:4 + size])))
            del self.buffer[:4 + size]
        return out


def worker_command() -> list[str]:
    """The town's process: this interpreter, isolated (no environment variables, no user site, no current
    directory), importing this package from where it is installed. It takes the idle scheduling class and the lowest
    priority BEFORE it imports anything of this package: the imports are most of a start's CPU (about 70 ms), and at a
    restart they would otherwise compete at normal priority with the live desk's own start (worker_main's
    :func:`_harden` then does the rest)."""
    root = str(Path(__file__).resolve().parent.parent)
    boot = ("import os, sys\n"
            "try:\n    os.sched_setscheduler(0, os.SCHED_IDLE, os.sched_param(0))\nexcept Exception:\n    pass\n"
            "try:\n    os.nice(19)\nexcept Exception:\n    pass\n"
            "sys.path.insert(0, sys.argv[1]); from nightcrawler.kalshi_arena import worker_main; sys.exit(worker_main())")
    return [sys.executable, "-I", "-X", "utf8", "-c", boot, root]


def worker_env() -> dict[str, str]:
    """The town's whole environment: nothing from the deployment, so no ``KALSHI_*`` key or any other secret."""
    return {"PATH": os.defpath, "LANG": "C.UTF-8", "TZ": "UTC"}


class ArenaLink:
    """The live loop's whole side of the town (module docstring, SPEED). :meth:`feed_book`, :meth:`feed_trade` and
    :meth:`feed_gap` are one bounded append; :meth:`flush` (once per runner step) encodes at most :data:`FLUSH_MAX`
    events within an encoding budget into one frame and writes it without waiting. Blocked or partial frames and
    later events retain FIFO order until sent; only queue overflow drops an event. :meth:`start` and :meth:`close`
    never block for long. None
    of them raises. It holds the town's configuration (numbers and genes) and a pipe, never a Settings object, a
    client or a key."""

    def __init__(self, config: ArenaConfig, *, command: Sequence[str] | None = None,
                 clock: Callable[[], float] = time.time, perf: Callable[[], int] = time.perf_counter_ns,
                 cpu: Callable[[], int] = time.thread_time_ns) -> None:
        self.wire = config_wire(config)
        self.command = list(command) if command is not None else worker_command()
        self.clock, self.perf, self.cpu = clock, perf, cpu
        self.cwd = Path(config.data_dir)
        self.pending: deque[Any] = deque()
        self.proc: subprocess.Popen[bytes] | None = None
        self.sock: socket.socket | None = None
        self.running = False
        self.out = b""  # the rest of a frame the pipe took only part of
        self.seq = 0
        self.puts = self.dropped = self.frames = self.sent_bytes = 0
        self.blocked = self.sliced = self.pending_peak = 0
        self._reported_dropped = 0
        self.returncode: int | None = None
        self._windows: Any = None
        self._makers: Any = None
        self._outcomes: Any = None
        self._bitcoin: Any = None
        self._recent: tuple[Any, ...] | None = None  # the windows last sent (as records) and their names
        self._recent_slugs: frozenset[str] = frozenset()
        self._shown: tuple[Any, ...] | None = None  # the outcomes last sent
        self._ladders: dict[tuple[str, str], tuple[tuple[Level, ...], tuple[Level, ...]]] = {}
        self.flush_ns: deque[int] = deque(maxlen=1024)
        self.last_flush_us = 0
        self.checked_at = -math.inf
        self.status_at = clock()

    # ------------------------------------------------------------------ the hot path (one append, never raises)
    def feed_book(self, book: Book) -> None:
        self._put(book)

    def feed_trade(self, trade: Trade) -> None:
        self._put(trade)

    def feed_gap(self, gap_windows: tuple[str, ...], trade_stream: bool, coinbase_connected: bool) -> None:
        self._put(("g", tuple(gap_windows), bool(trade_stream), bool(coinbase_connected)))

    def _put(self, item: Any) -> None:
        try:
            if not self.running:
                return
            if len(self.pending) >= PENDING_MAX:
                self.dropped += 1
                return
            self.pending.append(item)
            self.puts += 1
        except Exception:  # noqa: BLE001, S110 - the live loop must never see a practice error
            pass

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        """Start the town's process; on any failure the town stays off (logged) and the live desk runs on."""
        if self.proc is not None:
            return
        try:
            self.cwd.mkdir(parents=True, exist_ok=True)
            # A Unix stream socket, not a pipe: a pipe's reader holds a lock the writer needs while it copies, so a
            # town that loses its CPU mid-read would make the live loop wait; a socket's sender only takes spinlocks.
            ours, theirs = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock = ours
            try:
                with contextlib.suppress(OSError):
                    ours.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SEND_BYTES)
                self.proc = subprocess.Popen([*self.command, str(theirs.fileno())], stdin=subprocess.DEVNULL,
                                             env=worker_env(), cwd=str(self.cwd), close_fds=True,
                                             pass_fds=(theirs.fileno(),), start_new_session=True)
            finally:
                theirs.close()
            ours.setblocking(False)
            self.running = True
            self._send(frame(("config", self.wire)))
            if self.out:
                raise OSError("the Kalshi arena's pipe took part of its configuration")
            log.info("kalshi_arena_started pid=%d population=%d rent_usd=%.2f broke_usd=%.2f (practice only, its own "
                     "process)", self.proc.pid, self.wire["population"], self.wire["rent_usd"], self.wire["broke_usd"])
        except Exception as exc:  # noqa: BLE001 - a practice town never stops the speed desk
            log.warning("kalshi_arena_not_started error=%s", type(exc).__name__)
            self._stop_link()

    def close(self, wait_s: float = 0.0) -> None:
        """Close the pipe (the town saves and exits on it) and wait at most ``wait_s`` for that."""
        proc = self.proc
        self._stop_link()
        if proc is not None and wait_s > 0:
            with contextlib.suppress(Exception):
                proc.wait(timeout=wait_s)

    def _stop_link(self) -> None:
        self.running = False
        self.pending.clear()
        self.out = b""
        with contextlib.suppress(Exception):
            if self.sock is not None:
                self.sock.close()
        self.sock = None

    # ------------------------------------------------------------------ once per runner step
    def flush(self, snapshot: MarketView) -> None:
        if not self.running:
            return
        started = self.perf()
        try:
            self._flush(snapshot)
        except (BrokenPipeError, ConnectionResetError):  # the town's process is gone
            self._exited()
        except Exception as exc:  # noqa: BLE001 - a practice town never stops the speed desk
            log.warning("kalshi_arena_link_failed error=%s", type(exc).__name__)
            self._exited()
        elapsed = self.perf() - started
        self.flush_ns.append(elapsed)
        self.last_flush_us = elapsed // 1000

    def _flush(self, snapshot: MarketView) -> None:
        now = self.clock()
        assert self.proc is not None
        if now - self.checked_at >= CHECK_S:
            self.checked_at = now
            if self.proc.poll() is not None:
                self._exited()
                return
        if now - self.status_at >= LINK_STATUS_S:
            self._status(now)
        self.pending_peak = max(self.pending_peak, len(self.pending))
        if self.out:  # finish the frame the socket took only part of before a new one starts
            self._send(self.out)
            if self.out:  # retain the bounded FIFO; socket backpressure alone never loses a book or print
                self.blocked += 1
                return
        items: list[Any] = []
        # The market facts that changed since the last frame, first: the town reads its windows before the events.
        # The speed desk keeps every window it ever saw; the town needs only those it can still trade or settle
        # (it voids one without an outcome two hours after its close), so only those travel, and only on a change.
        windows = snapshot.windows
        if windows is not self._windows:
            cutoff = now - RECENT_S
            recent = tuple(window_wire(window) for window in windows if window.end > cutoff)
            if recent != self._recent:
                items.append(("w", recent))
                self._recent, self._recent_slugs = recent, frozenset(values[0] for values in recent)
                self._ladders = {key: value for key, value in self._ladders.items()
                                 if key[0] in self._recent_slugs}
        makers = snapshot.maker_windows
        if makers != self._makers:
            items.append(("k", tuple(sorted(makers))))
        outcome_index = len(items)
        bitcoin = (snapshot.bitcoin_price, snapshot.bitcoin_at, snapshot.sigma)
        if bitcoin != self._bitcoin:
            items.append(("m", *bitcoin))
        self._encode(items)
        # An outcome must not overtake its final queued prints: the child settles after draining this frame,
        # whereas a budget-limited following frame has not arrived yet. Retain the old outcome baseline until
        # this frame contains the end of the FIFO, so the unchanged snapshot will be considered again next step.
        outcomes = self._outcomes
        if not self.pending:
            outcomes = snapshot.outcomes
            if outcomes is not self._outcomes:
                shown = tuple(sorted((slug, bool(up)) for slug, up in outcomes.items() if slug in self._recent_slugs))
                if shown != self._shown:
                    items.insert(outcome_index, ("o", shown))
                    self._shown = shown
        if not items and self.dropped == self._reported_dropped:
            return
        self.seq += 1
        data = frame(("batch", self.seq, now, self.dropped, self.last_flush_us, items))
        self._send(data)
        self._reported_dropped = self.dropped
        self._windows, self._makers, self._outcomes, self._bitcoin = windows, makers, outcomes, bitcoin
        self.frames += 1

    def _encode(self, items: list[Any]) -> None:
        """Move only a bounded slice of the FIFO to this frame, preserving every intermediate book and print.

        A deque avoids copying the remaining burst on each step. No event that did not fit the time budget is
        consumed, and the ladder baseline advances only in the same order as the retained wire frames.
        """
        deadline = self.cpu() + FLUSH_BUDGET_NS
        limit = min(len(self.pending), FLUSH_MAX)
        taken = 0
        while taken < limit:
            for _ in range(min(FLUSH_CHUNK, limit - taken)):
                item = self.pending.popleft()
                if isinstance(item, Book):
                    key = (item.window, item.side)
                    items.append(book_wire(item, self._ladders.get(key)))
                    self._ladders[key] = (item.bids, item.asks)
                else:
                    items.append(trade_wire(item) if isinstance(item, Trade) else item)
                taken += 1
            if self.cpu() >= deadline:
                break
        if self.pending:
            self.sliced += 1

    def _send(self, data: bytes) -> None:
        assert self.sock is not None
        try:
            written = self.sock.send(data)
        except BlockingIOError:
            written = 0
        self.sent_bytes += written
        self.out = data[written:]

    def _exited(self) -> None:
        proc = self.proc
        code = None
        with contextlib.suppress(Exception):
            code = proc.poll() if proc is not None else None
        self.returncode = code
        log.warning("kalshi_arena_exited returncode=%s dropped=%d (practice town stopped; the live desk is "
                    "unaffected)", code, self.dropped)
        self._stop_link()

    def telemetry(self) -> dict[str, Any]:
        """The live loop's own cost of the town: what was handed over, dropped, and how long a flush took."""
        ordered = sorted(self.flush_ns)

        def us(q: float) -> int | None:
            return ordered[min(len(ordered) - 1, int(q * len(ordered)))] // 1000 if ordered else None

        return {"running": self.running, "pid": self.proc.pid if self.proc is not None else None, "put": self.puts,
                "dropped": self.dropped, "frames": self.frames, "kib": self.sent_bytes // 1024,
                "pending": len(self.pending), "pending_peak": self.pending_peak,
                "blocked": self.blocked, "sliced": self.sliced,
                "flush_us_p50": us(0.5), "flush_us_p99": us(0.99), "flush_us_max": us(1.0)}

    def _status(self, now: float) -> None:
        self.status_at = now
        feed = self.telemetry()
        log.info("kalshi_arena_feed pid=%s put=%d dropped=%d frames=%d kib=%d pending=%d pending_peak=%d "
                 "blocked=%d sliced=%d flush_us_p50=%s flush_us_p99=%s flush_us_max=%s",
                 feed["pid"], feed["put"], feed["dropped"], feed["frames"], feed["kib"],
                 feed["pending"], feed["pending_peak"], feed["blocked"], feed["sliced"],
                 feed["flush_us_p50"], feed["flush_us_p99"], feed["flush_us_max"])
        self.pending_peak = 0


# ---------------------------------------------------------------------- the town's view of the market
@dataclass
class WireView:
    """The market facts the link last sent (the town's :class:`MarketView`)."""

    windows: tuple[Window, ...] = ()
    books: dict[tuple[str, Side], Book] = field(default_factory=dict)
    bitcoin_price: float | None = None
    bitcoin_at: float | None = None
    sigma: float | None = None
    maker_windows: frozenset[str] = frozenset()
    outcomes: dict[str, bool] = field(default_factory=dict)


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


def _words(text: str, limit: int) -> str:
    """``text`` in at most ``limit`` characters, cut after a whole word (an ellipsis marks the cut)."""
    if len(text) <= limit:
        return text
    cut = text[:max(0, limit - 1)]
    if " " in cut:
        cut = cut[:cut.rindex(" ")]
    return cut.rstrip(" ,;:(") + "…"


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


def _maybe(value: Any) -> float | None:
    """A saved figure an older record may not carry: None (never counted) stays None."""
    return None if value is None else _number(value)


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
    try:
        speed_config(genes, {"window_usd": 10.0})  # values no desk accepts
    except Exception as exc:  # any failure is a bad file, never a crash
        raise ValueError("genes no desk accepts") from exc
    return genes


def _plain(value: Any) -> dict[str, Any] | None:
    """A saved display row (a grave, an event, a candidate flag) only if it is plain finite JSON; else dropped."""
    if not isinstance(value, Mapping):
        return None
    try:
        text = json.dumps(value, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        return None
    if len(text) > 8000:
        return None
    return dict(json.loads(text))


def _clean_row(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise TypeError("a resident must be a mapping")
    pnl = raw.get("pnl", [])
    if not isinstance(pnl, list) or any(value is not None and not isinstance(value, (int, float)) for value in pnl):
        raise TypeError("pnl must be numbers or nulls")
    saved_day = raw.get("day")
    day: Mapping[str, Any] = saved_day if isinstance(saved_day, Mapping) else {}
    row: dict[str, Any] = {
        "id": str(raw["id"]), "name": str(raw["name"])[:24], "control": bool(raw.get("control", False)),
        "gen": int(_number(raw.get("gen", 1))), "parent": None if raw.get("parent") is None else str(raw["parent"]),
        "born": _number(raw["born"]), "genes": _clean_genes(raw["genes"]),
        "equity_usd": _number(raw["equity_usd"]), "rent_paid": _number(raw.get("rent_paid", 0.0)),
        "pnl": [None if value is None else _number(value) for value in pnl][-RECORD_KEEP:],
        "windows": int(_number(raw.get("windows", 0))), "traded": int(_number(raw.get("traded", 0))),
        "wins": int(_number(raw.get("wins", 0))), "losses": int(_number(raw.get("losses", 0))),
        "pnl_usd": _number(raw.get("pnl_usd", 0.0)),
        # Counted since the field existed (None: a record from before that never counted it, shown as null).
        "fees_usd": _maybe(raw.get("fees_usd")), "contracts": _maybe(raw.get("contracts")),
        "fills": None if raw.get("fills") is None else int(_number(raw["fills"])),
        "funded_usd": _number(raw.get("funded_usd", START_CASH)),
        "record_from": _number(raw["record_from"]) if raw.get("record_from") is not None else _number(raw["born"]),
        "paired": {key: _number(value) for key, value in dict(raw.get("paired") or {}).items()
                   if key in ("n", "sum", "sumsq")},
        "verdict": {key: str(value)[:300] for key, value in dict(raw.get("verdict") or {}).items()
                    if key in ("word", "phrase", "reason")},
        "candidate": _plain(raw.get("candidate")),
        "candidate_now": bool(raw.get("candidate_now", False)),
        "since_flag": ({key: _number(value) for key, value in dict(raw["since_flag"]).items()
                        if key in ("n", "sum", "sumsq")} if isinstance(raw.get("since_flag"), Mapping) else None),
        # Today's settled P&L, so the day stop survives a restart as live's does.
        "day": ({"day": str(day["day"])[:10], "pnl_usd": _number(day["pnl_usd"])}
                if "day" in day and "pnl_usd" in day else {}),
    }
    return row


def _write(path: Path, text: str, *, durable: bool = False) -> None:
    """Atomic: a temporary sibling, then a rename; ``durable`` also fsyncs it first (the town's only record; this
    runs in the town's own process, never the live desk's). A write that fails (a full disk) removes its temporary
    file: DATA_DIR is the live desk's volume too, and a partial copy left behind would keep its space."""
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(text)
            if durable:
                stream.flush()
                os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            temporary.unlink()
        raise


# ---------------------------------------------------------------------- the town
class KalshiArena:
    """The town (it runs in its own process: :func:`worker_main`). PRACTICE ONLY: no client, no key, no order path.

    :meth:`receive` takes one frame from the live loop; :meth:`feed_book`, :meth:`feed_trade` and :meth:`feed_gap`
    queue events for the next pass; :meth:`step` is one pass of the town."""

    def __init__(self, config: ArenaConfig, snapshot: Callable[[], MarketView], *,
                 clock: Callable[[], float] = time.time, cpu: Callable[[], float] = time.process_time) -> None:
        if not 2 <= int(config.population) <= 24:
            raise ValueError("The Kalshi arena holds 2 to 24 residents")
        self.config = config
        self._snapshot = snapshot
        self.clock, self.cpu = clock, cpu
        self.directory = Path(config.data_dir) / "kalshi_arena"
        self.path = self.directory / "state.json"
        self.panel_path = self.directory / "panel.json"
        self.inbox: deque[tuple[Any, ...]] = deque()
        self.ladders: dict[tuple[str, str], tuple[tuple[Level, ...], tuple[Level, ...]]] = {}
        self.tape = FedTape()
        self.residents: dict[str, Resident] = {}
        self.windows: dict[str, Window] = {}
        self.members: dict[str, set[str]] = {}
        self.degraded: dict[str, str] = {}  # windows whose feed was incomplete for the town: void at settlement
        self.settled: deque[str] = deque(maxlen=SETTLED_KEEP)
        self.skipped: deque[str] = deque(maxlen=SETTLED_KEEP)
        self.seen_prints: set[str] = set()
        self.print_order: deque[str] = deque()
        self.grave: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.town: dict[str, Any] = {"born": 0, "evicted": 0, "windows": 0, "void_windows": 0, "void_feed": 0,
                                     "rent_paid": 0.0, "candidates": 0, "rent_days": 0}
        self.next_id = 1
        self.seq = 0
        # This town's identity, drawn afresh with every fresh state file: resident and event ids are unique within it.
        self.town_id = os.urandom(6).hex()
        self.next_event = 1
        self.window_fills: dict[tuple[str, str], int] = {}  # (resident id, window): fills not settled yet
        self.last_frame_at: float | None = None  # the town's clock when the last frame from the live loop arrived
        self.hardening: dict[str, Any] | None = None  # what the town's process runs with (report_hardening)
        self.rent_day: str | None = None
        self.problem: str | None = None
        self.received = 0
        self.late = 0
        self.coalesced = 0
        self.errors = 0
        self.lag_s = 0.0
        self.link_seq: int | None = None
        self.link_dropped = 0
        self._incomplete_before = -math.inf  # include windows first named in the same frame as a drop receipt
        self.live_flush_us: deque[int] = deque(maxlen=PASSES_KEEP)
        self.passes: deque[float] = deque(maxlen=PASSES_KEEP)
        # The share of a core: the process's whole CPU time (reading and decoding frames too, not only step()).
        self.cpu_base = cpu()
        self.cpu_since = clock()
        self.started_at = clock()
        self.saved_at = -math.inf
        self.status_at = clock()
        self.dirty = True
        self.snap: MarketView | None = None
        self._seen_windows: tuple[Window, ...] | None = None
        self._last_pass: float | None = None
        self._feed_status = (False, False)
        self.control_verdict = ""
        self.control_rule = rule_id(config.control)
        self.regime = rule_id(config.fixed)
        self.learning = OnlineLearning(clock())
        self._load(clock())
        self._learning_call("status", clock())
        self.rng = random.Random(SEED + self.next_id)
        self._populate(clock())

    def _learning_call(self, method: str, *args: Any) -> Any:
        """Optional child diagnostics cannot reset the arena or alter resident decisions."""
        try:
            return getattr(self.learning, method)(*args)
        except Exception:  # noqa: BLE001 - learning failures are isolated from practice and live execution
            self.learning.disable("optional_learning_method_failed")
            return None

    # ------------------------------------------------------------------ the feed
    def feed_book(self, book: Book) -> None:
        self.inbox.append(("book", book))

    def feed_trade(self, trade: Trade) -> None:
        self.inbox.append(("trade", trade))

    def feed_gap(self, gap_windows: tuple[str, ...], trade_stream: bool, coinbase_connected: bool) -> None:
        self.inbox.append(("gap", gap_windows, trade_stream, coinbase_connected))

    def receive(self, message: Any, view: WireView) -> None:
        """One frame from :class:`ArenaLink`: market facts update ``view``; books, prints and gaps are queued. A frame
        the link had to drop leaves every started, unsettled window incomplete (void at its settlement), including
        windows first named in this frame. A delayed drop receipt must not spare a window merely because it closed."""
        if not isinstance(message, tuple) or not message or message[0] != "batch":
            raise ValueError("unexpected Kalshi arena frame")
        _, seq, _sent_at, dropped, flush_us, items = message
        now = self.clock()
        self.last_frame_at = now
        if (self.link_seq is not None and seq != self.link_seq + 1) or dropped > self.link_dropped:
            self._incomplete_before = max(self._incomplete_before, now)
            self._degrade_started(now, "feed_dropped")
        self.link_seq, self.link_dropped = int(seq), max(self.link_dropped, int(dropped))
        self.live_flush_us.append(int(flush_us))
        for record in items:
            tag = record[0]
            if tag == "b":
                self.received += 1
                try:
                    self.feed_book(book_from_wire(record, self.ladders))
                except LookupError:  # a change to a ladder never received (not expected: the link resends whole)
                    self._degrade(str(record[1]), "feed_dropped")
            elif tag == "t":
                self.feed_trade(trade_from_wire(record))
                self.received += 1
            elif tag == "g":
                self.feed_gap(tuple(record[1]), bool(record[2]), bool(record[3]))
            elif tag == "w":
                view.windows = tuple(Window(*values) for values in record[1])
                self._learning_call("discover", view.windows, now)
                live = {window.slug for window in view.windows}
                self.ladders = {key: value for key, value in self.ladders.items() if key[0] in live}
            elif tag == "m":
                view.bitcoin_price, view.bitcoin_at, view.sigma = record[1], record[2], record[3]
            elif tag == "k":
                view.maker_windows = frozenset(record[1])
            elif tag == "o":
                self._learning_call("labels_received", record[1], now)
                view.outcomes = {str(slug): bool(up) for slug, up in record[1]}
            else:
                raise ValueError("unexpected Kalshi arena record")

    def _degrade(self, slug: str, why: str) -> None:
        self._learning_call("degrade", slug, why, self.clock())
        if slug in self.windows:
            self.degraded.setdefault(slug, why)

    def _degrade_started(self, now: float, why: str) -> None:
        for slug, window in self.windows.items():
            if window.start <= now:
                self._learning_call("degrade", slug, why, now)
                self.degraded.setdefault(slug, why)

    # ------------------------------------------------------------------ one pass
    def step(self, now: float) -> None:
        started = self.cpu()
        snap = self._snapshot()
        self.snap = snap
        self._learning_call("discover", snap.windows, now)
        self._windows(snap, now)
        self.tape.feed(snap.bitcoin_price, snap.bitcoin_at, snap.sigma)
        # Books and prints drained now may be newer than the pass's start: the rest of the pass uses the clock after
        # them, so none looks like it came from the future.
        now = max(self._drain(now), self.clock())
        self._learning_call("advance", snap.windows, snap.bitcoin_price, snap.sigma, snap.bitcoin_at,
                            snap.outcomes, now, self.degraded, True)
        self._settle(snap, now)
        self._voids(now)
        self._evaluate(snap, now)
        if (self.dirty and now - self.saved_at >= SAVE_SOON_S) or now - self.saved_at >= SAVE_EVERY_S:
            self._save(now)
        trouble = self.lag_s > 1.0 or bool(self.degraded)
        if now - self.status_at >= (STATUS_TROUBLE_S if trouble else STATUS_EVERY_S):
            self._status(now)
        self.passes.append(max(0.0, self.cpu() - started))

    def _holders(self, slug: str) -> list[Resident]:
        return [self.residents[rid] for rid in self.members.get(slug, ()) if rid in self.residents]

    def _windows(self, snap: MarketView, now: float) -> None:
        if snap.windows is self._seen_windows:
            return
        self._seen_windows = snap.windows
        settled = set(self.settled)
        for window in snap.windows:
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
                if window.start <= self._incomplete_before:
                    self.degraded.setdefault(slug, "feed_dropped")
                self.members[slug] = set()
                for res in self.residents.values():
                    if float(res.row["born"]) <= window.start:
                        res.desk.add_window(replace(window))
                        self.members[slug].add(res.id)
            elif known != window:
                changed = any(getattr(known, key) != getattr(window, key) for key in TERMS)
                for res in self._holders(slug):
                    if changed:  # the speed desk's own rule (SpeedRunner.on_windows)
                        res.desk.cancel(now, slug, "venue_terms_changed")
                        res.desk.books = {key: book for key, book in res.desk.books.items() if key[0] != slug}
                    res.desk.add_window(replace(window))
                self.windows[slug] = replace(window)

    def _drain(self, now: float) -> float:
        """Apply queued books, prints and gaps in arrival order, each at the time it is read; returns that time.

        A book is skipped only when a later book for the same window and side is already queued and no resident
        has an order there. Resting bids also need intervening books: a stale book can cancel a bid before the next
        print, and a take must see an ask disappear before it returns. Each print is de-duplicated once for all residents.
        An event read more than :data:`LATE_S` after it arrived leaves its window incomplete."""
        items = list(self.inbox)
        self.inbox.clear()
        if not items:
            self.lag_s = 0.0
            return now
        latest: dict[tuple[str, str], int] = {}
        for index, item in enumerate(items):
            if item[0] == "book":
                latest[(item[1].window, item[1].side)] = index
        ordered = {order.window for res in self.residents.values() for order in res.desk.orders.values()}
        lag = 0.0
        for index, item in enumerate(items):
            now = max(now, self.clock())
            kind = item[0]
            if kind == "book":
                book: Book = item[1]
                behind = now - book.at
                lag = max(lag, behind)
                if behind > LATE_S:
                    self.late += 1
                    self._degrade(book.window, "feed_late")
                if latest[(book.window, book.side)] != index and book.window not in ordered:
                    self.coalesced += 1
                    continue
                for res in self._holders(book.window):
                    if res.desk.on_book(book):
                        self._fills(res, res.desk.advance(now))
            elif kind == "trade":
                trade: Trade = item[1]
                behind = now - (trade.received_at if trade.received_at is not None else trade.at)
                lag = max(lag, behind)
                if behind > LATE_S:
                    self.late += 1
                    self._degrade(trade.window, "feed_late")
                identity = f"{trade.window}:{trade.side}:{trade.trade_id}"
                if identity in self.seen_prints:
                    continue
                self.seen_prints.add(identity)
                self.print_order.append(identity)
                while len(self.print_order) > SEEN_PRINTS:
                    self.seen_prints.discard(self.print_order.popleft())
                for res in self._holders(trade.window):
                    self._fills(res, res.desk.on_trade(trade, now))
            elif kind == "gap":
                self._gap(item[1], bool(item[2]), bool(item[3]), now)
        self.lag_s = max(0.0, lag)
        return now

    def _gap(self, gap_windows: Sequence[str], trade_stream: bool, coinbase: bool, now: float) -> None:
        """The speed desk's own feed-gap rule (SpeedRunner.on_status): a lost stream cancels everything."""
        self._learning_call("gap", gap_windows, trade_stream, coinbase, now)
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
        (the residents fall out of step, so no pass carries all twelve); a slow pass means less often."""
        makers = set(snap.maker_windows)
        elapsed = EVAL_S if self._last_pass is None else max(0.0, now - self._last_pass)
        self._last_pass = now
        share = max(1, math.ceil(len(self.residents) * elapsed / EVAL_S))
        due = sorted((res for res in self.residents.values() if now - res.last_eval >= EVAL_S),
                     key=lambda res: res.last_eval)
        for res in due[:share]:
            res.last_eval = now
            self._fills(res, res.desk.evaluate(now, makers_enabled=bool(makers), maker_windows=makers))

    def _fills(self, res: Resident, decisions: Sequence[Any]) -> None:
        """Count a resident's fills per window; a window's count is booked at its settlement (a void drops it)."""
        for decision in decisions:
            if decision.event == FILL:
                key = (res.id, decision.window)
                self.window_fills[key] = self.window_fills.get(key, 0) + 1

    def _forget_window(self, slug: str) -> None:
        self.windows.pop(slug, None)
        self.members.pop(slug, None)
        self.degraded.pop(slug, None)
        self.settled.append(slug)
        self.window_fills = {key: value for key, value in self.window_fills.items() if key[1] != slug}

    def _void(self, slug: str, now: float, why: str, text: str) -> None:
        """No record and no money for anyone: equal for all."""
        for res in self._holders(slug):
            res.desk.cancel(now, slug, "void")
            res.desk.forget(slug, void=True)
        self._forget_window(slug)
        self.town["void_windows"] += 1
        self._event(now, "Town", text, "neutral", "void")
        self.dirty = True
        log.info("kalshi_arena_void window=%s why=%s", slug, why)

    def _voids(self, now: float) -> None:
        for slug, window in list(self.windows.items()):
            if now - window.end > VOID_AFTER_S:
                self._void(slug, now, "no_outcome",
                           f"Window {slug[-12:]} never settled: void for everyone (no record, no money).")

    # ------------------------------------------------------------------ settlement and the town's rules
    def _settle(self, snap: MarketView, now: float) -> None:
        for slug in [slug for slug in self.windows if slug in snap.outcomes]:
            window = self.windows[slug]
            if now < window.end:
                continue
            why = self.degraded.get(slug)
            if why is not None:
                self.town["void_feed"] += 1
                self._void(slug, now, why, f"Window {slug[-12:]}: the town's feed was incomplete ({why}), so it is "
                           "void for everyone (no record, no money).")
                continue
            up_wins = bool(snap.outcomes[slug])
            results: dict[str, float | None] = {}
            books: dict[str, tuple[float, float, int]] = {}
            for res in self._holders(slug):
                if slug not in res.desk.windows:
                    continue  # never expected; one resident's gap must not stop the town's settlement
                res.desk.cancel(now, slug, "settled")
                result = res.desk.settle(slug, up_wins, now)
                res.desk.forget(slug)
                if result is not None:
                    contracts = result.up_shares + result.down_shares
                    results[res.id] = round(result.pnl_usd, 4) if contracts > 0 else None
                    books[res.id] = (result.fee_usd, contracts, self.window_fills.get((res.id, slug), 0))
            self._forget_window(slug)
            self._after_window(window, results, now, books)

    def _after_window(self, window: Window, results: Mapping[str, float | None], now: float,
                      books: Mapping[str, tuple[float, float, int]] | None = None) -> None:
        """Book one settled window for every resident that held it (``books``: its fees, contracts and fills there;
        the fees are already inside its P&L), then rent, evictions, births and flags."""
        self.town["windows"] += 1
        self.seq += 1
        control = self._control()
        # The control holds every window a challenger can be compared on (it is never evicted).
        benchmark = control is not None and control.id in results
        control_pnl = (results.get(control.id) or 0.0) if control is not None else 0.0
        today = _day(now)
        for rid, pnl in results.items():
            res = self.residents.get(rid)
            if res is None:
                continue
            row = res.row
            row["pnl"].append(pnl)
            del row["pnl"][:-RECORD_KEEP]
            row["windows"] += 1
            book = (books or {}).get(rid)
            if book is not None:
                fee, contracts, fills = book
                if row.get("fees_usd") is not None:
                    row["fees_usd"] = round(float(row["fees_usd"]) + fee, 6)
                if row.get("contracts") is not None:
                    row["contracts"] = round(float(row["contracts"]) + contracts, 6)
                if row.get("fills") is not None:
                    row["fills"] = int(row["fills"]) + int(fills)
            if pnl is not None:
                row["traded"] += 1
                row["wins"] += int(pnl > 0)
                row["losses"] += int(pnl < 0)
                row["pnl_usd"] = round(float(row["pnl_usd"]) + pnl, 6)
                row["equity_usd"] = round(float(row["equity_usd"]) + pnl, 6)
                day: dict[str, Any] = row.get("day") or {}
                earlier = float(day["pnl_usd"]) if day.get("day") == today else 0.0
                row["day"] = {"day": today, "pnl_usd": round(earlier + pnl, 6)}
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
        """The first window settled on a new UTC day charges every resident the rent for each day since the last
        one (at most :data:`RENT_CATCHUP_DAYS`; none on the town's first day); a challenger that cannot pay it is
        evicted instead."""
        day = _day(window.end)
        if self.rent_day is None:
            self.rent_day = day
            return
        if day <= self.rent_day:
            return
        days = max(1, min(RENT_CATCHUP_DAYS, (date.fromisoformat(day) - date.fromisoformat(self.rent_day)).days))
        self.rent_day = day
        rent = round(self.config.rent_usd * days, 6)
        paid = 0
        for res in list(self.residents.values()):
            if not res.control and float(res.row["equity_usd"]) < rent:
                self._evict(res, "could not pay the rent", now)
                continue
            res.row["equity_usd"] = round(float(res.row["equity_usd"]) - rent, 6)
            res.row["rent_paid"] = round(float(res.row["rent_paid"]) + rent, 6)
            self.town["rent_paid"] = round(float(self.town["rent_paid"]) + rent, 6)
            paid += 1
        self.town["rent_days"] += days
        if paid:
            span = f" for {days} days" if days > 1 else ""
            self._event(now, "Town", f"Rent day {day}: {paid} residents paid ${rent:.2f} each{span} (practice).",
                        "neutral", "rent")

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
                            "bad" if verdict.verdict == LOSING else "neutral", "control", res.id)
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
                    "pre-registered test, not proof.", "good", "candidate", res.id)

    def _evict(self, res: Resident, why: str, now: float) -> None:
        row = res.row
        self.residents.pop(res.id, None)
        for members in self.members.values():
            members.discard(res.id)
        days = max(0.0, (now - float(row["born"])) / 86_400.0)
        verdict = row.get("verdict") or {}
        self.window_fills = {key: value for key, value in self.window_fills.items() if key[0] != res.id}
        # The retired resident keeps its id (never given again in this town), lineage, genes and whole record.
        self.grave.insert(0, {
            "id": row["id"], "name": row["name"], "gen": row["gen"], "parent": row["parent"], "born": row["born"],
            "died": now, "days": round(days, 2), "windows": row["windows"], "traded": row["traded"],
            "wins": row["wins"], "losses": row["losses"], "fills": row.get("fills"),
            "contracts": None if row.get("contracts") is None else round(float(row["contracts"]), 4),
            "funded_usd": round(float(row["funded_usd"]), 4),
            "pnl_usd": round(float(row["pnl_usd"]), 4), "equity_usd": round(float(row["equity_usd"]), 4),
            "fees_usd": None if row.get("fees_usd") is None else round(float(row["fees_usd"]), 4),
            "rent_paid": round(float(row["rent_paid"]), 4), "why": why[:160], "verdict": verdict.get("word"),
            "genes": row["genes"], "rule_id": rule_id(row["genes"]), "style": style(row["genes"]),
            "vs_control": _paired(row["paired"]), "was_candidate": row.get("candidate") is not None})
        del self.grave[GRAVE_KEEP:]
        self.town["evicted"] += 1
        self.dirty = True
        log.info("kalshi_arena_evicted resident=%s why=%s windows=%d pnl_usd=%.2f equity_usd=%.2f days=%.1f",
                 row["name"], why.split(":")[0].replace(" ", "_"), row["traded"], float(row["pnl_usd"]),
                 float(row["equity_usd"]), days)
        head = f"{row['name']} was evicted: "
        tail = f" after {days:.1f} days ({row['traded']} windows traded, {float(row['pnl_usd']):+.2f} $)."
        # The reason fills what the line has room for, cut at a word (the grave row keeps it whole).
        self._event(now, row["name"], head + _words(why, EVENT_TEXT - len(head) - len(tail)) + tail, "bad",
                    "evicted", res.id)

    def _control(self) -> Resident | None:
        return next((res for res in self.residents.values() if res.control), None)

    # ------------------------------------------------------------------ births
    def _desk(self, genes: Mapping[str, Any]) -> PracticeDesk:
        desk = PracticeDesk(speed_config(genes, self.config.fixed))
        desk.tape = self.tape
        desk.trade_memory = RESIDENT_TRADE_MEMORY  # the town de-duplicates every print once (_drain)
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
               "wins": 0, "losses": 0, "pnl_usd": 0.0, "fees_usd": 0.0, "contracts": 0.0, "fills": 0,
               # One funding at birth, never topped up (a child inherits no money); the record runs from here.
               "funded_usd": float(self.config.start_cash), "record_from": now,
               "paired": {"n": 0, "sum": 0.0, "sumsq": 0.0},
               "verdict": {"word": "learning", "phrase": PHRASES["learning"], "reason": ""}, "candidate": None,
               "candidate_now": False, "since_flag": None, "day": {}}
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
        self._event(now, name, f"{name} moved in,{who}: {style(genes)}.", "good", "born", res.id)
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
        """Parents come from the richer half of the residents with a record (:data:`PARENT_MIN_TRADED` traded
        windows; the control always counts): a newborn's untouched $50 says nothing yet."""
        while len(self.residents) < self.config.population:
            proven = [res for res in self.residents.values()
                      if res.control or int(res.row["traded"]) >= PARENT_MIN_TRADED]
            ranked = sorted(proven, key=lambda res: -float(res.row["equity_usd"]))
            parents = ranked[:max(1, len(ranked) // 2)]
            parent = parents[min(len(parents) - 1, int(self.rng.random() ** 2 * len(parents)))]
            self._new_resident(child_genes(parent.row["genes"], self.rng), now, parent=parent)

    # ------------------------------------------------------------------ the story, the panel and the files
    def _event(self, now: float, who: str, text: str, tone: str, kind: str, resident_id: str | None = None) -> None:
        """One line of the town's story, with an id never used again in this town (``town_id``) and the resident it
        is about (None: the town itself)."""
        self.events.insert(0, {"id": self.next_event, "ts": now, "who": who[:24], "resident_id": resident_id,
                               "text": text[:EVENT_TEXT], "tone": tone, "kind": kind})
        self.next_event += 1
        del self.events[EVENTS_KEEP:]

    def telemetry(self, now: float) -> dict[str, Any]:
        """The feed and the town's own work since the last status line: what arrived, what the live loop dropped,
        late events, CPU per pass, the process's share of a core (everything it ran, reading and decoding frames
        too), lag, the live loop's own flush times (it sends them), when the last frame arrived (the town's clock),
        open windows already incomplete (void for everyone at their settlement), and what isolation the process
        actually got (:func:`report_hardening`; None outside the town's own process). Counters run from the start
        of the town's process (they are not restored from the state file)."""
        passes = sorted(self.passes)
        flushes = sorted(self.live_flush_us)
        elapsed = max(1e-9, now - self.cpu_since)

        def pick(values: list[Any], q: float) -> Any:
            return values[min(len(values) - 1, int(q * len(values)))] if values else None

        def ms(q: float) -> float | None:
            value = pick(passes, q)
            return None if value is None else round(value * 1000, 3)

        duty = round(100 * max(0.0, self.cpu() - self.cpu_base) / elapsed, 2)
        return {"queue": len(self.inbox), "received": self.received, "dropped": self.link_dropped,
                "late": self.late, "coalesced": self.coalesced, "pass_p50_ms": ms(0.5), "pass_p99_ms": ms(0.99),
                "pass_max_ms": ms(1.0), "duty_pct": duty, "lag_s": round(self.lag_s, 3),
                "errors": self.errors, "live_flush_us_p50": pick(flushes, 0.5), "live_flush_us_p99": pick(flushes, 0.99),
                "live_flush_us_max": pick(flushes, 1.0), "last_frame_at": self.last_frame_at,
                "open_incomplete": len(self.degraded),
                "hardening": None if self.hardening is None else dict(self.hardening)}

    def _resident_row(self, res: Resident, now: float) -> dict[str, Any]:
        """One resident as the page shows it. PRACTICE money in USD, fees included; equity carries the open
        contracts AT COST (``equity_basis`` "cost": they are not marked to the market, so ``open_mark_usd`` is
        null); rent is apart from the trading P&L (equity = funded + P&L - rent). ``cash_usd`` (equity less the open
        contracts' cost; it includes ``reserved_usd``) can briefly go below zero: every desk trades the live $10
        window and $20 open budgets whatever its own money."""
        row, desk = res.row, res.desk
        open_cost = sum(inventory.spent for inventory in desk.inventory.values())
        held = sum(inventory.up.shares + inventory.down.shares for inventory in desk.inventory.values())
        reserved = sum(order.reserved for order in desk.orders.values())
        activity = ("holding" if held > 0 else "bidding" if desk.orders else
                    "newborn" if row["windows"] == 0 else "idle")
        equity = float(row["equity_usd"])
        record = [value for value in row["pnl"] if value is not None]
        return {"id": row["id"], "name": row["name"], "control": res.control, "gen": row["gen"],
                "parent": row["parent"], "born": row["born"],
                "days": round(max(0.0, now - float(row["born"])) / 86_400.0, 2),
                "status": "active", "activity": activity, "genes": dict(row["genes"]), "rule_id": rule_id(row["genes"]),
                "style": style(row["genes"]), "funded_usd": round(float(row["funded_usd"]), 2),
                "equity_usd": round(equity, 2), "cash_usd": round(equity - open_cost, 2),
                "open_cost_usd": round(open_cost, 2), "open_contracts": round(held, 4), "open_mark_usd": None,
                "reserved_usd": round(reserved, 2), "open_orders": len(desk.orders),
                "pnl_usd": round(float(row["pnl_usd"]), 2),
                "fees_usd": None if row.get("fees_usd") is None else round(float(row["fees_usd"]), 4),
                "rent_paid": round(float(row["rent_paid"]), 2),
                "profit_usd": round(equity - float(row["funded_usd"]), 2),
                "windows": row["windows"], "traded": row["traded"], "wins": row["wins"], "losses": row["losses"],
                "fills": row.get("fills"),
                "contracts": None if row.get("contracts") is None else round(float(row["contracts"]), 4),
                "verdict": row["verdict"].get("word"), "phrase": row["verdict"].get("phrase"),
                "reason": row["verdict"].get("reason") or None,
                "record": {"from": row["record_from"], "windows": len(row["pnl"]), "traded": len(record),
                           "keep": RECORD_KEEP},
                "vs_control": None if res.control else _paired(row["paired"]),
                "candidate": row["candidate"] is not None, "candidate_now": bool(row["candidate_now"])}

    def panel(self, now: float) -> dict[str, Any]:
        """The page's compact view (``panel.json``; pagestate.kalshi_arena_block whitelists it into the page's
        top-level ``kalshi_arena``). Every list is bounded; ``counts`` are the full totals (``grave``: every eviction
        in this town; ``events``: every event recorded) and ``truncated`` says which list shows fewer."""
        rows = sorted((self._resident_row(res, now) for res in self.residents.values()),
                      key=lambda row: (-row["equity_usd"], row["id"]))
        control = self._control()
        candidates = []
        for res in self.residents.values():
            flag = res.row["candidate"]
            if flag is not None:
                candidates.append({"id": res.id, "name": res.row["name"], "at": flag.get("at"), "n": flag.get("n"),
                                   "t": flag.get("t"), "mean_usd": flag.get("mean_usd"),
                                   "since_flag": _paired(res.row["since_flag"]), "adopt": flag.get("adopt"),
                                   "candidate_now": bool(res.row["candidate_now"]),
                                   "note": "A lead for a pre-registered test, not proof."})
        candidates.sort(key=lambda row: (-(row["t"] or 0), row["id"]))
        # The one current candidate: the highest t among those whose flag holds now.
        leading = next((row["id"] for row in candidates if row["candidate_now"]), None)
        shown = {"residents": rows[:PANEL_RESIDENTS], "grave": self.grave[:PANEL_GRAVE],
                 "candidates": candidates[:PANEL_CANDIDATES], "events": self.events[:PANEL_EVENTS]}
        counts = {"residents": len(rows), "grave": int(self.town["evicted"]), "candidates": len(candidates),
                  "events": self.next_event - 1}
        return {"schema_version": PANEL_SCHEMA, "mode": "paper", "label": LABEL, "as_of": now,
                "town_id": self.town_id, "heartbeat_s": SAVE_EVERY_S, "problem": self.problem,
                "population": len(self.residents), "rent_usd": self.config.rent_usd,
                "broke_usd": self.config.broke_usd, "start_cash": self.config.start_cash, "note": NOTE,
                "control_id": None if control is None else control.id, "candidate_id": leading,
                "control": None if control is None else {
                    "id": control.id, "name": control.row["name"],
                    "equity_usd": round(float(control.row["equity_usd"]), 2),
                    "windows": control.row["windows"], "traded": control.row["traded"],
                    "pnl_usd": round(float(control.row["pnl_usd"]), 2), "verdict": control.row["verdict"].get("word"),
                    "phrase": control.row["verdict"].get("phrase"),
                    "reason": control.row["verdict"].get("reason", ""), "genes_line": style(control.row["genes"])},
                **shown, "counts": counts,
                "truncated": {key: len(shown[key]) < counts[key] for key in counts},
                "town": dict(self.town), "feed": self.telemetry(now),
                "learning": self._learning_call("panel")}

    def state(self, now: float) -> dict[str, Any]:
        return {"version": STATE_VERSION, "label": LABEL, "saved_at": now, "started_at": self.started_at,
                "settings": {"population": self.config.population, "rent_usd": self.config.rent_usd,
                             "broke_usd": self.config.broke_usd, "start_cash": self.config.start_cash},
                "control_rule": self.control_rule, "regime": self.regime, "next_id": self.next_id, "seq": self.seq,
                "town_id": self.town_id, "next_event": self.next_event, "rent_day": self.rent_day,
                "learning": self._learning_call("state"),
                "active_windows": [[slug, window.start] for slug, window in sorted(self.windows.items())],
                "residents": [res.row for res in self.residents.values()], "grave": self.grave,
                "events": self.events, "town": self.town,
                "feed": {"received": self.received, "dropped": self.link_dropped, "late": self.late,
                         "errors": self.errors}, "problem": self.problem}

    def _save(self, now: float) -> None:
        """state.json, then panel.json. The state is fsynced (the town's only record) only after a change that
        matters (``dirty``: a settlement, birth, eviction, void, flag or halt, and the first save); the minute's
        heartbeat save, which only keeps the panel and its counters current, is a plain atomic rename. So the town
        fsyncs a few times an hour, not every minute, on the volume and journal the live desk's own fsyncs use."""
        self.directory.mkdir(parents=True, exist_ok=True)
        _write(self.path, json.dumps(self.state(now), allow_nan=False, separators=(",", ":")), durable=self.dirty)
        _write(self.panel_path, json.dumps(self.panel(now), allow_nan=False, separators=(",", ":")))
        self.saved_at = now
        self.dirty = False

    def _status(self, now: float) -> None:
        self._learning_call("status", now)
        self.status_at = now
        feed = self.telemetry(now)
        log.info("kalshi_arena_status residents=%d windows=%d void=%d void_feed=%d received=%d dropped=%d late=%d "
                 "coalesced=%d pass_p99_ms=%s pass_max_ms=%s duty_pct=%.2f lag_s=%.2f errors=%d "
                 "live_flush_us_p99=%s live_flush_us_max=%s", len(self.residents), self.town["windows"],
                 self.town["void_windows"], self.town["void_feed"], feed["received"], feed["dropped"], feed["late"],
                 feed["coalesced"], feed["pass_p99_ms"], feed["pass_max_ms"], feed["duty_pct"], feed["lag_s"],
                 feed["errors"], feed["live_flush_us_p99"], feed["live_flush_us_max"])
        self.passes.clear()
        self.live_flush_us.clear()
        self.cpu_base, self.cpu_since = self.cpu(), now

    def _brief_panel(self, now: float) -> dict[str, Any]:
        """The panel without its figures (the page shows them as unknown): what still fits on a full disk."""
        return {"schema_version": PANEL_SCHEMA, "mode": "paper", "label": LABEL, "as_of": now,
                "town_id": self.town_id, "heartbeat_s": SAVE_EVERY_S, "problem": self.problem}

    def _halt(self, exc: BaseException) -> None:
        """The town stops itself. The page hears it first: panel.json (small, not fsynced) is written on its own,
        before the state file, because on a full disk (the volume the live desk shares) the larger state file fails
        first and would take the panel with it; when even the panel does not fit, its brief form does."""
        self.problem = "Practice town halted after repeated errors; the live desk is unaffected"
        self.dirty = True
        log.error("kalshi_arena_halted error=%s", type(exc).__name__)
        now = self.clock()
        for build in (self.panel, self._brief_panel):
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                _write(self.panel_path, json.dumps(build(now), allow_nan=False, separators=(",", ":")))
                break
            except Exception:  # noqa: BLE001, S112 - the halt is already logged; try the smaller form
                continue
        with contextlib.suppress(Exception):  # the halt is already logged
            self._save(now)

    def _load(self, now: float) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except Exception as exc:  # noqa: BLE001 - any unreadable file (even a too-deep one) moves aside
            self._reset(exc)
            return
        try:
            self._restore(raw, now)
        except Exception as exc:  # noqa: BLE001 - any bad content moves aside; the town starts fresh
            self.residents.clear()
            self.grave, self.events, self.next_id, self.seq, self.rent_day = [], [], 1, 0, None
            # A new town for every reader: its ids restart, so it gets an identity of its own.
            self.town_id, self.next_event = os.urandom(6).hex(), 1
            self.skipped.clear()
            self.town = {key: 0.0 if key == "rent_paid" else 0 for key in self.town}
            self._reset(exc)
        else:
            self._learning_call("restore", raw.get("learning"), now)

    def _reset(self, exc: BaseException) -> None:
        self.learning.disable("arena_state_unreadable")
        """A bad file moves aside (kept for a person to read) and the town starts fresh."""
        log.warning("kalshi_arena_state_reset error=%s", type(exc).__name__)
        with contextlib.suppress(OSError):
            os.replace(self.path, self.path.with_name(f"state.json.bad-{int(time.time())}"))

    def _restore(self, raw: Any, now: float) -> None:
        if not isinstance(raw, Mapping) or raw.get("version") != STATE_VERSION:
            raise ValueError("unsupported Kalshi arena state")
        rows = [_clean_row(item) for item in raw["residents"]]
        if sum(row["control"] for row in rows) > 1 or len({row["id"] for row in rows}) != len(rows):
            raise ValueError("one control and unique residents")
        self.next_id = max([int(_number(raw["next_id"]))] + [int(row["id"]) + 1 for row in rows if row["id"].isdigit()])
        self.seq = int(_number(raw.get("seq", 0)))
        rent_day = raw.get("rent_day")
        self.rent_day = None
        if isinstance(rent_day, str) and len(rent_day) == 10:
            date.fromisoformat(rent_day)  # a broken day is a bad file
            self.rent_day = rent_day
        town = raw.get("town") or {}
        for key in self.town:
            if key in town:
                self.town[key] = _number(town[key]) if key == "rent_paid" else int(_number(town[key]))
        self.grave = [row for row in map(_plain, raw.get("grave") or []) if row is not None][:GRAVE_KEEP]
        self.events = [row for row in map(_plain, raw.get("events") or []) if row is not None][:EVENTS_KEEP]
        # Before any event below: a new event's id follows every saved one. A state saved before town_id existed
        # keeps the identity drawn at the start (its resident ids are unchanged, so nothing is renumbered).
        ids = [row["id"] for row in self.events if isinstance(row.get("id"), int) and not isinstance(row["id"], bool)]
        self.next_event = max([int(_number(raw.get("next_event", 1))), 1] + [value + 1 for value in ids])
        saved_town = raw.get("town_id")
        if isinstance(saved_town, str) and len(saved_town) == 12 and set(saved_town) <= set("0123456789abcdef"):
            self.town_id = saved_town
        saved_rule = raw.get("control_rule")
        for row in rows:
            if row["control"] and saved_rule != self.control_rule:
                # The live rules changed: the benchmark's record and every comparison with it start again.
                log.info("kalshi_arena_control_changed old=%s new=%s", saved_rule, self.control_rule)
                # A new benchmark, funded afresh under the same id: ``born`` (the page's funding time) moves to now,
                # so a reader never takes the reset money for a trading result (a "control" event marks it).
                row.update(genes=dict(self.config.control), pnl=[], windows=0, traded=0, wins=0, losses=0,
                           pnl_usd=0.0, equity_usd=float(self.config.start_cash), rent_paid=0.0, born=now,
                           fees_usd=0.0, contracts=0.0, fills=0, funded_usd=float(self.config.start_cash),
                           record_from=now,
                           verdict={"word": "learning", "phrase": PHRASES["learning"], "reason": ""}, day={})
                for other in rows:
                    other["paired"] = {"n": 0, "sum": 0.0, "sumsq": 0.0}
                    if other["since_flag"] is not None:
                        other["since_flag"] = {"n": 0, "sum": 0.0, "sumsq": 0.0}
                self._event(now, row["name"], f"The live rules changed ({saved_rule} -> {self.control_rule}): the "
                            "control's record and every comparison start again.", "neutral", "control", row["id"])
            elif row["control"]:
                row["genes"] = dict(self.config.control)
        saved_regime = raw.get("regime")
        if saved_regime != self.regime:
            # The limits every resident shares changed (a doubled budget, say): every record was earned under other
            # rules, so each verdict and comparison starts again (deskguard judges the CURRENT rule only). Money,
            # rent and lifetime counts stay.
            log.info("kalshi_arena_regime_changed old=%s new=%s", saved_regime, self.regime)
            for row in rows:
                row.update(pnl=[], verdict={"word": "learning", "phrase": PHRASES["learning"], "reason": ""},
                           paired={"n": 0, "sum": 0.0, "sumsq": 0.0}, candidate_now=False, record_from=now)
                if row["since_flag"] is not None:
                    row["since_flag"] = {"n": 0, "sum": 0.0, "sumsq": 0.0}
            self._event(now, "Town", f"The shared live limits changed ({saved_regime} -> {self.regime}): every "
                        "verdict and comparison starts again; money stays.", "neutral", "control")
        today = _day(now)
        for row in rows:
            res = Resident(row, self._desk(row["genes"]))
            if row["day"].get("day") == today:
                res.desk.days.setdefault(today, {})["pnl_usd"] = float(row["day"]["pnl_usd"])
            self.residents[row["id"]] = res
        control = self._control()
        if control is not None:
            self.control_verdict = str(control.row["verdict"].get("word", ""))
        # A window that had started at the last save was open across the restart: void for everyone (fresh desks,
        # equal for all), counted once here. One that had not started yet is joined as usual; one that started while
        # the town was down is voided (and counted) when the market lists it (_windows).
        for entry in raw.get("active_windows") or []:
            slug, start = (entry, -math.inf) if isinstance(entry, str) else (entry[0], _number(entry[1]))
            if isinstance(slug, str) and start < now:
                self.skipped.append(slug)
                self.town["void_windows"] += 1


# ---------------------------------------------------------------------- the town's process
def _harden() -> None:
    """Best effort, before any work: the idle scheduling class (it never takes a CPU from a normal process, the live
    desk's; plus the lowest nice value), first in line for the out-of-memory killer, a memory limit, no core dump
    (its working directory is DATA_DIR, the live desk's volume, and a dump could be up to the memory limit), and
    Ctrl-C ignored (the town follows its socket, not a terminal). Each step fails silently here; what took effect is
    read back and logged once by :func:`report_hardening`."""
    with contextlib.suppress(Exception):
        os.nice(19)
    with contextlib.suppress(Exception):
        os.sched_setscheduler(0, os.SCHED_IDLE, os.sched_param(0))
    with contextlib.suppress(Exception):
        Path("/proc/self/oom_score_adj").write_text("1000", encoding="ascii")
    with contextlib.suppress(Exception):
        import resource

        _soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        if hard == resource.RLIM_INFINITY or hard > MEMORY_BYTES:
            resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, hard))
    with contextlib.suppress(Exception):
        import resource

        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    with contextlib.suppress(Exception):
        signal.signal(signal.SIGINT, signal.SIG_IGN)


def report_hardening() -> dict[str, Any]:
    """What the town's process actually runs with, read back after :func:`_harden` (a runtime may refuse any step,
    and _harden cannot say so): ``nice``, ``sched`` ("idle" or "other"), ``as_limit_bytes`` (its address-space
    limit; None without one) and ``oom_score_adj``, each None when it cannot be read, and ``applied`` (all four as
    _harden asks). Logged once (``kalshi_arena_hardened``; WARNING when the town competes for the CPU at normal
    priority) and carried in the panel's ``feed.hardening``."""
    def read(get: Callable[[], Any]) -> Any:
        try:
            return get()
        except Exception:  # noqa: BLE001 - unknown, shown as such
            return None

    import resource

    nice = read(lambda: int(os.getpriority(os.PRIO_PROCESS, 0)))
    policy = read(lambda: os.sched_getscheduler(0))
    idle = getattr(os, "SCHED_IDLE", None)
    sched = None if policy is None else "idle" if idle is not None and policy == idle else "other"
    soft = read(lambda: resource.getrlimit(resource.RLIMIT_AS)[0])
    limit = None if soft is None or soft == resource.RLIM_INFINITY else int(soft)
    oom = read(lambda: int(Path("/proc/self/oom_score_adj").read_text(encoding="ascii").strip()))
    report = {"nice": nice, "sched": sched, "as_limit_bytes": limit, "oom_score_adj": oom,
              "applied": (nice is not None and nice >= 19 and sched == "idle" and limit is not None
                          and limit <= MEMORY_BYTES and oom == 1000)}
    cpu_ok = nice is not None and nice >= 19 and sched == "idle"
    log.log(logging.INFO if cpu_ok else logging.WARNING,
            "kalshi_arena_hardened nice=%s sched=%s as_limit=%s oom_score_adj=%s applied=%s%s", nice, sched,
            "unlimited" if limit is None and soft is not None else limit, oom, report["applied"],
            "" if cpu_ok else " (the town competes for the CPU at normal priority; the live desk may feel it)")
    return report


def _alarm(seconds: int) -> None:
    """The town's two watchdogs, re-armed before every pass (``0`` clears both). Neither has a handler, so the
    kernel ends the process: the wall-clock alarm (SIGALRM) after ``seconds``, and a CPU budget (ITIMER_VIRTUAL,
    SIGVTALRM) after :data:`PASS_CPU_S` of the process's own CPU time. A spinning pass dies after 5 s of a core, not
    two minutes of it (SCHED_IDLE does not exempt CPU from a container's quota, which throttles the live loop too);
    a town that is only starved of CPU spends none and is ended by neither before :data:`HANG_S`."""
    signal.alarm(seconds)
    signal.setitimer(signal.ITIMER_VIRTUAL, PASS_CPU_S if seconds else 0.0)


def serve(fd: int, *, clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep,
          alarm: Callable[[int], Any] = _alarm, hardening: Mapping[str, Any] | None = None) -> int:
    """Run the town on the frames read from ``fd`` until the link closes it: 0 after the final save,
    :data:`EXIT_HALTED` after :data:`HALT_AFTER` failed passes in a row, 2 without a configuration,
    :data:`EXIT_BUSY` when another town already runs on the same DATA_DIR (:func:`_town_lock`). Each pass
    sleeps on its own timer, takes what arrived, then runs; a pass (or anything else) that hangs for :data:`HANG_S`,
    or spends :data:`PASS_CPU_S` of CPU, is killed by the kernel (:func:`_alarm`). Frames that arrive with the
    configuration (the link's first flush lands while the town is still importing; it carries the window list and
    whole ladders) are kept and read before the first pass, never dropped."""
    reader = FrameReader(fd)
    deadline = clock() + 60.0
    config: ArenaConfig | None = None
    early: list[Any] = []
    while config is None:
        alarm(HANG_S)
        for message in reader.drain():
            if config is None and isinstance(message, tuple) and len(message) == 2 and message[0] == "config":
                config = config_from_wire(message[1])
            else:
                early.append(message)
        if config is None:
            if reader.eof or clock() > deadline:
                log.warning("kalshi_arena_no_config")
                return 2
            sleep(0.05)
    lock = _town_lock(Path(config.data_dir) / "kalshi_arena", clock=clock, sleep=sleep)
    if isinstance(lock, int):
        return lock
    with lock:
        return _serve(reader, config, clock=clock, sleep=sleep, alarm=alarm, early=early, hardening=hardening)


def _town_lock(directory: Path, *, clock: Callable[[], float], sleep: Callable[[float], None]) -> Any:
    """One town per DATA_DIR: an exclusive lock held for the process's life (the kernel drops it at any exit). A
    second town (a wedged one outliving its bot outside a container, or a second bot on the same volume whose live
    desk its controller lock refused) waits :data:`LOCK_WAIT_S` for it (an old town's final save after a quick
    restart), then exits with :data:`EXIT_BUSY` and never writes. Returns the open lock file, or the exit code."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        stream = (directory / "town.lock").open("a", encoding="utf-8")
    except OSError as exc:
        log.error("kalshi_arena_halted error=%s (no town lock)", type(exc).__name__)
        return EXIT_HALTED
    deadline = clock() + LOCK_WAIT_S
    while True:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return stream
        except OSError:
            if clock() >= deadline:
                stream.close()
                log.warning("kalshi_arena_busy (another town holds this DATA_DIR; this one exits without writing)")
                return EXIT_BUSY
            sleep(0.1)


def _serve(reader: FrameReader, config: ArenaConfig, *, clock: Callable[[], float], sleep: Callable[[float], None],
           alarm: Callable[[int], Any], early: Sequence[Any] = (), hardening: Mapping[str, Any] | None = None) -> int:
    view = WireView()
    arena = KalshiArena(config, lambda: view, clock=clock)
    arena.hardening = None if hardening is None else dict(hardening)
    log.info("kalshi_arena_town pid=%d residents=%d control_rule=%s regime=%s (practice only)", os.getpid(),
             len(arena.residents), arena.control_rule, arena.regime)
    failures = 0
    last = clock()
    backlog = list(early)  # frames that came with the configuration: read first, in order
    while not reader.eof or backlog:
        alarm(HANG_S)
        sleep(max(0.0, POLL_S - (clock() - last)))
        last = clock()
        failed: Exception | None = None
        messages, backlog = backlog, []
        try:
            messages += reader.drain()
        except Exception as exc:  # noqa: BLE001 - a broken stream fails the pass (and the next, and halts)
            failed = exc
        for message in messages:
            try:
                arena.receive(message, view)
            except Exception as exc:  # noqa: BLE001 - one bad frame fails this pass; the others still count
                failed = exc
        try:
            arena.step(clock())
        except Exception as exc:  # noqa: BLE001 - the town halts itself; the live desk never notices
            failed = exc
        if failed is None:
            failures = 0
            continue
        failures += 1
        arena.errors += 1
        log.warning("kalshi_arena_step_failed error=%s", type(failed).__name__)
        if failures >= HALT_AFTER:
            arena._halt(failed)
            alarm(0)
            return EXIT_HALTED
    alarm(0)
    try:
        arena._save(clock())
    except Exception as exc:  # noqa: BLE001 - shutting down; the previous save stands
        log.warning("kalshi_arena_save_failed error=%s", type(exc).__name__)
    log.info("kalshi_arena_stopped windows=%d void=%d", arena.town["windows"], arena.town["void_windows"])
    return 0


def worker_main() -> int:
    """The town's process entry point (:func:`worker_command`): the link's socket is the last argument."""
    _harden()
    from .logging_setup import setup_logging

    setup_logging("INFO")
    return serve(int(sys.argv[-1]), hardening=report_hardening())


# ---------------------------------------------------------------------- the panel
def panel_state(data_dir: Path | str, now: float) -> dict[str, Any]:
    """What the page shows (its top-level ``kalshi_arena``), from ``panel.json`` only (never the larger state file).
    The page builder runs in the live desk's process, so a file over :data:`PANEL_MAX_BYTES` is refused unread."""
    path = Path(data_dir) / "kalshi_arena" / "panel.json"
    if path.stat().st_size > PANEL_MAX_BYTES:
        raise ValueError("Kalshi arena panel too large")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("label") != LABEL:
        raise ValueError("Invalid Kalshi arena panel")
    return raw
