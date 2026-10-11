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


def _tidy(text: str) -> str:
    """The town's own rule for the Arena's words (townTidy): money as "+$0.07" and "−$8.84", its people residents, a
    newcomer without its genes."""
    t = re.sub(r"([+-])(\d+(?:\.\d+)?) \$", lambda m: ("\u2212" if m[1] == "-" else "+") + "$" + m[2], text)
    t = re.sub(r"(^|[\s(])-\$(?=\d)", "\\1\u2212$", t)
    t = re.sub(r"\b(\d[\d,]*) traders paying\b", r"\1 residents paying", t)
    return re.sub(r"(moved in: a child of [^,]+), trading ([a-z]+)\b.*$", r"\1 (trades \2).", t, flags=re.IGNORECASE)


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
    for cond in ("!GOAL.pending", "!GOAL.queue.length"):  # (a real-money moment of the goal's waiting: no visit)
        assert cond in free, cond
    step = _js_body(section, "  function townStep(")
    assert "townCinema() && townFree()) townVisit(false);" in step
    # real money first: a real-money replay or a moment of the goal's waiting stops a visit, and the next comes back sooner
    assert "if (GOAL.pending || (rp && rp.real === true)) { TOWN.cut = true; filmStop(true); }" in step
    assert "TOWN.nextAt = simT + (TOWN.cut ? TOWN_DRAMA_S : TOWN_EVERY_S);" in step
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
    for name in ("townQueue", "townHouses", "townWrite", "townFx", "townAmbient", "townReady", "townFlush", "townFolk",
                 "townAlong", "townFolkPut", "townFolkHide", "townLabelsStep"):
        body = _code(_js_body(section, f"  function {name}("))
        for banned in ("new ", "function (", ".map(", ".filter(", ".concat(", ".slice(", "JSON", "[]", "{}", "=> "):
            assert banned not in body, (name, banned)
    step = _code(_js_body(section, "  function townStep("))
    for banned in ("new ", ".map(", ".filter(", "JSON", "=> "):
        assert banned not in step, banned
    assert "const TOWN_WAIT = new Uint8Array(TOWN_LOTS), TOWN_PEND = new Uint8Array(TOWN_LOTS);" in section
    assert "TOWN_WAIT.fill(0); TOWN_PEND.fill(0);" in section and "const TOWN_POSE = new Float32Array(4);" in section
    # 24 houses in four instanced draws, the plates in one, the smoke and the puffs in one Points each
    for part in ("TP.body = new THREE.InstancedMesh(bodyGeo, bodyMat, TOWN_LOTS);", "TP.roof = new THREE.InstancedMesh(",
                 "TP.chim = new THREE.InstancedMesh(", "TP.flags = new THREE.InstancedMesh(", "TP.plates = new THREE.Mesh(pg,",
                 "TP.smoke = new THREE.Points(", "TP.puffs = new THREE.Points(", "TP.coins = new THREE.InstancedMesh(",
                 "TP.parcels = new THREE.InstancedMesh(", "TP.trim = new THREE.InstancedMesh(trimGeo,",
                 "TP.folkBody = new THREE.InstancedMesh(", "TP.folkHead = new THREE.InstancedMesh(", "TP.folkHands = new THREE.InstancedMesh(",
                 "TP.folkPack = new THREE.InstancedMesh(", "TP.labels = new THREE.Mesh(lg,"):
        assert part in section, part
    # one villager a lot (made once, TOWN_LOTS instances each), at most three labels and the close-up's tag
    assert section.count("TOWN_LOTS);") >= 9 and "const NL = TOWN_LABELS + 1" in section and "TOWN_LABELS = 3" in section


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
  floors: [0, -3, null, NaN, 15.99, 16, 17.99, 18, 19.99, 20, 21.99, 22, 24, 27.99, 28, 1000].map(function (m) { return townFloors(m, 20); }),
  start: [townFloors(22, null), townFloors(12, 10), townFloors(10, 10), townFloors(9, 10), townFloors(22, 0)],
  profit: [townProfit(20, 20), townProfit(20.01, 20), townProfit(20.004, 20), townProfit(12, 10), townProfit(null, 20), townProfit(21, null)],
  fam: ["crypto, YES 0.40-0.60, +0.05 / -0.10, 6 h", "weather, NO", "sports", "other, YES", "", null, "Crypto , x"].map(townFamily) }));
