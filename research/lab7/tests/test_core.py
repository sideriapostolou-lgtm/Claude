"""Tests for research/lab7/core.py on hand-made tapes: every execution convention of PLAN §4 is proven here before
any return is read. Buyable / sellable sides (a buy never fills at a sell print, a sell never at a buy print), the
10 s latency and the 600 s entry window, the resting take profit (no fill at exactly the limit, trade-through and
size, cancelled at the stop), the stop's real slippage (the next sellable print, not the trigger price), the fair
cap, the three time-stop modes, settlement, fees on both legs under the three schemes, one position per market and
re-entry only after the exit, signals that never read the future, the random-entry placebo, the risk book, the bar
and selection, the TEST guard and the trial ledger."""

import json
import math
from itertools import pairwise

import core as C
import numpy as np
import pandas as pd
import pytest

T0 = 1_785_000_000.0  # 2026-07-25 17:20 UTC, inside lab 4's TRAIN split
END = T0 + 10_000


def market(tape, **kw):
    args = {
        "id": "m1",
        "event": "e1",
        "split": "train",
        "tape": tape,
        "rate_com": 0.05,
        "payout": (1.0, 0.0),
        "settle_t": END + 100,
        "hard_end": END,
        "entry_windows": ((T0 - 10**6, END),),
        "entry_deadline": END,
        "end_t": END,
        "end_mode": "settle",
    }
    if "end_t" in kw and "entry_deadline" not in kw:
        kw["entry_deadline"] = min(END, kw["end_t"])  # a deadline never after the market's own time stop
    args.update(kw)
    return C.Market(**args)


def tape(*rows):
    return C.Tape.from_prints(rows)


# --- sides ---------------------------------------------------------------------------------------------------------


def test_every_print_is_buyable_for_one_outcome_and_sellable_for_the_other():
    t = tape(
        (T0, 0, "BUY", 0.50, 10),  # buyable 0 at .50
        (T0 + 1, 1, "SELL", 0.47, 10),  # a taker sold token 1 at .47: buyable 0 at .53
        (T0 + 2, 0, "SELL", 0.49, 10),  # a taker hit the bid of 0 at .49: sellable 0
        (T0 + 3, 1, "BUY", 0.52, 10),  # a taker bought token 1 at .52: sellable 0 at .48
    )
    assert t.buyable(0).tolist() == [True, True, False, False]
    assert (t.buyable(0) == t.sellable(1)).all() and (t.buyable(1) == t.sellable(0)).all()
    assert t.price(0) == pytest.approx([0.50, 0.53, 0.49, 0.48])
    assert t.price(1) == pytest.approx([0.50, 0.47, 0.51, 0.52])


def test_a_buy_cannot_fill_at_a_sell_print():
    t = tape(
        (T0, 0, "BUY", 0.50, 50),
        (T0 + 12, 0, "SELL", 0.49, 50),  # bid-side for 0
        (T0 + 15, 1, "BUY", 0.52, 50),  # bid-side for 0 (0 at .48)
        (T0 + 20, 1, "SELL", 0.49, 50),  # buyable 0 at .51
    )
    i = C.taker_buy_index(t, 0, T0, END)
    assert i == 3 and t.price(0)[i] == pytest.approx(0.51)
    only_bids = tape((T0, 0, "BUY", 0.5, 5), (T0 + 30, 0, "SELL", 0.49, 50), (T0 + 40, 1, "BUY", 0.52, 50))
    assert C.taker_buy_index(only_bids, 0, T0, END) is None  # missed: nobody sold to a buyer
    rt = C.simulate(market(only_bids), 0, T0, C.Exits(tp=0.05))
    assert rt is None


def test_a_sell_cannot_fill_at_a_buy_print():
    t = tape((T0 + 20, 0, "BUY", 0.60, 50), (T0 + 25, 1, "SELL", 0.38, 50), (T0 + 30, 0, "SELL", 0.57, 50))
    assert C.taker_sell_index(t, 0, T0, END) == 2  # the two ask-side prints are skipped
    assert t.price(0)[2] == pytest.approx(0.57)
    assert C.taker_sell_index(tape((T0 + 20, 0, "BUY", 0.6, 50)), 0, T0, END) is None


