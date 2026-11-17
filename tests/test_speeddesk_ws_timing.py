from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from websockets.client import ClientProtocol
from websockets.datastructures import Headers
from websockets.exceptions import ConcurrencyError
from websockets.frames import Frame, Opcode
from websockets.http11 import Response
from websockets.protocol import OPEN
from websockets.uri import parse_uri

import nightcrawler.speeddesk_ws_timing as timing
from nightcrawler.speeddesk_ws_timing import TimingClientConnection


class Transport(asyncio.Transport):
    def set_write_buffer_limits(self, high: Any = None, low: Any = None) -> None:
        pass

    def pause_reading(self) -> None:
        pass

    def resume_reading(self) -> None:
        pass

    def write(self, data: bytes) -> None:
        pass

    def is_closing(self) -> bool:
        return False


def connection() -> TimingClientConnection:
    protocol = ClientProtocol(parse_uri("ws://example.invalid"), state=OPEN)
    conn = TimingClientConnection(protocol, max_queue=1024)
    conn.connection_made(Transport())
    conn.response = Response(101, "Switching Protocols", Headers())
    return conn


def feed(conn: TimingClientConnection, *frames: Frame) -> None:
    # Exercise the native Sans-I/O parser, ClientConnection event hook and
    # assembler, rather than a fake queue or a replacement recv implementation.
    conn.data_received(b"".join(frame.serialize(mask=False) for frame in frames))


def text(value: str, *, fin: bool = True) -> Frame:
    return Frame(Opcode.TEXT, value.encode(), fin=fin)


@pytest.mark.parametrize("count", [16, 64])
def test_native_burst_preserves_messages_and_exact_ordinals(count: int) -> None:
    async def run() -> None:
        conn = connection()
        feed(conn, *(text(f"message-{i}") for i in range(count)))
        for i in range(count):
            assert await conn.recv() == f"message-{i}"
            receipt = conn.last_receipt
            assert receipt is not None and receipt.ordinal == i + 1
            assert receipt.status == "known"
            assert receipt.accepted_wall <= receipt.received_wall
            assert receipt.residence_ms >= 0
            assert receipt.residence_ms == pytest.approx(
                (receipt.received_monotonic - receipt.accepted_monotonic) * 1000
            )
            json.dumps(receipt.as_dict(), allow_nan=False)
        status = conn.timing_status()
        assert status.pop("max_residence_ms") >= 0
        assert status == {
            "accepted": count, "received": count, "retained": 0,
            "overflow": 0, "unknown": 0, "known": count, "disabled": 0, "errors": 0,
            "unsupported": 0,
        }
    asyncio.run(run())


def test_fragments_control_frames_and_binary_have_one_stamp_per_message() -> None:
    async def run() -> None:
        conn = connection()
        feed(conn, text("hel", fin=False), Frame(Opcode.PING, b"control"))
        assert conn.timing_status()["accepted"] == 0
        feed(conn, Frame(Opcode.CONT, b"lo", fin=False),
             Frame(Opcode.PONG, b"unmatched"), Frame(Opcode.CONT, b"!"),
             Frame(Opcode.BINARY, b"bytes"), text("last"))
        assert [await conn.recv(), await conn.recv(), await conn.recv(decode=False)] == [
            "hello!", b"bytes", b"last",
        ]
        assert conn.last_receipt.ordinal == 3
        assert conn.timing_status()["accepted"] == 3
    asyncio.run(run())


def test_wait_for_timeout_and_fragment_cancellation_keep_alignment() -> None:
    async def run() -> None:
        conn = connection()
        feed(conn, text("part", fin=False))
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(conn.recv(), timeout=0.001)
        assert conn.timing_status()["received"] == 0
        assert conn.last_receipt is None
        feed(conn, Frame(Opcode.CONT, b"done"), text("next"))
        assert await conn.recv() == "partdone"
        assert conn.last_receipt.ordinal == 1
        assert await conn.recv() == "next"
        assert conn.last_receipt.ordinal == 2
        assert conn.last_receipt.status == "known"
    asyncio.run(run())


def test_overflow_does_not_shift_retained_timestamps() -> None:
    async def run() -> None:
        conn = connection()
        feed(conn, *(text(str(i)) for i in range(260)))
        assert conn.timing_status()["retained"] == 256
        assert conn.timing_status()["overflow"] == 4
        retained = tuple(conn._timing_stamps)
        for i in range(260):
            assert await conn.recv() == str(i)
            receipt = conn.last_receipt
            assert receipt.ordinal == i + 1
            assert receipt.status == ("overflow" if i < 4 else "known")
            if i < 4:
                assert receipt.accepted_monotonic is None
            else:
                assert receipt.accepted_monotonic == retained[i - 4][1]
        assert conn.timing_status()["unknown"] == 4
        assert conn.timing_status()["disabled"] == 0
    asyncio.run(run())


