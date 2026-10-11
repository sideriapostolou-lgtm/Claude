"""The 3D world's goal (world3d's THE GOAL section): the goal tower, the town's bill and backup power, the practice yard,
the strip in the bar, the goal panel, the beats and the programmes. Its pure block, its boards and its panel run here in
Node (the record room's recording canvas), over tests/goal_states.py's states: only real money lights anything (H2, H4),
red is real money only (H8), the strip says the data's words and never cuts the figure, beats fire only on a change seen
during the visit and wait for a real-money replay, a programme, a reader or the guide; the section never edits the live
director, allocates nothing in its frame step, makes no AudioContext of its own and never carries the token."""

from __future__ import annotations

import copy
import json
import math
import re
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock
from test_page import NOW, seed

from nightcrawler import pagestate
from nightcrawler.config import Settings
from nightcrawler.ledger import Ledger
from nightcrawler.world3d import _STYLE_GOAL, render_world_html
from tests import goal_states as GS
from tests.test_world3d import _js_body, _module, _node
from tests.test_world_records import _REDS, _film, _helpers

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
_HEADER, _DIRECTOR, _LOOP = "= THE GOAL (town goal)", "= THE LIVE DIRECTOR: an always-on broadcast", "= THE LOOP (paused"
_RECORDS = "THE RECORD ROOM (Builder B)"
#: the gambler's words (H6), never in the section's own copy either
_BANNED = re.compile(r"win it back|make it back|double (?:down|up)|\ball in\b|jackpot|\bluck(?:y)?\b|gambl|hurry|"
                     r"need to win|must win|push harder|bet more|deadline|skilled|genius|expert|chase it",
                     re.IGNORECASE)


@pytest.fixture(scope="module")
def page() -> str:
    return render_world_html(Settings.from_env({"DATA_DIR": "/tmp/nightcrawler-world-goal-test"}))


@pytest.fixture(scope="module")
def module(page: str) -> str:
    return _module(page)


@pytest.fixture(scope="module")
def section(module: str) -> str:
    start = module.index(_HEADER)
    return module[module.rindex("\n", 0, start) + 1:module.index(_DIRECTOR)]


@pytest.fixture(scope="module")
def records(module: str) -> str:
    return module[module.index(_RECORDS):module.index(_HEADER)]


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    tmp = tmp_path_factory.mktemp("world-goal")
    settings = Settings.from_env({"DATA_DIR": str(tmp)})
    with Ledger(tmp / "nc.db", clock=FakeClock(NOW)) as ledger:
        seed(ledger)
        return pagestate.build_page_state(ledger, settings, NOW)


@pytest.fixture(scope="module")
def states(base: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {name: GS.apply_state(base, name, GS.SNAPSHOT_AT) for name in GS.STATES}


def _at(base: dict[str, Any], today: float) -> dict[str, Any]:
    """town.goal as the server builds it with one real result today (a bet won, or lost; none at all at zero)."""
    name = "_probe"
    GS.STATES[name] = {"today": today, "settled": 0 if today == 0 else 1, "won": 1 if today > 0 else 0, "live": True,
                       "practice": 0.0, "env": {}, "about": "a probe"}
    try:
        goal: dict[str, Any] = GS.apply_state(base, name, GS.SNAPSHOT_AT)["town"]["goal"]
        return goal
    finally:
        del GS.STATES[name]


def _pure(section: str) -> str:
    return section[section.index("// >>> goal (pure)"):section.index("// <<< goal")]


def _fn(source: str, name: str) -> str:
    return _js_body(source, f"  function {name}(")


def _code(text: str) -> str:
    """The source without its line comments (a "//" inside a string literal stays: none in the section)."""
    return re.sub(r"(?m)^\s*//[^\n]*|  // [^\n]*", "", text)


def _line(source: str, start: str) -> str:
    found = re.search(r"^" + re.escape(start) + r".*$", source, re.MULTILINE)
    assert found is not None, start
    return found.group(0)


def _pages(states: dict[str, dict[str, Any]], names: Any = None) -> dict[str, dict[str, Any]]:
    return {n: {"g": states[n]["town"]["goal"], "w": states[n]["plain"]["goal"]} for n in (names or GS.STATES)}


def _dedup(items: list[str]) -> list[str]:
    """An engraving paints each line twice (its light edge, then its ink): each line once."""
    return [t for i, t in enumerate(items) if i == 0 or items[i - 1] != t]


# --------------------------------------------------------------------------- where the section sits


def test_the_goal_is_its_own_section_called_once_a_frame(page: str, module: str, section: str) -> None:
    assert module.index(_RECORDS) < module.index(_HEADER) < module.index(_DIRECTOR) < module.index(_LOOP)
    loop = _js_body(module, "  function frame(now) {")
    assert loop.count("goalFrame();") == 1 and module.count("goalFrame();") == 1
    assert loop.index("recFrame();") < loop.index("goalFrame();") < loop.index("director();")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "new Function", "document.write"):
        assert sink not in section, sink
    assert "window.__skyport = Object.assign(window.__skyport || {}, { goal: {" in section
    for hook in ("look: function ()", "beat: function (kind, rung)", "checkIn: function ()", "tour: function ()",
                 "strip: function ()"):
        assert hook in section, hook
    # its CSS in the page's one style (hashed by the CSP), its strip in the bar under the headline, before the status
    (style,) = re.findall(r"<style>(.*?)</style>", page, flags=re.DOTALL)
    assert _STYLE_GOAL in style and "#goal {" in _STYLE_GOAL
    head = page[page.index('<header id="bar">'):page.index("</header>")]
    assert head.index('id="headline"') < head.index('<button type="button" id="goal"') < head.index('id="status"')
    assert '<button type="button" id="goal" aria-controls="panel" hidden>' in head
    # a fault in the section stops the goal, never the world
    frame = _fn(section, "goalFrame")
    assert "if (!GOAL.ok) return;" in frame and "try { goalStep(); } catch (e) { GOAL.ok = false;" in frame
    assert "try { goalBuild(); GOAL.ok = true; }" in section
    # the one browser storage it keeps: the beats it has said today (read and written in a try)
    assert section.count("localStorage") == 1
    assert "function goalStore() { try { return window.localStorage; } catch (e) { return null; } }" in section


def test_the_goal_leaves_the_live_director_as_it_was(module: str, section: str) -> None:
    """The director's section names nothing of the goal; the goal reads FLY.on at most, never the planner, a rig or a
    cut of its own; it films through the record room's views and programmes; it makes no event (no bubble, no ticker
    item, no replay) and only reads the channel's replay."""
    director = module[module.index(_DIRECTOR):module.index(_LOOP)]
    for name in ("GOAL", "goalFrame", "goalStep", "goalLook", "GP", "goalStrip", "goalPlay", "goalFree"):
        assert re.search(r"\b" + name + r"\b", director) is None, name
    code = _code(section)
    assert set(re.findall(r"FLY\.\w+", code)) <= {"FLY.on"} and "FLY.on =" not in code
    for foreign in ("PLANNER.", "RIGS[", "liveDirector(", "startShot(", "setFov(", " cut(", "focusOn(", "togglePin("):
        assert foreign not in code, foreign
    assert code.count('recViewOf("') == 6 and code.count('progStart("goal", ') == 3
    for view in ('"goaltower"', '"goalboard"', '"billplaque"', '"yard"', '"power"', '"promenade"'):
        assert view in code, view
    for event in ("speak(", "replayQueue", "tickerItems", "bubblesEl", "showReplay(", "BUS.emit("):
        assert event not in code, event
    assert "sk.replay.now()" in _fn(section, "goalFree")


def test_the_goal_frame_allocates_nothing(section: str) -> None:
    for name in ("goalStep", "goalMove", "goalFrame"):
        body = _code(_fn(section, name))
        for banned in ("new ", "function (", "[]", "{}", ".map(", ".filter(", ".slice(", ".concat(", ".forEach(",
                       "JSON", "=> ", "createElement", "Array.from", '+ "', "Object.assign"):
            assert banned not in body, (name, banned)
    # the data once a poll lands, never per frame
    assert "if (data !== GOAL.seen) { GOAL.seen = data; if (data) goalApply(data); }" in _fn(section, "goalStep")


# --------------------------------------------------------------------------- the look: real money only


_LADDER = (-3.11, 0.0, 0.03, 0.21, 1.5, 12.0, 100.4, 160.0, 212.0, 320.0)


def _looks(section: str, goals: list[Any], tmp_path: Path, phone: bool = False,
           reduced: bool = False) -> list[dict[str, Any]]:
    return list(_node(_pure(section) + f"""
const out = {json.dumps(goals)}.map(function (g) {{
  return JSON.parse(JSON.stringify(goalLook(g, {json.dumps(phone)}, {json.dumps(reduced)}, {{}}))); }});
console.log(JSON.stringify(out));
""", tmp_path))


