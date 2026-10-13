"""The public Kalshi recorder: lanes, gaps, 429s, coverage manifests, restarts and the OFF-by-default hook."""

from __future__ import annotations

import ast
import json
import logging
import threading
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any, Self

import pytest
from kalshi_recorder_fixtures import (
    NOW,
    Clock,
    FakeKalshi,
    FakeResponse,
    event_row,
    iso,
    market_row,
    orderbook,
    sample,
    series_row,
)

from nightcrawler.config import ConfigError
from nightcrawler.kalshi_public import PublicKalshi, RateLimiter
from nightcrawler.kalshi_recorder import (
    PAGE_ATTEMPTS,
    Recorder,
    RecorderSettings,
    SpotTicks,
    Watched,
    coinbase_trades,
    favourite_mid,
    kraken_trades,
    main,
    start_from_engine,
)
from nightcrawler.kalshi_recorder_store import LEVEL_PAUSED, iter_records
from nightcrawler.speeddesk_kalshi import parse_books, parse_window

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = "KXHIGHNY-26OCT15-T76"


class Session:
    def __init__(self, fake: FakeKalshi) -> None:
        self.fake = fake

    def get(self, url: str, params: Any = None, headers: Any = None, **kwargs: Any) -> FakeResponse:
        return self.fake("GET", url, params=params, headers=headers, **kwargs)


def recorder(tmp_path: Path, fake: FakeKalshi, clock: Clock, **settings: Any) -> Recorder:
    client = PublicKalshi(RateLimiter(2.0, clock=clock.mono, sleep=clock.sleep), session=Session(fake),
                          wall=clock.wall, mono=clock.mono)
    return Recorder(RecorderSettings(data_dir=tmp_path, **settings), client=client, wall=clock.wall)


def run(box: Recorder, clock: Clock, steps: int) -> None:
    for _ in range(steps):
        if not box.step():
            clock.sleep(0.25)


def venue(**extra_markets: dict[str, Any]) -> FakeKalshi:
    fake = FakeKalshi()
    fake.series = {"KXHIGHNY": series_row()}
    fake.events = [event_row(), event_row("KXNBA-26OCT15", "KXNBA", "Sports")]
    fake.markets = {CANDIDATE: market_row(), **extra_markets}
    fake.books = {CANDIDATE: orderbook([("0.30", "12.00"), ("0.29", "5.00")], [("0.67", "40.00")])}
    return fake


def records(tmp_path: Path, *lanes: str) -> list[dict[str, Any]]:
    return list(iter_records(tmp_path / "kalshi_recorder", frozenset(lanes)))


# --------------------------------------------------------------------------- settings and the engine hook
def test_settings_defaults_and_validation() -> None:
    settings = RecorderSettings()
    assert (settings.enabled, settings.max_storage_mb, settings.rate_per_s, settings.storage_policy,
            settings.btc15m, settings.spot_ticks) == (False, 2048, 1.5, "protect", True, False)
    loaded = RecorderSettings.from_env({"DATA_DIR": "/tmp/x", "KALSHI_RECORDER_RATE_PER_S": "1.2",
                                        "KALSHI_RECORDER_BTC15M": "off", "KALSHI_RECORDER_MAX_STORAGE_MB": "4608"})
    assert (loaded.data_dir, loaded.rate_per_s, loaded.btc15m, loaded.max_storage_mb) == (Path("/tmp/x"), 1.2, False, 4608)
    assert loaded.root == Path("/tmp/x/kalshi_recorder")
    for env, words in ((({"KALSHI_RECORDER_RATE_PER_S": "2.5"}), "RATE_PER_S"),
                       ({"KALSHI_RECORDER_STORAGE_POLICY": "delete"}, "STORAGE_POLICY"),
                       ({"KALSHI_RECORDER_RELEASE_BEFORE": "soon"}, "RELEASE_BEFORE"),
                       ({"KALSHI_RECORDER_ENABLED": "maybe"}, "ENABLED"),
                       ({"KALSHI_RECORDER_MAX_STORAGE_MB": "nan"}, "MAX_STORAGE_MB")):
        with pytest.raises(ConfigError, match=words):
            RecorderSettings.from_env(env)


