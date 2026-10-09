"""The office: an animated view of the team at work, at ``/office`` (owner: "like a whole movie with characters").

Pure and static like :mod:`nightcrawler.page`: :func:`render_office_html` never puts ledger data into the HTML.
The inline script fetches ``/api/page`` (the same data the one page shows, already redacted and clipped) and draws
a little top-down office on a canvas: one desk per team member, the member's live status as what the character
does (typing when working, standing when waiting, dozing when idle, flagged when blocked, an empty desk when
absent), their real ``doing`` line and newest event as speech bubbles, a hand-off walk down the pipeline when a
member logs a new event, and the Broker walking to the safe when a trade closes: the safe shows the money card
(green drop when the trade made money, red when it lost - the safe never lies). The safe IS the bot wallet:
its SOL balance is printed on the door.

Nothing here touches trading. Everything drawn comes from ``/api/page`` text fields inserted as text only
(``fillText`` / ``textContent``); the CSP allows exactly this inline script and style and nothing else.
"""

from __future__ import annotations

import base64
import hashlib
import html

from nightcrawler.config import Settings
from nightcrawler.page import MEMBERS, REFRESH_S

__all__ = ["OFFICE_CSP", "render_office_html"]

#: Walk order of a hand-off (the pipeline a coin travels).
PIPELINE = ("crawler", "cocoon", "strategy", "radar", "judge", "broker", "risk", "receipts")

_STYLE = r"""
:root { color-scheme: light dark; --bg: #0b0d12; --fg: #e8e6df; --dim: #9a9890; --good: #46c67a; --bad: #e0564f;
        --warn: #e3b341; --card: #141821; }
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; background: var(--bg); color: var(--fg);
             font: 15px/1.4 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
body { display: flex; flex-direction: column; min-height: 100dvh; }
header { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-bottom: 1px solid #222838; }
header b.mode { font-size: 12px; letter-spacing: .12em; padding: 3px 8px; border-radius: 999px; background: #2a3146; }
header b.mode.live { background: var(--bad); color: #fff; }
header .money { margin-left: auto; font-variant-numeric: tabular-nums; }
header .money small { color: var(--dim); margin-left: 6px; }
header a { color: var(--dim); text-decoration: none; font-size: 13px; }
#stage { flex: 1; display: block; width: 100%; touch-action: manipulation; }
footer { padding: 8px 14px; color: var(--dim); font-size: 12px; border-top: 1px solid #222838;
         display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
#status.bad { color: var(--bad); }
"""

