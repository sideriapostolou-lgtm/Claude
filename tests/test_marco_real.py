"""Real money on Million Dollar Marco's loves (MARCO_REAL, the owner's explicit exception to "no real money on
sports"): one real IOC order per loved moneyline, on the side he loves (NO for a home team, priced the venue's way:
the YES price), through every cap; off by default; a NO holding settles to shares x (1 - the YES side's value)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nightcrawler import marcodesk as M
from nightcrawler import polydesk as P
from nightcrawler.config import Settings
from nightcrawler.polymarket_us import PolymarketUSClient
from tests.test_polydesk import NOW
from tests.test_polydesk_live import FakeExchange, FakeLedger, _live_settings

SLUG = "aec-nfl-chi-gb-2026-10-11"  # Bears (away, YES) at Packers (home, NO)


class Exchange(FakeExchange):
    def buy_short_ioc(self, slug: str, no_price: float, quantity: float, max_block_s: int = 5) -> dict[str, Any]:
        self.orders.append({"slug": slug, "price": no_price, "quantity": quantity, "side": "short"})
        self.book[slug] = {"slug": slug, "qty": quantity, "side": "short", "avg_price": 0.0, "cost": 0.0,
                           "value": 0.0, "realized": 0.0, "expired": False, "title": slug, "outcome": "",
                           "event_slug": "", "updated": "t"}
        return {"id": "s1", "filled": quantity, "avg_price": no_price, "cost": no_price * quantity}


def _episode() -> list[dict[str, Any]]:
    pick = {"id": "wk5|1|moneyline|green bay packers", "rank": 1, "love": True, "league": "nfl",
            "team": "Green Bay Packers", "opponent": "Chicago Bears", "kind": "moneyline", "line": "ML",
            "quote": "my favorite game of the week", "game_date": "2026-10-11"}
    return [{"id": "wk5", "title": "Week 5", "published": NOW - 86400, "source_url": "", "picks": [pick]}]


def _marco_state(settings: Settings, long: bool = False, kickoff: float = NOW + 3600) -> None:
    st = M.empty_state()
    st["picks"]["wk5|1|moneyline|green bay packers"] = {
        "status": "waiting", "game": {"slug": SLUG, "kickoff": kickoff, "event": "Bears at Packers"},
        "market": {"slug": SLUG, "long": long, "side": "Green Bay Packers", "fee_coef": 0.0695}}
    P.save_state(M.state_path(settings), st)


@pytest.fixture
def venue(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    quote: dict[str, Any] = {"best_bid": 0.5225, "best_ask": 0.525, "state": P.OPEN_STATE, "last": 0.52}
    monkeypatch.setattr(P, "open_markets", lambda now: [])
    monkeypatch.setattr(P, "live_sports_markets", lambda now: [])
    monkeypatch.setattr(P, "bbo", lambda slug: dict(quote))
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    monkeypatch.setattr(M, "load_episodes", lambda path=None: _episode())
    return quote


def _desk(settings: Settings, ex: FakeExchange) -> P.PolyDesk:
    return P.PolyDesk(settings, ledger=FakeLedger(), client_factory=ex)


def test_a_home_team_love_buys_the_no_side_at_one_minus_the_yes_bid(venue: dict[str, Any], tmp_path: Path) -> None:
    settings = _live_settings(tmp_path, MARCO_REAL="1", POLYDESK_LIVE_CONTRACTS="10", POLYDESK_LIVE_MAX_OPEN_USD="30",
                              POLYDESK_LIVE_DAILY_LOSS_USD="30", POLYDESK_LIVE_TOTAL_LOSS_USD="40")
    _marco_state(settings)
    ex = Exchange(cash=42.0)
    desk = _desk(settings, ex)
    desk.poll(NOW)
    assert ex.orders == [{"slug": SLUG, "price": pytest.approx(0.4775), "quantity": 10.0, "side": "short"}]
    pos = desk.state["positions"][SLUG]
    assert (pos["side"], pos["rule"], pos["live"], pos["shares"]) == ("short", P.RULE_MARCO, True, 10.0)
    assert pos["cost_usd"] == pytest.approx(4.775)
    desk.poll(NOW + 120)  # tried once: no second order
    assert len(ex.orders) == 1


def test_an_away_team_love_buys_yes(venue: dict[str, Any], tmp_path: Path) -> None:
    settings = _live_settings(tmp_path, MARCO_REAL="1", POLYDESK_LIVE_CONTRACTS="10", POLYDESK_LIVE_MAX_OPEN_USD="30",
                              POLYDESK_LIVE_DAILY_LOSS_USD="30", POLYDESK_LIVE_TOTAL_LOSS_USD="40")
    _marco_state(settings, long=True)
    ex = Exchange(cash=42.0)
    _desk(settings, ex).poll(NOW)
    assert [(o["slug"], o["price"], o.get("side", "long")) for o in ex.orders] == [(SLUG, 0.525, "long")]


@pytest.mark.parametrize("env", [{}, {"MARCO_REAL": "1", "POLYDESK_LIVE_MAX_OPEN_USD": "3"}])
def test_no_real_order_when_the_switch_is_off_or_the_caps_refuse(venue: dict[str, Any], tmp_path: Path,
                                                                  env: dict[str, str]) -> None:
    settings = _live_settings(tmp_path, POLYDESK_LIVE_CONTRACTS="10", **env)
    _marco_state(settings)
    ex = Exchange(cash=42.0)
    desk = _desk(settings, ex)
    desk.poll(NOW)
    assert ex.orders == [] and SLUG not in desk.state["positions"]


def test_no_order_after_his_buy_window_or_on_a_wide_book(venue: dict[str, Any], tmp_path: Path) -> None:
    settings = _live_settings(tmp_path, MARCO_REAL="1", POLYDESK_LIVE_CONTRACTS="10", POLYDESK_LIVE_MAX_OPEN_USD="30",
                              POLYDESK_LIVE_DAILY_LOSS_USD="30", POLYDESK_LIVE_TOTAL_LOSS_USD="40")
    _marco_state(settings, kickoff=NOW - M.LATE_BUY_S - 60)
    ex = Exchange(cash=42.0)
    _desk(settings, ex).poll(NOW)
    assert ex.orders == []
    _marco_state(settings)
    venue.update(best_bid=0.40, best_ask=0.60)
    _desk(settings, ex).poll(NOW)
    assert ex.orders == []


def test_a_no_holding_settles_to_one_minus_the_yes_value(venue: dict[str, Any], tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _live_settings(tmp_path, MARCO_REAL="1", POLYDESK_LIVE_CONTRACTS="10", POLYDESK_LIVE_MAX_OPEN_USD="30",
                              POLYDESK_LIVE_DAILY_LOSS_USD="30", POLYDESK_LIVE_TOTAL_LOSS_USD="40")
    _marco_state(settings)
    ex = Exchange(cash=42.0)
    desk = _desk(settings, ex)
    desk.poll(NOW)
    monkeypatch.setattr(P, "settlement", lambda slug: 0.0)  # the Bears (YES) lost: the Packers (NO) won
    venue.update(state="MARKET_STATE_CLOSED")
    desk.poll(NOW + 6 * 3600)
    row = next(r for r in desk.state["closed"] if r["slug"] == SLUG)
    assert row["won"] is True and row["pnl_usd"] == pytest.approx(10 - 4.775 - row["fee_usd"])


def test_the_client_prices_a_no_buy_on_the_yes_side_and_reads_documented_fills() -> None:
    sent: list[dict[str, Any]] = []

    class Reply:
        status_code = 200

        def __init__(self, doc: dict[str, Any]) -> None:
            self.doc = doc

        def json(self) -> dict[str, Any]:
            return self.doc

    def transport(method: str, url: str, headers: dict[str, str], data: str | None, timeout: float) -> Reply:
        import json
        body = json.loads(data or "{}")
        sent.append(body)
        yes = float(body["price"]["value"])
        return Reply({"id": "o1", "executions": [{"type": "EXECUTION_TYPE_FILL", "lastShares": str(body["quantity"]),
                                                  "lastPx": str(yes)}]})

    import base64
    client = PolymarketUSClient("kid", base64.b64encode(b"\x01" * 32).decode(), transport=transport)
    fill = client.buy_short_ioc(SLUG, 0.4775, 10)
    assert sent[0]["intent"] == "ORDER_INTENT_BUY_SHORT" and sent[0]["price"]["value"] == "0.5225"
    assert fill["filled"] == 10 and fill["avg_price"] == pytest.approx(0.4775) and fill["cost"] == pytest.approx(4.775)
    long_fill = client.buy_long_ioc("k1", 0.98, 1)
    assert long_fill["filled"] == 1 and long_fill["avg_price"] == pytest.approx(0.98)


def test_the_page_cash_is_the_buying_power_while_no_collateral_is_posted() -> None:
    bal = P._spendable({"cash": 81.8779, "buying_power": 51.8779, "at": 1.0})
    assert bal["cash"] == 51.8779 and bal["cash_reported"] == 81.8779
    assert P._spendable({"cash": 42.0, "buying_power": 42.0}) == {"cash": 42.0, "buying_power": 42.0}
