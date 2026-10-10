"""The 3D world (/world, nightcrawler.world3d): static render and purity, the CSP hashes of the inline module, import
map and style, the cast (the town's member mapping) and the rooms covering every member, the pinned three.js addons
and their imports, the real-model manifest and its on-disk detection (with a tiny GLB built here, never shipped), the
route (auth, headers, methods), the asset route serving the world's whitelist (no traversal), and the top bar and
first-visit guide in plain words (text only, the guide's storage guarded)."""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import re
import shutil
import struct
import subprocess
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
    assert page.startswith("<!doctype html>") and '<canvas id="view">' in page
    assert "Night Shift: Skyport · paper" in page
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
    """The title says the Solana bot's mode; the real-money button turns red only from the data (plain.real.on), never
    from the static page: before the first answer it claims nothing."""
    page = render_world_html(live_settings(make_settings))
    assert "Night Shift: Skyport · live" in page
    assert '<button type="button" class="pill real" id="real"' in page and "pill real on" not in page
    assert '<b id="real-label">Money</b><small id="real-sub">loading…</small>' in page


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
    # bubbles say the member's event in the server's plain words for that very event (else its own text), labelled
    # "ACTOR · job" (the member's name without the plain words)
    assert 'actor.name.toUpperCase() + jobOf(actor.key, memberId)' in module
    assert 'return t && t.job ? " · " + t.job : memberId ? " · " + nameOf(memberId) : "";' in module
    assert "speak(actor, memberId, saidOf(memberId, ev)" in module
    assert ('return s && s.ts === ev.ts && s.text ? s.text : String(ev.text || "").replace(/\\(paper\\)/g, '
            '"(pretend money)");') in module  # pretend money says "pretend" in a bubble too
    # the bar: the headline and the real money from plain, the first banner only when there is one
    assert "headlineEl.textContent = plain.headline;" in module and "realLabel.textContent = r.label;" in module
    assert 'realBtn.className = "pill real" + (r.on ? " on" : "")' in module
    assert 'statusEl.textContent = alerts.length ? alerts[0].text : ""; statusEl.hidden = !alerts.length;' in module
    assert "d.town" not in module and "townEl" not in module  # the dense town line is gone from the world


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


# --------------------------------------------------------------------------- the polish round (regressions)


def _js_body(module: str, start: str) -> str:
    """The source from ``start`` to the brace that closes the first block after it (strings and comments skipped)."""
    i = module.index(start)
    j, depth, quote = module.index("{", i), 0, ""
    while True:
        ch = module[j]
        if quote:
            if ch == "\\":
                j += 1
            elif ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif module.startswith("//", j):
            j = module.index("\n", j)
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return module[i:j + 1]
        j += 1


def _node(script: str, tmp_path: Path) -> Any:
    path = tmp_path / "check.mjs"
    path.write_text(script, encoding="utf-8")
    res = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=60, check=False)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


