"""Execution transport tests use generated keys and fake HTTP only."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)

from nightcrawler.clock import FakeClock
from nightcrawler.config import Secret
from nightcrawler.speeddesk_kalshi_client import (
    API_PATH,
    TIMEOUT,
    KalshiClient,
    KalshiClientError,
)

TICKER = "KXBTC15M-26OCT121200-00"
CLIENT_ID = "speeddesk-owned-1"


class Response:
    def __init__(self, data: Any = None, status: int = 200) -> None:
        self.data, self.status_code = data, status

    def json(self) -> Any:
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


class Transport:
    def __init__(self, *results: Any) -> None:
        self.results = list(results)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, method: str, url: str, **kwargs: Any) -> Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        if not self.results:
            raise AssertionError("Unexpected HTTP attempt")
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        assert isinstance(result, Response)
        return result


@pytest.fixture
def signing_key() -> ed25519.Ed25519PrivateKey:
    return ed25519.Ed25519PrivateKey.generate()


def pem(key: Any) -> str:
    return key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()


def client(key: Any, transport: Transport, **kwargs: Any) -> KalshiClient:
    return KalshiClient(Secret("throwaway-test-id"), Secret(pem(key)), transport=transport,
                        clock=kwargs.pop("clock", FakeClock(1000)), **kwargs)


def ack(**changes: Any) -> Response:
    return Response({"order_id": "exchange-order-1", "client_order_id": CLIENT_ID,
                     "fill_count": "0.00", "remaining_count": "2.00", "ts_ms": 1000000, **changes})


def create(c: KalshiClient, **changes: Any) -> dict[str, Any]:
    args: dict[str, Any] = {"ticker": TICKER, "side": "up", "price": 0.41, "size": 2,
                            "kind": "take", "client_order_id": CLIENT_ID}
    args.update(changes)
    return c.create_order(**args)


def test_ed25519_exact_signing_message_excludes_query_and_uses_wrapped_secrets(signing_key: Any) -> None:
    c = client(signing_key, Transport(), clock=FakeClock(1234.567))
    headers = c.headers("get", API_PATH + "/portfolio/orders?cursor=not-signed")
    assert headers["KALSHI-ACCESS-KEY"] == "throwaway-test-id"
    assert headers["KALSHI-ACCESS-TIMESTAMP"] == "1234567"
    signing_key.public_key().verify(base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"]),
                                    b"1234567GET/trade-api/v2/portfolio/orders")
    with pytest.raises(KalshiClientError, match="invalid signing path"):
        c.headers("GET", "/portfolio/orders")


def test_reject_non_ed25519_pkcs8_and_malformed_keys_without_key_text() -> None:
    # RSA also uses the PRIVATE KEY header: inspecting that header is insufficient.
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for invalid in (pem(rsa_key), "sensitive-invalid-test-material"):
        with pytest.raises(KalshiClientError) as error:
            KalshiClient("test-id", invalid, transport=Transport())
        assert str(error.value) == "Kalshi authentication: invalid Ed25519 signing key"
        assert invalid not in str(error.value)
    with pytest.raises(KalshiClientError):
        KalshiClient("test\nInjected: value", "bad", transport=Transport())


@pytest.mark.parametrize("side,kind,expected_side,expected_price", [
    ("up", "take", "bid", "0.4100"), ("down", "take", "ask", "0.5900"),
    ("up", "rest", "bid", "0.4100"), ("down", "rest", "ask", "0.5900"),
])
def test_v2_orders_exact_fields_and_direction(signing_key: Any, side: str, kind: str,
                                              expected_side: str, expected_price: str) -> None:
    transport = Transport(ack())
    create(client(signing_key, transport), side=side, kind=kind,
           expiration_ts=1100 if kind == "rest" else None)
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert urlsplit(call["url"]).path == API_PATH + "/portfolio/events/orders"
    assert call["allow_redirects"] is False
    assert call["timeout"] == TIMEOUT
    expected = {"ticker": TICKER, "client_order_id": CLIENT_ID, "side": expected_side,
                "count": "2.00", "price": expected_price,
                "time_in_force": "immediate_or_cancel" if kind == "take" else "good_till_canceled",
                "post_only": kind == "rest", "self_trade_prevention_type": "taker_at_cross",
                "cancel_order_on_pause": True, "subaccount": 0, "exchange_index": -1}
    if kind == "rest":
        expected["expiration_time"] = 1100
    assert call["json"] == expected


@pytest.mark.parametrize("changes", [
    {"size": 0}, {"size": 0.5}, {"size": True}, {"size": float("inf")},
    {"price": float("nan")}, {"price": 1}, {"price": 0}, {"price": 0.12345},
    {"side": "sell"}, {"kind": "market"}, {"ticker": "OTHER-MARKET"},
    {"client_order_id": "../unowned"}, {"kind": "rest"},
    {"kind": "rest", "expiration_ts": 1000}, {"kind": "rest", "expiration_ts": 1901},
    {"kind": "rest", "expiration_ts": True}, {"expiration_ts": 1100},
])
def test_invalid_or_unbounded_order_is_rejected_before_http(signing_key: Any,
                                                           changes: dict[str, Any]) -> None:
    transport = Transport()
    with pytest.raises(KalshiClientError) as error:
        create(client(signing_key, transport), **changes)
    assert not error.value.uncertain
    assert transport.calls == []


def test_whole_submitted_order_can_receive_fractional_actual_fill_ack(signing_key: Any) -> None:
    transport = Transport(ack(fill_count="0.17", remaining_count="1.83"))
    result = create(client(signing_key, transport))
    assert result["fill_count"] == "0.17"


def test_binary_price_noise_is_normalized_without_accepting_materially_finer_price(signing_key: Any) -> None:
    transport = Transport(ack())
    create(client(signing_key, transport), price=0.41000000000000003)
    assert transport.calls[0]["json"]["price"] == "0.4100"


@pytest.mark.parametrize("result", [
    requests.Timeout("sensitive transport data"), Response({}, 500), Response({}, 503),
    Response({}, 408), Response({}, 409), Response({}, 302),
    Response(ValueError("sensitive response text")), Response([]),
    ack(order_id=""), ack(client_order_id="other-order"), ack(fill_count="3.00"),
    ack(fill_count="1.00", remaining_count="2.00"), ack(remaining_count="NaN"),
    ack(ts_ms=None), ack(ts_ms=True), ack(ts_ms=-1),
])
def test_create_unknown_result_is_never_retried_and_is_explicitly_uncertain(signing_key: Any,
                                                                           result: Any) -> None:
    transport = Transport(result)
    with pytest.raises(KalshiClientError) as error:
        create(client(signing_key, transport))
    assert error.value.uncertain
    assert "sensitive" not in str(error.value)
    assert len(transport.calls) == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 429])
def test_explicit_create_rejection_is_safe_and_not_retried(signing_key: Any, status: int) -> None:
    transport = Transport(Response({"message": "sensitive-venue-response"}, status))
    with pytest.raises(KalshiClientError) as error:
        create(client(signing_key, transport))
    assert error.value.status == status
    assert error.value.auth is (status in (401, 403))
    assert not error.value.uncertain
    assert "sensitive" not in str(error.value)
    assert len(transport.calls) == 1


@pytest.mark.parametrize("method,key,endpoint", [
    ("list_orders", "orders", "orders"), ("fills", "fills", "fills"),
    ("positions", "market_positions", "positions"), ("settlements", "settlements", "settlements"),
])
def test_all_account_pages_are_read_across_shards(signing_key: Any, method: str,
                                                key: str, endpoint: str) -> None:
    transport = Transport(Response({key: [{"id": 1}], "cursor": "page-2"}),
                          Response({key: [], "cursor": "page-3"}),
                          Response({key: [{"id": 2}], "cursor": ""}))
    c = client(signing_key, transport)
    assert getattr(c, method)(ticker=TICKER) == [{"id": 1}, {"id": 2}]
    for index, call in enumerate(transport.calls):
        assert call["method"] == "GET"
        url = urlsplit(call["url"])
        assert url.path == API_PATH + "/portfolio/" + endpoint
        query = parse_qs(url.query)
        assert query["ticker"] == [TICKER]
        assert query["subaccount"] == ["0"] and query["limit"] == ["1000"]
        assert "exchange_index" not in query
        if index:
            assert query["cursor"] == [f"page-{index + 1}"]
        if method == "positions":
            assert query["settlement_status"] == ["unsettled"]


@pytest.mark.parametrize("method,key", [("list_orders", "orders"), ("fills", "fills")])
@pytest.mark.parametrize("cursor_fields", [{}, {"cursor": None}, {"cursor": 0}])
def test_required_cursor_cannot_be_missing_null_or_nonstring(signing_key: Any, method: str,
                                                            key: str, cursor_fields: Any) -> None:
    c = client(signing_key, Transport(Response({key: [], **cursor_fields})))
    with pytest.raises(KalshiClientError, match="invalid pagination cursor"):
        getattr(c, method)()


@pytest.mark.parametrize("method,key", [("positions", "market_positions"), ("settlements", "settlements")])
def test_optional_cursor_can_be_absent_on_terminal_page(signing_key: Any, method: str, key: str) -> None:
    c = client(signing_key, Transport(Response({key: []})))
    assert getattr(c, method)() == []


@pytest.mark.parametrize("responses", [
    [Response({"orders": [{"id": 1}], "cursor": "loop"}),
     Response({"orders": [{"id": 2}], "cursor": "loop"})],
    [Response({"orders": [{"id": 1}], "cursor": "next"}), Response({}, 500)],
    [Response({"orders": [None], "cursor": ""})],
    [Response({"cursor": ""})],
])
def test_partial_or_malformed_pagination_never_returns_partial_rows(signing_key: Any,
                                                                  responses: Any) -> None:
    c = client(signing_key, Transport(*responses))
    with pytest.raises(KalshiClientError):
        c.list_orders()


def test_pagination_limit_is_a_failure_not_truncation(signing_key: Any) -> None:
    c = client(signing_key, Transport(Response({"fills": [], "cursor": "next"})), max_pages=1)
    with pytest.raises(KalshiClientError, match="incomplete account pagination"):
        c.fills()


def test_order_get_has_no_undocumented_shard_filter_and_validates_identity(signing_key: Any) -> None:
    transport = Transport(Response({"order": {"order_id": "owned-1", "status": "resting"}}),
                          Response({"order": {"order_id": "other"}}))
    c = client(signing_key, transport)
    assert c.get_order("owned-1")["status"] == "resting"
    assert transport.calls[0]["url"].endswith("/portfolio/orders/owned-1")
    with pytest.raises(KalshiClientError, match="invalid order response"):
        c.get_order("owned-2")


def test_cancel_routes_one_specific_market_order_without_retry(signing_key: Any) -> None:
    transport = Transport(Response({"order_id": "owned-1", "reduced_by": "1.83", "ts_ms": 1000000}),
                          requests.Timeout("sensitive"))
    c = client(signing_key, transport)
    assert c.cancel("owned-1", ticker=TICKER)["reduced_by"] == "1.83"
    call = transport.calls[0]
    assert call["method"] == "DELETE"
    assert urlsplit(call["url"]).path.endswith("/portfolio/events/orders/owned-1")
    assert parse_qs(urlsplit(call["url"]).query) == {
        "market_ticker": [TICKER], "exchange_index": ["-1"], "subaccount": ["0"]}
    with pytest.raises(KalshiClientError) as error:
        c.cancel("owned-1", ticker=TICKER)
    assert error.value.uncertain and len(transport.calls) == 2


@pytest.mark.parametrize("reply", [{}, {"order_id": "other", "reduced_by": "1.00"},
                                  {"order_id": "owned-1", "reduced_by": "-0.01"}])
def test_malformed_cancel_ack_remains_uncertain(signing_key: Any, reply: Any) -> None:
    c = client(signing_key, Transport(Response(reply)))
    with pytest.raises(KalshiClientError) as error:
        c.cancel("owned-1", ticker=TICKER)
    assert error.value.uncertain


def test_available_balance_subaccounts_and_actual_fees_preserve_venue_units(signing_key: Any) -> None:
    balance = {"balance": 1439, "balance_dollars": "14.3900", "portfolio_value": 100, "updated_ts": 1000}
    sub = {"subaccount_number": 0, "exchange_index": 2, "balance": "14.3900", "updated_ts": 1000}
    fill = {"fill_id": "fill-1", "fee_cost": "0.002831", "count_fp": "0.17"}
    settlement = {"revenue": 100, "fee_cost": "0.002831"}
    transport = Transport(Response(balance), Response({"subaccount_balances": [sub]}),
                          Response({"fills": [fill], "cursor": ""}),
                          Response({"settlements": [settlement]}))
    c = client(signing_key, transport)
    assert c.balance() == balance
    assert parse_qs(urlsplit(transport.calls[0]["url"]).query) == {"subaccount": ["0"]}
    assert c.subaccount_balances() == [sub]
    assert transport.calls[1]["url"].endswith("/portfolio/subaccounts/balances")
    assert c.fills(order_id="owned-1", min_ts=1000) == [fill]
    assert c.settlements(min_ts=1000) == [settlement]


@pytest.mark.parametrize("body", [{}, {"subaccount_balances": None}, {"subaccount_balances": [None]}])
def test_invalid_direct_feature_response_fails_closed(signing_key: Any, body: Any) -> None:
    c = client(signing_key, Transport(Response(body)))
    with pytest.raises(KalshiClientError, match="invalid balance response"):
        c.subaccount_balances()


def test_global_spacing_and_rate_backoff_only_apply_to_future_explicit_calls(signing_key: Any) -> None:
    clock = FakeClock(1000)
    transport = Transport(Response({}), Response({}, 429), Response({}, 429), Response({}))
    c = client(signing_key, transport, clock=clock)
    c.balance()
    with pytest.raises(KalshiClientError) as first:
        c.balance()
    assert first.value.status == 429 and len(transport.calls) == 2
    assert clock.now() == pytest.approx(1000.2)
    with pytest.raises(KalshiClientError):
        c.balance()
    assert clock.now() == pytest.approx(1002.2) and len(transport.calls) == 3
    c.balance()
    assert clock.now() == pytest.approx(1006.2) and len(transport.calls) == 4


def test_send_guard_runs_after_rate_wait_immediately_before_transport(signing_key: Any) -> None:
    clock = FakeClock(1000)
    transport = Transport(Response({}))
    c = client(signing_key, transport, clock=clock)
    c.balance()
    observed: list[float] = []

    def stale_after_wait() -> bool:
        observed.append(clock.now())
        return clock.now() < 1000.1

    with pytest.raises(KalshiClientError) as error:
        create(c, before_send=stale_after_wait)
    assert observed == [1000.2]
    assert not error.value.uncertain
    assert error.value.reason == "send_guard_rejected"
    assert len(transport.calls) == 1  # Only the preceding balance read reached HTTP.


def test_send_guard_error_fails_closed_without_sensitive_details(signing_key: Any) -> None:
    transport = Transport()

    def broken_guard() -> bool:
        raise RuntimeError("sensitive-internal-state")

    with pytest.raises(KalshiClientError) as error:
        create(client(signing_key, transport), before_send=broken_guard)
    assert error.value.reason == "send_guard_rejected" and not error.value.uncertain
    assert "sensitive" not in str(error.value) and not transport.calls


def test_successful_send_guard_allows_exactly_one_attempt(signing_key: Any) -> None:
    transport = Transport(ack())
    create(client(signing_key, transport), before_send=lambda: True)
    assert len(transport.calls) == 1


@pytest.mark.parametrize("action", [
    lambda c: c.get_order("../other"), lambda c: c.cancel("owned-1", ticker="OTHER-MARKET"),
    lambda c: c.list_orders(status="all"), lambda c: c.fills(min_ts=True),
    lambda c: c.positions(ticker="OTHER-MARKET"),
])
def test_bad_read_or_cancel_filters_never_reach_transport(signing_key: Any, action: Any) -> None:
    transport = Transport()
    with pytest.raises(KalshiClientError):
        action(client(signing_key, transport))
    assert transport.calls == []


def test_default_transport_keeps_one_connection_alive(signing_key: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every call reuses one requests.Session (no new TLS handshake per order); close() releases it."""
    sessions: list[requests.Session] = []

    def fake_request(self: requests.Session, method: str, url: str, **kwargs: Any) -> Response:
        sessions.append(self)
        return Response({"balance": 2500})

    monkeypatch.setattr(requests.Session, "request", fake_request)
    live = KalshiClient(Secret("throwaway-test-id"), Secret(pem(signing_key)), clock=FakeClock(1000))
    live.balance()
    live.balance()
    assert len(sessions) == 2 and sessions[0] is sessions[1]
    live.close()
