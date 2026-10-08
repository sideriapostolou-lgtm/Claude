"""Auditor: per-trade P&L, daily summary, balance drift, book consistency, chain status."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fakes import FakeClock

from nightcrawler.audit import (
    SOL_DRIFT_TOLERANCE_LAMPORTS,
    Auditor,
    daily_summaries,
    trade_pnl,
)
from nightcrawler.ledger import Ledger
from nightcrawler.models import TOKEN_ACCOUNT_RENT_LAMPORTS as RENT
from nightcrawler.models import Balances, Fill, Position

NOW = 1_791_475_200.0  # 2026-10-08T16:00:00Z
DAY = 86_400
FEE = 300_000
START = 500_000_000
HIGGS = "HiGGSmintAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
HOOKI = "HooKimintBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"


def fill(fill_id: str, side: str, mint: str, sol: int, tokens: int, *, ts: float, rent: int = 0,
         position_id: str | None = None, mode: str = "paper", sol_usd: float = 200.0, impact: float = 1.0) -> Fill:
    return Fill(id=fill_id, mode=mode, side=side, mint=mint, sol_lamports=sol, token_amount=tokens, token_decimals=6,
                price_usd=0.004, sol_usd=sol_usd, fees_lamports=FEE, platform_fee_bps=10, price_impact_pct=impact,
                signature=None, request_id=f"req_{fill_id}", ts=ts, position_id=position_id, rent_lamports=rent)


def winner_fills(mode: str = "paper") -> list[Fill]:
    """HIGGS: buy 0.1 SOL, sell half for 0.07, rest for 0.04 -> +0.0091 SOL after 3 network fees."""
    return [fill("f1", "buy", HIGGS, 100_000_000, 5_000_000, ts=NOW, rent=RENT, mode=mode),  # opening buy: no pos id
            fill("f2", "sell", HIGGS, 70_000_000, 2_500_000, ts=NOW + 600, position_id="p1", mode=mode,
                 sol_usd=210.0),
            fill("f3", "sell", HIGGS, 40_000_000, 2_500_000, ts=NOW + 3600, rent=-RENT, position_id="p1", mode=mode,
                 sol_usd=210.0)]


def winner_position() -> Position:
    return Position(id="p1", mint=HIGGS, symbol="HIGGS", pool="pool1", opened_at=NOW, token_decimals=6,
                    entry_fill_ids=["f1"], exit_fill_ids=["f2", "f3"], token_amount=0,
                    initial_token_amount=5_000_000, status="closed", exit_reason="trailing_stop",
                    closed_at=NOW + 3600)


def open_fills() -> list[Fill]:
    """HOOKI: buy 0.05 SOL for 1M tokens, take profit on 400k for 0.03 SOL; 600k still held."""
    return [fill("g1", "buy", HOOKI, 50_000_000, 1_000_000, ts=NOW + 100, rent=RENT, position_id="p2", impact=2.0),
            fill("g2", "sell", HOOKI, 30_000_000, 400_000, ts=NOW + 700, position_id="p2", impact=3.0)]


def open_position(token_amount: int = 600_000) -> Position:
    return Position(id="p2", mint=HOOKI, symbol="HOOKI", pool="pool2", opened_at=NOW + 100, token_decimals=6,
                    entry_fill_ids=["g1"], exit_fill_ids=["g2"], token_amount=token_amount, partial_taken=True)


EXPECTED_SOL = START + 9_100_000 - 50_000_000 - FEE - RENT + 30_000_000 - FEE


class FakeBroker:
    def __init__(self, mode: str, sol: int, tokens: dict[str, int] | None = None, fail: bool = False) -> None:
        self.mode = mode
        self._balances = Balances(sol_lamports=sol, tokens=dict(tokens or {}))
        self.fail = fail

    def balances(self) -> Balances:
        if self.fail:
            raise ConnectionError("holdings endpoint down")
        return self._balances


@pytest.fixture
def ledger(tmp_path: Path, fake_clock: FakeClock) -> Ledger:
    with Ledger(tmp_path / "nc.db", clock=fake_clock) as led:
        yield led


def book(ledger: Ledger, fills: list[Fill], positions: list[Position], start: int | None = START,
         mode: str = "paper") -> None:
    if start is not None:
        ledger.set_kv(f"{mode}.start_lamports", start)
    for f in fills:
        ledger.record_fill(f)
    for p in positions:
        ledger.upsert_position(p)


@pytest.fixture
def paper_book(ledger: Ledger) -> Ledger:
    book(ledger, winner_fills() + open_fills(), [winner_position(), open_position()])
    return ledger


# --------------------------------------------------------------------------- pure P&L


def test_trade_pnl_of_a_closed_winner() -> None:
    t = trade_pnl(winner_position(), winner_fills() + open_fills())
    assert (t.cost_lamports, t.proceeds_lamports, t.fees_lamports, t.rent_lamports) == (
        100_000_000, 110_000_000, 3 * FEE, 0)
    assert t.realized_lamports == 9_100_000
    assert t.realized_pct == pytest.approx(9.1)
    assert t.avg_price_impact_pct == pytest.approx(1.0)
    assert (t.fills, t.fill_ids, t.symbol, t.status, t.exit_reason) == (
        3, ["f1", "f2", "f3"], "HIGGS", "closed", "trailing_stop")


def test_trade_pnl_of_an_open_position_counts_only_the_sold_part() -> None:
    t = trade_pnl(open_position(), open_fills())
    # basis of the 40% sold = 0.02 SOL; both network fees are sunk; locked rent is a refundable deposit
    assert t.realized_lamports == 30_000_000 - 20_000_000 - 2 * FEE
    assert t.realized_pct == pytest.approx(9_400_000 / 20_000_000 * 100)
    assert t.rent_lamports == RENT and t.status == "open" and t.closed_at is None
    assert t.avg_price_impact_pct == pytest.approx(2.5)


def test_trade_pnl_without_sells_or_fills() -> None:
    fresh = trade_pnl(open_position(1_000_000), open_fills()[:1])
    assert fresh.realized_lamports == -FEE and fresh.realized_pct is None
    empty = trade_pnl(open_position(), [])
    assert (empty.fills, empty.realized_lamports, empty.avg_price_impact_pct) == (0, 0, None)


def test_daily_summaries_group_closed_trades_by_close_day() -> None:
    loser_fills = [fill("h1", "buy", HOOKI, 50_000_000, 1_000_000, ts=NOW + DAY, rent=RENT, position_id="p3"),
                   fill("h2", "sell", HOOKI, 40_000_000, 1_000_000, ts=NOW + DAY + 60, rent=-RENT, position_id="p3",
                        sol_usd=0.0)]
    loser = Position(id="p3", mint=HOOKI, symbol="HOOKI", pool=None, opened_at=NOW + DAY, token_decimals=6,
                     status="closed", closed_at=NOW + DAY + 60, exit_reason="stop_loss")
    fills = winner_fills() + open_fills() + loser_fills
    trades = [trade_pnl(p, fills) for p in (winner_position(), open_position(), loser)]
    day1, day2 = daily_summaries(trades, fills)
    assert (day1.day, day1.trades_closed, day1.wins, day1.losses) == ("2026-10-08", 1, 1, 0)
    assert day1.realized_lamports == 9_100_000 and day1.fees_lamports == 3 * FEE
    usd = (-(100_000_000 + FEE + RENT) * 200 + (70_000_000 - FEE) * 210 + (40_000_000 - FEE + RENT) * 210) / 1e9
    assert day1.realized_usd == pytest.approx(usd)
    assert (day2.day, day2.losses, day2.realized_lamports) == ("2026-10-09", 1, -10_000_000 - 2 * FEE)
    assert day2.realized_usd is None  # one fill had no SOL price


# --------------------------------------------------------------------------- reconcile: paper


def test_paper_books_that_match_are_ok(paper_book: Ledger, fake_clock: FakeClock) -> None:
    broker = FakeBroker("paper", EXPECTED_SOL, {HOOKI: 600_000})
    report = Auditor(paper_book, broker, fake_clock).reconcile()
    assert report.ok, report.issues
    assert report.issues == []
    assert (report.mode, report.checked_at) == ("paper", NOW)
    assert report.expected_sol_lamports == report.broker_sol_lamports == EXPECTED_SOL
    assert report.sol_drift_lamports == 0 and report.token_drift == {}
    assert (report.chain_ok, report.chain_first_bad_seq) == (True, None)
    assert [t.position_id for t in report.trades] == ["p1", "p2"]
    assert report.totals == {"trades": 1, "open_trades": 1, "wins": 1, "losses": 0, "win_rate_pct": 100.0,
                             "realized_lamports": 9_100_000, "realized_usd": pytest.approx(report.daily[0].realized_usd),
                             "open_realized_lamports": 9_400_000, "fees_lamports": 5 * FEE}


@pytest.mark.parametrize(("sol_delta", "tokens", "needle"), [
    (1, {HOOKI: 600_000}, "SOL drift"),
    (-1, {HOOKI: 600_000}, "SOL drift"),
    (0, {HOOKI: 599_999}, "token drift"),
    (0, {HOOKI: 600_000, HIGGS: 5}, "token drift"),
])
def test_any_paper_drift_is_a_bug(paper_book: Ledger, sol_delta: int, tokens: dict[str, int], needle: str) -> None:
    report = Auditor(paper_book, FakeBroker("paper", EXPECTED_SOL + sol_delta, tokens)).reconcile()
    assert not report.ok
    assert any(needle in issue for issue in report.issues)


def test_paper_reset_starts_a_new_accounting_epoch(paper_book: Ledger) -> None:
    abandoned = open_position(token_amount=0)
    abandoned.status, abandoned.closed_at = "closed", NOW + 800
    paper_book.upsert_position(abandoned)
    paper_book.append_receipt("note", {"event": "paper_reset", "start_usd": 100.0})
    paper_book.set_kv("paper.start_lamports", 400_000_000)
    paper_book.record_fill(fill("k1", "buy", HIGGS, 10_000_000, 1_000, ts=NOW + 900, rent=RENT, position_id="p9"))
    paper_book.upsert_position(Position(id="p9", mint=HIGGS, symbol="HIGGS", pool=None, opened_at=NOW + 900,
                                        token_decimals=6, token_amount=1_000))
    expected = 400_000_000 - 10_000_000 - FEE - RENT
    report = Auditor(paper_book, FakeBroker("paper", expected, {HIGGS: 1_000})).reconcile()
    assert report.ok, report.issues
    assert report.expected_sol_lamports == expected


def test_fills_of_the_other_mode_are_ignored(paper_book: Ledger) -> None:
    paper_book.record_fill(fill("live1", "buy", HIGGS, 10_000_000, 1_000, ts=NOW + 50, position_id="p1", mode="live"))
    report = Auditor(paper_book, FakeBroker("paper", EXPECTED_SOL, {HOOKI: 600_000})).reconcile()
    assert report.expected_sol_lamports == EXPECTED_SOL and report.token_drift == {}


# --------------------------------------------------------------------------- reconcile: live


@pytest.fixture
def live_book(ledger: Ledger) -> Ledger:
    book(ledger, winner_fills("live"), [winner_position()], mode="live")
    return ledger


LIVE_EXPECTED = START + 9_100_000


@pytest.mark.parametrize(("sol_delta", "ok", "issue"), [
    (0, True, None),
    (SOL_DRIFT_TOLERANCE_LAMPORTS, True, None),
    (-SOL_DRIFT_TOLERANCE_LAMPORTS, True, None),
    (50_000_000, True, "more than the books"),
    (-SOL_DRIFT_TOLERANCE_LAMPORTS - 1, False, "LESS SOL"),
])
def test_live_sol_drift_only_fails_when_money_is_missing(live_book: Ledger, sol_delta: int, ok: bool,
                                                         issue: str | None) -> None:
    report = Auditor(live_book, FakeBroker("live", LIVE_EXPECTED + sol_delta)).reconcile()
    assert report.ok is ok
    assert report.sol_drift_lamports == sol_delta
    assert (issue is None and report.issues == []) or any(issue in i for i in report.issues)


def test_live_token_rules(live_book: Ledger) -> None:
    rounding = Auditor(live_book, FakeBroker("live", LIVE_EXPECTED, {HIGGS: 1})).reconcile()
    assert rounding.ok and rounding.token_drift == {HIGGS: {"expected": 0, "actual": 1, "drift": 1}}
    missing = Auditor(live_book, FakeBroker("live", LIVE_EXPECTED, {HIGGS: 2})).reconcile()
    assert not missing.ok
    airdrop = Auditor(live_book, FakeBroker("live", LIVE_EXPECTED, {"SpamMint111": 10**9})).reconcile()
    assert airdrop.ok and any("untracked token SpamMint111" in i for i in airdrop.issues)


def test_live_without_a_recorded_start_skips_sol(ledger: Ledger) -> None:
    book(ledger, winner_fills("live"), [winner_position()], start=None, mode="live")
    report = Auditor(ledger, FakeBroker("live", 123)).reconcile()
    assert report.ok and report.expected_sol_lamports is None and report.sol_drift_lamports is None
    assert any("start balance unknown" in i for i in report.issues)


# --------------------------------------------------------------------------- books + chain + offline


def test_offline_report_without_broker(paper_book: Ledger) -> None:
    report = Auditor(paper_book, None, mode="paper").reconcile(verify_chain=False)
    assert report.ok and report.broker_sol_lamports is None and report.chain_ok is None
    assert report.expected_sol_lamports == EXPECTED_SOL
    assert any("no broker" in i for i in report.issues)
    assert report.totals["trades"] == 1


def test_broker_failure_is_reported_not_raised(paper_book: Ledger) -> None:
    report = Auditor(paper_book, FakeBroker("paper", 0, fail=True)).reconcile()
    assert report.ok and any("ConnectionError" in i for i in report.issues)


def test_orphan_fill_and_position_mismatch_are_problems(paper_book: Ledger) -> None:
    paper_book.record_fill(fill("orphan", "buy", HIGGS, 1_000_000, 10, ts=NOW + 5))
    paper_book.upsert_position(open_position(token_amount=999))
    report = Auditor(paper_book, None).reconcile()
    assert not report.ok
    assert any("not linked to any position" in i and "orphan" in i for i in report.issues)
    assert any("position p2" in i and "net 600000" in i for i in report.issues)


def test_broken_chain_fails_the_audit(paper_book: Ledger, tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "nc.db")
    with conn:
        conn.execute("UPDATE receipts SET payload = replace(payload, '70000000', '90000000') WHERE seq = 2")
    conn.close()
    report = Auditor(paper_book, FakeBroker("paper", EXPECTED_SOL, {HOOKI: 600_000})).reconcile()
    assert not report.ok
    assert (report.chain_ok, report.chain_first_bad_seq) == (False, 2)
    assert any("receipt chain broken at seq 2" in i for i in report.issues)


def test_format_text_is_a_readable_summary(paper_book: Ledger, fake_clock: FakeClock) -> None:
    text = Auditor.format_text(Auditor(paper_book, FakeBroker("paper", EXPECTED_SOL + 1, {HOOKI: 600_000}),
                                       fake_clock).reconcile())
    assert text.startswith("nightcrawler audit - PAPER - 2026-10-08T16:00:00Z")
    assert "Result: PROBLEMS FOUND" in text and "Receipt chain: verified OK" in text
    assert f"books {EXPECTED_SOL / 1e9:.4f}" in text and "drift +0.0000" in text
    assert "HIGGS" in text and "trailing_stop" in text and "+0.0091" in text and "+9.1%" in text
    assert "2026-10-08" in text and "1 won / 0 lost" in text
    offline = Auditor.format_text(Auditor(paper_book, None).reconcile(verify_chain=False))
    assert "Receipt chain: not checked" in offline and "wallet n/a" in offline and "Tokens: not compared" in offline
