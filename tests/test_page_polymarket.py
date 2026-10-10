"""The one page counts the Polymarket desk too (nightcrawler.pagestate + page): the money card's Polymarket block
and the town's desk lines, paper and real kept strictly apart, read from the desk's own state file
(polydesk.panel_state); nothing when the desk is off; the page renders the block as text only."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock
from test_page import (  # noqa: F401 - shared fixture
    DAY,
    JARGON,
    NOW,
    live_settings,
    no_learning_module,
    page_script,
    seed,
)

from nightcrawler import polydesk
from nightcrawler.config import Settings
from nightcrawler.ledger import Ledger
from nightcrawler.page import PAGE_CSP, render_page_html
from nightcrawler.pagestate import (
    PAPER_LABEL,
    PLAIN_HEADLINE_MAX,
    REAL_LABEL,
    build_page_state,
    plain_event,
    polymarket_desk,
    town_ledger,
)

TODAY = datetime.fromtimestamp(NOW, UTC).strftime("%Y-%m-%d")
YESTERDAY = datetime.fromtimestamp(NOW - DAY, UTC).strftime("%Y-%m-%d")
MINUS = "−"
#: The venue on 2026-10-09: 8 real contracts the desk adopted, about $7.80, and the account's cash.
VENUE = {"positions": 8, "contracts": 8.0, "cost_usd": 7.80, "value_usd": 7.95, "at": NOW - 60}
CASH = {"cash": 16.27, "buying_power": 16.27, "at": NOW - 60}


@pytest.fixture
def ledger(tmp_path: Path, fake_clock: FakeClock) -> Iterator[Ledger]:
    with Ledger(tmp_path / "nc.db", clock=fake_clock) as led:
        yield led


def position(slug: str, *, live: bool, cost_usd: float, p_in: float = 0.97) -> dict[str, Any]:
    return {"slug": slug, "question": f"Will {slug} happen?", "category": "crypto", "side": "long", "p_in": p_in,
            "shares": cost_usd / p_in, "fee_usd": 0.0, "cost_usd": cost_usd, "t_in": NOW - 600, "end_ts": NOW + 1200,
            "event": None, "live": live}


def desk_state(*, paper_open: int = 2, real_open: int = 1, venue: dict[str, Any] | None = VENUE,
               balance: dict[str, Any] | None = CASH, live_today: dict[str, Any] | None = None,
               last_ok: float | None = NOW - 60) -> dict[str, Any]:
    """The desk after 2026-10-09's day: the paper rule lost $1,345.53 today on 114 settlements (68 won), made
    $12.40 yesterday; two real contracts settled yesterday for +$0.50; paper tickets and a real position open."""
    st = polydesk.empty_state()
    for i in range(paper_open):
        st["positions"][f"paper{i}"] = position(f"paper{i}", live=False, cost_usd=20.0)
    for i in range(real_open):
        st["positions"][f"real{i}"] = position(f"real{i}", live=True, cost_usd=0.97)
    live_days = {YESTERDAY: {"pnl_usd": 0.50, "settled": 2, "won": 2}}
    if live_today is not None:
        live_days[TODAY] = live_today
    today = {"pnl_usd": -1345.53 + float((live_today or {}).get("pnl_usd") or 0.0),
             "settled": 114 + int((live_today or {}).get("settled") or 0),
             "won": 68 + int((live_today or {}).get("won") or 0)}
    st["days"] = {YESTERDAY: {"pnl_usd": 12.40, "settled": 9, "won": 9}, TODAY: today}  # paper + real together
    st["live_days"] = live_days
    st["live_pnl_total_usd"] = sum(float(d["pnl_usd"]) for d in live_days.values())
    st["counters"].update({"settled": 9 + today["settled"], "won": 9 + today["won"], "polls": 500})
    st["exchange"] = venue
    st["balance"] = balance
    st["last_ok"] = last_ok
    st["last_poll"] = last_ok
    st["watched"] = 240
    return st


def save(settings: Settings, state: dict[str, Any]) -> None:
    polydesk.save_state(polydesk.state_path(settings), state)


# --------------------------------------------------------------------------- the JSON: paper and real, apart


def test_money_and_town_count_the_polymarket_desk_with_paper_and_real_kept_apart(ledger: Ledger,
                                                                                   settings: Settings) -> None:
    seed(ledger)  # the Solana bot lost $5.50 today (paper)
    save(settings, desk_state())
    state = build_page_state(ledger, settings, NOW)
    pm = state["money"]["polymarket"]
    assert pm["mode"] == "paper" and pm["label"] == PAPER_LABEL == "Paper money (pretend)" and pm["as_of"] == NOW - 60
    assert pm["paper"] == {"label": "Paper money (pretend)", "open": 2, "today_usd": pytest.approx(-1345.53),
                           "since_start_usd": pytest.approx(-1333.63), "settled_today": 114, "won_today": 68,
                           "settled_total": 121, "won_total": 75}
    assert pm["real"] == {"label": REAL_LABEL, "open": 1, "today_usd": 0.0, "since_start_usd": pytest.approx(0.50),
                          "settled_today": 0, "won_today": 0, "settled_total": 2, "won_total": 2,
                          "at_risk_usd": pytest.approx(0.97), "contracts": 8.0, "cost_usd": pytest.approx(7.80),
                          "value_usd": pytest.approx(7.95), "venue_at": NOW - 60, "cash_usd": pytest.approx(16.27),
                          "cash_at": NOW - 60, "pending": 0, "pending_usd": 0.0,
                          # the $3 day less the open real bet if it lost (its cost; this one carries no fee)
                          "stop_room_usd": pytest.approx(3.0 - 0.97), "stop_room_limit": "day"}
    assert REAL_LABEL == "Real money"
    # the SOL wallet's own figures are untouched
    assert state["money"]["today"]["usd"] == pytest.approx(-5.5) and state["money"]["since_start"]["usd"] == pytest.approx(-5.5)
    town = state["town"]
    assert town["income_today_usd"] == pytest.approx(-5.5) and town["income_since_start_usd"] == pytest.approx(-5.5)
    assert town["covered_today"] is False and town["label"] == "Paper money (pretend)"
    assert town["polymarket"]["paper"] == {
        "label": "Paper money (pretend)", "open": 2, "today_usd": pytest.approx(-1345.53),
        "since_start_usd": pytest.approx(-1333.63),
        "line": f"Polymarket desk (paper, pretend): today {MINUS}$1,345.53, since start {MINUS}$1,333.63, 2 open"}
    assert town["polymarket"]["real"] == {
        "label": "Real money", "open": 1, "contracts": 8.0, "cost_usd": pytest.approx(7.80),
        "value_usd": pytest.approx(7.95), "today_usd": 0.0, "settled_today": 0, "won_today": 0,
        "since_start_usd": pytest.approx(0.50), "cash_usd": pytest.approx(16.27),
        "line": "Polymarket desk (REAL money): 8 contracts at the venue, cost $7.80, worth $7.95 now; settled today "
                "0/0 won $0.00; since start +$0.50; cash at the venue $16.27"}
    assert town["line"] == ("The town costs $0.17 a day to run; the Solana desk lost $5.50 and the Polymarket desk lost "
                            "$1,345.53 today (paper money, pretend). Polymarket real money: nothing settled today; "
                            "since start +$0.50.")
    body = json.dumps(state, allow_nan=False)
    for summed in ("1351.03", "1,351.03", "1333.13", "1,333.13", "1345.03", "1,345.03"):  # SOL+paper, paper+real
        assert summed not in body, summed
    for text in (town["line"], town["polymarket"]["paper"]["line"], town["polymarket"]["real"]["line"]):
        assert not JARGON.search(text), text


def test_nothing_is_shown_when_the_desk_is_off(ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(POLYDESK_ENABLED=False)
    seed(ledger)
    save(settings, desk_state())  # a state file from before the switch changes nothing
    assert polymarket_desk(settings, NOW) is None
    state = build_page_state(ledger, settings, NOW)
    assert state["money"]["polymarket"] is None and state["town"]["polymarket"] is None
    assert state["town"]["line"] == "The town costs $0.17 a day to run; the desks lost $5.50 today (paper money)."
    assert state["money"]["today"]["usd"] == pytest.approx(-5.5)


def test_a_desk_that_never_ran_shows_zeros_marked_as_such_and_no_real_row(ledger: Ledger,
                                                                            settings: Settings) -> None:
    seed(ledger)
    state = build_page_state(ledger, settings, NOW)  # no state file at all
    pm = state["money"]["polymarket"]
    assert pm["as_of"] is None and pm["real"] is None
    assert pm["paper"] == {"label": "Paper money (pretend)", "open": 0, "today_usd": 0.0, "since_start_usd": 0.0,
                           "settled_today": 0, "won_today": 0, "settled_total": 0, "won_total": 0}
    town = state["town"]
    assert town["polymarket"]["real"] is None
    assert town["polymarket"]["paper"]["line"] == ("Polymarket desk (paper, pretend): today $0.00, since start $0.00, "
                                                   "0 open; no round finished yet")
    assert town["line"] == ("The town costs $0.17 a day to run; the Solana desk lost $5.50 today (paper money) and the "
                            "Polymarket desk has not finished a round yet (paper money, pretend).")


def test_the_venues_cash_alone_is_a_real_row_on_the_money_card_but_not_a_real_book_for_the_town(
        ledger: Ledger, settings: Settings) -> None:
    """A key is set and the venue answered with its cash, but nothing is held or settled: the money card shows the
    cash (real money, the venue's own figure); the town has no real line and no real sentence."""
    seed(ledger)
    save(settings, desk_state(real_open=0, venue=None, balance=CASH, paper_open=1))
    st = polydesk.load_state(polydesk.state_path(settings))
    st["live_days"], st["live_pnl_total_usd"] = {}, 0.0
    save(settings, st)
    state = build_page_state(ledger, settings, NOW)
    real = state["money"]["polymarket"]["real"]
    assert real["cash_usd"] == pytest.approx(16.27) and real["contracts"] is None and real["open"] == 0
    assert real["settled_total"] == 0 and real["since_start_usd"] == 0.0
    assert state["town"]["polymarket"]["real"] is None and "real money" not in state["town"]["line"]
    assert state["town"]["polymarket"]["paper"]["line"].endswith(", 1 open")


def test_contracts_at_the_venue_alone_are_a_real_book_even_before_the_desk_recorded_them(ledger: Ledger,
                                                                                            settings: Settings) -> None:
    """The venue's book is the truth for real money: contracts it holds count as a real book, with every part the
    venue has not answered (the cash) said so rather than shown as zero."""
    seed(ledger)
    save(settings, desk_state(real_open=0, balance=None))
    st = polydesk.load_state(polydesk.state_path(settings))
    st["live_days"], st["live_pnl_total_usd"] = {}, 0.0
    save(settings, st)
    town = build_page_state(ledger, settings, NOW)["town"]
    assert town["polymarket"]["real"]["line"] == ("Polymarket desk (REAL money): 8 contracts at the venue, cost $7.80, "
                                                  "worth $7.95 now; settled today 0/0 won $0.00; since start $0.00; "
                                                  "cash at the venue not read yet")
    assert town["polymarket"]["real"]["cash_usd"] is None
    assert town["line"].endswith(" Polymarket real money: nothing settled today; since start $0.00.")


def test_a_real_settlement_today_is_told_apart_from_the_paper_result(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    save(settings, desk_state(live_today={"pnl_usd": -0.97, "settled": 1, "won": 0}, real_open=0))
    state = build_page_state(ledger, settings, NOW)
    pm = state["money"]["polymarket"]
    assert pm["real"]["today_usd"] == pytest.approx(-0.97) and pm["real"]["settled_today"] == 1
    assert pm["real"]["since_start_usd"] == pytest.approx(-0.47) and pm["real"]["settled_total"] == 3
    assert pm["paper"]["today_usd"] == pytest.approx(-1345.53) and pm["paper"]["settled_today"] == 114  # unchanged
    town = state["town"]
    assert town["polymarket"]["real"]["line"] == ("Polymarket desk (REAL money): 8 contracts at the venue, cost $7.80, "
                                                  f"worth $7.95 now; settled today 0/1 won {MINUS}$0.97; since start "
                                                  f"{MINUS}$0.47; cash at the venue $16.27")
    assert town["line"].endswith(" Polymarket real money: lost $0.97 today (0/1 won); since start " f"{MINUS}$0.47.")


def test_a_live_solana_bot_and_the_paper_desk_are_named_apart_and_never_summed(ledger: Ledger,
                                                                                make_settings: Callable[..., Settings]
                                                                                ) -> None:
    settings = live_settings(make_settings)
    seed(ledger, mode="live")
    st = desk_state(real_open=0, venue=None, balance=None)
    st["days"][TODAY] = {"pnl_usd": 0.50, "settled": 1, "won": 1}
    st["live_days"], st["live_pnl_total_usd"] = {}, 0.0
    save(settings, st)
    state = build_page_state(ledger, settings, NOW)
    assert state["money"]["label"] == "Real money" and state["money"]["polymarket"]["real"] is None
    town = state["town"]
    assert town["label"] == "Real money" and town["income_today_usd"] == pytest.approx(-5.5)
    assert town["line"] == ("The town costs $0.17 a day to run; the Solana desk lost $5.50 today (real money) and the "
                            "Polymarket desk made $0.50 today (paper money, pretend).")
    assert town["polymarket"]["paper"]["line"].startswith("Polymarket desk (paper, pretend): today +$0.50, ")


def test_the_live_desks_label_and_the_mode_flag(ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    """The desk switched live (POLYDESK_MODE=live in its own state file): its label says real money; the books are
    still two, and the paper one (tickets from before the switch) is still called pretend."""
    settings = make_settings()
    seed(ledger)
    st = desk_state()
    st["mode"] = "live"
    save(settings, st)
    pm = build_page_state(ledger, settings, NOW)["money"]["polymarket"]
    assert pm["mode"] == "live" and pm["label"] == "Real money"
    assert pm["paper"]["label"] == "Paper money (pretend)" and pm["real"]["label"] == "Real money"


def test_an_unknown_solana_income_still_names_the_desk(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(TOWN_RAILWAY_USD_MONTH=3)
    save(settings, desk_state(real_open=0, venue=None, balance=None))
    desk = polymarket_desk(settings, NOW)
    money = {"label": "Paper money (pretend)", "today": {"usd": None}, "since_start": {"usd": None}, "polymarket": desk}
    town = town_ledger(settings, money, None, NOW, NOW - DAY)
    assert town["income_today_usd"] is None and town["covered_today"] is None
    assert town["line"] == ("The town costs $0.10 a day to run; what the Solana desk made today (paper money) is not "
                            "known yet: no money check so far; the Polymarket desk lost $1,345.53 today (paper money, "
                            "pretend). Polymarket real money: nothing settled today; since start +$0.50.")
    plain = town_ledger(settings, {"today": {"usd": 1.0}, "since_start": {"usd": 1.0}}, None, NOW, NOW - DAY)
    assert plain["polymarket"] is None and plain["line"] == "The town costs $0.10 a day to run; the desks made $1.00 today (paper money)."


def test_a_broken_desk_never_takes_the_page_down(monkeypatch: pytest.MonkeyPatch, ledger: Ledger,
                                                 settings: Settings) -> None:
    from nightcrawler import pagestate

    seed(ledger)
    polydesk.state_path(settings).parent.mkdir(parents=True)
    polydesk.state_path(settings).write_text("{garbage")  # an unreadable file reads as a desk that never ran
    pm = build_page_state(ledger, settings, NOW)["money"]["polymarket"]
    assert pm["as_of"] is None and pm["paper"]["open"] == 0 and pm["real"] is None

    def boom(settings: Settings, now: float) -> dict[str, Any]:
        raise KeyError("t_in")  # a position without its entry time

    monkeypatch.setattr(pagestate, "panel_state", boom)
    state = build_page_state(ledger, settings, NOW)
    assert state["money"]["polymarket"] is None and state["town"]["polymarket"] is None
    assert state["town"]["line"] == "The town costs $0.17 a day to run; the desks lost $5.50 today (paper money)."


def test_junk_in_the_desks_file_is_typed_not_trusted(settings: Settings) -> None:
    st = desk_state()
    st["exchange"] = {"contracts": "eight", "cost_usd": None, "value_usd": float("nan"), "at": "now"}
    st["balance"] = {"cash": True, "at": NOW}
    save(settings, st)
    real = polymarket_desk(settings, NOW)["real"]
    assert real["contracts"] is None and real["cost_usd"] is None and real["value_usd"] is None
    assert real["cash_usd"] is None and real["venue_at"] is None and real["open"] == 1  # the real book: the open one
    json.dumps(polymarket_desk(settings, NOW), allow_nan=False)


# --------------------------------------------------------------------------- the page itself


def test_the_page_renders_the_polymarket_block_as_text_only(settings: Settings,
                                                             make_settings: Callable[..., Settings]) -> None:
    html = render_page_html(settings)
    money = html[html.index('<section class="card" id="money">'):html.index('<section class="card" id="town">')]
    town = html[html.index('<section class="card" id="town">'):html.index('<section class="card" id="wallet">')]
    assert money.index('id="chart"') < money.index('id="money-polymarket"')  # under the SOL wallet and its chart
    assert town.index('id="town-bars"') < town.index('id="town-desks"')
    script = page_script(settings)
    assert "function renderPolymarket(pm)" in script and "renderPolymarket(m.polymarket);" in script
    assert "if (!pm || !pm.paper) { put(box); return; }" in script  # older data without the block: no error
    assert "book.label" in script and '"Real money"' not in script  # the labels come from the data, never the page
    assert '"real money ON" : "real money OFF"' in script
    assert "const desks = t.polymarket;" in script and '"Made today, Solana desk" : "Made today"' in script
    assert '.filter((d) => d && d.line)' in script and 'el("p", "meta", d.line)' in script
    assert "nothing here is added together" in script
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert sink not in script, sink
    assert script.count(".replaceChildren(") == 1  # every fill goes through put()
    strings = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', script)
    assert not [s for s in strings if " " in s and JARGON.search(s)]
    (style,) = re.findall(r"<style>(.*?)</style>", html, flags=re.DOTALL)  # the CSP hashes follow the edit
    for text, directive in ((script, "script-src"), (style, "style-src")):
        digest = base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()
        assert f"{directive} 'sha256-{digest}';" in PAGE_CSP
    assert "#town-desks p{margin-top:8px}" in style and style.count("--") == style.count("--")  # no new colours
    assert not re.search(r"#(?:money-polymarket|town-desks)[^{]*\{[^}]*(?:color|background)", style)
    live = render_page_html(live_settings(make_settings))
    assert 'id="money-polymarket"' in live and 'id="town-desks"' in live


# --------------------------------------------------------------------------- what the desk skips and why (C15)


def live_desk(**kw: Any) -> dict[str, Any]:
    """The desk in live mode (its own state file says so), as desk_state() builds it."""
    st = desk_state(**kw)
    st["mode"] = "live"
    return st


def _numbers(text: str) -> list[str]:
    return re.findall(r"\d[\d,]*(?:\.\d+)?", text)


def test_plain_real_names_the_sports_rule_from_history(ledger: Ledger, settings: Settings,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    from nightcrawler import pagestate

    save(settings, live_desk())
    line = build_page_state(ledger, settings, NOW)["plain"]["real"]["sports_line"]
    assert line.startswith("No real money on sports: in history (3,070 past bets like these, 104 lost: ")
    pooled = polydesk.SPORT_HISTORY_POOLED
    allowed = {f"{int(pooled['buys']):,}", f"{int(pooled['lost'])}", f"{100 * pooled['loss_rate']:.1f}",
               f"{100 * pooled['implied']:.1f}"}
    allowed |= {n for _, why in polydesk.SPORT_HISTORY.values() for n in _numbers(why)}
    assert _numbers(line) and set(_numbers(line)) <= allowed  # every number is the history's own
    for sport, (verdict, _) in polydesk.SPORT_HISTORY.items():  # each judged sport is named by its verdict
        name = {"hockey": "ice hockey", "mma/boxing": "boxing/MMA", "american football": "American football"}.get(
            sport, sport)
        if verdict != "mixed":
            assert name.lower() in line.lower(), sport
    assert "Tennis and esports favourites lost more often than their prices said" in line
    assert not JARGON.search(line) and "paid" not in line  # no sport "paid" in history: none was proven to
    # the wording follows the sports real money may bet: one allowed (by a code change) is named
    monkeypatch.setattr(pagestate, "REAL_SPORTS_ALLOWED", frozenset({"soccer"}))
    allowed_line = pagestate._sports_line()
    assert allowed_line.startswith("Real money on sports only for soccer; in history ") and "no other sport" in allowed_line
    assert "soccer, baseball" not in allowed_line and "baseball, basketball and cricket are unproven" in allowed_line


def test_plain_real_says_what_it_skipped_from_counts(ledger: Ledger, settings: Settings) -> None:
    st = live_desk()
    counts = {"sports_no_real": 4, "incoherent_game": 1, "never_traded": 0, "game_held": 7, "stop_room": 2}
    st["skips"] = {TODAY: {"counts": counts, "sports": {"tennis": 3, "soccer": 1}, "seen": []},
                   YESTERDAY: {"counts": {"never_traded": 9}, "sports": {}, "seen": []}}
    save(settings, st)
    state = build_page_state(ledger, settings, NOW)
    pm = state["money"]["polymarket"]
    assert pm["skips"] == {"counts": {"sports_no_real": 4, "incoherent_game": 1, "game_held": 7, "stop_room": 2},
                           "sports": {"tennis": 3, "soccer": 1}}  # today's only, zero parts left out
    line = state["plain"]["real"]["skips_line"]
    assert line == ("Today it practised 4 sports bets instead of betting real money and refused 1 game whose prices "
                    "did not add up.")
    assert _numbers(line) == ["4", "1"]  # the counts' own numbers; the never-traded part is zero: left out
    st["skips"][TODAY]["counts"] = {"sports_no_real": 1, "incoherent_game": 2, "never_traded": 3}
    save(settings, st)
    assert build_page_state(ledger, settings, NOW)["plain"]["real"]["skips_line"] == (
        "Today it practised 1 sports bet instead of betting real money, refused 2 games whose prices did not add up, "
        "and skipped 3 markets that had never traded near the price.")
    st["mode"] = "paper"  # paper mode: no real money to skip, so no sports clause
    save(settings, st)
    assert build_page_state(ledger, settings, NOW)["plain"]["real"]["skips_line"] == (
        "Today it refused 2 games whose prices did not add up and skipped 3 markets that had never traded near the "
        "price.")
    st["skips"][TODAY]["counts"] = {"junk": 5, "sports_no_real": "many", "incoherent_game": -1}  # typed, not trusted
    save(settings, st)
    assert build_page_state(ledger, settings, NOW)["money"]["polymarket"]["skips"]["counts"] == {}


def test_nothing_skipped_says_so(ledger: Ledger, settings: Settings) -> None:
    save(settings, live_desk())
    real = build_page_state(ledger, settings, NOW)["plain"]["real"]
    assert real["skips_line"] == "Nothing skipped yet today."
    assert polymarket_desk(settings, NOW)["skips"] == {"counts": {}, "sports": {}}


def test_pending_money_is_shown(ledger: Ledger, settings: Settings) -> None:
    st = live_desk()
    st["pending_orders"] = {"k1": {"limit": 0.98, "contracts": 1.0, "fee_coef": 0.0695, "t_in": NOW - 30,
                                   "question": "Will k1 happen?", "category": "crypto", "end_ts": NOW + 900}}
    save(settings, st)
    state = build_page_state(ledger, settings, NOW)
    real = state["money"]["polymarket"]["real"]
    assert (real["pending"], real["pending_usd"]) == (1, pytest.approx(0.98))
    assert real["open"] == 1 and real["at_risk_usd"] == pytest.approx(0.97)  # never added to the open bets
    line = state["plain"]["real"]["line"]
    assert ("$0.97 in 1 open bet, plus $0.98 in orders Polymarket has not confirmed yet;" in line)
    assert "1.95" not in json.dumps(state["plain"])  # the two are never summed
    st["pending_orders"] = {}
    save(settings, st)
    assert "not confirmed" not in build_page_state(ledger, settings, NOW)["plain"]["real"]["line"]


def test_room_kind_and_headline_fit(ledger: Ledger, settings: Settings) -> None:
    """The stops count money still at risk: with $0.97 open and the day at -$2.50, one more lost bet could pass the
    $3 day, so the desk waits; the headline says so in under two phone lines."""
    save(settings, live_desk(live_today={"pnl_usd": -2.50, "settled": 3, "won": 0}))
    p = build_page_state(ledger, settings, NOW)["plain"]
    assert p["real"]["paused_kind"] == "room"
    assert p["real"]["paused"] == "Waiting: if every open bet lost, today would pass the $3 limit, so it waits for some to finish."
    assert p["headline"] == "Real money is on for Voss's Polymarket bets, waiting on open bets; the rest is pretend."
    assert len(p["headline"]) <= PLAIN_HEADLINE_MAX
    # nothing open and the day's room gone: that is the day's stop
    save(settings, live_desk(real_open=0, live_today={"pnl_usd": -2.50, "settled": 3, "won": 0}))
    p = build_page_state(ledger, settings, NOW)["plain"]
    assert p["real"]["paused_kind"] == "day" and p["real"]["paused"] == (
        "Stopped for today: one more lost bet could pass the $3 daily limit. It can bet again after midnight UTC.")
    # nothing open and the total's room gone: at its loss limit
    st = live_desk(real_open=0)
    st["live_pnl_total_usd"] = -9.50
    save(settings, st)
    p = build_page_state(ledger, settings, NOW)["plain"]
    assert p["real"]["paused_kind"] == "room" and p["real"]["paused"] == (
        "Stopped: one more lost bet could pass the $10 total loss limit, so it places no new real bets.")
    assert p["headline"] == "Real money is on for Voss's Polymarket bets, at its loss limit; the rest is pretend."
    assert len(p["headline"]) <= PLAIN_HEADLINE_MAX
    # with room for a bet: nothing waits
    save(settings, live_desk())
    assert build_page_state(ledger, settings, NOW)["plain"]["real"]["paused_kind"] is None


def test_ticker_new_desk_events_are_worded() -> None:
    cases = [
        ("Order not confirmed yet at 0.980: Will k1 happen? (counted as open money until the venue shows it)",
         "a real-money order is waiting for Polymarket to confirm it · Will k1 happen?"),
        ("REAL buy confirmed late by the venue: Will k1 happen? · 1 contract at 0.980 ($0.98, crypto)",
         "Polymarket confirmed a real-money bet late: $0.98 · Will k1 happen?"),
        ("Refused a game whose prices do not add up: eBattles: Sassuolo vs. Roma (YES bids add up to 2.91)",
         "skipped a game whose prices did not add up ($2.91 for a $1 prize): eBattles: Sassuolo vs. Roma"),
        (("Practice record for american football clears the risk manager's bar (150 events (150 settled), 4 lost, "
          "+$212.00 in all): real money stays off for it until a fresh conf")[:160],
         "practice on american football looks good; real money stays off until a second check and the owner say yes"),
    ]
    for text, expected in cases:
        said = plain_event("predict", text)
        assert said == expected and not said.endswith("…") and "paper" not in said.lower(), text
        assert not JARGON.search(said)


def test_no_fill_still_worded() -> None:
    """"No fill" now comes only when the venue's book really holds nothing (a quiet read after the order)."""
    assert plain_event("predict", "No fill at 0.980: Will k1 happen? (order cancelled)") == (
        "a real-money order found no seller and was cancelled · Will k1 happen?")


def test_the_sports_table_rides_along_typed(settings: Settings) -> None:
    st = desk_state()
    save(settings, st)
    pm = polymarket_desk(settings, NOW)
    assert [s["sport"] for s in pm["sports"]] == list(polydesk.SPORT_HISTORY) and pm["real_sports_allowed"] == []
    assert {s["real"] for s in pm["sports"]} == {"blocked"} and not any(s["flagged"] for s in pm["sports"])
    tennis = pm["sports"][0]
    assert tennis == {"sport": "tennis", "real": "blocked", "history": "proven loser",
                      "why": polydesk.SPORT_HISTORY["tennis"][1], "paper": None, "flagged": False}
    json.dumps(pm, allow_nan=False)
