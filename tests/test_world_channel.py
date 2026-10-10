"""The 3D world's channel: ``/api/page.plain.ticker`` and ``plain.finished`` (nightcrawler.pagestate) and
the world's THE CHANNEL section (nightcrawler.world3d): the ticker in plain words, a replay only for something that
really finished (a closed trade, a settled REAL-money bet), the day-night cycle, the market's weather from real money
only, the sound off until the speaker is tapped (no AudioContext before), nothing allocated per frame, and the section
kept to itself (its own CSS block, the page's bus, hooks on ``window.__skyport``). The pure block runs in Node."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock
from test_page import JARGON, NOW, live_settings, seed
from test_page_polymarket import desk_state, save
from test_plain import owner_state
from test_world3d import _js_body, _module, _node

from nightcrawler.config import Settings
from nightcrawler.ledger import Ledger
from nightcrawler.office3d import CAST3D
from nightcrawler.pagestate import (
    PLAIN_FINISHED_MAX,
    PLAIN_TICKER_MAX,
    PLAIN_TICKER_WINDOW_S,
    build_page_state,
    plain_event,
    plain_finished,
    plain_ticker,
)
from nightcrawler.world3d import _STYLE_CHANNEL, WORLD_CSP, render_world_html

NODE = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
ACTOR_OF = {m: key for key, spec in CAST3D.items() for m in spec["members"]}  # type: ignore[union-attr]


@pytest.fixture
def ledger(tmp_path: Path, fake_clock: FakeClock) -> Iterator[Ledger]:
    with Ledger(tmp_path / "nc.db", clock=fake_clock) as led:
        yield led


def page(ledger: Ledger, settings: Settings) -> dict[str, Any]:
    state: dict[str, Any] = build_page_state(ledger, settings, NOW)
    json.dumps(state, allow_nan=False)
    return state


def member(mid: str, *events: tuple[float, str, str]) -> dict[str, Any]:
    return {"id": mid, "events": [{"ts": ts, "text": text, "tone": tone} for ts, text, tone in events]}


# --------------------------------------------------------------------------- the API: plain.ticker


def test_the_ticker_is_the_teams_last_events_in_plain_words(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)  # coins found, checked and judged, a trade bought (paper)
    save(settings, owner_state())  # the desk live: a real-money buy 30 s ago
    state = page(ledger, settings)
    ticker = state["plain"]["ticker"]
    assert 0 < len(ticker) <= PLAIN_TICKER_MAX == 8
    assert [t["ts"] for t in ticker] == sorted((t["ts"] for t in ticker), reverse=True)  # newest first
    raw = {(ACTOR_OF[m["id"]], plain_event(m["id"], e["text"])): e for m in state["team"]["members"]
           if m["id"] in ACTOR_OF for e in m["events"]}
    for t in ticker:
        assert set(t) == {"ts", "who", "name", "text", "tone"} and t["name"] == CAST3D[t["who"]]["name"]
        event = raw[(t["who"], t["text"])]  # the server's own plain words for a real event of that character
        assert t["ts"] == event["ts"] and t["tone"] == (event["tone"] if event["tone"] in ("good", "bad") else "neutral")
        assert not JARGON.search(t["text"]) and "paper" not in t["text"].lower()
    assert ticker[0] == {"ts": NOW - 30, "who": "voss", "name": "Voss", "tone": "good",
                         "text": "real-money bet: $0.95 on YES · Will it rain in Athens today?"}
    assert not [t for t in ticker if t["text"].startswith("sealed record")]  # the receipts' own log is left out


def test_the_ticker_keeps_a_day_eight_rows_and_each_words_once() -> None:
    old, future = NOW - PLAIN_TICKER_WINDOW_S - 1, NOW + 3600
    members = [
        member("crawler", *[(NOW - 10 * (i + 1), f"COIN{i} · {i}.0 min old", "neutral") for i in range(6)], (old, "OLD · 9 h old", "neutral")),
        member("risk", (NOW - 5, "REFUSED WIF · too many open", "bad"), (NOW - 7, "REFUSED WIF · too many open", "bad")),
        member("receipts", (NOW - 1, "#9 decision: watch · 0a1b2c3d", "neutral")),
        member("predict", (future, "Lesson: from the future", "good"), (NOW - 3, "Lesson: size weather bets smaller", "great")),
        member("nobody", (NOW - 2, "who is this", "good")),
    ]
    out = plain_ticker(members, NOW, live=False)
    assert len(out) == 8 and [t["ts"] for t in out] == sorted((t["ts"] for t in out), reverse=True)
    texts = [t["text"] for t in out]
    assert texts.count("refused to buy WIF: too many open") == 1  # the same words once
    assert "Lesson: from the future" not in texts and "found a new coin: OLD (9 h old)" not in texts
    assert not [t for t in texts if "sealed record" in t or t == "who is this"]
    assert out[0] == {"ts": NOW - 3, "who": "voss", "name": "Voss", "text": "Lesson: size weather bets smaller",
                      "tone": "neutral"}  # (an unknown tone: neutral)
    assert out[1] == {"ts": NOW - 5, "who": "rook", "name": "Rook", "text": "refused to buy WIF: too many open", "tone": "bad"}
    assert [t["who"] for t in out[2:]] == ["pip"] * 6


# --------------------------------------------------------------------------- the API: plain.finished


def test_finished_lists_closed_trades_and_settled_real_money_bets_only(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)  # two closed trades (paper): P2 won a day ago, P3 lost 8000 s ago
    st = desk_state()
    st["events"] = [
        {"ts": NOW - 40, "text": "Settled: Will x happen? · lost -20.03 $ (paper)", "tone": "bad"},  # practice: never replayed
        {"ts": NOW - 50, "text": "Settled: Will y happen? · won +0.02 $ (real)", "tone": "good"},
    ]
    save(settings, st)
    state = page(ledger, settings)
    finished = state["plain"]["finished"]
    assert len(finished) <= PLAIN_FINISHED_MAX == 3
    rows = {r["coin"]: r for r in state["trades"]["closed"]}
    assert finished == [
        {"id": f"bet|{NOW - 50:.3f}|Will y happen?", "ts": NOW - 50, "who": "voss", "what": "Will y happen?",
         "result": "won", "usd": 0.02, "real": True, "money": "real money"},
        {"id": f"trade|P3|{NOW - 8000:.3f}", "ts": NOW - 8000, "who": "jet", "what": "P3", "result": "lost",
         "usd": round(abs(rows["P3"]["pnl_usd"]), 2), "real": False, "money": "pretend"},
        {"id": f"trade|P2|{NOW - 86_400 + 3600:.3f}", "ts": NOW - 86_400 + 3600, "who": "jet", "what": "P2",
         "result": "won", "usd": round(abs(rows["P2"]["pnl_usd"]), 2), "real": False, "money": "pretend"},
    ]
    assert page(ledger, settings)["plain"]["finished"] == finished  # the same ids poll after poll: replayed once


def test_nothing_is_finished_without_a_real_event(ledger: Ledger, settings: Settings) -> None:
    assert page(ledger, settings)["plain"]["finished"] == []  # an empty ledger, no desk
    st = desk_state()
    st["events"] = [{"ts": NOW - 40, "text": "Settled: Will x happen? · won +1.03 $ (paper)", "tone": "good"},
                    {"ts": NOW - 30, "text": "REAL buy: Will z? · 1 contract at 0.950 ($0.95, weather)", "tone": "good"}]
    save(settings, st)
    assert page(ledger, settings)["plain"]["finished"] == []  # a practice settlement and a buy are not finished real bets
    real = member("predict", (NOW - 5, "Settled: Will y happen? · lost -0.97 $ (real)", "bad"))
    assert plain_finished([real], [], live=False, desk_on=False) == []  # the desk off: its events say nothing
    assert plain_finished([real], None, live=False, desk_on=True)[0]["result"] == "lost"
    junk = [{"coin": "X", "closed_at": None, "result": "won"}, {"coin": "", "closed_at": NOW, "result": "won"},
            {"coin": "Y", "closed_at": NOW, "result": "maybe"}]
    assert plain_finished([], junk, live=False, desk_on=True) == []


def test_a_live_solana_bot_finishes_real_money_trades(ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    seed(ledger, mode="live")
    finished = page(ledger, live_settings(make_settings))["plain"]["finished"]
    assert finished and all(f["who"] == "jet" and f["real"] is True and f["money"] == "real money" for f in finished)


# --------------------------------------------------------------------------- the world: the page and its section


def _channel(module: str) -> str:
    start = module.index("// ============================================================= THE CHANNEL")
    return module[start:module.index("// ============================================================= THE LIVE DIRECTOR")]


def _pure(module: str) -> str:
    return module[module.index("// >>> channel (pure)"):module.index("// <<< channel")]


def test_the_channel_keeps_to_its_own_section(settings: Settings) -> None:
    html = render_world_html(settings)
    module = re.sub(r"//[^\n]*", "", _module(html))  # (the code: comments may name what they talk about)
    section = _channel(_module(html))
    code = re.sub(r"//[^\n]*", "", section)
    # the page's bus, emitted at three places only; the director and the fps governor are untouched
    assert module.count('BUS.emit("data", d, first);') == 1 and module.count('BUS.emit("frame", dt, dtRaw);') == 1
    assert module.count('BUS.emit("start", 0, 0);') == 1 and module.count("BUS.emit(") == 3
    assert "function director() { liveDirector(); }" in module and "govern(dtRaw);" in module
    for foreign in ("liveDirector(", "PLANNER.", "startShot(", "govern(", "setFov("):
        assert foreign not in code, foreign
    # its hooks: window.__skyport from this section only, the director's own debug handle unchanged
    assert module.count("window.__skyport") == 2 == code.count("window.__skyport")  # (SKY = window.__skyport = ... || {})
    assert module.count("window.__world") == 1
    # the old once-a-minute tint is gone: the channel's cycle owns the sky
    assert "function tint()" not in module and "setInterval(tint" not in module
    # its own CSS block, in the one hashed style
    (style,) = re.findall(r"<style>(.*?)</style>", html, flags=re.DOTALL)
    assert style.endswith(_STYLE_CHANNEL) and "#ticker {" not in style[:-len(_STYLE_CHANNEL)]
    assert "'sha256-" in WORLD_CSP and "'unsafe-inline'" not in WORLD_CSP
    # the speaker sits in the bar before "?", the ticker just above the honesty line, the banner with the overlay
    head = html[html.index('<header id="bar">'):html.index("</header>")]
    assert head.index('id="sound"') < head.index('id="help"') and 'aria-pressed="false"' in head
    assert html.index('<div id="ticker"') < html.index('<p id="honest">') and 'id="replay" role="status"' in html
    assert "innerHTML" not in html and "insertAdjacentHTML" not in html


def test_the_ticker_sits_on_one_line_above_the_honesty_line() -> None:
    def px(rule: str, prop: str = "bottom") -> float:
        found = re.search(re.escape(rule) + r" \{[^}]*?" + prop + r": calc\((\d+)px", _STYLE_CHANNEL)
        assert found is not None, rule
        return float(found.group(1))

    height = float(re.search(r"#ticker \{[^}]*?height: (\d+)px", _STYLE_CHANNEL).group(1))  # type: ignore[union-attr]
    honest, ticker, chips, card = px("body.ticker #honest"), px("#ticker"), px("body.ticker #chips"), px("body.ticker #card, body.ticker #guide")
    assert honest + 15 <= ticker and ticker + height + 2 <= chips and chips + 32 + 6 <= card  # (the honesty line is 15 px)
    rule = _STYLE_CHANNEL[_STYLE_CHANNEL.index("#ticker {"):]
    assert "white-space: nowrap" in rule[:rule.index("}")] and "overflow: hidden" in rule[:rule.index("}")]  # never two lines
    assert "body.tab-hidden #ticker-track { animation-play-state: paused; }" in _STYLE_CHANNEL  # paused when hidden
    assert "@media (prefers-reduced-motion: reduce) { #ticker-track.roll { animation: none; } }" in _STYLE_CHANNEL


def test_the_ticker_and_the_banner_write_text_only(settings: Settings) -> None:
    section = _channel(_module(render_world_html(settings)))
    assert "innerHTML" not in section and "insertAdjacentHTML" not in section and "fillText" not in section
    row = _js_body(section, "    function tickerRow(it, nowMs) {")
    assert "when.textContent = p.when; who.textContent = p.who;" in row and "document.createTextNode(p.text)" in row
    render = _js_body(section, "    function renderTicker(d) {")
    assert "d.plain.ticker" in render and ".slice(0, 8)" in render  # the server's plain words, eight at most
    show = _js_body(section, "    function showReplay(it) {")
    assert "replayWhat.textContent = w.what; replayOutcome.textContent = w.outcome; replayMoney.textContent = w.money;" in show
    # the queue is filled only from plain.finished's newly listed items, and only the queue shows a banner
    assert section.count("replayQueue.push(") == 1 and "replayQueue.push(fresh[i])" in section
    assert "freshFinished(replayMemo, d && d.plain ? d.plain.finished : null)" in section
    assert section.count("showReplay(") == 2 and "showReplay(replayQueue.shift())" in section
    # six seconds on the wall clock (the world's own time slows on a slow screen and stops offline), one at a time
    assert "const REPLAY_MS = 6000" in section and "replayUntil = performance.now() + REPLAY_MS;" in show
    assert 'if (replayUntil && wall >= replayUntil) { replayUntil = 0; replayEl.className = ""; replayGap = wall + 600; }' in section


def test_the_sound_waits_for_the_speaker(settings: Settings) -> None:
    """No AudioContext before the viewer taps the speaker: the only constructor is the factory handed to the engine,
    and the engine's enable() is called from the speaker's tap only."""
    module = re.sub(r"//[^\n]*", "", _module(render_world_html(settings)))
    section = _channel(_module(render_world_html(settings)))
    assert module.count("AudioContext") == 2 and module.count("new AC()") == 1  # (window.AudioContext, webkitAudioContext)
    assert "const sound = makeSound(function () { const AC = window.AudioContext || window.webkitAudioContext; return AC ? new AC() : null; });" in section
    assert module.count("sound.enable()") == 1
    assert "speakerBtn.onclick = function () { if (sound.on) sound.disable(); else sound.enable();" in section
    assert 'document.addEventListener("visibilitychange", function () { const hid = document.visibilityState !== "visible"; body.classList.toggle("tab-hidden", hid); sound.hidden(hid); });' in section


def test_the_channel_allocates_nothing_per_frame(settings: Settings) -> None:
    section = _channel(_module(render_world_html(settings)))
    bodies = [_js_body(section, 'BUS.on("frame", function (dt, dtRaw) {')]
    for name in ("skyStep(dt)", "lampsStep()", "weatherStep(dt)", "mixC(key, out)", "mixN(key)", "overcast(c, g)",
                 "hear(name, at, ref, base)", "hearAll()"):
        bodies.append(_js_body(section, f"    function {name} {{"))
    for body in bodies:
        code = re.sub(r"//[^\n]*", "", body)
        for banned in ("new ", ".clone(", "function (", ".map(", ".filter(", ".concat(", ".slice(", "Object.assign", "=> ", "[]"):
            assert banned not in code.split("{", 1)[1], (code[:40], banned)
    hours = _js_body(section, "    function viewerHours() {")
    assert "if (now - tzAt > 60000) { tzAt = now; tzMs = new Date(now).getTimezoneOffset() * 60000; }" in hours  # once a minute
    # the sky four times a second, the rain capped and off on slow screens or once the governor steps down
    assert "skyT += dtRaw; if (skyT >= 0.25) { skyStep(skyT); skyT = 0; }" in section
    assert "const RAIN_N = Q.small ? 140 : 280" in section and "let rainOk = !LITE && !slow && !tiny;" in section
    assert "if (rainOk && ((bloom && Q.bloom && !bloom.enabled) || Q.dpr < DPR0)) { rainOk = false;" in section


# --------------------------------------------------------------------------- the world: the pure block in Node

_PURE_HARNESS = r"""
import fs from "node:fs";
const src = fs.readFileSync(process.argv[2], "utf8");
const P = new Function(src + "\nreturn { CH_LOOKS, CH_ANCHORS, CH_PAL, CH_COLORS, CH_SKY, CH_BELL, dayWeights, weatherOf, freshFinished, replayWords, tickerWhen, tickerParts, makeSound };")();
const out = {};
// the day: weights at every quarter hour (they sum to 1, never jump), the five looks at their own times
const steps = []; let maxJump = 0, prev = null, sumOff = 0;
for (let q = 0; q <= 96; q++) { const w = P.dayWeights(q / 4, {}); let s = 0; P.CH_LOOKS.forEach((k) => { s += w[k]; if (w[k] < -1e-9 || w[k] > 1 + 1e-9) sumOff = 9; });
  sumOff = Math.max(sumOff, Math.abs(s - 1)); if (prev) P.CH_LOOKS.forEach((k) => { maxJump = Math.max(maxJump, Math.abs(w[k] - prev[k])); }); prev = w; }