""", tmp_path)
    assert out["n"] == 24 and out["near"] > 1.85 and out["faces"] is True  # (each door toward the market)
    assert out["street"] == 0 and out["hall"] == 0 and out["market"] == 0 and out["rim"] < 7.3  # (inside the lawn)
    assert out["rings"] == "0" * 8 + "1" * 16  # the inner ring first
    # three at the start cash, one more for each $2 above it, one less for each $2 below ($22: four, $18: two, $16: one)
    assert out["floors"] == [1, 1, 1, 1, 1, 1, 1, 2, 2, 3, 3, 4, 5, 6, 7, 7]
    assert out["start"] == [4, 4, 3, 2, 4]  # (the page's own start cash; $20 when it has none)
    assert out["profit"] == [False, True, False, True, False, True]  # (in profit to the cent: the gold trim)
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
  caps: beats.map(function (b) { return cineSplit(cineReal(b.text))[0]; }), notes: beats.map(function (b) { return cineReal(b.note); }),
  kept: beats.concat(leader).map(function (b) { return cineBeat({ cam: "view:" + b.view, tag: "THE TOWN", text: b.text }); }) }));
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
    assert line.startswith("The Arena (practice money): ") and out["clauses"][0] == _tidy(line.split(": ", 1)[1].split("; ")[0])
    assert out["clauses"][0].endswith("residents paying $1.00 rent a day")  # (the hall's board's word for the same count)
    town_b, hall_b, house_b = out["beats"]
    assert [x["view"] for x in out["beats"]] == ["town", "townhall", "townhouse"]
    assert town_b["who"] == "THE TOWN · PRACTICE MONEY" and town_b["text"] == out["clauses"][0][0].upper() + out["clauses"][0][1:] + "."
    assert town_b["note"].startswith("Today ") and hall_b["who"] == "THE TOWN HALL · PRACTICE MONEY"
    assert hall_b["text"].startswith("The town's trading ") and hall_b["note"] == "Next rent in 3 h 31 min (00:00 UTC)."
    assert house_b["who"] == out["beats"][2]["name"].upper() + " · PRACTICE MONEY"
    assert house_b["text"] == _tidy(out["sale"].replace(" (practice)", "")) and house_b["note"].startswith("Leader ")
    assert re.search(r"[+\u2212]\$\d+\.\d\d\.$", house_b["text"]), house_b["text"]  # (money as the world writes it)
    assert out["leader"][2]["text"].startswith("Leader ") and out["leader"][2]["name"] == top["name"]
    assert out["born"]["text"].startswith(out["born"]["name"] + " moved in: a child of ")
    assert re.fullmatch(r"\S+ moved in: a child of \S+ \((?:trades )?[a-z]+\)\.", out["born"]["text"]), out["born"]["text"]
    assert out["empty"] == []  # (no line: no visit)
    for beat in out["beats"] + out["leader"] + [out["born"]]:
        words = (beat["text"] + " " + beat["note"]).lower()
        assert "practice" not in words and "real" not in words.split(), beat
        assert not re.search(r"\d \$|(?:^|[\s(])-\$|traders|0\.\d\d-0\.\d\d", words), beat  # (no "-8.84 $", no genes)
        assert beat["who"].count("PRACTICE") == 1
    assert out["caps"] == [x["text"] for x in out["beats"]]  # (the cinema's caption: each beat's words, whole)
    assert out["notes"] == [x["note"] for x in out["beats"]]
    assert out["kept"] == [True] * 6  # (the cinema's real-money filter keeps every town beat: the Arena is its exception)


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
    assert 'showing = !!b && b.cam !== "view:townhall";' in step
    assert "if (showing || (!townCinema() && !(mine && FILM.shown < 0 && simT - TOWN.visitStart < 5))) TOWN.clock += dt;" in step
    targets = _js_body(section, "  function townTargets(")
    assert "L.hT = townFloors(r.money_usd, TOWN.start) * TOWN_FLOOR_H; L.litT = townN(r.open) > 0 ? 1 : 0;" in targets
    assert "L.profit = townProfit(r.money_usd, TOWN.start);" in targets
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
const TOWN_VACANT_S = 1.6, TOWN_HOLD_S = 45, TOWN_WAIT = new Uint8Array(4), TOWN_PEND = new Uint8Array(4), V_TRIP = 1, V_LEAVE = 4, V_ARRIVE = 5;
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


# --------------------------------------------------------------------------- the fix round: words, labels, pace, walks


@needs_node
def test_the_arenas_words_are_written_as_the_world_writes_them(pure: str, town: dict[str, Any], tmp_path: Path) -> None:
    """Money as "+$0.07" and "−$8.84" (never "-8.84 $" or "-$143.86"), the town's people "residents" (the board's word),
    a newcomer's line without its trading genes; the Arena's own events through the town's words keep every figure."""
    events = [e["text"] for d in town["pages"] for e in d["money"]["arena"]["events"]]
    lines = [d["plain"]["arena_line"] for d in town["pages"]]
    out = _run(pure, r"""
console.log(JSON.stringify({ samples: SAMPLES.map(townTidy), words: EVENTS.map(townWords), clauses: LINES.map(townClauses) }));
""", tmp_path, SAMPLES=[
        "Ada-1 sold on the way out: Will btc-up happen? -8.84 $ (practice).",
        "Gus-7 was evicted: went broke after 0.7 days (12 trades, -15.66 $).",
        "Mae-13 took profit: ETH up? +0.07 $ (practice).",
        "The Arena (practice money): 24 traders paying $1.00 rent a day; the town's trading -$143.86 so far, 3 bets open.",
        "Yul-25 moved in: a child of Cy-3, trading weather, NO 0.88-0.99, +0.25 / -0.46, 30 h.",
        "Bo-2 bought YES at 0.45: Seattle rain today ($0.60, practice).",
    ], EVENTS=events, LINES=lines)
    assert out["samples"] == [
        "Ada-1 sold on the way out: Will btc-up happen? −$8.84 (practice).",
        "Gus-7 was evicted: went broke after 0.7 days (12 trades, −$15.66).",
        "Mae-13 took profit: ETH up? +$0.07 (practice).",
        "The Arena (practice money): 24 residents paying $1.00 rent a day; the town's trading −$143.86 so far, 3 bets open.",
        "Yul-25 moved in: a child of Cy-3 (trades weather).",
        "Bo-2 bought YES at 0.45: Seattle rain today ($0.60, practice).",  # (a price and a stake are left as they are)
    ]
    assert events and len(out["words"]) == len(events)
    for raw, said in zip(events, out["words"], strict=True):
        assert not re.search(r"\d \$|(?:^|[\s(])-\$|\(practice\)", said), said
        figures = re.findall(r"\d+\.\d\d", raw)
        assert figures == re.findall(r"\d+\.\d\d", said) or "moved in" in raw, (raw, said)  # (every figure kept)
    for clauses in out["clauses"]:
        assert clauses[0].endswith("residents paying $1.00 rent a day") and not any("-$" in c for c in clauses)