def test_latency_and_entry_window():
    t = tape((T0 + 9, 0, "BUY", 0.40, 50), (T0 + 10, 0, "BUY", 0.41, 50))
    assert C.taker_buy_index(t, 0, T0, END) == 1  # 9 s is too early, 10 s is the first allowed print
    late = tape((T0 + 601, 0, "BUY", 0.40, 50))
    assert C.taker_buy_index(late, 0, T0, END) is None  # beyond the 600 s window: missed
    assert C.taker_buy_index(t, 0, T0, deadline=T0 + 10) is None  # the deadline is exclusive


# --- take profit, stop loss, fair cap --------------------------------------------------------------------------


def _entry_at_50():
    return [(T0, 0, "BUY", 0.50, 50), (T0 + 10, 0, "BUY", 0.50, 50)]  # signal print, then the entry fill at .50


def test_resting_take_profit_does_not_fill_at_exactly_the_limit():
    rows = _entry_at_50() + [
        (T0 + 30, 0, "BUY", 0.55, 1000),  # exactly the limit: never fills a resting order
        (T0 + 35, 0, "SELL", 0.60, 1000),  # a taker SOLD at .60 (bid-side): cannot fill a resting SELL
    ]
    ex = C.Exits(tp=0.05, tp_mode="maker")
    rt = C.simulate(market(tape(*rows)), 0, T0, ex)
    assert rt["exit_leg"] == "settle" and rt["reason"] == "settle"
    rows.append((T0 + 40, 0, "BUY", 0.56, 100))  # a trade-through: fills, at the limit
    rt = C.simulate(market(tape(*rows)), 0, T0, ex)
    assert rt["exit_leg"] == "maker" and rt["reason"] == "tp"
    assert rt["p_exit"] == pytest.approx(0.55) and rt["t_exit"] == T0 + 40


def test_resting_take_profit_needs_the_size_and_is_cancelled_at_the_stop():
    rows = _entry_at_50() + [(T0 + 30, 0, "BUY", 0.57, 10)]  # through the limit but 10 < 40 shares
    ex = C.Exits(tp=0.05, sl=0.05, tp_mode="maker")
    assert C.simulate(market(tape(*rows)), 0, T0, ex)["exit_leg"] == "settle"
    rows += [(T0 + 31, 0, "BUY", 0.56, 30)]  # cumulative 40 at or above .55: filled on this print
    rt = C.simulate(market(tape(*rows)), 0, T0, ex)
    assert rt["exit_leg"] == "maker" and rt["t_exit"] == T0 + 31
    stopped = _entry_at_50() + [
        (T0 + 30, 0, "SELL", 0.44, 50),  # stop trigger (.45): the resting order is cancelled here
        (T0 + 41, 0, "SELL", 0.43, 50),  # the stop's sell
        (T0 + 50, 0, "BUY", 0.60, 500),  # a later trade-through cannot fill the cancelled order
    ]
    rt = C.simulate(market(tape(*stopped)), 0, T0, ex)
    assert rt["reason"] == "sl" and rt["exit_leg"] == "taker" and rt["p_exit"] == pytest.approx(0.43)


def test_stop_exits_at_the_next_sellable_print_not_the_trigger_price():
    rows = _entry_at_50() + [
        (T0 + 30, 0, "SELL", 0.44, 50),  # trigger: at or below .45
        (T0 + 35, 0, "SELL", 0.43, 50),  # sellable but before trigger + 10 s
        (T0 + 41, 0, "BUY", 0.46, 50),  # buyable: not a bid
        (T0 + 45, 1, "BUY", 0.60, 50),  # sellable for 0 at .40: the fill
    ]
    rt = C.simulate(market(tape(*rows)), 0, T0, C.Exits(tp=0.05, sl=0.05))
    assert rt["reason"] == "sl" and rt["t_trigger"] == T0 + 30
    assert rt["t_exit"] == T0 + 45 and rt["p_exit"] == pytest.approx(0.40)
    assert rt["pnl_us"] < 40 * (0.45 - 0.50)  # the slippage below the stop level is real


def test_a_stop_that_never_finds_a_bid_is_held_to_settlement():
    rows = _entry_at_50() + [(T0 + 30, 0, "BUY", 0.40, 50)]  # trigger on an ask-side print; no bid afterwards
    rt = C.simulate(market(tape(*rows), payout=(0.0, 1.0)), 0, T0, C.Exits(sl=0.05))
    assert rt["reason"] == "sl->settle" and rt["exit_leg"] == "settle" and rt["p_exit"] == 0.0


