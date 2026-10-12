"""Public observation and faster market data never grant trading authority."""

from __future__ import annotations

import threading

import pytest

from nightcrawler.config import ConfigError, Settings
from nightcrawler.engine import build_app


def test_observation_defaults_leave_every_money_gate_unchanged() -> None:
    settings = Settings()
    assert settings.skipwatch_enabled and settings.speeddesk_kalshi_ws_enabled
    assert settings.skipwatch_poll_s == 2.5
    assert settings.skipwatch_max_storage_mb == 4096 and settings.skipwatch_min_free_mb == 128
    assert settings.speeddesk_kalshi_mode == settings.speeddesk_mode == "paper"
    assert settings.speeddesk_kalshi_live_confirm is None
    assert settings.speeddesk_kalshi_account_type == "unknown"
    assert (settings.speeddesk_kalshi_window_usd, settings.speeddesk_kalshi_open_usd,
            settings.speeddesk_kalshi_day_stop_usd, settings.speeddesk_kalshi_total_stop_usd) == (2, 4, 3, 5)


def test_market_stream_keys_do_not_enable_real_orders() -> None:
    settings = Settings.from_env({"SPEEDDESK_KALSHI_WS_ENABLED": "true",
                                  "KALSHI_KEY_ID": "fake-test-read-only-id",
                                  "KALSHI_PRIVATE_KEY": "fake-test-read-only-signing-material"})
    assert settings.speeddesk_kalshi_ws_enabled
    assert settings.kalshi_key_id and settings.kalshi_private_key
    assert settings.speeddesk_kalshi_mode == "paper" and settings.speeddesk_kalshi_live_confirm is None
    assert not settings.public_dict()["speeddesk_kalshi_live_confirmed"]
    assert "fake-test-read-only-signing-material" not in repr(settings)


@pytest.mark.parametrize("name,value", [
    ("skipwatch_poll_s", 1.99), ("skipwatch_poll_s", 3.01), ("skipwatch_poll_s", float("nan")),
    ("skipwatch_poll_s", True), ("skipwatch_max_storage_mb", 0), ("skipwatch_max_storage_mb", 64.5),
    ("skipwatch_max_storage_mb", 16385), ("skipwatch_min_free_mb", 0), ("skipwatch_min_free_mb", False),
    ("skipwatch_min_free_mb", "128"),
])
def test_polling_and_storage_guards_cannot_be_disabled_by_bad_settings(name, value) -> None:
    with pytest.raises(ConfigError, match=name.upper()):
        Settings(**{name: value})


def test_public_watcher_has_its_own_thread_and_shared_shutdown(make_settings, fake_clock, http_client, monkeypatch):
    from nightcrawler import skipwatch

    entered, stopped = threading.Event(), threading.Event()
    seen = []

    def observe(settings, stop):
        seen.append((settings, threading.current_thread().name))
        entered.set()
        stop.wait(2)
        if stop.is_set():
            stopped.set()

    monkeypatch.setattr(skipwatch, "run_skipwatch", observe)
    settings = make_settings(POLYDESK_ENABLED=False, TRENDDESK_ENABLED=False,
                             SPEEDDESK_ENABLED=False, SKIPWATCH_ENABLED=True)
    app = build_app(settings, fake_clock, http=http_client)
    try:
        assert entered.wait(1)
        assert app.skipwatch is not None and app.skipwatch.is_alive()
        assert app.speeddesk is None and app.polydesk is None
        assert seen == [(settings, "skipwatch")]
    finally:
        app.close()
    assert stopped.is_set() and not app.skipwatch.is_alive()


def test_disabling_observation_never_starts_its_network_worker(make_settings, fake_clock, http_client, monkeypatch):
    from nightcrawler import skipwatch

    calls = []
    monkeypatch.setattr(skipwatch, "run_skipwatch", lambda *args: calls.append(args))
    settings = make_settings(POLYDESK_ENABLED=False, TRENDDESK_ENABLED=False,
                             SPEEDDESK_ENABLED=False, SKIPWATCH_ENABLED=False)
    app = build_app(settings, fake_clock, http=http_client)
    try:
        assert app.skipwatch is None and not calls
    finally:
        app.close()