def test_host_label_says_workspace_or_railway() -> None:
    assert RecorderSettings().host({}) == "workspace"
    assert RecorderSettings().host({"RAILWAY_SERVICE_ID": "x"}) == "railway"
    assert RecorderSettings(host_label="railway").host({}) == "railway"


def test_engine_hook_is_off_by_default(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    stop = threading.Event()
    assert start_from_engine(tmp_path, stop, env={}) is None
    assert start_from_engine(tmp_path, stop, env={"KALSHI_RECORDER_ENABLED": "false"}) is None
    with caplog.at_level(logging.WARNING, logger="nightcrawler.kalshi_recorder"):
        assert start_from_engine(tmp_path, stop, env={"KALSHI_RECORDER_ENABLED": "maybe"}) is None
    assert "unreadable" in caplog.text
    assert not (tmp_path / "kalshi_recorder").exists()  # nothing was even created


def test_engine_hook_when_switched_on_runs_in_its_own_thread(tmp_path: Path) -> None:
    stop = threading.Event()
    stop.set()  # stops at once, before any request
    thread = start_from_engine(tmp_path, stop, env={"KALSHI_RECORDER_ENABLED": "true"})
    assert thread is not None and thread.daemon and thread.name == "kalshi-recorder"
    thread.join(10)
    assert not thread.is_alive()
    assert (tmp_path / "kalshi_recorder" / "recorder_state.json").exists()


def test_engine_calls_the_hook_inside_a_guard_and_env_example_keeps_it_off() -> None:
    tree = ast.parse((ROOT / "src" / "nightcrawler" / "engine.py").read_text(encoding="utf-8"))
    guarded = [node for node in ast.walk(tree) if isinstance(node, ast.Try)
               and any(isinstance(call, ast.Call) and getattr(call.func, "id", None) == "start_from_engine"
                       for call in ast.walk(node))]
    assert len(guarded) == 1 and guarded[0].handlers
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "KALSHI_RECORDER_ENABLED=false" in example


# --------------------------------------------------------------------------- discovery and admissions
def test_discovery_logs_every_admission_and_exclusion_with_its_reason(tmp_path: Path) -> None:
    clock = Clock(NOW)
    fake = venue(**{"KXHIGHNY-26OCT15-B70": market_row("KXHIGHNY-26OCT15-B70", market_type="scalar"),
                    "KXHIGHNY-26OCT15-T80": market_row("KXHIGHNY-26OCT15-T80", open_offset=-2 * 3600,
                                                       close_offset=20 * 3600)})
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 60)
    box.close()
    admissions = [row for record in records(tmp_path, "admissions") if record["kind"] == "admissions"
                  for row in record["changed"]]
    reasons = {row["ticker"]: (row["admitted"], row["rule"], row["reason"]) for row in admissions}
    assert reasons[CANDIDATE] == (True, None, None)
    assert reasons["KXHIGHNY-26OCT15-B70"] == (False, "U2", "non_binary")
    assert reasons["KXHIGHNY-26OCT15-T80"] == (False, "U4", "duration_lt_24h")
    summary = next(record for record in records(tmp_path, "admissions") if record["kind"] == "discovery_summary")
    assert summary["other_category_events"] == {"Sports": 1}
    assert summary["counts"]["Climate and Weather|admitted"] == 1
    page = next(record for record in records(tmp_path, "discovery") if record["kind"] == "events_page")
    assert [row["event_ticker"] for row in page["rows"]] == ["KXHIGHNY-26OCT15"]  # blocked categories not kept
    watch = [record for record in records(tmp_path, "admissions") if record["kind"] == "watch"]
    assert watch[0]["tickers"] == [CANDIDATE] and watch[0]["action"] == "start"
    paths = {call["path"] for call in fake.calls}
    assert "/events/fee_changes" in paths and "/series/fee_changes" in paths
    fees = [record for record in records(tmp_path, "fees") if record["kind"] == "event_fee_changes"]
    assert fees and fees[0]["event_ticker"] == "KXHIGHNY-26OCT15"


