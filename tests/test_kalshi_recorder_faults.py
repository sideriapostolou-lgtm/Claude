"""Faults the 2026-10-13 isolation review found (F1-F10, R9): no reply may halt the recorder or wedge a lane.

Every case runs against the scripted public venue in ``kalshi_recorder_fixtures``; nothing touches the network.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
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

from nightcrawler import kalshi_recorder, kalshi_recorder_store
from nightcrawler.kalshi_familya_universe import OPEN_CATEGORIES
from nightcrawler.kalshi_public import Fetched
from nightcrawler.kalshi_recorder import (
    BTC15M,
    DISCOVERY_ABANDON_ITEMS,
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
    """F3: in_a_row was reset only by a success, so every pass after the first was abandoned on its first 429.

    Round 3: a pass waits only when DISCOVERY_ABANDON_ITEMS different items strike out with no reply in between,
    each after its own PAGE_ATTEMPTS. The next pass gives every item its own attempts again, and the items that
    were bad last pass abandon nothing, so a category list that keeps refusing no longer stops discovery: the event
    list and the series detail still admit the candidate.
    """
    clock, fake = Clock(NOW), venue()
    fake.routes["/series"] = lambda query: FakeResponse(429, {"error": "slow down"})
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 3000)
    box.close()
    abandoned = [record for record in gaps(tmp_path) if record["cause"] == "discovery_abandoned_429"]
    assert len(abandoned) == 1 and len(abandoned[0]["items"]) == DISCOVERY_ABANDON_ITEMS
    lists = [record["received_at"] for record in records(tmp_path, "requests") if record["path"] == "/series"]
    first = [at for at in lists if at <= abandoned[0]["to"]]
    assert len(first) == DISCOVERY_ABANDON_ITEMS * PAGE_ATTEMPTS  # every item its own attempts, then the pass waits
    assert len(lists) - len(first) == len(OPEN_CATEGORIES) * PAGE_ATTEMPTS  # the next pass: each category again
    assert any(record["kind"] == "discovery_summary" for record in records(tmp_path, "admissions"))
    assert CANDIDATE in box.watched


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


# --------------------------------------------------------------------------- rebreak 2026-10-13 (round 3)
def broken_series_venue(*names: str, failure: str = "500", detail: bool = False) -> FakeKalshi:
    """The candidate's venue plus series whose /markets (and, with ``detail``, /series/<name>) always fail."""
    fake = venue()
    for name in names:
        if not detail:  # listed in its category; with ``detail`` only an event names it, so its detail is asked
            fake.series[name] = {**fake.series["KXHIGHNY"], "ticker": name}
        fake.events = [*fake.events, event_row(f"{name}-26OCT15", name)]
    original = fake.route

    def route(path: str, query: dict[str, list[str]]) -> FakeResponse:
        if path in {f"/series/{name}" for name in names} or (
                path == "/markets" and query.get("series_ticker", [""])[0] in names):
            if failure == "connect_timeout":
                raise requests.exceptions.ConnectTimeout("scripted")
            return FakeResponse(500, {"error": "scripted"})
        return original(path, query)

    fake.route = route  # type: ignore[method-assign]
    return fake


def asked_for(fake: FakeKalshi, series: str) -> int:
    return sum(1 for call in fake.calls if call["path"] == f"/series/{series}"
               or call["query"].get("series_ticker") == [series])


@pytest.mark.parametrize("failure", ["500", "connect_timeout"])
def test_dw_one_series_failing_on_detail_and_markets_is_skipped_in_both_and_the_pass_admits(
        tmp_path: Path, failure: str) -> None:
    """Rebreak: the detail stage struck KXAAA out with in_a_row still 5, so its first /markets failure abandoned the
    pass (60 passes in 6 h, all abandoned, nothing ever admitted). The next item now gets its own attempts."""
    clock, fake = Clock(NOW), broken_series_venue("KXAAA", failure=failure, detail=True)
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 1500)
    box.close()
    assert CANDIDATE in box.watched
    assert not any(record["cause"].startswith("discovery_abandoned") for record in gaps(tmp_path))
    skipped = [(record["stage"], record["item"]) for record in gaps(tmp_path) if "_failed_" in record["cause"]]
    assert skipped == [("detail", "KXAAA"), ("markets", "KXAAA")]
    assert asked_for(fake, "KXAAA") == 2 * PAGE_ATTEMPTS
    assert any(record["kind"] == "discovery_summary" for record in records(tmp_path, "admissions"))


