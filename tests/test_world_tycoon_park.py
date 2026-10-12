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
    assert out["active"]["on"] and 0 < out["active"]["meshes"] <= 3
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
