"""Explicit authenticated Kalshi operations for the separately gated live desk.

API/auth/units verified against https://docs.kalshi.com/openapi.yaml and
https://docs.kalshi.com/getting_started/api_keys on 2026-10-12. This module does
not decide whether trading is enabled. The controller must persist an owned
intent and its full reservation before calling ``create_order``.

All methods make at most one attempt per request. An ambiguous create MUST be
reconciled by its client_order_id; it must never be blindly submitted again.
Account rows retain the venue's decimal strings, including actual fill fees,
so the controller can reconcile exact quantities and ownership before booking.
"""

from __future__ import annotations

import base64
import re
import threading
from collections import deque
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from urllib.parse import urlencode

import requests
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from .clock import Clock, RealClock
from .config import Secret

BASE_URL = "https://api.elections.kalshi.com"
API_PATH = "/trade-api/v2"
TIMEOUT = (3.05, 10.0)
# Half of Kalshi's Basic-tier limits (20 reads and 10 writes per second, docs.kalshi.com rate limits),
# counted apart so an order never queues behind the account reads that came just before it.
READS_PER_S, WRITES_PER_S = 10, 5


_ERROR_CODE = re.compile(r"[a-z0-9_]{1,64}")


class KalshiClientError(RuntimeError):
    """Safe to log: never includes a key, signature, URL, request or response body.

    ``code`` is Kalshi's machine error code (e.g. ``post_only_cross``) and is kept only
    when it is a short lowercase identifier, never free text from the response.
    """

    def __init__(self, operation: str, reason: str, *, status: int | None = None,
                 uncertain: bool = False, timed_out: bool = False, code: str | None = None) -> None:
        self.operation, self.reason = operation, reason
        self.status, self.uncertain = status, uncertain
        self.timed_out = timed_out
        self.code = code if isinstance(code, str) and _ERROR_CODE.fullmatch(code) else None
        super().__init__(f"Kalshi {operation}: {reason}" + (f" (HTTP {status})" if status is not None else "")
                         + (f" [{self.code}]" if self.code else ""))

    @property
    def auth(self) -> bool:
        return self.status in (401, 403)


def _error_code(response: Any) -> str | None:
    """Kalshi's ``{"error": {"code": ...}}`` identifier; anything else is dropped."""
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - an unreadable error body only loses the code
        return None
    error = body.get("error") if isinstance(body, dict) else None
    code = error.get("code") if isinstance(error, dict) else body.get("code") if isinstance(body, dict) else None
    return code if isinstance(code, str) and _ERROR_CODE.fullmatch(code) else None


def _plain(value: str | Secret) -> str:
    return value.reveal() if isinstance(value, Secret) else value


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise TypeError("Invalid number")
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Invalid number") from exc
    if not out.is_finite():
        raise ValueError("Invalid number")
    return out


def _identifier(value: str, *, market: bool = False) -> str:
    pattern = r"KXBTC15M-[A-Z0-9]+-[0-9]{2}" if market else r"[A-Za-z0-9_-]{1,128}"
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise KalshiClientError("validation", "invalid market or identifier")
    return value


