"""pump.fun swap-api trades feed: parsing the captured page, the client's own non-blocking bucket, Retry-After
cool-downs (shared with the candle client), usage counting, never an inline retry; CoinSync's oldest-first
catch-up and incremental polling against a fake swap-api that pages REAL recorded trades newest first; the
checkpoint-aware PollScheduler, end to end (the tracker it fills equals the recorded history)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import pytest
import requests

from fakes import FakeClock, FakeHttp, FakeRequest, FakeResponse, load_fixture
from nightcrawler.flow import VENUE_AMM, VENUE_CURVE, FlowTracker, grid_time
from nightcrawler.http import HttpClient, HttpError
from nightcrawler.sources.pumpfun import PumpFunClient, PumpFunCoolingDown
from nightcrawler.sources.pumpfun_trades import (
    DEFAULT_COOLDOWN_S,
    DEFAULT_TIMEOUT_S,
    HOST,
    HOST_BACKOFF_S,
    PAGE_LIMIT,
    ZERO_SID,
    CoinSync,
    MalformedTradesPage,
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
        #: (mint, params, body) -> what to serve instead (a body, a FakeResponse or an exception): a broken API
        self.transform: Callable[[str, dict[str, Any], dict[str, Any]], Any] | None = None

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
        body = {"trades": page, "pagination": {"nextCursor": nxt, "hasMore": len(rows) > limit, "limit": limit}}
        if self.transform is not None:
            return self.transform(mint, params, body)
        return body


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def synth(ts: int, slot: int, pos: int = 1, *, buy: bool = True, wallet: str = "W1", program: str = "pump_amm",
          price: str = "0.0000004", amount: str = "0.1", base: str = "250000") -> dict[str, Any]:
    """A swap-api row of a synthetic coin (the recorded rows' format)."""
    return {"slotIndexId": f"{slot:012d}{pos:010d}", "tx": f"tx{slot}_{pos}", "timestamp": _iso(ts),
            "userAddress": wallet, "type": "buy" if buy else "sell", "program": program, "priceSol": price,
            "amountSol": amount, "baseAmount": base}


EMPTY_PAGE = {"trades": [], "pagination": {"nextCursor": None, "hasMore": False, "limit": 100}}


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


@pytest.mark.parametrize("poison", [
    {"slotIndexId": "\u00b2" + "0" * 21},       # str.isdigit() accepts superscripts; int() does not
    {"slotIndexId": "\u0661" * 22},             # Arabic-Indic digits
    {"baseAmount": "1e300"}, {"amountSol": "1e300"}, {"priceSol": "1e300"}, {"baseAmount": "2e9"},
    {"amountSol": "1e8"}, {"timestamp": 12345}, {"priceSol": {"x": 1}},
    {"timestamp": "0001-01-01T00:00:00+14:00"}, {"timestamp": "9999-12-31T23:59:59Z"},
])
def test_parse_trade_rejects_values_that_cannot_be_used_and_never_raises(poison: dict[str, Any]) -> None:
    good = load_fixture("pumpfun_swap_trades")["trades"][0]
    assert parse_trade({**good, **poison}) is None


@pytest.mark.parametrize("body", [None, "junk", [], {"message": "Internal server error"}, {"trades": "x"},
                                  {"trades": []}, {"trades": [], "pagination": "x"},
                                  {"trades": [], "pagination": {"nextCursor": None}},
                                  {"trades": [], "pagination": {"hasMore": "false"}}])
def test_parse_page_refuses_a_body_that_is_not_a_trades_page(body: Any) -> None:
    with pytest.raises(MalformedTradesPage):
        parse_page(body)


def test_parse_page_tells_failed_rows_from_unparseable_ones() -> None:
    good = load_fixture("pumpfun_swap_trades")["trades"]
    page = parse_page({"trades": [good[0], {**good[1], "err": "Custom 6001"}, {**good[2], "program": "pump_amm_v2"}],
                       "pagination": {"nextCursor": "c", "hasMore": True}})
    assert len(page.trades) == 1 and page.n_failed == 1 and page.n_invalid == 1 and page.n_dropped == 2


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
    fake_http.register(TRADES, EMPTY_PAGE)
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
    fake_http.register(TRADES, EMPTY_PAGE)
    client.fetch_page("M")
    assert len(fake_http.calls) == 2


def test_cloudflare_block_without_retry_after_uses_the_default_cooldown(http, fake_http, clock) -> None:
    fake_http.register(TRADES, "<html>blocked</html>", status=403)
    client = PumpFunTradesClient(http)
    with pytest.raises(HttpError):
        client.fetch_page("M")
    assert client.cooldown_until == clock.now() + DEFAULT_COOLDOWN_S


def test_a_bad_request_does_not_cool_the_host_down_but_a_network_error_does(http, fake_http, clock) -> None:
    fake_http.register(TRADES, {"message": "limit must not be greater than 100"}, status=400)
    client = PumpFunTradesClient(http)
    with pytest.raises(HttpError) as exc:
        client.fetch_page("M")
    assert exc.value.status == 400 and not exc.value.retryable and client.cooldown_until == 0
    fake_http.register(TRADES, requests.ConnectionError("reset"))
    with pytest.raises(HttpError) as exc2:
        client.fetch_page("M")
    assert exc2.value.status is None and exc2.value.retryable and client.errors == 2
    assert client.cooldown_until == clock.now() + HOST_BACKOFF_S


def test_requests_use_the_short_timeout(http, fake_http, clock) -> None:
    fake_http.register(TRADES, EMPTY_PAGE)
    PumpFunTradesClient(http).fetch_page("M")
    assert fake_http.calls[0].timeout == DEFAULT_TIMEOUT_S < http.timeout_s


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
    late = now - 1 - sched.grace_s                                      # a decision that passed, grace included
    wb.checkpoints.append(late)
    rep = sched.tick(now)
    assert late in rep.missed[b] and late in wb.missed
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


def test_catch_up_is_shortest_job_first_and_demand_shows_overload(http, clock) -> None:
    client = PumpFunTradesClient(http, rate=(8 / 60, 2))
    sched = PollScheduler(client)
    now = clock.now()
    busy = sched.watch(FlowTracker("BUSY"), now - 600)
    quiet = sched.watch(FlowTracker("QUIET"), now - 300)
    busy.sync.rate_tps = 10.0          # a fresh graduate: 600 trades a minute
    quiet.sync.rate_tps = 0.05
    assert sched.plan(now, 2) == ["QUIET", "BUSY"]
    demand = sched.demand_per_min(now)
    assert demand["BUSY"] > sched.capacity_per_min() > demand["QUIET"]
    assert sched.overloaded(now)
    sched.unwatch("BUSY")
    assert not sched.overloaded(now)


# =========================================================================== failing closed (review round 1)

FIXTURE_MINT = "8Tj1fv3MBYj6fjhjRHr1ZWnxqvfbUCV8MwiYD1c1uMoC"      # instant graduate, 143 recorded trades


def _bad_rows(body: dict[str, Any], n: int, **change: Any) -> dict[str, Any]:
    return {**body, "trades": [{**r, **change} if i < n else r for i, r in enumerate(body["trades"])]}


MALFORMED: dict[str, Callable[[dict[str, Any]], Any]] = {
    "not a trades page": lambda body: {"message": "Internal server error"},
    "unknown program": lambda body: {**_bad_rows(body, 10**6, program="pump_amm_v2"),
                                     "pagination": {**body["pagination"], "hasMore": True}},
    "some rows unparseable": lambda body: _bad_rows(body, 10, priceSol="0"),
    "hasMore without nextCursor": lambda body: {**body, "pagination": {**body["pagination"], "hasMore": True,
                                                                       "nextCursor": None}},
    "empty page with hasMore": lambda body: {"trades": [], "pagination": {"nextCursor": "x", "hasMore": True}},
}


@pytest.mark.parametrize("kind", list(MALFORMED))
def test_a_malformed_page_never_marks_history_complete(kind: str, http, fake_http, clock) -> None:
    coin = COINS[FIXTURE_MINT]
    c = coin["created_ms"] // 1000
    clock.advance(c + 180 - clock.now())
    api = _api(fake_http, clock, [FIXTURE_MINT])
    api.transform = lambda mint, params, body: MALFORMED[kind](body)
    sched = PollScheduler(PumpFunTradesClient(http, rate=(10.0, 10)))
    tr = FlowTracker(FIXTURE_MINT, created_ts=c, creator=coin["graduate"]["creator"])
    w = sched.watch(tr, c)
    errors = 0
    for _ in range(120):
        errors += len(sched.tick().errors)
        clock.advance(1.0)
    assert tr.complete_through == c and not tr.as_of(c + 140).complete      # nothing claimed
    assert errors > 0 and w.sync.errors == errors and w.sync.last_error
    assert api.calls <= 6                                                  # per-coin back-off, not every tick
    api.transform = None                                                   # the API recovers
    for _ in range(400):
        sched.tick()
        clock.advance(1.0)
    assert tr.trades == tracker_for(coin).trades
    assert tr.as_of(c + 140).complete and w.sync.consecutive_errors == 0


@pytest.mark.parametrize("echo", ["same cursor", "same trades"])
def test_a_cursor_that_does_not_move_aborts_the_sweep(echo: str, http, fake_http, clock) -> None:
    t0 = int(clock.now())
    rows = {"STUCK": [synth(t0 - 300 + i // 2, 1_000 + i) for i in range(600)],
            "OK": [synth(t0 - 300 + 30 * i, 5_000 + i) for i in range(10)]}
    api = FakeSwapApi(rows, clock)
    fake_http.register(TRADES, api)
    first: dict[str, Any] = {}

    def stuck(mint: str, params: dict[str, Any], body: dict[str, Any]) -> Any:
        if mint != "STUCK":
            return body
        first.setdefault("body", body)
        nxt = params.get("cursor") if echo == "same cursor" else f"{ZERO_SID}-{api.calls}"
        return {"trades": first["body"]["trades"], "pagination": {"nextCursor": nxt, "hasMore": True}}

    api.transform = stuck
    sched = PollScheduler(PumpFunTradesClient(http, rate=(8 / 60, 2)))
    a = sched.watch(FlowTracker("STUCK"), t0 - 300)
    b = sched.watch(FlowTracker("OK"), t0 - 300, checkpoints=[grid_time(t0, 60 * k) for k in range(2, 30)])
    for _ in range(30 * 60):
        sched.tick()
        clock.advance(1.0)
    assert a.sync.requests <= 20 and a.sync.complete_through == t0 - 300 and a.sync.errors > 0
    assert not b.missed and b.sync.requests >= 25                          # the other coin is served


@pytest.mark.parametrize("failure", ["timeout", "connection", "502", "html 200"])
def test_host_failures_cool_the_shared_host_down_with_exponential_backoff(failure: str, http, fake_http,
                                                                          clock) -> None:
    if failure == "timeout":
        fake_http.register(TRADES, requests.Timeout("read timed out"))
    elif failure == "connection":
        fake_http.register(TRADES, requests.ConnectionError("reset"))
    elif failure == "502":
        fake_http.register(TRADES, "<html>Bad gateway</html>", status=502)
    else:
        fake_http.register(TRADES, "<html>Just a moment...</html>")
    candles = PumpFunClient(http)
    client = PumpFunTradesClient(http, cooldowns=candles.cooldowns)
    sched = PollScheduler(client)
    now = clock.now()
    for i in range(4):
        sched.watch(FlowTracker(f"M{i}"), now - 600, max_staleness_s=0.0)
    stopped = set()
    for _ in range(600):
        stopped.add(sched.tick().stopped)
        clock.advance(1.0)
    # 15 + 30 + 60 + 120 + 240 s: six attempts in ten minutes, never one per tick or per coin
    assert len(fake_http.calls) == 6
    assert candles.cooldown_until > clock.now()                            # the candle client backs off too
    assert "network" in stopped and "cooldown" in stopped
    fake_http.register(TRADES, EMPTY_PAGE)                                 # recovered: the streak resets
    clock.advance(client.cooldown_until - clock.now() + 1)
    client.fetch_page("M0")
    assert client.host_failures == 0
    fake_http.register(TRADES, requests.Timeout("again"))
    with pytest.raises(HttpError):
        client.fetch_page("M0")
    assert client.cooldown_until == pytest.approx(clock.now() + HOST_BACKOFF_S)


def test_a_poison_page_or_an_unexpected_error_never_escapes_a_tick(http, fake_http, clock, monkeypatch) -> None:
    good = load_fixture("pumpfun_swap_trades")["trades"][0]
    poison = [{**good, "slotIndexId": "\u00b2" + "0" * 21}, {**good, "amountSol": "1e300"}]
    fake_http.register(TRADES, {"trades": poison, "pagination": {"nextCursor": None, "hasMore": False}})
    sched = PollScheduler(PumpFunTradesClient(http, rate=(10.0, 10)))
    w = sched.watch(FlowTracker("M"), clock.now() - 100, max_staleness_s=0.0)
    for _ in range(100):
        sched.tick()
        clock.advance(1.0)
    assert w.sync.errors > 0 and len(w.sync.tracker) == 0 and w.sync.complete_through == w.sync.start_ts

    def boom(self: CoinSync, page: Any, now: float) -> int:
        raise RuntimeError("bug")

    monkeypatch.setattr(CoinSync, "on_page", boom)
    fake_http.register(TRADES, EMPTY_PAGE)
    w.sync.retry_after = 0.0
    rep = sched.tick()
    assert "M" in rep.errors and "bug" in rep.errors["M"]
    assert w.sync.sweep is None and w.sync.retry_after > clock.now()


# =========================================================================== re-watch, lag, budget, dormancy

SLOWISH = "FBsA4BegePq3q9iyZMyVRPscbxAasLcKgidd9YYUpump"                 # graduated 59 s after creation


def test_rewatching_from_an_earlier_start_is_not_complete_until_the_gap_is_fetched(http, fake_http, clock) -> None:
    coin = COINS[SLOWISH]
    c, g = coin["created_ms"] // 1000, coin["graduate"]["g_ts"]
    clock.advance(c + 300 - clock.now())
    api = _api(fake_http, clock, [SLOWISH])
    sched = PollScheduler(PumpFunTradesClient(http, rate=(10.0, 10)))
    tr = FlowTracker(SLOWISH, created_ts=c, creator=coin["graduate"]["creator"], g_ts=g)
    sched.watch(tr, g)                                                    # M1 wiring: pool only
    for _ in range(30):
        sched.tick()
        clock.advance(1.0)
    snap = tr.as_of(c + 140)
    assert snap.complete and not snap.curve_known and snap.get("curve_n_buys") is None
    sched.unwatch(SLOWISH)
    w = sched.watch(tr, c)                                                # S1 wiring: from creation
    snap = tr.as_of(c + 140)
    assert not snap.complete                                              # the curve trades are not in yet
    for _ in range(30):
        sched.tick()
        clock.advance(1.0)
    ref = tracker_for(coin, with_g=True)
    assert [t for t in tr.trades if t.ts < c + 120] == list(ref.trades)
    assert tr.as_of(c + 140).complete and tr.as_of(c + 140).features() == ref.as_of(c + 140).features()
    calls = api.calls
    sched.unwatch(SLOWISH)
    w = sched.watch(tr, g)                                                # a later start resumes, no re-download
    assert w.sync.complete_through == tr.complete_through and tr.as_of(c + 140).complete
    sched.tick()
    assert api.calls - calls <= 1


def test_indexing_lag_beyond_settle_is_detected_and_no_trade_is_lost(http, fake_http, clock) -> None:
    t0 = int(clock.now()) + 10
    rows = [synth(t0 + i // 2, 10_000 + i) for i in range(480)]           # 2 trades/s for 4 minutes
    api = FakeSwapApi({"M": rows}, clock, lag_s=5.0)                      # the indexer runs 5 s behind
    fake_http.register(TRADES, api)
    sched = PollScheduler(PumpFunTradesClient(http, rate=(10.0, 10)))
    tr = FlowTracker("M")
    w = sched.watch(tr, t0, max_staleness_s=0.0)
    late = 0
    while clock.now() < t0 + 300:
        late += sum(sched.tick().late.values())
        clock.advance(2.0)
        if clock.now() > t0 + 30:                                         # adapted: every claim holds
            want = {r["slotIndexId"] for r in rows if _ts_ms(r) < tr.complete_through * 1000}
            assert want <= {t.sid for t in tr.trades}
    assert len(tr) == len(rows)                                           # nothing lost for good
    assert late > 0 and w.sync.late_trades == late and w.sync.settle_s >= 5.0


def test_a_caught_up_coin_with_minute_checkpoints_leaves_the_budget_to_catch_up(http, fake_http, clock) -> None:
    t0 = int(clock.now())
    rows = {"Q": [synth(t0 - 7200 + 30 * i, 400_000_000 + 75 * i) for i in range(360)],     # 1 trade / 30 s
            "S": [synth(t0 - 1200 + i, 500_000_000 + 3 * i) for i in range(1200)]}         # 20-min backlog
    fake_http.register(TRADES, FakeSwapApi(rows, clock))
    sched = PollScheduler(PumpFunTradesClient(http))                       # default 8/min, burst 2
    q = sched.watch(FlowTracker("Q"), t0 - 60, checkpoints=[grid_time(t0, 60 * k) for k in range(1, 40)])
    s = sched.watch(FlowTracker("S"), t0 - 1200, checkpoints=[t0 + 1800])
    for _ in range(2000):
        sched.tick()
        clock.advance(1.0)
    assert not s.missed and not q.missed
    assert q.sync.requests <= 45                                            # ~one poll per checkpoint (33 min)
    assert s.sync.backlog_s(clock.now()) <= s.sync.window_s and len(s.sync.tracker) == 1200
    assert not sched.overloaded()


def test_a_late_evaluation_reads_the_checkpoint_snapshot(http, fake_http, clock) -> None:
    t0 = int(clock.now())
    rows = {"M": [synth(t0 - 600 + 2 * i, 700_000 + i) for i in range(900)]}
    fake_http.register(TRADES, FakeSwapApi(rows, clock))
    fake_http.register("/v2/coins/GONE/", {"message": "not found"}, status=404)
    sched = PollScheduler(PumpFunTradesClient(http))
    t_c = grid_time(t0, 600)
    w = sched.watch(FlowTracker("M"), t0 - 600, checkpoints=[t_c])
    gone = sched.watch(FlowTracker("GONE"), t0 - 600, checkpoints=[t_c])
    while clock.now() < t_c + 40:
        sched.tick()
        clock.advance(1.0)
    for late in (0, 2, 5, 10, 30):                                        # engine stages run on intervals
        snap = sched.snapshot("M", t_c, now=t_c + late)
        assert snap is not None and snap.complete and snap.t == t_c
        assert not w.sync.tracker.as_of(t_c + late).complete or late <= 2  # as_of(now) is NOT the checkpoint
    assert not w.missed
    assert sched.snapshot("GONE", t_c) is None and gone.missed == [t_c]   # reported once, never decided on
    assert sched.snapshot("M", t_c, now=t_c + 30, max_late_s=10.0) is None and t_c in w.missed
    assert t_c in sched.tick().missed["M"]


def test_trades_and_candles_draw_on_one_host_budget(fake_http, clock) -> None:
    http = HttpClient(session=fake_http, clock=clock, rate_limits={HOST: (12 / 60, 3)}, default_rate=None)
    fake_http.register(TRADES, EMPTY_PAGE)
    client = PumpFunTradesClient(http)
    assert PollScheduler(client).capacity_per_min() == pytest.approx(8.0)
    trades = waited = 0.0
    for sec in range(120):
        try:
            client.fetch_page("M")
            trades += 1
        except TradesBudgetExhausted:
            pass
        if sec % 10 == 0:
            waited += http.limiter.acquire(HOST)                             # what a candle request does
        clock.advance(1.0)
    assert waited == 0.0                                                     # trades never starve a candle call
    assert trades + 12 <= 3 + 12 * 2                                         # one per-IP budget for both
    assert trades >= 8


def test_a_watch_goes_quiet_after_its_last_checkpoint(http, fake_http, clock) -> None:
    t0 = int(clock.now())
    api = FakeSwapApi({"M": [synth(t0 - 600 + 20 * i, 9_000 + i) for i in range(200)]}, clock)
    fake_http.register(TRADES, api)
    sched = PollScheduler(PumpFunTradesClient(http))
    t_c = grid_time(t0, 300)
    w = sched.watch(FlowTracker("M"), t0 - 600, checkpoints=[t_c])
    while clock.now() < t_c + sched.lead_s + 60:
        sched.tick()
        clock.advance(1.0)
    calls = api.calls
    for _ in range(600):
        sched.tick()
        clock.advance(1.0)
    assert api.calls == calls and sched.status()["M"]["dormant"]          # no background polling for nothing
    sched.add_checkpoint("M", grid_time(clock.now(), 120))
    for _ in range(120):
        sched.tick()
        clock.advance(1.0)
    assert api.calls > calls and not w.missed


@pytest.mark.live
def test_live_catch_up_matches_the_recorded_history() -> None:
    """Opt-in (NIGHTCRAWLER_LIVE_TESTS=1), ~2 requests: the live API pages a recorded coin's first two minutes into
    exactly the trades recorded on 2026-10-08."""
    coin = COINS[INSTANT[1]]
    c_ts = coin["created_ms"] // 1000
    client = PumpFunTradesClient(HttpClient(), rate=(8 / 60, 2))
    tr = FlowTracker(coin["mint"], created_ts=c_ts)
    sync = CoinSync(tr, c_ts, window_s=120.0)
    while tr.complete_through < c_ts + 120 and client.requests_sent < 6:
        sync.on_page(client.fetch_page(coin["mint"], sync.next_cursor(c_ts + 10_000)), c_ts + 10_000)
    assert [t for t in tr.trades if t.ts < c_ts + 120] == list(tracker_for(coin).trades)
