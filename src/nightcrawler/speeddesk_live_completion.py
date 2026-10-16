"""Bounded quote calculations for real-inventory pair completion, with no I/O or reservation release."""

from __future__ import annotations

import math
from typing import Literal

from .speeddesk_live_model import LiveRejected, LiveRiskBook
from .speeddesk_model import Book, Side

EPS = 1e-8


def external_asks(risk: LiveRiskBook, window: str, side: Side, book: Book) -> list[tuple[float, float]]:
    """Remove our reflected binary bids before treating visible asks as executable liquidity."""
    own: dict[float, float] = {}
    for item in risk._window_intents(window):
        # A public snapshot can lag a cancel or fill. Remove the original quantity for this window,
        # including terminal orders, rather than count our stale reflected quote as outside liquidity.
        if item.kind == "rest" and item.side != side:
            price = round(1 - item.price, 8)
            own[price] = own.get(price, 0.0) + item.size
    levels: dict[float, float] = {}
    for level in book.asks:
        if (math.isfinite(level.price) and 0 < level.price < 1
                and math.isfinite(level.size) and level.size > EPS):
            price = round(level.price, 8)
            levels[price] = levels.get(price, 0.0) + level.size
    cents: dict[float, float] = {}
    for price, size in levels.items():
        outside = size - own.get(price, 0.0)
        if outside > EPS:
            limit = math.ceil(round(price * 100, 6)) / 100
            cents[limit] = cents.get(limit, 0.0) + outside
    return sorted(cents.items())  # At most 100 whole-cent buckets, independent of sub-cent book density.


def depth_limit(levels: list[tuple[float, float]], size: float, ceiling: float = .99) -> float | None:
    total = 0.0
    for price, available in levels:
        limit = math.ceil(round(price * 100, 6)) / 100
        if limit > ceiling + EPS:
            break
        total += available
        if total >= size - EPS:
            return limit
    return None


def starter_fit(risk: LiveRiskBook, window: str, side: Side, kind: Literal["take", "rest"],
                price: float, size: int, levels: list[tuple[float, float]]) -> tuple[float, int]:
    """Lower the starter's limit/quantity until the whole visible hedge fits the existing fee-inclusive cap."""
    if kind not in ("take", "rest"):
        return price, 0
    limits = risk.limits_for(window)
    # Precompute at most clip depth limits, rather than rescan the order book for every cent.
    hedge = {count: depth_limit(levels, count) for count in range(1, size + 1)}
    hedge_unit = {count: risk.unit_reserve(window, other, "take") if other is not None else math.inf
                  for count, other in hedge.items()}
    for cents in range(min(99, math.floor(price * 100 + EPS)), 0, -1):
        bid = cents / 100
        unit = risk.unit_reserve(window, bid, kind)
        for count in range(size, 0, -1):
            if unit + hedge_unit[count] <= limits.pair_cap + EPS:
                return bid, count
        if kind == "take":
            break  # An IOC cannot obtain the displayed first-side ask by lowering its price.
    return price, 0


def maker_price(risk: LiveRiskBook, window: str, side: Side, price: float, size: float, now: float,
                *, exclude: str | None = None) -> float:
    """Only a pair-cap refusal permits lowering a same-size balancing maker bid."""
    if risk.balancing_contracts(window, side, size, risk.unit_reserve(window, price, "rest")) < size - EPS:
        return price
    for cents in range(min(99, math.floor(price * 100 + EPS)), 0, -1):
        bid = cents / 100
        reason = (risk.replacement_verdict(exclude, bid, now) if exclude is not None
                  else risk._buy_verdict(window, side, "rest", bid, size, now))
        if not reason:
            return bid
        if reason != "pair_cap":
            break
    return price


def completion_guard(risk: LiveRiskBook, client_id: str, now: float) -> bool:
    """Revalidate an already-reserved early IOC without double counting its own liability."""
    item = risk.intents[client_id]
    if not item.completion or item.lock or item.kind != "take" or not risk.strictly_balancing_intent(client_id):
        return False
    limits = risk.limits_for(item.window)
    spec = risk.windows[item.window]
    if (not spec.start <= now < spec.end - limits.lock_s or risk.cash_usd is None or risk.cash_at is None
            or item.size > limits.clip + EPS or abs(item.remaining - item.size) > EPS
            or not 0 <= now - risk.cash_at <= limits.cash_max_age_s
            or risk.inventory[item.window].spent + sum(i.reserved for i in risk._window_intents(item.window))
            > limits.window_usd + EPS
            or risk.at_risk_usd + item.reserved > limits.open_usd + EPS
            or risk.reserved_usd + risk.cash_debits > risk.cash_usd + EPS):
        return False
    try:
        if risk.unit_reserve(item.window, item.price, item.kind) > item.unit_reserve + EPS:
            return False
        return not risk._inventory_guard(item.window, item.side, item.remaining, item.unit_reserve, limits,
                                         exclude=client_id)
    except LiveRejected:
        return False
