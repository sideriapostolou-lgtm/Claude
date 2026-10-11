"""The 3D world's data on ``/api/page`` (nightcrawler.pagestate, nightcrawler.recap, nightcrawler.teamroom): the trophy
shelf's ``trades.summary`` (every closed trade counted, the shelf's order capped; the real bets apart, from the receipts),
Rook's ``risk_wall`` (the panel's numbers and the real desk's caps), the nightly ``recap`` (yesterday in the owner's
time zone, from the ledger and its receipts only: its window, its beats in the page's plain words, real money apart from
pretend, an empty day, redaction, the cache) and the ``OWNER_TZ`` setting."""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock
from test_page import DAY, HIGGS, MEMBER_IDS, NOW, TOKEN, live_settings, seed
from test_page_polymarket import desk_state, save

from nightcrawler import polydesk
from nightcrawler import recap as recap_module
from nightcrawler.config import Settings
from nightcrawler.ledger import Ledger
from nightcrawler.models import (
    Decision,
    EquityPoint,
    Fill,
    Position,
    TokenCandidate,
    Verdict,
)
from nightcrawler.pagestate import (
    EXIT_WORDS,
    PAPER_LABEL,
    PRETEND_LABEL,
    REAL_LABEL,
    SHELF_MAX,
    build_page_state,
    plain_event,
    real_caps,
    recap_state,
)
from nightcrawler.recap import (
    HEADLINE_MAX,
    QUERY_CAP,
    RECAP_BEATS_MAX,
    RECAP_TTL_S,
    build_recap,
    day_window,
)
from nightcrawler.teamroom import build_team_state

LA = "America/Los_Angeles"
#: NOW is 2026-10-08T16:00Z: 09:00 in Los Angeles, so yesterday there is 2026-10-07, 00:00 PDT (07:00Z) to 07:00Z.
YDAY_START = 1_791_356_400.0
YDAY_END = YDAY_START + DAY
MINUS = "−"


@pytest.fixture
def ledger(tmp_path: Path, fake_clock: FakeClock) -> Iterator[Ledger]:
    with Ledger(tmp_path / "nc.db", clock=fake_clock) as led:
        yield led


