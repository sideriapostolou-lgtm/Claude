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
              "decisions", "rejections", "receipts", "judge", "wallet", "cocoon_rules", "activity", "limits", "usage",
              "safe_mode"}
USAGE_KEYS = {"day", "month", "warn_pct", "updated_at", "providers"}
USAGE_ROW_KEYS = {"id", "label", "unit", "period", "calls_today", "calls_month", "used", "budget", "used_pct", "level",
                  "tokens_today", "tokens_month", "cost_usd_today", "cost_usd_month"}
EQUITY_KEYS = {"sol", "usd", "sol_usd", "start_usd", "pnl_today_usd", "pnl_today_sol", "pnl_total_usd",
               "pnl_total_sol", "pnl_total_trading_usd", "sol_price_effect_usd", "curve"}
POSITION_KEYS = {"id", "mint", "symbol", "opened_at", "entry_price_usd", "last_price_usd", "value_sol",
                 "unrealized_pnl_sol", "unrealized_pnl_pct", "partial_taken", "cost_sol", "foreign_wallet"}
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


def populate(ledger: Ledger, leak: str = "", mode: str = "paper") -> None:
    """A realistic day: equity snapshots, one closed and one open trade, decisions, safety rejections.

    ``leak`` is appended to free-text fields to prove secrets get scrubbed from responses. ``mode``
    is the wallet the open position is in (a dashboard lists only its own mode's positions).
    """
    ledger.set_kv("paper.start_lamports", 500_000_000)
    ledger.set_kv("paper.start_sol_usd", 200.0)
    ledger.set_kv("live.start_lamports", 500_000_000)
    ledger.set_kv("live.start_sol_usd", 200.0)
    for curve_mode in ("paper", "live"):
        for ts, lamports, sol_usd in ((MIDNIGHT - 600, 490_000_000, 200.0), (MIDNIGHT + 60, 495_000_000, 200.0),
                                      (NOW - 60, 520_000_000, 210.0)):
            ledger.record_equity(EquityPoint(ts=ts, equity_lamports=lamports, sol_usd=sol_usd,
                                             equity_usd=lamports / 1e9 * sol_usd, mode=curve_mode))
    ledger.record_fill(Fill(id="f1", mode=mode, side="buy", mint=HIGGS, sol_lamports=100_000_000,
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
    populate(ledger, leak=leak, mode="live")
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


def _counts(day: str, day_counts: dict[str, Any], month: str, month_counts: dict[str, Any]) -> dict[str, Any]:
    return {"day": day, "day_counts": day_counts, "month": month, "month_counts": month_counts,
            "updated_at": NOW - 30}


def test_usage_panel_on_an_empty_ledger(ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    usage = build_state(ledger, make_settings(), NOW)["usage"]
    assert set(usage) == USAGE_KEYS and (usage["day"], usage["month"]) == ("2026-10-08", "2026-10")
    assert usage["warn_pct"] == 80.0 and usage["updated_at"] is None
    rows = usage["providers"]
    assert [r["id"] for r in rows] == ["solana_rpc", "jupiter", "geckoterminal", "dexscreener", "rugcheck", "anthropic"]
    assert all(set(r) == USAGE_ROW_KEYS and r["calls_today"] == r["calls_month"] == 0 for r in rows)
    rpc, anthropic = rows[0], rows[-1]
    assert (rpc["label"], rpc["unit"], rpc["budget"], rpc["used_pct"], rpc["level"]) == (
        "Solana RPC", "calls", None, None, None)  # the public RPC has no monthly budget
    assert (anthropic["unit"], anthropic["period"], anthropic["budget"], anthropic["used"]) == ("usd", "day", 1.0, 0.0)
    assert (anthropic["used_pct"], anthropic["level"]) == (0.0, "ok")
    blocked = build_state(ledger, make_settings(JUDGE_MAX_DAILY_USD=0), NOW)["usage"]["providers"][-1]
    assert (blocked["budget"], blocked["used_pct"], blocked["level"]) == (0.0, None, None)  # cap 0 = judge blocked


def test_usage_panel_shows_each_provider_against_its_budget(ledger: Ledger,
                                                            make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(SOLANA_RPC_URL=f"https://mainnet.helius-rpc.com/?api-key={RPC_KEY}",
                             USAGE_HELIUS_MONTHLY_CREDITS=1000, USAGE_JUPITER_MONTHLY_CALLS=100,
                             JUDGE_MAX_DAILY_USD=0.5)
    assert make_settings().usage_helius_monthly_credits == 1_000_000  # the Helius free plan
    ledger.set_kv("usage.providers", {
        "helius": _counts("2026-10-08", {"calls": 40, "credits": 40}, "2026-10", {"calls": 850, "credits": 850}),
        "jupiter": _counts("2026-10-07", {"calls": 70}, "2026-10", {"calls": 120}),  # nothing yet today
        "geckoterminal": _counts("2026-09-30", {"calls": 9}, "2026-09", {"calls": 9000}),  # last month's
        "anthropic": _counts("2026-10-08", {"calls": 3, "input_tokens": 6000, "output_tokens": 300, "cost_usd": 0.45},
                             "2026-10", {"calls": 30, "input_tokens": 60000, "output_tokens": 3000, "cost_usd": 0.6}),
        "pumpfun": _counts("2026-10-08", {"calls": 2}, "2026-10", {"calls": 2}),
        f"leak {RPC_KEY}": _counts("2026-10-08", {"calls": 1}, "2026-10", {"calls": 1}),  # unknown ids: ignored
    })
    ledger.set_kv("judge.cost_usd_day", {"day": "2026-10-08", "usd": 0.45})
    state = build_state(ledger, settings, NOW)
    usage = state["usage"]
    assert usage["updated_at"] == NOW - 30
    rows = {r["id"]: r for r in usage["providers"]}
    assert list(rows) == ["helius", "jupiter", "geckoterminal", "dexscreener", "rugcheck", "anthropic", "pumpfun"]
    none = dict.fromkeys(("tokens_today", "tokens_month", "cost_usd_today", "cost_usd_month"))
    assert rows["helius"] == {"id": "helius", "label": "Helius", "unit": "credits", "period": "month",
                              "calls_today": 40, "calls_month": 850, "used": 850, "budget": 1000,
                              "used_pct": 85.0, "level": "warn", **none}
    assert rows["jupiter"] == {"id": "jupiter", "label": "Jupiter", "unit": "calls", "period": "month",
                               "calls_today": 0, "calls_month": 120, "used": 120, "budget": 100,
                               "used_pct": 120.0, "level": "over", **none}
    assert (rows["geckoterminal"]["calls_today"], rows["geckoterminal"]["calls_month"]) == (0, 0)
    assert rows["geckoterminal"]["budget"] is None and rows["geckoterminal"]["level"] is None
    assert rows["anthropic"] == {"id": "anthropic", "label": "Anthropic", "unit": "usd", "period": "day",
                                 "calls_today": 3, "calls_month": 30, "used": 0.45, "budget": 0.5,
                                 "used_pct": pytest.approx(90.0), "level": "warn", "tokens_today": 6300,
                                 "tokens_month": 63000, "cost_usd_today": 0.45, "cost_usd_month": 0.6}
    assert rows["pumpfun"]["calls_today"] == 2 and rows["pumpfun"]["budget"] is None
    blob = json.dumps(state)
    assert RPC_KEY not in blob and "helius-rpc.com" not in blob  # provider names, never URLs


def test_usage_budget_of_the_judge_is_what_the_judge_enforces(ledger: Ledger,
                                                              make_settings: Callable[..., Settings]) -> None:
    """Without per-call usage (judge hook not wired yet) the daily spend still comes from the judge's kv."""
    ledger.set_kv("judge.cost_usd_day", {"day": "2026-10-08", "usd": 0.85})
    anthropic = build_state(ledger, make_settings(), NOW)["usage"]["providers"][-1]
    assert (anthropic["used"], anthropic["used_pct"], anthropic["level"]) == (0.85, pytest.approx(85.0), "warn")
    ledger.set_kv("judge.cost_usd_day", {"day": "2026-10-07", "usd": 5.0})  # yesterday's spend is over
    anthropic = build_state(ledger, make_settings(), NOW)["usage"]["providers"][-1]
    assert (anthropic["used"], anthropic["level"]) == (0.0, "ok")


def test_usage_card_and_budget_chips_are_on_the_page(settings: Settings) -> None:
    from nightcrawler.dashboard import _SCRIPT

    assert '<section class="card" id="usage">' in render_html(settings)
    assert "renderUsage(s.usage)" in _SCRIPT
    assert "of its " in _SCRIPT and "over its " in _SCRIPT  # chips: "<provider> at 85% of its monthly budget"


def test_missing_optional_parts_never_render_as_the_word_null() -> None:
    """``node.replaceChildren(null)`` inserts the TEXT "null" (it showed under Details whenever there was
    no engine error, and under the skip reasons): every card is filled through one helper that drops them."""
    from nightcrawler.dashboard import _SCRIPT

    assert _SCRIPT.count(".replaceChildren(") == 1 and "function put(node, ...kids)" in _SCRIPT


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


# --------------------------------------------------------------------------- review fixes


def test_since_start_is_measured_in_sol_not_moved_by_the_sol_price(ledger: Ledger, settings: Settings) -> None:
    """A bot that LOST 3 % in SOL while SOL/USD rose 12 % must not show a green "since start"."""
    from nightcrawler.dashboard import _SCRIPT

    start = 923_190_546  # $100 at $108.32/SOL
    ledger.set_kv("paper.start_lamports", start)
    ledger.set_kv("paper.start_sol_usd", 108.32)
    now_lamports = int(start * 0.97)
    ledger.record_equity(EquityPoint(ts=NOW - 60, equity_lamports=now_lamports, sol_usd=121.32,
                                     equity_usd=now_lamports / 1e9 * 121.32, mode="paper"))
    eq = build_state(ledger, settings, NOW)["equity"]
    assert eq["pnl_total_usd"] > 0 > eq["pnl_total_sol"]  # the USD figure is mostly the SOL price
    assert eq["pnl_total_trading_usd"] == pytest.approx(eq["pnl_total_sol"] * 121.32)
    assert eq["pnl_total_trading_usd"] < 0 < eq["sol_price_effect_usd"]
    assert eq["pnl_total_trading_usd"] + eq["sol_price_effect_usd"] == pytest.approx(eq["pnl_total_usd"])
    # the tiles' headline value and colour come from the SOL figures (the unit the risk limits use)
    assert 'tile("Since start", sol(e.pnl_total_sol, true)' in _SCRIPT and "tone(e.pnl_total_sol)" in _SCRIPT
    assert 'tile("Today", sol(e.pnl_today_sol, true)' in _SCRIPT and "tone(e.pnl_today_sol)" in _SCRIPT


def test_live_dashboard_lists_only_live_positions_and_shows_drift(ledger: Ledger,
                                                                  make_settings: Callable[..., Settings]) -> None:
    from nightcrawler.dashboard import _SCRIPT

    populate(ledger)  # p1 is a PAPER position
    live = make_settings(TRADING_MODE="live", LIVE_CONFIRM=LIVE_CONFIRM_PHRASE, BOT_WALLET_SECRET="x" * 88,
                         DASHBOARD_HOST="127.0.0.1")
    assert build_state(ledger, live, NOW)["positions"] == []
    assert [p["id"] for p in build_state(ledger, make_settings(), NOW)["positions"]] == ["p1"]
    assert "status.drift" in _SCRIPT  # a non-empty drift turns into a red chip


def test_safe_mode_banner_and_foreign_wallet_positions(ledger: Ledger,
                                                       make_settings: Callable[..., Settings]) -> None:
    """RT-9 / F3: the exits-only safe mode and live positions of ANOTHER wallet (never sold or counted
    by this bot) are shown from the ledger alone: a red chip, and foreign positions marked apart."""
    from nightcrawler.dashboard import _SCRIPT

    populate(ledger, mode="live")  # p1: a live position of the current wallet
    other = "OtherWa11et111111111111111111111111111111111"
    ledger.record_fill(Fill(id="f9", mode="live", side="buy", mint=HIGGS, sol_lamports=50_000_000,
                            token_amount=1_000_000, token_decimals=6, price_usd=0.004, sol_usd=200.0, fees_lamports=0,
                            platform_fee_bps=10, price_impact_pct=0.5, signature=None, request_id="r9",
                            ts=NOW - 9000, symbol="OLD"))
    ledger.upsert_position(Position(id="p9", mint=HIGGS, symbol="OLD", pool="pool", opened_at=NOW - 9000,
                                    token_decimals=6, entry_fill_ids=["f9"], token_amount=1_000_000,
                                    initial_token_amount=1_000_000, cost_lamports=50_000_000, mode="live"))
    ledger.set_kv("wallet.pubkey", WALLET)
    ledger.set_position_wallet("p1", WALLET)
    ledger.set_position_wallet("p9", other)
    live = make_settings(TRADING_MODE="live", LIVE_CONFIRM=LIVE_CONFIRM_PHRASE, BOT_WALLET_SECRET="x" * 88,
                         DASHBOARD_HOST="127.0.0.1")
    state = build_state(ledger, live, NOW)
    assert state["safe_mode"] is None
    assert {p["id"]: p["foreign_wallet"] for p in state["positions"]} == {"p1": None, "p9": other}

    ledger.set_kv("engine.safe_mode", {"problems": ["STOP_LOSS_PCT: must be a FRACTION"],
                                       "defaults_used": ["STOP_LOSS_PCT"], "since": NOW - 60})
    state = build_state(ledger, live, NOW)
    assert state["safe_mode"] == {"problems": ["STOP_LOSS_PCT: must be a FRACTION"],
                                  "defaults_used": ["STOP_LOSS_PCT"], "since": NOW - 60}
    assert all(p["foreign_wallet"] is None for p in build_state(ledger, make_settings(), NOW)["positions"])
    assert "SAFE MODE" in _SCRIPT and "s.safe_mode" in _SCRIPT
    assert "p.foreign_wallet" in _SCRIPT and "another wallet" in _SCRIPT
