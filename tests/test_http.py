"""Foundation tests: HttpClient retries, backoff, Retry-After, rate limits, errors."""

from __future__ import annotations

import random

import pytest
import requests

from fakes import FakeClock, FakeHttp, FakeResponse
from nightcrawler.http import DEFAULT_RATE_LIMITS, HttpClient, HttpError, RateLimiter, TokenBucket, host_of

URL = "https://api.example.com/v1/thing"


def make_client(fake: FakeHttp, clock: FakeClock, **kw) -> HttpClient:
    kw.setdefault("rate_limits", {})
    kw.setdefault("default_rate", None)
    kw.setdefault("rng", random.Random(0))
    return HttpClient(session=fake, clock=clock, **kw)


def test_get_json_success_records_params_and_headers(fake_http: FakeHttp, http_client: HttpClient) -> None:
    fake_http.register("api.example.com/v1/thing?a=1", {"ok": True})
    assert http_client.get_json(URL, params={"a": 1}, headers={"x-api-key": "k"}) == {"ok": True}
    call = fake_http.calls[0]
    assert call.method == "GET" and call.params == {"a": 1}
    assert call.headers["x-api-key"] == "k" and call.headers["User-Agent"].startswith("nightcrawler/")
    assert call.headers["Accept"] == "application/json"
    assert call.timeout == 10.0


def test_retries_on_429_then_succeeds_with_backoff(fake_http: FakeHttp, fake_clock: FakeClock) -> None:
    client = make_client(fake_http, fake_clock)
    fake_http.register("thing", {"ok": 1})
    fake_http.register("thing", {"error": "slow down"}, status=429, times=2)
    t0 = fake_clock.now()
    assert client.get_json(URL) == {"ok": 1}
    assert len(fake_http.calls) == 3
    # exponential backoff with jitter in [0.5, 1.0] x base * 2**attempt
    assert len(fake_clock.sleeps) == 2
    assert 0.5 <= fake_clock.sleeps[0] <= 1.0
    assert 1.0 <= fake_clock.sleeps[1] <= 2.0
    assert fake_clock.now() - t0 == pytest.approx(sum(fake_clock.sleeps))
    assert client.stats["api.example.com"]["retries"] == 2


def test_retry_after_seconds_is_honored(fake_http: FakeHttp, fake_clock: FakeClock) -> None:
    client = make_client(fake_http, fake_clock)
    fake_http.register("thing", {"ok": 1})
    fake_http.register("thing", {}, status=429, headers={"Retry-After": "7"}, times=1)
    assert client.get_json(URL) == {"ok": 1}
    assert fake_clock.sleeps == [7.0]


def test_retry_after_http_date_and_cap(fake_http: FakeHttp, fake_clock: FakeClock) -> None:
    client = make_client(fake_http, fake_clock, retry_after_max_s=60)
    fake_http.register("thing", {"ok": 1})
    # HTTP-date 30 s in the future relative to the fake clock
    import email.utils

    date = email.utils.formatdate(fake_clock.now() + 30, usegmt=True)
    fake_http.register("thing", {}, status=429, headers={"retry-after": "3600"}, times=1)
    fake_http.register("thing", {}, status=503, headers={"Retry-After": date}, times=1)  # served first
    assert client.get_json(URL) == {"ok": 1}
    assert fake_clock.sleeps == [pytest.approx(30), 60]  # date honoured, then 3600 s capped at 60


def test_gives_up_after_max_retries(fake_http: FakeHttp, fake_clock: FakeClock) -> None:
    client = make_client(fake_http, fake_clock)
    fake_http.register("thing", {"error": "down"}, status=503)
    with pytest.raises(HttpError) as ei:
        client.get_json(URL)
    assert len(fake_http.calls) == 5  # 1 + max_retries(4)
    assert ei.value.status == 503 and ei.value.retryable is True
    assert ei.value.payload == {"error": "down"}
    assert len(fake_clock.sleeps) == 4
    # backoff never exceeds the cap
    assert all(s <= 30 for s in fake_clock.sleeps)


def test_connection_errors_retry_then_raise(fake_http: FakeHttp, fake_clock: FakeClock) -> None:
    client = make_client(fake_http, fake_clock, max_retries=2)
    fake_http.register("thing", requests.ConnectionError("boom"))
    with pytest.raises(HttpError) as ei:
        client.get_json(URL)
    assert ei.value.status is None and ei.value.retryable
    assert len(fake_http.calls) == 3

    fake_http.register("other", {"fine": True})
    fake_http.register("other", requests.Timeout("slow"), times=1)
    assert client.get_json("https://api.example.com/other") == {"fine": True}


