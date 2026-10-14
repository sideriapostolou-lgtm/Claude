"""What the practice LIP desk and the lead-lag analyzer read: the Kalshi recorder's files, parsed (READ-ONLY files).

This module opens files and nothing else: no network, no key, no client, no order path. It reads the public Kalshi
recorder's segments (``DATA_DIR/kalshi_recorder/segments/<lane>/<day>/<lane>-<UTC start>-<first seq>.jsonl.gz``, the
open hour as ``.jsonl.gz.part``; see docs/KALSHI_RECORDER.md section 5) and turns their records into plain values:

* books (lane ``books`` or any lane named in :data:`BOOK_LANES`, kind ``book``): ``ticker``, ``requested_at``,
  ``received_at``, raw ``orderbook_fp`` (written only when a book changed);
* book calls (kind ``book_call``): every ticker asked, as ``changed``, ``unchanged`` or ``missing``, with the call's
  ``requested_at`` and ``received_at`` (an unchanged ticker's book is its newest written one);
* prints (kind ``trades``): raw ``GET /markets/trades`` rows (``created_time``, ``taker_outcome_side``,
  ``yes_price_dollars``, ``no_price_dollars``, ``count_fp``, ``is_block_trade``);
* trade coverage (kind ``trade_coverage``: every print in ``[from, to]`` was received) and gaps (kind ``gap``);
* market rows (kinds ``sweep``, ``discovery_markets``, ``settlement``, ``markets``): ``{ticker, full: row}``,
  ``{ticker, dyn: {...}}`` or raw rows (``open_time``, ``close_time``, ``result``, ``floor_strike``,
  ``expiration_value``, ``settlement_ts``);
* liquidity programs (kind ``incentives`` or any record whose ``body`` holds ``incentive_programs``; kind
  ``programs`` in the ``lip`` lane: a full snapshot's ``rows``, or a diff's ``added`` and ``changed`` rows);
* Pyth prices, in any of the shapes :func:`parse_pyth` lists (the recorder's ``pyth``/``updates`` batches:
  ``columns`` id, price, conf, expo, publish_time, prev_publish_time, received_at and their ``rows``; Hermes SSE
  ``parsed`` messages; Kalshi's ``pyth_value`` messages; Pyth Pro ``priceFeeds``; flat ``{symbol|feed_id, price,
  received_at}`` rows), always timed by OUR receive time (``received_at``, else the record's ``at``);
* Kalshi's free 1 s settlement series (the ``lip`` lane's ``series`` records: ``new`` ``[[t_ms, value], ...]``; or a
  raw ``GET /live_data/events/{event}`` reply, ``live_data.details.timeseries``).

Unknown kinds are ignored, so new recorder lanes never break a reader.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
import zlib
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

YES, NO = 0, 1

# ---------------------------------------------------------------------- the 15-minute reward series
FX, METAL_GAS, COINRACE = "FX", "METAL_GAS", "COINRACE"


@dataclass(frozen=True)
class Series:
    """One 15-minute reward series (FX research of 2026-10-13, section 1.1 and 3.2): its family, exchange shard, the
    Pyth symbol it settles on (Coin Race settles on CF Benchmarks: none), Pyth's Hermes and Pro ids, the settlement
    rounding, and the practice desk's pull threshold in basis points (PREREG.md section 8)."""

    ticker: str
    asset: str
    group: str
    shard: int
    pyth_symbol: str | None
    hermes_id: str | None
    pro_id: int | None
    round_digits: int
    pull_bps: float | None


