"""The trend desk (nightcrawler.trenddesk): a PAPER forward test of lab 3's T3 "sma50" rule on BTC, ETH and SOL.

* The rule and its timing: the decision at day t reads closes up to t only; the swap is at t's close and earns from
  t+1 on; nothing later can change what was booked.
* PARITY with lab 3's own code (``research/lab3/core.py`` + ``hypotheses.py``, imported here only): on real
  Coinbase candles (``tests/fixtures/trenddesk``), with a gap and a missing day too, the desk's daily positions and
  equity are the lab's, bit for bit.
* Costs (25 bps per side + $0.02 per swap on the sleeve), flips and their events, the forward-test start, the
  runtime (fetch, completed days only, late candles, failed fetches that keep the state and say so, restarts, catch
  up, receipts, schedule), the page / town / team-room JSON and wording (never summed with anything), the page
  script (text only, CSP hashes in sync) and the engine wiring (off / on / a crash never stops the bot).
"""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.util
import inspect
import json
import re
import sys
import threading
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import requests
from fakes import FakeClock, FakeHttp, FakeRequest
from test_page import (  # noqa: F401 - shared fixture
    JARGON,
    NOW,
    no_learning_module,
    page_script,
    seed,
)

from nightcrawler import trenddesk as T
from nightcrawler.clock import utc_day
from nightcrawler.config import Settings
from nightcrawler.http import HttpClient
from nightcrawler.ledger import Ledger
from nightcrawler.page import PAGE_CSP, render_page_html
from nightcrawler.pagestate import (
    PAPER_LABEL,
    build_page_state,
    town_ledger,
    trend_desk,
)
from nightcrawler.teamroom import build_team_state

ROOT = Path(__file__).resolve().parents[1]
LAB3 = ROOT / "research" / "lab3"
FIXTURE = Path(__file__).parent / "fixtures" / "trenddesk" / "candles_1d.csv"
DAY = 86_400.0
MINUS = "−"
FEE_ONE = 100.0 / 3 * 25 / 1e4 + 0.02  # one swap of a third of a $100 book: 25 bps + the $0.02 network fee


# --------------------------------------------------------------------------- helpers


@pytest.fixture
def ledger(tmp_path: Path, fake_clock: FakeClock) -> Iterator[Ledger]:
    with Ledger(tmp_path / "nc.db", clock=fake_clock) as led:
        yield led


def fixture_candles() -> dict[str, dict[str, tuple[float, float]]]:
    out: dict[str, dict[str, tuple[float, float]]] = {c: {} for c in T.COINS}
    with FIXTURE.open(newline="") as fh:
        for r in csv.DictReader(fh):
            out[r["coin"]][r["day"]] = (float(r["close"]), float(r["volume"]))
    return out


def synthetic(closes: dict[str, list[float | None]], start: str = "2026-01-01", volume: float = 1e6) -> list[T.Row]:
    """Rows for consecutive UTC days from ``start``; ``None`` is a missing candle."""
    n = len(closes["BTC"])
    rows: list[T.Row] = []
    for i in range(n):
        day = utc_day(T.day_start(start) + i * DAY)
        per: dict[str, tuple[float | None, float | None]] = {}
        for c in T.COINS:
            value = closes[c][i]
            per[c] = (value, volume) if value is not None else (None, None)
        rows.append((day, per))
    return rows


def series(*parts: tuple[float, int]) -> list[float | None]:
    """``series((100.0, 60), (110.0, 1))``: each value repeated that many days."""
    return [value for value, days in parts for _ in range(days)]


def cross(n: int = 70) -> dict[str, list[float | None]]:
    """BTC flat at 100 for 60 days, 110 on day 60 (above its average), 112 for five days, 90 on day 66 (below);
    ETH and SOL flat at 100 (a close equal to its average is not above it: out)."""
    btc = series((100.0, 60), (110.0, 1), (112.0, 5), (90.0, n - 66))
    return {"BTC": btc, "ETH": series((100.0, n)), "SOL": series((100.0, n))}


def coinbase(candles: dict[str, dict[str, tuple[float, float]]]) -> Callable[[FakeRequest], Any]:
    """A fake Coinbase candles endpoint: ``[time, low, high, open, close, volume]`` rows, newest first, for every bar
    that OPENS within [start, end] (the bar of the current day too, still open: the desk must skip it)."""

    def ts(text: str) -> float:
        return datetime.fromisoformat(text).timestamp()

    def respond(req: FakeRequest) -> Any:
        match = re.search(r"/products/([A-Z]+)-USD/candles", req.url)
        assert match is not None and req.params is not None and req.params["granularity"] == 86400
        lo, hi = ts(req.params["start"]), ts(req.params["end"])
        rows = [[int(T.day_start(d)), c * 0.98, c * 1.02, c, c, v] for d, (c, v) in candles[match.group(1)].items()
                if lo <= T.day_start(d) <= hi]
        return sorted(rows, reverse=True)

    return respond


def at(day: str, seconds: float = 400.0) -> float:
    """``seconds`` after the START of ``day`` (00:06:40 UTC by default: just after the desk's daily poll time)."""
    return T.day_start(day) + seconds


def save(settings: Settings, state: dict[str, Any]) -> None:
    T.save_state(T.state_path(settings), state)


