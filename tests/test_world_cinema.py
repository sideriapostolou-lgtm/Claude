"""The 3D world's cinema mode (world3d's THE CINEMA section and its CSS block, the default view): the page opens in it;
its one HUD line shows real money only; the caption under the shot says who and what in the data's own words (pretend
money only in a character's own caption, said "practice"); every character has a small name tag with a two-to-four word
job; the vault's sign reads the real cash; the first visit gets one three-line card; the director's rotation holds
longer; and the "details" button (remembered when the browser allows it) brings today's full view back exactly."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from nightcrawler.config import Settings
from nightcrawler.world3d import _STYLE_CINEMA, WORLD_CAST, WORLD_CSP, render_world_html
from tests import goal_states as GS
from tests import heart_states as HS
from tests.test_world3d import _js_body, _module, _node
from tests.test_world_records import _REDS

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
_HEADER, _END = "= THE CINEMA (cinema mode, the default view)", '  resize(); BUS.emit("start", 0, 0);'
_KEYS = ("voss", "rook", "pip", "nyx", "jet", "mote")


@pytest.fixture(scope="module")
def page() -> str:
    return render_world_html(Settings.from_env({"DATA_DIR": "/tmp/nightcrawler-world-cinema-test"}))


@pytest.fixture(scope="module")
def module(page: str) -> str:
    return _module(page)


@pytest.fixture(scope="module")
def section(module: str) -> str:
    return module[module.index(_HEADER):module.index(_END)]


@pytest.fixture(scope="module")
def pure(module: str) -> str:
    return module[module.index("// >>> cinema (pure)"):module.index("// <<< cinema")]


@pytest.fixture(scope="module")
def states() -> dict[str, dict[str, Any]]:
    """The harness's pages: "paper" (no real money: the seeded two days), and the hearts' live real-money days."""
    base = GS.base_page()
    out = {name: HS.apply_heart_state(base, name) for name in ("winning", "losing_big")}
    out["paper"] = base
    return out


def _pure_run(pure: str, body: str, tmp_path: Path, **data: Any) -> Any:
    """Run ``body`` (which ends by printing one JSON line) after the pure block, with ``data`` as JS constants."""
    consts = "".join(f"const {k} = {json.dumps(v)};\n" for k, v in data.items())
    return _node(pure + "\n" + consts + body, tmp_path)


def _sentence(s: str) -> str:  # the caption's own sentence rule (cineSentence), for the expectations
    t = s.strip()
    t = t[:1].upper() + t[1:]
    return t if re.search(r"[.!?…]$", t) else t + "."


def _first(s: str) -> str:  # a long line's first sentence (cineSplit)
    m = re.match(r"^(.*?[a-z0-9)%]\.)\s+([A-Z].*)$", s.strip(), flags=re.DOTALL)
    return m.group(1) if m else s.strip()


# --------------------------------------------------------------------------- the default view


def test_cinema_is_the_default_view(page: str, module: str, section: str) -> None:
    assert re.search(r'<body [^>]*class="cinema">', page)  # (from the first paint, before the module runs)
    assert '<button type="button" id="details" aria-pressed="false">details</button>' in page
    for part in ('<div id="lb-top"><button type="button" id="hud" aria-controls="panel">', '<b id="hud-cash">—</b>',
                 '<div id="lb-bot"><div id="cap" aria-live="off">', '<div id="tags" aria-hidden="true"></div>',
                 '<div id="intro" role="dialog" aria-labelledby="intro-title" hidden>'):
        assert part in page, part
    # the mode: cinema unless this browser remembers "details"; the section runs before the first frame and the first poll
    assert "cineSet(!cineStored(), false);" in section
    assert 'const CINE_KEY = "nightcrawler.world.details"' in section
    assert module.index(_HEADER) > module.index("= THE LOOP (paused") and module.index(_HEADER) < module.index(_END)
    # the guide waits behind "details": a first visit in cinema mode gets the three-line card instead
    assert _js_body(module, "  function openGuide() {").split("\n")[1].strip().startswith(
        "if (CINE.on) { cineIntroOpen(); return; }")
    assert "if (first) { chatterAt = simT + 6; if (plain && !guideSeen()) openGuide(); }" in module  # (unchanged)
    assert "if (first) cineIntroOpen();" in section


def test_the_csp_is_unchanged_but_for_the_inline_hashes() -> None:
    template = re.sub(r"'sha256-[A-Za-z0-9+/=]+'", "'sha256-X'", WORLD_CSP)
    assert template == ("default-src 'none'; script-src 'self' 'wasm-unsafe-eval' 'sha256-X' 'sha256-X'; "
                        "style-src 'sha256-X'; connect-src 'self' blob:; img-src 'self' data: blob:; "
                        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def _rules(css: str) -> list[tuple[list[str], str]]:
    """(selectors, body) of each rule, the @media wrappers opened up."""
    flat = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    flat = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^}]*\})*\s*\}", "", flat)
    flat = re.sub(r"@media[^{]*\{((?:[^{}]*\{[^}]*\})*)\s*\}", r"\1", flat)
    return [([s.strip() for s in sel.split(",")], body) for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", flat)]


def test_the_clutter_hides_in_cinema_mode_only(page: str) -> None:
    rules = _rules(_STYLE_CINEMA)
    hidden = {s for sels, body in rules if "display: none !important" in body for s in sels}
    for part in ("#chips", "#ticker", "#replay", "#postcard", "#rec-toast", "#film", "#guide", "#labels", "#bubbles", "#drop",
                 "#headline", "#goal"):
        assert f"body.cinema {part}" in hidden, part
    assert "body.cinema #bar .row1 > :not(#sound)" in hidden  # (the bar keeps the speaker; its real-problem line stays)
    assert "body.cinema #card" in {s for sels, body in rules if "visibility: hidden" in body for s in sels}
    # every rule that touches a part of the full view is scoped under body.cinema: the "details" button (which takes the
    # class off) brings that view back exactly as it was
    own = ("#cine", "#tags", "#intro", "#lb-top", "#lb-bot", "#hud", "#cap", "#details", ".ntag", ":root")
    for sels, body in rules:
        for s in sels:
            if s.startswith(("body.cinema", "body:not(.cinema)", *own)):
                continue
            pytest.fail(f"a rule outside cinema mode touches the full view: {s} {{{body}}}")
    for sels, body in rules:  # (and nothing hides outside it but the cinema's own parts)
        if "display: none" in body or "visibility: hidden" in body:
            for s in sels:
                assert s.startswith(("body.cinema ", "#cine", "#tags", "#intro[hidden]", "#cap-2[hidden]", ".ntag span:empty",
                                     "body:not(.cinema):has(#replay.on) #details")), s
    # the Goal Tower, the hearts and the speaker stay: nothing here hides the canvas, the panel or the speaker
    assert not any(s in hidden for s in ("body.cinema #view", "body.cinema #panel", "body.cinema #sound"))
    # red stays real money's: the HUD's tag is red only while the data says real money is on
    tag = {s: b for sels, b in rules for s in sels}
    assert any(red in tag["#hud .htag.on"] for red in _REDS) and not any(red in tag["#hud .htag"] for red in _REDS)


def test_the_section_is_text_only_and_its_storage_guarded(section: str) -> None:
    code = re.sub(r"//[^\n]*", "", section)
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "new Function", "document.write", "BUS.emit(",
                 "speak(", "focusOn(", "togglePin(", "progStart(", "LIVE_CFG"):
        assert sink not in code, sink
    uses = [line for line in section.splitlines() if "localStorage" in line]
    assert len(uses) == 4 and all("try { " in line and "catch (e)" in line for line in uses), uses


@needs_node
def test_the_storage_survives_a_blocked_browser(section: str, tmp_path: Path) -> None:
    fns = "\n".join(_js_body(section, f"  function {n}(") for n in ("cineStored", "cineStore", "cineIntroSeen", "cineIntroRemember"))
    out = _node(f"""
