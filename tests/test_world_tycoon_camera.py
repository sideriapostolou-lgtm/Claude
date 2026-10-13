"""Phone framing and camera ownership, using Three and the world's actual room anchors."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from nightcrawler import world3d
from nightcrawler.worldtycoon_camera import TYCOON_CAMERA

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


def _part(source: str, start: str, end: str) -> str:
    return source[source.index(start):source.index(end, source.index(start))]


def _run(tmp_path: Path, body: str, width: int = 390, height: int = 844, calm: bool = False,
         visuals: bool = False) -> dict[str, Any]:
    geometry = "\n".join([
        _part(world3d._M_SETUP, "  function roomFrame(", "  function prep("),
        _part(world3d._M_WORLD, "  const RF =", "  const blockers ="),
        _part(world3d._M_LIFE, "  const WS2 =", "  // ============================================================= THE ACTORS"),
        _part(world3d._M_LIFE, "  const LAMP_AT =", "  const lamps ="),
        _part(world3d._M_LIFE, "  const HEIGHT =", "\n"),
    ])
    script = f"""
import * as THREE from {json.dumps((world3d.ASSET_DIR / "three.module.min.js").as_uri())};
const V3 = (x, y, z) => new THREE.Vector3(x, y, z);
const ROOMS = {json.dumps(world3d.WORLD_ROOMS)}, CAST = {json.dumps(world3d.WORLD_CAST)};
{geometry}
const actors = Object.fromEntries(Object.entries(CAST).map(([key, a]) => [key, {{ homeRoom: a.room, height: HEIGHT[key], pos: NAV[SPOTS[a.room].home].p.clone() }}]));
const visualHeights = {json.dumps({'voss': 1.9, 'pip': 2.0, 'nyx': 1.35, 'rook': 2.8, 'mote': 1.6, 'jet': 1.6})};
const tycoonCastHeight = {"key => visualHeights[key]" if visuals else "undefined"};
if ({json.dumps(visuals)}) Object.keys(actors).forEach(key => actors[key].tycoonVisualHeight = visualHeights[key]);
const window = {{ innerWidth: {width}, innerHeight: {height}, matchMedia: () => ({{ matches: {json.dumps(calm)} }}) }};
const classes = new Set(), body = {{ classList: {{ toggle: (key, on) => on ? classes.add(key) : classes.delete(key) }} }};
const camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.08, 1800);
const cam = {{ pos: V3(0, 0, 0), look: V3(0, 0, 0) }}, user = {{ yaw: 0, pitch: 0, zoom: 1 }};
const FLY = {{ on: false }}, sky = {{ position: V3(0, 0, 0) }}, cloudU = {{ uCam: {{ value: V3(0, 0, 0) }} }};
const Q = {{ shadows: true }}, sunDir = V3(1, 2, 3).normalize();
const sun = {{ position: V3(0, 0, 0), target: {{ position: V3(0, 0, 0) }}, userData: {{}} }};
let tween = null, shotKey = "live";
{TYCOON_CAMERA}
const snap = () => ({{ position: camera.position.toArray(), quaternion: camera.quaternion.toArray(), projection: camera.projectionMatrix.toArray() }});
const projected = p => {{ const q = p.clone().project(camera); return [(q.x + 1) * window.innerWidth / 2, (1 - q.y) * window.innerHeight / 2, q.z]; }};
tycoonBounds(88, 164); tycoonCameraUpdate(1 / 60, 0);
{body}
"""
    path = tmp_path / "tycoon-camera.mjs"
    path.write_text(script)
    result = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=30, check=True)
    out: dict[str, Any] = json.loads(result.stdout)
    return out


@pytest.mark.parametrize(("width", "height"), [(390, 844), (320, 568), (1280, 800)])
def test_every_workstation_and_label_fits_the_visible_band(tmp_path: Path, width: int, height: int) -> None:
    out = _run(tmp_path, """