@needs_node
def test_the_words_over_a_house_say_who_and_how_much(pure: str, section: str, tmp_path: Path) -> None:
    out = _run(pure, r"""
const q = function (act, who, usd, text) { return { act: act, who: who, ev: usd === undefined && !text ? null : { usd: usd, text: text || "" } }; };
console.log(JSON.stringify([q("coins", "Mae-13", 0.434), q("puff", "Hal-8", -2.07), q("rise", "Yul-25"), q("sink", "Ada-1"),
  q("parcel", "Kai-7", 3.72, "Kai-7 bought YES at 0.85: x ($3.72, practice)."), q("parcel", "Bo-2", 1), q("even", "Ivy-9", 0),
  q("coins", "Nox-14", null), q("coins", "", 1), null, { act: "other", who: "Z-1" }].map(townLabel)));
""", tmp_path)
    assert out == [{"text": "Mae-13 +$0.43", "tone": "up"}, {"text": "Hal-8 −$2.07", "tone": "down"},
                   {"text": "Yul-25 moved in", "tone": "in"}, {"text": "Ada-1 moved out", "tone": "out"},
                   {"text": "Kai-7 bought YES", "tone": "buy"}, {"text": "Bo-2 bought", "tone": "buy"},
                   {"text": "Ivy-9 broke even", "tone": "even"}, None, None, None, None]
    # their colours: the town's own (mint up, slate down, amber in), never red; at most three at once and the close-up's tag
    tones = re.search(r"const TOWN_TONE = \{([^}]*)\};", section)
    assert tones is not None and "up: TOWN_MINT" in tones.group(1) and "down: TOWN_SLATE" in tones.group(1)
    assert '"in": TOWN_AMBER' in tones.group(1) and "out: TOWN_SLATE" in tones.group(1)
    show = _js_body(section, "  function townLabelShow(")
    assert "for (let i = 0; i < TOWN_LABELS; i++)" in show and 'if (q.act === "parcel") return; k = old;' in show
    step = _js_body(section, "  function townLabelsStep(")
    assert "s.rise = TOWN_CALM || s.still ? 0 : 0.9 * townEase(u);" in step and "u >= 1" in step  # (less motion: it only fades)
    assert "TOWN_LABEL_S = 2.5" in section
    # the close-up's own name and money over its ridge while its beat is on air (its plate faces the door)
    assert "if (mark !== TOWN.heroOn) { TOWN.heroOn = mark; if (mark) townHeroDraw(); }" in _js_body(section, "  function townAmbient(")
    assert "L.occ.name + (townNum(L.money) ? \"  \" + townUsd(L.money) : \"\")" in _js_body(section, "  function townHeroDraw(")