const CINE_KEY = "nightcrawler.world.details", CINE_INTRO_KEY = "nightcrawler.world.intro", CINE = {{ introDone: false }};
const store = {{}}, window = {{ localStorage: {{ getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => {{ store[k] = String(v); }},
  removeItem: (k) => {{ delete store[k]; }} }} }};
{fns}
const a = cineStored(); cineStore(true); const b = cineStored(); cineStore(false); const c = cineStored();
const d = cineIntroSeen(); cineIntroRemember(); const e = cineIntroSeen(); CINE.introDone = false; const f = cineIntroSeen();
window.localStorage = {{ getItem: () => {{ throw new Error("blocked"); }}, setItem: () => {{ throw new Error("blocked"); }},
  removeItem: () => {{ throw new Error("blocked"); }} }};
CINE.introDone = false; let threw = false;
try {{ cineStore(true); cineIntroRemember(); }} catch (x) {{ threw = true; }}
console.log(JSON.stringify([a, b, c, d, e, f, cineStored(), threw, cineIntroSeen()]));
""", tmp_path)
    # remembered; forgotten; a blocked browser: cinema (the default), nothing thrown, the card counted seen this visit
    assert out == [False, True, False, False, True, True, False, False, True]


# --------------------------------------------------------------------------- the HUD: real money only


@needs_node
def test_the_hud_shows_only_real_money(pure: str, states: dict[str, dict[str, Any]], tmp_path: Path) -> None:
    win, lose, paper = states["winning"], states["losing_big"], states["paper"]
    paused = json.loads(json.dumps(win))
    paused["plain"]["real"].update(paused="Paused by the risk manager.", paused_kind="risk")
    stopped = json.loads(json.dumps(win))
    stopped["plain"]["real"].update(paused="Stopped for today.", paused_kind="day")
    out = _pure_run(pure, """
