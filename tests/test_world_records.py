"""The 3D world's record room (world3d's THE RECORD ROOM section): the ledger plaque, the trophy shelf, Rook's risk
wall, the trend and research boards, their camera views, the postcard, yesterday's film and the records tour. Each
board's drawing runs here in Node over a recording canvas, so the tests read exactly the words it would paint and the
colour it paints them in: the data's own words, or the section's fixed copy; real money only where the data says so,
and red only for real money; nothing at all for what is missing (never "undefined" or "NaN"). The film plays a recap
through its beats (each beat's words are the event's own, shown once the drone has arrived), waits for a reader of
the money panel, plays an empty day, hands back to the live director and plays itself at 00:05; the boards' views are
worked out with three.js itself; the postcard burns in the real-money line and never the token or the page's address.
The section never edits the live director: it asks for shots through the director's own pin."""

from __future__ import annotations

import json
import math
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from nightcrawler.config import Settings
from nightcrawler.research_board import research_state
from nightcrawler.world3d import ASSET_DIR, WORLD_CSP, render_world_html
from tests.test_world3d import _js_body, _module, _node

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")

#: a canvas that records what is painted (text, where, its font and colour, and each stroke's colour);
#: measureText: half an em per character
_CANVAS = r"""
const drawn = [], strokes = [];
function makeCtx() {
  return { font: "10px x", fillStyle: "", strokeStyle: "", lineWidth: 1, lineCap: "", textAlign: "", textBaseline: "",
    imageSmoothingQuality: "",
    fillText: function (t, x, y) { drawn.push({ t: String(t), x: x, y: y, font: this.font, fill: this.fillStyle }); },
    measureText: function (t) { const m = /(\d+(?:\.\d+)?)px/.exec(this.font); return { width: String(t).length * (m ? +m[1] : 10) * 0.5 }; },
    createLinearGradient: function () { return { addColorStop: function () {} }; },
    fillRect: function () {}, strokeRect: function () {}, beginPath: function () {}, arc: function () {}, fill: function () {},
    stroke: function () { strokes.push(this.strokeStyle); }, moveTo: function () {}, lineTo: function () {}, drawImage: function () {} };
}
function canvas(w, h) { const ctx = makeCtx(); return { width: w, height: h, getContext: function () { return ctx; } }; }
function board(w, h) { return { visible: true, userData: { canvas: canvas(w, h), tex: { needsUpdate: false } } }; }
function roundRect() {}
const TAU = Math.PI * 2;
const clamp = function (v, a, b) { return Math.min(b, Math.max(a, v)); };
const texts = function () { return drawn.splice(0).map(function (d) { return d.t; }); };
const painted = function () { strokes.length = 0; return drawn.splice(0); };
"""

_DIRECTOR, _LOOP = "= THE LIVE DIRECTOR: an always-on broadcast", "= THE LOOP (paused while the tab is hidden)"
_HELPERS = ("recFit", "recLines", "recWrap", "recWrapFit", "recClauses", "recSized", "recCount", "recEngrave")
#: The colours the section may paint real money in (and nothing else).
_REDS = ("#ff8a80", "#ff6b61", "#ffb3ab", "#b3261e", "#7a1f18", "#cf3129")


def _section(module: str) -> str:
    start = module.index("THE RECORD ROOM (Builder B)")
    return module[start:module.index(_DIRECTOR)]


def _helpers(module: str) -> str:
    """The module's own money words and number test, and the section's constants and text helpers."""
    sec = _section(module)
    base = "\n".join(_js_body(module, f"function {name}(v) {{") for name in ("fmtUsd", "fmtSigned", "isNum"))
    consts = sec[sec.index("  const REC = {"):sec.index("  function recFit(")]
    helpers = "\n".join(_js_body(sec, f"  function {name}(") for name in _HELPERS)
    return _CANVAS + base + "\n" + consts + helpers + "\n"


def _line(text: str, start: str) -> str:
    """The one source line that starts with ``start`` (a constant table)."""
    found = re.search(r"^" + re.escape(start) + r".*$", text, re.MULTILINE)
    assert found is not None, start
    return found.group(0)


def _page(settings: Settings) -> tuple[str, str]:
    page = render_world_html(settings)
    return page, _module(page)


# --------------------------------------------------------------------------- where the section sits


def test_the_record_room_is_its_own_section_called_once_a_frame(settings: Settings) -> None:
    """The section sits before the live director (it only asks it for shots), runs from THE LOOP once a frame, keeps
    its CSS in the page's one <style> (hashed by the CSP) and offers its hooks on window.__skyport.records."""
    page, module = _page(settings)
    assert module.index("THE RECORD ROOM (Builder B)") < module.index(_DIRECTOR) < module.index(_LOOP)
    loop = _js_body(module, "  function frame(now) {")
    assert loop.count("recFrame();") == 1 and loop.index("recFrame();") < loop.index("director();")
    assert page.count("<style>") == 1 and "#postcard" in page and "#film" in page and "body.film #card" in page
    # a speech bubble passes over the postcard button: the button comes before the bubbles, with no z-index
    postcard_css = re.search(r"#postcard \{[^}]*\}", page)
    assert postcard_css is not None and "z-index" not in postcard_css.group(0)
    assert "body.insertBefore(recBtn, bubblesEl)" in _section(module)
    assert "style-src 'sha256-" in WORLD_CSP
    sec = _section(module)
    assert "window.__skyport = Object.assign(window.__skyport || {}, { records: {" in sec
    for hook in ("film: { play:", "seek: function (t, hold)", "tour: { play:", "view: function (id, hold, cardH)",
                 "flying: function () { return FLY.on; }", "postcard: { take:", "shelf: function ()"):
        assert hook in sec, hook
    assert "innerHTML" not in sec and "eval(" not in sec and "localStorage" not in sec


def test_the_record_room_leaves_the_live_director_as_it_was(settings: Settings) -> None:
    """Hooks, not edits: the planner's pin takes no angle (the film's close is the risk wall's own view), and the
    section only reads the drone's flight (FLY.on) and gives a board's shot the director's own way: a pin on a key the
    planner does not know, the shot set to that key, its rig in the operator's RIGS table."""
    _, module = _page(settings)
    director = module[module.index(_DIRECTOR):module.index(_LOOP)]
    assert "pin: function (id, now) { pin.id = id; pin.until = now + cfg.pin; }," in director
    assert "function frame(s, now, live, hard) {" in director and "pin.angle" not in director
    for name in ("REC", "FILM", "recView", "recFrame", "filmStep"):  # it knows nothing of the record room
        assert re.search(r"\b" + name + r"\b", director) is None, name
    sec = _section(module)
    assert set(re.findall(r"FLY\.\w+", sec)) == {"FLY.on"}  # read only (the film's clock, the hook)
    assert "FLY.on =" not in sec and "PLANNER.plan" not in sec and "PLANNER.cutHard" not in sec
    view = _js_body(sec, "  function recView(id, hold, hard, cardH) {")
    assert "RIGS[V.key] = V.rigs;" in view and "togglePin(V.key)" in view and "const s = PLANNER.shot;" in view