const labels = Object.fromEntries(Object.entries(LAMP_AT).map(([key, p]) => [key, projected(p.clone().add(V3(0, 2.2, 0)))]));
const workers = Object.fromEntries(Object.entries(actors).map(([key, a]) => [key, projected(a.pos.clone().add(V3(0, 1.4, 0)))]));
console.log(JSON.stringify({ labels, workers, state: tycoonCameraState() }));
""", width, height)
    assert "dock" in out["labels"] and "observatory" in out["labels"]
    for point in [*out["labels"].values(), *out["workers"].values()]:
        assert 28 <= point[0] <= width - 28
        assert 88 + 20 <= point[1] <= height - 164 - 20
        assert -1 < point[2] < 1


@pytest.mark.parametrize(("width", "height"), [(390, 844), (320, 568), (1280, 800)])
def test_real_pavilion_roofs_awnings_and_research_walls_fit_actual_phone_hud(
    tmp_path: Path, width: int, height: int,
) -> None:
    out = _run(tmp_path, """
tycoonBounds(181, 80); tycoonCameraUpdate(1, 0);
const corners = [];
// Measured outer geometry from the park, independent of the camera's padded fit.
Object.entries({workshop:[4.32,-4.18,5.075],den:[4.32,-4.18,5.075],
  archive:[4.07,-3.88,4.775],vault:[4.07,-3.88,4.775]}).forEach(([key, size]) => {
  for (const x of [-size[0],size[0]]) for (const z of [size[1],size[2]]) for (const y of [0,4.07])
    corners.push(projected(RF[key].at(x,y,z)));
});
for (let i=0;i<64;i++) for (const y of [0,4.1]) corners.push(projected(RF.observatory.at(
  5.75*Math.cos(i*Math.PI/32),y,5.75*Math.sin(i*Math.PI/32))));
for (const x of [20.10,26.34]) for (const z of [-3.35,.35]) for (const y of [0,4.06]) corners.push(projected(V3(x,y,z)));
const cast = Object.fromEntries(Object.entries(actors).map(([key,a]) => {
  const foot=projected(a.pos), head=projected(a.pos.clone().add(V3(0,tycoonCastHeight(key),0)));
  return [key,{foot,head,pixels:foot[1]-head[1]}];
}));
console.log(JSON.stringify({corners,cast,state:tycoonCameraState()}));
""", width, height, visuals=True)
    for point in out["corners"]:
        assert 20 <= point[0] <= width - 20
        assert 181 + 20 <= point[1] <= height - 80 - 20
        assert -1 < point[2] < 1
    # Every resident remains visible in the full overview. Station visits carry
    # the readable close-up; the town cannot turn into a cropped portrait.
    for actor in out["cast"].values():
        assert actor["pixels"] >= 7
        assert 20 <= actor["head"][0] <= width - 20
    if width == 390:
        assert out["cast"]["jet"]["pixels"] >= 10
        assert out["cast"]["rook"]["pixels"] >= 19


@pytest.mark.parametrize(("width", "height"), [(390, 844), (320, 568)])
def test_selected_camera_fits_enlarged_cast_without_moving_their_home_nodes(
    tmp_path: Path, width: int, height: int,
) -> None:
    out = _run(tmp_path, """
tycoonBounds(181, 210);
const homes = Object.fromEntries(Object.entries(actors).map(([key,a])=>[key,a.pos.toArray()]));
const views = Object.fromEntries(Object.entries(actors).map(([key,a]) => {
  tycoonSelect(key); tycoonCameraUpdate(1,0);
  const foot=projected(a.pos), head=projected(a.pos.clone().add(V3(0,tycoonCastHeight(key),0)));
  return [key,{foot,head,home:a.pos.toArray()}];
}));
console.log(JSON.stringify({homes,views}));
""", width, height, visuals=True)
    for key, view in out["views"].items():
        assert view["home"] == out["homes"][key]
        assert view["foot"][1] - view["head"][1] >= (36 if width == 320 else 60)
        for point in (view["foot"], view["head"]):
            assert 20 <= point[0] <= width - 20
            assert 181 + 20 <= point[1] <= height - 210 - 20


def test_selected_workers_are_readable_from_the_front_inside_phone_controls(tmp_path: Path) -> None:
    out = _run(tmp_path, """