const at = (h) => { const w = P.dayWeights(h, {}); return P.CH_LOOKS.reduce((best, k) => (w[k] > w[best] ? k : best), "night") + ":" + Math.max(...P.CH_LOOKS.map((k) => w[k])).toFixed(2); };
out.day = { sumOff, maxJump, at: ["06:30", "13:00", "18:45", "19:45", "23:30", "03:00"].map((t) => { const [h, m] = t.split(":").map(Number); return at(h + m / 60); }),
  keys: P.CH_LOOKS.every((k) => P.CH_COLORS.every((c) => typeof P.CH_PAL[k][c] === "number")
    && ["stars", "hemi", "sunI", "prac", "exp", "el", "sx", "key", "lantern"].every((n) => typeof P.CH_PAL[k][n] === "number")),
  sunSide: { dawn: P.CH_PAL.dawn.sx, golden: P.CH_PAL.golden.sx }, wrap: at(-0.5) + "|" + at(24.5) };
// the weather
const desk = (today, extra) => ({ mode: "PAPER", money: { label: "Paper money (pretend)", today: { usd: -5 },
  polymarket: Object.assign({ mode: "live", real: today === undefined ? null : { today_usd: today }, guard: { paused: false, real: null } }, extra || {}) }, plain: { real: {} } });
