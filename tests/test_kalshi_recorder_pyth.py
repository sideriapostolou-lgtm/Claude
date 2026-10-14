"""The recorder's Pyth lane: Hermes' SSE stream, every update with its receive time, reconnects and gaps, channel
step-downs, and above all the key: it reaches only a Pyth host's Authorization header and never a byte on disk or
a log record. Fake transports only; nothing touches the network.
"""

from __future__ import annotations

import gzip
import json
import logging
import threading
from pathlib import Path
from typing import Any

import pytest
from kalshi_recorder_fixtures import NOW, Clock
from test_kalshi_recorder import Session as KalshiSession
from test_kalshi_recorder import records, run, venue

from nightcrawler.kalshi_public import PublicKalshi, RateLimiter
from nightcrawler.kalshi_recorder import (
    READ_ONLY_KEYS,
    Recorder,
    RecorderSettings,
    main,
    trading_names,
)
from nightcrawler.kalshi_recorder_pyth import (
    CHANNELS,
    FEEDS,
    KEY_REFUSED_WAIT_S,
    NOT_ENTITLED_WAIT_S,
    PYTH_BASES,
    STREAM_PATH,
    PythKey,
    PythStream,
    parse_updates,
    plan_streams,
    sse_data,
)

KEY = "pk_TEST-0123456789abcdef-SENTINEL-KEY-zz9"
EUR, JPY = FEEDS[0], FEEDS[2]


def message(*updates: tuple[str, str, str, int, int], binary: str = "504e4155") -> bytes:
    """One Hermes SSE event: data:<json>\\n\\n with a parsed list (and the binary blob the recorder ignores)."""
    parsed = [{"id": feed, "price": {"price": price, "conf": conf, "expo": expo, "publish_time": published},
               "ema_price": {"price": price, "conf": conf, "expo": expo, "publish_time": published},
               "metadata": {"slot": 1, "proof_available_time": published, "prev_publish_time": published - 1}}
              for feed, price, conf, expo, published in updates]
    return b"data:" + json.dumps({"binary": {"encoding": "hex", "data": [binary]}, "parsed": parsed}).encode() + b"\n\n"


class Body:
    """A streamed body: ``read1`` hands out one scripted chunk at a time (an exception is raised when reached)."""

    def __init__(self, chunks: list[Any], clock: Clock | None = None, step: float = 0.0) -> None:
        self.chunks, self.clock, self.step = list(chunks), clock, step

    def read1(self, size: int) -> bytes:
        if self.clock is not None:
            self.clock.at += self.step
        if not self.chunks:
            return b""
        item = self.chunks.pop(0)
        if isinstance(item, BaseException):
            raise item
        return bytes(item)


class Reply:
    def __init__(self, status: int, chunks: list[Any], clock: Clock | None = None, step: float = 0.0) -> None:
        self.status_code, self.headers = status, {}
        self.raw = Body(chunks, clock, step)
        self.closed = False

    def close(self) -> None:
        self.closed = True


class PythSession:
    """A scripted Hermes: each GET takes the next item (a Reply, or an exception to raise); then ``stop`` is set."""

    def __init__(self, script: list[Any], stop: threading.Event | None = None) -> None:
        self.script, self.stop = list(script), stop
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, params: Any = None, headers: Any = None, **kwargs: Any) -> Any:
        self.calls.append({"url": url, "params": list(params or []), "headers": dict(headers or {}), **kwargs})
        if not self.script:
            if self.stop is not None:
                self.stop.set()
            raise ConnectionError("script over")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self) -> None:
        pass


class Sink:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, dict[str, Any]]] = []
        self.gaps: list[dict[str, Any]] = []

    def emit(self, lane: str, kind: str, payload: dict[str, Any], at: float | None = None) -> int:
        self.rows.append((lane, kind, payload))
        return len(self.rows)

    def gap(self, lane: str, start: float | None, end: float | None, cause: str, **extra: Any) -> None:
        self.gaps.append({"gap_lane": lane, "from": start, "to": end, "cause": cause, **extra})

    def kinds(self, kind: str) -> list[dict[str, Any]]:
        return [payload for _, name, payload in self.rows if name == kind]


