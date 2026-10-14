"""The recorder's rewards (LIP) lanes: programs found from the public list (never hard-coded), their books pinned
into the existing 1 s book call, prints, settlement rows, lossless program snapshots, Kalshi's free 1 s settlement
series, the shared 2/s budget (LIP books go first; the lanes that wait are counted), shedding and per-lane bytes.

Every case runs against a scripted public venue; nothing touches the network. The series names are invented on
purpose: the lane must find whatever ``/incentive_programs`` lists.
"""

from __future__ import annotations

import base64
import gzip
import json
import math
import os
from collections import Counter, deque
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from kalshi_recorder_fixtures import (
    NOW,
    Clock,
    FakeKalshi,
    FakeResponse,
    iso,
    market_row,
    orderbook,
)
from test_kalshi_recorder import CANDIDATE, recorder, records, venue

from nightcrawler.kalshi_public import PublicKalshi, RateLimiter
from nightcrawler.kalshi_recorder import (
    LIP_LEAD_S,
    LIP_TAIL_S,
    LipWindow,
    Recorder,
    RecorderSettings,
    TradeJob,
    Watched,
)
from nightcrawler.kalshi_recorder_store import LEVEL_SHED, RecorderStore, load_index

PERIOD = 900
BOUNDARY = math.floor(NOW / PERIOD) * PERIOD
# (series, market suffix): an FX-like and a metal-like series with a public live series, and a race-like one without.
FAST = (("KXZZZUSD15M", "30"), ("KXQQQMETAL15M", "00"), ("KXRACE15M", "BTC"))
DAILY_TICKER = "KXDAILYRAIN-26OCT13-T1"


def lip_ticker(series: str, start: float, suffix: str) -> str:
    stamp = datetime.fromtimestamp(start + PERIOD, UTC).strftime("%y%b%d%H%M").upper()
    return f"{series}-{stamp}-{suffix}"


def program(pid: str, ticker: str, start: float, end: float, reward: int = 500000) -> dict[str, Any]:
    return {"id": pid, "market_ticker": ticker, "market_id": "m-" + pid, "start_date": iso(start),
            "end_date": iso(end), "period_reward": reward, "target_size_fp": "300.00", "discount_factor_bps": 5000,
            "incentive_type": "liquidity", "incentive_description": "series_lip", "paid_out": False}


