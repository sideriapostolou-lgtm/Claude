"""The practice LIP desk on the page: the top-level ``kalshi_lip_practice`` block (its contract with the town is
docs/COORDINATION.md "kalshi_lip_practice contract" and the fixture ``tests/fixtures/kalshi_lip_practice_page.json``):
off by default, practice-labelled, read from panel.json only, every field whitelisted, never summed into anything."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from fakes import load_fixture

from nightcrawler import pagestate
from nightcrawler.ledger import Ledger

FIXTURE = load_fixture("kalshi_lip_practice_page")
CASES = FIXTURE["cases"]
ON = {"KALSHI_LIP_PRACTICE_ENABLED": "true"}
EMPTY = ("as_of", "heartbeat_s", "problem", "note", "primary_family", "policies", "fill_models", "scorecard",
         "accounts", "windows", "feed")


def write_panel(data_dir: Path, panel: Any) -> None:
    (data_dir / "kalshi_lip_practice").mkdir(parents=True, exist_ok=True)
    (data_dir / "kalshi_lip_practice" / "panel.json").write_text(json.dumps(panel, allow_nan=False),
                                                                 encoding="utf-8")


def fresh_panel() -> dict[str, Any]:
    return copy.deepcopy(CASES["fresh"]["kalshi_lip_practice"])


@pytest.mark.parametrize("name", sorted(CASES))
def test_each_fixture_case_is_exactly_what_the_page_emits(name: str, make_settings: Any) -> None:
    case = CASES[name]
    block = case["kalshi_lip_practice"]
    settings = make_settings()
    if block["status"] not in ("missing", "off"):
        write_panel(settings.data_dir, block)
    env = {} if block["status"] == "off" else ON
    assert pagestate.kalshi_lip_practice_block(settings, case["generated_at"], env) == block


def test_the_fixture_cases_mean_what_the_contract_says() -> None:
    expect = {"fresh": ("fresh", None), "stale": ("stale", "heartbeat_late"), "missing_no_file": ("missing",
                                                                                                "not_saved_yet"),
              "off": ("off", "disabled")}
    for name, (status, reason) in expect.items():
        block = CASES[name]["kalshi_lip_practice"]
        assert (block["status"], block["reason"]) == (status, reason)
        assert (block["schema_version"], block["mode"], block["real_orders_enabled"]) == (1, "paper", False)
        assert block["label"] == "Practice (pretend money)" and block["stale_after_s"] == 180.0
        if status in ("missing", "off"):
            assert block["stale"] is None and all(block[key] is None for key in EMPTY)
    fresh = CASES["fresh"]["kalshi_lip_practice"]
    assert fresh["stale"] is False and CASES["stale"]["kalshi_lip_practice"]["stale"] is True
    assert [row["name"] for row in fresh["policies"]] == ["ref_stop5", "ref_close", "best_stop5", "ref_pyth_pull"]
    assert fresh["fill_models"] == ["timed", "fee_timed"] and fresh["primary_family"] == "FX"
    assert {row["family"] for row in fresh["scorecard"]} == {"FX", "all"}
    assert len(fresh["accounts"]) == 8 and fresh["windows"]["settled"] == 1


def test_the_page_shows_the_desk_at_the_top_level_and_off_by_default(make_settings: Any, fake_clock: Any,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(POLYDESK_ENABLED=False, TRENDDESK_ENABLED=False)
    now = CASES["fresh"]["generated_at"]
    write_panel(settings.data_dir, fresh_panel())
    monkeypatch.delenv("KALSHI_LIP_PRACTICE_ENABLED", raising=False)
    with Ledger(settings.db_path, clock=fake_clock) as ledger:
        off = pagestate.build_page_state(ledger, settings, now)
        monkeypatch.setenv("KALSHI_LIP_PRACTICE_ENABLED", "true")
        on = pagestate.build_page_state(ledger, settings, now)
    assert off["kalshi_lip_practice"]["status"] == "off" and "kalshi_lip_practice" not in off["money"]
    assert on["kalshi_lip_practice"] == CASES["fresh"]["kalshi_lip_practice"]


def test_no_money_figure_reads_the_practice_desk(make_settings: Any, fake_clock: Any,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """Practice money never reaches real cash, the town, the goal, the hearts or the words: the whole page is the same
    with the desk on or off, except its own block."""
    settings = make_settings(POLYDESK_ENABLED=False, TRENDDESK_ENABLED=False)
    now = CASES["fresh"]["generated_at"]
    panel = fresh_panel()
    for row in panel["accounts"]:
        row["equity_usd"] = 5_000.0  # a fortune of pretend money
    write_panel(settings.data_dir, panel)
    with Ledger(settings.db_path, clock=fake_clock) as ledger:
        monkeypatch.setenv("KALSHI_LIP_PRACTICE_ENABLED", "true")
        shown = pagestate.build_page_state(ledger, settings, now)
        monkeypatch.setenv("KALSHI_LIP_PRACTICE_ENABLED", "false")
        hidden = pagestate.build_page_state(ledger, settings, now)
    assert shown["kalshi_lip_practice"]["accounts"][0]["equity_usd"] == 5_000.0
    assert "5000" not in json.dumps({key: value for key, value in shown.items() if key != "kalshi_lip_practice"})
    for page in (shown, hidden):
        page.pop("kalshi_lip_practice")
        page["about"].pop("uptime_s", None)
    assert shown == hidden


def test_status_rule_missing_unreadable_halted_and_degraded(make_settings: Any, caplog: Any) -> None:
    settings = make_settings()
    now = CASES["fresh"]["generated_at"]
    assert pagestate.kalshi_lip_practice_block(settings, now, ON)["reason"] == "not_saved_yet"
    halted = fresh_panel()
    halted["problem"] = "Practice LIP desk halted after repeated errors"
    write_panel(settings.data_dir, halted)
    assert pagestate.kalshi_lip_practice_block(settings, now, ON)["status"] == "halted"
    quiet = fresh_panel()
    quiet["feed"]["last_new_at"] = quiet["as_of"] - 500
    write_panel(settings.data_dir, quiet)
    assert pagestate.kalshi_lip_practice_block(settings, now, ON)["reason"] == "feed_quiet"
    nowhere = fresh_panel()
    nowhere["feed"]["recorder_dir_found"] = False
    write_panel(settings.data_dir, nowhere)
    assert pagestate.kalshi_lip_practice_block(settings, now, ON)["reason"] == "no_recorder"
    future = fresh_panel()
    future["as_of"] = now + 3600
    write_panel(settings.data_dir, future)
    assert pagestate.kalshi_lip_practice_block(settings, now, ON)["reason"] == "as_of_future"
    write_panel(settings.data_dir, {"label": "Real money", "real_orders_enabled": True, "mode": "live"})
    broken = pagestate.kalshi_lip_practice_block(settings, now, ON)
    assert (broken["status"], broken["reason"], broken["real_orders_enabled"], broken["mode"]) == (
        "missing", "unreadable", False, "paper")
    assert "kalshi_lip_practice_panel_failed error=ValueError" in caplog.text


def test_a_huge_panel_is_refused_unread(make_settings: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings()
    write_panel(settings.data_dir, {"label": "Practice (pretend money)", "note": "x" * 300_000})
    read: list[str] = []
    real = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda path, *a, **k: read.append(path.name) or real(path, *a, **k))
    assert pagestate.kalshi_lip_practice_block(settings, 0.0, ON)["reason"] == "unreadable"
    assert read == []


def test_every_field_is_whitelisted_and_texts_are_redacted(make_settings: Any) -> None:
    settings = make_settings()
    now = CASES["fresh"]["generated_at"]
    panel = fresh_panel()
    panel["scorecard"][0].update(model="lenient", family="Sports", reward_usd="lots", day="yesterday",
                                 extra="never shown")
    panel["accounts"][0].update(account="sk-" + "a" * 40 + "!", series=["KXEURUSD15M", {"x": 1}], periods=-3)
    panel["policies"][0].update(place="anywhere", size="10")
    panel["note"] = "Practice only sk-ant-" + "b" * 40  # an Anthropic-key-shaped text
    panel["secret_field"] = "never shown"
    write_panel(settings.data_dir, panel)
    block = pagestate.kalshi_lip_practice_block(settings, now, ON)
    row = block["scorecard"][0]
    assert (row["model"], row["family"], row["reward_usd"], row["day"]) == (None, None, None, None)
    assert "extra" not in row and "secret_field" not in block
    assert block["accounts"][0]["account"] is None and block["accounts"][0]["series"] == ["KXEURUSD15M"]
    assert block["accounts"][0]["periods"] is None
    assert block["policies"][0]["place"] is None and block["policies"][0]["size"] is None
    assert "b" * 40 not in json.dumps(block)
