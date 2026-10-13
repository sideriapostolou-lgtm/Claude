"""The 3D world's optional cinema mode (world3d's THE CINEMA section and its CSS block):
it is REAL MONEY ONLY (the owner's word, 2026-10-11: practice money nowhere but the Arena town's, which says PRACTICE
itself). Its one HUD line shows real money only, today's real result glowing a moment when a real settlement moves it;
the caption under the shot says who and what in the data's own words, never practice money (a character whose line is
about it is captioned by their job in plain words; a heart line keeps its real sentences), and crossfades; every
character has a small name tag with a two-to-four word job that never says practice; the vault's sign reads the real
cash and Rook's risk wall its real money only; the practice boards and props wait behind "details"; a programme keeps
only its real beats; the first visit gets one three-line card (every dollar on screen is real money but the Arena
town's); the director's rotation holds longer; and the "details" button (remembered when the browser allows it) brings
today's full view back exactly."""

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
_HEADER, _END = "= THE CINEMA (cinema mode,", '  resize(); BUS.emit("start", 0, 0);'
_KEYS = ("voss", "rook", "pip", "nyx", "jet", "mote")


@pytest.fixture(scope="module")
def page() -> str:
    return render_world_html(Settings.from_env({"DATA_DIR": "/tmp/nightcrawler-world-cinema-test"}))


@pytest.fixture(scope="module")
def module(page: str) -> str:
    return _module(page)


@pytest.fixture(scope="module")
def section(module: str) -> str:
    return module[module.index(_HEADER):module.index("// >>> tycoon data (pure)")]


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
    # These isolated tests exercise the optional camera tour, with the town overview switched off.
    return _node(pure + "\nfunction tycoonActive() { return false; }\n" + consts + body, tmp_path)


def _sentence(s: str) -> str:  # the caption's own sentence rule (cineSentence), for the expectations
    t = s.strip()
    t = t[:1].upper() + t[1:]
    return t if re.search(r"[.!?…]$", t) else t + "."


def _first(s: str) -> str:  # a long line's first sentence (cineSplit)
    m = re.match(r"^(.*?[a-z0-9)%]\.)\s+([A-Z].*)$", s.strip(), flags=re.DOTALL)
    return m.group(1) if m else s.strip()


# --------------------------------------------------------------------------- the optional camera tour


def test_legacy_scene_helpers_keep_money_filters_but_cannot_restore_old_controls(page: str, module: str, section: str) -> None:
    assert re.search(r'<body [^>]*class="cinema tycoon">', page)  # cinema's money filters also protect the overview
    assert '<button type="button" id="details" aria-pressed="false">details</button>' in page
    for part in ('<div id="lb-top"><button type="button" id="hud" aria-controls="panel">', '<b id="hud-cash">—</b>',
                 '<div id="lb-bot"><div id="cap" aria-live="off">', '<div id="tags" aria-hidden="true"></div>',
                 '<div id="intro" role="dialog" aria-labelledby="intro-title" hidden>'):
        assert part in page, part
    # Old display preferences cannot bring back the retired controls.
    assert "cineSet(true, false);" in section
    assert 'const CINE_KEY = "nightcrawler.world.details"' in section
    assert module.index("cineSet(true, false);") < module.index("tycoonBuildCrew(); tycoonView();")
    assert module.index("tycoonBuildCrew(); tycoonView();") < module.index(_END)
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
    assert out["win"] == [f"ACCOUNT CASH ${cash:.2f} · bots today (UTC) +$1.52 · goal $100/day", True, f"${cash:.2f}", ["up", ""]]
    assert out["lose"][0] == f"ACCOUNT CASH ${lose['plain']['real']['cash_usd']:.2f} · bots today (UTC) −$8.82 · goal $100/day"
    assert out["lose"][3] == ["down", ""]
    assert out["paused"][0].endswith(" · bots today (UTC) +$1.52 · paused · goal $100/day")
    assert out["stopped"][0].endswith(" · bots today (UTC) +$1.52 · stopped for today · goal $100/day")
    assert out["paper"] == ["ACCOUNT CASH — · off · goal $100/day", False, "—", ["state", ""]]
    assert out["none"][0] == "ACCOUNT CASH — · loading" and out["empty"][0] == "ACCOUNT CASH — · loading"
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
    assert win["usd"] == f"${real['cash_usd']:.2f}" and win["label"] == "POLYMARKET ACCOUNT CASH"
    since = states["winning"]["money"]["polymarket"]["real"]["since_start_usd"]
    assert win["accent"] == ("#58d68d" if since >= 0 else "#ff6b61")
    assert lose["label"] == "POLYMARKET ACCOUNT CASH"
    assert paper == {"usd": "—", "label": "ACCOUNT CASH · none reported", "accent": None}  # no pretend wallet
    # in cinema mode the sign is drawn again after the page's own (money.usd, money.label: the details view's) on each poll
    draw = _js_body(section, "  function cineVaultDraw() {")
    assert "if (CINE.on) { const v = cineVault(data); drawVaultSign(v.usd, v.label, v.accent); return; }" in draw
    assert 'drawVaultSign(fmtUsd(money.usd), money.label || "", since == null ? null' in draw  # (details: as before)
    assert "if (CINE.on) cineVaultDraw();" in _js_body(section, "  function cineOnData(")
    apply = _js_body(module, "  function apply(d) {")
    assert apply.index("drawVaultSign(fmtUsd(money.usd), money.label") < apply.index('BUS.emit("data", d, first);')