def booked_state(*, last_day: str = "2026-10-07", started: str = "2026-10-01", equity: float = 101.20,
                 hold: float = 100.40, before: tuple[float, float] = (100.90, 100.10),
                 in_market: tuple[str, ...] = ("BTC", "SOL")) -> dict[str, Any]:
    """A desk that booked a week: the rule's book +$1.20 since start (+$0.30 on the last day), holding +$0.40."""
    st = T.empty_state()
    st.update({"sleeve_usd": 100.0, "started": started, "started_at": T.day_start(started) + 600, "last_day": last_day,
               "last_ok": NOW - 600, "last_fetch": NOW - 600})
    prev_day = utc_day(T.day_start(last_day) - DAY)
    st["history"] = [
        {"day": prev_day, "ts": T.close_ts(prev_day), "equity_usd": before[0], "hold_usd": before[1], "in": []},
        {"day": last_day, "ts": T.close_ts(last_day), "equity_usd": equity, "hold_usd": hold, "in": list(in_market)},
    ]
    for c in T.COINS:
        st["positions"][c] = {"in": c in in_market, "since": "2026-10-03", "entry_price": 100.0 if c in in_market
                              else None, "last_close": 100.0}
    st["events"] = [{"ts": T.close_ts("2026-10-03"), "text": "Trend desk: BTC closed above its 50-day average -> in "
                     "(paper)", "tone": "neutral"}]
    return st


# --------------------------------------------------------------------------- the rule and its timing


def test_the_signal_is_the_close_against_its_own_50_day_average_up_to_that_close() -> None:
    closes: list[float | None] = [100.0 + (i % 7) for i in range(80)]
    for t in range(49, 80):
        window = [float(c) for c in closes[t - 49:t + 1] if c is not None]
        assert T.sma_signal(closes[: t + 1]) is (window[-1] > sum(window) / 50)
    assert T.sma_signal([101.0] * 49) is False  # fewer than 50 closes: no average, no signal
    assert T.sma_signal([100.0] * 49 + [100.0]) is False  # equal to the average is not above it
    gap = [100.0] * 20 + [None] + [100.0] * 28 + [130.0]
    assert T.sma_signal(gap) is False  # a missing candle inside the 50 days: the lab's average is undefined
    assert T.sma_signal([100.0] * 49 + [130.0]) is True


def test_nothing_after_a_close_can_change_what_was_booked_at_it() -> None:
    """No lookahead: the record up to day t is identical whatever the candles after t say."""
    rows = synthetic(cross())
    _, base = T.replay(rows, "2026-02-20", 100.0)
    for cut in (60, 63, 66):
        later = [(d, {c: ((v[0] * 3.0, v[1]) if v[0] is not None else v) for c, v in per.items()}) if i > cut
                 else (d, per) for i, (d, per) in enumerate(rows)]
        _, other = T.replay(later, "2026-02-20", 100.0)
        n = cut - 50 + 1  # days booked up to and including the cut (the record starts at row 50)
        for a, b in zip(base[:n], other[:n], strict=True):
            assert (a["day"], a["in"], a["growth"], a["equity_usd"]) == (b["day"], b["in"], b["growth"], b["equity_usd"])
    decision = T.decide(rows[:61])
    assert decision["BTC"] == (True, True, "above") and decision["ETH"] == (True, False, "below")


def test_the_swap_is_at_the_close_and_earns_only_from_the_next_day() -> None:
    rows = synthetic(cross())
    _, days = T.replay(rows, rows[50][0], 100.0)
    by_day = {d["day"]: d for d in days}
    d60, d61, d62 = (by_day[rows[i][0]] for i in (60, 61, 62))
    assert d60["in"] == ["BTC"] and [(s["coin"], s["side"], s["price"]) for s in d60["swaps"]] == [("BTC", "buy", 110.0)]
    assert d60["growth"] == 1.0  # the jump to 110 happened BEFORE the swap: the book did not earn it
    assert d60["equity_usd"] == pytest.approx(100.0 - FEE_ONE)  # the fee shows on the day it is paid
    cost = 1 / 3 * 25 / 1e4 + 0.02 / 100  # the lab books it in the next day's return
    assert d61["growth"] == pytest.approx(1.0 + (112 / 110 - 1) / 3 - cost, rel=1e-15)
    assert d62["growth"] == pytest.approx(d61["growth"], rel=1e-15)  # 112 -> 112: nothing earned, nothing paid
    assert all(by_day[rows[i][0]]["growth"] == 1.0 for i in range(50, 60))  # all cash before the cross


# --------------------------------------------------------------------------- parity with research/lab3


_LAB3_NAMES = ("lab3_core_for_trenddesk", "lab3_hypotheses_for_trenddesk")


def _lab3() -> tuple[Any, ModuleType, ModuleType]:
    """Lab 3's own modules, loaded from research/lab3 by path under names of their own (other labs have a ``core``
    too); ``hypotheses`` imports ``core`` by that bare name, so it is pointed at lab 3's while it loads."""
    pd = pytest.importorskip("pandas")
    pytest.importorskip("numpy")
    if not (LAB3 / "core.py").exists() or not (LAB3 / "hypotheses.py").exists():  # pragma: no cover - tree absent
        pytest.skip("research/lab3 is not in this checkout")
    if all(name in sys.modules for name in _LAB3_NAMES):
        return pd, sys.modules[_LAB3_NAMES[0]], sys.modules[_LAB3_NAMES[1]]

    def load(name: str, file: str) -> ModuleType:
        spec = importlib.util.spec_from_file_location(name, LAB3 / file)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module  # dataclasses look their module up while the class is made
        spec.loader.exec_module(module)
        return module

    saved = sys.modules.get("core")
    core = load(_LAB3_NAMES[0], "core.py")
    sys.modules["core"] = core
    try:
        hyp = load(_LAB3_NAMES[1], "hypotheses.py")
    finally:
        if saved is None:
            sys.modules.pop("core", None)
        else:
            sys.modules["core"] = saved
    return pd, core, hyp