def members(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {m["id"]: m for m in state["team"]["members"]}


def closed_position(pid: str, closed_at: float, proceeds: int, reason: str = "trailing_stop", mode: str = "paper"
                    ) -> Position:
    return Position(id=pid, mint=f"{pid}mint", symbol=pid.upper(), pool=None, opened_at=closed_at - 3600,
                    token_decimals=6, cost_lamports=100_000_000, proceeds_lamports=proceeds, fees_lamports=600_000,
                    entry_price_usd=0.01, status="closed", exit_reason=reason, closed_at=closed_at, mode=mode)


def settle(ledger: Ledger, slug: str, pnl: float, ts: float) -> None:
    """One real settlement, receipted the way the Polymarket desk receipts it."""
    ledger.append_receipt("polydesk_settled", {"slug": slug, "value": 1.0 if pnl > 0 else 0.0, "pnl_usd": pnl,
                                               "contracts": 1.0}, ts=ts)


# --------------------------------------------------------------------------- trades.summary (the trophy shelf)


def test_the_shelf_counts_every_closed_trade_newest_first(ledger: Ledger, settings: Settings) -> None:
    assert build_page_state(ledger, settings, NOW)["trades"]["summary"] == {
        "label": PAPER_LABEL, "won": 0, "lost": 0, "even": 0, "total": 0, "since": None, "order": "", "real": None,
        "result": "no money check yet"}
    seed(ledger)  # p2 won a day ago, p3 lost two hours ago
    summary = build_page_state(ledger, settings, NOW)["trades"]["summary"]
    # the money the tier stands for beside its counts: one win and one loss, down $5.50 in pretend money (the label)
    assert summary == {"label": PAPER_LABEL, "won": 1, "lost": 1, "even": 0, "total": 2, "since": NOW - DAY + 3600,
                       "order": "LW", "real": None, "result": "down $5.50 since start"}
    ledger.upsert_position(closed_position("p4", NOW - 60, 100_600_000))  # exactly even after fees
    assert build_page_state(ledger, settings, NOW)["trades"]["summary"]["order"] == "ELW"


def test_the_shelf_order_is_capped_but_the_counts_are_not(ledger: Ledger, settings: Settings) -> None:
    for i in range(SHELF_MAX + 30):
        ledger.upsert_position(closed_position(f"q{i}", NOW - 10 * DAY + i * 60, 120_000_000 if i % 3 else 80_000_000))
    ledger.upsert_position(closed_position("live1", NOW - 5, 200_000_000, mode="live"))  # the other mode: not counted
    trades = build_page_state(ledger, settings, NOW)["trades"]
    summary = trades["summary"]
    assert summary["total"] == SHELF_MAX + 30 and summary["won"] + summary["lost"] == summary["total"]
    assert summary["lost"] == (SHELF_MAX + 30 + 2) // 3 and summary["since"] == NOW - 10 * DAY
    assert len(summary["order"]) == SHELF_MAX and set(summary["order"]) <= {"W", "L"}
    assert summary["order"][0] == ("W" if (SHELF_MAX + 29) % 3 else "L")  # newest first
    assert len(trades["closed"]) == 10 and len(json.dumps(summary)) < 400


def test_the_real_bets_have_their_own_shelf_from_the_receipts(ledger: Ledger, settings: Settings) -> None:
    """Real money apart: the desk's own totals (money.polymarket.real), the order of its real settlements from the
    receipts (newest first), the newest lines in its own words, each REAL; nothing without a real book."""
    paper_only = desk_state(real_open=0, venue=None)
    paper_only["live_days"], paper_only["live_pnl_total_usd"] = {}, 0.0
    save(settings, paper_only)  # no real book: no real shelf
    assert build_page_state(ledger, settings, NOW)["trades"]["summary"]["real"] is None
    st = desk_state()  # two real settlements yesterday, both won (+$0.50), one real bet open
    st["closed"] = [{"slug": "r2", "question": "Will r2 happen?", "live": True, "won": True, "pnl_usd": 0.30,
                     "settled_at": NOW - DAY + 120},
                    {"slug": "p9", "question": "Will p9 happen?", "live": False, "won": False, "pnl_usd": -20.0,
                     "settled_at": NOW - DAY + 100},
                    {"slug": "r1", "question": "Will r1 happen?", "live": True, "won": True, "pnl_usd": 0.20,
                     "settled_at": NOW - DAY + 60}]
    save(settings, st)
    settle(ledger, "r1", 0.20, NOW - DAY + 60)
    settle(ledger, "r2", 0.30, NOW - DAY + 120)
    real = build_page_state(ledger, settings, NOW)["trades"]["summary"]["real"]
    assert real == {"label": REAL_LABEL, "won": 2, "lost": 0, "settled": 2, "since": NOW - DAY + 60, "order": "WW",
                    "lines": [{"ts": NOW - DAY + 120, "won": True, "text": "REAL · won +$0.30 · Will r2 happen?"},
                              {"ts": NOW - DAY + 60, "won": True, "text": "REAL · won +$0.20 · Will r1 happen?"}],
                    "result": "up $0.50 since start (real money)"}
    settle(ledger, "r3", -0.97, NOW - 30)  # a loss, newest
    assert build_page_state(ledger, settings, NOW)["trades"]["summary"]["real"]["order"] == "LWW"
    # the shelf's rows (money.polymarket.real_closed) apart from the replay banner's (settled_real: the desk's events)
    poly = build_page_state(ledger, settings, NOW)["money"]["polymarket"]
    assert [r["question"] for r in poly["real_closed"]] == ["Will r2 happen?", "Will r1 happen?"]
    assert all(set(r) == {"ts", "text"} for r in poly["settled_real"])


def test_the_real_tier_always_says_what_its_money_did(ledger: Ledger, settings: Settings) -> None:
    """A near-certain rule wins cents and loses dollars: a row of real trophies must never read as a profit, so the real
    tier always carries the desk's own result since start (the money card's figure), down as well as up."""
    st = desk_state()
    st["mode"] = "live"
    st["live_days"] = {"2026-10-07": {"pnl_usd": -2.52, "settled": 9, "won": 3}}
    st["live_pnl_total_usd"] = -2.52
    save(settings, st)
    state = build_page_state(ledger, settings, NOW)
    real = state["trades"]["summary"]["real"]
    assert (real["won"], real["lost"]) == (3, 6) and real["result"] == "down $2.52 since start"
    assert state["money"]["polymarket"]["real"]["since_start_usd"] == pytest.approx(-2.52)


# --------------------------------------------------------------------------- the risk wall


def test_the_risk_member_carries_its_wall_and_nobody_else_does(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    by = members(build_page_state(ledger, settings, NOW))
    wall = by["risk"]["risk_wall"]
    assert wall["allowance_used_pct"] == pytest.approx(25.0) and wall["daily_stop"] is False
    assert (wall["slots_used"], wall["slots_max"], wall["stopped_by"]) == (1, 3, None)
    assert all(set(d) == {"desk", "verdict", "paused"} for d in wall["desks"])
    assert wall["real_caps"] is None  # the desk has no real book
    assert all("risk_wall" not in by[mid] for mid in MEMBER_IDS if mid != "risk")


def test_the_wall_has_the_real_desks_caps_from_its_book_and_the_settings(ledger: Ledger,
                                                                         make_settings: Callable[..., Settings]
                                                                         ) -> None:
    settings = make_settings()
    st = desk_state(real_open=2, live_today={"pnl_usd": -1.25, "settled": 2, "won": 0})
    st["mode"] = "live"
    save(settings, st)
    caps = members(build_page_state(ledger, settings, NOW))["risk"]["risk_wall"]["real_caps"]
    # two real bets of $0.97 open, $1.25 lost today, $0.50 - $1.25 = -$0.75 in total; the caps are the settings'
    assert caps == {"label": REAL_LABEL, "on": True, "open_usd": 1.94, "open_max_usd": 10.0, "day_loss_usd": 1.25,
                    "day_max_usd": 3.0, "total_loss_usd": 0.75, "total_max_usd": 10.0}
    bigger = make_settings(POLYDESK_LIVE_MAX_OPEN_USD="20", POLYDESK_LIVE_DAILY_LOSS_USD="5")
    assert real_caps(bigger, build_page_state(ledger, bigger, NOW)["money"]["polymarket"])["open_max_usd"] == 20.0
    assert real_caps(settings, None) is None and real_caps(settings, {"real": None}) is None


# --------------------------------------------------------------------------- the recap: yesterday's window


def test_the_window_is_the_owners_previous_calendar_day() -> None:
    assert day_window(NOW, LA) == ("2026-10-07", YDAY_START, YDAY_END, LA)
    # Athens is 10 hours ahead of Los Angeles: the same instant, the same date, another window
    date, start, end, zone = day_window(NOW, "Europe/Athens")
    assert (date, zone) == ("2026-10-07", "Europe/Athens") and start == YDAY_START - 10 * 3600 and end - start == DAY
    # far enough east it is already the 9th: yesterday is the 8th
    assert day_window(NOW, "Pacific/Kiritimati")[0] == "2026-10-08"
    # the day the clocks go back lasts 25 hours, the day they go forward 23, as they really did
    date, start, end, _ = day_window(dt.datetime(2026, 11, 2, 20, tzinfo=dt.UTC).timestamp(), LA)
    assert date == "2026-11-01" and end - start == 25 * 3600
    date, start, end, _ = day_window(dt.datetime(2027, 3, 15, 20, tzinfo=dt.UTC).timestamp(), LA)
    assert date == "2027-03-14" and end - start == 23 * 3600
    # just before and just after the owner's midnight
    assert day_window(YDAY_END - 1, LA)[0] == "2026-10-06" and day_window(YDAY_END, LA)[0] == "2026-10-07"
    # an unknown zone never guesses: the UTC day, and it says so
    assert day_window(NOW, "Mars/Olympus") == ("2026-10-07", 1_791_331_200.0, 1_791_417_600.0, "UTC")
    assert day_window(NOW, LA, days_back=2)[0] == "2026-10-06"


def test_owner_tz_is_a_documented_setting_and_a_wrong_one_never_stops_the_bot(
        make_settings: Callable[..., Settings], ledger: Ledger, caplog: pytest.LogCaptureFixture) -> None:
    """A cosmetic setting (the film's day): an unknown zone is a warning at start and the recap's UTC day, never a
    refusal to start (that would stop the real desk too)."""
    assert make_settings().owner_tz == LA
    assert make_settings(OWNER_TZ=" Europe/Athens ").owner_tz == "Europe/Athens"
    with caplog.at_level(logging.WARNING, logger="nightcrawler.config"):
        wrong = make_settings(OWNER_TZ="Mars/Olympus")
    assert wrong.owner_tz == "Mars/Olympus" and "config_owner_tz_unknown" in caplog.text
    assert build_page_state(ledger, wrong, NOW)["recap"]["tz"] == "UTC"  # and it says so
    row = {r["env"]: r for r in Settings.describe()}["OWNER_TZ"]
    assert row["default"] == LA and row["unit"] == "text" and "recap" in row["help"]
    root = Path(__file__).resolve().parents[1]
    env = (root / ".env.example").read_text(encoding="utf-8")
    assert "OWNER_TZ=America/Los_Angeles" in env and "logs a warning" in env
    accounts = (root / "docs" / "ACCOUNTS.md").read_text(encoding="utf-8")
    assert "`OWNER_TZ`" in accounts and "never stops the bot" in accounts


# --------------------------------------------------------------------------- the recap: its beats


def test_an_empty_day_gives_an_empty_recap_not_a_made_up_one(ledger: Ledger, settings: Settings) -> None:
    recap = build_page_state(ledger, settings, NOW)["recap"]
    assert recap == {"date": "2026-10-07", "tz": LA, "window": [YDAY_START, YDAY_END], "events": [], "events_total": 0,
                     "quiet": True, "closed": [], "real": None,
                     "pretend": {"label": PRETEND_LABEL,
                                 "line": "Practice (pretend money): the Solana bot had no money check that day."}}


def test_a_day_without_beats_is_quiet_only_when_the_ledger_holds_nothing_for_it(ledger: Ledger,
                                                                                settings: Settings) -> None:
    """"quiet" (the film's "Nothing happened yesterday") only when the ledger has nothing at all for the day; a
    money check alone, or a receipt the film does not tell, is a day with no beats but not a quiet one."""
    ledger.record_equity(EquityPoint(ts=YDAY_START + 600, equity_lamports=1_000_000_000, sol_usd=100.0,
                                     equity_usd=100.0, mode="paper"))
    recap = build_page_state(ledger, settings, NOW)["recap"]
    assert recap["events"] == [] and recap["events_total"] == 0 and recap["quiet"] is False
    assert build_page_state(ledger, settings, NOW + 2 * DAY)["recap"]["quiet"] is True  # two days later: nothing


def test_the_seeded_ledger_recaps_yesterdays_one_trade_at_the_pages_own_figure(ledger: Ledger,
                                                                               settings: Settings) -> None:
    """One trade, one dollar figure: the film's is trades.closed's (the page's SOL price), not a second one."""
    seed(ledger)  # p2 closed yesterday 10:00 PDT; p3 and every decision happened today
    state = build_page_state(ledger, settings, NOW)
    recap = state["recap"]
    card = next(t for t in state["trades"]["closed"] if t["coin"] == "P2")
    assert card["pnl_usd"] == pytest.approx(0.0194 * 110.0)  # 0.0194 SOL at today's $110
    assert recap["closed"] == [{"coin": "P2", "closed_at": NOW - DAY + 3600, "pnl_usd": round(card["pnl_usd"], 2),
                                "result": "won", "why": EXIT_WORDS["trailing_stop"], "label": PAPER_LABEL}]
    assert recap["events"] == [{"ts": NOW - DAY + 3600, "member": "broker", "tone": "good", "real": False,
                                "text": "P2: Sold after the price fell from its high · won +$2.13 (pretend money)"}]
    assert recap["events_total"] == 1 and recap["real"] is None and recap["quiet"] is False
    # the money: the last check before the day (two days ago) and the last one during it (just after midnight UTC),
    # open trades counted at their price (why a won trade and an even day can stand side by side)
    assert recap["pretend"]["line"] == ("Practice (pretend money): the Solana bot's pretend wallet ended the day even, "
                                        "counting open trades at their price.")
    # without a SOL price the figure is in SOL, never a guessed dollar one
    raw = recap_module.build_recap(ledger, NOW, tz=LA, mode="paper", words=lambda m, line: line, exit_words=EXIT_WORDS)
    assert raw["closed"][0]["pnl_usd"] is None and raw["events"][0]["text"].endswith("won +0.0194 SOL (pretend money)")


def busy_day(ledger: Ledger, leak: str = "") -> list[float]:
    """Yesterday (Los Angeles) full of records of every kind; returns the hours' stamps."""
    t = [YDAY_START + h * 3600 for h in range(24)]
    yes = Verdict(decision="yes", confidence=0.8, reasons=["clean holders"], model="m", latency_ms=1, cost_usd=0.001,
                  source="claude")
    no = Verdict(decision="no", confidence=0.7, reasons=["creator selling" + leak], model="m", latency_ms=1,
                 cost_usd=0.001, source="claude")
    rules = Verdict(decision="yes", confidence=1.0, reasons=[], model="rules", latency_ms=0, cost_usd=0.0,
                    source="rules")
    for i in range(20):  # the scam filter's day: far more than a film can show
        ledger.record_decision(Decision(ts=t[1] + i, mint=f"R{i}", action="reject_cocoon", reason="[top10] own 45%",
                                        symbol=f"REJ{i}"))
    ledger.record_candidate(TokenCandidate(mint="F1", symbol="FIRST", age_min=70.0, mcap_usd=250_000.0,
                                           sources=["jupiter_recent"], discovered_at=t[2]))
    ledger.record_candidate(TokenCandidate(mint="F2", symbol="MIDDLE", age_min=70.0, discovered_at=t[3]))
    ledger.record_candidate(TokenCandidate(mint="F3", symbol="LAST", age_min=130.0, sources=["gt_new_pools"],
                                           discovered_at=t[4]))
    ledger.record_decision(Decision(ts=t[5], mint="W1", action="watch", reason="passed (0 warnings)", symbol="PASSED"))
    ledger.record_decision(Decision(ts=t[6], mint=HIGGS, action="enter", reason="dip-rebound", symbol="HIGGS",
                                    verdict=yes, inputs={"signal": {"kind": "enter"}}))
    ledger.record_fill(Fill(id="fy", mode="paper", side="buy", mint=HIGGS, sol_lamports=100_000_000,
                            token_amount=5_000_000_000, token_decimals=6, price_usd=0.002, sol_usd=100.0,
                            fees_lamports=300_000, platform_fee_bps=10, price_impact_pct=1.5, signature=None,
                            request_id="r", ts=t[6] + 1, symbol="HIGGS", position_id="py"))
    ledger.record_decision(Decision(ts=t[7], mint="RULEmint", action="enter", reason="dip-rebound", symbol="RULED",
                                    verdict=rules, inputs={"signal": {"kind": "enter"}}))  # the judge was off
    ledger.record_decision(Decision(ts=t[8], mint="J1", action="reject_judge", reason="judge: creator selling",
                                    symbol="JUDGED", verdict=no))
    ledger.record_decision(Decision(ts=t[9], mint="K1", action="reject_risk", reason="[max_positions] 3 open",
                                    symbol="RISKY"))
    ledger.record_decision(Decision(ts=t[10], mint="D1", action="reject_radar", reason="radar: creator sold $1,200",
                                    symbol="DUMP", inputs={"radar": {"flagged": True, "reasons": ["creator sold $1,200"]}}))
    ledger.record_decision(Decision(ts=t[11], mint="Q1", action="reject_quote", reason="price impact 4.1%",
                                    symbol="PRICEY"))
    ledger.record_decision(Decision(ts=t[12], mint=HIGGS, action="exit_partial", reason="take_profit_partial",
                                    symbol="HIGGS"))
    ledger.record_decision(Decision(ts=t[13], mint="U1", action="unwatch", reason="too old", symbol="OLDIE"))
    ledger.record_decision(Decision(ts=t[13] + 1, mint="P1", action="reject_prefilter", reason="too young",
                                    symbol="BABY"))  # never a beat
    ledger.upsert_position(closed_position("py", t[14], 120_000_000))
    ledger.record_fill(Fill(id="fs", mode="paper", side="sell", mint=HIGGS, sol_lamports=120_000_000,
                            token_amount=5_000_000_000, token_decimals=6, price_usd=0.0024, sol_usd=110.0,
                            fees_lamports=300_000, platform_fee_bps=10, price_impact_pct=1.0, signature=None,
                            request_id="r2", ts=t[14], symbol="HIGGS", position_id="py"))
    ledger.upsert_position(closed_position("pz", t[15], 80_000_000, reason="radar: creator sold"))
    ledger.append_receipt("halt", {"reason": "[drawdown] -52%"}, ts=t[16])
    ledger.upsert_position(closed_position("today", NOW - 60, 150_000_000))  # today: not yesterday's
    for ts, lamports, sol_usd in ((YDAY_START - 3600, 1_000_000_000, 100.0), (t[1], 990_000_000, 100.0),
                                  (t[20], 950_000_000, 110.0), (YDAY_END + 60, 940_000_000, 110.0)):
        ledger.record_equity(EquityPoint(ts=ts, equity_lamports=lamports, sol_usd=sol_usd,
                                         equity_usd=lamports / 1e9 * sol_usd, mode="paper"))
    return t


def test_a_busy_day_keeps_the_headlines_then_one_of_each_member_in_time_order(ledger: Ledger,
                                                                              settings: Settings) -> None:
    t = busy_day(ledger)
    recap = build_page_state(ledger, settings, NOW)["recap"]
    events = recap["events"]
    assert len(events) == RECAP_BEATS_MAX == 8 and [e["ts"] for e in events] == sorted(e["ts"] for e in events)
    # 20 rejections, 3 finds, 13 other records (9 decisions, a buy, a halt, two closed trades; the prefilter's skip
    # is not one the film tells)
    assert recap["events_total"] == 20 + 3 + 13
    assert {e["member"] for e in events} <= set(MEMBER_IDS)
    by_text = {e["text"]: e for e in events}
    # the headlines: both trades closed (at the page's own SOL price, $110 today: the trophy card's figure) and the
    # halt, in the page's plain words, pretend money said so
    assert by_text["PY: Sold after the price fell from its high · won +$2.13 (pretend money)"]["tone"] == "good"
    assert by_text[f"PZ: Danger spotted, sold early · lost {MINUS}$2.27 (pretend money)"]["tone"] == "bad"
    halt = next(e for e in events if e["member"] == "risk" and e["ts"] == t[16])
    assert halt["text"].startswith("stopped new buys: ") and halt["tone"] == "bad"
    # then the other kinds in rank order, a member the film has not shown yet first: a film of the whole team,
    # each line the page's own plain words (the same words its bubbles say)
    assert [(e["member"], e["text"]) for e in events if e["ts"] not in (t[14], t[15], t[16])] == [
        ("crawler", "found a new coin: FIRST (70 min old)"),
        ("cocoon", "PASSED passed the scam check"),
        ("strategy", "the buy signal came for HIGGS: bought (pretend money)"),
        ("judge", "the AI judge said yes to HIGGS: clean holders"),
        ("radar", "spotted danger on DUMP: creator sold $1,200")]
    assert len({e["member"] for e in events}) == 7  # (Jet has the two trades; everyone else once)
    # what a short film drops: the filter's 20 rejections, the drops, a rules-only "yes" (the judge was off), the
    # prefilter's skips, the second judge verdict (one of each kind first)
    assert not any(e["text"].startswith(("threw out", "stopped watching")) for e in events)
    assert not any("RULED" in e["text"] and "judge" in e["text"] for e in events)
    assert not any("BABY" in e["text"] for e in events)
    assert not any(e["real"] for e in events)  # all of it pretend money
    assert recap["closed"] == [
        {"coin": "PY", "closed_at": t[14], "pnl_usd": 2.13, "result": "won", "why": EXIT_WORDS["trailing_stop"],
         "label": PAPER_LABEL},
        {"coin": "PZ", "closed_at": t[15], "pnl_usd": -2.27, "result": "lost", "why": "Danger spotted, sold early",
         "label": PAPER_LABEL}]
    # 1.00 SOL before the day, 0.95 at its last check (SOL at $110): down 0.05 SOL = $5.50, in pretend money
    assert recap["pretend"]["line"] == ("Practice (pretend money): the Solana bot's pretend wallet ended the day "
                                        "down $5.50, counting open trades at their price.")


def test_every_beat_says_exactly_what_the_pages_plain_words_say(ledger: Ledger, settings: Settings) -> None:
    """The film's line for a record is the page's own plain words for it (plain_event), clipped: the bubbles, the card
    and the film never word the same record two ways."""
    busy_day(ledger)
    events = build_page_state(ledger, settings, NOW)["recap"]["events"]
    raw = recap_module.build_recap(ledger, NOW, tz=LA, mode="paper", words=lambda m, line: line, exit_words=EXIT_WORDS,
                                   sol_usd=110.0)  # (the page's own SOL price)
    assert [(e["ts"], e["member"]) for e in raw["events"]] == [(e["ts"], e["member"]) for e in events]
    assert [plain_event(e["member"], r["text"]) for e, r in zip(events, raw["events"], strict=True)] == \
        [e["text"] for e in events]


def test_a_quiet_day_shows_the_finds_and_the_filter_too(ledger: Ledger, settings: Settings) -> None:
    for i in range(3):
        ledger.record_candidate(TokenCandidate(mint=f"F{i}", symbol=f"COIN{i}", age_min=70.0 + i, mcap_usd=250_000.0,
                                               sources=["jupiter_recent", "gt_new_pools"],
                                               discovered_at=YDAY_START + 3600 * (i + 1)))
    ledger.record_decision(Decision(ts=YDAY_START + 4 * 3600, mint="F1", action="reject_cocoon",
                                    reason="[top10] top-10 own 45%", symbol="COIN1"))
    recap = build_page_state(ledger, settings, NOW)["recap"]
    assert [(e["member"], e["text"]) for e in recap["events"]] == [
        ("crawler", "found a new coin: COIN0 (70 min old)"),  # the first find
        ("crawler", "found a new coin: COIN2 (72 min old)"),  # and the last
        ("cocoon", "threw out COIN1: Top 10 wallets hold too much: top-10 own 45%")]
    assert recap["events_total"] == 4


def real_day(ledger: Ledger, settings: Settings) -> None:
    """Yesterday's real money (the desk live): a real buy, two settlements (one won, one lost), the risk manager's
    pause; one more settlement today."""
    st = desk_state(real_open=1)  # the money card's real book: +$0.50 since start, a real bet open on real0
    st["mode"] = "live"
    st["live_pnl_total_usd"] = 0.50 - 0.97 + 0.03 + 0.02  # the four settlements below
    st["closed"] = [{"slug": "won1", "question": "Will the Fed hold rates in October?", "live": True, "won": True,
                     "pnl_usd": 0.03, "settled_at": YDAY_START + 9 * 3600}]
    save(settings, st)
    ledger.append_receipt("polydesk_settled", {"slug": "old", "value": 1.0, "pnl_usd": 0.50, "contracts": 1.0},
                          ts=YDAY_START - 3600)  # the day before: part of where the day began
    ledger.append_receipt("polydesk_order_filled", {"slug": "real0", "order_id": "o1", "contracts": 1.0,
                                                    "price": 0.97, "cost_usd": 0.97}, ts=YDAY_START + 2 * 3600)
    settle(ledger, "lost1", -0.97, YDAY_START + 5 * 3600)
    ledger.append_receipt("polydesk_guard", {"book": "real", "paused": True, "rule": "r", "verdict": "losing", "n": 12,
                                             "total_usd": -3.1}, ts=YDAY_START + 6 * 3600)
    settle(ledger, "won1", 0.03, YDAY_START + 9 * 3600)
    settle(ledger, "won2", 0.02, NOW - 600)  # today: after the day ended


def test_the_real_money_of_the_day_is_real_and_apart(ledger: Ledger, settings: Settings) -> None:
    real_day(ledger, settings)
    recap = build_page_state(ledger, settings, NOW)["recap"]
    voss = [e for e in recap["events"] if e["member"] == "predict"]
    assert [(e["text"], e["tone"], e["real"]) for e in voss] == [
        ("real-money bet: $0.97 on YES · Will real0 happen?", "neutral", True),  # the question from the desk's state
        ("a real-money bet lost $0.97 · lost1", "bad", True),  # a market the desk no longer keeps: as the venue says
        ("the risk manager paused the real-money bets: the record was losing", "bad", True),
        ("a real-money bet won $0.03 · Will the Fed hold rates in October?", "good", True)]
    # the result since start when the day began (+$0.50 then) and when it ended (+$0.50 - $0.97 + $0.03), worked back
    # from the money card's own figure now (+$0.08) minus what settled since; one sentence, "real money" said once
    assert recap["real"] == {
        "label": REAL_LABEL, "start_usd": 0.50, "end_usd": -0.44, "settled": 2, "won": 1,
        "line": "Real money yesterday: the day began up $0.50 since start and ended down $0.44 since start; 1 of 2 "
                "finished bets won."}
    assert recap["real"]["line"].lower().count("real money") == 1
    assert recap["pretend"]["label"] == PRETEND_LABEL and "real" not in recap["pretend"]["line"].lower()
    assert recap["events_total"] == 4


def test_the_recap_is_redacted_and_clipped_like_the_rest_of_the_page(ledger: Ledger,
                                                                     make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(DASHBOARD_TOKEN=TOKEN)
    busy_day(ledger, leak=TOKEN)
    ledger.record_decision(Decision(ts=YDAY_START + 100, mint="L1", action="reject_risk",
                                    reason="[max_positions] " + "x" * 400, symbol="LONG"))
    state = build_page_state(ledger, settings, NOW)
    assert TOKEN not in json.dumps(state)
    assert all(len(e["text"]) <= 160 for e in state["recap"]["events"])


def test_the_recap_follows_the_owners_zone_and_the_mode(ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    busy_day(ledger)
    athens = make_settings(OWNER_TZ="Europe/Athens")
    recap = build_page_state(ledger, athens, NOW)["recap"]
    assert recap["tz"] == "Europe/Athens" and recap["window"][0] == YDAY_START - 10 * 3600
    # Athens's 7th ends at 21:00Z: the trades closed at 21:00Z and 22:00Z (t[14], t[15]) belong to its 8th
    assert recap["closed"] == [] and all(e["ts"] < YDAY_END - 10 * 3600 for e in recap["events"])
    live = live_settings(make_settings)
    recap = build_page_state(ledger, live, NOW)["recap"]
    assert recap["closed"] == [] and recap["pretend"] is None  # paper trades are not live money; nothing pretend here
    assert recap["real"]["line"] == "The Solana bot (real money): no money check that day."


def test_the_recap_is_cached_per_day_zone_and_mode(ledger: Ledger, settings: Settings,
                                                   make_settings: Callable[..., Settings]) -> None:
    """The day's records are read once per RECAP_TTL_S (per day, zone and mode); the words, and a closed trade's
    dollar figure at the page's SOL price, are made on every page."""
    seed(ledger)
    memory: dict[str, Any] = {}
    first = recap_state(ledger, settings, NOW, memory, sol_usd=110.0)
    kept = memory["recap"]["raw"]
    assert first["events"] and recap_state(ledger, settings, NOW + 5, memory, sol_usd=110.0) == first
    assert memory["recap"]["raw"] is kept
    ledger.upsert_position(closed_position("late", NOW - DAY + 7200, 150_000_000))  # yesterday, recorded late
    assert recap_state(ledger, settings, NOW + RECAP_TTL_S - 1, memory, sol_usd=110.0) == first  # the kept records
    # the SOL price moved: the same records, today's figure (the trophy card's), at once
    assert recap_state(ledger, settings, NOW + 10, memory, sol_usd=120.0)["closed"][0]["pnl_usd"] == round(0.0194 * 120, 2)
    again = recap_state(ledger, settings, NOW + RECAP_TTL_S, memory, sol_usd=110.0)
    assert memory["recap"]["raw"] is not kept and len(again["closed"]) == 2
    recap_state(ledger, make_settings(OWNER_TZ="Europe/Athens"), NOW + RECAP_TTL_S, memory)
    assert memory["recap"]["key"][1] == "Europe/Athens"
    # the owner's midnight: a new day is a new recap at once, whatever the age of the kept one
    assert recap_state(ledger, settings, YDAY_END + DAY - 10, memory)["date"] == "2026-10-07"
    assert recap_state(ledger, settings, YDAY_END + DAY + 10, memory)["date"] == "2026-10-08"
    assert build_recap(ledger, NOW, tz=LA, mode="paper", words=lambda m, x: x, exit_words={})["events"]


def test_a_broken_record_never_takes_the_page_down(ledger: Ledger, settings: Settings,
                                                   monkeypatch: pytest.MonkeyPatch,
                                                   caplog: pytest.LogCaptureFixture) -> None:
    """The recap is an extra: if its records cannot be read the page still builds, with an empty recap (the film then
    says nothing happened rather than anything made up), and the failure is logged."""
    seed(ledger)

    def broken(*_: Any, **__: Any) -> dict[str, Any]:
        raise ValueError("a bad row")

    monkeypatch.setattr("nightcrawler.pagestate.collect_recap", broken)
    with caplog.at_level(logging.WARNING, logger="nightcrawler.pagestate"):
        state = build_page_state(ledger, settings, NOW)
    assert state["recap"] == {"date": "2026-10-07", "tz": LA, "window": [YDAY_START, YDAY_END], "events": [],
                              "events_total": 0, "quiet": False, "closed": [], "real": None, "pretend": None}
    assert "recap_failed error=ValueError" in caplog.text and state["trades"]["closed"]


def test_malformed_real_rows_never_blank_the_real_desk(ledger: Ledger, settings: Settings) -> None:
    """A kept row without a number, or a settlement payload whose figure is not one, is skipped (the shelf's lines)
    or read as no win (its order): the real book stays on the page."""
    st = desk_state()
    st["mode"] = "live"
    st["closed"] = [{"slug": "r1", "question": "Will r1 happen?", "live": True, "won": True, "pnl_usd": 0.30,
                     "settled_at": NOW - 600},
                    {"slug": "r2", "question": "Will r2 happen?", "live": True, "won": False, "pnl_usd": "oops",
                     "settled_at": NOW - 500}]
    save(settings, st)
    assert [r["pnl_usd"] for r in polydesk.panel_state(settings, NOW)["real_closed"]] == [0.30]
    ledger.append_receipt("polydesk_settled", {"slug": "r9", "pnl_usd": {"nested": True}}, ts=NOW - 60)
    state = build_page_state(ledger, settings, NOW)
    assert state["money"]["polymarket"]["real"] is not None
    real = state["trades"]["summary"]["real"]
    assert real["order"] == "L" and [line["text"] for line in real["lines"]] == ["REAL · won +$0.30 · Will r1 happen?"]


def test_the_kill_switch_is_worded_by_what_its_receipt_says(ledger: Ledger, settings: Settings) -> None:
    """engine.handle_kill receipts every change, turning it off too: off is said as off (never "went on")."""
    for i, (mode, previous) in enumerate((("stop", "off"), ("off", "stop"), ("sell_all", "off"), ("off", "sell_all"))):
        ledger.append_receipt("kill", {"mode": mode, "previous": previous}, ts=YDAY_START + 3600 * (i + 1))
    events = build_page_state(ledger, settings, NOW)["recap"]["events"]
    assert [(e["member"], e["text"], e["tone"]) for e in events] == [
        ("risk", "the kill switch went on (no new buys)", "bad"),
        ("risk", "the kill switch was turned off", "neutral"),
        ("risk", "the kill switch went on (sell everything, buy nothing)", "bad"),
        ("risk", "the kill switch was turned off", "neutral")]
    assert not any("went on" in e["text"] and "off" in e["text"] for e in events)


def test_more_headlines_than_the_film_holds_are_spread_and_keep_the_pause_and_the_trade(
        ledger: Ledger, settings: Settings) -> None:
    """A heavy real-money day (7 settlements, 7 real buys, the risk manager's pause, kill-switch changes, a closed
    trade): one of each headline kind first, so the pause and the day's only closed trade always make the film, then
    the team's other work; the settlements chosen spread over the day, never only the morning's."""
    st = desk_state()
    st["mode"] = "live"
    save(settings, st)
    for i in range(7):
        settle(ledger, f"s{i}", 0.03 if i % 3 else -0.97, YDAY_START + 3600 * (1 + 3 * i))
        ledger.append_receipt("polydesk_order_filled", {"slug": f"b{i}", "contracts": 1.0, "price": 0.97,
                                                        "cost_usd": 0.97}, ts=YDAY_START + 3600 * (2 + 3 * i))
    ledger.append_receipt("polydesk_guard", {"book": "real", "paused": True, "rule": "r", "verdict": "losing"},
                          ts=YDAY_START + 23 * 3600)
    for i, mode in enumerate(("stop", "off")):
        ledger.append_receipt("kill", {"mode": mode, "previous": None}, ts=YDAY_START + 3600 * (4 + 10 * i) + 60)
    ledger.upsert_position(closed_position("pc", YDAY_START + 15 * 3600, 120_000_000))
    ledger.record_decision(Decision(ts=YDAY_START + 7200, mint="K1", action="reject_risk", reason="[max_positions] 3 open",
                                    symbol="RISKY"))
    ledger.record_candidate(TokenCandidate(mint="F1", symbol="FIRST", age_min=70.0, discovered_at=YDAY_START + 600))
    events = build_page_state(ledger, settings, NOW)["recap"]["events"]
    assert len(events) == RECAP_BEATS_MAX and HEADLINE_MAX < RECAP_BEATS_MAX
    texts = [e["text"] for e in events]
    assert sum(t.startswith("the risk manager paused") for t in texts) == 1
    assert sum(t.startswith("PC: ") for t in texts) == 1  # the day's one closed trade
    assert any(t.startswith("refused to buy RISKY") for t in texts) and any(t.startswith("found a new coin") for t in texts)
    settled = [e["ts"] for e in events if e["text"].startswith("a real-money bet")]
    assert settled and (len(settled) == 1 or max(settled) - min(settled) > 6 * 3600)
    # real money said real, and only real money
    assert all(e["real"] == (e["member"] == "predict") for e in events)


def test_only_real_money_records_are_marked_real(ledger: Ledger, settings: Settings,
                                                 make_settings: Callable[..., Settings]) -> None:
    busy_day(ledger)
    real_day(ledger, settings)
    events = build_page_state(ledger, settings, NOW)["recap"]["events"]
    assert {e["member"] for e in events if e["real"]} == {"predict"}
    assert all(e["real"] for e in events if e["member"] == "predict")
    assert not any(e["real"] for e in events if "(pretend money)" in e["text"])
    # the Solana bot on real money: its own trades are real money too
    live = build_page_state(ledger, live_settings(make_settings), NOW)["recap"]["events"]
    assert all(e["real"] for e in live if "(real money)" in e["text"])


def test_more_settlements_than_a_query_reads_give_no_made_up_start(ledger: Ledger, settings: Settings) -> None:
    """The day's start is worked back from every settlement since; past QUERY_CAP of them it is not worked back from
    part of them (it would be a wrong figure): the line keeps only what it can say."""
    st = desk_state()
    st["mode"] = "live"
    save(settings, st)
    for i in range(QUERY_CAP + 1):
        settle(ledger, f"m{i}", 0.01, YDAY_START + 60 + i)
    real = build_page_state(ledger, settings, NOW)["recap"]["real"]
    assert real["start_usd"] is None and real["end_usd"] is None and real["settled"] == QUERY_CAP
    assert real["line"] == f"Real money yesterday: at least {QUERY_CAP} bets finished."  # never a partial count


def test_a_flood_of_records_is_read_in_bounded_queries(ledger: Ledger, settings: Settings) -> None:
    for i in range(QUERY_CAP + 50):
        ledger.record_decision(Decision(ts=YDAY_START + 60 + i, mint=f"M{i}", action="reject_cocoon",
                                        reason="[top10] own 45%", symbol=f"C{i}"))
    recap = build_page_state(ledger, settings, NOW)["recap"]
    assert recap["events_total"] == QUERY_CAP + 50  # all counted; only QUERY_CAP of them read
    stamps = [e["ts"] for e in recap["events"]]
    assert len(stamps) == RECAP_BEATS_MAX and HEADLINE_MAX < RECAP_BEATS_MAX
    # spread over what was read: the first, the last read, the middle, the quarters...
    assert stamps[0] == YDAY_START + 60 and stamps[-1] == YDAY_START + 60 + QUERY_CAP - 1
    picked = {int(s - YDAY_START - 60) for s in stamps}
    assert {round((QUERY_CAP - 1) * f) for f in (0.25, 0.5, 0.75)} <= picked


def test_the_team_room_itself_is_unchanged_by_the_recap(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    assert "recap" not in build_team_state(ledger, settings, NOW)
