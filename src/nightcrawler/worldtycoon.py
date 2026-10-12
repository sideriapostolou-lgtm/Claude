"""Phone-first controls for the existing town; presentation only, using /api/page."""

from nightcrawler.worldtycoon_camera import TYCOON_CAMERA
from nightcrawler.worldtycoon_data import TYCOON_DATA
from nightcrawler.worldtycoon_park import TYCOON_PARK

TYCOON_HTML = """
<section id="ty-header" aria-label="Town and real money">
  <div class="ty-heading"><div><span class="ty-eyebrow">NIGHTCRAWLER</span><h1>Your town</h1></div>
    <span id="ty-state" role="status">Connecting</span><button type="button" id="ty-mode">Camera tour</button></div>
  <div class="ty-money">
    <button type="button" id="ty-cash-card" aria-controls="panel"><span>Available cash</span><b id="ty-cash">—</b><small>Polymarket account</small></button>
    <button type="button" id="ty-today-card" aria-controls="panel"><span>Bot today</span><b id="ty-today">—</b><small>Realized · UTC</small></button>
    <button type="button" id="ty-bets-card" aria-controls="panel"><span>Account bets</span><b id="ty-bets">—</b><small id="ty-held">Includes your own</small></button>
  </div>
  <button type="button" id="ty-alert" aria-controls="panel" hidden></button>
  <p id="ty-fresh">Waiting for the bot’s report…</p>
</section>
<div id="ty-markers" aria-label="Town workstations"></div>
<section id="ty-dock" aria-label="Your crew">
  <div class="ty-dock-head"><button type="button" id="ty-info" aria-controls="panel" aria-label="How the town works"><span class="ty-eyebrow" id="ty-context">YOUR CREW</span><span class="ty-focus-line"><b id="ty-focus">The whole town</b><span aria-hidden="true">ⓘ</span></span></button>
    <button type="button" id="ty-home" aria-label="Return to the whole town">Whole town <span aria-hidden="true">↗</span></button></div>
  <p id="ty-doing">Tap a teammate to see their desk and latest report.</p>
  <div id="ty-crew" aria-label="Choose a teammate"></div>
  <button type="button" id="ty-event" aria-controls="panel"><span class="ty-eyebrow">RECENT REAL RESULT</span><span id="ty-event-text">Waiting for the bot’s report…</span><span id="ty-event-age"></span></button>
</section>
"""

