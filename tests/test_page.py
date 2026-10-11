"""The one page at "/" (nightcrawler.page + pagestate + readiness): data assembly and empty states, the
"ready for real money?" checklist, the learning card fallback, routes behind the token, no secrets, a
bounded JSON and no way for ledger text to become markup."""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import re
import sys
import types
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock

from nightcrawler import __version__
from nightcrawler.botwallet import KV_BOT_WALLET
from nightcrawler.config import LIVE_CONFIRM_PHRASE, Settings
from nightcrawler.dashboard import CONTENT_SECURITY_POLICY, COOKIE_NAME, DashboardServer, build_state, render_html
from nightcrawler.ledger import Ledger
from nightcrawler.models import Decision, EquityPoint, Fill, Position, SafetyReport, TokenCandidate, Verdict
from nightcrawler.page import PAGE_CSP, REFRESH_S, render_page_html
from nightcrawler.pagestate import (LEARNING_RULE, MEMBERS, STALE_BANNER_S, build_page_state, learning_card,
                                    town_ledger)
from nightcrawler.readiness import CHECK_IDS, readiness
from nightcrawler.teamroom import ENGINE_STALE_S, TeamRoom, derive_status

NOW = 1_791_475_200.0  # 2026-10-08T16:00:00Z (the fake clock's start)
MIDNIGHT = NOW - NOW % 86_400
DAY = 86_400.0
XSS = "<img src=x onerror=alert(1)>"
HIGGS = "HiGGSmintAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
MEMBER_IDS = ["crawler", "cocoon", "strategy", "radar", "judge", "broker", "risk", "receipts", "coach", "predict"]
SECRETS = {
    "ANTHROPIC_API_KEY": "sk-ant-api03-TOPSECRETanthropicKEY0123456789",
    "JUPITER_API_KEY": "jup-secret-key-5f4dcc3b5aa765d61d8327deb882cf99",
    "BOT_WALLET_SECRET": "4wBqpZM9xaSheZzJSMawUKKwhdpChKbZ5eu5ky4Vigw1t7Wv5jNzqJmsRcFVw8NhpWxnJ8u5fE3ygVJgLFrTTXpo",
    "X_BEARER_TOKEN": "x-bearer-AAAAAAAAAAAAAAAAAAAAAMLheAAAAAAA0%2BuSeid",
    "DASHBOARD_TOKEN": "dash-token-correct-horse-battery-staple",
}
RPC_KEY = "helius-rpc-key-0a1b2c3d4e5f"
TOKEN = SECRETS["DASHBOARD_TOKEN"]
WALLET = "BotWa11etPubkey1111111111111111111111111111"
PROVEN = {"champion": "dip-rebound v2", "champion_passed_locked_test": True, "paper_matches_backtest": True,
          "state": "live_ready"}  # the Coach's stage 2 passed (G39: no real money before it)
#: The example password in docs/RAILWAY.md: public, so it must never tick "dashboard locked".
PLACEHOLDER_TOKEN = "change-me-to-a-long-random-password-1234567890"
#: Words a non-developer should never have to decode on the page.
JARGON = re.compile(r"\b(?:bps|lamports?|mint|slippage|mcap|prefilter|kv|ledger)\b", re.IGNORECASE)


# --------------------------------------------------------------------------- helpers


@pytest.fixture
def ledger(tmp_path: Path, fake_clock: FakeClock) -> Iterator[Ledger]:
    with Ledger(tmp_path / "nc.db", clock=fake_clock) as led:
        yield led


@pytest.fixture(autouse=True)
def no_learning_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """The learning card and the report cards are built by other teams: by default both are ABSENT in these
    tests (tests/test_page_experience.py covers the report cards)."""
    monkeypatch.setitem(sys.modules, "nightcrawler.learn.card", None)
    monkeypatch.setitem(sys.modules, "nightcrawler.experience.state", None)


def install_card(monkeypatch: pytest.MonkeyPatch, func: Callable[..., Any]) -> None:
    """Make ``nightcrawler.learn.card.learning_card_state`` importable and be ``func``."""
    package = types.ModuleType("nightcrawler.learn")
    package.__path__ = []
    module = types.ModuleType("nightcrawler.learn.card")
    module.learning_card_state = func  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "nightcrawler.learn", package)
    monkeypatch.setitem(sys.modules, "nightcrawler.learn.card", module)


def secret_values() -> list[str]:
    return [*SECRETS.values(), RPC_KEY]


def status_kv(ts: float = NOW - 5, **extra: Any) -> dict[str, Any]:
    status = {"state": "running", "mode": "paper", "ts": ts, "kill_mode": "off", "watchlist": 2,
              "watching": [{"mint": "A1", "symbol": "AAA", "last_signal": "dip 44.0% < required 55.0%"},
                           {"mint": "B1", "symbol": "BBB", "last_signal": None}],
              "cocoon_queue": 0, "unresolved_swaps": [], "drift": {}, "entries_blocked": None,
              "counters": {"cocoon_checked": 40, "candle_fetches": 12, "entry_signals": 1},
              "crawler": {"polls": 100, "rejected": 900, "nursery": 120, "feed_errors": {}}}
    status.update(extra)
    return status


def seed(ledger: Ledger, mode: str = "paper", leak: str = "", symbol: str = "HIGGS") -> None:
    """Two days of running: equity down 5 % in SOL while SOL rose 10 %, one open trade, a won and a lost
    trade, coins found and judged, receipts and a fresh engine heartbeat."""
    ledger.append_receipt("boot", {"version": __version__, "mode": mode, "settings": {}, "pid": 1},
                          ts=NOW - 2 * DAY - 100)
    ledger.set_kv(f"{mode}.start_lamports", 1_000_000_000)
    ledger.set_kv(f"{mode}.start_sol_usd", 100.0)
    for ts, lamports, sol_usd in ((NOW - 2 * DAY, 1_000_000_000, 100.0), (MIDNIGHT + 60, 1_000_000_000, 100.0),
                                  (NOW - 3700, 990_000_000, 105.0), (NOW - 30, 950_000_000, 110.0)):
        ledger.record_equity(EquityPoint(ts=ts, equity_lamports=lamports, sol_usd=sol_usd,
                                         equity_usd=lamports / 1e9 * sol_usd, mode=mode))
    ledger.record_candidate(TokenCandidate(mint="C1mint", symbol="NEWEST" + leak, age_min=61.0, mcap_usd=210_000.0,
                                           sources=["jupiter_recent"], discovered_at=NOW - 120))
    ledger.record_safety(SafetyReport(mint="C2mint", passed=False, hard_fail_reasons=["[top10] top-10 own 45%"],
                                      checked_at=NOW - 100))
    ledger.record_decision(Decision(ts=NOW - 200, mint="C2mint", action="reject_cocoon",
                                    reason="[top10] top-10 own 45%" + leak, symbol="SECOND"))
    ledger.record_decision(Decision(ts=NOW - 100, mint="C1mint", action="watch", reason="passed (0 warnings)",
                                    symbol="NEWEST"))
    no = Verdict(decision="no", confidence=0.7, reasons=["creator selling" + leak], model="claude-opus-5-5",
                 latency_ms=800, cost_usd=0.003, source="claude")
    ledger.record_decision(Decision(ts=NOW - 800, mint="JUDGEDmint", action="reject_judge", symbol="JUDGED",
                                    reason="judge: creator selling", verdict=no))
    ledger.record_fill(Fill(id="f1", mode=mode, side="buy", mint=HIGGS, sol_lamports=100_000_000,
                            token_amount=5_000_000_000, token_decimals=6, price_usd=0.002, sol_usd=100.0,
                            fees_lamports=300_000, platform_fee_bps=10, price_impact_pct=1.5, signature=None,
                            request_id="r1", ts=NOW - 3000, expected_out_amount=5_050_505_050, symbol=symbol))
    ledger.upsert_position(Position(id="p1", mint=HIGGS, symbol=symbol, pool="pool", opened_at=NOW - 3000,
                                    token_decimals=6, entry_fill_ids=["f1"], token_amount=5_000_000_000,
                                    initial_token_amount=5_000_000_000, cost_lamports=100_000_000,
                                    fees_lamports=300_000, rent_lamports=2_039_280, entry_price_usd=0.002,
                                    peak_price_usd=0.0031, last_price_usd=0.0029, mode=mode))
    for pid, opened, closed, proceeds, reason in (("p2", NOW - DAY, NOW - DAY + 3600, 120_000_000, "trailing_stop"),
                                                  ("p3", NOW - 9000, NOW - 8000, 85_000_000, "stop_loss")):
        ledger.upsert_position(Position(id=pid, mint=f"{pid}mint", symbol=pid.upper() + leak, pool=None,
                                        opened_at=opened, token_decimals=6, cost_lamports=100_000_000,
                                        proceeds_lamports=proceeds, fees_lamports=600_000, entry_price_usd=0.01,
                                        status="closed", exit_reason=reason, closed_at=closed, mode=mode))
    ledger.set_kv("engine.heartbeat", NOW - 5)
    ledger.set_kv("engine.started_at", NOW - 7200)
    ledger.set_kv("engine.status", status_kv(note="ok" + leak))
    ledger.set_kv("engine.last_error", "watch: HttpError 429" + leak)


