"""Marco's loves desk (nightcrawler.marcodesk): the picks file, the game lookup on a fake gateway, one paper buy per
loved pick at the ask, never before the data or after the cutoff, settlement, the non-moneyline picks, the page's
fields, and that it can never send a real order. No network, no keys."""

from __future__ import annotations

import inspect
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock
from test_page import no_learning_module, seed  # noqa: F401 - shared fixture

from nightcrawler import marcodesk as M
from nightcrawler import polydesk as P
from nightcrawler import polymarket_us
from nightcrawler.config import LIVE_CONFIRM_PHRASE, Settings
from nightcrawler.ledger import Ledger
from nightcrawler.pagestate import build_page_state, marco_desk, marco_line

KICK = datetime(2026, 10, 11, 17, 0, tzinfo=UTC).timestamp()  # Sunday's early NFL games
PUBLISHED = datetime(2026, 10, 8, 11, 0, tzinfo=UTC).timestamp()
NOW = KICK - 3 * 3600


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _game(away: str, home: str, code: str, kickoff: float = KICK, league: str = "nfl") -> dict[str, Any]:
    """An event as the gateway lists it with ``marketTypes=moneyline`` (read 2026-10-11): ONE moneyline market whose
    two sides are the teams, the away team the long side."""
    day = datetime.fromtimestamp(kickoff, UTC).strftime("%Y-%m-%d")
    slug = f"{league}-{code}-{day}"
    return {
        "slug": slug, "title": f"{away} vs. {home}", "startTime": _iso(kickoff), "tags": [{"slug": league}],
        "markets": [{
            "slug": f"aec-{slug}", "marketType": "moneyline", "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
            "gameStartTime": _iso(kickoff), "feeCoefficient": 0.0695, "closed": False,
            "marketSides": [
                {"description": away.split()[-1], "long": True, "team": {"name": away}},
                {"description": home.split()[-1], "long": False, "team": {"name": home}},
            ],
        }],
    }


def _spread(event_slug: str, team: str, other: str, number: float) -> dict[str, Any]:
    """A full-game spread market: the long side the other team at ``-number``, the short side ``team`` at
    ``+number`` (the venue's own layout)."""
    return {"slug": f"asc-{event_slug}-{number}", "marketType": "spreads", "closed": False,
            "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_SPREAD", "sportsMarketType": "football_team_full_game_spread",
            "line": number, "feeCoefficient": 0.0695,
            "marketSides": [{"description": f"-{number:.2f}", "long": True, "team": {"name": other}},
                            {"description": f"+{number:.2f}", "long": False, "team": {"name": team}}]}


