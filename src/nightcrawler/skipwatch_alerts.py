"""Public GET probes: verified US five-minute listings and Kalshi HTTP round-trip timing.

Verified 2026-10-12 against docs.polymarket.us/api-reference/events/get-events,
markets/get-market-by-slug and docs.kalshi.com/openapi.yaml (/exchange/status).
No credential, SDK account, order resource, or trading-universe mutation is used.
The runtime persists ``state()`` and journals each event returned by ``poll()``.
"""

from __future__ import annotations

import copy
import math
import re
import statistics
import threading
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import requests

from .speeddesk_feeds import number, timestamp

US_BASE = "https://gateway.polymarket.us"
US_EVENTS = US_BASE + "/v1/events?seriesId=387&limit=10&offset=0&orderBy=endDate&orderDirection=desc"
KALSHI_STATUS = "https://api.elections.kalshi.com/trade-api/v2/exchange/status"
BINANCE_PING = "https://api.binance.com/api/v3/ping"
ROLLING_SECONDS = 3600
MAX_SAMPLES = 256
MAX_BACKOFF_SECONDS = 7 * 86400
REGION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
MARKET_PATTERN = re.compile(r"cpc-btc-updown-5m-\d{4}-\d{2}-\d{2}-\d{4}z\Z")
LIMITATION = "Single-region HTTP measurement; no evidence that moving regions would help."


def _public_get(url: str) -> Any:
    return requests.get(url, timeout=(2.0, 3.0), allow_redirects=False,
                        headers={"Accept": "application/json", "User-Agent": "nightcrawler-public-watch/1"})


def verified_window(reply: Any, slug: str) -> dict[str, Any] | None:
    """A series name is insufficient: require one exact market and its five-minute BTC terms."""
    if not MARKET_PATTERN.fullmatch(slug):
        return None
    market = reply.get("market") if isinstance(reply, dict) else None
    if not isinstance(market, dict) or market.get("slug") != slug:
        return None
    terms = market.get("assetPriceTerms")
    if not isinstance(terms, dict) or not isinstance(terms.get("asset"), dict):
        return None
    start, end = timestamp(terms.get("windowStart")), timestamp(terms.get("windowEnd"))
    if (str(terms["asset"].get("symbol")).lower() != "btc" or terms.get("horizon") != "5m"
            or terms.get("marketType") != "ASSET_PRICE_MARKET_TYPE_UP_DOWN" or terms.get("indexSymbol") != "BRTI"
            or start is None or end is None or end - start != 300):
        return None
    expected = "cpc-btc-updown-5m-" + datetime.fromtimestamp(start, UTC).strftime("%Y-%m-%d-%H%Mz")
    if slug != expected:
        return None
    return {"market": slug, "window_start": start, "window_end": end}


def _read(response: Any) -> Any:
    if response.status_code != 200:
        raise ValueError("http_status")
    return response.json()