def _lab_runs(pd: Any, core: ModuleType, hyp: ModuleType, candles: dict[str, dict[str, tuple[float, float]]],
              start: str, sleeve: float) -> tuple[Any, Any, Any]:
    """The lab's T3 sma50 and its buy-and-hold benchmark, exactly as ``run.py`` builds them (the universe restricted
    to the majors), as a forward run: the target is zeroed before ``start`` (nothing held before the desk ran)."""
    recs = [{"asset": c, "date": pd.Timestamp(d, tz="UTC"), "open": cl, "high": cl, "low": cl, "close": cl, "volume": v}
            for c, days in candles.items() for d, (cl, v) in days.items()]
    P = core.panel(pd.DataFrame(recs).sort_values(["asset", "date"]))
    U = core.universe_mask(P)
    U.loc[:, [c for c in U.columns if c not in hyp.T3["universe"]]] = False
    begin = pd.Timestamp(start, tz="UTC")
    # from here on the majors pass the lab's history and volume filters: only a missing candle takes one out
    assert bool((U == P.close.notna())[U.index >= begin].all(axis=None))
    (sma50,) = [p for p in hyp.T3["GRID"] if hyp.T3["config_key"](p) == "sma50"]
    target = hyp.T3["signal"](P, sma50)
    target.loc[target.index < begin] = 0.0
    hold = core.buy_and_hold(P, U)
    hold.loc[hold.index < begin] = 0.0
    costs = core.Costs(capital_usd=sleeve)
    assert (costs.bps_side, costs.network_usd) == (T.COST_BPS_SIDE, T.NETWORK_USD)
    return core.backtest(P, target, "test", costs, U), core.backtest(P, hold, "test", costs, U), P


def _assert_parity(pd: Any, days: list[dict[str, Any]], run: Any, hold: Any) -> int:
    eq, eqh = run.equity(), hold.equity()
    held_next = {ts: [c for c in T.COINS if run.held.loc[ts, c] > 0] for ts in run.held.index}
    index = list(run.held.index)
    checked = 0
    for d in days:
        ts = pd.Timestamp(d["day"], tz="UTC")
        assert d["growth"] == eq[ts], d["day"]  # the same equity, bit for bit
        assert d["hold_growth"] == eqh[ts], d["day"]
        pos = index.index(ts)
        if pos + 1 < len(index):  # the position decided at this close is the one the lab holds the next day
            assert d["in"] == held_next[index[pos + 1]], d["day"]
        checked += 1
    return checked


@pytest.mark.parametrize("start,sleeve", [("2026-03-23", 100.0), ("2026-05-01", 100.0), ("2026-08-15", 1000.0)])
def test_parity_with_lab3_on_real_coinbase_candles(start: str, sleeve: float) -> None:
    pd, core, hyp = _lab3()
    candles = fixture_candles()
    run, hold, _ = _lab_runs(pd, core, hyp, candles, start, sleeve)
    _, days = T.replay(T.calendar(candles), start, sleeve)
    assert days[0]["day"] == start and days[-1]["day"] == "2026-10-08"
    assert _assert_parity(pd, days, run, hold) == len(days) >= 54
    assert sum(len(d["swaps"]) for d in days) >= 4  # the rule really flipped inside the window
    first = days[0]
    assert first["equity_usd"] == pytest.approx(sleeve - sum(s["fee_usd"] for s in first["swaps"]))


def test_parity_with_lab3_through_a_missing_candle_and_a_missing_day() -> None:
    """A candle missing for one coin (ETH on 2026-06-10: out of the universe that day, its 50-day average undefined for
    50 days, as the lab books it) and a day missing for all three (2026-07-04: two days' move in one row)."""
    pd, core, hyp = _lab3()
    candles = fixture_candles()
    del candles["ETH"]["2026-06-10"]
    for c in T.COINS:
        del candles[c]["2026-07-04"]
    rows = T.calendar(candles)
    assert "2026-07-04" not in [d for d, _ in rows] and rows[[d for d, _ in rows].index("2026-06-10")][1]["ETH"] == (
        None, None)
    run, hold, _ = _lab_runs(pd, core, hyp, candles, "2026-05-15", 100.0)
    _, days = T.replay(rows, "2026-05-15", 100.0)
    assert _assert_parity(pd, days, run, hold) == len(days)
    by_day = {d["day"]: d for d in days}
    assert "ETH" not in by_day["2026-06-10"]["in"]
    assert all("ETH" not in by_day[d]["in"] for d in by_day if "2026-06-10" <= d <= "2026-07-29")


# --------------------------------------------------------------------------- costs and flips


