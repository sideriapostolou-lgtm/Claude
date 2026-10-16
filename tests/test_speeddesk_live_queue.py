"""HISTORICAL ENTRY MECHANISM ONLY; no current entry authority or profitability claim.

Optional queue observations cannot alter fills, risk, send/cancel timing or persistence authority."""
from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from historical_speeddesk_entry import make_historical_desk
from test_speeddesk_live import TICKER
from test_speeddesk_live_pull import CAPS, MAKERS, market

from nightcrawler.clock import FakeClock
from nightcrawler.speeddesk_kalshi_client import KalshiClientError
from nightcrawler.speeddesk_live_queue import (
    MAX_BUFFERED,
    MAX_CANDIDATES,
    QueueContext,
    QueueObserver,
)


class Reader:
    def __init__(self, result='2.50'):
        self.result, self.calls, self.closed = result, [], False
        self.entered, self.release = threading.Event(), threading.Event()
        self.block = False

    def read(self, order_id):
        self.calls.append(order_id)
        self.entered.set()
        if self.block:
            assert self.release.wait(5), 'fake queue response was not released'
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def close(self):
        self.closed = True


def context(**changes):
    return replace(QueueContext('nc-speed-own', 'owned-order', TICKER, 'up', .47, 5,
                                'resting', 17, 10, 5), **changes)


async def completed(observer, contexts, current):
    observer.poll(contexts, current, enabled=True)
    assert observer.task is not None
    await asyncio.wait_for(asyncio.shield(observer.task), 2)
    observer.poll(contexts, current, enabled=True)


def test_success_has_interval_raw_fraction_and_no_simulator_authority():
    async def scenario():
        clock, reader = FakeClock(1000), Reader('0.00')
        observer = QueueObserver(reader, clock=clock.now, monotonic=clock.now)
        original = context()
        await completed(observer, [original], lambda _: original)
        [row] = observer.drain()
        assert row['queue_position_fp'] == '0.00'
        assert row['status'] == 'observed_interval_only' and row['dispatch']['twin_queue_ahead'] == 10
        assert row['clock_basis'] == ('local_selection_worker_return_intervals; '
                                      'includes_budget_signing_decode; not_network_RTT')
        assert row['version'] == 1 and len(row['session_id']) == 32
        assert row['selected_at'] == row['worker_started_at'] == row['response_returned_at'] == 1000
        assert row['selection_to_return_ms'] == row['worker_elapsed_ms'] == 0
        assert QueueObserver(None).session_id != observer.session_id
        assert reader.calls == ['owned-order']
        await observer.close(lambda _: original)
        assert reader.closed
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['remaining', 'status', 'order_id', 'twin_order_id', 'twin_queue_ahead', 'missing'])
def test_completion_race_retains_request_identity_and_marks_unknown(change):
    async def scenario():
        clock = FakeClock(1000)
        reader = Reader()
        observer = QueueObserver(reader, clock=clock.now, monotonic=clock.now)
        original = context()
        values = {'remaining': 2, 'status': 'cancel_requested', 'order_id': 'different-order',
                  'twin_order_id': 18, 'twin_queue_ahead': 7}
        current = None if change == 'missing' else context(**{change: values[change]})
        await completed(observer, [original], lambda _: current)
        [row] = observer.drain()
        assert row['status'] == 'unknown_context_changed'
        assert row['order_id'] == 'owned-order' and row['queue_position_fp'] == '2.50'
        assert row['context_changes']
        await observer.close(lambda _: current)
    asyncio.run(scenario())


@pytest.mark.parametrize('status', [404, 429, 401, 403, 500])
def test_errors_remain_unknown_and_backoff_or_disable_observer_only(status):
    async def scenario():
        clock = FakeClock(1000)
        reader = Reader(KalshiClientError('queue_position', 'observer_http_error', status=status))
        observer = QueueObserver(reader, clock=clock.now, monotonic=clock.now)
        original = context()
        await completed(observer, [original], lambda _: original)
        [row] = observer.drain()
        assert row['queue_position_fp'] is None and row['status'] == 'unknown_error'
        observer.poll([original], lambda _: original, enabled=True)
        assert len(reader.calls) == 1 and observer.next_at >= 1002
        assert observer.disabled is (status in (401, 403))
        await observer.close(lambda _: original)
    asyncio.run(scenario())