# --------------------------------------------------------------------------- books
def test_batch_books_write_raw_changes_and_list_unchanged_books(tmp_path: Path) -> None:
    clock = Clock(NOW)
    fake = venue()
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 60)
    first = fake.books[CANDIDATE]
    run(box, clock, 200)  # unchanged for a while
    fake.books[CANDIDATE] = orderbook([("0.31", "3.00")], [("0.67", "40.00")])
    run(box, clock, 200)
    box.close()
    books = [record for record in records(tmp_path, "books") if record["ticker"] == CANDIDATE]
    assert [record["orderbook_fp"] for record in books] == [first, fake.books[CANDIDATE]]
    assert all(record["requested_at"] <= record["received_at"] for record in books)
    calls = records(tmp_path, "book_calls")
    assert any(CANDIDATE in record["unchanged"] for record in calls)
    assert all(record["seq"] > 0 for record in calls)


def test_favourite_mid_uses_the_no_bid_for_the_yes_ask() -> None:
    assert str(favourite_mid(orderbook([("0.16", "5")], [("0.83", "9")]))) == "0.835"
    assert favourite_mid(orderbook([("0.16", "5")], [])) is None


def test_real_saved_kxbtc15m_books_are_recorded_raw_and_replay_with_the_arena_parsers(tmp_path: Path) -> None:
    meta = sample("KXBTC15M-metadata.json")
    btc = meta["data"]["markets"][0]
    rounds = [sample(f"KXBTC15M-round{index}.json") for index in (1, 2, 3)]
    clock = Clock(datetime.fromisoformat(rounds[0]["request_start"]).timestamp())
    fake = FakeKalshi()
    btc_series = {**series_row("KXBTC15M", "Crypto"), "frequency": "fifteen_min"}
    fake.series = {"KXBTC15M": btc_series}
    fake.markets = {btc["ticker"]: btc}
    fake.books = {btc["ticker"]: rounds[0]["data"]["orderbook_fp"]}
    box = recorder(tmp_path, fake, clock)
    run(box, clock, 40)
    for item in rounds[1:]:
        fake.books[btc["ticker"]] = item["data"]["orderbook_fp"]
        run(box, clock, 6)
    box.close()
    recorded = [record for record in records(tmp_path, "books_btc15m") if record["ticker"] == btc["ticker"]]
    assert [record["orderbook_fp"] for record in recorded] == [item["data"]["orderbook_fp"] for item in rounds]
    for record in recorded:
        books = parse_books({"orderbook_fp": record["orderbook_fp"]}, record["ticker"], record["received_at"])
        assert len(books) == 2 and books[0].bids and books[0].asks
        assert books[0].bids[0].price + books[1].bids[0].price < 1
    rows = [row for record in records(tmp_path, "btc15m_meta") if record["kind"] == "markets" for row in record["rows"]]
    series = next(record["series"] for record in records(tmp_path, "btc15m_meta") if record["kind"] == "series")
    window = parse_window(rows[0], series, clock.at - 60)
    assert window is not None and window.slug == btc["ticker"] and window.taker_coefficient == pytest.approx(0.07)


# --------------------------------------------------------------------------- trades
def trade(ticker: str, at: float, trade_id: str, count: str = "2.00") -> dict[str, Any]:
    return {"trade_id": trade_id, "ticker": ticker, "created_time": iso(at).replace("Z", ".250000Z"),
            "yes_price_dollars": "0.3000", "no_price_dollars": "0.7000", "count_fp": count,
            "taker_outcome_side": "no", "taker_book_side": "ask", "taker_side": "no", "is_block_trade": False}


def test_trades_keep_watched_tickers_dedupe_overlap_and_flag_conflicts(tmp_path: Path) -> None:
    clock = Clock(NOW)
    fake = venue()
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 60)  # discovery: the candidate is watched now
    fake.trades = [trade(CANDIDATE, clock.at - 1, "t1"), trade("KXOTHER-1", clock.at - 1, "t2"),
                   trade(CANDIDATE, clock.at - 1, "t1", count="9.00")]  # the last is a conflicting copy
    run(box, clock, 40)
    box.close()
    kept = [row for record in records(tmp_path, "trades") for row in record["rows"]]
    assert [row["trade_id"] for row in kept] == ["t1"]  # once, despite overlapping polls; t2 is not watched
    conflicts = [record for record in records(tmp_path, "gaps") if record["kind"] == "trade_conflict"]
    assert conflicts and conflicts[0]["row"]["count_fp"] == "9.00"
    coverage = records(tmp_path, "trade_coverage")
    assert coverage and all(row["scope"] == "exchange" and row["from"] <= row["to"] for row in coverage)
    spans = sorted((row["from"], row["to"]) for row in coverage)
    assert all(later[0] <= earlier[1] for earlier, later in pairwise(spans))  # overlapping polls


