"""Faults the 2026-10-13 isolation review found (F1-F10, R9): no reply may halt the recorder or wedge a lane.

Every case runs against the scripted public venue in ``kalshi_recorder_fixtures``; nothing touches the network.
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from itertools import pairwise
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
import requests
from kalshi_recorder_fixtures import (
    NOW,
    Clock,
    FakeKalshi,
    FakeResponse,
    event_row,
    iso,
    market_row,
    orderbook,
)
from test_kalshi_recorder import CANDIDATE, recorder, records, run, venue

from nightcrawler import kalshi_recorder
from nightcrawler.kalshi_public import Fetched
from nightcrawler.kalshi_recorder import (
    PAGE_ATTEMPTS,
    SWEEP_QUERY_BYTES,
    TICKERS_PER_SWEEP,
    RecorderSettings,
    Request,
    TradeJob,
    Watched,
    main,
    run_recorder,
    start_from_engine,
)
from nightcrawler.kalshi_recorder_store import RecorderStore, iter_records


def gaps(tmp_path: Path) -> list[dict[str, Any]]:
    return [record for record in records(tmp_path, "gaps") if record["kind"] == "gap"]


def candidate(ticker: str, *, close: float = NOW + 86400, status: str = "active") -> Watched:
    return Watched(ticker, "KXHIGHNY-26OCT15", "KXHIGHNY", "Climate and Weather", "candidate", NOW - 86400, close,
                   status, NOW - 3600)


# --------------------------------------------------------------------------- F1: malformed replies
def test_a_nan_in_one_trade_row_never_halts_the_recorder(tmp_path: Path) -> None:
    """F1: the NaN reached the store, the handler_error record itself raised, and run() stopped."""
    clock, fake = Clock(NOW), venue()
    raw = (b'{"trades":[{"trade_id":"t1","ticker":"' + CANDIDATE.encode()
           + b'","created_time":"2026-10-13T18:30:01Z","count_fp":NaN}],"cursor":""}')
    fake.routes["/markets/trades"] = lambda query: FakeResponse(200, raw)
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 600)  # raised ValueError('Record payloads may not set lane') within 3 calls before the fix
    books_before = sum(1 for call in fake.calls if call["path"] == "/markets/orderbooks")
    run(box, clock, 100)
    box.close()
    assert sum(1 for call in fake.calls if call["path"] == "/markets/orderbooks") > books_before  # still recording
    causes = [record["cause"] for record in gaps(tmp_path)]
    assert "trade_page_failed_invalid_json" in causes  # the window is a gap, then a backfill
    assert any(record.get("backfill") == "failed" for record in gaps(tmp_path))  # the backfill gave up too


def test_a_malformed_page_is_retried_then_skipped_and_discovery_finishes(tmp_path: Path) -> None:
    """F1: '"markets": 5' raised TypeError on every retry; the discovery stage never moved on."""
    clock, fake = Clock(NOW), venue()
    fake.routes["/markets"] = lambda query: FakeResponse(200, {"markets": 5, "cursor": ""})
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 120)
    box.close()
    errors = [record for record in records(tmp_path, "gaps") if record["kind"] == "handler_error"]
    assert len(errors) == PAGE_ATTEMPTS and {record["handler_lane"] for record in errors} == {"discovery"}
    assert all(record["error"] == "Malformed" and record["detail"] for record in errors)
    skipped = [record for record in gaps(tmp_path) if record["cause"] == "malformed_reply"]
    assert skipped and skipped[0]["stage"] == "markets" and skipped[0]["item"] == "KXHIGHNY"
    assert any(record["kind"] == "discovery_summary" for record in records(tmp_path, "admissions"))


def test_a_trade_page_that_cannot_be_processed_counts_its_attempts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F1: the trades lane reset job.attempts before processing, so a failing page was fetched forever."""
    clock, fake = Clock(NOW), venue()
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 60)
    fake.trades = [{"trade_id": "t1", "ticker": CANDIDATE, "created_time": iso(clock.at - 1)}]

    def broken(*args: Any) -> None:
        raise RuntimeError("cannot keep this page")

    monkeypatch.setattr(box, "_keep_trades", broken)
    run(box, clock, 200)
    box.close()
    errors = [record for record in records(tmp_path, "gaps") if record["kind"] == "handler_error"
              and record["handler_lane"] in ("trades", "backfill")]
    assert errors and all(record["detail"] == "cannot keep this page" for record in errors)
    causes = [record["cause"] for record in gaps(tmp_path)]
    assert "handler_error_RuntimeError" in causes  # abandoned after PAGE_ATTEMPTS, never fetched forever


