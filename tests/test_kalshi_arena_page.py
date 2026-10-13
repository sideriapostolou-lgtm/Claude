"""The Kalshi arena on the page: the top-level ``kalshi_arena`` block (the contract with the town, and its fixture
``tests/fixtures/kalshi_arena_page.json``), practice-labelled, from panel.json only, never summed into anything."""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any

import pytest
from fakes import load_fixture
from kalshi_arena_world import T0, Market, kalshi_window

from nightcrawler import pagestate
from nightcrawler.kalshi_arena import PANEL_GRAVE, ArenaConfig, KalshiArena, adoptable
from nightcrawler.ledger import Ledger
from nightcrawler.speeddesk_live import LiveSnapshot

FIXTURE = load_fixture("kalshi_arena_page")
CASES = FIXTURE["cases"]
EMPTY = ("as_of", "heartbeat_s", "town_id", "population", "rent_usd", "broke_usd", "start_cash", "note", "control_id",
         "candidate_id", "control", "residents", "grave", "candidates", "events", "counts", "truncated", "town",
         "feed")


def saved_town(path: Path, now: float) -> KalshiArena:
    """A town with a record, a grave and a flagged candidate, saved to ``path``."""
    arena = KalshiArena(ArenaConfig(data_dir=path), LiveSnapshot, clock=lambda: now)
    rng = random.Random(4)
    for index in range(40):
        arena._after_window(kalshi_window(T0 + index * 900),
                            {rid: round(rng.gauss(0, 1), 4) for rid in arena.residents}, T0 + index * 900 + 905)
    star = next(res for res in arena.residents.values() if not res.control)
    star.row["candidate"] = {"at": now, "n": 120, "t": 2.4, "mean_usd": 0.05, "verdict_reason": "winning",
                             "adopt": adoptable(star.row["genes"], 5)}
    star.row["candidate_now"] = True
    star.row["since_flag"] = {"n": 3, "sum": 0.1, "sumsq": 0.02}
    star.row["name"] = "Ivy-9 sk-" + "a" * 40  # a secret-shaped text is redacted, not shown
    arena.last_frame_at = now
    arena._save(now)
    return arena


def write_panel(data_dir: Path, panel: Any) -> None:
    (data_dir / "kalshi_arena").mkdir(parents=True, exist_ok=True)
    (data_dir / "kalshi_arena" / "panel.json").write_text(json.dumps(panel, allow_nan=False), encoding="utf-8")


# ---------------------------------------------------------------------- the fixture is the contract
@pytest.mark.parametrize("name", sorted(CASES))
def test_each_fixture_case_is_exactly_what_the_page_emits(name: str, make_settings: Any) -> None:
    """The town maps the fixture; the page must keep emitting it. A saved panel holding the case's block comes back
    unchanged (the page recomputes status, stale, truncated and its constants on its own clock)."""
    case = CASES[name]
    block = case["kalshi_arena"]
    settings = make_settings(KALSHI_ARENA_ENABLED=block["status"] != "off")
    if block["status"] not in ("missing", "off"):
        write_panel(settings.data_dir, block)
    assert pagestate.kalshi_arena_block(settings, case["generated_at"]) == block