@needs_node
def test_goal_look_follows_real_money_only(section: str, base: dict[str, Any], states: dict[str, dict[str, Any]],
                                           tmp_path: Path) -> None:
    """Rung by rung (the server's own town.goal at each figure): rings, beacon, generator, stalls, bunting, visitors,
    fireworks; a phone shows at most 12 visitors; less motion turns the fireworks into a still lamp ring."""
    goals = [_at(base, v) for v in _LADDER]
    desk = _looks(section, goals, tmp_path)
    phone = _looks(section, goals, tmp_path, phone=True)
    calm = _looks(section, [goals[6]], tmp_path, reduced=True)
    keys = ("tier", "rings", "beacon", "generator", "stalls", "bunting", "visitors", "fireworks")
    assert [[d[k] for k in keys] for d in desk] == [
        ["below", 0, False, "on", "shut", "none", 0, 0],
        ["even", 0, False, "on", "shut", "none", 1, 0],
        ["zero", 1, False, "on", "shut", "none", 2, 0],
        ["bill", 2, False, "off", "open", "none", 4, 0],
        ["one", 3, False, "off", "open", "bunting", 6, 0],
        ["ten", 4, False, "off", "open", "bunting", 9, 0],
        ["goal", 5, True, "off", "open", "flags", 13, 1],
        ["great", 6, True, "off", "open", "flags", 16, 2],
        ["double", 7, True, "off", "open", "flags", 19, 3],
        ["triple", 8, True, "off", "open", "flags", 21, 4]]
    spots = _line(section, "  const GOAL_SPOTS = ")
    n_spots = len(re.findall(r"\[-?\d+\.?\d*, -?\d+\.?\d*\]", section[section.index("  const GOAL_SPOTS = "):
                                                                    section.index("  function goalBuild(")]))
    assert spots and max(d["visitors"] for d in desk) <= n_spots == 21  # (never more visitors than places)
    assert [d["visitors"] for d in phone] == [0, 1, 2, 4, 6, 8, 12, 12, 12, 12]
    assert [d["figure"] for d in desk[:3]] == ["loss", "neutral", "gain"]
    assert desk[0]["gold"] == 0 and desk[2]["gold"] == pytest.approx(goals[2]["bill_share_real"]) and desk[3]["gold"] == 1
    assert 0 < desk[2]["gold"] < 1
    assert calm[0]["fireworks"] == 0 and calm[0]["glow"] is True and desk[6]["glow"] is False
    assert desk[6]["ring"] == ["lit", "lit", "lit", "lit", "goal", "dark", "dark", "dark"]
    assert desk[8]["ring"][4:] == ["goal", "above", "above", "dark"]
    assert [d["column"] for d in desk] == [0, 0, 1, 2, 3, 4, 5, 6, 7, 8]
    # the states: the snapshot's embers (above zero and the bill reached earlier today, gone dark), the stop hit
    looks = dict(zip(GS.STATES, _looks(section, [states[n]["town"]["goal"] for n in GS.STATES], tmp_path), strict=True))
    s = looks["stopped_today"]
    assert s["ring"][:3] == ["ember", "ember", "dark"] and s["floorHit"] is True and s["floor"] == 1
    assert s["stripFloor"] == "hit" and s["lifeline"] == 5 and s["figure"] == "loss" and s["visitors"] == 0
    assert looks["losing"]["stripFloor"] == "below" and 0 < looks["losing"]["floor"] < 1
    # H4: real money off (or no real book at all) lights nothing; the town runs on the owner's backup power
    for name in ("off", "practice_only"):
        L = looks[name]
        assert (L["rings"], L["column"], L["generator"], L["stalls"], L["visitors"], L["fireworks"], L["gold"],
                L["beacon"], L["bunting"], L["figure"]) == (0, 0, "on", "shut", 0, 0, 0, False, "none", "neutral"), name
        assert set(L["ring"]) == {"dark"}, name
    g = states["tiny"]["town"]["goal"]
    unknown = dict(g, tier={"id": "unknown", "rank": None}, power=None, real_today_usd=None, bill_share_real=None,
                   rungs=[dict(r, lit=False, reached=False) for r in g["rungs"]])
    u, none = _looks(section, [unknown, None], tmp_path)
    assert (u["generator"], u["rings"], u["visitors"], u["figure"]) == ("idle", 0, 0, "neutral")
    assert (none["generator"], none["rings"], none["n"], none["tier"]) == ("idle", 0, 0, "unknown")
    # H2: two goals that differ only in practice look the same, and goalLook never reads practice at all
    a = copy.deepcopy(states["bill"]["town"]["goal"])
    b = copy.deepcopy(a)
    b["practice"] = {"label": "Practice (pretend money)", "counts_toward_goal": False, "solana_today_usd": 777.77,
                     "polymarket_today_usd": 1000.0, "trend_today_usd": 99.0, "crew_road": None}
    la, lb = _looks(section, [a, b], tmp_path)
    assert la == lb
    assert "practice" not in _fn(section, "goalLook")
    # the rings' colours: never red (red is real money's loss, on the floor gauge only)
    cols = _line(section, "  const GOAL_COL = ").lower()
    assert not any(red in cols for red in ("ff6b61", "ff8a80", "d8453b", "cf3129", "b3261e"))
    assert "0xffcf7a, 3.2" in section  # (the gold beacon)


# --------------------------------------------------------------------------- the strip


_STRIP_DOM = r"""
function mk(tag) { return { tag: tag, className: "", textContent: "", hidden: true, attrs: {}, children: [], style: {},
  appendChild: function (c) { this.children.push(c); return c; },
  removeChild: function (c) { this.children.splice(this.children.indexOf(c), 1); },
  get lastChild() { return this.children[this.children.length - 1]; }, setAttribute: function (k, v) { this.attrs[k] = v; } }; }
const document = { createElement: mk };
const goalStrip = mk("button"), goalLabel = mk("span"), goalPips = mk("span"), goalBeatEl = mk("span"), goalFig = mk("b");
let measured = 0; const measureBar = function () { measured += 1; };
const window = { innerWidth: 390 };
"""


@needs_node
def test_the_strip_says_the_data_and_red_is_real_money(section: str, states: dict[str, dict[str, Any]],
                                                       tmp_path: Path) -> None:
    """The label and figure are plain.goal's own words; the figure red-pink only for a real loss, green for a real
    gain, neutral when real money is off; the pips: the floor, the rungs up to the goal, one beyond; under 340 px the
    short figure; the figure never cut (no ellipsis on it, its own width); hidden without plain.real."""
    names = ["stopped_today", "tiny", "met", "double", "off", "practice_only"]
    out = _node(_pure(section) + _STRIP_DOM + f"""
const GOAL = {{}}, GOAL_LOOK = {{ ring: [] }};
{_fn(section, "goalStripRender")}
const P = {json.dumps(_pages(states, names))}, out = {{}};
Object.keys(P).forEach(function (n) {{
  GOAL.g = P[n].g; GOAL.w = P[n].w; goalLook(GOAL.g, false, false, GOAL_LOOK); goalStripRender();
  out[n] = {{ hidden: goalStrip.hidden, label: goalLabel.textContent, fig: goalFig.textContent, cls: goalFig.className,
    aria: goalStrip.attrs["aria-label"], pips: goalPips.children.map(function (c) {{ return c.className; }}) }};
}});
window.innerWidth = 320; GOAL.g = P.double.g; GOAL.w = P.double.w; goalLook(GOAL.g, true, false, GOAL_LOOK); goalStripRender();
out.narrow = goalFig.textContent;
GOAL.g = null; GOAL.w = null; goalStripRender(); out.gone = goalStrip.hidden; out.measured = measured;
console.log(JSON.stringify(out));
""", tmp_path)
    for n in names:
        w = states[n]["plain"]["goal"]
        assert out[n]["label"] == w["strip_label"] == "Goal $100/day" and out[n]["fig"] == w["strip_figure"], n
        assert out[n]["aria"] == w["aria"] and out[n]["hidden"] is False, n
    assert [out[n]["cls"] for n in names] == ["gfig loss", "gfig gain", "gfig gain", "gfig gain", "gfig neutral",
                                              "gfig neutral"]
    assert out["stopped_today"]["fig"] == "−$3.11 real today" and out["off"]["fig"] == "real money is off"
    assert out["stopped_today"]["pips"] == ["gfloor hit", "ember", "ember", "dark", "dark", "dark", "beyond "]
    assert out["met"]["pips"] == ["gfloor ", "lit", "lit", "lit", "lit", "goal", "beyond "]
    assert out["double"]["pips"][-1] == "beyond above" and out["off"]["pips"][1:6] == ["dark"] * 5
    assert out["narrow"] == states["double"]["plain"]["goal"]["strip_figure_short"] == "+$212.00 real"
    assert out["gone"] is True and out["measured"] == 2  # (shown once, hidden once: the bar measured each time)
    fig = re.search(r"#goal \.gfig \{[^}]*\}", _STYLE_GOAL)
    assert fig is not None and "text-overflow" not in fig.group(0) and "flex: 0 0 auto" in fig.group(0)
    assert "white-space: nowrap" in fig.group(0)
    label = re.search(r"#goal \.glabel \{[^}]*\}", _STYLE_GOAL)  # the goal's own words: never cut, the pips give way
    assert label is not None and "flex: 0 0 auto" in label.group(0) and "text-overflow" not in label.group(0)
    assert "#goal .gpips { flex: 1 1 auto;" in _STYLE_GOAL and "overflow: hidden" in _line(_STYLE_GOAL, "#goal .gpips {")
    assert "#goal .gfig.loss { color: #ff8a80; }" in _STYLE_GOAL and "#goal .gfig.gain { color: #5fe39a; }" in _STYLE_GOAL
    assert "@media (min-width: 760px) { #goal { flex: 0 1 420px; } }" in _STYLE_GOAL
    assert "@media (prefers-reduced-motion: reduce) { #goal.beat { animation: none; } }" in _STYLE_GOAL
    assert "const show = !!(g && w && page.plain && page.plain.real);" in _fn(section, "goalApply")


# --------------------------------------------------------------------------- the beats


_SEEN = r"""
const store = {}; let blocked = false;
const fakeStore = function () { if (blocked) throw new Error("SecurityError");
  return { getItem: function (k) { return k in store ? store[k] : null; }, setItem: function (k, v) { store[k] = String(v); } }; };
"""


