"""An expired session clears private town state; a network outage keeps dated reports."""

import shutil
from pathlib import Path

import pytest

from nightcrawler.world3d import _MODULE
from tests.test_world3d import _js_body, _node

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


@pytest.mark.parametrize("status", [401, 503])
def test_failed_fetch_clears_activity_and_only_auth_failure_clears_private_data(
    tmp_path: Path, status: int,
) -> None:
    functions = "\n".join(_js_body(_MODULE, marker) for marker in (
        "  async function fetchPage(", "  function setOffline(", "  function clearPageAccess(",
    ))
    out = _node("""
const token = "local-test-only";
let data = {money: {cash: 42}}, plain = {private: true}, offline = false, authLocked = false;
let lastOkAt = 10, lastClosedKey = "old";
const members = {risk: {private: true}}, lastEventTs = {risk: 9};
const statusEl = {}, body = {classList: {add() {}}};
const TY_BUSINESS = {sources: {kalshi: true}, memo: {sources: {kalshi: true}}, latest: new Map([["old", 1]])};
const TY_UI = {panelSignature: "old", panelRoot: {}}, panelBody = {textContent: "private receipt"};
const board = {visible: true}, calls = [];
function townActivityMemo() { return {sources: {}}; }
function tycoonBusinessClear(initial) { calls.push(["clear", initial]); }
function closePanel() { calls.push(["close"]); }
function renderBar() { calls.push(["bar"]); }
function renderCard() { calls.push(["card"]); }
function drawVaultSign(amount, label) { calls.push(["vault", amount, label]); }
function tycoonDraw() { calls.push(["town", data]); }
let fetches = 0;
async function fetch() { fetches++; return {status: STATUS, ok: false}; }
""".replace("STATUS", str(status)) + functions + """
const result = await fetchPage();
console.log(JSON.stringify({result, data, plain, members, lastEventTs, lastOkAt, lastClosedKey,
  offline, authLocked, latest: TY_BUSINESS.latest.size, sources: TY_BUSINESS.sources,
  memoSources: TY_BUSINESS.memo.sources, panel: panelBody.textContent, board: board.visible,
  signature: TY_UI.panelSignature, calls, fetches}));
""", tmp_path)
    assert out["result"] is None and out["offline"] is True
    assert out["sources"] == out["memoSources"] == {}  # even before an animation frame
    if status == 401:
        assert out["fetches"] == 2  # existing token retry, then locked
        assert out["authLocked"] is True
        assert out["data"] is out["plain"] is out["lastOkAt"] is out["lastClosedKey"] is None
        assert out["members"] == out["lastEventTs"] == {}
        assert out["latest"] == 0 and out["panel"] == "" and out["signature"] is None
        assert out["board"] is False and ["town", None] in out["calls"]
        assert ["vault", "—", "PRIVATE DATA LOCKED"] in out["calls"]
    else:
        assert out["fetches"] == 1 and out["authLocked"] is False
        assert out["data"]["money"]["cash"] == 42 and out["lastOkAt"] == 10


def test_successful_reauthentication_starts_a_new_event_baseline() -> None:
    apply = _js_body(_MODULE, "  function apply(d)")
    assert "const first = !data;" in apply
    assert "authLocked = false;" in apply
    assert 'BUS.emit("data", d, first)' in apply
