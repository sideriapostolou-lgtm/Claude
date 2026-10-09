"""RiskManager: sizing clamps and reserve, every can_open rule in its documented order, and the gap-risk
budgets (G23 L_MAX arithmetic, G38 daily budget, drawdown cushion and total-at-risk cap)."""

from __future__ import annotations

import math
import random
from typing import Any

import pytest

from nightcrawler.models import LAMPORTS_PER_SOL, OPENING_RENT_RESERVE_LAMPORTS, EquityPoint, Position
from nightcrawler.risk import (
    KILL_WORDS,
    L_MAX,
    RiskManager,
    position_at_risk_lamports,
    risk_room,
    size_position_usd,
)
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


def held(mint: str = MINT, pid: str = "p", cost: int = SOL // 10, tokens: int = 1_000_000_000,
         price: float | None = None) -> Position:
    """An open position that still holds ``tokens`` (6 decimals) bought for ``cost`` lamports, marked at ``price``."""
    return Position(id=pid, mint=mint, symbol="X", pool=None, opened_at=NOW - 3600, token_decimals=6,
                    token_amount=tokens, initial_token_amount=tokens, cost_lamports=cost, last_price_usd=price,
                    last_marked_at=NOW - 10 if price is not None else None)


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
    overhead = 20_000_000 + 300_000 + OPENING_RENT_RESERVE_LAMPORTS  # Ultra's Token-2022 rent, not the 165-byte model
    assert risk.size_position(1 * SOL, 100.0, available_lamports=100_000_000) == 100_000_000 - overhead
    assert risk.size_position(1 * SOL, 100.0, available_lamports=70_000_000) == 0  # $4.77 left < $5
    assert risk.size_position(1 * SOL, 100.0, available_lamports=10_000_000) == 0  # below the reserve


def test_size_position_keeps_the_brokers_actual_network_fee(risk) -> None:
    """Paper's fee can be above the NETWORK_FEE_SOL floor (Helius priority fees): a max-size buy
    must still leave room for it, or the broker refuses the buy as InsufficientBalance."""
    fee = 2_000_000
    overhead = 20_000_000 + fee + OPENING_RENT_RESERVE_LAMPORTS
    assert risk.size_position(1 * SOL, 100.0, available_lamports=100_000_000,
                              network_fee_lamports=fee) == 100_000_000 - overhead
    floor = 20_000_000 + 300_000 + OPENING_RENT_RESERVE_LAMPORTS  # never below NETWORK_FEE_SOL
    assert risk.size_position(1 * SOL, 100.0, available_lamports=100_000_000,
                              network_fee_lamports=1) == 100_000_000 - floor


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
    risk = make_risk(DAILY_LOSS_LIMIT_PCT=0.99, DAILY_RISK_BUDGET_PCT=0.99)  # isolate the drawdown rule
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
    risk = make_risk(DAILY_LOSS_LIMIT_PCT=0.99, DAILY_RISK_BUDGET_PCT=0.99)
    equity(ledger, NOW - 60, 2 * SOL)
    assert risk.can_open(MINT, [], 1 * SOL) == (True, "ok")  # exactly -50 % is not below the limit
    assert risk.can_open(MINT, [], 1 * SOL - 1)[1].startswith("[drawdown]")


def test_reset_clears_the_halt_and_restarts_the_peak(make_risk, ledger, fake_clock) -> None:
    risk = make_risk(DAILY_LOSS_LIMIT_PCT=0.99, DAILY_RISK_BUDGET_PCT=0.99)
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