def test_4xx_is_not_retried_and_keeps_body(fake_http: FakeHttp, http_client: HttpClient) -> None:
    fake_http.register("report", {"error": "unable to generate report"}, status=400)
    with pytest.raises(HttpError) as ei:
        http_client.get_json("https://api.rugcheck.xyz/v1/tokens/X/report")
    assert len(fake_http.calls) == 1
    err = ei.value
    assert err.status == 400 and not err.retryable
    assert err.payload == {"error": "unable to generate report"}
    assert "unable to generate report" in err.body
    assert "api.rugcheck.xyz/v1/tokens/X/report" in str(err)


def test_post_without_retry_for_non_idempotent_calls(fake_http: FakeHttp, http_client: HttpClient) -> None:
    fake_http.register("execute", {"status": "Failed"}, status=502)
    with pytest.raises(HttpError):
        http_client.post_json("https://lite-api.jup.ag/ultra/v1/execute", json={"a": 1}, retry=False)
    assert len(fake_http.calls) == 1
    assert fake_http.calls[0].method == "POST" and fake_http.calls[0].json == {"a": 1}


def test_invalid_json_and_empty_body(fake_http: FakeHttp, http_client: HttpClient) -> None:
    fake_http.register("html", "<html>cloudflare</html>")
    fake_http.register("empty", None)
    with pytest.raises(HttpError, match="invalid JSON"):
        http_client.get_json("https://api.example.com/html")
    assert http_client.get_json("https://api.example.com/empty") is None


def test_secret_query_values_are_redacted_in_errors(fake_http: FakeHttp, http_client: HttpClient) -> None:
    fake_http.register("helius", {"error": "bad"}, status=401)
    with pytest.raises(HttpError) as ei:
        http_client.post_json("https://mainnet.helius-rpc.com/?api-key=SUPERSECRET", json={})
    assert "SUPERSECRET" not in ei.value.url and "SUPERSECRET" not in str(ei.value)


def test_token_bucket_paces_requests(fake_clock: FakeClock) -> None:
    bucket = TokenBucket(rate_per_s=20 / 60, burst=2, clock=fake_clock)
    waits = [bucket.acquire() for _ in range(4)]
    assert waits[0] == 0 and waits[1] == 0  # burst
    assert waits[2] == pytest.approx(3.0) and waits[3] == pytest.approx(3.0)
    fake_clock.advance(100)
    assert bucket.acquire() == 0  # refilled


def test_rate_limits_apply_per_host_and_to_retries(fake_http: FakeHttp, fake_clock: FakeClock) -> None:
    client = HttpClient(session=fake_http, clock=fake_clock, rng=random.Random(1), backoff_base_s=0.01)
    fake_http.register("rugcheck", {"ok": 1})
    fake_http.register("dexscreener", {"ok": 1})
    t0 = fake_clock.now()
    for _ in range(3):
        client.get_json("https://api.rugcheck.xyz/v1/x")
    assert fake_clock.now() - t0 == pytest.approx(2.0)  # 1 req/s, burst 1
    t1 = fake_clock.now()
    client.get_json("https://api.dexscreener.com/a")  # other host: own bucket, no wait
    assert fake_clock.now() == t1
    # retries also consume rate tokens
    fake_http.register("rugcheck", {}, status=429, headers={"Retry-After": "0"}, times=1)
    t2 = fake_clock.now()
    client.get_json("https://api.rugcheck.xyz/v1/x")
    assert fake_clock.now() - t2 >= 1.0


def test_default_rate_table_and_from_settings(settings, fake_http: FakeHttp, fake_clock: FakeClock) -> None:
    assert DEFAULT_RATE_LIMITS["api.geckoterminal.com"][0] == pytest.approx(20 / 60)
    assert DEFAULT_RATE_LIMITS["api.rugcheck.xyz"] == (1.0, 1)
    assert DEFAULT_RATE_LIMITS["api.jup.ag"] == (1.0, 1) and DEFAULT_RATE_LIMITS["lite-api.jup.ag"] == (1.0, 1)
    assert DEFAULT_RATE_LIMITS["api.dexscreener.com"][0] == 1.0
    s = settings.replace(solana_rpc_url="https://mainnet.helius-rpc.com/?api-key=abc")
    client = HttpClient.from_settings(s, session=fake_http, clock=fake_clock)
    assert client.limiter.limits["mainnet.helius-rpc.com"] == (5.0, 5)
    assert host_of("https://API.Example.com:443/x?y=1") == "api.example.com"


def test_unlimited_when_no_default_rate(fake_clock: FakeClock) -> None:
    limiter = RateLimiter(fake_clock, limits={}, default=None)
    assert all(limiter.acquire("anything.io") == 0 for _ in range(100))
    assert fake_clock.now() == 1_791_475_200.0


def test_fake_response_passthrough(fake_http: FakeHttp, http_client: HttpClient) -> None:
    fake_http.register("custom", lambda req: FakeResponse(200, {"echo": req.params}))
    assert http_client.get_json("https://api.example.com/custom", params={"q": "z"}) == {"echo": {"q": "z"}}