def test_the_fixture_cases_mean_what_the_contract_says() -> None:
    fresh, stale = CASES["fresh_with_candidate"]["kalshi_arena"], CASES["stale"]["kalshi_arena"]
    missing, off = CASES["missing_no_file"]["kalshi_arena"], CASES["off"]["kalshi_arena"]
    for block in (fresh, stale, missing, off):
        assert (block["schema_version"], block["mode"], block["real_orders_enabled"]) == (1, "paper", False)
        assert block["label"] == "Practice (pretend money)" and block["stale_after_s"] == 180.0
        assert block["fees_included"] is True and block["equity_basis"] == "cost"
    # fresh, with a current candidate who is also a resident (keyed by id, never by position)
    assert (fresh["status"], fresh["reason"], fresh["stale"]) == ("fresh", None, False)
    assert fresh["heartbeat_s"] == 60.0 and len(fresh["town_id"]) == 12
    ids = {row["id"]: row for row in fresh["residents"]}
    assert fresh["candidate_id"] == "7" and ids["7"]["candidate_now"] and fresh["candidates"][0]["id"] == "7"
    assert fresh["control_id"] == fresh["control"]["id"] == "1" and ids["1"]["control"]
    # retired bots keep their ids, lineage and record; the lists are bounded but the totals are full
    assert fresh["counts"] == {"residents": 4, "grave": 8, "candidates": 1, "events": 25}
    assert fresh["truncated"] == {"residents": False, "grave": True, "candidates": False, "events": True}
    assert all(row["status"] == "evicted" and row["died"] >= row["born"] for row in fresh["grave"])
    assert not set(ids) & {row["id"] for row in fresh["grave"]}
    assert all(isinstance(row["id"], int) for row in fresh["events"])
    assert [row["id"] for row in fresh["events"]] == sorted((row["id"] for row in fresh["events"]), reverse=True)
    for row in fresh["residents"] + fresh["grave"] + stale["residents"] + stale["grave"]:
        # one funding, trading P&L (fees included) and rent apart: equity = funded + P&L - rent, to the cent
        assert abs(row["equity_usd"] - (row["funded_usd"] + row["pnl_usd"] - row["rent_paid"])) <= 0.006
    for row in fresh["residents"] + stale["residents"]:
        assert abs(row["cash_usd"] - (row["equity_usd"] - row["open_cost_usd"])) <= 0.006
        assert row["open_mark_usd"] is None and row["record"]["keep"] == 960 and row["status"] == "active"
    # stale: the last saved town stays in place, flagged; never a fresh empty town
    assert (stale["status"], stale["reason"], stale["stale"]) == ("stale", "heartbeat_late", True)
    assert stale["residents"] and stale["candidate_id"] is None and stale["candidates"] == []
    # missing and off: every figure unknown (null), never a zero or an empty list
    assert (missing["status"], missing["reason"], missing["stale"]) == ("missing", "not_saved_yet", None)
    assert (off["status"], off["reason"], off["stale"]) == ("off", "disabled", None)
    assert all(missing[key] is None and off[key] is None for key in EMPTY)


def test_the_towns_own_panel_has_every_fixture_field(make_settings: Any, fake_clock: Any) -> None:
    """A real town's panel, through the page, has exactly the fixture's field names at every level."""
    settings = make_settings()
    now = fake_clock.now()
    arena = saved_town(settings.data_dir, now)
    for index in range(PANEL_GRAVE + 1):
        victim = next(res for res in arena.residents.values() if not res.control and not res.row["candidate"])
        arena._evict(victim, "went broke", now)
        arena._births(now)
    arena._save(now)
    block = pagestate.kalshi_arena_block(settings, now)
    model = CASES["fresh_with_candidate"]["kalshi_arena"]
    assert set(block) == set(model)
    for key in ("control", "counts", "truncated", "town", "feed"):
        assert set(block[key]) == set(model[key]), key
    for key in ("residents", "grave", "candidates", "events"):
        assert block[key] and model[key], key
        assert {frozenset(row) for row in block[key]} == {frozenset(model[key][0])}, key
    resident = block["residents"][0]
    assert set(resident["genes"]) == set(model["residents"][0]["genes"])
    assert set(resident["record"]) == set(model["residents"][0]["record"])
    assert set(block["candidates"][0]["adopt"]) == {"settings", "needs_code"}