def test_daily_loss_uses_the_first_snapshot_of_the_utc_day(make_risk, ledger) -> None:
    risk = make_risk(DAILY_RISK_BUDGET_PCT=0.99)  # isolate the daily loss rule
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
    # three open tickets of 0.1 SOL: 0.285 SOL can go in rugs (L_MAX 0.95 each)
    opened = [held(pid="a"), held("m2", pid="b"), held("m3", pid="c")]
    (tmp_data_dir / "KILL").write_text("stop")

    def reason(**overrides: Any) -> str:
        return make_risk(**{**live, **overrides}).can_open(MINT, opened, int(0.45 * SOL), wallet_usd=500.0)[1]

    loose = {"MAX_DRAWDOWN_HALT_PCT": 0.9, "DAILY_LOSS_LIMIT_PCT": 0.9, "DAILY_RISK_BUDGET_PCT": 0.9,
             "MAX_AT_RISK_PCT": 0.9}
    assert reason().startswith("[kill]")
    (tmp_data_dir / "KILL").unlink()
    ledger.set_kv("risk.halted", {"halted": True, "reason": "earlier drawdown", "ts": NOW})
    assert reason().startswith("[halted] earlier drawdown")
    ledger.set_kv("risk.halted", {"halted": False})
    assert reason().startswith("[drawdown]")
    ledger.set_kv("risk.halted", {"halted": False})
    assert reason(MAX_DRAWDOWN_HALT_PCT=0.9).startswith("[daily_loss]")  # 55 % down today
    worst = reason(MAX_DRAWDOWN_HALT_PCT=0.9, DAILY_LOSS_LIMIT_PCT=0.6)  # 55 % + 28.5 % in open rugs
    assert worst.startswith("[daily_loss]") and "worst case" in worst
    assert reason(MAX_DRAWDOWN_HALT_PCT=0.9, DAILY_LOSS_LIMIT_PCT=0.9).startswith("[risk_budget]")
    assert reason(**{**loose, "MAX_DRAWDOWN_HALT_PCT": 0.6}).startswith("[cushion]")
    assert reason(**{**loose, "MAX_AT_RISK_PCT": 0.25}).startswith("[at_risk]")
    assert reason(**loose).startswith("[max_positions]")
    opened.pop()
    assert reason(**loose).startswith("[already_open]")
    opened.pop(0)
    assert reason(**loose).startswith("[cooldown]")
    fake_clock.advance(31 * 60)
    assert reason(**loose).startswith("[wallet_cap]")


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


# --------------------------------------------------------------------------- gap risk: L_MAX in all arithmetic (G23)


def test_l_max_is_a_code_constant_out_of_reach_of_settings_and_learning(settings) -> None:
    """A rug is one sell that takes 84-97 % (G23): every risk sum uses 0.95 of a ticket, never the stop."""
    from nightcrawler.learn.variants import SpecRejected, make_spec

    assert L_MAX == 0.95
    assert not any("l_max" in name for name in settings.public_dict())
    for key in ("daily_risk_budget_pct", "max_at_risk_pct"):  # risk limits are never learnable
        with pytest.raises(SpecRejected):
            make_spec("dip_rebound", {key: 0.5}, settings.strategy_params())


def test_the_budget_settings_are_fractions_with_safe_defaults(make_settings) -> None:
    from nightcrawler.config import ConfigError

    s = make_settings()
    assert (s.daily_risk_budget_pct, s.max_at_risk_pct) == (0.15, 0.25)
    for name in ("DAILY_RISK_BUDGET_PCT", "MAX_AT_RISK_PCT"):
        for bad in ("15", "0", "-0.1"):  # 15 means 1500 %: refused with the FRACTION hint
            with pytest.raises(ConfigError) as err:
                make_settings(**{name: bad})
            assert name in str(err.value) and "FRACTION" in str(err.value)
        assert getattr(make_settings(**{name: "1"}), name.lower()) == 1.0


