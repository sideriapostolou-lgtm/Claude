"""The practice LIP desk (nightcrawler.lip_desk): pretend money only. It must reproduce the rewards review's simulator
exactly (a recorded FX window and the review's own results, tests/fixtures/lip_desk_window.json.gz), score with the
exact LIP formula, and apply each pre-registered fill and quoting rule (research/kalshi_rewards/PREREG.md section 8)."""

from __future__ import annotations

import gzip
import json
import math
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from nightcrawler import lip_desk as D
from nightcrawler import lip_score as L
from nightcrawler.lip_feed import FX, SERIES

FIXTURE = Path(__file__).parent / "fixtures" / "lip_desk_window.json.gz"
T0 = 1_791_918_900.0  # 2026-10-13 19:15:00 UTC, a Tuesday
EUR = "KXEURUSD15M-26OCT131530-30"
EUR_ID = SERIES["KXEURUSD15M"].hermes_id
YES_BOOK = [("0.41", 30), ("0.40", 50), ("0.39", 400)]  # Reference 40 (30 + 50 >= 60), Target reached at 39
NO_BOOK = [("0.57", 80), ("0.56", 400)]  # Reference 57


def iso(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).isoformat().replace("+00:00", "Z")


class Tape:
    """Recorder-shaped records for one window: a program, polls, prints, Pyth prices and the result."""

    def __init__(self, ticker: str = EUR, start: float = T0, end: float = T0 + 900, reward: float = 50.0) -> None:
        self.ticker, self.start, self.end = ticker, start, end
        self.seq = 0
        self.records: list[dict[str, Any]] = []
        self.add(start - 600, {"kind": "incentives", "body": {"incentive_programs": [{
            "incentive_type": "liquidity", "market_ticker": ticker, "start_date": iso(start), "end_date": iso(end),
            "period_reward": round(reward * 10000), "target_size_fp": "300.00", "discount_factor_bps": 5000,
            "id": f"p-{ticker}"}]}})

    def add(self, at: float, payload: dict[str, Any]) -> None:
        self.seq += 1
        self.records.append({"at": at, "seq": self.seq, **payload})

    def poll(self, at: float, yes: Any = YES_BOOK, no: Any = NO_BOOK) -> None:
        self.add(at, {"kind": "book", "ticker": self.ticker, "requested_at": at, "received_at": at,
                      "orderbook_fp": {"yes_dollars": [[p, str(s)] for p, s in yes],
                                       "no_dollars": [[p, str(s)] for p, s in no]}})

    def polls(self, start: float, end: float, every: float = 5.0) -> None:
        at = start
        while at < end:
            self.poll(at)
            at += every

    def sell_yes(self, at: float, price: str, size: float) -> None:
        """A taker selling YES: it hits YES bids at ``price``."""
        self.add(at, {"kind": "trades", "rows": [{"ticker": self.ticker, "trade_id": f"t{self.seq}",
                                                  "created_time": iso(at), "count_fp": str(size),
                                                  "taker_outcome_side": "no", "yes_price_dollars": price}]})

    def pyth(self, at: float, price: float) -> None:
        self.add(at, {"kind": "updates", "lane": "pyth", "columns": ["id", "price", "expo", "received_at"],
                      "rows": [[EUR_ID, str(round(price * 1e5)), -5, at]]})

    def result(self, outcome: str = "no") -> None:
        self.add(self.end + 20, {"kind": "settlement", "rows": [{"ticker": self.ticker, "result": outcome}]})


def run(tape: Tape, policies: tuple[D.Policy, ...] = (D.POLICIES[0],), models: tuple[str, ...] = ("timed",),
        **options: Any) -> tuple[D.LipDesk, list[dict[str, Any]]]:
    options.setdefault("accounts", ())
    return D.replay(tape.records, policies=policies, models=models, **options)


def row_of(rows: list[dict[str, Any]], policy: str = "ref_stop5", model: str = "timed",
           account: str | None = None) -> dict[str, Any]:
    return next(row for row in rows if row.get("policy") == policy and row.get("model") == model
                and row.get("account") == account)


