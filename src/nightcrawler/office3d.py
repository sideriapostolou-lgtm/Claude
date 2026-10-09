"""The 3D town at ``/office3d``: the team at work as a small low-poly campus, drawn by three.js in the browser.

Seven pavilions stand in a ring round a courtyard, one per desk of the bot (the workshop, the analysis den, the
mission table, the courier dock, the vault, the archive and the observatory, the Coach's lab), and the six cast
members of :mod:`nightcrawler.office` live in them, each built from a handful of three.js primitives with a
silhouette you can tell apart on a phone: Pip the fox scout, Nyx the octopus analyst, Voss the owl director, Rook
the stone golem, Mote the archivist in a glass bell and Jet the courier robot. They idle at their desks, walk the
courtyard paths when a hand-off happens (a new event on a member: the actor walks to the office of the next member
in :data:`~nightcrawler.office.PIPELINE`), and Jet carries each closed trade to the vault, where a coin drops into
the safe. A status light over every pavilion shows its members' state (green working, amber waiting, red blocked,
grey idle); speech bubbles are HTML overlays pinned to the actor's head; the camera orbits slowly, flies to the
office of the member whose event just happened, and can be pinned with a name chip or moved by hand (drag, pinch).

Honesty rules (the same as the office's, non-negotiable):

* Every WORD on screen comes from ``/api/page`` (names, roles, status words, event text, money, the town line) or
  from the fixed cast descriptions in :data:`CAST3D` and :data:`OFFICES3D`, and is inserted as text only (never as
  markup). The sign on the safe says exactly ``money.label`` (e.g. "Paper money (pretend)") under ``money.usd``.
* Nothing is invented: no trade, profit or activity appears that the ledger did not report. Hand-off walks and the
  coin drop are triggered only by a new member event or a newly closed trade in the data.
* When the API cannot be reached, the page says so in plain words and the town freezes.
* A footer line says the world is a visualisation of the bot's own ledger.

No external network: three.js (:data:`THREE_VERSION`, from :data:`THREE_SOURCE`) is bundled in ``office_assets/``
and served at ``/office/assets/<name>`` from the :data:`ASSET_FILES` whitelist behind the dashboard token; the CSP
allows scripts from this origin plus the inline module by its hash only. The scene is built for phones: a few
hundred meshes, no shadows, the device pixel ratio capped at 2, the animation paused while the tab is hidden, and a
plain fallback line when WebGL is unavailable.

Pure and static like :mod:`nightcrawler.page`: :func:`render_office3d_html` never puts ledger data into the HTML.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
from pathlib import Path

from nightcrawler.config import Settings
from nightcrawler.office import PIPELINE
from nightcrawler.page import MEMBERS, REFRESH_S

__all__ = [
    "ASSET_FILES",
    "CAST3D",
    "OFFICE3D_CSP",
    "OFFICES3D",
    "THREE_SHA256",
    "THREE_SOURCE",
    "THREE_VERSION",
    "asset_bytes",
    "render_office3d_html",
]

#: The bundled three.js release (the ES module build, unmodified) and where it was downloaded from.
THREE_VERSION = "0.160.1"
THREE_SOURCE = f"https://cdnjs.cloudflare.com/ajax/libs/three.js/{THREE_VERSION}/three.module.min.js"
#: SHA-256 of the bundled file (identical on cdnjs and jsdelivr for this release); tests check it.
THREE_SHA256 = "3e690ac7d180b0aadf0891bea39eec643e29e2d3e75c99b18689518665f69ba6"

ASSET_DIR = Path(__file__).resolve().parent / "office_assets"
#: The only files ``/office/assets/<name>`` will ever serve (no listing, no traversal), with their media types.
ASSET_FILES: dict[str, str] = {"three.module.min.js": "application/javascript; charset=utf-8"}

#: Who plays whom: the actor's fixed description, the bot roles it speaks for and the pavilion it lives in.
CAST3D: dict[str, dict[str, object]] = {
    "pip": {
        "name": "Pip",
        "kind": "fox scout",
        "members": ["crawler"],
        "office": "workshop",
        "job": "gathers the raw material: brand-new coins",
    },
    "nyx": {
        "name": "Nyx",
        "kind": "octopus analyst",
        "members": ["cocoon", "radar", "strategy"],
        "office": "den",
        "job": "three arms, three screens: scam filter, danger check, the setup",
    },
    "voss": {
        "name": "Voss",
        "kind": "owl director",
        "members": ["judge", "predict"],
        "office": "table",
        "job": "reviews and challenges every setup: the AI judge and the Polymarket desk",
    },
    "rook": {
        "name": "Rook",
        "kind": "stone golem",
        "members": ["risk"],
        "office": "vault",
        "job": "sizes, limits, approvals; keeps the safe",
    },
    "mote": {
        "name": "Mote",
        "kind": "archivist in a bell",
        "members": ["receipts", "coach"],
        "office": "archive",
        "job": "every decision and fill on a tamper-proof chain; what the team has learned",
    },
    "jet": {
        "name": "Jet",
        "kind": "courier robot",
        "members": ["broker"],
        "office": "dock",
        "job": "places the trades and carries the money to the vault",
    },
}

#: The seven pavilions: ring slot (pipeline order round the courtyard), the members whose status light they carry,
#: colours, roof style and a fixed one-line description. Every member is in exactly one pavilion.
OFFICES3D: dict[str, dict[str, object]] = {
    "workshop": {
        "slot": 0,
        "title": "The workshop",
        "members": ["crawler"],
        "wall": "#b5562a",
        "roof": "#5a2e1a",
        "trim": "#e8c17a",
        "style": "pyramid",
        "line": "Where the raw material arrives: brand-new coins on the bench.",
    },
    "den": {
        "slot": 1,
        "title": "The analysis den",
        "members": ["cocoon", "strategy", "radar"],
        "wall": "#1f4e6b",
        "roof": "#2bbfb3",
        "trim": "#9fe7e0",
        "style": "dome",
        "line": "Three screens: the scam filter, the setup, the danger check.",
    },
    "table": {
        "slot": 2,
        "title": "The mission table",
        "members": ["judge", "predict"],
        "wall": "#3d2a5e",
        "roof": "#d8a953",
        "trim": "#c9a24f",
        "style": "tower",
        "line": "A glowing map on a round table: every setup is argued here.",
    },
    "dock": {
        "slot": 3,
        "title": "The courier dock",
        "members": ["broker"],
        "wall": "#3a3d44",
        "roof": "#e9b83a",
        "trim": "#e9b83a",
        "style": "shed",
        "line": "Parcels in, parcels out: the trades leave from here.",
    },
    "vault": {
        "slot": 4,
        "title": "The vault",
        "members": ["risk"],
        "wall": "#4b505a",
        "roof": "#2c2f36",
        "trim": "#8c93a0",
        "style": "vault",
        "line": "The safe holds the money card; the sign says what kind of money it is.",
    },
    "archive": {
        "slot": 5,
        "title": "The archive",
        "members": ["receipts"],
        "wall": "#46663f",
        "roof": "#8fb57a",
        "trim": "#d9c48a",
        "style": "flat",
        "line": "Every decision and fill, chained so nothing can be rewritten.",
    },
    "observatory": {
        "slot": 6,
        "title": "The observatory",
        "members": ["coach"],
        "wall": "#1b2140",
        "roof": "#b9c3d6",
        "trim": "#7f8bb3",
        "style": "observatory",
        "line": "The Coach's lab: what the team has learned, under the stars.",
    },
}


def asset_bytes(name: str) -> bytes | None:
    """The bundled asset for an allowed name, else None (unknown names are never looked up on disk)."""
    if name not in ASSET_FILES:
        return None
    try:
        return (ASSET_DIR / name).read_bytes()
    except OSError:
        return None


_STYLE = r"""
:root { color-scheme: dark; --fg: #f3ecdf; --dim: #c9bda6; --good: #58d68d; --bad: #ff6b61; --brass: #d8a953;
        --glass: rgba(16, 14, 24, .62); --glass2: rgba(16, 14, 24, .82); }
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; background: #0a0f24; color: var(--fg);
             font: 15px/1.4 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
body { overflow: hidden; }
#view { position: fixed; inset: 0; width: 100%; height: 100%; display: block; touch-action: none; }
#vignette { position: fixed; inset: 0; pointer-events: none;
            background: linear-gradient(to bottom, rgba(5,3,10,.5), rgba(0,0,0,0) 16%, rgba(0,0,0,0) 72%, rgba(5,3,10,.6)); }
header { position: fixed; top: 0; left: 0; right: 0; display: flex; align-items: center; gap: 10px;
         padding: calc(8px + env(safe-area-inset-top)) 14px 8px; pointer-events: none; }
header a, header .money { pointer-events: auto; }
header b.mode { font-size: 11px; letter-spacing: .14em; padding: 3px 9px; border-radius: 999px;
                background: rgba(60, 50, 90, .75); border: 1px solid rgba(216,169,83,.5); }
header b.mode.live { background: var(--bad); color: #fff; }
header a { color: var(--dim); text-decoration: none; font-size: 13px; }
header .money { margin-left: auto; text-align: right; font-variant-numeric: tabular-nums;
                background: var(--glass); padding: 4px 10px; border-radius: 10px; border: 1px solid rgba(216,169,83,.35); }
header .money b { font-size: 16px; }
header .money small { display: block; font-size: 11px; color: var(--dim); }
header .money #clock { font-size: 10px; color: var(--dim); display: block; }
#foot { position: fixed; left: 14px; right: 14px; top: calc(54px + env(safe-area-inset-top)); font-size: 11px;
        color: var(--dim); text-shadow: 0 1px 2px #000; pointer-events: none; display: flex; gap: 10px; }
#status { flex: 1 1 auto; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
#status.bad { color: var(--bad); }
#town { position: fixed; left: 14px; right: 14px; top: calc(72px + env(safe-area-inset-top)); font-size: 11px; line-height: 1.3;
        color: var(--dim); text-shadow: 0 1px 2px #000; pointer-events: none; max-height: 2.9em; overflow: hidden; }
.label { position: fixed; font-size: 11px; letter-spacing: .12em; text-transform: uppercase; font-weight: 700;
         text-shadow: 0 1px 3px #000, 0 0 8px rgba(0,0,0,.85); pointer-events: none; white-space: nowrap; transition: opacity .3s ease; }
#boot { position: fixed; left: 16px; right: 16px; top: 40%; text-align: center; font-size: 15px; color: var(--fg);
        background: var(--glass2); border: 1px solid rgba(216,169,83,.4); border-radius: 12px; padding: 14px; }
#boot.bad { border-color: var(--bad); }
#boot a { color: var(--brass); }
.bubble { position: fixed; max-width: min(74vw, 400px); background: #f8f3e6; color: #1d1a16; padding: 8px 12px;
          border-radius: 14px; border: 2px solid var(--brass); font-size: 14px; line-height: 1.35;
          box-shadow: 0 8px 30px rgba(0,0,0,.45); pointer-events: none; transition: opacity .3s ease; }
.bubble:after { content: ""; position: absolute; left: 22px; bottom: -11px; border: 10px solid transparent;
                border-top-color: var(--brass); border-bottom: 0; }
.bubble.good { border-color: var(--good); } .bubble.good:after { border-top-color: var(--good); }
.bubble.bad { border-color: var(--bad); } .bubble.bad:after { border-top-color: var(--bad); }
.bubble small { display: block; color: #6c6356; font-size: 11px; letter-spacing: .08em; margin-bottom: 2px; }
#drop { position: fixed; font-weight: 700; font-size: 20px; pointer-events: none; opacity: 0; text-shadow: 0 1px 3px #000;
        transition: transform 1.6s ease-out, opacity 1.6s ease-out; }
#card { position: fixed; left: 12px; right: 12px; bottom: calc(82px + env(safe-area-inset-bottom));
        background: var(--glass2); border: 1px solid rgba(216,169,83,.4); border-radius: 14px; padding: 10px 12px;
        backdrop-filter: blur(6px); }