@pytest.mark.parametrize(("change", "status", "reason"), [
    ({"problem": "Practice town halted after repeated errors; the live desk is unaffected"}, "halted", "halted"),
    ({"as_of": None}, "stale", "as_of_unknown"),
    ({"as_of": "+181"}, "stale", "heartbeat_late"),
    ({"as_of": "-61"}, "stale", "as_of_future"),
    ({"feed.last_frame_at": "-121"}, "degraded", "feed_quiet"),
    ({"feed.last_frame_at": None}, "degraded", "feed_quiet"),
    ({"feed.open_incomplete": 1}, "degraded", "feed_incomplete"),
    ({}, "fresh", None),
])
def test_the_status_rule_on_the_pages_own_clock(make_settings: Any, change: dict[str, Any], status: str,
                                                 reason: str | None) -> None:
    """In order: a problem halts; then the producer time (unknown, three heartbeats late, or from the future); then
    a town that runs but hears no market, or whose open window will be void. Times are the page's generated_at."""
    case = CASES["fresh_with_candidate"]
    panel = copy.deepcopy(case["kalshi_arena"])
    now = case["generated_at"]
    for key, value in change.items():
        if isinstance(value, str) and value[0] in "+-":  # an offset from the page's clock / the town's as_of
            value = (now - float(value) if key == "as_of" else panel["as_of"] + float(value))
        if key.startswith("feed."):
            panel["feed"][key[5:]] = value
        else:
            panel[key] = value
    settings = make_settings()
    write_panel(settings.data_dir, panel)
    block = pagestate.kalshi_arena_block(settings, now)
    assert (block["status"], block["reason"]) == (status, reason)
    assert block["stale"] is (status in ("stale", "halted"))
    assert block["residents"] == case["kalshi_arena"]["residents"]  # the last record stays, flagged by status


def test_a_brief_halted_panel_shows_its_lists_as_unknown(make_settings: Any) -> None:
    """A halt on a full disk may save only the panel's brief form: the page says halted, and every list, count and
    figure it lacks is null (never an empty town)."""
    settings = make_settings()
    case = CASES["fresh_with_candidate"]
    brief = {key: case["kalshi_arena"][key] for key in ("schema_version", "mode", "label", "as_of", "town_id",
                                                         "heartbeat_s")}
    write_panel(settings.data_dir, {**brief, "problem": "Practice town halted after repeated errors"})
    block = pagestate.kalshi_arena_block(settings, case["generated_at"])
    assert (block["status"], block["reason"], block["stale"]) == ("halted", "halted", True)
    assert block["town_id"] == brief["town_id"] and block["as_of"] == brief["as_of"]
    assert all(block[key] is None for key in ("residents", "grave", "candidates", "events", "counts", "truncated",
                                              "control", "town", "feed", "population"))


# ---------------------------------------------------------------------- the page
def test_the_page_shows_the_town_at_the_top_level_labelled_practice(make_settings: Any, fake_clock: Any) -> None:
    settings = make_settings(POLYDESK_ENABLED=False, TRENDDESK_ENABLED=False)
    now = fake_clock.now()
    arena = saved_town(settings.data_dir, now)
    with Ledger(settings.db_path, clock=fake_clock) as ledger:
        page = pagestate.build_page_state(ledger, settings, now)
    assert "kalshi_arena" not in page["money"]  # practice money lives outside the money card
    town = page["kalshi_arena"]
    assert (town["schema_version"], town["mode"], town["real_orders_enabled"]) == (1, "paper", False)
    assert town["label"] == "Practice (pretend money)" and town["status"] == "fresh" and town["stale"] is False
    assert town["as_of"] == now and town["heartbeat_s"] == 60.0 and town["town_id"] == arena.town_id
    assert town["population"] == 12 and len(town["residents"]) == 12 and town["control"]["name"] == "Live"
    assert town["control_id"] == town["control"]["id"] and town["candidate_id"] == town["candidates"][0]["id"]
    assert town["candidates"][0]["n"] == 120 and "not proof" in town["candidates"][0]["note"]
    assert set(town["candidates"][0]["adopt"]["settings"]) >= {"SPEEDDESK_MAKE_EDGE", "SPEEDDESK_KALSHI_LOCK_S"}
    assert "a" * 40 not in json.dumps(town)
    assert town["counts"] == {"residents": 12, "grave": arena.town["evicted"], "candidates": 1,
                              "events": arena.next_event - 1}
    assert town["truncated"]["residents"] is False and town["truncated"]["events"] is (town["counts"]["events"] > 24)
    for row in town["residents"]:
        assert abs(row["equity_usd"] - (row["funded_usd"] + row["pnl_usd"] - row["rent_paid"])) <= 0.011
        assert row["status"] == "active" and row["genes"]["make_edge"] is not None and len(row["rule_id"]) == 12
        assert row["open_mark_usd"] is None and row["record"]["keep"] == 960
    for row in town["grave"]:
        assert row["status"] == "evicted" and row["id"] and row["born"] is not None and row["died"] is not None
    assert all(event["kind"] in ("born", "evicted", "candidate", "rent", "control", "void", "")
               and isinstance(event["id"], int) for event in town["events"])
    later = pagestate.kalshi_arena_block(settings, now + 181)
    assert later["status"] == "stale" and later["reason"] == "heartbeat_late" and later["as_of"] == now
    assert later["residents"] == town["residents"]