SERIES: dict[str, Series] = {item.ticker: item for item in (
    Series("KXEURUSD15M", "EUR/USD", FX, 0, "FX.EUR/USD",
           "a995d00bb36a63cef7fd2c287dc105fc8f3d93779f062f09551b0af3e81ec30b", 327, 5, 0.5),
    Series("KXGBPUSD15M", "GBP/USD", FX, 0, "FX.GBP/USD",
           "84c2dde9633d93d1bcad84e7dc41c9d56578b7ec52fabedc1f335d673df0a7c1", 333, 5, 0.5),
    Series("KXUSDJPY15M", "USD/JPY", FX, 0, "FX.USD/JPY",
           "ef2c98c804ba503c6a707e38be4dfbb16683775f195b091252bf24693042fd52", 340, 3, 0.5),
    Series("KXAUDUSD15M", "AUD/USD", FX, 0, "FX.AUD/USD",
           "67a6f93030420c1c9e3fe37c1ab6b77966af82f995944a9fefce357a22854a80", 315, 5, 0.5),
    Series("KXUSDCAD15M", "USD/CAD", FX, 0, "FX.USD/CAD",
           "3112b03a41c910ed446852aacf67118cb1bec67b2cd0b9a214c58cc0eaa2ecca", 338, 5, 0.5),
    Series("KXCOPPER15M", "Copper", METAL_GAS, 2, "Commodities.Index.CU/USD",
           "b2b238aeb6ef5a722c5cf278595bf40434e174cac4f88c8ad5b6f5009b548c59", 3525, 5, 1.0),
    Series("KXPLATINUM15M", "Platinum", METAL_GAS, 2, "Metal.XPT/USD",
           "398e4bbc7cbf89d6648c21e08019d878967677753b3096799595c78f805a34e5", 1781, 3, 1.0),
    Series("KXPALLADIUM15M", "Palladium", METAL_GAS, 2, "Metal.XPD/USD",
           "80367e9664197f37d89a07a804dffd2101c479c7c4e8490501bc9d9e1e7f9021", 1780, 3, 1.0),
    Series("KXNATGAS15M", "Natural gas", METAL_GAS, 2, "Commodities.Index.NATGAS/USD",
           "45f95717fbe158e896415d1cea33814d73e54169022a8f7bcbb815ebef92f71c", 3265, 5, 1.0),
    Series("KXCRYPTOLEAD15M", "Coin Race", COINRACE, 2, None, None, None, 3, None),
)}
FX_SERIES = tuple(name for name, item in SERIES.items() if item.group == FX)
SYMBOL_SERIES: dict[str, str] = {item.pyth_symbol: name for name, item in SERIES.items() if item.pyth_symbol}
HERMES_SYMBOL: dict[str, str] = {item.hermes_id: item.pyth_symbol for item in SERIES.values()
                                 if item.hermes_id and item.pyth_symbol}
PRO_SYMBOL: dict[int, str] = {item.pro_id: item.pyth_symbol for item in SERIES.values()
                              if item.pro_id is not None and item.pyth_symbol}
# Kalshi's live-data ``asset`` names (EURUSD, XPTUSD, ...) map back through the event ticker's series prefix.

#: Lanes the recorder may write each kind to. Readers take every lane listed and dispatch on ``kind``, so a lane
#: added later (an LIP book lane, a Pyth lane) only needs its name here.
BOOK_LANES = ("books", "books_lip")
CALL_LANES = ("book_calls", "lip")  # the recorder writes the LIP tickers' book calls to its ``lip`` lane
TRADE_LANES = ("trades", "trades_lip", "trade_coverage")
MARKET_LANES = ("markets", "settlement", "lip", "other")  # ``lip``: programs, settlement rows, the free series
PYTH_LANES = ("pyth",)
LIVE_LANES = ("lip",)
GAP_LANES = ("gaps",)
ALL_LANES = tuple(dict.fromkeys(BOOK_LANES + CALL_LANES + TRADE_LANES + MARKET_LANES + PYTH_LANES + LIVE_LANES
                                + GAP_LANES))
#: Only the recorder's rewards (LIP) lanes, the print coverage, Pyth, gaps and the daily program list: what the
#: practice desk and the analyzer need once the recorder writes the LIP lanes. Family A's own lanes (``books``,
#: ``book_calls``, ``trades``, ``markets``, ``settlement``) hold hundreds of MB a day nothing here needs.
LIP_LANES = ("books_lip", "trades_lip", "trade_coverage", "pyth", "gaps", "other", "lip")


