"""Read-only public Kalshi recorder for Family A and the KXBTC15M arena (PROTOCOL.md sections 3 and 16).

Run it as its own process or service::

    python -m nightcrawler.kalshi_recorder run            # DATA_DIR/kalshi_recorder/
    python -m nightcrawler.kalshi_recorder status         # storage, lanes, coverage
    python -m nightcrawler.kalshi_recorder verify         # re-hash every sealed segment

or inside the bot with ``KALSHI_RECORDER_ENABLED=true`` (OFF by default; the bot's IP and volume are
already busy, so a separate service is recommended). Inside the bot it refuses to start while any desk runs
live (``*_MODE=live``) and runs a reduced profile (0.25 request/s, no KXBTC15M lane, 1 GiB free-disk floor).
As its own service, ``run`` refuses to start when trading keys or live switches are present in its
environment (names are checked, values never read), so a copy of the bot's service cannot become a second
bot by accident. It sends only public, unauthenticated GETs from
the allowlist in ``kalshi_public`` (no key, no signer, no websocket to Kalshi), keeps every lane inside
one shared budget of at most 2 request starts per rolling second (1.5/s target), and records:

* market discovery with every admission and exclusion and its reason (the protocol's rules, with the
  wider 5 h - 8 d recording window; the fee rule is applied later by the replay);
* full-depth order books from ``/markets/orderbooks`` (100 per call; the current and next KXBTC15M
  windows ride in every call), each with its request and receive time and a local sequence number;
  a book is written in full when it changed and listed as "unchanged" when it did not;
* the exchange-wide trade tape every 5 s with a 5 s overlap, kept for candidates and KXBTC15M, with
  Kalshi's ``created_time``; gaps are backfilled from the public tape and otherwise left as gaps;
* market rules, fee terms and fee changes, quote sweeps every 5 minutes, settlement rows until each
  market is finalized, the historical cutoff and incentive programs (recorded, never credited);
* optionally (``KALSHI_RECORDER_SPOT_TICKS=true``, off by default) Coinbase and Kraken BTC trades from
  their public websockets; these are exchange spot prices, not the CF Benchmarks settlement index.

Missing data stays missing: failures, 429s, restarts, stale lanes and clock steps are written as gap
records, and an hourly coverage manifest lists coverage, request latency, 429s and segment hashes.
A malformed reply or a request the transport refuses is retried at most ``PAGE_ATTEMPTS`` times and then
dropped with a gap; no single reply can stop the recorder or wedge a lane.
There is no order, cancel, amend, portfolio or account call anywhere in this module.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import math
import os
import re
import sys
import threading
import time
import uuid
from collections import Counter, OrderedDict, deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, fields, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import __version__
from .config import ConfigError, parse_dotenv
from .kalshi_familya_universe import (
    OPEN_CATEGORIES,
    RECORDER_WINDOW,
    admit,
    dec,
    ts,
)
from .kalshi_public import Fetched, PublicKalshi, RateLimiter, public_ticker
from .kalshi_recorder_store import (
    LEVEL_PAUSED,
    RecorderStore,
    atomic_json,
    file_sha256,
    load_index,
)

log = logging.getLogger("nightcrawler.kalshi_recorder")
BTC15M = "KXBTC15M"
BOOKS_PER_CALL = 100
TICKERS_PER_SWEEP = 300
# Kalshi answered 414 for a 10.2 KB /markets?tickers= URL and 200 for 6.6 KB (2026-10-13); the encoded
# tickers value of one sweep or settlement call stays under this, and a 4xx halves the chunk.
SWEEP_QUERY_BYTES = 5000
FAVOURITE_BAND = (Decimal("0.45"), Decimal("0.97"))
FAST_BOOK_S, SLOW_BOOK_S = 20.0, 60.0
TRADE_OVERLAP_S = 5
LIVE_TRADE_SPAN_S = 60  # an older backlog goes to the backfill lane, so live polls stay small
LIVE_TRADE_PAGES = 20
BACKFILL_PAGES = 3000
PAGE_ATTEMPTS = 5
DEDUP_MEMORY = 50_000
SETTLEMENT_GIVE_UP_S = 45 * 86400.0
UNWATCHED_MEMORY_S = 4 * 86400.0  # a ticker's prints are kept for windows that began before its watch stopped
RETRY_AFTER_GAP_S = 60.0
IN_BOT_RATE_PER_S = 0.25
IN_BOT_MIN_FREE_MB = 1024
# A copy of the bot's service carries these; the standalone recorder refuses to start next to them.
TRADING_SECRET_NAMES = frozenset({"KALSHI_KEY_ID", "KALSHI_PRIVATE_KEY", "BOT_WALLET_SECRET"})
TRADING_SECRET_PREFIXES = ("POLYMARKET_US_",)
DYNAMIC_FIELDS = frozenset({
    "yes_bid_dollars", "yes_ask_dollars", "no_bid_dollars", "no_ask_dollars", "yes_bid_size_fp",
    "yes_ask_size_fp", "last_price_dollars", "previous_price_dollars", "previous_yes_bid_dollars",
    "previous_yes_ask_dollars", "volume_fp", "volume_24h_fp", "open_interest_fp", "updated_time",
    "liquidity_dollars", "status",
})
COINBASE_WS = "wss://advanced-trade-ws.coinbase.com"
KRAKEN_WS = "wss://ws.kraken.com/v2"


# =========================================================================== settings
def _bool(raw: str) -> bool:
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on", "y"):
        return True
    if value in ("0", "false", "no", "off", "n"):
        return False
    raise ValueError("must be true or false")


@dataclass(frozen=True)
class RecorderSettings:
    """``KALSHI_RECORDER_<FIELD>`` environment variables (``data_dir`` is ``DATA_DIR``)."""

    data_dir: Path = Path("./data")
    enabled: bool = False
    max_storage_mb: int = 2048
    min_free_mb: int = 256
    storage_policy: str = "protect"
    release_before: str = ""
    rate_per_s: float = 1.5
    book_interval_s: float = 1.0
    trade_interval_s: float = 5.0
    sweep_interval_s: float = 300.0
    discovery_interval_s: float = 3600.0
    settlement_interval_s: float = 900.0
    btc15m: bool = True
    btc15m_retention_h: float = 72.0
    spot_ticks: bool = False
    max_candidates: int = 4000
    host_label: str = "auto"

    def problems(self) -> list[str]:
        out: list[str] = []
        limits: dict[str, tuple[float, float]] = {
            "max_storage_mb": (64, 1_000_000), "min_free_mb": (0, 1_000_000), "rate_per_s": (0.05, 2.0),
            "book_interval_s": (0.5, 600), "trade_interval_s": (1, 60), "sweep_interval_s": (60, 3600),
            "discovery_interval_s": (600, 86400), "settlement_interval_s": (60, 3600),
            "btc15m_retention_h": (1, 24 * 365), "max_candidates": (1, 20_000),
        }
        for name, (lo, hi) in limits.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                out.append(f"KALSHI_RECORDER_{name.upper()} must be a finite number")
            elif not lo <= value <= hi:
                out.append(f"KALSHI_RECORDER_{name.upper()}={value} must be between {lo} and {hi}")
        if self.storage_policy not in ("protect", "rotate"):
            out.append("KALSHI_RECORDER_STORAGE_POLICY must be protect or rotate")
        if self.release_before and _release_ts(self.release_before) is None:
            out.append("KALSHI_RECORDER_RELEASE_BEFORE must be a date like 2026-12-31 (or empty)")
        if self.host_label not in ("auto", "workspace", "railway") and not re.fullmatch(r"[a-z0-9_-]{1,32}",
                                                                                         self.host_label):
            out.append("KALSHI_RECORDER_HOST_LABEL must be auto, workspace, railway or a short lowercase label")
        return out

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> RecorderSettings:
        env = os.environ if env is None else env
        kwargs: dict[str, Any] = {}
        problems: list[str] = []
        for item in fields(cls):
            name = "DATA_DIR" if item.name == "data_dir" else f"KALSHI_RECORDER_{item.name.upper()}"
            raw = env.get(name)
            if raw is None or not str(raw).strip():
                continue
            text = str(raw).strip()
            try:
                if item.name == "data_dir":
                    kwargs[item.name] = Path(text)
                elif item.type in ("bool", bool):
                    kwargs[item.name] = _bool(text)
                elif item.type in ("int", int):
                    kwargs[item.name] = int(text)
                elif item.type in ("float", float):
                    kwargs[item.name] = float(text)
                else:
                    kwargs[item.name] = text
            except ValueError as exc:
                problems.append(f"{name}: {exc}")
        if problems:
            raise ConfigError(problems)
        settings = cls(**kwargs)
        problems = settings.problems()
        if problems:
            raise ConfigError(problems)
        return settings

    @property
    def root(self) -> Path:
        return self.data_dir / "kalshi_recorder"

    def in_bot(self) -> RecorderSettings:
        """The reduced profile inside the bot's process: it shares the bot's IP, CPU and volume."""
        return replace(self, rate_per_s=min(self.rate_per_s, IN_BOT_RATE_PER_S), btc15m=False,
                       min_free_mb=max(self.min_free_mb, IN_BOT_MIN_FREE_MB))

    def host(self, env: Mapping[str, str] | None = None) -> str:
        if self.host_label != "auto":
            return self.host_label
        env = os.environ if env is None else env
        return "railway" if any(key in env for key in ("RAILWAY_ENVIRONMENT_NAME", "RAILWAY_SERVICE_ID")) else "workspace"


def _release_ts(value: str) -> float | None:
    try:
        return datetime.combine(date.fromisoformat(value), datetime.min.time(), UTC).timestamp()
    except ValueError:
        return None


def _wanted(name: str) -> bool:
    return name == "DATA_DIR" or name.startswith("KALSHI_RECORDER_") or name.endswith("_MODE")


def process_env(env: Mapping[str, str] | None = None, dotenv: str | None = ".env") -> tuple[dict[str, str], frozenset[str]]:
    """``.env`` overlaid by the real environment (as the bot's config loads them), reduced to what the recorder uses.

    Returns the values of ``DATA_DIR``, ``KALSHI_RECORDER_*`` and every ``*_MODE`` switch, and the set of every
    variable NAME present. No other value is kept.
    """
    real = os.environ if env is None else env
    file = parse_dotenv(dotenv) if dotenv else {}
    values = {name: value for name, value in file.items() if _wanted(name)}
    values.update({name: str(value) for name, value in real.items() if _wanted(name)})
    return values, frozenset(file) | frozenset(real)


def live_modes(values: Mapping[str, str]) -> list[str]:
    """The ``*_MODE`` switches set to live (any desk trading real money in this process)."""
    return sorted(name for name, value in values.items()
                  if name.endswith("_MODE") and str(value).strip().lower() == "live")


def trading_names(names: Iterable[str]) -> list[str]:
    """Names of trading keys present (values are never read)."""
    return sorted(name for name in names if name in TRADING_SECRET_NAMES or name.startswith(TRADING_SECRET_PREFIXES))


def _detail(exc: BaseException) -> str:
    """A short, single-line description of an exception for the logs and gap rows."""
    return " ".join(str(exc).split())[:200]


class Malformed(ValueError):
    """A 200 reply whose shape is not what the public API documents."""


def _rows(body: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    """The object rows of a list field (a missing or null field is empty; anything else is malformed)."""
    value = body.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise Malformed(f"{key} is not a list")
    return [row for row in value if isinstance(row, dict)]


def _cursor(body: Mapping[str, Any], key: str = "cursor") -> str:
    value = body.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise Malformed(f"{key} is not a string")
    return value


def _why(fetched: Fetched) -> str:
    """The HTTP status of a failed reply, or the transport's error when there was no failing status."""
    if fetched.status is not None and fetched.status != 200:
        return str(fetched.status)
    return fetched.error or "unknown"


def _transient(fetched: Fetched) -> bool:
    """A failure that says nothing about this request: no reply, a 429 or a server error."""
    return fetched.status is None or fetched.status == 429 or fetched.status >= 500


# =========================================================================== small helpers
def canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def best_bid(levels: Any) -> Decimal | None:
    """Kalshi lists bids ascending as [price, size] strings; the best bid is the highest with size."""
    best: Decimal | None = None
    for row in levels if isinstance(levels, list) else []:
        if isinstance(row, list) and len(row) == 2:
            price, size = dec(row[0]), dec(row[1])
            if price is not None and size is not None and size > 0 and (best is None or price > best):
                best = price
    return best


def favourite_mid(book: Any) -> Decimal | None:
    """max(m, 1 - m) for the YES mid m = (best YES bid + (1 - best NO bid)) / 2; None when one-sided."""
    if not isinstance(book, Mapping):
        return None
    yes, no = best_bid(book.get("yes_dollars")), best_bid(book.get("no_dollars"))
    if yes is None or no is None:
        return None
    mid = (yes + (1 - no)) / 2
    return max(mid, 1 - mid)


def split_row(row: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    static = {key: value for key, value in row.items() if key not in DYNAMIC_FIELDS}
    return {key: row[key] for key in DYNAMIC_FIELDS if key in row}, canonical_sha(static)


def percentiles(values: Iterable[float]) -> dict[str, float | None]:
    ordered = sorted(values)
    if not ordered:
        return {"n": 0, "p50": None, "p95": None, "p99": None}

    def pick(q: float) -> float:
        return round(ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))], 3)

    return {"n": len(ordered), "p50": pick(0.50), "p95": pick(0.95), "p99": pick(0.99)}


