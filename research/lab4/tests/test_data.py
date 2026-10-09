"""Tests for research/lab4/data.py against a fake Gamma / Data API: time parsing, the market row, the newest-first
listing that stops at --since, trade windows that split when full and drop overlaps, and a resumable run."""

import json
from datetime import UTC, datetime

import pandas as pd
import pytest

import data as D

T0 = 1_790_000_000  # a reference unix second


def test_parse_time_accepts_gamma_formats():
    assert D.parse_time("2026-08-08T20:27:18Z") == pytest.approx(1_786_220_838.0, abs=1)
    assert D.parse_time("2026-08-08 20:27:18+00") == D.parse_time(
        "2026-08-08T20:27:18Z"
    )
    assert D.parse_time("2026-07-31T19:10:57.603878Z") == pytest.approx(
        D.parse_time("2026-07-31T19:10:57Z"), abs=1
    )
    assert (
        D.parse_time(None) is None
        and D.parse_time("") is None
        and D.parse_time("not a date") is None
    )


def _market(
    i, closed_ts, volume=50_000.0, prices=("0", "1"), status="resolved", fees=True
):
    return {
        "id": str(i),
        "conditionId": f"0x{i:064x}",
        "question": f"Q{i}?",
        "slug": f"q{i}",
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": json.dumps(list(prices)),
        "clobTokenIds": json.dumps(["111", "222"]),
        "closedTime": datetime.fromtimestamp(closed_ts, UTC).strftime(
            "%Y-%m-%d %H:%M:%S+00"
        ),
        "endDate": "2026-12-31T00:00:00Z",
        "startDate": "2026-01-01T00:00:00Z",
        "volumeNum": volume,
        "liquidityNum": None,
        "feesEnabled": fees,
        "takerBaseFee": 1000 if fees else 0,
        "makerBaseFee": 0,
        "feeType": "politics_fees" if fees else None,
        "negRisk": False,
        "umaResolutionStatus": status,
        "resolvedBy": "0xabc",
        "events": [{"slug": "ev", "title": "Event"}],
    }


def test_market_row_flattens_and_finds_the_winner():
    r = D.market_row(_market(7, T0, prices=("1", "0")))
    assert (
        r["id"] == "7"
        and r["winner_index"] == 0
        and r["n_outcomes"] == 2
        and r["fees_enabled"] is True
    )
    assert (
        r["taker_base_fee"] == 1000
        and r["event_slug"] == "ev"
        and r["closed_time"] == pytest.approx(T0)
    )
    assert (
        D.market_row(_market(8, T0, prices=("0.5", "0.5")))["winner_index"] == -1
    )  # split resolution
    assert D.market_row({})["id"] == "None" and D.market_row({})["closed_time"] is None


def test_list_resolved_pages_newest_first_and_stops_at_since(monkeypatch):
    # 250 closed markets, one per hour back from T0; the 5th is unresolved, the 6th tiny
    allm = [_market(i, T0 - 3600 * i) for i in range(250)]
    allm[5]["umaResolutionStatus"] = "proposed"
    allm[6]["volumeNum"] = 10.0
    calls = []

    def fake_get(url, params, tries=6):
        calls.append(params)
        assert (
            url.endswith("/markets/keyset")
            and "offset" not in params
            and params["volume_num_min"] == 1000
        )
        assert (
            params["order"] == "closedTime"
            and params["ascending"] == "false"
            and params["limit"] == 100
        )
        off = int(params.get("after_cursor") or 0)
        nxt = str(off + 100) if off + 100 < len(allm) else None
        return {"markets": allm[off : off + 100], "next_cursor": nxt}

    monkeypatch.setattr(D, "_get", fake_get)
    monkeypatch.setattr(D.time, "sleep", lambda s: None)
    since = datetime.fromtimestamp(T0 - 3600 * 120, UTC)
    until = datetime.fromtimestamp(T0 - 3600 * 2, UTC)
    df = D.list_resolved(since, until, min_volume=1000)
    assert (
        len(calls) == 2
    )  # stopped once a page crossed --since (market 121 is older than since)
    assert df["closed_time"].is_monotonic_decreasing
    ids = set(df["id"])
    assert (
        "0" not in ids
        and "1" not in ids
        and "2" in ids
        and "120" in ids
        and "121" not in ids
    )
    assert "5" not in ids and "6" not in ids and len(ids) == 119 - 2