@needs_node
def test_cash_details_name_the_booked_day_and_each_source_check(pure: str, module: str, tmp_path: Path) -> None:
    out = _pure_run(pure, """
const page = {mode: "PAPER", money: {polymarket: {as_of: 1791820860,
  real: {cash_at: 1791820800, venue_at: 1791819900}}}};
const known = cineMoneyDetails(page); page.mode = "LIVE";
console.log(JSON.stringify({known: known, live: cineMoneyDetails(page), unknown: cineMoneyDetails(null),
  invalid: cineMoneyDetails({money: {polymarket: {as_of: Infinity, real: {cash_at: -1, venue_at: "today"}}}})}));
""", tmp_path)
    assert "not bot profit" in out["known"][0]
    assert "booked from 00:00 UTC" in out["known"][1] and "your own bets and deposits are excluded" in out["known"][1]
    assert out["known"][2] == "The town’s Bot today card uses Pacific midnight; this tour and safety limits show UTC."
    assert out["known"][3:] == ["Cash checked 2026-10-12 16:00 UTC.", "Positions checked 2026-10-12 15:45 UTC.",
                               "Desk report 2026-10-12 16:01 UTC."]
    assert "Bots today also includes the live Solana bot’s daily result." in out["live"]
    assert out["unknown"] == out["invalid"] == out["known"][:3]
    assert "cineMoneyDetails(data).forEach" in _js_body(module, "  function renderPanel() {")


# --------------------------------------------------------------------------- captions and job tags


_PRACTICE_WORDS = re.compile(r"\b(?:practi[cs](?:e|ing)\w*|pretend|paper)\b", re.IGNORECASE)


@needs_node
def test_the_practice_words_and_the_real_words(pure: str, tmp_path: Path) -> None:
    """The four rules a caption is made with: a place's line keeps only its sentences and clauses on real money; what a
    character does is a line with no practice money in it at all (strict: no money figure either); a job loses its
    practice money word; a sentence never splits inside "$1.52" or "U.S."."""
    out = _pure_run(pure, """
console.log(JSON.stringify({
  real: ["Real money is on only for Voss's small Polymarket bets; the rest is pretend money.",
         "No real money is being bet right now: everything is practice with pretend money.",
         "Scouting for the town all day. Practice today: +$2.40 (pretend money). One proven find could help keep the lights on.",
         "The town is up $1.52 in real money today. I deliver every trade on time; mine are practice (pretend money).",
         "Real money: $47.06 cash at Polymarket and no open bets; down $0.26 since start, 12 of 14 finished bets won.",
         "Will the U.S. hold rates at $1.52? Yes; a (paper) trade.", "", null].map((t) => cineReal(t)),
  strict: ["Every bet stays at 10 contracts, the owner's choice. Today's stop: $0.00 used of $30. I guard the town's savings.",
           "The town is up $1.52 in real money today. Up 0.5 SOL since noon.", "Down 40¢ on it. Then nothing."].map((t) => cineReal(t, true)),
  line: ["bought HIGGS for 0.1000 SOL (pretend money)", "Practice (pretend money): found a new coin", "found a new coin: NEWEST (61 min old)",
         "the AI judge said no to JUDGED: creator selling", "practicing the stop", "a paper trade", "  ", null].map((t) => cineLine(t)),
  lineStrict: ["sold HIGGS +$0.42", "sold HIGGS for 0.2 SOL", "NEWEST passed the scam check", "Daily stop hit: lost $3.20 today"].map((t) => cineLine(t, true)),
  job: ["places the Solana bot's trades (pretend money)", "bets on yes/no questions at Polymarket (real money) and asks the AI judge about coins",
        "bets on yes/no questions at Polymarket (pretend money) and asks the AI judge about coins", "keeps the tamper-proof records",
        "Jet places the Solana bot's trades (practice, pretend money)", "practice reps all day", null].map(cineJob),
  clauses: ["One. Two; three. Will the U.S. win $1.52? Yes.", "No stop", ""].map(cineClauses),
  split: ["Real money today: +$1.52, and it covers the bill. Same rule.", "Will the U.S. hold rates? Yes.", "One line only", "Down 3%. Then up."].map(cineSplit),
}));
""", tmp_path)
    assert out["real"] == ["Real money is on only for Voss's small Polymarket bets.", "",
                           "Scouting for the town all day. One proven find could help keep the lights on.",
                           "The town is up $1.52 in real money today. I deliver every trade on time.",
                           "Real money: $47.06 cash at Polymarket and no open bets; down $0.26 since start, 12 of 14 finished bets won.",
                           "Will the U.S. hold rates at $1.52? Yes.", "", ""]
    # strict (a character whose own money is practice): a figure stays only in a clause that says real
    assert out["strict"] == ["Every bet stays at 10 contracts, the owner's choice. I guard the town's savings.",
                             "The town is up $1.52 in real money today.", "Then nothing."]
    assert out["line"] == ["", "", "found a new coin: NEWEST (61 min old)", "the AI judge said no to JUDGED: creator selling", "", "", "", ""]
    assert out["lineStrict"] == ["", "", "NEWEST passed the scam check", ""]
    assert out["job"] == ["places the Solana bot's trades",
                          "bets on yes/no questions at Polymarket (real money) and asks the AI judge about coins",
                          "bets on yes/no questions at Polymarket and asks the AI judge about coins", "keeps the tamper-proof records",
                          "Jet places the Solana bot's trades", "", ""]
    assert out["clauses"] == [["One.", "Two;", "three.", "Will the U.S. win $1.52?", "Yes."], ["No stop"], []]
    # a long line splits after its first sentence, never inside "$1.52" or "U.S."
    assert out["split"] == [["Real money today: +$1.52, and it covers the bill.", "Same rule."], ["Will the U.S. hold rates? Yes.", ""],
                            ["One line only", ""], ["Down 3%.", "Then up."]]
    # (no look-behind in the pure block: an older phone's browser cannot read one, and the whole module would not run)
    assert "(?<" not in pure


