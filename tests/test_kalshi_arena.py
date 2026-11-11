"""The Kalshi arena's town: genes, the control, rent, evictions, births, candidates, files (practice money only)."""

from __future__ import annotations

import ast
import json
import logging
import math
import os
import random
import time
from collections import Counter
from dataclasses import fields, replace
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock
from kalshi_arena_world import T0, Market, kalshi_window

from nightcrawler import kalshi_arena
from nightcrawler.config import Secret, Settings
from nightcrawler.deskguard import LOSING, WINNING
from nightcrawler.kalshi_arena import (
    FILTERS,
    GENE_DEFAULTS,
    NUMBERS,
    SWITCHES,
    ArenaConfig,
    KalshiArena,
    adoptable,
    arena_config,
    child_genes,
    fixed_config,
    live_genes,
    random_genes,
    rule_id,
    speed_config,
)
from nightcrawler.speeddesk_live import LiveSnapshot
from nightcrawler.speeddesk_model import Book, Level, SpeedConfig, Trade

DAY = 86_400.0


def town(path: Path, *, population: int = 12, start: float = T0, **changes: Any) -> tuple[KalshiArena, FakeClock]:
    clock = FakeClock(start)
    snap = LiveSnapshot()
    arena = KalshiArena(ArenaConfig(data_dir=path, population=population, **changes), lambda: snap,
                        clock=clock.now)
    return arena, clock


def settle(arena: KalshiArena, start: float, results: dict[str, float | None], now: float | None = None) -> None:
    """Book one settled window for the residents named in ``results`` (by id)."""
    window = kalshi_window(start)
    arena._after_window(window, results, window.end + 5 if now is None else now)


def everyone(arena: KalshiArena, pnl: float | None, **overrides: float | None) -> dict[str, float | None]:
    return {rid: overrides.get(arena.residents[rid].row["name"], pnl) for rid in arena.residents}


def challenger(arena: KalshiArena) -> kalshi_arena.Resident:
    return next(res for res in arena.residents.values() if not res.control)


def control(arena: KalshiArena) -> kalshi_arena.Resident:
    found = arena._control()
    assert found is not None
    return found


# ---------------------------------------------------------------------- genes and the control
def test_first_town_is_the_control_its_children_and_newcomers(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, speeddesk_kalshi_clip=7, speeddesk_kalshi_lock_s=200,
                        speeddesk_kalshi_lock_max_price=0.95, speeddesk_pair_cap=1.0, speeddesk_max_imbalance=0.4,
                        speeddesk_make_edge=0.04, speeddesk_take_edge=0.5)
    config = arena_config(settings)
    genes = config.control
    # LiveLimits' own clamps: pair cap at most 0.99, imbalance at most 0.25, the lock never before the cutoff.
    assert (genes["starter"], genes["close_s"], genes["lock_max"], genes["pair_cap"], genes["max_imbalance"],
            genes["make_edge"]) == (7, 200, 0.95, 0.99, 0.25, 0.04)
    assert genes["lock"] and not genes["stop"] and not genes["rounds"] and genes["filters"] == []
    assert config.fixed["take_edge"] == 0.5 and config.fixed["clip"] == 7 and config.fixed["whole_contracts"]
    desk = speed_config(genes, config.fixed)
    assert (desk.cutoff_s, desk.lock_s, desk.lock_max_price, desk.clip, desk.starter_clip) == (200, 200, 0.95, 7, 7)
    assert desk.stop_s == 0 and not desk.rounds and desk.window_usd == 10 and desk.day_stop_usd == 6
    raised = live_genes(Settings(data_dir=tmp_path, speeddesk_kalshi_lock_s=60))
    assert raised["close_s"] == 180  # live never stops buying after its cutoff starts
    arena = KalshiArena(config, LiveSnapshot, clock=FakeClock().now)
    residents = list(arena.residents.values())
    assert len(residents) == 12 and sum(res.control for res in residents) == 1
    assert control(arena).row["genes"] == genes and control(arena).row["name"] == "Live"
    children = [res for res in residents if res.row["parent"] == control(arena).id]
    assert len(children) == 5 and all(res.row["gen"] == 2 for res in children)
    assert sum(res.row["parent"] is None and not res.control for res in residents) == 6
    assert all(res.row["equity_usd"] == 50.0 for res in residents)


def test_random_and_child_genes_stay_in_range_and_on_the_grid() -> None:
    rng = random.Random(3)
    parent = random_genes(rng)
    near = flips = 0
    for _ in range(2000):
        for genes in (random_genes(rng), child_genes(parent, rng)):
            for name, gene in NUMBERS.items():
                value = genes[name]
                assert gene.lo - 1e-9 <= value <= gene.hi + 1e-9
                assert abs((value - gene.lo) / gene.step - round((value - gene.lo) / gene.step)) < 1e-6
            assert all(isinstance(genes[name], bool) for name in SWITCHES) and genes["filters"] == []
        child = child_genes(parent, rng)
        near += all(abs(child[name] - parent[name]) <= 0.12 * (gene.hi - gene.lo) + gene.step
                    for name, gene in NUMBERS.items() if name in ("make_edge", "close_s"))
        flips += sum(child[name] != parent[name] for name in SWITCHES)
    assert near > 0.7 * 2000  # most children sit near their parent (one number in ten is redrawn)
    assert 0.06 * 3 * 2000 < flips < 0.14 * 3 * 2000  # each switch flips about one time in ten
    outside = {**GENE_DEFAULTS, "make_edge": 0.10, "close_s": 900}
    clamped = child_genes(outside, random.Random(1))
    assert clamped["make_edge"] <= 0.06 and clamped["close_s"] <= 300


