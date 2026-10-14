"""Pyth Hermes price stream for the recorder's rewards (LIP) research lane: read-only, never a trading key.

Kalshi settles its FX, metals and natural-gas 15-minute markets on Pyth (the last aggregate price before the
window closes; ``research/kalshi_rewards``). This lane records Pyth's own updates for those nine feeds with the
host's receive time, so a later analysis can measure whether Pyth moves before Kalshi's books reprice.

* **Source.** Hermes' server-sent-events stream ``GET /v2/updates/price/stream`` at the post-upgrade base URL
  (``https://pyth.dourolabs.app/hermes`` by default; ``https://hermes.pyth.network`` serves the same routes). Since
  2026-08-26 Hermes needs ``Authorization: Bearer <PYTH_API_KEY>``.
* **Off without a key.** With no ``PYTH_API_KEY`` in the environment the recorder never builds this lane: no thread,
  no request, no record, one info line.
* **The key.** It is read once by the entry point into a :class:`PythKey`, which prints as ``<redacted>`` and refuses
  to be pickled. It is sent only in the Authorization header of a GET to an allowlisted Pyth host over https, with
  redirects refused, so it can never follow a redirect elsewhere. It is never logged, never stored in a segment,
  status or manifest file, and never put in an error text: errors are recorded as an exception's type name or an
  HTTP status, and the short excerpt of a Pyth error body is redacted first. It is not a trading key: it can read
  prices and nothing else, so the recorder's trading-key guard lets it through (``kalshi_recorder.READ_ONLY_KEYS``).
* **Records.** Every parsed update (feed id, price, conf, expo, publish_time, prev_publish_time) with the local
  receive time, batched about once a second per stream into the ``pyth`` lane. Prices stay Pyth's integer strings
  (real price = price x 10^expo). ``publish_time`` is whole seconds, so a lead under one second is timed with the
  receive clock.
* **Reconnects and gaps.** A stream that drops (the server closes every stream after 24 h, a read timeout while a
  market is closed, a network error, an HTTP error) reconnects with backoff, and the silence from its last update to
  its next one is a ``gap`` row with the cause. A 401 (the key is refused) waits 15 minutes; a 400 or 403 on a
  channel the plan does not include steps the stream down to the next slower channel, recorded as a row.

Nothing here can place, cancel or amend an order: the only network call is one streaming GET to a Pyth host.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from .kalshi_public import public_session, strict_json

log = logging.getLogger("nightcrawler.kalshi_recorder")

KEY_NAME = "PYTH_API_KEY"
PYTH_BASES = ("https://pyth.dourolabs.app/hermes", "https://hermes.pyth.network")
STREAM_PATH = "/v2/updates/price/stream"
# Hermes channels, fastest first; the default for a request without one is fixed_rate@1000ms.
CHANNELS = ("real_time", "fixed_rate@50ms", "fixed_rate@200ms", "fixed_rate@1000ms")
COLUMNS = ("id", "price", "conf", "expo", "publish_time", "prev_publish_time", "received_at")
BATCH_S = 1.0
CONNECT_TIMEOUT_S = 10.0
READ_TIMEOUT_S = 30.0  # no byte for this long (a closed market, a stalled link): reconnect
MAX_EVENT_BYTES = 4 * 1024 * 1024
KEY_REFUSED_WAIT_S = 900.0
NOT_ENTITLED_WAIT_S = 1800.0
SILENT_WAIT_S = 300.0  # the backoff ceiling once a stream has been without updates for 10 minutes
ERROR_WAIT_S = 60.0
HEALTHY_S = 60.0  # a connection that delivered updates for this long resets the backoff


@dataclass(frozen=True)
class PythFeed:
    """A Pyth feed one of Kalshi's 15-minute series settles on (ids from Pyth's public feed metadata)."""

    symbol: str
    hermes_id: str
    pro_id: int
    expo: int
    min_channel: str
    kalshi_series: str


FEEDS: tuple[PythFeed, ...] = (
    PythFeed("FX.EUR/USD", "a995d00bb36a63cef7fd2c287dc105fc8f3d93779f062f09551b0af3e81ec30b", 327, -5,
             "real_time", "KXEURUSD15M"),
    PythFeed("FX.GBP/USD", "84c2dde9633d93d1bcad84e7dc41c9d56578b7ec52fabedc1f335d673df0a7c1", 333, -5,
             "fixed_rate@200ms", "KXGBPUSD15M"),
    PythFeed("FX.USD/JPY", "ef2c98c804ba503c6a707e38be4dfbb16683775f195b091252bf24693042fd52", 340, -3,
             "real_time", "KXUSDJPY15M"),
    PythFeed("FX.AUD/USD", "67a6f93030420c1c9e3fe37c1ab6b77966af82f995944a9fefce357a22854a80", 315, -5,
             "real_time", "KXAUDUSD15M"),
    PythFeed("FX.USD/CAD", "3112b03a41c910ed446852aacf67118cb1bec67b2cd0b9a214c58cc0eaa2ecca", 338, -5,
             "fixed_rate@200ms", "KXUSDCAD15M"),
    PythFeed("Commodities.Index.CU/USD", "b2b238aeb6ef5a722c5cf278595bf40434e174cac4f88c8ad5b6f5009b548c59", 3525,
             -5, "fixed_rate@50ms", "KXCOPPER15M"),
    PythFeed("Metal.XPT/USD", "398e4bbc7cbf89d6648c21e08019d878967677753b3096799595c78f805a34e5", 1781, -3,
             "fixed_rate@200ms", "KXPLATINUM15M"),
    PythFeed("Metal.XPD/USD", "80367e9664197f37d89a07a804dffd2101c479c7c4e8490501bc9d9e1e7f9021", 1780, -3,
             "fixed_rate@200ms", "KXPALLADIUM15M"),
    PythFeed("Commodities.Index.NATGAS/USD", "45f95717fbe158e896415d1cea33814d73e54169022a8f7bcbb815ebef92f71c",
             3265, -5, "fixed_rate@50ms", "KXNATGAS15M"),
)


def slower(first: str, second: str) -> str:
    """The slower of two Hermes channels."""
    return CHANNELS[max(CHANNELS.index(first), CHANNELS.index(second))]


def allowed_base(base: str) -> bool:
    """Only an allowlisted https Pyth host may ever receive the key."""
    return base in PYTH_BASES and urlsplit(base).scheme == "https"


class PythKey:
    """The Pyth API key. It prints as ``<redacted>`` and is handed out only as an Authorization header."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        token = value.strip() if isinstance(value, str) else ""
        # A token with whitespace or a control character could split a header; it is refused without echoing it.
        if not token or any(char.isspace() or ord(char) < 33 or ord(char) == 127 for char in token):
            raise ValueError(f"{KEY_NAME} is not a usable bearer token")
        self._value = token

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> PythKey | None:
        """The key from ``PYTH_API_KEY``, or None when it is absent or blank (the Pyth lane then stays off)."""
        raw = env.get(KEY_NAME)
        if raw is None or not str(raw).strip():
            return None
        return cls(str(raw))

    def __repr__(self) -> str:
        return "PythKey(<redacted>)"

    __str__ = __repr__

    def __reduce__(self) -> Any:
        raise TypeError("PythKey cannot be pickled")

    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self._value}

    def redact(self, text: str) -> str:
        return text.replace(self._value, "<redacted>")


