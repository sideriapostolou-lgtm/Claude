"""The 3D world's town (world3d's THE TOWN section and its CSS block): the Arena, a PRACTICE town of trader bots, as a
district of its own. One house per resident (floors by its money, windows lit while it has bets open, a name plate), a
lot left VACANT by an eviction until a newcomer's house rises there; only the page's new events move it, each once,
spread over the poll; the town hall's board and every caption say practice once and never red; the cinema visits it
through the record room's views and programmes and never edits the director. The section's pure block runs here in Node
over pages the Arena itself made (nightcrawler.arena, nightcrawler.pagestate.arena_town)."""

from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from nightcrawler import arena as A
from nightcrawler import pagestate
from nightcrawler import polydesk as P
from nightcrawler.config import Settings
from nightcrawler.world3d import (
    _MODULE,
    _STYLE_CHANNEL,
    _STYLE_TOWN,
    _STYLES,
    render_world_html,
)
from tests.test_world3d import _js_body, _module, _node
from tests.test_world_records import _REDS, _helpers

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
_HEADER = "= THE TOWN (the Arena)"
_HEARTS, _DIRECTOR = "= THE HEARTS (team hearts)", "= THE LIVE DIRECTOR: an always-on broadcast"
_LOOP, _CINEMA = "= THE LOOP (paused", "= THE CINEMA (cinema mode"
#: 2026-10-11 20:28:05 UTC: 3 h 31 min 55 s before the next rent (00:00 UTC)
NOW = datetime(2026, 10, 11, 20, 28, 5, tzinfo=UTC).timestamp()


@pytest.fixture(scope="module")
def page() -> str:
    return render_world_html(Settings.from_env({"DATA_DIR": "/tmp/nightcrawler-world-town-test"}))


@pytest.fixture(scope="module")
def module(page: str) -> str:
    return _module(page)


@pytest.fixture(scope="module")
def section(module: str) -> str:
    return module[module.index(_HEADER):module.index(_DIRECTOR)]


@pytest.fixture(scope="module")
def pure(section: str) -> str:
    return section[section.index("// >>> town (pure)"):section.index("// <<< town")]


def _code(text: str) -> str:
    """The source without its line comments."""
    return re.sub(r"//[^\n]*", "", text)


def _market(slug: str, hours: float = 6.0) -> dict[str, Any]:
    return {"slug": slug, "question": f"Will {slug} happen?", "event": f"{slug} by tonight?", "category": "crypto",
            "end_ts": NOW + hours * 3600, "fee_coef": 0.0695}


def _q(bid: float, ask: float) -> dict[str, Any]:
    return {"best_bid": bid, "best_ask": ask, "state": P.OPEN_STATE}


