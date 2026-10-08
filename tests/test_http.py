"""Foundation tests: HttpClient retries, backoff, Retry-After, rate limits, errors."""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from fakes import FakeClock, FakeHttp, FakeResponse
from nightcrawler.http import (
    DEFAULT_RATE_LIMITS,
    KV_USAGE,
    PROVIDERS,
    USAGE_FLUSH_EVERY_S,
    HttpClient,
    HttpError,
    RateLimiter,
    TokenBucket,
    UsageTracker,
    anthropic_usage_counts,
    attach_usage_store,
    flush_usage,
    host_of,
    provider_of,
    record_usage,
)
from nightcrawler.ledger import Ledger

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


def test_retry_after_zero_still_backs_off(fake_http: FakeHttp, fake_clock: FakeClock) -> None:
    """GeckoTerminal answers 429 with ``Retry-After: 0``; that must not cause back-to-back retries."""
    client = make_client(fake_http, fake_clock)
    fake_http.register("thing", {"ok": 1})
    fake_http.register("thing", {}, status=429, headers={"Retry-After": "0"}, times=2)
    assert client.get_json(URL) == {"ok": 1}
    assert len(fake_clock.sleeps) == 2
    assert 0.5 <= fake_clock.sleeps[0] <= 1.0  # exponential backoff, not 0
    assert 1.0 <= fake_clock.sleeps[1] <= 2.0


def test_host_max_retries_overrides_the_default_per_host(fake_http: FakeHttp, fake_clock: FakeClock) -> None:
    client = make_client(fake_http, fake_clock, host_max_retries={"api.example.com": 1})
    fake_http.register("thing", {"error": "slow down"}, status=429)
    with pytest.raises(HttpError):
        client.get_json(URL)
    assert len(fake_http.calls) == 2  # 1 attempt + 1 retry, not 1 + 4
    fake_http.register("other.example.org", {"error": "down"}, status=503)
    with pytest.raises(HttpError):
        client.get_json("https://other.example.org/x")
    assert len(fake_http.calls) == 2 + 5  # other hosts keep max_retries=4


# --------------------------------------------------------------------------- provider usage

KEY = "helius-secret-key-0123456789abcdef"


@pytest.fixture
def usage_ledger(tmp_path: Path, fake_clock: FakeClock) -> Ledger:
    with Ledger(tmp_path / "nc.db", clock=fake_clock) as led:
        yield led


def test_provider_of_maps_hosts_to_the_providers_on_the_usage_panel() -> None:
    cases = {"mainnet.helius-rpc.com": "helius", "api.helius.xyz": "helius", "lite-api.jup.ag": "jupiter",
             "api.jup.ag": "jupiter", "api.geckoterminal.com": "geckoterminal", "api.dexscreener.com": "dexscreener",
             "api.rugcheck.xyz": "rugcheck", "frontend-api-v3.pump.fun": "pumpfun", "api.anthropic.com": "anthropic",
             "api.mainnet-beta.solana.com": "solana_rpc", "example.com": "other", "notjup.ag": "other",
             "evil-helius-rpc.com": "other"}
    for host, provider in cases.items():
        assert provider_of(host) == provider, host
    assert provider_of("my-node.quiknode.pro", rpc_host="my-node.quiknode.pro") == "solana_rpc"
    assert provider_of("mainnet.helius-rpc.com", rpc_host="mainnet.helius-rpc.com") == "helius"
    assert set(cases.values()) <= set(PROVIDERS)