def test_the_record_room_allocates_nothing_in_its_frame_step(settings: Settings) -> None:
    """recFrame redraws only when a new poll landed (the data object changed); the programme's step only compares
    numbers; the chips are made once."""
    _, module = _page(settings)
    frame = _js_body(module, "  function recFrame() {")
    assert "if (data !== REC.seen) { REC.seen = data; if (data) recApply(data); }" in frame
    assert "if (!REC.chip && chipEls.length) recChips();" in frame and "createElement" not in frame
    assert "JSON" not in frame
    step = _js_body(module, "  function filmStep() {")
    for word in ("new ", "JSON", "function (", "[]", "{}", ".slice(", ".map(", "+ \""):
        assert word not in step, word


# --------------------------------------------------------------------------- the boards


@needs_node
def test_the_ledger_plaque_engraves_the_receipts_own_words(settings: Settings, tmp_path: Path) -> None:
    _, module = _page(settings)
    draw = _js_body(_section(module), "  function recDrawPlaque(rc) {")
    out = _node(_helpers(module) + f"""
const recPlaque = board(1024, 512);
{draw}
const runs = [];
[{{ count: 5, verified: true, first_bad_seq: null, head: "ab".repeat(32), head_short: "abababab…abababab" }},
 {{ count: 12, verified: false, first_bad_seq: 7, head: "cd".repeat(32), head_short: "cdcdcdcd…cdcdcdcd" }},
 {{ count: 1, verified: null, first_bad_seq: null, head: null, head_short: null }},
 {{ count: 0, verified: true, first_bad_seq: null, head: "0".repeat(64), head_short: "00000000…00000000" }}, null].forEach(function (rc) {{
  recDrawPlaque(rc); runs.push(Array.from(new Set(texts()))); }});
console.log(JSON.stringify(runs));
""", tmp_path)
    fixed = ["THE LEDGER", "each record is sealed to the one before it"]
    assert out[0] == ["THE LEDGER", "5 sealed receipts · verified", "head abababab…abababab", fixed[1]]
    assert "12 sealed receipts · first bad entry #7" in out[1] and "head cdcdcdcd…cdcdcdcd" in out[1]
    assert "1 sealed receipt · not checked yet" in out[2]
    # an empty ledger: no records yet, and no all-zero head hash
    assert out[3] == ["THE LEDGER", "no records yet", "", fixed[1]] and out[4] == out[3]


@needs_node
def test_rooks_risk_wall_reads_only_the_api_numbers_and_red_is_real_money(settings: Settings, tmp_path: Path) -> None:
    """The gauges come from team.members[risk].risk_wall and its real_caps; with nothing (or half a wall) the wall
    says so in words; a paused day and the real desk's caps (open $ vs $10, today's loss vs $3, total vs $10). The
    desks by the page's words (practice always pretend, the real one REAL), and red for real money only: a pretend
    gauge past 90% or a losing practice rule is orange or amber, never red."""
    _, module = _page(settings)
    sec = _section(module)
    tables = "\n".join(_line(sec, start) for start in ("  const REC_STOPS = ", "  const REC_DESKS = "))
    out = _node(_helpers(module) + f"""
const recWall = board(1024, 720);
{tables}
{_js_body(sec, "  function recBar(")}
{_js_body(sec, "  function recDeskWords(d) {")}
{_js_body(sec, "  function recDrawWall(wall, caps, label) {")}
const paused = {{ allowance_used_pct: 104.0, slots_used: 3, slots_max: 3, daily_stop: true, stopped_by: "daily_loss",
  desks: [{{ desk: "Polymarket paper", verdict: "losing", paused: true }}, {{ desk: "Polymarket real", verdict: "losing", paused: false }}] }};
const caps = {{ label: "Real money", on: true, open_usd: 4.82, open_max_usd: 10, day_loss_usd: 0.97, day_max_usd: 3,
  total_loss_usd: 2.52, total_max_usd: 10 }};
const runs = [];
recDrawWall(null, null, undefined); runs.push(texts());
recDrawWall({{}}, null, "Paper money (pretend)"); runs.push(texts());
recDrawWall({{ allowance_used_pct: null, slots_used: null, slots_max: null, daily_stop: null, desks: null }}, null, null); runs.push(texts());
strokes.length = 0; recDrawWall(paused, caps, "Paper money (pretend)"); const full = drawn.slice(), fullStrokes = strokes.slice(); runs.push(texts());
recDrawWall(paused, Object.assign({{}}, caps, {{ on: false }}), "Paper money (pretend)"); runs.push(texts());
recDrawWall(Object.assign({{}}, paused, {{ desks: [{{ desk: "Polymarket paper", verdict: "winning", paused: false }}] }}), null, "Paper money (pretend)");
const winning = painted();
console.log(JSON.stringify({{ runs: runs, full: full, strokes: fullStrokes, winning: winning }}));
""", tmp_path)
    runs = out["runs"]
    for run in runs:
        assert not any(bad in t for t in run for bad in ("undefined", "NaN", "null", "[object")), run
    empty = runs[0]
    for words in ("ROOK'S RISK WALL", "—", "no money check yet today", "Trade slots: 0 of 0 in use", "Daily stop: not known yet",
                  "no desk to judge", "Real money: no real-money bets on record."):
        assert words in empty, words
    assert runs[1] == [t if t != "Solana bot · " else "Solana bot · Paper money (pretend)" for t in empty]
    assert runs[2] == empty
    full = runs[3]
    for words in ("Solana bot · Paper money (pretend)", "104%", "of today's loss allowance", "Trade slots: 3 of 3 in use",
                  "Daily stop: ON, no new buys today", "New buys stopped: today's loss limit",
                  "Polymarket practice (pretend money)", "losing · new buys paused", "Polymarket REAL money", "losing",
                  "Real money · the Polymarket desk's hard limits", "In open bets", "$4.82 of $10.00", "Lost today (UTC)",
                  "$0.97 of $3.00", "Lost in total", "$2.52 of $10.00"):
        assert words in full, words
    assert "Polymarket paper" not in full and "Polymarket real" not in full  # never the desk's raw name
    assert "Real money · the Polymarket desk's hard limits (no new real bets now)" in runs[4]
    colour = {d["t"]: d["fill"] for d in out["full"]}
    assert colour["Polymarket REAL money"] in _REDS and colour["losing"] in _REDS  # the real desk: red
    assert colour["losing · new buys paused"] not in _REDS and colour["Polymarket practice (pretend money)"] not in _REDS
    assert colour["Daily stop: ON, no new buys today"] not in _REDS and colour["104%"] not in _REDS
    assert "#ff9f43" in out["strokes"] and not any(s in _REDS for s in out["strokes"][:3])  # the 104% gauge: orange
    win = {d["t"]: d["fill"] for d in out["winning"]}
    assert "winning (pretend)" in win and win["winning (pretend)"] not in _REDS  # a pretend win says pretend


