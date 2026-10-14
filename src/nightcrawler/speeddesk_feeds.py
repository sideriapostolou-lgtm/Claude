"""Read-only live inputs for the practice speed desk.

The SDK is used only for ``client.ws.markets()``. Neither its private stream nor
its order resource is accessed. Public REST book snapshots cannot create maker
fills: only the authenticated markets trade stream supplies ``Trade`` objects.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import requests

from .config import Secret, Settings
from .speeddesk_model import FUTURE_SKEW_S, Book, Level, Trade, Window

log = logging.getLogger("nightcrawler.speeddesk_feeds")
GATEWAY = "https://gateway.polymarket.us"
COINBASE_WS = "wss://advanced-trade-ws.coinbase.com"
# Speed plan step 4 (2026-10-13): Coinbase Exchange's "matches" channel delivers each trade on its own, 50 to 61 ms
# (median) before Advanced Trade's batches. Two Exchange connections lead; Advanced Trade stays as the backup. They
# share one trade-id space (no price mismatch in 4,280 shared trades), so each trade is delivered once, by
# whichever connection brings it first, and Bitcoin ticks keep flowing while any connection is up.
COINBASE_EXCHANGE_WS = "wss://ws-feed.exchange.coinbase.com"
COINBASE_FEEDS = (("exchange_a", COINBASE_EXCHANGE_WS), ("exchange_b", COINBASE_EXCHANGE_WS),
                  ("advanced_trade", COINBASE_WS))
SEEN_TRADE_IDS = 20000
# Future-stamped Coinbase trades (refused) are counted per connection and reported this often at most.
SKEW_REPORT_S = 10.0
# https://docs.polymarket.us/fees, verified 2026-10-12: standard, non-combo
# maker theta is -0.0125; rounded per fill to cents with half-even rounding.
DOCUMENTED_MAKER_COEFFICIENT = -0.0125


def number(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if math.isfinite(out) else None


def timestamp(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except (ValueError, OverflowError):
        return None


def window_slugs(now: float) -> list[str]:
    """Only the current and next US 15-minute and hourly windows."""
    out = []
    for horizon, seconds in (("15m", 900), ("1h", 3600)):
        current = int(now // seconds) * seconds
        for start in (current, current + seconds):
            suffix = datetime.fromtimestamp(start, UTC).strftime("%Y-%m-%d-%H%Mz")
            out.append(f"cpc-btc-updown-{horizon}-{suffix}")
    return out


def parse_window(reply: Any, slug: str) -> Window | None:
    raw = reply.get("market") if isinstance(reply, dict) else None
    if not isinstance(raw, dict) or raw.get("slug") != slug:
        return None
    terms = raw.get("assetPriceTerms")
    if not isinstance(terms, dict):
        return None
    asset = terms.get("asset")
    horizon = terms.get("horizon")
    start, end = timestamp(terms.get("windowStart")), timestamp(terms.get("windowEnd"))
    description = str(raw.get("description") or "").lower()
    fee, tick = number(raw.get("feeCoefficient")), number(raw.get("orderPriceMinTickSize"))
    minimum = number(raw.get("minimumTradeQty"))
    if (not isinstance(asset, dict) or str(asset.get("symbol")).lower() != "btc"
            or terms.get("indexSymbol") != "BRTI" or horizon not in ("15m", "1h")
            or terms.get("marketType") != "ASSET_PRICE_MARKET_TYPE_UP_DOWN"
            or start is None or end is None or end - start != {"15m": 900, "1h": 3600}[horizon]
            or slug not in window_slugs(start) or not slug.startswith(f"cpc-btc-updown-{horizon}-")
            or "settle to up" not in description or "greater than or equal" not in description
            or fee is None or fee < 0 or fee > 1 or tick is None or not 0 < tick < 1
            or minimum is None or minimum <= 0
            or raw.get("comboEnabled") is not False):
        return None
    venue_start = number(terms.get("priceToBeat"))
    return Window(slug=slug, start=start, end=end, start_price=None,
                  venue_start_price=venue_start if venue_start and venue_start > 0 else None,
                  taker_coefficient=fee,
                  maker_coefficient=DOCUMENTED_MAKER_COEFFICIENT if fee == 0.0695 else None,
                  tick_size=tick, min_trade_qty=minimum)


def _levels(raw: Any, *, reverse: bool = False) -> tuple[Level, ...] | None:
    if not isinstance(raw, list):
        return None
    levels: dict[float, float] = {}
    for row in raw:
        if not isinstance(row, dict):
            return None
        price, size = number(row.get("px")), number(row.get("qty"))
        if price is None or size is None or not 0 < price < 1 or size < 0:
            return None
        if size:
            levels[price] = levels.get(price, 0.0) + size
    return tuple(Level(price, size) for price, size in sorted(levels.items(), reverse=reverse))


def parse_books(reply: Any, received_at: float, *, source: str = "websocket") -> tuple[Book, ...]:
    raw = reply.get("marketData") if isinstance(reply, dict) else None
    if not isinstance(raw, dict) or not isinstance(raw.get("marketSlug"), str):
        return ()
    slug = raw["marketSlug"]
    bids, asks = _levels(raw.get("bids"), reverse=True), _levels(raw.get("offers"))
    exchange_at = timestamp(raw.get("transactTime"))
    if bids is None or asks is None or exchange_at is None:
        return ()
    if raw.get("state") != "MARKET_STATE_OPEN" or (bids and asks and bids[0].price >= asks[0].price):
        bids, asks = (), ()  # An explicit closed/crossed snapshot invalidates earlier quotes.
    sequence = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return (
        Book(slug, "up", bids, asks, received_at, sequence, exchange_at, source),
        Book(slug, "down", tuple(Level(round(1 - x.price, 8), x.size) for x in asks),
             tuple(Level(round(1 - x.price, 8), x.size) for x in bids),
             received_at, sequence, exchange_at, source),
    )


def parse_trades(reply: Any, received_at: float) -> tuple[Trade, ...]:
    raw = reply.get("trade") if isinstance(reply, dict) else None
    if not isinstance(raw, dict) or not isinstance(raw.get("marketSlug"), str):
        return ()
    price, size, at = number(raw.get("price")), number(raw.get("quantity")), timestamp(raw.get("tradeTime"))
    taker = raw.get("taker")
    intent = taker.get("intent") if isinstance(taker, dict) else None
    # The venue quotes every trade in YES dollars; BUY_SHORT is an aggressive
    # YES sale. Unknown intent is not evidence of a sale into our resting bid.
    up_buy = intent in ("ORDER_INTENT_BUY_LONG", "ORDER_INTENT_SELL_SHORT")
    up_sell = intent in ("ORDER_INTENT_SELL_LONG", "ORDER_INTENT_BUY_SHORT")
    if (price is None or size is None or at is None or not 0 < price < 1 or size <= 0
            or not (up_buy or up_sell)):
        return ()
    # The documented trade schema has no trade ID. Identical time/price/size/
    # side prints conservatively share one identity, rather than double-count.
    identity = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return (
        Trade(raw["marketSlug"], "up", price, size, at, identity + ":up",
              "buy" if up_buy else "sell", received_at),
        Trade(raw["marketSlug"], "down", round(1 - price, 8), size, at, identity + ":down",
              "sell" if up_buy else "buy", received_at),
    )


def _trade_id(value: Any) -> int | None:
    """Coinbase's integer trade id (Advanced Trade sends it as a decimal string); anything else is unknown."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return int(value) if isinstance(value, str) and value.isdigit() else None