# ---------------------------------------------------------------------- the review's simulator, reproduced
def test_a_recorded_fx_window_reproduces_the_reviews_simulator() -> None:
    doc = json.loads(gzip.decompress(FIXTURE.read_bytes()))
    stop = float(doc["stop_s"])
    policies = (D.Policy("ref_stop5", "ref", 10, stop), D.Policy("ref_close", "ref", 10, 0.0),
                D.Policy("best_stop5", "best", 10, stop))
    _desk, rows = D.replay(doc["records"], policies=policies, accounts=())
    assert len(rows) == 6 and not any(row.get("void") for row in rows)
    pairs = {"gross_raw_usd": "gross_raw", "reward_usd": "gross_paid", "contracts": "contracts",
             "cross_contracts": "c_cross", "at_contracts": "c_at", "through_contracts": "c_through",
             "fill_settle_usd": "fill_pnl_settle", "fill_m60_usd": "fill_pnl_m60", "net_settle_usd": "net_settle",
             "net_m60_usd": "net_m60", "orders_placed": "orders_placed", "orders_cancelled": "orders_cancelled"}
    for row in rows:
        expected = doc["expected"][f"{row['policy']}|{row['model']}"]
        for ours, theirs in pairs.items():
            assert row[ours] == pytest.approx(expected[theirs], abs=1e-3), (row["policy"], row["model"], ours)
    assert row_of(rows, "best_stop5")["contracts"] > row_of(rows, "ref_stop5")["contracts"] > 0


def test_float_scorer_matches_the_exact_formula_on_random_books() -> None:
    rng = random.Random(7)
    for _ in range(300):
        levels = tuple(sorted(((price, float(rng.choice([5, 20, 60, 150, 400])))
                               for price in rng.sample(range(20, 80), rng.randint(1, 8))), reverse=True))
        target = rng.choice([100.0, 300.0, 1000.0])
        price, size = rng.randint(15, 85), float(rng.choice([1, 10, 25]))
        ok, reference, total, mine = D.side_eval(levels, target, D.df_powers(0.5), price, size)
        exact = L.score_side([L.Bid(L.YES, f"0.{p:02d}", s) for p, s in levels] + [L.Bid(L.YES, f"0.{price:02d}",
                                                                                         size, L.US)],
                             L.YES, target, "0.5")
        assert ok == exact.qualified
        if ok:
            assert reference is not None and exact.reference_price == L.frac(reference) / 100
            assert total == pytest.approx(float(sum(exact.raw.values())))
            assert mine == pytest.approx(float(exact.raw.get(L.US, 0)))


# ---------------------------------------------------------------------- the fill rules
def test_back_of_the_queue_then_prints_at_our_price_and_through_it() -> None:
    tape = Tape()
    tape.polls(T0 + 0.5, T0 + 900)
    tape.sell_yes(T0 + 2, "0.40", 30)  # eats 30 of the 50 ahead of us: no fill
    tape.sell_yes(T0 + 3, "0.40", 25)  # the last 20 ahead, then 5 of ours
    tape.sell_yes(T0 + 3.5, "0.39", 7)  # a taker swept through our 40: the other 5 fill
    tape.result("no")
    _desk, rows = run(tape)
    row = row_of(rows)
    assert (row["at_contracts"], row["through_contracts"], row["cross_contracts"]) == (5.0, 5.0, 0.0)
    assert row["contracts"] == 10.0 and row["fill_settle_usd"] == pytest.approx(-4.0)  # 10 YES at 40c, NO won
    assert row["reward_usd"] > 0 and row["share_quoted"] > 0.6


def test_a_crossing_bid_fills_a_stale_quote_in_proportion_to_its_exposure() -> None:
    tape = Tape()
    tape.polls(T0 + 0.5, T0 + 10)  # we rest YES at 40 from T0 + 0.75
    tape.poll(T0 + 10.5, YES_BOOK, [("0.60", 25), ("0.57", 80), ("0.56", 400)])  # a NO bid at 60 crosses our 40
    tape.polls(T0 + 11, T0 + 900)
    tape.result("yes")
    _desk, rows = run(tape)
    row = row_of(rows)
    assert row["cross_contracts"] == 10.0  # live the whole interval since the poll before: the full 10 (of 25)
    assert row["fill_settle_usd"] == pytest.approx(6.0)  # bought YES at 40c, YES won