def test_taker_take_profit_and_the_fair_cap():
    rows = _entry_at_50() + [
        (T0 + 30, 0, "BUY", 0.53, 50),  # reaches the fair (.53) but not entry + tp (.55)
        (T0 + 45, 0, "SELL", 0.52, 50),
    ]
    t = tape(*rows)
    fair = np.full((2, len(t)), np.nan)
    fair[0, :] = 0.53
    fair[1, :] = 0.47
    rt = C.simulate(market(t, fair=fair), 0, T0, C.Exits(tp=0.05, fair_exit=True))
    assert rt["reason"] == "fair" and rt["t_trigger"] == T0 + 30 and rt["p_exit"] == pytest.approx(0.52)
    rt = C.simulate(market(t, fair=fair), 0, T0, C.Exits(tp=0.05))  # no fair cap: .53 is not a take profit
    assert rt["reason"] == "settle"
    fair[0, :] = 0.49  # a fair at or below the entry is not a target
    rt = C.simulate(market(t, fair=fair), 0, T0, C.Exits(tp=0.05, fair_exit=True))
    assert rt["reason"] == "settle"
    rows.append((T0 + 60, 0, "BUY", 0.55, 50))
    rows.append((T0 + 75, 0, "SELL", 0.54, 50))
    rt = C.simulate(market(tape(*rows)), 0, T0, C.Exits(tp=0.05))
    assert rt["reason"] == "tp" and rt["t_trigger"] == T0 + 60 and rt["p_exit"] == pytest.approx(0.54)


def test_a_print_in_the_entry_second_is_never_a_trigger():
    rows = _entry_at_50() + [(T0 + 10, 0, "SELL", 0.40, 50), (T0 + 30, 0, "SELL", 0.49, 50)]
    rt = C.simulate(market(tape(*rows), payout=(1.0, 0.0)), 0, T0, C.Exits(sl=0.05))
    assert rt["reason"] == "settle"  # the .40 print shares the fill's second: we could not have reacted to it


# --- time stops and settlement ---------------------------------------------------------------------------------


def test_time_stop_next_last_before_and_settle():
    base = _entry_at_50() + [(T0 + 500, 0, "SELL", 0.48, 50), (T0 + 915, 0, "SELL", 0.47, 50),
                             (T0 + 925, 0, "SELL", 0.46, 50), (T0 + 990, 0, "SELL", 0.45, 50),
                             (T0 + 1005, 0, "SELL", 0.30, 50)]
    t = tape(*base)
    rt = C.simulate(market(t), 0, T0, C.Exits(hold_s=900))  # stop at 910, sell at >= 920
    assert rt["reason"] == "time" and rt["t_exit"] == T0 + 925 and rt["p_exit"] == pytest.approx(0.46)
    mk = market(t, end_t=T0 + 1000, end_mode="last_before")
    rt = C.simulate(mk, 0, T0, C.Exits())
    assert rt["reason"] == "time" and rt["t_exit"] == T0 + 990 and not rt["late_stop"]
    early_only = tape(*_entry_at_50(), (T0 + 15, 0, "SELL", 0.49, 50), (T0 + 1012, 0, "SELL", 0.30, 50))
    rt = C.simulate(market(early_only, end_t=T0 + 1000, end_mode="last_before"), 0, T0, C.Exits())
    assert rt["late_stop"] and rt["t_exit"] == T0 + 1012  # the only earlier bid predates entry + 10 s
    rt = C.simulate(market(t, end_t=T0 + 1000, end_mode="next", payout=(0.0, 1.0)), 0, T0, C.Exits())
    assert rt["reason"] == "time->settle" and rt["p_exit"] == 0.0  # 1005 < stop + 10 s: no bid in time
    t2 = tape(*base, (T0 + 1015, 0, "SELL", 0.29, 50))
    rt = C.simulate(market(t2, end_t=T0 + 1000, end_mode="next"), 0, T0, C.Exits())
    assert rt["reason"] == "time" and rt["t_exit"] == T0 + 1015 and rt["p_exit"] == pytest.approx(0.29)
    rt = C.simulate(market(t, end_t=T0 + 1000, end_mode="settle", payout=(1.0, 0.0)), 0, T0, C.Exits())
    assert rt["reason"] == "settle" and rt["p_exit"] == 1.0 and rt["t_exit"] == END + 100
    assert rt["fee_us"] == pytest.approx(40 * C.US_RATE * 0.25)  # settlement: the entry leg's fee only


