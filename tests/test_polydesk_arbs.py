"""The no-lose desk (nightcrawler.polydesk, PAPER only): a question whose every answer can be bought for under $1 in
total, the taker fee on each leg included, pays exactly $1 at settlement whatever happens. Found once per group per
UTC day, bought on paper as one set, checked again the next round, settled into its own tally and flagged loudly when
a set pays back less than it cost. Never a real order; never part of the near-certain rule's record. No network."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nightcrawler import pagestate
from nightcrawler import polydesk as P
from nightcrawler.config import Settings
from tests.test_polydesk import NOW, _market
from tests.test_polydesk_live import FakeExchange, FakeLedger, _live_settings
from tests.test_polydesk_safety import LEADER, RAYO, Gateway2, _answers, _three_way

GAME = ("ebfsa-sas-roma-dh4", "eBattles: Sassuolo vs. Roma", -130, "3'", ("sas", "draw", "roma"))
LEGS = [f"atc-ebfsa-sas-roma-dh4-{o}" for o in GAME[4]]
#: Every answer at 0.28 / 0.30: the YES bids add up to 0.84 (a coherent book), the asks to 0.90.
CHEAP = {slug: (0.28, 0.30) for slug in LEGS}
FEE = 0.0695 * 0.30 * 0.70  # the venue's taker fee on one contract at 0.30
TOTAL = 3 * (0.30 + FEE)  # about 0.944: one set pays $1.00


@pytest.fixture
def gw(monkeypatch: pytest.MonkeyPatch) -> Gateway2:
    g = Gateway2()
    monkeypatch.setattr(P, "_get", g.get)
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    return g


def _paper(tmp_path: Path) -> Settings:
    return Settings.from_env({"DATA_DIR": str(tmp_path)})


def _desk(settings: Settings, ledger: FakeLedger, ex: FakeExchange | None = None) -> P.PolyDesk:
    return P.PolyDesk(settings, ledger=ledger, client_factory=ex or FakeExchange(cash=25.0))


def _legs(desk: P.PolyDesk) -> dict[str, dict[str, Any]]:
    return {s: p for s, p in desk.state["positions"].items() if p.get("arb_key")}


def _kinds(ledger: FakeLedger, kind: str) -> list[dict[str, Any]]:
    return [payload for k, payload in ledger.receipts if k == kind]


def _game(gw: Gateway2, quotes: dict[str, tuple[float, float]] | None = None) -> None:
    gw.events = [_three_way(*GAME)]
    gw.quotes = dict(quotes or CHEAP)
    gw.extra = {LEGS[0]: {"askShares": "120"}, LEGS[1]: {"askShares": "40"}, LEGS[2]: {"askShares": "75"}}


def test_an_arb_is_found_and_paper_bought_once(gw: Gateway2, tmp_path: Path) -> None:
    _game(gw)
    ledger = FakeLedger()
    desk = _desk(_paper(tmp_path), ledger)
    assert desk.poll(NOW)["arbs"] == 1
    (arb,) = desk.state["arbs"]
    assert arb["kind"] == "game" and arb["name"] == "eBattles: Sassuolo vs. Roma" and arb["n"] == 3
    assert arb["total"] == pytest.approx(TOTAL) and arb["edge"] == pytest.approx(1 - TOTAL)
    assert arb["min_size"] == 40.0 and arb["still_there"] is None
    assert [leg["slug"] for leg in arb["legs"]] == LEGS
    assert all(leg["ask"] == 0.30 and leg["fee"] == pytest.approx(FEE) for leg in arb["legs"])
    legs = _legs(desk)
    assert set(legs) == set(LEGS) and len(desk.state["positions"]) == 3  # the rule bought nothing (no leader)
    for p in legs.values():
        assert p["arb_key"] == arb["id"] and p["live"] is False and p["side"] == "long"
        assert p["shares"] == P.ARB_PAPER_SETS and p["p_in"] == 0.30 and p["fee_usd"] == pytest.approx(FEE)
    assert arb["set"]["bought"] is True and arb["set"]["cost_usd"] == pytest.approx(TOTAL)
    assert desk.state["arb_book"]["sets"] == 1
    assert [e["text"] for e in desk.state["events"] if e["text"].startswith("No-lose")] == [
        "No-lose set found: eBattles: Sassuolo vs. Roma: all 3 answers for $0.94 (pays $1.00)"]
    assert len(_kinds(ledger, "polydesk_arb_seen")) == 1
    # the next round: the same group the same day is not found again, and the set is checked: still buyable
    assert desk.poll(NOW + 60)["arbs"] == 0
    assert len(desk.state["arbs"]) == 1 and desk.state["arbs"][0]["still_there"] is True
    assert len(_kinds(ledger, "polydesk_arb_seen")) == 1 and desk.state["arb_book"]["sets"] == 1
    assert len(_legs(desk)) == 3


def test_a_set_that_moved_by_the_next_round_is_stale(gw: Gateway2, tmp_path: Path) -> None:
    _game(gw)
    desk = _desk(_paper(tmp_path), FakeLedger())
    desk.poll(NOW)
    gw.quotes[LEGS[1]] = (0.30, 0.32)  # one ask went up: the set is no longer there at the price seen
    desk.poll(NOW + 60)
    assert desk.state["arbs"][0]["still_there"] is False
    other = _desk(_paper(tmp_path / "gone"), FakeLedger())
    other.poll(NOW)
    gw.events = []  # the game left the live list before the next look
    other.poll(NOW + 60)
    assert other.state["arbs"][0]["still_there"] is False


@pytest.mark.parametrize("case", ["missing_ask", "missing_quote", "closed_leg", "too_dear", "fees_tip_it_over"])
def test_incomplete_or_dear_groups_are_not_arbs(gw: Gateway2, tmp_path: Path, case: str) -> None:
    _game(gw)
    if case == "missing_ask":
        gw.quotes[LEGS[2]] = (0.28, None)  # type: ignore[assignment]
    elif case == "missing_quote":
        gw.fail = {LEGS[2]}  # the game is cut: two of its three answers quoted
    elif case == "closed_leg":
        gw.extra[LEGS[0]] = {"state": "MARKET_STATE_CLOSED"}
    elif case == "too_dear":
        gw.quotes = {slug: (0.31, 0.33) for slug in LEGS}  # 0.99 before fees
    else:
        gw.quotes = {slug: (0.30, 0.32) for slug in LEGS}  # 0.96 before fees, about 1.005 with them
    ledger = FakeLedger()
    desk = _desk(_paper(tmp_path), ledger)
    assert desk.poll(NOW)["arbs"] == 0
    assert desk.state["arbs"] == [] and not _legs(desk) and not _kinds(ledger, "polydesk_arb_seen")


def test_fees_are_counted_from_the_market(gw: Gateway2, tmp_path: Path) -> None:
    """0.32 three times is 0.96: an arb only when the market charges no taker fee (its own ``feeCoefficient``)."""
    _game(gw, {slug: (0.30, 0.32) for slug in LEGS})
    for m in gw.events[0]["markets"]:
        m["feeCoefficient"] = "0"
    desk = _desk(_paper(tmp_path), FakeLedger())
    desk.poll(NOW)
    (arb,) = desk.state["arbs"]
    assert arb["total"] == pytest.approx(0.96) and all(leg["fee"] == 0.0 for leg in arb["legs"])


def test_a_nested_ladder_is_never_a_set(gw: Gateway2, tmp_path: Path) -> None:
    """'BTC above 82,400 / 82,500 / 82,600' share a question but are not exclusive answers: never a no-lose set."""
    rungs = [f"cpc-btc-above-hr-2026-10-10-0800z-{k}" for k in (82400, 82500, 82600)]
    gw.markets = _answers(rungs, "BTC Price at 4:00AM ET on Sat, Oct 10")
    gw.quotes = {r: (0.20, 0.22) for r in rungs}
    desk = _desk(_paper(tmp_path), FakeLedger())
    desk.poll(NOW)
    assert desk.state["arbs"] == []


def test_a_set_settles_to_about_plus_its_edge(gw: Gateway2, tmp_path: Path) -> None:
    _game(gw)
    ledger = FakeLedger()
    settings = _paper(tmp_path)
    desk = _desk(settings, ledger)
    desk.poll(NOW)
    gw.events = []  # the game is over: off the live list
    gw.settlements = {LEGS[0]: 1.0, LEGS[1]: 0.0, LEGS[2]: 0.0}
    desk.poll(NOW + 3600)
    s = desk.state["arbs"][0]["set"]
    assert s["status"] == "settled" and s["payout_usd"] == pytest.approx(1.0) and s["payout_per_set"] == 1.0
    assert s["pnl_usd"] == pytest.approx(1 - TOTAL)
    book = desk.state["arb_book"]
    assert book == {"sets": 1, "settled_sets": 1, "pnl_usd": pytest.approx(1 - TOTAL), "broken": 0}
    assert not desk.state["positions"] and not _kinds(ledger, "polydesk_arb_broken")
    assert any(e["text"] == "No-lose set paid: eBattles: Sassuolo vs. Roma: $1.00 back for $0.94 (+0.06 $, practice)"
               for e in desk.state["events"])
    # never the near-certain rule's record: no by_rule, no day P&L, no settlement counted, no closed row
    assert desk.state["by_rule"] == {} and desk.state["days"] == {} and desk.state["closed"] == []
    assert desk.state["counters"]["settled"] == 0 and desk.state["counters"]["bought"] == 0
    assert desk.state["guard"]["paper"]["n"] == 0
    panel = P.panel_state(settings, NOW + 3600)
    assert panel["arbs"]["settled_sets"] == 1 and panel["arbs"]["pnl_usd"] == pytest.approx(1 - TOTAL)
    assert panel["paper"]["settled_total"] == 0 and panel["paper"]["pnl_total_usd"] == 0.0


def test_a_broken_set_is_flagged_loudly(gw: Gateway2, tmp_path: Path) -> None:
    """A game the venue cancels with every answer settled at 0 (or a mis-grouped market): the set paid less than
    it cost, which disproves the no-lose claim for that kind of question."""
    _game(gw)
    ledger = FakeLedger()
    desk = _desk(_paper(tmp_path), ledger)
    desk.poll(NOW)
    gw.events = []
    gw.settlements = {slug: 0.0 for slug in LEGS}
    desk.poll(NOW + 3600)
    s = desk.state["arbs"][0]["set"]
    assert s["status"] == "broken" and s["pnl_usd"] == pytest.approx(-TOTAL)
    assert desk.state["arb_book"]["broken"] == 1 and desk.state["arb_book"]["settled_sets"] == 1
    (receipt,) = _kinds(ledger, "polydesk_arb_broken")
    assert receipt["kind"] == "game" and receipt["payout_usd"] == 0.0
    assert [leg["value"] for leg in receipt["legs"]] == [0.0, 0.0, 0.0]
    (said,) = [e for e in desk.state["events"] if e["text"].startswith("No-lose set BROKEN: ")]
    assert said["tone"] == "bad" and "not no-lose for this kind of question" in said["text"]


def test_the_rules_record_never_counts_arb_rows(gw: Gateway2, tmp_path: Path) -> None:
    """The rule's record, guard, lessons, paper cap and one-position-per-game check ignore rows with ``arb_key``."""
    rows = [{"slug": f"s{i}", "won": False, "pnl_usd": -0.3, "p_in": 0.3, "category": "sports", "arb_key": "k",
             "shares": 1.0, "cost_usd": 0.3} for i in range(P.LESSONS_MIN_ROWS + 2)]
    assert P.lessons(rows) == [] and P.worst_row(rows) is None and P._by_rule_from_rows(rows) == {}
    by_rule: dict[str, Any] = {}
    P._tally(by_rule, rows[0], -0.3, False, {})
    assert by_rule == {}
    # an open set in one game, the leader of another: the rule still buys its leader on paper
    gw.events = [_three_way(*GAME), _three_way(*RAYO)]
    gw.quotes = {**CHEAP, **LEADER}
    settings = _paper(tmp_path)
    desk = _desk(settings, FakeLedger())
    desk.poll(NOW)
    rule = {s for s, p in desk.state["positions"].items() if not p.get("arb_key")}
    assert rule == {"atc-lal-ray-ath-ray"} and len(_legs(desk)) == 3
    panel = P.panel_state(settings, NOW)
    assert panel["open"] == 1 and panel["paper"]["open"] == 1 and panel["before_fix"]["paper"]["open"] == 0
    assert [p["question"] for p in panel["positions"]] == ["Rayo vs. Athletic: ray?"]
    assert panel["arbs"]["open_sets"] == 1