def test_costs_are_25_bps_per_side_plus_two_cents_a_swap_on_the_sleeve() -> None:
    rows = synthetic({"BTC": series((100.0, 60), (110.0, 3)), "ETH": series((100.0, 60), (120.0, 3)),
                      "SOL": series((100.0, 63))})
    for sleeve in (100.0, 1000.0):
        state, days = T.replay(rows, rows[59][0], sleeve)
        day60 = days[1]
        assert [(s["coin"], s["side"]) for s in day60["swaps"]] == [("BTC", "buy"), ("ETH", "buy")]
        for s in day60["swaps"]:
            assert s["amount_usd"] == pytest.approx(sleeve / 3)
            assert s["fee_usd"] == pytest.approx(sleeve / 3 * 0.0025 + 0.02)  # the network fee is dollars, not a share
        assert day60["equity_usd"] == pytest.approx(sleeve - 2 * (sleeve / 3 * 0.0025 + 0.02))
        frac = 2 * (1 / 3 * 25 / 1e4 + 0.02 / sleeve)
        assert days[2]["growth"] == pytest.approx(1.0 - frac, rel=1e-15)  # flat prices: only the fees
        assert days[2]["equity_usd"] == pytest.approx(sleeve * (1.0 - frac))
        assert state["counters"]["swaps"] == 2


def test_holding_the_three_is_the_benchmark_bought_at_the_start_close() -> None:
    rows = synthetic(cross())
    _, days = T.replay(rows, rows[50][0], 100.0)
    first = days[0]
    assert first["hold_usd"] == pytest.approx(100.0 - 3 * FEE_ONE)  # three buys at the first close
    after = {d["day"]: d for d in days}[rows[61][0]]
    expected = (1 - 3 * (1 / 3 * 25 / 1e4 + 0.0002))  # the first day after the start: only the fees
    assert {d["day"]: d for d in days}[rows[51][0]]["hold_growth"] == pytest.approx(expected, rel=1e-15)
    assert after["hold_growth"] > 1.0 - 0.01


def test_flips_are_swaps_at_the_close_with_events_and_entry_prices() -> None:
    rows = synthetic(cross())
    state, _ = T.replay(rows, rows[50][0], 100.0)
    trades = state["trades"]
    assert [(t["coin"], t["side"], t["price"], t["day"]) for t in reversed(trades)] == [
        ("BTC", "buy", 110.0, rows[60][0]), ("BTC", "sell", 90.0, rows[66][0])]
    texts = [e["text"] for e in reversed(state["events"])]
    assert texts == ["Trend desk: BTC closed above its 50-day average -> in (paper)",
                     "Trend desk: BTC closed below its 50-day average -> out (paper)"]
    assert state["events"][0]["ts"] == T.close_ts(rows[66][0])  # stamped at the close the swap happened at
    pos = state["positions"]["BTC"]
    assert pos["in"] is False and pos["exit_price"] == 90.0 and pos["entry_was"] == 110.0 and pos["since"] == rows[66][0]
    assert state["positions"]["ETH"]["in"] is False and state["positions"]["ETH"]["since"] is None  # never held


def test_a_missing_candle_takes_the_coin_out_and_says_why() -> None:
    closes = cross(80)
    closes["BTC"][62] = None
    state, _ = T.replay(synthetic(closes), "2026-02-20", 100.0)
    texts = [e["text"] for e in reversed(state["events"])]
    assert texts[:2] == ["Trend desk: BTC closed above its 50-day average -> in (paper)",
                         "Trend desk: BTC has no daily candle for the day -> out (paper)"]
    sell = [t for t in state["trades"] if t["side"] == "sell"][-1]
    assert sell["price"] == 112.0 and sell["why"] == "no_bar"  # the last close it had: never a made-up price


# --------------------------------------------------------------------------- the runtime


def desk_for(settings: Settings, fake_http: FakeHttp, http_client: HttpClient,
             candles: dict[str, dict[str, tuple[float, float]]] | None = None, **kw: Any) -> T.TrendDesk:
    fake_http.register("api.exchange.coinbase.com/products/", coinbase(candles or fixture_candles()))
    return T.TrendDesk(settings, http=http_client, **kw)


def test_the_record_starts_the_day_the_desk_first_ran_and_books_completed_days_only(
        settings: Settings, fake_http: FakeHttp, http_client: HttpClient) -> None:
    desk = desk_for(settings, fake_http, http_client)
    out = desk.poll(at("2026-06-01", 15 * 3600))  # 400 days of history are there: none of it is booked
    assert out == {"booked": 0, "last_day": None, "error": None}
    st = T.load_state(T.state_path(settings))
    assert st["started"] == "2026-06-01" and st["history"] == [] and st["sleeve_usd"] == 100.0
    assert st["events"][0]["text"] == ("Trend desk started (paper): first swaps at the close of 2026-06-01 "
                                       "(UTC midnight)")
    calls = fake_http.calls_to("/products/BTC-USD/candles")
    assert calls[0].params is not None
    since = datetime.fromisoformat(calls[0].params["start"]).timestamp()
    assert at("2026-06-01", 15 * 3600) - since >= 120 * DAY  # enough history for the 50-day average
    assert len(fake_http.calls) == 3  # one request per coin
    out = desk.poll(at("2026-06-02"))  # the fake also serves 2026-06-02's bar, still open: never used
    assert out["booked"] == 1 and out["last_day"] == "2026-06-01"
    st = T.load_state(T.state_path(settings))
    assert [h["day"] for h in st["history"]] == ["2026-06-01"]


