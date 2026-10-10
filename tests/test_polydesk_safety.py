"""The real-money audit of 2026-10-10 (research/lab4/US/desk_audit_2026-10-10.md) as the desk's regression suite:
each leak it found, closed (rule 2026-10-10a), plus the owner's question, "which sports are screwing us", answered
the way lab 4's history test did (P6: no sport allowed, so no real money on sports). The audit's own tests
(research/lab4/US/desk_audit_2026-10-10_tests.py) are here, adjusted where a later fix changes what they can see
(sports are practised on paper, one order per ladder). No network, no keys: the repo's fake gateway and fake
exchange, extended with the fields the real venue sends."""

from __future__ import annotations

import importlib.util
import inspect
import json
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from nightcrawler import polydesk as P
from nightcrawler import sportmap
from nightcrawler.config import Settings
from nightcrawler.polymarket_us import PolymarketUSError
from tests.test_polydesk import NOW, Gateway, _event, _iso, _market
from tests.test_polydesk_live import FakeExchange, FakeLedger, _live_settings

ROOT = Path(__file__).resolve().parents[1]
TODAY = datetime.fromtimestamp(NOW, UTC).strftime("%Y-%m-%d")
#: Nine +$0.40 practice settlements then a -$20 one, six times: 90 % won and losing money (deskguard: losing).
LOSING = ([0.40] * 9 + [-20.0]) * 6


class Gateway2(Gateway):
    """The fake gateway plus a second, fresher quote per market (``fresh``: what a SECOND read of the market
    returns) and markets whose quote read fails (``fail``)."""

    def __init__(self) -> None:
        super().__init__()
        self.fresh: dict[str, tuple[float, float]] = {}
        self.reads: dict[str, int] = {}
        self.fail: set[str] = set()

    def get(self, path: str, params: dict[str, Any] | None = None, tries: int = 3, timeout: float = 20.0) -> Any:
        if path.endswith("/bbo"):
            slug = path.split("/")[2]
            if slug in self.fail:
                raise RuntimeError(f"GET {path} failed: HTTP 503")
            self.reads[slug] = self.reads.get(slug, 0) + 1
            if self.reads[slug] > 1 and slug in self.fresh:
                saved = self.quotes.get(slug)
                self.quotes[slug] = self.fresh[slug]
                try:
                    return super().get(path, params, tries, timeout)
                finally:
                    if saved is not None:
                        self.quotes[slug] = saved
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
        self.position_reads = 0

    def buy_long_ioc(self, slug: str, price: float, quantity: float, max_block_s: int = 5) -> dict[str, Any]:
        self.orders.append({"slug": slug, "price": price, "quantity": quantity})
        self.hidden[slug] = [{"slug": slug, "qty": quantity, "avg_price": price, "cost": quantity * price,
                              "value": quantity * price, "realized": 0.0, "expired": False, "title": slug,
                              "outcome": "", "event_slug": "", "updated": "t"}, 0]
        return {"id": f"o{len(self.orders)}", "filled": 0.0, "avg_price": None, "cost": 0.0, "raw_executions": 0}

    def positions(self) -> list[dict[str, Any]]:
        self.position_reads += 1
        if self.fail_positions:
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