def fake_time(row: dict[str, Any]) -> float:
    return datetime.fromisoformat(row["created_time"]).timestamp()


def test_429s_back_off_slow_everyone_and_failed_windows_are_backfilled_not_invented(tmp_path: Path) -> None:
    clock = Clock(NOW)
    fake = venue()
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 60)
    fake.fail["/markets/trades"] = [429] * PAGE_ATTEMPTS
    run(box, clock, 300)
    box.close()
    lane = box.lanes["trades"]
    assert lane.in_a_row == 0  # recovered
    gaps = [record for record in records(tmp_path, "gaps") if record["kind"] == "gap"]
    assert any(record["cause"].startswith("trade_page_failed_429") and record["backfill"] == "queued" for record in gaps)
    backfills = [row for row in records(tmp_path, "trade_coverage") if row["backfill"]]
    assert backfills, "the failed window was re-read from the public tape"
    requests_log = records(tmp_path, "requests")
    assert sum(1 for row in requests_log if row["status"] == 429) == PAGE_ATTEMPTS
    retries = [row["requested_at"] for row in requests_log if row["path"] == "/markets/trades"]
    assert retries == sorted(retries)


# --------------------------------------------------------------------------- manifests, restarts, caps
def test_an_hourly_coverage_manifest_and_a_status_file(tmp_path: Path) -> None:
    start = datetime(2026, 10, 13, 18, 58, tzinfo=UTC).timestamp()
    clock = Clock(start)
    box = recorder(tmp_path, venue(), clock, btc15m=False)
    while clock.at < start + 180:
        if not box.step():
            clock.sleep(0.25)
    box.close()
    manifest = json.loads((tmp_path / "kalshi_recorder" / "manifests" / "coverage-2026-10-13T18.json").read_text())
    assert manifest["read_only"] is True and manifest["order_capability"] is False and manifest["partial"] is False
    assert manifest["host"] == "workspace" and manifest["lanes"]["books"]["requests"] > 0
    assert manifest["lanes"]["books"]["rtt_ms"]["p99"] is not None
    assert manifest["coverage"]["candidate_book_fresh_share"] is not None and manifest["segments"]
    status = json.loads((tmp_path / "kalshi_recorder" / "status.json").read_text())
    assert status["candidates"] == 1 and status["read_only"] is True


def test_a_restart_reports_the_downtime_and_backfills_the_tape(tmp_path: Path) -> None:
    clock = Clock(NOW)
    fake = venue()
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 80)
    box.close()
    clock.at += 1800  # down for half an hour
    again = recorder(tmp_path, fake, clock, btc15m=False)
    assert CANDIDATE in again.watched  # the watch list survives a restart
    run(again, clock, 120)
    again.close()
    causes = [record["cause"] for record in records(tmp_path, "gaps") if record["kind"] == "gap"]
    assert "recorder_not_running" in causes and "trade_tape_behind" in causes
    assert any(row["backfill"] for row in records(tmp_path, "trade_coverage"))


def test_a_paused_store_sends_no_requests(tmp_path: Path) -> None:
    clock = Clock(NOW)
    fake = venue()
    box = recorder(tmp_path, fake, clock, btc15m=False)
    box.store.max_bytes = box.store.used_bytes() + 1  # the cap is reached
    clock.at += 61
    assert box.step() is False and box.store.level == LEVEL_PAUSED
    assert fake.calls == []
    box.close()


def test_a_stale_lane_opens_and_closes_a_gap(tmp_path: Path) -> None:
    clock = Clock(NOW)
    fake = venue()
    box = recorder(tmp_path, fake, clock, btc15m=False)
    run(box, clock, 80)
    fake.fail["/markets/orderbooks"] = [500] * 6  # backs off 2, 4, 8, 16, 30, 30 s: stale after 30 s
    run(box, clock, 800)
    box.close()
    gaps = [record for record in records(tmp_path, "gaps") if record["kind"] == "gap" and record["gap_lane"] == "books"]
    assert [record["cause"] for record in gaps][:2] == ["lane_stale", "lane_stale_recovered"]
    assert gaps[1]["from"] == gaps[0]["from"] and gaps[1]["to"] > gaps[1]["from"]


