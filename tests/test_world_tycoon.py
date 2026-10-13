"""The town overview stays in charge while existing character programmes keep playing."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from nightcrawler.config import Settings
from nightcrawler.world3d import render_world_html
from nightcrawler.worldtycoon import TYCOON_HTML, TYCOON_STYLE
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
    assert "Polymarket cash" in TYCOON_HTML and "PM bot profit" in TYCOON_HTML
    assert "today PT" in TYCOON_HTML
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


@needs_node
def test_account_freshness_and_service_alerts_survive_fresh_page_updates(module: str, tmp_path: Path) -> None:
    hooks = "\n".join(_js_body(module, f"  function {name}(") for name in
                      ("tyAge", "tyFee", "tyText", "tycoonDraw", "tycoonPanel"))
    out = _node("""
const nodes = {}, el = function (id) { return nodes[id] || (nodes[id] = {
  textContent: "", className: "", setAttribute: function () {} }); };
const document = { createElement: function (tag) { return { tagName: tag.toUpperCase(), textContent: "",
  appendChild: function () {}, setAttribute: function () {} }; } };
const TY_UI = { summary: null, people: [], markers: [] }, TYCOON = { selected: null }, CAST = {};
let data = {}, offline = false;
const statusEl = { textContent: "" };
const fmtUsd = function (n) { return n === null ? "—" : "$" + n.toFixed(2); };
const fmtSigned = fmtUsd, tycoonMeasure = function () {}, tycoonParkApply = function () {};
let panelKind = null, paragraphs = [];
const panelBody = { textContent: "", appendChild: function () {} };
const panelEl = { scrollTop: 140, className: "" }, panelTitle = { textContent: "" };
const para = function (parent, text, cls) { paragraphs.push({ text: text, cls: cls || "" }); };
const current = { state: "on", cash: 12, today: 0.25, count: 2, value: 3, crew: [], positions: [], pending: null,
  event: null, stale: false, updated: 1000000, pageAge: 1, deskAge: 2,
  cashAsOf: 999999, cashAge: 1, cashStale: false, venueAsOf: 999999, venueAge: 1, venueStale: false };
let sample = current;
const tycoonSummary = function () { return sample; };
""" + hooks + """
const show = function (change, kind) {
  sample = Object.assign({}, current, change); panelKind = null; tycoonDraw();
  const fresh = el("ty-fresh").textContent;
  panelKind = kind; paragraphs = []; tycoonPanel();
  return { fresh: fresh, warnings: paragraphs.filter(function (p) { return p.cls === "warn"; }).length,
    warningMessages: paragraphs.filter(function (p) { return p.cls === "warn"; }).map(function (p) { return p.text; }),
    scroll: panelEl.scrollTop, cash: el("ty-cash").textContent,
    state: el("ty-state").textContent, alert: el("ty-alert").textContent, hidden: el("ty-alert").hidden,
    messages: paragraphs.map(function (p) { return p.text; }) };
};
const reports = { fresh: show({}, "ty-bets"),
  venue: show({ venueAge: 900, venueStale: true }, "ty-bets"),
  cash: show({ cashAge: 7200, cashStale: true }, "ty-cash"),
  unknownVenue: show({ venueAsOf: null }, "ty-bets"), unknownCash: show({ cashAsOf: null }, "ty-cash") };
reports.accountCashOld = show({ cashAge: 7200, cashStale: true }, "ty-accounts");
reports.accountVenueOld = show({ venueAge: 900, venueStale: true }, "ty-accounts");
reports.accountCashUnknown = show({ cashAsOf: null }, "ty-accounts");
const kalshi = { state: "live", stateText: "Real-money trading is enabled", active: true, practice: false,
  cash: 25, exposure: 1.98, today: -0.34, reason: "", stale: false, cashAt: 999998, cashAge: 2,
  cashStale: false, todayStale: false, cleanupPending: false };
const account = function (change) {
  return show({ accounts: { kalshi: Object.assign({}, kalshi, change) } }, "ty-accounts");
};
reports.kalshiFresh = account({});
reports.kalshiCashOld = account({ cashAge: 120, cashStale: true });
reports.kalshiTodayUnknown = account({ today: null, todayStale: true });
reports.kalshiCashUnknown = account({ cash: null, cashAt: null, cashAge: null, cashStale: true });
reports.kalshiCleanup = account({ state: "exposure", active: false, practice: false,
  stateText: "Real bets remain open", cleanupPending: true });
reports.kalshiPractice = account({ state: "practice", active: false, practice: true, exposure: 0 });
reports.kalshiStale = account({ state: "stale", active: false, practice: false, stale: true,
  stateText: "Waiting for a fresh Kalshi report" });
