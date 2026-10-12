"""Phone-first controls for the existing town; presentation only, using /api/page."""

from nightcrawler.worldtycoon_camera import TYCOON_CAMERA
from nightcrawler.worldtycoon_data import TYCOON_DATA
from nightcrawler.worldtycoon_park import TYCOON_PARK

TYCOON_HTML = """
<section id="ty-header" aria-label="Town and real money">
  <div class="ty-heading"><div><span class="ty-logo" aria-hidden="true">N</span><h1>Nightcrawler<span>Your business, alive.</span></h1></div>
    <button type="button" id="ty-more" aria-controls="panel" aria-label="Open town menu">Menu <span aria-hidden="true">☰</span></button></div>
  <div class="ty-money">
    <div><span>Polymarket cash</span><b id="ty-cash">—</b></div>
    <div><span>PM bot profit <small>· today PT</small></span><b id="ty-today">—</b></div>
  </div>
  <div class="ty-status"><span id="ty-state" role="status">Connecting</span><span id="ty-fresh">Waiting for reports</span></div>
  <button type="button" id="ty-alert" aria-controls="panel" hidden></button>
</section>
<div id="ty-markers" aria-label="Town workstations"></div>
<section id="ty-selection" aria-label="Selected workstation" hidden>
  <div><span class="ty-eyebrow" id="ty-context">YOUR CREW</span><b id="ty-focus">The whole town</b></div>
  <button type="button" id="ty-home" aria-label="Return to the whole town">← Town</button>
  <p id="ty-doing">Tap a building to see its team.</p>
  <button type="button" id="ty-info" aria-controls="panel">Desk details <span aria-hidden="true">↗</span></button>
</section>
<section id="ty-dock" aria-label="Latest town activity">
  <div id="ty-event"><span class="ty-event-dot" aria-hidden="true"></span><span id="ty-event-text">Waiting for the bot’s report…</span><span id="ty-event-age"></span></div>
  <p id="ty-growth">Tap a building to visit your team</p>
</section>
<button type="button" id="ty-mode">Town view</button>
"""

