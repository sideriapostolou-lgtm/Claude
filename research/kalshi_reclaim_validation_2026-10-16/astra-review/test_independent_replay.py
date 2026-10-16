"""Independent synthetic review only; no data files or network access."""

import os
import sys
import unittest
from dataclasses import replace
from decimal import Decimal as D
from decimal import localcontext
from types import SimpleNamespace

sys.path.insert(
    0,
    os.environ.get(
        "REPLAY_REVIEW_MODULE_DIR",
        os.path.join(os.path.dirname(__file__), "../sol-replay"),
    ),
)
from replay import (
    MINUTE_MS,
    OHLC,
    WINDOW_MS,
    AttemptStatus,
    ClosedCandle,
    FeeAccumulator,
    Market,
    Position,
    QualityPolicy,
    Quote,
    Settlement,
    Side,
    btc_context,
    delayed_attempt,
    find_exit,
    hold_control,
    score_trade,
    unknown_entry_risk,
)

P = QualityPolicy(1000, 1000, 1500, 60, 2000, 2000, 3000, 32, True)
M = Market("KXBTC15M-SYNTHETIC", 96 * WINDOW_MS, 97 * WINDOW_MS, D(10000))


def q(ms, bid=".49", ask=".50"):
    b, a = D(bid), D(ask)
    return Quote(M.open_ms + ms, M.ticker, b, a, D(5), D(5), 1 - a, 1 - b, D(5), D(5))


def attempt(rows, action="buy", trigger=361000):
    return delayed_attempt(
        M,
        rows,
        Side.YES,
        action,
        M.open_ms + trigger,
        D(1),
        M.close_ms - 300000 if action == "buy" else M.close_ms - 1,
        P,
        price_band=(D(".35"), D(".55")) if action == "buy" else (D(".70"), D(1)),
    )


