"""Dashboard: routes, auth gate, state schema, read-only, CSP, and never a secret in any response."""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import logging
import re
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeClock

from nightcrawler.config import LIVE_CONFIRM_PHRASE, Settings
from nightcrawler.dashboard import (
    CONTENT_SECURITY_POLICY,
    COOKIE_NAME,
    VERIFY_EVERY_S,
    DashboardServer,
    build_state,
    render_html,
    rule_id,
)
from nightcrawler.ledger import Ledger
from nightcrawler.models import (
    Decision,
    EquityPoint,
    Fill,
    Position,
    SafetyReport,
    TokenCandidate,
    Verdict,
)

NOW = 1_791_475_200.0  # 2026-10-08T16:00:00Z
MIDNIGHT = NOW - NOW % 86_400
HIGGS = "HiGGSmintAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
WALLET = "BotWa11etPubkey1111111111111111111111111111"
SECRETS = {
    "ANTHROPIC_API_KEY": "sk-ant-api03-TOPSECRETanthropicKEY0123456789",
    "JUPITER_API_KEY": "jup-secret-key-5f4dcc3b5aa765d61d8327deb882cf99",
    "BOT_WALLET_SECRET": "4wBqpZM9xaSheZzJSMawUKKwhdpChKbZ5eu5ky4Vigw1t7Wv5jNzqJmsRcFVw8NhpWxnJ8u5fE3ygVJgLFrTTXpo",
    "X_BEARER_TOKEN": "x-bearer-AAAAAAAAAAAAAAAAAAAAAMLheAAAAAAA0%2BuSeid",
    "DASHBOARD_TOKEN": "dash-token-correct-horse-battery-staple",
}
RPC_KEY = "helius-rpc-key-0a1b2c3d4e5f"
TOKEN = SECRETS["DASHBOARD_TOKEN"]

STATE_KEYS = {"version", "generated_at", "mode", "kill", "halted", "engine", "equity", "positions", "fills",
              "decisions", "rejections", "receipts", "judge", "wallet", "cocoon_rules", "activity", "limits"}
EQUITY_KEYS = {"sol", "usd", "sol_usd", "start_usd", "pnl_today_usd", "pnl_today_sol", "pnl_total_usd",
               "pnl_total_sol", "curve"}
POSITION_KEYS = {"id", "mint", "symbol", "opened_at", "entry_price_usd", "last_price_usd", "value_sol",
                 "unrealized_pnl_sol", "unrealized_pnl_pct", "partial_taken", "cost_sol"}
RECEIPT_KEYS = {"head_hash", "seq", "count", "verified", "first_bad_seq", "verified_at"}
JUDGE_KEYS = {"mode", "model", "calls", "cost_usd_total", "cost_usd_today"}


# --------------------------------------------------------------------------- fixtures & helpers


@pytest.fixture
def ledger(tmp_path: Path, fake_clock: FakeClock) -> Ledger:
    with Ledger(tmp_path / "nc.db", clock=fake_clock) as led:
        yield led


@pytest.fixture
def secret_settings(make_settings: Callable[..., Settings]) -> Settings:
    """Live settings carrying every kind of secret (and an RPC URL with an api key)."""
    return make_settings(TRADING_MODE="live", LIVE_CONFIRM=LIVE_CONFIRM_PHRASE,
                         SOLANA_RPC_URL=f"https://mainnet.helius-rpc.com/?api-key={RPC_KEY}", **SECRETS)


def secret_values() -> list[str]:
    return [*SECRETS.values(), RPC_KEY]


