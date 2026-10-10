"""The Polymarket desk in LIVE mode, against a fake exchange client: the gate (confirm phrase, key, a balance read,
a record file that can be read), real buys on the long side only with caps, rejected and unconfirmed orders,
settlement with the real cost, the daily and total loss stops (counting money still at risk; the total stop switches
back to paper for good), receipts, and the panel's labels. The audit's fixes: tests/test_polydesk_safety.py."""

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
    gw.markets = [_market(f"m{i}", "crypto", 1800 + i) for i in range(15)]  # fifteen ladders, one rung each
    gw.quotes = {f"m{i}": (0.97, 0.98) for i in range(15)}
    ex = FakeExchange(cash=25.0)
    desk = P.PolyDesk(_live_settings(tmp_path, POLYDESK_LIVE_MAX_OPEN_USD="5", POLYDESK_LIVE_DAILY_LOSS_USD="50",
                                     POLYDESK_LIVE_TOTAL_LOSS_USD="50"), ledger=FakeLedger(), client_factory=ex)
    desk.poll(NOW)
    real = [p for p in desk.state["positions"].values() if p["live"]]
    assert len(ex.orders) == 5 and len(real) == 5  # 5 x $0.98 fits under $5; the 6th does not
    paper = [p for p in desk.state["positions"].values() if not p["live"]]
    assert len(paper) == P.PAPER_LEARNING_OPEN  # what real money could not take is practised on paper (its own cap)
    # a rejected order leaves no position, is not retried, and holds its ladder for the round (one order per ladder)
    gw.markets = [_market("r1", "crypto", 1800), _market("z1", "crypto", 1800)]
    gw.quotes = {"r1": (0.97, 0.98), "z1": (0.97, 0.98)}
    desk2 = P.PolyDesk(_live_settings(tmp_path / "2"), ledger=FakeLedger(), client_factory=FakeExchange())
    desk2.client.reject_orders = True  # type: ignore[union-attr]
    desk2.poll(NOW)
    assert not desk2.state["positions"] and "r1" in desk2.state["tried"] and desk2.state["counters"]["errors"] == 1
    assert [o["slug"] for o in desk2.client.orders] == ["r1"]  # type: ignore[union-attr]
    # a reply with no fill is not the last word: counted as open money until the venue's book has spoken
    desk3 = P.PolyDesk(_live_settings(tmp_path / "3"), ledger=FakeLedger(), client_factory=FakeExchange())
    desk3.client.fill_price = 0  # type: ignore[union-attr]
    desk3.poll(NOW)
    assert not desk3.state["positions"] and set(desk3.state["pending_orders"]) == {"r1"}
    assert desk3.state["events"][0]["text"].startswith("Order not confirmed yet at 0.980: Will r1 happen?")
    desk3.poll(NOW + 400)  # a quiet venue read five minutes on: it never filled
    assert not desk3.state["positions"] and not desk3.state["pending_orders"]
    assert desk3.state["events"][0]["text"] == "No fill at 0.980: Will r1 happen? (order cancelled)"


