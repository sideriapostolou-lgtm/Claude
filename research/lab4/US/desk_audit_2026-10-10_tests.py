"""Audit 2026-10-10: tests that describe the SAFE behaviour of the real-money path. Each one fails on 84d5ba9
(proving the leak) and should pass once the matching fix in research/lab4/US/desk_audit_2026-10-10.md is in.
No network, no keys: the repo's fake gateway and fake exchange."""

from __future__ import annotations

from typing import Any

import pytest

from nightcrawler import polydesk as P
from tests.test_polydesk import NOW, Gateway, _iso, _market
from tests.test_polydesk_live import FakeExchange, FakeLedger, _live_settings


class Gateway2(Gateway):
    """The fake gateway plus the fields the real quote reply carries (read 2026-10-10 from the public gateway:
    lastTradePx, sharesTraded, state, bidShares/askShares) and a second, fresher quote per market."""

    def __init__(self) -> None:
        super().__init__()
        self.extra: dict[str, dict[str, Any]] = {}
        self.fresh: dict[str, tuple[float, float]] = {}  # the quote a SECOND read of the market returns
        self.reads: dict[str, int] = {}

    def get(self, path: str, params: dict[str, Any] | None = None, tries: int = 3, timeout: float = 20.0) -> Any:
        if path.endswith("/bbo"):
            slug = path.split("/")[2]
            self.reads[slug] = self.reads.get(slug, 0) + 1
            bid, ask = self.quotes.get(slug, (None, None))
            if self.reads[slug] > 1 and slug in self.fresh:
                bid, ask = self.fresh[slug]
            x = {"lastTradePx": {"value": str(ask)} if ask is not None else None, "sharesTraded": "5000",
                 "state": "MARKET_STATE_OPEN", "bidShares": "500", "askShares": "500", **self.extra.get(slug, {})}
            return {"marketData": {"bestBid": {"value": str(bid)} if bid is not None else None,
                                   "bestAsk": {"value": str(ask)} if ask is not None else None, **x}}
        return super().get(path, params, tries, timeout)


@pytest.fixture
def gw(monkeypatch: pytest.MonkeyPatch) -> Gateway2:
    g = Gateway2()
    monkeypatch.setattr(P, "_get", g.get)
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    return g