const show = (d) => { const h = cineHud(d); return [h.line, h.on, h.cash, h.parts.map((q) => q.k)]; };
console.log(JSON.stringify({ win: show(WIN), lose: show(LOSE), paper: show(PAPER), paused: show(PAUSED), stopped: show(STOPPED),
  none: show(null), empty: show({}) }));
""", tmp_path, WIN=win, LOSE=lose, PAPER=paper, PAUSED=paused, STOPPED=stopped)
    cash = win["plain"]["real"]["cash_usd"]
    assert out["win"] == [f"REAL MONEY ${cash:.2f} · today +$1.52 · goal $100/day", True, f"${cash:.2f}", ["up", ""]]
    assert out["lose"][0] == f"REAL MONEY ${lose['plain']['real']['cash_usd']:.2f} · today −$8.82 · goal $100/day"
    assert out["lose"][3] == ["down", ""]
    assert out["paused"][0].endswith(" · today +$1.52 · paused · goal $100/day")
    assert out["stopped"][0].endswith(" · today +$1.52 · stopped for today · goal $100/day")
    assert out["paper"] == ["REAL MONEY — · off · goal $100/day", False, "—", ["state", ""]]
    assert out["none"][0] == "REAL MONEY — · loading" and out["empty"][0] == "REAL MONEY — · loading"
    # never a pretend figure: the paper wallet, the practice books and the trend desk say nothing here
    for name in ("winning", "losing_big", "paper"):
        line = out[{"winning": "win", "losing_big": "lose", "paper": "paper"}[name]][0]
        money = states[name]["money"]
        pretend = [money["usd"], money["start_usd"], money["sol_usd"], (money.get("polymarket") or {}).get("paper", {}).get("today_usd"),
                   ((money.get("trend") or {}).get("equity_usd"))]
        figures = {float(x.replace(",", "")) for x in re.findall(r"\$([\d,]+\.\d\d)", line)}
        allowed = {round(abs(v), 2) for v in (states[name]["plain"]["real"].get("cash_usd"),
                                              states[name]["town"]["goal"].get("real_today_usd")) if v is not None}
        assert figures <= allowed, (line, figures)
        assert "pretend" not in line.lower() and "practice" not in line.lower()
        assert not any(v is not None and abs(v) >= 1 and f"${abs(v):.2f}" in line for v in pretend if v not in allowed)


@needs_node
def test_the_vault_reads_real_money(pure: str, section: str, module: str, states: dict[str, dict[str, Any]], tmp_path: Path) -> None:
    out = _pure_run(pure, "console.log(JSON.stringify([cineVault(WIN), cineVault(LOSE), cineVault(PAPER)]));", tmp_path,
                    WIN=states["winning"], LOSE=states["losing_big"], PAPER=states["paper"])
    win, lose, paper = out
    real = states["winning"]["plain"]["real"]
    assert win["usd"] == f"${real['cash_usd']:.2f}" and win["label"] == "REAL · " + real["result"]
    since = states["winning"]["money"]["polymarket"]["real"]["since_start_usd"]
    assert win["accent"] == ("#58d68d" if since >= 0 else "#ff6b61")
    assert lose["label"] == "REAL · " + states["losing_big"]["plain"]["real"]["result"]
    assert paper == {"usd": "—", "label": "REAL · none reported", "accent": None}  # (no real money: never the pretend wallet)
    # in cinema mode the sign is drawn again after the page's own (money.usd, money.label: the details view's) on each poll
    draw = _js_body(section, "  function cineVaultDraw() {")
    assert "if (CINE.on) { const v = cineVault(data); drawVaultSign(v.usd, v.label, v.accent); return; }" in draw
    assert 'drawVaultSign(fmtUsd(money.usd), money.label || "", since == null ? null' in draw  # (details: as before)
    assert "if (CINE.on) cineVaultDraw();" in _js_body(section, "  function cineOnData(")
    apply = _js_body(module, "  function apply(d) {")
    assert apply.index("drawVaultSign(fmtUsd(money.usd), money.label") < apply.index('BUS.emit("data", d, first);')


# --------------------------------------------------------------------------- captions and job tags


@needs_node
def test_the_captions_come_from_the_data(pure: str, states: dict[str, dict[str, Any]], tmp_path: Path) -> None:
    win, paper = states["winning"], states["paper"]
    said = json.loads(json.dumps(win))
    said["plain"]["said"]["predict"] = {"ts": 1.0, "text": "bet $5.80 that the Packers win (real money)"}
    out = _pure_run(pure, """
