"""The lightweight fallback preserves money scope, freshness and GET-only access."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from nightcrawler.townsummary import SUMMARY_CSP, render_summary_html

NOW = 1_800_000_000
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


def recorded_page() -> dict[str, Any]:
    return {
        "generated_at": NOW - 1,
        "money": {
            "polymarket": {"mode": "live", "as_of": NOW - 10, "real": {
                "cash_usd": 14.39, "cash_at": NOW - 10, "venue_at": NOW - 10,
                "venue_open": 3, "value_usd": 6.22, "today_usd": 900,
                "today_pacific": {"date": "2027-01-15", "tz": "America/Los_Angeles",
                                  "start": NOW - 3600, "end": NOW + 82800, "as_of": NOW - 10,
                                  "status": "ok", "pnl_usd": .23},
            }, "paper": {"today_usd": 10000}},
            "speeddesk": {"mode": "paper", "as_of": NOW - 2, "today": {"pnl_usd": 20000},
                          "kalshi_live": {
                              "as_of": NOW - 2, "cash_at": NOW - 3, "cash_usd": 25,
                              "mode": "paper", "active": False, "has_real_exposure": True,
                              "at_risk_usd": 1.98, "cleanup_pending": True,
                              "today": {"day": datetime.fromtimestamp(NOW, UTC).date().isoformat(),
                                        "pnl_usd": -.34},
                          }},
        },
        "plain": {"team": [{"id": "voss", "name": "Voss", "job": "Polymarket (real money)"}]},
        "team": {"members": [{"id": "predict", "status": "working", "last_activity": NOW - 10,
                               "doing": "Watching Bitcoin markets"}]},
    }


def connected_page() -> dict[str, Any]:
    value = recorded_page()
    pacific = value["money"]["polymarket"]["real"]["today_pacific"]
    value["money"]["connections"] = {
        "version": 1,
        "polymarket_us": {
            "as_of": NOW - 10, "stale": False, "status": "ok", "source_note": "Shared account positions and bot records.",
            "positions_basis": "Venue account holdings, including your own bets", "today_pacific": pacific,
            "positions": [{"id": "owner-1", "title": "Your basketball bet", "scope": "owner", "side": "yes",
                           "quantity": 3, "price": .5, "cost_usd": 1.5, "fee_usd": None}],
            "orders": [], "events": [{"id": "owner-fill-1", "real": True, "scope": "owner", "venue": "polymarket_us",
                                      "ts": NOW - 120, "source_at": NOW - 10, "qualified": True,
                                      "type": "fill", "text": "Your basketball bet filled", "fee_usd": .00001,
                                      "fee_source": "estimated"}],
            "issues": ["Some fees were not reported by the venue."], "truncated": {},
        },
        "kalshi": {
            "as_of": NOW - 2, "stale": False, "status": "ok", "source_note": "Bot fills and resting orders.",
            "positions_basis": "Bot positions from real fills",
            "today_pacific": {**pacific, "as_of": NOW - 2, "pnl_usd": .56},
            "positions": [{"id": "kalshi-1", "title": "Bitcoin 15 minute", "scope": "bot", "side": "no",
                           "quantity": 2, "price": .47, "cost_usd": .94, "fee_usd": .0033, "fee_source": "actual"}],
            "orders": [{"id": "order-1", "title": "Bitcoin next window", "side": "yes", "status": "resting",
                        "quantity": 3, "filled_quantity": 1, "remaining_quantity": 2, "reserved_usd": .98}],
            "events": [{"id": "kalshi-fill-1", "real": True, "scope": "bot", "venue": "kalshi", "ts": NOW - 60,
                        "source_at": NOW - 2, "qualified": True, "type": "fill", "text": "Bought 2 NO contracts",
                        "fee_usd": .0033, "fee_source": "actual"},
                       {"id": "practice-fill", "real": False, "scope": "bot", "venue": "kalshi", "ts": NOW - 1,
                        "source_at": NOW - 2, "qualified": True, "type": "fill", "text": "Pretend fill must not appear"}],
            "issues": [], "truncated": {},
        },
    }
    return value


def run(tmp_path: Path, value: Any, actions: str = "") -> dict[str, Any]:
    script = re.search(r"<script>(.*?)</script>", render_summary_html(), re.DOTALL)
    assert script is not None
    harness = r"""