# The script is plain ES2017 and self-contained (no network but api/page; no eval; text only).
_SCRIPT = r"""
(function () {
  "use strict";
  const body = document.body;
  const canvas = document.getElementById("stage");
  const ctx = canvas.getContext("2d");
  const moneyEl = document.getElementById("money"), modeEl = document.getElementById("mode"),
        statusEl = document.getElementById("status"), clockEl = document.getElementById("clock");
  const REFRESH_MS = Math.max(4000, 1000 * (parseInt(body.dataset.refresh, 10) || 10));
  const MEMBERS = Array.from(document.querySelectorAll("#members span")).map(function (s) {
    return { id: s.dataset.id, name: s.dataset.name, role: s.dataset.role };
  });
  const PIPELINE = (body.dataset.pipeline || "").split(",");
  const params = new URLSearchParams(location.search);
  let token = null;
  if (params.has("token")) {
    token = params.get("token");
    params.delete("token");
    const q = params.toString();
    history.replaceState(null, "", location.pathname + (q ? "?" + q : ""));
  }

  // ------------------------------------------------------------- world
  const COLORS = { crawler: "#5aa9e6", cocoon: "#b48ead", strategy: "#f0a35e", radar: "#7fd1b9", judge: "#e3b341",
                   broker: "#46c67a", risk: "#e0564f", receipts: "#c0c4cc", coach: "#f6c6ea" };
  const people = {};          // id -> {x, y, tx, ty, desk:{x,y}, status, doing, event, bubbleUntil, phase, pinned}
  let safe = { x: 0, y: 0, w: 0, h: 0, usd: null, sol: null, label: "", flash: null };
  let world = { w: 0, h: 0, scale: 1 };
  let lastData = null, lastEventTs = {}, lastClosedKey = null, offline = false, lastOkAt = null;
  const drops = [];           // {x, y, vy, text, color, born}
  const walks = [];           // {id, path:[{x,y}], i, back:{x,y}}

  function layout() {
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const rect = canvas.getBoundingClientRect();
    world.w = Math.max(320, rect.width); world.h = Math.max(360, rect.height);
    canvas.width = Math.round(world.w * dpr); canvas.height = Math.round(world.h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const cols = world.w > 700 ? 3 : 2, n = MEMBERS.length;
    const rows = Math.ceil(n / cols);
    const padX = 24, top = 110, bottom = 150;
    const cellW = (world.w - 2 * padX) / cols, cellH = Math.max(90, (world.h - top - bottom) / rows);
    MEMBERS.forEach(function (m, i) {
      const c = i % cols, r = Math.floor(i / cols);
      const desk = { x: padX + cellW * (c + 0.5), y: top + cellH * (r + 0.5) + 10 };
      const p = people[m.id] || (people[m.id] = { x: desk.x + 56, y: desk.y + 2, phase: Math.random() * 6.28,
                                                  bubbleUntil: Date.now() + 2500 + 1800 * i });
      p.desk = desk; p.home = { x: desk.x + 56, y: desk.y + 2 }; p.name = m.name; p.role = m.role;
      if (!p.walking) { p.x = p.home.x; p.y = p.home.y; }
    });
    safe.w = Math.min(150, world.w * 0.4); safe.h = 84;
    safe.x = world.w - safe.w - 18; safe.y = world.h - safe.h - 44;
  }

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

  function apply(data) {
    offline = false; lastOkAt = Date.now(); statusEl.className = "";
    const mode = data.mode === "LIVE" ? "LIVE" : "PAPER";
    modeEl.textContent = mode; modeEl.className = "mode" + (mode === "LIVE" ? " live" : "");
    const money = data.money || {};
    safe.usd = money.usd; safe.sol = (data.wallet || {}).sol;
    safe.label = money.label || (mode === "LIVE" ? "Real money" : "Paper money (pretend)");
    moneyEl.textContent = fmtUsd(money.usd);
    const since = (money.since_start || {}).usd;
    const chip = document.getElementById("since");
    chip.textContent = since == null ? "" : (since >= 0 ? "+" : "") + fmtUsd(since).replace("−$", "-$") + " since start";
    chip.style.color = since == null ? "" : (since >= 0 ? "var(--good)" : "var(--bad)");
    const members = (data.team && data.team.members) || [];
    members.forEach(function (m) {
      const p = people[m.id]; if (!p) return;
      p.status = m.status; p.doing = m.doing || ""; p.why = m.why || "";
      const ev = (m.events && m.events[0]) || null;
      p.event = ev ? ev.text : ""; p.tone = ev ? ev.tone : "neutral";
      if (ev && lastData && lastEventTs[m.id] != null && ev.ts > lastEventTs[m.id]) handoff(m.id);
      if (ev) lastEventTs[m.id] = ev.ts;
    });
    const closed = ((data.trades || {}).closed || [])[0];
    if (closed) {
      const key = closed.coin + "|" + closed.closed_at;
      if (lastData && lastClosedKey && key !== lastClosedKey) toSafe(closed);
      lastClosedKey = key;
    }
    const alerts = (data.alerts || []);
    statusEl.textContent = alerts.length ? alerts[0].text : (members.length ? "Live from the bot's own ledger" : "Waiting for the team");
    if (alerts.length) statusEl.className = alerts[0].level === "bad" ? "bad" : "";
    lastData = data;
  }

  // ------------------------------------------------------------- choreography
  function handoff(id) {
    const i = PIPELINE.indexOf(id);
    const next = i >= 0 && i + 1 < PIPELINE.length ? PIPELINE[i + 1] : null;
    const p = people[id]; if (!p || p.walking) return;
    const target = next && people[next] ? { x: people[next].home.x - 30, y: people[next].home.y } : null;
    if (!target) { p.bubbleUntil = Date.now() + 5000; return; }
    p.walking = true; p.bubbleUntil = Date.now() + 9000;
    walks.push({ id: id, path: [target, { x: p.home.x, y: p.home.y }], i: 0 });
  }
  function toSafe(closed) {
    const p = people.broker; if (!p) return;
    const won = (closed.pnl_usd || 0) >= 0;
    p.walking = true; p.bubbleUntil = Date.now() + 12000;
    p.event = (won ? "Closed " : "Closed ") + (closed.coin || "a trade") + " " + (won ? "+" : "") + fmtUsd(closed.pnl_usd);
    p.tone = won ? "good" : "bad";
    walks.push({ id: "broker", path: [{ x: safe.x - 22, y: safe.y + safe.h - 10 }, { x: p.home.x, y: p.home.y }],
                 i: 0, onArrive: function () {
                   drops.push({ x: safe.x + safe.w / 2, y: safe.y - 6, vy: won ? 1.6 : -1.2, born: Date.now(),
                                text: (won ? "+" : "") + fmtUsd(closed.pnl_usd), color: won ? "#46c67a" : "#e0564f" });
                   safe.flash = { until: Date.now() + 1500, color: won ? "#46c67a" : "#e0564f" };
                 } });
  }

  // ------------------------------------------------------------- drawing
  function roundRect(x, y, w, h, r, fill, stroke) {
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
    if (fill) { ctx.fillStyle = fill; ctx.fill(); } if (stroke) { ctx.strokeStyle = stroke; ctx.stroke(); }
  }
  function clip(text, max) { text = String(text || ""); return text.length > max ? text.slice(0, max - 1) + "…" : text; }
  function bubble(x, y, lines, color) {
    ctx.font = "12px ui-sans-serif, system-ui, sans-serif";
    const w = Math.min(world.w - 20, Math.max.apply(null, lines.map(function (l) { return ctx.measureText(l).width; })) + 16);
    const h = 8 + 15 * lines.length;
    let bx = Math.max(10, Math.min(world.w - w - 10, x - w / 2)), by = y - h - 30;
    if (by < 50) by = y + 34;
    roundRect(bx, by, w, h, 8, "#f7f5ee", color || "#777");
    ctx.fillStyle = "#1a1a1a";
    lines.forEach(function (l, i) { ctx.fillText(l, bx + 8, by + 15 + 15 * i); });
  }
  function wrap(text, max) {
    const words = clip(text, 150).split(" "), out = []; let line = "";
    words.forEach(function (w) { if ((line + " " + w).trim().length > max) { out.push(line.trim()); line = w; } else { line += " " + w; } });
    if (line.trim()) out.push(line.trim());
    return out.slice(0, 3);
  }
  function drawDesk(p, t) {
    const d = p.desk, col = COLORS[p.id] || "#888";
    roundRect(d.x - 42, d.y - 14, 84, 28, 6, "#2a3146", "#3a4258");            // desk
    roundRect(d.x - 14, d.y - 30, 28, 18, 3, p.status === "working" ? "#1d2a3a" : "#161b26", col); // monitor
    if (p.status === "working") {                                              // typing light
      ctx.fillStyle = col; ctx.globalAlpha = 0.6 + 0.4 * Math.sin(t / 150 + p.phase); ctx.fillRect(d.x - 9, d.y - 26, 18, 2); ctx.globalAlpha = 1;
    }
    ctx.fillStyle = "#9a9890"; ctx.font = "11px ui-sans-serif, system-ui, sans-serif"; ctx.textAlign = "center";
    ctx.fillText(p.name + " · " + clip(p.role, 26), d.x, d.y + 30); ctx.textAlign = "left";
  }
  function drawPerson(p, t) {
    if (p.status === "absent") { ctx.fillStyle = "#555"; ctx.font = "11px sans-serif"; ctx.textAlign = "center"; ctx.fillText("(not built yet)", p.desk.x, p.desk.y + 30); ctx.textAlign = "left"; return; }
    const col = COLORS[p.id] || "#888", bob = p.walking ? Math.sin(t / 90) * 2 : (p.status === "working" ? Math.sin(t / 400 + p.phase) * 1.2 : 0);
    const x = p.x, y = p.y + bob;
    ctx.fillStyle = "rgba(0,0,0,.35)"; ctx.beginPath(); ctx.ellipse(x, y + 16, 10, 4, 0, 0, 6.28); ctx.fill();
    roundRect(x - 8, y - 4, 16, 20, 5, col);                                   // body
    ctx.fillStyle = "#f1d3b6"; ctx.beginPath(); ctx.arc(x, y - 12, 8, 0, 6.28); ctx.fill(); // head
    ctx.fillStyle = "#222"; ctx.fillRect(x - 3, y - 13, 2, 2); ctx.fillRect(x + 1, y - 13, 2, 2);
    if (p.status === "idle") { ctx.fillStyle = "#9a9890"; ctx.font = "11px sans-serif"; ctx.fillText("z", x + 10, y - 20 + Math.sin(t / 500) * 2); }
    if (p.status === "blocked") { ctx.fillStyle = "#e0564f"; ctx.font = "bold 13px sans-serif"; ctx.fillText("!", x + 10, y - 16); }
    if (p.status === "waiting") { ctx.fillStyle = "#9a9890"; ctx.font = "11px sans-serif"; ctx.fillText("…", x + 9, y - 16); }
  }
  function drawSafe(t) {
    const flash = safe.flash && safe.flash.until > Date.now() ? safe.flash.color : null;
    roundRect(safe.x, safe.y, safe.w, safe.h, 10, "#1b2130", flash || "#4a5370");
    ctx.strokeStyle = flash || "#6b7490"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(safe.x + safe.w - 26, safe.y + safe.h / 2, 11, 0, 6.28); ctx.stroke(); ctx.lineWidth = 1;
    ctx.fillStyle = "#9a9890"; ctx.font = "11px ui-sans-serif, system-ui, sans-serif"; ctx.fillText(clip(safe.label, 22), safe.x + 10, safe.y + 18);
    ctx.fillStyle = "#e8e6df"; ctx.font = "bold 20px ui-sans-serif, system-ui, sans-serif"; ctx.fillText(fmtUsd(safe.usd), safe.x + 10, safe.y + 44);
    ctx.fillStyle = "#9a9890"; ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
    ctx.fillText(safe.sol == null ? "wallet: not read yet" : "wallet " + Number(safe.sol).toFixed(3) + " SOL", safe.x + 10, safe.y + 64);
    ctx.fillText("THE SAFE", safe.x + 10, safe.y - 6);
  }
  function step(dt) {
    walks.slice().forEach(function (w) {
      const p = people[w.id]; if (!p) { walks.splice(walks.indexOf(w), 1); return; }
      const target = w.path[w.i], dx = target.x - p.x, dy = target.y - p.y, dist = Math.hypot(dx, dy), speed = 0.09 * dt;
      if (dist <= speed) {
        p.x = target.x; p.y = target.y;
        if (w.i === 0 && w.onArrive) { w.onArrive(); w.onArrive = null; w.pause = Date.now() + 900; }
        if (w.pause && Date.now() < w.pause) return;
        w.i += 1;
        if (w.i >= w.path.length) { p.walking = false; walks.splice(walks.indexOf(w), 1); }
      } else { p.x += dx / dist * speed; p.y += dy / dist * speed; }
    });
    drops.slice().forEach(function (d) { d.y += d.vy * dt / 16; if (Date.now() - d.born > 1800) drops.splice(drops.indexOf(d), 1); });
  }
  let lastT = performance.now();
  function frame(t) {
    const dt = Math.min(50, t - lastT); lastT = t; step(dt);
    ctx.clearRect(0, 0, world.w, world.h);
    ctx.fillStyle = "#0f1219"; ctx.fillRect(0, 0, world.w, world.h);                       // floor
    ctx.strokeStyle = "#151a24"; for (let gx = 0; gx < world.w; gx += 40) { ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, world.h); ctx.stroke(); }
    for (let gy = 0; gy < world.h; gy += 40) { ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(world.w, gy); ctx.stroke(); }
    ctx.fillStyle = "#9a9890"; ctx.font = "12px ui-sans-serif, system-ui, sans-serif"; ctx.fillText("NIGHTCRAWLER TRADING FLOOR", 14, 24);
    if (offline) { ctx.fillStyle = "#e0564f"; ctx.fillText("the office is dark: no data", 14, 42); }
    MEMBERS.forEach(function (m) { const p = people[m.id]; if (p) drawDesk(p, t); });
    drawSafe(t);
    MEMBERS.forEach(function (m) { const p = people[m.id]; if (p) drawPerson(p, t); });
    const now = Date.now();
    let shown = 0;
    MEMBERS.forEach(function (m) {
      const p = people[m.id]; if (!p || p.status === "absent") return;
      const must = p.pinned || p.walking;
      const show = must || (p.bubbleUntil && p.bubbleUntil > now && shown < 2);
      if (!show) return;
      if (!must) shown += 1;
      const text = p.event || p.doing || p.why || ""; if (!text) return;
      bubble(p.x, p.y - 20, wrap(text, world.w > 700 ? 46 : 30), p.tone === "good" ? "#46c67a" : p.tone === "bad" ? "#e0564f" : "#777");
    });
    drops.forEach(function (d) { ctx.fillStyle = d.color; ctx.font = "bold 14px ui-sans-serif, system-ui, sans-serif"; ctx.textAlign = "center"; ctx.fillText(d.text, d.x, d.y); ctx.textAlign = "left"; });
    // rotate idle chatter: one member speaks every few seconds so the floor never looks dead
    if (!offline && Math.floor(t / 4000) !== frame.lastTick) {
      frame.lastTick = Math.floor(t / 4000);
      const ids = MEMBERS.map(function (m) { return m.id; }).filter(function (id) { const p = people[id]; return p && p.status !== "absent" && (p.doing || p.event); });
      if (ids.length) { const p = people[ids[frame.lastTick % ids.length]]; p.bubbleUntil = now + 3500; }
    }
    requestAnimationFrame(frame);
  }
  canvas.addEventListener("click", function (e) {
    const r = canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    MEMBERS.forEach(function (m) { const p = people[m.id]; if (!p) return; const hit = Math.hypot(p.x - x, p.y - y) < 26; if (hit) p.pinned = !p.pinned; });
  });
  async function tick() {
    try { const d = await fetchPage(); if (d) apply(d); }
    catch (e) { setOffline("Cannot reach the bot right now"); }
    clockEl.textContent = lastOkAt ? "updated " + new Date(lastOkAt).toLocaleTimeString() : "";
  }
  window.addEventListener("resize", layout);
  layout(); tick(); setInterval(function () { if (document.visibilityState === "visible") tick(); }, REFRESH_MS);
  requestAnimationFrame(frame);
})();
"""


