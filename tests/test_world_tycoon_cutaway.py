"""The real room shells open for town viewing without changing their cinema or navigation geometry."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from nightcrawler import world3d

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


def _part(source: str, start: str, end: str) -> str:
    return source[source.index(start):source.index(end, source.index(start))]


def _run(tmp_path: Path, body: str) -> dict[str, Any]:
    three = (world3d.ASSET_DIR / "three.module.min.js").as_uri()
    utils = (world3d.ASSET_DIR / "addons/utils/BufferGeometryUtils.js").read_text()
    utils_path = tmp_path / "geometry-utils.mjs"
    utils_path.write_text(utils.replace("from 'three'", f"from {json.dumps(three)}"))
    rooms = re.findall(r"  roomShell\((WS|DN|AR|VT), (\{.*?\})\);", world3d._M_WORLD, re.DOTALL)
    assert len(rooms) == 4
    builds = "\n".join(f"specs.push([{frame}, {options}]);" for frame, options in rooms)
    script = f"""
import * as THREE from {json.dumps(three)};
import {{ mergeGeometries }} from {json.dumps(utils_path.as_uri())};
const TAU = Math.PI * 2, scene = new THREE.Scene(), Q = {{ shadows: true }};
const UVSCALE = {{ stone: 2.2, pavers: 2.6, wood: 1.6 }};
const MAT = Object.fromEntries(["stone", "pavers", "brass", "wood", "leaf"].map(key => [key, new THREE.MeshStandardMaterial({{ vertexColors: true }})]));
{_part(world3d._M_SETUP, "  function rng(", "  // a crag:")}
{_part(world3d._M_SETUP, "  const buckets =", "  function instanced(")}
{_part(world3d._M_SETUP, "  function instanced(", "  // a procedural stand-in")}
{_part(world3d._M_WORLD, "  const CREAM =", "  // ------------------------------------------------------------- the floating island:")}
{_part(world3d._M_WORLD, "  function archWall(", "  function bush(")}
{_part(world3d._M_WORLD, "  const TY_CUTAWAY =", "  const shelf =")}
function bush() {{}} function onIsland() {{ return false; }}
const WS = RF.workshop, DN = RF.den, AR = RF.archive, VT = RF.vault, specs = [];
{builds}
const sentinel = G.box(1, 1, 1); pushBucket("stone", sentinel);
vine(100, 0.5, 100, 0.3, 2); const groundLeaves = leaves.slice(), groundRacemes = racemes.slice();
specs.forEach(([frame, options]) => roomShell(frame, options));
scene.updateMatrixWorld(true);
const rayHits = (group, from, to) => {{
  const ray = new THREE.Raycaster(from, to.clone().sub(from).normalize(), 0, from.distanceTo(to));
  const meshes = []; group.traverseVisible(obj => {{ if (obj.isMesh) meshes.push(obj); }});
  return ray.intersectObjects(meshes, false).length;
}};
const wallSnapshot = () => JSON.stringify(blockers.map(b => [b.inv.elements, b.half.toArray()]));
{body}
"""
    path = tmp_path / "cutaway.mjs"
    path.write_text(script)
    result = subprocess.run(["node", str(path)], capture_output=True, text=True, check=True, timeout=30)
    out: dict[str, Any] = json.loads(result.stdout)
    return out


def test_roofs_open_and_restore_without_changing_original_geometry_or_collisions(tmp_path: Path) -> None:
    out = _run(tmp_path, """
const snapshot = wallSnapshot(), original = TY_CUTAWAY.parts.map(p => p.cover.children.map(m => m.geometry.uuid));
const fromAbove = (i, group) => rayHits(group, specs[i][0].at(0, 12, 0), specs[i][0].at(0, 1, 0));
const before = TY_CUTAWAY.parts.map((p, i) => ({ roof: fromAbove(i, p.cover), cover: p.cover.visible, low: p.low.visible }));
tycoonCutaway(true);
const opened = TY_CUTAWAY.parts.map((p, i) => ({ roof: fromAbove(i, p.cover) + fromAbove(i, p.low), cover: p.cover.visible, low: p.low.visible }));
tycoonCutaway(false); tycoonCutaway(false);
const restored = TY_CUTAWAY.parts.map((p, i) => ({ roof: fromAbove(i, p.cover), cover: p.cover.visible, low: p.low.visible }));
console.log(JSON.stringify({ before, opened, restored, collisionsKept: snapshot === wallSnapshot(), blockers: blockers.length,
  sameGeometry: JSON.stringify(original) === JSON.stringify(TY_CUTAWAY.parts.map(p => p.cover.children.map(m => m.geometry.uuid))),
  staticKept: buckets.get("stone").includes(sentinel), floorCount: (buckets.get("pavers") || []).length + (buckets.get("wood") || []).length }));