def test_market_refuses_an_entry_deadline_after_its_time_stop():
    with pytest.raises(ValueError):
        market(tape(*_entry_at_50()), entry_deadline=END, end_t=END - 1)
    with pytest.raises(ValueError):
        market(tape(*_entry_at_50()), end_mode="later")
    mk = market(tape(*_entry_at_50()), entry_windows=((T0, END + 500), (END + 600, END + 700)))
    assert mk.entry_windows == ((T0, END),)  # windows are clipped to the entry deadline


def test_hold_to_settlement_reference():
    rows = _entry_at_50() + [(T0 + 30, 0, "SELL", 0.80, 50)]
    rt = C.simulate(market(tape(*rows), payout=(1.0, 0.0)), 0, T0, C.Exits(tp=0.05, hold_to_settlement=True))
    assert rt["reason"] == "settle" and rt["pnl_us"] == pytest.approx(40 - 20 - 40 * C.US_RATE * 0.25)


# --- fees ------------------------------------------------------------------------------------------------------


def test_fees_on_both_legs_under_each_scheme():
    rows = _entry_at_50() + [(T0 + 30, 0, "BUY", 0.55, 50), (T0 + 45, 0, "SELL", 0.55, 50)]
    rt = C.simulate(market(tape(*rows), rate_com=0.05), 0, T0, C.Exits(tp=0.05))
    sh = 40.0
    us = sh * 0.0695 * 0.5 * 0.5 + sh * 0.0695 * 0.55 * 0.45
    com = sh * 0.05 * 0.5 * 0.5 + sh * 0.05 * 0.55 * 0.45
    assert rt["fee_us"] == pytest.approx(us) and rt["fee_com"] == pytest.approx(com)
    assert rt["fee_stress"] == pytest.approx(us)  # max(0.0695, 0.05) on both legs
    assert rt["pnl_us"] == pytest.approx(sh * 0.55 - 20 - us) and rt["net_us"] == pytest.approx(rt["pnl_us"] / 20)
    assert rt["entry_print_size"] == 50.0
    maker = _entry_at_50() + [(T0 + 30, 0, "BUY", 0.56, 100)]
    rt = C.simulate(market(tape(*maker), rate_com=0.07), 0, T0, C.Exits(tp=0.05, tp_mode="maker"))
    assert rt["fee_us"] == pytest.approx(sh * 0.0695 * 0.25)  # the maker leg is free on the venue
    assert rt["fee_com"] == pytest.approx(sh * 0.07 * 0.25)
    assert rt["fee_stress"] == pytest.approx(sh * 0.07 * 0.25 + sh * 0.07 * 0.55 * 0.45)  # stress charges it
    assert C.leg_fee(100, 0.5, 0.0695) == pytest.approx(1.7375)


# --- one position per market, signals, no lookahead ------------------------------------------------------------


def _random_tape(seed, n=400, span=20_000):
    rng = np.random.default_rng(seed)
    ts = np.sort(T0 + rng.integers(0, span, n)).astype(float)
    p = np.clip(0.5 + np.cumsum(rng.normal(0, 0.01, n)), 0.05, 0.95)
    oi = rng.integers(0, 2, n)
    side = np.where(rng.random(n) < 0.5, "BUY", "SELL")
    price = np.where(oi == 0, p, 1 - p)
    return tape(*[(ts[i], int(oi[i]), side[i], round(float(price[i]), 3), float(rng.integers(5, 200))) for i in range(n)])


def test_one_position_per_market_and_reentry_only_after_the_exit():
    t = _random_tape(1)
    sig = np.where(np.arange(len(t)) % 3 == 0, 0, -1).astype(np.int8)  # signals everywhere
    mk = market(t, hard_end=T0 + 20_000, entry_deadline=T0 + 20_000, end_t=T0 + 20_000, settle_t=T0 + 20_100,
                entry_windows=((T0, T0 + 20_000),))
    trips, _ = C.walk(mk, sig, C.Exits(tp=0.03, sl=0.03, hold_s=600))
    assert len(trips) > 5
    for a, b in pairwise(trips):
        assert b["t_signal"] > a["t_exit"]  # never two positions at once in one market
    for r in trips:
        assert r["t_entry"] >= r["t_signal"] + C.LATENCY_S
        if r["exit_leg"] == "taker" and math.isfinite(r["t_trigger"]) and r["reason"] != "time":
            assert r["t_exit"] >= r["t_trigger"] + C.LATENCY_S