def _event_date_ok(event_ticker: str, series: str, now: float) -> bool:
    """Skip series whose dated events are all far outside the recording window (saves discovery calls)."""
    match = re.match(re.escape(series) + r"-(\d{2})([A-Z]{3})(\d{2})", event_ticker)
    if not match:
        return True
    try:
        day = datetime.strptime("".join(match.groups()), "%y%b%d").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return True
    return now - 2 * 86400 <= day <= now + RECORDER_WINDOW[1] + 2 * 86400


# =========================================================================== state
@dataclass
class Watched:
    ticker: str
    event: str
    series: str
    category: str
    kind: str  # "candidate" (Family A) or "btc15m"
    open_time: float
    close_time: float
    status: str
    added_at: float
    last_book_at: float = -math.inf
    book_sha: str | None = None
    fav: Decimal | None = None
    settled: bool = False

    def book_due(self) -> float:
        if self.fav is None:
            return self.last_book_at
        fast = FAVOURITE_BAND[0] <= self.fav <= FAVOURITE_BAND[1]
        return self.last_book_at + (FAST_BOOK_S if fast else SLOW_BOOK_S)


@dataclass
class Lane:
    name: str
    weight: float
    cadence_s: float
    pass_value: float = 0.0
    backoff_until: float = -math.inf
    in_a_row: int = 0
    last_success_at: float | None = None
    gap_since: float | None = None
    hour: Counter[str] = field(default_factory=Counter)
    rtts: list[float] = field(default_factory=list)


@dataclass
class TradeJob:
    min_ts: int
    max_ts: int
    ticker: str | None
    backfill: bool
    cursor: str = ""
    pages: int = 0
    attempts: int = 0
    seen_cursors: set[str] = field(default_factory=set)
    oldest: float | None = None
    rows: int = 0


@dataclass
class Request:
    lane: str
    path: str
    params: list[tuple[str, Any]]
    context: dict[str, Any] = field(default_factory=dict)


