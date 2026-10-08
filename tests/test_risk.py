"""RiskManager: sizing clamps and reserve, and every can_open rule in its documented order."""

from __future__ import annotations

from typing import Any

import pytest

from nightcrawler.models import LAMPORTS_PER_SOL, TOKEN_ACCOUNT_RENT_LAMPORTS, EquityPoint, Position
from nightcrawler.risk import KILL_WORDS, RiskManager, size_position_usd
from test_broker_paper import FakeLedger

SOL = LAMPORTS_PER_SOL
NOW = 1_791_475_200.0  # conftest FIXED_NOW: 2026-10-08T16:00:00Z
MIDNIGHT = NOW - 16 * 3600
MINT = "DoVAVzViX8Bjy3r15nwikSaSbzE6dV4ovd28aWpJpump"


@pytest.fixture
def ledger(fake_clock) -> FakeLedger:
    return FakeLedger(clock=fake_clock)


@pytest.fixture
def make_risk(make_settings, ledger, fake_clock):
    def _make(**settings: Any) -> RiskManager:
        return RiskManager(make_settings(**settings), ledger, fake_clock)

    return _make


@pytest.fixture
def risk(make_risk) -> RiskManager:
    return make_risk()


def equity(ledger: FakeLedger, ts: float, lamports: int, mode: str = "paper") -> None:
    ledger.record_equity(EquityPoint(ts=ts, equity_lamports=lamports, sol_usd=100.0, equity_usd=lamports / SOL * 100,
                                     mode=mode))


def position(mint: str = MINT, status: str = "open", closed_at: float | None = None, pid: str = "p") -> Position:
    return Position(id=pid, mint=mint, symbol="X", pool=None, opened_at=NOW - 3600, token_decimals=6,
                    status=status, closed_at=closed_at)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- sizing


@pytest.mark.parametrize("equity_usd, expected", [
    (100.0, 20.0),  # POSITION_PCT of equity
    (200.0, 25.0),  # clamped to MAX_POSITION_USD
    (25.0, 5.0),  # exactly MIN_POSITION_USD is allowed
    (20.0, 0.0),  # $4 target: never rounded UP to the minimum
    (0.0, 0.0),
    (-50.0, 0.0),
])
def test_size_position_usd_is_pure_and_clamped(equity_usd: float, expected: float) -> None:
    assert size_position_usd(equity_usd, 0.20, 5.0, 25.0) == pytest.approx(expected)


def test_size_position_converts_usd_target_to_lamports(risk) -> None:
    assert risk.size_position(1 * SOL, 100.0) == 200_000_000  # $20 of $100
    assert risk.size_position(2 * SOL, 100.0) == 250_000_000  # clamped at $25
    assert risk.size_position(int(0.24 * SOL), 100.0) == 0  # $4.80 target < $5 minimum


def test_size_position_keeps_reserve_fee_and_rent(risk) -> None:
    overhead = 20_000_000 + 300_000 + TOKEN_ACCOUNT_RENT_LAMPORTS
    assert risk.size_position(1 * SOL, 100.0, available_lamports=100_000_000) == 100_000_000 - overhead
    assert risk.size_position(1 * SOL, 100.0, available_lamports=70_000_000) == 0  # $4.77 left < $5
    assert risk.size_position(1 * SOL, 100.0, available_lamports=10_000_000) == 0  # below the reserve


def test_size_position_without_a_sol_price_is_zero(risk) -> None:
    assert risk.size_position(1 * SOL, 0.0) == 0
    assert risk.size_position(1 * SOL, -1.0) == 0


# --------------------------------------------------------------------------- kill switch


def test_kill_switch_defaults_off(risk) -> None:
    assert risk.kill_mode() == "off"
    assert risk.can_open(MINT, [], SOL) == (True, "ok")