class LaggingExchange(FakeExchange):
    """The venue as it behaved on 2026-10-10 (34 of 91 real fills): the order reply shows no execution AND the
    positions call right after it does not show the contract yet; it appears on a later positions call."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.hidden: dict[str, list[Any]] = {}  # slug -> [row, positions calls seen since the fill]
        self.fail_positions = False

    def buy_long_ioc(self, slug: str, price: float, quantity: float, max_block_s: int = 5) -> dict[str, Any]:
        self.orders.append({"slug": slug, "price": price, "quantity": quantity})
        self.hidden[slug] = [{"slug": slug, "qty": quantity, "avg_price": price, "cost": quantity * price,
                              "value": quantity * price, "realized": 0.0, "expired": False, "title": slug,
                              "outcome": "", "event_slug": "", "updated": "t"}, 0]
        return {"id": f"o{len(self.orders)}", "filled": 0.0, "avg_price": None, "cost": 0.0, "raw_executions": 0}

    def positions(self) -> list[dict[str, Any]]:
        if self.fail_positions:
            from nightcrawler.polymarket_us import PolymarketUSError
            raise PolymarketUSError("GET /v1/portfolio/positions: HTTP 503", status=503)
        for slug, (row, seen) in list(self.hidden.items()):
            if seen >= 1:
                self.book[slug] = row
                del self.hidden[slug]
            else:
                self.hidden[slug][1] = seen + 1
        return [dict(r) for r in self.book.values()]

    def venue_cost(self) -> float:
        return sum(r["cost"] for r in self.book.values()) + sum(r["cost"] for r, _ in self.hidden.values())


def _three_way(slug: str, title: str, start_offset_s: float, period: str, outcomes: tuple[str, ...],
               live: bool | None = None, ended: bool | None = None) -> dict[str, Any]:
    ev: dict[str, Any] = {"slug": slug, "title": title, "startTime": _iso(NOW + start_offset_s), "period": period,
                          "markets": [{"slug": f"atc-{slug}-{o}", "question": f"{title}: {o}?",
                                       "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME", "closed": False,
                                       "feeCoefficient": "0.0695"} for o in outcomes]}
    if live is not None:
        ev["live"] = live
    if ended is not None:
        ev["ended"] = ended
    return ev


# ---------------------------------------------------------------- F1: two outcomes of one game cannot both be 0.98
def test_an_incoherent_three_way_book_buys_nothing(gw: Gateway2, tmp_path) -> None:
    """2026-10-10 13:12: Sassuolo win, draw and Roma win of ONE e-soccer game all quoted 0.97/0.98; the desk bought
    all three at 0.98 ($2.94 for outcomes that pay $1.00 in total: -$1.94 whatever happened)."""
    gw.events = [_three_way("ebfsa-sas-roma-dh4", "eBattles: Sassuolo vs. Roma", -130, "3'", ("sas", "draw", "roma"))]
    gw.quotes = {f"atc-ebfsa-sas-roma-dh4-{o}": (0.97, 0.98) for o in ("sas", "draw", "roma")}
    ex = FakeExchange(cash=25.0)
    desk = P.PolyDesk(_live_settings(tmp_path), ledger=FakeLedger(), client_factory=ex)
    desk.poll(NOW)
    assert ex.orders == []  # the three bids add up to 2.91: the book is broken, not near-certain


def test_a_coherent_three_way_book_still_buys_the_leader_once(gw: Gateway2, tmp_path) -> None:
    """Regression guard for the F1 fix: a normal book (leader 0.97/0.98, draw and trailer 0.01/0.02) buys one."""
    gw.events = [_three_way("lal-ray-ath", "Rayo vs. Athletic", -5000, "2H", ("ray", "draw", "ath"))]
    gw.quotes = {"atc-lal-ray-ath-ray": (0.97, 0.98), "atc-lal-ray-ath-draw": (0.01, 0.02),
                 "atc-lal-ray-ath-ath": (0.01, 0.02)}
    ex = FakeExchange(cash=25.0)
    desk = P.PolyDesk(_live_settings(tmp_path), ledger=FakeLedger(), client_factory=ex)
    desk.poll(NOW)
    assert [o["slug"] for o in ex.orders] == ["atc-lal-ray-ath-ray"]


def test_one_real_position_per_ladder(gw: Gateway2, tmp_path) -> None:
    """2026-10-10 08:00 UTC: four real positions ($3.92) rode on one BTC price; one move past the strikes loses more
    than the $3 daily stop in a single settlement."""
    gw.markets = [_market(f"cpc-btc-above-hr-0800z-{k}", "crypto", 1800) for k in (82400, 82500, 82600)]
    gw.quotes = {m["slug"]: (0.97, 0.98) for m in gw.markets}
    ex = FakeExchange(cash=25.0)
    desk = P.PolyDesk(_live_settings(tmp_path), ledger=FakeLedger(), client_factory=ex)
    desk.poll(NOW)
    assert len(ex.orders) == 1


# ---------------------------------------------------------------- F2: an order the venue did not confirm still costs money
def test_an_unconfirmed_order_counts_against_the_open_cap_in_the_same_round(gw: Gateway2, tmp_path) -> None:
    """2026-10-10 13:14: an unconfirmed fill (Bakken Bears) was not counted, the next order (Botic) passed the cap,
    and the venue then held $10.74 against a $10.00 cap."""
    gw.markets = [_market(f"m{i}", "crypto", 1800) for i in range(3)]
    gw.quotes = {f"m{i}": (0.97, 0.98) for i in range(3)}
    ex = LaggingExchange(cash=25.0)
    desk = P.PolyDesk(_live_settings(tmp_path, POLYDESK_LIVE_MAX_OPEN_USD="2"), ledger=FakeLedger(), client_factory=ex)
    desk.poll(NOW)
    assert ex.venue_cost() <= 2.0 + 1e-9


def test_no_real_buys_when_the_venue_book_cannot_be_read(gw: Gateway2, tmp_path) -> None:
    """The pre-buy venue check fails: last round's unconfirmed fills are unknown, so the caps cannot be trusted."""
    gw.markets = [_market("m0", "crypto", 1800)]
    gw.quotes = {"m0": (0.97, 0.98)}
    ex = LaggingExchange(cash=25.0)
    desk = P.PolyDesk(_live_settings(tmp_path), ledger=FakeLedger(), client_factory=ex)
    ex.fail_positions = True
    desk.poll(NOW)
    assert ex.orders == []


