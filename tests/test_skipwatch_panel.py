"""Public observation has no money, account, rule promotion or profit side effects."""

from __future__ import annotations

import json

import pytest

from nightcrawler import pagestate
from nightcrawler.ledger import Ledger
from nightcrawler.page import render_page_html


def save(settings, panel):
    path = settings.data_dir / "skipwatch" / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"panel": panel}), encoding="utf-8")


def sample(now):
    return {"as_of": now, "started_at": now - 3600, "status": "OBSERVING PUBLIC DATA",
            "windows_observed": 12, "wallet_fills": 123, "matched_inferred": 70, "ambiguous": 20, "unmatched": 33,
            "gaps": 2, "storage_bytes": 1_234_567, "max_storage_bytes": 1_073_741_824,
            "last_wallet_at": now - 9, "last_btc_at": now - .2,
            "fit": {"status": "collecting_train"}, "latest_window": "btc-updown-5m-1791835200",
            "coverage": {"bitcoin": True, "book": False, "wallet": True, "trades": True, "wallet_watermark": now - 3},
            "probes": {"us_5m": {"first_seen_at": now - 60, "first_market": "cpc-btc-updown-5m-2026-10-12-2000z",
                                  "first_window_start": 1791835200, "first_window_end": 1791835500,
                                  "last_checked_at": now - 2, "last_success_at": now - 2,
                                  "checks": 120, "errors": 1, "status": "Verified five-minute window observed"},
                       "kalshi_latency": {"region": "us-east4", "median_ms": 42.3, "p95_ms": 83.1, "last_rtt_ms": 46,
                                          "last_checked_at": now - 2, "measurements": 120, "successful_samples": 118,
                                          "errors": 2, "timeouts": 1}}}


def test_panel_preserves_public_counts_and_explicit_status_with_sticky_listing_and_rtt(make_settings, fake_clock):
    settings, now = make_settings(), fake_clock.now()
    save(settings, sample(now))
    panel = pagestate.skipwatch_panel(settings, now)
    assert panel["label"] == "PUBLIC WATCHER" and not panel["real_orders_available"]
    assert not panel["stale"] and panel["wallet_fills"] == 123 and panel["matched_inferred"] == 70
    assert panel["coverage"]["bitcoin"] is True and panel["coverage"]["book"] is False
    assert panel["coverage"]["wallet_watermark"] == now - 3
    assert panel["max_storage_bytes"] == 1_073_741_824
    assert panel["us_5m"]["first_seen_at"] == now - 60
    assert panel["kalshi_latency"]["median_ms"] == 42.3 and panel["kalshi_latency"]["region"] == "us-east4"
    assert "no evidence" in panel["kalshi_latency"]["limitation"]
    assert not panel["cancellations_visible"]


def test_missing_disabled_or_old_report_does_not_invent_counts_coverage_or_current_results(make_settings, fake_clock):
    settings, now = make_settings(), fake_clock.now()
    panel = pagestate.skipwatch_panel(settings, now)
    assert panel["stale"] and panel["wallet_fills"] is None and panel["gaps"] is None
    assert panel["coverage"]["wallet"] is None and panel["kalshi_latency"]["median_ms"] is None
    assert "first public observation" in panel["problem"]
    assert pagestate.skipwatch_panel(make_settings(SKIPWATCH_ENABLED=False), now) is None
    save(settings, sample(now - 61))
    assert pagestate.skipwatch_panel(settings, now)["stale"]


def test_unverified_execution_time_never_promises_a_scheduled_rule_verdict(make_settings, fake_clock):
    settings, now = make_settings(), fake_clock.now()
    raw = sample(now)
    raw["fit"] = {"status": "awaiting_verified_execution_time", "automatic_verdict_scheduled": False,
                  "freeze_due_at": now + 86400, "test_due_at": now + 172800,
                  "reason": "Block inclusion time is not execution time", "summary": {"stage": "timing_unverified"}}
    save(settings, raw)
    panel = pagestate.skipwatch_panel(settings, now)
    assert "execution timing unverified" in panel["fit_status"]
    assert panel["freeze_due_at"] is None and panel["test_due_at"] is None
    assert not panel["automatic_verdict_scheduled"]
    assert panel["fit_reason"] == raw["fit"]["reason"] and panel["wallet_fills"] == 123


