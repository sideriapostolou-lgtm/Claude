"""pump.fun candle fallback: parsing the captured response, gap filling, window trimming, its own
conservative rate bucket and the Cloudflare cool-down (Retry-After honoured, never retried inline)."""

from __future__ import annotations

import time

import pytest
import requests

from fakes import FakeClock, FakeHttp, load_fixture
from nightcrawler.http import HttpClient, HttpError
from nightcrawler.models import Candle
from nightcrawler.sources.pumpfun import (
    CANDLES_MAX_LIMIT,
    DEFAULT_COOLDOWN_S,
    HOST,
    MAX_COOLDOWN_S,
    RATE_LIMIT,
    PumpFunClient,
    PumpFunCoolingDown,
    is_pumpfun_coin,
    parse_candles,
)

INU = "AACtroE9u7vTbLWBbMtkPx4bK79YYxBHgb8tfd1Apump"  # tests/fixtures/pumpfun_candles_1m.json
CAPTURED_AT = 1_791_493_118.0  # Date header of the capture: 2026-10-08T20:58:38Z
FIRST_TS, LAST_TS = 1_791_490_080, 1_791_493_080  # first / newest candle (the newest was still open)
CANDLES = "/v1/coins/"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(CAPTURED_AT)


@pytest.fixture
def http(fake_http: FakeHttp, clock: FakeClock) -> HttpClient:
    return HttpClient(session=fake_http, clock=clock, rate_limits={}, default_rate=None)


@pytest.fixture
def client(http: HttpClient) -> PumpFunClient:
    return PumpFunClient(http)


# --------------------------------------------------------------------------- parsing


def test_parse_candles_reads_the_captured_response() -> None:
    rows = load_fixture("pumpfun_candles_1m")
    candles = parse_candles(rows)
    assert len(candles) == len(rows) == 40
    assert [c.ts for c in candles] == sorted(c.ts for c in candles)  # ascending, epoch SECONDS
    assert candles[0] == Candle(FIRST_TS, float(rows[0]["open"]), float(rows[0]["high"]), float(rows[0]["low"]),
                                float(rows[0]["close"]), float(rows[0]["volume"]))
    assert all(c.l <= min(c.o, c.c) and c.h >= max(c.o, c.c) for c in candles)


