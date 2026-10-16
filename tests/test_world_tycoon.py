"""The town overview stays in charge while existing character programmes keep playing."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from nightcrawler.config import Settings
from nightcrawler.world3d import render_world_html
from nightcrawler.worldtycoon import TYCOON_HTML, TYCOON_STYLE
from nightcrawler.worldtycoon_data import TYCOON_DATA
from tests.test_world3d import _js_body, _module, _node
from tests.test_world_records import _film
from tests.test_world_tycoon_connections import connected
from tests.test_world_tycoon_data import NOW

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


@pytest.fixture(scope="module")
def page() -> str:
    return render_world_html(Settings.from_env({"DATA_DIR": "/tmp/nightcrawler-tycoon-integration"}))


@pytest.fixture(scope="module")
def module(page: str) -> str:
    return _module(page)


def test_town_is_ready_before_the_first_frame_and_keeps_one_shared_details_panel(page: str, module: str) -> None:
    assert re.search(r'<body [^>]*class="cinema tycoon">', page)
    assert page.count('id="panel"') == 1
    assert page.count('id="ty-header"') == 1
    assert page.count('id="ty-dock"') == 1
    assert "Kalshi cash" in TYCOON_HTML and "Kalshi bot profit" in TYCOON_HTML
    assert "Polymarket" not in TYCOON_HTML
    assert "Since midnight Pacific" in TYCOON_HTML
    assert 'id="ty-more"' in TYCOON_HTML
    assert 'id="ty-crew"' not in TYCOON_HTML
    assert 'id="ty-selection" aria-label="Selected workstation" hidden' in TYCOON_HTML
    assert 'id="ty-alert" aria-controls="panel" hidden' in TYCOON_HTML
    assert 'el("ty-alert").onclick = function () { openPanel("ty-alerts"); };' in module
    assert module.index("tycoonBuildCrew(); tycoonView();") < module.index('resize(); BUS.emit("start", 0, 0);')
    # Returning viewers must not regain the old automatic tour merely because they saved a details preference.
    assert module.index("cineSet(true, false);") < module.index("tycoonBuildCrew(); tycoonView();")
    for hidden in ("#cine", "#tags", "#intro", "#details", "#bar"):
        assert f"body.tycoon {hidden}" in TYCOON_STYLE
    assert "min-height: 44px" in TYCOON_STYLE


@needs_node
def test_overview_keeps_six_colliding_station_labels_reachable_without_shrinking_tap_boxes(
    module: str, tmp_path: Path,
) -> None:
    place = _js_body(module, "  function tycoonMarkerPlace(")
    out = _node(place + """
// Measured phone projection: Nyx is only 28px below Voss and previously vanished.
const anchors = [[197,412],[203,356],[243,440],[145,460],[111,368],[258,530]];
const run = function (width) {
  const occupied = [];
  const points = width === 320 ? [[161,301],[166,258],[197,322],[121,338],[96,267],[209,393]] : anchors;
  for (const p of points) {
    const row = tycoonMarkerPlace({ok:true,x:p[0],y:p[1]},72,44,width,181,width===320?488:760,occupied);
    if (row) occupied.push(row);
  }
  return occupied;
};
console.log(JSON.stringify({phone:run(390),small:run(320),again:run(390)}));
""", tmp_path)
    assert out["phone"] == out["again"]
    for key, width in (("phone", 390), ("small", 320)):
        rows = out[key]
        bottom = 488 if width == 320 else 760
        assert len(rows) == 6
        for index, row in enumerate(rows):
            assert row["w"] >= 44 and row["h"] >= 44
            assert 5 <= row["x"] <= width - row["w"] - 5
            assert 181 < row["y"] < row["y"] + row["h"] < bottom
            for other in rows[:index]:
                assert (row["x"] >= other["x"] + other["w"] + 3
                        or row["x"] + row["w"] + 3 <= other["x"]
                        or row["y"] >= other["y"] + other["h"] + 3
                        or row["y"] + row["h"] + 3 <= other["y"])


@needs_node
def test_marker_offsets_never_rescue_offscreen_stations_or_cover_the_hud(module: str, tmp_path: Path) -> None:
    place = _js_body(module, "  function tycoonMarkerPlace(")
    out = _node(place + """
