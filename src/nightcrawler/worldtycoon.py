"""Phone-first controls for the existing town; presentation only, using /api/page."""

from nightcrawler.worldtycoon_camera import TYCOON_CAMERA
from nightcrawler.worldtycoon_data import TYCOON_DATA
from nightcrawler.worldtycoon_park import TYCOON_PARK

TYCOON_HTML = """
<section id="ty-header" aria-label="Town and real money">
  <div class="ty-heading"><div><span class="ty-logo" aria-hidden="true">N</span><h1>Nightcrawler<span>YOUR BUSINESS TYCOON</span></h1></div>
    <button type="button" id="ty-more" aria-controls="panel" aria-label="Open town menu">Menu <span aria-hidden="true">☰</span></button></div>
  <div class="ty-money">
    <div><span>Kalshi cash</span><b id="ty-cash">—</b><small>Available account cash</small></div>
    <div><span>Kalshi bot profit</span><b id="ty-today">—</b><small>Since midnight Pacific</small></div>
  </div>
  <div class="ty-status"><span id="ty-state" role="status">Connecting</span><span id="ty-fresh">Waiting for reports</span></div>
  <div id="ty-exposure">Waiting for Kalshi account records</div>
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
"""

TYCOON_STYLE = r"""
#ty-header, #ty-dock, #ty-markers, #ty-selection { display: none; }
body.tycoon { --ty-ink: #183c57; --ty-muted: #56768b; --ty-edge: #b4cfdf;
  font-family: ui-rounded, "Arial Rounded MT Bold", "Trebuchet MS", system-ui, sans-serif; }
body.tycoon #ty-header, body.tycoon #ty-dock, body.tycoon #ty-selection { display: block; position: fixed; z-index: 10; color: var(--ty-ink);
  background: #f5fbff; border: 3px solid #fff; box-shadow: 0 4px 0 #286587, 0 7px 16px #163a5830; border-radius: 11px; }
body.tycoon #ty-header { top: calc(8px + env(safe-area-inset-top)); left: 9px; right: 9px; padding: 0 9px 7px; overflow: hidden; }
.ty-heading, .ty-heading > div { display: flex; gap: 8px; align-items: center; }
.ty-heading { justify-content: space-between; background: #167cb9; margin: 0 -9px 4px; padding: 5px 8px; border-bottom: 3px solid #0d659b; }
.ty-logo { width: 31px; height: 33px; display: grid; place-items: center; background: #ffd35d; border: 2px solid #ffeaa0;
  border-radius: 6px; color: #7b4c13; font-size: 23px; font-weight: 900; box-shadow: 0 2px 0 #a9711f; transform: rotate(-5deg); }
.ty-heading h1 { font-size: 18px; line-height: 1.05; margin: 0; font-weight: 900; letter-spacing: -.035em; color: #fff; text-shadow: 0 2px 0 #09517d; }
.ty-heading h1 span { display: block; font-size: 7px; font-weight: 800; letter-spacing: .12em; margin-top: 4px; color: #d9f5ff; text-shadow: none; }
#ty-more, #ty-home, #ty-info { min-height: 44px; cursor: pointer; font: inherit; font-size: 12px; font-weight: 750; padding: 6px 10px;
  border: 2px solid #fff9; border-radius: 7px; color: #fff; background: #258fca; box-shadow: 0 3px 0 #0e5682; }
#ty-more { background: #f4fbff; color: #185780; border-color: #fff; }
#ty-more:active, #ty-home:active, #ty-info:active { transform: translateY(2px); box-shadow: 0 1px 0 #0e5682; }
#ty-more span { margin-left: 5px; }
.ty-money { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
.ty-money > div { min-width: 0; background: #e7f2fa; border: 1px solid #c1dcea; border-top: 3px solid #378ac1; border-radius: 6px; padding: 2px 6px 3px; }
.ty-money > div + div { border-top-color: #8464c6; }
.ty-money span { display: block; font-size: 10px; line-height: 1.1; font-weight: 800; color: #355d79; }
.ty-money small { font-size: 8px; font-weight: 500; }
.ty-money b { display: block; font-size: 25px; line-height: 1; letter-spacing: -.035em; font-weight: 900; font-variant-numeric: tabular-nums; }
.ty-money .positive { color: #238243; } .ty-money .negative { color: #b13c3c; }
.ty-status { display: flex; gap: 5px; align-items: baseline; justify-content: space-between; margin-top: 5px; font-size: 8px; line-height: 1.25; color: #607787; }
#ty-state { flex-shrink: 0; font-weight: 700; } #ty-state.on { color: #256c47; }
#ty-state.paused, #ty-state.stale, #ty-state.offline, #ty-state.blocked, #ty-state.exposure { color: #985a12; }
#ty-fresh { text-align: right; max-width: 50%; }
#ty-exposure { margin-top: 4px; font-size: 9px; line-height: 1.3; color: #56768b; }
#ty-alert { width: 100%; min-height: 44px; margin-top: 7px; padding: 6px 9px; text-align: left; cursor: pointer;
  font: inherit; font-size: 11px; border-radius: 8px; border: 1px solid #e0b965; color: #70460b; background: #fff1c9; }
#ty-alert[hidden], body.tycoon #ty-selection[hidden] { display: none; }
body.tycoon #ty-dock { bottom: calc(10px + env(safe-area-inset-bottom)); left: 9px; right: 9px; padding: 9px 10px; border-radius: 9px; }
#ty-event { display: flex; align-items: center; gap: 7px; font-size: 11px; line-height: 1.35; }
.ty-event-dot { width: 9px; height: 9px; flex-shrink: 0; border-radius: 3px; background: #418ab5; border: 1px solid #23678f; }
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
.ty-marker b { display: inline-block; background: #fff; padding: 4px 7px; border: 2px solid #fff; border-bottom-color: var(--ty-department, #75aac8);
  border-radius: 5px; box-shadow: 0 2px 0 #244b6799; font-size: 10px; }
.ty-marker b::before { content: ""; display: inline-block; width: 5px; height: 5px; border-radius: 50%; margin-right: 4px; vertical-align: middle; background: #91a4ab; }
.ty-marker[data-status="working"] b::before { background: #47a466; }
.ty-marker[data-status="stuck"] b::before { background: #d08c29; }
.ty-marker[data-background="true"] b { background: #edf2f5; color: #667e8b; font-size: 9px; border-bottom-color: #bdccd4; }
.ty-marker[data-background="true"] b::before { background: #91a4ab; }
.ty-marker small { display: none; }
.ty-marker[hidden] { display: none; }
body.tycoon #cine, body.tycoon #tags, body.tycoon #intro, body.tycoon #details, body.tycoon #bar,
body.tycoon #honest, body.tycoon #postcard, body.tycoon #bubbles { display: none !important; }
body.tycoon #vignette { background: none; }
body.world-failed #ty-header, body.world-failed #ty-dock, body.world-failed #ty-markers { display: none; }
body.tycoon #panel { top: calc(16px + env(safe-area-inset-top)); bottom: auto; max-height: calc(100% - 40px - env(safe-area-inset-top) - env(safe-area-inset-bottom));
  z-index: 20; border-radius: 11px; background: #f5fbff; color: #183c57; border: 3px solid #fff; box-shadow: 0 5px 0 #286587, 0 12px 40px #12395140; }
body.tycoon #panel-close { min-height: 44px; min-width: 44px; background: #258ec7; color: #fff; border-color: #258ec7; }
body.tycoon #panel h2, body.tycoon #panel h3 { color: #203846; }
body.tycoon #panel .dim { color: #5e7482; } body.tycoon #panel .warn { color: #8a5010; }
body.tycoon #panel .ty-menu-row { color: #27495f; border-color: #d6e4eb; font-weight: 700; }
body.tycoon #panel .ty-person { color: #27495f; background: #edf5f8; border-color: #d4e3eb; border-left-color: var(--ty-department); }
body.tycoon #panel .ty-person small { color: #5e7482; }
body.tycoon #panel .ty-flow-card { border-color: #d1e2e9; }
.legacy-world-ui { display: none !important; }
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
.ty-money > div > small { display: block; font-size: 8px; line-height: 1.25; color: #607787; margin-top: 2px; }
.ty-money strong { font-size: 10px; color: #203846; white-space: nowrap; }
.ty-flow-card, .ty-position { overflow-wrap: anywhere; }
.ty-details { border-top: 1px solid #c8dce8; margin-top: 12px; padding-top: 4px; }
.ty-details > summary { min-height: 44px; display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px; font-weight: 750; }
.ty-details > summary::before { content: "▸"; color: #167cb9; }
.ty-details[open] > summary::before { content: "▾"; }
.ty-details > summary:focus-visible { outline: 3px solid #ffb72e; outline-offset: 2px; }
.ty-position small { color: #bbc9bd; }
.ty-flow-card { padding: 12px; margin-top: 12px; border: 1px solid #c8dbc033; border-left: 4px solid #9acbae; border-radius: 10px; }
.ty-flow-card h3 { margin: 0 0 8px; font-size: 16px; } .ty-flow-card p { margin: 8px 0; } .ty-flow-card.practice { border-left-color: #bdabdf; }
@media (min-width: 760px) {
  body.tycoon #ty-header { left: 20px; right: auto; width: 365px; }
  body.tycoon #ty-dock { left: 50%; right: auto; transform: translateX(-50%); width: 430px; }
  body.tycoon #ty-selection { left: auto; right: 20px; width: 330px; }
}
@media (max-width: 350px) { .ty-money small { font-size: 7px; } .ty-status { font-size: 7px; } }
"""

