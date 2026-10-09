"""The Polymarket desk in LIVE mode, against a fake exchange client: the gate (confirm phrase, key, a balance read),
real buys on the long side only with caps, rejected and unfilled orders, settlement with the real cost, the daily
and total loss stops (the total stop switches back to paper for good), receipts, and the panel's labels."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from nightcrawler import polydesk as P
from nightcrawler.config import LIVE_CONFIRM_PHRASE, ConfigError, Settings
from nightcrawler.polymarket_us import PolymarketUSError
from tests.test_polydesk import NOW, Gateway, _market

KEY = {"POLYMARKET_US_KEY_ID": "0000-key", "POLYMARKET_US_SECRET_KEY": "c2VjcmV0"}


class FakeExchange:
    """Balances, orders and their outcomes, scripted by the test."""

    def __init__(self, cash: float = 25.0, reject_key: bool = False) -> None:
        self.cash = cash
        self.reject_key = reject_key
        self.orders: list[dict[str, Any]] = []
        self.fill_price: float | None = None  # None = fill at the limit price; 0 = no fill
        self.reject_orders = False
        self.silent_fills = False  # the real venue: the order reply shows no execution, the book shows the fill
        self.book: dict[str, dict[str, Any]] = {}  # slug -> position row as positions() returns it

    def __call__(self, key_id: str, secret_key: str) -> FakeExchange:
        self.key_id, self.secret = key_id, secret_key
        return self

    def balances(self) -> dict[str, Any]:
        if self.reject_key:
            raise PolymarketUSError("GET /v1/account/balances: HTTP 401", status=401)
        return {"cash": self.cash, "buying_power": self.cash, "asset_notional": 0.0, "open_orders": 0.0, "currency": "USD"}

    def positions(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.book.values()]

    def hold(self, slug: str, qty: float, price: float, title: str = "", outcome: str = "", event_slug: str = "") -> None:
        self.book[slug] = {"slug": slug, "qty": qty, "avg_price": price, "cost": qty * price, "value": qty * price,
                           "realized": 0.0, "expired": False, "title": title, "outcome": outcome,
                           "event_slug": event_slug, "updated": "t"}

    def buy_long_ioc(self, slug: str, price: float, quantity: float, max_block_s: int = 5) -> dict[str, Any]:
        self.orders.append({"slug": slug, "price": price, "quantity": quantity})
        if self.reject_orders:
            raise PolymarketUSError("POST /v1/orders: HTTP 400", status=400)
        if self.fill_price == 0:
            return {"id": "o", "filled": 0.0, "avg_price": None, "cost": 0.0, "raw_executions": 0}
        p = self.fill_price if self.fill_price is not None else price
        if self.silent_fills:
            self.hold(slug, quantity, p)
            self.cash -= p * quantity
            return {"id": f"o{len(self.orders)}", "filled": 0.0, "avg_price": None, "cost": 0.0, "raw_executions": 0}
        self.hold(slug, quantity, p)
        return {"id": f"o{len(self.orders)}", "filled": quantity, "avg_price": p, "cost": p * quantity, "raw_executions": 1}


class FakeLedger:
    def __init__(self) -> None:
        self.receipts: list[tuple[str, dict[str, Any]]] = []

    def append_receipt(self, kind: str, payload: dict[str, Any], ts: float | None = None) -> None:
        self.receipts.append((kind, payload))


@pytest.fixture
def gw(monkeypatch: pytest.MonkeyPatch) -> Gateway:
    g = Gateway()
    monkeypatch.setattr(P, "_get", g.get)
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    return g


def _live_settings(tmp_path, **extra: str) -> Settings:
    return Settings.from_env({"DATA_DIR": str(tmp_path), "POLYDESK_MODE": "live",
                              "POLYDESK_LIVE_CONFIRM": LIVE_CONFIRM_PHRASE, **KEY, **extra})


def test_live_settings_need_the_phrase_and_the_key(tmp_path) -> None:
    with pytest.raises(ConfigError):
        Settings.from_env({"DATA_DIR": str(tmp_path), "POLYDESK_MODE": "live", **KEY})
    with pytest.raises(ConfigError):
        Settings.from_env({"DATA_DIR": str(tmp_path), "POLYDESK_MODE": "live", "POLYDESK_LIVE_CONFIRM": LIVE_CONFIRM_PHRASE})
    s = _live_settings(tmp_path)
    assert s.polydesk_mode == "live" and s.polydesk_live_max_open_usd == 10.0 and s.polydesk_live_total_loss_usd == 10.0
    public = s.public_dict()
    assert "c2VjcmV0" not in str(public) and "0000-key" not in str(public)  # secrets never leave the process


def test_live_connects_only_after_a_balance_read(gw: Gateway, tmp_path) -> None:
    ledger = FakeLedger()
    ex = FakeExchange(cash=25.0)
    desk = P.PolyDesk(_live_settings(tmp_path), ledger=ledger, client_factory=ex)
    assert desk.state["mode"] == "live" and desk.state["balance"]["cash"] == 25.0 and ex.key_id == "0000-key"
    assert ledger.receipts[0][0] == "polydesk_live_connected"
    d = P.panel_state(desk.settings, NOW)
    assert d["mode"] == "live" and d["label"] == "Real money" and d["balance"]["cash"] == 25.0
    # a rejected key: paper, with the reason
    bad = P.PolyDesk(_live_settings(tmp_path / "b"), ledger=FakeLedger(), client_factory=FakeExchange(reject_key=True))
    assert bad.state["mode"] == "paper" and "rejected the API key (401)" in bad.state["live_status"]
    assert P.panel_state(bad.settings, NOW)["label"] == "Paper money (pretend)"
    # paper settings never touch the client
    paper = P.PolyDesk(Settings.from_env({"DATA_DIR": str(tmp_path / "p")}), client_factory=FakeExchange(reject_key=True))
    assert paper.state["mode"] == "paper" and paper.client is None and paper.state["live_status"] is None


def test_live_buys_long_only_with_caps_and_settles_at_real_cost(gw: Gateway, tmp_path) -> None:
    gw.markets = [_market("w1", "climate", 1800), _market("c1", "crypto", 1800), _market("n1", "crypto", 1800)]
    gw.events = []
    gw.quotes = {"w1": (0.96, 0.975), "c1": (0.02, 0.05), "n1": (0.50, 0.52)}  # c1 is a SHORT setup: paper only
    ledger = FakeLedger()
    ex = FakeExchange(cash=25.0)
    desk = P.PolyDesk(_live_settings(tmp_path), ledger=ledger, client_factory=ex)
    r = desk.poll(NOW)
    assert r["bought"] == 1 and [o["slug"] for o in ex.orders] == ["w1"] and ex.orders[0]["quantity"] == 1.0
    pos = desk.state["positions"]
    assert set(pos) == {"w1"} and pos["w1"]["live"] and pos["w1"]["cost_usd"] == pytest.approx(0.975)
    assert "c1" not in pos and "c1" not in desk.state["tried"]  # shorts are not tried live (they stay available to paper)
    assert desk.state["events"][0]["text"].startswith("REAL buy:")
    assert [k for k, _ in ledger.receipts] == ["polydesk_live_connected", "polydesk_order_filled"]
    # settlement: the real cost, a receipt, the live day book
    gw.markets = []
    gw.settlements = {"w1": 1.0}
    desk.poll(NOW + 2000)
    closed = desk.state["closed"][0]
    fee = (1 / 0.975) * 0 + closed["fee_usd"]
    assert closed["won"] and closed["pnl_usd"] == pytest.approx(1.0 - fee - 0.975)
    day = datetime.fromtimestamp(NOW + 2000, UTC).strftime("%Y-%m-%d")
    assert desk.state["live_days"][day]["pnl_usd"] == pytest.approx(closed["pnl_usd"])
    assert ledger.receipts[-1][0] == "polydesk_settled" and desk.state["mode"] == "live"


def test_live_caps_open_money_rejections_and_no_fills(gw: Gateway, tmp_path) -> None:
    gw.markets = [_market(f"m{i}", "crypto", 1800) for i in range(15)]
    gw.quotes = {f"m{i}": (0.97, 0.98) for i in range(15)}
    ex = FakeExchange(cash=25.0)
    desk = P.PolyDesk(_live_settings(tmp_path, POLYDESK_LIVE_MAX_OPEN_USD="5"), ledger=FakeLedger(), client_factory=ex)
    desk.poll(NOW)
    assert len(ex.orders) == 5 and len(desk.state["positions"]) == 5  # 5 x $0.98 fits under $5; the 6th does not
    # rejected orders and no-fills leave no position and are not retried
    gw.markets = [_market("r1", "crypto", 1800), _market("z1", "crypto", 1800)]
    gw.quotes = {"r1": (0.97, 0.98), "z1": (0.97, 0.98)}
    desk2 = P.PolyDesk(_live_settings(tmp_path / "2"), ledger=FakeLedger(), client_factory=FakeExchange())
    desk2.client.reject_orders = True  # type: ignore[union-attr]
    desk2.poll(NOW)
    assert not desk2.state["positions"] and "r1" in desk2.state["tried"] and desk2.state["counters"]["errors"] == 2
    desk3 = P.PolyDesk(_live_settings(tmp_path / "3"), ledger=FakeLedger(), client_factory=FakeExchange())
    desk3.client.fill_price = 0  # type: ignore[union-attr]
    desk3.poll(NOW)
    assert not desk3.state["positions"] and desk3.state["events"][0]["text"].startswith("No fill")


def test_daily_and_total_loss_stops(gw: Gateway, tmp_path) -> None:
    gw.markets = [_market(f"m{i}", "crypto", 1800) for i in range(4)]
    gw.quotes = {f"m{i}": (0.97, 0.98) for i in range(4)}
    ledger = FakeLedger()
    desk = P.PolyDesk(_live_settings(tmp_path, POLYDESK_LIVE_DAILY_LOSS_USD="1", POLYDESK_LIVE_TOTAL_LOSS_USD="3"),
                      ledger=ledger, client_factory=FakeExchange())
    desk.poll(NOW)
    assert len(desk.state["positions"]) == 4
    gw.markets = []
    gw.settlements = {f"m{i}": 0.0 for i in range(2)}  # two losses of ~$0.98: past the $1 daily stop, under the $3 total
    desk.poll(NOW + 2000)
    assert desk.state["mode"] == "live" and len(desk.state["positions"]) == 2
    gw.markets = [_market("new", "crypto", 1800)]
    gw.quotes = {"new": (0.97, 0.98)}
    desk.poll(NOW + 2100)
    assert "new" not in desk.state["positions"] and "Daily loss cap" in desk.state["live_status"]
    gw.markets = []
    gw.settlements.update({"m2": 0.0, "m3": 0.0})  # two more losses: past the $3 total stop
    desk.poll(NOW + 2200)
    assert desk.state["mode"] == "paper" and desk.state["live_halted"] and desk.client is None
    assert "Total loss cap" in desk.state["live_status"] and ledger.receipts[-1][0] == "polydesk_live_halted"
    # a restart with live settings stays on paper until the owner resets the state
    again = P.PolyDesk(_live_settings(tmp_path, POLYDESK_LIVE_TOTAL_LOSS_USD="3"), ledger=FakeLedger(), client_factory=FakeExchange())
    assert again.state["mode"] == "paper" and "stays on paper" in again.state["live_status"]
    d = P.panel_state(again.settings, NOW + 2300)
    assert d["label"] == "Paper money (pretend)" and d["live_pnl_total_usd"] < -3


def test_panel_tells_leftover_paper_positions_from_real_ones(gw: Gateway, tmp_path) -> None:
    gw.markets = [_market("p1", "crypto", 1800), _market("p2", "crypto", 1800)]
    gw.quotes = {"p1": (0.97, 0.98), "p2": (0.97, 0.98)}
    paper = P.PolyDesk(Settings.from_env({"DATA_DIR": str(tmp_path)}))
    paper.poll(NOW)
    assert len(paper.state["positions"]) == 2 and not any(p.get("live") for p in paper.state["positions"].values())
    # the owner switches the same desk (same state file) to live: the paper positions run off, new buys are real
    gw.markets = [_market("p1", "crypto", 1800), _market("p2", "crypto", 1800), _market("r1", "crypto", 1800)]
    gw.quotes["r1"] = (0.96, 0.97)
    live = P.PolyDesk(_live_settings(tmp_path), ledger=FakeLedger(), client_factory=FakeExchange())
    live.poll(NOW + 10)
    d = P.panel_state(live.settings, NOW + 10)
    assert d["mode"] == "live" and d["open"] == 3
    assert d["real"] == {"open": 1, "at_risk_usd": pytest.approx(0.97), "settled_total": 0, "won_total": 0,
                         "pnl_total_usd": 0.0, "today": {"pnl_usd": 0.0, "settled": 0, "won": 0}}
    assert d["paper"]["open"] == 2 and d["paper"]["settled_total"] == 0
    assert {(x["question"], x["live"]) for x in d["positions"]} == {
        ("Will p1 happen?", False), ("Will p2 happen?", False), ("Will r1 happen?", True)}
    # settlements book paper and real apart
    gw.markets = []
    gw.settlements = {"p1": 1.0, "p2": 0.0, "r1": 1.0}
    live.poll(NOW + 2000)
    d = P.panel_state(live.settings, NOW + 2000)
    assert d["real"]["settled_total"] == 1 and d["real"]["won_total"] == 1 and d["real"]["open"] == 0
    assert d["real"]["pnl_total_usd"] == pytest.approx(d["live_pnl_total_usd"]) and d["real"]["pnl_total_usd"] > 0
    assert d["paper"]["settled_total"] == 2 and d["paper"]["won_total"] == 1 and d["paper"]["open"] == 0
    assert d["paper"]["pnl_total_usd"] == pytest.approx(d["pnl_total_usd"] - d["real"]["pnl_total_usd"])
    assert d["paper"]["pnl_total_usd"] < 0  # one $20 paper loss outweighs one paper win


def test_silent_fills_are_found_in_the_venues_book(gw: Gateway, tmp_path) -> None:
    """2026-10-09: six real buys filled while every order reply showed no execution. The venue's book decides."""
    gw.markets = [_market("w1", "crypto", 1800), _market("w2", "crypto", 1800)]
    gw.quotes = {"w1": (0.96, 0.97), "w2": (0.97, 0.98)}
    ex = FakeExchange(cash=25.0)
    ex.silent_fills = True
    ledger = FakeLedger()
    desk = P.PolyDesk(_live_settings(tmp_path), ledger=ledger, client_factory=ex)
    r = desk.poll(NOW)
    assert r["bought"] == 2 and len(ex.orders) == 2
    pos = desk.state["positions"]
    assert pos["w1"]["live"] and pos["w1"]["cost_usd"] == pytest.approx(0.97) and pos["w2"]["cost_usd"] == pytest.approx(0.98)
    assert not any(e["text"].startswith("No fill") for e in desk.state["events"])
    assert [k for k, _ in ledger.receipts].count("polydesk_order_filled") == 2
    d = P.panel_state(desk.settings, NOW)
    assert d["real"]["open"] == 2 and d["real"]["at_risk_usd"] == pytest.approx(1.95)
    assert d["exchange"]["contracts"] == 2 and d["exchange"]["cost_usd"] == pytest.approx(1.95)