const missing = [ {ok:false,x:200,y:400}, {ok:true,x:-1,y:400}, {ok:true,x:391,y:400},
  {ok:true,x:200,y:180}, {ok:true,x:200,y:761} ].map(p=>tycoonMarkerPlace(p,72,44,390,181,760,[]));
const blocked=tycoonMarkerPlace({ok:true,x:200,y:400},72,44,390,181,760,[{x:0,y:181,w:390,h:579}]);
console.log(JSON.stringify({missing,blocked}));
""", tmp_path)
    assert out["missing"] == [None] * 5 and out["blocked"] is None


@needs_node
def test_automatic_director_intro_and_arena_tour_wait_behind_town_mode(module: str, tmp_path: Path) -> None:
    # Deliberately omit director/intro dependencies: a town frame must return before touching them.
    hooks = "\n".join(_js_body(module, f"  function {name}(") for name in
                      ("liveDirector", "cineIntroOpen", "townCinema"))
    out = _node("""
const tycoonActive = function () { return true; };
""" + hooks + """
liveDirector(); cineIntroOpen(true);
console.log(JSON.stringify({ arenaTour: townCinema() }));
""", tmp_path)
    assert out == {"arenaTour": False}


@needs_node
def test_town_programmes_finish_without_taking_the_camera_or_closing_details(module: str, tmp_path: Path) -> None:
    out = _node(_film(module) + """
tycoonMode = true; pinned = "nyx"; panelKind = "ty-bets";
const script = [filmBeat(0, "view:riskwall", 1, "GOAL", "1 of 2", "Rook", "First real beat"),
                filmBeat(1, "voss", 1, "GOAL", "2 of 2", "Voss", "Second real beat")];
progStart("goal", script, false);
run(2);
const reading = { open: panelKind, panelCloses: panelCloses, guideCloses: guideCloses,
  playing: FILM.on, paused: FILM.paused, beat: FILM.i };
panelKind = null; untilShown();
const first = shot(); run(1.1); untilShown(); const second = shot(); run(2);
console.log(JSON.stringify({ reading: reading, first: first.text, second: second.text,
  finished: !FILM.on, pinned: pinned, pins: pins, views: views, wentLive: wentLive }));
""", tmp_path)
    assert out["reading"] == {"open": "ty-bets", "panelCloses": 0, "guideCloses": 0,
                              "playing": True, "paused": True, "beat": 0}
    assert [out["first"], out["second"]] == ["First real beat", "Second real beat"]
    assert out["finished"] is True
    assert out["pinned"] == "nyx" and out["pins"] == [] and out["views"] == [] and out["wentLive"] == 0


@needs_node
def test_real_settlement_still_gathers_the_crew_without_moving_town_camera(module: str, tmp_path: Path) -> None:
    goal_play = _js_body(module, "  function goalPlay(")
    out = _node(_film(module) + """
tycoonMode = true; pinned = "rook";
let gathered = 0;
const GOAL = { pending: { kind: "huddle" } };
const heartsGather = function () { gathered += 1; };
const goalBeatScript = function () { return [filmBeat(0, "view:goaltower", 1, "REAL", "", "Crew", "A real bet settled")]; };
""" + goal_play + """
goalPlay({ kind: "huddle" }); untilShown(); const words = shot().text; run(2);
console.log(JSON.stringify({ gathered: gathered, pending: GOAL.pending, words: words,
  done: !FILM.on, pinned: pinned, pins: pins, views: views }));
""", tmp_path)
    assert out == {"gathered": 1, "pending": None, "words": "A real bet settled", "done": True,
                   "pinned": "rook", "pins": [], "views": []}


@needs_node
def test_town_cannot_switch_back_to_legacy_ui_or_expose_practice_money(
    module: str, tmp_path: Path,
) -> None:
    hooks = "\n".join(_js_body(module, f"  function {name}(") for name in
                      ("cineBoards", "cineSet", "tycoonView"))
    out = _node("""
const classes = new Set(["cinema", "tycoon"]);
const body = { classList: { toggle: function (key, on) { if (on) classes.add(key); else classes.delete(key); } } };
const TP = { labels: { visible: true }, plates: { visible: true } };
let practiceLayer = true, realOnly = false, wentLive = 0;
const camera = { layers: { disable: function (n) { if (n === 1) practiceLayer = false; },
                          enable: function (n) { if (n === 1) practiceLayer = true; } } };