# --------------------------------------------------------------------------- F2: odd fields that the transport refuses
def test_a_float_cursor_and_an_unusable_series_name_never_halt_discovery(tmp_path: Path) -> None:
    """F2: a float cursor raised TypeError and a lowercase series_ticker raised ValueError outside the guard."""
    clock, fake = Clock(NOW), venue()
    fake.events = [event_row(), event_row("kxweird-26OCT15", "kxweird", "Climate and Weather")]
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 120)
    assert all(call["path"] != "/series/kxweird" for call in fake.calls)
    assert any(record["cause"] == "series_ticker_unusable" and record["series"] == ["kxweird"]
               for record in box.gaps_this_hour)  # this hour's gaps (its segment is not sealed yet)
    assert CANDIDATE in box.watched  # the rest of the pass went on
    fake.routes["/events"] = lambda query: FakeResponse(200, {"events": fake.events, "cursor": 1.5})
    box.next_discovery_at = clock.at
    run(box, clock, 120)
    box.close()
    assert any(record["cause"] == "malformed_reply" and record["stage"] == "events" for record in gaps(tmp_path))


def test_a_request_the_transport_refuses_becomes_a_gap_not_a_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock(NOW)
    box = recorder(tmp_path, venue(), clock, btc15m=False)
    original = box.client.get

    def get(lane: str, path: str, params: Any = None, stop: Any = None) -> Fetched:
        if path == "/series/fee_changes":
            raise ValueError(f"{path!r} is not a public Kalshi market-data path")
        return original(lane, path, params, stop)

    monkeypatch.setattr(box.client, "get", get)
    run(box, clock, 80)
    box.close()
    refused = [record for record in records(tmp_path, "gaps") if record["kind"] == "request_refused"]
    assert len(refused) == 1 and refused[0]["handler_lane"] == "fees"  # dropped at once, retried in an hour
    assert box.next_series_fees_at >= NOW + 3600


# --------------------------------------------------------------------------- F6: lanes that wedged on a persistent error
def test_a_414_halves_the_sweep_chunk_until_kalshi_takes_it(tmp_path: Path) -> None:
    clock, fake = Clock(NOW), venue()
    box = recorder(tmp_path, fake, clock, btc15m=False)
    for index in range(40):
        box._watch(candidate(f"KXHIGHNY-26OCT15-T{index:02d}"))
    original = fake.route

    def route(path: str, query: dict[str, list[str]]) -> FakeResponse:
        if path == "/markets" and "tickers" in query and len(query["tickers"][0].split(",")) > 10:
            return FakeResponse(414, {"error": "uri too long"})
        return original(path, query)

    fake.route = route  # type: ignore[method-assign]
    box.next_sweep_at = clock.at
    run(box, clock, 300)
    box.close()
    assert not box.sweep_queue
    halved = [record for record in records(tmp_path, "telemetry") if record["kind"] == "chunk_halved"]
    assert halved and all(record["status"] == 414 for record in halved) and min(r["chunk_size"] for r in halved) <= 10
    assert any(record["kind"] == "sweep" for record in records(tmp_path, "markets"))
    taken = {ticker for call in fake.calls if call["path"] == "/markets" and "tickers" in call["query"]
             for ticker in call["query"]["tickers"][0].split(",") if len(call["query"]["tickers"][0].split(",")) <= 10}
    assert len(taken) == 40  # every ticker went out in a chunk Kalshi took


def test_a_settlement_call_that_keeps_failing_is_dropped_with_a_gap(tmp_path: Path) -> None:
    """F6: 157 retries in 1.3 h and the queue never drained; settlement is the only way off the watch list."""
    clock, fake = Clock(NOW), venue()
    box = recorder(tmp_path, fake, clock, btc15m=False)
    box._watch(candidate("KXHIGHNY-26OCT12-T70", close=NOW - 3600, status="closed"))
    original = fake.route
    calls = {"n": 0}

    def route(path: str, query: dict[str, list[str]]) -> FakeResponse:
        if path == "/markets" and "tickers" in query:
            calls["n"] += 1
            return FakeResponse(500, {"error": "scripted"})
        return original(path, query)

    fake.route = route  # type: ignore[method-assign]
    box.next_settlement_at = clock.at
    box.next_sweep_at = clock.at + 10 ** 6
    run(box, clock, 400)
    box.close()
    assert not box.settle_queue and calls["n"] == PAGE_ATTEMPTS
    assert any(record["cause"] == "settlement_page_failed_500" for record in gaps(tmp_path))