def test_parse_candles_skips_bad_rows_and_keeps_the_last_duplicate() -> None:
    good = {"timestamp": 1_791_490_080_000, "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "9"}
    rows = [good, {**good, "close": "1.7"}, {**good, "timestamp": None}, {**good, "open": "x"},
            {**good, "timestamp": 1_791_490_140_000, "volume": None}, "junk", None]
    candles = parse_candles(rows)
    assert [(c.ts, c.c, c.v) for c in candles] == [(1_791_490_080, 1.7, 9.0), (1_791_490_140, 1.5, 0.0)]
    assert parse_candles({"not": "a list"}) == [] and parse_candles(None) == []


# --------------------------------------------------------------------------- candles


def test_candles_fill_the_no_trade_minutes_and_send_the_documented_request(client, fake_http) -> None:
    fake_http.register_fixture(CANDLES, "pumpfun_candles_1m")
    candles = client.candles(INU, minutes=60)
    # pump.fun only returns minutes that had trades: the 12 empty ones between them are filled flat
    assert [c.ts for c in candles] == list(range(FIRST_TS, LAST_TS + 1, 60))
    by_ts = {c.ts: c for c in candles}
    gap = by_ts[1_791_490_740]  # no trades in this minute
    assert (gap.o, gap.h, gap.l, gap.c, gap.v) == (by_ts[1_791_490_680].c,) * 4 + (0.0,)
    [call] = fake_http.calls
    assert call.url == f"https://{HOST}/v1/coins/{INU}/candles"
    assert call.params == {"interval": "1m", "limit": 61}


def test_candles_trim_to_the_window_and_never_invent_newer_minutes(client, fake_http, clock) -> None:
    fake_http.register_fixture(CANDLES, "pumpfun_candles_1m")
    clock.advance(600)  # ten minutes later, no new trades: nothing is invented after the newest candle
    candles = client.candles(INU, minutes=20)
    end = int(clock.now())
    assert candles[0].ts >= end - 20 * 60 and candles[-1].ts == LAST_TS


def test_candles_limit_is_capped_at_1000(client, fake_http) -> None:
    fake_http.register(CANDLES, [])
    assert client.candles(INU, minutes=6 * 60 + 4) == []
    assert client.candles(INU, minutes=5000) == []
    assert [c.params["limit"] for c in fake_http.calls] == [6 * 60 + 5, CANDLES_MAX_LIMIT]


def test_candles_with_no_minutes_make_no_request(client, fake_http) -> None:
    assert client.candles(INU, minutes=0) == []
    assert fake_http.calls == []


def test_an_invalid_mint_surfaces_as_http_error_without_a_cool_down(client, fake_http) -> None:
    fake_http.register(CANDLES, {"statusCode": 404, "message": "Invalid mint address format"}, status=404)
    with pytest.raises(HttpError) as info:
        client.candles("notamint", minutes=30)
    assert info.value.status == 404
    assert client.cooldown_until == 0.0
    with pytest.raises(HttpError):
        client.candles("notamint", minutes=30)
    assert len(fake_http.calls) == 2


# --------------------------------------------------------------------------- Cloudflare limits


def test_a_429_starts_a_cool_down_of_retry_after_seconds(client, fake_http, clock) -> None:
    fake_http.register_fixture(CANDLES, "pumpfun_candles_1m")
    fake_http.register(CANDLES, {"error": "rate limited"}, status=429, headers={"Retry-After": "120"}, times=1)
    with pytest.raises(HttpError) as info:
        client.candles(INU, minutes=30)
    assert info.value.status == 429 and len(fake_http.calls) == 1  # never retried inline (no blocking sleep)
    assert clock.sleeps == []
    clock.advance(119)
    with pytest.raises(PumpFunCoolingDown):
        client.candles(INU, minutes=30)
    assert len(fake_http.calls) == 1  # nothing sent while cooling down
    clock.advance(1)
    assert client.candles(INU, minutes=30)
    assert len(fake_http.calls) == 2


@pytest.mark.parametrize("headers,expected", [
    ({}, DEFAULT_COOLDOWN_S),
    ({"Retry-After": "0"}, DEFAULT_COOLDOWN_S),  # "0" is no licence to hammer a Cloudflare limit
    ({"retry-after": "7200"}, MAX_COOLDOWN_S),
    ({"Retry-After": "Thu, 08 Oct 2026 21:03:38 GMT"}, 300.0),
    ({"Retry-After": "soon"}, DEFAULT_COOLDOWN_S),
])
def test_cool_down_length(client, fake_http, clock, headers, expected) -> None:
    fake_http.register(CANDLES, "<html>Cloudflare</html>", status=429, headers=headers)
    with pytest.raises(HttpError):
        client.candles(INU, minutes=30)
    assert client.cooldown_until - clock.now() == pytest.approx(expected)


@pytest.mark.parametrize("status", [403, 503])
def test_cloudflare_blocks_also_cool_down(client, fake_http, clock, status) -> None:
    fake_http.register(CANDLES, "<html>Attention Required! | Cloudflare</html>", status=status)
    with pytest.raises(HttpError):
        client.candles(INU, minutes=30)
    assert client.cooldown_until > clock.now()


def test_a_connection_error_is_an_http_error(client, fake_http) -> None:
    fake_http.register(CANDLES, requests.ConnectionError("reset by peer"))
    with pytest.raises(HttpError) as info:
        client.candles(INU, minutes=30)
    assert info.value.status is None and info.value.retryable


def test_requests_go_through_the_shared_rate_bucket(fake_http, clock) -> None:
    http = HttpClient(session=fake_http, clock=clock, rate_limits={HOST: RATE_LIMIT}, default_rate=None)
    fake_http.register(CANDLES, [])
    pumpfun = PumpFunClient(http)
    for _ in range(6):
        pumpfun.candles(INU, minutes=30)
    assert RATE_LIMIT[0] <= 12 / 60 and RATE_LIMIT[1] <= 3  # conservative: about 12 requests a minute
    assert sum(clock.sleeps) == pytest.approx((6 - RATE_LIMIT[1]) / RATE_LIMIT[0])
    assert http.stats[HOST]["requests"] == 6


def test_every_request_counts_on_the_usage_panel(client, http, fake_http, clock, tmp_path) -> None:
    """pump.fun bypasses ``request_json`` (no inline retries), so it counts its own calls - failed
    ones too - in the shared tracker that the dashboard's API usage card reads."""
    from nightcrawler.http import KV_USAGE, attach_usage_store
    from nightcrawler.ledger import Ledger

    fake_http.register_fixture(CANDLES, "pumpfun_candles_1m")
    fake_http.register(CANDLES, {"error": "rate limited"}, status=429, times=1)
    with Ledger(tmp_path / "usage.db", clock=clock) as ledger:
        attach_usage_store(http, ledger)
        with pytest.raises(HttpError):
            client.candles(INU, minutes=30)
        with pytest.raises(PumpFunCoolingDown):  # nothing sent while cooling down: nothing counted
            client.candles(INU, minutes=30)
        clock.advance(DEFAULT_COOLDOWN_S)
        assert client.candles(INU, minutes=30)
        assert http.usage.flush()
        assert ledger.get_kv(KV_USAGE)["pumpfun"]["day_counts"] == {"calls": 2}
        assert len(fake_http.calls) == 2


# --------------------------------------------------------------------------- which coins


@pytest.mark.parametrize("launchpad,dex,expected", [
    ("pump.fun", None, True),
    (None, "pumpfun", True),  # still on the bonding curve
    (None, "pumpswap", True),  # graduated to PumpSwap
    ("pump.fun", "raydium", False),  # its main market moved: pump.fun candles would miss most trades
    (None, "raydium", False),
    ("letsbonk.fun", None, False),
    (None, None, False),
])
def test_is_pumpfun_coin(launchpad, dex, expected) -> None:
    assert is_pumpfun_coin(launchpad=launchpad, dex=dex) is expected


# --------------------------------------------------------------------------- live


@pytest.mark.live
def test_live_pumpfun_candles_match_the_documented_shape() -> None:
    client = PumpFunClient(HttpClient())
    candles = client.candles("8ZCmwpW3MtC5UpNcZf7U4HMvRNTo71syU11BDiAFpump", minutes=30)  # GARY (graduated)
    now = time.time()
    assert candles and candles[-1].ts >= now - 30 * 60
    assert [c.ts for c in candles] == list(range(candles[0].ts, candles[-1].ts + 1, 60))
    assert all(c.l <= min(c.o, c.c) and c.h >= max(c.o, c.c) and c.v >= 0 for c in candles)
