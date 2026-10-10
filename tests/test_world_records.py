"""The 3D world's record room (world3d's THE RECORD ROOM section): the ledger plaque, the trophy shelf, Rook's risk
wall, the trend and research boards, the postcard and yesterday's film. Each board's drawing runs here in Node over a
recording canvas, so the tests read exactly the words it would paint: the data's own, or the section's fixed copy;
real money only where the data says so; nothing at all for what is missing (never "undefined" or "NaN"). The film
plays a recap through its beats (each beat's words are the event's own), an empty day, the hand-back to the live
director and the 00:05 autoplay; the postcard burns in the real-money line and never the token or the page's
address."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from nightcrawler.config import Settings
from nightcrawler.research_board import research_state
from nightcrawler.world3d import WORLD_CSP, render_world_html
from tests.test_world3d import _js_body, _module, _node

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")

#: a canvas that records what is painted (text and where); measureText: half an em per character
_CANVAS = r"""
const drawn = [];
function makeCtx() {
  return { font: "10px x", fillStyle: "", strokeStyle: "", lineWidth: 1, lineCap: "", textAlign: "", textBaseline: "",
    imageSmoothingQuality: "",
    fillText: function (t, x, y) { drawn.push({ t: String(t), x: x, y: y, font: this.font }); },
    measureText: function (t) { const m = /(\d+(?:\.\d+)?)px/.exec(this.font); return { width: String(t).length * (m ? +m[1] : 10) * 0.5 }; },
    createLinearGradient: function () { return { addColorStop: function () {} }; },
    fillRect: function () {}, strokeRect: function () {}, beginPath: function () {}, arc: function () {}, fill: function () {},
    stroke: function () {}, moveTo: function () {}, lineTo: function () {}, drawImage: function () {} };
}
function canvas(w, h) { const ctx = makeCtx(); return { width: w, height: h, getContext: function () { return ctx; } }; }
function board(w, h) { return { visible: true, userData: { canvas: canvas(w, h), tex: { needsUpdate: false } } }; }
function roundRect() {}
const TAU = Math.PI * 2;
const clamp = function (v, a, b) { return Math.min(b, Math.max(a, v)); };
const texts = function () { return drawn.splice(0).map(function (d) { return d.t; }); };
"""


_DIRECTOR, _LOOP = "= THE LIVE DIRECTOR: an always-on broadcast", "= THE LOOP (paused while the tab is hidden)"


def _section(module: str) -> str:
    start = module.index("THE RECORD ROOM (Builder B)")
    return module[start:module.index(_DIRECTOR)]


def _helpers(module: str) -> str:
    """The module's own money words and number test, and the section's constants and text helpers."""
    sec = _section(module)
    base = "\n".join(_js_body(module, f"function {name}(v) {{") for name in ("fmtUsd", "fmtSigned", "isNum"))
    consts = sec[sec.index("  const REC = {"):sec.index("  function recFit(")]
    helpers = "\n".join(_js_body(sec, f"  function {name}(") for name in ("recFit", "recWrap", "recSized", "recCount", "recEngrave"))
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
    """The section sits before the live director (it only uses the director's pin), runs from THE LOOP once a frame,
    keeps its CSS in the page's one <style> (hashed by the CSP) and offers its hooks on window.__skyport.records."""
    page, module = _page(settings)
    assert module.index("THE RECORD ROOM (Builder B)") < module.index(_DIRECTOR) < module.index(_LOOP)
    loop = _js_body(module, "  function frame(now) {")
    assert loop.count("recFrame();") == 1 and loop.index("recFrame();") < loop.index("render")
    assert page.count("<style>") == 1 and "#postcard" in page and "#film" in page and "body.film #card" in page
    assert "style-src 'sha256-" in WORLD_CSP
    sec = _section(module)
    assert "window.__skyport = Object.assign(window.__skyport || {}, { records: {" in sec
    for hook in ("film: { play:", "seek: function (t, hold)", "postcard: { take:", "shelf: function ()"):
        assert hook in sec, hook
    assert "innerHTML" not in sec and "eval(" not in sec and "localStorage" not in sec


def test_the_record_room_allocates_nothing_in_its_frame_step(settings: Settings) -> None:
    """recFrame redraws only when a new poll landed (the data object changed); the film's step only compares numbers;
    the one element it ever makes (the "yesterday" chip) is made once."""
    _, module = _page(settings)
    frame = _js_body(module, "  function recFrame() {")
    assert "if (data !== REC.seen) { REC.seen = data; if (data) recApply(data); }" in frame
    assert "if (!REC.chip && chipEls.length) {" in frame and frame.count("createElement") == 1
    assert "JSON" not in frame
    step = _js_body(module, "  function filmStep() {")
    for word in ("new ", "JSON", "[", "function ("):
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
 {{ count: 1, verified: null, first_bad_seq: null, head: null, head_short: null }}, null].forEach(function (rc) {{
  recDrawPlaque(rc); runs.push(Array.from(new Set(texts()))); }});