@pytest.mark.parametrize("content, mode", [
    ("stop", "stop"), ("  SELL_ALL\n", "sell_all"), ("sell-all", "sell_all"), ("sell all", "sell_all"),
    ("off", "off"), ("", "stop"), ("please stop now", "stop"), ("\x00\x01", "stop"),
])
def test_kill_file_words_and_fail_safe(risk, tmp_data_dir, content: str, mode: str) -> None:
    (tmp_data_dir / "KILL").write_text(content, encoding="utf-8")
    assert risk.kill_mode() == mode


def test_unreadable_kill_file_means_stop(risk, tmp_data_dir) -> None:
    (tmp_data_dir / "KILL").mkdir()  # reading a directory raises OSError
    assert risk.kill_mode() == "stop"
    (tmp_data_dir / "KILL").rmdir()
    (tmp_data_dir / "KILL").write_bytes(b"\xff\xfe\xfa")  # not UTF-8
    assert risk.kill_mode() == "stop"


def test_most_severe_of_env_and_file_wins(make_risk, tmp_data_dir) -> None:
    assert make_risk(KILL_SWITCH="stop").kill_mode() == "stop"
    (tmp_data_dir / "KILL").write_text("sell_all")
    assert make_risk(KILL_SWITCH="stop").kill_mode() == "sell_all"
    (tmp_data_dir / "KILL").write_text("off")
    assert make_risk(KILL_SWITCH="sell_all").kill_mode() == "sell_all"
    assert KILL_WORDS == ("off", "stop", "sell_all")


def test_kill_switch_blocks_entries(make_risk, tmp_data_dir) -> None:
    assert make_risk(KILL_SWITCH="stop").can_open(MINT, [], SOL) == (False, "[kill] kill switch is stop")
    (tmp_data_dir / "KILL").write_text("sell_all")
    ok, reason = make_risk().can_open(MINT, [], SOL)
    assert not ok and reason.startswith("[kill]") and "sell_all" in reason


# --------------------------------------------------------------------------- drawdown halt


def test_drawdown_engages_a_persistent_halt_with_a_receipt(make_risk, ledger) -> None:
    risk = make_risk(DAILY_LOSS_LIMIT_PCT=0.99)  # isolate the drawdown rule
    equity(ledger, NOW - 7200, 2 * SOL)
    equity(ledger, NOW - 60, int(1.2 * SOL))
    assert risk.can_open(MINT, [], int(1.01 * SOL)) == (True, "ok")
    assert ledger.get_kv("risk.halted") is None

    ok, reason = risk.can_open(MINT, [], int(0.99 * SOL))
    assert not ok and reason.startswith("[drawdown]") and "50.5%" in reason
    assert risk.is_halted()[0]
    assert ledger.get_kv("risk.halted")["halted"] is True
    (halt,) = [r for r in ledger.receipts() if r.kind == "halt"]
    assert "below the peak" in halt.payload["reason"]

    # stays halted even if equity recovers, until a manual reset
    ok, reason = risk.can_open(MINT, [], 3 * SOL)
    assert not ok and reason.startswith("[halted]")


def test_drawdown_boundary_is_strict(make_risk, ledger) -> None:
    risk = make_risk(DAILY_LOSS_LIMIT_PCT=0.99)
    equity(ledger, NOW - 60, 2 * SOL)
    assert risk.can_open(MINT, [], 1 * SOL) == (True, "ok")  # exactly -50 % is not below the limit
    assert risk.can_open(MINT, [], 1 * SOL - 1)[1].startswith("[drawdown]")


def test_reset_clears_the_halt_and_restarts_the_peak(make_risk, ledger, fake_clock) -> None:
    risk = make_risk(DAILY_LOSS_LIMIT_PCT=0.99)
    equity(ledger, NOW - 60, 2 * SOL)
    assert risk.can_open(MINT, [], int(0.9 * SOL))[1].startswith("[drawdown]")

    fake_clock.advance(5)
    risk.reset_halt("operator checked the wallet")
    assert risk.is_halted() == (False, "")
    assert ledger.get_kv("risk.peak_reset_ts") == fake_clock.now()
    (reset,) = [r for r in ledger.receipts() if r.kind == "reset"]
    assert reset.payload["note"] == "operator checked the wallet"
    assert risk.peak_equity() is None  # the old 2 SOL peak no longer counts
    assert risk.can_open(MINT, [], int(0.9 * SOL)) == (True, "ok")
    assert ledger.verify_chain() == (True, None)


