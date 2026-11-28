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


def _fake_gateway(markets, bbos, settlements, events=()):
    events = list(events)

    def fake_get(path, params=None, tries=4):
        if path == "/markets":
            off = params["offset"]
            ms = [m for m in markets if m["category"] == params["categories"]]
            return {"markets": ms[off : off + params["limit"]]}
        if path == "/events":
            return {
                "events": events[params["offset"] : params["offset"] + params["limit"]]
            }
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
    assert {k: r1[k] for k in ("watched", "rows", "settled_now", "settled_total")} == {
        "watched": 2,
        "rows": 2,
        "settled_now": 0,
        "settled_total": 0,
    }
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


def _event(slug, start_offset_s, period, n_markets=2, closed=False):
    from datetime import UTC, datetime

    start = datetime.fromtimestamp(NOW + start_offset_s, UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    markets = [
        {
            "slug": f"{slug}-ml",
            "question": slug,
            "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
            "closed": closed,
            "endDate": start,
            "feeCoefficient": "0.0695",
            "orderPriceMinTickSize": "0.001",
            "minimumTradeQty": "1",
            "status": "MARKET_STATUS_OPEN",
        },
        {
            "slug": f"{slug}-spread",
            "question": slug,
            "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_SPREAD",
            "closed": False,
            "endDate": start,
        },
    ][:n_markets]
    return {
        "slug": slug,
        "startTime": start,
        "period": period,
        "closed": closed,
        "markets": markets,
    }


def test_live_sports_markets_keeps_moneylines_of_games_in_progress(monkeypatch):
    evs = [
        _event("live1", -3600, "2H"),
        _event("live2", -600, "LIVE"),
        _event("notstarted", 1800, "NS"),
        _event("scheduled", -300, ""),
        _event("done", -4 * 3600, "FT"),
        _event("live3", -7200, "4Q"),
    ]
    monkeypatch.setattr(R, "_get", _fake_gateway([], {}, {}, events=evs))
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    got = R.live_sports_markets(NOW)
    assert [m["slug"] for m in got] == [
        "live2-ml",
        "live1-ml",
        "live3-ml",
    ]  # newest start first, moneylines only
    assert (
        got[0]["category"] == "sports"
        and got[0]["period"] == "LIVE"
        and got[0]["fee_coef"] == 0.0695
    )
    assert len(R.live_sports_markets(NOW, cap=2)) == 2


def test_poll_includes_live_sports_and_settles_them_when_they_leave_the_list(
    monkeypatch, tmp_path
):
    bbos = {"g1-ml": (0.96, 0.97, 0.965)}
    monkeypatch.setattr(
        R, "_get", _fake_gateway([], bbos, {}, events=[_event("g1", -3600, "2H")])
    )
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    r1 = R.poll(tmp_path, now=NOW)
    assert r1["watched"] == 1 and r1["rows"] == 1
    rec = json.loads((tmp_path / "markets.json").read_text())["g1-ml"]
    assert (
        rec["category"] == "sports" and rec["period"] == "2H" and rec["event"] == "g1"
    )
    # the game ends: it leaves the live list (its endDate may still be in the future) and settles at 1
    monkeypatch.setattr(R, "_get", _fake_gateway([], bbos, {"g1-ml": 1}, events=[]))
    r2 = R.poll(tmp_path, now=NOW + 1800)
    assert r2["watched"] == 0 and r2["settled_now"] == 1
    assert (
        json.loads((tmp_path / "settlements.json").read_text())["g1-ml"]["settlement"]
        == 1.0
    )


def test_state_files_are_written_atomically(tmp_path):
    R._write_atomic(tmp_path / "x.json", "{}")
    assert (tmp_path / "x.json").read_text() == "{}" and not (
        tmp_path / "x.tmp"
    ).exists()
