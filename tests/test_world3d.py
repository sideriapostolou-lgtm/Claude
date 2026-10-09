"""The 3D world (/world, nightcrawler.world3d): static render and purity, the CSP hashes of the inline module, import
map and style, the cast (the town's member mapping) and the rooms covering every member, the pinned three.js addons
and their imports, the real-model manifest and its on-disk detection (with a tiny GLB built here, never shipped), the
route (auth, headers, methods) and the asset route serving the world's whitelist (no traversal)."""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import re
import struct
import tomllib
from collections.abc import Callable, Iterator
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
from fakes import FakeClock

from nightcrawler import world3d
from nightcrawler.config import Settings
from nightcrawler.dashboard import DashboardServer, build_state
from nightcrawler.ledger import Ledger
from nightcrawler.office import PIPELINE
from nightcrawler.office3d import ASSET_FILES, CAST3D, THREE_SHA256
from nightcrawler.page import MEMBERS
from nightcrawler.teamroom import TeamRoom
from nightcrawler.world3d import (
    ADDON_FILES,
    CART_MODEL,
    CAST_MODELS,
    MOTION_FILES,
    PROP_MODELS,
    WORLD_ASSETS,
    WORLD_CAST,
    WORLD_CSP,
    WORLD_ROOMS,
    models_on_disk,
    render_world_html,
    world_asset_bytes,
)
from tests.test_page import TOKEN, live_settings

ROOT = Path(__file__).resolve().parents[1]
MEMBER_IDS = [mid for mid, _, _ in MEMBERS]
ADDON = "/office/assets/addons/postprocessing/UnrealBloomPass.js"
#: SHA-256 of each vendored three.js 0.160.1 addon, unmodified from cdn.jsdelivr.net/npm/three@0.160.1/examples/jsm/
#: (identical on unpkg.com).
ADDON_SHA256 = {
    "addons/loaders/GLTFLoader.js": "d073b438e6a07e1359741dd5d6c76c953420cc0d4fd84eb1bdde94315540e6a3",
    "addons/libs/meshopt_decoder.module.js": "01f48524f4bac6141eaba07e94cc36e7ee56f311796fa6117c159842941b0468",
    "addons/utils/BufferGeometryUtils.js": "9be041e96308775d00e2695cc607645b9a9b64fd7c0e759dd8f7c00a8d92becb",
    "addons/postprocessing/EffectComposer.js": "d234e578618fa816955ebdc059c049c577e203e650e33cf22bde3f232c29e669",
    "addons/postprocessing/RenderPass.js": "1c90c085312871c4bcdccfcf519499c6276dd503363fcf7cb7f703add45cf4a2",
    "addons/postprocessing/UnrealBloomPass.js": "8f09315c0cec117a0ca2494d3e3586035b3c4323d6dcb037537cc51b04c3cdba",
    "addons/postprocessing/OutputPass.js": "13817fc7a87f662d29d2c5e00f44d3a4588c9afac4a372de0cacb0e44e368ffd",
    "addons/postprocessing/ShaderPass.js": "3b28a1ee27e0eb96c0eab137a1f442ccf127a926904eced2d51e125ec44af781",
    "addons/postprocessing/MaskPass.js": "328cf7db0da5d9be83ffe39d54b01d5ac1fddf108cc98182ddbb056f5c8b537f",
    "addons/postprocessing/Pass.js": "b3c6128340eaa37e40a6a2f1b738e894c855239417d50959759b34a2b5e89f92",
    "addons/shaders/CopyShader.js": "4e3346db194db56a596cd074e9bdb39fb5eb52040c333e0d29dc4eb1324d3b1d",
    "addons/shaders/LuminosityHighPassShader.js": "3d841cc594a0c1767d1b0185720b32761a0133c5f1b70b56658e28f2fb9b7900",
    "addons/shaders/OutputShader.js": "53a52e430c27bc36ceaab8ae90a2b4af7b02672d7ee4b29d6ba3c28e09c92c2a",
}