def test_the_lantern_halos_are_soft_glows_over_the_lamp_heads(settings: Settings) -> None:
    """A canvas texture's colour is white wherever anything is drawn: the halos read its alpha (the red channel made a
    flat pale disc), sit a little toward the drone (so they glow over the lamp head, walls still hide them), and the
    ticket board draws after them."""
    module = _module(render_world_html(settings))
    assert "texture2D(uMap, vUv).a" in module and "texture2D(uMap, vUv).r" not in module
    assert "c.xyz += normalize(-c.xyz) * 0.22;" in module
    lantern = _js_body(module, "    lantern: function (h) {")
    assert "props.heroBulbMat = props.lanternBulbs.material.clone()" in lantern
    assert "map: haloTex" in lantern and "halo.scale.setScalar(0.42)" in lantern
    assert "board.renderOrder = 8;" in module


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_the_arches_are_camera_blockers(settings: Settings, tmp_path: Path) -> None:
    """The hero arches register their pillars and lintel as oriented boxes: a drone line through a pillar is blocked,
    one through the opening is clear (the follow shot used to fly into the stonework)."""
    module = _module(render_world_html(settings))
    arch = _js_body(module, "    arch: function (h) {").replace("    arch: function (h) {", "const arch = function (h) {", 1)
    blocked = _js_body(module, "  function blocked(from, to) {")
    three = (world3d.ASSET_DIR / "three.module.min.js").as_uri()
    out = _node(f"""
import * as THREE from {json.dumps(three)};
const V3 = function (x, y, z) {{ return new THREE.Vector3(x, y, z); }};
const blockers = [];
const _o = new THREE.Vector3(), _d = new THREE.Vector3(), _r = new THREE.Ray(), _b = new THREE.Box3(), _hit = new THREE.Vector3();
{arch};
{blocked}
const h = new THREE.Group(), inner = new THREE.Group(); inner.userData.size = V3(2.54, 3.4, 0.71); h.add(inner);
h.position.set(-7.25, 0, -3); h.rotation.y = Math.PI / 2;  // the workshop door: the arch spans world z
arch(h);
const through = function (z) {{ return blocked(V3(-9, 1.2, z), V3(-5.5, 1.2, z)); }};
console.log(JSON.stringify({{ n: blockers.length, pillar: through(-3 + 1.1), opening: through(-3),
  lintel: blocked(V3(-9, 3.2, -3), V3(-5.5, 3.2, -3)) }}));
""", tmp_path)
    assert out["n"] == 3
    assert out["pillar"] < 1 and out["lintel"] < 1 and out["opening"] == 1


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_a_fade_in_never_touches_the_worlds_shared_materials(settings: Settings, tmp_path: Path) -> None:
    """Mote's bell is made with its own brass, the hero lantern bulbs with their own material, and fadeIn() skips the
    world's shared materials whatever is under the root (every railing used to blink out when Mote arrived)."""
    module = _module(render_world_html(settings))
    bell = _js_body(module, "  function makeBell(radius, height) {")
    assert "const bellBrass = MAT.brass.clone();" in bell and bell.count("MAT.brass") == 1  # (only to clone it)
    fade = _js_body(module, "  function fadeIn(root, seconds, done) {")
    out = _node(f"""
const mat = function (name) {{ return {{ name: name, transparent: false, opacity: 1, needsUpdate: false }}; }};
const MAT = {{ brass: mat("brass"), stone: mat("stone") }}, CMAT = {{ eye: mat("eye"), brass: MAT.brass }};
const props = {{ lanternBulbs: {{ material: mat("bulbs") }} }}, shadowMat = mat("shadow"), bellMat = mat("bell");
const fades = []; let SHARED_MATS = null;
{fade}
const own = mat("own");
const meshes = [{{ isMesh: true, material: MAT.brass }}, {{ isMesh: true, material: [own, props.lanternBulbs.material] }},
  {{ isMesh: true, material: CMAT.eye }}];
fadeIn({{ traverse: function (fn) {{ meshes.forEach(fn); }} }}, 0.5, null);
console.log(JSON.stringify({{ brass: MAT.brass.opacity, bulbs: props.lanternBulbs.material.opacity, eye: CMAT.eye.opacity,
  own: own.opacity, kept: fades[0].keep.length }}));
""", tmp_path)
    assert out == {"brass": 1, "bulbs": 1, "eye": 1, "own": 0, "kept": 1}
    # a model dropped mid-fade: its fade goes, and a late callback never hides the drawing that came back
    assert "if (fades[i].root === a.model) fades.splice(i, 1);" in module
    assert "fadeIn(holder, 0.45, function () { if (a.model === holder) a.body.visible = false; });" in module


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_the_chips_are_made_once_and_only_updated(settings: Settings, tmp_path: Path) -> None:
    """Every /api/page poll used to clear and rebuild the chip row, so a tap could land on a detached button: the
    buttons are made once, later polls only update the status dots and which chip is on."""
    module = _module(render_world_html(settings))
    build = _js_body(module, "  function buildChips() {")
    render = _js_body(module, "  function renderChips() {")
    assert 'chips.textContent = ""' not in render
    out = _node(f"""
const el = function (tag) {{ return {{ tag: tag, className: "", children: [], appendChild: function (c) {{ this.children.push(c); }} }}; }};
const document = {{ createElement: el, createTextNode: function (t) {{ return {{ text: t }}; }} }};
const chips = el("div"); Object.defineProperty(chips, "textContent", {{ set: function () {{ chips.children = []; }} }});
const CAST = {{ voss: {{ name: "Voss", members: ["judge"] }}, jet: {{ name: "Jet", members: ["broker"] }} }}, actors = {{ voss: {{}}, jet: {{}} }};
const ROOMS = {{ observatory: {{ title: "The observatory", members: ["coach"] }} }};
const status = {{ judge: "working", broker: "idle", coach: "waiting" }};
const worstStatus = function (ids) {{ return ids.length ? status[ids[0]] : "idle"; }};
let pinned = null; const renderCard = function () {{}};
// (the live director's pin and its way back, as the page wires them: a chip pins, the live chip goes back to live)
const togglePin = function (k) {{ pinned = pinned === k ? null : k; renderChips(); }}, goLive = function () {{ pinned = null; renderChips(); }};
const chipEls = [];
{build}
{render}
renderChips(); const first = chips.children.slice(), onOf = function () {{ return first.map(function (b) {{ return b.className; }}); }};
const live0 = onOf();
status.broker = "working"; renderChips(); renderChips();
first[2].onclick(); const pinnedOn = onOf();
first[0].onclick(); const back = onOf();
console.log(JSON.stringify({{ n: chips.children.length, same: chips.children.every(function (b, i) {{ return b === first[i]; }}),
  dots: first.map(function (b) {{ return b.children[0].className === undefined ? null : b.children[0].className; }}),
  live0: live0, on: pinnedOn, back: back }}));
""", tmp_path)
    assert out["n"] == 5 and out["same"] is True
    assert out["dots"] == [None, "working", "working", "waiting", None]  # Jet's dot followed the poll; live and map have none
    assert out["live0"] == ["on live", "", "", "", ""]  # the broadcast is on until something is pinned
    assert out["on"] == ["", "", "on", "", ""]
    assert out["back"] == ["on live", "", "", "", ""]  # the live chip unpins


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_the_fps_governor_ignores_loading_and_can_step_back_up(settings: Settings, tmp_path: Path) -> None:
    """A loading stall (models decoding and uploading) never costs the phone its bloom, pixel ratio or shadows; after
    the set is in, a slow window turns bloom off, and two fast windows bring it back once (never a see-saw)."""
    module = _module(render_world_html(settings))
    state = re.search(r"  let fpsN = 0, fpsT = 0,[^\n]*;", module)
    assert state is not None
    govern = _js_body(module, "  function govern(dt) {")
    out = _node(f"""
let clock = 0; const performance = {{ now: function () {{ return clock; }} }};
const FULLQ = false, LITE = false; console.info = function () {{}};
const loading = {{ crew: 0, crewN: 6, set: 0, setN: 12 }}, bloom = {{ enabled: true }}, Q = {{ dpr: 2, shadows: true }};
const renderer = {{ shadowMap: {{}} }}, sun = {{}}; let resizeNext = false;
const trimDecor = function () {{ return 0; }};
{state.group(0)}
{govern}
const run = function (seconds, fps) {{ for (let i = 0; i < seconds * fps; i++) {{ clock += 1000 / fps; govern(1 / fps); }} }};
const log = [];
run(30, 4); log.push([bloom.enabled, Q.dpr]);  // loading the crew and the set at 4 fps: nothing changes
loading.crew = 6; loading.set = 12; run(2, 60); run(6, 20); log.push([bloom.enabled, Q.dpr]);  // settled, then slow
run(11, 60); log.push([bloom.enabled, Q.dpr]);  // fast again: bloom back on
run(6, 20); log.push([bloom.enabled, Q.dpr]);  // slow again: bloom off for good
run(11, 60); log.push([bloom.enabled, Q.dpr]);
console.log(JSON.stringify(log));
""", tmp_path)
    assert out == [[True, 2], [False, 2], [True, 2], [False, 2], [False, 2]]


def test_chatter_never_talks_over_a_real_moment(settings: Settings) -> None:
    """The generic status chatter used to replace Jet's trade bubble and Voss's lesson: event bubbles are tagged,
    chatter waits while the drone is on a real moment or an event's words are up."""
    module = _module(render_world_html(settings))
    chatter = _js_body(module, "  function chatter() {")
    assert "if (focus && simT < focus.until) return;" in chatter
    assert 'if (bubbles[i].kind !== "chatter" && simT < bubbles[i].until) return;' in chatter
    assert 'if (b) b.kind = "chatter";' in chatter
    assert 'until: simT + (seconds || 8), kind: "event" }' in module