const cap = (p, k, room) => cineCaption(p, k, room, k ? k.charAt(0).toUpperCase() + k.slice(1) : "");
const keys = ["voss", "rook", "pip", "nyx", "jet", "mote"], rooms = ["vault", "table", "observatory", "dock", "archive", "workshop", "den", null];
const all = (p) => keys.map((k) => cap(p, k, null)).concat(rooms.map((r) => cap(p, null, r)));
console.log(JSON.stringify({
  win: Object.fromEntries(keys.map((k) => [k, cap(WIN.plain, k, null)])), said: cap(SAID.plain, "voss", null),
  places: Object.fromEntries(rooms.map((r) => [String(r), cap(WIN.plain, null, r)])), paper: cap(PAPER.plain, "voss", null),
  none: cap(null, "voss", null), every: all(WIN.plain).concat(all(PAPER.plain)),
  words: ["Practice (pretend money): found a coin", "bought HIGGS for 0.1000 SOL (pretend money)", "keeps money (practice, pretend money).",
          "the rest is pretend money.", "everything is practice with pretend money.", "Pretend books", "a (paper) trade",
          "Practice for now (pretend money), but I watch", "Practice today: +$2.40 (pretend money). One find", "mine are practice (pretend money)."]
         .map(cinePractice),
  split: ["Real money today: +$1.52, and it covers the bill. Same rule.", "Will the U.S. hold rates? Yes.", "One line only", "Down 3%. Then up."].map(cineSplit),
}));
""", tmp_path, WIN=win, SAID=said, PAPER=paper)
    p = win["plain"]
    hearts = {m["id"]: m["line"] for m in p["hearts"]["members"]}
    team = {t["id"]: t for t in p["team"]}
    # Voss: the Polymarket desk's newest event in the server's plain words, else his goal line; his heart line second
    assert out["said"]["who"] == "VOSS" and out["said"]["rest"] == ", the real-money trader. Bet $5.80 that the Packers win (real money)."
    voss_line = p["goal"]["lines"]["voss"]  # (a goal line: its first sentence)
    assert _first(voss_line) != voss_line and out["win"]["voss"]["rest"] == ", the real-money trader. " + _sentence(_first(voss_line))
    assert out["win"]["voss"]["second"] == _sentence(hearts["voss"]) and out["win"]["voss"]["heart"] is True
    # Rook: today's real loss stop; Mote: the newest record; the practice crew: their newest event, said "practice"
    assert out["win"]["rook"]["rest"] == ", the risk guard. " + _sentence(p["goal"]["floor_line"])
    assert out["win"]["mote"]["rest"] == ", the record keeper. " + _sentence(team["mote"]["latest"])
    assert out["win"]["pip"]["rest"] == ", the coin scout (practice). " + _sentence(team["pip"]["latest"])
    assert out["win"]["jet"]["rest"] == ", the trade runner (practice). Bought HIGGS for 0.1000 SOL (practice)."
    # (the heart says "Practice today: +$2.40 (pretend money)": practice said once)
    assert "Practice today" in hearts["pip"] and out["win"]["pip"]["second"] == _sentence(hearts["pip"].replace(" (pretend money)", ""))
    # the places: the vault's real money, the courtyard's headline and goal, the observatory's labs, a room's keeper
    real, goal = p["real"], p["goal"]
    assert out["places"]["vault"] == {"who": "THE VAULT", "rest": " · " + _sentence(real["line"]), "second": _sentence(goal["reserve_line"]), "heart": False}
    assert out["places"]["table"]["rest"] == " · " + _sentence(p["headline"].replace("pretend money", "practice money"))
    assert out["places"]["table"]["second"] == _sentence(_first(goal["line"])) and out["places"]["null"] == out["places"]["table"]
    assert out["places"]["observatory"]["rest"] == " · " + _sentence(real["research"])
    assert out["places"]["dock"]["rest"] == " · Jet places the Solana bot's trades (practice)."
    # a long line splits after its first sentence, never inside "$1.52" or "U.S."
    assert out["split"] == [["Real money today: +$1.52, and it covers the bill.", "Same rule."], ["Will the U.S. hold rates? Yes.", ""],
                            ["One line only", ""], ["Down 3%.", "Then up."]]
    # practice money is said "practice", once; and no caption ever says pretend
    assert out["words"] == ["Practice: found a coin", "bought HIGGS for 0.1000 SOL (practice)", "keeps money (practice).",
                            "the rest is practice money.", "everything is practice.", "Practice books", "a (practice) trade",
                            "Practice for now, but I watch", "Practice today: +$2.40. One find", "mine are practice."]
    for c in out["every"]:
        text = c["who"] + c["rest"] + " " + c["second"]
        assert "pretend" not in text.lower() and "paper" not in text.lower(), text
    # with real money off Voss is a practice trader; before the first poll a caption is the name alone
    assert out["paper"]["rest"].startswith(", the trader (practice). ")
    assert out["none"] == {"who": "VOSS", "rest": "", "second": "", "heart": True}


@needs_node
def test_every_character_has_a_job_tag(pure: str, section: str, states: dict[str, dict[str, Any]], tmp_path: Path) -> None:
    out = _pure_run(pure, """
