"""Kalshi's actual account stays separate from its practice twin and all existing money totals."""

from __future__ import annotations

import copy
import json

import pytest

from nightcrawler import pagestate, speeddesk
from nightcrawler.clock import utc_day
from nightcrawler.ledger import Ledger
from nightcrawler.page import render_page_html


def companion(now: float) -> dict:
    day = utc_day(now)
    return {
        "mode": "live", "configured_mode": "live", "status": "Live account connected", "reason": None,
        "authenticated": True, "real_orders_available": True, "as_of": now,
        "cash_usd": 14.39, "cash_at": now, "reserved_usd": .70, "open_risk_usd": 1.10, "at_risk_usd": 1.80,
        "open_orders": 1, "positions": 2, "total_halted": False, "cleanup_pending": False,
        "caps": {"window_usd": 2, "open_usd": 4, "day_stop_usd": 3, "total_stop_usd": 5},
        "today": {"day": day, "windows": 3, "fills": 5, "fees_usd": .04,
                  "locked_usd": .12, "directional_usd": -.10, "pnl_usd": .02},
        "total": {"fees_usd": .08, "locked_usd": .18, "directional_usd": -.11, "pnl_usd": .07},
        "practice_twin": {"day": day, "windows": 4, "fills": 7, "pnl_usd": 1.23,
                          "locked_usd": 1.25, "directional_usd": -.02},
    }


def speed_report(now: float, kalshi: dict | None) -> dict:
    return {"as_of": now, "status": "Practice connected", "today": {"day": utc_day(now)}, "kalshi_live": kalshi}


def live_settings(make_settings, **overrides):
    values = {"SPEEDDESK_KALSHI_MODE": "live", "SPEEDDESK_KALSHI_LIVE_CONFIRM": "yes",
              "KALSHI_KEY_ID": "fake-panel-key-id", "KALSHI_PRIVATE_KEY": "fake-panel-key-material"}
    return make_settings(**(values | overrides))


def test_actual_and_practice_financials_have_distinct_scopes(make_settings, fake_clock, monkeypatch) -> None:
    now = fake_clock.now()
    raw = speed_report(now, companion(now))
    monkeypatch.setattr(speeddesk, "panel_state", lambda *args: raw)
    panel = pagestate.speed_desk(live_settings(make_settings), now)
    live = panel["kalshi_live"]
    assert panel["mode"] == "paper" and panel["today"]["pnl_usd"] is None
    assert live["active"] and live["mode"] == "live" and live["label"] == "REAL MONEY (Kalshi)"
    assert live["cash_usd"] == 14.39 and live["today"]["pnl_usd"] == .02
    assert live["total"]["pnl_usd"] == .07 and live["practice_twin"]["pnl_usd"] == 1.23
    assert live["practice_twin"]["mode"] == "paper" and live["has_real_exposure"]
    assert live["caps"] == {"window_usd": 2, "open_usd": 4, "day_stop_usd": 3, "total_stop_usd": 5}


@pytest.mark.parametrize("change", [
    {"authenticated": False}, {"real_orders_available": False}, {"mode": "paper"}, {"mode": "invalid"},
])
def test_report_cannot_claim_active_without_complete_controller_status(
        make_settings, fake_clock, monkeypatch, change) -> None:
    now = fake_clock.now()
    raw = companion(now) | change
    monkeypatch.setattr(speeddesk, "panel_state", lambda *args: speed_report(now, raw))
    live = pagestate.speed_desk(live_settings(make_settings), now)["kalshi_live"]
    assert not live["active"] and not live["real_orders_available"]
    assert live["has_real_exposure"]  # switching off does not erase actual orders/positions


@pytest.mark.parametrize("offset", [-61, 3600])
def test_stale_or_future_report_cannot_claim_current_live_or_current_cash(
        make_settings, fake_clock, monkeypatch, offset) -> None:
    now = fake_clock.now()
    raw = companion(now + offset)
    monkeypatch.setattr(speeddesk, "panel_state", lambda *args: speed_report(now, raw))
    live = pagestate.speed_desk(live_settings(make_settings), now)["kalshi_live"]
    assert live["stale"] and not live["active"] and live["cash_usd"] is None
    assert live["at_risk_usd"] == 1.80 and live["has_real_exposure"]


def test_cash_has_its_own_freshness_and_old_day_metrics_remain_unknown(make_settings, fake_clock, monkeypatch) -> None:
    now = fake_clock.now()
    raw = companion(now)
    raw["cash_at"] = now - 61
    raw["today"]["day"] = raw["practice_twin"]["day"] = utc_day(now - 86400)
    monkeypatch.setattr(speeddesk, "panel_state", lambda *args: speed_report(now, raw))
    live = pagestate.speed_desk(live_settings(make_settings), now)["kalshi_live"]
    assert live["active"] and not live["stale"] and live["cash_usd"] is None
    assert live["today"]["pnl_usd"] is None and live["today"]["windows"] is None
    assert live["practice_twin"]["pnl_usd"] is None and live["total"]["pnl_usd"] == .07