def test_dw_two_bad_series_side_by_side_each_get_their_own_attempts(tmp_path: Path) -> None:
    """Rebreak: KXBADA struck out, then KXBADB's first 500 abandoned the pass; KXBADB never got its own 5."""
    clock, fake = Clock(NOW), broken_series_venue("KXBADA", "KXBADB")
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 1500)
    box.close()
    assert CANDIDATE in box.watched
    assert asked_for(fake, "KXBADA") == asked_for(fake, "KXBADB") == PAGE_ATTEMPTS
    assert not any(record["cause"].startswith("discovery_abandoned") for record in gaps(tmp_path))


def test_dw_after_a_skip_one_429_on_the_next_item_does_not_abandon_the_pass(tmp_path: Path) -> None:
    clock, fake = Clock(NOW), broken_series_venue("KXBAD")
    original = fake.route
    blips = {"left": 1}

    def route(path: str, query: dict[str, list[str]]) -> FakeResponse:
        if path == "/markets" and query.get("series_ticker") == ["KXHIGHNY"] and blips["left"]:
            blips["left"] -= 1
            return FakeResponse(429, {"error": "slow down"})
        return original(path, query)

    fake.route = route  # type: ignore[method-assign]
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 1500)
    box.close()
    assert not blips["left"] and CANDIDATE in box.watched  # was abandoned (discovery_abandoned_429), admitted 426 s on
    assert not any(record["cause"].startswith("discovery_abandoned") for record in gaps(tmp_path))


def test_dw_three_bad_series_abandon_one_pass_then_the_next_skips_them_and_admits(tmp_path: Path) -> None:
    """Item after item failing is what a struggling venue looks like, so the first pass waits; the items that were
    bad then are one bad item each, not a struggling venue, so they never wedge the passes after it."""
    clock, fake = Clock(NOW), broken_series_venue("KXBADA", "KXBADB", "KXBADC")
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 3000)
    box.close()
    abandoned = [record for record in gaps(tmp_path) if record["cause"].startswith("discovery_abandoned")]
    assert len(abandoned) == 1 and abandoned[0]["items"] == ["KXBADA", "KXBADB", "KXBADC"]
    assert CANDIDATE in box.watched
    assert all(asked_for(fake, name) == 2 * PAGE_ATTEMPTS for name in ("KXBADA", "KXBADB", "KXBADC"))


def overflowing(fake: FakeKalshi, path: str) -> None:
    """Replace the string "__OVF__" with 1e400 (a JSON number that parses as infinity) in every reply on ``path``."""
    original = fake.route

    def route(where: str, query: dict[str, list[str]]) -> FakeResponse:
        response = original(where, query)
        if where == path:
            response._raw = response._raw.replace(b'"__OVF__"', b"1e400")
        return response

    fake.route = route  # type: ignore[method-assign]


def test_p6_an_overflowing_print_of_a_ticker_nobody_watches_never_fails_the_page(tmp_path: Path) -> None:
    """Rebreak r1: the blanket non-finite check failed the exchange-wide page and lost the watched print in it."""
    clock, fake = Clock(NOW), venue()
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 600)
    assert CANDIDATE in box.watched
    at = clock.at + 3
    fake.trades = [{**trade_row("keep-me", at)}, {"trade_id": "not-ours", "ticker": "KXNBAGAME-26OCT15LALBOS-LAL",
                                                 "created_time": iso(at), "count_fp": "1.00", "price": "__OVF__"}]
    overflowing(fake, "/markets/trades")
    run(box, clock, 800)
    box.close()
    kept = {row["trade_id"] for record in records(tmp_path, "trades") for row in record["rows"]}
    assert kept == {"keep-me"}
    assert not [record for record in gaps(tmp_path) if record["gap_lane"] == "trades"]


def test_p6_an_overflowing_watched_print_still_fails_its_page_and_is_never_stored(tmp_path: Path) -> None:
    clock, fake = Clock(NOW), venue()
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 600)
    fake.trades = [{**trade_row("bad", clock.at + 3), "count_fp": "__OVF__"}]
    overflowing(fake, "/markets/trades")
    run(box, clock, 600)
    box.close()
    assert not [row for record in records(tmp_path, "trades") for row in record["rows"]]
    errors = [record for record in records(tmp_path, "gaps") if record["kind"] == "handler_error"]
    assert errors and all(record["error"] == "Malformed" for record in errors)
    assert any(record.get("backfill") == "failed" for record in gaps(tmp_path))  # the window is a gap, not coverage