class Gateway:
    """A fake public gateway: events (moneyline listing, or one event's spreads / totals by slug), quotes (the long
    side's book) and settlements; every path it is asked is recorded."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.extra_markets: dict[str, list[dict[str, Any]]] = {}  # event slug -> its spread / total markets
        self.quotes: dict[str, tuple[float | None, float | None]] = {}
        self.settlements: dict[str, float] = {}
        self.calls: list[str] = []

    def get(self, path: str, params: dict[str, Any] | None = None, tries: int = 3, timeout: float = 20.0) -> Any:
        params = params or {}
        self.calls.append(path)
        if path == "/events":
            assert params["categories"] == "sports" and params["closed"] == "false"
            lo, hi = P.parse_iso(params["startDateMin"]), P.parse_iso(params["startDateMax"])
            evs = [e for e in self.events if lo <= P.parse_iso(e["startTime"]) <= hi]  # type: ignore[operator]
            if params.get("slug"):
                evs = [{**e, "markets": self.extra_markets.get(e["slug"], [])} for e in evs if e["slug"] == params["slug"]]
            else:
                assert params["marketTypes"] == "moneyline"
            return {"events": evs[params["offset"]: params["offset"] + params["limit"]]}
        if path.endswith("/bbo"):
            bid, ask = self.quotes.get(path.split("/")[2], (None, None))
            return {"marketData": {"bestBid": {"value": str(bid)} if bid is not None else None,
                                   "bestAsk": {"value": str(ask)} if ask is not None else None,
                                   "state": "MARKET_STATE_OPEN"}}
        if path.endswith("/settlement"):
            slug = path.split("/")[2]
            if slug in self.settlements:
                return {"slug": slug, "settlement": self.settlements[slug]}
            raise RuntimeError("404")
        raise AssertionError(path)

    def week5(self) -> None:
        """Sunday's three games of Marco's loves (books as read 2026-10-11 05:45 UTC) and a decoy: the Packers'
        next game, a week later."""
        self.events = [_game("Chicago Bears", "Green Bay Packers", "chi-gb"),
                       _game("Minnesota Vikings", "New Orleans Saints", "min-no"),
                       _game("New York Giants", "Washington Commanders", "nyg-was"),
                       _game("Green Bay Packers", "Detroit Lions", "gb-det", kickoff=KICK + 7 * 86_400)]
        self.quotes = {"aec-nfl-chi-gb-2026-10-11": (0.5225, 0.5250), "aec-nfl-min-no-2026-10-11": (0.5575, 0.56),
                       "aec-nfl-nyg-was-2026-10-11": (0.37, 0.3725), "aec-nfl-gb-det-2026-10-18": (0.40, 0.41)}
        self.extra_markets = {"nfl-chi-gb-2026-10-11": [_spread("nfl-chi-gb-2026-10-11", "Green Bay Packers",
                                                                "Chicago Bears", 2.5)]}


@pytest.fixture
def gw(monkeypatch: pytest.MonkeyPatch) -> Gateway:
    g = Gateway()
    monkeypatch.setattr(P, "_get", g.get)
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    return g


def _desk(tmp_path: Path, data: Path | None = None, **env: str) -> M.MarcoDesk:
    return M.MarcoDesk(Settings.from_env({"DATA_DIR": str(tmp_path), **env}), data_path=data)


def _picks(desk: M.MarcoDesk) -> dict[str, dict[str, Any]]:
    """The desk's pick records by label ('Packers moneyline', 'Packers +3', ...)."""
    by_id = {p["id"]: p for ep in M.load_episodes(desk.data_path) for p in ep["picks"]}
    return {M.pick_label(by_id[pid]): rec for pid, rec in desk.state["picks"].items()}


def _data(tmp_path: Path, picks: list[dict[str, Any]], published: str = "2026-10-08T11:00:00Z") -> Path:
    path = tmp_path / "picks.json"
    path.write_text(json.dumps({"episodes": [{"id": "ep", "title": "t", "published": published,
                                              "source_url": "u", "picks": picks}]}))
    return path


ML_PACKERS = {"rank": 1, "love": True, "league": "nfl", "team": "Green Bay Packers", "opponent": "Chicago Bears",
              "kind": "moneyline", "line": "ML", "quote": "q", "game_date": "2026-10-11"}


# --------------------------------------------------------------------------- the picks file


def test_seed_file_holds_week_5_and_his_three_loves() -> None:
    eps = M.load_episodes()
    assert [e["id"] for e in eps] == ["nfl-2026-week-05"] and eps[0]["published"] == PUBLISHED
    assert eps[0]["title"] == "NFL Week 5: Sharp Plays & Public Traps!"
    assert eps[0]["source_url"] == "https://www.youtube.com/watch?v=zQMEJVDKhhk"
    picks = eps[0]["picks"]
    assert [M.pick_label(p) for p in picks] == ["Packers moneyline", "Packers +3", "Saints moneyline", "Saints +3",
                                                "Commanders moneyline", "Six-leg parlay +2300"]
    assert {p["rank"] for p in picks if p["love"]} == {1, 2, 3} and not picks[-1]["love"]
    assert all(p["game_date"] == "2026-10-11" and p["league"] == "nfl" for p in picks)
    assert [M.followed(p) for p in picks] == [True, True, True, True, True, False]
    assert [M.first_status(p) for p in picks] == ["waiting", M.NOT_LISTED, "waiting", M.NOT_LISTED, "waiting",
                                                  M.NOT_LISTED]