@pytest.mark.parametrize(("gene", "value", "changed"), [
    ("make_edge", 0.045, {"make_edge"}),
    ("starter", 3, {"starter_clip"}),
    ("pair_cap", 0.97, {"pair_cap"}),
    ("max_imbalance", 0.15, {"max_imbalance"}),
    ("starter_delay_s", 60, {"starter_delay_s"}),
    ("starter_stop_s", 400, {"starter_stop_s"}),
    ("close_s", 180, {"cutoff_s", "lock_s"}),
    ("lock", False, {"lock_s"}),
    ("lock_max", 0.93, {"lock_max_price"}),
    ("stop", True, {"stop_s", "stop_pair_cost"}),
    ("rounds", True, {"rounds"}),
])
def test_each_gene_changes_exactly_its_practice_field(gene: str, value: Any, changed: set[str]) -> None:
    fixed = dict(kalshi_arena.DEFAULT_FIXED)
    base = speed_config(GENE_DEFAULTS, fixed)
    other = speed_config({**GENE_DEFAULTS, gene: value}, fixed)
    assert {item.name for item in fields(SpeedConfig) if getattr(base, item.name) != getattr(other, item.name)} == changed
    with_stop = {**GENE_DEFAULTS, "stop": True}
    assert speed_config({**with_stop, "stop_s": 700}, fixed).stop_s == 700
    assert speed_config({**with_stop, "stop_cost": 1.2}, fixed).stop_pair_cost == 1.2


def test_the_filter_slot_gates_starters_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def quiet_hours(window: Any, now: float, snap: Any) -> bool:
        calls.append(window.slug)
        return False

    monkeypatch.setitem(FILTERS, "quiet", quiet_hours)
    rng = random.Random(5)
    switched = sum("quiet" in child_genes({**GENE_DEFAULTS, "filters": []}, rng)["filters"] for _ in range(500))
    assert 20 < switched < 90  # a registered filter is switched on about one time in ten
    arena, clock = town(tmp_path)
    res = arena._new_resident({**GENE_DEFAULTS, "filters": ["quiet"]}, clock.now())
    assert res.desk.starter_gate is not None and control(arena).desk.starter_gate is None
    window = kalshi_window(T0)
    assert res.desk.starter_gate(window, T0) == "filter_missing"  # no market view read yet
    arena.step(clock.now())
    assert res.desk.starter_gate(window, T0) == "filter_quiet" and calls == [window.slug]
    FILTERS.pop("quiet")
    assert res.desk.starter_gate(window, T0) == "filter_missing"  # a filter that is gone never lets a starter by


def test_adoptable_separates_settings_from_code_and_rule_ids_track_genes() -> None:
    plain = adoptable(GENE_DEFAULTS, 5)
    assert plain["needs_code"] == [] and plain["settings"]["SPEEDDESK_KALSHI_LOCK_S"] == 240
    odd = adoptable({**GENE_DEFAULTS, "lock": False, "stop": True, "rounds": True, "starter": 8}, 5)
    assert len(odd["needs_code"]) == 4 and any("first buy of 8" in line for line in odd["needs_code"])
    assert rule_id(GENE_DEFAULTS) == rule_id(dict(GENE_DEFAULTS)) != rule_id({**GENE_DEFAULTS, "make_edge": 0.035})
    assert len(rule_id(GENE_DEFAULTS)) == 12


# ---------------------------------------------------------------------- windows
def test_window_lifecycle_records_pnl_forgets_windows_and_newborns_wait(tmp_path: Path) -> None:
    market = Market(tmp_path, seed=11, length=300)
    arena = market.start()
    first = kalshi_window(T0).slug
    market.run(320, step_s=0.5)  # through the first window's close and outcome
    assert arena.town["windows"] == 1 and first not in arena.windows
    for res in arena.residents.values():
        assert res.row["windows"] == 1 and len(res.row["pnl"]) == 1
        assert first not in res.desk.windows and not any(key[0] == first for key in res.desk.books)
    assert any(res.row["traded"] for res in arena.residents.values())
    assert sum(res.row["pnl"][0] is None for res in arena.residents.values()) == 12 - sum(
        res.row["traded"] for res in arena.residents.values())  # alive but no trade: None, P&L 0
    market.run(40, step_s=0.5)  # inside the second window
    newborn = arena._new_resident(dict(GENE_DEFAULTS), market.clock.now())
    second = kalshi_window(T0 + 300).slug
    assert newborn.id not in arena.members[second] and second not in newborn.desk.windows
    market.run(305, step_s=0.5)  # the second window settles; the third opens
    third = kalshi_window(T0 + 600).slug
    assert newborn.row["windows"] == 0 and newborn.id in arena.members[third]


def test_a_window_that_was_open_at_startup_is_void_for_everyone(tmp_path: Path) -> None:
    market = Market(tmp_path)
    market.clock.set(T0 + 30)
    market.windows.append(kalshi_window(T0))
    arena = market.start()
    market.run(10)
    assert kalshi_window(T0).slug not in arena.windows and arena.town["void_windows"] == 1


# ---------------------------------------------------------------------- rent, eviction, births
def test_rent_charges_everyone_from_the_second_day_and_evicts_who_cannot_pay(tmp_path: Path, caplog: Any) -> None:
    arena, _clock = town(tmp_path)
    poor = challenger(arena)
    poor.row["equity_usd"] = 10.1
    settle(arena, T0, everyone(arena, None))
    assert arena.town["rent_paid"] == 0 and arena.rent_day == "2026-10-08"  # no rent on the town's first day
    settle(arena, T0 + 900, everyone(arena, None))
    assert arena.town["rent_paid"] == 0  # the same day again
    caplog.set_level(logging.INFO, "nightcrawler.kalshi_arena")
    tomorrow = T0 + 7 * 3600  # 2026-10-09 00:00 UTC
    poor.row["equity_usd"] = 0.1
    settle(arena, tomorrow, everyone(arena, None))
    assert poor.id not in arena.residents and arena.grave[0]["why"] == "could not pay the rent"
    assert control(arena).row["rent_paid"] == pytest.approx(0.2) and control(arena).row["equity_usd"] == 49.8
    assert arena.town["rent_paid"] == pytest.approx(0.2 * 11) and arena.town["rent_days"] == 1
    assert len(arena.residents) == 12  # the empty home went to a child at once
    assert "kalshi_arena_evicted resident=" in caplog.text and "why=could_not_pay_the_rent" in caplog.text
    assert "kalshi_arena_born resident=" in caplog.text


