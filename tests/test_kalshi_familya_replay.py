"""Family A replay and accounting: fees, queue, partial fills, cancel races, limits, settlement, freeze gate.

Every case is deterministic and pinned to research/kalshi_edge_search/PROTOCOL.md (kalshi-familyA-v1).
All money here is a SIMULATED research account.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, date, datetime
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from kalshi_recorder_fixtures import event_row, iso, market_row, orderbook, series_row

from nightcrawler.kalshi_familya import (
    DIRECT_GRID,
    FCM_GRID,
    Account,
    Coverage,
    FamilyAReplay,
    FeeAccumulator,
    FeeBook,
    FeeTerms,
    FreezeError,
    Print,
    ReplayConfig,
    baseline_side,
    check_scoring_allowed,
    run_replay,
)
from nightcrawler.kalshi_recorder_store import RecorderStore

D = Decimal
ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "research" / "kalshi_edge_search"
DAY = date(2026, 10, 20)
START = datetime(2026, 10, 20, tzinfo=UTC).timestamp()
TICKER, EVENT = "KXHIGHNY-26OCT21-T76", "KXHIGHNY-26OCT21"


# --------------------------------------------------------------------------- fees (section 9)
def test_kalshi_published_example_one_fill_on_the_cent_grid() -> None:
    cash = FeeAccumulator(FCM_GRID).fill(D("-0.055000"), D("0.00363825"))
    assert cash.trade_fee == D("0.003639")
    assert cash.cash_change == D("-0.06") and cash.rounding_fee == D("0.001361")
    assert cash.trade_fee + cash.rounding_fee == D("0.005") and cash.rebate == 0


def test_kalshi_published_example_three_fills_rebate_on_the_third() -> None:
    accumulator = FeeAccumulator(FCM_GRID)
    results = [accumulator.fill(D("-0.05"), D("0.006")) for _ in range(3)]  # each overpays $0.004 by rounding
    assert [result.rounding_fee for result in results] == [D("0.004")] * 3
    assert [result.rebate for result in results] == [0, 0, D("0.01")]
    assert accumulator.carried == D("0.002")
    assert [result.cash_change for result in results] == [D("-0.06"), D("-0.06"), D("-0.05")]


def test_the_same_examples_on_the_direct_account_grid() -> None:
    one = FeeAccumulator(DIRECT_GRID).fill(D("-0.055000"), D("0.00363825"))
    assert (one.cash_change, one.rounding_fee) == (D("-0.0587"), D("0.000061"))
    accumulator = FeeAccumulator(DIRECT_GRID)
    results = [accumulator.fill(D("-0.05"), D("0.00606")) for _ in range(3)]  # $0.00004 each
    assert [result.rebate for result in results] == [0, 0, D("0.0001")]
    assert accumulator.carried == D("0.00002")


def test_a_zero_fee_maker_fill_between_grid_steps_pays_the_rounding_and_gets_no_rebate() -> None:
    accumulator = FeeAccumulator(DIRECT_GRID)
    cash = accumulator.fill(-(D("0.555") * D("0.37")), D(0))  # 0.20535 is between $0.0001 steps
    assert cash.cash_change == D("-0.2054") and cash.rounding_fee == D("0.00005") and cash.rebate == 0
    again = accumulator.fill(-(D("0.555") * D("0.37")), D(0))
    assert again.rebate == 0  # capped: a zero-fee fill's net fee may not go negative


def test_maker_fees_only_where_the_series_charges_makers() -> None:
    assert FeeTerms("quadratic", D(1)).maker_model_fee(D(1), D("0.55")) == 0
    charged = FeeTerms("quadratic_with_maker_fees", D(1)).maker_model_fee(D(1), D("0.55"))
    assert charged == D("0.0175") * D("0.55") * D("0.45")
    assert FeeTerms("quadratic", D(1)).taker_model_fee(D(1), D("0.49")) == D("0.07") * D("0.49") * D("0.51")


def test_a_split_fill_rounds_each_part_and_carries_the_accumulator() -> None:
    accumulator = FeeAccumulator(DIRECT_GRID)
    terms = FeeTerms("quadratic_with_maker_fees", D(1))
    parts = [D("0.37"), D("0.63")]
    cash = [accumulator.fill(-(D("0.55") * part), terms.maker_model_fee(part, D("0.55"))) for part in parts]
    whole = FeeAccumulator(DIRECT_GRID).fill(-D("0.55"), terms.maker_model_fee(D(1), D("0.55")))
    assert sum((item.cash_change for item in cash), D(0)) <= whole.cash_change  # splitting never pays less
    assert all(item.cash_change == item.cash_change.quantize(DIRECT_GRID) for item in cash)


def test_a_reservation_covers_one_hundred_partial_fills() -> None:
    terms = FeeTerms("quadratic_with_maker_fees", D(1))
    price = D("0.55")
    reserved = price + (terms.maker_model_fee(D(1), price) / D("0.000001")).to_integral_value(
        rounding="ROUND_CEILING") * D("0.000001") + D("0.0100")
    accumulator = FeeAccumulator(DIRECT_GRID)
    paid = -sum((accumulator.fill(-(price * D("0.01")), terms.maker_model_fee(D("0.01"), price)).cash_change
                 for _ in range(100)), D(0))
    assert paid <= reserved
    flat = FeeAccumulator(DIRECT_GRID)
    paid_flat = -sum((flat.fill(-(D("0.555") * D("0.01")), D(0)).cash_change for _ in range(100)), D(0))
    assert paid_flat <= D("0.555") + D("0.0100")


def test_a_scheduled_fee_change_takes_effect_between_two_fills() -> None:
    book = FeeBook()
    book.add_series(series_row(), START - 86400)
    book.add_series_changes([{"series_ticker": "KXHIGHNY", "fee_type": "quadratic_with_maker_fees",
                              "fee_multiplier": 1, "scheduled_ts": iso(START + 3600)}], START - 3600)
    before = book.terms_at("KXHIGHNY", EVENT, START + 3599)
    after = book.terms_at("KXHIGHNY", EVENT, START + 3601)
    assert before == FeeTerms("quadratic", D(1)) and after == FeeTerms("quadratic_with_maker_fees", D(1))
    book.add_event_changes(EVENT, [{"fee_type": "quadratic", "fee_multiplier": 0, "scheduled_ts": iso(START)}],
                           START - 60)
    assert book.terms_at("KXHIGHNY", EVENT, START + 3601) == FeeTerms("quadratic", D(0))


# --------------------------------------------------------------------------- a small simulated market
def covered() -> Coverage:
    coverage = Coverage()
    coverage.exchange.add(int(START - 86400), int(START + 40 * 86400))
    for ticker in (TICKER, "KXHIGHNY-26OCT21-T78", *(f"KX{city}-26OCT21-T1" for city in CITIES)):
        coverage.watched[ticker].add(START - 86400, START + 40 * 86400)
    return coverage


CITIES = ("HIGHCHI", "HIGHMIA", "HIGHLAX", "HIGHDEN", "HIGHAUS", "HIGHPHIL", "HIGHSEA", "HIGHBOS")


def market(replay: FamilyAReplay, ticker: str = TICKER, event: str = EVENT, series: str = "KXHIGHNY",
           at: float = START - 600, **row: Any) -> None:
    replay.on_series_row(series_row(series), at)
    replay.on_event_row(event_row(event, series), at)
    replay.on_event_fee_changes(event, [], at)
    replay.on_market_row(market_row(ticker, event, now=START, open_offset=-30 * 3600, close_offset=40 * 3600,
                                    volume_24h_fp="100.00", **row), at, full=True, sweep=True)


def simulated(variant: str = "A1", *, days: int = 1, tickers: tuple[str, ...] = (TICKER,), **config: Any) -> FamilyAReplay:
    replay = FamilyAReplay(ReplayConfig(variant, "TRAIN", DAY, days, **config), covered())
    replay.on_series_fee_changes([], START - 600)
    for ticker in tickers:
        if ticker.startswith("KXHIGHNY"):
            market(replay, ticker)
        else:
            series = ticker.split("-")[0]
            market(replay, ticker, f"{series}-26OCT21", series)
    return replay


def sell_yes(ticker: str, at: float, count: str, price: str = "0.62", trade_id: str = "", block: bool = False,
             outcome: str = "no", book_side: str = "ask") -> Print:
    yes = D(price)
    return Print(ticker, trade_id or f"t{at}", at, at + 0.2, yes, 1 - yes, D(count), outcome, book_side, block)


def book(replay: FamilyAReplay, at: float, yes: list[tuple[str, str]], no: list[tuple[str, str]],
         ticker: str = TICKER) -> None:
    raw = orderbook(yes, no)
    replay.on_book(ticker, raw["yes_dollars"], raw["no_dollars"], at)


def order_of(replay: FamilyAReplay, ticker: str = TICKER) -> Any:
    return max((order for order in replay.orders.values() if order.ticker == ticker), key=lambda order: order.oid)


def settle(replay: FamilyAReplay, at: float, result: str = "yes", ticker: str = TICKER) -> None:
    value = "1.0000" if result == "yes" else "0.0000"
    replay.on_market_row({**replay.markets[ticker].row, "status": "finalized", "result": result,
                          "settlement_value_dollars": value, "settlement_ts": iso(at - 300)}, at, full=True)


# --------------------------------------------------------------------------- queue, partial fills and settlement
def test_queue_behind_visible_size_partial_fills_and_settlement_reconcile_exactly() -> None:
    replay = simulated("A1")
    book(replay, START - 10, [("0.62", "5.00")], [("0.35", "10.00")])  # YES favourite: mid 0.635, join 0.62
    replay.on_print(sell_yes(TICKER, START + 0.5, "50"))  # before our arrival: never ours
    book(replay, START + 2, [("0.62", "4.00")], [("0.35", "10.00")])  # confirms: queue = max(5, 4)
    order = order_of(replay)
    assert (order.side, order.price, order.state, order.queue) == ("yes", D("0.62"), "resting", D(5))
    replay.on_print(sell_yes(TICKER, START + 3, "3"))  # uses the queue ahead first
    assert order.queue == 2 and order.remaining == 1
    book(replay, START + 4, [("0.62", "1.00")], [("0.35", "10.00")])  # cancellations ahead of us
    assert order.queue == 1
    replay.on_print(sell_yes(TICKER, START + 5, "1.5"))
    assert order.remaining == D("0.50") and order.queue == 0
    replay.on_print(sell_yes(TICKER, START + 6, "0.7"))
    assert order.state == "dead" and order.remaining == 0
    assert replay.account.cash == D("25.0000") - D("0.62")
    settle(replay, START + 40 * 3600 + 600, "yes")
    result = replay.finish(START + 40 * 3600 + 700)
    assert result["net_usd"] == "0.3800" or D(result["net_usd"]) == D("0.38")
    assert result["accounting"]["reconciled"] is True and result["counts"]["fills"] == 2
    assert result["traded_resolved_clusters"] == 1 and D(result["capital_days_usd"]) > 0
    assert result["label"].startswith("SIMULATED")


def test_wrong_side_higher_price_block_and_inconsistent_prints_never_fill() -> None:
    replay = simulated("A1")
    book(replay, START - 10, [("0.62", "2.00")], [("0.35", "10.00")])
    book(replay, START + 2, [("0.62", "2.00")], [("0.35", "10.00")])
    order = order_of(replay)
    replay.on_print(sell_yes(TICKER, START + 3, "5", outcome="yes", book_side="bid"))  # a buyer of YES
    replay.on_print(sell_yes(TICKER, START + 4, "5", price="0.63"))  # above our bid
    replay.on_print(sell_yes(TICKER, START + 5, "5", block=True))  # block trades never touch the book
    assert order.remaining == 1 and order.queue == 2
    replay.on_print(Print(TICKER, "odd", START + 6, START + 6, D("0.62"), D("0.40"), D("1"), "no", "ask", False))
    assert order.remaining == 1 and order.queue == 1  # inconsistent sides: reduces the queue, never fills


def test_cancel_race_fills_count_and_the_reservation_stays_until_the_cancel_takes_effect() -> None:
    replay = simulated("A2")  # improve by one tick: 0.63 with nobody displayed there
    book(replay, START - 10, [("0.62", "5.00")], [("0.35", "10.00")])
    book(replay, START + 2, [("0.62", "5.00")], [("0.35", "10.00")])
    order = order_of(replay)
    assert (order.price, order.queue, order.state) == (D("0.63"), 0, "resting")
    book(replay, START + 30, [("0.50", "5.00")], [("0.35", "10.00")])  # spread 15c: the next decision cancels
    replay.on_print(sell_yes(TICKER, START + 60.5, "0.20", price="0.63"))  # after the decision, before the ack
    assert order.cancel_at == START + 61 and order.remaining == D("0.80")
    replay.on_print(sell_yes(TICKER, START + 61.2, "0.30", price="0.63"))  # inside the clock margin: still ours
    assert order.remaining == D("0.50") and order.oid in replay.account.reserved
    replay.on_print(sell_yes(TICKER, START + 61.3, "0.30", price="0.63"))  # too late
    assert order.remaining == D("0.50") and order.state == "dead"
    assert order.oid not in replay.account.reserved and replay.counts["cancel_spread_gt_10c"] == 1


def test_post_only_rejections_at_and_after_arrival() -> None:
    replay = simulated("A1")
    book(replay, START - 10, [("0.62", "5.00")], [("0.35", "10.00")])
    book(replay, START + 0.5, [("0.62", "5.00")], [("0.38", "10.00")])  # YES ask 0.62 = our bid at arrival
    first = order_of(replay)
    replay.on_print(sell_yes(TICKER, START + 2, "1"))
    assert first.state == "rejected" and replay.counts["post_only_rejections"] == 1
    later = simulated("A1")
    book(later, START - 10, [("0.62", "5.00")], [("0.35", "10.00")])
    later.on_print(sell_yes(TICKER, START + 1.5, "20"))  # buffered until the next book confirms the order
    book(later, START + 3, [("0.62", "5.00")], [("0.39", "10.00")])  # YES ask 0.61: we would have taken
    order = order_of(later)
    assert order.state == "rejected" and order.remaining == 1 and later.account.cash == D("25.0000")


def test_a_book_offering_at_or_below_our_bid_counts_once_as_a_print() -> None:
    replay = simulated("A1")
    book(replay, START - 10, [("0.62", "5.00")], [("0.35", "10.00")])
    book(replay, START + 2, [("0.62", "5.00")], [("0.35", "10.00")])
    order = order_of(replay)
    book(replay, START + 10, [("0.62", "5.00")], [("0.39", "3.00"), ("0.35", "10.00")])  # 3 offered at 0.61
    assert order.queue == 2 and order.remaining == 1
    book(replay, START + 11, [("0.62", "5.00")], [("0.39", "3.00"), ("0.35", "10.00")])  # the same 3: no recount
    assert order.queue == 2
    book(replay, START + 12, [("0.62", "5.00")], [("0.39", "10.00")])  # 7 more
    assert order.remaining == 0 and replay.counts["crossing_book_prints"] == 2


def test_pessimistic_model_queue_never_falls_on_books_and_trade_throughs_fill_first() -> None:
    replay = simulated("A1", model="pessimistic")
    assert replay.latency == 2.0
    book(replay, START - 10, [("0.62", "5.00")], [("0.35", "10.00")])
    book(replay, START + 3, [("0.62", "5.00")], [("0.35", "10.00")])
    order = order_of(replay)
    book(replay, START + 4, [("0.62", "1.00")], [("0.35", "10.00")])
    assert order.queue == 5  # cancellations never move us up
    replay.on_print(sell_yes(TICKER, START + 5, "0.40", price="0.61"))  # a trade-through reaches us first
    assert order.remaining == D("0.60") and order.queue == 5
    replay.on_print(sell_yes(TICKER, START + 6, "3", price="0.62"))  # at our price the queue still goes first
    assert order.remaining == D("0.60") and order.queue == 2
    assert order.accumulator.rebates is False


def test_no_trade_at_exactly_even_odds_and_the_baseline_ignores_the_favourite() -> None:
    replay = simulated("A1")
    book(replay, START - 10, [("0.50", "5.00")], [("0.49", "10.00")])  # YES mid 0.505: favourite YES
    assert replay.favourite(replay.markets[TICKER].book) == "yes"
    book(replay, START - 5, [("0.49", "5.00")], [("0.49", "10.00")])  # mid 0.50: no favourite
    assert replay.target(replay.markets[TICKER], START) is None
    assert baseline_side("KXHIGHNY-26OCT21-T76") in ("yes", "no")
    assert baseline_side("A") == ("yes" if hashlib.sha256(b"familyA-baseline-v1|A").digest()[0] % 2 == 0 else "no")


def test_one_quote_per_cluster_and_the_day_stop_binds_at_three_dollars() -> None:
    tickers = (TICKER, "KXHIGHNY-26OCT21-T78", *(f"KX{city}-26OCT21-T1" for city in CITIES))
    replay = simulated("A1", tickers=tickers)
    for ticker in tickers:
        book(replay, START - 10, [("0.62", "5.00")], [("0.35", "10.00")], ticker=ticker)
    replay.on_book_unchanged(TICKER, START + 0.5)  # anything after 00:00:00 runs the first decision
    sent = [order for order in replay.orders.values()]
    clusters = [order.cluster for order in sent]
    assert len(clusters) == len(set(clusters))  # two NYC strikes on one date share one cluster: one quote
    assert len(sent) == 4 and replay.blocks["day_3"] >= 1  # 4 x $0.63 = $2.52; a fifth would reach $3.15
    assert replay.account.at_risk() == D("2.52")


def test_account_limits_cluster_outstanding_lifetime_and_cash() -> None:
    account = Account()
    account.reserved = {1: D("1.50")}
    account.order_cluster = {1: "TEMP_NYC|26OCT21"}
    account.order_day = {1: "2026-10-19"}
    assert account.blocked_by("TEMP_NYC|26OCT21", "2026-10-20", D("0.60")) == "cluster_2"
    assert account.blocked_by("OIL|26OCT21", "2026-10-20", D("0.60")) is None
    account.reserved.update({2: D("1.90")})
    account.order_cluster[2], account.order_day[2] = "GOLD|26OCT21", "2026-10-19"
    assert account.blocked_by("OIL|26OCT21", "2026-10-20", D("0.61")) == "outstanding_4"
    assert account.blocked_by("OIL|26OCT21", "2026-10-20", D("0.61"), day_stop="live_style") == "outstanding_4"
    assert account.blocked_by("OIL|26OCT21", "2026-10-20", D("0.60")) is None  # carried risk is not today's
    assert account.blocked_by("OIL|26OCT21", "2026-10-20", D("0.60"), day_stop="live_style") == "day_3"
    account.realized = [{"pnl": D("-1.55")}]
    assert account.blocked_by("OIL|26OCT21", "2026-10-20", D("0.10")) == "lifetime_5"  # 1.55 + 3.40 + 0.10 >= 5
    poor = Account(cash=D("0.50"))
    assert poor.blocked_by("OIL|26OCT21", "2026-10-20", D("0.60")) == "cash"
    assert Account().blocked_by("OIL|26OCT21", "2026-10-20", D("5"), unfunded=True) == "cluster_2"


def test_a_loss_settles_at_settlement_time_and_capital_is_charged_until_then() -> None:
    replay = simulated("A1")
    book(replay, START - 10, [("0.62", "1.00")], [("0.35", "10.00")])
    book(replay, START + 2, [("0.62", "1.00")], [("0.35", "10.00")])
    replay.on_print(sell_yes(TICKER, START + 3, "5"))
    assert replay.account.positions[TICKER].count == 1
    settle(replay, START + 3 * 86400, "no")
    result = replay.finish(START + 3 * 86400 + 60)
    assert D(result["net_usd"]) == D("-0.62") and result["by_block"]
    assert D(result["capital_days_usd"]) >= D("0.62") * D("2.9")  # held almost three days
    assert D(result["days"]) > D("2.9")  # the calendar runs until the last settlement


def test_unresolved_positions_count_at_zero_and_a_short_tape_is_flagged() -> None:
    replay = simulated("A1")
    book(replay, START - 10, [("0.62", "1.00")], [("0.35", "10.00")])
    book(replay, START + 2, [("0.62", "1.00")], [("0.35", "10.00")])
    replay.on_print(sell_yes(TICKER, START + 3, "5"))
    result = replay.finish(START + 2 * 86400)
    assert result["resolution_complete"] is False and result["status"].startswith("INCOMPLETE_DATA")
    assert result["unresolved"][0]["ticker"] == TICKER and D(result["net_usd"]) == D("-0.62")


def test_rotation_cancels_after_six_hours_without_a_fill_and_rests_six_hours() -> None:
    replay = simulated("A1")
    book(replay, START - 10, [("0.62", "5.00")], [("0.35", "10.00")])
    for minute in range(1, 7 * 60):
        replay.on_book_unchanged(TICKER, START + minute * 60 - 1)
        replay.on_market_row({"ticker": TICKER, "volume_24h_fp": "100.00"}, START + minute * 60 - 1, full=False,
                             sweep=True)
    assert replay.counts["cancel_rotation_6h"] == 1
    assert replay.counts["quotes_sent"] == 1  # still cooling down an hour after the rotation


# --------------------------------------------------------------------------- the freeze gate (sections 11 and 18)
def research_copy(tmp_path: Path) -> Path:
    target = tmp_path / "research"
    target.mkdir()
    for name in ("PROTOCOL.md", "PROTOCOL.sha256"):
        shutil.copy(RESEARCH / name, target / name)
    return target


def freeze(research: Path, **values: Any) -> None:
    published = (research / "PROTOCOL.sha256").read_text().split()[0]
    body = {"protocol_sha256": published, "variant": "A1", "E1": "2026-12-01", "test_days": 28,
            "parameters": ReplayConfig("A1", "TEST", date(2026, 12, 1), 28).parameters(), **values}
    directory = research / "family_a"
    directory.mkdir(exist_ok=True)
    (directory / "FREEZE.json").write_text(json.dumps(body))
    digest = hashlib.sha256((directory / "FREEZE.json").read_bytes()).hexdigest()
    (directory / "FREEZE.sha256").write_text(f"{digest}  FREEZE.json\n")


def test_test_rows_are_refused_until_a_frozen_hashed_config_exists(tmp_path: Path) -> None:
    research = research_copy(tmp_path)
    test = ReplayConfig("A1", "TEST", date(2026, 12, 1), 28)
    with pytest.raises(FreezeError, match="TEST rows cannot be scored"):
        check_scoring_allowed(test, research)
    with pytest.raises(FreezeError, match="TEST rows cannot be scored"):
        run_replay(tmp_path / "no-data-read", test, research)  # refused before any row is read
    freeze(research)
    assert check_scoring_allowed(test, research) is not None
    with pytest.raises(FreezeError, match="does not match"):
        check_scoring_allowed(ReplayConfig("A2", "TEST", date(2026, 12, 1), 28), research)
    assert check_scoring_allowed(ReplayConfig("A1", "TEST", date(2026, 12, 1), 28, model="pessimistic"), research)
    with pytest.raises(FreezeError, match="frozen TEST period"):
        check_scoring_allowed(ReplayConfig("A1", "VAL", date(2026, 11, 28), 7), research)
    assert check_scoring_allowed(ReplayConfig("A1", "VAL", date(2026, 11, 20), 7), research)


def test_an_unhashed_freeze_or_an_edited_protocol_blocks_every_phase(tmp_path: Path) -> None:
    research = research_copy(tmp_path)
    freeze(research)
    (research / "family_a" / "FREEZE.sha256").write_text("0" * 64 + "  FREEZE.json\n")
    with pytest.raises(FreezeError, match="FREEZE.sha256"):
        check_scoring_allowed(ReplayConfig("A1", "TRAIN", DAY, 7), research)
    (research / "PROTOCOL.md").write_text("edited after the freeze\n")
    with pytest.raises(FreezeError, match="PROTOCOL.md"):
        check_scoring_allowed(ReplayConfig("A1", "TRAIN", DAY, 7), research)


def test_the_real_protocol_hash_matches_and_train_is_allowed_without_a_freeze() -> None:
    assert check_scoring_allowed(ReplayConfig("A1", "TRAIN", DAY, 7), RESEARCH) is None


# --------------------------------------------------------------------------- end to end on the recorder's format
def test_a_replay_reads_the_recorders_own_files(tmp_path: Path) -> None:
    root = tmp_path / "kalshi_recorder"
    clock = {"at": START - 3600}
    store = RecorderStore(root, max_bytes=256 * 1024 * 1024, min_free_bytes=0, clock=lambda: clock["at"],
                          disk_free=lambda path: 10 ** 12, headroom_bytes=1024)
    at = START - 3600
    store.append("discovery", "series_list", {"category": "Climate and Weather", "rows": [series_row()]}, at)
    store.append("discovery", "events_page", {"rows": [event_row(EVENT)], "page": 1}, at + 1)
    store.append("fees", "series_fee_changes", {"body": {"series_fee_change_arr": []}}, at + 2)
    store.append("fees", "event_fee_changes", {"event_ticker": EVENT, "body": {"event_fee_changes": []}}, at + 3)
    full = market_row(TICKER, EVENT, now=START, open_offset=-30 * 3600, close_offset=40 * 3600)
    store.append("markets", "discovery_markets", {"rows": [{"ticker": TICKER, "full": full}]}, at + 4)
    store.append("admissions", "watch", {"action": "start", "tickers": [TICKER], "at_watch": at + 5}, at + 5)
    store.append("trade_coverage", "trade_coverage", {"from": int(at), "to": int(START + 2 * 86400),
                                                      "scope": "exchange", "backfill": False}, at + 6)
    store.append("books", "book", {"ticker": TICKER, "orderbook_fp": orderbook([("0.62", "1.00")], [("0.35", "9")])},
                 START - 30)
    for minute in range(0, 24 * 60, 5):
        when = START + minute * 60 - 20
        clock["at"] = when
        store.append("markets", "sweep", {"rows": [{"ticker": TICKER, "dyn": {"volume_24h_fp": "80.00"}}]}, when)
        store.append("book_calls", "book_call", {"unchanged": [TICKER], "changed": [], "missing": []}, when + 1)
    store.append("trades", "trades", {"rows": [{
        "trade_id": "x1", "ticker": TICKER, "created_time": iso(START + 30), "yes_price_dollars": "0.6200",
        "no_price_dollars": "0.3800", "count_fp": "2.00", "taker_outcome_side": "no", "taker_book_side": "ask",
        "is_block_trade": False}]}, START + 32)
    settled = {**full, "status": "finalized", "result": "yes", "settlement_value_dollars": "1.0000",
               "settlement_ts": iso(START + 41 * 3600)}
    clock["at"] = START + 42 * 3600
    store.append("settlement", "settlement", {"rows": [settled]}, START + 42 * 3600)
    store.close()
    result = run_replay(root, ReplayConfig("A1", "TRAIN", DAY, 1), RESEARCH)
    assert result["counts"]["quotes_sent"] >= 1 and result["counts"]["fills"] == 1
    assert D(result["net_usd"]) == D("0.38") and result["accounting"]["reconciled"] is True
    assert result["resolution_complete"] is True and result["unidentifiable_quotes"] == 0


def test_every_saved_public_book_parses_into_an_uncrossed_top_ten_book() -> None:
    from kalshi_recorder_fixtures import SAMPLE

    from nightcrawler.kalshi_familya import Book, parse_levels
    from nightcrawler.kalshi_recorder import favourite_mid

    paths = sorted(SAMPLE.glob("*-round*.json"))
    assert len(paths) == 12
    for path in paths:
        raw = json.loads(path.read_text(encoding="utf-8"))["data"]["orderbook_fp"]
        yes, no = parse_levels(raw["yes_dollars"]), parse_levels(raw["no_dollars"])
        assert yes is not None and no is not None and len(yes) == len(no) == 10
        parsed = Book(path.stem, 0.0, yes, no)
        assert not parsed.crossed_or_locked() and parsed.ask("yes") == 1 - parsed.best("no")
        assert all(earlier[0] > later[0] for earlier, later in pairwise(yes))
        mid = favourite_mid(raw)
        assert mid is not None and D("0.5") <= mid < 1
