"""Public observation only: wallet rows, BTC five-minute books and Coinbase.

Verified 2026-10-12: docs.polymarket.com/migrate/data-api-v1-to-v2,
data-api.polymarket.com/v2/openapi.json, and the raw API tab of
docs.polymarket.com/market-data/realtime-data. No signing or trading client.
Public CLOB messages expose hashes/timestamps, not sequence numbers: silent
upstream loss cannot be disproved. Wallet timestamps are block-time seconds,
not order-decision timestamps; identical public rows have ambiguous identity.
Normalized deltas omit opaque book hashes (no documented verification chain)
and redundant BBO fields after checking them against the rebuilt book. Every
economic price/size/side/time change remains recorded; there is no sampling.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
import time
from collections import Counter
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode, urlsplit

import requests

from .speeddesk_feeds import COINBASE_WS, coinbase_ticks, number, timestamp

WALLET = "0xc53375ff94e96100f2b30a4b5775db35218d69a9"
DATA = "https://data-api.polymarket.com/v2/trades"
GAMMA = "https://gamma-api.polymarket.com/markets/slug/"
CLOB_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
MAX_LEVELS = 1000
MAX_PAGES = 20
LOOKBACK = 600


class PublicFeedError(ValueError):
    """A fixed, safe diagnostic code for a failed public-data invariant."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _string(value: Any, limit: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError("Invalid public identifier")
    return value


def _amount(value: Any, *, positive: bool = False) -> float:
    out = number(value)
    if out is None or out < 0 or (positive and out == 0):
        raise ValueError("Invalid public amount")
    return out


def _price(value: Any) -> float:
    out = _amount(value)
    if out > 1:
        raise ValueError("Invalid outcome price")
    return out


def _array(value: Any) -> list[Any]:
    value = json.loads(value) if isinstance(value, str) else value
    if not isinstance(value, list):
        raise TypeError("Expected public array")
    return value


def parse_market(raw: Any, slug: str) -> dict[str, Any]:
    """Gamma startDate is creation time; use eventStartTime and verify the slug."""
    if not isinstance(raw, dict) or raw.get("slug") != slug:
        raise ValueError("Unexpected Gamma market")
    if re.fullmatch(r"btc-updown-5m-[0-9]{10}", slug) is None:
        raise ValueError("Unexpected Bitcoin series")
    start, end = timestamp(raw.get("eventStartTime")), timestamp(raw.get("endDate"))
    if start != int(slug.rsplit("-", 1)[1]) or end is None or end - start != 300:
        raise ValueError("Unverified five-minute times")
    outcomes, tokens = _array(raw.get("outcomes")), _array(raw.get("clobTokenIds"))
    if len(outcomes) != 2 or len(tokens) != 2 or set(outcomes) != {"Up", "Down"}:
        raise ValueError("Unverified outcomes")
    mapping = dict(zip(outcomes, (_string(token) for token in tokens), strict=True))
    if mapping["Up"] == mapping["Down"]:
        raise ValueError("Duplicate outcome token")
    rules = _string(raw.get("description"), 16000)
    source = _string(raw.get("resolutionSource"), 2048)
    return {"source": "gamma", "market_id": _string(raw.get("conditionId")), "slug": slug,
            "start": start, "end": end, "up_token": mapping["Up"], "down_token": mapping["Down"],
            "rules": rules, "resolution_source": source, "coinbase_is_resolution_source": False,
            "tick_size": _amount(raw.get("orderPriceMinTickSize"), positive=True),
            "min_order_size": _amount(raw.get("orderMinSize"), positive=True),
            "active": raw.get("active") is True, "closed": raw.get("closed") is True,
            "accepting_orders": raw.get("acceptingOrders") is True,
            "fee_type": str(raw.get("feeType", ""))[:128],
            "fee_schedule": {key: value for key, value in (raw.get("feeSchedule") or {}).items()
                             if key in ("rate", "exponent", "takerOnly", "rebateRate")
                             and isinstance(value, (int, float, bool))}}


