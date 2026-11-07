"""Speed plan step 3: the constant-work Bitcoin tape and the sigma cache match the previous code on a recorded tape.

The fixture holds the first 3,000 Coinbase Exchange BTC-USD matches recorded on 2026-10-13 (exchange stamp,
local receipt minus stamp, trade id, price). It is replayed six times, 700 s apart, so the hour-long window
fills, slides and drops its oldest seconds; late ticks that revise the current or the just-completed second are
added on purpose.
"""

from __future__ import annotations

import csv
import gzip
import math
import threading
from pathlib import Path

import pytest
from test_speeddesk_snapshot_cache import Companion, Feeds

from nightcrawler.clock import FakeClock
from nightcrawler.config import Settings
from nightcrawler.speeddesk import SpeedRunner
from nightcrawler.speeddesk_model import BitcoinTape

FIXTURE = Path(__file__).parent / "fixtures" / "coinbase_btc_matches_20261013.csv.gz"


class PreviousTape:
    """BitcoinTape as it was before step 3 (both dictionaries rebuilt on every accepted tick)."""

    def __init__(self) -> None:
        self.prices: dict[int, float] = {}
        self.first_prices: dict[int, float] = {}
        self.started_at: float | None = None
        self.last_at: float | None = None
        self.price: float | None = None

    def tick(self, price: float, at: float) -> bool:
        if not math.isfinite(price) or price <= 0 or not math.isfinite(at):
            return False
        if self.last_at is not None and at < self.last_at:
            return False
        if self.started_at is None:
            self.started_at = at
        self.last_at, self.price = at, price
        second = int(at)
        self.prices[second] = price
        self.first_prices.setdefault(second, price)
        self.prices = {stamp: value for stamp, value in self.prices.items() if stamp >= second - 3601}
        self.first_prices = {stamp: value for stamp, value in self.first_prices.items() if stamp >= second - 3601}
        return True

    def sigma(self, now: float, minimum: int = 1500, warmup_s: float = 3600.0) -> float | None:
        if self.started_at is None or now - self.started_at < warmup_s:
            return None
        last_complete = int(now) - 1
        returns = [math.log(self.prices[second] / self.prices[second - 1])
                   for second in range(last_complete - 3599, last_complete + 1)
                   if second in self.prices and second - 1 in self.prices]
        if len(returns) < minimum:
            return None
        return math.sqrt(sum(value * value for value in returns) / len(returns))


def recorded_ticks(loops: int = 6, spacing_s: float = 700.0) -> list[tuple[float, float, float]]:
    """(price, exchange time, local receipt time) in arrival order, with late revisions mixed in."""
    with gzip.open(FIXTURE, "rt", newline="") as stream:
        rows = [(int(row["exchange_us"]) / 1e6, int(row["received_minus_exchange_us"]) / 1e6, float(row["price"]))
                for row in csv.DictReader(stream)]
    ticks: list[tuple[float, float, float]] = []
    for loop in range(loops):
        for index, (stamp, delay, price) in enumerate(rows):
            at = stamp + loop * spacing_s
            ticks.append((price, at, at + delay))
            if index % 97 == 0:  # a second print in the same second, received after that second ended
                late = math.floor(at) + .999
                ticks.append((price + 1.25, late, late + .06))
    return ticks


def test_the_fixture_is_the_recorded_tape() -> None:
    ticks = recorded_ticks(loops=1)
    assert len([tick for tick in ticks if tick[1] % 1 != .999]) >= 3000
    assert ticks[0][0] == 83421.86 and 1791909589 < ticks[0][1] < 1791909590
    assert any(received < at for _price, at, received in ticks)  # the recorder's clock ran behind Coinbase's