@needs_node
def test_beats_fire_only_on_changes_seen_during_the_visit(section: str, states: dict[str, dict[str, Any]],
                                                          tmp_path: Path) -> None:
    """The first poll sets the state silently (but for yesterday's closing card, once in this browser, said as
    yesterday's: never a day opening on load); then a rung lit (LIGHT ON), gone dark (LIGHT OFF), a stand-down, the goal
    reached once a UTC day (in storage; with storage blocked, once a page load), the day closing then opening when the
    day turns during the visit; nothing while real money is off. The queue keeps two at most, never the same twice, and
    GOAL REACHED takes a waiting LIGHT ON's place."""
    out = _node(_pure(section) + _SEEN + f"""
const P = {json.dumps(_pages(states))}, out = {{}};
function run(seq, seen) {{
  let prev = null; const said = [];
  seq.forEach(function (n) {{ const s = P[n], b = goalChanges(prev, s.g, s.w, seen);
    b.forEach(function (x) {{ if (x.kind === "closes") seen.mark("closed." + x.day); if (x.kind === "reached") seen.mark("reached." + x.day); }});
    said.push(b.map(function (x) {{ return x.kind + (x.late ? "(late)" : "") + (x.rung ? ":" + x.rung.id : ""); }}).join(",")); prev = goalSnap(s.g); }});
  return said;
}}
out.first = run(["stopped_today"], goalSeen(fakeStore));
out.again = run(["stopped_today"], goalSeen(fakeStore));
out.walk = run(["tiny", "bill", "tiny", "losing", "stopped_today", "bill", "met", "bill", "met", "double"], goalSeen(fakeStore));
out.reload = run(["bill", "met"], goalSeen(fakeStore));
out.stored = Object.keys(store).sort();
blocked = true;
out.blocked = run(["bill", "met", "bill", "met"], goalSeen(fakeStore));
out.blockedLoad = run(["bill", "met"], goalSeen(fakeStore));
out.off = run(["off", "practice_only", "off", "tiny"], goalSeen(fakeStore));
blocked = false;
const next = JSON.parse(JSON.stringify(P.tiny)); next.g.day = "2026-10-11"; next.w.result = Object.assign({{}}, next.w.result, {{ day: "2026-10-10" }});
P.next = next;
out.day = run(["tiny", "next"], goalSeen(fakeStore));
const q = [];
goalQueue(q, {{ kind: "on", rung: {{ id: "zero" }} }}); goalQueue(q, {{ kind: "on", rung: {{ id: "zero" }} }});
out.dedupe = q.length; goalQueue(q, {{ kind: "off", rung: {{ id: "bill" }} }}); goalQueue(q, {{ kind: "reached", rung: {{ id: "goal" }} }});
out.queue = q.map(function (x) {{ return x.kind; }});
goalQueue(q, {{ kind: "stand", rung: null }}); out.full = q.map(function (x) {{ return x.kind; }});
goalQueue(q, {{ kind: "closes", rung: null }}); goalQueue(q, {{ kind: "opens", rung: null }}); goalQueue(q, {{ kind: "on", rung: {{ id: "one" }} }});
out.dayq = q.map(function (x) {{ return x.kind; }});
const T = function (kind, n, rung) {{ return goalBeatText({{ kind: kind, rung: rung }}, P[n].g, P[n].w); }};
out.text = {{ on: T("on", "bill", P.bill.g.rungs[1]), off: T("off", "tiny", P.tiny.g.rungs[1]), stand: T("stand", "stopped_today"),
  reached: T("reached", "met"), closes: T("closes", "stopped_today"), opens: T("opens", "stopped_today"),
  late: goalBeatText({{ kind: "closes", rung: null, late: true }}, P.stopped_today.g, P.stopped_today.w) }};
out.quiet = ["on", "off", "stand", "reached", "closes", "opens"].map(goalQuiet);
console.log(JSON.stringify(out));
""", tmp_path)
    assert out["first"] == ["closes(late)"] and out["again"] == [""]  # yesterday's card once in this browser, no "opens"
    assert out["walk"] == ["", "on:bill", "off:bill", "off:zero", "stand", "on:bill", "reached:goal", "off:one", "on:goal",
                           "on:double"]
    assert out["reload"] == ["", "on:goal"]  # the goal reached once a UTC day: after a reload it is a LIGHT ON
    assert out["stored"] == ["nightcrawler.world.goal.closed.2026-10-09", "nightcrawler.world.goal.reached.2026-10-10"]
    assert out["blocked"] == ["closes(late)", "reached:goal", "off:one", "on:goal"]  # storage blocked: once a page load
    assert out["blockedLoad"] == ["closes(late)", "reached:goal"]  # (and again on the next: nothing could be remembered)
    assert out["off"] == ["", "", "", "on:zero"]  # real money off says nothing; a ring lit once it is back on does
    assert out["day"] == ["", "closes,opens"]  # the day turning during the visit: it closes, then a new one opens
    assert out["dedupe"] == 1 and out["queue"] == ["off", "reached"] and out["full"] == ["reached", "stand"]
    assert out["dayq"] == ["closes", "opens"]  # a new day clears the old one's beats and keeps its own two
    t = out["text"]
    # (today's real figure is the strip's own, beside the beat: never repeated, never cut; a figure a beat says comes
    # first, before anything a narrow strip may cut)
    assert t["on"] == "LIGHT ON · Covers the bill" and t["off"] == "LIGHT OFF · Covers the bill"
    assert t["stand"] == "STAND DOWN · daily stop reached"
    assert t["reached"] == "GOAL REACHED · same size"
    assert t["closes"] == "DAY CLOSES · −$1.78 real money"
    assert t["late"] == "YESTERDAY · −$1.78 real money"  # (on load: yesterday's card, never "the day closes" now)
    assert t["opens"] == "NEW DAY (UTC) · goal $100/day"
    assert out["quiet"] == [False, True, True, False, False, False]  # a light gone dark and a stand-down: no brass glow


@needs_node
def test_beats_wait_for_a_replay_a_programme_a_reader_and_the_guide(section: str, states: dict[str, dict[str, Any]],
                                                                    tmp_path: Path) -> None:
    """A beat's strip shows at once; its programme starts only when nothing else is on (no guide, no panel, no
    programme, no real-money replay, the tab in view) and gives up after a minute; the check-in comes once a visit,
    after the first poll's 40 s, when nothing waits."""
    g, w = states["bill"]["town"]["goal"], states["bill"]["plain"]["goal"]
    out = _node(_pure(section) + f"""
let simT = 0, panelKind = null;
const data = {{}}, guideEl = {{ hidden: true }}, FILM = {{ on: false, kind: "", shown: -1, script: [] }}, REC = {{ chip: null }};
const document = {{ visibilityState: "visible" }};
let replay = null; const window = {{ __skyport: {{ replay: {{ now: function () {{ return replay; }} }} }} }};
const performance = {{ _t: 0, now: function () {{ return this._t; }} }};
const clamp = function (v, a, b) {{ return Math.min(b, Math.max(a, v)); }};
const GOAL = {{ ok: true, seen: data, g: {json.dumps(g)}, w: {json.dumps(w)}, prev: null, queue: [], beatUntil: 0, pending: null,
  pendingAt: 0, firstAt: 0, checkInAt: 40, checkInDone: false, chip: null, shown: -1, lastT: 0, humT: 0, lean: 0 }};
const started = []; let shown = "";
const progStart = function (kind, script) {{ started.push(kind + ":" + script.length); FILM.on = true; FILM.kind = kind; return true; }};
const goalBeatShow = function (t) {{ shown = t; GOAL.beatUntil = performance.now() + GOAL_STRIP_MS; }};
const goalBeatEnd = function () {{ GOAL.beatUntil = 0; shown = ""; }};
const goalCue = function () {{}}, goalMove = function () {{}}, goalHum = function () {{}}, goalChordStep = function () {{}};
const goalGest = function () {{}}, goalApply = function () {{}}, goalChipMake = function () {{}};
const goalBeatScript = function (b) {{ return [b, b]; }}, goalProg = function (list) {{ return list; }};
const marked = []; const goalSeenStore = {{ mark: function (k) {{ marked.push(k); }} }};
{_fn(section, "goalFree")}
{_fn(section, "goalPlay")}
{_fn(section, "goalCheckIn")}
{_fn(section, "goalBeatStart")}
{_fn(section, "goalStep")}
function tick(s) {{ for (let i = 0; i < Math.round(s * 10); i++) {{ simT += 0.1; performance._t += 100; goalStep(); }} }}
const out = {{}};
GOAL.queue.push({{ kind: "on", rung: GOAL.g.rungs[1] }});
guideEl.hidden = false; tick(1); out.guide = [shown, started.length];
guideEl.hidden = true; panelKind = "real"; tick(1); out.panel = started.length;
panelKind = null; replay = {{ id: "bet" }}; tick(1); out.replay = started.length;
replay = null; document.visibilityState = "hidden"; tick(1); out.hidden = started.length;
document.visibilityState = "visible"; tick(0.2); out.free = started.slice();
FILM.on = false; GOAL.queue.push({{ kind: "off", rung: GOAL.g.rungs[1] }}); FILM.on = true; FILM.kind = "tour";
tick(8); out.busy = [started.length, GOAL.pending ? GOAL.pending.kind : null];
tick(70); out.expired = [started.length, GOAL.pending, GOAL.checkInDone];
FILM.on = false; tick(1); out.checkIn = [started.slice(), GOAL.checkInDone];
FILM.on = false; tick(60); out.once = started.length;
// yesterday's card: marked said when its programme starts, never while it waits (a guide open for 90 s lets it expire
// unseen: then it is not marked, and the next visit shows it)
out.marks0 = marked.slice(); FILM.on = false; guideEl.hidden = false;
GOAL.queue.push({{ kind: "closes", rung: null, day: "2026-10-09", late: true }}); tick(70); out.expiredMarks = marked.slice();
guideEl.hidden = true; FILM.on = false; GOAL.queue.push({{ kind: "closes", rung: null, day: "2026-10-09", late: true }}); tick(8);
GOAL.queue.push({{ kind: "reached", rung: GOAL.g.rungs[1], day: "2026-10-10" }}); FILM.on = false; tick(8);
out.marks = marked.slice();
console.log(JSON.stringify(out));
""", tmp_path)
    assert out["guide"][0] == "LIGHT ON · Covers the bill" and out["guide"][1] == 0
    assert out["panel"] == 0 and out["replay"] == 0 and out["hidden"] == 0  # (a real JUST FINISHED goes first)
    assert out["free"] == ["goal:2"]
    assert out["busy"] == [1, "off"]  # another programme on air: the next beat waits
    assert out["expired"] == [1, None, False]  # a minute on, it gives up (the strip said it)
    assert out["checkIn"] == [["goal:2", "goal:6"], True] and out["once"] == 2  # (the check-in: six beats at most)
    assert out["marks0"] == [] and out["expiredMarks"] == []  # never marked said before it played
    assert out["marks"] == ["closed.2026-10-09", "reached.2026-10-10"]


# --------------------------------------------------------------------------- the boards, the panel, the guide


