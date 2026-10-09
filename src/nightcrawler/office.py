"""The office, "Night Shift: Skyport": the team at work as a short film, at ``/office``.

The sets are the owner's concept art of the headquarters (ten images, made for this project, bundled web-sized in
``office_art/`` and served at ``/office/art/<name>.jpg`` behind the same token). A director in the page cuts between
rooms the way a low drone would fly through the building: to the room of the member whose event just happened, to
the vault when a trade closes, otherwise slowly round the rooms where someone is working. Every WORD on screen comes
from ``/api/page`` (the one page's data, already redacted and clipped) and is inserted as text only; the art is
labelled as concept art in the footer. Nothing here touches trading.

Cast (presentation identities for the bot's real roles; ``CAST`` below):
Pip the fox scout = Crawler; Nyx the octopus analyst = Cocoon, Radar and Strategy (three arms, three screens);
Voss the owl at the mission table = Jev, the AI judge / the Desk; Rook the golem at the vault = Risk, and the vault
IS the safe (the money card and the bot wallet's SOL); Mote in the glass bell = Receipts and the Coach's memory;
Jet the courier robot = Broker (he carries the money to the vault when a trade closes); the observatory = the Coach
and the research lab.

Pure and static like :mod:`nightcrawler.page`: :func:`render_office_html` never puts ledger data into the HTML.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
from pathlib import Path

from nightcrawler.config import Settings
from nightcrawler.page import MEMBERS, REFRESH_S

__all__ = [
    "ART_FILES",
    "CAST",
    "OFFICE_CSP",
    "PIPELINE",
    "SHOTS",
    "art_bytes",
    "render_office_html",
]

#: Walk order of a hand-off (the pipeline a coin travels).
PIPELINE = (
    "crawler",
    "cocoon",
    "strategy",
    "radar",
    "judge",
    "broker",
    "risk",
    "receipts",
)

ART_DIR = Path(__file__).resolve().parent / "office_art"
#: The only files ``/office/art/<name>`` will ever serve (no listing, no traversal).
ART_FILES: tuple[str, ...] = (
    "00_world_layout.jpg",
    "01_arrival_drone.jpg",
    "02_mission_table.jpg",
    "03_analyst_nyx.jpg",
    "04_workshop_pip.jpg",
    "05_vault_rook.jpg",
    "06_archive_mote.jpg",
    "07_courier_cafe.jpg",
    "08_crew_lineup.jpg",
    "09_observatory.jpg",
)

#: Who plays whom. ``members``: the bot roles that live in the character's room (first = the speaker).
CAST: dict[str, dict[str, object]] = {
    "pip": {
        "name": "Pip",
        "kind": "fox scout",
        "members": ["crawler"],
        "shot": "04_workshop_pip.jpg",
        "room": "The workshop",
        "job": "gathers the raw material: brand-new coins",
    },
    "nyx": {
        "name": "Nyx",
        "kind": "octopus analyst",
        "members": ["cocoon", "radar", "strategy"],
        "shot": "03_analyst_nyx.jpg",
        "room": "The analysis den",
        "job": "three arms, three screens: scam filter, danger check, the setup",
    },
    "voss": {
        "name": "Voss",
        "kind": "owl director",
        "members": ["judge", "predict"],
        "shot": "02_mission_table.jpg",
        "room": "The mission table",
        "job": "reviews and challenges every setup: the AI judge",
    },
    "rook": {
        "name": "Rook",
        "kind": "stone golem",
        "members": ["risk"],
        "shot": "05_vault_rook.jpg",
        "room": "The vault",
        "job": "sizes, limits, approvals; keeps the safe",
    },
    "mote": {
        "name": "Mote",
        "kind": "archivist in a bell",
        "members": ["receipts", "coach"],
        "shot": "06_archive_mote.jpg",
        "room": "The archive",
        "job": "every decision and fill on a tamper-proof chain; what the team has learned",
    },
    "jet": {
        "name": "Jet",
        "kind": "courier robot",
        "members": ["broker"],
        "shot": "07_courier_cafe.jpg",
        "room": "The courier dock",
        "job": "places the trades and carries the money to the vault",
    },
}

#: Shots: where the speaker stands (percent of the 16:9 frame: the bubble's anchor and the crop's focal point).
SHOTS: dict[str, dict[str, object]] = {
    "01_arrival_drone.jpg": {
        "title": "Arrival",
        "anchor": [0.47, 0.37],
        "focus": [0.5, 0.45],
    },
    "02_mission_table.jpg": {
        "title": "The mission table",
        "anchor": [0.51, 0.33],
        "focus": [0.5, 0.45],
    },
    "03_analyst_nyx.jpg": {
        "title": "The analysis den",
        "anchor": [0.42, 0.40],
        "focus": [0.5, 0.5],
    },
    "04_workshop_pip.jpg": {
        "title": "The workshop",
        "anchor": [0.42, 0.30],
        "focus": [0.45, 0.45],
    },
    "05_vault_rook.jpg": {
        "title": "The vault",
        "anchor": [0.64, 0.30],
        "focus": [0.62, 0.45],
    },
    "06_archive_mote.jpg": {
        "title": "The archive",
        "anchor": [0.37, 0.46],
        "focus": [0.45, 0.5],
    },
    "07_courier_cafe.jpg": {
        "title": "The courier dock",
        "anchor": [0.55, 0.52],
        "focus": [0.5, 0.55],
    },
    "09_observatory.jpg": {
        "title": "The observatory",
        "anchor": [0.22, 0.42],
        "focus": [0.45, 0.5],
    },
    "00_world_layout.jpg": {
        "title": "The headquarters",
        "anchor": [0.5, 0.42],
        "focus": [0.5, 0.5],
    },
    "08_crew_lineup.jpg": {
        "title": "The crew",
        "anchor": [0.5, 0.45],
        "focus": [0.5, 0.55],
    },
}


def art_bytes(name: str) -> bytes | None:
    """The bundled JPEG for an allowed name, else None (unknown names are never looked up on disk)."""
    if name not in ART_FILES:
        return None
    try:
        return (ART_DIR / name).read_bytes()
    except OSError:
        return None


_STYLE = r"""
:root { color-scheme: dark; --fg: #f3ecdf; --dim: #c9bda6; --good: #58d68d; --bad: #ff6b61; --brass: #d8a953;
        --glass: rgba(16, 14, 24, .62); --glass2: rgba(16, 14, 24, .8); }
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; background: #0c0a14; color: var(--fg);
             font: 15px/1.4 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