def test_walk_respects_windows_and_band():
    rows = [(T0 + 100 * i, 0, "BUY", 0.30 if i < 5 else 0.50, 50) for i in range(10)]
    t = tape(*rows)
    sig = np.zeros(len(t), dtype=np.int8)
    mk = market(t, entry_windows=((T0 + 250, T0 + 900),), band=(0.40, 0.60))
    trips, _ = C.walk(mk, sig, C.Exits(hold_to_settlement=True))
    assert len(trips) == 1 and trips[0]["t_signal"] == T0 + 500  # 300, 400 are out of band; 500 is the first


def test_signals_never_read_the_future():
    t = _random_tape(2, n=300)
    fair = np.vstack([np.clip(t.p0 + 0.04, 0, 1), np.clip(1 - t.p0 + 0.04, 0, 1)])
    full_sw = {d: C.swing_signals(t, 0.03, 120, 3, d) for d in ("mom", "fade")}
    full_gap = C.gap_signals(t, fair, 0.03)
    for k in range(1, len(t), 7):
        cut = C.Tape(t.ts[:k], t.p0[:k], t.buy0[:k], t.size[:k])
        for d in ("mom", "fade"):
            assert (C.swing_signals(cut, 0.03, 120, 3, d) == full_sw[d][:k]).all()
        assert (C.gap_signals(cut, fair[:, :k], 0.03) == full_gap[:k]).all()


def test_a_trip_does_not_depend_on_prints_after_its_exit():
    t = _random_tape(3)
    mk = market(t, hard_end=T0 + 20_000, entry_deadline=T0 + 20_000, end_t=T0 + 20_000, settle_t=T0 + 20_100)
    ex = C.Exits(tp=0.03, sl=0.03, hold_s=900)
    rng = np.random.default_rng(9)
    checked = 0
    for i in range(0, len(t), 25):
        rt = C.simulate(mk, 0, float(t.ts[i]), ex)
        if rt is None or rt["exit_leg"] == "settle":
            continue
        after = t.ts > rt["t_exit"]
        p0 = t.p0.copy()
        p0[after] = rng.uniform(0.01, 0.99, after.sum())
        buy0 = t.buy0.copy()
        buy0[after] = rng.random(after.sum()) < 0.5
        other = market(C.Tape(t.ts, p0, buy0, t.size), hard_end=mk.hard_end, entry_deadline=mk.entry_deadline,
                       end_t=mk.end_t, settle_t=mk.settle_t)
        again = C.simulate(other, 0, float(t.ts[i]), ex)
        assert {k: again[k] for k in ("t_entry", "p_entry", "t_exit", "p_exit", "reason")} == {
            k: rt[k] for k in ("t_entry", "p_entry", "t_exit", "p_exit", "reason")}
        checked += 1
    assert checked >= 5


def test_swing_signal_direction_and_print_count():
    rows = [(T0 + 20 * i, 0, "BUY", 0.40 + 0.02 * i, 10) for i in range(7)]  # .40 -> .52 in 120 s, 7 prints
    t = tape(*rows)
    mom = C.swing_signals(t, 0.10, 120, 5, "mom")
    fade = C.swing_signals(t, 0.10, 120, 5, "fade")
    assert mom.tolist() == [-1] * 6 + [0] and fade.tolist() == [-1] * 6 + [1]
    assert C.swing_signals(t, 0.10, 120, 7, "mom").tolist() == [-1] * 7  # only 6 prints after the reference
    down = tape(*[(T0 + 20 * i, 0, "BUY", 0.60 - 0.02 * i, 10) for i in range(7)])
    assert C.swing_signals(down, 0.10, 120, 5, "mom")[-1] == 1 and C.swing_signals(down, 0.10, 120, 5, "fade")[-1] == 0