@needs_node
def test_the_captions_come_from_the_data_and_say_real_money_only(pure: str, states: dict[str, dict[str, Any]], tmp_path: Path) -> None:
    win, paper = states["winning"], states["paper"]
    said = json.loads(json.dumps(win))
    said["plain"]["said"]["predict"] = {"ts": 1.0, "text": "bet $5.80 that the Packers win (real money)"}
    pretend_said = json.loads(json.dumps(win))
    pretend_said["plain"]["said"]["predict"] = {"ts": 1.0, "text": "practice bet (pretend money): $5.00 on YES · Will it rain?"}
    out = _pure_run(pure, """
const cap = (p, k, room) => cineCaption(p, k, room, k ? k.charAt(0).toUpperCase() + k.slice(1) : "");
const keys = ["voss", "rook", "pip", "nyx", "jet", "mote"], rooms = ["vault", "table", "observatory", "dock", "archive", "workshop", "den", null];
const all = (p) => keys.map((k) => cap(p, k, null)).concat(rooms.map((r) => cap(p, null, r)));
console.log(JSON.stringify({
  win: Object.fromEntries(keys.map((k) => [k, cap(WIN.plain, k, null)])), said: cap(SAID.plain, "voss", null),
  pretendSaid: cap(PSAID.plain, "voss", null),
  places: Object.fromEntries(rooms.map((r) => [String(r), cap(WIN.plain, null, r)])),
  paper: Object.fromEntries(keys.map((k) => [k, cap(PAPER.plain, k, null)])), paperTable: cap(PAPER.plain, null, "table"),
  none: cap(null, "voss", null), every: all(WIN.plain).concat(all(PAPER.plain)).concat(all(SAID.plain)).concat(all(PSAID.plain)),
}));
""", tmp_path, WIN=win, SAID=said, PSAID=pretend_said, PAPER=paper)
    p = win["plain"]
    hearts = {m["id"]: m["line"] for m in p["hearts"]["members"]}
    team = {t["id"]: t for t in p["team"]}
    # Voss: the Polymarket desk's newest REAL event in the server's plain words, else his goal line; his heart line second
    assert out["said"]["who"] == "VOSS" and out["said"]["rest"] == ", the real-money trader. Bet $5.80 that the Packers win (real money)."
    voss_line = p["goal"]["lines"]["voss"]  # (a goal line: its first sentence)
    assert _first(voss_line) != voss_line and out["win"]["voss"]["rest"] == ", the real-money trader. " + _sentence(_first(voss_line))
    assert out["pretendSaid"] == out["win"]["voss"]  # (a practice bet is never his caption: his goal line instead)
    assert out["win"]["voss"]["second"] == _sentence(hearts["voss"]) and out["win"]["voss"]["heart"] is True
    # Rook: today's real loss stop; his heart without its unlabelled figure (his own money word is practice's)
    assert out["win"]["rook"]["rest"] == ", the risk guard. " + _sentence(p["goal"]["floor_line"])
    assert "Today's stop:" in hearts["rook"] and out["win"]["rook"]["second"] == ("Every bet stays at 10 contracts, the owner's choice. "
                                                                                 "I guard the town's savings.")
    # Mote: the newest record; Pip and Nyx: their newest event, which has no practice money in it (no tag says practice)
    assert out["win"]["mote"]["rest"] == ", the record keeper. " + _sentence(team["mote"]["latest"])
    assert out["win"]["pip"]["rest"] == ", the coin scout. " + _sentence(team["pip"]["latest"])
    assert out["win"]["nyx"]["rest"] == ", the scam checker. " + _sentence(team["nyx"]["latest"])
    # Jet's newest event and his goal line are practice money: his job in plain words instead
    assert "(pretend money)" in team["jet"]["latest"] and "pretend money" in p["goal"]["lines"]["jet"]
    assert out["win"]["jet"]["rest"] == ", the trade runner. Places the Solana bot's trades."
    # the hearts keep their real sentences only ("Practice today: +$2.40 (pretend money)" is gone, figure and all)
    assert "Practice today: +$2.40" in hearts["pip"]
    assert out["win"]["pip"]["second"] == "Scouting for the town all day. One proven find could help keep the lights on."
    assert out["win"]["nyx"]["second"] == "Every scam I stop is money the town keeps."
    assert out["win"]["jet"]["second"] == "The town is up $1.52 in real money today. I deliver every trade on time."
    # the places: the vault's real money, the courtyard's real headline and goal, the observatory's labs, a room's keeper
    real, goal = p["real"], p["goal"]
    assert out["places"]["vault"] == {"who": "THE VAULT", "rest": " · " + _sentence(real["line"]), "second": _sentence(goal["reserve_line"]), "heart": False}
    assert p["headline"].endswith("; the rest is pretend money.")
    assert out["places"]["table"]["rest"] == " · Real money is on only for Voss's small Polymarket bets."
    assert out["places"]["table"]["second"] == _sentence(_first(goal["line"])) and out["places"]["null"] == out["places"]["table"]
    assert out["places"]["observatory"]["rest"] == " · " + _sentence(real["research"])
    assert out["places"]["dock"]["rest"] == " · Jet places the Solana bot's trades."
    # with real money off: Voss is the Polymarket trader (never "practice"), the courtyard says no practice line
    assert out["paper"]["voss"]["rest"].startswith(", the Polymarket trader.")
    assert p["headline"] != paper["plain"]["headline"] and out["paperTable"]["rest"] == ""
    # no caption, in any state, says practice, pretend or paper, or carries a practice figure
    pretend_figures = {"$2.40", "$1.72", "0.1000 SOL", f"${paper['money']['usd']:.2f}", f"${win['money']['usd']:.2f}"}
    pretend_figures -= {f"${win['plain']['real']['cash_usd']:.2f}"}
    for c in out["every"]:
        text = c["who"] + c["rest"] + " " + c["second"]
        assert not _PRACTICE_WORDS.search(text), text
        assert not any(f in text for f in pretend_figures), text
    # before the first poll a caption is the name alone
    assert out["none"] == {"who": "VOSS", "rest": "", "second": "", "heart": True}