def test_malformed_picks_are_left_out_never_guessed(tmp_path: Path) -> None:
    path = _data(tmp_path, [ML_PACKERS, {**ML_PACKERS, "kind": "teaser"}, {**ML_PACKERS, "game_date": "Sunday"},
                            {**ML_PACKERS, "team": ""}, {**ML_PACKERS, "rank": True}, "junk"])
    assert len(M.load_episodes(path)[0]["picks"]) == 1
    (tmp_path / "bad.json").write_text("{not json")
    assert M.load_episodes(tmp_path / "bad.json") == [] and M.load_episodes(tmp_path / "missing.json") == []
    assert M.pick_line({"kind": "total", "line": "u51"}) == ("under", 51.0)
    assert M.pick_line({"kind": "total", "line": "o48.5"}) == ("over", 48.5)
    assert M.pick_line({"kind": "spread", "line": "+3"}) == ("spread", 3.0)
    assert M.pick_line({"kind": "spread", "line": "three"}) is None


# --------------------------------------------------------------------------- buying


def test_finds_each_loved_teams_game_and_buys_it_once_at_the_ask(gw: Gateway, tmp_path: Path) -> None:
    gw.week5()
    desk = _desk(tmp_path)
    out = desk.poll(NOW)
    assert out["bought"] == 3
    recs = _picks(desk)
    pk, sa, wa = recs["Packers moneyline"], recs["Saints moneyline"], recs["Commanders moneyline"]
    # the Packers are the home (short) side of CHI-GB: their ask is 1 - the Bears' bid; the decoy (a week later) is
    # never taken
    assert pk["position"]["slug"] == "aec-nfl-chi-gb-2026-10-11" and pk["position"]["long"] is False
    assert pk["position"]["price"] == pytest.approx(0.4775) and pk["status"] == "bought"
    assert sa["position"]["price"] == pytest.approx(0.4425) and wa["position"]["price"] == pytest.approx(0.63)
    shares = 20.0 / 0.4775
    assert pk["position"]["shares"] == pytest.approx(shares) and pk["position"]["cost_usd"] == 20.0
    assert pk["position"]["fee_usd"] == pytest.approx(0.0695 * shares * 0.4775 * 0.5225)
    assert pk["game"]["kickoff"] == KICK and pk["game"]["event_slug"] == "nfl-chi-gb-2026-10-11"
    # spreads: the venue lists half points only (+2.5 here), so '+3' is not there: shown, never bought
    assert recs["Packers +3"]["status"] == M.NOT_LISTED and recs["Packers +3"]["position"] is None
    assert recs["Saints +3"]["status"] == M.NOT_LISTED
    assert recs["Six-leg parlay +2300"]["status"] == M.NOT_LISTED and recs["Six-leg parlay +2300"]["game"] is None
    assert desk.state["events"][-1]["text"].startswith("Marco desk bought Packers moneyline at 0.48 (practice")
    # once: the next rounds buy nothing again and quote nothing already bought
    calls = len(gw.calls)
    assert desk.poll(NOW + 600)["bought"] == 0 and desk.poll(NOW + 3600)["bought"] == 0
    assert not [c for c in gw.calls[calls:] if c.endswith("/bbo")]
    assert desk.state["counters"]["bought"] == 3
    # the state file is written and read back whole
    assert M.load_state(M.state_path(desk.settings))["picks"] == json.loads(json.dumps(desk.state["picks"]))