def test_one_pending_request_round_robin_and_bounded_publication():
    async def scenario():
        clock, reader = FakeClock(1000), Reader()
        observer = QueueObserver(reader, clock=clock.now, monotonic=clock.now)
        contexts = [context(client_order_id=f'nc-speed-{i}', order_id=f'own-{i}') for i in range(2)]
        for _ in range(MAX_BUFFERED + 2):
            await completed(observer, contexts, lambda old: old)
            clock.advance(1)
        assert len(observer.rows) == MAX_BUFFERED and observer.counts['buffer_dropped'] == 2
        assert reader.calls[:4] == ['own-0', 'own-1', 'own-0', 'own-1']
        for i in range(MAX_CANDIDATES + 2):
            observer.register(f'nc-speed-{i}')
        assert len(observer.tracked) == MAX_CANDIDATES and observer.counts['registry_dropped'] == 2
        await observer.close(lambda old: old)
    asyncio.run(scenario())


def test_bad_clock_disables_diagnostic_without_nonfinite_log_row():
    async def scenario():
        reader = Reader()
        observer = QueueObserver(reader, clock=lambda: float('nan'), monotonic=lambda: 0)
        await completed(observer, [context()], lambda old: old)
        assert observer.disabled and not observer.rows and observer.counts['invalid_clock'] == 1
        await observer.close(lambda old: old)
    asyncio.run(scenario())


@pytest.mark.parametrize('changes', [{'remaining': float('nan')}, {'client_order_id': 'x' * 129},
                                   {'twin_order_id': 2**64}, {'twin_queue_ahead': 1e19}])
def test_unbounded_context_never_dispatched_or_published(changes):
    reader = Reader()
    observer = QueueObserver(reader)
    observer.poll([context(**changes)], lambda old: old, enabled=True)
    assert not reader.calls and not observer.rows and observer.counts['invalid_context'] == 1
    assert observer.close_idle(lambda old: old)


def test_cancelled_async_wrapper_never_closes_or_reuses_underlying_live_thread():
    async def scenario():
        clock, reader = FakeClock(1000), Reader()
        reader.block = True
        observer = QueueObserver(reader, clock=clock.now, monotonic=clock.now)
        original = context()
        observer.poll([original], lambda old: old, enabled=True)
        await asyncio.to_thread(reader.entered.wait, 1)
        assert reader.entered.is_set()
        worker = observer.worker
        observer.task.cancel()
        await asyncio.sleep(0)
        clock.advance(2)
        observer.poll([original], lambda old: old, enabled=True)
        assert observer.worker is worker and len(reader.calls) == 1
        assert not observer.close_idle(lambda old: old) and not reader.closed
        closing = asyncio.create_task(observer.close(lambda old: old))
        await asyncio.sleep(0)
        assert not closing.done() and not reader.closed
        reader.release.set()
        await asyncio.wait_for(closing, 2)
        assert reader.closed and observer.counts['shutdown_unpublished'] == 1
    asyncio.run(scenario())


def prepare(tmp_path, reader):
    desk, account, clock = make_historical_desk(tmp_path, caps=CAPS, extra=MAKERS)
    market(desk, clock, .5)
    asyncio.run(desk.step())
    # Only fake signing-free reader creation is available; no real key or network client is constructed.
    account.own_queue_reader = lambda: reader
    return desk, account, clock


def test_real_books_reservations_practice_and_save_cadence_unchanged(tmp_path: Path):
    async def scenario():
        reader = Reader()
        desk, account, clock = make_historical_desk(tmp_path, caps=CAPS, extra=MAKERS)
        try:
            market(desk, clock, .5)
            await desk.step()
            account.own_queue_reader = lambda: reader
            desk.checkpoint()
            original = json.loads(json.dumps({'book': desk.book.to_state(), 'twin': desk.twin.to_state(),
                                              'creates': account.creates, 'cancels': account.cancels,
                                              'pending': desk.pending, 'dirty': desk.dirty}))
            # The observer never consults the full active/history iterator.
            desk._active = lambda: pytest.fail('queue observation scanned financial history')
            desk._queue_tick()
            assert desk.queue_observer.task not in desk._workers
            assert desk.queue_observer.task not in desk._read_workers
            await asyncio.wait_for(asyncio.shield(desk.queue_observer.task), 2)
            desk._queue_tick()
            after = json.loads(json.dumps({'book': desk.book.to_state(), 'twin': desk.twin.to_state(),
                                           'creates': account.creates, 'cancels': account.cancels,
                                           'pending': desk.pending, 'dirty': desk.dirty}))
            assert after == original
            assert reader.calls == ['order-1']
            assert desk.queue_observer.rows
            desk.checkpoint()
            rows = [r for r in desk.ledger.iter_receipts() if r.kind == 'speeddesk_live_queue']
            assert len(rows) == 1 and not desk.queue_observer.rows
            assert not any(r.get('event') == 'speeddesk_live_queue' for r in desk.latest_events)
            await desk.queue_observer.close(lambda old: desk._queue_context(old.client_order_id))
        finally:
            desk.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('gate', ['paper', 'disabled', 'foreign', 'uncertain', 'cancel', 'terminal', 'lock', 'noack'])
