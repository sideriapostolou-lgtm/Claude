"""Independent money clocks cannot freshen another account or incomplete profits."""

from pathlib import Path

from test_world_tycoon_connections import connected
from test_world_tycoon_data import NOW, run


def test_fast_kalshi_report_does_not_refresh_polymarket_or_require_crew(tmp_path: Path) -> None:
    value = connected()
    value["generated_at"] = NOW - 1000
    value["money"]["_town_kalshi_generated_at"] = NOW
    value["money"]["connections"]["kalshi"]["total_pnl_usd"] = -22.90
    value["plain"] = {}
    value["team"] = {}
    result = run(tmp_path, value)
    assert result["focus"]["cash"] == 25
    assert result["focus"]["today"] == .10
    assert result["focus"]["total"] == -22.90
    assert result["pageStale"] is True
    assert result["business"]["venues"]["polymarket_us"]["current"] is False
    assert {row["key"] for row in result["crew"]} == {"voss", "rook", "jet", "mote"}
    assert all(row["status"] != "working" for row in result["crew"])


def test_independent_book_failure_keeps_cash_but_hides_unverified_results(tmp_path: Path) -> None:
    value = connected()
    value["money"]["connections"]["kalshi"]["status"] = "incomplete"
    result = run(tmp_path, value)
    assert result["focus"]["cash"] == 25
    assert result["focus"]["today"] is None
    assert result["focus"]["total"] is None


def test_funding_and_daily_stop_keep_their_own_times_and_exposure(tmp_path: Path) -> None:
    value = connected()
    value["money"]["speeddesk"]["kalshi_live"].update(
        mode="paper", active=False, day_stop_latched=True,
        shard_funding={"at": NOW - 80, "balances": [{"exchange_index": 2, "balance_usd": 0}]},
        create_funding_cooldown={"until": NOW + 20, "remaining_s": 200},
        open_cost_usd=4.15,
    )
    result = run(tmp_path, value)
    account = result["accounts"]["kalshi"]
    assert account["state"] == "blocked"
    assert account["stateText"] == "Daily loss stop: no new real bets; filled bets remain"
    assert account["shardStale"] is True and account["shardAge"] == 80
    assert account["fundingCooldownRemaining"] == 20
    assert account["accountAt"] is None
    assert result["focus"]["openCost"] == 4.15
    assert result["focus"]["exposure"] == 1.98
