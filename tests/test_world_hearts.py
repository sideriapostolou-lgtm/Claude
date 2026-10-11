"""The 3D world's hearts (world3d's THE HEARTS section and the card's heart row): the card shows each character's mood
and heart line as text only; the mood moves the body through the move library only and only while the member is idle
of the director's own beats; the huddle is a goal beat that fires only for a real settlement new since the last poll and
films the tower, then Voss's heart; the guide has the hearts card; red stays real money's; the director is untouched."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from nightcrawler.config import Settings
from nightcrawler.world3d import _STYLE_HEARTS, ASSET_DIR, render_world_html
from tests import goal_states as GS
from tests import heart_states as HS
from tests.test_world3d import _js_body, _module, _node
from tests.test_world_records import _REDS

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
_HEADER, _DIRECTOR = "= THE HEARTS (team hearts)", "= THE LIVE DIRECTOR: an always-on broadcast"


@pytest.fixture(scope="module")
def page() -> str:
    return render_world_html(Settings.from_env({"DATA_DIR": "/tmp/nightcrawler-world-hearts-test"}))


@pytest.fixture(scope="module")
def module(page: str) -> str:
    return _module(page)


@pytest.fixture(scope="module")
def section(module: str) -> str:
    return module[module.index(_HEADER):module.index(_DIRECTOR)]


@pytest.fixture(scope="module")
def states() -> dict[str, dict[str, Any]]:
    base = GS.base_page()
    return {name: HS.apply_heart_state(base, name) for name in HS.HEART_STATES}


def _fn(source: str, name: str) -> str:
    return _js_body(source, f"  function {name}(")


def test_the_section_sits_after_the_goal_and_leaves_the_director_alone(page: str, module: str, section: str) -> None:
    assert module.index("= THE GOAL (town goal)") < module.index(_HEADER) < module.index(_DIRECTOR)
    director = module[module.index(_DIRECTOR):module.index("= THE LOOP (paused")]
    for name in ("HEART", "heartsStep", "heartsGather", "heartsOnData", "heartOf", "heartRow"):
        assert re.search(r"\b" + name + r"\b", director) is None, name
    code = re.sub(r"//[^\n]*", "", section)
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "new Function", "document.write",
                 "localStorage", "focusOn(", "togglePin(", "PLANNER.", "speak(", "BUS.emit(", "progStart("):
        assert sink not in code, sink
    assert 'BUS.on("data", heartsOnData);' in code and 'BUS.on("frame", heartsStep);' in code
    # the huddle is the goal's own beat: its programme through goalPlay's progStart("goal"), its walk when it starts
    assert 'if (beat.kind === "huddle") return heartsHuddleScript(beat);' in module
    assert 'if (beat.kind === "huddle") heartsGather();' in _fn(module, "goalPlay")
    assert 'if (beat.kind === "huddle") return "HUDDLE · at the goal tower";' in module
    # its CSS in the page's one style: the mood colours are never real money's red
    (style,) = re.findall(r"<style>(.*?)</style>", page, flags=re.DOTALL)
    assert _STYLE_HEARTS in style
    for red in _REDS:
        assert red not in _STYLE_HEARTS.lower(), red
    for mood in ("proud", "determined", "worried", "hurting", "hopeful", "calm", "relieved"):
        assert f".heart.mood-{mood} b {{" in _STYLE_HEARTS, mood


def test_the_moods_play_only_the_move_library(section: str) -> None:
    manifest = json.loads((ASSET_DIR / "cast_manifest.json").read_text(encoding="utf-8"))["clips"]
    moves = json.loads(re.search(r"const HEART_MOVES = (\{.*?\});", section, re.DOTALL).group(1)  # type: ignore[union-attr]
                       .replace("proud:", '"proud":').replace("worried:", '"worried":').replace("hurting:", '"hurting":')
                       .replace("hopeful:", '"hopeful":').replace("calm:", '"calm":').replace("relieved:", '"relieved":'))
    assert moves == {"proud": ["cheer", "nod"], "worried": ["worried", "think"], "hurting": ["shrug", "worried"],
                     "hopeful": ["look", "wave"], "calm": ["idle", "drink"], "relieved": ["drink", "idle"]}
    loops = {"look", "idle", "drink"}
    for pair in moves.values():
        for name in pair:
            assert name in manifest and bool(manifest[name]["loop"]) == (name in loops), name
    assert manifest["walk_quick"]["loop"] and 'a.action.quick && (a.state === "out" || a.state === "back") ? "walk_quick"' in (
        section + _js_body(_module(render_world_html(Settings.from_env({"DATA_DIR": "/tmp/x"}))), "  function walkClip("))
    assert "const HEART_LOOPS = { look: true, idle: true, drink: true };" in section


@needs_node
def test_the_card_shows_the_heart_as_text(module: str, states: dict[str, dict[str, Any]], tmp_path: Path) -> None:
    rows = _js_body(module, "  function heartOf(key) {") + "\n" + _js_body(module, "  function heartRow(rows, h) {")
    out = _node(r"""
function mk(tag) { return { tag: tag, className: "", textContent: "", children: [], appendChild: function (c) { this.children.push(c); return c; } }; }
const document = { createElement: mk };
let plain = PLAIN;
""".replace("PLAIN", json.dumps(states["losing_big"]["plain"])) + rows + r"""
const box = mk("div"); heartRow(box, heartOf("voss")); heartRow(box, heartOf("rook"));
plain = { hearts: { members: [{ id: "voss", mood: "proud", line: "<img src=x onerror=alert(1)>" }, { id: "pip", mood: "<b>", line: "x" }] } };
const evil = mk("div"); heartRow(evil, heartOf("voss")); const none = heartRow(evil, heartOf("pip")); heartRow(evil, heartOf("nobody"));
console.log(JSON.stringify({ rows: box.children.map(function (d) { return [d.className, d.children.map(function (c) { return c.textContent; })]; }),
  evil: evil.children.map(function (d) { return d.children.map(function (c) { return c.textContent; }); }), none: none }));
