"""Read-only funding checks for primary-subaccount orders on a market's exchange shard."""

from __future__ import annotations

import math
import re
from typing import Any

from .speeddesk_live_model import LiveRiskBook
from .speeddesk_model import Window


def shard_index(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def primary_balances(rows: Any) -> dict[int, float]:
    """Exact subaccount endpoint: balance is a USD string, unlike aggregate balance cents.

    https://docs.kalshi.com/api-reference/portfolio/get-all-subaccount-balances
    Missing shards are unknown; neither other subaccounts nor aggregate cash funds primary orders.
    """
    if not isinstance(rows, list):
        raise TypeError("Invalid shard balances")
    result: dict[int, float] = {}
    seen: set[tuple[int, int]] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("Invalid shard balance row")
        account, shard, value = row.get("subaccount_number"), shard_index(row.get("exchange_index")), row.get("balance")
        if (type(account) is not int or not 0 <= account <= 63 or shard is None
                or (account, shard) in seen or not isinstance(value, str)
                or re.fullmatch(r"[0-9]+(?:\.[0-9]{1,6})?", value) is None):
            raise ValueError("Invalid or duplicate shard balance")
        amount = float(value)
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("Invalid shard balance amount")
        seen.add((account, shard))
        if account == 0:
            result[shard] = amount
    return result


class ShardFunding:
    def __init__(self) -> None:
        self.balances: dict[int, float] = {}
        self.at: float | None = None
        self.error: str | None = "shard_cash_unknown"
        # Recent order scans cannot erase an older owner's resting commitment.
        self.foreign_resting: set[str] = set()
        self.unknown_resting = False
        self.refusal: dict[str, Any] | None = None

    def orders(self, rows: list[dict[str, Any]], book: LiveRiskBook, *, full: bool) -> None:
        if full:
            self.foreign_resting.clear()
            self.unknown_resting = False
        for row in rows:
            if (not isinstance(row, dict) or not isinstance(row.get("order_id"), str) or not row["order_id"]):
                self.unknown_resting = True
                continue
            if row.get("status") not in {"resting", "canceled", "executed"}:
                self.foreign_resting.add(row["order_id"])
                continue
            order_id = row.get("order_id")
            intent = book.intents.get(str(row.get("client_order_id", "")))
            owned = intent is not None and order_id is not None and order_id == intent.order_id
            if row.get("status") == "resting" and not owned:
                if not isinstance(order_id, str) or not order_id:
                    self.unknown_resting = True
                else:
                    self.foreign_resting.add(order_id)
            elif isinstance(order_id, str) and (owned or row.get("status") in {"canceled", "executed"}):
                self.foreign_resting.discard(order_id)

    def update(self, rows: Any, now: float) -> None:
        # Invalidate first: a failed read/parse cannot leave old cash authorized.
        self.balances, self.at, self.error = {}, None, "shard_cash_invalid"
        self.balances = primary_balances(rows)
        self.at, self.error, self.refusal = now, None, None

    def check(self, window: Window, book: LiveRiskBook, now: float, *, cost: float = 0.0) -> str:
        shard = shard_index(window.exchange_index)
        code = self.error or ""
        if not code and book.windows[window.slug].exchange_index != shard:
            code = "market_shard_changed"
        available: float | None = None
        if not code and (self.at is None or not 0 <= now - self.at <= book.limits_for(window.slug).cash_max_age_s):
            code = "shard_cash_stale"
        if not code and (shard is None or shard not in self.balances):
            code = "shard_cash_unknown"
        if not code and (self.foreign_resting or self.unknown_resting):
            code = "external_resting_funding_unknown"
        reserved = debits = 0.0
        if not code:
            for key in book.open_intent_ids():
                item = book.intents[key]
                if item.reserved <= 0:
                    continue
                source = shard_index(book.windows[item.window].exchange_index)
                if source is None:
                    code = "reservation_shard_unknown"
                    break
                if source == shard:
                    reserved += item.reserved
            for slug, amount in book.cash_debits_by_window.items():
                source = shard_index(book.windows[slug].exchange_index)
                if source is None:
                    code = "debit_shard_unknown"
                    break
                if source == shard:
                    debits += amount
            if not code:
                assert shard is not None
                available = self.balances[shard] - reserved - debits
                if not math.isfinite(cost) or cost < 0 or cost > available + 1e-8:
                    code = "shard_cash_budget"
        if code:
            self.refusal = {"code": code, "window": window.slug, "exchange_index": shard,
                            "subaccount_number": 0, "required_usd": cost, "available_usd": available}
        else:
            self.refusal = None
        return code

    def panel(self) -> dict[str, Any]:
        return {"source": "GET /portfolio/subaccounts/balances", "subaccount_number": 0,
                "at": self.at, "error": self.error,
                "balances": [{"exchange_index": shard, "balance_usd": value}
                             for shard, value in sorted(self.balances.items())],
                "external_resting_orders": len(self.foreign_resting),
                "external_resting_unknown": self.unknown_resting, "refusal": self.refusal}
