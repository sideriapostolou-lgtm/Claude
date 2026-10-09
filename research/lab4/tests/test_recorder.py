"""Tests for research/lab4/recorder.py against a fake gateway: the watch list (non-sports, within the horizon),
one poll's BBO rows and settlement bookkeeping, and the status line."""

import csv
import json

import recorder as R

NOW = 1_791_560_000.0


def _market(slug, cat, end_offset_s, closed=False):
    from datetime import UTC, datetime

    return {
        "slug": slug,
        "question": slug,
        "category": cat,
        "closed": closed,
        "status": "MARKET_STATUS_OPEN",
        "endDate": datetime.fromtimestamp(NOW + end_offset_s, UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "feeCoefficient": "0.0695",
        "orderPriceMinTickSize": "0.001",
        "minimumTradeQty": "1",
    }


def _fake_gateway(markets, bbos, settlements):
    def fake_get(path, params=None, tries=4):
        if path == "/markets":
            off = params["offset"]
            return {"markets": markets[off : off + params["limit"]]}
        if path.endswith("/bbo"):
            slug = path.split("/")[2]
            return {
                "marketData": {
                    "bestBid": {"value": str(bbos[slug][0])},
                    "bestAsk": {"value": str(bbos[slug][1])},
                    "lastTradePx": {"value": str(bbos[slug][2])},
                }
            }
        if path.endswith("/settlement"):
            slug = path.split("/")[2]
            if slug in settlements:
                return {"slug": slug, "settlement": settlements[slug]}
            raise RuntimeError("404")
        raise AssertionError(path)

    return fake_get


def test_open_markets_filters_sports_and_horizon(monkeypatch):
    ms = [
        _market("w1", "climate", 3600),
        _market("s1", "sports", 3600),
        _market("far", "crypto", 100 * 3600),
        _market("old", "politics", -2 * 3600),
        _market("c1", "crypto", 20 * 3600),
    ]
    monkeypatch.setattr(R, "_get", _fake_gateway(ms, {}, {}))
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    got = R.open_markets(NOW)
    assert (
        [m["slug"] for m in got] == ["w1", "c1"]
        and got[0]["fee_coef"] == 0.0695
        and got[0]["tick"] == 0.001
    )


def test_poll_records_bbo_and_settles_closed_markets(monkeypatch, tmp_path):
    ms = [_market("w1", "climate", 3600), _market("c1", "crypto", 7200)]
    bbos = {"w1": (0.97, 0.98, 0.975), "c1": (0.40, 0.42, 0.41)}
    monkeypatch.setattr(R, "_get", _fake_gateway(ms, bbos, {}))
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    r1 = R.poll(tmp_path, now=NOW)
    assert r1 == {"watched": 2, "rows": 2, "settled_now": 0, "settled_total": 0}
    rows = list(csv.DictReader((tmp_path / "bbo" / "2026-10-09.csv").open()))
    assert (
        len(rows) == 2
        and rows[0]["slug"] == "w1"
        and rows[0]["best_ask"] == "0.98"
        and rows[0]["fee_coef"] == "0.0695"
    )
    # an hour later w1 has closed and settled at 1; c1 still open
    later = NOW + 3700
    monkeypatch.setattr(
        R, "_get", _fake_gateway([_market("c1", "crypto", 7200)], bbos, {"w1": 1})
    )
    r2 = R.poll(tmp_path, now=later)
    assert r2["watched"] == 1 and r2["settled_now"] == 1 and r2["settled_total"] == 1
    settled = json.loads((tmp_path / "settlements.json").read_text())
    assert settled["w1"]["settlement"] == 1.0 and settled["w1"]["category"] == "climate"
    r3 = R.poll(tmp_path, now=later + 60)  # settled once, not again
    assert r3["settled_now"] == 0 and r3["settled_total"] == 1
    assert set(json.loads((tmp_path / "markets.json").read_text())) == {"w1", "c1"}
    R.status(tmp_path)


def test_parse_helpers():
    assert (
        R.parse_iso("2026-10-09T15:00:00Z") == 1_791_558_000.0
        and R.parse_iso(None) is None
        and R.parse_iso("x") is None
    )
    assert (
        R._num({"value": "0.5"}) == 0.5
        and R._num("") is None
        and R._num(None) is None
        and R._num("abc") is None
    )
