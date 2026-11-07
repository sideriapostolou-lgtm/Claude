"""The team's hearts (``plain.hearts``, :mod:`nightcrawler.hearts`): fixed temperaments and reasons to care, moods chosen
from the page's own figures only, heart lines from fixed templates filled with those figures only. Every mood (and
every template) is reachable from data; every number in a line traces to the inputs; real and pretend money are never
added and the practice crew always say practice or pretend; a missing figure gives no line (and no goal, no hearts);
hearts reaches no desk."""

from __future__ import annotations

import ast
import itertools
import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock
from test_page import NOW, seed

from nightcrawler import hearts, pagestate
from nightcrawler.config import Settings
from nightcrawler.ledger import Ledger
from nightcrawler.world3d import WORLD_CAST
from tests import goal_states as GS
from tests import heart_states as HS

SRC = Path(pagestate.__file__).resolve().parent
DAY0 = 1_791_590_400.0  # 2026-10-10 00:00 UTC
FMT = {"dollars": pagestate._dollars, "signed": pagestate._signed, "limit": pagestate._limit}
_MONEY = re.compile(r"[+−-]?\$[\d,]+(?:\.\d+)?")
_BANNED = re.compile(r"win it back|make it back|double (?:down|up)|\ball in\b|jackpot|\bluck(?:y)?\b|gambl|hurry|"
                     r"need to win|must win|push harder|bet more|bigger|raise|deadline|guarantee|promise|will make|"
                     r"sure thing|can't lose|easy money", re.IGNORECASE)


def _goal(mood: str = "climb", today: float | None = 1.52, *, stand: str | None = None, day_used: float = 0.0,
          lost: float = 3.11, practice: float | None = 2.4, solana: bool = False) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [{"id": "polymarket", "today_usd": today, "settled": 6, "won": 6}]
    if solana:
        parts.append({"id": "solana", "today_usd": 0.5})
    return {"target_usd": 100.0, "day_start": DAY0, "mood": mood, "real_today_usd": today, "stand_down": stand,
            "parts": parts, "floor": {"day_loss_usd": day_used, "day_max_usd": 30.0, "hit": stand == "day"},
            "lifeline": {"lost_usd": lost, "max_usd": 40.0, "left_usd": round(40.0 - lost, 2), "segments_lit": 9},
            "practice": {"solana_today_usd": None if solana else practice, "polymarket_today_usd": -5.0}}


def _inp(goal: dict[str, Any] | None, *, last: tuple[str, float] | None = None, status: str = "idle",
         verified: bool | None = True, contracts: float = 10.0, old: bool = False) -> dict[str, Any]:
    finished = [{"id": "trade|PEPE|1", "ts": DAY0 + 50, "who": "jet", "what": "PEPE", "result": "lost", "usd": 4.4,
                 "real": False, "money": "pretend"}]  # (a practice trade: never counts)
    if last is not None:
        ts = DAY0 - 600 if old else DAY0 + 3600
        finished.insert(0, {"id": f"bet|{ts:.3f}|Q", "ts": ts, "who": "voss", "what": "Q", "result": last[0],
                            "usd": last[1], "real": True, "money": "real money"})
    team = [{"id": k, "status_word": status if k in ("pip", "nyx", "jet") else "working"} for k in hearts.CAST]
    return {"goal": goal, "team": team, "finished": finished, "receipts": {"count": 1234, "verified": verified},
            "contracts": contracts, "theta": 0.97}


def _hearts(inp: dict[str, Any]) -> dict[str, Any]:
    out = hearts.team_hearts(inp, **FMT)
    assert out is not None
    return out