def test_no_real_order_is_ever_sent_in_live_mode(gw: Gateway2, tmp_path: Path) -> None:
    """Live mode, a non-sports question (real money may buy those) and a game, both no-lose: paper sets only."""
    bands = [f"tc-temp-nychigh-2026-10-10-{b}" for b in ("lt60f", "gte60lt62f", "gte62lt64f", "gte64f")]
    gw.markets = _answers(bands, "Highest temperature in NYC on Oct 10?") + [_market("btc-x", "crypto", 1800)]
    _game(gw)
    gw.quotes.update({bands[0]: (0.18, 0.20), bands[1]: (0.18, 0.20), bands[2]: (0.23, 0.25),
                      bands[3]: (0.23, 0.25), "btc-x": (0.50, 0.52)})
    ex, ledger = FakeExchange(cash=25.0), FakeLedger()
    desk = _desk(_live_settings(tmp_path), ledger, ex)
    assert desk.state["mode"] == "live"
    assert desk.poll(NOW)["arbs"] == 2
    assert ex.orders == [] and not any(k.startswith("polydesk_order") for k, _ in ledger.receipts)
    assert {a["kind"] for a in desk.state["arbs"]} == {"game", "question"}
    assert set(_legs(desk)) == set(bands) | set(LEGS) and all(not p["live"] for p in _legs(desk).values())
    desk.poll(NOW + 60)
    assert ex.orders == [] and P.real_room(desk.state, desk.settings, NOW)["held_usd"] == 0.0


