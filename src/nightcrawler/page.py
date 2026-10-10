"""The ONE dashboard page at ``/`` (owner: O6): built for an owner who checks the bot from a phone.

Top to bottom, in plain words: the header's badge and the tab's title say real money only where ``plain.real`` does
(on, real bets still open, or pretend money; nothing before the first answer unless the bot itself runs live), with
the links to the 3D team and its pictures; "In plain words" (``plain``: what the app is, one headline, the real money
with its result, how it bets, its hard limits and the lab's verdict, the practice books, always "pretend", what just
happened, who is who and what the words mean; every sentence is the data's own), the Solana bot's money ("Pretend:"
or "Real:" before a big dollar number, and a chart; under it the Polymarket desk's two books,
paper and real, never added to the SOL wallet or to each other, and the trend desk's paper book, a forward test of
lab 3's 50-day trend rule on BTC, ETH and SOL, never added to anything either), the town (what running the bot costs
against what each desk made, with the trend desk's own line under the bars), the bot wallet (its public address with
a copy button, its SOL and how to fund it from Phantom), the team (one row per bot member with the character who
plays it in the 3D world and the plain words, tap for its report
card and last events; the team's practice record on top and the playbook's counts below, docs/EXPERIENCE.md
§9), trades, learning (the Coach), "ready for real money?" (a six-step checklist)
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
    ("predict", "Polymarket desk", "paper desk on prediction markets"),
)
#: Shown only when the learning module says it really can (``can_stop_trading``), never as static text.
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
.top{display:flex;flex-wrap:wrap;align-items:center;gap:4px 8px;min-height:32px;font-size:13px;color:var(--ink2)}
.top .name{font-weight:700;color:var(--ink);font-size:15px}
.top .updated{margin-left:auto;text-align:right}
.top .links{flex:1 1 100%;display:flex;flex-wrap:wrap;gap:4px 16px;font-size:14px}
.top .links a{color:var(--accent);font-weight:600;padding:4px 0}
.mode{display:inline-block;color:#fff;background:var(--paper);border-radius:6px;padding:1px 7px;font-size:12px;
font-weight:800;letter-spacing:.08em}
.mode.live{background:var(--live)}
.mode[hidden]{display:none}
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
.state{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:4px;max-width:170px}
@media (min-width:480px){.state{max-width:none}}
.skill-chip.good{color:var(--up);border-color:var(--good)}
.skill-chip.bad{color:var(--down);border-color:var(--critical)}
.row .graded{grid-column:1/-1;color:var(--ink2);font-size:13px;overflow-wrap:anywhere;min-width:0}
.row .graded:empty{display:none}
.metric{margin-top:10px;font-size:13px}
.metric .line{flex-wrap:wrap;gap:0 10px}
.metric .line b{font-size:13px;margin-left:auto}
.metric small{display:block;color:var(--ink2);overflow-wrap:anywhere}
.rbar{position:relative;height:14px;margin:6px 6px 2px}
.rbar div{position:absolute}
.rbar .rt{left:0;right:0;top:6px;height:2px;background:var(--hair)}
.rbar .rb{top:2px;height:10px;min-width:3px;border-radius:5px;background:var(--area);border:1px solid var(--accent)}
.rbar .rk{top:0;width:2px;height:14px;margin-left:-1px;background:var(--ink2)}
.rbar .rd{top:2px;width:10px;height:10px;margin-left:-5px;border-radius:50%;background:var(--ink);
border:2px solid var(--card)}
.meta.old{opacity:.6}
.line>.tag{flex:none;margin-left:0}
.spark{margin-top:4px}
.spark svg{display:block;width:100%;height:44px}
.spark .band{fill:var(--area);stroke:none}
.spark .ln{fill:none;stroke:var(--accent);stroke-width:2;stroke-linejoin:round}
.spark .base{stroke:var(--muted);stroke-width:1;stroke-dasharray:3 3}
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
.fill.cost{background:var(--muted)}.fill.up{background:var(--up)}.fill.down{background:var(--down)}
.rows>div{border-top:1px solid var(--hair);padding:10px 0}
.rows>div:first-child{border-top:0}
#town-desks p{margin-top:8px}
.line{display:flex;justify-content:space-between;align-items:baseline;gap:10px;min-width:0}
.line>*{min-width:0}
.coin{font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.big{font-size:17px;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
.meta{color:var(--ink2);font-size:13px;margin-top:2px;overflow-wrap:anywhere}
.tag{display:inline-block;font-size:12px;font-weight:700;border-radius:6px;padding:0 6px;margin-left:6px;
background:var(--chip);border:1px solid var(--border);vertical-align:1px}
.lead{font-size:16px;font-weight:650;margin:10px 0 0;overflow-wrap:anywhere}
.rule{margin:12px 0 0;padding:10px 12px;border-radius:10px;background:var(--chip);font-size:14px;font-weight:600}
.rule[hidden]{display:none}
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
.addr{display:block;margin-top:4px;font-size:14px;-webkit-user-select:all;user-select:all}
button.copy{margin-top:10px;min-height:44px;padding:8px 16px;border-radius:10px;border:1px solid var(--border);
background:var(--accent);color:#fff;font:inherit;font-size:15px;font-weight:650;cursor:pointer}
button.copy:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
footer{color:var(--ink2);font-size:12px;text-align:center;margin-top:18px}
.box{border:1px solid var(--border);border-radius:12px;padding:10px 12px;margin-top:10px;min-width:0}
.box>.meta{font-size:15px;color:var(--ink)}
.box p{margin:6px 0 0}
.box>p:first-child{margin-top:0}
.box.on{border:2px solid var(--live)}
.tag.on{background:var(--live);border-color:var(--live);color:#fff}
.box .verdict-line{font-weight:650;color:var(--ink)}
.box .figs{display:flex;flex-wrap:wrap;gap:0 16px;margin-top:2px}
#plain-about{font-size:15px;color:var(--ink2);margin:8px 0 0}
#plain-now>div{font-size:15px;overflow-wrap:anywhere}
#plain-team .chip{flex:none}
.hero-tag{font-size:20px;font-weight:650;color:var(--ink2);letter-spacing:0}
"""