def test_day_by_day_with_restarts_equals_one_replay_bit_for_bit(make_settings: Callable[..., Settings],
                                                                 fake_http: FakeHttp, http_client: HttpClient) -> None:
    """The state round trip: a new desk every day (a redeploy) reloads the record from the file and goes on."""
    settings = make_settings()
    candles = fixture_candles()
    fake_http.register("api.exchange.coinbase.com/products/", coinbase(candles))
    T.TrendDesk(settings, http=http_client).poll(at("2026-06-01", 9 * 3600))
    for k in range(1, 26):
        desk = T.TrendDesk(make_settings(TRENDDESK_SLEEVE_USD=500), http=http_client)  # the sleeve is fixed at start
        assert desk.poll(at(utc_day(T.day_start("2026-06-01") + k * DAY)))["booked"] == 1
    st = T.load_state(T.state_path(settings))
    _, days = T.replay(T.calendar(candles), "2026-06-01", 100.0)
    assert len(st["history"]) == 25 and st["sleeve_usd"] == 100.0
    for h, d in zip(st["history"], days, strict=False):
        assert (h["day"], h["in"], h["growth"], h["hold_growth"], h["equity_usd"], h["hold_usd"]) == (
            d["day"], d["in"], d["growth"], d["hold_growth"], d["equity_usd"], d["hold_usd"])
    assert st["book"]["growth"] == days[24]["growth"]


def test_a_pause_is_caught_up_from_the_same_closes(settings: Settings, fake_http: FakeHttp,
                                                   http_client: HttpClient) -> None:
    candles = fixture_candles()
    desk = desk_for(settings, fake_http, http_client, candles)
    desk.poll(at("2026-06-01", 9 * 3600))
    desk.poll(at("2026-06-03"))
    out = desk.poll(at("2026-06-10"))  # the bot was down for a week
    assert out["booked"] == 7 and out["last_day"] == "2026-06-09"
    st = T.load_state(T.state_path(settings))
    _, days = T.replay(T.calendar(candles), "2026-06-01", 100.0)
    assert [h["growth"] for h in st["history"]] == [d["growth"] for d in days[:9]]
    assert st["events"][0]["text"] == "Trend desk caught up 7 daily closes after a pause (paper)"


def test_a_failed_fetch_books_nothing_keeps_the_state_and_says_so(settings: Settings, fake_http: FakeHttp,
                                                                  http_client: HttpClient) -> None:
    candles = fixture_candles()
    desk = desk_for(settings, fake_http, http_client, candles)
    desk.poll(at("2026-06-01", 9 * 3600))
    desk.poll(at("2026-06-02"))
    before = T.load_state(T.state_path(settings))
    for failure in ({"response": None, "status": 503}, {"response": requests.ConnectionError("down")},
                    {"response": {"message": "maintenance"}}):
        fake_http.register("api.exchange.coinbase.com/products/", **failure)  # newest route wins
        now = at("2026-06-03", 2 * 3600)
        out = desk.poll(now)
        assert out["booked"] == 0
        st = T.load_state(T.state_path(settings))
        for key in ("history", "book", "hold", "positions", "trades", "last_day", "started"):
            assert st[key] == before[key], key  # yesterday's state, untouched
        assert st["last_error"].startswith("Coinbase candles not read (")
        assert desk.next_wait(now) == T.RETRY_S
    reasons = desk.state["last_error"]
    assert "an unexpected reply" in reasons
    panel = T.panel_state(settings, at("2026-06-03", 2 * 3600))
    assert panel["problem"] == ("Behind: the book stays at the close of 2026-06-01; Coinbase candles not read (an "
                                "unexpected reply) at 2026-06-03T02:00:00Z. It retries every 15 minutes.")
    assert panel["as_of"] == T.close_ts("2026-06-01") and panel["last_day"] == "2026-06-01"
    fake_http.register("api.exchange.coinbase.com/products/", coinbase(candles))
    assert desk.poll(at("2026-06-03", 3 * 3600))["booked"] == 1  # back: it catches up, and the problem is gone
    assert T.panel_state(settings, at("2026-06-03", 3 * 3600))["problem"] is None
    assert desk.state["last_error"] is None and desk.state["counters"]["errors"] == 3


def test_http_failures_name_the_status_or_the_connection(settings: Settings, fake_http: FakeHttp,
                                                         http_client: HttpClient) -> None:
    desk = desk_for(settings, fake_http, http_client)
    fake_http.register("api.exchange.coinbase.com/products/", None, status=503)
    desk.poll(at("2026-06-01"))
    assert desk.state["last_error"] == "Coinbase candles not read (HTTP 503) at 2026-06-01T00:06:40Z"
    fake_http.register("api.exchange.coinbase.com/products/", requests.ConnectionError("down"))
    desk.poll(at("2026-06-01", 900))
    assert desk.state["last_error"] == "Coinbase candles not read (no connection) at 2026-06-01T00:15:00Z"