def stream_for(script: list[Any], clock: Clock, sink: Sink, *, channel: str = "real_time",
               feeds: tuple[Any, ...] = (EUR, JPY)) -> tuple[PythStream, PythSession, threading.Event, list[float]]:
    stop = threading.Event()
    session = PythSession(script, stop)
    waits: list[float] = []

    def pause(event: threading.Event, seconds: float) -> None:
        waits.append(seconds)
        clock.at += seconds

    stream = PythStream("test", feeds, channel, base=PYTH_BASES[0], key=PythKey(KEY), emit=sink.emit, gap=sink.gap,
                        allowed=lambda: True, session_factory=lambda: session, wall=clock.wall, pause=pause)
    return stream, session, stop, waits


# --------------------------------------------------------------------------- parsing
def test_sse_events_survive_any_chunking_comments_and_crlf() -> None:
    raw = (b": keep-alive\r\n\r\n" + message((EUR.hermes_id, "116234", "12", -5, 1791930600))
           + b"data: line one\ndata: line two\n\n" + b"event: x\nid: 7\ndata:{}\r\n\r\n")
    for size in (1, 2, 7, 64, len(raw)):
        chunks = [raw[index:index + size] for index in range(0, len(raw), size)]
        events = list(sse_data(chunks))
        assert len(events) == 3 and events[1] == "line one\nline two" and events[2] == "{}"
        assert json.loads(events[0])["parsed"][0]["price"]["price"] == "116234"
    assert list(sse_data([b"data: torn at the end"])) == []  # an event without its blank line is never guessed


def test_updates_keep_pyth_integer_strings_and_skip_what_cannot_be_read() -> None:
    payload = message((EUR.hermes_id, "116234", "12", -5, 1791930600), ("0x" + JPY.hermes_id.upper(), "151230",
                                                                         "9", -3, 1791930601))[5:-2].decode()
    rows, bad = parse_updates(payload)
    assert rows == [[EUR.hermes_id, "116234", "12", -5, 1791930600, 1791930599],
                    [JPY.hermes_id, "151230", "9", -3, 1791930601, 1791930600]] and bad == 0
    broken = json.dumps({"parsed": [{"id": EUR.hermes_id, "price": {"price": 116234, "conf": "1", "expo": -5,
                                                                    "publish_time": 1}}, "nonsense"]})
    assert parse_updates(broken) == ([], 2)
    with pytest.raises(TypeError):
        parse_updates(json.dumps({"binary": {}}))
    with pytest.raises(ValueError):
        parse_updates('{"parsed": [], "x": NaN}')


def test_feeds_are_the_nine_kalshi_settles_on_grouped_by_the_channel_each_allows() -> None:
    assert {feed.kalshi_series for feed in FEEDS} == {
        "KXEURUSD15M", "KXGBPUSD15M", "KXUSDJPY15M", "KXAUDUSD15M", "KXUSDCAD15M", "KXCOPPER15M", "KXPLATINUM15M",
        "KXPALLADIUM15M", "KXNATGAS15M"}
    assert all(len(feed.hermes_id) == 64 and int(feed.hermes_id, 16) >= 0 for feed in FEEDS)
    groups = plan_streams("real_time")
    assert {feed.symbol for feed in groups["real_time"]} == {"FX.EUR/USD", "FX.USD/JPY", "FX.AUD/USD"}
    assert {feed.symbol for feed in groups["fixed_rate@50ms"]} == {"Commodities.Index.CU/USD",
                                                                   "Commodities.Index.NATGAS/USD"}
    assert len(groups["fixed_rate@200ms"]) == 4
    assert list(plan_streams("fixed_rate@1000ms")) == ["fixed_rate@1000ms"]


