"""The signed Polymarket US client: headers and signature (verifiable with the key's public half), balances
parsing, order body shape and execution parsing, and error mapping. No network."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from nacl.signing import SigningKey

from nightcrawler.polymarket_us import PolymarketUSClient, PolymarketUSError

SEED = bytes(range(32))
SECRET_64 = base64.b64encode(SEED + SigningKey(SEED).verify_key.encode()).decode()


class Resp:
    def __init__(self, status: int, body: Any) -> None:
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)

    def json(self) -> Any:
        return self._body


def test_headers_sign_timestamp_method_and_path() -> None:
    calls: list[dict[str, Any]] = []

    def transport(method: str, url: str, **kw: Any) -> Resp:
        calls.append({"method": method, "url": url, **kw})
        return Resp(200, {"balances": [{"currency": "USD", "currentBalance": 25.0, "buyingPower": 25.0}]})

    c = PolymarketUSClient("key-id", SECRET_64, transport=transport, clock=lambda: 1_791_560_000.123)
    b = c.balances()
    assert b == {"cash": 25.0, "buying_power": 25.0, "asset_notional": 0.0, "open_orders": 0.0, "currency": "USD"}
    h = calls[0]["headers"]
    assert h["X-PM-Access-Key"] == "key-id" and h["X-PM-Timestamp"] == "1791560000123"
    message = (h["X-PM-Timestamp"] + "GET" + "/v1/account/balances").encode()
    SigningKey(SEED).verify_key.verify(message, base64.b64decode(h["X-PM-Signature"]))  # raises if wrong
    assert calls[0]["url"] == "https://api.polymarket.us/v1/account/balances" and calls[0]["data"] is None
    with pytest.raises(ValueError):
        PolymarketUSClient("k", base64.b64encode(b"short").decode())


def test_buy_long_ioc_body_and_executions() -> None:
    sent: list[dict[str, Any]] = []

    def transport(method: str, url: str, **kw: Any) -> Resp:
        sent.append({"method": method, "url": url, "body": json.loads(kw["data"])})
        return Resp(200, {"id": "ord-1", "executions": [{"quantity": 1, "price": {"value": "0.970"}}]})

    c = PolymarketUSClient("key-id", SECRET_64, transport=transport)
    r = c.buy_long_ioc("some-market", 0.97, 1)
    assert r == {"id": "ord-1", "filled": 1.0, "avg_price": 0.97, "cost": 0.97, "raw_executions": 1}
    body = sent[0]["body"]
    assert body["marketSlug"] == "some-market" and body["intent"] == "ORDER_INTENT_BUY_LONG"
    assert body["type"] == "ORDER_TYPE_LIMIT" and body["price"] == {"value": "0.970", "currency": "USD"}
    assert body["quantity"] == 1 and body["tif"] == "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL" and body["synchronousExecution"]
    assert sent[0]["method"] == "POST" and sent[0]["url"].endswith("/v1/orders")
    # nothing matched
    c2 = PolymarketUSClient("key-id", SECRET_64, transport=lambda m, u, **kw: Resp(200, {"id": "ord-2", "executions": []}))
    assert c2.buy_long_ioc("m", 0.5, 1)["filled"] == 0.0


def test_errors_carry_the_status() -> None:
    c = PolymarketUSClient("key-id", SECRET_64, transport=lambda m, u, **kw: Resp(401, {"error": "nope"}))
    with pytest.raises(PolymarketUSError) as e:
        c.balances()
    assert e.value.status == 401 and "HTTP 401" in str(e.value)
    c3 = PolymarketUSClient("key-id", SECRET_64, transport=lambda m, u, **kw: Resp(200, {"positions": [{"marketSlug": "m"}]}))
    assert [r["slug"] for r in c3.positions()] == ["m"]


def test_positions_are_keyed_by_slug_and_the_signature_skips_the_query() -> None:
    """The venue answers ``{"positions": {slug: {...}}}`` (seen 2026-10-09) and signs paths without ``?query``."""
    calls: list[dict[str, Any]] = []
    venue = {"positions": {"aec-del-kec-sww-2026-10-09": {
        "netPosition": "1", "netPositionDecimal": "1.0000", "qtyBought": "1", "qtySold": "0", "expired": False,
        "cost": {"value": "0.9700", "currency": "USD"}, "avgPx": {"value": "0.9700", "currency": "USD"},
        "cashValue": {"value": "0.6800", "currency": "USD"}, "realized": {"value": "0.0000", "currency": "USD"},
        "updateTime": "2026-10-09T17:32:20Z",
        "marketMetadata": {"slug": "aec-del-kec-sww-2026-10-09", "title": "Koelner Haie vs. Schwenninger Wild Wings",
                           "outcome": "Koelner Haie", "eventSlug": "del-kec-sww-2026-10-09"}}},
        "nextCursor": "", "eof": True}

    def transport(method: str, url: str, **kw: Any) -> Resp:
        calls.append({"method": method, "url": url, **kw})
        return Resp(200, venue)

    c = PolymarketUSClient("key-id", SECRET_64, transport=transport, clock=lambda: 1_791_560_000.0)
    rows = c.positions()
    assert rows == [{"slug": "aec-del-kec-sww-2026-10-09", "qty": 1.0, "avg_price": 0.97, "cost": 0.97, "value": 0.68,
                     "realized": 0.0, "expired": False, "title": "Koelner Haie vs. Schwenninger Wild Wings",
                     "outcome": "Koelner Haie", "event_slug": "del-kec-sww-2026-10-09", "updated": "2026-10-09T17:32:20Z"}]
    c._call("GET", "/v1/portfolio/positions?includeClosed=true")
    h = calls[1]["headers"]
    message = (h["X-PM-Timestamp"] + "GET" + "/v1/portfolio/positions").encode()  # no query in the signed text
    SigningKey(SEED).verify_key.verify(message, base64.b64decode(h["X-PM-Signature"]))
    assert calls[1]["url"].endswith("/v1/portfolio/positions?includeClosed=true")


def test_order_reply_with_the_fill_on_the_order_object() -> None:
    reply = {"order": {"id": "o-9", "status": "ORDER_STATUS_FILLED", "filledQuantity": "1", "avgPrice": {"value": "0.980"}}}
    c = PolymarketUSClient("key-id", SECRET_64, transport=lambda m, u, **kw: Resp(200, reply))
    r = c.buy_long_ioc("m", 0.98, 1)
    assert r["id"] == "o-9" and r["filled"] == 1.0 and r["avg_price"] == pytest.approx(0.98) and r["cost"] == pytest.approx(0.98)
    # a reply that only says "accepted" reads as no fill here: the desk then asks the venue's book
    c2 = PolymarketUSClient("key-id", SECRET_64, transport=lambda m, u, **kw: Resp(200, {"id": "o-10", "status": "ORDER_STATUS_PENDING"}))
    assert c2.buy_long_ioc("m", 0.98, 1) == {"id": "o-10", "filled": 0.0, "avg_price": None, "cost": 0.0, "raw_executions": 0}