const tags = (p) => Object.fromEntries(CINE_ORDER.map((k) => [k, cineTag(k, cineTeam(p, k))]));
console.log(JSON.stringify({ keys: Object.keys(CINE_TAGS), tags: CINE_TAGS, win: tags(WIN.plain), paper: tags(PAPER.plain), none: tags(null) }));
""", tmp_path, WIN=states["winning"], PAPER=states["paper"])
    assert sorted(out["keys"]) == sorted(WORLD_CAST) == sorted(_KEYS)
    assert out["win"] == {"voss": "real-money trader", "rook": "risk guard", "pip": "coin scout (practice)",
                          "nyx": "scam checker (practice)", "jet": "trade runner (practice)", "mote": "record keeper"}
    assert out["paper"]["voss"] == "trader (practice)" and out["none"] == {k: "" for k in _KEYS}  # (no data: no claim)
    for tag in out["tags"].values():
        for words in tag.values():
            assert 2 <= len(words.replace("(practice)", "").split()) + ("(practice)" in words) <= 4, words
    # one tag per character, as text, over their head while they are on screen (in plain view, near enough)
    assert "const CINE_NAMETAGS = ACTOR_KEYS.map(function (k) {" in section
    assert "b.textContent = CAST[k].name.toUpperCase();" in section and "q.job.textContent = tag;" in section
    frame = _js_body(section, "  function cineTagsFrame() {")
    assert "blocked(camera.position, a.headAt) > 0.98" in frame and "dist < CINE_FAR" in frame
    rules = {s: b for sels, b in _rules(_STYLE_CINEMA) for s in sels}
    assert "font-size: 10.5px" in rules[".ntag b"] and "font-size: 10.5px" in rules[".ntag span"]  # (small, not a game bar)


@needs_node
def test_the_first_visit_card_says_three_things_from_the_data(pure: str, section: str, states: dict[str, dict[str, Any]],
                                                              tmp_path: Path) -> None:
    out = _pure_run(pure, "console.log(JSON.stringify([cineIntroLines(WIN.plain), cineIntroLines(null)]));", tmp_path,
                    WIN=states["winning"])
    p = states["winning"]["plain"]
    assert out[0]["about"] == p["about"]  # what this is
    assert out[0]["team"] == [["Voss", "real-money trader"], ["Rook", "risk guard"], ["Pip", "coin scout (practice)"],
                              ["Nyx", "scam checker (practice)"], ["Jet", "trade runner (practice)"], ["Mote", "record keeper"]]
    assert out[0]["money"] == "Real money is on only for Voss's small Polymarket bets; the rest is practice money."
    assert out[1] == {"about": "", "team": [], "money": ""}
    opener = _js_body(section, "  function cineIntroOpen(")
    assert "cineIntroSeen()" in opener and "setTimeout(function () { cineIntroClose(true); }, CINE_INTRO_MS)" in opener
    assert "para(cineIntroBody, L.about);" in opener and 'para(cineIntroBody, L.money, "money");' in opener


# --------------------------------------------------------------------------- the details button and the director


@needs_node
def test_the_details_button_brings_the_full_view_back(pure: str, section: str, module: str, states: dict[str, dict[str, Any]],
                                                      tmp_path: Path) -> None:
    fns = "\n".join(_js_body(section, f"  function {n}(") for n in ("cineStore", "cineBoards", "cineVaultDraw", "cineSet"))
    fmt = _js_body(module, "function fmtUsd(v) {")
    out = _pure_run(pure, f"""