def tiny_glb() -> bytes:
    """A minimal valid binary glTF: one box (2 m tall, off-centre, so scaling and grounding are exercised), one
    material and one animation clip named "Idle" turning it about Y. Test-only: never written into the package."""
    lo, hi = (0.5, 2.0, -0.5), (1.5, 4.0, 0.5)
    faces = [  # normal, then the four corners (counter-clockwise seen from outside)
        ((1, 0, 0), [(hi[0], lo[1], hi[2]), (hi[0], lo[1], lo[2]), (hi[0], hi[1], lo[2]), (hi[0], hi[1], hi[2])]),
        ((-1, 0, 0), [(lo[0], lo[1], lo[2]), (lo[0], lo[1], hi[2]), (lo[0], hi[1], hi[2]), (lo[0], hi[1], lo[2])]),
        ((0, 1, 0), [(lo[0], hi[1], hi[2]), (hi[0], hi[1], hi[2]), (hi[0], hi[1], lo[2]), (lo[0], hi[1], lo[2])]),
        ((0, -1, 0), [(lo[0], lo[1], lo[2]), (hi[0], lo[1], lo[2]), (hi[0], lo[1], hi[2]), (lo[0], lo[1], hi[2])]),
        ((0, 0, 1), [(lo[0], lo[1], hi[2]), (hi[0], lo[1], hi[2]), (hi[0], hi[1], hi[2]), (lo[0], hi[1], hi[2])]),
        ((0, 0, -1), [(hi[0], lo[1], lo[2]), (lo[0], lo[1], lo[2]), (lo[0], hi[1], lo[2]), (hi[0], hi[1], lo[2])]),
    ]
    positions = b"".join(struct.pack("<3f", *v) for _, quad in faces for v in quad)
    normals = b"".join(struct.pack("<3f", *n) for n, quad in faces for _ in quad)
    indices = b"".join(struct.pack("<6H", k, k + 1, k + 2, k, k + 2, k + 3) for k in range(0, 24, 4))
    times = struct.pack("<2f", 0.0, 1.0)
    rotations = struct.pack("<8f", 0, 0, 0, 1, 0, 0.7071068, 0, 0.7071068)
    blobs = [positions, normals, indices, times, rotations]
    views, offset = [], 0
    for i, blob in enumerate(blobs):
        view: dict[str, Any] = {"buffer": 0, "byteOffset": offset, "byteLength": len(blob)}
        if i == 2:
            view["target"] = 34963
        elif i < 2:
            view["target"] = 34962
        views.append(view)
        offset += len(blob)
    binary = b"".join(blobs)
    gltf = {
        "asset": {"version": "2.0", "generator": "nightcrawler tests"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "body", "mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "material": 0}]}],
        "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [0.97, 0.73, 0.17, 1.0], "metallicFactor": 0.0,
                                                "roughnessFactor": 0.5}}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": views,
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 24, "type": "VEC3", "min": list(lo), "max": list(hi)},
            {"bufferView": 1, "componentType": 5126, "count": 24, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5123, "count": 36, "type": "SCALAR"},
            {"bufferView": 3, "componentType": 5126, "count": 2, "type": "SCALAR", "min": [0.0], "max": [1.0]},
            {"bufferView": 4, "componentType": 5126, "count": 2, "type": "VEC4"},
        ],
        "animations": [{"name": "Idle", "channels": [{"sampler": 0, "target": {"node": 0, "path": "rotation"}}],
                        "samplers": [{"input": 3, "output": 4, "interpolation": "LINEAR"}]}],
    }
    text = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 4)
    binary += b"\0" * (-len(binary) % 4)
    body = struct.pack("<II", len(text), 0x4E4F534A) + text + struct.pack("<II", len(binary), 0x004E4942) + binary
    return struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body


class Client:
    def __init__(self, server: DashboardServer) -> None:
        self.port = server.bound_port

    def request(self, path: str, method: str = "GET", headers: dict[str, str] | None = None
                ) -> tuple[int, http.client.HTTPMessage, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, headers=headers or {})
            res = conn.getresponse()
            return res.status, res.headers, res.read()
        finally:
            conn.close()


@pytest.fixture
def ledger(tmp_path: Path, fake_clock: FakeClock) -> Iterator[Ledger]:
    with Ledger(tmp_path / "nc.db", clock=fake_clock) as led:
        yield led


@pytest.fixture
def serve() -> Iterator[Callable[..., Client]]:
    servers: list[DashboardServer] = []

    def _serve(settings: Settings, ledger: Ledger) -> Client:
        cache: dict[str, Any] = {}
        team = TeamRoom(settings, ledger=ledger, clock=FakeClock(1_791_475_200.0), environ={})
        server = DashboardServer(settings, lambda: build_state(ledger, settings, 1_791_475_200.0, cache),
                                 host="127.0.0.1", port=0, team=team)
        server.start()
        servers.append(server)
        return Client(server)

    yield _serve
    for server in servers:
        server.stop()