def test_panel_page_and_plain_sentence(gw: Gateway2, tmp_path: Path) -> None:
    settings = _paper(tmp_path)
    _desk(settings, FakeLedger())
    assert P.panel_state(settings, NOW)["arbs"]["today_seen"] == 0
    assert pagestate._arbs_line(pagestate.polymarket_desk(settings, NOW) or {}) is None  # nothing found: no sentence
    _game(gw)
    desk = _desk(settings, FakeLedger())
    desk.poll(NOW)
    assert pagestate._arbs_line(pagestate.polymarket_desk(settings, NOW) or {}) == (
        "No-lose check (practice): found 1 question whose every answer cost under $1 together today, fees included; "
        "practice bought the set.")
    desk.poll(NOW + 60)
    view = P.panel_state(settings, NOW + 60)["arbs"]
    assert {k: view[k] for k in ("today_seen", "today_bought", "today_checked", "today_still_there", "sets_paper",
                                 "open_sets", "settled_sets", "broken")} == {
        "today_seen": 1, "today_bought": 1, "today_checked": 1, "today_still_there": 1, "sets_paper": 1,
        "open_sets": 1, "settled_sets": 0, "broken": 0}
    assert view["last"] == [{"name": "eBattles: Sassuolo vs. Roma", "total": pytest.approx(TOTAL),
                             "edge": pytest.approx(1 - TOTAL), "min_size": 40.0, "still_there": True}]
    money = pagestate.polymarket_desk(settings, NOW + 60)
    assert money is not None and money["arbs"]["today_still_there"] == 1 and money["arbs"]["last"][0]["min_size"] == 40.0
    assert pagestate._arbs_line(money) == (
        "No-lose check (practice): found 1 question whose every answer cost under $1 together today, fees included; "
        "practice bought the set; 1 was still there at the next look.")
    assert pagestate.plain_event("predict", desk.state["events"][-1]["text"]).startswith(
        "practice found a question whose 3 answers cost $0.94 together and pay $1 whatever happens")
    # junk from the file is never trusted: whole counts, numbers, a name
    junk = pagestate._desk_arbs({"today_seen": "2", "broken": -1, "pnl_usd": "x",
                                 "last": [{"name": 5, "total": 0.9, "edge": 0.1}, {"name": "ok", "total": 0.9,
                                          "edge": 0.1, "min_size": "big", "still_there": "yes"}]},
                                pagestate._Text(settings))
    assert junk["today_seen"] == 0 and junk["broken"] == 0 and junk["pnl_usd"] == 0.0
    assert junk["last"] == [{"name": "ok", "total": 0.9, "edge": 0.1, "min_size": None, "still_there": None}]
    # broken sets are said in the sentence, never hidden
    assert "1 practice set paid back less than it cost" in (pagestate._arbs_line(
        {"arbs": {"today_seen": 2, "today_bought": 2, "broken": 1}}) or "")