const store = {{}}, window = {{ localStorage: {{ setItem: (k, v) => {{ store[k] = v; }}, removeItem: (k) => {{ delete store[k]; }} }} }};
const CINE_KEY = "nightcrawler.world.details", CINE = {{ on: true, cap: "x", capAt: 9, hud: "x" }}, calls = [];
const cls = new Set(["cinema"]), body = {{ classList: {{ toggle: (c, on) => {{ if (on) cls.add(c); else cls.delete(c); }} }} }};
const cineDetails = {{ textContent: "", attrs: {{}}, setAttribute(k, v) {{ this.attrs[k] = v; }} }};
const layers = {{ on: [] }}, camera = {{ layers: {{ enable: (n) => layers.on.push(["enable", n]), disable: (n) => layers.on.push(["disable", n]) }} }};
const PAGE_MAT = {{ id: "page" }}, CINE_DARK = {{ id: "dark" }}, CINE_BOARDS = [{{ m: {{ material: PAGE_MAT }}, mat: PAGE_MAT }}];
const signs = [], drawVaultSign = (u, l, a) => signs.push([u, l]);
{fmt}
const closePanel = () => calls.push("closePanel"), closeGuide = () => calls.push("closeGuide"), cineIntroClose = () => calls.push("introClose");
const cineMeasure = () => {{}}, measureBar = () => calls.push("measureBar"), renderCard = () => calls.push("renderCard"), cineHudDraw = () => calls.push("hud");
let data = DATA;
{fns}
const snap = () => [cls.has("cinema"), cineDetails.textContent, cineDetails.attrs["aria-pressed"], CINE_BOARDS[0].m.material.id,
                    layers.on[layers.on.length - 1], signs[signs.length - 1], store[CINE_KEY] || null];
cineSet(true, false); const a = snap(); calls.length = 0;
cineSet(false, true); const b = snap(), cb = calls.slice(); calls.length = 0;
cineSet(true, true); const c = snap(), cc = calls.slice();
console.log(JSON.stringify({{ a, b, c, cb, cc }}));
""", tmp_path, DATA=states["winning"])
    win = states["winning"]
    cash, money = f"${win['plain']['real']['cash_usd']:.2f}", win["money"]
    real_sign = [cash, "REAL · " + win["plain"]["real"]["result"]]
    assert out["a"] == [True, "details", "false", "dark", ["disable", 1], real_sign, None]
    # details: the class off (every hidden part back), the boards' own words and the trophies back, the page's own sign
    # (money.usd and exactly money.label), remembered; the card drawn again for the full view
    assert out["b"] == [False, "simple view", "true", "page", ["enable", 1], [f"${money['usd']:.2f}", money["label"]], "1"]
    assert "renderCard" in out["cb"] and "introClose" in out["cb"] and "closePanel" not in out["cb"]
    # back to cinema: forgotten, the panel and the guide closed
    assert out["c"] == [True, "details", "false", "dark", ["disable", 1], real_sign, None]
    assert "closePanel" in out["cc"] and "closeGuide" in out["cc"]
    # what waits behind "details" in the world itself: the boards' words (a dark panel in their frames), the trophies and the
    # ticket board (another layer); their own visibility logic is untouched
    assert "[recLabs, recTrend, recCard, GP.yard].filter(Boolean)" in section
    assert "[recTrophies, recTiles, board].forEach(function (m) { m.layers.set(1); });" in section
    code = re.sub(r"//[^\n]*", "", section)
    assert ".visible =" not in code


@needs_node
def test_the_director_holds_longer_in_cinema_mode(module: str, section: str, tmp_path: Path) -> None:
    planner = module[module.index("// >>> live planner (pure)"):module.index("// <<< live planner")]
    camera = _js_body(section, "  function cineCamera() {")
    out = _node(planner + f"""