def test_every_attempt_is_counted_per_provider_utc_day_and_month(settings, fake_http: FakeHttp,
                                                                 fake_clock: FakeClock, usage_ledger: Ledger) -> None:
    s = settings.replace(solana_rpc_url=f"https://mainnet.helius-rpc.com/?api-key={KEY}")
    client = HttpClient.from_settings(s, session=fake_http, clock=fake_clock, rate_limits={}, default_rate=None,
                                      rng=random.Random(0))
    fake_http.register("helius-rpc.com", {"jsonrpc": "2.0", "result": 1})
    fake_http.register("lite-api.jup.ag", {"ok": 1})
    fake_http.register("geckoterminal", {"ok": 1})
    fake_http.register("geckoterminal", {}, status=429, times=1)
    client.post_json(s.solana_rpc_url, {"method": "getSlot"})
    client.post_json(s.solana_rpc_url, {"method": "getSlot"})
    client.get_json("https://lite-api.jup.ag/tokens/v2/recent")
    client.get_json("https://api.geckoterminal.com/api/v2/x")  # a 429 and its retry: two calls on the quota
    attach_usage_store(client, usage_ledger)  # counted before the ledger existed: nothing is lost
    assert client.usage.flush()
    stored = usage_ledger.get_kv(KV_USAGE)
    helius = stored["helius"]
    assert (helius["day"], helius["month"]) == ("2026-10-08", "2026-10")
    assert helius["day_counts"] == helius["month_counts"] == {"calls": 2, "credits": 2}  # 1 credit per RPC call
    assert stored["jupiter"]["day_counts"] == {"calls": 1}
    assert stored["geckoterminal"]["month_counts"] == {"calls": 2}
    text = json.dumps(stored)
    assert KEY not in text and "http" not in text and "helius-rpc.com" not in text  # provider names only


def test_usage_is_written_at_most_once_a_minute(fake_http: FakeHttp, fake_clock: FakeClock,
                                                 usage_ledger: Ledger) -> None:
    client = make_client(fake_http, fake_clock)
    attach_usage_store(client, usage_ledger)
    fake_http.register("dexscreener", {"ok": 1})
    client.get_json("https://api.dexscreener.com/latest/dex/tokens/x")  # first call after binding: written
    assert usage_ledger.get_kv(KV_USAGE)["dexscreener"]["day_counts"] == {"calls": 1}
    fake_clock.advance(30)
    client.get_json("https://api.dexscreener.com/latest/dex/tokens/x")
    assert usage_ledger.get_kv(KV_USAGE)["dexscreener"]["day_counts"] == {"calls": 1}  # pending in memory
    fake_clock.advance(USAGE_FLUSH_EVERY_S)
    client.get_json("https://api.dexscreener.com/latest/dex/tokens/x")
    assert usage_ledger.get_kv(KV_USAGE)["dexscreener"]["day_counts"] == {"calls": 3}


def test_flush_usage_writes_the_last_counts_at_shutdown(fake_http: FakeHttp, fake_clock: FakeClock,
                                                        usage_ledger: Ledger) -> None:
    client = make_client(fake_http, fake_clock)
    attach_usage_store(client, usage_ledger)
    fake_http.register("rugcheck", {"ok": 1})
    client.get_json("https://api.rugcheck.xyz/v1/tokens/x/report")
    fake_clock.advance(10)
    client.get_json("https://api.rugcheck.xyz/v1/tokens/x/report")  # pending: the minute is not over
    assert usage_ledger.get_kv(KV_USAGE)["rugcheck"]["day_counts"] == {"calls": 1}
    assert flush_usage(client) is True
    assert usage_ledger.get_kv(KV_USAGE)["rugcheck"]["day_counts"] == {"calls": 2}
    assert flush_usage(object()) is False  # a test double without usage tracking


def test_usage_rolls_over_at_utc_midnight_and_at_the_month_end(fake_clock: FakeClock, usage_ledger: Ledger) -> None:
    fake_clock.set(datetime(2026, 10, 31, 23, 59, tzinfo=timezone.utc).timestamp())
    tracker = UsageTracker(fake_clock, usage_ledger)
    tracker.record("jupiter")
    tracker.record("jupiter")
    assert tracker.flush()
    fake_clock.advance(120)  # 2026-11-01 00:01 UTC
    tracker.record("jupiter")
    assert tracker.flush()
    j = usage_ledger.get_kv(KV_USAGE)["jupiter"]
    assert (j["day"], j["day_counts"], j["month"], j["month_counts"]) == (
        "2026-11-01", {"calls": 1}, "2026-11", {"calls": 1})
    fake_clock.advance(86_400)  # next day, same month: the day starts over, the month keeps counting
    tracker.record("jupiter")
    assert tracker.flush()
    j = usage_ledger.get_kv(KV_USAGE)["jupiter"]
    assert (j["day"], j["day_counts"], j["month_counts"]) == ("2026-11-02", {"calls": 1}, {"calls": 2})