def sse_data(chunks: Iterable[bytes]) -> Iterator[str]:
    """The ``data`` payload of each server-sent event, yielded as soon as its closing blank line arrives."""
    buffer = b""
    lines: list[str] = []
    for chunk in chunks:
        buffer += chunk
        while (end := buffer.find(b"\n")) >= 0:
            line, buffer = buffer[:end].rstrip(b"\r"), buffer[end + 1:]
            if not line:
                if lines:
                    yield "\n".join(lines)
                    lines = []
                continue
            if line.startswith(b":"):
                continue  # a comment (keep-alive)
            name, _, value = line.partition(b":")
            if name == b"data":
                lines.append(value.removeprefix(b" ").decode("utf-8", "replace"))
        if len(buffer) > MAX_EVENT_BYTES or sum(len(line) for line in lines) > MAX_EVENT_BYTES:
            raise ValueError("Pyth event exceeded the size cap")


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_updates(payload: str) -> tuple[list[list[Any]], int]:
    """``[id, price, conf, expo, publish_time, prev_publish_time]`` per parsed price in one Hermes message, and the
    number of items that could not be read (skipped, never guessed)."""
    body = strict_json(payload.encode())
    items = body.get("parsed") if isinstance(body, dict) else None
    if not isinstance(items, list):
        raise TypeError("Pyth message has no parsed list")
    rows: list[list[Any]] = []
    bad = 0
    for item in items:
        price = item.get("price") if isinstance(item, dict) else None
        meta = item.get("metadata") if isinstance(item, dict) else None
        if not isinstance(price, dict):
            bad += 1
            continue
        feed, value, conf = item.get("id"), price.get("price"), price.get("conf")
        expo, published = _int(price.get("expo")), _int(price.get("publish_time"))
        if (not isinstance(feed, str) or not isinstance(value, str) or not isinstance(conf, str) or expo is None
                or published is None):
            bad += 1
            continue
        previous = _int(meta.get("prev_publish_time")) if isinstance(meta, dict) else None
        rows.append([feed.lower().removeprefix("0x"), value, conf, expo, published, previous])
    return rows, bad