const CINE_HOLD = 0.6, CINE_FLY = 0.35;
const actors = [{{ id: "voss", room: "table", x: 0, z: 0 }}, {{ id: "pip", room: "workshop", x: -6, z: 0 }}];
const PLANNER = makePlanner(actors, [{{ id: "arrival", room: "table", wide: true, x: 0, z: 9 }}], {{ random: () => 0.5 }});
const live = {{ actors: {{ voss: {{ room: "table", x: 0, z: 0 }}, pip: {{ room: "workshop", x: -6, z: 0 }} }}, focus: null }};
let simT = 0; const CINE = {{ on: true, seq: -1, held: 0 }}, FILM = {{ on: false }}, RUN = {{ seq: -1, dur: 0, t0: 0 }}, FLY = {{ on: false, dur: 2, start: 0 }};
{camera}
const take = () => {{ RUN.seq = PLANNER.shot.seq; RUN.dur = PLANNER.shot.hold; RUN.t0 = simT; }};
PLANNER.plan(0, live); take(); const h0 = PLANNER.shot.hold; cineCamera(); const a = [h0, PLANNER.shot.hold, RUN.dur];
cineCamera(); const again = PLANNER.shot.hold;  // (once a shot)
simT = PLANNER.shot.hold + 0.1; PLANNER.plan(simT, live); take(); FLY.on = true; FLY.start = simT; FLY.dur = 2; const h1 = PLANNER.shot.hold, t1 = RUN.t0;
cineCamera(); const b = [h1, PLANNER.shot.hold, FLY.dur, RUN.t0 - t1];
simT += 100; live.focus = {{ actor: "pip", kind: "speak", start: simT, until: simT + 9 }}; PLANNER.plan(simT, live); take();
const h2 = PLANNER.shot.hold; cineCamera(); const c = [PLANNER.shot.event, h2, PLANNER.shot.hold];
CINE.on = false; live.focus = null; simT += 100; PLANNER.plan(simT, live); take(); const h3 = PLANNER.shot.hold; cineCamera();
console.log(JSON.stringify({{ a, again, b, c, d: [h3, PLANNER.shot.hold], held: CINE.held }}));
""", tmp_path)
    h0, h, dur = out["a"]
    assert abs(h - h0 * 1.6) < 1e-9 and abs(dur - h0 * 1.6) < 1e-9 and out["again"] == h  # a rotation shot holds 60 % longer
    h1, h1b, fly, t0 = out["b"]
    assert abs(fly - 2.7) < 1e-9 and abs(t0 - 0.7) < 1e-9 and abs(h1b - (h1 * 1.6 + 0.7)) < 1e-9  # and its flight is slower
    assert out["c"][0] is True and out["c"][1] == out["c"][2]  # an event's shot keeps its timing
    assert out["d"][0] == out["d"][1] and out["held"] == 2  # the details view: the director as it was


def test_the_caption_follows_the_shot_and_the_programmes(section: str) -> None:
    capf = _js_body(section, "  function cineCapFrame() {")
    assert "if (FILM.on) c = cineFilmCaption();" in capf and "cineCaption(plain, s.key, s.room" in capf
    assert "cineCap1.textContent = " in capf and "createTextNode(c.rest)" in capf and "innerHTML" not in capf
    film = _js_body(section, "  function cineFilmCaption() {")
    # a programme's own words; its practice words only on a character's own beat, said practice
    assert "!filmPretend.hidden && onActor ? filmPretend.textContent" in film and "cinePractice(text || real || pretend)" in film
    sub = _js_body(section, "  function cineSubject() {")
    assert "PLANNER.shot" in sub and "PLACE_AT[id]" in sub and "REC_VIEWS[id.slice(4)]" in sub