def series_of(ticker: str) -> str | None:
    """The reward series of a market or event ticker (``KXEURUSD15M-26OCT132000-30`` -> ``KXEURUSD15M``)."""
    head = ticker.split("-", 1)[0]
    return head if head in SERIES else None


# ---------------------------------------------------------------------- small parsers
def number(value: Any) -> float | None:
    """A finite float from a number or a decimal string; None for anything else."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def when(value: Any) -> float | None:
    """Epoch seconds from an ISO-8601 string (``2026-10-13T19:11:02.062941Z``) or a number (seconds, or
    milliseconds when it is clearly too large to be seconds)."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).timestamp()
        except ValueError:
            return number(value)
    out = number(value)
    if out is not None and out > 1e11:  # milliseconds (or finer)
        while out > 1e11:
            out /= 1000.0
    return out


def cents(price: Any) -> int | None:
    """A dollar price on the cent grid as whole cents (``"0.4000"`` -> 40); None when off the grid or out of (0, 1)."""
    value = number(price)
    if value is None:
        return None
    whole = round(value * 100)
    if abs(value * 100 - whole) > 1e-6 or not 0 < whole < 100:
        return None
    return int(whole)


Levels = tuple[tuple[int, float], ...]  # (price in cents, size), best (highest) first


def levels_from(raw: Any) -> Levels:
    """One side of an ``orderbook_fp`` (``[[price_dollars, count], ...]``, any order) as cent levels, best first.
    Levels off the cent grid or with no size are dropped; equal prices add."""
    out: dict[int, float] = {}
    for item in raw or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        price, size = cents(item[0]), number(item[1])
        if price is None or size is None or size <= 0:
            continue
        out[price] = out.get(price, 0.0) + size
    return tuple(sorted(out.items(), reverse=True))


@dataclass(frozen=True)
class BookSnap:
    """One poll's book of one market: YES and NO bids in cents, best first."""

    ticker: str
    requested_at: float
    received_at: float
    yes: Levels
    no: Levels

    @property
    def best_yes(self) -> int | None:
        return self.yes[0][0] if self.yes else None

    @property
    def best_no(self) -> int | None:
        return self.no[0][0] if self.no else None

    @property
    def mid(self) -> float | None:
        """``(best YES bid + 100 - best NO bid) / 2`` in cents; None with an empty side."""
        if not self.yes or not self.no:
            return None
        return (self.yes[0][0] + 100 - self.no[0][0]) / 2.0


def book_from_record(record: Mapping[str, Any]) -> BookSnap | None:
    if record.get("kind") != "book":
        return None
    ticker, raw = record.get("ticker"), record.get("orderbook_fp")
    received = number(record.get("received_at"))
    if received is None:
        received = number(record.get("at"))
    requested = number(record.get("requested_at"))
    if not isinstance(ticker, str) or not isinstance(raw, Mapping) or received is None:
        return None
    return BookSnap(ticker, received if requested is None else requested, received,
                    levels_from(raw.get("yes_dollars")), levels_from(raw.get("no_dollars")))


@dataclass(frozen=True)
class BookCall:
    requested_at: float
    received_at: float
    changed: tuple[str, ...]
    unchanged: tuple[str, ...]
    missing: tuple[str, ...]
    ok: bool


def call_from_record(record: Mapping[str, Any]) -> BookCall | None:
    if record.get("kind") != "book_call":
        return None
    received = number(record.get("received_at"))
    requested = number(record.get("requested_at"))
    if received is None:
        return None

    def names(key: str) -> tuple[str, ...]:
        value = record.get(key)
        return tuple(item for item in value if isinstance(item, str)) if isinstance(value, list) else ()

    status = record.get("status")
    return BookCall(received if requested is None else requested, received, names("changed"), names("unchanged"),
                    names("missing"), status in (200, None) and not record.get("error"))