@pytest.fixture
def asset_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private copy of office_assets/ the world reads instead of the package's (models can be dropped in)."""
    import shutil

    target = tmp_path / "office_assets"
    shutil.copytree(world3d.ASSET_DIR, target)
    for model in target.glob("*.glb"):
        model.unlink()
    monkeypatch.setattr(world3d, "ASSET_DIR", target)
    return target


def _hash(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii") + "'"


def _block(page: str, pattern: str) -> str:
    found = re.search(pattern, page, re.DOTALL)
    assert found is not None, pattern
    return found.group(1)


def _module(page: str) -> str:
    return _block(page, r'<script type="module">(.*?)</script>')


# --------------------------------------------------------------------------- the page


def test_world_is_static_and_lists_every_member(settings: Settings) -> None:
    page = render_world_html(settings)
    assert page.startswith("<!doctype html>") and '<canvas id="view">' in page and "PAPER" in page
    for mid, name, role in MEMBERS:
        assert f'data-id="{mid}"' in page and f'data-name="{name}"' in page and f'data-role="{role}"' in page
    assert f'data-pipeline="{",".join(PIPELINE)}"' in page
    module = _module(page)
    assert module.lstrip().startswith('import * as THREE from "three";')
    assert 'fetch("api/page"' in module and "http" not in module  # data and code come from this server only
    assert "innerHTML" not in page and "eval(" not in page and "insertAdjacentHTML" not in page  # text only, ever
    assert "textContent" in module and "fillText" in module
    assert "Math.min(1.75, window.devicePixelRatio" in module  # the pixel ratio cap
    assert "visibilitychange" in module and "requestAnimationFrame" in module  # paused while hidden
    assert "Math.min(0.1," in module  # the frame step is capped
    assert "no WebGL" in module and "Cannot reach the bot" in module and "Locked" in module  # the honest fallbacks
    assert "A visualisation of the bot's own ledger: every word is the bot's data; the world and its cast are drawings." \
        in page.replace("&#x27;", "'")
    assert 'href="office"' in page and 'href="./"' in page  # the ways back
    assert not re.search(r"""(?:src|href)\s*=\s*["']?(?:https?:)?//""", page)
    assert render_world_html(settings) == page  # pure


def test_world_live_mode_is_marked(make_settings: Callable[..., Settings]) -> None:
    page = render_world_html(live_settings(make_settings))
    assert 'class="mode live" id="mode">LIVE</b>' in page and "Night Shift: Skyport · live" in page


def test_world_data_blocks_are_json_that_cannot_break_out(settings: Settings) -> None:
    page = render_world_html(settings)
    for block_id, expected in (("cast", WORLD_CAST), ("rooms", WORLD_ROOMS), ("models", models_on_disk())):
        raw = _block(page, rf'<script id="{block_id}" type="application/json">(.*?)</script>')
        assert "<" not in raw and ">" not in raw and "&" not in raw
        assert json.loads(raw) == expected


def test_world_csp_hashes_the_inline_module_import_map_and_style(settings: Settings) -> None:
    page = render_world_html(settings)
    style = _block(page, r"<style>(.*?)</style>")
    importmap = _block(page, r'<script type="importmap">(.*?)</script>')
    assert _hash(style) in WORLD_CSP and _hash(_module(page)) in WORLD_CSP and _hash(importmap) in WORLD_CSP
    assert json.loads(importmap) == {"imports": {"three": "./office/assets/three.module.min.js",
                                                 "three/addons/": "./office/assets/addons/"}}
    assert WORLD_CSP.startswith("default-src 'none'; script-src 'self' 'wasm-unsafe-eval' 'sha256-")
    assert "; style-src 'sha256-" in WORLD_CSP and WORLD_CSP.endswith(
        "; connect-src 'self' blob:; img-src 'self' data: blob:; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'")
    assert "'unsafe-inline'" not in WORLD_CSP and "'unsafe-eval'" not in WORLD_CSP
    assert page.count("<script") == 5  # the import map, three JSON data blocks and the one module: nothing else runs
    assert page.index('type="importmap"') < page.index('type="module"')  # the map must come before the module


def test_world_csp_adds_only_webassembly_for_the_decoder(settings: Settings) -> None:
    """The meshopt decoder instantiates its bundled WebAssembly: ``'wasm-unsafe-eval'`` is the one addition, and
    nothing else is looser than before (no eval, no inline script or style, no other origin, no workers)."""
    directives = dict(d.strip().split(" ", 1) for d in WORLD_CSP.split(";"))
    page = render_world_html(settings)
    module, importmap = _module(page), _block(page, r'<script type="importmap">(.*?)</script>')
    assert directives["script-src"].split() == ["'self'", "'wasm-unsafe-eval'", _hash(module), _hash(importmap)]
    assert directives["style-src"] == _hash(_block(page, r"<style>(.*?)</style>"))
    assert directives == {"default-src": "'none'", "script-src": directives["script-src"],
                          "style-src": directives["style-src"], "connect-src": "'self' blob:",
                          "img-src": "'self' data: blob:", "base-uri": "'none'", "form-action": "'none'",
                          "frame-ancestors": "'none'"}
    for loose in ("'unsafe-inline'", "'unsafe-eval'", "'unsafe-hashes'", "'strict-dynamic'", "*", "http", "data:",
                  "blob:"):
        assert loose not in directives["script-src"], loose


def test_the_module_loads_the_real_cast_with_the_meshopt_decoder(settings: Settings) -> None:
    module = _module(render_world_html(settings))
    # three's GLTFLoader with the meshopt decoder (the cast's files are meshopt-compressed), both from this server
    assert 'import("three/addons/loaders/GLTFLoader.js")' in module
    assert 'import("three/addons/libs/meshopt_decoder.module.js")' in module
    assert "await decoder.ready;" in module and "gltfLoader.setMeshoptDecoder(decoder);" in module
    # the bodies in motion: cast_motion.js (same origin), its move library and actors
    assert 'import("./office/assets/cast_motion.js")' in module and "m.loadLibrary(gltfLoader, ASSET)" in module
    assert "new motionMod.Actor(got[0].scene, s, lib)" in module
    # progressive: never before the first frame; the crew first, then the set nearest the camera; a counter line
    assert "if (!started) { started = true; setTimeout(function () { loadModels()" in module
    assert '"loading the crew " + loading.crew + "/" + loading.crewN' in module
    assert "propIds.sort(function (x, y) { return PLACE[x][0].at.distanceTo(camera.position)" in module
    # every procedural stand-in stays until its model is ready, then fades out; a failure keeps the drawing
    assert "keeping the drawing" in module and "back to the drawing" in module
    assert "(STANDIN[id] || []).forEach(function (s) { s.visible = false; })" in module
    assert "a.body.visible = false" in module and "a.body.visible = true" in module
    # Mote rides a glass bell drawn in code on its cart, Rook's amber eyes are drawn on his Head bone
    assert "new THREE.LatheGeometry(prof.map(function (q) { return new THREE.Vector2(q[0] * radius, q[1] * height); }), 48)" \
        in module and "clearcoat: 1" in module
    assert "rookEyes(A)" in module and "A.bones.Head" in module
    layout = module[module.index("const PLACE = {"):module.index("const placed = {};")]
    for prop in PROP_MODELS:
        assert f"\n    {prop}: " in layout, prop  # every hero prop has a place in the layout


def test_the_acting_follows_the_ledger(settings: Settings) -> None:
    """Moves are acting triggered by real events and statuses; nothing invents a result."""
    module = _module(render_world_html(settings))
    # Jet carries a real closed trade's cube (the carry walk), cheers only for a win and shrugs only at a loss
    assert 'carry: won ? "gold" : "red"' in module and 'return a.carrying ? "carry"' in module
    assert 'if (pnl > 0) oneShot(a, "cheer"); else if (pnl < 0) oneShot(a, "shrug");' in module
    assert module.count('"cheer"') == 1 and module.count('"shrug"') == 1
    # worried only on a bad-tone event; Rook nods only on a good-tone one
    assert 'if (ev.tone === "bad") oneShot(actor, "worried");' in module and module.count('"worried"') == 1
    assert 'ev.tone === "good" && actor.key === "rook") oneShot(actor, "nod"' in module and module.count('"nod"') == 1
    # the Polymarket desk's lessons: Voss thinks, then says the desk's own words
    assert 'memberId === "predict" && /^Lesson:/.test(' in module and 'oneShot(actor, "think", 3.4)' in module
    assert "speak(a, memberId, ev.text, ev.tone, 10)" in module
    # talk while the member's own words are up; the crew within ~6 m turn and listen
    assert 'else if (a.speaking) loop = "talk";' in module and 'else if (a.listening) loop = "listen";' in module
    assert "let best = 6.0;" in module
    # blocked or waiting: think; ambient life only while every member an actor plays is idle (no words)
    assert 'if (status === "blocked" || status === "waiting")' in module
    assert 'worstStatus(a.members) === "idle"' in module


def test_the_honest_words_come_from_the_data(settings: Settings) -> None:
    module = _module(render_world_html(settings))
    # the vault sign: money.usd and exactly money.label
    assert "drawVaultSign(fmtUsd(money.usd), money.label || \"\"" in module
    # the Polymarket ticket board: the desk's own label, counts and at most three positions, questions cut to 28
    for text in ('"Polymarket desk · " + (desk.label || "")', 'nReal + " REAL · " + nPaper + " paper"',
                 "desk.positions : []).slice(0, 3)", 'q.live ? "REAL" : "paper"', "String(q.question).slice(0, 27) + \"…\""):
        assert text in module, text
    assert "realBulbMat.emissiveIntensity = nReal > 0 ? 4 : 0" in module  # the REAL lamp only with real positions
    # a closed trade: the cube is gold for a win, red for a loss, and the float is the trade's own pnl_usd
    assert 'carry: won ? "gold" : "red"' in module and "dropEl.textContent = fmtSigned(pnl)" in module
    # bubbles say the member's own event text, labelled "ACTOR · Member"
    assert 'actor.name.toUpperCase() + " · " + nameOf(memberId)' in module and "speak(actor, memberId, ev.text" in module
    assert "(d.town && d.town.line)" in module
    assert "alerts[0].text" in module


def test_the_screenshot_switches_never_change_the_default(settings: Settings) -> None:
    module = _module(render_world_html(settings))
    assert 'params.get("lite") === "1"' in module and 'params.get("q") === "full"' in module
    assert "bloom: !LITE && !tiny && !slow" in module  # bloom by default, skipped on tiny or slow screens


# --------------------------------------------------------------------------- the cast, the rooms, the models


def test_the_cast_is_the_towns_cast() -> None:
    assert set(WORLD_CAST) == set(CAST3D) == set(CAST_MODELS) == {"voss", "pip", "nyx", "rook", "mote", "jet"}
    for key, actor in WORLD_CAST.items():
        assert actor["members"] == CAST3D[key]["members"] and actor["room"] == CAST3D[key]["office"]
        assert actor["name"] and actor["kind"] and actor["look"] and actor["gait"] and actor["job"]
        assert actor["room"] in WORLD_ROOMS
    played = [m for c in WORLD_CAST.values() for m in c["members"]]  # type: ignore[attr-defined]
    assert sorted(played) == sorted(MEMBER_IDS)  # each member has one actor; nobody is left out or invented


def test_every_member_has_exactly_one_room_lamp() -> None:
    housed = [m for room in WORLD_ROOMS.values() for m in room["members"]]  # type: ignore[attr-defined]
    assert sorted(housed) == sorted(MEMBER_IDS)
    assert set(WORLD_ROOMS) == {"table", "workshop", "den", "vault", "archive", "dock", "observatory"}
    assert WORLD_ROOMS["table"]["members"] == ["judge", "predict"]  # Voss's table holds the Polymarket desk
    for room in WORLD_ROOMS.values():
        assert room["title"] and room["line"]


def test_the_model_manifest_names_one_whitelisted_glb_per_actor() -> None:
    for key, spec in CAST_MODELS.items():
        assert spec["asset"] == f"cast_{key}.glb" and WORLD_ASSETS[f"cast_{key}.glb"] == "model/gltf-binary"
        assert isinstance(spec["height"], float) and 0.5 < spec["height"] < 3.0
    assert float(str(CAST_MODELS["rook"]["height"])) > 1.8 * float(str(CAST_MODELS["pip"]["height"]))  # twice Pip
    others = [float(str(s["height"])) for k, s in CAST_MODELS.items() if k != "rook"]
    assert float(str(CAST_MODELS["rook"]["height"])) > 1.6 * max(others)  # clearly the biggest of the lineup
    assert WORLD_ASSETS[CART_MODEL] == "model/gltf-binary"
    for key, spec in PROP_MODELS.items():
        assert spec["asset"] == f"prop_{key}.glb" and WORLD_ASSETS[f"prop_{key}.glb"] == "model/gltf-binary"


def test_the_model_tables_agree_with_the_cast_manifest() -> None:
    """The page's heights, facings, kinds and walks are the build's (cast_manifest.json), so nothing floats, sinks
    or faces backwards; the cast's heights are the world's own lineup (the manifest's are the rigs')."""
    manifest = json.loads((world3d.ASSET_DIR / "cast_manifest.json").read_text(encoding="utf-8"))
    for key, spec in CAST_MODELS.items():
        built = manifest["characters"][key]
        assert (spec["asset"], spec["kind"], spec["walk"]) == (built["file"], built["kind"], built["walk"]), key
        assert spec["yaw"] == pytest.approx(built["yaw"]), key
        if built["walk"]:
            assert built["walk"] in manifest["clips"] and manifest["clips"][built["walk"]]["walk"], key
    assert manifest["characters"]["motecart"]["file"] == CART_MODEL
    assert set(PROP_MODELS) == set(manifest["props"])
    for key, spec in PROP_MODELS.items():
        built = manifest["props"][key]
        assert spec["asset"] == built["file"] and spec["height"] == built["height_m"], key
        assert spec["yaw"] == pytest.approx(built["yaw"]), key
    assert set(MOTION_FILES) == {"clips.glb", "cast_manifest.json", "cast_rig.js", "cast_motion.js"}
    assert manifest["library"]["file"] == "clips.glb"


def test_the_tiny_glb_is_a_valid_binary_gltf() -> None:
    data = tiny_glb()
    magic, version, length = struct.unpack_from("<III", data, 0)
    assert (magic, version, length) == (0x46546C67, 2, len(data)) and length % 4 == 0
    json_len, json_type = struct.unpack_from("<II", data, 12)
    gltf = json.loads(data[20:20 + json_len])
    bin_len, bin_type = struct.unpack_from("<II", data, 20 + json_len)
    assert json_type == 0x4E4F534A and bin_type == 0x004E4942 and bin_len >= gltf["buffers"][0]["byteLength"]
    assert gltf["animations"][0]["name"] == "Idle" and gltf["accessors"][0]["max"][1] == 4.0


def test_models_on_disk_reports_the_real_files() -> None:
    on = models_on_disk()
    assert on["motion"] is True  # the move library, its manifest and both modules ship
    cast_on, props_on = on["cast"], on["props"]
    assert isinstance(cast_on, dict) and isinstance(props_on, dict)
    assert set(cast_on) == set(CAST_MODELS) and set(props_on) == set(PROP_MODELS)
    assert cast_on["mote"] == dict(CAST_MODELS["mote"], cart=CART_MODEL)
    assert cast_on["jet"] == CAST_MODELS["jet"] and props_on["arch"] == PROP_MODELS["arch"]
    for name in list(MOTION_FILES) + [CART_MODEL] + [str(s["asset"]) for s in [*CAST_MODELS.values(), *PROP_MODELS.values()]]:
        assert (world3d.ASSET_DIR / name).is_file(), name


def test_models_on_disk_lists_only_whitelisted_files_that_exist(asset_dir: Path, settings: Settings) -> None:
    assert models_on_disk() == {"motion": False, "cast": {}, "props": {}}  # the fixture took every model away
    (asset_dir / "cast_pip.glb").write_bytes(tiny_glb())
    (asset_dir / "cast_bob.glb").write_bytes(tiny_glb())  # not a cast member: ignored
    (asset_dir / "cast_nyx.glb").mkdir()  # not a file: ignored
    (asset_dir / "cast_mote.glb").write_bytes(tiny_glb())  # Mote without its cart: keeps the drawing
    (asset_dir / "prop_lantern.glb").write_bytes(tiny_glb())
    (asset_dir / "prop_bob.glb").write_bytes(tiny_glb())  # not a hero prop: ignored
    expected = {"motion": False, "cast": {"pip": CAST_MODELS["pip"]}, "props": {"lantern": PROP_MODELS["lantern"]}}
    assert models_on_disk() == expected
    page = render_world_html(settings)
    raw = _block(page, r'<script id="models" type="application/json">(.*?)</script>')
    assert json.loads(raw) == expected
    (asset_dir / CART_MODEL).write_bytes(tiny_glb())
    (asset_dir / "clips.glb").write_bytes(tiny_glb())
    on = models_on_disk()
    assert on["motion"] is True and on["cast"]["mote"] == dict(CAST_MODELS["mote"], cart=CART_MODEL)  # type: ignore[index]
    (asset_dir / "cast_motion.js").unlink()  # one motion file missing: the bipeds keep their drawings
    assert models_on_disk()["motion"] is False


def test_without_models_the_world_still_draws_everyone(asset_dir: Path, settings: Settings) -> None:
    """The fallback path: no model on disk (or any that fails) leaves the procedural cast and set in place."""
    page = render_world_html(settings)
    raw = _block(page, r'<script id="models" type="application/json">(.*?)</script>')
    assert json.loads(raw) == {"motion": False, "cast": {}, "props": {}}
    module = _module(page)
    assert "const BUILD = { voss: makeVoss, pip: makePip, nyx: makeNyx, rook: makeRook, mote: makeMote, jet: makeJet };" in module
    assert "if (!castIds.length && !propIds.length) return;" in module  # nothing to fetch: no loader at all
    assert "a.anim(simT + a.phase, st, dt);" in module  # each drawing animates itself until a model replaces it
    assert "console.warn(\"world: model for \" + id + \" could not load, keeping the drawing\", e)" in module
    assert "console.warn(\"world: prop \" + id + \" could not load, keeping the drawing\", e)" in module


# --------------------------------------------------------------------------- the vendored addons


def test_the_vendored_addons_are_pinned_and_unmodified() -> None:
    assert set(ADDON_FILES) == set(ADDON_SHA256)
    three = world3d.ASSET_DIR / "three.module.min.js"
    assert hashlib.sha256(three.read_bytes()).hexdigest() == THREE_SHA256  # the same release they were cut from
    for name, digest in ADDON_SHA256.items():
        data = world_asset_bytes(name)
        assert data is not None and hashlib.sha256(data).hexdigest() == digest, name
        assert WORLD_ASSETS[name] == "application/javascript; charset=utf-8"


def test_every_addon_import_resolves_inside_the_whitelist() -> None:
    for name in ADDON_FILES:
        text = (world3d.ASSET_DIR / name).read_text(encoding="utf-8")
        for spec in re.findall(r"""^\s*(?:import|export)[^;]*?from\s+['"]([^'"]+)['"]""", text, re.MULTILINE | re.DOTALL):
            if spec == "three":
                continue  # the import map
            target = (Path(name).parent / spec).as_posix()
            parts: list[str] = []
            for piece in target.split("/"):
                if piece == "..":
                    parts.pop()
                elif piece != ".":
                    parts.append(piece)
            assert "/".join(parts) in ADDON_FILES, (name, spec)


def test_the_world_whitelist_never_reaches_outside(asset_dir: Path) -> None:
    for bad in ("../world3d.py", "world3d.py", "", "addons", "addons/", "addons/loaders", "addons/../three.module.min.js",
                "/addons/loaders/GLTFLoader.js", "addons/loaders/GLTFLoader.js.map", "cast_bob.glb", "cast_pip.glb"):
        assert world_asset_bytes(bad) is None, bad  # cast_pip.glb: whitelisted, but not on disk
    assert not set(WORLD_ASSETS) & set(ASSET_FILES)  # the town's three.js stays the town's


def test_package_data_ships_the_addons_and_models() -> None:
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]["package-data"]
    globs = declared["nightcrawler"]
    for glob in ("office_assets/addons/**/*.js", "office_assets/*.glb", "office_assets/*.json", "office_assets/*.js"):
        assert glob in globs, glob
    # every file the world serves is matched by one of the globs (so a wheel or the Docker image carries it)
    for name in WORLD_ASSETS:
        assert any(PurePosixPath("office_assets/" + name).match(g) for g in globs), name


