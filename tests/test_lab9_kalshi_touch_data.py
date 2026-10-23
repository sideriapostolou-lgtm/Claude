"""No-network acquisition checks: retain source evidence, fail on incomplete pages."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
import requests

SOURCE = Path(__file__).parents[1] / "research/lab9/kalshi_touch_data.py"
SPEC = importlib.util.spec_from_file_location("lab9_kalshi_touch_data", SOURCE)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class Reply:
    def __init__(self, body: Any, status: int = 200, headers: dict[str, str] | None = None) -> None:
        self.text = json.dumps(body)
        self.status_code = status
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        raise requests.HTTPError(str(self.status_code))


def fake(tmp_path: Path, replies: list[Reply | Exception]) -> tuple[Any, list[Any], list[float]]:
    calls: list[Any] = []
    delays: list[float] = []

    def get(url: str, **kwargs: Any) -> Reply:
        calls.append((url, kwargs))
        response = replies.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    return module.PublicArchive(tmp_path, get=get, wait=lambda: None, sleep=delays.append), calls, delays


@pytest.mark.parametrize("path", ["/portfolio/orders", "/portfolio/balance", "/api_keys", "https://elsewhere", "/markets/../../portfolio/orders"])
def test_private_or_arbitrary_routes_never_reach_transport(tmp_path: Path, path: str) -> None:
    archive, calls, _ = fake(tmp_path, [])
    with pytest.raises(ValueError, match="allowlisted public GET"):
        archive.request(path, {})
    assert calls == []


def test_cursor_exhaustion_preserves_exact_decimal_and_unknown_fields(tmp_path: Path) -> None:
    raw = {"trade_id": "t", "count_fp": "0.010000", "yes_price_dollars": "0.0310", "new_field": {"x": 1}}
    archive, calls, _ = fake(tmp_path, [Reply({"trades": [raw], "cursor": "next"}), Reply({"trades": [], "cursor": ""})])
    rows, pages = archive.pages("/historical/trades", {"ticker": "X", "limit": 1000}, "trades")
    assert rows == [raw]
    assert pages == 2
    assert calls[1][1]["params"]["cursor"] == "next"
    assert all(call[1]["allow_redirects"] is False for call in calls)
    assert all("headers" not in call[1] for call in calls)


def test_repeated_cursor_fails_instead_of_claiming_complete(tmp_path: Path) -> None:
    archive, _, _ = fake(tmp_path, [Reply({"trades": [], "cursor": "same"}), Reply({"trades": [], "cursor": "same"})])
    with pytest.raises(ValueError, match="Repeated cursor"):
        archive.pages("/historical/trades", {}, "trades")


@pytest.mark.parametrize("body", [{}, {"trades": {}}, {"trades": ["bad"]}, {"trades": []}, {"trades": [], "cursor": 2}])
def test_bad_page_cannot_mean_empty_history(tmp_path: Path, body: Any) -> None:
    archive, _, _ = fake(tmp_path, [Reply(body)])
    with pytest.raises((ValueError, TypeError)):
        archive.pages("/historical/trades", {}, "trades")


def test_retries_rate_limit_and_network_failure_then_caches(tmp_path: Path) -> None:
    archive, calls, delays = fake(tmp_path, [Reply({}, 429, {"Retry-After": "3"}), requests.Timeout(), Reply({"markets": [], "cursor": ""})])
    assert archive.request("/markets", {}) == {"markets": [], "cursor": ""}
    assert delays == [3, 2]
    assert len(calls) == 3
    assert archive.request("/markets", {}) == {"markets": [], "cursor": ""}
    assert len(calls) == 3
    attempts = [json.loads(line) for line in (tmp_path / "requests.jsonl").read_text().splitlines()]
    assert [item["status"] for item in attempts] == [429, None, 200]


def test_cached_body_corruption_fails_closed(tmp_path: Path) -> None:
    archive, calls, _ = fake(tmp_path, [Reply({"markets": []})])
    archive.request("/markets", {})
    page = next((tmp_path / "pages").glob("*.json"))
    saved = json.loads(page.read_text())
    saved["body"] = '{"markets":[{}]}'
    page.write_text(json.dumps(saved))
    with pytest.raises(ValueError, match="checksum"):
        archive.request("/markets", {})
    assert len(calls) == 1


def test_both_tier_duplicate_is_not_second_fill_and_conflict_fails() -> None:
    trade = {"trade_id": "x", "created_time": "2026-01-01T00:00:00.123456Z", "count_fp": "2.01"}
    assert module.merge_trades([[trade], [dict(trade)]]) == ([trade], 1)
    with pytest.raises(ValueError, match="Conflicting"):
        module.merge_trades([[trade], [{**trade, "count_fp": "2.02"}]])


def test_missing_trade_id_never_gets_artificial_identity() -> None:
    with pytest.raises(ValueError, match="Missing trade ID"):
        module.merge_trades([[{"count_fp": "2"}]])


def test_redirect_is_not_followed_and_failed_request_is_not_cached(tmp_path: Path) -> None:
    archive, calls, _ = fake(tmp_path, [Reply({}, 302)])
    with pytest.raises(ValueError, match="302"):
        archive.request("/markets", {})
    assert calls[0][1]["allow_redirects"] is False
    assert not (tmp_path / "pages").exists()


def test_failed_retries_do_not_write_success(tmp_path: Path) -> None:
    archive, calls, _ = fake(tmp_path, [Reply({}, 503) for _ in range(6)])
    with pytest.raises(requests.HTTPError):
        archive.request("/markets", {})
    assert len(calls) == 6
    assert not (tmp_path / "pages").exists()


def test_retry_after_long_numeric_stops_without_early_retry(tmp_path: Path) -> None:
    archive, calls, delays = fake(tmp_path, [Reply({}, 429, {"Retry-After": "120"})])
    with pytest.raises(RuntimeError, match="Retry-After exceeds"):
        archive.request("/markets", {})
    assert len(calls) == 1
    assert delays == []
    resumed, resumed_calls, _ = fake(tmp_path, [])
    with pytest.raises(RuntimeError, match="still inside"):
        resumed.request("/markets", {})
    assert resumed_calls == []


def test_http_date_retry_after_is_honored() -> None:
    assert module.retry_delay("Thu, 01 Jan 1970 00:02:00 GMT", 0) == 120
    assert module.retry_delay("Thu, 01 Jan 1970 00:02:00 GMT", 121) == 0
    assert module.retry_delay("invalid", 0) == 0


def test_capture_timestamp_is_actual_response_not_request_start(tmp_path: Path, monkeypatch: Any) -> None:
    clocks = iter(["2026-01-01T00:00:00+00:00", "2026-01-01T00:00:03+00:00"])
    monkeypatch.setattr(module, "utc_now", lambda: next(clocks))
    archive, _, _ = fake(tmp_path, [Reply({"markets": []})])
    archive.request("/markets", {})
    saved = json.loads(next((tmp_path / "pages").glob("*.json")).read_text())
    assert saved["requested_at"] == "2026-01-01T00:00:00+00:00"
    assert saved["received_at"] == saved["captured_at"] == "2026-01-01T00:00:03+00:00"


def test_ticker_filter_is_verified_before_saving_tape(tmp_path: Path) -> None:
    archive, _, _ = fake(tmp_path, [Reply({"trades": [{"ticker": "OTHER"}], "cursor": ""})])
    with pytest.raises(ValueError, match="ignored ticker"):
        module.collect_market(archive, "SERIES", "EXPECTED", 100)
    assert not (tmp_path / "trades").exists()


def test_source_timestamp_must_respect_frozen_cutoff(tmp_path: Path) -> None:
    row = {"ticker": "X", "created_time": "1970-01-01T00:01:41Z"}
    archive, _, _ = fake(tmp_path, [Reply({"trades": [row], "cursor": ""})])
    with pytest.raises(ValueError, match="frozen capture cutoff"):
        module.collect_market(archive, "SERIES", "X", 100)
    assert not (tmp_path / "trades").exists()


def test_exchange_timestamp_without_timezone_is_not_localized_silently() -> None:
    with pytest.raises(ValueError, match="no timezone"):
        module.trade_time({"created_time": "2026-01-01T12:00:00"})


def test_full_tape_uses_both_tiers_without_losing_fractional_sizes(tmp_path: Path) -> None:
    trade = {"trade_id": "t", "ticker": "X", "created_time": "1970-01-01T00:00:30Z", "count_fp": "0.01", "no_price_dollars": "0.9731"}
    archive, calls, _ = fake(tmp_path, [Reply({"trades": [trade], "cursor": ""}), Reply({"trades": [trade], "cursor": ""})])
    ticker, summary = module.collect_market(archive, "SERIES", "X", 100)
    assert ticker == "X"
    assert summary["trades"] == summary["duplicates"] == 1
    assert len(calls) == 2
    assert {call[0] for call in calls} == {module.BASE + "/markets/trades", module.BASE + "/historical/trades"}
    assert json.loads((tmp_path / "trades/X.jsonl").read_text()) == trade


def test_fresh_cutoff_check_preserves_original_snapshot_page(tmp_path: Path) -> None:
    archive, calls, _ = fake(tmp_path, [Reply({"trades_created_ts": "old"}), Reply({"trades_created_ts": "new"})])
    assert archive.request("/historical/cutoff", {})["trades_created_ts"] == "old"
    assert archive.request("/historical/cutoff", {}, refresh=True)["trades_created_ts"] == "new"
    assert archive.request("/historical/cutoff", {})["trades_created_ts"] == "old"
    assert len(calls) == 2
    assert len(list((tmp_path / "pages").glob("*.json"))) == 2
