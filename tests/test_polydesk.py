"""The Polymarket desk (nightcrawler.polydesk): watch list from a fake gateway, the candidate rule's paper buys
(long and short), settlement bookkeeping, the state file, and the team-room panel. No network, no keys."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from nightcrawler import polydesk as P
from nightcrawler.config import Settings

NOW = 1_791_560_000.0


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _market(slug: str, cat: str, end_offset_s: float) -> dict[str, Any]:
    return {
        "slug": slug,
        "question": f"Will {slug} happen?",
        "category": cat,
        "closed": False,
        "endDate": _iso(NOW + end_offset_s),
        "feeCoefficient": "0.0695",
    }


def _event(slug: str, start_offset_s: float, period: str) -> dict[str, Any]:
    return {
        "slug": slug,
        "title": f"{slug} game",
        "startTime": _iso(NOW + start_offset_s),
        "period": period,
        "markets": [
            {
                "slug": f"{slug}-ml",
                "question": f"{slug} wins",
                "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
                "closed": False,
                "feeCoefficient": "0.0695",
            },
            {
                "slug": f"{slug}-spread",
                "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_SPREAD",
                "closed": False,
            },
        ],
    }


class Gateway:
    """A fake gateway: markets per category, live events, quotes and settlements, all mutable by the test."""

    def __init__(self) -> None:
        self.markets: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.quotes: dict[str, tuple[float | None, float | None]] = {}
        self.settlements: dict[str, float] = {}
        self.calls = 0

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        tries: int = 3,
        timeout: float = 20.0,
    ) -> Any:
        self.calls += 1
        params = params or {}
        if path == "/markets":
            ms = [m for m in self.markets if m["category"] == params["categories"]]
            return {
                "markets": ms[params["offset"] : params["offset"] + params["limit"]]
            }
        if path == "/events":
            return {
                "events": self.events[
                    params["offset"] : params["offset"] + params["limit"]
                ]
            }
        if path.endswith("/bbo"):
            slug = path.split("/")[2]
            bid, ask = self.quotes.get(slug, (None, None))
            return {
                "marketData": {
                    "bestBid": {"value": str(bid)} if bid is not None else None,
                    "bestAsk": {"value": str(ask)} if ask is not None else None,
                }
            }
        if path.endswith("/settlement"):
            slug = path.split("/")[2]
            if slug in self.settlements:
                return {"slug": slug, "settlement": self.settlements[slug]}
            raise RuntimeError("404")
        raise AssertionError(path)


@pytest.fixture
def gw(monkeypatch: pytest.MonkeyPatch) -> Gateway:
    g = Gateway()
    monkeypatch.setattr(P, "_get", g.get)
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    return g


def _desk(tmp_path, **env: str) -> P.PolyDesk:
    settings = Settings.from_env({"DATA_DIR": str(tmp_path), **env})
    return P.PolyDesk(settings)


def test_settings_defaults_and_validation(tmp_path) -> None:
    s = Settings.from_env({"DATA_DIR": str(tmp_path)})
    assert (
        s.polydesk_enabled
        and s.polydesk_theta == 0.97
        and s.polydesk_hours == 1.0
        and s.polydesk_ticket_usd == 20.0
    )
    with pytest.raises(Exception):
        Settings.from_env({"DATA_DIR": str(tmp_path), "POLYDESK_THETA": "1.5"})


def test_watch_list_non_sports_and_live_games(gw: Gateway) -> None:
    gw.markets = [
        _market("w1", "climate", 3600),
        _market("far", "crypto", 100 * 3600),
        _market("old", "politics", -2 * 3600),
        _market("c1", "crypto", 20 * 3600),
        _market("s0", "sports", 3600),
    ]
    gw.events = [
        _event("live1", -3600, "2H"),
        _event("soon", 1800, "NS"),
        _event("done", -4 * 3600, "FT"),
    ]
    non = P.open_markets(NOW)
    assert [m["slug"] for m in non] == ["w1", "c1"] and non[0]["fee_coef"] == 0.0695
    live = P.live_sports_markets(NOW)
    assert (
        [m["slug"] for m in live] == ["live1-ml"]
        and live[0]["category"] == "sports"
        and live[0]["period"] == "2H"
    )


def test_rule_buys_long_and_short_then_settles(gw: Gateway, tmp_path) -> None:
    gw.markets = [
        _market("w1", "climate", 1800),
        _market("c1", "crypto", 1800),
        _market("n1", "crypto", 1800),
        _market("later", "crypto", 5 * 3600),
    ]
    gw.events = [_event("g1", -3600, "2H")]
    gw.quotes = {
        "w1": (0.96, 0.975),
        "c1": (0.02, 0.05),
        "n1": (0.50, 0.52),
        "later": (0.98, 0.99),
        "g1-ml": (0.97, 0.98),
    }
    desk = _desk(tmp_path)
    r = desk.poll(NOW)
    assert r["watched"] == 5 and r["bought"] == 3 and r["settled"] == 0
    pos = desk.state["positions"]
    assert set(pos) == {
        "w1",
        "c1",
        "g1-ml",
    }  # 'later' is outside the 1 h window, 'n1' never near-certain
    assert pos["w1"]["side"] == "long" and pos["w1"]["p_in"] == 0.975
    assert pos["c1"]["side"] == "short" and abs(pos["c1"]["p_in"] - 0.98) < 1e-9
    fee = pos["w1"]["fee_usd"]
    assert abs(fee - (20 / 0.975) * 0.0695 * 0.975 * 0.025) < 1e-9
    assert desk.state["events"][0]["text"].startswith("Paper buy:")
    # the state file is written and reloads
    reloaded = P.load_state(desk.path)
    assert (
        set(reloaded["positions"]) == {"w1", "c1", "g1-ml"}
        and reloaded["counters"]["bought"] == 3
    )
    # an hour later: w1 and c1 ended, the game left the live list; settle w1 long at 1 (win), c1 short at 0 (win),
    # g1 long at 0 (loss)
    gw.markets = [_market("later", "crypto", 5 * 3600 - 3700)]
    gw.events = []
    gw.settlements = {"w1": 1.0, "c1": 0.0, "g1-ml": 0.0}
    r2 = desk.poll(NOW + 3700)
    assert r2["settled"] == 3 and not desk.state["positions"]
    closed = {c["slug"]: c for c in desk.state["closed"]}
    assert closed["w1"]["won"] and closed["c1"]["won"] and not closed["g1-ml"]["won"]
    assert (
        abs(closed["w1"]["pnl_usd"] - ((20 / 0.975) - fee - 20)) < 1e-9
        and closed["g1-ml"]["pnl_usd"] < -20
    )
    day = datetime.fromtimestamp(NOW + 3700, UTC).strftime("%Y-%m-%d")
    d = desk.state["days"][day]
    assert d["settled"] == 3 and d["won"] == 2 and d["pnl_usd"] < 0
    assert "w1" in desk.state["tried"]  # never bought twice
    r3 = desk.poll(NOW + 3800)
    assert r3["bought"] == 0


def test_poll_survives_a_sports_listing_failure(
    gw: Gateway, tmp_path, monkeypatch
) -> None:
    gw.markets = [_market("w1", "climate", 1800)]
    gw.quotes = {"w1": (0.97, 0.98)}

    def boom(now, cap=P.SPORTS_CAP):
        raise RuntimeError("events down")

    monkeypatch.setattr(P, "live_sports_markets", boom)
    desk = _desk(tmp_path)
    r = desk.poll(NOW)
    assert (
        r["watched"] == 1 and r["bought"] == 1 and desk.state["counters"]["errors"] == 1
    )


def test_panel_state_reads_the_file(gw: Gateway, tmp_path) -> None:
    settings = Settings.from_env({"DATA_DIR": str(tmp_path)})
    fresh = P.panel_state(settings, NOW)
    assert (
        fresh["enabled"]
        and fresh["last_ok"] is None
        and fresh["open"] == 0
        and fresh["label"] == "Paper money (pretend)"
    )
    gw.markets = [_market("w1", "climate", 1800)]
    gw.quotes = {"w1": (0.97, 0.98)}
    desk = P.PolyDesk(settings)
    desk.poll(NOW)
    gw.markets = []
    gw.settlements = {"w1": 1.0}
    desk.poll(NOW + 1900)
    d = P.panel_state(settings, NOW + 1900)
    assert (
        d["open"] == 0
        and d["settled_total"] == 1
        and d["won_total"] == 1
        and d["pnl_total_usd"] > 0
    )
    assert (
        d["today"]["settled"] == 1
        and d["events"][0]["text"].startswith("Settled:")
        and d["rule"]["theta"] == 0.97
    )
    off = Settings.from_env({"DATA_DIR": str(tmp_path), "POLYDESK_ENABLED": "false"})
    assert P.panel_state(off, NOW)["enabled"] is False


def test_state_file_is_atomic_and_versioned(tmp_path) -> None:
    path = tmp_path / "polydesk" / "state.json"
    st = P.empty_state()
    st["watched"] = 7
    P.save_state(path, st)
    assert (
        json.loads(path.read_text())["watched"] == 7
        and not path.with_suffix(".tmp").exists()
    )
    path.write_text("{garbage")
    assert P.load_state(path)["watched"] == 0
    path.write_text(json.dumps({"version": 99, "watched": 5}))
    assert (
        P.load_state(path)["watched"] == 0
    )  # an unknown version is ignored, never half-read


def test_page_members_carry_the_desks_positions() -> None:
    from nightcrawler.pagestate import _members

    panels = {mid: {"id": mid, "status": "idle", "why": "", "doing": "", "last_activity": None, "events": []}
              for mid, _, _ in __import__("nightcrawler.page", fromlist=["MEMBERS"]).MEMBERS}
    panels["predict"].update({"positions": [{"question": "Q?", "side": "long", "p_in": 0.97, "category": "sports", "t_in": 1}],
                              "label": "Paper money (pretend)"})
    card = {"source": "missing", "headline": "", "updated_at": None, "state": "collecting"}
    members = {m["id"]: m for m in _members({"panels": list(panels.values())}, card, NOW)}
    assert members["predict"]["positions"] == [{"question": "Q?", "side": "long", "p_in": 0.97, "category": "sports",
                                                "live": False}]
    assert members["predict"]["label"] == "Paper money (pretend)" and "positions" not in members["crawler"]
    assert (members["predict"]["open_real"], members["predict"]["open_paper"]) == (0, 0)  # counts come from the panel


def test_a_wide_or_one_sided_book_is_never_near_certain(gw: Gateway, tmp_path) -> None:
    """2026-10-09: the paper desk bought asks above theta on books like bid 0.14 / ask 0.69 and lost 60% of them."""
    gw.markets = [_market("wide", "crypto", 1800), _market("gap", "crypto", 1800), _market("oneside", "crypto", 1800),
                  _market("tight", "crypto", 1800)]
    gw.quotes = {"wide": (0.14, 0.98), "gap": (0.02, 0.98), "oneside": (None, 0.99), "tight": (0.97, 0.98)}
    desk = _desk(tmp_path)
    r = desk.poll(NOW)
    assert r["bought"] == 1 and set(desk.state["positions"]) == {"tight"}
    assert "wide" not in desk.state["tried"] and "within 0.03" in desk.state["rule"]["label"]


def _row(slug: str, cat: str, p: float, won: bool, pnl: float, *, spread: float | None = None, live: bool = False,
         rule: str | None = None, end_left: float = 1800.0) -> dict[str, Any]:
    """A closed row as the desk writes it; the rule and quote stamps only when given (a row from before the fix
    has neither)."""
    row: dict[str, Any] = {"slug": slug, "question": f"Will {slug} happen?", "category": cat, "side": "long", "p_in": p,
                           "shares": 20 / p, "fee_usd": 0.1, "cost_usd": p if live else 20.0, "t_in": NOW,
                           "end_ts": NOW + end_left, "live": live, "settled_at": NOW + 3600, "value": float(won),
                           "pnl_usd": pnl, "won": won}
    if rule is not None:
        row["rule"] = rule
    if spread is not None:
        row.update({"bid_in": p - spread, "ask_in": p, "spread_in": spread})
    return row


def _open(slug: str, cat: str, p: float, **kw: Any) -> dict[str, Any]:
    return {k: v for k, v in _row(slug, cat, p, False, 0.0, **kw).items() if k not in ("settled_at", "value", "pnl_usd", "won")}


def test_new_positions_carry_the_rule_version_and_the_book_at_entry(gw: Gateway, tmp_path) -> None:
    gw.markets = [_market("w1", "climate", 1800), _market("c1", "crypto", 1800)]
    gw.quotes = {"w1": (0.96, 0.975), "c1": (0.02, 0.04)}
    desk = _desk(tmp_path)
    desk.poll(NOW)
    pos = desk.state["positions"]
    assert pos["w1"]["rule"] == P.RULE_VERSION == "2026-10-09b" == desk.state["rule"]["version"]
    assert (pos["w1"]["bid_in"], pos["w1"]["ask_in"]) == (0.96, 0.975) and pos["w1"]["spread_in"] == pytest.approx(0.015)
    assert pos["c1"]["side"] == "short" and (pos["c1"]["bid_in"], pos["c1"]["ask_in"]) == (0.02, 0.04)  # the book as quoted
    gw.markets = []
    gw.settlements = {"w1": 1.0, "c1": 0.0}
    desk.poll(NOW + 1900)
    closed = {c["slug"]: c for c in desk.state["closed"]}
    assert closed["w1"]["rule"] == P.RULE_VERSION and closed["w1"]["spread_in"] == pytest.approx(0.015)  # inherited
    rec = desk.state["by_rule"]
    assert set(rec) == {P.RULE_VERSION} and set(rec[P.RULE_VERSION]) == {"paper"}  # kept as it settles, per rule and book
    assert rec[P.RULE_VERSION]["paper"]["settled"] == 2 and rec[P.RULE_VERSION]["paper"]["won"] == 2
    assert rec[P.RULE_VERSION]["paper"]["pnl_usd"] == pytest.approx(closed["w1"]["pnl_usd"] + closed["c1"]["pnl_usd"])
    d = P.panel_state(desk.settings, NOW + 1900)
    assert d["since_fix"]["paper"]["settled_total"] == 2 and d["since_fix"]["paper"]["won_total"] == 2
    assert d["before_fix"]["paper"] == {"open": 0, "settled_total": 0, "won_total": 0, "pnl_total_usd": 0.0}


def test_since_fix_and_before_fix_split_a_mixed_state_file(tmp_path) -> None:
    """A file with rows from before the stamp, a venue adoption and the new rule's own rows: the new rule's record
    stands apart (paper and real apart), everything else is 'before the fix', and every older key keeps its meaning."""
    settings = Settings.from_env({"DATA_DIR": str(tmp_path)})
    st = P.empty_state()
    before = [_row(f"old{i}", "sports", 0.98, i < 4, 0.4 if i < 4 else -20.0) for i in range(10)]  # 4 won: -118.40
    since = [_row(f"new{i}", "crypto", 0.98, i < 7, 0.3 if i < 7 else -20.0, spread=0.01, rule=P.RULE_VERSION)
             for i in range(8)]  # 7 won: -17.90
    real_before = [_row("venue1", "sports", 0.97, False, -0.99, live=True, rule=P.RULE_VENUE)]
    real_since = [_row("live1", "crypto", 0.97, True, 0.02, spread=0.01, live=True, rule=P.RULE_VERSION)]
    st["closed"] = before + since + real_before + real_since
    st["positions"] = {"p_old": _open("p_old", "politics", 0.98),
                       "p_new": _open("p_new", "crypto", 0.98, spread=0.01, rule=P.RULE_VERSION),
                       "v_open": _open("v_open", "sports", 0.97, live=True, rule=P.RULE_VENUE),
                       "r_new": _open("r_new", "crypto", 0.97, live=True, spread=0.01, rule=P.RULE_VERSION)}
    st["counters"].update({"settled": 20, "won": 12})
    st["days"] = {"2026-10-09": {"pnl_usd": -118.4 - 17.9 - 0.99 + 0.02, "settled": 20, "won": 12}}
    st["live_days"] = {"2026-10-09": {"pnl_usd": -0.97, "settled": 2, "won": 1}}
    st["live_pnl_total_usd"] = -0.97
    P.save_state(P.state_path(settings), st)
    d = P.panel_state(settings, NOW)
    assert d["since_fix"] == {"rule": "2026-10-09b",
                              "paper": {"open": 1, "settled_total": 8, "won_total": 7, "pnl_total_usd": pytest.approx(-17.9)},
                              "real": {"open": 1, "settled_total": 1, "won_total": 1, "pnl_total_usd": pytest.approx(0.02)}}
    assert d["before_fix"] == {"rule": "before the fix",
                               "paper": {"open": 1, "settled_total": 10, "won_total": 4, "pnl_total_usd": pytest.approx(-118.4)},
                               "real": {"open": 1, "settled_total": 1, "won_total": 0, "pnl_total_usd": pytest.approx(-0.99)}}
    # the older keys are the whole book, unchanged
    assert (d["open"], d["settled_total"], d["won_total"]) == (4, 20, 12) and d["pnl_total_usd"] == pytest.approx(-137.27)
    assert d["paper"]["settled_total"] == 18 and d["real"]["settled_total"] == 2 and d["real"]["open"] == 2
    assert d["lessons"] and d["worst"]["book"] == "paper" and d["worst"]["pnl_usd"] == -20.0 and d["paper_max_open"] == 60
    # the record is kept as it settles: a file that carries it is not re-read from its (capped) closed list
    st["by_rule"] = {P.RULE_VERSION: {"paper": {"settled": 230, "won": 200, "pnl_usd": 12.5}}}
    P.save_state(P.state_path(settings), st)
    d2 = P.panel_state(settings, NOW)
    assert d2["since_fix"]["paper"] == {"open": 1, "settled_total": 230, "won_total": 200, "pnl_total_usd": 12.5}
    assert d2["since_fix"]["real"]["settled_total"] == 0
    # an empty file: the shape is there, all zero
    fresh = P.panel_state(Settings.from_env({"DATA_DIR": str(tmp_path / "f")}), NOW)
    assert fresh["since_fix"]["paper"] == fresh["before_fix"]["real"] == {"open": 0, "settled_total": 0, "won_total": 0,
                                                                          "pnl_total_usd": 0.0}
    assert fresh["lessons"] == [] and fresh["worst"] is None


def test_lessons_are_computed_from_the_closed_rows_paper_and_real_apart() -> None:
    closed = [_row(f"wide{i}", "sports", 0.98, False, -20.0, spread=0.6) for i in range(6)]
    closed += [_row(f"tight{i}", "crypto", 0.98, True, 0.3, spread=0.01, rule=P.RULE_VERSION) for i in range(5)]
    closed += [_row(f"old{i}", "politics", 0.99, True, 0.1) for i in range(2)]  # no quote saved at entry
    closed += [_row("venue1", "sports", 0.97, False, -0.99, live=True, rule=P.RULE_VENUE)]
    got = P.lessons(closed)
    assert got[0] == "Wide books (spread over 0.03): 0 of 6 won, -$120 (paper) — never again (now blocked)."
    assert "Sports: 0 of 6 won, -$120 (paper); 0 of 1 won, -$0.99 (real)." in got  # stated apart, never added
    assert "Sports in play: 0 of 6 won, -$120 (paper); 0 of 1 won, -$0.99 (real)." in got
    assert "Bought at 0.97-0.99: 5 of 11 won, -$118 (paper); 0 of 1 won, -$0.99 (real)." in got
    assert got[-1] == "Tight books in crypto: 5 of 5 won, +$1.50 (paper)." and len(got) == 5
    assert all(len(s) <= 120 for s in got)
    assert P.lessons(closed[:9]) == []  # fewer than 10 settled rows: nothing is claimed
    unresolved = [{**r, "won": None, "pnl_usd": None, "unresolved": True} for r in closed]
    assert P.lessons(unresolved + closed[:9]) == []  # unresolved rows are not settlements
    assert P.worst_row(closed) == {"question": "Will wide0 happen?", "p_in": 0.98, "category": "sports", "pnl_usd": -20.0,
                                   "book": "paper", "rule": "before the fix", "settled_at": NOW + 3600}
    assert P.worst_row([r for r in closed if r["won"]]) is None
    # the other cuts: an unknown book, the price bands, the time to the end
    old = [_row(f"o{i}", "politics", 0.995, i % 2 == 0, 0.1 if i % 2 == 0 else -20.0, end_left=7200.0 if i < 5 else 600.0)
           for i in range(10)]
    got2 = P.lessons(old)
    assert "Unknown book (no quote saved at entry): 5 of 10 won, -$99.50 (paper)." in got2
    assert "Bought at 0.99 or above: 5 of 10 won, -$99.50 (paper)." in got2
    assert "Other markets (not sports or crypto): 5 of 10 won, -$99.50 (paper)." in got2
    assert got2[3] == "Bought in the last hour before the end: 2 of 5 won, -$59.80 (paper)."  # the time cut's bigger group
    assert got2[4] == "Bought more than an hour before the end: 3 of 5 won, -$39.70 (paper)."  # fills the fifth slot
    assert len(got2) == 5  # no tight book in these rows: the fifth sentence is the next biggest group instead
    assert P.lesson_key(got[0]) == "Wide books (spread over #): # of # won, -$# (paper) — never again (now blocked)."
    assert P.lesson_key("Tight books: 24 of 25 won, +$7.90 (paper).") == P.lesson_key("Tight books: 25 of 26 won, +$8.20 (paper).")
    assert P.lesson_key("Tight books: 24 of 25 won, +$7.90 (paper).") != P.lesson_key("Tight books: 24 of 45 won, -$392 (paper).")


def test_a_new_lesson_is_said_once(gw: Gateway, tmp_path) -> None:
    """The desk says a lesson when it is new (a group, a sign, a book); a changed count is the same lesson."""
    settings = Settings.from_env({"DATA_DIR": str(tmp_path)})
    st = P.empty_state()
    st["closed"] = [_row(f"t{i}", "crypto", 0.98, True, 0.3, spread=0.01, rule=P.RULE_VERSION) for i in range(10)]
    P.save_state(P.state_path(settings), st)
    desk = P.PolyDesk(settings)
    desk.poll(NOW)
    said = [e for e in desk.state["events"] if e["text"].startswith("Lesson:")]
    assert len(said) == 1 and said[0]["tone"] == "good" and said[0]["ts"] == NOW
    assert said[0]["text"] == "Lesson: Tight books (spread 0.03 or less): 10 of 10 won, +$3.00 (paper)."
    assert desk.state["last_lessons"] == P.lessons(desk.state["closed"]) and len(desk.state["last_lessons"]) == 5
    desk.poll(NOW + 100)
    assert sum(e["text"].startswith("Lesson:") for e in desk.state["events"]) == 1  # nothing new: not repeated
    # one more tight crypto win changes the counts only: the same lesson, not said again
    gw.markets = [_market("t10", "crypto", 1800)]
    gw.quotes = {"t10": (0.97, 0.98)}
    desk.poll(NOW + 200)
    gw.markets = []
    gw.settlements = {"t10": 1.0}
    desk.poll(NOW + 2000)
    assert desk.state["closed"][0]["slug"] == "t10" and "11 of 11 won" in desk.state["last_lessons"][0]
    assert sum(e["text"].startswith("Lesson:") for e in desk.state["events"]) == 1
    # a lost sports game is a new group AND flips the tight-book sign: the biggest new lesson is said, once
    gw.events = [_event("g1", -3600, "2H")]
    gw.quotes = {"g1-ml": (0.97, 0.98)}
    desk.poll(NOW + 2100)
    gw.events = []
    gw.settlements["g1-ml"] = 0.0
    desk.poll(NOW + 4000)
    said = [e for e in desk.state["events"] if e["text"].startswith("Lesson:")]
    assert len(said) == 2 and said[0]["text"] == "Lesson: Sports: 0 of 1 won, -$20.03 (paper)." and said[0]["tone"] == "bad"
    desk.poll(NOW + 4100)
    assert sum(e["text"].startswith("Lesson:") for e in desk.state["events"]) == 2
    # the panel carries the same lessons and the event
    d = P.panel_state(settings, NOW + 4100)
    assert d["lessons"] == desk.state["last_lessons"] and d["events"][0]["text"].startswith("Lesson: Sports")
    assert d["worst"]["question"] == "g1 wins" and d["worst"]["book"] == "paper"


def test_the_paper_book_is_capped_at_paper_max_open(gw: Gateway, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert P.PAPER_MAX_OPEN == 60
    monkeypatch.setattr(P, "PAPER_MAX_OPEN", 3)
    gw.markets = [_market(f"m{i}", "crypto", 1800) for i in range(5)]
    gw.quotes = {f"m{i}": (0.97, 0.98) for i in range(5)}
    desk = _desk(tmp_path)
    r = desk.poll(NOW)
    assert r["bought"] == 3 and set(desk.state["positions"]) == {"m0", "m1", "m2"}
    assert "m3" not in desk.state["tried"] and desk.state["paper_full"]  # not tried: it may be bought once a slot frees
    assert desk.state["events"][0]["text"] == "Paper book full (3 open): no new paper buys until some settle."
    desk.poll(NOW + 60)
    assert sum(e["text"].startswith("Paper book full") for e in desk.state["events"]) == 1  # said once while full
    gw.markets = [_market(f"m{i}", "crypto", 1800) for i in range(1, 5)]
    gw.settlements = {"m0": 1.0}
    r = desk.poll(NOW + 1900)  # buys are tried before settlements: still full this round, then m0 settles
    assert (r["bought"], r["settled"]) == (0, 1)
    r = desk.poll(NOW + 2000)
    assert r["bought"] == 1 and set(desk.state["positions"]) == {"m1", "m2", "m3"} and "m4" not in desk.state["tried"]
    assert sum(e["text"].startswith("Paper book full") for e in desk.state["events"]) == 2  # full again: said again