console.log(JSON.stringify(runs));
""", tmp_path)
    fixed = ["THE LEDGER", "each record is sealed to the one before it"]
    assert out[0] == ["THE LEDGER", "5 sealed receipts · verified", "head abababab…abababab", fixed[1]]
    assert "12 sealed receipts · first bad entry #7" in out[1] and "head cdcdcdcd…cdcdcdcd" in out[1]
    assert "1 sealed receipt · not checked yet" in out[2]
    assert out[3] == ["THE LEDGER", "no records yet", "", fixed[1]]


@needs_node
def test_rooks_risk_wall_reads_only_the_api_numbers_and_survives_nulls(settings: Settings, tmp_path: Path) -> None:
    """The gauges come from team.members[risk].risk_wall and its real_caps; with nothing (or half a wall) the wall
    says so in words; a paused day and the real desk's caps (open $ vs $10, today's loss vs $3, total vs $10)."""
    _, module = _page(settings)
    sec = _section(module)
    draw = _js_body(sec, "  function recDrawWall(wall, caps, label) {")
    tables = _line(sec, "  const REC_STOPS = ") + "\n" + _line(sec, "  const REC_VERDICT = ")
    out = _node(_helpers(module) + f"""
const recWall = board(1024, 720);
{tables}
{_js_body(sec, "  function recBar(")}
{draw}
const paused = {{ allowance_used_pct: 104.0, slots_used: 3, slots_max: 3, daily_stop: true, stopped_by: "daily_loss",
  desks: [{{ desk: "Polymarket paper", verdict: "losing", paused: true }}, {{ desk: "Polymarket real", verdict: "learning", paused: false }}] }};
const caps = {{ label: "Real money", on: true, open_usd: 4.82, open_max_usd: 10, day_loss_usd: 0.97, day_max_usd: 3,
  total_loss_usd: 2.52, total_max_usd: 10 }};
