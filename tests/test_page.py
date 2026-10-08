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
from nightcrawler.config import LIVE_CONFIRM_PHRASE, Settings
from nightcrawler.dashboard import CONTENT_SECURITY_POLICY, COOKIE_NAME, DashboardServer, build_state, render_html
from nightcrawler.ledger import Ledger
from nightcrawler.models import Decision, EquityPoint, Fill, Position, SafetyReport, TokenCandidate, Verdict
from nightcrawler.page import PAGE_CSP, REFRESH_S, render_page_html
from nightcrawler.pagestate import LEARNING_RULE, MEMBERS, STALE_BANNER_S, build_page_state, learning_card
from nightcrawler.readiness import CHECK_IDS, readiness
from nightcrawler.teamroom import TeamRoom

NOW = 1_791_475_200.0  # 2026-10-08T16:00:00Z (the fake clock's start)
MIDNIGHT = NOW - NOW % 86_400
DAY = 86_400.0
XSS = "<img src=x onerror=alert(1)>"
HIGGS = "HiGGSmintAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
MEMBER_IDS = ["crawler", "cocoon", "strategy", "radar", "judge", "broker", "risk", "receipts", "coach"]
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
PROVEN = {"champion": "dip-rebound v2", "champion_passed_locked_test": True, "paper_matches_backtest": True}
#: Words a non-developer should never have to decode on the page.
JARGON = re.compile(r"\b(?:bps|lamports?|mint|slippage|mcap|prefilter|kv|ledger)\b", re.IGNORECASE)


# --------------------------------------------------------------------------- helpers


@pytest.fixture
def ledger(tmp_path: Path, fake_clock: FakeClock) -> Iterator[Ledger]:
    with Ledger(tmp_path / "nc.db", clock=fake_clock) as led:
        yield led


@pytest.fixture(autouse=True)
def no_learning_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """The learning card module is built on another branch: by default it is ABSENT in these tests."""
    monkeypatch.setitem(sys.modules, "nightcrawler.learn.card", None)


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
        assert m["status"] == "waiting" and m["doing"] and m["last_activity"] is None and m["events"] == []
    assert state["trades"]["open"] == [] and state["trades"]["closed"] == []
    assert state["learning"]["state"] == "collecting" and state["learning"]["headline"] == "Collecting data, day 1"
    assert state["learning"]["rule"] == LEARNING_RULE and state["learning"]["source"] == "fallback"
    assert state["ready"]["ready"] is False and state["ready"]["headline"] == "Not ready yet — 0 of 6 done"
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
        "Crawler", "Cocoon", "Strategy", "Radar", "Jev", "Broker", "Risk", "Receipts", "Coach"]
    assert by["crawler"]["status"] == "working" and by["crawler"]["last_activity"] == NOW  # coin last seen now
    assert by["crawler"]["doing"] == "Found 1 new coin in the last hour; 120 too young to judge yet."
    assert by["cocoon"]["doing"].startswith("Last 24 h: threw out 1 coin, let 1 through.")
    assert by["strategy"]["doing"] == "Watching 2 coins for a 55% drop and a bounce back; closest: AAA."
    assert by["broker"]["doing"] == "1 buy and 0 sells in the last 24 h, with pretend money. Holding 1 trade."
    assert by["risk"]["status"] == "working" and "1 of 3 trade slots" in by["risk"]["doing"]
    assert by["judge"]["doing"].startswith("Last 24 h: 0 yes, 1 no.")
    assert by["coach"]["status"] == "waiting" and by["coach"]["doing"] == "Collecting data, day 3"
    assert sum(state["team"]["counts"].values()) == len(MEMBER_IDS)
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
    assert [a["level"] for a in stale] == ["bad"] and "has not checked in for 2 min" in stale[0]["text"]
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


# --------------------------------------------------------------------------- learning card


def test_learning_falls_back_when_the_module_is_absent(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)  # first receipt two days ago: day 3
    card = learning_card(settings, NOW, ledger)
    assert card["source"] == "fallback" and card["state"] == "collecting"
    assert card["headline"] == "Collecting data, day 3" and card["variants"] == []
    assert card["champion"] is None and card["champion_passed_locked_test"] is False


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


def test_a_failing_learning_module_falls_back(monkeypatch: pytest.MonkeyPatch, ledger: Ledger,
                                              settings: Settings) -> None:
    def broken(settings: Settings, now: float) -> dict[str, Any]:
        raise RuntimeError("boom")

    install_card(monkeypatch, broken)
    card = learning_card(settings, NOW, ledger)
    assert card["source"] == "fallback" and card["headline"].startswith("Collecting data")


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
    assert card["rule"] == "The Coach can turn real trading OFF on its own, never ON."


# --------------------------------------------------------------------------- ready for real money?


