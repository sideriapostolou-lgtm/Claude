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
    code_hashes,
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
    """A repository-shaped copy: <repo>/research/kalshi_edge_search (the protocol) and <repo>/docs/WORKLOG.md."""
    repo = tmp_path / "repo"
    target = repo / "research" / "kalshi_edge_search"
    target.mkdir(parents=True)
    for name in ("PROTOCOL.md", "PROTOCOL.sha256"):
        shutil.copy(RESEARCH / name, target / name)
    (repo / "docs").mkdir()
    (repo / "docs" / "WORKLOG.md").write_text("# Work log\n")
    return target


def freeze(research: Path, *, log_hash: bool = True, **values: Any) -> str:
    """Write a FREEZE.json (A1, E1 2026-12-01, 28 days, frozen a day early) and publish its hash."""
    published = (research / "PROTOCOL.sha256").read_text().split()[0]
    body = {"protocol_sha256": published, "variant": "A1", "E1": "2026-12-01", "test_days": 28,
            "parameters": ReplayConfig("A1", "TEST", date(2026, 12, 1), 28).parameters(),
            "code_sha256": code_hashes(), "frozen_at": "2026-11-30T09:00:00+00:00", **values}
    directory = research / "family_a"
    directory.mkdir(exist_ok=True)
    (directory / "FREEZE.json").write_text(json.dumps(body))
    digest = hashlib.sha256((directory / "FREEZE.json").read_bytes()).hexdigest()
    (directory / "FREEZE.sha256").write_text(f"{digest}  FREEZE.json\n")
    if log_hash:
        worklog = research.parents[1] / "docs" / "WORKLOG.md"
        worklog.write_text(worklog.read_text() + f"- Family A FREEZE.json SHA-256 {digest}\n")
    return digest


def test_test_rows_are_refused_until_a_frozen_hashed_config_exists(tmp_path: Path) -> None:
    research = research_copy(tmp_path)
    test = ReplayConfig("A1", "TEST", date(2026, 12, 1), 28)
    with pytest.raises(FreezeError, match="TEST rows cannot be scored"):
        check_scoring_allowed(test, research)
    with pytest.raises(FreezeError, match="TEST rows cannot be scored"):
        run_replay(tmp_path / "no-data-read", test, research)  # refused before any row is read
    freeze(research)
    assert check_scoring_allowed(test, research).freeze is not None
    with pytest.raises(FreezeError, match="neither the frozen variant"):
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
    assert check_scoring_allowed(ReplayConfig("A1", "TRAIN", DAY, 7), RESEARCH).freeze is None


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
    result = run_replay(root, ReplayConfig("A1", "TRAIN", DAY, 7), RESEARCH)
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


# --------------------------------------------------------------------------- review regressions (2026-10-13)
def test_r1_the_lower_bound_fills_an_unfilled_unidentifiable_quote_whose_side_lost() -> None:
    """7.7: an unidentifiable quote counts as filled at q for its remaining size if that side lost."""
    coverage = Coverage()
    coverage.exchange.add(int(START - 86400), int(START + 10))  # a tape gap from START+10 ...
    coverage.exchange.add(int(START + 400), int(START + 40 * 86400))  # ... to START+400
    coverage.watched[TICKER].add(START - 86400, START + 40 * 86400)
    replay = FamilyAReplay(ReplayConfig("A1", "TRAIN", DAY, 1), coverage)
    replay.on_series_fee_changes([], START - 600)
    market(replay)
    book(replay, START - 10, [("0.62", "5.00")], [("0.35", "10.00")])
    book(replay, START + 2, [("0.62", "5.00")], [("0.35", "10.00")])  # resting, never filled
    settle(replay, START + 40 * 3600 + 600, "no")  # the YES side we bid lost
    result = replay.finish(START + 40 * 3600 + 700)
    assert result["unidentifiable_quotes"] == 1 and D(result["net_usd"]) == 0
    assert D(result["lower_bound_net_usd_unidentifiable"]) == D("-0.63")  # q + fee + the rounding pad (was 0)
    assert result["verdict_basis"] == "lower_bound_7_7" and D(result["verdict_net_usd"]) == D("-0.63")
    assert D(result["verdict_net_per_day_usd_before_opex"]) < 0