body { overflow: hidden; }
#stage { position: fixed; inset: 0; background: #0c0a14; }
#stage img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover;
             transition: opacity 1.4s ease, transform 14s linear; opacity: 0; will-change: transform, opacity; }
#stage img.on { opacity: 1; }
#vignette { position: fixed; inset: 0; pointer-events: none;
            background: radial-gradient(ellipse at center, rgba(0,0,0,0) 55%, rgba(5,3,10,.55) 100%),
                        linear-gradient(to bottom, rgba(5,3,10,.55), rgba(0,0,0,0) 18%, rgba(0,0,0,0) 70%, rgba(5,3,10,.7)); }
header { position: fixed; top: 0; left: 0; right: 0; display: flex; align-items: center; gap: 10px;
         padding: calc(8px + env(safe-area-inset-top)) 14px 8px; }
header b.mode { font-size: 11px; letter-spacing: .14em; padding: 3px 9px; border-radius: 999px;
                background: rgba(60, 50, 90, .75); border: 1px solid rgba(216,169,83,.5); }
header b.mode.live { background: var(--bad); color: #fff; }
header a { color: var(--dim); text-decoration: none; font-size: 13px; }
header .money { margin-left: auto; text-align: right; font-variant-numeric: tabular-nums;
                background: var(--glass); padding: 4px 10px; border-radius: 10px; border: 1px solid rgba(216,169,83,.35); }
header .money b { font-size: 16px; }
header .money small { display: block; font-size: 11px; color: var(--dim); }
#bubble { position: fixed; max-width: min(78vw, 420px); background: #f8f3e6; color: #1d1a16; padding: 9px 12px;
          border-radius: 14px; border: 2px solid var(--brass); font-size: 14px; line-height: 1.35;
          box-shadow: 0 8px 30px rgba(0,0,0,.45); opacity: 0; transition: opacity .5s ease; pointer-events: none; }
#bubble.on { opacity: 1; }
#bubble:after { content: ""; position: absolute; left: 22px; bottom: -11px; border: 10px solid transparent;
                border-top-color: var(--brass); border-bottom: 0; }
