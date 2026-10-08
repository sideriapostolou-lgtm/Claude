"""The ONE dashboard page at ``/`` (owner: O6): built for an owner who checks the bot from a phone.

Top to bottom, in plain words: money (a big dollar number and a chart), the team (one row per bot member,
tap for its last events), trades, learning (the Coach), "ready for real money?" (a six-step checklist)
and, small at the bottom, receipts and service usage. Data: ``/api/page``
(:func:`nightcrawler.pagestate.build_page_state`), fetched every :data:`REFRESH_S` seconds while the tab is
visible and at once when it comes back.

Pure and static: :func:`render_page_html` never puts ledger data into the HTML. The inline script inserts
every value as TEXT (``textContent``/``append`` of strings, ``createElementNS`` + numeric attributes for the
chart) and never parses markup, so a coin called ``<img src=x onerror=...>`` is just text. The inline
script and style are allowed by their sha256 hashes only (:data:`PAGE_CSP`); nothing loads from anywhere
else. This module has no dependency on the dashboard, so ``nightcrawler.dashboard`` can import it.
"""

from __future__ import annotations

import base64
import hashlib
import html

from nightcrawler import __version__
from nightcrawler.config import Settings

__all__ = ["LEARNING_RULE", "MEMBERS", "PAGE_CSP", "REFRESH_S", "render_page_html"]

REFRESH_S = 15
#: (id, name, what it does) in display order; all but the Coach are team-room panels.
MEMBERS: tuple[tuple[str, str, str], ...] = (
    ("crawler", "Crawler", "finds new coins"),
    ("cocoon", "Cocoon", "throws out rugs and scams"),
    ("strategy", "Strategy", "waits for the setup"),
    ("radar", "Radar", "checks right before buying, watches for danger"),
    ("judge", "Jev", "AI judge, may be switched off"),
    ("broker", "Broker", "places the trades"),
    ("risk", "Risk", "protects the money"),
    ("receipts", "Receipts", "tamper-proof log"),
    ("coach", "Coach", "the self-learning system"),
)
LEARNING_RULE = "The Coach can turn real trading OFF on its own, never ON."

