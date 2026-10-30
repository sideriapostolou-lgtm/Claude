"""The displayed crew's pace, turns and arrivals, using the page's actual movement functions."""

from __future__ import annotations

import json
import shutil
import subprocess
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from nightcrawler import world3d

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


def _node(script: str, tmp_path: Path) -> dict[str, Any]:
    path = tmp_path / "movement.mjs"
    path.write_text(script)
    result = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=30, check=True)
    out: dict[str, Any] = json.loads(result.stdout)
    return out


def _between(start: str, end: str) -> str:
    source = world3d._M_LIFE
    return source[source.index(start):source.index(end, source.index(start))]


@pytest.fixture
def movement(tmp_path: Path) -> dict[str, Any]:
    three = (world3d.ASSET_DIR / "three.module.min.js").as_uri()
    parts = [
        _between("  function pathLength(", "  function visitNodeFor("),
        _between("  const WALK_RATE =", "  function startWalk("),
        _between("  const _wdir =", "  const _cp ="),
        _between("  function driveActor(", "  function cubeBetweenHands("),
    ]
    return _node(f"""
import * as THREE from {json.dumps(three)};
const V3 = (x, y, z) => new THREE.Vector3(x, y, z);
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const lerp = (a, b, t) => a + (b - a) * t;
const angleDiff = (a, b) => Math.atan2(Math.sin(a - b), Math.cos(a - b));
let simT = 0, focus = null;
const SPOTS = {{ room: {{ homeYaw: 0 }} }};
const facingCamera = () => false;
const endOneShot = () => {{ throw new Error("unexpected one-shot"); }};
{chr(10).join(parts)}
function actor(path, yaw = 0, pace = 1.8) {{
  return {{ key: "jet", pos: V3(...path[0]), path: path.map(p => V3(...p)), seg: 0,
    yaw, yawGoal: yaw, state: "out", speed: pace, moveSpeed: 0, groundSpeed: 0,
    destNode: "end", destRoom: "room", destYaw: Math.PI / 2, homeRoom: "room", homeNode: "start",
    action: {{ hold: 3, onArrive: a => {{ a.arrivals = (a.arrivals || 0) + 1; }} }} }};
}}
function tick(a, dt) {{
  simT += dt;
  if (a.path) stepWalk(a, dt);
  a.yaw += angleDiff(a.yawGoal, a.yaw) * (1 - Math.exp(-dt * (a.path ? 7 : 3)));
}}
const straight = actor([[0, 0, 0], [0, 0, 5]]), speeds = [];
for (let i = 0; straight.path && i < 1000; i++) {{ tick(straight, 1 / 60); speeds.push(straight.groundSpeed); }}
const backward = actor([[0, 0, 0], [0, 0, 5]], Math.PI);
for (let i = 0; i < 6; i++) tick(backward, 1 / 60);
const corner = actor([[0, 0, 0], [0, 0, 2], [2, 0, 2]]), bendSpeeds = [], errors = [];
for (let i = 0; corner.path && i < 1500; i++) {{
  tick(corner, 1 / 60);
  if (corner.pos.distanceTo(V3(0, 0, 2)) < 0.12) bendSpeeds.push(corner.groundSpeed);
  errors.push(corner.pos.x === 0 ? Math.abs(corner.pos.x) : Math.abs(corner.pos.z - 2));
}}
const paused = actor([[0, 0, 0], [0, 0, 2]], Math.PI), frozen = JSON.stringify(paused);
for (let i = 0; i < 120; i++) tick(paused, 0);
const pauseSame = frozen === JSON.stringify(paused);
const stairs = actor([[0, 0, 0], [0, 0, 0], [0, 1.8, 3], [0, 1.8, 3], [0, 1.8, 5]]);
for (let i = 0; stairs.path && i < 1500; i++) tick(stairs, 1 / 30);
const home = actor([[0, 0, 0], [0, 0, 2]]); home.state = "back";
for (let i = 0; home.path && i < 1000; i++) tick(home, 1 / 60);
const byFps = [30, 60, 120].map(fps => {{
  const a = actor([[0, 0, 0], [0, 0, 5]]); let frames = 0;
  while (a.path && frames++ < fps * 10) tick(a, 1 / fps);
  return {{ seconds: frames / fps, pos: a.pos.toArray(), arrivals: a.arrivals }};
}});
const gait = actor([[0, 0, 0], [0, 0, 5]]);
let rate = null, loop = null;
gait.actor = {{ spec: {{ kind: "biped", walk: "walk_quick" }}, hipsHeight: 0.5,
  library: {{ info: () => ({{ speed_hips_per_s: 1.476 }}) }},
  current: {{ setEffectiveTimeScale: value => {{ rate = value; }} }},
  play: name => {{ loop = name; }}, root: new THREE.Group(), lookAt: () => {{}}, reachTo: () => {{}}, update: () => {{}} }};
const gaitChecks = [];
for (let i = 0; i < 30; i++) {{
  const before = gait.pos.clone(); tick(gait, 1 / 60);
  driveActor(gait, {{ walking: true }}, 1 / 60);
  gaitChecks.push({{ feet: rate * 0.5 * 1.476, travel: before.distanceTo(gait.pos) * 60, loop }});
}}
console.log(JSON.stringify({{
  straight: {{ pos: straight.pos.toArray(), state: straight.state, arrivals: straight.arrivals,
    moveSpeed: straight.moveSpeed, speeds }},
  backward: {{ distance: backward.pos.length(), yaw: backward.yaw }},
  corner: {{ pos: corner.pos.toArray(), arrivals: corner.arrivals, bendSpeeds, maxRouteError: Math.max(...errors) }},
  pauseSame, stairs: {{ pos: stairs.pos.toArray(), arrivals: stairs.arrivals }}, byFps, gaitChecks,
  home: {{ pos: home.pos.toArray(), state: home.state, node: home.node, since: home.homeSince, arrivals: home.arrivals || 0 }}
}}));
""", tmp_path)