@pytest.fixture(scope="module")
def town(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Four polls of the page as the server would build them from the Arena's own runs: the town as it opened (no
    events), a round of buys, a round of sales (some won, some lost) and a round where two went broke (evicted) and two
    children moved in."""
    tmp = tmp_path_factory.mktemp("world-town")
    settings = Settings.from_env({"DATA_DIR": str(tmp)})
    arena = A.Arena(settings)
    t0 = NOW - 600
    arena.poll(t0, markets=[], quotes={})
    for i, res in enumerate(arena.state["residents"].values()):
        res["genes"] = {"lo": 0.40, "width": 0.2, "tp": 0.05, "sl": 0.10, "hold_h": 6.0, "max_spread": 0.03,
                        "stake": 0.5, "horizon_h": 24.0, "family": "crypto", "side": "yes"}
        if i % 3 == 2:
            res["genes"]["family"] = "weather"  # (a third stay out of the market: lit and dark windows both)
    markets = [_market("btc-up"), _market("eth-up")]
    pages = []

    def snap(now: float) -> dict[str, Any]:
        money = pagestate.arena_town(settings, now)
        assert money is not None
        return {"generated_at": now, "money": {"arena": money}, "plain": {"arena_line": A.arena_line(money)}}

    pages.append(snap(t0 + 5))
    arena.poll(t0 + 60, markets=markets, quotes={"btc-up": _q(0.49, 0.50), "eth-up": _q(0.49, 0.50)})
    pages.append(snap(t0 + 65))
    arena.poll(t0 + 120, markets=markets, quotes={"btc-up": _q(0.56, 0.57), "eth-up": _q(0.38, 0.39)})
    pages.append(snap(t0 + 125))
    poor = [r for r in arena.state["residents"].values() if not r["positions"]][:2]
    for r in poor:
        r["cash"] = 0.4
    arena.poll(t0 + 180, markets=markets, quotes={"btc-up": _q(0.56, 0.57), "eth-up": _q(0.38, 0.39)})
    pages.append(snap(NOW))
    return {"pages": pages, "poor": [r["name"] for r in poor]}


def _run(pure: str, body: str, tmp_path: Path, **data: Any) -> Any:
    consts = "".join(f"const {k} = {json.dumps(v)};\n" for k, v in data.items())
    return _node(pure + "\n" + consts + body, tmp_path)


# --------------------------------------------------------------------------- where the section sits


def test_the_town_is_its_own_section_after_the_hearts_and_before_the_director(page: str, module: str,
                                                                                section: str) -> None:
    assert module.index(_HEARTS) < module.index(_HEADER) < module.index(_DIRECTOR) < module.index(_LOOP)
    assert "+ _M_TOWN" not in module and _MODULE.index(_HEADER) < _MODULE.index(_DIRECTOR)
    # on the page's bus (no line in THE LOOP), a fault stops the town and never the world
    code = _code(section)
    assert 'BUS.on("data", townOnData);' in code and 'BUS.on("frame", townFrame);' in code and "BUS.emit(" not in code
    assert "try { townBuild(); TOWN.ok = true; }" in code
    assert "try { townStep(clamp(dt, 0, 0.1)); } catch (e) { TOWN.ok = false;" in _js_body(section, "  function townFrame(")
    assert "townFrame" not in _js_body(module, "  function frame(now) {")
    # text only, no storage of its own
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "new Function", "document.write", "localStorage"):
        assert sink not in section, sink
    assert "window.__skyport = Object.assign(window.__skyport || {}, { town: {" in section
    for hook in ("houses: function ()", "lots: function ()", "events: function ()", "queue: function ()", "board: function ()",
                 "visit: function ()", "view: function (id, hold)", "state: function ()"):
        assert hook in section, hook
    # its CSS in the page's one style (hashed by the CSP), before the channel's and the cinema's
    (style,) = re.findall(r"<style>(.*?)</style>", page, flags=re.DOTALL)
    assert style == _STYLES and _STYLE_TOWN in style and style.index(_STYLE_TOWN) < style.index(_STYLE_CHANNEL)
    assert "#film.practice {" in _STYLE_TOWN


def test_the_town_never_edits_the_live_director(module: str, section: str) -> None:
    """It films through the record room's views and programmes (recViewOf, recView, progStart("town")) and reads FILM,
    focus, pinned and the channel's replay only: no planner, rig, cut or flight of its own, no event of the crew's."""
    director = module[module.index(_DIRECTOR):module.index(_LOOP)]
    cinema = module[module.index(_CINEMA):module.index('  resize(); BUS.emit("start", 0, 0);')]
    for name in ("TOWN", "townStep", "townVisit", "townFrame", "TP.", "TL["):
        assert name not in director and name not in cinema, name
    code = _code(section)
    for foreign in ("PLANNER.", "RIGS[", "togglePin(", "startShot(", "setFov(", " cut(", "focusOn(", "speak(", "oneShot(",
                    "FLY.", "liveDirector(", "CINE.", "cineCap", "arenaEl"):
        assert foreign not in code, foreign
    assert code.count('progStart("town", ') == 1 and code.count("recViewOf(") == 3
    for view in ('recViewOf("town", ', 'recViewOf("townhall", ', 'recViewOf("townhouse", '):
        assert view in code, view
    # in the cinema only, when nothing else is on (no guide, panel, programme, pin, fresh moment, replay, first-visit card)
    free = _js_body(section, "  function townFree(")
    for cond in ("guideEl.hidden", "!panelKind", "!FILM.on", "!replay", "!pinned", "!(focus && simT < focus.until)", "c.intro()"):
        assert cond in free, cond
    step = _js_body(section, "  function townStep(")
    assert "townCinema() && townFree()) townVisit(false);" in step
    assert "if (rp && rp.real === true) filmStop(true);" in step  # (a real-money replay first)
    # the details view: a "town" chip after "records" (the visit, or back to live)
    chip = _js_body(section, "  function townChipMake(")
    assert 'b.textContent = "town"' in chip and "chips.insertBefore(b, REC.tourChip.nextSibling)" in chip
    assert 'if (FILM.on && FILM.kind === "town") filmStop(true); else townVisit(true);' in chip


def test_practice_is_said_once_and_never_red(section: str) -> None:
    code = _code(section).lower()
    for red in _REDS:
        assert red not in code, red  # (the board, the plates, the puffs: blue, slate, lilac, mint and gold)
    assert "0xff6b61" not in code and "0xcf3129" not in code
    strings = re.findall(r'"((?:[^"\\]|\\.)*)"', _code(section))
    assert not [s for s in strings if re.search(r"\breal\b", s, flags=re.IGNORECASE)], "the town never says real"
    assert 'TOWN_TAG = "PRACTICE MONEY", TOWN_TITLE = "THE TOWN · PRACTICE MONEY"' in section
    assert "pretend" not in " ".join(strings).lower()


def test_the_frame_step_allocates_nothing(section: str) -> None:
    """Once a frame: numbers only (the moments' records, the pools and the scratch vectors are made at a poll or once)."""
    for name in ("townQueue", "townHouses", "townWrite", "townFx", "townAmbient", "townReady", "townFlush"):
        body = _code(_js_body(section, f"  function {name}("))
        for banned in ("new ", "function (", ".map(", ".filter(", ".concat(", ".slice(", "JSON", "[]", "{}", "=> "):
            assert banned not in body, (name, banned)
    step = _code(_js_body(section, "  function townStep("))
    for banned in ("new ", ".map(", ".filter(", "JSON", "=> "):
        assert banned not in step, banned
    assert "const TOWN_WAIT = new Uint8Array(TOWN_LOTS);" in section and "TOWN_WAIT.fill(0);" in section
    # 24 houses in four instanced draws, the plates in one, the smoke and the puffs in one Points each
    for part in ("TP.body = new THREE.InstancedMesh(bodyGeo, bodyMat, TOWN_LOTS);", "TP.roof = new THREE.InstancedMesh(",
                 "TP.chim = new THREE.InstancedMesh(", "TP.flags = new THREE.InstancedMesh(", "TP.plates = new THREE.Mesh(pg,",
                 "TP.smoke = new THREE.Points(", "TP.puffs = new THREE.Points(", "TP.coins = new THREE.InstancedMesh(",
                 "TP.parcels = new THREE.InstancedMesh("):
        assert part in section, part


# --------------------------------------------------------------------------- the pure block in Node


@needs_node
def test_floors_lots_and_families(pure: str, tmp_path: Path) -> None:
    out = _run(pure, r"""
const lots = townLots(TOWN_LOTS);
let near = 1e9;
for (let i = 0; i < lots.length; i++) for (let j = i + 1; j < lots.length; j++) near = Math.min(near, Math.hypot(lots[i].x - lots[j].x, lots[i].z - lots[j].z));
const faces = lots.every(function (q) { const r = Math.hypot(q.x, q.z); return Math.abs(Math.sin(q.yaw) + q.x / r) < 1e-9 && Math.abs(Math.cos(q.yaw) + q.z / r) < 1e-9; });
const half = 1.32 / Math.SQRT2;  // (a house's half diagonal: clear of the street, the hall and the market whichever way it turns)
const street = lots.filter(function (q) { return q.x + half > 1.95 && Math.abs(q.z) - half < 1.15; }).length;
const hall = lots.filter(function (q) { return Math.abs(q.x) - half < 2.05 && q.z + half > -8.1 && q.z - half < -4.85; }).length;
const market = lots.filter(function (q) { return Math.hypot(q.x, q.z) - half < 1.95; }).length;
console.log(JSON.stringify({ n: lots.length, near: near, faces: faces, street: street, hall: hall, market: market,
  rings: lots.map(function (q) { return q.ring; }).join(""), rim: Math.max.apply(null, lots.map(function (q) { return Math.hypot(q.x, q.z) + half; })),
  floors: [0, -3, null, NaN, 7.99, 8, 20, 24, 47.9, 48, 1000].map(townFloors),
  fam: ["crypto, YES 0.40-0.60, +0.05 / -0.10, 6 h", "weather, NO", "sports", "other, YES", "", null, "Crypto , x"].map(townFamily) }));
""", tmp_path)
    assert out["n"] == 24 and out["near"] > 1.85 and out["faces"] is True  # (each door toward the market)
    assert out["street"] == 0 and out["hall"] == 0 and out["market"] == 0 and out["rim"] < 7.3  # (inside the lawn)
    assert out["rings"] == "0" * 8 + "1" * 16  # the inner ring first
    assert out["floors"] == [1, 1, 1, 1, 1, 2, 3, 4, 6, 7, 7]  # one floor more for each $8 ($20 to start: three)
    assert out["fam"] == ["crypto", "weather", "sports", "", "", "", "crypto"]


@needs_node
def test_everyone_keeps_their_lot_and_a_newcomer_takes_the_longest_vacant(pure: str, tmp_path: Path) -> None:
    out = _run(pure, r"""
const R = function (ids) { return ids.map(function (id) { return { id: id, name: "N-" + id }; }); };
const a = townAssign(null, R(["1", "2", "3"]), 5, 10);
const old = JSON.stringify(a.lots);
const b = townAssign(a.lots, R(["3", "1"]), 5, 20);  // 2 gone at 20
const c = townAssign(b.lots, R(["4", "3"]), 5, 30);  // 1 gone at 30; 4 takes 2's lot (vacant longest), not a never-lived one
const d = townAssign(c.lots, R(["4", "3", "5", "6", "7", "8"]), 5, 40);  // 5 takes 1's lot, then the never-lived ones; 8: no lot
const e = townAssign(d.lots, [{ id: "4", name: "N-4" }, { id: "4", name: "dup" }, { name: "no id" }, null, { id: "", name: "x" }], 5, 50);
console.log(JSON.stringify({ a: a, unchanged: JSON.stringify(a.lots) === old, b: b, c: c, d: d, e: e }));
""", tmp_path)
    ids = lambda m: [q["id"] for q in m["lots"]]
    assert ids(out["a"]) == ["1", "2", "3", None, None] and [b["lot"] for b in out["a"]["born"]] == [0, 1, 2]
    assert out["unchanged"] is True and out["a"]["lots"][3] == {"id": None, "at": -1}
    assert ids(out["b"]) == ["1", None, "3", None, None] and out["b"]["gone"] == [{"lot": 1, "id": "2", "name": "N-2"}]
    assert out["b"]["lots"][1] == {"id": None, "at": 20} and out["b"]["born"] == []
    assert ids(out["c"]) == [None, "4", "3", None, None] and out["c"]["born"] == [{"lot": 1, "id": "4", "name": "N-4"}]
    assert out["c"]["gone"] == [{"lot": 0, "id": "1", "name": "N-1"}]
    assert ids(out["d"]) == ["5", "4", "3", "6", "7"] and [b["lot"] for b in out["d"]["born"]] == [0, 3, 4]
    assert ids(out["e"]) == [None, "4", None, None, None] and len(out["e"]["gone"]) == 4 and out["e"]["born"] == []


@needs_node
def test_only_new_events_play_each_once_oldest_first(pure: str, tmp_path: Path) -> None:
    out = _run(pure, r"""
const seen = { keys: {}, order: [] };
const ev = function (ts, who, kind, text, usd) { return { ts: ts, who: who, kind: kind, text: text, tone: "neutral", usd: usd == null ? null : usd }; };
const p1 = [ev(10, "Ada-1", "buy", "Ada-1 bought YES", 2), ev(10, "Bo-2", "buy", "Bo-2 bought NO", 3)];
const first = townFresh(p1, seen, true);
const again = townFresh(p1, seen, false);
// newest first, as the page lists them: one resident sells and buys in the same round (same ts and who: both play)
const p2 = [ev(20, "Ada-1", "buy", "Ada-1 bought NO", 1), ev(20, "Ada-1", "sale", "Ada-1 took profit +0.40 $", 0.4),
            ev(20, "Cy-3", "", "an old line without a kind", null), "junk", null].concat(p1);
const second = townFresh(p2, seen, false).map(function (e) { return e.kind + ":" + e.text; });
const many = []; for (let i = 0; i < 700; i++) many.unshift(ev(100 + i, "X-" + i, "buy", "x", 1));  // (newest first)
townFresh(many, seen, false);
console.log(JSON.stringify({ first: first, again: again, second: second, size: seen.order.length, keys: Object.keys(seen.keys).length,
  max: TOWN_SEEN_MAX, oldest: seen.order[0] }));
""", tmp_path)
    assert out["first"] == [] and out["again"] == []  # (the first poll is the town as it stands; nothing twice)
    assert out["second"] == ["sale:Ada-1 took profit +0.40 $", "buy:Ada-1 bought NO"]  # (oldest first; a kindless line: none)
    assert out["size"] == out["keys"] == out["max"] == 600 and out["oldest"].startswith("200|X-100|")


@needs_node
def test_the_plan_turns_each_kind_into_its_moment_in_order(pure: str, tmp_path: Path) -> None:
    out = _run(pure, r"""
const e = function (who, kind, usd) { return { ts: 1, who: who, kind: kind, text: who + " " + kind, usd: usd }; };
const moves = { gone: [{ lot: 4, id: "9", name: "Gus-9" }, { lot: 6, id: "12", name: "Lux-12" }],
                born: [{ lot: 4, id: "25", name: "Yul-25" }, { lot: 6, id: "26", name: "Zed-26" }] };
const lotOf = { "Ada-1": 0, "Bo-2": 1, "Yul-25": 4, "Zed-26": 6, "Gus-9": 4, "Lux-12": 6 };
const fresh = [e("Ada-1", "buy", 2), e("Bo-2", "sale", 0.42), e("Bo-2", "sale", -0.21), e("Ada-1", "sale", 0), e("Ada-1", "sale", null),
               e("Gus-9", "sale", -1.1), e("Gus-9", "evicted", null), e("Yul-25", "born", null), e("Zed-26", "buy", 1.5), e("Nobody-0", "buy", 1)];
const plan = townPlan(fresh, moves, lotOf).map(function (q) { return q.act + "@" + q.lot + ":" + q.who + (q.ev ? "" : "*"); });
console.log(JSON.stringify({ plan: plan, gaps: [townGap(1, 15), townGap(2, 15), townGap(24, 15), townGap(100, 15)],
  spot: townSpot([{ act: "parcel" }, { act: "coins" }, { act: "rise", done: true }, { act: "coins" }, { act: "even" }, { act: "rise", hold: true }]),
  none: townSpot([{ act: "even" }, { act: "parcel", done: true }]) }));
""", tmp_path)
    assert out["plan"] == ["parcel@0:Ada-1", "coins@1:Bo-2", "puff@1:Bo-2", "even@0:Ada-1", "even@0:Ada-1",
                           "puff@4:Gus-9", "sink@4:Gus-9", "rise@4:Yul-25",
                           # a newcomer's first trade waits for its house: Lux-12 goes first (no event: *), Zed-26 rises
                           "sink@6:Lux-12*", "rise@6:Zed-26*", "parcel@6:Zed-26"]
    assert out["gaps"] == [0, 1.6, 0.5, 0.45]  # (spread over the poll, never a burst, never a crawl)
    assert out["spot"] == 3 and out["none"] == -1  # (the newest of the best kind still waiting; never an even)


@needs_node
def test_the_arenas_own_polls_become_moments(pure: str, town: dict[str, Any], tmp_path: Path) -> None:
    """The Arena's own four polls through townAssign, townFresh and townPlan as the page does: the first poll places
    everyone silently; then the buys, the sales (coins for a win, a puff for a loss), the two evictions and the two
    children moving into the lots they left."""
    out = _run(pure, r"""
const seen = { keys: {}, order: [] }; let lots = null; const plays = [];
PAGES.forEach(function (d, k) {
  const a = d.money.arena, m = townAssign(lots, a.residents, TOWN_LOTS, k);
  const lotOf = {}; m.lots.forEach(function (q, i) { if (q.id != null) lotOf[q.name] = i; }); m.gone.forEach(function (g) { if (lotOf[g.name] == null) lotOf[g.name] = g.lot; });
  const fresh = townFresh(a.events, seen, k === 0);
  plays.push(k === 0 ? [m.born.length] : townPlan(fresh, m, lotOf).map(function (q) { return q.act; }));
  lots = m.lots;
});
console.log(JSON.stringify({ plays: plays, names: lots.map(function (q) { return q.name; }) }));
""", tmp_path, PAGES=town["pages"])
    first, buys, sales, broke = out["plays"]
    assert first == [24]  # (everyone placed on the first poll, nothing played)
    assert buys and set(buys) == {"parcel"}
    assert "coins" in sales and "puff" in sales and set(sales) <= {"coins", "puff", "parcel", "even"}
    assert broke.count("sink") == 2 and broke.count("rise") == 2 and broke.index("sink") < broke.index("rise")
    assert not set(town["poor"]) & set(out["names"]) and len(out["names"]) == 24


@needs_node
def test_the_board_and_the_visit_say_the_pages_words(pure: str, town: dict[str, Any], tmp_path: Path, module: str) -> None:
    """The hall's board: every figure money.arena's and the next rent from generated_at; the visit's beats: the line's
    own clauses, the next rent, the moment's own words; practice said once in each title and nowhere else; the cinema's
    caption keeps each beat's words whole."""
    d = town["pages"][-1]
    cine = module[module.index("// >>> cinema (pure)"):module.index("// <<< cinema")]
    out = _run(pure + "\n" + cine, r"""
const a = D.money.arena, line = D.plain.arena_line, rent = townRentIn(D.generated_at, 0);
const sale = a.events.find(function (e) { return e.kind === "sale"; }), born = a.events.find(function (e) { return e.kind === "born"; });
const beats = townScript(a, line, rent, { who: sale.who, text: sale.text }), leader = townScript(a, line, rent, null);
console.log(JSON.stringify({ board: townBoardLines(a, rent), none: townBoardLines(null, null), rent: rent, beats: beats, leader: leader,
  born: townScript(a, line, rent, { who: born.who, text: born.text })[2], empty: townScript(a, "", rent, null),
  later: townRentIn(D.generated_at, 3600), midnight: townRentIn(Math.floor(D.generated_at / 86400) * 86400, 0), nil: townRentIn(null, 0),
  ins: [0, 59, 60, 3599, 12715].map(townIn), clauses: townClauses(line), sale: sale.text,
  caps: beats.map(function (b) { return cineSplit(cinePractice(b.text))[0]; }) }));
""", tmp_path, D=d)
    a, line = d["money"]["arena"], d["plain"]["arena_line"]
    assert out["rent"] == 12715 and out["later"] == 12715 - 3600 and out["midnight"] == 86400 and out["nil"] is None
    assert out["ins"] == ["under a minute", "under a minute", "1 min", "59 min", "3 h 31 min"]
    b = out["board"]
    top = a["residents"][0]
    t = a["today"]
    assert b["ok"] is True and b["title"] == "THE TOWN · PRACTICE MONEY" and b["pop"] == f"{a['population']} residents"
    assert b["rent"] == "rent $1.00 a day each" and b["next"] == "Next rent in 3 h 31 min · 00:00 UTC"
    assert b["stats"] == [[t["buys"], "buys"], [t["trades"], "sales"], [t["evicted"], "evictions"], [t["born"], "moved in"]]
    sign = "+" if round(a["result_usd"] * 100) >= 0 else "−"
    assert b["result"] == f"Trading since the start: {sign}${abs(a['result_usd']):.2f}" and b["up"] is (sign == "+")
    assert b["open"] == f"{a['open_bets']} bets open" and b["top"] == f"Richest: {top['name']} · ${top['money_usd']:.2f}"
    assert out["none"] == {"ok": False, "title": "THE TOWN · PRACTICE MONEY", "empty": "No report from the town yet."}
    blob = json.dumps(out)
    assert "undefined" not in blob and "NaN" not in blob and "null," not in json.dumps(b)
    # the beats: the line's clauses (its "The Arena (practice money): " said by each title), the rent, the event's words
    assert line.startswith("The Arena (practice money): ") and out["clauses"][0] == line.split(": ", 1)[1].split("; ")[0]
    town_b, hall_b, house_b = out["beats"]
    assert [x["view"] for x in out["beats"]] == ["town", "townhall", "townhouse"]
    assert town_b["who"] == "THE TOWN · PRACTICE MONEY" and town_b["text"] == out["clauses"][0][0].upper() + out["clauses"][0][1:] + "."
    assert town_b["note"].startswith("Today ") and hall_b["who"] == "THE TOWN HALL · PRACTICE MONEY"
    assert hall_b["text"].startswith("The town's trading ") and hall_b["note"] == "Next rent in 3 h 31 min (00:00 UTC)."
    assert house_b["who"] == out["beats"][2]["name"].upper() + " · PRACTICE MONEY"
    assert house_b["text"] == out["sale"].replace(" (practice)", "") and house_b["note"].startswith("Leader ")
    assert out["leader"][2]["text"].startswith("Leader ") and out["leader"][2]["name"] == top["name"]
    assert out["born"]["text"].startswith(out["born"]["name"] + " moved in: a child of ")
    assert out["empty"] == []  # (no line: no visit)
    for beat in out["beats"] + out["leader"] + [out["born"]]:
        words = (beat["text"] + " " + beat["note"]).lower()
        assert "practice" not in words and "real" not in words.split(), beat
        assert beat["who"].count("PRACTICE") == 1
    assert out["caps"] == [x["text"] for x in out["beats"]]  # (the cinema's caption: each beat's words, whole)


@needs_node
def test_the_board_and_the_plates_paint_the_words_in_practice_colours(pure: str, section: str, module: str,
                                                                    town: dict[str, Any], tmp_path: Path) -> None:
    consts = section[section.index("  const TOWN_AT = "):section.index("  const TOWN_CALM = ")]
    consts = "\n".join(line for line in consts.splitlines() if "V3(" not in line)  # (three.js: not needed here)
    draw = _js_body(section, "  function townDrawBoard(") + "\n" + _js_body(section, "  function townPlate(")
    # (the recording canvas and the record room's text helpers, the pure block, the colours; the page's data a constant)
    script = (_helpers(module) + pure + consts + "\nconst DATA = " + json.dumps(town["pages"][-1]) + ";\n"
              + "const TP = { board: board(1024, 640), plateCtx: Object.assign(makeCtx(), { clearRect: function () {} }) };\n" + draw + r"""
const a = DATA.money.arena, L = townBoardLines(a, townRentIn(DATA.generated_at, 0));
townDrawBoard(L); const words = painted();
townDrawBoard(townBoardLines(null, null)); const empty = painted();
const lot = { i: 5, occ: { id: "7", name: "Kai-7" }, money: 24.1, plate: "" }; townPlate(lot); const plate = painted();
townPlate(lot); const again = painted();
lot.occ = null; townPlate(lot); const vacant = painted();
console.log(JSON.stringify({ words: words, empty: empty, plate: plate, again: again, vacant: vacant, dirty: TP.plateDirty,
  tex: TP.board.userData.tex.needsUpdate, L: L }));
""")
    out = _node(script, tmp_path)
    texts = [w["t"] for w in out["words"]]
    L = out["L"]
    for want in (L["title"], L["pop"], L["rent"], "TODAY (UTC)", L["top"], L["next"], L["result"] + " · " + L["open"]):
        assert want in texts, want
    for n, label in L["stats"]:
        assert str(n) in texts and label in texts
    assert out["tex"] is True and [w["t"] for w in out["empty"]] == ["THE TOWN · PRACTICE MONEY", "No report from the town yet."]
    fills = {w["fill"].lower() for w in out["words"] + out["plate"] + out["vacant"]}
    assert not fills & {r.lower() for r in _REDS}  # (practice money is never red)
    result = next(w for w in out["words"] if w["t"].startswith("Trading since the start"))
    assert result["fill"] == ("#8ef0c8" if L["up"] else "#c3a6ff")  # mint up, lilac down
    assert [w["t"] for w in out["plate"]] == ["Kai-7", "$24.10"] and out["again"] == [] and out["dirty"] is True
    assert [w["t"] for w in out["vacant"]] == ["VACANT"]


def test_the_houses_and_the_moments_follow_the_rules_in_the_scene(section: str) -> None:
    """The scene's own rules, in its source: a rise waits for its lot's sink and a short VACANT; a lot's moments play in
    their order; a moment held for the close-up plays on air (at most TOWN_HOLD_S late); the moments' clock waits for the
    drone's first beat; the windows are lit only while bets are open; a poll without a report changes no house."""
    ready = _js_body(section, "  function townReady(")
    assert '(L.state === "vacant" || L.state === "empty") && simT - L.vacantAt >= TOWN_VACANT_S' in ready
    queue = _js_body(section, "  function townQueue(")
    assert "if (TOWN_WAIT[q.lot] || TOWN.clock < q.at) { TOWN_WAIT[q.lot] = 1; continue; }" in queue
    assert "if (q.hold && !spotOn && simT - q.heldAt < TOWN_HOLD_S)" in queue
    assert "FILM.shown === TOWN.spotBeat" in queue
    step = _js_body(section, "  function townStep(")
    assert "if (!(mine && FILM.shown < 0 && simT - TOWN.visitStart < 5)) TOWN.clock += dt;" in step
    targets = _js_body(section, "  function townTargets(")
    assert "L.hT = townFloors(r.money_usd) * TOWN_FLOOR_H; L.litT = townN(r.open) > 0 ? 1 : 0;" in targets
    apply = _js_body(section, "  function townApply(")
    assert "if (!a) { TOWN.a = null; townBoard(); return; }" in apply  # (no report this poll: the houses stay as they were)
    assert "TOWN.first = false;" in apply and "TOWN.nextAt = simT + TOWN_FIRST_S;" in apply
    assert "TOWN_QUEUE_MAX" in apply  # (a slow screen never builds a backlog: the oldest buys give way first)
    houses = _js_body(section, "  function townHouses(")
    assert 'const lt = L.state === "up" ? L.litT : 0;' in houses  # (a rising or sinking house is dark)
    assert "TOWN_RISE_S" in houses and "TOWN_SINK_S" in houses and 'L.state = "vacant"' in houses
    # the town to its rooftops is solid for the drone (every move into, out of and within it a cut: none through a roof)
    assert "blocker(TF, 0, 2.55, 0, 0, 9.4, 3.55, 9.4);" in section and section.count("blocker(") == 1
    # a poll during a visit: its beats say that poll's words, the close-up keeps its own house and moment
    assert "if (TOWN.visiting && FILM.on && FILM.kind === \"town\") townRefresh();" in apply
    refresh = _js_body(section, "  function townRefresh(")
    assert "townScript(TOWN.a, TOWN.line, townRentNow(), TOWN.spotWords)" in refresh
    assert 'w.view === "townhouse" && w.name !== TOWN.aimName' in refresh and "filmShow(FILM.shown)" in refresh


@needs_node
def test_the_queue_plays_each_lot_in_order_and_never_loses_a_house(section: str, tmp_path: Path) -> None:
    """The scene's queue (townReady, townQueue) over three stub lots, the house animations played by the clock: a lot's
    moments in their order; a newcomer's house rises only after the old one has sunk and the lot stood VACANT a moment;
    a moment held for the close-up waits until its beat is on air; a moment of a house that never stands is dropped
    after 14 s, a rise or a sink never (a rise on a lot whose house still stands sinks that house first)."""
    code = _js_body(section, "  function townReady(") + "\n" + _js_body(section, "  function townQueue(")
    out = _node(r"""
let simT = 0; const FILM = { on: false, kind: "", shown: -1 };
const TOWN_VACANT_S = 1.6, TOWN_HOLD_S = 45, TOWN_WAIT = new Uint8Array(4);
const TOWN = { queue: [], clock: 0, spotBeat: -1, wait: 0 };
const TL = [{ state: "up", vacantAt: -1e9 }, { state: "up", vacantAt: -1e9 }, { state: "empty", vacantAt: -1e9 }, { state: "up", vacantAt: -1e9 }];
const played = [];
function townPlay(q, L) {  // (what the scene starts: a sink sinks for 3.2 s, a rise rises for 2.6 s)
  played.push(q.act + "@" + q.lot + "@" + simT);
  if (q.act === "sink") { L.state = "sinking"; L.t0 = simT; } else if (q.act === "rise") { L.state = "rising"; L.t0 = simT; }
}
""" + code + r"""
const item = function (act, lot, at, extra) { return Object.assign({ act: act, lot: lot, at: at, done: false, hold: false, heldAt: 0 }, extra || {}); };
TOWN.queue = [item("parcel", 0, 0), item("sink", 1, 0.5), item("rise", 1, 1.0), item("coins", 1, 1.5), item("parcel", 2, 0.2),
              item("coins", 0, 2.0, { hold: true, heldAt: 0 }), item("puff", 0, 2.5), item("rise", 3, 3.0), item("sink", 2, 3.0)];
const waits = [];
for (let k = 0; k <= 64; k++) {
  simT = k * 0.5; TOWN.clock = simT;
  TL.forEach(function (L) {
    if (L.state === "sinking" && simT - L.t0 >= 3.2) { L.state = "vacant"; L.vacantAt = simT; }
    if (L.state === "rising" && simT - L.t0 >= 2.6) L.state = "up";
  });
  if (simT === 10) { FILM.on = true; FILM.kind = "town"; TOWN.spotBeat = 2; FILM.shown = 2; }  // (the close-up's beat on air)
  townQueue(); waits.push(TOWN.wait);
}
console.log(JSON.stringify({ played: played, left: TOWN.queue.filter(function (q) { return !q.done; }).length, waits: waits.slice(0, 4), last: waits[waits.length - 1] }));
""", tmp_path)
    assert out["played"] == [
        "parcel@0@0", "sink@1@0.5",
        "rise@1@6", "coins@1@6",  # (the old house down at 4, VACANT 1.6 s, then the newcomer's; its trade after it)
        "rise@3@8.5",  # (a rise on a lot whose house still stood: that house sank first, from 3 to 6.5)
        "coins@0@10", "puff@0@10",  # (held for the close-up: played the moment its beat is on air, the lot's next after it)
    ]
    # the parcel of a lot with no house is dropped after 14 s; the sink of a lot with nothing standing is done at once
    assert out["left"] == 0 and out["last"] == 0 and out["waits"][0] == 8