_STYLE = r"""
:root{color-scheme:light;--page:#f5f5f2;--card:#fff;--ink:#121211;--ink2:#56554f;--muted:#8b8a84;--hair:#e3e2db;
--border:rgba(18,18,17,.10);--accent:#2a6fd6;--area:rgba(42,111,214,.10);--up:#0a7a2a;--down:#c42f2a;
--good:#14a33a;--warn:#e9a20f;--warn-ink:#7a5200;--critical:#d33a3a;--paper:#2a6fd6;--live:#d33a3a;
--chip:#f1f1ec;--alert:#b8261f}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--page:#0e0e0d;--card:#1a1a18;--ink:#f3f3ef;
--ink2:#bebdb5;--muted:#8b8a84;--hair:#2f2f2c;--border:rgba(255,255,255,.10);--accent:#5d9cf0;
--area:rgba(93,156,240,.16);--up:#45d06e;--down:#ff7b72;--good:#2fbf57;--warn:#f0b43a;--warn-ink:#f4c968;
--critical:#ff5f5a;--paper:#2f73d8;--live:#e0413c;--chip:#232320;--alert:#9e2019}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--page);color:var(--ink);font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,
sans-serif;padding:12px 16px calc(28px + env(safe-area-inset-bottom))}
main{max-width:640px;margin:0 auto}
.top{display:flex;align-items:center;gap:8px;min-height:32px;font-size:13px;color:var(--ink2)}
.top .name{font-weight:700;color:var(--ink);font-size:15px}
.top .updated{margin-left:auto;text-align:right}
.mode{display:inline-block;color:#fff;background:var(--paper);border-radius:6px;padding:1px 7px;font-size:12px;
font-weight:800;letter-spacing:.08em}
.mode.live{background:var(--live)}
.alert{margin-top:8px;padding:10px 14px;border-radius:12px;font-weight:600;font-size:14px;overflow-wrap:anywhere}
.alert.bad{background:var(--alert);color:#fff}
.alert.warn{background:var(--warn);color:#1c1400}
.card{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:16px;margin-top:12px;
min-width:0}
main.stale .card{opacity:.6}
h2{font-size:17px;font-weight:700;margin:0;display:flex;justify-content:space-between;align-items:baseline;gap:8px}
h2 small{font-size:13px;font-weight:500;color:var(--ink2);text-align:right}
.help{color:var(--ink2);font-size:13px;margin:6px 0 0;overflow-wrap:anywhere}
.empty{color:var(--ink2);font-size:14px;margin:10px 0 0}
.num{font-variant-numeric:tabular-nums;white-space:nowrap}
.up{color:var(--up)}.down{color:var(--down)}
.hero{font-size:44px;font-weight:700;line-height:1.1;letter-spacing:-.01em;margin-top:6px;
font-variant-numeric:tabular-nums}
.tiles{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:8px;margin-top:12px}
.tile{border:1px solid var(--border);border-radius:12px;padding:8px 12px;min-width:0}
.tile .label{color:var(--ink2);font-size:13px}
.tile b{display:block;font-size:20px;font-weight:700;font-variant-numeric:tabular-nums}
.tile span{font-size:13px;font-variant-numeric:tabular-nums}
.chart{margin-top:12px;touch-action:pan-y}
.chart svg{display:block;width:100%;height:120px}
.chart .area{fill:var(--area);stroke:none}
.chart .ln{fill:none;stroke:var(--accent);stroke-width:2;stroke-linejoin:round}
.chart .start{stroke:var(--muted);stroke-width:1;stroke-dasharray:4 4}
.chart .cross{stroke:var(--ink2);stroke-width:1}
.readout,.axis{display:flex;justify-content:space-between;gap:8px;font-size:12px;color:var(--ink2);
font-variant-numeric:tabular-nums}
.readout b{color:var(--ink);font-size:14px}
.members{margin-top:8px}
.member{border-top:1px solid var(--hair)}
.member:first-child{border-top:0}
summary{list-style:none;cursor:pointer;display:block;min-height:44px}
summary::-webkit-details-marker{display:none}
.row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 10px;padding:10px 0;align-items:center}
summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:8px}
.who{min-width:0;overflow-wrap:anywhere}
.who b{font-size:16px}
.who small{display:block;color:var(--ink2);font-size:13px}
.doing,.when{grid-column:1/-1;font-size:14px;overflow-wrap:anywhere;min-width:0}
.when{color:var(--ink2);font-size:12px;display:flex;justify-content:space-between;gap:8px}
.when::after{content:"details ▾";color:var(--accent);font-weight:600}
details[open] .when::after{content:"hide ▴"}
.chip{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--border);border-radius:999px;
padding:2px 10px;font-size:13px;font-weight:650;background:var(--chip);white-space:nowrap}
.chip i{width:8px;height:8px;border-radius:50%;background:var(--muted);flex:none}
.chip.working i{background:var(--good)}.chip.waiting i{background:var(--warn)}
.chip.blocked{border-color:var(--critical)}.chip.blocked i{background:var(--critical)}
.more{padding:0 0 12px}
.sub{color:var(--ink2);font-size:13px;font-weight:600;margin:10px 0 0}
ol.events{list-style:none;margin:6px 0 0;padding:0}
ol.events li{display:grid;grid-template-columns:auto minmax(0,1fr);gap:10px;padding:5px 0;font-size:13px;
border-top:1px solid var(--hair);align-items:baseline}
ol.events time{color:var(--ink2);font-variant-numeric:tabular-nums;white-space:nowrap}
ol.events span{overflow-wrap:anywhere;min-width:0}
ol.events li.good span::before,ol.events li.bad span::before{content:"";display:inline-block;width:7px;height:7px;
border-radius:50%;margin-right:6px;vertical-align:1px;background:var(--good)}
ol.events li.bad span::before{background:var(--critical)}
.bar{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:3px 10px;margin-top:8px;font-size:13px}
.bar>span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar small{grid-column:1/-1;color:var(--ink2);overflow-wrap:anywhere}
.track{grid-column:1/-1;height:8px;border-radius:4px;background:var(--hair);overflow:hidden}
.fill{height:100%;border-radius:4px;background:var(--accent)}
.fill.warn{background:var(--warn)}.fill.over{background:var(--critical)}
.rows>div{border-top:1px solid var(--hair);padding:10px 0}
.rows>div:first-child{border-top:0}
.line{display:flex;justify-content:space-between;align-items:baseline;gap:10px;min-width:0}
.line>*{min-width:0}
.coin{font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.big{font-size:17px;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
.meta{color:var(--ink2);font-size:13px;margin-top:2px;overflow-wrap:anywhere}
.tag{display:inline-block;font-size:12px;font-weight:700;border-radius:6px;padding:0 6px;margin-left:6px;
background:var(--chip);border:1px solid var(--border);vertical-align:1px}
.lead{font-size:16px;font-weight:650;margin:10px 0 0;overflow-wrap:anywhere}
.rule{margin:12px 0 0;padding:10px 12px;border-radius:10px;background:var(--chip);font-size:14px;font-weight:600}
.verdict{font-size:19px;font-weight:700;margin:8px 0 0}
.verdict.ready{color:var(--up)}
.warning{margin:8px 0 0;color:var(--critical);font-weight:600;font-size:14px}
.warning[hidden]{display:none}
ol.checks{list-style:none;margin:8px 0 0;padding:0}
ol.checks li{display:grid;grid-template-columns:26px minmax(0,1fr);gap:10px;padding:9px 0;
border-top:1px solid var(--hair)}
ol.checks li:first-child{border-top:0}
.mark{width:24px;height:24px;border-radius:50%;border:2px solid var(--muted);display:flex;align-items:center;
justify-content:center;font-size:14px;font-weight:800;color:#fff;margin-top:1px}
.mark.done{border-color:var(--good);background:var(--good)}
ol.checks b{display:block;font-size:15px}
ol.checks small{display:block;color:var(--ink2);font-size:13px;overflow-wrap:anywhere}
#receipts h2,#usage h2{font-size:15px}
.broken{color:var(--critical);font-weight:700}
.okay{color:var(--up);font-weight:700}
details.about{margin-top:6px}
details.about summary{padding:10px 0 0;color:var(--accent);font-weight:600;font-size:14px}
details.about p{color:var(--ink2);font-size:13px;margin:6px 0 0}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;word-break:break-all}
#about{margin-top:12px}
footer{color:var(--ink2);font-size:12px;text-align:center;margin-top:18px}
"""