def test_missing_live_report_is_unknown_and_never_queries_credentials(make_settings, fake_clock, monkeypatch) -> None:
    now = fake_clock.now()
    monkeypatch.setattr(speeddesk, "panel_state", lambda *args: speed_report(now, None))
    assert pagestate.speed_desk(make_settings(), now)["kalshi_live"] is None
    live = pagestate.speed_desk(make_settings(SPEEDDESK_KALSHI_MODE="live"), now)["kalshi_live"]
    assert live["stale"] and live["mode"] is None and not live["active"]
    assert live["cash_usd"] is None and live["at_risk_usd"] is None and live["today"]["pnl_usd"] is None


def test_panel_whitelists_saved_fields_and_redacts_reasons_before_clipping(make_settings, fake_clock, monkeypatch) -> None:
    now = fake_clock.now()
    secret = "throwaway-test-only-secret-1234567890"
    settings = live_settings(make_settings, KALSHI_PRIVATE_KEY=secret)
    raw = companion(now)
    raw.update(status=secret, reason=secret * 100, private_key=secret, latest_events=[{"secret": secret}])
    raw["today"]["pnl_usd"] = float("inf")
    raw["cash_usd"] = True
    monkeypatch.setattr(speeddesk, "panel_state", lambda *args: speed_report(now, raw))
    live = pagestate.speed_desk(settings, now)["kalshi_live"]
    body = json.dumps(live)
    assert secret not in body and "private_key" not in body and "latest_events" not in body
    assert live["status"] == "[REDACTED]" and len(live["reason"]) <= pagestate.TEXT_MAX
    assert live["today"]["pnl_usd"] is None and live["cash_usd"] is None


def test_kalshi_money_never_changes_other_accounts_town_goals_or_hearts(make_settings, fake_clock, monkeypatch) -> None:
    now = fake_clock.now()
    settings = live_settings(make_settings, POLYDESK_ENABLED=False, TRENDDESK_ENABLED=False)
    raw = speed_report(now, None)
    monkeypatch.setattr(speeddesk, "panel_state", lambda *args: raw)
    with Ledger(settings.db_path) as ledger:
        before = pagestate.build_page_state(ledger, settings, now)
        raw["kalshi_live"] = companion(now)
        after = pagestate.build_page_state(ledger, settings, now)
    before_money, after_money = copy.deepcopy(before["money"]), copy.deepcopy(after["money"])
    before_money.pop("speeddesk")
    after_money.pop("speeddesk")
    assert before_money == after_money and before["town"] == after["town"]
    assert before["plain"]["hearts"] == after["plain"]["hearts"]
    assert before["plain"]["goal"] == after["plain"]["goal"]
    assert not after["plain"]["real"]["on"]  # this pre-existing field still scopes Polymarket/Solana only
    assert "Kalshi is using real money" in after["plain"]["headline"]
    assert "everything is practice" not in after["plain"]["real"]["line"]
    assert len(after["plain"]["headline"]) <= pagestate.PLAIN_HEADLINE_MAX


def test_page_retains_separate_practice_and_real_cards(make_settings) -> None:
    html = render_page_html(make_settings())
    assert '<h2>Bitcoin speed desk <small>PRACTICE</small>' in html
    assert '<section class="card" id="kalshilive" hidden><h2>Kalshi live desk' in html
    assert "Actual real-money results today (UTC)" in html and "Practice twin today · PRACTICE" in html
    assert "Cash is not profit" in html and "existing bets still settle" in html


@pytest.mark.parametrize("change", [
    {"SPEEDDESK_KALSHI_MODE": "paper"}, {"SPEEDDESK_KALSHI_LIVE_CONFIRM": ""},
    {"KALSHI_KEY_ID": ""}, {"KALSHI_PRIVATE_KEY": ""}, {"SPEEDDESK_KALSHI_ENABLED": False},
])
def test_new_paper_or_revoked_gate_overrides_old_saved_live_report_without_erasing_real_exposure(
        make_settings, fake_clock, monkeypatch, change) -> None:
    now = fake_clock.now()
    monkeypatch.setattr(speeddesk, "panel_state", lambda *args: speed_report(now, companion(now)))
    settings = live_settings(make_settings, **change)
    live = pagestate.speed_desk(settings, now)["kalshi_live"]
    assert not live["active"] and not live["real_orders_available"]
    assert live["mode"] == "paper" and live["label"] == "PRACTICE" and live["status"] == "PRACTICE"
    assert "Current settings disable" in live["reason"]
    assert live["has_real_exposure"] and live["at_risk_usd"] == 1.80 and live["open_orders"] == 1