@needs_node
def test_the_wide_beat_is_as_long_as_its_moments_and_a_backlog_stays_bounded(pure: str, tmp_path: Path) -> None:
    out = _run(pure, r"""
const item = function (act, extra) { return Object.assign({ act: act, done: false, hold: false }, extra || {}); };
const Q = [item("rise"), item("parcel"), item("coins"), item("sink"), item("parcel"), item("puff"), item("even"),
           item("coins", { hold: true }), item("parcel", { done: true })];
const over = townTrim(Q, 4);
const Q2 = [item("rise"), item("sink"), item("rise"), item("coins", { hold: true })], over2 = townTrim(Q2, 2);
console.log(JSON.stringify({ wide: [0, 1, 5, 13, 14, 40, null].map(townWideS), pace: [[0, 8], [1, 8], [2, 8], [12, 18.8], [40, 20], [3, 3]].map(function (p) { return townPace(p[0], p[1]); }),
  left: Q.map(function (q) { return q.done ? "" : q.act; }).filter(Boolean), over: over, left2: Q2.filter(function (q) { return !q.done; }).length, over2: over2 }));
""", tmp_path)
    assert out["wide"] == pytest.approx([8, 8.9, 12.5, 19.7, 20, 20, 8])  # (longer by 0.9 s a moment waiting, at most 20 s)
    # paced into the beat (a second's lead-in, two at the end), never closer than 0.35 s nor further than 1.6 s apart
    assert out["pace"] == pytest.approx([0, 0, 1.6, 15.8 / 11, 17 / 39, 0.35])
    # the buys give way first, then an even, then a sale lost; a rise, a sink and the close-up's moment never
    assert out["left"] == ["rise", "coins", "sink", "coins"] and out["over"] == 0
    assert out["left2"] == 4 and out["over2"] == 2


