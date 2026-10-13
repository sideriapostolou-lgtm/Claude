"""The phone HUD keeps shared account money apart from the bot's realized result."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_page_polymarket import NOW as DESK_NOW
from test_page_polymarket import desk_state, position, save

from nightcrawler.config import Settings
from nightcrawler.ledger import Ledger
from nightcrawler.pagestate import build_page_state, polymarket_desk
from nightcrawler.worldtycoon_data import TYCOON_DATA

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
NOW = 1_800_000_000


def run(tmp_path: Path, value: Any, now: float = NOW, *, raw_crew: bool = False) -> dict[str, Any]:
    script = tmp_path / "tycoon-data.mjs"
    script.write_text(TYCOON_DATA + "\nconst input = " + json.dumps(value) + ";\n"
                      + "const before = JSON.stringify(input);\n"
                      + f"const output = tycoonSummary(input, {now});\n"
                      + "if (JSON.stringify(input) !== before) throw new Error('mutated input');\n"
                      + (f"output.crew = tycoonCrew(input, {now}, output.updated !== null && !output.pageStale, "
                         "output.asOf !== null && !output.deskStale);\n" if raw_crew else "")
                      + "console.log(JSON.stringify(output));\n")
    result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=20, check=True)
    out: dict[str, Any] = json.loads(result.stdout)
    return out


def page() -> dict[str, Any]:
    return {
        "generated_at": NOW - 5,
        "money": {
            "today": {"usd": 999},  # the Solana practice book is never a real HUD source
            "polymarket": {
                "mode": "live", "as_of": NOW - 90,
                "paper": {"today_usd": 888, "open": 50},
                "real": {"cash_usd": 14.22, "cash_at": NOW - 90, "venue_at": NOW - 90,
                         "today_usd": 999.23, "today_pacific": {"date": "2027-01-15",
                             "tz": "America/Los_Angeles", "start": NOW - 3600, "end": NOW + 82800,
                             "as_of": NOW - 90, "status": "ok", "pnl_usd": 0.23, "settled": 1},
                         "open": 2, "at_risk_usd": 24.97, "venue_open": 3,
                         "cost_usd": 26.41, "value_usd": 27.10, "pending": 1, "pending_usd": 9.70},
            },
        },
        "plain": {
            "real": {"on": True, "cash_usd": 14.22, "paused": None, "paused_kind": None},
            "team": [
                {"id": "voss", "name": "Voss", "job": "bets on Polymarket (real money)",
                 "status_word": "working", "latest": "an old bet won", "latest_ts": NOW - 3600},
                {"id": "pip", "name": "Pip", "job": "finds coins (pretend money)",
                 "status_word": "idle", "latest": "old discovery", "latest_ts": NOW - 7200},
                {"id": "mote", "name": "Mote", "job": "keeps tamper-proof records", "status_word": "working"},
            ],
            "finished": [
                {"id": "real-1", "ts": NOW - 300, "who": "voss", "what": "Will Bitcoin finish above its strike?",
                 "result": "won", "usd": 0.23, "real": True, "money": "real money"},
                {"id": "paper-1", "ts": NOW - 10, "who": "jet", "what": "Practice coin",
                 "result": "won", "usd": 999, "real": False, "money": "pretend"},
            ],
        },
        "team": {"members": [
            {"id": "predict", "doing": "Watching the venue's markets.", "last_activity": NOW - 90,
             "events": [{"ts": NOW - 2, "text": "Practice looks good; real money stays off."}],
             "positions": [{"live": True, "question": "Account bet", "side": "long", "p_in": 0.97},
                           {"live": False, "question": "Practice bet", "side": "short", "p_in": 0.62}]},
            {"id": "crawler", "doing": "Nothing new recently.", "last_activity": NOW - 800},
        ]},
    }


def test_account_and_bot_figures_remain_separate(tmp_path: Path) -> None:
    out = run(tmp_path, page())
    assert (out["cash"], out["today"], out["count"], out["value"]) == (14.22, 0.23, 3, 27.10)
    assert out["labels"]["cash"] == "Available cash"
    assert out["labels"]["today"] == "Bot today"
    assert out["labels"]["bets"] == "Account bets"
    assert out["labels"]["betsNote"] == "Includes your own bets"
    assert out["pending"] == {"count": 1, "held": 9.70}  # never added to confirmed bets
    assert out["positions"] == [{"question": "Account bet", "side": "YES", "price": 0.97,
                                 "scope": "account", "owner": "unknown"}]
    assert out["updated"] == NOW - 5 and out["asOf"] == NOW - 90
    assert out["state"] == "on" and out["on"] is True


def test_actual_page_desk_fields_include_owner_open_bets_but_not_owner_profit(
    tmp_path: Path, settings: Settings,
) -> None:
    # A local state fixture only: no keys, clients, orders, or live settings.
    st = desk_state(live_today={"pnl_usd": 0.23, "settled": 1, "won": 1})
    st["positions"]["owner"] = dict(position("owner", live=True, cost_usd=24), rule="owner", owner=True)
    st["owner_pnl_usd"] = -52.38
    st["closed"] = [{"live": True, "owner": False, "settled_at": DESK_NOW - 120, "pnl_usd": 0.23, "won": True}]
    save(settings, st)
    source = polymarket_desk(settings, DESK_NOW)
    out = run(tmp_path, {"generated_at": DESK_NOW, "money": {"polymarket": source}}, now=DESK_NOW)
    assert out["count"] == 8 and out["value"] == pytest.approx(7.95)
    assert out["recorded"] == {"count": 2, "cost": pytest.approx(24.97)}
    assert out["today"] == pytest.approx(0.23)
    assert out["labels"]["betsNote"] == "Includes your own bets"
    assert out["state"] == "off"  # the fixture retains real history in safe paper mode


@pytest.mark.parametrize("value", [None, {}, {"money": None, "plain": None}, {"generated_at": NOW}])
def test_missing_records_never_become_zero(tmp_path: Path, value: Any) -> None:
    out = run(tmp_path, value)
    assert all(out[k] is None for k in ("cash", "today", "count", "value", "on", "asOf"))
    assert out["state"] == "unknown"
    assert out["event"] is None and out["crew"] == [] and out["positions"] == []


def test_reported_zero_and_negative_result_are_not_missing(tmp_path: Path) -> None:
    p = page()
    p["money"]["polymarket"]["real"].update(cash_usd=0, today_usd=-9.81, open=0, at_risk_usd=0, venue_open=0, value_usd=0)
    p["money"]["polymarket"]["real"]["today_pacific"]["pnl_usd"] = -9.81
    out = run(tmp_path, p)
    assert (out["cash"], out["today"], out["count"], out["value"]) == (0, -9.81, 0, 0)
    p["money"]["polymarket"]["as_of"] = None
    out = run(tmp_path, p)
    assert out["cash"] == 0  # a separately reported balance may precede the first complete desk round
    assert out["today"] == -9.81 and out["count"] == 0 and out["value"] == 0
    assert out["recorded"] == {"count": None, "cost": None}
    assert out["state"] == "unknown"


@pytest.mark.parametrize("change", [None, {"status": "incomplete"}, {"status": "unavailable"},
                                   {"tz": "UTC"}, {"end": NOW}, {"start": NOW + 1},
                                   {"as_of": NOW - 7200}, {"pnl_usd": False}])
def test_pacific_today_never_relabels_the_utc_total(tmp_path: Path, change: dict[str, Any] | None) -> None:
    p = page()
    real = p["money"]["polymarket"]["real"]
    assert real["today_usd"] == 999.23
    if change is None:
        real.pop("today_pacific")
    else:
        real["today_pacific"].update(change)
    out = run(tmp_path, p)
    assert out["today"] is None
    assert out["labels"]["todayNote"] == "Since midnight PT"


def test_pacific_profit_has_its_own_checked_age_and_true_zero(tmp_path: Path) -> None:
    p = page()
    p["money"]["polymarket"]["real"]["today_pacific"].update(pnl_usd=0, as_of=NOW - 900)
    out = run(tmp_path, p)
    assert out["today"] == 0 and out["todayStatus"] == "ok"
    assert out["todayAge"] == 900 and out["todayStale"]
    assert not out["cashStale"] and not out["deskStale"]


def test_account_holdings_do_not_fall_back_to_old_desk_positions(tmp_path: Path) -> None:
    p = page()
    real = p["money"]["polymarket"]["real"]
    real.update(venue_open=0, value_usd=0)  # owner sold; desk still records two bets
    out = run(tmp_path, p)
    assert (out["count"], out["value"]) == (0, 0)
    assert out["recorded"] == {"count": 2, "cost": 24.97}
    assert "not the current venue book" in out["positionsNote"]
    real.pop("venue_open")
    assert run(tmp_path, p)["count"] is None
    real.update(venue_open=3, venue_at=None)
    out = run(tmp_path, p)
    assert out["count"] is None and out["value"] is None


def test_spendable_cash_and_venue_balance_are_not_profit(tmp_path: Path) -> None:
    p = page()
    real = p["money"]["polymarket"]["real"]
    real.update(cash_usd=4.59, cash_reported_usd=14.39, buying_power_usd=4.59)
    out = run(tmp_path, p)
    assert (out["cash"], out["reportedCash"], out["buyingPower"]) == (4.59, 14.39, 4.59)
    assert out["today"] == 0.23  # neither account balance nor a cash difference
    assert out["labels"]["todayNote"] == "Since midnight PT"
    p["generated_at"] = NOW  # a fresh web response cannot freshen the balance
    real["cash_at"] = NOW - 1200
    out = run(tmp_path, p)
    assert out["cashAge"] == 1200 and out["cashStale"]


def test_practice_cannot_fill_the_real_cards(tmp_path: Path) -> None:
    p = page()
    p["money"]["polymarket"].update(mode="paper", real=None)
    p["plain"]["real"].update(on=False, cash_usd=None)
    p["plain"]["finished"] = p["plain"]["finished"][1:]
    out = run(tmp_path, p)
    assert (out["cash"], out["today"], out["count"], out["value"]) == (None, None, None, None)
    assert out["state"] == "off" and out["event"] is None
    p["plain"]["real"]["on"] = True  # another real desk cannot turn Polymarket on in this view
    assert run(tmp_path, p)["state"] == "off"


def test_real_history_remains_visible_after_new_bets_are_off(tmp_path: Path) -> None:
    p = page()
    p["money"]["polymarket"]["mode"] = "paper"
    out = run(tmp_path, p)
    assert out["state"] == "off" and out["today"] == 0.23 and out["value"] == 27.10
    assert out["stateText"] == "No new bot bets"


def test_fresh_page_does_not_make_an_old_desk_or_cash_fresh(tmp_path: Path) -> None:
    p = page()
    p["money"]["polymarket"]["as_of"] = NOW - 601
    out = run(tmp_path, p)
    assert out["state"] == "stale" and out["deskStale"] and not out["pageStale"]
    assert out["crew"][0]["status"] == "unknown"
    assert "Kalshi" in out["crew"][0]["doing"]
    assert out["crew"][1]["status"] == "idle"
    p["money"]["polymarket"]["as_of"] = NOW - 90
    p["money"]["polymarket"]["real"].update(cash_at=NOW - 7200, venue_at=NOW - 900)
    out = run(tmp_path, p)
    assert out["cashStale"] and out["venueStale"] and out["state"] == "on"
    p["generated_at"] = NOW - 61
    out = run(tmp_path, p)
    assert out["pageStale"] and out["state"] == "stale"
    assert all(c["status"] == "unknown" for c in out["crew"])


def test_pause_and_invalid_timestamps_are_explicit(tmp_path: Path) -> None:
    p = page()
    p["plain"]["real"].update(paused_kind="risk", paused="Risk manager paused new real bets.")
    out = run(tmp_path, p)
    assert out["state"] == "paused" and out["pauseKind"] == "risk"
    assert out["stateText"] == "Risk manager paused new real bets."
    p["money"]["polymarket"]["as_of"] = NOW + 61
    out = run(tmp_path, p)
    assert out["asOf"] is None and out["state"] == "unknown"
    assert out["crew"][0]["status"] == "unknown"
    p["generated_at"] = None
    assert all(c["status"] == "unknown" for c in run(tmp_path, p)["crew"])


def test_owner_account_total_cannot_claim_the_bot_is_full(tmp_path: Path, settings: Settings) -> None:
    st = desk_state(live_today={"pnl_usd": 0.23, "settled": 1, "won": 1})
    st["mode"] = "live"  # stored display fixture only; settings stay paper and no client is started
    st["positions"]["owner"] = dict(position("owner", live=True, cost_usd=24), rule="owner", owner=True)
    save(settings, st)
    with Ledger(tmp_path / "display.db") as ledger:
        source = build_page_state(ledger, settings, DESK_NOW)
    assert source["plain"]["real"]["paused_kind"] == "full"  # upstream compares shared $24.97 to bot cap
    assert source["money"]["polymarket"]["status"] is None
    out = run(tmp_path, source, now=DESK_NOW)
    assert out["count"] == 8 and out["value"] == pytest.approx(7.95)
    assert out["recorded"] == {"count": 2, "cost": pytest.approx(24.97)}
    assert out["state"] == "on" and out["pauseKind"] is None
    assert out["stateText"] == "Real-money desk is on"


@pytest.mark.parametrize("kind", ["full", "room", None])
def test_untrusted_capacity_sentence_cannot_pause_the_bot(tmp_path: Path, kind: str | None) -> None:
    p = page()
    p["plain"]["real"].update(paused_kind=kind, paused="Waiting for an open bet to finish.")
    out = run(tmp_path, p)
    assert out["state"] == "on" and out["pauseKind"] is None


def test_explicit_desk_status_is_preserved_in_live_and_off_modes(tmp_path: Path) -> None:
    p = page()
    text = "Bot open-money cap reached: no new real buys until a position closes."
    p["money"]["polymarket"]["status"] = text
    out = run(tmp_path, p)
    assert out["state"] == "paused" and out["pauseKind"] == "reported"
    assert out["stateText"] == out["deskStatus"] == text
    text = "Live was switched off by the total-loss cap; the desk stays on paper until the owner resets it."
    p["money"]["polymarket"].update(mode="paper", status=text)
    out = run(tmp_path, p)
    assert out["state"] == "off" and out["pauseKind"] is None
    assert out["stateText"] == out["deskStatus"] == text


@pytest.mark.parametrize("guard", [{"paused": True}, {"real": {"paused": True}}])
def test_actual_guard_pause_survives_an_incorrect_capacity_message(tmp_path: Path, guard: dict[str, Any]) -> None:
    p = page()
    p["money"]["polymarket"]["guard"] = guard
    p["plain"]["real"].update(paused_kind="full", paused="Shared account is full.")
    out = run(tmp_path, p)
    assert out["state"] == "paused" and out["pauseKind"] == "risk"
    assert out["stateText"] == "Risk manager paused new real bets."


def test_explicit_daily_stop_is_preserved(tmp_path: Path) -> None:
    p = page()
    p["plain"]["real"].update(paused_kind="day", paused="Daily limit reached.")
    out = run(tmp_path, p)
    assert out["state"] == "paused" and out["pauseKind"] == "day"
    assert out["stateText"] == "Daily limit reached."
    p["money"]["polymarket"]["status"] = "Daily loss cap reached: no more real buys today."
    assert run(tmp_path, p)["stateText"] == p["money"]["polymarket"]["status"]


def test_polymarket_history_and_practice_cannot_fill_the_kalshi_activity_feed(tmp_path: Path) -> None:
    p = page()
    out = run(tmp_path, p)
    assert out["event"] is None and out["activity"] == []
    assert out["activitySources"] == {"polymarket_us": False, "kalshi": False}
    assert out["today"] == .23  # Polymarket remains available in secondary Money.
    assert out["focus"]["today"] is None and out["focus"]["cash"] is None
    p["plain"]["finished"] *= 20
    assert run(tmp_path, p)["event"] is None


def test_crew_status_is_the_reported_work_not_a_replayed_old_win(tmp_path: Path) -> None:
    crew = run(tmp_path, page(), raw_crew=True)["crew"]
    assert crew[0]["job"] == "Trading" and crew[0]["practice"] is False
    assert crew[0]["doing"] == "Watching the venue's markets." and crew[0]["age"] == 90
    assert "old bet won" not in crew[0]["doing"]
    assert crew[1]["job"] == "Finding coins" and crew[1]["practice"] is True
    assert crew[2]["job"] == "Records" and crew[2]["practice"] is None


def test_crew_status_description_and_age_follow_the_same_member(tmp_path: Path) -> None:
    p = page()
    p["plain"]["team"][0]["status_word"] = "stuck"  # Voss also plays the practice AI judge
    p["team"]["members"][0]["status"] = "working"
    p["team"]["members"].append({"id": "judge", "status": "blocked", "why": "Judge unavailable.",
                                    "last_activity": NOW - 5})
    p["plain"]["team"].append({"id": "nyx", "name": "Nyx", "status_word": "stuck",
                                "job": "checks each coin for scams and waits for the buy signal (pretend money)"})
    p["team"]["members"].extend([
        {"id": "cocoon", "status": "working", "doing": "Checking coins.", "last_activity": NOW - 2},
        {"id": "radar", "status": "blocked", "why": "Danger check unavailable.", "last_activity": NOW - 30},
    ])
    crew = {c["key"]: c for c in run(tmp_path, p, raw_crew=True)["crew"]}
    assert crew["voss"]["status"] == "working" and crew["voss"]["age"] == 90
    assert crew["voss"]["doing"] == "Watching the venue's markets."
    assert crew["nyx"]["job"] == "Coin checks" and crew["nyx"]["practice"] is True
    assert crew["nyx"]["status"] == "stuck" and crew["nyx"]["age"] == 30
    assert crew["nyx"]["doing"] == "Danger check unavailable."


def test_voss_recorded_work_preserves_both_real_and_practice_labels(tmp_path: Path) -> None:
    p = page()
    work = "Watching 240 markets; real money today +0.23 $. Paper (pretend): 2 open; -20.03 $."
    p["team"]["members"][0].update(why="A round finished recently.", doing=work)
    voss = run(tmp_path, p, raw_crew=True)["crew"][0]
    assert voss["recordedWork"] == work
    assert voss["statusReason"] == voss["doing"] == "A round finished recently."
    assert voss["jobDetail"] == p["plain"]["team"][0]["job"]
    p["generated_at"] = NOW - 61
    voss = run(tmp_path, p, raw_crew=True)["crew"][0]
    assert voss["status"] == "unknown" and voss["doing"].startswith("Last report: ")
    assert voss["recordedWork"] == work and voss["statusReason"] == "A round finished recently."


def test_mote_recorded_work_and_status_reason_follow_the_selected_role(tmp_path: Path) -> None:
    p = page()
    p["team"]["members"].extend([
        {"id": "receipts", "status": "working", "why": "A new record arrived.",
         "doing": "100 entries sealed; checked: nothing was edited.", "last_activity": NOW - 2},
        {"id": "coach", "status": "blocked", "why": "The learning system failed.",
         "doing": "Practice learning unavailable.", "last_activity": NOW - 80},
    ])
    mote = next(c for c in run(tmp_path, p, raw_crew=True)["crew"] if c["key"] == "mote")
    assert mote["status"] == "stuck" and mote["age"] == 80
    assert mote["recordedWork"] == "Practice learning unavailable."
    assert mote["statusReason"] == mote["doing"] == "The learning system failed."
    assert mote["practice"] is None  # records are shared; the selected learning report labels its own scope
    p["team"]["members"][-1]["status"] = "idle"
    mote = next(c for c in run(tmp_path, p, raw_crew=True)["crew"] if c["key"] == "mote")
    assert mote["status"] == "working" and mote["age"] == 2
    assert mote["recordedWork"] == "100 entries sealed; checked: nothing was edited."
    assert mote["statusReason"] == mote["doing"] == "A new record arrived."


def test_invalid_money_is_not_coerced(tmp_path: Path) -> None:
    p = page()
    p["plain"]["real"]["cash_usd"] = None
    p["money"]["polymarket"]["real"].update(cash_usd="14.22", today_usd=False, open=1.5, at_risk_usd=-20,
                                          venue_open=1.5, value_usd=-20)
    p["money"]["polymarket"]["real"]["today_pacific"]["pnl_usd"] = False
    out = run(tmp_path, p)
    assert all(out[k] is None for k in ("cash", "today", "count", "value"))


def test_adapter_has_no_browser_or_money_side_effects() -> None:
    # A reported per-window limit is plain data; browser-global access is forbidden.
    for forbidden in ("document", "window.", "window[", "fetch(", "Date.now", "new Date()", "performance.", "localStorage", "THREE", "simT"):
        assert forbidden not in TYCOON_DATA
    assert "// >>> tycoon data (pure)" in TYCOON_DATA and "// <<< tycoon data" in TYCOON_DATA


@pytest.mark.parametrize(("profit", "level"), [(-5, 0), (0, 0), (.009, 0), (.01, 1), (.24, 1),
                                               (.25, 2), (1, 3), (5, 4), (10, 5), (9999, 5)])
def test_daily_gardens_follow_actual_net_profit_milestones(tmp_path: Path, profit: float, level: int) -> None:
    p = kalshi_page()
    p["money"]["connections"]["kalshi"]["today_pacific"]["pnl_usd"] = profit
    out = run(tmp_path, p)
    assert out["growth"] == {
        "qualified": True, "level": level, "pnl_usd": profit, "thresholds": [.01, .25, 1, 5, 10],
        "label": "Kalshi bot profit since midnight PT", "date": "2027-01-15", "reason": None,
    }


def test_cash_practice_utc_profit_and_event_replays_do_not_grow_gardens(tmp_path: Path) -> None:
    p = kalshi_page()
    expected = run(tmp_path, p)["growth"]
    p["money"]["polymarket"]["real"].update(cash_usd=50000, today_usd=80000, since_start_usd=90000)
    p["money"]["polymarket"]["paper"]["today_usd"] = 100000
    p["town"] = {"goal": {"real_today_usd": 80000, "tier": {"rank": 5}}}
    p["plain"]["finished"][0]["usd"] = 100000
    p["plain"]["finished"] *= 20
    assert run(tmp_path, p)["growth"] == expected


@pytest.mark.parametrize("source", ["page", "desk", "profit", "missing_book", "incomplete", "midnight"])
def test_unconfirmed_or_stale_profit_cannot_claim_daily_upgrades(tmp_path: Path, source: str) -> None:
    p = kalshi_page()
    book = p["money"]["connections"]["kalshi"]
    if source == "page":
        p["generated_at"] = NOW - 61
    elif source == "desk":
        book["as_of"] = NOW - 61
    elif source == "profit":
        book["today_pacific"]["as_of"] = NOW - 61
    elif source == "missing_book":
        p["money"]["connections"].pop("kalshi")
    elif source == "incomplete":
        book["today_pacific"]["status"] = "incomplete"
    else:
        book["today_pacific"]["end"] = NOW
    growth = run(tmp_path, p)["growth"]
    assert growth["qualified"] is False and growth["level"] is None
    assert growth["reason"]


def test_losses_remove_daily_decorations_and_paper_mode_keeps_real_results(tmp_path: Path) -> None:
    p = kalshi_page()
    p["money"]["connections"]["kalshi"]["today_pacific"]["pnl_usd"] = 5
    assert run(tmp_path, p)["growth"]["level"] == 4
    p["money"]["speeddesk"]["kalshi_live"].update(mode="paper", active=False, real_orders_available=False)
    p["money"]["connections"]["kalshi"]["today_pacific"]["pnl_usd"] = .20
    assert run(tmp_path, p)["growth"]["level"] == 1
    assert run(tmp_path, {})["growth"]["level"] is None


def kalshi() -> dict[str, Any]:
    return {
        "as_of": NOW - 5, "cash_at": NOW - 10, "cash_usd": 25, "mode": "live", "active": True,
        "authenticated": True, "real_orders_available": True, "stale": False,
        "has_real_exposure": True, "at_risk_usd": 1.98, "positions": 1, "open_orders": 2, "reserved_usd": .99,
        "today": {"day": datetime.fromtimestamp(NOW, UTC).date().isoformat(), "pnl_usd": -.34,
                  "fees_usd": .013, "locked_usd": .10, "directional_usd": -.44},
        "total": {"pnl_usd": .87},
        "practice_twin": {"pnl_usd": 10000},
    }


def kalshi_page() -> dict[str, Any]:
    p = page()
    p["money"]["speeddesk"] = {"kalshi_live": kalshi()}
    p["money"]["connections"] = {"version": 1, "kalshi": {
        "as_of": NOW - 5, "status": "ok", "stale": False,
        "today_pacific": {**p["money"]["polymarket"]["real"]["today_pacific"], "as_of": NOW - 5},
    }}
    return p


def test_kalshi_is_a_separate_real_account_with_its_own_utc_day(tmp_path: Path) -> None:
    p = page()
    expected_growth = run(tmp_path, p)["growth"]
    p["money"]["speeddesk"] = {"mode": "paper", "kalshi_live": kalshi(), "today": {"pnl_usd": 20000}}
    out = run(tmp_path, p)
    account = out["accounts"]["kalshi"]
    assert account["state"] == "live" and account["active"] is True
    assert (account["cash"], account["today"], account["total"]) == (25, -.34, .87)
    assert (account["exposure"], account["positions"], account["orders"]) == (1.98, 1, 2)
    assert account["todayNote"] == "Bot profit since midnight UTC"
    assert (out["cash"], out["today"]) == (14.22, .23)
    assert out["growth"] == expected_growth


@pytest.mark.parametrize("change", [{"as_of": NOW - 61}, {"as_of": None}, {"stale": True},
                                    {"active": False}, {"authenticated": False}, {"real_orders_available": False}])
def test_kalshi_live_claim_requires_its_current_sanitized_report(tmp_path: Path, change: dict[str, Any]) -> None:
    p = page()
    p["money"]["speeddesk"] = {"kalshi_live": {**kalshi(), **change}}
    account = run(tmp_path, p)["accounts"]["kalshi"]
    assert account["active"] is False and account["state"] != "live"


def test_kalshi_stale_cash_and_utc_midnight_stay_visible_as_unknown_age_or_date(tmp_path: Path) -> None:
    p = page()
    account = kalshi()
    account["cash_at"] = NOW - 61
    account["today"]["day"] = "2000-01-01"
    p["money"]["speeddesk"] = {"kalshi_live": account}
    out = run(tmp_path, p)["accounts"]["kalshi"]
    assert out["cash"] == 25 and out["cashStale"] is True
    assert out["today"] is None and out["todayStale"] is True
    account["cash_at"] = None
    assert run(tmp_path, p)["accounts"]["kalshi"]["cash"] is None
    p["generated_at"] = NOW - 61
    assert run(tmp_path, p)["accounts"]["kalshi"]["state"] == "stale"


def test_kalshi_paper_mode_keeps_open_real_exposure_explicit(tmp_path: Path) -> None:
    p = page()
    account = kalshi()
    account.update(mode="paper", active=False, real_orders_available=False, cleanup_pending=True)
    p["money"]["speeddesk"] = {"kalshi_live": account}
    out = run(tmp_path, p)["accounts"]["kalshi"]
    assert out["state"] == "exposure" and out["practice"] is False and out["cleanupPending"] is True
    account.update(has_real_exposure=False, at_risk_usd=0, positions=0, open_orders=0, reserved_usd=0)
    assert run(tmp_path, p)["accounts"]["kalshi"]["state"] == "practice"
    out = run(tmp_path, {})["accounts"]["kalshi"]
    assert out["state"] == "unknown" and out["cash"] is None and out["today"] is None


@pytest.mark.parametrize("change", [
    {"lock_only": True},
    {"reason": "Daily loss stop; only completing half-filled pairs before the close"},
    {"total_halted": True, "lock_only": True},
])
def test_pair_completion_is_real_money_without_permission_for_new_bets(tmp_path: Path, change: dict[str, Any]) -> None:
    p = page()
    p["money"]["speeddesk"] = {"kalshi_live": {**kalshi(), **change}}
    out = run(tmp_path, p)["accounts"]["kalshi"]
    assert out["active"] is True and out["practice"] is False
    assert out["locksOnly"] is True and out["newRiskAllowed"] is False
    assert out["state"] == "pairs only"
    assert "new bets are stopped" in out["stateText"]
    assert "may exceed these budgets or loss stops" in out["limitsNote"]
    assert "pair-completion reservations do not" in out["reserveNote"]
    assert "Completing existing pairs may still use real cash" in out["stopNote"]


@pytest.mark.parametrize("change", [
    {"total_halted": True},
    {"total_halted": True, "lock_only": False,
     "reason": "Total loss stop; only completing half-filled pairs before the close"},
    {"total_halted": True, "reason": "Previously only completing half-filled pairs before the close; now stopped"},
])
def test_total_stop_alone_never_invents_pair_completion_permission(tmp_path: Path, change: dict[str, Any]) -> None:
    p = page()
    p["money"]["speeddesk"] = {"kalshi_live": {**kalshi(), **change}}
    out = run(tmp_path, p)["accounts"]["kalshi"]
    assert out["reportedLocksOnly"] is False and out["locksOnly"] is False
    assert out["active"] is False and out["newRiskAllowed"] is False


@pytest.mark.parametrize("change", [{"integrity_error": "order_fill_count_mismatch"},
                                    {"integrity_reset": "positions_open"}])
def test_accounting_problem_overrides_any_active_live_claim(tmp_path: Path, change: dict[str, Any]) -> None:
    p = page()
    p["money"]["speeddesk"] = {"kalshi_live": {**kalshi(), "lock_only": True, **change}}
    out = run(tmp_path, p)["accounts"]["kalshi"]
    assert out["active"] is False and out["newRiskAllowed"] is False and out["locksOnly"] is False
    assert out["state"] == "blocked" and out["practice"] is False
    assert "real buys are blocked" in out["integrityNote"]
    assert out["integrityError"] == change.get("integrity_error", "")
    assert out["integrityReset"] == change.get("integrity_reset", "")
    if out["integrityReset"]:
        assert out["integrityResetNote"] == "Accounting reset: positions remain open."


@pytest.mark.parametrize(("code", "explanation"), [
    ("order_fill_count_mismatch", "fewer filled contracts than the trade receipts"),
    ("order_terminal_regressed", "an order marked finished now shows contracts still waiting to fill"),
    ("fill_changed", "a previously recorded trade receipt changed"),
    ("settlement_net_payout_mismatch", "the settlement payout does not match the recorded holdings"),
    ("fill_after_terminal_confirmation", "another fill arrived after its order was confirmed finished"),
    ("fill_exceeded_reserved_terms", "a fill exceeded its reserved size, price or fees"),
    ("future_integrity_check", "Kalshi records need review; real buys are blocked."),
])
def test_accounting_warning_explains_confirmed_problem_without_exposing_internal_code(
    tmp_path: Path, code: str, explanation: str,
) -> None:
    p = page()
    p["money"]["speeddesk"] = {"kalshi_live": {**kalshi(), "integrity_error": code}}
    out = run(tmp_path, p)["accounts"]["kalshi"]
    assert explanation in out["integrityNote"]
    assert code not in out["integrityNote"]
    assert out["integrityError"] == code  # preserved for programmatic diagnostics only
    assert out["active"] is False


def test_restricted_report_can_go_stale_without_claiming_trading_or_new_account_check(tmp_path: Path) -> None:
    p = page()
    p["money"]["speeddesk"] = {"kalshi_live": {**kalshi(), "as_of": NOW - 61, "lock_only": True}}
    out = run(tmp_path, p)["accounts"]["kalshi"]
    assert out["state"] == "stale" and out["reportedLocksOnly"] is True
    assert out["active"] is False and out["locksOnly"] is False and out["newRiskAllowed"] is False
    assert out["accountAt"] is None and out["accountAge"] is None and out["accountStale"] is True
    assert out["cashAt"] == NOW - 10  # the heartbeat never replaces a cash observation


def test_saved_profit_mismatch_explains_unknown_without_replacing_it_with_zero(tmp_path: Path) -> None:
    p = page()
    p["money"]["polymarket"]["real"]["today_pacific"].update(
        status="incomplete", reason="day_book_mismatch", pnl_usd=None)
    out = run(tmp_path, p)
    assert out["today"] is None and out["todayStatus"] == "incomplete"
    assert out["todayReason"] == "Polymarket profit today is unverified: saved result totals do not match the daily book."
    assert out["growth"]["qualified"] is False and "Kalshi" in out["growth"]["reason"]
    assert out["cash"] == 14.22


def test_research_shows_observations_only_and_never_creates_financial_growth(tmp_path: Path) -> None:
    p = page()
    expected_growth = run(tmp_path, p)["growth"]
    p["money"]["speeddesk"] = {"as_of": NOW - 2, "stale": False, "status": "Watching Bitcoin",
                               "today": {"day": datetime.fromtimestamp(NOW, UTC).date().isoformat(),
                                         "fills": 100, "pnl_usd": 9999}}
    p["skipwatch"] = {"as_of": NOW - 2, "wallet_fills": 200, "status": "Recording public trades"}
    p["weatherwatch"] = {"as_of": NOW - 119, "active_watches": 3, "status": "Observing weather",
                         "today": {"conditional_hold_pnl_usd": 9999}}
    out = run(tmp_path, p)
    assert out["growth"] == expected_growth
    assert [(r["scope"], r["count"]) for r in out["research"][:3]] == [("PRACTICE", 100), ("READ ONLY", 200), ("READ ONLY", 3)]
    assert all(r["state"] == "observing" for r in out["research"][:3])
    assert all(r["state"] == "unknown" and r["count"] is None for r in out["research"][3:])
    assert all(r["realOrders"] is False for r in out["research"])
    p["weatherwatch"]["as_of"] = NOW - 121
    assert run(tmp_path, p)["research"][2]["state"] == "unknown"
    p["generated_at"] = NOW - 61
    assert all(r["current"] is False for r in run(tmp_path, p)["research"])