def test_the_phone_keeps_the_ticket_board_and_the_map_labels_inside_the_frame(settings: Settings) -> None:
    module = _module(render_world_html(settings))
    place = _js_body(module, "  function placeBoard() {")
    assert "camera.aspect < 0.85" in place and "board.scale.setScalar(tall ? 0.62 : 1)" in place
    assert "camera.updateProjectionMatrix(); placeBoard();" in module  # re-placed on every resize
    assert "clamp(s.x - w / 2, 8, window.innerWidth - w - 8)" in module  # a room label never runs off the edge
    assert 'const hide = shotKey === "map"; if (bubblesEl.hidden !== hide) bubblesEl.hidden = hide;' in module


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_the_follow_shot_swings_round_a_wall_before_closing_in(settings: Settings, tmp_path: Path) -> None:
    """A wall between the walker and the drone's place: the drone takes the other side if that is clear; only when
    every side is blocked does it close in, and then it looks at the walker (the subject used to drop out of the
    bottom of the frame while the look stayed on the floor ahead)."""
    module = _module(render_world_html(settings))
    sides = re.search(r"  const FOLLOW_SIDES = [^\n]*;", module)
    assert sides is not None
    parts = [sides.group(0), _js_body(module, "  function followAt(base, back, side, up) {"),
             _js_body(module, "  function followShot(a) {"), _js_body(module, "  function blocked(from, to) {")]
    three = (world3d.ASSET_DIR / "three.module.min.js").as_uri()
    out = _node(f"""
import * as THREE from {json.dumps(three)};
const V3 = function (x, y, z) {{ return new THREE.Vector3(x, y, z); }};
let blockers = [];
const wall = function (x, y, z, hx, hy, hz) {{ return {{ inv: new THREE.Matrix4().makeTranslation(x, y, z).invert(), half: V3(hx, hy, hz) }}; }};
const _o = new THREE.Vector3(), _d = new THREE.Vector3(), _r = new THREE.Ray(), _b = new THREE.Box3(), _hit = new THREE.Vector3();
const _fwd = new THREE.Vector3(), _side = new THREE.Vector3(), _fh = new THREE.Vector3(), _try = new THREE.Vector3();
const _fol = {{ pos: V3(0, 0, 0), look: V3(0, 0, 0) }};
{chr(10).join(parts)}
const a = {{ group: {{ position: V3(0, 0, 0) }}, height: 1.0, yawS: 0, carrying: null }};
const at = function () {{ const s = followShot(a); return {{ pos: s.pos.toArray(), look: s.look.toArray(), side: a.folSide }}; }};
const open = at();
blockers = [wall(0.4, 1.3, -1.5, 0.3, 2, 0.3)];  // a pillar on the drone's usual side
const swung = at();
blockers = [wall(0, 1.5, -0.8, 6, 3, 0.2)];  // a wall right behind the walker: every side is blocked
const closed = at();
console.log(JSON.stringify({{ open: open, swung: swung, closed: closed }}));
""", tmp_path)
    assert out["open"]["side"] == 0.75 and out["open"]["pos"] == pytest.approx([0.75, 1.75, -2.95])
    assert out["swung"]["side"] == -0.75 and out["swung"]["pos"] == pytest.approx([-0.75, 1.75, -2.95])
    assert out["swung"]["look"] == pytest.approx(out["open"]["look"])  # a clear side: the usual look ahead
    closed = out["closed"]
    assert closed["pos"][2] > -1.0  # it closed in toward the walker
    head = [0.0, 0.85, 0.0]
    dist = sum((p - q) ** 2 for p, q in zip(closed["look"], head, strict=True)) ** 0.5
    ahead = sum((p - q) ** 2 for p, q in zip(out["open"]["look"], head, strict=True)) ** 0.5
    assert dist < 0.5 * ahead  # ...and looks at the walker, not the floor two metres ahead


# --------------------------------------------------------------------------- the live director