TYCOON_STYLE = r"""
#ty-header, #ty-dock, #ty-markers, #ty-selection, #ty-mode { display: none; }
body.tycoon { --ty-ink: #203846; --ty-muted: #607787; --ty-edge: #cedde4; }
body.tycoon #ty-header, body.tycoon #ty-dock, body.tycoon #ty-selection { display: block; position: fixed; z-index: 10; color: var(--ty-ink);
  background: #f8fcff; border: 2px solid #fff; box-shadow: 0 3px 0 #aed0df, 0 6px 20px #22466426; border-radius: 15px; }
body.tycoon #ty-header { top: calc(9px + env(safe-area-inset-top)); left: 10px; right: 10px; padding: 8px 12px 6px; }
.ty-heading, .ty-heading > div { display: flex; gap: 8px; align-items: center; }
.ty-heading { justify-content: space-between; }
.ty-logo { width: 31px; height: 31px; display: grid; place-items: center; background: #36a9e4; border-radius: 9px; color: #fff; font-size: 22px; font-weight: 900; box-shadow: 0 2px 0 #2281b3; }
.ty-heading h1 { font-size: 16px; line-height: 1.1; margin: 0; font-weight: 850; letter-spacing: -.03em; }
.ty-heading h1 span { display: block; font-size: 9px; font-weight: 500; letter-spacing: 0; margin-top: 3px; color: #657c8b; }
#ty-more, #ty-home, #ty-info { min-height: 44px; cursor: pointer; font: inherit; font-size: 12px; font-weight: 750; padding: 6px 10px;
  border: 0; border-radius: 9px; color: #fff; background: #258ec7; box-shadow: 0 2px 0 #176c9d; }
#ty-more span { margin-left: 5px; }
.ty-money { display: grid; grid-template-columns: 1fr 1fr; margin-top: 5px; gap: 10px; }
.ty-money > div { min-width: 0; } .ty-money > div + div { border-left: 1px solid #d9e5eb; padding-left: 14px; }
.ty-money span { display: block; font-size: 10px; font-weight: 650; color: #506b7b; }
.ty-money small { font-size: 8px; font-weight: 500; }
.ty-money b { display: block; font-size: 25px; line-height: 1.1; letter-spacing: -.035em; font-variant-numeric: tabular-nums; }
.ty-money .positive { color: #238243; } .ty-money .negative { color: #b13c3c; }
.ty-status { display: flex; gap: 5px; align-items: baseline; justify-content: space-between; margin-top: 5px; font-size: 8px; line-height: 1.25; color: #607787; }
#ty-state { flex-shrink: 0; font-weight: 700; } #ty-state.on { color: #256c47; }
#ty-state.paused, #ty-state.stale, #ty-state.offline { color: #985a12; }
#ty-fresh { text-align: right; max-width: 50%; }
#ty-alert { width: 100%; min-height: 44px; margin-top: 7px; padding: 6px 9px; text-align: left; cursor: pointer;
  font: inherit; font-size: 11px; border-radius: 8px; border: 1px solid #e0b965; color: #70460b; background: #fff1c9; }
#ty-alert[hidden], body.tycoon #ty-selection[hidden] { display: none; }
body.tycoon #ty-dock { bottom: calc(10px + env(safe-area-inset-bottom)); left: 10px; right: 10px; padding: 9px 12px; }
#ty-event { display: flex; align-items: center; gap: 7px; font-size: 11px; line-height: 1.35; }
.ty-event-dot { width: 7px; height: 7px; flex-shrink: 0; border-radius: 50%; background: #48ab64; }
#ty-event-text { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; flex: 1; }
#ty-event-age { color: #607787; font-size: 9px; }
#ty-growth { margin: 4px 0 0 14px; color: #607787; font-size: 9px; line-height: 1.3; }
body.tycoon #ty-selection { left: 10px; right: 10px; bottom: calc(82px + env(safe-area-inset-bottom)); padding: 11px 12px; }
#ty-selection > div { padding-right: 75px; } .ty-eyebrow { font-size: 9px; line-height: 1.2; font-weight: 750; letter-spacing: .08em; color: #607787; }
#ty-focus { display: block; font-size: 17px; margin-top: 2px; } #ty-home { position: absolute; top: 9px; right: 10px; }
#ty-doing { font-size: 12px; line-height: 1.4; margin: 12px 0 7px; }
#ty-info { color: #276789; background: #e4f1f9; box-shadow: none; min-height: 44px; }
body.tycoon #ty-markers { display: block; position: fixed; inset: 0; pointer-events: none; z-index: 5; }
.ty-marker { position: absolute; top: 0; left: 0; min-height: 44px; min-width: 44px; pointer-events: auto; padding: 5px 9px;
  background: transparent; color: #294356; border: 0; border-radius: 9px; box-shadow: none;
  font: inherit; font-size: 11px; font-weight: 800; cursor: pointer; }
.ty-marker b { display: inline-block; background: #fcffffef; padding: 4px 6px; border-radius: 6px; box-shadow: 0 2px 4px #23415720; font-size: 10px; }
.ty-marker b::before { content: ""; display: inline-block; width: 5px; height: 5px; border-radius: 50%; margin-right: 4px; vertical-align: middle; background: #91a4ab; }
.ty-marker[data-status="working"] b::before { background: #47a466; }
.ty-marker[data-status="stuck"] b::before { background: #d08c29; }
.ty-marker small { display: none; }
.ty-marker[hidden] { display: none; }
body.tycoon #cine, body.tycoon #tags, body.tycoon #intro, body.tycoon #details, body.tycoon #bar,
body.tycoon #honest, body.tycoon #postcard, body.tycoon #bubbles { display: none !important; }
body.tycoon #vignette { background: none; }
body.world-failed #ty-header, body.world-failed #ty-dock, body.world-failed #ty-markers { display: none; }
body.tycoon #panel { top: calc(16px + env(safe-area-inset-top)); bottom: auto; max-height: calc(100% - 40px - env(safe-area-inset-top) - env(safe-area-inset-bottom));
  z-index: 20; border-radius: 16px; background: #16262a; }
body.tycoon #panel-close { min-height: 44px; min-width: 44px; }
#ty-header button:focus-visible, #ty-selection button:focus-visible, .ty-marker:focus-visible, .ty-menu-row:focus-visible, .ty-person:focus-visible { outline: 3px solid #ffb72e; outline-offset: 3px; }
.ty-menu-row { display: flex; align-items: center; justify-content: space-between; width: 100%; min-height: 48px; padding: 10px 0; border: 0; border-bottom: 1px solid #ffffff20;
  color: #f4f6ed; background: none; font: inherit; font-size: 15px; text-decoration: none; text-align: left; cursor: pointer; }
.ty-menu-row span { color: #b7d4c2; } .ty-menu-crew { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 10px 0; }
.ty-person { display: flex; align-items: center; gap: 8px; min-height: 48px; padding: 7px; border: 1px solid #ffffff20; border-left: 3px solid var(--ty-department); border-radius: 9px;
  color: #f4f6ed; background: #ffffff06; font: inherit; text-align: left; cursor: pointer; }
.ty-person i { font-style: normal; font-size: 20px; } .ty-person b, .ty-person small { display: block; }
.ty-person b { font-size: 12px; } .ty-person small { font-size: 9px; color: #c0d2c5; }
.ty-person .ty-scope { font-size: 8px; margin-top: 2px; }
.ty-position { padding: 10px 0; border-top: 1px solid #c8dbc030; } .ty-position p { margin: 4px 0; }
.ty-position small { color: #bbc9bd; }
.ty-flow-card { padding: 12px; margin-top: 12px; border: 1px solid #c8dbc033; border-left: 4px solid #9acbae; border-radius: 10px; }
.ty-flow-card h3 { margin: 0 0 8px; font-size: 16px; } .ty-flow-card p { margin: 8px 0; } .ty-flow-card.practice { border-left-color: #bdabdf; }
body:not(.tycoon) #ty-mode { display: block; position: fixed; top: calc(65px + env(safe-area-inset-top)); right: 10px; z-index: 10;
  min-height: 44px; padding: 8px 12px; border: 1px solid #a3d8dd; border-radius: 9px; background: #163038; color: #fff; font: inherit; cursor: pointer; }
@media (min-width: 760px) {
  body.tycoon #ty-header { left: 20px; right: auto; width: 365px; }
  body.tycoon #ty-dock { left: 50%; right: auto; transform: translateX(-50%); width: 430px; }
  body.tycoon #ty-selection { left: auto; right: 20px; width: 330px; }
}
@media (max-width: 350px) { .ty-money small { font-size: 7px; } .ty-status { font-size: 7px; } }
"""