#bubble.good { border-color: var(--good); } #bubble.good:after { border-top-color: var(--good); }
#bubble.bad { border-color: var(--bad); } #bubble.bad:after { border-top-color: var(--bad); }
#bubble small { display: block; color: #6c6356; font-size: 11px; letter-spacing: .08em; margin-bottom: 2px; }
#card { position: fixed; left: 12px; right: 12px; bottom: calc(44px + env(safe-area-inset-bottom));
        background: var(--glass2); border: 1px solid rgba(216,169,83,.4); border-radius: 14px; padding: 10px 12px;
        backdrop-filter: blur(6px); }
#card .room { font-size: 11px; letter-spacing: .14em; color: var(--brass); }
#card .who { font-weight: 700; font-size: 16px; margin-top: 2px; }
#card .who small { font-weight: 400; color: var(--dim); margin-left: 6px; }
#card .line { color: var(--fg); margin-top: 4px; font-size: 14px; }
#card .status { display: inline-block; font-size: 11px; padding: 1px 8px; border-radius: 999px; margin-left: 6px;
                background: rgba(255,255,255,.12); vertical-align: middle; }
#card .status.working { background: rgba(88,214,141,.25); color: var(--good); }
#card .status.blocked { background: rgba(255,107,97,.3); color: var(--bad); }
#card .status.idle, #card .status.waiting { color: var(--dim); }
#card .rows { margin-top: 6px; font-size: 13px; color: var(--dim); }
#card .rows div { display: flex; justify-content: space-between; gap: 10px; }
#safe { position: fixed; right: 14px; bottom: calc(150px + env(safe-area-inset-bottom)); min-width: 170px;
        background: linear-gradient(160deg, rgba(60,46,30,.92), rgba(28,22,18,.92)); border: 2px solid var(--brass);
        border-radius: 16px; padding: 10px 14px; box-shadow: 0 10px 40px rgba(0,0,0,.5); display: none; }
#safe.on { display: block; } #safe.flash-good { border-color: var(--good); } #safe.flash-bad { border-color: var(--bad); }
#safe small { display: block; font-size: 11px; letter-spacing: .12em; color: var(--brass); }
#safe b { font-size: 24px; font-variant-numeric: tabular-nums; }
#safe .sol { color: var(--dim); font-size: 12px; }
#drop { position: fixed; font-weight: 700; font-size: 18px; pointer-events: none; opacity: 0;
        transition: transform 1.6s ease-out, opacity 1.6s ease-out; }
#chips { position: fixed; left: 12px; right: 12px; bottom: calc(10px + env(safe-area-inset-bottom)); display: flex;
         gap: 6px; overflow-x: auto; scrollbar-width: none; }
#chips::-webkit-scrollbar { display: none; }
#chips button { flex: 0 0 auto; font: inherit; font-size: 12px; color: var(--fg); background: var(--glass);
                border: 1px solid rgba(216,169,83,.35); border-radius: 999px; padding: 4px 10px; cursor: pointer; }
#chips button.on { border-color: var(--brass); background: rgba(216,169,83,.25); }
#chips button i { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; background: #777; }
#chips button i.working { background: var(--good); } #chips button i.blocked { background: var(--bad); }
#foot { position: fixed; right: 14px; top: calc(52px + env(safe-area-inset-top)); font-size: 11px; color: var(--dim);
        text-align: right; max-width: 60vw; text-shadow: 0 1px 2px #000; }