def test_a_fee_lookup_the_venue_keeps_refusing_is_dropped_then_retried_an_hour_later(tmp_path: Path) -> None:
    clock, fake = Clock(NOW), venue()
    fake.routes["/events/fee_changes"] = lambda query: FakeResponse(404, {"error": "not found"})
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 200)
    first = sum(1 for call in fake.calls if call["path"] == "/events/fee_changes")
    assert first == PAGE_ATTEMPTS and not box.fee_queue  # the next event is not held behind it
    assert any(record["cause"] == "fee_lookup_failed_404" for record in box.gaps_this_hour)
    clock.at += 3700
    run(box, clock, 100)
    box.close()
    assert sum(1 for call in fake.calls if call["path"] == "/events/fee_changes") > first


def test_sweep_chunks_stay_under_the_url_budget() -> None:
    box = object.__new__(kalshi_recorder.Recorder)
    box.chunk_size = TICKERS_PER_SWEEP
    tickers = [f"KXBTCD-26OCT{index % 28 + 1:02d}17-T{100000 + index}.99" for index in range(2000)]
    chunks = box._chunks(tickers)
    assert [ticker for chunk in chunks for ticker in chunk] == tickers
    for chunk in chunks:
        assert len(chunk) <= TICKERS_PER_SWEEP and len(quote(",".join(chunk), safe="")) <= SWEEP_QUERY_BYTES


# --------------------------------------------------------------------------- F8: Retry-After
def test_a_long_retry_after_is_clamped_and_recorded_as_a_gap(tmp_path: Path) -> None:
    clock, fake = Clock(NOW), venue()
    state = {"sent": False}

    def books(query: dict[str, list[str]]) -> FakeResponse:
        if not state["sent"]:
            state["sent"] = True
            return FakeResponse(429, {"error": "slow down"}, {"Retry-After": "31536000"})
        return FakeResponse(200, {"orderbooks": []})

    fake.routes["/markets/orderbooks"] = books
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 300)
    box.close()
    hold = [record for record in gaps(tmp_path) if record["cause"] == "retry_after_hold"]
    assert hold and hold[0]["seconds"] == 900.0 and hold[0]["to"] - hold[0]["from"] == 900.0
    assert clock.at - NOW < 2000  # held for 15 minutes, not a year


# --------------------------------------------------------------------------- F3 and F10: the engine hook
def test_the_engine_hook_refuses_while_any_desk_in_the_process_trades_live(tmp_path: Path,
                                                                          caplog: pytest.LogCaptureFixture) -> None:
    stop = threading.Event()
    with caplog.at_level(logging.WARNING, logger="nightcrawler.kalshi_recorder"):
        thread = start_from_engine(tmp_path, stop, env={"KALSHI_RECORDER_ENABLED": "true",
                                                        "SPEEDDESK_KALSHI_MODE": "live"})
    assert thread is None and "live_trading_in_this_process" in caplog.text and "SPEEDDESK_KALSHI_MODE" in caplog.text
    assert not (tmp_path / "kalshi_recorder").exists()


