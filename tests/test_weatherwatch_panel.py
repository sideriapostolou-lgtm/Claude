"""A weather observation remains separate from account cash and actual trading results."""

from __future__ import annotations

import json

import pytest

from nightcrawler import pagestate
from nightcrawler.ledger import Ledger
from nightcrawler.page import render_page_html


def save(settings, panel):
    path = settings.data_dir / "weatherwatch" / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"panel": panel}), encoding="utf-8")


def sample(now):
    scenario = {"candidate_markets": 4, "conditional_entries": 2, "unassessed_markets": 1,
                "displayed_contracts_at_assessment": 12.5, "conditional_capital_usd": 1.9402,
                "settled_entries": 1, "pending_hold_entries": 1, "exit_observations": 0,
                "conditional_hold_pnl_usd": .03, "conditional_exit_pnl_usd": None,
                "execution_proven": False, "qualified_pnl_usd": None}
    today = {"day": "2026-10-12", "complete": False, "candidate_locks": 4,
             "confirmed_observation_proxies": 2, "gaps": 2, "recorded_seconds": 35,
             "rejected_readings": 3, "trade_prints": 5, "cli_disagreements": [],
             "cli_reports": 1, "cli_comparisons": 1,
             "settlement_disagreements": ["kalshi:TEST"],
             "sources": {"nws": {"readings": 30, "median": 51, "p95": 88, "overflow": False,
                                 "bootstrap_readings": 2, "latency_samples": 28}},
             "conditional_scenarios": {"kalshi": {"0.97": scenario, "0.98": scenario}}}
    return {"as_of": now, "started_at": now - 3600, "status": "Observing", "markets": 20,
            "active_watches": 2, "capacity_skips": 1, "storage_bytes": 123456,
            "modeled_quote_delay_s": .25, "actual_order_latency_s": None,
            "health": {"nws": {"status": "ok"}}, "today": today,
            "reports": {"2026-10-11": {**today, "day": "2026-10-11"}}}

def test_weather_panel_retains_measured_counts_with_unknown_unmeasured_results(make_settings, fake_clock):
    settings, now = make_settings(), fake_clock.now()
    save(settings, sample(now))
    panel = pagestate.weatherwatch_panel(settings, now)
    assert panel["label"] == "READ-ONLY WEATHER STOPWATCH" and not panel["real_orders_available"]
    assert not panel["stale"] and panel["today"]["candidate_locks"] == 4 and panel["capacity_skips"] == 1
    assert panel["sources"]["nws"]["median_latency_s"] == 51
    assert panel["sources"]["nws"]["bootstrap_readings"] == 2
    assert panel["sources"]["nws"]["latency_samples"] == 28
    kalshi = panel["today"]["conditional_scenarios"]["kalshi"]["0.97"]
    assert kalshi["displayed_contracts_at_assessment"] == 12.5 and kalshi["conditional_hold_pnl_usd"] == .03
    assert panel["qualified_cents_per_day"] is None and kalshi["conditional_exit_pnl_usd"] is None
    assert "polymarket_us" not in panel["today"]["conditional_scenarios"]
    assert panel["today"]["cli_disagreements"] == 0 and panel["today"]["settlement_disagreements"] == 1
    assert not panel["reports"]["2026-10-11"]["complete"]


def test_missing_disabled_and_old_weather_panels_are_explicit_not_zero_profit(make_settings, fake_clock):
    settings, now = make_settings(), fake_clock.now()
    panel = pagestate.weatherwatch_panel(settings, now)
    assert panel["stale"] and "first weather observation" in panel["status"]
    assert "venues" not in panel and len(json.dumps(panel)) < 250
    assert pagestate.weatherwatch_panel(make_settings(WEATHERWATCH_ENABLED=False), now) is None
    save(settings, sample(now - 121))
    assert pagestate.weatherwatch_panel(settings, now)["stale"]
    save(settings, sample(now + 3600))
    assert pagestate.weatherwatch_panel(settings, now)["stale"]


@pytest.mark.parametrize("body", [b"{broken", b"{}", b"x" * (8 * 1024 * 1024 + 1)])
def test_unreadable_weather_state_cannot_take_down_the_page(make_settings, fake_clock, body):
    settings = make_settings()
    save(settings, {})
    (settings.data_dir / "weatherwatch" / "state.json").write_bytes(body)
    panel = pagestate.weatherwatch_panel(settings, fake_clock.now())
    assert panel["stale"] and "unknown" in panel["status"]
    assert "venues" not in panel