def _board_lib(module: str, section: str) -> str:
    return (_helpers(module) + _line(section, "  const GOAL_INK = ") + "\n" + _pure(section) + r"""
function gboard(w, h) { const b = board(w, h), ctx = b.userData.canvas.getContext("2d"); ctx.clearRect = function () {}; return b; }
const GP = { board: gboard(1024, 576), plaque: gboard(512, 712), yard: gboard(1024, 646), tags: gboard(256, 2048) };
const GOAL_LOOK = { ring: [] }, GOAL_RING_DY = 0.5;
""" + "\n".join(_fn(section, n) for n in ("goalDrawBoard", "goalDrawPlaque", "goalDrawYard", "goalDrawTags")))


@needs_node
def test_the_boards_paint_the_datas_words(module: str, section: str, states: dict[str, dict[str, Any]],
                                          tmp_path: Path) -> None:
    """The streak board, the bill plaque, the practice yard and the ring tags paint the data's words and the fixed
    copy, never "undefined", "NaN" or "null"; the yard is blue and slate only (pretend money is never red)."""
    out = _node(_board_lib(module, section) + f"""
const P = {json.dumps(_pages(states))}, out = {{}};
const words = function () {{ return painted().map(function (d) {{ return [d.t, d.fill]; }}); }};
Object.keys(P).forEach(function (n) {{
  const s = P[n]; goalLook(s.g, false, false, GOAL_LOOK);
  goalDrawBoard(s.g, s.w); const b = words(); goalDrawPlaque(s.w); const p = words();
  goalDrawYard(s.g, s.w); const y = words(); goalDrawTags(s.g); const t = words();
  out[n] = {{ board: b, plaque: p, yard: y, tags: t }};
}});
goalDrawBoard(null, null); out.none = {{ board: words() }}; goalDrawYard(null, null); out.none.yard = words();
goalDrawPlaque(null); out.none.plaque = words(); goalDrawTags(null); out.none.tags = words();
console.log(JSON.stringify(out));
""", tmp_path)
    for name, shot in out.items():
        for part, items in shot.items():
            for text, _fill in items:
                assert not re.search(r"undefined|NaN|null|\[object", text), (name, part, text)
                assert not _BANNED.search(text), (name, part, text)
        for text, fill in shot.get("yard", []):
            assert str(fill).lower() not in _REDS, (name, text, fill)  # pretend money is never red
            if "$" in text:
                assert text.endswith("(pretend)"), (name, text)
    s, w = out["stopped_today"], states["stopped_today"]["plain"]["goal"]
    board = [t for t, _ in s["board"]]
    assert board[:2] == ["DAY 2 ON REAL MONEY", "In a row (closed days, UTC): up 0 · bill covered 0 · goal met 0"]
    assert board[2:] == ["−$1.78", "10-09 UTC", "No up day on real money yet."]
    assert [f for t, f in s["board"] if t == "−$1.78"] == ["#ffb3ab"]  # (a real loss: red)
    plaque = _dedup([t for t, _ in s["plaque"]])
    assert plaque[:4] == ["THE TOWN'S BILL", "$0.17", "a day", "(hosting + AI judge, real)"]  # (the bill is both)
    assert " ".join(plaque[4:]) == w["plaque_line"] == "today: paid by the owner"
    assert " ".join(_dedup([t for t, _ in out["bill"]["plaque"]])[4:]) == "today: covered by real money"
    yard = [t for t, _ in s["yard"]]
    assert yard[:7] == ["PRACTICE · PRETEND MONEY · never counts toward the goal", "The Solana bot today",
                        "−$5.26 (pretend)", "Polymarket practice today", "−$5.26 (pretend)", "The trend desk's last day",
                        "−$0.53 (pretend)"]
    steps = states["stopped_today"]["town"]["goal"]["practice"]["crew_road"]["steps"]
    n = len(steps)  # (the road line wraps on the board: two lines at most, never cut)
    assert " ".join(yard[7:-n]) == w["crew_road_line"] and yard[-n:] == ["· " + st["label"] for st in steps]
    for secret in ("Keys shared in chat", "Dashboard locked"):  # the security steps stay off the world
        assert not any(secret in t for t in yard), secret
    assert [t for t, _ in out["practice_only"]["yard"]][1:3] == ["The Solana bot today", "+$777.77 (pretend)"]
    # (embers: reached earlier today, not lit now, so in slate and said "earlier", never in a lit ring's colour)
    assert [t for t, _ in s["tags"]] == ["> $0", "earlier today", "bill $0.17", "earlier today", "$1", "$10",
                                         "$100 GOAL", "$150", "$200", "$300"]
    assert [f for _, f in s["tags"]][:5] == ["#8f9bb3", "#e0b25e", "#8f9bb3", "#e0b25e", "#c7c0b2"]
    assert [t for t, _ in out["bill"]["tags"]][:3] == ["> $0", "bill $0.17", "$1"]  # (lit: no "earlier")
    assert [f for _, f in out["double"]["tags"]][4:7] == ["#ffcf7a", "#d9c8ff", "#d9c8ff"]
    none = out["none"]
    assert [t for t, _ in none["board"]] == ["REAL MONEY: NOT STARTED", "History not available yet",
                                             "No closed day on real money yet.", "No up day on real money yet."]
    assert [t for t, _ in none["yard"]][1:] == ["No practice book today.",
                                                "Road to real money for the Solana bot: not known yet."]
    assert none["tags"] == []


_PANEL_DOM = r"""
function mk(tag) { return { tag: tag, className: "", textContent: "", children: [], style: {}, type: "",
  appendChild: function (c) { this.children.push(c); return c; } }; }
const document = { createElement: mk };
const panelBody = mk("div"), panelEl = mk("div"), panelTitle = mk("h2");
Object.defineProperty(panelBody, "textContent", { set: function () { this.children = []; }, get: function () { return ""; } });
function flat(n, out) {
  if (n.tag === "p" || n.tag === "h3" || n.tag === "li" || n.tag === "button") out.push([n.tag, n.className, n.textContent]);
  n.children.forEach(function (c) { flat(c, out); }); return out; }
const isNum = function (v) { return typeof v === "number" && isFinite(v); };
let closed = 0, checkins = 0; const closePanel = function () { closed += 1; }, goalCheckIn = function (f) { checkins += f ? 1 : 100; };
"""


@needs_node
def test_the_goal_panel_lists_the_api_lines_in_order(module: str, section: str, states: dict[str, dict[str, Any]],
                                                     tmp_path: Path) -> None:
    """The ladder (the rungs top to bottom, today's marker, the red cellar of the day's stop) beside the first lines,
    then plain.goal's lines in their order, the practice box in blue, the honest line and the check-in button."""
    state = states["stopped_today"]
    g, w = state["town"]["goal"], state["plain"]["goal"]
    out = _node(_pure(section) + _PANEL_DOM + _js_body(module, "  function para(parent, text, cls) {") + f"""
const data = {json.dumps(state)}, GOAL = {{ g: data.town.goal, w: data.plain.goal, phone: true }}, GOAL_LOOK = {{ ring: [] }};
const GOAL_CALM = false;
{_fn(section, "goalReset")}
{_fn(section, "goalNowS")}
{_fn(section, "goalLadder")}
{_fn(section, "goalHead")}
{_fn(section, "goalOf")}
{_fn(section, "goalPanel")}
goalPanel();
const items = flat(panelBody, []), kids = panelBody.children, button = kids[kids.length - 1];
const ladder = kids[0].children[0].children.map(function (c) {{
  return [c.className, c.textContent || (c.children[1] ? c.children[1].textContent : "")]; }});
button.onclick();
const practice = kids.filter(function (c) {{ return c.className === "gpractice"; }}).map(function (c) {{ return flat(c, []).map(function (x) {{ return x[2]; }}); }});
console.log(JSON.stringify({{ title: panelTitle.textContent, cls: panelEl.className, items: items, closed: closed,
  checkins: checkins, ladder: ladder, practice: practice, cellar: kids[0].children[0].children[9].children[0].style.width,
  box: kids[0].children[0].className }}));
""", tmp_path)
    assert out["title"] == "The owner's goal: $100 a day (real money)" and out["cls"] == "goal"
    texts = [t for _, _, t in out["items"]]
    steps = ["· " + s["label"] for s in g["practice"]["crew_road"]["steps"]]
    order = [w["line"], w["ember_line"], "New day in ", w["bill_line"], w["power_line"], w["floor_line"],
             w["lifeline_line"], w["reserve_line"],
             "Why the meter is low", w["reach_line"], w["streak_line"], *w["day_lines"], w["best_line"],
             "The road to the $100 goal", *w["road_lines"], w["practice_line"], w["crew_road_line"], *steps,
             w["honest"], "Watch the goal check-in"]
    order = [o for o in order if o]
    assert len(texts) == len(order)
    for text, want in zip(texts, order, strict=True):
        assert text.startswith(want.split("{local_reset}")[0]), (text, want)
    assert re.fullmatch(r"New day in 3 h 31 min \(.+ your time\)\.", texts[2]), texts[2]
    assert ["p", "ember", w["ember_line"]] in out["items"] and "+$0.47" in w["ember_line"]  # (amber, in words)
    assert [t for tag, _, t in out["items"] if tag == "h3"] == ["Why the meter is low", "The road to the $100 goal"]
    assert ["p", "dim", w["reserve_line"]] in out["items"] and ["p", "dim", w["honest"]] in out["items"]
    assert out["practice"] == [[w["practice_line"], w["crew_road_line"], *steps]]
    for text in texts:
        assert not _BANNED.search(text), text
    assert out["closed"] == 1 and out["checkins"] == 1  # the button: the panel closes, the check-in plays (forced)
    ladder = out["ladder"]
    assert [c[1] for c in ladder[:8]] == ["$300", "$200", "$150", "$100 GOAL", "$10", "$1", "bill $0.17", "> $0"]
    assert [c[0] for c in ladder[:8]] == ["grung dark"] * 6 + ["grung ember"] * 2
    assert ladder[8] == ["gmark loss", "−$3.11 real"]  # below zero the marker sits under the rungs, never at $0
    assert ladder[9] == ["gcellar", "today's loss stop"] and out["cellar"] == "100%"
    assert ladder[10] == ["gkey", "amber: reached earlier today"] and out["box"] == "gladder em"  # (what amber means)


