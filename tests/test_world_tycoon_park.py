"""The park skin must preserve navigation and disappear cleanly for the original camera tour."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from nightcrawler import world3d
from nightcrawler.worldtycoon_park import TYCOON_PARK

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


def _part(source: str, start: str, end: str) -> str:
    return source[source.index(start):source.index(end, source.index(start))]


def _run(tmp_path: Path, body: str) -> dict[str, Any]:
    three = (world3d.ASSET_DIR / "three.module.min.js").as_uri()
    utils = tmp_path / "geometry-utils.mjs"
    utils.write_text((world3d.ASSET_DIR / "addons/utils/BufferGeometryUtils.js").read_text().replace(
        "from 'three'", f"from {json.dumps(three)}"
    ))
    geometry = "\n".join([
        _part(world3d._M_SETUP, "  const V3 =", "  // shapes ("),
        _part(world3d._M_SETUP, "  function roomFrame(", "  function worldUV("),
        _part(world3d._M_WORLD, "  const COURT_R =", "  const blockers ="),
        _part(world3d._M_WORLD, "  const DISCS =", "  const onIsland ="),
        _part(world3d._M_LIFE, "  const WS2 =", "  // ============================================================= THE ACTORS"),
    ])
    script = f"""
import * as THREE from {json.dumps(three)};
import {{ mergeGeometries }} from {json.dumps(utils.as_uri())};
const ROOMS = {json.dumps(world3d.WORLD_ROOMS)}, scene = new THREE.Scene(), Q = {{ shadows: true }};
{geometry}
{TYCOON_PARK}
const nav = () => JSON.stringify(Object.fromEntries(Object.entries(NAV).map(([key, n]) => [key, [n.p.toArray(), n.edges]])));
{body}
"""
    path = tmp_path / "park.mjs"
    path.write_text(script)
    result = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=30, check=True)
    out: dict[str, Any] = json.loads(result.stdout)
    return out


def test_park_toggles_without_changing_existing_scene_or_routes(tmp_path: Path) -> None:
    out = _run(tmp_path, """
const original = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshStandardMaterial({ color: 0x483525 }));
original.position.set(4, 2, 6); scene.add(original);
const before = JSON.stringify(original.toJSON()), paths = nav();
tycoonPark(false); const lazy = tycoonParkState();
tycoonPark(true); const active = tycoonParkState(), group = TYCOON_PARK_STATE.group;
for (let i = 0; i < 25; i++) { tycoonPark(false); tycoonPark(true); }
const reused = group === TYCOON_PARK_STATE.group, total = scene.children.length;
tycoonPark(false);
console.log(JSON.stringify({ lazy, active, reused, total, hidden: !group.visible, pathsUntouched: nav() === paths,
  originalUntouched: before === JSON.stringify(original.toJSON()), final: tycoonParkState() }));
""")
    assert out["lazy"]["meshes"] == 0
    # Four merged scenery batches and five independently earned terrace gardens.
    assert out["active"]["on"] and 0 < out["active"]["meshes"] <= 9
    assert set(out["active"]["departments"]) == set(world3d.WORLD_ROOMS)
    assert out["reused"] and out["total"] == 2 and out["hidden"]
    assert out["pathsUntouched"] and out["originalUntouched"] and not out["final"]["on"]


def test_park_keeps_feet_shadows_stairs_and_door_routes_clear(tmp_path: Path) -> None:
    out = _run(tmp_path, """
tycoonPark(true); scene.updateMatrixWorld(true);
const ground = TYCOON_PARK_STATE.group.children.find(m => m.name === "tycoon:lawns-and-paving");
const ray = new THREE.Raycaster(), heights = {};
for (const [key, spot] of Object.entries(SPOTS)) {
  if (!ROOMS[key]) continue;
  const p = NAV[spot.home].p;
  ray.set(p.clone().add(new THREE.Vector3(0, 10, 0)), new THREE.Vector3(0, -1, 0));
  const hit = ray.intersectObject(ground)[0]; heights[key] = hit ? hit.point.y - p.y : null;
}
const matchesWalkGraph = TYCOON_PARK_STATE.routes.every(([a, b]) => NAV[a].edges.includes(b) && Math.abs(NAV[a].p.y - NAV[b].p.y) < .05);
let clearance = Infinity;
for (const flag of TYCOON_PARK_STATE.flags) {
  const p = new THREE.Vector3().fromArray(flag.position), closest = new THREE.Vector3();
  for (const [a, b] of TYCOON_PARK_STATE.routes) {
    if (Math.abs(NAV[a].p.y - p.y) > .1) continue;
    new THREE.Line3(NAV[a].p, NAV[b].p).closestPointToPoint(p, true, closest);
    clearance = Math.min(clearance, closest.distanceTo(p));
  }
}
const position = ground.geometry.attributes.position;
console.log(JSON.stringify({ heights, matchesWalkGraph, clearance, finite: Array.from(position.array).every(Number.isFinite),
  triangles: ground.geometry.index.count / 3, routes: TYCOON_PARK_STATE.routes.length }));
