"""The owner's own bets in the shared Polymarket US account (2026-10-11: his parlays tripped the desk's total-loss
stop): shown and settled, never counted in the desk's caps or stops; the rows adopted before they were told apart
are re-read once; and the owner's switch (POLYDESK_RESUME_TOKEN) turns real money back on after a total-loss halt,
once per value, with every cap and stop unchanged."""

from __future__ import annotations

import json
from datetime import UTC, datetime
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


def test_the_desk_logs_each_account_activity_once(gw: Gateway, tmp_path: Path,  # noqa: F811
                                                  caplog: pytest.LogCaptureFixture) -> None:
    class Ex(FakeExchange):
        def activities(self, limit: int = 50) -> list[dict[str, Any]]:
            return [{"kind": "trade", "id": "t9", "slug": "aec-nfl-nyg-was-2026-10-11", "time": "2026-10-11T20:20:00Z",
                     "price": 0.55, "qty": 10.0, "realized": -0.8, "cost_basis": 6.3, "amount": 0.0, "side": ""}]

    desk = P.PolyDesk(_live_settings(tmp_path), ledger=FakeLedger(), client_factory=Ex())
    with caplog.at_level("INFO", logger="nightcrawler.polydesk"):
        desk.poll(NOW)
        desk.poll(NOW + 90)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("polydesk_activity ")]
    assert lines == ["polydesk_activity kind=trade slug=aec-nfl-nyg-was-2026-10-11 qty=10 price=0.5500 "
                     "realized=-0.8000 cost_basis=6.3000 amount=0.0000 side= time=2026-10-11T20:20:00Z"]


SALE_T = "2026-10-09T16:00:00Z"  # after the position's buy (NOW is 2026-10-09 15:33 UTC), before its settlement


class SaleEx(FakeExchange):
    """The account's activity feed, scripted: the owner's cash-outs in the app."""

    def __init__(self, sales: list[dict[str, Any]], **kw: Any) -> None:
        super().__init__(**kw)
        self.sales = sales

    def activities(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(reversed(self.sales))  # newest first, as the venue sends them


def _sale(slug: str, qty: float, price: float, realized: float, sid: str = "t1", when: str = SALE_T) -> dict[str, Any]:
    return {"kind": "trade", "id": sid, "slug": slug, "time": when, "price": price, "qty": qty, "realized": realized,
            "cost_basis": 6.46, "amount": 0.0, "side": ""}


def _held(desk: P.PolyDesk, slug: str = "aec-nfl-nyg-was", shares: float = 10.0, **kw: Any) -> dict[str, Any]:
    pos = {"slug": slug, "question": "Marco's love: Commanders moneyline", "category": "crypto", "side": "short",
           "p_in": 0.63, "shares": shares, "fee_usd": 0.16, "cost_usd": 6.30, "t_in": NOW, "end_ts": NOW + 86_400,
           "live": True, "rule": P.RULE_MARCO, **kw}
    desk.state["positions"][slug] = pos
    return pos


def test_a_cash_out_in_the_app_closes_the_desks_bet_at_the_venues_figure(gw: Gateway, tmp_path: Path) -> None:  # noqa: F811
    ledger = FakeLedger()
    ex = SaleEx([_sale("aec-nfl-nyg-was", 10, 0.0975, -5.54)])
    desk = P.PolyDesk(_live_settings(tmp_path), ledger=ledger, client_factory=ex)
    _held(desk)
    desk.poll(NOW + 3600)
    assert "aec-nfl-nyg-was" not in desk.state["positions"]
    row = desk.state["closed"][0]
    assert row["sold_in_app"] and row["pnl_usd"] == pytest.approx(-5.54) and row["won"] is False
    assert desk.state["live_pnl_total_usd"] == pytest.approx(-5.54)
    assert ("polydesk_sold_in_app", {"slug": "aec-nfl-nyg-was", "contracts": 10.0, "price": 0.0975,
                                     "pnl_usd": -5.54, "trade_id": "t1"}) in ledger.receipts
    desk.poll(NOW + 3700)  # the same trade is never booked twice
    assert desk.state["live_pnl_total_usd"] == pytest.approx(-5.54)


def test_a_booking_from_the_settlement_is_corrected_to_the_sale(gw: Gateway, tmp_path: Path) -> None:  # noqa: F811
    ex = SaleEx([_sale("aec-nfl-nyg-was", 10, 0.0975, -5.54)])
    desk = P.PolyDesk(_live_settings(tmp_path), ledger=FakeLedger(), client_factory=ex)
    settled_at = NOW + 2 * 3600  # booked at the 0.50 settlement after the owner had sold
    day = datetime.fromtimestamp(settled_at, UTC).strftime("%Y-%m-%d")
    desk.state["closed"].insert(0, {"slug": "aec-nfl-nyg-was", "question": "Commanders", "live": True,
                                    "rule": P.RULE_MARCO, "t_in": NOW, "settled_at": settled_at, "value": 0.5,
                                    "pnl_usd": -1.46, "won": False, "shares": 10.0})
    desk.state["live_pnl_total_usd"] = -1.46
    desk.state["live_days"] = {day: {"pnl_usd": -1.46, "settled": 1, "won": 0}}
    desk.poll(NOW + 3 * 3600)
    row = desk.state["closed"][0]
    assert row["sold_in_app"] and row["pnl_usd"] == pytest.approx(-5.54)
    assert desk.state["live_pnl_total_usd"] == pytest.approx(-5.54)
    assert desk.state["live_days"][day]["pnl_usd"] == pytest.approx(-5.54)


def test_a_partial_cash_out_keeps_the_rest_open(gw: Gateway, tmp_path: Path) -> None:  # noqa: F811
    ex = SaleEx([_sale("aec-nfl-nyg-was", 4, 0.30, -1.30)])
    desk = P.PolyDesk(_live_settings(tmp_path), ledger=FakeLedger(), client_factory=ex)
    _held(desk)
    desk.poll(NOW + 3600)
    rest = desk.state["positions"]["aec-nfl-nyg-was"]
    assert rest["shares"] == pytest.approx(6.0) and rest["cost_usd"] == pytest.approx(6.30 * 0.6)
    assert desk.state["closed"][0]["shares"] == pytest.approx(4.0)
    assert desk.state["live_pnl_total_usd"] == pytest.approx(-1.30)


def test_the_owners_own_bets_and_older_trades_are_not_the_desks(gw: Gateway, tmp_path: Path) -> None:  # noqa: F811
    early = datetime.fromtimestamp(NOW - 3600, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    ex = SaleEx([_sale("parlay", 300, 0.03, 21.55, sid="p1"), _sale("aec-nfl-nyg-was", 10, 0.1, -5.0, sid="t0",
                                                                    when=early)])
    desk = P.PolyDesk(_live_settings(tmp_path), ledger=FakeLedger(), client_factory=ex)
    _held(desk, "parlay", 300.0, owner=True, rule=P.RULE_OWNER)
    _held(desk)
    desk.poll(NOW + 3600)
    assert "parlay" in desk.state["positions"] and "aec-nfl-nyg-was" in desk.state["positions"]
    assert float(desk.state.get("live_pnl_total_usd") or 0.0) == 0.0