def test_r1_the_lower_bound_ignores_a_quote_whose_side_won() -> None:
    coverage = Coverage()
    coverage.exchange.add(int(START - 86400), int(START + 10))
    coverage.exchange.add(int(START + 400), int(START + 40 * 86400))
    coverage.watched[TICKER].add(START - 86400, START + 40 * 86400)
    replay = FamilyAReplay(ReplayConfig("A1", "TRAIN", DAY, 1), coverage)
    replay.on_series_fee_changes([], START - 600)
    market(replay)
    book(replay, START - 10, [("0.62", "5.00")], [("0.35", "10.00")])
    book(replay, START + 2, [("0.62", "5.00")], [("0.35", "10.00")])
    settle(replay, START + 40 * 3600 + 600, "yes")  # our side won: an unfilled quote costs nothing
    won = replay.finish(START + 40 * 3600 + 700)
    assert won["unidentifiable_quotes"] == 1 and D(won["lower_bound_net_usd_unidentifiable"]) == 0
    assert won["verdict_basis"] == "lower_bound_7_7"


def test_r1_the_lower_bound_counts_at_most_one_contract_per_market() -> None:
    from nightcrawler.kalshi_familya import Order

    replay = simulated("A1")
    replay.markets[TICKER].yes_value = D(0)  # NO won; both quotes bid YES
    for oid, price in ((901, D("0.62")), (902, D("0.63"))):  # a quote and its replacement, both in a gap
        replay.orders[oid] = Order(oid, TICKER, "yes", price, D(1), "TEMP_NYC|26OCT21", START, START + 1,
                                   "2026-10-20", price + D("0.01"), oid == 902, remaining=D(1))
        replay.unidentifiable.append(oid)
    assert replay._lower_bound(D(0)) == D("-0.64")  # one contract, at the dearer of the two (not -1.27)
    replay.markets[TICKER].yes_value = None  # never resolved: counts at $0 (section 11), so still a loss
    assert replay._lower_bound(D(0)) == D("-0.64")


def test_r2_a_replacement_is_not_blocked_by_the_reservation_it_replaces() -> None:
    """6: a reservation is held until its cancel is acknowledged; 5.5: the replacement is sent at that ack."""
    tickers = (TICKER, "KXHIGHNY-26OCT21-T78", *(f"KX{city}-26OCT21-T1" for city in CITIES))
    replay = simulated("A1", tickers=tickers)
    for ticker in tickers:
        book(replay, START - 10, [("0.62", "5.00")], [("0.35", "10.00")], ticker=ticker)
    replay.on_book_unchanged(TICKER, START + 0.5)  # decision at 00:00: four quotes, $2.52 of today's risk
    assert replay.counts["quotes_sent"] == 4
    first = "KXHIGHAUS-26OCT21-T1"
    book(replay, START + 30, [("0.63", "5.00")], [("0.35", "10.00")], ticker=first)  # the best bid moved up
    for ticker in tickers:  # keep every quote sweep fresh so nothing else is cancelled
        replay.on_market_row({"ticker": ticker, "volume_24h_fp": "100.00"}, START + 30, full=False, sweep=True)
    replay.on_book_unchanged(TICKER, START + 60.5)  # after the 00:01 decision, before its ack at 00:01:01
    assert replay.counts["replacements"] == 1
    # 5.9: the replacement's extra $0.01 is held back from new quotes at that decision.
    old = next(order for order in replay.orders.values() if order.ticker == first)
    assert replay.account.earmarks[old.oid][2] == D("0.01")
    assert replay.account.blocked_by("OIL|26OCT21", "2026-10-20", D("0.475")) == "day_3"
    earmark = replay.account.earmarks.pop(old.oid)
    assert replay.account.blocked_by("OIL|26OCT21", "2026-10-20", D("0.475")) is None
    replay.account.earmarks[old.oid] = earmark
    replay.on_book_unchanged(TICKER, START + 62)
    # 3 x 0.63 + 0.64 = 2.53 < 3.00: sent. The old reservation was counted until ack + epsilon before (3.16).
    assert replay.counts["replacement_orders"] == 1, dict(replay.blocks)
    assert not replay.account.earmarks and replay.account.at_risk() == D("2.53")