def test_ineligible_owned_order_never_requests_queue(tmp_path: Path, gate):
    reader = Reader()
    desk, _account, _ = prepare(tmp_path, reader)
    try:
        intent = next(iter(desk.intents.values()))
        if gate == 'paper': desk.settings = replace(desk.settings, speeddesk_kalshi_mode='paper')
        elif gate == 'disabled': desk.settings = replace(desk.settings, speeddesk_kalshi_enabled=False)
        elif gate == 'foreign': desk.foreign_windows.add(TICKER)
        elif gate == 'uncertain': intent.uncertain = True
        elif gate == 'cancel': intent.cancel_requested = True
        elif gate == 'terminal': intent.terminal = True
        elif gate == 'lock': intent.lock = True
        elif gate == 'noack': intent.order_id = ''
        # No asynchronous worker can be scheduled by an ineligible registry entry.
        desk._queue_tick()
        assert not reader.calls
        assert desk.queue_observer.task is None
    finally:
        desk.close()


@pytest.mark.parametrize('field,value', [('order_id', 'other-order'), ('window', 'other-window'),
                                        ('side', 'down'), ('kind', 'take'), ('price', .01),
                                        ('size', 100), ('lock', True), ('client_order_id', 'other-client'),
                                        ('status', 'canceled'), ('status', 'executed')])
def test_canonical_reservation_mismatch_or_terminal_pending_fills_never_probed(tmp_path, field, value):
    reader = Reader()
    desk, _account, _clock = prepare(tmp_path, reader)
    try:
        intent = next(iter(desk.intents.values()))
        reserved = desk.book.intents[intent.client_order_id]
        setattr(reserved, field, value)
        desk._queue_tick()
        assert not reader.calls and desk.queue_observer.worker is None
    finally:
        desk.close()


def test_slow_probe_never_delays_shutdown_first_cancel_or_closes_live_connection(tmp_path: Path):
    async def scenario():
        reader = Reader(); reader.block = True
        desk, account, clock = make_historical_desk(tmp_path, caps=CAPS, extra=MAKERS)
        shutdown = None
        try:
            market(desk, clock, .5)
            await desk.step()
            account.own_queue_reader = lambda: reader
            desk._queue_tick()
            await asyncio.to_thread(reader.entered.wait, 1)
            assert reader.entered.is_set()
            first_task = desk.queue_observer.task
            clock.advance(2)
            desk._queue_tick()
            assert desk.queue_observer.task is first_task and len(reader.calls) == 1
            checkpoint = desk.checkpoint
            financial_saved = []
            def final_checkpoint(**kwargs):
                checkpoint(**kwargs)
                if kwargs.get('durable') and desk.stopping:
                    financial_saved.append(True)
            desk.checkpoint = final_checkpoint
            shutdown = asyncio.create_task(desk.shutdown())
            for _ in range(100):
                if financial_saved:
                    break
                await asyncio.sleep(.005)
            assert account.cancels == ['order-1'] and not shutdown.done()
            assert financial_saved == [True]  # final durable financial save did not wait for optional HTTP
            assert not reader.closed
            reader.release.set()
            await asyncio.wait_for(shutdown, 2)
            assert reader.closed and desk.shutdown_done
            assert financial_saved == [True] and desk.queue_observer.counts['shutdown_unpublished'] == 1
        finally:
            reader.release.set()
            if shutdown is not None:
                await shutdown
            desk.close()
    asyncio.run(scenario())