def test_the_engine_hook_reads_dotenv_like_the_bot_and_runs_the_reduced_profile(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """F3/F10: .env was ignored; inside the bot the recorder now runs at 0.25/s with KXBTC15M off."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(os, "environ", {"KALSHI_RECORDER_RATE_PER_S": "1.5"})
    started: list[RecorderSettings] = []
    monkeypatch.setattr(kalshi_recorder, "run_recorder", lambda settings, stop: started.append(settings))
    (tmp_path / ".env").write_text("KALSHI_RECORDER_ENABLED=true\nPOLYDESK_MODE=live\nKALSHI_KEY_ID=not-read\n")
    with caplog.at_level(logging.WARNING, logger="nightcrawler.kalshi_recorder"):
        assert start_from_engine(tmp_path / "data", threading.Event()) is None
    assert "POLYDESK_MODE" in caplog.text and "not-read" not in caplog.text
    (tmp_path / ".env").write_text("KALSHI_RECORDER_ENABLED=true\nPOLYDESK_MODE=paper\n")
    thread = start_from_engine(tmp_path / "data", threading.Event())
    assert thread is not None
    thread.join(5)
    settings = started[0]
    assert (settings.rate_per_s, settings.btc15m, settings.min_free_mb) == (0.25, False, 1024)
    assert settings.data_dir == tmp_path / "data"


def test_a_halt_logs_its_detail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                caplog: pytest.LogCaptureFixture) -> None:
    def broken(settings: RecorderSettings) -> None:
        raise RuntimeError("the store\nis unreadable")

    monkeypatch.setattr(kalshi_recorder, "Recorder", broken)
    with caplog.at_level(logging.ERROR, logger="nightcrawler.kalshi_recorder"):
        run_recorder(RecorderSettings(data_dir=tmp_path), threading.Event())
    assert "kalshi_recorder_halted error=RuntimeError detail=the store is unreadable" in caplog.text


# --------------------------------------------------------------------------- F5: a copy of the bot's service
def test_run_refuses_next_to_trading_keys_or_live_switches_and_never_prints_a_value(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(tmp_path)
    for name, value in (("KALSHI_KEY_ID", "SECRET-VALUE-123"), ("POLYMARKET_US_SECRET_KEY", "SECRET-VALUE-456"),
                        ("POLYDESK_MODE", "live")):
        monkeypatch.setenv(name, value)
    assert main(["run", "--data-dir", str(tmp_path / "data"), "--max-runtime-s", "1"]) == 3
    err = capsys.readouterr().err
    assert "KALSHI_KEY_ID" in err and "POLYMARKET_US_SECRET_KEY" in err and "POLYDESK_MODE=live" in err
    assert "SECRET-VALUE" not in err
    assert not (tmp_path / "data" / "kalshi_recorder").exists()  # nothing started
    assert main(["status", "--data-dir", str(tmp_path / "data")]) == 0  # reading the store is still fine


# --------------------------------------------------------------------------- R9: prints of a ticker unwatched before its backfill
def test_a_backfill_after_unwatch_keeps_the_prints_its_coverage_claims(tmp_path: Path) -> None:
    from nightcrawler.kalshi_familya import load_coverage

    clock = Clock(NOW)
    box = recorder(tmp_path, FakeKalshi(), clock)
    ticker = "KXHIGHNY-26OCT14-T70"
    box._watch(Watched(ticker, "KXHIGHNY-26OCT14", "KXHIGHNY", "Climate and Weather", "candidate",
                       NOW - 86400, NOW - 600, "active", NOW - 3600))
    low, high = int(NOW - 1800), int(NOW - 1200)
    box._queue_backfill(low, high, "trade_page_failed_429")  # a window the live lane lost while watched
    box._unwatch(ticker, NOW, "finalized")  # the settlement lane finalizes it before the backfill runs
    request = box._plan_backfill(NOW)
    assert request is not None
    row = {"trade_id": "lost-1", "ticker": ticker, "created_time": iso(NOW - 1500), "yes_price_dollars": "0.6200",
           "no_price_dollars": "0.3800", "count_fp": "3.00", "taker_outcome_side": "no", "taker_book_side": "ask",
           "is_block_trade": False}
    box._done_backfill(request, Fetched("backfill", "/markets/trades", (), 200, None, NOW, NOW + 0.1, 100.0, 10,
                                        "0" * 64, {"trades": [row], "cursor": ""}, None))
    box.close()
    root = tmp_path / "kalshi_recorder"
    kept = [item for record in iter_records(root, frozenset({"trades"})) for item in record.get("rows") or []]
    assert load_coverage(root, NOW - 86400, NOW + 86400).tape(ticker, NOW - 1500, NOW - 1490)
    assert [item["trade_id"] for item in kept] == ["lost-1"]
    again = recorder(tmp_path, FakeKalshi(), clock)  # the memory of unwatched tickers survives a restart
    assert again.unwatched[ticker] == ("candidate", NOW)
    again.close()


def test_a_backlog_is_still_backfilled_when_its_only_ticker_was_unwatched(tmp_path: Path) -> None:
    clock = Clock(NOW)
    box = recorder(tmp_path, FakeKalshi(), clock)
    box._watch(candidate("KXHIGHNY-26OCT14-T70"))
    box._unwatch("KXHIGHNY-26OCT14-T70", NOW - 60, "finalized")
    box._queue_backfill(int(NOW - 600), int(NOW - 300), "trade_tape_behind")
    assert len(box.backfill_jobs) == 1  # was skipped: "no watched tickers, nothing missing"
    box._queue_backfill(int(NOW - 30), int(NOW), "trade_tape_behind")  # after the stop: nothing to keep
    assert len(box.backfill_jobs) == 1
    box.close()



# --------------------------------------------------------------------------- preflight 2026-10-13 (F2, P1/F3, P5-P7, M1)
def crash_copy(tmp_path: Path, name: str = "crash") -> Path:
    """What a SIGKILL right now would leave: the files as the OS holds them (Python's buffers die with the process),
    then recovered the way a restart recovers them."""
    copy = tmp_path / name
    shutil.copytree(tmp_path / "kalshi_recorder", copy / "kalshi_recorder")
    RecorderStore(copy / "kalshi_recorder", max_bytes=256 * 1024 * 1024, min_free_bytes=0).close()
    return copy


def fetched(lane: str, path: str, at: float, body: dict[str, Any]) -> Fetched:
    return Fetched(lane, path, (), 200, None, at - 0.1, at, 100.0, 10, "0" * 64, body, None)


def test_f2_the_main_loop_flushes_a_quiet_lane_so_a_kill_keeps_its_rows(tmp_path: Path) -> None:
    """F2: a lane was flushed only by a later append on it >= 5 s on; a quiet lane's rows sat in memory for an hour."""
    clock, fake = Clock(NOW), venue()
    box = recorder(tmp_path, fake, clock, btc15m=False)
    box.emit("telemetry", "probe", {"n": 1})
    run(box, clock, 4)
    box.emit("telemetry", "probe", {"n": 2})  # nothing else writes this lane for the rest of the hour
    written = clock.at
    while clock.at < written + 5.5:
        if not box.step():
            clock.sleep(0.25)
    copy = crash_copy(tmp_path)
    assert [record["n"] for record in records(copy, "telemetry") if record["kind"] == "probe"] == [1, 2]
    assert any(record["kind"] == "session_started" for record in records(copy, "gaps"))
    box.close()


CHILD = r"""
import sys
sys.path[:0] = sys.argv[2:]
from kalshi_recorder_fixtures import FakeKalshi, event_row, market_row, orderbook, series_row
from nightcrawler import kalshi_recorder
from nightcrawler.kalshi_public import PublicKalshi

fake = FakeKalshi()
fake.series = {"KXHIGHNY": series_row()}
fake.events = [event_row()]
fake.markets = {"KXHIGHNY-26OCT15-T76": market_row()}
fake.books = {"KXHIGHNY-26OCT15-T76": orderbook([("0.30", "12.00")], [("0.67", "40.00")])}


class Session:
    def get(self, url, params=None, headers=None, **kwargs):
        return fake("GET", url, params=params, headers=headers, **kwargs)


kalshi_recorder.PublicKalshi = lambda limiter, wall: PublicKalshi(limiter, session=Session(), wall=wall)
raise SystemExit(kalshi_recorder.main(["run", "--data-dir", sys.argv[1]]))
"""


@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGINT])
def test_f2_sigterm_or_sigint_flushes_and_seals_every_lane_before_exit(tmp_path: Path, number: int) -> None:
    """Railway stops a service with SIGTERM (then SIGKILL after drainingSeconds): every lane is sealed first."""
    source = Path(__file__).resolve().parents[1]
    child = subprocess.Popen([sys.executable, "-c", CHILD, str(tmp_path / "data"), str(source / "src"),
                              str(source / "tests")], cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, env={"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)})
    assert child.stdout is not None
    for line in child.stdout:
        if "kalshi_recorder_started" in line:
            break
    time.sleep(1.5)  # a few public GETs (to the scripted venue) land in several lanes
    child.send_signal(number)
    output = child.communicate(timeout=60)[0]
    assert child.returncode == 0, output
    assert "kalshi_recorder_stopped" in output
    root = tmp_path / "data" / "kalshi_recorder"
    assert not list(root.rglob("*.part"))  # sealed, nothing left for a recovery
    assert kalshi_recorder.verify(root)["ok"]
    lanes = {record["lane"] for record in iter_records(root, frozenset({"gaps", "requests", "fees", "admissions"}))}
    assert {"gaps", "requests"} <= lanes


@pytest.mark.parametrize("failure", ["500", "connect_timeout"])
def test_p1_one_discovery_item_that_always_fails_is_skipped_and_the_pass_still_admits(tmp_path: Path,
                                                                                     failure: str) -> None:
    """P1: a transient failure was never struck per item, so one bad series abandoned every pass at the same place."""
    clock, fake = Clock(NOW), venue()
    fake.series["KXBAD"] = {**fake.series["KXHIGHNY"], "ticker": "KXBAD"}
    fake.events = [*fake.events, event_row("KXBAD-26OCT15", "KXBAD")]
    original = fake.route

    def route(path: str, query: dict[str, list[str]]) -> FakeResponse:
        if path == "/markets" and query.get("series_ticker") == ["KXBAD"]:  # sorts before KXHIGHNY
            if failure == "connect_timeout":
                raise requests.exceptions.ConnectTimeout("scripted")
            return FakeResponse(500, {"error": "scripted"})
        return original(path, query)

    fake.route = route  # type: ignore[method-assign]
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 1500)
    box.close()
    assert CANDIDATE in box.watched  # was never admitted: 15 abandoned passes in 1.3 h
    assert any(record["kind"] == "discovery_summary" for record in records(tmp_path, "admissions"))
    skipped = [record for record in gaps(tmp_path) if record["cause"].startswith("discovery_markets_failed_")]
    assert skipped and skipped[0]["item"] == "KXBAD"
    assert sum(1 for call in fake.calls if call["query"].get("series_ticker") == ["KXBAD"]) == PAGE_ATTEMPTS
    assert not any(record["cause"].startswith("discovery_abandoned") for record in gaps(tmp_path))


def test_f3_after_an_abandoned_discovery_pass_the_next_pass_gets_its_own_attempts(tmp_path: Path) -> None:
    """F3: in_a_row was reset only by a success, so every pass after the first was abandoned on its first 429."""
    clock, fake = Clock(NOW), venue()
    fake.routes["/series"] = lambda query: FakeResponse(429, {"error": "slow down"})
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 3000)
    box.close()
    ends = sorted(record["to"] for record in gaps(tmp_path) if record["cause"] == "discovery_abandoned_429")
    assert len(ends) >= 2
    asked = [record["received_at"] for record in records(tmp_path, "requests") if record["request_lane"] == "discovery"]
    per_pass = [sum(1 for at in asked if low < at <= high) for low, high in pairwise([-math.inf, *ends])]
    assert all(count > PAGE_ATTEMPTS for count in per_pass), per_pass  # one item struck out, then a second failed


