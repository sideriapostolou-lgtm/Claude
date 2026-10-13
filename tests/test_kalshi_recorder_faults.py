"""Faults the 2026-10-13 isolation review found (F1-F10, R9): no reply may halt the recorder or wedge a lane.

Every case runs against the scripted public venue in ``kalshi_recorder_fixtures``; nothing touches the network.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from kalshi_recorder_fixtures import (
    NOW,
    Clock,
    FakeKalshi,
    FakeResponse,
    event_row,
    iso,
)
from test_kalshi_recorder import CANDIDATE, recorder, records, run, venue

from nightcrawler import kalshi_recorder
from nightcrawler.kalshi_public import Fetched
from nightcrawler.kalshi_recorder import (
    PAGE_ATTEMPTS,
    SWEEP_QUERY_BYTES,
    TICKERS_PER_SWEEP,
    RecorderSettings,
    Watched,
    main,
    run_recorder,
    start_from_engine,
)
from nightcrawler.kalshi_recorder_store import iter_records


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
    assert box.chunk_size <= 10 and not box.sweep_queue
    halved = [record for record in records(tmp_path, "telemetry") if record["kind"] == "chunk_halved"]
    assert halved and all(record["status"] == 414 for record in halved)
    assert any(record["kind"] == "sweep" for record in records(tmp_path, "markets"))


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