def test_p6_an_overflowing_number_in_an_event_outside_the_open_categories_hides_no_events_page(tmp_path: Path) -> None:
    """Rebreak r2: page 1 (one Sports event with exchange_index 1e400) failed 5 times; page 2 was never read."""
    clock, fake = Clock(NOW), venue()
    sports = event_row("KXNBA-26OCT15", "KXNBA", "Sports", exchange_index="__OVF__")

    def events(query: dict[str, list[str]]) -> FakeResponse:
        if query.get("cursor", [""])[0] == "page2":
            return FakeResponse(200, {"events": [event_row()], "cursor": ""})
        return FakeResponse(200, json.dumps({"events": [sports], "cursor": "page2"}).encode().replace(
            b'"__OVF__"', b"1e400"))

    fake.routes["/events"] = events
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 900)
    box.close()
    assert [call["query"].get("cursor", [""])[0] for call in fake.calls if call["path"] == "/events"] == ["", "page2"]
    assert CANDIDATE in box.watched


def test_p6_one_overflowing_unwatched_print_never_costs_a_backfill_its_coverage(tmp_path: Path) -> None:
    """Rebreak r7: a 2-hour exchange-wide backfill lost its coverage row and 2,600 of 3,600 watched prints."""
    clock, fake = Clock(NOW), venue()
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 600)
    high = int(clock.at) - 120
    low = high - 7200
    rows = [{**trade_row(f"w{at}", at)} for at in range(low, high, 2)]
    rows.append({"trade_id": "bad", "ticker": "KXNBAGAME-26OCT15LALBOS-LAL", "created_time": iso(low + 3600),
                 "count": "__OVF__"})
    rows.sort(key=lambda row: row["created_time"], reverse=True)

    def trades(query: dict[str, list[str]]) -> FakeResponse:
        lo, hi = int(query["min_ts"][0]), int(query["max_ts"][0])
        chosen = [row for row in rows if lo <= datetime.fromisoformat(row["created_time"]).timestamp() <= hi + 1]
        start = int(query.get("cursor", ["0"])[0] or 0)
        cursor = str(start + 1000) if start + 1000 < len(chosen) else ""
        return FakeResponse(200, json.dumps({"trades": chosen[start:start + 1000], "cursor": cursor}).encode().replace(
            b'"__OVF__"', b"1e400"))

    fake.routes["/markets/trades"] = trades
    box.backfill_jobs.append(TradeJob(low, high, None, True))
    run(box, clock, 1500)
    box.close()
    covered = [(record["from"], record["to"]) for record in records(tmp_path, "trade_coverage") if record["backfill"]]
    assert covered == [(low, high)]
    kept = {row["trade_id"] for record in records(tmp_path, "trades") if record["window"] == [low, high]
            for row in record["rows"]}
    assert len(kept) == len(rows) - 1


def test_p6_an_unreadable_book_waits_for_its_slow_retry_with_the_kxbtc15m_lane_on(tmp_path: Path) -> None:
    """Rebreak r3: with KXBTC15M on (the service default) spare slots asked the bad ticker on all 233 calls."""
    clock, fake = Clock(NOW), venue()
    good = [f"KXHIGHNY-26OCT15-T{index:02d}" for index in range(10)]
    bad, btc = "KXHIGHNY-26OCT15-T05X", "KXBTC15M-26OCT131845-45"
    book = json.dumps(orderbook([("0.62", "5.00")], [("0.35", "10.00")]))

    def books(query: dict[str, list[str]]) -> FakeResponse:
        parts = [f'{{"ticker":"{ticker}","orderbook_fp":{BAD_BOOKS["json_number"] if ticker == bad else book}}}'
                 for ticker in query.get("tickers", []) if ticker in (*good, bad, btc)]
        return FakeResponse(200, ('{"orderbooks":[' + ",".join(parts) + "]}").encode())

    fake.routes["/markets/orderbooks"] = books
    box = recorder(tmp_path, fake, clock)
    assert box.settings.btc15m
    box._watch(*(candidate(ticker) for ticker in [*good, bad]))
    box._watch(Watched(btc, "KXBTC15M-26OCT131845", BTC15M, "Crypto", "btc15m", NOW - 60, NOW + 840, "active", NOW))
    start = clock.at
    run(box, clock, 1200)
    box.close()
    span = clock.at - start
    asked = sum(1 for call in fake.calls if call["path"] == "/markets/orderbooks" and bad in call["query"]["tickers"])
    assert asked <= span / kalshi_recorder.SLOW_BOOK_S + 2
    assert len([record for record in gaps(tmp_path) if record["cause"] == "book_unreadable"]) == asked