def test_f3_after_btc15m_metadata_is_given_up_the_retry_gets_its_own_attempts(tmp_path: Path) -> None:
    clock, fake = Clock(NOW), venue()
    fake.routes["/series/KXBTC15M"] = lambda query: FakeResponse(500, {"error": "scripted"})
    box = recorder(tmp_path, fake, clock)
    run(box, clock, 2000)
    box.close()
    rounds = sum(1 for record in gaps(tmp_path) if record["cause"] == "btc15m_metadata_unavailable")
    calls = sum(1 for call in fake.calls if call["path"] == "/series/KXBTC15M")
    assert rounds >= 2 and calls >= PAGE_ATTEMPTS * rounds  # was 5 + 1 per later round


def test_p5_the_sweep_chunk_grows_back_after_a_burst_of_4xx(tmp_path: Path) -> None:
    """P5: after 12 x 403 every later sweep sent one ticker per call (301 calls and 186 s for 300 candidates)."""
    clock, fake = Clock(NOW), venue()
    tickers = [f"KXHIGHNY-26OCT15-T{index:02d}" for index in range(60)]
    for ticker in tickers:
        fake.markets[ticker] = {**fake.markets[CANDIDATE], "ticker": ticker}
    box = recorder(tmp_path, fake, clock, btc15m=False)
    for ticker in tickers:
        box._watch(candidate(ticker))
    original = fake.route
    burst = {"left": 12}

    def route(path: str, query: dict[str, list[str]]) -> FakeResponse:
        if path == "/markets" and "tickers" in query and burst["left"] > 0:
            burst["left"] -= 1
            return FakeResponse(403, {"error": "challenge"})
        return original(path, query)

    fake.route = route  # type: ignore[method-assign]
    box.next_sweep_at = clock.at
    run(box, clock, 1500)
    assert not burst["left"] and not box.sweep_queue
    before = len(fake.calls)
    box.next_sweep_at = clock.at  # a later pass, after the burst
    run(box, clock, 200)
    box.close()
    later = [len(call["query"]["tickers"][0].split(",")) for call in fake.calls[before:]
             if call["path"] == "/markets" and "tickers" in call["query"]]
    candidates = sum(1 for item in box.watched.values() if item.kind == "candidate")
    assert later == [candidates] and box.chunk_size >= candidates  # one call, not 61