def populate(ledger: Ledger, leak: str = "") -> None:
    """A realistic day: equity snapshots, one closed and one open trade, decisions, safety rejections.

    ``leak`` is appended to free-text fields to prove secrets get scrubbed from responses.
    """
    ledger.set_kv("paper.start_lamports", 500_000_000)
    ledger.set_kv("paper.start_sol_usd", 200.0)
    ledger.set_kv("live.start_lamports", 500_000_000)
    ledger.set_kv("live.start_sol_usd", 200.0)
    for mode in ("paper", "live"):
        for ts, lamports, sol_usd in ((MIDNIGHT - 600, 490_000_000, 200.0), (MIDNIGHT + 60, 495_000_000, 200.0),
                                      (NOW - 60, 520_000_000, 210.0)):
            ledger.record_equity(EquityPoint(ts=ts, equity_lamports=lamports, sol_usd=sol_usd,
                                             equity_usd=lamports / 1e9 * sol_usd, mode=mode))
    ledger.record_fill(Fill(id="f1", mode="paper", side="buy", mint=HIGGS, sol_lamports=100_000_000,
                            token_amount=5_000_000_000, token_decimals=6, price_usd=0.004, sol_usd=200.0,
                            fees_lamports=300_000, platform_fee_bps=10, price_impact_pct=1.5, signature=None,
                            request_id="r1", ts=NOW - 3000, symbol="HIGGS" + leak))
    ledger.upsert_position(Position(id="p1", mint=HIGGS, symbol="HIGGS" + leak, pool="pool", opened_at=NOW - 3000,
                                    token_decimals=6, entry_fill_ids=["f1"], token_amount=5_000_000_000,
                                    initial_token_amount=5_000_000_000, cost_lamports=100_000_000,
                                    fees_lamports=300_000, rent_lamports=2_039_280, entry_price_usd=0.004,
                                    peak_price_usd=0.006, last_price_usd=0.0052))
    verdict = Verdict(decision="no", confidence=0.7, reasons=["creator selling" + leak], model="claude-opus-5-5",
                      latency_ms=800, cost_usd=0.003, source="claude")
    ledger.record_decision(Decision(ts=NOW - 500, mint=HIGGS, action="reject_judge", reason="judge no" + leak,
                                    verdict=verdict))
    ledger.record_decision(Decision(ts=NOW - 400, mint="M2", action="reject_cocoon", reason="[top10] 45%" + leak))
    ledger.record_decision(Decision(ts=NOW - 2 * 86_400, mint="M3", action="reject_cocoon", reason="old"))
    for mint, reasons in (("M2", ["[top10] top-10 own 45%", "[mint_authority] not renounced"]),
                          ("M3", ["[top10] top-10 own 60%"]), ("M4", ["source unavailable: rugcheck (not ready)"])):
        ledger.record_safety(SafetyReport(mint=mint, passed=False, hard_fail_reasons=reasons, checked_at=NOW - 100))
    ledger.record_candidate(TokenCandidate(mint="M2", discovered_at=NOW - 200))
    ledger.set_kv("engine.heartbeat", NOW - 5)
    ledger.set_kv("engine.started_at", NOW - 7200)
    ledger.set_kv("engine.status", {"watchlist": 3, "note": "ok" + leak})
    ledger.set_kv("engine.last_error", {"stage": "watch", "error": "HttpError 429" + leak})
    ledger.set_kv("judge.calls", 12)
    ledger.set_kv("judge.cost_usd_total", 0.41)
    ledger.set_kv("judge.cost_usd_day", {"day": "2026-10-08", "usd": 0.03})
    ledger.set_kv("wallet.pubkey", WALLET)


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
def serve() -> Callable[..., Client]:
    servers: list[DashboardServer] = []

    def _serve(settings: Settings, provider: Callable[[], dict[str, Any]]) -> Client:
        server = DashboardServer(settings, provider, host="127.0.0.1", port=0)
        server.start()
        servers.append(server)
        return Client(server)

    yield _serve
    for server in servers:
        server.stop()


def provider_for(ledger: Ledger, settings: Settings) -> Callable[[], dict[str, Any]]:
    cache: dict[str, Any] = {}
    return lambda: build_state(ledger, settings, NOW, cache)


# --------------------------------------------------------------------------- routes


def test_routes_without_token(serve: Callable[..., Client], ledger: Ledger, settings: Settings) -> None:
    populate(ledger)
    client = serve(settings, provider_for(ledger, settings))
    status, headers, body = client.request("/healthz")
    assert (status, body) == (200, b"ok") and headers["Content-Type"].startswith("text/plain")
    status, headers, body = client.request("/api/state")
    assert status == 200 and headers["Content-Type"] == "application/json"
    assert headers["Cache-Control"] == "no-store"
    state = json.loads(body)
    assert set(state) == STATE_KEYS and state["mode"] == "PAPER"
    status, headers, body = client.request("/")
    assert status == 200 and headers["Content-Type"] == "text/html; charset=utf-8"
    assert headers["Content-Security-Policy"] == CONTENT_SECURITY_POLICY
    assert headers["X-Frame-Options"] == "DENY" and headers["X-Content-Type-Options"] == "nosniff"
    assert b"PAPER" in body and "Set-Cookie" not in headers
    assert client.request("/nope")[0] == 404
    assert client.request("/api/state/extra")[0] == 404


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
def test_everything_but_get_is_refused(serve: Callable[..., Client], ledger: Ledger, settings: Settings,
                                       method: str) -> None:
    client = serve(settings, provider_for(ledger, settings))
    for path in ("/", "/api/state", "/healthz"):
        status, headers, _ = client.request(path, method=method)
        assert status == 405 and headers["Allow"] == "GET"