def test_counts_of_several_processes_add_up_instead_of_overwriting(fake_clock: FakeClock,
                                                                   usage_ledger: Ledger) -> None:
    bot, cli = UsageTracker(fake_clock, usage_ledger), UsageTracker(fake_clock, usage_ledger)
    for _ in range(3):
        bot.record("rugcheck")
    cli.record("rugcheck")
    cli.record("geckoterminal")
    late = UsageTracker(fake_clock, usage_ledger)
    late.record("rugcheck")  # recorded on 2026-10-08, flushed after midnight
    assert bot.flush() and cli.flush()
    stored = usage_ledger.get_kv(KV_USAGE)
    assert stored["rugcheck"]["day_counts"] == {"calls": 4} and stored["geckoterminal"]["day_counts"] == {"calls": 1}
    fake_clock.advance(86_400)
    bot.record("rugcheck")
    assert bot.flush() and late.flush()
    rugcheck = usage_ledger.get_kv(KV_USAGE)["rugcheck"]
    assert (rugcheck["day"], rugcheck["day_counts"]) == ("2026-10-09", {"calls": 1})  # yesterday's late count
    assert rugcheck["month_counts"] == {"calls": 6}  # ... still belongs to the month


def test_a_failing_store_never_breaks_a_request_and_loses_no_counts(fake_http: FakeHttp, fake_clock: FakeClock,
                                                                    usage_ledger: Ledger) -> None:
    class BrokenStore:
        def get_kv(self, key: str, default: object = None) -> object:
            raise RuntimeError("disk full")

        def set_kv(self, key: str, value: object) -> None:
            raise RuntimeError("disk full")

    client = make_client(fake_http, fake_clock)
    attach_usage_store(client, BrokenStore())
    fake_http.register("rugcheck", {"ok": 1})
    assert client.get_json("https://api.rugcheck.xyz/v1/tokens/x/report") == {"ok": 1}
    assert client.usage.flush() is False
    client.usage.bind(usage_ledger)
    assert client.usage.flush()
    assert usage_ledger.get_kv(KV_USAGE)["rugcheck"]["day_counts"] == {"calls": 1}
    attach_usage_store(object(), usage_ledger)  # a client without usage tracking: nothing to do


def test_judge_hook_counts_anthropic_calls_tokens_and_cost(fake_clock: FakeClock, usage_ledger: Ledger) -> None:
    usage = {"input_tokens": 1200, "cache_read_input_tokens": 800, "cache_creation_input_tokens": 0,
             "output_tokens": 90}
    counts = anthropic_usage_counts(usage, 0.0123)
    assert counts == {"calls": 1, "input_tokens": 2000, "output_tokens": 90, "cost_usd": 0.0123}
    record_usage(usage_ledger, "anthropic", fake_clock.now(), **counts)
    record_usage(usage_ledger, "anthropic", fake_clock.now(), **anthropic_usage_counts(None, 0.0))  # API error
    anthropic = usage_ledger.get_kv(KV_USAGE)["anthropic"]
    assert anthropic["day_counts"] == anthropic["month_counts"] == {
        "calls": 2, "input_tokens": 2000, "output_tokens": 90, "cost_usd": 0.0123}

    class SdkUsage:  # the SDK's usage object: attributes, some None
        input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens = 5, 7, None, 3

    assert anthropic_usage_counts(SdkUsage(), 0.5) == {"calls": 1, "input_tokens": 8, "output_tokens": 7,
                                                       "cost_usd": 0.5}
    record_usage(None, "anthropic", fake_clock.now(), calls=1)  # no ledger: nothing to do, never raises

    class BrokenStore:
        def get_kv(self, key: str, default: object = None) -> object:
            raise RuntimeError("locked")

    record_usage(BrokenStore(), "anthropic", fake_clock.now(), calls=1)  # logged, never raised