""")
    assert out["matchesWalkGraph"] and out["routes"] > 20 and out["finite"]
    assert out["clearance"] > 0.5
    assert out["triangles"] < 5000
    for height in out["heights"].values():
        assert height is not None and 0 <= height < 0.012


def test_only_qualified_daily_real_profit_reveals_earned_gardens(tmp_path: Path) -> None:
    out = _run(tmp_path, """
tycoonPark(true);
const show = (growth) => { tycoonParkApply({ growth }); return tycoonParkState(); };
const before = tycoonParkState();
const earned = show({ qualified: true, level: 3, pnl_usd: 1.25 });
const loss = show({ qualified: true, level: 1, pnl_usd: .12 });
const midnight = show({ qualified: true, level: 0, pnl_usd: 0 });
const stale = show({ qualified: false, level: 5, pnl_usd: 100 });
const malformed = show({ qualified: true, level: 12, pnl_usd: 100 });
tycoonParkApply({ cash: 1000, practice: { result: 5000 } });
const unrelated = tycoonParkState();
console.log(JSON.stringify({ before, earned, loss, midnight, stale, malformed, unrelated }));
""")
    assert out["before"]["earnedGardens"] == 0
    assert out["earned"]["earnedGardens"] == 3
    assert out["loss"]["earnedGardens"] == 1
    assert out["midnight"]["earnedGardens"] == 0
    for key in ("stale", "malformed", "unrelated"):
        assert out[key]["earnedGardens"] == 0
        assert not out[key]["growth"]["qualified"]
        assert out[key]["growth"]["pnl_usd"] is None


def test_utc_and_practice_props_are_excluded_from_daily_town_then_restored(tmp_path: Path) -> None:
    out = _run(tmp_path, """
const camera = new THREE.PerspectiveCamera();
const GP = { rings: new THREE.Mesh(), yard: new THREE.Mesh(), stalls: [{ shutter: new THREE.Mesh(), goods: new THREE.Mesh() }] };
GP.yard.layers.set(1);
const TP = { houses: new THREE.Mesh(), rings: [{ m: new THREE.Mesh() }] };
const nodes = [GP.rings, GP.yard, GP.stalls[0].shutter, TP.houses, TP.rings[0].m];
const masks = nodes.map(n => n.layers.mask);
tycoonPark(true);
const excluded = nodes.every(n => !n.layers.test(camera.layers));
// Existing financial animation can update visible without exposing the wrong money book.
nodes.forEach(n => { n.visible = true; });
const stillExcluded = nodes.every(n => !n.layers.test(camera.layers));
tycoonPark(false);
console.log(JSON.stringify({ excluded, stillExcluded, restored: nodes.every((n, i) => n.layers.mask === masks[i]) }));
""")
    assert out == {"excluded": True, "stillExcluded": True, "restored": True}


def test_connected_land_has_bounded_geometry_and_original_floor_clearance(tmp_path: Path) -> None:
    out = _run(tmp_path, """
tycoonPark(true);
const group = TYCOON_PARK_STATE.group;
const triangles = group.children.reduce((sum, m) => sum + (m.geometry.index ? m.geometry.index.count / 3 : m.geometry.attributes.position.count / 3), 0);
const ray = new THREE.Raycaster(new THREE.Vector3(18, 10, 14), new THREE.Vector3(0, -1, 0));
const hit = ray.intersectObjects(group.children).find(h => h.object.name === 'tycoon:lawns-and-paving');
console.log(JSON.stringify({ triangles, lawn: hit && hit.point.y, finite: group.children.every(m => Array.from(m.geometry.attributes.position.array).every(Number.isFinite)) }));
""")
    assert out["finite"]
    assert out["triangles"] < 20000
    assert -0.16 < out["lawn"] < 0


def test_building_taps_follow_actual_floor_coordinates(tmp_path: Path) -> None:
    out = _run(tmp_path, """
const camera = new THREE.PerspectiveCamera(42, 1, .1, 1000);
camera.position.set(45, 70, 65); camera.lookAt(0, 0, 0); camera.updateMatrixWorld(true);
const renderer = { domElement: { getBoundingClientRect: () => ({left:0,top:0,right:600,bottom:600,width:600,height:600}) } };
const project = p => { const q = p.clone().project(camera); return [(q.x + 1) * 300, (1 - q.y) * 300]; };
tycoonPark(true);
const picks = {};
for (const [room, who] of Object.entries({workshop:'pip',den:'nyx',archive:'mote',vault:'rook',observatory:'observatory'})) {
  picks[who] = tycoonParkPick(...project(RF[room].origin));
}
picks.voss = tycoonParkPick(...project(new THREE.Vector3(0,0,0)));
picks.jet = tycoonParkPick(...project(new THREE.Vector3(23.2,0,-1.5)));
const outside = tycoonParkPick(-100,20);
const lawn = tycoonParkPick(...project(new THREE.Vector3(22,0,17)));
tycoonPark(false); const hidden = tycoonParkPick(...project(RF.workshop.origin));
console.log(JSON.stringify({picks, outside, lawn, hidden}));
""")
    assert out["picks"] == {key: key for key in (
        "pip", "nyx", "mote", "rook", "observatory", "voss", "jet",
    )}
    assert out["outside"] is None
    assert out["lawn"] is None
    assert out["hidden"] is None