def test_a_late_candle_is_waited_for_never_made_up(settings: Settings, fake_http: FakeHttp,
                                                   http_client: HttpClient) -> None:
    candles = fixture_candles()
    late = dict(candles)
    late["SOL"] = {d: v for d, v in candles["SOL"].items() if d != "2026-06-02"}
    desk = desk_for(settings, fake_http, http_client, late)
    desk.poll(at("2026-06-01", 9 * 3600))
    desk.poll(at("2026-06-02"))
    out = desk.poll(at("2026-06-03"))  # SOL's candle of 2026-06-02 is not out yet: the day waits
    assert out["booked"] == 0 and desk.state["last_day"] == "2026-06-01" and out["error"] is None
    assert desk.next_wait(at("2026-06-03")) == T.RETRY_S
    fake_http.register("api.exchange.coinbase.com/products/", coinbase(candles))
    assert desk.poll(at("2026-06-03", 1800))["booked"] == 1
    assert desk.state["history"][-1]["closes"]["SOL"] == candles["SOL"]["2026-06-02"][0]


def test_only_completed_well_formed_candles_are_read() -> None:
    now = T.day_start("2026-06-03") + 3600
    rows = [[int(T.day_start("2026-06-03")), 1, 1, 1, 150.0, 10.0],  # still open
            [int(T.day_start("2026-06-02")), 1, 1, 1, 149.0, 10.0],
            [int(T.day_start("2026-06-01")) + 60, 1, 1, 1, 148.0, 10.0],  # not a UTC-day bar
            [int(T.day_start("2026-05-31")), 1, 1, 1, "x", 10.0], [int(T.day_start("2026-05-30")), 1, 1, 1, -5, 1],
            [int(T.day_start("2026-05-29")), 1, 1, 1, float("nan"), 1], ["bad"], None,
            [int(T.day_start("2026-05-28")), 1, 1, 1, 147.0, 12.0]]
    assert T.parse_candles(rows, now) == {"2026-06-02": (149.0, 10.0), "2026-05-28": (147.0, 12.0)}
    with pytest.raises(TypeError):
        T.parse_candles({"message": "x"}, now)


def test_every_booked_day_is_sealed_in_the_receipts(settings: Settings, fake_http: FakeHttp, http_client: HttpClient,
                                                    ledger: Ledger) -> None:
    desk = desk_for(settings, fake_http, http_client, ledger=ledger)
    desk.poll(at("2026-06-01", 9 * 3600))
    desk.poll(at("2026-06-04"))
    receipts = [r for r in ledger.receipts() if r.kind == "trenddesk_day"]
    assert [r.payload["day"] for r in receipts] == ["2026-06-01", "2026-06-02", "2026-06-03"]
    assert receipts[0].payload["equity_usd"] == pytest.approx(desk.state["history"][0]["equity_usd"], abs=1e-6)
    assert set(receipts[0].payload) == {"day", "closes", "in", "equity_usd", "hold_usd", "swaps"}


def test_the_desk_polls_once_a_day_after_0005_utc_and_retries_when_behind(settings: Settings, fake_http: FakeHttp,
                                                                         http_client: HttpClient) -> None:
    desk = desk_for(settings, fake_http, http_client)
    noon = at("2026-06-01", 12 * 3600)
    desk.poll(noon)
    assert desk.current(noon) and desk.next_wait(noon) == pytest.approx(at("2026-06-02", 300) - noon)
    assert not desk.current(at("2026-06-02", 360))  # the start day closed and is not booked yet
    desk.poll(at("2026-06-02", 360))
    assert desk.current(at("2026-06-02", 400)) and desk.next_wait(at("2026-06-02", 400)) == pytest.approx(DAY - 100)


def test_an_unreadable_state_file_is_kept_aside_never_overwritten(settings: Settings, http_client: HttpClient) -> None:
    path = T.state_path(settings)
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    desk = T.TrendDesk(settings, http=http_client)
    assert desk.state["started"] is None and not path.exists()
    (kept,) = path.parent.glob("state.unreadable-*.json")
    assert kept.read_text() == "{not json"