@needs_node
def test_the_panel_marker_sits_at_the_highest_ring_lit(section: str, states: dict[str, dict[str, Any]],
                                                       tmp_path: Path) -> None:
    out = _node(_pure(section) + _PANEL_DOM + f"""
const P = {json.dumps(_pages(states, ["tiny", "met", "off"]))}, GOAL_LOOK = {{ ring: [] }}, out = {{}};
{_fn(section, "goalLadder")}
Object.keys(P).forEach(function (n) {{ goalLook(P[n].g, false, false, GOAL_LOOK);
  out[n] = goalLadder(P[n].g, P[n].w).children.map(function (c) {{ return c.className; }}); }});
console.log(JSON.stringify(out));
""", tmp_path)
    assert out["tiny"][7:9] == ["gmark gain", "grung lit"]  # just above the "> $0" rung
    assert out["met"][3:5] == ["gmark gain", "grung goal"]
    assert out["off"][8:] == ["gmark neutral", "gcellar"]  # off: at the bottom, neither green nor red


@needs_node
def test_the_guide_has_four_cards_and_the_goal_card_says_not_a_cost(page: str, module: str, section: str,
                                                                    states: dict[str, dict[str, Any]],
                                                                    tmp_path: Path) -> None:
    cards = re.findall(r'<section class="gcard"><h2[^>]*>([^<]*)</h2><div id="([^"]+)">', page)
    assert [c[1] for c in cards] == ["guide-team", "guide-money", "guide-goal", "guide-camera"]
    assert cards[2][0] == "The team's goal"
    assert '<span class="dots" id="guide-dots"><i class="on"></i><i></i><i></i><i></i></span>' in page
    assert 'if (guidePage >= el("guide-dots").children.length - 1) { closeGuide(); return; }' in module
    assert "guidePage >= 2" not in module
    assert 'goalGuide(el("guide-goal"));' in _js_body(module, "  function renderGuide() {")
    out = _node(_PANEL_DOM + _js_body(module, "  function para(parent, text, cls) {") + f"""
let data = {json.dumps(states["stopped_today"])};
{_fn(section, "goalReset")}
{_fn(section, "goalGuide")}
const box = mk("div"); goalGuide(box); const a = box.children.map(function (p) {{ return p.textContent; }});
data = {{ plain: {{ goal: null }}, town: {{ goal: null }} }}; const none = mk("div"); goalGuide(none);
console.log(JSON.stringify({{ a: a, none: none.children.map(function (p) {{ return p.textContent; }}) }}));
""", tmp_path)
    a, w = out["a"], states["stopped_today"]["plain"]["goal"]
    assert a[0] == "The team's goal: $100 a day in real money, set by the owner, and more is better."
    assert a[1].startswith("What really keeps the town running is its bill: $0.17 a day for hosting and the AI judge.")
    assert "the owner pays it: that is the backup power by the kiosk." in a[1]
    assert "on real money only" in a[2] and re.search(r"midnight UTC \(.+ your time\)\.$", a[2])
    assert "a dim amber ring was reached earlier today and is not lit now" in a[2]  # (what amber means, in the guide)
    assert a[3].startswith("Practice (pretend money) trains the team but never counts")
    assert a[4] == ("The goal changes no bet size, limit or rule. The team gets there only with a strategy that "
                    "proves itself.")
    assert a[5] == w["honest"] and "not a cost" in a[5] and len(a) == 6
    assert out["none"] == ["The team's goal shows here once the bot's own data has arrived."]
    for text in a:
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if "$100" in sentence:
                assert "goal" in sentence.lower(), sentence  # the $100 is a goal, never a cost (H1)
            assert not _BANNED.search(sentence), sentence


# --------------------------------------------------------------------------- the programmes and the chip


def _secs(base: float, text: str, note: str = "") -> float:
    """goalSecs: at least the script's seconds, longer for more words (0.32 s a word, to the half second), 12 at most."""
    words = len(f"{text} {note}".split())
    return max(base, min(12.0, round(0.32 * words * 2) / 2))


@needs_node
def test_the_tour_and_check_in_are_the_record_rooms_programmes(section: str, records: str,
                                                               states: dict[str, dict[str, Any]],
                                                               tmp_path: Path) -> None:
    """Each beat is a board's own view or a character's pin, with the data's words: the desk's own lines (Voss, Rook)
    in red as real money, practice in blue as pretend, the records' Mote in neither; Rook's real-money words on his own
    wall (never over a shot of whoever stands near him); the owner's backup power while it runs, the promenade once
    real money pays the bill; each beat long enough to read; the beats' scripts by kind."""
    g, w = states["stopped_today"]["town"]["goal"], states["stopped_today"]["plain"]["goal"]
    wb, gb = states["bill"]["plain"]["goal"], states["bill"]["town"]["goal"]
    boards = section[section.index("  const GOAL_BOARDS = "):section.index("  function goalCard(")]
    fns = "\n".join(_fn(section, n) for n in ("goalReset", "goalCard", "goalScript", "goalProg", "goalCheckIn",
                                               "goalTour", "goalRungAt", "goalBeatScript"))
    out = _node(_pure(section) + f"""
const actors = {{ voss: {{}}, rook: {{}}, pip: {{}}, nyx: {{}}, jet: {{}}, mote: {{}} }};
const CAST = {{ voss: {{ name: "Voss" }}, rook: {{ name: "Rook" }}, pip: {{ name: "Pip" }}, nyx: {{ name: "Nyx" }},
  jet: {{ name: "Jet" }}, mote: {{ name: "Mote" }} }};
const REC_VIEWS = {{ goaltower: {{ mesh: {{ visible: true }} }}, billplaque: {{ mesh: {{ visible: true }} }},
  goalboard: {{ mesh: {{ visible: true }} }}, yard: {{ mesh: {{ visible: true }} }}, riskwall: {{ mesh: {{ visible: true }} }},
  power: {{ mesh: {{ visible: true }} }}, promenade: {{ mesh: {{ visible: true }} }} }};
const data = {{ plain: {{ goal: {json.dumps(w)} }} }}, GOAL = {{ g: {json.dumps(g)}, w: data.plain.goal, checkInDone: false }};
const started = [];
const progStart = function (kind, script) {{ started.push([kind, script]); return true; }};
const goalFree = function () {{ return true; }};
{_js_body(records, "  function filmBeat(phase, cam, s, tag, prog, who, text, cls) {")}
{boards}
{fns}
goalCheckIn(false); goalTour();
const beats = {{}};
["on", "off", "stand", "reached", "closes", "opens"].forEach(function (k) {{ beats[k] = goalBeatScript({{ kind: k, rung: GOAL.g.rungs[1] }}); }});
REC_VIEWS.billplaque.mesh.visible = false; const hidden = goalProg(data.plain.goal.programmes.tour)[1].cam;
REC_VIEWS.billplaque.mesh.visible = true;
// the bill's rung lit by real money (the stalls open) and gone dark (the generator starts again)
GOAL.g = {json.dumps(gb)}; GOAL.w = {json.dumps(wb)};
const billOn = goalBeatScript({{ kind: "on", rung: GOAL.g.rungs[1] }}), zeroOn = goalBeatScript({{ kind: "on", rung: GOAL.g.rungs[0] }});
GOAL.g = {json.dumps(g)}; GOAL.w = {json.dumps(w)};
const billOff = goalBeatScript({{ kind: "off", rung: GOAL.g.rungs[1] }});
REC_VIEWS.riskwall.mesh.visible = false; const rookBeat = goalProg(data.plain.goal.programmes.check_in)[3], rookPin = [rookBeat.cam, rookBeat.who];
console.log(JSON.stringify({{ started: started, beats: beats, hidden: hidden, done: GOAL.checkInDone, billOn: billOn,
  zeroOn: zeroOn, billOff: billOff, rookPin: rookPin }}));
""", tmp_path)
    (kind, check_in), (kind2, tour) = out["started"]
    assert kind == kind2 == "goal" and out["done"] is True
    assert [b["cam"] for b in check_in] == ["view:goaltower", "view:power", "voss", "view:riskwall", "voss", "mote"]
    assert [b["cam"] for b in tour] == ["view:goaltower", "view:billplaque", "view:power", "view:riskwall",
                                        "view:goalboard", "view:yard", "voss", "view:riskwall", "pip", "nyx", "jet",
                                        "mote"]
    assert [b["prog"] for b in check_in] == [f"{i} of 6" for i in range(1, 7)]
    texts = [b["text"] for b in w["programmes"]["tour"]]
    assert [b["s"] for b in tour] == [_secs(7, t) for t in texts[:6]] + [_secs(6, t) for t in texts[6:]]
    assert all(b["s"] <= 12 for b in tour) and max(b["s"] for b in tour) > 7  # (a long line gets the time to read it)
    for b in tour + check_in:
        assert "{local_reset}" not in json.dumps(b, ensure_ascii=False)
        assert b["cardH"] == 170 and b["gest"] is None
    by = {b["who"]: b for b in tour}
    voss, (before, after) = by["VOSS"], w["lines"]["voss"].split("{local_reset}")
    assert voss["cls"] == "real" and voss["text"] == "" and voss["real"].startswith(before)
    assert voss["real"].endswith(after)
    rook = by["ROOK · THE RISK WALL"]  # (Rook's words on his own wall, his name on the card, red: real money)
    assert rook["cam"] == "view:riskwall" and rook["cls"] == "real" and rook["real"] == w["lines"]["rook"]
    assert rook["text"] == "" and "ROOK" not in by
    assert out["rookPin"] == ["rook", "ROOK"]  # (a version without the wall: the director's pin on him, as before)
    for who in ("PIP", "NYX", "JET"):
        assert by[who]["pretend"] == w["lines"][who.lower()] and by[who]["tag"] == "PRACTICE · PRETEND MONEY", who
        assert by[who]["cls"] == "" and by[who]["text"] == "" and by[who]["real"] == "", who
    yard = by["THE PRACTICE YARD"]
    assert yard["tag"] == "PRACTICE · PRETEND MONEY" and yard["cls"] == ""
    assert yard["text"] == yard["pretend"] == w["practice_line"] + " " + w["crew_road_line"]
    assert by["MOTE"]["cls"] == "" and by["MOTE"]["text"] == w["lines"]["mote"]  # the records are no money: not red
    tower = by["THE GOAL TOWER"]  # (the tower's beat says what amber means)
    assert tower["text"] == w["line"] + " " + w["ember_line"] and by["THE TOWN'S BILL"]["text"] == w["bill_line"]
    assert by["THE OWNER'S BACKUP POWER"]["text"] == w["power_line"] and by["THE OWNER'S BACKUP POWER"]["cam"] == "view:power"
    assert by["THE VAULT"]["cam"] == "view:riskwall" and by["THE VAULT"]["text"] == " ".join(
        [w["lifeline_line"], w["floor_line"], w["reserve_line"]])
    assert out["hidden"] == ""  # a board out of this version: no view (the film holds its card)
    beats = out["beats"]
    assert [b["cam"] for b in beats["on"]] == ["view:goaltower", "view:power", "voss"]  # (the bill's rung: the power)
    assert beats["on"][2]["gest"] == [["voss", "cheer"]] and beats["on"][0]["gest"] == [["mote", "nod"]]
    assert [b["cam"] for b in beats["off"]] == ["view:goaltower", "view:power", "view:riskwall"]
    assert [b["cam"] for b in beats["stand"]] == ["view:riskwall", "voss"]  # (Rook says the stop on his wall)
    assert beats["stand"][0]["real"] == w["lines"]["rook"] and beats["stand"][0]["who"] == "ROOK · THE RISK WALL"
    assert beats["stand"][0]["gest"] == [["rook", "worried"]]
    assert not any(gs[1] == "cheer" for k in ("off", "stand") for b in beats[k] for gs in (b["gest"] or []))
    assert [b["cam"] for b in beats["reached"]] == ["view:goaltower", "voss", "pip", "view:riskwall", "jet", "mote"]
    reached_texts = [w["line"], w["lines"]["voss"], w["lines"]["pip"], w["lines"]["rook"], w["lines"]["jet"],
                     w["lines"]["mote"]]
    assert [b["s"] for b in beats["reached"]] == [_secs(b, t) for b, t in zip([6, 4, 4, 4, 4, 4], reached_texts,
                                                                              strict=True)]
    assert min(b["s"] for b in beats["reached"]) >= 4  # (never 2.5 s for a 20-word line)
    closes = beats["closes"]
    assert len(closes) == 1 and closes[0]["cam"] == "view:goalboard" and closes[0]["who"] == w["result"]["title"]
    assert closes[0]["text"] == w["result"]["line"] and closes[0]["note"] == w["result"]["streak"]
    assert beats["opens"][0]["text"] == "A new day (UTC): the rings start again from zero."
    # the bill's rung on real money: the promenade's open stalls between the tower and Voss; another rung: no power beat
    assert [b["cam"] for b in out["billOn"]] == ["view:goaltower", "view:promenade", "voss"]
    assert out["billOn"][1]["text"] == wb["power_line"] and out["billOn"][1]["who"] == "THE PROMENADE"
    assert out["billOn"][1]["s"] >= 4 and [b["cam"] for b in out["zeroOn"]] == ["view:goaltower", "voss"]
    assert out["billOff"][1]["who"] == "THE OWNER'S BACKUP POWER" and out["billOff"][1]["text"] == w["power_line"]


