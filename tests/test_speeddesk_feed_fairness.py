"""Ready work runs between complete buffered messages, with real parser/assembler paths."""
from __future__ import annotations

import ast
import asyncio
import copy
import inspect
import json
import textwrap
import threading
from types import SimpleNamespace
from typing import Any

import pytest
from test_speeddesk_coinbase import messages
from test_speeddesk_kalshi_ws import (
    START,
    TICKER,
    ack,
    delta,
    print_frame,
    snapshot,
    state,
)
from websockets.asyncio.connection import Connection
from websockets.frames import OP_TEXT, Frame
from websockets.protocol import Protocol, Side

from nightcrawler import speeddesk_feeds, speeddesk_kalshi_ws
from nightcrawler.clock import FakeClock
from nightcrawler.config import Settings
from nightcrawler.speeddesk_feeds import COINBASE_EXCHANGE_WS, COINBASE_WS, LiveFeeds
from nightcrawler.speeddesk_kalshi_ws import KalshiMarketWS, MarketDataGap
from nightcrawler.speeddesk_live import KalshiLiveDesk

NOW = START + 1.2


def without_boundary_yield(method: Any, module: Any) -> Any:
    """Counterfactual removes exactly the new statement; all business code stays actual."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(method)))
    removed = 0
    for node in ast.walk(tree):
        body = getattr(node, 'body', None)
        if isinstance(body, list) and body and ast.unparse(body[-1]) == 'await asyncio.sleep(0)':
            body.pop()
            removed += 1
    assert removed == 1
    namespace: dict[str, Any] = {}
    exec(compile(tree, '<without-message-boundary-yield>', 'exec'), vars(module), namespace)  # noqa: S102
    return namespace[method.__name__]


class Transport:
    def __init__(self) -> None:
        self.pauses = self.resumes = 0

    def pause_reading(self) -> None:
        self.pauses += 1

    def resume_reading(self) -> None:
        self.resumes += 1

    def set_write_buffer_limits(self, *_args: Any) -> None:
        pass

    def write(self, _data: bytes) -> None:
        raise AssertionError('No protocol/network writes are allowed')


class Buffered:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.transport = Transport()
        self.connection = Connection(Protocol(Side.CLIENT, max_size=1_000_000), max_queue=16,
                                     ping_interval=None)
        self.connection.connection_made(self.transport)  # type: ignore[arg-type]
        self.connection.data_received(b''.join(Frame(OP_TEXT, json.dumps(p).encode()).serialize(mask=False)
                                               for p in payloads))
        assert len(self.connection.recv_messages.frames) == len(payloads)
        self.received = 0
        self.sent: list[dict[str, Any]] = []

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def recv(self) -> str | bytes:
        message = await self.connection.recv()
        self.received += 1
        return message


def frames(total: int) -> list[dict[str, Any]]:
    out = []
    book_seq, trade_seq = 2, 0
    for index in range(total):
        if index % 2:
            trade_seq += 1
            row = print_frame(seq=trade_seq, at=NOW)
            row['msg']['trade_id'] = f'unique-{trade_seq}'
        else:
            book_seq += 1
            row = delta(seq=book_seq, at=NOW)
            row['msg']['delta_fp'] = '.01'
        out.append(row)
    return out


def reader(callback: Any, statuses: list[Any], clock: Any = lambda: NOW) -> KalshiMarketWS:
    out = KalshiMarketWS(Settings(kalshi_key_id=None, kalshi_private_key=None),
        tickers=lambda: frozenset({TICKER}), on_book=lambda book: callback('book', book),
        on_trade=lambda trade: callback('trade', trade), on_status=statuses.append, clock=clock)
    out.connected, out.state = True, state()
    return out


@pytest.mark.parametrize('total', [16, 64])
def test_actual_buffered_messages_yield_atomically_and_preserve_full_state(total: int) -> None:
    async def replay(candidate: bool) -> Any:
        ws, stop = Buffered(frames(total)), threading.Event()
        callbacks, statuses, observations = [], [], []
        ready = asyncio.get_running_loop().create_future()
        async def account() -> None:
            await ready
            observations.append((len(callbacks), ws.received))
        task = asyncio.create_task(account())
        await asyncio.sleep(0)
        def callback(kind: str, value: Any) -> None:
            callbacks.append((kind, value))
            if len(callbacks) == 1:
                ready.set_result(None)
            if len(callbacks) == total * 2:
                stop.set()
        feed = reader(callback, statuses)
        method = KalshiMarketWS._session if candidate else without_boundary_yield(
            KalshiMarketWS._session, speeddesk_kalshi_ws)
        await method(feed, ws, frozenset({TICKER}), stop)
        await task
        if candidate:
            assert observations == [(2, 1)]
        else:
            # Python3.11 wait_for schedules recv separately; newer versions can
            # return inline. Correctness requires complete-message boundaries.
            callback_count, received_count = observations[0]
            assert len(observations) == 1 and 1 <= received_count <= total
            assert callback_count == received_count * 2
        assert ws.received == total
        for index in range(total):
            pair = callbacks[index * 2:index * 2 + 2]
            assert [value.side for _, value in pair] == ['up', 'down']
            assert all(value.at == NOW for _, value in pair)
            assert all(kind == ('trade' if index % 2 else 'book') for kind, _ in pair)
        assert all(v.exchange_at == NOW and v.source == 'websocket' for k, v in callbacks if k == 'book')
        assert ws.transport.pauses == ws.transport.resumes == int(total > 16)
        return callbacks, statuses, vars(feed.state), ws.sent
    async def scenario() -> None:
        assert await replay(False) == await replay(True)
    asyncio.run(scenario())


@pytest.mark.parametrize('total', [16, 64])
def test_actual_account_read_wrapper_progresses_before_buffer_is_drained(total: int) -> None:
    async def scenario() -> None:
        ws, stop = Buffered(frames(total)), threading.Event()
        completed = asyncio.get_running_loop().create_future()
        callbacks: list[Any] = []
        cancel_checks: list[int] = []
        desk = object.__new__(KalshiLiveDesk)
        desk.monotonic = asyncio.get_running_loop().time
        desk.read_trace = None
        desk._read_workers, desk._sync_reads = set(), []
        desk.client = SimpleNamespace(read_stats={})
        def start(fn: Any, *args: Any, _read_span: Any = None, **kwargs: Any) -> asyncio.Task[Any]:
            async def worker() -> Any:
                await completed
                return fn(*args, **kwargs)
            return asyncio.create_task(worker())
        async def cancel_unsafe() -> None:
            cancel_checks.append(len(callbacks))
        desk._start_io = start  # type: ignore[method-assign]
        desk._cancel_unsafe = cancel_unsafe  # type: ignore[method-assign]
        observed = []
        async def read() -> None:
            observed.append((await desk._read('fills', lambda: ['fake-fill']), len(callbacks)))
        task = asyncio.create_task(read())
        await asyncio.sleep(0)
        def callback(_kind: str, value: Any) -> None:
            callbacks.append(value)
            if len(callbacks) == 1:
                completed.set_result(None)
            if len(callbacks) == total * 2:
                stop.set()
        feed = reader(callback, [])
        await feed._session(ws, frozenset({TICKER}), stop)
        await task
        assert observed[0][0] == ['fake-fill']
        assert 2 <= observed[0][1] < total * 2 and observed[0][1] % 2 == 0
        assert cancel_checks == [observed[0][1]]
        assert desk._sync_reads[0]['rows'] == 1 and desk._sync_reads[0]['read'] == 'fills'
        assert ws.received == total and len(callbacks) == total * 2
    asyncio.run(scenario())


@pytest.mark.parametrize('reason', ['sequence', 'duplicate', 'stale'])
def test_new_turn_rechecks_sequence_and_freshness_before_next_message(reason: str) -> None:
    async def scenario() -> None:
        clock, callbacks = FakeClock(NOW), []
        payloads = frames(4)
        if reason in ('sequence', 'duplicate'):
            payloads[1] = delta(seq=99 if reason == 'sequence' else 3, at=NOW)
        ws, stop = Buffered(payloads), threading.Event()
        def callback(_kind: str, value: Any) -> None:
            callbacks.append(value)
            if len(callbacks) == 1 and reason == 'stale':
                asyncio.get_running_loop().call_soon(clock.advance, 3.1)
        feed = reader(callback, [], clock.now)
        with pytest.raises(MarketDataGap, match='sequence_gap' if reason != 'stale' else 'timestamp_missing_or_stale'):
            await feed._session(ws, frozenset({TICKER}), stop)
        assert len(callbacks) == 2 and ws.received == 2
    asyncio.run(scenario())


def test_stop_between_messages_finishes_pair_and_skips_buffered_successor() -> None:
    async def scenario() -> None:
        ws, stop, callbacks = Buffered(frames(16)), threading.Event(), []
        def callback(_kind: str, value: Any) -> None:
            callbacks.append(value)
            if len(callbacks) == 1:
                asyncio.get_running_loop().call_soon(stop.set)
        feed = reader(callback, [])
        await feed._session(ws, frozenset({TICKER}), stop)
        assert len(callbacks) == 2 and ws.received == 1
    asyncio.run(scenario())


def test_kalshi_cancel_at_new_boundary_invalidates_before_socket_close(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        stop, callbacks, statuses = threading.Event(), [], []
        payloads = [ack(), ack('trade', 9), snapshot(seq=1), delta(seq=2, at=NOW), *frames(16)]
        ws = Buffered(payloads)
        task: asyncio.Task[Any]
        def callback(_kind: str, value: Any) -> None:
            callbacks.append(value)
            if len(callbacks) == 1:
                asyncio.get_running_loop().call_soon(task.cancel)
        feed = reader(callback, statuses)
        closed = []
        class Context:
            async def __aenter__(self) -> Buffered:
                return ws
            async def __aexit__(self, *_args: object) -> None:
                assert not feed.connected and not feed.fresh_books()
                assert statuses[-1]['gap_windows'] == [TICKER]
                closed.append(True)
                await asyncio.sleep(0)
        monkeypatch.setattr(speeddesk_kalshi_ws, 'MarketHandshake', lambda _settings: SimpleNamespace(headers=lambda _now: {}))
        feed._connect = lambda *_args, **_kwargs: Context()
        task = asyncio.create_task(feed.run(stop))
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(callbacks) == 2 and closed == [True]
        assert feed.state.depth == {} and not feed.connected
    asyncio.run(scenario())


def coinbase_payloads(url: str, total: int, *, ignored: bool = False) -> list[dict[str, Any]]:
    if ignored:
        return [{'type': 'heartbeat'} if url == COINBASE_EXCHANGE_WS else {'channel': 'heartbeats', 'events': []}
                for _ in range(total)]
    parse = speeddesk_feeds.exchange_ticks if url == COINBASE_EXCHANGE_WS else speeddesk_feeds.advanced_trade_ticks
    template = next(row for row in messages('exchange_matches' if url == COINBASE_EXCHANGE_WS else 'advanced_trades')
                    if parse(row))
    rows = []
    for i in range(total):
        row = copy.deepcopy(template)
        if url == COINBASE_EXCHANGE_WS:
            row['trade_id'] = 10000 + i
        else:
            tick = row['events'][0]['trades'][0]
            row['events'][0]['trades'] = [dict(tick, trade_id=str(10000 + 2 * i)),
                dict(tick, trade_id=str(10001 + 2 * i), price='80001')]
        rows.append(row)
    return rows


@pytest.mark.parametrize('url', [COINBASE_EXCHANGE_WS, COINBASE_WS])
@pytest.mark.parametrize('total', [16, 64])
def test_coinbase_buffered_ticks_remain_message_atomic(url: str, total: int) -> None:
    async def replay(candidate: bool) -> Any:
        payloads = coinbase_payloads(url, total)
        parse = speeddesk_feeds.exchange_ticks if url == COINBASE_EXCHANGE_WS else speeddesk_feeds.advanced_trade_ticks
        at = parse(payloads[0])[0][1]
        ws, ticks, statuses, observed = Buffered(payloads), [], [], []
        ready = asyncio.get_running_loop().create_future()
        per_message = len(parse(payloads[0]))
        async def account() -> None:
            await ready
            observed.append((len(ticks), ws.received))
        account_task = asyncio.create_task(account())
        await asyncio.sleep(0)
        class Context:
            async def __aenter__(self) -> Buffered:
                return ws
            async def __aexit__(self, *_args: object) -> None:
                pass
        feed_task: asyncio.Task[Any]
        def on_tick(*values: Any) -> None:
            ticks.append(values)
            if len(ticks) == 1:
                ready.set_result(None)
            if len(ticks) == total * per_message:
                asyncio.get_running_loop().call_soon(feed_task.cancel)
        feed = LiveFeeds(Settings(), on_tick=on_tick, on_book=lambda _: None,
            on_trade=lambda _: None, on_windows=lambda _: None, on_status=statuses.append,
            coinbase_connect=lambda *_a, **_kw: Context(), clock=lambda: at)
        method = LiveFeeds._coinbase_feed if candidate else without_boundary_yield(
            LiveFeeds._coinbase_feed, speeddesk_feeds)
        feed_task = asyncio.create_task(method(feed, 'exchange_a' if url == COINBASE_EXCHANGE_WS else 'advanced_trade', url))
        with pytest.raises(asyncio.CancelledError):
            await feed_task
        await account_task
        if candidate:
            assert observed == [(per_message, 1)]
        else:
            callback_count, received_count = observed[0]
            assert len(observed) == 1 and 1 <= received_count <= total
            assert callback_count == received_count * per_message
        assert ws.received == total and len(ticks) == total * per_message
        assert all(received == at for _, _, received in ticks)
        return ticks, statuses, feed._seen_trades, feed._latest_trade_id, ws.sent
    async def scenario() -> None:
        assert await replay(False) == await replay(True)
    asyncio.run(scenario())


@pytest.mark.parametrize('url', [COINBASE_EXCHANGE_WS, COINBASE_WS])
def test_coinbase_ignored_messages_also_yield_and_cancel_without_new_invalidation(url: str) -> None:
    async def scenario() -> None:
        ws = Buffered(coinbase_payloads(url, 64, ignored=True))
        ticks, statuses = [], []
        receipt_sampled = asyncio.Event()
        receipt_count = 0

        def clock() -> float:
            nonlocal receipt_count
            receipt_count += 1
            # This runs after wait_for returned. On Python3.11, cancelling
            # inside recv can instead hit its completed-child cancellation race.
            receipt_sampled.set()
            return NOW

        class Context:
            async def __aenter__(self) -> Buffered:
                return ws
            async def __aexit__(self, *_args: object) -> None:
                pass
        feed = LiveFeeds(Settings(), on_tick=lambda *v: ticks.append(v), on_book=lambda _: None,
            on_trade=lambda _: None, on_windows=lambda _: None, on_status=statuses.append,
            coinbase_connect=lambda *_a, **_kw: Context(), clock=clock)
        task = asyncio.create_task(feed._coinbase_feed('advanced_trade', url))
        # The receipt hook runs after recv's wrapper. Processing stays synchronous
        # through this heartbeat, then cancellation reaches the explicit yield.
        async with asyncio.timeout(2):
            await receipt_sampled.wait()
        assert ws.received == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert receipt_count == 1
        assert not ticks and statuses[-1]['coinbase'] == 'connected'
    asyncio.run(scenario())


def test_kalshi_timeout_reports_without_changing_depth_or_callback_order() -> None:
    async def replay(candidate: bool) -> Any:
        class TimeoutThenBuffered(Buffered):
            timeouts = 0
            async def recv(self) -> str | bytes:
                if not self.timeouts:
                    self.timeouts += 1
                    raise TimeoutError
                return await super().recv()
        ws, stop, callbacks, statuses = TimeoutThenBuffered(frames(4)), threading.Event(), [], []
        def callback(kind: str, value: Any) -> None:
            callbacks.append((kind, value))
            if len(callbacks) == 8:
                stop.set()
        feed = reader(callback, statuses)
        method = KalshiMarketWS._session if candidate else without_boundary_yield(
            KalshiMarketWS._session, speeddesk_kalshi_ws)
        await method(feed, ws, frozenset({TICKER}), stop)
        assert ws.timeouts == 1 and ws.received == 4
        return callbacks, statuses, vars(feed.state)
    async def scenario() -> None:
        assert await replay(False) == await replay(True)
    asyncio.run(scenario())


def test_callback_failure_still_invalidates_and_closes_without_delivering_second_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        stop, statuses, callbacks = threading.Event(), [], []
        ws = Buffered([ack(), snapshot(seq=1), delta(seq=2, at=NOW), *frames(16)])
        def callback(_kind: str, value: Any) -> None:
            callbacks.append(value)
            raise ValueError('fake callback failed')
        feed = reader(callback, statuses)
        class Context:
            async def __aenter__(self) -> Buffered:
                return ws
            async def __aexit__(self, *_args: object) -> None:
                assert not feed.connected and not feed.fresh_books()
                assert statuses[-1]['gap_windows'] == [TICKER]
                stop.set()
        monkeypatch.setattr(speeddesk_kalshi_ws, 'MarketHandshake', lambda _settings: SimpleNamespace(headers=lambda _now: {}))
        feed._connect = lambda *_args, **_kwargs: Context()
        await feed.run(stop)
        assert len(callbacks) == 1 and ws.received == 3
        assert feed.state.depth == {} and not feed.connected
    asyncio.run(scenario())


@pytest.mark.parametrize('expiry', ['cutoff', 'stale'])
def test_ready_model_guard_uses_new_clock_at_complete_message_boundary(expiry: str) -> None:
    from nightcrawler.speeddesk_model import PracticeDesk, SpeedConfig, Window

    async def scenario() -> None:
        clock, stop, callbacks = FakeClock(NOW), threading.Event(), []
        model = PracticeDesk(SpeedConfig(cutoff_s=60))
        end = NOW + 61 if expiry == 'cutoff' else NOW + 800
        window = Window(TICKER, end - 900, end, 80000, venue='kalshi', venue_start_price=80000)
        model.add_window(window)
        model.tick_btc(80000, NOW)
        ready = asyncio.get_running_loop().create_future()
        guarded = []
        async def guard() -> None:
            await ready
            clock.advance(2 if expiry == 'cutoff' else 3.1)
            guarded.append((len(callbacks), model.blocked(window, clock.now())))
            stop.set()
        task = asyncio.create_task(guard())
        await asyncio.sleep(0)
        def callback(kind: str, value: Any) -> None:
            callbacks.append(value)
            if kind == 'book':
                model.on_book(value)
            if len(callbacks) == 1:
                ready.set_result(None)
        feed = reader(callback, [], clock.now)
        await feed._session(Buffered(frames(16)), frozenset({TICKER}), stop)
        await task
        assert guarded == [(2, 'cutoff' if expiry == 'cutoff' else 'bitcoin_stale')]
        assert len(model.books) == 2 and len(callbacks) == 2
    asyncio.run(scenario())
