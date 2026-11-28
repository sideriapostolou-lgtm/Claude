"""Shared pytest fixtures. Tests are OFFLINE by default.

* Real network through ``requests`` is blocked in every test not marked
  ``@pytest.mark.live`` (raises ``RuntimeError``).
* ``@pytest.mark.live`` tests are skipped unless ``NIGHTCRAWLER_LIVE_TESTS=1``.

Fixtures: ``fixtures_dir``, ``load_fixture``, ``fake_clock``, ``fake_http``,
``http_client`` (real HttpClient over FakeHttp + FakeClock, no rate limits,
seeded jitter), ``tmp_data_dir``, ``make_settings`` (factory), ``settings``.
"""

from __future__ import annotations

import os
import random
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import requests
from fakes import FIXTURES_DIR, FakeClock, FakeHttp
from fakes import load_fixture as _load_fixture

from nightcrawler.config import Settings
from nightcrawler.http import HttpClient

#: 2026-10-08T16:00:00Z - shortly after the fixtures were captured (~15:30-15:45Z).
FIXED_NOW = 1_791_475_200.0


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("NIGHTCRAWLER_LIVE_TESTS") == "1":
        return
    skip_live = pytest.mark.skip(reason="live network test; set NIGHTCRAWLER_LIVE_TESTS=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture(autouse=True)
def _block_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("live"):
        return

    def _blocked(self: Any, method: str, url: str, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(f"network access blocked in offline tests: {method} {url}")

    monkeypatch.setattr(requests.Session, "request", _blocked)


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def load_fixture() -> Callable[[str], Any]:
    return _load_fixture


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock(FIXED_NOW)


@pytest.fixture
def fake_http() -> FakeHttp:
    return FakeHttp()


@pytest.fixture
def http_client(fake_http: FakeHttp, fake_clock: FakeClock) -> HttpClient:
    """Real HttpClient over FakeHttp: no rate limiting, deterministic jitter, instant sleeps."""
    return HttpClient(session=fake_http, clock=fake_clock, rate_limits={}, default_rate=None,
                      rng=random.Random(0))


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def make_settings(tmp_data_dir: Path) -> Callable[..., Settings]:
    """Factory: ``make_settings(position_pct=0.1, TRADING_MODE="paper", ...)``.

    Keys may be attribute names or ENV names; values may be native types or
    strings. ``DATA_DIR`` defaults to the per-test temp dir. Never reads os.environ.
    """

    def _make(**overrides: Any) -> Settings:
        env: dict[str, str] = {"DATA_DIR": str(tmp_data_dir)}
        for key, value in overrides.items():
            if value is None:
                continue
            if isinstance(value, bool):
                value = "true" if value else "false"
            env[key.upper()] = str(value)
        return Settings.from_env(env)

    return _make


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings()


@pytest.fixture(autouse=True)
def _offline_speeddesk(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Default-enabled practice streams never escape a wiring test onto a real network."""
    if request.node.get_closest_marker("live"):
        return
    from nightcrawler import speeddesk

    monkeypatch.setattr(speeddesk, "run_speeddesk", lambda settings, stop_event: None)


@pytest.fixture(autouse=True)
def _offline_skipwatch(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Engine tests never start real public sockets; observer tests inject fake transports directly."""
    if request.node.get_closest_marker("live"):
        return
    from nightcrawler import skipwatch

    monkeypatch.setattr(skipwatch, "run_skipwatch", lambda settings, stop_event: None)


@pytest.fixture(autouse=True)
def _offline_weatherwatch(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Default-enabled weather capture is replaced before any offline engine test starts it."""
    if request.node.get_closest_marker("live"):
        return
    from nightcrawler import weatherwatch

    monkeypatch.setattr(weatherwatch, "run_weatherwatch", lambda settings, stop_event: None)


@pytest.fixture(autouse=True)
def _bitcoin_far_from_the_line(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Offline tests of the Polymarket desk see Bitcoin far from every line (the distance check passes), so they
    keep testing the rest of the rule; tests/test_btcdistance.py tests the check itself."""
    if request.module.__name__.endswith("test_btcdistance"):
        return
    from nightcrawler import btcdistance

    monkeypatch.setattr(btcdistance.Distance, "check", lambda self, slug, end_ts, now=None, price=None: (99.0, None))