def test_broke_residents_are_evicted_and_the_graveyard_is_bounded(tmp_path: Path) -> None:
    arena, _clock = town(tmp_path)
    for index in range(kalshi_arena.GRAVE_KEEP + 5):
        victim = challenger(arena)
        victim.row["equity_usd"] = 10.5
        settle(arena, T0 + index * 900, {victim.id: -1.0, control(arena).id: 0.0})
        assert victim.id not in arena.residents and arena.grave[0]["name"] == victim.row["name"]
        assert arena.grave[0]["why"] == "went broke" and arena.grave[0]["equity_usd"] < 10
    assert len(arena.grave) == kalshi_arena.GRAVE_KEEP and arena.town["evicted"] == kalshi_arena.GRAVE_KEEP + 5
    assert arena.grave[0]["died"] > arena.grave[-1]["died"]  # newest first


def test_a_clear_loser_is_evicted_by_the_risk_managers_early_stop_but_never_the_control(tmp_path: Path) -> None:
    arena, _clock = town(tmp_path)
    loser = challenger(arena)
    live = control(arena)
    for index in range(10):
        settle(arena, T0 + index * 900, {loser.id: -1.0 - 0.01 * index, live.id: -1.0 - 0.01 * index})
    assert loser.id not in arena.residents
    row = arena.grave[0]
    assert row["why"].startswith("losing: 10 settled, 10 lost") and row["verdict"] == LOSING
    assert live.id in arena.residents and live.row["verdict"]["word"] == LOSING
    assert any(event["kind"] == "control" for event in arena.events)  # "the live rules lose in practice"


def test_births_come_from_the_richest_half_control_included(tmp_path: Path, caplog: Any) -> None:
    arena, clock = town(tmp_path)
    ranked = sorted(arena.residents.values(), key=lambda res: int(res.id))
    for index, res in enumerate(ranked):
        res.row["equity_usd"] = 100.0 - index  # the control (id 1) is the richest
    top = {res.id for res in ranked[:6]}
    caplog.set_level(logging.INFO, "nightcrawler.kalshi_arena")
    caplog.clear()  # the first town's births may already be captured, depending on earlier tests
    parents = []
    for _ in range(40):
        poorest = min((res for res in arena.residents.values() if not res.control),
                      key=lambda res: res.row["equity_usd"])
        arena._evict(poorest, "test", clock.now())
        arena._births(clock.now())
        child = max(arena.residents.values(), key=lambda res: int(res.id))
        child.row["equity_usd"] = 0.0  # never a parent itself
        parents.append(child.row["parent"])
    assert set(parents) <= top and control(arena).id in parents
    assert caplog.text.count("kalshi_arena_born") == 40


def test_a_shrunken_population_sends_the_poorest_away(tmp_path: Path) -> None:
    arena, clock = town(tmp_path)
    poorest = challenger(arena)
    poorest.row["equity_usd"] = 1.0
    arena._save(clock.now())
    smaller, _ = town(tmp_path, population=6)
    assert len(smaller.residents) == 6 and poorest.id not in smaller.residents
    assert smaller.grave[0]["why"] == "the town shrank" and smaller._control() is not None


# ---------------------------------------------------------------------- candidates
def _winning_run(arena: KalshiArena, res: kalshi_arena.Resident, windows: int, edge: float, start: int = 0,
                 noise: float = 0.1) -> None:
    live = control(arena)
    base = (1.0, -1.0, 0.5, -0.5)
    wobble = (noise, -noise, noise / 2, -noise / 2)
    for index in range(start, start + windows):
        bench = base[index % 4]
        settle(arena, T0 + index * 900, {res.id: bench + edge + wobble[index % 4], live.id: bench})


def test_a_candidate_needs_winning_100_paired_windows_and_t_of_2(tmp_path: Path, caplog: Any) -> None:
    arena, _clock = town(tmp_path)
    star = challenger(arena)
    caplog.set_level(logging.INFO, "nightcrawler.kalshi_arena")
    _winning_run(arena, star, 99, 0.4)
    assert star.row["candidate"] is None  # 99 windows: not yet
    _winning_run(arena, star, 1, 0.4, start=99)
    assert star.row["verdict"]["word"] == WINNING and star.row["candidate"] is not None
    flag = star.row["candidate"]
    assert flag["n"] == 100 and flag["t"] >= 2 and flag["mean_usd"] == pytest.approx(0.4, abs=0.01)
    assert flag["adopt"]["settings"]["SPEEDDESK_MAKE_EDGE"] == star.row["genes"]["make_edge"]
    assert "kalshi_arena_candidate resident=" + star.row["name"] in caplog.text and arena.town["candidates"] == 1
    _winning_run(arena, star, 20, 0.4, start=100)
    assert star.row["since_flag"]["n"] == 20 and arena.town["candidates"] == 1  # flagged once; the check goes on
    assert star.row["candidate_now"] and control(arena).row["candidate"] is None
    panel = arena.panel(T0)
    assert panel["candidates"][0]["name"] == star.row["name"] and "not proof" in panel["candidates"][0]["note"]


def test_no_candidate_without_a_winning_record_even_far_ahead_of_the_control(tmp_path: Path) -> None:
    arena, _clock = town(tmp_path)
    unclear = challenger(arena)
    live = control(arena)
    for index in range(130):
        swing = (1.0, -1.0, 0.9, -0.9)[index % 4]  # breaks even
        bench = (0.4, -1.6, -0.1, -1.1)[index % 4]  # the control loses
        settle(arena, T0 + index * 900, {unclear.id: swing, live.id: bench})
    assert unclear.row["verdict"]["word"] != WINNING and kalshi_arena._paired(unclear.row["paired"])["t"] > 2
    assert unclear.row["candidate"] is None and live.id in arena.residents


