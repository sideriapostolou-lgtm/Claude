"""Shared fakes for the Kalshi recorder / Family A tests: realistic public rows and a scripted public API.

Rows follow the shapes of real public responses (``research/kalshi_edge_search/book_sample/`` and the
2026-10-13 audit). Nothing here touches the network.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

SAMPLE = Path(__file__).resolve().parents[1] / "research" / "kalshi_edge_search" / "book_sample"
NOW = datetime(2026, 10, 13, 18, 30, tzinfo=UTC).timestamp()


def iso(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sample(name: str) -> dict[str, Any]:
    return json.loads((SAMPLE / name).read_text(encoding="utf-8"))


def series_row(ticker: str = "KXHIGHNY", category: str = "Climate and Weather", *, fee_type: str = "quadratic",
               multiplier: Any = 1, tags: list[str] | None = None) -> dict[str, Any]:
    return {"ticker": ticker, "category": category, "categories": [category], "fee_type": fee_type,
            "fee_multiplier": multiplier, "frequency": "daily", "tags": tags or ["Daily temperature"],
            "settlement_sources": [{"name": "The Weather Company", "url": "https://weather.com/kalshi"}],
            "contract_terms_url": "https://assets.kalshi.com/contract_terms/GLOBALTEMPERATURE.pdf",
            "title": "Highest temperature in NYC"}


def event_row(event: str = "KXHIGHNY-26OCT15", series: str = "KXHIGHNY", category: str = "Climate and Weather",
              **extra: Any) -> dict[str, Any]:
    return {"event_ticker": event, "series_ticker": series, "category": category, "collateral_return_type": "",
            "mutually_exclusive": True, "exchange_index": 0,
            "settlement_sources": [{"name": "The Weather Company", "url": "https://weather.com/kalshi"}],
            "title": "Highest temperature in NYC", **extra}


def market_row(ticker: str = "KXHIGHNY-26OCT15-T76", event: str = "KXHIGHNY-26OCT15", *, now: float = NOW,
               open_offset: float = -36 * 3600, close_offset: float = 30 * 3600, **extra: Any) -> dict[str, Any]:
    row = {
        "ticker": ticker, "event_ticker": event, "market_type": "binary", "status": "active",
        "open_time": iso(now + open_offset), "close_time": iso(now + close_offset),
        "notional_value_dollars": "1.0000", "settlement_bounds_type": "default",
        "price_level_structure": "linear_cent",
        "price_ranges": [{"start": "0.0000", "end": "1.0000", "step": "0.0100"}],
        "rules_primary": "If the highest temperature recorded in Central Park is above 76 degrees, Yes.",
        "rules_secondary": "", "strike_type": "greater", "floor_strike": 76,
        "yes_bid_dollars": "0.3000", "yes_ask_dollars": "0.3300", "no_bid_dollars": "0.6700",
        "no_ask_dollars": "0.7000", "volume_24h_fp": "120.00", "volume_fp": "4000.00",
        "open_interest_fp": "900.00", "result": "", "settlement_value_dollars": None,
    }
    row.update(extra)
    return row


def orderbook(yes: list[tuple[str, str]], no: list[tuple[str, str]]) -> dict[str, Any]:
    """Kalshi's ``orderbook_fp``: ascending [price, size] bid lists for YES and NO."""
    return {"yes_dollars": [list(level) for level in sorted(yes)], "no_dollars": [list(level) for level in sorted(no)]}


class FakeResponse:
    def __init__(self, status: int, body: Any, headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self.headers = headers or {}
        self._raw = body if isinstance(body, bytes) else json.dumps(body).encode()

    def iter_content(self, size: int) -> Any:
        for index in range(0, len(self._raw), size):
            yield self._raw[index:index + size]

    def close(self) -> None:
        pass


class FakeKalshi:
    """A scripted public API keyed by path; records every (method, url, params, headers) it was asked for."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.routes: dict[str, Callable[[dict[str, list[str]]], FakeResponse]] = {}
        self.books: dict[str, dict[str, Any]] = {}
        self.trades: list[dict[str, Any]] = []
        self.series: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.markets: dict[str, dict[str, Any]] = {}
        self.fail: dict[str, list[int]] = {}

    def __call__(self, method: str, url: str, params: Any = None, headers: Any = None, **kwargs: Any) -> FakeResponse:
        parts = urlsplit(url)
        path = parts.path.removeprefix("/trade-api/v2")
        query: dict[str, list[str]] = {}
        for key, value in list(parse_qsl(parts.query)) + [(key, str(value)) for key, value in (params or [])]:
            query.setdefault(key, []).append(value)
        self.calls.append({"method": method, "url": url, "path": path, "query": query, "headers": dict(headers or {}),
                           "kwargs": kwargs})
        if self.fail.get(path):
            return FakeResponse(self.fail[path].pop(0), {"error": "scripted"})
        return self.route(path, query)

    def route(self, path: str, query: dict[str, list[str]]) -> FakeResponse:
        if path in self.routes:
            return self.routes[path](query)
        if path == "/markets/orderbooks":
            return FakeResponse(200, {"orderbooks": [{"ticker": ticker, "orderbook_fp": self.books[ticker]}
                                                     for ticker in query.get("tickers", []) if ticker in self.books]})
        if path == "/markets/trades":
            low, high = int(query["min_ts"][0]), int(query["max_ts"][0])
            ticker = query.get("ticker", [None])[0]
            rows = [row for row in self.trades
                    if low <= datetime.fromisoformat(row["created_time"]).timestamp() <= high + 1
                    and (ticker is None or row["ticker"] == ticker)]
            return FakeResponse(200, {"trades": sorted(rows, key=lambda row: row["created_time"], reverse=True),
                                      "cursor": ""})
        if path == "/series":
            category = query.get("category", [""])[0]
            return FakeResponse(200, {"series": [row for row in self.series.values() if row["category"] == category]})
        if path.startswith("/series/") and path != "/series/fee_changes":
            name = path.split("/")[2]
            return FakeResponse(200, {"series": self.series.get(name)})
        if path == "/events":
            return FakeResponse(200, {"events": self.events, "cursor": ""})
        if path == "/markets":
            if "tickers" in query:
                wanted = set(query["tickers"][0].split(","))
                return FakeResponse(200, {"markets": [row for ticker, row in self.markets.items() if ticker in wanted],
                                          "cursor": ""})
            series = query.get("series_ticker", [""])[0]
            rows = [row for row in self.markets.values() if row["event_ticker"].startswith(series + "-")]
            return FakeResponse(200, {"markets": rows, "cursor": ""})
        if path == "/series/fee_changes":
            return FakeResponse(200, {"series_fee_change_arr": []})
        if path == "/events/fee_changes":
            return FakeResponse(200, {"event_fee_changes": [], "cursor": ""})
        if path == "/historical/cutoff":
            return FakeResponse(200, {"market_settled_ts": "2026-08-14T00:00:00Z"})
        if path == "/incentive_programs":
            return FakeResponse(200, {"incentive_programs": [], "next_cursor": ""})
        return FakeResponse(404, {"error": "not found"})


class Clock:
    """Wall and monotonic time that only move when a test (or a fake sleep) moves them."""

    def __init__(self, at: float = NOW) -> None:
        self.at = at

    def wall(self) -> float:
        return self.at

    def mono(self) -> float:
        return self.at

    def sleep(self, seconds: float) -> None:
        self.at += max(seconds, 0.0)
