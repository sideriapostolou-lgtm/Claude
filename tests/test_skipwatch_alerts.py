"""Public probes are evidence-only: no account client, credentials, or trading-universe edits."""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest
import requests

from nightcrawler.skipwatch_alerts import (
    KALSHI_STATUS,
    US_BASE,
    US_EVENTS,
    PublicProbes,
    _public_get,
    verified_window,
)
from nightcrawler.speeddesk_feeds import window_slugs

NOW = datetime(2026, 10, 12, 20, 0, tzinfo=UTC).timestamp()
SLUG = "cpc-btc-updown-5m-2026-10-12-2000z"


class Reply:
    def __init__(self, payload, status=200, headers=None):
        self.status_code, self.payload = status, payload
        self.headers = headers or {}

    def json(self):
        return self.payload


def market():
    return {"market": {"slug": SLUG, "assetPriceTerms": {
        "asset": {"symbol": "BTC"}, "horizon": "5m", "indexSymbol": "BRTI",
        "marketType": "ASSET_PRICE_MARKET_TYPE_UP_DOWN",
        "windowStart": "2026-10-12T20:00:00Z", "windowEnd": "2026-10-12T20:05:00Z"}}}


def transport(*, listed=True, detail=None):
    calls = []

    def get(url):
        calls.append(url)
        if url == KALSHI_STATUS:
            return Reply({"exchange_active": True, "trading_active": True})
        if url == US_EVENTS:
            return Reply({"events": [{"seriesSlug": "btc-updown-5m", "markets": [{"slug": SLUG}]}] if listed else []})
        assert url == US_BASE + "/v1/market/slug/" + SLUG
        return Reply(market() if detail is None else detail)

    return get, calls


def test_only_verified_market_terms_alert_and_first_observation_survives_restart_and_later_failure():
    get, calls = transport()
    probe = PublicProbes(get=get, clock=lambda: NOW, region="us-east4")
    events = probe.poll()
    assert len(events) == 1 and events[0]["kind"] == "skipwatch_us_5m_listing"
    assert events[0]["market"] == SLUG and events[0]["window_end"] - events[0]["window_start"] == 300
    assert events[0]["evidence"] == "verified_public_market_terms" and not events[0]["real_orders_available"]
    first = probe.state()["us_5m"]
    assert first["first_seen_at"] == NOW and first["first_market"] == SLUG
    assert probe.poll() == []  # sticky notification, not a new fake first-seen on every poll
    restored = PublicProbes(get=get, clock=lambda: NOW + 30, region="us-east4", initial=probe.state())
    assert restored.poll() == [] and restored.state()["us_5m"]["first_seen_at"] == NOW

    def failure(_url):
        raise RuntimeError("provider-body-with-secret-must-not-appear")

    restored.get = failure
    assert restored.poll() == []
    assert restored.state()["us_5m"]["first_seen_at"] == NOW
    assert "provider-body" not in repr(restored.state())
    assert set(calls) == {KALSHI_STATUS, US_EVENTS, US_BASE + "/v1/market/slug/" + SLUG}
    assert all("-5m-" not in slug for slug in window_slugs(NOW))  # existing trading universe is unchanged


@pytest.mark.parametrize("field,value", [
    ("horizon", "15m"), ("windowEnd", "2026-10-12T20:15:00Z"), ("windowStart", None),
    ("asset", {"symbol": "ETH"}), ("marketType", "ASSET_PRICE_MARKET_TYPE_ABOVE_BELOW"),
    ("indexSymbol", "OTHER"),
])
def test_series_name_and_unverified_or_wrong_market_terms_never_trigger_alert(field, value):
    detail = market()
    detail["market"]["assetPriceTerms"][field] = value
    get, _ = transport(detail=detail)
    probe = PublicProbes(get=get, clock=lambda: NOW)
    assert probe.poll() == [] and probe.state()["us_5m"]["first_seen_at"] is None


def test_empty_series_wrong_series_and_malformed_market_do_not_count_as_a_listing():
    get, _ = transport(listed=False)
    probe = PublicProbes(get=get, clock=lambda: NOW)
    assert probe.poll() == []
    assert probe.state()["us_5m"]["last_success_at"] == NOW
    assert probe.state()["us_5m"]["first_market"] is None
    assert verified_window({"series": {"slug": "btc-updown-5m"}}, SLUG) is None
    assert verified_window(market(), SLUG.replace("2000", "2005")) is None
    probe.get = lambda url: Reply({"events": [{"seriesSlug": "btc-updown-15m"}]}) if url == US_EVENTS else get(url)
    assert probe.poll() == []
    assert probe.state()["us_5m"]["errors"] == 1