@needs_node
def test_the_trophy_shelf_counts_each_result_and_says_what_the_money_did(settings: Settings, tmp_path: Path) -> None:
    """One trophy per win and one tile per loss (grey if even), the real bets on the top tier (a real loss a red tile,
    a pretend loss a dark slate one), the practice trades inside, newest at the left end (nearest Mote); each tier's
    counts beside the money it stands for since start (from the API: a row of real trophies never reads as a profit
    the money does not show); what is not on the shelf; the last five results, each tagged REAL or pretend; the
    instances' bounds set round what is on the shelf (culled like any mesh)."""
    _, module = _page(settings)
    sec = _section(module)
    out = _node(_helpers(module) + f"""
{_line(sec, "  const SHELF = ")}
const slots = [];
let bounds = 0;
const inst = function () {{ return {{ count: 0, instanceMatrix: {{}}, instanceColor: {{}}, colours: [], setColorAt: function (i, c) {{ this.colours[i] = c; }},
  computeBoundingSphere: function () {{ bounds += 1; }} }}; }};
const recTrophies = inst(), recTiles = inst(), REC_LOSS = "loss", REC_LOSS_REAL = "lossReal", REC_EVEN = "even";
const recSlot = function (im, i, x, y, tilt) {{ slots.push({{ kind: im === recTrophies ? "W" : "T", i: i, x: x, y: y }}); }};
const recCard = board(1024, 704);
{_js_body(sec, "  function recMore(n) {")}
{_js_body(sec, "  function recDrawShelf(sum, closed) {")}
{_js_body(sec, "  function recLatest(sum, closed) {")}
let order = ""; for (let i = 0; i < 180; i++) order += "WLLE"[i % 4];
const sum = {{ label: "Paper money (pretend)", won: 45, lost: 90, even: 45, total: 230, since: 1, order: order, result: "down $5.50 since start",
  real: {{ label: "Real money", won: 1, lost: 2, settled: 3, since: 1, order: "LWL", result: "down $2.52 since start",
    lines: [{{ ts: 300, won: false, text: "REAL · lost −$0.97 · Will the Fed cut rates?" }}, {{ ts: 100, won: true, text: "REAL · won +$0.03 · Rain in Athens?" }}] }} }};
const closed = [{{ coin: "HIGGS", closed_at: 200, pnl_usd: 2.13, result: "won", why: "Took profit" }},
  {{ coin: "PY", closed_at: 50, pnl_usd: -1.5, result: "lost", why: "Stop-loss: cut the loss" }},
  {{ coin: "OLD", closed_at: 10, pnl_usd: 0.1, result: "won", why: "" }}, {{ coin: "OLDER", closed_at: 5, pnl_usd: 0.1, result: "won", why: "" }}];
recDrawShelf(sum, closed);
const cardDrawn = drawn.slice(), card = texts(), first = slots.slice(), counts = [recTrophies.count, recTiles.count], shown = Object.assign({{}}, REC.shelf);
const colours = recTiles.colours.slice(0, recTiles.count), latest = REC.lines.slice();
let many = ""; for (let i = 0; i < 40; i++) many += "W";
recDrawShelf(Object.assign({{}}, sum, {{ real: Object.assign({{}}, sum.real, {{ won: 46, lost: 1, order: many + "L" }}) }}), closed); const moreCard = texts();
slots.length = 0; recDrawShelf(null, null);
console.log(JSON.stringify({{ card: card, cardDrawn: cardDrawn, counts: counts, shown: shown, slots: first, colours: colours, latest: latest,
  moreCard: moreCard, none: texts(), noneCounts: [recTrophies.count, recTiles.count], shelf: SHELF, bounds: bounds }}));
""", tmp_path)
    shelf, slots = out["shelf"], out["slots"]
    shown_pretend = shelf["tierCap"] * shelf["tiers"]
    assert out["shown"] == {"real": 3, "pretend": shown_pretend, "realMore": 0, "pretendMore": 230 - shown_pretend}
    pretend = "".join("WLLE"[i % 4] for i in range(shown_pretend))
    assert out["counts"] == [1 + pretend.count("W"), 2 + pretend.count("L") + pretend.count("E")]
    # real losses red, practice losses a dark slate, even ones grey
    assert out["colours"][:2] == ["lossReal", "lossReal"]
    assert out["colours"][2:].count("loss") == pretend.count("L") and out["colours"].count("even") == pretend.count("E")
    assert out["bounds"] >= 2 * 3  # each redraw: both instance sets' bounds
    top, inner = slots[:3], slots[3:5]  # (the real bets first, then the practice trades, each newest first)
    assert [s["x"] for s in top] == pytest.approx([shelf["realX0"] + (i + 0.5) * shelf["step"] for i in range(3)])
    assert all(s["y"] == pytest.approx(shelf["topY"], abs=0.03) for s in top)
    assert [s["kind"] for s in top] == ["T", "W", "T"]  # "LWL": the newest (a loss) at the left
    assert inner[0]["x"] == pytest.approx(shelf["x0"] + 0.5 * shelf["step"]) and inner[1]["x"] > inner[0]["x"]
    assert all(s["y"] == pytest.approx(shelf["tierY"][0], abs=0.03) for s in inner)
    card = out["card"]
    for words in ("THE TROPHY SHELF", "a trophy per win, a dark tile per loss (grey: even); red: real money",
                  "Top shelf: Real money · Polymarket bets", "1 won · 2 lost · down $2.52 since start",
                  "Inside: Paper money (pretend) · Solana bot trades", "45 won · 90 lost · 45 even · down $5.50 since start",
                  f"+{230 - shown_pretend} more not on the shelf", "Latest results"):
        assert words in card, words
    assert "+15 more not on the shelf" in out["moreCard"] and "46 won · 1 lost · down $2.52 since start" in out["moreCard"]
    assert [line["text"] for line in out["latest"]] == [
        "REAL · lost −$0.97 · Will the Fed cut rates?", "pretend · HIGGS won +$2.13 · Took profit",
        "REAL · won +$0.03 · Rain in Athens?", "pretend · PY lost −$1.50 · Stop-loss: cut the loss", "pretend · OLD won +$0.10"]
    assert [line["real"] for line in out["latest"]] == [True, False, True, False, False]
    colour = {d["t"]: d["fill"] for d in out["cardDrawn"]}
    assert colour["pretend · PY lost −$1.50 · Stop-loss: cut the loss"] not in _REDS  # a pretend loss is not red
    assert colour["REAL · won +$0.03 · Rain in Athens?"] in _REDS  # real money is
    assert out["noneCounts"] == [0, 0]
    assert "Top shelf: real money: no real bets on record" in out["none"] and "No trade or real bet has finished yet." in out["none"]


@needs_node
def test_the_labs_board_is_the_fixed_table_in_plain_words(settings: Settings, tmp_path: Path) -> None:
    """"What the labs found": each lab's verdict chip (its own word), its question and its plain words, whole (never
    cut with "…"); the counted trials and the board's sentence (true of the table: no lab passed); while real money is
    on, the real desk's own verdict on its rule beside it, in red. It never says real money follows the labs."""
    _, module = _page(settings)
    sec = _section(module)
    research = research_state()
    verdict = ("This rule did not pass our tests for a real edge (proof that it wins over many bets), so it trades "
               "only tiny real amounts with hard limits.")
    out = _node(_helpers(module) + f"""
const recLabs = board(1024, 768);
{_line(sec, "  const REC_LAB_COLOUR = ")}
{_js_body(sec, "  function recDrawLabs(res, real) {")}
const research = {json.dumps(research)};
recDrawLabs(research, {{ on: true, verdict: {json.dumps(verdict)} }}); const on = painted();
recDrawLabs(research, {{ on: false, verdict: "This rule did not pass our tests for a real edge; it places no new real-money bets now." }}); const off = texts();
recDrawLabs(null, null); const none = texts();
console.log(JSON.stringify({{ on: on, off: off, none: none }}));
""", tmp_path)
    on = [d["t"] for d in out["on"]]
    assert on[0] == "What the labs found"
    joined = " ".join(on)
    for lab in research["labs"]:
        assert lab["lab"] in on and lab["verdict"] in on
        assert any(t.startswith(f"{lab['trials']:,} trial") for t in on), lab["lab"]
        assert " ".join(lab["plain"].split()) in joined, lab["lab"]  # the plain words, whole, over its lines
        assert lab["reading"] not in joined  # (not the researchers' shorthand)
    assert {lab["verdict"] for lab in research["labs"]} == {"NO WINNER", "NO EDGE", "FAIL"}
    assert not any(t.endswith("…") for t in on)
    assert f"{research['trials_total']:,} trials counted;" in on and research["rule"] in on
    real = [d for d in out["on"] if d["fill"] in _REDS]
    assert " ".join(d["t"] for d in real) == "Real money: " + verdict  # the desk's own words, in red
    assert not any(t.startswith("Real money") for t in out["off"])  # real money off: nothing said about it here
    for t in on + out["off"]:
        assert "no edge gets real money" not in t
    assert out["none"] == ["What the labs found", "Not in this version."]