def test_weather_panel_cannot_enable_money_echo_secrets_or_accept_invalid_numbers(make_settings, fake_clock):
    secret = "fake-weather-test-secret-content"
    settings, now = make_settings(KALSHI_PRIVATE_KEY=secret), fake_clock.now()
    raw = sample(now)
    raw.update(real_orders_available=True, mode="live", cash_usd=100, profit_usd=200, private_key=secret,
               status=secret, problem=secret * 100)
    raw["health"]["nws"]["reason"] = secret
    raw["today"]["sources"]["nws"]["overflow"] = True
    raw.update(qualified_cents_per_day=1000, actual_order_latency_s=.001, scenarios_overlap=False)
    raw["today"]["conditional_scenarios"]["kalshi"]["0.97"].update(
        displayed_contracts_at_assessment=-1, conditional_capital_usd=float("nan"),
        conditional_hold_pnl_usd=float("inf"), qualified_pnl_usd=900, execution_proven=True)
    raw["reports"]["unsafe-day"] = raw["reports"]["2026-10-11"]
    save(settings, raw)
    panel = pagestate.weatherwatch_panel(settings, now)
    assert not panel["real_orders_available"]
    assert not {"mode", "cash_usd", "profit_usd", "private_key"} & panel.keys()
    assert secret not in json.dumps(panel) and panel["status"] == "[REDACTED]"
    assert len(panel["problem"]) <= pagestate.TEXT_MAX
    scenario = panel["today"]["conditional_scenarios"]["kalshi"]["0.97"]
    assert all(scenario[key] is None for key in ("displayed_contracts_at_assessment", "conditional_capital_usd",
                                               "conditional_hold_pnl_usd", "qualified_pnl_usd"))
    assert not scenario["execution_proven"] and panel["qualified_cents_per_day"] is None
    assert panel["actual_order_latency_s"] is None and panel["scenarios_overlap"]
    assert panel["sources"]["nws"]["median_latency_s"] is None
    assert panel["sources"]["nws"]["p95_latency_s"] is None
    assert "unsafe-day" not in panel["reports"]


def test_weather_reports_have_bounded_days_and_known_venues_only(make_settings, fake_clock):
    settings, now = make_settings(), fake_clock.now()
    raw = sample(now)
    report = raw["reports"]["2026-10-11"]
    raw["reports"] = {f"2026-10-{i:02}": report for i in range(1, 21)}
    raw["today"]["conditional_scenarios"]["unknown_private_venue"] = {"0.97": {"reason": "Do not expose arbitrary state"}}
    save(settings, raw)
    panel = pagestate.weatherwatch_panel(settings, now)
    assert len(panel["reports"]) == 7 and min(panel["reports"]) == "2026-10-14"
    assert set(panel["today"]["conditional_scenarios"]) == {"kalshi"}


def test_weather_counts_cannot_change_cash_town_profit_or_plain_summary(make_settings, fake_clock):
    settings, now = make_settings(POLYDESK_ENABLED=False, TRENDDESK_ENABLED=False), fake_clock.now()
    with Ledger(settings.db_path) as ledger:
        before = pagestate.build_page_state(ledger, settings, now)
        save(settings, sample(now))
        after = pagestate.build_page_state(ledger, settings, now)
    assert before["money"] == after["money"] and before["town"] == after["town"]
    assert before["plain"] == after["plain"] and before["mode"] == after["mode"]
    assert after["weatherwatch"]["today"]["candidate_locks"] == 4


def test_weather_ui_labels_latency_depth_and_hypothetical_results_without_promising_profit(make_settings):
    html = render_page_html(make_settings())
    assert "READ-ONLY WEATHER STOPWATCH" in html
    assert "Observed thresholds are not guaranteed wins" in html
    assert "they are not guaranteed fills" in html
    assert "not order execution latency" in html
    assert "This observer sends no orders" in html
    assert "Estimated cents per day" in html and "Not measured" in html
    assert "scenarios overlap: never add their results" in html
    assert "Actual order latency and resting-order fills have not been measured" in html
    assert "NOAA MADIS ASOS (5-minute)" in html and "One-minute ASOS" in html
    assert "Startup / backfill readings excluded" in html
    assert "Final CLI reports / comparisons" in html


def test_madis_five_minute_source_is_reported_separately_from_unavailable_one_minute(make_settings, fake_clock):
    settings, now = make_settings(), fake_clock.now()
    raw = sample(now)
    raw["health"].update({"madis_hfm": {"status": "ok"}, "asos_1minute": {
        "status": "unavailable", "reason": "No supported public one-minute feed"}})
    raw["today"]["sources"]["madis_hfm"] = {"readings": 12, "median": 84, "p95": 110, "overflow": False}
    save(settings, raw)
    panel = pagestate.weatherwatch_panel(settings, now)
    assert panel["sources"]["madis_hfm"]["readings"] == 12
    assert panel["sources"]["madis_hfm"]["median_latency_s"] == 84
    assert panel["sources"]["asos_1minute"]["status"] == "unavailable"
    assert panel["sources"]["asos_1minute"]["median_latency_s"] is None


@pytest.mark.parametrize("comparisons", [None, 0])
def test_no_cli_comparisons_cannot_be_presented_as_zero_disagreements(make_settings, fake_clock, comparisons):
    settings, now = make_settings(), fake_clock.now()
    raw = sample(now)
    raw["today"].update(cli_reports=0, cli_comparisons=comparisons, cli_disagreements=[])
    save(settings, raw)
    panel = pagestate.weatherwatch_panel(settings, now)
    assert panel["today"]["cli_reports"] == 0
    assert panel["today"]["cli_disagreements"] is None
    assert panel["reports"]["2026-10-11"]["cli_disagreements"] == 0  # A recorded comparison had no disagreement.