def test_latency_is_http_rtt_success_percentiles_and_failure_counts_not_websocket_delay():
    values = iter([.01, .03, .05, requests.Timeout("private"), Reply({}, 503)])
    monotonic = [10.0]

    def get(url):
        if url == US_EVENTS:
            return Reply({"events": []})
        assert url == KALSHI_STATUS
        value = next(values)
        if isinstance(value, Exception):
            raise value
        if isinstance(value, Reply):
            return value
        monotonic[0] += value
        return Reply({"exchange_active": False, "trading_active": False})

    probe = PublicProbes(get=get, clock=lambda: NOW, monotonic=lambda: monotonic[0], region="us-west2")
    for _ in range(5):
        probe.poll()
    stats = probe.state()["kalshi_latency"]
    assert (stats["measurements"], stats["successful_samples"], stats["errors"], stats["timeouts"]) == (5, 3, 2, 1)
    assert stats["median_ms"] == pytest.approx(30) and stats["p95_ms"] == pytest.approx(50)
    assert stats["last_rtt_ms"] is None and stats["region"] == "us-west2"
    assert "HTTP" in stats["limitation"] and "no evidence" in stats["limitation"]


def test_samples_expire_and_region_change_or_unknown_location_cannot_mix_old_latency():
    get, _ = transport(listed=False)
    probe = PublicProbes(get=get, clock=lambda: NOW, region="us-east4")
    probe.poll()
    saved = probe.state()
    assert PublicProbes(clock=lambda: NOW + 30, region="us-east4", initial=saved).state()["kalshi_latency"]["measurements"] == 1
    for region, now in (("us-west2", NOW), (None, NOW), ("us-east4", NOW + 3601)):
        stats = PublicProbes(clock=lambda now=now: now, region=region, initial=saved).state()["kalshi_latency"]
        assert stats["measurements"] == 0 and stats["median_ms"] is None and stats["p95_ms"] is None
    assert PublicProbes(region="https://untrusted-region").state()["region"] is None


def test_probe_storage_is_bounded_and_invalid_saved_first_seen_is_not_presented_as_verified():
    get, _ = transport(listed=False)
    probe = PublicProbes(get=get, clock=lambda: NOW, region="us-east4")
    for _ in range(280):
        probe.poll()
    saved = probe.state()
    assert len(saved["samples"]) == 256
    invalid = copy.deepcopy(saved)
    invalid["us_5m"].update(first_seen_at=NOW, first_market=SLUG, first_window_start=NOW + 300, first_window_end=NOW + 600)
    restored = PublicProbes(clock=lambda: NOW, region="us-east4", initial=invalid)
    assert restored.state()["us_5m"]["first_seen_at"] is None
    assert "invalid" in restored.state()["us_5m"]["status"]


def test_production_transport_is_public_get_only_without_authentication(monkeypatch):
    calls = []
    monkeypatch.setattr(requests, "get", lambda url, **kwargs: calls.append((url, kwargs)))
    _public_get(KALSHI_STATUS)
    url, options = calls[0]
    assert url == KALSHI_STATUS and options["allow_redirects"] is False
    assert options["timeout"] == (2.0, 3.0)
    assert "auth" not in options and "Authorization" not in options["headers"]


@pytest.mark.parametrize("retry", ["180", "Mon, 12 Oct 2026 20:03:00 GMT"])
def test_retry_after_is_honored_per_host_and_survives_restart_without_fake_successes(retry):
    now, calls = [NOW], []

    def get(url):
        calls.append(url)
        if url == KALSHI_STATUS:
            return Reply({}, 429, {"Retry-After": retry})
        assert url == US_EVENTS
        return Reply({"events": []})

    probe = PublicProbes(get=get, clock=lambda: now[0], region="us-east4")
    probe.poll()
    assert probe.state()["kalshi_latency"]["successful_samples"] == 0
    assert probe.state()["kalshi_latency"]["errors"] == 1
    assert probe.state()["kalshi_latency"]["backoff_until"] == NOW + 180
    probe = PublicProbes(get=get, clock=lambda: now[0], region="us-east4", initial=probe.state())
    now[0] += 30
    probe.poll()
    assert calls.count(KALSHI_STATUS) == 1 and calls.count(US_EVENTS) == 2
    now[0] = NOW + 180
    probe.poll()
    assert calls.count(KALSHI_STATUS) == 2


def test_listing_backoff_retains_first_seen_and_does_not_delay_independent_kalshi_probe():
    get, calls = transport()
    now = [NOW]
    probe = PublicProbes(get=get, clock=lambda: now[0])
    probe.poll()
    probe.get = lambda url: Reply({}, 429, {"Retry-After": "120"}) if url == US_EVENTS else get(url)
    probe.poll()
    checks = probe.state()["us_5m"]["checks"]
    now[0] += 30
    probe.poll()
    assert probe.state()["us_5m"]["checks"] == checks and probe.state()["us_5m"]["first_seen_at"] == NOW
    assert probe.state()["us_5m"]["backoff_until"] == NOW + 120
    assert calls.count(KALSHI_STATUS) == 3