@needs_node
def test_the_trend_board_is_pretend_money_and_gives_its_screen_back(settings: Settings, tmp_path: Path) -> None:
    _, module = _page(settings)
    sec = _section(module)
    out = _node(_helpers(module) + f"""
const recTrend = board(1024, 648); REC.trendScreen = {{ visible: true }};
{_js_body(sec, "  function recDrawTrend(tr) {")}
const trend = {{ mode: "paper", label: "Paper money (pretend)", as_of: 1, sleeve_usd: 100, equity_usd: 101.2, today_usd: 0.3,
  since_start_usd: 1.2, hold_since_start_usd: -0.4, in_market: {{ BTC: true, ETH: false, SOL: true }}, started: "2026-10-07", problem: null }};
recDrawTrend(trend); const on = {{ texts: texts(), board: recTrend.visible, screen: REC.trendScreen.visible }};
recDrawTrend(Object.assign({{}}, trend, {{ as_of: null }})); const first = texts();
recDrawTrend(null); const off = {{ texts: texts(), board: recTrend.visible, screen: REC.trendScreen.visible }};
console.log(JSON.stringify({{ on: on, first: first, off: off }}));
""", tmp_path)
    on = out["on"]
    assert on["board"] is True and on["screen"] is False
    for words in ("Trend desk · Paper money (pretend)", "BTC", "ETH", "SOL", "Since start: +$1.20", "Holding the three: −$0.40",
                  "Pretend money: lab 3's rule tried on new days"):
        assert words in on["texts"], words
    assert on["texts"].count("IN") == 2 and on["texts"].count("OUT") == 1
    assert "First booking at the close of 2026-10-07 (UTC midnight)" in out["first"]
    assert out["off"] == {"texts": [], "board": False, "screen": True}


# --------------------------------------------------------------------------- the boards' camera views

_THREE = (ASSET_DIR / "three.module.min.js").resolve().as_uri()


@needs_node
def test_each_board_has_a_view_sized_for_the_screen_in_hand(settings: Settings, tmp_path: Path) -> None:
    """A board straight on, as large as the band between the top bar and the card allows: on a 390 and a 360 px phone a
    two-column board (the risk wall, the labs) is panned across, each half read at about twice the size, while the
    plaque and the trophy card fit whole; on a wide screen nothing pans; the drone is always in front of the board. A
    view is the director's own place rig, given through its pin: the shot is set to the board's key."""
    _, module = _page(settings)
    sec, director = _section(module), module[module.index(_DIRECTOR):]
    views = sec[sec.index("  const REC_VIEWS = {};"):sec.index("  function recView(id, hold, hard, cardH) {")]
    views = views[:views.index('  recViewOf("riskwall"')] + views[views.index("  const _vc = "):]
    out = _node(f"""
import * as THREE from "{_THREE}";
const V3 = function (x, y, z) {{ return new THREE.Vector3(x, y, z); }};
const camera = {{ aspect: 1 }};
{_line(director, "  const LENS_MM = ")}
{_js_body(director, "  function fovFor(mm) {")}
const window = {{ innerWidth: 390, innerHeight: 844 }};
let barBottom = 190, cardTop = 690, cardBottom = 800, pinned = null, simT = 3;
const card = {{ getBoundingClientRect: function () {{ return {{ top: cardTop, bottom: cardBottom }}; }} }};
const RIGS = {{}}, pins = [];
const PLANNER = {{ shot: {{ seq: 4, subject: "jet", grammar: "closeup" }}, pin: function (k) {{ pins.push(k); pinned = k; }} }};
const togglePin = function (k) {{ pins.push(k); pinned = k; }};
const mesh = function (w, h, x, y, z, ry, tilt) {{
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h)); m.position.set(x, y, z); m.rotation.order = "YXZ"; m.rotation.y = ry; m.rotation.x = tilt || 0; m.visible = true; return m; }};
const recWall = mesh(1.4, 0.984, 8, 2.84, -3, 0.6), recPlaque = mesh(0.84, 0.42, 12, 2.2, -3, 0.6), recCard = mesh(0.9, 0.62, -6, 1.36, 2, 2.0, -0.2);
const recLabs = mesh(1.5, 1.125, -6, 2.35, 2, 2.0), recTrend = mesh(1.5, 0.95, 1, 1.95, -9, -0.3);
{views}
recViewOf("riskwall", recWall, 1.4, 0.984, true, "vault"); recViewOf("plaque", recPlaque, 0.84, 0.42, false, "vault");
recViewOf("trophies", recCard, 0.9, 0.62, false, "archive", 0.45); recViewOf("labs", recLabs, 1.5, 1.125, true, "archive");
recViewOf("trend", recTrend, 1.5, 0.95, true, "observatory");
{_js_body(sec, "  function recView(id, hold, hard, cardH) {")}
const measure = function (V) {{
  recViewRig(V); const m = V.mesh, c = new THREE.Vector3(), q = new THREE.Quaternion(); m.getWorldPosition(c); m.getWorldQuaternion(q);
  const n = new THREE.Vector3(0, 0, 1).applyQuaternion(q), r = new THREE.Vector3(1, 0, 0).applyQuaternion(q), R = V.rig;
  const t = Math.tan(fovFor(LENS_MM.place) * Math.PI / 360), d = R.p0.distanceTo(R.l0), hv = 2 * d * t, wv = hv * camera.aspect;
  return {{ pan: R.l1.clone().sub(R.l0).dot(r), front: Math.min(R.p0.clone().sub(c).dot(n), R.p1.clone().sub(c).dot(n)),
    straight: R.p0.clone().sub(R.l0).normalize().dot(n.clone().applyAxisAngle(r, -V.lift)), lift: V.lift,
    up: R.p0.y - R.l0.y, wv: wv, hv: hv, w: V.w, h: V.h,
    css: window.innerWidth / wv * V.w / 1024 }};
}};
const run = function (w, h, bar, top, bottom) {{
  window.innerWidth = w; window.innerHeight = h; camera.aspect = w / h; barBottom = bar; cardTop = top; cardBottom = bottom;
  const o = {{}}; Object.keys(REC_VIEWS).forEach(function (k) {{ o[k] = measure(REC_VIEWS[k]); }}); return o;
}};
const phone = run(390, 844, 190, 690, 800), small = run(360, 780, 200, 630, 740), desk = run(1440, 900, 60, 760, 880);
const key = recView("riskwall", 12, true, 150);
console.log(JSON.stringify({{ phone: phone, small: small, desk: desk, key: key, shot: PLANNER.shot, rigs: Object.keys(RIGS), pins: pins,
  rigIsTheView: RIGS["rec:riskwall"][0] === REC_VIEWS.riskwall.rig }}));
""", tmp_path)
    for screen, (W, H, bar, top) in (("phone", (390, 844, 190, 650)), ("small", (360, 780, 200, 590))):
        o = out[screen]
        band = (top / H - 0.02) - (bar + 10) / H  # (the card the beat shows: 150 px over the LIVE card's bottom)
        for k in ("riskwall", "labs"):  # two columns: panned, each half large
            assert o[k]["pan"] > 0.2 and o[k]["wv"] < o[k]["w"], (screen, k)
            assert o[k]["css"] >= 0.44, (screen, k)  # a 24 px canvas line reads at 10.5 css px or more
        for k in ("plaque", "trophies"):  # read across: whole
            assert abs(o[k]["pan"]) < 1e-6 and o[k]["wv"] >= o[k]["w"] * 1.05, (screen, k)
        for k, v in o.items():
            assert v["front"] > 0.3 and v["straight"] > 0.999, (screen, k)  # in front of the board, straight on
            assert v["h"] / v["hv"] <= 0.95 * band + 1e-6, (screen, k)  # never under the bar or the card
    assert out["phone"]["trophies"]["up"] > 0.8  # the trophy card from above Mote's bell (the drone looks down at it)
    for k, v in out["desk"].items():
        assert abs(v["pan"]) < 1e-6 and v["wv"] >= v["w"] and v["front"] > 0.3, k
    assert out["key"] == "rec:riskwall" and out["rigs"] == ["rec:riskwall"] and out["rigIsTheView"] is True
    shot = out["shot"]
    assert (shot["seq"], shot["subject"], shot["grammar"], shot["angle"], shot["hold"], shot["hard"], shot["pinned"]) == \
        (5, "rec:riskwall", "place", 0, 12, True, True)
    assert out["pins"] == ["rec:riskwall"]
    assert math.isfinite(out["phone"]["riskwall"]["css"])