_SCRIPT = r"""
"use strict";
(() => {
  const REFRESH_MS = Number(document.body.dataset.refresh || 15) * 1000;
  const SVG = "http://www.w3.org/2000/svg";
  const MINUS = "−";
  const MONEY_STALE_S = 300;  // the bot checks the money every minute; older than this is worth saying
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
    const [big, unit, small, unit2] = s < 86400 ? [Math.floor(s / 3600), " h", Math.floor(s % 3600 / 60), " min"]
      : [Math.floor(s / 86400), " d", Math.floor(s % 86400 / 3600), " h"];
    return big + unit + (small ? " " + small + unit2 : "");
  }
  function ago(ts) { return isNum(ts) ? dur(nowS() - ts) + " ago" : ""; }
  function when(ts) {
    if (!isNum(ts)) return "";
    const d = new Date(ts * 1000);
    const today = d.toDateString() === new Date(nowS() * 1000).toDateString();
    return today ? d.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})
      : d.toLocaleString([], {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"});
  }
  const WORD = {working: "Working", idle: "Idle", waiting: "Waiting", blocked: "Blocked", absent: "Not built yet"};
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

  // ---------------------------------------------------------------- 0. in plain words (plain)
  // The whole screen in a few sentences for a newcomer: the headline, the real money (only what the data calls real,
  // with its hard limits and the lab's verdict), the practice books (always "pretend"), what just happened, who is
  // who and what the words mean. Every sentence is the data's own; the page adds only fixed words around them.
  const STATUS_CHIP = {working: "working", waiting: "waiting", idle: "idle", stuck: "blocked"};
  // The header's badge and the tab's title: real money only where the plain words say it (plain.real), and still
  // red while a real bet is open after real betting stopped; before the first answer they claim nothing.
  function moneyWords(r) {
    if (!r) return null;
    if (r.on) return {badge: "REAL MONEY ON", live: true, title: "real money on"};
    if (r.reported === false) return {badge: "REAL MONEY: NO REPORT YET", live: false, title: "real money: no report yet"};
    if (r.open_bets > 0) return {badge: "REAL BETS STILL OPEN", live: true, title: "real bets still open"};
    return {badge: "PRETEND MONEY", live: false, title: "pretend money"};
  }
  function renderPlain(p) {
    if (!p || !p.real || !p.pretend) return;  // older data without the block: the card keeps "Loading…"
    $("plain-about").textContent = p.about || "";
    $("plain-headline").textContent = p.headline;
    const r = p.real, open = r.on || r.open_bets > 0;
    const held = open && isNum(r.at_risk_usd) ? usd(r.at_risk_usd) + (r.on ? " at risk now" : " still in open bets") : null;
    put($("plain-real"), el("div", "box" + (open ? " on" : ""),
      el("div", "line", el("span", "coin", r.label, el("span", "tag" + (open ? " on" : ""),
        r.on ? "ON" : r.reported === false ? "NO REPORT YET" : open ? "OFF FOR NEW BETS" : "OFF"))),
      held || r.result ? el("div", "figs", held ? el("span", "big", held) : null,
        r.result ? el("span", "big", r.result) : null) : null,
      el("p", "meta", r.line), r.how ? el("p", "help", r.how) : null, r.paused ? el("p", "warning", r.paused) : null,
      r.limits ? el("p", "meta", r.limits) : null, r.verdict ? el("p", "help verdict-line", r.verdict) : null,
      r.research ? el("p", "help", r.research) : null));
    const practice = el("div", "box", el("p", "meta", p.pretend.line));  // (the line starts with its own label)
    practice.setAttribute("aria-label", p.pretend.label);
    put($("plain-pretend"), practice);
    put($("plain-now"), ...(p.now.length ? p.now.map((t) => el("div", null, t))
      : [el("p", "empty", "Nothing new in the last six hours.")]));
    put($("plain-team"), ...p.team.map((c) => el("div", "line", el("span", null, c.plain_role),
      el("span", "chip " + (STATUS_CHIP[c.status_word] || "idle"), el("i"), c.status_word))));
    put($("plain-words"), ...p.glossary.map((g) => el("div", null, el("b", null, g.word), el("div", "meta", g.means))));
  }

  // ---------------------------------------------------------------- A. money
  // the Solana bot's wallet: its kind of money said right before the big figure (``live``: the bot runs live)
  function renderMoney(m, live) {
    $("money-label").textContent = m.label;
    put($("money-value"), el("span", "hero-tag", live ? "Real: " : "Pretend: "), isNum(m.usd) ? usd(m.usd) : "—");
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
    if (isNum(m.withdrawn_sol) && m.withdrawn_sol > 0) {
      help.push("Sent back to you so far: " + m.withdrawn_sol.toFixed(4) + " SOL (not counted as a loss).");
    }
    if (!isNum(m.usd)) help.push("No money check yet: the first one comes about a minute after the bot starts.");
    else if (isNum(m.as_of) && nowS() - m.as_of > MONEY_STALE_S) {
      help.unshift("Last money check: " + dur(nowS() - m.as_of) + " ago.");
    }
    $("money-help").textContent = help.join(" ");
    put($("chart"), chart(m.curve || [], m.start_usd, m.chart_ready));
    renderPolymarket(m.polymarket);
    renderTrend(m.trend);
  }

  // The Polymarket desk's two books under the SOL wallet (money.polymarket), never added to it or to each other.
  // The real row only when the venue's own book holds contracts, a real settlement exists or the venue's cash was
  // read; the paper row always. The labels are the data's own; a part the venue has not answered says so. Under
  // them, the risk manager's verdict line(s), and a "paused" tag while it has stopped new buys.
  function renderPolymarket(pm) {
    const box = $("money-polymarket");
    if (!pm || !pm.paper) { put(box); return; }
    const join = (...bits) => bits.filter(Boolean).join(" · ");
    const count = (n, one, many) => (isNum(n) ? n.toLocaleString() + " " + (n === 1 ? one : many) : "");
    const won = (w, s) => (isNum(w) && isNum(s) ? w + "/" + s + " won" : "");
    const row = (book, meta) => el("div", null,
      el("div", "line", el("span", "coin", book.label), el("span", "big " + tone(book.since_start_usd),
        usd(book.since_start_usd, true))),
      el("div", "meta", meta));
    const r = pm.real, p = pm.paper, rows = [];
    if (r) {
      const venue = isNum(r.contracts) ? count(r.contracts, "contract held", "contracts held")
        + (isNum(r.cost_usd) ? ", cost " + usd(r.cost_usd) : "") + (isNum(r.value_usd) ? ", worth " + usd(r.value_usd) + " now" : "")
        : count(r.open, "open position", "open positions") + ", the venue's book not read yet";
      rows.push(row(r, join("settled since start", isNum(r.cash_usd) ? "cash at the venue " + usd(r.cash_usd)
        : "cash at the venue not read yet", venue, join("today " + usd(r.today_usd, true), won(r.won_today, r.settled_today)))));
    }
    const settled = won(p.won_total, p.settled_total);
    rows.push(row(p, join("since start", count(p.open, "open paper position", "open paper positions"),
      "today " + usd(p.today_usd, true), settled ? settled + " since start" : "")));
    // The risk manager's verdict on the current rule's record (pm.guard): its own sentence per book, as text, and
    // a tag while it has stopped buying (the desk's buys, or only the real ones).
    const g = pm.guard, verdicts = g ? [g, g.real].filter((v) => v && v.line).map((v) => el("p", "meta", v.line)) : [];
    const pausedTag = !g ? null : g.paused ? "paused by the risk manager"
      : g.real && g.real.paused ? "real buys paused by the risk manager" : null;
    put(box, el("p", "sub", "Polymarket desk", el("span", "tag", pm.mode === "live" ? "real money ON" : "real money OFF"),
      pausedTag ? el("span", "tag", pausedTag) : null),
      el("div", "rows", ...rows), ...verdicts,
      el("p", "help", "Kept apart from the SOL wallet above, and paper from real: nothing here is added together."));
  }

  // The trend desk's paper book (money.trend) under the Polymarket desk: its own figures, never added to anything.
  // Text only; before its first daily close it says so instead of showing a result.
  function renderTrend(tr) {
    const box = $("money-trend");
    if (!tr || !tr.in_market) { put(box); return; }
    const coins = Object.keys(tr.in_market);
    const ins = coins.filter((c) => tr.in_market[c] === true), outs = coins.filter((c) => tr.in_market[c] !== true);
    const meta = isNum(tr.as_of)
      ? ["since start", "holding the three instead (bought on day one, never touched) "
        + usd(tr.hold_since_start_usd, true), "last day " + usd(tr.today_usd, true),
        ins.length ? "in " + ins.join(", ") : "all cash", ins.length && outs.length ? "out " + outs.join(", ") : "",
        "book " + usd(tr.equity_usd) + " of " + usd(tr.sleeve_usd)]
      : ["no daily close booked yet" + (tr.started ? ": the first is the close of " + tr.started + " (UTC midnight)"
        : "")];
    // lab 3's own figures put the book back to thirds every day for free: shown for comparison, never as the result
    const lab = isNum(tr.as_of) && tr.lab && isNum(tr.lab.since_start_usd) && isNum(tr.lab.hold_since_start_usd)
      ? "lab 3's way (back to thirds every day, for free): rule " + usd(tr.lab.since_start_usd, true) + ", holding "
        + usd(tr.lab.hold_since_start_usd, true) : null;
    put(box, el("p", "sub", "Trend desk", el("span", "tag", "paper only")),
      el("div", "rows", el("div", null,
        el("div", "line", el("span", "coin", tr.label), el("span", "big " + tone(tr.since_start_usd),
          usd(tr.since_start_usd, true))),
        el("div", "meta", meta.filter(Boolean).join(" · ")),
        lab ? el("div", "meta", lab) : null,
        tr.reset_from ? el("div", "meta", "(record restarted " + (tr.started || "today") + ": the earlier record "
          + "could not be read and is kept aside)") : null,
        tr.problem ? el("div", "meta", tr.problem) : null)),
      el("p", "help", "Lab 3's 50-day trend rule on BTC, ETH and SOL, checked once a day after the daily close "
        + "(UTC midnight). Each coin has its own third of the book, as a real account would hold it: a sell puts that "
        + "coin's money in its own cash and a buy spends only that cash; nothing is moved between the thirds. It has "
        + "to beat holding the three, bought on day one and never touched. Kept apart from everything above: nothing "
        + "here is added together."));
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

  // ---------------------------------------------------------------- A1. the town: what it costs vs what the desks made
  // Two bars on one scale: what running the bot cost so far today (grey) and what the desks made today (green;
  // red for a loss). An income that is not known yet draws no bar at all; every word is fixed text or the data's.
  // Only real money can cover the bill: the Solana bar says "covered" only while its money is real (the card's own
  // label is the real-money label), and the real Polymarket line says it from the goal's real figure
  // (town.goal.bill_covered_by_real).
  function renderTown(t) {
    $("town-label").textContent = t.label;
    $("town-line").textContent = t.line;
    // (the town's label is the real-money label exactly when the page's own real-money words say it: data, not copy)
    const realLabel = last && last.plain && last.plain.real ? last.plain.real.label : null;
    const cost = t.cost_today_usd, made = t.income_today_usd, real = !!realLabel && t.label === realLabel;
    const scale = Math.max(isNum(cost) ? cost : 0, isNum(made) ? Math.abs(made) : 0, 0.01);
    const since = (v, signed, covered) => "since start: " + (isNum(v) ? usd(v, signed) : "not known yet")
      + (covered === true ? " · covered" : covered === false ? " · not covered" : "");
    const verdict = !real ? null : t.covered_today === true ? el("span", "tag", "covered")
      : t.covered_today === false ? el("span", "tag", "not covered") : null;
    const byReal = t.goal ? t.goal.bill_covered_by_real : null;
    const realTag = byReal === true ? "covered by real money today" : byReal === false ? "not covered by real money today" : null;
    const desks = t.polymarket;  // the Polymarket desk's lines (town.polymarket); the bar stays the Solana desk's
    put($("town-bars"),
      el("div", "bar", el("span", null, "Costs today"), el("b", "num", usd(cost)),
        isNum(cost) ? track(cost / scale, "cost") : null, el("small", null, since(t.cost_since_start_usd, false, null))),
      el("div", "bar", el("span", null, desks ? "Made today, Solana desk" : "Made today", verdict),
        el("b", "num " + tone(made), usd(made, true)),
        isNum(made) ? track(Math.abs(made) / scale, made < 0 ? "down" : "up") : null,
        el("small", null, since(t.income_since_start_usd, true, real ? t.covered_since_start : null))));
    // the trend desk's own line (town.trend) comes last: words only, never part of the bars above
    put($("town-desks"), ...[...(desks ? [desks.paper, desks.real] : []), t.trend].filter((d) => d && d.line)
      .map((d) => el("p", "meta", d.line, desks && d === desks.real && realTag ? el("span", "tag", realTag) : null)));
  }
  // the town's goal (plain.goal): the owner's goal for the team in its own words, and why it is not a cost
  function renderGoal(g) {
    put($("town-goal"), ...(g ? [el("p", "meta", g.line), el("p", "help", g.honest)] : []));
  }

  // ---------------------------------------------------------------- A2. the bot wallet: where to send SOL
  // Text only. The copy button writes the address (plain text) to the clipboard; without clipboard access it
  // selects the address so a long-press copies it.
  let walletShown = null, walletSol = null, walletLast = null;
  function copyButton(address, node) {
    const button = el("button", "copy", "Copy address");
    button.type = "button";
    button.addEventListener("click", async () => {
      let copied = false;
      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(address);
          copied = true;
        }
      } catch (err) {
        copied = false;
      }
      if (!copied) {
        const range = document.createRange();
        range.selectNodeContents(node);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      }
      button.textContent = copied ? "Copied ✓" : "Selected: press and hold it to copy";
      setTimeout(() => { button.textContent = "Copy address"; }, 3000);
    });
    return button;
  }
  function renderWallet(w) {
    $("wallet-kind").textContent = w.address && w.own ? "made by the bot, its key never leaves it" : "";
    if (!w.address) {
      walletShown = null;
      put($("wallet-body"), el("p", "empty", w.note || "No bot wallet yet."));
      return;
    }
    if (walletShown !== w.address) {  // rebuilt only when the address changes: a selection survives refreshes
      walletShown = w.address;
      const addr = el("span", "mono addr", w.address);
      walletSol = el("p", "meta");
      walletLast = el("p", "help");
      put($("wallet-body"), el("p", "lead", "Bot wallet:", addr), copyButton(w.address, addr), walletSol,
        el("p", "help", w.help), w.paper_note ? el("p", "help", w.paper_note) : null,
        w.keep_note ? el("p", "help", w.keep_note) : null, walletLast);
    }
    walletSol.textContent = isNum(w.sol) ? "In it now: " + w.sol.toFixed(4) + " SOL"
      + (isNum(w.checked_at) ? " (checked " + ago(w.checked_at) + ")" : "")
      : "Its SOL has not been checked in the last hour.";
    const last = w.last_withdrawal;
    walletLast.textContent = last && isNum(last.sol) ? "Last sent back: " + last.sol.toFixed(4) + " SOL to "
      + last.to + (isNum(last.at) ? ", " + ago(last.at) : "") + "." : "";  // in full: look-alikes share the ends
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
  function renderTeam(t, x, plain) {
    const c = t.counts;
    $("team-counts").textContent = ["working", "waiting", "idle", "blocked"].filter((k) => c[k])
      .map((k) => c[k] + " " + k).join(" · ");
    const graded = x && x.source === "state";
    const cast = (plain && plain.team) || [];
    for (const m of t.members) {
      const node = $("m-" + m.id);
      if (!node) continue;
      const card = graded ? x.members[m.id] || null : null;
      // the character who plays this member in the 3D world and the plain words (one set of names for both)
      const ch = cast.find((k) => (k.members || []).includes(m.id));
      if (m.role) node.querySelector(".who small").textContent = m.role + (ch ? " · played by " + ch.name : "");
      node.className = "member " + m.status;
      put(node.querySelector(".state"), chip(m.status), card ? skillChip(card) : null);
      node.querySelector(".doing").textContent = m.doing || "";
      node.querySelector(".graded").textContent = card ? gradedLine(m.id, card) : "";
      node.querySelector(".when").textContent = m.status === "absent" ? "not part of this version yet"
        : isNum(m.last_activity) ? "last active " + ago(m.last_activity) : "no activity recorded yet";
      const bars = (m.bars || []).map((b) => bar(b.label, b.value, b.text, "", b.note));
      put(node.querySelector(".more"), bars.length ? el("p", "sub", BAR_TITLES[m.id] || "") : null, ...bars,
        ...(card ? reportCard(m.id, card, x) : []), ...(graded && m.id === "coach" ? coachBlock(x) : []),
        el("p", "sub", "Last events"), events(m.events));
    }
    renderExperience(x);
  }

  // ---------------------------------------------------------------- B2. report cards (docs/EXPERIENCE.md §9)
  // Green only for a band that clears chance or the bar, red for the bad side, grey otherwise (never amber:
  // "Collecting" and "No skill yet" are the expected states). The chip word always shows, so colour is never the
  // only signal, and every word of a card comes from the data: the page itself never claims a skill.
  const GOOD_LABELS = ["skilled", "meets_bar"];
  const BAD_LABELS = ["worse", "below_bar", "check_failed"];
  const GRADED_UNIT = {strategy: "trades", radar: "trades", risk: "trades", broker: "trades"};
  const BASE_WORDS = {chance: "a random stand-in would give ", bar: "the bar is ", self_check: "the target is "};
  const LESSON_WORDS = {open: "open", testing: "being tested", adopted: "kept", rejected: "dropped"};
  const LOSS_WORDS = {pipeline_fault: "A bug in the bot (fixed at once)", rug_missed: "Rug missed",
    regime: "Bad market hour", oversize: "Trade too big for the money", late_entry: "Late entry",
    bad_entry: "Bad entry", early_exit: "Sold too early", late_exit: "Sold too late",
    cost_eaten: "Costs ate the gain", missed_winner: "Missed a winner", variance: "No type: ordinary swings"};
  const UNITS = {
    pp: (v) => sign(v, true) + Math.abs(v).toFixed(1) + " pts",
    share: (v) => (Math.abs(v) < 0.1 ? (v * 100).toFixed(1) : String(Math.round(v * 100))) + "%",
    ratio: (v) => v.toFixed(1) + "×",
    count: (v) => Math.round(v).toLocaleString(),
    s: (v) => v.toFixed(1) + " s",
  };
  const words = (key) => String(key).replace(/_/g, " ");
  function fmt(v, unit) { return isNum(v) ? (UNITS[unit] || String)(v) : "—"; }
  // A band's ends without the unit word the value beside them already carries: "−0.4 pts [−1.2, +0.5]".
  function fmtEnd(v, unit) { return unit === "pp" && isNum(v) ? sign(v, true) + Math.abs(v).toFixed(1) : fmt(v, unit); }

  function skillChip(card) {
    const tone = GOOD_LABELS.includes(card.label) ? " good" : BAD_LABELS.includes(card.label) ? " bad" : "";
    return el("span", "chip skill-chip" + tone, card.chip);
  }
  function gradedLine(id, card) {
    if (!isNum(card.graded)) return "";
    const days = isNum(card.days) ? " · " + card.days + (card.days === 1 ? " day" : " days") : "";
    return "Graded on " + card.graded.toLocaleString() + " " + (GRADED_UNIT[id] || "coins") + days;
  }
  // A track, the shaded band [lo, hi], a dot at the value and a tick at the baseline or the bar. No band, no bar.
  function rangeBar(m, kind) {
    if (!isNum(m.lo) || !isNum(m.hi)) return null;
    const known = [m.lo, m.hi, m.value, m.baseline].filter(isNum);
    let lo = Math.min(...known), hi = Math.max(...known);
    const pad = (hi - lo) * 0.12 || Math.max(Math.abs(hi), 1) * 0.12;
    lo -= pad;
    hi += pad;
    const at = (v) => ((v - lo) / (hi - lo) * 100).toFixed(2) + "%";
    const band = el("div", "rb");
    band.style.left = at(m.lo);
    band.style.width = ((m.hi - m.lo) / (hi - lo) * 100).toFixed(2) + "%";
    const parts = [el("div", "rt"), band];
    if (isNum(m.baseline)) {
      const tick = el("div", "rk");
      tick.style.left = at(m.baseline);
      parts.push(tick);
    }
    if (isNum(m.value)) {
      const dot = el("div", "rd");
      dot.style.left = at(m.value);
      parts.push(dot);
    }
    const box = el("div", "rbar", ...parts);
    box.setAttribute("role", "img");
    box.setAttribute("aria-label", (m.name + ": " + fmt(m.value, m.unit) + ", likely between " + fmt(m.lo, m.unit)
      + " and " + fmt(m.hi, m.unit) + (isNum(m.baseline) ? "; " + (BASE_WORDS[kind] || "the baseline is ")
      + fmt(m.baseline, m.unit) : "")).replace(/ pts\b/g, " points"));
    return box;
  }
  function metricRow(m, kind) {
    const band = isNum(m.lo) && isNum(m.hi) ? " [" + fmtEnd(m.lo, m.unit) + ", " + fmtEnd(m.hi, m.unit) + "]" : "";
    return el("div", "metric", el("div", "line", el("span", null, m.name), el("b", "num", fmt(m.value, m.unit) + band)),
      rangeBar(m, kind), m.text ? el("small", null, m.text) : null);
  }
  // The primary metric week by week, from 3 weeks on. No trend words: the picture is the data.
  function sparkline(trend, primary) {
    if (trend.length < 3) return null;
    const W = 300, H = 44, pad = 3;
    const base = primary && isNum(primary.baseline) ? primary.baseline : null;
    const vals = trend.flatMap((w) => w.slice(1)).filter(isNum).concat(base === null ? [] : [base]);
    let lo = Math.min(...vals), hi = Math.max(...vals);
    if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
    const x = (i) => (i / (trend.length - 1) * W).toFixed(1);
    const y = (v) => (pad + (1 - (v - lo) / (hi - lo)) * (H - 2 * pad)).toFixed(1);
    const plot = svg("svg", {viewBox: "0 0 " + W + " " + H, preserveAspectRatio: "none", "aria-hidden": "true"});
    if (trend.every((w) => isNum(w[2]) && isNum(w[3]))) {
      const top = trend.map((w, i) => x(i) + "," + y(w[3]));
      const bottom = trend.map((w, i) => x(i) + "," + y(w[2])).reverse();
      plot.append(svg("path", {d: "M" + top.concat(bottom).join("L") + "Z", class: "band"}));
    }
    if (base !== null) {
      plot.append(svg("line", {x1: 0, x2: W, y1: y(base), y2: y(base), class: "base",
        "vector-effect": "non-scaling-stroke"}));
    }
    plot.append(svg("polyline", {points: trend.map((w, i) => x(i) + "," + y(w[1])).join(" "), class: "ln",
      "vector-effect": "non-scaling-stroke"}));
    return el("div", "spark", el("p", "sub", "Week by week, the last " + trend.length + " weeks"), plot);
  }
  function reportCard(id, card, x) {
    const span = x.team.practised_window ? " (" + x.team.practised_window + ")" : "";
    const record = [gradedLine(id, card), isNum(card.practised)
      ? "practised on " + card.practised.toLocaleString() + " past coins" + span : ""].filter(Boolean);
    const exam = card.exam;
    const lessons = ["open", "testing", "adopted", "rejected"].filter((k) => k === "open" || card.lessons[k])
      .map((k) => card.lessons[k] + " " + LESSON_WORDS[k]).join(" · ");
    return [el("p", "sub", "Report card"), card.line ? el("p", "help", card.line) : null,
      record.length ? el("p", "meta", record.join(" · ")) : null,
      ...card.metrics.map((m) => metricRow(m, card.kind)),
      exam ? el("p", "meta" + (exam.current ? "" : " old"), "Past-data check" + (exam.date ? ", " + exam.date : "")
        + (exam.version12 ? ", version " + exam.version12 : "") + ": " + exam.result
        + (exam.current ? "" : " (an earlier version)")) : null,
      sparkline(card.trend, card.metrics[0]),
      card.version_line ? el("p", "meta", card.version_line) : null,
      card.independent ? el("p", "meta", card.independent) : null,
      card.coverage ? el("p", "meta", card.coverage) : null,
      card.kind === "self_check" ? null : el("p", "meta", "Lessons: " + lessons),
      isNum(card.budget_left) ? el("p", "meta", "False-alarm budget left: " + (card.budget_left * 100).toFixed(2)
        + "%") : null];
  }
  // The Coach's row: this week's loss types next to what luck alone gives, then the lessons (ideas to test).
  function coachBlock(x) {
    const losses = x.loss_types_week.map((t) => el("div", null,
      el("div", "line", el("span", null, LOSS_WORDS[t.type] || words(t.type)), el("b", "num", String(t.n))),
      el("div", "meta", isNum(t.expected) ? "random entries in the same situations: " + t.expected.toFixed(1)
        + " expected" : "no luck-only count for this type"),
      t.text ? el("div", "meta", t.text) : null));
    const lessons = x.lessons.map((l) => el("div", null, el("div", "line", el("span", null, l.text || l.id),
      el("span", "tag", LESSON_WORDS[l.status] || words(l.status)))));
    return [el("p", "sub", "Loss types this week"),
      losses.length ? el("div", "rows", ...losses) : el("p", "empty", "No graded losses this week."),
      el("p", "help", "Each type sits next to what luck alone gives; one loss on its own changes nothing."),
      el("p", "sub", "Lessons"),
      lessons.length ? el("div", "rows", ...lessons)
        : el("p", "empty", "None yet: a lesson needs the same kind of loss on many different coins."),
      el("p", "help", "A lesson is an idea to test, never a change to the bot by itself.")];
  }
  // The team's headline under the Team card's first line, and the playbook under the members.
  function renderExperience(x) {
    if (!x) {
      put($("xp-head"));
      put($("xp-playbook"));
      return;
    }
    if (x.source === "state") {
      put($("xp-head"), ...x.headline.filter(Boolean).map((h) => el("p", "lead", h)),
        x.bars_line ? el("p", "help", x.bars_line) : null, el("p", "help", x.money_line), el("p", "help", x.caveat));
    } else {
      put($("xp-head"), el("p", "help", x.source === "missing"
        ? "Report cards: not built yet. Each member will be graded against a random stand-in or a fixed bar."
        : "Report cards: could not be read right now (see the logs)."));
    }
    const p = x.playbook;
    if (!isNum(p.in_bot_contradicted)) {
      put($("xp-playbook"));
      return;
    }
    const n = (v) => (isNum(v) ? String(v) : "?");
    put($("xp-playbook"), el("p", "sub", "Playbook: every craft rule is a test"),
      el("p", "help", "In the bot, contradicted by our data: " + n(p.in_bot_contradicted) + " · in the bot, untested: "
        + n(p.in_bot_unsupported) + " · being tested: " + n(p.testing) + "."),
      el("p", "help", "Tested and kept: " + n(p.validated) + " (at most " + p.false_keep_bound
        + " expected to be a false keep) · tested and dropped: " + n(p.rejected) + "."));
  }

  // ---------------------------------------------------------------- C. trades
  function renderTrades(tr) {
    $("trades-count").textContent = tr.open.length + " of " + tr.max_open + " open";
    // a line from its known parts only: right after a buy there is no price (and no result) yet
    const parts = (...bits) => bits.filter(Boolean).join(" · ");
    const known = (v) => isNum(v) && v > 0;
    const result = (v) => (isNum(v) ? el("span", "big " + tone(v), usd(v, true)) : null);
    const open = tr.open.map((p) => el("div", null,
      el("div", "line", el("span", "coin", p.coin), isNum(p.pnl_usd) ? el("span", "big " + tone(p.pnl_usd),
        usd(p.pnl_usd, true)) : null),
      el("div", "meta", parts(known(p.entry_usd) ? "Bought at " + price(p.entry_usd) : null,
        known(p.now_usd) ? "now " + price(p.now_usd) : "price not checked yet", pct(p.pnl_pct),
        isNum(p.opened_at) ? "held " + dur(nowS() - p.opened_at) : null,
        p.partial ? "half already sold at a profit" : null,
        p.foreign ? "in an earlier wallet: this bot does not sell or count it" : null))));
    const closed = tr.closed.map((p) => el("div", null,
      el("div", "line", el("span", "coin", p.coin, el("span", "tag", p.result === "won" ? "Won" : p.result === "lost"
        ? "Lost" : "Even")), result(p.pnl_usd)),
      el("div", "meta", parts(p.why, pct(p.pnl_pct), isNum(p.closed_at) ? "closed " + ago(p.closed_at) : null))));
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
    const rule = $("learn-rule");  // a safety claim: only when the learning system says it really can
    rule.hidden = !l.rule;
    rule.textContent = l.rule || "";
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
    const words = moneyWords(s.plain && s.plain.real), mode = $("mode");
    mode.textContent = words ? words.badge : "";
    mode.hidden = !words;
    mode.className = "mode" + (words && words.live ? " live" : "");
    document.title = "nightcrawler" + (words ? " · " + words.title : "");
    put($("alerts"), ...s.alerts.map((a) => el("div", "alert " + a.level, a.text)));
    renderPlain(s.plain);
    renderMoney(s.money, s.mode === "LIVE");
    if (s.town) renderTown(s.town);
    renderGoal(s.plain && s.plain.goal);
    if (s.wallet) renderWallet(s.wallet);
    renderTeam(s.team, s.experience, s.plain);
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
  // The link's ?token= already set the login cookie (an HMAC, never the token), so a refresh sends only that
  // cookie: the raw token is not written into proxy logs every few seconds. It is sent again only if the
  // cookie was refused (cookies blocked, or the cookie is from an older token).
  async function load() {
    const opts = {cache: "no-store", credentials: "same-origin"};
    let res = await fetch("api/page", opts);
    if (res.status === 401 && token) res = await fetch("api/page?token=" + encodeURIComponent(token), opts);
    return res;
  }
  async function refresh() {
    clearTimeout(timer);
    try {
      const res = await load();
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
            '<span class="state"></span><span class="doing">Loading…</span><span class="graded"></span>'
            '<span class="when"></span></span></summary><div class="more"></div></details>\n')


def render_page_html(settings: Settings) -> str:
    """The complete page (static: the script fills in live data; no ledger data, no secrets). Pure."""
    live = settings.is_live
    # the badge and the title claim real money before the first answer only when the bot itself runs live (real
    # money is then on whatever the desks say); otherwise they wait for the data (plain.real) and claim nothing
    badge = '<b class="mode live" id="mode">REAL MONEY ON</b>' if live else '<b class="mode" id="mode" hidden></b>'
    title = "nightcrawler · real money on" if live else "nightcrawler"
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
        f"<link rel=\"icon\" href=\"data:,\">\n<title>{title}</title>\n"
        f"<style>{_STYLE}</style>\n</head>\n"
        f"<body data-refresh=\"{REFRESH_S}\">\n<main id=\"main\">\n"
        f"<header class=\"top\">{badge}"
        f"<span class=\"name\">nightcrawler</span><span class=\"updated\" id=\"updated\">loading…</span>"
        "<nav class=\"links\"><a class=\"office\" href=\"world\" title=\"The bot's team at work, live in 3D\">"
        "Watch the team (3D)</a><a class=\"office\" href=\"office\" title=\"The same team as pictures\">Pictures</a>"
        "</nav></header>\n"
        "<div id=\"alerts\" role=\"status\"></div>\n"
        "<div class=\"alert warn\" id=\"offline\" role=\"status\" hidden></div>\n"

        "<section class=\"card\" id=\"plain\"><h2>In plain words</h2><p id=\"plain-about\"></p>"
        "<p class=\"lead\" id=\"plain-headline\">Loading…</p><div id=\"plain-real\"></div>"
        "<div id=\"plain-pretend\"></div><p class=\"sub\">Right now</p><div class=\"rows\" id=\"plain-now\"></div>"
        "<details class=\"about\"><summary>Who is who</summary><div class=\"rows\" id=\"plain-team\"></div>"
        "<p class=\"help\">The six characters of the 3D world; each acts out one part of the bot.</p>"
        "<p class=\"help\"><a href=\"world\">Watch them in 3D</a></p></details>"
        "<details class=\"about\"><summary>What the words mean</summary><div class=\"rows\" id=\"plain-words\"></div>"
        "</details></section>\n"

        "<section class=\"card\" id=\"money\">"
        f"<h2>Solana bot <small id=\"money-label\">{label}</small></h2>"
        "<div class=\"hero\" id=\"money-value\">—</div>"
        "<div class=\"tiles\"><div class=\"tile\"><div class=\"label\">Since start</div>"
        "<b id=\"since-usd\">—</b><span id=\"since-pct\"></span></div>"
        "<div class=\"tile\"><div class=\"label\">Today</div><b id=\"today-usd\">—</b><span id=\"today-pct\"></span>"
        "</div></div>"
        "<p class=\"help\">Since start and today count only the bot's own trading, at today's price of SOL.</p>"
        "<p class=\"help\" id=\"money-help\"></p><div id=\"chart\"></div><div id=\"money-polymarket\"></div>"
        "<div id=\"money-trend\"></div></section>\n"

        "<section class=\"card\" id=\"town\">"
        f"<h2>The town <small id=\"town-label\">{label}</small></h2>"
        "<p class=\"lead\" id=\"town-line\">Loading…</p><div id=\"town-bars\"></div><div id=\"town-desks\"></div>"
        "<div id=\"town-goal\"></div>"
        "<p class=\"help\">To run on its own, real money must earn more than the town costs to run: the hosting plan "
        "plus the AI judge's spending. Practice money never counts.</p></section>\n"

        "<section class=\"card\" id=\"wallet\"><h2>Bot wallet <small id=\"wallet-kind\"></small></h2>"
        "<div id=\"wallet-body\"><p class=\"empty\">Loading…</p></div></section>\n"

        "<section class=\"card\" id=\"team\"><h2>The team <small id=\"team-counts\"></small></h2>"
        "<p class=\"help\">Each one is a part of the bot. Tap a name to see what it did last.</p>"
        "<div id=\"xp-head\"></div>"
        f"<div class=\"members\">\n{members}</div><div id=\"xp-playbook\"></div></section>\n"

        "<section class=\"card\" id=\"trades\"><h2>Trades <small id=\"trades-count\"></small></h2>"
        "<div id=\"trades-body\"><p class=\"empty\">Loading…</p></div>"
        "<p class=\"help\">Dollar amounts use today's price of SOL.</p></section>\n"

        "<section class=\"card\" id=\"learning\"><h2>Learning <small>the Coach</small></h2>"
        "<p class=\"lead\" id=\"learn-headline\">Loading…</p><p class=\"help\" id=\"learn-state\"></p>"
        "<div id=\"learn-variants\"></div><p class=\"help\" id=\"learn-data\"></p>"
        "<p class=\"rule\" id=\"learn-rule\" hidden></p></section>\n"

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
