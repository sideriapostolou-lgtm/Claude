"""Foundation tests: base58, clock, logging redaction, FakeHttp itself."""

from __future__ import annotations

import io
import json
import logging
import os
import threading

import pytest
import requests

from fakes import FakeClock, FakeHttp, FakeResponse, UnregisteredURL, load_fixture
from nightcrawler.base58 import b58decode, b58encode, is_pubkey
from nightcrawler.clock import RealClock, iso_utc, minute_floor, utc_day
from nightcrawler.logging_setup import REDACTED, get_logger, redact_text, setup_logging
from nightcrawler.models import SOL_MINT


# ----------------------------------------------------------------------------- base58
def test_base58_round_trip_and_pubkeys() -> None:
    for data in (b"", b"\0\0abc", os.urandom(32), os.urandom(64)):
        assert b58decode(b58encode(data)) == data
    assert len(b58decode(SOL_MINT)) == 32 and is_pubkey(SOL_MINT)
    assert b58encode(bytes(32)) == "1" * 32
    assert not is_pubkey("0OIl") and not is_pubkey("abc") and not is_pubkey(None)
    with pytest.raises(ValueError):
        b58decode("0")


# ----------------------------------------------------------------------------- clock
def test_fake_clock() -> None:
    c = FakeClock(100.0)
    c.sleep(5)
    c.advance(2.5)
    assert c.now() == 107.5 and c.sleeps == [5.0]
    c.set(200)
    assert c.now() == 200
    with pytest.raises(ValueError):
        c.advance(-1)
    with pytest.raises(ValueError):
        c.set(10)


def test_real_clock_sleep_is_interruptible() -> None:
    ev = threading.Event()
    clock = RealClock(ev)
    ev.set()
    t0 = clock.now()
    clock.sleep(30)  # returns immediately because the stop event is set
    assert clock.now() - t0 < 1


def test_time_helpers() -> None:
    assert utc_day(1_791_475_200.0) == "2026-10-08"
    assert iso_utc(1_791_475_200.0) == "2026-10-08T16:00:00Z" and iso_utc(None) is None
    assert minute_floor(1_791_475_259.9) == 1_791_475_200


# ----------------------------------------------------------------------------- logging
def test_redaction_of_exact_values_and_patterns() -> None:
    keygen = json.dumps(list(range(64)))
    text = f"key=SUPERSECRETVALUE anthropic=sk-ant-api03-abcdefghijk wallet={keygen} short=abc"
    out = redact_text(text, ["SUPERSECRETVALUE", "abc"])  # too-short secrets are ignored
    assert "SUPERSECRETVALUE" not in out and "sk-ant-api03" not in out and "[0, 1, 2" not in out
    assert out.count(REDACTED) == 3 and "short=abc" in out
    sig = "5" * 88  # transaction signatures stay visible
    assert redact_text(f"sig={sig}") == f"sig={sig}"


def test_setup_logging_one_line_and_redacted() -> None:
    stream = io.StringIO()
    filt = setup_logging("INFO", secrets=["TOPSECRET-123"], stream=stream)
    log = get_logger("test")
    assert log.name == "nightcrawler.test"
    log.info("hello %s", "TOPSECRET-123")
    filt.add_secret("LATER-SECRET")
    log.warning("multi\nline LATER-SECRET")
    try:
        raise ValueError("boom TOPSECRET-123")
    except ValueError:
        log.exception("failed")
    log.debug("not shown")
    lines = stream.getvalue().splitlines()
    assert len(lines) == 3, lines
    assert "TOPSECRET-123" not in stream.getvalue() and "LATER-SECRET" not in stream.getvalue()
    assert lines[0].endswith("INFO nightcrawler.test: hello [REDACTED]")
    assert "multi | line [REDACTED]" in lines[1]
    assert "ValueError: boom [REDACTED]" in lines[2]
    # idempotent: a second setup replaces our handler instead of duplicating it
    setup_logging("INFO", stream=stream)
    assert sum(getattr(h, "_nightcrawler", False) for h in logging.getLogger().handlers) == 1


# ----------------------------------------------------------------------------- FakeHttp
def test_fake_http_routes_and_calls() -> None:
    fake = FakeHttp()
    fake.register_fixture("/price/v3", "jup_price_v3")
    fake.register("/ultra/v1/order", {"taker": False})  # general route first ...
    fake.register("re:/ultra/v1/order\\?.*taker=", {"taker": True})  # ... specific route last (wins)
    r = fake.request("GET", "https://lite-api.jup.ag/price/v3", params={"ids": SOL_MINT})
    assert r.status_code == 200 and r.json()[SOL_MINT]["decimals"] == 9
    assert fake.request("GET", "https://x/ultra/v1/order", params={"amount": 1}).json() == {"taker": False}
    assert fake.request("GET", "https://x/ultra/v1/order", params={"taker": "abc"}).json() == {"taker": True}
    assert len(fake.calls_to("ultra/v1/order")) == 2 and len(fake.calls_to("re:taker=abc")) == 1
    with pytest.raises(UnregisteredURL):
        fake.request("GET", "https://nowhere.example/")
    fake.reset_calls()
    assert fake.calls == []


def test_fake_http_times_status_callables_and_errors() -> None:
    fake = FakeHttp()
    fake.register("a", {"ok": 1})
    fake.register("a", {"err": 1}, status=429, times=1)
    assert fake.request("GET", "https://h/a").status_code == 429
    assert fake.request("GET", "https://h/a").status_code == 200
    fake.register("b", lambda req: {"method": req.method, "json": req.json})
    assert fake.request("POST", "https://h/b", json={"x": 1}).json() == {"method": "POST", "json": {"x": 1}}
    fake.register("c", requests.ConnectionError("down"))
    with pytest.raises(requests.ConnectionError):
        fake.request("GET", "https://h/c")
    fake.register("d", FakeResponse(503, "busy", {"Retry-After": "2"}))
    resp = fake.request("GET", "https://h/d")
    assert resp.status_code == 503 and resp.text == "busy" and resp.headers["Retry-After"] == "2"
    fake.register("e", {"only": "post"}, method="POST")
    with pytest.raises(UnregisteredURL):
        fake.request("GET", "https://h/e")


def test_all_fixtures_are_valid_json() -> None:
    from fakes import FIXTURES_DIR

    names = sorted(p.name for p in FIXTURES_DIR.glob("*.json"))
    assert len(names) >= 40
    for name in names:
        load_fixture(name)


def test_network_is_blocked_offline() -> None:
    with pytest.raises(RuntimeError, match="network access blocked"):
        requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=1)
