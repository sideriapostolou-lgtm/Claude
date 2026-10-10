"""The 3D world at ``/world``: "Night Shift: Skyport", the owner's floating-island headquarters, filmed by a drone.

The owner handed over a professional art pack (``office_art/``: the world layout, the arrival drone shot, the
mission table, one workstation per member, the crew lineup). This page builds that world in three.js at the scale
of its cast and films it the way the pack asks: a drone 1.6-2.4 m above the walkway, a 24-35 mm lens, near
horizontal, close behind the crew; never a top-down tycoon view.

* The layout is the pack's canonical one, seen from the entrance bridge: the round mission courtyard with the mint
  holographic table in the middle, the raised observatory with its brass telescope at the rear, Pip's warm workshop
  on the left, Nyx's violet analysis den on the right, Mote's crystal archive front-left, Rook's stone vault and
  risk desk front-right, and on the outer right walkway Jet's courier dock (an airship moored) and a small espresso
  kiosk. Bridges, steps and open arches connect everything; a glass parcel tube runs along the rails.
* The cast (:data:`WORLD_CAST`) plays the same bot members as the 3D town (:data:`nightcrawler.office3d.CAST3D`):
  Voss the cobalt owl, Pip the orange fox, Nyx the lavender octopus, Rook the slate golem (twice the others' size),
  Mote in a glass bell on a brass cart and Jet the yellow capsule courier. The first frame draws each one
  procedurally (rounded, big animated-film eyes that blink, the lineup's costumes and colours), so the world is
  never empty while the real cast downloads.
* The real cast (``art/CAST_3D.md``): :data:`CAST_MODELS` names each member's rigged model, :data:`MOTION_FILES`
  the shared move library (``clips.glb`` and ``cast_manifest.json``) and the two modules that play it
  (``cast_rig.js``, ``cast_motion.js``). The page loads them progressively after the first frame (three.js's
  GLTFLoader with the meshopt decoder: the files are meshopt-compressed), the library and the six characters
  first, and swaps each drawing for its model with a quick fade; a missing or broken file keeps the drawing. Each
  biped walks with its own measured walk (Voss's penguin steps and glides, Pip's skip, Rook's heavy steps, Jet's
  quick walk), Nyx's tentacles ripple and Mote rides a clear glass bell (drawn in code) on its brass cart.
* Twelve hero props (:data:`PROP_MODELS`: the mission table, the telescope, the vault door, the workbench, Nyx's
  desk, the archive shelves, the airship, the kiosk, lanterns, flowered arches, Rook's desk, floating islands) take
  the place of the procedural pieces they supersede the same way, nearest the camera first.
* The acting comes from the ledger: whoever speaks a real event talks while the crew nearby turn and listen, a
  hand-off walks to the next department, Jet carries a closed trade's cube to the vault and cheers only for a win
  (a shrug for a loss), Rook nods at good news and worries at bad, a blocked or waiting member thinks, the
  Polymarket desk's lessons make Voss think, then talk. Idle members get ambient life (coffee, looking around,
  chatting with a neighbour) that shows no words and no numbers.
* The camera is live all the time (the module's LIVE DIRECTOR section): a director plans the next shot from what
  is happening now (a fresh event first, then whoever works at a station, then the life of the place), films it as
  one of a few moving shot types (close-up, over-the-shoulder, follow, low angle, crane, slow orbit, dolly,
  establishing wide; a 24-35 mm lens) and flies the drone between shots along the walkways (never over a wall or
  through one) or cuts. Its memory of each subject's last airtime and angle keeps every room and character on air.
  A chip pins the camera for 25 seconds, then it goes back to live; the LIVE tag says which.

Honesty rules (the same as the office's and the town's, non-negotiable):

* Every WORD on screen comes from ``/api/page`` (names, roles, status words, event text, money, the town line, the
  Polymarket desk's positions) or from the fixed descriptions in this module, and is inserted as text only (never
  as markup). The vault sign says ``money.usd`` and exactly ``money.label``.
* Nothing is invented: hand-off walks follow a new member event, Jet carries a cube to the vault only for a newly
  closed trade (gold won, red lost, the float shows ``pnl_usd``), the ticket board over the mission table lists the
  desk's own positions. Ambient life (coffee, typing, plants, drones, tube parcels) shows no words or numbers.
* When the API cannot be reached, the page says so in plain words and the world freezes.
* A footer line says the world is a visualisation of the bot's own ledger.

No external network: three.js and the addons it needs (:data:`ADDON_FILES`, three.js release
:data:`~nightcrawler.office3d.THREE_VERSION`, unmodified) are bundled in ``office_assets/`` and served at
``/office/assets/<name>`` from the :data:`WORLD_ASSETS` whitelist behind the dashboard token; an inline import map
resolves their bare ``three`` imports. The CSP allows scripts from this origin plus the inline module and import
map by their hashes only, and ``'wasm-unsafe-eval'`` for the meshopt decoder's bundled WebAssembly (nothing looser:
no ``eval``, no inline scripts). Built for phones: static geometry merged per material, instancing for plants,
railings and lanterns, the device pixel ratio capped at 1.75, one shadow-casting light (large screens only), soft
contact shadows under every character, bloom skipped on small or slow screens, smaller prop textures on small
screens, the ~20 MB of models never blocking the first frame, the loop paused while the tab is hidden and a plain
fallback line without WebGL.

Pure and static like :mod:`nightcrawler.office3d`: :func:`render_world_html` never puts ledger data into the HTML
(the only thing it reads from disk is which whitelisted model files exist).
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
from pathlib import Path

from nightcrawler.config import Settings
from nightcrawler.office import PIPELINE
from nightcrawler.office3d import CAST3D
from nightcrawler.page import MEMBERS, REFRESH_S

__all__ = [
    "ADDON_FILES",
    "ASSET_DIR",
    "CART_MODEL",
    "CAST_MODELS",
    "MOTION_FILES",
    "PROP_MODELS",
    "WORLD_ASSETS",
    "WORLD_CAST",
    "WORLD_CSP",
    "WORLD_ROOMS",
    "models_on_disk",
    "render_world_html",
    "world_asset_bytes",
]

#: Where the bundled files live (read at call time, so tests can point it at a temp dir).
ASSET_DIR = Path(__file__).resolve().parent / "office_assets"

_JS = "application/javascript; charset=utf-8"
_GLB = "model/gltf-binary"
#: The three.js 0.160.1 addons the world imports, copied unmodified from
#: ``https://cdn.jsdelivr.net/npm/three@0.160.1/examples/jsm/<name>`` (identical on unpkg); tests pin each SHA-256.
#: Every relative import inside them is in this list, and their bare ``three`` imports go through the import map.
#: The meshopt decoder unpacks the cast's compressed models (it instantiates its bundled WebAssembly, hence the
#: CSP's ``'wasm-unsafe-eval'``).
ADDON_FILES: tuple[str, ...] = (
    "addons/loaders/GLTFLoader.js",
    "addons/libs/meshopt_decoder.module.js",
    "addons/utils/BufferGeometryUtils.js",
    "addons/postprocessing/EffectComposer.js",
    "addons/postprocessing/RenderPass.js",
    "addons/postprocessing/UnrealBloomPass.js",
    "addons/postprocessing/OutputPass.js",
    "addons/postprocessing/ShaderPass.js",
    "addons/postprocessing/MaskPass.js",
    "addons/postprocessing/Pass.js",
    "addons/shaders/CopyShader.js",
    "addons/shaders/LuminosityHighPassShader.js",
    "addons/shaders/OutputShader.js",
)

#: The real cast (``art/CAST_3D.md``), one rigged or sculpted model per member. ``height`` is the character's
#: standing height in metres on the set (the model is scaled to it; the crew lineup's proportions, Rook towering),
#: ``yaw`` turns the model to face +Z, ``kind`` and ``walk`` say how it moves (the same as ``cast_manifest.json``,
#: which a test keeps in step). Mote's ``height`` is the whole travel bell on its cart; the creature inside is
#: ``body_height`` tall and the cart (:data:`CART_MODEL`) ``cart_height``.
CAST_MODELS: dict[str, dict[str, object]] = {
    "voss": {"asset": "cast_voss.glb", "height": 1.18, "yaw": 0.0, "kind": "biped", "walk": "walk_penguin"},
    "pip": {"asset": "cast_pip.glb", "height": 1.3, "yaw": 0.0, "kind": "biped", "walk": "walk_skip"},
    "nyx": {"asset": "cast_nyx.glb", "height": 0.9, "yaw": -1.5708, "kind": "octopus", "walk": None},
    "rook": {"asset": "cast_rook.glb", "height": 2.35, "yaw": 0.0, "kind": "biped", "walk": "walk_heavy"},
    "mote": {"asset": "cast_mote.glb", "height": 1.05, "yaw": -1.5708, "kind": "blob", "walk": None,
             "body_height": 0.4, "cart_height": 0.46},
    "jet": {"asset": "cast_jet.glb", "height": 0.85, "yaw": 0.0, "kind": "biped", "walk": "walk_quick"},
}
#: Mote's brass wheeled cart (the glass bell over it is drawn in code).
CART_MODEL = "cast_motecart.glb"

#: The twelve hero props (Tripo, 40k triangles, webp textures), each scaled to ``height`` metres and turned by
#: ``yaw`` to face +Z (the same as ``cast_manifest.json``'s props, which a test keeps in step); the page places
#: them in the canonical layout and removes the procedural pieces they supersede once they are in.
PROP_MODELS: dict[str, dict[str, object]] = {
    "missiontable": {"asset": "prop_missiontable.glb", "height": 1.0, "yaw": 0.0},
    "telescope": {"asset": "prop_telescope.glb", "height": 2.4, "yaw": 0.0},
    "vaultdoor": {"asset": "prop_vaultdoor.glb", "height": 2.6, "yaw": -1.5708},
    "workbench": {"asset": "prop_workbench.glb", "height": 1.05, "yaw": -1.5708},
    "nyxdesk": {"asset": "prop_nyxdesk.glb", "height": 1.5, "yaw": -1.5708},
    "archive": {"asset": "prop_archive.glb", "height": 2.8, "yaw": -1.5708},
    "airship": {"asset": "prop_airship.glb", "height": 3.2, "yaw": 0.0},
    "kiosk": {"asset": "prop_kiosk.glb", "height": 2.8, "yaw": -1.5708},
    "lantern": {"asset": "prop_lantern.glb", "height": 2.6, "yaw": 0.0},
    "arch": {"asset": "prop_arch.glb", "height": 3.4, "yaw": -1.5708},
    "rookdesk": {"asset": "prop_rookdesk.glb", "height": 1.3, "yaw": -1.5708},
    "island": {"asset": "prop_island.glb", "height": 6.0, "yaw": 0.0},
}

#: The move library and the modules that play it (art/CAST_3D.md): 21 moves on one reference skeleton, the
#: manifest (per move: loops or not, length, ground speed; per character: kind, size, facing), the retarget math and
#: the bodies in motion. The page imports ``cast_motion.js`` from this server; it imports ``cast_rig.js`` and
#: ``three`` (the import map).
MOTION_FILES: dict[str, str] = {
    "clips.glb": _GLB,
    "cast_manifest.json": "application/json",
    "cast_rig.js": "text/javascript; charset=utf-8",
    "cast_motion.js": "text/javascript; charset=utf-8",
}

#: The only files ``/office/assets/<name>`` serves for this page (exact names, no listing, no traversal), with
#: their media types. The three.js module itself is :data:`nightcrawler.office3d.ASSET_FILES`.
WORLD_ASSETS: dict[str, str] = {
    **{name: _JS for name in ADDON_FILES},
    **MOTION_FILES,
    **{str(spec["asset"]): _GLB for spec in CAST_MODELS.values()},
    CART_MODEL: _GLB,
    **{str(spec["asset"]): _GLB for spec in PROP_MODELS.values()},
}

#: The six actors: the bot members they play come from the 3D town's cast (one mapping for both pages), the rest
#: is the art pack's canonical cast (looks, the room they work in, how they move).
_CAST_LOOKS: dict[str, dict[str, str]] = {
    "voss": {"kind": "cobalt owl", "gait": "small steps and glides",
             "look": "golden eyes, teal waistcoat, violet cape with a brass clasp, a cyan tablet"},
    "pip": {"kind": "orange fox", "gait": "a springy walk, the tail for balance",
            "look": "white muzzle and tail tip, brass goggles with blue lenses, ivory shirt, brown harness"},
    "nyx": {"kind": "lavender octopus", "gait": "a tentacle crawl",
            "look": "dark intelligent eyes, a brass optic, eight compact arms"},
    "rook": {"kind": "slate golem", "gait": "heavy steps",
             "look": "amber eyes and fissures, a brass collar; twice everyone's size"},
    "mote": {"kind": "archivist in a glass bell", "gait": "rolls the bell along",
             "look": "a small translucent mint creature in a clear bell on a brass wheeled cart"},
    "jet": {"kind": "courier robot", "gait": "quick steps",
            "look": "a yellow capsule, black visor with cyan eyes, yellow boots, a messenger satchel"},
}


def _members_of(key: str) -> list[str]:
    raw = CAST3D[key]["members"]
    return [str(m) for m in raw] if isinstance(raw, list) else []


WORLD_CAST: dict[str, dict[str, object]] = {
    key: {
        "name": str(CAST3D[key]["name"]),
        "members": _members_of(key),
        "room": str(CAST3D[key]["office"]),
        "job": str(CAST3D[key]["job"]),
        **_CAST_LOOKS[key],
    }
    for key in ("voss", "pip", "nyx", "rook", "mote", "jet")
}

#: The departments, keyed like the town's offices: the members whose status lamp hangs at the door (every member
#: in exactly one room) and a fixed one-line description.
WORLD_ROOMS: dict[str, dict[str, object]] = {
    "table": {"title": "The mission table", "members": ["judge", "predict"],
              "line": "The round courtyard in the middle: every setup is argued over the holographic table."},
    "workshop": {"title": "The workshop", "members": ["crawler"],
                 "line": "Pip's bench on the left: where the raw material (brand-new coins) arrives."},
    "den": {"title": "The analysis den", "members": ["cocoon", "strategy", "radar"],
            "line": "Nyx's screens on the right: the scam filter, the setup, the danger check."},
    "vault": {"title": "The vault", "members": ["risk"],
              "line": "Rook's risk desk front-right; the sign over the vault door says what kind of money it is."},
    "archive": {"title": "The archive", "members": ["receipts"],
                "line": "Mote's crystal archive front-left: every decision and fill, chained."},
    "dock": {"title": "The courier dock", "members": ["broker"],
             "line": "Jet's dock on the outer walkway: the trades leave from here."},
    "observatory": {"title": "The observatory", "members": ["coach"],
                    "line": "Up the steps at the rear: the Coach's lab, what the team has learned."},
}


def world_asset_bytes(name: str) -> bytes | None:
    """The bundled file for a whitelisted name, else None (any other name is never looked up on disk)."""
    if name not in WORLD_ASSETS:
        return None
    try:
        return (ASSET_DIR / name).read_bytes()
    except OSError:
        return None


def models_on_disk() -> dict[str, object]:
    """What the page may load, from the whitelisted files that exist: ``motion`` (the move library, its manifest and
    both modules are all there: the bipeds can move), ``cast`` (members whose model exists, with their entry; Mote
    only with its cart), ``props`` (hero props whose model exists, with their entry)."""

    def there(name: str) -> bool:
        return (ASSET_DIR / name).is_file()

    cast: dict[str, dict[str, object]] = {}
    for key, spec in CAST_MODELS.items():
        if there(str(spec["asset"])) and (key != "mote" or there(CART_MODEL)):
            cast[key] = dict(spec, cart=CART_MODEL) if key == "mote" else dict(spec)
    props = {key: dict(spec) for key, spec in PROP_MODELS.items() if there(str(spec["asset"]))}
    return {"motion": all(there(name) for name in MOTION_FILES), "cast": cast, "props": props}


_STYLE = r"""
:root { color-scheme: dark; --fg: #f6efe2; --dim: #d4c8b3; --good: #5fe39a; --bad: #ff6b61; --warn: #f5b133;
        --brass: #e0b25e; --glass: rgba(24, 18, 44, .58); --glass2: rgba(20, 15, 38, .82); }
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; background: #1b1f4a; color: var(--fg);
             font: 15px/1.4 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
body { overflow: hidden; }
#view { position: fixed; inset: 0; width: 100%; height: 100%; display: block; touch-action: none; }
#vignette { position: fixed; inset: 0; pointer-events: none;
            background: radial-gradient(ellipse at 50% 55%, rgba(0,0,0,0) 58%, rgba(10,6,24,.42) 100%),
                        linear-gradient(to bottom, rgba(12,8,30,.55), rgba(0,0,0,0) 15%, rgba(0,0,0,0) 74%, rgba(12,8,30,.62)); }
header { position: fixed; top: 0; left: 0; right: 0; display: flex; align-items: center; gap: 10px;
         padding: calc(8px + env(safe-area-inset-top)) 14px 6px; pointer-events: none; }
header a, header .money { pointer-events: auto; }
header b.mode { font-size: 11px; letter-spacing: .14em; padding: 3px 9px; border-radius: 999px;
                background: rgba(60, 46, 100, .75); border: 1px solid rgba(224,178,94,.5); }
header b.mode.live { background: var(--bad); color: #fff; }
header a { color: var(--dim); text-decoration: none; font-size: 13px; text-shadow: 0 1px 2px #000; }
header .money { margin-left: auto; text-align: right; font-variant-numeric: tabular-nums;
                background: var(--glass); padding: 4px 10px; border-radius: 10px; border: 1px solid rgba(224,178,94,.35);
                backdrop-filter: blur(6px); }
header .money b { font-size: 16px; }
header .money small { display: block; font-size: 11px; color: var(--dim); }
header .money #clock { font-size: 10px; color: var(--dim); display: block; }
#foot { position: fixed; left: 14px; right: 14px; top: calc(52px + env(safe-area-inset-top)); font-size: 11px;
        color: var(--dim); text-shadow: 0 1px 2px #000, 0 0 6px rgba(0,0,0,.6); pointer-events: none; display: flex; }
#status { flex: 1 1 auto; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#status.bad { color: var(--bad); }
#loading { position: absolute; right: 11px; top: 7px; font-size: 10.5px; letter-spacing: .06em; color: var(--brass);
            font-variant-numeric: tabular-nums; white-space: nowrap; }
#loading[hidden] { display: none; }
#town { position: fixed; left: 14px; right: 14px; top: calc(68px + env(safe-area-inset-top)); font-size: 11px;
        line-height: 1.3; color: var(--dim); text-shadow: 0 1px 2px #000, 0 0 6px rgba(0,0,0,.6); pointer-events: none;
        max-height: 2.7em; overflow: hidden; }
.label { position: fixed; font-size: 11px; letter-spacing: .12em; text-transform: uppercase; font-weight: 700;
         color: var(--brass); text-shadow: 0 1px 3px #000, 0 0 8px rgba(0,0,0,.85); pointer-events: none;
         white-space: nowrap; transition: opacity .4s ease; }
#boot { position: fixed; left: 16px; right: 16px; top: 40%; text-align: center; font-size: 15px; color: var(--fg);
        background: var(--glass2); border: 1px solid rgba(224,178,94,.4); border-radius: 12px; padding: 14px; }
#boot.bad { border-color: var(--bad); }
#boot a { color: var(--brass); }
.bubble { position: fixed; max-width: min(72vw, 380px); background: #fbf5e8; color: #1d1a16; padding: 7px 12px 8px;
          border-radius: 14px; border: 2px solid var(--brass); font-size: 14px; line-height: 1.33;
          box-shadow: 0 8px 28px rgba(20,8,40,.5); pointer-events: none; transition: opacity .35s ease; }
.bubble:after { content: ""; position: absolute; left: var(--tail, 22px); bottom: -11px; border: 10px solid transparent;
                border-top-color: var(--brass); border-bottom: 0; }
.bubble.good { border-color: var(--good); } .bubble.good:after { border-top-color: var(--good); }
.bubble.bad { border-color: var(--bad); } .bubble.bad:after { border-top-color: var(--bad); }
.bubble small { display: block; color: #6c6356; font-size: 10.5px; letter-spacing: .1em; margin-bottom: 1px; font-weight: 700; }
#drop { position: fixed; font-weight: 800; font-size: 22px; pointer-events: none; opacity: 0;
        text-shadow: 0 1px 3px #000, 0 0 12px rgba(0,0,0,.7); font-variant-numeric: tabular-nums; }
#card { position: fixed; left: 12px; right: 12px; bottom: calc(76px + env(safe-area-inset-bottom));
        background: var(--glass); border: 1px solid rgba(224,178,94,.32); border-radius: 12px; padding: 7px 11px;
        backdrop-filter: blur(8px); max-width: 560px; }
#card .room { font-size: 10.5px; letter-spacing: .16em; color: var(--brass); font-weight: 700; display: flex; align-items: center; gap: 8px; }
#card .room .name { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#live { flex: 0 0 auto; font-size: 10px; letter-spacing: .14em; font-weight: 800; color: #fff; background: var(--bad);
        border-radius: 999px; padding: 1px 8px 1px 7px; cursor: pointer; text-transform: uppercase; }
#live::before { content: ""; display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #fff;
                margin-right: 5px; vertical-align: 1px; animation: livedot 1.4s ease-in-out infinite; }
#live.pinned { background: rgba(224,178,94,.92); color: #1d1a16; text-transform: none; letter-spacing: .04em; font-weight: 700; }
#live.pinned::before { animation: none; background: #1d1a16; }
@keyframes livedot { 0%, 100% { opacity: 1; } 50% { opacity: .3; } }
#card .who { font-weight: 700; font-size: 14px; margin-top: 1px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#card .who small { font-weight: 400; color: var(--dim); margin-left: 6px; font-size: 12px; }
#card .rows { margin-top: 3px; font-size: 12px; color: var(--dim); }
#card .rows div { display: flex; justify-content: space-between; gap: 10px; align-items: center; }
#card .rows div span:first-child { flex: 1 1 auto; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.status { display: inline-block; font-size: 10.5px; padding: 0 7px; border-radius: 999px; white-space: nowrap;
          background: rgba(255,255,255,.12); }
.status.working { background: rgba(95,227,154,.22); color: var(--good); }
.status.blocked { background: rgba(255,107,97,.28); color: var(--bad); }
.status.waiting { background: rgba(245,177,51,.2); color: var(--warn); }
.status.idle, .status.absent { color: var(--dim); }
#chips { position: fixed; left: 12px; right: 12px; bottom: calc(36px + env(safe-area-inset-bottom)); display: flex;
         gap: 6px; overflow-x: auto; scrollbar-width: none; }
#chips::-webkit-scrollbar { display: none; }
#chips button { flex: 0 0 auto; font: inherit; font-size: 12px; color: var(--fg); background: var(--glass);
                border: 1px solid rgba(224,178,94,.35); border-radius: 999px; padding: 4px 11px; cursor: pointer;
                min-height: 32px; backdrop-filter: blur(6px); }
#chips button.on { border-color: var(--brass); background: rgba(224,178,94,.28); }
#chips button.live { border-color: var(--bad); background: rgba(255,107,97,.3); font-weight: 700; letter-spacing: .06em; text-transform: uppercase; font-size: 11px; }
#chips button i { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; background: #6c717c; }
#chips button i.working { background: var(--good); } #chips button i.blocked { background: var(--bad); }
#chips button i.waiting { background: var(--warn); }
#honest { position: fixed; left: 12px; right: 12px; bottom: calc(10px + env(safe-area-inset-bottom)); margin: 0;
          font-size: 10.5px; color: var(--dim); text-align: center; text-shadow: 0 1px 2px #000; pointer-events: none;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
body.offline #view { filter: grayscale(.75) brightness(.7); }
"""

#: Resolves the addons' bare ``three`` imports (and the module's own) to the bundled files on this server.
_IMPORTMAP = json.dumps(
    {"imports": {"three": "./office/assets/three.module.min.js", "three/addons/": "./office/assets/addons/"}},
    separators=(",", ":"),
)

_M_SETUP = r"""
import * as THREE from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

const body = document.body;
const REFRESH_MS = Math.max(4000, 1000 * (parseInt(body.dataset.refresh, 10) || 15));
const PIPELINE = (body.dataset.pipeline || "").split(",").filter(Boolean);
const CAST = JSON.parse(document.getElementById("cast").textContent);
const ROOMS = JSON.parse(document.getElementById("rooms").textContent);
const MODELS = JSON.parse(document.getElementById("models").textContent);
const MODEL_CAST = MODELS.cast || {}, MODEL_PROPS = MODELS.props || {};
const HAS = function (id) { return !!MODEL_PROPS[id]; };  // a hero prop will replace its procedural stand-in
const MEMBERS = Array.from(document.querySelectorAll("#members span")).map(function (s) {
  return { id: s.dataset.id, name: s.dataset.name, role: s.dataset.role };
});
const el = function (id) { return document.getElementById(id); };
const boot = el("boot"), statusEl = el("status"), clockEl = el("clock"), townEl = el("town"), loadingEl = el("loading");
const moneyEl = el("money"), sinceEl = el("since"), modeEl = el("mode");
const bubblesEl = el("bubbles"), dropEl = el("drop"), card = el("card"), chips = el("chips"), labelsEl = el("labels");
const canvas = el("view");
const params = new URLSearchParams(location.search);
const LITE = params.get("lite") === "1", FULLQ = params.get("q") === "full";
let token = null;
if (params.has("token")) { token = params.get("token"); params.delete("token"); const q = params.toString();
  history.replaceState(null, "", location.pathname + (q ? "?" + q : "")); }

const nameOf = function (id) { const m = MEMBERS.find(function (x) { return x.id === id; }); return m ? m.name : id; };
const actorOf = {}, roomOf = {};
Object.keys(CAST).forEach(function (k) { CAST[k].members.forEach(function (m) { actorOf[m] = k; }); });
Object.keys(ROOMS).forEach(function (k) { ROOMS[k].members.forEach(function (m) { roomOf[m] = k; }); });
const clamp = THREE.MathUtils.clamp, lerp = THREE.MathUtils.lerp, smoothstep = THREE.MathUtils.smoothstep;
const TAU = Math.PI * 2;
function angleDiff(a, b) { return ((a - b + Math.PI) % TAU + TAU) % TAU - Math.PI; }
function fmtUsd(v) { return v == null ? "—" : (v < 0 ? "−" : "") + "$" + Math.abs(v).toFixed(2); }
function fmtSigned(v) { return v == null ? "—" : (v >= 0 ? "+" : "−") + "$" + Math.abs(v).toFixed(2); }
function fail(text) { boot.hidden = false; boot.textContent = text; boot.className = "bad"; canvas.hidden = true; }

let renderer = null;
try { renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: LITE, powerPreference: "high-performance" }); }
catch (e) { renderer = null; }
if (!renderer || !renderer.getContext()) {
  fail("This browser cannot draw the 3D world (no WebGL). The Office page shows the same team as pictures.");
} else {
  try { main(); } catch (e) { console.error(e); fail("The 3D world could not start in this browser. The Office page shows the same team as pictures."); }
}

function main() {
  // ------------------------------------------------------------- quality: phones first
  const W0 = window.innerWidth, H0 = window.innerHeight;
  const tiny = Math.min(W0, H0) < 340, slow = (navigator.hardwareConcurrency || 8) <= 2 || (navigator.deviceMemory || 8) <= 2;
  const Q = { dpr: LITE ? 1 : Math.min(1.75, window.devicePixelRatio || 1), bloom: !LITE && !tiny && !slow,
              shadows: !LITE && !slow && Math.min(W0, H0) >= 600, msaa: LITE ? 0 : 4,
              // phones: half-size prop textures (GPU memory) and fewer decorative copies (lanterns, islands)
              small: LITE || slow || Math.min(W0, H0) < 600 || (navigator.deviceMemory || 8) <= 4 };
  renderer.setPixelRatio(Q.dpr);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.08;
  renderer.shadowMap.enabled = Q.shadows;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(55, W0 / H0, 0.08, 1800);
  scene.add(camera);
  const uTime = { value: 0 };

  // ------------------------------------------------------------- small helpers
  function rng(seed) { let s = (seed * 2654435761) >>> 0 || 1;
    return function () { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; }; }
  const V3 = function (x, y, z) { return new THREE.Vector3(x, y, z); };
  const col = function (h) { return new THREE.Color(h); };
  const _e = new THREE.Euler(), _q = new THREE.Quaternion(), _p = new THREE.Vector3(), _s = new THREE.Vector3();
  function mat4(p, r, s) {
    _e.set(r ? r[0] : 0, r ? r[1] : 0, r ? r[2] : 0, "YXZ"); _q.setFromEuler(_e); _p.set(p ? p[0] : 0, p ? p[1] : 0, p ? p[2] : 0);
    if (typeof s === "number") _s.set(s, s, s); else _s.set(s ? s[0] : 1, s ? s[1] : 1, s ? s[2] : 1);
    return new THREE.Matrix4().compose(_p, _q, _s);
  }
  // paint a geometry's vertex colours: a hex, a Color (linear, may exceed 1 for glow) or fn(x, y, z, i) -> Color
  const _c = new THREE.Color();
  function paint(geo, c) {
    const pos = geo.attributes.position, n = pos.count, a = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const cc = typeof c === "function" ? c(pos.getX(i), pos.getY(i), pos.getZ(i), i) : c && c.isColor ? c : _c.set(c);
      a[i * 3] = cc.r; a[i * 3 + 1] = cc.g; a[i * 3 + 2] = cc.b;
    }
    geo.setAttribute("color", new THREE.BufferAttribute(a, 3)); return geo;
  }
  function hdr(h, k) { return new THREE.Color(h).multiplyScalar(k); }
  // shapes (always new geometries, so each can carry its own colours)
  const G = {
    box: function (w, h, d) { return new THREE.BoxGeometry(w, h, d); },
    sph: function (r, ws, hs, p0, pl, t0, tl) { return new THREE.SphereGeometry(r, ws || 28, hs || 18, p0, pl, t0, tl); },
    cyl: function (rt, rb, h, s, open) { return new THREE.CylinderGeometry(rt, rb, h, s || 20, 1, !!open); },
    cone: function (r, h, s) { return new THREE.ConeGeometry(r, h, s || 18); },
    tor: function (R, r, rs, ts, arc) { return new THREE.TorusGeometry(R, r, rs || 8, ts || 28, arc == null ? TAU : arc); },
    cap: function (r, l, cs, rs) { return new THREE.CapsuleGeometry(r, l, cs || 6, rs || 14); },
    ico: function (r, d) { return new THREE.IcosahedronGeometry(r, d || 0); },
    // a rounded box (superellipsoid): tactile, smooth-shaded, cheap
    rbox: function (w, h, d, e, seg) {
      const g = new THREE.SphereGeometry(1, seg || 24, Math.max(8, Math.round((seg || 24) * 0.66)));
      const p = g.attributes.position, k = e == null ? 0.28 : e;
      for (let i = 0; i < p.count; i++) {
        const x = p.getX(i), y = p.getY(i), z = p.getZ(i);
        p.setXYZ(i, Math.sign(x) * Math.pow(Math.abs(x), k) * w / 2, Math.sign(y) * Math.pow(Math.abs(y), k) * h / 2,
                 Math.sign(z) * Math.pow(Math.abs(z), k) * d / 2);
      }
      g.computeVertexNormals(); return g;
    },
    // an arc of torus lying flat (xz plane) from angle a0 to a1 (atan2(z, x))
    arc: function (R, r, a0, a1, ts) { return new THREE.TorusGeometry(R, r, 6, ts || Math.max(6, Math.round(Math.abs(a1 - a0) * R * 3)), a1 - a0).rotateX(Math.PI / 2).rotateY(-a0); },
  };
  // a crag: an icosahedron pushed about, flat-shaded (rock chunks for the golem and the island)
  function crag(r, detail, seed, squash) {
    const g = new THREE.IcosahedronGeometry(r, detail == null ? 1 : detail), p = g.attributes.position, rr = rng(seed || 1);
    const seen = new Map();
    for (let i = 0; i < p.count; i++) {
      const key = Math.round(p.getX(i) * 1000) + "," + Math.round(p.getY(i) * 1000) + "," + Math.round(p.getZ(i) * 1000);
      let k = seen.get(key); if (k == null) { k = 0.82 + rr() * 0.3; seen.set(key, k); }
      p.setXYZ(i, p.getX(i) * k, p.getY(i) * k * (squash || 1), p.getZ(i) * k);
    }
    g.computeVertexNormals(); return g;
  }
  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.lineTo(x + w - r, y); ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r); ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h); ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r); ctx.lineTo(x, y + r); ctx.quadraticCurveTo(x, y, x + r, y); ctx.closePath();
  }

  // ------------------------------------------------------------- procedural textures (drawn once, no files)
  const maxAniso = Math.min(8, renderer.capabilities.getMaxAnisotropy());
  function canvasTex(w, h, draw, linear) {
    const c = document.createElement("canvas"); c.width = w; c.height = h;
    const ctx = c.getContext("2d"); if (ctx) draw(ctx, w, h);
    const t = new THREE.CanvasTexture(c); t.colorSpace = linear ? THREE.NoColorSpace : THREE.SRGBColorSpace;
    t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = maxAniso; return t;
  }
  function grey(v, a) { return "rgba(" + v + "," + v + "," + v + "," + (a == null ? 1 : a) + ")"; }
  // worn stone pavers in running rows (greyscale: the vertex colour gives the tint)
  const paverTex = canvasTex(512, 512, function (ctx, w, h) {
    const r = rng(11); ctx.fillStyle = grey(150); ctx.fillRect(0, 0, w, h);
    const rows = 8, rh = h / rows;
    for (let j = 0; j < rows; j++) {
      let x = -r() * 80;
      while (x < w) {
        const sw = 56 + r() * 76, v = 214 + Math.floor(r() * 38);
        [0, -w].forEach(function (o) { ctx.fillStyle = grey(v); roundRect(ctx, x + o + 3, j * rh + 3, sw - 6, rh - 6, 8); ctx.fill();
          ctx.fillStyle = grey(255, 0.12); roundRect(ctx, x + o + 6, j * rh + 5, sw - 14, 10, 5); ctx.fill(); });
        x += sw;
      }
    }
    for (let i = 0; i < 3200; i++) { ctx.fillStyle = r() > 0.5 ? grey(255, 0.08) : grey(60, 0.07); ctx.fillRect(r() * w, r() * h, 2, 2); }
  });
  // carved ashlar blocks for the walls
  const ashlarTex = canvasTex(512, 512, function (ctx, w, h) {
    const r = rng(23); ctx.fillStyle = grey(176); ctx.fillRect(0, 0, w, h);
    const rh = h / 4;
    for (let j = 0; j < 4; j++) {
      const off = j % 2 ? 128 : 0;
      for (let i = -1; i < 3; i++) {
        const x = i * 256 + off, v = 222 + Math.floor(r() * 30);
        ctx.fillStyle = grey(v); roundRect(ctx, x + 3, j * rh + 3, 250, rh - 6, 10); ctx.fill();
        const g = ctx.createLinearGradient(0, j * rh, 0, j * rh + rh); g.addColorStop(0, grey(255, 0.14)); g.addColorStop(1, grey(0, 0.1));
        ctx.fillStyle = g; roundRect(ctx, x + 3, j * rh + 3, 250, rh - 6, 10); ctx.fill();
      }
    }
    for (let i = 0; i < 4000; i++) { ctx.fillStyle = r() > 0.5 ? grey(255, 0.06) : grey(40, 0.06); ctx.fillRect(r() * w, r() * h, 2, 2); }
  });
  // walnut planks with grain
  const woodTex = canvasTex(256, 512, function (ctx, w, h) {
    const r = rng(5), pw = w / 4;
    for (let i = 0; i < 4; i++) {
      const v = 190 + Math.floor(r() * 50); ctx.fillStyle = grey(v); ctx.fillRect(i * pw, 0, pw, h);
      for (let k = 0; k < 26; k++) { const x0 = i * pw + r() * pw, a = 0.05 + r() * 0.12; ctx.strokeStyle = r() > 0.5 ? grey(80, a) : grey(255, a * 0.6);
        ctx.lineWidth = 1 + r() * 2; ctx.beginPath(); for (let y = 0; y <= h; y += 16) ctx.lineTo(x0 + Math.sin(y * 0.02 + k) * 3, y); ctx.stroke(); }
      ctx.fillStyle = grey(40, 0.55); ctx.fillRect(i * pw, 0, 2, h);
      const cut = r() * h; ctx.fillRect(i * pw, cut, pw, 2);
    }
  });
  // feather scallops (the owl), speckles (the octopus), fur strokes (the fox)
  const featherTex = canvasTex(256, 256, function (ctx, w, h) {
    ctx.fillStyle = grey(200); ctx.fillRect(0, 0, w, h);
    for (let j = -1; j < 11; j++) for (let i = -1; i < 9; i++) {
      const x = i * 32 + (j % 2 ? 16 : 0), y = j * 24;
      const g = ctx.createRadialGradient(x, y + 8, 2, x, y, 20); g.addColorStop(0, grey(255)); g.addColorStop(0.7, grey(232)); g.addColorStop(1, grey(170));
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, 18, 0, Math.PI); ctx.fill();
      ctx.strokeStyle = grey(150, 0.5); ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(x, y, 18, 0.2, Math.PI - 0.2); ctx.stroke();
    }
  });
  const speckleTex = canvasTex(256, 256, function (ctx, w, h) {
    const r = rng(9); ctx.fillStyle = grey(218); ctx.fillRect(0, 0, w, h);
    for (let i = 0; i < 520; i++) { const s = 1 + r() * 3.2; ctx.fillStyle = r() > 0.25 ? grey(255, 0.85) : grey(150, 0.5);
      ctx.beginPath(); ctx.arc(r() * w, r() * h, s, 0, TAU); ctx.fill(); }
  });
  const furTex = canvasTex(256, 256, function (ctx, w, h) {
    const r = rng(17); ctx.fillStyle = grey(225); ctx.fillRect(0, 0, w, h);
    for (let i = 0; i < 1600; i++) { const x = r() * w, y = r() * h, l = 4 + r() * 9; ctx.strokeStyle = r() > 0.5 ? grey(255, 0.5) : grey(150, 0.35);
      ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + (r() - 0.5) * 3, y + l); ctx.stroke(); }
  });
  // a soft round glow (halos, steam)
  const glowTex = canvasTex(64, 64, function (ctx) {
    const g = ctx.createRadialGradient(32, 32, 1, 32, 32, 32);
    g.addColorStop(0, "rgba(255,255,255,1)"); g.addColorStop(0.3, "rgba(255,255,255,.45)"); g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g; ctx.fillRect(0, 0, 64, 64);
  });
  glowTex.wrapS = glowTex.wrapT = THREE.ClampToEdgeWrapping;

  // ------------------------------------------------------------- shared materials (vertex-coloured, so one per surface)
  const MAT = {
    stone: new THREE.MeshStandardMaterial({ vertexColors: true, map: ashlarTex, roughness: 0.86, envMapIntensity: 0.5 }),
    pavers: new THREE.MeshStandardMaterial({ vertexColors: true, map: paverTex, roughness: 0.78, envMapIntensity: 0.55 }),
    plain: new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.8, envMapIntensity: 0.5 }),
    brass: new THREE.MeshStandardMaterial({ vertexColors: true, metalness: 0.9, roughness: 0.3, envMapIntensity: 1.35 }),
    iron: new THREE.MeshStandardMaterial({ vertexColors: true, metalness: 0.6, roughness: 0.45, envMapIntensity: 0.9 }),
    wood: new THREE.MeshStandardMaterial({ vertexColors: true, map: woodTex, roughness: 0.5, envMapIntensity: 0.7 }),
    cloth: new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.92, side: THREE.DoubleSide, envMapIntensity: 0.4 }),
    rock: new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.96, flatShading: true, envMapIntensity: 0.35 }),
    leaf: new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.7, envMapIntensity: 0.45 }),
    glass: new THREE.MeshPhysicalMaterial({ color: 0xffffff, roughness: 0.04, transparent: true, opacity: 0.14, clearcoat: 1,
                                            clearcoatRoughness: 0.03, envMapIntensity: 2.2, depthWrite: false, side: THREE.DoubleSide }),
    glow: new THREE.MeshBasicMaterial({ vertexColors: true }),
  };
  // plants sway in the wind (instanced leaves only: each instance by its own position)
  MAT.leaf.onBeforeCompile = function (sh) {
    sh.uniforms.uTime = uTime;
    sh.vertexShader = "uniform float uTime;\n" + sh.vertexShader.replace("#include <begin_vertex>", [
      "#include <begin_vertex>", "#ifdef USE_INSTANCING", "vec3 ip = instanceMatrix[3].xyz;",
      "float sway = sin(uTime * 1.3 + ip.x * 0.7 + ip.z * 0.4) * 0.05 + sin(uTime * 2.7 + ip.z * 1.3) * 0.02;",
      "transformed.x += sway * (position.y + 0.5); transformed.z += sway * 0.5 * (position.y + 0.5);", "#endif"].join("\n"));
  };
  const UVSCALE = { stone: 2.2, pavers: 2.6, wood: 1.6 };

  // ------------------------------------------------------------- static geometry, merged per material
  const buckets = new Map();
  function pushBucket(key, geo) { if (!buckets.has(key)) buckets.set(key, []); buckets.get(key).push(geo); }
  // a frame: a room's own coordinates (x across, z towards its door, y up), placed and turned in the world
  function roomFrame(x, y, z, yaw) {
    const q = new THREE.Quaternion().setFromAxisAngle(V3(0, 1, 0), yaw || 0);
    const M = new THREE.Matrix4().compose(V3(x, y, z), q, V3(1, 1, 1));
    return {
      M: M, yaw: yaw || 0, origin: V3(x, y, z),
      add: function (key, geo, p, r, s, c) { if (c != null) paint(geo, c); geo.applyMatrix4(mat4(p, r, s)).applyMatrix4(M); pushBucket(key, geo); return geo; },
      at: function (lx, ly, lz) { return V3(lx, ly, lz).applyMatrix4(M); },
      place: function (obj, lx, ly, lz, ry) { obj.position.copy(V3(lx, ly, lz).applyMatrix4(M)); obj.rotation.y = (yaw || 0) + (ry || 0); scene.add(obj); return obj; },
    };
  }
  const WF = roomFrame(0, 0, 0, 0);
  function prep(geo) {
    if (!geo.index) { const n = geo.attributes.position.count, idx = new Uint32Array(n); for (let i = 0; i < n; i++) idx[i] = i; geo.setIndex(new THREE.BufferAttribute(idx, 1)); }
    Object.keys(geo.attributes).forEach(function (k) { if (k !== "position" && k !== "normal" && k !== "uv" && k !== "color") geo.deleteAttribute(k); });
    if (!geo.attributes.normal) geo.computeVertexNormals();
    if (!geo.attributes.uv) geo.setAttribute("uv", new THREE.BufferAttribute(new Float32Array(geo.attributes.position.count * 2), 2));
    if (!geo.attributes.color) paint(geo, 0xffffff);
    geo.morphAttributes = {}; geo.clearGroups();
    return geo;
  }
  function worldUV(geo, scale) {
    const p = geo.attributes.position, n = geo.attributes.normal, uv = geo.attributes.uv;
    for (let i = 0; i < p.count; i++) {
      const ax = Math.abs(n.getX(i)), ay = Math.abs(n.getY(i)), az = Math.abs(n.getZ(i));
      if (ay >= ax && ay >= az) uv.setXY(i, p.getX(i) / scale, p.getZ(i) / scale);
      else if (ax >= az) uv.setXY(i, p.getZ(i) / scale, p.getY(i) / scale);
      else uv.setXY(i, p.getX(i) / scale, p.getY(i) / scale);
    }
    uv.needsUpdate = true;
  }
  const staticMeshes = [];
  function flushStatic() {
    buckets.forEach(function (list, key) {
      const geo = mergeGeometries(list.map(prep), false); if (!geo) { console.warn("could not merge " + key); return; }
      if (UVSCALE[key]) worldUV(geo, UVSCALE[key]);
      geo.computeBoundingSphere();
      const m = new THREE.Mesh(geo, MAT[key]);
      m.receiveShadow = key !== "glow" && key !== "glass";
      m.castShadow = Q.shadows && (key === "stone" || key === "wood" || key === "brass" || key === "plain" || key === "iron" || key === "cloth");
      m.matrixAutoUpdate = false; m.updateMatrix(); if (key === "glass") m.renderOrder = 2;
      scene.add(m); staticMeshes.push(m);
    });
    buckets.clear();
  }
  function instanced(geo, mat, list, cast) {
    const im = new THREE.InstancedMesh(prep(geo), mat, Math.max(1, list.length)); im.count = list.length;
    list.forEach(function (it, i) { im.setMatrixAt(i, mat4(it.p, it.r, it.s)); if (it.c != null) im.setColorAt(i, it.c.isColor ? it.c : col(it.c)); });
    im.instanceMatrix.needsUpdate = true; if (im.instanceColor) im.instanceColor.needsUpdate = true;
    im.castShadow = !!cast && Q.shadows; im.receiveShadow = true; im.computeBoundingSphere(); scene.add(im); return im;
  }
  // a procedural stand-in for a hero prop: what fn() builds is merged into its own group (not the shared static
  // meshes), so it can fade away when the prop's model is in place (and stays if the model never arrives)
  const STANDIN = {};
  let standinBooks = null;
  function standin(key, fn) {
    const saved = new Map(buckets); buckets.clear(); standinBooks = [];
    try { fn(); } finally {
      const g = new THREE.Group(); g.name = "standin:" + key;
      buckets.forEach(function (list, k) {
        const geo = mergeGeometries(list.map(prep), false); if (!geo) return;
        if (UVSCALE[k]) worldUV(geo, UVSCALE[k]); geo.computeBoundingSphere();
        const m = new THREE.Mesh(geo, MAT[k]); m.receiveShadow = k !== "glow" && k !== "glass";
        m.castShadow = Q.shadows && k !== "glow" && k !== "glass" && k !== "leaf"; if (k === "glass") m.renderOrder = 2; g.add(m);
      });
      if (standinBooks.length) g.add(instanced(paint(G.box(1, 1, 1), 0xffffff), MAT.plain, standinBooks, false));
      buckets.clear(); saved.forEach(function (v, k) { buckets.set(k, v); }); standinBooks = null;
      scene.add(g); (STANDIN[key] = STANDIN[key] || []).push(g);
    }
  }

  // ------------------------------------------------------------- sky, sun, clouds (blue hour; the viewer's clock tints it)
  const GLSL_NOISE = [
    "float hash2(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }",
    "float vnoise(vec2 p) { vec2 i = floor(p), f = fract(p); vec2 u = f * f * (3.0 - 2.0 * f);",
    "  return mix(mix(hash2(i), hash2(i + vec2(1.0, 0.0)), u.x), mix(hash2(i + vec2(0.0, 1.0)), hash2(i + vec2(1.0, 1.0)), u.x), u.y); }",
    "float fbm(vec2 p) { float v = 0.0, a = 0.5; for (int i = 0; i < 5; i++) { v += a * vnoise(p); p = p * 2.03 + 17.1; a *= 0.5; } return v; }",
  ].join("\n");
  const sunDir = V3(-0.84, 0.085, 0.32).normalize();  // low in the west: left of the arrival view
  const skyU = { uTop: { value: col(0x161a52) }, uMid: { value: col(0x4d3f93) }, uHorizon: { value: col(0xf2a07a) },
                 uBelow: { value: col(0xa486c4) }, uSunDir: { value: sunDir.clone() }, uSunCol: { value: col(0xffb98a) },
                 uStars: { value: 0.7 }, uTime: uTime };
  const skyMat = new THREE.ShaderMaterial({
    uniforms: skyU, side: THREE.BackSide, depthWrite: false, fog: false,
    vertexShader: "varying vec3 vDir; void main() { vDir = position; vec4 p = projectionMatrix * modelViewMatrix * vec4(position, 1.0); gl_Position = p.xyww; }",
    fragmentShader: [
      "uniform vec3 uTop, uMid, uHorizon, uBelow, uSunDir, uSunCol; uniform float uStars, uTime; varying vec3 vDir;",
      "float h3(vec3 p) { p = fract(p * 0.3183099 + 0.1); p *= 17.0; return fract(p.x * p.y * p.z * (p.x + p.y + p.z)); }",
      "void main() {",
      "  vec3 d = normalize(vDir); float h = d.y; float s = max(dot(d, uSunDir), 0.0);",
      "  vec3 hor = mix(mix(uHorizon, uMid, 0.45), uHorizon, pow(s, 1.5));",
      "  vec3 c = mix(hor, uMid, smoothstep(0.0, 0.34, h)); c = mix(c, uTop, smoothstep(0.22, 0.92, h));",
      "  c = mix(c, uBelow, smoothstep(0.0, -0.3, h));",
      "  c += uSunCol * (pow(s, 5.0) * 0.4 + pow(s, 60.0) * 0.9 + pow(s, 1200.0) * 8.0);",
      "  vec3 sp = d * 190.0; vec3 cell = floor(sp); float r = h3(cell); float star = step(0.986, r) * smoothstep(0.45, 0.05, length(fract(sp) - 0.5));",
      "  float tw = 0.55 + 0.45 * sin(uTime * (0.8 + r * 3.0) + r * 60.0);",
      "  c += vec3(1.0, 0.94, 0.86) * star * tw * uStars * smoothstep(0.06, 0.5, h) * 1.6;",
      "  gl_FragColor = vec4(c, 1.0);",
      "  #include <tonemapping_fragment>", "  #include <colorspace_fragment>",
      "}"].join("\n"),
  });
  const sky = new THREE.Mesh(new THREE.SphereGeometry(900, 48, 24), skyMat); sky.frustumCulled = false; sky.renderOrder = -10; scene.add(sky);
  scene.fog = new THREE.Fog(0xb294c4, 70, 520);

  // the cloud sea under the island: soft peach tops lit by the low sun, lilac in the shade
  const cloudU = { uTime: uTime, uSunDir: { value: sunDir.clone() }, uLit: { value: col(0xffc7a6) }, uShade: { value: col(0x7d64b4) },
                   uFar: { value: col(0xb89ac8) }, uCam: { value: V3(0, 0, 0) } };
  const cloudSea = new THREE.Mesh(new THREE.PlaneGeometry(3000, 3000, 1, 1).rotateX(-Math.PI / 2), new THREE.ShaderMaterial({
    uniforms: cloudU, fog: false, depthWrite: true,
    vertexShader: "varying vec3 vW; void main() { vec4 w = modelMatrix * vec4(position, 1.0); vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }",
    fragmentShader: [GLSL_NOISE,
      "uniform float uTime; uniform vec3 uSunDir, uLit, uShade, uFar, uCam; varying vec3 vW;",
      "void main() {",
      "  vec2 p = vW.xz * 0.018 + vec2(uTime * 0.012, uTime * 0.004);",
      "  float n = fbm(p) * 0.75 + fbm(p * 2.7 - uTime * 0.01) * 0.35;",
      "  float lit = clamp(n * 1.4 - 0.35 + dot(normalize(vec2(-uSunDir.x, -uSunDir.z)), normalize(vW.xz + 0.001)) * -0.18, 0.0, 1.0);",
      "  vec3 c = mix(uShade, uLit, smoothstep(0.15, 0.95, lit));",
      "  float dist = length(vW.xz - uCam.xz); c = mix(c, uFar, smoothstep(160.0, 1100.0, dist));",
      "  gl_FragColor = vec4(c * 1.05, 1.0);",
      "  #include <tonemapping_fragment>", "  #include <colorspace_fragment>",
      "}"].join("\n"),
  }));
  cloudSea.position.y = -26; scene.add(cloudSea);
  // cloud banks: one instanced billboard draw for every puff
  const puffMat = new THREE.ShaderMaterial({
    uniforms: { uTime: uTime, uLit: cloudU.uLit, uShade: cloudU.uShade, uSunDir: cloudU.uSunDir },
    transparent: true, depthWrite: false, fog: false,
    vertexShader: [
      "varying vec2 vUv; varying float vSeed; varying float vSide;",
      "uniform vec3 uSunDir;",
      "void main() { vUv = uv; vec4 c = modelViewMatrix * instanceMatrix * vec4(0.0, 0.0, 0.0, 1.0);",
      "  float s = length(instanceMatrix[0].xyz); vSeed = fract(instanceMatrix[3].x * 0.137 + instanceMatrix[3].z * 0.071);",
      "  vSide = dot(normalize(instanceMatrix[3].xz + 0.01), normalize(uSunDir.xz));",
      "  c.xy += position.xy * vec2(s, s * 0.55); gl_Position = projectionMatrix * c; }"].join("\n"),
    fragmentShader: [GLSL_NOISE,
      "uniform float uTime; uniform vec3 uLit, uShade; varying vec2 vUv; varying float vSeed; varying float vSide;",
      "void main() { vec2 q = vUv - 0.5; float n = fbm(vUv * 3.0 + vSeed * 20.0 + uTime * 0.01);",
      "  float a = smoothstep(0.5, 0.12, length(q * vec2(1.0, 1.3)) + (n - 0.5) * 0.35);",
      "  vec3 c = mix(uShade, uLit, clamp(vUv.y * 0.9 + n * 0.5 + vSide * 0.25 - 0.1, 0.0, 1.0));",
      "  gl_FragColor = vec4(c * 1.08, a * 0.9);",
      "  #include <tonemapping_fragment>", "  #include <colorspace_fragment>",
      "}"].join("\n"),
  });
  (function () {
    const r = rng(31), list = [];
    for (let i = 0; i < (LITE ? 30 : 64); i++) {
      const a = r() * TAU, d = 26 + r() * 150, s = 14 + r() * 34;
      list.push({ p: [Math.cos(a) * d, -24 + r() * 12 - (d > 100 ? 0 : 2), Math.sin(a) * d], s: s });
    }
    for (let i = 0; i < 14; i++) { const a = r() * TAU, d = 300 + r() * 250; list.push({ p: [Math.cos(a) * d, -6 + r() * 26, Math.sin(a) * d], s: 70 + r() * 90 }); }
    const im = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 1), puffMat, list.length);
    list.forEach(function (it, i) { im.setMatrixAt(i, mat4(it.p, null, it.s)); });
    im.frustumCulled = false; im.renderOrder = 1; scene.add(im);
  })();

  // the environment the brass and glass reflect: this same sky with warm lit windows round the horizon
  const pmrem = new THREE.PMREMGenerator(renderer);
  function buildEnv() {
    const es = new THREE.Scene();
    es.add(new THREE.Mesh(new THREE.SphereGeometry(60, 32, 16), skyMat));
    const lampM = new THREE.MeshBasicMaterial({ color: hdr(0xffb46a, 2.4) });
    for (let i = 0; i < 12; i++) { const a = i / 12 * TAU, m = new THREE.Mesh(new THREE.PlaneGeometry(5 + (i % 3) * 2, 2.5), lampM);
      m.position.set(Math.cos(a) * 28, (i % 4) * 0.8 - 0.5, Math.sin(a) * 28); m.lookAt(0, 0, 0); es.add(m); }
    const fl = new THREE.Mesh(new THREE.CircleGeometry(40, 24), new THREE.MeshBasicMaterial({ color: 0x4a3640 })); fl.rotation.x = -Math.PI / 2; fl.position.y = -3; es.add(fl);
    const t = pmrem.fromScene(es, 0.03).texture; es.traverse(function (o) { if (o.geometry) o.geometry.dispose(); }); return t;
  }
  scene.environment = buildEnv();

  // ------------------------------------------------------------- lights: blue hour, a low warm sun, the room practicals
  const hemi = new THREE.HemisphereLight(0xb4a2ff, 0x6a4a3c, 1.25);
  const sun = new THREE.DirectionalLight(0xffb27c, 2.6);
  sun.position.copy(sunDir).multiplyScalar(60); scene.add(hemi, sun, sun.target);
  if (Q.shadows) {
    sun.castShadow = true; sun.shadow.mapSize.set(1024, 1024);
    const sc = sun.shadow.camera; sc.left = -13; sc.right = 13; sc.top = 13; sc.bottom = -13; sc.near = 1; sc.far = 140;
    sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.03; sun.shadow.radius = 3;
  }
  const rimFill = new THREE.DirectionalLight(0x7f8cff, 0.55); rimFill.position.set(30, 22, -40); scene.add(rimFill);
  const practicals = {};
  function practical(key, color, x, y, z, intensity, dist) {
    const L = new THREE.PointLight(color, intensity, dist || 10, 2); L.position.set(x, y, z); scene.add(L);
    practicals[key] = { light: L, base: intensity }; return L;
  }
"""

_M_WORLD = r"""
  // ============================================================= THE WORLD (metres; y up; the entrance is +z)
  const CREAM = 0xf0e3cb, CREAM2 = 0xe2d2b4, STONE_DARK = 0xa8957d, BRASS = 0xe0ad55, BRASS_DARK = 0xb07f38, COPPER = 0xc9814e,
        WALNUT = 0x8a5634, WALNUT_DARK = 0x5a3420, LEATHER = 0x7e3a26, IRON = 0x3a3540, TERRA = 0xc46a42, PAPER = 0xf1e8d2;
  const COURT_R = 6.2;
  const RF = {
    workshop: roomFrame(-11.8, 0, -3, Math.PI / 2),
    den: roomFrame(11.8, 0, -3, -Math.PI / 2),
    archive: roomFrame(-9.8, 0, 9.4, 3 * Math.PI / 4),
    vault: roomFrame(9.8, 0, 9.4, -3 * Math.PI / 4),
    observatory: roomFrame(0, 1.8, -15.5, 0),
  };
  const blockers = [];  // solid wall pieces the drone will not fly through (oriented boxes)
  function blocker(F, cx, cy, cz, ry, hx, hy, hz) {
    const m = new THREE.Matrix4().multiplyMatrices(F.M, mat4([cx, cy, cz], [0, ry, 0], 1));
    blockers.push({ inv: m.clone().invert(), half: V3(hx, hy, hz) });
  }
  function bar(key, a, b, r, c, seg) {
    const d = b.clone().sub(a), len = d.length(); if (len < 1e-4) return;
    const g = G.cyl(r, r, len, seg || 8); g.translate(0, len / 2, 0);
    g.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(V3(0, 1, 0), d.normalize())); g.translate(a.x, a.y, a.z);
    paint(g, c); pushBucket(key, g);
  }
  const railPosts = [], lanterns = [], bushes = [], blooms = [], leaves = [], racemes = [], cypresses = [], books = [];

  // ------------------------------------------------------------- the floating island: discs of rock under paved ground
  const DISCS = [[0, 0, 8.6, 0], [-11.8, -3, 6.2, 0], [11.8, -3, 6.2, 0], [-9.8, 9.4, 5.5, 0], [9.8, 9.4, 5.5, 0],
                 [0, -15.5, 6.8, 1.8], [-6.6, 3.4, 4.0, 0], [6.6, 3.4, 4.0, 0], [13.1, 3.9, 3.1, 0], [-13.1, 3.9, 3.1, 0],
                 [-6.6, -8.8, 4.3, 0], [6.6, -8.8, 4.3, 0], [0, -7.9, 3.8, 0]];
  const onIsland = function (x, z, m) { return DISCS.some(function (d) { return Math.hypot(x - d[0], z - d[1]) < d[2] - (m || 0); }); };
  DISCS.forEach(function (d, i) {
    const r = d[2], top = d[3], depth = 7 + r * 1.5, rr = rng(40 + i);
    const prof = [[0.02, -10.4], [0.14, -9.3], [0.3, -7.8], [0.5, -6.0], [0.68, -4.2], [0.84, -2.6], [0.96, -1.3], [1.03, -0.45], [1.0, 0]];
    const pts = prof.map(function (q) { return new THREE.Vector2(r * q[0], top - 0.08 + q[1] * depth / 10.4); });
    const g = new THREE.LatheGeometry(pts, 26), p = g.attributes.position, seen = new Map();
    for (let k = 0; k < p.count; k++) {
      const y = p.getY(k); if (y > top - 0.1) continue;
      const key = Math.round(p.getX(k) * 100) + "," + Math.round(y * 100) + "," + Math.round(p.getZ(k) * 100);
      let j = seen.get(key); if (!j) { j = [0.84 + rr() * 0.32, (rr() - 0.5) * 0.5]; seen.set(key, j); }
      p.setXYZ(k, p.getX(k) * j[0], y + j[1], p.getZ(k) * j[0]);
    }
    const cTop = col(0x8b6a5c), cBot = col(0x45364f);
    WF.add("rock", g, [d[0], 0, d[1]], null, null, function (x, y) { return _c.copy(cBot).lerp(cTop, clamp((y - top + depth) / depth, 0, 1)); });
    WF.add("pavers", G.cyl(r, r, 0.12, 56), [d[0], top - 0.06 - i * 0.004, d[1]], null, null, 0xcdb99b);
    // a mossy lip round the rim
    WF.add("leaf", G.tor(r - 0.05, 0.12, 6, 56), [d[0], top - 0.1, d[1]], [Math.PI / 2, 0, 0], [1, 1, 0.6], 0x4d7a3e);
  });
  // the observatory terrace stands on a carved retaining wall
  WF.add("stone", G.cyl(6.86, 6.9, 1.8, 64, true), [0, 0.9, -15.5], null, null, CREAM2);
  WF.add("brass", G.tor(6.88, 0.04, 6, 96), [0, 1.78, -15.5], [Math.PI / 2, 0, 0], null, BRASS);

  // waterfalls off the rim, into the clouds (one merged strip mesh, a scrolling shader)
  const fallMat = new THREE.ShaderMaterial({
    uniforms: { uTime: uTime }, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide, fog: false,
    vertexShader: "varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: [GLSL_NOISE, "uniform float uTime; varying vec2 vUv;",
      "void main() { float s = vUv.y * 9.0 + uTime * 1.6; float n = vnoise(vec2(vUv.x * 10.0, s)) * 0.7 + vnoise(vec2(vUv.x * 23.0, s * 1.7)) * 0.3;",
      "  float streak = smoothstep(0.3, 0.9, n); float edge = smoothstep(0.0, 0.22, vUv.x) * smoothstep(1.0, 0.78, vUv.x);",
      "  float fade = smoothstep(0.0, 0.35, vUv.y); vec3 c = mix(vec3(0.45, 0.62, 0.95), vec3(1.0, 0.97, 0.95), streak);",
      "  gl_FragColor = vec4(c * (0.5 + streak * 0.8), (0.18 + 0.55 * streak) * edge * fade);",
      "  #include <tonemapping_fragment>", "  #include <colorspace_fragment>", "}"].join("\n"),
  });
  (function () {
    const strips = [];
    [[0, 8.55, 0, 1.5], [-17.9, -2.4, -Math.PI / 2, 1.8], [-13.2, 13.2, -Math.PI / 4, 1.4], [12.0, -9.0 + 0.0, Math.PI * 0.85, 1.2]].forEach(function (f) {
      const g = new THREE.PlaneGeometry(f[3], 26, 1, 24); g.translate(0, -13, 0);
      const p = g.attributes.position; for (let i = 0; i < p.count; i++) { const y = -p.getY(i); p.setZ(i, Math.pow(y, 1.25) * 0.06 + 0.05); }
      g.rotateY(f[2]); g.translate(f[0], -0.05, f[1]); strips.push(g);
      WF.add("brass", G.box(f[3] * 0.8, 0.12, 0.5), [f[0], -0.02, f[1]], [0, f[2], 0], null, BRASS_DARK);
    });
    const m = new THREE.Mesh(mergeGeometries(strips.map(prep), false), fallMat); m.renderOrder = 3; scene.add(m);
  })();

  // ------------------------------------------------------------- walls with carved arches
  // a wall (its own x along, y up, z through) with arched windows (y0 > 0), round windows and arched doorways (y0 = 0)
  function archWall(F, w, h, t, ops, p, ry, tint, solidBlock) {
    const s = new THREE.Shape(), doors = ops.filter(function (o) { return !o.y0; }).sort(function (a, b) { return a.x - b.x; });
    s.moveTo(-w / 2, 0);
    doors.forEach(function (o) { const hw = o.w / 2; s.lineTo(o.x - hw, 0); s.lineTo(o.x - hw, o.sp); s.absarc(o.x, o.sp, hw, Math.PI, 0, true); s.lineTo(o.x + hw, 0); });
    s.lineTo(w / 2, 0); s.lineTo(w / 2, h); s.lineTo(-w / 2, h); s.lineTo(-w / 2, 0);
    ops.filter(function (o) { return o.y0; }).forEach(function (o) {
      const hole = new THREE.Path(), hw = o.w / 2;
      if (o.round) hole.absarc(o.x, o.y0, hw, 0, TAU, false);
      else { hole.moveTo(o.x - hw, o.y0); hole.lineTo(o.x + hw, o.y0); hole.lineTo(o.x + hw, o.sp); hole.absarc(o.x, o.sp, hw, 0, Math.PI, false); hole.lineTo(o.x - hw, o.y0); }
      s.holes.push(hole);
    });
    const g = new THREE.ExtrudeGeometry(s, { depth: t, bevelEnabled: false, curveSegments: 18 }); g.translate(0, 0, -t / 2);
    F.add("stone", g, p, [0, ry || 0, 0], null, tint || CREAM);
    // brass trims and keystones round every arch, a sill under every window
    ops.forEach(function (o) {
      const R = o.w / 2;
      [t / 2 + 0.012, -t / 2 - 0.012].forEach(function (z) {
        if (o.round) { const tr = G.tor(R + 0.02, 0.04, 6, 40); tr.translate(o.x, o.y0, z); F.add("brass", tr, p, [0, ry || 0, 0], null, BRASS); return; }
        const tr = G.tor(R + 0.03, 0.035, 6, 30, Math.PI); tr.translate(o.x, o.sp, z); F.add("brass", tr, p, [0, ry || 0, 0], null, BRASS);
        const ks = G.box(0.22, 0.3, 0.08); ks.translate(o.x, o.sp + R + 0.08, z); F.add("stone", ks, p, [0, ry || 0, 0], null, CREAM2);
      });
      if (o.y0 && !o.round) { const sill = G.box(o.w + 0.3, 0.09, t + 0.16); sill.translate(o.x, o.y0 - 0.045, 0); F.add("stone", sill, p, [0, ry || 0, 0], null, CREAM2); }
    });
    // what the camera may not cross: the solid parts beside the doorways
    const cuts = [-w / 2].concat(doors.reduce(function (a, o) { return a.concat([o.x - o.w / 2, o.x + o.w / 2]); }, [])).concat([w / 2]);
    for (let i = 0; i < cuts.length; i += 2) {
      const x0 = cuts[i], x1 = cuts[i + 1]; if (x1 - x0 < 0.2) continue;
      const c = V3((x0 + x1) / 2, h / 2, 0).applyAxisAngle(V3(0, 1, 0), ry || 0).add(V3(p[0], p[1], p[2]));
      blocker(F, c.x, c.y, c.z, ry || 0, (x1 - x0) / 2, h / 2, t / 2 + 0.05);
    }
  }
  function column(F, x, z, h, r, y0) {
    const b = y0 || 0;
    F.add("stone", G.cyl(r, r * 1.08, h - 0.5, 18), [x, b + 0.25 + (h - 0.5) / 2, z], null, null, CREAM);
    F.add("stone", G.rbox(r * 2.6, 0.26, r * 2.6, 0.3, 14), [x, b + 0.13, z], null, null, CREAM2);
    F.add("stone", G.rbox(r * 2.7, 0.26, r * 2.7, 0.3, 14), [x, b + h - 0.13, z], null, null, CREAM2);
    F.add("brass", G.tor(r + 0.02, 0.03, 6, 20), [x, b + 0.3, z], [Math.PI / 2, 0, 0], null, BRASS);
    F.add("brass", G.tor(r * 1.05, 0.03, 6, 20), [x, b + h - 0.3, z], [Math.PI / 2, 0, 0], null, BRASS);
  }
  // a hanging strand of vine with purple wisteria (instanced leaves)
  function vine(x, y, z, len, seed) {
    const r = rng(seed);
    for (let k = 0; k * 0.12 < len; k++) {
      const yy = y - k * 0.12, j = 0.06 * (1 - k * 0.12 / len);
      leaves.push({ p: [x + (r() - 0.5) * 0.14, yy, z + (r() - 0.5) * 0.14], r: [r() * 3, r() * 3, r() * 3], s: 0.09 + r() * 0.08 + j });
      if (r() < 0.32) racemes.push({ p: [x + (r() - 0.5) * 0.2, yy - 0.05, z + (r() - 0.5) * 0.2], r: [0, r() * 3, (r() - 0.5) * 0.3], s: 0.22 + r() * 0.2,
                                     c: [0x9a5fe0, 0xb88cf2, 0x7d47c9, 0xd2b8ff][Math.floor(r() * 4)] });
    }
  }
  function vinesAlong(F, x0, x1, y, z, step, maxLen, seed) {
    const r = rng(seed);
    for (let x = x0; x <= x1; x += step * (0.6 + r() * 0.8)) { const p = F.at(x, y, z); vine(p.x, p.y, p.z, 0.4 + r() * maxLen, Math.floor(r() * 1e6)); }
  }
  function bush(x, y, z, s, flowers, seed) {
    const r = rng(seed || Math.floor(x * 131 + z * 71 + 9999));
    bushes.push({ p: [x, y + 0.2 * s, z], r: [0, r() * TAU, 0], s: [s * (0.9 + r() * 0.3), s * (0.75 + r() * 0.3), s * (0.9 + r() * 0.3)],
                  c: [0x4e8a3e, 0x3d7537, 0x5d9845, 0x447f45, 0x6aa04a][Math.floor(r() * 5)] });
    for (let i = 0; i < flowers; i++) {
      const a = r() * TAU, rr = s * (0.25 + r() * 0.3);
      blooms.push({ p: [x + Math.cos(a) * rr, y + s * (0.35 + r() * 0.35), z + Math.sin(a) * rr], r: [r(), r() * 3, r()], s: 0.1 + r() * 0.08 * s,
                    c: [0xa86ae8, 0xc79cf5, 0x8b4fd8, 0xf2e6ff, 0xe8a0d8][Math.floor(r() * 5)] });
    }
  }
  function pot(F, x, z, s, y0) {
    const y = y0 || 0;
    F.add("plain", G.cyl(0.2 * s, 0.15 * s, 0.34 * s, 16), [x, y + 0.17 * s, z], null, null, TERRA);
    F.add("plain", G.tor(0.2 * s, 0.03 * s, 6, 16), [x, y + 0.34 * s, z], [Math.PI / 2, 0, 0], null, 0xb05a36);
    const p = F.at(x, y + 0.34 * s, z); bush(p.x, p.y, p.z, 0.42 * s, 3);
  }
  function lantern(x, y, z, h) { lanterns.push({ p: [x, y, z], h: h || 1.0 }); }
  function hangingLamp(F, x, y, z, drop) {
    F.add("iron", G.cyl(0.008, 0.008, drop, 4), [x, y - drop / 2, z], null, null, IRON);
    F.add("brass", G.cone(0.2, 0.18, 18), [x, y - drop - 0.05, z], null, null, BRASS);
    F.add("glow", G.sph(0.075, 12, 8), [x, y - drop - 0.14, z], null, null, hdr(0xffc27a, 5.5));
  }
  function railing(pts, opts) {
    const o = opts || {};
    for (let i = 0; i < pts.length - 1; i++) {
      const a = pts[i], b = pts[i + 1], n = Math.max(1, Math.round(a.distanceTo(b) / 1.1));
      for (let k = 0; k <= n; k++) { if (k === n && i < pts.length - 2) continue; const q = a.clone().lerp(b, k / n); railPosts.push({ p: [q.x, q.y, q.z] }); }
      bar("brass", a.clone().setY(a.y + 1.0), b.clone().setY(b.y + 1.0), 0.042, BRASS);
      bar("brass", a.clone().setY(a.y + 0.52), b.clone().setY(b.y + 0.52), 0.02, BRASS_DARK);
      if (o.lamps) for (let k = 1; k < n; k += o.lamps) { const q = a.clone().lerp(b, k / n); lantern(q.x, q.y, q.z, 1.0); }
    }
  }

  // ------------------------------------------------------------- the mission courtyard (the hub) and its table
  WF.add("pavers", new THREE.CircleGeometry(COURT_R + 0.35, 80).rotateX(-Math.PI / 2), [0, 0.003, 0], null, null, 0xf2e5cc);
  WF.add("pavers", new THREE.RingGeometry(1.9, 2.5, 64).rotateX(-Math.PI / 2), [0, 0.005, 0], null, null, 0xd9c6a4);
  [2.5, 4.3, COURT_R - 0.15].forEach(function (r) { WF.add("brass", new THREE.RingGeometry(r - 0.035, r + 0.035, 120).rotateX(-Math.PI / 2), [0, 0.007, 0], null, null, BRASS); });
  for (let i = 0; i < 16; i++) { const a = i / 16 * TAU + TAU / 32; const g = G.box(0.05, 0.004, 1.75); g.translate(0, 0, 3.4);
    WF.add("brass", g, [0, 0.007, 0], [0, -a + Math.PI / 2, 0], null, i % 2 ? BRASS_DARK : BRASS); }
  // the parapet: low carved walls between the exits, a brass rail, planters on top
  const EXITS = [45, 90, 135, 200, 270, 340];
  [[58, 76], [104, 122], [148, 187], [213, 256], [284, 326], [354, 392]].forEach(function (seg, si) {
    const a0 = seg[0] * Math.PI / 180, a1 = seg[1] * Math.PI / 180, R = COURT_R + 0.2, n = Math.max(2, Math.round((a1 - a0) * R / 0.55));
    for (let k = 0; k < n; k++) {
      const a = a0 + (k + 0.5) / n * (a1 - a0), len = (a1 - a0) * R / n + 0.04;
      WF.add("stone", G.box(len, 0.56, 0.34), [Math.cos(a) * R, 0.28, Math.sin(a) * R], [0, Math.PI / 2 - a, 0], null, CREAM);
      WF.add("stone", G.rbox(len + 0.02, 0.1, 0.46, 0.35, 10), [Math.cos(a) * R, 0.6, Math.sin(a) * R], [0, Math.PI / 2 - a, 0], null, CREAM2);
      if (k % 2 === 0 && n > 2) bush(Math.cos(a) * (R + 0.45), -0.05, Math.sin(a) * (R + 0.45), 0.55, 3);
    }
    WF.add("brass", G.arc(R, 0.035, a0, a1), [0, 0.98, 0], null, null, BRASS);
    for (let k = 0; k <= Math.max(1, Math.round((a1 - a0) * R / 1.2)); k++) { const a = a0 + k / Math.max(1, Math.round((a1 - a0) * R / 1.2)) * (a1 - a0);
      railPosts.push({ p: [Math.cos(a) * R, 0.62, Math.sin(a) * R], s: [1, 0.36, 1] }); }
    [a0, a1].forEach(function (a) { lantern(Math.cos(a) * (R + 0.05), 0.65, Math.sin(a) * (R + 0.05), 0.75); });
    blocker(WF, Math.cos((a0 + a1) / 2) * R, 0.4, Math.sin((a0 + a1) / 2) * R, Math.PI / 2 - (a0 + a1) / 2, (a1 - a0) * R / 2, 0.4, 0.2);
  });
  // benches and armillary spheres
  [168, 12].forEach(function (deg) {
    const a = deg * Math.PI / 180, x = Math.cos(a) * 5.35, z = Math.sin(a) * 5.35, ry = Math.PI / 2 - a;
    WF.add("wood", G.rbox(1.5, 0.1, 0.45, 0.25, 14), [x, 0.46, z], [0, ry, 0], null, WALNUT);
    WF.add("wood", G.rbox(1.5, 0.42, 0.08, 0.25, 14), [x + Math.cos(a) * 0.22, 0.72, z + Math.sin(a) * 0.22], [0, ry, 0], null, WALNUT);
    [-0.6, 0.6].forEach(function (o) { WF.add("brass", G.box(0.06, 0.44, 0.4), [x - Math.sin(a) * o, 0.22, z + Math.cos(a) * o], [0, ry, 0], null, BRASS_DARK); });
  });
  function armillary(F, x, y, z, s) {
    F.add("stone", G.cyl(0.16 * s, 0.22 * s, 0.9 * s, 16), [x, y + 0.45 * s, z], null, null, CREAM2);
    F.add("brass", G.cyl(0.04 * s, 0.06 * s, 0.25 * s, 10), [x, y + 1.0 * s, z], null, null, BRASS);
    [[0, 0, 0], [Math.PI / 2, 0, 0], [0.4, 0, Math.PI / 2], [Math.PI / 2, 0, 0.42]].forEach(function (r, i) {
      F.add("brass", G.tor((0.32 - i * 0.02) * s, 0.016 * s, 6, 40), [x, y + 1.38 * s, z], r, null, i === 3 ? COPPER : BRASS); });
    F.add("brass", G.sph(0.07 * s, 14, 10), [x, y + 1.38 * s, z], null, null, BRASS);
  }
  armillary(WF, -2.65, 0, 7.05, 0.8); armillary(WF, 2.65, 0, 7.05, 0.8);
  // the table: a stone drum, brass bands, a walnut rim and dark glass under the hologram (until the hero prop, a
  // round brass holo table, stands on a smaller dais in its place)
  const DAIS_Y = HAS("missiontable") ? 0.12 : 0;
  WF.add("stone", HAS("missiontable") ? G.cyl(1.2, 1.3, 0.12, 56) : G.rbox(3.7, 0.12, 3.7, 0.2, 40), [0, 0.06, 0], null, null, STONE_DARK);
  if (HAS("missiontable")) WF.add("brass", G.tor(1.21, 0.025, 6, 64), [0, 0.12, 0], [Math.PI / 2, 0, 0], null, BRASS);
  standin("missiontable", function () {
    WF.add("stone", G.cyl(1.58, 1.72, 0.66, 56), [0, 0.33, 0], null, null, CREAM2);
    [0.16, 0.52].forEach(function (y) { WF.add("brass", G.tor(1.66, 0.035, 8, 80), [0, y, 0], [Math.PI / 2, 0, 0], null, BRASS); });
    WF.add("wood", G.tor(1.6, 0.13, 14, 96), [0, 0.74, 0], [Math.PI / 2, 0, 0], [1, 1, 0.72], WALNUT);
    WF.add("brass", G.tor(1.46, 0.03, 8, 80), [0, 0.8, 0], [Math.PI / 2, 0, 0], null, BRASS);
    WF.add("iron", G.cyl(1.47, 1.47, 0.08, 64), [0, 0.74, 0], null, null, 0x10272a);
    for (let i = 0; i < 18; i++) {
      const a = i / 18 * TAU + 0.1; if (i % 6 === 0) continue;
      const x = Math.cos(a) * 1.62, z = Math.sin(a) * 1.62;
      if (i % 3 === 1) { WF.add("brass", G.cyl(0.045, 0.055, 0.06, 12), [x, 0.86, z], null, null, BRASS); WF.add("brass", G.sph(0.03, 10, 8), [x, 0.91, z], null, null, COPPER); }
      else { WF.add("brass", G.cyl(0.075, 0.075, 0.03, 18), [x, 0.85, z], null, null, BRASS_DARK); WF.add("glow", G.cyl(0.058, 0.058, 0.032, 18), [x, 0.852, z], null, null, hdr(0x6dffd2, 1.8)); }
    }
    [[0.7, 1.45], [2.3, 1.5], [3.9, 1.46], [5.5, 1.5]].forEach(function (q) {
      const x = Math.cos(q[0]) * q[1], z = Math.sin(q[0]) * q[1];
      WF.add("brass", G.cyl(0.05, 0.07, 0.05, 12), [x, 0.85, z], null, null, BRASS);
      WF.add("glass", G.cyl(0.055, 0.055, 0.14, 12), [x, 0.95, z]); WF.add("glow", G.sph(0.03, 8, 6), [x, 0.95, z], null, null, hdr(0xffc27a, 6));
    });
  });
  // chairs suited to the visitors' shapes (a stool, a low perch)
  [[-2.3, -0.95], [2.3, -0.95]].forEach(function (c, i) {
    WF.add("wood", G.cyl(0.26, 0.24, 0.07, 22), [c[0], 0.5, c[1]], null, null, WALNUT);
    WF.add("cloth", G.cyl(0.22, 0.22, 0.05, 22), [c[0], 0.555, c[1]], null, null, i ? 0x6b3d8f : 0x2f6d6a);
    WF.add("brass", G.cyl(0.035, 0.05, 0.5, 10), [c[0], 0.25, c[1]], null, null, BRASS);
    WF.add("brass", G.tor(0.18, 0.018, 6, 22), [c[0], 0.18, c[1]], [Math.PI / 2, 0, 0], null, BRASS_DARK);
  });
  practical("table", 0x62ffd0, 0, 2.1, 0, 16, 9);

  // ------------------------------------------------------------- the main pedestrian bridge (the arrival), the promenade, the pad
  WF.add("pavers", G.box(3.0, 0.03, 9.2), [0, -0.015, 10.6], null, null, 0xeadcc2);
  WF.add("stone", G.box(3.3, 0.5, 9.2), [0, -0.28, 10.6], null, null, CREAM2);
  [-1.05, 1.05].forEach(function (x) { WF.add("stone", G.tor(3.1, 0.34, 10, 28, Math.PI), [x, -2.55, 11.9], [0, Math.PI / 2, 0], [1, 0.62, 1.6], CREAM); });
  [9.0, 14.6].forEach(function (z) { WF.add("stone", G.cyl(0.55, 0.28, 9, 10), [0, -5.0, z], null, null, STONE_DARK); });
  railing([V3(-1.45, 0, 6.2), V3(-1.45, 0, 15.15)], { lamps: 3 }); railing([V3(1.45, 0, 6.2), V3(1.45, 0, 15.15)], { lamps: 3 });
  // the brass arch over the bridge
  [-1.8, 1.8].forEach(function (x) {
    WF.add("stone", G.rbox(0.62, 3.3, 0.62, 0.22, 16), [x, 1.65, 11.5], null, null, CREAM);
    WF.add("stone", G.rbox(0.8, 0.22, 0.8, 0.3, 14), [x, 0.11, 11.5], null, null, CREAM2);
    WF.add("brass", G.sph(0.16, 16, 12), [x, 3.42, 11.5], null, null, BRASS);
    vine(x * 1.02, 3.2, 11.5 + 0.33, 1.6, Math.round(x * 10 + 50)); vine(x * 1.02, 3.1, 11.5 - 0.33, 1.2, Math.round(x * 10 + 60));
  });
  WF.add("stone", G.tor(1.8, 0.26, 12, 40, Math.PI), [0, 3.3, 11.5], null, [1, 1, 1.5], CREAM);
  WF.add("brass", G.tor(1.53, 0.055, 8, 40, Math.PI), [0, 3.3, 11.75], null, null, BRASS);
  WF.add("brass", G.tor(1.53, 0.055, 8, 40, Math.PI), [0, 3.3, 11.25], null, null, BRASS);
  WF.add("stone", G.rbox(0.34, 0.44, 0.5, 0.3, 12), [0, 5.16, 11.5], null, null, CREAM2);
  hangingLamp(WF, -0.8, 4.75, 11.5, 0.5); hangingLamp(WF, 0.8, 4.75, 11.5, 0.5);
  for (let i = 0; i < 9; i++) { const a = Math.PI * (0.12 + i * 0.095); vine(Math.cos(a) * 1.8, 3.3 + Math.sin(a) * 1.8, 11.5 + (i % 2 ? 0.3 : -0.3), 0.4 + (i % 3) * 0.35, 300 + i); }
  // flower boxes along the bridge rails
  [7.8, 13.2].forEach(function (z) { [-1.62, 1.62].forEach(function (x) {
    WF.add("wood", G.box(0.32, 0.26, 1.1), [x + Math.sign(x) * 0.15, 0.9, z], null, null, WALNUT_DARK);
    for (let k = 0; k < 3; k++) bush(x + Math.sign(x) * 0.15, 0.95, z - 0.35 + k * 0.35, 0.32, 3); }); });
  // the promenade along the front edge, to the arrival pad and the outer walkway
  WF.add("pavers", G.box(33.3, 0.03, 2.0), [4.15, -0.015, 16.2], null, null, 0xe6d6bb);
  WF.add("stone", G.box(33.5, 0.45, 2.3), [4.15, -0.26, 16.2], null, null, CREAM2);
  for (let x = -12; x <= 20; x += 4) WF.add("stone", G.box(0.5, 1.6, 1.4), [x, -1.2, 16.0], [0.25, 0, 0], null, STONE_DARK);
  railing([V3(-12.4, 0, 17.15), V3(-3.2, 0, 17.15)], { lamps: 4 }); railing([V3(3.2, 0, 17.15), V3(20.75, 0, 17.15)], { lamps: 4 });
  railing([V3(-12.4, 0, 15.25), V3(-12.4, 0, 17.15)]);
  railing([V3(-12.4, 0, 15.25), V3(-1.55, 0, 15.25)]); railing([V3(1.55, 0, 15.25), V3(18.15, 0, 15.25)]);
  WF.add("pavers", G.cyl(3.2, 3.2, 0.03, 56), [0, -0.015, 20.4], null, null, 0xe9dcc3);
  WF.add("stone", G.cyl(3.3, 2.6, 0.7, 56), [0, -0.37, 20.4], null, null, CREAM2);
  WF.add("brass", new THREE.RingGeometry(1.6, 1.68, 64).rotateX(-Math.PI / 2), [0, 0.006, 20.4], null, null, BRASS);
  WF.add("brass", new THREE.RingGeometry(2.9, 2.96, 64).rotateX(-Math.PI / 2), [0, 0.006, 20.4], null, null, BRASS);
  (function () { const pts = []; for (let a = -0.15; a <= Math.PI + 0.151; a += Math.PI / 12) pts.push(V3(Math.cos(a) * 3.12, 0, 20.4 + Math.sin(a) * 3.12)); railing(pts, { lamps: 4 }); })();

  // ------------------------------------------------------------- the outer right walkway, the courier dock, the espresso kiosk
  WF.add("wood", G.box(2.6, 0.08, 25.4), [19.5, -0.04, 4.5], null, null, WALNUT);
  for (let z = -8; z <= 17; z += 1.5) WF.add("wood", G.box(2.9, 0.16, 0.18), [19.5, -0.16, z], null, null, WALNUT_DARK);
  for (let z = -6; z <= 16; z += 5.5) { WF.add("stone", G.cyl(0.26, 0.2, 12, 10), [19.5, -6.2, z], null, null, STONE_DARK);
    WF.add("brass", G.tor(0.27, 0.04, 6, 14), [19.5, -0.4, z], [Math.PI / 2, 0, 0], null, BRASS); }
  railing([V3(20.75, 0, 17.15), V3(20.75, 0, 8.45)], { lamps: 3 }); railing([V3(20.75, 0, 2.55), V3(20.75, 0, -0.35)]);
  railing([V3(20.75, 0, -2.65), V3(20.75, 0, -8.15), V3(18.25, 0, -8.15), V3(18.25, 0, 5.5)], { lamps: 3 });
  railing([V3(18.25, 0, 7.1), V3(18.25, 0, 15.25)], { lamps: 4 });
  // the hatch path: a little bridge from the walkway to the vault's document hatch
  WF.add("wood", G.box(3.8, 0.08, 1.6), [16.3, -0.04, 6.3], null, null, WALNUT);
  railing([V3(14.4, 0, 5.5), V3(18.25, 0, 5.5)]); railing([V3(14.4, 0, 7.1), V3(18.25, 0, 7.1)]);
  (function () { const a = V3(11.3, 0, 0.6), b = V3(13.6, 0, 6.3), m = a.clone().add(b).multiplyScalar(0.5);
    WF.add("pavers", G.box(1.4, 0.02, a.distanceTo(b) + 0.4), [m.x, 0.004, m.z], [0, Math.atan2(b.x - a.x, b.z - a.z), 0], null, 0xd8c6a8); })();
  // the dock pier, its console, crates and parcels
  WF.add("wood", G.box(4.9, 0.08, 2.4), [23.2, -0.04, -1.5], null, null, WALNUT);
  railing([V3(20.8, 0, -2.65), V3(25.6, 0, -2.65)], { lamps: 2 }); railing([V3(20.8, 0, -0.35), V3(25.6, 0, -0.35)]);
  [[25.55, -2.6], [25.55, -0.4]].forEach(function (q) { WF.add("brass", G.cyl(0.11, 0.13, 0.5, 14), [q[0], 0.25, q[1]], null, null, BRASS_DARK); WF.add("brass", G.sph(0.12, 12, 8), [q[0], 0.52, q[1]], null, null, BRASS); });
  WF.add("wood", G.rbox(0.55, 1.0, 0.45, 0.25, 16), [24.5, 0.5, -2.2], null, null, WALNUT_DARK);
  WF.add("brass", G.rbox(0.62, 0.06, 0.52, 0.3, 14), [24.5, 1.02, -2.2], null, null, BRASS);
  WF.add("glow", G.box(0.42, 0.26, 0.02), [24.5, 1.2, -2.0], [-0.45, 0, 0], null, hdr(0x6dffd2, 1.6));
  [[21.5, 0.3, -2.25, 0.6], [21.5, 0.85, -2.25, 0.5], [22.15, 0.25, -2.3, 0.5], [21.55, 0.18, -0.9, 0.36]].forEach(function (b) {
    WF.add("wood", G.rbox(b[3], b[3], b[3], 0.15, 10), [b[0], b[1], b[2]], [0, b[0] * 3, 0], null, WALNUT);
    WF.add("brass", G.box(b[3] + 0.02, 0.05, b[3] + 0.02), [b[0], b[1] + b[3] * 0.32, b[2]], [0, b[0] * 3, 0], null, BRASS_DARK); });
  [[22.6, 0.14, -0.75], [22.95, 0.1, -0.65]].forEach(function (b, i) { WF.add("plain", G.rbox(0.3 - i * 0.08, 0.26 - i * 0.07, 0.24, 0.2, 10), b, [0, 0.4 * i, 0], null, 0xc8a06a); });
  // the espresso kiosk on its terrace
  WF.add("wood", G.box(3.6, 0.08, 5.8), [22.6, -0.04, 5.5], null, null, WALNUT);
  railing([V3(20.8, 0, 8.45), V3(24.45, 0, 8.45), V3(24.45, 0, 2.55), V3(20.8, 0, 2.55)]);
  standin("kiosk", function () {  // the counter, the espresso machine, the awning and stools (the hero kiosk replaces them)
    WF.add("wood", G.rbox(0.8, 0.98, 2.7, 0.18, 18), [23.25, 0.49, 5.5], null, null, WALNUT_DARK);
    WF.add("stone", G.rbox(0.92, 0.07, 2.84, 0.25, 18), [23.22, 1.0, 5.5], null, null, PAPER);
    WF.add("brass", G.box(0.03, 0.05, 2.7), [22.84, 0.88, 5.5], null, null, BRASS);
    WF.add("wood", G.box(0.12, 2.2, 3.0), [24.25, 1.1, 5.5], null, null, WALNUT_DARK);
    [1.5, 2.0].forEach(function (y) { WF.add("wood", G.box(0.32, 0.04, 2.6), [24.08, y, 5.5], null, null, WALNUT);
      for (let k = 0; k < 7; k++) { WF.add("plain", G.cyl(0.04, 0.032, 0.08, 10), [24.05, y + 0.06, 4.45 + k * 0.33], null, null, 0xfaf4ea);
        if (k % 3 === 1) WF.add("glass", G.cyl(0.06, 0.06, 0.18, 10), [24.08, y + 0.11, 4.6 + k * 0.33]); } });
    // the espresso machine
    WF.add("brass", G.rbox(0.42, 0.42, 0.62, 0.3, 18), [23.3, 1.25, 5.1], null, null, BRASS);
    WF.add("brass", G.sph(0.2, 20, 12, 0, TAU, 0, Math.PI / 2), [23.3, 1.46, 5.1], null, null, COPPER);
    WF.add("brass", G.sph(0.06, 10, 8), [23.3, 1.69, 5.1], null, null, BRASS);
    [-0.15, 0.15].forEach(function (o) { WF.add("iron", G.cyl(0.05, 0.05, 0.09, 12), [23.12, 1.07, 5.1 + o], null, null, IRON);
      WF.add("wood", G.cyl(0.018, 0.018, 0.2, 6), [23.0, 1.04, 5.1 + o], [0, 0, Math.PI / 2], null, WALNUT_DARK);
      WF.add("glow", G.cyl(0.045, 0.045, 0.01, 14), [23.09, 1.33, 5.1 + o], [0, 0, Math.PI / 2], null, hdr(0xfff1d0, 1.6)); });
    [4.55, 5.75, 6.3].forEach(function (z, i) { WF.add("plain", G.cyl(0.04, 0.03, 0.06, 10), [22.95, 1.07, z], null, null, 0xfbf6ee);
      WF.add("plain", G.cyl(0.07, 0.07, 0.01, 12), [22.95, 1.04, z], null, null, 0xfbf6ee); if (i === 2) WF.add("glass", G.sph(0.17, 16, 10, 0, TAU, 0, Math.PI / 2), [23.25, 1.04, 6.4]); });
    [0, 1, 2, 3].forEach(function (k) { WF.add("plain", G.sph(0.045, 8, 6), [23.2 + (k % 2) * 0.07, 1.07, 6.35 + (k > 1 ? 0.07 : -0.05)], null, [1, 0.6, 1], 0xd9a066); });
    // the awning, striped, on brass poles
    for (let k = 0; k < 14; k++) WF.add("cloth", G.box(2.5, 0.025, 0.24), [23.15, 2.55, 3.93 + k * 0.24], [0, 0, 0.26], null, k % 2 ? 0xf3e7d0 : 0xd8795a);
    for (let k = 0; k < 14; k++) WF.add("cloth", G.cyl(0.12, 0.12, 0.024, 12, false), [21.98, 2.22, 3.93 + k * 0.24], [0, 0, 0.26], [1, 1, 1], k % 2 ? 0xf3e7d0 : 0xd8795a);
    [[22.0, 3.85], [22.0, 7.15]].forEach(function (q) { WF.add("brass", G.cyl(0.035, 0.035, 2.25, 10), [q[0], 1.12, q[1]], null, null, BRASS); });
    hangingLamp(WF, 22.4, 2.4, 4.6, 0.35); hangingLamp(WF, 22.4, 2.4, 6.4, 0.35);
    // stools at the counter and a cafe table
    [4.7, 5.5, 6.3].forEach(function (z) {
      WF.add("brass", G.cyl(0.03, 0.06, 0.66, 10), [22.45, 0.33, z], null, null, BRASS);
      WF.add("cloth", G.rbox(0.36, 0.09, 0.36, 0.3, 14), [22.45, 0.7, z], null, null, LEATHER);
      WF.add("brass", G.tor(0.15, 0.014, 6, 16), [22.45, 0.25, z], [Math.PI / 2, 0, 0], null, BRASS_DARK); });
  });
  if (!HAS("kiosk")) { vinesAlong(WF, 22.0, 24.2, 2.62, 3.85, 0.35, 0.9, 77); vinesAlong(WF, 22.0, 24.2, 2.62, 7.15, 0.35, 0.9, 78); }
  WF.add("brass", G.cyl(0.04, 0.2, 0.72, 12), [21.6, 0.36, 3.35], null, null, BRASS);
  WF.add("stone", G.cyl(0.38, 0.38, 0.05, 24), [21.6, 0.74, 3.35], null, null, PAPER);
  WF.add("plain", G.cyl(0.045, 0.035, 0.07, 10), [21.5, 0.8, 3.3], null, null, 0xfbf6ee);
  pot(WF, 24.1, 8.05, 1.1); pot(WF, 24.1, 2.95, 1.0); pot(WF, 21.1, 8.05, 0.9);
  practical("kiosk", 0xffbd74, 22.6, 2.2, 5.5, 18, 8);

  // ------------------------------------------------------------- the departments
  function roomShell(F, o) {
    const w = o.w, d = o.d, h = o.h, t = 0.42;
    F.add(o.floorKey || "pavers", G.box(w, 0.04, d), [0, -0.019, 0], null, null, o.floor || 0xeadcc4);
    F.add("stone", G.box(w + 0.8, 0.6, d + 0.8), [0, -0.33, 0], null, null, STONE_DARK);
    archWall(F, w + t, h, t, o.back || [], [0, 0, -d / 2], 0, o.tint);
    archWall(F, d, h, t, o.left || [], [-w / 2, 0, 0], Math.PI / 2, o.tint);
    archWall(F, d, h, t, o.right || [], [w / 2, 0, 0], -Math.PI / 2, o.tint);
    archWall(F, w + t, h, t, o.front || [], [0, 0, d / 2], 0, o.tint);
    // cornice, a brass band, the corner columns, pergola beams under an open sky
    F.add("stone", G.box(w + t + 0.36, 0.24, d + t + 0.36), [0, h + 0.12, 0], null, null, CREAM2);
    F.add("stone", G.box(w + t - 1.2, 0.3, d + t - 1.2), [0, h + 0.12, 0], null, null, CREAM2);
    F.add("brass", G.box(w + t + 0.38, 0.05, d + t + 0.38), [0, h - 0.02, 0], null, null, BRASS);
    [[-1, 1], [1, 1], [-1, -1], [1, -1]].forEach(function (c) { column(F, c[0] * (w / 2 + 0.12), c[1] * (d / 2 + 0.12), h, 0.27); });
    for (let z = -d / 2 + 0.7; z < d / 2 - 0.4; z += 1.05) F.add("wood", G.box(w + 0.1, 0.2, 0.15), [0, h + 0.36, z], null, null, WALNUT_DARK);
    F.add("wood", G.box(0.15, 0.2, d + 0.1), [-w / 4, h + 0.56, 0], null, null, WALNUT_DARK); F.add("wood", G.box(0.15, 0.2, d + 0.1), [w / 4, h + 0.56, 0], null, null, WALNUT_DARK);
    // flower-heavy vines over the front and the sides
    vinesAlong(F, -w / 2 - 0.1, w / 2 + 0.1, h + 0.05, d / 2 + 0.28, 0.32, 1.5, o.seed || 1);
    vinesAlong(F, -w / 2 + 0.3, w / 2 - 0.3, h + 0.3, 0.6, 0.6, 0.8, (o.seed || 1) + 5);
    [-1, 1].forEach(function (s) { for (let z = -d / 2; z < d / 2; z += 0.9) { const p = F.at(s * (w / 2 + 0.28), h + 0.05, z); vine(p.x, p.y, p.z, 0.3 + ((z * 7 + s * 3) % 1 + 1) % 1 * 1.2, Math.round(z * 100 + s * 7 + (o.seed || 1) * 1000)); } });
    // bushes round the outside
    for (let x = -w / 2 + 0.4; x < w / 2; x += 1.1) { const p = F.at(x, 0, -d / 2 - 0.55); if (onIsland(p.x, p.z, 0.4)) bush(p.x, 0, p.z, 0.65, 4); }
    [-1, 1].forEach(function (s) { for (let z = -d / 2 + 0.4; z < d / 2 - 0.4; z += 1.2) { const p = F.at(s * (w / 2 + 0.6), 0, z); if (onIsland(p.x, p.z, 0.4)) bush(p.x, 0, p.z, 0.6, 3); } });
  }
  const shelf = function (F, x, z, ry, w, h, rows, seed) {
    const r = rng(seed);
    F.add("wood", G.box(w, h, 0.36), [x, h / 2, z], [0, ry, 0], null, WALNUT_DARK);
    for (let k = 0; k < rows; k++) {
      const y = 0.35 + k * (h - 0.5) / rows;
      F.add("wood", G.box(w - 0.06, 0.04, 0.4), [x, y, z], [0, ry, 0], null, WALNUT);
      let u = -w / 2 + 0.08;
      while (u < w / 2 - 0.12) { const bw = 0.04 + r() * 0.05, bh = 0.18 + r() * 0.12, q = V3(u + bw / 2, 0, 0.06).applyAxisAngle(V3(0, 1, 0), ry);
        const p = F.at(x + q.x, y + 0.02 + bh / 2, z + q.z);
        (standinBooks || books).push({ p: [p.x, p.y, p.z], r: [0, F.yaw + ry + (r() < 0.1 ? 0.25 : 0), 0], s: [bw, bh, 0.24], c: [0x7b2f2a, 0x2f4d6e, 0x3f5e3a, 0x7a5a2c, 0x5a2f5e, 0x8c6b3e, 0x2e3a4f][Math.floor(r() * 7)] });
        u += bw + 0.005; if (r() < 0.06) u += 0.12; }
    }
  };
  function chair(F, x, z, ry, s, seat, back) {
    F.add("wood", G.rbox(0.5 * s, 0.09 * s, 0.5 * s, 0.25, 14), [x, 0.45 * s, z], [0, ry, 0], null, WALNUT);
    F.add("cloth", G.rbox(0.44 * s, 0.07 * s, 0.44 * s, 0.25, 14), [x, 0.51 * s, z], [0, ry, 0], null, seat);
    const bk = V3(0, 0, -0.23 * s).applyAxisAngle(V3(0, 1, 0), ry);
    F.add("cloth", G.rbox(0.48 * s, (back || 0.6) * s, 0.08 * s, 0.25, 14), [x + bk.x, (0.5 + (back || 0.6) / 2) * s, z + bk.z], [0, ry, 0], null, seat);
    F.add("brass", G.cyl(0.03 * s, 0.05 * s, 0.42 * s, 10), [x, 0.21 * s, z], null, null, BRASS);
    F.add("brass", G.cyl(0.25 * s, 0.27 * s, 0.04 * s, 18), [x, 0.03 * s, z], null, null, BRASS_DARK);
  }
  function screenTex(kind, hue) {
    return canvasTex(512, 320, function (ctx, w, h) {
      const r = rng(kind.length * 97 + hue.length);
      const g = ctx.createLinearGradient(0, 0, 0, h); g.addColorStop(0, "#151a3c"); g.addColorStop(1, "#0b0f26"); ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
      ctx.strokeStyle = "rgba(140,170,255,.12)"; ctx.lineWidth = 1; for (let x = 0; x < w; x += 32) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
      for (let y = 0; y < h; y += 32) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
      ctx.strokeStyle = hue; ctx.fillStyle = hue; ctx.lineWidth = 3; ctx.shadowColor = hue; ctx.shadowBlur = 12;
      if (kind === "nodes") { const pts = []; for (let i = 0; i < 9; i++) pts.push([60 + r() * (w - 120), 50 + r() * (h - 100)]);
        pts.forEach(function (p, i) { if (i) { ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]); ctx.lineTo(p[0], p[1]); ctx.stroke(); } });
        pts.forEach(function (p, i) { ctx.beginPath(); ctx.arc(p[0], p[1], i ? 9 : 22, 0, TAU); i ? ctx.fill() : ctx.stroke(); }); }
      else if (kind === "wave") { for (let k = 0; k < 3; k++) { ctx.globalAlpha = 1 - k * 0.3; ctx.beginPath();
        for (let x = 0; x <= w; x += 6) ctx.lineTo(x, h / 2 + Math.sin(x * (0.02 + k * 0.013) + k) * (40 + k * 18) * Math.sin(x * 0.004 + k)); ctx.stroke(); } ctx.globalAlpha = 1; }
      else if (kind === "rings") { for (let k = 1; k < 5; k++) { ctx.beginPath(); ctx.arc(w / 2, h / 2, k * 34, 0, TAU); ctx.stroke(); }
        ctx.beginPath(); ctx.moveTo(w / 2, h / 2); ctx.lineTo(w / 2 + 130, h / 2 - 60); ctx.stroke(); for (let i = 0; i < 6; i++) { ctx.beginPath(); ctx.arc(w / 2 + (r() - 0.5) * 260, h / 2 + (r() - 0.5) * 200, 6, 0, TAU); ctx.fill(); } }
      else if (kind === "stars") { for (let i = 0; i < 60; i++) { ctx.globalAlpha = 0.3 + r() * 0.7; ctx.beginPath(); ctx.arc(r() * w, r() * h, 1 + r() * 2.5, 0, TAU); ctx.fill(); }
        ctx.globalAlpha = 1; const s = []; for (let i = 0; i < 7; i++) s.push([80 + r() * (w - 160), 60 + r() * (h - 120)]); ctx.beginPath(); s.forEach(function (p) { ctx.lineTo(p[0], p[1]); }); ctx.stroke();
        s.forEach(function (p) { ctx.beginPath(); ctx.arc(p[0], p[1], 6, 0, TAU); ctx.fill(); }); }
      else if (kind === "gem") { ctx.beginPath(); ctx.moveTo(w / 2, 40); ctx.lineTo(w / 2 + 90, h / 2 - 20); ctx.lineTo(w / 2, h - 40); ctx.lineTo(w / 2 - 90, h / 2 - 20); ctx.closePath(); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(w / 2 - 90, h / 2 - 20); ctx.lineTo(w / 2 + 90, h / 2 - 20); ctx.moveTo(w / 2, 40); ctx.lineTo(w / 2, h - 40); ctx.stroke();
        for (let i = 0; i < 4; i++) { const a = i / 4 * TAU + 0.6; ctx.beginPath(); ctx.arc(w / 2 + Math.cos(a) * 170, h / 2 + Math.sin(a) * 100, 10, 0, TAU); ctx.fill(); } }
      else if (kind === "checks") { for (let i = 0; i < 3; i++) { const y = 70 + i * 80; ctx.strokeRect(240, y - 22, 44, 44); ctx.beginPath(); ctx.moveTo(250, y); ctx.lineTo(262, y + 12); ctx.lineTo(280, y - 14); ctx.stroke();
        ctx.globalAlpha = 0.5; ctx.fillRect(300, y - 6, 150 - i * 20, 12); ctx.globalAlpha = 1; }
        ctx.beginPath(); ctx.arc(120, 170, 70, Math.PI * 0.8, Math.PI * 2.2); ctx.stroke(); ctx.beginPath(); ctx.moveTo(120, 170); ctx.lineTo(160, 120); ctx.stroke(); }
    });
  }
  const screens = [];
  function screen(F, x, y, z, ry, w, h, kind, hue, tilt, k) {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: screenTex(kind, hue), color: hdr(0xffffff, k || 1.5), toneMapped: true }));
    // the glass sits just proud of its brass frame (inside the frame it would be hidden)
    const front = V3(0, 0, 0.024).applyAxisAngle(V3(1, 0, 0), tilt || 0).applyAxisAngle(V3(0, 1, 0), ry);
    F.place(m, x + front.x, y + front.y, z + front.z, ry); m.rotation.x = tilt || 0; m.rotation.order = "YXZ";
    F.add("brass", G.rbox(w + 0.07, h + 0.07, 0.035, 0.2, 14), [x, y, z], [tilt || 0, ry, 0], null, BRASS_DARK);
    const back = V3(0, 0, -0.03).applyAxisAngle(V3(1, 0, 0), tilt || 0).applyAxisAngle(V3(0, 1, 0), ry);
    F.add("iron", G.box(w + 0.02, h + 0.02, 0.02), [x + back.x, y + back.y, z + back.z], [tilt || 0, ry, 0], null, IRON);
    screens.push({ mesh: m, base: k || 1.5, phase: screens.length * 1.7 }); return m;
  }

  // -- the workshop (left): Pip's warm bench, tools, blueprints, a brass boiler
  const WS = RF.workshop;
  roomShell(WS, { w: 7.5, d: 7.0, h: 4.4, seed: 11, floor: 0xe6cfae,
    back: [{ x: 0, w: 2.4, y0: 1.0, sp: 2.6 }], left: [{ x: 0.6, w: 1.3, y0: 1.1, sp: 2.5 }], right: [],
    front: [{ x: 0, w: 3.0, sp: 2.45 }] });
  WS.add("cloth", G.rbox(3.6, 0.02, 2.4, 0.2, 16), [0, 0.012, -0.6], null, null, 0x7a3428);
  standin("workbench", function () {  // Pip's bench and what is on it (the hero workbench replaces them)
    WS.add("wood", G.rbox(2.7, 0.1, 0.95, 0.2, 18), [0, 0.68, -0.7], null, null, WALNUT);
    WS.add("cloth", G.box(2.0, 0.012, 0.7), [0, 0.735, -0.7], null, null, 0x3f2a1e);
    WS.add("brass", G.box(2.72, 0.035, 0.03), [0, 0.68, -0.22], null, null, BRASS);
    [-1.2, 1.2].forEach(function (x) { WS.add("wood", G.box(0.1, 0.64, 0.82), [x, 0.32, -0.7], null, null, WALNUT_DARK); });
    WS.add("wood", G.box(2.3, 0.05, 0.7), [0, 0.16, -0.7], null, null, WALNUT_DARK);
    // the sensor drone being assembled, parts, tools, the blueprint roll
    WS.add("plain", G.sph(0.13, 24, 16), [0.05, 0.86, -0.55], null, null, 0xf4efe6);
    WS.add("brass", G.tor(0.135, 0.02, 8, 28), [0.05, 0.86, -0.55], [0, 0.3, 0], null, BRASS);
    WS.add("brass", G.tor(0.135, 0.014, 8, 28), [0.05, 0.86, -0.55], [Math.PI / 2, 0, 0], null, BRASS);
    WS.add("glow", G.cyl(0.055, 0.055, 0.02, 18), [0.05, 0.86, -0.42], [Math.PI / 2, 0, 0], null, hdr(0x5fffd4, 3));
    WS.add("plain", G.sph(0.11, 20, 14), [0.95, 0.84, -0.62], null, null, 0xf4efe6);
    WS.add("glow", G.cyl(0.045, 0.045, 0.02, 16), [0.95, 0.84, -0.51], [Math.PI / 2, 0, 0], null, hdr(0x5fffd4, 2.4));
    WS.add("brass", G.tor(0.115, 0.018, 8, 24), [0.95, 0.84, -0.62], [0, -0.4, 0], null, BRASS);
    [[-0.45, -0.45, 0.06], [-0.3, -0.8, 0.05], [0.5, -0.4, 0.04], [0.6, -0.9, 0.07]].forEach(function (q) {
      WS.add("brass", G.cyl(q[2], q[2], 0.03, 16), [q[0], 0.76, q[1]], null, null, BRASS); WS.add("brass", G.tor(q[2], 0.012, 6, 16), [q[0], 0.78, q[1]], [Math.PI / 2, 0, 0], null, COPPER); });
    WS.add("wood", G.cyl(0.018, 0.018, 0.14, 8), [0.35, 0.76, -0.35], [0, 0, Math.PI / 2], null, WALNUT_DARK);
    WS.add("brass", G.cyl(0.006, 0.006, 0.12, 6), [0.48, 0.76, -0.35], [0, 0, Math.PI / 2], null, 0xd8d8d8);
    WS.add("plain", G.cyl(0.07, 0.07, 0.9, 16), [-0.85, 0.8, -0.35], [0, 0.2, Math.PI / 2], null, PAPER);
    WS.add("plain", G.box(0.6, 0.006, 0.42), [-0.6, 0.746, -0.85], [0, 0.15, 0], null, 0xe8eef4);
    // the desk lamp
    WS.add("brass", G.cyl(0.09, 0.11, 0.04, 16), [-1.05, 0.76, -0.95], null, null, BRASS);
    WS.add("brass", G.cyl(0.012, 0.012, 0.5, 6), [-1.05, 1.0, -0.95], [0.3, 0, 0], null, BRASS);
    WS.add("brass", G.cyl(0.012, 0.012, 0.42, 6), [-1.05, 1.32, -0.82], [-0.9, 0, 0], null, BRASS);
    WS.add("brass", G.cone(0.13, 0.16, 18, true), [-1.05, 1.4, -0.62], [Math.PI + 0.5, 0, 0], null, BRASS);
    WS.add("glow", G.sph(0.05, 12, 8), [-1.05, 1.37, -0.6], null, null, hdr(0xffd08a, 7));
  });
  // the pegboard of hung tools, the shelves, the boiler, crates, a stool
  WS.add("wood", G.box(0.06, 1.5, 2.4), [3.48, 1.8, -1.0], null, null, WALNUT);
  for (let i = 0; i < 14; i++) { const zz = -2.0 + (i % 7) * 0.33, yy = 1.35 + Math.floor(i / 7) * 0.62;
    if (i % 3 === 0) WS.add("brass", G.tor(0.06, 0.014, 6, 14), [3.42, yy + 0.2, zz], [0, Math.PI / 2, 0], null, BRASS);
    WS.add(i % 2 ? "iron" : "brass", G.box(0.025, 0.32 - (i % 3) * 0.06, 0.045), [3.42, yy, zz], [0.1 * (i % 3 - 1), 0, 0], null, i % 2 ? IRON : BRASS); }
  shelf(WS, -2.5, -3.2, 0, 1.3, 2.2, 3, 4); shelf(WS, 2.5, -3.2, 0, 1.3, 2.2, 3, 5);
  WS.add("brass", G.sph(0.55, 28, 20), [-2.6, 1.05, 2.0], null, null, BRASS);
  WS.add("brass", G.tor(0.56, 0.04, 8, 32), [-2.6, 1.05, 2.0], [Math.PI / 2, 0, 0], null, COPPER);
  WS.add("brass", G.tor(0.56, 0.04, 8, 32), [-2.6, 1.05, 2.0], null, null, COPPER);
  [[-0.3, -0.3], [0.3, -0.3], [-0.3, 0.3], [0.3, 0.3]].forEach(function (q) { WS.add("iron", G.cyl(0.04, 0.05, 0.6, 8), [-2.6 + q[0], 0.3, 2.0 + q[1]], null, null, IRON); });
  WS.add("brass", G.cyl(0.05, 0.05, 1.2, 10), [-2.0, 1.75, 2.0], [0, 0, 0.9], null, COPPER);
  WS.add("brass", G.cyl(0.1, 0.1, 0.03, 18), [-2.6, 1.05, 2.56], [Math.PI / 2, 0, 0], null, BRASS_DARK);
  WS.add("glow", G.cyl(0.08, 0.08, 0.02, 18), [-2.6, 1.05, 2.575], [Math.PI / 2, 0, 0], null, hdr(0xfff0c8, 1.4));
  [[2.7, 0.35, 2.3, 0.7], [2.75, 1.0, 2.3, 0.55], [2.0, 0.28, 2.6, 0.56]].forEach(function (b) {
    WS.add("wood", G.rbox(b[3], b[3], b[3], 0.15, 10), [b[0], b[1], b[2]], [0, b[0], 0], null, WALNUT);
    WS.add("brass", G.box(b[3] + 0.02, 0.05, b[3] + 0.02), [b[0], b[1] + b[3] * 0.3, b[2]], [0, b[0], 0], null, BRASS_DARK); });
  WS.add("wood", G.cyl(0.2, 0.2, 0.06, 18), [1.2, 0.55, -1.75], null, null, WALNUT); WS.add("brass", G.cyl(0.03, 0.04, 0.52, 8), [1.2, 0.27, -1.75], null, null, BRASS);
  hangingLamp(WS, -1.0, 4.4, -0.7, 1.1); hangingLamp(WS, 1.2, 4.4, 0.6, 1.2);
  pot(WS, -3.2, 2.9, 1.2); pot(WS, 3.2, 2.9, 1.0);
  (function () { const p = WS.at(0, 2.7, -0.5); practical("workshop", 0xffa553, p.x, p.y, p.z, 30, 10); })();

  // -- the analysis den (right): Nyx's curved desk, four glass screens, a round window
  const DN = RF.den;
  roomShell(DN, { w: 7.5, d: 7.0, h: 4.4, seed: 23, floor: 0x7b5a46, floorKey: "wood",
    back: [{ x: 0, w: 2.3, y0: 3.0, round: true }], left: [{ x: 1.0, w: 1.3, y0: 1.1, sp: 2.5 }], right: [{ x: 0.5, w: 1.3, sp: 1.95 }],
    front: [{ x: 0, w: 3.0, sp: 2.45 }] });
  DN.add("cloth", new THREE.CircleGeometry(1.9, 48).rotateX(-Math.PI / 2), [0, 0.012, -1.2], null, null, 0x4d2c6e);
  DN.add("brass", new THREE.RingGeometry(1.86, 1.93, 64).rotateX(-Math.PI / 2), [0, 0.014, -1.2], null, null, BRASS);
  DN.add("brass", G.tor(1.12, 0.05, 8, 48), [0, 3.0, -3.27], null, null, BRASS);
  for (let k = 0; k < 4; k++) DN.add("brass", G.box(0.04, 2.2, 0.06), [0, 3.0, -3.3], [0, 0, k * Math.PI / 4], null, BRASS_DARK);
  // Nyx's curved desk, its keyboard, mug and chair (the hero desk replaces them); the four glass screens stay, over
  // the procedural desk or, once the hero desk (its own violet monitors) is coming, a tier higher on brass rods
  standin("nyxdesk", function () {
    const s = new THREE.Shape(); s.absarc(0, 0, 1.42, Math.PI * 0.2, Math.PI * 0.8, false); s.absarc(0, 0, 0.62, Math.PI * 0.8, Math.PI * 0.2, true);
    const top = new THREE.ExtrudeGeometry(s, { depth: 0.07, bevelEnabled: false, curveSegments: 40 }).rotateX(-Math.PI / 2);
    DN.add("wood", top, [0, 0.72, -0.95], null, null, WALNUT);
    const front = new THREE.CylinderGeometry(1.36, 1.36, 0.66, 40, 1, true, Math.PI * 0.7, Math.PI * 0.6);
    DN.add("wood", front, [0, 0.36, -0.95], [0, Math.PI, 0], null, WALNUT_DARK);
    DN.add("brass", G.tor(1.42, 0.02, 6, 40, Math.PI * 0.6), [0, 0.795, -0.95], [-Math.PI / 2, 0, Math.PI * 0.2], null, BRASS);
    if (!HAS("nyxdesk")) [-62, -22, 22, 62].forEach(function (deg) { const a = (90 + deg) * Math.PI / 180;
      DN.add("brass", G.cyl(0.02, 0.02, 0.38, 8), [Math.cos(a) * 1.33, 0.93, -0.95 - Math.sin(a) * 1.33], null, null, BRASS); });
    DN.add("iron", G.rbox(0.56, 0.04, 0.2, 0.3, 14), [0, 0.81, -1.72], null, null, IRON);
    DN.add("brass", G.cyl(0.08, 0.09, 0.05, 18), [0.55, 0.8, -1.65], null, null, BRASS); DN.add("glow", G.cyl(0.05, 0.05, 0.052, 16), [0.55, 0.8, -1.65], null, null, hdr(0xb47bff, 2));
    DN.add("plain", G.box(0.32, 0.03, 0.24), [-0.6, 0.78, -1.65], [0, 0.4, 0], null, PAPER);
    DN.add("brass", G.cyl(0.008, 0.008, 0.2, 6), [-0.55, 0.8, -1.62], [0, 0.4, Math.PI / 2], null, BRASS);
    DN.add("plain", G.cyl(0.05, 0.045, 0.1, 14), [-0.75, 0.84, -1.6], null, null, 0xfbf6ee);
    DN.add("plain", G.tor(0.03, 0.01, 6, 10), [-0.7, 0.84, -1.6], null, null, 0xfbf6ee);
    chair(DN, 0, -0.95, Math.PI, 1.0, 0x5e2f6e, 0.55);
  });
  [[-62, "nodes", "#9d7bff"], [-22, "wave", "#7fb2ff"], [22, "rings", "#b78cff"], [62, "gem", "#79e9ff"]].forEach(function (q) {
    const a = (90 + q[0]) * Math.PI / 180, ry = Math.atan2(-Math.cos(a), Math.sin(a));
    if (!HAS("nyxdesk")) { screen(DN, Math.cos(a) * 1.33, 1.25, -0.95 - Math.sin(a) * 1.33, ry, 0.86, 0.56, q[1], q[2], -0.08, 1.7); return; }
    const x = Math.cos(a) * 1.5, z = -1.15 - Math.sin(a) * 1.5;
    screen(DN, x, 2.08, z, ry, 0.78, 0.5, q[1], q[2], -0.1, 1.7);
    [-0.3, 0.3].forEach(function (o) { DN.add("brass", G.cyl(0.01, 0.01, 2.08, 6), [x + Math.sin(a) * o, 3.37, z + Math.cos(a) * o], null, null, BRASS_DARK); });
  });
  shelf(DN, -1.6, -3.2, 0, 1.1, 2.3, 4, 8); shelf(DN, 1.6, -3.2, 0, 1.1, 2.3, 4, 9);
  DN.add("glow", G.ico(0.09, 0), [-1.6, 2.05, -3.1], null, [1, 1.6, 1], hdr(0xc08bff, 3));
  hangingLamp(DN, 0.9, 4.4, 0.4, 1.3); hangingLamp(DN, -1.2, 4.4, 1.3, 1.0);
  pot(DN, 3.2, 2.9, 1.1); pot(DN, -3.2, 2.9, 1.2); pot(DN, -3.1, -2.8, 1.0);
  (function () { const p = DN.at(0, 2.7, -1.4); practical("den", 0xb27dff, p.x, p.y, p.z, 26, 10); })();

  // -- the archive (front-left): tall bookshelves, lavender memory crystals, a ladder, a reading desk
  const AR = RF.archive;
  roomShell(AR, { w: 7.0, d: 6.4, h: 4.8, seed: 37, floor: 0xe4dcc8,
    back: [{ x: 0, w: 1.6, y0: 1.2, sp: 3.0 }], left: [], right: [{ x: 0.3, w: 2.0, sp: 2.4 }],
    front: [{ x: 0, w: 2.6, sp: 2.4 }] });
  AR.add("cloth", G.rbox(3.4, 0.02, 2.6, 0.2, 16), [-0.2, 0.012, -0.3], null, null, 0x6d2a34);
  standin("archive", function () { shelf(AR, -2.4, -2.95, 0, 1.6, 3.6, 6, 13); shelf(AR, 2.4, -2.95, 0, 1.6, 3.6, 6, 14); });
  shelf(AR, -3.25, -1.2, Math.PI / 2, 1.6, 3.6, 6, 15); shelf(AR, -3.25, 0.7, Math.PI / 2, 1.6, 3.6, 6, 16);
  AR.add("brass", G.cyl(0.02, 0.02, 3.6, 8), [-3.0, 1.8, -1.8], [0.2, 0, 0], null, BRASS);
  AR.add("brass", G.cyl(0.02, 0.02, 3.6, 8), [-3.0, 1.8, -1.3], [0.2, 0, 0], null, BRASS);
  for (let k = 0; k < 9; k++) AR.add("brass", G.cyl(0.012, 0.012, 0.5, 6), [-3.0 + 0.0, 0.25 + k * 0.38, -1.55 - (0.25 + k * 0.38 - 1.8) * 0.2], [Math.PI / 2, 0, 0], null, BRASS_DARK);
  [[-2.1, 1.5], [2.3, 1.7], [2.2, -1.5], [-0.9, -2.3]].forEach(function (q, i) {
    AR.add("brass", G.cyl(0.18, 0.24, 0.85, 18), [q[0], 0.43, q[1]], null, null, BRASS_DARK);
    AR.add("brass", G.tor(0.2, 0.025, 6, 20), [q[0], 0.86, q[1]], [Math.PI / 2, 0, 0], null, BRASS);
    AR.add("glass", G.sph(0.26, 20, 14, 0, TAU, 0, Math.PI / 2), [q[0], 0.86, q[1]], null, [1, 1.5, 1]);
    AR.add("glow", G.ico(0.11, 0), [q[0], 1.1, q[1]], [0, i, 0], [1, 1.9, 1], hdr(i % 2 ? 0xc596ff : 0x9fd8ff, 3.2));
  });
  AR.add("wood", G.rbox(1.3, 0.08, 0.7, 0.2, 14), [1.4, 0.74, -0.9], [0, -0.4, 0], null, WALNUT);
  [[1.0, -0.75], [1.8, -1.05]].forEach(function (q) { AR.add("wood", G.box(0.08, 0.7, 0.55), [q[0], 0.35, q[1]], [0, -0.4, 0], null, WALNUT_DARK); });
  AR.add("plain", G.box(0.22, 0.02, 0.3), [1.28, 0.79, -0.85], [0, -0.25, 0.08], null, PAPER); AR.add("plain", G.box(0.22, 0.02, 0.3), [1.5, 0.79, -0.95], [0, -0.55, -0.08], null, PAPER);
  AR.add("plain", G.cyl(0.035, 0.04, 0.12, 10), [1.85, 0.84, -1.1], null, null, 0xf6eedd); AR.add("glow", G.sph(0.022, 8, 6), [1.85, 0.93, -1.1], null, [1, 1.6, 1], hdr(0xffc070, 7));
  hangingLamp(AR, -0.8, 4.8, 0.2, 1.4); hangingLamp(AR, 1.2, 4.8, -0.9, 1.3);
  railing([AR.at(3.4, 0, -0.75), AR.at(3.4, 0, 1.35)]);
  pot(AR, 3.0, 2.7, 1.0); pot(AR, -2.9, 2.6, 1.2);
  (function () { const p = AR.at(0, 2.8, -0.4); practical("archive", 0x7affd4, p.x, p.y, p.z, 20, 10); })();

  // -- the vault (front-right): the round brass door, Rook's risk desk, the document hatch
  const VT = RF.vault;
  roomShell(VT, { w: 7.0, d: 6.4, h: 4.4, seed: 51, floor: 0xd8cebe,
    back: [], left: [{ x: 0.2, w: 0.8, y0: 0.6, sp: 1.15 }], right: [{ x: -0.6, w: 1.3, y0: 1.1, sp: 2.4 }],
    front: [{ x: 0, w: 2.8, sp: 2.4 }] });
  VT.add("brass", new THREE.RingGeometry(1.2, 1.28, 64).rotateX(-Math.PI / 2), [0.9, 0.012, -2.0], null, null, BRASS);
  // the vault door: frame, door, rings, the wheel, bolts (the hero vault door replaces them)
  standin("vaultdoor", function () {
    const x = 0.9, y = 1.55, z = -2.98;
    VT.add("stone", G.tor(1.3, 0.2, 10, 48), [x, y, z], null, [1, 1, 0.6], CREAM2);
    VT.add("brass", G.tor(1.22, 0.1, 12, 56), [x, y, z + 0.05], null, null, BRASS_DARK);
    VT.add("brass", G.cyl(1.14, 1.14, 0.16, 56), [x, y, z + 0.06], [Math.PI / 2, 0, 0], null, BRASS);
    [0.95, 0.72, 0.45].forEach(function (r, i) { VT.add("brass", G.tor(r, 0.03, 8, 48), [x, y, z + 0.15], null, null, i % 2 ? BRASS_DARK : COPPER); });
    VT.add("brass", G.tor(0.36, 0.045, 10, 36), [x, y, z + 0.32], null, null, BRASS);
    for (let k = 0; k < 6; k++) VT.add("brass", G.box(0.04, 0.7, 0.04), [x, y, z + 0.3], [0, 0, k * Math.PI / 6], null, BRASS);
    VT.add("brass", G.cyl(0.1, 0.1, 0.25, 18), [x, y, z + 0.22], [Math.PI / 2, 0, 0], null, COPPER);
    for (let k = 0; k < 10; k++) { const a = k / 10 * TAU; VT.add("brass", G.cyl(0.05, 0.05, 0.1, 10), [x + Math.cos(a) * 1.02, y + Math.sin(a) * 1.02, z + 0.16], [Math.PI / 2, 0, 0], null, BRASS_DARK); }
    VT.add("brass", G.box(0.18, 0.5, 0.18), [x + 1.2, y + 0.4, z + 0.12], null, null, BRASS_DARK); VT.add("brass", G.box(0.18, 0.5, 0.18), [x + 1.2, y - 0.4, z + 0.12], null, null, BRASS_DARK);
  });
  // cubbies, no money on show
  for (let i = 0; i < 4; i++) for (let j = 0; j < 3; j++) { VT.add("wood", G.box(0.42, 0.36, 0.1), [-2.6 + i * 0.46, 1.3 + j * 0.42, -3.0], null, null, WALNUT_DARK);
    VT.add("plain", G.box(0.36, 0.3, 0.02), [-2.6 + i * 0.46, 1.3 + j * 0.42, -2.94], null, null, 0x2a2228); if ((i + j) % 3 === 0) VT.add("plain", G.box(0.25, 0.2, 0.05), [-2.6 + i * 0.46, 1.25 + j * 0.42, -2.92], null, null, PAPER); }
  // the desk, the oversized chair, the ledger, the stamp pad (the hero risk desk with its scales replaces them)
  standin("rookdesk", function () {
    VT.add("wood", G.rbox(2.8, 0.1, 1.1, 0.18, 18), [0.2, 0.84, -0.7], null, null, WALNUT);
    VT.add("brass", G.box(2.82, 0.04, 0.03), [0.2, 0.84, -0.14], null, null, BRASS);
    [-0.9, 1.3].forEach(function (x) { VT.add("wood", G.rbox(0.8, 0.8, 0.95, 0.15, 14), [x, 0.4, -0.72], null, null, WALNUT_DARK);
      [0.25, 0.55].forEach(function (y) { VT.add("brass", G.box(0.18, 0.03, 0.03), [x, y, -0.23], null, null, BRASS); }); });
    VT.add("plain", G.box(0.5, 0.025, 0.36), [-0.35, 0.9, -0.55], [0, 0.1, 0], null, PAPER); VT.add("plain", G.box(0.5, 0.025, 0.36), [0.15, 0.9, -0.55], [0, -0.1, 0], null, PAPER);
    VT.add("wood", G.box(1.02, 0.02, 0.38), [-0.1, 0.885, -0.55], null, null, 0x6a2a20);
    VT.add("iron", G.rbox(0.2, 0.04, 0.14, 0.3, 10), [0.75, 0.9, -0.5], null, null, IRON);
    VT.add("plain", G.cyl(0.06, 0.05, 0.12, 14), [1.35, 0.95, -0.45], null, null, 0xfbf6ee);
    [[-0.95, -0.6], [-0.75, -0.95]].forEach(function (q) { VT.add("plain", G.box(0.3, 0.12, 0.4), [q[0], 0.95, q[1]], [0, q[0], 0], null, 0x5a3a2a); });
    chair(VT, 0.2, -1.55, 0, 1.55, 0x6e2a22, 0.75);
  });
  VT.add("brass", G.box(0.6, 0.05, 0.2), [-3.35, 0.58, 0.2 * -1], [0, Math.PI / 2, 0], null, BRASS);
  shelf(VT, 3.2, -1.0, -Math.PI / 2, 1.4, 2.2, 3, 20);
  armillary(VT, 2.6, 0, 2.4, 0.7);
  hangingLamp(VT, -0.5, 4.4, -0.6, 1.1); hangingLamp(VT, 1.1, 4.4, 0.4, 1.2);
  pot(VT, -3.0, 2.6, 1.1); pot(VT, 3.0, -2.6, 1.0);
  (function () { const p = VT.at(0.2, 2.7, -0.6); practical("vault", 0xffb057, p.x, p.y, p.z, 26, 10); })();

  // -- the observatory (rear, raised): round walls with tall windows, a glass dome, the brass telescope
  const OB = RF.observatory;
  OB.add("pavers", G.cyl(5.5, 5.5, 0.04, 72), [0, -0.019, 0], null, null, 0xdcd4ca);
  OB.add("plain", G.cyl(1.4, 1.4, 0.01, 48), [0.6, 0.004, -1.2], null, null, 0x1d2350);
  [1.45, 3.2, 5.2].forEach(function (r) { OB.add("brass", new THREE.RingGeometry(r - 0.03, r + 0.03, 96).rotateX(-Math.PI / 2), [0, 0.006, 0], null, null, BRASS); });
  for (let i = 0; i < 8; i++) { const g = G.box(0.04, 0.004, 3.6); g.translate(0, 0, 3.4); OB.add("brass", g, [0, 0.007, 0], [0, i * Math.PI / 4, 0], null, BRASS_DARK); }
  (function () {
    const R = 5.55, a0 = 160 * Math.PI / 180, a1 = 380 * Math.PI / 180, n = 8, step = (a1 - a0) / n;
    for (let i = 0; i < n; i++) {
      const a = a0 + (i + 0.5) * step, chord = 2 * R * Math.sin(step / 2) + 0.06, x = Math.cos(a) * R, z = Math.sin(a) * R;
      const solid = i === 3 || i === 4;
      archWall(OB, chord, 4.0, 0.4, solid ? [] : [{ x: 0, w: 1.25, y0: 0.75, sp: 2.75 }], [x, 0, z], Math.PI / 2 - a + Math.PI, CREAM);
      const ea = a0 + i * step; column(OB, Math.cos(ea) * (R + 0.05), Math.sin(ea) * (R + 0.05), 4.0, 0.26);
      if (solid) { const sx = Math.cos(a) * (R - 0.25), sz = Math.sin(a) * (R - 0.25), ry = Math.PI / 2 - a + Math.PI;
        screen(OB, sx, 1.95, sz, ry, 1.5, 0.95, i === 3 ? "stars" : "rings", i === 3 ? "#8fb0ff" : "#b892ff", 0, 1.6);
        const up = V3(Math.cos(a) * (R - 0.24), 3.15, Math.sin(a) * (R - 0.24)); screen(OB, up.x, up.y, up.z, ry, 0.7, 0.5, "stars", "#a6c2ff", 0, 1.4); }
    }
    column(OB, Math.cos(a1) * (R + 0.05), Math.sin(a1) * (R + 0.05), 4.0, 0.26);
    OB.add("stone", G.tor(R, 0.24, 8, 64, a1 - a0), [0, 4.1, 0], [Math.PI / 2, 0, a0], [1, 1, 0.8], CREAM2);
    // the dome: glass in brass ribs
    OB.add("glass", G.sph(5.65, 48, 20, 0, TAU, 0, Math.PI / 2), [0, 4.2, 0], null, [1, 0.78, 1]);
    for (let k = 0; k < 12; k++) OB.add("brass", G.tor(5.66, 0.045, 6, 30, Math.PI / 2), [0, 4.2, 0], [0, k * Math.PI / 6, 0], [1, 0.78, 1], BRASS);
    [0.35, 0.7].forEach(function (f) { const ang = f * Math.PI / 2; OB.add("brass", G.tor(5.66 * Math.cos(ang), 0.04, 6, 64), [0, 4.2 + 5.66 * 0.78 * Math.sin(ang), 0], [Math.PI / 2, 0, 0], null, BRASS); });
    OB.add("brass", G.tor(5.66, 0.08, 8, 96), [0, 4.2, 0], [Math.PI / 2, 0, 0], null, BRASS);
  })();
  OB.add("wood", G.rbox(2.4, 0.08, 0.8, 0.2, 16), [-2.4, 0.76, -3.6], [0, 0.55, 0], null, WALNUT);
  [[-3.1, -3.2], [-1.75, -4.1]].forEach(function (q) { OB.add("wood", G.box(0.08, 0.72, 0.7), [q[0], 0.36, q[1]], [0, 0.55, 0], null, WALNUT_DARK); });
  OB.add("brass", G.cyl(0.03, 0.05, 0.2, 10), [-2.0, 0.9, -3.95], null, null, BRASS); OB.add("plain", G.sph(0.14, 18, 12), [-2.0, 1.12, -3.95], null, null, 0x2c4c8a);
  OB.add("brass", G.tor(0.16, 0.012, 6, 20), [-2.0, 1.12, -3.95], [0.4, 0, 0], null, BRASS);
  OB.add("plain", G.box(0.3, 0.05, 0.22), [-2.7, 0.83, -3.4], [0, 0.4, 0], null, 0x6a2a2a); OB.add("plain", G.box(0.28, 0.02, 0.2), [-2.4, 0.81, -3.5], [0, 0.7, 0], null, PAPER);
  armillary(OB, 3.2, 0, -2.6, 0.9);
  pot(OB, -4.6, 1.5, 1.2); pot(OB, 4.6, 1.5, 1.2); pot(OB, -4.2, -2.5, 1.1);
  (function () { const p = OB.at(0, 3.2, -1.0); practical("observatory", 0x8ea2ff, p.x, p.y, p.z, 16, 11); })();
  // the steps up from the courtyard, with carved side walls and brass handrails
  for (let i = 0; i < 10; i++) { const zf = -6.2 - 0.25 * i, depth = zf + 8.8;
    WF.add("stone", G.box(3.2, 0.18 * (i + 1), depth), [0, 0.09 * (i + 1), zf - depth / 2], null, null, i % 2 ? CREAM : 0xe9dabf);
    WF.add("brass", G.box(3.2, 0.012, 0.03), [0, 0.18 * (i + 1) + 0.006, zf - 0.02], null, null, BRASS_DARK); }
  [-1.76, 1.76].forEach(function (x) {
    const sh = new THREE.Shape(); sh.moveTo(0, 0); sh.lineTo(0, 0.55); sh.lineTo(2.62, 2.35); sh.lineTo(2.62, 0); sh.lineTo(0, 0);
    const g = new THREE.ExtrudeGeometry(sh, { depth: 0.34, bevelEnabled: false }).rotateY(Math.PI / 2);
    WF.add("stone", g, [x - 0.17, 0, -6.2], null, null, CREAM2);
    bar("brass", V3(x, 1.0, -6.2), V3(x, 2.82, -8.8), 0.04, BRASS);
    WF.add("brass", G.sph(0.1, 14, 10), [x, 1.0, -6.18], null, null, BRASS);
  });
  [[103.5, 168], [76.5, 12]].forEach(function (q) { const pts = [], n = 8; for (let k = 0; k <= n; k++) { const a = (q[0] + (q[1] - q[0]) * k / n) * Math.PI / 180;
    pts.push(V3(Math.cos(a) * 6.72, 1.8, -15.5 + Math.sin(a) * 6.72)); } railing(pts, { lamps: 4 }); });

  // ------------------------------------------------------------- paths from the hub to every door
  [[200, RF.workshop.at(0, 0, 4.0)], [340, RF.den.at(0, 0, 4.0)], [135, RF.archive.at(0, 0, 3.7)], [45, RF.vault.at(0, 0, 3.7)]].forEach(function (q) {
    const a = q[0] * Math.PI / 180, s = V3(Math.cos(a) * COURT_R, 0, Math.sin(a) * COURT_R), e = q[1], mid = s.clone().add(e).multiplyScalar(0.5), len = s.distanceTo(e) + 0.6;
    WF.add("pavers", G.box(2.4, 0.02, len), [mid.x, 0.001, mid.z], [0, Math.atan2(e.x - s.x, e.z - s.z), 0], null, 0xe4d2b2);
  });

  // ------------------------------------------------------------- the glass parcel tube along the rails (parcels glide through it)
  const tubeCurve = new THREE.CatmullRomCurve3([V3(21.35, 0.95, -0.2), V3(21.1, 1.9, 0.3), V3(19.5, 2.75, 0.7), V3(18.0, 1.9, 1.3), V3(17.95, 1.25, 2.6),
    V3(17.95, 1.25, 4.9), V3(17.95, 2.75, 6.3), V3(17.95, 1.25, 7.7), V3(17.95, 1.25, 16.0), V3(17.4, 1.25, 17.42), V3(9.0, 1.25, 17.42), V3(3.6, 1.25, 17.42),
    V3(2.4, 2.75, 16.2), V3(1.78, 1.25, 14.8), V3(1.75, 1.25, 9.0), V3(1.78, 1.15, 6.9), V3(2.3, 0.75, 5.95)], false, "centripetal", 0.5);
  WF.add("glass", new THREE.TubeGeometry(tubeCurve, 420, 0.17, 14, false));
  (function () {
    const L = tubeCurve.getLength(), o = new THREE.Object3D();
    for (let s = 0.4; s < L; s += 2.1) { const u = s / L, p = tubeCurve.getPointAt(u), t = tubeCurve.getTangentAt(u);
      o.position.copy(p); o.lookAt(p.clone().add(t)); o.updateMatrix(); const g = G.tor(0.19, 0.035, 6, 18); g.applyMatrix4(o.matrix); paint(g, BRASS); pushBucket("brass", g);
      if (Math.round(s / 2.1) % 2 === 0 && p.y < 1.4) bar("brass", V3(p.x, 0, p.z), V3(p.x, p.y - 0.17, p.z), 0.025, BRASS_DARK); }
    WF.add("brass", G.rbox(0.5, 0.75, 0.5, 0.25, 14), [21.35, 0.5, -0.25], null, null, BRASS);
    WF.add("brass", G.rbox(0.55, 0.5, 0.55, 0.25, 14), [2.4, 0.45, 5.75], null, null, BRASS);
  })();

  // ------------------------------------------------------------- bushes round the island rim, cypress trees, potted courtyard plants
  DISCS.forEach(function (d, i) {
    const n = Math.round(d[2] * 2.2);
    for (let k = 0; k < n; k++) {
      const a = k / n * TAU + i, x = d[0] + Math.cos(a) * (d[2] - 0.55), z = d[1] + Math.sin(a) * (d[2] - 0.55);
      if (DISCS.some(function (o, j) { return j !== i && Math.hypot(x - o[0], z - o[1]) < o[2] - 0.2; })) continue;
      if (Math.abs(x) < 2.2 && z > 5) continue;  // the bridge
      if (x > 13.5 && z > 4.5 && z < 8) continue;  // the hatch path
      if (Math.hypot(x, z) < COURT_R + 1.2) continue;
      bush(x, d[3], z, 0.7 + ((k * 37 + i * 11) % 10) / 14, 4);
    }
  });
  [[-16.2, -7.2, 6.5], [-16.8, 0.8, 5.2], [16.0, -7.3, 6.2], [-5.6, -18.5, 7.0], [5.8, -18.6, 6.4], [-8.6, -12.5, 5.0], [8.7, -12.6, 5.3],
   [-14.4, 12.6, 5.6], [14.2, 13.2, 4.8], [-4.6, 10.4, 4.2], [4.7, 10.2, 4.4], [-3.6, -21.5, 5.6]].forEach(function (t, i) {
    if (!onIsland(t[0], t[1], 0.3) && i < 11) return; cypresses.push({ p: [t[0], DISCS.reduce(function (m, d) { return Math.hypot(t[0] - d[0], t[1] - d[1]) < d[2] ? Math.max(m, d[3]) : m; }, 0), t[1]], s: [1, t[2], 1] });
  });
  [[1.6, 3.9], [-1.6, 3.9], [3.9, -1.0], [-3.9, -1.0]].forEach(function (q) { pot(WF, q[0] * 1.32, q[1] * 1.32, 1.0); });

  // ------------------------------------------------------------- distant floating islands with towers (silhouettes in the haze)
  (function () {
    const r = rng(91), farMat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 1, flatShading: true }), geos = [];
    [[-190, 24, -280, 22], [240, 36, -320, 28], [330, 8, 30, 18], [-340, 14, 70, 20], [70, 58, -470, 34], [-60, -4, 380, 16], [170, 18, 260, 14], [-250, 46, -120, 12]].forEach(function (s) {
      const R = s[3], rock = new THREE.ConeGeometry(R, R * 1.8, 9, 3).rotateX(Math.PI); rock.translate(0, -R * 0.9, 0);
      const p = rock.attributes.position; for (let i = 0; i < p.count; i++) { if (p.getY(i) > -0.01) continue; p.setXYZ(i, p.getX(i) * (0.8 + r() * 0.4), p.getY(i), p.getZ(i) * (0.8 + r() * 0.4)); }
      paint(rock, 0x5d4b6e); rock.translate(s[0], s[1], s[2]); geos.push(rock);
      const top = G.cyl(R, R * 0.96, 1.2, 12); paint(top, 0x6f6084); top.translate(s[0], s[1] + 0.6, s[2]); geos.push(top);
      for (let k = 0; k < 5 + Math.floor(R / 5); k++) {
        const a = r() * TAU, d = r() * R * 0.6, h = 4 + r() * R * 0.9, w = 1.5 + r() * 2.5, x = s[0] + Math.cos(a) * d, z = s[2] + Math.sin(a) * d;
        const t = G.cyl(w, w * 1.05, h, 8); paint(t, 0x9a8db0); t.translate(x, s[1] + 1.2 + h / 2, z); geos.push(t);
        const c = G.cone(w * 1.3, w * 2.4, 8); paint(c, 0x4a3d70); c.translate(x, s[1] + 1.2 + h + w * 1.2, z); geos.push(c);
        for (let j = 0; j < 3; j++) { const wg = G.box(0.6, 0.9, 0.2); paint(wg, hdr(0xffc070, 3.5)); wg.translate(x + Math.cos(j * 2) * w * 1.02, s[1] + 1.2 + h * (0.3 + j * 0.2), z + Math.sin(j * 2) * w * 1.02); pushBucket("glow", wg); }
      }
    });
    const m = new THREE.Mesh(mergeGeometries(geos.map(prep), false), farMat); scene.add(m);
  })();

  // ------------------------------------------------------------- animated set pieces (their own meshes)
  const props = {};
  // the holographic map on the table: rings, the miniature headquarters, a wire dome, icon cards
  (function () {
    const holoTex = canvasTex(1024, 1024, function (ctx, w, h) {
      const c = w / 2; ctx.translate(c, c);
      const g = ctx.createRadialGradient(0, 0, 10, 0, 0, c); g.addColorStop(0, "rgba(120,255,214,.55)"); g.addColorStop(0.75, "rgba(60,220,180,.25)"); g.addColorStop(1, "rgba(60,220,180,0)");
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(0, 0, c, 0, TAU); ctx.fill();
      ctx.strokeStyle = "rgba(190,255,235,.9)"; ctx.shadowColor = "#7dffd8"; ctx.shadowBlur = 14;
      [0.95, 0.8, 0.62, 0.4, 0.2].forEach(function (f, i) { ctx.lineWidth = i ? 3 : 7; ctx.beginPath(); ctx.arc(0, 0, c * f, 0, TAU); ctx.stroke(); });
      ctx.lineWidth = 2; for (let i = 0; i < 72; i++) { const a = i / 72 * TAU, l = i % 6 ? 0.9 : 0.84; ctx.beginPath(); ctx.moveTo(Math.cos(a) * c * l, Math.sin(a) * c * l); ctx.lineTo(Math.cos(a) * c * 0.95, Math.sin(a) * c * 0.95); ctx.stroke(); }
      for (let i = 0; i < 8; i++) { const a = i / 8 * TAU; ctx.beginPath(); ctx.moveTo(Math.cos(a) * c * 0.2, Math.sin(a) * c * 0.2); ctx.lineTo(Math.cos(a) * c * 0.8, Math.sin(a) * c * 0.8); ctx.stroke(); }
    });
    holoTex.wrapS = holoTex.wrapT = THREE.ClampToEdgeWrapping;
    const disc = new THREE.Mesh(new THREE.CircleGeometry(1.44, 96).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ map: holoTex, color: hdr(0x9dffe0, 1.9), transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
    disc.position.y = 0.792; scene.add(disc); props.holoDisc = disc;
    const holoMat = new THREE.MeshBasicMaterial({ color: hdr(0x7dffd8, 1.5), transparent: true, opacity: 0.42, blending: THREE.AdditiveBlending, depthWrite: false });
    const mini = new THREE.Group(); mini.position.y = 1.05; scene.add(mini); props.holoMini = mini;
    const S = 0.062, spots = [[0, 0, 0.5, 0], [-11.8, -3, 0.38, 1], [11.8, -3, 0.38, 2], [-9.8, 9.4, 0.34, 3], [9.8, 9.4, 0.34, 4], [0, -15.5, 0.42, 5], [19.5, 0, 0.22, 6], [0, 20.4, 0.2, 7]];
    const mg = [];
    spots.forEach(function (s) {
      const x = s[0] * S, z = s[1] * S, r = s[2];
      const rock = G.cone(r * 0.9, r * 1.1, 8).rotateX(Math.PI); rock.translate(x, -r * 0.55, z); mg.push(rock);
      const top = G.cyl(r * 0.9, r * 0.9, 0.02, 16); top.translate(x, 0, z); mg.push(top);
      const b = s[3] === 5 ? G.sph(r * 0.45, 12, 8, 0, TAU, 0, Math.PI / 2) : s[3] === 0 ? G.cyl(r * 0.25, r * 0.25, 0.05, 16) : G.box(r * 0.7, r * 0.45, r * 0.6); b.translate(x, s[3] === 5 ? 0.01 : r * 0.22, z); mg.push(b);
      if (s[3] === 1 || s[3] === 2 || s[3] === 5) { const t = G.cone(r * 0.2, r * 0.5, 6); t.translate(x + r * 0.2, r * 0.6, z); mg.push(t); }
    });
    mini.add(new THREE.Mesh(mergeGeometries(mg.map(prep), false), holoMat));
    const dome = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.SphereGeometry(1.35, 16, 6, 0, TAU, 0, Math.PI / 2), 1),
      new THREE.LineBasicMaterial({ color: hdr(0x7dffd8, 1.2), transparent: true, opacity: 0.22, blending: THREE.AdditiveBlending, depthWrite: false }));
    dome.scale.y = 0.55; dome.position.y = 0.8; scene.add(dome); props.holoDome = dome;
    // floating icon cards (pictures, never words): a book, a gem, a wrench, a gear
    const cards = new THREE.Group(); cards.position.y = 1.42; scene.add(cards); props.holoCards = cards;
    ["book", "gem", "wrench", "gear"].forEach(function (kind, i) {
      const t = canvasTex(128, 128, function (ctx) {
        ctx.fillStyle = "rgba(40,120,110,.35)"; roundRect(ctx, 6, 6, 116, 116, 14); ctx.fill(); ctx.strokeStyle = "rgba(190,255,235,.95)"; ctx.lineWidth = 4; roundRect(ctx, 6, 6, 116, 116, 14); ctx.stroke();
        ctx.lineWidth = 5; ctx.beginPath();
        if (kind === "book") { ctx.moveTo(30, 40); ctx.lineTo(64, 48); ctx.lineTo(98, 40); ctx.lineTo(98, 92); ctx.lineTo(64, 100); ctx.lineTo(30, 92); ctx.closePath(); ctx.moveTo(64, 48); ctx.lineTo(64, 100); }
        else if (kind === "gem") { ctx.moveTo(64, 26); ctx.lineTo(98, 60); ctx.lineTo(64, 102); ctx.lineTo(30, 60); ctx.closePath(); ctx.moveTo(30, 60); ctx.lineTo(98, 60); }
        else if (kind === "wrench") { ctx.moveTo(40, 92); ctx.lineTo(80, 52); ctx.arc(88, 42, 14, 2.4, 5.6); }
        else { ctx.arc(64, 64, 22, 0, TAU); for (let k = 0; k < 8; k++) { const a = k / 8 * TAU; ctx.moveTo(64 + Math.cos(a) * 26, 64 + Math.sin(a) * 26); ctx.lineTo(64 + Math.cos(a) * 36, 64 + Math.sin(a) * 36); } }
        ctx.stroke();
      });
      const m = new THREE.Mesh(new THREE.PlaneGeometry(0.26, 0.26), new THREE.MeshBasicMaterial({ map: t, color: hdr(0xffffff, 1.6), transparent: true, depthWrite: false, side: THREE.DoubleSide }));
      const a = i / 4 * TAU + 0.4; m.position.set(Math.cos(a) * 1.05, (i % 2) * 0.12, Math.sin(a) * 1.05); m.userData.a = a; cards.add(m);
    });
    // fit the whole hologram to a table top of radius r at height y (the procedural table, then the hero prop)
    props.holoFit = function (r, y) {
      const k = r / 1.44; props.holoK = k; props.holoY = y;
      disc.scale.setScalar(k); disc.position.y = y; mini.scale.setScalar(k); dome.scale.set(k, 0.55 * k, k); dome.position.y = y + 0.008 * k;
      cards.scale.setScalar(k); cards.position.y = y + 0.63 * k;
    };
    props.holoFit(1.44, 0.792);
  })();
  // the telescope: turns slowly on its mount
  (function () {
    const g = new THREE.Group(); OB.place(g, 0.6, 0, -1.2, 0); props.telescope = g; STANDIN.telescope = [g];
    const parts = new THREE.Group(); g.add(parts);
    const pm = function (geo, c, p, r) { const m = new THREE.Mesh(paint(geo, c), MAT.brass); if (p) m.position.set(p[0], p[1], p[2]); if (r) m.rotation.set(r[0], r[1], r[2]); m.castShadow = Q.shadows; return m; };
    for (let k = 0; k < 3; k++) { const leg = pm(G.cyl(0.05, 0.07, 1.4, 10), BRASS_DARK, [Math.cos(k * TAU / 3) * 0.45, 0.62, Math.sin(k * TAU / 3) * 0.45]); leg.rotation.set(Math.sin(k * TAU / 3) * 0.35, 0, -Math.cos(k * TAU / 3) * 0.35); parts.add(leg); }
    parts.add(pm(G.cyl(0.16, 0.2, 0.5, 18), BRASS, [0, 1.3, 0]));
    parts.add(pm(G.tor(0.2, 0.04, 8, 24), COPPER, [0, 1.55, 0], [Math.PI / 2, 0, 0]));
    const yoke = new THREE.Group(); yoke.position.y = 1.62; parts.add(yoke); props.telescopeYoke = yoke;
    [-0.24, 0.24].forEach(function (x) { yoke.add(pm(G.box(0.06, 0.55, 0.14), BRASS_DARK, [x, 0.25, 0])); });
    const tube = new THREE.Group(); tube.position.y = 0.45; tube.rotation.x = -0.75; yoke.add(tube); props.telescopeTube = tube;
    tube.add(pm(G.cyl(0.2, 0.17, 2.6, 28), BRASS, [0, 0, 0.45], [Math.PI / 2, 0, 0]));
    tube.add(pm(G.cyl(0.26, 0.24, 0.6, 28), BRASS_DARK, [0, 0, 1.75], [Math.PI / 2, 0, 0]));
    [-0.6, 0.0, 0.7, 1.4].forEach(function (z) { tube.add(pm(G.tor(0.215, 0.03, 8, 28), COPPER, [0, 0, z])); });
    tube.add(pm(G.cyl(0.05, 0.05, 0.3, 12), BRASS_DARK, [0, 0.1, -0.95], [Math.PI / 2 + 0.6, 0, 0]));
    tube.add(pm(G.cyl(0.07, 0.04, 0.6, 12), BRASS, [0.2, 0.15, 0.3], [Math.PI / 2, 0, 0]));
    tube.add(pm(G.tor(0.12, 0.02, 6, 20), BRASS, [0.27, 0, 0], [0, Math.PI / 2, 0]));
    const lens = new THREE.Mesh(G.cyl(0.235, 0.235, 0.02, 28), MAT.glass); lens.rotation.x = Math.PI / 2; lens.position.z = 2.05; tube.add(lens);
  })();
  // the airship moored at the dock: bobs, its propellers turn
  (function () {
    const g = new THREE.Group(); g.position.set(29.6, 2.35, -1.6); scene.add(g); props.airship = g; STANDIN.airship = [g];
    const add = function (geo, key, c, p, r, s) { const m = new THREE.Mesh(paint(geo, c), MAT[key]); if (p) m.position.set(p[0], p[1], p[2]); if (r) m.rotation.set(r[0], r[1], r[2]); if (s) m.scale.set(s[0], s[1], s[2]); m.castShadow = Q.shadows; g.add(m); return m; };
    add(G.sph(1, 40, 24), "cloth", 0xf1e5cb, [0, 0.6, 0], null, [4.0, 1.5, 1.5]);
    [-2.6, -1.2, 0.2, 1.6, 2.9].forEach(function (x) { const k = Math.sqrt(Math.max(0.05, 1 - (x / 4) * (x / 4))); add(G.tor(1.5 * k + 0.01, 0.035, 6, 40), "brass", BRASS, [x, 0.6, 0], [0, Math.PI / 2, 0], [1, 1, 1]); });
    add(G.sph(0.32, 16, 12), "brass", COPPER, [4.0, 0.6, 0]);
    [[0, 1], [0, -1], [1, 0], [-1, 0]].forEach(function (f) { add(G.rbox(1.2, 0.06, 0.9, 0.3, 12), "cloth", 0xd9805d, [-3.7, 0.6 + f[1] * 0.75, f[0] * 0.75], [f[0] ? Math.PI / 2 : 0, 0, 0]); });
    add(G.rbox(3.0, 0.75, 1.1, 0.25, 22), "wood", WALNUT, [0.2, -1.4, 0]);
    add(G.box(3.02, 0.05, 1.12), "brass", BRASS, [0.2, -1.05, 0]);
    for (let k = 0; k < 5; k++) [-0.56, 0.56].forEach(function (z) { add(G.box(0.26, 0.2, 0.02), "glow", hdr(0xffc27a, 3.2), [-0.8 + k * 0.5, -1.3, z]); });
    [[-1.0, 0.45], [1.3, 0.45], [-1.0, -0.45], [1.3, -0.45]].forEach(function (q) { const m = add(G.cyl(0.012, 0.012, 1.7, 4), "iron", IRON, [q[0], -0.4, q[1]]); m.rotation.z = q[0] * 0.08; });
    props.propellers = [];
    [-0.6, 0.6].forEach(function (z) { const hub = new THREE.Group(); hub.position.set(-1.6, -1.25, z * 1.4); g.add(hub);
      const hm = new THREE.Mesh(paint(G.cyl(0.08, 0.08, 0.25, 12), BRASS), MAT.brass); hm.rotation.z = Math.PI / 2; hub.add(hm);
      for (let k = 0; k < 3; k++) { const b = new THREE.Mesh(paint(G.rbox(0.04, 0.55, 0.12, 0.3, 10), WALNUT), MAT.wood); b.position.y = 0; b.rotation.x = k * TAU / 3; b.geometry.translate(0, 0.28, 0); hub.add(b); }
      props.propellers.push(hub); });
    standin("airship", function () { WF.add("brass", G.box(2.9, 0.05, 0.7), [26.95, 0.27, -1.5], [0, 0, 0.19], null, BRASS_DARK); });
  })();
  // two small delivery drones looping round the island (decorative)
  props.drones = [0, 1].map(function (i) {
    const g = new THREE.Group(); scene.add(g);
    g.add(new THREE.Mesh(paint(G.rbox(0.36, 0.2, 0.36, 0.3, 14), BRASS), MAT.brass));
    [[1, 1], [1, -1], [-1, 1], [-1, -1]].forEach(function (q) { const r = new THREE.Mesh(paint(G.tor(0.12, 0.02, 6, 16), BRASS_DARK), MAT.brass); r.rotation.x = Math.PI / 2; r.position.set(q[0] * 0.25, 0.08, q[1] * 0.25); g.add(r); });
    const eye = new THREE.Mesh(paint(G.sph(0.06, 10, 8), hdr(i ? 0x7dffd8 : 0xffc27a, 4)), MAT.glow); eye.position.set(0, -0.02, 0.18); g.add(eye);
    return { g: g, phase: i * Math.PI, r: 21 + i * 6, y: 5 + i * 2.2, speed: 0.07 + i * 0.025 };
  });
  // parcels gliding through the glass tube (violet and mint: never the colours of a trade)
  props.parcels = (function () {
    const n = 7, im = new THREE.InstancedMesh(paint(G.rbox(0.18, 0.18, 0.18, 0.4, 10), 0xffffff), new THREE.MeshBasicMaterial({ vertexColors: true }), n);
    for (let i = 0; i < n; i++) im.setColorAt(i, hdr(i % 2 ? 0xb58cff : 0x7dffd8, 2.4));
    im.frustumCulled = false; scene.add(im); return { im: im, n: n, len: tubeCurve.getLength() };
  })();

  // ------------------------------------------------------------- instanced: railing posts, lanterns, plants, books
  (function () {
    const post = new THREE.LatheGeometry([[0.0, 0], [0.05, 0], [0.05, 0.05], [0.025, 0.1], [0.022, 0.75], [0.035, 0.8], [0.02, 0.92], [0.035, 0.97], [0.0, 1.02]].map(function (q) { return new THREE.Vector2(q[0], q[1]); }), 10);
    instanced(paint(post, BRASS), MAT.brass, railPosts.map(function (q) { return { p: q.p, s: q.s ? q.s : 1 }; }));
    const lg = [];
    const add = function (g, c, x, y, z) { g.translate(x, y, z); paint(g, c); lg.push(prep(g)); };
    add(G.cyl(0.03, 0.05, 1.7, 8), BRASS_DARK, 0, 0.85, 0); add(G.cyl(0.09, 0.11, 0.1, 10), BRASS_DARK, 0, 0.05, 0);
    add(G.cone(0.13, 0.16, 8), BRASS, 0, 2.14, 0); add(G.cyl(0.1, 0.1, 0.03, 8), BRASS, 0, 1.71, 0); add(G.sph(0.03, 8, 6), BRASS, 0, 2.24, 0);
    for (let k = 0; k < 4; k++) add(G.box(0.014, 0.32, 0.014), BRASS, Math.cos(k * Math.PI / 2 + 0.78) * 0.085, 1.88, Math.sin(k * Math.PI / 2 + 0.78) * 0.085);
    const lgeo = mergeGeometries(lg, false);
    props.lanternPosts = instanced(lgeo, MAT.brass, lanterns.map(function (q) { return { p: q.p, s: [1, q.h, 1] }; }));
    props.lanternBulbs = instanced(paint(G.sph(0.06, 10, 8), 0xffffff), new THREE.MeshBasicMaterial({ vertexColors: true, color: hdr(0xffc47e, 6) }), lanterns.map(function (q) { return { p: [q.p[0], q.p[1] + 1.88 * q.h, q.p[2]], s: [1, 1.5, 1] }; }));
    // soft halos round the lanterns: one additive billboard draw
    const haloMat = new THREE.ShaderMaterial({ transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, uniforms: { uMap: { value: glowTex } },
      // (a halo fades out as the drone comes close, so a lamp passing the lens never blooms over the shot)
      vertexShader: "varying vec2 vUv; varying float vFade; void main() { vUv = uv; vec4 c = modelViewMatrix * instanceMatrix * vec4(0.0, 0.0, 0.0, 1.0); vFade = smoothstep(1.4, 3.6, -c.z); c.xy += position.xy * length(instanceMatrix[0].xyz); gl_Position = projectionMatrix * c; }",
      fragmentShader: "uniform sampler2D uMap; varying vec2 vUv; varying float vFade; void main() { float a = texture2D(uMap, vUv).r; gl_FragColor = vec4(vec3(1.0, 0.62, 0.3) * a * 0.4 * vFade, 1.0); }" });
    const halos = new THREE.InstancedMesh(new THREE.PlaneGeometry(1, 1), haloMat, lanterns.length);
    lanterns.forEach(function (q, i) { halos.setMatrixAt(i, mat4([q.p[0], q.p[1] + 1.88 * q.h, q.p[2]], null, 0.72)); });
    halos.frustumCulled = false; halos.renderOrder = 4; scene.add(halos); props.lanternHalos = halos;
    // plants
    instanced(crag(0.5, 1, 3, 1), MAT.leaf, bushes, false);
    const bloomGeo = (function () { const parts = [], r = rng(5); for (let i = 0; i < 9; i++) { const g = G.sph(0.3, 6, 5); g.translate((r() - 0.5) * 0.6, (r() - 0.5) * 0.4, (r() - 0.5) * 0.6); parts.push(prep(g)); } return mergeGeometries(parts, false); })();
    instanced(bloomGeo, MAT.leaf, blooms, false);
    instanced(paint(crag(0.5, 0, 9, 0.55), 0xffffff), MAT.leaf, leaves.map(function (q) { return { p: q.p, r: q.r, s: q.s, c: [0x4a8a3e, 0x3c7a3a, 0x5e9a48][Math.floor((q.p[0] * 13 + q.p[1] * 7) % 3 + 3) % 3] }; }), false);
    const raceme = (function () { const parts = [], r = rng(8); for (let i = 0; i < 12; i++) { const t = i / 11, g = G.sph(0.11 * (1 - t * 0.6), 6, 5);
      g.translate((r() - 0.5) * 0.12 * (1 - t), -t * 0.6, (r() - 0.5) * 0.12 * (1 - t)); paint(g, _c.set(0xffffff).lerp(col(0xc9b0ff), t)); parts.push(prep(g)); } return mergeGeometries(parts, false); })();
    instanced(raceme, MAT.leaf, racemes, false);
    const cyp = new THREE.LatheGeometry([[0, 0], [0.12, 0], [0.12, 0.6], [0.55, 0.9], [0.75, 1.6], [0.8, 2.4], [0.7, 3.4], [0.5, 4.4], [0.25, 5.2], [0, 5.7]].map(function (q) { return new THREE.Vector2(q[0], q[1] / 5.7); }), 12);
    instanced(paint(cyp, function (x, y) { return _c.set(y < 0.1 ? 0x5a3a26 : 0x2f5e36).lerp(col(0x4f8a46), clamp(y * 0.8, 0, 0.6)); }), MAT.leaf, cypresses, true);
    instanced(paint(G.box(1, 1, 1), 0xffffff), MAT.plain, books, false);
  })();
  flushStatic();
"""

_M_CAST = r"""
  // ============================================================= THE CAST (drawn until real models are dropped in)
  const CMAT = {
    owl: new THREE.MeshStandardMaterial({ vertexColors: true, map: featherTex, roughness: 0.72, envMapIntensity: 0.7 }),
    fox: new THREE.MeshStandardMaterial({ vertexColors: true, map: furTex, roughness: 0.8, envMapIntensity: 0.6 }),
    octo: new THREE.MeshPhysicalMaterial({ vertexColors: true, map: speckleTex, roughness: 0.38, clearcoat: 0.7, clearcoatRoughness: 0.3,
                                           sheen: 0.6, sheenColor: new THREE.Color(0xffd6ff), envMapIntensity: 0.85 }),
    cloth: new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.82, envMapIntensity: 0.55 }),
    cape: new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.78, side: THREE.DoubleSide, envMapIntensity: 0.6 }),
    leather: new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.5, envMapIntensity: 0.75 }),
    glossy: new THREE.MeshPhysicalMaterial({ vertexColors: true, roughness: 0.3, clearcoat: 1, clearcoatRoughness: 0.06, envMapIntensity: 1.1 }),
    visor: new THREE.MeshPhysicalMaterial({ color: 0x07080c, roughness: 0.06, metalness: 0.3, clearcoat: 1, clearcoatRoughness: 0.02, envMapIntensity: 1.8 }),
    rubber: new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.55, envMapIntensity: 0.6 }),
    rock: new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.88, flatShading: true, envMapIntensity: 0.5 }),
    magma: new THREE.MeshStandardMaterial({ color: 0x2a1408, emissive: 0xff7418, emissiveIntensity: 2.4, roughness: 0.8 }),
    ghost: new THREE.MeshPhysicalMaterial({ color: 0xaaf8d6, emissive: 0x3fe0a6, emissiveIntensity: 0.6, roughness: 0.22, clearcoat: 1,
                                            transparent: true, opacity: 0.84, envMapIntensity: 0.9 }),
    lens: new THREE.MeshPhysicalMaterial({ color: 0x3aa6ff, emissive: 0x1a6cff, emissiveIntensity: 0.9, roughness: 0.05, clearcoat: 1, envMapIntensity: 1.5 }),
    eye: new THREE.MeshPhysicalMaterial({ vertexColors: true, roughness: 0.14, clearcoat: 1, clearcoatRoughness: 0.03, envMapIntensity: 0.9 }),
    hi: new THREE.MeshBasicMaterial({ color: hdr(0xffffff, 1.7) }),
    brass: MAT.brass,
  };
  const shadowMat = new THREE.MeshBasicMaterial({ map: glowTex, color: 0x140a24, transparent: true, opacity: 0.6, depthWrite: false });
  // put a part on a parent: geometry, material, colour (hex or fn), position, rotation, scale
  function part(parent, geo, mat, c, p, r, s) {
    const m = new THREE.Mesh(c == null ? geo : paint(geo, c), mat);
    if (p) m.position.set(p[0], p[1], p[2]); if (r) m.rotation.set(r[0], r[1], r[2]); if (s) { if (typeof s === "number") m.scale.setScalar(s); else m.scale.set(s[0], s[1], s[2]); }
    m.castShadow = Q.shadows; parent.add(m); return m;
  }
  // merge a group's own meshes per material (moving sub-groups stay separate): a character is ~20 draws, not 200
  function bake(g) {
    const by = new Map();
    g.children.slice().forEach(function (c) {
      if (!c.isMesh || c.userData.keep) return;
      c.updateMatrix(); const geo = prep(c.geometry.clone().applyMatrix4(c.matrix));
      if (!by.has(c.material)) by.set(c.material, []); by.get(c.material).push(geo); g.remove(c);
    });
    by.forEach(function (list, m) { const mesh = new THREE.Mesh(mergeGeometries(list, false), m); mesh.castShadow = Q.shadows; g.add(mesh); });
    return g;
  }
  // animated-film eyes: glossy sclera, a coloured iris with a dark rim, the pupil, two highlights, an eyelid that blinks
  function makeEyes(parent, o) {
    const out = [];
    const iris = col(o.iris), rim = col(o.iris).multiplyScalar(0.35), light = col(o.iris).lerp(col(0xffffff), 0.35);
    [-1, 1].forEach(function (s) {
      const g = new THREE.Group(); g.position.set(s * o.sep, o.y, o.z); g.rotation.y = s * (o.spread == null ? 0.22 : o.spread); parent.add(g);
      const r = o.r, parts = [];
      if (!o.bead) parts.push(prep(paint(G.sph(r, 32, 24), 0xfcfbf7)));
      const ir = r * (o.bead ? 1.0 : 0.68), irisG = G.sph(ir, 32, 20); irisG.scale(1, 1, o.bead ? 1 : 0.42); if (!o.bead) irisG.translate(0, 0, r * 0.76);
      parts.push(prep(paint(irisG, function (x, y) { const d = Math.hypot(x, y) / ir; return _c.copy(iris).lerp(light, clamp(-y / ir * 0.7, 0, 0.6)).lerp(rim, smoothstep(d, 0.72, 1.0)); })));
      if (!o.bead) { const pu = G.sph(r * 0.38 * (o.pupil || 1), 24, 16); pu.scale(1, 1, 0.34); pu.translate(0, 0, r * 0.93); parts.push(prep(paint(pu, 0x040306))); }
      const ball = new THREE.Mesh(mergeGeometries(parts, false), CMAT.eye); g.add(ball);
      const h1 = G.sph(r * 0.16, 12, 8); h1.scale(1, 1, 0.45); h1.translate(-r * 0.3, r * 0.34, r * 1.0);
      const h2 = G.sph(r * 0.075, 10, 6); h2.scale(1, 1, 0.45); h2.translate(r * 0.27, -r * 0.24, r * 1.01);
      g.add(new THREE.Mesh(mergeGeometries([prep(h1), prep(h2)], false), CMAT.hi));
      let lid = null;
      if (o.lid != null) { lid = new THREE.Mesh(paint(G.sph(r * 1.08, 32, 14, 0, TAU, 0, Math.PI / 2), o.lid), o.lidMat || CMAT.cloth);
        lid.rotation.x = o.open == null ? -1.25 : o.open; lid.userData.open = lid.rotation.x; g.add(lid); }
      out.push({ g: g, lid: lid });
    });
    return out;
  }
  function smile(parent, R, tube, c, p, open) {
    const g = G.tor(R, tube, 8, 20, Math.PI * 0.9); g.rotateZ(Math.PI + Math.PI * 0.05);
    part(parent, g, CMAT.rubber, c, p);
    if (open) { const m = G.sph(1, 20, 12, 0, TAU, Math.PI / 2, Math.PI / 2); part(parent, m, CMAT.rubber, 0x3a1218, [p[0], p[1] + 0.002, p[2] - 0.004], null, [R * 0.92, R * 0.75, R * 0.4]); }
  }
  // a tapered tube along points (tails, Mote's curl)
  function taper(pts, r0, r1, radial) {
    const curve = new THREE.CatmullRomCurve3(pts), n = 24, g = new THREE.TubeGeometry(curve, n, 1, radial || 10, false), p = g.attributes.position;
    const frames = curve.computeFrenetFrames(n, false), ring = (radial || 10) + 1;
    for (let i = 0; i <= n; i++) { const c = curve.getPointAt(i / n), rr = lerp(r0, r1, i / n);
      for (let j = 0; j < ring; j++) { const k = i * ring + j; p.setXYZ(k, c.x + (p.getX(k) - c.x) * rr, c.y + (p.getY(k) - c.y) * rr, c.z + (p.getZ(k) - c.z) * rr); } }
    g.computeVertexNormals(); return g;
  }
  function actorBase(key, shadowR) {
    const group = new THREE.Group(); scene.add(group);
    const body = new THREE.Group(); group.add(body);
    const head = new THREE.Object3D(); group.add(head);
    const carry = new THREE.Object3D(); group.add(carry);
    const sh = new THREE.Mesh(new THREE.CircleGeometry(shadowR, 24).rotateX(-Math.PI / 2), shadowMat); sh.position.y = 0.012; sh.renderOrder = 1; group.add(sh);
    return { key: key, group: group, body: body, head: head, carry: carry, shadow: sh, eyes: [], blinkAt: 1 + Math.random() * 3, blinkT: -1,
             lookYaw: 0, lookPitch: 0, phase: Math.random() * 10, step: 0 };
  }

  // -- VOSS: cobalt owl; golden eyes, teal waistcoat, violet cape with a brass clasp, a cyan tablet
  function makeVoss() {
    const A = actorBase("voss", 0.36), B = A.body;
    const COB = 0x3355cc, COB_D = 0x233a94, COB_L = 0x9cc2f4, FACE = 0xc4dcf8, TEAL = 0x1e8078, VIOLET = 0x6b3cb4, VIOLET_D = 0x4a2884, GOLD = 0xf3a51a, TALON = 0xc77d2c, LEATH = 0x6e4428;
    const feet = [-1, 1].map(function (s) {
      const f = new THREE.Group(); f.position.set(s * 0.1, 0, 0.02); B.add(f);
      for (let k = -1; k <= 1; k++) part(f, G.cap(0.02, 0.06, 4, 8), CMAT.leather, TALON, [k * 0.034, 0.02, 0.05], [Math.PI / 2, k * 0.4, 0]);
      part(f, G.cap(0.028, 0.1, 4, 8), CMAT.leather, TALON, [0, 0.08, 0]);
      part(f, G.sph(1, 16, 12), CMAT.owl, COB_D, [0, 0.16, 0], null, [0.075, 0.07, 0.075]);
      return bake(f);
    });
    const torso = new THREE.Group(); torso.position.y = 0.16; B.add(torso);
    part(torso, G.sph(1, 40, 28), CMAT.owl, COB, [0, 0.34, 0], null, [0.3, 0.37, 0.27]);
    part(torso, G.sph(1, 32, 24, Math.PI / 2 - 1.25, 2.5, Math.PI * 0.4, Math.PI * 0.42), CMAT.cloth, TEAL, [0, 0.34, 0], null, [0.312, 0.382, 0.285]);
    part(torso, G.sph(1, 28, 20), CMAT.owl, COB_L, [0, 0.6, 0.12], null, [0.15, 0.11, 0.12]);
    [0.47, 0.39, 0.31].forEach(function (y) { part(torso, G.sph(0.018, 12, 8), CMAT.brass, BRASS, [0, y, 0.283 + (y > 0.45 ? -0.012 : 0)]); });
    part(torso, G.tor(0.275, 0.022, 8, 40), CMAT.leather, LEATH, [0, 0.19, 0], [Math.PI / 2, 0, 0], [1, 0.92, 1]);
    part(torso, G.rbox(0.07, 0.05, 0.02, 0.3, 10), CMAT.brass, BRASS, [0, 0.19, 0.255]);
    part(torso, G.rbox(0.13, 0.11, 0.06, 0.25, 12), CMAT.leather, LEATH, [0.24, 0.15, 0.1], [0, 0.9, 0]);
    part(torso, G.rbox(0.03, 0.03, 0.01, 0.3, 8), CMAT.brass, BRASS, [0.27, 0.17, 0.125], [0, 0.9, 0]);
    const cape = new THREE.Group(); cape.position.set(0, 0.66, -0.02); torso.add(cape);
    part(cape, new THREE.CylinderGeometry(0.21, 0.41, 0.64, 44, 3, true, Math.PI * 0.27, Math.PI * 1.46), CMAT.cape,
      function (x, y) { return _c.set(VIOLET).lerp(col(VIOLET_D), clamp(0.3 - y, 0, 1)); }, [0, -0.31, 0]);
    part(cape, G.tor(0.19, 0.055, 10, 32), CMAT.cape, VIOLET_D, [0, 0.0, 0.0], [Math.PI / 2, 0, 0], [1, 0.85, 1]);
    part(cape, G.cyl(0.042, 0.042, 0.02, 20), CMAT.brass, BRASS, [0, -0.03, 0.2], [Math.PI / 2 - 0.3, 0, 0]);
    part(cape, G.tor(0.045, 0.01, 6, 20), CMAT.brass, BRASS_DARK, [0, -0.03, 0.212], [-0.3, 0, 0]);
    part(cape, G.sph(0.016, 10, 8), CMAT.lens, null, [0, -0.03, 0.215]);
    bake(cape);
    // the tablet in the left wing, glowing cyan (a drawing of a map, no words)
    const tabTex = canvasTex(256, 192, function (ctx, w, h) { ctx.fillStyle = "#0c3a44"; ctx.fillRect(0, 0, w, h); ctx.strokeStyle = "rgba(160,255,250,.5)"; ctx.lineWidth = 1;
      for (let x = 0; x < w; x += 22) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); } for (let y = 0; y < h; y += 22) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
      ctx.strokeStyle = "#b8fff6"; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(30, 150); ctx.lineTo(90, 90); ctx.lineTo(150, 120); ctx.lineTo(220, 40); ctx.stroke();
      [[30, 150], [90, 90], [150, 120], [220, 40]].forEach(function (p) { ctx.beginPath(); ctx.arc(p[0], p[1], 7, 0, TAU); ctx.stroke(); }); });
    const tablet = new THREE.Group(); tablet.position.set(0.09, 0.42, 0.25); tablet.rotation.set(-0.95, -0.3, 0.1); torso.add(tablet);
    part(tablet, G.rbox(0.22, 0.165, 0.014, 0.25, 12), CMAT.brass, BRASS_DARK);
    const tabScreen = new THREE.Mesh(new THREE.PlaneGeometry(0.19, 0.135), new THREE.MeshBasicMaterial({ map: tabTex, color: hdr(0xffffff, 1.9) }));
    tabScreen.position.z = 0.0075; tabScreen.userData.keep = true; tablet.add(tabScreen); bake(tablet);
    const wings = [-1, 1].map(function (s) {
      const w = new THREE.Group(); w.position.set(s * 0.27, 0.6, 0.0); torso.add(w);
      part(w, G.sph(1, 28, 20), CMAT.owl, COB, [s * 0.025, -0.2, -0.01], [0, 0, s * 0.1], [0.075, 0.25, 0.16]);
      part(w, G.sph(1, 20, 14), CMAT.owl, COB_D, [s * 0.045, -0.4, 0.04], [0, 0, s * 0.2], [0.05, 0.08, 0.06]);
      for (let k = 0; k < 3; k++) part(w, G.sph(1, 14, 10), CMAT.owl, COB_D, [s * 0.04, -0.3 - k * 0.04, -0.1 + k * 0.02], [0.3, 0, 0], [0.04, 0.12, 0.05]);
      return bake(w);
    });
    for (let k = -1; k <= 1; k++) part(torso, G.sph(1, 14, 10), CMAT.owl, COB_D, [k * 0.06, 0.06, -0.24], [-0.6, k * 0.3, 0], [0.05, 0.13, 0.03]);
    bake(torso);
    const head = new THREE.Group(); head.position.set(0, 0.8, 0.02); torso.add(head);
    part(head, G.sph(1, 40, 30), CMAT.owl, COB, [0, 0, 0], null, [0.27, 0.235, 0.245]);
    [-1, 1].forEach(function (s) { part(head, G.sph(1, 28, 20), CMAT.owl, FACE, [s * 0.086, 0.005, 0.135], null, [0.125, 0.125, 0.11]); });
    part(head, G.sph(1, 24, 16), CMAT.owl, FACE, [0, -0.07, 0.15], null, [0.15, 0.08, 0.1]);
    [-1, 1].forEach(function (s) { part(head, G.cap(0.02, 0.11, 4, 8), CMAT.owl, COB_D, [s * 0.085, 0.105, 0.205], [0.15, 0, -Math.PI / 2 + 0.32 * s]); });
    part(head, G.cone(0.032, 0.08, 14), CMAT.leather, 0xe6a13a, [0, -0.045, 0.245], [Math.PI / 2 + 0.55, 0, 0]);
    [-1, 1].forEach(function (s) { part(head, G.cone(0.056, 0.16, 14), CMAT.owl, COB_D, [s * 0.155, 0.2, -0.01], [-0.15, 0, -s * 0.55]); });
    A.eyes = makeEyes(head, { r: 0.08, sep: 0.088, y: 0.01, z: 0.168, iris: GOLD, lid: COB, lidMat: CMAT.owl, spread: 0.24, open: -1.05 });
    bake(head);
    A.head.position.set(0, 1.26, 0);
    A.carry.position.set(0, 0.55, 0.32);
    A.headObj = head;
    A.anim = function (t, st, dt) {
      const walk = st.walking, glide = st.glide || 0;
      torso.scale.set(1, 1 + Math.sin(t * 2.1) * 0.012, 1);
      if (walk && glide < 0.5) { A.step += dt * st.speed * 11; const p = A.step;
        feet.forEach(function (f, i) { const q = Math.sin(p + i * Math.PI); f.position.z = 0.02 + q * 0.05; f.position.y = Math.max(0, q) * 0.035; });
        torso.position.y = 0.16 + Math.abs(Math.sin(p)) * 0.022; torso.rotation.z = Math.sin(p) * 0.07;
      } else { feet.forEach(function (f) { f.position.z += (0.02 - f.position.z) * 0.2; f.position.y *= 0.8; }); torso.position.y += (0.16 - torso.position.y) * 0.2; torso.rotation.z *= 0.9; }
      torso.rotation.x = glide * 0.32;
      wings[0].rotation.z = -(0.08 + glide * 1.35) + (st.working ? Math.sin(t * 5) * 0.04 : 0);
      wings[0].rotation.x = st.working ? -0.55 + Math.sin(t * 4.2) * 0.12 : glide * 0.3;
      wings[1].rotation.z = 0.15 + glide * 1.35; wings[1].rotation.x = glide > 0.3 ? glide * 0.3 : -0.75;
      tablet.visible = glide < 0.5;
      cape.rotation.x = -glide * 0.45 + Math.sin(t * (walk ? 7 : 1.3)) * (walk ? 0.04 : 0.015) - (walk ? 0.08 : 0);
      head.rotation.x = (st.working ? 0.22 : 0) + A.lookPitch;
      head.rotation.y = A.lookYaw + Math.sin(t * 0.45) * 0.15;
      head.rotation.z = Math.sin(t * 0.33) * 0.1 + (st.working ? Math.sin(t * 0.8) * 0.05 : 0);
      tabScreen.material.color.copy(hdr(0xffffff, 1.6 + Math.sin(t * 3) * 0.25));
    };
    return A;
  }

  // -- PIP: orange fox; white muzzle, chest and tail tip, brass blue-lens goggles, ivory shirt, brown harness
  function makePip() {
    const A = actorBase("pip", 0.32), B = A.body;
    const OR = 0xec7a2e, OR_D = 0xc95c1a, WH = 0xfbf4ea, DK = 0x2f211a, SHIRT = 0xf3ead8, HAR = 0x6e4a2c, HAR_D = 0x4f3320;
    const legs = [-1, 1].map(function (s) {
      const l = new THREE.Group(); l.position.set(s * 0.075, 0.4, 0); B.add(l);
      part(l, G.cap(0.062, 0.08, 6, 14), CMAT.cloth, HAR, [0, -0.07, 0]);
      part(l, G.cap(0.042, 0.13, 6, 12), CMAT.fox, OR, [0, -0.22, 0]);
      part(l, G.rbox(0.095, 0.085, 0.16, 0.3, 14), CMAT.leather, DK, [0, -0.355, 0.03]);
      return bake(l);
    });
    const torso = new THREE.Group(); torso.position.y = 0.4; B.add(torso);
    part(torso, G.sph(1, 28, 20), CMAT.cloth, HAR, [0, 0.03, 0], null, [0.15, 0.1, 0.125]);
    part(torso, G.cap(0.14, 0.17, 10, 24), CMAT.cloth, SHIRT, [0, 0.22, 0], null, [1, 1, 0.86]);
    part(torso, G.sph(1, 24, 18), CMAT.fox, WH, [0, 0.39, 0.085], null, [0.095, 0.085, 0.06]);
    part(torso, G.rbox(0.19, 0.15, 0.035, 0.3, 14), CMAT.cloth, HAR, [0, 0.13, 0.112]);
    [-1, 1].forEach(function (s) {
      part(torso, G.box(0.032, 0.3, 0.018), CMAT.leather, HAR_D, [s * 0.065, 0.28, 0.118], [0.08, 0, 0]);
      part(torso, G.box(0.032, 0.32, 0.018), CMAT.leather, HAR_D, [s * 0.065, 0.27, -0.118], [-0.08, 0, 0]);
      part(torso, G.rbox(0.035, 0.03, 0.012, 0.3, 8), CMAT.brass, BRASS, [s * 0.065, 0.2, 0.13]);
      part(torso, G.rbox(0.07, 0.08, 0.05, 0.3, 10), CMAT.leather, HAR_D, [s * 0.13, 0.03, 0.07], [0, s * 0.5, 0]);
    });
    part(torso, G.tor(0.152, 0.024, 8, 32), CMAT.leather, HAR_D, [0, 0.07, 0], [Math.PI / 2, 0, 0], [1, 0.85, 1]);
    part(torso, G.rbox(0.045, 0.035, 0.015, 0.3, 8), CMAT.brass, BRASS, [0, 0.07, 0.135]);
    part(torso, G.cyl(0.012, 0.012, 0.12, 6), CMAT.brass, BRASS, [0.14, 0.12, 0.08], [0, 0, 0.2]);
    const arms = [-1, 1].map(function (s) {
      const a = new THREE.Group(); a.position.set(s * 0.165, 0.37, 0); torso.add(a);
      part(a, G.cap(0.046, 0.08, 6, 14), CMAT.cloth, SHIRT, [0, -0.06, 0]);
      part(a, G.tor(0.044, 0.018, 8, 16), CMAT.cloth, SHIRT, [0, -0.125, 0], [Math.PI / 2, 0, 0]);
      part(a, G.cap(0.037, 0.08, 6, 12), CMAT.fox, OR, [0, -0.19, 0]);
      part(a, G.sph(1, 16, 12), CMAT.leather, DK, [0, -0.265, 0.01], null, [0.045, 0.05, 0.045]);
      return bake(a);
    });
    const tail = new THREE.Group(); tail.position.set(0, 0.05, -0.12); torso.add(tail);
    [[0, 0, -0.04, 0.06, OR], [0, 0.03, -0.12, 0.085, OR], [0.015, 0.08, -0.21, 0.105, OR], [0.03, 0.16, -0.27, 0.115, OR], [0.04, 0.26, -0.29, 0.105, WH], [0.04, 0.35, -0.26, 0.08, WH], [0.035, 0.41, -0.22, 0.05, WH]]
      .forEach(function (q) { part(tail, G.sph(q[3], 22, 16), CMAT.fox, q[4], [q[0], q[1], q[2]]); });
    bake(tail); bake(torso);
    const head = new THREE.Group(); head.position.set(0, 0.48, 0.01); torso.add(head);
    part(head, G.sph(1, 36, 28), CMAT.fox, OR, [0, 0.12, 0], null, [0.19, 0.17, 0.17]);
    [-1, 1].forEach(function (s) {
      part(head, G.sph(1, 24, 18), CMAT.fox, WH, [s * 0.1, 0.05, 0.075], null, [0.1, 0.075, 0.08]);
      part(head, G.cone(0.045, 0.12, 10), CMAT.fox, WH, [s * 0.19, 0.035, 0.01], [0, 0, s * (Math.PI / 2 + 0.45)]);
      part(head, G.cap(0.012, 0.05, 4, 8), CMAT.fox, OR_D, [s * 0.075, 0.215, 0.15], [0.3, 0, -Math.PI / 2 - s * 0.25]);
    });
    part(head, G.sph(1, 28, 20), CMAT.fox, WH, [0, 0.055, 0.14], null, [0.08, 0.062, 0.105]);
    part(head, G.sph(1, 16, 12), CMAT.eye, 0x120c0c, [0, 0.08, 0.243], null, [0.026, 0.02, 0.02]);
    smile(head, 0.03, 0.007, 0x2a1414, [0, 0.028, 0.234], true);
    part(head, G.sph(1, 12, 8), CMAT.rubber, 0xe7737e, [0, 0.014, 0.238], null, [0.016, 0.009, 0.008]);
    A.eyes = makeEyes(head, { r: 0.064, sep: 0.078, y: 0.135, z: 0.128, iris: 0x5b3214, lid: OR, lidMat: CMAT.fox, spread: 0.3, open: -1.3 });
    const ears = [-1, 1].map(function (s) {
      const e = new THREE.Group(); e.position.set(s * 0.11, 0.25, -0.01); e.rotation.z = -s * 0.32; head.add(e);
      part(e, G.cone(0.078, 0.21, 16), CMAT.fox, OR, [0, 0.1, 0], null, [1, 1, 0.45]);
      part(e, G.cone(0.05, 0.15, 14), CMAT.fox, WH, [0, 0.085, 0.022], null, [1, 1, 0.3]);
      part(e, G.cone(0.035, 0.07, 12), CMAT.fox, DK, [0, 0.185, 0], null, [1, 1, 0.5]);
      return bake(e);
    });
    part(head, G.tor(0.183, 0.014, 8, 40), CMAT.leather, DK, [0, 0.2, -0.01], [Math.PI / 2 + 0.3, 0, 0]);
    [-1, 1].forEach(function (s) {
      part(head, G.tor(0.05, 0.017, 10, 24), CMAT.brass, BRASS, [s * 0.064, 0.265, 0.12], [-0.75, 0, 0]);
      part(head, G.cyl(0.044, 0.044, 0.02, 24), CMAT.lens, null, [s * 0.064, 0.265, 0.12], [Math.PI / 2 - 0.75, 0, 0]);
    });
    part(head, G.box(0.04, 0.012, 0.012), CMAT.brass, BRASS, [0, 0.27, 0.135], [-0.75, 0, 0]);
    bake(head);
    A.head.position.set(0, 1.36, 0); A.carry.position.set(0, 0.6, 0.28); A.headObj = head;
    A.anim = function (t, st, dt) {
      if (st.walking) { A.step += dt * st.speed * 7.2; const p = A.step;
        legs.forEach(function (l, i) { l.rotation.x = Math.sin(p + i * Math.PI) * 0.62; });
        arms.forEach(function (a, i) { a.rotation.x = -Math.sin(p + i * Math.PI) * 0.5; a.rotation.z = (i ? 1 : -1) * 0.12; });
        B.position.y = Math.abs(Math.sin(p)) * 0.055; torso.rotation.x = 0.1;
        tail.rotation.x = -0.15 + Math.cos(2 * p) * 0.14; tail.rotation.y = Math.sin(p) * 0.4;
      } else {
        legs.forEach(function (l) { l.rotation.x *= 0.85; }); B.position.y *= 0.8; torso.rotation.x *= 0.9;
        arms.forEach(function (a, i) { const s = i ? 1 : -1;
          if (st.working) { a.rotation.x = -1.05 + Math.sin(t * 8.5 + i * 2) * 0.13; a.rotation.z = -s * 0.28; }
          else { a.rotation.x = Math.sin(t * 1.1 + i) * 0.05; a.rotation.z = s * 0.12; } });
        tail.rotation.y = Math.sin(t * 1.6) * 0.3; tail.rotation.x = -0.05 + Math.sin(t * 0.9) * 0.05;
      }
      torso.scale.y = 1 + Math.sin(t * 2.3) * 0.01;
      head.rotation.x = (st.working && !st.walking ? 0.32 : 0) + A.lookPitch;
      head.rotation.y = A.lookYaw + (st.working ? Math.sin(t * 0.7) * 0.12 : Math.sin(t * 0.4) * 0.2);
      head.rotation.z = Math.sin(t * 0.6) * 0.06;
      const tw = Math.max(0, Math.sin(t * 0.37) - 0.92) * 6;
      ears[0].rotation.z = 0.32 + tw * 0.4; ears[1].rotation.z = -0.32 - Math.max(0, Math.sin(t * 0.31 + 2) - 0.92) * 2.4;
    };
    return A;
  }

  // -- NYX: lavender octopus; dark intelligent eyes, a brass optic, eight compact arms (built live each frame)
  function makeNyx() {
    const A = actorBase("nyx", 0.42), B = A.body;
    const LAV = 0xab70e8, LAV_D = 0x8a52cc, SUCK = 0xf5c4ef;
    const mantle = new THREE.Group(); mantle.position.set(0, 0.62, 0); B.add(mantle);
    part(mantle, G.sph(1, 44, 32), CMAT.octo, function (x, y) { return _c.set(LAV).lerp(col(0xc596f5), clamp(y * 1.4, 0, 0.5)); }, [0, 0.06, -0.03], null, [0.37, 0.41, 0.35]);
    part(mantle, G.sph(1, 36, 24), CMAT.octo, LAV, [0, -0.17, 0.03], null, [0.3, 0.2, 0.29]);
    [-1, 1].forEach(function (s) { part(mantle, G.sph(1, 16, 12), CMAT.octo, 0xe58fd2, [s * 0.155, -0.15, 0.276], [0, s * 0.5, 0], [0.045, 0.026, 0.012]); });
    smile(mantle, 0.042, 0.009, 0x34143c, [0, -0.165, 0.318], true);
    A.eyes = makeEyes(mantle, { r: 0.094, sep: 0.13, y: -0.04, z: 0.235, iris: 0x2c2150, lid: LAV, lidMat: CMAT.octo, spread: 0.36, pupil: 1.25, open: -1.32 });
    // the brass optic over its right eye, with a tiny chain
    part(mantle, G.tor(0.112, 0.022, 10, 32), CMAT.brass, BRASS, [-0.13, -0.04, 0.3], [0, -0.36, 0]);
    part(mantle, G.cyl(0.035, 0.03, 0.09, 14), CMAT.brass, BRASS_DARK, [-0.245, -0.03, 0.24], [0, 0, Math.PI / 2]);
    part(mantle, G.sph(0.02, 10, 8), CMAT.brass, COPPER, [-0.29, -0.03, 0.24]);
    for (let k = 0; k < 4; k++) part(mantle, G.tor(0.012, 0.004, 4, 8), CMAT.brass, BRASS, [-0.25 - k * 0.006, -0.08 - k * 0.025, 0.25], [0, k % 2 ? Math.PI / 2 : 0, 0]);
    bake(mantle);
    // eight arms: one geometry rebuilt every frame (cheap: ~1900 vertices), suckers coloured on the curled side
    const NT = 8, SEG = 20, RAD = 10, ring = RAD + 1, per = (SEG + 1) * ring, tg = new THREE.BufferGeometry();
    const pos = new Float32Array(NT * per * 3), nor = new Float32Array(NT * per * 3), colr = new Float32Array(NT * per * 3), uvs = new Float32Array(NT * per * 2), idx = [];
    const cL = col(LAV), cD = col(LAV_D), cS = col(SUCK);
    for (let k = 0; k < NT; k++) for (let i = 0; i <= SEG; i++) for (let j = 0; j <= RAD; j++) {
      const v = k * per + i * ring + j, s = i / SEG, ph = j / RAD * TAU;
      const suck = smoothstep(Math.cos(ph), 0.35, 0.85) * smoothstep(s, 0.18, 0.4) * (0.65 + 0.35 * Math.cos(i * 2.6));
      _c.copy(cL).lerp(cD, s * 0.3).lerp(cS, suck); colr[v * 3] = _c.r; colr[v * 3 + 1] = _c.g; colr[v * 3 + 2] = _c.b;
      uvs[v * 2] = j / RAD * 0.5; uvs[v * 2 + 1] = s * 2 + k * 0.37;
      if (i < SEG && j < RAD) { const a = v, b = v + 1, c = v + ring, d = v + ring + 1; idx.push(a, c, b, b, c, d); }
    }
    tg.setAttribute("position", new THREE.BufferAttribute(pos, 3)); tg.setAttribute("normal", new THREE.BufferAttribute(nor, 3));
    tg.setAttribute("color", new THREE.BufferAttribute(colr, 3)); tg.setAttribute("uv", new THREE.BufferAttribute(uvs, 2)); tg.setIndex(idx);
    tg.boundingSphere = new THREE.Sphere(V3(0, 0.45, 0), 1.4);
    const arms = new THREE.Mesh(tg, CMAT.octo); arms.castShadow = Q.shadows; arms.frustumCulled = false; B.add(arms);
    const stylus = new THREE.Group(); B.add(stylus);
    part(stylus, G.cyl(0.009, 0.006, 0.2, 8), CMAT.brass, BRASS, [0, 0, 0]); part(stylus, G.cone(0.009, 0.03, 8), CMAT.brass, COPPER, [0, -0.115, 0], [Math.PI, 0, 0]); bake(stylus);
    const up = V3(0, 1, 0), o = new THREE.Vector3(), bn = new THREE.Vector3(), P = new THREE.Vector3(), T = new THREE.Vector3(), N = new THREE.Vector3();
    const pose = { lift: 0, seated: 0, typing: 0, crawl: 0 };
    function arm(k, t) {
      const a = k / NT * TAU + Math.PI / 8; o.set(Math.sin(a), 0, Math.cos(a)); bn.crossVectors(up, o).normalize();
      const front = Math.max(0, Math.cos(a)), base = 0.4 + pose.lift;
      P.set(o.x * 0.16, base, o.z * 0.16);
      const wave = Math.sin(t * 6.5 + k * 0.785) * pose.crawl, isType = (k === 0 || k === 7) ? pose.typing : 0, isPen = k === 1 ? Math.max(pose.typing, 0.6 * (1 - pose.crawl)) : 0;
      const th0 = lerp(lerp(-1.32 + wave * 0.35, -1.5 + 0.25 * front, pose.seated), -0.15, isType), th0b = lerp(th0, 0.75, isPen);
      const curl = lerp(lerp(3.3 + wave * 0.6, 2.2, pose.seated), 0.9, isType) * (1 - isPen * 0.45);
      const L = (0.64 + pose.seated * 0.12 + isType * 0.08) / SEG, side = Math.sin(t * 1.3 + k * 1.7) * 0.15 + (isType ? Math.sin(t * 13 + k) * 0.06 : 0);
      for (let i = 0; i <= SEG; i++) {
        const s = i / SEG, th = th0b + curl * s * s + Math.sin(t * 2.1 + k + s * 3) * 0.06, r = 0.074 * (1 - 0.84 * s) + 0.007;
        T.set(Math.cos(th) * o.x + bn.x * side * 0.3, Math.sin(th), Math.cos(th) * o.z + bn.z * side * 0.3).normalize();
        N.set(-Math.sin(th) * o.x, Math.cos(th), -Math.sin(th) * o.z).normalize();
        if (i > 0) { P.addScaledVector(T, L); if (P.y < r + 0.004) P.y = r + 0.004; }
        for (let j = 0; j <= RAD; j++) {
          const ph = j / RAD * TAU, cx = Math.cos(ph), sx = Math.sin(ph), v = (k * per + i * ring + j) * 3;
          const nx = N.x * cx + bn.x * sx, ny = N.y * cx + bn.y * sx, nz = N.z * cx + bn.z * sx;
          pos[v] = P.x + nx * r; pos[v + 1] = P.y + ny * r; pos[v + 2] = P.z + nz * r; nor[v] = nx; nor[v + 1] = ny; nor[v + 2] = nz;
        }
        if (k === 1 && i === SEG) { stylus.position.copy(P); stylus.rotation.set(0.4, 0, -0.3); stylus.visible = isPen > 0.3; }
      }
    }
    A.head.position.set(0, 1.18, 0); A.carry.position.set(0, 0.7, 0.36); A.headObj = mantle;
    A.anim = function (t, st, dt) {
      const k = 1 - Math.exp(-dt * 5);
      pose.seated += ((st.seated ? 1 : 0) - pose.seated) * k; pose.lift = pose.seated * 0.3;
      pose.typing += ((st.working && st.seated ? 1 : 0) - pose.typing) * k; pose.crawl += ((st.walking ? 1 : 0) - pose.crawl) * k;
      mantle.position.y = 0.62 + pose.lift + Math.sin(t * (st.walking ? 6.5 : 1.7)) * (st.walking ? 0.025 : 0.012);
      mantle.scale.set(1 + Math.sin(t * 1.7) * 0.012, 1 - Math.sin(t * 1.7) * 0.012, 1);
      mantle.rotation.x = A.lookPitch + (st.walking ? 0.12 : 0) + pose.typing * 0.12;
      mantle.rotation.y = A.lookYaw + Math.sin(t * 0.5) * 0.12;
      mantle.rotation.z = Math.sin(t * 0.8) * 0.04;
      for (let i = 0; i < NT; i++) arm(i, t);
      tg.attributes.position.needsUpdate = true; tg.attributes.normal.needsUpdate = true;
    };
    return A;
  }

  // -- ROOK: chunky slate golem (twice everyone's height); amber eyes and fissures, a broad brass collar
  function makeRook() {
    const A = actorBase("rook", 0.75), B = A.body;
    const SL = [0x857a70, 0x786e66, 0x8f847a, 0x6f665f], LEATH = 0x5e3a22;
    let seed = 1;
    const chunk = function (g, r, p, s, rot) { const c = SL[seed % 4]; part(g, crag(r, 1, seed++, 1), CMAT.rock, function () { return _c.set(c); }, p, rot || [seed * 0.7, seed * 1.3, seed * 0.4], s); };
    const glowLine = function (g, p, r, l) { part(g, G.box(0.025, l, 0.025), CMAT.magma, null, p, r); };
    const legs = [-1, 1].map(function (s) {
      const l = new THREE.Group(); l.position.set(s * 0.25, 0.8, 0); B.add(l);
      part(l, G.sph(0.14, 12, 8), CMAT.magma, null, [0, -0.33, 0]);
      chunk(l, 0.21, [0, -0.17, 0], [1, 1.2, 1]); chunk(l, 0.22, [0, -0.5, 0.02], [1.05, 1.1, 1.05]); chunk(l, 0.2, [0, -0.7, 0.09], [1.25, 0.6, 1.45]);
      return bake(l);
    });
    const torso = new THREE.Group(); torso.position.y = 0.8; B.add(torso);
    part(torso, G.sph(1, 20, 14), CMAT.magma, null, [0, 0.62, 0], null, [0.42, 0.55, 0.34]);
    chunk(torso, 0.3, [0, 0.12, 0], [1.3, 0.8, 1.05]); chunk(torso, 0.32, [0, 0.44, 0.06], [1.15, 0.95, 1]);
    chunk(torso, 0.42, [0, 0.86, 0.0], [1.28, 1.0, 0.95]); chunk(torso, 0.27, [-0.2, 0.92, 0.24]); chunk(torso, 0.27, [0.21, 0.9, 0.24]);
    chunk(torso, 0.37, [0, 0.98, -0.22], [1.2, 1, 0.9]); chunk(torso, 0.3, [-0.5, 1.06, 0]); chunk(torso, 0.3, [0.5, 1.06, 0]);
    const rr = rng(77);
    for (let i = 0; i < 12; i++) { const a = rr() * TAU, y = 0.2 + rr() * 0.9; chunk(torso, 0.1 + rr() * 0.09, [Math.cos(a) * (0.36 + rr() * 0.08), y, Math.sin(a) * 0.32]); }
    [[0.12, 0.6, 0.36, 0.5], [-0.15, 0.32, 0.33, -0.4], [0.33, 0.95, 0.28, 0.9], [-0.36, 0.75, 0.25, -0.2], [0.05, 0.25, 0.32, 0.1], [-0.05, 1.05, 0.36, 1.2]].forEach(function (q) {
      glowLine(torso, [q[0], q[1], q[2]], [0.2, 0, q[3]], 0.16); });
    part(torso, G.tor(0.36, 0.075, 12, 40), CMAT.brass, BRASS, [0, 1.2, 0.08], [Math.PI / 2 + 0.3, 0, 0], [1.05, 1, 1]);
    for (let k = 0; k < 5; k++) { const a = -Math.PI / 2 + (k - 2) * 0.45; part(torso, G.cyl(0.03, 0.03, 0.03, 5), CMAT.brass, BRASS_DARK, [Math.cos(a) * 0.37, 1.17 - Math.abs(k - 2) * 0.02, 0.08 - Math.sin(a) * 0.37 * 0.95], [Math.PI / 2 - 0.3, 0, 0]); }
    [-1, 1].forEach(function (s) { part(torso, G.box(0.09, 1.0, 0.035), CMAT.leather, LEATH, [s * 0.02, 0.7, 0.39], [-0.12, 0, s * 0.5]);
      part(torso, G.rbox(0.09, 0.07, 0.03, 0.3, 10), CMAT.brass, BRASS, [s * 0.16, 0.95, 0.4], [-0.1, 0, s * 0.5]); });
    part(torso, G.rbox(0.12, 0.12, 0.04, 0.3, 10), CMAT.brass, BRASS, [0, 0.66, 0.42], [-0.12, 0, 0]);
    part(torso, G.rbox(0.24, 0.2, 0.12, 0.2, 12), CMAT.leather, LEATH, [0.36, 0.18, 0.2], [0, 0.5, 0]);
    bake(torso);
    const head = new THREE.Group(); head.position.set(0, 1.3, 0.18); torso.add(head);
    chunk(head, 0.22, [0, 0.05, 0], [1.1, 0.95, 1]); chunk(head, 0.14, [0, 0.13, 0.13], [1.9, 0.5, 0.8]); chunk(head, 0.16, [0, -0.08, 0.07], [1.25, 0.6, 1]);
    chunk(head, 0.12, [0.06, 0.21, -0.05]);
    part(head, G.box(0.1, 0.012, 0.02), CMAT.rubber, 0x2a1d18, [0, -0.07, 0.235]);
    const eyeGlow = new THREE.MeshBasicMaterial({ color: hdr(0xffb23c, 6) });
    const eyes = [-1, 1].map(function (s) { const e = new THREE.Group(); e.position.set(s * 0.075, 0.055, 0.2); head.add(e);
      part(e, G.sph(1, 16, 12), eyeGlow, null, [0, 0, 0], null, [0.04, 0.026, 0.02]); return e; });
    bake(head);
    const stamp = new THREE.Group(); stamp.visible = false; scene.add(stamp);
    part(stamp, G.cyl(0.05, 0.06, 0.08, 16), CMAT.brass, BRASS_DARK, [0, 0, 0]); part(stamp, G.sph(0.045, 14, 10), CMAT.brass, BRASS, [0, 0.12, 0]);
    part(stamp, G.cyl(0.02, 0.02, 0.1, 8), CMAT.brass, BRASS, [0, 0.06, 0]); bake(stamp);
    const arms = [-1, 1].map(function (s) {
      const a = new THREE.Group(); a.position.set(s * 0.58, 1.02, 0); torso.add(a);
      part(a, G.sph(0.1, 10, 8), CMAT.magma, null, [0, -0.33, 0]);
      chunk(a, 0.2, [0, -0.15, 0], [1, 1.3, 1]); chunk(a, 0.24, [0, -0.5, 0.03], [1.05, 1.35, 1.05]);
      chunk(a, 0.15, [0, -0.83, 0.06]); chunk(a, 0.12, [s * 0.07, -0.8, 0.13]); chunk(a, 0.11, [-s * 0.06, -0.86, 0.12]);
      const fist = new THREE.Object3D(); fist.position.set(0, -0.86, 0.12); a.add(fist); a.userData.fist = fist;
      return bake(a);
    });
    A.head.position.set(0, 2.45, 0); A.carry.position.set(0, 1.1, 0.5); A.headObj = head;
    A.eyesGlow = eyes;
    const _w = new THREE.Vector3();
    A.anim = function (t, st, dt) {
      const k = 1 - Math.exp(-dt * 4), seat = st.seated ? 1 : 0;
      A.seat = (A.seat || 0) + (seat - (A.seat || 0)) * k;
      if (st.walking) { A.step += dt * st.speed * 4.4; const p = A.step;
        legs.forEach(function (l, i) { l.rotation.x = Math.sin(p + i * Math.PI) * 0.38; });
        arms.forEach(function (a, i) { a.rotation.x = -Math.sin(p + i * Math.PI) * 0.32; a.rotation.z = 0; });
        torso.rotation.z = Math.sin(p) * 0.07; B.position.y = -Math.pow(Math.abs(Math.cos(p)), 6) * 0.05;
        const impact = Math.pow(Math.abs(Math.cos(p)), 30); A.impact = impact;
      } else {
        A.impact = 0; torso.rotation.z *= 0.9;
        legs.forEach(function (l) { l.rotation.x += (-1.45 * A.seat - l.rotation.x) * k; });
        B.position.y += (-0.02 * A.seat - B.position.y) * k;
        arms.forEach(function (a, i) {
          let goal = -0.08 + Math.sin(t * 0.9 + i) * 0.03;
          if (A.seat > 0.5) goal = -0.5;
          if (st.working && A.seat > 0.5 && i === 0) { const u = (t % 4.2) / 4.2; goal = u < 0.55 ? -0.5 - smoothstep(u, 0, 0.5) * 0.75 : u < 0.62 ? -1.25 + smoothstep(u, 0.55, 0.62) * 0.8 : -0.45; }
          a.rotation.x += (goal - a.rotation.x) * Math.min(1, dt * 9); a.rotation.z = (i ? 1 : -1) * 0.06;
        });
      }
      torso.rotation.x = A.seat * 0.1 + Math.sin(t * 0.8) * 0.015;
      head.rotation.y = A.lookYaw + Math.sin(t * 0.3) * 0.15; head.rotation.x = A.lookPitch + (st.working ? 0.2 : 0);
      stamp.visible = A.seat > 0.5 && !st.walking;
      if (stamp.visible) { arms[0].userData.fist.getWorldPosition(_w); stamp.position.set(_w.x, _w.y - 0.08, _w.z); stamp.rotation.y = A.group.rotation.y; }
    };
    A.blink = function (v) { eyes.forEach(function (e) { e.scale.y = Math.max(0.08, 1 - v); }); };
    return A;
  }

  // -- MOTE: a small translucent mint creature in a clear glass travel bell on a brass wheeled cart
  function makeMote() {
    const A = actorBase("mote", 0.42), B = A.body;
    const cart = new THREE.Group(); B.add(cart);
    part(cart, G.rbox(0.64, 0.07, 0.46, 0.25, 18), CMAT.brass, BRASS, [0, 0.3, 0]);
    part(cart, G.rbox(0.54, 0.025, 0.37, 0.3, 14), CMAT.leather, WALNUT, [0, 0.338, 0]);
    part(cart, G.rbox(0.56, 0.1, 0.38, 0.2, 14), CMAT.leather, WALNUT_DARK, [0, 0.22, 0]);
    part(cart, G.rbox(0.16, 0.06, 0.012, 0.3, 8), CMAT.leather, WALNUT, [0, 0.22, 0.192]); part(cart, G.sph(0.012, 8, 6), CMAT.brass, BRASS, [0, 0.22, 0.2]);
    [[1, 1], [1, -1], [-1, 1], [-1, -1]].forEach(function (q) { part(cart, G.cyl(0.012, 0.012, 0.16, 8), CMAT.brass, BRASS, [q[0] * 0.3, 0.39, q[1] * 0.21]);
      part(cart, G.sph(0.022, 10, 8), CMAT.brass, BRASS, [q[0] * 0.3, 0.475, q[1] * 0.21]); });
    part(cart, G.tor(0.3, 0.012, 6, 36), CMAT.brass, BRASS_DARK, [0, 0.46, 0], [Math.PI / 2, 0, 0], [1.05, 0.73, 1]);
    // the bell: clear glass, a brass base ring, the hatch, a loop on top
    const prof = [[0.29, 0], [0.295, 0.03], [0.29, 0.38], [0.275, 0.47], [0.245, 0.55], [0.195, 0.615], [0.13, 0.66], [0.06, 0.683], [0.001, 0.69]];
    part(cart, new THREE.LatheGeometry(prof.map(function (q) { return new THREE.Vector2(q[0], q[1]); }), 48), MAT.glass, null, [0, 0.338, 0]);
    part(cart, G.tor(0.296, 0.024, 10, 48), CMAT.brass, BRASS, [0, 0.35, 0], [Math.PI / 2, 0, 0]);
    part(cart, G.sph(0.04, 14, 10), CMAT.brass, BRASS, [0, 1.03, 0]); part(cart, G.tor(0.04, 0.011, 8, 20), CMAT.brass, BRASS, [0, 1.085, 0]);
    part(cart, G.tor(0.07, 0.013, 8, 24), CMAT.brass, BRASS, [0.2, 0.62, 0.2], [0, Math.PI / 4, 0]);
    // inside: a tiny lectern with an open book, a tiny mint screen of linked cards
    part(cart, G.box(0.1, 0.11, 0.07), CMAT.leather, WALNUT, [-0.14, 0.4, 0.09]);
    part(cart, G.box(0.075, 0.006, 0.09), CMAT.cloth, PAPER, [-0.17, 0.46, 0.09], [0, 0, 0.2]); part(cart, G.box(0.075, 0.006, 0.09), CMAT.cloth, PAPER, [-0.11, 0.46, 0.09], [0, 0, -0.2]);
    part(cart, G.cyl(0.006, 0.006, 0.14, 6), CMAT.brass, BRASS, [0.04, 0.41, -0.2]);
    const scr = part(cart, G.box(0.16, 0.1, 0.006), CMAT.hi, null, [0.04, 0.5, -0.2], [0.1, 0, 0]); scr.material = new THREE.MeshBasicMaterial({ color: hdr(0x63ffcc, 1.4) }); scr.userData.keep = true;
    bake(cart);
    const wheels = [[0.335, 0.17, 0.125], [-0.335, 0.17, 0.125], [0.335, -0.17, 0.15], [-0.335, -0.17, 0.15]].map(function (q) {
      const w = new THREE.Group(); w.position.set(q[0], q[2], q[1]); B.add(w);
      const sp = new THREE.Group(); w.add(sp);
      part(sp, G.tor(q[2], 0.016, 8, 32), CMAT.brass, BRASS_DARK, [0, 0, 0], [0, Math.PI / 2, 0]);
      part(sp, G.tor(q[2] + 0.004, 0.01, 6, 32), CMAT.rubber, 0x2a2228, [0, 0, 0], [0, Math.PI / 2, 0]);
      part(sp, G.cyl(0.022, 0.022, 0.05, 12), CMAT.brass, BRASS, [0, 0, 0], [0, 0, Math.PI / 2]);
      for (let k = 0; k < 8; k++) part(sp, G.box(0.008, q[2] * 2, 0.008), CMAT.brass, BRASS, [0, 0, 0], [k * Math.PI / 8, 0, 0]);
      bake(sp); return { g: sp, r: q[2] };
    });
    const ghost = new THREE.Group(); ghost.position.set(0, 0.38, 0); B.add(ghost);
    part(ghost, G.sph(1, 36, 28), CMAT.ghost, null, [0, 0.21, 0], null, [0.14, 0.165, 0.13]);
    part(ghost, G.sph(1, 28, 20), CMAT.ghost, null, [0, 0.08, -0.015], null, [0.11, 0.1, 0.1]);
    part(ghost, taper([V3(0, 0.05, -0.06), V3(0.05, 0.0, -0.12), V3(0.12, 0.03, -0.13), V3(0.14, 0.09, -0.08), V3(0.1, 0.11, -0.04)], 0.06, 0.012, 10), CMAT.ghost, null);
    A.eyes = makeEyes(ghost, { r: 0.03, sep: 0.05, y: 0.25, z: 0.117, iris: 0x060608, bead: true, spread: 0.3 });
    smile(ghost, 0.022, 0.005, 0x1b3a30, [0, 0.205, 0.128], true);
    const garms = [-1, 1].map(function (s) { const a = new THREE.Group(); a.position.set(s * 0.12, 0.2, 0.03); ghost.add(a);
      part(a, G.cap(0.026, 0.05, 6, 10), CMAT.ghost, null, [s * 0.03, 0.02, 0], [0, 0, -s * 0.9]); return bake(a); });
    bake(ghost);
    A.head.position.set(0, 1.2, 0); A.carry.position.set(0.25, 0.65, 0.3); A.headObj = ghost;
    let lastPos = null, lag = new THREE.Vector3();
    A.anim = function (t, st, dt) {
      if (!lastPos) lastPos = A.group.position.clone();
      const moved = A.group.position.distanceTo(lastPos); lastPos.copy(A.group.position);
      wheels.forEach(function (w) { w.g.rotation.x += moved / w.r; });
      const want = st.walking ? 1 : 0; lag.x += (want * 0.04 - lag.x) * Math.min(1, dt * 3);
      ghost.position.y = 0.38 + Math.sin(t * 2.0) * 0.022; ghost.position.z = -lag.x * 0.6; ghost.rotation.x = -lag.x * 2.5;
      ghost.rotation.y = A.lookYaw + Math.sin(t * 0.6) * 0.25; ghost.rotation.z = Math.sin(t * 1.1) * 0.06;
      garms.forEach(function (a, i) { const s = i ? 1 : -1;
        a.rotation.z = st.working ? -s * (0.2 + Math.sin(t * 3 + i) * 0.15) : s * (Math.sin(t * 2.4 + i * 1.3) * 0.35 + (st.walking ? 0.5 : 0));
        a.rotation.x = st.working ? -0.7 : 0; });
      B.rotation.x = -lag.x * 0.4;
      scr.material.color.copy(hdr(0x63ffcc, 1.3 + Math.sin(t * 2.2) * 0.2));
    };
    A.blink = function (v) { A.eyes.forEach(function (e) { e.g.scale.y = Math.max(0.1, 1 - v); }); };
    return A;
  }

  // -- JET: yellow capsule robot; black visor, cyan eyes, short dark limbs, yellow boots, a messenger satchel
  function makeJet() {
    const A = actorBase("jet", 0.3), B = A.body;
    const YEL = 0xf7bb2c, YEL_D = 0xdc9d1b, DKL = 0x2c2e35, SOLE = 0x1c1d22, BAG = 0x7e4c2a;
    const legs = [-1, 1].map(function (s) {
      const l = new THREE.Group(); l.position.set(s * 0.08, 0.25, 0); B.add(l);
      part(l, G.sph(0.042, 14, 10), CMAT.rubber, DKL, [0, 0, 0]);
      part(l, G.cap(0.034, 0.07, 6, 10), CMAT.rubber, DKL, [0, -0.08, 0]);
      part(l, G.rbox(0.115, 0.1, 0.165, 0.3, 16), CMAT.glossy, YEL, [0, -0.175, 0.03]);
      part(l, G.rbox(0.12, 0.03, 0.17, 0.3, 14), CMAT.rubber, SOLE, [0, -0.225, 0.03]);
      return bake(l);
    });
    const torso = new THREE.Group(); torso.position.y = 0.25; B.add(torso);
    part(torso, G.cap(0.15, 0.1, 10, 24), CMAT.glossy, YEL, [0, 0.13, 0], null, [1, 1, 0.86]);
    part(torso, G.tor(0.13, 0.02, 8, 28), CMAT.rubber, DKL, [0, 0.02, 0], [Math.PI / 2, 0, 0], [1, 0.86, 1]);
    part(torso, G.rbox(0.12, 0.085, 0.025, 0.3, 12), CMAT.rubber, DKL, [0, 0.16, 0.125]);
    part(torso, G.sph(0.014, 10, 8), CMAT.hi, null, [0.03, 0.17, 0.14]);
    part(torso, G.tor(0.17, 0.012, 6, 36).scale(1, 0.85, 1).rotateX(Math.PI / 2).rotateZ(0.7), CMAT.leather, BAG, [0, 0.16, 0]);
    part(torso, G.rbox(0.17, 0.14, 0.07, 0.22, 14), CMAT.leather, BAG, [0.17, 0.0, 0.06], [0, 0.55, 0]);
    part(torso, G.rbox(0.17, 0.07, 0.075, 0.22, 12), CMAT.leather, 0x6a3e22, [0.17, 0.045, 0.065], [0, 0.55, 0]);
    part(torso, G.rbox(0.03, 0.03, 0.012, 0.3, 8), CMAT.brass, BRASS, [0.2, 0.03, 0.105], [0, 0.55, 0]);
    part(torso, G.cyl(0.055, 0.06, 0.06, 16), CMAT.rubber, DKL, [0, 0.33, 0]);
    const arms = [-1, 1].map(function (s) {
      const a = new THREE.Group(); a.position.set(s * 0.17, 0.24, 0); torso.add(a);
      part(a, G.sph(0.045, 14, 10), CMAT.rubber, DKL, [0, 0, 0]);
      part(a, G.cap(0.03, 0.06, 6, 10), CMAT.rubber, DKL, [0, -0.06, 0]);
      part(a, G.sph(0.034, 12, 8), CMAT.rubber, DKL, [0, -0.115, 0]);
      part(a, G.cap(0.04, 0.06, 6, 12), CMAT.glossy, YEL, [0, -0.175, 0]);
      part(a, G.sph(1, 14, 10), CMAT.rubber, DKL, [0, -0.245, 0.01], null, [0.046, 0.05, 0.042]);
      return bake(a);
    });
    bake(torso);
    const head = new THREE.Group(); head.position.set(0, 0.47, 0); torso.add(head);
    part(head, G.sph(1, 44, 32), CMAT.glossy, YEL, [0, 0, 0], null, [0.25, 0.235, 0.23]);
    const visor = part(head, G.sph(1, 40, 28), CMAT.visor, null, [0, -0.008, 0.155], null, [0.19, 0.142, 0.1]); visor.userData.keep = true;
    [-1, 1].forEach(function (s) {
      part(head, G.cyl(0.072, 0.072, 0.06, 28), CMAT.glossy, YEL_D, [s * 0.245, 0, 0], [0, 0, Math.PI / 2]);
      part(head, G.tor(0.046, 0.012, 8, 24), CMAT.brass, BRASS, [s * 0.278, 0, 0], [0, Math.PI / 2, 0]);
      part(head, G.cyl(0.03, 0.03, 0.02, 16), CMAT.rubber, DKL, [s * 0.278, 0, 0], [0, 0, Math.PI / 2]);
    });
    bake(head);
    const eyeMat = new THREE.MeshBasicMaterial({ color: hdr(0x5cf4ff, 3.6) });
    const eyes = [-1, 1].map(function (s) { const e = new THREE.Group(); e.position.set(s * 0.062, 0.0, 0.252); e.rotation.y = s * 0.3; head.add(e);
      part(e, G.sph(1, 16, 12), eyeMat, null, [0, 0, 0], null, [0.03, 0.044, 0.012]); return e; });
    A.head.position.set(0, 1.08, 0); A.carry.position.set(0, 0.47, 0.25); A.headObj = head;
    A.anim = function (t, st, dt) {
      if (st.walking) { A.step += dt * st.speed * 12; const p = A.step;
        legs.forEach(function (l, i) { l.rotation.x = Math.sin(p + i * Math.PI) * 0.62; });
        B.position.y = Math.abs(Math.sin(p)) * 0.03; torso.rotation.x = 0.08; torso.rotation.y = Math.sin(p) * 0.08;
      } else { legs.forEach(function (l) { l.rotation.x *= 0.8; }); B.position.y *= 0.8; torso.rotation.x *= 0.9; torso.rotation.y *= 0.9; }
      arms.forEach(function (a, i) { const s = i ? 1 : -1;
        if (st.carrying) { a.rotation.x = -1.2; a.rotation.z = -s * 0.32; }
        else if (st.walking) { a.rotation.x = -Math.sin(A.step + i * Math.PI) * 0.7; a.rotation.z = s * 0.1; }
        else if (st.working && i === 0) { a.rotation.x = -0.9 + Math.max(0, Math.sin(t * 5)) * 0.25; a.rotation.z = 0.1; }
        else { a.rotation.x = Math.sin(t * 1.2 + i) * 0.05; a.rotation.z = s * 0.1; } });
      head.rotation.y = A.lookYaw + Math.sin(t * 0.7) * 0.18; head.rotation.x = A.lookPitch; head.rotation.z = Math.sin(t * 0.9) * 0.05;
      eyeMat.color.copy(hdr(0x5cf4ff, 3.3 + Math.sin(t * 2.5) * 0.4));
    };
    A.blink = function (v) { eyes.forEach(function (e) { e.scale.y = Math.max(0.08, 1 - v); }); };
    return A;
  }

  // -- Mote's clear glass travel bell (for the real model on its brass cart): a lathe bell of clear glass with a
  //    clearcoat and a faint mint rim (a fresnel glow, no transmission pass), a brass base ring, a knob and a loop
  const bellMat = new THREE.MeshPhysicalMaterial({ color: 0xf4fffb, roughness: 0.03, metalness: 0, transparent: true, opacity: 0.1,
    clearcoat: 1, clearcoatRoughness: 0.02, envMapIntensity: 2.4, depthWrite: false, side: THREE.DoubleSide, specularIntensity: 1 });
  bellMat.onBeforeCompile = function (sh) {
    sh.fragmentShader = sh.fragmentShader.replace("#include <emissivemap_fragment>", [
      "#include <emissivemap_fragment>",
      "float rimF = pow(1.0 - abs(dot(normal, normalize(vViewPosition))), 2.6);",
      "totalEmissiveRadiance += vec3(0.32, 0.95, 0.72) * rimF * 0.55;",
      "diffuseColor.a = clamp(diffuseColor.a + rimF * 0.42, 0.0, 1.0);"].join("\n"));
  };
  function makeBell(radius, height) {
    const g = new THREE.Group(); g.name = "bell";
    const prof = [[1.0, 0], [1.02, 0.04], [1.0, 0.55], [0.95, 0.68], [0.85, 0.8], [0.68, 0.9], [0.46, 0.965], [0.22, 0.995], [0.001, 1.0]];
    const glass = new THREE.Mesh(new THREE.LatheGeometry(prof.map(function (q) { return new THREE.Vector2(q[0] * radius, q[1] * height); }), 48), bellMat);
    glass.renderOrder = 6; g.add(glass);
    const brass = function (geo, p, r) { const m = new THREE.Mesh(paint(geo, BRASS), MAT.brass); m.position.set(p[0], p[1], p[2]); if (r) m.rotation.set(r[0], r[1], r[2]); m.castShadow = Q.shadows; g.add(m); return m; };
    brass(G.tor(radius * 1.02, radius * 0.075, 10, 48), [0, radius * 0.06, 0], [Math.PI / 2, 0, 0]);
    brass(G.tor(radius * 1.0, radius * 0.03, 6, 48), [0, height * 0.55, 0], [Math.PI / 2, 0, 0]).material = MAT.brass;
    brass(G.sph(radius * 0.13, 14, 10), [0, height + radius * 0.08, 0]);
    brass(G.tor(radius * 0.12, radius * 0.035, 8, 20), [0, height + radius * 0.27, 0]);
    return g;
  }
"""

_M_LIFE = r"""
  // ============================================================= WHERE EVERYONE STANDS, AND THE PATHS BETWEEN
  const WS2 = RF.workshop, DN2 = RF.den, AR2 = RF.archive, VT2 = RF.vault, OB2 = RF.observatory;
  const NAV = {};
  function node(id, p) { NAV[id] = { id: id, p: p, edges: [] }; }
  function link(a, b) { NAV[a].edges.push(b); NAV[b].edges.push(a); }
  for (let k = 0; k < 8; k++) node("r" + k, V3(Math.cos(k * Math.PI / 4) * 3.05, 0, Math.sin(k * Math.PI / 4) * 3.05));
  for (let k = 0; k < 8; k++) link("r" + k, "r" + ((k + 1) % 8));
  [[200, ["r4", "r5"]], [340, ["r7", "r0"]], [135, ["r3"]], [45, ["r1"]], [90, ["r2"]], [270, ["r6"]]].forEach(function (q) {
    const a = q[0] * Math.PI / 180; node("e" + q[0], V3(Math.cos(a) * 5.6, 0, Math.sin(a) * 5.6)); q[1].forEach(function (r) { link("e" + q[0], r); }); });
  // round the mission table: Voss's place on its left (seen from the bridge) and two places for visitors, kept just
  // clear of whichever table stands there (the procedural one, then the hero prop): see tableSpots()
  node("tbH", V3(0, 0, 0)); link("tbH", "r2"); link("tbH", "r3"); link("tbH", "r4");
  node("tbW", V3(0, 0, 0)); link("tbW", "r0"); link("tbW", "r1"); link("tbW", "r7");
  node("tbN", V3(0, 0, 0)); link("tbN", "r6"); link("tbN", "r7"); link("tbN", "r5");
  node("wsD", WS2.at(0, 0, 4.1)); node("wsI", WS2.at(0, 0, 2.2)); node("wsS", WS2.at(1.8, 0, 0.25)); node("wsB", WS2.at(1.65, 0, -1.45));
  node("wsH", WS2.at(0, 0, -1.3)); node("wsV", WS2.at(1.45, 0, 0.95));
  link("e200", "wsD"); link("wsD", "wsI"); link("wsI", "wsS"); link("wsS", "wsB"); link("wsB", "wsH"); link("wsI", "wsV"); link("wsV", "wsS");
  node("dnD", DN2.at(0, 0, 4.1)); node("dnI", DN2.at(0, 0, 2.0)); node("dnH", DN2.at(0, 0, -1.15)); node("dnV", DN2.at(-1.6, 0, -1.0));
  node("dnSi", DN2.at(2.6, 0, 0.5)); node("dnSo", DN2.at(4.6, 0, 0.5));
  link("e340", "dnD"); link("dnD", "dnI"); link("dnI", "dnH"); link("dnI", "dnV"); link("dnI", "dnSi"); link("dnSi", "dnSo");
  node("arD", AR2.at(0, 0, 3.75)); node("arI", AR2.at(0, 0, 1.6)); node("arH", AR2.at(-1.4, 0, -1.55)); node("arV", AR2.at(0.95, 0, 0.55));
  link("e135", "arD"); link("arD", "arI"); link("arI", "arH"); link("arI", "arV");
  node("vtD", VT2.at(0, 0, 3.75)); node("vtI", VT2.at(0, 0, 1.75)); node("vtS", VT2.at(-1.95, 0, 0.6)); node("vtB", VT2.at(-1.95, 0, -1.8)); node("vtH", VT2.at(0.2, 0, -1.55));
  node("vtX", VT2.at(-4.35, 0, -0.2));
  link("e45", "vtD"); link("vtD", "vtI"); link("vtI", "vtS"); link("vtS", "vtB"); link("vtB", "vtH");
  node("wk6", V3(19.5, 0, 6.3)); node("wkN", V3(19.5, 0, -1.5)); node("wkS", V3(19.5, 0, 16.2));
  node("kiV", V3(22.0, 0, 5.1)); node("dkV", V3(21.6, 0, -1.1)); node("dkH", V3(23.05, 0, -1.45));
  link("dnSo", "vtX"); link("vtX", "wk6"); link("wk6", "wkN"); link("wk6", "wkS"); link("wk6", "kiV"); link("wkN", "dkV"); link("dkV", "dkH");
  node("br", V3(0, 0, 11)); node("pr0", V3(0, 0, 16.2)); link("e90", "br"); link("br", "pr0"); link("pr0", "wkS");
  node("stB", V3(0, 0, -6.0)); node("stT", V3(0, 1.8, -8.95)); node("obC", OB2.at(0, 0, 2.6)); node("obH", OB2.at(-1.0, 0, -1.9)); node("obV", OB2.at(-1.75, 0, 0.7));
  link("e270", "stB"); link("stB", "stT"); link("stT", "obC"); link("obC", "obH"); link("obC", "obV");
  // room -> where its resident works (home) and where a visitor stands
  const SPOTS = {
    table: { home: "tbH", homeYaw: 0, visit: ["tbW", "tbN"], visitYaw: [0, 0] },
    workshop: { home: "wsH", homeYaw: WS2.yaw, visit: ["wsV"], visitYaw: [WS2.yaw + Math.PI + 0.5] },
    den: { home: "dnH", homeYaw: DN2.yaw + Math.PI, visit: ["dnV"], visitYaw: [DN2.yaw + Math.PI / 2] },
    archive: { home: "arH", homeYaw: AR2.yaw + 0.3, visit: ["arV"], visitYaw: [AR2.yaw - 2.0] },
    vault: { home: "vtH", homeYaw: VT2.yaw, visit: ["vtX"], visitYaw: [VT2.yaw + Math.PI / 2] },
    dock: { home: "dkH", homeYaw: -0.95, visit: ["dkV"], visitYaw: [Math.PI / 2] },
    observatory: { home: "obH", homeYaw: OB2.yaw + Math.PI + 0.6, visit: ["obV"], visitYaw: [OB2.yaw + Math.PI - 0.3] },
    kiosk: { home: "kiV", homeYaw: Math.PI / 2, visit: ["kiV"], visitYaw: [Math.PI / 2] },
  };
  // the table's places for a table of radius R with its top at y (the procedural one, then the hero prop): Voss on
  // the left turned three-quarters to the bridge, the visitors facing the middle; TABLE_PT is the rim he reaches for
  const TABLE_PT = V3(0, 0.8, 0);
  function tableSpots(R, top) {
    const at = function (deg, d, out) { const a = deg * Math.PI / 180; return out.set(Math.cos(a) * d, 0, Math.sin(a) * d); };
    at(170, R + 0.45, NAV.tbH.p); at(18, R + 0.52, NAV.tbW.p); at(-62, R + 0.52, NAV.tbN.p);
    const face = function (p) { return Math.atan2(-p.x, -p.z); };
    SPOTS.table.homeYaw = 0.8; SPOTS.table.visitYaw[0] = face(NAV.tbW.p); SPOTS.table.visitYaw[1] = face(NAV.tbN.p);
    at(170, R * 0.82, TABLE_PT).setY(top);
  }
  tableSpots(1.72, 0.8);
  function route(from, to) {
    const dist = {}, prev = {}, todo = new Set(Object.keys(NAV));
    Object.keys(NAV).forEach(function (k) { dist[k] = Infinity; }); dist[from] = 0;
    while (todo.size) {
      let u = null; todo.forEach(function (k) { if (u === null || dist[k] < dist[u]) u = k; });
      if (u === null || dist[u] === Infinity || u === to) break; todo.delete(u);
      NAV[u].edges.forEach(function (v) { const d = dist[u] + NAV[u].p.distanceTo(NAV[v].p); if (d < dist[v]) { dist[v] = d; prev[v] = u; } });
    }
    if (dist[to] === Infinity) return null;
    const out = [to]; while (out[0] !== from) out.unshift(prev[out[0]]); return out;
  }

  // ============================================================= THE ACTORS
  const BUILD = { voss: makeVoss, pip: makePip, nyx: makeNyx, rook: makeRook, mote: makeMote, jet: makeJet };
  const SPEED = { voss: 1.0, pip: 1.45, nyx: 1.05, rook: 0.95, mote: 1.15, jet: 1.8 };
  const HEIGHT = { voss: 1.22, pip: 1.34, nyx: 1.08, rook: 2.37, mote: 1.1, jet: 0.96 };
  const actors = {}, ACTOR_KEYS = [];
  Object.keys(CAST).forEach(function (k) {
    if (!BUILD[k] || !SPOTS[CAST[k].room]) return;
    const a = BUILD[k](), sp = SPOTS[CAST[k].room];
    a.name = CAST[k].name; a.members = CAST[k].members; a.homeRoom = CAST[k].room; a.room = a.homeRoom;
    a.homeNode = sp.home; a.node = sp.home; a.pos = NAV[sp.home].p.clone(); a.yaw = sp.homeYaw; a.yawGoal = a.yaw; a.yawS = a.yaw;
    a.state = "home"; a.queue = []; a.speed = SPEED[k]; a.height = HEIGHT[k]; a.glide = 0; a.homeSince = 0;
    // the acting state (reused every frame: nothing is allocated in the loop)
    a.st = { walking: false, speed: a.speed, working: false, seated: false, carrying: false, glide: 0 };
    a.headAt = V3(0, 0, 0); a.beats = []; a.nextThink = 0; a.nextReach = 6 + Math.random() * 8; a.reachUntil = 0;
    a.speaking = false; a.listening = false; a.listenTo = null; a.station = "idle"; a.ambient = false;
    a.reachL = null; a.reachR = null; a.typing = false; a.lookTarget = null; a.shadowR = a.shadow.geometry.parameters.radius;
    a.group.position.copy(a.pos); a.group.rotation.y = a.yaw; actors[k] = a; ACTOR_KEYS.push(k);
  });
  function pathLength(a) { let L = 0; if (!a.path) return 0; L += a.pos.distanceTo(a.path[Math.min(a.seg + 1, a.path.length - 1)]);
    for (let i = a.seg + 1; i < a.path.length - 1; i++) L += a.path[i].distanceTo(a.path[i + 1]); return L; }
  function visitNodeFor(room, a) {
    const sp = SPOTS[room]; if (!sp) return null;
    const busy = Object.keys(actors).map(function (k) { return actors[k] !== a ? (actors[k].state === "out" || actors[k].state === "visit" ? actors[k].destNode : actors[k].node) : null; });
    for (let i = 0; i < sp.visit.length; i++) if (busy.indexOf(sp.visit[i]) < 0) return { id: sp.visit[i], yaw: sp.visitYaw[i] };
    return { id: sp.visit[0], yaw: sp.visitYaw[0] };
  }
  // ground speed: the drawing's own pace; a real biped walks at its own walk's measured speed (the feet do not
  // slide). Jet hurries with a closed trade's cube (the carry move, quicker); Voss takes quick penguin steps and
  // glides when the way is long (wings spread).
  const WALK_RATE = { carry: 3.2, walk_penguin: 2.4, other: 1.25 };  // (a brisker cadence: the playback and the ground speed scale together)
  function walkClip(a) { return a.carrying ? "carry" : (a.actor && a.actor.spec.walk) || "walk_casual"; }
  function walkSpeedOf(a) {
    const A = a.actor;
    if (!A || A.spec.kind !== "biped") return a.speed * (a.key === "voss" ? lerp(1, 2.3, a.glide) : 1);
    const name = walkClip(a), feet = (A.library.info(name).speed_hips_per_s || 0) * A.hipsHeight * (WALK_RATE[name] || WALK_RATE.other);
    return a.key === "voss" ? lerp(Math.max(0.15, feet), 1.5, a.glide) : Math.max(0.15, feet);
  }
  function travelSpeed(a) { return a.key === "voss" ? (a.actor ? 1.35 : 1.8) : walkSpeedOf(a); }
  function startWalk(a, action) {
    const v = visitNodeFor(action.dest, a); if (!v) return;
    const ids = route(a.node, v.id); if (!ids) return;
    a.path = ids.map(function (id) { return NAV[id].p.clone(); }); a.path[0] = a.pos.clone(); a.seg = 0;
    a.state = "out"; a.action = action; a.destNode = v.id; a.destYaw = v.yaw; a.destRoom = action.dest; a.ambient = !!action.ambient;
    a.carrying = action.carry || null; if (a.carrying) showCube(a.carrying);
    if (focus && focus.actor === a) focus.until = Math.max(focus.until, simT + 2 + pathLength(a) / travelSpeed(a));
  }
  function walkBack(a) {
    const ids = route(a.node, a.homeNode); if (!ids) { a.state = "home"; return; }
    a.path = ids.map(function (id) { return NAV[id].p.clone(); }); a.path[0] = a.pos.clone(); a.seg = 0; a.state = "back"; a.room = a.homeRoom; a.ambient = false;
  }
  // a home place moved (the table changed): whoever stands there steps to the new place
  function resettle(nodeId) {
    ACTOR_KEYS.forEach(function (k) { const a = actors[k];
      if (a.node !== nodeId || (a.state !== "home" && a.state !== "visit")) return;
      a.path = [a.pos.clone(), NAV[nodeId].p.clone()]; a.seg = 0;
      if (a.state === "home") a.state = "back"; else { a.state = "out"; a.action = { dest: a.destRoom, hold: Math.max(1, a.visitUntil - simT) }; }
    });
  }
  const _wdir = new THREE.Vector3();
  function stepWalk(a, dt) {
    const remaining = pathLength(a);
    if (a.key === "voss") a.glide += ((remaining > (a.actor ? 3.0 : 4.5) && a.state !== "home" ? 1 : 0) - a.glide) * Math.min(1, dt * 1.6);
    let left = walkSpeedOf(a) * dt;
    while (left > 0 && a.seg < a.path.length - 1) {
      const to = a.path[a.seg + 1], d = to.distanceTo(a.pos);
      if (d <= left) { a.pos.copy(to); a.seg += 1; left -= d; }
      else { _wdir.copy(to).sub(a.pos).normalize(); a.pos.addScaledVector(_wdir, left); left = 0; if (Math.abs(_wdir.x) + Math.abs(_wdir.z) > 0.01) a.yawGoal = Math.atan2(_wdir.x, _wdir.z); }
    }
    if (a.seg >= a.path.length - 1) {
      a.path = null;
      if (a.state === "out") { a.state = "visit"; a.node = a.destNode; a.room = a.destRoom; a.yawGoal = a.destYaw; a.visitUntil = simT + (a.action.hold || 3);
        if (a.action.onArrive) a.action.onArrive(a); if (focus && focus.actor === a) focus.until = Math.max(focus.until, simT + (a.action.hold || 3) + 1.5); }
      else { a.state = "home"; a.node = a.homeNode; a.room = a.homeRoom; a.yawGoal = SPOTS[a.homeRoom].homeYaw; a.homeSince = simT; }
    }
  }
  const _cp = new THREE.Vector3(), _w1 = new THREE.Vector3(), _w2 = new THREE.Vector3();
  function updateActors(dt) {
    // who is speaking (a bubble with the member's own words is up) and who stands near enough to listen
    for (let i = 0; i < ACTOR_KEYS.length; i++) { const a = actors[ACTOR_KEYS[i]]; a.head.getWorldPosition(a.headAt); a.speaking = false; a.listenTo = null; }
    for (let i = 0; i < bubbles.length; i++) if (simT < bubbles[i].until) bubbles[i].actor.speaking = true;
    for (let i = 0; i < ACTOR_KEYS.length; i++) {
      const a = actors[ACTOR_KEYS[i]]; if (a.speaking || a.walking) continue;
      let best = 6.0;
      for (let j = 0; j < ACTOR_KEYS.length; j++) { const s = actors[ACTOR_KEYS[j]]; if (s === a || !s.speaking) continue;
        const d = a.group.position.distanceTo(s.group.position); if (d < best) { best = d; a.listenTo = s; } }
    }
    for (let i = 0; i < ACTOR_KEYS.length; i++) {
      const k = ACTOR_KEYS[i], a = actors[k];
      a.listening = !!a.listenTo;
      while (a.beats.length && simT >= a.beats[0].at) a.beats.shift().fn(a);
      const busy = !!(a.actor && a.actor.oneShot);  // a one-shot move (a nod, a cheer) finishes before a walk starts
      if (a.state === "home" && a.queue.length && !busy) startWalk(a, a.queue.shift());
      if (a.state === "out" || a.state === "back") stepWalk(a, dt);
      else if (a.state === "visit" && simT >= a.visitUntil && !busy) walkBack(a);
      else if (a.key === "voss") a.glide += (0 - a.glide) * Math.min(1, dt * 2);
      a.walking = a.state === "out" || a.state === "back";
      a.yaw += angleDiff(a.yawGoal, a.yaw) * (1 - Math.exp(-dt * (a.walking ? 7 : 3)));
      a.yawS += angleDiff(a.yaw, a.yawS) * (1 - Math.exp(-dt * 1.4));
      let working = false; for (let j = 0; j < a.members.length; j++) if (members[a.members[j]] && members[a.members[j]].status === "working") working = true;
      const st = a.st;
      st.walking = a.walking; st.speed = a.speed; st.working = working && a.state === "home"; st.seated = a.state === "home" && (k === "nyx" || k === "rook");
      st.carrying = !!a.carrying; st.glide = a.glide;
      a.group.position.set(a.pos.x, a.pos.y + a.glide * 0.38, a.pos.z); a.group.rotation.y = a.yaw;
      if (a.actor) {
        try { act(a, st); driveActor(a, st, dt); } catch (e) { dropModel(a, e); }
      } else {
        // the drawing: turn the head towards the drone when it is close and in front, blink every few seconds
        _cp.copy(camera.position).sub(a.headAt);
        const rel = angleDiff(Math.atan2(_cp.x, _cp.z), a.yaw), near = _cp.length() < 7.5 && Math.abs(rel) < 1.9;
        const wantY = near ? clamp(rel, -0.75, 0.75) : 0, wantP = near ? clamp(-Math.atan2(_cp.y, Math.hypot(_cp.x, _cp.z)) * 0.6, -0.35, 0.3) : 0;
        a.lookYaw += (wantY - a.lookYaw) * (1 - Math.exp(-dt * 2.5)); a.lookPitch += (wantP - a.lookPitch) * (1 - Math.exp(-dt * 2.5));
        a.blinkAt -= dt; if (a.blinkAt <= 0 && a.blinkT < 0) { a.blinkT = 0; a.blinkAt = 2.2 + Math.random() * 4.5; }
        let bv = 0; if (a.blinkT >= 0) { a.blinkT += dt; const u = a.blinkT / 0.17; bv = u >= 1 ? 0 : Math.sin(u * Math.PI); if (u >= 1) a.blinkT = -1; }
        for (let j = 0; j < a.eyes.length; j++) { const e = a.eyes[j]; if (e.lid) e.lid.rotation.x = e.lid.userData.open + (1.5 - e.lid.userData.open) * bv; }
        if (a.blink) a.blink(bv);
        a.anim(simT + a.phase, st, dt);
      }
      a.shadow.position.y = 0.012 - a.glide * 0.38; a.shadow.material.opacity = 0.6;
      if (a.carrying && cube.mesh.visible && !cube.flight) {
        if (a.actor && a.actor.bones) cubeBetweenHands(a);
        else { a.carry.getWorldPosition(cube.mesh.position); cube.mesh.position.y += Math.sin(simT * 4) * 0.02; }
      }
    }
  }

  // ============================================================= ACTING FROM THE LEDGER (the real cast)
  // Moves are acting, triggered only by real events and statuses: talk while the member's own words are up, listen
  // (and turn) when someone nearby talks, think while blocked or waiting, Rook nods at good news and worries at bad,
  // a bad-tone event worries its speaker, Jet cheers only for a closed winning trade and shrugs at a loss, Voss
  // thinks over the Polymarket desk's lessons before saying them. Ambient life (coffee, looking around, chatting with
  // a neighbour) only while every member an actor plays is idle, and it never shows words or numbers.
  const BENCH = { l: V3(0, 0, 0), r: V3(0, 0, 0), c: V3(0, 0, 0) };  // where Pip's hands tinker (set with the bench)
  function benchAt(top, zBack) { BENCH.l.copy(WS2.at(0.17, top, zBack)); BENCH.r.copy(WS2.at(-0.17, top, zBack)); BENCH.c.copy(WS2.at(0, top - 0.05, zBack + 0.12)); }
  benchAt(0.76, -0.95);
  function oneShot(a, name, maxSeconds) {
    const A = a.actor; if (!A || A.spec.kind !== "biped" || a.state === "out" || a.state === "back") return false;
    if (!A.play(name, 0.3)) return false;
    if (maxSeconds) { const shot = A.oneShot; a.beats.push({ at: simT + maxSeconds, fn: function (b) { if (b.actor && b.actor.oneShot === shot) endOneShot(b.actor); } });
      a.beats.sort(function (x, y) { return x.at - y.at; }); }
    return true;
  }
  function endOneShot(A) {
    if (!A.oneShot) return;
    A.oneShot.fadeOut(0.35); A.oneShot = null;
    if (A.current) A.current.reset().fadeIn(0.35).play();
  }
  function visitorOf(a) {
    for (let i = 0; i < ACTOR_KEYS.length; i++) { const v = actors[ACTOR_KEYS[i]]; if (v !== a && v.state === "visit" && v.ambient && v.room === a.homeRoom) return v; }
    return null;
  }
  function handToward(a, p) {  // the hand on the side of the point reaches for it
    const left = (p.x - a.pos.x) * Math.cos(a.yaw) - (p.z - a.pos.z) * Math.sin(a.yaw) > 0;
    a.reachL = left ? p : null; a.reachR = left ? null : p;
  }
  const STATION = {  // at their station while one of their members works
    pip: function (a) { a.reachL = BENCH.l; a.reachR = BENCH.r; a.typing = true; a.lookTarget = BENCH.c; },
    voss: function (a) {
      a.station = Math.floor((simT + 3) / 12) % 2 ? "look" : "idle";
      if (simT >= a.nextReach) { a.reachUntil = simT + 2.8; a.nextReach = simT + 13 + Math.random() * 9; }
      if (simT < a.reachUntil) { handToward(a, TABLE_PT); a.lookTarget = TABLE_PT; a.station = "idle"; }
    },
    rook: function (a) { a.station = "idle"; },
    jet: function (a) { a.station = "look"; },
  };
  function act(a, st) {
    a.station = "idle"; a.reachL = null; a.reachR = null; a.typing = false; a.lookTarget = null;
    if (st.walking) return;
    if (a.state === "visit") {
      a.station = a.room === "kiosk" && a.key === "jet" ? "drink" : a.ambient ? "chat" : "idle";
      if (a.ambient && a.room === "table" && actors.voss && actors.voss.state === "home") a.lookTarget = actors.voss.headAt;
      return;
    }
    if (a.state !== "home") return;
    const status = worstStatus(a.members);
    if (status === "blocked" || status === "waiting") {
      if (simT >= a.nextThink && !a.speaking) { a.nextThink = simT + 17 + Math.random() * 8; oneShot(a, "think", 6); }
      return;
    }
    const visitor = visitorOf(a);  // a neighbour dropped by: chat (no words)
    if (visitor) { a.station = "chat"; a.lookTarget = visitor.headAt; return; }
    if (status === "working") { if (STATION[a.key]) STATION[a.key](a); }
    else if (simT - a.homeSince > 20) a.station = Math.floor((simT + a.phase * 10) / 14) % 2 ? "look" : "idle";
  }
  function facingCamera(a) { _cp.copy(camera.position).sub(a.headAt); return _cp.length() < 6.5 && Math.abs(angleDiff(Math.atan2(_cp.x, _cp.z), a.yaw)) < 1.4; }
  function driveActor(a, st, dt) {
    const A = a.actor, biped = A.spec.kind === "biped";
    if (biped) {
      let loop = a.station, rate = 1;
      if (st.walking) { loop = walkClip(a); rate = WALK_RATE[loop] || WALK_RATE.other; if (a.key === "voss" && a.glide > 0.35) { loop = "idle"; rate = 1; } }
      else if (a.speaking) loop = "talk";
      else if (a.listening) loop = "listen";
      if (st.walking && A.oneShot) endOneShot(A);
      if (!A.oneShot) A.play(loop, 0.4);
      if (A.current) A.current.setEffectiveTimeScale(st.walking ? rate : 1);
    }
    // the head: whoever talks nearby, the work in hand, or a glance at the drone when it comes close
    if (a.listenTo) A.lookAt(a.listenTo.headAt, 0.9);
    else if (a.lookTarget) A.lookAt(a.lookTarget, 0.75);
    else if (!st.walking && facingCamera(a)) A.lookAt(camera.position, 0.45);
    else A.lookAt(null);
    if (biped) {
      if (st.walking && a.key === "voss" && a.glide > 0.35) {  // gliding: the wings spread
        const h = a.height, lx = Math.cos(a.yaw), lz = -Math.sin(a.yaw), fx = Math.sin(a.yaw) * 0.12, fz = Math.cos(a.yaw) * 0.12;
        _w1.set(a.group.position.x + lx * h * 0.75 + fx, a.group.position.y + h * 0.72, a.group.position.z + lz * h * 0.75 + fz);
        _w2.set(a.group.position.x - lx * h * 0.75 + fx, a.group.position.y + h * 0.72, a.group.position.z - lz * h * 0.75 + fz);
        A.reachTo(_w1, _w2, false);
      } else if (!st.walking && (a.reachL || a.reachR)) A.reachTo(a.reachL, a.reachR, a.typing);
      else A.reachTo(null, null);
      A.root.rotation.x = a.key === "voss" ? a.glide * 0.22 : 0;
    } else {
      // Nyx and Mote have no neck: the whole body turns a little toward whoever talks
      const want = a.listenTo ? clamp(angleDiff(Math.atan2(a.listenTo.headAt.x - a.headAt.x, a.listenTo.headAt.z - a.headAt.z), a.yaw), -0.7, 0.7) : 0;
      A.root.rotation.y += (want - A.root.rotation.y) * Math.min(1, dt * 2.5);
    }
    if (a.rig) a.rig(dt, st);
    A.update(dt);
  }
  function cubeBetweenHands(a) {  // Jet holds the closed trade's cube between his hands
    const B = a.actor.bones;
    B.LeftHand.getWorldPosition(_w1); B.RightHand.getWorldPosition(_w2);
    const gap = _w1.distanceTo(_w2);
    cube.mesh.position.addVectors(_w1, _w2).multiplyScalar(0.5);
    cube.mesh.position.x += Math.sin(a.yaw) * 0.05; cube.mesh.position.z += Math.cos(a.yaw) * 0.05;
    cube.mesh.scale.setScalar(clamp(gap / 0.36, 0.7, 1.15));
  }
  // ambient life: now and then one idle member strolls (coffee at the kiosk, a word with Voss at the table); no
  // words, no numbers, and never while there is real work in the queue or the camera is on a real moment
  const STROLL = { jet: "kiosk", pip: "table", nyx: "table", mote: "table" };
  let nextStroll = 40;
  function ambientLife() {
    if (simT < nextStroll) return;
    nextStroll = simT + 45 + Math.random() * 40;
    if (focus && simT < focus.until) return;
    const idle = ACTOR_KEYS.map(function (k) { return actors[k]; }).filter(function (a) {
      return STROLL[a.key] && a.state === "home" && !a.queue.length && !a.carrying && worstStatus(a.members) === "idle" && simT - a.homeSince > 30
        && !(a.actor && a.actor.oneShot) && (STROLL[a.key] !== "table" || (actors.voss && actors.voss.state === "home" && !visitorOf(actors.voss)));
    });
    if (!idle.length) return;
    const a = idle[Math.floor(Math.random() * idle.length)];
    a.queue.push({ dest: STROLL[a.key], hold: STROLL[a.key] === "kiosk" ? 12 : 11, ambient: true });
  }

  // ============================================================= REAL MODELS: the cast and the hero props, progressively
  // Nothing here blocks the first frame: the drawings are up first, then the move library and the six characters
  // download together (each swaps in with a quick fade as soon as it is ready), then the props, nearest the camera
  // first. A missing or broken file keeps its drawing; a fixed-text line in the footer counts the crew and the set.
  const ASSET = "office/assets/";
  let gltfLoader = null, motionMod = null;
  const loading = { crew: 0, crewN: 0, set: 0, setN: 0 };
  function showLoading() {
    const text = loading.crew < loading.crewN ? "loading the crew " + loading.crew + "/" + loading.crewN
      : loading.set < loading.setN ? "loading the set " + loading.set + "/" + loading.setN : "";
    loadingEl.textContent = text; loadingEl.hidden = !text;
  }
  // a quick fade-in (the model over its drawing), then the drawing goes
  const fades = [];
  function fadeIn(root, seconds, done) {
    const keep = [];
    root.traverse(function (o) { if (!o.isMesh) return; [].concat(o.material).forEach(function (m) {
      if (keep.some(function (k) { return k.m === m; })) return;
      keep.push({ m: m, t: m.transparent, o: m.opacity }); m.transparent = true; m.opacity = 0; m.needsUpdate = true; }); });
    fades.push({ keep: keep, t: 0, dur: seconds, done: done });
  }
  function updateFades(dt) {
    for (let i = fades.length - 1; i >= 0; i--) {
      const f = fades[i]; f.t += dt; const u = Math.min(1, f.t / f.dur), e = u * u * (3 - 2 * u);
      for (let j = 0; j < f.keep.length; j++) f.keep[j].m.opacity = f.keep[j].o * e;
      if (u >= 1) {
        for (let j = 0; j < f.keep.length; j++) { const k = f.keep[j]; k.m.transparent = k.t; k.m.opacity = k.o; k.m.needsUpdate = true; }
        fades.splice(i, 1); if (f.done) f.done();
      }
    }
  }
  // the models' own PBR textures under this sky: the environment map, shadows, and on phones half-size prop textures
  function dress(root, envK) {
    root.traverse(function (o) {
      if (!o.isMesh) return;
      o.castShadow = Q.shadows; o.receiveShadow = true;
      [].concat(o.material).forEach(function (m) { if (m && m !== bellMat && "envMapIntensity" in m) m.envMapIntensity = envK; });
    });
  }
  function shrinkTextures(root, size, keys) {
    const seen = [];
    root.traverse(function (o) { if (!o.isMesh) return; [].concat(o.material).forEach(function (m) {
      (keys || ["map", "normalMap", "roughnessMap", "metalnessMap", "emissiveMap", "aoMap"]).forEach(function (key) {
        const t = m[key]; if (!t || seen.indexOf(t) >= 0 || !t.image || !(t.image.width > size)) return; seen.push(t);
        const c = document.createElement("canvas"); c.width = c.height = size; const ctx = c.getContext("2d"); if (!ctx) return;
        ctx.drawImage(t.image, 0, 0, size, size); if (t.image.close) t.image.close(); t.image = c; t.needsUpdate = true;
      }); }); });
  }
  // scale to height, turn to face +Z, stand on the floor, centred (the same fit as cast_motion.js's actors)
  function fitModel(scene3, height, yaw) {
    const inner = new THREE.Group(); inner.add(scene3); scene3.rotation.y = yaw || 0; inner.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(inner), size = box.getSize(new THREE.Vector3());
    if (!(size.y > 1e-6) || !isFinite(size.y)) throw new Error("empty model");
    inner.scale.setScalar(height / size.y); inner.updateMatrixWorld(true);
    box.setFromObject(inner); const c = box.getCenter(new THREE.Vector3());
    inner.position.set(-c.x, -box.min.y, -c.z); inner.updateMatrixWorld(true);
    inner.userData.size = box.getSize(new THREE.Vector3());
    return inner;
  }
  function dropModel(a, e) {  // a model that misbehaves goes; the drawing comes back
    console.warn("world: model for " + a.key + " failed, back to the drawing", e);
    if (a.model) a.group.remove(a.model); a.model = null; a.actor = null; a.rig = null; a.body.visible = true; a.body.scale.setScalar(1);
    a.shadow.scale.setScalar(1); a.head.position.y = a.height0 || a.head.position.y;
  }

  // Rook's model lost its amber eyes: two small glowing spheres on his Head bone, facing forward, gently pulsing
  const rookEyeMat = new THREE.MeshBasicMaterial({ color: hdr(0xffa22e, 3.2) });
  const rookEyeHalo = new THREE.SpriteMaterial({ map: glowTex, color: 0xff7a14, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0.4 });
  function rookEyes(A) {
    const head = A.bones && A.bones.Head; let mesh = null;
    A.model.traverse(function (o) { if (o.isSkinnedMesh && !mesh) mesh = o; });
    if (!head || !mesh) return;
    const bi = mesh.skeleton.bones.indexOf(head); if (bi < 0) return;
    A.root.updateMatrixWorld(true); mesh.skeleton.update();
    const toRoot = new THREE.Matrix4().copy(A.root.matrixWorld).invert().multiply(mesh.matrixWorld);
    const pos = mesh.geometry.attributes.position, si = mesh.geometry.attributes.skinIndex, sw = mesh.geometry.attributes.skinWeight;
    const v = new THREE.Vector3(), pts = [], box = new THREE.Box3();
    for (let i = 0; i < pos.count; i++) {
      let w = 0; for (let c = 0; c < 4; c++) if (si.getComponent(i, c) === bi) w += sw.getComponent(i, c);
      if (w < 0.6) continue;
      mesh.getVertexPosition(i, v); v.applyMatrix4(toRoot); pts.push(v.clone()); box.expandByPoint(v);
    }
    if (pts.length < 20) return;
    const size = box.getSize(new THREE.Vector3()), r = Math.max(0.018, size.x * 0.075), headS = head.getWorldScale(new THREE.Vector3()).x / A.root.getWorldScale(v).x;
    [-1, 1].forEach(function (s) {
      const ex = (box.min.x + box.max.x) / 2 + s * size.x * 0.2, ey = box.min.y + size.y * 0.56;
      let front = box.min.z;  // the face's surface in front of this eye
      for (let i = 0; i < pts.length; i++) { const p = pts[i]; if (Math.abs(p.x - ex) < size.x * 0.1 && Math.abs(p.y - ey) < size.y * 0.1 && p.z > front) front = p.z; }
      const eye = new THREE.Mesh(new THREE.SphereGeometry(r, 16, 10), rookEyeMat);
      const at = head.worldToLocal(A.root.localToWorld(new THREE.Vector3(ex, ey, front - r * 0.25)));
      eye.position.copy(at); eye.scale.set(1.25 / headS, 0.8 / headS, 0.6 / headS);  // an amber slit, facing forward
      eye.quaternion.copy(head.getWorldQuaternion(new THREE.Quaternion()).invert().multiply(A.root.getWorldQuaternion(new THREE.Quaternion())));
      const halo = new THREE.Sprite(rookEyeHalo); halo.position.copy(at); halo.scale.setScalar(r * 4.5 / headS);
      head.add(eye, halo);
    });
    A.eyes = true;
  }
  // Mote: a soft translucent mint glow over its own texture
  function moteGlow(A) {
    A.model.traverse(function (o) { if (!o.isMesh) return; o.renderOrder = 5; [].concat(o.material).forEach(function (m) {
      m.transparent = true; m.opacity = 0.9; if (m.emissive) { m.emissive.set(0x5ff2bd); m.emissiveIntensity = 0.42; if (!m.emissiveMap && m.map) m.emissiveMap = m.map; }
      m.roughness = Math.min(m.roughness, 0.55); m.needsUpdate = true; }); });
  }
  function adoptActor(a, A, cartScene, spec) {
    const holder = new THREE.Group(); holder.name = "model:" + a.key;
    let top = A.size.y;
    if (cartScene) {  // Mote rides inside a clear glass bell on its brass cart; the three move together
      const ch = Number(spec.cart_height) || 0.46, cart = fitModel(cartScene, ch, 0), deck = ch * 0.74;
      const cs = cart.userData.size, br = Math.min(cs.x, cs.z) * 0.36, bh = Math.max(A.size.y * 1.45, Number(spec.height) - deck);
      const bell = makeBell(br, bh); bell.position.y = deck;
      A.root.position.y = deck + 0.015;
      holder.add(cart, bell, A.root); top = deck + bh;
      a.rig = function (dt, st) {  // the cart rocks a little as it rolls
        cart.rotation.z = st.walking ? Math.sin(simT * 9) * 0.012 : 0; bell.rotation.z = cart.rotation.z;
        holder.position.y = st.walking ? Math.abs(Math.sin(simT * 9)) * 0.008 : 0;
      };
    } else holder.add(A.root);
    dress(holder, a.key === "mote" ? 1.1 : 0.95);
    holder.traverse(function (o) {  // skinned bounds once, padded for the moves (no per-frame recompute)
      if (o.isSkinnedMesh) { o.computeBoundingSphere(); o.boundingSphere.radius *= 1.6; }
    });
    if (a.key === "rook") rookEyes(A);
    if (a.key === "mote") moteGlow(A);
    if (A.spec.kind === "biped") { A.play("idle", 0); A.update(0.016); }  // never a T-pose, not even for a frame
    a.height0 = a.head.position.y;
    a.group.add(holder); a.actor = A; a.model = holder; a.height = top; a.head.position.set(0, top + 0.12, 0);
    const foot = Math.max(A.size.x, A.size.z, cartScene ? 0.8 : 0) * 0.55;
    a.shadow.scale.setScalar(clamp(foot / a.shadowR, 0.6, 3.2));
    fadeIn(holder, 0.45, function () { a.body.visible = false; });
    console.info("world: real model for " + a.key + " in place");
  }
  async function loadMember(id, libReady) {
    const a = actors[id], spec = MODEL_CAST[id];
    try {
      // the model downloads alongside the move library; it swaps in once both are here
      const files = Promise.all([gltfLoader.loadAsync(ASSET + spec.asset)].concat(spec.cart ? [gltfLoader.loadAsync(ASSET + spec.cart)] : []));
      files.catch(function () {});  // (handled below, after the library)
      const lib = await libReady, kind = String(spec.kind || "prop");
      if (!motionMod) throw new Error("no motion module");
      if (kind === "biped" && !lib) throw new Error("no move library");
      const got = await files;
      // phones: the colour maps stay sharp (faces read close up); the normal, roughness and glow maps go to half size
      if (Q.small) got.forEach(function (g, i) { shrinkTextures(g.scene, 512, i ? null : ["normalMap", "roughnessMap", "metalnessMap", "emissiveMap"]); });
      const s = { id: id, file: spec.asset, kind: kind, walk: spec.walk || "walk_casual", yaw: Number(spec.yaw) || 0,
                  height: spec.cart ? Number(spec.body_height) || 0.4 : Number(spec.height) || a.height };
      const A = new motionMod.Actor(got[0].scene, s, lib);
      if (kind === "biped" && A.spec.kind !== "biped") throw new Error("the rig is missing bones");
      adoptActor(a, A, got[1] ? got[1].scene : null, spec);
    } catch (e) { console.warn("world: model for " + id + " could not load, keeping the drawing", e); }
    loading.crew += 1; showLoading();
  }

  // where each hero prop stands (a room's own coordinates: across, up, toward its door; ry turns it from facing the
  // door), and what happens once it is in
  function propSpot(F, x, y, z, ry) { return { at: F.at(x, y, z), yaw: F.yaw + (ry || 0) }; }
  // lanterns: flanking the paths to the workshop and the den (in the arrival shot), down the bridge and (large
  // screens) along the promenade; the bridge and promenade ones take the place of procedural railing lamps
  const LANTERN_SPOTS = [WS2.at(-1.6, 0, 5.35), WS2.at(1.6, 0, 5.35), DN2.at(-1.6, 0, 5.35), DN2.at(1.6, 0, 5.35),
    V3(-1.62, 0, 10.68), V3(1.62, 0, 10.68)].concat(Q.small ? [] : [V3(-1.62, 0, 14.03), V3(1.62, 0, 14.03),
    V3(-6.65, 0, 17.15), V3(4.3, 0, 17.15), V3(8.68, 0, 17.15)]);
  const ISLAND_SPOTS = [[-36, -5, -20, 0.4, 1.0], [41, 1, -27, 2.1, 1.25], [-27, 4, 31, 4.0, 0.85], [33, -9, 25, 5.2, 1.1]].slice(0, Q.small ? 2 : 4);
  const PLACE = {
    missiontable: [propSpot(WF, 0, DAIS_Y, 0)],
    telescope: [propSpot(OB2, 0.6, 0, -1.2, 0.35)],
    vaultdoor: [propSpot(VT2, 0.9, 0, -2.63)],
    workbench: [propSpot(WS2, 0, 0, -0.62)],
    nyxdesk: [propSpot(DN2, 0, 0, -1.9)],
    archive: [propSpot(AR2, -2.4, 0, -2.69), propSpot(AR2, 2.4, 0, -2.69)],
    airship: [propSpot(WF, 27.3, -0.3, -1.5, Math.PI / 2)],
    kiosk: [propSpot(WF, 23.55, 0, 5.5, -Math.PI / 2)],
    rookdesk: [propSpot(VT2, 0.2, 0, -0.62)],
    arch: [propSpot(WS2, 0, 0, 4.55), propSpot(DN2, 0, 0, 4.55), { at: V3(0, 1.8, -9.3), yaw: 0 }],  // the workshop, the den, the observatory steps
    lantern: LANTERN_SPOTS.map(function (q) { return { at: q, yaw: 0 }; }),
    island: ISLAND_SPOTS.map(function (q) { return { at: V3(q[0], q[1], q[2]), yaw: q[3], bob: q[4] }; }),
  };
  const placed = {};  // prop id -> the placed holders
  const PLACED = {
    missiontable: function (h) {  // the hologram over the prop's own top; Voss and the visitors step up to it
      const s = h.children[0].userData.size, r = Math.max(s.x, s.z) / 2, top = DAIS_Y + s.y * 0.86;
      props.holoFit(Math.max(0.95, r * 1.6), top + 0.03); props.holoDisc.material.color.multiplyScalar(0.55); props.holoMini.children[0].material.opacity = 0.3; tableSpots(r, top); ["tbH", "tbW", "tbN"].forEach(resettle);
      board.position.y = 2.05;
    },
    workbench: function (h) { const s = h.children[0].userData.size; benchAt(s.y * 0.63, -0.62 - s.z / 2 + 0.1); },
    telescope: function (h) { props.telescopeModel = h; h.userData.yaw = h.rotation.y; },
    airship: function (h) { props.airshipModel = h; h.userData.y = h.position.y; },
    island: function (h, i) { (props.islands = props.islands || []).push({ h: h, y: h.position.y, k: PLACE.island[i].bob, ph: i * 1.7 }); },
    lantern: function (h) {  // a warm bulb and a soft halo in the lantern's head; the procedural lamps it replaces make way
      const bulb = new THREE.Mesh(G.sph(0.06, 12, 8), props.lanternBulbs.material); bulb.position.y = 2.27; bulb.scale.set(1, 1.4, 1); h.add(bulb);
      const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color: 0xffa04d, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0.5 }));
      halo.position.y = 2.27; halo.scale.setScalar(0.8); h.add(halo); (props.lanternGlow = props.lanternGlow || []).push(halo);
      if (props.lanternGlow.length < PLACE.lantern.length) return;  // the rest once, after the last copy is placed
      const zero = new THREE.Matrix4().makeScale(0, 0, 0);
      lanterns.forEach(function (q, i) {
        if (!LANTERN_SPOTS.some(function (s) { return Math.hypot(s.x - q.p[0], s.z - q.p[2]) < 0.4 && q.p[1] === 0; })) return;
        props.lanternPosts.setMatrixAt(i, zero); props.lanternBulbs.setMatrixAt(i, zero); props.lanternHalos.setMatrixAt(i, zero);
      });
      props.lanternPosts.instanceMatrix.needsUpdate = true; props.lanternBulbs.instanceMatrix.needsUpdate = true; props.lanternHalos.instanceMatrix.needsUpdate = true;
    },
  };
  async function loadProp(id) {
    const spec = MODEL_PROPS[id];
    try {
      const gltf = await gltfLoader.loadAsync(ASSET + spec.asset);
      if (Q.small) shrinkTextures(gltf.scene, 512);
      const holders = PLACE[id].map(function (spot, i) {
        const h = new THREE.Group(); h.name = "prop:" + id;
        h.add(fitModel(i ? gltf.scene.clone() : gltf.scene, Number(spec.height) || 1, Number(spec.yaw) || 0));
        h.position.copy(spot.at); h.rotation.y = spot.yaw; dress(h, 1.0);
        h.traverse(function (o) { if (o.isMesh) o.castShadow = Q.shadows && id !== "island"; });
        scene.add(h); if (PLACED[id]) PLACED[id](h, i); return h;
      });
      placed[id] = holders;
      // the copies share their materials: one fade brings them all in, then the procedural stand-ins go
      fadeIn(holders[0], 0.6, function () { (STANDIN[id] || []).forEach(function (s) { s.visible = false; }); });
    } catch (e) { console.warn("world: prop " + id + " could not load, keeping the drawing", e); }
    loading.set += 1; showLoading();
  }
  async function loadModels() {
    const castIds = MODELS.motion ? Object.keys(MODEL_CAST).filter(function (id) { return actors[id]; }) : [];
    const propIds = Object.keys(MODEL_PROPS).filter(function (id) { return PLACE[id] && PLACE[id].length; });
    if (!castIds.length && !propIds.length) return;
    loading.crewN = castIds.length; loading.setN = propIds.length; showLoading();
    try {
      const mods = await Promise.all([import("three/addons/loaders/GLTFLoader.js"), import("three/addons/libs/meshopt_decoder.module.js")]);
      const decoder = mods[1].MeshoptDecoder; await decoder.ready;
      gltfLoader = new mods[0].GLTFLoader(); gltfLoader.setMeshoptDecoder(decoder);
    } catch (e) { console.warn("world: no model loader, keeping the drawings", e); loading.crewN = loading.setN = 0; showLoading(); return; }
    if (castIds.length) {
      // the move library and the six characters together; a biped swaps in once the library is also ready
      const libReady = import("./office/assets/cast_motion.js").then(function (m) { motionMod = m; return m.loadLibrary(gltfLoader, ASSET); })
        .then(function (lib) { return lib && lib.rest && lib.manifest && lib.manifest.clips && Object.keys(lib.manifest.clips).length ? lib : null; })
        .catch(function (e) { console.warn("world: no move library, the bipeds keep their drawings", e); return null; });
      await Promise.all(castIds.map(function (id) { return loadMember(id, libReady); }));
    }
    // then the set, nearest the camera first, two at a time
    propIds.sort(function (x, y) { return PLACE[x][0].at.distanceTo(camera.position) - PLACE[y][0].at.distanceTo(camera.position); });
    const next = async function () { while (propIds.length) await loadProp(propIds.shift()); };
    await Promise.all([next(), next()]);
  }

  // ============================================================= SIGNS, LAMPS, THE TICKET BOARD, THE TRADE CUBE
  function makeBoard(cw, ch, ww, wh, opts) {
    const c = document.createElement("canvas"); c.width = cw; c.height = ch;
    const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = maxAniso;
    const m = new THREE.Mesh(new THREE.PlaneGeometry(ww, wh), new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, toneMapped: false,
      side: (opts && opts.double) ? THREE.DoubleSide : THREE.FrontSide, color: (opts && opts.k) ? hdr(0xffffff, opts.k) : 0xffffff }));
    m.userData.canvas = c; m.userData.tex = tex; m.renderOrder = 5; return m;
  }
  function fitText(ctx, text, x, y, maxW) { ctx.fillText(text, x, y, maxW); }
  // the vault sign: money.usd and exactly money.label
  const vaultSign = makeBoard(1024, 384, 2.0, 0.75); VT2.place(vaultSign, 0.9, 3.5, -2.9, 0); vaultSign.renderOrder = 0; vaultSign.material.transparent = false;
  function drawVaultSign(usd, label, accent) {
    const c = vaultSign.userData.canvas, ctx = c.getContext("2d"); if (!ctx) return;
    ctx.clearRect(0, 0, c.width, c.height);
    const g = ctx.createLinearGradient(0, 0, 0, c.height); g.addColorStop(0, "#2a1d16"); g.addColorStop(1, "#160f0b"); ctx.fillStyle = g; ctx.fillRect(0, 0, c.width, c.height);
    ctx.lineWidth = 16; ctx.strokeStyle = "#c99a48"; roundRect(ctx, 10, 10, c.width - 20, c.height - 20, 30); ctx.stroke();
    ctx.lineWidth = 4; ctx.strokeStyle = accent || "#e8c27a"; roundRect(ctx, 30, 30, c.width - 60, c.height - 60, 22); ctx.stroke();
    ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillStyle = "#ffe3a6";
    ctx.font = "bold 150px ui-sans-serif, system-ui, sans-serif"; fitText(ctx, usd, c.width / 2, 160, c.width - 100);
    ctx.fillStyle = "#e9dcc4"; ctx.font = "56px ui-sans-serif, system-ui, sans-serif"; fitText(ctx, label, c.width / 2, 290, c.width - 100);
    vaultSign.userData.tex.needsUpdate = true;
  }
  drawVaultSign("—", "", null);
  // the Polymarket desk's ticket board over the mission table (only the desk's own positions)
  const board = makeBoard(1024, 560, 2.3, 1.26, { double: true }); board.position.set(0.15, 2.18, -0.55); board.visible = false; scene.add(board);
  function drawBoard(desk) {
    const c = board.userData.canvas, ctx = c.getContext("2d"); if (!ctx) return;
    ctx.clearRect(0, 0, c.width, c.height);
    ctx.fillStyle = "rgba(8, 40, 44, .72)"; roundRect(ctx, 8, 8, c.width - 16, c.height - 16, 26); ctx.fill();
    ctx.strokeStyle = "rgba(125,255,216,.95)"; ctx.lineWidth = 5; roundRect(ctx, 8, 8, c.width - 16, c.height - 16, 26); ctx.stroke();
    ctx.textAlign = "left"; ctx.textBaseline = "middle";
    ctx.fillStyle = "#aefbe2"; ctx.font = "bold 54px ui-sans-serif, system-ui, sans-serif";
    fitText(ctx, "Polymarket desk · " + (desk.label || ""), 40, 70, c.width - 80);
    const nReal = Number(desk.open_real || 0), nPaper = Number(desk.open_paper || 0);
    ctx.fillStyle = nReal > 0 ? "#ffd27a" : "#cfe9e2"; ctx.font = "48px ui-sans-serif, system-ui, sans-serif";
    fitText(ctx, nReal + " REAL · " + nPaper + " paper", 40, 150, c.width - 80);
    ctx.fillStyle = "rgba(125,255,216,.45)"; ctx.fillRect(40, 196, c.width - 80, 3);
    (Array.isArray(desk.positions) ? desk.positions : []).slice(0, 3).forEach(function (q, i) {
      const q28 = String(q.question || "").length > 28 ? String(q.question).slice(0, 27) + "…" : String(q.question || "");
      ctx.fillStyle = q.live ? "#f0c26a" : "rgba(196,226,218,.62)"; ctx.font = (q.live ? "bold " : "") + "40px ui-sans-serif, system-ui, sans-serif";
      fitText(ctx, (q.live ? "REAL" : "paper") + "  " + String(q.side || "") + " " + (q.p_in != null && isFinite(Number(q.p_in)) ? Number(q.p_in).toFixed(3) : "") + "  " + q28, 40, 260 + i * 92, c.width - 80);
    });
    board.userData.tex.needsUpdate = true;
  }
  // the red REAL lamp at the table: lit only while the desk holds real-money positions
  const realBulbMat = new THREE.MeshStandardMaterial({ color: 0x5a1010, emissive: 0xff2a1a, emissiveIntensity: 0, roughness: 0.2 });
  const realBulb = new THREE.Mesh(G.sph(0.065, 16, 12), realBulbMat); scene.add(realBulb);
  if (HAS("missiontable")) {  // on its own brass post at the hero table's front right
    realBulb.position.set(0.66, 1.18, 1.02);
    WF.add("brass", G.cyl(0.028, 0.05, 1.06, 12), [0.66, DAIS_Y + 0.53, 1.02], null, null, BRASS_DARK);
    WF.add("brass", G.cyl(0.08, 0.1, 0.05, 14), [0.66, DAIS_Y + 0.025, 1.02], null, null, BRASS);
    WF.add("brass", G.tor(0.07, 0.012, 6, 18), [0.66, 1.18, 1.02], [Math.PI / 2, 0, 0], null, BRASS);
  } else {  // on the procedural table's rim
    realBulb.position.set(-1.2, 0.98, 1.08);
    WF.add("brass", G.cyl(0.05, 0.07, 0.12, 14), [-1.2, 0.86, 1.08], null, null, BRASS); WF.add("brass", G.tor(0.07, 0.012, 6, 18), [-1.2, 0.98, 1.08], [Math.PI / 2, 0, 0], null, BRASS);
  }
  const realHalo = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color: 0xff3a2a, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0 }));
  realHalo.scale.set(0.6, 0.6, 1); realHalo.position.copy(realBulb.position); scene.add(realHalo);
  // a status lamp at every department's door (the worst status of its members)
  const LAMP_AT = { table: WF.at(2.05, 0, -1.55), workshop: WS2.at(1.95, 0, 4.0), den: DN2.at(-1.95, 0, 4.0), archive: AR2.at(1.6, 0, 3.65),
                    vault: VT2.at(-1.6, 0, 3.65), dock: V3(21.05, 0, -2.45), observatory: OB2.at(-2.1, 0, 5.75) };
  const lamps = {};
  Object.keys(ROOMS).forEach(function (k) {
    const p = LAMP_AT[k]; if (!p) return;
    WF.add("brass", G.cyl(0.035, 0.05, 1.4, 10), [p.x, p.y + 0.7, p.z], null, null, BRASS_DARK);
    WF.add("brass", G.cyl(0.1, 0.12, 0.06, 14), [p.x, p.y + 0.03, p.z], null, null, BRASS_DARK);
    WF.add("brass", G.tor(0.11, 0.015, 6, 18), [p.x, p.y + 1.42, p.z], [Math.PI / 2, 0, 0], null, BRASS);
    const m = new THREE.MeshStandardMaterial({ color: 0x6c717c, emissive: 0x6c717c, emissiveIntensity: 0.2, roughness: 0.25 });
    const bulb = new THREE.Mesh(G.sph(0.11, 18, 14), m); bulb.position.set(p.x, p.y + 1.53, p.z); scene.add(bulb);
    const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color: 0x6c717c, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0 }));
    halo.scale.set(0.9, 0.9, 1); halo.position.copy(bulb.position); scene.add(halo);
    lamps[k] = { mat: m, halo: halo, at: bulb.position.clone() };
  });
  flushStatic();
  const LIGHT = { working: 0x4be08a, waiting: 0xf5b133, blocked: 0xff4d4d, idle: 0x6c717c, absent: 0x6c717c };
  const WORST = ["blocked", "working", "waiting", "idle"];
  function worstStatus(ids) {  // (no allocation: the acting asks every frame)
    for (let i = 0; i < WORST.length; i++) for (let j = 0; j < ids.length; j++) { const m = members[ids[j]]; if (m && m.status === WORST[i]) return WORST[i]; }
    return "idle";
  }
  function updateLamps() {
    Object.keys(lamps).forEach(function (k) {
      const st = worstStatus(ROOMS[k].members), c = LIGHT[st] || LIGHT.idle, L = lamps[k];
      L.mat.color.setHex(c); L.mat.emissive.setHex(c); L.mat.emissiveIntensity = st === "idle" ? 0.15 : 2.6; L.halo.material.color.setHex(c); L.halo.material.opacity = st === "idle" ? 0 : 0.85;
    });
  }
  // the trade cube Jet carries to the vault: gold for a win, red for a loss
  const cube = { mesh: new THREE.Group(), flight: null };
  const cubeOuter = new THREE.Mesh(G.rbox(0.24, 0.24, 0.24, 0.35, 14), new THREE.MeshPhysicalMaterial({ color: 0xffd36a, emissive: 0xffb02a, emissiveIntensity: 1.2,
    roughness: 0.1, transparent: true, opacity: 0.55, clearcoat: 1, depthWrite: false }));
  const cubeCore = new THREE.Mesh(G.rbox(0.12, 0.12, 0.12, 0.4, 10), new THREE.MeshBasicMaterial({ color: hdr(0xffd36a, 5) }));
  cube.mesh.add(cubeOuter, cubeCore); cube.mesh.visible = false; scene.add(cube.mesh);
  const vaultFlash = new THREE.Mesh(G.tor(1.05, 0.06, 10, 64), new THREE.MeshBasicMaterial({ color: hdr(0xffd36a, 4), transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }));
  // the vault door's face: the procedural door's, or the hero door's (it stands proud of the wall)
  const DOOR = HAS("vaultdoor") ? { y: 1.32, z: -2.24, r: 0.95 } : { y: 1.55, z: -2.62, r: 1.0 };
  VT2.place(vaultFlash, 0.9, DOOR.y, DOOR.z, 0); vaultFlash.scale.setScalar(DOOR.r); let flashUntil = 0;
  function showCube(kind) {
    const won = kind === "gold", c = won ? 0xffd36a : 0xff5a4a;
    cubeOuter.material.color.setHex(c); cubeOuter.material.emissive.setHex(won ? 0xffb02a : 0xff2a1a); cubeCore.material.color.copy(hdr(c, 5));
    vaultFlash.material.color.copy(hdr(c, 4)); cube.mesh.visible = true; cube.flight = null;
  }
  function deliverCube(a, pnl) {
    const from = cube.mesh.position.clone(), to = VT2.at(0.9, DOOR.y, DOOR.z + 0.12), mid = VT2.at(-3.5, 1.0, -0.2);
    cube.flight = { t: 0, from: from, mid: mid, to: to, pnl: pnl }; a.carrying = null;
  }
  function updateCube(dt) {
    if (cube.flight) {
      const f = cube.flight; f.t += dt / 1.8; const u = Math.min(1, f.t);
      const p = u < 0.4 ? f.from.clone().lerp(f.mid, u / 0.4) : f.mid.clone().lerp(f.to, (u - 0.4) / 0.6); p.y += Math.sin(u * Math.PI) * 0.4;
      cube.mesh.position.copy(p); cube.mesh.rotation.y += dt * 3; cube.mesh.scale.setScalar(1 - Math.max(0, u - 0.85) * 5);
      if (u >= 1) { cube.flight = null; cube.mesh.visible = false; cube.mesh.scale.setScalar(1); flashUntil = simT + 2.2; dropLabel(f.pnl, f.to); }
    } else if (cube.mesh.visible) cube.mesh.rotation.y += dt * 1.5;
    vaultFlash.material.opacity = flashUntil > simT ? Math.min(1, (flashUntil - simT) / 1.2) * 0.9 : 0;
  }

  // ============================================================= THE DRONE: shots, glides between rooms, touch
  function rig(F, p, l) { return { pos: F.at(p[0], p[1], p[2]), look: F.at(l[0], l[1], l[2]) }; }
  const SHOTS = {
    table: { pos: V3(-1.3, 1.7, 3.05), look: V3(-0.45, 0.98, -0.1) },
    workshop: rig(WS2, [0.95, 1.55, 1.15], [-0.05, 0.92, -1.3]),
    den: rig(DN2, [1.95, 1.6, -1.7], [-0.3, 0.85, -1.2]),  // beside the desk: Nyx in profile at the screens
    archive: rig(AR2, [0.35, 1.35, 0.55], [-1.3, 0.72, -1.5]),
    vault: rig(VT2, [1.5, 1.85, 1.9], [0.0, 1.55, -1.45]),
    dock: { pos: V3(20.9, 1.65, 0.75), look: V3(23.4, 0.8, -1.7) },
    kiosk: { pos: V3(19.4, 1.8, 3.0), look: V3(22.6, 0.95, 5.6) },
    observatory: rig(OB2, [-2.9, 2.1, 3.3], [0.6, 1.5, -1.5]),
  };
  // the arrival (the pack's primary shot): the drone floats just above the bridge walkway at the courtyard's edge,
  // close behind the railings, the mission table and Voss ahead, the observatory and its telescope behind; on a
  // portrait phone it comes closer so faces stay readable. Each shot fills one reused object (no allocation).
  const _arr = { pos: V3(0, 0, 0), look: V3(0, 0, 0) }, _map = { pos: V3(0, 0, 0), look: V3(1, 0, 1) }, _fol = { pos: V3(0, 0, 0), look: V3(0, 0, 0) };
  function arrivalShot(t) {
    const tall = camera.aspect < 0.85, z = (tall ? 5.0 : 6.55) + Math.sin(t * 0.055) * (tall ? 0.45 : 0.4), x = (tall ? -0.35 : 0.1) + Math.sin(t * 0.041) * (tall ? 0.25 : 0.35);
    _arr.pos.set(x, 2.05 + Math.sin(t * 0.09) * 0.07, z);
    _arr.look.set((tall ? -0.8 : -0.45) + Math.sin(t * 0.032) * (tall ? 0.5 : 2.0), 0.95, -0.9);
    return _arr;
  }
  function mapShot(t) { const a = 0.35 + t * 0.025; _map.pos.set(Math.sin(a) * 34, 25, Math.cos(a) * 34 + 2); return _map; }
  const _o = new THREE.Vector3(), _d = new THREE.Vector3(), _r = new THREE.Ray(), _b = new THREE.Box3(), _hit = new THREE.Vector3();
  function blocked(from, to) {
    // the nearest solid wall between the subject and the drone (oriented boxes), as a fraction of the way
    let best = 1; const len = from.distanceTo(to); if (len < 1e-3) return 1;
    for (let i = 0; i < blockers.length; i++) {
      const b = blockers[i];
      _o.copy(from).applyMatrix4(b.inv); _d.copy(to).applyMatrix4(b.inv).sub(_o).normalize(); _r.set(_o, _d);
      _b.min.copy(b.half).negate(); _b.max.copy(b.half);
      if (_r.intersectBox(_b, _hit)) { const f = _hit.distanceTo(_o) / len; if (f < best) best = f; }
    }
    return best;
  }
  const _fwd = new THREE.Vector3(), _side = new THREE.Vector3(), _fh = new THREE.Vector3();
  // follow a walker from close behind; a courier with a closed trade's cube is led instead (the drone flies ahead,
  // facing him, so the cube in his hands and his visor read)
  function followShot(a) {
    const base = a.group.position, h = a.height, lead = !!a.carrying;
    _fwd.set(Math.sin(a.yawS), 0, Math.cos(a.yawS)); _side.set(_fwd.z, 0, -_fwd.x);
    _fh.copy(base); _fh.y += h * 0.85;
    const want = _fol.pos.copy(base).addScaledVector(_fwd, lead ? 1.7 + h * 0.6 : -(2.2 + h * 0.75)).addScaledVector(_side, lead ? 0.5 : 0.75);
    want.y += lead ? Math.max(1.35, h + 0.5) : Math.max(1.6, h + 0.75);
    const f = blocked(_fh, want); if (f < 1) want.lerpVectors(_fh, want, Math.max(0.25, f - 0.08));
    _fol.look.copy(base).addScaledVector(_fwd, lead ? 0.1 : 2.0).setY(base.y + h * (lead ? 0.5 : 0.55));
    return _fol;
  }
  // a close shot of someone where they stopped (a hand-off, a delivery): in front of them, a little to the side
  // (if a wall is in the way, the drone swings round the subject to the clearest side rather than closing in)
  const _face = { pos: V3(0, 0, 0), look: V3(0, 0, 0) }, _try = new THREE.Vector3(), SWING = [0.35, -0.35, 1.0, -1.0, 1.7, -1.7, 2.6, -2.6];
  function faceShot(a) {
    const base = a.group.position, h = a.height, d = 1.9 + h * 0.55, up = Math.max(1.4, h * 0.85 + 0.5);
    _fh.copy(base); _fh.y += h * 0.7;
    let best = -1, bestA = SWING[0];
    for (let i = 0; i < SWING.length && best < 0.98; i++) {
      const ang = a.yawS + SWING[i];
      _try.set(base.x + Math.sin(ang) * d, base.y + up, base.z + Math.cos(ang) * d);
      const f = blocked(_fh, _try); if (f > best) { best = f; bestA = ang; }
    }
    const want = _face.pos.set(base.x + Math.sin(bestA) * d, base.y + up, base.z + Math.cos(bestA) * d);
    if (best < 1) want.lerpVectors(_fh, want, Math.max(0.55, best - 0.08));
    _face.look.copy(base).setY(base.y + h * 0.6);
    return _face;
  }
  function roomShot(room) { return SHOTS[room] || SHOTS.table; }
  const cam = { pos: V3(0, 0, 0), look: V3(0, 0, 0) };
  let shotKey = "", shotFn = null, tween = null;
  function cut(key, fn) {
    if (key === shotKey) { shotFn = fn; return; }
    shotKey = key; shotFn = fn; const s = fn(simT), d = s.pos.distanceTo(cam.pos);
    if (cam.pos.lengthSq() === 0) { cam.pos.copy(s.pos); cam.look.copy(s.look); tween = null; return; }
    tween = { from: cam.pos.clone(), fromLook: cam.look.clone(), t: 0, dur: clamp(1.0 + d / 6.5, 1.1, 5.5), lift: d > 8 ? Math.min(7, d * 0.24) : 0 };
    renderCard();
  }
  const user = { yaw: 0, pitch: 0, zoom: 1 }; let lastInputAt = -1e9, shake = 0;
  const _camP = new THREE.Vector3(), _dir = new THREE.Vector3(), _right = new THREE.Vector3(), _look = new THREE.Vector3(), UP = V3(0, 1, 0);
  function updateCamera(dt, t) {
    const s = shotFn(t);
    if (tween) {
      tween.t += dt / tween.dur; const u = Math.min(1, tween.t), e = u * u * (3 - 2 * u);
      cam.pos.lerpVectors(tween.from, s.pos, e); cam.pos.y += Math.sin(Math.PI * e) * tween.lift; cam.look.lerpVectors(tween.fromLook, s.look, e);
      if (u >= 1) tween = null;
    } else {
      const kp = 1 - Math.exp(-dt * 2.2), kl = 1 - Math.exp(-dt * 3.2);
      cam.pos.lerp(s.pos, kp); cam.look.lerp(s.look, kl);
    }
    if (performance.now() - lastInputAt > 9000) { const k = 1 - Math.exp(-dt * 0.8); user.yaw -= user.yaw * k; user.pitch -= user.pitch * k; user.zoom += (1 - user.zoom) * k * 0.6; }
    _dir.copy(cam.look).sub(cam.pos); const dist = _dir.length(); _dir.normalize();
    const p = _camP.copy(cam.look).addScaledVector(_dir, -dist * user.zoom);
    // the drone floats: a slow bob and drift
    p.x += Math.sin(t * 0.53) * 0.05; p.y += Math.sin(t * 0.71) * 0.045 + Math.sin(t * 1.9) * 0.008; p.z += Math.cos(t * 0.43) * 0.05;
    if (p.y < 0.9 && shotKey !== "map") p.y = 0.9;
    _dir.applyAxisAngle(UP, user.yaw); _right.crossVectors(_dir, UP).normalize(); _dir.applyAxisAngle(_right, user.pitch);
    p.y += shake * (Math.random() - 0.5) * 0.03; shake *= Math.exp(-dt * 8);
    camera.position.copy(p); _look.copy(p).addScaledVector(_dir, dist); _look.x += Math.sin(t * 0.37) * 0.03; _look.y += Math.sin(t * 0.29) * 0.02;
    camera.lookAt(_look);
    sky.position.copy(camera.position); cloudU.uCam.value.copy(camera.position);
    if (Q.shadows) { sun.target.position.copy(cam.look); sun.position.copy(cam.look).addScaledVector(sun.userData.dir || sunDir, 60); }
  }
  const pointers = new Map(); let pinchD = 0, dragged = 0;
  function pinchDist() { const p = Array.from(pointers.values()); return p.length < 2 ? 0 : Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y); }
  canvas.addEventListener("pointerdown", function (e) { pointers.set(e.pointerId, { x: e.clientX, y: e.clientY }); try { canvas.setPointerCapture(e.pointerId); } catch (err) {} lastInputAt = performance.now(); pinchD = pinchDist(); dragged = 0; });
  canvas.addEventListener("pointermove", function (e) {
    const p = pointers.get(e.pointerId); if (!p) return;
    const dx = e.clientX - p.x, dy = e.clientY - p.y; p.x = e.clientX; p.y = e.clientY; lastInputAt = performance.now(); dragged += Math.abs(dx) + Math.abs(dy);
    if (pointers.size === 1) { user.yaw = clamp(user.yaw - dx * 0.0045, -0.95, 0.95); user.pitch = clamp(user.pitch - dy * 0.0035, -0.35, 0.3); }
    else if (pointers.size === 2) { const d = pinchDist(); if (pinchD > 0 && d > 0) user.zoom = clamp(user.zoom * pinchD / d, 0.5, 1.8); pinchD = d; }
  });
  const up = function (e) { pointers.delete(e.pointerId); pinchD = pinchDist(); };
  canvas.addEventListener("pointerup", up); canvas.addEventListener("pointercancel", up);
  canvas.addEventListener("wheel", function (e) { e.preventDefault(); user.zoom = clamp(user.zoom * (1 + e.deltaY * 0.0012), 0.5, 1.8); lastInputAt = performance.now(); }, { passive: false });

  // the director: who the drone is on. THE LIVE DIRECTOR below owns the camera: a broadcast that never waits for a
  // tap; a pin (a chip, the map) holds it on one thing for a while and times out back to the broadcast.
  let focus = null, pinned = null;
  function director() { liveDirector(); }
  // a real moment the camera goes to: who, how long, and what kind (speak, lesson, carry) for the director
  function focusOn(actor, lead, seconds, kind) { if (!actor) return; focus = { actor: actor, start: simT, lead: lead, until: simT + seconds, kind: kind || "speak" }; renderCard(); }

  // ============================================================= THE HUD: bubbles, labels, chips, the caption
  const _v = new THREE.Vector3();
  const _scr = { x: 0, y: 0, ok: false };  // (one reused result: read it before the next call)
  function toScreen(p) { const v = _v.copy(p).project(camera); _scr.x = (v.x + 1) / 2 * window.innerWidth; _scr.y = (1 - v.y) / 2 * window.innerHeight; _scr.ok = v.z < 1 && v.z > -1; return _scr; }
  const bubbles = [];
  function speak(actor, memberId, text, tone, seconds) {
    if (!actor || !text) return;
    const i = bubbles.findIndex(function (b) { return b.actor === actor; }); if (i >= 0) { bubbles[i].el.remove(); bubbles.splice(i, 1); }
    while (bubbles.length >= 2) bubbles.shift().el.remove();
    const d = document.createElement("div"); d.className = "bubble" + (tone === "good" ? " good" : tone === "bad" ? " bad" : "");
    const s = document.createElement("small"); s.textContent = actor.name.toUpperCase() + " · " + nameOf(memberId);
    const p = document.createElement("span"); p.textContent = text;
    d.appendChild(s); d.appendChild(p); d.style.opacity = "0"; bubblesEl.appendChild(d);
    bubbles.push({ el: d, actor: actor, until: simT + (seconds || 8) });
  }
  function updateBubbles() {
    const Wd = window.innerWidth, Hg = window.innerHeight, top = 96, bottom = Hg - 150;
    for (let i = bubbles.length - 1; i >= 0; i--) {
      const b = bubbles[i];
      if (simT >= b.until) { b.el.remove(); bubbles.splice(i, 1); continue; }
      const s = toScreen(b.actor.headAt);
      const visible = s.ok && s.x > -30 && s.x < Wd + 30 && s.y > 30 && s.y < bottom + 60 && blocked(camera.position, b.actor.headAt) > 0.98;  // (not through a wall)
      b.el.style.opacity = visible ? "1" : "0";
      if (visible) { const bw = b.el.offsetWidth, bh = b.el.offsetHeight, left = clamp(s.x - 30, 8, Wd - bw - 8);
        b.el.style.left = left + "px"; b.el.style.top = clamp(s.y - bh - 14, top, bottom - bh) + "px"; b.el.style.setProperty("--tail", clamp(s.x - left - 10, 12, bw - 30) + "px"); }
    }
  }
  const labels = Object.keys(ROOMS).map(function (k) {
    const at = (LAMP_AT[k] || V3(0, 0, 0)).clone(); at.y += 2.2;
    const d = document.createElement("div"); d.className = "label"; d.textContent = ROOMS[k].title; d.style.opacity = "0"; labelsEl.appendChild(d); return { el: d, at: at };
  });
  let labelsShown = false;
  function updateLabels() {
    const show = shotKey === "map";
    if (!show && !labelsShown) return;  // (only the map shows them; nothing to do otherwise)
    labelsShown = show;
    for (let i = 0; i < labels.length; i++) { const l = labels[i], s = toScreen(l.at), ok = show && s.ok && s.x > 10 && s.x < window.innerWidth - 10 && s.y > 100 && s.y < window.innerHeight - 160;
      l.el.style.opacity = ok ? "1" : "0"; if (ok) { l.el.style.left = (s.x - l.el.offsetWidth / 2) + "px"; l.el.style.top = s.y + "px"; } }
  }
  function dropLabel(pnl, at) {
    const won = (pnl || 0) >= 0; dropEl.textContent = fmtSigned(pnl); dropEl.style.color = won ? "var(--good)" : "var(--bad)";
    dropEl.style.transition = "none"; dropEl.style.opacity = "1"; dropEl.style.transform = "translateY(0)";
    drop = { at: at.clone(), until: simT + 2.8 };
  }
  let drop = null;
  function updateDrop() {
    if (!drop) return; const left = drop.until - simT; if (left <= 0) { dropEl.style.opacity = "0"; drop = null; return; }
    const s = toScreen(drop.at); dropEl.style.left = (s.x - dropEl.offsetWidth / 2) + "px"; dropEl.style.top = (s.y - 40 - (2.8 - left) * 26) + "px"; dropEl.style.opacity = String(Math.min(1, left));
  }
  function statusDot(ids) { const i = document.createElement("i"); i.className = worstStatus(ids); return i; }
  function renderChips() {
    chips.textContent = "";
    const live = document.createElement("button"); live.appendChild(document.createTextNode("live")); live.className = pinned ? "" : "on live";
    live.onclick = goLive; chips.appendChild(live);
    Object.keys(CAST).forEach(function (k) {
      if (!actors[k]) return; const c = CAST[k], b = document.createElement("button");
      b.appendChild(statusDot(c.members)); b.appendChild(document.createTextNode(c.name)); b.className = pinned === k ? "on" : "";
      b.onclick = function () { togglePin(k); }; chips.appendChild(b);
    });
    [["observatory", ROOMS.observatory ? ROOMS.observatory.title : "The observatory"], ["map", "map"]].forEach(function (q) {
      const b = document.createElement("button"); if (q[0] === "observatory") b.appendChild(statusDot(ROOMS.observatory ? ROOMS.observatory.members : []));
      b.appendChild(document.createTextNode(q[1])); b.className = pinned === q[0] ? "on" : "";
      b.onclick = function () { togglePin(q[0]); }; chips.appendChild(b);
    });
  }
  function renderCard() {
    const room = card.querySelector(".room .name"), who = card.querySelector(".who"), rows = card.querySelector(".rows");
    rows.textContent = ""; who.textContent = "";
    let roomKey = null, actor = null;
    if (pinned && actors[pinned]) { actor = actors[pinned]; roomKey = actor.room; }
    else if (pinned === "observatory") roomKey = "observatory";
    else if (!pinned) { const s = liveSubject(); actor = s.actor; roomKey = s.room; }  // the broadcast's subject
    if (roomKey && !actor) actor = actors[Object.keys(actors).find(function (k) { return actors[k].homeRoom === roomKey; })] || null;
    if (actor || roomKey) {
      const spec = ROOMS[roomKey] || ROOMS[actor ? actor.homeRoom : ""] || null;
      room.textContent = (actor && actor.walking ? "ON THE WAY" : spec ? spec.title : "").toUpperCase();
      if (actor) { const c = CAST[actor.key]; who.appendChild(document.createTextNode(c.name + " · " + c.kind));
        const small = document.createElement("small"); small.textContent = "plays " + c.members.map(nameOf).join(", "); who.appendChild(small); }
      else if (spec) who.appendChild(document.createTextNode(spec.line));
      const ids = actor ? actor.members : spec ? spec.members : [];
      ids.slice(0, 3).forEach(function (id) {
        const m = members[id]; if (!m) return;
        const div = document.createElement("div"), a = document.createElement("span"), st = document.createElement("span");
        a.textContent = nameOf(id) + ": " + (m.doing || m.why || ""); st.className = "status " + m.status; st.textContent = m.status;
        div.appendChild(a); div.appendChild(st); rows.appendChild(div);
      });
    } else {
      room.textContent = shotKey === "map" ? "THE HEADQUARTERS" : "NIGHT SHIFT: SKYPORT"; who.appendChild(document.createTextNode("The team"));
      const counts = (data && data.team && data.team.counts) || {}, div = document.createElement("div"), sp = document.createElement("span");
      sp.textContent = Object.keys(counts).filter(function (k) { return counts[k]; }).map(function (k) { return counts[k] + " " + k; }).join(" · ");
      div.appendChild(sp); rows.appendChild(div);
    }
  }

  // ============================================================= THE DATA (the bot's own ledger, nothing else)
  let data = null, offline = false, lastOkAt = null, lastClosedKey = null, chatterAt = 0, chatterIdx = 0;
  const members = {}, lastEventTs = {};
  async function fetchPage() {
    const opts = { cache: "no-store", credentials: "same-origin" };
    let res = await fetch("api/page", opts);
    if (res.status === 401 && token) res = await fetch("api/page?token=" + encodeURIComponent(token), opts);
    if (res.status === 401) { setOffline("Locked: open the link that ends with ?token=…"); return null; }
    if (!res.ok) { setOffline("Cannot reach the bot's data (" + res.status + ")"); return null; }
    return res.json();
  }
  function setOffline(text) { offline = true; statusEl.textContent = text; statusEl.className = "bad"; body.classList.add("offline"); }
  function onEvent(memberId, ev) {
    const actor = actors[actorOf[memberId]]; if (!actor) return;
    const here = roomOf[memberId] || actor.homeRoom, i = PIPELINE.indexOf(memberId);
    let dest = i >= 0 && i + 1 < PIPELINE.length ? roomOf[PIPELINE[i + 1]] : null;
    if (!dest && here !== actor.homeRoom) dest = here;
    const lesson = memberId === "predict" && /^Lesson:/.test(String(ev.text || ""));
    if (lesson && actor.actor) {  // the Polymarket desk's lesson: Voss thinks it over, then says it
      oneShot(actor, "think", 3.4);
      actor.beats.push({ at: simT + 3.2, fn: function (a) { speak(a, memberId, ev.text, ev.tone, 10); } });
      actor.beats.sort(function (x, y) { return x.at - y.at; });
    } else {
      speak(actor, memberId, ev.text, ev.tone, 9);
      if (ev.tone === "bad") oneShot(actor, "worried");  // a bad-tone event worries its speaker (Rook too)
      else if (ev.tone === "good" && actor.key === "rook") oneShot(actor, "nod", 4.5);  // Rook nods at good news
    }
    const walks = dest && dest !== actor.homeRoom && actor.queue.length < 3;
    if (walks) actor.queue.push({ dest: dest, hold: 3.5 });
    focusOn(actor, 3.5, walks ? 8 : 10, lesson ? "lesson" : "speak");
  }
  function onClosed(t) {
    const jet = actors.jet; if (!jet) return;
    const pnl = t.pnl_usd, won = (pnl || 0) >= 0;
    speak(jet, "broker", (t.coin || "a trade") + ": " + (t.result ? t.result + " " : "") + fmtSigned(pnl), won ? "good" : "bad", 12);
    // Jet carries the cube to the vault; there he cheers only for a winning trade and shrugs at a losing one
    jet.queue.unshift({ dest: "vault", hold: 4.5, carry: won ? "gold" : "red", onArrive: function (a) {
      deliverCube(a, pnl);
      a.yawGoal = a.destYaw + Math.PI;  // the cube goes in through the hatch; he turns round to the walkway for it
      if (pnl > 0) oneShot(a, "cheer"); else if (pnl < 0) oneShot(a, "shrug");
      if (focus && focus.actor === a) focus.until = Math.max(focus.until, simT + (pnl > 0 ? 10 : 5));  // the camera stays for it
    } });
    focusOn(jet, 2.0, 8, "carry");
  }
  function chatter() {
    const on = liveActor();  // (the one on camera says what they are doing; otherwise whoever is in view)
    const ids = Object.keys(members).filter(function (id) { const a = actors[actorOf[id]]; if (!a || (on && a !== on)) return false; const s = toScreen(a.headAt);
      return s.ok && s.x > 0 && s.x < window.innerWidth && s.y > 60 && s.y < window.innerHeight - 140 && blocked(camera.position, a.headAt) > 0.98; });
    const working = ids.filter(function (id) { return members[id].status === "working"; });
    const pool = (working.length ? working : ids).filter(function (id) { const m = members[id]; return m.doing || (m.events && m.events.length) || m.why; });
    if (!pool.length) return;
    const id = pool[chatterIdx++ % pool.length], m = members[id];
    speak(actors[actorOf[id]], id, m.doing || ((m.events || [])[0] || {}).text || m.why, null, 8);
  }
  function apply(d) {
    const first = !data;
    offline = false; lastOkAt = Date.now(); body.classList.remove("offline");
    const mode = d.mode === "LIVE" ? "LIVE" : "PAPER";
    modeEl.textContent = mode; modeEl.className = "mode" + (mode === "LIVE" ? " live" : "");
    const money = d.money || {}, since = (money.since_start || {}).usd;
    moneyEl.textContent = fmtUsd(money.usd);
    sinceEl.textContent = since == null ? (money.label || "") : fmtSigned(since) + " since start";
    sinceEl.style.color = since == null ? "" : since >= 0 ? "var(--good)" : "var(--bad)";
    drawVaultSign(fmtUsd(money.usd), money.label || "", since == null ? null : since >= 0 ? "#58d68d" : "#ff6b61");
    ((d.team && d.team.members) || []).forEach(function (m) {
      members[m.id] = m;
      const ev = (m.events && m.events[0]) || null;
      if (ev && !first && ev.ts > (lastEventTs[m.id] || 0)) onEvent(m.id, ev);
      if (ev) lastEventTs[m.id] = ev.ts;
    });
    const desk = members.predict;
    if (desk && Array.isArray(desk.positions)) { drawBoard(desk); board.visible = true; } else board.visible = false;
    const nReal = desk ? Number(desk.open_real || 0) : 0;
    realBulbMat.emissiveIntensity = nReal > 0 ? 4 : 0; realHalo.material.opacity = nReal > 0 ? 0.9 : 0;
    const closed = ((d.trades || {}).closed || [])[0];
    if (closed) { const key = closed.coin + "|" + closed.closed_at; if (!first && lastClosedKey && key !== lastClosedKey) onClosed(closed); lastClosedKey = key; }
    const alerts = d.alerts || [];
    statusEl.textContent = alerts.length ? alerts[0].text : "Every word on screen is the bot's own data";
    statusEl.className = alerts.length && alerts[0].level === "bad" ? "bad" : "";
    townEl.textContent = (d.town && d.town.line) || "";
    data = d;
    updateLamps(); renderChips(); renderCard();
    if (first) chatterAt = simT + 6;
  }
  async function tick() {
    try { const d = await fetchPage(); if (d) apply(d); } catch (e) { setOffline("Cannot reach the bot right now"); }
    clockEl.textContent = lastOkAt ? "updated " + new Date(lastOkAt).toLocaleTimeString() : "";
  }

  // ============================================================= TIME OF DAY (the viewer's clock): blue hour, night, a pastel day
  const PAL = {
    night: { top: 0x0a0e30, mid: 0x262064, hor: 0x6b4a8e, below: 0x4a3a78, sun: 0x9a7ab8, stars: 1.0, hemi: 0.85, hsky: 0x7f78d6, sunI: 0.9, sunC: 0xb8a0ff, fog: 0x3a3070, prac: 1.35, exp: 1.12, el: 0.12 },
    blue: { top: 0x161a52, mid: 0x4d3f93, hor: 0xf2a07a, below: 0xa486c4, sun: 0xffb98a, stars: 0.7, hemi: 1.25, hsky: 0xb4a2ff, sunI: 2.6, sunC: 0xffb27c, fog: 0xb294c4, prac: 1.0, exp: 1.08, el: 0.085 },
    day: { top: 0x3a64c8, mid: 0x8aa2e6, hor: 0xffd0b4, below: 0xc7b4e0, sun: 0xfff0d8, stars: 0.0, hemi: 1.7, hsky: 0xd2dcff, sunI: 3.2, sunC: 0xfff1dc, fog: 0xc8bce0, prac: 0.6, exp: 1.0, el: 0.4 },
  };
  function tint() {
    const d = new Date(), h = d.getHours() + d.getMinutes() / 60;
    const day = clamp(Math.min((h - 8) / 1.5, (16.5 - h) / 1.5), 0, 1), night = clamp(Math.max(Math.min((h - 21) / 1.5, 1), Math.min((5.5 - h) / 1.5, 1)), 0, 1);
    const blue = Math.max(0, 1 - day - night);
    const mix = function (key) { return col(PAL.blue[key]).multiplyScalar(blue).add(col(PAL.day[key]).multiplyScalar(day)).add(col(PAL.night[key]).multiplyScalar(night)); };
    const num = function (key) { return PAL.blue[key] * blue + PAL.day[key] * day + PAL.night[key] * night; };
    skyU.uTop.value.copy(mix("top")); skyU.uMid.value.copy(mix("mid")); skyU.uHorizon.value.copy(mix("hor")); skyU.uBelow.value.copy(mix("below"));
    skyU.uSunCol.value.copy(mix("sun")); skyU.uStars.value = num("stars");
    const sd = V3(sunDir.x, num("el"), sunDir.z).normalize(); skyU.uSunDir.value.copy(sd); cloudU.uSunDir.value.copy(sd); sun.userData.dir = sd;
    if (!Q.shadows) sun.position.copy(sd).multiplyScalar(60);
    hemi.intensity = num("hemi"); hemi.color.copy(mix("hsky")); sun.intensity = num("sunI"); sun.color.copy(mix("sunC"));
    scene.fog.color.copy(mix("fog")); cloudU.uFar.value.copy(mix("fog")); renderer.toneMappingExposure = num("exp");
    cloudU.uLit.value.copy(col(0xffc7a6).lerp(col(0xfff1e6), day).lerp(col(0x8a78c8), night));
    cloudU.uShade.value.copy(col(0x7d64b4).lerp(col(0xa898d8), day).lerp(col(0x2e2660), night));
    Object.keys(practicals).forEach(function (k) { practicals[k].light.intensity = practicals[k].base * num("prac"); });
  }

  // ============================================================= RENDERING: bloom on capable screens, a quality governor
  let composer = null, bloom = null;
  if (!LITE) {
    try {
      const rt = new THREE.WebGLRenderTarget(W0, H0, { type: THREE.HalfFloatType, samples: Q.msaa });
      composer = new EffectComposer(renderer, rt);
      composer.addPass(new RenderPass(scene, camera));
      bloom = new UnrealBloomPass(new THREE.Vector2(Math.max(1, W0 / 2), Math.max(1, H0 / 2)), 0.6, 0.55, 0.82); bloom.enabled = Q.bloom; composer.addPass(bloom);
      composer.addPass(new OutputPass());
    } catch (e) { console.warn("world: no post-processing", e); composer = null; }
  }
  function resize() {
    const w = window.innerWidth, h = window.innerHeight, aspect = w / h;
    renderer.setPixelRatio(Q.dpr); renderer.setSize(w, h, false);
    camera.aspect = aspect; camera.fov = aspect >= 1 ? 55 : clamp(2 * Math.atan(Math.tan(THREE.MathUtils.degToRad(20)) / aspect) * 180 / Math.PI, 55, 75);
    camera.updateProjectionMatrix();
    if (composer) { composer.setPixelRatio(Q.dpr); composer.setSize(w, h); }
  }
  window.addEventListener("resize", resize);
  let fpsN = 0, fpsT = 0, governed = FULLQ || LITE;
  function trimDecor() {  // the last step down: the distant islands and the extra lantern copies go (the crew stays)
    let n = 0;
    (props.islands || []).forEach(function (q) { if (q.h.visible) { q.h.visible = false; n++; } });
    (placed.lantern || []).forEach(function (h, i) { if (i >= 4 && h.visible) { h.visible = false; n++; } });
    (placed.arch || []).forEach(function (h) { if (h.visible) { h.visible = false; n++; } });
    return n;
  }
  function govern(dt) {
    if (governed) return; fpsN += 1; fpsT += dt; if (fpsT < 5) return;
    const fps = fpsN / fpsT; fpsN = 0; fpsT = 0;
    if (fps >= 28) { if (loading.set >= loading.setN && loading.crew >= loading.crewN) governed = true; return; }
    if (bloom && bloom.enabled) { bloom.enabled = false; console.info("world: bloom off (" + fps.toFixed(0) + " fps)"); return; }
    if (Q.dpr > 1) { Q.dpr = 1; resizeNext = true; console.info("world: pixel ratio 1"); return; }  // (resized just before the next draw: no blank frame)
    if (Q.shadows) { Q.shadows = false; renderer.shadowMap.enabled = false; sun.castShadow = false; console.info("world: shadows off"); return; }
    if (trimDecor()) { console.info("world: fewer decorations"); return; }
    if (loading.set >= loading.setN && loading.crew >= loading.crewN) governed = true;
  }

  // ============================================================= AMBIENT LIFE (decorative: no words, no numbers)
  const tubeLen = props.parcels.len, _pm = new THREE.Matrix4(), _pp = new THREE.Vector3();
  function updateProps(dt) {
    props.holoDisc.rotation.y += dt * 0.08; props.holoMini.rotation.y -= dt * 0.05; props.holoMini.position.y = props.holoY + (0.258 + Math.sin(simT * 0.9) * 0.025) * props.holoK;
    props.holoDome.rotation.y += dt * 0.03; props.holoCards.rotation.y += dt * 0.12;
    const cards = props.holoCards.children, face = Math.atan2(camera.position.x, camera.position.z);
    for (let i = 0; i < cards.length; i++) { cards[i].position.y = (i % 2) * 0.12 + Math.sin(simT * 1.3 + i) * 0.03; cards[i].rotation.y = -props.holoCards.rotation.y + face; }
    if (props.telescope.visible) { props.telescope.rotation.y = OB2.yaw + Math.sin(simT * 0.04) * 0.7; props.telescopeTube.rotation.x = -0.75 + Math.sin(simT * 0.07) * 0.12; }
    if (props.telescopeModel) props.telescopeModel.rotation.y = props.telescopeModel.userData.yaw + Math.sin(simT * 0.04) * 0.45;
    if (props.airship.visible) {
      props.airship.position.y = 2.35 + Math.sin(simT * 0.6) * 0.08; props.airship.rotation.z = Math.sin(simT * 0.5) * 0.015; props.airship.rotation.y = Math.sin(simT * 0.2) * 0.03;
      for (let i = 0; i < props.propellers.length; i++) props.propellers[i].rotation.x += dt * 4;
    }
    if (props.airshipModel) { const m = props.airshipModel; m.position.y = m.userData.y + Math.sin(simT * 0.6) * 0.07; m.rotation.z = Math.sin(simT * 0.5) * 0.012; }
    if (props.islands) for (let i = 0; i < props.islands.length; i++) { const q = props.islands[i]; q.h.position.y = q.y + Math.sin(simT * 0.21 + q.ph) * 0.35; q.h.rotation.y += dt * 0.004; }
    if (props.lanternGlow) for (let i = 0; i < props.lanternGlow.length; i++) {  // the prop lanterns' halos fade near the lens too
      const s = props.lanternGlow[i]; s.getWorldPosition(_pp); s.material.opacity = 0.5 * smoothstep(_pp.distanceTo(camera.position), 1.6, 4.0); }
    rookEyeMat.color.setRGB(1, 0.42, 0.06).multiplyScalar(1.8 + Math.sin(simT * 1.7) * 0.55); rookEyeHalo.opacity = 0.36 + Math.sin(simT * 1.7) * 0.12;
    for (let i = 0; i < props.drones.length; i++) { const d = props.drones[i], a = simT * d.speed + d.phase;
      d.g.position.set(Math.cos(a) * d.r, d.y + Math.sin(simT * 0.9 + d.phase) * 0.3, Math.sin(a) * d.r * 0.8 + 1); d.g.rotation.y = -a; d.g.rotation.z = Math.sin(simT * 2 + d.phase) * 0.05; }
    for (let i = 0; i < props.parcels.n; i++) { const u = ((simT * 2.2 + i * tubeLen / props.parcels.n) % tubeLen) / tubeLen;
      tubeCurve.getPointAt(u, _pp); _pm.makeRotationY(simT * 2 + i); _pm.setPosition(_pp); props.parcels.im.setMatrixAt(i, _pm); }
    props.parcels.im.instanceMatrix.needsUpdate = true;
    for (let i = 0; i < screens.length; i++) { const s = screens[i]; s.mesh.material.color.setScalar(s.base * (0.92 + Math.sin(simT * 1.7 + s.phase) * 0.08)); }
    board.lookAt(camera.position.x, board.position.y, camera.position.z);
    board.material.opacity = smoothstep(camera.position.distanceTo(board.position), 2.0, 4.2);  // it never fills the lens
    const r = actors.rook; if (r && !r.actor && r.impact > 0.5) { const d = r.group.position.distanceTo(camera.position); if (d < 9) shake = Math.max(shake, (1 - d / 9) * r.impact); }
    ambientLife();
  }

  // ============================================================= THE LIVE DIRECTOR: an always-on broadcast
  // The owner's direction: the camera is live all the time, flying and cutting between what is happening right now,
  // like a film. A fresh event comes first (whoever speaks, the listeners in frame; a hand-off walk; Jet's carry to
  // the vault, the drop and the cheer or the shrug; a lesson at the table; a blocked or waiting member thinking),
  // then whoever works at a station, then the life of the place (the courtyard, the telescope, the bridge with the
  // islands behind, the dock and its airship, the kiosk). Every shot moves (a push-in, an orbit, a crane, a dolly, a
  // drift) and is one of a few named types; between shots the drone flies a safe way along the walkways (never over
  // the walls) or, about every third shot, cuts. Memory of what each subject and room last had on air, and from
  // which angle, keeps everyone on screen. Only real statuses and events choose the shots. The planner is pure (no
  // three.js, no DOM): tests/test_world3d.py runs the block between the >>> and <<< markers in Node. The only words
  // this section writes are the LIVE tag's fixed ones; the card under it shows the data's own words. The director
  // keeps to this section: it calls the page's camera, shots and blockers above, and changes none of them.
  // >>> live planner (pure)
  // the places the director films between the characters (the operator below gives each its rigs and a position),
  // the room each one shows (for coverage) and whether it is a wide establishing shot (never more than one in six)
  const LIVE_PLACES = [
    { id: "arrival", room: "table", wide: true }, { id: "overhead", room: "table", wide: true },
    { id: "courtyard", room: "table" }, { id: "bridge", room: null }, { id: "telescope", room: "observatory" },
    { id: "walkway", room: "dock" }, { id: "airship", room: "dock" }, { id: "kiosk", room: "dock" },
    { id: "vaultsign", room: "vault" }, { id: "shelves", room: "archive" }, { id: "bench", room: "workshop" },
    { id: "screens", room: "den" },
  ];
  // the shot types the director may pick, by what the subject is doing right now (the operator makes each real;
  // "station" is the room's own framing, the shots table above)
  const LIVE_GRAMMAR = {
    work: ["station", "closeup", "ots", "orbit", "low", "crane"], idle: ["closeup", "orbit", "low", "crane", "station"],
    think: ["closeup", "low", "orbit"], speak: ["closeup", "ots", "low"], lesson: ["ots", "closeup", "orbit"],
    walk: ["follow", "dolly"], carry: ["follow", "dolly"], visit: ["closeup", "ots", "orbit"], drop: ["low", "crane"],
    place: ["place"], wide: ["wide"],
  };
  // seconds (and metres): a shot holds at least minHold before another event or phase takes it (a fresh event cuts
  // into the rotation at once), an event shot is re-framed after maxHold, a character unseen for actorStarve or a
  // room unseen for roomStarve comes next, a wide at most once in wideEvery shots, a pin lasts pin; angles round a
  // character; a flight goes to a neighbour within flyRange (a hard cut, every third shot, goes anywhere); the plan
  // runs every step
  const LIVE_CFG = { minHold: 3, maxHold: 14, actorStarve: 105, roomStarve: 95, wideEvery: 6, pin: 25, angles: 6, flyRange: 17, step: 0.25 };
  function makePlanner(actorSpecs, placeSpecs, opts) {
    const o = opts || {}, cfg = {};
    Object.keys(LIVE_CFG).forEach(function (k) { cfg[k] = o[k] != null ? o[k] : LIVE_CFG[k]; });
    const rnd = o.random || Math.random, alias = o.alias || {};
    const subjects = [], byId = {}, roomSeen = {};
    function subject(spec, kind, n) {
      const s = { id: spec.id, kind: kind, room: spec.room || null, wide: !!spec.wide, x: spec.x || 0, z: spec.z || 0,
                  seen: kind === "actor" ? -1e9 : -90 * rnd(), shots: 0, angles: n, used: [], mask: 0, grammars: {} };
      for (let i = 0; i < n; i++) s.used.push(-1e9);
      subjects.push(s); byId[s.id] = s; if (s.room) roomSeen[s.room] = -1e9;
    }
    actorSpecs.forEach(function (a) { subject(a, "actor", cfg.angles); });
    placeSpecs.forEach(function (p) { subject(p, "place", p.angles || 3); });
    // the current shot (one object, mutated in place: the operator reads it every frame)
    const shot = { seq: 0, subject: "", kind: "", grammar: "", angle: 0, room: null, start: -1e9, hold: 0, hard: false,
                   event: false, phase: "", pinned: false };
    const pin = { id: null, until: -1e9 };
    let sinceWide = 1e3, sinceHard = 0, lastFocus = null, places = 0;
    function lru(s, list, now) {  // the shot type this subject has gone longest without (ties at random)
      let best = list[0], bestT = Infinity;
      for (let i = 0; i < list.length; i++) { const t = (s.grammars[list[i]] != null ? s.grammars[list[i]] : -1e9) + rnd() * 0.5;
        if (t < bestT) { bestT = t; best = list[i]; } }
      s.grammars[best] = now; return best;
    }
    function freshAngle(s, now) {  // the angle this subject has gone longest without: every angle before any repeats
      let best = 0, bestT = Infinity;
      for (let i = 0; i < s.angles; i++) { const t = s.used[i] + rnd() * 0.5; if (t < bestT) { bestT = t; best = i; } }
      s.used[best] = now; s.mask |= 1 << best; return best;
    }
    function begin(s, kind, list, hold, now, event, phase, hard, room, angle) {
      shot.seq += 1; shot.subject = s.id; shot.kind = kind; shot.grammar = lru(s, list, now);
      if (angle != null) { shot.angle = angle; s.used[angle] = now; s.mask |= 1 << angle; } else shot.angle = freshAngle(s, now);
      shot.room = room || null; shot.start = now; shot.hold = hold; shot.event = !!event; shot.phase = phase || "";
      shot.hard = !!hard; shot.pinned = !!pin.id; sinceHard = hard ? 0 : sinceHard + 1;
      s.seen = now; s.shots += 1; if (room && room in roomSeen) roomSeen[room] = now;
      sinceWide = s.wide ? 0 : sinceWide + 1; places = kind === "place" ? places + 1 : 0;
      return shot;
    }
    function pinnedNow(now) { if (pin.id && now >= pin.until) pin.id = null; return pin.id; }
    function focusOf(live, now) { const f = live.focus; return f && now < f.until && byId[f.actor] ? f : null; }
    function phaseOf(live, f) {  // what the event's character is doing right now decides the shot type
      const a = live.actors[f.actor];
      if (!a) return "speak";
      if (a.walking) return a.carrying ? "carry" : "walk";
      if (a.visiting) return f.kind === "carry" ? "drop" : "visit";
      return f.kind === "lesson" ? "lesson" : "speak";
    }
    function onEvent(f, now, live) {
      const phase = phaseOf(live, f), fresh = f.start !== lastFocus, held = now - shot.start;
      const onIt = shot.event && !fresh && shot.subject === f.actor && shot.phase === phase;
      if (onIt && held < cfg.maxHold) return shot;  // on it: hold while this phase of the event lasts
      if (shot.event && held < cfg.minHold) return shot;  // an event shot holds its minimum; the next phase waits
      lastFocus = f.start;
      const a = live.actors[f.actor];
      return begin(byId[f.actor], "event", LIVE_GRAMMAR[phase] || LIVE_GRAMMAR.speak,
                   Math.min(cfg.maxHold, Math.max(cfg.minHold + 2, f.until - now)), now, true, phase, fresh, a ? a.room : null);
    }
    function frame(s, now, live, hard) {  // the next shot of a subject: its type and hold by what it is doing
      const a = s.kind === "actor" ? live.actors[s.id] : null;
      let list = LIVE_GRAMMAR.place, hold = 6 + rnd() * 3;
      if (s.wide) { list = LIVE_GRAMMAR.wide; hold = 5 + rnd() * 2; }
      else if (a) {
        const k = a.walking ? (a.carrying ? "carry" : "walk") : a.visiting ? "visit" : a.thinking ? "think"
          : a.speaking ? "speak" : a.working ? "work" : "idle";
        list = LIVE_GRAMMAR[k]; hold = k === "work" ? 6 + rnd() * 4 : 5.5 + rnd() * 3;
      }
      return begin(s, s.kind, list, hold, now, false, "", hard, a ? a.room : s.room);
    }
    function rotate(now, live) {
      // the rotation: whoever has gone longest unseen, real work and a blocked or waiting member first, the places
      // between them; a room or a character starved of airtime jumps the queue; a flight (two in three shots) goes
      // to a neighbour, a hard cut anywhere; never the same subject twice running, rarely the same room
      const allowWide = sinceWide >= cfg.wideEvery - 1, flight = sinceHard < 2, cur = byId[shot.subject] || null;
      const cl = cur && cur.kind === "actor" ? live.actors[cur.id] : null;
      const cx = cl ? cl.x : cur ? cur.x : 0, cz = cl ? cl.z : cur ? cur.z : 0, curRoom = cl ? cl.room : cur ? cur.room : null;
      let best = null, bestScore = -Infinity;
      for (let i = 0; i < subjects.length; i++) {
        const s = subjects[i];
        if (s === cur || (s.wide && !allowWide)) continue;
        const a = s.kind === "actor" ? live.actors[s.id] : null, room = a ? a.room : s.room, age = Math.min(now - s.seen, 900);
        let score = age * (a ? (a.thinking ? 1.7 : a.working ? 1.5 : 1.0) : s.wide ? 0.45 : 0.6);
        if (a && (a.walking || a.visiting || a.speaking)) score += 25;
        if (!a && places >= 2) score -= 400;  // the crew between the places: never three places running
        if (room && room === curRoom) score -= 45;
        if (room && room in roomSeen && now - roomSeen[room] > cfg.roomStarve) score += 2000 + Math.min(900, now - roomSeen[room]);
        if (a && age > cfg.actorStarve) score += 1500 + age;
        if (flight && cur) { const x = a ? a.x : s.x, z = a ? a.z : s.z; if (Math.hypot(x - cx, z - cz) > cfg.flyRange) score -= 600; }
        score += rnd() * 8;
        if (score > bestScore) { bestScore = score; best = s; }
      }
      return best ? frame(best, now, live, !flight) : shot;
    }
    function plan(now, live) {
      // live: { actors: { id: { room, x, z, walking, carrying, speaking, working, thinking, visiting } },
      //         focus: { actor, kind, start, until } | null }
      const pid = pinnedNow(now), f = focusOf(live, now);
      if (!shot.seq && !pid && byId.arrival) return begin(byId.arrival, "place", LIVE_GRAMMAR.wide, 6 + rnd(), now, false, "", true, "table", 0);
      if (pid) {  // pinned: the camera stays on that subject, still moving round it; the map: the plan waits
        const s = byId[alias[pid] || pid];
        if (!s) { shot.pinned = true; return shot; }
        if (f && f.actor === s.id) return onEvent(f, now, live);
        if (shot.subject === s.id && shot.pinned && now - shot.start < (shot.event ? cfg.minHold : shot.hold)) return shot;
        return frame(s, now, live, false);
      }
      if (f) return onEvent(f, now, live);
      if (shot.seq && !shot.pinned && now - shot.start < shot.hold) return shot;
      return rotate(now, live);
    }
    return {
      shot: shot, subjects: subjects, roomSeen: roomSeen, cfg: cfg, plan: plan,
      pin: function (id, now) { pin.id = id; pin.until = now + cfg.pin; },
      unpin: function () { pin.id = null; },
      pinned: pinnedNow,
      pinLeft: function (now) { return pin.id ? Math.max(0, pin.until - now) : 0; },
      extend: function (seconds) { shot.hold += seconds; },  // the flight to a shot does not eat its hold
      cutHard: function () { shot.hard = true; sinceHard = 0; },  // the operator had to cut (no safe way to fly)
      anglesSeen: function (id) { let n = 0, m = byId[id] ? byId[id].mask : 0; while (m) { n += m & 1; m >>= 1; } return n; },
    };
  }
  // <<< live planner
  // ------------------------------------------------------------- the operator: the drone that makes each planned shot real
  // What the drone keeps out of besides the walls (already blockers): the furniture, the hero arches at the workshop,
  // den and observatory doors (their posts and lintels; the opening stays free to fly through), the lantern posts,
  // the moored airship. The flights also keep clear of the hologram over the mission table (flight-only: Voss
  // stands at its edge).
  const TABLE_HALF = HAS("missiontable") ? 0.66 : 1.78;
  blocker(VT2, 0.9, 1.3, -2.63, 0, 1.4, 1.3, 0.5); blocker(VT2, 0.2, 0.65, -0.62, 0, 1.1, 0.65, 0.45);
  blocker(DN2, 0, 0.75, -1.9, 0, 1.3, 0.75, 0.5); blocker(WS2, 0, 0.4, -0.62, 0, 1.2, 0.4, 0.5);
  blocker(WF, 0, 0.5, 0, 0, TABLE_HALF, 0.5, TABLE_HALF); blocker(AR2, -2.4, 1.4, -2.69, 0, 1.3, 1.4, 0.4); blocker(AR2, 2.4, 1.4, -2.69, 0, 1.3, 1.4, 0.4);
  blocker(WF, 23.5, 1.2, 5.5, 0, 0.75, 1.2, 1.45); blocker(WF, 24.5, 0.6, -2.2, 0, 0.35, 0.6, 0.3); blocker(OB2, 0.6, 1.2, -1.2, 0, 0.9, 1.2, 0.9);
  if (HAS("airship")) blocker(WF, 27.3, 1.3, -1.5, 0, 1.0, 1.6, 1.55);
  if (HAS("workbench")) blocker(WS2, -0.4, 1.05, -0.85, 0, 0.16, 0.22, 0.16);  // the bench lamp, at Pip's face height
  if (HAS("arch")) PLACE.arch.forEach(function (q) {
    const F = roomFrame(q.at.x, q.at.y, q.at.z, q.yaw);
    blocker(F, -1.08, 1.7, 0, 0, 0.2, 1.7, 0.38); blocker(F, 1.08, 1.7, 0, 0, 0.2, 1.7, 0.38); blocker(F, 0, 3.05, 0, 0, 1.28, 0.35, 0.38);
  });
  if (HAS("lantern")) LANTERN_SPOTS.forEach(function (q) { blocker(WF, q.x, 1.3, q.z, 0, 0.2, 1.3, 0.2); });
  const FLY_BLOCK = [];  // (the same oriented boxes as blockers)
  (function () { const m = new THREE.Matrix4().makeTranslation(0, 1.7, 0); FLY_BLOCK.push({ inv: m.invert(), half: V3(1.2, 1.25, 1.2) }); })();
  const _fo = new THREE.Vector3(), _fd = new THREE.Vector3(), _fr = new THREE.Ray(), _fb = new THREE.Box3(), _fh2 = new THREE.Vector3();
  function flyClear(a, b) {  // a straight stretch the drone can fly: no wall, furniture or hologram on it
    if (blocked(a, b) < 0.999) return false;
    const len = a.distanceTo(b); if (len < 1e-3) return true;
    for (let i = 0; i < FLY_BLOCK.length; i++) {
      const q = FLY_BLOCK[i]; _fo.copy(a).applyMatrix4(q.inv); _fd.copy(b).applyMatrix4(q.inv).sub(_fo).normalize(); _fr.set(_fo, _fd);
      _fb.min.copy(q.half).negate(); _fb.max.copy(q.half);
      if (_fr.intersectBox(_fb, _fh2) && _fh2.distanceTo(_fo) < len) return false;
    }
    return true;
  }
  function clearTo(from, to) {  // how far a look from a character reaches: the blockers and (seen from outside it) the hologram
    let f = blocked(from, to);
    const q = FLY_BLOCK[0], len = from.distanceTo(to); if (len < 1e-3) return f;
    _fo.copy(from).applyMatrix4(q.inv); _fb.min.copy(q.half).negate(); _fb.max.copy(q.half);
    if (_fb.containsPoint(_fo)) return f;  // (Voss at the table stands under it)
    _fd.copy(to).applyMatrix4(q.inv).sub(_fo).normalize(); _fr.set(_fo, _fd);
    if (_fr.intersectBox(_fb, _fh2)) f = Math.min(f, _fh2.distanceTo(_fo) / len);
    return f;
  }

  // the lens: each shot type has its focal length (35 mm equivalent on the long side of the screen, 24-35 mm; a
  // portrait phone a little wider), eased between shots; the page's own lens (resize) comes back for the map
  const LENS_MM = { station: 28, closeup: 35, ots: 30, low: 26, orbit: 28, crane: 26, follow: 28, dolly: 30, place: 28, wide: 24 };
  const lens = { fov: 0, set: -1, base: 55, from: 0, to: 0 };
  function fovFor(mm) {
    const tall = camera.aspect < 1, f = tall ? 24 + (mm - 24) * 0.6 : mm, half = Math.atan(18 / f);
    return 2 * Math.atan(tall ? Math.tan(half) : Math.tan(half) / camera.aspect) * 180 / Math.PI;
  }
  function setFov(f) { if (Math.abs(camera.fov - f) > 0.02) { camera.fov = f; camera.updateProjectionMatrix(); } lens.fov = f; lens.set = camera.fov; }
  // how far away a shot must be to fill `fill` of the screen's height with `size` metres of the subject
  function frameDist(size, fill, mm) { return size / (2 * Math.tan(fovFor(mm) * Math.PI / 360) * fill); }

  // the characters' eye height (a fraction of the drawn height: the faces are what the shots are about)
  const EYE = { voss: 0.72, pip: 0.68, nyx: 0.62, rook: 0.84, mote: 0.5, jet: 0.72 };
  function eyeOf(a, out) { out.copy(a.group.position); out.y += a.height * (EYE[a.key] || 0.7); return out; }
  // the angle slots round a character, from its facing (radians; the planner's angle picks one, the operator checks
  // it is clear and otherwise turns to the nearest clear side): three-quarter fronts for the faces, the shoulders
  // from behind for over-the-shoulder
  const OFF = { closeup: [0.45, -0.45, 0.85, -0.85, 0.2, -0.2], low: [0.6, -0.6, 1.05, -1.05, 0.3, -0.3],
                orbit: [1.25, -1.25, 0.95, -0.95, 1.5, -1.5], crane: [0.55, -0.55, 0.95, -0.95, 0.25, -0.25],
                ots: [2.75, -2.75, 2.5, -2.5, 2.92, -2.92] };
  const FALLBACK = { ots: "closeup", crane: "closeup", low: "closeup", orbit: "closeup", closeup: "station", station: "closeup" };
  // the shot in progress (one record, reused): its subject, type, side, the move's parameters, when its own move
  // starts (after the flight) and how long it lasts
  const RUN = { seq: -1, a: null, place: null, g: "", side: 1, az: 0, sweep: 0, d0: 2, d1: 2, y0: 1.6, y1: 1.6, ly: 0, lf: 0,
                mag: 0, t0: 0, dur: 6, mm: 28, clear: 1, lastT: 0, rig: null, wide: false, cutAt: -1e9 };
  const _eye = V3(0, 0, 0), _fw = V3(0, 0, 0), _sd = V3(0, 0, 0), _pt = V3(0, 0, 0), _lq = V3(0, 0, 0);
  const _live = { pos: V3(0, 0, 0), look: V3(0, 0, 0) }, _dst = { pos: V3(0, 0, 0), look: V3(0, 0, 0) };
  function ease(u) { return u <= 0 ? 0 : u >= 1 ? 1 : u * u * (3 - 2 * u); }
  function progressAt(t) { return ease((t - RUN.t0) / Math.max(1, RUN.dur)); }
  function posePos(a, az, e, out) {  // a shot round a character: the camera at progress e of the move
    const base = a.group.position, d = lerp(RUN.d0, RUN.d1, e), ang = az + RUN.sweep * e;
    return out.set(base.x + Math.sin(ang) * d, base.y + lerp(RUN.y0, RUN.y1, e), base.z + Math.cos(ang) * d);
  }
  function poseLook(a, out) {
    eyeOf(a, out); out.y += RUN.ly;
    if (RUN.lf) { out.x += Math.sin(a.yawS) * RUN.lf; out.z += Math.cos(a.yawS) * RUN.lf; }  // over the shoulder: what is in front of them
    return out;
  }
  function poseClear(a, az) {  // the whole move is clear of the walls and the furniture
    eyeOf(a, _eye);
    for (let k = 0; k <= 2; k++) { posePos(a, az, k / 2, _pt); if (clearTo(_eye, _pt) < 0.985) return false; }
    return true;
  }
  function shape(a, g, slot) {  // the move's parameters for a shot type on a character (metres above its floor)
    const h = a.height, eyeH = h * (EYE[a.key] || 0.7), mm = LENS_MM[g] || 28;
    RUN.g = g; RUN.mm = mm; RUN.sweep = 0; RUN.ly = 0; RUN.lf = 0;
    if (g === "closeup") {  // the face readable (1.2-2.7 m: a big one further), at the eye line, a slow push-in and drift
      const S = 0.75 * h + 0.3, d = clamp(frameDist(S, 0.8, mm), 1.2 + 0.15 * h, 2.2 + 0.2 * h);  // (a big one from further)
      RUN.d0 = d * 1.1; RUN.d1 = d * 0.9; RUN.y0 = RUN.y1 = eyeH + 0.04; RUN.sweep = 0.12 * RUN.side; RUN.ly = -0.08 * S;
    } else if (g === "low") {  // up at the character from knee height, sliding sideways
      const S = 1.1 * h + 0.25, d = clamp(frameDist(S, 0.85, mm), 1.6, 3.6);
      RUN.d0 = d; RUN.d1 = d * 0.94; RUN.y0 = 0.35 + 0.15 * h; RUN.y1 = RUN.y0 + 0.15; RUN.sweep = 0.22 * RUN.side; RUN.ly = -0.05 * h;
    } else if (g === "orbit") {  // a slow orbit, 30-60 degrees over the hold, towards the face
      const S = h + 0.6, d = clamp(frameDist(S, 0.8, mm), 1.9, 4.2), off = OFF.orbit[slot % 6];
      RUN.d0 = RUN.d1 = d; RUN.y0 = RUN.y1 = eyeH + 0.35 + 0.1 * h; RUN.sweep = -Math.sign(off) * (0.55 + 0.15 * (RUN.seq % 4)); RUN.ly = -0.22 * h;
      RUN.mag = Math.abs(RUN.sweep);
    } else if (g === "crane") {  // a crane down to the character (up and away on the odd angles)
      const S = 1.1 * h + 0.4, d = clamp(frameDist(S, 0.8, mm), 1.9, 4.0), hi = Math.min(eyeH + 0.95 + 0.2 * h, 3.6), lo = eyeH + 0.15 + 0.05 * h;
      RUN.d0 = d * 1.05; RUN.d1 = d * 0.92; RUN.y0 = slot % 2 ? lo : hi; RUN.y1 = slot % 2 ? hi : lo; RUN.sweep = 0.15 * RUN.side; RUN.ly = -0.15 * h;
    } else if (g === "ots") {  // over the shoulder: the bench, the screens or the table in front of them in frame
      const d = 0.75 + 0.35 * h;
      RUN.d0 = d * 1.08; RUN.d1 = d * 0.95; RUN.y0 = RUN.y1 = eyeH + 0.2 + 0.08 * h; RUN.sweep = 0.1 * RUN.side; RUN.ly = -0.12 - 0.1 * h; RUN.lf = 1.0 + 0.5 * h;
    }
  }
  function setupActor(a, ps) {
    let g = ps.grammar;
    if (a.walking) g = g === "dolly" ? "dolly" : "follow";
    else if (g === "follow" || g === "dolly") g = "closeup";
    for (let tries = 0; tries < 4; tries++) {
      if (g === "station" && (a.state !== "home" || !SHOTS[a.homeRoom])) { if (tries) break; g = "closeup"; }
      shape(a, g, ps.angle);
      if (g === "station") return;
      if (g === "follow" || g === "dolly") {  // a walker: the clearer side of them
        eyeOf(a, _eye); walkPose(a, _dst); const f = clearTo(_eye, _dst.pos); RUN.side = -RUN.side; walkPose(a, _dst);
        if (clearTo(_eye, _dst.pos) <= f) RUN.side = -RUN.side;
        return;
      }
      const offs = OFF[g], pref = offs[ps.angle % offs.length], ots = g === "ots", yaw = a.yawS;
      for (let shrink = 0; shrink < 2; shrink++) {
        // the slot, its mirror, then the nearest clear side (a face shot stays in front, over-the-shoulder behind)
        for (let k = 0; k < 18; k++) {
          const off = k === 0 ? pref : k === 1 ? -pref : pref + (k % 2 ? 1 : -1) * Math.ceil((k - 1) / 2) * 0.28;
          if (ots ? Math.abs(angleDiff(off, 0)) < 2.1 : Math.abs(off) > 1.8) continue;
          if (g === "orbit") RUN.sweep = -Math.sign(off) * RUN.mag;  // (an orbit turns towards the face)
          if (poseClear(a, yaw + off)) { RUN.az = yaw + off; return; }
        }
        RUN.d0 *= 0.8; RUN.d1 *= 0.8;
      }
      g = FALLBACK[g];
    }
    shape(a, "closeup", ps.angle); RUN.az = a.yawS + OFF.closeup[ps.angle % 6];  // (nothing clear: closer in, below)
  }
  function stationPose(a, e, out) {  // the room's own framing (the shots table above), with a slow push-in and drift
    const S = SHOTS[a.homeRoom];
    _lq.copy(S.look).sub(S.pos); _sd.set(_lq.z, 0, -_lq.x).normalize();
    out.pos.copy(S.pos).addScaledVector(_lq, 0.1 * e).addScaledVector(_sd, (e - 0.5) * 0.35 * RUN.side); out.look.copy(S.look);
  }
  function walkPose(a, out) {  // a walker: ahead and beside, facing back (follow), or beside, travelling along (dolly)
    const base = a.group.position, h = a.height, eyeH = h * (EYE[a.key] || 0.7);
    _fw.set(Math.sin(a.yawS), 0, Math.cos(a.yawS)); _sd.set(_fw.z, 0, -_fw.x); eyeOf(a, out.look);
    if (RUN.g === "follow") {
      out.pos.copy(base).addScaledVector(_fw, 1.45 + 0.5 * h).addScaledVector(_sd, RUN.side * (0.55 + 0.1 * h)); out.pos.y = base.y + Math.max(1.3, eyeH + 0.32 + 0.1 * h);
      out.look.addScaledVector(_fw, 0.1); out.look.y -= 0.08 * h;
    } else {
      out.pos.copy(base).addScaledVector(_sd, RUN.side * (1.9 + 0.4 * h)).addScaledVector(_fw, 0.6); out.pos.y = base.y + Math.max(1.35, eyeH + 0.35);  // (over the rails)
      out.look.addScaledVector(_fw, camera.aspect < 1 ? 0.15 : 0.45);  // (a narrow phone screen: the walker stays in frame)
    }
  }
  function actorPose(a, t, out) {
    const e = progressAt(t);
    if (RUN.g === "station") stationPose(a, e, out);
    else if (RUN.g === "follow" || RUN.g === "dolly") walkPose(a, out);
    else { posePos(a, RUN.az, e, out.pos); poseLook(a, out.look); }
    return out;
  }
  // the places' rigs: three per place, each a move from p0 to p1 (through pm for an arc) while the look goes l0 -> l1
  function rigOf(F, p0, l0, p1, l1, pm) {
    return { p0: F.at(p0[0], p0[1], p0[2]), l0: F.at(l0[0], l0[1], l0[2]), p1: F.at(p1[0], p1[1], p1[2]), l1: F.at(l1[0], l1[1], l1[2]), pm: pm ? F.at(pm[0], pm[1], pm[2]) : null };
  }
  const RIGS = {
    arrival: [null,  // the pack's arrival (the arrival shot above, drifting)
              rigOf(WF, [0.1, 1.5, 9.0], [0, 1.1, 0], [0.3, 3.2, 12.6], [0, 1.0, 0]),  // a crane up and back: the courtyard through the arch
              rigOf(WF, [0, 2.5, 19.6], [0, 1.2, 2.0], [0, 2.2, 15.4], [0, 1.1, 1.0])],  // from the arrival pad, down the bridge
    overhead: [rigOf(WF, [-4.0, 5.2, 7.0], [0, 1.0, -0.3], [-2.0, 3.0, 4.6], [0, 1.0, -0.3]),  // a crane down into the courtyard
               rigOf(WF, [2.4, 5.6, -7.6], [0, 1.0, 0.5], [1.8, 3.2, -4.8], [0, 1.0, 0.5]),  // from over the observatory steps
               rigOf(WF, [5.6, 4.6, 3.0], [0, 1.0, 0], [1.2, 4.2, 6.4], [0, 1.0, 0], [4.4, 4.5, 5.8])],  // a high orbit segment
    courtyard: [rigOf(WF, [3.2, 1.9, 3.0], [0, 1.0, -0.2], [-3.0, 1.9, 3.1], [0, 1.0, 0.2], [0.2, 1.95, 4.4]),  // an orbit round the table
                rigOf(WF, [4.6, 1.3, -1.2], [0, 1.1, 0], [3.0, 1.5, -0.6], [-0.4, 1.0, 0.2]),  // a low push-in from the den side
                rigOf(WF, [-2.5, 3.4, -5.0], [0, 1.0, 0], [-2.0, 2.0, -3.6], [0, 1.0, 0])],  // a crane from the steps
    bridge: [rigOf(WF, [-1.0, 2.2, 13.2], [14, 2.0, -6], [0.8, 2.0, 11.8], [12, 2.0, -6]),  // across the bridge, the den and the islands beyond
             rigOf(WF, [-0.6, 2.0, 13.5], [-0.3, 1.0, -0.5], [-0.6, 2.0, 9.0], [-0.45, 1.0, -0.2]),  // a dolly in, to the table
             rigOf(WF, [0.6, 1.0, 14.0], [0, 2.0, 4.0], [0.4, 1.2, 12.8], [-0.2, 1.6, 2.0])],  // low, the courtyard through the brass arch
    telescope: [rigOf(OB2, [-2.6, 2.1, 1.6], [0.6, 1.4, -1.2], [3.0, 2.1, 1.4], [0.6, 1.4, -1.2], [0.4, 2.2, 2.8]),  // an orbit
                rigOf(OB2, [-1.4, 3.6, 2.6], [0.6, 1.7, -1.2], [-1.0, 1.9, 1.6], [0.6, 1.3, -1.2]),  // a crane down
                rigOf(OB2, [2.2, 0.9, 0.6], [0.6, 2.0, -1.2], [1.6, 1.1, 0.2], [0.4, 2.3, -1.3])],  // low, up at the scope and the dome
    walkway: [rigOf(WF, [19.4, 1.85, 12.0], [21.0, 1.1, 2.0], [19.4, 1.85, 4.0], [23.0, 1.6, -1.5]),  // a dolly north to the dock
              rigOf(WF, [19.6, 1.8, -4.0], [20.5, 1.0, 5.0], [19.6, 1.8, 3.0], [22.5, 1.0, 5.5]),  // a dolly south to the kiosk
              rigOf(WF, [18.0, 4.0, 9.0], [19.5, 0.8, 3.0], [18.9, 2.2, 7.0], [21.5, 1.0, 1.5])],  // a crane over the walkway
    airship: [rigOf(WF, [20.4, 1.3, 1.2], [26.5, 2.4, -1.6], [21.4, 1.5, 0.2], [26.5, 2.4, -1.6]),  // a low push-in from the walkway
              rigOf(WF, [21.0, 2.4, -0.2], [26.5, 2.2, -1.5], [22.2, 2.3, -0.6], [26.8, 2.4, -1.5]),  // along the pier
              rigOf(WF, [22.3, 1.2, -0.2], [25.5, 1.8, -1.8], [22.0, 2.9, 0.8], [27.0, 2.6, -1.5])],  // a crane up from the console
    kiosk: [rigOf(WF, [19.6, 1.8, 2.7], [23.0, 1.0, 5.4], [20.8, 1.55, 3.6], [23.2, 1.1, 5.3]),  // a push-in to the counter
            rigOf(WF, [21.0, 1.7, 8.9], [23.2, 1.2, 5.0], [21.6, 1.6, 7.6], [23.2, 1.2, 5.0]),  // along the counter from the south
            rigOf(WF, [21.4, 1.35, 4.0], [23.3, 1.3, 5.2], [21.8, 1.4, 4.6], [23.3, 1.25, 5.6])],  // low over the counter top
    vaultsign: [rigOf(VT2, [1.9, 1.7, 2.2], [0.4, 1.3, -0.9], [1.4, 2.4, 1.0], [0.9, 3.3, -2.9]),  // a crane up from the desk to the sign
                rigOf(VT2, [-1.2, 2.3, 3.0], [0.9, 3.4, -2.9], [-0.6, 2.4, 1.6], [0.9, 3.4, -2.9]),  // a push from the door
                rigOf(VT2, [-1.6, 0.9, 1.4], [0.9, 2.2, -2.7], [-1.2, 1.1, 0.8], [0.9, 3.2, -2.9])],  // low, up at the door and the sign
    shelves: [rigOf(AR2, [-1.8, 1.7, 0.9], [-2.4, 1.6, -2.69], [1.8, 1.7, 0.9], [2.4, 1.6, -2.69]),  // a dolly across the shelves
              rigOf(AR2, [0.6, 1.5, 1.2], [-1.3, 0.8, -1.5], [0.1, 1.35, 0.4], [-1.3, 0.8, -1.5]),  // a push-in to the bell
              rigOf(AR2, [1.4, 3.6, 1.8], [-1.0, 1.2, -1.6], [0.8, 1.9, 1.0], [-1.4, 0.9, -1.5])],  // a crane down
    bench: [rigOf(WS2, [1.8, 1.4, 0.9], [0, 0.95, -0.7], [-1.6, 1.4, 0.9], [0, 0.95, -0.7], [0.2, 1.3, 1.5]),  // an orbit over the bench
            rigOf(WS2, [0.9, 1.6, 2.6], [0, 0.9, -0.7], [0.6, 1.35, 1.1], [0, 0.9, -0.7]),  // a push-in from the door
            rigOf(WS2, [-1.6, 3.5, 1.8], [0, 1.0, -0.8], [-1.0, 1.8, 1.0], [0, 1.0, -0.8])],  // a crane down
    screens: [rigOf(DN2, [2.2, 1.65, -0.4], [0, 1.2, -2.1], [-2.2, 1.65, -0.4], [0, 1.2, -2.1]),  // a dolly along the screens
              rigOf(DN2, [0.8, 1.7, 2.4], [0, 1.2, -2.0], [0.5, 1.5, 0.9], [0, 1.2, -2.0]),  // a push-in from the door
              rigOf(DN2, [-1.9, 1.0, -1.0], [0.4, 1.3, -2.0], [-1.4, 1.05, -0.6], [0.4, 1.3, -2.0])],  // low across the desk
  };
  function placePose(R, t, out) {
    const e = progressAt(t), v = R[PLANNER.shot.angle % R.length];
    if (!v) { const s = arrivalShot(t); out.pos.copy(s.pos).lerp(s.look, 0.08 * e); out.look.copy(s.look); return out; }  // (pushing in)
    const w = 1 - e;
    if (v.pm) out.pos.copy(v.p0).multiplyScalar(w * w).addScaledVector(v.pm, 2 * w * e).addScaledVector(v.p1, e * e);
    else out.pos.lerpVectors(v.p0, v.p1, e);
    out.look.lerpVectors(v.l0, v.l1, e);
    return out;
  }
  function shotPose(t, out) {  // the planned shot right now (its own move; still at its first frame during the flight)
    if (RUN.a) return actorPose(RUN.a, t, out);
    if (RUN.rig) return placePose(RUN.rig, t, out);
    const s = arrivalShot(t); out.pos.copy(s.pos); out.look.copy(s.look); return out;
  }

  // ------------------------------------------------------------- the flights between shots
  // The drone flies the cast's own walkways at drone height (through the doorways, up the observatory steps; the
  // places round the table left out), cut short wherever a straight line is clear, its corners rounded; it never
  // climbs over a wall. Where there is no safe way, or the way is long, the director cuts instead.
  const FLY_H = 2.05, FLY_MAX = 26;
  const CN = [], CN_AT = {};
  Object.keys(NAV).forEach(function (k) { if (k.indexOf("tb") === 0) return; CN_AT[k] = CN.length; CN.push({ p: NAV[k].p.clone().setY(NAV[k].p.y + FLY_H), edges: [] }); });
  Object.keys(CN_AT).forEach(function (k) { NAV[k].edges.forEach(function (e) { if (CN_AT[e] != null) CN[CN_AT[k]].edges.push(CN_AT[e]); }); });
  function hop(id, p, links) {  // a camera-only waypoint (open air: no one walks there)
    CN_AT[id] = CN.length; CN.push({ p: p, edges: [] });
    links.forEach(function (k) { if (CN_AT[k] == null) return; CN[CN_AT[id]].edges.push(CN_AT[k]); CN[CN_AT[k]].edges.push(CN_AT[id]); });
  }
  hop("c0", V3(7.4, FLY_H, 2.6), ["e45", "e340"]); hop("c1", V3(12.6, FLY_H, 3.6), ["c0", "vtX", "dnSo"]);  // beside the den and the vault
  const cnDist = new Float64Array(CN.length), cnPrev = new Int16Array(CN.length), cnDone = new Uint8Array(CN.length), cnRoute = [];
  function nearestNode(p) {  // the closest walkway point in plain view of p
    let best = -1, bd = Infinity;
    for (let i = 0; i < CN.length; i++) { const d = CN[i].p.distanceToSquared(p); if (d < bd && flyClear(p, CN[i].p)) { bd = d; best = i; } }
    return best;
  }
  function routeNodes(s, e) {  // the shortest walkway route (node indices into cnRoute), or false
    cnDist.fill(Infinity); cnPrev.fill(-1); cnDone.fill(0); cnDist[s] = 0;
    for (;;) {
      let u = -1, bu = Infinity; for (let i = 0; i < CN.length; i++) if (!cnDone[i] && cnDist[i] < bu) { bu = cnDist[i]; u = i; }
      if (u < 0 || u === e) break; cnDone[u] = 1;
      const ed = CN[u].edges;
      for (let j = 0; j < ed.length; j++) { const v = ed[j], d = bu + CN[u].p.distanceTo(CN[v].p); if (d < cnDist[v]) { cnDist[v] = d; cnPrev[v] = u; } }
    }
    if (cnDist[e] === Infinity) return false;
    cnRoute.length = 0; for (let v = e; v >= 0; v = cnPrev[v]) cnRoute.push(v); cnRoute.reverse(); return true;
  }
  const WP = [], FLY = { on: false, start: 0, dur: 2, len: 0, n: 0, pts: [], cum: new Float64Array(160), fromLook: V3(0, 0, 0), fov0: 55, i: 0, see: 1 };
  for (let i = 0; i < 40; i++) WP.push(V3(0, 0, 0));
  for (let i = 0; i < 160; i++) FLY.pts.push(V3(0, 0, 0));
  function addPt(p) { if (FLY.n < FLY.pts.length) FLY.pts[FLY.n++].copy(p); }
  function planFlight(from, to) {  // the way from the drone to the next shot, sampled into FLY.pts; false: cut instead
    let n = 0; WP[n++].copy(from);
    if (!flyClear(from, to)) {
      const s = nearestNode(from), e = nearestNode(to);
      if (s < 0 || e < 0 || !routeNodes(s, e)) return false;
      for (let i = 0; i < cnRoute.length && n < WP.length - 1; i++) WP[n++].copy(CN[cnRoute[i]].p);
    }
    WP[n++].copy(to);
    let out = 1, i = 0;  // string-pull: keep only the turns a straight line cannot skip
    while (i < n - 1) { let j = n - 1; while (j > i + 1 && !flyClear(WP[i], WP[j])) j--;
      if (j === i + 1 && !flyClear(WP[i], WP[j])) return false;
      WP[out++].copy(WP[j]); i = j; }
    n = out;
    let len = 0; for (let k = 1; k < n; k++) len += WP[k].distanceTo(WP[k - 1]);
    if (len > FLY_MAX) return false;
    // sample, the corners rounded (a quadratic curve within r of each turn)
    FLY.n = 0; addPt(WP[0]);
    for (let k = 1; k < n - 1; k++) {
      const a = WP[k - 1], c = WP[k], b = WP[k + 1], r = Math.min(1.3, 0.45 * c.distanceTo(a), 0.45 * c.distanceTo(b));
      _lq.copy(a).sub(c).setLength(r).add(c); _pt.copy(b).sub(c).setLength(r).add(c);  // where the curve leaves and rejoins the lines
      for (let m = 0; m <= 6; m++) { const u = m / 6, w = 1 - u;
        _eye.copy(_lq).multiplyScalar(w * w).addScaledVector(c, 2 * w * u).addScaledVector(_pt, u * u); addPt(_eye); }
    }
    addPt(WP[n - 1]);
    FLY.cum[0] = 0; for (let k = 1; k < FLY.n; k++) FLY.cum[k] = FLY.cum[k - 1] + FLY.pts[k].distanceTo(FLY.pts[k - 1]);
    FLY.len = FLY.cum[FLY.n - 1]; FLY.i = 0;
    return true;
  }
  function flyPoint(s, out) {  // the point s metres along the flight
    let i = Math.min(FLY.i, FLY.n - 2); while (i > 0 && FLY.cum[i] > s) i--; while (i < FLY.n - 2 && FLY.cum[i + 1] < s) i++;
    const seg = Math.max(1e-6, FLY.cum[i + 1] - FLY.cum[i]); FLY.i = i;
    return out.lerpVectors(FLY.pts[i], FLY.pts[i + 1], clamp((s - FLY.cum[i]) / seg, 0, 1));
  }
  function cruise(u) {  // speed up over the first third, cruise, slow down over the last third (distance 0..1)
    const a = 0.3;
    if (u < a) return u * u / (2 * a * (1 - a));
    if (u > 1 - a) return 1 - (1 - u) * (1 - u) / (2 * a * (1 - a));
    return (u - a / 2) / (1 - a);
  }
  const _ahead = V3(0, 0, 0), _fp = V3(0, 0, 0);
  function flyPose(t, dt, out) {  // during a flight: along the way, the look panning from the last subject to the next
    const u = clamp((t - FLY.start) / FLY.dur, 0, 1), s = cruise(u) * FLY.len;
    flyPoint(s, _fp);
    const k = FLY.i; flyPoint(Math.min(FLY.len, s + 3), _ahead); _ahead.y -= 0.35; FLY.i = k;
    // the pan from the last subject to the next stays at their height; while a wall hides it, the drone looks
    // where it flies instead (out holds the next shot: its look and its place take over at the end)
    _lq.copy(FLY.fromLook).lerp(out.look, ease(u));
    FLY.see += ((blocked(_fp, _lq) > 0.95 ? 1 : 0) - FLY.see) * (1 - Math.exp(-dt * 5));
    _ahead.lerp(_lq, FLY.see);
    out.look.lerp(_ahead, 1 - smoothstep(u, 0.7, 1));
    out.pos.lerp(_fp, 1 - smoothstep(u, 0.75, 1));  // (so a moving subject is met where it is)
    return u >= 1;
  }

  // ------------------------------------------------------------- the director: plan, then fly or cut, then film
  const PLACE_AT = {};
  const PLANNER = makePlanner(ACTOR_KEYS.map(function (k) { const p = actors[k].pos; return { id: k, room: actors[k].homeRoom, x: p.x, z: p.z }; }),
    LIVE_PLACES.map(function (p) { const R = RIGS[p.id], v = R[0] || R[1]; PLACE_AT[p.id] = p;
      return { id: p.id, room: p.room, wide: p.wide, x: v.l0.x, z: v.l0.z, angles: R.length }; }),
    { alias: { observatory: "telescope" } });
  const liveEl = el("live");
  // what the planner sees (filled every plan step, reused: nothing allocated)
  const LIVE_STATE = { actors: {}, focus: null }, LIVE_FOCUS = { actor: "", kind: "", start: 0, until: 0 };
  ACTOR_KEYS.forEach(function (k) { LIVE_STATE.actors[k] = { room: "", x: 0, z: 0, walking: false, carrying: false, speaking: false, working: false, thinking: false, visiting: false }; });
  function readLive() {
    for (let i = 0; i < ACTOR_KEYS.length; i++) {
      const a = actors[ACTOR_KEYS[i]], s = LIVE_STATE.actors[a.key], w = worstStatus(a.members);
      s.room = a.room; s.x = a.pos.x; s.z = a.pos.z; s.walking = a.walking; s.carrying = !!a.carrying; s.speaking = a.speaking;
      s.visiting = a.state === "visit"; s.working = a.st.working; s.thinking = a.state === "home" && (w === "blocked" || w === "waiting");
    }
    if (focus && simT < focus.until) {
      LIVE_FOCUS.actor = focus.actor.key; LIVE_FOCUS.kind = focus.kind || "speak"; LIVE_FOCUS.start = focus.start; LIVE_FOCUS.until = focus.until;
      LIVE_STATE.focus = LIVE_FOCUS;
    } else LIVE_STATE.focus = null;
  }
  function liveShot() { return _live; }  // (the drone already flies it: the camera follows it exactly)
  function startShot(reframe) {  // a new planned shot (or, reframe, the same subject's shot set up again: they set off)
    const ps = PLANNER.shot, a = actors[ps.subject] || null;
    RUN.seq = ps.seq; RUN.a = a; RUN.rig = a ? null : RIGS[ps.subject] || null; RUN.wide = !a && !!PLACE_AT[ps.subject] && !!PLACE_AT[ps.subject].wide;
    RUN.side = ps.angle % 2 ? -1 : 1; RUN.clear = 1; RUN.t0 = simT; RUN.dur = reframe ? Math.max(3, ps.start + ps.hold - simT) : ps.hold;
    if (a) setupActor(a, ps); else { RUN.g = RUN.wide ? "wide" : "place"; RUN.mm = LENS_MM[RUN.g]; }
    shotKey = "live"; shotFn = liveShot; tween = null;
    shotPose(simT, _dst);
    let hard = !reframe && (ps.hard || cam.pos.lengthSq() === 0);
    // (a fresh event right after a cut flies there instead: two cuts in a breath would flicker)
    if (hard && ps.event && simT - RUN.cutAt < 1.5 && cam.pos.lengthSq() > 0 && planFlight(cam.pos, _dst.pos)) hard = false;
    else if (!hard && !planFlight(cam.pos, _dst.pos)) { hard = true; if (!reframe) PLANNER.cutHard(); }
    if (hard) { FLY.on = false; cam.pos.copy(_dst.pos); cam.look.copy(_dst.look); setFov(fovFor(RUN.mm)); RUN.cutAt = simT; }
    else {
      FLY.on = true; FLY.start = simT; FLY.dur = clamp(0.9 + FLY.len / 7, 1.2, 4.0); FLY.fromLook.copy(cam.look);
      FLY.fov0 = lens.fov; FLY.see = 1; RUN.t0 = simT + FLY.dur; if (!reframe) PLANNER.extend(FLY.dur);
    }
    if (!reframe) renderCard();
  }
  let nextPlanAt = 0, lastFocusStart = -1;
  function liveDirector() {
    const dt = clamp(simT - RUN.lastT, 0, 0.1); RUN.lastT = simT;
    if (camera.fov !== lens.set) { lens.base = camera.fov; lens.fov = camera.fov; lens.set = camera.fov; }  // (resized)
    const p = PLANNER.pinned(simT); if (p !== pinned) { pinned = p; nextPlanAt = 0; renderChips(); renderCard(); }  // (a pin timed out)
    // an event's walk (a hand-off, Jet's carry) stays on air until they arrive (the arrival keeps it for the drop)
    if (focus && focus.actor.state === "out" && !focus.actor.ambient && focus.until < simT + 1) focus.until = simT + 1;
    if (focus && simT >= focus.until) focus = null;
    renderLive();
    if (pinned === "map") {  // the overview (the page's own map shot and lens)
      if (shotKey !== "map") { FLY.on = false; cut("map", mapShot); }
      setFov(lens.fov + (lens.base - lens.fov) * Math.min(1, dt * 3)); PLANNER.plan(simT, LIVE_STATE); return;
    }
    const fresh = !!focus && focus.start !== lastFocusStart;  // a fresh event is planned at once
    if (simT >= nextPlanAt || fresh || shotKey !== "live") {
      nextPlanAt = simT + PLANNER.cfg.step; if (focus) lastFocusStart = focus.start;
      readLive(); PLANNER.plan(simT, LIVE_STATE);
    }
    if (shotKey !== "live" || PLANNER.shot.seq !== RUN.seq) startShot(false);
    else if (RUN.a && RUN.a.walking && RUN.g !== "follow" && RUN.g !== "dolly" && !FLY.on) startShot(true);  // (they set off: follow)
    shotPose(simT, _live);
    if (RUN.a && RUN.g !== "station" && !FLY.on) {  // never through a wall or the furniture: if the subject moved behind one, come in closer
      eyeOf(RUN.a, _eye); const f = clearTo(_eye, _live.pos), want = f < 0.999 ? clamp(f - 0.1, 0.35, 1) : 1;
      RUN.clear += (want - RUN.clear) * (1 - Math.exp(-dt * (want < RUN.clear ? 9 : 2)));
      if (RUN.clear < 0.999) _live.pos.sub(_eye).multiplyScalar(RUN.clear).add(_eye);
      const floor = RUN.a.group.position.y + 0.45; if (_live.pos.y < floor) _live.pos.y = floor;
    }
    const target = fovFor(RUN.mm);
    if (FLY.on) {
      const u = clamp((simT - FLY.start) / FLY.dur, 0, 1);
      setFov(lerp(FLY.fov0, target, ease(u)));
      if (flyPose(simT, dt, _live)) FLY.on = false;
    } else setFov(lens.fov + (target - lens.fov) * Math.min(1, dt * 2.5));
    cam.pos.copy(_live.pos); cam.look.copy(_live.look);
  }
  function liveActor() { return pinned === "map" ? null : RUN.a; }  // who the broadcast is on (their words come up)
  // the card follows the broadcast: the subject (a character, or the room a place shows)
  const _subj = { actor: null, room: null };
  function liveSubject() {
    const ps = PLANNER.shot, a = actors[ps.subject];
    _subj.actor = a || null; _subj.room = a ? (a.walking ? null : a.room) : PLACE_AT[ps.subject] ? PLACE_AT[ps.subject].room : null;
    return _subj;
  }
  // the LIVE tag: its own words are fixed ("LIVE", "pinned · back to live in N s"); everything else on the card is data
  let liveShown = -2;  // (the seconds on the tag, -1 for LIVE: it is rewritten only when they change)
  function renderLive() {
    const n = pinned ? Math.ceil(PLANNER.pinLeft(simT)) : -1;
    if (n === liveShown) return;
    liveShown = n; liveEl.textContent = n < 0 ? "LIVE" : "pinned · back to live in " + n + " s"; liveEl.className = n < 0 ? "" : "pinned";
  }
  function togglePin(k) { if (pinned === k) PLANNER.unpin(); else PLANNER.pin(k, simT); pinned = PLANNER.pinned(simT); nextPlanAt = 0; renderChips(); renderCard(); renderLive(); }
  function goLive() { PLANNER.unpin(); pinned = null; nextPlanAt = 0; renderChips(); renderCard(); renderLive(); }
  liveEl.onclick = goLive;
  if (params.get("debug") === "1") window.__world = { planner: PLANNER, shot: PLANNER.shot, run: RUN, fly: FLY, cam: cam, camera: camera, state: LIVE_STATE, blockers: blockers,
    pinned: function () { return pinned; },
    force: function (subject, grammar, angle, hold, fly) {  // (the screenshot harness: film one subject in one way now)
      const s = PLANNER.shot; s.seq += 1; s.subject = subject; s.grammar = grammar; s.angle = angle || 0; s.start = simT; s.hold = hold || 30;
      s.hard = !fly; s.event = false; s.pinned = false;
      PLANNER.subjects.forEach(function (q) { if (q.id === subject) q.seen = simT; });
    } };

  // ============================================================= THE LOOP (paused while the tab is hidden)
  let simT = 0, last = performance.now(), raf = 0, started = false, resizeNext = false;
  function frame(now) {
    raf = 0;
    const dtRaw = Math.min(0.1, Math.max(0, (now - last) / 1000)); last = now;
    const dt = offline ? 0 : dtRaw;
    simT += dt; uTime.value = simT;
    if (data && !offline && simT >= chatterAt) { chatter(); chatterAt = simT + 12; }
    if (resizeNext) { resizeNext = false; resize(); }
    updateActors(dt); updateCube(dt); updateProps(dt); updateFades(dtRaw); director(); updateCamera(dtRaw, simT);
    updateBubbles(); updateLabels(); updateDrop();
    if (composer) composer.render(dtRaw); else renderer.render(scene, camera);
    govern(dtRaw);
    // the ~20 MB of models start downloading only once the drawn world is on screen
    if (!started) { started = true; setTimeout(function () { loadModels().catch(function (e) { console.warn("world: models stopped loading", e); }); }, 50); }
    if (document.visibilityState === "visible") raf = requestAnimationFrame(frame);
  }
  document.addEventListener("visibilitychange", function () { if (document.visibilityState === "visible" && !raf) { last = performance.now(); raf = requestAnimationFrame(frame); } });

  resize(); tint(); setInterval(tint, 60000);
  cut("arrival", arrivalShot);
  renderChips(); renderCard();
  boot.hidden = true;
  tick(); setInterval(function () { if (document.visibilityState === "visible") tick(); }, REFRESH_MS);
  raf = requestAnimationFrame(frame);
}
"""

_MODULE = _M_SETUP + _M_WORLD + _M_CAST + _M_LIFE


def _sha256_source(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii") + "'"


#: Sent with ``/world``: scripts from this server (three.js, its addons and the cast's modules), this exact inline
#: module and import map, and WebAssembly compilation for the meshopt decoder (``'wasm-unsafe-eval'`` allows
#: compiling WebAssembly only; JavaScript ``eval`` stays forbidden); this exact inline style; data and models only
#: from this server (``blob:``: the textures GLTFLoader unpacks from a model file in memory).
WORLD_CSP = (
    f"default-src 'none'; script-src 'self' 'wasm-unsafe-eval' {_sha256_source(_MODULE)} "
    f"{_sha256_source(_IMPORTMAP)}; "
    f"style-src {_sha256_source(_STYLE)}; connect-src 'self' blob:; img-src 'self' data: blob:; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def _json_block(value: object) -> str:
    """Strict JSON that cannot close its ``<script>`` block (``<``, ``>`` and ``&`` escaped as JSON, still JSON)."""
    return json.dumps(value, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_world_html(settings: Settings) -> str:
    """The complete world page (static; the module loads live data, three.js and any real models). No ledger data."""
    live = settings.is_live
    mode = "LIVE" if live else "PAPER"
    members = "".join(
        f'<span data-id="{html.escape(mid)}" data-name="{html.escape(name)}" data-role="{html.escape(role)}"></span>'
        for mid, name, role in MEMBERS
    )
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<meta name="color-scheme" content="dark">\n<meta name="theme-color" content="#1b1f4a">\n'
        '<meta name="robots" content="noindex, nofollow">\n<meta name="referrer" content="no-referrer">\n'
        '<meta name="apple-mobile-web-app-capable" content="yes">\n'
        f'<link rel="icon" href="data:,">\n<title>Night Shift: Skyport · {mode.lower()}</title>\n'
        f"<style>{_STYLE}</style>\n"
        f'<script type="importmap">{_IMPORTMAP}</script>\n</head>\n'
        f'<body data-refresh="{REFRESH_S}" data-pipeline="{",".join(PIPELINE)}">\n'
        '<canvas id="view"></canvas><div id="vignette"></div>\n'
        f'<header><b class="mode{" live" if live else ""}" id="mode">{mode}</b><a href="./">← the page</a>'
        '<a href="office">office</a>'
        '<span class="money"><b id="money">—</b><small id="since"></small><span id="clock"></span></span></header>\n'
        '<div id="foot"><span id="status">Loading the world…</span></div>\n'
        '<div id="town"></div>\n'
        f'<div id="members" hidden>{members}</div>\n'
        f'<script id="cast" type="application/json">{_json_block(WORLD_CAST)}</script>\n'
        f'<script id="rooms" type="application/json">{_json_block(WORLD_ROOMS)}</script>\n'
        f'<script id="models" type="application/json">{_json_block(models_on_disk())}</script>\n'
        '<div id="labels"></div>\n<div id="bubbles"></div>\n<div id="drop"></div>\n'
        '<div id="card"><div class="room"><b id="live">LIVE</b><span class="name">NIGHT SHIFT: SKYPORT</span></div>'
        '<div class="who">Loading…</div>'
        '<div class="rows"></div><span id="loading" hidden></span></div>\n'
        '<div id="chips"></div>\n'
        '<p id="boot">Loading the 3D world… It needs a browser with JavaScript modules and WebGL; '
        'the <a href="office">Office</a> page shows the same team as pictures.</p>\n'
        '<p id="honest">A visualisation of the bot\'s own ledger: every word is the bot\'s data; '
        "the world and its cast are drawings.</p>\n"
        f'<script type="module">{_MODULE}</script>\n</body>\n</html>\n'
    )
