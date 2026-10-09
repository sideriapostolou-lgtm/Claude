"""Lab 3 data loader: only finished bars. Coinbase's ``end`` is inclusive, so a request ending at ``until`` also
returns the candle that OPENS at ``until`` (still open when ``until`` is today's 00:00 UTC or this hour); the loader
promises [since, until) and must drop it, and a stale open bar kept by an older cache is dropped and fetched again
(erratum 2026-10-09: the first cache kept 2026-10-09's bar, taken at 12:24 UTC)."""

import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import data as D

DAY = 86_400


def _coinbase(closes: dict[int, float]):
    """A fake ``/candles``: every bar whose OPEN is within [start, end], both ends included (as Coinbase does)."""

    def get(url: str, params: dict, tries: int = 5) -> list:
        lo = datetime.fromisoformat(params["start"]).timestamp()
        hi = datetime.fromisoformat(params["end"]).timestamp()
        return [[ts, c, c, c, c, 10.0] for ts, c in sorted(closes.items(), reverse=True) if lo <= ts <= hi]

    return get


def test_fetch_product_keeps_since_until_and_drops_the_open_bar(monkeypatch) -> None:
    until = datetime(2026, 10, 9, tzinfo=UTC)
    end = int(until.timestamp())
    closes = {end - k * DAY: 100.0 + k for k in range(1, 6)} | {end: 999.0}  # the bar at ``until`` is still open
    monkeypatch.setattr(D, "_get", _coinbase(closes))
    monkeypatch.setattr(D.time, "sleep", lambda s: None)
    df = D.fetch_product("BTC-USD", DAY, datetime(2026, 10, 4, tzinfo=UTC), until)
    assert list(df["ts"]) == [end - k * DAY for k in range(5, 0, -1)]
    assert int(df["ts"].max()) < end and 999.0 not in set(df["close"])


def test_run_drops_an_open_bar_an_older_cache_kept(monkeypatch, tmp_path: Path) -> None:
    now = datetime(2026, 10, 10, 12, 24, tzinfo=UTC)
    today = int(datetime(2026, 10, 10, tzinfo=UTC).timestamp())
    yesterday = today - DAY

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):  # datetime.now's own signature
            return now

    old = pd.DataFrame([{"asset": "BTC", "ts": yesterday - k * DAY, "low": 1.0, "high": 1.0, "open": 1.0,
                         "close": 100.0 - k, "volume": 1.0, "src": "coinbase"} for k in range(3, -1, -1)]
                       + [{"asset": "BTC", "ts": today, "low": 1.0, "high": 1.0, "open": 1.0, "close": 555.0,
                           "volume": 1.0, "src": "coinbase"}])  # today's bar, cached while it was still open
    old.to_parquet(tmp_path / "candles_1d.parquet", index=False)
    closes = {yesterday - k * DAY: 100.0 - k for k in range(4)} | {yesterday: 101.0, today: 777.0}
    monkeypatch.setattr(D, "datetime", Clock)
    monkeypatch.setattr(D, "_get", _coinbase(closes))
    monkeypatch.setattr(D.time, "sleep", lambda s: None)
    D.run("1d", ["BTC"], tmp_path)
    df = pd.read_parquet(tmp_path / "candles_1d.parquet")
    assert int(df["ts"].max()) == yesterday and not (df["ts"] >= today).any()
    assert df.set_index("ts").loc[yesterday, "close"] == 101.0  # the finished bar, fetched again