BAD_BOOKS = {
    "json_number": '{"yes_dollars":[["0.6200","5.00"]],"no_dollars":[["0.3500","10.00"]],"depth":1e400}',
    "decimal_string": '{"yes_dollars":[["1E+1000000","5.00"]],"no_dollars":[["0.3500","10.00"]]}',
}


@pytest.mark.parametrize("kind", sorted(BAD_BOOKS))
def test_p6_one_book_that_overflows_is_a_failed_read_for_that_ticker_alone(tmp_path: Path, kind: str) -> None:
    """P6: 1e400 parsed as inf, the store refused it mid-call, and every ticker sorted after it was never recorded."""
    clock, fake = Clock(NOW), venue()
    good = [f"KXHIGHNY-26OCT15-T{index:02d}" for index in range(10)]
    bad = "KXHIGHNY-26OCT15-T05X"  # sorts among the good ones
    book = json.dumps(orderbook([("0.62", "5.00")], [("0.35", "10.00")]))

    def books(query: dict[str, list[str]]) -> FakeResponse:
        parts = [f'{{"ticker":"{ticker}","orderbook_fp":{BAD_BOOKS[kind] if ticker == bad else book}}}'
                 for ticker in query.get("tickers", []) if ticker in good or ticker == bad]
        return FakeResponse(200, ('{"orderbooks":[' + ",".join(parts) + "]}").encode())

    fake.routes["/markets/orderbooks"] = books
    box = recorder(tmp_path, fake, clock, btc15m=False)
    for ticker in [*good, bad]:
        box._watch(candidate(ticker))
    start = clock.at
    run(box, clock, 2000)
    box.close()
    recorded = {record["ticker"] for record in records(tmp_path, "books") if record["kind"] == "book"}
    assert set(good) <= recorded and bad not in recorded
    assert not [record for record in records(tmp_path, "gaps") if record["kind"] == "handler_error"
                and record["handler_lane"] == "books"]
    unreadable = [record for record in gaps(tmp_path) if record["cause"] == "book_unreadable"]
    assert unreadable and {record["ticker"] for record in unreadable} == {bad}
    asked = sum(1 for call in fake.calls if call["path"] == "/markets/orderbooks" and bad in call["query"]["tickers"])
    assert asked <= (clock.at - start) / kalshi_recorder.SLOW_BOOK_S + 2  # the slow cadence, not every call