def test_daily_and_total_loss_stops(gw: Gateway, tmp_path) -> None:
    """The stops count money still at risk (rule 2026-10-10a): a day can lose at most the daily stop even if every
    open bet loses, so the rule's own bets stop short of it; the day's realised loss at the stop holds the line for
    the day; the total stop, once realised (here through a contract bought elsewhere, which the venue's book makes
    the desk's), switches the desk back to paper for good, and a restart stays on paper."""
    settings = _live_settings(tmp_path, POLYDESK_LIVE_DAILY_LOSS_USD="2", POLYDESK_LIVE_TOTAL_LOSS_USD="3")
    gw.markets = [_market(f"m{i}", "crypto", 1800 + i) for i in range(4)]
    gw.quotes = {f"m{i}": (0.97, 0.98) for i in range(4)}
    ledger = FakeLedger()
    ex = FakeExchange()
    desk = P.PolyDesk(settings, ledger=ledger, client_factory=ex)
    desk.poll(NOW)
    real = {s for s, p in desk.state["positions"].items() if p["live"]}
    assert real == {"m0", "m1"} and len(ex.orders) == 2  # two bets ($1.96 with fees) fit the $2 day; a third would not
    assert desk.state["positions"]["m2"]["live"] is False  # the rest is practised on paper
    gw.markets = []
    gw.settlements = {"m0": 0.0, "m1": 0.0, "m2": 1.0, "m3": 1.0}  # both real bets lose: -$1.96, under the $2 stop
    desk.poll(NOW + 2000)
    day = datetime.fromtimestamp(NOW, UTC).strftime("%Y-%m-%d")
    assert desk.state["mode"] == "live" and desk.state["live_days"][day]["pnl_usd"] == pytest.approx(-1.9627, abs=1e-3)
    gw.markets = [_market("new", "crypto", 3900)]
    gw.quotes = {"new": (0.97, 0.98)}
    desk.poll(NOW + 2100)  # $0.04 of room left today: no real order, a practice bet instead
    assert len(ex.orders) == 2 and desk.state["positions"]["new"]["live"] is False
    assert desk.state["live_status"] is None  # not the daily stop: the room for one more bet that could lose
    assert P.panel_state(settings, NOW + 2100)["skips"]["counts"]["stop_room"] == 3  # m2, m3 this morning, now new
    # two contracts bought elsewhere show up in the venue's book and lose: past the $2 day and the $3 total
    ex.hold("outside", 2.0, 0.97, title="Bought elsewhere", outcome="Yes")
    gw.markets = []
    desk.poll(NOW + 2200)
    assert desk.state["positions"]["outside"]["rule"] == "venue"
    gw.settlements["outside"] = 0.0
    desk.poll(NOW + 2200 + P.ADOPTED_END_GUESS_S + 1)
    assert desk.state["mode"] == "paper" and desk.state["live_halted"] and desk.client is None
    assert desk.state["halt_reason"] == "total_loss"
    assert "Total loss cap" in desk.state["live_status"] and ledger.receipts[-1][0] == "polydesk_live_halted"
    # a restart with live settings stays on paper until the owner resets the state
    again = P.PolyDesk(_live_settings(tmp_path, POLYDESK_LIVE_TOTAL_LOSS_USD="3"), ledger=FakeLedger(),
                       client_factory=FakeExchange())
    assert again.state["mode"] == "paper" and again.state["live_status"] == P.TOTAL_HALT_STATUS
    assert "stays on paper" in again.state["live_status"]
    d = P.panel_state(again.settings, NOW + 2300)
    assert d["label"] == "Paper money (pretend)" and d["live_pnl_total_usd"] < -3


def test_panel_tells_leftover_paper_positions_from_real_ones(gw: Gateway, tmp_path) -> None:
    gw.markets = [_market("p1", "crypto", 1800), _market("p2", "crypto", 1801)]
    gw.quotes = {"p1": (0.97, 0.98), "p2": (0.97, 0.98)}
    paper = P.PolyDesk(Settings.from_env({"DATA_DIR": str(tmp_path)}))
    paper.poll(NOW)
    assert len(paper.state["positions"]) == 2 and not any(p.get("live") for p in paper.state["positions"].values())
    # the owner switches the same desk (same state file) to live: the paper positions run off, new buys are real
    gw.markets = [_market("p1", "crypto", 1800), _market("p2", "crypto", 1801), _market("r1", "crypto", 1802)]
    gw.quotes["r1"] = (0.96, 0.97)
    live = P.PolyDesk(_live_settings(tmp_path), ledger=FakeLedger(), client_factory=FakeExchange())
    live.poll(NOW + 10)
    d = P.panel_state(live.settings, NOW + 10)
    assert d["mode"] == "live" and d["open"] == 3
    worst = 0.97 + 0.0695 * 0.97 * 0.03  # if the open bet lost: its cost and the modelled fee
    assert d["real"] == {"open": 1, "at_risk_usd": pytest.approx(0.97), "settled_total": 0, "won_total": 0,
                         "pnl_total_usd": 0.0, "today": {"pnl_usd": 0.0, "settled": 0, "won": 0},
                         "pending": 0, "pending_usd": 0.0, "stop_room_usd": pytest.approx(3.0 - worst),
                         "stop_room_limit": "day"}
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
    gw.markets = [_market("w1", "crypto", 1800), _market("w2", "crypto", 1801)]
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
    worst = 2 * (0.97 + 0.0695 * 0.97 * 0.03)  # both lost: their cost and the modelled fee
    assert d["real"] == {"open": 2, "at_risk_usd": pytest.approx(1.94), "settled_total": 0, "won_total": 0,
                         "pnl_total_usd": 0.0, "today": {"pnl_usd": 0.0, "settled": 0, "won": 0},
                         "pending": 0, "pending_usd": 0.0, "stop_room_usd": pytest.approx(3.0 - worst),
                         "stop_room_limit": "day"}
    assert d["exchange"] == {"positions": 2, "contracts": 2.0, "cost_usd": pytest.approx(1.94), "value_usd": pytest.approx(1.65),
                             "at": NOW}
    # the adopted money counts against the open cap: $1.94 held + $0.98 > $2.50 (another ladder: n1 ends later)
    gw.markets.append(_market("n1", "crypto", 1900))
    gw.quotes["n1"] = (0.97, 0.98)
    desk.poll(NOW + 100)
    assert not ex.orders and desk.state["positions"]["n1"]["live"] is False  # practised on paper instead
    # the venue's book is shown in paper mode too (the key is set, no orders are placed)
    paper = P.PolyDesk(Settings.from_env({"DATA_DIR": str(tmp_path / "p"), **KEY}), client_factory=ex)
    assert paper.state["mode"] == "paper" and paper.client is None and paper.reader is ex
    gw.markets = [_market("n1", "crypto", 1900)]
    r = paper.poll(NOW)
    assert r["adopted"] == 2 and not ex.orders and paper.state["positions"]["n1"]["live"] is False  # paper buy, real adoptions
    dd = P.panel_state(paper.settings, NOW)
    assert dd["mode"] == "paper" and dd["real"]["open"] == 2 and dd["paper"]["open"] == 1 and dd["balance"]["cash"] == 16.27


