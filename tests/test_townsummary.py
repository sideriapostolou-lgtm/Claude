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


@needs_node
def test_missing_or_practice_only_records_never_become_real_zero_profit(tmp_path: Path) -> None:
    value = {"generated_at": NOW, "money": {"polymarket": {"mode": "paper", "as_of": NOW,
                                                            "paper": {"today_usd": 999}},
                                          "speeddesk": {"today": {"pnl_usd": 888}}}}
    first = run(tmp_path, value)["first"]
    for key in ("pm-cash", "pm-profit", "pm-open", "pm-value", "kalshi-cash", "kalshi-profit", "kalshi-risk"):
        assert first[key]["text"] == "Not reported"
    assert "No new bot bets" in first["pm-state"]["text"]
    assert "complete Pacific-day bot result is not available" in first["pm-warning"]["text"]


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
