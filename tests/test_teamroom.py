"""Team room (/team, /api/team): state assembly from the ledger, status chips, routes behind the
dashboard token, the page itself, no secrets anywhere and a small JSON."""

from __future__ import annotations

import http.client
import json
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock

from nightcrawler import __version__
from nightcrawler.config import LIVE_CONFIRM_PHRASE, Settings
from nightcrawler.dashboard import COOKIE_NAME, DashboardServer, build_state
from nightcrawler.ledger import Ledger, LedgerError
from nightcrawler.models import (
    Decision,
    EquityPoint,
    Fill,
    Position,
    SafetyReport,
    TokenCandidate,
    Verdict,
)
from nightcrawler.teamroom import (
    ENGINE_STALE_S,
    EVENTS_MAX,
    PANELS,
    REFRESH_S,
    TeamRoom,
    build_team_state,
    deploy_info,
    derive_status,
    proximity,
)

NOW = 1_791_475_200.0  # 2026-10-08T16:00:00Z (the fake clock's start)
MIDNIGHT = NOW - NOW % 86_400
HIGGS = "HiGGSmintAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
PANEL_IDS = ["crawler", "cocoon", "radar", "judge", "strategy", "broker", "risk", "receipts", "upgrades"]
PANEL_KEYS = {"id", "name", "role", "status", "why", "doing", "last_activity", "headline", "stats", "events"}
STATUSES = {"working", "idle", "waiting", "blocked"}
SECRETS = {
    "ANTHROPIC_API_KEY": "sk-ant-api03-TOPSECRETanthropicKEY0123456789",
    "JUPITER_API_KEY": "jup-secret-key-5f4dcc3b5aa765d61d8327deb882cf99",
    "BOT_WALLET_SECRET": "4wBqpZM9xaSheZzJSMawUKKwhdpChKbZ5eu5ky4Vigw1t7Wv5jNzqJmsRcFVw8NhpWxnJ8u5fE3ygVJgLFrTTXpo",
    "X_BEARER_TOKEN": "x-bearer-AAAAAAAAAAAAAAAAAAAAAMLheAAAAAAA0%2BuSeid",
    "DASHBOARD_TOKEN": "dash-token-correct-horse-battery-staple",
}
RPC_KEY = "helius-rpc-key-0a1b2c3d4e5f"
TOKEN = SECRETS["DASHBOARD_TOKEN"]
DEPLOY_ENV = {"RAILWAY_GIT_COMMIT_SHA": "0123456789abcdef0123456789abcdef01234567",
              "RAILWAY_GIT_COMMIT_MESSAGE": "feat: team room\n\nlong body",
              "SOME_OTHER_VAR": "must-never-be-shown-7f3a"}


# --------------------------------------------------------------------------- helpers


@pytest.fixture
def ledger(tmp_path: Path, fake_clock: FakeClock) -> Iterator[Ledger]:
    with Ledger(tmp_path / "nc.db", clock=fake_clock) as led:
        yield led


def secret_values() -> list[str]:
    return [*SECRETS.values(), RPC_KEY]


def status_kv(ts: float = NOW - 5, **extra: Any) -> dict[str, Any]:
    """An ``engine.status`` dict shaped like the engine writes it."""
    status = {
        "state": "running", "mode": "paper", "ts": ts, "kill_mode": "off", "watchlist": 4,
        "watching": [{"mint": "A1", "symbol": "AAA", "last_signal": "dip 12.0% < required 55.0%"},
                     {"mint": "B1", "symbol": "BBB", "last_signal": "buyers not back: 1 green closes < 2"},
                     {"mint": "C1", "symbol": "CCC", "last_signal": "dip 44.0% < required 55.0%"},
                     {"mint": "D1", "symbol": "DDD", "last_signal": None}],
        "cocoon_queue": 4, "unresolved_swaps": [], "inflight_swaps": [], "drift": {}, "entries_blocked": None,
        "counters": {"cocoon_checked": 40, "candle_fetches": 12, "entry_signals": 2, "cocoon_retry": 1},
        "prefilter_rejections": {"too young": 2000},
        "crawler": {"polls": 100, "seen": 2500, "emitted": 60, "rejected": 900, "nursery": 2100,
                    "feed_errors": {"gt_new_pools": 3, "jupiter_recent": 1}},
        "stages": {},
    }
    status.update(extra)
    return status