def _sha256_source(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii") + "'"


#: Sent with ``/office``: nothing loads from anywhere; only this exact inline script and style run.
OFFICE_CSP = (
    f"default-src 'none'; script-src {_sha256_source(_SCRIPT)}; style-src {_sha256_source(_STYLE)}; "
    "connect-src 'self'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def render_office_html(settings: Settings) -> str:
    """The complete office page (static; the script draws live data). Pure: no ledger data, no secrets."""
    live = settings.is_live
    mode = "LIVE" if live else "PAPER"
    members = "".join(
        f'<span data-id="{html.escape(mid)}" data-name="{html.escape(name)}" data-role="{html.escape(role)}"></span>'
        for mid, name, role in MEMBERS
    )
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<meta name="color-scheme" content="dark">\n<meta name="theme-color" content="#0b0d12">\n'
        '<meta name="robots" content="noindex, nofollow">\n<meta name="referrer" content="no-referrer">\n'
        '<meta name="apple-mobile-web-app-capable" content="yes">\n'
        f'<link rel="icon" href="data:,">\n<title>nightcrawler · the office · {mode.lower()}</title>\n'
        f"<style>{_STYLE}</style>\n</head>\n"
        f'<body data-refresh="{REFRESH_S}" data-pipeline="{",".join(PIPELINE)}">\n'
        f'<header><b class="mode{" live" if live else ""}" id="mode">{mode}</b>'
        '<a href="./">← the page</a>'
        '<span class="money"><b id="money">—</b><small id="since"></small></span></header>\n'
        f'<div id="members" hidden>{members}</div>\n'
        '<canvas id="stage" aria-label="The team at work: one desk per member, the safe shows the money"></canvas>\n'
        '<footer><span id="status">Loading the office…</span><span id="clock"></span></footer>\n'
        f"<script>{_SCRIPT}</script>\n</body>\n</html>\n"
    )