def test_peak_tracks_new_snapshots_and_resets_from_other_processes(risk, ledger, fake_clock) -> None:
    assert risk.peak_equity() is None
    equity(ledger, NOW - 120, 1 * SOL)
    equity(ledger, NOW - 60, 3 * SOL)
    assert risk.peak_equity() == 3 * SOL
    equity(ledger, NOW - 30, 2 * SOL)
    assert risk.peak_equity() == 3 * SOL
    ledger.set_kv("risk.peak_reset_ts", NOW - 45)  # e.g. `nightcrawler` CLI reset in another process
    assert risk.peak_equity() == 2 * SOL


# --------------------------------------------------------------------------- daily loss


def test_daily_loss_uses_the_first_snapshot_of_the_utc_day(risk, ledger) -> None:
    equity(ledger, MIDNIGHT - 60, int(0.5 * SOL))  # yesterday: must NOT be the baseline
    equity(ledger, MIDNIGHT + 300, 1 * SOL)
    equity(ledger, NOW - 60, int(0.85 * SOL))
    assert risk.day_start_equity() == 1 * SOL
    assert risk.can_open(MINT, [], int(0.81 * SOL)) == (True, "ok")
    ok, reason = risk.can_open(MINT, [], int(0.79 * SOL))
    assert not ok and reason.startswith("[daily_loss]") and "21.0%" in reason


def test_daily_loss_falls_back_to_the_last_snapshot_before_midnight(risk, ledger) -> None:
    equity(ledger, MIDNIGHT - 7200, int(1.2 * SOL))
    equity(ledger, MIDNIGHT - 60, 1 * SOL)
    assert risk.day_start_equity() == 1 * SOL
    assert risk.can_open(MINT, [], int(0.79 * SOL))[1].startswith("[daily_loss]")


def test_daily_loss_resets_the_next_utc_day(risk, ledger, fake_clock) -> None:
    equity(ledger, MIDNIGHT + 60, 1 * SOL)
    assert risk.can_open(MINT, [], int(0.7 * SOL))[1].startswith("[daily_loss]")
    fake_clock.set(MIDNIGHT + 86_400 + 30)
    equity(ledger, MIDNIGHT + 86_400 + 10, int(0.7 * SOL))
    assert risk.can_open(MINT, [], int(0.7 * SOL)) == (True, "ok")


def test_no_snapshots_means_current_equity_is_the_baseline(risk) -> None:
    assert risk.day_start_equity() is None
    assert risk.can_open(MINT, [], 1) == (True, "ok")


# --------------------------------------------------------------------------- positions & cooldown


def test_max_open_positions_counts_only_open_ones(risk) -> None:
    three = [position(f"m{i}", pid=f"p{i}") for i in range(3)]
    assert risk.can_open(MINT, three, SOL) == (False, "[max_positions] 3 open (MAX_OPEN_POSITIONS 3)")
    three[0].status = "closed"
    assert risk.can_open(MINT, three, SOL) == (True, "ok")


def test_already_open_mint_is_refused(risk) -> None:
    ok, reason = risk.can_open(MINT, [position()], SOL)
    assert not ok and reason.startswith("[already_open]")


def test_cooldown_after_closing_a_mint(risk, ledger) -> None:
    ledger.upsert_position(position(status="closed", closed_at=NOW - 10 * 60))
    ok, reason = risk.can_open(MINT, [], SOL)
    assert not ok and reason == "[cooldown] closed 10.0 min ago (COOLDOWN_MIN 30)"
    assert risk.can_open("OtherMint1111111111111111111111111111111111", [], SOL) == (True, "ok")
    ledger.upsert_position(position(status="closed", closed_at=NOW - 31 * 60))  # same id: older close
    assert risk.can_open(MINT, [], SOL) == (True, "ok")