@dataclass(frozen=True)
class Print:
    """One public print, as the side whose resting bids it consumed: a taker selling YES hits YES bids at the YES
    price; a taker buying YES hits NO bids at the NO price (Kalshi's ``taker_outcome_side``, changelog 2026-05-06;
    checked against books in the rewards research)."""

    ticker: str
    at: float  # Kalshi's created_time
    side: int  # YES or NO: the resting bids it consumed
    price: int  # cents on that side
    size: float
    trade_id: str
    block: bool


def prints_from_record(record: Mapping[str, Any]) -> list[Print]:
    if record.get("kind") != "trades":
        return []
    out: list[Print] = []
    for row in record.get("rows") or []:
        if not isinstance(row, Mapping):
            continue
        ticker, trade_id = row.get("ticker"), row.get("trade_id")
        at = when(row.get("created_time"))
        size = number(row.get("count_fp", row.get("count")))
        taker = row.get("taker_outcome_side", row.get("taker_side"))
        if not isinstance(ticker, str) or not isinstance(trade_id, str) or at is None or size is None or size <= 0:
            continue
        if taker == "no":
            side, price = YES, cents(row.get("yes_price_dollars"))
        elif taker == "yes":
            side, price = NO, cents(row.get("no_price_dollars"))
        else:
            continue
        if price is None:
            continue
        out.append(Print(ticker, at, side, price, size, trade_id, bool(row.get("is_block_trade"))))
    return out


@dataclass(frozen=True)
class Coverage:
    start: float
    end: float
    scope: str


def coverage_from_record(record: Mapping[str, Any]) -> Coverage | None:
    if record.get("kind") != "trade_coverage":
        return None
    start, end = number(record.get("from")), number(record.get("to"))
    if start is None or end is None or end < start:
        return None
    return Coverage(start, end, str(record.get("scope") or "exchange"))


@dataclass(frozen=True)
class Gap:
    lane: str
    start: float | None
    end: float | None
    cause: str


def gap_from_record(record: Mapping[str, Any]) -> Gap | None:
    if record.get("kind") != "gap":
        return None
    return Gap(str(record.get("gap_lane") or "all"), number(record.get("from")), number(record.get("to")),
               str(record.get("cause") or ""))


@dataclass(frozen=True)
class ProgramRow:
    """One liquidity program: the market and its Time Period (epoch seconds), reward in dollars, Target, DF."""

    ticker: str
    start: float
    end: float
    reward: float
    target: float
    discount_factor: float
    program_id: str


def programs_from_record(record: Mapping[str, Any]) -> list[ProgramRow]:
    body = record.get("body")
    rows: list[Any] = []
    if isinstance(body, Mapping) and isinstance(body.get("incentive_programs"), list):
        rows = list(body["incentive_programs"])
    elif record.get("kind") in ("incentives", "incentive_programs", "programs"):
        for key in ("rows", "incentive_programs", "added", "changed"):
            value = record.get(key)
            if isinstance(value, list):
                rows.extend(value)
    out: list[ProgramRow] = []
    for row in rows:
        if not isinstance(row, Mapping) or row.get("incentive_type", "liquidity") != "liquidity":
            continue
        ticker = row.get("market_ticker")
        start, end = when(row.get("start_date")), when(row.get("end_date"))
        reward, target = number(row.get("period_reward")), number(row.get("target_size_fp"))
        bps = number(row.get("discount_factor_bps"))
        if (not isinstance(ticker, str) or start is None or end is None or reward is None or target is None
                or bps is None or end <= start):
            continue
        out.append(ProgramRow(ticker, start, end, reward / 10000.0, target, bps / 10000.0, str(row.get("id") or "")))
    return out