def test_dashboard_is_read_only(serve: Callable[..., Client], ledger: Ledger, settings: Settings,
                                tmp_path: Path) -> None:
    populate(ledger)
    client = serve(settings, provider_for(ledger, settings))
    db = tmp_path / "nc.db"

    def snapshot() -> list[Any]:
        conn = sqlite3.connect(db)
        try:
            return [conn.execute(f"SELECT * FROM {t}").fetchall()
                    for t in ("kv", "receipts", "fills", "decisions", "positions", "equity", "safety", "candidates")]
        finally:
            conn.close()

    before = snapshot()
    for path in ("/", "/api/state", "/healthz", "/api/state?token=x"):
        client.request(path)
    for method in ("POST", "PUT", "DELETE"):
        client.request("/api/state", method=method)
    assert snapshot() == before


# --------------------------------------------------------------------------- auth


def test_token_gate(serve: Callable[..., Client], ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(DASHBOARD_TOKEN=TOKEN)
    client = serve(settings, provider_for(ledger, settings))
    assert client.request("/healthz")[0] == 200  # Railway's health check needs no token
    for path in ("/", "/api/state", "/?token=wrong", "/api/state?token=" + TOKEN[:-1]):
        status, headers, body = client.request(path)
        assert status == 401 and b"Locked" in body and "Set-Cookie" not in headers
    status, headers, _ = client.request("/?token=" + TOKEN)
    assert status == 200
    cookie = headers["Set-Cookie"]
    assert cookie.startswith(f"{COOKIE_NAME}=") and TOKEN not in cookie
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Secure" not in cookie
    value = cookie.split(";", 1)[0].split("=", 1)[1]
    assert client.request("/api/state", headers={"Cookie": f"{COOKIE_NAME}={value}"})[0] == 200
    assert client.request("/", headers={"Cookie": f"other=1; {COOKIE_NAME}={value}"})[0] == 200
    assert client.request("/api/state", headers={"Cookie": f"{COOKIE_NAME}={TOKEN}"})[0] == 200
    assert client.request("/api/state", headers={"Cookie": f"{COOKIE_NAME}=forged"})[0] == 401
    assert client.request("/api/state", headers={"Cookie": "garbage;;=\x7f"})[0] == 401
    _, headers, _ = client.request("/api/state?token=" + TOKEN, headers={"X-Forwarded-Proto": "https"})
    assert "Secure" in headers["Set-Cookie"]


# --------------------------------------------------------------------------- secrets


def test_no_secret_ever_appears_in_any_response(serve: Callable[..., Client], ledger: Ledger,
                                                secret_settings: Settings, caplog: pytest.LogCaptureFixture) -> None:
    leak = " " + " ".join(secret_values())  # the engine accidentally stored secrets in free text
    populate(ledger, leak=leak)
    client = serve(secret_settings, provider_for(ledger, secret_settings))
    caplog.set_level(logging.DEBUG, logger="nightcrawler")
    responses = [client.request(path, method=method, headers=headers) for path, method, headers in [
        ("/healthz", "GET", None), ("/", "GET", None), ("/api/state", "GET", None),
        (f"/?token={TOKEN}", "GET", None), (f"/api/state?token={TOKEN}", "GET", None),
        ("/api/state", "GET", {"Cookie": f"{COOKIE_NAME}={TOKEN}"}), ("/missing", "GET", None),
        (f"/api/state?token={TOKEN}", "POST", None)]]
    state = json.loads(responses[4][2])
    assert state["mode"] == "LIVE" and state["wallet"]["address"] == WALLET
    assert "[REDACTED]" in state["engine"]["last_error"] and "[REDACTED]" in state["positions"][0]["symbol"]
    for status, headers, body in responses:
        blob = body.decode("utf-8") + "\n" + "\n".join(f"{k}: {v}" for k, v in headers.items())
        for secret in secret_values():
            assert secret not in blob, (status, secret)
    for secret in secret_values():
        assert secret not in caplog.text  # request logs drop the query string


def test_render_html_has_no_secrets_and_no_external_assets(secret_settings: Settings) -> None:
    html = render_html(secret_settings)
    for secret in secret_values():
        assert secret not in html
    assert not re.search(r"""(?:src|href)\s*=\s*["']?(?:https?:)?//""", html)
    assert "@import" not in html and "url(" not in html
    assert set(re.findall(r"https?://[^\s\"'<>]+", html)) == {"http://www.w3.org/2000/svg"}  # SVG namespace only
    assert ">LIVE<" in html


def test_csp_hashes_match_the_inline_script_and_style(settings: Settings) -> None:
    """If these drift apart the browser silently refuses to run the page."""
    html = render_html(settings)
    (script,) = re.findall(r"<script>(.*?)</script>", html, flags=re.DOTALL)
    (style,) = re.findall(r"<style>(.*?)</style>", html, flags=re.DOTALL)

    def source(text: str) -> str:
        return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"

    assert f"script-src {source(script)};" in CONTENT_SECURITY_POLICY
    assert f"style-src {source(style)};" in CONTENT_SECURITY_POLICY
    assert "default-src 'none'" in CONTENT_SECURITY_POLICY and "connect-src 'self'" in CONTENT_SECURITY_POLICY
    assert "unsafe-inline" not in CONTENT_SECURITY_POLICY and "unsafe-eval" not in CONTENT_SECURITY_POLICY


def test_page_is_built_for_phones(settings: Settings) -> None:
    html = render_html(settings)
    assert 'name="viewport"' in html and "width=device-width" in html
    assert "prefers-color-scheme:dark" in html and "body{margin:0;background:var(--page)" in html
    assert 'data-refresh="15"' in html and ">PAPER<" in html
    assert "What is this?" in html and "innerHTML" not in html  # untrusted text goes in via textContent only


# --------------------------------------------------------------------------- state


def test_state_schema_on_an_empty_ledger(ledger: Ledger, settings: Settings) -> None:
    state = build_state(ledger, settings, NOW)
    assert set(state) == STATE_KEYS
    assert set(state["equity"]) == EQUITY_KEYS and state["equity"]["curve"] == []
    assert all(state["equity"][k] is None for k in EQUITY_KEYS - {"curve"})
    assert set(state["receipts"]) == RECEIPT_KEYS
    assert state["receipts"]["count"] == 0 and state["receipts"]["verified"] is True
    assert set(state["judge"]) == JUDGE_KEYS and state["judge"]["calls"] == 0
    assert state["engine"] == {"heartbeat": None, "started_at": None, "status": None, "last_error": None}
    assert state["halted"] == {"halted": False, "reason": None}
    assert state["kill"] == "off" and state["wallet"] == {"address": None}
    assert state["positions"] == state["fills"] == state["decisions"] == []
    assert state["rejections"] == state["cocoon_rules"] == {} and state["activity"] == {"candidates_24h": 0}
    json.dumps(state, allow_nan=False)


def test_state_numbers(ledger: Ledger, settings: Settings) -> None:
    populate(ledger)
    state = build_state(ledger, settings, NOW)
    eq = state["equity"]
    assert eq["sol"] == pytest.approx(0.52) and eq["usd"] == pytest.approx(0.52 * 210)
    assert eq["sol_usd"] == 210.0 and eq["start_usd"] == pytest.approx(100.0)
    assert eq["pnl_today_sol"] == pytest.approx(0.025)  # vs the first snapshot after UTC midnight
    assert eq["pnl_today_usd"] == pytest.approx(0.52 * 210 - 0.495 * 200)
    assert eq["pnl_total_sol"] == pytest.approx(0.02) and eq["pnl_total_usd"] == pytest.approx(0.52 * 210 - 100)
    assert [p[0] for p in eq["curve"]] == [MIDNIGHT - 600, MIDNIGHT + 60, NOW - 60]
    (pos,) = state["positions"]
    assert set(pos) == POSITION_KEYS
    value = 5_000 * 0.0052 / 210  # 5,000 whole tokens at $0.0052, in SOL
    assert pos["value_sol"] == pytest.approx(value, rel=1e-6)
    assert pos["unrealized_pnl_sol"] == pytest.approx(value - 0.1 - 0.0003 - 0.00203928, rel=1e-6)
    assert pos["unrealized_pnl_pct"] == pytest.approx(pos["unrealized_pnl_sol"] / 0.1 * 100)
    assert state["fills"][0]["sol"] == 0.1 and state["fills"][0]["id"] == "f1"
    assert [d["action"] for d in state["decisions"]] == ["reject_cocoon", "reject_judge", "reject_cocoon"]
    assert state["decisions"][1]["verdict"]["reasons"] == ["creator selling"]
    assert state["rejections"] == {"reject_cocoon": 1, "reject_judge": 1}  # last 24 h only
    assert state["cocoon_rules"] == {"top10": 2, "mint_authority": 1, "source_unavailable": 1}
    assert state["activity"] == {"candidates_24h": 1}
    assert state["engine"]["heartbeat"] == NOW - 5 and state["engine"]["status"]["watchlist"] == 3
    assert "HttpError 429" in state["engine"]["last_error"]
    assert state["judge"] == {"mode": "off", "model": "claude-opus-5-5", "calls": 12, "cost_usd_total": 0.41,
                              "cost_usd_today": 0.03}
    assert state["wallet"] == {"address": None}  # paper: never show an address
    assert state["receipts"]["seq"] == state["receipts"]["count"] == 4


def test_kill_halt_and_stale_judge_day(ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(KILL_SWITCH="stop")
    assert build_state(ledger, settings, NOW)["kill"] == "stop"
    ledger.set_kv("engine.kill_mode", "sell_all")
    ledger.set_kv("risk.halted", {"halted": True, "reason": "[drawdown] -52%", "ts": NOW})
    ledger.set_kv("judge.cost_usd_day", {"day": "2026-10-07", "usd": 0.5})
    state = build_state(ledger, settings, NOW)
    assert state["kill"] == "sell_all"
    assert state["halted"] == {"halted": True, "reason": "[drawdown] -52%"}
    assert state["judge"]["cost_usd_today"] == 0.0


def test_non_finite_numbers_become_null(ledger: Ledger, settings: Settings) -> None:
    ledger.set_kv("engine.status", {"ratio": float("nan"), "big": float("inf")})
    state = build_state(ledger, settings, NOW)
    assert state["engine"]["status"] == {"ratio": None, "big": None}
    json.dumps(state, allow_nan=False)


def test_chain_verification_is_throttled_and_catches_tampering(ledger: Ledger, settings: Settings,
                                                                tmp_path: Path) -> None:
    populate(ledger)
    cache: dict[str, Any] = {}
    first = build_state(ledger, settings, NOW, cache)["receipts"]
    assert (first["verified"], first["verified_at"]) == (True, NOW)
    conn = sqlite3.connect(tmp_path / "nc.db")
    with conn:
        conn.execute("UPDATE receipts SET payload = replace(payload, 'judge no', 'judge yes') WHERE seq = 2")
    conn.close()
    cached = build_state(ledger, settings, NOW + VERIFY_EVERY_S - 1, cache)["receipts"]
    assert cached["verified"] is True and cached["verified_at"] == NOW
    fresh = build_state(ledger, settings, NOW + VERIFY_EVERY_S, cache)["receipts"]
    assert (fresh["verified"], fresh["first_bad_seq"]) == (False, 2)


def test_rule_ids() -> None:
    assert rule_id("[lp_unlocked] only 0% of LP locked") == "lp_unlocked"
    assert rule_id("source unavailable: rpc (mint account not found)") == "source_unavailable"
    assert rule_id("something else") == "other"


# --------------------------------------------------------------------------- server lifecycle


def test_provider_failure_returns_500_without_details(serve: Callable[..., Client], settings: Settings) -> None:
    def broken() -> dict[str, Any]:
        raise RuntimeError("db exploded at /secret/path")

    client = serve(settings, broken)
    status, _, body = client.request("/api/state")
    assert status == 500 and json.loads(body) == {"error": "state unavailable"}
    assert client.request("/healthz")[0] == 200


def test_server_lifecycle(settings: Settings) -> None:
    server = DashboardServer(settings, dict, host="127.0.0.1", port=0)
    with pytest.raises(RuntimeError):
        _ = server.bound_port
    thread = server.start()
    assert server.start() is thread and thread.daemon
    assert Client(server).request("/healthz")[0] == 200
    server.stop()
    server.stop()  # idempotent
    assert not thread.is_alive()
