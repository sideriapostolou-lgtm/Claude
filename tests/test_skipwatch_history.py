"""Public-history coverage and accounting: synthetic pages, no network calls."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def history(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "research/lab8/skip"))
    return importlib.import_module("history")


@pytest.fixture
def accounting(history):
    return importlib.import_module("history_analysis")


class Clock:
    def __init__(self):
        self.at = 1000.0
        self.waits = []

    def __call__(self):
        return self.at

    def sleep(self, delay):
        self.waits.append(delay)
        self.at += delay


class Response:
    def __init__(self, body, status=200, headers=None):
        self.body, self.status_code, self.headers = body, status, headers or {}

    def json(self):
        return self.body


class Session:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def row(history, **changes):
    return {"proxy_wallet": history.WALLET, "timestamp": 900, "type": "TRADE", "side": "BUY",
            "size": 10, "price": .4, "usdc_size": 4.1, "token_id": "token", "condition_id": "market",
            "transaction_hash": "public-transaction", **changes}


def page(rows, *, offset=0, cursor=None, more=None):
    return {"data": rows, "pagination": {"limit": 1000, "offset": offset,
            "has_more": bool(cursor) if more is None else more, "next_cursor": cursor}}


def reader(history, *responses):
    clock, session = Clock(), Session(*responses)
    return history.PublicReader(session=session, clock=clock, sleep=clock.sleep), clock, session


def test_exact_cursor_pagination_resume_and_identical_fill_multiplicity(history, tmp_path):
    api, _, session = reader(history, Response(page([row(history), row(history)], cursor="page2")))
    params = {"user": history.WALLET, "start": 1, "end": 1000, "limit": 1000}
    first = history.walk(api, tmp_path, "activity", "activity", params, max_pages=1)
    assert first["rows"] == 2 and first["complete"] is False
    resumed, _, network = reader(history, Response(page([row(history, timestamp=901)], offset=2)))
    final = history.walk(resumed, tmp_path, "activity", "activity", params)
    assert final["rows"] == 3 and final["complete"] is True
    assert "cursor=page2" in network.calls[0][0]
    rows = list(history.iter_rows(tmp_path / "activity"))
    assert len(rows) == len({r["history_row_id"] for r in rows}) == 3
    assert rows[0]["history_row_id"].rsplit(":", 1)[0] == rows[1]["history_row_id"].rsplit(":", 1)[0]
    # Completed resume performs no network request or duplicate accounting.
    assert history.walk(resumed, tmp_path, "activity", "activity", params)["rows"] == 3
    assert len(network.calls) == 1
    assert session.calls[0][1]["allow_redirects"] is False


@pytest.mark.parametrize("bad", [
    {"data": [], "pagination": {}},
    page([], more=True, cursor="more"),
    page([], offset=10),
    page([], more=False, cursor="contradiction"),
])
def test_incomplete_or_contradictory_page_cannot_certify_coverage(history, tmp_path, bad):
    api, _, _ = reader(history, Response(bad))
    with pytest.raises(ValueError):
        history.walk(api, tmp_path, "activity", "activity", {"user": history.WALLET})
    manifest = json.loads((tmp_path / "activity/manifest.json").read_text())
    assert manifest["complete"] is False and manifest["rows"] == 0


def test_cursor_loop_never_counts_a_replayed_page(history, tmp_path):
    api, _, _ = reader(history, Response(page([row(history)], cursor="same")),
                       Response(page([row(history)], offset=1, cursor="same")))
    with pytest.raises(ValueError, match="Cursor loop"):
        history.walk(api, tmp_path, "activity", "activity", {"user": history.WALLET})
    manifest = json.loads((tmp_path / "activity/manifest.json").read_text())
    assert manifest["rows"] == 1 and not manifest["complete"]


def test_retry_after_is_honored_without_cap_and_requests_are_spaced(history):
    api, clock, session = reader(history, Response({}, 429, {"Retry-After": "301"}), Response({"data": []}),
                                 Response({"data": []}))
    api.get("activity", {"user": history.WALLET})
    api.get("trades", {"user": history.WALLET})
    assert 301 in clock.waits and clock.at >= 1302
    assert len(session.calls) == 3 and api.retries[0]["reason"] == "http_429"
    with pytest.raises(ValueError, match="fixed public wallet"):
        api.get("orders", {"user": history.WALLET})


def test_history_digest_mismatch_rejects_resume(history, tmp_path):
    api, _, _ = reader(history, Response(page([row(history)])))
    params = {"user": history.WALLET}
    history.walk(api, tmp_path, "activity", "activity", params)
    manifest_path = tmp_path / "activity/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["pages"][0]["sha256"] = "incorrect"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="digest mismatch"):
        history.walk(api, tmp_path, "activity", "activity", params)


@pytest.mark.parametrize("field,value", [("next_cursor", "skipped-page"), ("complete", False)])
def test_resume_manifest_cannot_skip_pages_or_change_terminal_status(history, tmp_path, field, value):
    api, _, _ = reader(history, Response(page([row(history)])))
    params = {"user": history.WALLET}
    history.walk(api, tmp_path, "activity", "activity", params)
    path = tmp_path / "activity/manifest.json"
    manifest = json.loads(path.read_text())
    manifest[field] = value
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="completion or resume cursor"):
        history.walk(api, tmp_path, "activity", "activity", params)


def test_daily_cumulative_pnl_never_double_subtracts_fees_or_fabricates_nulls(accounting):
    points = [{"timestamp": 86400, "realized_pnl": 75, "position_pnl": 80, "economic_pnl": 83,
               "trade_pnl": 100, "fees": -20, "wallet_income": 3, "unrealized_pnl": 5},
              {"timestamp": 172800, "realized_pnl": 100, "position_pnl": 110, "economic_pnl": 120,
               "trade_pnl": 150, "fees": -40, "wallet_income": 10, "unrealized_pnl": 10},
              {"timestamp": 259200, "realized_pnl": 90, "position_pnl": None, "economic_pnl": None,
               "trade_pnl": None, "fees": -45, "wallet_income": 10, "unrealized_pnl": None},
              {"timestamp": 260000, "economic_pnl": 90}]
    rows, risk = accounting.pnl_deltas(points)
    assert rows[1]["economic_pnl_change"] == 37 and rows[1]["fees_change"] == -20
    assert rows[2]["economic_pnl_change"] is None and rows[3]["economic_pnl_change"] is None
    assert rows[0]["first_inception_interval"] and not rows[0]["complete_grid_day"]
    assert rows[1]["complete_grid_day"] and not rows[3]["complete_grid_day"]
    assert risk["daily_grid_max_drawdown"] == 30 and risk["intraday_drawdown"] is None


def test_funding_is_not_trading_profit_and_unknown_activity_remains_unknown(accounting, history):
    assert accounting.activity_cash_delta(row(history, type="DEPOSIT", usdc_size=4000)) == ("external_funding", 4000)
    assert accounting.activity_cash_delta(row(history, type="WITHDRAWAL", usdc_size=100)) == ("external_funding", -100)
    bucket, delta = accounting.activity_cash_delta(row(history))
    assert bucket == "trading_cash" and str(delta) == "-4.1"
    assert accounting.activity_cash_delta(row(history, type="CONVERSION")) == ("unknown", None)


def test_tip_cash_uses_documented_size_and_does_not_become_trading_profit(accounting, history):
    assert accounting.activity_cash_delta(row(history, type="TIP", side="IN", size=12, usdc_size=0)) == ("external_funding", 12)
    assert accounting.activity_cash_delta(row(history, type="TIP", side="OUT", size=12, usdc_size=0)) == ("external_funding", -12)


def test_summary_includes_opt_in_tips_and_excludes_post_pnl_cash_from_partial_day(accounting, history, tmp_path):
    api, _, _ = reader(history, Response(page([
        row(history, type="DEPOSIT", timestamp=600, usdc_size=4000),
        row(history, type="WITHDRAWAL", timestamp=900, usdc_size=100),
    ])), Response(page([row(history, type="TIP", side="IN", timestamp=700, size=12, usdc_size=0)])))
    history.walk(api, tmp_path, "activity", "activity", {"user": history.WALLET})
    history.walk(api, tmp_path, "tips", "activity", {"user": history.WALLET, "type": "TIP"})
    (tmp_path / "request.json").write_text(json.dumps({"cutoff": 1000}))
    pnl = {"received_at": 850, "response": {"data": {"proxy_wallet": history.WALLET, "source_fidelity": "1d",
             "points": [{"timestamp": 800, "economic_pnl": 0}]}}}
    (tmp_path / "pnl-daily.json").write_text(json.dumps(pnl))
    summary = accounting.summarize(tmp_path)
    assert summary["daily"][0]["external_funding"] == 4012
    assert summary["daily"][0]["withdrawals"] == 0
    assert summary["daily"][0]["activity_end_at"] == 800
    assert summary["activity_after_last_pnl_point"]["1970-01-01"]["withdrawals"] == 100
    assert summary["activity_types"]["TIP"] == 1 and summary["cash_balance"] is None


def test_archived_cash_preserves_actual_block_clock_and_cannot_be_called_profit(history, tmp_path):
    balances = importlib.import_module("history_balances")
    pnl = tmp_path / "pnl.json"
    pnl.write_text(json.dumps({"response": {"data": {"proxy_wallet": history.WALLET,
                          "points": [{"timestamp": 800, "source_block": 123}]}}}))

    class Rpc:
        def __init__(self):
            self.calls = []

        def call(self, method, params):
            self.calls.append((method, params))
            if method == "eth_chainId":
                return "0x89"
            if method == "eth_getBlockByNumber":
                return {"number": "0x7b", "hash": "0x" + "1" * 64, "timestamp": hex(799)}
            assert params == [{"to": balances.PUSD, "data": balances.BALANCE_DATA}, "0x7b"]
            return "0x" + hex(4_000_000_000)[2:].rjust(64, "0")

    rpc = Rpc()
    result = balances.collect(pnl, tmp_path / "balances", rpc)
    assert result["complete"] and result["net_profit"] is None
    assert result["points"][0]["pusd_cash"] == "4000.000000"
    assert result["points"][0]["block_at"] == 799 and result["points"][0]["series_at"] == 800
    balances.collect(pnl, tmp_path / "balances", rpc)
    assert len(rpc.calls) == 4  # chain check on resume, no duplicated historical reads