# =========================================================================== the recorder
class Recorder:
    def __init__(self, settings: RecorderSettings, *, client: PublicKalshi | None = None,
                 store: RecorderStore | None = None, wall: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep, env: Mapping[str, str] | None = None) -> None:
        self.settings, self.wall, self.sleep = settings, wall, sleep
        self.root = settings.root
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = store or RecorderStore(
            self.root, max_bytes=settings.max_storage_mb * 1024 * 1024, min_free_bytes=settings.min_free_mb * 1024 * 1024,
            policy=settings.storage_policy, btc15m_retention_s=settings.btc15m_retention_h * 3600.0,
            release_before=_release_ts(settings.release_before) if settings.release_before else None, clock=wall)
        self.client = client or PublicKalshi(RateLimiter(settings.rate_per_s), wall=wall)
        self.host = settings.host(env)
        self.session = uuid.uuid4().hex
        self.started_at = wall()
        self.lanes: dict[str, Lane] = {lane.name: lane for lane in (
            Lane("books", 8, settings.book_interval_s), Lane("trades", 4, settings.trade_interval_s),
            Lane("backfill", 2, 3600), Lane("btc15m_meta", 2, 900), Lane("discovery", 2, settings.discovery_interval_s),
            Lane("sweep", 1, settings.sweep_interval_s), Lane("settlement", 1, settings.settlement_interval_s),
            Lane("fees", 1, 86400), Lane("other", 0.5, 86400))}
        self.virtual = 0.0
        self.watched: dict[str, Watched] = {}
        self.series_rows: dict[str, dict[str, Any]] = {}
        self.series_at: dict[str, float] = {}
        self.decisions: dict[str, tuple[bool, str | None]] = {}
        self.static_sha: dict[str, str] = {}
        self.dedup: OrderedDict[str, str] = OrderedDict()
        self.trade_conflicts = 0
        self.lags: list[float] = []
        # Lane schedules (wall-clock seconds).
        self.next_books_at = -math.inf
        self.next_trades_at = -math.inf
        self.next_sweep_at = wall() + 60
        self.next_settlement_at = wall() + 120
        self.next_btc_meta_at = -math.inf
        self.next_discovery_at = -math.inf
        self.next_series_fees_at = -math.inf
        self.next_other_at = -math.inf
        self.trade_job: TradeJob | None = None
        self.backfill_jobs: deque[TradeJob] = deque()
        self.trade_covered_to: int | None = None
        self.trade_rate = 150.0
        self.discovery: dict[str, Any] | None = None
        self.btc_queue: deque[Request] = deque()
        self.fee_events: dict[str, float] = {}
        self.fee_queue: deque[str] = deque()
        self.other_queue: deque[Request] = deque()
        self.sweep_queue: deque[list[str]] = deque()
        self.settle_queue: deque[list[str]] = deque()
        self.chunk_size = TICKERS_PER_SWEEP  # halved by a 4xx (a URL Kalshi will not take)
        # Failed attempts at each lane's current request: (request key, count). One entry per lane.
        self.strikes: dict[str, tuple[tuple[Any, ...], int]] = {}
        # Recently unwatched tickers -> (kind, stop time): a later backfill of a window from before the stop
        # still keeps their prints, because trade_coverage promises every print of every ticker watched then.
        self.unwatched: dict[str, tuple[str, float]] = {}
        self.fee_retry: dict[str, float] = {}
        self.paused_since: float | None = None
        self.last_minute = -1
        self.hour_started = math.floor(self.started_at / 3600) * 3600
        self.minutes: Counter[str] = Counter()
        self.gaps_this_hour: list[dict[str, Any]] = []
        self.last_wall = self.started_at
        self._restore()

    # ------------------------------------------------------------------ records
    def emit(self, lane: str, kind: str, payload: dict[str, Any], at: float | None = None) -> int | None:
        return self.store.append(lane, kind, {"session": self.session, **payload}, at)

    def gap(self, lane: str, start: float | None, end: float | None, cause: str, **extra: Any) -> None:
        row = {"gap_lane": lane, "from": start, "to": end, "cause": cause, **extra}
        self.gaps_this_hour.append(row)
        self.emit("gaps", "gap", row)
        log.warning("kalshi_recorder_gap lane=%s cause=%s", lane, cause)

    def _state_path(self) -> Path:
        return self.root / "recorder_state.json"

    def _restore(self) -> None:
        path = self._state_path()
        saved: dict[str, Any] = {}
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(saved, dict) or saved.get("version") != 1:
                raise ValueError("Unreadable recorder_state.json; inspect it before recording again")
        now = self.started_at
        self.emit("gaps", "session_started", {"version": __version__, "host": self.host, "read_only": True,
                                               "order_capability": False, "previous": saved.get("session"),
                                               "commit": os.environ.get("RAILWAY_GIT_COMMIT_SHA")})
        for item in self.store.recovered:
            self.gap(item["lane"], item.get("last_at"), now, "restart_partial_segment_recovered",
                     records=item["records"], dropped_bytes=item["dropped_bytes"])
        if saved.get("last_alive_at"):
            self.gap("all", float(saved["last_alive_at"]), now, "recorder_not_running")
        for row in saved.get("watched") or []:
            restored = Watched(**row)
            self.watched[restored.ticker] = restored
        self.fee_events = {str(key): float(value) for key, value in (saved.get("fee_events") or {}).items()}
        self.unwatched = {str(ticker): (str(kind), float(at)) for ticker, (kind, at) in
                          (saved.get("unwatched") or {}).items() if now - float(at) <= UNWATCHED_MEMORY_S}
        if self.watched:
            self.emit("admissions", "watch", {"action": "resumed", "tickers": sorted(self.watched)})
        covered = saved.get("trade_covered_to")
        if isinstance(covered, int) and now - covered <= 3 * 86400:
            # The public tape keeps history: queue the downtime for backfill instead of calling it lost.
            self.trade_covered_to = covered
        elif isinstance(covered, int):
            self.gap("trades", covered, now, "downtime_too_long_to_backfill")
        self._save_state(now)

    def _save_state(self, now: float) -> None:
        watched = [{"ticker": item.ticker, "event": item.event, "series": item.series, "category": item.category,
                    "kind": item.kind, "open_time": item.open_time, "close_time": item.close_time,
                    "status": item.status, "added_at": item.added_at} for item in self.watched.values()]
        atomic_json(self._state_path(), {"version": 1, "session": self.session, "last_alive_at": now,
                                         "trade_covered_to": self.trade_covered_to, "started_at": self.started_at,
                                         "watched": watched, "fee_events": self.fee_events,
                                         "unwatched": {ticker: list(item) for ticker, item in self.unwatched.items()}})

    # ------------------------------------------------------------------ scheduling
    def _planners(self) -> dict[str, Callable[[float], Request | None]]:
        return {"books": self._plan_books, "trades": self._plan_trades, "backfill": self._plan_backfill,
                "btc15m_meta": self._plan_btc_meta, "discovery": self._plan_discovery, "sweep": self._plan_sweep,
                "settlement": self._plan_settlement, "fees": self._plan_fees, "other": self._plan_other}

    def step(self, stop: threading.Event | None = None) -> bool:
        """Housekeeping, then at most one public GET; False when nothing was due."""
        now = self.wall()
        self._housekeeping(now)
        if self.store.level == LEVEL_PAUSED:
            return False
        ready: list[tuple[Lane, Request]] = []
        for name, plan in self._planners().items():
            lane = self.lanes[name]
            if lane.backoff_until > now:
                continue
            request = plan(now)
            if request is not None:
                lane.pass_value = max(lane.pass_value, self.virtual)
                ready.append((lane, request))
        if not ready:
            return False
        lane, request = min(ready, key=lambda pair: (pair[0].pass_value, -pair[0].weight))
        self.virtual = lane.pass_value
        lane.pass_value += 1.0 / lane.weight
        try:
            fetched = self.client.get(request.lane, request.path, request.params, stop)
        except (ValueError, TypeError) as exc:  # the transport refused it (path or parameter): never sent
            self._refused(request, now, exc)
            return True
        if fetched.error == "stopped":
            return False
        self._account(lane, fetched)
        handler = getattr(self, f"_done_{request.lane}")
        try:
            handler(request, fetched)
        except Exception as exc:  # noqa: BLE001 - a malformed reply becomes a recorded failure, never a crash
            self._handler_failed(request, fetched, exc)
        return True

    # ------------------------------------------------------------------ failures that are not HTTP errors
    @staticmethod
    def _key(request: Request) -> tuple[Any, ...]:
        return (request.path, tuple((name, str(value)) for name, value in request.params))

    def _strike(self, request: Request) -> bool:
        """Count one failed attempt at this lane's current request; True once it failed ``PAGE_ATTEMPTS`` times."""
        key = self._key(request)
        last, count = self.strikes.get(request.lane, ((), 0))
        count = count + 1 if last == key else 1
        if count >= PAGE_ATTEMPTS:
            self.strikes.pop(request.lane, None)
            return True
        self.strikes[request.lane] = (key, count)
        return False

    def _accepted(self, request: Request) -> None:
        self.strikes.pop(request.lane, None)

    def _handler_failed(self, request: Request, fetched: Fetched, exc: Exception) -> None:
        """A reply that could not be processed: recorded, retried at most PAGE_ATTEMPTS times, then dropped."""
        cause = "malformed_reply" if isinstance(exc, Malformed) else f"handler_error_{type(exc).__name__}"
        with_detail = {"handler_lane": request.lane, "error": type(exc).__name__, "detail": _detail(exc),
                       "path": request.path, "received_at": fetched.received_at}
        try:
            self.emit("gaps", "handler_error", with_detail)
        except Exception as again:  # noqa: BLE001 - the record itself must never be the next crash
            log.warning("kalshi_recorder_handler_error_unrecorded error=%s", type(again).__name__)
        log.warning("kalshi_recorder_handler_error lane=%s error=%s detail=%s", request.lane, type(exc).__name__,
                    _detail(exc))
        if request.lane in ("trades", "backfill"):
            job: TradeJob = request.context["job"]
            job.attempts += 1
            if job.attempts >= PAGE_ATTEMPTS:
                self._abandon(job, request.lane == "backfill", cause)
        elif self._strike(request):
            self._give_up(request, fetched.received_at, cause)

    def _refused(self, request: Request, now: float, exc: Exception) -> None:
        """The transport refused to send a request (not a public path or parameter): drop it with a gap at once."""
        self.emit("gaps", "request_refused", {"handler_lane": request.lane, "error": type(exc).__name__,
                                              "detail": _detail(exc), "path": request.path})
        log.warning("kalshi_recorder_request_refused lane=%s error=%s detail=%s", request.lane,
                    type(exc).__name__, _detail(exc))
        self._give_up(request, now, f"request_refused_{type(exc).__name__}")

    def _give_up(self, request: Request, at: float, cause: str) -> None:
        """Drop this lane's current request with a gap, so the lane moves on (never retried forever)."""
        lane = request.lane
        self.strikes.pop(lane, None)
        if lane in ("trades", "backfill"):
            self._abandon(request.context["job"], lane == "backfill", cause)
        elif lane == "discovery":
            self._skip_discovery(request, at, cause)
        elif lane in ("sweep", "settlement"):
            chunks = self.sweep_queue if lane == "sweep" else self.settle_queue
            if chunks and chunks[0] == request.context["tickers"]:
                chunks.popleft()
            self.gap(lane, at, at, cause, tickers=len(request.context["tickers"]))
        elif lane == "fees":
            event = request.context.get("event")
            if request.context["step"] == "series":
                self.next_series_fees_at = at + 3600  # try the series list again in an hour
            elif isinstance(event, str):
                if self.fee_queue and self.fee_queue[0] == event:
                    self.fee_queue.popleft()
                self.fee_retry[event] = at + 3600
            self.gap("fees", at, at, cause, step=request.context["step"], event=event)
        elif lane in ("btc15m_meta", "other"):
            queue = self.btc_queue if lane == "btc15m_meta" else self.other_queue
            if queue and queue[0] is request:
                queue.popleft()
            self.gap(lane, at, at, cause, path=request.path)
        else:  # books: the next call is already scheduled
            self.gap(lane, at, at, cause, path=request.path)

    def _account(self, lane: Lane, fetched: Fetched) -> None:
        self.emit("requests", "request", fetched.log_row(), fetched.received_at)
        lane.hour["requests"] += 1
        lane.rtts.append(fetched.rtt_ms)
        if fetched.ok:
            lane.hour["ok"] += 1
            lane.in_a_row = 0
            lane.last_success_at = fetched.received_at
            if lane.gap_since is not None:
                self.gap(lane.name, lane.gap_since, fetched.received_at, "lane_stale_recovered")
                lane.gap_since = None
            return
        lane.in_a_row += 1
        if fetched.status == 429:
            lane.hour["429"] += 1
            log.warning("kalshi_recorder_429 lane=%s in_a_row=%d", lane.name, lane.in_a_row)
        else:
            lane.hour["errors"] += 1
        wait = min(30.0, 2.0 ** lane.in_a_row)
        if fetched.retry_after_s is not None:
            wait = max(wait, fetched.retry_after_s)  # clamped to 15 minutes by the transport
            if fetched.retry_after_s >= RETRY_AFTER_GAP_S:
                # A long Retry-After holds every lane: that is missing data, so it is a gap, never silent.
                self.gap("all", fetched.received_at, fetched.received_at + fetched.retry_after_s,
                         "retry_after_hold", seconds=fetched.retry_after_s, request_lane=lane.name)
        lane.backoff_until = fetched.received_at + wait

    # ------------------------------------------------------------------ housekeeping
    def _housekeeping(self, now: float) -> None:
        if now < self.last_wall - 1.0:
            self.gap("all", now, self.last_wall, "clock_moved_backwards")
        self.last_wall = max(self.last_wall, now)
        minute = int(now // 60)
        if minute == self.last_minute:
            return
        self.last_minute = minute
        self.store.seal_hour(now)  # first, so the finished hour's segments (and hashes) are in its manifest
        if now >= self.hour_started + 3600:
            self.write_manifest(self.hour_started, self.hour_started + 3600)
            self.hour_started = math.floor(now / 3600) * 3600
        level_before = self.store.level
        status = self.store.enforce()
        if status.level != level_before:
            # Shedding stops KXBTC15M/spot capture; a pause stops everything. Both are gaps, never silent.
            if status.level == LEVEL_PAUSED:
                self.paused_since = now
                log.error("kalshi_recorder_paused reason=storage_cap used=%d cap=%d", status.used_bytes, status.cap_bytes)
                self.gaps_this_hour.append({"gap_lane": "all", "from": now, "to": None, "cause": "storage_cap_paused"})
            else:
                if self.paused_since is not None:
                    self.gap("all", self.paused_since, now, "storage_cap_paused", used_bytes=status.used_bytes)
                    self.paused_since = None
                cause = "storage_soft_cap_shed_btc15m_and_spot" if status.level else "storage_ok"
                self.gap("btc15m", now if status.level else None, None if status.level else now, cause,
                         used_bytes=status.used_bytes, deleted=status.reasons)
        live_events = {item.event for item in self.watched.values() if item.kind == "candidate"}
        for event, at in self.fee_events.items():
            if now - at >= 86400 and event in live_events and event not in self.fee_queue:
                self.fee_queue.append(event)
        for event, at in list(self.fee_retry.items()):
            if event not in live_events:
                self.fee_retry.pop(event)
            elif now >= at:
                self.fee_retry.pop(event)
                if event not in self.fee_queue:
                    self.fee_queue.append(event)
        self.fee_events = {event: at for event, at in self.fee_events.items() if event in live_events}
        self.unwatched = {ticker: item for ticker, item in self.unwatched.items()
                          if now - item[1] <= UNWATCHED_MEMORY_S}
        for lane in self.lanes.values():
            if (lane.last_success_at is not None and lane.gap_since is None
                    and now - lane.last_success_at > max(2 * lane.cadence_s, 30)
                    and lane.name in ("books", "trades")):
                lane.gap_since = lane.last_success_at
                self.gap(lane.name, lane.last_success_at, None, "lane_stale")
        self._sample_coverage(now)
        self._save_state(now)
        self._write_status(now, status.used_bytes)

    def _sample_coverage(self, now: float) -> None:
        candidates = [item for item in self.watched.values() if item.kind == "candidate" and item.close_time > now]
        self.minutes["minutes"] += 1
        self.minutes["candidate_minutes"] += len(candidates)
        self.minutes["book_fresh_minutes"] += sum(1 for item in candidates if now - item.last_book_at <= 120)
        tape = self.trade_covered_to is not None and now - self.trade_covered_to <= 120  # section 12: last 120 s
        self.minutes["trade_tape_minutes"] += int(tape)
        btc = [item for item in self.watched.values() if item.kind == "btc15m" and item.open_time <= now < item.close_time]
        self.minutes["btc15m_minutes"] += int(bool(btc))
        self.minutes["btc15m_fresh_minutes"] += int(bool(btc) and all(now - item.last_book_at <= 5 for item in btc))

    def write_manifest(self, start: float, end: float, *, partial: bool = False) -> Path:
        """The hourly coverage manifest: coverage, latency, 429s, gaps and the segments sealed this hour."""
        hour = datetime.fromtimestamp(start, UTC).strftime("%Y-%m-%dT%H")
        directory = self.root / "manifests"
        directory.mkdir(parents=True, exist_ok=True)
        segments = [segment.__dict__ for segment in load_index(self.root)
                    if segment.first_at < end and segment.last_at >= start]
        minutes = dict(self.minutes)
        candidate_minutes = minutes.get("candidate_minutes", 0)
        manifest = {
            "schema": 1, "hour": hour, "from": start, "to": end, "partial": partial, "host": self.host,
            "session_started_at": self.started_at,
            "session": self.session, "version": __version__, "commit": os.environ.get("RAILWAY_GIT_COMMIT_SHA"),
            "read_only": True, "order_capability": False,
            "coverage": {
                "minutes_sampled": minutes.get("minutes", 0),
                "candidate_book_fresh_share": round(minutes.get("book_fresh_minutes", 0) / candidate_minutes, 4)
                if candidate_minutes else None,
                "trade_tape_minutes": minutes.get("trade_tape_minutes", 0),
                "btc15m_minutes": minutes.get("btc15m_minutes", 0),
                "btc15m_fresh_minutes": minutes.get("btc15m_fresh_minutes", 0),
                "candidates_now": sum(1 for item in self.watched.values() if item.kind == "candidate"),
                "trade_covered_to": self.trade_covered_to, "backfill_jobs_pending": len(self.backfill_jobs),
            },
            "lanes": {name: {**dict(lane.hour), "rtt_ms": percentiles(lane.rtts)} for name, lane in self.lanes.items()},
            "trade_receive_lag_s": percentiles(self.lags),
            "trade_conflicts": self.trade_conflicts,
            "gaps": self.gaps_this_hour,
            "storage": {"used_bytes": self.store.used_bytes(), "cap_bytes": self.store.max_bytes,
                        "level": self.store.level, "policy": self.store.policy,
                        "deleted_segments": self.store.deleted_segments},
            "segments": segments,
        }
        # A session that stops mid-hour keeps its own partial file; the next session cannot overwrite it.
        name = f"coverage-{hour}-{self.session[:8]}-partial.json" if partial else f"coverage-{hour}.json"
        path = directory / name
        atomic_json(path, manifest)
        self.emit("telemetry", "coverage_manifest", {"hour": hour, "path": str(path.relative_to(self.root)),
                                                    "sha256": file_sha256(path)})
        for lane in self.lanes.values():
            lane.hour.clear()
            lane.rtts.clear()
        self.lags.clear()
        self.minutes.clear()
        self.gaps_this_hour = []
        return path

    def _write_status(self, now: float, used: int) -> None:
        atomic_json(self.root / "status.json", {
            "as_of": now, "started_at": self.started_at, "host": self.host, "session": self.session,
            "version": __version__, "read_only": True, "order_capability": False, "storage_level": self.store.level,
            "used_bytes": used, "cap_bytes": self.store.max_bytes,
            "candidates": sum(1 for item in self.watched.values() if item.kind == "candidate"),
            "btc15m_windows": sorted(item.ticker for item in self.watched.values() if item.kind == "btc15m"),
            "trade_covered_to": self.trade_covered_to,
            "lanes": {name: {"last_success_at": lane.last_success_at, "backoff_until": lane.backoff_until
                             if math.isfinite(lane.backoff_until) else None, "stale_since": lane.gap_since}
                      for name, lane in self.lanes.items()},
        })

    # ------------------------------------------------------------------ books
    def _plan_books(self, now: float) -> Request | None:
        if now < self.next_books_at:
            return None
        btc: list[Watched] = []
        if self.settings.btc15m and self.store.lane_allowed("books_btc15m"):
            btc = sorted((item for item in self.watched.values()
                          if item.kind == "btc15m" and item.close_time > now and item.open_time <= now + 900),
                         key=lambda item: item.open_time)[:2]
        pool = sorted((item for item in self.watched.values()
                       if item.kind == "candidate" and item.close_time > now and item.status == "active"),
                      key=lambda item: (item.book_due(), item.ticker))
        room = BOOKS_PER_CALL - len(btc)
        due = [item for item in pool if item.book_due() <= now][:room]
        if not btc and not due:
            return None
        if btc:  # the call happens anyway: spare slots refresh the soonest-due books for free
            chosen = {item.ticker for item in due}
            due += [item for item in pool if item.ticker not in chosen][:room - len(due)]
        tickers = [item.ticker for item in btc + due]
        return Request("books", "/markets/orderbooks", [("tickers", ticker) for ticker in tickers],
                       {"tickers": tickers})

    def _done_books(self, request: Request, fetched: Fetched) -> None:
        tickers: list[str] = request.context["tickers"]
        # Scheduled from the call actually made: a planned call that lost its turn keeps its place.
        self.next_books_at = fetched.requested_at + self.settings.book_interval_s
        items = fetched.body.get("orderbooks") if fetched.ok else None
        if not isinstance(items, list):
            self.emit("book_calls", "book_call", {"requested_at": fetched.requested_at, "received_at": fetched.received_at,
                                                  "status": fetched.status, "error": fetched.error or "no_orderbooks",
                                                  "tickers": tickers, "changed": [], "unchanged": [], "missing": tickers})
            return
        by_ticker = {item["ticker"]: item for item in items
                     if isinstance(item, dict) and isinstance(item.get("ticker"), str)}
        changed, unchanged, missing = [], [], []
        for ticker in tickers:
            item, watched = by_ticker.get(ticker), self.watched.get(ticker)
            book = item.get("orderbook_fp") if isinstance(item, dict) else None
            if watched is None or not isinstance(book, dict):
                missing.append(ticker)
                continue
            digest = canonical_sha(book)
            lane = "books_btc15m" if watched.kind == "btc15m" else "books"
            if digest != watched.book_sha:
                seq = self.emit(lane, "book", {"ticker": ticker, "requested_at": fetched.requested_at,
                                               "received_at": fetched.received_at, "sha256": digest,
                                               "orderbook_fp": book}, fetched.received_at)
                if seq is None:
                    missing.append(ticker)
                    continue
                watched.book_sha = digest
                changed.append(ticker)
            else:
                unchanged.append(ticker)
            watched.last_book_at = fetched.received_at
            watched.fav = favourite_mid(book)
        self.emit("book_calls", "book_call", {"requested_at": fetched.requested_at, "received_at": fetched.received_at,
                                              "status": fetched.status, "body_sha256": fetched.sha256,
                                              "rtt_ms": round(fetched.rtt_ms, 3), "tickers": tickers,
                                              "changed": changed, "unchanged": unchanged, "missing": missing},
                  fetched.received_at)

    # ------------------------------------------------------------------ trades
    def _plan_trades(self, now: float) -> Request | None:
        job = self.trade_job
        if job is None:
            if now < self.next_trades_at:
                return None
            high = int(now)
            low = high - int(self.settings.trade_interval_s) - TRADE_OVERLAP_S
            if self.trade_covered_to is not None:
                low = self.trade_covered_to - TRADE_OVERLAP_S
                if low < high - LIVE_TRADE_SPAN_S:
                    self._queue_backfill(low, high - LIVE_TRADE_SPAN_S + TRADE_OVERLAP_S, "trade_tape_behind")
                    low = high - LIVE_TRADE_SPAN_S
            job = self.trade_job = TradeJob(low, high, None, False)
            self.next_trades_at = now + self.settings.trade_interval_s
        return self._trade_request("trades", job)

    def _plan_backfill(self, now: float) -> Request | None:
        if not self.backfill_jobs:
            return None
        return self._trade_request("backfill", self.backfill_jobs[0])

    def _trade_request(self, lane: str, job: TradeJob) -> Request:
        params: list[tuple[str, Any]] = [("min_ts", job.min_ts), ("max_ts", job.max_ts), ("limit", 1000)]
        if job.ticker:
            params.insert(0, ("ticker", job.ticker))
        if job.cursor:
            params.append(("cursor", job.cursor))
        return Request(lane, "/markets/trades", params, {"job": job})

    def _queue_backfill(self, low: int, high: int, cause: str) -> None:
        """Exchange-wide windows when that is cheaper, else one window per watched ticker.

        A window that touches the last queued, not yet started exchange-wide window extends it, so a lane
        that keeps falling behind under 429s queues one growing job instead of thousands of small ones.
        """
        tickers = self._tape_tickers(low)
        if not tickers:
            return  # prints are kept only for watched tickers: with none, nothing in this window is missing
        last = self.backfill_jobs[-1] if self.backfill_jobs else None
        if (last is not None and last.ticker is None and not last.pages and not last.cursor
                and low <= last.max_ts + 1 and high >= last.min_ts):
            last.min_ts, last.max_ts = min(last.min_ts, low), max(last.max_ts, high)
            return
        self.gap("trades", low, high, cause, backfill="queued")
        pages = self.trade_rate * max(1, high - low) / 1000.0
        if pages <= max(1, len(tickers)):
            self.backfill_jobs.append(TradeJob(low, high, None, True))
        else:
            self.backfill_jobs.extend(TradeJob(low, high, ticker, True) for ticker in tickers)

    def _tape_tickers(self, since: float) -> list[str]:
        """Tickers whose prints a trade window starting at ``since`` must keep: watched now, or unwatched after it."""
        return sorted(set(self.watched) | {ticker for ticker, (_, stopped) in self.unwatched.items() if stopped >= since})

    def _tape_kind(self, ticker: str, since: float) -> str | None:
        watched = self.watched.get(ticker)
        if watched is not None:
            return watched.kind
        gone = self.unwatched.get(ticker)
        return gone[0] if gone is not None and gone[1] >= since else None

    def _done_trades(self, request: Request, fetched: Fetched) -> None:
        self._trade_page(request, fetched, backfill=False)

    def _done_backfill(self, request: Request, fetched: Fetched) -> None:
        self._trade_page(request, fetched, backfill=True)

    def _trade_page(self, request: Request, fetched: Fetched, *, backfill: bool) -> None:
        job: TradeJob = request.context["job"]
        rows = fetched.body.get("trades") if fetched.ok else None
        cursor = fetched.body.get("cursor") if fetched.ok else None
        if not isinstance(rows, list) or not isinstance(cursor, (str, type(None))):
            job.attempts += 1
            if job.attempts >= PAGE_ATTEMPTS:
                self._abandon(job, backfill, f"trade_page_failed_{_why(fetched) if not fetched.ok else 'malformed'}")
            return
        self._keep_trades(rows, job, fetched)  # may raise: the attempt then counts (step's guard)
        job.attempts = 0
        job.pages += 1
        cursor = cursor or ""
        if cursor and cursor in job.seen_cursors:
            self._abandon(job, backfill, "trade_cursor_repeated")
            return
        if cursor and job.pages >= (BACKFILL_PAGES if backfill else LIVE_TRADE_PAGES):
            # Newest first: everything from the oldest fetched print to max_ts is complete; the rest is backfilled.
            cut = min(job.max_ts, math.ceil(job.oldest) + 1) if job.oldest is not None else job.max_ts
            self._record_coverage(job, max(job.min_ts, cut), backfill, fetched)
            if backfill:
                self.gap("trades", job.min_ts, cut, "backfill_page_cap", ticker=job.ticker)
            else:
                self._queue_backfill(job.min_ts, cut + TRADE_OVERLAP_S, "trade_page_cap")
            self._finish(job, backfill)
            return
        if cursor:
            job.seen_cursors.add(cursor)
            job.cursor = cursor
            return
        self._record_coverage(job, job.min_ts, backfill, fetched)
        self._finish(job, backfill)

    def _record_coverage(self, job: TradeJob, low: int, backfill: bool, fetched: Fetched) -> None:
        """Every trade of every watched ticker in [low, max_ts] was received (newest-first pages, empty cursor)."""
        self.emit("trade_coverage", "trade_coverage", {"from": low, "to": job.max_ts, "scope": job.ticker or "exchange",
                                                       "backfill": backfill, "pages": job.pages, "rows": job.rows,
                                                       "received_at": fetched.received_at}, fetched.received_at)
        if not backfill and job.ticker is None:
            # Exchange-wide prints per second, to choose between exchange-wide and per-ticker backfill.
            self.trade_rate = 0.8 * self.trade_rate + 0.2 * job.rows / max(1, job.max_ts - low)

    def _finish(self, job: TradeJob, backfill: bool) -> None:
        if backfill:
            if self.backfill_jobs and self.backfill_jobs[0] is job:
                self.backfill_jobs.popleft()
        else:
            self.trade_covered_to = max(self.trade_covered_to or job.max_ts, job.max_ts)
            self.trade_job = None

    def _abandon(self, job: TradeJob, backfill: bool, cause: str) -> None:
        if backfill:
            self.gap("trades", job.min_ts, job.max_ts, cause, ticker=job.ticker, backfill="failed")
        else:
            self._queue_backfill(job.min_ts, job.max_ts, cause)
        self._finish(job, backfill)

    def _keep_trades(self, rows: list[Any], job: TradeJob, fetched: Fetched) -> None:
        """Keep the prints of tickers watched during this window; a trade id is remembered only once it is stored."""
        kept: dict[str, list[dict[str, Any]]] = {"trades": [], "trades_btc15m": []}
        fresh: dict[str, dict[str, str]] = {"trades": {}, "trades_btc15m": {}}
        oldest = job.oldest
        for row in rows:
            if not isinstance(row, dict):
                continue
            created = ts(row.get("created_time"))
            if created is not None:
                oldest = created if oldest is None else min(oldest, created)
            ticker, trade_id = row.get("ticker"), row.get("trade_id")
            kind = self._tape_kind(ticker, job.min_ts) if isinstance(ticker, str) else None
            if kind is None or not isinstance(trade_id, str) or not trade_id:
                continue
            lane = "trades_btc15m" if kind == "btc15m" else "trades"
            digest = canonical_sha(row)[:16]
            previous = self.dedup.get(trade_id) or fresh["trades"].get(trade_id) or fresh["trades_btc15m"].get(trade_id)
            if previous == digest:
                continue
            if previous is not None:
                self.trade_conflicts += 1
                self.emit("gaps", "trade_conflict", {"trade_id": trade_id, "ticker": ticker, "row": row,
                                                     "received_at": fetched.received_at})
                continue
            fresh[lane][trade_id] = digest
            kept[lane].append(row)
        for lane, values in kept.items():
            if not values:
                continue
            seq = self.emit(lane, "trades", {"requested_at": fetched.requested_at, "received_at": fetched.received_at,
                                             "window": [job.min_ts, job.max_ts], "scope": job.ticker or "exchange",
                                             "page": job.pages + 1, "body_sha256": fetched.sha256,
                                             "rows_in_page": len(rows), "rows": values}, fetched.received_at)
            if seq is None:
                continue  # shed by the storage cap (a recorded gap): these ids are not remembered as stored
            for trade_id, digest in fresh[lane].items():
                self.dedup[trade_id] = digest
            while len(self.dedup) > DEDUP_MEMORY:
                self.dedup.popitem(last=False)
            self.lags.extend(fetched.received_at - created for created in
                             (ts(row.get("created_time")) for row in values) if created is not None)
        job.rows += len(rows)
        job.oldest = oldest

    # ------------------------------------------------------------------ KXBTC15M metadata (Family B tape)
    def _plan_btc_meta(self, now: float) -> Request | None:
        if not self.settings.btc15m or not self.store.lane_allowed("btc15m_meta"):
            return None
        if not self.btc_queue and now >= self.next_btc_meta_at:
            current = int(now // 900) * 900
            query = [("series_ticker", BTC15M), ("min_close_ts", current + 1), ("max_close_ts", current + 1800),
                     ("limit", 100)]
            self.btc_queue.extend([Request("btc15m_meta", f"/series/{BTC15M}", [], {"step": "series"}),
                                   Request("btc15m_meta", "/markets", query, {"step": "markets"})])
            self.next_btc_meta_at = current + 900 + 5
        return self.btc_queue[0] if self.btc_queue else None

    def _done_btc15m_meta(self, request: Request, fetched: Fetched) -> None:
        if not fetched.ok:
            if self.lanes["btc15m_meta"].in_a_row >= PAGE_ATTEMPTS:
                self.btc_queue.clear()
                self.next_btc_meta_at = fetched.received_at + 30
                self.gap("btc15m_meta", fetched.requested_at, fetched.received_at, "btc15m_metadata_unavailable")
            return
        step = request.context["step"]
        body = fetched.body
        rows = _rows(body, "markets") if step == "markets" else []  # a malformed page raises before it is popped
        if self.btc_queue and self.btc_queue[0] is request:
            self.btc_queue.popleft()
        self._accepted(request)
        meta = {"requested_at": fetched.requested_at, "received_at": fetched.received_at, "body_sha256": fetched.sha256}
        if step == "series":
            self.emit("btc15m_meta", "series", {**meta, "series": body.get("series")}, fetched.received_at)
        elif step == "markets":
            self.emit("btc15m_meta", "markets", {**meta, "cursor": body.get("cursor"), "rows": rows}, fetched.received_at)
            for row in rows:
                ticker, event = row.get("ticker"), row.get("event_ticker")
                opened, closes = ts(row.get("open_time")), ts(row.get("close_time"))
                if not isinstance(ticker, str) or not isinstance(event, str) or opened is None or closes is None:
                    continue
                if ticker not in self.watched:
                    self._watch(Watched(ticker, event, BTC15M, "Crypto", "btc15m", opened, closes,
                                        str(row.get("status")), fetched.received_at))
                    self.btc_queue.append(Request("btc15m_meta", "/events/fee_changes", [("event_ticker", event)],
                                                  {"step": "event_fees", "event": event}))
        elif step == "event_fees":
            self.emit("btc15m_meta", "event_fee_changes", {**meta, "event_ticker": request.context["event"],
                                                           "body": body}, fetched.received_at)

    # ------------------------------------------------------------------ discovery (Family A)
    def _plan_discovery(self, now: float) -> Request | None:
        state = self.discovery
        if state is None:
            if now < self.next_discovery_at:
                return None
            state = self.discovery = {"started_at": now, "stage": "series", "categories": list(OPEN_CATEGORIES),
                                      "cursor": "", "pages": 0, "events": {}, "other_categories": Counter(),
                                      "series_todo": [], "detail_todo": [], "markets": [], "market_cursor": "",
                                      "seen": set()}
            self.next_discovery_at = now + self.settings.discovery_interval_s
            if all(now - self.series_at.get("category:" + name, -math.inf) < 86400 for name in OPEN_CATEGORIES):
                state["stage"] = "events"
        stage = state["stage"]
        if stage == "series":
            return Request("discovery", "/series", [("category", state["categories"][0])], {"stage": "series"})
        if stage == "events":
            params: list[tuple[str, Any]] = [("status", "open"), ("limit", 200)]
            if state["cursor"]:
                params.append(("cursor", state["cursor"]))
            return Request("discovery", "/events", params, {"stage": "events"})
        if stage == "detail":
            return Request("discovery", f"/series/{state['detail_todo'][0]}", [], {"stage": "detail"})
        if stage == "markets":
            series = state["series_todo"][0]
            params = [("series_ticker", series), ("min_close_ts", int(state["started_at"] + RECORDER_WINDOW[0])),
                      ("max_close_ts", int(state["started_at"] + RECORDER_WINDOW[1])), ("limit", 1000)]
            if state["market_cursor"]:
                params.append(("cursor", state["market_cursor"]))
            return Request("discovery", "/markets", params, {"stage": "markets", "series": series})
        return None

    def _done_discovery(self, request: Request, fetched: Fetched) -> None:
        state = self.discovery
        if state is None:
            return
        stage = request.context["stage"]
        if not fetched.ok:
            if _transient(fetched):
                # No reply, 429s or server errors: the venue is struggling, so the whole pass waits.
                if self.lanes["discovery"].in_a_row >= PAGE_ATTEMPTS:
                    self.gap("discovery", state["started_at"], fetched.received_at,
                             f"discovery_abandoned_{_why(fetched)}")
                    self.discovery = None
                    self.next_discovery_at = fetched.received_at + 300
            elif self._strike(request):  # this one item is refused (4xx) or unreadable: skip it, keep the pass
                self._give_up(request, fetched.received_at, f"discovery_{stage}_failed_{_why(fetched)}")
            return
        body = fetched.body
        meta = {"requested_at": fetched.requested_at, "received_at": fetched.received_at, "body_sha256": fetched.sha256}
        if stage == "series":
            rows = _rows(body, "series")
            category = state["categories"].pop(0)
            self.emit("discovery", "series_list", {**meta, "category": category, "rows": rows}, fetched.received_at)
            for row in rows:
                if isinstance(row.get("ticker"), str):
                    self.series_rows[row["ticker"]] = row
            self.series_at["category:" + category] = fetched.received_at
            if not state["categories"]:
                state["stage"] = "events"
        elif stage == "events":
            rows, cursor = _rows(body, "events"), _cursor(body)
            kept = [row for row in rows if row.get("category") in OPEN_CATEGORIES]
            others = Counter(str(row.get("category")) for row in rows if row.get("category") not in OPEN_CATEGORIES)
            state["other_categories"].update(others)
            self.emit("discovery", "events_page", {**meta, "page": state["pages"] + 1, "rows": kept,
                                                   "rows_in_page": len(rows), "other_categories": dict(others)},
                      fetched.received_at)
            for row in kept:
                if isinstance(row.get("event_ticker"), str):
                    state["events"][row["event_ticker"]] = row
            state["pages"] += 1
            if cursor and cursor not in state["seen"] and state["pages"] < 500:
                state["seen"].add(cursor)
                state["cursor"] = cursor
            else:
                if cursor:
                    self.gap("discovery", state["started_at"], fetched.received_at, "events_pagination_incomplete")
                self._events_done(state, fetched.received_at)
        elif stage == "detail":
            row = body.get("series")
            if row is not None and not isinstance(row, dict):
                raise Malformed("series is not an object")
            name = state["detail_todo"].pop(0)
            self.emit("discovery", "series", {**meta, "series_ticker": name, "series": row}, fetched.received_at)
            if isinstance(row, dict):
                self.series_rows[name] = row
            if not state["detail_todo"]:
                state["stage"] = "markets"
        elif stage == "markets":
            rows, cursor = _rows(body, "markets"), _cursor(body)
            self._market_rows("discovery_markets", rows, meta, request.context["series"])
            state["markets"].extend(rows)
            if cursor and cursor not in state["seen"]:
                state["seen"].add(cursor)
                state["market_cursor"] = cursor
            else:
                state["market_cursor"] = ""
                state["series_todo"].pop(0)
        self._accepted(request)
        self._discovery_maybe_done(state, fetched.received_at)

    def _events_done(self, state: dict[str, Any], now: float) -> None:
        """The event list is complete (or cut short): list the series to read, skipping unusable names."""
        names = {row.get("series_ticker") for row in state["events"].values()
                 if isinstance(row.get("series_ticker"), str)
                 and _event_date_ok(str(row.get("event_ticker")), str(row.get("series_ticker")), state["started_at"])}
        bad = sorted(str(name) for name in names if not public_ticker(name))
        if bad:  # a name no public path may carry (lowercase, empty, odd bytes): recorded, never requested
            self.gap("discovery", now, now, "series_ticker_unusable", series=bad[:50], count=len(bad))
        state["series_todo"] = sorted(str(name) for name in names if public_ticker(name))
        state["detail_todo"] = [name for name in state["series_todo"] if name not in self.series_rows]
        state["stage"] = "detail" if state["detail_todo"] else "markets"

    def _discovery_maybe_done(self, state: dict[str, Any], now: float) -> None:
        if state["stage"] == "markets" and not state["series_todo"] and self.discovery is state:
            self._admit_all(state, now)
            self.discovery = None

    def _skip_discovery(self, request: Request, at: float, cause: str) -> None:
        """Drop the one discovery item that keeps failing (with a gap) and carry on with the rest of the pass."""
        state = self.discovery
        if state is None:
            return
        stage = request.context["stage"]
        item: Any = None
        if stage == "series" and state["categories"]:
            item = state["categories"].pop(0)
            if not state["categories"]:
                state["stage"] = "events"
        elif stage == "events":
            self.gap("discovery", state["started_at"], at, "events_pagination_incomplete")
            self._events_done(state, at)
        elif stage == "detail" and state["detail_todo"]:
            item = state["detail_todo"].pop(0)
            if not state["detail_todo"]:
                state["stage"] = "markets"
        elif stage == "markets" and state["series_todo"]:
            item = state["series_todo"].pop(0)
            state["market_cursor"] = ""
        self.gap("discovery", at, at, cause, stage=stage, item=item)
        self._discovery_maybe_done(state, at)

    def _market_rows(self, kind: str, rows: list[dict[str, Any]], meta: dict[str, Any], scope: str | None) -> None:
        """Full rows when a ticker's rules/terms changed; otherwise only the moving fields (lossless)."""
        out: list[dict[str, Any]] = []
        for row in rows:
            ticker = row.get("ticker")
            if not isinstance(ticker, str):
                continue
            dynamic, static = split_row(row)
            if self.static_sha.get(ticker) != static:
                out.append({"ticker": ticker, "full": row, "static_sha256": static})
                self.static_sha[ticker] = static
            else:
                out.append({"ticker": ticker, "dyn": dynamic, "static_sha256": static})
        self.emit("markets", kind, {**meta, "scope": scope, "rows": out}, meta["received_at"])

    def _admit_all(self, state: dict[str, Any], now: float) -> None:
        counts: Counter[str] = Counter()
        rows: list[dict[str, Any]] = []
        decisions: dict[str, tuple[bool, str | None]] = {}
        candidates = sum(1 for item in self.watched.values() if item.kind == "candidate")
        for market in state["markets"]:
            ticker = str(market.get("ticker") or "")
            event = state["events"].get(market.get("event_ticker"))
            series_name = event.get("series_ticker") if isinstance(event, dict) else None
            series = self.series_rows.get(series_name) if isinstance(series_name, str) else None
            decision = admit(market, event, series, now, window=RECORDER_WINDOW, check_fees=False)
            admitted, reason = decision.admitted, decision.reason
            if admitted and ticker not in self.watched and candidates >= self.settings.max_candidates:
                admitted, reason = False, "recorder_capacity"
            counts[f"{decision.category}|{reason or 'admitted'}"] += 1
            decisions[ticker] = (admitted, reason)
            if self.decisions.get(ticker) != (admitted, reason):
                rows.append({**decision.row(), "admitted": admitted, "reason": reason,
                             "rule": decision.rule if reason != "recorder_capacity" else "capacity",
                             "event_ticker": market.get("event_ticker"), "series_ticker": series_name,
                             "event_listed": isinstance(event, dict)})
            if admitted and ticker not in self.watched and isinstance(event, dict) and isinstance(series_name, str):
                opened, closes = ts(market.get("open_time")), ts(market.get("close_time"))
                if opened is not None and closes is not None:
                    self._watch(Watched(ticker, str(market.get("event_ticker")), series_name,
                                        str(event.get("category")), "candidate", opened, closes,
                                        str(market.get("status")), now))
                    candidates += 1
                    event_ticker = str(market.get("event_ticker"))
                    if event_ticker not in self.fee_events and event_ticker not in self.fee_queue:
                        self.fee_queue.append(event_ticker)
        self.decisions = decisions
        self.static_sha = {ticker: digest for ticker, digest in self.static_sha.items()
                           if ticker in decisions or ticker in self.watched}
        self.emit("admissions", "admissions", {"at_discovery": state["started_at"], "changed": rows,
                                               "window": list(RECORDER_WINDOW), "fee_rule": "applied_by_replay"}, now)
        self.emit("admissions", "discovery_summary", {
            "started_at": state["started_at"], "finished_at": now, "events_pages": state["pages"],
            "open_category_events": len(state["events"]), "other_category_events": dict(state["other_categories"]),
            "markets_seen": len(state["markets"]), "counts": dict(counts),
            "candidates": sum(1 for item in self.watched.values() if item.kind == "candidate")}, now)

    # ------------------------------------------------------------------ sweep and settlement
    def _chunks(self, tickers: list[str]) -> list[list[str]]:
        """Ticker lists for ``/markets?tickers=``: at most ``chunk_size`` each, and a URL Kalshi accepts."""
        out: list[list[str]] = []
        chunk: list[str] = []
        size = 0
        for ticker in tickers:
            cost = len(quote(ticker, safe="")) + 3  # the encoded comma
            if chunk and (len(chunk) >= self.chunk_size or size + cost > SWEEP_QUERY_BYTES):
                out.append(chunk)
                chunk, size = [], 0
            chunk.append(ticker)
            size += cost
        if chunk:
            out.append(chunk)
        return out

    def _chunk_failed(self, request: Request, fetched: Fetched) -> None:
        """A failed sweep/settlement call: a 4xx halves its chunk; otherwise it is dropped after PAGE_ATTEMPTS."""
        queue = self.sweep_queue if request.lane == "sweep" else self.settle_queue
        tickers: list[str] = request.context["tickers"]
        if not queue or queue[0] != tickers:
            return
        status = fetched.status
        if status is not None and 400 <= status < 500 and status != 429 and len(tickers) > 1:
            half = len(tickers) // 2
            queue.popleft()
            queue.extendleft([tickers[half:], tickers[:half]])
            self.chunk_size = max(1, min(self.chunk_size, half))
            self.strikes.pop(request.lane, None)
            self.emit("telemetry", "chunk_halved", {"request_lane": request.lane, "status": status,
                                                    "tickers": len(tickers), "chunk_size": self.chunk_size})
            return
        if self._strike(request):
            self._give_up(request, fetched.received_at, f"{request.lane}_page_failed_{_why(fetched)}")

    def _plan_sweep(self, now: float) -> Request | None:
        queue = self.sweep_queue
        if not queue and now >= self.next_sweep_at:
            tickers = sorted(item.ticker for item in self.watched.values()
                             if item.kind == "candidate" and item.close_time > now and not item.settled)
            queue.extend(self._chunks(tickers))
            self.next_sweep_at = now + self.settings.sweep_interval_s
        if not queue:
            return None
        return Request("sweep", "/markets", [("tickers", ",".join(queue[0])), ("limit", 1000)], {"tickers": queue[0]})

    def _done_sweep(self, request: Request, fetched: Fetched) -> None:
        if not fetched.ok:
            self._chunk_failed(request, fetched)
            return
        rows = _rows(fetched.body, "markets")
        if self.sweep_queue and self.sweep_queue[0] == request.context["tickers"]:
            self.sweep_queue.popleft()
        self._accepted(request)
        self._market_rows("sweep", rows, {"requested_at": fetched.requested_at, "received_at": fetched.received_at,
                                          "body_sha256": fetched.sha256}, None)
        for row in rows:
            ticker = row.get("ticker")
            watched = self.watched.get(ticker) if isinstance(ticker, str) else None
            if watched is not None:
                watched.status = str(row.get("status"))
                closes = ts(row.get("close_time"))
                if closes is not None:
                    watched.close_time = closes

    def _plan_settlement(self, now: float) -> Request | None:
        queue = self.settle_queue
        if not queue and now >= self.next_settlement_at:
            due = sorted(item.ticker for item in self.watched.values()
                         if not item.settled and (item.close_time <= now or item.status not in ("active", "initialized")))
            queue.extend(self._chunks(due))
            self.next_settlement_at = now + self.settings.settlement_interval_s
        if not queue:
            return None
        return Request("settlement", "/markets", [("tickers", ",".join(queue[0])), ("limit", 1000)],
                       {"tickers": queue[0]})

    def _done_settlement(self, request: Request, fetched: Fetched) -> None:
        if not fetched.ok:
            self._chunk_failed(request, fetched)
            return
        rows = {row.get("ticker"): row for row in _rows(fetched.body, "markets")}
        if self.settle_queue and self.settle_queue[0] == request.context["tickers"]:
            self.settle_queue.popleft()
        self._accepted(request)
        meta = {"requested_at": fetched.requested_at, "received_at": fetched.received_at, "body_sha256": fetched.sha256}
        for kind in ("btc15m", "candidate"):
            chosen = [rows[ticker] for ticker in request.context["tickers"]
                      if ticker in rows and self.watched.get(ticker) is not None and self.watched[ticker].kind == kind]
            if chosen:
                self.emit("btc15m_meta" if kind == "btc15m" else "settlement", "settlement", {**meta, "rows": chosen},
                          fetched.received_at)
        for ticker in request.context["tickers"]:
            watched, row = self.watched.get(ticker), rows.get(ticker)
            if watched is None:
                continue
            if row is not None:
                watched.status = str(row.get("status"))
                if row.get("status") in ("finalized", "settled") and row.get("result") in ("yes", "no"):
                    watched.settled = True
                    self._unwatch(ticker, fetched.received_at, "finalized")
                    continue
            if fetched.received_at - watched.close_time > SETTLEMENT_GIVE_UP_S:
                self.gap("settlement", watched.close_time, fetched.received_at, "settlement_not_seen_45_days",
                         ticker=ticker)
                self._unwatch(ticker, fetched.received_at, "settlement_timeout")

    def _watch(self, item: Watched) -> None:
        """The tape is complete for a ticker only from here: trades are kept only while it is watched."""
        self.watched[item.ticker] = item
        self.unwatched.pop(item.ticker, None)
        self.emit("admissions", "watch", {"action": "start", "tickers": [item.ticker], "watch_kind": item.kind,
                                          "at_watch": item.added_at}, item.added_at)

    def _unwatch(self, ticker: str, now: float, reason: str) -> None:
        item = self.watched.pop(ticker, None)
        if item is not None:
            self.unwatched[ticker] = (item.kind, now)  # a later backfill of an earlier window still keeps its prints
            self.emit("admissions", "watch", {"action": "stop", "tickers": [ticker], "reason": reason}, now)

    # ------------------------------------------------------------------ fees and other daily rows
    def _plan_fees(self, now: float) -> Request | None:
        if now >= self.next_series_fees_at:
            return Request("fees", "/series/fee_changes", [("show_historical", "true")], {"step": "series"})
        if not self.fee_queue:
            return None
        return Request("fees", "/events/fee_changes", [("event_ticker", self.fee_queue[0])],
                       {"step": "event", "event": self.fee_queue[0]})

    def _done_fees(self, request: Request, fetched: Fetched) -> None:
        if not fetched.ok:
            # Any failure counts: one event the venue keeps refusing must not hold every later lookup back.
            if self._strike(request):
                self._give_up(request, fetched.received_at, f"fee_lookup_failed_{_why(fetched)}")
            return
        self._accepted(request)
        meta = {"requested_at": fetched.requested_at, "received_at": fetched.received_at, "body_sha256": fetched.sha256}
        if request.context["step"] == "series":
            self.next_series_fees_at = fetched.received_at + 86400
            self.emit("fees", "series_fee_changes", {**meta, "body": fetched.body}, fetched.received_at)
            return
        event = request.context["event"]
        if self.fee_queue and self.fee_queue[0] == event:
            self.fee_queue.popleft()
        self.fee_events[event] = fetched.received_at
        self.emit("fees", "event_fee_changes", {**meta, "event_ticker": event, "body": fetched.body},
                  fetched.received_at)

    def _plan_other(self, now: float) -> Request | None:
        if not self.other_queue and now >= self.next_other_at:
            self.other_queue.extend([Request("other", "/historical/cutoff", [], {"step": "cutoff"}),
                                     Request("other", "/incentive_programs", [("status", "active"), ("limit", 1000)],
                                             {"step": "incentives", "page": 1})])
            self.next_other_at = now + 86400
        return self.other_queue[0] if self.other_queue else None

    def _done_other(self, request: Request, fetched: Fetched) -> None:
        if not fetched.ok:
            if self.lanes["other"].in_a_row >= PAGE_ATTEMPTS:
                self.other_queue.clear()
            return
        if self.other_queue and self.other_queue[0] is request:
            self.other_queue.popleft()
        self._accepted(request)
        meta = {"requested_at": fetched.requested_at, "received_at": fetched.received_at, "body_sha256": fetched.sha256}
        self.emit("other", request.context["step"], {**meta, "page": request.context.get("page"), "body": fetched.body},
                  fetched.received_at)
        cursor = fetched.body.get("next_cursor") if request.context["step"] == "incentives" else None
        if isinstance(cursor, str) and cursor and request.context["page"] < 200:
            self.other_queue.appendleft(Request("other", "/incentive_programs",
                                                [("status", "active"), ("limit", 1000), ("cursor", cursor)],
                                                {"step": "incentives", "page": request.context["page"] + 1}))

    # ------------------------------------------------------------------ running
    def run(self, stop: threading.Event, *, max_runtime_s: float | None = None) -> None:
        spot = SpotTicks(self) if self.settings.spot_ticks else None
        if spot is not None:
            spot.start(stop)
        log.info("kalshi_recorder_started mode=READ_ONLY_PUBLIC host=%s rate_per_s=%s btc15m=%s spot=%s cap_mb=%s",
                 self.host, self.settings.rate_per_s, self.settings.btc15m, self.settings.spot_ticks,
                 self.settings.max_storage_mb)
        deadline = None if max_runtime_s is None else self.started_at + max_runtime_s
        try:
            while not stop.is_set() and (deadline is None or self.wall() < deadline):
                if not self.step(stop):
                    stop.wait(0.2)
        finally:
            self.close()

    def close(self) -> None:
        now = self.wall()
        try:
            self.write_manifest(self.hour_started, now, partial=True)
            self._save_state(now)
        finally:
            self.store.close()
        log.info("kalshi_recorder_stopped")


# =========================================================================== optional spot ticks
def coinbase_trades(message: Any) -> list[dict[str, Any]]:
    """Raw BTC-USD trades from a Coinbase Advanced Trade ``market_trades`` message."""
    if not isinstance(message, dict) or message.get("channel") != "market_trades":
        return []
    out: list[dict[str, Any]] = []
    for event in message.get("events") or []:
        for trade in (event.get("trades") or []) if isinstance(event, dict) else []:
            if isinstance(trade, dict) and trade.get("product_id") == "BTC-USD" and trade.get("price"):
                out.append(trade)
    return out


def kraken_trades(message: Any) -> list[dict[str, Any]]:
    """Raw BTC/USD trades from a Kraken v2 ``trade`` message (snapshot or update)."""
    if not isinstance(message, dict) or message.get("channel") != "trade":
        return []
    return [row for row in message.get("data") or []
            if isinstance(row, dict) and row.get("symbol") == "BTC/USD" and row.get("price") is not None]


class SpotTicks:
    """Coinbase and Kraken public trade websockets, batched per second into the ``spot`` lane."""

    def __init__(self, recorder: Recorder, *, connect: Callable[..., Any] | None = None) -> None:
        self.recorder, self._connect = recorder, connect
        self.batches: dict[str, list[dict[str, Any]]] = {"coinbase": [], "kraken": []}
        self.lock = threading.Lock()

    def start(self, stop: threading.Event) -> threading.Thread:
        thread = threading.Thread(target=lambda: asyncio.run(self.run(stop)), name="kalshi-recorder-spot", daemon=True)
        thread.start()
        return thread

    def add(self, venue: str, rows: list[dict[str, Any]], received_at: float) -> None:
        if rows:
            with self.lock:
                self.batches[venue].extend({"received_at": received_at, **row} for row in rows)

    def flush(self) -> None:
        with self.lock:
            batches, self.batches = self.batches, {"coinbase": [], "kraken": []}
        for venue, rows in batches.items():
            if rows:
                self.recorder.emit("spot", "spot_trades", {"venue": venue, "rows": rows,
                                                           "basis": "exchange_spot_not_cf_benchmarks"})

    async def _feed(self, venue: str, url: str, subscribe: list[dict[str, Any]],
                    parse: Callable[[Any], list[dict[str, Any]]], stop: threading.Event) -> None:
        connect_ws: Callable[..., Any]
        if self._connect is not None:
            connect_ws = self._connect
        else:
            from websockets.asyncio.client import connect

            connect_ws = connect
        down_since: float | None = None
        while not stop.is_set():
            try:
                async with connect_ws(url, open_timeout=10, ping_interval=20, ping_timeout=10) as ws:
                    for message in subscribe:
                        await ws.send(json.dumps(message))
                    if down_since is not None:
                        self.recorder.gap("spot", down_since, self.recorder.wall(), "spot_reconnected", venue=venue)
                        down_since = None
                    while not stop.is_set():
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        self.add(venue, parse(json.loads(raw)), self.recorder.wall())
            except Exception as exc:  # noqa: BLE001 - a dropped public socket is a recorded gap, then a retry
                if down_since is None:
                    down_since = self.recorder.wall()
                    log.warning("kalshi_recorder_spot_disconnected venue=%s error=%s", venue, type(exc).__name__)
                await asyncio.sleep(5)

    async def run(self, stop: threading.Event) -> None:
        feeds = [
            asyncio.create_task(self._feed("coinbase", COINBASE_WS, [
                {"type": "subscribe", "product_ids": ["BTC-USD"], "channel": "market_trades"},
                {"type": "subscribe", "product_ids": ["BTC-USD"], "channel": "heartbeats"}], coinbase_trades, stop)),
            asyncio.create_task(self._feed("kraken", KRAKEN_WS, [
                {"method": "subscribe", "params": {"channel": "trade", "symbol": ["BTC/USD"], "snapshot": False}}],
                kraken_trades, stop)),
        ]
        try:
            while not stop.is_set():
                await asyncio.sleep(1)
                self.flush()
        finally:
            for task in feeds:
                task.cancel()
            await asyncio.gather(*feeds, return_exceptions=True)
            self.flush()


# =========================================================================== entry points
def run_recorder(settings: RecorderSettings, stop: threading.Event, *, max_runtime_s: float | None = None) -> None:
    """Run until ``stop``; faults are logged and never propagate into a caller's money thread."""
    recorder = None
    try:
        recorder = Recorder(settings)
        recorder.run(stop, max_runtime_s=max_runtime_s)
    except Exception as exc:  # noqa: BLE001 - research capture never stops anything else
        log.error("kalshi_recorder_halted error=%s detail=%s", type(exc).__name__, _detail(exc))


def start_from_engine(data_dir: Path, stop: threading.Event,
                      env: Mapping[str, str] | None = None) -> threading.Thread | None:
    """The bot's hook: does nothing unless ``KALSHI_RECORDER_ENABLED=true`` (OFF by default).

    Reads ``.env`` overlaid by the real environment, as the bot's config does (``env`` replaces both, for
    tests). It refuses to start while any desk in this process trades live (a recorder 429 could hold the
    live client, cancels included), and otherwise runs the reduced in-bot profile (``RecorderSettings.in_bot``).
    """
    values, _ = process_env(env, dotenv=None if env is not None else ".env")
    try:
        enabled = _bool(str(values.get("KALSHI_RECORDER_ENABLED") or "false"))
    except ValueError:
        log.warning("kalshi_recorder_not_started reason=KALSHI_RECORDER_ENABLED_unreadable")
        return None
    if not enabled:
        return None
    live = live_modes(values)
    if live:
        log.warning("kalshi_recorder_not_started reason=live_trading_in_this_process modes=%s "
                    "(run it as its own service: python -m nightcrawler.kalshi_recorder run)", ",".join(live))
        return None
    try:
        settings = RecorderSettings.from_env({**values, "DATA_DIR": str(data_dir)}).in_bot()
    except ConfigError as exc:
        log.warning("kalshi_recorder_not_started reason=invalid_settings detail=%s", _detail(exc))
        return None
    log.info("kalshi_recorder_in_bot rate_per_s=%s btc15m=off min_free_mb=%s (the bot's own Kalshi readers "
             "are not counted in this budget)", settings.rate_per_s, settings.min_free_mb)
    thread = threading.Thread(target=run_recorder, args=(settings, stop), name="kalshi-recorder", daemon=True)
    thread.start()
    return thread


def storage_summary(root: Path) -> dict[str, Any]:
    segments = load_index(root)
    by_lane: Counter[str] = Counter()
    for segment in segments:
        by_lane[segment.lane] += segment.gz_bytes
    status_path = root / "status.json"
    return {"root": str(root), "segments": len(segments), "bytes_by_lane": dict(by_lane),
            "bytes": sum(by_lane.values()),
            "status": json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else None}


def verify(root: Path) -> dict[str, Any]:
    bad = [segment.path for segment in load_index(root) if file_sha256(root / segment.path) != segment.sha256]
    return {"segments": len(load_index(root)), "mismatched": bad, "ok": not bad}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m nightcrawler.kalshi_recorder", description=__doc__.split("\n")[0])
    parser.add_argument("command", nargs="?", default="run", choices=("run", "status", "verify"))
    parser.add_argument("--data-dir", type=Path, help="Overrides DATA_DIR; data goes to <dir>/kalshi_recorder")
    parser.add_argument("--max-runtime-s", type=float, help="Stop after this many seconds (smoke runs)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    values, names = process_env()
    if args.data_dir is not None:
        values["DATA_DIR"] = str(args.data_dir)
    try:
        settings = RecorderSettings.from_env(values)
    except ConfigError as exc:
        print(f"kalshi_recorder: invalid settings: {exc}", file=sys.stderr)
        return 2
    if args.command == "run":
        # A service copied from the bot carries its keys and live switches; this recorder needs neither, and
        # a copy whose start command is wrong would be a second live bot. Names only; no value is read.
        unsafe = trading_names(names) + [f"{name}=live" for name in live_modes(values)]
        if unsafe:
            print("kalshi_recorder: refusing to run next to trading keys or live switches: " + ", ".join(unsafe)
                  + ". Run it as a new, empty service with no keys (docs/KALSHI_RECORDER.md section 2).",
                  file=sys.stderr)
            return 3
    if args.command == "status":
        print(json.dumps(storage_summary(settings.root), indent=2, sort_keys=True))
        return 0
    if args.command == "verify":
        result = verify(settings.root)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1
    stop = threading.Event()
    try:
        import signal

        for number in (signal.SIGTERM, signal.SIGINT):
            signal.signal(number, lambda *_: stop.set())
    except ValueError:
        pass
    recorder = Recorder(settings)
    recorder.run(stop, max_runtime_s=args.max_runtime_s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