@needs_node
def test_a_programme_never_shows_the_last_ones_words_while_the_drone_flies(module: str, tmp_path: Path) -> None:
    """The goal's programmes open on a board or a character (no title card): while the drone flies there the card says
    that first beat's tag, place and title, never the words of the programme before it (a stale real-money line)."""
    out = _node(_film(module) + """
const one = [filmBeat(0, "rook", 6, "THE GOAL · REAL MONEY", "1 of 1", "ROOK", "", "real")];
one[0].real = "Stopped for today after losing $3.11 (the limit is $3).";
progStart("goal", one, false); untilShown(); const first = shot();
const two = [filmBeat(0, "view:riskwall", 6, "THE GOAL · REAL MONEY", "1 of 2", "THE VAULT", "Real money stops for good after $10.", ""),
             filmBeat(1, "voss", 6, "THE GOAL · REAL MONEY", "2 of 2", "VOSS", "", "real")];
FLY.on = true; progStart("goal", two, false); run(0.3); const flying = shot(); FLY.on = false; untilShown(); const arrived = shot();
// the next beat: while the drone flies on to Voss, the card says his beat's tag, place and title, never the vault's words
run(5.4); FLY.on = true; run(0.9); const between = shot(); FLY.on = false; untilShown(); const second = shot();
console.log(JSON.stringify({ first: first, flying: flying, arrived: arrived, between: between, second: second }));
""", tmp_path)
    assert out["first"]["real"] == "Stopped for today after losing $3.11 (the limit is $3)." and out["first"]["cls"] == "real"
    flying = out["flying"]
    assert (flying["tag"], flying["prog"], flying["who"], flying["text"]) == ("THE GOAL · REAL MONEY", "1 of 2", "THE VAULT", "")
    assert flying["real"] is None and flying["pretend"] is None and flying["note"] is None and flying["cls"] == ""
    assert out["arrived"]["text"] == "Real money stops for good after $10." and out["arrived"]["shown"] == 0
    between = out["between"]
    assert (between["prog"], between["who"], between["text"]) == ("2 of 2", "VOSS", "")
    assert between["real"] is None and between["note"] is None and between["shown"] == 0
    assert out["second"]["shown"] == 1 and out["second"]["who"] == "VOSS"


def test_the_goal_chip_sits_first_after_live(section: str) -> None:
    chip = _fn(section, "goalChipMake")
    assert 'b.textContent = "goal"' in chip and "chips.insertBefore(b, chips.children[1] || null)" in chip
    assert 'if (FILM.on && FILM.kind === "goal") filmStop(true); else goalTour();' in chip
    step = _fn(section, "goalStep")
    assert 'const on = FILM.on && FILM.kind === "goal" ? "on" : "";' in step
    assert "if (!GOAL.chip && REC.chip) goalChipMake();" in step  # (after the record room's chips are made)


# --------------------------------------------------------------------------- the postcard, the sound, the copy


@needs_node
def test_the_postcard_burns_in_the_goal_line_never_the_token_or_address(module: str, records: str, section: str,
                                                                       states: dict[str, dict[str, Any]],
                                                                       tmp_path: Path) -> None:
    """plain.goal.postcard in gold between the real-money line and the practice line, whole; without it, nothing."""
    for word in (r"\btoken\b", r"\blocation\b", r"\bparams\b", r"\bURLSearchParams\b"):
        assert re.search(word, _code(section)) is None, word
    plain = states["stopped_today"]["plain"]
    out = _node(_helpers(module) + _js_body(module, "  function realWords(r) {") + "\n"
                + _line(records, "  const REC_FOOT = ") + "\n" + f"""
{_js_body(records, "  function recRealLine(r) {")}
{_js_body(records, "  function recPostcardLines(now) {")}
{_js_body(records, "  function recBurnIn(c, now) {")}
let plain = {json.dumps(plain)};
const c = canvas(1600, 2400); recBurnIn(c, new Date(2026, 9, 10, 20, 28)); const lines = REC.postcardLines, all = painted();
plain = Object.assign({{}}, plain, {{ goal: null }}); recBurnIn(c, new Date(2026, 9, 10, 20, 28));
const without = REC.postcardLines, rest = texts();
console.log(JSON.stringify({{ lines: lines, all: all, without: without, rest: rest }}));
""", tmp_path)
    goal_lines = out["lines"]["goal"]
    assert goal_lines and " ".join(goal_lines) == plain["goal"]["postcard"]
    drawn = [d["t"] for d in out["all"]]
    assert drawn.index(out["lines"]["real"][0]) < drawn.index(goal_lines[0]) < drawn.index(out["lines"]["practice"][0])
    assert {d["fill"] for d in out["all"] if d["t"] in goal_lines} == {"#ffcf7a"}
    assert out["without"]["goal"] == [] and not set(goal_lines) & set(out["rest"])
    for text in drawn:
        for bad in ("token", "http", "/world", "?", "undefined", "NaN"):
            assert bad not in text, (bad, text)


@needs_node
def test_no_audio_context_before_the_speaker_and_cues_follow_the_real_tier(module: str, section: str,
                                                                           tmp_path: Path) -> None:
    """The cues and the generator's hum use the channel's own context and master gain (null before the speaker's
    tap): nothing before it, nothing while the sound is off or the tab hidden; the section never makes a context."""
    code = _code(section)
    assert "AudioContext" not in code and "webkitAudioContext" not in code
    assert "S.out = function () { return master; };" in module
    assert "ctx: function () { return sound.context(); }, out: function () { return sound.out(); }" in module
    fns = "\n".join(_fn(section, n) for n in ("goalAudio", "goalTone", "goalRungAt", "goalCue", "goalHum",
                                               "goalChordStep"))
    out = _node(_pure(section) + f"""
const document = {{ visibilityState: "visible" }};
let made = 0, ctx = null, on = false;
const param = function () {{ return {{ value: 0, setValueAtTime: function () {{}}, exponentialRampToValueAtTime: function () {{}},
  setTargetAtTime: function () {{}} }}; }};
const fakeCtx = {{ currentTime: 1,
  createOscillator: function () {{ made += 1; return {{ frequency: {{}}, connect: function () {{}}, start: function () {{}}, stop: function () {{}} }}; }},
  createGain: function () {{ return {{ gain: param(), connect: function () {{}} }}; }},
  createBiquadFilter: function () {{ return {{ frequency: {{}}, connect: function () {{}} }}; }} }};
const window = {{ __skyport: {{ sound: {{ on: function () {{ return on; }}, ctx: function () {{ return ctx; }},
  out: function () {{ return ctx ? {{}} : null; }} }} }} }};
const GOAL = {{ g: {{ rungs: [{{ id: "zero" }}, {{ id: "bill" }}, {{ id: "goal" }}], tier: {{ rank: 1 }} }}, lastCue: "", sounds: 0,
  hum: null, chord: null, chordRank: null }};
const GOAL_LOOK = {{ generator: "on" }}, GP = {{ genAt: {{}} }}, camera = {{ position: {{ distanceTo: function () {{ return 3; }} }} }};
{fns}
const out = {{}};
goalCue({{ kind: "on", rung: {{ id: "bill" }} }}); goalHum(); goalChordStep(); out.before = [made, GOAL.lastCue];
ctx = fakeCtx; goalCue({{ kind: "on", rung: {{ id: "bill" }} }}); out.off = [made, GOAL.lastCue];
on = true; document.visibilityState = "hidden"; goalCue({{ kind: "on", rung: {{ id: "bill" }} }}); goalHum(); out.hidden = made;
document.visibilityState = "visible"; goalCue({{ kind: "reached" }}); out.reached = [made, GOAL.lastCue];
goalHum(); goalHum(); out.hum = made;
goalChordStep(); out.chord = made; goalChordStep(); out.same = made;
GOAL.g.tier.rank = 3; goalChordStep(); out.goal = made;
console.log(JSON.stringify(out));
""", tmp_path)
    assert out["before"] == [0, ""] and out["off"] == [0, ""] and out["hidden"] == 0
    assert out["reached"] == [6, "reached"]  # a three-note brass phrase, two partials a note
    assert out["hum"] == 7  # the hum: one oscillator, made once, after the speaker is on
    assert out["chord"] == 7 + 2 and out["same"] == 9  # an open fifth at rank 1, retuned only when the tier moves
    assert out["goal"] == 9 + 4  # the triad and the bell from the goal's rank
    pure = _pure(section)
    assert "if (rank < 0) return [110, 130.81, 164.81];" in pure  # a minor drone below zero
    assert "return rank >= goalRank ? [110, 138.59, 164.81, 880] : [110, 138.59, 164.81];" in pure