def test_status_off_missing_unreadable_and_halted(make_settings: Any, fake_clock: Any, caplog: Any) -> None:
    now = fake_clock.now()
    missing = pagestate.kalshi_arena_block(make_settings(), now)
    assert (missing["status"], missing["reason"]) == ("missing", "not_saved_yet")
    assert all(missing[key] is None for key in EMPTY)
    arena = saved_town(make_settings().data_dir, now)
    off = pagestate.kalshi_arena_block(make_settings(KALSHI_ARENA_ENABLED=False), now)
    assert (off["status"], off["residents"], off["real_orders_enabled"]) == ("off", None, False)
    assert pagestate.kalshi_arena_block(make_settings(SPEEDDESK_KALSHI_ENABLED=False), now)["status"] == "off"
    arena.problem = "Practice town halted after repeated errors; the live desk is unaffected"
    arena._save(now)
    assert pagestate.kalshi_arena_block(make_settings(), now)["status"] == "halted"
    panel = make_settings().data_dir / "kalshi_arena" / "panel.json"
    panel.write_text('{"label": "Real money", "real_orders_enabled": true, "mode": "live"}', encoding="utf-8")
    broken = pagestate.kalshi_arena_block(make_settings(), now)
    assert (broken["status"], broken["reason"], broken["real_orders_enabled"], broken["mode"]) == (
        "missing", "unreadable", False, "paper")
    assert "kalshi_arena_panel_failed error=ValueError" in caplog.text


