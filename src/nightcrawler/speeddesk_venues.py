"""Read-only venue routing for one shared practice inventory and risk budget."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from .config import Settings
from .speeddesk_feeds import LiveFeeds


class MarketFeeds:
    def __init__(self, settings: Settings, **callbacks: Any) -> None:
        self._on_status = callbacks.pop("on_status")
        self.status: dict[str, dict[str, Any]] = {}
        self.known_windows: dict[str, set[str]] = {}
        self.adapters: dict[str, Any] = {}
        self.adapters["polymarket_us"] = LiveFeeds(
            settings, **callbacks, on_status=lambda value: self._status("polymarket_us", value))
        if settings.speeddesk_kalshi_enabled:
            from .speeddesk_kalshi import KalshiFeeds

            self.adapters["kalshi"] = KalshiFeeds(
                settings, **callbacks, on_status=lambda value: self._status("kalshi", value))

    def _status(self, venue: str, value: dict[str, Any]) -> None:
        previous = self.status.get(venue, {})
        self.status[venue] = value
        windows = set(self.adapters[venue].windows)
        previous_windows = self.known_windows.get(venue, set())
        gap = windows | previous_windows if previous.get("trade_stream") and not value.get("trade_stream") else set()
        # A sequence gap can precede the first trade. Propagate it independently
        # of the other venue's health and of the aggregate tape flag.
        explicit = value.get("gap_windows", [])
        if isinstance(explicit, list):
            gap |= {slug for slug in explicit if isinstance(slug, str)} & (windows | previous_windows)
        self.known_windows[venue] = windows
        self._on_status({"coinbase": self.status.get("polymarket_us", {}).get("coinbase", "connecting"),
                         "markets": "venue_adapters", "venues": dict(self.status), "gap_windows": sorted(gap),
                         "trade_stream": any(item.get("trade_stream") for item in self.status.values())})

    def maker_windows(self) -> set[str]:
        result: set[str] = set()
        for venue, adapter in self.adapters.items():
            status = self.status.get(venue, {})
            if not status.get("trade_stream"):
                continue
            explicit = status.get("maker_windows")
            result |= set(adapter.windows) & set(explicit) if isinstance(explicit, list) else set(adapter.windows)
        return result

    async def settlement(self, slug: str) -> float | None:
        venue = "kalshi" if slug.startswith("KXBTC15M-") else "polymarket_us"
        adapter = self.adapters.get(venue)
        if adapter is None:
            return None
        result: float | None = await adapter.settlement(slug)
        return result

    async def run(self, stop: threading.Event) -> None:
        tasks = [asyncio.create_task(adapter.run(stop)) for adapter in self.adapters.values()]
        try:
            while not stop.is_set():
                for task in tasks:
                    if task.done():
                        task.result()
                        if not stop.is_set():
                            raise RuntimeError("Practice venue feed exited")
                await asyncio.sleep(0.1)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
