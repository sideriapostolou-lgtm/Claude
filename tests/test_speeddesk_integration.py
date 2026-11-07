"""Practice-only settings, thread lifecycle and page isolation for the speed desk."""

from __future__ import annotations

import dataclasses
import threading

import pytest

from nightcrawler import pagestate, speeddesk
from nightcrawler.clock import utc_day
from nightcrawler.config import ConfigError, Settings
from nightcrawler.engine import build_app
from nightcrawler.ledger import Ledger
from nightcrawler.page import render_page_html


def report(now: float) -> dict:
    return {
        "as_of": now, "status": "Practice feeds connected", "problem": None,
        "btc_age_s": 0.5, "book_age_s": 1.0,
        "today": {"day": utc_day(now), "windows": 3, "settled_windows": 2, "fills": 5, "locked_usd": 0.25,
                  "directional_usd": -0.10, "pnl_usd": 0.15, "won": 1, "lost": 1,
                  "worst_usd": -0.10, "take_attempts": 4, "take_fills": 2,
                  "maker_orders": 5, "maker_fills": 3, "avg_latency_ms": 260.0},
    }


def test_defaults_are_independent_practice_settings() -> None:
    settings = Settings()
    assert settings.speeddesk_enabled
    assert settings.speeddesk_kalshi_enabled
    assert settings.speeddesk_mode == "paper"
    assert (settings.speeddesk_window_usd, settings.speeddesk_open_usd, settings.speeddesk_day_stop_usd) == (20, 20, 10)
    assert (settings.speeddesk_take_edge, settings.speeddesk_make_edge, settings.speeddesk_pair_cap) == (.02, .03, .99)
    assert (settings.speeddesk_max_imbalance, settings.speeddesk_clip) == (.25, 25)
    assert (settings.speeddesk_cutoff_s, settings.speeddesk_latency_ms) == (60, 250)
    assert not settings.marco_real
    assert settings.polydesk_mode == "paper"
    assert settings.polydesk_live_contracts == 1
    assert settings.polydesk_live_max_open_usd == 10


def test_kalshi_practice_adapter_switch_is_independent() -> None:
    settings = Settings.from_env({"SPEEDDESK_KALSHI_ENABLED": "false"})
    assert not settings.speeddesk_kalshi_enabled
    assert settings.speeddesk_enabled and settings.speeddesk_mode == "paper"
    assert settings.polydesk_mode == "paper" and not settings.marco_real


def test_live_speeddesk_mode_is_rejected_from_env_and_direct_construction() -> None:
    with pytest.raises(ConfigError, match="SPEEDDESK_MODE"):
        Settings.from_env({"SPEEDDESK_MODE": "live"})
    with pytest.raises(ConfigError, match="SPEEDDESK_MODE"):
        Settings(speeddesk_mode="live")


@pytest.mark.parametrize("field,value", [
    ("speeddesk_window_usd", 0), ("speeddesk_open_usd", -1), ("speeddesk_day_stop_usd", 0),
    ("speeddesk_take_edge", -0.01), ("speeddesk_make_edge", 1.01), ("speeddesk_pair_cap", 1.01),
    ("speeddesk_max_imbalance", -0.01), ("speeddesk_clip", 0),
    ("speeddesk_cutoff_s", 900), ("speeddesk_latency_ms", 0),
    ("speeddesk_open_usd", float("nan")), ("speeddesk_clip", float("inf")),
])
def test_invalid_practice_limits_cannot_disable_guards(field: str, value: float) -> None:
    with pytest.raises(ConfigError, match=field.upper()):
        dataclasses.replace(Settings(), **{field: value})


def test_speeddesk_thread_starts_and_stops_independently(make_settings, fake_clock, http_client, monkeypatch) -> None:
    entered = threading.Event()
    stopped = threading.Event()
    seen = []

    def run(settings, stop_event):
        seen.append((settings, stop_event, threading.current_thread().name))
        entered.set()
        stop_event.wait(2)
        if stop_event.is_set():
            stopped.set()

    monkeypatch.setattr(speeddesk, "run_speeddesk", run)
    settings = make_settings(POLYDESK_ENABLED=False, TRENDDESK_ENABLED=False, SPEEDDESK_ENABLED=True)
    app = build_app(settings, fake_clock, http=http_client)
    try:
        assert entered.wait(1)
        assert app.speeddesk is not None and app.speeddesk.is_alive()
        assert seen == [(settings, app.stop_event, "speeddesk")]
        assert app.polydesk is None
    finally:
        app.close()
    assert stopped.is_set()
    assert not app.speeddesk.is_alive()