TYCOON_UI = r"""
  // ============================================================= TYCOON CONTROLS (read-only)
  const TY_UI = { summary: null, stamp: -1, markers: [], people: [], top: 140, bottom: 70 };
  const tyHeader = el("ty-header"), tyDock = el("ty-dock"), tyMarkers = el("ty-markers");
  function tyAge(seconds) {
    if (seconds == null || !isFinite(seconds)) return "time unknown";
    if (seconds < 60) return "<1m ago";
    if (seconds < 3600) return Math.floor(seconds / 60) + "m ago";
    if (seconds < 86400) return Math.floor(seconds / 3600) + "h ago";
    return Math.floor(seconds / 86400) + "d ago";
  }
  function tyText(id, value) { const n = el(id), s = String(value); if (n.textContent !== s) n.textContent = s; }
  function tycoonMeasure() {
    if (!tycoonActive()) return;
    TY_UI.top = tyHeader.getBoundingClientRect().bottom + 8;
    const selection = el("ty-selection");
    TY_UI.bottom = window.innerHeight - (selection.hidden ? tyDock : selection).getBoundingClientRect().top + 8;
    tycoonBounds(TY_UI.top, TY_UI.bottom);
    TY_UI.markers.forEach(function (m) { m.w = 0; });
  }
  function tycoonChoose(key) {
    if (key === "observatory") { openPanel("ty-research"); return; }
    if (!TYCOON.on) tycoonView(true);
    closePanel(); tycoonSelect(key); tycoonDraw();
    for (const p of TY_UI.people) p.b.setAttribute("aria-pressed", String(TYCOON.selected === p.key));
  }
  function tycoonView(on) {
    filmStop(true); closePanel(); closeGuide(); cineIntroClose(false);
    tycoonEnable(on); cineSet(true, false);
    tycoonCutaway(on);
    tycoonPark(on);
    // Arena animation is practice. Its floating dollar labels must not sit under the real-money HUD.
    if (TP.labels) TP.labels.visible = !on;
    if (TP.plates) TP.plates.visible = !on;
    el("ty-mode").textContent = on ? "Camera tour" : "Town view";
    if (!on) goLive();
    tycoonMeasure(); tycoonDraw();
  }
  function tycoonBuildCrew() {
    for (const key of ["voss", "pip", "nyx", "rook", "mote", "jet"]) {
      const b = document.createElement("button"), icon = document.createElement("i"), words = document.createElement("span");
      const name = document.createElement("b"), job = document.createElement("small"), scope = document.createElement("small");
      b.type = "button"; b.className = "ty-person"; b.dataset.key = key; b.setAttribute("aria-pressed", "false");
      const colour = "#" + TYCOON_PARK_COLORS[CAST[key].room].toString(16).padStart(6, "0");
      b.style.setProperty("--ty-department", colour); scope.className = "ty-scope";
      icon.textContent = CAST[key].name[0]; icon.setAttribute("aria-hidden", "true"); name.textContent = CAST[key].name;
      job.textContent = "Workstation"; scope.textContent = "NO REPORT";
      words.appendChild(name); words.appendChild(job); words.appendChild(scope); b.appendChild(icon); b.appendChild(words);
      b.onclick = function () { tycoonChoose(key); }; TY_UI.people.push({ key: key, b: b, job: job, scope: scope });
      const m = document.createElement("button"), sub = document.createElement("small");
      m.type = "button"; m.className = "ty-marker"; m.dataset.key = key; const label = document.createElement("b"); label.textContent = CAST[key].name; m.appendChild(label); m.appendChild(sub); m.hidden = true;
      m.style.borderBottomColor = colour;
      m.onclick = b.onclick; tyMarkers.appendChild(m);
      const at = LAMP_AT[CAST[key].room].clone(); at.y += 2.2;
      TY_UI.markers.push({ key: key, el: m, sub: sub, at: at, w: 0 });
    }
  }
  function tycoonDraw() {
    const s = tycoonSummary(data, Date.now() / 1000); TY_UI.summary = s;
    tycoonParkApply(s);
    const state = offline ? "offline" : s.state;
    const stateWords = { on: "PM live", off: "PM buys off", paused: "PM paused", stale: "Data delayed", offline: "Reconnecting", unknown: "No report yet" };
    const status = el("ty-state"); status.className = state; status.textContent = (stateWords[state] || "No report yet")
      + (s.accounts && s.accounts.kalshi ? " · Kalshi " + s.accounts.kalshi.state : "");
    const alerts = data && Array.isArray(data.alerts) ? data.alerts : [];
    const warning = offline ? statusEl.textContent : alerts.length ? alerts[0].text : "";
    el("ty-alert").hidden = !warning; tyText("ty-alert", warning || "");
    tyText("ty-cash", fmtUsd(s.cash)); tyText("ty-today", fmtSigned(s.today));
    el("ty-today").className = s.today > 0 ? "positive" : s.today < 0 ? "negative" : "";
    const oldMoney = [];
    if (s.cashStale) oldMoney.push("Cash checked " + tyAge(s.cashAge));
    else if (s.cash !== null && !s.cashAsOf) oldMoney.push("Cash update time unknown");
    if (s.venueStale) oldMoney.push("Account bets checked " + tyAge(s.venueAge));
    else if (s.count !== null && !s.venueAsOf) oldMoney.push("Account bets update time unknown");
    if (s.todayStale) oldMoney.push("Profit checked " + tyAge(s.todayAge));
    tyText("ty-fresh", offline ? "Connection lost · showing the last report" : s.stale ? "Last report " + tyAge(s.deskAge) + " · figures may be old"
      : oldMoney.length ? oldMoney.join(" · ") + " · may be old"
      : s.updated ? "Cash checked " + tyAge(s.cashAge) + " · bets " + tyAge(s.venueAge) : "Waiting for the bot’s report…");
    const chosen = s.crew.find(function (c) { return c.key === TYCOON.selected; }) || (CAST[TYCOON.selected] ? {
      name: CAST[TYCOON.selected].name, job: "Workstation", status: "unknown", doing: "Waiting for a crew report.", age: null, practice: null,
    } : null);
    el("ty-selection").hidden = !chosen;
    const workWords = { working: "Recently active", waiting: "Waiting", idle: "Idle", stuck: "Needs attention", unknown: "No current report" };
    const activity = ["working", "waiting", "idle", "stuck", "unknown"].map(function (k) {
      const n = s.crew.filter(function (c) { return c.status === k; }).length;
      return n ? n + " " + ({ working: "active", waiting: "waiting", idle: "idle", stuck: "need attention", unknown: "unreported" }[k]) : "";
    }).filter(Boolean).join(" · ");
    tyText("ty-context", chosen ? (chosen.practice ? "PRACTICE DESK" : "TEAM WORKSTATION") : "YOUR CREW");
    tyText("ty-focus", chosen ? chosen.name + " · " + chosen.job : "The whole town");
    el("ty-info").setAttribute("aria-label", chosen ? "About " + chosen.name + "’s workstation" : "How the town works");
    tyText("ty-doing", chosen ? (workWords[chosen.status] || "No current report") + ". " + chosen.doing + (chosen.age == null ? "" : " · " + tyAge(chosen.age))
      : (activity ? "Latest report: " + activity + ". Tap a teammate for details." : "Waiting for crew reports. Tap a teammate to see their desk."));
    for (const p of TY_UI.people) {
      const c = s.crew.find(function (q) { return q.key === p.key; });
      if (!c) {
        p.b.dataset.status = "unknown"; p.scope.textContent = "NO REPORT";
        p.b.title = CAST[p.key].name + ": No current report"; p.b.setAttribute("aria-label", p.b.title); continue;
      }
      p.b.dataset.status = c.status;
      p.scope.textContent = c.practice === true ? "PRACTICE" : c.practice === false ? "REAL DESK" : "SHARED";
      p.job.textContent = c.job; p.b.title = c.name + ": " + (workWords[c.status] || "No current report") + (c.practice ? " · practice" : "");
      p.b.setAttribute("aria-label", c.name + ", " + c.job + ", " + (workWords[c.status] || "No current report") + (c.practice ? ", practice" : ""));
    }
    for (const m of TY_UI.markers) {
      const c = s.crew.find(function (q) { return q.key === m.key; });
      m.el.dataset.status = c ? c.status : "unknown";
      if (c) {
        const job = c.practice ? c.job + " · practice" : c.job;
        if (m.sub.textContent !== job) { m.sub.textContent = job; m.w = 0; }
        m.el.setAttribute("aria-label", "View " + c.name + "’s workstation");
      } else { m.sub.textContent = "No current report"; m.w = 0; }
    }
    tyText("ty-event-text", s.event ? s.event.text : "No recent real settlement reported");
    tyText("ty-event-age", s.event ? tyAge(s.event.age) : "");
    const growth = s.growth;
    tyText("ty-growth", growth && growth.qualified ? "Garden upgrades " + growth.level + "/5 · earned today, resets midnight PT"
      : "Tap a building to visit your team · growth awaiting verified results");
    if (panelKind && panelKind.indexOf("ty-") === 0 && panelKind !== "ty-menu") tycoonPanel();
    tycoonMeasure();
  }
  function tycoonPanel() {
    if (!panelKind || panelKind.indexOf("ty-") !== 0) return false;
    // Data polls must not replace focused navigation while someone is choosing a destination.
    if (panelKind === "ty-menu" && panelTitle.textContent === "Your town" && panelBody.querySelector(".ty-menu-crew")) return true;
    const focusedRow = typeof document !== "undefined" && document.activeElement
      && document.activeElement.classList.contains("ty-menu-row") && panelBody.contains(document.activeElement)
      ? document.activeElement.textContent : null;
    const s = TY_UI.summary || tycoonSummary(data, Date.now() / 1000), scroll = panelEl.scrollTop;
    panelBody.textContent = ""; panelEl.className = "";
    const row = function (title, target, action) {
      const b = document.createElement(target && target[0] === "/" ? "a" : "button");
      b.className = "ty-menu-row"; b.textContent = title;
      if (b.tagName === "A") b.href = target;
      else { b.type = "button"; b.onclick = action || function () { openPanel(target); }; }
      panelBody.appendChild(b); return b;
    };
    if (panelKind === "ty-menu") {
      panelTitle.textContent = "Your town";
      row("Accounts & open bets", "ty-accounts"); row("Today’s result & garden", "ty-today");
      row("Research desks", "ty-research"); row("Detailed reports ↗", "/reports");
      para(panelBody, "VISIT YOUR TEAM", "dim");
      const crew = document.createElement("div"); crew.className = "ty-menu-crew";
      TY_UI.people.forEach(function (p) { crew.appendChild(p.b); }); panelBody.appendChild(crew);
      row("Camera tour", null, function () { tycoonView(false); });
      row("How the town works", "ty-flow");
      row("Stop new real orders · instructions", "ty-stop");
    } else if (panelKind === "ty-research") {
      panelTitle.textContent = "Research desks";
      (s.research || []).forEach(function (r) {
        const h = document.createElement("h3"); h.textContent = r.name + " · " + r.scope; panelBody.appendChild(h);
        para(panelBody, r.status);
        if (r.count !== null) para(panelBody, r.count + " " + r.countLabel, "dim");
        para(panelBody, r.asOf ? "Reported " + tyAge(r.age) : "No current report", "dim");
      });
      para(panelBody, "Research and practice results never count as real profit or unlock gardens.", "dim");
      row("Open detailed reports ↗", "/reports");
    } else if (panelKind === "ty-stop") {
      panelTitle.textContent = "Stop new real orders";
      para(panelBody, "On Railway’s bot service, set both:");
      para(panelBody, "POLYDESK_MODE = paper"); para(panelBody, "SPEEDDESK_KALSHI_MODE = paper");
      para(panelBody, "Wait for the restart and verify that both desks report practice. Check that Kalshi’s resting bids were cancelled and its remaining exposure was reconciled.");
      para(panelBody, "Already filled bets stay open and still win or lose at settlement. This page shows instructions; it does not change trading settings.", "warn");
    } else if (panelKind === "ty-accounts") {
      panelTitle.textContent = "Your accounts";
      para(panelBody, "POLYMARKET US", "dim");
      para(panelBody, "Available cash: " + fmtUsd(s.cash));
      para(panelBody, "Open markets: " + (s.count == null ? "not reported" : s.count) + " · value " + fmtUsd(s.value));
      para(panelBody, "Shared with your own bets. Cash is not profit. " + (s.stateText || "Money mode not reported."), "dim");
      row("Polymarket cash details", "ty-cash"); row("Polymarket open bets", "ty-bets");
      const k = s.accounts && s.accounts.kalshi;
      para(panelBody, "KALSHI", "dim");
      if (k) {
        para(panelBody, (k.active ? "REAL MONEY (Kalshi)" : k.practice ? "PRACTICE (Kalshi)" : k.stateText) + " · cash " + fmtUsd(k.cash));
        para(panelBody, "Money at risk: " + fmtUsd(k.exposure) + " · today (UTC): " + fmtSigned(k.today));
        para(panelBody, k.reason || "Inventory and results are reported by the Kalshi desk.", "dim");
        para(panelBody, k.cashAt ? "Kalshi cash checked " + tyAge(k.cashAge) + "." : "Kalshi cash update time is unknown.", "dim");
        if (k.cashStale) para(panelBody, "Kalshi cash may be old; waiting for a fresh balance read.", "warn");
        if (k.todayStale) para(panelBody, "Kalshi’s UTC-day result is delayed or unavailable.", "warn");
        if (k.cleanupPending) para(panelBody, "Resting-order cancellation and reconciliation are still pending.", "warn");
        if (k.stale) para(panelBody, "Kalshi’s report is delayed or missing. These figures may be old.", "warn");
      } else para(panelBody, "Waiting for a Kalshi account report.", "dim");
      para(panelBody, "Accounts stay separate. Kalshi’s UTC day is not added to Polymarket’s Pacific day.", "dim");
    } else if (panelKind === "ty-alerts") {
      panelTitle.textContent = "Town needs attention";
      const alerts = data && Array.isArray(data.alerts) ? data.alerts : [];
      if (offline) para(panelBody, statusEl.textContent, "warn");
      alerts.forEach(function (a) { if (a && a.text) para(panelBody, a.text, "warn"); });
      if (!offline && !alerts.length) para(panelBody, "No current alerts reported.");
      para(panelBody, "The real-bets label reports the Polymarket money setting. Each message above describes the service or desk named in that message.", "dim");
    } else if (panelKind === "ty-flow") {
      const chosen = s.crew.find(function (c) { return c.key === TYCOON.selected; });
      panelTitle.textContent = chosen ? chosen.name + "’s workstation" : "How your town works";
      if (chosen) {
        para(panelBody, chosen.jobDetail || "Role not reported yet.");
        para(panelBody, chosen.recordedWork || chosen.doing, "dim");
        if (chosen.age !== null) para(panelBody, "Last activity recorded " + tyAge(chosen.age) + ".", "dim");
      }
      const lane = function (title, words, practice) {
        const card = document.createElement("section"), h = document.createElement("h3");
        card.className = "ty-flow-card" + (practice ? " practice" : ""); h.textContent = title; card.appendChild(h);
        words.forEach(function (w) { para(card, w); }); panelBody.appendChild(card);
      };
      lane("Voss · Polymarket", [s.state === "unknown" ? "Waiting for a current desk report." : s.stateText,
        "Voss’s desk watches Polymarket, checks its own limits and places its own bets. Open bets remain until they settle or are closed, even when new bets are off.",
        "The money at the top comes from this account. Cash and open bets include your own activity; Bot today counts only the bot’s realized real-money result."], false);
      const kalshi = s.accounts && s.accounts.kalshi;
      lane("Bitcoin speed desk · Kalshi", [kalshi ? kalshi.stateText : "Waiting for a Kalshi report.",
        "Kalshi has its own cash, positions and limits. See Accounts in the menu. Its UTC-day result stays separate from the Pacific-day number above."], kalshi && kalshi.practice);
      const coinCrew = s.crew.filter(function (c) { return ["pip", "nyx", "rook", "jet"].includes(c.key); });
      const practice = coinCrew.length === 4 && coinCrew.every(function (c) { return c.practice === true; });
      const realCoins = coinCrew.some(function (c) { return c.practice === false; });
      lane("Coin team · " + (practice ? "practice money" : realCoins ? "see each desk’s money mode" : "mode not reported"), [
        "Pip finds coins → Nyx checks them and watches for a setup → Rook checks trade size and loss limits → Nyx checks for danger again.",
        "Voss can review that coin setup when the AI judge is enabled. Jet then handles approved coin orders and exits. Jet does not place Voss’s Polymarket bets.",
        "Mote records decisions and trades from both desks. Rook’s board also reports Polymarket safeguards."], practice);
      para(panelBody, "Paths connect departments. Walking, resting and chatting keep the town alive; they do not mean an order was placed. Money changes only when the bot reports it.", "dim");
    } else if (panelKind === "ty-bets") {
      panelTitle.textContent = "Account’s open real bets";
      para(panelBody, "This Polymarket account is shared by you and the bot. These totals include your own bets.");
      para(panelBody, (s.count == null ? "Venue open count not reported" : s.count + " open markets at Polymarket")
        + (s.value == null ? "" : " · " + fmtUsd(s.value) + " reported value"));
      para(panelBody, "Value is what Polymarket reports for the holdings. It is separate from available cash and from realized profit.", "dim");
      if (s.pending && s.pending.count) para(panelBody, s.pending.count + " bot orders awaiting confirmation; separate from open bets.", "dim");
      if (!s.positions.length) para(panelBody, s.count === 0 ? "No open real bets reported by Polymarket." : "No individual bet records in this report.", "dim");
      if (s.positions.length) para(panelBody, "Desk records · may differ from current holdings", "dim");
      for (const p of s.positions) {
        const row = document.createElement("div"); row.className = "ty-position";
        para(row, p.question); para(row, p.side + (p.price == null ? "" : " · entry " + Math.round(p.price * 100) + "¢"), "dim"); panelBody.appendChild(row);
      }
      if (s.positions.length) para(panelBody, s.positionsNote, "dim");
      para(panelBody, s.venueAsOf ? "Account positions checked " + tyAge(s.venueAge) + "." : "Account positions update time not reported.", "dim");
    } else if (panelKind === "ty-result") {
      panelTitle.textContent = "Recent real result";
      para(panelBody, s.event ? s.event.text : "No recent real settlement reported.");
      if (s.event) { para(panelBody, "Recorded " + tyAge(s.event.age) + ".", "dim"); para(panelBody, s.eventNote, "dim"); }
    } else if (panelKind === "ty-today") {
      panelTitle.textContent = "Bot’s result today"; para(panelBody, fmtSigned(s.today));
      para(panelBody, "The bot’s recorded profit or loss since 12:00 a.m. Pacific, including settlements and cash-outs. Daylight saving time is handled automatically. Your own bets, deposits and practice money are excluded.");
      if (s.todayDate) para(panelBody, "Pacific date: " + s.todayDate + ".", "dim");
      if (s.today == null) para(panelBody, s.todayStatus === "incomplete"
        ? "A complete Pacific-day total could not be verified from the saved records."
        : "Waiting for a complete Pacific-day report.", "warn");
      para(panelBody, "This uses the time the bot records the result. A result discovered late can appear on a different day from Polymarket’s history.", "dim");
      para(panelBody, "Garden upgrades unlock at 1¢, 25¢, $1, $5 and $10 of verified net Polymarket bot profit today. They are decorations, not money spent. They can recede after a loss and reset at midnight Pacific. Practice gains and your own bets never unlock them.", "dim");
      para(panelBody, "Trading safety limits and the camera tour keep their UTC day; this card uses your Pacific day.", "dim");
      para(panelBody, s.todayAsOf ? "Profit report checked " + tyAge(s.todayAge) + "." : "Profit report time not available.", "dim");
      para(panelBody, "Open bets can still win or lose. This number is not a forecast.", "dim");
    } else {
      panelTitle.textContent = "Available account cash"; para(panelBody, fmtUsd(s.cash));
      para(panelBody, "Spendable cash reported by Polymarket for your shared account. It can include deposits and your own activity. It is not the bot’s profit.");
      if (s.reportedCash != null) para(panelBody, "Polymarket balance: " + fmtUsd(s.reportedCash) + ".", "dim");
      if (s.buyingPower != null) para(panelBody, "Available buying power: " + fmtUsd(s.buyingPower) + ".", "dim");
      para(panelBody, "Money in open bets is shown separately. The town refreshes saved account reports; it is not a tick-by-tick balance feed.", "dim");
      para(panelBody, s.cashAsOf ? "Cash reported " + tyAge(Math.max(0, Date.now() / 1000 - s.cashAsOf)) + "." : "Cash update time not reported.", "dim");
    }
    const oldAccount = panelKind === "ty-accounts" && (s.cashStale || !s.cashAsOf || s.venueStale || !s.venueAsOf)
      || panelKind === "ty-bets" && (s.venueStale || !s.venueAsOf)
      || panelKind === "ty-cash" && (s.cashStale || !s.cashAsOf)
      || panelKind === "ty-today" && s.todayStale;
    if (s.stale || offline || oldAccount) para(panelBody, "Showing the last report. Wait for a fresh update before treating these as current figures.", "warn");
    if (focusedRow) {
      const match = Array.from(panelBody.querySelectorAll(".ty-menu-row")).find(function (node) { return node.textContent === focusedRow; });
      if (match) match.focus({ preventScroll: true });
    }
    panelEl.scrollTop = scroll; return true;
  }
  function tycoonFrame() {
    if (!tycoonActive()) return;
    const stamp = Math.floor(Date.now() / 1000);
    if (stamp !== TY_UI.stamp) { TY_UI.stamp = stamp; tycoonDraw(); }
    const W = window.innerWidth, bottom = window.innerHeight - TY_UI.bottom, occupied = [];
    for (const m of TY_UI.markers) {
      const p = toScreen(m.at); let visible = p.ok && !TYCOON.selected;
      m.el.hidden = !visible; if (!visible) continue;
      if (!m.w) m.w = m.el.offsetWidth;
      const x = clamp(p.x - m.w / 2, 5, W - m.w - 5), y = p.y - 44;
      visible = y > TY_UI.top && y + 44 < bottom;
      if (visible && occupied.some(function (r) { return x < r.x + r.w + 3 && x + m.w + 3 > r.x && y < r.y + 47 && y + 47 > r.y; })) visible = false;
      m.el.hidden = !visible;
      if (visible) { m.el.style.transform = "translate3d(" + Math.round(x) + "px," + Math.round(y) + "px,0)"; occupied.push({ x: x, y: y, w: m.w }); }
    }
  }
  el("ty-mode").onclick = function () { tycoonView(!tycoonActive()); };
  el("ty-home").onclick = function () { tycoonChoose(null); };
  el("ty-more").onclick = function () { openPanel("ty-menu"); };
  el("ty-info").onclick = function () { openPanel("ty-flow"); };
  el("ty-alert").onclick = function () { openPanel("ty-alerts"); };
  BUS.on("data", function () { tycoonDraw(); }); BUS.on("frame", tycoonFrame);
  window.addEventListener("resize", tycoonMeasure);
  tycoonBuildCrew(); tycoonView(true);
  window.__skyport = Object.assign(window.__skyport || {}, { tycoon: {
    on: tycoonActive, select: tycoonChoose, set: tycoonView, camera: tycoonCameraState,
    summary: function () { return tycoonSummary(data, Date.now() / 1000); },
    bounds: function () { return { top: TY_UI.top, bottom: TY_UI.bottom }; }, park: tycoonParkState,
  } });
"""

TYCOON_MODULE = TYCOON_DATA + TYCOON_CAMERA + TYCOON_PARK + TYCOON_UI