#: Runs the page's pure planner (the block between its markers, cut from the rendered module) through the scenarios
#: the tests check, with a seeded random: a quiet ten minutes (coverage in every three-minute window, holds, angles,
#: the wide ratio, the hard cuts), a fresh event and its phases, Jet's carry and drop, a lesson, the pins (a
#: character, the observatory, the map) and their clocks. Prints one JSON object.
_PLANNER_HARNESS = r"""
const fs = require("node:fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const { makePlanner, LIVE_PLACES, LIVE_GRAMMAR, LIVE_CFG } = new Function(src + "\nreturn { makePlanner, LIVE_PLACES, LIVE_GRAMMAR, LIVE_CFG };")();
function rng(seed) { let s = seed >>> 0 || 1; return function () { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; }; }
const ACTORS = %(actors)s, ROOMS = %(rooms)s, STEP = LIVE_CFG.step;
// where things stand (metres: the rooms' places in the layout, roughly; the planner only compares distances)
const AT = { voss: [-1, 0], pip: [-12.5, -3], nyx: [12.5, -3], rook: [10.8, 10.6], mote: [-10.5, 10.5], jet: [23, -1.5],
  arrival: [0, 6], overhead: [0, 1], courtyard: [0, 0], bridge: [0, 12], telescope: [0.6, -16.7], walkway: [20, 3], airship: [26, -1.6],
  kiosk: [23, 5.4], vaultsign: [10.5, 11], shelves: [-10, 11], bench: [-12.5, -3], screens: [13, -3] };
const PLACES = LIVE_PLACES.map((p) => Object.assign({}, p, { x: AT[p.id][0], z: AT[p.id][1], angles: 3 }));
function planner(seed) {
  return makePlanner(ACTORS.map(([id, room]) => ({ id, room, x: AT[id][0], z: AT[id][1] })), PLACES, { random: rng(seed), alias: { observatory: "telescope" } });
}
function live(working) {
  const st = { actors: {}, focus: null };
  ACTORS.forEach(([id, room]) => { st.actors[id] = { room, x: AT[id][0], z: AT[id][1], walking: false, carrying: false, speaking: false,
    working: working.indexOf(id) >= 0, thinking: false, visiting: false }; });
  return st;
}
function roomOf(subject) { const a = ACTORS.find((x) => x[0] === subject), p = LIVE_PLACES.find((x) => x.id === subject); return a ? a[1] : p ? p.room : null; }
const isWide = (id) => !!LIVE_PLACES.find((p) => p.id === id && p.wide);
const out = { places: LIVE_PLACES, grammar: LIVE_GRAMMAR, cfg: LIVE_CFG, quiet: [] };
for (const seed of [1, 7, 42]) {  // a quiet ten minutes, five members working, three seeds
  const P = planner(seed), st = live(["pip", "nyx", "voss", "rook", "mote"]), seen = [];
  for (let t = 0; t <= 600; t += STEP) {
    const seq = P.shot.seq; P.plan(t, st);
    if (P.shot.seq !== seq) seen.push({ t, subject: P.shot.subject, grammar: P.shot.grammar, angle: P.shot.angle, hard: P.shot.hard, wide: isWide(P.shot.subject) });
  }
  const gaps = [];  // every three-minute window: who and which room had no airtime
  for (let t0 = 0; t0 <= 420; t0 += 5) {
    const w = seen.filter((s) => s.t >= t0 && s.t < t0 + 180);
    ROOMS.forEach((r) => { if (!w.some((s) => roomOf(s.subject) === r)) gaps.push(r + "@" + t0); });
    ACTORS.forEach(([id]) => { if (!w.some((s) => s.subject === id)) gaps.push(id + "@" + t0); });
  }
  const holds = seen.slice(1).map((s, i) => s.t - seen[i].t);
  let maxWideIn6 = 0; seen.forEach((s, i) => { maxWideIn6 = Math.max(maxWideIn6, seen.slice(Math.max(0, i - 5), i + 1).filter((x) => x.wide).length); });
  const angles = {};
  seen.forEach((s) => { (angles[s.subject] = angles[s.subject] || new Set()).add(s.angle); });
  const visits = {}; seen.forEach((s) => { visits[s.subject] = (visits[s.subject] || 0) + 1; });
  out.quiet.push({ seed, shots: seen.length, first: seen[0], gaps, minHold: Math.min(...holds), maxHold: Math.max(...holds),
    wides: seen.filter((s) => s.wide).length, maxWideIn6, repeats: seen.filter((s, i) => i && s.subject === seen[i - 1].subject).length,
    angles: Object.fromEntries(Object.entries(angles).map(([k, v]) => [k, v.size])), visits,
    anglesSeen: Object.fromEntries(ACTORS.map(([id]) => [id, P.anglesSeen(id)])), grammars: [...new Set(seen.map((s) => s.grammar))].sort(),
    hardCuts: seen.filter((s) => s.hard).length, actorShots: seen.filter((s) => ACTORS.some(([id]) => id === s.subject)).length });
}
{  // a fresh event cuts into the rotation at the next plan step, even a shot that has just begun
  const P = planner(3), st = live(["pip", "nyx"]); let t = 0;
  const step = () => { t += STEP; P.plan(t, st); };
  while (t < 30) step();
  const seq0 = P.shot.seq; while (P.shot.seq === seq0) step();
  const begun = t; step(); step();  // half a second into a rotation shot
  const before = { subject: P.shot.subject, event: P.shot.event };
  st.focus = { actor: "pip", kind: "speak", start: t, until: t + 10 }; st.actors.pip.speaking = true; const asked = t;
  step();
  const first = { subject: P.shot.subject, event: P.shot.event, phase: P.shot.phase, grammar: P.shot.grammar, hard: P.shot.hard,
    after: +(t - asked).toFixed(2), rotationHeld: +(asked - begun).toFixed(2) };
  // a second fresh event inside the first one's minimum hold waits for it, then cuts
  const evStart = t; step(); step();
  st.focus = { actor: "rook", kind: "speak", start: t, until: t + 9 }; st.actors.rook.speaking = true;
  let secondAt = null; while (t < evStart + 6 && secondAt === null) { step(); if (P.shot.subject === "rook") secondAt = +(t - evStart).toFixed(2); }
  const second = { subject: P.shot.subject, phase: P.shot.phase, hard: P.shot.hard, heldFirst: secondAt };
  // its phases: the walk (follow or dolly, a flight: same event), then the visit
  st.actors.rook.speaking = false; st.actors.rook.walking = true; st.focus.until = t + 14; for (let i = 0; i < 16; i++) step();
  const walking = { subject: P.shot.subject, phase: P.shot.phase, grammar: P.shot.grammar, hard: P.shot.hard };
  st.actors.rook.walking = false; st.actors.rook.visiting = true; for (let i = 0; i < 16; i++) step();
  const visiting = { subject: P.shot.subject, phase: P.shot.phase, grammar: P.shot.grammar };
  // over: back to the rotation
  st.focus = null; st.actors.rook.visiting = false; const t0 = t; let resumedAt = null;
  while (t < t0 + 20 && resumedAt === null) { step(); if (!P.shot.event) resumedAt = +(t - t0).toFixed(2); }
  out.event = { before, first, second, walking, visiting, resumedAt };
}
{  // Jet's carry: the trade line at the dock, the carry walk, the drop at the vault; a lesson at the table
  const Q = planner(5), s2 = live([]); let u = 0; const step2 = () => { u += STEP; Q.plan(u, s2); };
  while (u < 20) step2();
  s2.focus = { actor: "jet", kind: "carry", start: u, until: u + 8 }; s2.actors.jet.speaking = true;
  for (let i = 0; i < 14; i++) step2(); const speak = { subject: Q.shot.subject, phase: Q.shot.phase, grammar: Q.shot.grammar };
  s2.actors.jet.walking = true; s2.actors.jet.carrying = true; s2.focus.until = u + 12; for (let i = 0; i < 14; i++) step2();
  const carry = { phase: Q.shot.phase, grammar: Q.shot.grammar };
  s2.actors.jet.walking = false; s2.actors.jet.carrying = false; s2.actors.jet.visiting = true; s2.actors.jet.room = "vault";
  for (let i = 0; i < 14; i++) step2(); const drop = { phase: Q.shot.phase, grammar: Q.shot.grammar, room: Q.shot.room };
  s2.focus = { actor: "voss", kind: "lesson", start: u, until: u + 13 }; s2.actors.jet.visiting = false;
  for (let i = 0; i < 14; i++) step2(); const lesson = { subject: Q.shot.subject, phase: Q.shot.phase, grammar: Q.shot.grammar };
  out.carry = { speak, carry, drop, lesson };
}
{  // the pins: the clock, a pinned character keeps the camera (still moving round it), the map waits, then live again
  const P = planner(1), st = live(["pip"]); let t = 90;
  for (let k = 90; k < 100; k += STEP) P.plan(k, st);
  P.pin("voss", 100); t = 100;
  const subjects = new Set(), shots = new Set(); let lastSeq = P.shot.seq;
  for (; t < 125; t += STEP) { P.plan(t, st); subjects.add(P.shot.subject); if (P.shot.seq !== lastSeq) { lastSeq = P.shot.seq; shots.add(P.shot.grammar + ":" + P.shot.angle); } }
  const clock = { at100: null, left100: null };
  out.pin = { subjects: [...subjects], shots: shots.size };
  P.plan(125, st); out.pin.after = { pinned: P.pinned(125), subject: P.shot.subject, event: P.shot.event };
  const C = planner(1); C.pin("voss", 100);
  Object.assign(out.pin, { at100: C.pinned(100), left100: C.pinLeft(100), at112: C.pinned(112), left112: C.pinLeft(112), at124: C.pinned(124.9),
    at125: C.pinned(125), left125: C.pinLeft(125) });
  C.pin("map", 200); C.unpin(); out.pin.afterUnpin = C.pinned(200.1);
  const M = planner(2), sm = live([]);
  for (let k = 0; k < 20; k += STEP) M.plan(k, sm);
  M.pin("map", 20); const frozen = M.shot.seq; for (let k = 20; k < 45; k += STEP) M.plan(k, sm);
  const mapHeld = M.shot.seq === frozen; M.plan(45.25, sm);
  out.map = { held: mapHeld, back: M.shot.seq !== frozen && !M.pinned(45.25) };
  const O = planner(4), so = live([]); O.plan(0, so); O.pin("observatory", 1); O.plan(1, so);
  out.observatory = { subject: O.shot.subject };
  O.unpin(); O.plan(1.25, so); out.observatory.unpinned = O.shot.subject;
  const H = planner(6), sh = live([]); H.plan(0, sh); const hold = H.shot.hold; H.extend(2.5);
  out.extend = { added: +(H.shot.hold - hold).toFixed(2) };
}
console.log(JSON.stringify(out));
"""