tycoonBounds(173, 260);
const views = Object.fromEntries(Object.entries(actors).map(([key, a]) => {
  tycoonSelect(key); tycoonCameraUpdate(1, 0);
  const home = NAV[SPOTS[a.homeRoom].home].p, yaw = SPOTS[a.homeRoom].homeYaw;
  const feet = projected(home), head = projected(home.clone().add(V3(0, a.height, 0)));
  const viewDirection = camera.position.clone().sub(home).setY(0).normalize();
  const facing = viewDirection.dot(V3(Math.sin(yaw), 0, Math.cos(yaw)));
  return [key, { feet, head, facing }];
}));
console.log(JSON.stringify({ views }));
""")
    for view in out["views"].values():
        assert view["feet"][1] - view["head"][1] >= 45
        assert view["facing"] > 0.8
        for point in (view["feet"], view["head"]):
            assert 32 <= point[0] <= 390 - 32
            assert 173 + 20 <= point[1] <= 844 - 260 - 20


def test_view_stays_fixed_through_events_and_selected_worker_movement(tmp_path: Path) -> None:
    out = _run(tmp_path, """
const first = snap();
for (let i = 0; i < 3600; i++) tycoonCameraUpdate(1 / 60, i / 60);
const later = snap();
tycoonSelect("pip");
const before = snap(); tycoonCameraUpdate(0, 60); const paused = snap();
for (let i = 0; i < 42; i++) tycoonCameraUpdate(1 / 60, 60 + i / 60);
const selected = snap();
actors.pip.pos.set(100, 40, 100); actors.pip.room = "vault";
for (let i = 0; i < 3600; i++) { FLY.on = true; tween = { t: i }; tycoonCameraUpdate(1 / 60, 61 + i / 60); }
console.log(JSON.stringify({ first, later, before, paused, selected, after: snap(), state: tycoonCameraState(), flight: FLY.on, tween }));
""")
    assert out["first"] == out["later"]
    assert out["before"] == out["paused"]
    assert out["selected"] != out["first"] and out["selected"] == out["after"]
    assert out["state"]["selected"] == "pip" and out["state"]["room"] == "workshop"
    assert out["state"]["settled"] and not out["flight"] and out["tween"] is None


def test_pan_and_zoom_stay_where_the_viewer_put_them_and_cinema_is_restored(tmp_path: Path) -> None:
    out = _run(tmp_path, """
const overview = snap();
user.yaw = 0.3; user.pitch = -0.15; user.zoom = 0.75; tycoonCameraUpdate(1 / 60, 0);
const touched = snap(); for (let i = 0; i < 3600; i++) tycoonCameraUpdate(1 / 60, i / 60);
const held = snap();
tycoonSelect(null); tycoonCameraUpdate(0, 61); const recenterStart = snap();
tycoonCameraUpdate(1, 62); const recentered = snap();
tycoonEnable(false); const cinema = snap(), restoredFov = camera.fov, viewEnabled = camera.view.enabled;
const handled = tycoonCameraUpdate(1 / 60, 1000), untouched = snap();
tycoonEnable(true); tycoonSelect("dock"); tycoonCameraUpdate(1, 1001);
tycoonSelect(null); tycoonCameraUpdate(1, 1002);
console.log(JSON.stringify({ overview, touched, held, recenterStart, recentered, cinema, untouched, handled, restoredFov, viewEnabled,
  returned: snap(), state: tycoonCameraState(), invalid: tycoonSelect("missing") }));
""")
    assert out["touched"] != out["overview"] and out["touched"] == out["held"]
    assert out["recenterStart"] == out["held"] and out["recentered"] == out["overview"]
    assert not out["handled"] and out["cinema"] == out["untouched"]
    assert out["restoredFov"] == 55 and not out["viewEnabled"]
    assert out["returned"] == out["overview"] and out["state"]["selected"] is None
    assert not out["invalid"]


def test_reduced_motion_selects_a_station_without_flying(tmp_path: Path) -> None:
    out = _run(tmp_path, """
const overview = snap(); tycoonSelect("rook"); tycoonCameraUpdate(0, 1);
const selected = snap(), state = tycoonCameraState(); tycoonCameraUpdate(10, 100);
console.log(JSON.stringify({ overview, selected, state, later: snap(), roomPoint: projected(NAV[SPOTS.vault.home].p) }));
""", calm=True)
    assert out["selected"] != out["overview"] and out["selected"] == out["later"]
    assert out["state"]["selected"] == "rook" and out["state"]["settled"]
    assert 32 < out["roomPoint"][0] < 390 - 32 and 88 < out["roomPoint"][1] < 844 - 164