def sweep_passes(tmp_path: Path, tickers: list[str], bad: str | None, passes: int,
                 burst: dict[str, bool] | None = None) -> tuple[Any, list[list[int]]]:
    clock, fake = Clock(NOW), venue()
    for ticker in tickers:
        fake.markets[ticker] = {**fake.markets[CANDIDATE], "ticker": ticker}
    if bad is not None:
        fake.markets[bad]["volume_fp"] = "__OVF__"
    overflowing(fake, "/markets")
    if burst is not None:
        original = fake.route

        def route(path: str, query: dict[str, list[str]]) -> FakeResponse:
            if path == "/markets" and "tickers" in query and burst["on"]:
                return FakeResponse(403, {"error": "challenge"})
            return original(path, query)

        fake.route = route  # type: ignore[method-assign]
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 600)  # discovery first, so it does not interleave
    box._watch(*(candidate(ticker) for ticker in tickers))
    out: list[list[int]] = []
    for number in range(passes):
        if burst is not None:
            burst["on"] = number == 0  # a 403 burst that outlasts the first pass, then is over
        before = len(fake.calls)
        box.next_sweep_at = clock.at
        box.next_settlement_at = clock.at + 10 ** 9
        for _ in range(400):
            run(box, clock, 100)
            if not box.sweep_queue:
                break
        assert not box.sweep_queue
        out.append([len(call["query"]["tickers"][0].split(",")) for call in fake.calls[before:]
                    if call["path"] == "/markets" and "tickers" in call["query"]])
    box.close()
    return box, out


def test_p5_a_bad_row_that_sorts_last_costs_later_passes_only_its_own_call(tmp_path: Path) -> None:
    """Rebreak r4/r5: the halving ended at the right edge, so every later pass ran at 2 tickers per call (156 calls
    for 300 candidates). Every pass now starts at full size and the known bad row is asked alone, last."""
    tickers = [f"KXHIGHNY-26OCT15-T{index:03d}" for index in range(298)] + ["KXHIGHNY-26OCT15-Z99"]
    box, passes = sweep_passes(tmp_path, tickers, "KXHIGHNY-26OCT15-Z99", 3)
    candidates = sum(1 for item in box.watched.values() if item.kind == "candidate")
    assert candidates == 300 and len(passes[0]) <= 2 * 9 + PAGE_ATTEMPTS  # found by halving, once
    assert any(record["cause"] == "market_row_unreadable" and record["tickers"] == ["KXHIGHNY-26OCT15-Z99"]
               for record in gaps(tmp_path))  # discovery refused that row alone and admitted the candidate
    readable = sorted(item.ticker for item in box.watched.values() if item.ticker != "KXHIGHNY-26OCT15-Z99")
    full = [len(chunk) for chunk in kalshi_recorder.Recorder._chunks(readable)]  # 300 per call and the URL budget
    assert len(full) == 2
    for later in passes[1:]:
        assert later == full + [1] * PAGE_ATTEMPTS  # full-size calls, then the bad row alone (was 156 calls)
    swept = {row["ticker"] for record in records(tmp_path, "markets") if record["kind"] == "sweep"
             for row in record["rows"]}
    assert "KXHIGHNY-26OCT15-Z99" not in swept and len(swept) == candidates - 1


def test_p5_a_403_burst_that_outlasts_a_pass_leaves_the_next_pass_at_full_size(tmp_path: Path) -> None:
    """Rebreak r6: the burst left chunk_size at 1, and the whole next pass ran 300 one-ticker calls."""
    tickers = [f"KXHIGHNY-26OCT15-T{index:03d}" for index in range(40)]
    box, passes = sweep_passes(tmp_path, tickers, None, 2, burst={"on": True})
    assert len(passes[0]) > 40 and min(passes[0]) == 1  # the burst halved the first pass down to single tickers
    assert passes[1] == [41] and not box.bad_rows["sweep"]  # a 403 is the venue's challenge, not a bad row


HookCallback = Any


class HookClock(Clock):
    """A fake clock whose sleeps (the limiter's waits) run hooks: a crash copy taken in the middle of a hold."""

    def __init__(self, at: float) -> None:
        super().__init__(at)
        self.hooks: list[HookCallback] = []
        self.offset = 0.0

    def wall(self) -> float:
        return self.at + self.offset

    def sleep(self, seconds: float) -> None:
        super().sleep(seconds)
        for hook in list(self.hooks):
            hook(self.at)


ALL_LANES = ("gaps", "requests", "books", "book_calls", "trades", "trade_coverage", "admissions", "discovery",
             "markets", "telemetry", "fees", "other", "settlement")


def lost_since(tmp_path: Path, copy: Path, at: float) -> list[dict[str, Any]]:
    """Records the recorder wrote at least 2 x FLUSH_EVERY_S before ``at`` that a crash copy taken at ``at`` lacks."""
    kept = {record["seq"] for record in records(copy, *ALL_LANES)}
    return [record for record in records(tmp_path, *ALL_LANES)
            if record["at"] <= at - 2 * kalshi_recorder_store.FLUSH_EVERY_S and record["seq"] not in kept]