const nodes = {}, intervals = [], listeners = {}, requests = [], tags = [];
let now = NOW, queue = [{ status: 200, value: INPUT }];
Date.now = function () { return now * 1000; };
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.value = ""; this.hidden = false; }
  set textContent(text) { this.value = String(text); this.children = []; }
  get textContent() { return this.value + this.children.map(function (c) { return c.textContent; }).join(" "); }
  set innerHTML(value) { throw new Error("Unsafe markup insertion"); }
  appendChild(child) { this.children.push(child); }
  replaceChildren(...children) { this.value = ""; this.children = children; }
}
const document = { hidden: false,
  getElementById: function (id) { return nodes[id] || (nodes[id] = new Element("div")); },
  createElement: function (tag) { tags.push(tag); return new Element(tag); },
  addEventListener: function (kind, callback) { listeners[kind] = callback; }
};
const setInterval = function (callback, delay) { intervals.push({ callback, delay }); return intervals.length; };
const setTimeout = function () { return 1; }, clearTimeout = function () {};
const fetch = async function (url, options) {
  requests.push({ url, method: options.method, credentials: options.credentials, cache: options.cache,
    redirect: options.redirect, body: options.body || null });
  const reply = queue.shift();
  if (!reply || reply.error) throw new Error("Network failure");
  return { status: reply.status, ok: reply.status >= 200 && reply.status < 300,
    json: async function () { return reply.value; } };
};
const snapshot = function () { return Object.fromEntries(Object.entries(nodes).map(function (row) {
  return [row[0], { text: row[1].textContent, hidden: row[1].hidden }];
})); };
const poll = function () { return intervals.find(function (i) { return i.delay === 15000; }).callback(); };
"""
    tail = """
