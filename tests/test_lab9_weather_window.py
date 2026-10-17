from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from research.lab9 import weather_window as weather


def print_row(identity: str, seconds: int, price: str = "0.97", count: str = "2.50",
              taker: str = "no") -> dict[str, Any]:
    return {"trade_id": identity, "created_time": datetime.fromtimestamp(
        1791216000 + seconds, UTC).isoformat(), "yes_price_dollars": str(1 - Decimal(price)),
        "no_price_dollars": price, "count_fp": count, "taker_side": taker}


def test_integer_fahrenheit_without_t_group_is_not_precision_evidence() -> None:
    assert weather.conservative_temperature("KNYC 010051Z 10SM CLR 20/10 A3000", "NYC") is None
    assert weather.conservative_temperature("KNYC 010051Z RMK 10200 20100", "NYC") is None


def test_t_group_station_sign_and_conservative_rounding() -> None:
    assert weather.conservative_temperature("KNYC 010051Z RMK T02000100", "NYC") == (Decimal("68.0"), 68)
    assert weather.conservative_temperature("KNYC 010051Z RMK T10001100", "NYC") == (Decimal("32.0"), 32)
    assert weather.conservative_temperature("KNYC 010051Z RMK T10151100", "NYC") == (Decimal("29.30"), 29)
    assert weather.conservative_temperature("KLGA 010051Z RMK T02000100", "NYC") is None
    # 21.4C converts to 70.52F, but its rounding interval includes <70.5F.
    assert weather.conservative_temperature("KNYC 010051Z RMK T02140100", "NYC") == (Decimal("70.52"), 70)


def test_parse_records_unknown_availability_and_corrections() -> None:
    body = "station,valid,tmpf,metar\nNYC,2026-10-05 05:51,68,KNYC 050551Z COR RMK T02000100\n"
    body += "NYC,2026-10-05 06:51,68,KNYC 050651Z 20/10\n"
    body += "LGA,2026-10-05 06:51,68,KLGA 050651Z RMK T02000100\n"
    obs, excluded = weather.parse_observations(body, "NYC")
    assert len(obs) == 1 and obs[0]["availability_at"] is None
    assert obs[0]["correction"] is True
    assert excluded == {"missing_or_invalid_current_t_group": 1, "wrong_station": 1}


def test_bucket_ties_are_not_overstated() -> None:
    between = {"strike_type": "between", "cap_strike": 70}
    below = {"strike_type": "less", "cap_strike": 70}
    assert not weather.no_proxy(between, 70)
    assert weather.no_proxy(between, 71)
    assert weather.no_proxy(below, 70)
    assert not weather.no_proxy(below, 69)
    assert not weather.no_proxy({"strike_type": "greater", "floor_strike": 70}, 90)


def test_local_standard_day_not_dst_and_no_cross_day_running_max() -> None:
    market = {"event_ticker": "KXHIGHNY-26OCT05", "strike_type": "between", "cap_strike": 70}
    obs = [{"at": at, "lower_integer_f": temp} for at, temp in [
        ("2026-10-05T04:59:00Z", 90), ("2026-10-05T05:00:00Z", 69),
        ("2026-10-05T06:00:00Z", 72), ("2026-10-06T05:00:00Z", 100)]]
    found, included = weather.first_proxy(market, obs, -5)
    assert len(included) == 2
    assert found == obs[2]


def test_print_boundaries_dedup_and_taker_direction() -> None:
    at = datetime.fromtimestamp(1791216000, UTC)
    rows = [print_row("before", -1), print_row("zero", 0), print_row("sixty", 60, taker="yes"),
            print_row("unknown", 120, taker="missing"), print_row("end", 180), print_row("zero", 0)]
    actual = weather.summarize_prints(rows, at)
    assert actual["prints"] == 3 and actual["contracts"] == "7.50"
    assert actual["target_no_taker_contracts"] == "2.50"
    assert actual["target_yes_taker_contracts"] == "2.50"
    assert actual["target_unknown_taker_contracts"] == "2.50"
    assert actual["minute_contracts"] == {"0_60": "2.50", "60_120": "2.50", "120_180": "2.50"}
    assert actual["achievable_fills"] is None and actual["achievable_pnl"] is None
    stressed = weather.summarize_prints(rows, at, 120)
    assert stressed["prints"] == 1