def test_p6_an_overflowing_number_in_a_sweep_reply_fails_only_the_ticker_that_carries_it(tmp_path: Path) -> None:
    clock, fake = Clock(NOW), venue()
    good = [f"KXHIGHNY-26OCT15-T{index:02d}" for index in range(20)]
    bad = "KXHIGHNY-26OCT15-T07X"
    for ticker in [*good, bad]:
        fake.markets[ticker] = {**fake.markets[CANDIDATE], "ticker": ticker}
    fake.markets[bad]["volume_fp"] = "__OVERFLOW__"
    original = fake.route

    def route(path: str, query: dict[str, list[str]]) -> FakeResponse:
        response = original(path, query)
        if path == "/markets" and "tickers" in query:
            response._raw = response._raw.replace(b'"__OVERFLOW__"', b"1e400")
        return response

    fake.route = route  # type: ignore[method-assign]
    box = recorder(tmp_path, fake, clock, btc15m=False)
    for ticker in [*good, bad]:
        box._watch(candidate(ticker))
    box.next_sweep_at = clock.at
    run(box, clock, 1500)
    box.close()
    swept = {row["ticker"] for record in records(tmp_path, "markets") if record["kind"] == "sweep"
             for row in record["rows"]}
    assert set(good) <= swept and bad not in swept
    assert any(record["error"] == "non_finite_number" for record in records(tmp_path, "requests"))
    assert not [record for record in records(tmp_path, "gaps") if record["kind"] == "handler_error"]


def test_p6_a_market_row_whose_decimal_overflows_is_refused_alone_and_discovery_admits_the_rest(tmp_path: Path) -> None:
    """An overflowing decimal string raised inside admission, and the next plan of the open pass raised IndexError."""
    clock, fake = Clock(NOW), venue()
    bad = "KXHIGHNY-26OCT15-T80"
    fake.markets[bad] = market_row(bad, price_ranges=[{"start": "0.0000", "end": "1E+1000000", "step": "0.0100"}])
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 600)
    box.close()
    assert CANDIDATE in box.watched and bad not in box.watched
    changed = [row for record in records(tmp_path, "admissions") if record["kind"] == "admissions"
               for row in record["changed"]]
    assert any(row["ticker"] == bad and row["reason"] == "row_unreadable" for row in changed)


def trade_row(trade_id: str, at: float) -> dict[str, Any]:
    return {"trade_id": trade_id, "ticker": CANDIDATE, "created_time": iso(at), "yes_price_dollars": "0.6200",
            "no_price_dollars": "0.3800", "count_fp": "1.00", "taker_outcome_side": "no", "taker_book_side": "ask",
            "is_block_trade": False}