const W = (d) => { const o = P.weatherOf(d, {}); return [o.sky, o.real, o.clouds, o.dim, o.rain]; };
const reused = {}; P.weatherOf(desk(-1), reused);
out.weather = {
  none: W(null), pretendOnly: W(desk(undefined)), up: W(desk(0.03)), even: W(desk(0)), cents: W(desk(-0.004)), down: W(desk(-0.97)),
  paused: W(desk(0.5, { guard: { paused: true, real: null } })), pausedReal: W(desk(0.5, { guard: { paused: false, real: { paused: true } } })),
  dayStop: W(Object.assign(desk(-3), { plain: { real: { paused_kind: "day" } } })), full: W(Object.assign(desk(0.2), { plain: { real: { paused_kind: "full" } } })),
  solanaLive: W({ mode: "LIVE", money: { label: "Real money", today: { usd: -2 } }, plain: {} }),
  solanaPaper: W({ mode: "PAPER", money: { label: "Paper money (pretend)", today: { usd: -2 } }, plain: {} }),
  bothWorst: W({ mode: "LIVE", money: { label: "Real money", today: { usd: 4 }, polymarket: { real: { today_usd: -0.5 } } }, plain: {} }),
  reused: P.weatherOf(null, reused) === reused && reused.sky === "clear", skies: P.CH_SKY };
