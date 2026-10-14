"""The exact LIP score (nightcrawler.lip_score): the filing's rules, the help center's example, and the rewards
playbook's worked example (research/kalshi_rewards/PLAYBOOK.md section 1: $1.90)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction as F

import pytest

from nightcrawler import lip_score as L

YES, NO, US, OT = L.YES, L.NO, L.US, L.OTHERS


def bids(side: str, levels: list[tuple[str, object]], owner: str = OT) -> list[L.Bid]:
    return [L.Bid(side, price, size, owner) for price, size in levels]


def snap_with(us_yes: object = 0, us_no: object = 0, valid: bool = True) -> L.SnapshotResult:
    if not valid:
        return L.SnapshotResult(False, "excluded", None, None, {})
    mine = F(str(us_yes)) + F(str(us_no))
    return L.SnapshotResult(True, "", None, None, {US: mine, OT: 2 - mine})


# ---------------------------------------------------------------------- the playbook's worked example
def worked_example_book(yes_price: str = "0.40") -> list[L.Bid]:
    """EUR/USD: YES bids 41c 30, 40c 90 + our 10, 39c 250; NO bids 57c 70 + our 10, 56c 300."""
    return (bids(YES, [("0.41", 30), ("0.40", 90), ("0.39", 250)]) + bids(NO, [("0.57", 70), ("0.56", 300)])
            + [L.Bid(YES, yes_price, 10, US), L.Bid(NO, "0.57", 10, US)])


def test_worked_example_pays_190_on_a_50_dollar_fx_pool() -> None:
    snap = L.score_snapshot(worked_example_book(), 300, "0.5")
    assert snap.valid and snap.yes is not None and snap.no is not None
    assert snap.yes.reference_price == F(40, 100) and snap.no.reference_price == F(57, 100)
    assert snap.yes.raw[US] + snap.yes.raw[OT] == 255 and snap.no.raw[US] + snap.no.raw[OT] == 230
    assert snap.yes.normalized[US] == F(10, 255) and snap.no.normalized[US] == F(10, 230)
    score = snap.score(US)
    assert round(float(score), 4) == 0.0827
    # 828 of 900 seconds two-sided and like this one (92 %, typical for FX).
    raw = L.payout_shortcut([score] * 828, 50, 900)
    assert L.paid_amount(raw) == Decimal("1.90")
    period = L.period_payout([snap] * 828 + [snap_with(valid=False)] * 72, 50)
    assert period.paid == Decimal("1.90") and period.valid_snapshots == 828


def test_worked_example_copper_pool_pays_nothing_and_one_tick_below_pays_less() -> None:
    score = L.score_snapshot(worked_example_book(), 300, "0.5").score(US)
    copper = L.payout_shortcut([score] * 828, 20, 900)
    assert round(float(copper), 2) == 0.76 and L.paid_amount(copper) == Decimal("0.00")
    lower = L.score_snapshot(worked_example_book("0.39"), 300, "0.5")
    assert lower.yes is not None and round(float(lower.yes.normalized[US]), 3) == 0.020
    assert L.paid_amount(L.payout_shortcut([lower.score(US)] * 828, 50, 900)) == Decimal("1.46")
    assert 10 * F(40, 100) + 10 * F(57, 100) == F(97, 10)  # the cash the pair ties up: $9.70


def test_floor_cent_is_exact_at_a_cent_boundary() -> None:
    """The research copy floored a 28-digit decimal approximation, so a payout a hair under $2.00 became $2.00."""
    just_under = F(2) - F(1, 10 ** 40)
    assert L.floor_cent(just_under) == Decimal("1.99")
    assert L.floor_cent(F(2)) == Decimal("2.00")
    assert L.paid_amount(F(1) - F(1, 10 ** 40)) == Decimal("0.00")


# ---------------------------------------------------------------------- the help center's example
def test_help_center_16_dollars() -> None:
    result = L.payout_from_tp_score("0.20", 100, valid_snapshots=8000, total_snapshots=10000)
    assert result.raw_payout == 16 and result.paid == Decimal("16.00")
    snaps = [snap_with("0.2", "0.2") for _ in range(8000)] + [snap_with(valid=False) for _ in range(2000)]
    period = L.period_payout(snaps, 100)
    assert period.tp_score == F(1, 5) and period.valid_snapshots == 8000 and period.paid == Decimal("16.00")
    assert L.payout_shortcut([snap.score(US) for snap in snaps], 100, 10000) == 16
    assert L.period_payout(snaps[:8000], 100, total_snapshots=10000).paid == Decimal("16.00")


# ---------------------------------------------------------------------- the Reference price and the walk
def test_small_top_order_does_not_set_the_reference() -> None:
    side = L.score_side(bids(YES, [("0.55", 5), ("0.54", 100), ("0.53", 300)]), YES, 300, "0.5")
    assert side.qualified and side.reference_price == F(54, 100)
    assert [(level[0], level[2]) for level in side.levels] == [(F(55, 100), 0), (F(54, 100), 0), (F(53, 100), 1)]
    assert side.raw[OT] == 5 + 100 + F(1, 2) * 300


@pytest.mark.parametrize(("top", "reference"), [("60", F(1, 2)), ("59.99", F(49, 100))])
def test_reference_is_where_a_fifth_of_the_target_is_reached(top: str, reference: F) -> None:
    side = L.score_side(bids(YES, [("0.50", top), ("0.49", 300)]), YES, 300, "0.5")
    assert side.reference_price == reference


def test_coin_race_target_1000() -> None:
    side = L.score_side(bids(NO, [("0.80", 150), ("0.79", 60), ("0.70", 900)]), NO, 1000, "0.5")
    assert side.reference_price == F(79, 100) and [level[2] for level in side.levels] == [0, 0, 9]


def test_last_level_counts_whole_and_deeper_levels_never() -> None:
    side = L.score_side(bids(YES, [("0.50", 250), ("0.49", 200), ("0.48", 1000)]), YES, 300, "0.5")
    assert side.qualifying_total == 450 and [level[0] for level in side.levels] == [F(1, 2), F(49, 100)]
    snap = L.score_snapshot(bids(YES, [("0.50", 300)]) + [L.Bid(YES, "0.49", 10, US)] + bids(NO, [("0.45", 300)]),
                            300, "0.5")
    assert snap.valid and snap.score(US) == 0


def test_a_side_short_of_the_target_excludes_the_snapshot() -> None:
    assert not L.score_side(bids(YES, [("0.50", 100), ("0.40", 199)]), YES, 300, "0.5").qualified
    assert not L.score_side([], NO, 300, "0.5").qualified
    book = bids(YES, [("0.50", 1000)]) + bids(NO, [("0.45", 299)]) + [L.Bid(YES, "0.50", 10, US)]
    snap = L.score_snapshot(book, 300, "0.5")
    assert not snap.valid and snap.score(US) == 0 and "not two-sided" in snap.reason


def test_our_size_can_complete_a_side() -> None:
    book = bids(YES, [("0.50", 400)]) + bids(NO, [("0.45", 290)])
    assert not L.score_snapshot(book, 300, "0.5").valid
    snap = L.score_snapshot(book + [L.Bid(NO, "0.45", 10, US)], 300, "0.5")
    assert snap.valid and snap.score(US) == F(10, 300)


def test_closed_market_crossed_book_and_sums() -> None:
    book = bids(YES, [("0.50", 400)]) + bids(NO, [("0.45", 400)])
    assert not L.score_snapshot(book, 300, "0.5", market_open=False).valid
    assert not L.is_crossed(book)
    with pytest.raises(ValueError):
        L.score_snapshot(book + [L.Bid(YES, "0.55", 10, US)], 300, "0.5")
    rich = (bids(YES, [("0.52", 20), ("0.51", 80), ("0.50", 300)]) + bids(NO, [("0.46", 70), ("0.44", 500)])
            + [L.Bid(YES, "0.52", 10, US), L.Bid(NO, "0.46", 10, US), L.Bid(NO, "0.44", 5, "u2")])
    assert sum(L.score_snapshot(rich, 300, "0.5").scores.values()) == 2
    sole = L.score_snapshot([L.Bid(YES, "0.50", 300, US), L.Bid(NO, "0.45", 300, US)], 300, "0.5")
    assert sole.score(US) == 2


def test_join_best_bid_and_discount_factor_one() -> None:
    book = bids(YES, [("0.50", 100), ("0.49", 300)]) + bids(NO, [("0.47", 100), ("0.46", 300)])
    snap = L.score_snapshot(book + [L.Bid(YES, "0.50", 10, US), L.Bid(NO, "0.47", 10, US)], 300, "0.5")
    assert snap.score(US) == 2 * F(10, 260)
    assert L.period_payout([snap] * 900, 50).paid == Decimal("1.92")
    flat = bids(YES, [("0.50", 100), ("0.30", 300)]) + bids(NO, [("0.45", 300)]) + [L.Bid(YES, "0.30", 100, US)]
    flat_snap = L.score_snapshot(flat, 300, 1)
    assert flat_snap.yes is not None and flat_snap.yes.normalized[US] == F(100, 500)


def test_asks_count_as_bids_and_fractional_sizes() -> None:
    no_bid = L.yes_ask_as_no_bid("0.53", 10)
    assert (no_bid.side, no_bid.price, no_bid.size) == (NO, F(47, 100), 10)
    assert L.no_ask_as_yes_bid("0.60", 5).price == F(2, 5)
    book = bids(YES, [("0.50", "299.99")]) + bids(NO, [("0.45", 300)])
    assert not L.score_snapshot(book, 300, "0.5").valid
    assert L.score_snapshot(book + [L.Bid(YES, "0.50", "0.01", US)], 300, "0.5").valid


def test_live_book_merge_subtracts_our_own_orders() -> None:
    public = L.bids_from_orderbook({"orderbook_fp": {"yes_dollars": [["0.4900", "300.00"], ["0.5000", "100.00"]],
                                                     "no_dollars": [["0.4700", "310.00"]]}})
    merged = L.combine_book(public, [L.Bid(YES, "0.50", 10, US), L.Bid(NO, "0.47", 10, US)], ours_in_book=True)
    snap = L.score_snapshot(merged, 300, "0.5")
    assert snap.yes is not None and snap.no is not None
    assert snap.yes.normalized[US] == F(10, 250) and snap.no.normalized[US] == F(10, 310)
    with pytest.raises(ValueError):
        L.combine_book(L.bids_from_orderbook({"yes_dollars": [["0.50", "5"]], "no_dollars": []}),
                       [L.Bid(YES, "0.50", 10, US)], ours_in_book=True)


def test_grids() -> None:
    assert L.LINEAR_CENT.ticks_between("0.50", "0.53") == 3
    tapered = L.Grid.from_price_ranges([{"start": "0", "end": "0.1", "step": "0.001"},
                                        {"start": "0.1", "end": "0.9", "step": "0.01"},
                                        {"start": "0.9", "end": "1", "step": "0.001"}])
    assert tapered.ticks_between("0.095", "0.12") == 7 and tapered.ticks_between("0.89", "0.905") == 6
    with pytest.raises(ValueError):
        tapered.ticks_between("0.105", "0.12")


def test_period_rules() -> None:
    assert L.period_payout([snap_with("0.5", "0"), snap_with("0.1", "0")], 50).tp_score == F(6, 10) / 4
    assert L.payout_from_tp_score(F(999, 50000), 50, 900, 900).paid == Decimal("0.00")
    assert L.payout_from_tp_score(F(1, 50), 50, 900, 900).paid == Decimal("1.00")
    assert L.payout_from_tp_score(F(1239, 50000), 50, 900, 900).paid == Decimal("1.23")
    half = L.period_payout([snap_with(1, 1)] * 450 + [snap_with(valid=False)] * 450, 50)
    assert half.tp_score == 1 and half.paid == Decimal("25.00")
    assert L.period_payout([snap_with(valid=False)] * 900, 50).paid == Decimal("0.00")
    with pytest.raises(ValueError):
        L.payout_from_tp_score("0.1", 50, 901, 900)


def test_program_rows() -> None:
    row = {"discount_factor_bps": 5000, "end_date": "2026-10-13T19:15:00Z", "id": "x",
           "incentive_description": "series_lip", "incentive_type": "liquidity", "market_id": "m",
           "market_ticker": "KXEURUSD15M-26OCT131515-30", "paid_out": False, "period_reward": 500000,
           "start_date": "2026-10-13T19:00:00Z", "target_size_fp": "300.00"}
    program = L.program_from_api(row)
    assert (program.reward, program.discount_factor, program.target, program.snapshots) == (50, F(1, 2), 300, 900)
    assert program.start == datetime(2026, 10, 13, 19, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        L.program_from_api({**row, "incentive_type": "volume"})
    with pytest.raises(TypeError):
        L.frac(True)