def test_no_candidate_when_the_paired_difference_is_noise(tmp_path: Path) -> None:
    arena, _clock = town(tmp_path)
    twin = challenger(arena)
    live = control(arena)
    base = (1.4, -0.6, 0.9, -0.1)
    for index in range(130):
        bench = base[index % 4]
        settle(arena, T0 + index * 900, {twin.id: bench + (0.3, -0.3, -0.3, 0.3)[index % 4], live.id: bench})
    paired = kalshi_arena._paired(twin.row["paired"])
    assert twin.row["verdict"]["word"] == WINNING and paired["n"] == 130 and abs(paired["t"] or 0) < 2
    assert twin.row["candidate"] is None and not twin.row["candidate_now"]


# ---------------------------------------------------------------------- restart and files
def test_restart_restores_the_town_and_voids_the_open_window(tmp_path: Path) -> None:
    market = Market(tmp_path, seed=5, length=300)
    arena = market.start()
    market.run(320, step_s=0.5)
    market.run(60, step_s=0.5)
    assert kalshi_window(T0 + 300).slug in arena.windows
    arena._save(market.clock.now())
    before = {rid: (res.row["name"], res.row["genes"], res.row["equity_usd"], res.row["pnl"])
              for rid, res in arena.residents.items()}
    restored = KalshiArena(market.config, lambda: market.snap, clock=market.clock.now)
    assert {rid: (res.row["name"], res.row["genes"], res.row["equity_usd"], res.row["pnl"])
            for rid, res in restored.residents.items()} == before
    assert restored.town["windows"] == 1 and restored.next_id == arena.next_id
    restored.step(market.clock.now())
    open_window = kalshi_window(T0 + 300).slug
    assert open_window not in restored.windows and restored.town["void_windows"] == arena.town["void_windows"] + 1
    assert all(not res.desk.windows for res in restored.residents.values())


def test_a_bad_state_file_moves_aside_and_the_town_starts_fresh(tmp_path: Path, caplog: Any) -> None:
    directory = tmp_path / "kalshi_arena"
    directory.mkdir()
    (directory / "state.json").write_text('{"version": 1, "residents": [{"id": "1"}]}', encoding="utf-8")
    caplog.set_level(logging.WARNING, "nightcrawler.kalshi_arena")
    arena, _ = town(tmp_path)
    assert len(arena.residents) == 12 and "kalshi_arena_state_reset error=KeyError" in caplog.text
    assert [path.name.startswith("state.json.bad-") for path in directory.iterdir()] == [True]
    (directory / "state.json").write_text("not json", encoding="utf-8")
    again, _ = town(tmp_path)
    assert len(again.residents) == 12


def test_files_are_written_atomically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    arena, clock = town(tmp_path)
    renames: list[tuple[str, str]] = []
    real = os.replace
    monkeypatch.setattr(kalshi_arena.os, "replace", lambda a, b: renames.append((Path(a).name, Path(b).name))
                        or real(a, b))
    arena._save(clock.now())
    assert renames == [("state.json.tmp", "state.json"), ("panel.json.tmp", "panel.json")]
    assert sorted(path.name for path in (tmp_path / "kalshi_arena").iterdir()) == ["panel.json", "state.json"]
    assert json.loads((tmp_path / "kalshi_arena" / "state.json").read_text())["version"] == 1