# --------------------------------------------------------------------------- the postcard

_LONG_PRACTICE = ("Practice (pretend money): the Solana bot is up $3.50 since start; Polymarket practice bets are down "
                  "$1,345.53 since start (−$1,345.53 today); the trend desk is up $3.50 since start.")


@needs_node
def test_the_postcard_burns_in_the_real_line_and_never_the_token_or_address(settings: Settings, tmp_path: Path) -> None:
    """The frame, rendered sharp at a set pixel ratio (and the page's own put back), plus the real-money line
    (plain.real's own result and money in bets, "real money" said once, red while it is on, never smaller than the
    practice text), the practice line (smaller before it is cut, and then only whole clauses), the time with its zone
    and the fixed footer; the share sheet gets the picture alone, a file name without the address; the section never
    reads the token or the page's location; one postcard at a time."""
    _, module = _page(settings)
    sec = _section(module)
    assert re.search(r"\btoken\b", sec) is None and "location" not in sec and "params" not in sec
    assert 'navigator.share({ files: [file], title: "nightcrawler" })' in sec
    out = _node(_helpers(module) + f"""
const document = {{ createElement: function () {{ const ctx = makeCtx(); return {{ width: 0, height: 0, getContext: function () {{ return ctx; }} }}; }} }};
const THREE = {{ Vector2: function () {{ this.x = 0; this.y = 0; }} }};
const composer = null, scene = {{}}, camera = {{}};
const renderer = {{ _w: 390, _h: 844, _r: 1, renders: [], domElement: {{ width: 390, height: 844 }},
  getSize: function (v) {{ v.x = this._w; v.y = this._h; return v; }}, getPixelRatio: function () {{ return this._r; }},
  setPixelRatio: function (r) {{ this._r = r; this.setSize(this._w, this._h); }},
  setSize: function (w, h) {{ this._w = w; this._h = h; this.domElement.width = Math.floor(w * this._r); this.domElement.height = Math.floor(h * this._r); }},
  render: function () {{ this.renders.push(this._r); }} }};
{_js_body(module, "  function realWords(r) {")}
{_line(sec, "  const REC_FOOT = ")}
{_line(sec, "  const _recSize = ")}
{_js_body(sec, "  function recRealLine(r) {")}
{_js_body(sec, "  function recPostcardLines(now) {")}
{_js_body(sec, "  function recPostcard(now) {")}
{_js_body(sec, "  function recBurnIn(c, now) {")}
{_js_body(sec, "  function recFileName(now) {")}
let plain = {{ real: {{ label: "Real money", on: true, reported: true, at_risk_usd: 4.82, open_bets: 5, result: "down $2.52 since start" }},
  pretend: {{ line: "Practice (pretend money): the Solana bot is down $5.50 since start; Polymarket practice bets have not finished a round yet." }} }};
const when = new Date(2026, 9, 10, 8, 39);
const c = recPostcard(when), on = {{ size: [c.width, c.height], texts: texts(), lines: REC.postcardLines, red: recPostcardLines(when).red,
  renders: renderer.renders.slice(), after: renderer._r }};
plain = {{ real: {{ label: "Real money", on: true, reported: true, at_risk_usd: 4.82, open_bets: 5, result: "up $0.03 since start (real money)" }},
  pretend: {{ line: {json.dumps(_LONG_PRACTICE)} }} }};
const up = {{}};
[[390, 844], [360, 780]].forEach(function (s) {{ renderer._w = s[0]; renderer._h = s[1]; recPostcard(when); up[s[0]] = {{ lines: REC.postcardLines, texts: texts() }}; }});
plain = Object.assign({{}}, plain, {{ pretend: {{ line: {json.dumps(_LONG_PRACTICE)} + " " + {json.dumps(_LONG_PRACTICE)} + " " + {json.dumps(_LONG_PRACTICE)} }} }});
renderer._w = 360; renderer._h = 780; recPostcard(when); const flood = REC.postcardLines;
plain = {{ real: {{ label: "Real money", on: false, reported: false }}, pretend: {{ line: "Practice (pretend money): nothing yet." }} }};
const off = recPostcardLines(when); recPostcard(when); const offTexts = texts();
plain = null; const none = recPostcardLines(when);
console.log(JSON.stringify({{ on: on, up: up, flood: flood, off: off, offTexts: offTexts, none: none, name: recFileName(when) }}));
""", tmp_path)
    on = out["on"]
    ratio = 2048 / 844
    assert on["size"] == [math.floor(390 * ratio), math.floor(844 * ratio)]  # sharp: 2048 px on the long side
    assert on["renders"] == [pytest.approx(ratio)] and on["after"] == 1  # rendered at the set ratio, the page's put back
    assert " ".join(on["lines"]["real"]) == "Real money: down $2.52 since start · $4.82 in bets" and on["red"] is True
    painted_texts = " ".join(on["texts"])
    assert on["texts"][0] == on["lines"]["real"][0]
    assert "Practice (pretend money): the Solana bot is down $5.50" in painted_texts
    assert "nightcrawler · a visualisation of the bot's own ledger" in painted_texts and on["lines"]["when"] in painted_texts
    assert re.search(r"\b(?:UTC|GMT|[A-Z]{2,5}|GMT[+-]\d+)$", on["lines"]["when"])  # the time says its zone
    for width, shot in out["up"].items():
        lines = shot["lines"]
        assert " ".join(lines["real"]) == "Real money: up $0.03 since start · $4.82 in bets", width  # said once
        assert lines["realPx"] >= lines["practicePx"], width  # never smaller than the practice text
        assert " ".join(lines["practice"]) == _LONG_PRACTICE, width  # smaller, but whole
        # each line ends at a clause where the size allows ("$4.82 in" / "bets" never; this long practice line holds
        # its three clauses in three lines only by words)
        assert all(line.endswith("·") for line in lines["real"][:-1]), (width, lines["real"])
    for name, mark in (("real", "·"), ("practice", ";")):
        assert len(on["lines"][name]) > 1 and all(line.endswith(mark) for line in on["lines"][name][:-1]), on["lines"]
    flood = out["flood"]
    practice = " ".join(flood["practice"])
    assert practice.endswith("; …") and _LONG_PRACTICE.startswith(practice[:-3].split("; ")[0])
    for text in [t for shot in out["up"].values() for t in shot["texts"]] + flood["practice"]:
        assert not re.search(r"\d…$", text), text  # never a figure cut in two
    assert out["off"]["real"] == "Real money: no report yet" and out["off"]["red"] is False
    assert out["none"]["real"] == "Real money: not in this version"
    assert out["none"]["practice"] == "Practice (pretend money): not in this version"
    for text in on["texts"] + out["offTexts"]:
        for bad in ("token", "http", "/world", "?", "127.0.0.1", "undefined"):
            assert bad not in text, (bad, text)
    assert out["name"] == "nightcrawler-postcard-20261010-0839.png"