#status.bad { color: var(--bad); }
"""

_SCRIPT = r"""
(function () {
  "use strict";
  const body = document.body;
  const REFRESH_MS = Math.max(4000, 1000 * (parseInt(body.dataset.refresh, 10) || 10));
  const CAST = JSON.parse(document.getElementById("cast").textContent);
  const SHOTS = JSON.parse(document.getElementById("shots").textContent);
  const MEMBERS = Array.from(document.querySelectorAll("#members span")).map(function (s) {
    return { id: s.dataset.id, name: s.dataset.name, role: s.dataset.role };
  });
  const el = function (id) { return document.getElementById(id); };
  const imgs = [el("img0"), el("img1")];
  const bubble = el("bubble"), card = el("card"), safe = el("safe"), drop = el("drop"), chips = el("chips");
  const moneyEl = el("money"), sinceEl = el("since"), modeEl = el("mode"), statusEl = el("status"), clockEl = el("clock");
  const params = new URLSearchParams(location.search);
  let token = null;
  if (params.has("token")) { token = params.get("token"); params.delete("token"); const q = params.toString();
    history.replaceState(null, "", location.pathname + (q ? "?" + q : "")); }

  const roleOf = {};                         // member id -> cast key
  Object.keys(CAST).forEach(function (k) { CAST[k].members.forEach(function (m) { roleOf[m] = k; }); });
  let data = null, members = {}, lastEventTs = {}, lastClosedKey = null, lastOkAt = null, offline = false;
  let current = null, layer = 0, holdUntil = 0, rotation = 0, pinned = null;
  const queue = [];                           // cuts waiting: {shot, speaker, text, tone, hold, onCut}

  // ------------------------------------------------------------- data
  async function fetchPage() {
    const opts = { cache: "no-store", credentials: "same-origin" };
    let res = await fetch("api/page", opts);
    if (res.status === 401 && token) res = await fetch("api/page?token=" + encodeURIComponent(token), opts);
    if (res.status === 401) { setOffline("Locked: open the link that ends with ?token=…"); return null; }
    if (!res.ok) { setOffline("The bot's data is unavailable (" + res.status + ")"); return null; }
    return res.json();
  }
  function setOffline(text) { offline = true; statusEl.textContent = text; statusEl.className = "bad"; }
  function fmtUsd(v) { return v == null ? "—" : (v < 0 ? "−" : "") + "$" + Math.abs(v).toFixed(2); }
  function fmtPct(v) { return v == null ? "" : (v >= 0 ? "+" : "") + (100 * v).toFixed(1) + "%"; }

  function apply(d) {
    offline = false; lastOkAt = Date.now(); statusEl.className = "";
    const mode = d.mode === "LIVE" ? "LIVE" : "PAPER";
    modeEl.textContent = mode; modeEl.className = "mode" + (mode === "LIVE" ? " live" : "");
    const money = d.money || {};
    moneyEl.textContent = fmtUsd(money.usd);
    const since = (money.since_start || {}).usd;
    sinceEl.textContent = since == null ? (money.label || "") : ((since >= 0 ? "+" : "") + fmtUsd(since).replace("−$", "-$") + " since start");
    sinceEl.style.color = since == null ? "" : (since >= 0 ? "var(--good)" : "var(--bad)");
    el("safe-usd").textContent = fmtUsd(money.usd);
    el("safe-label").textContent = money.label || (mode === "LIVE" ? "REAL MONEY" : "PAPER MONEY (PRETEND)");
    const sol = (d.wallet || {}).sol;
    el("safe-sol").textContent = sol == null ? "wallet: not read yet" : "wallet " + Number(sol).toFixed(3) + " SOL";
    const first = !data;
    ((d.team && d.team.members) || []).forEach(function (m) {
      members[m.id] = m;
      const ev = (m.events && m.events[0]) || null;
      if (ev && !first && lastEventTs[m.id] != null && ev.ts > lastEventTs[m.id]) {
        const k = roleOf[m.id];
        if (k) queue.push({ shot: CAST[k].shot, speaker: m.id, text: ev.text, tone: ev.tone, hold: 9000 });
      }
      if (ev) lastEventTs[m.id] = ev.ts;
    });
    const closed = ((d.trades || {}).closed || [])[0];
    if (closed) {
      const key = closed.coin + "|" + closed.closed_at;
      if (!first && lastClosedKey && key !== lastClosedKey) {
        const won = (closed.pnl_usd || 0) >= 0;
        queue.unshift({ shot: "05_vault_rook.jpg", speaker: "broker", tone: won ? "good" : "bad", hold: 12000,
                        text: "Jet brings the result to the vault: " + (closed.coin || "a trade") + " " + (won ? "+" : "") + fmtUsd(closed.pnl_usd),
                        onCut: function () { dropMoney(closed.pnl_usd); } });
      }
      lastClosedKey = key;
    }
    const alerts = d.alerts || [];
    statusEl.textContent = alerts.length ? alerts[0].text : "Every word on screen is from the bot's own ledger · sets are concept art";
    if (alerts.length) statusEl.className = alerts[0].level === "bad" ? "bad" : "";
    data = d;
    renderChips();
    if (!current) director(true);
    else renderOverlay();
  }

  // ------------------------------------------------------------- director
  function workingRooms() {
    const out = [];
    Object.keys(CAST).forEach(function (k) {
      const ms = CAST[k].members.map(function (id) { return members[id]; }).filter(Boolean);
      if (ms.some(function (m) { return m.status === "working"; })) out.push(k);
    });
    return out;
  }
  function anyActivity() { return Object.keys(members).some(function (id) { return members[id].status === "working"; }); }
  function director(force) {
    const now = Date.now();
    if (pinned) { if (force || !current || current.shot !== CAST[pinned].shot) cut({ shot: CAST[pinned].shot, speaker: CAST[pinned].members[0], hold: 1e12 }); return; }
    if (!force && now < holdUntil) return;
    if (queue.length) { cut(queue.shift()); return; }
    const rooms = workingRooms();
    let next;
    if (rooms.length) { next = rooms[rotation % rooms.length]; rotation += 1; }
    else {                                    // nothing moving: arrival, the café, the observatory, the map
      const idle = ["01_arrival_drone.jpg", "07_courier_cafe.jpg", "09_observatory.jpg", "00_world_layout.jpg"];
      cut({ shot: idle[rotation % idle.length], speaker: null, hold: 12000 }); rotation += 1; return;
    }
    cut({ shot: CAST[next].shot, speaker: CAST[next].members[0], hold: 11000 });
  }
  function cut(c) {
    current = c; holdUntil = Date.now() + (c.hold || 10000);
    const nextLayer = 1 - layer, img = imgs[nextLayer], old = imgs[layer];
    const shot = SHOTS[c.shot] || { focus: [0.5, 0.5], anchor: [0.5, 0.4] };
    img.style.objectPosition = (100 * shot.focus[0]) + "% " + (100 * shot.focus[1]) + "%";
    img.style.transition = "none"; img.style.transform = "scale(1.04) translate(0.6%, 0.4%)";
    const start = function () {
      img.classList.add("on"); old.classList.remove("on");
      requestAnimationFrame(function () { img.style.transition = "opacity 1.4s ease, transform 14s linear"; img.style.transform = "scale(1.12) translate(-0.8%, -0.6%)"; });
      layer = nextLayer; renderOverlay(); if (c.onCut) c.onCut();
    };
    if (img.dataset.shot !== c.shot) { img.dataset.shot = c.shot; img.onload = start; img.src = "office/art/" + c.shot; if (img.complete && img.naturalWidth) start(); }
    else start();
  }

  // ------------------------------------------------------------- overlay
  function anchorPx(shot) {
    const s = SHOTS[shot] || { anchor: [0.5, 0.4], focus: [0.5, 0.5] };
    const W = window.innerWidth, H = window.innerHeight, iw = 1400, ih = 788;
    const scale = Math.max(W / iw, H / ih), dw = iw * scale, dh = ih * scale;
    const ox = (W - dw) * s.focus[0], oy = (H - dh) * s.focus[1];   // object-position: focus % of the overflow
    return { x: ox + s.anchor[0] * dw, y: oy + s.anchor[1] * dh };
  }
  function statusChip(m) { return m ? '<span class="status ' + m.status + '">' + m.status + "</span>" : ""; }
  function renderOverlay() {
    if (!current) return;
    const shot = SHOTS[current.shot] || {}, k = current.speaker ? roleOf[current.speaker] : null, c = k ? CAST[k] : null;
    const m = current.speaker ? members[current.speaker] : null;
    card.querySelector(".room").textContent = (shot.title || "").toUpperCase();
    const who = card.querySelector(".who");
    who.textContent = "";
    if (c) {
      who.appendChild(document.createTextNode(c.name + " · " + c.kind));
      const roles = c.members.map(function (id) { const mm = MEMBERS.find(function (x) { return x.id === id; }); return mm ? mm.name : id; }).join(", ");
      const small = document.createElement("small"); small.textContent = "plays " + roles; who.appendChild(small);
      if (m) { const st = document.createElement("span"); st.className = "status " + m.status; st.textContent = m.status; who.appendChild(st); }
    } else {
      who.appendChild(document.createTextNode(current.shot === "00_world_layout.jpg" ? "The headquarters" : current.shot === "08_crew_lineup.jpg" ? "The crew" : "Between rooms"));
    }
    const line = card.querySelector(".line");
    line.textContent = c ? c.job : (anyActivity() ? "The team is at work; the camera is on its way." : "A quiet night: nobody is on a coin right now.");
    const rows = card.querySelector(".rows"); rows.textContent = "";
    if (c) {
      c.members.forEach(function (id) {
        const mm = members[id]; if (!mm) return;
        const div = document.createElement("div");
        const a = document.createElement("span"); a.textContent = (MEMBERS.find(function (x) { return x.id === id; }) || { name: id }).name + ": " + (mm.doing || mm.why || "");
        div.appendChild(a); rows.appendChild(div);
      });
    }
    if (current.shot === "02_mission_table.jpg" && data) {
      const open = ((data.trades || {}).open || []).slice(0, 4);
      open.forEach(function (t) { const div = document.createElement("div"); const a = document.createElement("span"); a.textContent = "open: " + (t.coin || "?"); const b = document.createElement("span"); b.textContent = fmtUsd(t.pnl_usd) + " " + fmtPct(t.pnl_pct); b.style.color = (t.pnl_usd || 0) >= 0 ? "var(--good)" : "var(--bad)"; div.appendChild(a); div.appendChild(b); rows.appendChild(div); });
      if (!open.length) { const div = document.createElement("div"); div.textContent = "No open trades on the table."; rows.appendChild(div); }
    }
    if (current.shot === "09_observatory.jpg" && data && data.learning) {
      const L = data.learning; const div = document.createElement("div"); div.textContent = "Coach: " + (L.headline || L.state || "collecting data"); rows.appendChild(div);
      (L.variants || []).slice(0, 3).forEach(function (v) { const d2 = document.createElement("div"); const a = document.createElement("span"); a.textContent = v.name; const b = document.createElement("span"); b.textContent = (v.n != null ? v.n + " trades" : "") + (v.avg != null ? " · avg " + Number(v.avg).toFixed(1) + "%" : ""); d2.appendChild(a); d2.appendChild(b); rows.appendChild(d2); });
    }
    safe.className = current.shot === "05_vault_rook.jpg" ? "on" : "";
    positionSafe();
    // the speech bubble: what this member is really saying
    const text = current.text || (m ? ((m.events && m.events[0] && m.events[0].text) || m.doing || m.why) : "");
    if (text) {
      bubble.querySelector("small").textContent = c ? c.name.toUpperCase() : "";
      bubble.querySelector("span").textContent = text;
      bubble.className = "on " + (current.tone === "good" ? "good" : current.tone === "bad" ? "bad" : "");
      positionBubble();
    } else { bubble.className = ""; }
  }
  function positionSafe() {                  // the safe sits just above the card, whatever the card's height
    const r = card.getBoundingClientRect();
    safe.style.bottom = Math.round(window.innerHeight - r.top + 10) + "px";
  }
  function positionBubble() {
    if (!current) return;
    const a = anchorPx(current.shot), W = window.innerWidth;
    bubble.style.left = Math.max(10, Math.min(W - bubble.offsetWidth - 10, a.x - 30)) + "px";
    bubble.style.top = Math.max(70, a.y - bubble.offsetHeight - 26) + "px";
  }
  function dropMoney(pnl) {
    const won = (pnl || 0) >= 0;
    safe.classList.add(won ? "flash-good" : "flash-bad");
    const r = safe.getBoundingClientRect();
    drop.textContent = (won ? "+" : "") + fmtUsd(pnl); drop.style.color = won ? "var(--good)" : "var(--bad)";
    drop.style.left = (r.left + r.width / 2 - 30) + "px"; drop.style.top = (r.top - 40) + "px";
    drop.style.transition = "none"; drop.style.transform = "translateY(0)"; drop.style.opacity = "1";
    requestAnimationFrame(function () { drop.style.transition = "transform 1.6s ease-out, opacity 1.6s ease-out"; drop.style.transform = "translateY(" + (won ? 44 : -44) + "px)"; drop.style.opacity = "0"; });
    setTimeout(function () { safe.classList.remove("flash-good", "flash-bad"); }, 1800);
  }
  function renderChips() {
    chips.textContent = "";
    Object.keys(CAST).forEach(function (k) {
      const c = CAST[k], b = document.createElement("button"), i = document.createElement("i");
      const ms = c.members.map(function (id) { return members[id]; }).filter(Boolean);
      i.className = ms.some(function (m) { return m.status === "blocked"; }) ? "blocked" : ms.some(function (m) { return m.status === "working"; }) ? "working" : "";
      b.appendChild(i); b.appendChild(document.createTextNode(c.name)); b.className = pinned === k ? "on" : "";
      b.onclick = function () { pinned = pinned === k ? null : k; renderChips(); director(true); };
      chips.appendChild(b);
    });
    [["map", "00_world_layout.jpg"], ["crew", "08_crew_lineup.jpg"]].forEach(function (pair) {
      const b = document.createElement("button"); b.textContent = pair[0];
      b.onclick = function () { pinned = null; renderChips(); cut({ shot: pair[1], speaker: null, hold: 15000 }); };
      chips.appendChild(b);
    });
  }

  // ------------------------------------------------------------- loop
  async function tick() {
    try { const d = await fetchPage(); if (d) apply(d); } catch (e) { setOffline("Cannot reach the bot right now"); }
    clockEl.textContent = lastOkAt ? "· updated " + new Date(lastOkAt).toLocaleTimeString() : "";
  }
  window.addEventListener("resize", function () { positionBubble(); positionSafe(); });
  setInterval(function () { if (document.visibilityState === "visible") director(false); }, 1000);
  tick(); setInterval(function () { if (document.visibilityState === "visible") tick(); }, REFRESH_MS);
})();
"""


def _sha256_source(text: str) -> str:
    return (
        "'sha256-"
        + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode(
            "ascii"
        )
        + "'"
    )


#: Sent with ``/office``: the sets load only from this server; only this exact inline script and style run.
OFFICE_CSP = (
    f"default-src 'none'; script-src {_sha256_source(_SCRIPT)}; style-src {_sha256_source(_STYLE)}; "
    "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def render_office_html(settings: Settings) -> str:
    """The complete office page (static; the script loads live data and the bundled sets). Pure: no ledger data."""
    live = settings.is_live
    mode = "LIVE" if live else "PAPER"
    members = "".join(
        f'<span data-id="{html.escape(mid)}" data-name="{html.escape(name)}" data-role="{html.escape(role)}"></span>'
        for mid, name, role in MEMBERS
    )
    cast_json = html.escape(json.dumps(CAST, separators=(",", ":")), quote=False)
    shots_json = html.escape(json.dumps(SHOTS, separators=(",", ":")), quote=False)
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<meta name="color-scheme" content="dark">\n<meta name="theme-color" content="#0c0a14">\n'
        '<meta name="robots" content="noindex, nofollow">\n<meta name="referrer" content="no-referrer">\n'
        '<meta name="apple-mobile-web-app-capable" content="yes">\n'
        f'<link rel="icon" href="data:,">\n<title>Night Shift: Skyport · {mode.lower()}</title>\n'
        f"<style>{_STYLE}</style>\n</head>\n"
        f'<body data-refresh="{REFRESH_S}" data-pipeline="{",".join(PIPELINE)}">\n'
        '<div id="stage"><img id="img0" alt=""><img id="img1" alt=""></div><div id="vignette"></div>\n'
        f'<header><b class="mode{" live" if live else ""}" id="mode">{mode}</b><a href="./">← the page</a>'
        '<span class="money"><b id="money">—</b><small id="since"></small></span></header>\n'
        '<div id="foot"><span id="status">Loading the headquarters…</span> <span id="clock"></span></div>\n'
        f'<div id="members" hidden>{members}</div>\n'
        f'<script id="cast" type="application/json">{cast_json}</script>\n'
        f'<script id="shots" type="application/json">{shots_json}</script>\n'
        '<div id="bubble"><small></small><span></span></div>\n'
        '<div id="safe"><small>THE SAFE</small><div id="safe-label" class="sol"></div><b id="safe-usd">—</b>'
        '<div id="safe-sol" class="sol"></div></div>\n<div id="drop"></div>\n'
        '<div id="card"><div class="room">NIGHT SHIFT: SKYPORT</div><div class="who">Loading…</div>'
        '<div class="line"></div><div class="rows"></div></div>\n'
        '<div id="chips"></div>\n'
        f"<script>{_SCRIPT}</script>\n</body>\n</html>\n"
    )
