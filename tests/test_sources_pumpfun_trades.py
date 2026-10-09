"""pump.fun swap-api trades feed: parsing the captured page, the client's own non-blocking bucket, Retry-After
cool-downs (shared with the candle client), usage counting, never an inline retry; CoinSync's oldest-first
catch-up and incremental polling against a fake swap-api that pages REAL recorded trades newest first; the
checkpoint-aware PollScheduler, end to end (the tracker it fills equals the recorded history)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
import requests

from fakes import FakeClock, FakeHttp, FakeRequest, FakeResponse, load_fixture
from nightcrawler.flow import VENUE_AMM, VENUE_CURVE, FlowTracker
from nightcrawler.http import HttpClient, HttpError
from nightcrawler.sources.pumpfun import PumpFunClient, PumpFunCoolingDown
from nightcrawler.sources.pumpfun_trades import (
    DEFAULT_COOLDOWN_S,
    HOST,
    PAGE_LIMIT,
    ZERO_SID,
    CoinSync,
    PollScheduler,
    PumpFunTradesClient,
    RequestBucket,
    TradesBudgetExhausted,
    cursor_before,
    parse_page,
    parse_trade,
    split_sid,
)
from test_flow_parity import COINS, INSTANT, tracker_for

TRADES = "/v2/coins/"


def _ts_ms(row: dict[str, Any]) -> int:
    return int(datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")).timestamp() * 1000)


class FakeSwapApi:
    """swap-api's /trades semantics over recorded rows: newest first, ``cursor = <sid>-<ts_ms>`` returns rows strictly
    older than (ts_ms, sid), 100 per page; rows stamped after the clock (minus an indexing lag) do not exist yet."""

    def __init__(self, rows_by_mint: dict[str, list[dict[str, Any]]], clock: FakeClock, lag_s: float = 1.0) -> None:
        self.rows = {m: sorted(rs, key=lambda r: (_ts_ms(r), r["slotIndexId"]), reverse=True)
                     for m, rs in rows_by_mint.items()}
        self.clock = clock
        self.lag_s = lag_s
        self.calls = 0

    def __call__(self, req: FakeRequest) -> Any:
        self.calls += 1
        mint = req.url.split(TRADES)[1].split("/")[0]
        params = req.params or {}
        limit = int(params.get("limit", 100))
        if limit > 100:
            return FakeResponse(400, {"message": "limit must not be greater than 100"})
        cur = params.get("cursor")
        now_ms = (self.clock.now() - self.lag_s) * 1000
        rows = [r for r in self.rows.get(mint, []) if _ts_ms(r) <= now_ms]
        if cur:
            sid, ts = cur.split("-")
            rows = [r for r in rows if (_ts_ms(r), r["slotIndexId"]) < (int(ts), sid)]
        page = rows[:limit]
        nxt = f"{page[-1]['slotIndexId']}-{_ts_ms(page[-1])}" if page else None
        return {"trades": page, "pagination": {"nextCursor": nxt, "hasMore": len(rows) > limit, "limit": limit}}


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(1_791_400_000.0)                   # before every fixture coin; tests move it forward


@pytest.fixture
def http(fake_http: FakeHttp, clock: FakeClock) -> HttpClient:
    return HttpClient(session=fake_http, clock=clock, rate_limits={}, default_rate=None)


# =========================================================================== parsing


def test_parse_page_reads_the_captured_response() -> None:
    body = load_fixture("pumpfun_swap_trades")
    page = parse_page(body)
    assert page.n_rows == len(body["trades"]) and page.n_dropped == 0
    assert page.next_cursor == body["pagination"]["nextCursor"] and page.has_more is bool(body["pagination"]["hasMore"])
    t, row = page.trades[0], body["trades"][0]
    assert t.sid == row["slotIndexId"] and (t.slot, t.pos) == split_sid(row["slotIndexId"])
    assert t.ts == _ts_ms(row) // 1000 and t.wallet == row["userAddress"] and t.is_buy is (row["type"] == "buy")
    assert t.venue == (VENUE_AMM if row["program"] == "pump_amm" else VENUE_CURVE)
    assert t.tok_raw == round(float(row["baseAmount"]) * 1e6) and t.price == float(row["priceSol"])
    assert [x.key for x in page.trades] == sorted((x.key for x in page.trades), reverse=True)   # newest first


def test_parse_trade_rejects_malformed_or_failed_rows() -> None:
    good = load_fixture("pumpfun_swap_trades")["trades"][0]
    assert parse_trade(good) is not None
    for bad in ({**good, "slotIndexId": "12"}, {**good, "program": "raydium"}, {**good, "type": "swap"},
                {**good, "timestamp": "yesterday"}, {**good, "userAddress": ""}, {**good, "priceSol": "0"},
                {**good, "amountSol": "-1"}, {**good, "baseAmount": None}, {**good, "err": "Custom 6001"},
                {**good, "success": False}, "junk", None):
        assert parse_trade(bad) is None
    assert parse_page({"trades": "x"}).trades == [] and parse_page(None).next_cursor is None


def test_cursor_before_is_exclusive_on_the_timestamp() -> None:
    assert cursor_before(1_791_414_561_000) == f"{ZERO_SID}-1791414561000"


# =========================================================================== client


def test_client_sends_one_request_counts_usage_and_records_the_origin_limit(http, fake_http, clock) -> None:
    fake_http.register(TRADES, load_fixture("pumpfun_swap_trades"),
                       headers={"x-ratelimit-remaining": "952", "x-ratelimit-limit": "1000"})
    client = PumpFunTradesClient(http)
    page = client.fetch_page("MINT", cursor_before(123))
    assert page.trades
    (call,) = fake_http.calls
    assert call.url == f"https://{HOST}/v2/coins/MINT/trades"
    assert call.params == {"limit": PAGE_LIMIT, "cursor": f"{ZERO_SID}-123"}
    assert http.usage._pending[("pumpfun", "2026-10-07")]["calls"] == 1
    assert client.ratelimit_remaining == 952 and client.ratelimit_limit == 1000
    assert http.stats[HOST]["requests"] == 1


def test_bucket_is_non_blocking(http, fake_http, clock) -> None:
    fake_http.register(TRADES, {"trades": [], "pagination": {}})
    client = PumpFunTradesClient(http, rate=(6 / 60, 2))
    client.fetch_page("M")
    client.fetch_page("M")
    with pytest.raises(TradesBudgetExhausted) as exc:
        client.fetch_page("M")                                       # nothing sent, no sleep
    assert len(fake_http.calls) == 2 and clock.sleeps == []
    assert exc.value.seconds_left == pytest.approx(10.0)
    assert client.available() == 0
    clock.advance(10)
    assert client.available() == 1
    client.fetch_page("M")
    assert len(fake_http.calls) == 3


def test_rate_limit_starts_a_shared_cooldown_and_is_never_retried(http, fake_http, clock) -> None:
    fake_http.register(TRADES, {"trades": []}, status=429, headers={"Retry-After": "120"})
    candles = PumpFunClient(http)
    client = PumpFunTradesClient(http, cooldowns=candles.cooldowns)
    with pytest.raises(HttpError) as exc:
        client.fetch_page("M")
    assert exc.value.status == 429 and len(fake_http.calls) == 1        # no inline retry
    assert client.cooldown_until == clock.now() + 120
    assert candles.cooldown_until == clock.now() + 120                  # the candle client backs off too
    with pytest.raises(PumpFunCoolingDown):
        client.fetch_page("M")
    with pytest.raises(PumpFunCoolingDown):
        candles.candles("M", 5)
    assert len(fake_http.calls) == 1 and client.available() == 0
    clock.advance(121)
    fake_http.register(TRADES, {"trades": [], "pagination": {}})
    client.fetch_page("M")
    assert len(fake_http.calls) == 2


def test_cloudflare_block_without_retry_after_uses_the_default_cooldown(http, fake_http, clock) -> None:
    fake_http.register(TRADES, "<html>blocked</html>", status=403)
    client = PumpFunTradesClient(http)
    with pytest.raises(HttpError):
        client.fetch_page("M")
    assert client.cooldown_until == clock.now() + DEFAULT_COOLDOWN_S


def test_bad_request_and_network_errors_do_not_cool_down(http, fake_http, clock) -> None:
    fake_http.register(TRADES, {"message": "limit must not be greater than 100"}, status=400)
    client = PumpFunTradesClient(http)
    with pytest.raises(HttpError) as exc:
        client.fetch_page("M")
    assert exc.value.status == 400 and not exc.value.retryable and client.cooldown_until == 0
    fake_http.register(TRADES, requests.ConnectionError("reset"))
    with pytest.raises(HttpError) as exc2:
        client.fetch_page("M")
    assert exc2.value.status is None and exc2.value.retryable and client.errors == 2


def test_request_bucket_refills_on_the_clock(clock) -> None:
    b = RequestBucket(1.0, 2, clock)
    assert b.try_take() and b.try_take() and not b.try_take()
    assert b.seconds_until() == pytest.approx(1.0)
    clock.advance(1.5)
    assert b.try_take() and not b.try_take()
    with pytest.raises(ValueError):
        RequestBucket(0, 1, clock)


# =========================================================================== CoinSync against a fake swap-api


def _api(fake_http: FakeHttp, clock: FakeClock, mints: list[str], lag_s: float = 1.0) -> FakeSwapApi:
    api = FakeSwapApi({m: COINS[m]["swap"] for m in mints}, clock, lag_s)
    fake_http.register(TRADES, api)
    return api


def _drive(sync: CoinSync, client: PumpFunTradesClient, clock: FakeClock, until: float) -> int:
    """One request per second while there is work, the way the scheduler would."""
    sent = 0
    while clock.now() < until:
        cur = sync.next_cursor(clock.now())
        if cur is not None and client.available():
            sync.on_page(client.fetch_page(sync.mint, cur), clock.now())
            sent += 1
        clock.advance(1.0)
    return sent


@pytest.mark.parametrize("mint", INSTANT)
def test_catch_up_after_the_fact_rebuilds_the_exact_history(mint, http, fake_http, clock) -> None:
    """Watch a coin 5 minutes late: oldest-first windows rebuild every trade, in order, from creation."""
    coin = COINS[mint]
    c_ts = coin["created_ms"] // 1000
    clock.advance(c_ts + 300 - clock.now())
    api = _api(fake_http, clock, [mint])
    client = PumpFunTradesClient(http, rate=(10.0, 10))
    tr = FlowTracker(mint, created_ts=c_ts, creator=coin["graduate"]["creator"])
    sync = CoinSync(tr, c_ts, window_s=30.0)
    assert tr.history_from == c_ts and tr.complete_through == c_ts
    _drive(sync, client, clock, clock.now() + 60)
    ref = tracker_for(coin)
    assert tr.trades == ref.trades                              # every recorded trade, nothing else, chain order
    assert tr.complete_through >= c_ts + 120
    assert sync.caught_up(clock.now())
    assert api.calls == sync.requests
    s, r = tr.as_of(c_ts + 140), ref.as_of(c_ts + 140)
    assert s.complete and s.features() == r.features()


def test_live_polling_only_marks_settled_seconds_complete(http, fake_http, clock) -> None:
    mint = INSTANT[0]
    coin = COINS[mint]
    c_ts = coin["created_ms"] // 1000
    clock.advance(c_ts - clock.now())
    _api(fake_http, clock, [mint], lag_s=1.0)
    client = PumpFunTradesClient(http, rate=(10.0, 10))
    tr = FlowTracker(mint, created_ts=c_ts)
    sync = CoinSync(tr, c_ts, window_s=20.0, settle_s=3.0)
    for _ in range(130):
        _drive(sync, client, clock, clock.now() + 1)
        assert tr.complete_through <= max(c_ts, clock.now() - sync.settle_s) + 1e-9
        assert all(t.ts < tr.complete_through for t in tr.trades)      # nothing past the confirmed horizon
    assert tr.trades == tracker_for(coin).trades
    assert sync.rate_tps > 0


# =========================================================================== scheduler


def test_scheduler_serves_due_checkpoints_first_and_reports_missed_ones(http, fake_http, clock) -> None:
    a, b = INSTANT[0], INSTANT[1]
    ca, cb = COINS[a]["created_ms"] // 1000, COINS[b]["created_ms"] // 1000
    now = max(ca, cb) + 600
    clock.advance(now - clock.now())
    _api(fake_http, clock, [a, b])
    client = PumpFunTradesClient(http, rate=(1 / 6, 1))                # 10 requests a minute, burst 1
    sched = PollScheduler(client)
    wa = sched.watch(FlowTracker(a, created_ts=ca), ca)                 # catching up, no checkpoint
    wb = sched.watch(FlowTracker(b, created_ts=cb), cb, checkpoints=[now + 5])   # tau = now - 15: due
    assert sched.plan(now, 2) == [b, a]
    rep = sched.tick()
    assert rep.polled == [b] and rep.sent == 1
    rep = sched.tick()                                                  # bucket empty: nothing sent, no blocking
    assert rep.sent == 0 and rep.stopped == "budget"
    wb.checkpoints.append(now - 1)                                      # a decision that already passed
    rep = sched.tick(now)
    assert now - 1 in rep.missed[b] and now - 1 in wb.missed
    assert wa.sync.requests == 0


def test_scheduler_end_to_end_fills_trackers_within_budget(http, fake_http, clock) -> None:
    mints = INSTANT
    c0 = min(COINS[m]["created_ms"] // 1000 for m in mints)
    clock.advance(c0 - 5 - clock.now())
    api = _api(fake_http, clock, mints)
    client = PumpFunTradesClient(http, rate=(12 / 60, 2))
    sched = PollScheduler(client)
    trackers = {}
    for m in mints:
        c = COINS[m]["created_ms"] // 1000
        trackers[m] = FlowTracker(m, created_ts=c, creator=COINS[m]["graduate"]["creator"])
        sched.watch(trackers[m], c, checkpoints=[c + 140], max_staleness_s=30.0)
    end = max(COINS[m]["created_ms"] // 1000 for m in mints) + 400
    sent_per_minute: dict[int, int] = {}
    while clock.now() < end:
        rep = sched.tick()
        minute = int(clock.now() // 60)
        sent_per_minute[minute] = sent_per_minute.get(minute, 0) + rep.sent
        clock.advance(1.0)
    assert max(sent_per_minute.values()) <= 14                         # 12/min + the burst of 2
    assert api.calls == sum(sent_per_minute.values())
    for m in mints:
        c = COINS[m]["created_ms"] // 1000
        ref = tracker_for(COINS[m])
        got = [t for t in trackers[m].trades if t.ts < c + 120]
        assert got == list(ref.trades)
        snap = trackers[m].as_of(c + 140)
        assert snap.complete and snap.features() == ref.as_of(c + 140).features()
        assert not sched.watches[m].missed


def test_scheduler_stops_on_cooldown_and_backs_off_a_bad_coin(http, fake_http, clock) -> None:
    client = PumpFunTradesClient(http, rate=(10.0, 10))
    sched = PollScheduler(client)
    c = int(clock.now()) - 600
    sched.watch(FlowTracker("BAD", created_ts=c), c)
    sched.watch(FlowTracker("GOOD", created_ts=c), c, max_staleness_s=0.0)
    fake_http.register("/v2/coins/GOOD/", {"trades": [], "pagination": {"hasMore": False}})
    fake_http.register("/v2/coins/BAD/", {"message": "bad mint"}, status=404)
    rep = sched.tick()
    assert "BAD" in rep.errors and sched.watches["BAD"].sync.retry_after > clock.now()
    assert "GOOD" in rep.polled
    fake_http.register("/v2/coins/GOOD/", {}, status=429, headers={"Retry-After": "30"})
    clock.advance(1)
    sched.watches["GOOD"].sync.sweep = None
    rep = sched.tick()
    assert rep.stopped == "cooldown"
    calls = len(fake_http.calls)
    rep = sched.tick()
    assert rep.sent == 0 and rep.stopped == "cooldown" and len(fake_http.calls) == calls