def test_real_buys_and_venue_adoptions_carry_their_rule_and_the_record_splits(gw: Gateway, tmp_path,
                                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(P, "PAPER_MAX_OPEN", 0)  # the paper cap never limits real buys
    gw.markets = [_market("w1", "climate", 1800), _market("w2", "crypto", 1800), _market("s1", "crypto", 1800)]
    gw.quotes = {"w1": (0.96, 0.975), "w2": (0.97, 0.98), "s1": (0.02, 0.04)}  # s1 is a short setup: never placed live
    ex = FakeExchange(cash=25.0)
    ex.hold("held", 1.0, 0.97, title="Held before this build", outcome="Yes", event_slug="x")
    desk = P.PolyDesk(_live_settings(tmp_path), ledger=FakeLedger(), client_factory=ex)
    r = desk.poll(NOW)
    assert (r["bought"], r["adopted"]) == (2, 1)
    pos = desk.state["positions"]
    assert pos["w1"]["live"] and pos["w1"]["rule"] == P.rule_id(desk.settings) and pos["w1"]["spread_in"] == pytest.approx(0.015)
    assert (pos["w1"]["bid_in"], pos["w1"]["ask_in"]) == (0.96, 0.975) and pos["w2"]["rule"] == P.rule_id(desk.settings)
    assert pos["held"]["rule"] == "venue" and pos["held"]["adopted"] and "spread_in" not in pos["held"]  # not this rule's buy
    assert "s1" not in pos and not any(e["text"].startswith("Paper book full") for e in desk.state["events"])
    zero = {"settled_total": 0, "won_total": 0, "pnl_total_usd": 0.0}
    d = P.panel_state(desk.settings, NOW)
    assert d["since_fix"] == {"rule": P.rule_id(desk.settings), "paper": {"open": 0, **zero}, "real": {"open": 2, **zero}}
    assert d["before_fix"] == {"rule": "before the fix", "paper": {"open": 0, **zero}, "real": {"open": 1, **zero}}
    # settlements: the rule's real record since the fix stands apart from the venue position's
    gw.markets = []
    gw.settlements = {"w1": 1.0, "w2": 0.0, "held": 1.0}
    desk.poll(NOW + 2000)
    closed = {c["slug"]: c for c in desk.state["closed"]}
    assert closed["held"]["rule"] == "venue" and closed["w2"]["rule"] == P.rule_id(desk.settings)  # inherited
    d = P.panel_state(desk.settings, NOW + 2000)
    since, before = d["since_fix"], d["before_fix"]
    assert (since["real"]["settled_total"], since["real"]["won_total"]) == (2, 1)
    assert since["real"]["pnl_total_usd"] == pytest.approx(closed["w1"]["pnl_usd"] + closed["w2"]["pnl_usd"])
    assert since["paper"] == {"open": 0, **zero}
    assert (before["real"]["settled_total"], before["real"]["won_total"]) == (1, 1)
    assert before["real"]["pnl_total_usd"] == pytest.approx(closed["held"]["pnl_usd"])
    assert before["paper"] == {"open": 0, **zero}
    assert d["real"]["settled_total"] == 3 and d["real"]["pnl_total_usd"] == pytest.approx(
        since["real"]["pnl_total_usd"] + before["real"]["pnl_total_usd"])
    assert set(desk.state["by_rule"]) == {P.rule_id(desk.settings), "venue"}
    assert "paper" not in desk.state["by_rule"]["venue"] and "paper" not in desk.state["by_rule"][desk.rule]


# --------------------------------------------------------------------------- C14: a record file that cannot be read


@pytest.mark.parametrize("junk", ["not json", '{"version": 99, "live_pnl_total_usd": -4.885}', "[1, 2]"],
                         ids=["not-json", "another-version", "not-an-object"])
def test_an_unreadable_state_file_refuses_live_and_keeps_a_copy(gw: Gateway, tmp_path, junk: str) -> None:
    """The file holds the loss stops (-$4.89 so far, today's loss, the halt). Read as empty, it would re-arm the
    full $10 total stop, so a live desk refuses real money from it, says why, and keeps the file for the owner."""
    settings = _live_settings(tmp_path)
    path = P.state_path(settings)
    path.parent.mkdir(parents=True)
    path.write_text(junk)
    ledger = FakeLedger()
    ex = FakeExchange(cash=17.43)
    desk = P.PolyDesk(settings, ledger=ledger, client_factory=ex)
    assert desk.state["mode"] == "paper" and desk.client is None and desk.state["live_halted"] is True
    assert desk.state["halt_reason"] == "unreadable_state" and desk.state["live_status"] == P.UNREADABLE_STATUS
    assert "loss limits cannot be trusted" in desk.state["live_status"]
    copies = list(path.parent.glob("state.json.unreadable-*"))
    assert len(copies) == 1 and copies[0].read_text() == junk  # the evidence, as it was
    assert [k for k, _ in ledger.receipts] == ["polydesk_state_unreadable"]  # never polydesk_live_connected
    assert desk.state["events"][0]["text"].startswith("The desk's record file could not be read")
    gw.markets = [_market("w1", "crypto", 1800)]
    gw.quotes = {"w1": (0.97, 0.98)}
    desk.poll(NOW)
    assert not ex.orders and desk.state["positions"]["w1"]["live"] is False  # practice only
    assert P.load_state(path)["live_halted"] is True  # the saved state carries the halt


def test_a_restart_after_an_unreadable_file_stays_off(gw: Gateway, tmp_path) -> None:
    settings = _live_settings(tmp_path)
    path = P.state_path(settings)
    path.parent.mkdir(parents=True)
    path.write_text("{garbage")
    P.PolyDesk(settings, ledger=FakeLedger(), client_factory=FakeExchange())
    ex = FakeExchange()
    again = P.PolyDesk(settings, ledger=FakeLedger(), client_factory=ex)  # the file is readable now: the halt holds
    assert again.state["mode"] == "paper" and again.client is None and again.state["live_status"] == P.UNREADABLE_STATUS
    assert len(list(path.parent.glob("state.json.unreadable-*"))) == 1  # the second start found a good file
    # POLYDESK_MODE is untouched: only the owner resets the state
    assert again.settings.polydesk_mode == "live" and P.panel_state(settings, NOW)["mode"] == "paper"


def test_a_good_file_still_goes_live(gw: Gateway, tmp_path) -> None:
    settings = _live_settings(tmp_path)
    st = P.empty_state()
    st["live_pnl_total_usd"] = -4.885
    P.save_state(P.state_path(settings), st)
    desk = P.PolyDesk(settings, ledger=FakeLedger(), client_factory=FakeExchange())
    assert desk.state["mode"] == "live" and desk.state["live_halted"] is False and desk.state["halt_reason"] is None
    assert desk.state["live_pnl_total_usd"] == pytest.approx(-4.885)
    assert not list(P.state_path(settings).parent.glob("state.json.unreadable-*"))
    fresh = P.PolyDesk(_live_settings(tmp_path / "new"), ledger=FakeLedger(), client_factory=FakeExchange())
    assert fresh.state["mode"] == "live"  # no file at all is a first start, not an unreadable one