def parse_wallet_fill(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or str(raw.get("proxy_wallet", "")).lower() != WALLET:
        raise ValueError("Wallet row belongs to a different observer")
    action = str(raw.get("side", "")).lower()
    if action not in ("buy", "sell"):
        raise ValueError("Unknown wallet action")
    side = str(raw.get("outcome", "")).lower()
    slug = raw.get("slug", "")
    if not isinstance(slug, str) or len(slug) > 256:
        raise ValueError("Invalid public market label")
    at = _amount(raw.get("timestamp"), positive=True)
    if at != int(at):
        raise ValueError("Unexpected wallet timestamp precision")
    return {"source": "wallet", "wallet": WALLET, "market_id": _string(raw.get("condition_id")),
            "token_id": _string(raw.get("token_id")), "side": side if side in ("up", "down") else "unknown",
            "action": action, "price": _price(raw.get("price")), "size": _amount(raw.get("size"), positive=True),
            "exchange_at": at, "timestamp_precision_s": 1, "slug": slug,
            "transaction_hash": _string(raw.get("transaction_hash")), "maker_taker": "unknown",
            "identity_precision": "public_row_content_and_duplicate_ordinal"}


def _public_get(url: str) -> Any:
    # Fixed public hosts/paths only; never accept account credentials or redirects.
    response = requests.get(url, timeout=(3.05, 10), allow_redirects=False)
    response.raise_for_status()
    if not 200 <= response.status_code < 300:
        raise ValueError("Unexpected public redirect")
    return response.json()


class SkipwatchFeeds:
    """Bounded public readers. The consumer durably records callback envelopes.

    Pass the last complete wallet watermark on restart. The overlap includes
    late indexing for ten minutes; indexing later than that is not certified.
    A failed page never advances the watermark. Initial/backfilled observations
    retain their actual receipt time and must never become prospective evidence.
    """

    def __init__(self, settings: Any = None, *, on_event: Callable[[str, dict[str, Any], float], None],
                 clock: Callable[[], float] = time.time, rest_get: Callable[[str], Any] | None = None,
                 coinbase_connect: Any = None, clob_connect: Any = None,
                 wallet_since: float | None = None) -> None:
        self.on_event, self.clock = on_event, clock
        self.poll_s = float(getattr(settings, "skipwatch_poll_s", 2.5))
        if not 2 <= self.poll_s <= 3:
            raise ValueError("Wallet polling must stay between two and three seconds")
        self._get = rest_get or _public_get
        self._coinbase_connect, self._clob_connect = coinbase_connect, clob_connect
        self.wallet_watermark = wallet_since if wallet_since is not None else clock()
        self._wallet_seen: dict[str, float] = {}
        self.markets: dict[str, dict[str, Any]] = {}
        self.tokens: dict[str, tuple[str, str]] = {}
        self.books: dict[str, dict[str, Any]] = {}
        self._last_request: dict[str, float] = {}
        self._backoff_until: dict[str, float] = {}
        self._failures: dict[str, int] = {}
        self._request_locks: dict[str, asyncio.Lock] = {}
        self._health_status: dict[str, tuple[str, float]] = {}
        self._health_last: dict[str, tuple[str, float]] = {}
        self._generation = 0
        self._coinbase_sequence: int | None = None

    def _emit(self, kind: str, payload: dict[str, Any], received_at: float | None = None) -> None:
        self.on_event(kind, payload, self.clock() if received_at is None else received_at)

    def _health(self, source: str, status: str, **fields: Any) -> None:
        now = self.clock()
        previous, since = self._health_status.get(source, ("starting", now))
        if previous != status:
            fields["previous_status"] = previous
            if status == "connected":
                fields.update(gap_from=since, gap_to=now)
            self._health_status[source] = (status, now)
        signature = _digest({"status": status, **fields})
        last_signature, last_at = self._health_last.get(source, ("", 0))
        if signature == last_signature and now - last_at < 30:
            return
        self._health_last[source] = (signature, now)
        self._emit("health", {"source": source, "status": status, **fields}, now)

    async def _request(self, url: str) -> Any:
        host = urlsplit(url).hostname or ""
        if host not in ("gamma-api.polymarket.com", "data-api.polymarket.com"):
            raise ValueError("Only public discovery endpoints are allowed")
        async with self._request_locks.setdefault(host, asyncio.Lock()):
            wait = max(self._last_request.get(host, 0) + 0.25, self._backoff_until.get(host, 0)) - self.clock()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request[host] = self.clock()
            try:
                result = await asyncio.to_thread(self._get, url)
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status in (429, 503):
                    count = self._failures.get(host, 0) + 1
                    self._failures[host] = count
                    raw_retry = exc.response.headers.get("Retry-After") if exc.response is not None else None
                    retry = number(raw_retry)
                    if retry is None and isinstance(raw_retry, str):
                        try:
                            retry = max(0, parsedate_to_datetime(raw_retry).timestamp() - self.clock())
                        except (ValueError, TypeError, OverflowError):
                            retry = None
                    delay = max(2 ** min(count, 6), retry or 0)
                    self._backoff_until[host] = self.clock() + delay
                    self._health("wallet" if host.startswith("data") else "gamma", "rate_limited",
                                 status_code=status, retry_after_s=delay)
                raise
            self._failures[host] = 0
            return result

    async def poll_wallet(self) -> None:
        end = int(self.clock())
        start = max(1, int(self.wallet_watermark) - LOOKBACK)
        # The API treats omitted/zero filter_amount as 0.01 tokens. An explicit
        # tiny positive threshold includes sub-cent fractional fills too.
        params: dict[str, Any] = {"user": WALLET, "taker_only": "false", "limit": 500,
                                  "filter_type": "TOKENS", "filter_amount": 1e-9,
                                  "start": start, "end": end}
        rows: list[dict[str, Any]] = []
        cursors: set[str] = set()
        for _ in range(MAX_PAGES):
            reply = await self._request(DATA + "?" + urlencode(params))
            if not isinstance(reply, dict) or not isinstance(reply.get("data"), list):
                raise TypeError("Invalid wallet response")
            pagination = reply.get("pagination")
            if not isinstance(pagination, dict) or "next_cursor" not in pagination:
                raise ValueError("Missing wallet pagination")
            if (not isinstance(pagination.get("has_more"), bool)
                    or not isinstance(pagination.get("limit"), int) or isinstance(pagination["limit"], bool)
                    or not 0 <= pagination["limit"] <= 1000
                    or not isinstance(pagination.get("offset"), int) or isinstance(pagination["offset"], bool)
                    or pagination["offset"] < 0):
                raise ValueError("Invalid wallet pagination metadata")
            if len(reply["data"]) > 1000:
                raise ValueError("Wallet page exceeded documented maximum")
            for raw in reply["data"]:
                row = parse_wallet_fill(raw)
                if not start <= row["exchange_at"] <= end:
                    raise ValueError("Wallet row outside requested time bounds")
                rows.append(row)
            cursor = pagination["next_cursor"]
            if pagination["has_more"] != (cursor is not None):
                raise ValueError("Contradictory wallet pagination")
            if cursor is None:
                break
            if not isinstance(cursor, str) or not cursor or len(cursor) > 4096 or cursor in cursors:
                raise ValueError("Invalid wallet pagination cursor")
            cursors.add(cursor)
            params["cursor"] = cursor
        else:
            raise ValueError("Wallet pagination incomplete; watermark retained")
        received_at = self.clock()
        occurrences: Counter[str] = Counter()
        for row in sorted(rows, key=lambda item: item["exchange_at"]):
            # Enrichment labels can arrive later; they cannot create a new fill.
            digest = _digest({key: row[key] for key in ("wallet", "market_id", "token_id", "action",
                                                       "price", "size", "exchange_at", "transaction_hash")})
            occurrences[digest] += 1
            fill_id = f"{digest}:{occurrences[digest]}"
            if fill_id not in self._wallet_seen:
                self._emit("wallet_fill", {**row, "fill_id": fill_id}, received_at)
                self._wallet_seen[fill_id] = row["exchange_at"]
        self.wallet_watermark = float(end)
        self._wallet_seen = {key: at for key, at in self._wallet_seen.items() if at >= end - LOOKBACK - 60}
        self._health("wallet", "connected", wallet_watermark=end, lookback_s=LOOKBACK,
                     maker_rows_included=True, maker_taker_identifiable=False,
                     indexed_after_lookback_not_certified=True, minimum_public_size=1e-9, rows=len(rows))

    async def discover(self) -> None:
        current = int(self.clock() // 300) * 300
        markets: dict[str, dict[str, Any]] = {}
        for start in (current, current + 300):
            slug = f"btc-updown-5m-{start}"
            try:
                raw = await self._request(GAMMA + slug)
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 404:
                    self._health("gamma", "market_unlisted", slug=slug)
                    continue
                raise
            market = parse_market(raw, slug)
            markets[market["market_id"]] = market
            if self.markets.get(market["market_id"]) != market:
                self._emit("market", market)
        self.markets = markets
        self.tokens = {market[token_key]: (market_id, side) for market_id, market in markets.items()
                       for side, token_key in (("up", "up_token"), ("down", "down_token"))}
        self._health("gamma", "connected", markets=len(markets), expected_markets=2)

    def reset_books(self, reason: str) -> None:
        self.books.clear()
        self._generation += 1
        self._health("clob", "gap", reason=reason, generation=self._generation,
                     sequence_available=False, books_valid=False)

    def _identity(self, raw: dict[str, Any], token: str) -> dict[str, Any]:
        market, side = self.tokens[token]
        if raw.get("market") != market:
            raise ValueError("CLOB token and market disagree")
        at = _amount(raw.get("timestamp"), positive=True) / 1000
        if at > self.clock() + 5:
            raise ValueError("CLOB timestamp is in the future")
        return {"source": "clob", "market_id": market, "token_id": token, "side": side,
                "exchange_at": at, "generation": self._generation, "sequence_available": False}

    @staticmethod
    def _levels(raw: Any) -> dict[float, float]:
        rows = _array(raw)
        if len(rows) > MAX_LEVELS:
            raise ValueError("Public book too large to preserve completely")
        out: dict[float, float] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise TypeError("Invalid public book level")
            price, size = _price(row.get("price")), _amount(row.get("size"))
            if price in out:
                raise ValueError("Duplicate public book level")
            if size:
                out[price] = size
        return out

    @staticmethod
    def _view(book: dict[str, Any], limit: int = MAX_LEVELS) -> dict[str, Any]:
        return {"bids": [list(pair) for pair in sorted(book["bids"].items(), reverse=True)[:limit]],
                "asks": [list(pair) for pair in sorted(book["asks"].items())[:limit]]}

    def clob_message(self, reply: Any, received_at: float | None = None) -> None:
        received_at = self.clock() if received_at is None else received_at
        rows = reply if isinstance(reply, list) else [reply]
        if len(rows) > 1000:
            raise ValueError("Oversized CLOB batch")
        for raw in rows:
            if not isinstance(raw, dict):
                raise TypeError("Invalid CLOB event")
            kind = raw.get("event_type")
            if kind == "price_change":
                changes = raw.get("price_changes")
                if not isinstance(changes, list) or len(changes) > 2000:
                    raise ValueError("Invalid price changes")
                grouped: dict[str, list[dict[str, Any]]] = {}
                for change in changes:
                    if not isinstance(change, dict):
                        raise TypeError("Invalid price change")
                    token = change.get("asset_id")
                    if token not in self.tokens:
                        continue
                    side = {"BUY": "bids", "SELL": "asks"}.get(str(change.get("side")))
                    if side is None:
                        raise ValueError("Invalid changed book side")
                    grouped.setdefault(token, []).append({"book_side": side[:-1],
                        "price": _price(change.get("price")), "size": _amount(change.get("size")),
                        "best_bid": number(change.get("best_bid")), "best_ask": number(change.get("best_ask"))})
                frame_updates: list[dict[str, Any]] = []
                frame_identity: dict[str, Any] = {}
                for token, updates in grouped.items():
                    identity = self._identity(raw, token)
                    frame_identity = {key: value for key, value in identity.items() if key not in ("token_id", "side")}
                    previous = self.books.get(token)
                    if previous is None:
                        self._health("clob_book", "gap", reason="awaiting_snapshot", token_id=token)
                        frame_updates.append({"token_id": token, "side": identity["side"],
                                              "changes": updates, "valid": False})
                        continue
                    book = {**previous, "bids": dict(previous["bids"]), "asks": dict(previous["asks"])}
                    if identity["exchange_at"] < book["exchange_at"]:
                        raise PublicFeedError("out_of_order_delta", "Out-of-order CLOB delta")
                    for update in updates:
                        levels = book[update["book_side"] + "s"]
                        if update["size"]:
                            levels[update["price"]] = update["size"]
                        else:
                            levels.pop(update["price"], None)
                        if len(levels) > MAX_LEVELS:
                            raise PublicFeedError("book_level_limit", "Public book exceeds level bound")
                    book["exchange_at"] = identity["exchange_at"]
                    expected = updates[-1]
                    crossed = bool(book["bids"] and book["asks"] and max(book["bids"]) >= min(book["asks"]))
                    mismatch = crossed
                    for key, actual in (("best_bid", max(book["bids"], default=0)),
                                        ("best_ask", min(book["asks"], default=1))):
                        if expected[key] is not None and abs(expected[key] - actual) > 1e-8:
                            mismatch = True
                    # Public probing found quote changes can precede matching
                    # full snapshots (a consumed level temporarily remains).
                    # Preserve the observation, including reported BBO, but no
                    # depth inference may use it until a fresh full snapshot.
                    book["valid"] = previous.get("valid", True) and not mismatch
                    self.books[token] = book
                    if mismatch:
                        self._health("clob_book", "gap", reason="bbo_mismatch", token_id=token,
                                     reported_bid=expected["best_bid"], reported_ask=expected["best_ask"],
                                     rebuilt_bid=max(book["bids"], default=0),
                                     rebuilt_ask=min(book["asks"], default=1))
                    normalized = ([{key: update[key] for key in ("book_side", "price", "size")} for update in updates]
                                  if book["valid"] else updates)
                    frame_updates.append({"token_id": token, "side": identity["side"],
                                          "changes": normalized, "valid": book["valid"]})
                if frame_updates:
                    self._emit("book_deltas", {**frame_identity, "updates": frame_updates,
                               "book_view": "deltas", "book_depth_complete": False}, received_at)
                continue
            token = raw.get("asset_id")
            if token not in self.tokens:
                continue
            identity = self._identity(raw, token)
            if kind == "book":
                book = {"bids": self._levels(raw.get("bids")), "asks": self._levels(raw.get("asks")),
                        "exchange_at": identity["exchange_at"], "valid": True}
                old = self.books.get(token)
                if old is not None and identity["exchange_at"] < old["exchange_at"]:
                    raise PublicFeedError("out_of_order_snapshot", "Out-of-order CLOB snapshot")
                if book["bids"] and book["asks"] and max(book["bids"]) >= min(book["asks"]):
                    raise PublicFeedError("crossed_book", "Crossed public order book")
                self.books[token] = book
                self._emit("book_snapshot", {**identity, **self._view(book), "hash": str(raw.get("hash", ""))[:256],
                           "valid": True, "book_view": "full", "book_depth_complete": True}, received_at)
                if set(self.books) >= set(self.tokens):
                    all_valid = all(item.get("valid", False) for item in self.books.values())
                    self._health("clob", "connected", books_valid=all_valid, sequence_available=False,
                                 continuity="transport_and_timestamps_only", delta_hashes_omitted=True,
                                 delta_bbo="validated_then_omitted")
                    if all_valid and self._health_status.get("clob_book", ("", 0))[0] == "gap":
                        self._health("clob_book", "connected", books_valid=True, recovery="full_snapshots")
            elif kind == "last_trade_price":
                tx = raw.get("transaction_hash", raw.get("transactionHash"))
                trade = {**identity, "price": _price(raw.get("price")),
                         "size": _amount(raw.get("size"), positive=True),
                         "aggressor": {"BUY": "buy", "SELL": "sell"}.get(str(raw.get("side")), "unknown"),
                         "transaction_hash": str(tx)[:256] if tx else None,
                         "id_source": "content_hash", "identity_exact": False}
                identity_fields = {key: value for key, value in trade.items() if key != "generation"}
                self._emit("public_trade", {**trade, "trade_id": _digest(identity_fields)}, received_at)
            elif kind == "tick_size_change":
                self._emit("market_rule_change", {**identity, "old_tick_size": _price(raw.get("old_tick_size")),
                           "new_tick_size": _price(raw.get("new_tick_size"))}, received_at)

    def coinbase_message(self, reply: Any, received_at: float) -> None:
        # Coinbase documents one counter per connection, including subscription
        # acknowledgements and heartbeats; per-channel tracking creates false gaps.
        sequence = reply.get("sequence_num") if isinstance(reply, dict) else None
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise ValueError("Missing Coinbase sequence")
        expected = 0 if self._coinbase_sequence is None else self._coinbase_sequence + 1
        if sequence != expected:
            raise PublicFeedError("sequence_gap", "Coinbase sequence gap")
        self._coinbase_sequence = sequence
        for price, at in coinbase_ticks(reply):
            self._emit("bitcoin_tick", {"source": "coinbase", "price": price, "exchange_at": at,
                       "sequence": sequence, "sequence_scope": "connection"}, received_at)

    async def _wallet_loop(self) -> None:
        while True:
            try:
                await self.poll_wallet()
            except Exception as exc:  # noqa: BLE001 - public failures create explicit coverage gaps.
                self._health("wallet", "gap", error=type(exc).__name__, wallet_watermark=self.wallet_watermark)
            await asyncio.sleep(self.poll_s)

    async def _discovery_loop(self) -> None:
        while True:
            try:
                await self.discover()
            except Exception as exc:  # noqa: BLE001 - preserve last metadata but expose failed discovery.
                self._health("gamma", "gap", error=type(exc).__name__)
            await asyncio.sleep(20)

    async def _clob_loop(self) -> None:
        from websockets.asyncio.client import connect

        connector = self._clob_connect or connect
        while True:
            assets = tuple(sorted(self.tokens))
            if not assets:
                await asyncio.sleep(0.5)
                continue
            self.reset_books("connect_or_subscription_change")
            try:
                async with connector(CLOB_WS, open_timeout=10, ping_interval=None, max_size=2**20) as ws:
                    await ws.send(json.dumps({"assets_ids": assets, "type": "market"}))
                    last_ping = last_message = self.clock()
                    try:
                        while assets == tuple(sorted(self.tokens)):
                            now = self.clock()
                            if now - last_ping >= 10:
                                await ws.send("PING")
                                last_ping = now
                            if now - last_message > 30:
                                raise TimeoutError("Public market heartbeat stale")
                            try:
                                message = await asyncio.wait_for(ws.recv(), timeout=1)
                            except TimeoutError:
                                continue
                            last_message = self.clock()
                            if message == "PONG":
                                continue
                            self.clob_message(json.loads(message), last_message)
                    finally:
                        # Invalidate before socket close can await, also when
                        # discovery removed every token or shutdown cancels us.
                        self.reset_books("connection_closed")
            except Exception as exc:  # noqa: BLE001 - every reconnect requires new snapshots.
                self.reset_books(exc.reason if isinstance(exc, PublicFeedError) else type(exc).__name__)
                await asyncio.sleep(2)

    async def _coinbase_loop(self) -> None:
        from websockets.asyncio.client import connect

        connector = self._coinbase_connect or connect
        while True:
            try:
                async with connector(COINBASE_WS, open_timeout=10, ping_interval=20, ping_timeout=10) as ws:
                    self._coinbase_sequence = None
                    for channel in ("market_trades", "heartbeats"):
                        await ws.send(json.dumps({"type": "subscribe", "product_ids": ["BTC-USD"],
                                                  "channel": channel}))
                    self._health("coinbase", "connected", opening_source="Coinbase spot; not venue resolution")
                    while True:
                        reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                        received_at = self.clock()
                        self.coinbase_message(reply, received_at)
            except Exception as exc:  # noqa: BLE001 - timestamped observations resume only after reconnect.
                self._health("coinbase", "gap", error=type(exc).__name__,
                             reason=exc.reason if isinstance(exc, PublicFeedError) else "connection_failed")
                await asyncio.sleep(2)

    async def run(self, stop: threading.Event) -> None:
        self._health("wallet", "starting", wallet_watermark=self.wallet_watermark,
                     lookback_s=LOOKBACK, public_only=True)
        tasks = [asyncio.create_task(loop()) for loop in
                 (self._wallet_loop, self._discovery_loop, self._clob_loop, self._coinbase_loop)]
        try:
            while not stop.is_set():
                for task in tasks:
                    if task.done():
                        task.result()
                        raise RuntimeError("Public observer task exited")
                await asyncio.sleep(0.1)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.reset_books("shutdown")
            self._health("wallet", "stopped", wallet_watermark=self.wallet_watermark)
            self._health("coinbase", "stopped")