def _chunks(response: Any) -> Iterator[bytes]:
    """The body as it arrives: ``read1`` returns whatever the socket has, so an event is never held back waiting
    for the next one to fill a buffer."""
    raw = getattr(response, "raw", None)
    read1 = getattr(raw, "read1", None)
    if callable(read1):
        while data := read1(65536):
            yield data
    else:
        yield from response.iter_content(chunk_size=None)


class PythStream:
    """One Hermes SSE connection for a group of feeds on one channel; reconnects with backoff and records gaps."""

    def __init__(self, name: str, feeds: Iterable[PythFeed], channel: str, *, base: str, key: PythKey,
                 emit: Callable[..., Any], gap: Callable[..., Any], allowed: Callable[[], bool],
                 session_factory: Callable[[], Any] = public_session, wall: Callable[[], float] = time.time,
                 read_timeout_s: float = READ_TIMEOUT_S,
                 pause: Callable[[threading.Event, float], Any] | None = None) -> None:
        if not allowed_base(base):
            raise ValueError("The Pyth base URL must be one of the allowlisted Pyth hosts")
        if channel not in CHANNELS:
            raise ValueError("Unknown Pyth channel")
        self.name, self.feeds, self.channel = name, tuple(feeds), channel
        self.url = base + STREAM_PATH
        self._key, self._emit, self._gap, self._allowed = key, emit, gap, allowed
        self._session_factory, self.wall, self.read_timeout_s = session_factory, wall, read_timeout_s
        self._pause = pause or (lambda stop, seconds: stop.wait(seconds))
        self._lock = threading.Lock()
        self._response: Any = None
        self._batch: list[list[Any]] = []
        self._batch_started: float | None = None
        self.connected = False
        self.ever_updated = False
        self.last_update_at: float | None = None
        self.down_since: float | None = None  # the start of the current silence (None while updates flow)
        self.cause: str | None = None  # the latest failure of the current silence
        self.first_cause: str | None = None  # the failure that began it
        self.failures = 0  # connections in a row that ended without a healthy run
        self.updates = self.messages = self.unreadable = self.connects = self.dropped = 0
        self.wait_until: float | None = None

    # ------------------------------------------------------------------ records
    def params(self) -> list[tuple[str, str]]:
        return ([("ids[]", feed.hermes_id) for feed in self.feeds]
                + [("parsed", "true"), ("encoding", "hex"), ("channel", self.channel)])

    def _event(self, kind: str, **payload: Any) -> None:
        self._emit("pyth", kind, {"stream": self.name, "channel": self.channel, **payload})

    def add(self, rows: list[list[Any]], received_at: float) -> None:
        with self._lock:
            if self._batch_started is None:
                self._batch_started = received_at
            self._batch.extend([*row, received_at] for row in rows)
            due = received_at - self._batch_started >= BATCH_S
        if due:
            self.flush()

    def flush(self, now: float | None = None) -> None:
        """Write the batch (every update since the last write) as one ``pyth``/``updates`` record."""
        with self._lock:
            if not self._batch or (now is not None and self._batch_started is not None
                                   and now - self._batch_started < BATCH_S):
                return
            batch, self._batch, self._batch_started = self._batch, [], None
        if not self._allowed():
            self.dropped += len(batch)  # shed by the storage cap; the recorder writes the shed as a gap
            return
        self._event("updates", columns=list(COLUMNS), rows=batch)

    # ------------------------------------------------------------------ the connection
    def run(self, stop: threading.Event) -> None:
        session = self._session_factory()
        try:
            while not stop.is_set():
                started = self.wall()
                cause, status, detail = self._connect_once(session, stop)
                self.flush()
                if stop.is_set():
                    break
                healthy = self.last_update_at is not None and self.last_update_at - started >= HEALTHY_S
                self.failures = 1 if healthy else self.failures + 1
                downgraded = self._down(cause, status, detail)
                wait = 1.0 if downgraded else self._wait(cause, status)
                self.wait_until = self.wall() + wait
                self._pause(stop, wait)
        finally:
            self.flush()
            close = getattr(session, "close", None)
            if callable(close):
                close()

    def stop(self) -> None:
        """Unblock a read in progress (closing the response ends it at once)."""
        with self._lock:
            response = self._response
        if response is not None:
            with contextlib.suppress(Exception):  # closing is best effort; the thread is a daemon
                response.close()

    def _connect_once(self, session: Any, stop: threading.Event) -> tuple[str, int | None, str | None]:
        """One connection: (cause it ended, HTTP status, redacted detail). Never raises."""
        headers = {"Accept": "text/event-stream", "Accept-Encoding": "identity",
                   "User-Agent": "nightcrawler-kalshi-recorder/1 (pyth, read-only)", **self._key.headers()}
        try:
            response = session.get(self.url, params=self.params(), headers=headers, stream=True,
                                   timeout=(CONNECT_TIMEOUT_S, self.read_timeout_s), allow_redirects=False)
        except Exception as exc:  # noqa: BLE001 - only the type name is kept: an error text could carry anything
            return f"connect_{type(exc).__name__}", None, None
        with self._lock:
            self._response = response
        try:
            status = int(response.status_code)
            if status != 200:
                return f"http_{status}", status, self._excerpt(response)
            self.connected = True
            self.connects += 1
            self._event("connection", event="connected", attempt=self.failures)
            for payload in sse_data(_chunks(response)):
                received = self.wall()
                self.messages += 1
                try:
                    rows, bad = parse_updates(payload)
                except (ValueError, TypeError, RecursionError):
                    self.unreadable += 1
                    continue
                self.unreadable += bad
                if rows:
                    self._updated(received)
                    self.updates += len(rows)
                    self.add(rows, received)
                if stop.is_set():
                    break
            return "server_closed", status, None
        except Exception as exc:  # noqa: BLE001 - a read timeout or a dropped link; only the type name is kept
            return f"read_{type(exc).__name__}", None, None
        finally:
            self.connected = False
            with self._lock:
                self._response = None
            with contextlib.suppress(Exception):
                response.close()

    def _excerpt(self, response: Any) -> str | None:
        """At most 120 characters of an error body, with the key redacted (never the raw body)."""
        try:
            first = next(_chunks(response), b"")[:512]
        except Exception:  # noqa: BLE001
            return None
        text = " ".join(self._key.redact(first.decode("utf-8", "replace")).split())
        return self._key.redact(text[:120]) or None

    def _updated(self, now: float) -> None:
        """The first update after a silence closes it with one gap row: from the last update (or, before the first
        update ever, from the first failed attempt) to this one."""
        if self.down_since is not None:
            self._gap("pyth", self.down_since, now, f"pyth_{self.first_cause or 'silent'}", stream=self.name,
                      channel=self.channel, attempts=self.failures, last_cause=self.cause,
                      before_first_update=not self.ever_updated)
            log.info("kalshi_recorder_pyth_recovered stream=%s channel=%s down_s=%.1f", self.name, self.channel,
                     now - self.down_since)
        if not self.ever_updated:
            self._event("first_update", feeds=[feed.symbol for feed in self.feeds])
        self.ever_updated = True
        self.down_since, self.cause, self.first_cause = None, None, None
        self.last_update_at = now

    def _down(self, cause: str, status: int | None, detail: str | None) -> bool:
        """Record one connection that ended; True when it stepped the stream down to a slower channel."""
        now = self.wall()
        first = self.down_since is None
        if first:
            self.down_since = self.last_update_at if self.last_update_at is not None else now
            self.first_cause = cause
        changed = cause != self.cause
        self.cause = cause
        self._event("connection", event="disconnected", cause=cause, status=status, detail=detail,
                    attempt=self.failures)
        if status == 401 and (first or changed):
            log.error("kalshi_recorder_pyth_key_refused stream=%s status=401 (check the PYTH_API_KEY variable; "
                      "the key itself is never logged)", self.name)
        elif first or changed:
            log.warning("kalshi_recorder_pyth_down stream=%s channel=%s cause=%s", self.name, self.channel, cause)
        if status in (400, 403):
            index = CHANNELS.index(self.channel)
            if index + 1 < len(CHANNELS):
                # The plan may not include this channel: the next slower one is tried at once (until a restart).
                previous, self.channel = self.channel, CHANNELS[index + 1]
                self._event("channel_downgraded", previous=previous, status=status)
                log.warning("kalshi_recorder_pyth_channel_downgraded stream=%s from=%s to=%s status=%s", self.name,
                            previous, self.channel, status)
                return True
        return False

    def _wait(self, cause: str, status: int | None) -> float:
        if status == 401:
            return KEY_REFUSED_WAIT_S
        if status in (400, 403):
            return NOT_ENTITLED_WAIT_S  # refused even on the slowest channel: these feeds are not in the plan
        ceiling = ERROR_WAIT_S
        if self.down_since is not None and self.wall() - self.down_since >= 600:
            ceiling = SILENT_WAIT_S  # a closed market (a weekend): ask again every few minutes, not every minute
        if cause == "server_closed" and self.failures <= 1:
            return 0.5  # the 24 h close: straight back
        return float(min(ceiling, 2 ** min(self.failures, 12)))

    def status(self) -> dict[str, Any]:
        return {"channel": self.channel, "feeds": [feed.symbol for feed in self.feeds], "connected": self.connected,
                "last_update_at": self.last_update_at, "down_since": self.down_since, "cause": self.cause,
                "updates": self.updates, "messages": self.messages, "unreadable": self.unreadable,
                "connects": self.connects, "dropped": self.dropped, "wait_until": self.wait_until}