const runs = [];
recDrawWall(null, null, undefined); runs.push(texts());
recDrawWall({{}}, null, "Paper money (pretend)"); runs.push(texts());
recDrawWall({{ allowance_used_pct: null, slots_used: null, slots_max: null, daily_stop: null, desks: null }}, null, null); runs.push(texts());
recDrawWall(paused, caps, "Paper money (pretend)"); runs.push(texts());
recDrawWall(paused, Object.assign({{}}, caps, {{ on: false }}), "Paper money (pretend)"); runs.push(texts());
console.log(JSON.stringify(runs));
""", tmp_path)
    for run in out:
        assert not any(bad in t for t in run for bad in ("undefined", "NaN", "null", "[object")), run
    empty = out[0]
    for words in ("ROOK'S RISK WALL", "—", "no money check yet today", "Trade slots: 0 of 0 in use", "Daily stop: not known yet",
                  "no desk to judge", "Real money: no real-money bets on record."):
        assert words in empty, words
    assert out[1] == [t if t != "Solana bot · " else "Solana bot · Paper money (pretend)" for t in empty]
    assert out[2] == empty
    full = out[3]
    for words in ("Solana bot · Paper money (pretend)", "104%", "of today's loss allowance", "Trade slots: 3 of 3 in use",
                  "Daily stop: ON, no new buys today", "New buys stopped: today's loss limit", "Polymarket paper",
                  "losing · new buys paused", "Polymarket real", "learning", "Real money · the Polymarket desk's hard limits",
                  "In open bets", "$4.82 of $10.00", "Lost today (UTC)", "$0.97 of $3.00", "Lost in total", "$2.52 of $10.00"):
        assert words in full, words
    assert "Real money · the Polymarket desk's hard limits (no new real bets now)" in out[4]


@needs_node
def test_the_trophy_shelf_counts_each_result_newest_nearest_mote(settings: Settings, tmp_path: Path) -> None:
    """One trophy per win and one tile per loss (grey if even), the real bets on the top tier, the practice trades
    inside, newest at the left end (nearest Mote); what does not fit is "+N more"; the card says which shelf is real
    and lists the last five results, each tagged REAL or pretend."""
    _, module = _page(settings)
    sec = _section(module)
    out = _node(_helpers(module) + f"""
{_line(sec, "  const SHELF = ")}
const slots = [];
const inst = function () {{ return {{ count: 0, instanceMatrix: {{}}, instanceColor: {{}}, colours: [], setColorAt: function (i, c) {{ this.colours[i] = c; }} }}; }};
const recTrophies = inst(), recTiles = inst(), REC_LOSS = "loss", REC_EVEN = "even";
const recSlot = function (im, i, x, y, tilt) {{ slots.push({{ kind: im === recTrophies ? "W" : "T", i: i, x: x, y: y }}); }};
const recCard = board(1024, 704);
{_js_body(sec, "  function recDrawShelf(sum, closed) {")}
{_js_body(sec, "  function recLatest(sum, closed) {")}
let order = ""; for (let i = 0; i < 180; i++) order += "WLLE"[i % 4];
const sum = {{ label: "Paper money (pretend)", won: 45, lost: 90, even: 45, total: 230, since: 1, order: order,
  real: {{ label: "Real money", won: 1, lost: 2, settled: 3, since: 1, order: "LWL",
    lines: [{{ ts: 300, won: false, text: "REAL · lost −$0.97 · Will the Fed cut rates?" }}, {{ ts: 100, won: true, text: "REAL · won +$0.03 · Rain in Athens?" }}] }} }};
const closed = [{{ coin: "HIGGS", closed_at: 200, pnl_usd: 2.13, result: "won", why: "Took profit" }},
  {{ coin: "PY", closed_at: 50, pnl_usd: -1.5, result: "lost", why: "Stop-loss: cut the loss" }},
  {{ coin: "OLD", closed_at: 10, pnl_usd: 0.1, result: "won", why: "" }}, {{ coin: "OLDER", closed_at: 5, pnl_usd: 0.1, result: "won", why: "" }}];
recDrawShelf(sum, closed);
const card = texts(), first = slots.slice(), counts = [recTrophies.count, recTiles.count], shown = Object.assign({{}}, REC.shelf);
const colours = recTiles.colours.slice(0, recTiles.count), latest = REC.lines.slice();
slots.length = 0; recDrawShelf(null, null);
console.log(JSON.stringify({{ card: card, counts: counts, shown: shown, slots: first, colours: colours, latest: latest,
  none: texts(), noneCounts: [recTrophies.count, recTiles.count], shelf: SHELF }}));
