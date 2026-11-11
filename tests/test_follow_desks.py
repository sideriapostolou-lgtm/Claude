"""The loves desks for more than one expert (nightcrawler.marcodesk.Follow): Marco and the NHL bettor each have their
own picks file and state; a desk reads its file's copy on the deploy branch (FOLLOW_PICKS_URL) between deploys and
merges it with the packaged file; an NHL desk follows NHL picks only; the page shows the NHL desk as practice money.
No network: the branch read goes through a fake ``requests.get``."""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_marcodesk import KICK, NOW, Gateway, _game, gw  # noqa: F401 - shared fixture

from nightcrawler import marcodesk as M
from nightcrawler import polydesk as P
from nightcrawler.config import Settings
from nightcrawler.pagestate import marco_desk, marco_line


def _settings(tmp_path: Path, **env: str) -> Settings:
    return Settings.from_env({"DATA_DIR": str(tmp_path), **env})


def _doc(eid: str, picks: list[dict[str, Any]], published: str = "2026-10-11T12:00:00Z") -> dict[str, Any]:
    return {"episodes": [{"id": eid, "title": eid, "published": published, "source_url": "", "picks": picks}]}


def _nhl_pick(team: str, opponent: str, rank: int = 1, league: str = "nhl", love: bool = True) -> dict[str, Any]:
    return {"rank": rank, "love": love, "league": league, "team": team, "opponent": opponent, "kind": "moneyline",
            "line": "ML", "quote": "best bet", "game_date": "2026-10-11"}


class Reply:
    def __init__(self, status: int, body: bytes) -> None:
        self.status_code, self.content = status, body