def _by_id(out: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {m["id"]: m for m in out["members"]}


def _grid() -> list[dict[str, Any]]:
    """Inputs over every town signal, the crew's statuses, a tight stop and the record check."""
    goals = [_goal("stopped_for_good", -3.0, lost=40.0), _goal("off", 0.0), _goal("unknown", None),
             _goal("stand_down", -30.2, stand="day", day_used=30.2), _goal("stand_down", -0.5, stand="risk"),
             _goal("climb", -8.82, day_used=8.82), _goal("climb", -21.0, day_used=21.0), _goal("goal", 101.5),
             _goal("climb", 1.52), _goal("climb", 0.0), _goal("climb", 1.52, practice=None), _goal("off", 0.0, practice=None),
             {**_goal("stand_down", -30.2, stand="day", day_used=30.2), "lifeline": None}]
    out = []
    for goal, status, verified in itertools.product(goals, ("idle", "working", "stuck"), (True, False, None)):
        lasts: list[tuple[str, float] | None] = [None, ("won", 0.25), ("lost", 9.8)]
        for last in lasts:
            out.append(_inp(goal, last=last, status=status, verified=verified))
    return out


def _allowed(inp: dict[str, Any]) -> set[str]:
    """Every figure a line may say: the inputs' own, in the page's own wording (computed here independently)."""
    g, d, s, lim = inp["goal"], pagestate._dollars, pagestate._signed, pagestate._limit
    ok = {lim(g["target_usd"]), lim(g["floor"]["day_max_usd"]), d(g["floor"]["day_loss_usd"]),
          d(max(0.0, round(g["floor"]["day_max_usd"] - g["floor"]["day_loss_usd"], 2))),
          d(round(inp["contracts"] * inp["theta"], 2))}
    if g["lifeline"]:
        ok |= {d(g["lifeline"]["lost_usd"]), d(g["lifeline"]["left_usd"])}
    today = g["real_today_usd"]
    if today is not None:
        ok |= {s(today), d(today), d(round(g["target_usd"] - today, 2))}
    if g["practice"]["solana_today_usd"] is not None:
        ok.add(s(g["practice"]["solana_today_usd"]))
    for row in inp["finished"]:
        if row["real"]:
            ok.add(d(row["usd"]))
    return ok


# --------------------------------------------------------------------------- the cast and the copy


def test_the_cast_is_the_worlds_with_fixed_temperaments_and_reasons() -> None:
    out = _hearts(_inp(_goal()))
    assert [m["id"] for m in out["members"]] == ["voss", "rook", "pip", "nyx", "jet", "mote"]
    assert set(hearts.CAST) == set(WORLD_CAST)
    for m in out["members"]:
        assert m["name"] == WORLD_CAST[m["id"]]["name"]
        assert m["temperament"] == hearts.CAST[m["id"]]["temperament"] and m["why"] == hearts.CAST[m["id"]]["why"]
        assert "lights" in m["why"] and m["why"].endswith(".") and m["why"].count(".") == 1  # (one sentence each)
    t = {m["id"]: m["temperament"] for m in out["members"]}
    assert "real money" in t["voss"] and "too much to gamble" in t["rook"] and "scouting" in t["pip"]
    assert "scams" in t["nyx"] and "every trade" in t["jet"] and "honest record" in t["mote"]
    assert out["label"] == "The team's hearts"


def test_the_copy_is_careful() -> None:
    """No gambler's words, no promise, no nudge to bigger bets; the $100 is the owner's goal, never a need."""
    texts = list(hearts.TEMPLATES.values()) + list(hearts.HUDDLE_TEMPLATES.values())
    texts += [c["temperament"] for c in hearts.CAST.values()] + [c["why"] for c in hearts.CAST.values()]
    for text in texts:
        # (Rook's refusals: "too much to gamble it", "I won't let us ... chasing it")
        assert not _BANNED.search(text.replace("too much to gamble it", "").replace("chasing it", "")), text
        if "{target}" in text:
            assert "owner's" in text and "goal" in text, text
    assert "{per}" in hearts.TEMPLATES[("rook", "calm", "live")] and "the owner's choice" in hearts.TEMPLATES[
        ("rook", "calm", "live")]  # (the bet size is the owner's: Rook may state it, nobody urges it)
    for key, text in hearts.TEMPLATES.items():
        if key[0] in hearts.PRACTICE:
            assert "practice" in text.lower() or "pretend" in text.lower(), key
            assert "real money" not in text or "practice (pretend money)" in text, key  # (Jet says the town's real)
        else:
            assert "pretend" not in text and "practice" not in text.lower(), key


# --------------------------------------------------------------------------- moods from data only


def test_every_mood_and_every_template_is_reachable_from_data() -> None:
    reached: set[tuple[str, str]] = set()
    lines: set[str] = set()
    for inp in _grid():
        for m in _hearts(inp)["members"]:
            assert m["mood"] in hearts.MOODS
            if m["line"]:
                reached.add((m["id"], m["mood"]))
                lines.add(m["line"])
    assert {mood for _, mood in reached} == set(hearts.MOODS)
    assert reached == {(k[0], k[1]) for k in hearts.TEMPLATES}
    # every template (each situation) said at least once
    said = 0
    for template in hearts.TEMPLATES.values():
        pattern = re.escape(template)
        for name in re.findall(r"\\\{(\w+)\\\}", pattern):
            pattern = pattern.replace(r"\{" + name + r"\}", ".+?")
        if any(re.fullmatch(pattern, line) for line in lines):
            said += 1
        else:
            pytest.fail(f"never said: {template}")
    assert said == len(hearts.TEMPLATES)


def test_moods_follow_the_real_money_and_the_stops() -> None:
    win = _by_id(_hearts(_inp(_goal("climb", 1.52), last=("won", 0.25))))
    assert win["voss"]["mood"] == "proud" and win["voss"]["line"] == ("Brought home $1.52 for the town today. $98.48 "
                                                                       "to go to the owner's $100 goal.")
    assert win["rook"]["mood"] == "calm" and win["jet"]["mood"] == "proud" and win["pip"]["mood"] == "hopeful"
    hit = _by_id(_hearts(_inp(_goal("climb", -8.82, day_used=8.82), last=("lost", 9.8))))
    assert hit["voss"] == {**hit["voss"], "mood": "hurting", "line": "That miss cost the town $9.80. I owe it steadier "
                                                                     "hands."}
    assert hit["rook"]["mood"] == "worried"
    assert hit["rook"]["line"] == ("One miss now costs about $9.70; $21.18 is left under today's stop. I won't let us "
                                   "spend the town's savings chasing it.")
    assert {hit[k]["mood"] for k in ("pip", "nyx", "jet")} == {"determined"}
    # an old loss (yesterday's) is not today's hit; a practice loss never is
    old = _by_id(_hearts(_inp(_goal("climb", 1.52), last=("lost", 9.8), old=True)))
    assert old["voss"]["mood"] == "proud" and old["rook"]["mood"] == "calm"
    # the stop: Voss hurts, Rook is relieved the stop held (and says the room kept for good)
    day = _by_id(_hearts(_inp(_goal("stand_down", -30.2, stand="day", day_used=30.2, lost=33.31))))
    assert day["voss"]["mood"] == "hurting" and day["rook"]["mood"] == "relieved"
    assert day["rook"]["line"] == "The $30 daily stop held. It stings, but $6.69 of the town's room is kept for another day."
    # a tight stop worries Rook even after a win (less than two misses of room left)
    tight = _by_id(_hearts(_inp(_goal("climb", -21.0, day_used=21.0), last=("won", 0.25))))
    assert tight["rook"]["mood"] == "worried" and tight["voss"]["mood"] == "determined"
    goal = _by_id(_hearts(_inp(_goal("goal", 101.5))))
    assert goal["voss"]["mood"] == "proud" and goal["rook"]["mood"] == "relieved" and goal["mote"]["mood"] == "proud"
    assert goal["rook"]["line"] == ("Goal day, and my limits never moved: every bet 10 contracts, a stop at $30 a day. "
                                    "That is how the town stays safe.")
    off = _by_id(_hearts(_inp(_goal("off", 0.0))))
    assert off["voss"]["mood"] == "calm" and "off today" in off["voss"]["line"]
    unknown = _by_id(_hearts(_inp(_goal("unknown", None))))
    assert "not known yet" in unknown["voss"]["line"] and unknown["voss"]["mood"] == "calm"
    # the crew's own status: stuck worries them; the record check's fault worries Mote
    stuck = _by_id(_hearts(_inp(_goal(), status="stuck", verified=False)))
    assert {stuck[k]["mood"] for k in ("pip", "nyx", "jet", "mote")} == {"worried"}


def test_every_number_in_a_line_traces_to_the_inputs() -> None:
    for inp in _grid():
        ok = _allowed(inp)
        for m in _hearts(inp)["members"]:
            for figure in _MONEY.findall(m["line"] or ""):
                assert figure in ok, (m["id"], m["line"], figure)
            for n in re.findall(r"(\d[\d,]*) (contracts?|sealed records)", m["line"] or ""):
                assert n[0] in ("10", "1,234"), m["line"]


def test_real_and_pretend_are_never_added_and_practice_says_so() -> None:
    inp = _inp(_goal("climb", 1.52, practice=2.4))
    out = _by_id(_hearts(inp))
    assert "Practice today: +$2.40 (pretend money)" in out["pip"]["line"]
    for m in out.values():
        assert "$3.92" not in (m["line"] or "")  # (1.52 + 2.40: never)
    for inp in _grid():
        for m in _hearts(inp)["members"]:
            if m["id"] in hearts.PRACTICE and m["line"]:
                assert "practice" in m["line"].lower() or "pretend" in m["line"].lower(), m
                practice = inp["goal"]["practice"]["solana_today_usd"]
                if practice is not None and pagestate._signed(practice) in m["line"]:
                    assert "(pretend money)" in m["line"]
            if m["id"] not in hearts.PRACTICE:
                assert "pretend" not in (m["line"] or "")
            assert m["money"] == ("pretend money" if m["id"] in hearts.PRACTICE else "real money")
    # the Solana bot on real money: the practice words would not be true, so the crew says nothing
    live = _by_id(_hearts(_inp(_goal(solana=True))))
    assert all(live[k]["line"] is None and live[k]["money"] == "real money" for k in hearts.PRACTICE)
    assert live["voss"]["line"]


def test_a_missing_figure_gives_no_line_and_no_goal_gives_no_hearts() -> None:
    assert hearts.team_hearts(_inp(None), **FMT) is None
    assert hearts.team_hearts({}, **FMT) is None
    # no bet size: Rook cannot say what one miss costs (no "$0.00"), so he says nothing rather than a zero
    out = _by_id(_hearts(_inp(_goal("climb", -8.82, day_used=8.82), last=("lost", 9.8), contracts=0.0)))
    assert out["rook"]["mood"] == "worried" and out["rook"]["line"] is None
    # no practice figure: Pip's line without one; no record count: Mote's without one
    bare = _by_id(_hearts({**_inp(_goal(practice=None)), "receipts": {}}))
    assert bare["pip"]["line"] == hearts.TEMPLATES[("pip", "hopeful", "plain")]
    assert bare["mote"]["line"] == hearts.TEMPLATES[("mote", "calm", "plain")]
    # a settled bet without its dollars: no huddle line with a made-up figure
    inp = _inp(_goal(), last=("won", 0.25))
    inp["finished"][0]["usd"] = None
    assert _hearts(inp)["huddle"] is None
    for inp in _grid():
        for m in _hearts(inp)["members"]:
            assert "$0.00" not in (m["line"] or "") or m["id"] == "rook"  # (Rook's "$0.00 used of $30" is a figure)


def test_the_huddle_is_the_newest_real_settlement_today() -> None:
    out = _hearts(_inp(_goal(), last=("lost", 9.8)))
    assert out["huddle"] == {"id": f"bet|{DAY0 + 3600:.3f}|Q", "ts": DAY0 + 3600, "result": "lost", "usd": 9.8,
                             "line": "A real bet just settled: lost $9.80 (real money). The team gathers at the goal tower."}
    assert _hearts(_inp(_goal()))["huddle"] is None  # (a practice trade never gathers anyone)
    assert _hearts(_inp(_goal(), last=("won", 0.25), old=True))["huddle"] is None  # (yesterday's: not new today)


# --------------------------------------------------------------------------- the page


def test_the_page_carries_plain_hearts_after_the_goal(tmp_path: Path) -> None:
    settings = Settings.from_env({"DATA_DIR": str(tmp_path)})
    with Ledger(tmp_path / "nc.db", clock=FakeClock(NOW)) as ledger:
        seed(ledger)
        page = pagestate.build_page_state(ledger, settings, NOW)
    h = page["plain"]["hearts"]
    assert h is not None and [m["id"] for m in h["members"]] == list(hearts.CAST)
    assert h == pagestate.hearts_block(settings, page)
    json.dumps(h, allow_nan=False)


def test_the_hearts_states_say_the_owners_size(tmp_path: Path) -> None:
    base = GS.base_page()
    win = _by_id(HS.apply_heart_state(base, "winning")["plain"]["hearts"])
    loss_page = HS.apply_heart_state(base, "losing_big")
    loss = _by_id(loss_page["plain"]["hearts"])
    assert win["voss"]["line"] == "Brought home $1.52 for the town today. $98.48 to go to the owner's $100 goal."
    assert loss["voss"]["line"] == "That miss cost the town $9.80. I owe it steadier hands."
    assert "about $9.70" in loss["rook"]["line"] and "$21.18 is left" in loss["rook"]["line"]
    assert loss_page["plain"]["hearts"]["huddle"]["line"].startswith("A real bet just settled: lost $9.80")


def test_a_failure_gives_null_hearts_and_a_log_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                    caplog: pytest.LogCaptureFixture) -> None:
    def boom(*_: Any, **__: Any) -> None:
        raise ValueError("boom")

    monkeypatch.setattr(hearts, "team_hearts", boom)
    settings = Settings.from_env({"DATA_DIR": str(tmp_path)})
    with Ledger(tmp_path / "nc.db", clock=FakeClock(NOW)) as ledger, caplog.at_level(logging.WARNING):
        seed(ledger)
        page = pagestate.build_page_state(ledger, settings, NOW)
    assert page["plain"]["hearts"] is None and page["plain"]["goal"] is not None
    assert "hearts_failed error=ValueError" in caplog.text