def test_an_exact_spread_line_on_the_venue_is_bought(gw: Gateway, tmp_path: Path) -> None:
    gw.week5()
    gw.extra_markets["nfl-chi-gb-2026-10-11"].append(
        _spread("nfl-chi-gb-2026-10-11", "Green Bay Packers", "Chicago Bears", 3.0))
    gw.quotes["asc-nfl-chi-gb-2026-10-11-3.0"] = (0.40, 0.42)
    desk = _desk(tmp_path)
    desk.poll(NOW)
    rec = _picks(desk)["Packers +3"]
    assert rec["status"] == "bought" and rec["position"]["slug"] == "asc-nfl-chi-gb-2026-10-11-3.0"
    assert rec["position"]["long"] is False and rec["position"]["price"] == pytest.approx(0.60)


def test_never_before_the_data(gw: Gateway, tmp_path: Path) -> None:
    gw.week5()
    desk = _desk(tmp_path)
    assert desk.poll(PUBLISHED - 3600)["bought"] == 0 and gw.calls == []  # the episode is not out yet
    assert all(rec["position"] is None for rec in desk.state["picks"].values())
    assert desk.poll(PUBLISHED + 60)["bought"] == 3  # out: bought (the games are three days away)


def test_never_after_the_cutoff(gw: Gateway, tmp_path: Path) -> None:
    gw.week5()
    late = _desk(tmp_path / "late")
    assert late.poll(KICK + 31 * 60)["bought"] == 0  # found only after kickoff + 30 min: no market
    assert _picks(late)["Packers moneyline"]["status"] == M.NO_MARKET
    under_way = _desk(tmp_path / "under_way")
    assert under_way.poll(KICK + 15 * 60)["bought"] == 0  # the game is under way: too late to copy him
    assert _picks(under_way)["Packers moneyline"]["status"] == "waiting"
    assert under_way.poll(KICK + 31 * 60)["bought"] == 0
    assert _picks(under_way)["Packers moneyline"]["status"] == M.MISSED
    calls = len(gw.calls)
    under_way.poll(KICK + 3600)
    assert not [c for c in gw.calls[calls:] if c.endswith("/bbo")]  # a closed pick is never quoted again
    first_minutes = _desk(tmp_path / "first_minutes")
    assert first_minutes.poll(KICK + 5 * 60)["bought"] == 3  # the game's first minutes still count


def test_a_game_never_listed_is_no_market(gw: Gateway, tmp_path: Path) -> None:
    desk = _desk(tmp_path)
    desk.poll(NOW)
    assert _picks(desk)["Packers moneyline"]["status"] == "waiting" and gw.calls.count("/events") == 1
    desk.poll(NOW + 60)  # the date's listing is read again only after DISCOVER_S
    assert gw.calls.count("/events") == 1
    desk.poll(NOW + M.DISCOVER_S)
    assert gw.calls.count("/events") == 2
    desk.poll(datetime(2026, 10, 12, 4, 31, tzinfo=UTC).timestamp())  # past the date's latest kickoff + 30 min
    recs = _picks(desk)
    assert recs["Packers moneyline"]["status"] == M.NO_MARKET and recs["Packers +3"]["status"] == M.NOT_LISTED
    assert desk.state["record"]["picks"] == 0


def test_no_price_before_the_cutoff_is_missed(gw: Gateway, tmp_path: Path) -> None:
    gw.week5()
    gw.quotes["aec-nfl-chi-gb-2026-10-11"] = (None, None)  # an empty book: no price for either side
    desk = _desk(tmp_path)
    assert desk.poll(NOW)["bought"] == 2
    desk.poll(KICK + 31 * 60)
    assert _picks(desk)["Packers moneyline"]["status"] == M.MISSED


# --------------------------------------------------------------------------- settling