def test_disabled_speeddesk_never_starts_a_thread(make_settings, fake_clock, http_client, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(speeddesk, "run_speeddesk", lambda *args: calls.append(args))
    app = build_app(make_settings(POLYDESK_ENABLED=False, TRENDDESK_ENABLED=False, SPEEDDESK_ENABLED=False),
                    fake_clock, http=http_client)
    try:
        assert app.speeddesk is None
        assert calls == []
    finally:
        app.close()


def test_practice_report_rates_and_unknowns_are_honest(make_settings, fake_clock, monkeypatch) -> None:
    now = fake_clock.now()
    raw = report(now)
    raw.update(mode="live", label="REAL MONEY")
    monkeypatch.setattr(speeddesk, "panel_state", lambda *args: raw)
    panel = pagestate.speed_desk(make_settings(), now)
    assert panel["mode"] == "paper" and panel["label"] == "PRACTICE (pretend money)"
    assert not panel["stale"]
    today = panel["today"]
    assert (today["windows"], today["settled_windows"]) == (3, 2)
    assert today["take_fill_rate_pct"] == 50
    assert today["maker_fill_rate_pct"] == 60
    assert today["locked_usd"] + today["directional_usd"] == pytest.approx(today["pnl_usd"])
    assert "PRACTICE" in pagestate.speed_line(panel)
    assert "UTC" in pagestate.speed_line(panel)
    raw["today"] = {"day": utc_day(now), "windows": 0, "pnl_usd": 0, "take_attempts": 0, "take_fills": 0}
    missing = pagestate.speed_desk(make_settings(), now)["today"]
    assert missing["fills"] is None and missing["worst_usd"] is None
    assert missing["take_fill_rate_pct"] is None
    assert "waiting" in pagestate.speed_line(pagestate.speed_desk(make_settings(), now))


def test_broken_or_stale_report_is_visible_without_invented_profit(make_settings, fake_clock, monkeypatch) -> None:
    now = fake_clock.now()

    def unreadable(*args):
        raise OSError("missing")

    monkeypatch.setattr(speeddesk, "panel_state", unreadable)
    panel = pagestate.speed_desk(make_settings(), now)
    assert panel["stale"] and panel["problem"] == "Practice report unavailable"
    assert panel["today"]["pnl_usd"] is None
    raw = report(now - 61)
    monkeypatch.setattr(speeddesk, "panel_state", lambda *args: raw)
    assert pagestate.speed_desk(make_settings(), now)["stale"]
    assert pagestate.speed_desk(make_settings(SPEEDDESK_ENABLED=False), now) is None


def test_saved_previous_day_is_not_relabelled_as_today(make_settings, fake_clock, monkeypatch) -> None:
    now = fake_clock.now()
    raw = report(now - 86_400)
    monkeypatch.setattr(speeddesk, "panel_state", lambda *args: raw)
    panel = pagestate.speed_desk(make_settings(), now)
    assert panel["today"]["day"] == utc_day(now)
    assert panel["today"]["pnl_usd"] is None and panel["today"]["fills"] is None
    assert panel["problem"] == "Today's practice report is unavailable"


def test_daily_history_keeps_coverage_and_never_invents_missing_values(make_settings, fake_clock, monkeypatch) -> None:
    now = fake_clock.now()
    raw = report(now)
    yesterday = utc_day(now - 86_400)
    prior = {**report(now - 86_400)["today"], "mode": "live", "partial_day": True,
             "observed_seconds": 20_000, "avg_bitcoin_feed_latency_ms": 34, "reported_at": now}
    older = utc_day(now - 2 * 86_400)
    raw["reports"] = {yesterday: prior, older: {"day": older}, utc_day(now): raw["today"],
                      "2026-00-00": {"day": "2026-00-00"}, "malformed": {},
                      utc_day(now - 3 * 86_400): {"day": yesterday}}
    monkeypatch.setattr(speeddesk, "panel_state", lambda *args: raw)
    panel = pagestate.speed_desk(make_settings(), now)
    assert set(panel["reports"]) == {yesterday, older}
    previous = panel["reports"][yesterday]
    assert previous["mode"] == "paper" and previous["label"] == "PRACTICE (pretend money)"
    assert previous["observed_seconds"] == 20_000 and previous["partial_day"] is True
    assert previous["avg_bitcoin_feed_latency_ms"] == 34
    assert previous["take_fill_rate_pct"] == 50
    assert panel["reports"][older]["pnl_usd"] is None
    assert panel["reports"][older]["partial_day"] is None

    raw["reports"] = {utc_day(now - offset * 86_400): report(now - offset * 86_400)["today"]
                      for offset in range(1, 61)}
    history = pagestate.speed_desk(make_settings(), now)["reports"]
    assert len(history) == 31
    assert min(history) == utc_day(now - 31 * 86_400) and max(history) == yesterday


def test_venue_reports_preserve_separate_results_rates_and_real_data_coverage(
        make_settings, fake_clock, monkeypatch) -> None:
    now = fake_clock.now()
    raw = report(now)
    day = utc_day(now)
    shared = {"day": day, "mode": "live", "label": "REAL", "reporting_complete": True,
              "reporting_started_at": now - 3600, "coverage_started_at": now - 3500,
              "enabled": True, "observed_seconds": 3600, "avg_bitcoin_feed_latency_ms": 120,
              "fill_rate_basis": "orders_placed_on_day"}
    raw["today"]["venues"] = {
        "polymarket_us": {**shared, "pnl_usd": 0.22, "locked_usd": 0.24, "directional_usd": -0.02,
                          "windows": 2, "fills": 4, "take_attempts": 10, "take_fills": 3,
                          "maker_orders": 4, "maker_fills": 1, "fresh_data_seconds": 3300,
                          "maker_data_seconds": 3200},
        "kalshi": {**shared, "pnl_usd": -0.07, "locked_usd": 0.01, "directional_usd": -0.08,
                   "windows": 1, "fills": 1, "take_attempts": 3, "take_fills": 1,
                   "maker_orders": 2, "maker_fills": 0, "fresh_data_seconds": 200,
                   "maker_data_seconds": 0},
        "unknown_venue": {**shared, "pnl_usd": 999},
    }
    monkeypatch.setattr(speeddesk, "panel_state", lambda *args: raw)
    panel = pagestate.speed_desk(make_settings(), now)
    assert panel["today"]["pnl_usd"] == 0.15
    venues = panel["today"]["venues"]
    assert set(venues) == {"kalshi", "polymarket_us"}
    us, kalshi = venues["polymarket_us"], venues["kalshi"]
    assert us["pnl_usd"] == 0.22 and kalshi["pnl_usd"] == -0.07
    assert us["take_fill_rate_pct"] == 30 and kalshi["take_fill_rate_pct"] == pytest.approx(100 / 3)
    assert us["maker_fill_rate_pct"] == 25 and kalshi["maker_fill_rate_pct"] == 0
    assert us["mode"] == kalshi["mode"] == "paper"
    assert us["label"] == kalshi["label"] == "PRACTICE (pretend money)"
    assert us["observed_seconds"] == kalshi["observed_seconds"] == 3600
    assert us["fresh_data_seconds"] == 3300 and kalshi["fresh_data_seconds"] == 200
    assert us["maker_data_seconds"] == 3200 and kalshi["maker_data_seconds"] == 0
    assert us["reporting_complete"] is True and us["fill_rate_basis"] == "orders_placed_on_day"
    assert us["reporting_started_at"] == now - 3600 and us["coverage_started_at"] == now - 3500


def test_legacy_and_disabled_venue_reports_are_unknown_or_incomplete_not_zero(
        make_settings, fake_clock, monkeypatch) -> None:
    now = fake_clock.now()
    raw = report(now)
    monkeypatch.setattr(speeddesk, "panel_state", lambda *args: raw)
    assert pagestate.speed_desk(make_settings(), now)["today"]["venues"] == {}
    raw["today"]["venues"] = {
        "polymarket_us": {"day": utc_day(now), "reporting_complete": False,
                          "reporting_started_at": now, "pnl_usd": 0.15, "take_attempts": None,
                          "take_fills": None, "fills": None},
        "kalshi": {"day": utc_day(now), "enabled": False, "reporting_complete": False},
    }
    venues = pagestate.speed_desk(make_settings(), now)["today"]["venues"]
    assert venues["polymarket_us"]["pnl_usd"] == 0.15
    assert venues["polymarket_us"]["fills"] is None
    assert venues["polymarket_us"]["take_fill_rate_pct"] is None
    assert venues["kalshi"]["enabled"] is False and venues["kalshi"]["pnl_usd"] is None
    assert venues["kalshi"]["fresh_data_seconds"] is None
    assert venues["kalshi"]["fill_rate_basis"] is None
    raw["today"]["venues"]["kalshi"]["day"] = utc_day(now - 86_400)
    assert set(pagestate.speed_desk(make_settings(), now)["today"]["venues"]) == {"polymarket_us"}


def test_completed_daily_reports_keep_venue_breakdown_and_unknown_history(
        make_settings, fake_clock, monkeypatch) -> None:
    now = fake_clock.now()
    raw = report(now)
    yesterday, older = utc_day(now - 86_400), utc_day(now - 2 * 86_400)
    raw["reports"] = {
        yesterday: {"day": yesterday, "pnl_usd": 1.0, "venues": {
            "kalshi": {"day": yesterday, "pnl_usd": 1.3, "reporting_complete": True},
            "polymarket_us": {"day": yesterday, "pnl_usd": -0.3, "reporting_complete": False}}},
        older: {"day": older, "pnl_usd": 4.0},
    }
    monkeypatch.setattr(speeddesk, "panel_state", lambda *args: raw)
    history = pagestate.speed_desk(make_settings(), now)["reports"]
    assert history[yesterday]["venues"]["kalshi"]["pnl_usd"] == 1.3
    assert history[yesterday]["venues"]["polymarket_us"]["pnl_usd"] == -0.3
    assert history[yesterday]["venues"]["polymarket_us"]["reporting_complete"] is False
    assert history[older]["venues"] == {} and history[older]["pnl_usd"] == 4.0
    html = render_page_html(make_settings())
    assert 'id="speeddesk-venues"' in html and "Completed daily reports by venue" in html
    assert "No venue report for this day" in html and "Incomplete venue history" in html
    assert "App running (shared)" in html and "Fresh Bitcoin + venue books" in html
    assert "Fill rates: orders placed this UTC day." in html


def test_page_never_adds_practice_result_to_cash_real_profit_or_town(make_settings, fake_clock, monkeypatch) -> None:
    settings = make_settings(POLYDESK_ENABLED=False, TRENDDESK_ENABLED=False)
    now = fake_clock.now()
    raw = report(now)
    monkeypatch.setattr(speeddesk, "panel_state", lambda *args: raw)
    with Ledger(settings.db_path, clock=fake_clock) as ledger:
        first = pagestate.build_page_state(ledger, settings, now)
        raw["today"]["locked_usd"] = 12345
        raw["today"]["pnl_usd"] = 12344.90
        raw["today"]["venues"] = {"kalshi": {"day": utc_day(now), "pnl_usd": 12344.90}}
        second = pagestate.build_page_state(ledger, settings, now)
    assert second["money"]["speeddesk"]["today"]["pnl_usd"] == 12344.90
    for key in ("usd", "today", "since_start", "polymarket"):
        assert first["money"][key] == second["money"][key]
    assert first["town"] == second["town"]
    assert first["plain"]["real"] == second["plain"]["real"]
    assert second["plain"]["speeddesk_line"].startswith("Bitcoin speed desk (PRACTICE, pretend money)")
    html = render_page_html(settings)
    assert 'id="speeddesk"' in html and "<small>PRACTICE</small>" in html
    assert "Instant-order fill rate" in html and "Resting-order fill rate" in html
    assert "midnight UTC" in html and "Average fill delay" in html