def test_a_position_risks_l_max_of_its_ticket_or_of_its_mark_whichever_is_larger() -> None:
    p = held(cost=SOL // 10, tokens=1_000_000_000)  # 1,000 whole tokens for 0.1 SOL
    assert position_at_risk_lamports(p) == math.ceil(0.95 * SOL / 10)
    assert position_at_risk_lamports(p, 100.0) == math.ceil(0.95 * SOL / 10)  # no mark: the ticket
    p.last_price_usd = 0.03  # 1,000 x $0.03 = $30 = 0.3 SOL: a winner has more to lose
    assert position_at_risk_lamports(p, 100.0) == math.ceil(0.95 * 0.3 * SOL)
    p.last_price_usd = 0.001  # marked far below its cost: the ticket still counts (never less than spec)
    assert position_at_risk_lamports(p, 100.0) == math.ceil(0.95 * SOL / 10)
    p.token_amount = 400_000_000  # after selling 60 %: the rest of the ticket
    assert position_at_risk_lamports(p) == math.ceil(0.95 * 0.4 * SOL / 10)
    p.status = "closed"
    assert position_at_risk_lamports(p) == 0


def test_risk_room_arithmetic() -> None:
    room = risk_room(equity=0.9 * SOL, day_start=1.0 * SOL, peak=1.2 * SOL, at_risk=0.1 * SOL,
                     daily_loss_limit_pct=0.20, daily_risk_budget_pct=0.15, max_drawdown_pct=0.50,
                     max_at_risk_pct=0.25)
    assert room.daily_loss == pytest.approx(0.20 * SOL - 0.1 * SOL - 0.1 * SOL)
    assert room.daily_budget == pytest.approx(0.15 * SOL - 0.1 * SOL - 0.1 * SOL)
    assert room.cushion == pytest.approx(0.9 * SOL - 0.6 * SOL - 0.1 * SOL)
    assert room.total == pytest.approx(0.25 * 0.9 * SOL - 0.1 * SOL)
    assert room.binding == "daily_budget" and room.max_ticket() == 0
    gain = risk_room(equity=1.3 * SOL, day_start=1.0 * SOL, peak=1.3 * SOL, at_risk=0.0,
                     daily_loss_limit_pct=0.20, daily_risk_budget_pct=0.15, max_drawdown_pct=0.50,
                     max_at_risk_pct=0.25)
    assert gain.daily_budget == pytest.approx(0.45 * SOL)  # today's gain is budget too ...
    assert gain.binding == "total" and gain.max_ticket() == int(0.25 * 1.3 * SOL / 0.95)  # ... up to the cap


def test_a_ticket_at_max_ticket_keeps_every_worst_case_inside_every_limit() -> None:
    rng = random.Random(7)
    for _ in range(2000):
        start, peak = rng.uniform(0.2, 3) * SOL, rng.uniform(0.2, 4) * SOL
        equity_now = rng.uniform(0.05, 1.5) * start
        peak = max(peak, equity_now)
        at_risk = rng.uniform(0, 0.4) * equity_now
        pcts = {"daily_loss_limit_pct": rng.uniform(0.05, 0.5), "daily_risk_budget_pct": rng.uniform(0.05, 0.5),
                "max_drawdown_pct": rng.uniform(0.1, 0.9), "max_at_risk_pct": rng.uniform(0.05, 0.9)}
        room = risk_room(equity=equity_now, day_start=start, peak=peak, at_risk=at_risk, **pcts)
        ticket = room.max_ticket()
        assert ticket is not None and ticket >= 0
        if ticket == 0:
            continue
        risk, lost = at_risk + L_MAX * ticket, start - equity_now
        assert lost + risk <= pcts["daily_risk_budget_pct"] * start + 1
        assert lost + risk <= pcts["daily_loss_limit_pct"] * start + 1
        assert equity_now - risk >= (1 - pcts["max_drawdown_pct"]) * peak - 1
        assert risk <= pcts["max_at_risk_pct"] * equity_now + 1


# --------------------------------------------------------------------------- budgets in sizing and the gate (G23, G38)


def test_the_first_ticket_is_capped_by_the_daily_risk_budget(risk, make_risk) -> None:
    """20 % of $100 risks $19 in a rug: more than the 15 % daily budget, so the ticket is $15.79 (G38)."""
    assert risk.size_position(1 * SOL, 100.0, open_positions=[]) == int(0.15 * SOL / 0.95)
    assert risk.size_position(1 * SOL, 100.0) == 200_000_000  # callers that pass no positions: unchanged
    # without the budget the daily loss limit binds: 20 % x 0.95 = 19 % <= 20 %, the full ticket fits
    assert make_risk(DAILY_RISK_BUDGET_PCT=0.99).size_position(1 * SOL, 100.0, open_positions=[]) == 200_000_000


def test_open_tickets_and_todays_loss_shrink_the_next_ticket(risk, ledger) -> None:
    equity(ledger, MIDNIGHT + 60, 1 * SOL)  # today's start
    one = held(cost=SOL // 20)  # 0.05 SOL open: 0.0475 SOL at risk
    # down 5 % today + 4.75 % at risk: 5.25 % of the budget left
    assert risk.size_position(int(0.95 * SOL), 100.0, open_positions=[one]) == int(
        (0.15 * SOL - 0.05 * SOL - math.ceil(0.0475 * SOL)) / 0.95)
    # less than a $5 ticket's worst case left: no ticket at all (never rounded UP to the minimum)
    assert risk.size_position(int(0.89 * SOL), 100.0, open_positions=[one]) == 0


def test_daily_loss_counts_open_tickets_at_l_max(make_risk, ledger) -> None:
    """G23: realized + marked + open tickets x L_MAX + the new ticket x L_MAX, before an entry."""
    risk = make_risk(DAILY_RISK_BUDGET_PCT=0.99)  # isolate the daily loss rule
    equity(ledger, MIDNIGHT + 60, 1 * SOL)
    one = held("m1", cost=SOL // 10)
    assert risk.can_open(MINT, [], int(0.9 * SOL), sol_usd=100.0) == (True, "ok")
    ok, reason = risk.can_open(MINT, [one], int(0.9 * SOL), sol_usd=100.0)  # 10 % + 9.5 % + 4.75 % > 20 %
    assert not ok and reason.startswith("[daily_loss]") and "worst case" in reason
    assert risk.can_open(MINT, [one], int(0.95 * SOL), sol_usd=100.0) == (True, "ok")  # 5 % + 9.5 % + 4.75 %


def test_the_daily_risk_budget_refuses_when_not_even_a_minimum_ticket_fits(risk, ledger) -> None:
    equity(ledger, MIDNIGHT + 60, 1 * SOL)
    assert risk.can_open(MINT, [], int(0.9 * SOL), sol_usd=100.0) == (True, "ok")  # 10 % + 4.75 % <= 15 %
    ok, reason = risk.can_open(MINT, [], int(0.89 * SOL), sol_usd=100.0)  # 11 % + 4.75 % > 15 %
    assert not ok and reason.startswith("[risk_budget]") and "DAILY_RISK_BUDGET_PCT 15%" in reason
    ok, reason = risk.can_open(MINT, [held("m1", cost=SOL // 10)], 1 * SOL, sol_usd=100.0)  # 9.5 % + 4.75 %
    assert ok, reason
    ok, reason = risk.can_open(MINT, [held("m1", pid="a", cost=SOL // 10), held("m2", pid="b", cost=SOL // 50)],
                               1 * SOL, sol_usd=100.0)  # 11.4 % + 4.75 % > 15 %
    assert not ok and reason.startswith("[risk_budget]")


def test_the_cushion_closes_the_50_percent_cliffs_blind_spot(make_risk, ledger) -> None:
    """Old rules at 49 % drawdown: three 20 % tickets that rug end the account 78 % down. Now the worst case of
    every open ticket must fit above the floor (1 - MAX_DRAWDOWN_HALT_PCT) x peak (G38)."""
    risk = make_risk(DAILY_LOSS_LIMIT_PCT=0.99, DAILY_RISK_BUDGET_PCT=0.99)  # isolate the cushion
    equity(ledger, NOW - 7200, 2 * SOL)
    equity(ledger, NOW - 60, int(1.02 * SOL))
    legacy_worst = 1.02 - 3 * 0.95 * min(0.20 * 1.02, 0.25)
    assert 1 - legacy_worst / 2 == pytest.approx(0.78, abs=0.01)
    ok, reason = risk.can_open(MINT, [], int(1.02 * SOL), sol_usd=100.0)  # 0.02 SOL cushion < a $5 rug
    assert not ok and reason.startswith("[cushion]") and not risk.is_halted()[0]  # refused, not halted
    assert risk.size_position(int(1.02 * SOL), 100.0, open_positions=[]) == 0
    assert risk.can_open(MINT, [], int(1.2 * SOL), sol_usd=100.0) == (True, "ok")
    cap = risk.size_position(int(1.2 * SOL), 100.0, open_positions=[])
    assert cap == int(0.2 * SOL / 0.95) and 1.2 * SOL - 0.95 * cap >= 1.0 * SOL - 1


def test_the_total_at_risk_cap_counts_every_open_ticket(make_risk, ledger) -> None:
    risk = make_risk(MAX_OPEN_POSITIONS=10)
    equity(ledger, MIDNIGHT + 60, 1 * SOL)
    equity(ledger, NOW - 60, 2 * SOL)  # +100 % today: the daily budget is wide open
    tickets = [held(f"m{i}", pid=f"p{i}", cost=SOL // 10) for i in range(5)]  # 0.475 SOL at risk
    ok, reason = risk.can_open(MINT, tickets, 2 * SOL, sol_usd=100.0)  # 23.75 % + 2.4 % > 25 % of equity
    assert not ok and reason.startswith("[at_risk]") and "MAX_AT_RISK_PCT 25%" in reason
    assert risk.can_open(MINT, tickets[:4], 2 * SOL, sol_usd=100.0) == (True, "ok")


def test_without_a_sol_price_the_budgets_still_count_open_tickets(risk, ledger) -> None:
    equity(ledger, MIDNIGHT + 60, 1 * SOL)
    ok, reason = risk.can_open(MINT, [held("m1", cost=SOL // 5, pid="a")], 1 * SOL)  # 19 % at risk > 15 %
    assert not ok and reason.startswith("[risk_budget]")


# --------------------------------------------------------------------------- policy simulation (GROUNDED G38)

#: Zero edge, 15 % rugs: the three-outcome trade model of the risk research (+26 % / -25 % / -90 %).
_P_RUG = 0.15
_P_TP = (0.0 + 0.25 * (1 - _P_RUG) + 0.90 * _P_RUG) / 0.51
_OUTCOMES = ((0.26, _P_TP), (-0.25, 1 - _P_TP - _P_RUG), (-0.90, _P_RUG))
_FIXED_COST = 0.044  # $ per round trip (network fees, rent reclaimed)


def _simulate(budgets: bool, sims: int = 500, days: int = 30, per_day: int = 6, seed: int = 11) -> dict[str, float]:
    """The risk research's ``policy_mc``: $100, up to 3 positions opened from one equity snapshot and resolved
    together (the daily check cannot react inside a slot). ``budgets=False`` is the old arithmetic (20 %, cap
    $25, day -20 %, halt -50 %); ``budgets=True`` also sizes every ticket with :func:`risk_room` at the
    default limits."""
    rng = random.Random(seed)
    values, weights = zip(*_OUTCOMES, strict=True)
    worst_days: list[float] = []
    deep = 0
    for _ in range(sims):
        eq = peak = 100.0
        low_vs_peak, worst, halted = 1.0, 0.0, False
        for _day in range(days):
            day0, left = eq, per_day
            while left > 0 and not halted:
                if eq < peak * 0.5:
                    halted = True
                    break
                if eq < day0 * 0.8:
                    break
                tickets: list[float] = []
                for _slot in range(min(3, left)):
                    ticket = min(eq * 0.20, 25.0)
                    if budgets:
                        room = risk_room(equity=eq, day_start=day0, peak=peak,
                                         at_risk=sum(L_MAX * t for t in tickets), daily_loss_limit_pct=0.20,
                                         daily_risk_budget_pct=0.15, max_drawdown_pct=0.50, max_at_risk_pct=0.25)
                        ticket = min(ticket, room.max_ticket() or 0)
                    if ticket < 5.0 or sum(tickets) + ticket > eq:
                        break
                    tickets.append(ticket)
                if not tickets:
                    break
                returns = rng.choices(values, weights, k=len(tickets))
                eq += sum(t * (r + _FIXED_COST / 20 - _FIXED_COST / t) for t, r in zip(tickets, returns, strict=True))
                left -= len(tickets)
                peak = max(peak, eq)
                low_vs_peak = min(low_vs_peak, eq / peak)
            worst = max(worst, 1 - eq / day0)
        worst_days.append(worst)
        deep += low_vs_peak < 0.45
    worst_days.sort()
    return {"worst_day_p90": worst_days[int(0.9 * sims)], "worst_day_max": worst_days[-1],
            "deeper_than_55": deep / sims}


def test_policy_simulation_reproduces_the_grounded_numbers_and_the_budgets_bound_them() -> None:
    """GROUNDED G38 (policy_mc): under the old rules the 90th-percentile worst day is 41-43 % against a nominal
    20 %, and the 50 % cliff can end far below its floor. With the budgets every day stays within 15 % of its
    start and the account never falls through (1 - D) x peak."""
    legacy, budgeted = _simulate(budgets=False), _simulate(budgets=True)
    assert 0.36 <= legacy["worst_day_p90"] <= 0.48, legacy
    assert legacy["deeper_than_55"] > 0.05, legacy
    assert budgeted["worst_day_max"] <= 0.15 + 1e-9, budgeted
    assert budgeted["deeper_than_55"] == 0.0, budgeted