@dataclass
class MarketFacts:
    """What is known of one market: its window, strike, result and settlement value (merged from every row)."""

    ticker: str
    open_ts: float | None = None
    close_ts: float | None = None
    floor_strike: float | None = None
    result: str | None = None  # "yes" / "no" once settled
    expiration_value: float | None = None
    settlement_ts: float | None = None
    status: str | None = None

    def merge(self, row: Mapping[str, Any]) -> None:
        for key, attr in (("open_time", "open_ts"), ("close_time", "close_ts"), ("settlement_ts", "settlement_ts")):
            value = when(row.get(key))
            if value is not None:
                setattr(self, attr, value)
        for key in ("floor_strike", "expiration_value"):
            value = number(row.get(key))
            if value is not None:
                setattr(self, key, value)
        result = row.get("result")
        if result in ("yes", "no"):
            self.result = result
        status = row.get("status")
        if isinstance(status, str) and status:
            self.status = status


def market_rows_from_record(record: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    """``(ticker, row)`` pairs from a market-row record of any of the recorder's shapes."""
    if record.get("kind") not in ("sweep", "discovery_markets", "settlement", "markets", "market", "lip_markets"):
        return []
    rows = record.get("rows")
    if rows is None and isinstance(record.get("body"), Mapping):
        rows = record["body"].get("markets")
    out: list[tuple[str, Mapping[str, Any]]] = []
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        inner = row.get("full") if isinstance(row.get("full"), Mapping) else row.get("dyn")
        data = inner if isinstance(inner, Mapping) else row
        ticker = row.get("ticker", data.get("ticker"))
        if isinstance(ticker, str):
            out.append((ticker, data))
    return out


@dataclass(frozen=True)
class PythTick:
    """One Pyth price as we received it: the aggregate price (never the confidence), our receive time, the source."""

    symbol: str
    at: float  # OUR receive time (seconds)
    price: float
    source: str
    publish: float | None = None  # the publisher's own time, when given (never used for timing)


def _scaled(price: Any, expo: Any) -> float | None:
    value, power = number(price), number(expo)
    if value is None:
        return None
    if power is None:
        return value
    return value * 10.0 ** power


def _symbol(item: Mapping[str, Any]) -> str | None:
    for key in ("symbol", "underlying_ticker", "pyth_symbol"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    for key in ("id", "feed_id", "hermes_id"):
        value = item.get(key)
        if isinstance(value, str):
            known = HERMES_SYMBOL.get(value.lower().removeprefix("0x"))
            if known:
                return known
    for key in ("priceFeedId", "pro_id", "feed_id"):
        value = item.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value in PRO_SYMBOL:
            return PRO_SYMBOL[value]
    return None


def parse_pyth(record: Mapping[str, Any]) -> list[PythTick]:
    """Every Pyth price a record carries (see the module docstring for the shapes), timed by our receive time."""
    at = number(record.get("received_at"))
    if at is None:
        at = number(record.get("at"))
    if at is None:
        return []
    tag = record.get("source") if isinstance(record.get("source"), str) else None
    out: list[PythTick] = []

    def add(symbol: str | None, price: float | None, source: str, publish: float | None = None,
            stamp: float | None = None) -> None:
        if symbol and price is not None and price > 0:
            out.append(PythTick(symbol, at if stamp is None else stamp, price, tag or source, publish))

    columns, rows = record.get("columns"), record.get("rows")
    if isinstance(columns, list) and isinstance(rows, list) and "price" in columns and "id" in columns:
        # the recorder's pyth lane: {"columns": [id, price, conf, expo, publish_time, ...], "rows": [[...], ...]}
        stream = "pyth_hermes"
        for values in rows:
            if not isinstance(values, (list, tuple)) or len(values) != len(columns):
                continue
            cells = dict(zip(columns, values, strict=True))
            add(_symbol(cells), _scaled(cells.get("price"), cells.get("expo")), stream, when(cells.get("publish_time")),
                number(cells.get("received_at")))
        return out
    payloads: list[Mapping[str, Any]] = [record]
    for key in ("updates", "messages", "data"):
        value = record.get(key)
        if isinstance(value, list):
            payloads.extend(item for item in value if isinstance(item, Mapping))
    for item in payloads:
        stamp = number(item.get("received_at")) if item is not record else None
        parsed = item.get("parsed")
        if isinstance(parsed, list):  # Hermes: {"parsed": [{"id", "price": {"price", "expo", "publish_time"}}]}
            for feed in parsed:
                if not isinstance(feed, Mapping) or not isinstance(feed.get("price"), Mapping):
                    continue
                quote = feed["price"]
                add(_symbol(feed), _scaled(quote.get("price"), quote.get("expo")), "pyth_hermes",
                    when(quote.get("publish_time")), stamp)
        msg = item.get("msg")
        if isinstance(msg, Mapping) and "value_usd" in msg:  # Kalshi pyth_value
            add(_symbol(msg), number(msg.get("value_usd")), "kalshi_pyth_value", when(msg.get("source_ts_ms")), stamp)
        feeds = item.get("priceFeeds")
        if isinstance(feeds, list):  # Pyth Pro (Lazer)
            publish = when(item.get("timestampUs"))
            for feed in feeds:
                if isinstance(feed, Mapping):
                    add(_symbol(feed), _scaled(feed.get("price"), feed.get("exponent")), "pyth_pro", publish, stamp)
        if item is not record and "price" in item and not isinstance(item.get("price"), Mapping):
            add(_symbol(item), _scaled(item.get("price"), item.get("expo")), "pyth", when(item.get("publish_time")),
                stamp)
    if "price" in record and not isinstance(record.get("price"), Mapping):  # a flat row
        add(_symbol(record), _scaled(record.get("price"), record.get("expo")), "pyth",
            when(record.get("publish_time")))
    return out


@dataclass(frozen=True)
class LivePoint:
    """One point of Kalshi's free 1 s settlement series: Pyth's second ``label`` and its value (the last Pyth price
    in [label, label + 1); FX research section 1.2). Usable only as a quick look: a bot cannot receive it in time."""

    series: str
    label: float
    value: float


def live_points_from_record(record: Mapping[str, Any]) -> list[LivePoint]:
    if record.get("kind") == "series" and isinstance(record.get("new"), list):  # the recorder's lip lane
        name = record.get("series") or record.get("event_ticker")
        series = series_of(name) if isinstance(name, str) else None
        if series is None:
            return []
        points = []
        for item in record["new"]:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                label, value = when(item[0]), number(item[1])
                if label is not None and value is not None:
                    points.append(LivePoint(series, label, value))
        return points
    holder: Any = record.get("body") if isinstance(record.get("body"), Mapping) else record
    live = holder.get("live_data") if isinstance(holder, Mapping) else None
    details = live.get("details") if isinstance(live, Mapping) else None
    if not isinstance(details, Mapping):
        return []
    event = details.get("event_ticker") or record.get("event_ticker")
    series = series_of(event) if isinstance(event, str) else None
    if series is None:
        return []
    out = []
    for point in details.get("timeseries") or []:
        if isinstance(point, Mapping):
            label, value = when(point.get("t")), number(point.get("v"))
            if label is not None and value is not None:
                out.append(LivePoint(series, label, value))
    return out


# ---------------------------------------------------------------------- reading the recorder's files
_SEGMENT = re.compile(r"^(?P<lane>[a-z0-9_]+)-(?P<stamp>\d{8}T\d{6}Z)-(?P<seq>\d+)\.jsonl\.gz(?:\.part)?$")


def segment_start(name: str) -> float | None:
    """A segment file's UTC start from its name (``books-20261013T190000Z-000000000123.jsonl.gz``)."""
    match = _SEGMENT.match(name)
    if not match:
        return None
    return datetime.strptime(match.group("stamp"), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).timestamp()


def _inflate(decoder: Any, data: bytes) -> tuple[bytes, bool]:
    """``(output, broken)``: what ``data`` decodes to; at a corrupt byte (compressed garbage or zeros after a host
    crash) the longest prefix that still decodes, and ``broken``."""
    backup = decoder.copy()  # a decoder that raised is unusable: search from the state before it
    try:
        return decoder.decompress(data), False
    except zlib.error:
        pass
    low, high = 0, len(data)  # the longest prefix that decodes: low always does, high never does
    while high - low > 1:
        middle = (low + high) // 2
        try:
            backup.copy().decompress(data[:middle])
            low = middle
        except zlib.error:
            high = middle
    try:
        return backup.decompress(data[:low]), True
    except zlib.error:
        return b"", True


def _complete_lines(path: Path) -> Iterator[bytes]:
    """The complete lines of a gzip file that may still be written (a ``.part`` flushed with Z_SYNC_FLUSH) or that
    a crash cut short: whatever decodes, up to the last newline."""
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    tail = b""
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1 << 16)
            if not chunk:
                break
            data, broken = _inflate(decoder, chunk)
            tail += data
            *lines, tail = tail.split(b"\n")
            yield from lines
            if broken or decoder.eof:
                break


def _records(path: Path) -> Iterator[dict[str, Any]]:
    for line in _complete_lines(path):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            yield row


def _index(root: Path) -> dict[str, str]:
    """Sealed segment path -> its recorded SHA-256 (deleted ones removed)."""
    out: dict[str, str] = {}
    path = root / "index.jsonl"
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.endswith("\n"):
                break
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("kind") == "segment" and isinstance(row.get("path"), str):
                out[row["path"]] = str(row.get("sha256") or "")
            elif row.get("kind") == "deleted":
                out.pop(str(row.get("path")), None)
    return out


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def segment_files(root: Path, lanes: Iterable[str], *, start: float = -math.inf, end: float = math.inf,
                  parts: bool = True) -> list[Path]:
    """Segment files of the named lanes that may hold records in ``[start, end]``, oldest first per lane. A
    segment's records begin at its start (its name) and end before the next segment of its lane begins (or within
    the hour, or later for the open one)."""
    chosen: list[tuple[float, str, Path]] = []
    for lane in dict.fromkeys(lanes):
        directory = root / "segments" / lane
        if not directory.is_dir():
            continue
        files = sorted((path for path in directory.glob("*/*") if _SEGMENT.match(path.name)
                        and (parts or not path.name.endswith(".part"))),
                       key=lambda path: (segment_start(path.name) or 0.0, path.name))
        for index, path in enumerate(files):
            begin = segment_start(path.name) or 0.0
            later = segment_start(files[index + 1].name) if index + 1 < len(files) else None
            finish = later if later is not None else math.inf
            if begin <= end and finish >= start:
                chosen.append((begin, lane, path))
    return [path for _, _, path in sorted(chosen, key=lambda item: (item[0], item[1], item[2].name))]


def read_records(root: Path | str, lanes: Iterable[str] = ALL_LANES, *, start: float = -math.inf,
                 end: float = math.inf, verify: bool = True, parts: bool = True) -> list[dict[str, Any]]:
    """Every record of the named lanes with ``at`` in ``[start, end]``, sorted by ``(at, seq)``. A sealed segment
    named in ``index.jsonl`` is checked against its SHA-256 first (``verify``; a mismatch raises). Open ``.part``
    files are read up to their last complete line (``parts``)."""
    base = Path(root)
    index = _index(base) if verify else {}
    out: list[dict[str, Any]] = []
    for path in segment_files(base, lanes, start=start, end=end, parts=parts):
        relative = str(path.relative_to(base))
        if verify and relative in index and index[relative] and _sha256(path) != index[relative]:
            raise ValueError(f"Recorder segment {relative} does not match its index hash")
        for record in _records(path):
            at = number(record.get("at"))
            if at is not None and start <= at <= end:
                out.append(record)
    out.sort(key=lambda row: (float(row["at"]), int(row.get("seq") or 0)))
    return out


@dataclass
class _LaneTail:
    file: str | None = None  # the segment's sealed name (without .part)
    part: bool = False
    offset: int = 0
    decoder: Any = None
    tail: bytes = b""
    last_seq: int = -1


@dataclass
class RecorderTail:
    """New records of the named lanes as the recorder writes them, read incrementally from the open ``.part`` and
    then from the sealed file. A record is never returned twice (``seq`` only grows); when a segment is sealed (or
    re-sealed after a crash) under its final name it is read again from the start and the records already returned
    are skipped. Starts at the segments that may hold records at or after ``start``."""

    root: Path
    lanes: Sequence[str] = ALL_LANES
    start: float = -math.inf
    lanes_state: dict[str, _LaneTail] = field(default_factory=dict)

    def poll(self, max_records: int = 200_000) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for lane in dict.fromkeys(self.lanes):
            out.extend(self._lane(lane, max_records - len(out)))
            if len(out) >= max_records:
                break
        out.sort(key=lambda row: (float(row.get("at") or 0.0), int(row.get("seq") or 0)))
        return out

    def _files(self, lane: str) -> list[str]:
        directory = self.root / "segments" / lane
        if not directory.is_dir():
            return []
        names = {path.name.removesuffix(".part"): path.parent for path in directory.glob("*/*")
                 if _SEGMENT.match(path.name)}
        ordered = sorted(names, key=lambda name: (segment_start(name) or 0.0, name))
        return [str(names[name] / name) for name in ordered]

    def _lane(self, lane: str, budget: int) -> list[dict[str, Any]]:
        state = self.lanes_state.setdefault(lane, _LaneTail())
        files = self._files(lane)
        if not files or budget <= 0:
            return []
        if state.file is None:
            starts = [segment_start(Path(name).name) or 0.0 for name in files]
            first = max([index for index, begin in enumerate(starts) if begin <= self.start] or [0])
            state.file = files[first]
        out: list[dict[str, Any]] = []
        while state.file is not None and len(out) < budget:
            sealed, part = Path(state.file), Path(state.file + ".part")
            if part.exists():
                path, is_part = part, True
            elif sealed.exists():
                path, is_part = sealed, False
            else:
                path, is_part = None, False
            if path is not None and state.part and not is_part:  # sealed since: read it again from its start
                state.offset, state.decoder, state.tail = 0, None, b""
            state.part = is_part
            done = path is None
            if path is not None:
                done = self._read(path, state, out) and not is_part
            if not done:
                break
            later = [name for name in files if (segment_start(Path(name).name) or 0.0, name)
                     > (segment_start(Path(state.file).name) or 0.0, state.file)]
            if not later:
                break
            state.file, state.offset, state.decoder, state.tail, state.part = later[0], 0, None, b"", False
        return out

    @staticmethod
    def _read(path: Path, state: _LaneTail, out: list[dict[str, Any]]) -> bool:
        """New complete lines of ``path`` from ``state.offset``; True when the gzip stream ended."""
        if state.decoder is None:
            state.decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            with path.open("rb") as stream:
                stream.seek(state.offset)
                data = stream.read()
        except OSError:
            return False
        state.offset += len(data)
        decoded, broken = _inflate(state.decoder, data)
        state.tail += decoded
        *lines, state.tail = state.tail.split(b"\n")
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            seq = row.get("seq")
            if isinstance(seq, int) and not isinstance(seq, bool):
                if seq <= state.last_seq:
                    continue
                state.last_seq = seq
            out.append(row)
        return broken or bool(state.decoder.eof)  # a broken file: what came before stands; move on


def write_segment(path: Path, records: Iterable[Mapping[str, Any]], *, sealed: bool = True) -> None:
    """A recorder-shaped segment (tests and replays of other recordings): JSON lines, gzip; open when not sealed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"".join((json.dumps(dict(row), separators=(",", ":")) + "\n").encode() for row in records)
    if sealed:
        path.write_bytes(gzip.compress(payload, mtime=0))
        return
    encoder = zlib.compressobj(6, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
    path.write_bytes(encoder.compress(payload) + encoder.flush(zlib.Z_SYNC_FLUSH))
