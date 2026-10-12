"""Weather observation cannot grant trading authority or interfere with another desk."""

from __future__ import annotations

import threading
from dataclasses import fields
from types import SimpleNamespace

import pytest

from nightcrawler.config import ConfigError, Settings
from nightcrawler.engine import build_app


def test_weather_settings_only_add_observation_and_preserve_financial_defaults() -> None:
    settings = Settings()
    disabled = Settings(weatherwatch_enabled=False)
    for field in fields(settings):
        if not field.name.startswith("weatherwatch_"):
            assert getattr(settings, field.name) == getattr(disabled, field.name)
    assert settings.weatherwatch_enabled
    assert settings.weatherwatch_max_storage_mb == 512
    assert settings.weatherwatch_min_free_mb == 128
    assert settings.weatherwatch_retention_days == 7
    assert settings.weatherwatch_discovery_s == 300
    assert settings.weatherwatch_max_active_watches == 20
    assert settings.trading_mode == settings.polydesk_mode == settings.speeddesk_kalshi_mode == "paper"
    assert settings.speeddesk_kalshi_live_confirm is None
    assert (settings.speeddesk_kalshi_window_usd, settings.speeddesk_kalshi_open_usd,
            settings.speeddesk_kalshi_day_stop_usd, settings.speeddesk_kalshi_total_stop_usd) == (2, 4, 3, 5)


def test_weather_settings_and_read_only_stream_credentials_do_not_enable_orders() -> None:
    settings = Settings.from_env({"WEATHERWATCH_ENABLED": "true", "WEATHERWATCH_RETENTION_DAYS": "4",
                                  "KALSHI_KEY_ID": "fake-weather-readonly-test-id",
                                  "KALSHI_PRIVATE_KEY": "fake-weather-readonly-test-material"})
    assert settings.weatherwatch_retention_days == 4
    assert settings.speeddesk_kalshi_mode == settings.polydesk_mode == "paper"
    assert not settings.public_dict()["speeddesk_kalshi_live_confirmed"]
    assert not any(field.name.startswith("weatherwatch_") and "live" in field.name for field in fields(settings))
    assert "fake-weather-readonly-test-material" not in repr(settings)


@pytest.mark.parametrize("name,value", [
    ("weatherwatch_enabled", "true"), ("weatherwatch_enabled", 1),
    ("weatherwatch_max_storage_mb", 63), ("weatherwatch_max_storage_mb", 4097),
    ("weatherwatch_max_storage_mb", 512.0), ("weatherwatch_min_free_mb", False),
    ("weatherwatch_min_free_mb", 0), ("weatherwatch_retention_days", 3),
    ("weatherwatch_retention_days", 32), ("weatherwatch_retention_days", 7.5),
    ("weatherwatch_discovery_s", float("nan")), ("weatherwatch_discovery_s", float("inf")),
    ("weatherwatch_discovery_s", True), ("weatherwatch_discovery_s", 59),
    ("weatherwatch_max_active_watches", 0), ("weatherwatch_max_active_watches", 101),
    ("weatherwatch_max_active_watches", "20"),
])
def test_weather_resource_guards_cannot_be_disabled_by_invalid_settings(name, value) -> None:
    with pytest.raises(ConfigError, match=name.upper()):
        Settings(**{name: value})


def test_weather_observer_owns_thread_and_uses_shared_shutdown(make_settings, fake_clock, http_client, monkeypatch):
    from nightcrawler import weatherwatch

    entered, stopped = threading.Event(), threading.Event()
    calls = []

    def observe(settings, stop):
        calls.append((settings, threading.current_thread().name))
        entered.set()
        stop.wait(2)
        if stop.is_set():
            stopped.set()

    monkeypatch.setattr(weatherwatch, "run_weatherwatch", observe)
    settings = make_settings(POLYDESK_ENABLED=False, TRENDDESK_ENABLED=False, SPEEDDESK_ENABLED=False,
                             SKIPWATCH_ENABLED=False, WEATHERWATCH_ENABLED=True)
    app = build_app(settings, fake_clock, http=http_client)
    try:
        assert entered.wait(1)
        assert app.weatherwatch is not None and app.weatherwatch.is_alive()
        assert app.polydesk is None and app.speeddesk is None and app.skipwatch is None
        assert calls == [(settings, "weatherwatch")]
    finally:
        app.close()
    assert stopped.is_set() and not app.weatherwatch.is_alive()


def test_weather_disabled_never_starts_network_worker(make_settings, fake_clock, http_client, monkeypatch):
    from nightcrawler import weatherwatch

    calls = []
    monkeypatch.setattr(weatherwatch, "run_weatherwatch", lambda *args: calls.append(args))
    settings = make_settings(POLYDESK_ENABLED=False, TRENDDESK_ENABLED=False, SPEEDDESK_ENABLED=False,
                             SKIPWATCH_ENABLED=False, WEATHERWATCH_ENABLED=False)
    app = build_app(settings, fake_clock, http=http_client)
    try:
        assert app.weatherwatch is None and not calls
    finally:
        app.close()


def test_weather_join_cannot_delay_existing_desk_shutdown(make_settings, fake_clock, http_client):
    settings = make_settings(POLYDESK_ENABLED=False, TRENDDESK_ENABLED=False, SPEEDDESK_ENABLED=False,
                             SKIPWATCH_ENABLED=False, WEATHERWATCH_ENABLED=False)
    app = build_app(settings, fake_clock, http=http_client)
    stopped = []
    existing = ("polydesk", "trenddesk", "marcodesk", "nhldesk", "arena", "dashboard")
    for name in existing:
        setattr(app, name, SimpleNamespace(stop=lambda desk=name: stopped.append(desk)))
    app.weatherwatch = SimpleNamespace(join=lambda timeout: stopped.append(("weatherwatch", timeout)))
    app.close()
    assert stopped == [*existing, ("weatherwatch", 1)]