def test_thirty_days_of_churn_keep_both_files_small(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Quick:
        def __init__(self, pnls: list[float]) -> None:
            total = sum(pnls)
            self.verdict = LOSING if len(pnls) >= 10 and total < -4 else "learning"
            self.reason = f"{len(pnls)} settled, {total:+.2f} in all; a reason of a realistic length for the panel"

    monkeypatch.setattr(kalshi_arena, "judge", Quick)  # sizes, not verdicts, are under test here
    arena, _clock = town(tmp_path)
    rng = random.Random(9)
    for index in range(30 * 96):
        results = {rid: (round(rng.gauss(0, 1.2), 4) if rng.random() < 0.8 else None) for rid in arena.residents}
        settle(arena, T0 + index * 900, results)
    assert arena.town["evicted"] > 20 and arena.town["rent_days"] >= 29
    for res in [res for res in arena.residents.values() if not res.control][:5]:  # the panel's worst case
        res.row["candidate"] = {"at": T0, "n": 140, "t": 2.31, "mean_usd": 0.042, "verdict_reason": "x" * 300,
                                "adopt": adoptable({**res.row["genes"], "stop": True, "rounds": True}, 5)}
        res.row["since_flag"] = {"n": 12, "sum": 0.3, "sumsq": 0.2}
    arena._save(T0 + 30 * DAY)
    state = (tmp_path / "kalshi_arena" / "state.json").stat().st_size
    panel = (tmp_path / "kalshi_arena" / "panel.json").stat().st_size
    # The panel carries each resident's genes and money lines for the town's contract (about 27 KB at worst); the
    # page refuses one over kalshi_arena.PANEL_MAX_BYTES unread.
    assert state <= 192_000 and panel <= 32_000, (state, panel)
    assert all(len(res.row["pnl"]) <= kalshi_arena.RECORD_KEEP for res in arena.residents.values())


def test_a_control_rule_change_restarts_the_benchmark_and_every_comparison(tmp_path: Path, caplog: Any) -> None:
    arena, clock = town(tmp_path)
    star = challenger(arena)
    _winning_run(arena, star, 12, 0.4)
    assert star.row["paired"]["n"] == 12 and control(arena).row["windows"] == 12
    arena._save(clock.now())
    caplog.set_level(logging.INFO, "nightcrawler.kalshi_arena")
    changed, _ = town(tmp_path, control={**GENE_DEFAULTS, "make_edge": 0.04})
    live = changed._control()
    assert live is not None and live.row["windows"] == 0 and live.row["genes"]["make_edge"] == 0.04
    assert changed.residents[star.id].row["paired"]["n"] == 0 and changed.residents[star.id].row["windows"] == 12
    assert f"kalshi_arena_control_changed old={rule_id(GENE_DEFAULTS)} new=" in caplog.text
    _winning_run(changed, changed.residents[star.id], 5, 0.4, start=20)
    changed._save(clock.now())
    same, _ = town(tmp_path, control={**GENE_DEFAULTS, "make_edge": 0.04})
    assert same.residents[star.id].row["paired"]["n"] == 5  # no second reset without a change


# ---------------------------------------------------------------------- practice only
def test_the_module_cannot_reach_a_real_order() -> None:
    source = Path(kalshi_arena.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    forbidden = {"speeddesk_kalshi_client", "speeddesk_live", "speeddesk_kalshi_ws", "requests", "websockets",
                 "polymarket_us", "urllib", "http", "asyncio"}
    assert not {name.split(".")[-1] for name in imported} & forbidden, imported
    assert "create_order" not in source and "KalshiClient" not in source
    # Its one socket is the local pair to its own process (Unix, no address): nothing can reach a network.
    import re

    assert set(re.findall(r"socket\.(\w+)", source)) <= {"socketpair", "AF_UNIX", "SOCK_STREAM", "SOL_SOCKET",
                                                          "SO_SNDBUF", "socket"}
    assert "connect(" not in source and "bind(" not in source and "AF_INET" not in source


def test_a_running_town_holds_no_settings_or_secret(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, kalshi_key_id="key-id", kalshi_private_key="private")
    arena = KalshiArena(arena_config(settings), LiveSnapshot, clock=FakeClock().now)

    def walk(value: Any, depth: int) -> None:
        assert not isinstance(value, (Settings, Secret)), type(value)
        assert "private" != value and "key-id" != value
        if depth == 0:
            return
        if isinstance(value, dict):
            for item in value.values():
                walk(item, depth - 1)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                walk(item, depth - 1)
        elif hasattr(value, "__dict__") and not callable(value):
            for item in vars(value).values():
                walk(item, depth - 1)

    walk(arena, 3)
    for item in fields(ArenaConfig):
        value = getattr(arena.config, item.name)
        assert isinstance(value, (int, float, Path, dict)), item.name
    assert all(isinstance(value, (int, float, bool)) for value in fixed_config(settings).values())


def test_panel_is_compact_and_labelled_practice(tmp_path: Path) -> None:
    arena, clock = town(tmp_path)
    arena._save(clock.now())
    panel = kalshi_arena.panel_state(tmp_path, clock.now())
    assert panel["label"] == "Practice (pretend money)" and panel["population"] == 12
    assert panel["control"]["name"] == "Live" and len(panel["residents"]) == 12
    assert set(panel["feed"]) >= {"queue", "received", "dropped", "late", "coalesced", "pass_p99_ms", "duty_pct",
                                  "lag_s", "errors", "live_flush_us_p99"}
    assert math.isclose(panel["start_cash"], 50.0) and panel["rent_usd"] == 0.2
    with pytest.raises(FileNotFoundError):
        kalshi_arena.panel_state(tmp_path / "missing", clock.now())


# ---------------------------------------------------------------------- the review of 2026-10-13
def test_the_control_runs_the_live_risk_books_rules(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, speeddesk_kalshi_account_type="direct")
    fixed = fixed_config(settings)
    assert (fixed["day_stop_counts_risk"], fixed["hedged_open_budget"], fixed["rest_ttl_s"],
            fixed["edge_fee_precision"]) == (True, True, 30.0, 0.0001)
    assert fixed_config(Settings(data_dir=tmp_path))["edge_fee_precision"] == 0.01  # unattested: live's own bound
    desk = speed_config(live_genes(settings), fixed)
    assert desk.day_stop_counts_risk and desk.hedged_open_budget and desk.rest_ttl_s == 30
    assert kalshi_arena.DEFAULT_FIXED == {**fixed_config(Settings(
        data_dir=tmp_path, speeddesk_kalshi_account_type="direct", speeddesk_kalshi_clip=5,
        speeddesk_kalshi_window_usd=10, speeddesk_kalshi_open_usd=20, speeddesk_kalshi_day_stop_usd=6,
        speeddesk_take_edge=1.0)), "latency_ms": kalshi_arena.DEFAULT_FIXED["latency_ms"]}


def test_a_change_of_the_shared_live_limits_restarts_every_record(tmp_path: Path, caplog: Any) -> None:
    arena, clock = town(tmp_path)
    star = challenger(arena)
    _winning_run(arena, star, 12, 0.4)
    star.row["candidate_now"] = True
    money = {rid: res.row["equity_usd"] for rid, res in arena.residents.items()}
    arena._save(clock.now())
    caplog.set_level(logging.INFO, "nightcrawler.kalshi_arena")
    doubled = {**kalshi_arena.DEFAULT_FIXED, "window_usd": 20.0, "open_usd": 40.0, "day_stop_usd": 12.0}
    after, _ = town(tmp_path, fixed=doubled)  # the owner's "double tomorrow": the control's genes are the same
    assert after.control_rule == arena.control_rule and after.regime != arena.regime
    assert "kalshi_arena_regime_changed old=" in caplog.text
    for rid, res in after.residents.items():
        assert res.row["pnl"] == [] and res.row["paired"]["n"] == 0 and res.row["verdict"]["word"] == "learning"
        assert res.row["equity_usd"] == money[rid] and not res.row["candidate_now"]  # money stays
    assert after.residents[star.id].row["windows"] == 12  # lifetime counts stay
    after._save(clock.now())
    again, _ = town(tmp_path, fixed=doubled)
    assert again.residents[star.id].row["pnl"] == [] and "regime" in json.loads(after.path.read_text())


def _open(market: Market) -> str:
    market.run(30, step_s=0.25)  # the first window is open and every resident holds it
    slug = kalshi_window(T0).slug
    assert slug in market.arena.windows
    return slug


def test_a_window_whose_feed_dropped_is_void_for_everyone(tmp_path: Path, caplog: Any) -> None:
    caplog.set_level(logging.INFO, "nightcrawler.kalshi_arena")
    market = Market(tmp_path, seed=5, length=300)
    arena = market.start()
    slug = _open(market)
    view = kalshi_arena.WireView()
    arena.receive(("batch", 1, T0, 0, 40, []), view)
    assert slug not in arena.degraded
    arena.receive(("batch", 2, T0, 7, 40, []), view)  # the live loop dropped 7 events
    assert arena.degraded == {slug: "feed_dropped"}
    before = {rid: res.row["windows"] for rid, res in arena.residents.items()}
    market.run(300, step_s=0.5)  # to the outcome
    assert slug not in arena.windows and arena.town["windows"] == 0 and arena.town["void_feed"] == 1
    assert {rid: res.row["windows"] for rid, res in arena.residents.items()} == before  # no record, no money
    assert f"kalshi_arena_void window={slug} why=feed_dropped" in caplog.text
    gap, _ = town(tmp_path / "gap")
    gap.windows[slug] = kalshi_window(T0)
    gap.clock = lambda: T0 + 10  # type: ignore[method-assign]
    gap.receive(("batch", 1, T0, 0, 40, []), view)
    gap.receive(("batch", 3, T0, 0, 40, []), view)  # a frame missing in the sequence
    assert gap.degraded == {slug: "feed_dropped"}


def test_a_window_read_too_late_is_void_for_everyone(tmp_path: Path) -> None:
    """The review's backlog: the town reads every event 4 s after it arrived (beyond the desks' 3 s freshness), so
    no resident can trade, and the window must not count as if the town had seen the market."""
    market = Market(tmp_path, population=12, seed=5)
    arena = market.start()
    slug = _open(market)
    lag = 4.0
    arena.clock = lambda: market.clock.now() + lag  # type: ignore[method-assign]
    real_step = arena.step
    arena.step = lambda now: real_step(now + lag)  # type: ignore[method-assign]
    before = {rid: res.row["paired"].get("n", 0) for rid, res in arena.residents.items()}
    market.run(900, step_s=0.25)
    assert arena.late > 0 and arena.town["void_feed"] >= 1
    assert not [rid for rid, res in arena.residents.items() if res.row["paired"]["n"] > before[rid]]
    assert slug not in arena.windows


def test_a_backlog_drains_fast_and_orders_keep_every_book(tmp_path: Path) -> None:
    """The review's ceiling was about 400 books a second whatever CPU was free (a 2 ms rest after each book). The
    town now has its own process and no rests: a backlog of 25-level books coalesces to the latest per window
    and side only where no resident has an order. Resting bids, takes and locks keep every book."""
    market = Market(tmp_path, population=12, seed=5)
    arena = market.start()
    slug = _open(market)
    for res in arena.residents.values():
        res.desk.orders.clear()
    now = market.clock.now()
    bids = tuple(Level(round(.45 - k / 100, 2), 10 + k) for k in range(25))
    asks = tuple(Level(round(.50 + k / 100, 2), 10 + k) for k in range(25))
    for n in range(5000):
        arena.feed_book(Book(slug, "up" if n % 2 else "down", bids, asks, now, f"x{n}", now))  # type: ignore[arg-type]
    started = time.thread_time()
    arena._drain(now)
    cpu = time.thread_time() - started
    assert arena.coalesced == 4998 and cpu < 0.5, (arena.coalesced, cpu)  # 5,000 books in well under a second
    seen: list[str] = []
    taker = challenger(arena)
    real = taker.desk.on_book
    taker.desk.on_book = lambda book: seen.append(book.sequence) or real(book)  # type: ignore[method-assign]
    taker.desk.orders[999] = _take(slug, now)
    arena.coalesced = 0
    for n in range(10):
        arena.feed_book(Book(slug, "up", bids, asks, now + 0.01 * n, f"t{n}", now))  # type: ignore[arg-type]
    arena._drain(now + 0.2)
    assert seen == [f"t{n}" for n in range(10)] and arena.coalesced == 0  # a pending take sees every book
    taker.desk.orders[999] = replace(_take(slug, now), kind="rest", lock=False)
    seen.clear()
    for n in range(10):
        arena.feed_book(Book(slug, "up", bids, asks, now + 0.01 * n, f"r{n}", now))
    arena._drain(now + 0.2)
    assert seen == [f"r{n}" for n in range(10)] and arena.coalesced == 0


def _take(slug: str, now: float) -> Any:
    from nightcrawler.speeddesk_model import PracticeOrder

    return PracticeOrder(999, slug, "down", "take", 0.5, 1.0, 1.0, now, now + 0.25, 0.5, 0.07, lock=True)


def test_prints_are_deduplicated_once_and_resident_memories_stay_small(tmp_path: Path) -> None:
    market = Market(tmp_path, population=12, seed=5)
    arena = market.start()
    slug = _open(market)
    assert all(res.desk.trade_memory == kalshi_arena.RESIDENT_TRADE_MEMORY for res in arena.residents.values())
    calls = Counter()
    for res in arena.residents.values():
        real = res.desk.on_trade
        res.desk.on_trade = lambda trade, now, real=real: calls.update([trade.trade_id]) or real(trade, now)  # type: ignore[method-assign]
    now = market.clock.now()
    for _ in range(3):  # the same print three times
        arena.feed_trade(Trade(slug, "up", .30, 1, now, "same", "sell", now))  # type: ignore[arg-type]
    arena._drain(now)
    assert calls["same"] == 12  # once per resident, not three times
    for n in range(kalshi_arena.SEEN_PRINTS + 100):
        arena.feed_trade(Trade(slug, "up", .30, 1, now, f"p{n}", "sell", now))  # type: ignore[arg-type]
    arena._drain(now)
    assert len(arena.seen_prints) == len(arena.print_order) == kalshi_arena.SEEN_PRINTS
    assert all(len(res.desk.seen_trades) <= kalshi_arena.RESIDENT_TRADE_MEMORY for res in arena.residents.values())


def test_births_prefer_parents_with_a_record(tmp_path: Path) -> None:
    """The review's probe: in a losing town a never-traded newborn's $50 outranked everyone who had traded."""
    arena, clock = town(tmp_path)
    for res in arena.residents.values():
        res.row.update(equity_usd=49.0, traded=50, windows=60)
    victim = challenger(arena)
    arena._evict(victim, "test", clock.now())
    arena._births(clock.now())
    newborn = max(arena.residents.values(), key=lambda res: int(res.id))
    assert newborn.row["traded"] == 0 and newborn.row["equity_usd"] == 50.0
    parents = []
    for _ in range(30):
        poorest = min((res for res in arena.residents.values() if not res.control and res is not newborn),
                      key=lambda res: res.row["equity_usd"])
        arena._evict(poorest, "test", clock.now())
        arena._births(clock.now())
        child = max(arena.residents.values(), key=lambda res: int(res.id))
        child.row.update(equity_usd=49.0, traded=0)
        parents.append(child.row["parent"])
    assert newborn.id not in parents  # 0 of 30 (the review drew it 12 times in 30)
    young, _ = town(tmp_path / "young")
    poorest = challenger(young)
    young._evict(poorest, "test", clock.now())
    young._births(clock.now())
    assert max(young.residents.values(), key=lambda res: int(res.id)).row["parent"] == control(young).id


def test_a_restart_voids_only_the_window_that_had_started(tmp_path: Path) -> None:
    clock = FakeClock(T0 - 10)
    upcoming = kalshi_window(T0 + 900)  # Kalshi lists the next window too
    snap = LiveSnapshot(windows=(kalshi_window(T0), upcoming), bitcoin_price=80_000.0, bitcoin_at=T0 + 100,
                        sigma=0.0003)
    config = ArenaConfig(data_dir=tmp_path)
    arena = KalshiArena(config, lambda: snap, clock=clock.now)
    clock.set(T0 + 100)
    arena.step(clock.now())
    assert {kalshi_window(T0).slug, upcoming.slug} <= set(arena.windows)
    arena._save(clock.now())
    clock.advance(60)  # a quick redeploy, long before the upcoming window opens
    again = KalshiArena(config, lambda: snap, clock=clock.now)
    again.step(clock.now())
    assert upcoming.slug in again.windows and kalshi_window(T0).slug not in again.windows
    assert again.town["void_windows"] == arena.town["void_windows"] + 1  # one deploy, one window (the review: 2)


def test_rent_is_charged_for_each_missed_day_up_to_a_week(tmp_path: Path) -> None:
    arena, _clock = town(tmp_path)
    settle(arena, T0, everyone(arena, None))
    settle(arena, T0 + 4 * DAY, everyone(arena, None))  # the town was down for three days
    assert control(arena).row["rent_paid"] == pytest.approx(0.8) and arena.town["rent_days"] == 4
    assert any("for 4 days" in event["text"] for event in arena.events)
    settle(arena, T0 + 40 * DAY, everyone(arena, None))
    assert control(arena).row["rent_paid"] == pytest.approx(0.8 + 0.2 * kalshi_arena.RENT_CATCHUP_DAYS)


@pytest.mark.parametrize("damage", ["deep", "pair_cap_zero", "pair_cap_tiny", "nan_grave", "nan_candidate",
                                    "bad_active", "bad_rent_day"])
def test_any_corrupt_state_moves_aside_or_is_cleaned_and_the_town_still_saves(tmp_path: Path, damage: str,
                                                                              caplog: Any) -> None:
    arena, clock = town(tmp_path)
    arena._evict(challenger(arena), "test", clock.now())
    arena._save(clock.now())
    path = tmp_path / "kalshi_arena" / "state.json"
    if damage == "deep":
        path.write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")
    else:
        raw = json.loads(path.read_text(encoding="utf-8"))
        target = next(row for row in raw["residents"] if not row["control"])
        if damage == "pair_cap_zero":
            target["genes"]["pair_cap"] = 0
        elif damage == "pair_cap_tiny":
            target["genes"]["pair_cap"] = 1e-320
        elif damage == "nan_grave":
            raw["grave"][0]["pnl_usd"] = float("nan")
        elif damage == "nan_candidate":
            target["candidate"] = {"t": float("inf"), "n": 120}
        elif damage == "bad_active":
            raw["active_windows"] = [["x", "not a time"]]
        elif damage == "bad_rent_day":
            raw["rent_day"] = "2026-99-99"
        path.write_text(json.dumps(raw), encoding="utf-8")  # json writes NaN and Infinity
    caplog.set_level(logging.WARNING, "nightcrawler.kalshi_arena")
    restored, _ = town(tmp_path)
    assert len(restored.residents) == 12
    restored._save(clock.now())  # every later save works (the review: 6 of 6 passes failed and the town halted)
    json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda name: pytest.fail(name))
    if damage in ("nan_grave", "nan_candidate"):  # one bad display row is dropped; the town is kept
        assert "kalshi_arena_state_reset" not in caplog.text
        assert set(arena.residents) <= set(restored.residents) and restored.grave == (
            [] if damage == "nan_grave" else arena.grave)
        assert all(res.row["candidate"] is None for res in restored.residents.values())
    else:
        assert "kalshi_arena_state_reset" in caplog.text
        assert any(item.name.startswith("state.json.bad-") for item in path.parent.iterdir())


def test_the_day_stop_survives_a_restart(tmp_path: Path) -> None:
    arena, clock = town(tmp_path, start=T0 + 3600)
    live = control(arena)
    settle(arena, T0, {live.id: -4.0}, now=T0 + 3600)
    assert live.row["day"] == {"day": "2026-10-08", "pnl_usd": -4.0}
    arena._save(clock.now())
    again, _ = town(tmp_path, start=T0 + 3700)
    assert again.residents[live.id].desk.days["2026-10-08"]["pnl_usd"] == -4.0
    tomorrow, _ = town(tmp_path, start=T0 + 2 * DAY)
    assert "2026-10-08" not in tomorrow.residents[live.id].desk.days  # a new day starts from zero, as live


def test_the_state_file_is_fsynced_only_after_a_change_that_matters(tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """The minute's heartbeat save (nothing changed) is a plain atomic rename: the town's fsyncs share the live
    desk's volume and journal, so it fsyncs only after a settlement, birth, eviction, void, flag or halt."""
    arena, clock = town(tmp_path)
    synced: list[int] = []
    real = os.fsync
    monkeypatch.setattr(kalshi_arena.os, "fsync", lambda fd: synced.append(fd) or real(fd))
    arena._save(clock.now())
    assert len(synced) == 1  # state.json (the town's only record); the panel is a display copy
    for _ in range(3):  # three heartbeats with nothing to record
        clock.advance(kalshi_arena.SAVE_EVERY_S)
        arena.step(clock.now())
        assert arena.saved_at == clock.now()
    assert len(synced) == 1
    settle(arena, T0, everyone(arena, 0.25))  # a settlement: the next save is durable
    clock.advance(kalshi_arena.SAVE_SOON_S)
    arena.step(clock.now())
    assert len(synced) == 2 and arena.saved_at == clock.now()
    arena._halt(RuntimeError("synthetic"))
    assert len(synced) == 3


def test_a_halt_on_a_full_disk_still_reaches_the_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """On a full disk (the volume the live desk shares) the larger state file fails first; the halt still reaches
    the panel, written on its own, in its brief form when the whole panel does not fit either."""
    import errno

    arena, clock = town(tmp_path)
    arena._save(clock.now())
    real = kalshi_arena._write
    room = {"bytes": 10**9}

    def full(path: Path, text: str, *, durable: bool = False) -> None:
        if path.name == "state.json" or len(text) > room["bytes"]:
            raise OSError(errno.ENOSPC, "No space left on device")
        real(path, text, durable=durable)

    monkeypatch.setattr(kalshi_arena, "_write", full)
    clock.advance(5)
    arena._halt(OSError(errno.ENOSPC, "No space left on device"))
    panel = kalshi_arena.panel_state(tmp_path, clock.now())
    assert "live desk is unaffected" in panel["problem"] and panel["as_of"] == clock.now()
    assert len(panel["residents"]) == 12  # the whole panel still fit
    room["bytes"] = 1_000  # only a small file fits now
    clock.advance(5)
    arena._halt(OSError(errno.ENOSPC, "No space left on device"))
    brief = kalshi_arena.panel_state(tmp_path, clock.now())
    assert "live desk is unaffected" in brief["problem"] and brief["as_of"] == clock.now()
    assert "residents" not in brief and brief["town_id"] == arena.town_id
    assert sorted(path.name for path in (tmp_path / "kalshi_arena").iterdir()) == ["panel.json", "state.json"]


def test_the_share_of_a_core_counts_the_whole_process(tmp_path: Path) -> None:
    """duty_pct is the process's CPU over wall time: reading and decoding frames happen outside step() (about half
    the town's CPU at 400 books a second), and the status line must not report only the half inside it."""
    clock = FakeClock(T0)
    used = {"cpu": 0.0}
    arena = KalshiArena(ArenaConfig(data_dir=tmp_path), LiveSnapshot, clock=clock.now, cpu=lambda: used["cpu"])
    for _ in range(10):
        used["cpu"] += 0.03  # the frames of the last 0.1 s, read and decoded before the pass
        clock.advance(0.1)
        arena.step(clock.now())
    assert arena.telemetry(clock.now())["duty_pct"] == pytest.approx(30.0, abs=0.5)
    arena._status(clock.now())  # each status line starts a new period
    clock.advance(1.0)
    assert arena.telemetry(clock.now())["duty_pct"] == 0.0


def test_an_eviction_line_cuts_its_reason_after_a_whole_word(tmp_path: Path) -> None:
    arena, clock = town(tmp_path)
    victim = challenger(arena)
    why = ("losing: 26 settled, 17 lost, -$9.88 in all; even at best -$0.05 a settlement (99 % sure, early stop) and "
           "a few more words of a long reason")
    arena._evict(victim, why, clock.now())
    line = arena.events[0]
    assert line["kind"] == "evicted" and line["resident_id"] == victim.id
    assert len(line["text"]) <= kalshi_arena.EVENT_TEXT and line["text"].endswith(" windows traded, +0.00 $).")
    reason = line["text"].split(" was evicted: ", 1)[1].rsplit(" after ", 1)[0]
    kept = reason.removesuffix("…")
    assert reason.endswith("…") and why.startswith(kept) and why[len(kept)] in " ,;:("
    assert arena.grave[0]["why"] == why[:160]  # the grave keeps the reason whole


def test_a_failed_write_leaves_no_temporary_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A full disk: the partial temporary copy is removed (DATA_DIR is the live desk's volume too) and the last good
    file stands."""
    import errno

    path = tmp_path / "state.json"
    kalshi_arena._write(path, '{"good": 1}', durable=True)

    def full(_fd: int) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(kalshi_arena.os, "fsync", full)
    with pytest.raises(OSError):
        kalshi_arena._write(path, '{"good": 2}' + " " * 100_000, durable=True)
    assert sorted(item.name for item in tmp_path.iterdir()) == ["state.json"]
    assert json.loads(path.read_text(encoding="utf-8")) == {"good": 1}


def test_the_panel_says_the_control_runs_the_configured_limits_not_the_ladder(tmp_path: Path) -> None:
    """The town reads Settings once: every resident, the control included, runs the configured limits, which are the
    live earned-growth ladder's rung 0. After a live promotion live trades a bigger window; the page says so."""
    from nightcrawler.speeddesk_live_ladder import rung_limits

    settings = Settings(data_dir=tmp_path)
    fixed, base = fixed_config(settings), kalshi_arena._limits(settings)
    rung0, rung1 = rung_limits(base, 0), rung_limits(base, 1)
    assert (fixed["window_usd"], fixed["open_usd"], fixed["day_stop_usd"]) == (
        rung0.window_usd, rung0.open_usd, rung0.day_loss_usd)
    assert rung1.window_usd > fixed["window_usd"]  # what the note owns up to
    assert "rung 0" in kalshi_arena.NOTE and "promotion" in kalshi_arena.NOTE and len(kalshi_arena.NOTE) <= 400
    arena, clock = town(tmp_path)
    assert arena.panel(clock.now())["note"] == kalshi_arena.NOTE