""", tmp_path)
    shelf, slots = out["shelf"], out["slots"]
    shown_pretend = shelf["tierCap"] * shelf["tiers"]
    assert out["shown"] == {"real": 3, "pretend": shown_pretend, "realMore": 0, "pretendMore": 230 - shown_pretend}
    pretend = "".join("WLLE"[i % 4] for i in range(shown_pretend))
    assert out["counts"] == [1 + pretend.count("W"), 2 + pretend.count("L") + pretend.count("E")]
    assert out["colours"].count("even") == pretend.count("E") and out["colours"].count("loss") == 2 + pretend.count("L")
    # the newest result is the leftmost slot of its tier (Mote's end), the next one a step to the right
    top, inner = slots[:3], slots[3:5]  # (the real bets first, then the practice trades, each newest first)
    assert [s["x"] for s in top] == pytest.approx([shelf["realX0"] + (i + 0.5) * shelf["step"] for i in range(3)])
    assert all(s["y"] == pytest.approx(shelf["topY"], abs=0.03) for s in top)
    assert [s["kind"] for s in top] == ["T", "W", "T"]  # "LWL": the newest (a loss) at the left
    assert inner[0]["x"] == pytest.approx(shelf["x0"] + 0.5 * shelf["step"]) and inner[1]["x"] > inner[0]["x"]
    assert all(s["y"] == pytest.approx(shelf["tierY"][0], abs=0.03) for s in inner)
    card = out["card"]
    for words in ("THE TROPHY SHELF", "Top: Real money · Polymarket bets", "1 won · 2 lost",
                  "Inside: Paper money (pretend) · Solana bot trades", f"45 won · 90 lost · 45 even · +{230 - shown_pretend} more",
                  "Latest results"):
        assert words in card, words
    assert [line["text"] for line in out["latest"]] == [
        "REAL · lost −$0.97 · Will the Fed cut rates?", "pretend · HIGGS won +$2.13 · Took profit",
        "REAL · won +$0.03 · Rain in Athens?", "pretend · PY lost −$1.50 · Stop-loss: cut the loss", "pretend · OLD won +$0.10"]
    assert [line["real"] for line in out["latest"]] == [True, False, True, False, False]
    assert out["noneCounts"] == [0, 0]
    assert "real money: no real bets on record" in " ".join(out["none"]) and "No trade or real bet has finished yet." in out["none"]


@needs_node
def test_the_labs_board_is_the_fixed_research_table(settings: Settings, tmp_path: Path) -> None:
    """"What the labs found": each lab's verdict chip (NO EDGE / PROMISING), its question, its counted trials and
    reading; the total of trials and the rule; "Not in this version." without the block."""
    _, module = _page(settings)
    sec = _section(module)
    research = research_state()
    out = _node(_helpers(module) + f"""