@pytest.mark.parametrize("body", [b"{broken", b"{}", b"x" * (8 * 1024 * 1024 + 1)])
def test_broken_missing_or_oversized_panel_is_unknown_without_taking_down_page(make_settings, fake_clock, body):
    settings = make_settings()
    save(settings, {})
    (settings.data_dir / "skipwatch" / "state.json").write_bytes(body)
    panel = pagestate.skipwatch_panel(settings, fake_clock.now())
    assert panel["stale"] and panel["problem"] and panel["wallet_fills"] is None


def test_saved_panel_cannot_promote_trading_claim_profit_or_echo_unknown_secret_fields(make_settings, fake_clock):
    secret = "fake-test-only-unknown-private-key-content"
    settings, now = make_settings(KALSHI_PRIVATE_KEY=secret), fake_clock.now()
    raw = sample(now)
    raw.update(real_orders_available=True, cancellations_visible=True, mode="live", cash_usd=9000, profit_usd=3000,
               private_key=secret, status=secret, problem=secret * 100)
    raw["probes"]["samples"] = [{"secret": secret}]
    save(settings, raw)
    panel = pagestate.skipwatch_panel(settings, now)
    assert not panel["real_orders_available"] and not panel["cancellations_visible"]
    assert not {"mode", "profit_usd", "cash_usd", "private_key", "samples"} & panel.keys()
    assert secret not in json.dumps(panel) and panel["status"] == "[REDACTED]"
    assert len(panel["problem"]) <= pagestate.TEXT_MAX


def test_watcher_panel_changes_no_money_or_town_figures(make_settings, fake_clock):
    settings, now = make_settings(POLYDESK_ENABLED=False, TRENDDESK_ENABLED=False), fake_clock.now()
    with Ledger(settings.db_path) as ledger:
        before = pagestate.build_page_state(ledger, settings, now)
        save(settings, sample(now))
        after = pagestate.build_page_state(ledger, settings, now)
    assert before["money"] == after["money"] and before["town"] == after["town"]
    assert before["plain"] == after["plain"] and before["mode"] == after["mode"]
    assert after["skipwatch"]["wallet_fills"] == 123


def test_watcher_ui_labels_observations_inference_and_latency_without_profit(make_settings):
    html = render_page_html(make_settings())
    assert "PUBLIC WATCHER" in html and "US five-minute listing alert" in html
    assert "exact timing and maker/taker identity are not proven" in html
    assert "We are testing how well rules predict future trades" in html
    assert "liquidity and latency observations do not prove an edge" in html
    assert "HTTP round trip" in html and "not WebSocket data age" in html


def test_research_metrics_are_prediction_only_with_explicit_stage_and_unknowns(make_settings, fake_clock):
    settings, now = make_settings(), fake_clock.now()
    raw = sample(now)
    raw["fit"] = {"status": "predictive_pattern_only", "live_promotion": True, "net_profit_usd": 999,
                  "summary": {"stage": "held_out", "rows": 4500, "precision": .4, "recall": .6,
                              "f1": .48, "coverage": .95, "feature_coverage": .75,
                              "reasons": ["feature_coverage_below_80pct"]}}
    save(settings, raw)
    panel = pagestate.skipwatch_panel(settings, now)
    assert panel["fit_summary"]["precision"] == .4 and panel["fit_summary"]["recall"] == .6
    assert panel["fit_summary"]["stage"] == "held_out" and "profitability remains untested" in panel["fit_status"]
    assert panel["fit_summary"]["feature_coverage"] == .75
    assert panel["fit_summary"]["reasons"] == ["Usable feature coverage below 80%"]
    assert "net_profit" not in json.dumps(panel) and "live_promotion" not in json.dumps(panel)
    raw["fit"]["summary"].update(precision=float("inf"), recall=1.1, coverage=-1)
    save(settings, raw)
    summary = pagestate.skipwatch_panel(settings, now)["fit_summary"]
    assert summary["precision"] is None and summary["recall"] is None and summary["coverage"] is None


def test_speed_desk_exposes_observed_volatility_progress_without_treating_elapsed_time_as_ready(
        make_settings, fake_clock, monkeypatch):
    from nightcrawler import speeddesk
    from nightcrawler.clock import utc_day

    now = fake_clock.now()
    raw = {"as_of": now, "today": {"day": utc_day(now)},
           "volatility": {"samples": 1560, "required_samples": 3000, "required_elapsed_s": 3600,
                          "ready": False, "source": "unsafe arbitrary source"}}
    monkeypatch.setattr(speeddesk, "panel_state", lambda *args: raw)
    progress = pagestate.speed_desk(make_settings(), now)["volatility"]
    assert progress == {"samples": 1560, "required_samples": 3000, "required_elapsed_s": 3600,
                        "ready": False, "source": "observed one-second Coinbase returns"}