// a replay: never on the first poll, never twice, never an older one; only valid items
const memo = { polled: false, top: -Infinity, ids: {} }, ids = (l) => l.map((i) => i.id);
const T = (id, ts, who, result) => ({ id, ts, who: who || "jet", result: result || "won", what: id, usd: 1, real: false, money: "pretend" });
const seen = [];
seen.push(ids(P.freshFinished(memo, [T("a", 10), T("b", 5)])));     // first poll: old news
seen.push(ids(P.freshFinished(memo, [T("a", 10), T("b", 5)])));     // nothing new
seen.push(ids(P.freshFinished(memo, null)));                         // no data
seen.push(ids(P.freshFinished(memo, [T("c", 12), T("a", 10)])));     // a new one
seen.push(ids(P.freshFinished(memo, [T("c", 12), T("a", 10)])));     // the same again
seen.push(ids(P.freshFinished(memo, [T("old", 3), T("c", 12)])));    // older than the newest seen: not news
seen.push(ids(P.freshFinished(memo, [T("x", 20, "rook"), T("y", 21, "jet", "maybe"), { id: 5, ts: 22 }, T("e", 30), T("d", 25, "voss")])));  // oldest first
const empty = { polled: false, top: -Infinity, ids: {} };
seen.push(ids(P.freshFinished(empty, []))); seen.push(ids(P.freshFinished(empty, [T("first", 1)])));  // the first ever
out.replay = { seen, words: [
  P.replayWords({ what: "DEMO", result: "won", usd: 12.34, real: false, money: "pretend" }).line,
  P.replayWords({ what: "Will the Fed cut?", result: "won", usd: 0.03, real: true, money: "real money" }).line,
  P.replayWords({ what: "LIE", result: "lost", usd: 1, real: false, money: "real money" }).line,
  P.replayWords({ what: "LIE2", result: "lost", usd: 1, real: true, money: "pretend" }).line,
  P.replayWords({ what: "E", result: "even", usd: 0, real: false, money: "pretend" }).line,
  P.replayWords({ what: "N", result: "lost", usd: null, real: false, money: "pretend" }).line] };