def test_status_and_verify_commands(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    clock = Clock(NOW)
    box = recorder(tmp_path, venue(), clock, btc15m=False)
    run(box, clock, 40)
    box.close()
    assert main(["status", "--data-dir", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["segments"] > 0
    assert main(["verify", "--data-dir", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


# --------------------------------------------------------------------------- optional spot ticks
def test_spot_parsers_keep_raw_btc_trades_only() -> None:
    coinbase = {"channel": "market_trades", "events": [{"trades": [
        {"trade_id": "1", "product_id": "BTC-USD", "price": "83000.01", "size": "0.01", "side": "BUY",
         "time": "2026-10-13T18:00:00.1Z"},
        {"trade_id": "2", "product_id": "ETH-USD", "price": "3000", "size": "1", "side": "SELL",
         "time": "2026-10-13T18:00:00.2Z"}]}]}
    assert [row["trade_id"] for row in coinbase_trades(coinbase)] == ["1"]
    assert coinbase_trades({"channel": "heartbeats"}) == []
    kraken = {"channel": "trade", "type": "update", "data": [
        {"symbol": "BTC/USD", "side": "buy", "price": 83000.1, "qty": 0.002, "trade_id": 9,
         "timestamp": "2026-10-13T18:00:00.300000Z"}]}
    assert kraken_trades(kraken)[0]["trade_id"] == 9 and kraken_trades({"channel": "status"}) == []


def test_spot_feed_writes_batches_and_reports_reconnects(tmp_path: Path) -> None:
    import asyncio

    clock = Clock(NOW)
    box = recorder(tmp_path, venue(), clock, btc15m=False, spot_ticks=True)
    stop = threading.Event()
    attempts = {"n": 0}

    class Socket:
        def __init__(self) -> None:
            self.messages = [json.dumps({"channel": "market_trades", "events": [{"trades": [
                {"trade_id": "1", "product_id": "BTC-USD", "price": "83000", "size": "0.1", "side": "BUY",
                 "time": "2026-10-13T18:30:00Z"}]}]})]

        async def __aenter__(self) -> Self:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise OSError("first connect fails")
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def send(self, message: str) -> None:
            return None

        async def recv(self) -> str:
            if self.messages:
                return self.messages.pop()
            stop.set()
            raise OSError("closed")

    spot = SpotTicks(box, connect=lambda *args, **kwargs: Socket())

    async def go() -> None:
        original = asyncio.sleep

        async def quick(seconds: float) -> None:
            await original(0)

        asyncio.sleep = quick  # type: ignore[assignment]
        try:
            await spot._feed("coinbase", "wss://example", [], coinbase_trades, stop)
        finally:
            asyncio.sleep = original

    asyncio.run(go())
    spot.flush()
    box.close()
    rows = [record for record in records(tmp_path, "spot")]
    assert rows and rows[0]["venue"] == "coinbase" and rows[0]["basis"] == "exchange_spot_not_cf_benchmarks"
    assert any(record["cause"] == "spot_reconnected" for record in records(tmp_path, "gaps") if record["kind"] == "gap")


def test_a_lagging_tape_keeps_live_windows_short_and_merges_its_backlog(tmp_path: Path) -> None:
    clock = Clock(NOW)
    box = recorder(tmp_path, venue(), clock, btc15m=False)
    box._watch(Watched(CANDIDATE, "KXHIGHNY-26OCT15", "KXHIGHNY", "Climate and Weather", "candidate",
                       NOW - 86400, NOW + 86400, "active", NOW))
    box.trade_rate = 0.5  # a quiet tape: one exchange-wide window is cheaper than one per ticker
    box.trade_covered_to = int(NOW) - 600  # ten minutes behind
    request = box._plan_trades(clock.at)
    assert request is not None
    job = request.context["job"]
    assert job.max_ts - job.min_ts == 60 and len(box.backfill_jobs) == 1
    first = box.backfill_jobs[0]
    assert (first.min_ts, first.ticker) == (int(NOW) - 605, None)
    box.trade_job = None
    box.trade_covered_to = job.min_ts - 30  # still behind: the backlog extends the queued window
    box.next_trades_at = -1
    clock.at += 5
    box._plan_trades(clock.at)
    assert len(box.backfill_jobs) == 1 and box.backfill_jobs[0].min_ts == int(NOW) - 605
    box.close()