def test_a_crash_inside_a_poll_is_recorded_and_the_loop_goes_on(settings: Settings, http_client: HttpClient,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    desk = T.TrendDesk(settings, http=http_client)
    monkeypatch.setattr(T, "FIRST_POLL_DELAY_S", 0.0)

    def boom(now: float) -> dict[str, Any]:
        desk.stop()  # one round only
        raise RuntimeError("boom")

    monkeypatch.setattr(desk, "poll", boom)
    desk._loop()
    assert desk.state["last_error"] == "RuntimeError" and desk.state["counters"]["errors"] == 1
    assert T.load_state(T.state_path(settings))["last_error"] == "RuntimeError"


# --------------------------------------------------------------------------- paper only


def test_the_desk_is_paper_only_with_no_way_to_real_money(settings: Settings) -> None:
    source = inspect.getsource(T)
    for word in ("broker", "keystore", "solders", "wallet", "sign(", "ultra", "jupiter", "polymarket_us"):
        assert word not in source.lower().replace("no broker, no swap, no key and no wallet", ""), word
    assert not [f for f in settings.describe() if f["env"].startswith("TRENDDESK_") and f["secret"]]
    assert {f["env"] for f in settings.describe() if f["env"].startswith("TRENDDESK_")} == {
        "TRENDDESK_ENABLED", "TRENDDESK_SLEEVE_USD"}
    assert settings.trenddesk_enabled is True and settings.trenddesk_sleeve_usd == 100.0
    panel = T.panel_state(settings, NOW)
    assert panel["mode"] == "paper" and panel["label"] == "Paper money (pretend)" == T.PAPER_LABEL == PAPER_LABEL


# --------------------------------------------------------------------------- the page, the town, the team room


def test_money_and_town_show_the_trend_desk_apart_from_everything(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)  # the Solana bot lost $5.50 today (paper)
    plain = build_page_state(ledger, settings, NOW)  # no trend state yet
    save(settings, booked_state())
    state = build_page_state(ledger, settings, NOW)
    trend = state["money"]["trend"]
    assert trend == {"mode": "paper", "label": "Paper money (pretend)", "as_of": T.close_ts("2026-10-07"),
                     "sleeve_usd": 100.0, "equity_usd": pytest.approx(101.20), "today_usd": pytest.approx(0.30),
                     "since_start_usd": pytest.approx(1.20), "hold_since_start_usd": pytest.approx(0.40),
                     "in_market": {"BTC": True, "ETH": False, "SOL": True}, "started": "2026-10-01", "problem": None}
    assert state["town"]["trend"] == {
        "line": "Trend desk (paper, pretend): in BTC and SOL, out of ETH; since start +$1.20 vs holding +$0.40"}
    # nothing summed: the SOL wallet, the Polymarket desk and the town's own figures and line are untouched
    for key in ("today", "since_start", "usd", "polymarket"):
        assert state["money"][key] == plain["money"][key], key
    for key in ("line", "income_today_usd", "income_since_start_usd", "covered_today", "polymarket"):
        assert state["town"][key] == plain["town"][key], key
    body = json.dumps(state, allow_nan=False)
    numbers = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", body)]
    for summed in (-5.5 + 1.2, -5.5 + 0.3, 1.2 + 0.4, 0.3 + 0.3, 101.2 + 100.4, 1.2 - 5.5 + 0.4):  # SOL+trend, trend+hold
        assert not [n for n in numbers if abs(n - summed) < 1e-6], summed
    for text in ("$4.30", "$5.20", "$1.60", "$4.70"):
        assert text not in body, text
    assert not JARGON.search(state["town"]["trend"]["line"])


def test_before_its_first_close_the_desk_says_so(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    st = T.empty_state()
    st.update({"started": "2026-10-08", "started_at": NOW - 3600, "sleeve_usd": 100.0})
    save(settings, st)
    state = build_page_state(ledger, settings, NOW)
    trend = state["money"]["trend"]
    assert trend["as_of"] is None and trend["equity_usd"] == 100.0 and trend["since_start_usd"] == 0.0
    assert trend["in_market"] == {"BTC": False, "ETH": False, "SOL": False} and trend["problem"] is None
    assert state["town"]["trend"]["line"] == ("Trend desk (paper, pretend): first booking at the close of 2026-10-08 "
                                              "(UTC midnight); nothing booked yet")


def test_a_book_behind_says_why_on_the_card_and_in_the_town(ledger: Ledger, settings: Settings) -> None:
    seed(ledger)
    st = booked_state(last_day="2026-10-06")
    st["last_error"] = "Coinbase candles not read (HTTP 503) at 2026-10-08T15:45:00Z"
    save(settings, st)
    state = build_page_state(ledger, settings, NOW)
    assert state["money"]["trend"]["problem"] == (
        "Behind: the book stays at the close of 2026-10-06; Coinbase candles not read (HTTP 503) at "
        "2026-10-08T15:45:00Z. It retries every 15 minutes.")
    assert state["town"]["trend"]["line"].endswith("; behind: the newest daily close is not booked yet")
    fresh = booked_state(last_day="2026-10-07")
    fresh["last_error"] = st["last_error"]  # a start-up fetch failed, but every close is booked: nothing is behind
    save(settings, fresh)
    assert build_page_state(ledger, settings, NOW)["money"]["trend"]["problem"] is None


def test_nothing_is_shown_when_the_desk_is_off_or_its_file_is_junk(ledger: Ledger, make_settings: Callable[..., Settings],
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    off = make_settings(TRENDDESK_ENABLED=False)
    seed(ledger)
    save(off, booked_state())
    assert trend_desk(off, NOW) is None
    state = build_page_state(ledger, off, NOW)
    assert state["money"]["trend"] is None and state["town"]["trend"] is None
    on = make_settings()
    junk = booked_state()
    junk["history"][-1]["equity_usd"] = "lots"
    save(on, junk)
    assert trend_desk(on, NOW) is None  # never a made-up number
    T.state_path(on).write_text("{garbage")
    unread = trend_desk(on, NOW)
    assert unread is not None and unread["as_of"] is None  # an unreadable file reads as a desk not booked yet

    def boom(settings: Settings, now: float) -> dict[str, Any]:
        raise KeyError("history")

    monkeypatch.setattr(T, "panel_state", boom)
    state = build_page_state(ledger, on, NOW)
    assert state["money"]["trend"] is None and state["town"]["trend"] is None
    plain = town_ledger(on, {"today": {"usd": 1.0}, "since_start": {"usd": 1.0}, "trend": {"junk": 1}}, None, NOW,
                        NOW - DAY)
    assert plain["trend"] is None


def test_in_and_out_in_plain_words() -> None:
    assert T.in_out_text({"BTC": True, "ETH": False, "SOL": True}) == "in BTC and SOL, out of ETH"
    assert T.in_out_text({"BTC": True, "ETH": True, "SOL": True}) == "in BTC, ETH and SOL"
    assert T.in_out_text({"BTC": False, "ETH": False, "SOL": False}) == "out of BTC, ETH and SOL (all cash)"
    assert T.in_out_text({"ETH": True}) == "in ETH, out of BTC and SOL"


def test_the_strategy_member_carries_the_trend_desk(ledger: Ledger, make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    seed(ledger)
    before = {p["id"]: p for p in build_team_state(ledger, settings, NOW)["panels"]}["strategy"]
    save(settings, booked_state())
    strategy = {p["id"]: p for p in build_team_state(ledger, settings, NOW)["panels"]}["strategy"]
    stats = {s["label"]: s["value"] for s in strategy["stats"]}
    assert stats["Trend desk (paper)"] == "in BTC and SOL, out of ETH"
    assert (stats["Trend desk BTC (paper)"], stats["Trend desk ETH (paper)"], stats["Trend desk SOL (paper)"]) == (
        "in", "out", "in")
    assert stats["Trend desk since start $ (paper)"] == 1.2 and stats["Holding the three instead $ (paper)"] == 0.4
    assert "Trend desk: BTC closed above its 50-day average -> in (paper)" in [e["text"] for e in strategy["events"]]
    assert strategy["trend"]["in_market"] == {"BTC": True, "ETH": False, "SOL": True}
    assert strategy["trend"]["label"] == "Paper money (pretend)"
    # the desk's flips never make the Strategy member look busy, and its own sentence is unchanged
    assert (strategy["status"], strategy["last_activity"], strategy["doing"]) == (
        before["status"], before["last_activity"], before["doing"])
    page = build_page_state(ledger, settings, NOW)
    member = {m["id"]: m for m in page["team"]["members"]}["strategy"]
    assert "Trend desk: BTC closed above its 50-day average -> in (paper)" in [e["text"] for e in member["events"]]
    off = make_settings(TRENDDESK_ENABLED=False)
    strategy_off = {p["id"]: p for p in build_team_state(ledger, off, NOW)["panels"]}["strategy"]
    assert strategy_off["trend"] is None and not [s for s in strategy_off["stats"] if "Trend" in s["label"]]


def test_the_page_renders_the_trend_block_and_line_as_text_only(settings: Settings) -> None:
    html = render_page_html(settings)
    money = html[html.index('<section class="card" id="money">'):html.index('<section class="card" id="town">')]
    assert money.index('id="money-polymarket"') < money.index('id="money-trend"')  # under the Polymarket desk
    script = page_script(settings)
    assert "function renderTrend(tr)" in script and "renderTrend(m.trend);" in script
    assert "if (!tr || !tr.in_market) { put(box); return; }" in script  # older data without the block: no error
    assert 'el("span", "coin", tr.label)' in script and '"Paper money (pretend)"' not in script  # label from data
    assert '"paper only"' in script and "nothing here is " in script and "added together" in script
    assert "...[...(desks ? [desks.paper, desks.real] : []), t.trend].filter((d) => d && d.line)" in script
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert sink not in script, sink
    assert script.count(".replaceChildren(") == 1  # every fill goes through put()
    strings = re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"', script)
    assert not [s for s in strings if " " in s and JARGON.search(s)]
    (style,) = re.findall(r"<style>(.*?)</style>", html, flags=re.DOTALL)  # the CSP hashes follow the edit
    for text, directive in ((script, "script-src"), (style, "style-src")):
        digest = base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()
        assert f"{directive} 'sha256-{digest}';" in PAGE_CSP


# --------------------------------------------------------------------------- the engine wiring


def test_the_engine_starts_the_desk_in_its_own_thread_and_stops_it(make_settings: Callable[..., Settings],
                                                                   http_client: HttpClient, fake_http: FakeHttp,
                                                                   fake_clock: FakeClock) -> None:
    from nightcrawler.engine import build_app

    app = build_app(make_settings(), fake_clock, http=http_client)
    try:
        desk = app.trenddesk
        assert isinstance(desk, T.TrendDesk) and desk.ledger is app.ledger
        assert desk._thread is not None and desk._thread.daemon and desk._thread.is_alive()
        assert not fake_http.calls_to("coinbase")  # the first poll waits: a bot built and closed never fetches
    finally:
        app.close()
    assert desk._stop.is_set()
    desk._thread.join(timeout=5)
    assert not desk._thread.is_alive()


def test_the_engine_builds_no_desk_when_it_is_off(make_settings: Callable[..., Settings], http_client: HttpClient,
                                                  fake_clock: FakeClock) -> None:
    from nightcrawler.engine import build_app

    app = build_app(make_settings(TRENDDESK_ENABLED=False), fake_clock, http=http_client)
    try:
        assert app.trenddesk is None and not T.state_path(app.settings).exists()
    finally:
        app.close()


def test_a_desk_that_cannot_start_never_stops_the_bot(make_settings: Callable[..., Settings], http_client: HttpClient,
                                                      fake_clock: FakeClock, monkeypatch: pytest.MonkeyPatch) -> None:
    from nightcrawler.engine import build_app

    def broken(self: T.TrendDesk, *args: Any, **kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(T.TrendDesk, "__init__", broken)
    app = build_app(make_settings(), fake_clock, http=http_client)
    try:
        assert app.trenddesk is None and app.engine is not None
        app.engine.tick(fake_clock.now())  # the trading loop runs
    finally:
        app.close()
    assert not [t for t in threading.enumerate() if t.name == "trenddesk" and not t.daemon]