# ---------------------------------------------------------------- F3: the loss stops must count money still at risk
def test_the_daily_stop_counts_money_still_at_risk(gw: Gateway2, tmp_path) -> None:
    gw.markets = [_market(f"m{i}", "crypto", 1800) for i in range(5)]
    gw.quotes = {f"m{i}": (0.97, 0.98) for i in range(5)}
    ex = FakeExchange(cash=25.0)
    desk = P.PolyDesk(_live_settings(tmp_path, POLYDESK_LIVE_DAILY_LOSS_USD="3"), ledger=FakeLedger(),
                      client_factory=ex)
    desk.poll(NOW)
    at_risk = sum(o["price"] * o["quantity"] for o in ex.orders)
    assert at_risk <= 3.0 + 1e-9  # if every open bet loses, the day still loses no more than the $3 stop


def test_the_total_stop_counts_money_still_at_risk(gw: Gateway2, tmp_path) -> None:
    st = P.empty_state()
    st["live_pnl_total_usd"] = -9.0
    settings = _live_settings(tmp_path)
    P.save_state(P.state_path(settings), st)
    gw.markets = [_market(f"m{i}", "crypto", 1800) for i in range(5)]
    gw.quotes = {f"m{i}": (0.97, 0.98) for i in range(5)}
    ex = FakeExchange(cash=25.0)
    desk = P.PolyDesk(settings, ledger=FakeLedger(), client_factory=ex)
    desk.poll(NOW)
    assert -9.0 - sum(o["price"] * o["quantity"] for o in ex.orders) >= -10.0 - 1e-9


# ---------------------------------------------------------------- F4: the desk's own unconfirmed buys are the rule's buys
def test_an_unconfirmed_fill_of_the_desks_own_order_counts_in_the_rules_record(gw: Gateway2, tmp_path) -> None:
    gw.markets = [_market("k1", "crypto", 1800)]
    gw.quotes = {"k1": (0.97, 0.98)}
    ex = LaggingExchange(cash=25.0)
    desk = P.PolyDesk(_live_settings(tmp_path), ledger=FakeLedger(), client_factory=ex)
    desk.poll(NOW)  # order sent, reply and positions show nothing
    desk.poll(NOW + 60)  # the venue check finds the contract
    assert desk.state["positions"]["k1"]["rule"] == desk.rule
    gw.markets = []
    gw.settlements = {"k1": 1.0}
    desk.poll(NOW + 2000)
    assert desk.state["by_rule"][desk.rule]["real"]["settled"] == 1


# ---------------------------------------------------------------- F5: a quote ~20 s old is not the book at order time
def test_a_real_order_rechecks_the_quote_first(gw: Gateway2, tmp_path) -> None:
    gw.markets = [_market("q1", "crypto", 1800)]
    gw.quotes = {"q1": (0.97, 0.98)}
    gw.fresh = {"q1": (0.90, 0.93)}  # the market fell between the round's quote and the order
    ex = FakeExchange(cash=25.0)
    desk = P.PolyDesk(_live_settings(tmp_path), ledger=FakeLedger(), client_factory=ex)
    desk.poll(NOW)
    assert ex.orders == []