@needs_node
def test_one_postcard_at_a_time_with_a_note_while_it_is_made(settings: Settings, tmp_path: Path) -> None:
    _, module = _page(settings)
    sec = _section(module)
    out = _node(_helpers(module) + f"""
let simT = 10;
const timers = [], saved = [];
const setTimeout = function (fn) {{ timers.push(fn); }};
const recToast = {{ textContent: "", hidden: true }}, body = {{ appendChild: function () {{}} }};
const document = {{ createElement: function () {{ return {{ click: function () {{ saved.push(this.download); }}, remove: function () {{}} }}; }} }};
const URL = {{ createObjectURL: function () {{ return "blob:x"; }}, revokeObjectURL: function () {{}} }};
const navigator = {{ maxTouchPoints: 0 }};
const recPostcard = function () {{ return {{ toBlob: function (cb) {{ cb({{ size: 1 }}); }} }}; }};
{_js_body(sec, "  function recToastSay(text, seconds) {")}
{_js_body(sec, "  function recFileName(now) {")}
{_js_body(sec, "  function recDone(text) {")}
{_js_body(sec, "  function recSaveBlob(blob, name) {")}
{_js_body(sec, "  function recShoot() {")}
recShoot(); const making = recToast.textContent, busy = REC.busy; recShoot(); recShoot();
const queued = timers.length; timers.shift()();
const done = {{ busy: REC.busy, toast: recToast.textContent, saved: saved.length }};
recShoot(); while (timers.length) timers.shift()();
console.log(JSON.stringify({{ making: making, busy: busy, queued: queued, done: done, saved: saved.length }}));
""", tmp_path)
    assert out["making"] == "Making your postcard…" and out["busy"] is True
    assert out["queued"] == 1  # the second and third taps did nothing
    assert out["done"] == {"busy": False, "toast": "Postcard saved", "saved": 1}
    assert out["saved"] == 2  # and the next tap makes the next one


# --------------------------------------------------------------------------- yesterday's film and the records tour

_FILM_STUBS = r"""
const el = function (tag) { return { tag: tag, hidden: false, className: "", textContent: "", style: {}, children: [], attrs: {},
  appendChild: function (c) { this.children.push(c); }, setAttribute: function (k, v) { this.attrs[k] = v; } }; };
const document = { createElement: el };
const bodyCls = new Set(), body = { appendChild: function () {}, classList: { add: function (c) { bodyCls.add(c); }, remove: function (c) { bodyCls.delete(c); } } };
const card = { getBoundingClientRect: function () { return { bottom: 700 }; } }, window = { innerHeight: 800 };
const guideEl = { hidden: true }; let panelKind = null, simT = 0, pinned = null, wentLive = 0, data = null;
const closePanel = function () {}, closeGuide = function () {};
const pins = [], views = [], FLY = { on: false };
const PLANNER = { pin: function (k, t) { pins.push(k); pinned = k; } };
const togglePin = function (k) { pinned = pinned === k ? null : k; if (pinned) pins.push(k); };
const goLive = function () { pinned = null; wentLive += 1; };
const REC_VIEWS = { riskwall: { mesh: { visible: true } }, plaque: { mesh: { visible: true } }, trophies: { mesh: { visible: true } },
  labs: { mesh: { visible: true } }, trend: { mesh: { visible: true } } };
const recView = function (id, hold, hard) { views.push(id); pinned = "rec:" + id; return pinned; };
const actorOf = { judge: "voss", predict: "voss", broker: "jet", risk: "rook", receipts: "mote", crawler: "pip" };
const CAST = { voss: { name: "Voss" }, jet: { name: "Jet" }, rook: { name: "Rook" }, mote: { name: "Mote" }, pip: { name: "Pip" } };
const nameOf = function (m) { return m; };
const plain = { jobs: { judge: "bets on yes/no questions at Polymarket", broker: "places the Solana bot's trades" } };
const shot = function () { return { i: FILM.i, shown: FILM.shown, tag: filmTag.textContent, prog: filmProg.textContent, who: filmWho.textContent,
  text: filmText.textContent, real: filmReal.hidden ? null : filmReal.textContent, pretend: filmPretend.hidden ? null : filmPretend.textContent,
  note: filmNote.hidden ? null : filmNote.textContent, cls: filmEl.className, pinned: pinned, film: bodyCls.has("film"),
  visibility: filmEl.style.visibility || "" }; };
const run = function (seconds) { const n = Math.round(seconds / 0.1); for (let k = 0; k < n; k++) { simT += 0.1; if (FILM.on) filmStep(); } };
// (a beat's words come up a frame after the director's pass at the request: step until they do)
const untilShown = function () { for (let k = 0; k < 50 && FILM.on && FILM.shown !== FILM.i; k++) { simT += 0.1; filmStep(); } };
"""


def _film(module: str) -> str:
    sec = _section(module)
    block = sec[sec.index("  const FILM = {"):sec.index("once a frame (from THE LOOP)")]
    return _helpers(module) + _FILM_STUBS + block[:block.rindex("\n")] + "\n"


