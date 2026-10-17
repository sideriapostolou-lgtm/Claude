"""Independent offline reclaim primitives. No network, account, or third-party imports.

These functions describe conservative observed-snapshot simulations, never venue
fills. There is no network or real-data runner in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from enum import Enum
from typing import Mapping, Sequence

D = Decimal
MINUTE_MS = 60_000
WINDOW_MS = 15 * MINUTE_MS
SOURCE_SHA = "d5a55bf10c02ddc2b429eec78b1fd847fa1b6760"


def decimal(value: object) -> Decimal:
    """Reject implicit binary-float prices and nonfinite public input values."""
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("use exact decimal strings, integers, or Decimal")
    number = value if isinstance(value, Decimal) else D(str(value))
    if not number.is_finite():
        raise ValueError("nonfinite decimal")
    return number


def timestamp(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("timestamp must be a nonnegative integer in milliseconds")


class Side(str, Enum):
    YES = "yes"
    NO = "no"


@dataclass(frozen=True)
class Market:
    ticker: str
    open_ms: int
    close_ms: int
    strike: Decimal

    def __post_init__(self) -> None:
        timestamp(self.open_ms)
        timestamp(self.close_ms)
        object.__setattr__(self, "strike", decimal(self.strike))
        if self.close_ms - self.open_ms != WINDOW_MS:
            raise ValueError(
                "explicit metadata must describe an actual 15-minute window"
            )
        if not self.ticker.startswith("KXBTC15M-") or decimal(self.strike) <= 0:
            raise ValueError("invalid market identity or strike")


@dataclass(frozen=True)
class OHLC:
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    def __post_init__(self) -> None:
        for name in ("open", "high", "low", "close"):
            object.__setattr__(self, name, decimal(getattr(self, name)))
        if self.low > min(self.open, self.close) or self.high < max(
            self.open, self.close
        ):
            raise ValueError("inconsistent OHLC")
        if self.low > self.high:
            raise ValueError("negative candle range")


@dataclass(frozen=True)
class SideCandle:
    ticker: str
    side: Side
    start_ms: int
    end_ms: int
    available_ms: int
    ohlc: OHLC
    availability_assumed: bool

    def __post_init__(self) -> None:
        timestamp(self.start_ms)
        timestamp(self.end_ms)
        timestamp(self.available_ms)
        if self.end_ms - self.start_ms != MINUTE_MS or self.available_ms < self.end_ms:
            raise ValueError("candle must be complete before availability")
        if not D(0) <= self.ohlc.low <= self.ohlc.high <= D(1):
            raise ValueError("side candle prices must be dollars in [0,1]")


@dataclass(frozen=True)
class ClosedCandle:
    product: str
    start_ms: int
    end_ms: int
    available_ms: int
    ohlc: OHLC
    availability_assumed: bool

    def __post_init__(self) -> None:
        timestamp(self.start_ms)
        timestamp(self.end_ms)
        timestamp(self.available_ms)
        if self.end_ms - self.start_ms != MINUTE_MS or self.available_ms < self.end_ms:
            raise ValueError("BTC candle must close before it becomes available")
        if self.ohlc.low <= 0:
            raise ValueError("BTC price must be positive")


@dataclass(frozen=True)
class Quote:
    ts_ms: int
    ticker: str
    yes_bid: Decimal | None
    yes_ask: Decimal | None
    yes_bid_qty: Decimal | None
    yes_ask_qty: Decimal | None
    no_bid: Decimal | None
    no_ask: Decimal | None
    no_bid_qty: Decimal | None
    no_ask_qty: Decimal | None

    def __post_init__(self) -> None:
        timestamp(self.ts_ms)
        for name in ("yes_bid", "yes_ask", "no_bid", "no_ask"):
            value = getattr(self, name)
            if value is not None and not D(0) <= decimal(value) <= D(1):
                raise ValueError("quote price must be dollars in [0,1]")
            if value is not None:
                object.__setattr__(self, name, decimal(value))
        for name in ("yes_bid_qty", "yes_ask_qty", "no_bid_qty", "no_ask_qty"):
            value = getattr(self, name)
            if value is not None and decimal(value) < 0:
                raise ValueError("negative displayed quantity")
            if value is not None:
                object.__setattr__(self, name, decimal(value))

    def level(self, side: Side, action: str) -> tuple[Decimal | None, Decimal | None]:
        if action not in ("buy", "sell"):
            raise ValueError("unknown action")
        suffix = "ask" if action == "buy" else "bid"
        return getattr(self, f"{side.value}_{suffix}"), getattr(
            self, f"{side.value}_{suffix}_qty"
        )

    def crossed(self, side: Side) -> bool:
        bid, _ = self.level(side, "sell")
        ask, _ = self.level(side, "buy")
        return bid is not None and ask is not None and bid > ask

    def complete_side(self, side: Side) -> bool:
        bid, _ = self.level(side, "sell")
        ask, _ = self.level(side, "buy")
        return bid is not None and ask is not None and not self.crossed(side)


@dataclass(frozen=True)
class Spot:
    ts_ms: int
    product: str
    price: Decimal

    def __post_init__(self) -> None:
        timestamp(self.ts_ms)
        object.__setattr__(self, "price", decimal(self.price))
        if decimal(self.price) <= 0:
            raise ValueError("spot must be positive")


@dataclass(frozen=True)
class Coverage:
    valid: bool
    reasons: tuple[str, ...]
    samples: int
    largest_gap_ms: int | None = None


@dataclass(frozen=True)
class SampleBar:
    start_ms: int
    end_ms: int
    available_ms: int
    ohlc: OHLC | None
    coverage: Coverage


@dataclass(frozen=True)
class QualityPolicy:
    """Explicit pending protocol inputs; no implicit gap or freshness defaults."""

    bar_guard_ms: int
    sample_edge_tolerance_ms: int
    max_sample_gap_ms: int
    min_samples_per_minute: int
    signal_quote_max_age_ms: int
    execution_snapshot_timeout_ms: int
    execution_max_gap_ms: int
    ema_warmup_bars: int
    require_all_prior_candidate_bars: bool

    def __post_init__(self) -> None:
        values = (
            self.bar_guard_ms,
            self.sample_edge_tolerance_ms,
            self.max_sample_gap_ms,
            self.min_samples_per_minute,
            self.signal_quote_max_age_ms,
            self.execution_snapshot_timeout_ms,
            self.execution_max_gap_ms,
            self.ema_warmup_bars,
        )
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in values):
            raise ValueError("quality limits must be explicit nonnegative integers")
        if self.min_samples_per_minute < 1 or self.ema_warmup_bars < 21:
            raise ValueError("need samples and at least21 complete EMA warmup bars")


def sampled_bar(
    samples: Sequence[tuple[int, Decimal]],
    start_ms: int,
    end_ms: int,
    policy: QualityPolicy,
) -> SampleBar:
    """Receipt-clock OHLC without carry-forward, interpolation, or future ticks.

    This optional path does not replace official historical Kalshi feature bars.
    Explicit edge/sample-gap limits determine whether a sampled bar is usable.
    """
    if end_ms - start_ms != MINUTE_MS:
        raise ValueError("expected an actual one-minute bucket")
    selected = [(ts, decimal(p)) for ts, p in samples if start_ms <= ts < end_ms]
    reasons = []
    if selected != sorted(selected):
        reasons.append("out_of_order")
    ordered = sorted(selected)
    if len({ts for ts, _ in ordered}) != len(ordered):
        reasons.append("duplicate_timestamp")
    if len(ordered) < policy.min_samples_per_minute:
        reasons.append("insufficient_samples")
    if not ordered:
        return SampleBar(
            start_ms,
            end_ms,
            end_ms + policy.bar_guard_ms,
            None,
            Coverage(False, tuple(reasons + ["empty_bar"]), 0),
        )
    gaps = [b[0] - a[0] for a, b in zip(ordered, ordered[1:])]
    largest = max(gaps, default=0)
    if ordered[0][0] - start_ms > policy.sample_edge_tolerance_ms:
        reasons.append("missing_open_edge")
    if end_ms - 1 - ordered[-1][0] > policy.sample_edge_tolerance_ms:
        reasons.append("missing_close_edge")
    if largest > policy.max_sample_gap_ms:
        reasons.append("sample_gap")
    prices = [p for _, p in ordered]
    return SampleBar(
        start_ms,
        end_ms,
        end_ms + policy.bar_guard_ms,
        OHLC(prices[0], max(prices), min(prices), prices[-1]),
        Coverage(not reasons, tuple(reasons), len(ordered), largest),
    )


def quote_ask_bars(
    market: Market, quotes: Sequence[Quote], side: Side, policy: QualityPolicy
) -> tuple[SampleBar, ...]:
    prices = []
    for quote in quotes:
        price, _ = quote.level(side, "buy")
        if (
            quote.ticker == market.ticker
            and price is not None
            and not quote.crossed(side)
        ):
            prices.append((quote.ts_ms, price))
    return tuple(
        sampled_bar(
            prices,
            market.open_ms + i * MINUTE_MS,
            market.open_ms + (i + 1) * MINUTE_MS,
            policy,
        )
        for i in range(15)
    )


def official_side_candle(
    row: Mapping[str, object], market: Market, side: Side, assumed_guard_ms: int
) -> SideCandle:
    """Parse public raw API OHLC; historical availability remains an assumption."""
    end_seconds = row["end_period_ts"]
    if isinstance(end_seconds, bool) or not isinstance(end_seconds, int):
        raise ValueError("end_period_ts must be integer seconds")
    end_ms = end_seconds * 1000
    if not market.open_ms < end_ms <= market.close_ms:
        raise ValueError("bar belongs outside this market window")
    if (end_ms - market.open_ms) % MINUTE_MS:
        raise ValueError("bar does not align with actual market window")
    key = "yes_ask" if side == Side.YES else "yes_bid"
    node = row.get(key)
    if not isinstance(node, Mapping):
        raise ValueError("missing side OHLC")
    values = {
        name: decimal(node[f"{name}_dollars"])
        for name in ("open", "high", "low", "close")
    }
    if side == Side.NO:
        values = {
            "open": 1 - values["open"],
            "high": 1 - values["low"],
            "low": 1 - values["high"],
            "close": 1 - values["close"],
        }
    return SideCandle(
        market.ticker,
        side,
        end_ms - MINUTE_MS,
        end_ms,
        end_ms + assumed_guard_ms,
        OHLC(**values),
        True,
    )


@dataclass(frozen=True)
class BtcContext:
    available: bool
    reason: str
    decision_ms: int
    first_five_return: Decimal | None = None
    ema21: Decimal | None = None
    decision_close_minus_ema: Decimal | None = None
    availability_assumed: bool = True


def btc_context(
    market: Market, candles: Sequence[ClosedCandle], at_ms: int, policy: QualityPolicy
) -> BtcContext:
    cutoff = market.open_ms + 5 * MINUTE_MS

    def unavailable(why: str) -> BtcContext:
        return BtcContext(False, why, cutoff + policy.bar_guard_ms)

    if at_ms < cutoff + policy.bar_guard_ms:
        return unavailable("first_five_not_available")
    # Freeze features as of the declared decision time; future availability or
    # later revision of an old candle cannot silently enter the context.
    declared_decision = cutoff + policy.bar_guard_ms
    history_start = market.open_ms - policy.ema_warmup_bars * WINDOW_MS
    eligible = [
        c
        for c in candles
        if c.product == "BTC-USD"
        and c.start_ms >= history_start
        and c.end_ms <= cutoff
        and c.available_ms <= declared_decision
    ]
    by_start = {}
    for candle in eligible:
        if candle.start_ms in by_start:
            return unavailable("duplicate_btc_candle")
        by_start[candle.start_ms] = candle
    first = [by_start.get(market.open_ms + i * MINUTE_MS) for i in range(5)]
    if any(c is None for c in first):
        return unavailable("missing_first_five_btc_bar")
    if market.open_ms % WINDOW_MS:
        return unavailable("market_not_utc_quarter_aligned")
    # Fixed complete warmup, not a variable prefix chosen after seeing outcomes.
    if history_start < 0:
        return unavailable("insufficient_ema_history")
    closes = []
    for index in range(policy.ema_warmup_bars):
        start = history_start + index * WINDOW_MS
        chunk = [by_start.get(start + minute * MINUTE_MS) for minute in range(15)]
        if any(c is None for c in chunk):
            return unavailable("missing_complete_ema_bucket")
        last = chunk[-1]
        assert last is not None  # All required starts were checked above.
        closes.append(last.ohlc.close)
    first_open, fifth_close = first[0], first[-1]
    assert first_open is not None and fifth_close is not None
    with localcontext() as ctx:
        ctx.prec = 50
        alpha = D(2) / D(22)
        estimate = closes[0]
        for close in closes[1:]:
            estimate = alpha * close + (1 - alpha) * estimate
        change = fifth_close.ohlc.close - first_open.ohlc.open
        distance = fifth_close.ohlc.close - estimate
    assumed = any(c.availability_assumed for c in eligible)
    return BtcContext(
        True, "ok", declared_decision, change, estimate, distance, assumed
    )


@dataclass(frozen=True)
class LaneRule:
    name: str
    side: Side
    early_gt: Decimal
    early_lte: Decimal
    entry_gte: Decimal
    entry_lt: Decimal
    live_ask_gte: Decimal
    live_ask_lte: Decimal
    signed_btc_gte: Decimal
    signed_btc_lte: Decimal
    ema_gte: Decimal | None
    ema_lt: Decimal | None
    target: Decimal


def current_rules(cards: Mapping[str, object]) -> tuple[LaneRule, ...]:
    if cards.get("source_sha") != SOURCE_SHA:
        raise ValueError("rulecard source pin mismatch")
    lanes = cards.get("current_lanes")
    if (
        not isinstance(lanes, list)
        or {r.get("id") for r in lanes} != {"RECLAIM_70", "NO_RECLAIM_80"}
        or len(lanes) != 2
    ):
        raise ValueError("exactly the two current lanes are required")
    rules = []
    for row in lanes:
        side = Side(row["side"])
        early = row.get("early_ask_low_dollars") or row["early_side_ask_low_dollars"]
        close = row["latest_side_ask_close_dollars"]
        live = row["current_side_ask_dollars"]
        change = (
            row.get("first_five_btc_return_usd")
            or row["side_signed_first_five_btc_return_usd"]
        )
        ema = row.get("decision_btc_close_minus_15m_ema21_usd")
        rules.append(
            LaneRule(
                row["id"],
                side,
                decimal(early["gt"]),
                decimal(early["lte"]),
                decimal(close["gte"]),
                decimal(close["lt"]),
                decimal(live["gte"]),
                decimal(live["lte"]),
                decimal(change["gte"]),
                decimal(change["lte"]),
                decimal(ema["gte"]) if ema else None,
                decimal(ema["lt"]) if ema else None,
                decimal(row["exit_limit_cents"]) / 100,
            )
        )
    return tuple(sorted(rules, key=lambda r: r.name))


@dataclass(frozen=True)
class SignalDecision:
    eligible: bool
    unknown: bool
    reasons: tuple[str, ...]
    lane: str
    bar_minute: int
    detected_ms: int


def signal_decision(
    rule: LaneRule,
    market: Market,
    candles: Sequence[SideCandle],
    context: BtcContext,
    latest_minute: int,
    quote: Quote,
    at_ms: int,
    policy: QualityPolicy,
) -> SignalDecision:
    def result(reasons: list[str], unknown: bool = False) -> SignalDecision:
        return SignalDecision(
            not reasons, unknown, tuple(reasons), rule.name, latest_minute, at_ms
        )

    if not 6 <= latest_minute <= 10:
        return result(["outside_entry_bar_window"])
    if at_ms > market.close_ms - 5 * MINUTE_MS or at_ms >= market.close_ms:
        return result(["entry_cutoff"])
    if quote.ticker != market.ticker:
        return result(["cross_ticker_quote"], True)
    if (
        quote.ts_ms < market.open_ms
        or quote.ts_ms > at_ms
        or at_ms - quote.ts_ms > policy.signal_quote_max_age_ms
    ):
        return result(["unavailable_or_stale_quote"], True)
    selected = [
        c
        for c in candles
        if c.ticker == market.ticker
        and c.side == rule.side
        and c.available_ms <= at_ms
        and c.end_ms <= market.open_ms + latest_minute * MINUTE_MS
    ]
    by_minute = {}
    for candle in selected:
        offset = candle.end_ms - market.open_ms
        if offset % MINUTE_MS or candle.start_ms < market.open_ms:
            return result(["misaligned_market_candle"], True)
        minute = offset // MINUTE_MS
        if minute in by_minute:
            return result(["duplicate_market_candle"], True)
        by_minute[minute] = candle
    needed = (
        set(range(1, latest_minute + 1))
        if policy.require_all_prior_candidate_bars
        else {*range(1, 6), latest_minute}
    )
    if any(i not in by_minute for i in needed):
        return result(["missing_required_market_bar"], True)
    if any(by_minute[i].available_ms > at_ms for i in needed):
        return result(["incomplete_or_unavailable_market_bar"], True)
    latest = by_minute[latest_minute]
    if at_ms >= latest.end_ms + MINUTE_MS + policy.bar_guard_ms:
        return result(["stale_signal_bar"], True)
    if not context.available or context.decision_ms > at_ms:
        return result(["btc_context:" + context.reason], True)
    if context.first_five_return is None or context.ema21 is None:
        return result(["incomplete_btc_context"], True)
    ask, qty = quote.level(rule.side, "buy")
    if ask is None or qty is None or not quote.complete_side(rule.side):
        return result(["invalid_current_ask"], True)
    if qty < D(1):
        return result(["insufficient_signal_top_size"])
    early_low = min(by_minute[i].ohlc.low for i in range(1, 6))
    signed_return = context.first_five_return * (1 if rule.side == Side.YES else -1)
    checks = {
        "early_low_band": rule.early_gt < early_low <= rule.early_lte,
        "close_band": rule.entry_gte <= latest.ohlc.close < rule.entry_lt,
        "live_ask_band": rule.live_ask_gte <= ask <= rule.live_ask_lte,
        "reclaim_minute5": latest.ohlc.close > by_minute[5].ohlc.close,
        "green_candle": latest.ohlc.close > latest.ohlc.open,
        "btc_return_band": rule.signed_btc_gte <= signed_return <= rule.signed_btc_lte,
    }
    if rule.ema_gte is not None:
        distance = context.decision_close_minus_ema
        checks["ema_distance_band"] = (
            distance is not None
            and rule.ema_lt is not None
            and rule.ema_gte <= distance < rule.ema_lt
        )
    return result([name for name, passed in checks.items() if not passed])


@dataclass(frozen=True)
class FeeDebit:
    model_fee: Decimal
    actual_fee: Decimal
    signed_balance_change: Decimal

    @property
    def balance_debit(self) -> Decimal:
        """Compatibility name: effective fee, NOT total purchase debit."""
        return self.actual_fee


@dataclass(frozen=True)
class FeeAccumulator:
    """One order; ceil model6dp, floor signed net revenue4dp cumulatively."""

    model_total: Decimal = D(0)
    balance_total: Decimal = D(0)
    gross_total: Decimal = D(0)
    action: str | None = None

    def add(
        self, count: Decimal, price: Decimal, action: str = "buy"
    ) -> tuple[FeeDebit, FeeAccumulator]:
        count, price = decimal(count), decimal(price)
        if count < 0 or not D(0) <= price <= D(1) or action not in ("buy", "sell"):
            raise ValueError("invalid fee input")
        if self.action is not None and action != self.action:
            raise ValueError("one order cannot mix buy and sell accumulators")
        with localcontext() as ctx:
            ctx.prec = 50
            model = (D("0.07") * count * price * (1 - price)).quantize(
                D("0.000001"), rounding=ROUND_CEILING
            )
            total = self.model_total + model
            gross_increment = count * price
            gross = self.gross_total + gross_increment
            signed_gross = -gross if action == "buy" else gross
            balance = (signed_gross - total).quantize(D("0.0001"), rounding=ROUND_FLOOR)
            change = balance - self.balance_total
            fee = (
                -change - gross_increment
                if action == "buy"
                else gross_increment - change
            )
        return FeeDebit(model, fee, change), FeeAccumulator(
            total, balance, gross, action
        )


class AttemptStatus(str, Enum):
    OBSERVED_SNAPSHOT_FILL = "observed_snapshot_fill"
    UNFILLED = "unfilled"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Attempt:
    status: AttemptStatus
    reason: str
    side: Side
    action: str
    trigger_ms: int
    ready_ms: int
    observed_ms: int | None
    requested_count: Decimal
    simulated_count: Decimal | None
    price: Decimal | None = None
    fee: FeeDebit | None = None


def delayed_attempt(
    market: Market,
    quotes: Sequence[Quote],
    side: Side,
    action: str,
    trigger_ms: int,
    count: Decimal,
    deadline_ms: int,
    policy: QualityPolicy,
    delay_ms: int = 1000,
    price_band: tuple[Decimal, Decimal] | None = None,
) -> Attempt:
    """Use first sampled snapshot after delay, never search for a better fill.

    A sufficient sampled top size permits an observed-snapshot simulation only;
    it is not evidence that liquidity survived between1Hz samples or our arrival.
    """
    count = decimal(count)
    if count <= 0 or action not in ("buy", "sell") or delay_ms < 0:
        raise ValueError("invalid simulated order")
    ready = trigger_ms + delay_ms

    def answer(
        status: AttemptStatus,
        why: str,
        q: Quote | None = None,
        price: Decimal | None = None,
    ) -> Attempt:
        filled = (
            count
            if status == AttemptStatus.OBSERVED_SNAPSHOT_FILL
            else D(0)
            if status == AttemptStatus.UNFILLED
            else None
        )
        fee = None
        if filled == count:
            assert price is not None
            fee = FeeAccumulator().add(count, price, action)[0]
        return Attempt(
            status,
            why,
            side,
            action,
            trigger_ms,
            ready,
            q.ts_ms if q else None,
            count,
            filled,
            price,
            fee,
        )

    deadline = min(deadline_ms, market.close_ms - 1)
    if trigger_ms < market.open_ms or ready > deadline:
        return answer(AttemptStatus.UNFILLED, "outside_execution_window")
    same = sorted(
        (
            q
            for q in quotes
            if q.ticker == market.ticker and market.open_ms <= q.ts_ms <= deadline
        ),
        key=lambda q: q.ts_ms,
    )
    before = [q for q in same if q.ts_ms <= trigger_ms]
    candidates = [q for q in same if ready <= q.ts_ms <= deadline]
    if not candidates:
        return answer(AttemptStatus.UNKNOWN, "missing_delayed_snapshot")
    observed = candidates[0]
    # A future malformed frame cannot invalidate an earlier execution decision.
    visible = [q for q in same if q.ts_ms <= observed.ts_ms]
    received = [
        q.ts_ms
        for q in quotes
        if q.ticker == market.ticker and market.open_ms <= q.ts_ms <= observed.ts_ms
    ]
    if received != sorted(received):
        return answer(AttemptStatus.UNKNOWN, "reversed_receipt_clock", observed)
    if len({q.ts_ms for q in visible}) != len(visible):
        return answer(AttemptStatus.UNKNOWN, "duplicate_quote_timestamp", observed)
    if observed.ts_ms - ready > policy.execution_snapshot_timeout_ms:
        return answer(AttemptStatus.UNKNOWN, "delayed_snapshot_too_late", observed)
    if not before or trigger_ms - before[-1].ts_ms > policy.execution_max_gap_ms:
        return answer(AttemptStatus.UNKNOWN, "missing_trigger_coverage", observed)
    bridge = [before[-1]] + [q for q in same if trigger_ms < q.ts_ms <= observed.ts_ms]
    if any(
        b.ts_ms - a.ts_ms > policy.execution_max_gap_ms
        for a, b in zip(bridge, bridge[1:])
    ):
        return answer(AttemptStatus.UNKNOWN, "gap_across_execution_delay", observed)
    price, qty = observed.level(side, action)
    if price is None or qty is None or not observed.complete_side(side):
        return answer(
            AttemptStatus.UNKNOWN, "missing_or_invalid_executable_level", observed
        )
    if price <= 0 or price >= 1:
        # Pre-confirmation proxy validity convention, not a venue-rejection claim.
        return answer(AttemptStatus.UNFILLED, "nontradable_price", observed, price)
    if price_band is not None and not price_band[0] <= price <= price_band[1]:
        return answer(AttemptStatus.UNFILLED, "outside_price_band", observed, price)
    if qty < count:
        return answer(
            AttemptStatus.UNFILLED, "insufficient_observed_top_size", observed, price
        )
    return answer(
        AttemptStatus.OBSERVED_SNAPSHOT_FILL,
        "sampled_top_price_and_size_only",
        observed,
        price,
    )


@dataclass(frozen=True)
class Settlement:
    ticker: str
    result: Side
    available_ms: int
    official: bool

    def __post_init__(self) -> None:
        timestamp(self.available_ms)
        if not isinstance(self.result, Side) or not isinstance(self.official, bool):
            raise ValueError("explicit binary result and provenance required")


@dataclass(frozen=True)
class Position:
    ticker: str
    side: Side
    count: Decimal
    entry_price: Decimal
    entry_fee: Decimal
    entry_ms: int

    def __post_init__(self) -> None:
        timestamp(self.entry_ms)
        for name in ("count", "entry_price", "entry_fee"):
            object.__setattr__(self, name, decimal(getattr(self, name)))
        if (
            self.count <= 0
            or not D(0) <= self.entry_price <= D(1)
            or self.entry_fee < 0
        ):
            raise ValueError("invalid position")

    @property
    def debit(self) -> Decimal:
        return self.count * self.entry_price + self.entry_fee


@dataclass(frozen=True)
class SettlementScore:
    known: bool
    reason: str
    payout: Decimal | None
    pnl: Decimal | None
    lower_pnl: Decimal
    upper_pnl: Decimal


def settle(
    position: Position, market: Market, label: Settlement | None, at_ms: int
) -> SettlementScore:
    lower, upper = -position.debit, position.count - position.debit
    why = None
    if position.ticker != market.ticker:
        raise ValueError("position/market identity mismatch")
    if at_ms < market.close_ms:
        why = "market_not_closed"
    elif label is None:
        why = "missing_official_settlement"
    elif label.ticker != position.ticker:
        why = "cross_ticker_settlement"
    elif not label.official:
        why = "nonofficial_settlement"
    elif label.available_ms < market.close_ms or label.available_ms > at_ms:
        why = "settlement_unavailable_at_score_time"
    if why:
        return SettlementScore(False, why, None, None, lower, upper)
    assert label is not None
    payout = position.count if label.result == position.side else D(0)
    pnl = payout - position.debit
    return SettlementScore(True, "official", payout, pnl, pnl, pnl)


@dataclass(frozen=True)
class EntrySearch:
    market: Market
    lane: LaneRule
    decisions: tuple[SignalDecision, ...]
    attempt: Attempt | None
    position: Position | None
    unknown: bool
    reason: str
    entry_limit: Decimal | None = None


@dataclass(frozen=True)
class UnknownEntryRisk:
    """Attempted entry uncertainty; no known position is invented."""

    entry_limit: Decimal
    maximum_entry_fee: Decimal
    lower_pnl: Decimal
    upper_pnl: Decimal


def unknown_entry_risk(entry: EntrySearch) -> UnknownEntryRisk | None:
    if entry.attempt is None or entry.attempt.status != AttemptStatus.UNKNOWN:
        return None
    if entry.entry_limit is None:
        raise ValueError("unknown attempt must retain its decision limit")
    # A cheaper in-band fill cannot cost more including this fee: p+.07p(1-p)
    # is increasing on [0,1]. The upper bound permits a free winning unit.
    fee = FeeAccumulator().add(D(1), entry.entry_limit)[0].balance_debit
    return UnknownEntryRisk(entry.entry_limit, fee, -entry.entry_limit - fee, D(1))


def find_entry(
    market: Market,
    quotes: Sequence[Quote],
    candles: Sequence[SideCandle],
    btc_candles: Sequence[ClosedCandle],
    rule: LaneRule,
    policy: QualityPolicy,
    delay_ms: int = 1000,
) -> EntrySearch:
    """First qualifying complete bar, one entry attempt, fixed1 contract.

    No label/outcome argument exists in this phase. Bar10 is recorded as a
    cutoff rejection rather than quietly dropping the nominal source endpoint.
    """
    context = btc_context(
        market,
        btc_candles,
        market.open_ms + 5 * MINUTE_MS + policy.bar_guard_ms,
        policy,
    )
    decisions = []
    for minute in range(6, 11):
        decision_ms = market.open_ms + minute * MINUTE_MS + policy.bar_guard_ms
        known_quotes = [
            q
            for q in quotes
            if q.ticker == market.ticker and market.open_ms <= q.ts_ms <= decision_ms
        ]
        if minute == 10:
            decisions.append(
                SignalDecision(
                    False, False, ("entry_cutoff",), rule.name, minute, decision_ms
                )
            )
            continue
        if not known_quotes:
            decision = SignalDecision(
                False, True, ("missing_signal_quote",), rule.name, minute, decision_ms
            )
        else:
            latest_ts = max(q.ts_ms for q in known_quotes)
            latest_quotes = [q for q in known_quotes if q.ts_ms == latest_ts]
            if len(latest_quotes) != 1:
                decision = SignalDecision(
                    False,
                    True,
                    ("duplicate_signal_quote",),
                    rule.name,
                    minute,
                    decision_ms,
                )
            else:
                decision = signal_decision(
                    rule,
                    market,
                    candles,
                    context,
                    minute,
                    latest_quotes[0],
                    decision_ms,
                    policy,
                )
        decisions.append(decision)
        if decision.unknown:
            # Cannot infer that a later observed entry was the first signal if
            # an earlier candidate's necessary inputs were not observable.
            return EntrySearch(
                market,
                rule,
                tuple(decisions),
                None,
                None,
                True,
                "unobservable_candidate_before_first_signal",
            )
        if not decision.eligible:
            continue
        quote = latest_quotes[0]
        limit, _ = quote.level(rule.side, "buy")
        assert limit is not None  # An eligible decision validated the ask.
        attempt = delayed_attempt(
            market,
            quotes,
            rule.side,
            "buy",
            decision_ms,
            D(1),
            market.close_ms - 5 * MINUTE_MS,
            policy,
            delay_ms,
            (rule.live_ask_gte, min(rule.live_ask_lte, limit)),
        )
        position = None
        if attempt.status == AttemptStatus.OBSERVED_SNAPSHOT_FILL:
            assert (
                attempt.price is not None
                and attempt.fee is not None
                and attempt.observed_ms is not None
            )
            position = Position(
                market.ticker,
                rule.side,
                D(1),
                attempt.price,
                attempt.fee.balance_debit,
                attempt.observed_ms,
            )
        return EntrySearch(
            market,
            rule,
            tuple(decisions),
            attempt,
            position,
            attempt.status == AttemptStatus.UNKNOWN,
            "first_signal_attempt:" + attempt.reason,
            limit,
        )
    return EntrySearch(market, rule, tuple(decisions), None, None, False, "no_signal")


@dataclass(frozen=True)
class ExitSearch:
    position: Position
    target: Decimal
    attempts: tuple[Attempt, ...]
    filled: Attempt | None
    unknown: bool
    holding_gap_count: int
    largest_holding_gap_ms: int


def find_exit(
    position: Position,
    market: Market,
    quotes: Sequence[Quote],
    target: Decimal,
    policy: QualityPolicy,
    delay_ms: int = 1000,
) -> ExitSearch:
    """Observed target triggers only; delayed bid must still meet target/size.

    On a known failed arrival wait for a new observed target trigger. Never
    backfill from a minute high or the old trigger quote. Unknown arrival leaves
    outcome bounds unresolved; we do not silently force an assumed holding P&L.
    """
    if position.ticker != market.ticker:
        raise ValueError("position/market identity mismatch")
    seen = sorted(
        (
            q
            for q in quotes
            if q.ticker == market.ticker
            and position.entry_ms < q.ts_ms < market.close_ms
        ),
        key=lambda q: q.ts_ms,
    )

    def holding_gaps(until_ms: int) -> tuple[int, int]:
        times = [position.entry_ms] + [q.ts_ms for q in seen if q.ts_ms <= until_ms]
        if times[-1] != until_ms:
            times.append(until_ms)
        gaps = [b - a for a, b in zip(times, times[1:])]
        return sum(g > policy.execution_max_gap_ms for g in gaps), max(gaps, default=0)

    attempts = []
    next_trigger_ms = position.entry_ms + 1
    for quote in seen:
        if quote.ts_ms < next_trigger_ms:
            continue
        bid, qty = quote.level(position.side, "sell")
        if bid is None or qty is None or not quote.complete_side(position.side):
            continue
        if bid < target or qty < position.count:
            continue
        attempt = delayed_attempt(
            market,
            quotes,
            position.side,
            "sell",
            quote.ts_ms,
            position.count,
            market.close_ms - 1,
            policy,
            delay_ms,
            (target, D(1)),
        )
        attempts.append(attempt)
        if attempt.status == AttemptStatus.OBSERVED_SNAPSHOT_FILL:
            assert attempt.observed_ms is not None
            gap_count, largest = holding_gaps(attempt.observed_ms)
            return ExitSearch(
                position, target, tuple(attempts), attempt, False, gap_count, largest
            )
        if attempt.status == AttemptStatus.UNKNOWN:
            gap_count, largest = holding_gaps(attempt.observed_ms or market.close_ms)
            return ExitSearch(
                position, target, tuple(attempts), None, True, gap_count, largest
            )
        # A failed arrival cannot generate a simultaneous second order. This
        # policy waits for the next sampled target observation after arrival.
        next_trigger_ms = (attempt.observed_ms or attempt.ready_ms) + 1
    gap_count, largest = holding_gaps(market.close_ms)
    return ExitSearch(
        position, target, tuple(attempts), None, False, gap_count, largest
    )


@dataclass(frozen=True)
class TradeScore:
    known: bool
    reason: str
    entry_debit: Decimal
    exit_or_settlement_credit: Decimal | None
    net_pnl: Decimal | None
    lower_pnl: Decimal
    upper_pnl: Decimal
    total_fees: Decimal | None


def score_trade(
    exits: ExitSearch, market: Market, label: Settlement | None, at_ms: int
) -> TradeScore:
    """Labels enter only after entries/exits are frozen."""
    position = exits.position
    lower, upper = -position.debit, position.count - position.debit
    if exits.unknown:
        return TradeScore(
            False,
            "unobservable_exit_arrival",
            position.debit,
            None,
            None,
            lower,
            upper,
            None,
        )
    if exits.filled is not None:
        fill = exits.filled
        assert fill.price is not None and fill.fee is not None
        credit = position.count * fill.price - fill.fee.balance_debit
        pnl = credit - position.debit
        return TradeScore(
            True,
            "observed_snapshot_exit",
            position.debit,
            credit,
            pnl,
            pnl,
            pnl,
            position.entry_fee + fill.fee.balance_debit,
        )
    result = settle(position, market, label, at_ms)
    return TradeScore(
        result.known,
        result.reason,
        position.debit,
        result.payout,
        result.pnl,
        result.lower_pnl,
        result.upper_pnl,
        position.entry_fee if result.known else None,
    )


def hold_control(position: Position) -> ExitSearch:
    """Control on identical entry; no target attempts, so no borrowed exit P&L."""
    return ExitSearch(position, D(1), (), None, False, 0, 0)


def quote_from_row(row: Mapping[str, str], *, price_unit: str) -> Quote:
    """Adapter boundary requires explicit cents/dollars; blanks stay unknown."""
    if price_unit not in ("dollars", "cents"):
        raise ValueError("explicit dollars or cents required")
    divisor = D(100) if price_unit == "cents" else D(1)

    def number(key: str, price: bool = False) -> Decimal | None:
        value = row.get(key)
        if value is None or not value.strip():
            return None
        return decimal(value) / divisor if price else decimal(value)

    return Quote(
        int(row["ts_ms"]),
        row["ticker"],
        number("yes_bid", True),
        number("yes_ask", True),
        number("yes_bid_qty"),
        number("yes_ask_qty"),
        number("no_bid", True),
        number("no_ask", True),
        number("no_bid_qty"),
        number("no_ask_qty"),
    )


def coinbase_closed_candle(
    raw: Sequence[object], assumed_guard_ms: int
) -> ClosedCandle:
    """Historical Coinbase row [start_seconds,low,high,open,close,volume]."""
    if len(raw) < 6 or isinstance(raw[0], bool) or not isinstance(raw[0], int):
        raise ValueError("invalid Coinbase candle row")
    start = raw[0] * 1000
    end = start + MINUTE_MS
    return ClosedCandle(
        "BTC-USD",
        start,
        end,
        end + assumed_guard_ms,
        OHLC(decimal(raw[3]), decimal(raw[2]), decimal(raw[1]), decimal(raw[4])),
        True,
    )