""")
    assert len(out["before"]) == 4
    assert all(part["roof"] > 0 and part["cover"] and not part["low"] for part in out["before"])
    assert all(part["roof"] == 0 and not part["cover"] and part["low"] for part in out["opened"])
    assert out["restored"] == out["before"] and out["sameGeometry"]
    assert out["collisionsKept"] and out["blockers"] > 16
    assert out["staticKept"] and out["floorCount"] == 4


def test_low_walls_leave_real_doorways_open_and_do_not_hide_people(tmp_path: Path) -> None:
    out = _run(tmp_path, """
tycoonCutaway(true);
const rooms = TY_CUTAWAY.parts.map((part, i) => {
  const [frame, options] = specs[i], d = options.d;
  const door = rayHits(part.low, frame.at(0, 0.36, d / 2 + 1), frame.at(0, 0.36, d / 2 - 1));
  const wall = rayHits(part.low, frame.at(options.w / 2 - 0.3, 0.36, d / 2 + 1), frame.at(options.w / 2 - 0.3, 0.36, d / 2 - 1));
  const aboveWall = rayHits(part.low, frame.at(options.w / 2 - 0.3, 1.0, d / 2 + 1), frame.at(options.w / 2 - 0.3, 1.0, d / 2 - 1));
  const bounds = new THREE.Box3().setFromObject(part.low);
  return { door, wall, aboveWall, top: bounds.max.y - frame.origin.y };
});
console.log(JSON.stringify({ rooms }));
""")
    for room in out["rooms"]:
        assert room["door"] == 0
        assert room["wall"] > 0
        assert room["aboveWall"] == 0
        assert room["top"] == pytest.approx(0.77)


def test_roof_vines_hide_with_shells_and_restore_unchanged_without_hiding_ground_plants(tmp_path: Path) -> None:
    out = _run(tmp_path, """
const groundKept = JSON.stringify(leaves) === JSON.stringify(groundLeaves) && JSON.stringify(racemes) === JSON.stringify(groundRacemes);
const ground = instanced(paint(G.box(0.1, 0.1, 0.1), 0xffffff), MAT.leaf, vineLeafInstances(leaves), false);
tycoonRoofVines(paint(G.box(0.1, 0.1, 0.1), 0xffffff), paint(G.box(0.1, 0.2, 0.1), 0xffffff));
const roof = TY_CUTAWAY.parts.at(-1).cover;
const snapshot = () => JSON.stringify(roof.children.map(m => [m.geometry.uuid, Array.from(m.instanceMatrix.array), Array.from(m.instanceColor.array)]));
const original = snapshot();
const visible = () => { const meshes = []; scene.traverseVisible(m => { if (m.isInstancedMesh) meshes.push(m); }); return meshes; };
const before = visible().filter(m => m.parent === roof).map(m => m.count);
tycoonCutaway(true);
const open = { roof: visible().filter(m => m.parent === roof).length, ground: visible().includes(ground) };
tycoonCutaway(false);
console.log(JSON.stringify({ groundKept, groundCount: ground.count, before, open,
  restored: visible().filter(m => m.parent === roof).map(m => m.count), unchanged: snapshot() === original,
  expected: [TY_CUTAWAY.leaves.length, TY_CUTAWAY.racemes.length] }));
""")
    assert out["groundKept"] and out["groundCount"] > 0
    assert out["before"] == out["expected"] and out["before"][0] > 1000 and out["before"][1] > 100
    assert out["open"] == {"roof": 0, "ground": True}
    assert out["restored"] == out["before"] and out["unchanged"]
    assert "tycoonRoofVines(leafGeo.clone(), raceme.clone());" in world3d._M_WORLD
