"""Snapshot caching preserves every observation and the original volatility/freshness decisions."""

from __future__ import annotations

import math
import threading
from dataclasses import replace

from nightcrawler.clock import FakeClock
from nightcrawler.config import Settings
from nightcrawler.speeddesk import SpeedRunner
from nightcrawler.speeddesk_model import Book, Level, Window


class Feeds:
    def __init__(self, *_args, **_kwargs):
        self.makers = {"KXBTC15M-cache"}

    def maker_windows(self):
        return self.makers.copy()


class Companion:
    def __init__(self, _settings, _path, snapshot, **_kwargs):
        self.snapshot = snapshot
        self.books = []

    def on_windows(self, _windows):
        pass

    def on_tick(self, *_args):
        pass

    def on_book(self, book):
        self.books.append((book, self.snapshot()))

    def on_status(self, _status):
        pass

    def close(self):
        pass


def make_runner(tmp_path, clock):
    return SpeedRunner(Settings(data_dir=tmp_path), threading.Event(), clock=clock,
                       feed_factory=Feeds, live_factory=Companion)


def test_book_burst_reuses_sigma_and_copied_metadata_but_publishes_every_book_and_advance(tmp_path, monkeypatch):
    clock = FakeClock(4000.5)
    runner = make_runner(tmp_path, clock)
    try:
        for second in range(399, 4001):
            runner.desk.tape.tick(80000 * math.exp((second % 7) * .00001), float(second))
        runner.on_windows([Window("KXBTC15M-cache", 3900, 4800, 80000, venue="kalshi")])
        expected = runner.desk.tape.sigma(clock.now())
        assert expected is not None
        sigma_calls, advances = [], []
        sigma = runner.desk.tape.sigma
        monkeypatch.setattr(runner.desk.tape, "sigma", lambda *args: sigma_calls.append(args) or sigma(*args))
        monkeypatch.setattr(runner.desk, "advance", lambda now: advances.append(now) or [])
        window_copies = runner.live_snapshot().windows
        before = runner.live_snapshot()
        for sequence in range(200):
            side = "up" if sequence % 2 == 0 else "down"
            book = Book("KXBTC15M-cache", side, (Level(.30, 3),),
                        (Level(.6 if sequence % 3 else .7, 10),), clock.now(), str(sequence))
            runner.on_book(book)
            current = runner.live_snapshot()
            assert current.books[(book.window, book.side)] is book
            assert current.sigma == expected and current.windows is window_copies
        assert not sigma_calls  # the completed-second value was already published before the burst
        assert len(advances) == 200 and runner.live is not None and len(runner.live.books) == 200
        assert [book.sequence for book, _snapshot in runner.live.books] == [str(i) for i in range(200)]
        for book, snapshot in runner.live.books:
            assert snapshot.books[(book.window, book.side)] is book
        assert before.books == {}  # no published dictionary was later mutated
        runner.feeds.makers.clear()
        runner._refresh_live_snapshot()
        assert not runner.live_snapshot().maker_windows  # feed permission is never cached with sigma
        clock.advance(4)
        runner._refresh_live_snapshot()
        assert runner.live_snapshot().bitcoin_at == 4000
        assert clock.now() - runner.live_snapshot().bitcoin_at > 3  # no fresh timestamp borrowed from a book
        assert len(sigma_calls) == 1
    finally:
        runner.close()


def test_sigma_cache_respects_fractional_warmup_completed_seconds_and_both_config_inputs(tmp_path, monkeypatch):
    clock = FakeClock(102.5)
    runner = make_runner(tmp_path, clock)
    try:
        runner.desk.config = replace(runner.desk.config, sigma_min_samples=1, sigma_warmup_s=2.5)
        for price, at in ((80000, 100.2), (80010, 101.2), (80050, 102.2)):
            runner.on_tick(price, at, clock.now())
        sigma = runner.desk.tape.sigma
        calls = []
        monkeypatch.setattr(runner.desk.tape, "sigma", lambda *args: calls.append(args) or sigma(*args))
        assert runner._live_sigma(102.6) is None  # still warming inside the same completed second
        ready = runner._live_sigma(102.71)
        assert ready is not None and ready == sigma(102.71, 1, 2.5)
        assert len(calls) == 1  # warm-up boundary alone invalidated the previous None
        assert runner._live_sigma(102.8) == ready and len(calls) == 1
        runner.desk.config = replace(runner.desk.config, sigma_min_samples=2)
        assert runner._live_sigma(102.8) is None and len(calls) == 2
        assert runner._live_sigma(103.0) == sigma(103.0, 2, 2.5) and len(calls) == 3
        runner.desk.config = replace(runner.desk.config, sigma_warmup_s=10)
        assert runner._live_sigma(103.0) is None and len(calls) == 4
    finally:
        runner.close()