def test_fee_model_spares_a_crossing_that_would_not_pay_the_taker_fee() -> None:
    tape = Tape()
    tape.polls(T0 + 0.5, T0 + 10)
    # The crossing NO bid at 60 sits at the new book's mid (fair YES 40.5c): the crosser gains 0.5c, under the fee.
    tape.poll(T0 + 10.5, [("0.41", 30), ("0.40", 50), ("0.39", 400)], [("0.60", 25), ("0.56", 400)])
    tape.polls(T0 + 11, T0 + 900)
    tape.result("yes")
    _desk, rows = run(tape, models=("timed", "fee_timed"))
    assert row_of(rows, model="timed")["cross_contracts"] == 10.0
    assert row_of(rows, model="fee_timed")["cross_contracts"] == 0.0


def test_post_only_and_the_guards() -> None:
    tape = Tape()
    # The NO side never reaches the Target: no quote at all (it would score nothing).
    tape.polls(T0 + 0.5, T0 + 900)
    for record in tape.records:
        if record.get("kind") == "book":
            record["orderbook_fp"]["no_dollars"] = [["0.57", "80"]]
    tape.result("no")
    _desk, rows = run(tape)
    assert row_of(rows)["orders_placed"] == 0 and row_of(rows)["reward_usd"] == 0


def test_the_stop_cancels_300_s_before_the_close_and_to_the_close_keeps_quoting() -> None:
    tape = Tape()
    tape.polls(T0 + 0.5, T0 + 900)
    tape.sell_yes(T0 + 700, "0.39", 50)  # after the 5-minute stop: only the to-the-close policy is hit
    tape.result("no")
    _desk, rows = run(tape, policies=(D.POLICIES[0], D.POLICIES[1]))
    assert row_of(rows, "ref_stop5")["contracts"] == 0.0
    assert row_of(rows, "ref_close")["through_contracts"] == 10.0
    assert row_of(rows, "ref_close")["reward_usd"] >= row_of(rows, "ref_stop5")["reward_usd"]


# ---------------------------------------------------------------------- the Pyth policy
def test_pyth_pull_cancels_the_stale_side_before_it_is_picked_off() -> None:
    tape = Tape()
    tape.polls(T0 + 0.5, T0 + 900, every=2.0)  # polls at .5, 2.5, ..., 20.5, 22.5, ...
    for step in range(1800):
        at = T0 + step * 0.5
        tape.pyth(at, 1.16000 if at < T0 + 20.1 else 1.16010)
    tape.pyth(T0 + 20.1, 1.16010)  # +0.86 bp: our NO bid at 57 (a YES offer at 43) is now too cheap
    crossing = [("0.43", 25), ("0.41", 30), ("0.40", 50), ("0.39", 400)]  # a YES bid at 43 takes NO at 57
    tape.poll(T0 + 20.9, crossing, NO_BOOK)
    tape.result("yes")
    pull = D.Policy("ref_pyth_pull", "ref", 10, 300, pyth_pull=True)
    desk, rows = run(tape, policies=(D.POLICIES[0], pull))
    plain, pulled = row_of(rows, "ref_stop5"), row_of(rows, "ref_pyth_pull")
    assert plain["cross_contracts"] == 10.0  # the plain Reference quote was picked off
    assert pulled["cross_contracts"] == 0.0  # pulled at 20.35; the unchanged book at 20.5 did not bring it back
    assert pulled["pyth_active"] is True and pulled["pyth_share"] > 0.9
    assert pulled["orders_cancelled"] > plain["orders_cancelled"] and desk.counters.pyth > 0
    assert pulled["share_quoted"] > 0.6  # it came back PULL_HOLD_S later and quoted the rest of the window