# ---------------------------------------------------------------- F6: a market that never traded has no price yet
def test_a_market_that_never_traded_is_not_near_certain(gw: Gateway2, tmp_path) -> None:
    """All three e-soccer orders of 13:12 were the FIRST trades those markets ever had (the venue's book stats)."""
    gw.markets = [_market("fresh", "crypto", 1800), _market("traded", "crypto", 1800)]
    gw.quotes = {"fresh": (0.97, 0.98), "traded": (0.97, 0.98)}
    gw.extra = {"fresh": {"lastTradePx": None, "sharesTraded": "0"}}
    ex = FakeExchange(cash=25.0)
    desk = P.PolyDesk(_live_settings(tmp_path), ledger=FakeLedger(), client_factory=ex)
    desk.poll(NOW)
    assert [o["slug"] for o in ex.orders] == ["traded"]


# ---------------------------------------------------------------- F7: the venue says which games are in play
def test_ended_and_postponed_games_are_not_in_play(gw: Gateway2) -> None:
    """2026-10-10 18:4x UTC listing: 'VFT' (ended, live false) and 'POST' (postponed, live false) pass the desk's
    deny-list of periods."""
    gw.events = [_three_way("epl-mnu-tot", "Man Utd vs. Spurs", -8000, "VFT", ("mnu", "draw", "tot"), live=False,
                            ended=True),
                 _three_way("vtb-mba-eni", "MBA vs. Enisey", -3000, "POST", ("mba", "draw", "eni"), live=False,
                            ended=False),
                 _three_way("lal-ray-ath", "Rayo vs. Athletic", -5000, "2H", ("ray", "draw", "ath"), live=True,
                            ended=False)]
    got = {m["slug"].rsplit("-", 1)[0] for m in P.live_sports_markets(NOW)}
    assert got == {"atc-lal-ray-ath"}


# ---------------------------------------------------------------- F8: book a finished market as soon as its quote is closed
def test_a_closed_market_still_on_the_live_list_is_settled_this_round(gw: Gateway2, tmp_path) -> None:
    """14 ITF matches were booked ~64 min after the venue settled them (the games stayed on the live list)."""
    gw.events = [_three_way("itf-a-b", "A vs. B", -5000, "S2", ("a", "draw", "b"))]
    gw.quotes = {"atc-itf-a-b-a": (0.97, 0.98), "atc-itf-a-b-draw": (0.01, 0.02), "atc-itf-a-b-b": (0.01, 0.02)}
    ex = FakeExchange(cash=25.0)
    desk = P.PolyDesk(_live_settings(tmp_path), ledger=FakeLedger(), client_factory=ex)
    desk.poll(NOW)
    assert "atc-itf-a-b-a" in desk.state["positions"]
    gw.extra = {s: {"state": "MARKET_STATE_CLOSED"} for s in gw.quotes}
    gw.quotes = {s: (None, None) for s in gw.quotes}
    gw.settlements = {"atc-itf-a-b-a": 1.0}
    desk.poll(NOW + 600)  # still listed as live, but the market is closed and settled
    assert "atc-itf-a-b-a" not in desk.state["positions"]


# ---------------------------------------------------------------- F13: the tried list keeps the NEWEST, not the alphabetically last
def test_the_tried_list_drops_the_oldest_not_the_sports_slugs(gw: Gateway2, tmp_path) -> None:
    settings = _live_settings(tmp_path)
    st = P.empty_state()
    st["tried"] = [f"zz-old-{i:05d}" for i in range(5000)]
    P.save_state(P.state_path(settings), st)
    gw.markets = [_market("aec-new", "crypto", 1800)]
    gw.quotes = {"aec-new": (0.97, 0.98)}
    ex = FakeExchange(cash=25.0)
    ex.reject_orders = True  # tried but not held: only the tried list stops a retry
    desk = P.PolyDesk(settings, ledger=FakeLedger(), client_factory=ex)
    desk.poll(NOW)
    assert "aec-new" in desk.state["tried"]
