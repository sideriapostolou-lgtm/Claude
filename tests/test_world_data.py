"""The 3D world's data on ``/api/page`` (nightcrawler.pagestate, nightcrawler.recap, nightcrawler.teamroom): the trophy
shelf's ``trades.summary`` (every closed trade counted, the shelf's order capped; the real bets apart, from the receipts),
Rook's ``risk_wall`` (the panel's numbers and the real desk's caps), the nightly ``recap`` (yesterday in the owner's
time zone, from the ledger and its receipts only: its window, its beats in the page's plain words, real money apart from
pretend, an empty day, redaction, the cache) and the ``OWNER_TZ`` setting."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock
from test_page import DAY, HIGGS, MEMBER_IDS, NOW, TOKEN, live_settings, seed
from test_page_polymarket import desk_state, save

from nightcrawler import recap as recap_module
from nightcrawler.config import ConfigError, Settings
from nightcrawler.ledger import Ledger
from nightcrawler.models import Decision, EquityPoint, Fill, Position, TokenCandidate, Verdict
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
from nightcrawler.recap import HEADLINE_MAX, QUERY_CAP, RECAP_BEATS_MAX, RECAP_TTL_S, build_recap, day_window
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
        "label": PAPER_LABEL, "won": 0, "lost": 0, "even": 0, "total": 0, "since": None, "order": "", "real": None}
    seed(ledger)  # p2 won a day ago, p3 lost two hours ago
    summary = build_page_state(ledger, settings, NOW)["trades"]["summary"]
    assert summary == {"label": PAPER_LABEL, "won": 1, "lost": 1, "even": 0, "total": 2, "since": NOW - DAY + 3600,
                       "order": "LW", "real": None}
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
    assert len(trades["closed"]) == 10 and len(json.dumps(summary)) < 360


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
                              {"ts": NOW - DAY + 60, "won": True, "text": "REAL · won +$0.20 · Will r1 happen?"}]}
    settle(ledger, "r3", -0.97, NOW - 30)  # a loss, newest
    assert build_page_state(ledger, settings, NOW)["trades"]["summary"]["real"]["order"] == "LWW"


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


def test_owner_tz_is_a_documented_setting_that_must_name_a_real_zone(make_settings: Callable[..., Settings]
                                                                     ) -> None:
    assert make_settings().owner_tz == LA
    assert make_settings(OWNER_TZ=" Europe/Athens ").owner_tz == "Europe/Athens"
    with pytest.raises(ConfigError, match="OWNER_TZ"):
        make_settings(OWNER_TZ="Mars/Olympus")
    row = {r["env"]: r for r in Settings.describe()}["OWNER_TZ"]
    assert row["default"] == LA and row["unit"] == "text" and "recap" in row["help"]
    root = Path(__file__).resolve().parents[1]
    assert "OWNER_TZ=America/Los_Angeles" in (root / ".env.example").read_text(encoding="utf-8")
    assert "`OWNER_TZ`" in (root / "docs" / "ACCOUNTS.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- the recap: its beats


def test_an_empty_day_gives_an_empty_recap_not_a_made_up_one(ledger: Ledger, settings: Settings) -> None:
    recap = build_page_state(ledger, settings, NOW)["recap"]
    assert recap == {"date": "2026-10-07", "tz": LA, "window": [YDAY_START, YDAY_END], "events": [], "events_total": 0,
                     "closed": [], "real": None,
                     "pretend": {"label": PRETEND_LABEL,
                                 "line": "Practice (pretend money): the Solana bot had no money check that day."}}


def test_the_seeded_ledger_recaps_yesterdays_one_trade(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)  # p2 closed yesterday 10:00 PDT; p3 and every decision happened today
    recap = build_page_state(ledger, settings, NOW)["recap"]
    assert recap["closed"] == [{"coin": "P2", "closed_at": NOW - DAY + 3600, "pnl_usd": 1.94, "result": "won",
                                "why": EXIT_WORDS["trailing_stop"], "label": PAPER_LABEL}]
    assert recap["events"] == [{"ts": NOW - DAY + 3600, "member": "broker", "tone": "good",
                                "text": "P2: Sold after the price fell from its high · won +$1.94 (pretend money)"}]
    assert recap["events_total"] == 1 and recap["real"] is None
    # the money: the last check before the day (two days ago) and the last one during it (just after midnight UTC)
    assert recap["pretend"]["line"] == "Practice (pretend money): the Solana bot ended the day even."


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


def test_a_busy_day_keeps_the_headlines_then_every_kind_in_time_order(ledger: Ledger, settings: Settings) -> None:
    t = busy_day(ledger)
    recap = build_page_state(ledger, settings, NOW)["recap"]
    events = recap["events"]
    assert len(events) == RECAP_BEATS_MAX and [e["ts"] for e in events] == sorted(e["ts"] for e in events)
    # 20 rejections, 3 finds, 13 other records (9 decisions, a buy, a halt, two closed trades; the prefilter's skip
    # is not one the film tells)
    assert recap["events_total"] == 20 + 3 + 13
    assert {e["member"] for e in events} <= set(MEMBER_IDS)
    by_text = {e["text"]: e for e in events}
    # the headlines: both trades closed (at the sell's own SOL price, else the day's last money check before it) and
    # the halt, in the page's plain words, pretend money said so
    assert by_text["PY: Sold after the price fell from its high · won +$2.13 (pretend money)"]["tone"] == "good"
    assert by_text[f"PZ: Danger spotted, sold early · lost {MINUS}$2.06 (pretend money)"]["tone"] == "bad"
    halt = next(e for e in events if e["member"] == "risk" and e["ts"] == t[16])
    assert halt["text"].startswith("stopped new buys: ") and halt["tone"] == "bad"
    # then one of each other kind, each in the page's plain words (the same words its bubbles say)
    for member, line in (("strategy", "the buy signal came for HIGGS: bought (pretend money)"),
                         ("broker", "bought HIGGS for 0.1000 SOL (pretend money)"),
                         ("radar", "spotted danger on DUMP: creator sold $1,200"),
                         ("judge", "the AI judge said yes to HIGGS: clean holders"),
                         ("broker", "sold part of HIGGS to take profit (pretend money)"),
                         ("broker", "did not buy PRICEY: the price was not good enough (price impact 4.1%)"),
                         ("cocoon", "PASSED passed the scam check"),
                         ("crawler", "found a new coin: FIRST (70 min old)")):
        assert by_text[line]["member"] == member, line
    assert any(e["member"] == "risk" and e["text"].startswith("refused to buy RISKY: ") for e in events)
    # what a short film drops: the filter's 20 rejections, the drops, a rules-only "yes" (the judge was off), the
    # prefilter's skips, the second judge verdict (one of each kind first)
    assert not any(e["text"].startswith(("threw out", "stopped watching")) for e in events)
    assert not any("RULED" in e["text"] and "judge" in e["text"] for e in events)
    assert not any("BABY" in e["text"] for e in events)
    assert recap["closed"] == [
        {"coin": "PY", "closed_at": t[14], "pnl_usd": 2.13, "result": "won", "why": EXIT_WORDS["trailing_stop"],
         "label": PAPER_LABEL},
        {"coin": "PZ", "closed_at": t[15], "pnl_usd": -2.06, "result": "lost", "why": "Danger spotted, sold early",
         "label": PAPER_LABEL}]
    # 1.00 SOL before the day, 0.95 at its last check (SOL at $110): down 0.05 SOL = $5.50, in pretend money
    assert recap["pretend"]["line"] == "Practice (pretend money): the Solana bot ended the day down $5.50."


def test_every_beat_says_exactly_what_the_pages_plain_words_say(ledger: Ledger, settings: Settings) -> None:
    """The film's line for a record is the page's own plain words for it (plain_event), clipped: the bubbles, the card
    and the film never word the same record two ways."""
    busy_day(ledger)
    events = build_page_state(ledger, settings, NOW)["recap"]["events"]
    raw = recap_module.build_recap(ledger, NOW, tz=LA, mode="paper", words=lambda m, line: line, exit_words=EXIT_WORDS)
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
    assert [(e["text"], e["tone"]) for e in voss] == [
        ("real-money bet: $0.97 on YES · Will real0 happen?", "neutral"),  # the question from the desk's own state
        ("a real-money bet lost $0.97 · lost1", "bad"),  # a market the desk no longer keeps: named as the venue does
        ("the risk manager paused the real-money bets: the record was losing", "bad"),
        ("a real-money bet won $0.03 · Will the Fed hold rates in October?", "good")]
    # the result since start when the day began (+$0.50 then) and when it ended (+$0.50 - $0.97 + $0.03), worked back
    # from the money card's own figure now (+$0.08) minus what settled since
    assert recap["real"] == {
        "label": REAL_LABEL, "start_usd": 0.50, "end_usd": -0.44, "settled": 2, "won": 1,
        "line": "Real money: up $0.50 since start (real money) when the day began, down $0.44 since start when it "
                "ended; 1 of 2 finished bets won."}
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
    seed(ledger)
    memory: dict[str, Any] = {}
    first = recap_state(ledger, settings, NOW, memory)
    assert first["events"] and recap_state(ledger, settings, NOW + 5, memory) is first
    ledger.upsert_position(closed_position("late", NOW - DAY + 7200, 150_000_000))  # yesterday, recorded late
    assert recap_state(ledger, settings, NOW + RECAP_TTL_S - 1, memory) is first  # still the kept one
    again = recap_state(ledger, settings, NOW + RECAP_TTL_S, memory)
    assert again is not first and len(again["closed"]) == 2
    assert recap_state(ledger, make_settings(OWNER_TZ="Europe/Athens"), NOW + RECAP_TTL_S, memory) is not again
    # the owner's midnight: a new day is a new recap at once, whatever the age of the kept one
    assert recap_state(ledger, settings, YDAY_END + DAY - 10, memory)["date"] == "2026-10-07"
    assert recap_state(ledger, settings, YDAY_END + DAY + 10, memory)["date"] == "2026-10-08"
    assert build_recap(ledger, NOW, tz=LA, mode="paper", words=lambda m, x: x, exit_words={})["events"]


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