class IndependentChecks(unittest.TestCase):
    def test_missing_opposite_price_does_not_certify_noncrossed_entry(self):
        out = attempt([q(361000), replace(q(362000), yes_bid=None)])
        self.assertNotEqual(out.status, AttemptStatus.OBSERVED_SNAPSHOT_FILL)

    def test_missing_opposite_price_does_not_certify_noncrossed_exit(self):
        out = attempt(
            [q(400000, ".70", ".71"), replace(q(401000, ".70", ".71"), yes_ask=None)],
            "sell",
            400000,
        )
        self.assertNotEqual(out.status, AttemptStatus.OBSERVED_SNAPSHOT_FILL)

    def test_reversed_receive_clock_is_not_silently_sorted_into_fill(self):
        out = attempt([q(362000), q(361000)])
        self.assertNotEqual(out.status, AttemptStatus.OBSERVED_SNAPSHOT_FILL)

    def test_ema_nonconstant_exact32_seed_and_midnight(self):
        start = M.open_ms - 32 * WINDOW_MS
        candles = []
        expected = D(10000)
        with localcontext() as ctx:
            ctx.prec = 50
            alpha = D(1) / D(11)
            for k in range(32):
                price = D(10000 + k * 10)
                if k:
                    expected = alpha * price + (1 - alpha) * expected
                for j in range(15):
                    t = start + (k * 15 + j) * MINUTE_MS
                    candles.append(
                        ClosedCandle(
                            "BTC-USD",
                            t,
                            t + MINUTE_MS,
                            t + MINUTE_MS + 1000,
                            OHLC(price, price, price, price),
                            True,
                        )
                    )
        for j in range(5):
            t = M.open_ms + j * MINUTE_MS
            candles.append(
                ClosedCandle(
                    "BTC-USD",
                    t,
                    t + MINUTE_MS,
                    t + MINUTE_MS + 1000,
                    OHLC(D(10000), D(10025), D(10000), D(10025)),
                    True,
                )
            )
        out = btc_context(M, candles, M.open_ms + 301000, P)
        self.assertTrue(out.available)
        self.assertEqual(out.ema21, expected)
        self.assertEqual(out.first_five_return, D(25))
        self.assertEqual(M.open_ms % (24 * 60 * MINUTE_MS), 0)

    def test_full_loss_uses_entry_debit_once(self):
        fee = FeeAccumulator().add(D(1), D(".1234"))[0].balance_debit
        pos = Position(M.ticker, Side.YES, D(1), D(".1234"), fee, M.open_ms + 362000)
        result = score_trade(
            hold_control(pos),
            M,
            Settlement(M.ticker, Side.NO, M.close_ms + 1, True),
            M.close_ms + 1,
        )
        self.assertEqual(result.net_pnl, D("-.1310"))

    def test_fractional_buy_rounds_signed_debit_and_second_fill_refunds_excess(self):
        first, acc = FeeAccumulator().add(D(".5"), D(".3333"), "buy")
        second, acc = acc.add(D(".5"), D(".3333"), "buy")
        self.assertEqual(first.signed_balance_change, D("-.1745"))
        self.assertEqual(first.actual_fee, D(".00785"))
        self.assertEqual(second.signed_balance_change, D("-.1744"))
        self.assertEqual(second.actual_fee, D(".00775"))
        self.assertEqual(
            first.signed_balance_change + second.signed_balance_change, D("-.3489")
        )

    def test_fractional_sale_rounds_credit_down_not_only_fee_up(self):
        first, acc = FeeAccumulator().add(D(".5"), D(".3333"), "sell")
        second, acc = acc.add(D(".5"), D(".3333"), "sell")
        self.assertEqual(first.signed_balance_change, D(".1588"))
        self.assertEqual(second.signed_balance_change, D(".1589"))
        self.assertEqual(first.actual_fee + second.actual_fee, D(".01560"))

    def test_postclose_only_quote_cannot_fill(self):
        out = attempt([q(361000), q(900000)])
        self.assertEqual(out.status, AttemptStatus.UNKNOWN)

    def test_declared_proxy_rejects_endpoint_execution_but_ohlc_allows_one(self):
        candle = OHLC(D(1), D(1), D(1), D(1))
        self.assertEqual(candle.close, D(1))
        out = attempt([q(400000, ".70", ".71"), q(401000, "1", "1")], "sell", 400000)
        self.assertEqual(out.status, AttemptStatus.UNFILLED)
        self.assertEqual(out.reason, "nontradable_price")

    def test_first_arrival_bad_size_not_replaced_with_later_good(self):
        out = attempt([q(361000), replace(q(362000), yes_ask_qty=D(0)), q(363000)])
        self.assertEqual(out.status, AttemptStatus.UNFILLED)
        self.assertEqual(out.observed_ms, M.open_ms + 362000)

    def test_unknown_entry_retains_full_limit_and_fee_loss(self):
        missing = attempt([q(361000)])
        self.assertEqual(missing.status, AttemptStatus.UNKNOWN)
        risk = unknown_entry_risk(
            SimpleNamespace(attempt=missing, entry_limit=D(".55"))
        )
        self.assertEqual(risk.maximum_entry_fee, D(".0174"))
        self.assertEqual(risk.lower_pnl, D("-.5674"))
        self.assertIsNone(unknown_entry_risk(SimpleNamespace(attempt=None)))

    def test_unknown_exit_stays_unknown_even_with_winning_official_label(self):
        pos = Position(
            M.ticker, Side.YES, D(1), D(".50"), D(".0175"), M.open_ms + 362000
        )
        out = find_exit(
            pos, M, [q(400000, ".70", ".71"), q(410000, ".80", ".81")], D(".70"), P
        )
        score = score_trade(
            out, M, Settlement(M.ticker, Side.YES, M.close_ms + 1, True), M.close_ms + 1
        )
        self.assertFalse(score.known)
        self.assertEqual((score.lower_pnl, score.upper_pnl), (D("-.5175"), D(".4825")))


if __name__ == "__main__":
    unittest.main()