def test_r3_a_clock_margin_fill_of_the_old_order_trims_the_replacement_to_the_rest() -> None:
    replay = simulated("A1")
    book(replay, START - 10, [("0.62", "5.00")], [("0.35", "10.00")])
    book(replay, START + 30, [("0.63", "5.00")], [("0.35", "10.00")])  # confirms (Q = max(5, 0) = 5)
    book(replay, START + 40, [("0.63", "5.00")], [("0.35", "10.00")])  # nobody left at 0.62: Q -> 0
    replay.on_market_row({"ticker": TICKER, "volume_24h_fp": "100.00"}, START + 40, full=False, sweep=True)
    old = order_of(replay)
    assert old.state == "resting" and old.queue == 0
    replay.on_print(sell_yes(TICKER, START + 61.1, "0.30", price="0.62"))  # after the ack, inside epsilon
    new = order_of(replay)
    assert new.oid != old.oid and old.remaining == D("0.70")
    assert replay.account.positions[TICKER].count == D("0.30")
    assert new.state == "pending" and new.remaining == D("0.70")  # was trimmed to 0 and killed
    assert replay.account.reserved[new.oid] == D("0.70") * new.per_contract


def test_r4_the_matched_baseline_of_the_frozen_variant_may_be_scored_in_test(tmp_path: Path) -> None:
    """10: 'In TEST, only the baseline matching the frozen variant runs' (MB-J for a join variant)."""
    research = research_copy(tmp_path)
    freeze(research)  # A1 frozen, E1 2026-12-01, 28 days
    assert check_scoring_allowed(ReplayConfig("MB-J", "TEST", date(2026, 12, 1), 28), research).freeze
    with pytest.raises(FreezeError, match="matched baseline"):
        check_scoring_allowed(ReplayConfig("MB-I", "TEST", date(2026, 12, 1), 28), research)


def test_r5_a_freeze_without_every_parameter_is_refused(tmp_path: Path) -> None:
    research = research_copy(tmp_path)
    freeze(research, parameters={})
    with pytest.raises(FreezeError, match="every frozen parameter"):
        check_scoring_allowed(ReplayConfig("A1", "TEST", date(2026, 12, 1), 28, epsilon_ms=0), research)
    freeze(research)
    with pytest.raises(FreezeError, match="epsilon_ms"):
        check_scoring_allowed(ReplayConfig("A1", "TEST", date(2026, 12, 1), 28, epsilon_ms=0), research)


def test_r5_primary_and_pessimistic_test_runs_use_the_frozen_latency_and_stresses_are_labelled(tmp_path: Path) -> None:
    research = research_copy(tmp_path)
    freeze(research)  # parameters carry latency_ms=1000
    for config in (ReplayConfig("A1", "TEST", date(2026, 12, 1), 28, latency_ms=100),
                   ReplayConfig("A1", "TEST", date(2026, 12, 1), 28, latency_ms=500, model="pessimistic")):
        with pytest.raises(FreezeError, match="latency_ms"):
            check_scoring_allowed(config, research)
    stress = ReplayConfig("A1", "TEST", date(2026, 12, 1), 28, latency_ms=100, latency_stress=True)
    assert check_scoring_allowed(stress, research).freeze
    assert stress.kind == "latency_stress" and "LATENCY STRESS" in stress.label() and "L=100 ms" in stress.label()
    assert stress.parameters()["kind"] == "latency_stress"
    with pytest.raises(ValueError, match="one kind"):
        ReplayConfig("A1", "TEST", date(2026, 12, 1), 28, model="pessimistic", unfunded=True)


def test_r5_the_freeze_pins_the_replay_code_its_time_and_its_published_hash(tmp_path: Path) -> None:
    research = research_copy(tmp_path)
    test = ReplayConfig("A1", "TEST", date(2026, 12, 1), 28)
    freeze(research, code_sha256={**code_hashes(), "kalshi_familya.py": "0" * 64})
    with pytest.raises(FreezeError, match="code_sha256"):
        check_scoring_allowed(test, research)
    freeze(research, frozen_at="2026-11-30T23:30:00+00:00")  # only 30 minutes before E1
    with pytest.raises(FreezeError, match="frozen_at"):
        check_scoring_allowed(test, research)
    freeze(research, log_hash=False)  # FREEZE.sha256 regenerated, but the hash is not in the work log
    with pytest.raises(FreezeError, match="WORKLOG"):
        check_scoring_allowed(test, research)
    freeze(research)
    permit = check_scoring_allowed(test, research)
    with pytest.raises(FreezeError, match="permit"):
        FamilyAReplay(test, Coverage())  # no TEST account without the gate
    with pytest.raises(FreezeError, match="permit"):
        FamilyAReplay(ReplayConfig("A1", "TEST", date(2026, 12, 1), 28, model="pessimistic"), Coverage(),
                      permit=permit)  # a permit is for one config
    assert FamilyAReplay(test, Coverage(), permit=permit).config == test