@needs_node
def test_the_villagers_walk_clear_of_every_house(pure: str, section: str, tmp_path: Path) -> None:
    """Each lot's villager: its doorstep in front of its door, its trip to the market and back (an inner house straight
    in, an outer one by the lane and a gap between the inner houses) and its way out to the bridge's head, every step
    clear of every house, the market's plinth, the hall, its columns, the lamps and the name plates' posts."""
    out = _run(pure, r"""
const lots = townLots(TOWN_LOTS), walks = townWalks(lots), H = 1.32 / 2 + 0.08, bad = [];
const posts = [], lamps = [0, 45, 135, -45, -90, -135].map(function (d) { const a = d * Math.PI / 180; return [Math.sin(a) * 5.05, Math.cos(a) * 5.05]; });
lots.forEach(function (q) { const dx = Math.sin(q.yaw), dz = Math.cos(q.yaw); posts.push([q.x + dx * (1.32 / 2 + 0.3) + dz * 0.48, q.z + dz * (1.32 / 2 + 0.3) - dx * 0.48]); });
function clear(x, z, what) {
  for (let i = 0; i < lots.length; i++) {  // (each house a square facing the market)
    const q = lots[i], c = Math.cos(q.yaw), s = Math.sin(q.yaw), lx = (x - q.x) * c - (z - q.z) * s, lz = (x - q.x) * s + (z - q.z) * c;
    if (Math.abs(lx) < H && Math.abs(lz) < H) bad.push([what, "house", i, x.toFixed(2), z.toFixed(2)]);
  }
  if (Math.hypot(x, z) < 1.95 + 0.07) bad.push([what, "market"]);
  if (Math.abs(x) < 2.05 + 0.07 && z < -5.1 + 0.07 && z > -8.1) bad.push([what, "hall"]);
  [[-1.62, -5.18], [1.62, -5.18]].forEach(function (p) { if (Math.hypot(x - p[0], z - p[1]) < 0.32 + 0.08) bad.push([what, "column"]); });
  lamps.concat(posts).forEach(function (p) { if (Math.hypot(x - p[0], z - p[1]) < 0.12) bad.push([what, "post"]); });
}
let longest = 0;
walks.forEach(function (w, i) {
  ["trip", "away"].forEach(function (k) {
    const P = w[k]; let len = 0;
    for (let j = 2; j < P.length; j += 2) {
      const ax = P[j - 2], az = P[j - 1], bx = P[j], bz = P[j + 1], n = Math.max(1, Math.ceil(Math.hypot(bx - ax, bz - az) / 0.05));
      len += Math.hypot(bx - ax, bz - az);
      for (let t = 0; t <= n; t++) clear(ax + (bx - ax) * t / n, az + (bz - az) * t / n, k + i);
    }
    if (k === "away") longest = Math.max(longest, len);
  });
  clear(w.step[0], w.step[1], "step" + i);
});
const ends = walks.map(function (w) { return [Math.hypot(w.trip[w.trip.length - 2], w.trip[w.trip.length - 1]), w.away[w.away.length - 2], w.away[w.away.length - 1]]; });
const doors = walks.map(function (w, i) { const q = lots[i]; return Math.hypot(q.x, q.z) - Math.hypot(w.door[0], w.door[1]); });
console.log(JSON.stringify({ bad: bad.slice(0, 12), n: bad.length, ends: ends, doors: doors, longest: longest }));
""", tmp_path)
    assert out["n"] == 0, out["bad"]
    assert all(abs(e[0] - 2.2) < 1e-9 and e[1] == 8.45 and e[2] == 0 for e in out["ends"])  # the market; the bridge's head
    assert all(abs(d - 0.76) < 1e-9 for d in out["doors"])  # (just out of its own front door)
    assert out["longest"] < 22  # (the way out is short enough to walk in a few seconds)
    # the scene: one walker a lot (the lot's next moment waits for it), the house of a newcomer rises as they arrive
    queue = _js_body(section, "  function townQueue(")
    assert "if (L.vm === V_TRIP || L.vm === V_LEAVE || L.vm === V_ARRIVE) { TOWN_WAIT[q.lot] = 1; continue; }" in queue
    play = _js_body(section, "  function townPlay(")
    assert 'L.state = "arriving"; townFolkGo(L, V_ARRIVE, q.hold ? TOWN_NEAR_M : TOWN_COME_M);' in play
    assert "townFolkGo(L, V_LEAVE, 0)" in play and "townFolkGo(L, V_CHEER, 0)" in play and "townFolkGo(L, V_SHRUG, 0)" in play
    assert "if (m === V_ARRIVE) townArrived(L);" in _js_body(section, "  function townFolk(")
    assert 'show = L.state !== "vacant" && L.state !== "empty" && L.state !== "arriving";' in _js_body(section, "  function townWrite(")
    # indoors at night (the channel's own clock), on the doorstep by day
    assert "w.night > 0.5" in _js_body(section, "  function townNight(")
    assert "const on = !!home && (act || !TOWN.night);" in _js_body(section, "  function townFolk(")