#card .room { font-size: 11px; letter-spacing: .14em; color: var(--brass); }
#card .who { font-weight: 700; font-size: 16px; margin-top: 2px; }
#card .who small { font-weight: 400; color: var(--dim); margin-left: 6px; font-size: 12px; }
#card .line { color: var(--fg); margin-top: 4px; font-size: 14px; }
#card .rows { margin-top: 6px; font-size: 13px; color: var(--dim); }
#card .rows div { display: flex; justify-content: space-between; gap: 10px; align-items: center; }
#card .rows div span:first-child { flex: 1 1 auto; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.status { display: inline-block; font-size: 11px; padding: 1px 8px; border-radius: 999px; white-space: nowrap;
          background: rgba(255,255,255,.12); vertical-align: middle; }
.status.working { background: rgba(88,214,141,.25); color: var(--good); }
.status.blocked { background: rgba(255,107,97,.3); color: var(--bad); }
.status.idle, .status.waiting, .status.absent { color: var(--dim); }
#chips { position: fixed; left: 12px; right: 12px; bottom: calc(44px + env(safe-area-inset-bottom)); display: flex;
         gap: 6px; overflow-x: auto; scrollbar-width: none; }
#chips::-webkit-scrollbar { display: none; }
#chips button { flex: 0 0 auto; font: inherit; font-size: 12px; color: var(--fg); background: var(--glass);
                border: 1px solid rgba(216,169,83,.35); border-radius: 999px; padding: 5px 11px; cursor: pointer; min-height: 30px; }
#chips button.on { border-color: var(--brass); background: rgba(216,169,83,.25); }
#chips button i { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; background: #6c717c; }
#chips button i.working { background: var(--good); } #chips button i.blocked { background: var(--bad); }
#chips button i.waiting { background: #f5b133; }
#honest { position: fixed; left: 12px; right: 12px; bottom: calc(14px + env(safe-area-inset-bottom)); font-size: 10.5px;
          color: var(--dim); text-align: center; text-shadow: 0 1px 2px #000; pointer-events: none;
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
body.offline #view { filter: grayscale(.7) brightness(.7); }
"""

_MODULE = r"""
import * as THREE from "./office/assets/three.module.min.js";

const body = document.body;
const REFRESH_MS = Math.max(4000, 1000 * (parseInt(body.dataset.refresh, 10) || 15));
const PIPELINE = (body.dataset.pipeline || "").split(",").filter(Boolean);
const CAST = JSON.parse(document.getElementById("cast").textContent);
const OFFICES = JSON.parse(document.getElementById("offices").textContent);
const MEMBERS = Array.from(document.querySelectorAll("#members span")).map(function (s) {
  return { id: s.dataset.id, name: s.dataset.name, role: s.dataset.role };
});
const el = function (id) { return document.getElementById(id); };
const boot = el("boot"), statusEl = el("status"), clockEl = el("clock"), townEl = el("town");
const moneyEl = el("money"), sinceEl = el("since"), modeEl = el("mode");
const bubblesEl = el("bubbles"), dropEl = el("drop"), card = el("card"), chips = el("chips"), labelsEl = el("labels");
const canvas = el("view");
const params = new URLSearchParams(location.search);
let token = null;
if (params.has("token")) { token = params.get("token"); params.delete("token"); const q = params.toString();
  history.replaceState(null, "", location.pathname + (q ? "?" + q : "")); }

const nameOf = function (id) { const m = MEMBERS.find(function (x) { return x.id === id; }); return m ? m.name : id; };
const actorOf = {}, officeOf = {};
Object.keys(CAST).forEach(function (k) { CAST[k].members.forEach(function (m) { actorOf[m] = k; }); });
Object.keys(OFFICES).forEach(function (k) { OFFICES[k].members.forEach(function (m) { officeOf[m] = k; }); });
const clamp = THREE.MathUtils.clamp;
const TAU = Math.PI * 2;
function angleDiff(a, b) { return ((a - b + Math.PI) % TAU + TAU) % TAU - Math.PI; }
function hex(s) { return parseInt(String(s).slice(1), 16); }
function fmtUsd(v) { return v == null ? "—" : (v < 0 ? "−" : "") + "$" + Math.abs(v).toFixed(2); }
function fmtSigned(v) { return v == null ? "—" : (v >= 0 ? "+" : "−") + "$" + Math.abs(v).toFixed(2); }

function fail(text) { boot.hidden = false; boot.textContent = text; boot.className = "bad"; canvas.hidden = true; }

let renderer = null;
try { renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, powerPreference: "low-power" }); }
catch (e) { renderer = null; }
if (!renderer || !renderer.getContext()) {
  fail("This browser cannot draw the 3D town (no WebGL). The Office page shows the same team as pictures.");
} else {
  try { main(); } catch (e) { console.error(e); fail("The 3D town could not start in this browser. The Office page shows the same team as pictures."); }
}