class KalshiClient:
    """Synchronous client; run from the async controller with ``to_thread``.

    Read filters deliberately OMIT exchange_index: the current API defines
    omission as all shards and rejects negative read filters. Writes use -1
    plus a market ticker, which is documented automatic shard routing.
    ``transport`` is a single-attempt requests-compatible callable for tests.
    """

    def __init__(self, key_id: str | Secret, private_key: str | Secret, *, transport: Any = None,
                 clock: Clock | None = None, reads_per_s: int = READS_PER_S, writes_per_s: int = WRITES_PER_S,
                 page_size: int = 1000, max_pages: int = 100) -> None:
        if (not 1 <= reads_per_s <= READS_PER_S or not 1 <= writes_per_s <= WRITES_PER_S
                or not 1 <= page_size <= 1000 or not 1 <= max_pages <= 1000):
            raise KalshiClientError("configuration", "invalid request limits")
        try:
            key_text, pem = _plain(key_id), _plain(private_key)
            if not isinstance(key_text, str) or not key_text.strip() or any(char in key_text for char in "\r\n"):
                raise ValueError("Invalid key id")
            signer = load_pem_private_key(pem.encode("utf-8"), password=None)
            if not isinstance(signer, Ed25519PrivateKey):
                raise TypeError("An Ed25519 key is required")
        except (ValueError, TypeError, AttributeError, UnsupportedAlgorithm):
            raise KalshiClientError("authentication", "invalid Ed25519 signing key") from None
        self._key_id = key_text.strip()
        self._signer = signer
        # One kept-alive connection: a fresh TCP + TLS handshake per call cost
        # several round trips to Kalshi (decision-to-acknowledgement was 641 ms
        # on the first live order, 2026-10-12). Calls are serialized by _lock.
        self._session: requests.Session | None = None if transport else requests.Session()
        self._transport = transport or self._session.request  # type: ignore[union-attr]
        self._clock = clock or RealClock()
        self._page_size, self._max_pages = page_size, max_pages
        self._limits = {False: reads_per_s, True: writes_per_s}
        self._recent: dict[bool, deque[float]] = {False: deque(), True: deque()}
        self._lock = threading.Lock()
        self._blocked_until = 0.0
        self._rate_failures = 0
        # Pages and response bytes of each operation's last complete paginated read, for the status line.
        self.read_stats: dict[str, dict[str, int | None]] = {}
        self._local = threading.local()  # the response size of this thread's last call

    def _wait_turn(self, mutates: bool) -> None:
        """Rolling one-second budgets, reads and writes apart; a 429 backoff holds every later call."""
        recent, limit = self._recent[mutates], self._limits[mutates]
        while True:
            now = self._clock.now()
            while recent and recent[0] <= now - 1.0:
                recent.popleft()
            wait = max(self._blocked_until - now, recent[0] + 1.0 - now if len(recent) >= limit else 0.0)
            if wait <= 0:
                recent.append(now)
                return
            self._clock.sleep(wait)

    def writes_last_second(self) -> int:
        """Order creates and cancels in the rolling second, as the write budget counts them. Read without the
        transport lock (a snapshot taken under the GIL), so the event loop never waits behind a request."""
        now = self._clock.now()
        return sum(1 for moment in tuple(self._recent[True]) if moment > now - 1.0)

    def close(self) -> None:
        """Close the kept-alive HTTP connection; no credential file is ever opened."""
        if self._session is not None:
            self._session.close()

    def headers(self, method: str, path: str) -> dict[str, str]:
        """Fresh Ed25519 signature; callers must never log the returned headers."""
        timestamp = str(int(self._clock.now() * 1000))
        clean_path = path.split("?", 1)[0]
        if not clean_path.startswith(API_PATH + "/") or not clean_path.isascii():
            raise KalshiClientError("authentication", "invalid signing path")
        message = (timestamp + method.upper() + clean_path).encode("ascii")
        signature = base64.b64encode(self._signer.sign(message)).decode("ascii")
        return {"KALSHI-ACCESS-KEY": self._key_id, "KALSHI-ACCESS-TIMESTAMP": timestamp,
                "KALSHI-ACCESS-SIGNATURE": signature, "Content-Type": "application/json",
                "Accept": "application/json"}

    def _call(self, operation: str, method: str, path: str, *, query: dict[str, Any] | None = None,
              body: dict[str, Any] | None = None,
              before_send: Callable[[], bool] | None = None) -> dict[str, Any]:
        full_path = API_PATH + path
        query_string = urlencode(query or {})
        url = BASE_URL + full_path + ("?" + query_string if query_string else "")
        mutates = method != "GET"
        with self._lock:
            self._wait_turn(mutates)
            headers = self.headers(method, full_path)
            if before_send is not None:
                try:
                    permitted = before_send() is True
                except Exception:  # noqa: BLE001 - any guard failure must prevent the real order
                    permitted = False
                if not permitted:
                    raise KalshiClientError(operation, "send_guard_rejected")
            try:
                response = self._transport(method, url, headers=headers, json=body,
                                           timeout=TIMEOUT, allow_redirects=False)
            except (requests.Timeout, TimeoutError):
                raise KalshiClientError(operation, "transport failure", uncertain=mutates, timed_out=True) from None
            except (requests.RequestException, OSError):
                raise KalshiClientError(operation, "transport failure", uncertain=mutates) from None
            status = getattr(response, "status_code", None)
            if not isinstance(status, int) or isinstance(status, bool):
                raise KalshiClientError(operation, "invalid response status", uncertain=mutates)
            if status == 429:
                self._rate_failures += 1
                self._blocked_until = self._clock.now() + min(30.0, 2.0 ** min(self._rate_failures, 5))
            else:
                self._rate_failures = 0
            if not 200 <= status < 300:
                uncertain = mutates and (status >= 500 or status in (408, 409) or 300 <= status < 400)
                raise KalshiClientError(operation, "request rejected" if not uncertain else "result unconfirmed",
                                        status=status, uncertain=uncertain, code=_error_code(response))
            content = getattr(response, "content", None)
            self._local.bytes = len(content) if isinstance(content, (bytes, bytearray)) else None
            try:
                result = response.json()
            except (ValueError, TypeError):
                raise KalshiClientError(operation, "invalid JSON response", status=status, uncertain=mutates) from None
            if not isinstance(result, dict):
                raise KalshiClientError(operation, "invalid response shape", status=status, uncertain=mutates)
            return result

    def _pages(self, operation: str, path: str, key: str, query: dict[str, Any]) -> list[dict[str, Any]]:
        """Complete result or an exception: never silently return a partial account."""
        params = {**query, "limit": self._page_size, "subaccount": 0}
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        size: int | None = 0
        for page in range(1, self._max_pages + 1):
            result = self._call(operation, "GET", path, query=params)
            last = getattr(self._local, "bytes", None)
            size = None if size is None or last is None else size + last
            rows = result.get(key)
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise KalshiClientError(operation, "invalid account page")
            out.extend(rows)
            cursor = result.get("cursor", "")
            if (operation in ("list_orders", "fills") and "cursor" not in result
                    or not isinstance(cursor, str) or cursor in seen):
                raise KalshiClientError(operation, "invalid pagination cursor")
            if cursor == "":
                self.read_stats[operation] = {"pages": page, "bytes": size}
                return out
            seen.add(cursor)
            params["cursor"] = cursor
        raise KalshiClientError(operation, "incomplete account pagination")

    @staticmethod
    def _filters(*, ticker: str | None = None, min_ts: int | None = None) -> dict[str, Any]:
        query: dict[str, Any] = {}
        if ticker is not None:
            query["ticker"] = _identifier(ticker, market=True)
        if min_ts is not None:
            if not isinstance(min_ts, int) or isinstance(min_ts, bool) or min_ts < 0:
                raise KalshiClientError("validation", "invalid time filter")
            query["min_ts"] = min_ts
        return query

    def balance(self) -> dict[str, Any]:
        """Available cash: balance_dollars USD; balance/portfolio_value CENTS; updated_ts seconds."""
        return self._call("balance", "GET", "/portfolio/balance", query={"subaccount": 0})

    def subaccount_balances(self) -> list[dict[str, Any]]:
        """Read exact per-shard balances; primary subaccount is number zero.

        This endpoint's ``balance`` is a USD decimal string (unlike the cents
        field on the aggregate balance endpoint). Every account has primary zero:
        success here does NOT prove Direct membership or a narrower fee quantum.
        """
        reply = self._call("subaccount_balances", "GET", "/portfolio/subaccounts/balances")
        rows = reply.get("subaccount_balances")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise KalshiClientError("subaccount_balances", "invalid balance response")
        return rows

    def create_order(self, *, ticker: str, side: Literal["up", "down"], price: float, size: float,
                     kind: Literal["take", "rest"], client_order_id: str,
                     expiration_ts: int | None = None,
                     before_send: Callable[[], bool] | None = None) -> dict[str, Any]:
        """Owned exposure only: V2 ask is YES-selling/NO-buying at complementary price.

        The controller must block markets with somebody else's exposure, because
        Kalshi nets opposing holdings. A response is an acknowledgement, not an
        actual fill receipt: reconcile the fills endpoint before booking inventory.
        """
        ticker = _identifier(ticker, market=True)
        client_order_id = _identifier(client_order_id)
        try:
            quantity, limit = _decimal(size), _decimal(price)
            wire_limit = limit.quantize(Decimal("0.0001"))
            # floor(fair/tick)*tick can introduce binary float noise. Accept
            # only that noise, never silently round a materially finer price.
            if (quantity <= 0 or quantity != quantity.to_integral_value() or quantity > 1_000_000
                    or not 0 < wire_limit < 1 or abs(limit - wire_limit) > Decimal("0.000000000001")
                    or side not in ("up", "down") or kind not in ("take", "rest")):
                raise ValueError("Invalid order")
            limit = wire_limit
            if kind == "rest":
                if (not isinstance(expiration_ts, int) or isinstance(expiration_ts, bool)
                        or not self._clock.now() < expiration_ts <= self._clock.now() + 900):
                    raise ValueError("Invalid resting expiration")
            elif expiration_ts is not None:
                raise ValueError("IOC cannot have an expiration")
        except (ValueError, TypeError, InvalidOperation):
            raise KalshiClientError("create_order", "invalid order parameters") from None
        body: dict[str, Any] = {
            "ticker": ticker, "client_order_id": client_order_id, "side": "bid" if side == "up" else "ask",
            "count": f"{quantity:.2f}", "price": f"{limit if side == 'up' else 1 - limit:.4f}",
            "time_in_force": "immediate_or_cancel" if kind == "take" else "good_till_canceled",
            "post_only": kind == "rest", "self_trade_prevention_type": "taker_at_cross",
            "cancel_order_on_pause": True, "subaccount": 0, "exchange_index": -1,
        }
        if kind == "rest":
            body["expiration_time"] = expiration_ts
        reply = self._call("create_order", "POST", "/portfolio/events/orders", body=body,
                           before_send=before_send)
        try:
            if (not isinstance(reply.get("order_id"), str) or not reply["order_id"]
                    or reply.get("client_order_id", client_order_id) != client_order_id
                    or not isinstance(reply.get("ts_ms"), int) or isinstance(reply["ts_ms"], bool)
                    or reply["ts_ms"] <= 0
                    or not 0 <= _decimal(reply.get("fill_count")) <= quantity
                    or not 0 <= _decimal(reply.get("remaining_count")) <= quantity
                    or _decimal(reply.get("fill_count")) + _decimal(reply.get("remaining_count")) > quantity):
                raise ValueError("Invalid acknowledgement")
        except (ValueError, TypeError):
            raise KalshiClientError("create_order", "invalid order acknowledgement", uncertain=True) from None
        return reply

    def get_order(self, order_id: str) -> dict[str, Any]:
        result = self._call("get_order", "GET", "/portfolio/orders/" + _identifier(order_id))
        order = result.get("order")
        if not isinstance(order, dict) or order.get("order_id") != order_id:
            raise KalshiClientError("get_order", "invalid order response")
        return order

    def list_orders(self, *, ticker: str | None = None, status: str | None = None,
                    min_ts: int | None = None) -> list[dict[str, Any]]:
        query = self._filters(ticker=ticker, min_ts=min_ts)
        if status is not None:
            if status not in ("resting", "canceled", "executed"):
                raise KalshiClientError("list_orders", "invalid status filter")
            query["status"] = status
        return self._pages("list_orders", "/portfolio/orders", "orders", query)

    def fills(self, *, ticker: str | None = None, order_id: str | None = None,
              min_ts: int | None = None) -> list[dict[str, Any]]:
        """Actual fee_cost is a USD decimal string, possibly six decimals; do not recompute it."""
        query = self._filters(ticker=ticker, min_ts=min_ts)
        if order_id is not None:
            query["order_id"] = _identifier(order_id)
        return self._pages("fills", "/portfolio/fills", "fills", query)

    def positions(self, *, ticker: str | None = None) -> list[dict[str, Any]]:
        """Unsettled net holdings; position_fp >0 YES, <0 NO, all cost/P&L fields in dollars."""
        return self._pages("positions", "/portfolio/positions", "market_positions",
                           {**self._filters(ticker=ticker), "settlement_status": "unsettled"})

    def settlements(self, *, ticker: str | None = None, min_ts: int | None = None) -> list[dict[str, Any]]:
        """Venue settlements: revenue in CENTS, fee_cost and *_cost_dollars in dollars."""
        return self._pages("settlements", "/portfolio/settlements", "settlements",
                           self._filters(ticker=ticker, min_ts=min_ts))

    def cancel(self, order_id: str, *, ticker: str) -> dict[str, Any]:
        """One owned-ID cancellation attempt; cancellation never proves that no fill raced it."""
        reply = self._call("cancel", "DELETE", "/portfolio/events/orders/" + _identifier(order_id),
                           query={"market_ticker": _identifier(ticker, market=True), "exchange_index": -1,
                                  "subaccount": 0})
        try:
            if (reply.get("order_id") != order_id or _decimal(reply.get("reduced_by")) < 0
                    or not isinstance(reply.get("ts_ms"), int) or isinstance(reply["ts_ms"], bool)
                    or reply["ts_ms"] <= 0):
                raise ValueError("Invalid cancellation")
        except (ValueError, TypeError):
            raise KalshiClientError("cancel", "invalid cancellation acknowledgement", uncertain=True) from None
        return reply