def seed(ledger: Ledger, leak: str = "", mode: str = "paper") -> None:
    """A realistic morning: coins found, rug-filter verdicts, a radar flag, judge verdicts, one trade with a
    partial take-profit, equity down 5 % today, receipts, a boot and the engine's status."""
    ledger.append_receipt("note", {"event": "shutdown", "version": "0.0.9"}, ts=NOW - 7300)
    ledger.append_receipt("boot", {"version": __version__, "mode": mode, "settings": {}, "pid": 1}, ts=NOW - 7200)
    ledger.set_kv(f"{mode}.start_lamports", 1_000_000_000)
    ledger.set_kv(f"{mode}.start_sol_usd", 100.0)
    for ts, lamports, sol_usd in ((MIDNIGHT - 600, 980_000_000, 100.0), (MIDNIGHT + 60, 1_000_000_000, 100.0),
                                  (NOW - 30, 950_000_000, 110.0)):
        ledger.record_equity(EquityPoint(ts=ts, equity_lamports=lamports, sol_usd=sol_usd,
                                         equity_usd=lamports / 1e9 * sol_usd, mode=mode))
    for i, (mint, symbol, age) in enumerate((("C1mint", "NEWEST" + leak, 120), ("C2mint", "SECOND", 600),
                                             ("C3mint", "THIRD", 1800), ("C4mint", "OLDER", 7200),
                                             ("C5mint", "ANCIENT", 30 * 3600))):
        ledger.record_candidate(TokenCandidate(mint=mint, symbol=symbol, age_min=61.0 + i, mcap_usd=210_000.0,
                                               sources=["jupiter_recent", "gt_new_pools"], discovered_at=NOW - age))
    for mint, passed, reasons in (("C1mint", True, []),
                                  ("C2mint", False, ["[top10] top-10 own 45%", "[mint_authority] not renounced"]),
                                  ("C3mint", False, ["[top10] top-10 own 60%"]),
                                  ("C4mint", False, ["source unavailable: rugcheck (not ready)"])):
        ledger.record_safety(SafetyReport(mint=mint, passed=passed, hard_fail_reasons=reasons, checked_at=NOW - 100))
    signal = {"kind": "enter", "reason": "dip-rebound: dip 60.0% from high, 2 green closes", "confidence": 0.6,
              "fraction": 1.0, "metrics": {}}
    clear = {"window_min": 15.0, "big_sells_usd": 450.0, "insider_sell_usd": 0.0, "creator_sold": False,
             "flagged": False, "reasons": [], "trades_seen": 7, "liquidity_usd": 80_000.0, "error": None}
    flagged = {**clear, "flagged": True, "creator_sold": True, "insider_sell_usd": 1200.0,
               "reasons": ["creator sold $1,200"]}
    yes = Verdict(decision="yes", confidence=0.8, reasons=["clean holders"], model="claude-opus-5-5",
                  latency_ms=900, cost_usd=0.004, source="claude")
    no = Verdict(decision="no", confidence=0.7, reasons=["creator selling" + leak], model="claude-opus-5-5",
                 latency_ms=800, cost_usd=0.003, source="claude")
    quote = {"side": "buy", "expected_out_amount": 5_050_505_050, "price_impact_pct": 1.5}
    for d in (
        Decision(ts=NOW - 5000, mint="C4mint", action="reject_cocoon", reason="[top10] old", symbol="OLDER"),
        Decision(ts=NOW - 3000, mint=HIGGS, action="enter", reason=signal["reason"], symbol="HIGGS", verdict=yes,
                 inputs={"signal": signal, "radar": clear, "quote": quote}),
        Decision(ts=NOW - 1000, mint=HIGGS, action="exit_partial", reason="take_profit_partial", symbol="HIGGS"),
        Decision(ts=NOW - 900, mint="DUMPmint", action="reject_radar", reason="radar: creator sold $1,200",
                 symbol="DUMP", inputs={"signal": signal, "radar": flagged}),
        Decision(ts=NOW - 800, mint="JUDGEDmint", action="reject_judge", reason="judge: creator selling" + leak,
                 symbol="JUDGED", verdict=no, inputs={"signal": signal, "radar": clear}),
        Decision(ts=NOW - 700, mint="RISKmint", action="reject_risk", reason="[max_positions] 3 open",
                 symbol="RISKY", inputs={"signal": signal}),
        Decision(ts=NOW - 200, mint="C2mint", action="reject_cocoon",
                 reason="[top10] top-10 own 45%; [mint_authority] not renounced" + leak, symbol="SECOND"),
        Decision(ts=NOW - 100, mint="C1mint", action="watch", reason="passed cocoon (2 warnings)", symbol="NEWEST"),
    ):
        ledger.record_decision(d)
    ledger.record_fill(Fill(id="f1", mode=mode, side="buy", mint=HIGGS, sol_lamports=100_000_000,
                            token_amount=5_000_000_000, token_decimals=6, price_usd=0.002, sol_usd=100.0,
                            fees_lamports=300_000, platform_fee_bps=10, price_impact_pct=1.5, signature=None,
                            request_id="r1", ts=NOW - 3000, expected_out_amount=5_050_505_050,
                            rent_lamports=2_039_280, symbol="HIGGS"))
    ledger.record_fill(Fill(id="f2", mode=mode, side="sell", mint=HIGGS, sol_lamports=69_300_000,
                            token_amount=2_500_000_000, token_decimals=6, price_usd=0.003, sol_usd=110.0,
                            fees_lamports=300_000, platform_fee_bps=10, price_impact_pct=2.0, signature=None,
                            request_id="r2", ts=NOW - 1000, expected_out_amount=70_000_000, symbol="HIGGS"))
    ledger.upsert_position(Position(id="p1", mint=HIGGS, symbol="HIGGS", pool="pool", opened_at=NOW - 3000,
                                    token_decimals=6, entry_fill_ids=["f1"], exit_fill_ids=["f2"],
                                    token_amount=2_500_000_000, initial_token_amount=5_000_000_000,
                                    cost_lamports=100_000_000, proceeds_lamports=69_300_000,
                                    fees_lamports=600_000, rent_lamports=2_039_280, entry_price_usd=0.002,
                                    peak_price_usd=0.0031, last_price_usd=0.0029, partial_taken=True, mode=mode))
    ledger.set_kv("engine.heartbeat", NOW - 5)
    ledger.set_kv("engine.started_at", NOW - 7200)
    ledger.set_kv("engine.status", status_kv(note="ok" + leak))
    ledger.set_kv("engine.last_error", "2026-10-08T15:00:00Z watch: HttpError 429" + leak)
    ledger.set_kv("judge.calls", 5)
    ledger.set_kv("judge.cost_usd_total", 0.02)
    ledger.set_kv("judge.cost_usd_day", {"day": "2026-10-08", "usd": 0.012})


def panels(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p["id"]: p for p in state["panels"]}