const CINE_DARK = {}, CINE_BOARDS = [];
const recRealOnly = function (on) { realOnly = on; };
const CINE = { on: false }, FILM = { on: false }, data = null;
const cineDetails = { textContent: "", setAttribute: function () {} };
const cineCapEl = { classList: { remove: function () {} } };
const mode = { textContent: "" }, el = function () { return mode; };
const cineVaultDraw = function () {}, closePanel = function () {}, closeGuide = function () {};
const cineMeasure = function () {}, measureBar = function () {}, renderCard = function () {};
const cineIntroClose = function () {}, filmStop = function () {};
const tycoonMeasure = function () {}, tycoonDraw = function () {};
const tycoonCutaway = function () {}, tycoonPark = function () {};
const tycoonEnable = function (on) { body.classList.toggle("tycoon", on); };
const goLive = function () { wentLive += 1; };
""" + hooks + """
const snapshot = function () { return { town: classes.has("tycoon"), cinema: classes.has("cinema"),
  labels: TP.labels.visible, plates: TP.plates.visible, practiceLayer: practiceLayer,
  realOnly: realOnly, button: mode.textContent, wentLive: wentLive }; };
tycoonView(true); const town = snapshot();
tycoonView(false); const tour = snapshot();
tycoonView(true); const returned = snapshot();
console.log(JSON.stringify({ town: town, tour: tour, returned: returned }));
""", tmp_path)
    assert out["town"] == {"town": True, "cinema": True, "labels": False, "plates": False,
                           "practiceLayer": False, "realOnly": True, "button": "", "wentLive": 0}
    assert out["tour"] == out["town"]
    assert out["returned"] == out["town"]


_UI_STUB = r"""
class Node {
  constructor(tag="div") { this.tagName=tag.toUpperCase(); this.children=[]; this.own=""; this.className="";
    this.dataset={}; this.attributes={}; this.hidden=false; this.open=false; this.scrollTop=140; }
  set textContent(text) { this.own=String(text); this.children=[]; }
  get textContent() { return this.own+this.children.map(n=>n.textContent).join(""); }
  appendChild(child) { if(child.parentElement) child.parentElement.removeChild(child);
    child.parentElement=this; this.children.push(child); return child; }
  removeChild(child) { if(document.activeElement && child.contains(document.activeElement))document.activeElement=null;
    const index=this.children.indexOf(child);if(index>=0)this.children.splice(index,1);
    child.parentElement=null;return child; }
  insertBefore(child,reference) { if(child.parentElement)child.parentElement.removeChild(child);
    const index=reference?this.children.indexOf(reference):this.children.length;
    child.parentElement=this;this.children.splice(index,0,child);return child; }
  setAttribute(key,value) { this.attributes[key]=value; }
  contains(node) { return this===node || this.children.some(c=>c.contains(node)); }
  querySelectorAll(selector) { const all=this.children.flatMap(c=>[c,...c.querySelectorAll("*")]);
    return all.filter(c=>selector==="*" || (selector[0]==="." ? c.className.split(" ").includes(selector.slice(1))
      : c.tagName.toLowerCase()===selector)); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  focus() { document.activeElement=this; }
  get classList() { return { contains: value=>this.className.split(" ").includes(value) }; }
}
const document={activeElement:null,createElement:tag=>new Node(tag)}, nodes={};
const el=id=>nodes[id] || (nodes[id]=new Node());
const TY_UI={summary:null,people:[],markers:[],openDetails:{}}, TYCOON={selected:null}, CAST={};
let offline=false, panelKind=null, paragraphs=[];
const statusEl={textContent:"Sign in again to reconnect to the dashboard."};
const fmtUsd=n=>n==null?"—":"$"+n.toFixed(2), fmtSigned=fmtUsd;
const tycoonMeasure=()=>{},tycoonParkApply=()=>{},tycoonWorkApply=()=>{};
const panelBody=new Node(),panelEl=new Node(),panelTitle=new Node();
const para=(parent,text,cls)=>{ const n=new Node("p");n.textContent=text;n.className=cls||"";parent.appendChild(n);
  paragraphs.push({text,cls:cls||""}); };
const openPanel=kind=>{panelKind=kind;tycoonPanel();};
Date.now=()=>now*1000;
function draw(kind="ty-accounts") {
  panelKind=null;tycoonDraw();panelKind=kind;paragraphs=[];tycoonPanel();
  return {cash:el("ty-cash").textContent,today:el("ty-today").textContent,state:el("ty-state").textContent,
    fresh:el("ty-fresh").textContent,exposure:el("ty-exposure").textContent,alert:el("ty-alert").textContent,
    alertHidden:el("ty-alert").hidden,growth:el("ty-growth").textContent,scroll:panelEl.scrollTop,
    messages:panelBody.querySelectorAll("p").map(p=>p.textContent),
    warnings:panelBody.querySelectorAll("p").filter(p=>p.className==="warn").map(p=>p.textContent),
    details:panelBody.querySelectorAll("details").map(d=>({title:d.querySelector("summary").textContent,
      open:d.open,text:d.textContent})),direct:panelBody.children.filter(n=>n.tagName!=="DETAILS").map(n=>n.textContent),
    menu:panelBody.querySelectorAll(".ty-menu-row").map(n=>n.textContent)};
}
"""


def run_ui(module: str, tmp_path: Path, code: str, value: dict[str, Any] | None = None) -> Any:
    hooks = "\n".join(_js_body(module, f"  function {name}(") for name in (
        "tyAge", "tyFee", "tyText", "tycoonNowDoing", "tycoonDraw", "tycoonFocusWarning", "tycoonDetails", "tycoonBusinessDetails",
        "tycoonResearchDetails", "tycoonOtherAlerts", "tycoonPanelMerge", "tycoonPanel",
    ))
    return _node(TYCOON_DATA + "\nconst data=" + json.dumps(value if value is not None else connected())
                 + f";const now={NOW};\n" + _UI_STUB + hooks + code, tmp_path)


@needs_node
def test_kalshi_hud_is_independent_of_polymarket_cash_profit_and_alerts(module: str, tmp_path: Path) -> None:
    out = run_ui(module, tmp_path, r"""
const reports={fresh:draw()};
data.money.polymarket.mode="paper";
data.money.polymarket.real.cash_usd=123456;
data.money.polymarket.real.today_pacific.pnl_usd=999;
data.money.connections.polymarket_us.stale=true;
data.alerts=[{text:"Polymarket orders need attention."},{text:"Coin practice stopped."}];
reports.otherDeskChanged=draw();
data.money.speeddesk.kalshi_live.cash_at=now-120;
reports.cashOld=draw();
data.money.speeddesk.kalshi_live.as_of=now-120;
reports.kalshiOld=draw();
offline=true;reports.offline=draw("ty-alerts");
console.log(JSON.stringify(reports));
""")
    assert out["fresh"]["cash"] == "$25.00" and out["fresh"]["today"] == "$0.10"
    assert out["fresh"]["state"] == "REAL MONEY · Kalshi"
    assert out["fresh"]["alertHidden"] is True
    assert "Kalshi" in out["fresh"]["growth"]
    assert out["otherDeskChanged"]["cash"] == "$25.00" and out["otherDeskChanged"]["today"] == "$0.10"
    assert out["otherDeskChanged"]["state"] == out["fresh"]["state"]
    assert out["otherDeskChanged"]["alertHidden"] is True
    assert "Polymarket orders need attention." in out["otherDeskChanged"]["messages"]
    assert any(d["title"] == "Other service notices (2)" and not d["open"]
               for d in out["otherDeskChanged"]["details"])
    assert "Cash checked 2m ago" in out["cashOld"]["fresh"]
    assert out["cashOld"]["alert"] == "Kalshi cash needs a fresh balance read."
    assert out["kalshiOld"]["state"] == "Kalshi · data delayed"
    assert "fresh Kalshi" in out["kalshiOld"]["alert"]
    assert out["offline"]["state"] == "Reconnecting"
    assert out["offline"]["alert"] == "Sign in again to reconnect to the dashboard."
    assert "Kalshi account" in out["offline"]["messages"][1] or "Kalshi" in out["offline"]["messages"][1]
    assert all(row["scroll"] == 140 for row in out.values())


@needs_node
def test_money_details_keep_polymarket_real_and_background_practice_separate(module: str, tmp_path: Path) -> None:
    out = run_ui(module, tmp_path, r"""
const money=draw();
const menu=draw("ty-menu");
console.log(JSON.stringify({money,menu}));
""")
    money = out["money"]
    assert money["direct"][0] == "REAL MONEY (Kalshi) · cash $25.00"
    assert all("Polymarket" not in text and "$14.22" not in text for text in money["direct"])
    pm = next(d for d in money["details"] if d["title"].startswith("Polymarket ·"))
    assert pm["title"] == "Polymarket · REAL MONEY · separate account"
    assert pm["open"] is False and "Available cash: $14.22" in pm["text"]
    assert "not practice when real money is on" in pm["text"]
    labs = next(d for d in money["details"] if d["title"] == "Background practice and research")
    assert labs["open"] is False and "PRACTICE" in labs["text"]
    assert out["menu"]["menu"] == ["Money", "Team", "Help"]


@needs_node
def test_missing_kalshi_never_falls_back_to_other_account_or_practice_cash(module: str, tmp_path: Path) -> None:
    value = connected()
    value["money"].pop("speeddesk")
    value["money"]["connections"].pop("kalshi")
    out = run_ui(module, tmp_path, "console.log(JSON.stringify(draw()));", value)
    assert out["cash"] == "—" and out["today"] == "—"
    assert out["state"] == "Kalshi · waiting for report"
    assert "Waiting for a fresh Kalshi" in out["alert"]
    assert "Practice stays separate" in out["growth"]
    assert not any("REAL MONEY (Kalshi)" in text for text in out["direct"])


@needs_node
def test_kalshi_paper_with_real_positions_is_not_labelled_as_zero_exposure(module: str, tmp_path: Path) -> None:
    out = run_ui(module, tmp_path, r"""
Object.assign(data.money.speeddesk.kalshi_live,{mode:"paper",active:false,real_orders_available:false,
  has_real_exposure:true,positions:2,at_risk_usd:1.98});
const exposed=draw();
Object.assign(data.money.speeddesk.kalshi_live,{has_real_exposure:false,positions:0,at_risk_usd:0});
const paper=draw();
console.log(JSON.stringify({exposed,paper}));
""")
    assert out["exposed"]["state"] == "Kalshi · real bets remain"
    assert "2 positions" in out["exposed"]["exposure"] and "$1.98 bot risk" in out["exposed"]["exposure"]
    assert out["paper"]["state"] == "PRACTICE · Kalshi"
    assert "0 positions" in out["paper"]["exposure"]


@needs_node
def test_expanded_receipts_stay_open_across_live_refreshes(module: str, tmp_path: Path) -> None:
    out = run_ui(module, tmp_path, r"""
draw();
const receipts=panelBody.querySelectorAll("details")[0];
receipts.open=true;receipts.ontoggle();receipts.querySelector("summary").focus();
const before=TY_UI.openDetails["kalshi-receipts"];
const after=draw();
console.log(JSON.stringify({before,after,focus:document.activeElement.parentElement.dataset.detailKey}));
""")
    assert out["before"] is True
    assert out["focus"] == "kalshi-receipts"
    receipts = next(d for d in out["after"]["details"] if d["title"] == "Kalshi orders, positions and receipts")
    assert receipts["open"] is True
    assert next(d for d in out["after"]["details"] if d["title"].startswith("Polymarket ·"))["open"] is False


@needs_node
def test_money_panel_explains_restricted_real_orders_and_unverified_profit(module: str, tmp_path: Path) -> None:
    value = connected()
    value["money"]["speeddesk"]["kalshi_live"].update(lock_only=True, total_halted=True,
        caps={"window_usd": 2, "open_usd": 4, "day_stop_usd": 3, "total_stop_usd": 5})
    value["money"]["polymarket"]["real"]["today_pacific"].update(
        status="incomplete", reason="day_book_mismatch", pnl_usd=None)
    out = run_ui(module, tmp_path, "console.log(JSON.stringify(draw()));", value)
    messages = out["messages"]
    assert "REAL MONEY (Kalshi) · cash $25.00" in messages
    assert "Real money: completing existing pairs only; new bets are stopped" in messages
    assert "New-bet limits: $2.00 per window · $4.00 at risk · $3.00 daily loss stop · $5.00 lifetime loss stop." in messages
    assert any("pair-completion reservations do not" in text for text in messages)
    assert any("may exceed these budgets or loss stops" in text for text in messages)
    assert any("saved result totals do not match the daily book" in text for text in messages)
    assert any("Account reconciliation time is not recorded" in text for text in messages)
    assert any(text.startswith("Saved checkpoint ") for text in messages)
    assert out["state"] == "REAL MONEY · completing pairs"
    assert not any("New real buys remain off" in text or "Included in money at risk" in text for text in messages)


@needs_node
def test_background_markers_are_quiet_without_changing_reported_work_or_money_mode(
    module: str, tmp_path: Path,
) -> None:
    out = run_ui(module, tmp_path, r"""
const original=tycoonSummary;
const crew=["voss","pip","nyx","rook","mote","jet"].map(key=>({key,name:key[0].toUpperCase()+key.slice(1),
  job:"Workstation",status:"working",background:["pip","nyx"].includes(key),practice:key==="pip"?true:null}));
tycoonSummary=(value,time)=>Object.assign(original(value,time),{crew});
TY_UI.markers=crew.map(c=>({key:c.key,el:new Node("button"),label:new Node("b"),sub:new Node("small"),w:80}));
draw();
const read=()=>TY_UI.markers.map(m=>({key:m.key,label:m.label.textContent,status:m.el.dataset.status,
  background:m.el.dataset.background,width:m.w}));
const first=read();crew.find(c=>c.key==="pip").practice=false;draw();
console.log(JSON.stringify({first,second:read()}));
""")
    first = {row["key"]: row for row in out["first"]}
    assert len(first) == 6
    assert first["pip"]["label"] == "Research · practice"
    assert first["nyx"]["label"] == "Lab · background"
    assert first["voss"]["label"] == "Observe"
    assert first["pip"]["background"] == first["nyx"]["background"] == "true"
    assert first["voss"]["background"] == "false"
    assert all(row["status"] == "working" for row in out["first"])
    assert next(row for row in out["second"] if row["key"] == "pip")["label"] == "Research · background"
    assert '.ty-marker[data-background="true"] b::before { background: #91a4ab; }' in TYCOON_STYLE


@needs_node
def test_live_panel_keeps_tappable_nodes_until_displayed_data_or_freshness_changes(
    module: str, tmp_path: Path,
) -> None:
    out = run_ui(module, tmp_path, r"""
draw();
const first=panelBody.children[0],summary=panelBody.querySelectorAll("details")[0].querySelector("summary");
Date.now=()=>(now+1)*1000;draw();
const stable=first===panelBody.children[0] && summary===panelBody.querySelectorAll("details")[0].querySelector("summary");
const labelsBefore=panelBody.textContent;
data.money.speeddesk.kalshi_live.cash_usd=24.50;draw();
const changed=panelBody.textContent!==labelsBefore;
const stayedAttached=summary===panelBody.querySelectorAll("details")[0].querySelector("summary");
const changedNode=panelBody.children[0];
Date.now=()=>(now+61)*1000;
const old=draw();
const stale=old.cash==="—" && old.state==="Kalshi · data delayed"
  && panelBody.textContent.includes("Kalshi’s report is delayed or missing");
const staleNode=panelBody.children[0];offline=true;draw();
const disconnected=panelBody.textContent.includes("Connection lost. Showing the last report");
// Reopening after another view replaced the contents cannot accidentally reuse the old cache.
const prior=panelBody.children[0];panelBody.textContent="Another panel";draw();
const restored=panelBody.children.length>0 && prior!==panelBody.children[0];
console.log(JSON.stringify({stable,changed,stayedAttached,stale,disconnected,restored}));
""")
    assert out == {"stable": True, "changed": True, "stayedAttached": True,
                   "stale": True, "disconnected": True, "restored": True}


@needs_node
def test_team_button_keeps_keyboard_focus_when_live_report_refreshes(module: str, tmp_path: Path) -> None:
    out = run_ui(module, tmp_path, r"""
const members=tycoonSummary(data,now).crew;
TY_UI.people=members.map(c=>{const b=new Node("button"),job=new Node("small"),scope=new Node("small");
  b.className="ty-person";b.dataset.key=c.key;b.appendChild(job);b.appendChild(scope);
  return {key:c.key,b,job,scope};});
draw("ty-team");
const button=panelBody.querySelectorAll(".ty-person").find(n=>n.dataset.key==="voss");button.focus();
data.money.speeddesk.kalshi_live.cash_usd=24.50;
draw("ty-team");
console.log(JSON.stringify({same:panelBody.querySelectorAll(".ty-person").find(n=>n.dataset.key==="voss")===button,
  focused:document.activeElement===button,allPresent:panelBody.querySelectorAll(".ty-person").length===members.length}));
""")
    assert out == {"same": True, "focused": True, "allPresent": True}