def advanced_trade_ticks(reply: Any) -> list[tuple[float, float, int | None]]:
    """Advanced Trade ``market_trades``: (price, exchange time, trade id), oldest first.

    Heartbeats aren't ticks, and neither is the ``snapshot`` event of past trades replayed on every (re)connect.
    """
    if not isinstance(reply, dict) or reply.get("channel") != "market_trades":
        return []
    rows: list[tuple[float, float, int | None]] = []
    events = reply.get("events")
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict) or event.get("type") == "snapshot":
            continue
        trades = event.get("trades")
        for trade in trades if isinstance(trades, list) else []:
            if not isinstance(trade, dict) or trade.get("product_id") != "BTC-USD":
                continue
            price, at = number(trade.get("price")), timestamp(trade.get("time"))
            if price is not None and price > 0 and at is not None:
                rows.append((price, at, _trade_id(trade.get("trade_id"))))
    return sorted(rows, key=lambda row: (row[1], -1 if row[2] is None else row[2]))


def coinbase_ticks(reply: Any) -> list[tuple[float, float]]:
    """Price and exchange time from Advanced Trade; heartbeats and replayed snapshots aren't ticks."""
    return [(price, at) for price, at, _trade in advanced_trade_ticks(reply)]


def exchange_ticks(reply: Any) -> list[tuple[float, float, int | None]]:
    """Coinbase Exchange ``matches``: one (price, exchange time, trade id) per ``match`` message.

    ``last_match``, sent once on every subscribe, replays a trade already past; heartbeats and subscription
    replies are not ticks either.
    """
    if not isinstance(reply, dict) or reply.get("type") != "match" or reply.get("product_id") != "BTC-USD":
        return []
    price, at = number(reply.get("price")), timestamp(reply.get("time"))
    if price is None or price <= 0 or at is None:
        return []
    return [(price, at, _trade_id(reply.get("trade_id")))]