def test_checklist_items_on_a_fresh_paper_bot(settings: Settings) -> None:
    ready = readiness(settings, {}, wallet_address=None, wallet_sol=None)
    assert [i["id"] for i in ready["items"]] == list(CHECK_IDS)
    assert [i["label"] for i in ready["items"]] == [
        "A strategy proved an edge on unseen data", "Paper results match the test results",
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
    assert ready["done"] == 0 and ready["ready"] is False and ready["headline"] == "Not ready yet — 0 of 6 done"
    assert ready["warning"] is None


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


def test_wallet_item_needs_live_config_an_address_and_a_known_positive_balance(
        make_settings: Callable[..., Settings]) -> None:
    paper = make_settings(BOT_WALLET_SECRET="x" * 88)
    assert not readiness(paper, {}, wallet_address=WALLET, wallet_sol=1.0)["items"][2]["done"]
    live = live_settings(make_settings)
    for address, sol, expect in ((None, 1.0, "not known yet"), (WALLET, None, "not been read yet"),
                                 (WALLET, 0.0, "empty")):
        item = readiness(live, {}, wallet_address=address, wallet_sol=sol)["items"][2]
        assert not item["done"] and expect in item["reason"], (address, sol)
    item = readiness(live, {}, wallet_address=WALLET, wallet_sol=0.5)["items"][2]
    assert item["done"] and "0.5" in item["reason"] and WALLET[:4] in item["reason"] and WALLET not in item["reason"]


def test_keys_lock_and_live_switch_items(make_settings: Callable[..., Settings]) -> None:
    def item(settings: Settings, cid: str) -> dict[str, Any]:
        return {i["id"]: i for i in readiness(settings, {}, wallet_address=None, wallet_sol=None)["items"]}[cid]

    assert make_settings().keys_rotated_on == ""
    assert item(make_settings(KEYS_ROTATED_ON="2026-10-08"), "keys")["done"]
    assert "2026-10-08" in item(make_settings(KEYS_ROTATED_ON="2026-10-08"), "keys")["reason"]
    assert not item(make_settings(KEYS_ROTATED_ON="   "), "keys")["done"]
    assert item(make_settings(DASHBOARD_TOKEN=TOKEN), "locked")["done"]
    assert TOKEN not in item(make_settings(DASHBOARD_TOKEN=TOKEN), "locked")["reason"]
    assert not item(make_settings(LIVE_CONFIRM=LIVE_CONFIRM_PHRASE), "live")["done"]  # paper mode
    assert item(live_settings(make_settings), "live")["done"]


def test_all_six_done_is_the_only_ready(make_settings: Callable[..., Settings]) -> None:
    live = live_settings(make_settings, KEYS_ROTATED_ON="2026-10-08")
    ready = readiness(live, PROVEN, wallet_address=WALLET, wallet_sol=0.5)
    assert ready["done"] == 6 and ready["ready"] is True and ready["headline"] == "Ready"
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
        assert r["ready"] is False and r["done"] < 6 and r["headline"].startswith("Not ready yet — ")
    assert variants[0]["warning"] is not None  # real money is ON before every step is done


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
    assert len(body) < 40_000, len(body)
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
    assert ids == ["money", "team", "trades", "learning", "ready", "receipts", "usage"]
    for mid, name, role in MEMBERS:
        assert f'id="m-{mid}"' in html and f"<b>{name}</b>" in html and role in html
    assert html.count("<details") >= len(MEMBERS)  # tap a member to see its last events, no JS needed
    assert 'name="viewport"' in html and "width=device-width" in html
    assert "prefers-color-scheme:dark" in html and "body{margin:0;background:var(--page)" in html
    assert f'data-refresh="{REFRESH_S}"' in html and 10 <= REFRESH_S <= 15
    assert "visibilitychange" in html and "document.hidden" in html  # pauses while hidden, refreshes on return
    assert "Paper money (pretend)" in html and ">PAPER<" in html
    assert LEARNING_RULE in html and "Ready for real money?" in html
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
    assert ">LIVE<" in html and "Real money" in html


def test_page_csp_hashes_match_the_inline_script_and_style(settings: Settings) -> None:
    html = render_page_html(settings)
    (script,) = re.findall(r"<script>(.*?)</script>", html, flags=re.DOTALL)
    (style,) = re.findall(r"<style>(.*?)</style>", html, flags=re.DOTALL)

    def source(text: str) -> str:
        return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"

    assert f"script-src {source(script)};" in PAGE_CSP and f"style-src {source(style)};" in PAGE_CSP
    assert "default-src 'none'" in PAGE_CSP and "connect-src 'self'" in PAGE_CSP
    assert "unsafe-inline" not in PAGE_CSP and "unsafe-eval" not in PAGE_CSP


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