def plan_streams(channel: str) -> dict[str, list[PythFeed]]:
    """Feeds grouped by the channel they can stream on: the configured one, or the feed's minimum when slower."""
    groups: dict[str, list[PythFeed]] = {}
    for feed in FEEDS:
        groups.setdefault(slower(channel, feed.min_channel), []).append(feed)
    return groups


class PythLane:
    """Every Pyth stream of the recorder, each in its own daemon thread."""

    def __init__(self, key: PythKey, *, base: str, channel: str, emit: Callable[..., Any], gap: Callable[..., Any],
                 allowed: Callable[[], bool], session_factory: Callable[[], Any] = public_session,
                 wall: Callable[[], float] = time.time, read_timeout_s: float = READ_TIMEOUT_S,
                 pause: Callable[[threading.Event, float], Any] | None = None) -> None:
        self.streams = [PythStream(group, feeds, group, base=base, key=key, emit=emit, gap=gap, allowed=allowed,
                                   session_factory=session_factory, wall=wall, read_timeout_s=read_timeout_s,
                                   pause=pause)
                        for group, feeds in plan_streams(channel).items()]
        self.base, self.preferred = base, channel
        self._stop = threading.Event()
        self.threads: list[threading.Thread] = []

    def start(self) -> list[threading.Thread]:
        for stream in self.streams:
            thread = threading.Thread(target=self._guarded, args=(stream,), name=f"kalshi-recorder-pyth-{stream.name}",
                                      daemon=True)
            thread.start()
            self.threads.append(thread)
        log.info("kalshi_recorder_pyth_on base=%s streams=%s", self.base,
                 ",".join(f"{stream.name}:{len(stream.feeds)}" for stream in self.streams))
        return self.threads

    def _guarded(self, stream: PythStream) -> None:
        try:
            stream.run(self._stop)
        except Exception as exc:  # noqa: BLE001 - a fault here never stops the recorder; only the type is logged
            log.error("kalshi_recorder_pyth_halted stream=%s error=%s", stream.name, type(exc).__name__)

    def flush_due(self, now: float) -> None:
        for stream in self.streams:
            stream.flush(now)

    def stop(self, timeout_s: float = 3.0) -> None:
        self._stop.set()
        for stream in self.streams:
            stream.stop()
        deadline = time.monotonic() + timeout_s
        for thread in self.threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        for stream in self.streams:
            stream.flush()

    def status(self) -> dict[str, Any]:
        return {"state": "on", "base": self.base, "preferred_channel": self.preferred,
                "streams": {stream.name: stream.status() for stream in self.streams}}

