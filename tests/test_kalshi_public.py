"""The shared public request budget and the GET transport (PROTOCOL.md section 3, rate limits)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from email.utils import format_datetime
from itertools import pairwise
from typing import Any

import pytest
from kalshi_recorder_fixtures import Clock, FakeResponse

from nightcrawler.kalshi_public import (
    MAX_RETRY_AFTER_S,
    PublicKalshi,
    RateLimiter,
    public_ticker,
    retry_after_seconds,
)


def starts(limiter: RateLimiter, clock: Clock, count: int) -> list[float]:
    out = []
    for _ in range(count):
        limiter.wait()
        out.append(clock.at)
    return out


def test_ceiling_is_two_per_second_and_cannot_be_raised() -> None:
    with pytest.raises(ValueError):
        RateLimiter(2.5)
    with pytest.raises(ValueError):
        RateLimiter(1.0, ceiling_per_s=3.0)
    with pytest.raises(ValueError):
        RateLimiter(0.0)


def test_starts_are_spaced_at_the_target_and_never_exceed_two_in_a_rolling_second() -> None:
    clock = Clock(1000.0)
    limiter = RateLimiter(1.5, clock=clock.mono, sleep=clock.sleep)
    times = starts(limiter, clock, 30)
    gaps = [later - earlier for earlier, later in pairwise(times)]
    assert all(gap >= 1 / 1.5 - 1e-9 for gap in gaps)
    assert all(sum(1 for other in times if at - 1.0 < other <= at) <= 2 for at in times)
    assert times[-1] - times[0] == pytest.approx(29 / 1.5)


def test_full_two_per_second_still_respects_the_rolling_window() -> None:
    clock = Clock(0.0)
    limiter = RateLimiter(2.0, clock=clock.mono, sleep=clock.sleep)
    times = starts(limiter, clock, 21)
    assert all(sum(1 for other in times if at - 1.0 < other <= at) <= 2 for at in times)
    assert times[-1] - times[0] == pytest.approx(10.0)


def test_a_429_slows_everyone_by_a_quarter_for_ten_minutes_and_honours_retry_after() -> None:
    clock = Clock(0.0)
    limiter = RateLimiter(1.5, clock=clock.mono, sleep=clock.sleep)
    limiter.wait()
    limiter.penalize(retry_after_s=5.0)
    assert limiter.rate() == pytest.approx(1.125)
    limiter.wait()
    assert clock.at == pytest.approx(5.0)  # the Retry-After holds every lane
    first = clock.at
    limiter.wait()
    assert clock.at - first == pytest.approx(1 / 1.125)
    clock.at = 601.0
    assert limiter.rate() == pytest.approx(1.5)  # the cut lasts ten minutes, then the target returns


def test_retry_after_accepts_seconds_and_http_dates() -> None:
    now = datetime(2026, 10, 13, 18, 0, tzinfo=UTC).timestamp()
    assert retry_after_seconds("7", now) == 7.0
    assert retry_after_seconds(format_datetime(datetime(2026, 10, 13, 18, 0, 30, tzinfo=UTC), usegmt=True), now) == 30.0
    assert retry_after_seconds("soon", now) is None
    assert retry_after_seconds(None, now) is None
    assert retry_after_seconds("-3", now) == 0.0


class Session:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.kwargs = {"url": url, **kwargs}
        return self.response


def client(response: FakeResponse, **kwargs: Any) -> tuple[PublicKalshi, Session, Clock]:
    clock = Clock(100.0)
    session = Session(response)
    return PublicKalshi(RateLimiter(2.0, clock=clock.mono, sleep=clock.sleep), session=session, wall=clock.wall,
                        mono=clock.mono, **kwargs), session, clock


def test_a_200_records_times_bytes_hash_and_the_body() -> None:
    body = {"orderbooks": []}
    transport, session, _ = client(FakeResponse(200, body))
    fetched = transport.get("books", "/markets/orderbooks", [("tickers", "A"), ("tickers", "B")])
    assert fetched.ok and fetched.body == body and fetched.nbytes == len(json.dumps(body))
    assert fetched.sha256 and len(fetched.sha256) == 64 and fetched.requested_at <= fetched.received_at
    assert session.kwargs["allow_redirects"] is False and session.kwargs["params"] == [("tickers", "A"), ("tickers", "B")]
    assert "Authorization" not in session.kwargs["headers"]
    row = fetched.log_row()
    assert row["status"] == 200 and row["path"] == "/markets/orderbooks" and row["query"] == [["tickers", "A"],
                                                                                              ["tickers", "B"]]


def test_a_429_penalizes_the_shared_budget_and_carries_retry_after() -> None:
    transport, _, _ = client(FakeResponse(429, {"error": "too many"}, {"Retry-After": "3"}))
    fetched = transport.get("trades", "/markets/trades", {"limit": 1000})
    assert not fetched.ok and fetched.status == 429 and fetched.retry_after_s == 3.0
    assert transport.limiter.rate() == pytest.approx(1.5)


def test_redirects_oversize_bodies_and_bad_json_are_failures_not_data() -> None:
    transport, _, _ = client(FakeResponse(302, b""))
    assert transport.get("x", "/events").error == "redirect_refused"
    transport, _, _ = client(FakeResponse(200, b"x" * 2048), max_bytes=1024)
    assert transport.get("x", "/events").error == "ValueError"
    transport, _, _ = client(FakeResponse(200, b"not json"))
    assert transport.get("x", "/events").error == "invalid_json"
    transport, _, _ = client(FakeResponse(200, b"[1, 2]"))
    fetched = transport.get("x", "/events")
    assert fetched.error == "not_an_object" and fetched.body is None


def test_json_with_nan_infinity_or_absurd_nesting_is_a_failed_request_never_a_record() -> None:
    """Review F1: a NaN in a reply used to reach the store (allow_nan=False) and halt the recorder."""
    for raw in (b'{"trades":[{"count_fp":NaN}]}', b'{"a":Infinity}', b'{"a":-Infinity}', b"[" * 100_000 + b"]" * 100_000):
        transport, _, _ = client(FakeResponse(200, raw))
        fetched = transport.get("x", "/markets/trades")
        assert fetched.error == "invalid_json" and fetched.body is None and not fetched.ok


def test_a_huge_retry_after_is_clamped_to_fifteen_minutes() -> None:
    """Review F8: a one-year Retry-After froze every lane with no gap."""
    now = datetime(2026, 10, 13, 18, 0, tzinfo=UTC).timestamp()
    assert retry_after_seconds("31536000", now) == MAX_RETRY_AFTER_S == 900.0
    clock = Clock(0.0)
    limiter = RateLimiter(1.5, clock=clock.mono, sleep=clock.sleep)
    limiter.penalize(retry_after_s=31_536_000.0)
    limiter.wait()
    assert clock.at == pytest.approx(900.0)


def test_public_tickers_are_the_ones_a_public_path_may_carry() -> None:
    assert public_ticker("KXHIGHNY") and public_ticker("KXBTCD-26OCT1617-T112499.99")
    assert not public_ticker("kxweird") and not public_ticker("") and not public_ticker(1.5)
    assert not public_ticker("KX/../portfolio")


def test_a_burst_of_two_keeps_the_average_and_the_ceiling_but_allows_half_second_gaps() -> None:
    """The LIP lane's budget: two tokens, so a 1 s call and the other lanes can interleave at 0.5 s."""
    clock = Clock(0.0)
    limiter = RateLimiter(1.5, burst=2.0, clock=clock.mono, sleep=clock.sleep)
    times = starts(limiter, clock, 301)
    gaps = [later - earlier for earlier, later in pairwise(times)]
    assert min(gaps) >= 0.5 - 1e-9 and gaps[0] == pytest.approx(0.5)  # the burst: never closer than 1/ceiling
    assert all(sum(1 for other in times if at - 1.0 < other <= at) <= 2 for at in times)
    assert (len(times) - 2) / (times[-1] - times[0]) == pytest.approx(1.5, rel=0.01)  # the average is the target
    with pytest.raises(ValueError):
        RateLimiter(1.5, burst=0.5)
    with pytest.raises(ValueError):
        RateLimiter(1.5, burst=3.0)


def test_delays_says_when_the_next_two_requests_may_start() -> None:
    clock = Clock(100.0)
    limiter = RateLimiter(1.5, burst=2.0, clock=clock.mono, sleep=clock.sleep)
    assert limiter.delays() == (0.0, pytest.approx(0.5))  # a full bucket: now, then 0.5 s later
    limiter.wait()
    limiter.wait()  # two starts 0.5 s apart (at 100.0 and 100.5); 0.75 of a token is left
    first, second = limiter.delays()
    assert first == pytest.approx(0.5)  # 101.0: the rolling second and the spacing allow it, and tokens suffice
    assert second == pytest.approx(1.0)  # 101.5: the rolling second binds (the bucket would allow 101.33)
    single = RateLimiter(1.5, clock=clock.mono, sleep=clock.sleep)
    single.wait()
    assert single.delays() == (pytest.approx(1 / 1.5), pytest.approx(2 / 1.5))  # burst 1: plain target spacing