def _recap(n: int = 8) -> dict[str, Any]:
    tz = ZoneInfo("America/Los_Angeles")
    w0 = int(datetime(2026, 10, 9, tzinfo=tz).timestamp())
    events = [{"ts": w0 + 3600 * (i + 1) + 1800, "member": member, "text": text, "tone": tone, "real": real}
              for i, (member, text, tone, real) in enumerate([
                  ("crawler", "found a new coin: FIRST (70 min old)", "neutral", False),
                  ("predict", "real-money bet: $0.97 on YES · Will the Fed cut rates at the December meeting?", "neutral", True),
                  ("broker", "bought HIGGS for 0.1000 SOL (pretend money)", "neutral", False),
                  ("risk", "refused to buy RISKY: Too many open trades: 3 open", "bad", False),
                  ("predict", "a real-money bet lost $0.97 · Will the Fed cut rates at the December meeting?", "bad", True),
                  ("broker", "HIGGS: Sold after the price fell from its high · won +$2.13 (pretend money)", "good", False),
                  ("receipts", "sealed record #3 in the tamper-proof log", "neutral", False),
                  ("predict", "a real-money bet won $0.03 · Will it rain in Athens on Saturday?", "good", True)][:n])]
    return {"date": "2026-10-09", "tz": "America/Los_Angeles", "window": [w0, w0 + 86400], "events": events, "events_total": 214,
            "quiet": False, "closed": [],
            "real": {"label": "Real money", "start_usd": -1.2, "end_usd": -2.14, "settled": 2, "won": 1,
                     "line": "Real money yesterday: the day began down $1.20 since start and ended down $2.14 since start; "
                             "1 of 2 finished bets won."},
            "pretend": {"label": "Practice (pretend money)",
                        "line": "Practice (pretend money): the Solana bot's pretend wallet ended the day down $5.50, counting open "
                                "trades at their price."}}


@needs_node
def test_the_film_shows_each_beat_once_the_drone_has_arrived(settings: Settings, tmp_path: Path) -> None:
    """A title card at once, then one beat per event: the director pinned on whoever made it, the event's own words
    (real money marked REAL) only once the drone has arrived, the beat's clock waiting while it flies; the close on
    the risk wall's own view with real money's start and end and the practice line; then back to live. The same
    beat holds while the film is held (the screenshot hook)."""
    _, module = _page(settings)
    recap = _recap()
    out = _node(_film(module) + f"""
const recap = {json.dumps(recap)};
const played = filmPlay(recap, false), title = shot();
// the first beat: the drone flies for 3 s; its words wait on the title, and so does its clock
FLY.on = true; run(FILM_TITLE_S + 0.15); const asked = shot(); run(3); const flying = shot(), during = simT - FILM.t0; FLY.on = false; run(0.1);
const arrived = shot();
const beats = [arrived];
for (let k = 1; k < FILM.n; k++) {{ run(FILM.beat); untilShown(); beats.push(shot()); }}
run(FILM.beat); untilShown(); const closing = shot(), viewsAtEnd = views.slice();
run(FILM_END_S + 0.2);
const after = {{ on: FILM.on, pinned: pinned, wentLive: wentLive, film: bodyCls.has("film"), hidden: filmEl.hidden }};
// held: the frame stays on beat 3 however long the screenshot takes
filmPlay(recap, false); FILM.hold = FILM_TITLE_S + 2 * FILM.beat + 0.5; run(0.3); const heldA = shot(); run(30); const heldB = shot(); filmStop(true);
console.log(JSON.stringify({{ played: played, title: title, asked: asked, flying: flying, during: during, beats: beats, closing: closing,
  views: viewsAtEnd, after: after, held: [heldA.i, heldB.i, heldB.text], beat: FILM.beat, n: FILM.n, pins: pins }}));
""", tmp_path)
    assert out["played"] is True and out["n"] == 8 and out["beat"] == 5
    title = out["title"]
    assert title["who"] == "Friday, October 9 (PDT)" and title["tag"] == "YESTERDAY" and title["film"] is True
    assert title["text"] == "What the team did, from its own records: 8 moments of 214 records."
    # the request goes out at once, the words stay on the title while the drone flies, the clock waits for it
    assert out["asked"]["pinned"] == "pip" and out["asked"]["who"] == title["who"]
    assert out["flying"]["who"] == title["who"] and out["during"] == pytest.approx(5.05, abs=0.15)
    assert out["beats"][0]["who"] == "PIP"  # once the drone is there
    beats = out["beats"]
    assert [b["text"] for b in beats] == [e["text"] for e in recap["events"]]  # the event's own words, in order
    assert [b["prog"].split(" · ")[0] for b in beats] == [f"{i} of 8" for i in range(1, 9)]
    assert [b["pinned"] for b in beats] == ["pip", "voss", "jet", "rook", "voss", "jet", "mote", "voss"]
    assert beats[0]["tag"] == "YESTERDAY" and beats[0]["prog"].endswith(" · 1:30 AM PDT")
    assert beats[1]["tag"] == "YESTERDAY · REAL MONEY" and beats[1]["cls"] == "real"  # real money marked
    assert all((b["tag"] == "YESTERDAY · REAL MONEY") == e["real"] for b, e in zip(beats, recap["events"], strict=True))
    assert beats[2]["who"] == "JET · places the Solana bot's trades" and beats[1]["who"] == "VOSS"
    assert [b["cls"] for b in beats][3:6] == ["bad", "real", "good"]
    closing = out["closing"]
    assert out["views"] == ["riskwall"] and closing["pinned"] == "rec:riskwall"  # the real-money board, not the sign
    assert closing["who"] == "How the day ended" and closing["cls"] == "real" and closing["tag"] == "YESTERDAY · THE VAULT"
    assert closing["real"] == recap["real"]["line"] and closing["pretend"] == recap["pretend"]["line"]
    assert out["after"] == {"on": False, "pinned": None, "wentLive": 1, "film": False, "hidden": True}
    assert out["held"][0] == out["held"][1] == 3 and out["held"][2] == recap["events"][2]["text"]


@needs_node
def test_a_beats_words_wait_for_the_directors_pass_at_the_request(settings: Settings, tmp_path: Path) -> None:
    """A request made between two frames (the seek hook) is planned by the director in the next frame: the words wait
    for that pass (the drone may only then set off), and come up a frame later when there is no flight."""
    _, module = _page(settings)
    out = _node(_film(module) + f"""
filmPlay({json.dumps(_recap())}, false); run(0.3);
FILM.t0 = simT - 10.3; filmStep(); const asked = FILM.i, before = FILM.shown;  // (the hook calls filmStep itself)
simT += 0.1; filmStep(); const next = FILM.shown;  // the director's pass comes after this frame's step
simT += 0.1; filmStep(); const after = FILM.shown;
console.log(JSON.stringify({{ asked: asked, before: before, next: next, after: after }}));
""", tmp_path)
    assert out["asked"] == 2 and out["before"] == 0 and out["next"] == 0 and out["after"] == 2


@needs_node
def test_the_film_waits_for_a_reader_of_the_money_panel_and_hides(settings: Settings, tmp_path: Path) -> None:
    """Tapping REAL MONEY (or "?") during the film: the film's card hides and its clock and camera wait, so the panel
    is never stacked over a film that runs on underneath; closing the panel picks it up where it was."""
    _, module = _page(settings)
    out = _node(_film(module) + f"""
filmPlay({json.dumps(_recap())}, false); run(FILM_TITLE_S + FILM.beat + 1);
const before = shot(); panelKind = "real"; run(0.1); const opened = shot(); const pinsBefore = pins.length;
run(40); const waited = shot(), renewed = pins.length - pinsBefore;
panelKind = null; run(0.1); const back = shot();
guideEl.hidden = false; run(10); const guide = shot(); guideEl.hidden = true; run(0.1);
console.log(JSON.stringify({{ before: before, opened: opened, waited: waited, renewed: renewed, back: back, guide: guide, on: FILM.on }}));
""", tmp_path)
    assert out["opened"]["visibility"] == "hidden" and out["before"]["visibility"] == ""
    assert out["waited"]["i"] == out["before"]["i"] and out["waited"]["text"] == out["before"]["text"]  # it waited
    assert out["renewed"] > 0 and out["waited"]["pinned"] == out["before"]["pinned"]  # and kept its camera
    assert out["back"]["visibility"] == "" and out["back"]["i"] == out["before"]["i"] and out["on"] is True
    assert out["guide"]["visibility"] == "hidden" and out["guide"]["i"] == out["before"]["i"]