_THREAD = threading.local()


def thread_session() -> requests.Session:
    """This thread's kept-alive HTTP session (speed plan step 8). asyncio's worker threads are reused, so each
    keeps its connections instead of a new TCP and TLS handshake on every public poll; no session is shared
    between threads."""
    session: requests.Session | None = getattr(_THREAD, "session", None)
    if session is None:
        session = _THREAD.session = requests.Session()
    return session


def _public_get(path: str) -> Any:
    response = thread_session().get(GATEWAY + path, timeout=10)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


class LiveFeeds:
    """Async market-data readers with injected transports for safety tests."""

    def __init__(self, settings: Settings, *, on_tick: Callable[[float, float, float], None],
                 on_book: Callable[[Book], None], on_trade: Callable[[Trade], None],
                 on_windows: Callable[[list[Window]], None], on_status: Callable[[dict[str, Any]], None],
                 sdk_client: Any = None, rest_get: Callable[[str], Any] | None = None,
                 clock: Callable[[], float] = time.time, coinbase_connect: Any = None) -> None:
        self._key_id = settings.polymarket_us_key_id
        self._secret_key = settings.polymarket_us_secret_key
        self._client = sdk_client
        self._rest_get = rest_get or _public_get
        self._clock = clock
        self._coinbase_connect = coinbase_connect
        self.on_tick, self.on_book, self.on_trade = on_tick, on_book, on_trade
        self.on_windows, self.on_status = on_windows, on_status
        self.windows: dict[str, Window] = {}
        self._book_seen: dict[str, float] = {}
        self._last_rest_book = -math.inf
        self._rest_book_retry_at = -math.inf
        self._rest_index = 0
        self._market_seen = 0.0
        self._market_connected = False
        self._subscription_error = False
        self._coinbase_up: dict[str, bool] = {name: False for name, _url in COINBASE_FEEDS}
        self._seen_trades: set[int] = set()
        self._seen_order: deque[int] = deque()
        self._latest_trade_at = -math.inf
        self._latest_trade_id: int | None = None
        # Trades each connection brought stamped further ahead of the local clock than FUTURE_SKEW_S (the desks
        # refuse them), reported in the status at most every SKEW_REPORT_S.
        self._future_stamped: dict[str, int] = {name: 0 for name, _url in COINBASE_FEEDS}
        self._future_reported_at = -math.inf
        self._status: dict[str, Any] = {"coinbase": "connecting", "markets": "connecting", "trade_stream": False}

    def _report(self, **changes: Any) -> None:
        self._status.update(changes)
        self.on_status(dict(self._status))

    async def refresh_windows(self) -> None:
        async def fetch(slug: str) -> Window | None:
            try:
                raw = await asyncio.to_thread(self._rest_get, f"/v1/market/slug/{slug}")
                return parse_window(raw, slug)
            except Exception as exc:  # noqa: BLE001 — keep the feed alive; never echo transport credentials.
                log.warning("speeddesk_feed_metadata_failed error=%s", type(exc).__name__)
                return self.windows.get(slug)

        windows = await asyncio.gather(*(fetch(slug) for slug in window_slugs(self._clock())))
        self.windows = {window.slug: window for window in windows if window is not None}
        self.on_windows(list(self.windows.values()))

    def _book(self, reply: Any, *, source: str = "websocket", requested_at: float | None = None) -> bool:
        now = self._clock()
        delivered = False
        for book in parse_books(reply, now, source=source):
            if requested_at is not None:
                book = replace(book, requested_at=requested_at)
            if book.window in self.windows:
                if source == "websocket":
                    self._book_seen[book.window] = now
                    self._market_seen = now
                self.on_book(book)
                delivered = True
        return delivered

    def _trade(self, reply: Any) -> None:
        now = self._clock()
        for trade in parse_trades(reply, now):
            if trade.window in self.windows:
                self._market_seen = now
                if self._market_connected and now - 3 <= trade.at <= now + 1 and not self._status["trade_stream"]:
                    self._report(trade_stream=True)
                self.on_trade(trade)

    async def poll_book(self) -> bool:
        """A single REST book, globally capped at one request per second."""
        now = self._clock()
        if now - self._last_rest_book < 1 or now < self._rest_book_retry_at:
            return False
        slugs = [slug for slug, window in self.windows.items()
                 if window.start <= now < window.end
                 and (not self._market_connected or now - self._book_seen.get(slug, 0) > 3)]
        if not slugs:
            return False
        slug = slugs[self._rest_index % len(slugs)]
        self._rest_index += 1
        self._last_rest_book = now  # Failed reads count against the global limit too.

        def fetch() -> tuple[Any, float]:
            requested_at = self._clock()
            self._last_rest_book = requested_at
            return self._rest_get(f"/v1/markets/{slug}/book"), requested_at

        try:
            raw, requested_at = await asyncio.to_thread(fetch)
            if self._book(raw, source="rest", requested_at=requested_at):
                self._report(rest_books="snapshot_received", rest_retry_at=None, rest_http_status=200)
        except Exception as exc:  # noqa: BLE001 — a failed data read must not stop other streams.
            response = exc.response if isinstance(exc, requests.HTTPError) else None
            status = response.status_code if response is not None else None
            delay = 30 if status in (403, 429) else 5
            self._rest_book_retry_at = self._clock() + delay
            self._report(rest_books="rate_limited" if status == 429 else "unavailable",
                         rest_retry_at=self._rest_book_retry_at, rest_http_status=status)
            log.warning("speeddesk_feed_book_failed error=%s http_status=%s retry_s=%s",
                        type(exc).__name__, status, delay)
        return True

    async def settlement(self, slug: str) -> float | None:
        if not slug.startswith(("cpc-btc-updown-15m-", "cpc-btc-updown-1h-")):
            return None
        try:
            raw = await asyncio.to_thread(self._rest_get, f"/v1/markets/{slug}/settlement")
        except Exception as exc:  # noqa: BLE001 — unknown settlement remains unbooked.
            log.warning("speeddesk_feed_settlement_failed error=%s", type(exc).__name__)
            return None
        if not isinstance(raw, dict) or raw.get("slug", slug) != slug:
            return None
        value = number(raw.get("settlement"))
        return value if value in (0.0, 1.0) else None

    def _first_delivery(self, trade_id: int | None, at: float) -> bool:
        """Deduplicate copies and order trades sharing a timestamp by Coinbase's increasing product trade id.

        Both Exchange connections can miss an older trade on reconnect; Advanced Trade may then deliver that
        unseen trade after a newer one with the same stamp. Letting it through would move the tape price back
        and refresh its receipt. Different older stamps are already refused by BitcoinTape. Unknown ids retain
        the existing timestamp-only behavior; they cannot supply evidence of relative order.
        """
        if trade_id is not None:
            if trade_id in self._seen_trades:
                return False
            self._seen_trades.add(trade_id)
            self._seen_order.append(trade_id)
            while len(self._seen_order) > SEEN_TRADE_IDS:
                self._seen_trades.discard(self._seen_order.popleft())
            if at == self._latest_trade_at and self._latest_trade_id is not None and trade_id < self._latest_trade_id:
                return False
        if at > self._latest_trade_at:
            self._latest_trade_at, self._latest_trade_id = at, trade_id
        elif at == self._latest_trade_at and trade_id is not None:
            self._latest_trade_id = trade_id
        return True

    def _future_stamp(self, name: str, now: float) -> None:
        self._future_stamped[name] = self._future_stamped.get(name, 0) + 1
        if now - self._future_reported_at >= SKEW_REPORT_S:
            self._future_reported_at = now
            self._report(coinbase_future_stamped=dict(self._future_stamped))

    def _coinbase_state(self, name: str, up: bool) -> None:
        """Bitcoin data counts as connected while any one connection is up; each one's state is reported too."""
        if self._coinbase_up.get(name) == up and self._status.get("coinbase") != "connecting":
            return
        self._coinbase_up[name] = up
        self._report(coinbase="connected" if any(self._coinbase_up.values()) else "disconnected",
                     coinbase_feeds={feed: "connected" if state else "disconnected"
                                     for feed, state in self._coinbase_up.items()})

    async def _coinbase(self) -> None:
        await asyncio.gather(*(self._coinbase_feed(name, url) for name, url in COINBASE_FEEDS))

    async def _coinbase_feed(self, name: str, url: str) -> None:
        from websockets.asyncio.client import connect

        connect_ws = self._coinbase_connect or connect
        exchange = url == COINBASE_EXCHANGE_WS
        subscriptions = ([{"type": "subscribe", "product_ids": ["BTC-USD"], "channels": ["matches", "heartbeat"]}]
                         if exchange else
                         [{"type": "subscribe", "product_ids": ["BTC-USD"], "channel": channel}
                          for channel in ("market_trades", "heartbeats")])
        parse = exchange_ticks if exchange else advanced_trade_ticks
        while True:
            try:
                async with connect_ws(url, open_timeout=10, ping_interval=20, ping_timeout=10) as ws:
                    for subscription in subscriptions:
                        await ws.send(json.dumps(subscription))
                    self._coinbase_state(name, True)
                    log.info("speeddesk_feed_coinbase_connected product=BTC-USD feed=%s", name)
                    while True:
                        message = await asyncio.wait_for(ws.recv(), timeout=10)
                        received_at = self._clock()
                        reply = json.loads(message)
                        for price, at, trade_id in parse(reply):
                            if received_at - at < -FUTURE_SKEW_S:
                                # Refused by every desk, so it must not use up the trade id (latency review,
                                # 2026-10-13): another connection's later copy may be inside the bound.
                                self._future_stamp(name, received_at)
                                continue
                            if self._first_delivery(trade_id, at):
                                self.on_tick(price, at, received_at)
            except Exception as exc:  # noqa: BLE001 — reconnect on transport/protocol failure.
                self._coinbase_state(name, False)
                log.warning("speeddesk_feed_coinbase_disconnected feed=%s error=%s", name, type(exc).__name__)
                await asyncio.sleep(2)

    def _ws_error(self, error: Any) -> None:
        self._subscription_error = True
        self._market_connected = False
        self._report(markets="subscription_error", trade_stream=False)
        log.warning("speeddesk_feed_markets_error error=%s", type(error).__name__)

    def _ws_closed(self) -> None:
        self._market_connected = False
        self._report(markets="disconnected_rest_fallback", trade_stream=False)

    def _heartbeat(self) -> None:
        self._market_seen = self._clock()

    async def _markets(self) -> None:
        if not self._key_id or not self._secret_key:
            self._report(markets="missing_credentials_rest_only", trade_stream=False)
            log.warning("speeddesk_feed_markets_missing_credentials maker_fills=disabled")
            return
        if self._client is None:
            from polymarket_us import PolymarketUS

            # Settings.from_env wraps credentials in Secret, even though these
            # legacy fields are annotated str. The SDK must receive plaintext
            # only at this in-memory authentication boundary, never str(Secret).
            key_id = self._key_id.reveal() if isinstance(self._key_id, Secret) else self._key_id
            secret_key = self._secret_key.reveal() if isinstance(self._secret_key, Secret) else self._secret_key
            self._client = PolymarketUS(key_id=key_id, secret_key=secret_key,
                                       timeout=10, max_retries=0)
        while True:
            ws = None
            try:
                ws = self._client.ws.markets()
                ws.on("market_data", self._book)
                ws.on("trade", self._trade)
                ws.on("heartbeat", self._heartbeat)
                ws.on("error", self._ws_error)
                ws.on("close", self._ws_closed)
                self._subscription_error = False
                await asyncio.wait_for(ws.connect(), timeout=15)
                self._market_connected = True
                self._market_seen = self._clock()
                subscribed: tuple[str, ...] = ()
                generation = 0
                # No SDK acknowledgement proves the tape is active. A valid
                # current trade frame below enables simulated resting orders.
                self._report(markets="connected", trade_stream=False)
                log.info("speeddesk_feed_markets_connected mode=PRACTICE")
                while ws.is_connected and not self._subscription_error:
                    slugs = tuple(sorted(self.windows))
                    if slugs != subscribed:
                        self._report(trade_stream=False)
                        if subscribed:
                            await ws.unsubscribe(f"speed-books-{generation}")
                            await ws.unsubscribe(f"speed-trades-{generation}")
                        generation += 1
                        if slugs:
                            await ws.subscribe_market_data(f"speed-books-{generation}", list(slugs))
                            await ws.subscribe_trades(f"speed-trades-{generation}", list(slugs))
                        subscribed = slugs
                    if self._clock() - self._market_seen > 15:
                        break
                    await asyncio.sleep(0.5)
            except Exception as exc:  # noqa: BLE001 — reconnect on SDK/transport failure.
                log.warning("speeddesk_feed_markets_disconnected error=%s", type(exc).__name__)
            finally:
                self._market_connected = False
                self._book_seen.clear()
                self._report(markets="disconnected_rest_fallback", trade_stream=False)
                if ws is not None:
                    try:
                        await asyncio.wait_for(ws.close(), timeout=5)
                    except Exception as exc:  # noqa: BLE001 — a failed close must not defeat cancellation.
                        log.warning("speeddesk_feed_close_failed error=%s", type(exc).__name__)
            await asyncio.sleep(2)

    async def _metadata(self) -> None:
        while True:
            await self.refresh_windows()
            await asyncio.sleep(15)

    async def _fallback(self) -> None:
        while True:
            await self.poll_book()
            await asyncio.sleep(0.25)

    async def run(self, stop: threading.Event) -> None:
        tasks = [asyncio.create_task(job()) for job in
                 (self._coinbase, self._markets, self._metadata, self._fallback)]
        try:
            while not stop.is_set():
                for task in tasks:
                    if task.done():
                        error = task.exception()
                        if error is not None:
                            raise error
                await asyncio.sleep(0.1)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self._client is not None:
                self._client.close()