TYCOON_STYLE = r"""
#ty-header, #ty-dock, #ty-markers { display: none; }
body.tycoon { --ty-ink: #fff4de; --ty-muted: #c1c9c0; --ty-edge: rgba(220,226,204,.18); }
body.tycoon #ty-header, body.tycoon #ty-dock { display: block; position: fixed; z-index: 10; color: var(--ty-ink);
  background: rgba(16,29,31,.96); border: 1px solid var(--ty-edge); box-shadow: 0 8px 24px rgba(0,0,0,.22); border-radius: 16px; }
body.tycoon #ty-header { top: calc(8px + env(safe-area-inset-top)); left: 8px; right: 8px; padding: 9px 10px 7px; }
.ty-heading { display: flex; gap: 7px; align-items: center; margin-bottom: 9px; }
.ty-heading > div { flex: 1; min-width: 0; }
.ty-eyebrow { font-size: 9px; line-height: 1.2; font-weight: 800; letter-spacing: .12em; color: #a8bdad; }
.ty-heading h1 { font-size: 18px; line-height: 1.2; margin: 1px 0 0; font-weight: 750; letter-spacing: -.02em; }
#ty-state { font-size: 10px; font-weight: 700; max-width: 95px; color: #c4cfcc; text-align: right; }
#ty-state.on { color: #ffb7ab; } #ty-state.paused, #ty-state.stale, #ty-state.offline { color: #ffe1a1; }
#ty-mode, #ty-home { min-height: 44px; cursor: pointer; font: inherit; font-size: 11px; font-weight: 650; padding: 6px 9px;
  border: 1px solid rgba(211,227,207,.25); border-radius: 10px; color: #e4eddc; background: rgba(180,201,168,.08); }
.ty-money { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 6px; }
.ty-money button { min-width: 0; padding: 7px 7px 6px; border: 1px solid var(--ty-edge); border-radius: 9px; text-align: left;
  color: var(--ty-ink); font: inherit; background: rgba(201,214,176,.05); cursor: pointer; }
.ty-money span, .ty-money small { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ty-money span { font-size: 10px; color: #cdd5c9; } .ty-money small { margin-top: 2px; font-size: 8.5px; color: #a9b9ac; }
.ty-money b { display: block; font-size: clamp(17px,5.1vw,24px); line-height: 1.3; letter-spacing: -.025em; font-variant-numeric: tabular-nums; }
.ty-money .positive { color: #abecad; } .ty-money .negative { color: #ffb7ab; }
#ty-fresh { font-size: 9px; line-height: 1.2; margin: 6px 0 0; color: #adbdb2; }
#ty-alert { width: 100%; min-height: 44px; margin-top: 6px; padding: 6px 8px; text-align: left; cursor: pointer;
  font: inherit; font-size: 11px; line-height: 1.3; border-radius: 8px; border: 1px solid #b68d4b; color: #ffe1a1; background: #43372a; }
#ty-alert[hidden] { display: none; }
body.tycoon #ty-dock { bottom: calc(8px + env(safe-area-inset-bottom)); left: 8px; right: 8px; padding: 8px 10px; }
.ty-dock-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
#ty-info { background: none; color: inherit; border: 0; padding: 0; text-align: left; min-height: 44px; min-width: 0; cursor: pointer; }
.ty-focus-line { display: flex; align-items: center; gap: 6px; margin-top: 2px; }
#ty-focus { font-size: 16px; line-height: 1.15; letter-spacing: -.01em; }
.ty-focus-line > span { font-size: 13px; color: #c2d7b3; }
#ty-home { min-height: 44px; flex-shrink: 0; } #ty-home span { color: #c5d7a5; }
#ty-doing { min-height: 28px; margin: 4px 0 7px; font-size: 11px; line-height: 1.3; color: #d0d9cd;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
#ty-crew { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 5px; }
.ty-person { display: flex; align-items: center; gap: 6px; min-width: 0; min-height: 44px; padding: 5px 6px; text-align: left;
  color: #e9eddf; background: rgba(199,213,186,.04); border: 1px solid rgba(204,220,196,.15); border-radius: 9px; cursor: pointer; }
.ty-person[aria-pressed="true"] { background: rgba(221,206,142,.13); border-color: #d6c68b; }
.ty-person i { height: 25px; width: 25px; flex-shrink: 0; border-radius: 8px; display: grid; place-items: center; font-style: normal;
  font-size: 12px; font-weight: 800; color: #fff6dc; background: #425e67; position: relative; }
.ty-person i::after { content: ""; position: absolute; bottom: -2px; right: -2px; width: 7px; height: 7px; border-radius: 50%;
  border: 2px solid #16272a; background: #86918d; }
.ty-person[data-status="working"] i::after { background: #a5e6a6; }
.ty-person[data-status="waiting"] i::after, .ty-person[data-status="stuck"] i::after { background: #f5ca7e; }
.ty-person[data-key="pip"] i { background: #845137; } .ty-person[data-key="nyx"] i { background: #665877; }
.ty-person[data-key="rook"] i { background: #566266; } .ty-person[data-key="mote"] i { background: #456c60; }
.ty-person[data-key="jet"] i { background: #827039; }
.ty-person { border-left: 3px solid var(--ty-department, #8ebfab); }
.ty-person i { background: color-mix(in srgb, var(--ty-department, #8ebfab) 38%, #183034) !important; }
.ty-person b, .ty-person small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ty-person > span { min-width: 0; } .ty-person b { font-size: 11px; line-height: 1.3; } .ty-person small { font-size: 9px; color: #b7c7b8; line-height: 1.25; }
.ty-person .ty-scope { font-size: 7px; letter-spacing: .04em; color: #d5d6c6; margin-top: 1px; }
#ty-event { border: 0; border-top: 1px solid var(--ty-edge); display: grid; grid-template-columns: 1fr auto; gap: 3px 8px;
  width: 100%; min-height: 44px; padding: 7px 0 0; margin-top: 7px; background: none; color: #dfe8da; text-align: left; cursor: pointer; font: inherit; }
#ty-event .ty-eyebrow { grid-column: 1; } #ty-event-text { grid-row: 2; grid-column: 1; font-size: 10.5px; line-height: 1.25;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; } #ty-event-age { grid-column: 2; grid-row: 1 / 3; align-self: center; font-size: 9px; color: #a9b9ac; }
#ty-header button:focus-visible, #ty-dock button:focus-visible, .ty-marker:focus-visible { outline: 2px solid #f3d287; outline-offset: 2px; }
body.tycoon #ty-markers { display: block; position: fixed; inset: 0; pointer-events: none; z-index: 5; }
.ty-marker { position: absolute; top: 0; left: 0; min-height: 44px; min-width: 44px; pointer-events: auto; padding: 4px 7px;
  background: rgba(21,33,34,.9); color: #fff3d7; border: 1px solid rgba(243,224,170,.5); border-radius: 9px; box-shadow: 0 3px 9px rgba(0,0,0,.25);
  font: inherit; font-size: 10px; font-weight: 750; cursor: pointer; }
.ty-marker small { display: block; color: #d5dcc9; font-size: 8px; font-weight: 400; margin-top: 2px; }
.ty-marker[hidden] { display: none; }
body.tycoon #cine, body.tycoon #tags, body.tycoon #intro, body.tycoon #details, body.tycoon #bar,
body.tycoon #honest, body.tycoon #postcard { display: none !important; }
body.tycoon #vignette { background: radial-gradient(ellipse at 50% 48%, transparent 60%, rgba(9,21,24,.18) 100%); }
body.tycoon #panel { top: calc(16px + env(safe-area-inset-top)); bottom: auto; max-height: calc(100% - 40px - env(safe-area-inset-top) - env(safe-area-inset-bottom));
  z-index: 20; border-radius: 16px; background: #16262a; }
body.tycoon #panel-close { min-height: 44px; min-width: 44px; }
.ty-position { padding: 10px 0; border-top: 1px solid rgba(200,219,192,.18); }
.ty-position p { margin: 4px 0; } .ty-position small { color: #bbc9bd; }
.ty-flow-card { padding: 12px; margin-top: 12px; border: 1px solid rgba(200,219,192,.2); border-left: 4px solid #9acbae; border-radius: 10px; }
.ty-flow-card h3 { margin: 0 0 8px; font-size: 16px; } .ty-flow-card p { margin: 8px 0; }
.ty-flow-card.practice { border-left-color: #bdabdf; }
body:not(.tycoon) #ty-header { display: contents; }
body:not(.tycoon) #ty-header .ty-heading { display: contents; }
body:not(.tycoon) #ty-header .ty-heading > div, body:not(.tycoon) #ty-header #ty-state,
body:not(.tycoon) #ty-header .ty-money, body:not(.tycoon) #ty-header #ty-fresh, body:not(.tycoon) #ty-alert { display: none; }
body:not(.tycoon) #ty-mode { position: fixed; top: calc(65px + env(safe-area-inset-top)); right: 10px; z-index: 10; background: rgba(16,29,31,.95); }
@media (min-width: 760px) {
  body.tycoon #ty-header { left: 50%; right: auto; transform: translateX(-50%); width: 600px; }
  body.tycoon #ty-dock { left: 50%; right: auto; transform: translateX(-50%); width: 620px; }
  #ty-crew { grid-template-columns: repeat(6,minmax(0,1fr)); } .ty-person { gap: 4px; }
  .ty-person i { width: 22px; height: 25px; } .ty-money small { font-size: 10px; } .ty-money span { font-size: 11px; }
}
@media (max-height: 700px) and (max-width: 759px) {
  body.tycoon #ty-header { padding: 6px 8px; } .ty-heading { margin-bottom: 4px; } .ty-heading h1 { font-size: 16px; }
  .ty-money button { padding: 4px 6px; } .ty-money b { font-size: 18px; }
  body.tycoon #ty-dock { padding: 5px 8px; } #ty-doing { min-height: 14px; -webkit-line-clamp: 1; margin: 2px 0 4px; }
  #ty-focus { font-size: 14px; } #ty-event { margin-top: 4px; padding-top: 4px; }
  #ty-crew { display: flex; overflow-x: auto; scroll-snap-type: x proximity; }
  .ty-person { flex: 0 0 calc((100% - 10px) / 3); scroll-snap-align: start; }
}
@media (max-width: 350px) { .ty-heading { gap: 4px; } #ty-mode { padding: 5px 6px; font-size: 10px; }
  #ty-state { font-size: 9px; max-width: 70px; } .ty-money span { font-size: 9px; } .ty-money small { font-size: 7.5px; }
  .ty-person { gap: 4px; padding: 4px; } .ty-person i { width: 20px; font-size: 10px; } .ty-person small { font-size: 8px; } }
"""