def test_the_pyth_policy_never_quotes_without_pyth_and_counts_as_inactive() -> None:
    tape = Tape()
    tape.polls(T0 + 0.5, T0 + 900)
    tape.result("no")
    pull = D.Policy("ref_pyth_pull", "ref", 10, 300, pyth_pull=True)
    _desk, rows = run(tape, policies=(D.POLICIES[0], pull))
    assert row_of(rows, "ref_pyth_pull")["orders_placed"] == 0
    assert row_of(rows, "ref_pyth_pull")["pyth_active"] is False
    card = D.scorecard(rows)
    fx = next(row for row in card if row["policy"] == "ref_pyth_pull" and row["family"] == FX)
    assert fx["periods"] == 0 and fx["inactive_periods"] == 1


# ---------------------------------------------------------------------- accounts
def test_a_cash_carrying_account_locks_cash_and_settles_it() -> None:
    tape = Tape()
    tape.polls(T0 + 0.5, T0 + 900)
    tape.sell_yes(T0 + 3.5, "0.39", 7)
    tape.result("no")
    plan = D.AccountPlan("A45", ("KXEURUSD15M",), 45.0)
    desk, rows = run(tape, accounts=(plan,))
    account = next(item for item in desk.accounts if item.policy.name == "ref_stop5")
    own = row_of(rows, account="A45:ref_stop5")
    assert own["contracts"] == 7.0
    assert account.equity() == pytest.approx(45.0 + own["fill_settle_usd"] + own["reward_usd"])
    assert account.row()["periods"] == 1 and account.low <= 45.0


def test_an_account_cannot_rest_more_than_its_cash() -> None:
    tape = Tape()
    tape.polls(T0 + 0.5, T0 + 900)
    tape.result("no")
    plan = D.AccountPlan("A5", ("KXEURUSD15M",), 5.0)
    desk, _rows = run(tape, accounts=(plan,))
    tape2 = Tape()
    tape2.polls(T0 + 0.5, T0 + 3)
    desk2 = D.LipDesk(policies=(D.POLICIES[0],), models=("timed",), accounts=(plan,))
    desk2.feed(tape2.records)
    desk2.advance(T0 + 2)
    sim = next(sim for window in desk2.windows.values() for sim in window.sims if sim.account is not None)
    resting = [order for order in sim.orders if order is not None]
    assert sum(order.price * order.left / 100 for order in resting) <= 5.0 + 1e-9
    assert desk.accounts[0].equity() == pytest.approx(5.0 + desk.accounts[0].reward)


# ---------------------------------------------------------------------- void windows
@pytest.mark.parametrize(("shape", "reason"), [("no_first_poll", "no_first_poll"), ("gap", "poll_gap"),
                                               ("no_result", "no_result"), ("recorder_gap", "recorder_gap")])
def test_incomplete_windows_are_void(shape: str, reason: str) -> None:
    tape = Tape()
    if shape == "no_first_poll":
        tape.polls(T0 + 30, T0 + 900)
    elif shape == "gap":
        tape.polls(T0 + 0.5, T0 + 300)
        tape.polls(T0 + 330, T0 + 900)
    else:
        tape.polls(T0 + 0.5, T0 + 900)
    if shape != "no_result":
        tape.result("no")
    if shape == "recorder_gap":
        tape.add(T0 + 400, {"kind": "gap", "gap_lane": "trades", "from": T0 + 100, "to": T0 + 160,
                            "cause": "trade_page_failed_429"})
    desk, rows = run(tape)
    assert rows == [{"ticker": EUR, "series": "KXEURUSD15M", "group": FX, "open": T0, "close": T0 + 900,
                     "day": "2026-10-13", "void": reason}]
    assert desk.counters.void == 1


def test_a_window_waits_for_its_result_and_its_marks() -> None:
    tape = Tape()
    tape.polls(T0 + 0.5, T0 + 900)
    desk = D.LipDesk(policies=(D.POLICIES[0],), models=("timed",), accounts=())
    desk.feed(tape.records)
    assert desk.advance(T0 + 950) == []  # closed, no result yet
    tape.result("yes")
    desk.feed(tape.records[-1:])
    assert desk.advance(T0 + 955) == [] and len(desk.advance(T0 + 965)) == 1  # the 60 s mark after the close
    assert desk.open_windows() == []