def test_accepted_same_second_btc_revision_invalidates_sigma_rejected_ticks_do_not(tmp_path, monkeypatch):
    clock = FakeClock(102.5)
    runner = make_runner(tmp_path, clock)
    try:
        runner.desk.config = replace(runner.desk.config, sigma_min_samples=1, sigma_warmup_s=0)
        runner.on_tick(80000, 100.5, clock.now())
        runner.on_tick(80010, 101.5, clock.now())
        old = runner.live_snapshot()
        sigma = runner.desk.tape.sigma
        calls = []
        monkeypatch.setattr(runner.desk.tape, "sigma", lambda *args: calls.append(args) or sigma(*args))
        runner.on_tick(80100, 101.5, clock.now())  # same completed second and timestamp, revised observed price
        assert runner.live_snapshot().sigma == sigma(clock.now(), 1, 0)
        assert runner.live_snapshot().sigma != old.sigma and len(calls) == 1
        assert old.bitcoin_price == 80010 and old.bitcoin_at == 101.5
        revision = runner._bitcoin_revision
        runner.on_tick(90000, 100.9, clock.now())  # out of order
        runner.on_tick(float("nan"), 101.8, clock.now())
        runner.on_tick(90000, 98, clock.now())  # outside the existing 3s receive-delay guard
        assert runner._bitcoin_revision == revision and len(calls) == 1
        assert runner.live_snapshot().bitcoin_price == 80100 and runner.live_snapshot().bitcoin_at == 101.5
    finally:
        runner.close()


def test_restored_or_replaced_tape_prices_cannot_reuse_an_old_sigma(tmp_path):
    clock = FakeClock(102.5)
    runner = make_runner(tmp_path, clock)
    try:
        runner.desk.config = replace(runner.desk.config, sigma_min_samples=1, sigma_warmup_s=0)
        runner.on_tick(80000, 100.5, clock.now())
        runner.on_tick(80010, 101.5, clock.now())
        first = runner._live_sigma(clock.now())
        runner.desk.tick_btc(80200, 101.6)  # restore/test model updates also replace the observation dictionary
        second = runner._live_sigma(clock.now())
        assert first != second and second == runner.desk.tape.sigma(clock.now(), 1, 0)
    finally:
        runner.close()


def test_opening_metadata_and_settlement_updates_leave_prior_worker_snapshots_unchanged(tmp_path):
    clock = FakeClock(100.2)
    runner = make_runner(tmp_path, clock)
    try:
        window = Window("KXBTC15M-cache", 100, 1000, venue="kalshi")
        runner.on_windows([window])
        unopened = runner.live_snapshot()
        assert unopened.windows[0].start_price is None
        runner.on_tick(80000, 100.2, clock.now())
        opened = runner.live_snapshot()
        assert opened.windows[0].start_price == 80000 and unopened.windows[0].start_price is None
        assert opened.windows[0] is not runner.desk.windows[window.slug]
        runner.on_windows([replace(window, taker_coefficient=.08)])
        changed = runner.live_snapshot()
        assert changed.windows[0].taker_coefficient == .08 and opened.windows[0].taker_coefficient == .0695
        clock.advance(900)
        runner.desk.settle(window.slug, True, clock.now())
        runner._refresh_live_snapshot()
        assert runner.live_snapshot().outcomes == {window.slug: True}
        assert unopened.outcomes == opened.outcomes == changed.outcomes == {}
    finally:
        runner.close()