@needs_node
def test_every_character_has_a_job_tag(pure: str, section: str, states: dict[str, dict[str, Any]], tmp_path: Path) -> None:
    out = _pure_run(pure, """
const tags = (p) => Object.fromEntries(CINE_ORDER.map((k) => [k, cineTag(k, cineTeam(p, k))]));
console.log(JSON.stringify({ keys: Object.keys(CINE_TAGS), tags: CINE_TAGS, win: tags(WIN.plain), paper: tags(PAPER.plain), none: tags(null) }));
""", tmp_path, WIN=states["winning"], PAPER=states["paper"])
    assert sorted(out["keys"]) == sorted(WORLD_CAST) == sorted(_KEYS)
    assert out["win"] == {"voss": "real-money trader", "rook": "risk guard", "pip": "coin scout", "nyx": "scam checker",
                          "jet": "trade runner", "mote": "record keeper"}
    # real money off: the plain words (never "practice"); no data: no claim
    assert out["paper"]["voss"] == "Polymarket trader" and out["none"] == {k: "" for k in _KEYS}
    for tag in out["tags"].values():
        assert sorted(tag) == ["plain", "real"]
        for words in tag.values():
            assert 2 <= len(words.split()) <= 4 and not _PRACTICE_WORDS.search(words), words
    assert out["tags"]["voss"]["real"] == "real-money trader" and all("real" not in t["plain"] for t in out["tags"].values())
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
    out = _pure_run(pure, "console.log(JSON.stringify([cineIntroLines(WIN.plain, true), cineIntroLines(WIN.plain, false), cineIntroLines(null, true)]));",
                    tmp_path, WIN=states["winning"])
    p = states["winning"]["plain"]
    assert out[0]["about"] == p["about"]  # what this is
    assert out[0]["team"] == [["Voss", "real-money trader"], ["Rook", "risk guard"], ["Pip", "coin scout"],
                              ["Nyx", "scam checker"], ["Jet", "trade runner"], ["Mote", "record keeper"]]
    # one short line: every dollar here is real money but the Arena town's (named only while the data has the Arena)
    assert out[0]["money"] == "Every dollar on screen is real money, except in the Arena town, which trains with practice money."
    assert out[1]["money"] == "Every dollar on screen is real money."
    assert out[2] == {"about": "", "team": [], "money": ""}
    assert len(out[0]["money"].split()) <= 20
    opener = _js_body(section, "  function cineIntroOpen(")
    assert "cineIntroSeen()" in opener and "setTimeout(function () { cineIntroClose(true); }, CINE_INTRO_MS)" in opener
    assert "para(cineIntroBody, L.about);" in opener and 'para(cineIntroBody, L.money, "money");' in opener
    assert "cineIntroLines(plain, CINE.arena)" in opener
    assert "CINE.arena = !!(d && d.money && d.money.arena);" in _js_body(section, "  function cineOnData(")
    # (the first poll opens the card from apply(), before the bus says "data": the card reads the Arena from the page)
    assert opener.index("CINE.arena = !!(data && data.money && data.money.arena);") < opener.index("cineIntroLines(plain, CINE.arena)")


@needs_node
def test_the_first_visit_card_names_the_arena_on_the_very_first_poll(pure: str, section: str, module: str,
                                                                       states: dict[str, dict[str, Any]], tmp_path: Path) -> None:
    """The page's own order on its first answer: apply() keeps the page (data), opens the card (openGuide ->
    cineIntroOpen), and only then says "data" on the bus (cineOnData). With an Arena in that very first answer the card
    says "except in the Arena town"; without one it does not."""
    apply = _js_body(module, "  function apply(d) {")
    assert apply.index("data = d;") < apply.index("openGuide();") < apply.index('BUS.emit("data", d, first);')
    fns = _js_body(module, "  function openGuide() {") + "\n" + _js_body(section, "  function cineIntroOpen(")
    page = json.loads(json.dumps(states["winning"]))
    page["money"]["arena"] = {"label": "pretend", "population": 24, "rent_usd": 1.0, "residents": [], "events": []}
    bare = json.loads(json.dumps(states["winning"]))
    bare["money"].pop("arena", None)
    out = _pure_run(pure, """
const made = [];
const document = { createElement: function (t) { const n = { tag: t, kids: [], className: "", textContent: "", appendChild: function (c) { this.kids.push(c); } }; made.push(n); return n; },
                   createTextNode: function (t) { return { textContent: t }; } };
const cineIntroBody = { kids: [], set textContent(v) { this.kids = []; }, appendChild: function (c) { this.kids.push(c); } };
const cineIntroEl = { hidden: true }, setTimeout = function () { return 1; }, clearTimeout = function () {};
const cineIntroSeen = function () { return false; }, cineIntroClose = function () {}, CINE_INTRO_MS = 30000;
const closePanel = function () {}, renderGuide = function () {}, armGuide = function () {}, guideDots = function () {};
function para(parent, text, cls) { if (!text) return null; const q = { tag: "p", className: cls || "", textContent: text }; parent.appendChild(q); return q; }
let data = null, plain = null, CINE = null;
""" + fns + """
const said = function (d) {
  CINE = { on: true, intro: false, introDone: false, introTimer: 0, arena: false };
  data = d; plain = d.plain; openGuide();  // (apply(): the page kept, then the card, then the bus)
  const money = cineIntroBody.kids.filter(function (k) { return k.className === "money"; })[0];
  return money ? money.textContent : null;
};
console.log(JSON.stringify([said(ARENA), said(BARE)]));
""", tmp_path, ARENA=page, BARE=bare)
    assert out[0] == "Every dollar on screen is real money, except in the Arena town, which trains with practice money."
    assert out[1] == "Every dollar on screen is real money."