# --------------------------------------------------------------------------- wallet cap


def test_wallet_cap_applies_only_in_live_mode(make_risk) -> None:
    live = make_risk(TRADING_MODE="live", LIVE_CONFIRM="I_ACCEPT_REAL_MONEY_RISK", BOT_WALLET_SECRET="x" * 88,
                     DASHBOARD_HOST="127.0.0.1")
    assert live.can_open(MINT, [], SOL, wallet_usd=149.0) == (True, "ok")
    ok, reason = live.can_open(MINT, [], SOL, wallet_usd=151.0)
    assert not ok and reason.startswith("[wallet_cap] wallet worth $151.00")
    ok, reason = live.can_open(MINT, [], SOL, wallet_usd=None)
    assert not ok and reason.startswith("[wallet_cap]") and "unknown" in reason
    assert make_risk().can_open(MINT, [], SOL, wallet_usd=10_000.0) == (True, "ok")


# --------------------------------------------------------------------------- rule order


def test_rules_are_checked_in_the_documented_order(make_risk, ledger, tmp_data_dir, fake_clock) -> None:
    live = {"TRADING_MODE": "live", "LIVE_CONFIRM": "I_ACCEPT_REAL_MONEY_RISK", "BOT_WALLET_SECRET": "x" * 88,
            "DASHBOARD_HOST": "127.0.0.1"}
    equity(ledger, MIDNIGHT + 60, 1 * SOL, mode="live")
    ledger.upsert_position(position(status="closed", closed_at=NOW - 60, pid="old"))
    opened = [position(pid="a"), position("m2", pid="b"), position("m3", pid="c")]
    (tmp_data_dir / "KILL").write_text("stop")

    def reason(**overrides: Any) -> str:
        return make_risk(**{**live, **overrides}).can_open(MINT, opened, int(0.45 * SOL), wallet_usd=500.0)[1]

    assert reason().startswith("[kill]")
    (tmp_data_dir / "KILL").unlink()
    ledger.set_kv("risk.halted", {"halted": True, "reason": "earlier drawdown", "ts": NOW})
    assert reason().startswith("[halted] earlier drawdown")
    ledger.set_kv("risk.halted", {"halted": False})
    assert reason().startswith("[drawdown]")
    ledger.set_kv("risk.halted", {"halted": False})
    assert reason(MAX_DRAWDOWN_HALT_PCT=0.9).startswith("[daily_loss]")
    assert reason(MAX_DRAWDOWN_HALT_PCT=0.9, DAILY_LOSS_LIMIT_PCT=0.9).startswith("[max_positions]")
    opened.pop()
    assert reason(MAX_DRAWDOWN_HALT_PCT=0.9, DAILY_LOSS_LIMIT_PCT=0.9).startswith("[already_open]")
    opened.pop(0)
    assert reason(MAX_DRAWDOWN_HALT_PCT=0.9, DAILY_LOSS_LIMIT_PCT=0.9).startswith("[cooldown]")
    fake_clock.advance(31 * 60)
    assert reason(MAX_DRAWDOWN_HALT_PCT=0.9, DAILY_LOSS_LIMIT_PCT=0.9).startswith("[wallet_cap]")


def test_only_equity_of_the_current_mode_counts(make_risk, ledger) -> None:
    """A paper history on the same ledger must not set the live peak or day start."""
    equity(ledger, MIDNIGHT + 60, 10 * SOL, mode="paper")
    equity(ledger, NOW - 60, 1 * SOL, mode="live")
    live = make_risk(TRADING_MODE="live", LIVE_CONFIRM="I_ACCEPT_REAL_MONEY_RISK", BOT_WALLET_SECRET="x" * 88,
                     DASHBOARD_HOST="127.0.0.1")
    assert live.peak_equity() == 1 * SOL
    assert live.day_start_equity() == 1 * SOL
    assert live.can_open(MINT, [], 1 * SOL, wallet_usd=50.0) == (True, "ok")
    assert make_risk().peak_equity() == 10 * SOL