def _planner_source(module: str) -> str:
    start, end = module.index("// >>> live planner"), module.index("// <<< live planner")
    return module[start:end]


def _function_source(module: str, name: str) -> str:
    """The source of one function in the module (from its declaration to the next declaration at its indent)."""
    start = module.index(f"\n  function {name}(")
    following = re.search(r"\n  (?:function |const |let |if \(|// )", module[start + 1:])
    return module[start:start + 1 + (following.start() if following else len(module))]


_REPORT: dict[str, Any] = {}


def _director_report(settings: Settings, tmp_path: Path) -> dict[str, Any]:
    """The planner's Node run (once per session: it is deterministic under the harness's seeded random)."""
    import shutil
    import subprocess

    if shutil.which("node") is None:
        pytest.skip("Node is not installed")
    if not _REPORT:
        actors = [[key, str(WORLD_CAST[key]["room"])] for key in WORLD_CAST]
        (tmp_path / "planner.js").write_text(_planner_source(_module(render_world_html(settings))))
        (tmp_path / "run.js").write_text(_PLANNER_HARNESS % {"actors": json.dumps(actors), "rooms": json.dumps(list(WORLD_ROOMS))})
        res = subprocess.run(["node", str(tmp_path / "run.js"), str(tmp_path / "planner.js")], capture_output=True, text=True,
                             timeout=120, check=True)
        _REPORT.update(json.loads(res.stdout))
    return _REPORT


def test_the_live_director_owns_the_camera_by_default(settings: Settings) -> None:
    """Live is the default: the director plans and flies every shot unless the viewer pinned something; a tap pins
    for a while and times out; "live" (the chip or the tag) returns at once; the map times out the same way."""
    module = _module(render_world_html(settings))
    assert "function director() { liveDirector(); }" in module
    director = _function_source(module, "liveDirector")
    assert "const p = PLANNER.pinned(simT); if (p !== pinned) { pinned = p; nextPlanAt = 0; renderChips(); renderCard(); }" in director
    assert 'if (pinned === "map") {' in director and 'cut("map", mapShot)' in director  # the page's own overview
    assert "readLive(); PLANNER.plan(simT, LIVE_STATE);" in director and "startShot(false);" in director
    # an event's walk stays on air until the walker arrives (where the arrival keeps it for the drop or hand-off)
    assert 'if (focus && focus.actor.state === "out" && !focus.actor.ambient && focus.until < simT + 1) focus.until = simT + 1;' in director
    assert "function togglePin(k) { if (pinned === k) PLANNER.unpin(); else PLANNER.pin(k, simT);" in module
    assert "function goLive() { PLANNER.unpin(); pinned = null;" in module and "liveEl.onclick = goLive;" in module
    # the chips (made once): "live" first, which goes back to live; every other chip pins through the director
    build = _js_body(module, "  function buildChips() {")
    assert 'add(null, "live", null);' in build and "b.onclick = key ? function () { togglePin(key); } : goLive;" in build
    assert 'pinned ? "" : "on live"' in _js_body(module, "  function renderChips() {")
    assert "pin: 25" in module and '{ alias: { observatory: "telescope" } }' in module  # 25 s; the observatory chip
    # the planner is pure: no three.js, no DOM, no page state or clock inside its block
    code = re.sub(r"//[^\n]*", "", _planner_source(module)).replace("live.actors[", "")
    for banned in ("THREE", "document", "window", "simT", "camera", "cam.", "performance", "Date", "scene", "actors["):
        assert banned not in code, banned
    # the director keeps to its own section, after the page's camera, shots and blockers it calls
    section = module[module.index("// ============================================================= THE LIVE DIRECTOR"):
                     module.index("// ============================================================= THE LOOP")]
    assert "// >>> live planner" in section and "function liveDirector()" in section
    for helper in ("blocked(", "blocker(", "arrivalShot(t)", "mapShot", "SHOTS[a.homeRoom]", "cut(\"map\""):
        assert helper in section, helper
    for owned in ("function cut(", "function updateCamera(", "const SHOTS = {", "function arrivalShot("):
        assert owned not in section and owned in module, owned