def test_a_house_changes_only_as_its_last_moment_plays(section: str) -> None:
    """A poll's new money, floors and lights wait for a house with a moment still to play (the coins come first); the
    town's card under its own views says practice once and the board's figures (the details view)."""
    apply = _js_body(section, "  function townApply(")
    assert "if (waits[i]) L.pend = r; else { L.pend = null; townTargets(L, r); townPlate(L); }" in apply
    assert apply.index("townTrim(TOWN.queue, TOWN_QUEUE_MAX);") < apply.index("if (waits[i]) L.pend = r;")
    assert "for (let i = 0; i < TL.length; i++) if (TL[i].pend && !TOWN_PEND[i]) townSettle(TL[i]);" in _js_body(section, "  function townQueue(")
    assert "L.pend && !townLeft(q)) townSettle(L);" in _js_body(section, "  function townPlay(")
    card = _js_body(section, "  function townCard(")
    assert 'room: "THE TOWN", who: "The Arena · " + TOWN_TAG.toLowerCase()' in card and "[B.pop, B.rent].filter(Boolean).join" in card
    assert 'CARD_FOR["rec:town"] = CARD_FOR["rec:townhall"] = CARD_FOR["rec:townhouse"] = townCard;' in section
    # a phone's wide sees the whole round islet from high above; a landscape screen pans low over the roofs
    fit = _js_body(section, "  function townWideFit(")
    assert "V.pan = !tall; V.w = tall ? 17.5 : 15.5;" in fit and "V.lift = tall ? 0.95 : 0.46;" in fit
    assert "townWideFit();" in _js_body(section, "  function townVisit(")


def _goal_and_town(module: str, section: str) -> str:
    goal = module[module.index("= THE GOAL (town goal)"):module.index("= THE HEARTS (team hearts)")]
    names = ("goalFree", "goalPlay", "goalBeatStart", "goalStep")
    return ("\n".join(_js_body(goal, f"  function {n}(") for n in names) + "\n"
            + "\n".join(_js_body(section, f"  function {n}(") for n in ("townCinema", "townFree", "townStep")))