class LipVenue(FakeKalshi):
    """The Family A venue of the recorder tests plus a liquidity program list that follows the clock."""

    def __init__(self, clock: Clock, *, series: tuple[tuple[str, str], ...] = FAST, windows: range = range(-2, 10),
                 page_size: int | None = None) -> None:
        super().__init__()
        base = venue()
        self.series, self.events, self.markets, self.books = base.series, base.events, base.markets, base.books
        self.clock, self.page_size = clock, page_size
        self.programs: list[dict[str, Any]] = []
        self.ends: dict[str, float] = {}
        for name, suffix in series:
            for index in windows:
                start = BOUNDARY + index * PERIOD
                ticker = lip_ticker(name, start, suffix)
                self.programs.append(program(f"{name}-{index}", ticker, start, start + PERIOD))
                self.books[ticker] = orderbook([("0.40", "100.00"), ("0.39", "250.00")], [("0.57", "80.00")])
                self.ends[ticker] = start + PERIOD
        self.programs.append(program("daily-1", DAILY_TICKER, BOUNDARY - 3600, BOUNDARY - 3600 + 86400, 250000))
        self.books[DAILY_TICKER] = orderbook([("0.10", "5.00")], [("0.80", "5.00")])
        self.no_series = {"KXRACE15M"}
        self.revise: dict[tuple[str, int], float] = {}

    def status(self, row: dict[str, Any], now: float) -> str:
        start = datetime.fromisoformat(row["start_date"]).timestamp()
        end = datetime.fromisoformat(row["end_date"]).timestamp()
        return "upcoming" if now < start else "active" if now < end else "closed"

    def value(self, series: str, when: int) -> float:
        return self.revise.get((series, when), round(1.1 + (when // 1000 % 7) * 1e-5, 5))

    def route(self, path: str, query: dict[str, list[str]]) -> FakeResponse:
        now = self.clock.at
        if path == "/incentive_programs":
            rows = [row for row in self.programs if self.status(row, now) == query.get("status", ["active"])[0]]
            if self.page_size:
                offset = int(query.get("cursor", ["0"])[0] or 0)
                cursor = str(offset + self.page_size) if offset + self.page_size < len(rows) else ""
                return FakeResponse(200, {"incentive_programs": rows[offset:offset + self.page_size],
                                          "next_cursor": cursor})
            return FakeResponse(200, {"incentive_programs": rows, "next_cursor": ""})
        if path.startswith("/live_data/events/"):
            event = path.rsplit("/", 1)[1]
            name = event.split("-", 1)[0]
            if name in self.no_series:
                return FakeResponse(404, {"error": {"code": "not_found", "message": "not found"}})
            end = int(now) * 1000
            points = [{"t": end - 1000 * back, "v": self.value(name, end - 1000 * back)} for back in range(3600, -1, -1)]
            return FakeResponse(200, {"live_data": {"type": "commodity", "details": {
                "asset": name, "cadence": "15min", "interval": "1s", "start_ms": points[0]["t"], "end_ms": end,
                "event_ticker": event, "timeseries": points}}})
        if path == "/markets" and "tickers" in query:
            out = []
            for ticker in query["tickers"][0].split(","):
                if ticker in self.ends:
                    end = self.ends[ticker]
                    done = now >= end + 30
                    out.append(market_row(ticker, ticker.rsplit("-", 1)[0], now=end, open_offset=-PERIOD,
                                          close_offset=0, status="finalized" if done else "active",
                                          result="yes" if done else "", expiration_value="1.10005" if done else None))
                elif ticker in self.markets:
                    out.append(self.markets[ticker])
            return FakeResponse(200, {"markets": out, "cursor": ""})
        return super().route(path, query)


def tickers_at(index: int, series: tuple[tuple[str, str], ...] = FAST) -> list[str]:
    return [lip_ticker(name, BOUNDARY + index * PERIOD, suffix) for name, suffix in series]


def run_until(box: Recorder, clock: Clock, until: float) -> None:
    while clock.at < until:
        if not box.step():
            clock.sleep(0.25)


def lip_box(tmp_path: Path, clock: Clock, fake: FakeKalshi | None = None, **settings: Any) -> tuple[Recorder, Any]:
    fake = fake if fake is not None else LipVenue(clock)
    return recorder(tmp_path, fake, clock, btc15m=False, **settings), fake


def lip_calls(tmp_path: Path) -> list[dict[str, Any]]:
    return [record for record in records(tmp_path, "lip") if record["kind"] == "book_call"]


def live(box: Recorder, lane: str) -> list[dict[str, Any]]:
    """A lane's rows written so far, the open segment included (flushed first; its lines are complete)."""
    box.store.flush_all(box.wall())
    out: list[dict[str, Any]] = []
    for path in sorted((box.root / "segments" / lane).rglob("*.jsonl.gz*")):
        with gzip.open(path, "rb") as stream:
            try:
                for line in stream:
                    out.append(json.loads(line))
            except EOFError:  # an open segment has no gzip trailer yet; every flushed line was read
                pass
    return sorted(out, key=lambda record: record["seq"])


def degraded(box: Recorder) -> Counter[str]:
    total: Counter[str] = Counter()
    for record in live(box, "telemetry"):
        if record["kind"] == "degraded":
            total.update(record["counts"])
    return total


def next_minute(box: Recorder, clock: Clock) -> None:
    """Move to the next minute and step once, so the minute's degradation row is written."""
    clock.at = (math.floor(clock.at / 60) + 1) * 60 + 1
    box.step()


# --------------------------------------------------------------------------- discovery and the 1 s pins
def test_programs_are_found_from_the_list_and_their_books_ride_every_call_at_one_second(tmp_path: Path) -> None:
    clock = Clock(BOUNDARY + 100)
    box, _ = lip_box(tmp_path, clock)
    run_until(box, clock, BOUNDARY + 160)
    box.close()
    current = set(tickers_at(0))
    calls = lip_calls(tmp_path)
    assert calls and all(set(call["tickers"]) == current for call in calls)  # no daily, no next window yet
    starts = [call["requested_at"] for call in calls]
    intervals = [later - earlier for earlier, later in pairwise(starts)]
    assert len(calls) >= 50 and max(intervals) <= 1.5 and min(intervals) >= 1.0  # the scoring cadence
    books = records(tmp_path, "books_lip")
    assert {record["ticker"] for record in books} == current
    assert all(record["requested_at"] <= record["received_at"] and "yes_dollars" in record["orderbook_fp"]
               for record in books)
    assert len(books) == len(current)  # written once; every later call lists them as unchanged
    assert all(set(call["unchanged"]) == current for call in calls[1:])
    # Family A's book rows never list a LIP market, and no LIP book or watch row reaches a Family A lane.
    for record in records(tmp_path, "book_calls"):
        assert not set(record["tickers"]) & current and record["lip_tickers"] == 3
    assert not {record.get("ticker") for record in records(tmp_path, "books")} & current
    assert not any(set(record.get("tickers") or []) & current for record in records(tmp_path, "admissions"))
    status = json.loads((tmp_path / "kalshi_recorder" / "status.json").read_text())
    assert set(status["lip"]["pinned"]) == current and status["lip"]["fast_programs"] >= 3
    assert DAILY_TICKER not in status["lip"]["pinned"]


def test_the_next_window_is_pinned_before_it_starts_and_the_last_one_after_it_ends(tmp_path: Path) -> None:
    edge = BOUNDARY + PERIOD
    clock = Clock(edge - 40)
    box, _ = lip_box(tmp_path, clock)
    run_until(box, clock, edge + 20)
    box.close()
    calls = lip_calls(tmp_path)
    nxt, now = set(tickers_at(1)), set(tickers_at(0))
    first_next = min(call["requested_at"] for call in calls if set(call["tickers"]) & nxt)
    assert edge - LIP_LEAD_S <= first_next < edge  # the new window's book is there from its first scored second
    last_old = max(call["requested_at"] for call in calls if set(call["tickers"]) & now)
    assert edge <= last_old < edge + LIP_TAIL_S  # and the old one through its last
    assert all(not set(call["tickers"]) & now for call in calls if call["requested_at"] >= edge + LIP_TAIL_S)


# --------------------------------------------------------------------------- program snapshots
def rebuild(snapshots: list[dict[str, Any]]) -> list[tuple[float, set[str]]]:
    state: dict[str, dict[str, Any]] = {}
    out = []
    for record in snapshots:
        if record["full"]:
            state = {row["id"]: row for row in record["rows"]}
        else:
            for pid in record["removed"]:
                state.pop(pid)
            for row in record["added"] + record["changed"]:
                state[row["id"]] = row
        assert len(state) == record["count"]
        out.append((record["received_at"], set(state)))
    return out


def test_program_snapshots_are_full_then_lossless_diffs_on_a_fixed_cadence(tmp_path: Path) -> None:
    clock = Clock(BOUNDARY + 100)
    box, fake = lip_box(tmp_path, clock, lip_programs_interval_s=300)
    run_until(box, clock, BOUNDARY + PERIOD + 400)
    box.close()
    snapshots = [record for record in records(tmp_path, "lip") if record["kind"] == "programs"]
    active = [record for record in snapshots if record["status"] == "active"]
    assert active[0]["full"] and not any(record["full"] for record in active[1:]) and len(active) >= 4
    for received_at, ids in rebuild(active):  # every diff rebuilds exactly the list the venue showed
        assert ids == {row["id"] for row in fake.programs if fake.status(row, received_at) == "active"}
    for record in active[1:]:  # 5 s after each 5-minute boundary (the setting), whatever the start time
        assert 5 <= record["requested_at"] % 300 < 20
    crossing = next(record for record in active if record["requested_at"] > BOUNDARY + PERIOD)
    assert {row["id"] for row in crossing["added"]} == {f"{name}-1" for name, _ in FAST}
    assert set(crossing["removed"]) == {f"{name}-0" for name, _ in FAST}
    assert {record["status"] for record in snapshots} == {"active", "upcoming", "closed"}
    upcoming = next(record for record in snapshots if record["status"] == "upcoming")
    assert upcoming["full"] and upcoming["count"] == 3 * 9  # windows 1..9 of every fast series


def test_program_pages_are_joined_into_one_snapshot(tmp_path: Path) -> None:
    clock = Clock(BOUNDARY + 100)
    box, fake = lip_box(tmp_path, clock, LipVenue(clock, page_size=2))
    run_until(box, clock, BOUNDARY + 140)
    box.close()
    first = next(record for record in records(tmp_path, "lip")
                 if record["kind"] == "programs" and record["status"] == "active")
    assert first["count"] == 4 and len(first["pages"]) == 2 and len(first["rows"]) == 4
    assert [page["page"] for page in first["pages"]] == [1, 2]
    asked = [call for call in fake.calls if call["path"] == "/incentive_programs" and "type" in call["query"]]
    assert all(call["query"]["type"] == ["liquidity"] and call["query"]["limit"] == ["10000"] for call in asked)
    assert any(call["query"].get("cursor") == ["2"] for call in asked)


# --------------------------------------------------------------------------- prints and settlement
def trade(ticker: str, at: float, trade_id: str) -> dict[str, Any]:
    return {"trade_id": trade_id, "ticker": ticker, "created_time": iso(at).replace("Z", ".100000Z"),
            "yes_price_dollars": "0.4000", "no_price_dollars": "0.6000", "count_fp": "3.00",
            "taker_outcome_side": "yes", "taker_book_side": "ask", "taker_side": "yes", "is_block_trade": False}


def test_lip_prints_and_settlement_rows_go_to_the_lip_lanes_never_to_family_a(tmp_path: Path) -> None:
    clock = Clock(BOUNDARY + PERIOD - 120)
    box, fake = lip_box(tmp_path, clock, settlement_interval_s=60)
    ticker = tickers_at(0)[0]
    fake.trades = [trade(ticker, BOUNDARY + PERIOD - 60, "lip-1"), trade(CANDIDATE, BOUNDARY + PERIOD - 60, "fa-1")]
    run_until(box, clock, BOUNDARY + PERIOD + 200)
    box.close()
    kept = [row["trade_id"] for record in records(tmp_path, "trades_lip") for row in record["rows"]]
    assert kept == ["lip-1"]
    assert "lip-1" not in [row["trade_id"] for record in records(tmp_path, "trades") for row in record["rows"]]
    settled = [row for record in records(tmp_path, "lip") if record["kind"] == "settlement" for row in record["rows"]]
    assert ticker in {row["ticker"] for row in settled if row["status"] == "finalized"}
    assert not any(row["ticker"] == ticker for record in records(tmp_path, "settlement") for row in record["rows"])
    watch = [record for record in records(tmp_path, "lip") if record["kind"] == "watch" and ticker in record["tickers"]]
    assert [record["action"] for record in watch] == ["start", "stop"] and watch[1]["reason"] == "finalized"
    assert ticker not in box.watched
    coverage = records(tmp_path, "trade_coverage")
    assert any(row["from"] <= BOUNDARY + PERIOD - 60 <= row["to"] for row in coverage)  # the tape vouches for it


# --------------------------------------------------------------------------- the shared budget
def test_due_lip_books_go_first_and_the_lane_they_pass_is_counted(tmp_path: Path) -> None:
    clock = Clock(NOW)
    fake = venue()
    box = recorder(tmp_path, fake, clock, btc15m=False)
    box.lip_queue, box.next_lip_at = deque(), {name: math.inf for name in box.next_lip_at}  # no LIP GETs here
    box._watch(Watched(CANDIDATE, "KXHIGHNY-26OCT15", "KXHIGHNY", "Climate and Weather", "candidate", NOW - 86400,
                       NOW + 86400, "active", NOW))
    box.next_discovery_at = box.next_trades_at = box.next_other_at = box.next_series_fees_at = math.inf
    box.next_sweep_at = box.next_books_at = clock.at  # a sweep and a Family A book call are both due
    box.lanes["books"].pass_value = 10.0  # books went often lately: the fair queue picks the sweep
    assert box.step() and fake.calls[-1]["path"] == "/markets"  # control: without LIP books, it does
    box.lip_windows = {"p": LipWindow("p", "KXZZZUSD15M-26OCT131845-30", NOW - 10, NOW + 890, "active")}
    box.lip_version += 1
    box.next_sweep_at = clock.at
    box.sweep_queue.clear()
    box.lanes["sweep"].backoff_until = -math.inf
    assert box.step() and fake.calls[-1]["path"] == "/markets/orderbooks"  # now the LIP book call goes first
    assert "KXZZZUSD15M-26OCT131845-30" in fake.calls[-1]["query"]["tickers"]
    assert box.degraded["preempted:sweep"] == 1 and box.lanes["sweep"].hour["preempted_by_lip_books"] == 1
    assert box.lanes["books"].pass_value == 10.0  # the pick happened outside the fair queue's accounting
    first = clock.at
    while fake.calls[-1]["path"] != "/markets":  # the sweep waits for the next LIP book call, then goes
        if not box.step():
            clock.sleep(0.05)
        assert clock.at - first < 3
    assert box.degraded["held:sweep"] == 1
    next_minute(box, clock)  # the minute rolls over: the slowing is written down
    assert degraded(box)["preempted:sweep"] >= 1 and degraded(box)["held:sweep"] == 1
    box.close()


def test_two_starts_per_second_is_never_exceeded_while_lip_books_keep_their_second(tmp_path: Path) -> None:
    clock = Clock(BOUNDARY + 100)
    box, _ = lip_box(tmp_path, clock)
    run_until(box, clock, BOUNDARY + 400)
    box.close()
    starts = sorted(row["requested_at"] for row in records(tmp_path, "requests"))
    window: deque[float] = deque()
    for at in starts:
        window.append(at)
        while window[0] <= at - 1.0:
            window.popleft()
        assert len(window) <= 2
    calls = [call["requested_at"] for call in lip_calls(tmp_path)]
    assert max(later - earlier for earlier, later in pairwise(calls)) <= 1.5
    paths = {row["path"] for row in records(tmp_path, "requests")}
    assert {"/markets/trades", "/events", "/incentive_programs"} <= paths  # the other lanes still ran
    assert any(path.startswith("/live_data/events/") for path in paths)


def test_family_a_books_displaced_by_lip_pins_are_written_down(tmp_path: Path) -> None:
    clock = Clock(BOUNDARY + 100)
    box, fake = lip_box(tmp_path, clock)
    box.lip_queue, box.next_lip_at = deque(), {name: math.inf for name in box.next_lip_at}
    box.lip_windows = {f"p{i}": LipWindow(f"p{i}", ticker, BOUNDARY, BOUNDARY + PERIOD, "active")
                       for i, ticker in enumerate(tickers_at(0))}
    box.lip_version += 1
    box._watch(*(Watched(f"KXHIGHNY-26OCT15-T{i:03d}", "KXHIGHNY-26OCT15", "KXHIGHNY", "Climate and Weather",
                         "candidate", NOW - 86400, NOW + 86400, "active", NOW) for i in range(100)))
    request = box._plan_books(clock.at)
    assert request is not None and len(request.context["tickers"]) == 100
    assert sorted(request.context["lip"]) == sorted(tickers_at(0)) and request.context["displaced"] == 3
    box.next_discovery_at = box.next_trades_at = box.next_other_at = box.next_series_fees_at = math.inf
    for _ in range(50):
        if any(call["path"] == "/markets/orderbooks" for call in fake.calls):
            break
        if not box.step():
            clock.sleep(0.25)
    next_minute(box, clock)
    assert degraded(box)["familya_books_displaced"] >= 3
    box.close()


def test_more_lip_markets_than_the_pin_cap_are_dropped_and_counted(tmp_path: Path) -> None:
    clock = Clock(BOUNDARY + 100)
    box, _ = lip_box(tmp_path, clock, lip_max_pinned=2)
    run_until(box, clock, BOUNDARY + 130)
    next_minute(box, clock)
    calls = [record for record in live(box, "lip") if record["kind"] == "book_call"]
    assert calls and all(len(call["tickers"]) == 2 for call in calls)
    assert degraded(box)["lip_pins_dropped"] >= 1
    box.close()


# --------------------------------------------------------------------------- the free 1 s settlement series
def test_the_free_settlement_series_keeps_each_point_once_lists_revisions_and_holes(tmp_path: Path) -> None:
    clock = Clock(BOUNDARY + 100)
    box, fake = lip_box(tmp_path, clock)
    run_until(box, clock, BOUNDARY + 140)
    series = [record for record in live(box, "lip") if record["kind"] == "series"]
    assert {record["series"] for record in series} == {"KXZZZUSD15M", "KXQQQMETAL15M"}
    assert all(len(record["new"]) == 3601 and record["points_in_reply"] == 3601 for record in series)
    unavailable = [record for record in live(box, "lip") if record["kind"] == "series_unavailable"]
    assert [record["series"] for record in unavailable] == ["KXRACE15M"]  # a 404: asked again only a day later
    first_end = {record["series"]: record["new"][-1][0] for record in series}
    overlap = first_end["KXZZZUSD15M"] - 5000
    before = fake.value("KXZZZUSD15M", overlap)
    fake.revise[("KXZZZUSD15M", overlap)] = 1.23456
    run_until(box, clock, BOUNDARY + 140 + 610)
    later = [record for record in live(box, "lip") if record["kind"] == "series"][len(series):]
    zzz = next(record for record in later if record["series"] == "KXZZZUSD15M")
    assert zzz["new"][0][0] == first_end["KXZZZUSD15M"] + 1000 and 590 <= len(zzz["new"]) <= 640
    assert zzz["revised"] == [[overlap, before, 1.23456]]
    race_asks = [call for call in fake.calls if call["path"].startswith("/live_data/events/KXRACE15M")]
    assert len(race_asks) == 1
    clock.at += 2 * 3600  # the recorder was stopped for two hours: the series has a hole it cannot fill
    run_until(box, clock, clock.at + 40)
    box.close()
    holes = [record for record in records(tmp_path, "gaps") if record.get("cause") == "lip_series_hole"]
    assert {record["series"] for record in holes} == {"KXZZZUSD15M", "KXQQQMETAL15M"}


# --------------------------------------------------------------------------- storage and status
MB = 1024 * 1024


def _fill(box: RecorderStore, lane: str, hours: int, start: float, size: int = 150_000) -> None:
    for hour in range(hours):
        box.append(lane, "blob", {"blob": base64.b64encode(os.urandom(size)).decode()}, start + hour * 3600)


def test_lip_and_pyth_are_shed_before_family_a_and_kept_for_their_own_retention(tmp_path: Path) -> None:
    at = {"now": NOW}
    box = RecorderStore(tmp_path, max_bytes=64 * MB, min_free_bytes=0, clock=lambda: at["now"],
                        disk_free=lambda path: 10 ** 12, headroom_bytes=16 * 1024, btc15m_retention_s=3600.0,
                        retention_s={"lip": 10 * 3600.0, "pyth": 10 * 3600.0})
    _fill(box, "books_lip", 4, NOW)  # hours 0-3
    _fill(box, "pyth", 4, NOW)
    _fill(box, "books_btc15m", 4, NOW)
    _fill(box, "books", 4, NOW)
    at["now"] = NOW + 12 * 3600
    box.seal_hour(at["now"])
    family = {segment.path for segment in load_index(tmp_path) if segment.lane == "books"}
    box.max_bytes = int(box.used_bytes() * 0.6)
    status = box.enforce()
    left = {segment.lane for segment in load_index(tmp_path)}
    assert "btc15m_older_than_retention" in status.reasons and "lip_older_than_retention" in status.reasons
    assert "books" in left and {segment.path for segment in load_index(tmp_path) if segment.lane == "books"} == family
    # A younger LIP segment is kept for its retention even under pressure: the LIP and Pyth lanes are shed (and
    # Family A goes on) rather than delete it.
    _fill(box, "books_lip", 1, at["now"])
    box.seal_hour(at["now"] + 3600)
    young = [segment.path for segment in load_index(tmp_path) if segment.lane == "books_lip"]
    deletable = sum(segment.gz_bytes for segment, _ in box._deletable(at["now"]))
    box.max_bytes = int((box.used_bytes() - deletable) / 0.97)
    assert box.enforce().level == LEVEL_SHED
    assert [segment.path for segment in load_index(tmp_path) if segment.lane == "books_lip"] == young
    assert box.append("books_lip", "book", {}, at["now"]) is None and box.append("pyth", "updates", {}) is None
    assert box.append("books", "book", {}, at["now"]) is not None  # Family A still records
    assert box.retention("lip") == 10 * 3600.0 and box.retention("btc15m") == 3600.0
    box.close()


def test_status_counts_bytes_per_lane_and_estimates_a_day(tmp_path: Path) -> None:
    clock = Clock(BOUNDARY + 100)
    box, _ = lip_box(tmp_path, clock)
    run_until(box, clock, BOUNDARY + 400)
    clock.at = (math.floor(clock.at / 60) + 1) * 60 + 1
    box.step()
    status = json.loads((tmp_path / "kalshi_recorder" / "status.json").read_text())
    box.close()
    lanes = status["lane_bytes"]
    for lane in ("books_lip", "lip", "requests"):
        row = lanes[lane]
        assert row["session_raw_bytes"] > 0 and row["session_records"] > 0 and row["stored_bytes"] > 0
        assert row["est_stored_bytes_per_day"] is not None and row["est_stored_bytes_per_day"] > 0
    assert status["pyth"] == {"state": "off", "reason": "no PYTH_API_KEY"}


# --------------------------------------------------------------------------- settings
def test_lip_settings_are_validated_and_the_in_bot_profile_turns_the_lane_off() -> None:
    settings = RecorderSettings()
    assert settings.lip and settings.lip_max_period_s == 900 and settings.lip_max_pinned == 40
    assert not settings.in_bot().lip
    loaded = RecorderSettings.from_env({"KALSHI_RECORDER_LIP": "false", "KALSHI_RECORDER_LIP_MAX_PERIOD_S": "3600",
                                        "KALSHI_RECORDER_PYTH_CHANNEL": "fixed_rate@200ms"})
    assert (loaded.lip, loaded.lip_max_period_s, loaded.pyth_channel) == (False, 3600.0, "fixed_rate@200ms")
    from nightcrawler.config import ConfigError

    for env, words in (({"KALSHI_RECORDER_LIP_MAX_PINNED": "99"}, "LIP_MAX_PINNED"),
                       ({"KALSHI_RECORDER_LIP_SERIES_INTERVAL_S": "4000"}, "LIP_SERIES_INTERVAL_S"),
                       ({"KALSHI_RECORDER_PYTH_BASE": "https://example.com/hermes"}, "PYTH_BASE"),
                       ({"KALSHI_RECORDER_PYTH_CHANNEL": "fastest"}, "PYTH_CHANNEL")):
        with pytest.raises(ConfigError, match=words):
            RecorderSettings.from_env(env)


def test_with_the_lane_off_nothing_about_lip_is_asked_or_written(tmp_path: Path) -> None:
    clock = Clock(BOUNDARY + 100)
    box, fake = lip_box(tmp_path, clock, lip=False)
    run_until(box, clock, BOUNDARY + 160)
    box.close()
    assert not any(call["path"].startswith("/live_data") for call in fake.calls)
    assert not any(call["path"] == "/incentive_programs" and call["query"].get("type") == ["liquidity"]
                   for call in fake.calls)  # the daily Family A "other" pull has no type and stays
    assert not records(tmp_path, "lip", "books_lip", "trades_lip")
    assert all(not set(call["query"].get("tickers", [])) & set(tickers_at(0))
               for call in fake.calls if call["path"] == "/markets/orderbooks")


class SlowSession:
    """The scripted venue with a real round trip: every GET takes ``rtt`` seconds of the fake clock."""

    def __init__(self, fake: FakeKalshi, clock: Clock, rtt: float) -> None:
        self.fake, self.clock, self.rtt = fake, clock, rtt

    def get(self, url: str, params: Any = None, headers: Any = None, **kwargs: Any) -> FakeResponse:
        self.clock.at += self.rtt
        return self.fake("GET", url, params=params, headers=headers, **kwargs)


def run_like_service(box: Recorder, clock: Clock, until: float) -> None:
    """``Recorder.run``'s loop on the fake clock: idle 0.2 s at most, and never past the next LIP book call."""
    while clock.at < until:
        if not box.step():
            wake = box.wake_at
            clock.sleep(0.2 if wake is None else min(0.2, max(0.001, wake - clock.at)))


def test_with_real_round_trips_lip_books_keep_their_second_and_the_others_share_the_rest(tmp_path: Path) -> None:
    """Measured live before this fix: 2.67 s between LIP book calls (target-rate spacing plus round trips)."""
    clock = Clock(BOUNDARY + 100)
    fake = LipVenue(clock)
    client = PublicKalshi(RateLimiter(1.5, burst=2.0, clock=clock.mono, sleep=clock.sleep),
                          session=SlowSession(fake, clock, 0.3), wall=clock.wall, mono=clock.mono)
    box = Recorder(RecorderSettings(data_dir=tmp_path, btc15m=False), client=client, wall=clock.wall)
    # A backlog the other lanes could never finish in the run: 600 one-page backfill windows of the candidate.
    box.backfill_jobs.extend(TradeJob(int(NOW) - 7200 + 10 * index, int(NOW) - 7190 + 10 * index, CANDIDATE, True)
                             for index in range(600))
    run_like_service(box, clock, BOUNDARY + 700)
    next_minute(box, clock)
    held = Counter({key: value for key, value in degraded(box).items() if key.startswith("held:")})
    box.close()
    calls = [call["requested_at"] for call in lip_calls(tmp_path) if call["requested_at"] <= BOUNDARY + 700]
    intervals = sorted(later - earlier for earlier, later in pairwise(calls))
    assert len(calls) > 500 and intervals[len(intervals) // 2] == pytest.approx(1.0, abs=0.01)
    assert intervals[-1] <= 1.0 + 0.1 + 1e-6  # never more than the slack late, and never carried forward
    starts = sorted(row["requested_at"] for row in records(tmp_path, "requests") if row["requested_at"] <= BOUNDARY + 700)
    assert len(starts) / (starts[-1] - starts[0]) <= 1.5 * 1.02  # the average stays at the target
    window: deque[float] = deque()
    for at in starts:
        window.append(at)
        while window[0] <= at - 1.0:
            window.popleft()
        assert len(window) <= 2  # and the ceiling holds
    others = [row for row in records(tmp_path, "requests")
              if row["request_lane"] != "books" and row["requested_at"] <= BOUNDARY + 700]
    assert len(others) / (starts[-1] - starts[0]) >= 0.4  # the other lanes still get the rest of the budget
    assert sum(held.values()) > 0  # and the waits they took for the LIP book call are written down


def test_spare_slots_refresh_a_candidate_at_most_every_five_seconds(tmp_path: Path) -> None:
    """With LIP book calls every second, a short candidate list is not asked every second (storage and replay)."""
    clock = Clock(BOUNDARY + 100)
    box, _ = lip_box(tmp_path, clock)
    run_like_service(box, clock, BOUNDARY + 400)
    box.close()
    asked = [call["requested_at"] for call in records(tmp_path, "book_calls") if CANDIDATE in call["tickers"]]
    lip = lip_calls(tmp_path)
    assert len(lip) > 250 and len(asked) >= 40  # far fewer than the LIP calls it could have ridden in
    assert min(later - earlier for earlier, later in pairwise(asked)) >= 5.0
    assert max(later - earlier for earlier, later in pairwise(asked)) <= 20.0 + 1.5  # its protocol cadence holds
