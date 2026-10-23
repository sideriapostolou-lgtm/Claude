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
import logging
import time
from typing import Any

import requests

API = "https://api.polymarket.us"
TIMEOUT_S = 15.0
log = logging.getLogger("nightcrawler.polymarket_us")


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
            # the signature covers the path without its query string (the venue rejects it otherwise)
            r = self._transport(method.upper(), f"{self.base_url}{path}", headers=self.headers(method, path.split("?", 1)[0]),
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
        """The venue's positions, one row per market: ``{"slug", "qty", "avg_price", "cost", "value", "realized",
        "expired", "title", "outcome", "event_slug", "updated"}``. The venue keys them by market slug (a dict);
        a list is accepted too."""
        doc = self._call("GET", "/v1/portfolio/positions")
        raw = doc.get("positions") if isinstance(doc, dict) else doc
        items: list[tuple[str, dict[str, Any]]] = []
        if isinstance(raw, dict):
            items = [(str(k), v) for k, v in raw.items() if isinstance(v, dict)]
        elif isinstance(raw, list):
            items = [("", v) for v in raw if isinstance(v, dict)]
        out: list[dict[str, Any]] = []
        for key, row in items:
            md: dict[str, Any] = row["marketMetadata"] if isinstance(row.get("marketMetadata"), dict) else {}
            slug = key or str(row.get("marketSlug") or md.get("slug") or row.get("slug") or "")
            qty = row.get("netPositionDecimal") if row.get("netPositionDecimal") is not None else row.get("netPosition")
            net = _f(qty)
            short = net < 0  # the SDK's netPositionDecimal: positive = long (YES), negative = short (NO)
            out.append({
                "slug": slug,
                "qty": abs(net),
                "side": "short" if short else "long",
                # a NO holding's average price and cost are not documented as NO prices: the desk prices it from
                # its own order instead (never from these)
                "avg_price": 0.0 if short else _f(row.get("avgPx")),
                "cost": 0.0 if short else _f(row.get("cost")),
                "value": _f(row.get("cashValue")),
                "realized": _f(row.get("realized")),
                "expired": bool(row.get("expired")),
                "title": str(md.get("title") or ""),
                "outcome": str(md.get("outcome") or ""),
                "event_slug": str(md.get("eventSlug") or ""),
                "updated": str(row.get("updateTime") or ""),
            })
        return out

    def activities(self, limit: int = 50) -> list[dict[str, Any]]:
        """READ ONLY: the account's newest activities (the SDK's ``GET /v1/portfolio/activities``, newest first),
        one flat row each: ``{"kind": "trade" | "resolution" | "deposit" | "withdrawal" | ..., "id", "slug", "time",
        "price", "qty", "realized", "cost_basis", "amount"}`` (missing figures are 0.0). A trade is a buy or a sale
        on the account, the desk's or the owner's own in the app (a cash-out shows here with its realized P&L)."""
        doc = self._call("GET", f"/v1/portfolio/activities?limit={max(1, min(int(limit), 100))}"
                                "&sortOrder=SORT_ORDER_DESCENDING")
        rows = doc.get("activities") if isinstance(doc, dict) else None
        out: list[dict[str, Any]] = []
        for a in rows if isinstance(rows, list) else []:
            if not isinstance(a, dict):
                continue
            kind = str(a.get("type") or "").removeprefix("ACTIVITY_TYPE_").lower()
            t, res, bal = (_dict(a.get(k)) for k in ("trade", "positionResolution", "accountBalanceChange"))
            txs = bal.get("transactions")
            tx = _dict(txs[0]) if isinstance(txs, list) and txs else {}
            after = _dict(res.get("afterPosition"))
            out.append({
                "kind": kind,
                "id": str(t.get("id") or res.get("tradeId") or tx.get("transactionId") or ""),
                "slug": str(t.get("marketSlug") or res.get("marketSlug") or ""),
                "time": str(t.get("updateTime") or t.get("createTime") or res.get("updateTime")
                            or tx.get("updateTime") or ""),
                "price": _f(t.get("price")),
                "qty": _f(t.get("qtyDecimal") if t.get("qtyDecimal") is not None else t.get("qty")),
                "realized": _f(t.get("realizedPnl")) if t else _f(after.get("realized")),
                "cost_basis": _f(t.get("costBasis")),
                "amount": _f(tx.get("amount")),
                "side": str(res.get("side") or ""),
            })
        return out

    def buy_long_ioc(self, market_slug: str, price: float, quantity: float, max_block_s: int = 5) -> dict[str, Any]:
        """A limit BUY of the YES side (``ORDER_INTENT_BUY_LONG``), immediate-or-cancel, executed synchronously.
        Returns ``{"id", "filled", "avg_price", "cost"}`` from the executions (filled 0 when nothing matched)."""
        return self._ioc(market_slug, "ORDER_INTENT_BUY_LONG", price, quantity, max_block_s)

    def buy_short_ioc(self, market_slug: str, no_price: float, quantity: float, max_block_s: int = 5) -> dict[str, Any]:
        """A limit BUY of the NO side (``ORDER_INTENT_BUY_SHORT``) at a NO price of at most ``no_price``,
        immediate-or-cancel. The venue reads every order's price as the YES (long) side's price ("to trade the NO
        side at any price X, set price.value = 1.00 - X", orders overview), so the order carries 1 - ``no_price``.
        ``avg_price`` and ``cost`` are returned as NO prices."""
        yes_limit = min(0.99, max(0.01, 1.0 - no_price))
        fill = self._ioc(market_slug, "ORDER_INTENT_BUY_SHORT", yes_limit, quantity, max_block_s)
        if fill["filled"] > 0 and fill["avg_price"] is not None:
            p = float(fill["avg_price"])
            # the execution price is the long side's (the docs' convention); a reply quoting the NO price itself is
            # recognised by fitting the order's NO limit while 1 - p does not
            no = p if (p <= no_price + 0.005 and 1.0 - p > no_price + 0.005) else 1.0 - p
            fill = {**fill, "avg_price": no, "cost": no * fill["filled"]}
        return fill

    def _ioc(self, market_slug: str, intent: str, price: float, quantity: float, max_block_s: int) -> dict[str, Any]:
        body = {
            "marketSlug": market_slug,
            "intent": intent,
            "type": "ORDER_TYPE_LIMIT",
            # four decimals: the venue quotes quarter-cents (0.5225), and a limit rounded to three could land on
            # the wrong side of the book and never fill
            "price": {"value": f"{price:.4f}", "currency": "USD"},
            "quantity": quantity,
            "tif": "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
            "synchronousExecution": True,
            "maxBlockTime": str(max_block_s),
            "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC",
        }
        doc = self._call("POST", "/v1/orders", body)
        top: dict[str, Any] = doc if isinstance(doc, dict) else {}
        order: dict[str, Any] = top["order"] if isinstance(top.get("order"), dict) else top
        execs = top.get("executions") if isinstance(top.get("executions"), list) else order.get("executions")
        filled = 0.0
        cost = 0.0
        for e in execs if isinstance(execs, list) else []:
            if not isinstance(e, dict):
                continue
            kind = str(e.get("type") or "").upper()
            if "CANCEL" in kind or "REJECT" in kind or "EXPIRE" in kind:
                continue  # a cancel, rejection or expiry report, not a fill
            # lastShares / lastPx are the documented execution fields; the older names are kept as fallbacks
            q = _f(e.get("lastShares") or e.get("quantity") or e.get("lastQuantity") or e.get("cumQuantity"))
            p = _f(e.get("lastPx") or e.get("price") or e.get("lastPrice"))
            if q > 0 and p > 0:
                filled += q
                cost += q * p
        if filled <= 0:  # some replies carry the fill on the order itself rather than as executions
            q = _f(order.get("filledQuantity") or order.get("cumQuantity") or order.get("executedQuantity"))
            p = _f(order.get("avgPrice") or order.get("averagePrice") or order.get("avgPx"))
            if q > 0 and p > 0:
                filled, cost = q, q * p
        # the reply's shape, so a fill the desk only finds later in the venue's book can be traced (no secrets here)
        log.info("polymarket_us_order_reply keys=%s status=%s executions=%d filled=%g",
                 ",".join(sorted(top.keys())), order.get("status"), len(execs) if isinstance(execs, list) else -1, filled)
        oid = order.get("id") if order.get("id") is not None else top.get("id")
        return {"id": str(oid) if oid is not None else None, "filled": filled,
                "avg_price": (cost / filled) if filled > 0 else None, "cost": cost,
                "raw_executions": len(execs) if isinstance(execs, list) else 0}


def _dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _f(v: Any) -> float:
    if isinstance(v, dict):
        v = v.get("value")
    try:
        return float(v) if v is not None and v != "" else 0.0
    except (TypeError, ValueError):
        return 0.0
