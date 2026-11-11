"""Session-only observations of selling depth after real Kalshi buy fills.

This module cannot send an order or change accounting. Horizons start when the
complete fills batch returns locally, not at an assumed exchange receipt time.
The first callback at each horizon is final, including a missing/invalid quote;
waiting for a later, better quote would overstate obtainable exits.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any

from .speeddesk_live_model import ActualFill
from .speeddesk_model import Book, Side, Window

HORIZONS = (1, 5, 30)
MAX_AGE_S = 0.5
MAX_LEVELS = 512
PROTOCOL_VERSION = 2
MAX_MEASUREMENTS_PER_BOOK = 8
QUANTITY_GRID = Decimal("0.01")
SAMPLING_METHOD = "first_post_horizon_websocket_update"
FEE_MODEL = "sell_formula_plus_per_0.01_contract_rounding_upper_bound"


def _finite(value: object) -> bool:
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def _number(value: float) -> float | None:
    return value if _finite(value) else None


def _price_key(value: float) -> float:
    # Treat floating point representations of the same quoted price as one level.
    return round(value, 12)


@dataclass
class _Pending:
    fill: ActualFill
    observed_at: float
    observed_mono: float
    window_end: float
    coefficient: float
    precision: float
    fee_verified: bool
    remaining: set[int] = field(default_factory=lambda: set(HORIZONS))


class FillMarkouts:
    """Bounded diagnostic state; every return value is a separate log record."""

    def __init__(self, started_at: float, started_mono: float, max_pending: int = 1024) -> None:
        if not (_finite(started_at) and _finite(started_mono)):
            raise ValueError("Markout start clocks must be finite")
        if not isinstance(max_pending, int) or isinstance(max_pending, bool) or not 1 <= max_pending <= 4096:
            raise ValueError("Markout pending bound must be between 1 and 4096")
        self.started_at, self.started_mono = started_at, started_mono
        self.max_pending = max_pending
        self.session_id = hashlib.sha256(f"{started_at!r}:{started_mono!r}".encode()).hexdigest()[:20]
        self._pending: dict[str, _Pending] = {}
        self._by_book: dict[tuple[str, str], set[str]] = {}
        self._next_due: dict[tuple[str, str], float] = {}
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._seen_limit = max(1024, max_pending * 8)
        self._seen_before = -math.inf
        self._counts: Counter[str] = Counter()
        self._gaps: Counter[str] = Counter()

    def _clock_reason(self, now: float, mono: float) -> str | None:
        if not (_finite(now) and _finite(mono)):
            return "clock_invalid"
        if mono < self.started_mono or abs((now - self.started_at) - (mono - self.started_mono)) > MAX_AGE_S:
            return "clock_change"
        return None

    def _base(self, pending: _Pending, at: float) -> dict[str, Any]:
        fill = pending.fill
        return {
            "at": _number(at), "event": "speeddesk_fill_observed",
            "protocol_version": PROTOCOL_VERSION, "max_levels_per_side": MAX_LEVELS,
            "mode": "diagnostic", "fill_source": "real", "session_id": self.session_id,
            "fill_id": fill.fill_id, "order_id": fill.order_id, "window": fill.window,
            "side": fill.side, "entry_price": _number(fill.price), "entry_size": _number(fill.size),
            "entry_fee_usd": _number(fill.fee_usd), "actual_fill_at": _number(fill.at),
            "fills_batch_returned_at": _number(pending.observed_at),
            "detection_delay_s": _number(pending.observed_at - fill.at),
            "detection_delay_kind": "venue_fill_to_complete_paginated_batch_return",
            "horizon_basis": "fills_batch_return",
            "window_end": _number(pending.window_end), "fee_coefficient": _number(pending.coefficient),
            "fee_precision": _number(pending.precision), "fee_verified": pending.fee_verified,
            "is_taker": fill.is_taker, "horizons_s": list(HORIZONS), "session_only": True,
        }

    def _horizon(self, pending: _Pending, horizon: int, now: float, mono: float) -> dict[str, Any]:
        return {
            **self._base(pending, now), "event": "speeddesk_fill_markout", "horizon_s": horizon,
            "target_at": _number(pending.observed_at + horizon),
            "elapsed_s": _number(mono - pending.observed_mono), "sampling_method": SAMPLING_METHOD,
            "fee_model": FEE_MODEL, "reason": None, "filled_size": None, "unfilled_size": None,
            "gross_proceeds_usd": None, "allocated_entry_fee_usd": None, "exit_fee_bound_usd": None,
            "partial_hypothetical_net_usd": None, "hypothetical_net_usd": None,
            "consumed_depth": [], "execution_assumption": "instantaneous_visible_bid_depth_no_order_sent",
            "own_depth_policy": "all_original_bot_order_sizes_in_window",
            "external_depth_is_conservative_lower_bound": True,
            "liquidity_scope": "isolated_fill_not_joint_inventory_liquidation",
        }

    def _gap(self, pending: _Pending, horizon: int, now: float, mono: float, reason: str) -> dict[str, Any]:
        row = self._horizon(pending, horizon, now, mono)
        row.update(event="speeddesk_fill_markout_gap", reason=reason)
        pending.remaining.discard(horizon)
        self._counts["gap_horizons"] += 1
        self._gaps[reason] += 1
        return row

    def _remove_if_done(self, pending: _Pending) -> None:
        if pending.remaining:
            return
        fill = pending.fill
        self._pending.pop(fill.fill_id, None)
        key = (fill.window, fill.side)
        indexed = self._by_book.get(key)
        if indexed is not None:
            indexed.discard(fill.fill_id)
            if not indexed:
                self._by_book.pop(key, None)
                self._next_due.pop(key, None)

    def _refresh_due(self, key: tuple[str, str]) -> None:
        indexed = self._by_book.get(key)
        if indexed:
            self._next_due[key] = min(self._pending[item].observed_mono + min(self._pending[item].remaining)
                                      for item in indexed)

    def needs_book(self, window: str, side: Side, mono: float) -> bool:
        """O(1) admission check before the caller constructs conservative own depth."""
        due = self._next_due.get((window, side))
        return due is not None and (not _finite(mono) or mono >= due or mono < self.started_mono)

    def observe_fill(self, fill: ActualFill, window: Window, *, observed_at: float, observed_mono: float,
                     fee_precision: float, fee_verified: bool) -> list[dict[str, Any]]:
        """Admit a newly reconciled owned fill, never reconstructed startup history."""
        if fill.fill_id in self._seen:
            self._counts["duplicate_fills"] += 1
            return []
        pending = _Pending(fill, observed_at, observed_mono, window.end, window.taker_coefficient,
                           fee_precision, fee_verified)
        reason = self._fill_reason(pending, window)
        if reason is None and fill.at <= self._seen_before:
            reason = "dedup_retention_boundary"
        # Invalid nonfinite timestamps must never poison the bounded dedup watermark.
        self._seen[fill.fill_id] = fill.at if _finite(fill.at) else -math.inf
        if len(self._seen) > self._seen_limit:
            _, retired_at = self._seen.popitem(last=False)
            self._seen_before = max(self._seen_before, retired_at)
            self._counts["dedup_evictions"] += 1
        if reason is not None:
            self._counts["rejected_fills"] += 1
            return [self._gap(pending, horizon, observed_at, observed_mono, reason) for horizon in HORIZONS]
        self._counts["observed_fills"] += 1
        rows = [self._base(pending, observed_at)]
        if len(self._pending) >= self.max_pending:
            self._counts["overflow_fills"] += 1
            rows.extend(self._gap(pending, horizon, observed_at, observed_mono, "pending_overflow")
                        for horizon in HORIZONS)
            return rows
        for horizon in HORIZONS:
            if observed_at + horizon >= window.end:
                rows.append(self._gap(pending, horizon, observed_at, observed_mono, "market_closed"))
        if pending.remaining:
            self._pending[fill.fill_id] = pending
            key = (fill.window, fill.side)
            self._by_book.setdefault(key, set()).add(fill.fill_id)
            self._next_due[key] = min(self._next_due.get(key, math.inf), observed_mono + min(pending.remaining))
        return rows

    def _fill_reason(self, pending: _Pending, window: Window) -> str | None:
        fill = pending.fill
        if window.venue != "kalshi" or not window.slug.startswith("KXBTC15M-") or fill.window != window.slug:
            return "unsupported_market"
        if fill.side not in ("up", "down"):
            return "invalid_side"
        if any(not isinstance(value, str) or not 0 < len(value) <= 256
               for value in (fill.fill_id, fill.order_id, fill.client_order_id, fill.window)):
            return "invalid_identifier"
        if not all(_finite(value) for value in (fill.at, fill.price, fill.size, fill.fee_usd,
                                                window.start, window.end, pending.observed_at,
                                                pending.observed_mono, pending.coefficient, pending.precision)):
            return "nonfinite_fill"
        if not 0 < fill.price < 1 or fill.size <= 0 or fill.fee_usd < 0 or window.end <= window.start:
            return "invalid_fill"
        if not math.isfinite(fill.size * 100):
            return "numeric_overflow"
        grid_size = Decimal(str(fill.size)) / QUANTITY_GRID
        if grid_size != grid_size.to_integral_value():
            return "quantity_off_grid"
        if fill.at < self.started_at:
            return "prior_session_fill"
        if fill.at > pending.observed_at:
            return "fill_timestamp_future"
        if not window.start <= fill.at < window.end:
            return "fill_outside_window"
        return self._clock_reason(pending.observed_at, pending.observed_mono)

    def _quote_reason(self, book: Book, own_bids: dict[float, float], ownership_unknown: bool,
                      now: float) -> str | None:
        if book.source != "websocket":
            return "not_websocket"
        if book.exchange_at is None:
            return "exchange_timestamp_missing"
        if not (_finite(book.at) and _finite(book.exchange_at)):
            return "book_timestamp_invalid"
        if book.at > now or book.exchange_at > now:
            return "book_timestamp_future"
        if now - book.at > MAX_AGE_S or now - book.exchange_at > MAX_AGE_S:
            return "book_stale"
        if ownership_unknown:
            return "ownership_unknown"
        if len(book.bids) > MAX_LEVELS or len(book.asks) > MAX_LEVELS or len(own_bids) > MAX_LEVELS:
            return "depth_work_bound"
        for levels in (book.bids, book.asks):
            seen: set[float] = set()
            for level in levels:
                if not (_finite(level.price) and _finite(level.size)) or not 0 < level.price < 1 or level.size < 0:
                    return "invalid_level"
                key = _price_key(level.price)
                if key in seen:
                    return "duplicate_level"
                seen.add(key)
        for price, size in own_bids.items():
            if not (_finite(price) and _finite(size)) or not 0 < price < 1 or size < 0:
                return "own_depth_unknown"
        bid = max((level.price for level in book.bids if level.size > 0), default=0.0)
        ask = min((level.price for level in book.asks if level.size > 0), default=1.0)
        return "crossed_book" if bid >= ask else None

    def on_book(self, book: Book, *, now: float, mono: float, own_bids: dict[float, float],
                ownership_unknown: bool = False) -> list[dict[str, Any]]:
        """Resolve only matching pending fills; ordinary book callbacks are O(1)."""
        keys = self._by_book.get((book.window, book.side))
        if not keys:
            return []
        rows: list[dict[str, Any]] = []
        clock_reason = self._clock_reason(now, mono)
        quote_reason: str | None = None
        quote_checked = False
        measured = 0
        for fill_id in sorted(keys, key=lambda item: (self._pending[item].observed_mono, item)):
            pending = self._pending[fill_id]
            for horizon in sorted(pending.remaining):
                elapsed = mono - pending.observed_mono
                if clock_reason is None and elapsed < horizon:
                    continue
                target = pending.observed_at + horizon
                reason = clock_reason
                if reason is None and (target >= pending.window_end or now >= pending.window_end):
                    reason = "market_closed"
                if reason is None and elapsed - horizon > MAX_AGE_S:
                    reason = "observation_late"
                if reason is None and not quote_checked:
                    quote_reason = self._quote_reason(book, own_bids, ownership_unknown, now)
                    quote_checked = True
                reason = reason or quote_reason
                if reason is None and book.at < target:
                    reason = "book_before_horizon"
                if reason is None and (not pending.fee_verified or pending.precision not in (0.0001, 0.01)
                                       or not 0 <= pending.coefficient <= 1):
                    reason = "fee_unverified"
                if reason is None and measured >= MAX_MEASUREMENTS_PER_BOOK:
                    reason = "callback_work_bound"
                if reason is not None:
                    row = self._gap(pending, horizon, now, mono, reason)
                else:
                    row = self._measure(pending, horizon, book, own_bids, now, mono)
                    measured += 1
                row.update(book_received_at=_number(book.at),
                           book_bid_levels=len(book.bids), book_ask_levels=len(book.asks),
                           own_bid_levels=len(own_bids),
                           book_exchange_at=_number(book.exchange_at) if book.exchange_at is not None else None,
                           book_source=book.source, book_receive_age_s=_number(now - book.at),
                           book_source_age_s=_number(now - book.exchange_at) if book.exchange_at is not None else None)
                rows.append(row)
            self._remove_if_done(pending)
        self._refresh_due((book.window, book.side))
        return rows

    def _measure(self, pending: _Pending, horizon: int, book: Book, own_bids: dict[float, float],
                 now: float, mono: float) -> dict[str, Any]:
        row = self._horizon(pending, horizon, now, mono)
        remaining = Decimal(str(pending.fill.size))
        entry_size = remaining
        proceeds, exit_fee = Decimal(0), Decimal(0)
        coefficient, precision = Decimal(str(pending.coefficient)), Decimal(str(pending.precision))
        owned: dict[float, Decimal] = {}
        for price, size in own_bids.items():
            key = _price_key(price)
            owned[key] = owned.get(key, Decimal(0)) + Decimal(str(size))
        depth: list[dict[str, float]] = []
        for level in sorted(book.bids, key=lambda item: item.price, reverse=True):
            available = max(Decimal(0), Decimal(str(level.size)) - owned.get(_price_key(level.price), Decimal(0)))
            available = (available / QUANTITY_GRID).to_integral_value(rounding=ROUND_FLOOR) * QUANTITY_GRID
            quantity = min(remaining, available)
            if quantity <= 0:
                continue
            sale_price = Decimal(str(level.price))
            proceeds += sale_price * quantity
            # The actual sell fee can depend on fill partitions. No future rebate
            # or buy-side price-plus-fee helper is treated as an exact sell fee.
            partitions = (quantity / QUANTITY_GRID).to_integral_value(rounding=ROUND_CEILING)
            exit_fee += coefficient * quantity * sale_price * (1 - sale_price) + precision * partitions
            depth.append({"price": level.price, "size": float(quantity)})
            remaining -= quantity
            if remaining == 0:
                break
        taken = entry_size - remaining
        allocated_fee = Decimal(str(pending.fill.fee_usd)) * taken / entry_size
        partial_net = proceeds - taken * Decimal(str(pending.fill.price)) - allocated_fee - exit_fee
        values = (taken, remaining, proceeds, allocated_fee, exit_fee, partial_net)
        if not all(math.isfinite(float(value)) for value in values):
            return self._gap(pending, horizon, now, mono, "numeric_overflow")
        row.update(filled_size=float(taken), unfilled_size=float(remaining), gross_proceeds_usd=float(proceeds),
                   allocated_entry_fee_usd=float(allocated_fee), exit_fee_bound_usd=float(exit_fee),
                   partial_hypothetical_net_usd=float(partial_net),
                   hypothetical_net_usd=float(partial_net) if remaining == 0 else None,
                   consumed_depth=depth, own_bids_subtracted=True, complete_depth=remaining == 0,
                   own_bid_sizes_excluded=[{"price": price, "size": size}
                                           for price, size in sorted(own_bids.items(), reverse=True)])
        pending.remaining.discard(horizon)
        self._counts["measured_horizons"] += 1
        self._counts["full_depth_horizons" if remaining == 0 else "partial_depth_horizons"] += 1
        return row

    def expire(self, *, now: float, mono: float, reason: str | None = None,
               window: str | None = None) -> list[dict[str, Any]]:
        """Make missing evidence explicit on timeout, feed gaps, settlement or shutdown."""
        rows: list[dict[str, Any]] = []
        clock_reason = self._clock_reason(now, mono)
        for pending in tuple(self._pending.values()):
            if window is not None and pending.fill.window != window:
                continue
            for horizon in sorted(pending.remaining):
                why = reason or clock_reason
                if why is None and (now >= pending.window_end or pending.observed_at + horizon >= pending.window_end):
                    why = "market_closed"
                if why is None and mono - pending.observed_mono > horizon + MAX_AGE_S:
                    why = "no_post_horizon_book"
                if why is not None:
                    rows.append(self._gap(pending, horizon, now, mono, why))
            self._remove_if_done(pending)
        for key in tuple(self._by_book):
            self._refresh_due(key)
        return rows

    def status(self) -> dict[str, Any]:
        """No financial total: these samples are not trades or an exit strategy."""
        return {
            "enabled": True, "mode": "diagnostic", "fill_source": "real", "session_id": self.session_id,
            "protocol_version": PROTOCOL_VERSION,
            "basis": "fills_batch_return", "liquidity_scope": "isolated_fill_not_joint_inventory_liquidation",
            "session_only": True, "earlier_pending_unknown": True, "restored_pending": False,
            "started_at": self.started_at, "horizons_s": list(HORIZONS),
            "sampling_method": SAMPLING_METHOD, "max_age_s": MAX_AGE_S,
            "max_levels_per_side": MAX_LEVELS, "max_measurements_per_book": MAX_MEASUREMENTS_PER_BOOK,
            "pending_fills": len(self._pending), "max_pending": self.max_pending,
            "dedup_entries": len(self._seen), "dedup_capacity": self._seen_limit,
            "counts": dict(self._counts), "gap_reasons": dict(self._gaps),
            "not_realized_pnl": True, "exit_latency_not_simulated": True,
        }
