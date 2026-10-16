"""Synthetic, outcome-independent causal and accounting tests; stdlib only."""

import unittest
from dataclasses import replace
from decimal import Decimal as D

from replay import (
    MINUTE_MS,
    OHLC,
    SOURCE_SHA,
    WINDOW_MS,
    AttemptStatus,
    BtcContext,
    ClosedCandle,
    FeeAccumulator,
    LaneRule,
    Market,
    Position,
    QualityPolicy,
    Quote,
    Settlement,
    Side,
    SideCandle,
    btc_context,
    coinbase_closed_candle,
    current_rules,
    delayed_attempt,
    find_entry,
    find_exit,
    hold_control,
    official_side_candle,
    quote_ask_bars,
    quote_from_row,
    sampled_bar,
    score_trade,
    settle,
    signal_decision,
    unknown_entry_risk,
)

POLICY = QualityPolicy(1000, 1000, 1500, 60, 2000, 2000, 3000, 32, True)
MARKET = Market("KXBTC15M-SYNTHETIC", 36 * WINDOW_MS, 37 * WINDOW_MS, D("10000"))
YES = LaneRule(
    "RECLAIM_70",
    Side.YES,
    D(".15"),
    D(".30"),
    D(".35"),
    D(".55"),
    D(".35"),
    D(".55"),
    D(-20),
    D(20),
    D(-150),
    D(-50),
    D(".70"),
)
NO = LaneRule(
    "NO_RECLAIM_80",
    Side.NO,
    D(".35"),
    D(".40"),
    D(".50"),
    D(".70"),
    D(".50"),
    D(".70"),
    D(-75),
    D(-25),
    None,
    None,
    D(".80"),
)


def quote(
    offset: int,
    bid: str = ".49",
    ask: str = ".50",
    qty: str = "5",
    ticker: str = MARKET.ticker,
) -> Quote:
    bid_value, ask_value, qty_value = D(bid), D(ask), D(qty)
    return Quote(
        MARKET.open_ms + offset,
        ticker,
        bid_value,
        ask_value,
        qty_value,
        qty_value,
        1 - ask_value,
        1 - bid_value,
        qty_value,
        qty_value,
    )


def btc_candles(change: str = "0") -> list[ClosedCandle]:
    candles = []
    start = MARKET.open_ms - 32 * WINDOW_MS
    for index in range(32 * 15):
        t = start + index * MINUTE_MS
        candles.append(
            ClosedCandle(
                "BTC-USD",
                t,
                t + MINUTE_MS,
                t + MINUTE_MS + 1000,
                OHLC(D(10100), D(10100), D(10100), D(10100)),
                True,
            )
        )
    for minute in range(5):
        t = MARKET.open_ms + minute * MINUTE_MS
        op = D(10000)
        close = op + (D(change) if minute == 4 else D(0))
        candles.append(
            ClosedCandle(
                "BTC-USD",
                t,
                t + MINUTE_MS,
                t + MINUTE_MS + 1000,
                OHLC(op, max(op, close), min(op, close), close),
                True,
            )
        )
    return candles


def side_candles(side: Side = Side.YES) -> list[SideCandle]:
    result = []
    for minute in range(1, 11):
        end = MARKET.open_ms + minute * MINUTE_MS
        if side == Side.YES:
            values = (
                (".40", ".45", ".20", ".40")
                if minute <= 5
                else (".40", ".50", ".40", ".50")
            )
        else:
            values = (
                (".45", ".50", ".37", ".45")
                if minute <= 5
                else (".50", ".60", ".50", ".60")
            )
        result.append(
            SideCandle(
                MARKET.ticker,
                side,
                end - MINUTE_MS,
                end,
                end + 1000,
                OHLC(*(D(v) for v in values)),
                True,
            )
        )
    return result


def context(change: str = "0", distance: str = "-100") -> BtcContext:
    return BtcContext(
        True, "ok", MARKET.open_ms + 301000, D(change), D(10100), D(distance), True
    )


