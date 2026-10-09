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