def test_the_shot_grammar_is_every_type_with_its_lens(settings: Settings) -> None:
    """Close-up, over-the-shoulder, follow, low, crane, slow orbit (30-60 degrees), dolly, establishing wide, the
    room's own framing and the places' moves, each with a 24-35 mm lens; every place has its three rigs."""
    module = _module(render_world_html(settings))
    lenses = dict(re.findall(r"(\w+): (\d+)", _block(module, r"const LENS_MM = \{(.*?)\};")))
    grammar = json.loads(re.sub(r",\s*}", "}", re.sub(r"(\w+):", r'"\1":', _block(module, r"const LIVE_GRAMMAR = (\{.*?\});"))))
    types = {t for kinds in grammar.values() for t in kinds}
    assert types == {"station", "closeup", "ots", "orbit", "low", "crane", "follow", "dolly", "place", "wide"}
    assert set(lenses) == types and all(24 <= int(mm) <= 35 for mm in lenses.values()), lenses
    assert lenses["closeup"] == "35" and lenses["wide"] == "24"
    shape, slots = _function_source(module, "shape"), _block(module, r"const OFF = \{(.*?)\};")
    for kind in ("closeup", "low", "orbit", "crane", "ots"):
        assert f'g === "{kind}"' in shape and len(re.findall(rf"\b{kind}: \[([^\]]*)\]", slots)[0].split(",")) == 6, kind
    assert "clamp(frameDist(S, 0.8, mm), 1.2 + 0.15 * h, 2.2 + 0.2 * h)" in shape  # the close-up: 1.3-2.7 m, the face filling it
    assert "(0.55 + 0.15 * (RUN.seq % 4))" in shape  # the orbit: 0.55-1.0 rad (31-57 degrees) over the hold
    assert 'if (RUN.g === "follow")' in module and "addScaledVector(_fw, 1.45 + 0.5 * h)" in module  # ahead and beside
    places = re.findall(r'\{ id: "(\w+)", room', _planner_source(module))
    assert len(places) == 12 and len(set(places)) == 12
    parts = re.split(r"\n    (\w+): \[", module[module.index("const RIGS = {"):module.index("function placePose(")])
    rigs = dict(zip(parts[1::2], parts[2::2]))
    assert sorted(rigs) == sorted(places)
    for place, text in rigs.items():
        assert text.count("rigOf(") + text.count("null,") == 3, place
    assert "if (!v) { const s = arrivalShot(t); out.pos.copy(s.pos).lerp(s.look, 0.08 * e);" in module  # the opener: the page's arrival


def test_the_live_tag_says_only_its_fixed_words(settings: Settings) -> None:
    """The LIVE tag's own words are fixed ("LIVE", "pinned · back to live in N s"); the subject's name and kind, the
    room and what each member is doing are the card's rows: the cast's and rooms' fixed descriptions and the data's
    own words, as text."""
    page = render_world_html(settings)
    module = _module(page)
    assert '<b id="live">LIVE</b><span class="name">NIGHT SHIFT: SKYPORT</span>' in page
    assert module.count("liveEl.textContent = ") == 1
    assert 'liveEl.textContent = n < 0 ? "LIVE" : "pinned · back to live in " + n + " s";' in module
    assert 'const room = card.querySelector(".room .name")' in module  # the room line keeps the tag beside it
    assert "else if (!pinned) { const s = liveSubject(); actor = s.actor; roomKey = s.room; }" in module
    assert 'room.textContent = (actor && actor.walking ? "ON THE WAY" : spec ? spec.title : "").toUpperCase();' in module
    assert 'who.appendChild(document.createTextNode(c.name + " · " + c.kind))' in module
    assert 'a.textContent = nameOf(id) + ": " + (m.doing || m.why || "")' in module  # the member's own words
    section = module[module.index("// ============================================================= THE LIVE DIRECTOR"):
                     module.index("// ============================================================= THE LOOP")]
    assert re.findall(r"textContent = ", section) == ["textContent = "]  # nothing else here writes on screen
    assert "innerHTML" not in section and "fillText" not in section


def test_an_event_pre_empts_the_broadcast_within_one_plan_step(settings: Settings, tmp_path: Path) -> None:
    report = _director_report(settings, tmp_path)
    ev, step = report["event"], report["cfg"]["step"]
    assert step == 0.25 and ev["before"]["subject"] != "pip" and not ev["before"]["event"]
    assert ev["first"]["rotationHeld"] < report["cfg"]["minHold"]  # even a rotation shot that has just begun
    assert ev["first"]["after"] <= step and ev["first"]["grammar"] in report["grammar"]["speak"]  # within 0.25 s
    assert {k: ev["first"][k] for k in ("subject", "event", "phase", "hard")} == {"subject": "pip", "event": True, "phase": "speak", "hard": True}
    assert 3 <= ev["second"]["heldFirst"] <= 3 + step  # an event shot holds its 3 s, then the next one cuts in
    assert {k: ev["second"][k] for k in ("subject", "phase", "hard")} == {"subject": "rook", "phase": "speak", "hard": True}
    assert ev["walking"] == {"subject": "rook", "phase": "walk", "grammar": ev["walking"]["grammar"], "hard": False}
    assert ev["walking"]["grammar"] in ("follow", "dolly")  # the hand-off walk: followed (a flight, not a cut)
    assert ev["visiting"]["phase"] == "visit" and ev["visiting"]["grammar"] in report["grammar"]["visit"]
    assert ev["resumedAt"] is not None and ev["resumedAt"] <= report["cfg"]["maxHold"]  # then back to the rotation
    carry = report["carry"]
    assert carry["speak"]["subject"] == "jet" and carry["speak"]["phase"] == "speak"
    assert carry["carry"]["phase"] == "carry" and carry["carry"]["grammar"] in ("follow", "dolly")
    assert carry["drop"] == {"phase": "drop", "grammar": carry["drop"]["grammar"], "room": "vault"}
    assert carry["drop"]["grammar"] in ("low", "crane")  # the drop at the vault: a low or a crane shot
    assert carry["lesson"]["subject"] == "voss" and carry["lesson"]["phase"] == "lesson"
    assert carry["lesson"]["grammar"] in ("ots", "closeup", "orbit")