_SCRIPT = r"""
"use strict";
(() => {
  const REFRESH_MS = Number(document.body.dataset.refresh || 15) * 1000;
  const SVG = "http://www.w3.org/2000/svg";
  const MINUS = "−";
  const $ = (id) => document.getElementById(id);
  let token = null, timer = null, last = null, lastOkAt = null, serverOffset = 0;

  const params = new URLSearchParams(location.search);
  if (params.has("token")) {
    token = params.get("token");
    params.delete("token");
    const rest = params.toString();
    history.replaceState(null, "", location.pathname + (rest ? "?" + rest : "") + location.hash);
  }

  // ---------------------------------------------------------------- helpers: text only, never markup
  function el(tag, cls, ...kids) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    for (const k of kids) if (k !== null && k !== undefined && k !== false) node.append(k);
    return node;
  }
  // Fill a node. Missing parts are dropped: replaceChildren(null) would show the word "null".
  function put(node, ...kids) {
    node.replaceChildren(...kids.filter((k) => k !== null && k !== undefined && k !== false));
  }
  function svg(tag, attrs) {
    const node = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
    return node;
  }
  const isNum = (v) => typeof v === "number" && isFinite(v);
  const sign = (v, signed) => (v < 0 ? MINUS : signed && v > 0 ? "+" : "");
  const tone = (v) => (isNum(v) && v > 0 ? "up" : isNum(v) && v < 0 ? "down" : "");
  const nowS = () => Date.now() / 1000 + serverOffset;
  function usd(v, signed) {
    if (!isNum(v)) return "—";
    const a = Math.abs(v);
    return sign(v, signed) + "$" + (a >= 1000 ? a.toLocaleString(undefined, {maximumFractionDigits: 0}) : a.toFixed(2));
  }
  function pct(v) { return isNum(v) ? sign(v, true) + Math.abs(v).toFixed(1) + "%" : ""; }
  function price(v) {
    if (!isNum(v) || v <= 0) return "—";
    const s = v >= 1 ? v.toFixed(2) : v.toPrecision(3);
    return "$" + (s.includes("e") ? v.toFixed(12).replace(/0+$/, "") : s);
  }
  function dur(s) {
    s = Math.max(0, s);
    if (s < 60) return Math.round(s) + " s";
    if (s < 3600) return Math.floor(s / 60) + " min";
    if (s < 86400) return Math.floor(s / 3600) + " h " + Math.floor(s % 3600 / 60) + " min";
    return Math.floor(s / 86400) + " d " + Math.floor(s % 86400 / 3600) + " h";
  }
  function ago(ts) { return isNum(ts) ? dur(nowS() - ts) + " ago" : ""; }
  function when(ts) {
    if (!isNum(ts)) return "";
    const d = new Date(ts * 1000);
    const today = d.toDateString() === new Date(nowS() * 1000).toDateString();
    return today ? d.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})
      : d.toLocaleString([], {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"});
  }
  const WORD = {working: "Working", idle: "Idle", waiting: "Waiting", blocked: "Blocked"};
  function chip(status) { return el("span", "chip " + status, el("i"), WORD[status] || status); }
  function track(value, cls) {
    const fill = el("div", "fill" + (cls ? " " + cls : ""));
    // a tiny share stays visible; exactly zero draws nothing
    fill.style.width = (value > 0 ? Math.max(0.015, Math.min(1, value)) * 100 : 0).toFixed(1) + "%";
    return el("div", "track", fill);
  }
  // No track at all for an unknown value: an empty track read as a FULL bar in dark mode.
  function bar(label, value, text, cls, note) {
    return el("div", "bar", el("span", null, label), el("b", "num", text || ""),
      isNum(value) ? track(value, cls) : null, note ? el("small", null, note) : null);
  }

  // ---------------------------------------------------------------- A. money
  function renderMoney(m) {
    $("money-label").textContent = m.label;
    $("money-value").textContent = isNum(m.usd) ? usd(m.usd) : "—";
    for (const [id, part] of [["since", m.since_start], ["today", m.today]]) {
      const value = $(id + "-usd"), share = $(id + "-pct");
      value.textContent = usd(part.usd, true);
      value.className = "num " + tone(part.usd);
      share.textContent = pct(part.pct);
      share.className = tone(part.pct);
    }
    const help = [];
    if (isNum(m.start_usd)) help.push("Started with " + usd(m.start_usd) + ".");
    if (isNum(m.sol_price_effect_usd) && Math.abs(m.sol_price_effect_usd) >= 0.01) {
      help.push("The price of SOL itself moved the value " + usd(m.sol_price_effect_usd, true)
        + " on top: not the bot's doing.");
    }
    if (!isNum(m.usd)) help.push("No money check yet: the first one comes about a minute after the bot starts.");
    $("money-help").textContent = help.join(" ");
    put($("chart"), chart(m.curve || [], m.start_usd, m.chart_ready));
  }

  function chart(curve, startUsd, ready) {
    if (!ready || curve.length < 2) return el("p", "empty", "The chart starts after the first hour.");
    const W = 600, H = 120, pad = 6;
    const ts = curve.map((p) => p[0]), vs = curve.map((p) => p[1]);
    let lo = Math.min(...vs), hi = Math.max(...vs);
    if (isNum(startUsd)) { lo = Math.min(lo, startUsd); hi = Math.max(hi, startUsd); }
    if (hi - lo < 0.01) { hi += 0.5; lo -= 0.5; }
    const t0 = ts[0], t1 = ts[ts.length - 1];
    const x = (t) => (t - t0) / Math.max(1, t1 - t0) * W;
    const y = (v) => pad + (1 - (v - lo) / (hi - lo)) * (H - 2 * pad);
    const pts = curve.map((p) => x(p[0]).toFixed(1) + "," + y(p[1]).toFixed(1));
    const plot = svg("svg", {viewBox: "0 0 " + W + " " + H, preserveAspectRatio: "none", "aria-hidden": "true"});
    plot.append(svg("path", {d: "M" + pts.join("L") + "L" + W + "," + H + "L0," + H + "Z", class: "area"}));
    if (isNum(startUsd)) {
      plot.append(svg("line", {x1: 0, x2: W, y1: y(startUsd), y2: y(startUsd), class: "start",
        "vector-effect": "non-scaling-stroke"}));
    }
    plot.append(svg("polyline", {points: pts.join(" "), class: "ln", "vector-effect": "non-scaling-stroke"}));
    const cross = svg("line", {x1: 0, x2: 0, y1: 0, y2: H, class: "cross", visibility: "hidden",
      "vector-effect": "non-scaling-stroke"});
    plot.append(cross);
    const value = el("b", "num"), at = el("span");
    const box = el("div", "chart", el("p", "sub", "Total value over time (the price of SOL moves it too)"),
      el("div", "readout", el("span", null, value, " ", at),
      el("span", null, "high " + usd(Math.max(...vs)) + " · low " + usd(Math.min(...vs)))), plot,
      el("div", "axis", el("span", null, when(t0)), el("span", null, isNum(startUsd) ? "dashed line: the start" : ""),
        el("span", null, "now")));
    box.setAttribute("role", "img");
    box.setAttribute("aria-label", "Money over time, from " + usd(vs[0]) + " to " + usd(vs[vs.length - 1]));
    function show(i, active) {
      value.textContent = usd(vs[i]);
      at.textContent = active ? when(ts[i]) : "now";
      cross.setAttribute("x1", x(ts[i]));
      cross.setAttribute("x2", x(ts[i]));
      cross.setAttribute("visibility", active ? "visible" : "hidden");
    }
    function nearest(clientX) {
      const r = plot.getBoundingClientRect();
      const t = t0 + (clientX - r.left) / Math.max(1, r.width) * (t1 - t0);
      let best = 0;
      for (let i = 1; i < ts.length; i++) if (Math.abs(ts[i] - t) < Math.abs(ts[best] - t)) best = i;
      return best;
    }
    plot.addEventListener("pointermove", (ev) => show(nearest(ev.clientX), true));
    plot.addEventListener("pointerdown", (ev) => show(nearest(ev.clientX), true));
    plot.addEventListener("pointerleave", () => show(vs.length - 1, false));
    show(vs.length - 1, false);
    return box;
  }

  // ---------------------------------------------------------------- B. the team
  function events(list) {
    if (!list.length) return el("p", "empty", "Nothing recorded yet.");
    return el("ol", "events", ...list.map((e) => {
      const item = el("li", e.tone, el("time", null, when(e.ts)), el("span", null, e.text));
      item.title = new Date(e.ts * 1000).toLocaleString();
      return item;
    }));
  }
  const BAR_TITLES = {strategy: "How close each watched coin is to the setup",
    cocoon: "Why coins were thrown out, last 24 h"};
  function renderTeam(t) {
    const c = t.counts;
    $("team-counts").textContent = ["working", "waiting", "idle", "blocked"].filter((k) => c[k])
      .map((k) => c[k] + " " + k).join(" · ");
    for (const m of t.members) {
      const node = $("m-" + m.id);
      if (!node) continue;
      node.className = "member " + m.status;
      put(node.querySelector(".state"), chip(m.status));
      node.querySelector(".doing").textContent = m.doing || "";
      node.querySelector(".when").textContent = isNum(m.last_activity) ? "last active " + ago(m.last_activity)
        : "no activity recorded yet";
      const bars = (m.bars || []).map((b) => bar(b.label, b.value, b.text, "", b.note));
      put(node.querySelector(".more"), bars.length ? el("p", "sub", BAR_TITLES[m.id] || "") : null, ...bars,
        el("p", "sub", "Last events"), events(m.events));
    }
  }

  // ---------------------------------------------------------------- C. trades
  function renderTrades(tr) {
    $("trades-count").textContent = tr.open.length + " of " + tr.max_open + " open";
    const open = tr.open.map((p) => el("div", null,
      el("div", "line", el("span", "coin", p.coin), el("span", "big " + tone(p.pnl_usd), usd(p.pnl_usd, true))),
      el("div", "meta", "Bought at " + price(p.entry_usd) + " · now " + price(p.now_usd) + " · "
        + pct(p.pnl_pct) + " · held " + dur(nowS() - p.opened_at)
        + (p.partial ? " · half already sold at a profit" : ""))));
    const closed = tr.closed.map((p) => el("div", null,
      el("div", "line", el("span", "coin", p.coin, el("span", "tag", p.result === "won" ? "Won" : p.result === "lost"
        ? "Lost" : "Even")), el("span", "big " + tone(p.pnl_usd), usd(p.pnl_usd, true))),
      el("div", "meta", p.why + " · " + pct(p.pnl_pct) + " · closed " + ago(p.closed_at))));
    if (!open.length && !closed.length) {
      put($("trades-body"), el("p", "empty", "No trades yet — on most days the bot buys nothing, that's on purpose."));
      return;
    }
    put($("trades-body"), el("p", "sub", "Open now"),
      open.length ? el("div", "rows", ...open) : el("p", "empty", "No open trades right now."),
      closed.length ? el("p", "sub", "Last " + closed.length + " finished") : null,
      closed.length ? el("div", "rows", ...closed) : null);
  }

  // ---------------------------------------------------------------- D. learning
  function renderLearning(l) {
    $("learn-headline").textContent = l.headline;
    const repeats = l.state && l.headline.toLowerCase().includes(l.state.toLowerCase());
    $("learn-state").textContent = l.state && !repeats ? "Stage: " + l.state : "";
    const variants = l.variants.map((v) => bar(v.name, v.proof,
      (isNum(v.n) ? v.n + " trades" : "") + (isNum(v.avg) ? " · " + pct(v.avg) + " a trade" : ""), "",
      isNum(v.proof) ? "proof " + Math.round(v.proof * 100) + "% of the way" : "proof not measured yet"));
    put($("learn-variants"), variants.length ? el("p", "sub", "Best strategies on trial") : null,
      variants.length ? el("p", "help", "Proof: how close a strategy is to beating trading costs on data it never saw.")
        : null, ...variants);
    $("learn-data").textContent = l.data || "";
  }

  // ---------------------------------------------------------------- E. ready for real money?
  function renderReady(r) {
    const head = $("ready-headline");
    head.textContent = r.headline;
    head.className = "verdict" + (r.ready ? " ready" : "");
    const warning = $("ready-warning");
    warning.hidden = !r.warning;
    warning.textContent = r.warning || "";
    put($("ready-items"), ...r.items.map((i, n) => {
      const mark = el("span", "mark" + (i.done ? " done" : ""), i.done ? "✓" : "");
      mark.setAttribute("aria-label", i.done ? "done" : "not done");
      return el("li", null, mark,
        el("div", null, el("b", null, (n + 1) + ". " + i.label), el("small", null, i.reason)));
    }));
  }

  // ---------------------------------------------------------------- F. receipts & usage
  function renderReceipts(r) {
    const status = r.verified === false ? el("span", "broken", "✗ broken at #" + r.first_bad_seq)
      : r.verified === true ? el("span", "okay", "chain verified ✓") : el("span", null, "not checked yet");
    put($("receipts-line"), r.count.toLocaleString() + " entries · ", status);
    $("receipts-head").textContent = r.count ? "Latest fingerprint: " + r.head : "No entries yet.";
  }
  function renderUsage(u, about) {
    // with a budget: a bar (amber from 80 %, red when over); without one: a single line of counts
    put($("usage-rows"), ...u.map((row) => isNum(row.pct)
      ? bar(row.label, row.pct / 100, Math.round(row.pct) + "%",
        row.level === "over" ? "over" : row.level === "warn" ? "warn" : "", row.text)
      : bar(row.label, null, row.text)));
    const parts = ["version " + about.version];
    if (isNum(about.uptime_s)) parts.push("running for " + dur(about.uptime_s));
    if (about.commit) parts.push("build " + about.commit);
    $("about").textContent = parts.join(" · ");
  }

  function render(s) {
    last = s;
    const mode = $("mode");
    mode.textContent = s.mode;
    mode.className = "mode" + (s.mode === "LIVE" ? " live" : "");
    put($("alerts"), ...s.alerts.map((a) => el("div", "alert " + a.level, a.text)));
    renderMoney(s.money);
    renderTeam(s.team);
    renderTrades(s.trades);
    renderLearning(s.learning);
    renderReady(s.ready);
    renderReceipts(s.receipts);
    renderUsage(s.usage, s.about);
    tick();
  }

  // ---------------------------------------------------------------- refresh: only while the tab is visible
  function offline(text) {
    const b = $("offline");
    b.hidden = !text;
    b.textContent = text || "";
    $("main").classList.toggle("stale", Boolean(text) && last !== null);
  }
  function tick() {
    if (!lastOkAt) return;
    $("updated").textContent = "updated " + dur((Date.now() - lastOkAt) / 1000) + " ago";
  }
  async function refresh() {
    clearTimeout(timer);
    try {
      const url = "api/page" + (token ? "?token=" + encodeURIComponent(token) : "");
      const res = await fetch(url, {cache: "no-store", credentials: "same-origin"});
      if (res.status === 401) {
        offline("Locked: open the link that ends with ?token=…");
      } else if (!res.ok) {
        throw new Error("HTTP " + res.status);
      } else {
        const s = await res.json();
        serverOffset = s.generated_at - Date.now() / 1000;
        lastOkAt = Date.now();
        render(s);
        offline(null);
      }
    } catch (err) {
      offline("Can't reach the bot right now" + (lastOkAt ? " — showing what it said "
        + dur((Date.now() - lastOkAt) / 1000) + " ago" : "") + ". Trying again…");
    } finally {
      if (!document.hidden) timer = setTimeout(refresh, REFRESH_MS);
    }
  }
  document.addEventListener("visibilitychange", () => { if (document.hidden) clearTimeout(timer); else refresh(); });
  setInterval(tick, 5000);
  refresh();
})();
"""


