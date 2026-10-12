"""The phone HUD keeps shared account money apart from the bot's realized result."""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
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


def run(tmp_path: Path, value: Any, now: float = NOW) -> dict[str, Any]:
    script = tmp_path / "tycoon-data.mjs"
    script.write_text(TYCOON_DATA + "\nconst input = " + json.dumps(value) + ";\n"
                      + "const before = JSON.stringify(input);\n"
                      + f"const output = tycoonSummary(input, {now});\n"
                      + "if (JSON.stringify(input) !== before) throw new Error('mutated input');\n"
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
                         "today_usd": 0.23, "open": 2, "at_risk_usd": 24.97, "venue_open": 3,
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
    out = run(tmp_path, p)
    assert (out["cash"], out["today"], out["count"], out["value"]) == (0, -9.81, 0, 0)
    p["money"]["polymarket"]["as_of"] = None
    out = run(tmp_path, p)
    assert out["cash"] == 0  # a separately reported balance may precede the first complete desk round
    assert out["today"] is None and out["count"] == 0 and out["value"] == 0
    assert out["recorded"] == {"count": None, "cost": None}
    assert out["state"] == "unknown"


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
    assert out["labels"]["todayNote"] == "Since 00:00 UTC"
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
    assert out["crew"][0]["doing"].startswith("Last report: ")
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


def test_only_explicit_real_results_enter_the_timestamped_feed(tmp_path: Path) -> None:
    p = page()
    out = run(tmp_path, p)
    assert out["event"]["id"] == "real-1" and out["event"]["age"] == 300
    assert out["event"]["text"].startswith("Won $0.23")
    assert run(tmp_path, p)["event"] == out["event"]  # no poll creates a fresh event or timestamp
    bad = copy.deepcopy(p["plain"]["finished"][0])
    bad.update(id="ambiguous", ts=NOW - 1, real=True, money="pretend")
    future = copy.deepcopy(bad)
    future.update(id="future", ts=NOW + 61, money="real money")
    p["plain"]["finished"] = [bad, future]
    assert run(tmp_path, p)["event"] is None


def test_crew_status_is_the_reported_work_not_a_replayed_old_win(tmp_path: Path) -> None:
    crew = run(tmp_path, page())["crew"]
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
    crew = {c["key"]: c for c in run(tmp_path, p)["crew"]}
    assert crew["voss"]["status"] == "working" and crew["voss"]["age"] == 90
    assert crew["voss"]["doing"] == "Watching the venue's markets."
    assert crew["nyx"]["job"] == "Coin checks" and crew["nyx"]["practice"] is True
    assert crew["nyx"]["status"] == "stuck" and crew["nyx"]["age"] == 30
    assert crew["nyx"]["doing"] == "Danger check unavailable."


def test_voss_recorded_work_preserves_both_real_and_practice_labels(tmp_path: Path) -> None:
    p = page()
    work = "Watching 240 markets; real money today +0.23 $. Paper (pretend): 2 open; -20.03 $."
    p["team"]["members"][0].update(why="A round finished recently.", doing=work)
    voss = run(tmp_path, p)["crew"][0]
    assert voss["recordedWork"] == work
    assert voss["statusReason"] == voss["doing"] == "A round finished recently."
    assert voss["jobDetail"] == p["plain"]["team"][0]["job"]
    p["generated_at"] = NOW - 61
    voss = run(tmp_path, p)["crew"][0]
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
    mote = next(c for c in run(tmp_path, p)["crew"] if c["key"] == "mote")
    assert mote["status"] == "stuck" and mote["age"] == 80
    assert mote["recordedWork"] == "Practice learning unavailable."
    assert mote["statusReason"] == mote["doing"] == "The learning system failed."
    assert mote["practice"] is None  # records are shared; the selected learning report labels its own scope
    p["team"]["members"][-1]["status"] = "idle"
    mote = next(c for c in run(tmp_path, p)["crew"] if c["key"] == "mote")
    assert mote["status"] == "working" and mote["age"] == 2
    assert mote["recordedWork"] == "100 entries sealed; checked: nothing was edited."
    assert mote["statusReason"] == mote["doing"] == "A new record arrived."


def test_invalid_money_is_not_coerced(tmp_path: Path) -> None:
    p = page()
    p["plain"]["real"]["cash_usd"] = None
    p["money"]["polymarket"]["real"].update(cash_usd="14.22", today_usd=False, open=1.5, at_risk_usd=-20,
                                          venue_open=1.5, value_usd=-20)
    out = run(tmp_path, p)
    assert all(out[k] is None for k in ("cash", "today", "count", "value"))


def test_adapter_has_no_browser_or_money_side_effects() -> None:
    for forbidden in ("document", "window", "fetch(", "Date.", "performance.", "localStorage", "THREE", "simT"):
        assert forbidden not in TYCOON_DATA
    assert "// >>> tycoon data (pure)" in TYCOON_DATA and "// <<< tycoon data" in TYCOON_DATA