def stat(panel: dict[str, Any], label: str) -> Any:
    for row in panel["stats"]:
        if row["label"] == label:
            return row["value"]
    raise KeyError(f"{panel['id']} has no stat {label!r}: {[r['label'] for r in panel['stats']]}")


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

    def _serve(settings: Settings, ledger: Ledger | None, clock: FakeClock | None = None,
               environ: dict[str, str] | None = None) -> Client:
        cache: dict[str, Any] = {}
        team = None
        if ledger is not None:
            team = TeamRoom(settings, ledger=ledger, clock=clock or FakeClock(NOW), environ=environ or {})
        server = DashboardServer(settings, (lambda: build_state(ledger, settings, NOW, cache)) if ledger else dict,
                                 host="127.0.0.1", port=0, team=team)
        server.start()
        servers.append(server)
        return Client(server)

    yield _serve
    for server in servers:
        server.stop()


# --------------------------------------------------------------------------- state assembly


def test_state_assembly_from_a_seeded_ledger(ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(ANTHROPIC_API_KEY="sk-ant-test-key-0123456789", JUDGE_MODE="advisory")
    seed(ledger)
    state = build_team_state(ledger, settings, NOW, deploy=deploy_info(DEPLOY_ENV))
    assert state["mode"] == "PAPER" and state["version"] == __version__ and state["generated_at"] == NOW
    assert state["refresh_s"] == REFRESH_S
    assert [p["id"] for p in state["panels"]] == PANEL_IDS == [pid for pid, _, _ in PANELS]
    for panel in state["panels"]:
        assert PANEL_KEYS <= set(panel), panel["id"]
        assert panel["status"] in STATUSES and isinstance(panel["why"], str)
        assert len(panel["events"]) <= EVENTS_MAX
        assert all(e["ts"] <= NOW and e["text"] for e in panel["events"])
    by = panels(state)

    doing = {pid: by[pid]["doing"] for pid in PANEL_IDS}  # one plain sentence each
    assert doing["crawler"] == "Found 3 new coins in the last hour; 2,100 too young to judge yet."
    assert doing["cocoon"] == ("Last 24 h: threw out 2 coins, let 1 through. "
                               "Most common problem: top 10 wallets hold too much.")
    assert doing["radar"] == "Watching 1 open trade for danger: the creator or big holders selling."
    assert doing["judge"] == "Last 24 h: 1 yes, 1 no. Spent $0.01 of $1.00 today."
    assert doing["strategy"] == "Watching 4 coins for a 55% drop and a bounce back; closest: BBB."
    assert doing["broker"] == "1 buy and 1 sell in the last 24 h, with pretend money. Holding 1 trade."
    assert doing["risk"] == "Used 25% of today's loss allowance; 1 of 3 trade slots in use."
    assert doing["receipts"] == f"{ledger.receipt_count()} entries sealed; checked: nothing was edited."
    assert doing["upgrades"] == f"Running version {__version__} for 2 h 00 min."

    crawler = by["crawler"]
    assert crawler["headline"]["value"] == 3  # first seen within the hour
    assert stat(crawler, "Last 24 h") == 4 and stat(crawler, "Too young, waiting") == 2100
    assert stat(crawler, "Feed errors since boot") == 4
    assert crawler["events"][0]["text"].startswith("NEWEST") and crawler["events"][0]["ts"] == NOW - 120
    assert [e["ts"] for e in crawler["events"]] == sorted((e["ts"] for e in crawler["events"]), reverse=True)

    cocoon = by["cocoon"]
    assert (stat(cocoon, "Passed 1 h"), stat(cocoon, "Rejected 1 h")) == (1, 1)
    assert (stat(cocoon, "Passed 24 h"), stat(cocoon, "Rejected 24 h")) == (1, 2)
    assert stat(cocoon, "Waiting in queue") == 4
    assert [(b["label"], b["text"]) for b in cocoon["bars"]][:2] == [("Top 10 wallets hold too much", "2"),
                                                                     ("Creator can still mint more", "1")]
    assert stat(cocoon, "Newest pass") == "NEWEST"
    assert cocoon["events"][0]["text"].startswith("PASS NEWEST") and cocoon["events"][0]["tone"] == "good"
    assert cocoon["events"][1]["tone"] == "bad" and "top-10 own 45%" in cocoon["events"][1]["text"]

    radar = by["radar"]
    assert radar["headline"]["value"] == 1  # one flagged entry in 24 h
    assert stat(radar, "Scans before a buy (24 h)") == 3 and stat(radar, "Creator sold") == 1
    assert stat(radar, "Last scan") == NOW - 800 and radar["last_activity"] == NOW - 800
    flagged = [e for e in radar["events"] if e["tone"] == "bad"]
    assert len(flagged) == 1 and "DUMP" in flagged[0]["text"] and "creator sold $1,200" in flagged[0]["text"]

    judge = by["judge"]
    assert stat(judge, "Mode") == "advisory" and stat(judge, "Calls since start") == 5
    assert judge["headline"]["value"] == pytest.approx(0.012) and judge["headline"]["unit"] == "usd"
    assert [e["text"].split(" ")[0] for e in judge["events"]] == ["NO", "YES"]
    assert "creator selling" in judge["events"][0]["text"] and "70%" in judge["events"][0]["text"]

    strategy = by["strategy"]
    assert strategy["headline"]["value"] == "4 of 15"
    assert [b["label"] for b in strategy["bars"]] == ["BBB", "CCC", "AAA", "DDD"]  # closest first
    assert strategy["bars"][1]["value"] == pytest.approx(44 / 55) and strategy["bars"][3]["value"] is None
    assert stat(strategy, "Required dip") == pytest.approx(55.0)
    assert any("RISKY" in e["text"] and "risk" in e["text"] for e in strategy["events"])
    assert any(e["text"] == "SETUP JUDGED · stopped by the judge: creator selling" for e in strategy["events"])

    broker = by["broker"]
    assert broker["headline"]["value"] == 2 and stat(broker, "Fills 24 h") == "1 buy · 1 sell"
    assert stat(broker, "Last entry") == "HIGGS @ $0.002"
    assert stat(broker, "Last exit") == "HIGGS @ $0.003"
    assert stat(broker, "Network fees 24 h") == pytest.approx(0.0006)
    assert stat(broker, "Slippage haircut") == "100 bps (paper model)"
    assert broker["events"][0]["text"].startswith("SELL HIGGS") and "1.00% below quote" in broker["events"][0]["text"]

    risk = by["risk"]
    assert risk["headline"]["value"] == pytest.approx(0.95) and risk["headline"]["unit"] == "sol"
    assert stat(risk, "Equity (USD)") == pytest.approx(104.5)
    assert stat(risk, "Open positions") == "1 of 3"
    assert risk["meter"]["fraction"] == pytest.approx(0.25)  # lost 0.05 of the 0.20 SOL allowed today
    assert risk["meter"]["used"] == pytest.approx(0.05) and risk["meter"]["limit"] == pytest.approx(0.2)
    assert risk["status"] == "working"  # the equity snapshot 30 s ago
    assert any("REFUSED RISKY · Too many open trades: 3 open" == e["text"] for e in risk["events"])

    receipts = by["receipts"]
    seq, head = ledger.head()
    assert receipts["headline"]["value"] == ledger.receipt_count() == seq
    assert receipts["hash"]["head"] == head and receipts["hash"]["short"] == head[:8] + "…" + head[-8:]
    assert stat(receipts, "Verified") == "yes" and receipts["status"] == "working"
    assert receipts["events"][0]["text"].startswith(f"#{seq} ")
    assert "hindsight" in receipts["hash"]["explainer"]

    upgrades = by["upgrades"]
    assert upgrades["headline"]["value"] == f"v{__version__}"
    assert stat(upgrades, "Commit") == "0123456789ab" and stat(upgrades, "Commit message") == "feat: team room"
    assert stat(upgrades, "Uptime") == pytest.approx(7200)
    assert {e["text"].split(" ")[0] for e in upgrades["events"]} == {"Booted", "Shut"}

    assert state["bank"]["sol"] == pytest.approx(0.95) and state["bank"]["change_sol"] == pytest.approx(-0.05)
    assert state["bank"]["change_pct"] == pytest.approx(-5.0) and state["bank"]["start_sol"] == 1.0
    assert sum(state["team"].values()) == len(PANEL_IDS) and set(state["team"]) == STATUSES
    json.dumps(state, allow_nan=False)


def test_empty_ledger_says_not_available_instead_of_inventing(ledger: Ledger, settings: Settings) -> None:
    state = build_team_state(ledger, settings, NOW, deploy=deploy_info({}))
    assert [p["id"] for p in state["panels"]] == PANEL_IDS
    by = panels(state)
    for panel in state["panels"]:
        assert panel["events"] == [] and panel["last_activity"] is None
        assert panel["status"] == "waiting" and "engine has not started" in panel["why"]
    assert stat(by["crawler"], "Too young, waiting") is None  # nothing invented: JS shows "not available yet"
    assert by["strategy"]["headline"]["value"] is None and by["strategy"]["bars"] == []
    assert "not available yet" in by["strategy"]["bars_empty"]
    assert stat(by["upgrades"], "Commit") is None and stat(by["upgrades"], "Uptime") is None
    assert by["risk"]["meter"]["fraction"] is None
    assert state["bank"] == {"sol": None, "usd": None, "start_sol": None, "change_sol": None, "change_pct": None,
                             "change_usd": None}
    assert state["team"] == {"working": 0, "idle": 0, "waiting": 9, "blocked": 0}


# --------------------------------------------------------------------------- status chips


def test_status_derivation_thresholds() -> None:
    assert derive_status(NOW, NOW - 300, 300) == ("working", "")
    assert derive_status(NOW, NOW - 301, 300) == ("idle", "nothing new recently")
    assert derive_status(NOW, NOW + 2, 300) == ("working", "")  # a clock a little ahead still counts
    assert derive_status(NOW, None, 300) == ("idle", "nothing recorded yet")
    assert derive_status(NOW, None, 300, idle="no coins") == ("idle", "no coins")
    assert derive_status(NOW, NOW - 900, 300, waiting="waiting for the crawler") == ("waiting",
                                                                                     "waiting for the crawler")
    # working beats waiting/idle; blocked beats everything
    assert derive_status(NOW, NOW - 10, 300, waiting="w")[0] == "working"
    assert derive_status(NOW, NOW - 10, 300, blocked="kill switch stop") == ("blocked", "kill switch stop")


def test_engine_health_drives_every_chip(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    fresh = build_team_state(ledger, settings, NOW)
    assert panels(fresh)["crawler"]["status"] == "working"
    stale_at = NOW - 5 + ENGINE_STALE_S + 1  # heartbeat older than ENGINE_STALE_S
    stale = build_team_state(ledger, settings, stale_at)
    assert all(p["status"] == "blocked" and "engine silent" in p["why"] for p in stale["panels"])
    assert stale["team"]["blocked"] == len(PANEL_IDS)
    almost = build_team_state(ledger, settings, NOW - 5 + ENGINE_STALE_S)
    assert all("engine" not in p["why"] for p in almost["panels"])
    stopped = build_team_state(ledger, settings, NOW, engine_status=status_kv(state="stopped"))
    assert all(p["status"] == "blocked" and p["why"] == "engine stopped" for p in stopped["panels"])


def test_blocks_come_from_real_state(ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    seed(ledger)
    ledger.set_kv("engine.kill_mode", "stop")
    ledger.set_kv("risk.halted", {"halted": True, "reason": "[drawdown] -52%", "ts": NOW})
    ledger.set_kv("judge.cost_usd_day", {"day": "2026-10-08", "usd": 1.0})
    settings = make_settings(ANTHROPIC_API_KEY="sk-ant-test-key-0123456789", JUDGE_MODE="required")
    by = panels(build_team_state(ledger, settings, NOW))
    assert by["strategy"]["status"] == "blocked" and "kill switch stop" in by["strategy"]["why"]
    assert by["broker"]["status"] == "blocked" and "new buys blocked" in by["broker"]["why"]
    assert by["risk"]["status"] == "blocked" and "halted" in by["risk"]["why"]
    assert by["judge"]["status"] == "blocked" and "budget" in by["judge"]["why"]
    assert by["crawler"]["status"] == "working"  # discovery keeps running under a kill switch
    # each blocked member's one sentence says why, in plain words
    assert by["strategy"]["doing"] == "Paused by the kill switch; still watching 4 coins."
    assert by["broker"]["doing"] == ("No new buys right now: buying is halted after a big drop; sells still run. "
                                     "Holding 1 trade.")
    assert by["risk"]["doing"] == "Stopped new buys: the money fell too far from its high. It needs your reset."
    assert by["judge"]["doing"] == "Spent today's budget: says no to everything until midnight UTC."


def test_daily_loss_limit_reached_blocks_risk(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    ledger.record_equity(EquityPoint(ts=NOW - 10, equity_lamports=790_000_000, sol_usd=100.0, equity_usd=79.0,
                                     mode="paper"))
    risk = panels(build_team_state(ledger, settings, NOW))["risk"]
    assert risk["meter"]["fraction"] == pytest.approx(1.05)
    assert risk["status"] == "blocked" and "daily loss limit" in risk["why"]


def test_risk_says_flat_on_a_day_without_gain_or_loss(ledger: Ledger, settings: Settings) -> None:
    """Exactly zero today is not "up"; a gain is."""
    for ts, lamports in ((MIDNIGHT + 60, 1_000_000_000), (NOW - 30, 1_000_000_000)):
        ledger.record_equity(EquityPoint(ts=ts, equity_lamports=lamports, sol_usd=100.0,
                                         equity_usd=lamports / 1e7, mode="paper"))
    risk = panels(build_team_state(ledger, settings, NOW))["risk"]
    assert risk["doing"] == "Flat today: no gain or loss yet; 0 of 3 trade slots in use."
    assert not risk["meter"]["text"].startswith("Up")
    ledger.record_equity(EquityPoint(ts=NOW - 10, equity_lamports=1_010_000_000, sol_usd=100.0, equity_usd=101.0,
                                     mode="paper"))
    risk = panels(build_team_state(ledger, settings, NOW))["risk"]
    assert risk["doing"] == "Up today; 0 of 3 trade slots in use." and risk["meter"]["text"].startswith("Up 0.0100")


def test_a_far_future_activity_stamp_is_not_activity() -> None:
    """A millisecond epoch or a clock far ahead must not keep a member Working forever."""
    assert derive_status(NOW, NOW * 1000, 300) == ("idle", "nothing recorded yet")
    assert derive_status(NOW, NOW + 3600, 300, waiting="w") == ("waiting", "w")
    assert derive_status(NOW, NOW + 30, 300) == ("working", "")


def test_counter_changes_between_reads_count_as_activity(ledger: Ledger, settings: Settings) -> None:
    """With no candidate recorded, the crawler is 'working' only once its poll counter is seen moving."""
    ledger.set_kv("engine.heartbeat", NOW - 5)
    memory: dict[str, Any] = {}
    first = panels(build_team_state(ledger, settings, NOW, engine_status=status_kv(), memory=memory))
    assert first["crawler"]["status"] == "idle" and first["crawler"]["last_activity"] is None
    same = panels(build_team_state(ledger, settings, NOW + 10, engine_status=status_kv(), memory=memory))
    assert same["crawler"]["status"] == "idle"  # an unchanged counter proves nothing
    moved = status_kv(ts=NOW + 15, crawler={**status_kv()["crawler"], "polls": 101},
                      counters={**status_kv()["counters"], "candle_fetches": 13})
    later = panels(build_team_state(ledger, settings, NOW + 20, engine_status=moved, memory=memory))
    # it moved after the previous read (status stamp NOW - 5): dated there, never later than proven
    assert later["crawler"]["status"] == "working" and later["crawler"]["last_activity"] == NOW - 5
    assert later["strategy"]["last_activity"] == NOW - 5
    assert later["cocoon"]["last_activity"] is None  # its counter did not move


def test_a_counter_that_moved_during_a_long_gap_is_dated_to_the_previous_read(ledger: Ledger,
                                                                              settings: Settings) -> None:
    """The phone screen was off for an hour: a counter that moved since the last read moved somewhere in that
    hour, so it proves activity only since the PREVIOUS read, never "Working · 5 s ago"."""
    memory: dict[str, Any] = {}
    ledger.set_kv("engine.heartbeat", NOW - 5)
    build_team_state(ledger, settings, NOW, engine_status=status_kv(), memory=memory)
    hour = 3600.0
    ledger.set_kv("engine.heartbeat", NOW + hour - 5)
    moved = status_kv(ts=NOW + hour - 5, crawler={**status_kv()["crawler"], "polls": 220},
                      counters={**status_kv()["counters"], "candle_fetches": 70})
    after_gap = panels(build_team_state(ledger, settings, NOW + hour, engine_status=moved, memory=memory))
    for pid in ("crawler", "strategy"):
        assert after_gap[pid]["last_activity"] == NOW - 5, pid
        assert after_gap[pid]["status"] != "working", pid
    ledger.set_kv("engine.heartbeat", NOW + hour + 10)
    again = status_kv(ts=NOW + hour + 10, crawler={**status_kv()["crawler"], "polls": 221},
                      counters={**status_kv()["counters"], "candle_fetches": 71})
    steady = panels(build_team_state(ledger, settings, NOW + hour + 12, engine_status=again, memory=memory))
    assert steady["crawler"]["last_activity"] == NOW + hour - 5 and steady["crawler"]["status"] == "working"


def test_rules_only_verdicts_are_not_judge_activity(ledger: Ledger, settings: Settings) -> None:
    """JUDGE_MODE=off: the judge returns a ``source="rules"`` yes that the engine attaches to every entry. That
    is not Jev at work: no activity, no 'Working' chip, no verdict counted as an AI yes."""
    assert settings.judge_mode == "off"
    ledger.set_kv("engine.heartbeat", NOW - 5)
    rules = Verdict(decision="yes", confidence=1.0, reasons=["judge off: rules only"], model="rules",
                    latency_ms=0, cost_usd=0.0, source="rules")
    ledger.record_decision(Decision(ts=NOW - 60, mint=HIGGS, action="enter", reason="dip-rebound", symbol="HIGGS",
                                    verdict=rules))
    judge = panels(build_team_state(ledger, settings, NOW, engine_status=status_kv()))["judge"]
    assert judge["last_activity"] is None and judge["status"] == "idle"
    assert judge["why"] == "off: the rules decide alone"
    assert stat(judge, "Verdicts 24 h") == "0 yes · 0 no" and judge["events"] == []


def test_a_sell_forced_by_the_radar_is_radar_activity(ledger: Ledger, settings: Settings) -> None:
    ledger.set_kv("engine.heartbeat", NOW - 5)
    ledger.record_decision(Decision(ts=NOW - 60, mint=HIGGS, action="exit", symbol="HIGGS",
                                    reason="radar: insiders sold $900"))
    radar = panels(build_team_state(ledger, settings, NOW, engine_status=status_kv()))["radar"]
    assert radar["last_activity"] == NOW - 60 and radar["status"] == "working"
    assert radar["events"][0]["text"].startswith("SOLD HIGGS")


def test_a_manual_risk_reset_says_why(ledger: Ledger, settings: Settings, fake_clock: FakeClock) -> None:
    from nightcrawler.risk import RiskManager

    seed(ledger)
    RiskManager(settings, ledger, fake_clock).reset_halt("manual reset via CLI")
    risk = panels(build_team_state(ledger, settings, NOW))["risk"]
    assert any(e["text"] == "RESET manual reset via CLI" for e in risk["events"])


def test_the_saved_nursery_counts_its_coins(ledger: Ledger, settings: Settings) -> None:
    """The engine saves the nursery as ``{saved_at, items}`` every 10 min (redeploy-proof): that is 3 coins, not
    2 keys, and the engine's status (rewritten every 15 s) wins when it is newer."""
    ledger.set_kv("engine.heartbeat", NOW - 5)
    ledger.set_kv("crawler.nursery", {"saved_at": NOW - 60, "items": [{"mint": f"N{i}"} for i in range(3)]})
    no_count = status_kv(crawler={"polls": 100})
    crawler = panels(build_team_state(ledger, settings, NOW, engine_status=no_count))["crawler"]
    assert stat(crawler, "Too young, waiting") == 3 and "3 too young" in crawler["doing"]
    newer = panels(build_team_state(ledger, settings, NOW, engine_status=status_kv(ts=NOW - 5)))["crawler"]
    assert stat(newer, "Too young, waiting") == 2100
    older = panels(build_team_state(ledger, settings, NOW, engine_status=status_kv(ts=NOW - 120)))["crawler"]
    assert stat(older, "Too young, waiting") == 3


def test_the_saved_watchlist_is_read_in_the_engine_format_and_never_beats_a_newer_status(
        ledger: Ledger, settings: Settings) -> None:
    ledger.set_kv("engine.heartbeat", NOW - 5)
    saved = {"saved_at": NOW - 300, "items": [{"candidate": {"mint": "Z1mint", "symbol": "ZZZ"}, "added_at": NOW - 900,
                                               "last_signal_reason": "dip 50.0% < required 55.0%"}]}
    ledger.set_kv("engine.watchlist", saved)
    stale = status_kv(ts=NOW - 400)  # older than the saved list: the saved list wins
    strategy = panels(build_team_state(ledger, settings, NOW, engine_status=stale))["strategy"]
    assert [(b["label"], b["value"]) for b in strategy["bars"]] == [("ZZZ", pytest.approx(50 / 55))]
    assert strategy["headline"]["value"] == "1 of 15"
    fresh = panels(build_team_state(ledger, settings, NOW, engine_status=status_kv(ts=NOW - 5)))["strategy"]
    assert fresh["headline"]["value"] == "4 of 15" and [b["label"] for b in fresh["bars"]][0] == "BBB"


def test_dedicated_kv_keys_win_over_the_status(ledger: Ledger, settings: Settings) -> None:
    ledger.set_kv("engine.heartbeat", NOW - 5)
    ledger.set_kv("engine.status", status_kv())
    ledger.set_kv("engine.watchlist", [{"mint": "Z1", "symbol": "ZZZ", "last_signal": "dip 50.0% < required 55.0%"}])
    ledger.set_kv("crawler.nursery", {"count": 7})
    by = panels(build_team_state(ledger, settings, NOW))
    assert stat(by["crawler"], "Too young, waiting") == 7
    assert [b["label"] for b in by["strategy"]["bars"]] == ["ZZZ"] and by["strategy"]["headline"]["value"] == "1 of 15"


@pytest.mark.parametrize(("signal", "progress"), [
    ("dip 12.0% < required 55.0%", 12 / 55),
    ("dip 0.0% < required 55.0%", 0.0),
    ("buyers not back: 1 green closes < 2", 1.0),
    ("chasing: last close 3.1% below high < 27.5%", 1.0),
    ("buy/sell ratio 0.80 < 1.20", 1.0),
    ("setup, but liquidity $20,000 < $30,000", 1.0),
    ("insufficient data", None),
    ("candles stale: newest closed candle ended 4 min ago", None),
    (None, None),
])
def test_setup_proximity_is_parsed_from_the_strategy_reason(signal: str | None, progress: float | None) -> None:
    value, text = proximity(signal)
    assert value == (pytest.approx(progress) if progress is not None else None)
    assert text


# --------------------------------------------------------------------------- routes


def test_routes_without_a_token(serve: Callable[..., Client], ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    client = serve(settings, ledger)
    status, headers, body = client.request("/team")  # the old team page is part of the one page now
    assert (status, headers["Location"], body) == (302, "/", b"")
    assert headers["Cache-Control"] == "no-store" and headers["X-Frame-Options"] == "DENY"
    status, headers, body = client.request("/api/team")
    assert status == 200 and headers["Content-Type"] == "application/json"
    assert [p["id"] for p in json.loads(body)["panels"]] == PANEL_IDS
    assert client.request("/api/team/extra")[0] == 404 and client.request("/teams")[0] == 404
    for path in ("/team", "/api/team"):
        assert client.request(path, method="POST")[0] == 405


def test_token_gate_on_both_routes(serve: Callable[..., Client], ledger: Ledger,
                                   make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(DASHBOARD_TOKEN=TOKEN)
    client = serve(settings, ledger)
    for path in ("/team", "/api/team", "/team?token=wrong", "/api/team?token=" + TOKEN[:-1]):
        status, headers, body = client.request(path)
        assert status == 401 and b"Locked" in body and "Set-Cookie" not in headers
    status, headers, _ = client.request("/team?token=" + TOKEN)
    assert status == 302 and headers["Location"] == "/"
    cookie = headers["Set-Cookie"].split(";", 1)[0]
    assert TOKEN not in cookie
    assert client.request("/api/team", headers={"Cookie": cookie})[0] == 200
    assert client.request("/team", headers={"Cookie": cookie})[0] == 302
    assert client.request("/api/team?token=" + TOKEN)[0] == 200
    assert client.request("/api/team", headers={"Cookie": f"{COOKIE_NAME}=forged"})[0] == 401


def test_team_routes_are_read_only(serve: Callable[..., Client], ledger: Ledger, settings: Settings,
                                   tmp_path: Path) -> None:
    seed(ledger)
    client = serve(settings, ledger)

    def snapshot() -> list[Any]:
        conn = sqlite3.connect(tmp_path / "nc.db")
        try:
            return [conn.execute(f"SELECT * FROM {t}").fetchall()
                    for t in ("kv", "receipts", "fills", "decisions", "positions", "equity", "safety", "candidates")]
        finally:
            conn.close()

    before = snapshot()
    for path in ("/team", "/api/team", "/api/team", "/team?token=x"):
        client.request(path)
    assert snapshot() == before


def test_without_a_wired_ledger_the_team_room_reads_the_db_file(serve: Callable[..., Client],
                                                                settings: Settings) -> None:
    """``build_app`` does not pass a TeamRoom: it then opens DATA_DIR/nightcrawler.db (WAL) itself."""
    with Ledger(settings.db_path, clock=FakeClock(NOW)) as led:
        seed(led)
    client = serve(settings, None)
    status, _, body = client.request("/api/team")
    state = json.loads(body)
    assert status == 200 and panels(state)["crawler"]["events"][0]["text"].startswith("NEWEST")


def test_build_app_hands_the_engine_ledger_to_the_team_room(make_settings: Callable[..., Settings],
                                                           http_client: Any, fake_clock: FakeClock) -> None:
    from nightcrawler.engine import build_app

    app = build_app(make_settings(), fake_clock, http=http_client)
    try:
        assert app.dashboard.team._ledger is app.ledger  # one connection, not a second one to the same file
        app.ledger.set_kv("engine.heartbeat", NOW - 5)
        assert app.dashboard.team.response("/api/team", [])[0] == 200
    finally:
        app.close()


def test_the_standalone_fallback_opens_the_ledger_read_only(settings: Settings) -> None:
    """Without a wired ledger the team room reads DATA_DIR/nightcrawler.db through a READ-ONLY connection:
    it never creates the file, never migrates it and cannot write to it."""
    room = TeamRoom(settings, clock=FakeClock(NOW), environ={})
    assert room.response("/api/team", [])[0] == 500  # no ledger yet: nothing to show, nothing created
    assert not settings.db_path.exists()
    with Ledger(settings.db_path, clock=FakeClock(NOW)) as led:
        seed(led)
        conn = sqlite3.connect(settings.db_path)
        conn.execute("PRAGMA user_version=1")  # an older schema the fallback must NOT migrate
        conn.close()
        assert room.response("/api/team", [])[0] == 200
        with pytest.raises(LedgerError):
            room._ledger.set_kv("engine.heartbeat", 1.0)
        conn = sqlite3.connect(settings.db_path)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        conn.close()
    room.close()


@pytest.mark.parametrize("wired", [True, False])
def test_dashboard_restart_keeps_the_team_room_answering(ledger: Ledger, settings: Settings, wired: bool) -> None:
    """``stop()`` then ``start()`` (e.g. a restarted server) must not leave /api/team answering 500."""
    seed(ledger)
    team = TeamRoom(settings, ledger=ledger, clock=FakeClock(NOW), environ={}) if wired else None
    if not wired:
        with Ledger(settings.db_path, clock=FakeClock(NOW)) as led:
            seed(led)
    server = DashboardServer(settings, dict, host="127.0.0.1", port=0, team=team)
    try:
        server.start()
        assert Client(server).request("/api/team")[0] == 200
        server.stop()
        server.start()
        assert Client(server).request("/api/team")[0] == 200
    finally:
        server.stop()


def test_a_closed_team_room_never_reopens_its_ledger(settings: Settings) -> None:
    with Ledger(settings.db_path, clock=FakeClock(NOW)) as led:
        seed(led)
    room = TeamRoom(settings, clock=FakeClock(NOW), environ={})
    assert room.response("/api/team", [])[0] == 200 and room._ledger is not None
    room.close()
    assert room._ledger is None and room.response("/api/team", [])[0] == 500 and room._ledger is None
    room.close()  # idempotent


def test_team_state_failure_is_a_500_without_details(serve: Callable[..., Client], ledger: Ledger,
                                                    settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    client = serve(settings, ledger)

    def broken(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("db exploded at /secret/path")

    monkeypatch.setattr("nightcrawler.teamroom.build_team_state", broken)
    status, _, body = client.request("/api/team")
    assert status == 500 and json.loads(body) == {"error": "team state unavailable"}
    monkeypatch.setattr("nightcrawler.pagestate.build_page_state", broken)
    status, _, body = client.request("/api/page")
    assert status == 500 and json.loads(body) == {"error": "page state unavailable"}
    assert client.request("/team")[0] == 302 and client.request("/")[0] == 200


# --------------------------------------------------------------------------- secrets & size


def test_no_secret_ever_appears_in_team_responses(serve: Callable[..., Client], ledger: Ledger,
                                                  make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(TRADING_MODE="live", LIVE_CONFIRM=LIVE_CONFIRM_PHRASE,
                             SOLANA_RPC_URL=f"https://mainnet.helius-rpc.com/?api-key={RPC_KEY}", **SECRETS)
    leak = " " + " ".join(secret_values())
    seed(ledger, leak=leak, mode="live")
    environ = {**DEPLOY_ENV, "RAILWAY_GIT_COMMIT_MESSAGE": "fix: rotate key" + leak,
               "SOLANA_RPC_URL": f"https://x/?api-key={RPC_KEY}"}
    client = serve(settings, ledger, environ=environ)
    responses = [client.request(path, headers=headers) for path, headers in [
        ("/team", None), ("/api/team", None), (f"/team?token={TOKEN}", None), (f"/api/team?token={TOKEN}", None),
        ("/api/team", {"Cookie": f"{COOKIE_NAME}={TOKEN}"})]]
    state = json.loads(responses[3][2])
    assert state["mode"] == "LIVE"
    by = panels(state)
    assert "[REDACTED]" in stat(by["upgrades"], "Commit message")
    assert any("[REDACTED]" in e["text"] for e in by["judge"]["events"])
    for status, headers, body in responses:
        blob = body.decode("utf-8") + "\n" + "\n".join(f"{k}: {v}" for k, v in headers.items())
        for secret in [*secret_values(), DEPLOY_ENV["SOME_OTHER_VAR"]]:
            assert secret not in blob, (status, secret)
            # texts are clipped AFTER redaction, so not even the start or end of a secret survives a clip
            assert secret[:16] not in blob and secret[-16:] not in blob, (status, secret)
        assert "helius-rpc.com" not in blob


def test_deploy_info_reads_only_the_two_railway_variables() -> None:
    info = deploy_info(DEPLOY_ENV)
    assert info == {"commit": "0123456789ab", "message": "feat: team room"}
    assert deploy_info({}) == {"commit": None, "message": None}
    assert deploy_info({"RAILWAY_GIT_COMMIT_MESSAGE": "x" * 500})["message"] == "x" * 119 + "…"


def test_json_stays_small_on_a_busy_ledger(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    for i in range(300):
        ledger.record_candidate(TokenCandidate(mint=f"BULK{i}", symbol=f"B{i}" + "x" * 40, discovered_at=NOW - i,
                                               sources=["jupiter_recent"] * 5))
        ledger.record_decision(Decision(ts=NOW - i, mint=f"BULK{i}",
                                        action="reject_cocoon" if i % 2 else "reject_risk",
                                        reason="[top10] " + "very long reason " * 40, symbol=f"B{i}"))
    watching = [{"mint": f"W{i}", "symbol": f"W{i}", "last_signal": f"dip {i % 50}.0% < required 55.0%"}
                for i in range(100)]
    state = build_team_state(ledger, settings, NOW, engine_status=status_kv(watchlist=100, watching=watching))
    body = json.dumps(state, separators=(",", ":"))
    assert len(body) < 16_000, len(body)
    for panel in state["panels"]:
        assert len(panel["events"]) <= EVENTS_MAX and len(panel.get("bars", [])) <= 5
        assert all(len(e["text"]) <= 160 for e in panel["events"])
    assert panels(state)["crawler"]["headline"]["value"] == 303