def test_a_window_that_began_before_the_desk_started_is_void() -> None:
    tape = Tape()
    tape.polls(T0 + 0.5, T0 + 900)
    tape.result("no")
    desk = D.LipDesk(policies=(D.POLICIES[0],), models=("timed",), accounts=(), started_at=T0 + 100)
    desk.feed([record for record in tape.records if record["at"] >= T0 + 100 or record["kind"] == "incentives"])
    rows = desk.advance(math.inf)
    assert rows[0]["void"] == "joined_late"


def test_late_events_are_counted_not_used() -> None:
    tape = Tape()
    tape.polls(T0 + 0.5, T0 + 20)
    desk = D.LipDesk(policies=(D.POLICIES[0],), models=("timed",), accounts=())
    desk.feed(tape.records)
    desk.advance(T0 + 30)
    late = Tape()
    late.sell_yes(T0 + 10, "0.39", 5)
    desk.feed(late.records[1:])
    assert desk.counters.late_records == 1


# ---------------------------------------------------------------------- the scorecard
def test_scorecard_sums_and_ranges() -> None:
    rows = []
    for index, net in enumerate((-2.0, -1.0, 0.5, -3.5)):
        rows.append({"day": "2026-10-13", "policy": "ref_stop5", "model": "timed", "group": FX, "account": None,
                     "contracts": 10.0, "cross_contracts": 5.0 + index, "reward_usd": 1.5, "fill_m60_usd": net - 1.0,
                     "fill_settle_usd": net - 1.5, "net_m60_usd": net + 0.5, "net_settle_usd": net,
                     "pyth_active": None})
    rows.append({"day": "2026-10-13", "group": FX, "void": "poll_gap"})
    rows.append({**rows[0], "account": "A45:ref_stop5"})
    card = D.scorecard(rows)
    fx = next(row for row in card if row["family"] == FX)
    assert (fx["periods"], fx["reward_usd"], fx["contracts"], fx["net_settle_usd"]) == (4, 6.0, 40.0, -6.0)
    assert fx["cross_share"] == pytest.approx(26 / 40) and fx["void_periods_day"] == 1
    assert fx["mean_net_settle_usd"] == -1.5
    low, high = fx["range95_settle_usd"]
    assert low < -1.5 < high and fx["per_day_settle_usd"] == pytest.approx(-1.5 * D.FX_PERIODS_PER_DAY)
    assert next(row for row in card if row["family"] == "all")["periods"] == 4
    text = D.scorecard_text(card)
    assert "ref_stop5" in text and "pretend money" in text


def test_the_pre_registered_policies_and_accounts() -> None:
    assert [(p.name, p.place, p.size, p.stop_s, p.pyth_pull) for p in D.POLICIES] == [
        ("ref_stop5", "ref", 10.0, 300.0, False), ("ref_close", "ref", 10.0, 0.0, False),
        ("best_stop5", "best", 10.0, 300.0, False), ("ref_pyth_pull", "ref", 10.0, 300.0, True)]
    assert D.FILL_MODELS == ("timed", "fee_timed")
    assert [(a.name, a.series, a.start_cash, a.shard) for a in D.ACCOUNTS] == [
        ("A45", ("KXEURUSD15M",), 45.0, 0),
        ("A250", ("KXEURUSD15M", "KXGBPUSD15M", "KXUSDJPY15M", "KXAUDUSD15M", "KXUSDCAD15M"), 250.0, 0)]
    assert SERIES["KXEURUSD15M"].pull_bps == 0.5 and SERIES["KXNATGAS15M"].pull_bps == 1.0


def test_a_long_running_desk_forgets_finished_markets() -> None:
    desk = D.LipDesk(policies=(D.POLICIES[0],), models=("timed",), accounts=())
    for day in range(4):
        tape = Tape(ticker=f"KXEURUSD15M-26OCT1{3 + day}1530-30", start=T0 + day * 86_400,
                    end=T0 + day * 86_400 + 900)
        tape.polls(tape.start + 0.5, tape.end)
        tape.result("no")
        desk.feed(tape.records)
        desk.advance(tape.end + 120)
    assert desk.counters.settled == 4
    assert len(desk.books) <= 3 and len(desk.facts) <= 3 and len(desk.seen_programs) <= 3