TYCOON_UI = r"""
  // ============================================================= TYCOON CONTROLS (read-only)
  const TY_UI = { summary: null, stamp: -1, markers: [], people: [], top: 160, bottom: 250 };
  const tyHeader = el("ty-header"), tyDock = el("ty-dock"), tyCrew = el("ty-crew"), tyMarkers = el("ty-markers");
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
    TY_UI.bottom = window.innerHeight - tyDock.getBoundingClientRect().top + 8;
    tycoonBounds(TY_UI.top, TY_UI.bottom);
    TY_UI.markers.forEach(function (m) { m.w = 0; });
  }
  function tycoonChoose(key) {
    if (!TYCOON.on) tycoonView(true);
    tycoonSelect(key); tycoonDraw();
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
      words.appendChild(name); words.appendChild(job); words.appendChild(scope); b.appendChild(icon); b.appendChild(words); tyCrew.appendChild(b);
      b.onclick = function () { tycoonChoose(key); }; TY_UI.people.push({ key: key, b: b, job: job, scope: scope });
      const m = document.createElement("button"), sub = document.createElement("small");
      m.type = "button"; m.className = "ty-marker"; m.textContent = CAST[key].name; m.appendChild(sub); m.hidden = true;
      m.style.borderColor = colour;
      m.onclick = b.onclick; tyMarkers.appendChild(m);
      const at = LAMP_AT[CAST[key].room].clone(); at.y += 2.2;
      TY_UI.markers.push({ key: key, el: m, sub: sub, at: at, w: 0 });
    }
  }
  function tycoonDraw() {
    const s = tycoonSummary(data, Date.now() / 1000); TY_UI.summary = s;
    const state = offline ? "offline" : s.state;
    const stateWords = { on: "Real bets enabled", off: "New real bets off", paused: "New bets paused", stale: "Data delayed", offline: "Reconnecting", unknown: "No report yet" };
    const status = el("ty-state"); status.className = state; status.textContent = stateWords[state] || "No report yet";
    const alerts = data && Array.isArray(data.alerts) ? data.alerts : [];
    const warning = offline ? statusEl.textContent : alerts.length ? alerts[0].text : "";
    el("ty-alert").hidden = !warning; tyText("ty-alert", warning || "");
    tyText("ty-cash", fmtUsd(s.cash)); tyText("ty-today", fmtSigned(s.today)); tyText("ty-bets", s.count == null ? "—" : s.count);
    el("ty-today").className = s.today > 0 ? "positive" : s.today < 0 ? "negative" : "";
    tyText("ty-held", s.held == null ? "Includes your own" : fmtUsd(s.held) + " committed");
    const oldMoney = [];
    if (s.cashStale) oldMoney.push("Cash checked " + tyAge(s.cashAge));
    else if (s.cash !== null && !s.cashAsOf) oldMoney.push("Cash update time unknown");
    if (s.venueStale) oldMoney.push("Account bets checked " + tyAge(s.venueAge));
    else if (s.count !== null && !s.venueAsOf) oldMoney.push("Account bets update time unknown");
    tyText("ty-fresh", offline ? "Connection lost · showing the last report" : s.stale ? "Last report " + tyAge(s.deskAge) + " · figures may be old"
      : oldMoney.length ? oldMoney.join(" · ") + " · may be old"
      : s.updated ? "Updated " + tyAge(s.pageAge) + " · account bets include your own" : "Waiting for the bot’s report…");
    const chosen = s.crew.find(function (c) { return c.key === TYCOON.selected; }) || (CAST[TYCOON.selected] ? {
      name: CAST[TYCOON.selected].name, job: "Workstation", status: "unknown", doing: "Waiting for a crew report.", age: null, practice: null,
    } : null);
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
      if (c) {
        const job = c.practice ? c.job + " · practice" : c.job;
        if (m.sub.textContent !== job) { m.sub.textContent = job; m.w = 0; }
        m.el.setAttribute("aria-label", "View " + c.name + "’s workstation");
      } else { m.sub.textContent = "No current report"; m.w = 0; }
    }
    tyText("ty-event-text", s.event ? s.event.text : "No recent real settlement reported");
    tyText("ty-event-age", s.event ? tyAge(s.event.age) : "");
    if (panelKind && panelKind.indexOf("ty-") === 0) tycoonPanel();
    tycoonMeasure();
  }
  function tycoonPanel() {
    if (!panelKind || panelKind.indexOf("ty-") !== 0) return false;
    const s = TY_UI.summary || tycoonSummary(data, Date.now() / 1000), scroll = panelEl.scrollTop;
    panelBody.textContent = ""; panelEl.className = "";
    if (panelKind === "ty-alerts") {
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
      para(panelBody, (s.count == null ? "Open count not reported" : s.count + " open bets") + (s.held == null ? "" : " · " + fmtUsd(s.held) + " committed"));
      if (s.pending && s.pending.count) para(panelBody, s.pending.count + " bot orders awaiting confirmation; separate from open bets.", "dim");
      if (!s.positions.length) para(panelBody, s.count === 0 ? "No open real bets reported." : "No individual bet details in this report.", "dim");
      for (const p of s.positions) {
        const row = document.createElement("div"); row.className = "ty-position";
        para(row, p.question); para(row, p.side + (p.price == null ? "" : " · entry " + Math.round(p.price * 100) + "¢"), "dim"); panelBody.appendChild(row);
      }
      if (s.positions.length) para(panelBody, "Reported positions only; the feed may show fewer rows than the total. It does not identify which belong to you.", "dim");
      para(panelBody, s.venueAsOf ? "Account positions checked " + tyAge(s.venueAge) + "." : "Account positions update time not reported.", "dim");
    } else if (panelKind === "ty-result") {
      panelTitle.textContent = "Recent real result";
      para(panelBody, s.event ? s.event.text : "No recent real settlement reported.");
      if (s.event) { para(panelBody, "Recorded " + tyAge(s.event.age) + ".", "dim"); para(panelBody, s.eventNote, "dim"); }
    } else if (panelKind === "ty-today") {
      panelTitle.textContent = "Bot’s result today"; para(panelBody, fmtSigned(s.today));
      para(panelBody, "The bot’s realized profit or loss booked today (UTC), including settlements and cash-outs. Your own bets, deposits and practice money are not counted here.");
      para(panelBody, "Open bets can still win or lose. This number is not a forecast.", "dim");
    } else {
      panelTitle.textContent = "Available account cash"; para(panelBody, fmtUsd(s.cash));
      para(panelBody, "Spendable cash reported by Polymarket for your shared account. It can include deposits and your own activity. It is not the bot’s profit.");
      para(panelBody, s.cashAsOf ? "Cash reported " + tyAge(Math.max(0, Date.now() / 1000 - s.cashAsOf)) + "." : "Cash update time not reported.", "dim");
    }
    const oldAccount = panelKind === "ty-bets" && (s.venueStale || !s.venueAsOf)
      || panelKind === "ty-cash" && (s.cashStale || !s.cashAsOf);
    if (s.stale || offline || oldAccount) para(panelBody, "Showing the last report. Wait for a fresh update before treating these as current figures.", "warn");
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
  el("ty-info").onclick = function () { openPanel("ty-flow"); };
  el("ty-alert").onclick = function () { openPanel("ty-alerts"); };
  el("ty-cash-card").onclick = function () { openPanel("ty-cash"); };
  el("ty-today-card").onclick = function () { openPanel("ty-today"); };
  el("ty-bets-card").onclick = function () { openPanel("ty-bets"); };
  el("ty-event").onclick = function () { openPanel("ty-result"); };
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