class PublicProbes:
    """Bounded, restartable observational probes. Injected transports make all tests offline."""

    def __init__(self, *, get: Callable[[str], Any] | None = None, clock: Callable[[], float] = time.time,
                 monotonic: Callable[[], float] = time.monotonic, region: str | None = None,
                 initial: Mapping[str, Any] | None = None, check_availability: bool = False) -> None:
        self.get, self.clock, self.monotonic = get or _public_get, clock, monotonic
        self.check_availability = check_availability
        self.region = region if isinstance(region, str) and REGION_PATTERN.fullmatch(region) else None
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {}
        self.restore(initial)

    def restore(self, initial: Mapping[str, Any] | None) -> None:
        """Keep first-seen evidence and same-region samples; corrupt evidence is explicitly unavailable."""
        initial = initial if isinstance(initial, Mapping) else {}
        now = self.clock()
        raw_us = initial.get("us_5m")
        us = raw_us if isinstance(raw_us, Mapping) else {}
        first = number(us.get("first_seen_at"))
        start, end = number(us.get("first_window_start")), number(us.get("first_window_end"))
        slug = us.get("first_market")
        try:
            named_start = datetime.strptime(str(slug), "cpc-btc-updown-5m-%Y-%m-%d-%H%Mz").replace(tzinfo=UTC).timestamp()
        except (ValueError, OverflowError):
            named_start = None
        valid = bool(first is not None and first <= now + 5 and start is not None and end is not None
                     and end - start == 300 and isinstance(slug, str) and MARKET_PATTERN.fullmatch(slug)
                     and start == named_start)
        restored = {"first_seen_at": first if valid else None, "first_market": slug if valid else None,
                    "first_window_start": start if valid else None, "first_window_end": end if valid else None,
                    "last_checked_at": number(us.get("last_checked_at")),
                    "last_success_at": number(us.get("last_success_at")), "checks": 0, "errors": 0,
                    "status": "Verified five-minute window previously observed" if valid else "Not checked yet"}
        for key in ("checks", "errors"):
            value = us.get(key)
            restored[key] = value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
        if us.get("first_seen_at") is not None and not valid:
            restored["status"] = "Saved listing evidence is invalid; waiting for a new verified observation"
        samples = []
        if self.region is not None and initial.get("region") == self.region:
            raw_samples = initial.get("samples")
            for raw in raw_samples[-MAX_SAMPLES:] if isinstance(raw_samples, list) else []:
                if not isinstance(raw, dict):
                    continue
                at, rtt = number(raw.get("at")), number(raw.get("rtt_ms"))
                error = raw.get("error")
                if (at is not None and now - ROLLING_SECONDS <= at <= now + 5
                        and error in (None, "timeout", "http_or_payload", "transport")
                        and (error is not None or rtt is not None and 0 <= rtt <= 60_000)):
                    samples.append({"at": at, "rtt_ms": rtt if error is None else None, "error": error})
        with self._lock:
            raw_retry = initial.get("retry_at")
            retry_at = raw_retry if isinstance(raw_retry, Mapping) else {}
            availability = initial.get("binance_availability")
            self._state = {"version": 1, "region": self.region, "as_of": None, "us_5m": restored, "samples": samples,
                           "binance_availability": (dict(availability) if isinstance(availability, Mapping)
                                                    and initial.get("region") == self.region else None),
                           "retry_at": {host: min(now + MAX_BACKOFF_SECONDS, max(now, number(retry_at.get(host)) or now))
                                        for host in ("us", "kalshi")}}

    def state(self) -> dict[str, Any]:
        with self._lock:
            out = copy.deepcopy(self._state)
        now = self.clock()
        out["samples"] = [s for s in out["samples"] if now - ROLLING_SECONDS <= s["at"] <= now + 5][-MAX_SAMPLES:]
        samples = out["samples"]
        out["us_5m"]["backoff_until"] = out["retry_at"]["us"] if out["retry_at"]["us"] > now else None
        good = sorted(s["rtt_ms"] for s in samples if s["error"] is None)
        out["kalshi_latency"] = {
            "endpoint": "/trade-api/v2/exchange/status", "rolling_window_s": ROLLING_SECONDS,
            "measurements": len(samples), "successful_samples": len(good),
            "errors": sum(s["error"] is not None for s in samples),
            "timeouts": sum(s["error"] == "timeout" for s in samples),
            "median_ms": statistics.median(good) if good else None,
            "p95_ms": good[math.ceil(.95 * len(good)) - 1] if good else None,
            "last_rtt_ms": samples[-1]["rtt_ms"] if samples else None,
            "last_checked_at": samples[-1]["at"] if samples else None,
            "region": self.region, "limitation": LIMITATION,
            "backoff_until": out["retry_at"]["kalshi"] if out["retry_at"]["kalshi"] > now else None,
        }
        return out

    def _backoff(self, state: dict[str, Any], response: Any, host: str) -> None:
        """Honor 429 Retry-After seconds or HTTP dates independently for each public host (up to one week)."""
        if response.status_code != 429:
            return
        headers = getattr(response, "headers", {})
        value = headers.get("Retry-After") if isinstance(headers, Mapping) else None
        now = self.clock()
        delay = number(value)
        if delay is None and isinstance(value, str):
            try:
                at = parsedate_to_datetime(value)
                delay = at.timestamp() - now if at.tzinfo is not None else None
            except (ValueError, TypeError, OverflowError):
                delay = None
        state["retry_at"][host] = now + min(MAX_BACKOFF_SECONDS, max(30.0, delay if delay is not None else 30.0))

    def _latency(self, state: dict[str, Any]) -> None:
        if self.clock() < state["retry_at"]["kalshi"]:
            return
        start = self.monotonic()
        rtt: float | None = None
        error: str | None = None
        try:
            response = self.get(KALSHI_STATUS)
            rtt = max(0.0, (self.monotonic() - start) * 1000)
            self._backoff(state, response, "kalshi")
            raw = _read(response)
            if (not isinstance(raw, dict) or not isinstance(raw.get("exchange_active"), bool)
                    or not isinstance(raw.get("trading_active"), bool)):
                raise TypeError("invalid_status")
        except (requests.Timeout, TimeoutError):
            error = "timeout"
        except (ValueError, TypeError, AttributeError):
            error = "http_or_payload"
        except Exception:  # noqa: BLE001 — never echo transport exceptions, URLs or provider bodies.
            error = "transport"
        state["samples"].append({"at": self.clock(), "rtt_ms": rtt if error is None else None, "error": error})
        state["samples"] = state["samples"][-MAX_SAMPLES:]

    def _listing(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        us = state["us_5m"]
        if self.clock() < state["retry_at"]["us"]:
            us["status"] = "Listing checks paused for the venue's Retry-After backoff; first observation retained"
            return []
        us["last_checked_at"] = self.clock()
        us["checks"] += 1
        try:
            response = self.get(US_EVENTS)
            self._backoff(state, response, "us")
            raw = _read(response)
            events = raw.get("events") if isinstance(raw, dict) else None
            if not isinstance(events, list):
                raise TypeError("invalid_events")
            candidates = []
            for event in events[:10]:
                if not isinstance(event, dict) or event.get("seriesSlug") != "btc-updown-5m":
                    raise ValueError("series_filter_unverified")
                for market in event.get("markets", []) if isinstance(event.get("markets"), list) else []:
                    slug = market.get("slug") if isinstance(market, dict) else None
                    if isinstance(slug, str) and MARKET_PATTERN.fullmatch(slug) and slug not in candidates:
                        candidates.append(slug)
            for slug in candidates[:10]:
                response = self.get(US_BASE + "/v1/market/slug/" + slug)
                self._backoff(state, response, "us")
                found = verified_window(_read(response), slug)
                if found is None:
                    continue
                us["last_success_at"] = self.clock()
                us["status"] = "Verified five-minute window observed; not added to trading"
                if us["first_seen_at"] is None:
                    at = self.clock()
                    us.update(first_seen_at=at, first_market=found["market"],
                              first_window_start=found["window_start"], first_window_end=found["window_end"])
                    return [{"kind": "skipwatch_us_5m_listing", "at": at, **found,
                             "evidence": "verified_public_market_terms", "real_orders_available": False}]
                return []
            us["last_success_at"] = self.clock()
            us["status"] = ("First verified observation saved; no matching window in this check" if us["first_seen_at"]
                            else "No verified window among the latest ten series events")
        except Exception as exc:  # noqa: BLE001 — isolated public lookup; never echo remote text.
            us["errors"] += 1
            us["status"] = "Listing check failed (" + type(exc).__name__ + "); saved first observation retained"
        return []

    def _availability(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """One public availability request, persisted across restarts. Never bypass or retry a denial."""
        if state.get("binance_availability") is not None:
            return []
        status, result = None, "transport_unavailable"
        try:
            response = self.get(BINANCE_PING)
            value = response.status_code
            status = value if isinstance(value, int) and 100 <= value <= 599 else None
            if status in (403, 451):
                result = "access_denied_no_retry"
            elif status == 200 and response.json() == {}:
                result = "public_ping_reachable_feed_not_tested"
            else:
                result = "http_unavailable_no_retry"
        except Exception:  # noqa: BLE001 — transport/provider text is neither needed nor safe to echo.
            result = "transport_unavailable"
        evidence = {"at": self.clock(), "region": self.region, "http_status": status, "result": result,
                    "requests": 1, "feed_enabled": False, "retry_scheduled": False}
        state["binance_availability"] = evidence
        return [{"kind": "skipwatch_binance_availability", **evidence}]

    def poll(self) -> list[dict[str, Any]]:
        """One sequential probe cycle. Returned first-seen event must be durably logged by the caller."""
        state = self.state()
        state.pop("kalshi_latency", None)
        self._latency(state)
        events = self._listing(state)
        if self.check_availability:
            events.extend(self._availability(state))
        state["as_of"] = self.clock()
        with self._lock:
            self._state = state
        return events