def test_p7_a_crash_never_keeps_trade_coverage_for_prints_it_lost(tmp_path: Path) -> None:
    """P7: three live polls 4.9 s apart, then a SIGKILL: coverage for 3 windows survived and 0 of their prints."""
    clock = Clock(NOW)
    box = recorder(tmp_path, FakeKalshi(), clock, btc15m=False)
    box._watch(candidate(CANDIDATE))
    for number, at in enumerate((NOW, NOW + 4.9, NOW + 9.8)):
        clock.at = at
        job = box.trade_job = TradeJob(int(at) - 10, int(at), None, False)
        rows = [trade_row(f"p{number}", at - 1)] if number else []
        box._done_trades(Request("trades", "/markets/trades", [], {"job": job}),
                         fetched("trades", "/markets/trades", at, {"trades": rows, "cursor": ""}))
    copy = crash_copy(tmp_path)  # killed right after the third coverage row
    covered = [(record["from"], record["to"]) for record in records(copy, "trade_coverage")]
    kept = {row["trade_id"] for record in records(copy, "trades") for row in record["rows"]}
    assert covered
    for number, at in ((1, NOW + 4.9), (2, NOW + 9.8)):
        created = int(at - 1)
        if any(low <= created <= high for low, high in covered):
            assert f"p{number}" in kept, (covered, kept)
    box.close()


def test_p7_a_crash_never_keeps_a_book_call_whose_changed_book_it_lost(tmp_path: Path) -> None:
    """The replay re-dates the last written book for every "unchanged" ticker; that book must survive with the row."""
    clock = Clock(NOW)
    box = recorder(tmp_path, FakeKalshi(), clock, btc15m=False)
    box._watch(candidate(CANDIDATE))
    first, second = orderbook([("0.62", "5.00")], [("0.35", "10.00")]), orderbook([("0.63", "5.00")], [("0.35", "10.00")])
    for at, book in ((NOW, first), (NOW + 1, second), (NOW + 5.5, second)):
        clock.at = at
        box._done_books(Request("books", "/markets/orderbooks", [("tickers", CANDIDATE)], {"tickers": [CANDIDATE]}),
                        fetched("books", "/markets/orderbooks", at,
                                {"orderbooks": [{"ticker": CANDIDATE, "orderbook_fp": book}]}))
    copy = crash_copy(tmp_path)
    written = {record["received_at"] for record in records(copy, "books") if record["kind"] == "book"}
    calls = records(copy, "book_calls")
    assert calls and all(call["received_at"] in written for call in calls if call["changed"]), (calls, written)
    box.close()


def test_m1_the_engine_hook_sees_live_switches_from_the_env_file_the_bot_read(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, fake_clock: Any,
        http_client: Any) -> None:
    """M1: `nightcrawler --env-file bot.env run` with POLYDESK_MODE=live in bot.env started the recorder in a live bot."""
    from nightcrawler import engine
    from nightcrawler.config import LIVE_CONFIRM_PHRASE, load_settings

    monkeypatch.chdir(tmp_path)  # no ./.env: the bot read bot.env
    monkeypatch.setattr(os, "environ", {"KALSHI_RECORDER_ENABLED": "true"})
    started: list[RecorderSettings] = []
    monkeypatch.setattr(kalshi_recorder, "run_recorder", lambda settings, stop: started.append(settings))
    (tmp_path / "bot.env").write_text(
        f"DATA_DIR={tmp_path / 'data'}\nPOLYDESK_MODE=live\nPOLYDESK_LIVE_CONFIRM={LIVE_CONFIRM_PHRASE}\n"
        "POLYMARKET_US_KEY_ID=FAKE-not-read\nPOLYMARKET_US_SECRET_KEY=FAKE-not-read\nPOLYDESK_ENABLED=false\n"
        "TRENDDESK_ENABLED=false\nSPEEDDESK_ENABLED=false\nSKIPWATCH_ENABLED=false\nWEATHERWATCH_ENABLED=false\n")
    settings = load_settings(dotenv_path=tmp_path / "bot.env")
    assert settings.polydesk_mode == "live"
    with caplog.at_level(logging.WARNING, logger="nightcrawler.kalshi_recorder"):
        app = engine.build_app(settings, fake_clock, http=http_client)
        app.close()
    assert not started and not (tmp_path / "data" / "kalshi_recorder").exists()
    assert "live_trading_in_this_process" in caplog.text and "POLYDESK_MODE" in caplog.text
    assert "FAKE-not-read" not in caplog.text
    assert engine.live_mode_names(settings) == ["POLYDESK_MODE"]
    assert start_from_engine(tmp_path, threading.Event(), env={"KALSHI_RECORDER_ENABLED": "true"},
                             live=["TRADING_MODE"]) is None  # either source saying live is enough