// the ticker's times on the viewer's clock
const now = new Date(2026, 9, 10, 14, 5).getTime(), today = new Date(2026, 9, 10, 9, 7).getTime() / 1000, yday = new Date(2026, 9, 9, 23, 59).getTime() / 1000;
out.ticker = { today: P.tickerWhen(today, now), yday: P.tickerWhen(yday, now),
  parts: P.tickerParts({ ts: today, name: "Voss", text: "a real-money bet won $0.03 · Will it rain?", tone: "great" }, now) };
// the sound: nothing made before enable(); suspended while hidden or off; the bell higher for a win; one whoosh per cut
let made = 0; const log = [];
function Param(v) { return { value: v, setTargetAtTime() {}, setValueAtTime() {}, linearRampToValueAtTime() {}, exponentialRampToValueAtTime() {} }; }
function Node() { return { connect() {}, start() {}, stop() {} }; }
function FakeCtx() {
  this.state = "running"; this.currentTime = 0; this.sampleRate = 8000; this.destination = {};
  this.createGain = () => Object.assign(Node(), { gain: Param(1) });
  this.createBiquadFilter = () => Object.assign(Node(), { frequency: Param(350), Q: Param(1), type: "" });
  this.createOscillator = () => { const o = Object.assign(Node(), { frequency: Param(440), type: "" }); log.push(o); return o; };
  this.createBufferSource = () => Object.assign(Node(), { playbackRate: Param(1), buffer: null, loop: false });
  this.createBuffer = (c, n) => ({ duration: n / 8000, getChannelData: () => new Float32Array(n) });
  this.createStereoPanner = () => Object.assign(Node(), { pan: Param(0) });
  this.suspend = () => { this.state = "suspended"; log.push("suspend"); }; this.resume = () => { this.state = "running"; log.push("resume"); };
}
const S = P.makeSound(() => { made += 1; return new FakeCtx(); });
const before = { made, on: S.on }; S.bell(true); S.cut(); S.level("water", 1, 0); S.hidden(true); const quiet = { made, ctx: S.context() };
const ok = S.enable(); const afterOn = { made, on: S.on, ok };
const nOsc = log.length; S.bell(true); const winF = log.slice(nOsc).filter((o) => typeof o === "object")[0].frequency.value;
const nOsc2 = log.length; S.bell(false); const lossF = log.slice(nOsc2).filter((o) => typeof o === "object")[0].frequency.value;
S.cut(); const first = S.last; S.last = ""; S.cut(); const twice = S.last;  // (same instant: one whoosh)
const ctx = S.context(); ctx.currentTime = 1; S.cut(); const later = S.last;
S.hidden(true); const hid = ctx.state; S.hidden(false); const back = ctx.state;
S.disable(); const off = [ctx.state, S.on]; S.hidden(false); const stillOff = ctx.state; S.enable(); const again = [made, ctx.state, S.on];
const F = P.makeSound(() => null); const failed = [F.enable(), F.failed, F.on];
out.sound = { before, quiet, afterOn, winF, lossF, first, twice, later, hid, back, off, stillOff, again, failed, desks: S.desks };
console.log(JSON.stringify(out));
"""

_PURE_REPORT: dict[str, Any] = {}


def _pure_report(settings: Settings, tmp_path: Path) -> dict[str, Any]:
    if not _PURE_REPORT:
        (tmp_path / "pure.js").write_text(_pure(_module(render_world_html(settings))), encoding="utf-8")
        _PURE_REPORT.update(_node(_PURE_HARNESS.replace("process.argv[2]", json.dumps(str(tmp_path / "pure.js"))), tmp_path))
    return _PURE_REPORT


def test_the_pure_block_is_pure(settings: Settings) -> None:
    code = re.sub(r"//[^\n]*", "", _pure(_module(render_world_html(settings))))
    for banned in ("THREE", "document", "window", "simT", "camera", "scene", "actors", "performance", "props."):
        assert banned not in code, banned


@NODE
def test_the_day_runs_full_circle_on_the_viewers_clock(settings: Settings, tmp_path: Path) -> None:
    day = _pure_report(settings, tmp_path)["day"]
    assert day["sumOff"] < 1e-9 and day["maxJump"] < 0.35  # always a whole mix of looks, never a jump
    assert day["at"] == ["dawn:1.00", "day:1.00", "golden:1.00", "dusk:1.00", "night:1.00", "night:1.00"]
    assert day["keys"] is True and day["wrap"] == "night:1.00|night:1.00"
    assert day["sunSide"]["dawn"] > 0 > day["sunSide"]["golden"]  # the sun rises on one side and sets on the other


@NODE
def test_the_weather_follows_real_money_only(settings: Settings, tmp_path: Path) -> None:
    w = _pure_report(settings, tmp_path)["weather"]
    clear, cloudy, storm = w["skies"]["clear"], w["skies"]["cloudy"], w["skies"]["storm"]
    assert w["none"] == ["clear", False, clear["clouds"], 0, False]  # no data: no claim
    assert w["pretendOnly"] == ["clear", False, 0, 0, False]  # pretend money never makes weather (the paper bot lost $5)
    assert w["up"][0] == w["even"][0] == w["cents"][0] == "clear" and w["up"][1] is True
    assert w["down"] == ["cloudy", True, cloudy["clouds"], cloudy["dim"], False]  # drifting clouds, dimmer lanterns
    assert w["paused"][0] == w["pausedReal"][0] == w["dayStop"][0] == "storm" and w["paused"][4] is True
    assert w["full"][0] == "clear"  # the open-money limit is waiting, not a stop
    assert w["solanaLive"][0] == "cloudy" and w["solanaPaper"][0] == "clear" and w["bothWorst"][0] == "cloudy"
    assert storm["clouds"] > cloudy["clouds"] > clear["clouds"] == 0 and clear["dim"] == 0 and w["reused"] is True


@NODE
def test_no_replay_without_something_newly_finished(settings: Settings, tmp_path: Path) -> None:
    r = _pure_report(settings, tmp_path)["replay"]
    assert r["seen"] == [[], [], [], ["c"], [], [], ["d", "e"], [], ["first"]]
    assert r["words"] == ["REPLAY · DEMO · won $12.34 · pretend", "REPLAY · Will the Fed cut? · won $0.03 · real money",
                          "REPLAY · LIE · lost $1.00 · pretend", "REPLAY · LIE2 · lost $1.00 · pretend",
                          "REPLAY · E · even · pretend", "REPLAY · N · lost · pretend"]


@NODE
def test_the_ticker_says_each_events_time_on_the_viewers_clock(settings: Settings, tmp_path: Path) -> None:
    t = _pure_report(settings, tmp_path)["ticker"]
    assert t["today"] == "09:07" and t["yday"] == "yesterday 23:59"
    assert t["parts"] == {"when": "09:07 · ", "who": "Voss: ", "text": "a real-money bet won $0.03 · Will it rain?", "tone": ""}


@NODE
def test_no_audio_context_before_the_tap(settings: Settings, tmp_path: Path) -> None:
    s = _pure_report(settings, tmp_path)["sound"]
    assert s["before"] == {"made": 0, "on": False} and s["quiet"] == {"made": 0, "ctx": None}  # nothing until enable()
    assert s["afterOn"] == {"made": 1, "on": True, "ok": True}
    assert s["winF"] > s["lossF"]  # the bell rings higher for a win
    assert s["first"] == "cut" and s["twice"] == "" and s["later"] == "cut"  # one whoosh per cut
    assert s["hid"] == "suspended" and s["back"] == "running"  # silent while the tab is hidden
    assert s["off"] == ["suspended", False] and s["stillOff"] == "suspended"  # off stays off when the tab comes back
    assert s["again"] == [1, "running", True]  # one context for the whole visit
    assert s["failed"] == [False, True, False] and s["desks"] == ["voss", "pip", "nyx", "rook", "mote"]