def test_constant_work_tape_matches_the_previous_tape_on_a_recorded_hour_and_more() -> None:
    old, new = PreviousTape(), BitcoinTape()
    ticks = recorded_ticks()
    accepted, newest = 0, -math.inf
    for count, (price, at, received) in enumerate(ticks):
        result = new.tick(price, at)
        assert result == old.tick(price, at)
        accepted += result
        assert result == (at >= newest)
        newest = max(newest, at)
        assert (new.last_at, new.price, new.started_at) == (old.last_at, old.price, old.started_at)
        if count % 20 == 0 or at % 1 == .999:
            assert new.prices == old.prices and new.first_prices == old.first_prices
        if count % 60 == 0 or at % 1 == .999:
            for now in (received, received + .5):
                assert new.sigma(now) == old.sigma(now)
                assert new.sigma(now, 100, 600) == old.sigma(now, 100, 600)
    assert new.prices == old.prices and new.first_prices == old.first_prices
    assert old.sigma(ticks[-1][2]) is not None  # the window warmed, slid and dropped old seconds
    assert len(new.prices) <= 3603 and min(new.prices) >= int(ticks[-1][1]) - 3601
    assert new.revision == accepted  # every accepted tick counted once


def runner(tmp_path: Path, clock: FakeClock) -> SpeedRunner:
    return SpeedRunner(Settings(data_dir=tmp_path), threading.Event(), clock=clock, feed_factory=Feeds,
                       live_factory=Companion)


def test_cached_sigma_equals_a_fresh_computation_at_every_recorded_tick(tmp_path: Path) -> None:
    clock = FakeClock(1_791_909_589.0)
    desk = runner(tmp_path, clock)
    reference = PreviousTape()
    try:
        ticks = recorded_ticks()
        checked = 0
        for count, (price, at, received) in enumerate(ticks):
            desk.desk.tick_btc(price, at)
            reference.tick(price, at)
            warm = at - ticks[0][1] > 3590
            if warm and (count % 9 == 0 or at % 1 == .999 or math.floor(received) != math.floor(at)):
                for now in (received, received + .3):
                    assert desk._live_sigma(now) == reference.sigma(now)
                    checked += 1
        assert checked > 600
    finally:
        desk.close()


@pytest.mark.parametrize("late_offset", [.0, .999])
def test_a_late_tick_in_a_completed_second_changes_the_cached_sigma(tmp_path: Path, late_offset: float) -> None:
    clock = FakeClock(10_000.0)
    desk = runner(tmp_path, clock)
    try:
        for second in range(5000, 8700):
            desk.desk.tick_btc(80000 * math.exp((second % 13) * 1e-5), second + .2)
        now = 8700.05  # second 8699 has just completed
        before = desk._live_sigma(now)
        assert before is not None and desk._live_sigma(now) == before
        desk.desk.tick_btc(81000, 8699 + max(.2, late_offset))  # stamped in the completed second, received late
        after = desk._live_sigma(now)
        assert after != before and after == desk.desk.tape.sigma(now, 1500, 3600)
        desk.desk.tick_btc(82000, 8700.01)  # the current second: the completed-second value stays cached
        assert desk._live_sigma(now) == after
    finally:
        desk.close()


def test_a_tick_stamped_ahead_of_the_local_clock_keeps_the_cache(tmp_path: Path, monkeypatch) -> None:
    """Latency review minor: when the newest tick is stamped in a later second than the local clock (allowed up to
    FUTURE_SKEW_S), every snapshot refresh recomputed the hour (7.2 a second at -240 ms skew). The cache now keys on
    that second: unchanged until it changes or a tick lands in a completed second, and always equal to a fresh
    computation."""
    clock = FakeClock(10_000.0)
    desk = runner(tmp_path, clock)
    try:
        for second in range(5000, 8700):
            desk.desk.tick_btc(80000 * math.exp((second % 13) * 1e-5), second + .2)
        desk.desk.tick_btc(80100, 8700.1)  # stamped 0.24 s after the local clock below
        tape = desk.desk.tape
        computed = [0]
        original = tape.sigma

        def counted(*args, **kwargs):  # type: ignore[no-untyped-def]
            computed[0] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(tape, "sigma", counted)
        now = 8699.86
        first = desk._live_sigma(now)
        for _ in range(5):  # book updates within the same tick
            assert desk._live_sigma(now) == first
        assert computed[0] == 1
        desk.desk.tick_btc(80200, 8700.12)  # the same later second: still cached
        assert desk._live_sigma(now) == first and computed[0] == 1
        desk.desk.tick_btc(80300, 8701.0)  # a newer second can evict an old one: recomputed
        assert desk._live_sigma(now) == original(now, 1500, 3600) and computed[0] == 2
    finally:
        desk.close()