# --------------------------------------------------------------------------- no path to any desk


def test_hearts_reaches_no_desk() -> None:
    tree = ast.parse((SRC / "hearts.py").read_text(encoding="utf-8"))
    imported = {(n.module or "") if isinstance(n, ast.ImportFrom) else a.name for n in ast.walk(tree)
                if isinstance(n, (ast.Import, ast.ImportFrom)) for a in (n.names if isinstance(n, ast.Import) else [n])}
    assert imported and imported <= {"__future__", "math", "string", "collections.abc", "typing"}, imported
    probe = ("import sys, nightcrawler.hearts; "
             "print(sorted(m for m in sys.modules if m.startswith('nightcrawler')))")
    res = subprocess.run([sys.executable, "-c", probe],
                         capture_output=True, text=True, timeout=60, check=True, cwd=str(SRC.parent))
    assert json.loads(res.stdout.replace("'", '"')) == ["nightcrawler", "nightcrawler.hearts"]
    named = sorted(str(p.relative_to(SRC)) for p in SRC.rglob("*.py")
                   if re.search(r"\bhearts\b", p.read_text(encoding="utf-8")) and p.name != "hearts.py")
    assert named == ["pagestate.py", "world3d.py"], named  # (no desk names it: polydesk, deskguard, risk, engine ...)