function main() {
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;

  // ------------------------------------------------------------- the world
  const R = 12, RING_R = 8.2, W = 5.6, D = 4.4, H = 3.0;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0a0f24);
  scene.fog = new THREE.Fog(0x0a0f24, 46, 118);
  const camera = new THREE.PerspectiveCamera(52, 1, 0.5, 220);
  const hemi = new THREE.HemisphereLight(0xcfe3ff, 0x4a3b2a, 2.2);
  const sun = new THREE.DirectionalLight(0xfff0d8, 2.6);
  sun.position.set(18, 26, 12);
  scene.add(hemi, sun);

  const mats = new Map();
  function mat(color, extra) {
    if (extra) return new THREE.MeshLambertMaterial(Object.assign({ color: color }, extra));
    if (!mats.has(color)) mats.set(color, new THREE.MeshLambertMaterial({ color: color }));
    return mats.get(color);
  }
  function glow(color, k) { return { color: color, emissive: color, emissiveIntensity: k == null ? 0.9 : k }; }
  function mesh(geo, color, x, y, z, extra) { const m = new THREE.Mesh(geo, mat(color, extra)); m.position.set(x || 0, y || 0, z || 0); return m; }
  const box = function (w, h, d, c, x, y, z, extra) { return mesh(new THREE.BoxGeometry(w, h, d), c, x, y, z, extra); };
  const sph = function (r, c, x, y, z, extra) { return mesh(new THREE.SphereGeometry(r, 12, 9), c, x, y, z, extra); };
  const cyl = function (rt, rb, h, c, x, y, z, extra) { return mesh(new THREE.CylinderGeometry(rt, rb, h, 12), c, x, y, z, extra); };
  const cone = function (r, h, c, x, y, z, seg, extra) { return mesh(new THREE.ConeGeometry(r, h, seg || 12), c, x, y, z, extra); };
  const windowMats = [], lampMats = [];

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.lineTo(x + w - r, y); ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r); ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h); ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r); ctx.lineTo(x, y + r); ctx.quadraticCurveTo(x, y, x + r, y); ctx.closePath();
  }
  // A sign: a canvas texture on a sprite. draw(lines, accent) writes the lines as TEXT (fillText) only.
  function makeSign(w, h, sw, sh) {
    const c = document.createElement("canvas"); c.width = w; c.height = h;
    const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
    sp.scale.set(sw, sh, 1);
    sp.userData.draw = function (lines, accent) {
      const ctx = c.getContext("2d"); if (!ctx) return;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "rgba(14,12,22,0.88)"; roundRect(ctx, 5, 5, w - 10, h - 10, 24); ctx.fill();
      ctx.lineWidth = 7; ctx.strokeStyle = accent || "#d8a953"; roundRect(ctx, 5, 5, w - 10, h - 10, 24); ctx.stroke();
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      const used = lines.filter(function (ln) { return ln.text; });
      const total = used.reduce(function (s, ln) { return s + ln.size; }, 0) * 1.18;
      let y = h / 2 - total / 2;
      used.forEach(function (ln) {
        ctx.font = (ln.bold ? "bold " : "") + ln.size + "px ui-sans-serif, system-ui, sans-serif";
        ctx.fillStyle = ln.color || "#f3ecdf";
        ctx.fillText(ln.text, w / 2, y + ln.size * 0.62, w - 40);
        y += ln.size * 1.18;
      });
      tex.needsUpdate = true;
    };
    return sp;
  }
  const haloCanvas = document.createElement("canvas"); haloCanvas.width = haloCanvas.height = 64;
  (function () { const ctx = haloCanvas.getContext("2d"); if (!ctx) return; const g = ctx.createRadialGradient(32, 32, 2, 32, 32, 32);
    g.addColorStop(0, "rgba(255,255,255,0.9)"); g.addColorStop(0.35, "rgba(255,255,255,0.35)"); g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g; ctx.fillRect(0, 0, 64, 64); })();
  const haloTex = new THREE.CanvasTexture(haloCanvas);
  function halo(color, size) {
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: haloTex, color: color, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    sp.scale.set(size, size, 1); return sp;
  }

  // ground, courtyard, paths, fountain, lamps, trees
  scene.add(mesh(new THREE.CircleGeometry(150, 48), 0x3b7446).rotateX(-Math.PI / 2));
  scene.add(mesh(new THREE.CircleGeometry(RING_R + 1.0, 48), 0x8d877a, 0, 0.02, 0).rotateX(-Math.PI / 2));
  scene.add(mesh(new THREE.RingGeometry(RING_R - 0.75, RING_R + 0.75, 56), 0xbfb49c, 0, 0.04, 0).rotateX(-Math.PI / 2));
  scene.add(cyl(2.3, 2.6, 0.6, 0x9c968a, 0, 0.3, 0));
  const water = mesh(new THREE.CircleGeometry(2.05, 32), 0x3a7bd5, 0, 0.62, 0, { color: 0x3a7bd5, emissive: 0x2a5fb0, emissiveIntensity: 0.5, transparent: true, opacity: 0.85 });
  water.rotateX(-Math.PI / 2); scene.add(water);
  scene.add(cyl(0.32, 0.5, 1.5, 0x9c968a, 0, 1.35, 0)); scene.add(sph(0.5, 0x6fb3ff, 0, 2.35, 0, glow(0x6fb3ff, 0.4)));
  for (let i = 0; i < 4; i++) {
    const a = i * Math.PI / 2 + Math.PI / 4, x = 4.9 * Math.cos(a), z = 4.9 * Math.sin(a);
    scene.add(cyl(0.07, 0.11, 2.8, 0x33363f, x, 1.4, z));
    const lm = mat(0xffd27a, glow(0xffd27a, 1.0)); lampMats.push(lm);
    const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.28, 10, 8), lm); lamp.position.set(x, 2.95, z); scene.add(lamp);
    const hl = halo(0xffd27a, 2.0); hl.position.set(x, 2.95, z); scene.add(hl); lampMats.push(hl.material);
  }
  for (let i = 0; i < 3; i++) {
    const a = i * TAU / 3 + 0.6; const b = box(1.5, 0.12, 0.5, 0x7a5636, 5.9 * Math.cos(a), 0.5, 5.9 * Math.sin(a)); b.rotation.y = -a; scene.add(b);
    const legs = box(1.3, 0.4, 0.4, 0x4a3a2a, 5.9 * Math.cos(a), 0.22, 5.9 * Math.sin(a)); legs.rotation.y = -a; scene.add(legs);
  }
  function tree(x, z, kind, s) {
    const g = new THREE.Group(); g.position.set(x, 0, z); g.scale.setScalar(s || 1);
    g.add(cyl(0.16, 0.24, 1.3, 0x5a3b22, 0, 0.65, 0));
    if (kind === 0) g.add(cone(1.05, 2.4, 0x2d7a3f, 0, 2.3, 0, 8));
    else if (kind === 1) { const c = sph(1.05, 0x4c9a4a, 0, 2.2, 0); c.scale.set(1, 1.15, 1); g.add(c); }
    else { g.add(cone(1.2, 1.6, 0x2b6e3a, 0, 1.9, 0, 7)); g.add(cone(0.85, 1.4, 0x3b8a48, 0, 2.9, 0, 7)); }
    scene.add(g);
  }
  for (let i = 0; i < 7; i++) { const a = -Math.PI / 2 + (i + 0.5) * TAU / 7; tree(R * Math.cos(a), R * Math.sin(a), i % 3, 1.0); }
  for (let i = 0; i < 12; i++) { const a = i * TAU / 12 + 0.21 + Math.sin(i * 2.3) * 0.15, r = 17.5 + Math.abs(Math.sin(i * 1.7)) * 3.5;
    tree(r * Math.cos(a), r * Math.sin(a), (i + 1) % 3, 1.1 + Math.abs(Math.sin(i * 3.1)) * 0.5); }

  // ------------------------------------------------------------- pavilions
  const offices = {}, labels = [];
  const props = {
    workshop: function (g, o) {
      g.add(box(2.7, 0.12, 0.95, 0x8a5a2b, 0, 0.98, -0.4));
      [-1.2, 1.2].forEach(function (x) { g.add(box(0.12, 0.65, 0.8, 0x5a3b22, x, 0.62, -0.4)); });
      g.add(cyl(0.03, 0.03, 0.7, 0x33363f, -1.0, 1.4, -0.5)); g.add(cone(0.24, 0.26, 0xffd27a, -1.0, 1.75, -0.5, 10, glow(0xffd27a, 0.8)));
      [[-0.3, 0], [0.1, -0.1], [0.45, 0.12]].forEach(function (p) { g.add(cyl(0.13, 0.13, 0.04, 0xf0c04a, p[0], 1.06, -0.4 + p[1], glow(0xf0c04a, 0.25))); });
      g.add(cyl(0.09, 0.09, 0.7, 0xe8d9b5, 0.9, 1.1, -0.45).rotateZ(Math.PI / 2));
      g.add(box(0.75, 0.75, 0.75, 0x9c6b3c, 2.0, 0.68, 0.5)); g.add(box(0.55, 0.55, 0.55, 0xb07a44, 2.0, 1.33, 0.5));
      g.add(box(0.65, 0.65, 0.65, 0x9c6b3c, -2.05, 0.63, 0.3));
      g.add(box(1.7, 1.0, 0.06, 0x3a2a1e, 0.9, 2.05, -D / 2 + 0.18));
      [-0.5, -0.15, 0.2, 0.55].forEach(function (x) { g.add(box(0.08, 0.5, 0.06, 0xbfc5cc, 0.9 + x, 2.0, -D / 2 + 0.22)); });
    },
    den: function (g, o) {
      g.add(box(3.2, 0.1, 0.8, 0x24364a, 0, 0.98, -0.35));
      [-1.4, 1.4].forEach(function (x) { g.add(box(0.1, 0.65, 0.7, 0x1a2a3a, x, 0.63, -0.35)); });
      const colors = [0x2bd4c8, 0x56e39f, 0x5aa0ff];
      [-1.1, 0, 1.1].forEach(function (x, i) {
        const s = box(0.98, 0.66, 0.06, colors[i], x, 1.6, -0.5, glow(colors[i], 0.6)); s.rotation.y = -x * 0.3; s.rotation.x = -0.12; g.add(s); o.screens.push(s.material);
        g.add(cyl(0.04, 0.04, 0.3, 0x33363f, x, 1.18, -0.5)); g.add(cyl(0.18, 0.18, 0.03, 0x33363f, x, 1.04, -0.5));
      });
      g.add(box(2.6, 0.08, 0.4, 0x5a3b22, 0, 2.1, -D / 2 + 0.3));
      g.add(cyl(0.16, 0.12, 0.3, 0xb5562a, -0.9, 2.3, -D / 2 + 0.3)); g.add(sph(0.3, 0x3b8a48, -0.9, 2.65, -D / 2 + 0.3));
      g.add(box(0.5, 0.6, 0.3, 0x24364a, 0.9, 2.45, -D / 2 + 0.3));
    },
    table: function (g, o) {
      g.add(cyl(0.3, 0.5, 0.65, 0x2a1d3a, 0, 0.62, -0.2)); g.add(cyl(1.5, 1.5, 0.14, 0x3a2b26, 0, 0.98, -0.2));
      const map = mesh(new THREE.CircleGeometry(1.32, 28), 0x3a6fd6, 0, 1.06, -0.2, glow(0x3a6fd6, 0.75)); map.rotateX(-Math.PI / 2); g.add(map); o.screens.push(map.material);
      g.add(mesh(new THREE.TorusGeometry(1.42, 0.05, 8, 32), 0xd8a953, 0, 1.06, -0.2).rotateX(Math.PI / 2));
      [[0.4, 0.3], [-0.6, -0.4], [0.2, -0.7]].forEach(function (p) { g.add(cone(0.08, 0.26, 0xd8a953, p[0], 1.2, -0.2 + p[1], 8)); });
      [-1.9, 1.9].forEach(function (x) { g.add(cone(0.16, 0.26, 0xd8a953, x, 2.2, -D / 2 + 0.25, 8)); const lm = sph(0.14, 0xffd27a, x, 2.42, -D / 2 + 0.25, glow(0xffd27a, 0.9)); g.add(lm); lampMats.push(lm.material); });
      g.add(box(2.4, 1.3, 0.06, 0x241a38, 0, 2.05, -D / 2 + 0.18)); g.add(box(2.5, 0.06, 0.08, 0xd8a953, 0, 2.72, -D / 2 + 0.19)); g.add(box(2.5, 0.06, 0.08, 0xd8a953, 0, 1.38, -D / 2 + 0.19));
    },
    vault: function (g, o) {
      [1.2, 2.45].forEach(function (y) { g.add(box(W, 0.18, 0.08, 0x2c2f36, 0, y, -D / 2 + 0.17)); });
      g.add(box(1.7, 1.9, 1.3, 0x3b3f4a, 1.3, 1.25, -0.6));
      o.safeDoor = new THREE.MeshLambertMaterial({ color: 0x2a2d35, emissive: 0x000000, emissiveIntensity: 0 });
      const door = new THREE.Mesh(new THREE.CylinderGeometry(0.62, 0.62, 0.08, 20), o.safeDoor); door.rotation.x = Math.PI / 2; door.position.set(1.3, 1.3, 0.08); g.add(door);
      g.add(mesh(new THREE.TorusGeometry(0.2, 0.045, 8, 20), 0xd8a953, 1.3, 1.3, 0.14));
      g.add(box(0.36, 0.08, 0.08, 0xd8a953, 1.3, 1.02, 0.14)); g.add(box(0.08, 0.36, 0.08, 0xd8a953, 1.3, 1.3, 0.14));
      g.add(box(0.6, 0.06, 0.12, 0x15171c, 1.3, 2.23, -0.6));
      o.safeTop = g.localToWorld(new THREE.Vector3(1.3, 2.3, -0.6));
      o.sign = makeSign(640, 256, 3.6, 1.44); o.sign.position.set(1.3, 3.2, -0.6); g.add(o.sign);
      o.sign.userData.draw([{ text: "—", size: 84, bold: true }], "#d8a953");
      [[-1.9, 0.6], [-2.2, 1.6], [2.3, 0.7], [0.4, 2.6]].forEach(function (p) { g.add(box(0.5, 0.3, 0.1, 0x5a606b, p[0], p[1], -D / 2 + 0.19)); });
      o.deskX = -0.9;
    },
    archive: function (g, o) {
      [-1.9, 1.9].forEach(function (x) {
        g.add(box(1.3, 2.5, 0.5, 0x6b4a2b, x, 1.55, -D / 2 + 0.45));
        [0.9, 1.6, 2.3].forEach(function (y, i) { for (let k = 0; k < 4; k++) { const c = [0x8a3b2e, 0x2f5d8a, 0x9a7a2a, 0x3f6b3a][(k + i) % 4]; g.add(box(0.2, 0.42, 0.3, c, x - 0.45 + k * 0.3, y + 0.21, -D / 2 + 0.5)); } });
      });
      g.add(cyl(0.62, 0.72, 0.5, 0xc79a3c, 0, 0.55, -1.0)); o.deskY = 0.8;
      g.add(box(1.7, 0.1, 0.7, 0x6b4a2b, 0, 0.98, 0.1)); [-0.7, 0.7].forEach(function (x) { g.add(box(0.1, 0.65, 0.6, 0x5a3b22, x, 0.63, 0.1)); });
      g.add(cyl(0.07, 0.07, 0.5, 0xe8d9b5, -0.3, 1.1, 0.1).rotateZ(Math.PI / 2)); g.add(box(0.3, 0.05, 0.22, 0x8a3b2e, 0.45, 1.06, 0.1));
      g.add(cyl(0.03, 0.03, 0.6, 0x33363f, 0.0, 1.35, 0.3)); const lm = cone(0.2, 0.22, 0xffd27a, 0.0, 1.68, 0.3, 10, glow(0xffd27a, 0.7)); g.add(lm); lampMats.push(lm.material);
    },
    dock: function (g, o) {
      g.add(box(3.4, 0.5, 2.0, 0x4a4f58, 0, 0.55, -1.0)); o.deskY = 0.8;
      for (let k = 0; k < 7; k++) g.add(box(0.48, 0.1, 0.1, k % 2 ? 0x15171c : 0xe9b83a, -1.44 + k * 0.48, 0.82, 0.02));
      g.add(box(3.0, 2.3, 0.06, 0x2c2f36, 0, 1.75, -D / 2 + 0.18)); [1.0, 1.6, 2.2, 2.8].forEach(function (y) { g.add(box(3.0, 0.04, 0.08, 0x4a4f58, 0, y, -D / 2 + 0.19)); });
      [[-1.9, 0.6, 0.6, 0.4], [-1.9, 1.15, 0.5, 0.4], [1.95, 0.55, 0.7, 0.5], [1.95, 1.2, 0.55, 0.5], [2.0, 1.65, 0.35, 0.2]].forEach(function (p) {
        g.add(box(p[2], p[2], p[2], 0xb98a52, p[0], p[1], p[3])); g.add(box(p[2] + 0.02, 0.07, p[2] + 0.02, 0xeedfb8, p[0], p[1], p[3]));
      });
      g.add(cyl(0.05, 0.05, 2.0, 0x33363f, -2.5, 1.0 + 0.3, 1.6)); g.add(box(0.9, 0.55, 0.05, 0xe9b83a, -2.05, 2.1, 1.6));
    },
    observatory: function (g, o) {
      g.add(box(2.5, 1.5, 0.06, 0x111733, 0, 2.05, -D / 2 + 0.18));
      [[-0.9, 0.4], [-0.3, -0.3], [0.2, 0.5], [0.8, 0.1], [0.5, -0.45], [-0.6, -0.5]].forEach(function (p) { g.add(sph(0.045, 0xffffff, p[0], 2.05 + p[1], -D / 2 + 0.23, glow(0xffffff, 1.2))); });
      const tri = new THREE.Group(); tri.position.set(0, 0.3, -0.5);
      for (let k = 0; k < 3; k++) { const leg = cyl(0.04, 0.05, 1.5, 0x33363f, 0, 0.75, 0); leg.rotation.z = 0.35; const lg = new THREE.Group(); lg.rotation.y = k * TAU / 3; lg.add(leg); tri.add(lg); }
      g.add(tri);
      const tube = cyl(0.17, 0.26, 2.3, 0x9aa3b2, 0, 1.75, -0.5); tube.rotation.x = -0.9; tube.rotation.z = 0.35; g.add(tube);
      g.add(cyl(0.3, 0.3, 0.1, 0x2c2f36, 0, 1.72, -0.5));
      g.add(cyl(0.22, 0.26, 0.45, 0x6b4a2b, 1.6, 0.52, 0.2));
    },
  };

  function buildOffice(key, spec) {
    const angle = -Math.PI / 2 + spec.slot * TAU / 7;
    const g = new THREE.Group();
    g.position.set(R * Math.cos(angle), 0, R * Math.sin(angle));
    g.rotation.y = Math.atan2(-g.position.x, -g.position.z);
    scene.add(g); g.updateMatrixWorld(true);
    const wall = hex(spec.wall), roof = hex(spec.roof), trim = hex(spec.trim);
    const o = { key: key, spec: spec, angle: angle, group: g, pos: g.position.clone(), screens: [], deskY: 0.3, deskX: 0 };
    g.add(box(W + 0.8, 0.3, D + 0.8, 0x9a948a, 0, 0.15, 0));
    g.add(box(0.3, H, 0.3, trim, -W / 2, 0.3 + H / 2, D / 2)); g.add(box(0.3, H, 0.3, trim, W / 2, 0.3 + H / 2, D / 2));
    // the shell: walls, lintel, windows and roof (faded away when it stands between the camera and its subject)
    const sh = new THREE.Group(); g.add(sh);
    sh.add(box(W + 0.4, 0.16, 0.4, trim, 0, 0.3 + H, D / 2));
    sh.add(box(W, H, 0.3, wall, 0, 0.3 + H / 2, -D / 2));
    sh.add(box(0.3, 1.1, D, wall, -W / 2, 0.85, 0)); sh.add(box(0.3, 1.1, D, wall, W / 2, 0.85, 0));
    const win = mat(0xffe6a8, { color: 0xffe6a8, emissive: 0xffd27a, emissiveIntensity: 0 });
    [-1.7, 1.7].forEach(function (x) { const m = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.9, 0.1), win); m.position.set(x, 2.1, -D / 2 - 0.12); sh.add(m); });
    let top = 0.3 + H;
    if (spec.style === "pyramid") {
      const rg = new THREE.Group(); const c = mesh(new THREE.ConeGeometry(1, 1, 4), roof); c.rotation.y = Math.PI / 4; rg.add(c);
      rg.scale.set((W + 1.2) * 0.707, 1.8, (D + 1.2) * 0.707); rg.position.y = top + 0.9; sh.add(rg); top += 1.8;
    } else if (spec.style === "dome") {
      sh.add(box(W + 0.6, 0.3, D + 0.6, trim, 0, top + 0.15, 0)); top += 0.3;
      const d = mesh(new THREE.SphereGeometry(W / 2, 16, 8, 0, TAU, 0, Math.PI / 2), roof, 0, top, 0); d.scale.set(1, 0.7, D / W + 0.1); sh.add(d); top += W / 2 * 0.7;
    } else if (spec.style === "tower") {
      sh.add(box(W + 0.6, 0.3, D + 0.6, trim, 0, top + 0.15, 0)); top += 0.3;
      sh.add(box(W * 0.55, 2.0, D * 0.6, wall, 0, top + 1.0, -0.4));
      [-0.8, 0.8].forEach(function (x) { const m = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.8, 0.1), win); m.position.set(x, top + 1.1, -0.4 + D * 0.3 + 0.03); sh.add(m); });
      top += 2.0;
      const rg = new THREE.Group(); const c = mesh(new THREE.ConeGeometry(1, 1, 4), roof); c.rotation.y = Math.PI / 4; rg.add(c);
      rg.scale.set((W * 0.55 + 0.8) * 0.707, 1.5, (D * 0.6 + 0.8) * 0.707); rg.position.set(0, top + 0.75, -0.4); sh.add(rg); top += 1.5;
    } else if (spec.style === "vault") {
      sh.add(box(W + 1.0, 0.6, D + 1.0, roof, 0, top + 0.3, 0)); [-1, 1].forEach(function (k) { sh.add(box(0.2, 0.7, D + 1.1, 0x2c2f36, k * (W / 2 + 0.3), top + 0.35, 0)); }); top += 0.6;
      sh.add(box(1.2, 0.5, 1.2, 0x2c2f36, 1.3, top + 0.25, -0.6)); top += 0.5;
    } else if (spec.style === "flat") {
      sh.add(box(W + 0.8, 0.35, D + 0.8, roof, 0, top + 0.17, 0)); top += 0.35;
      [-1, 1].forEach(function (k) { sh.add(box(W + 0.8, 0.4, 0.2, trim, 0, top + 0.2, k * (D / 2 + 0.3))); sh.add(box(0.2, 0.4, D + 0.8, trim, k * (W / 2 + 0.3), top + 0.2, 0)); });
      sh.add(mesh(new THREE.CylinderGeometry(0.7, 0.7, 0.9, 8), 0xcfe9ff, 0, top + 0.6, -0.6, { color: 0xcfe9ff, transparent: true, opacity: 0.35 }));
      sh.add(cone(0.9, 0.5, trim, 0, top + 1.3, -0.6, 8)); top += 1.55;
    } else if (spec.style === "shed") {
      const slab = box(W + 1.2, 0.25, D + 1.6, roof, 0, top + 0.75, 0.2); slab.rotation.x = 0.2; sh.add(slab);
      sh.add(box(W + 0.4, 0.5, 0.3, wall, 0, top + 0.65, -D / 2)); top += 1.4;
    } else if (spec.style === "observatory") {
      sh.add(mesh(new THREE.CylinderGeometry(W / 2 - 0.1, W / 2 + 0.2, 0.9, 16), wall, 0, top + 0.45, -0.3)); top += 0.9;
      const d = mesh(new THREE.SphereGeometry(W / 2, 16, 10, 0, TAU, 0, Math.PI / 2), roof, 0, top, -0.3); d.scale.set(1, 0.85, 1); sh.add(d);
      sh.add(box(0.5, 2.0, 0.3, 0x2c2f36, 0, top + 1.3, -0.3 + W / 2 - 0.4).rotateX(-0.5));
      const tele = cyl(0.14, 0.2, 1.6, 0x9aa3b2, 0, top + 2.2, -0.3 + 0.9); tele.rotation.x = -0.75; sh.add(tele); top += W / 2 * 0.85;
    }
    o.shellMats = []; o.shellOpacity = 1; o.shell = sh;
    sh.traverse(function (m) {
      if (!m.isMesh) return;
      const isWindow = m.material === win;
      m.material = m.material.clone(); m.material.transparent = true; m.material.userData.base = m.material.opacity;
      o.shellMats.push(m.material); if (isWindow) windowMats.push(m.material);
    });
    // the status light on a pole (the title is an HTML label pinned above the roof)
    g.add(cyl(0.05, 0.05, 1.3, 0x3a3a44, W / 2 + 0.2, top + 0.65, D / 2 - 0.2));
    const lightMat = new THREE.MeshLambertMaterial({ color: 0x6c717c, emissive: 0x6c717c, emissiveIntensity: 0.9 });
    const light = new THREE.Mesh(new THREE.SphereGeometry(0.3, 12, 9), lightMat); light.position.set(W / 2 + 0.2, top + 1.4, D / 2 - 0.2); g.add(light);
    const hl = halo(0x6c717c, 1.8); hl.position.copy(light.position); hl.material.opacity = 0; g.add(hl);
    o.light = lightMat; o.halo = hl.material; o.top = top;
    o.labelAnchor = new THREE.Object3D(); o.labelAnchor.position.set(0, top + 0.9, 0); g.add(o.labelAnchor);
    const label = document.createElement("div"); label.className = "label"; label.textContent = spec.title; label.style.color = spec.trim;
    label.style.opacity = "0"; labelsEl.appendChild(label); labels.push({ el: label, office: o });
    if (props[key]) props[key](g, o);
    g.updateMatrixWorld(true);
    o.desk = g.localToWorld(new THREE.Vector3(o.deskX, o.deskY, -1.3));
    o.deskYaw = g.rotation.y;
    o.visitor = g.localToWorld(new THREE.Vector3(0.9, 0, D / 2 + 1.3));
    o.visitorYaw = g.rotation.y + Math.PI;
    o.door = g.localToWorld(new THREE.Vector3(0, 0, D / 2 + 1.8));
    o.door.y = 0;
    o.roofPos = g.localToWorld(new THREE.Vector3(0, top * 0.7, -0.5));
    offices[key] = o;
    // the path from the ring to the door
    const rp = box(1.4, 0.05, 1.3, 0xbfb49c, 0, 0.03, 0); rp.position.set(9.15 * Math.cos(angle), 0.03, 9.15 * Math.sin(angle)); rp.rotation.y = g.rotation.y; scene.add(rp);
  }
  Object.keys(OFFICES).forEach(function (k) { buildOffice(k, OFFICES[k]); });

  // ------------------------------------------------------------- the cast
  function shadow(g) { const s = mesh(new THREE.CircleGeometry(0.6, 16), 0x000000, 0, 0.02, 0, { color: 0x000000, transparent: true, opacity: 0.3 }); s.rotateX(-Math.PI / 2); g.add(s); }
  function anchor(g, y) { const a = new THREE.Object3D(); a.position.set(0, y, 0); g.add(a); return a; }
  const builders = {
    pip: function () {
      const g = new THREE.Group(), ORANGE = 0xe0772d, CREAM = 0xf6e7c9, DARK = 0x2b2320;
      shadow(g);
      [-0.17, 0.17].forEach(function (x) { g.add(cyl(0.09, 0.1, 0.5, DARK, x, 0.25, 0)); });
      const torso = sph(0.42, ORANGE, 0, 0.95, 0); torso.scale.set(1, 1.25, 0.85); g.add(torso);
      const chest = sph(0.3, CREAM, 0, 0.9, 0.2); chest.scale.set(0.9, 1.1, 0.6); g.add(chest);
      const head = sph(0.4, ORANGE, 0, 1.68, 0); g.add(head);
      const snout = cone(0.17, 0.42, CREAM, 0, 1.58, 0.45); snout.rotation.x = Math.PI / 2; g.add(snout);
      g.add(sph(0.06, DARK, 0, 1.58, 0.66));
      [-0.15, 0.15].forEach(function (x) { g.add(sph(0.055, DARK, x, 1.76, 0.34)); });
      [-0.22, 0.22].forEach(function (x) { const e = cone(0.13, 0.5, ORANGE, x, 2.2, -0.02); e.rotation.z = -x * 0.9; g.add(e);
        const tip = cone(0.06, 0.2, DARK, x * 1.12, 2.42, -0.02); tip.rotation.z = -x * 0.9; g.add(tip); });
      const tail = sph(0.22, ORANGE, 0.18, 0.75, -0.55); tail.scale.set(1, 1, 2.2); g.add(tail);
      g.add(sph(0.14, CREAM, 0.2, 0.75, -0.98));
      const armL = cyl(0.07, 0.07, 0.55, ORANGE, -0.42, 1.05, 0.15), armR = cyl(0.07, 0.07, 0.55, ORANGE, 0.42, 1.05, 0.15);
      armL.rotation.x = armR.rotation.x = -0.9; g.add(armL, armR);
      g.add(box(0.7, 0.1, 0.1, DARK, 0, 1.98, 0.22));
      [-0.15, 0.15].forEach(function (x) { g.add(cyl(0.1, 0.1, 0.08, 0x8fd3ff, x, 1.98, 0.3, glow(0x8fd3ff, 0.4)).rotateX(Math.PI / 2)); });
      return { group: g, head: anchor(g, 2.6), anim: function (t, working, walking) {
        tail.rotation.y = Math.sin(t * 4) * 0.35; const k = working ? Math.sin(t * 9) * 0.35 : walking ? Math.sin(t * 8) * 0.5 : 0;
        armL.rotation.x = -0.9 + k; armR.rotation.x = -0.9 - k; head.rotation.y = Math.sin(t * 0.8) * 0.15; } };
    },
    nyx: function () {
      const g = new THREE.Group(), PURPLE = 0x7d55c7, LILAC = 0xb79be6, DARK = 0x1d1530;
      shadow(g);
      const head = sph(0.66, PURPLE, 0, 1.3, 0); head.scale.set(1, 1.15, 1); g.add(head);
      [[-0.3, 1.7, 0.35], [0.35, 1.78, 0.2], [0.1, 1.95, -0.3], [-0.45, 1.5, -0.3]].forEach(function (p) { g.add(sph(0.11, LILAC, p[0], p[1], p[2])); });
      [-0.27, 0.27].forEach(function (x) { g.add(sph(0.17, 0xffffff, x, 1.42, 0.52)); g.add(sph(0.085, DARK, x, 1.42, 0.67)); });
      const tents = [];
      for (let i = 0; i < 8; i++) {
        const tg = new THREE.Group(); tg.position.set(0, 0.78, 0); tg.rotation.y = i * TAU / 8 + Math.PI / 8;
        const c = new THREE.Mesh(new THREE.CapsuleGeometry(0.11, 0.8, 4, 8), mat(PURPLE)); c.position.set(0.36, -0.38, 0); c.rotation.z = -0.6; tg.add(c);
        tg.add(sph(0.1, LILAC, 0.62, -0.76, 0)); g.add(tg); tents.push(tg);
      }
      return { group: g, head: anchor(g, 2.25), anim: function (t, working, walking) {
        tents.forEach(function (tg, i) { tg.rotation.x = Math.sin(t * 3 + i) * (walking ? 0.3 : 0.12); tg.rotation.z = (working && (i === 1 || i === 2 || i === 6)) ? Math.sin(t * 10 + i) * 0.25 : 0; });
        head.rotation.y = Math.sin(t * 0.7) * 0.2; head.position.y = 1.3 + Math.sin(t * 1.6) * 0.03; } };
    },
    voss: function () {
      const g = new THREE.Group(), BROWN = 0x6e4b2a, TAN = 0xd9b88a, AMBER = 0xf0b64a, DARK = 0x1a1511;
      shadow(g);
      const bodyM = sph(0.55, BROWN, 0, 1.0, 0); bodyM.scale.set(1, 1.25, 0.9); g.add(bodyM);
      const chest = sph(0.38, TAN, 0, 0.95, 0.28); chest.scale.set(0.9, 1.1, 0.6); g.add(chest);
      const head = sph(0.48, BROWN, 0, 1.8, 0); g.add(head);
      [-0.2, 0.2].forEach(function (x) {
        g.add(cyl(0.21, 0.21, 0.06, TAN, x, 1.86, 0.4).rotateX(Math.PI / 2)); g.add(sph(0.11, DARK, x, 1.86, 0.46)); g.add(sph(0.035, 0xffffff, x - 0.03, 1.9, 0.56));
        g.add(mesh(new THREE.TorusGeometry(0.24, 0.035, 8, 20), AMBER, x, 1.86, 0.48));
      });
      g.add(box(0.12, 0.03, 0.03, AMBER, 0, 1.86, 0.5));
      g.add(cone(0.09, 0.25, AMBER, 0, 1.68, 0.52).rotateX(Math.PI / 2));
      [-0.3, 0.3].forEach(function (x) { const tuft = cone(0.1, 0.35, BROWN, x, 2.3, 0); tuft.rotation.z = -x * 1.2; g.add(tuft); });
      const wingL = sph(0.2, BROWN, -0.58, 1.05, 0), wingR = sph(0.2, BROWN, 0.58, 1.05, 0); wingL.scale.set(0.5, 2.0, 1.4); wingR.scale.set(0.5, 2.0, 1.4); g.add(wingL, wingR);
      [-0.18, 0.18].forEach(function (x) { g.add(cone(0.08, 0.3, AMBER, x, 0.1, 0.25).rotateX(Math.PI / 2)); });
      return { group: g, head: anchor(g, 2.75), anim: function (t, working, walking) {
        head.rotation.y = Math.sin(t * 0.6) * 0.3; head.rotation.z = working ? Math.sin(t * 1.3) * 0.08 : 0;
        const f = working ? Math.sin(t * 7) * 0.2 : walking ? Math.sin(t * 9) * 0.35 : 0; wingL.rotation.z = -f; wingR.rotation.z = f; } };
    },
    rook: function () {
      const g = new THREE.Group(), STONE = 0x7f8794, STONE2 = 0x6a717c, MOSS = 0x5fa352, EYE = 0x79e8ff;
      shadow(g);
      [-0.32, 0.32].forEach(function (x) { g.add(box(0.4, 0.7, 0.45, STONE2, x, 0.35, 0)); });
      g.add(box(1.0, 0.5, 0.65, STONE2, 0, 0.95, 0)); g.add(box(1.25, 1.05, 0.75, STONE, 0, 1.75, 0));
      const arms = [-1, 1].map(function (s) { const ag = new THREE.Group(); ag.position.set(s * 0.9, 2.15, 0); ag.add(box(0.45, 0.45, 0.5, STONE, 0, 0, 0)); ag.add(box(0.36, 1.0, 0.4, STONE2, 0, -0.65, 0)); ag.add(box(0.4, 0.3, 0.42, STONE, 0, -1.25, 0)); g.add(ag); return ag; });
      const head = box(0.62, 0.58, 0.58, STONE, 0, 2.62, 0); g.add(head);
      [-0.16, 0.16].forEach(function (x) { g.add(box(0.14, 0.08, 0.05, EYE, x, 2.66, 0.3, glow(EYE, 1.2))); });
      g.add(box(0.3, 0.1, 0.3, MOSS, 0.55, 2.42, 0.1)); g.add(box(0.25, 0.08, 0.25, MOSS, -0.2, 2.94, -0.05)); g.add(box(0.22, 0.09, 0.2, MOSS, -0.9, 2.42, 0.15));
      g.add(box(0.08, 0.5, 0.05, EYE, 0, 1.75, 0.39, glow(EYE, 1.0)));
      return { group: g, head: anchor(g, 3.2), anim: function (t, working, walking) {
        g.children.forEach(function () {}); const s = Math.sin(t * 0.9) * 0.03; head.rotation.y = Math.sin(t * 0.5) * 0.2;
        arms[0].rotation.x = walking ? Math.sin(t * 6) * 0.5 : working ? -0.6 + Math.sin(t * 2.5) * 0.25 : s;
        arms[1].rotation.x = walking ? -Math.sin(t * 6) * 0.5 : working ? -0.2 : -s; } };
    },
    mote: function () {
      const g = new THREE.Group(), BRASS = 0xc79a3c, GLASS = 0xcfe9ff, GOLD = 0xffe08a;
      shadow(g);
      g.add(cyl(0.55, 0.6, 0.22, BRASS, 0, 0.11, 0));
      [[0.4, 0], [-0.4, 0], [0, 0.4], [0, -0.4]].forEach(function (p) { g.add(sph(0.08, 0x33363f, p[0], 0.08, p[1])); });
      const glassM = { color: GLASS, transparent: true, opacity: 0.25, depthWrite: false };
      g.add(cyl(0.46, 0.46, 0.95, GLASS, 0, 0.7, 0, glassM)); g.add(mesh(new THREE.SphereGeometry(0.46, 14, 8, 0, TAU, 0, Math.PI / 2), GLASS, 0, 1.17, 0, glassM));
      g.add(sph(0.08, BRASS, 0, 1.7, 0)); g.add(mesh(new THREE.TorusGeometry(0.46, 0.03, 8, 24), BRASS, 0, 1.17, 0).rotateX(Math.PI / 2));
      const mote = sph(0.17, GOLD, 0, 0.98, 0, glow(GOLD, 1.5)); g.add(mote);
      const robe = cone(0.15, 0.4, 0xf6e7c9, 0, 0.7, 0); g.add(robe);
      const hl = halo(GOLD, 1.3); hl.position.set(0, 0.98, 0); g.add(hl);
      const sparks = [0, 1].map(function (i) { const s = sph(0.04, GOLD, 0, 0.9, 0, glow(GOLD, 1.5)); g.add(s); return s; });
      const book = box(0.22, 0.03, 0.16, 0x8a3b2e, 0.26, 0.78, 0.1); g.add(book);
      return { group: g, head: anchor(g, 2.0), hover: true, anim: function (t, working, walking) {
        mote.position.y = 0.98 + Math.sin(t * 2) * 0.06; hl.position.y = mote.position.y; robe.position.y = mote.position.y - 0.28;
        sparks.forEach(function (s, i) { const a = t * 2.2 + i * Math.PI; s.position.set(Math.cos(a) * 0.3, 0.95 + Math.sin(t * 3 + i) * 0.12, Math.sin(a) * 0.3); });
        book.rotation.z = working ? 0.5 + Math.sin(t * 6) * 0.08 : 0; book.position.y = 0.78 + (working ? 0.12 : 0) + Math.sin(t * 2.5) * 0.03; } };
    },
    jet: function () {
      const g = new THREE.Group(), YELLOW = 0xe9b83a, DARK = 0x2a2d35, GREY = 0x9aa3b2, VISOR = 0x5ff0ff, KRAFT = 0xb98a52;
      shadow(g);
      const wheels = [-0.4, 0.4].map(function (x) { const w = cyl(0.26, 0.26, 0.18, DARK, x, 0.26, 0); w.rotation.z = Math.PI / 2; g.add(w); return w; });
      g.add(box(0.9, 0.08, 0.08, GREY, 0, 0.26, 0));
      g.add(box(0.85, 0.9, 0.62, YELLOW, 0, 0.98, 0)); g.add(box(0.87, 0.14, 0.64, DARK, 0, 0.78, 0)); g.add(box(0.5, 0.3, 0.05, DARK, 0, 1.12, 0.33));
      g.add(box(0.55, 0.5, 0.35, KRAFT, 0, 1.15, -0.5)); g.add(box(0.56, 0.06, 0.36, 0xeedfb8, 0, 1.15, -0.5));
      g.add(cyl(0.1, 0.1, 0.15, GREY, 0, 1.5, 0));
      const head = box(0.62, 0.45, 0.5, GREY, 0, 1.78, 0); g.add(head);
      g.add(box(0.46, 0.14, 0.05, VISOR, 0, 1.8, 0.26, glow(VISOR, 1.1)));
      g.add(cyl(0.025, 0.025, 0.4, GREY, 0.2, 2.2, 0)); const tip = sph(0.06, 0xff5f5a, 0.2, 2.42, 0, glow(0xff5f5a, 1.2)); g.add(tip);
      const arms = [-1, 1].map(function (s) { const ag = new THREE.Group(); ag.position.set(s * 0.52, 1.3, 0); ag.add(cyl(0.06, 0.06, 0.55, GREY, 0, -0.27, 0)); ag.add(box(0.14, 0.14, 0.14, DARK, 0, -0.58, 0)); g.add(ag); return ag; });
      return { group: g, head: anchor(g, 2.7), anim: function (t, working, walking) {
        tip.material.emissiveIntensity = Math.sin(t * 6) > 0 ? 1.3 : 0.2;
        if (walking) wheels.forEach(function (w) { w.rotation.x += 0.25; });
        const k = working ? Math.sin(t * 5) * 0.5 : walking ? -1.1 : 0; arms[0].rotation.x = k; arms[1].rotation.x = working ? -k : k;
        head.rotation.y = Math.sin(t * 0.9) * 0.2; } };
    },
  };
  const actors = {};
  Object.keys(CAST).forEach(function (k, i) {
    const spec = CAST[k], home = offices[spec.office]; if (!home || !builders[k]) return;
    const a = builders[k]();
    a.key = k; a.name = spec.name; a.members = spec.members; a.homeOffice = spec.office;
    a.deskPos = home.desk.clone(); a.deskYaw = home.deskYaw; a.pos = home.desk.clone(); a.yaw = home.deskYaw;
    a.state = "desk"; a.queue = []; a.path = null; a.seg = 0; a.speed = k === "rook" ? 2.4 : k === "mote" ? 2.6 : 3.2; a.phase = i * 1.7;
    a.group.position.copy(a.pos); a.group.rotation.y = a.yaw; scene.add(a.group);
    actors[k] = a;
  });
  function arcPoints(a0, a1) {
    const d = angleDiff(a1, a0), n = Math.max(1, Math.round(Math.abs(d) / 0.3)), out = [];
    for (let i = 1; i < n; i++) { const a = a0 + d * i / n; out.push(new THREE.Vector3(RING_R * Math.cos(a), 0, RING_R * Math.sin(a))); }
    return out;
  }
  function startWalk(a, action) {
    const dest = offices[action.dest], home = offices[a.homeOffice]; if (!dest || !home) return;
    const out = [a.pos.clone(), home.door.clone()];
    arcPoints(home.angle, dest.angle).forEach(function (p) { out.push(p); });
    out.push(dest.visitor.clone());
    a.path = out; a.returnPath = out.slice().reverse(); a.seg = 0; a.state = "out"; a.action = action;
  }
  function stepWalk(a, dt) {
    let left = a.speed * dt;
    while (left > 0 && a.seg < a.path.length - 1) {
      const to = a.path[a.seg + 1], d = to.distanceTo(a.pos);
      if (d <= left) { a.pos.copy(to); a.seg += 1; left -= d; }
      else { const dir = to.clone().sub(a.pos).normalize(); a.pos.addScaledVector(dir, left); left = 0;
        a.yaw += angleDiff(Math.atan2(dir.x, dir.z), a.yaw) * (1 - Math.exp(-dt * 9)); }
    }
    if (a.seg >= a.path.length - 1) {
      if (a.state === "out") { a.state = "visit"; a.visitUntil = simT + (a.action.hold || 2.5); a.yaw = offices[a.action.dest].visitorYaw; if (a.action.onArrive) a.action.onArrive(a); }
      else { a.state = "desk"; a.pos.copy(a.deskPos); a.yaw = a.deskYaw; }
    }
  }
  function updateActors(dt) {
    Object.keys(actors).forEach(function (k) {
      const a = actors[k];
      const working = a.members.some(function (id) { return (members[id] || {}).status === "working"; });
      if (a.state === "desk" && a.queue.length) startWalk(a, a.queue.shift());
      if (a.state === "out" || a.state === "back") stepWalk(a, dt);
      else if (a.state === "visit" && simT >= a.visitUntil) { a.state = "back"; a.path = a.returnPath; a.seg = 0; }
      const walking = a.state === "out" || a.state === "back";
      const bob = a.hover ? Math.sin(simT * 1.8 + a.phase) * 0.06 : a.state === "desk" || a.state === "visit" ? Math.sin(simT * 2.2 + a.phase) * 0.035 : Math.abs(Math.sin(simT * 9)) * 0.1;
      a.group.position.set(a.pos.x, a.pos.y + bob, a.pos.z); a.group.rotation.y = a.yaw;
      a.anim(simT + a.phase, working && !walking, walking);
    });
  }

  // the coin Jet drops into the safe
  const coinGood = new THREE.MeshLambertMaterial(glow(0xf0c04a, 0.9)), coinBad = new THREE.MeshLambertMaterial(glow(0xff6b61, 0.9));
  const coinMesh = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.3, 0.07, 18), coinGood); coinMesh.visible = false; scene.add(coinMesh);
  let coin = null, safeFlashUntil = 0;
  function dropCoin(pnl) {
    const vault = offices.vault, won = (pnl || 0) >= 0; if (!vault || !vault.safeTop) return;
    coinMesh.material = won ? coinGood : coinBad; coinMesh.visible = true;
    const from = actors.jet.head.getWorldPosition(new THREE.Vector3()); from.y -= 1.3;
    coin = { t: 0, from: from, to: vault.safeTop.clone() };
    vault.safeDoor.emissive.setHex(won ? 0x2ecc71 : 0xe74c3c); vault.safeDoor.emissiveIntensity = 0.9; safeFlashUntil = simT + 2.0;
    dropLabel(pnl, vault.safeTop);
  }
  function updateCoin(dt) {
    if (coin) { coin.t += dt / 0.9; const u = Math.min(1, coin.t), p = coin.from.clone().lerp(coin.to, u); p.y += Math.sin(u * Math.PI) * 1.5;
      coinMesh.position.copy(p); coinMesh.rotation.y += dt * 8; coinMesh.rotation.x += dt * 5; if (u >= 1) { coin = null; coinMesh.visible = false; } }
    if (safeFlashUntil && simT > safeFlashUntil) { offices.vault.safeDoor.emissiveIntensity = 0; safeFlashUntil = 0; }
    offices.den.screens.concat(offices.table.screens).forEach(function (m, i) { m.emissiveIntensity = 0.55 + Math.sin(simT * (3 + i) + i) * 0.12; });
    water.rotation.z += dt * 0.15;
  }
  const _v = new THREE.Vector3(), _w = new THREE.Vector3();
  function toScreen(p) { const v = _v.copy(p).project(camera); return { x: (v.x + 1) / 2 * window.innerWidth, y: (1 - v.y) / 2 * window.innerHeight, ok: v.z < 1 }; }
  function dropLabel(pnl, at) {
    const won = (pnl || 0) >= 0, s = toScreen(at);
    dropEl.textContent = fmtSigned(pnl); dropEl.style.color = won ? "var(--good)" : "var(--bad)";
    dropEl.style.left = (s.x - 30) + "px"; dropEl.style.top = (s.y - 30) + "px";
    dropEl.style.transition = "none"; dropEl.style.transform = "translateY(0)"; dropEl.style.opacity = "1";
    requestAnimationFrame(function () { dropEl.style.transition = "transform 1.6s ease-out, opacity 1.6s ease-out"; dropEl.style.transform = "translateY(" + (won ? -60 : 60) + "px)"; dropEl.style.opacity = "0"; });
  }

  // ------------------------------------------------------------- lights, day and night
  const LIGHT = { working: 0x4ade80, waiting: 0xf5b133, blocked: 0xff4d4d, idle: 0x6c717c, absent: 0x6c717c };
  const WORST = ["blocked", "working", "waiting", "idle"];
  function worstStatus(ids) { const st = ids.map(function (id) { return (members[id] || {}).status; }); for (let i = 0; i < WORST.length; i++) if (st.indexOf(WORST[i]) >= 0) return WORST[i]; return "idle"; }
  function updateLights() {
    Object.keys(offices).forEach(function (k) {
      const st = worstStatus(OFFICES[k].members), c = LIGHT[st] || LIGHT.idle;
      offices[k].light.color.setHex(c); offices[k].light.emissive.setHex(c); offices[k].light.emissiveIntensity = st === "idle" ? 0.25 : 0.9;
      offices[k].halo.color.setHex(c); offices[k].halo.opacity = st === "idle" ? 0 : 0.9;
    });
  }
  const SKY_D = new THREE.Color(0x9ec9ef), SKY_N = new THREE.Color(0x0a0f24), SKY_G = new THREE.Color(0xf2a35c), HEMI_D = new THREE.Color(0xcfe3ff), HEMI_N = new THREE.Color(0x3b4a7a);
  function daylight() { const d = new Date(), h = d.getHours() + d.getMinutes() / 60; return THREE.MathUtils.smoothstep(Math.cos((h - 13) / 12 * Math.PI), -0.3, 0.35); }
  function tint() {
    const k = daylight(), dusk = 1 - Math.abs(k - 0.5) * 2;
    const sky = SKY_N.clone().lerp(SKY_D, k).lerp(SKY_G, Math.max(0, dusk) * 0.35);
    scene.background.copy(sky); scene.fog.color.copy(sky);
    hemi.intensity = 0.8 + 1.6 * k; hemi.color.copy(HEMI_N).lerp(HEMI_D, k);
    sun.intensity = 0.5 + 2.4 * k; sun.color.set(0xfff0d8).lerp(new THREE.Color(0xffb070), Math.max(0, dusk) * 0.6);
    windowMats.forEach(function (m) { m.emissiveIntensity = 1.1 * (1 - k); });
    lampMats.forEach(function (m) { if (m.isSpriteMaterial) m.opacity = 0.05 + 0.9 * (1 - k); else m.emissiveIntensity = 0.1 + 1.2 * (1 - k); });
  }

  // ------------------------------------------------------------- camera
  const cam = { target: new THREE.Vector3(0, 1.2, 0), theta: 2.2, phi: 1.0, radius: 26 };
  const want = { target: new THREE.Vector3(0, 1.2, 0), theta: 2.2, phi: 1.0, radius: 26 };
  let focus = null, pinned = null, lastInputAt = -1e9, portrait = false;
  function fitRadius() { const t = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * camera.aspect; return clamp(17 / t + 1, 21, portrait ? 31 : 27); }
  function viewFor(key, follow) {
    const o = offices[key];
    const target = follow ? follow.group.position.clone().add(new THREE.Vector3(0, 1.3, 0)) : o.pos.clone().add(new THREE.Vector3(0, 1.7, 0));
    return { target: target, theta: o.angle + Math.PI + 0.3, phi: 1.02, radius: portrait ? 13 : 10.5 };
  }
  function setView(v) { want.target.copy(v.target); want.theta = v.theta; want.phi = v.phi; want.radius = v.radius; }
  function orbitView() { return { target: new THREE.Vector3(0, 1.2, 0), theta: want.theta, phi: portrait ? 0.92 : 1.0, radius: fitRadius() }; }
  function focusOn(key, follow, seconds) { if (!offices[key]) return; focus = { office: key, follow: follow, until: simT + seconds }; if (!pinned) setView(viewFor(key, follow)); renderCard(); }
  function pin(key) { pinned = pinned === key ? null : key; setView(pinned ? viewFor(pinned, null) : orbitView()); renderChips(); renderCard(); }
  function updateCamera(dt) {
    const now = performance.now();
    if (focus && simT >= focus.until) { focus = null; if (!pinned) setView(orbitView()); renderCard(); }
    if (pinned) want.target.copy(viewFor(pinned, null).target);
    else if (focus) want.target.copy(viewFor(focus.office, focus.follow).target);
    else if (now - lastInputAt > 6000 && !offline) want.theta += dt * 0.07;
    const k = 1 - Math.exp(-dt * 2.4);
    cam.target.lerp(want.target, k); cam.theta += angleDiff(want.theta, cam.theta) * k; cam.phi += (want.phi - cam.phi) * k; cam.radius += (want.radius - cam.radius) * k;
    const sp = Math.sin(cam.phi);
    camera.position.set(cam.target.x + cam.radius * sp * Math.cos(cam.theta), cam.target.y + cam.radius * Math.cos(cam.phi), cam.target.z + cam.radius * sp * Math.sin(cam.theta));
    camera.lookAt(cam.target);
    // the dollhouse cut-away: a shell between the camera and its subject, or the shell the camera is looking into
    const look = _v.copy(cam.target).sub(camera.position), dLook = look.length(), k2 = 1 - Math.exp(-dt * 4);
    const open = pinned || (focus && focus.office) || null;
    look.normalize();
    Object.keys(offices).forEach(function (key) {
      const o = offices[key], to = _w.copy(o.roofPos).sub(camera.position), dO = to.length();
      const between = dO < dLook - 1.5 && to.normalize().dot(look) > 0.9, goal = between || key === open ? 0 : 1;
      if (Math.abs(goal - o.shellOpacity) < 0.002) return;
      o.shellOpacity += (goal - o.shellOpacity) * k2;
      if (Math.abs(goal - o.shellOpacity) < 0.002) o.shellOpacity = goal;
      o.shell.visible = o.shellOpacity > 0.02;
      o.shellMats.forEach(function (m) { m.opacity = o.shellOpacity * m.userData.base; m.depthWrite = o.shellOpacity > 0.95; });
    });
  }
  const pointers = new Map(); let pinchD = 0;
  function pinchDist() { const p = Array.from(pointers.values()); return p.length < 2 ? 0 : Math.hypot(p[0].x - p[1].x, p[0].y - p[1].y); }
  canvas.addEventListener("pointerdown", function (e) { pointers.set(e.pointerId, { x: e.clientX, y: e.clientY }); try { canvas.setPointerCapture(e.pointerId); } catch (err) {} lastInputAt = performance.now(); pinchD = pinchDist(); });
  canvas.addEventListener("pointermove", function (e) {
    const p = pointers.get(e.pointerId); if (!p) return;
    const dx = e.clientX - p.x, dy = e.clientY - p.y; p.x = e.clientX; p.y = e.clientY; lastInputAt = performance.now();
    if (pointers.size === 1) { want.theta -= dx * 0.006; want.phi = clamp(want.phi - dy * 0.006, 0.35, 1.5); }
    else if (pointers.size === 2) { const d = pinchDist(); if (pinchD > 0 && d > 0) want.radius = clamp(want.radius * pinchD / d, 6, 40); pinchD = d; }
  });
  const up = function (e) { pointers.delete(e.pointerId); pinchD = pinchDist(); };
  canvas.addEventListener("pointerup", up); canvas.addEventListener("pointercancel", up);
  canvas.addEventListener("wheel", function (e) { e.preventDefault(); want.radius = clamp(want.radius * (1 + e.deltaY * 0.0012), 6, 40); lastInputAt = performance.now(); }, { passive: false });
  function resize() {
    const w = window.innerWidth, h = window.innerHeight; portrait = w / h < 0.8;
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1)); renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.fov = portrait ? 62 : 52;
    const pad = Math.round(h * (portrait ? 0.26 : 0.1)); camera.setViewOffset(w, h + pad, 0, pad, w, h); camera.updateProjectionMatrix();
    if (!focus && !pinned) { want.radius = fitRadius(); want.phi = portrait ? 0.92 : 1.0; }
  }
  window.addEventListener("resize", resize);

  // ------------------------------------------------------------- bubbles and the HUD
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
    const Wd = window.innerWidth, Hg = window.innerHeight;
    for (let i = bubbles.length - 1; i >= 0; i--) {
      const b = bubbles[i];
      if (simT >= b.until) { b.el.remove(); bubbles.splice(i, 1); continue; }
      const s = toScreen(b.actor.head.getWorldPosition(new THREE.Vector3()));
      const visible = s.ok && s.x > -40 && s.x < Wd + 40 && s.y > 40 && s.y < Hg;
      b.el.style.opacity = visible ? "1" : "0";
      if (visible) { const bw = b.el.offsetWidth, bh = b.el.offsetHeight;
        b.el.style.left = clamp(s.x - 28, 8, Wd - bw - 8) + "px"; b.el.style.top = clamp(s.y - bh - 16, 96, Hg - bh - 170) + "px"; }
    }
  }
  function updateLabels() {
    const Wd = window.innerWidth, Hg = window.innerHeight;
    labels.forEach(function (l) {
      const s = toScreen(l.office.labelAnchor.getWorldPosition(_w));
      const visible = s.ok && s.x > 10 && s.x < Wd - 10 && s.y > 100 && s.y < Hg - 190;
      l.el.style.opacity = visible ? "1" : "0";
      if (visible) { l.el.style.left = (s.x - l.el.offsetWidth / 2) + "px"; l.el.style.top = (s.y - 8) + "px"; }
    });
  }
  function statusDot(ids) { const i = document.createElement("i"); i.className = worstStatus(ids); return i; }
  function renderChips() {
    chips.textContent = "";
    Object.keys(CAST).forEach(function (k) {
      const c = CAST[k], b = document.createElement("button");
      b.appendChild(statusDot(c.members)); b.appendChild(document.createTextNode(c.name)); b.className = pinned === c.office ? "on" : "";
      b.onclick = function () { pin(c.office); }; chips.appendChild(b);
    });
    Object.keys(OFFICES).forEach(function (k) {
      if (Object.keys(CAST).some(function (a) { return CAST[a].office === k; })) return;
      const b = document.createElement("button"); b.appendChild(statusDot(OFFICES[k].members)); b.appendChild(document.createTextNode(OFFICES[k].title)); b.className = pinned === k ? "on" : "";
      b.onclick = function () { pin(k); }; chips.appendChild(b);
    });
    const all = document.createElement("button"); all.textContent = "campus"; all.className = pinned ? "" : "on"; all.onclick = function () { if (pinned) pin(pinned); }; chips.appendChild(all);
  }
  function renderCard() {
    const key = pinned || (focus && focus.office) || null;
    const room = card.querySelector(".room"), who = card.querySelector(".who"), line = card.querySelector(".line"), rows = card.querySelector(".rows");
    rows.textContent = ""; who.textContent = "";
    if (key && OFFICES[key]) {
      const spec = OFFICES[key], actorKey = Object.keys(CAST).find(function (k) { return CAST[k].office === key; }), c = actorKey ? CAST[actorKey] : null;
      room.textContent = spec.title.toUpperCase();
      who.appendChild(document.createTextNode(c ? c.name + " · " + c.kind : spec.title));
      if (c) { const small = document.createElement("small"); small.textContent = "plays " + c.members.map(nameOf).join(", "); who.appendChild(small); }
      line.textContent = c ? c.job : spec.line;
      spec.members.forEach(function (id) {
        const m = members[id]; if (!m) return;
        const div = document.createElement("div"), a = document.createElement("span"), st = document.createElement("span");
        a.textContent = nameOf(id) + ": " + (m.doing || m.why || ""); st.className = "status " + m.status; st.textContent = m.status;
        div.appendChild(a); div.appendChild(st); rows.appendChild(div);
      });
    } else {
      room.textContent = "THE CAMPUS"; who.appendChild(document.createTextNode("The team"));
      const counts = (data && data.team && data.team.counts) || {};
      line.textContent = Object.keys(counts).filter(function (k) { return counts[k]; }).map(function (k) { return counts[k] + " " + k; }).join(" · ");
      if (data) { const open = ((data.trades || {}).open || []), div = document.createElement("div");
        div.textContent = open.length + (open.length === 1 ? " open trade" : " open trades") + (data.trades && data.trades.max_open != null ? " of " + data.trades.max_open : ""); rows.appendChild(div); }
    }
  }

  // ------------------------------------------------------------- data
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
    const here = officeOf[memberId], i = PIPELINE.indexOf(memberId);
    let dest = i >= 0 && i + 1 < PIPELINE.length ? officeOf[PIPELINE[i + 1]] : null;
    if (!dest && here !== actor.homeOffice) dest = here;
    speak(actor, memberId, ev.text, ev.tone, 9);
    if (dest && dest !== actor.homeOffice && actor.queue.length < 3) actor.queue.push({ dest: dest, hold: 3 });
    focusOn(here, actor, 10);
  }
  function onClosed(t) {
    const jet = actors.jet; if (!jet) return;
    const pnl = t.pnl_usd, won = (pnl || 0) >= 0;
    speak(jet, "broker", (t.coin || "a trade") + ": " + (t.result ? t.result + " " : "") + fmtSigned(pnl), won ? "good" : "bad", 12);
    jet.queue.unshift({ dest: "vault", hold: 4, onArrive: function () { dropCoin(pnl); } });
    focusOn("vault", jet, 14);
  }
  function chatter() {
    const ids = Object.keys(members).filter(function (id) { return actorOf[id]; });
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
    const money = d.money || {}, since = (money.since_start || {}).usd, sol = (d.wallet || {}).sol;
    moneyEl.textContent = fmtUsd(money.usd);
    sinceEl.textContent = since == null ? (money.label || "") : fmtSigned(since) + " since start";
    sinceEl.style.color = since == null ? "" : since >= 0 ? "var(--good)" : "var(--bad)";
    if (offices.vault && offices.vault.sign) offices.vault.sign.userData.draw([
      { text: fmtUsd(money.usd), size: 84, bold: true },
      { text: money.label || "", size: 44 },
      { text: sol == null ? "" : "wallet " + Number(sol).toFixed(3) + " SOL", size: 36, color: "#c9bda6" },
    ], since == null ? "#d8a953" : since >= 0 ? "#58d68d" : "#ff6b61");
    ((d.team && d.team.members) || []).forEach(function (m) {
      members[m.id] = m;
      const ev = (m.events && m.events[0]) || null;
      if (ev && !first && ev.ts > (lastEventTs[m.id] || 0)) onEvent(m.id, ev);
      if (ev) lastEventTs[m.id] = ev.ts;
    });
    const closed = ((d.trades || {}).closed || [])[0];
    if (closed) { const key = closed.coin + "|" + closed.closed_at; if (!first && lastClosedKey && key !== lastClosedKey) onClosed(closed); lastClosedKey = key; }
    const alerts = d.alerts || [];
    statusEl.textContent = alerts.length ? alerts[0].text : "Every word on screen is the bot's own data";
    statusEl.className = alerts.length && alerts[0].level === "bad" ? "bad" : "";
    townEl.textContent = (d.town && d.town.line) || "";
    data = d;
    updateLights(); renderChips(); renderCard();
    if (first) { chatterAt = simT + 0.5; }
  }
  async function tick() {
    try { const d = await fetchPage(); if (d) apply(d); } catch (e) { setOffline("Cannot reach the bot right now"); }
    clockEl.textContent = lastOkAt ? "updated " + new Date(lastOkAt).toLocaleTimeString() : "";
  }

  // ------------------------------------------------------------- the loop (paused while the tab is hidden)
  let simT = 0, last = performance.now(), raf = 0;
  function frame(now) {
    raf = 0;
    const dtRaw = Math.min(0.1, Math.max(0, (now - last) / 1000)); last = now;
    const dt = offline ? 0 : dtRaw;
    simT += dt;
    if (data && !offline && simT >= chatterAt) { chatter(); chatterAt = simT + 10; }
    updateActors(dt); updateCoin(dt); updateCamera(dtRaw); updateBubbles(); updateLabels();
    renderer.render(scene, camera);
    if (document.visibilityState === "visible") raf = requestAnimationFrame(frame);
  }
  document.addEventListener("visibilitychange", function () { if (document.visibilityState === "visible" && !raf) { last = performance.now(); raf = requestAnimationFrame(frame); } });

  resize(); tint(); setInterval(tint, 60000);
  renderChips(); renderCard();
  boot.hidden = true;
  tick(); setInterval(function () { if (document.visibilityState === "visible") tick(); }, REFRESH_MS);
  raf = requestAnimationFrame(frame);
}
"""


def _sha256_source(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii") + "'"


#: Sent with ``/office3d``: scripts from this server (the bundled three.js module) and this exact inline module;
#: this exact inline style; data only from this server.
OFFICE3D_CSP = (
    f"default-src 'none'; script-src 'self' {_sha256_source(_MODULE)}; style-src {_sha256_source(_STYLE)}; "
    "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def _json_block(value: object) -> str:
    """Strict JSON that cannot close its ``<script>`` block (``<``, ``>`` and ``&`` escaped as JSON, still JSON)."""
    return json.dumps(value, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_office3d_html(settings: Settings) -> str:
    """The complete 3D town page (static; the module loads live data and the bundled three.js). Pure: no ledger data."""
    live = settings.is_live
    mode = "LIVE" if live else "PAPER"
    members = "".join(
        f'<span data-id="{html.escape(mid)}" data-name="{html.escape(name)}" data-role="{html.escape(role)}"></span>'
        for mid, name, role in MEMBERS
    )
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<meta name="color-scheme" content="dark">\n<meta name="theme-color" content="#0a0f24">\n'
        '<meta name="robots" content="noindex, nofollow">\n<meta name="referrer" content="no-referrer">\n'
        '<meta name="apple-mobile-web-app-capable" content="yes">\n'
        f'<link rel="icon" href="data:,">\n<title>Night Shift: the town · {mode.lower()}</title>\n'
        f"<style>{_STYLE}</style>\n</head>\n"
        f'<body data-refresh="{REFRESH_S}" data-pipeline="{",".join(PIPELINE)}">\n'
        '<canvas id="view"></canvas><div id="vignette"></div>\n'
        f'<header><b class="mode{" live" if live else ""}" id="mode">{mode}</b><a href="./">← the page</a>'
        '<a href="office">office</a>'
        '<span class="money"><b id="money">—</b><small id="since"></small><span id="clock"></span></span></header>\n'
        '<div id="foot"><span id="status">Loading the town…</span></div>\n'
        '<div id="town"></div>\n'
        f'<div id="members" hidden>{members}</div>\n'
        f'<script id="cast" type="application/json">{_json_block(CAST3D)}</script>\n'
        f'<script id="offices" type="application/json">{_json_block(OFFICES3D)}</script>\n'
        '<div id="labels"></div>\n<div id="bubbles"></div>\n<div id="drop"></div>\n'
        '<div id="card"><div class="room">NIGHT SHIFT: THE TOWN</div><div class="who">Loading…</div>'
        '<div class="line"></div><div class="rows"></div></div>\n'
        '<div id="chips"></div>\n'
        '<p id="boot">Loading the 3D town… It needs a browser with JavaScript modules and WebGL; '
        'the <a href="office">Office</a> page shows the same team as pictures.</p>\n'
        '<p id="honest">A visualisation of the bot\'s own ledger: every word is the bot\'s data; the town and its cast are drawings.</p>\n'
        f'<script type="module">{_MODULE}</script>\n</body>\n</html>\n'
    )