""", tmp_path)
    assert out["rows"][0] == ["heart mood-hurting", ["♥ hurting", " · That miss cost the town $9.80. I owe it steadier hands."]]
    assert out["rows"][1][0] == "heart mood-worried" and "about $9.70" in out["rows"][1][1][1]
    assert out["evil"] == [["♥ proud", " · <img src=x onerror=alert(1)>"]] and out["none"] is None  # (text only)
    card = _js_body(module, "  function renderCard() {")
    assert "heartRow(rows, heartOf(actor ? actor.key : t.id));" in card and "innerHTML" not in card


@needs_node
def test_the_huddle_fires_only_for_a_real_settlement_new_since_the_last_poll(module: str, section: str,
                                                                            states: dict[str, dict[str, Any]],
                                                                            tmp_path: Path) -> None:
    on_data = _fn(section, "heartsOnData")
    nod = re.search(r"  const HEART_NOD = \{.*?\};", section).group(0)  # type: ignore[union-attr]
    pre, win, loss = (states[n] for n in ("winning_pre", "winning", "losing_big"))
    out = _node(f"""
let simT = 0; const ACTOR_KEYS = ["voss", "pip", "nyx", "rook", "mote", "jet"];
const GOAL = {{ g: {{ day: "2026-10-10" }}, queue: [] }};
const goalQueue = function (q, beat) {{ q.push(beat); return q; }};
const HEART = {{ h: null, mood: {{}}, next: {{}}, turn: {{}}, seen: false, last: "", lastTs: 0, tick: 0, i: 0, huddles: 0, gathered: 0 }};
const isNum = function (v) {{ return typeof v === "number" && isFinite(v); }};
{nod}
{on_data}
const seen = [];
[{json.dumps(win)}, {json.dumps(win)}, {json.dumps(pre)}, {json.dumps(win)}, {json.dumps(loss)}, {{ plain: {{ hearts: null }} }}, {json.dumps(loss)}]
  .forEach(function (d) {{ heartsOnData(d); seen.push(GOAL.queue.length); }});
console.log(JSON.stringify({{ seen: seen, kinds: GOAL.queue.map(function (b) {{ return [b.kind, b.huddle.result]; }}), moods: HEART.mood }}));
""", tmp_path)
    # the first poll never huddles (it settled before the visit); the same settlement again is not new, nor an older
    # one; a later one is; a poll without hearts forgets nothing (the same loss after it is not new)
    assert out["seen"] == [0, 0, 0, 0, 1, 1, 1]
    assert out["kinds"] == [["huddle", "lost"]]
    assert out["moods"] == {"voss": "hurting", "pip": "determined", "nyx": "determined", "rook": "worried",
                            "mote": "calm", "jet": "determined"}


@needs_node
def test_the_body_language_waits_for_the_directors_beats(section: str, tmp_path: Path) -> None:
    free = _fn(section, "heartsFree")
    out = _node(f"""
let simT = 100, pinned = null, focus = null;
const worstStatus = function (ids) {{ return ids[0] || "idle"; }};
{free}
const base = function () {{ return {{ key: "voss", state: "home", queue: [], carrying: null, speaking: false, listening: false, beats: [],
  actor: {{ oneShot: null }}, homeSince: 0, members: ["idle"] }}; }};
const cases = [base()];
let a = base(); a.speaking = true; cases.push(a);
a = base(); a.queue.push({{}}); cases.push(a);
a = base(); a.beats.push({{}}); cases.push(a);
a = base(); a.actor.oneShot = {{}}; cases.push(a);
a = base(); a.state = "visit"; cases.push(a);
a = base(); a.members = ["blocked"]; cases.push(a);
a = base(); a.homeSince = 95; cases.push(a);
const r = cases.map(heartsFree);
pinned = "voss"; r.push(heartsFree(base())); pinned = null;
focus = {{ actor: null, until: 200 }}; const f = base(); focus.actor = f; r.push(heartsFree(f));
console.log(JSON.stringify(r));
""", tmp_path)
    assert out == [True, False, False, False, False, False, False, False, False, False]
    step = _fn(section, "heartsStep")
    assert "if (!HEART.h || FILM.on || !ACTOR_KEYS.length) return;" in step  # (never during a programme)
    assert "!heartsFree(a)" in step and "!heartsWalking()" in step


def test_the_huddle_programme_is_the_tower_then_voss(section: str) -> None:
    script = _fn(section, "heartsHuddleScript")
    assert 'const list = [["tower", 6, GOAL_REAL, hud.line,' in script
    assert 'if (voss && voss.line) list.push(["voss", 7, GOAL_REAL, voss.line,' in script
    assert 'out[0].who = "THE HUDDLE · THE GOAL TOWER";' in script
    gather = _fn(section, "heartsGather")
    assert "if (!SPOTS[dest] || a.carrying) continue;" in gather  # (a trade's cube is delivered first)
    assert "const HEART_HUDDLE_S = 14" in section


def test_the_guide_has_the_hearts_card(page: str, module: str) -> None:
    assert '<section class="gcard"><h2>The team\'s hearts</h2><div id="guide-hearts"></div></section>' in page
    assert page.index('id="guide-goal"') < page.index('id="guide-hearts"') < page.index('id="guide-camera"')
    assert 'heartsGuide(el("guide-hearts"));' in _js_body(module, "  function renderGuide() {")
    guide = _js_body(module, "  function heartsGuide(box) {")
    assert "m.temperament" in guide and "m.why" in guide and "innerHTML" not in guide