TYCOON_UI = r"""
  // ============================================================= TYCOON CONTROLS (read-only)
  const TY_UI = { summary: null, stamp: -1, markers: [], people: [], top: 140, bottom: 70, openDetails: {} };
  const tyHeader = el("ty-header"), tyDock = el("ty-dock"), tyMarkers = el("ty-markers");
  function tyAge(seconds) {
    if (seconds == null || !isFinite(seconds)) return "time unknown";
    if (seconds < 60) return "<1m ago";
    if (seconds < 3600) return Math.floor(seconds / 60) + "m ago";
    if (seconds < 86400) return Math.floor(seconds / 3600) + "h ago";
    return Math.floor(seconds / 86400) + "d ago";
  }
  function tyFee(value) {
    if (value === null || typeof value !== "number" || !isFinite(value)) return "—";
    if (value > 0 && value < .0001) return "<$0.0001";
    return value > 0 && value < .01 ? "$" + value.toFixed(4) : fmtUsd(value);
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
    if (!TYCOON.on) tycoonView();
    closePanel(); tycoonSelect(key); tycoonDraw();
    for (const p of TY_UI.people) p.b.setAttribute("aria-pressed", String(TYCOON.selected === p.key));
  }
  function tycoonView() {
    // One app, one view. Keep the old scene helpers only for the cast's animation machinery.
    filmStop(true); closePanel(); closeGuide(); cineIntroClose(false);
    tycoonEnable(true); cineSet(true, false); tycoonCutaway(true); tycoonPark(true);
    if (TP.labels) TP.labels.visible = false;
    if (TP.plates) TP.plates.visible = false;
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
      m.style.borderBottomColor = colour; m.style.setProperty("--ty-department", colour);
      m.onclick = b.onclick; tyMarkers.appendChild(m);
      const at = LAMP_AT[CAST[key].room].clone(); at.y += 2.2;
      TY_UI.markers.push({ key: key, el: m, label: label, sub: sub, at: at, w: 0 });
    }
  }
  function tycoonDraw() {
    const s = tycoonSummary(data, Date.now() / 1000); TY_UI.summary = s;
    if (typeof cineVaultDraw === "function") cineVaultDraw();
    if (offline) {
      s.activitySources = { polymarket_us: false, kalshi: false };
      (s.activity || []).forEach(function (e) { e.current = false; });
      if (s.growth) s.growth = Object.assign({}, s.growth, { qualified: false, level: null });
    }
    tycoonParkApply(s);
    if (typeof tycoonBusinessApply === "function") tycoonBusinessApply(s);
    const f = s.focus, k = f.account, state = offline ? "offline" : f.state;
    const stateWords = { live: "REAL MONEY · Kalshi", "pairs only": "REAL MONEY · completing pairs",
      practice: "PRACTICE · Kalshi", exposure: "Kalshi · real bets remain", blocked: "Kalshi · buys blocked",
      stale: "Kalshi · data delayed", offline: "Reconnecting", unknown: "Kalshi · waiting for report" };
    const status = el("ty-state"); status.className = state === "live" ? "on" : state;
    status.textContent = stateWords[state] || "Kalshi · waiting for report";
    const warning = tycoonFocusWarning(s, offline);
    el("ty-alert").hidden = !warning; tyText("ty-alert", warning || "");
    tyText("ty-cash", fmtUsd(f.cash)); tyText("ty-today", fmtSigned(f.today));
    el("ty-today").className = f.today > 0 ? "positive" : f.today < 0 ? "negative" : "";
    const oldMoney = [];
    if (f.cashStale) oldMoney.push(f.cashAt ? "Cash checked " + tyAge(f.cashAge) : "Cash time unknown");
    if (k.accountStale) oldMoney.push(k.accountAt ? "Account checked " + tyAge(k.accountAge) : "Account time unknown");
    if (!f.todayCurrent) oldMoney.push("Profit needs verification");
    tyText("ty-fresh", offline ? "Connection lost · last report" : f.stale ? "Waiting for fresh Kalshi data"
      : oldMoney.length ? oldMoney.join(" · ")
      : f.cashAt ? "Cash checked " + tyAge(f.cashAge) : "Waiting for Kalshi");
    const count = function (n, word) { return n === null ? word + " unknown" : n + " " + word; };
    tyText("ty-exposure", count(f.positions, "positions") + " · " + count(f.orders, "waiting orders")
      + " · " + fmtUsd(f.exposure) + " at risk" + (offline || k.accountStale ? " · last report" : ""));
    const chosen = s.crew.find(function (c) { return c.key === TYCOON.selected; }) || (CAST[TYCOON.selected] ? {
      name: CAST[TYCOON.selected].name, job: "Workstation", status: "unknown", doing: "Waiting for a crew report.", age: null, practice: null,
    } : null);
    el("ty-selection").hidden = !chosen;
    const workWords = { working: "Recently active", waiting: "Waiting", idle: "Idle", stuck: "Needs attention", unknown: "No current report" };
    const activity = ["working", "waiting", "idle", "stuck", "unknown"].map(function (k) {
      const n = s.crew.filter(function (c) { return c.status === k; }).length;
      return n ? n + " " + ({ working: "active", waiting: "waiting", idle: "idle", stuck: "need attention", unknown: "unreported" }[k]) : "";
    }).filter(Boolean).join(" · ");
    tyText("ty-context", chosen ? (chosen.background ? chosen.practice ? "BACKGROUND PRACTICE" : "BACKGROUND DESK" : "KALSHI WORKSTATION") : "YOUR CREW");
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
      const background = c ? c.background === true : ["pip", "nyx"].includes(m.key);
      m.el.dataset.background = String(background);
      const markerName = c ? c.name : CAST[m.key].name;
      const label = markerName + (background ? c && c.practice === true ? " · practice" : " · background" : "");
      if (m.label.textContent !== label) { m.label.textContent = label; m.w = 0; }
      if (c) {
        const job = c.practice ? c.job + " · practice" : c.job;
        if (m.sub.textContent !== job) { m.sub.textContent = job; m.w = 0; }
        m.el.setAttribute("aria-label", "View " + c.name + "’s workstation");
      } else { m.sub.textContent = "No current report"; m.w = 0; }
    }
    tyText("ty-event-text", s.event ? s.event.text : "Kalshi · waiting for the next recorded event");
    tyText("ty-event-age", s.event ? tyAge(s.event.age) : "");
    const growth = s.growth;
    tyText("ty-growth", growth && growth.qualified ? "Gardens " + growth.level + "/5 · " + growth.label
      : "Kalshi gardens wait for verified profit · tap a building to visit");
    if (panelKind && panelKind.indexOf("ty-") === 0 && panelKind !== "ty-menu") tycoonPanel();
    tycoonMeasure();
  }
  function tycoonFocusWarning(s, disconnected) {
    if (disconnected) return statusEl.textContent || "Connection lost. Showing the last Kalshi report.";
    const f = s.focus, k = f.account;
    if (k.integrityNote) return k.integrityNote;
    if (k.cleanupPending) return "Kalshi order cancellation and account checks are still pending.";
    if (f.stale || f.state === "unknown") return "Waiting for a fresh Kalshi connection. Figures may be old.";
    if (k.totalHalted) return k.stopNote;
    if (k.locksOnly) return k.stateText;
    if (f.book.status === "incomplete") return "Kalshi records need review; profit and town growth are unverified.";
    if (f.cashStale) return "Kalshi cash needs a fresh balance read.";
    return "";
  }
  function tycoonDetails(parent, title, key) {
    const box = document.createElement("details"), label = document.createElement("summary");
    box.className = "ty-details"; box.dataset.detailKey = key; label.textContent = title;
    const state = TY_UI.openDetails || (TY_UI.openDetails = {});
    box.open = state[key] === true;
    box.ontoggle = function () { state[key] = this.open; };
    box.appendChild(label); parent.appendChild(box); return box;
  }
  function tycoonBusinessDetails(parent, s, venueKey) {
    const heading = function (words) { const h = document.createElement("h3"); h.textContent = words; parent.appendChild(h); };
    const amount = function (value) { return value === null ? "unknown" : String(value); };
    [venueKey || "kalshi"].forEach(function (key) {
      const v = s.business.venues[key]; heading(v.name + " · recorded orders and bets");
      para(parent, v.sourceNote || "Waiting for saved venue records.", "dim");
      para(parent, v.asOf ? (key === "kalshi" ? "Saved checkpoint " : "Completed desk update ") + tyAge(v.age)
        + (v.current ? "." : " · records need review or a fresh update.") : "Record time not reported.", "dim");
      v.issues.forEach(function (issue) { para(parent, issue, "dim"); });
      if (v.orders.length) {
        v.orders.forEach(function (o) {
          para(parent, o.side + " · " + o.title + " · " + o.status);
          if (o.lock) para(parent, "Pair-completion order: uses cash to reduce the existing possible loss.", "dim");
          para(parent, amount(o.filled) + " filled / " + amount(o.quantity) + " requested · " + amount(o.remaining)
            + " remaining · reserved " + fmtUsd(o.reserved), "dim");
        });
      } else para(parent, "No open-order rows in this report. Unconfirmed orders remain separate from filled bets.", "dim");
      if (v.positions.length) {
        para(parent, "Holdings basis: " + v.positionsBasis, "dim");
        v.positions.forEach(function (p) {
          para(parent, (p.scope === "owner" ? "Your bet" : p.scope === "bot" ? "Bot bet" : "Owner unknown")
            + " · " + p.side + " · " + p.title);
          para(parent, amount(p.quantity) + " contracts · recorded cost " + fmtUsd(p.cost)
            + " · fee " + tyFee(p.fee) + (p.feeBasis ? " (" + p.feeBasis + ")" : ""), "dim");
          if (p.statusNote) para(parent, p.statusNote, "warn");
        });
      } else para(parent, "No individual holdings recorded here; check the account totals above.", "dim");
      if (v.truncated.orders || v.truncated.positions || v.truncated.events) para(parent, "Showing the most recent records; this list is not the entire history.", "dim");
    });
    const activity = s.business.activity.filter(function (e) { return e.venue === (venueKey || "kalshi"); });
    heading("Latest " + (venueKey === "polymarket_us" ? "Polymarket" : "Kalshi") + " activity");
    if (!activity.length) para(parent, "No real event records available yet.", "dim");
    activity.slice(0, 12).forEach(function (e) {
      para(parent, e.text);
      para(parent, tyAge(e.age) + (e.current ? "" : " · source needs an update")
        + (e.fee !== null ? " · " + (e.feeBasis || "recorded") + " fee " + tyFee(e.fee) : ""), "dim");
    });
    para(parent, "Orders reserve money; only fills create holdings. Held-to-settlement profit includes recorded fees. Cash-outs use venue realized figures; fee inclusion may be unknown. A cancellation request does not prove the order was cancelled.", "dim");
  }
  function tycoonResearchDetails(parent, s) {
    (s.research || []).forEach(function (r) {
      const h = document.createElement("h3"); h.textContent = r.name + " · " + r.scope; parent.appendChild(h);
      para(parent, r.status);
      if (r.count !== null) para(parent, r.count + " " + r.countLabel, "dim");
      para(parent, r.asOf ? (r.timeLabel || "Report checked") + " " + tyAge(r.age) : "No current report", "dim");
    });
    para(parent, "Research and practice stay separate from real money. They never change Kalshi cash, profit or gardens.", "dim");
  }
  function tycoonOtherAlerts(parent) {
    const alerts = data && Array.isArray(data.alerts) ? data.alerts.filter(function (a) { return a && a.text; }) : [];
    if (!alerts.length) return;
    const other = tycoonDetails(parent, "Other service notices (" + alerts.length + ")", "service-notices");
    alerts.forEach(function (a) { para(other, a.text, "warn"); });
    para(other, "These notices keep their original desk or service scope. They do not describe Kalshi unless they name it.", "dim");
  }
  function tycoonPanelMerge(target, source) {
    // Keep native disclosure controls attached while their account data refreshes.
    // Replacing their content is safe; replacing the summary interrupts taps and keyboard focus.
    const keep = new Set();
    Array.from(source.children).forEach(function (fresh, index) {
      const key = fresh.dataset.detailKey;
      const old = key ? Array.from(target.children).find(function (node) { return node.dataset.detailKey === key; })
        : target.children[index];
      let node = fresh;
      if (old && !keep.has(old) && old.tagName === fresh.tagName && (key || !old.dataset.detailKey)) {
        node = old; node.className = fresh.className;
        if (key) {
          const label = node.querySelector("summary"), nextLabel = fresh.querySelector("summary");
          if (label.textContent !== nextLabel.textContent) label.textContent = nextLabel.textContent;
          node.ontoggle = fresh.ontoggle;
          Array.from(node.children).forEach(function (child) { if (child !== label) node.removeChild(child); });
          Array.from(fresh.children).forEach(function (child) { if (child !== nextLabel) node.appendChild(child); });
        } else if (fresh.children.length) {
          node.textContent = "";
          Array.from(fresh.children).forEach(function (child) { node.appendChild(child); });
        } else if (node.textContent !== fresh.textContent) node.textContent = fresh.textContent;
        if (fresh.onclick) node.onclick = fresh.onclick;
      }
      if (target.children[index] !== node) target.insertBefore(node, target.children[index] || null);
      keep.add(node);
    });
    Array.from(target.children).forEach(function (node) { if (!keep.has(node)) target.removeChild(node); });
  }
  function tycoonPanel() {
    if (!panelKind || panelKind.indexOf("ty-") !== 0) return false;
    // Data polls must not replace focused navigation while someone is choosing a destination.
    if (panelKind === "ty-menu" && panelTitle.textContent === "Your town" && panelBody.querySelector(".ty-menu-row")) return true;
    if (panelKind === "ty-help" && panelTitle.textContent === "Help" && panelBody.querySelector("h3")) return true;
    const s = TY_UI.summary || tycoonSummary(data, Date.now() / 1000);
    // A live clock must not replace a summary element while a phone is trying to tap it.
    // Compare the actual rendered data and freshness flags, rounding ages only to their displayed words.
    const signature = JSON.stringify([panelKind, TYCOON.selected, offline, offline ? statusEl.textContent : null,
      data && data.alerts, s], function (key, value) {
      return key === "age" || key.endsWith("Age") ? tyAge(value) : value;
    });
    if (TY_UI.panelSignature === signature && TY_UI.panelRoot && TY_UI.panelRoot === panelBody.children[0]) return true;
    const focusedRow = typeof document !== "undefined" && document.activeElement
      && document.activeElement.classList.contains("ty-menu-row") && panelBody.contains(document.activeElement)
      ? document.activeElement.textContent : null;
    const focusedDetails = document.activeElement && document.activeElement.tagName === "SUMMARY"
      && panelBody.contains(document.activeElement) ? document.activeElement.parentElement.dataset.detailKey : null;
    const focusedPerson = document.activeElement && document.activeElement.classList.contains("ty-person")
      && panelBody.contains(document.activeElement) ? document.activeElement.dataset.key : null;
    const scroll = panelEl.scrollTop, f = s.focus, k = f.account;
    const content = document.createElement("div"); panelEl.className = "";
    const row = function (title, target, action) {
      const b = document.createElement(target && target[0] === "/" ? "a" : "button");
      b.className = "ty-menu-row"; b.textContent = title;
      if (b.tagName === "A") b.href = target;
      else { b.type = "button"; b.onclick = action || function () { openPanel(target); }; }
      content.appendChild(b); return b;
    };
    if (panelKind === "ty-menu") {
      panelTitle.textContent = "Your town";
      row("Money", "ty-accounts"); row("Team", "ty-team"); row("Help", "ty-help");
    } else if (panelKind === "ty-team") {
      panelTitle.textContent = "Your team";
      para(content, "Tap a teammate or their building to visit their workstation.", "dim");
      const crew = document.createElement("div"); crew.className = "ty-menu-crew";
      TY_UI.people.filter(function (p) { return !["pip", "nyx"].includes(p.key); }).forEach(function (p) { crew.appendChild(p.b); });
      content.appendChild(crew);
      const background = tycoonDetails(content, "Background practice and research", "team-background");
      const labs = document.createElement("div"); labs.className = "ty-menu-crew";
      TY_UI.people.filter(function (p) { return ["pip", "nyx"].includes(p.key); }).forEach(function (p) { labs.appendChild(p.b); });
      background.appendChild(labs); tycoonResearchDetails(background, s);
      para(content, "The town follows Kalshi. Polymarket remains separate; its real-money status is in Money.", "dim");
    } else if (panelKind === "ty-help") {
      panelTitle.textContent = "Help";
      para(content, "Tap a building to see who works there. Drag to look around; pinch to zoom. Town returns to the full view.");
      para(content, "Walking and chatting are decoration. Work descriptions and money come from the bot’s recorded reports.");
      para(content, "Garden upgrades reflect Kalshi bot profit since midnight Pacific: 1¢, 25¢, $1, $5 and $10. Its saved results must be complete and current. Losses can remove gardens; midnight resets them. Polymarket, practice, deposits and your own bets do not count.", "dim");
      para(content, "Jet shows Kalshi order and fill receipts; Mote records its settled results. Only a newly received, dated, real Kalshi bot profit can trigger a gold delivery. Old events are never replayed on reconnect. Neither movement nor a submitted order means money was made.", "dim");
      const title = document.createElement("h3"); title.textContent = "Stop new real orders"; content.appendChild(title);
      para(content, "On Railway’s bot service, set both POLYDESK_MODE = paper and SPEEDDESK_KALSHI_MODE = paper.");
      para(content, "After the restart, verify both desks are in practice and Kalshi’s resting bids were cancelled and remaining exposure reconciled.");
      para(content, "Already filled bets still win or lose at settlement. This page gives instructions; it does not change trading settings.", "warn");
    } else if (panelKind === "ty-research") {
      panelTitle.textContent = "Research desks";
      tycoonResearchDetails(content, s);
    } else if (panelKind === "ty-stop") {
      panelTitle.textContent = "Stop new real orders";
      para(content, "On Railway’s bot service, set both:");
      para(content, "POLYDESK_MODE = paper"); para(content, "SPEEDDESK_KALSHI_MODE = paper");
      para(content, "Wait for the restart and verify that both desks report practice. Check that Kalshi’s resting bids were cancelled and its remaining exposure was reconciled.");
      para(content, "Already filled bets stay open and still win or lose at settlement. This page shows instructions; it does not change trading settings.", "warn");
    } else if (panelKind === "ty-accounts") {
      panelTitle.textContent = "Kalshi money";
      para(content, (k.active ? "REAL MONEY (Kalshi)" : k.practice ? "PRACTICE (Kalshi)" : k.stateText) + " · cash " + fmtUsd(f.cash));
      para(content, "Bot profit today (midnight Pacific): " + fmtSigned(f.today));
      para(content, "Cash is the account balance. Profit is settled bot winnings minus losses and fees; they are different numbers.", "dim");
      para(content, "Money at risk: " + fmtUsd(k.exposure) + " · " + (k.positions === null ? "unknown" : k.positions) + " positions");
      para(content, (k.orders === null ? "Unknown" : k.orders) + " waiting orders · cash reserved " + fmtUsd(k.reserved));
      para(content, k.cashAt ? "Kalshi cash checked " + tyAge(k.cashAge) + "." : "Kalshi cash update time is unknown.", "dim");
      if (k.reason && !k.integrityNote && !k.locksOnly) para(content, k.reason, "dim");
      if (k.active && k.locksOnly) para(content, k.stateText, "warn");
      if (k.totalHalted) para(content, k.stopNote, "warn");
      if (k.integrityNote) para(content, k.integrityNote, "warn");
      if (k.integrityResetNote) para(content, k.integrityResetNote, "warn");
      if (k.cashStale) para(content, "Kalshi cash may be old; waiting for a fresh balance read.", "warn");
      if (!f.todayCurrent) para(content, f.todayReason || "Kalshi’s Pacific-day profit is unverified.", "warn");
      if (k.cleanupPending) para(content, "Resting-order cancellation and reconciliation are still pending.", "warn");
      if (k.stale) para(content, "Kalshi’s report is delayed or missing. These figures may be old.", "warn");
      if (s.business.available) {
        const receipts = tycoonDetails(content, "Kalshi orders, positions and receipts", "kalshi-receipts");
        tycoonBusinessDetails(receipts, s, "kalshi");
      }
      const limits = tycoonDetails(content, "Limits, fees and account checks", "kalshi-checks");
      if (k.limits && [k.limits.window, k.limits.open, k.limits.day, k.limits.total].some(function (n) { return n !== null; })) para(limits, "New-bet limits: " + fmtUsd(k.limits.window) + " per window · " + fmtUsd(k.limits.open)
        + " at risk · " + fmtUsd(k.limits.day) + " daily loss stop · " + fmtUsd(k.limits.total) + " total loss stop (UTC).", "dim");
      if (k.limitsNote) para(limits, k.limitsNote, "dim");
      if (k.riskNote) para(limits, k.riskNote, "dim");
      if (k.reserveNote) para(limits, k.reserveNote, "dim");
      para(limits, "Fees paid today (UTC): " + tyFee(k.fees == null ? null : k.fees) + ". Settled profit already includes its fees.", "dim");
      para(limits, "Settled profit (UTC): " + fmtSigned(k.today) + " · matched pairs " + fmtSigned(k.locked == null ? null : k.locked)
        + " · direction " + fmtSigned(k.directional == null ? null : k.directional), "dim");
      if (k.todayStale) para(limits, "Kalshi’s UTC-day result is delayed or unavailable.", "warn");
      para(limits, k.asOf ? "Kalshi desk report " + tyAge(k.age) + "." : "Kalshi desk report time is unknown.", "dim");
      para(limits, k.accountAt ? "Account reconciliation recorded " + tyAge(k.accountAge)
        + (k.accountStale ? " · may be old." : ".") : "Account reconciliation time is not recorded; a desk report or checkpoint does not prove the account was checked.", "dim");
      const pmMode = s.stale || s.state === "unknown" ? "status needs update" : s.on === true ? "REAL MONEY" : "new real buys off";
      const other = tycoonDetails(content, "Polymarket · " + pmMode + " · separate account", "polymarket-account");
      para(other, "Polymarket keeps running separately. It is not practice when real money is on. Its results do not change this Kalshi town.", "dim");
      para(other, "POLYMARKET US", "dim");
      para(other, "Available cash: " + fmtUsd(s.cash));
      para(other, "Open markets: " + (s.count == null ? "not reported" : s.count) + " · value " + fmtUsd(s.value));
      para(other, "Shared with your own bets. Cash is not profit. " + (s.stateText || "Money mode not reported."), "dim");
      para(other, "Bot profit today (midnight Pacific): " + fmtSigned(s.today));
      para(other, "Profit excludes your own bets, deposits and practice. It uses the bot’s recorded booking time; late discoveries can differ from venue history.", "dim");
      if (s.limits && [s.limits.open, s.limits.day, s.limits.total].some(function (n) { return n !== null; })) para(other, "Reported limits: " + fmtUsd(s.limits.open) + " open · " + fmtUsd(s.limits.day)
        + " daily loss stop · " + fmtUsd(s.limits.total) + " total loss stop. Safety days use UTC.", "dim");
      para(other, s.cashAsOf ? "Cash checked " + tyAge(s.cashAge) + "." : "Cash update time unknown.", "dim");
      para(other, s.venueAsOf ? "Open bets checked " + tyAge(s.venueAge) + "." : "Open-bet update time unknown.", "dim");
      if (s.todayReason || s.today === null || s.todayStale) para(other, s.todayReason || "The Pacific-day profit report is unavailable or old.", "warn");
      if (s.pending && s.pending.count) para(other, s.pending.count + " bot orders still awaiting confirmation.", "warn");
      if (s.positions.length && !(s.business && s.business.available)) {
        para(other, "Recorded bets · may differ from current account holdings", "dim");
        s.positions.forEach(function (p) { para(other, p.side + " · " + p.question); });
        para(other, s.positionsNote, "dim");
      }
      if (s.cashStale || !s.cashAsOf || s.venueStale || !s.venueAsOf || s.stale) para(other, "Polymarket’s account figures need a fresh update.", "warn");
      if (s.business.available) tycoonBusinessDetails(other, s, "polymarket_us");
      const practice = tycoonDetails(content, "Background practice and research", "money-background");
      tycoonResearchDetails(practice, s);
      tycoonOtherAlerts(content);
    } else if (panelKind === "ty-alerts") {
      panelTitle.textContent = "Kalshi connection";
      const warning = tycoonFocusWarning(s, offline);
      para(content, warning || "No current Kalshi connection warning.", warning ? "warn" : "dim");
      para(content, k.stateText);
      if (f.todayReason) para(content, f.todayReason, "warn");
      if (k.accountAt) para(content, "Account checked " + tyAge(k.accountAge) + ".", "dim");
      tycoonOtherAlerts(content);
    } else if (panelKind === "ty-flow") {
      const chosen = s.crew.find(function (c) { return c.key === TYCOON.selected; });
      panelTitle.textContent = chosen ? chosen.name + "’s workstation" : "How your town works";
      if (chosen) {
        para(content, chosen.jobDetail || "Role not reported yet.");
        para(content, chosen.recordedWork || chosen.doing, "dim");
        if (chosen.age !== null) para(content, "Last activity recorded " + tyAge(chosen.age) + ".", "dim");
      }
      if (chosen && ["pip", "nyx"].includes(chosen.key)) {
        para(content, "This coin team runs separately in the background. Its own report shows its money mode. Its work does not create Kalshi orders or change the town’s money.", "dim");
        const practice = tycoonDetails(content, "Practice and research reports", "workstation-background");
        tycoonResearchDetails(practice, s);
      } else {
        para(content, "Kalshi · " + k.stateText);
        para(content, "Voss follows the Kalshi Bitcoin desk. Rook shows its safeguards. Jet relays actual order and fill receipts. Mote records fees and settlements.", "dim");
        para(content, "A waiting order reserves cash. A fill becomes a position. Settlement changes the bot’s profit; only recorded profit earns gardens.", "dim");
        if (chosen && chosen.key === "rook") {
          if (k.riskNote) para(content, k.riskNote, "dim");
          if (k.integrityNote) para(content, k.integrityNote, "warn");
          if (k.totalHalted) para(content, k.stopNote, "warn");
          if (k.limitsNote) para(content, k.limitsNote, "dim");
        }
        if (s.business.available) {
          const receipts = tycoonDetails(content, "Kalshi receipts", "workstation-receipts");
          tycoonBusinessDetails(receipts, s, "kalshi");
        }
      }
      para(content, "Walking and chatting are decoration. This view does not send orders or change any trading setting.", "dim");
    } else if (panelKind === "ty-bets") {
      panelTitle.textContent = "Kalshi positions and orders";
      para(content, "Money at risk: " + fmtUsd(f.exposure));
      if (s.business.available) tycoonBusinessDetails(content, s, "kalshi");
      else para(content, "Waiting for Kalshi’s recorded positions.", "dim");
    } else if (panelKind === "ty-result") {
      panelTitle.textContent = "Recent real result";
      para(content, s.event ? s.event.text : "No recent real settlement reported.");
      if (s.event) { para(content, "Recorded " + tyAge(s.event.age) + ".", "dim"); para(content, s.eventNote, "dim"); }
    } else if (panelKind === "ty-today") {
      panelTitle.textContent = "Kalshi bot profit today"; para(content, fmtSigned(f.today));
      para(content, "Real Kalshi bot profit after recorded fees, since midnight Pacific. Deposits, practice and Polymarket results do not count.");
      if (f.todayDate) para(content, "Pacific date: " + f.todayDate + ".", "dim");
      if (f.todayReason) para(content, f.todayReason, "warn");
      para(content, "Gardens mark 1¢, 25¢, $1, $5 and $10 in verified Kalshi profit. Losses can remove them; midnight Pacific resets them. Trading limits still use UTC.", "dim");
      para(content, "Open positions can still win or lose. This result is not a forecast.", "dim");
    } else {
      panelTitle.textContent = "Kalshi account cash"; para(content, fmtUsd(f.cash));
      para(content, "Cash reported by Kalshi is separate from the bot’s profit and the money still at risk.");
      para(content, f.cashAt ? "Cash reported " + tyAge(f.cashAge) + "." : "Cash update time not reported.", "dim");
    }
    if (offline) para(content, "Connection lost. Showing the last report; wait for a fresh update.", "warn");
    tycoonPanelMerge(panelBody, content);
    if (focusedRow) {
      const match = Array.from(panelBody.querySelectorAll(".ty-menu-row")).find(function (node) { return node.textContent === focusedRow; });
      if (match) match.focus({ preventScroll: true });
    }
    if (focusedDetails) {
      const detail = Array.from(panelBody.querySelectorAll("details")).find(function (node) { return node.dataset.detailKey === focusedDetails; });
      if (detail) detail.querySelector("summary").focus({ preventScroll: true });
    }
    if (focusedPerson) {
      const person = Array.from(panelBody.querySelectorAll(".ty-person")).find(function (node) { return node.dataset.key === focusedPerson; });
      if (person) person.focus({ preventScroll: true });
    }
    TY_UI.panelSignature = signature; TY_UI.panelRoot = panelBody.children[0];
    panelEl.scrollTop = scroll; return true;
  }
  function tycoonMarkerPlace(p, width, height, viewportWidth, top, bottom, occupied) {
    if (!p.ok || !isFinite(p.x) || !isFinite(p.y) || p.x < 0 || p.x > viewportWidth
        || p.y <= top || p.y >= bottom || width > viewportWidth - 10) return null;
    const step = Math.min(96, Math.max(48, width + 4));
    const offsets = [[0,0],[48,0],[-48,0],[step,0],[-step,0],[0,48],[0,-48],[48,48],[-48,48],[48,-48],[-48,-48]];
    for (const offset of offsets) {
      const x = Math.max(5, Math.min(viewportWidth - width - 5, p.x - width / 2 + offset[0]));
      const y = p.y - height + offset[1];
      if (y <= top || y + height >= bottom) continue;
      if (occupied.some(function (r) { return x < r.x + r.w + 3 && x + width + 3 > r.x
          && y < r.y + r.h + 3 && y + height + 3 > r.y; })) continue;
      return { x: x, y: y, w: width, h: height };
    }
    return null;
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
      const placed = tycoonMarkerPlace(p, Math.max(44, m.w), Math.max(44, m.el.offsetHeight), W, TY_UI.top, bottom, occupied);
      m.el.hidden = !placed;
      if (placed) { m.el.style.transform = "translate3d(" + Math.round(placed.x) + "px," + Math.round(placed.y) + "px,0)"; occupied.push(placed); }
    }
  }
  el("ty-home").onclick = function () { tycoonChoose(null); };
  el("ty-more").onclick = function () { openPanel("ty-menu"); };
  el("ty-info").onclick = function () { openPanel("ty-flow"); };
  el("ty-alert").onclick = function () { openPanel("ty-alerts"); };
  BUS.on("data", function () { tycoonDraw(); }); BUS.on("frame", tycoonFrame);
  window.addEventListener("resize", tycoonMeasure);
  tycoonBuildCrew(); tycoonView();
  window.__skyport = Object.assign(window.__skyport || {}, { tycoon: {
    on: tycoonActive, select: tycoonChoose, camera: tycoonCameraState,
    summary: function () { return tycoonSummary(data, Date.now() / 1000); },
    bounds: function () { return { top: TY_UI.top, bottom: TY_UI.bottom }; }, park: tycoonParkState,
  } });
"""

TYCOON_MODULE = TYCOON_DATA + TYCOON_CAMERA + TYCOON_PARK + TYCOON_UI