@pytest.mark.parametrize("method", ["_observe_event", "_record_receipt"])
def test_diagnostic_exception_never_breaks_native_receive(monkeypatch: Any, method: str) -> None:
    async def run() -> None:
        conn = connection()
        def fail(*args: Any) -> None:
            raise RuntimeError("diagnostic failure")
        monkeypatch.setattr(conn, method, fail)
        feed(conn, text("original"))
        assert await conn.recv() == "original"
        assert conn.timing_status()["errors"] == 1
        assert conn.timing_status()["disabled"] == 1
        assert conn.timing_status()["received"] == 1
        assert conn.timing_status()["unknown"] == 1
        assert not conn._timing_stamps
    asyncio.run(run())


def test_observer_retains_only_numeric_metadata() -> None:
    async def run() -> None:
        conn = connection()
        secret = "sensitive-payload-that-must-not-be-retained"
        feed(conn, text(secret))
        assert await conn.recv() == secret
        observer = {key: value for key, value in vars(conn).items()
                    if key.startswith("_timing_") or key == "last_receipt"}
        assert secret not in repr(observer)
        assert all(isinstance(value, (int, float))
                   for stamp in conn._timing_stamps for value in stamp)
        json.dumps(conn.timing_status(), allow_nan=False)
    asyncio.run(run())


def test_concurrent_readers_preserve_native_error_and_disable_diagnostics() -> None:
    async def run() -> None:
        conn = connection()
        first = asyncio.create_task(conn.recv())
        await asyncio.sleep(0)
        with pytest.raises(ConcurrencyError):
            await conn.recv()
        feed(conn, text("first"))
        assert await first == "first"
        assert conn.last_receipt.status == "disabled"
        assert conn.timing_status()["unsupported"] == 1
    asyncio.run(run())


def test_streaming_preserves_fragments_and_disables_later_timing() -> None:
    async def run() -> None:
        conn = connection()
        feed(conn, text("one", fin=False), Frame(Opcode.CONT, b"two"), text("next"))
        assert [part async for part in conn.recv_streaming()] == ["one", "two"]
        assert await conn.recv() == "next"
        assert conn.last_receipt.status == "disabled"
        assert conn.timing_status()["unsupported"] == 1
    asyncio.run(run())


@pytest.mark.parametrize("values", [(float("nan"), 100.0), (10.0, float("inf")),
                                    (9.0, 100.0), (10.0, 99.0)])
def test_invalid_or_backwards_clocks_disable_without_changing_recv(
    monkeypatch: Any, values: tuple[float, float],
) -> None:
    async def run() -> None:
        conn = connection()
        monkeypatch.setattr(timing, "time", SimpleNamespace(monotonic=lambda: 10.0, time=lambda: 100.0))
        feed(conn, text("first"))
        monkeypatch.setattr(timing, "time", SimpleNamespace(monotonic=lambda: values[0], time=lambda: values[1]))
        assert await conn.recv() == "first"
        assert conn.timing_status()["disabled"] == 1
        assert conn.timing_status()["errors"] == 1
        assert conn.last_receipt is None
    asyncio.run(run())


@pytest.mark.parametrize("values", [(float("nan"), 100.0), (10.0, float("inf")),
                                    (9.0, 100.0), (10.0, 99.0)])
def test_bad_acceptance_clock_disables_without_interrupting_assembler(
    monkeypatch: Any, values: tuple[float, float],
) -> None:
    async def run() -> None:
        conn = connection()
        monkeypatch.setattr(timing, "time", SimpleNamespace(monotonic=lambda: 10.0, time=lambda: 100.0))
        feed(conn, text("first"))
        monkeypatch.setattr(timing, "time", SimpleNamespace(monotonic=lambda: values[0], time=lambda: values[1]))
        feed(conn, text("second"))
        assert await conn.recv() == "first"
        assert await conn.recv() == "second"
        assert conn.timing_status()["errors"] == 1
        assert conn.timing_status()["disabled"] == 1
        assert conn.timing_status()["known"] == 0
    asyncio.run(run())


def test_unexplained_missing_stamp_is_unknown_and_permanently_disables() -> None:
    async def run() -> None:
        conn = connection()
        feed(conn, text("first"), text("second"))
        conn._timing_stamps.popleft()  # Fault injection, not an overflow.
        assert await conn.recv() == "first"
        assert conn.last_receipt.status == "unknown"
        assert conn.last_receipt.accepted_monotonic is None
        assert await conn.recv() == "second"
        assert conn.last_receipt.status == "disabled"
        assert conn.timing_status()["known"] == 0
    asyncio.run(run())


def test_failed_native_recv_does_not_consume_metadata(monkeypatch: Any) -> None:
    from websockets.asyncio.client import ClientConnection

    async def run() -> None:
        conn = connection()
        feed(conn, text("first"))
        original = ClientConnection.recv
        error = RuntimeError("native receive failure")
        async def fail(*args: Any, **kwargs: Any) -> Any:
            raise error
        monkeypatch.setattr(ClientConnection, "recv", fail)
        with pytest.raises(RuntimeError) as raised:
            await conn.recv()
        assert raised.value is error
        assert conn.timing_status()["received"] == 0
        assert conn.timing_status()["retained"] == 1
        monkeypatch.setattr(ClientConnection, "recv", original)
        assert await conn.recv() == "first"
        assert conn.last_receipt.ordinal == 1
        assert conn.last_receipt.status == "known"
    asyncio.run(run())
