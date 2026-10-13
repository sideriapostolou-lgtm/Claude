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


def test_both_cash_accounts_stay_separate_and_growth_uses_only_same_pacific_day(tmp_path: Path) -> None:
    p = connected()
    p["money"]["today"] = {"usd": 100000}
    p["money"]["connections"]["kalshi"]["orders"] = [{"reserved_usd": 500}]
    out = run(tmp_path, p)
    assert (out["cash"], out["accounts"]["kalshi"]["cash"]) == (14.22, 25)
    assert out["today"] == .23  # compatibility: always the PM Pacific book
    assert out["accounts"]["kalshi"]["today"] == -.34  # existing UTC stop day
    assert out["accounts"]["kalshi"]["todayPacific"]["value"] == .10
    assert out["business"]["today"] == pytest.approx(.33)
    assert out["growth"]["level"] == 2
    p["money"]["connections"]["kalshi"]["today_pacific"]["pnl_usd"] = -1
    assert run(tmp_path, p)["growth"]["level"] == 0


@pytest.mark.parametrize("change", [
    {"stale": True}, {"as_of": NOW - 61}, {"as_of": None}, {"status": "incomplete"},
    {"today_pacific": {"status": "incomplete", "pnl_usd": 100}},
])
def test_missing_or_stale_second_book_cannot_unlock_combined_gardens(tmp_path: Path, change: dict[str, Any]) -> None:
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


def test_real_order_fill_and_settlement_remain_different_and_each_venue_is_visible(tmp_path: Path) -> None:
    p = connected()
    p["money"]["connections"]["polymarket_us"]["events"] = [event("polymarket_us", "settlement", pnl_usd=.23)]
    p["money"]["connections"]["kalshi"]["events"] = [
        event("kalshi", id="fill", ts=NOW - 2),
        event("kalshi", "order", id="order", ts=NOW - 4, text="Order submitted; not filled"),
        event("kalshi", "settlement", id="practice", real=False),
    ]
    out = run(tmp_path, p)
    assert [e["kind"] for e in out["activity"]] == ["fill", "order", "settlement"]
    assert [e["usd"] for e in out["activity"]] == [None, None, .23]
    assert out["event"]["text"] == "Kalshi · Filled 1 YES contract"
    assert out["event"]["fee"] == .0034  # fee never rounded to a false zero in the read model
    assert all(e["current"] for e in out["activity"])
    assert out["activitySources"] == {"polymarket_us": True, "kalshi": True}


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


def test_cast_reports_both_desks_but_does_not_invent_an_execution_pipeline(tmp_path: Path) -> None:
    p = connected()
    p["plain"]["team"].extend([{"id": "jet", "name": "Jet"}, {"id": "rook", "name": "Rook"}])
    p["money"]["connections"]["kalshi"]["events"] = [event("kalshi")]
    out = run(tmp_path, p)
    crew = {c["key"]: c for c in out["crew"]}
    assert "Polymarket" in crew["voss"]["doing"] and "Kalshi" in crew["voss"]["doing"]
    assert crew["jet"]["job"] == "Order status"
    assert "Each trading desk places its own orders" in crew["jet"]["jobDetail"]
    assert "Kalshi" in crew["mote"]["doing"]
    assert crew["pip"]["practice"] is True
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
