"""The owner's own bets in the shared Polymarket US account (2026-10-11: his parlays tripped the desk's total-loss
stop): shown and settled, never counted in the desk's caps or stops; the rows adopted before they were told apart
are re-read once; and the owner's switch (POLYDESK_RESUME_TOKEN) turns real money back on after a total-loss halt,
once per value, with every cap and stop unchanged."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_polydesk import NOW, Gateway, _market, gw  # noqa: F401 - shared fixture
from test_polydesk_live import FakeExchange, FakeLedger, _live_settings

from nightcrawler import polydesk as P

DAY = "2026-10-11"
T = P.OWNER_MIGRATION_FROM + 6 * 3600  # 2026-10-11 06:00 UTC


def test_the_owners_losing_bet_never_moves_the_desks_stops(gw: Gateway, tmp_path: Path) -> None:  # noqa: F811
    settings = _live_settings(tmp_path, POLYDESK_LIVE_TOTAL_LOSS_USD="3")
    ex = FakeExchange(cash=25.0)
    ex.hold("parlay", 300.0, 0.08, title="Six-leg parlay", outcome="Yes")
    ledger = FakeLedger()
    desk = P.PolyDesk(settings, ledger=ledger, client_factory=ex)
    desk.poll(NOW)
    pos = desk.state["positions"]["parlay"]
    assert pos["owner"] and pos["rule"] == P.RULE_OWNER and pos["live"]
    assert P.real_room(desk.state, settings, NOW)["held_usd"] == 0.0  # not the desk's money
    gw.settlements = {"parlay": 0.0}
    desk.poll(NOW + P.ADOPTED_END_GUESS_S + 1)  # it loses $24: far past the $3 total stop, were it the desk's
    assert desk.state["mode"] == "live" and not desk.state["live_halted"]
    assert float(desk.state.get("live_pnl_total_usd") or 0.0) == 0.0 and not desk.state.get("live_days")
    assert -26.0 < desk.state["owner_pnl_usd"] < -24.0  # its $24 cost and the modelled fee
    kinds = [k for k, _ in ledger.receipts]
    assert "polydesk_owner_bet_seen" in kinds and "polydesk_owner_bet_settled" in kinds
    assert "polydesk_settled" not in kinds and "polydesk_live_halted" not in kinds


def _saved(tmp_path: Path, **over: Any) -> Path:
    st = P.empty_state()
    st.pop("owner_migrated", None)
    owner = {"slug": "parlay", "live": True, "rule": P.RULE_VENUE, "adopted": True, "shares": 323.68, "t_in": T,
             "settled_at": T + 3600, "pnl_usd": -25.0, "won": False, "question": "parlay"}
    desk_row = {"slug": "marco", "live": True, "rule": P.RULE_VENUE, "adopted": True, "shares": 10.0, "t_in": T,
                "settled_at": T + 3600, "pnl_usd": -6.3, "won": False, "question": "marco"}
    old = {"slug": "old", "live": True, "rule": P.RULE_VENUE, "adopted": True, "shares": 40.0,
           "t_in": P.OWNER_MIGRATION_FROM - 3600, "settled_at": P.OWNER_MIGRATION_FROM, "pnl_usd": -1.0, "won": False}
    st.update({"closed": [owner, desk_row, old], "live_pnl_total_usd": -47.07,
               "live_days": {DAY: {"pnl_usd": -40.0, "settled": 5, "won": 1}},
               "positions": {"open-parlay": {**owner, "slug": "open-parlay", "shares": 1200.0}}, **over})
    path = P.state_path(_live_settings(tmp_path))
    P.save_state(path, st)
    return path


def test_the_owners_rows_adopted_before_are_taken_out_once(tmp_path: Path) -> None:
    path = _saved(tmp_path)
    st = P.load_state(path)
    assert st["live_pnl_total_usd"] == pytest.approx(-22.07)  # the $25 parlay is his, not the desk's
    assert st["live_days"][DAY] == {"pnl_usd": pytest.approx(-15.0), "settled": 4, "won": 1}
    assert st["owner_pnl_usd"] == pytest.approx(-25.0)
    by_slug = {r["slug"]: r for r in st["closed"]}
    assert by_slug["parlay"]["owner"] and by_slug["parlay"]["rule"] == P.RULE_OWNER
    assert by_slug["marco"]["rule"] == P.RULE_VENUE and not by_slug["marco"].get("owner")  # a desk-sized order
    assert by_slug["old"]["rule"] == P.RULE_VENUE  # before the desk ordered 10: never re-read
    assert st["positions"]["open-parlay"]["owner"]
    P.save_state(path, st)
    again = P.load_state(path)
    assert again["live_pnl_total_usd"] == pytest.approx(-22.07)  # once only


def test_the_owners_switch_turns_real_money_back_on_once(tmp_path: Path) -> None:
    _saved(tmp_path, live_halted=True, halt_reason="total_loss", mode="paper")
    ledger = FakeLedger()
    off = P.PolyDesk(_live_settings(tmp_path, POLYDESK_LIVE_TOTAL_LOSS_USD="40"), ledger=FakeLedger(),
                     client_factory=FakeExchange())
    assert off.state["mode"] == "paper" and off.state["live_status"] == P.TOTAL_HALT_STATUS  # no switch: stays off
    desk = P.PolyDesk(_live_settings(tmp_path, POLYDESK_LIVE_TOTAL_LOSS_USD="40", POLYDESK_RESUME_TOKEN="2026-10-11"),
                      ledger=ledger, client_factory=FakeExchange())
    assert desk.state["mode"] == "live" and not desk.state["live_halted"] and desk.client is not None
    assert desk.state["resume_token_used"] == "2026-10-11"
    assert ("polydesk_live_resumed", {"token": "2026-10-11", "live_pnl_total_usd": pytest.approx(-22.07)}) in [
        (k, v) for k, v in ledger.receipts]
    room = P.real_room(desk.state, desk.settings, T)
    assert room["total_room"] == pytest.approx(40.0 - 22.07)  # the stops as before, on the desk's own result
    # halted again later: the same value does not switch it on twice
    desk.state.update({"live_halted": True, "halt_reason": "total_loss", "mode": "paper"})
    desk._save()
    same = P.PolyDesk(_live_settings(tmp_path, POLYDESK_RESUME_TOKEN="2026-10-11"), ledger=FakeLedger(),
                      client_factory=FakeExchange())
    assert same.state["mode"] == "paper" and same.state["live_halted"]


def test_the_switch_never_clears_an_unreadable_record_halt(tmp_path: Path) -> None:
    _saved(tmp_path, live_halted=True, halt_reason="unreadable_state", mode="paper")
    desk = P.PolyDesk(_live_settings(tmp_path, POLYDESK_RESUME_TOKEN="x1"), ledger=FakeLedger(),
                      client_factory=FakeExchange())
    assert desk.state["mode"] == "paper" and desk.state["live_halted"]
    assert json.loads(P.state_path(desk.settings).read_text()).get("resume_token_used") is None