def test_fetch_trades_splits_full_windows_and_dedupes(monkeypatch):
    # a market with one fill per second over 40,000 s: a single window overflows the 20k cap and must split
    fills = {
        t: {
            "timestamp": t,
            "price": 0.97,
            "size": 10.0,
            "side": "BUY",
            "outcomeIndex": 0,
            "asset": "111",
            "transactionHash": f"0x{t:x}",
        }
        for t in range(T0, T0 + 40_000)
    }
    calls = []

    def fake_get(url, params, tries=6):
        calls.append((params["start"], params["end"], params["offset"]))
        ts = sorted(
            (t for t in fills if params["start"] <= t <= params["end"]), reverse=True
        )
        page = ts[params["offset"] : params["offset"] + params["limit"]]
        return [fills[t] for t in page]

    monkeypatch.setattr(D, "_get", fake_get)
    monkeypatch.setattr(D.time, "sleep", lambda s: None)
    df = D.fetch_trades("0xcid", T0, T0 + 39_999)
    assert len(df) == 40_000 and df["ts"].is_monotonic_increasing and df["tx"].is_unique
    assert list(df.columns) == D.TRADE_COLUMNS
    assert any(c[0] > T0 for c in calls)  # the window was split
    empty = D.fetch_trades("0xcid", T0 - 10, T0 - 5)
    assert empty.empty and list(empty.columns) == D.TRADE_COLUMNS


def test_run_is_resumable_and_writes_manifest(monkeypatch, tmp_path):
    ms = [_market(i, T0 - 86400 * i) for i in range(3)]
    fetched = []

    def fake_get(url, params, tries=6):
        if "gamma" in url:
            return {"markets": ms, "next_cursor": None}
        fetched.append(params["market"])
        t = params["end"] - 7200
        return [
            {
                "timestamp": t,
                "price": 0.98,
                "size": 5.0,
                "side": "BUY",
                "outcomeIndex": 1,
                "asset": "222",
                "transactionHash": "0x1",
            }
        ]

    monkeypatch.setattr(D, "_get", fake_get)
    monkeypatch.setattr(D.time, "sleep", lambda s: None)
    monkeypatch.setattr(D, "HERE", tmp_path / "pkg")
    (tmp_path / "pkg").mkdir()
    since, until = (
        datetime.fromtimestamp(T0 - 86400 * 10, UTC),
        datetime.fromtimestamp(T0 + 1, UTC),
    )
    s1 = D.run(since, until, min_volume=0, lookback_days=1, out=tmp_path / "out")
    assert (
        s1["markets_listed"] == 3
        and s1["markets_with_tapes"] == 3
        and s1["fills"] == 3
        and len(fetched) == 3
    )
    man = json.loads((tmp_path / "out" / "manifest.json").read_text())
    assert set(man["markets"]) == {"0", "1", "2"} and man["markets"]["0"]["rows"] == 1
    assert (tmp_path / "pkg" / "data" / "manifest.json").exists()
    assert len(pd.read_parquet(tmp_path / "out" / "trades" / "1.parquet")) == 1
    s2 = D.run(
        since, until, min_volume=0, lookback_days=1, out=tmp_path / "out"
    )  # nothing refetched
    assert len(fetched) == 3 and s2["markets_with_tapes"] == 3
    assert fetched == [
        ms[2]["conditionId"],
        ms[1]["conditionId"],
        ms[0]["conditionId"],
    ]  # oldest first
    # list-only writes the list and fetches nothing; from-list fetches from it without listing
    out2 = tmp_path / "out2"
    s3 = D.run(since, until, min_volume=0, lookback_days=1, out=out2, list_only=True)
    assert (
        s3 == {"markets_listed": 3, "markets_in_window": 3}
        and not (out2 / "manifest.json").exists()
    )
    n_gamma = len(fetched)
    later = datetime.fromtimestamp(T0 - 86400 * 1.5, UTC)
    s4 = D.run(later, until, min_volume=0, lookback_days=1, out=out2, from_list=True)
    assert (
        s4["markets_with_tapes"] == 2 and len(fetched) == n_gamma + 2
    )  # only the two newest are in that window
    markets = pd.read_parquet(tmp_path / "out" / "markets.parquet")
    assert len(markets) == 3 and markets["closed_time"].is_monotonic_decreasing