def test_the_page_reads_only_the_small_panel(make_settings: Any, fake_clock: Any,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings()
    now = fake_clock.now()
    saved_town(settings.data_dir, now)
    (settings.data_dir / "kalshi_arena" / "state.json").write_text("not json at all", encoding="utf-8")
    read: list[str] = []
    real = Path.read_text

    def spy(path: Path, *args: Any, **kwargs: Any) -> str:
        if "kalshi_arena" in str(path):
            read.append(path.name)
        return real(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", spy)
    assert pagestate.kalshi_arena_block(settings, now)["status"] == "fresh"
    assert read == ["panel.json"]


def test_a_huge_panel_is_refused_unread(make_settings: Any, fake_clock: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The page builder shares the live desk's process: an oversized panel is never parsed."""
    settings = make_settings()
    write_panel(settings.data_dir, {"label": "Practice (pretend money)", "note": "x" * 300_000})
    read: list[str] = []
    real = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda path, *a, **k: read.append(path.name) or real(path, *a, **k))
    assert pagestate.kalshi_arena_block(settings, fake_clock.now())["reason"] == "unreadable"
    assert read == []


def test_no_money_figure_reads_the_arena(make_settings: Any, fake_clock: Any) -> None:
    """Practice money never reaches real cash, Pacific profit, the town's growth or goal, the hearts or the words:
    the whole page is the same with the arena on or off, except its own block."""
    now = fake_clock.now()
    on = make_settings(POLYDESK_ENABLED=False, TRENDDESK_ENABLED=False)
    arena = saved_town(on.data_dir, now)
    for res in arena.residents.values():
        res.row["equity_usd"] = 5_000.0  # a fortune of pretend money
    arena._save(now)
    off = make_settings(POLYDESK_ENABLED=False, TRENDDESK_ENABLED=False, KALSHI_ARENA_ENABLED=False)
    with Ledger(on.db_path, clock=fake_clock) as ledger:
        shown = pagestate.build_page_state(ledger, on, now)
        hidden = pagestate.build_page_state(ledger, off, now)
    assert shown["kalshi_arena"]["residents"][0]["equity_usd"] == 5_000.0
    assert hidden["kalshi_arena"]["status"] == "off"
    assert "5000" not in json.dumps({key: value for key, value in shown.items() if key != "kalshi_arena"})
    for page in (shown, hidden):
        page.pop("kalshi_arena")
        page["about"].pop("uptime_s", None)
    assert shown == hidden


# ---------------------------------------------------------------------- the town's side of the contract
def test_retired_ids_are_stable_and_counts_are_full(tmp_path: Path) -> None:
    now = T0 + 99 * 900
    arena = KalshiArena(ArenaConfig(data_dir=tmp_path), LiveSnapshot, clock=lambda: now)
    for index in range(PANEL_GRAVE + 3):
        victim = next(res for res in arena.residents.values() if not res.control)
        arena._evict(victim, "went broke", now + index)
        arena._births(now + index)
    panel = arena.panel(now + 50)
    ids = [row["id"] for row in panel["grave"]]
    assert len(ids) == PANEL_GRAVE == len(set(ids)) and panel["counts"]["grave"] == PANEL_GRAVE + 3
    assert panel["truncated"]["grave"] is True
    assert all({"id", "parent", "born", "genes", "rule_id", "fills", "fees_usd", "funded_usd"} <= set(row)
               for row in panel["grave"])
    arena._save(now + 50)
    reborn = KalshiArena(ArenaConfig(data_dir=tmp_path), LiveSnapshot, clock=lambda: now + 60)
    assert reborn.town_id == arena.town_id and [row["id"] for row in reborn.panel(now + 60)["grave"]] == ids
    assert reborn.next_event == arena.next_event
    assert not set(reborn.residents) & set(ids)  # a retired id is never given to a newcomer


def test_event_ids_never_repeat_and_a_rebuilt_town_is_a_new_town(tmp_path: Path) -> None:
    now = T0
    arena = KalshiArena(ArenaConfig(data_dir=tmp_path), LiveSnapshot, clock=lambda: now)
    first = [row["id"] for row in arena.events]
    assert first == sorted(first, reverse=True) and len(set(first)) == len(first) == arena.next_event - 1
    assert all(row["resident_id"] in arena.residents for row in arena.events if row["kind"] == "born")
    arena._save(now)
    again = KalshiArena(ArenaConfig(data_dir=tmp_path), LiveSnapshot, clock=lambda: now + 5)
    again._event(now + 5, "Town", "A line.", "neutral", "")
    assert again.events[0]["id"] == max(first) + 1
    (tmp_path / "kalshi_arena" / "state.json").write_text('{"version": 1, "residents": "bad"}', encoding="utf-8")
    rebuilt = KalshiArena(ArenaConfig(data_dir=tmp_path), LiveSnapshot, clock=lambda: now + 10)
    assert rebuilt.town_id != arena.town_id and min(row["id"] for row in rebuilt.events) == 1


def test_a_refunded_control_moves_its_born_and_says_so(tmp_path: Path) -> None:
    """A live-rules change funds a new benchmark under the same id: born (the funding time) moves, the money starts
    at the funding, and a "control" event names the resident. A reader never takes it for a trading gain."""
    from nightcrawler.kalshi_arena import GENE_DEFAULTS

    now = T0
    arena = KalshiArena(ArenaConfig(data_dir=tmp_path), LiveSnapshot, clock=lambda: now)
    live = arena._control()
    assert live is not None
    arena._after_window(kalshi_window(T0), {live.id: -4.0}, T0 + 905)
    arena._save(now)
    changed = KalshiArena(ArenaConfig(data_dir=tmp_path, control={**GENE_DEFAULTS, "make_edge": 0.04}),
                          LiveSnapshot, clock=lambda: now + 3600)
    row = changed.panel(now + 3600)["residents"]
    control = next(item for item in row if item["control"])
    assert control["id"] == live.id and control["born"] == now + 3600 and control["record"]["from"] == now + 3600
    assert control["equity_usd"] == control["funded_usd"] == 50.0 and control["windows"] == 0
    assert changed.events[0]["kind"] == "control" and changed.events[0]["resident_id"] == live.id


def test_fills_fees_and_open_money_are_booked(tmp_path: Path) -> None:
    market = Market(tmp_path, population=4, seed=5, length=300)
    arena = market.start()
    market.run(1250, step_s=0.5)  # four short windows, settled
    rows = arena.panel(market.clock.now())["residents"]
    assert arena.town["windows"] >= 2 and any(row["fills"] for row in rows)
    for row in rows:
        assert (row["fills"] > 0) == (row["traded"] > 0) == (row["contracts"] > 0)
        assert row["fees_usd"] is not None and row["fees_usd"] >= 0
        assert abs(row["equity_usd"] - (row["funded_usd"] + row["pnl_usd"] - row["rent_paid"])) <= 0.011
        assert abs(row["cash_usd"] - (row["equity_usd"] - row["open_cost_usd"])) <= 0.011
        assert row["activity"] in ("holding", "bidding", "idle", "newborn")
        assert row["record"]["windows"] == row["windows"] and row["record"]["traded"] == row["traded"]
    assert arena.telemetry(market.clock.now())["last_frame_at"] is None  # fed in-process, never through a frame


def test_a_malformed_panel_never_takes_the_page_down(make_settings: Any, monkeypatch: pytest.MonkeyPatch,
                                                     caplog: Any) -> None:
    """Wrong types anywhere in the panel are whitelisted away (null), and an unexpected failure shows the block as
    missing/unreadable: the practice town never breaks /api/page."""
    case = CASES["fresh_with_candidate"]
    settings = make_settings()
    rng = random.Random(3)
    junk: list[Any] = [None, "x", 7, -1.5, True, [], {}, [1, "a"], {"a": [None]}]
    for _ in range(60):
        panel = copy.deepcopy(case["kalshi_arena"])
        for _hit in range(5):
            target: Any = panel
            for _depth in range(rng.randint(1, 3)):
                if isinstance(target, dict) and target:
                    key = rng.choice(sorted(target))
                    if isinstance(target[key], (dict, list)) and target[key] and rng.random() < 0.6:
                        target = target[key]
                        continue
                    target[key] = rng.choice(junk)
                    break
                if isinstance(target, list) and target:
                    target[rng.randrange(len(target))] = rng.choice(junk)
                    break
        panel["label"] = "Practice (pretend money)"
        write_panel(settings.data_dir, panel)
        block = pagestate.kalshi_arena_block(settings, case["generated_at"])
        assert block["status"] in ("fresh", "degraded", "stale", "halted", "missing")
        assert (block["mode"], block["real_orders_enabled"]) == ("paper", False)
        json.dumps(block, allow_nan=False)
    monkeypatch.setattr(pagestate, "_kalshi_arena_view", lambda *_args: 1 / 0)
    broken = pagestate.kalshi_arena_block(settings, case["generated_at"])
    assert (broken["status"], broken["reason"]) == ("missing", "unreadable")
    assert "kalshi_arena_panel_failed error=ZeroDivisionError" in caplog.text