# --------------------------------------------------------------------------- the stream
def test_every_update_is_recorded_with_its_receive_time_in_one_second_batches() -> None:
    clock, sink = Clock(NOW), Sink()
    events = [message((EUR.hermes_id, str(116230 + index), "12", -5, int(NOW) + index // 4)) for index in range(10)]
    stream, session, stop, _ = stream_for([Reply(200, events, clock, 0.25)], clock, sink)
    stream.run(stop)
    rows = [row for batch in sink.kinds("updates") for row in batch["rows"]]
    assert [row[1] for row in rows] == [str(116230 + index) for index in range(10)]  # every update, in order
    assert [row[-1] for row in rows] == [NOW + 0.25 * (index + 1) for index in range(10)]  # its receive time
    assert all(batch["columns"][-1] == "received_at" and batch["channel"] == "real_time"
               for batch in sink.kinds("updates"))
    assert len(sink.kinds("updates")) >= 2  # batched about once a second, not one record per update
    call = session.calls[0]
    assert call["url"] == PYTH_BASES[0] + STREAM_PATH and call["allow_redirects"] is False and call["stream"]
    assert ("channel", "real_time") in call["params"] and ("ids[]", EUR.hermes_id) in call["params"]
    assert call["headers"]["Authorization"] == "Bearer " + KEY  # the only place the key ever goes


def test_reconnects_back_off_and_each_silence_is_one_gap_with_its_cause() -> None:
    clock, sink = Clock(NOW), Sink()
    one = [message((EUR.hermes_id, "116230", "12", -5, int(NOW)))]
    two = [message((EUR.hermes_id, "116240", "12", -5, int(NOW) + 50))]
    script = [ConnectionError("no route"), Reply(200, one), Reply(200, [TimeoutError("read timed out")]),
              Reply(503, [b"busy"]), Reply(200, two)]
    stream, _, stop, waits = stream_for(script, clock, sink)
    stream.run(stop)
    assert [gap["cause"] for gap in sink.gaps] == ["pyth_connect_ConnectionError", "pyth_server_closed"]
    assert sink.gaps[1]["last_cause"] == "http_503" and sink.gaps[1]["attempts"] == 4
    first, second = sink.gaps
    assert first["before_first_update"] and first["from"] == NOW and first["to"] >= NOW
    assert not second["before_first_update"] and second["from"] < second["to"]  # last update to the next one
    assert waits[:4] == [2.0, 4.0, 8.0, 16.0]  # 2^n, n = connections in a row without a healthy run
    downs = [row for row in sink.kinds("connection") if row["event"] == "disconnected"]
    assert [row["cause"] for row in downs][:4] == ["connect_ConnectionError", "server_closed", "read_TimeoutError",
                                                   "http_503"]
    assert len(sink.kinds("first_update")) == 1


def test_a_refused_key_waits_fifteen_minutes_and_is_logged_without_the_key(caplog: pytest.LogCaptureFixture) -> None:
    clock, sink = Clock(NOW), Sink()
    stream, _, stop, waits = stream_for([Reply(401, [f"unauthorized: token {KEY} is invalid".encode()])], clock, sink)
    with caplog.at_level(logging.INFO, logger="nightcrawler.kalshi_recorder"):
        stream.run(stop)
    assert waits[0] == KEY_REFUSED_WAIT_S
    down = next(row for row in sink.kinds("connection") if row["event"] == "disconnected")
    assert down["status"] == 401 and "<redacted>" in down["detail"] and KEY not in down["detail"]
    assert "kalshi_recorder_pyth_key_refused" in caplog.text and KEY not in caplog.text


def test_a_channel_the_plan_lacks_steps_the_stream_down_until_one_answers() -> None:
    clock, sink = Clock(NOW), Sink()
    ok = [message((EUR.hermes_id, "116230", "12", -5, int(NOW)))]
    script = [Reply(403, [b"channel not allowed"]), Reply(400, [b"bad channel"]), Reply(200, ok)]
    stream, session, stop, waits = stream_for(script, clock, sink)
    stream.run(stop)
    asked = [dict(call["params"])["channel"] for call in session.calls]
    assert asked[:3] == ["real_time", "fixed_rate@50ms", "fixed_rate@200ms"]
    assert [row["previous"] for row in sink.kinds("channel_downgraded")] == ["real_time", "fixed_rate@50ms"]
    assert waits[:2] == [1.0, 1.0] and stream.channel == "fixed_rate@200ms"
    # Refused even on the slowest channel: the feeds are not in the plan; it asks again half an hour later.
    clock2, sink2 = Clock(NOW), Sink()
    slow, _, stop2, waits2 = stream_for([Reply(403, [b"no"])], clock2, sink2, channel=CHANNELS[-1])
    slow.run(stop2)
    assert waits2[0] == NOT_ENTITLED_WAIT_S and not sink2.kinds("channel_downgraded")


def test_only_an_allowlisted_https_pyth_host_can_receive_the_key() -> None:
    sink = Sink()
    for base in ("https://evil.example/hermes", "http://hermes.pyth.network", "https://hermes.pyth.network.evil.io"):
        with pytest.raises(ValueError, match="allowlisted"):
            PythStream("x", FEEDS, "real_time", base=base, key=PythKey(KEY), emit=sink.emit, gap=sink.gap,
                       allowed=lambda: True)
    assert RecorderSettings(pyth_base="https://evil.example/hermes").problems()


def test_the_key_prints_redacted_and_an_unusable_value_is_refused_without_echo() -> None:
    key = PythKey(KEY)
    assert KEY not in repr(key) and KEY not in str(key) and KEY not in f"{key!r} {key}"
    assert KEY not in repr({"key": key}) and key.redact(f"x{KEY}y") == "x<redacted>y"
    with pytest.raises(TypeError):
        import pickle

        pickle.dumps(key)
    assert PythKey.from_env({}) is None and PythKey.from_env({"PYTH_API_KEY": "   "}) is None
    for bad in ("two words", "line\nbreak", "tab\tkey"):
        with pytest.raises(ValueError) as caught:
            PythKey(bad)
        assert bad not in str(caught.value)


# --------------------------------------------------------------------------- the recorder with and without a key
def hermes_script(clock: Clock) -> list[Any]:
    leaky = OSError(f"connection reset while sending Authorization: Bearer {KEY}")  # an error text with the key
    updates = [message((EUR.hermes_id, str(116230 + index), "12", -5, int(NOW) + index)) for index in range(6)]
    return [Reply(401, [f'{{"error": "token {KEY} rejected"}}'.encode()]), leaky,
            Reply(200, updates, clock, 0.4), Reply(200, [RuntimeError(f"stream broke near {KEY}")])]


def every_written_byte(root: Path) -> bytes:
    out = b""
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        out += raw
        if path.name.endswith((".gz", ".gz.part")):
            try:
                out += gzip.decompress(raw)
            except (EOFError, OSError):  # an open segment: decode what is complete
                import zlib

                out += zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw)
    return out


def test_the_key_never_appears_in_any_written_byte_or_log_record(tmp_path: Path,
                                                                 caplog: pytest.LogCaptureFixture) -> None:
    """A hostile Hermes: a 401 whose body echoes the key, connection and read errors whose text carries it."""
    clock = Clock(NOW)
    stop = threading.Event()
    session = PythSession(hermes_script(clock), stop)
    fake = venue()
    client = PublicKalshi(RateLimiter(2.0, clock=clock.mono, sleep=clock.sleep), session=KalshiSession(fake),
                          wall=clock.wall, mono=clock.mono)
    with caplog.at_level(logging.DEBUG):
        box = Recorder(RecorderSettings(data_dir=tmp_path, btc15m=False), client=client, wall=clock.wall,
                       pyth_key=PythKey(KEY), pyth_session=lambda: session)
        assert box.pyth is not None and KEY not in repr(box.pyth.status())
        stream = box.pyth.streams[0]
        stream._pause = lambda event, seconds: None
        box.pyth_open = True
        stream.run(stop)  # in this thread, until the script is used up
        run(box, clock, 120)  # the Kalshi lanes, status files and a manifest around it
        box.close()
    assert len(session.calls) == 5 and all(call["headers"]["Authorization"] == "Bearer " + KEY
                                           and call["url"].startswith(PYTH_BASES[0]) for call in session.calls)
    assert fake.calls and not any("Authorization" in call["headers"] for call in fake.calls)  # Kalshi: keyless
    data = every_written_byte(tmp_path)
    assert b'"updates"' in data and b"116235" in data  # the stream was recorded
    assert b"<redacted>" in data and b"connect_OSError" in data and b"read_RuntimeError" in data
    assert KEY.encode() not in data and KEY[8:30].encode() not in data
    texts = [caplog.text] + [record.getMessage() for record in caplog.records]
    texts += [repr(record.args) for record in caplog.records] + [str(record.__dict__) for record in caplog.records]
    assert "kalshi_recorder_pyth_key_refused" in caplog.text
    assert all(KEY not in text and KEY[8:30] not in text for text in texts)
    status = (tmp_path / "kalshi_recorder" / "status.json").read_text()
    assert '"state":"on"' in status and KEY not in status


def test_without_a_key_the_pyth_lane_is_off_and_silent(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    clock = Clock(NOW)
    fake = venue()
    client = PublicKalshi(RateLimiter(2.0, clock=clock.mono, sleep=clock.sleep), session=KalshiSession(fake),
                          wall=clock.wall, mono=clock.mono)
    box = Recorder(RecorderSettings(data_dir=tmp_path, btc15m=False), client=client, wall=clock.wall)
    stop = threading.Event()
    with caplog.at_level(logging.INFO, logger="nightcrawler.kalshi_recorder"):
        run(box, clock, 60)  # writes status.json
        stop.set()
        box.run(stop)  # logs its start, then closes at once
    assert box.pyth is None
    lines = [record for record in caplog.records if record.getMessage().startswith("kalshi_recorder_pyth")]
    off = "kalshi_recorder_pyth_off reason=no_PYTH_API_KEY (the Pyth lane needs a key; nothing about it is recorded)"
    assert [(record.levelname, record.getMessage()) for record in lines] == [("INFO", off)]  # exactly one line
    assert not records(tmp_path, "pyth")
    assert not [thread for thread in threading.enumerate() if thread.name.startswith("kalshi-recorder-pyth")]
    status = json.loads((tmp_path / "kalshi_recorder" / "status.json").read_text())
    assert status["pyth"]["state"] == "off"


def test_the_trading_key_guard_lets_the_pyth_key_through(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                        capsys: pytest.CaptureFixture[str]) -> None:
    assert "PYTH_API_KEY" in READ_ONLY_KEYS
    assert trading_names(["PYTH_API_KEY", "KALSHI_KEY_ID", "POLYMARKET_US_KEY"]) == ["KALSHI_KEY_ID",
                                                                                    "POLYMARKET_US_KEY"]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PYTH_API_KEY", KEY)
    assert main(["run", "--data-dir", str(tmp_path / "data"), "--max-runtime-s", "0"]) == 0  # started, not refused
    out = capsys.readouterr()
    assert "refusing" not in out.err and KEY not in out.out + out.err
    assert KEY.encode() not in every_written_byte(tmp_path / "data")
    # A trading key next to it is still refused, and the Pyth key's value is never printed either way.
    monkeypatch.setenv("KALSHI_KEY_ID", "SECRET-VALUE-123")
    assert main(["run", "--data-dir", str(tmp_path / "data2"), "--max-runtime-s", "0"]) == 3
    err = capsys.readouterr().err
    assert "KALSHI_KEY_ID" in err and "PYTH_API_KEY" not in err and KEY not in err and "SECRET-VALUE" not in err