class SilentExchange(FakeExchange):
    """Answers every order with no fill and never shows a contract (the order really did not fill); its positions
    read can be made to fail."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.fill_price = 0
        self.fail_positions = False

    def positions(self) -> list[dict[str, Any]]:
        if self.fail_positions:
            raise PolymarketUSError("GET /v1/portfolio/positions: HTTP 503", status=503)
        return super().positions()


def _three_way(slug: str, title: str, start_offset_s: float, period: str, outcomes: tuple[str, ...],
               live: bool | None = True, ended: bool | None = None, **extra: Any) -> dict[str, Any]:
    """A game with one DRAWABLE_OUTCOME market per outcome (``atc-<slug>-<outcome>``), in play by default (the
    venue's ``live`` flag)."""
    ev: dict[str, Any] = {"slug": slug, "title": title, "startTime": _iso(NOW + start_offset_s), "period": period,
                          "markets": [{"slug": f"atc-{slug}-{o}", "question": f"{title}: {o}?",
                                       "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME", "closed": False,
                                       "feeCoefficient": "0.0695"} for o in outcomes], **extra}
    if live is not None:
        ev["live"] = live
    if ended is not None:
        ev["ended"] = ended
    return ev


def _paper(tmp_path: Path, **env: str) -> Settings:
    return Settings.from_env({"DATA_DIR": str(tmp_path), **env})


def _desk(settings: Settings, ex: FakeExchange | None = None, ledger: FakeLedger | None = None) -> P.PolyDesk:
    return P.PolyDesk(settings, ledger=ledger or FakeLedger(), client_factory=ex or FakeExchange(cash=25.0))


def _said(desk: P.PolyDesk, start: str) -> list[dict[str, Any]]:
    return [e for e in desk.state["events"] if e["text"].startswith(start)]


def _skips(settings: Settings, now: float = NOW) -> dict[str, Any]:
    return P.panel_state(settings, now)["skips"]


def _real(desk: P.PolyDesk) -> dict[str, dict[str, Any]]:
    return {s: p for s, p in desk.state["positions"].items() if p.get("live")}


def _practice(desk: P.PolyDesk) -> dict[str, dict[str, Any]]:
    return {s: p for s, p in desk.state["positions"].items() if not p.get("live")}


ESOCCER = ("ebfsa-sas-roma-dh4", "eBattles: Sassuolo vs. Roma", -130, "3'", ("sas", "draw", "roma"))
RAYO = ("lal-ray-ath", "Rayo vs. Athletic", -5000, "2H", ("ray", "draw", "ath"))
LEADER = {"atc-lal-ray-ath-ray": (0.97, 0.98), "atc-lal-ray-ath-draw": (0.01, 0.02),
          "atc-lal-ray-ath-ath": (0.01, 0.02)}


# ---------------------------------------------------------------- C2 / F1: one outcome per game, and only books that add up
@pytest.mark.parametrize("mode", ["real_money", "paper"])
def test_an_incoherent_three_way_book_buys_nothing(gw: Gateway2, tmp_path: Path, mode: str) -> None:
    """2026-10-10 13:12: Sassuolo win, draw and Roma win of ONE e-soccer game all quoted 0.97/0.98; the desk bought
    all three at 0.98 ($2.94 for outcomes that pay $1.00 in total: -$1.94 whatever happened). Paper too: in live
    mode the sports block alone would keep real money out, so the practice book is the real test of the check."""
    gw.events = [_three_way(*ESOCCER)]
    gw.quotes = {f"atc-ebfsa-sas-roma-dh4-{o}": (0.97, 0.98) for o in ("sas", "draw", "roma")}
    ex = FakeExchange(cash=25.0)
    settings = _live_settings(tmp_path) if mode == "real_money" else _paper(tmp_path)
    desk = _desk(settings, ex)
    desk.poll(NOW)
    assert ex.orders == [] and not desk.state["positions"]  # the bids add up to 2.91: broken, not near-certain
    refused = _said(desk, "Refused a game whose prices do not add up: ")
    assert [e["text"] for e in refused] == [
        "Refused a game whose prices do not add up: eBattles: Sassuolo vs. Roma (YES bids add up to 2.91)"]
    assert set(gw.quotes) <= set(desk.state["tried"])  # every outcome, in both books: never bought later
    desk.poll(NOW + 60)
    assert not desk.state["positions"] and len(_said(desk, "Refused a game")) == 1
    assert _skips(settings)["counts"] == {"incoherent_game": 1}  # one game, counted once


@pytest.mark.parametrize("mode", ["real_money", "paper"])
def test_a_coherent_three_way_book_still_buys_the_leader_once(gw: Gateway2, tmp_path: Path, mode: str) -> None:
    """A normal book (leader 0.97/0.98, draw and trailer 0.01/0.02) still buys one: on paper in live mode too (no
    sport has earned real money), never with a real order."""
    gw.events = [_three_way(*RAYO)]
    gw.quotes = dict(LEADER)
    ex = FakeExchange(cash=25.0)
    desk = _desk(_live_settings(tmp_path) if mode == "real_money" else _paper(tmp_path), ex)
    desk.poll(NOW)
    assert ex.orders == []
    assert {s: p["live"] for s, p in desk.state["positions"].items()} == {"atc-lal-ray-ath-ray": False}
    assert desk.state["positions"]["atc-lal-ray-ath-ray"]["sport"] == "soccer"
    assert not _said(desk, "Refused a game")


@pytest.mark.parametrize("mode", ["real_money", "paper"])
def test_one_real_position_per_ladder(gw: Gateway2, tmp_path: Path, mode: str) -> None:
    """2026-10-10 08:00 UTC: four real positions ($3.92) rode on one BTC price; one move past the strikes loses more
    than the $3 daily stop in a single settlement. The practice book holds one rung of a ladder too."""
    gw.markets = [_market(f"cpc-btc-above-hr-0800z-{k}", "crypto", 1800) for k in (82400, 82500, 82600)]
    gw.quotes = {m["slug"]: (0.97, 0.98) for m in gw.markets}
    ex = FakeExchange(cash=25.0)
    settings = _live_settings(tmp_path) if mode == "real_money" else _paper(tmp_path)
    desk = _desk(settings, ex)
    desk.poll(NOW)
    assert len(desk.state["positions"]) == 1
    if mode == "real_money":
        assert len(ex.orders) == 1 and len(_real(desk)) == 1
    else:
        assert ex.orders == [] and len(_practice(desk)) == 1
    assert _skips(settings)["counts"] == {"game_held": 2}  # the other two rungs: held, marked tried
    assert {m["slug"] for m in gw.markets} <= set(desk.state["tried"])


def test_a_held_game_is_not_bought_again_on_a_comeback(gw: Gateway2, tmp_path: Path) -> None:
    """The desk holds the leader; the game turns and the other side becomes near-certain in a coherent book: it is
    not a second bet on the same game (one position per game, in both books)."""
    gw.events = [_three_way(*RAYO)]
    gw.quotes = dict(LEADER)
    desk = _desk(_paper(tmp_path))
    desk.poll(NOW)
    assert set(desk.state["positions"]) == {"atc-lal-ray-ath-ray"}
    gw.quotes = {"atc-lal-ray-ath-ray": (0.01, 0.02), "atc-lal-ray-ath-draw": (0.01, 0.02),
                 "atc-lal-ray-ath-ath": (0.97, 0.98)}  # bids 0.99: coherent, a comeback
    desk.poll(NOW + 60)
    assert set(desk.state["positions"]) == {"atc-lal-ray-ath-ray"} and "atc-lal-ray-ath-ath" in desk.state["tried"]


def test_a_game_cut_by_the_cap_is_skipped_this_round(gw: Gateway2, tmp_path: Path) -> None:
    """Three outcomes, only two quoted this round (the sports cap or a failed read): the book cannot be checked, so
    nothing is bought and nothing is marked tried; the next round, with all three quoted, buys the leader."""
    gw.events = [_three_way(*RAYO)]
    gw.quotes = dict(LEADER)
    gw.fail = {"atc-lal-ray-ath-draw"}
    settings = _paper(tmp_path)
    desk = _desk(settings)
    watch = P.live_sports_markets(NOW)
    assert {m["n_outcomes"] for m in watch} == {3}
    desk.poll(NOW)
    assert not desk.state["positions"] and not set(LEADER) & set(desk.state.get("tried") or [])
    assert _skips(settings)["counts"] == {"game_incomplete": 1}
    gw.fail = set()
    desk.poll(NOW + 60)
    assert set(desk.state["positions"]) == {"atc-lal-ray-ath-ray"}


# ---------------------------------------------------------------- C3 / F2: a market that never traded has no price yet
def test_a_market_that_never_traded_is_not_near_certain(gw: Gateway2, tmp_path: Path) -> None:
    """All three e-soccer orders of 13:12 were the FIRST trades those markets ever had (the venue's book stats)."""
    gw.markets = [_market("fresh", "crypto", 1800), _market("traded", "crypto", 1801)]
    gw.quotes = {"fresh": (0.97, 0.98), "traded": (0.97, 0.98)}
    gw.extra = {"fresh": {"lastTradePx": None, "sharesTraded": "0"}}
    ex = FakeExchange(cash=25.0)
    settings = _live_settings(tmp_path)
    desk = _desk(settings, ex)
    desk.poll(NOW)
    assert [o["slug"] for o in ex.orders] == ["traded"] and "fresh" not in desk.state["positions"]
    assert "fresh" not in desk.state["tried"]  # it may trade later
    assert _skips(settings)["counts"] == {"never_traded": 1}
    # the practice book's twin: no paper position on it either
    paper = _desk(_paper(tmp_path / "p"))
    paper.poll(NOW)
    assert set(paper.state["positions"]) == {"traded"}


def test_a_closed_state_quote_is_not_bought(gw: Gateway2, tmp_path: Path) -> None:
    gw.markets = [_market("shut", "crypto", 1800)]
    gw.quotes = {"shut": (0.97, 0.98)}
    gw.extra = {"shut": {"state": "MARKET_STATE_CLOSED"}}
    ex = FakeExchange(cash=25.0)
    desk = _desk(_live_settings(tmp_path), ex)
    desk.poll(NOW)
    assert ex.orders == [] and not desk.state["positions"]
    gw.extra = {"shut": {"state": None}}  # a reply without the state says nothing about trading: not bought either
    desk.poll(NOW + 60)
    assert ex.orders == [] and not desk.state["positions"]


def test_a_last_trade_far_below_theta_is_not_bought(gw: Gateway2, tmp_path: Path) -> None:
    gw.markets = [_market("cheap", "crypto", 1800)]
    gw.quotes = {"cheap": (0.97, 0.98)}
    gw.extra = {"cheap": {"lastTradePx": {"value": "0.60"}}}  # offers at 0.98, but it last traded at 0.60
    desk = _desk(_paper(tmp_path))
    desk.poll(NOW)
    assert not desk.state["positions"] and "cheap" not in desk.state["tried"]
    gw.extra = {"cheap": {"lastTradePx": {"value": "0.95"}}}  # traded near the price (within the max spread)
    desk.poll(NOW + 60)
    assert set(desk.state["positions"]) == {"cheap"}


def test_positions_save_the_trade_fields(gw: Gateway2, tmp_path: Path) -> None:
    gw.markets = [_market("k1", "crypto", 1800)]
    gw.quotes = {"k1": (0.97, 0.98)}
    gw.extra = {"k1": {"lastTradePx": {"value": "0.975"}, "sharesTraded": "4321", "bidShares": "120",
                       "askShares": "80"}}
    desk = _desk(_paper(tmp_path))
    desk.poll(NOW)
    pos = desk.state["positions"]["k1"]
    assert (pos["last_in"], pos["traded_in"], pos["bid_size_in"], pos["ask_size_in"]) == (0.975, 4321.0, 120.0, 80.0)
    q = P.bbo("k1")
    assert q["state"] == "MARKET_STATE_OPEN" and q["shares_traded"] == 4321.0 and q["bid_size"] == 120.0


# ---------------------------------------------------------------- C4: no real money on any sport (history allowed none)
def test_sports_get_no_real_orders_in_live_mode(gw: Gateway2, tmp_path: Path) -> None:
    gw.events = [_event("nba-lal-bos-2026-10-10", -3600, "Q4")]  # a traded, in-play winner market at 0.97/0.98
    gw.quotes = {"nba-lal-bos-2026-10-10-ml": (0.97, 0.98)}
    ex = FakeExchange(cash=25.0)
    settings = _live_settings(tmp_path)
    desk = _desk(settings, ex)
    desk.poll(NOW)
    assert ex.orders == [] and desk.state["mode"] == "live"
    pos = desk.state["positions"]["nba-lal-bos-2026-10-10-ml"]
    assert pos["side"] == "long" and pos["live"] is False and pos["sport"] == "basketball"
    assert _skips(settings) == {"counts": {"sports_no_real": 1}, "sports": {"basketball": 1}}
    desk.poll(NOW + 60)
    assert ex.orders == [] and _skips(settings)["counts"]["sports_no_real"] == 1  # once per market a day


def test_the_page_counts_only_the_sports_bets_really_practised(gw: Gateway2, tmp_path: Path) -> None:
    """The page says "practised N sports bets instead of betting real money": N is the practice bets made, not the
    picks. A full practice book (10 open while a rule learns) or a paused one practises nothing more, so the picks
    it could not take are not counted (they are once a slot frees and the bet is made)."""
    from nightcrawler.pagestate import _skips_line

    cap = P.PAPER_LEARNING_OPEN
    games = [f"nba-g{i:02d}-2026-10-10" for i in range(cap + 5)]  # 15 games in play, each one winner at 0.97/0.98
    gw.events = [_event(g, -3600, "Q4") for g in games]
    gw.quotes = {f"{g}-ml": (0.97, 0.98) for g in games}
    ex = FakeExchange(cash=25.0)
    settings = _live_settings(tmp_path)
    desk = _desk(settings, ex)
    desk.poll(NOW)
    assert ex.orders == [] and len(_practice(desk)) == cap
    assert _skips(settings) == {"counts": {"sports_no_real": cap}, "sports": {"basketball": cap}}
    assert _skips_line(P.panel_state(settings, NOW), live=True) == (
        f"Today it practised {cap} sports bets instead of betting real money.")
    # a paused practice book (its record is losing) practises nothing, so nothing is counted as practised
    paused = _live_settings(tmp_path / "paused")
    st = P.empty_state()
    st["by_rule"] = {P.rule_id(paused): {"paper": {"settled": 60, "won": 54, "pnl_usd": sum(LOSING),
                                                   "pnls": list(LOSING), "costs": [20.0] * 60,
                                                   "keys": [f"k{i}" for i in range(60)]}}}
    P.save_state(P.state_path(paused), st)
    gw.events, gw.quotes = [_event(games[0], -3600, "Q4")], {f"{games[0]}-ml": (0.97, 0.98)}
    other = _desk(paused, ex)
    other.poll(NOW)
    assert other.state["paused"] is not None and not other.state["positions"] and ex.orders == []
    assert "sports_no_real" not in _skips(paused)["counts"]
    assert _skips_line(P.panel_state(paused, NOW), live=True) == "Nothing skipped yet today."


def test_crypto_still_gets_a_real_order(gw: Gateway2, tmp_path: Path) -> None:
    gw.markets = [_market("btc-above", "crypto", 1800)]
    gw.quotes = {"btc-above": (0.97, 0.98)}
    ex = FakeExchange(cash=25.0)
    desk = _desk(_live_settings(tmp_path), ex)
    desk.poll(NOW)
    assert [o["slug"] for o in ex.orders] == ["btc-above"] and desk.state["positions"]["btc-above"]["live"] is True


def test_real_sports_allowed_is_empty_and_other_is_never_allowed() -> None:
    assert P.REAL_SPORTS_ALLOWED == frozenset() and "other" not in P.REAL_SPORTS_ALLOWED
    source = inspect.getsource(P)
    assert 'if "other" in REAL_SPORTS_ALLOWED:' in source and "raise AssertionError" in source  # checked at import
    assert source.count("REAL_SPORTS_ALLOWED: frozenset[str] = frozenset()") == 1  # one place, in code
    # no setting or variable can re-allow a sport
    assert not [name for name in Settings.__dataclass_fields__ if "sport" in name]
    assert "environ" not in source


def test_the_block_keys_on_the_category(gw: Gateway2, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Were a sport ever allowed (only by a code change after a pass), only that sport would get real orders; any
    other game, or one whose sport the map does not know, stays blocked because it is a sports market."""
    monkeypatch.setattr(P, "REAL_SPORTS_ALLOWED", frozenset({"soccer"}))
    gw.events = [_event("epl-ars-che-2026-10-10", -3600, "2H"), _event("nba-lal-bos-2026-10-10", -3700, "Q4"),
                 _event("zzz-x-y-2026-10-10", -3800, "2H")]
    gw.quotes = {f"{e['slug']}-ml": (0.97, 0.98) for e in gw.events}
    ex = FakeExchange(cash=25.0)
    desk = _desk(_live_settings(tmp_path), ex)
    desk.poll(NOW)
    assert [o["slug"] for o in ex.orders] == ["epl-ars-che-2026-10-10-ml"]
    assert desk.state["positions"]["zzz-x-y-2026-10-10-ml"]["sport"] == "other"
    assert not desk.state["positions"]["zzz-x-y-2026-10-10-ml"]["live"]


def _lab_sports() -> ModuleType:
    path = ROOT / "research" / "lab4" / "P6" / "sports.py"
    if not path.is_file():
        pytest.skip("research/lab4/P6/sports.py is not in this checkout")
    spec = importlib.util.spec_from_file_location("lab4_p6_sports", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sportmap_matches_the_lab_map() -> None:
    """The desk labels a game's sport exactly as lab 4's history test did (src never imports research)."""
    lab = _lab_sports()
    venue = ROOT / "research" / "lab4" / "US" / "venue_map.json"
    if not venue.is_file():
        pytest.skip("research/lab4/US/venue_map.json is not in this checkout")
    assert sportmap.SPORTS == lab.SPORTS and set(P.SPORT_HISTORY) == set(sportmap.SPORTS)
    codes = set(lab._EXACT)
    codes |= {str(row["league_code"]) for row in json.loads(venue.read_text())["by_slug_prefix"].values()
              if isinstance(row, dict) and row.get("league_code")}
    assert len(codes) > 200
    for code in sorted(codes):
        assert sportmap.sport_of(code) == lab.sport_of(code), code
        assert sportmap.sport_of(f"{code}-a-b-2026-10-10") == lab.sport_of(f"{code}-a-b-2026-10-10"), code
    for tags, want in ((["sports", "table-tennis"], "table tennis"), (["efootball"], "e-soccer"),
                       (["ice-hockey"], "hockey"), (["tennis", "atp"], "tennis")):
        assert sportmap.sport_of("pdc-x-y", tags) == lab.sport_of("pdc-x-y", tags) == want, tags
    # the desk's own reading of a market: the event slug first, else the league word of an aec-/atc- slug
    assert P._sport(None, "aec-setkameua-mukvit-konvas", []) == "table tennis"
    assert P._sport(None, "atc-ebfsa-sas-roma-2026-10-10-dh4-sas", []) == "e-soccer"
    assert P._sport("del-kec-sww-2026-10-09", "aec-del-kec-sww", []) == "hockey"
    assert P._sport(None, "plain-slug", []) == "other"


def test_sport_history_matches_p6_train() -> None:
    """Every number the desk and the page say about the history is lab 4 P6 TRAIN's own (train.json)."""
    path = ROOT / "research" / "lab4" / "P6" / "train.json"
    if not path.is_file():
        pytest.skip("research/lab4/P6/train.json is not in this checkout")
    train = json.loads(path.read_text())
    assert train["allowed"] == [] and train["decision"].startswith("NO SPORT ALLOWED on TRAIN")
    blocked = {s for s, (verdict, _) in P.SPORT_HISTORY.items()
               if verdict in ("proven loser", "no history", "too little history")}
    assert set(train["blocked"]) == blocked
    assert {s for s, (v, _) in P.SPORT_HISTORY.items() if v == "proven loser"} == P.PROVEN_LOSERS
    cell = train["cells"]["theta0.97"]

    def says(sport: str, row: dict[str, Any], *, n_word: str = "") -> None:
        why = P.SPORT_HISTORY[sport][1]
        for text in (f"{row['n']:,}{n_word}", f"{row['losses']}", f"{100 * row['loss_rate']:.1f}%",
                     f"{100 * row['implied_loss_rate']:.1f}%"):
            assert text in why, (sport, text, why)

    expect = {"tennis": (1848, 66), "soccer": (448, 10), "baseball": (515, 16), "basketball": (108, 5),
              "cricket": (140, 7), "american football": (11, 0)}
    for sport, (n, losses) in expect.items():
        row = cell["sports"][sport]
        assert (row["n"], row["losses"]) == (n, losses), sport
        if sport != "american football":
            says(sport, row)
    assert P.SPORT_HISTORY["american football"] == ("too little history", "11 games, fewer than the 30 needed")
    esports, itf = cell["sports_fallback"]["esports"], cell["leagues_fallback"]["itf"]
    assert (esports["n"], esports["losses"], itf["n"], itf["losses"]) == (821, 57, 223, 23)
    says("esports", esports)
    assert "ITF 23 of 223 (10.3% vs 4.4%)" in P.SPORT_HISTORY["tennis"][1]
    assert f"{100 * itf['loss_rate']:.1f}% vs {100 * itf['implied_loss_rate']:.1f}%" == "10.3% vs 4.4%"
    for sport in ("table tennis", "e-soccer", "hockey", "mma/boxing"):  # no judged game at all
        assert sport not in cell["sports"] and P.SPORT_HISTORY[sport][0] == "no history", sport
    pooled = cell["pooled"]
    assert (pooled["n"], pooled["losses"]) == (P.SPORT_HISTORY_POOLED["buys"], P.SPORT_HISTORY_POOLED["lost"]) == (
        3070, 104)
    assert round(pooled["loss_rate"], 3) == P.SPORT_HISTORY_POOLED["loss_rate"]
    assert round(pooled["implied_loss_rate"], 3) == P.SPORT_HISTORY_POOLED["implied"]


# ---------------------------------------------------------------- C5: practice buys what real money skips, YES only
def test_live_mode_paper_buys_what_real_money_skips(gw: Gateway2, tmp_path: Path) -> None:
    gw.markets = [_market("btc", "crypto", 1800)]
    gw.events = [_event("nba-lal-bos-2026-10-10", -3600, "Q4")]
    gw.quotes = {"btc": (0.97, 0.98), "nba-lal-bos-2026-10-10-ml": (0.97, 0.98)}
    ex = FakeExchange(cash=25.0)
    desk = _desk(_live_settings(tmp_path), ex)
    desk.poll(NOW)
    assert [o["slug"] for o in ex.orders] == ["btc"]
    assert set(_real(desk)) == {"btc"} and set(_practice(desk)) == {"nba-lal-bos-2026-10-10-ml"}
    assert not set(_real(desk)) & set(_practice(desk))  # one market, one book


def test_live_mode_daily_stop_still_lets_paper_watch(gw: Gateway2, tmp_path: Path) -> None:
    settings = _live_settings(tmp_path)
    st = P.empty_state()
    st["live_days"] = {TODAY: {"pnl_usd": -3.0, "settled": 4, "won": 1}}
    st["live_pnl_total_usd"] = -3.0
    P.save_state(P.state_path(settings), st)
    gw.markets = [_market("btc", "crypto", 1800)]
    gw.quotes = {"btc": (0.97, 0.98)}
    ex = FakeExchange(cash=25.0)
    desk = _desk(settings, ex)
    desk.poll(NOW)
    assert ex.orders == [] and desk.state["positions"]["btc"]["live"] is False
    assert desk.state["live_status"] == P.DAILY_NOTE


def test_a_losing_practice_record_still_pauses_real_buys(gw: Gateway2, tmp_path: Path) -> None:
    settings = _live_settings(tmp_path)
    st = P.empty_state()
    st["by_rule"] = {P.rule_id(settings): {"paper": {"settled": 60, "won": 54, "pnl_usd": sum(LOSING),
                                                     "pnls": list(LOSING), "costs": [20.0] * 60,
                                                     "keys": [f"k{i}" for i in range(60)]}}}
    P.save_state(P.state_path(settings), st)
    gw.markets = [_market("btc", "crypto", 1800)]
    gw.quotes = {"btc": (0.97, 0.98)}
    ex = FakeExchange(cash=25.0)
    desk = _desk(settings, ex)
    desk.poll(NOW)
    assert ex.orders == [] and not desk.state["positions"] and desk.state["paused"] is not None


# ---------------------------------------------------------------- C7 / F3, F5: an order the venue has not confirmed
def test_an_unconfirmed_order_counts_against_the_open_cap_in_the_same_round(gw: Gateway2, tmp_path: Path) -> None:
    """2026-10-10 13:14: an unconfirmed fill (Bakken Bears) was not counted, the next order (Botic) passed the cap,
    and the venue then held $10.74 against a $10.00 cap."""
    gw.markets = [_market(f"m{i}", "crypto", 1800 + i) for i in range(3)]  # three ladders: the cap is the test
    gw.quotes = {f"m{i}": (0.97, 0.98) for i in range(3)}
    ex = LaggingExchange(cash=25.0)
    desk = _desk(_live_settings(tmp_path, POLYDESK_LIVE_MAX_OPEN_USD="2"), ex)
    desk.poll(NOW)
    assert ex.venue_cost() <= 2.0 + 1e-9
    assert len(ex.orders) == 1  # after an unconfirmed order no further real order goes out that round
    assert set(_practice(desk)) == {"m1", "m2"}  # ... and the rule's other picks are practised on paper
    assert _skips(desk.settings)["counts"]["waiting_unconfirmed"] == 2


def test_an_unconfirmed_fill_of_the_desks_own_order_counts_in_the_rules_record(gw: Gateway2, tmp_path: Path) -> None:
    gw.markets = [_market("k1", "crypto", 1800)]
    gw.quotes = {"k1": (0.97, 0.98)}
    ex = LaggingExchange(cash=25.0)
    ledger = FakeLedger()
    desk = _desk(_live_settings(tmp_path), ex, ledger)
    desk.poll(NOW)  # order sent, reply and positions show nothing at first
    desk.poll(NOW + 60)
    pos = desk.state["positions"]["k1"]
    assert pos["rule"] == desk.rule and pos["adopted"] is True and pos["t_in"] == NOW and pos["ask_in"] == 0.98
    assert pos["order_id"] == "o1" and not desk.state["pending_orders"]
    assert _said(desk, "REAL buy confirmed late by the venue: Will k1 happen? · 1 contract at 0.980 ($0.98, crypto)")
    assert ("polydesk_order_filled", {"slug": "k1", "order_id": "o1", "contracts": 1.0, "price": 0.98,
                                      "cost_usd": 0.98, "late": True}) in ledger.receipts
    gw.markets = []
    gw.settlements = {"k1": 1.0}
    desk.poll(NOW + 2000)
    assert desk.state["by_rule"][desk.rule]["real"]["settled"] == 1 and "venue" not in desk.state["by_rule"]


def test_the_end_of_round_venue_check_runs_after_an_unconfirmed_order(gw: Gateway2, tmp_path: Path) -> None:
    gw.markets = [_market("k1", "crypto", 1800)]
    gw.quotes = {"k1": (0.97, 0.98)}
    ex = LaggingExchange(cash=25.0)
    desk = _desk(_live_settings(tmp_path), ex)
    r = desk.poll(NOW)
    assert r["bought"] == 0 and r["adopted"] == 1  # found by the end-of-round read of the same round
    assert desk.state["positions"]["k1"]["live"] and desk.state["exchange"]["contracts"] == 1.0
    assert ex.position_reads == 3  # start of round, the reply check, and the end-of-round read


def test_a_pending_order_is_dropped_after_quiet_venue_reads(gw: Gateway2, tmp_path: Path) -> None:
    gw.markets = [_market("k1", "crypto", 1800)]
    gw.quotes = {"k1": (0.97, 0.98)}
    ex = SilentExchange(cash=25.0)
    settings = _live_settings(tmp_path)
    desk = _desk(settings, ex)
    desk.poll(NOW)
    assert set(desk.state["pending_orders"]) == {"k1"} and not desk.state["positions"]
    assert _said(desk, "Order not confirmed yet at 0.980: Will k1 happen? (counted as open money until the venue "
                       "shows it)")
    desk.poll(NOW + 120)  # too soon to call it: still counted as open money
    real = P.panel_state(settings, NOW + 120)["real"]
    assert (real["pending"], real["pending_usd"]) == (1, pytest.approx(0.98))
    desk.poll(NOW + 400)
    assert not desk.state["pending_orders"] and not desk.state["positions"] and len(ex.orders) == 1
    assert [e["text"] for e in _said(desk, "No fill at")] == ["No fill at 0.980: Will k1 happen? (order cancelled)"]


def test_a_pending_order_expires_after_a_day(gw: Gateway2, tmp_path: Path) -> None:
    gw.markets = [_market("k1", "crypto", 1800)]
    gw.quotes = {"k1": (0.97, 0.98)}
    ex = SilentExchange(cash=25.0)
    desk = _desk(_live_settings(tmp_path), ex)
    desk.poll(NOW)
    assert set(desk.state["pending_orders"]) == {"k1"}
    ex.fail_positions = True  # the venue's book cannot be read any more
    gw.markets = []
    desk.poll(NOW + 3600)
    assert set(desk.state["pending_orders"]) == {"k1"}  # no good read: still counted
    desk.poll(NOW + P.PENDING_MAX_S + 1)
    assert not desk.state["pending_orders"] and len(_said(desk, "No fill at 0.980: Will k1 happen?")) == 1


def test_contracts_the_desk_never_ordered_stay_venue(gw: Gateway2, tmp_path: Path) -> None:
    gw.markets = [_market("k1", "crypto", 1800)]
    gw.quotes = {"k1": (0.97, 0.98)}
    ex = LaggingExchange(cash=25.0)
    ex.hold("elsewhere", 1.0, 0.95, title="Bought in the app", outcome="Yes")
    desk = _desk(_live_settings(tmp_path), ex)
    desk.poll(NOW)
    pos = desk.state["positions"]
    assert pos["elsewhere"]["rule"] == "venue" and "ask_in" not in pos["elsewhere"]
    assert pos["k1"]["rule"] == desk.rule  # the desk's own order, confirmed late
    assert _said(desk, "REAL position found at the venue: Bought in the app · Yes")


def test_a_settled_market_is_never_adopted_twice(gw: Gateway2, tmp_path: Path) -> None:
    """The venue may still list a contract after the desk booked its result (F17): it is not a second bet."""
    gw.markets = [_market("k1", "crypto", 1800)]
    gw.quotes = {"k1": (0.97, 0.98)}
    ex = FakeExchange(cash=25.0)  # its book keeps every contract it ever filled, settled or not
    desk = _desk(_live_settings(tmp_path), ex)
    desk.poll(NOW)
    gw.markets = []
    gw.settlements = {"k1": 1.0}
    desk.poll(NOW + 2000)
    assert "k1" not in desk.state["positions"] and desk.state["closed"][0]["slug"] == "k1"
    desk.poll(NOW + 2100)
    assert "k1" not in desk.state["positions"] and desk.state["counters"]["bought"] == 1
    assert not _said(desk, "REAL position found")
    day = desk.state["live_days"][TODAY]
    assert day["settled"] == 1


# ---------------------------------------------------------------- C8 / F4: the loss stops count money still at risk
def test_the_daily_stop_counts_money_still_at_risk(gw: Gateway2, tmp_path: Path) -> None:
    gw.markets = [_market(f"m{i}", "crypto", 1800 + i) for i in range(5)]  # five ladders: the stop is the test
    gw.quotes = {f"m{i}": (0.97, 0.98) for i in range(5)}
    ex = FakeExchange(cash=25.0)
    desk = _desk(_live_settings(tmp_path, POLYDESK_LIVE_DAILY_LOSS_USD="3"), ex)
    desk.poll(NOW)
    at_risk = sum(o["price"] * o["quantity"] for o in ex.orders)
    assert at_risk <= 3.0 + 1e-9 and len(ex.orders) == 3  # if every open bet loses, the day still loses <= $3
    assert _skips(desk.settings)["counts"]["stop_room"] == 2


def test_the_total_stop_counts_money_still_at_risk(gw: Gateway2, tmp_path: Path) -> None:
    st = P.empty_state()
    st["live_pnl_total_usd"] = -9.0
    settings = _live_settings(tmp_path)
    P.save_state(P.state_path(settings), st)
    gw.markets = [_market(f"m{i}", "crypto", 1800 + i) for i in range(5)]
    gw.quotes = {f"m{i}": (0.97, 0.98) for i in range(5)}
    ex = FakeExchange(cash=25.0)
    desk = _desk(settings, ex)
    desk.poll(NOW)
    assert -9.0 - sum(o["price"] * o["quantity"] for o in ex.orders) >= -10.0 - 1e-9 and len(ex.orders) == 1


def test_the_daily_stop_counts_pending_orders(gw: Gateway2, tmp_path: Path) -> None:
    settings = _live_settings(tmp_path)
    st = P.empty_state()
    st["pending_orders"] = {f"p{i}": {"rule": P.rule_id(settings), "t_in": NOW - 10, "limit": 0.98, "contracts": 1.0,
                                      "fee_coef": 0.0695, "question": f"p{i}?", "category": "crypto",
                                      "end_ts": NOW + 900 + i} for i in range(3)}
    P.save_state(P.state_path(settings), st)
    gw.markets = [_market("new", "crypto", 1800)]
    gw.quotes = {"new": (0.97, 0.98)}
    ex = FakeExchange(cash=25.0)
    desk = _desk(settings, ex)
    desk.poll(NOW)
    assert ex.orders == [] and desk.state["positions"]["new"]["live"] is False  # $2.94 unconfirmed: no room
    assert set(desk.state["pending_orders"]) == {"p0", "p1", "p2"}  # a read 10 s after: too soon to drop them
    room = P.real_room(desk.state, settings, NOW)
    assert room["open_room"] == pytest.approx(10.0 - 2.94)
    assert room["day_room"] == pytest.approx(3.0 - 3 * 0.98 * (1 + 0.0695 * 0.02))


def test_real_room_matches_live_allows(tmp_path: Path) -> None:
    settings = _live_settings(tmp_path)
    desk = _desk(settings)
    st = desk.state
    common = {"side": "long", "p_in": 0.97, "t_in": NOW, "category": "crypto", "end_ts": NOW + 60}
    st["positions"] = {"a": {**common, "slug": "a", "question": "a?", "live": True, "cost_usd": 0.97, "fee_usd": 0.002},
                       "paper": {**common, "slug": "paper", "question": "p?", "live": False, "cost_usd": 20.0,
                                 "fee_usd": 0.3}}
    st["pending_orders"] = {"b": {"limit": 0.98, "contracts": 1.0, "fee_coef": 0.0695, "t_in": NOW}}
    for day_pnl, total in ((0.0, 0.0), (-1.0, -1.0), (-1.05, -2.0), (-1.06, -7.0), (-2.9, -8.0), (-3.0, -3.0)):
        st["live_days"] = {TODAY: {"pnl_usd": day_pnl, "settled": 1, "won": 0}}
        st["live_pnl_total_usd"] = total
        room = P.real_room(st, settings, NOW)
        held = 0.97 + 0.98
        at_risk = 0.97 + 0.002 + 0.98 * (1 + 0.0695 * 0.02)
        assert room["open_room"] == pytest.approx(10.0 - held)  # paper tickets are never real money
        assert room["day_room"] == pytest.approx(3.0 + day_pnl - at_risk)
        assert room["total_room"] == pytest.approx(10.0 + total - at_risk)
        for price in (0.97, 0.98, 0.99):
            risk = price * (1 + 0.0695 * (1 - price))
            want = price <= room["open_room"] and day_pnl > -3.0 and risk <= room["day_room"] and \
                risk <= room["total_room"]
            assert desk._live_allows(NOW, price, 0.0695) is want, (day_pnl, total, price)
    P.save_state(desk.path, st)
    real = P.panel_state(settings, NOW)["real"]
    room = P.real_room(st, settings, NOW)
    assert real["stop_room_usd"] == pytest.approx(min(room["day_room"], room["total_room"]))


# ---------------------------------------------------------------- C9 / F11: a failed venue read means no real orders
def test_no_real_buys_when_the_venue_book_cannot_be_read(gw: Gateway2, tmp_path: Path) -> None:
    """The pre-buy venue check fails: last round's unconfirmed fills are unknown, so the caps cannot be trusted."""
    gw.markets = [_market("m0", "crypto", 1800)]
    gw.quotes = {"m0": (0.97, 0.98)}
    ex = LaggingExchange(cash=25.0)
    settings = _live_settings(tmp_path)
    desk = _desk(settings, ex)
    ex.fail_positions = True
    desk.poll(NOW)
    assert ex.orders == [] and desk.state["positions"]["m0"]["live"] is False  # practised instead
    assert _skips(settings)["counts"] == {"venue_unread": 1}
    ex.fail_positions = False
    gw.markets = [_market("m1", "crypto", 1900)]
    gw.quotes = {"m1": (0.97, 0.98)}
    desk.poll(NOW + 60)  # a good read: real orders again
    assert [o["slug"] for o in ex.orders] == ["m1"]


# ---------------------------------------------------------------- C10 / F6: a quote ~20 s old is not the book at order time
def test_a_real_order_rechecks_the_quote_first(gw: Gateway2, tmp_path: Path) -> None:
    gw.markets = [_market("q1", "crypto", 1800)]
    gw.quotes = {"q1": (0.97, 0.98)}
    gw.fresh = {"q1": (0.90, 0.93)}  # the market fell between the round's quote and the order
    ex = FakeExchange(cash=25.0)
    settings = _live_settings(tmp_path)
    desk = _desk(settings, ex)
    desk.poll(NOW)
    assert ex.orders == [] and not desk.state["positions"]  # no paper twin of a price that moved
    assert "q1" not in desk.state["tried"] and _skips(settings)["counts"] == {"price_moved": 1}


def test_the_fresh_ask_is_the_limit(gw: Gateway2, tmp_path: Path) -> None:
    gw.markets = [_market("q1", "crypto", 1800)]
    gw.quotes = {"q1": (0.96, 0.97)}
    gw.fresh = {"q1": (0.97, 0.98)}
    ex = FakeExchange(cash=25.0)
    desk = _desk(_live_settings(tmp_path), ex)
    desk.poll(NOW)
    assert ex.orders == [{"slug": "q1", "price": 0.98, "quantity": 1.0}]
    pos = desk.state["positions"]["q1"]
    assert (pos["bid_in"], pos["ask_in"], pos["p_in"]) == (0.97, 0.98, 0.98)  # the book the order was placed on


def test_a_failed_fresh_read_sends_nothing(gw: Gateway2, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gw.markets = [_market("q1", "crypto", 1800)]
    gw.quotes = {"q1": (0.97, 0.98)}
    ex = FakeExchange(cash=25.0)
    desk = _desk(_live_settings(tmp_path), ex)
    calls = {"n": 0}
    real_bbo = P.bbo

    def flaky(slug: str) -> dict[str, Any]:
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("GET bbo failed")
        return real_bbo(slug)

    monkeypatch.setattr(P, "bbo", flaky)
    desk.poll(NOW)
    assert ex.orders == [] and not desk.state["positions"] and "q1" not in desk.state["tried"]


# ---------------------------------------------------------------- C11 / F7: the venue says which games are in play
def test_ended_and_postponed_games_are_not_in_play(gw: Gateway2) -> None:
    """2026-10-10 18:4x UTC listing: 'VFT' (ended, live false) and 'POST' (postponed, live false) passed the desk's
    deny-list of periods."""
    gw.events = [_three_way("epl-mnu-tot", "Man Utd vs. Spurs", -8000, "VFT", ("mnu", "draw", "tot"), live=False,
                            ended=True),
                 _three_way("vtb-mba-eni", "MBA vs. Enisey", -3000, "POST", ("mba", "draw", "eni"), live=False,
                            ended=False),
                 _three_way("lal-ray-ath", "Rayo vs. Athletic", -5000, "2H", ("ray", "draw", "ath"), live=True,
                            ended=False),
                 _three_way("lal-x-y", "Listed live, says ended", -5000, "2H", ("x", "draw", "y"), live=True,
                            ended=True),
                 _three_way("lal-p-q", "No live flag", -5000, "2H", ("p", "draw", "q"), live=None)]
    got = {m["slug"].rsplit("-", 1)[0] for m in P.live_sports_markets(NOW)}
    assert got == {"atc-lal-ray-ath"}
    assert {"VFT", "POST"} <= P.NOT_LIVE_PERIODS  # the second check


def test_positions_save_period_and_score(gw: Gateway2, tmp_path: Path) -> None:
    gw.events = [_three_way(*RAYO, score="1-0", elapsed="63'", tags=[{"slug": "soccer"}, {"slug": "la-liga"}])]
    gw.quotes = dict(LEADER)
    desk = _desk(_paper(tmp_path))
    desk.poll(NOW)
    pos = desk.state["positions"]["atc-lal-ray-ath-ray"]
    assert (pos["period"], pos["score"], pos["elapsed"], pos["game_start"]) == ("2H", "1-0", "63'", NOW - 5000)
    assert pos["sport"] == "soccer" and pos["event"] == "Rayo vs. Athletic"
    (rec,) = [m for m in P.live_sports_markets(NOW) if m["slug"] == "atc-lal-ray-ath-ray"]
    assert rec["tags"] == ["soccer", "la-liga"] and rec["event_slug"] == "lal-ray-ath" and rec["n_outcomes"] == 3


# ---------------------------------------------------------------- C12 / F10: book a finished market as soon as it closes
def test_a_closed_market_still_on_the_live_list_is_settled_this_round(gw: Gateway2, tmp_path: Path) -> None:
    """14 ITF matches were booked ~64 min after the venue settled them (the games stayed on the live list). With no
    real money on sports, the bet is a practice one; it is still booked the same round."""
    gw.events = [_three_way("itf-a-b", "A vs. B", -5000, "S2", ("a", "draw", "b"))]
    gw.quotes = {"atc-itf-a-b-a": (0.97, 0.98), "atc-itf-a-b-draw": (0.01, 0.02), "atc-itf-a-b-b": (0.01, 0.02)}
    ex = FakeExchange(cash=25.0)
    desk = _desk(_live_settings(tmp_path), ex)
    desk.poll(NOW)
    assert desk.state["positions"]["atc-itf-a-b-a"]["live"] is False and ex.orders == []
    gw.extra = {s: {"state": "MARKET_STATE_CLOSED"} for s in gw.quotes}
    gw.quotes = {s: (None, None) for s in gw.quotes}
    gw.settlements = {"atc-itf-a-b-a": 1.0}
    desk.poll(NOW + 600)  # still listed as live, but the market is closed and settled
    assert "atc-itf-a-b-a" not in desk.state["positions"] and desk.state["closed"][0]["won"] is True
    assert desk.state["by_sport"][desk.rule]["tennis"]["paper"]["settled"] == 1


# ---------------------------------------------------------------- C13 / F13, F16: bookkeeping
def test_the_tried_list_drops_the_oldest_not_the_sports_slugs(gw: Gateway2, tmp_path: Path) -> None:
    settings = _live_settings(tmp_path)
    st = P.empty_state()
    st["tried"] = [f"zz-old-{i:05d}" for i in range(5000)]
    P.save_state(P.state_path(settings), st)
    gw.markets = [_market("aec-new", "crypto", 1800)]
    gw.quotes = {"aec-new": (0.97, 0.98)}
    ex = FakeExchange(cash=25.0)
    ex.reject_orders = True  # tried but not held: only the tried list stops a retry
    desk = _desk(settings, ex)
    desk.poll(NOW)
    tried = desk.state["tried"]
    assert "aec-new" in tried and tried[-1] == "aec-new" and len(tried) == P.TRIED_KEEP
    assert "zz-old-00000" not in tried and "zz-old-04999" in tried  # the oldest dropped first
    desk.poll(NOW + 60)
    assert len(ex.orders) == 1  # never ordered again


def test_the_daily_status_line_clears_the_next_day(gw: Gateway2, tmp_path: Path) -> None:
    settings = _live_settings(tmp_path)
    st = P.empty_state()
    st["live_days"] = {TODAY: {"pnl_usd": -3.1, "settled": 9, "won": 6}}
    st["live_pnl_total_usd"] = -4.885
    P.save_state(P.state_path(settings), st)
    desk = _desk(settings)
    desk.poll(NOW)
    assert desk.state["live_status"] == P.DAILY_NOTE and len(_said(desk, P.DAILY_NOTE)) == 1
    desk.poll(NOW + 86_400)  # the next UTC day: the stop no longer holds, nor does its line
    assert desk.state["live_status"] is None and desk.state["mode"] == "live"


def test_the_daily_status_line_returns_after_a_restart_while_the_stop_holds(gw: Gateway2, tmp_path: Path) -> None:
    settings = _live_settings(tmp_path)
    st = P.empty_state()
    st["live_days"] = {TODAY: {"pnl_usd": -3.1, "settled": 9, "won": 6}}
    P.save_state(P.state_path(settings), st)
    first = _desk(settings)
    first.poll(NOW)
    assert first.state["live_status"] == P.DAILY_NOTE
    again = _desk(settings)  # a restart: connecting clears the line ...
    assert again.state["live_status"] is None
    again.poll(NOW + 60)  # ... and the first round sets it again, without saying it twice
    assert again.state["live_status"] == P.DAILY_NOTE and len(_said(again, P.DAILY_NOTE)) == 1