def test_no_practice_money_in_the_cinema_but_the_towns_own_visit(page: str, section: str) -> None:
    """The Arena has no strip, ticker or line of its own in this view: nothing in the cinema's markup, style or code
    shows money.arena or plain.arena_line (the town's visits say its words, each beat's title PRACTICE MONEY once; the
    card above names it in one fixed line)."""
    cine = page[page.index('<div id="cine">'):page.index('<div id="intro"')]
    assert not re.search(r"arena|practice|pretend", cine, flags=re.IGNORECASE), cine
    assert 'id="arena' not in page and "#arena" not in _STYLE_CINEMA
    code = re.sub(r"//[^\n]*", "", section)
    for gone in ("arenaEl", "arenaTxt", "arenaLines", "arenaOnData", "arenaFrame", "arena_line", "ARENA."):
        assert gone not in code, gone
    # the only reads of the Arena: whether the data has one (the card's fixed line), never its figures or its words
    reads = re.findall(r"money\.arena[\w.\[]*", code)
    assert reads and set(reads) == {"money.arena"}, reads
    assert "arena:" not in _js_body(section, "  window.__skyport = Object.assign(window.__skyport || {}, { cinema: {")


@needs_node
def test_the_cinemas_words_never_carry_the_arenas_figures(pure: str, states: dict[str, dict[str, Any]], tmp_path: Path) -> None:
    """A page with a busy Arena (practice dollars in every resident, event and line): the HUD, the vault's sign and
    every character's and place's caption say none of its figures."""
    page = json.loads(json.dumps(states["winning"]))
    page["money"]["arena"] = {"population": 24, "rent_usd": 1.0, "result_usd": -143.86, "open_bets": 33, "start_cash": 20.0,
                              "residents": [{"id": "6", "name": "Fin-6", "money_usd": 13.57, "open": 3}],
                              "events": [{"ts": 1, "who": "Ada-1", "kind": "evicted", "usd": None,
                                          "text": "Ada-1 was evicted: went broke after 0.7 days (12 trades, -8.84 $)."}]}
    page["plain"]["arena_line"] = ("The Arena (practice money): 24 traders paying $1.00 rent a day; the town's trading "
                                   "-$143.86 so far, 33 bets open; leader Cy-3 up $2.13.")
    out = _pure_run(pure, """
const keys = ["voss", "rook", "pip", "nyx", "jet", "mote", null], rooms = ["vault", "table", "observatory", "dock", "archive", "workshop", "den"];
const caps = keys.map(function (k) { return cineCaption(P.plain, k, null, k || ""); }).concat(rooms.map(function (r) { return cineCaption(P.plain, null, r, ""); }));
console.log(JSON.stringify({ hud: cineHud(P), vault: cineVault(P), caps: caps }));
""", tmp_path, P=page)
    blob = json.dumps(out)
    for figure in ("13.57", "8.84", "143.86", "2.13", "Fin-6", "Ada-1", "Arena", "24 traders"):
        assert figure not in blob, figure


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
const recRealOnly = (on) => calls.push("realOnly:" + on), cineCapEl = {{ classList: {{ remove: (c) => calls.push("capIn") }} }};
const FILM = {{ on: false, script: [] }}, filmStop = (back) => {{ calls.push("filmStop:" + back); FILM.on = false; }};
let data = DATA;
{fns}
const snap = () => [cls.has("cinema"), cineDetails.textContent, cineDetails.attrs["aria-pressed"], CINE_BOARDS[0].m.material.id,
                    layers.on[layers.on.length - 1], signs[signs.length - 1], store[CINE_KEY] || null];
cineSet(true, false); const a = snap(), ca = calls.slice(); calls.length = 0;
cineSet(false, true); const b = snap(), cb = calls.slice(); calls.length = 0;
cineSet(true, true); const c = snap(), cc = calls.slice(); calls.length = 0;
// a programme already on air: one with a practice beat stops when the cinema comes back, a real one plays on
cineSet(false, true); FILM.on = true; FILM.script = [{{ cam: "view:goaltower", tag: "THE GOAL · REAL MONEY", text: "Real money today: +$1.52." }},
                                                   {{ cam: "view:yard", tag: "PRACTICE · PRETEND MONEY", text: "Practice (pretend money) never counts." }}];