def test_f2_a_retry_after_hold_hands_every_lane_to_the_os_before_it_waits(tmp_path: Path) -> None:
    """Rebreak: the 429's own request row and gap rows sat in Python's buffers for the whole 600 s hold."""
    clock, fake = HookClock(NOW), venue()
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 300)
    state: dict[str, Any] = {"armed": True, "hold_at": None, "copies": {}}
    original = fake.route

    def route(path: str, query: dict[str, list[str]]) -> FakeResponse:
        if path == "/markets/orderbooks" and state["armed"]:
            state["armed"], state["hold_at"] = False, clock.at
            return FakeResponse(429, {"error": "slow down"}, {"Retry-After": "600"})
        return original(path, query)

    def hook(at: float) -> None:
        for after in (30, 590):
            if state["hold_at"] is not None and after not in state["copies"] and at >= state["hold_at"] + after:
                state["copies"][after] = (at, crash_copy(tmp_path, f"hold{after}"))

    fake.route = route  # type: ignore[method-assign]
    clock.hooks.append(hook)
    run(box, clock, 200)
    box.close()
    assert len(state["copies"]) == 2
    for at, copy in state["copies"].values():
        assert not lost_since(tmp_path, copy, at)
        assert any(record["status"] == 429 for record in records(copy, "requests"))
        assert any(record["kind"] == "gap" and record["cause"] == "retry_after_hold" for record in records(copy, "gaps"))


def test_f2_a_429_storm_ending_in_a_retry_after_keeps_its_gap_rows_through_the_hold(tmp_path: Path) -> None:
    clock, fake = HookClock(NOW), venue()
    calls: dict[str, Any] = {"n": 0, "hold_at": None}
    original = fake.route

    def route(path: str, query: dict[str, list[str]]) -> FakeResponse:
        if path == "/series":
            calls["n"] += 1
            if calls["n"] < 5:
                return FakeResponse(429, {"error": "slow down"})
            if calls["n"] == 5:
                calls["hold_at"] = clock.at
                return FakeResponse(429, {"error": "slow down"}, {"Retry-After": "600"})
        return original(path, query)

    copies: dict[int, tuple[float, Path]] = {}

    def hook(at: float) -> None:
        if calls["hold_at"] is not None and not copies and at >= calls["hold_at"] + 590:
            copies[590] = (at, crash_copy(tmp_path, "storm"))

    fake.route = route  # type: ignore[method-assign]
    box = recorder(tmp_path, fake, clock, btc15m=False)
    clock.hooks.append(hook)
    run(box, clock, 300)
    box.close()
    at, copy = copies[590]
    assert not lost_since(tmp_path, copy, at)
    assert any(record.get("cause") == "discovery_series_failed_429" for record in records(copy, "gaps"))


def test_f2_a_wall_clock_step_back_writes_one_gap_and_neither_stalls_nor_holds_back_records(tmp_path: Path) -> None:
    """Rebreak: after a 20-minute step back nothing was flushed for 10 minutes (2,361 clock_moved_backwards rows, one
    per step, all lost), and every wall-clock schedule stalled its lane until the clock caught up."""
    clock, fake = HookClock(NOW), venue()
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 300)
    books_before = sum(1 for call in fake.calls if call["path"] == "/markets/orderbooks")
    clock.offset = -20 * 60
    stepped = clock.wall()
    cutoff = None
    while clock.wall() < stepped + 10 * 60:
        if cutoff is None and clock.wall() >= stepped + 10 * 60 - 2 * kalshi_recorder_store.FLUSH_EVERY_S:
            cutoff = box.store.next_seq  # every record before this one is at least 10 s old at the copy
        if not box.step():
            clock.sleep(0.25)
    copy = crash_copy(tmp_path, "stepped")
    box.close()
    kept = {record["seq"] for record in records(copy, *ALL_LANES)}
    assert cutoff is not None
    assert not [record for record in records(tmp_path, *ALL_LANES) if record["seq"] < cutoff and record["seq"] not in kept]
    steps_back = [record for record in gaps(tmp_path) if record["cause"] == "clock_moved_backwards"]
    assert len(steps_back) == 1 and steps_back[0]["seconds"] >= 1199
    books_after = sum(1 for call in fake.calls if call["path"] == "/markets/orderbooks") - books_before
    assert books_after >= 25  # the 20 s cadence of a favourite in the band, as before the step (was 0: stalled)


