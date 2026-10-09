"""A minimal signed client for the Polymarket US trading API (api.polymarket.us): balances, positions and
limit orders. Used by the Polymarket desk ONLY in live mode; paper mode never imports a key.

Authentication (https://docs.polymarket.us/api-reference/authentication, read 2026-10-09): every request carries
``X-PM-Access-Key`` (the key id), ``X-PM-Timestamp`` (unix milliseconds, within 30 s of the server) and
``X-PM-Signature`` = base64(Ed25519 sign of ``f"{timestamp}{method}{path}"`` in UTF-8) where the secret is the
base64 of 64 bytes whose first 32 are the Ed25519 seed. The request body is not signed.

The client never logs or returns the secret; the key id is the only identifier that may appear in logs.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import requests

API = "https://api.polymarket.us"
TIMEOUT_S = 15.0


class PolymarketUSError(RuntimeError):
    """A failed call (HTTP status or transport), with the status when known."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _seed(secret_key: str) -> bytes:
    raw = base64.b64decode(secret_key.strip(), validate=True)
    if len(raw) not in (32, 64):
        raise ValueError("Polymarket US secret key must decode to 32 or 64 bytes")
    return raw[:32]


class PolymarketUSClient:
    """Signed REST calls. ``transport`` (tests) replaces ``requests.request``."""

    def __init__(self, key_id: str, secret_key: str, *, base_url: str = API, transport: Any = None,
                 clock: Any = None) -> None:
        from nacl.signing import SigningKey

        self.key_id = key_id.strip()
        self._signer = SigningKey(_seed(secret_key))
        self.base_url = base_url.rstrip("/")
        self._transport = transport or requests.request
        self._clock = clock or time.time

    # ------------------------------------------------------------------ signing
    def headers(self, method: str, path: str) -> dict[str, str]:
        ts = str(int(self._clock() * 1000))
        message = f"{ts}{method.upper()}{path}".encode()
        signature = base64.b64encode(self._signer.sign(message).signature).decode("ascii")
        return {"X-PM-Access-Key": self.key_id, "X-PM-Timestamp": ts, "X-PM-Signature": signature,
                "Content-Type": "application/json", "Accept": "application/json"}

    def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        try:
            r = self._transport(method.upper(), f"{self.base_url}{path}", headers=self.headers(method, path),
                                data=json.dumps(body) if body is not None else None, timeout=TIMEOUT_S)
        except requests.RequestException as e:
            raise PolymarketUSError(f"{method} {path}: {type(e).__name__}") from e
        status = getattr(r, "status_code", None)
        if status is None or status >= 400:
            text = ""
            try:
                text = str(getattr(r, "text", ""))[:200]
            except Exception:  # noqa: BLE001
                text = ""
            raise PolymarketUSError(f"{method} {path}: HTTP {status} {text}", status=status)
        try:
            return r.json()
        except ValueError as e:
            raise PolymarketUSError(f"{method} {path}: bad JSON") from e

    # ------------------------------------------------------------------ calls
    def balances(self) -> dict[str, Any]:
        """``{"cash": float, "buying_power": float, "asset_notional": float, "currency": str}`` for USD."""
        doc = self._call("GET", "/v1/account/balances")
        rows = doc.get("balances") if isinstance(doc, dict) else None
        usd = next((b for b in rows or [] if str(b.get("currency", "USD")).upper() == "USD"), (rows or [{}])[0] if rows else {})
        return {
            "cash": _f(usd.get("currentBalance")),
            "buying_power": _f(usd.get("buyingPower")),
            "asset_notional": _f(usd.get("assetNotional")),
            "open_orders": _f(usd.get("openOrders")),
            "currency": str(usd.get("currency") or "USD"),
        }

    def positions(self) -> list[dict[str, Any]]:
        doc = self._call("GET", "/v1/portfolio/positions")
        rows = doc.get("positions") if isinstance(doc, dict) else doc
        return rows if isinstance(rows, list) else []

    def buy_long_ioc(self, market_slug: str, price: float, quantity: float, max_block_s: int = 5) -> dict[str, Any]:
        """A limit BUY of the YES side (``ORDER_INTENT_BUY_LONG``), immediate-or-cancel, executed synchronously.
        Returns ``{"id", "filled", "avg_price", "cost"}`` from the executions (filled 0 when nothing matched)."""
        body = {
            "marketSlug": market_slug,
            "intent": "ORDER_INTENT_BUY_LONG",
            "type": "ORDER_TYPE_LIMIT",
            "price": {"value": f"{price:.3f}", "currency": "USD"},
            "quantity": quantity,
            "tif": "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
            "synchronousExecution": True,
            "maxBlockTime": str(max_block_s),
            "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC",
        }
        doc = self._call("POST", "/v1/orders", body)
        execs = doc.get("executions") if isinstance(doc, dict) else None
        filled = 0.0
        cost = 0.0
        for e in execs or []:
            q = _f(e.get("quantity") or e.get("lastQuantity") or e.get("cumQuantity"))
            p = _f(e.get("price") or e.get("lastPrice"))
            if q > 0 and p > 0:
                filled += q
                cost += q * p
        return {"id": str(doc.get("id")) if isinstance(doc, dict) else None, "filled": filled,
                "avg_price": (cost / filled) if filled > 0 else None, "cost": cost, "raw_executions": len(execs or [])}


def _f(v: Any) -> float:
    if isinstance(v, dict):
        v = v.get("value")
    try:
        return float(v) if v is not None and v != "" else 0.0
    except (TypeError, ValueError):
        return 0.0