calls.length = 0; cineSet(true, true); const stopped = calls.filter((x) => x.indexOf("filmStop") === 0);
cineSet(false, true); FILM.on = true; FILM.script = [FILM.script[0]]; calls.length = 0; cineSet(true, true);
const kept = calls.filter((x) => x.indexOf("filmStop") === 0);
console.log(JSON.stringify({{ a, b, c, ca, cb, cc, stopped, kept, filmOn: FILM.on }}));
""", tmp_path, DATA=states["winning"])
    win = states["winning"]
    cash, money = f"${win['plain']['real']['cash_usd']:.2f}", win["money"]
    real_sign = [cash, "POLYMARKET ACCOUNT CASH"]
    assert out["a"] == [True, "details", "false", "dark", ["disable", 1], real_sign, None]
    assert "realOnly:true" in out["ca"] and "capIn" in out["ca"]  # (Rook's wall real money only; the caption written afresh)
    # details: the class off (every hidden part back), the boards' own words and the trophies back, the page's own sign
    # (money.usd and exactly money.label), Rook's whole wall, remembered; the card drawn again for the full view
    assert out["b"] == [False, "simple view", "true", "page", ["enable", 1], [f"${money['usd']:.2f}", money["label"]], "1"]
    assert "renderCard" in out["cb"] and "introClose" in out["cb"] and "closePanel" not in out["cb"] and "realOnly:false" in out["cb"]
    # back to cinema: forgotten, the panel and the guide closed
    assert out["c"] == [True, "details", "false", "dark", ["disable", 1], real_sign, None]
    assert "closePanel" in out["cc"] and "closeGuide" in out["cc"] and "realOnly:true" in out["cc"]
    assert out["stopped"] == ["filmStop:true"] and out["kept"] == [] and out["filmOn"] is True


def test_the_practice_money_in_the_world_waits_behind_details(section: str, module: str) -> None:
    """The practice boards and props are on layer 1 (the cinema's camera does not film it; details enables it again):
    the practice yard with its own frame and posts, the trend desk's board, the trophy shelf and its card, the ticket
    board; a trade cube only while its trade's money is practice. Their own visibility logic is untouched."""
    assert ("const CINE_HIDDEN = [recTrophies, recTiles, board, recTrend, recCard, GP.yard, GP.yardFrame].filter(Boolean);"
            in section)
    assert "CINE_HIDDEN.forEach(function (m) { m.layers.set(1); });" in section
    assert "const CINE_BOARDS = [recLabs].filter(Boolean)" in section  # (the labs' words wait: a dark panel in its frame)
    boards = _js_body(section, "  function cineBoards(on) {")
    assert "if (on) camera.layers.disable(1); else camera.layers.enable(1);" in boards and "recRealOnly(on);" in boards
    code = re.sub(r"//[^\n]*", "", section)
    assert ".visible =" not in code
    # the yard's frame and posts are a mesh of their own (not merged with the set), so the whole yard goes
    goal = module[module.index("= THE GOAL (town goal)"):module.index("= THE HEARTS (team hearts)")]
    build = _js_body(goal, "  function goalBuild() {")
    assert "GP.yard = recBoard(F, 22.85, 1.12, -2.58, 0, 1024, 646, 1.3, 0.82, null);" in build  # (no rim merged into F)
    assert "GP.yardFrame = new THREE.Mesh(mergeGeometries(yardParts.map(prep), false), MAT.brass);" in build
    assert "scene.add(GP.yardFrame)" in build and 'F.add("brass", G.cyl(0.02, 0.02, 0.72, 8), [22.85' not in build
    # the cube: its money from the data (set when Jet picks it up for a closed trade), on the layer that money says
    assert "const cube = { mesh: new THREE.Group(), flight: null, real: false };" in module
    assert "cube.real = !!live;" in _js_body(module, "  function onClosed(t, live) {")
    cube = _js_body(section, "  function cineCube() {")
    assert "const real = cube.real === true;" in cube and "CINE_CUBE[i].layers.set(real ? 0 : 1);" in cube
    assert "const CINE_CUBE = [cubeOuter, cubeCore, cubeLattice, vaultFlash];" in section
    assert "cineCamera(); cineCube();" in _js_body(section, "  function cineFrame() {")
    # the trend desk's decorative screen comes back in the cinema (its board is hidden there)
    records = module[module.index("THE RECORD ROOM (Builder B)"):module.index("= THE GOAL (town goal)")]
    assert "REC.trendScreen.visible = !tr || REC.realOnly;" in _js_body(records, "  function recDrawTrend(tr) {")
    real_only = _js_body(records, "  function recRealOnly(on) {")
    assert "recDrawWall(REC.wall[0], REC.wall[1], REC.wall[2]);" in real_only
    assert "REC.trendScreen.visible = !recTrend.visible || REC.realOnly;" in real_only


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
    assert "let c = FILM.on ? cineFilmCaption() : null;" in capf and "cineCaption(plain, s.key, s.room" in capf
    write = _js_body(section, "  function cineCapWrite(c, now) {")
    assert "cineCap1.textContent = " in write and "createTextNode(c.rest)" in write and "innerHTML" not in write
    film = _js_body(section, "  function cineFilmCaption() {")
    # a programme's own words, real money only: its practice line is never read, a practice beat gives way to the live caption
    assert "filmPretend" not in film and "if (b && !cineBeat(b)) return null;" in film
    assert "cineReal(filmText.textContent)" in film and "cineReal(filmReal.textContent)" in film
    sub = _js_body(section, "  function cineSubject() {")
    assert "PLANNER.shot" in sub and "PLACE_AT[id]" in sub and "REC_VIEWS[id.slice(4)]" in sub


@needs_node
def test_the_caption_crossfades_and_holds_a_moment(section: str, tmp_path: Path) -> None:
    """A new caption fades the old words out, then writes its own and fades in (never a blink); the first one, and every
    one for a reader who asked for less motion, is written at once; the same subject's newer words wait until its caption
    has been up a moment (a name alone gives way at once: a programme's words arriving)."""
    fns = "\n".join(_js_body(section, f"  function {n}(") for n in ("cineCapFrame", "cineCapWrite"))
    body = """
let now = 1000, simT = 0, plain = null, CINE_CALM = false;
const performance = { now: () => now };
const CINE_CAP_FADE_MS = 340, CINE_CAP_MIN_MS = 2600;
const CINE = { capAt: 0, cap: "", capNext: null, capSwapAt: 0, capShownAt: 0, capWho: "", capRest: "" };
const FILM = { on: false }, cineFilmCaption = () => null, CAST = {};
let next = { who: "VOSS", rest: ", the real-money trader. A.", second: "", heart: true };
const cineSubject = () => ({ key: "voss", room: "table" }), cineCaption = () => next;
const cls = new Set(), cineCapEl = { classList: { add: (c) => cls.add(c), remove: (c) => cls.delete(c) } };
const node = () => ({ textContent: "", hidden: false, kids: [], appendChild(n) { this.kids.push(n); this.textContent += n.textContent; } });
const cineCap1 = node(), cineCap2 = node();
const document = { createElement: () => ({ textContent: "" }), createTextNode: (t) => ({ textContent: t }) };
""" + fns + """
const shown = () => [cineCap1.textContent, cls.has("out")];
const step = (ms) => { now += ms; simT += ms / 1000; cineCapFrame(); return shown(); };
const out = {};
out.first = step(0);                                      // the first caption: at once
next = { who: "VOSS", rest: ", the real-money trader. B.", second: "", heart: true };
out.held = step(300);                                     // the same subject's newer words: not yet (up 0.3 s)
out.later = step(2500);                                   // up 2.8 s: the old words fade out
out.swapped = step(400);                                  // then the new ones, fading in
next = { who: "ROOK", rest: ", the risk guard. C.", second: "", heart: true };
out.cut = step(300);                                      // another subject: fades out at once (no hold)
out.cutIn = step(400);
CINE_CALM = true; next = { who: "PIP", rest: ", the coin scout. D.", second: "", heart: true };
out.calm = step(300);                                     // less motion: written at once, no fade
console.log(JSON.stringify(out));
"""
    out = _node(body, tmp_path)
    assert out["first"] == ["VOSS, the real-money trader. A.", False]
    assert out["held"] == ["VOSS, the real-money trader. A.", False]
    assert out["later"] == ["VOSS, the real-money trader. A.", True]
    assert out["swapped"] == ["VOSS, the real-money trader. B.", False]
    assert out["cut"] == ["VOSS, the real-money trader. B.", True]
    assert out["cutIn"] == ["ROOK, the risk guard. C.", False]
    assert out["calm"] == ["PIP, the coin scout. D.", False]
    cap = [b for sels, b in _rules(_STYLE_CINEMA) if "#cap" in sels]
    assert any("transition: opacity .34s ease" in b for b in cap) and any("transition: none" in b for b in cap)
    assert "@media (prefers-reduced-motion: reduce) { #cap { transition: none; } }" in _STYLE_CINEMA
    assert any("opacity: 0" in b for sels, b in _rules(_STYLE_CINEMA) if "#cap.out" in sels)


@needs_node
def test_todays_real_result_glows_when_a_real_settlement_moves_it(pure: str, section: str, tmp_path: Path) -> None:
    out = _pure_run(pure, """
console.log(JSON.stringify([cineTick(1.52, 2.10), cineTick(1.52, -0.4), cineTick(1.52, 1.524), cineTick(null, 1.52), cineTick(1.52, null),
  cineHud({ plain: { real: { on: true, cash_usd: 47.06 }, goal: { target_text: "$100" } }, town: { goal: { real_today_usd: 1.52 } } }).today]));
""", tmp_path)
    assert out == ["up", "down", "", "", "", 1.52]
    draw = _js_body(section, "  function cineHudDraw(d) {")
    # (today's figure only, never the cash: a new bet moves the cash too, and that is no loss)
    assert "const tick = cineTick(CINE.today, h.today);" in draw and '(q.today && tick ? " tick tick-" + tick : "")' in draw
    assert "if (cineNum(h.today)) CINE.today = h.today;" in draw
    tick = [b for sels, b in _rules(_STYLE_CINEMA) if "#hud-rest .tick" in sels]
    assert any("animation: hudtick" in b for b in tick) and any("animation: none" in b for b in tick)  # (still for less motion)
    assert not any(red in b for b in tick for red in _REDS)  # (it glows in the figure's own colour: no colour of its own)


# --------------------------------------------------------------------------- the programmes: real beats only


@needs_node
def test_a_programme_in_the_cinema_keeps_only_its_real_beats(pure: str, module: str, states: dict[str, dict[str, Any]],
                                                              tmp_path: Path) -> None:
    """The record room's progStart asks THE CINEMA's filter (progKeep): in cinema mode a programme has no beat on practice
    money (the goal's practice beats, the practice boards' views, a beat on someone whose words speak of practice money);
    the details view plays every beat as before."""
    w = states["winning"]["plain"]["goal"]
    boards = {"tower": "goaltower", "bill": "billplaque", "board": "goalboard", "yard": "yard", "vault": "riskwall",
              "power": "power", "promenade": "promenade"}
    tour = [{"cam": "view:" + boards[b["who"]] if b["who"] in boards else b["who"], "tag": b["tag"], "text": b["text"]}
            for b in w["programmes"]["tour"]]
    recap = [{"cam": "", "tag": "YESTERDAY", "text": "What the team did, from its own records: 3 moments of 40 records."},
             {"cam": "jet", "tag": "YESTERDAY", "text": "bought HIGGS for 0.1000 SOL (pretend money)"},
             {"cam": "voss", "tag": "YESTERDAY · REAL MONEY", "text": "bet $5.80 that the Packers win (real money)"},
             {"cam": "mote", "tag": "YESTERDAY", "text": "sealed record #3 in the tamper-proof log"},
             {"cam": "view:riskwall", "tag": "YESTERDAY · THE VAULT", "text": "", "real": "Real money: up $1.20.", "pretend": "Practice: +$3 (pretend)."},
             {"cam": "view:trophies", "tag": "THE RECORDS", "text": "A trophy per win and a tile per loss."},
             {"cam": "view:trend", "tag": "THE RECORDS", "text": "Pretend money: in or out of each coin."}]
    start = _js_body(module, "  function progStart(kind, script, auto) {")
    out = _pure_run(pure, """
const CINE = { on: true }, started = [];
let progKeep = function (b) { return !CINE.on || cineBeat(b); };
let FILM = { on: false }; const filmStop = () => {}, closePanel = () => {}, closeGuide = () => {}, filmIncoming = () => {}, filmChips = () => {}, filmStep = () => {};
const card = { getBoundingClientRect: () => ({ bottom: 700 }) }, window = { innerHeight: 780 }, simT = 0;
const filmEl = { style: {}, hidden: true }, body = { classList: { add: () => {} } };
""" + start + """
const run = (script) => { FILM = { on: false }; progStart("goal", script, false); return FILM.script ? FILM.script.map((b) => b.cam + "|" + b.tag) : null; };
const cinema = { tour: run(TOUR), recap: run(RECAP), practiceOnly: progStart("goal", [TOUR.find((b) => b.cam === "view:yard")], false) };
CINE.on = false;
const details = { tour: run(TOUR), recap: run(RECAP) };
console.log(JSON.stringify({ cinema, details }));
""", tmp_path, TOUR=tour, RECAP=recap)
    kept = out["cinema"]["tour"]
    assert [b.split("|")[0] for b in kept] == [b["cam"] for b in tour if b["tag"] == "THE GOAL · REAL MONEY" and b["cam"] not in ("pip", "nyx", "jet")]
    assert not any("view:yard" in b or "PRACTICE" in b for b in kept)
    assert {b["cam"] for b in tour if b["tag"] == "PRACTICE · PRETEND MONEY"} >= {"view:yard"}  # (the harness has practice beats)
    assert out["cinema"]["recap"] == ["|YESTERDAY", "voss|YESTERDAY · REAL MONEY", "mote|YESTERDAY", "view:riskwall|YESTERDAY · THE VAULT"]
    assert out["cinema"]["practiceOnly"] is False  # (nothing real left: no programme at all)
    assert len(out["details"]["tour"]) == len(tour) and len(out["details"]["recap"]) == len(recap)  # (details: every beat)
    assert "if (progKeep) script = script.filter(progKeep);" in start and "let progKeep = null;" in module
    assert "progKeep = function (b) { return !CINE.on || cineBeat(b); };" in module


# --------------------------------------------------------------------------- Rook's risk wall: real money only


@needs_node
def test_rooks_wall_in_the_cinema_is_real_money_only(module: str, tmp_path: Path) -> None:
    from tests.test_world_records import _helpers, _section

    sec = _section(module)
    tables = "\n".join(re.search(r"^" + re.escape(s) + r".*$", sec, re.MULTILINE).group(0)  # type: ignore[union-attr]
                       for s in ("  const REC_STOPS = ", "  const REC_DESKS = "))
    out = _node(_helpers(module) + f"""
const recWall = board(1024, 720);
{tables}
{_js_body(sec, "  function recBar(")}
{_js_body(sec, "  function recDeskWords(d) {")}
{_js_body(sec, "  function recDrawWall(wall, caps, label) {")}
const wall = {{ allowance_used_pct: 25, slots_used: 1, slots_max: 3, daily_stop: false,
  desks: [{{ desk: "Polymarket paper", verdict: "winning", paused: false }}, {{ desk: "Polymarket real", verdict: "losing", paused: false }}] }};
const caps = {{ label: "Real money", on: true, open_usd: 4.82, open_max_usd: 30, day_loss_usd: 0.97, day_max_usd: 30, total_loss_usd: 2.52, total_max_usd: 40 }};
REC.realOnly = true;
recDrawWall(wall, caps, "Paper money (pretend)"); const real = painted();
recDrawWall(Object.assign({{}}, wall, {{ desks: [wall.desks[0]] }}), caps, "Paper money (pretend)"); const none = texts();
recDrawWall(wall, caps, "Real money"); const live = texts();
REC.realOnly = false; recDrawWall(wall, caps, "Paper money (pretend)"); const full = texts();
console.log(JSON.stringify({{ real, none, live, full }}));
""", tmp_path)
    words = [d["t"] for d in out["real"]]
    assert words[:2] == ["ROOK'S RISK WALL · REAL MONEY", "The desks' risk manager · real money"]
    for t in ("Polymarket REAL money", "losing", "Real money · the Polymarket desk's hard limits", "Account open", "$4.82 incl. yours", "Bot cap $30.00", "$0.97 of $30.00",
              "$2.52 of $40.00"):
        assert t in words, t
    assert "$4.82 of $30.00" not in words  # account positions also include the owner's bets, outside the bot's cap
    # no practice anywhere on it: not the Solana bot's practice half, not the practice desk, not its verdict
    for t in words:
        assert not _PRACTICE_WORDS.search(t) and "Solana" not in t and "slots" not in t and "%" not in t, t
    colour = {d["t"]: d["fill"] for d in out["real"]}
    assert colour["Polymarket REAL money"] in _REDS and colour["losing"] in _REDS  # (red: the real desk only)
    assert "no verdict on real money yet" in out["none"] and not any("Polymarket practice" in t for t in out["none"])
    # while the Solana bot trades real money its half is real money too, and stays
    assert "Solana bot · Real money" in out["live"] and "Polymarket practice (pretend money)" not in out["live"]
    # the details view: the whole wall as before (the record room's own test pins its words)
    assert "Solana bot · Paper money (pretend)" in out["full"] and "Polymarket practice (pretend money)" in out["full"]
    assert out["full"][0] == "ROOK'S RISK WALL"