@needs_node
def test_a_day_without_records_says_how_quiet_it_was_and_the_viewer_can_take_the_camera(settings: Settings,
                                                                                        tmp_path: Path) -> None:
    """No beats: "Nothing happened yesterday" only when the ledger held nothing at all that day (recap.quiet); else a
    scoped line: no trades, real bets or alerts on record (practice bets live elsewhere). The date says its zone."""
    _, module = _page(settings)
    recap = _recap()
    quiet = dict(recap, events=[], events_total=0, quiet=True, real=None)
    calm = dict(quiet, quiet=False)
    out = _node(_film(module) + f"""
const quiet = {json.dumps(quiet)}, calm = {json.dumps(calm)}, recap = {json.dumps(recap)};
filmPlay(quiet, false); const a = shot(); run(FILM_EMPTY_S + 0.2); const ended = {{ on: FILM.on, wentLive: wentLive }};
filmPlay(calm, false); const b = shot(); filmStop(true);
simT = 100; filmPlay(recap, false); run(FILM_TITLE_S + 0.2); const pinnedOn = pinned;
pinned = "nyx"; run(0.1);  // the viewer tapped another chip
const taken = {{ on: FILM.on, pinned: pinned, wentLive: wentLive }};
simT = 200; filmPlay(recap, false); run(FILM_TITLE_S + 0.2); filmStop(true);
const closed = {{ on: FILM.on, pinned: pinned, wentLive: wentLive }};
console.log(JSON.stringify({{ quiet: a, ended: ended, calm: b, pinnedOn: pinnedOn, taken: taken, closed: closed }}));
""", tmp_path)
    assert (out["quiet"]["who"], out["quiet"]["text"]) == ("Nothing happened yesterday",
                                                           "Nothing in the bot's ledger for Friday, October 9 (PDT).")
    assert out["quiet"]["note"] is None and out["quiet"]["pinned"] is None
    assert (out["calm"]["who"], out["calm"]["text"]) == ("A quiet day yesterday",
                                                         "No trades, real bets or alerts on record for Friday, October 9 (PDT).")
    assert "America/Los_Angeles" not in out["quiet"]["text"] + out["calm"]["text"]  # the zone's name people know
    assert out["ended"] == {"on": False, "wentLive": 0}  # (nothing was pinned: the live camera never left)
    assert out["pinnedOn"] == "pip"
    assert out["taken"] == {"on": False, "pinned": "nyx", "wentLive": 0}  # the film stops and leaves the viewer's pick alone
    assert out["closed"] == {"on": False, "pinned": None, "wentLive": 1}  # the close button hands back to live


@needs_node
def test_the_film_plays_itself_once_at_five_past_midnight(settings: Settings, tmp_path: Path) -> None:
    """Once per recapped day, 00:05 to 01:00 in the owner's zone by the server's clock, only when the page was already
    open before 00:05, and never over an open panel or the guide (it waits for the next poll)."""
    _, module = _page(settings)
    recap = _recap()
    out = _node(_film(module) + f"""
const recap = {json.dumps(recap)}, w1 = recap.window[1];
const poll = function (now) {{ filmAuto({{ generated_at: now, recap: recap }}); const was = FILM.on; if (FILM.on) {{ filmStop(true); }} return was; }};
const fresh = function () {{ FILM.firstSeen = null; FILM.autoDone = ""; }};
const open = [poll(w1 - 3600), poll(w1 + 120), poll(w1 + 300), poll(w1 + 400)];
fresh(); const late = [poll(w1 + 600), poll(w1 + 900)];
fresh(); const stale = [poll(w1 - 60), poll(w1 + 300 + 3400)];
fresh(); poll(w1 - 60); panelKind = "real"; const busy = poll(w1 + 300); panelKind = null; filmAuto({{ generated_at: w1 + 330, recap: recap }});
const next = FILM.on, auto = FILM.auto; filmStop(true);
fresh(); filmAuto({{ generated_at: w1 - 60, recap: null }}); const noRecap = FILM.firstSeen;
console.log(JSON.stringify({{ open: open, late: late, stale: stale, busy: busy, next: next, auto: auto, noRecap: noRecap }}));
""", tmp_path)
    assert out["open"] == [False, False, True, False]  # open before midnight: plays at 00:05, once
    assert out["late"] == [False, False]  # opened after 00:05: never by itself
    assert out["stale"] == [False, False]  # an hour late: not any more
    assert out["busy"] is False and out["next"] is True and out["auto"] is True
    assert out["noRecap"] is None


@needs_node
def test_the_records_tour_visits_each_board_with_a_fixed_line(settings: Settings, tmp_path: Path) -> None:
    """The "records" chip: each board in turn on its own view (the risk wall, the plaque, the trophy card, the labs,
    the trend desk while it runs), each beat a fixed line on what the board shows; the trend board is skipped while
    the desk is off; the yesterday film and the tour never play at once."""
    _, module = _page(settings)
    out = _node(_film(module) + f"""
data = {{ team: {{ members: [{{ id: "risk", risk_wall: {{ real_caps: {{ on: true }} }} }}] }} }};
tourPlay(); const seen = [];
for (let k = 0; k < 5; k++) {{ untilShown(); seen.push(shot()); run(FILM.script[FILM.i].s); }}
const allViews = views.slice(), done = FILM.on; views.length = 0;
REC_VIEWS.trend.mesh.visible = false; data = null; tourPlay(); const four = FILM.script.length, firstLine = FILM.script[0].text;
filmPlay({json.dumps(_recap())}, false); const switched = {{ kind: FILM.kind, on: FILM.on }}; filmStop(true);
console.log(JSON.stringify({{ seen: seen, views: allViews, done: done, four: four, firstLine: firstLine, switched: switched }}));
""", tmp_path)
    assert out["views"] == ["riskwall", "plaque", "trophies", "labs", "trend"]
    assert [s["who"] for s in out["seen"]] == ["ROOK'S RISK WALL", "THE LEDGER PLAQUE", "THE TROPHY SHELF",
                                               "WHAT THE LABS FOUND", "THE TREND DESK"]
    assert [s["prog"] for s in out["seen"]] == [f"{i} of 5" for i in range(1, 6)]
    assert all(s["tag"] == "THE RECORDS" for s in out["seen"])
    assert "in red, the real-money desk's hard limits" in out["seen"][0]["text"]
    assert out["seen"][4]["text"].startswith("Pretend money:")
    assert out["done"] is False and out["four"] == 4
    assert "in red" not in out["firstLine"]  # no real caps on the wall: no red box promised
    assert out["switched"] == {"kind": "recap", "on": True}