@needs_node
def test_real_money_first_a_huddle_queued_during_a_visit_plays_at_once(module: str, section: str, tmp_path: Path) -> None:
    """The goal's own step and the town's, over stubs: a huddle (a real bet just settled) queued while the town's visit
    is on air stops the visit in the same frame and starts the next; no visit starts while one waits; and in the cinema
    the town's moments' clock runs only while a beat that shows the houses is on air."""
    out = _node(r"""
let simT = 0, data = { x: 1 }, panelKind = null, pinned = null, focus = null, CINEMA = true;
const document = { visibilityState: "visible" }, guideEl = { hidden: true }, performance = { now: function () { return simT * 1000; } };
const window = { __skyport: { replay: { now: function () { return null; } }, cinema: { on: function () { return CINEMA; }, intro: function () { return false; } } } };
const FILM = { on: false, kind: "", script: [], i: -1, shown: -1 }, log = [];
function progStart(kind, script) { FILM.on = true; FILM.kind = kind; FILM.script = script; FILM.i = 0; FILM.shown = 0; log.push("start:" + kind); return true; }
function filmStop() { log.push("stop:" + FILM.kind); FILM.on = false; FILM.kind = ""; }
const GOAL_PENDING_S = 60, GOAL = { seen: data, chip: {}, lastT: 0, beatUntil: 0, queue: [], pending: null, pendingAt: 0, checkInDone: true, checkInAt: -1,
  shown: -1, humT: 0, g: {}, w: {} }, REC = { chip: {}, tourChip: {} };
const goalApply = function () {}, goalChipMake = function () {}, goalBeatEnd = function () {}, goalBeatShow = function () {}, goalCue = function () {};
const goalBeatText = function () { return ""; }, goalMove = function () {}, goalHum = function () {}, goalChordStep = function () {}, goalGest = function () {};
const goalCheckIn = function () {}, heartsGather = function () { log.push("gather"); }, goalSeenStore = { mark: function () {} };
const goalBeatScript = function (b) { return [{ cam: "view:goaltower", s: 6 }]; };
const clamp = function (v, a, b) { return Math.max(a, Math.min(b, v)); };
const TOWN_DRAMA_S = 50, TOWN_EVERY_S = 140, TOWN_OVERDUE_S = 40;
const TOWN = { chip: { className: "", hidden: false }, visiting: true, visitStart: 0, lastEnd: -1e9, nextAt: Infinity, queue: [], spotBeat: -1, cut: false,
  clock: 0, rentT: 1e9, rentMin: 0, a: {}, wait: 0 };
const townChipMake = function () {}, townQueue = function () {}, townHouses = function () {}, townFolk = function () {}, townFx = function () {};
const townLabelsStep = function () {}, townAmbient = function () {}, townNight = function () {}, townRentNow = function () { return 0; }, townBoard = function () {};
let visits = 0; const townVisit = function () { visits += 1; return true; };
""" + _goal_and_town(module, section) + r"""
// a visit on air: the wide (houses), then the hall's board (no houses)
progStart("town", [{ cam: "view:town", s: 20 }, { cam: "view:townhall", s: 7 }, { cam: "view:townhouse", s: 7 }]);
const frame = function (dt) { simT += dt; goalStep(); townStep(dt); };
frame(0.5); const c1 = TOWN.clock;                    // the wide on air: the clock runs
FILM.i = 1; frame(0.5); const c2 = TOWN.clock;        // flying to the hall (its words not up): it waits
FILM.shown = 1; frame(0.5); const c3 = TOWN.clock;    // the hall's board on air: it waits
FILM.i = 2; FILM.shown = 2; frame(0.5); const c4 = TOWN.clock;  // the close-up (houses): it runs
GOAL.queue.push({ kind: "huddle" });                  // a real bet settles: the huddle is queued
frame(0.1); const after1 = [FILM.on, FILM.kind, !!GOAL.pending, TOWN.cut];
frame(0.1); const after2 = [FILM.on, FILM.kind, TOWN.visiting, TOWN.nextAt - simT];
// no visit while the goal has a moment waiting; the details view keeps the clock running
GOAL.queue.push({ kind: "on" }); FILM.on = false; FILM.kind = ""; TOWN.nextAt = 0; TOWN.wait = 3; const v0 = visits;
GOAL.beatUntil = 1e9; frame(0.1); const blocked = visits - v0;
CINEMA = false; const c5 = TOWN.clock; frame(0.5); const c6 = TOWN.clock;
console.log(JSON.stringify({ clocks: [c1, c2, c3, c4, c6 - c5], after1: after1, after2: after2, log: log, blocked: blocked }));
""", tmp_path)
    c1, c2, c3, c4, details = out["clocks"]
    assert c1 == 0.5 and c2 == c1 and c3 == c1 and c4 == 1.0 and details == 0.5
    # the huddle: the visit stops in the frame its beat starts waiting, the huddle's programme starts in the next
    assert out["after1"] == [False, "", True, True]
    assert out["after2"][:3] == [True, "goal", False] and abs(out["after2"][3] - 50) < 1e-6  # (the town comes back sooner)
    assert out["log"] == ["start:town", "stop:town", "start:goal", "gather"]
    assert out["blocked"] == 0