def _literals(code: str) -> Iterator[str]:
    yield from re.findall(r'"((?:[^"\\\n]|\\.)*)"', code)


def test_the_goal_copy_is_careful_and_red_is_real_money(section: str) -> None:
    """H6 and H8 on the section's own fixed copy: no gambler's words, no deadline, no chasing; the yard's colours
    (pretend money) never red; the goal keeps the same rules and the same size."""
    words = [s for s in _literals(_code(section)) if " " in s]
    assert len(words) > 30
    for text in words:
        assert not _BANNED.search(text), text
        assert "chase" not in text.lower() and "raise the" not in text.lower(), text
    yard = _fn(section, "goalDrawYard").lower()
    for red in _REDS:
        assert red not in yard, red
    assert "goal_blue" in yard and "goal_slate" in yard
    assert '"GOAL REACHED · same size"' in section  # (short: the strip says it whole on a phone)
    assert ("The goal changes no bet size, limit or rule. The team gets there only with a strategy that proves "
            "itself.") in section


def test_jet_nods_at_a_stop_loss(module: str) -> None:
    """P1: a loss cut at its stop is as planned (Jet nods; a shrug if the nod cannot play); a win still cheers."""
    closed = _js_body(module, "  function onClosed(t, live) {")
    assert ('if (pnl > 0) oneShot(a, "cheer");\n      else if (pnl < 0 && !(/^Stop-loss/.test(String(t.why || "")) && '
            'oneShot(a, "nod"))) oneShot(a, "shrug");') in closed


@needs_node
def test_jet_nod_runs_as_written(module: str, tmp_path: Path) -> None:
    closed = _js_body(module, "  function onClosed(t, live) {")
    start = closed.index("      if (pnl > 0) oneShot")
    branch = closed[start:closed.index('oneShot(a, "shrug");') + len('oneShot(a, "shrug");')]
    out = _node(f"""
function run(pnl, why, nodOk) {{
  const did = [], a = {{}}, t = {{ why: why }};
  const oneShot = function (x, name) {{ did.push(name); return name !== "nod" || nodOk; }};
  {branch}
  return did;
}}
console.log(JSON.stringify([run(0.03, "Settled", true), run(-0.4, "Stop-loss at 89c", true),
  run(-0.4, "Stop-loss at 89c", false), run(-0.4, "Settled: lost", true), run(0, "Settled", true)]));
""", tmp_path)
    assert out == [["cheer"], ["nod"], ["nod", "shrug"], ["shrug"], []]


# --------------------------------------------------------------------------- the fix round's own checks


_SCROLL_DOM = _PANEL_DOM + r"""
// the panel scrolls: its content is 60 px a paragraph; a layout clamps scrollTop to what the content allows
let _top = 0;
function lines(n) { let k = n.tag === "p" || n.tag === "h3" || n.tag === "li" || n.tag === "button" ? 1 : 0;
  n.children.forEach(function (c) { k += lines(c); }); return k; }
Object.defineProperty(panelEl, "scrollTop", { get: function () { return _top; },
  set: function (v) { _top = Math.max(0, Math.min(v, lines(panelBody) * 60 - 500)); } });
"""


@needs_node
def test_the_goal_panel_keeps_its_place_and_says_this_polls_figures(module: str, section: str,
                                                                    states: dict[str, dict[str, Any]],
                                                                    tmp_path: Path) -> None:
    """A phone reader scrolled down the goal panel stays there through every poll, even a scroll the page has not
    told anyone about yet (a slow frame: no scroll event before the poll lands): the page's own panel redraw leaves the
    goal's panel alone (it drew the short practice panel there, and the layout that followed reset the scroll), and
    the goal reads the place before it redraws. The panel says the poll that just landed, never the last one."""
    a, b = states["stopped_today"], states["tiny"]
    fns = "\n".join(_fn(section, n) for n in ("goalReset", "goalNowS", "goalLadder", "goalHead", "goalOf", "goalPanel",
                                               "goalOnScroll", "goalOnData"))
    out = _node(_pure(section) + _SCROLL_DOM + _js_body(module, "  function para(parent, text, cls) {") + f"""
let data = {json.dumps(a)}, panelKind = "goal", plain = data.plain;
const GOAL = {{ ok: true, seen: data, g: data.town.goal, w: data.plain.goal, phone: true, scroll: 0 }}, GOAL_LOOK = {{ ring: [] }};
const GOAL_CALM = false; let applied = 0;
const goalApply = function (d) {{ applied += 1; GOAL.g = d.town.goal; GOAL.w = d.plain.goal; }};
{_js_body(module, "  function renderPanel() {")}
{fns}
const first = function () {{ return panelBody.children[0].children[1].children[0].textContent; }};
goalPanel(data); const tall = lines(panelBody) * 60;
// the reader scrolls; the page has not dispatched the scroll event yet when the poll lands
panelEl.scrollTop = 770; const before = [panelEl.scrollTop, GOAL.scroll];
// a poll lands: the page's renderBar redraws the open panel, a layout follows (it clamps), then the bus says "data"
const poll = function (d) {{ data = d; plain = d.plain; renderPanel(); panelEl.scrollTop = panelEl.scrollTop; goalOnData(d);
  goalOnScroll(); }};
poll({json.dumps(b)}); const after = [panelEl.scrollTop, GOAL.scroll, first(), applied];
poll({json.dumps(b)}); const again = [panelEl.scrollTop, applied];
// the goal stopped (a fault): the panel still says this poll's own figures, never the stale ones
GOAL.ok = false; GOAL.g = {json.dumps(b["town"]["goal"])}; GOAL.w = {json.dumps(b["plain"]["goal"])};
poll({json.dumps(a)}); const stale = [first(), panelEl.scrollTop];
console.log(JSON.stringify({{ tall: tall, before: before, after: after, again: again, stale: stale }}));
""", tmp_path)
    assert out["tall"] > 1270 and out["before"] == [770, 0]  # (no scroll event yet: the goal had not heard of it)
    top, kept, line, applied = out["after"]
    assert top == kept == 770  # (the reader's place, after the poll)
    assert line == b["plain"]["goal"]["line"] and applied == 1  # (this poll's own words: applied before drawn)
    assert out["again"] == [770, 2]
    assert out["stale"] == [a["plain"]["goal"]["line"], 770]
    render = _js_body(module, "  function renderPanel() {")
    assert render.index('if (panelKind === "goal") return;') < render.index('panelBody.textContent = "";')
    onclick = _line(section, "  goalStrip.onclick = ")
    assert "GOAL.scroll = 0;" in onclick and "panelEl.scrollTop = 0;" in onclick  # (the strip opens it at its top)
    assert 'panelEl.addEventListener("scroll", goalOnScroll, { passive: true });' in section
    assert 'BUS.on("data", goalOnData);' in section


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _srgb(v: float) -> float:
    v = max(0.0, min(1.0, v))
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def _ring_rgb(hexcol: int, k: float, mix: float, dark: int) -> tuple[float, float, float]:
    """A ring's colour on screen as three.js paints it (sRGB hex to linear, mixed toward the dark ring, scaled, clipped
    by the screen: toneMapped false), back in sRGB."""
    def rgb(h: int) -> list[float]:
        return [_lin(((h >> s) & 255) / 255) for s in (16, 8, 0)]
    c, d = rgb(hexcol), rgb(dark)
    out = [(ci * (1 - mix) + di * mix) * k for ci, di in zip(c, d, strict=True)]
    r, g, b = (_srgb(v) for v in out)
    return r, g, b