def position() -> Position:
    return Position(
        MARKET.ticker, Side.YES, D(1), D(".50"), D(".0175"), MARKET.open_ms + 362000
    )


class ClockAndBarTests(unittest.TestCase):
    def test_sample_bucket_excludes_next_minute_tick(self):
        points = [(i * 1000, D(i)) for i in range(60)] + [(60000, D(999))]
        bar = sampled_bar(points, 0, 60000, POLICY)
        self.assertTrue(bar.coverage.valid)
        assert bar.ohlc is not None
        self.assertEqual(bar.ohlc.close, D(59))
        self.assertEqual(bar.available_ms, 61000)

    def test_sample_missing_or_duplicate_ticks_are_visible(self):
        points = [(i * 1000, D(1)) for i in range(60) if i not in (20, 21)]
        bar = sampled_bar(points, 0, 60000, POLICY)
        self.assertIn("sample_gap", bar.coverage.reasons)
        self.assertIn("insufficient_samples", bar.coverage.reasons)
        duplicate = sampled_bar(points + [points[-1]], 0, 60000, POLICY)
        self.assertIn("duplicate_timestamp", duplicate.coverage.reasons)

    def test_receipt_sample_bars_never_borrow_other_ticker(self):
        bars = quote_ask_bars(
            MARKET, [quote(0, ticker="KXBTC15M-OTHER")], Side.YES, POLICY
        )
        self.assertFalse(bars[0].coverage.valid)
        self.assertEqual(bars[0].coverage.samples, 0)

    def test_no_side_ohlc_complements_yes_bid_extrema(self):
        row = {
            "end_period_ts": (MARKET.open_ms + 60000) // 1000,
            "yes_bid": {
                "open_dollars": ".60",
                "high_dollars": ".80",
                "low_dollars": ".30",
                "close_dollars": ".70",
            },
        }
        bar = official_side_candle(row, MARKET, Side.NO, 1000)
        self.assertEqual(bar.ohlc, OHLC(D(".40"), D(".70"), D(".20"), D(".30")))
        self.assertTrue(bar.availability_assumed)
        self.assertEqual(bar.available_ms, MARKET.open_ms + 61000)

    def test_official_bar_wrong_window_or_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            official_side_candle(
                {"end_period_ts": MARKET.open_ms // 1000}, MARKET, Side.YES, 1000
            )

    def test_coinbase_start_label_cannot_be_used_as_same_time_close(self):
        bar = coinbase_closed_candle(
            [MARKET.open_ms // 1000, "9999", "10002", "10000", "10001", "2"], 1000
        )
        self.assertEqual(bar.end_ms, MARKET.open_ms + MINUTE_MS)
        self.assertEqual(bar.available_ms, MARKET.open_ms + MINUTE_MS + 1000)

    def test_first5_context_and_exact32_warmup(self):
        result = btc_context(MARKET, btc_candles(), MARKET.open_ms + 301000, POLICY)
        self.assertTrue(result.available)
        self.assertEqual(result.first_five_return, 0)
        self.assertEqual(result.ema21, 10100)
        self.assertEqual(result.decision_close_minus_ema, -100)

    def test_missing_warmup_minute_does_not_silently_shorten_ema(self):
        candles = btc_candles()
        del candles[20]
        result = btc_context(MARKET, candles, MARKET.open_ms + 301000, POLICY)
        self.assertEqual(result.reason, "missing_complete_ema_bucket")

    def test_context_is_invariant_to_future_start_labelled_close(self):
        candles = btc_candles()
        cutoff = MARKET.open_ms + 300000
        future = ClosedCandle(
            "BTC-USD",
            cutoff,
            cutoff + MINUTE_MS,
            cutoff + MINUTE_MS + 1000,
            OHLC(D(10000), D(99999), D(10000), D(99999)),
            True,
        )
        self.assertEqual(
            btc_context(MARKET, candles, cutoff + 1000, POLICY),
            btc_context(MARKET, candles + [future], cutoff + 1000, POLICY),
        )

    def test_late_old_candle_revision_cannot_enter_frozen_cutoff(self):
        candles = btc_candles()
        candles[-1] = replace(candles[-1], available_ms=MARKET.open_ms + 302000)
        result = btc_context(MARKET, candles, MARKET.open_ms + 400000, POLICY)
        self.assertEqual(result.reason, "missing_first_five_btc_bar")


class RuleTests(unittest.TestCase):
    def test_rulecard_pin_two_current_lanes_and_retired_exclusion(self):
        rows = []
        for rule in (YES, NO):
            row = {
                "id": rule.name,
                "side": rule.side.value,
                "early_side_ask_low_dollars": {
                    "gt": str(rule.early_gt),
                    "lte": str(rule.early_lte),
                },
                "latest_side_ask_close_dollars": {
                    "gte": str(rule.entry_gte),
                    "lt": str(rule.entry_lt),
                },
                "current_side_ask_dollars": {
                    "gte": str(rule.live_ask_gte),
                    "lte": str(rule.live_ask_lte),
                },
                "side_signed_first_five_btc_return_usd": {
                    "gte": str(rule.signed_btc_gte),
                    "lte": str(rule.signed_btc_lte),
                },
                "exit_limit_cents": str(rule.target * 100),
            }
            if rule.ema_gte is not None:
                row["decision_btc_close_minus_15m_ema21_usd"] = {
                    "gte": str(rule.ema_gte),
                    "lt": str(rule.ema_lt),
                }
            rows.append(row)
        cards = {
            "source_sha": SOURCE_SHA,
            "current_lanes": rows,
            "retired_lanes": [{"id": "BTC_FADE_90"}],
        }
        self.assertEqual(set(current_rules(cards)), {YES, NO})
        with self.assertRaises(ValueError):
            current_rules({**cards, "source_sha": "unfrozen"})
        with self.assertRaises(ValueError):
            current_rules({**cards, "current_lanes": rows + [{"id": "BTC_FADE_90"}]})

    def decide(self, rule=YES, bars=None, ctx=None, q=None, minute=6, at=None):
        return signal_decision(
            rule,
            MARKET,
            bars or side_candles(rule.side),
            ctx or context(),
            minute,
            q or quote(361000),
            at or MARKET.open_ms + 361000,
            POLICY,
        )

    def test_yes_exact_boundaries(self):
        self.assertTrue(self.decide().eligible)
        self.assertTrue(self.decide(ctx=context("-20", "-150")).eligible)
        self.assertFalse(self.decide(ctx=context("20.00001")).eligible)
        self.assertFalse(self.decide(ctx=context("0", "-50")).eligible)
        bars = side_candles()
        bars[0] = replace(bars[0], ohlc=OHLC(D(".4"), D(".45"), D(".15"), D(".4")))
        self.assertFalse(self.decide(bars=bars).eligible)

    def test_no_rule_uses_actual_positive_btc_move(self):
        q = quote(361000, ".40", ".41")
        self.assertTrue(self.decide(rule=NO, ctx=context("50"), q=q).eligible)
        self.assertFalse(self.decide(rule=NO, ctx=context("-50"), q=q).eligible)

    def test_missing_prior_candle_is_unknown_not_ordinal_renumber(self):
        bars = side_candles()
        del bars[1]
        decision = self.decide(bars=bars)
        self.assertTrue(decision.unknown)
        self.assertIn("missing_required_market_bar", decision.reasons)

    def test_candle_availability_guard_and_quote_age(self):
        decision = self.decide(at=MARKET.open_ms + 360999, q=quote(360999))
        self.assertTrue(decision.unknown)
        self.assertTrue(self.decide(q=quote(358999)).unknown)
        self.assertFalse(self.decide(q=quote(361000, qty=".99")).eligible)

    def test_minute10_cannot_pass_source_cutoff_after_guard(self):
        decision = self.decide(minute=10, q=quote(601000), at=MARKET.open_ms + 601000)
        self.assertEqual(decision.reasons, ("entry_cutoff",))

    def test_future_duplicate_candle_does_not_change_past_signal(self):
        bars = side_candles()
        future_revision = replace(bars[0], available_ms=MARKET.open_ms + 500000)
        self.assertEqual(
            self.decide(bars=bars), self.decide(bars=bars + [future_revision])
        )

    def test_cross_ticker_quote_rejected(self):
        self.assertTrue(self.decide(q=quote(361000, ticker="KXBTC15M-OTHER")).unknown)

    def test_incomplete_context_does_not_become_no_btc_filter(self):
        self.assertTrue(
            self.decide(
                ctx=BtcContext(True, "malformed", MARKET.open_ms + 301000)
            ).unknown
        )

    def test_missing_opposite_price_cannot_prove_noncrossed_signal(self):
        self.assertTrue(self.decide(q=replace(quote(361000), yes_bid=None)).unknown)


class FeeAndExecutionTests(unittest.TestCase):
    def test_direct_fee_has_model6dp_and_balance4dp(self):
        fee, _ = FeeAccumulator().add(D(1), D(".1234"))
        self.assertEqual(fee.model_fee, D(".007573"))
        self.assertEqual(fee.balance_debit, D(".0076"))

    def test_accumulator_shared_within_order_not_between_orders(self):
        first, accumulator = FeeAccumulator().add(D(".001"), D(".5"))
        second, accumulator = accumulator.add(D(".001"), D(".5"))
        self.assertEqual(first.balance_debit, D(".0001"))
        self.assertEqual(second.balance_debit, 0)
        independent, _ = FeeAccumulator().add(D(".001"), D(".5"))
        self.assertEqual(first.balance_debit + independent.balance_debit, D(".0002"))

    def test_fractional_fee_aligns_combined_signed_revenue(self):
        buy, _ = FeeAccumulator().add(D(".5"), D(".3333"), "buy")
        sell, _ = FeeAccumulator().add(D(".5"), D(".3333"), "sell")
        self.assertEqual(buy.model_fee, D(".007778"))
        self.assertEqual(buy.signed_balance_change, D("-.1745"))
        self.assertEqual(sell.signed_balance_change, D(".1588"))
        self.assertEqual(buy.actual_fee, D(".00785"))
        self.assertEqual(sell.actual_fee, D(".00785"))
        first, accumulator = FeeAccumulator().add(D(".5"), D(".3333"), "buy")
        second, accumulator = accumulator.add(D(".5"), D(".3333"), "buy")
        self.assertEqual(
            first.signed_balance_change + second.signed_balance_change,
            accumulator.balance_total,
        )
        self.assertEqual(accumulator.balance_total, D("-.3489"))
        first_sell, sale = FeeAccumulator().add(D(".5"), D(".3333"), "sell")
        second_sell, sale = sale.add(D(".5"), D(".3333"), "sell")
        self.assertEqual(first_sell.signed_balance_change, D(".1588"))
        self.assertEqual(second_sell.signed_balance_change, D(".1589"))
        self.assertEqual(first_sell.actual_fee + second_sell.actual_fee, D(".0156"))
        self.assertEqual(sale.balance_total, D(".3177"))
        with self.assertRaises(ValueError):
            accumulator.add(D(1), D(".5"), "sell")

    def test_delayed_entry_uses_actual_first_arrival_and_limit(self):
        quotes = [quote(361000), quote(362000, ".48", ".49")]
        attempt = delayed_attempt(
            MARKET,
            quotes,
            Side.YES,
            "buy",
            MARKET.open_ms + 361000,
            D(1),
            MARKET.close_ms - 300000,
            POLICY,
            price_band=(D(".35"), D(".50")),
        )
        self.assertEqual(attempt.status, AttemptStatus.OBSERVED_SNAPSHOT_FILL)
        self.assertEqual(attempt.price, D(".49"))
        worse = delayed_attempt(
            MARKET,
            [quotes[0], quote(362000, ".50", ".51"), quote(363000)],
            Side.YES,
            "buy",
            MARKET.open_ms + 361000,
            D(1),
            MARKET.close_ms - 300000,
            POLICY,
            price_band=(D(".35"), D(".50")),
        )
        self.assertEqual(worse.status, AttemptStatus.UNFILLED)
        self.assertEqual(worse.reason, "outside_price_band")

    def test_partial_observed_capacity_does_not_become_full_fill(self):
        attempt = delayed_attempt(
            MARKET,
            [quote(361000), quote(362000, qty=".5")],
            Side.YES,
            "buy",
            MARKET.open_ms + 361000,
            D(1),
            MARKET.close_ms - 300000,
            POLICY,
        )
        self.assertEqual(attempt.status, AttemptStatus.UNFILLED)
        self.assertEqual(attempt.simulated_count, 0)

    def test_missing_opposite_price_is_unknown_arrival(self):
        for action, arrival in (
            ("buy", replace(quote(362000), yes_bid=None)),
            ("sell", replace(quote(362000), yes_ask=None)),
        ):
            attempt = delayed_attempt(
                MARKET,
                [quote(361000), arrival],
                Side.YES,
                action,
                MARKET.open_ms + 361000,
                D(1),
                MARKET.close_ms - 300000,
                POLICY,
            )
            self.assertEqual(attempt.status, AttemptStatus.UNKNOWN)

    def test_gap_missing_quantity_and_late_arrival_stay_unknown(self):
        gap = delayed_attempt(
            MARKET,
            [quote(361000), quote(365000)],
            Side.YES,
            "buy",
            MARKET.open_ms + 361000,
            D(1),
            MARKET.close_ms - 300000,
            POLICY,
        )
        self.assertEqual(gap.status, AttemptStatus.UNKNOWN)
        self.assertIsNone(gap.simulated_count)
        missing = replace(quote(362000), yes_ask_qty=None)
        unknown = delayed_attempt(
            MARKET,
            [quote(361000), missing],
            Side.YES,
            "buy",
            MARKET.open_ms + 361000,
            D(1),
            MARKET.close_ms - 300000,
            POLICY,
        )
        self.assertEqual(unknown.status, AttemptStatus.UNKNOWN)

    def test_closed_market_never_fills_late(self):
        attempt = delayed_attempt(
            MARKET,
            [quote(899500), quote(900500)],
            Side.YES,
            "sell",
            MARKET.open_ms + 899500,
            D(1),
            MARKET.close_ms - 1,
            POLICY,
        )
        self.assertEqual(attempt.status, AttemptStatus.UNFILLED)
        self.assertEqual(attempt.reason, "outside_execution_window")

    def test_endpoint_ohlc_is_valid_but_proxy_execution_excludes_endpoint(self):
        bar = SideCandle(
            MARKET.ticker,
            Side.YES,
            MARKET.open_ms,
            MARKET.open_ms + MINUTE_MS,
            MARKET.open_ms + MINUTE_MS + 1000,
            OHLC(D(0), D(1), D(0), D(1)),
            True,
        )
        self.assertEqual(bar.ohlc.high, D(1))
        attempt = delayed_attempt(
            MARKET,
            [quote(400000, ".99", "1"), quote(401000, "1", "1")],
            Side.YES,
            "sell",
            MARKET.open_ms + 400000,
            D(1),
            MARKET.close_ms - 1,
            POLICY,
            price_band=(D(".70"), D(1)),
        )
        self.assertEqual(attempt.status, AttemptStatus.UNFILLED)
        self.assertEqual(attempt.reason, "nontradable_price")

    def test_future_duplicate_snapshot_does_not_change_prior_fill(self):
        quotes = [quote(361000), quote(362000)]
        args = (
            MARKET,
            quotes,
            Side.YES,
            "buy",
            MARKET.open_ms + 361000,
            D(1),
            MARKET.close_ms - 300000,
            POLICY,
        )
        before = delayed_attempt(*args)
        after = delayed_attempt(
            MARKET, quotes + [quote(800000), quote(800000)], *args[2:]
        )
        self.assertEqual(before, after)

    def test_find_entry_one_attempt_and_no_future_feature_access(self):
        result = find_entry(
            MARKET,
            [quote(361000), quote(362000)],
            side_candles(),
            btc_candles(),
            YES,
            POLICY,
        )
        self.assertIsNotNone(result.position)
        self.assertEqual(len(result.decisions), 1)
        failed = find_entry(
            MARKET,
            [quote(361000), quote(362000, ".50", ".51"), quote(421000), quote(422000)],
            side_candles(),
            btc_candles(),
            YES,
            POLICY,
        )
        self.assertIsNone(failed.position)
        self.assertEqual(len(failed.decisions), 1)
        self.assertFalse(failed.unknown)

    def test_unobservable_earlier_candidate_cannot_invent_later_first_signal(self):
        bars = side_candles()
        del bars[5]
        result = find_entry(
            MARKET,
            [quote(361000), quote(421000), quote(422000)],
            bars,
            btc_candles(),
            YES,
            POLICY,
        )
        self.assertTrue(result.unknown)
        self.assertIsNone(result.position)

    def test_fixed_three_second_sensitivity_recomputes_entry_cohort(self):
        quotes = [
            quote(361000),
            quote(362000),
            quote(363000),
            quote(364000, ".50", ".51"),
        ]
        fast = find_entry(
            MARKET, quotes, side_candles(), btc_candles(), YES, POLICY, delay_ms=1000
        )
        slow = find_entry(
            MARKET, quotes, side_candles(), btc_candles(), YES, POLICY, delay_ms=3000
        )
        self.assertIsNotNone(fast.position)
        self.assertIsNone(slow.position)
        assert slow.attempt is not None
        self.assertEqual(slow.attempt.status, AttemptStatus.UNFILLED)
        self.assertEqual(fast.decisions, slow.decisions)

    def test_unknown_attempt_retains_full_limit_and_fee_risk(self):
        entry = find_entry(
            MARKET, [quote(361000)], side_candles(), btc_candles(), YES, POLICY
        )
        self.assertTrue(entry.unknown)
        self.assertIsNone(entry.position)
        risk = unknown_entry_risk(entry)
        assert risk is not None
        self.assertEqual(risk.entry_limit, D(".50"))
        self.assertEqual(risk.maximum_entry_fee, D(".0175"))
        self.assertEqual(risk.lower_pnl, D("-.5175"))
        known_unfilled = find_entry(
            MARKET,
            [quote(361000), quote(362000, qty="0")],
            side_candles(),
            btc_candles(),
            YES,
            POLICY,
        )
        self.assertIsNone(unknown_entry_risk(known_unfilled))

    def test_reversed_receipt_clock_is_not_silently_sorted_into_fill(self):
        attempt = delayed_attempt(
            MARKET,
            [quote(362000), quote(361000)],
            Side.YES,
            "buy",
            MARKET.open_ms + 361000,
            D(1),
            MARKET.close_ms - 300000,
            POLICY,
        )
        self.assertEqual(attempt.status, AttemptStatus.UNKNOWN)
        self.assertEqual(attempt.reason, "reversed_receipt_clock")


class ExitAndSettlementTests(unittest.TestCase):
    def label(self, side=Side.YES):
        return Settlement(MARKET.ticker, side, MARKET.close_ms + 5000, True)

    def test_missed_target_becomes_official_full_loss(self):
        exits = find_exit(
            position(), MARKET, [quote(500000, ".40", ".41")], D(".70"), POLICY
        )
        result = score_trade(exits, MARKET, self.label(Side.NO), MARKET.close_ms + 5000)
        self.assertTrue(result.known)
        self.assertEqual(result.net_pnl, D("-.5175"))
        self.assertEqual(result.total_fees, D(".0175"))
        self.assertGreater(exits.holding_gap_count, 0)

    def test_missing_or_cross_ticker_settlement_stays_unknown_bounds(self):
        result = settle(position(), MARKET, None, MARKET.close_ms + 5000)
        self.assertFalse(result.known)
        self.assertEqual(
            (result.lower_pnl, result.upper_pnl), (D("-.5175"), D(".4825"))
        )
        wrong = replace(self.label(), ticker="KXBTC15M-OTHER")
        self.assertFalse(
            settle(position(), MARKET, wrong, MARKET.close_ms + 5000).known
        )

    def test_exit_target_vanishes_then_retries_with_actual_higher_bid(self):
        quotes = [
            quote(362000),
            quote(400000, ".70", ".71"),
            quote(401000, ".69", ".70"),
            quote(402000, ".72", ".73"),
            quote(403000, ".73", ".74"),
        ]
        exits = find_exit(position(), MARKET, quotes, D(".70"), POLICY)
        self.assertEqual(len(exits.attempts), 2)
        assert exits.filled is not None
        self.assertEqual(exits.filled.price, D(".73"))
        result = score_trade(exits, MARKET, None, MARKET.close_ms + 5000)
        self.assertEqual(result.net_pnl, D(".1987"))

    def test_unknown_exit_is_not_booked_as_winning_hold(self):
        quotes = [
            quote(362000),
            quote(400000, ".70", ".71"),
            quote(410000, ".80", ".81"),
        ]
        exits = find_exit(position(), MARKET, quotes, D(".70"), POLICY)
        self.assertTrue(exits.unknown)
        result = score_trade(exits, MARKET, self.label(), MARKET.close_ms + 5000)
        self.assertFalse(result.known)
        self.assertEqual(result.reason, "unobservable_exit_arrival")
        self.assertEqual(
            (result.lower_pnl, result.upper_pnl), (D("-.5175"), D(".4825"))
        )
        hold = score_trade(
            hold_control(position()), MARKET, self.label(), MARKET.close_ms + 5000
        )
        self.assertTrue(hold.known)
        self.assertEqual(hold.net_pnl, D(".4825"))

    def test_other_ticker_cannot_trigger_exit(self):
        exits = find_exit(
            position(),
            MARKET,
            [quote(400000, ".90", ".91", ticker="KXBTC15M-OTHER")],
            D(".70"),
            POLICY,
        )
        self.assertFalse(exits.attempts)

    def test_future_quote_changes_do_not_change_completed_exit_or_gap_count(self):
        quotes = [
            quote(362000),
            quote(400000, ".70", ".71"),
            quote(401000, ".71", ".72"),
        ]
        exits = find_exit(position(), MARKET, quotes, D(".70"), POLICY)
        later = find_exit(
            position(), MARKET, quotes + [quote(850000)], D(".70"), POLICY
        )
        self.assertEqual(exits, later)


class AdapterTests(unittest.TestCase):
    def test_explicit_price_units_and_missing_qty(self):
        q = quote_from_row(
            {
                "ts_ms": "1000",
                "ticker": MARKET.ticker,
                "yes_bid": "49",
                "yes_ask": "50",
            },
            price_unit="cents",
        )
        self.assertEqual(q.yes_ask, D(".50"))
        self.assertIsNone(q.yes_ask_qty)
        with self.assertRaises(ValueError):
            quote_from_row({"ts_ms": "1", "ticker": MARKET.ticker}, price_unit="guess")

    def test_float_nan_crossed_or_invalid_ohlc(self):
        with self.assertRaises(ValueError):
            # Deliberately invalid typed input verifies runtime float rejection.
            OHLC(0.5, D(1), D(0), D(".5"))  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            OHLC(D(1), D("NaN"), D(0), D(1))
        with self.assertRaises(ValueError):
            OHLC(D(".5"), D(".4"), D(".3"), D(".5"))
        self.assertTrue(quote(361000, ".6", ".5").crossed(Side.YES))


if __name__ == "__main__":
    unittest.main()