@pytest.fixture
def branch(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The deploy branch as a fake ``requests.get``: ``files`` maps a URL to (status, body)."""
    seen: dict[str, Any] = {"urls": [], "files": {}}

    def get(url: str, timeout: float, headers: dict[str, str] | None = None) -> Reply:
        seen["urls"].append(url)
        status, body = seen["files"].get(url, (404, b"Not Found"))
        return Reply(status, body)

    monkeypatch.setattr(M.requests, "get", get)
    return seen


BASE = "https://example.test/data"


def test_each_expert_has_his_own_files() -> None:
    assert M.MARCO.data_path == M.DATA_PATH
    assert M.NHL.data_path.name == "nhl_picks.json" and M.NHL.data_path.exists()
    assert M.NHL.leagues == ("nhl",) and M.NHL.sport == "hockey"
    assert len({f.key for f in M.FOLLOWS}) == len(M.FOLLOWS)


def test_the_branch_copy_is_kept_and_merged_by_episode(branch: dict[str, Any], tmp_path: Path) -> None:
    s = _settings(tmp_path, FOLLOW_PICKS_URL=BASE)
    branch["files"][f"{BASE}/nhl_picks.json"] = (200, json.dumps(_doc("day1", [_nhl_pick("New York Rangers",
                                                                                         "Vancouver Canucks")])).encode())
    assert M.fetch_remote(s, M.NHL) is True
    assert M.remote_path(s, M.NHL) == tmp_path / "nhldesk" / "picks.json"
    eps = M.follow_episodes(s, M.NHL)
    assert "day1" in [ep["id"] for ep in eps]
    assert [p["team"] for ep in eps if ep["id"] == "day1" for p in ep["picks"]] == ["New York Rangers"]


@pytest.mark.parametrize("reply", [(404, b"Not Found"), (200, b"{garbage"), (200, b'{"episodes": 3}'),
                                   (200, b"[1, 2]"), (200, b" " * (M.REMOTE_MAX_BYTES + 1))])
def test_a_bad_branch_copy_keeps_the_old_one(branch: dict[str, Any], tmp_path: Path, reply: tuple) -> None:
    s = _settings(tmp_path, FOLLOW_PICKS_URL=BASE)
    good = json.dumps(_doc("day1", [_nhl_pick("New York Rangers", "Vancouver Canucks")])).encode()
    branch["files"][f"{BASE}/nhl_picks.json"] = (200, good)
    assert M.fetch_remote(s, M.NHL)
    branch["files"][f"{BASE}/nhl_picks.json"] = reply
    assert M.fetch_remote(s, M.NHL) is False
    assert json.loads(M.remote_path(s, M.NHL).read_text()) == json.loads(good)


def test_no_url_means_packaged_files_only(branch: dict[str, Any], tmp_path: Path) -> None:
    for url in ("off", "http://example.test/data"):
        assert M.fetch_remote(_settings(tmp_path, FOLLOW_PICKS_URL=url), M.NHL) is False
    assert branch["urls"] == []


def test_an_nhl_desk_follows_nhl_picks_only(tmp_path: Path) -> None:
    s = _settings(tmp_path)
    path = M.remote_path(s, M.NHL)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_doc("day1", [_nhl_pick("New York Rangers", "Vancouver Canucks"),
                                             _nhl_pick("Green Bay Packers", "Chicago Bears", rank=2, league="nfl")])))
    teams = [p["team"] for ep in M.follow_episodes(s, M.NHL) if ep["id"] == "day1" for p in ep["picks"]]
    assert teams == ["New York Rangers"]


def test_the_desk_reads_the_branch_in_its_loop_never_in_poll(branch: dict[str, Any], gw: Gateway,  # noqa: F811
                                                            tmp_path: Path) -> None:
    desk = M.MarcoDesk(_settings(tmp_path, FOLLOW_PICKS_URL=BASE), follow=M.NHL)
    desk.poll(NOW)
    assert branch["urls"] == []
    assert desk.refresh(NOW) is False  # both 404: kept nothing
    assert branch["urls"] == [f"{BASE}/nhl_picks.json", M.NHL.source]
    assert desk.refresh(NOW + 60) is False and len(branch["urls"]) == 2  # at most every REMOTE_EVERY_S
    desk.refresh(NOW + M.REMOTE_EVERY_S)
    assert branch["urls"][2:] == [f"{BASE}/nhl_picks.json"]  # his page: at most every SOURCE_EVERY_S
    desk.refresh(NOW + M.SOURCE_EVERY_S)
    assert branch["urls"][3:] == [M.NHL.source]


def test_an_nhl_love_is_bought_on_paper_in_its_own_state(gw: Gateway, tmp_path: Path) -> None:  # noqa: F811
    kick = datetime(2026, 10, 11, 22, 0, tzinfo=UTC).timestamp()
    gw.events.append(_game("Vancouver Canucks", "New York Rangers", "van-nyr", kickoff=kick, league="nhl"))
    gw.quotes["aec-nhl-van-nyr-2026-10-11"] = (0.44, 0.45)
    s = _settings(tmp_path)
    path = M.remote_path(s, M.NHL)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_doc("day1", [_nhl_pick("New York Rangers", "Vancouver Canucks")],
                                    published="2026-10-11T12:00:00Z")))
    desk = M.MarcoDesk(s, follow=M.NHL)
    desk.poll(kick - 3600)
    rec = desk.state["picks"]["day1|1|moneyline|new york rangers"]
    assert rec["status"] == M.BOUGHT
    assert rec["position"]["long"] is False and rec["position"]["price"] == pytest.approx(0.56)  # home: 1 - bid
    assert desk.path == tmp_path / "nhldesk" / "state.json" and not M.state_path(s).exists()
    assert desk.state["events"][0]["text"].startswith(f"{M.NHL.who} desk bought Rangers moneyline")
    panel = marco_desk(s, kick - 3500, M.NHL)
    assert panel is not None and panel["who"] == M.NHL.who and panel["mode"] == "paper"
    line = marco_line(panel, "today")
    assert line is not None and line.startswith(f"{M.NHL.who}'s loves (practice, pretend money): 1 pick today")
    assert marco_desk(s, kick - 3500)["who"] == "Marco"  # Marco's own desk is untouched


def test_the_nhl_desk_never_sends_a_real_order() -> None:
    """Practice only: the module has no venue client, and the Polymarket desk's real orders read Marco's desk only (no
    real-money switch exists for the NHL bettor until the owner asks for one)."""
    assert not hasattr(Settings, "nhl_real")
    assert "polymarket_us" not in inspect.getsource(M) and "buy_long_ioc" not in inspect.getsource(M)
    real = inspect.getsource(P.PolyDesk._marco_orders)
    assert "NHL" not in real and "nhldesk" not in real and "follow_episodes" not in real


def _team(tid: int, name: str) -> dict[str, Any]:
    return {"id": tid, "full_name": name, "display_name": name.split()[-1], "abbr": name[:3].upper()}


def _an_pick(pid: int, side: int, units: float = 1.0, kind: str = "ml_away", play: str = "NYR -120",
             status: str = "published", live: bool = False, league: str = "nhl", created: str = "2026-10-11T15:00:00.000Z",
             starts: str = "2026-10-11T23:00:00.000Z") -> dict[str, Any]:
    """A pick as his Action Network profile page embeds it (read 2026-10-11): Rangers (101) at Flyers (102)."""
    return {"id": pid, "league_name": league, "play": play, "type": kind, "period": "game", "side_id": side,
            "units": units, "status": status, "is_live": live, "created_at": created, "starts_at": starts,
            "game": {"id": 9, "away_team_id": 101, "home_team_id": 102, "start_time": starts,
                     "teams": [_team(101, "New York Rangers"), _team(102, "Philadelphia Flyers")]}}


def _page(picks: list[dict[str, Any]]) -> str:
    data = {"props": {"pageProps": {"profile": {"name": "Nick Martin", "picks": picks}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


def test_his_page_reads_as_picks_and_only_full_size_pregame_moneylines_are_loves() -> None:
    picks = M.action_picks(_page([
        _an_pick(1, 101),                                              # a love: Rangers moneyline, 1u, pre-game
        _an_pick(2, 102, units=2.0, kind="ml_home", play="PHI +100"),  # a love too (2u)
        _an_pick(3, 101, units=0.5, play="NYR +400 regulation"),        # a half-unit special: not a love
        _an_pick(4, 101, live=True, play="NYR -150 (Live)"),           # live: not a love
        _an_pick(5, 101, kind="spread_away", play="NYR -1.5"),         # puck line: shown, never a love
        _an_pick(6, 101, status="deleted"),                            # withdrawn: gone
        _an_pick(7, 101, league="nfl"),                                # not hockey: gone
    ]))
    assert [(p["source_id"], p["love"], p["kind"], p["team"]) for p in picks] == [
        ("1", True, "moneyline", "New York Rangers"), ("2", True, "moneyline", "Philadelphia Flyers"),
        ("3", False, "moneyline", "New York Rangers"), ("4", False, "moneyline", "New York Rangers"),
        ("5", False, "prop", "New York Rangers")]
    assert picks[0]["opponent"] == "Philadelphia Flyers" and picks[1]["opponent"] == "New York Rangers"
    assert picks[0]["game_date"] == "2026-10-11" and picks[0]["quote"] == "NYR -120 (1u)"
    assert M.action_picks("<html>no data</html>") == [] and M.action_picks(_page([])) == []


def test_a_late_game_belongs_to_its_us_date() -> None:
    late = M.action_picks(_page([_an_pick(1, 101, starts="2026-10-12T02:30:00.000Z")]))
    assert late[0]["game_date"] == "2026-10-11"  # 10:30 pm Eastern on the 11th


def test_the_file_built_from_his_page_keeps_ranks_and_picks_that_scroll_off() -> None:
    now = datetime(2026, 10, 11, 16, 0, tzinfo=UTC).timestamp()
    first = M.merge_source(None, M.action_picks(_page([_an_pick(1, 101)])), "Nick Martin", "https://x", now)
    later = M.merge_source(first, M.action_picks(_page([_an_pick(2, 102, kind="ml_home",
                                                                created="2026-10-11T17:00:00.000Z")])),
                           "Nick Martin", "https://x", now)
    (ep,) = later["episodes"]
    assert ep["id"] == "nick-martin-2026-10-11" and ep["published"] == "2026-10-11T15:00:00.000Z"
    assert [(p["rank"], p["source_id"]) for p in ep["picks"]] == [(1, "1"), (2, "2")]
    assert M.merge_source(later, M.action_picks(_page([_an_pick(1, 101)])), "Nick Martin", "https://x", now) == later
    old = M.merge_source(None, M.action_picks(_page([_an_pick(1, 101)])), "Nick Martin", "https://x",
                         now + (M.SOURCE_KEEP_DAYS + 1) * 86_400)
    assert old["episodes"] == []  # older than the days kept


def test_his_page_feeds_the_desk(branch: dict[str, Any], gw: Gateway, tmp_path: Path) -> None:  # noqa: F811
    kick = datetime(2026, 10, 11, 23, 0, tzinfo=UTC).timestamp()
    gw.events.append(_game("New York Rangers", "Philadelphia Flyers", "nyr-phi", kickoff=kick, league="nhl"))
    gw.quotes["aec-nhl-nyr-phi-2026-10-11"] = (0.53, 0.54)
    branch["files"][M.NHL.source] = (200, _page([_an_pick(1, 101), _an_pick(3, 101, units=0.5)]).encode())
    desk = M.MarcoDesk(_settings(tmp_path, FOLLOW_PICKS_URL="off"), follow=M.NHL)
    assert desk.refresh(kick - 7200) is True
    desk.poll(kick - 7200)
    recs = {pid.split("|")[1]: rec for pid, rec in desk.state["picks"].items()}
    assert recs["1"]["status"] == M.BOUGHT and recs["1"]["position"]["price"] == pytest.approx(0.54)
    assert recs["2"]["status"] == M.NOT_LOVE
