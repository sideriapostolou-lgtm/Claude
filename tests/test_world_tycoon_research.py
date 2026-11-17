"""Practice coverage keeps source cadences, unknown values and real money separate."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from nightcrawler.worldtycoon_data import TYCOON_DATA
from nightcrawler.worldtycoon_research import TYCOON_RESEARCH

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
NOW = 1_800_000_000


def run(tmp_path: Path, value: Any, *, current: bool = True) -> dict[str, Any]:
    assert TYCOON_RESEARCH in TYCOON_DATA
    script = tmp_path / "research.mjs"
    script.write_text(TYCOON_DATA + "\nconst input = " + json.dumps(value) + ";\n"
                      + "const before = JSON.stringify(input);\n"
                      + f"const rows = tycoonResearch(input, {NOW}, {json.dumps(current)});\n"
                      + "if (JSON.stringify(input) !== before) throw new Error('mutated input');\n"
                      + "console.log(JSON.stringify(Object.fromEntries(rows.map(r => [r.key, r]))));\n")
    result = subprocess.run(["node", str(script)], capture_output=True, text=True, check=True, timeout=20)
    out: dict[str, Any] = json.loads(result.stdout)
    return out


def reports() -> dict[str, Any]:
    return {
        "money": {
            "speeddesk": {"as_of": NOW - 2, "mode": "paper",
                          "today": {"day": datetime.fromtimestamp(NOW, UTC).date().isoformat(), "fills": 8},
                          "kalshi_live": {"active": True, "mode": "live", "today": {"fills": 999}}},
            "trend": {"as_of": NOW - 72000, "mode": "paper", "in_market": {"BTC": True, "ETH": False, "SOL": True}},
            "arena": {"as_of": NOW - 100, "population": 24},
            "marco": {"as_of": NOW - 300, "mode": "paper", "record": {"picks": 17}, "picks": [{}, {}]},
            "nhl": {"as_of": NOW - 500, "mode": "paper", "record": {"picks": 5}},
        },
        "skipwatch": {"as_of": NOW - 20, "wallet_fills": 150},
        "weatherwatch": {"as_of": NOW - 90, "active_watches": 3},
    }


def test_all_seven_services_use_their_own_books_and_timestamps(tmp_path: Path) -> None:
    out = run(tmp_path, reports())
    assert list(out) == ["speed", "watcher", "weather", "trend", "arena", "marco", "nhl"]
    assert [r["count"] for r in out.values()] == [8, 150, 3, 2, 24, 17, 5]
    assert all(r["current"] and r["state"] == "observing" and r["realOrders"] is False for r in out.values())
    assert [r["scope"] for r in out.values()] == ["PRACTICE", "READ ONLY", "READ ONLY"] + ["PRACTICE"] * 4
    assert out["trend"]["timeLabel"] == "Daily close (UTC)" and out["trend"]["age"] == 72000
    assert out["marco"]["countLabel"] == "practice picks settled"  # Not the truncated visible pick rows.
    assert all("pnl" not in r and r["count"] != 999 for r in out.values())


def test_no_report_is_unknown_not_an_empty_or_active_business(tmp_path: Path) -> None:
    out = run(tmp_path, {})
    assert len(out) == 7
    assert all(r["count"] is None and r["asOf"] is None and not r["current"] for r in out.values())
    assert all(r["state"] == "unknown" and r["realOrders"] is False for r in out.values())
    value = reports()
    value["money"]["arena"] = {"population": 0}
    assert run(tmp_path, value)["arena"]["count"] is None
    value["money"]["arena"]["as_of"] = NOW
    assert run(tmp_path, value)["arena"]["count"] == 0


def test_service_cadences_do_not_claim_a_daily_close_is_a_live_heartbeat(tmp_path: Path) -> None:
    value = reports()
    value["money"]["trend"]["as_of"] = NOW - 90001
    value["money"]["arena"]["as_of"] = NOW - 181
    value["money"]["marco"]["as_of"] = NOW - 601
    value["money"]["nhl"]["as_of"] = NOW - 599
    out = run(tmp_path, value)
    assert all(not out[key]["current"] for key in ("trend", "arena", "marco"))
    assert out["nhl"]["current"] and out["speed"]["current"]
    assert out["trend"]["asOf"] == NOW - 90001 and out["trend"]["count"] == 2
    assert all(not r["current"] for r in run(tmp_path, reports(), current=False).values())


def test_invalid_counts_timestamps_or_modes_do_not_become_practice_activity(tmp_path: Path) -> None:
    value = reports()
    value["money"]["arena"]["population"] = True
    value["money"]["trend"]["in_market"]["BTC"] = "true"
    value["money"]["marco"]["as_of"] = NOW + 61
    value["money"]["nhl"]["mode"] = "live"
    value["money"]["speeddesk"]["today"]["day"] = "2000-01-01"
    out = run(tmp_path, value)
    assert all(out[key]["count"] is None for key in ("arena", "trend", "marco", "nhl", "speed"))
    assert out["marco"]["asOf"] is None and not out["marco"]["current"]
    assert not out["nhl"]["current"] and "unexpected mode" in out["nhl"]["status"]
    assert out["nhl"]["scope"] == "PRACTICE" and not out["nhl"]["realOrders"]


def test_each_service_problem_is_reported_without_affecting_other_services(tmp_path: Path) -> None:
    value = reports()
    value["money"]["trend"]["problem"] = "Behind: the newest daily close is not booked."
    value["weatherwatch"]["problem"] = "Waiting for official weather observations."
    out = run(tmp_path, value)
    assert out["trend"]["state"] == "attention" and out["trend"]["status"].startswith("Behind:")
    assert out["weather"]["state"] == "attention" and "official" in out["weather"]["status"]
    assert out["arena"]["state"] == "observing"
