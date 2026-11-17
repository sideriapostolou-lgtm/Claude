"""Tests for research/lab6/data.py against a fake Odds API session: the key never reaches a file or an error
message, the credit ledger and its hard cap (checked before a call is sent), the cache (a cached request is never
sent again, a 4xx answer is cached too), the snapshot schedule (every interval stabbed, every request before the
start), and the snapshot parser (pre-game Pinnacle rows only)."""

import json

import pandas as pd
import pytest
import requests

import data as D

KEY = "FAKEKEY0123456789abcdef"  # a made-up key for the fake session; the real one is never in a test
T0 = 1_785_000_000.0


class FakeResponse:
    def __init__(self, status, body, last=10, used=1000):
        self.status_code = status
        self._body = body
        self.headers = {"x-requests-last": str(last), "x-requests-used": str(used), "x-requests-remaining": "99"}

    def json(self):
        return self._body


def snapshot_body(ts=T0, commence=T0 + 600, extra_events=()):
    def ev(eid, home, away, c, prices):
        return {"id": eid, "sport_key": "baseball_mlb", "commence_time": D.iso(c), "home_team": home,
                "away_team": away, "bookmakers": [{"key": "pinnacle", "last_update": D.iso(ts - 30), "markets": [
                    {"key": "h2h", "last_update": D.iso(ts - 30), "outcomes": [
                        {"name": home, "price": prices[0]}, {"name": away, "price": prices[1]}]}]}]}

    data = [ev("e1", "Minnesota Twins", "Kansas City Royals", commence, (1.6, 2.5)),
            ev("e0", "Old Home", "Old Away", ts - 60, (1.9, 1.9))]  # already started: dropped by the builder
    data += list(extra_events)
    return {"timestamp": D.iso(ts), "previous_timestamp": D.iso(ts - 300), "next_timestamp": D.iso(ts + 300),
            "data": data}


class FakeSession:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = list(responses or [])

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        if self.responses:
            r = self.responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        return FakeResponse(200, snapshot_body())


def client(tmp_path, session, cap=1000):
    led = D.Ledger(tmp_path / "credits.json", cap=cap)
    return D.OddsClient(key=KEY, ledger=led, cache=tmp_path / "cache", session=session, sleep_s=0.0)


def test_redact():
    assert D.redact(f"https://x/?apiKey={KEY}&a=1", KEY) == "https://x/?apiKey=***&a=1"
    assert D.redact("nothing", None) == "nothing"


def test_cache_first_and_the_key_is_never_written(tmp_path):
    s = FakeSession()
    c = client(tmp_path, s)
    body = c.historical_odds("baseball_mlb", T0)
    assert body["data"][0]["id"] == "e1" and len(s.calls) == 1
    assert s.calls[0][1]["apiKey"] == KEY and s.calls[0][1]["bookmakers"] == "pinnacle"
    assert s.calls[0][1]["markets"] == "h2h" and s.calls[0][1]["date"] == D.iso(T0)
    c.historical_odds("baseball_mlb", T0)
    assert len(s.calls) == 1  # cached: never sent twice
    for p in tmp_path.rglob("*"):
        if p.is_file():
            assert KEY not in p.read_text()
    st = c.ledger.status()
    assert st["spent"] == 10 and st["calls"] == 1 and st["api_used"] == 1000


def test_ledger_cap_is_checked_before_the_call(tmp_path):
    s = FakeSession()
    c = client(tmp_path, s, cap=25)
    c.historical_odds("baseball_mlb", T0)
    c.historical_odds("baseball_mlb", T0 + 300)
    with pytest.raises(D.BudgetExceeded):
        c.historical_odds("baseball_mlb", T0 + 600)
    assert len(s.calls) == 2 and c.ledger.status()["spent"] == 20


def test_fetch_plan_stops_at_the_cap_and_at_its_own_limit(tmp_path):
    plan = pd.DataFrame({"sport_key": ["baseball_mlb"] * 5, "request_ts": [T0 + 300 * i for i in range(5)],
                         "n_intervals": 1})
    s = FakeSession()
    out = D.fetch_plan(plan, client(tmp_path, s, cap=30))
    assert out["fetched"] == 3 and out["lab_spent"] == 30
    s2 = FakeSession()
    out2 = D.fetch_plan(plan, client(tmp_path / "b", s2, cap=1000), max_credits=20)
    assert out2["fetched"] == 2 and len(s2.calls) == 2


def test_errors_are_redacted_and_4xx_is_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(D.time, "sleep", lambda *_: None)  # no real waiting in the retry loop
    boom = requests.ConnectionError(f"Max retries exceeded with url: /v4/x?apiKey={KEY}")
    s = FakeSession([boom, FakeResponse(422, {"message": "bad"}, last=0)])
    c = client(tmp_path, s)
    assert c.historical_odds("tennis_x", T0) is None
    assert c.historical_odds("tennis_x", T0) is None  # the negative answer is cached
    assert len(s.calls) == 2
    s3 = FakeSession([boom] * 6)
    with pytest.raises(RuntimeError) as e:
        client(tmp_path / "c", s3).historical_odds("tennis_y", T0)
    assert KEY not in str(e.value) and "***" in str(e.value)


def test_missing_key_refuses(tmp_path, monkeypatch):
    monkeypatch.delenv(D.KEY_ENV, raising=False)
    c = D.OddsClient(key=None, ledger=D.Ledger(tmp_path / "l.json"), cache=tmp_path, session=FakeSession())
    with pytest.raises(RuntimeError):
        c.historical_odds("baseball_mlb", T0)


def test_plan_snapshots_stabs_every_interval_before_the_start():
    starts = [T0, T0 + 300, T0 + 3 * 3600, T0 + 86400]
    games = pd.DataFrame({"game_id": [f"g{i}" for i in range(4)], "game_start": starts,
                          "sport_keys": [json.dumps(["baseball_mlb"])] * 4})
    plan = D.plan_snapshots(games)
    req = plan["request_ts"].to_numpy()
    for c in starts:
        for o in D.OFFSETS_MIN:
            before, after = D.WINDOW_MIN[o]
            lo, hi = c - (o + before) * 60, c - (o - after) * 60
            assert ((req >= lo) & (req <= hi)).any(), (c, o)
            assert hi < c  # every interval ends before the start
    assert len(plan) < len(starts) * len(D.OFFSETS_MIN)  # games of one sport share snapshots
    assert D.plan_snapshots(games.assign(game_start=float("nan"))).empty


def test_parse_and_build_keep_pregame_pinnacle_rows(tmp_path):
    s = FakeSession()
    c = client(tmp_path, s)
    c.historical_odds("baseball_mlb", T0)
    pin = D.build_pinnacle(cache=tmp_path / "cache", out=tmp_path / "pin.parquet")
    assert pin["event_id"].tolist() == ["e1"]
    r = pin.iloc[0]
    assert r["snap_ts"] == T0 and r["commence"] == T0 + 600 and r["home"] == "Minnesota Twins"
    assert json.loads(r["prices"]) == [1.6, 2.5]
    ev = D.events_table(pin)
    assert ev.iloc[0]["away"] == "Kansas City Royals"