def test_f2_the_flusher_thread_hands_rows_to_the_os_while_a_get_hangs(tmp_path: Path,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """Rebreak: flush_due ran only between GETs, so a GET hanging to requests' 20 s timeout kept the rows written
    just before it in memory (6 of 30 hang positions lost a requests row 20.4 s old)."""
    monkeypatch.setattr(kalshi_recorder, "FLUSH_POLL_S", 0.05)
    clock, fake = Clock(NOW), venue()
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 300)
    box.emit("telemetry", "probe", {"n": 1})  # a new segment's first record reaches the OS at once ...
    box.emit("telemetry", "probe", {"n": 2})  # ... this one, just before the GET that hangs, only in Python's buffers
    seen: dict[str, Any] = {}

    class Hanging:
        def get(self, url: str, params: Any = None, headers: Any = None, **kwargs: Any) -> FakeResponse:
            if not seen:
                clock.at += 19.9  # the socket read blocks ...
                time.sleep(0.5)  # ... while the flusher thread runs
                seen["copy"] = crash_copy(tmp_path, "hang")  # ... and the host dies here
                raise requests.exceptions.ReadTimeout("scripted 20 s read timeout")
            return fake("GET", url, params=params, headers=headers, **kwargs)

    box.client._session = Hanging()
    done = threading.Event()
    flusher = box.start_flusher(done)
    try:
        while not seen:
            run(box, clock, 1)
    finally:
        done.set()
        flusher.join(5)
    box.close()
    assert [record["n"] for record in records(seen["copy"], "telemetry") if record["kind"] == "probe"] == [1, 2]
    assert not lost_since(tmp_path, seen["copy"], clock.at)


HANGING_CHILD = r"""
import json, os, sys, time
sys.path[:0] = sys.argv[3:]
from kalshi_recorder_fixtures import FakeKalshi, event_row, market_row, orderbook, series_row
from nightcrawler import kalshi_recorder, kalshi_recorder_store
from nightcrawler.kalshi_public import PublicKalshi

log = os.open(sys.argv[2], os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)  # kernel-side: survives the SIGKILL
append = kalshi_recorder_store.RecorderStore.append

def logged(self, lane, kind, payload, at=None):
    seq = append(self, lane, kind, payload, at)
    if seq is not None:
        os.write(log, (json.dumps({"seq": seq, "lane": lane, "kind": kind}) + "\n").encode())
    return seq

kalshi_recorder_store.RecorderStore.append = logged
fake = FakeKalshi()
fake.series = {"KXHIGHNY": series_row()}
fake.events = [event_row()]
fake.markets = {"KXHIGHNY-26OCT15-T76": market_row()}
fake.books = {"KXHIGHNY-26OCT15-T76": orderbook([("0.30", "12.00")], [("0.67", "40.00")])}
calls = []

class Session:
    def get(self, url, params=None, headers=None, **kwargs):
        calls.append(url)
        if len(calls) == 4:  # this GET hangs (a socket that never answers)
            os.write(log, b'{"event": "hang"}\n')
            time.sleep(600)
        return fake("GET", url, params=params, headers=headers, **kwargs)

kalshi_recorder.PublicKalshi = lambda limiter, wall: PublicKalshi(limiter, session=Session(), wall=wall)
raise SystemExit(kalshi_recorder.main(["run", "--data-dir", sys.argv[1]]))
"""