def members(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {m["id"]: m for m in state["team"]["members"]}


def items(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {i["id"]: i for i in state["ready"]["items"]}


class Client:
    def __init__(self, server: DashboardServer) -> None:
        self.port = server.bound_port

    def request(self, path: str, method: str = "GET", headers: dict[str, str] | None = None
                ) -> tuple[int, http.client.HTTPMessage, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, headers=headers or {})
            res = conn.getresponse()
            return res.status, res.headers, res.read()
        finally:
            conn.close()


@pytest.fixture
def serve() -> Iterator[Callable[..., Client]]:
    servers: list[DashboardServer] = []

    def _serve(settings: Settings, ledger: Ledger) -> Client:
        cache: dict[str, Any] = {}
        team = TeamRoom(settings, ledger=ledger, clock=FakeClock(NOW), environ={})
        server = DashboardServer(settings, lambda: build_state(ledger, settings, NOW, cache), host="127.0.0.1",
                                 port=0, team=team)
        server.start()
        servers.append(server)
        return Client(server)

    yield _serve
    for server in servers:
        server.stop()


def live_settings(make_settings: Callable[..., Settings], **extra: Any) -> Settings:
    return make_settings(TRADING_MODE="live", LIVE_CONFIRM=LIVE_CONFIRM_PHRASE, BOT_WALLET_SECRET="x" * 88,
                         DASHBOARD_TOKEN=TOKEN, **extra)


# --------------------------------------------------------------------------- state: sections and empty states


def test_empty_ledger_gives_every_section_with_honest_empty_states(ledger: Ledger, settings: Settings) -> None:
    state = build_page_state(ledger, settings, NOW)
    assert state["mode"] == "PAPER" and state["version"] == __version__ and state["refresh_s"] == REFRESH_S
    money = state["money"]
    assert money["label"] == "Paper money (pretend)"
    assert money["usd"] is None and money["since_start"] == {"usd": None, "pct": None}
    assert money["today"] == {"usd": None, "pct": None} and money["curve"] == [] and money["chart_ready"] is False
    assert [m["id"] for m in state["team"]["members"]] == MEMBER_IDS == [mid for mid, _, _ in MEMBERS]
    for m in state["team"]["members"]:
        assert m["status"] == ("absent" if m["id"] == "coach" else "waiting"), m["id"]
        assert m["doing"] and m["last_activity"] is None and m["events"] == []
    assert state["trades"]["open"] == [] and state["trades"]["closed"] == []
    assert state["learning"]["source"] == "missing" and state["learning"]["headline"].startswith("Not installed yet")
    assert state["learning"]["rule"] is None  # no "the Coach can turn trading off" claim without a Coach
    assert state["experience"]["source"] == "missing" and state["experience"]["members"] == {}  # no report cards
    assert state["ready"]["ready"] is False and state["ready"]["headline"] == "Not ready yet — 0 of 5 done"
    assert state["receipts"] == {"count": 0, "verified": True, "first_bad_seq": None, "head": "0" * 64,
                                 "head_short": "00000000…00000000"}
    assert [a["level"] for a in state["alerts"]] == ["warn"] and "not started" in state["alerts"][0]["text"]
    assert state["about"]["version"] == __version__ and state["about"]["uptime_s"] is None
    json.dumps(state, allow_nan=False)


def test_money_is_the_bots_own_result_measured_in_sol(ledger: Ledger, settings: Settings) -> None:
    """Lost 5 % in SOL while SOL/USD rose 10 %: the dollar value went UP, but the bot's result is a loss and
    must never show green. The SOL price effect is shown apart, as not the bot's doing."""
    seed(ledger)
    money = build_page_state(ledger, settings, NOW)["money"]
    assert money["usd"] == pytest.approx(104.5) and money["start_usd"] == pytest.approx(100.0)
    assert money["sol"] == pytest.approx(0.95) and money["sol_usd"] == 110.0
    assert money["since_start"]["usd"] == pytest.approx(-0.05 * 110)
    assert money["since_start"]["pct"] == pytest.approx(-5)
    assert money["sol_price_effect_usd"] == pytest.approx(10.0)  # 100 - 5.5 + 10 = 104.5
    assert money["today"]["usd"] == pytest.approx(-0.05 * 110) and money["today"]["pct"] == pytest.approx(-5)
    assert money["chart_ready"] is True and money["curve"][-1] == [NOW - 30, pytest.approx(104.5)]


def test_the_chart_waits_for_the_first_hour(ledger: Ledger, settings: Settings) -> None:
    for ts in (NOW - 1800, NOW - 60):
        ledger.record_equity(EquityPoint(ts=ts, equity_lamports=10**9, sol_usd=100.0, equity_usd=100.0))
    money = build_page_state(ledger, settings, NOW)["money"]
    assert len(money["curve"]) == 2 and money["chart_ready"] is False  # 29 min of data is not a chart yet
    ledger.record_equity(EquityPoint(ts=NOW - 3700, equity_lamports=10**9, sol_usd=100.0, equity_usd=100.0))
    assert build_page_state(ledger, settings, NOW)["money"]["chart_ready"] is True
    assert "The chart starts after the first hour" in render_page_html(settings)


def test_live_money_is_labelled_real(ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    assert build_page_state(ledger, live_settings(make_settings), NOW)["money"]["label"] == "Real money"


def test_team_rows_reuse_the_team_room_rules_in_plain_words(ledger: Ledger, make_settings: Callable[..., Settings]
                                                            ) -> None:
    settings = make_settings(ANTHROPIC_API_KEY="sk-ant-test-key-0123456789", JUDGE_MODE="advisory")
    seed(ledger)
    state = build_page_state(ledger, settings, NOW)
    by = members(state)
    assert [m["name"] for m in state["team"]["members"]] == [
        "Crawler", "Cocoon", "Strategy", "Radar", "Jev", "Broker", "Risk", "Receipts", "Coach", "Polymarket desk"]
    assert by["crawler"]["status"] == "working" and by["crawler"]["last_activity"] == NOW  # coin last seen now
    assert by["crawler"]["doing"] == "Found 1 new coin in the last hour; 120 too young to judge yet."
    assert by["cocoon"]["doing"].startswith("Last 24 h: threw out 1 coin, let 1 through.")
    assert by["strategy"]["doing"] == "Watching 2 coins for a 55% drop and a bounce back; closest: AAA."
    assert by["broker"]["doing"] == "1 buy and 0 sells in the last 24 h, with pretend money. Holding 1 trade."
    assert by["risk"]["status"] == "working" and "1 of 3 trade slots" in by["risk"]["doing"]
    assert by["judge"]["doing"].startswith("Last 24 h: 0 yes, 1 no.")
    assert by["coach"]["status"] == "absent" and by["coach"]["doing"].startswith("Not installed yet")
    assert sum(state["team"]["counts"].values()) == len(MEMBER_IDS) - 1  # a Coach that is not built is not counted
    for m in state["team"]["members"]:
        assert len(m["doing"]) <= 160 and not JARGON.search(m["doing"]), m
        assert len(m["events"]) <= 5 and all(not JARGON.search(e["text"]) for e in m["events"]), m["id"]
    cocoon_events = [e["text"] for e in by["cocoon"]["events"]]
    assert any("Top 10 wallets hold too much" in t and "[top10]" not in t for t in cocoon_events)
    strategy_bars = by["strategy"]["bars"]
    assert [b["label"] for b in strategy_bars] == ["AAA", "BBB"] and strategy_bars[1]["value"] is None


def test_trades_open_then_closed_with_plain_results(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    trades = build_page_state(ledger, settings, NOW)["trades"]
    raw = build_state(ledger, settings, NOW)["positions"][0]
    (pos,) = trades["open"]
    assert pos["coin"] == "HIGGS" and pos["entry_usd"] == 0.002 and pos["now_usd"] == 0.0029
    assert pos["pnl_pct"] == pytest.approx(raw["unrealized_pnl_pct"])
    assert pos["pnl_usd"] == pytest.approx(raw["unrealized_pnl_sol"] * 110.0)
    assert pos["opened_at"] == NOW - 3000 and trades["max_open"] == 3
    assert [t["coin"] for t in trades["closed"]] == ["P3", "P2"]  # newest first
    lost, won = trades["closed"]
    assert (won["result"], won["pnl_pct"]) == ("won", pytest.approx(19.4))
    assert won["why"] == "Sold after the price fell from its high"
    assert won["pnl_usd"] == pytest.approx(0.0194 * 110.0)
    assert (lost["result"], lost["pnl_pct"], lost["why"]) == ("lost", pytest.approx(-15.6), "Stop-loss: cut the loss")
    for i in range(12):
        ledger.upsert_position(Position(id=f"old{i}", mint="m", symbol="OLD", pool=None, opened_at=NOW - DAY * 3,
                                        token_decimals=6, cost_lamports=1, status="closed", closed_at=NOW - DAY * 2,
                                        mode="paper"))
    assert len(build_page_state(ledger, settings, NOW)["trades"]["closed"]) == 10
    assert "No trades yet — on most days the bot buys nothing, that's on purpose." in render_page_html(settings)


def test_alerts_come_from_real_trouble_only(ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    seed(ledger)
    assert build_page_state(ledger, settings, NOW)["alerts"] == []
    stale = build_page_state(ledger, settings, NOW - 5 + STALE_BANNER_S + 1)["alerts"]
    assert [a["level"] for a in stale] == ["bad"] and "has not checked in for 3 min" in stale[0]["text"]
    assert build_page_state(ledger, settings, NOW - 5 + STALE_BANNER_S)["alerts"] == []
    ledger.set_kv("engine.kill_mode", "sell_all")
    ledger.set_kv("risk.halted", {"halted": True, "reason": "[drawdown] -52%", "ts": NOW})
    ledger.set_kv("engine.status", status_kv(drift={"M": {"books": 1, "wallet": 0}}, unresolved_swaps=["M"]))
    texts = [(a["level"], a["text"]) for a in build_page_state(ledger, settings, NOW)["alerts"]]
    assert [level for level, _ in texts] == ["bad", "bad", "bad", "warn"]
    assert "Kill switch" in texts[0][1] and "sell" in texts[0][1]
    assert "Stopped buying" in texts[1][1] and "wallet" in texts[2][1] and "unknown" in texts[3][1]


def test_receipts_usage_and_about(ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(SOLANA_RPC_URL=f"https://mainnet.helius-rpc.com/?api-key={RPC_KEY}",
                             USAGE_HELIUS_MONTHLY_CREDITS=1000, USAGE_JUPITER_MONTHLY_CALLS=100)
    seed(ledger)
    ledger.set_kv("usage.providers", {
        "helius": {"day": "2026-10-08", "day_counts": {"calls": 4, "credits": 4}, "month": "2026-10",
                   "month_counts": {"calls": 850, "credits": 850}, "updated_at": NOW},
        "jupiter": {"day": "2026-10-08", "day_counts": {"calls": 9}, "month": "2026-10",
                    "month_counts": {"calls": 120}, "updated_at": NOW}})
    state = build_page_state(ledger, settings, NOW, deploy={"commit": "0123456789ab", "message": "x"})
    seq, head = ledger.head()
    assert state["receipts"] == {"count": seq, "verified": True, "first_bad_seq": None, "head": head,
                                 "head_short": head[:8] + "…" + head[-8:]}
    usage = {u["label"]: u for u in state["usage"]}
    assert (usage["Helius"]["pct"], usage["Helius"]["level"]) == (85.0, "warn")
    assert usage["Helius"]["text"] == "850 of 1,000 credits this month"
    assert (usage["Jupiter"]["level"], usage["GeckoTerminal"]["pct"]) == ("over", None)
    assert usage["GeckoTerminal"]["text"] == "0 calls today"
    assert any("Jupiter" in a["text"] and "over" in a["text"] for a in state["alerts"])  # over budget: top banner
    assert state["about"] == {"version": __version__, "uptime_s": pytest.approx(7200), "commit": "0123456789ab",
                              "started_at": NOW - 7200}


def test_services_say_not_measured_instead_of_zero_calls(ledger: Ledger, settings: Settings) -> None:
    """Before any call counter was saved the page cannot tell "0 calls" from "not counted": it says so."""
    usage = {u["label"]: u for u in build_page_state(ledger, settings, NOW)["usage"]}
    for label in ("Solana RPC", "Jupiter", "GeckoTerminal", "DexScreener", "RugCheck"):
        assert usage[label] == {"label": label, "pct": None, "level": None, "text": "not measured yet",
                                "measured": False}, label
    assert usage["Anthropic"]["measured"] is True  # the judge measures its own spending (kv judge.cost_usd_day)
    ledger.set_kv("usage.providers", {"jupiter": {"day": "2026-10-08", "day_counts": {"calls": 3}, "month": "2026-10",
                                                  "month_counts": {"calls": 3}, "updated_at": NOW - 30}})
    usage = {u["label"]: u for u in build_page_state(ledger, settings, NOW)["usage"]}
    assert usage["Jupiter"]["text"] == "3 calls today" and usage["GeckoTerminal"]["text"] == "0 calls today"
    assert all(u["measured"] for u in usage.values())


def test_the_page_reads_the_bot_wallet_checked_in_paper_mode(ledger: Ledger, make_settings: Callable[..., Settings]
                                                             ) -> None:
    """GOING_LIVE steps 1-3 happen in paper mode: the engine reads the bot wallet's SOL (kv bot_wallet.balance)
    and the checklist trusts a reading of the last hour only."""
    settings = make_settings(BOT_WALLET_SECRET="x" * 88)
    assert "has not read" in items(build_page_state(ledger, settings, NOW))["wallet"]["reason"]
    ledger.set_kv(KV_BOT_WALLET, {"address": WALLET, "sol_lamports": 500_000_000, "checked_at": NOW - 600})
    item = items(build_page_state(ledger, settings, NOW))["wallet"]
    assert item["done"] and "holds 0.5 SOL" in item["reason"]
    stale = items(build_page_state(ledger, settings, NOW + 3600))["wallet"]
    assert not stale["done"] and "has not been read recently" in stale["reason"]
    gone = items(build_page_state(ledger, make_settings(), NOW))["wallet"]  # the secret was removed again
    assert not gone["done"] and gone["reason"].startswith("No bot wallet yet")
    for junk in ("x", {"address": WALLET}, {"address": 5, "sol_lamports": 1, "checked_at": NOW},
                 {"address": WALLET, "sol_lamports": "lots", "checked_at": NOW},
                 {"address": WALLET, "sol_lamports": 1, "checked_at": None}):
        ledger.set_kv(KV_BOT_WALLET, junk)
        assert not items(build_page_state(ledger, settings, NOW))["wallet"]["done"], junk


def test_live_wallet_balance_is_its_sol_not_its_total_value(ledger: Ledger, make_settings: Callable[..., Settings]
                                                            ) -> None:
    """Total value includes the coins held; "funded" means SOL in the wallet (EquityPoint.sol_lamports)."""
    settings = live_settings(make_settings)
    ledger.set_kv("wallet.pubkey", WALLET)
    ledger.record_equity(EquityPoint(ts=NOW - 30, equity_lamports=925_000_000, sol_usd=100.0, equity_usd=92.5,
                                     sol_lamports=300_000_000, positions_value_lamports=625_000_000, open_positions=1,
                                     mode="live"))
    item = items(build_page_state(ledger, settings, NOW))["wallet"]
    assert item["done"] and "holds 0.3 SOL" in item["reason"] and "0.925" not in item["reason"]
    ledger.record_equity(EquityPoint(ts=NOW - 20, equity_lamports=600_000_000, sol_usd=100.0, equity_usd=60.0,
                                     sol_lamports=0, positions_value_lamports=600_000_000, open_positions=1,
                                     mode="live"))
    item = items(build_page_state(ledger, settings, NOW))["wallet"]
    assert not item["done"] and "empty" in item["reason"]  # only coins, no SOL: not funded
    assert not items(build_page_state(ledger, settings, NOW + 3600))["wallet"]["done"]  # an hour-old reading


def test_a_long_silence_reads_in_days_and_the_money_says_how_old_it_is(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)  # heartbeat NOW - 5, last money check NOW - 30
    state = build_page_state(ledger, settings, NOW - 5 + 3 * DAY)
    (silent,) = [a for a in state["alerts"] if "checked in" in a["text"]]
    assert silent["text"] == "The bot has not checked in for 3 d: it may be down."
    assert state["money"]["as_of"] == NOW - 30
    assert build_page_state(ledger, settings, NOW + 2 * 3600)["alerts"][0]["text"] == (
        "The bot has not checked in for 2 h 00 min: it may be down.")
    script = page_script(settings)
    assert "Last money check: " in script and "m.as_of" in script


def test_the_banner_and_the_team_agree_on_when_the_bot_is_silent(ledger: Ledger, settings: Settings) -> None:
    assert STALE_BANNER_S == ENGINE_STALE_S
    seed(ledger)
    quiet = build_page_state(ledger, settings, NOW - 5 + 150)  # 2.5 min: neither a banner nor blocked members
    assert quiet["alerts"] == [] and all(m["status"] != "blocked" for m in quiet["team"]["members"])
    silent = build_page_state(ledger, settings, NOW - 5 + ENGINE_STALE_S + 1)
    assert [a["level"] for a in silent["alerts"]] == ["bad"]
    assert all(m["status"] == "blocked" for m in silent["team"]["members"] if m["id"] != "coach")


# --------------------------------------------------------------------------- the town: costs vs what the desks made


def test_the_town_compares_what_the_bot_costs_with_what_the_desks_made(ledger: Ledger,
                                                                       make_settings: Callable[..., Settings]) -> None:
    """Railway's price per day (the monthly price / 30) plus the AI judge's spending, against the money card's own
    result. The run starts at the ledger's first record (the first boot), not at the engine's last restart."""
    settings = make_settings(TOWN_RAILWAY_USD_MONTH=6)  # $0.20 a day
    seed(ledger)  # first receipt 2 days and 100 s ago, engine restarted 2 h ago, the bot lost $5.50 today
    ledger.set_kv("judge.cost_usd_total", 0.30)
    ledger.set_kv("judge.cost_usd_day", {"day": "2026-10-08", "usd": 0.05})
    state = build_page_state(ledger, settings, NOW)
    town = state["town"]
    assert town["label"] == state["money"]["label"] == "Paper money (pretend)"
    assert town["cost_per_day_usd"] == pytest.approx(0.20 + 0.05)
    assert town["cost_today_usd"] == pytest.approx(0.20 * 16 / 24 + 0.05)  # 16:00 UTC: two thirds of the day
    assert town["cost_since_start_usd"] == pytest.approx(0.20 * (2 * DAY + 100) / DAY + 0.30)
    assert town["income_today_usd"] == state["money"]["today"]["usd"] == pytest.approx(-5.5)
    assert town["income_since_start_usd"] == state["money"]["since_start"]["usd"] == pytest.approx(-5.5)
    assert town["covered_today"] is False and town["covered_since_start"] is False
    assert town["line"] == ("The town costs $0.25 a day to run; the Solana desk lost $5.50 today (paper money) and "
                            "the Polymarket desk has not finished a round yet (paper money, pretend).")
    assert town["polymarket"]["real"] is None  # no real book: the desk never ran here
    assert not JARGON.search(town["line"])
    json.dumps(town, allow_nan=False)


def test_the_towns_clock_is_the_first_record_not_the_last_restart(ledger: Ledger, settings: Settings) -> None:
    ledger.set_kv("engine.started_at", NOW - 3600)  # the current process has run for an hour
    assert build_page_state(ledger, settings, NOW)["town"]["cost_since_start_usd"] == pytest.approx(5 / 30 / 24)
    ledger.append_receipt("boot", {"version": __version__, "mode": "paper"}, ts=NOW - 10 * DAY)  # the first boot
    assert build_page_state(ledger, settings, NOW)["town"]["cost_since_start_usd"] == pytest.approx(5 / 30 * 10)


@pytest.mark.parametrize(("today", "since", "covered_today", "covered_since", "made"), [
    (0.50, 3.00, True, True, "the desks made $0.50 today (paper money)"),
    (0.05, -2.00, False, False, "the desks made $0.05 today (paper money)"),
    (-0.40, 1.00, False, True, "the desks lost $0.40 today (paper money)"),
    (None, None, None, None, "what the desks made today (paper money) is not known yet: no money check so far"),
])
def test_town_from_a_synthetic_state_covered_not_covered_or_unknown(make_settings: Callable[..., Settings],
                                                                     today: float | None, since: float | None,
                                                                     covered_today: bool | None,
                                                                     covered_since: bool | None, made: str) -> None:
    settings = make_settings(TOWN_RAILWAY_USD_MONTH=3)  # $0.10 a day
    money = {"label": "Paper money (pretend)", "today": {"usd": today}, "since_start": {"usd": since}}
    town = town_ledger(settings, money, {"cost_usd_total": 0.40, "cost_usd_today": 0.02}, NOW, NOW - 4 * DAY)
    assert town["label"] == money["label"]
    assert town["cost_per_day_usd"] == pytest.approx(0.12)
    assert town["cost_today_usd"] == pytest.approx(0.10 * 16 / 24 + 0.02)
    assert town["cost_since_start_usd"] == pytest.approx(0.40 + 0.40)
    assert (town["income_today_usd"], town["income_since_start_usd"]) == (today, since)
    assert (town["covered_today"], town["covered_since_start"]) == (covered_today, covered_since)
    assert town["line"] == f"The town costs $0.12 a day to run; {made}."


def test_the_town_says_what_it_does_not_know_instead_of_making_numbers_up(ledger: Ledger, settings: Settings,
                                                                            make_settings: Callable[..., Settings]
                                                                            ) -> None:
    """An empty ledger: no money check and no record yet, so the income and the since-start cost are null and the
    line says so. A judge block without figures, or with junk, counts as nothing spent; without a figure for today
    the judge's total is spread over the days run."""
    town = build_page_state(ledger, settings, NOW)["town"]
    assert town["cost_per_day_usd"] == pytest.approx(5 / 30)
    assert town["cost_today_usd"] == pytest.approx(5 / 30 * 16 / 24)
    assert town["income_today_usd"] is None and town["covered_today"] is None
    assert town["cost_since_start_usd"] is None and town["covered_since_start"] is None
    assert town["line"] == ("The town costs $0.17 a day to run; what the Solana desk made today (paper money) is not "
                            "known yet: no money check so far; the Polymarket desk has not finished a round yet (paper "
                            "money, pretend). How long the town has been running is not known yet.")
    money = {"today": {"usd": 1.0}, "since_start": {"usd": 1.0}}
    bare = town_ledger(settings, money, None, NOW, NOW - 2 * DAY)
    assert (bare["cost_per_day_usd"], bare["cost_since_start_usd"]) == (pytest.approx(5 / 30), pytest.approx(10 / 30))
    spread = town_ledger(settings, money, {"cost_usd_total": 0.90}, NOW, NOW - 3 * DAY)  # no figure for today
    assert spread["cost_per_day_usd"] == pytest.approx(5 / 30 + 0.30)  # $0.90 over the 3 days run
    assert spread["cost_since_start_usd"] == pytest.approx(15 / 30 + 0.90)
    junk = town_ledger(settings, money, {"cost_usd_total": "lots", "cost_usd_today": -1}, NOW, NOW - DAY)
    assert junk["cost_per_day_usd"] == pytest.approx(5 / 30) and junk["cost_since_start_usd"] == pytest.approx(5 / 30)
    live = town_ledger(live_settings(make_settings), money, None, NOW, None)
    assert live["label"] == "Real money" and "today (real money)." in live["line"] and live["covered_today"] is True
    assert live["cost_since_start_usd"] is None and live["line"].endswith("has been running is not known yet.")


def test_the_town_card_sits_under_the_money_card_with_two_bars_of_plain_html(make_settings: Callable[..., Settings]
                                                                             ) -> None:
    from nightcrawler.page import _STYLE

    settings = make_settings()
    html = render_page_html(settings)
    ids = re.findall(r'<section class="card" id="([a-z]+)"', html)
    assert ids.index("town") == ids.index("money") + 1
    assert '<h2>The town <small id="town-label">Paper money (pretend)</small></h2>' in html
    assert 'id="town-line"' in html and 'id="town-bars"' in html
    assert 'id="town-label">Real money</small>' in render_page_html(live_settings(make_settings))
    script = page_script(settings)
    assert "function renderTown(t)" in script and "if (s.town) renderTown(s.town);" in script
    assert '"Costs today"' in script and '"Made today"' in script and '"not known yet"' in script
    assert 'track(cost / scale, "cost")' in script and 'made < 0 ? "down" : "up"' in script
    assert "isNum(made) ? track(" in script  # an income that is not known yet draws no bar at all
    assert "canvas" not in script.lower() and "innerHTML" not in script
    assert ".fill.cost{background:var(--muted)}" in _STYLE and ".fill.down{background:var(--down)}" in _STYLE
    (style,) = re.findall(r"<style>(.*?)</style>", html, flags=re.DOTALL)  # the CSP hashes follow the edit
    for text, directive in ((script, "script-src"), (style, "style-src")):
        digest = base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()
        assert f"{directive} 'sha256-{digest}';" in PAGE_CSP


# --------------------------------------------------------------------------- learning card


def test_learning_says_not_installed_when_the_module_is_absent(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)  # first receipt two days ago: day 3
    card = learning_card(settings, NOW, ledger)
    assert card["source"] == "missing" and card["state"] is None and card["variants"] == []
    assert card["headline"] == "Not installed yet: nothing learns by itself in this version."
    assert "day 3" in card["data"]
    assert card["champion"] is None and card["champion_passed_locked_test"] is False
    assert card["can_stop_trading"] is False


@pytest.mark.parametrize("junk", [
    None, [], "text", 42, {"headline": 7, "state": ["x"], "variants": "nope", "data": {"a": 1}},
    {"headline": "ok", "variants": [None, 3, {"name": None}, {"name": "v", "n": "many", "avg": float("nan"),
                                                               "proof": "half"}]},
    {"champion": {"name": 5}, "champion_passed_locked_test": "true", "paper_matches_backtest": 1},
    {"headline": "x" * 10_000, "variants": [{"name": "v" * 500, "n": 10**12, "avg": 1e308, "proof": 7}] * 50},
])
def test_learning_card_junk_never_raises_and_never_counts(monkeypatch: pytest.MonkeyPatch, ledger: Ledger,
                                                          settings: Settings, junk: Any) -> None:
    install_card(monkeypatch, lambda settings, now: junk)
    card = learning_card(settings, NOW, ledger)
    usable = isinstance(junk, dict) and isinstance(junk.get("headline"), str)
    assert card["source"] == ("card" if usable else "error"), junk  # junk is a failure, never "collecting"
    assert isinstance(card["headline"], str) and 0 < len(card["headline"]) <= 160
    assert card["state"] is None or (isinstance(card["state"], str) and len(card["state"]) <= 60)
    assert isinstance(card["variants"], list) and len(card["variants"]) <= 5
    for v in card["variants"]:
        assert isinstance(v["name"], str) and 0 < len(v["name"]) <= 40
        assert v["n"] is None or (isinstance(v["n"], int) and v["n"] >= 0)
        assert v["avg"] is None or abs(v["avg"]) < 1e6
        assert v["proof"] is None or 0.0 <= v["proof"] <= 1.0
    assert card["data"] is None or isinstance(card["data"], str)
    assert card["champion_passed_locked_test"] is False and card["paper_matches_backtest"] is False
    json.dumps(card, allow_nan=False)
    state = build_page_state(ledger, settings, NOW)
    assert not items(state)["edge"]["done"] and not items(state)["paper_match"]["done"]


def test_a_broken_learning_module_shows_as_a_failure_not_as_collecting(monkeypatch: pytest.MonkeyPatch,
                                                                       ledger: Ledger, settings: Settings) -> None:
    """A raising module or a non-card answer is a failure: the Coach is Blocked and steps 1-2 say unknown."""
    def broken(settings: Settings, now: float) -> dict[str, Any]:
        raise RuntimeError("boom")

    seed(ledger)
    for module in (broken, lambda settings, now: ["not", "a", "card"]):
        install_card(monkeypatch, module)
        card = learning_card(settings, NOW, ledger)
        assert card["source"] == "error" and card["headline"] == "The learning system failed: see the logs."
        state = build_page_state(ledger, settings, NOW + 40 * DAY)
        coach = members(state)["coach"]
        assert coach["status"] == "blocked" and "learning system failed" in coach["why"]
        assert "Collecting" not in coach["doing"] and state["learning"]["rule"] is None
        for cid in ("edge", "paper_match"):
            item = items(state)[cid]
            assert not item["done"] and item["reason"] == "Unknown (learning system error): see the logs.", cid


def test_a_learning_card_with_a_future_timestamp_is_not_activity(monkeypatch: pytest.MonkeyPatch, ledger: Ledger,
                                                                  settings: Settings) -> None:
    """A millisecond epoch (a common mistake) or any stamp from the future must not keep the Coach Working."""
    for stamp, kept in ((NOW * 1000, False), (NOW + 3600, False), (NOW + 30, True), (NOW - 60, True)):
        install_card(monkeypatch, lambda settings, now, stamp=stamp: {"headline": "learning", "updated_at": stamp})
        card = learning_card(settings, NOW, ledger)
        assert card["updated_at"] == (stamp if kept else None), stamp
        coach = members(build_page_state(ledger, settings, NOW))["coach"]
        assert coach["status"] == ("working" if kept else "idle") and coach["last_activity"] == card["updated_at"]
    assert derive_status(NOW, NOW * 1000, 300)[0] != "working"  # the team room guards its own stamps too
    assert derive_status(NOW, NOW + 2, 300) == ("working", "")  # a clock a little ahead still counts


def test_the_off_switch_rule_shows_only_when_the_learning_module_says_it_has_one(
        monkeypatch: pytest.MonkeyPatch, ledger: Ledger, settings: Settings) -> None:
    """"The Coach can turn real trading OFF on its own" is a safety claim: never static text, only when the real
    learning module reports exactly ``can_stop_trading: true``."""
    html = render_page_html(settings)
    assert LEARNING_RULE not in html and 'id="learn-rule"' in html
    assert build_page_state(ledger, settings, NOW)["learning"]["rule"] is None  # module absent
    for flag, rule in ((None, None), ("true", None), (1, None), (False, None), (True, LEARNING_RULE)):
        install_card(monkeypatch, lambda settings, now, flag=flag: {"headline": "learning", "can_stop_trading": flag})
        assert build_page_state(ledger, settings, NOW)["learning"]["rule"] == rule, flag


def test_a_real_learning_card_is_shown_safely(monkeypatch: pytest.MonkeyPatch, ledger: Ledger,
                                              settings: Settings) -> None:
    calls: list[tuple[Settings, float]] = []

    def card_state(settings: Settings, now: float) -> dict[str, Any]:
        calls.append((settings, now))
        return {"state": "testing", "headline": "3 strategies on trial, none proven", "data": "41 trades logged",
                "variants": [{"name": "dip-55" + XSS, "n": 12, "avg": -0.8, "proof": 0.25},
                             {"name": "dip-65", "trades": 9, "average": 0.4, "proof_progress": 1.5}]}

    install_card(monkeypatch, card_state)
    card = build_page_state(ledger, settings, NOW)["learning"]
    assert calls == [(settings, NOW)]
    assert card["source"] == "card" and card["state"] == "testing" and card["data"] == "41 trades logged"
    assert card["variants"] == [{"name": "dip-55" + XSS, "n": 12, "avg": -0.8, "proof": 0.25},
                                {"name": "dip-65", "n": 9, "avg": 0.4, "proof": 1.0}]
    assert card["rule"] is None  # the card does not say it can turn trading off


# --------------------------------------------------------------------------- ready for real money?


def test_checklist_items_on_a_fresh_paper_bot(settings: Settings) -> None:
    ready = readiness(settings, {}, wallet_address=None, wallet_sol=None)
    assert [i["id"] for i in ready["items"]] == list(CHECK_IDS)
    assert [i["label"] for i in ready["items"]] == [
        "A strategy proved an edge on unseen data", "Paper trades proved it (150+ trades, 14+ days)",
        "Bot wallet set up and funded", "Keys shared in chat replaced", "Dashboard locked with a password link",
        "Real-money switch"]
    reasons = {i["id"]: i["reason"] for i in ready["items"]}
    assert reasons == {
        "edge": "Not yet — no strategy has beaten trading costs on unseen data so far.",
        "paper_match": "Needs a proven strategy first",
        "wallet": "No bot wallet yet — you create it when you're ready (docs/GOING_LIVE.md).",
        "keys": "Replace the keys you pasted in chat, then set KEYS_ROTATED_ON in Railway.",
        "locked": "Set DASHBOARD_TOKEN in Railway to a long random password.",
        "live": "Last step, only after 1–5.",
    }
    assert ready["done"] == 0 and ready["total"] == 5 and ready["ready"] is False
    assert ready["headline"] == "Not ready yet — 0 of 5 done" and ready["warning"] is None


@pytest.mark.parametrize(("card", "done"), [
    ({}, False), ({"champion": None, "champion_passed_locked_test": True}, False),
    ({"champion": "CASH", "champion_passed_locked_test": True}, False),
    ({"champion": " cash ", "champion_passed_locked_test": True}, False),
    ({"champion": {"name": "CASH"}, "champion_passed_locked_test": True}, False),
    ({"champion": "dip-55", "champion_passed_locked_test": False}, False),
    ({"champion": "dip-55", "champion_passed_locked_test": "true"}, False),
    ({"champion": "dip-55"}, False),
    ({"champion": "dip-55", "champion_passed_locked_test": True}, True),
    ({"champion": {"name": "dip-55"}, "champion_passed_locked_test": True}, True),
])
def test_edge_item_needs_a_non_cash_champion_that_passed_the_locked_test(settings: Settings, card: dict[str, Any],
                                                                         done: bool) -> None:
    item = readiness(settings, card, wallet_address=None, wallet_sol=None)["items"][0]
    assert item["id"] == "edge" and item["done"] is done
    if done:
        assert "dip-55" in item["reason"]


@pytest.mark.parametrize(("card", "done", "reason"), [
    ({"paper_matches_backtest": True}, False, "Needs a proven strategy first"),
    ({**PROVEN, "paper_matches_backtest": False}, False, "Not yet — paper trades don't match the test results yet."),
    ({**PROVEN, "paper_matches_backtest": False, "paper_matches_backtest_reason": "only 4 paper trades so far"},
     False, "only 4 paper trades so far"),
    ({**PROVEN, "paper_matches_backtest": "yes"}, False, "Not yet — paper trades don't match the test results yet."),
    (PROVEN, True, None),
])
def test_paper_match_item(settings: Settings, card: dict[str, Any], done: bool, reason: str | None) -> None:
    item = readiness(settings, card, wallet_address=None, wallet_sol=None)["items"][1]
    assert item["id"] == "paper_match" and item["done"] is done
    if reason is not None:
        assert item["reason"] == reason


def test_wallet_item_needs_a_configured_wallet_an_address_and_a_known_positive_balance(
        make_settings: Callable[..., Settings]) -> None:
    """GOING_LIVE steps 1-3 (create, fund, add BOT_WALLET_SECRET) all happen in PAPER mode, so the wallet
    step can be done before real money is switched on; without the secret it is never done."""
    def wallet(settings: Settings, address: str | None, sol: float | None) -> dict[str, Any]:
        item: dict[str, Any] = readiness(settings, {}, wallet_address=address, wallet_sol=sol)["items"][2]
        assert item["id"] == "wallet"
        return item

    no_wallet = wallet(make_settings(), WALLET, 1.0)
    assert not no_wallet["done"] and no_wallet["reason"].startswith("No bot wallet yet")
    for settings in (make_settings(BOT_WALLET_SECRET="x" * 88), live_settings(make_settings)):
        for address, sol, expect in ((None, 1.0, "not" if settings.is_live else "has not read"),
                                     (WALLET, None, "has not been read recently"), (WALLET, 0.0, "empty"),
                                     (WALLET, -1.0, "empty")):
            item = wallet(settings, address, sol)
            assert not item["done"] and expect in item["reason"], (settings.trading_mode, address, sol)
            assert "No bot wallet yet" not in item["reason"]
        item = wallet(settings, WALLET, 0.5)
        assert item["done"] and "holds 0.5 SOL" in item["reason"], settings.trading_mode
        assert WALLET[:4] in item["reason"] and WALLET not in item["reason"]


def test_keys_lock_and_live_switch_items(make_settings: Callable[..., Settings]) -> None:
    def item(settings: Settings, cid: str) -> dict[str, Any]:
        return {i["id"]: i for i in readiness(settings, {}, wallet_address=None, wallet_sol=None,
                                              now=NOW)["items"]}[cid]

    assert make_settings().keys_rotated_on == ""
    assert item(make_settings(KEYS_ROTATED_ON="2026-10-08"), "keys")["done"]
    assert "2026-10-08" in item(make_settings(KEYS_ROTATED_ON="2026-10-08"), "keys")["reason"]
    assert not item(make_settings(KEYS_ROTATED_ON="   "), "keys")["done"]
    assert item(make_settings(DASHBOARD_TOKEN=TOKEN), "locked")["done"]
    assert TOKEN not in item(make_settings(DASHBOARD_TOKEN=TOKEN), "locked")["reason"]
    assert not item(make_settings(LIVE_CONFIRM=LIVE_CONFIRM_PHRASE), "live")["done"]  # paper mode
    assert item(live_settings(make_settings), "live")["done"]


def test_steps_one_to_five_decide_and_the_switch_is_the_action(make_settings: Callable[..., Settings]) -> None:
    """The verdict is over steps 1-5 (all doable in paper mode); step 6, the real-money switch, is what the
    owner does once they are done, never a requirement for the "ready" answer."""
    paper = make_settings(BOT_WALLET_SECRET="x" * 88, KEYS_ROTATED_ON="2026-10-08", DASHBOARD_TOKEN=TOKEN)
    ready = readiness(paper, PROVEN, wallet_address=WALLET, wallet_sol=0.5, now=NOW)
    assert (ready["done"], ready["total"], ready["ready"]) == (5, 5, True)
    assert ready["headline"] == "Ready to switch on" and ready["warning"] is None
    switch = {i["id"]: i for i in ready["items"]}["live"]
    assert not switch["done"] and "GOING_LIVE" in switch["reason"] and "switch" in switch["reason"]
    live = live_settings(make_settings, KEYS_ROTATED_ON="2026-10-08")
    ready = readiness(live, PROVEN, wallet_address=WALLET, wallet_sol=0.5, now=NOW)
    assert (ready["done"], ready["total"], ready["ready"]) == (5, 5, True)
    assert ready["headline"] == "Ready — real money is on" and ready["items"][5]["done"]
    assert ready["warning"] is None
    # each condition missing on its own keeps the headline neutral and NOT ready
    variants = [
        readiness(live, {**PROVEN, "champion": "CASH"}, wallet_address=WALLET, wallet_sol=0.5),
        readiness(live, {**PROVEN, "paper_matches_backtest": False}, wallet_address=WALLET, wallet_sol=0.5),
        readiness(live, PROVEN, wallet_address=WALLET, wallet_sol=0.0),
        readiness(live_settings(make_settings), PROVEN, wallet_address=WALLET, wallet_sol=0.5),
        readiness(make_settings(KEYS_ROTATED_ON="2026-10-08"), PROVEN, wallet_address=WALLET, wallet_sol=0.5),
    ]
    for r in variants:
        assert r["ready"] is False and r["done"] < 5 and r["headline"].startswith("Not ready yet — ")
        assert r["headline"].endswith(" of 5 done")
    assert variants[0]["warning"] is not None  # real money is ON before every step is done


def test_never_ready_while_the_bot_is_stopped(make_settings: Callable[..., Settings]) -> None:
    live = live_settings(make_settings, KEYS_ROTATED_ON="2026-10-08")
    ready = readiness(live, PROVEN, wallet_address=WALLET, wallet_sol=0.5, now=NOW, stopped=True)
    assert ready["ready"] is False and ready["done"] == 5
    assert ready["headline"] == "Set up, but stopped right now: see the banners at the top"
    not_set_up = readiness(live, {}, wallet_address=WALLET, wallet_sol=0.5, now=NOW, stopped=True)
    assert not_set_up["headline"] == "Not ready yet — 3 of 5 done"


def test_the_page_is_never_ready_with_a_banner_up(monkeypatch: pytest.MonkeyPatch, ledger: Ledger,
                                                  make_settings: Callable[..., Settings]) -> None:
    """Kill switch, halt, silence, a wallet that doesn't match, safe mode, an unknown trade: each one keeps the
    answer at "stopped right now", even with all five steps done."""
    settings = live_settings(make_settings, KEYS_ROTATED_ON="2026-10-08")
    install_card(monkeypatch, lambda settings, now: {"headline": "proven", **PROVEN})
    seed(ledger, mode="live")
    ledger.set_kv("wallet.pubkey", WALLET)
    ledger.record_equity(EquityPoint(ts=NOW - 10, equity_lamports=950_000_000, sol_usd=110.0, equity_usd=104.5,
                                     sol_lamports=600_000_000, positions_value_lamports=350_000_000, mode="live"))
    assert build_page_state(ledger, settings, NOW)["ready"]["headline"] == "Ready — real money is on"
    troubles: list[Callable[[], None]] = [
        lambda: ledger.set_kv("engine.kill_mode", "stop"),
        lambda: ledger.set_kv("risk.halted", {"halted": True, "reason": "[drawdown] -52%", "ts": NOW}),
        lambda: ledger.set_kv("engine.heartbeat", NOW - ENGINE_STALE_S - 60),
        lambda: ledger.set_kv("engine.status", status_kv(drift={"M": {"books": 1, "wallet": 0}})),
        lambda: ledger.set_kv("engine.safe_mode", {"problems": ["x"], "defaults_used": []}),
        lambda: ledger.set_kv("engine.status", status_kv(unresolved_swaps=["M"])),
    ]
    for trouble in troubles:
        trouble()
        state = build_page_state(ledger, settings, NOW)
        assert state["alerts"] and state["ready"]["ready"] is False
        assert state["ready"]["headline"] == "Set up, but stopped right now: see the banners at the top"
        for key, value in (("engine.kill_mode", "off"), ("risk.halted", None), ("engine.heartbeat", NOW - 5),
                           ("engine.status", status_kv()), ("engine.safe_mode", None)):
            ledger.set_kv(key, value)
        assert build_page_state(ledger, settings, NOW)["ready"]["ready"] is True


@pytest.mark.parametrize(("token", "why"), [
    ("4821", "too short"), ("x" * 40, "too easy to guess"), ("abcabcabcabcabcabcabcabcabc", "too easy to guess"),
    (PLACEHOLDER_TOKEN, "the example from the guide"), ("a1B2c3D4e5F6g7H8i9J0k1", "too short"),
])
def test_a_weak_dashboard_token_does_not_count_as_locked(make_settings: Callable[..., Settings], token: str,
                                                         why: str) -> None:
    """Step 5 is ticked only for a password nobody can guess: 24+ characters, not repetitive, not the guide's
    example. The reason never shows the token itself."""
    item = {i["id"]: i for i in readiness(make_settings(DASHBOARD_TOKEN=token), {}, wallet_address=None,
                                          wallet_sol=None, now=NOW)["items"]}["locked"]
    assert not item["done"] and why in item["reason"] and token not in item["reason"]
    strong = {i["id"]: i for i in readiness(make_settings(DASHBOARD_TOKEN=TOKEN), {}, wallet_address=None,
                                            wallet_sol=None, now=NOW)["items"]}["locked"]
    assert strong["done"]


def test_keys_item_needs_a_real_date_that_is_not_in_the_future(make_settings: Callable[..., Settings]) -> None:
    def keys(value: str) -> dict[str, Any]:
        settings = make_settings()
        object.__setattr__(settings, "keys_rotated_on", value)  # what Settings validation would refuse
        return {i["id"]: i for i in readiness(settings, {}, wallet_address=None, wallet_sol=None,
                                              now=NOW)["items"]}["keys"]

    assert keys("2026-10-08") == {"id": "keys", "label": "Keys shared in chat replaced", "done": True,
                                  "reason": "Done on 2026-10-08."}
    assert keys("2026-10-09")["done"]  # "today" in a time zone ahead of UTC
    future = keys("2026-10-12")
    assert not future["done"] and "in the future" in future["reason"]
    for junk in ("no", "false", "not yet", "TODO", "08/10/2026", "20261008", "sk-ant-api03-NEWKEY0123456789"):
        item = keys(junk)
        assert not item["done"] and item["reason"] == "KEYS_ROTATED_ON must be a date like 2026-10-09.", junk


# --------------------------------------------------------------------------- routes


def test_page_route_and_combined_endpoint(serve: Callable[..., Client], ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    client = serve(settings, ledger)
    status, headers, body = client.request("/")
    assert status == 200 and headers["Content-Type"] == "text/html; charset=utf-8"
    assert headers["Content-Security-Policy"] == PAGE_CSP == CONTENT_SECURITY_POLICY
    assert headers["X-Frame-Options"] == "DENY" and headers["Cache-Control"] == "no-store"
    assert body.decode() == render_html(settings) == render_page_html(settings)
    status, headers, body = client.request("/api/page")
    assert status == 200 and headers["Content-Type"] == "application/json"
    assert headers["Cache-Control"] == "no-store" and headers["X-Content-Type-Options"] == "nosniff"
    assert [m["id"] for m in json.loads(body)["team"]["members"]] == MEMBER_IDS
    assert client.request("/api/state")[0] == 200 and client.request("/api/team")[0] == 200  # still served
    assert client.request("/api/page/x")[0] == 404 and client.request("/api/page", method="POST")[0] == 405


def test_old_team_links_redirect_to_the_one_page(serve: Callable[..., Client], ledger: Ledger,
                                                 make_settings: Callable[..., Settings]) -> None:
    client = serve(make_settings(), ledger)
    status, headers, body = client.request("/team")
    assert (status, headers["Location"], body) == (302, "/", b"")
    locked = serve(make_settings(DASHBOARD_TOKEN=TOKEN), ledger)
    assert locked.request("/team")[0] == 401
    status, headers, _ = locked.request(f"/team?token={TOKEN}")
    assert status == 302 and headers["Location"] == "/"  # never echo the token back
    cookie = headers["Set-Cookie"].split(";", 1)[0]
    assert TOKEN not in cookie and locked.request("/", headers={"Cookie": cookie})[0] == 200


def test_token_gate_on_every_route(serve: Callable[..., Client], ledger: Ledger,
                                   make_settings: Callable[..., Settings]) -> None:
    seed(ledger)
    client = serve(make_settings(DASHBOARD_TOKEN=TOKEN), ledger)
    assert client.request("/healthz")[0] == 200
    routes = ("/", "/api/page", "/api/state", "/api/team", "/team")
    for path in routes:
        for query in ("", "?token=wrong", "?token=" + TOKEN[:-1]):
            status, headers, body = client.request(path + query)
            assert status == 401 and b"Locked" in body and "Set-Cookie" not in headers, path + query
        status, headers, _ = client.request(f"{path}?token={TOKEN}")
        assert status == (302 if path == "/team" else 200) and "Set-Cookie" in headers, path
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        assert client.request(path, headers={"Cookie": cookie})[0] in (200, 302)
        assert client.request(path, headers={"Cookie": f"{COOKIE_NAME}=forged"})[0] == 401


def test_no_secret_in_any_response(serve: Callable[..., Client], ledger: Ledger, monkeypatch: pytest.MonkeyPatch,
                                   make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(TRADING_MODE="live", LIVE_CONFIRM=LIVE_CONFIRM_PHRASE,
                             SOLANA_RPC_URL=f"https://mainnet.helius-rpc.com/?api-key={RPC_KEY}", **SECRETS)
    leak = " " + " ".join(secret_values())
    seed(ledger, mode="live", leak=leak)
    ledger.set_kv("wallet.pubkey", WALLET)
    card = {"headline": "card" + leak, "state": "s" + leak, "data": "d" + leak, "champion": "c" + leak,
            "variants": [{"name": "v" + leak, "n": 1}], "paper_matches_backtest_reason": "r" + leak}
    install_card(monkeypatch, lambda settings, now: card)
    client = serve(settings, ledger)
    responses = [client.request(path) for path in (
        "/", f"/?token={TOKEN}", "/api/page", f"/api/page?token={TOKEN}", f"/team?token={TOKEN}",
        f"/api/team?token={TOKEN}", f"/api/state?token={TOKEN}")]
    state = json.loads(responses[3][2])
    assert state["mode"] == "LIVE" and state["learning"]["source"] == "card"
    assert "[REDACTED]" in state["learning"]["headline"] and "[REDACTED]" in state["trades"]["closed"][0]["coin"]
    for status, headers, body in responses:
        blob = body.decode("utf-8") + "\n" + "\n".join(f"{k}: {v}" for k, v in headers.items())
        for secret in secret_values():
            assert secret not in blob, (status, secret)
            assert secret[:16] not in blob and secret[-16:] not in blob, (status, secret)
        assert "helius-rpc.com" not in blob


def test_json_stays_small_on_a_busy_ledger(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    for i in range(400):
        ledger.record_candidate(TokenCandidate(mint=f"BULK{i}", symbol=f"B{i}" + "x" * 60, discovered_at=NOW - i))
        ledger.record_decision(Decision(ts=NOW - i, mint=f"BULK{i}", action="reject_cocoon",
                                        reason="[top10] " + "very long reason " * 40, symbol="B" * 200))
        ledger.record_equity(EquityPoint(ts=NOW - 30 * DAY + i * 6000, equity_lamports=10**9, sol_usd=100.0,
                                         equity_usd=100.0))
        ledger.upsert_position(Position(id=f"q{i}", mint=f"Q{i}", symbol="Q" * 300, pool=None, opened_at=NOW - 3 * DAY,
                                        token_decimals=6, cost_lamports=10**8, status="closed",
                                        closed_at=NOW - 2 * DAY, exit_reason="x" * 400, mode="paper"))
    watching = [{"mint": f"W{i}", "symbol": "W" * 100, "last_signal": "dip 1.0% < required 55.0%"} for i in range(100)]
    ledger.set_kv("engine.status", status_kv(watchlist=100, watching=watching))
    state = build_page_state(ledger, settings, NOW)
    body = json.dumps(state, separators=(",", ":"))
    assert len(body) < 43_000, len(body)  # (plain.hearts, the team's hearts, adds about 2.2 KB of fixed copy and lines)
    assert len(state["money"]["curve"]) <= 300 and len(state["trades"]["closed"]) == 10
    assert all(len(t["coin"]) <= 24 and len(t["why"]) <= 60 for t in state["trades"]["closed"])


def test_ledger_text_never_becomes_markup(serve: Callable[..., Client], ledger: Ledger, settings: Settings) -> None:
    """A coin called ``<img src=x onerror=alert(1)>``: the HTML never carries ledger data at all, and the JSON is
    served as JSON (nosniff) with ``<`` escaped, so even a browser that guessed would see no tag."""
    seed(ledger, symbol=XSS)
    client = serve(settings, ledger)
    _, _, html = client.request("/")
    assert XSS.encode() not in html and b"onerror" not in html
    _, headers, body = client.request("/api/page")
    assert headers["Content-Type"] == "application/json" and headers["X-Content-Type-Options"] == "nosniff"
    assert b"<img" not in body and json.loads(body)["trades"]["open"][0]["coin"] == XSS[:23] + "…"


# --------------------------------------------------------------------------- the page itself


def page_script(settings: Settings) -> str:
    (script,) = re.findall(r"<script>(.*?)</script>", render_page_html(settings), flags=re.DOTALL)
    return script


def test_page_script_never_turns_data_into_html(settings: Settings) -> None:
    script = page_script(settings)
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function",
                 "setAttribute(\"on", "srcdoc"):
        assert sink not in script, sink
    assert "textContent" in script or ".append(" in script
    assert script.count(".replaceChildren(") == 1 and "function put(node, ...kids)" in script  # never "null"


def test_page_has_every_section_in_order_and_is_built_for_phones(settings: Settings) -> None:
    html = render_page_html(settings)
    ids = re.findall(r'<section class="card" id="([a-z]+)"', html)
    assert ids == ["plain", "money", "town", "wallet", "team", "trades", "learning", "ready", "receipts", "usage"]
    for mid, name, role in MEMBERS:
        assert f'id="m-{mid}"' in html and f"<b>{name}</b>" in html and role in html
    assert html.count("<details") >= len(MEMBERS)  # tap a member to see its last events, no JS needed
    assert 'name="viewport"' in html and "width=device-width" in html
    assert "prefers-color-scheme:dark" in html and "body{margin:0;background:var(--page)" in html
    assert f'data-refresh="{REFRESH_S}"' in html and 10 <= REFRESH_S <= 15
    assert "visibilitychange" in html and "document.hidden" in html  # pauses while hidden, refreshes on return
    assert "Paper money (pretend)" in html and ">PAPER<" not in html  # the badge waits for the data (plain.real)
    assert '<b class="mode" id="mode" hidden></b>' in html
    assert 'id="learn-rule" hidden' in html and "Ready for real money?" in html  # the rule only from real data
    assert "min-height:44px" in html  # tap targets
    assert not re.search(r"""(?:src|href)\s*=\s*["']?(?:https?:)?//""", html)
    assert "@import" not in html and "url(" not in html
    assert set(re.findall(r"https?://[^\s\"'<>]+", html)) == {"http://www.w3.org/2000/svg"}  # SVG namespace only


def test_page_texts_are_plain_words(settings: Settings) -> None:
    html = render_page_html(settings)
    visible = re.sub(r"<script>.*?</script>|<style>.*?</style>|<[^>]+>", " ", html, flags=re.DOTALL)
    assert not JARGON.search(visible), JARGON.search(visible)
    strings = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', page_script(settings))
    words = [s for s in strings if " " in s]  # user-facing sentences, not identifiers
    assert words and not [s for s in words if JARGON.search(s)]


def test_live_page_says_real_money(make_settings: Callable[..., Settings]) -> None:
    html = render_page_html(live_settings(make_settings))
    assert ">REAL MONEY ON<" in html and "Real money" in html


def test_page_csp_hashes_match_the_inline_script_and_style(settings: Settings) -> None:
    html = render_page_html(settings)
    (script,) = re.findall(r"<script>(.*?)</script>", html, flags=re.DOTALL)
    (style,) = re.findall(r"<style>(.*?)</style>", html, flags=re.DOTALL)

    def source(text: str) -> str:
        return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"

    assert f"script-src {source(script)};" in PAGE_CSP and f"style-src {source(style)};" in PAGE_CSP
    assert "default-src 'none'" in PAGE_CSP and "connect-src 'self'" in PAGE_CSP
    assert "unsafe-inline" not in PAGE_CSP and "unsafe-eval" not in PAGE_CSP


def test_an_open_trade_without_a_price_yet_reads_cleanly(settings: Settings) -> None:
    """Right after a buy, before the first price check: no "now —", no empty " ·  · " part, no bare dash."""
    script = page_script(settings)
    assert '"price not checked yet"' in script
    assert '" · now " + price(' not in script and '" · " + pct(p.pnl_pct)' not in script
    assert '.filter(Boolean).join(" · ")' in script
    assert 'isNum(p.pnl_usd) ? el("span", "big "' in script  # no lone dash where the result would be


def test_refreshes_rely_on_the_login_cookie_not_the_raw_token(settings: Settings) -> None:
    """The link's ?token= sets the HMAC cookie on the first response; every refresh then sends only the cookie,
    so the raw token is not written into proxy logs every 15 s. The token is retried only after a 401."""
    script = page_script(settings)
    assert '"api/page" + (token' not in script
    assert 'fetch("api/page", opts)' in script
    retry = re.search(r'if \(res\.status === 401 && token\) res = await fetch\("api/page\?token=" \+ '
                      r'encodeURIComponent\(token\), opts\);', script)
    assert retry is not None and script.count("api/page?token=") == 1


def test_an_unknown_bar_draws_no_track_and_tracks_are_neutral(settings: Settings) -> None:
    """A bar with no value ("not checked yet") draws no track at all: a full-width soft track looked like a
    FULL bar in dark mode. Tracks use the neutral hairline colour; >= 80 % of a budget is the warn colour."""
    from nightcrawler.page import _SCRIPT, _STYLE

    assert "isNum(value) ? track(value, cls) : null" in _SCRIPT
    rule = re.search(r"\.track\{[^}]*\}", _STYLE)
    assert rule is not None and "var(--hair)" in rule.group(0)
    assert 'level === "warn"' in _SCRIPT and "--warn" in _STYLE


def test_dark_mode_redefines_every_colour_with_an_explicit_background(settings: Settings) -> None:
    from nightcrawler.page import _STYLE

    light = dict(re.findall(r"(--[a-z0-9-]+):([^;}]+)", _STYLE.split("@media (prefers-color-scheme:dark)")[0]))
    dark_block = _STYLE.split("@media (prefers-color-scheme:dark)")[1].split("}}")[0]
    dark = dict(re.findall(r"(--[a-z0-9-]+):([^;}]+)", dark_block))
    for token in ("--page", "--card", "--ink", "--ink2", "--hair", "--accent", "--up", "--down"):
        assert token in light and token in dark and light[token] != dark[token], token