await new Promise(setImmediate);
const first = snapshot();
""" + actions + """
console.log(JSON.stringify({ first, last: snapshot(), requests, tags }));
"""
    path = tmp_path / "summary.mjs"
    path.write_text("const NOW = " + str(NOW) + "; const INPUT = " + json.dumps(value) + ";\n"
                    + harness + script.group(1) + tail)
    result = subprocess.run(["node", str(path)], capture_output=True, text=True, check=True, timeout=20)
    out: dict[str, Any] = json.loads(result.stdout)
    return out


def test_static_response_cannot_include_credentials_or_unhashed_executable_content(monkeypatch: pytest.MonkeyPatch) -> None:
    before = render_summary_html()
    monkeypatch.setenv("DASHBOARD_TOKEN", "test-private-value-never-render")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", "test-private-key-never-render")
    assert render_summary_html() == before
    for tag in ("script", "style"):
        content = re.findall(fr"<{tag}>(.*?)</{tag}>", before, re.DOTALL)
        assert len(content) == 1
        digest = base64.b64encode(hashlib.sha256(content[0].encode()).digest()).decode()
        assert f"'sha256-{digest}'" in SUMMARY_CSP
    directives = dict(part.strip().split(" ", 1) for part in SUMMARY_CSP.split(";"))
    assert directives["default-src"] == "'none'"
    assert directives["connect-src"] == "'self'"
    assert directives["form-action"] == directives["frame-ancestors"] == "'none'"
    assert "'unsafe-inline'" not in SUMMARY_CSP and "'unsafe-eval'" not in SUMMARY_CSP
    assert re.findall(r'<a\b[^>]*href="([^"]+)"', before) == ["/"]
    assert not re.search(r"<(?:form|button|iframe|canvas)\b|\bonclick=", before)
    assert "location.search" not in before and "localStorage" not in before


@needs_node
def test_same_adapter_keeps_account_cash_pacific_profit_and_kalshi_exposure_separate(tmp_path: Path) -> None:
    out = run(tmp_path, recorded_page())
    first = out["first"]
    assert first["pm-cash"]["text"] == "$14.39"
    assert first["pm-profit"]["text"] == "+$0.23"
    assert first["pm-open"]["text"] == "3" and first["pm-value"]["text"] == "$6.22"
    assert first["kalshi-cash"]["text"] == "$25.00" and first["kalshi-profit"]["text"] == "−$0.34"
    assert first["kalshi-risk"]["text"] == "$1.98"
    assert first["kalshi-state"]["text"] == "Real bets remain open"
    assert "cancellation and reconciliation are still pending" in first["kalshi-warning"]["text"]
    assert "20000" not in json.dumps(first) and "10000" not in json.dumps(first)
    assert out["requests"] == [{"url": "/api/page", "method": "GET", "credentials": "same-origin",
                               "cache": "no-store", "redirect": "error", "body": None}]


@needs_node
def test_independent_source_ages_survive_a_fresh_heartbeat(tmp_path: Path) -> None:
    value = recorded_page()
    real = value["money"]["polymarket"]["real"]
    real.update(cash_at=NOW - 7200, venue_at=NOW - 900)
    real["today_pacific"]["as_of"] = NOW - 601
    value["money"]["speeddesk"]["kalshi_live"].update(cash_at=NOW - 121, cleanup_pending=False)
    first = run(tmp_path, value)["first"]
    assert "cash may be old" in first["pm-warning"]["text"].lower()
    assert "Holdings may be old" in first["pm-warning"]["text"]
    assert "Pacific-day profit may be old" in first["pm-warning"]["text"]
    assert "2 hours ago" in first["pm-times"]["text"]
    assert "current Kalshi cash balance is not available" in first["kalshi-warning"]["text"]
    assert "2 minutes ago" in first["kalshi-times"]["text"]
    assert first["kalshi-times"]["text"].startswith("Desk report less than a minute ago; cash read 2 minutes ago")
    assert "Account reconciliation time not reported" in first["kalshi-times"]["text"]
    assert "Account checked" not in first["kalshi-times"]["text"]


@needs_node
def test_missing_or_practice_only_records_never_become_real_zero_profit(tmp_path: Path) -> None:
    value = {"generated_at": NOW, "money": {"polymarket": {"mode": "paper", "as_of": NOW,
                                                            "paper": {"today_usd": 999}},
                                          "speeddesk": {"today": {"pnl_usd": 888}}}}
    first = run(tmp_path, value)["first"]
    for key in ("pm-cash", "pm-profit", "pm-open", "pm-value", "kalshi-cash", "kalshi-profit", "kalshi-pacific-profit", "kalshi-risk"):
        assert first[key]["text"] == "Not reported"
    assert "No new bot bets" in first["pm-state"]["text"]
    assert "profit today is unverified" in first["pm-warning"]["text"]
    assert "complete Pacific-day report is unavailable" in first["pm-warning"]["text"]


@needs_node
def test_dynamic_crew_and_status_text_cannot_become_html(tmp_path: Path) -> None:
    value = recorded_page()
    attack = "<img src=x onerror=alert(1)>"
    value["plain"]["team"][0]["name"] = attack
    value["team"]["members"][0]["doing"] = attack
    value["money"]["speeddesk"]["kalshi_live"]["reason"] = attack
    value["alerts"] = [{"text": attack}, {"text": "The bot is stopped."}]
    out = run(tmp_path, value)
    assert attack in out["first"]["crew"]["text"]
    assert out["first"]["kalshi-reason"]["text"] == attack
    assert "The bot is stopped." in out["first"]["service-warning"]["text"]
    assert attack in out["first"]["service-warning"]["text"]
    assert set(out["tags"]) <= {"li", "strong", "p"}


@needs_node
@pytest.mark.parametrize("status", [401, 403])
def test_auth_expiry_clears_old_figures_and_stops_requests_without_exposing_tokens(tmp_path: Path, status: int) -> None:
    out = run(tmp_path, recorded_page(), f"queue.push({{status:{status}}}); await poll(); await poll();")
    assert "Session expired" in out["last"]["connection"]["text"]
    assert out["last"]["pm-cash"]["text"] == out["last"]["kalshi-cash"]["text"] == "Not reported"
    assert len(out["requests"]) == 2
    assert all(request["url"] == "/api/page" and request["method"] == "GET" for request in out["requests"])


@needs_node
def test_offline_retains_explicit_history_and_hides_no_missing_numbers(tmp_path: Path) -> None:
    out = run(tmp_path, recorded_page(), "now += 700; queue.push({error:true}); await poll();")
    assert "Connection lost" in out["last"]["connection"]["text"]
    assert "last saved report, not a current check" in out["last"]["connection"]["text"]
    assert out["last"]["pm-cash"]["text"] == "$14.39"
    assert out["last"]["pm-state"]["text"].startswith("Last report:")
    assert "delayed" in out["last"]["pm-warning"]["text"]
    assert "delayed" in out["last"]["kalshi-warning"]["text"]


@needs_node
def test_hidden_page_does_not_poll_and_invalid_json_is_an_offline_report(tmp_path: Path) -> None:
    out = run(tmp_path, recorded_page(), "document.hidden = true; await poll(); document.hidden = false;"
              "queue.push({status:200,value:[]}); await poll();")
    assert len(out["requests"]) == 2
    assert "Connection lost" in out["last"]["connection"]["text"]
    assert out["last"]["pm-cash"]["text"] == "$14.39"


@needs_node
def test_venue_positions_orders_fees_and_owner_activity_keep_their_scope(tmp_path: Path) -> None:
    first = run(tmp_path, connected_page())["first"]
    assert first["kalshi-pacific-profit"]["text"] == "+$0.56"
    assert first["kalshi-profit"]["text"] == "−$0.34"  # The original UTC result is separate.
    assert first["pm-profit"]["text"] == "+$0.23" and first["pm-cash"]["text"] == "$14.39"
    assert "Your own bet · YES · Contracts: 3" in first["pm-business"]["text"]
    assert "Fee: Not reported" in first["pm-business"]["text"]
    assert "Bot bet · NO · Contracts: 2" in first["kalshi-business"]["text"]
    assert "Fee: $0.0033 (actual)" in first["kalshi-business"]["text"]
    assert "filled: 1; remaining: 2" in first["kalshi-business"]["text"]
    assert "Money reserved: $0.98" in first["kalshi-business"]["text"]
    assert "Some fees were not reported" in first["pm-business-warning"]["text"]
    activity = first["activity"]["text"]
    assert "Kalshi · Bot activity" in activity and "Polymarket US · Your activity" in activity
    assert "Recorded fee: <$0.0001 (estimated)" in activity and "Recorded 1 minutes ago" in activity
    assert "Recorded fee: $0.0033 (actual)" in activity
    assert "Pretend fill" not in activity


@needs_node
def test_missing_details_and_old_sources_do_not_claim_reconciled_empty_accounts(tmp_path: Path) -> None:
    absent = run(tmp_path, recorded_page())["first"]
    assert "Missing records do not mean zero holdings or fees" in absent["pm-business"]["text"]
    value = connected_page()
    value["money"]["connections"]["kalshi"].update(as_of=NOW - 300, stale=True)
    first = run(tmp_path, value)["first"]
    assert first["kalshi-business-time"]["text"].startswith("Last saved source: 5 minutes ago")
    assert "awaiting a current source check" in first["activity"]["text"]
    assert "profit today is unverified" in first["kalshi-warning"]["text"]
    assert "old" in first["kalshi-warning"]["text"]


@needs_node
def test_book_mismatch_explains_unavailable_pacific_profit_without_hiding_cash(tmp_path: Path) -> None:
    value = connected_page()
    value["money"]["polymarket"]["real"]["today_pacific"].update(
        status="incomplete", reason="day_book_mismatch", pnl_usd=None,
    )
    first = run(tmp_path, value)["first"]
    assert first["pm-cash"]["text"] == "$14.39"
    assert first["pm-profit"]["text"] == "Not reported"
    assert "profit today is unverified" in first["pm-warning"]["text"]
    assert "do not match" in first["pm-warning"]["text"]


@needs_node
def test_pair_completion_is_real_cash_but_not_permission_for_new_bets(tmp_path: Path) -> None:
    value = connected_page()
    value["money"]["speeddesk"]["kalshi_live"].update(
        mode="live", active=True, authenticated=True, real_orders_available=True,
        total_halted=True, cleanup_pending=False, reserved_usd=2.5, at_risk_usd=.75,
        reason="Total loss stop; only completing half-filled pairs before the close",
        caps={"window_usd": 5, "open_usd": 10, "day_stop_usd": 6, "total_stop_usd": 10},
    )
    first = run(tmp_path, value)["first"]
    assert first["kalshi-state"]["text"].startswith("REAL MONEY (Kalshi)")
    assert "completing existing pairs only" in first["kalshi-state"]["text"]
    assert "new bets are stopped" in first["kalshi-state"]["text"]
    assert "new real orders enabled" not in first["kalshi-state"]["text"]
    assert first["kalshi-risk"]["text"] == "$0.75"
    assert first["kalshi-reserved"]["text"] == "$2.50"
    assert "$5.00 per window; $10.00 open risk; $6.00 UTC-day stop; $10.00 total stop" in first["kalshi-limits"]["text"]
    assert "pair-completion reservations do not" in first["kalshi-risk-note"]["text"]
    assert "may exceed these budgets or loss stops" in first["kalshi-limits-note"]["text"]
    assert "do not guarantee profit" in first["kalshi-limits-note"]["text"]


@needs_node
@pytest.mark.parametrize("reset", ["armed", "account_unreconciled"])
def test_integrity_stop_and_pending_reset_never_look_like_resumed_trading(tmp_path: Path, reset: str) -> None:
    value = recorded_page()
    value["money"]["speeddesk"]["kalshi_live"].update(
        mode="live", active=True, authenticated=True, real_orders_available=True,
        integrity_error="position_mismatch", integrity_reset=reset, cleanup_pending=False,
    )
    first = run(tmp_path, value)["first"]
    assert first["kalshi-state"]["text"] == "Accounting checks stopped real buys"
    assert "real buys are blocked" in first["kalshi-warning"]["text"]
    assert "Accounting reset: waiting" in first["kalshi-warning"]["text"]
    assert "REAL MONEY (Kalshi)" not in first["kalshi-state"]["text"]


@needs_node
def test_account_reconciliation_has_its_own_age_not_the_desk_heartbeat(tmp_path: Path) -> None:
    value = recorded_page()
    value["money"]["speeddesk"]["kalshi_live"].update(account_at=NOW - 601)
    first = run(tmp_path, value)["first"]
    assert first["kalshi-times"]["text"].startswith("Desk report less than a minute ago; cash read less than a minute ago")
    assert "Account reconciliation 10 minutes ago" in first["kalshi-times"]["text"]
    assert "fresh desk report does not refresh it" in first["kalshi-warning"]["text"]


@needs_node
def test_finished_window_status_does_not_present_recorded_fills_as_current_holdings(tmp_path: Path) -> None:
    value = connected_page()
    value["money"]["connections"]["kalshi"]["positions"][0].update(
        status="finalized_unreconciled", current_position_verified=False,
        status_note="This window has finalized; settlement is not reconciled. These are recorded fills, not verified open holdings.",
    )
    first = run(tmp_path, value)["first"]
    assert "This window has finalized; settlement is not reconciled" in first["kalshi-business"]["text"]
    assert "not verified open holdings" in first["kalshi-business"]["text"]


@needs_node
def test_saved_inventory_and_activity_are_bounded_and_untrusted_text_is_safe(tmp_path: Path) -> None:
    value = connected_page()
    kalshi = value["money"]["connections"]["kalshi"]
    attack = "<img src=x onerror=alert(1)>"
    kalshi["positions"] = [{**kalshi["positions"][0], "id": str(i), "title": f"{attack} position {i}"} for i in range(10)]
    kalshi["orders"] = [{**kalshi["orders"][0], "id": str(i), "title": f"order {i}"} for i in range(10)]
    kalshi["events"] = [{**kalshi["events"][0], "id": str(i), "text": f"{attack} event {i}", "ts": NOW - i}
                        for i in range(15)]
    out = run(tmp_path, value)
    first = out["first"]
    assert "position 7" in first["kalshi-business"]["text"] and "position 8" not in first["kalshi-business"]["text"]
    assert "order 7" in first["kalshi-business"]["text"] and "order 8" not in first["kalshi-business"]["text"]
    assert "event 11" in first["activity"]["text"] and "event 12" not in first["activity"]["text"]
    assert "not the full account history" in first["kalshi-business-more"]["text"]
    assert "not the full account history" in first["activity-more"]["text"]
    assert attack in first["activity"]["text"] and set(out["tags"]) <= {"li", "strong", "p"}