def test_departures_and_arrivals_ease_without_changing_destinations(movement: dict[str, Any]) -> None:
    trip = movement["straight"]
    speeds = trip["speeds"]
    assert 0 < speeds[0] < 0.15
    assert max(speeds) == pytest.approx(1.8)
    assert max(abs(b - a) for a, b in pairwise(speeds)) < 0.25
    assert max(speeds[-6:]) < 0.8
    assert trip["pos"] == pytest.approx([0, 0, 5])
    assert trip["state"] == "visit" and trip["arrivals"] == 1 and trip["moveSpeed"] == 0


def test_workers_face_the_route_and_slow_for_corners(movement: dict[str, Any]) -> None:
    assert movement["backward"]["distance"] < 0.02
    turn = movement["corner"]
    assert turn["bendSpeeds"] and min(turn["bendSpeeds"]) < 0.3
    assert max(turn["bendSpeeds"]) < 1.4
    assert turn["maxRouteError"] < 1e-9
    assert turn["pos"] == pytest.approx([2, 0, 2]) and turn["arrivals"] == 1


def test_paused_frames_and_stairs_keep_the_route_intact(movement: dict[str, Any]) -> None:
    assert movement["pauseSame"]
    assert movement["stairs"]["pos"] == pytest.approx([0, 1.8, 5])
    assert movement["stairs"]["arrivals"] == 1
    home = movement["home"]
    assert home["pos"] == [0, 0, 2] and home["state"] == "home" and home["node"] == "start"
    assert home["since"] > 0 and home["arrivals"] == 0
    trips = movement["byFps"]
    assert max(t["seconds"] for t in trips) - min(t["seconds"] for t in trips) < 0.15
    assert all(t["arrivals"] == 1 and t["pos"] == [0, 0, 5] for t in trips)


def test_walk_animation_matches_the_distance_actually_covered(movement: dict[str, Any]) -> None:
    for frame in movement["gaitChecks"]:
        assert frame["feet"] == pytest.approx(frame["travel"], abs=1e-9)
        assert frame["loop"] == "walk_quick"


def test_walk_changes_and_gesture_returns_preserve_loop_phase(tmp_path: Path) -> None:
    """Use the real Three mixer so a faded-out action must be re-enabled, without rewinding it."""
    assets = world3d.ASSET_DIR
    motion = (assets / "cast_motion.js").read_text().replace(
        'from "three"', f'from {json.dumps((assets / "three.module.min.js").as_uri())}',
    ).replace('from "./cast_rig.js"', f'from {json.dumps((assets / "cast_rig.js").as_uri())}')
    module = tmp_path / "cast_motion.mjs"
    module.write_text(motion)
    out = _node(f"""
import * as THREE from {json.dumps((assets / "three.module.min.js").as_uri())};
import {{ Actor }} from {json.dumps(module.as_uri())};
{_between("  function endOneShot(", "  function visitorOf(")}
const a = Object.create(Actor.prototype), model = new THREE.Group(); model.name = "body";
a.library = {{ info: name => ({{ loop: name !== "nod", walk: name.startsWith("walk") }}) }};
a.mixer = new THREE.AnimationMixer(model); a.actions = {{}}; a.current = null; a.oneShot = null;
a.time = 0; a.spec = {{ kind: "biped" }}; a._move = a._layers = a._blink = () => {{}};
for (const [name, seconds] of [["idle", 4], ["walk_quick", 3], ["walk_heavy", 5.5], ["nod", 2]]) {{
  const clip = new THREE.AnimationClip(name, seconds, [new THREE.NumberKeyframeTrack("body.position[x]", [0, seconds], [0, 0])]);
  a.actions[name] = a.mixer.clipAction(clip);
}}
a.play("walk_quick", 0); a.update(0.75);
a.play("walk_heavy", 0.2); const phase = a.current.time / 5.5;
a.play("idle", 0.2); a.update(1.2); a.play("nod", 0.2); a.update(0.3);
const pausedAt = a.current.time, disabled = !a.current.enabled;
a.update(1.55);
const resumedAt = a.current.time, enabled = a.current.enabled, shot = a.oneShot;
const legacy = {{ current: a.current, oneShot: a.actions.nod }};
legacy.current.enabled = false; legacy.current.paused = true;
endOneShot(legacy);
console.log(JSON.stringify({{ phase, disabled, pausedAt, resumedAt, enabled, shot,
  legacy: {{ time: legacy.current.time, enabled: legacy.current.enabled, paused: legacy.current.paused, shot: legacy.oneShot }} }}));
""", tmp_path)
    assert out["phase"] == pytest.approx(0.25)
    assert out["disabled"] and out["pausedAt"] > 1
    assert out["enabled"] and out["shot"] is None
    assert out["resumedAt"] == pytest.approx(out["pausedAt"] + 1.55)
    assert out["legacy"]["enabled"] and not out["legacy"]["paused"] and out["legacy"]["shot"] is None
    assert out["legacy"]["time"] == out["resumedAt"]