def test_settles_won_lost_and_even_at_the_venues_price(gw: Gateway, tmp_path: Path) -> None:
    gw.week5()
    desk = _desk(tmp_path)
    desk.poll(NOW)
    gw.settlements = {"aec-nfl-chi-gb-2026-10-11": 0.0,  # the Bears (long) lost: the Packers won
                      "aec-nfl-min-no-2026-10-11": 1.0,  # the Vikings won: the Saints lost
                      "aec-nfl-nyg-was-2026-10-11": 0.5}  # a tie: half a dollar back
    assert desk.poll(KICK + 3600)["settled"] == 0 and not [c for c in gw.calls if c.endswith("/settlement")]
    assert desk.poll(KICK + 3 * 3600)["settled"] == 3
    recs = _picks(desk)
    pk, sa, wa = (recs[k] for k in ("Packers moneyline", "Saints moneyline", "Commanders moneyline"))
    assert (pk["status"], sa["status"], wa["status"]) == ("won", "lost", "even")
    win = 20.0 / 0.4775 - pk["position"]["fee_usd"] - 20.0
    assert pk["result"]["pnl_usd"] == pytest.approx(win) and sa["result"]["pnl_usd"] == pytest.approx(
        -20.0 - sa["position"]["fee_usd"])
    tie = 20.0 / 0.63 * 0.5 - wa["position"]["fee_usd"] - 20.0
    rec = desk.state["record"]
    assert (rec["picks"], rec["won"], rec["lost"], rec["even"]) == (3, 1, 1, 1)
    assert rec["pnl_usd"] == pytest.approx(win + sa["result"]["pnl_usd"] + tie)
    assert desk.poll(KICK + 4 * 3600)["settled"] == 0 and desk.state["record"]["picks"] == 3  # booked once


def test_an_unsettled_market_is_tried_again_later(gw: Gateway, tmp_path: Path) -> None:
    gw.week5()
    desk = _desk(tmp_path)
    desk.poll(NOW)
    assert desk.poll(KICK + 3 * 3600)["settled"] == 0  # the venue has not settled yet (404)
    tried = len([c for c in gw.calls if c.endswith("/settlement")])
    desk.poll(KICK + 3 * 3600 + 60)  # not again within SETTLE_EVERY_S
    assert len([c for c in gw.calls if c.endswith("/settlement")]) == tried
    gw.settlements["aec-nfl-chi-gb-2026-10-11"] = 0.0
    assert desk.poll(KICK + 3 * 3600 + M.SETTLE_EVERY_S)["settled"] == 1


def test_a_junk_state_file_never_stops_the_desk(gw: Gateway, tmp_path: Path) -> None:
    gw.week5()
    settings = Settings.from_env({"DATA_DIR": str(tmp_path)})
    junk = {"version": M.STATE_VERSION, "picks": {"nfl-2026-week-05|1|moneyline|green bay packers": "junk", "x": 3},
            "record": {"won": 2}, "events": "junk", "counters": None}
    P.save_state(M.state_path(settings), junk)
    desk = M.MarcoDesk(settings)
    assert desk.poll(NOW)["bought"] == 3 and desk.state["record"] == M.empty_state()["record"] | {"won": 2}


# --------------------------------------------------------------------------- paper only


def test_never_sends_a_real_order_even_when_the_polymarket_desk_is_live(gw: Gateway, tmp_path: Path,
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **k: Any) -> Any:
        raise AssertionError("a real-money call from the loves desk")

    monkeypatch.setattr(polymarket_us.PolymarketUSClient, "__init__", boom)
    monkeypatch.setattr(polymarket_us.PolymarketUSClient, "buy_long_ioc", boom)
    gw.week5()
    desk = _desk(tmp_path, POLYDESK_MODE="live", POLYDESK_LIVE_CONFIRM=LIVE_CONFIRM_PHRASE,
                 POLYMARKET_US_KEY_ID="key", POLYMARKET_US_SECRET_KEY="c2VjcmV0")
    assert desk.settings.polydesk_mode == "live"
    assert desk.poll(NOW)["bought"] == 3  # bought on paper all the same
    assert not hasattr(desk, "client") and not hasattr(desk, "reader")
    source = inspect.getsource(M)
    assert "polymarket_us" not in source and "buy_long_ioc" not in source and "PolymarketUSClient" not in source