def test_gap_signal_uses_the_outcome_the_print_could_buy():
    t = tape((T0, 0, "BUY", 0.45, 10), (T0 + 1, 0, "SELL", 0.45, 10), (T0 + 2, 1, "SELL", 0.55, 10))
    fair = np.array([[0.50, 0.50, 0.50], [0.50, 0.50, 0.50]])
    s = C.gap_signals(t, fair, 0.05)
    # print 0: buyable 0 at .45 vs fair .50 -> buy 0; print 1: buyable 1 at .55 (above its fair) -> none;
    # print 2: a SELL of token 1 at .55 = buyable 0 at .45 -> buy 0
    assert s.tolist() == [0, -1, 0]
    assert C.gap_signals(t, fair, 0.06).tolist() == [-1, -1, -1]


# --- placebo, risk book, bar -----------------------------------------------------------------------------------


def _flat_tape(n=600):
    rows = []
    for i in range(n):
        rows.append((T0 + 10 * i, 0, "BUY", 0.50, 100))  # buyable 0 at .50
        rows.append((T0 + 10 * i + 5, 0, "SELL", 0.50, 100))  # sellable 0 at .50
    return tape(*rows)


def test_placebo_on_a_flat_market_is_the_fee_and_stays_inside_the_windows():
    t = _flat_tape()
    mk = market(t, entry_windows=((T0 + 1000, T0 + 2000),), band=(0.4, 0.6), hard_end=T0 + 6000,
                entry_deadline=T0 + 6000, end_t=T0 + 6000, settle_t=T0 + 6100)
    ex = C.Exits(tp=0.05, sl=0.05, hold_s=300)
    m = C.placebo_matrix(mk, 3, ex, draws=20, rng=np.random.default_rng(5))
    assert m.shape == (20, 3) and np.isfinite(m).all()
    fee_only = -(40 * 0.0695 * 0.25 * 2) / 20  # in and out at .50: the round trip costs two taker fees
    assert m == pytest.approx(np.full((20, 3), fee_only))
    rd = C.placebo_reading([m], real_mean=0.0)
    assert rd["p95"] == pytest.approx(fee_only) and rd["real_percentile"] == 100.0 and rd["drop_share"] == 0.0
    again = C.placebo_matrix(mk, 3, ex, draws=20, rng=np.random.default_rng(5))
    assert np.array_equal(m, again)  # seeded: reproducible
    closed = market(t, entry_windows=((T0 + 1000, T0 + 2000),), band=(0.6, 0.9))
    assert np.isnan(C.placebo_matrix(closed, 1, ex, draws=3)).all()  # nothing in band: dropped, not invented


def test_placebo_draws_the_side_as_well_as_the_time():
    rows = []
    for i in range(600):
        rows.append((T0 + 10 * i, 0, "BUY", 0.30, 100))  # outcome 0 at .30 (sellable 1 at .70)
        rows.append((T0 + 10 * i + 5, 0, "SELL", 0.30, 100))  # sellable 0 at .30 (buyable 1 at .70)
    mk = market(tape(*rows), entry_windows=((T0 + 1000, T0 + 2000),), hard_end=T0 + 6000, entry_deadline=T0 + 6000,
                end_t=T0 + 6000, settle_t=T0 + 6100)
    m = C.placebo_matrix(mk, 4, C.Exits(hold_s=300), draws=50, rng=np.random.default_rng(1))
    # flat prices: the cost is 2 x 20 x 0.0695 x (1 - p) per $20, so the two sides give two different values
    side0, side1 = -2 * 0.0695 * 0.70, -2 * 0.0695 * 0.30
    vals = set(np.round(m.ravel(), 9))
    assert vals == {round(side0, 9), round(side1, 9)}


def test_placebo_reading_percentile():
    m = np.arange(100, dtype=float).reshape(100, 1) / 1000.0  # draw means 0.000 .. 0.099
    rd = C.placebo_reading([m], real_mean=0.0965)
    assert rd["p95"] == pytest.approx(np.percentile(np.arange(100) / 1000.0, 95))
    assert rd["real_percentile"] == pytest.approx(97.0)


