"""Multiple read-only venues share practice caps without sharing queue health."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from nightcrawler import speeddesk_kalshi, speeddesk_venues
from nightcrawler.config import Settings
from nightcrawler.speeddesk_model import Window


class Adapter:
    def __init__(self, _settings: Settings, **callbacks: Any) -> None:
        self.callbacks = callbacks
        self.windows: dict[str, Window] = {}
        self.reads: list[str] = []
        self.closed = False

    async def settlement(self, slug: str) -> float | None:
        self.reads.append(slug)
        return 1.0

    async def run(self, stop: threading.Event) -> None:
        try:
            while not stop.is_set():
                await asyncio.sleep(0)
        finally:
            self.closed = True


def make(monkeypatch, *, kalshi: bool = True):
    monkeypatch.setattr(speeddesk_venues, "LiveFeeds", Adapter)
    monkeypatch.setattr(speeddesk_kalshi, "KalshiFeeds", Adapter)
    statuses: list[dict[str, Any]] = []
    feeds = speeddesk_venues.MarketFeeds(Settings(speeddesk_kalshi_enabled=kalshi), on_status=statuses.append)
    return feeds, statuses


def test_tape_proof_and_gap_apply_only_to_the_correct_venue(monkeypatch) -> None:
    feeds, statuses = make(monkeypatch)
    us, kalshi = feeds.adapters["polymarket_us"], feeds.adapters["kalshi"]
    us.windows["cpc-btc-updown-15m-a"] = Window("cpc-btc-updown-15m-a", 0, 900)
    kalshi.windows["KXBTC15M-A"] = Window("KXBTC15M-A", 0, 900)
    us.callbacks["on_status"]({"coinbase": "connected", "trade_stream": True})
    kalshi.callbacks["on_status"]({"trade_stream": False})
    assert feeds.maker_windows() == set(us.windows)
    kalshi.callbacks["on_status"]({"trade_stream": True})
    assert feeds.maker_windows() == set(us.windows) | set(kalshi.windows)
    us.callbacks["on_status"]({"coinbase": "connected", "trade_stream": False})
    assert statuses[-1]["gap_windows"] == list(us.windows)
    assert statuses[-1]["trade_stream"]  # Kalshi's independent tape remains available.
    assert feeds.maker_windows() == set(kalshi.windows)
    us.callbacks["on_status"]({"coinbase": "connected", "trade_stream": True})
    kalshi.windows.clear()  # Metadata can disappear before the failure callback.
    kalshi.callbacks["on_status"]({"trade_stream": False})
    assert statuses[-1]["gap_windows"] == ["KXBTC15M-A"]
    assert statuses[-1]["trade_stream"]
    assert feeds.maker_windows() == set(us.windows)


def test_settlement_routes_to_the_venue_and_disabled_adapter_is_never_created(monkeypatch) -> None:
    feeds, _ = make(monkeypatch)
    assert asyncio.run(feeds.settlement("KXBTC15M-A")) == 1
    assert feeds.adapters["kalshi"].reads == ["KXBTC15M-A"]
    assert not feeds.adapters["polymarket_us"].reads
    assert asyncio.run(feeds.settlement("cpc-btc-updown-15m-a")) == 1
    disabled, _ = make(monkeypatch, kalshi=False)
    assert list(disabled.adapters) == ["polymarket_us"]
    assert asyncio.run(disabled.settlement("KXBTC15M-A")) is None


def test_composite_shutdown_closes_every_reader(monkeypatch) -> None:
    feeds, _ = make(monkeypatch)
    stop = threading.Event()

    async def exercise() -> None:
        task = asyncio.create_task(feeds.run(stop))
        await asyncio.sleep(0.02)
        stop.set()
        await task

    asyncio.run(exercise())
    assert all(adapter.closed for adapter in feeds.adapters.values())