@needs_node
def test_embers_are_dim_and_said_in_words(section: str, states: dict[str, dict[str, Any]], tmp_path: Path) -> None:
    """Today's snapshot (−$3.11, the two lowest rings reached earlier today): the embers glow far dimmer than any lit
    ring (a worse day never looks better), the gold and the violet stay their colour (never clipped to white), the pips
    and the ladder dots are dark ringed in amber, and the words say what amber means (panel, aria, tower beat)."""
    out = _node(_pure(section) + """
console.log(JSON.stringify({ tone: GOAL_TONE, col: GOAL_COL }));
""", tmp_path)
    tone, colours = out["tone"], out["col"]
    rgb = {s: _ring_rgb(colours[s], tone[s]["k"], tone[s]["mix"], colours["dark"]) for s in ("lit", "goal", "above",
                                                                                              "ember", "dark")}
    luma = {s: 0.2126 * r + 0.7152 * g + 0.0722 * b for s, (r, g, b) in rgb.items()}
    assert luma["ember"] < 0.5 * min(luma["lit"], luma["goal"], luma["above"]), luma
    assert luma["ember"] > luma["dark"]  # (still a mark: dimmer than lit, brighter than dark)
    r, g, b = rgb["above"]
    assert b - g > 0.08 and min(r, g, b) < 0.95  # (violet, not white)
    r, g, b = rgb["goal"]
    assert r - b > 0.25  # (gold, not white)
    assert tone["ember"]["mix"] > 0 and "_gc.lerp(_gd.set(GOAL_COL.dark), t.mix)" in _fn(section, "goalScene")
    for rule in ("#goal .gpips i.ember {", "#panel .grung.ember i {"):
        css = _line(_STYLE_GOAL, rule)
        assert "background: #3a4352" in css and "box-shadow: inset 0 0 0 1.5px" in css, css
    w = states["stopped_today"]["plain"]["goal"]
    assert "+$0.47" in w["ember_line"] and "Amber rings: reached earlier today, not lit now." in w["ember_line"]
    assert w["ember_line"] in w["aria"] and w["programmes"]["tour"][0]["text"].endswith(w["ember_line"])
    for name in ("tiny", "bill", "met", "off", "practice_only"):  # (no ember, no words about one)
        assert states[name]["plain"]["goal"]["ember_line"] is None, name


def _width(text: str, px: float, spacing_em: float = 0.0) -> float:
    """Helvetica Bold's widths (per 1000 em): a bold system font's width, about."""
    widths = {" ": 278, "!": 333, "(": 333, ")": 333, "+": 584, ",": 278, "-": 333, ".": 278, "/": 278, ":": 333,
              "$": 556, "·": 278, "−": 584, "'": 278, "%": 889}
    for ch in "0123456789":
        widths[ch] = 556
    upper = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", (722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833,
                                                     722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611),
                     strict=True))
    lower = dict(zip("abcdefghijklmnopqrstuvwxyz", (556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889,
                                                     611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500),
                     strict=True))
    widths |= upper | lower
    return sum(widths.get(ch, 611) for ch in text) / 1000 * px + len(text) * spacing_em * px


@needs_node
def test_the_strip_beat_fits_a_phone_and_quiet_beats_stay_quiet(section: str, states: dict[str, dict[str, Any]],
                                                                tmp_path: Path) -> None:
    """Beside a beat the strip shows the short figure, and every beat's words with it fit 300 px at the strip's 11 px
    bold (GOAL REACHED whole on a 360 px phone); under 340 px the label is the short one; a light gone dark and a
    stand-down are slate and still, never the brass glow of a win."""
    names = ["stopped_today", "tiny", "bill", "met", "double", "losing"]
    out = _node(_pure(section) + _STRIP_DOM + f"""
const GOAL = {{}}, GOAL_LOOK = {{ ring: [] }};
{_fn(section, "goalStripRender")}
const P = {json.dumps(_pages(states, names))}, out = {{ beats: [], figs: {{}} }};
Object.keys(P).forEach(function (n) {{
  const g = P[n].g, w = P[n].w;
  g.rungs.forEach(function (r) {{ ["on", "off"].forEach(function (k) {{ out.beats.push([n, goalBeatText({{ kind: k, rung: r }}, g, w), w.strip_figure_short]); }}); }});
  ["stand", "reached", "closes", "opens"].forEach(function (k) {{ out.beats.push([n, goalBeatText({{ kind: k, rung: null }}, g, w), w.strip_figure_short]); }});
  out.beats.push([n, goalBeatText({{ kind: "closes", rung: null, late: true }}, g, w), w.strip_figure_short]);
  out.beats.push([n, goalBeatText({{ kind: "stand", rung: null }}, Object.assign({{}}, g, {{ stand_down: "risk" }}), w), w.strip_figure_short]);
  GOAL.g = g; GOAL.w = w; GOAL.beatUntil = 0; goalLook(g, true, false, GOAL_LOOK); goalStripRender(); const full = goalFig.textContent;
  GOAL.beatUntil = 1234; goalStripRender(); out.figs[n] = [full, goalFig.textContent, goalLabel.textContent];
}});
window.innerWidth = 330; GOAL.beatUntil = 0; goalStripRender(); out.narrow = [goalLabel.textContent, goalFig.textContent];
console.log(JSON.stringify(out));
""", tmp_path)
    for name, text, fig in out["beats"]:
        width = _width(text, 11, 0.04) + 7 + _width(fig, 13)
        assert width <= 300, (name, text, round(width))
    for n in names:
        w = states[n]["plain"]["goal"]
        assert out["figs"][n] == [w["strip_figure"], w["strip_figure_short"], w["strip_label"]], n
    assert out["narrow"] == ["Goal $100", states["losing"]["plain"]["goal"]["strip_figure_short"]]
    quiet = _line(_STYLE_GOAL, "#goal.beat.quiet {")
    assert "box-shadow: none" in quiet and "animation: none" in quiet and "#8f9bb3" in quiet
    show = _fn(section, "goalBeatShow")
    assert 'goalStrip.classList.toggle("quiet", goalQuiet(kind));' in show
    assert 'goalStrip.classList.remove("quiet");' in _fn(section, "goalBeatEnd")
    # (the pips: the floor and "beyond" never give way; the rungs' pips shrink first; smaller on a 360 px phone)
    assert "flex-shrink: 0; order: 99;" in _line(_STYLE_GOAL, "#goal .gpips i.beyond {")
    assert "flex-shrink: 0;" in _line(_STYLE_GOAL, "#goal .gpips i.gfloor {")
    assert "flex: 0 1 8px; min-width: 4px;" in _line(_STYLE_GOAL, "#goal .gpips i {")
    assert "@media (max-width: 380px) { #goal .gpips { gap: 3px; }" in _STYLE_GOAL


@needs_node
def test_the_lights_follow_real_money_once_it_covered_the_bill(section: str, states: dict[str, dict[str, Any]],
                                                              tmp_path: Path) -> None:
    """One rule for the town's power: the plaque, the generator, the stalls and the lights all follow whether real
    money covered today's bill, even after real money is switched off (the tower stays dark: real money is off)."""
    g = copy.deepcopy(states["bill"]["town"]["goal"])
    off = dict(g, mood="off", tier={"id": "off", "rank": None, "name": "Real money is off"},
               rungs=[dict(r, lit=False, reached=False) for r in g["rungs"]])
    half = dict(off, power="backup", bill_covered_by_real=False, bill_share_real=0.5)
    on, o, h = _looks(section, [g, off, half], tmp_path)
    assert (on["generator"], on["stalls"], on["gold"]) == ("off", "open", 1)
    assert (o["generator"], o["stalls"], o["gold"], o["rings"], o["visitors"]) == ("off", "open", 1, 0, 0)
    assert (h["generator"], h["stalls"], h["gold"]) == ("on", "shut", 0)  # (a share while off: the owner's power)
    assert states["bill"]["plain"]["goal"]["plaque_line"] == "today: covered by real money"


def test_fireworks_are_sized_for_the_screen_and_burst_in_the_towers_view(section: str) -> None:
    build, move = _fn(section, "goalBuild"), _fn(section, "goalMove")
    assert "uPx: { value: 800 }" in build and "gl_PointSize = clamp(uPx * 0.16 / max(0.5, -mv.z), 2.0, 64.0);" in build
    assert "GP.fw.position.set(X, top + 1.2, Z);" in build and "* 1.6; p.y -= 0.25 * t * t;" in build
    assert ("GP.fw.material.uniforms.uPx.value = renderer.domElement.height * camera.projectionMatrix.elements[5] / 2;"
            in move)
    # the tower's view: framed between its tags (now on the rings' left, clear of the desk's board) and its rings
    assert 'recViewOf("goaltower", GP.towerAt, 2.1, 5.8, false, "table", 0.12);' in build
    assert "GP.tags.position.set(X - 0.82," in build and 'recViewOf("power", GP.genPlate, 1.8, 1.25, true, "kiosk", 0.3);' in build
    assert 'recViewOf("promenade", GP.promAt, 8.8, 3.3, true, null, 0.28);' in build


def test_visitors_are_townsfolk_and_keep_out_of_the_boards_views(section: str) -> None:
    spots = section[section.index("  const GOAL_SPOTS = "):section.index("  function goalBuild(")]
    places = [(float(x), float(z)) for x, z in re.findall(r"\[(-?\d+\.?\d*), (-?\d+\.?\d*)\]", spots)]
    assert len(places) == 21
    plaque = (-1.8, 11.5 + 0.325)
    assert all(math.hypot(x - plaque[0], z - plaque[1]) > 2.5 for x, z in places)  # (none by the bill plaque)
    for gone in ((2.2, 16.85), (-2.2, 16.8), (-0.95, 12.2)):
        assert gone not in places
    build, move = _fn(section, "goalBuild"), _code(_fn(section, "goalMove"))
    assert "GP.visHead = new THREE.InstancedMesh(" in build and "GP.visHat = new THREE.InstancedMesh(" in build
    assert "GP.visHead.setMatrixAt(i, GP.vm);" in move and "GP.visHat.setMatrixAt(i, GP.vm);" in move
    assert "const n = Math.min(L.visitors, GOAL_SPOTS.length)" in move


def test_the_bar_keeps_to_a_fifth_of_a_short_phone() -> None:
    """375x667 (an iPhone SE or 8) and 320x700: the strip, the bar's gaps and the headline are smaller; at 320 px the
    top row's four buttons keep apart (the screenshots measure it: under 146 px at 667 tall)."""
    assert ("@media (max-height: 700px) and (max-width: 759px) {\n  #goal { height: 24px; padding: 0 8px; }"
            in _STYLE_GOAL)
    assert "#bar { row-gap: 4px; padding-bottom: 10px; } #headline { font-size: 14px; line-height: 1.25; } }" in _STYLE_GOAL
    from nightcrawler.world3d import _STYLE
    narrow = _STYLE[_STYLE.index("@media (max-width: 340px) {"):]
    narrow = narrow[:narrow.index("} }") + 3]
    for rule in ("#bar .pill.real b { font-size: 13px;", "#bar .row1 > .pill.practice { font-size: 11px;",
                 "#bar .pill.sound, #bar .pill.help { width: 32px; }"):
        assert rule in narrow, rule