def _trips(rows):
    """rows: (t_entry, t_exit, pnl_us, event)"""
    out = []
    for i, (a, b, pnl, ev) in enumerate(rows):
        out.append({"id": f"m{i}", "event": ev, "split": "train", "o": 0, "t_signal": a - 10, "p_signal": 0.5,
                    "t_entry": a, "p_entry": 0.5, "shares": 40.0, "entry_print_size": 10.0 if i % 2 else 50.0,
                    "t_trigger": b - 10, "t_exit": b, "p_exit": 0.5,
                    "reason": "tp" if pnl > 0 else "sl", "exit_leg": "taker", "late_stop": False, "hold_s": b - a,
                    "fee_us": 1.0, "fee_com": 0.8, "fee_stress": 1.0, "pnl_us": pnl, "pnl_com": pnl + 0.2,
                    "pnl_stress": pnl, "net_us": pnl / 20, "net_com": (pnl + 0.2) / 20, "net_stress": pnl / 20,
                    "day": C._day(b)})
    return C.trips_frame(out)


def test_risk_book_open_positions_drawdown_worst_day_and_daily_stop():
    d0 = 1_785_024_000.0  # 2026-07-26 00:00 UTC
    h = 3600.0
    f = _trips([
        (d0 + 1 * h, d0 + 3 * h, 5.0, "a"),
        (d0 + 2 * h, d0 + 4 * h, -12.0, "b"),  # realized at 04:00: the day is now at -7
        (d0 + 2.5 * h, d0 + 5 * h, -4.0, "c"),  # realized at 05:00: -11 -> the daily stop is hit
        (d0 + 6 * h, d0 + 7 * h, 3.0, "d"),  # entered after the stop: skipped by the overlay
        (d0 + 26 * h, d0 + 27 * h, 2.0, "e"),  # next day: allowed again
    ])
    rb = C.risk_book(f, "train")
    assert rb["max_open"] == 3 and rb["capital_usd"] == 60.0
    assert rb["max_drawdown_usd"] == pytest.approx(-16.0)  # +5, -12, -4 from the +5 peak
    assert rb["worst_day_usd"] == pytest.approx(-8.0) and rb["best_day_usd"] == pytest.approx(2.0)
    ds = rb["daily_stop"]
    assert ds["skipped"] == 1 and ds["days_stopped"] == 1 and ds["n"] == 4
    assert ds["total_usd"] == pytest.approx(5 - 12 - 4 + 2)
    assert rb["longest_losing_streak"] == 2 and rb["worst_trip_usd"] == -12.0
    assert rb["sharpe_daily"] is not None
    assert C.max_open_positions(np.array([1.0, 2.0]), np.array([2.0, 3.0])) == 1  # exit frees the slot first


def test_summary_bar_and_selection():
    rows = [(T0 + 100 * i, T0 + 100 * i + 50, 1.0 if i % 4 else -0.5, f"ev{i % 40}") for i in range(160)]
    s = C.summarize(_trips(rows), "train", B=300)
    assert s["n"] == 160 and s["n_events"] == 40 and s["losses"] == 40
    assert s["win_rate"] == pytest.approx(0.75) and s["mean_net_us"] > 0 and s["ci95"][0] > 0
    assert s["win_cents"] == pytest.approx(2.5) and s["loss_cents"] == pytest.approx(1.25)
    assert s["breakeven_win_rate"] == pytest.approx(1.25 / 3.75)
    assert s["small_entry_share"] == pytest.approx(0.5)  # half the fills printed 10 < 40 contracts
    assert all(C.bar_checks(s).values())
    assert not C.bar(s, None)["passes"]  # no placebo computed: no pass
    assert not C.bar(s, {"p95": s["mean_net_us"]})["passes"]  # must be strictly above the 95th percentile
    assert C.bar(s, {"p95": -0.02})["passes"]
    weak = {**s, "mean_net_stress": -0.001}
    assert not C.bar(weak, {"p95": -0.02})["passes"]  # negative under the stress fee
    few = C.summarize(_trips(rows[:99]), "train", B=200)
    assert not C.bar_checks(few)["n"]
    cells = [
        {"cell": "a", "selectable": True, "summary": {"ci95": [0.01, 0.2], "mean_net_us": 0.05}, "bar": {"passes": True}},
        {"cell": "b", "selectable": True, "summary": {"ci95": [0.02, 0.1], "mean_net_us": 0.04}, "bar": {"passes": True}},
        {"cell": "c", "selectable": False, "summary": {"ci95": [0.09, 0.3], "mean_net_us": 0.2}, "bar": {"passes": True}},
        {"cell": "d", "selectable": True, "summary": {"ci95": [0.05, 0.3], "mean_net_us": 0.2}, "bar": {"passes": False}},
    ]
    assert C.select_one(cells)["cell"] == "b"  # highest CI lower bound among selectable passes
    assert C.select_one(cells[2:]) is None