# --------------------------------------------------------------------------- the page


def test_page_fields_and_the_plain_line(gw: Gateway, tmp_path: Path) -> None:
    gw.week5()
    desk = _desk(tmp_path)
    settings = desk.settings
    before = marco_desk(settings, NOW)
    assert before is not None and before["as_of"] is None and before["record"]["picks"] == 0
    assert [r["status"] for r in before["picks"]] == ["waiting", M.NOT_LISTED, "waiting", M.NOT_LISTED, "waiting",
                                                      M.NOT_LISTED]
    assert marco_line(before) == ("Marco's loves (practice, pretend money): 3 picks this week; nothing bought yet; "
                                  "no results yet.")
    desk.poll(NOW)
    gw.settlements = {"aec-nfl-chi-gb-2026-10-11": 0.0, "aec-nfl-min-no-2026-10-11": 1.0,
                      "aec-nfl-nyg-was-2026-10-11": 0.0}
    desk.poll(KICK + 3 * 3600)
    page = marco_desk(settings, KICK + 3 * 3600)
    assert page is not None
    assert page["mode"] == "paper" and page["label"] == "Practice (pretend money)" and page["loves"] == 3
    assert page["episode"]["title"] == "NFL Week 5: Sharp Plays & Public Traps!" and page["ticket_usd"] == 20.0
    rows = {r["label"]: r for r in page["picks"]}
    assert rows["Packers moneyline"]["status"] == "won" and rows["Packers moneyline"]["price"] == pytest.approx(0.4775)
    assert rows["Packers moneyline"]["quote"] == "my favorite game of the week ... I'm hammering it"
    assert rows["Packers +3"]["price"] is None and rows["Six-leg parlay +2300"]["love"] is False
    rec = page["record"]
    assert (rec["picks"], rec["won"], rec["lost"], rec["even"]) == (3, 2, 1, 0)
    pnl = desk.state["record"]["pnl_usd"]
    assert rec["pnl_usd"] == pytest.approx(pnl)
    sign = "+" if pnl > 0 else "−"
    assert marco_line(page) == (
        "Marco's loves (practice, pretend money): 3 picks this week; Packers moneyline bought at 0.48, Saints "
        f"moneyline bought at 0.44, Commanders moneyline bought at 0.63; record 2-1, {sign}${abs(pnl):,.2f}.")


def test_page_shows_nothing_for_junk_or_a_desk_that_is_off(tmp_path: Path) -> None:
    settings = Settings.from_env({"DATA_DIR": str(tmp_path)})
    path = M.state_path(settings)
    P.save_state(path, {**M.empty_state(), "record": {"picks": "three", "won": 0, "lost": 0, "even": 0,
                                                      "pnl_usd": 0.0}})
    assert marco_desk(settings, NOW) is None and marco_line(None) is None
    P.save_state(path, {**M.empty_state(), "picks": {"x": "junk"}})
    page = marco_desk(settings, NOW)
    assert page is not None and len(page["picks"]) == 6  # junk records fall back to each pick's first status
    off = Settings.from_env({"DATA_DIR": str(tmp_path), "POLYDESK_ENABLED": "false"})
    assert marco_desk(off, NOW) is None


@pytest.fixture
def ledger(tmp_path: Path, fake_clock: FakeClock) -> Iterator[Ledger]:
    with Ledger(tmp_path / "nc.db", clock=fake_clock) as led:
        yield led


def test_api_page_carries_money_marco_and_plain_marco_line(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    page = build_page_state(ledger, settings, NOW)
    assert page["money"]["marco"]["label"] == "Practice (pretend money)" and page["money"]["marco"]["loves"] == 3
    assert page["plain"]["marco_line"].startswith("Marco's loves (practice, pretend money): 3 picks this week")