def test_the_broadcast_covers_every_room_and_character(settings: Settings, tmp_path: Path) -> None:
    """Without events: every room and character on air in any three minutes, three angles each over ten minutes,
    every shot held (3 s at least; the rotation 5-10 s), never the same subject twice running, wides at most one in
    six, about every third shot a hard cut, the crew most of the airtime."""
    report = _director_report(settings, tmp_path)
    for quiet in report["quiet"]:
        assert quiet["first"]["subject"] == "arrival" and quiet["first"]["hard"]  # it opens on the pack's arrival
        assert quiet["gaps"] == [], quiet["gaps"][:5]
        assert quiet["minHold"] >= 5 and quiet["maxHold"] <= 10 and quiet["repeats"] == 0
        assert quiet["maxWideIn6"] <= 1 and quiet["wides"] * 6 <= quiet["shots"]
        assert all(n >= 3 for n in quiet["anglesSeen"].values()), quiet["anglesSeen"]
        assert all(quiet["angles"][k] >= min(3, quiet["visits"][k]) for k in quiet["visits"]), (quiet["angles"], quiet["visits"])
        assert {"station", "closeup", "ots", "orbit", "low", "crane", "place", "wide"} <= set(quiet["grammars"])
        assert 0.28 <= quiet["hardCuts"] / quiet["shots"] <= 0.4
        assert quiet["actorShots"] / quiet["shots"] >= 0.5


def test_a_pin_times_out_back_to_live(settings: Settings, tmp_path: Path) -> None:
    report = _director_report(settings, tmp_path)
    pin = report["pin"]
    assert {k: pin[k] for k in ("at100", "left100", "at112", "left112", "at124", "at125", "left125", "afterUnpin")} == {
        "at100": "voss", "left100": 25, "at112": "voss", "left112": 13, "at124": "voss", "at125": None, "left125": 0, "afterUnpin": None}
    assert pin["subjects"] == ["voss"] and pin["shots"] >= 3  # pinned: on Voss only, still moving round him
    assert pin["after"]["pinned"] is None and pin["after"]["subject"] != "voss"  # then straight back to the broadcast
    assert report["map"] == {"held": True, "back": True}  # the map holds the plan, then times out back to live
    assert report["observatory"] == {"subject": "telescope", "unpinned": report["observatory"]["unpinned"]}
    assert report["observatory"]["unpinned"] != "telescope"  # "live" returns at once
    assert report["extend"] == {"added": 2.5}  # a flight to a shot does not eat its hold


def test_the_flights_keep_to_the_walkways_and_clear_the_walls(settings: Settings) -> None:
    """Between shots the drone flies the cast's own walkways at drone height (never climbing over a wall), the way
    cut short where a straight line is clear of every wall, furniture blocker and the table's hologram, its corners
    rounded; a long way or no safe way is a hard cut. The hero arches and the lanterns are blockers too."""
    module = _module(render_world_html(settings))
    assert "const FLY_H = 2.05, FLY_MAX = 26;" in module and "CLEAR_Y" not in module
    plan = _function_source(module, "planFlight")
    assert "if (!flyClear(from, to)) {" in plan and "nearestNode(from), e = nearestNode(to)" in plan
    assert "while (j > i + 1 && !flyClear(WP[i], WP[j])) j--;" in plan  # string-pulled
    assert "if (len > FLY_MAX) return false;" in plan
    assert "if (blocked(a, b) < 0.999) return false;" in _function_source(module, "flyClear")
    assert "!planFlight(cam.pos, _dst.pos)) { hard = true; if (!reframe) PLANNER.cutHard(); }" in module
    assert 'if (HAS("arch")) PLACE.arch.forEach(function (q) {' in module  # the workshop, den and observatory arches
    assert 'if (HAS("lantern")) LANTERN_SPOTS.forEach(' in module
    assert "FLY.dur = clamp(0.9 + FLY.len / 7, 1.2, 4.0)" in module  # eased, at most 4 s
    assert 'hop("c0", V3(7.4, FLY_H, 2.6)' in module  # the open-air way between the courtyard and the outer walkway
    # every shot is checked clear of the walls before it starts, and pulled in if the subject moves behind one
    assert "if (poseClear(a, yaw + off)) { RUN.az = yaw + off; return; }" in module
    assert "const f = clearTo(_eye, _live.pos)" in module and "if (clearTo(_eye, _pt) < 0.985) return false;" in module


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_a_walker_beside_something_solid_is_filmed_from_the_clear_side(settings: Settings, tmp_path: Path) -> None:
    """The final check's frames: a follow shot of Voss leaving the table pushed the lens into the table rim, and Jet's
    walk along the dock put the lens inside the glass parcel tube. The tube is a chain of camera blockers now, and a
    walker whose drone side is blocked is filmed from the clearest of the follow and dolly sides instead (a cut, at
    most once in 1.5 s, and only when another side is clearly better)."""
    module = _module(render_world_html(settings))
    assert "tubeCurve.getPointAt(i / n, a); tubeCurve.getPointAt((i + 1) / n, b);" in module
    assert "blockers.push({ inv: m.clone().invert(), half: V3(0.27, 0.27, len / 2 + 0.12) });" in module
    assert "eyeOf(RUN.a, _eye); if (RUN.a.walking) sideStep();" in _function_source(module, "liveDirector")
    # a flight's pan never stares down at the paving: past a gentle tilt the look gives way to the way ahead
    assert "? 1 - steep : 0) - FLY.see)" in _function_source(module, "flyPose")
    tries = re.search(r"  const WALK_TRY = [^\n]*;", module)
    assert tries is not None
    step = _function_source(module, "sideStep")
    out = _node(f"""
let simT = 10;
const RUN = {{ g: "follow", side: 1, stepAt: -1e9, mm: 28, clear: 0.4, a: {{}} }}, LENS_MM = {{ follow: 28, dolly: 30 }};
const _eye = {{}}, _live = {{ pos: {{}}, look: {{}} }}, _dst = {{ pos: {{}}, look: {{}} }};
let clear = {{ "follow1": 0.3, "follow-1": 1, "dolly1": 0.6, "dolly-1": 0.6 }};
const walkPose = function (a, out) {{ out.pos.k = RUN.g + RUN.side; }};
const clearTo = function (e, p) {{ return clear[p.k]; }};
{tries.group(0)}
{step}
walkPose(RUN.a, _live); sideStep(); const first = [RUN.g, RUN.side, RUN.stepAt, RUN.clear, _live.pos.k];
clear = {{ "follow1": 1, "follow-1": 0.2, "dolly1": 0.6, "dolly-1": 0.6 }}; simT = 10.5; sideStep(); const soon = [RUN.g, RUN.side];
simT = 12; clear = {{ "follow1": 0.3, "follow-1": 0.35, "dolly1": 0.4, "dolly-1": 0.3 }}; sideStep(); const stuck = [RUN.g, RUN.side];
console.log(JSON.stringify({{ first: first, soon: soon, stuck: stuck }}));
""", tmp_path)
    assert out["first"] == ["follow", -1, 10, 1, "follow-1"]  # the clear side, re-posed at once
    assert out["soon"] == ["follow", -1]  # never twice in 1.5 s (no flicker)
    assert out["stuck"] == ["follow", -1]  # nothing clearly better: it stays (and comes in closer as before)