def test_train_and_val_are_seven_days_and_test_twenty_eight() -> None:
    with pytest.raises(FreezeError, match="exactly 7"):
        check_scoring_allowed(ReplayConfig("A1", "TRAIN", DAY, 3), RESEARCH)
    with pytest.raises(FreezeError, match="exactly 28"):
        check_scoring_allowed(ReplayConfig("A1", "TEST", date(2026, 12, 1), 7), RESEARCH)


def test_r6_the_unfunded_diagnostic_runs_past_twenty_five_dollars_and_says_so() -> None:
    tickers = tuple(f"KXT{index:02d}-26OCT21-T1" for index in range(45))
    coverage = Coverage()
    coverage.exchange.add(int(START - 86400), int(START + 40 * 86400))
    for ticker in tickers:
        coverage.watched[ticker].add(START - 86400, START + 40 * 86400)
    replay = FamilyAReplay(ReplayConfig("A1", "TRAIN", DAY, 1, unfunded=True), coverage)
    replay.on_series_fee_changes([], START - 600)
    for ticker in tickers:
        series = ticker.split("-")[0]
        market(replay, ticker, f"{series}-26OCT21", series)
        book(replay, START - 10, [("0.62", "5.00")], [("0.35", "10.00")], ticker=ticker)
    replay.on_book_unchanged(tickers[0], START + 0.5)
    assert replay.counts["quotes_sent"] == 45
    for ticker in tickers:
        book(replay, START + 2, [("0.62", "5.00")], [("0.35", "10.00")], ticker=ticker)
    for ticker in tickers:  # 45 x $0.62 = $27.90 > $25: raised LimitBreach('Simulated cash went negative')
        replay.on_print(sell_yes(ticker, START + 3, "10", trade_id=f"x-{ticker}"))
    assert replay.counts["fills"] == 45 and replay.account.cash < 0
    for ticker in tickers:
        settle(replay, START + 40 * 3600 + 600, "yes", ticker=ticker)
    result = replay.finish(START + 40 * 3600 + 700)
    assert "UNFUNDED diagnostic" in result["label"] and result["run_kind"] == "unfunded"
    assert result["accounting"]["reconciled"] is True


def test_r7_a_cluster_belongs_to_one_block_the_date_of_its_last_settlement() -> None:
    other = "KXHIGHNY-26OCT21-T78"  # the same TEMP_NYC|26OCT21 cluster as TICKER
    replay = simulated("A1", tickers=(TICKER, other))
    for ticker in (TICKER, other):
        book(replay, START - 10, [("0.62", "1.00")], [("0.35", "10.00")], ticker=ticker)
    book(replay, START + 2, [("0.62", "1.00")], [("0.35", "10.00")])
    replay.on_print(sell_yes(TICKER, START + 3, "5", trade_id="a"))
    book(replay, START + 50, [("0.62", "1.00")], [("0.35", "10.00")], ticker=other)
    replay.on_market_row({"ticker": other, "volume_24h_fp": "100.00"}, START + 50, full=False, sweep=True)
    book(replay, START + 62, [("0.62", "1.00")], [("0.35", "10.00")], ticker=other)
    replay.on_print(sell_yes(other, START + 63, "5", trade_id="b"))
    assert replay.account.positions[TICKER].count == 1 and replay.account.positions[other].count == 1
    settle(replay, START + 40 * 3600 + 300, "yes")  # New York 2026-10-21
    settle(replay, START + 2 * 86400 + 6 * 3600 + 300, "yes", ticker=other)  # New York 2026-10-22
    result = replay.finish(START + 3 * 86400)
    assert result["settlement_blocks"] == 1 and list(result["by_block"]) == ["2026-10-22"]  # was 2 blocks
    assert D(result["by_block"]["2026-10-22"]) == D("0.76")


def test_r7_unresolved_positions_stay_out_of_the_blocks_and_extend_the_days_to_the_limit() -> None:
    replay = simulated("A1")
    book(replay, START - 10, [("0.62", "1.00")], [("0.35", "10.00")])
    book(replay, START + 2, [("0.62", "1.00")], [("0.35", "10.00")])
    replay.on_print(sell_yes(TICKER, START + 3, "5"))
    result = replay.finish(START + 20 * 86400)  # the tape outlives the 14-day resolution limit
    assert result["settlement_blocks"] == 0 and result["by_block"] == {}
    assert D(result["unresolved_pnl_usd_outside_blocks"]) == D("-0.62")
    assert D(result["days"]) == 15  # 13: D runs to the follow-up end when a position never settled (was 1)


