"""The Kalshi arena on the page: ``money.kalshi_arena``, practice-labelled, from panel.json only, never summed."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest
from kalshi_arena_world import T0, kalshi_window

from nightcrawler import pagestate
from nightcrawler.kalshi_arena import ArenaConfig, KalshiArena, adoptable
from nightcrawler.ledger import Ledger
from nightcrawler.speeddesk_live import LiveSnapshot


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
    star.row["since_flag"] = {"n": 3, "sum": 0.1, "sumsq": 0.02}
    star.row["name"] = "Ivy-9 sk-" + "a" * 40  # a secret-shaped text is redacted, not shown
    arena._save(now)
    return arena


def test_the_page_shows_the_town_labelled_practice(make_settings: Any, fake_clock: Any) -> None:
    settings = make_settings(POLYDESK_ENABLED=False, TRENDDESK_ENABLED=False)
    now = fake_clock.now()
    saved_town(settings.data_dir, now)
    with Ledger(settings.db_path, clock=fake_clock) as ledger:
        page = pagestate.build_page_state(ledger, settings, now)
    town = page["money"]["kalshi_arena"]
    assert town["label"] == "Practice (pretend money)" and town["stale"] is False
    assert town["population"] == 12 and len(town["residents"]) == 12 and town["control"]["name"] == "Live"
    assert town["candidates"][0]["n"] == 120 and "not proof" in town["candidates"][0]["note"]
    assert set(town["candidates"][0]["adopt"]["settings"]) >= {"SPEEDDESK_MAKE_EDGE", "SPEEDDESK_KALSHI_LOCK_S"}
    assert "a" * 40 not in json.dumps(town)
    assert set(town["feed"]) >= {"queue", "received", "dropped", "coalesced", "pass_p99_ms", "duty_pct",
                                 "live_flush_us_p99"}
    assert town["town"]["void_feed"] == 0
    assert all(event["kind"] in ("born", "evicted", "candidate", "rent", "control", "void", "")
               for event in town["events"])
    later = pagestate.kalshi_arena_town(settings, now + 600)
    assert later is not None and later["stale"] is True


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
    assert pagestate.kalshi_arena_town(settings, now) is not None
    assert read == ["panel.json"]


def test_off_missing_or_broken_panels_show_nothing(make_settings: Any, fake_clock: Any, caplog: Any) -> None:
    now = fake_clock.now()
    assert pagestate.kalshi_arena_town(make_settings(), now) is None  # not saved yet: quietly nothing
    saved_town(make_settings().data_dir, now)
    assert pagestate.kalshi_arena_town(make_settings(KALSHI_ARENA_ENABLED=False), now) is None
    assert pagestate.kalshi_arena_town(make_settings(SPEEDDESK_KALSHI_ENABLED=False), now) is None
    panel = make_settings().data_dir / "kalshi_arena" / "panel.json"
    panel.write_text('{"label": "Real money"}', encoding="utf-8")
    assert pagestate.kalshi_arena_town(make_settings(), now) is None
    assert "kalshi_arena_panel_failed error=ValueError" in caplog.text


def test_the_town_ledger_never_counts_the_arena(make_settings: Any, fake_clock: Any) -> None:
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
    assert shown["money"]["kalshi_arena"]["residents"][0]["equity_usd"] == 5_000.0
    assert hidden["money"]["kalshi_arena"] is None
    assert shown["town"] == hidden["town"]
    for key in ("usd", "today", "since_start", "polymarket"):
        assert shown["money"][key] == hidden["money"][key]
    assert shown["plain"]["real"] == hidden["plain"]["real"]