def test_f2_a_sigkill_while_a_get_hangs_keeps_every_row_written_before_it(tmp_path: Path) -> None:
    """A real process and a real SIGKILL (an OOM kill, a host failure, a stop with draining 0 s): every record
    appended before the GET that hangs reaches the OS while it hangs, through the flusher thread."""
    source = Path(__file__).resolve().parents[1]
    log = tmp_path / "appends.jsonl"
    child = subprocess.Popen([sys.executable, "-c", HANGING_CHILD, str(tmp_path / "data"), str(log),
                              str(source / "src"), str(source / "tests")], cwd=tmp_path,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             env={"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)})
    try:
        deadline = time.time() + 60
        while time.time() < deadline and not (log.exists() and b'"hang"' in log.read_bytes()):
            time.sleep(0.1)
        assert log.exists() and b'"hang"' in log.read_bytes(), "the child never reached the hanging GET"
        time.sleep(kalshi_recorder_store.FLUSH_EVERY_S + 2 * kalshi_recorder.FLUSH_POLL_S + 0.5)
    finally:
        child.kill()
        child.wait(30)
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    before = [row["seq"] for row in rows[:next(index for index, row in enumerate(rows) if "event" in row)]]
    root = tmp_path / "data" / "kalshi_recorder"
    RecorderStore(root, max_bytes=256 * 1024 * 1024, min_free_bytes=0).close()  # what the restart recovers
    kept = {record["seq"] for record in iter_records(root, frozenset(kalshi_recorder_store.LANE_CLASS))}
    assert before and set(before) <= kept, sorted(set(before) - kept)


def test_p7_the_saved_state_lists_a_ticker_before_its_watch_row_is_written(tmp_path: Path) -> None:
    """Rebreak: recorder_state.json was saved once a minute, so a kill within a minute of an admission restarted
    without the ticker while its "start" row was in the tape; the new session dropped its prints."""
    clock, fake = Clock(NOW), venue()
    box = recorder(tmp_path, fake, clock, btc15m=False)
    while CANDIDATE not in box.watched:
        if not box.step():
            clock.sleep(0.25)
    saved = json.loads((tmp_path / "kalshi_recorder" / "recorder_state.json").read_text())
    assert CANDIDATE in {row["ticker"] for row in saved["watched"]}
    box.close()


def test_p7_a_restart_closes_the_watch_of_a_ticker_it_does_not_resume(tmp_path: Path) -> None:
    """Rebreak: with a saved state that predates an admission (as before), the replay kept the ticker's watch open
    across the restart, and the new session's exchange-wide coverage vouched for prints it never kept."""
    from nightcrawler.kalshi_familya import load_coverage

    clock, fake = Clock(NOW), venue()
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 120)
    assert CANDIDATE in box.watched
    stale = json.loads((tmp_path / "kalshi_recorder" / "recorder_state.json").read_text())
    stale["watched"] = []  # the state as it was before the admission
    copy = crash_copy(tmp_path, "killed")  # SIGKILL now: the tape has the "start" row
    (copy / "kalshi_recorder" / "recorder_state.json").write_text(json.dumps(stale))
    box.close()
    clock.at += 60
    after = venue()
    after.trades = [trade_row(f"after-{index}", clock.at + index) for index in range(1, 30)]
    again = recorder(copy, after, clock, btc15m=False)  # resumes nothing; its discovery re-admits the ticker later
    run(again, clock, 120)
    again.close()
    started = next(record for record in records(copy, "gaps") if record["kind"] == "session_started"
                   and record["session"] == again.session)
    kept = {row["trade_id"] for record in records(copy, "trades") for row in record["rows"]}
    coverage = load_coverage(copy / "kalshi_recorder", NOW - 3600, clock.at + 60)
    assert coverage.exchange.covers(int(clock.at - 40), int(clock.at - 5))  # the new session did cover the tape
    for row in after.trades:
        created = datetime.fromisoformat(row["created_time"]).timestamp()
        if created < clock.at - 5:
            assert row["trade_id"] in kept or not coverage.tape(CANDIDATE, created, created), row["trade_id"]
    # Not watched between the new session's first vouched-for print and its restart: closed where its tape begins.
    assert not coverage.watched[CANDIDATE].covers(started["keeps_prints_from"] + 1, started["at"])


def test_m1_the_in_bot_recorder_refuses_while_the_bot_holds_kalshi_account_keys(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Rebreak: a bot restarted on paper after a live Kalshi run keeps a real Kalshi account client (it cancels the
    live run's resting order in recovery), yet live_mode_names saw nothing and the recorder started in it."""
    import asyncio

    from test_speeddesk_live import FIVE_DOLLAR_CAPS, TICKER, FakeAccount

    from nightcrawler import engine
    from nightcrawler.clock import FakeClock
    from nightcrawler.config import Secret, Settings, load_settings
    from nightcrawler.speeddesk_live import KalshiLiveDesk, LiveSnapshot
    from nightcrawler.speeddesk_model import Book, Level, Window

    data, clock = tmp_path / "data", FakeClock()
    live_dir, account = data / "speeddesk" / "kalshi_live", FakeAccount(clock)
    window = Window(TICKER, clock.now() - 10, clock.now() + 890, start_price=80000, venue_start_price=80000,
                    venue="kalshi", taker_coefficient=.07, maker_coefficient=0, min_trade_qty=.01, fee_rounding="kalshi")
    books = {(TICKER, side): Book(TICKER, side, (Level(.3, 2),), (Level(.4 if side == "up" else .6, 10),),
                                 clock.now(), "book", source="rest", requested_at=clock.now()) for side in ("up", "down")}
    snapshot = LiveSnapshot((window,), books, 80000, clock.now(), .001, frozenset({TICKER}))
    live = Settings(data_dir=data, speeddesk_kalshi_mode="live", speeddesk_kalshi_live_confirm=Secret("yes"),
                    kalshi_key_id=Secret("FAKE-id"), kalshi_private_key=Secret("FAKE-key"), **FIVE_DOLLAR_CAPS)
    desk = KalshiLiveDesk(live, live_dir, lambda: snapshot, clock=clock.now, client_factory=lambda: account,
                          direct_member_verified=True)
    desk.on_windows([window])
    desk.on_tick(80000, clock.now(), clock.now())
    for item in books.values():
        desk.on_book(item)
    asyncio.run(desk.step())
    desk.close()
    assert [order["status"] for order in account.orders] == ["resting"]  # yesterday's live run left a real bid
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(os, "environ", {"DATA_DIR": str(data), "SPEEDDESK_KALSHI_MODE": "paper",
                                        "KALSHI_KEY_ID": "FAKE-id-not-read", "KALSHI_PRIVATE_KEY": "FAKE-key-not-read",
                                        "SPEEDDESK_KALSHI_WINDOW_USD": "5", "SPEEDDESK_KALSHI_OPEN_USD": "10",
                                        "KALSHI_RECORDER_ENABLED": "true"})
    settings = load_settings()  # the owner turned real money off; the keys stay for the companion's recovery
    started: list[Any] = []
    monkeypatch.setattr(kalshi_recorder, "run_recorder", lambda settings, stop: started.append(settings))
    assert engine.live_mode_names(settings) == []
    assert engine.kalshi_account_names(settings) == ["KALSHI_KEY_ID", "KALSHI_PRIVATE_KEY"]
    with caplog.at_level(logging.WARNING, logger="nightcrawler.kalshi_recorder"):
        thread = start_from_engine(settings.data_dir, threading.Event(), live=engine.live_mode_names(settings),
                                   account=engine.kalshi_account_names(settings))  # exactly as engine.py calls it
        assert start_from_engine(settings.data_dir, threading.Event(), env={"KALSHI_RECORDER_ENABLED": "true"},
                                 account=engine.kalshi_account_names(settings)) is None  # the Settings alone suffice
    assert thread is None and not started
    assert "kalshi_account_keys_in_this_process" in caplog.text and "not-read" not in caplog.text
    restored = KalshiLiveDesk(settings, live_dir, lambda: snapshot, clock=clock.now, client_factory=lambda: account)
    try:
        asyncio.run(restored.step())
        assert account.cancels == ["order-1"]  # the companion does hold a real client here: the refusal is needed
    finally:
        restored.close()


def test_m1_build_app_with_kalshi_keys_on_paper_does_not_start_the_recorder(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, fake_clock: Any,
        http_client: Any) -> None:
    from nightcrawler import engine
    from nightcrawler.config import load_settings

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(os, "environ", {"KALSHI_RECORDER_ENABLED": "true"})
    started: list[RecorderSettings] = []
    monkeypatch.setattr(kalshi_recorder, "run_recorder", lambda settings, stop: started.append(settings))
    (tmp_path / "bot.env").write_text(
        f"DATA_DIR={tmp_path / 'data'}\nSPEEDDESK_KALSHI_MODE=paper\nKALSHI_KEY_ID=FAKE-not-read\n"
        "KALSHI_PRIVATE_KEY=FAKE-not-read\nPOLYDESK_ENABLED=false\nTRENDDESK_ENABLED=false\nSPEEDDESK_ENABLED=false\n"
        "SKIPWATCH_ENABLED=false\nWEATHERWATCH_ENABLED=false\n")
    settings = load_settings(dotenv_path=tmp_path / "bot.env")
    with caplog.at_level(logging.WARNING, logger="nightcrawler.kalshi_recorder"):
        app = engine.build_app(settings, fake_clock, http=http_client)
        app.close()
    assert not started and not (tmp_path / "data" / "kalshi_recorder").exists()
    assert "kalshi_account_keys_in_this_process" in caplog.text and "FAKE-not-read" not in caplog.text


def test_p4_the_recorder_writes_the_freeze_hash_it_was_given_at_session_start(tmp_path: Path) -> None:
    digest = "ab" * 32
    clock = Clock(NOW)
    box = recorder(tmp_path, venue(), clock, btc15m=False, freeze_sha256=digest)
    box.close()
    rows = [record for record in records(tmp_path, "telemetry") if record["kind"] == "freeze_witness"]
    assert [(row["sha256"], row["at"]) for row in rows] == [(digest, NOW)]
    with pytest.raises(kalshi_recorder.ConfigError, match="FREEZE_SHA256"):
        RecorderSettings.from_env({"KALSHI_RECORDER_FREEZE_SHA256": "not-a-hash"})