# --------------------------------------------------------------------------- the routes


def test_world_route_auth_headers_and_methods(serve: Callable[..., Client], ledger: Ledger,
                                              make_settings: Callable[..., Settings]) -> None:
    client = serve(make_settings(DASHBOARD_TOKEN=TOKEN), ledger)
    status, _, body = client.request("/world")
    assert status == 401 and b"Locked" in body
    status, headers, body = client.request(f"/world?token={TOKEN}")
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    assert headers["Content-Security-Policy"] == WORLD_CSP and b'<canvas id="view">' in body
    assert headers["X-Frame-Options"] == "DENY" and headers["Cache-Control"] == "no-store"
    cookie = headers["Set-Cookie"].split(";")[0]
    status, headers, _ = client.request("/world", headers={"Cookie": cookie})
    assert status == 200 and "Set-Cookie" not in headers
    for method in ("POST", "PUT", "DELETE"):
        status, headers, _ = client.request("/world", method=method, headers={"Cookie": cookie})
        assert status == 405 and headers["Allow"] == "GET"
    for bad in ("/world.html", "/world/", "/world/x", "/worlds"):
        assert client.request(bad, headers={"Cookie": cookie})[0] == 404, bad


def test_the_addons_are_served_behind_the_token_from_the_whitelist(
        serve: Callable[..., Client], ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    client = serve(make_settings(DASHBOARD_TOKEN=TOKEN), ledger)
    assert client.request(ADDON)[0] == 401  # private like everything else
    _, headers, _ = client.request(f"/world?token={TOKEN}")
    cookie = headers["Set-Cookie"].split(";")[0]
    status, headers, body = client.request(ADDON, headers={"Cookie": cookie})
    assert status == 200 and headers["Content-Type"] == "application/javascript; charset=utf-8"
    assert hashlib.sha256(body).hexdigest() == ADDON_SHA256["addons/postprocessing/UnrealBloomPass.js"]
    assert headers["Cache-Control"] == "private, max-age=86400" and headers["X-Content-Type-Options"] == "nosniff"
    status, _, body = client.request("/office/assets/three.module.min.js", headers={"Cookie": cookie})
    assert status == 200 and hashlib.sha256(body).hexdigest() == THREE_SHA256  # the town's file still served
    for bad in ("/office/assets/addons/", "/office/assets/addons/loaders/", "/office/assets/addons/../../world3d.py",
                "/office/assets/addons/%2e%2e/%2e%2e/world3d.py", "/office/assets/addons/loaders/GLTFLoader.js/",
                "/office/assets/addons//loaders/GLTFLoader.js", "/office/assets/cast_bob.glb", "/office/assets/prop_bob.glb",
                "/office/assets/cast_manifest.json/", "/office/assets/../cast_manifest.json", "/office/assets/CLIPS.glb",
                "/office/assets/addons/libs/", "/office/assets/addons/libs/meshopt_decoder.js"):
        assert client.request(bad, headers={"Cookie": cookie})[0] == 404, bad
    status, headers, _ = client.request(ADDON, method="POST", headers={"Cookie": cookie})
    assert status == 405 and headers["Allow"] == "GET"


def test_the_cast_props_library_and_decoder_are_whitelisted_and_served_behind_the_token(
        serve: Callable[..., Client], ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    expected = {
        "addons/libs/meshopt_decoder.module.js": "application/javascript; charset=utf-8",
        "clips.glb": "model/gltf-binary", "cast_manifest.json": "application/json",
        "cast_rig.js": "text/javascript; charset=utf-8", "cast_motion.js": "text/javascript; charset=utf-8",
        CART_MODEL: "model/gltf-binary",
        **{str(s["asset"]): "model/gltf-binary" for s in CAST_MODELS.values()},
        **{str(s["asset"]): "model/gltf-binary" for s in PROP_MODELS.values()},
    }
    for name, media in expected.items():
        assert WORLD_ASSETS[name] == media, name
    shipped = {p.name for p in world3d.ASSET_DIR.glob("*") if p.suffix in (".glb", ".json") or p.name.startswith("cast_")}
    assert shipped <= set(WORLD_ASSETS)  # every model, the manifest and the cast modules on disk are servable
    client = serve(make_settings(DASHBOARD_TOKEN=TOKEN), ledger)
    _, headers, _ = client.request(f"/world?token={TOKEN}")
    cookie = headers["Set-Cookie"].split(";")[0]
    for name, media in expected.items():
        assert client.request("/office/assets/" + name)[0] == 401, name  # private like everything else
        status, headers, body = client.request("/office/assets/" + name, headers={"Cookie": cookie})
        assert status == 200 and headers["Content-Type"] == media, name
        assert body == (world3d.ASSET_DIR / name).read_bytes(), name
        assert headers["Cache-Control"] == "private, max-age=86400" and headers["X-Content-Type-Options"] == "nosniff"


def test_a_dropped_in_model_is_served_and_announced(serve: Callable[..., Client], ledger: Ledger,
                                                    settings: Settings, asset_dir: Path) -> None:
    glb = tiny_glb()
    (asset_dir / "cast_jet.glb").write_bytes(glb)
    client = serve(settings, ledger)
    status, headers, body = client.request("/office/assets/cast_jet.glb")
    assert status == 200 and headers["Content-Type"] == "model/gltf-binary" and body == glb
    status, _, page = client.request("/world")
    raw = _block(page.decode("utf-8"), r'<script id="models" type="application/json">(.*?)</script>')
    assert status == 200 and json.loads(raw) == {"motion": False, "cast": {"jet": CAST_MODELS["jet"]}, "props": {}}
    assert client.request("/office/assets/cast_rook.glb")[0] == 404  # whitelisted, but not dropped in