reports.pmBuysOff = show({ state: "off" }, "ty-bets");
data = { alerts: [{ text: "The bot is stopped." }, { text: "Polymarket orders need attention." }] };
reports.alerted = show({}, "ty-alerts");
reports.refreshed = show({ updated: 1001000, pageAge: 0, deskAge: 0 }, "ty-alerts");
offline = true; statusEl.textContent = "Sign in again to reconnect to the dashboard.";
reports.disconnected = show({}, "ty-alerts");
offline = false; data = { alerts: [] };
reports.cleared = show({}, "ty-alerts");
console.log(JSON.stringify(reports));
""", tmp_path)
    assert out["fresh"]["warnings"] == 0 and "Cash checked <1m ago" in out["fresh"]["fresh"]
    assert "Account bets checked 15m ago" in out["venue"]["fresh"]
    assert "Cash checked 2h ago" in out["cash"]["fresh"]
    assert "Account bets update time unknown" in out["unknownVenue"]["fresh"]
    assert "Cash update time unknown" in out["unknownCash"]["fresh"]
    for name in ("venue", "cash", "unknownVenue", "unknownCash"):
        assert out[name]["warnings"] == 1
        assert out[name]["scroll"] == 140
        assert out[name]["cash"] == "$12.00"
    for name in ("accountCashOld", "accountVenueOld", "accountCashUnknown"):
        assert out[name]["warnings"] == 1
        assert "Wait for a fresh update" in out[name]["warningMessages"][0]
    assert out["kalshiFresh"]["warnings"] == 0
    assert "Available cash: $12.00" in out["kalshiFresh"]["messages"]
    assert "REAL MONEY (Kalshi) · cash $25.00" in out["kalshiFresh"]["messages"]
    assert "Money at risk: $1.98 · today (UTC): $-0.34" in out["kalshiFresh"]["messages"]
    assert "Accounts stay separate. Kalshi’s UTC day is not added to Polymarket’s Pacific day." in out["kalshiFresh"]["messages"]
    assert out["kalshiCashOld"]["warnings"] == 1
    assert "Kalshi cash checked 2m ago." in out["kalshiCashOld"]["messages"]
    assert out["kalshiCashOld"]["warningMessages"] == ["Kalshi cash may be old; waiting for a fresh balance read."]
    assert out["kalshiTodayUnknown"]["warningMessages"] == ["Kalshi’s UTC-day result is delayed or unavailable."]
    assert "Money at risk: $1.98 · today (UTC): —" in out["kalshiTodayUnknown"]["messages"]
    assert "Kalshi cash update time is unknown." in out["kalshiCashUnknown"]["messages"]
    assert "REAL MONEY (Kalshi) · cash —" in out["kalshiCashUnknown"]["messages"]
    assert out["kalshiCleanup"]["warningMessages"] == ["Resting-order cancellation and reconciliation are still pending."]
    assert "Real bets remain open · cash $25.00" in out["kalshiCleanup"]["messages"]
    assert not any("PRACTICE (Kalshi)" in text for text in out["kalshiCleanup"]["messages"])
    assert "PRACTICE (Kalshi) · cash $25.00" in out["kalshiPractice"]["messages"]
    assert out["kalshiStale"]["warningMessages"] == ["Kalshi’s report is delayed or missing. These figures may be old."]
    assert not any("REAL MONEY (Kalshi)" in text for text in out["kalshiStale"]["messages"])
    assert out["pmBuysOff"]["state"] == "PM buys off"
    for name in ("alerted", "refreshed"):
        assert out[name]["state"] == "PM live"
        assert out[name]["hidden"] is False and out[name]["alert"] == "The bot is stopped."
        assert "Cash checked <1m ago" in out[name]["fresh"]
        assert "The bot is stopped." in out[name]["messages"]
        assert "Polymarket orders need attention." in out[name]["messages"]
        assert any("reports the Polymarket money setting" in text for text in out[name]["messages"])
    assert out["disconnected"]["state"] == "Reconnecting"
    assert out["disconnected"]["hidden"] is False
    assert out["disconnected"]["alert"] == "Sign in again to reconnect to the dashboard."
    assert out["disconnected"]["alert"] in out["disconnected"]["messages"]
    assert "The bot is stopped." in out["disconnected"]["messages"]
    assert out["cleared"]["hidden"] is True and out["cleared"]["alert"] == ""
    assert "No current alerts reported." in out["cleared"]["messages"]


@needs_node
def test_money_panel_explains_restricted_real_orders_and_unverified_profit(module: str, tmp_path: Path) -> None:
    from nightcrawler.worldtycoon_data import TYCOON_DATA

    value = connected()
    value["money"]["speeddesk"]["kalshi_live"].update(lock_only=True, total_halted=True,
        caps={"window_usd": 2, "open_usd": 4, "day_stop_usd": 3, "total_stop_usd": 5})
    value["money"]["polymarket"]["real"]["today_pacific"].update(
        status="incomplete", reason="day_book_mismatch", pnl_usd=None)
    hooks = "\n".join(_js_body(module, f"  function {name}(") for name in
                      ("tyAge", "tyFee", "tycoonBusinessDetails", "tycoonPanel"))
    out = _node(TYCOON_DATA + "\nconst data = " + json.dumps(value) + ";\n" + f"const now = {NOW};\n" + """
const document = { createElement: function () { return { textContent: "", appendChild: function () {} }; } };
const TY_UI = { summary: tycoonSummary(data, now) }, offline = false;
const panelBody = { textContent: "", appendChild: function () {} };
const panelEl = { scrollTop: 0, className: "" }, panelTitle = { textContent: "" };
const panelKind = "ty-accounts", paragraphs = [];
const para = function (parent, text, cls) { paragraphs.push({ text: text, cls: cls || "" }); };
const fmtUsd = function (n) { return n === null ? "—" : "$" + n.toFixed(2); }, fmtSigned = fmtUsd;
""" + hooks + """
tycoonPanel(); console.log(JSON.stringify(paragraphs));
""", tmp_path)
    messages = [row["text"] for row in out]
    assert "REAL MONEY (Kalshi) · cash $25.00" in messages
    assert "Real money: completing existing pairs only; new bets are stopped" in messages
    assert "New-bet limits: $2.00 per window · $4.00 at risk · $3.00 daily loss stop · $5.00 total loss stop (UTC)." in messages
    assert any("pair-completion reservations do not" in text for text in messages)
    assert any("may exceed these budgets or loss stops" in text for text in messages)
    assert any("saved result totals do not match the daily book" in text for text in messages)
    assert any("Account reconciliation time is not recorded" in text for text in messages)
    assert any(text.startswith("Saved checkpoint ") for text in messages)
    assert not any("New real buys remain off" in text or "Included in money at risk" in text for text in messages)