def test_event_bootstrap_treats_an_event_as_one_draw():
    v = np.array([1.0] * 50 + [-1.0] * 50)
    g = np.array(["a"] * 50 + ["b"] * 50)  # two events: the mean is either side of zero with equal odds
    lo, hi = C.event_bootstrap_ci(v, g, B=500)
    assert lo == pytest.approx(-1.0) and hi == pytest.approx(1.0)


# --- guards and ledger -------------------------------------------------------------------------------------------


def test_test_split_refuses_without_the_flag(monkeypatch, tmp_path):
    monkeypatch.delenv("LAB7_ALLOW_TEST", raising=False)
    C.check_split_allowed("train")
    C.check_split_allowed("val")
    with pytest.raises(PermissionError):
        C.check_split_allowed("test")
    with pytest.raises(PermissionError):
        C.first_test_look(tmp_path / "test.json")
    with pytest.raises(ValueError):
        C.check_split_allowed("holdout")
    monkeypatch.setenv("LAB7_ALLOW_TEST", "1")
    C.check_split_allowed("test")
    C.first_test_look(tmp_path / "test.json")  # first look allowed
    (tmp_path / "test.json").write_text("{}")
    with pytest.raises(PermissionError):
        C.first_test_look(tmp_path / "test.json")  # never a second


def test_splits_are_lab4s():
    assert C.SPLITS == {"train": ("2026-07-01", "2026-08-16"), "val": ("2026-08-16", "2026-09-16"),
                        "test": ("2026-09-16", "2026-10-09")}
    assert C.split_of(T0) == "train" and C.split_of(1_789_000_000.0) == "val" and C.split_of(1_791_000_000.0) == "test"
    assert C.split_of(1_800_000_000.0) is None


def test_ledger_upserts_and_counts_across_labs(monkeypatch, tmp_path):
    sib = tmp_path / "lab2.json"
    sib.write_text(json.dumps({"n_trials_total": 7}))
    monkeypatch.setattr(C, "SIBLING_LEDGERS", (sib, tmp_path / "missing.json"))
    led = tmp_path / "trials.json"
    assert C.record_run({"hyp": "W1", "cell": "x", "split": "train", "stage": "train"}, ledger=led) == 8
    assert C.record_run({"hyp": "W1", "cell": "x", "split": "train", "stage": "train", "n": 3}, ledger=led) == 8
    assert C.record_run({"hyp": "W1", "cell": "y", "split": "train", "stage": "train"}, ledger=led) == 9
    rows = json.loads(led.read_text())
    assert len(rows) == 2 and rows[0]["lab"] == "lab7" and {r["cell"] for r in rows} == {"x", "y"}
    batch = [{"hyp": "W3", "cell": f"c{i}", "split": "train", "stage": "train"} for i in range(5)]
    assert C.record_runs(batch, ledger=led) == 7 + 7  # 2 earlier + 5 new, plus the sibling's 7
    assert C.record_runs(batch, ledger=led) == 14  # idempotent
    assert (tmp_path / "trials.json.lock").exists() and not (tmp_path / "trials.json.tmp").exists()


def test_load_tape_reads_one_market(tmp_path):
    df = pd.DataFrame({"ts": [T0 + 1, T0, 0, T0 + 2], "price": [0.4, 0.6, 0.5, 1.0], "size": [1.0, 2.0, 3.0, 4.0],
                       "side": ["BUY", "SELL", "BUY", "BUY"], "outcome_index": [0, 1, 0, 0],
                       "asset": ["a"] * 4, "tx": ["t"] * 4})
    df.to_parquet(tmp_path / "123.parquet")
    t = C.load_tape("123", tmp_path)
    assert t.ts.tolist() == [T0, T0 + 1]  # ts 0 and price 1 dropped; sorted
    assert t.price(0) == pytest.approx([0.4, 0.4]) and t.buyable(0).tolist() == [True, True]
    assert C.load_tape("123", tmp_path, min_fills=3) is None and C.load_tape("999", tmp_path) is None