def test_venue_positions_the_desk_never_recorded_are_adopted_and_capped(gw: Gateway, tmp_path) -> None:
    gw.markets = [_market("k1", "crypto", 1800)]
    gw.quotes = {"k1": (0.96, 0.97)}
    ex = FakeExchange(cash=16.27)
    # real contracts bought under an earlier build: one on a watched market, one on a market the list no longer carries
    ex.hold("k1", 1.0, 0.97)
    ex.hold("aec-del-kec-sww", 1.0, 0.97, title="Koelner Haie vs. Schwenninger Wild Wings", outcome="Koelner Haie",
            event_slug="del-kec-sww")
    ex.book["aec-del-kec-sww"]["value"] = 0.68
    ledger = FakeLedger()
    desk = P.PolyDesk(_live_settings(tmp_path, POLYDESK_LIVE_MAX_OPEN_USD="2.5"), ledger=ledger, client_factory=ex)
    r = desk.poll(NOW)
    assert r["adopted"] == 2 and not ex.orders  # k1 is held already, so it is not bought again
    pos = desk.state["positions"]
    assert pos["k1"]["live"] and pos["k1"]["adopted"] and pos["k1"]["question"] == "Will k1 happen?" and pos["k1"]["end_known"]
    hockey = pos["aec-del-kec-sww"]
    assert hockey["question"] == "Koelner Haie vs. Schwenninger Wild Wings · Koelner Haie" and hockey["category"] == "sports"
    assert hockey["cost_usd"] == pytest.approx(0.97) and not hockey["end_known"] and hockey["end_ts"] == NOW + P.ADOPTED_END_GUESS_S
    assert [k for k, _ in ledger.receipts].count("polydesk_position_adopted") == 2
    d = P.panel_state(desk.settings, NOW)
    assert d["real"] == {"open": 2, "at_risk_usd": pytest.approx(1.94), "settled_total": 0, "won_total": 0,
                         "pnl_total_usd": 0.0, "today": {"pnl_usd": 0.0, "settled": 0, "won": 0}}
    assert d["exchange"] == {"positions": 2, "contracts": 2.0, "cost_usd": pytest.approx(1.94), "value_usd": pytest.approx(1.65),
                             "at": NOW}
    # the adopted money counts against the open cap: $1.94 held + $0.98 > $2.50
    gw.markets.append(_market("n1", "crypto", 1800))
    gw.quotes["n1"] = (0.97, 0.98)
    desk.poll(NOW + 100)
    assert not ex.orders and "n1" not in desk.state["positions"]
    # the venue's book is shown in paper mode too (the key is set, no orders are placed)
    paper = P.PolyDesk(Settings.from_env({"DATA_DIR": str(tmp_path / "p"), **KEY}), client_factory=ex)
    assert paper.state["mode"] == "paper" and paper.client is None and paper.reader is ex
    gw.markets = [_market("n1", "crypto", 1800)]
    r = paper.poll(NOW)
    assert r["adopted"] == 2 and not ex.orders and paper.state["positions"]["n1"]["live"] is False  # paper buy, real adoptions
    dd = P.panel_state(paper.settings, NOW)
    assert dd["mode"] == "paper" and dd["real"]["open"] == 2 and dd["paper"]["open"] == 1 and dd["balance"]["cash"] == 16.27
