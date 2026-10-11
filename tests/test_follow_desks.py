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

    def get(url: str, timeout: float) -> Reply:
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
    assert desk.refresh(NOW) is False and branch["urls"] == [f"{BASE}/nhl_picks.json"]  # 404: kept nothing
    assert desk.refresh(NOW + 60) is False and len(branch["urls"]) == 1  # at most every REMOTE_EVERY_S
    desk.refresh(NOW + M.REMOTE_EVERY_S)
    assert len(branch["urls"]) == 2


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