def test_r8_a_quiet_book_written_before_the_lookback_still_counts_when_calls_say_unchanged(tmp_path: Path) -> None:
    """4/12: the latest book received by t; the recorder writes a book only when it changes."""
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
    book_at = START - 1200  # the last CHANGE was 20 minutes before 00:00 UTC
    clock["at"] = book_at
    store.append("books", "book", {"ticker": TICKER, "orderbook_fp": orderbook([("0.62", "1.00")], [("0.35", "9")])},
                 book_at)
    for second in range(int(book_at) + 60, int(START + 3600), 60):
        clock["at"] = second
        store.append("book_calls", "book_call", {"unchanged": [TICKER], "changed": [], "missing": []}, second - 5)
        if (second - int(book_at)) % 300 == 0:
            store.append("markets", "sweep", {"rows": [{"ticker": TICKER, "dyn": {"volume_24h_fp": "80.00"}}]},
                         second - 10)
    clock["at"] = START + 2 * 86400
    store.close()
    result = run_replay(root, ReplayConfig("A1", "TRAIN", DAY, 7), RESEARCH)
    assert result["counts"].get("quotes_sent", 0) >= 1  # was 0: no book was ever loaded


def test_r10_reconciliation_catches_a_position_ledger_that_disagrees_with_cash() -> None:
    from nightcrawler.kalshi_familya import LimitBreach

    replay = simulated("A1")
    book(replay, START - 10, [("0.62", "1.00")], [("0.35", "10.00")])
    book(replay, START + 2, [("0.62", "1.00")], [("0.35", "10.00")])
    replay.on_print(sell_yes(TICKER, START + 3, "5"))
    assert D(replay.reconcile()["open_exposure"]) == D("0.62")
    replay.account.positions[TICKER].lots[0].cost += D("0.0100")  # an injected ledger defect
    with pytest.raises(LimitBreach, match="inventory"):
        replay.reconcile()  # only cash = 25 + fill cash + payouts was checked
    replay.account.positions[TICKER].lots[0].cost -= D("0.0100")
    replay.account.fees += D("0.0100")  # a fee total that no fill produced
    with pytest.raises(LimitBreach, match="fees"):
        replay.reconcile()


def test_block_prints_count_toward_the_twenty_four_hour_volume_fallback() -> None:
    replay = simulated("A1")
    state = replay.markets[TICKER]
    state.sweep_at = START - 3600  # the sweep is too old: the fallback sums recorded trades
    replay.on_print(sell_yes(TICKER, START - 120, "30", block=True))
    assert state.volume_24h(START) == D("30")


def test_a_quote_outside_the_ten_best_bids_at_arrival_assumes_the_queue_unknown() -> None:
    replay = simulated("A1")
    book(replay, START - 10, [("0.62", "5.00")], [("0.35", "10.00")])  # the decision joins at 0.62
    above = [(f"0.{63 + index}", "1.00") for index in range(10)]
    book(replay, START + 0.5, above + [("0.62", "5.00")], [("0.25", "10.00")])  # 0.62 is now 11th
    book(replay, START + 2, above + [("0.62", "5.00")], [("0.25", "10.00")])  # confirms, still outside
    order = order_of(replay)
    assert order.state == "resting" and order.queue.is_infinite()
    replay.on_print(sell_yes(TICKER, START + 3, "5"))
    assert order.remaining == 1  # was filled with Q = 0
    book(replay, START + 4, [("0.63", "1.00"), ("0.62", "2.00")], [("0.25", "10.00")])  # q is visible again
    assert order.queue == 2
    replay.on_print(sell_yes(TICKER, START + 5, "2.5"))
    assert order.remaining == D("0.50")


def test_a_replacement_is_not_re_checked_against_books_that_arrive_during_its_cancel() -> None:
    replay = simulated("A1")
    book(replay, START - 10, [("0.62", "5.00")], [("0.35", "10.00")])
    book(replay, START + 30, [("0.63", "5.00")], [("0.35", "10.00")])
    replay.on_market_row({"ticker": TICKER, "volume_24h_fp": "100.00"}, START + 40, full=False, sweep=True)
    replay.on_book_unchanged(TICKER, START + 60.5)  # the 00:01 decision reprices to 0.63
    book(replay, START + 60.7, [("0.63", "5.00")], [("0.25", "10.00")])  # a 12-cent spread before the ack
    replay.on_book_unchanged(TICKER, START + 61.5)
    assert replay.counts["replacement_orders"] == 1 and replay.counts.get("replacement_skipped", 0) == 0