const recLabs = board(1024, 768);
{_line(sec, "  const REC_LAB_COLOUR = ")}
{_js_body(sec, "  function recDrawLabs(res) {")}
recDrawLabs({json.dumps(research)}); const full = texts();
recDrawLabs(null); const none = texts();
console.log(JSON.stringify({{ full: full, none: none }}));
""", tmp_path)
    full = out["full"]
    assert full[0] == "What the labs found"
    for lab in research["labs"]:
        assert lab["lab"] in full and lab["verdict"] in full
        assert any(t.startswith(f"{lab['trials']:,} trial") for t in full), lab["lab"]
    assert {lab["verdict"] for lab in research["labs"]} <= {"NO EDGE", "PROMISING"}
    assert full[-1] == f"{research['trials_total']:,} trials counted · {research['rule']}"
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
                  "Pretend money: practice only, lab 3's rule tested forward"):
        assert words in on["texts"], words
    assert on["texts"].count("IN") == 2 and on["texts"].count("OUT") == 1
    assert "First booking at the close of 2026-10-07 (UTC midnight)" in out["first"]
    assert out["off"] == {"texts": [], "board": False, "screen": True}


# --------------------------------------------------------------------------- the postcard


@needs_node
def test_the_postcard_burns_in_the_real_line_and_never_the_token_or_address(settings: Settings, tmp_path: Path) -> None:
    """The frame plus the real-money line (plain.real's own result and money in bets, red while it is on), the
    practice line, the time and the fixed footer; the share sheet gets the picture alone, a file name without the
    address; the section never reads the token or the page's location."""
    _, module = _page(settings)
    sec = _section(module)
    assert re.search(r"\btoken\b", sec) is None and "location" not in sec and "params" not in sec
    assert 'navigator.share({ files: [file], title: "nightcrawler" })' in sec
    out = _node(_helpers(module) + f"""
const document = {{ createElement: function () {{ const ctx = makeCtx(); return {{ width: 0, height: 0, getContext: function () {{ return ctx; }} }}; }} }};
const composer = null, scene = {{}}, camera = {{}};
const renderer = {{ domElement: {{ width: 780, height: 1688 }}, render: function () {{}} }};
{_js_body(module, "  function realWords(r) {")}
{_line(sec, "  const REC_FOOT = ")}
{_js_body(sec, "  function recRealLine(r) {")}
{_js_body(sec, "  function recPostcardLines(now) {")}
{_js_body(sec, "  function recPostcard(now) {")}
{_js_body(sec, "  function recFileName(now) {")}
let plain = {{ real: {{ label: "Real money", on: true, reported: true, at_risk_usd: 4.82, open_bets: 5, result: "down $2.52 since start" }},
  pretend: {{ line: "Practice (pretend money): the Solana bot is down $5.50 since start; Polymarket practice bets have not finished a round yet." }} }};
const when = new Date(2026, 9, 10, 8, 39);
const c = recPostcard(when), on = {{ size: [c.width, c.height], texts: texts(), lines: REC.postcardLines, red: recPostcardLines(when).red }};
plain = {{ real: {{ label: "Real money", on: false, reported: false }}, pretend: {{ line: "Practice (pretend money): nothing yet." }} }};
const off = recPostcardLines(when); recPostcard(when); const offTexts = texts();
plain = null; const none = recPostcardLines(when);
console.log(JSON.stringify({{ on: on, off: off, offTexts: offTexts, none: none, name: recFileName(when) }}));
""", tmp_path)
    on = out["on"]
    assert on["size"] == [round(780 * 1600 / 1688), 1600]  # (no larger than 1600 px)
    assert on["lines"]["real"] == "Real money: down $2.52 since start · $4.82 in bets" and on["red"] is True
    painted = " ".join(on["texts"])
    assert on["texts"][0] == on["lines"]["real"]
    assert "Practice (pretend money): the Solana bot is down $5.50" in painted
    assert "nightcrawler · a visualisation of the bot's own ledger" in painted and on["lines"]["when"] in painted
    assert out["off"]["real"] == "Real money: no report yet" and out["off"]["red"] is False
    assert out["none"]["real"] == "Real money: not in this version"
    assert out["none"]["practice"] == "Practice (pretend money): not in this version"
    for text in on["texts"] + out["offTexts"]:
        for bad in ("token", "http", "/world", "?", "127.0.0.1", "undefined"):
            assert bad not in text, (bad, text)
    assert out["name"] == "nightcrawler-postcard-20261010-0839.png"


# --------------------------------------------------------------------------- yesterday's film

_FILM_STUBS = r"""
const el = function (tag) { return { tag: tag, hidden: false, className: "", textContent: "", style: {}, children: [], attrs: {},
  appendChild: function (c) { this.children.push(c); }, setAttribute: function (k, v) { this.attrs[k] = v; } }; };
const document = { createElement: el };
const bodyCls = new Set(), body = { appendChild: function () {}, classList: { add: function (c) { bodyCls.add(c); }, remove: function (c) { bodyCls.delete(c); } } };
const card = { getBoundingClientRect: function () { return { bottom: 700 }; } }, window = { innerHeight: 800 };
const guideEl = { hidden: true }; let panelKind = null, simT = 0, pinned = null, wentLive = 0;
const closePanel = function () {}, closeGuide = function () {};
const pins = [];
const PLANNER = { pin: function (k, t, angle) { pins.push([k, angle == null ? null : angle]); pinned = k; } };
const togglePin = function (k) { pinned = pinned === k ? null : k; if (pinned) pins.push([k, null]); };
const goLive = function () { pinned = null; wentLive += 1; };
const actorOf = { judge: "voss", predict: "voss", broker: "jet", risk: "rook", receipts: "mote", crawler: "pip" };
const CAST = { voss: { name: "Voss" }, jet: { name: "Jet" }, rook: { name: "Rook" }, mote: { name: "Mote" }, pip: { name: "Pip" } };
const nameOf = function (m) { return m; };
const plain = { jobs: { judge: "bets on yes/no questions at Polymarket", broker: "places the Solana bot's trades" } };
"""


def _film(module: str) -> str:
    sec = _section(module)
    block = sec[sec.index("  const FILM = {"):sec.index("once a frame (from THE LOOP)")]
    return _helpers(module) + _FILM_STUBS + block[:block.rindex("\n")] + "\n"


def _recap() -> dict[str, Any]:
    tz = ZoneInfo("America/Los_Angeles")
    w0 = int(datetime(2026, 10, 9, tzinfo=tz).timestamp())
    events = [{"ts": w0 + 3600 * (i + 1) + 1800, "member": member, "text": text, "tone": tone} for i, (member, text, tone) in enumerate([
        ("crawler", "found a new coin: FIRST (70 min old)", "neutral"),
        ("predict", "real-money bet: $0.97 on YES · Will the Fed cut rates at the December meeting?", "neutral"),
        ("broker", "bought HIGGS for 0.1000 SOL (pretend money)", "neutral"),
        ("risk", "refused to buy RISKY: Too many open trades: 3 open", "bad"),
        ("predict", "a real-money bet lost $0.97 · Will the Fed cut rates at the December meeting?", "bad"),
        ("broker", "HIGGS: Sold after the price fell from its high · won +$2.13 (pretend money)", "good"),
        ("receipts", "sealed record #3 in the tamper-proof log", "neutral"),
        ("coach", "tested the playbook again: no change", "neutral"),
        ("predict", "a real-money bet won $0.03 · Will it rain in Athens on Saturday?", "good"),
        ("crawler", "found a new coin: LAST (12 min old)", "neutral")])]
    return {"date": "2026-10-09", "tz": "America/Los_Angeles", "window": [w0, w0 + 86400], "events": events, "events_total": 214,
            "closed": [], "real": {"label": "Real money", "start_usd": -1.2, "end_usd": -2.52, "settled": 4, "won": 1,
                                   "line": "Real money: down $1.20 since start when the day began, down $2.52 since start when it ended; 1 of 4 finished bets won."},
            "pretend": {"label": "Practice (pretend money)", "line": "Practice (pretend money): the Solana bot ended the day down $5.50."}}


@needs_node
def test_the_film_plays_each_beat_with_the_events_own_words(settings: Settings, tmp_path: Path) -> None:
    """A title card, one beat per event (the director pinned on whoever made it, the event's own words, its time in the
    owner's zone), the vault with real money's start and end and the practice line, then back to live; the same
    beat's frame holds while the film is held (the screenshot hook)."""
    _, module = _page(settings)
    recap = _recap()
    out = _node(_film(module) + f"""
const recap = {json.dumps(recap)};
const shot = function () {{ return {{ phase: FILM.phase, tag: filmTag.textContent, prog: filmProg.textContent, who: filmWho.textContent,
  text: filmText.textContent, real: filmReal.hidden ? null : filmReal.textContent, pretend: filmPretend.hidden ? null : filmPretend.textContent,
  note: filmNote.hidden ? null : filmNote.textContent, cls: filmEl.className, pinned: pinned, film: bodyCls.has("film") }}; }};
const played = filmPlay(recap, false), frames = [shot()];
for (let i = 0; i < 10; i++) {{ simT = FILM_TITLE_S + i * FILM.beat + 0.5; filmStep(); frames.push(shot()); }}
simT = FILM_TITLE_S + 10 * FILM.beat + 1; filmStep(); frames.push(shot());
const pinsAtEnd = pins.slice();
simT = FILM_TITLE_S + 10 * FILM.beat + FILM_END_S + 0.1; filmStep();
const after = {{ on: FILM.on, pinned: pinned, wentLive: wentLive, film: bodyCls.has("film"), hidden: filmEl.hidden }};
// held: the frame stays on beat 3 however long the screenshot takes
filmPlay(recap, false); FILM.hold = FILM_TITLE_S + 2 * FILM.beat + 0.5; simT = 1000; filmStep(); const heldA = FILM.phase;
simT = 2000; filmStep(); const heldB = FILM.phase; filmStop(true);
console.log(JSON.stringify({{ played: played, frames: frames, after: after, pins: pinsAtEnd, held: [heldA, heldB], beat: FILM.beat }}));
""", tmp_path)
    assert out["played"] is True
    frames = out["frames"]
    title, beats, closing = frames[0], frames[1:11], frames[11]
    assert title["phase"] == -1 and title["tag"] == "YESTERDAY" and title["who"] == "Friday, October 9"
    assert title["text"] == "What the team did, from its own records: 10 moments of 214 records." and title["film"] is True
    assert [b["text"] for b in beats] == [e["text"] for e in recap["events"]]  # the event's own words, in order
    assert [b["prog"] for b in beats] == [f"{i} of 10" for i in range(1, 11)]
    assert [b["pinned"] for b in beats] == ["pip", "voss", "jet", "rook", "voss", "jet", "mote", "observatory", "voss", "pip"]
    assert beats[0]["tag"].startswith("YESTERDAY · ") and "01:30" in beats[0]["tag"] and "PDT" in beats[0]["tag"]
    assert beats[1]["who"] == "VOSS" and beats[2]["who"] == "JET · places the Solana bot's trades"
    assert [b["cls"] for b in beats][3:6] == ["bad", "bad", "good"]
    assert all(b["real"] is None and b["pretend"] is None for b in beats)
    assert closing["phase"] == 98 and closing["pinned"] == "vaultsign" and closing["who"] == "How the day ended"
    assert closing["real"] == recap["real"]["line"] and closing["pretend"] == recap["pretend"]["line"] and closing["cls"] == "real"
    assert out["pins"][-1] == ["vaultsign", 1]  # the closing shot asks the director for the push from the door
    assert out["after"] == {"on": False, "pinned": None, "wentLive": 1, "film": False, "hidden": True}
    assert out["held"] == [2, 2]
    assert 4 <= out["beat"] <= 6


@needs_node
def test_an_empty_day_says_nothing_happened_and_the_viewer_can_take_the_camera(settings: Settings, tmp_path: Path) -> None:
    _, module = _page(settings)
    recap = _recap()
    empty = dict(recap, events=[], events_total=0, real=None,
                 pretend={"label": "Practice (pretend money)", "line": "Practice (pretend money): the Solana bot had no money check that day."})
    out = _node(_film(module) + f"""
const empty = {json.dumps(empty)}, recap = {json.dumps(recap)};
filmPlay(empty, false);
const title = {{ who: filmWho.textContent, text: filmText.textContent, note: filmNote.hidden, pinned: pinned }};
simT = FILM_EMPTY_S + 0.1; filmStep(); const ended = {{ on: FILM.on, wentLive: wentLive }};
simT = 100; filmPlay(recap, false); simT = 100 + FILM_TITLE_S + 0.5; filmStep(); const pinnedOn = pinned;
pinned = "nyx"; simT += 0.1; filmStep();  // the viewer tapped another chip
const taken = {{ on: FILM.on, pinned: pinned, wentLive: wentLive }};
simT = 200; filmPlay(recap, false); simT = 200 + FILM_TITLE_S + 0.5; filmStep(); filmStop(true);
const closed = {{ on: FILM.on, pinned: pinned, wentLive: wentLive }};
console.log(JSON.stringify({{ card: title, ended: ended, pinnedOn: pinnedOn, taken: taken, closed: closed }}));
""", tmp_path)
    assert out["card"] == {"who": "Nothing happened yesterday", "text": "Friday, October 9 (America/Los_Angeles): the bot recorded nothing that day.",
                           "note": True, "pinned": None}
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
fresh(); poll(w1 - 60); panelKind = "real"; const busy = poll(w1 + 300); panelKind = null; const next = poll(w1 + 330);
fresh(); filmAuto({{ generated_at: w1 - 60, recap: null }}); const noRecap = FILM.firstSeen;
console.log(JSON.stringify({{ open: open, late: late, stale: stale, busy: busy, next: next, auto: FILM.auto, noRecap: noRecap }}));
""", tmp_path)
    assert out["open"] == [False, False, True, False]  # open before midnight: plays at 00:05, once
    assert out["late"] == [False, False]  # opened after 00:05: never by itself
    assert out["stale"] == [False, False]  # an hour late: not any more
    assert out["busy"] is False and out["next"] is True and out["auto"] is True
    assert out["noRecap"] is None