def test_target_band_decimal_price_counts_not_spurious_float_rounding() -> None:
    rows = [print_row("a", 1, "0.96", "1"), print_row("b", 1, "0.97", "2"),
            print_row("c", 1, "0.98", "3"), print_row("d", 1, "0.99", "4")]
    actual = weather.summarize_prints(rows, datetime.fromtimestamp(1791216000, UTC))
    assert actual["contracts_at_97"] == "2"
    assert actual["contracts_at_98"] == "3"
    assert actual["target_contracts"] == "5"
    assert actual["below_97_contracts"] == "1"
    assert actual["above_98_contracts"] == "4"
    assert actual["weighted_no_price"] == "0.98"


@pytest.mark.parametrize("field,value", [
    ("no_price_dollars", "0.98"), ("yes_price_dollars", "NaN"),
    ("count_fp", "0"), ("count_fp", "-1"), ("count_fp", "Infinity"),
    ("created_time", "2026-10-05T12:00:00"),
])
def test_invalid_trade_cannot_create_volume(field: str, value: str) -> None:
    row = print_row("bad", 1)
    row[field] = value
    result = weather.summarize_prints([row], datetime.fromtimestamp(1791216000, UTC))
    assert result["prints"] == 0 and result["excluded"]["invalid_trade"] == 1


def test_pagination_preserves_filters_and_exhausts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = weather.PublicClient(tmp_path)
    requests: list[list[tuple[str, Any]]] = []

    def fake_get(url: str, params: list[tuple[str, Any]] | None = None) -> str:
        assert url == weather.BASE + "/markets/trades"
        assert params is not None
        requests.append(params)
        return json.dumps({"trades": [{"n": len(requests)}], "cursor": "next" if len(requests) == 1 else ""})

    monkeypatch.setattr(client, "get", fake_get)
    rows = client.pages("/markets/trades", {"ticker": "x", "min_ts": 1, "max_ts": 181}, "trades")
    assert rows == [{"n": 1}, {"n": 2}]
    assert dict(requests[1]) == {"ticker": "x", "min_ts": 1, "max_ts": 181, "cursor": "next"}


def test_repeated_cursor_is_incomplete_not_silent_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = weather.PublicClient(tmp_path)
    monkeypatch.setattr(client, "get", lambda *_: json.dumps({"trades": [], "cursor": "stuck"}))
    with pytest.raises(ValueError, match="repeated pagination"):
        client.pages("/markets/trades", {}, "trades")


def test_conflicting_duplicate_trade_id_invalidates_window() -> None:
    rows = [print_row("same", 1, "0.97"), print_row("same", 1, "0.98")]
    with pytest.raises(ValueError, match="conflicting duplicate"):
        weather.summarize_prints(rows, datetime.fromtimestamp(1791216000, UTC))


@pytest.mark.parametrize("tamper", ["body", "url", "status"])
def test_cache_integrity_rejects_corrupt_or_wrong_response(
        tmp_path: Path, tamper: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib

    client = weather.PublicClient(tmp_path)
    url = weather.BASE + "/markets?limit=1"
    identity = hashlib.sha256(url.encode()).hexdigest()
    body = b'{"markets": []}'
    metadata = {"url": url, "status": 200, "sha256": hashlib.sha256(body).hexdigest()}
    if tamper == "url":
        metadata["url"] = url + "0"
    elif tamper == "status":
        metadata["status"] = 429
    client.raw.joinpath(identity + ".body").write_bytes(body + (b" " if tamper == "body" else b""))
    client.raw.joinpath(identity + ".json").write_text(json.dumps(metadata))
    monkeypatch.setattr(weather.urllib.request, "urlopen", lambda *_: pytest.fail("no network"))
    with pytest.raises(ValueError, match="raw cache integrity"):
        client.get(weather.BASE + "/markets", [("limit", 1)])
