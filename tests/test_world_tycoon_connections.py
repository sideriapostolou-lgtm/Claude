"""Real desks drive the town without counting cash, orders or practice as profit."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from test_world_tycoon_data import NOW, kalshi, page, run


def connected() -> dict[str, Any]:
    value = page()
    value["money"]["speeddesk"] = {"kalshi_live": kalshi()}
    day = value["money"]["polymarket"]["real"]["today_pacific"]
    venues = {}
    for name in ("polymarket_us", "kalshi"):
        venues[name] = {"as_of": NOW - 5, "status": "ok", "stale": False, "positions": [], "orders": [], "events": [],
                        "issues": [], "today_pacific": {**day, "as_of": NOW - 5,
                                                          "pnl_usd": .23 if name == "polymarket_us" else .10}}
    value["money"]["connections"] = {"version": 1, **venues}
    return value


def event(venue: str, kind: str = "fill", **kwargs: Any) -> dict[str, Any]:
    return {"id": venue + "-event", "venue": venue, "type": kind, "ts": NOW - 8, "real": True,
            "scope": "bot", "qualified": True, "source_at": NOW - 5, "text": "Filled 1 YES contract",
            "pnl_usd": 999, "fee_usd": .0034, **kwargs}


def test_both_cash_accounts_stay_separate_and_growth_uses_only_kalshi_pacific_day(tmp_path: Path) -> None:
    p = connected()
    p["money"]["today"] = {"usd": 100000}
    p["money"]["connections"]["kalshi"]["orders"] = [{"reserved_usd": 500}]
    out = run(tmp_path, p)
    assert (out["cash"], out["accounts"]["kalshi"]["cash"]) == (14.22, 25)
    assert out["today"] == .23  # compatibility: always the PM Pacific book
    assert out["accounts"]["kalshi"]["today"] == -.34  # existing UTC stop day
    assert out["accounts"]["kalshi"]["todayPacific"]["value"] == .10
    assert out["business"]["today"] == pytest.approx(.33)
    assert out["growth"]["level"] == 1
    assert out["growth"]["pnl_usd"] == .10
    assert out["focus"]["cash"] == 25 and out["focus"]["today"] == .10
    p["money"]["connections"]["kalshi"]["today_pacific"]["pnl_usd"] = -1
    assert run(tmp_path, p)["growth"]["level"] == 0


@pytest.mark.parametrize("change", [
    {"stale": True}, {"as_of": NOW - 61}, {"as_of": None}, {"status": "incomplete"},
    {"today_pacific": {"status": "incomplete", "pnl_usd": 100}},
])
def test_missing_or_stale_kalshi_book_cannot_unlock_gardens(tmp_path: Path, change: dict[str, Any]) -> None:
    p = connected()
    p["money"]["connections"]["kalshi"].update(change)
    out = run(tmp_path, p)
    assert out["growth"]["qualified"] is False and out["growth"]["level"] is None
    assert out["business"]["today"] is None


def test_distinct_dates_and_pacific_midnight_invalidate_combined_profit(tmp_path: Path) -> None:
    p = connected()
    p["money"]["connections"]["kalshi"]["today_pacific"]["date"] = "2000-01-01"
    assert run(tmp_path, p)["growth"]["qualified"] is False
    p = connected()
    out = run(tmp_path, p, NOW + 82800)
    assert out["business"]["today"] is None


def test_main_activity_is_kalshi_only_and_other_venue_remains_in_secondary_money(tmp_path: Path) -> None:
    p = connected()
    p["money"]["connections"]["polymarket_us"]["events"] = [event("polymarket_us", "settlement", pnl_usd=.23)]
    p["money"]["connections"]["kalshi"]["events"] = [
        event("kalshi", id="fill", ts=NOW - 2),
        event("kalshi", "order", id="order", ts=NOW - 4, text="Order submitted; not filled"),
        event("kalshi", "settlement", id="practice", real=False),
    ]
    out = run(tmp_path, p)
    assert [e["kind"] for e in out["activity"]] == ["fill", "order"]
    assert [e["usd"] for e in out["activity"]] == [None, None]
    assert [e["kind"] for e in out["business"]["activity"]] == ["fill", "order", "settlement"]
    assert out["event"]["text"] == "Kalshi · Filled 1 YES contract"
    assert out["event"]["fee"] == .0034  # fee never rounded to a false zero in the read model
    assert all(e["current"] for e in out["activity"])
    assert out["activitySources"] == {"polymarket_us": False, "kalshi": True}


def test_wrong_venue_unqualified_future_and_owner_records_are_never_misattributed(tmp_path: Path) -> None:
    p = connected()
    p["money"]["connections"]["kalshi"]["events"] = [
        event("polymarket_us", id="wrong-venue"), event("kalshi", id="future", ts=NOW + 100),
        event("kalshi", id="unqualified", qualified=False),
        event("kalshi", id="owner", scope="owner", text="Owner’s position settled"),
    ]
    out = run(tmp_path, p)
    assert {e["id"] for e in out["activity"]} == {"unqualified", "owner"}
    assert next(e for e in out["activity"] if e["id"] == "unqualified")["current"] is False
    assert next(e for e in out["activity"] if e["id"] == "owner")["text"].startswith("Kalshi · Your activity")
    p["generated_at"] = NOW - 61
    assert not any(e["current"] for e in run(tmp_path, p)["activity"])


def test_recorded_inventory_keeps_ownership_and_partial_order_reservations(tmp_path: Path) -> None:
    p = connected()
    raw = p["money"]["connections"]
    raw["kalshi"]["positions_basis"] = "Bot fills; not a current venue position snapshot"
    raw["kalshi"]["positions"] = [{"scope": "bot", "side": "yes", "title": "BTC window",
                                    "quantity": 1, "cost_usd": .48, "fee_usd": .004}]
    raw["kalshi"]["orders"] = [{"status": "cancel_requested", "quantity": 3, "filled_quantity": 1,
                                 "remaining_quantity": 2, "reserved_usd": .99}]
    raw["polymarket_us"]["positions"] = [{"scope": "owner", "title": "Your bet"}]
    out = run(tmp_path, p)
    k = out["business"]["venues"]["kalshi"]
    assert k["positions"][0]["scope"] == "bot"
    assert k["orders"][0]["status"] == "cancel_requested"
    assert k["orders"][0]["reserved"] == .99
    assert k["orders"][0]["filled"] == 1 and k["orders"][0]["remaining"] == 2
    assert out["business"]["venues"]["polymarket_us"]["positions"][0]["scope"] == "owner"
    assert out["business"]["today"] == pytest.approx(.33)


def test_cast_follows_kalshi_with_practice_behind_the_scenes_without_an_invented_pipeline(tmp_path: Path) -> None:
    p = connected()
    p["plain"]["team"].extend([{"id": "jet", "name": "Jet"}, {"id": "rook", "name": "Rook"}])
    p["money"]["connections"]["kalshi"]["events"] = [event("kalshi")]
    out = run(tmp_path, p)
    crew = {c["key"]: c for c in out["crew"]}
    assert "Polymarket" not in crew["voss"]["doing"] and "Kalshi" in crew["voss"]["doing"]
    assert crew["jet"]["job"] == "Kalshi orders"
    assert "The trading desk places its own orders" in crew["jet"]["jobDetail"]
    assert "Kalshi" in crew["mote"]["doing"]
    assert crew["pip"]["practice"] is True and crew["pip"]["background"] is True
    assert crew["pip"]["job"] == "Practice scouting"
    before = copy.deepcopy(p)
    run(tmp_path, p)
    assert p == before


def test_reported_safety_limits_do_not_turn_into_profit_or_spending_permission(tmp_path: Path) -> None:
    p = connected()
    p["team"]["members"].append({"id": "risk", "risk_wall": {"real_caps": {
        "open_max_usd": 30, "day_max_usd": 30, "total_max_usd": 40, "open_usd": 999,
    }}})
    p["money"]["speeddesk"]["kalshi_live"].update(
        caps={"window_usd": 2, "open_usd": 4, "day_stop_usd": 3, "total_stop_usd": 5}, total_halted=True,
        mode="paper", active=False, real_orders_available=False)
    out = run(tmp_path, p)
    assert out["limits"] == {"open": 30, "day": 30, "total": 40, "room": None}
    assert out["accounts"]["kalshi"]["limits"] == {"window": 2, "open": 4, "day": 3, "total": 5}
    assert out["accounts"]["kalshi"]["totalHalted"] is True
    assert out["accounts"]["kalshi"]["active"] is False
    assert out["business"]["today"] == pytest.approx(.33)


@pytest.mark.parametrize("problem", ["integrity", "reset", "total_stop", "both_incomplete"])
def test_rook_reports_current_accounting_problems_and_stops(tmp_path: Path, problem: str) -> None:
    p = connected()
    p["plain"]["team"].append({"id": "rook", "name": "Rook"})
    live = p["money"]["speeddesk"]["kalshi_live"]
    if problem == "integrity":
        live["integrity_error"] = "order_fill_count_mismatch"
    elif problem == "reset":
        live["integrity_reset"] = "orders_open"
    elif problem == "total_stop":
        live["total_halted"] = True
    else:
        p["money"]["polymarket"]["real"]["today_pacific"].update(status="incomplete", reason="day_book_mismatch", pnl_usd=None)
        for key in (["polymarket_us", "kalshi"] if problem == "both_incomplete" else ["polymarket_us"]):
            p["money"]["connections"][key]["status"] = "incomplete"
    out = run(tmp_path, p)
    rook = next(c for c in out["crew"] if c["key"] == "rook")
    assert rook["status"] == "stuck"
    assert any(words in rook["doing"] for words in ("need review", "checks are pending", "total-loss stop", "do not match"))
    if problem == "both_incomplete":
        assert all(v["reportFresh"] and not v["current"] for v in out["business"]["venues"].values())
        assert out["growth"]["qualified"] is False


def test_completed_unreconciled_holdings_preserve_their_limits_and_do_not_claim_current_positions(tmp_path: Path) -> None:
    p = connected()
    p["money"]["connections"]["kalshi"]["positions"] = [{
        "scope": "bot", "side": "yes", "title": "Ended BTC window", "quantity": 1,
        "status": "finalized_unreconciled", "status_note": "This window ended; account settlement is still unverified.",
        "end_at": NOW - 60, "final_outcome": "YES", "mixed_account_activity": True, "current_position_verified": False,
    }]
    row = run(tmp_path, p)["business"]["venues"]["kalshi"]["positions"][0]
    assert row["status"] == "finalized_unreconciled"
    assert "still unverified" in row["statusNote"]
    assert row["finalOutcome"] == "YES" and row["endAt"] == NOW - 60
    assert row["mixedAccountActivity"] is True and row["currentPositionVerified"] is False


def test_activity_does_not_repeat_its_venue_and_order_reserves_keep_pair_purpose(tmp_path: Path) -> None:
    p = connected()
    raw = p["money"]["connections"]["kalshi"]
    raw["events"] = [event("kalshi", text="Kalshi remaining order cancelled")]
    raw["orders"] = [{"side": "yes", "lock": True, "reserved_usd": .50}]
    out = run(tmp_path, p)
    assert out["activity"][0]["text"] == "Kalshi · remaining order cancelled"
    assert out["business"]["venues"]["kalshi"]["orders"][0]["lock"] is True


def test_polymarket_profit_and_outage_cannot_grow_or_pause_kalshi_town(tmp_path: Path) -> None:
    p = connected()
    expected = run(tmp_path, p)
    p["money"]["connections"]["polymarket_us"].update(
        status="incomplete", stale=True, as_of=NOW - 3600)
    p["money"]["connections"]["polymarket_us"]["today_pacific"]["pnl_usd"] = 99999
    p["money"]["polymarket"]["guard"] = {"paused": True}
    p["money"]["polymarket"]["real"]["today_pacific"].update(status="incomplete", pnl_usd=None)
    out = run(tmp_path, p)
    assert out["growth"] == expected["growth"]
    assert out["focus"] == expected["focus"]
    assert out["crew"] == expected["crew"]
    assert out["business"]["venues"]["polymarket_us"]["current"] is False


def test_focus_never_borrows_cash_risk_or_profit_from_other_sources(tmp_path: Path) -> None:
    p = connected()
    p["money"]["connections"].pop("kalshi")
    p["money"]["speeddesk"].pop("kalshi_live")
    out = run(tmp_path, p)
    assert out["cash"] == 14.22 and out["today"] == .23
    assert out["focus"]["venue"] == "kalshi" and out["focus"]["state"] == "unknown"
    assert all(out["focus"][key] is None for key in ("cash", "today", "exposure", "positions", "orders", "reserved"))
    assert out["growth"]["qualified"] is False
    assert all(c["status"] == "unknown" for c in out["crew"] if not c["background"])


def test_focus_cash_day_and_risk_have_independent_freshness(tmp_path: Path) -> None:
    p = connected()
    live = p["money"]["speeddesk"]["kalshi_live"]
    live["cash_at"] = NOW - 90
    out = run(tmp_path, p)
    assert out["focus"]["cash"] is None and out["focus"]["cashAge"] == 90
    assert out["focus"]["today"] == .10 and out["focus"]["exposure"] == 1.98
    assert out["growth"]["qualified"] is True
    live["as_of"] = NOW - 90
    out = run(tmp_path, p)
    assert out["focus"]["state"] == "stale" and out["focus"]["exposure"] is None
    assert out["focus"]["orders"] is None and out["accounts"]["kalshi"]["orders"] == 2
    p["money"]["connections"]["kalshi"]["as_of"] = NOW - 61
    out = run(tmp_path, p)
    assert out["focus"]["today"] is None and out["growth"]["qualified"] is False


def test_only_kalshi_receipts_can_mark_foreground_crew_working(tmp_path: Path) -> None:
    p = connected()
    p["plain"]["team"].append({"id": "jet", "name": "Jet"})
    p["money"]["connections"]["polymarket_us"]["events"] = [event("polymarket_us", ts=NOW - 1)]
    out = run(tmp_path, p)
    assert all(c["status"] == "waiting" for c in out["crew"] if not c["background"])
    assert out["event"] is None
    p["money"]["connections"]["kalshi"]["events"] = [event("kalshi", ts=NOW - 2)]
    out = run(tmp_path, p)
    crew = {c["key"]: c for c in out["crew"]}
    assert crew["voss"]["status"] == "waiting"
    assert crew["jet"]["status"] == "working"
    assert crew["jet"]["lastReceipt"]["kind"] == "fill"
    assert crew["voss"]["lastReceipt"] is None
    assert out["event"]["venue"] == "kalshi"


def test_busy_secondary_desk_cannot_crowd_kalshi_out_of_main_activity(tmp_path: Path) -> None:
    p = connected()
    for key, age in (("polymarket_us", 1), ("kalshi", 2)):
        p["money"]["connections"][key]["events"] = [event(key, id=f"{key}-{i}", ts=NOW - age) for i in range(50)]
    out = run(tmp_path, p)
    assert len(out["business"]["activity"]) == 60
    assert len(out["activity"]) == 50
    assert all(e["venue"] == "kalshi" for e in out["activity"])


@pytest.mark.parametrize(("kind", "busy"), [
    ("order", {"jet"}), ("fill", {"jet", "mote"}),
    ("settlement", {"mote"}), ("reject", {"rook", "jet"}),
])
def test_receipts_only_mark_the_roles_that_handle_them(tmp_path: Path, kind: str, busy: set[str]) -> None:
    p = connected()
    for key in ("rook", "jet"):
        p["plain"]["team"].append({"id": key, "name": key.title()})
    p["money"]["connections"]["kalshi"]["events"] = [event("kalshi", kind)]
    crew = run(tmp_path, p)["crew"]
    assert {c["key"] for c in crew if not c["background"] and c["status"] == "working"} == busy
    p["money"]["connections"]["kalshi"]["stale"] = True
    crew = run(tmp_path, p)["crew"]
    assert all(c["status"] == "unknown" and c["lastReceipt"] is None for c in crew if not c["background"])
