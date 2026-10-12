"""The owner's "far from the line" rule for real Bitcoin buys (nightcrawler.btcdistance, 2026-10-12)."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nightcrawler import btcdistance as B
from nightcrawler import polydesk as P
from tests.test_polydesk import NOW
from tests.test_polydesk_live import FakeExchange, FakeLedger, _live_settings
from tests.test_polydesk_safety import Gateway2, _market, _practice, _real, _skips


def _candles(now: float, spot: float, step: float = 0.0002, n: int = 120) -> list[B.Candle]:
    """n one-minute candles ending at the minute holding ``now``, closes alternating +-step (sigma = step)."""
    last = math.floor(now / 60.0) * 60.0
    closes = [spot * math.exp(step * (1 if k % 2 else -1) * 0.5) for k in range(n)]
    closes[-1] = spot
    return [(last - 60.0 * (n - 1 - k), closes[k - 1] if k else closes[0], closes[k]) for k in range(n)]


def _ts(text: str) -> float:
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=UTC).timestamp()


def test_parse_reads_the_strike_and_the_window() -> None:
    assert B.parse("cpc-btc-above-hr-2026-10-12-1600z-82500") == {"kind": "above", "strike": 82500.0}
    up = B.parse("cpc-btc-updown-15m-2026-10-12-0430z")
    assert up == {"kind": "updown", "start_ts": _ts("2026-10-12 04:30"), "window_s": 900.0}
    assert B.parse("cpc-btc-range-hr-2026-10-12-1600z-82500-83000") is None
    assert B.is_crypto("cpc-btc-anything") and not B.is_crypto("aec-nfl-chi-gb-2026-10-11")


def test_sigma_is_the_root_mean_square_of_complete_minutes() -> None:
    now = _ts("2026-10-12 13:36") + 5
    sig = B.sigma_per_minute(_candles(now, 82_464.0, step=0.0004), now)
    assert sig is not None and sig == pytest.approx(0.0004, rel=0.02)
    assert B.sigma_per_minute(_candles(now, 82_464.0, n=30), now) is None  # too few minutes: no verdict


def test_the_owners_example_and_a_close_call() -> None:
    """2026-10-12 13:36 UTC: BTC about $82,464, line $81,900, 24 minutes left. Quiet hour (sigma 0.02 %/min): far."""
    now = _ts("2026-10-12 13:36")
    end = _ts("2026-10-12 14:00")
    far = B.Distance(fetch=lambda: _candles(now, 82_464.0, step=0.0002))
    z, why = far.check("cpc-btc-above-hr-2026-10-12-1400z-81900", end, now)
    assert why is None and z is not None and z > B.MIN_Z
    close = B.Distance(fetch=lambda: _candles(now, 82_000.0, step=0.0010))
    z, why = close.check("cpc-btc-above-hr-2026-10-12-1400z-81900", end, now)
    assert why == "too_close" and z is not None and z < B.MIN_Z


def test_updown_measures_from_the_windows_open() -> None:
    now = _ts("2026-10-12 04:42")
    cs = _candles(now, 82_000.0, step=0.0001)
    start = _ts("2026-10-12 04:30")
    cs = [(t, 81_000.0 if t == start else o, c) for t, o, c in cs]  # opened $1,000 lower: far above the open
    z, why = B.Distance(fetch=lambda: cs).check("cpc-btc-updown-15m-2026-10-12-0430z", start + 900, now)
    assert why is None and z is not None and z > 10


def test_it_fails_closed() -> None:
    now = _ts("2026-10-12 13:36")

    def broken() -> list[B.Candle]:
        raise RuntimeError("feed down")

    assert B.Distance(fetch=broken).check("cpc-btc-above-hr-2026-10-12-1400z-81900", now + 1440, now) == (
        None, "distance_unknown")
    good = B.Distance(fetch=lambda: _candles(now, 82_464.0))
    assert good.check("cpc-btc-range-hr-x", now + 1440, now) == (None, "distance_unknown")  # unknown market
    assert good.check("cpc-btc-above-hr-2026-10-12-1400z-81900", now - 1, now) == (None, "distance_unknown")


class _Fixed(B.Distance):
    def __init__(self, z: float | None, why: str | None) -> None:
        super().__init__(fetch=list)
        self.result = (z, why)

    def check(self, slug: str, end_ts: float, now: float | None = None,
              price: float | None = None) -> tuple[float | None, str | None]:
        return self.result


@pytest.fixture
def gw(monkeypatch: pytest.MonkeyPatch) -> Gateway2:
    g = Gateway2()
    monkeypatch.setattr(P, "_get", g.get)
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    return g


@pytest.mark.parametrize(("z", "why", "real"), [(5.2, None, 1), (2.1, "too_close", 0), (None, "distance_unknown", 0)])
def test_the_desk_buys_real_bitcoin_only_far_from_the_line(gw: Gateway2, tmp_path: Path, z: float | None,
                                                           why: str | None, real: int) -> None:
    gw.markets = [_market("cpc-btc-above-hr-2026-10-12-1400z-81900", "crypto", 1800)]
    gw.quotes = {m["slug"]: (0.98, 0.99) for m in gw.markets}
    ex = FakeExchange(cash=25.0)
    settings = _live_settings(tmp_path)
    desk = P.PolyDesk(settings, ledger=FakeLedger(), client_factory=ex, distance=_Fixed(z, why))
    desk.poll(NOW)
    assert len(ex.orders) == real and len(_real(desk)) == real
    if not real:  # waits: no paper twin, not tried, so the next round judges it again; counted for the page
        assert _practice(desk) == {}
        assert "cpc-btc-above-hr-2026-10-12-1400z-81900" not in desk.state["tried"]
        assert _skips(settings)["counts"] == {why: 1}


def test_a_too_close_rung_does_not_block_a_farther_one(gw: Gateway2, tmp_path: Path) -> None:
    near, far = "cpc-btc-above-hr-2026-10-12-1400z-82400", "cpc-btc-above-hr-2026-10-12-1400z-81900"
    gw.markets = [_market(near, "crypto", 1800), _market(far, "crypto", 1800)]
    gw.quotes = {near: (0.97, 0.98), far: (0.98, 0.99)}

    class ByStrike(_Fixed):
        def check(self, slug: str, end_ts: float, now: float | None = None,
                  price: float | None = None) -> tuple[float | None, str | None]:
            return (2.0, "too_close") if slug == near else (4.6, None)

    ex = FakeExchange(cash=25.0)
    desk = P.PolyDesk(_live_settings(tmp_path), ledger=FakeLedger(), client_factory=ex, distance=ByStrike(None, None))
    desk.poll(NOW)
    assert [o["slug"] for o in ex.orders] == [far] and set(_real(desk)) == {far}


def test_other_markets_skip_the_check(gw: Gateway2, tmp_path: Path) -> None:
    gw.markets = [_market("wx-nyc-high-2026-10-12", "weather", 1800)]
    gw.quotes = {m["slug"]: (0.98, 0.99) for m in gw.markets}
    ex = FakeExchange(cash=25.0)
    desk = P.PolyDesk(_live_settings(tmp_path), ledger=FakeLedger(), client_factory=ex,
                      distance=_Fixed(None, "distance_unknown"))
    desk.poll(NOW)
    assert len(ex.orders) == 1


def test_the_bar_depends_on_price_and_time_left() -> None:
    assert B.required_z(0.99, 25) == 3.3 and B.required_z(0.98, 8) == 2.2 and B.required_z(0.95, 50) == 2.0
    assert B.required_z(0.90, 8) == B.REQUIRED_Z[10][0.95]  # under 95c: the 95c column (more distance than needed)
    assert B.required_z(0.985, 8) == B.REQUIRED_Z[10][0.99]  # a part cent rounds up: the stricter column
    assert B.required_z(None, 8) == B.MIN_Z and B.required_z(0.99, 61) is None and B.required_z(0.99, 0) is None


def test_a_cheaper_price_needs_less_distance() -> None:
    """2.5 units with 8 minutes left: enough at 97c (bar 1.9), not at 99c (bar 2.8)."""
    now = _ts("2026-10-12 13:52")
    end = _ts("2026-10-12 14:00")
    sig = 0.0004
    spot = 81_900.0 * math.exp(2.5 * sig * math.sqrt(8.0))
    d = B.Distance(fetch=lambda: _candles(now, spot, step=sig))
    z, why = d.check("cpc-btc-above-hr-2026-10-12-1400z-81900", end, now, price=0.97)
    assert why is None and z == pytest.approx(2.5, abs=0.15)
    assert d.check("cpc-btc-above-hr-2026-10-12-1400z-81900", end, now, price=0.99)[1] == "too_close"