def test_a_bubble_shows_only_over_its_own_speaker_close_up(settings: Settings) -> None:
    """The final check's frames: Pip's words (labelled PIP) hung over Jet in a close follow shot on the dock, because
    Pip's head, 30 m away through a line of open doorways, projected just above Jet's. A bubble now shows only while
    its speaker is within 12 m of the drone and in plain view."""
    module = _module(render_world_html(settings))
    body = _js_body(module, "  function updateBubbles() {")
    assert "camera.position.distanceToSquared(b.actor.headAt) < 144" in body
    assert "blocked(camera.position, b.actor.headAt) > 0.98" in body


def test_the_director_allocates_nothing_per_frame(settings: Settings) -> None:
    """The director and the camera's moves run every frame: no new objects, closures or copies there (each shot's
    setup and each flight's plan allocate nothing either beyond reusing their records)."""
    module = _module(render_world_html(settings))
    for name in ("liveDirector", "shotPose", "actorPose", "posePos", "poseLook", "stationPose", "walkPose", "placePose",
                 "flyPose", "flyPoint", "cruise", "eyeOf", "fovFor", "setFov", "renderLive", "readLive", "startShot",
                 "setupActor", "shape", "poseClear", "planFlight", "routeNodes", "nearestNode", "flyClear", "clearTo", "liveSubject",
                 "sideStep"):
        body = re.sub(r"//[^\n]*", "", _function_source(module, name))
        for banned in ("new ", ".clone(", "function (", ".map(", ".filter(", ".concat(", ".slice(", "Array.from", "=> "):
            assert banned not in body, (name, banned)
    planner = _planner_source(module)
    plan = planner[planner.index("    function plan("):planner.index("    return {\n      shot: shot")]
    for banned in ("new ", ".map(", ".filter(", "=> "):
        assert banned not in plan, banned
    assert "govern(dtRaw);" in module and "director(); updateCamera(dtRaw, simT);" in module  # the fps governor stays
    assert 'if (params.get("debug") === "1") window.__world =' in module and module.count("window.__world") == 1


# --------------------------------------------------------------------------- the bar and the guide (plain words)


def test_the_world_bar_replaces_the_two_dense_lines(settings: Settings) -> None:
    page = render_world_html(settings)
    module = _module(page)
    head = page[page.index('<header id="bar">'):page.index("</header>")]
    for part in ('class="back" href="./"', 'id="real"', 'id="practice"', ">Practice (pretend)</button>", 'id="help"',
                 'id="headline"', 'id="status" role="status" hidden'):
        assert part in head, part
    assert 'id="town"' not in page and 'id="foot"' not in page and 'id="money"' not in page and 'id="mode"' not in page
    # the real-money panel: the data's line, the paused reason, the limits, the verdict and the research line
    panel = _js_body(module, "  function renderPanel() {")
    for call in ("para(panelBody, r.line)", 'para(panelBody, r.paused, "warn")', "para(panelBody, r.limits)",
                 'para(panelBody, r.verdict, "verdict")', 'para(panelBody, r.research, "dim")',
                 "para(panelBody, plain.pretend.line)"):
        assert call in panel, call
    assert "p.textContent = text;" in _js_body(module, "  function para(parent, text, cls) {")
    bar = _js_body(module, "  function renderBar() {")
    assert 'realSub.textContent = !r.on ? "off" : r.paused ?' in bar and '" at risk now"' in bar
    # the LIVE card: the character's plain job and latest event
    card = _js_body(module, "  function renderCard() {")
    assert "a.textContent = t.plain_role;" in card and '"Latest: " + t.latest' in card
    assert "bubbles" not in head and "innerHTML" not in page


def test_the_guides_storage_is_guarded(settings: Settings) -> None:
    module = _module(render_world_html(settings))
    uses = [line for line in module.splitlines() if "localStorage" in line]
    assert len(uses) == 2 and all("try { " in line and "catch (e)" in line for line in uses), uses
    assert "if (first) { chatterAt = simT + 6; if (plain && !guideSeen()) openGuide(); }" in module  # first visit
    assert "GUIDE_IDLE_MS = 30000" in module and "setTimeout(closeGuide, GUIDE_IDLE_MS)" in module  # never long
    guide = _js_body(module, "  function renderGuide() {")
    assert "t.plain_role" in guide and "r.line" in guide and "r.limits" in guide and "r.verdict" in guide
    assert "LIVE_CFG.pin" in guide  # the camera card says the pin's own length


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_the_guide_survives_blocked_storage(settings: Settings, tmp_path: Path) -> None:
    module = _module(render_world_html(settings))
    seen, remember = _js_body(module, "  function guideSeen() {"), _js_body(module, "  function guideRemember() {")
    out = _node(f"""
const store = {{}};
const window = {{ localStorage: {{ getItem: function (k) {{ return k in store ? store[k] : null; }},
  setItem: function (k, v) {{ store[k] = String(v); }} }} }};
const GUIDE_KEY = "nightcrawler.world.guide"; let guideShown = false;
{seen}
{remember}
const a = guideSeen(); guideRemember(); const b = guideSeen(); guideShown = false; const c = guideSeen();
Object.defineProperty(window, "localStorage", {{ get: function () {{ throw new Error("SecurityError"); }} }});
guideShown = false; const d = guideSeen(); let threw = false;
try {{ guideRemember(); }} catch (e) {{ threw = true; }}
console.log(JSON.stringify([a, b, c, d, threw, guideSeen()]));
""", tmp_path)
    # unseen, then remembered; read back from storage; blocked storage: unseen, no error, remembered for this visit
    assert out == [False, True, True, False, False, True]


def test_the_world_csp_follows_the_edit(settings: Settings) -> None:
    page = render_world_html(settings)
    (style,) = re.findall(r"<style>(.*?)</style>", page, flags=re.DOTALL)
    for text in (style, _module(page)):
        digest = "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"
        assert digest in WORLD_CSP
    assert page.count("<script") == 5