def _sha256_source(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii") + "'"


#: Sent with ``/``: nothing loads from anywhere; only this exact inline script and style run.
PAGE_CSP = (f"default-src 'none'; script-src {_sha256_source(_SCRIPT)}; style-src {_sha256_source(_STYLE)}; "
            "connect-src 'self'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def _member(mid: str, name: str, role: str) -> str:
    return (f'<details class="member" id="m-{mid}"><summary><span class="row">'
            f'<span class="who"><b>{html.escape(name)}</b><small>{html.escape(role)}</small></span>'
            '<span class="state"></span><span class="doing">Loading…</span>'
            '<span class="when"></span></span></summary><div class="more"></div></details>\n')


def render_page_html(settings: Settings) -> str:
    """The complete page (static: the script fills in live data; no ledger data, no secrets). Pure."""
    live = settings.is_live
    mode = "LIVE" if live else "PAPER"
    label = "Real money" if live else "Paper money (pretend)"
    members = "".join(_member(*m) for m in MEMBERS)
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
        "<meta name=\"color-scheme\" content=\"light dark\">\n"
        "<meta name=\"theme-color\" content=\"#f5f5f2\" media=\"(prefers-color-scheme: light)\">\n"
        "<meta name=\"theme-color\" content=\"#0e0e0d\" media=\"(prefers-color-scheme: dark)\">\n"
        "<meta name=\"robots\" content=\"noindex, nofollow\">\n<meta name=\"referrer\" content=\"no-referrer\">\n"
        "<meta name=\"apple-mobile-web-app-capable\" content=\"yes\">\n"
        f"<link rel=\"icon\" href=\"data:,\">\n<title>nightcrawler · {mode.lower()}</title>\n"
        f"<style>{_STYLE}</style>\n</head>\n"
        f"<body data-refresh=\"{REFRESH_S}\">\n<main id=\"main\">\n"
        f"<header class=\"top\"><b class=\"mode{' live' if live else ''}\" id=\"mode\">{mode}</b>"
        f"<span class=\"name\">nightcrawler</span><span class=\"updated\" id=\"updated\">loading…</span></header>\n"
        "<div id=\"alerts\" role=\"status\"></div>\n"
        "<div class=\"alert warn\" id=\"offline\" role=\"status\" hidden></div>\n"

        "<section class=\"card\" id=\"money\">"
        f"<h2>Money <small id=\"money-label\">{label}</small></h2>"
        "<div class=\"hero\" id=\"money-value\">—</div>"
        "<div class=\"tiles\"><div class=\"tile\"><div class=\"label\">Since start</div>"
        "<b id=\"since-usd\">—</b><span id=\"since-pct\"></span></div>"
        "<div class=\"tile\"><div class=\"label\">Today</div><b id=\"today-usd\">—</b><span id=\"today-pct\"></span>"
        "</div></div>"
        "<p class=\"help\">Since start and today count only the bot's own trading, at today's price of SOL.</p>"
        "<p class=\"help\" id=\"money-help\"></p><div id=\"chart\"></div></section>\n"

        "<section class=\"card\" id=\"team\"><h2>The team <small id=\"team-counts\"></small></h2>"
        "<p class=\"help\">Each one is a part of the bot. Tap a name to see what it did last.</p>"
        f"<div class=\"members\">\n{members}</div></section>\n"

        "<section class=\"card\" id=\"trades\"><h2>Trades <small id=\"trades-count\"></small></h2>"
        "<div id=\"trades-body\"><p class=\"empty\">Loading…</p></div>"
        "<p class=\"help\">Dollar amounts use today's price of SOL.</p></section>\n"

        "<section class=\"card\" id=\"learning\"><h2>Learning <small>the Coach</small></h2>"
        "<p class=\"lead\" id=\"learn-headline\">Loading…</p><p class=\"help\" id=\"learn-state\"></p>"
        "<div id=\"learn-variants\"></div><p class=\"help\" id=\"learn-data\"></p>"
        f"<p class=\"rule\">{html.escape(LEARNING_RULE)}</p></section>\n"

        "<section class=\"card\" id=\"ready\"><h2>Ready for real money?</h2>"
        "<p class=\"verdict\" id=\"ready-headline\">Checking…</p>"
        "<p class=\"warning\" id=\"ready-warning\" hidden></p><ol class=\"checks\" id=\"ready-items\"></ol>"
        "<p class=\"help\">Each step turns green only when it is really done. The full guide is "
        "docs/GOING_LIVE.md.</p></section>\n"

        "<section class=\"card\" id=\"receipts\"><h2>Receipts</h2>"
        "<p class=\"meta\" id=\"receipts-line\">Loading…</p>"
        "<details class=\"about\"><summary>What is this?</summary>"
        "<p>Every decision and every trade is sealed into a chain of receipts the moment it happens, before the "
        "bot can see what the price does next. Each receipt carries the fingerprint of the one before it, so "
        "changing or deleting anything later breaks the chain, and the check above turns red.</p>"
        "<p class=\"mono\" id=\"receipts-head\"></p></details></section>\n"

        "<section class=\"card\" id=\"usage\"><h2>Services used</h2>"
        "<p class=\"help\">Calls to the free data services the bot relies on; a bar turns amber at 80% of a "
        "budget.</p><div id=\"usage-rows\"></div><p class=\"meta\" id=\"about\"></p></section>\n"

        f"<footer>nightcrawler v{html.escape(__version__)} · read-only · refreshes every {REFRESH_S} s</footer>\n"
        "</main>\n"
        f"<script>{_SCRIPT}</script>\n</body>\n</html>\n"
    )
