"""Speed plan step 8: Kalshi's dedicated Trade API host and kept-alive public poll connections."""

from __future__ import annotations

import base64
import threading
from typing import Any
from urllib.parse import urlsplit

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)

import nightcrawler.speeddesk_feeds as feeds
import nightcrawler.speeddesk_kalshi as kalshi
from nightcrawler.clock import FakeClock
from nightcrawler.config import Secret
from nightcrawler.speeddesk_kalshi_client import API_PATH, BASE_URL, KalshiClient


class Reply:
    def __init__(self, status: int = 200, body: Any = None) -> None:
        self.status_code, self.body = status, body if body is not None else {"ok": True}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")

    def json(self) -> Any:
        return self.body


def test_signed_orders_go_to_kalshis_dedicated_trade_api_host_with_unchanged_signatures() -> None:
    key = ed25519.Ed25519PrivateKey.generate()
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    calls: list[dict[str, Any]] = []

    def transport(method: str, url: str, **kwargs: Any) -> Any:
        calls.append({"method": method, "url": url, **kwargs})
        return type("Response", (), {"status_code": 200, "json": lambda self: {"balance_dollars": "1.0000"}})()

    client = KalshiClient(Secret("throwaway-id"), Secret(pem), transport=transport, clock=FakeClock(1000))
    client.balance()
    assert BASE_URL == "https://external-api.kalshi.com"
    url = urlsplit(calls[0]["url"])
    assert (url.scheme, url.netloc, url.path) == ("https", "external-api.kalshi.com", API_PATH + "/portfolio/balance")
    headers = calls[0]["headers"]
    message = (headers["KALSHI-ACCESS-TIMESTAMP"] + "GET" + API_PATH + "/portfolio/balance").encode()
    key.public_key().verify(base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"]), message)  # path only


def test_public_polls_keep_one_session_per_worker_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions: list[Any] = []
    urls: list[str] = []

    class Session:
        def __init__(self) -> None:
            sessions.append(self)

        def get(self, url: str, **_kwargs: Any) -> Reply:
            urls.append(url)
            return Reply(404) if url.endswith("/missing") else Reply()

    monkeypatch.setattr(feeds.requests, "Session", Session)
    monkeypatch.setattr(feeds, "_THREAD", threading.local())
    assert kalshi._public_get("/markets/KXBTC15M-X/orderbook") == {"ok": True}
    assert kalshi._public_get("/missing") is None
    assert feeds._public_get("/v1/markets/x/book") == {"ok": True}
    assert len(sessions) == 1  # one kept-alive session on this thread for every poller
    worker = threading.Thread(target=lambda: kalshi._public_get("/series/KXBTC15M"))
    worker.start()
    worker.join()
    assert len(sessions) == 2  # another thread never shares it
    assert urls[0] == kalshi.API + "/markets/KXBTC15M-X/orderbook" and urls[2] == feeds.GATEWAY + "/v1/markets/x/book"
    assert kalshi.API.startswith("https://api.elections.kalshi.com")  # the public poller keeps its host
