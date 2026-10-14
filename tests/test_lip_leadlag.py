"""The Pyth lead-lag analyzer (research/kalshi_rewards/leadlag.py) against PREREG.md: events, interval-censored
warnings, exclusions, the statistic, the decision rule, the split by FX days and the one-look TEST freeze."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from nightcrawler.lip_feed import SERIES, write_segment

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("kalshi_rewards_leadlag", ROOT / "research/kalshi_rewards/leadlag.py")
assert SPEC and SPEC.loader
LL = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LL
SPEC.loader.exec_module(LL)

T0 = 1_791_918_900.0  # 2026-10-13 19:15:00 UTC, a Tuesday (15:15 EDT)
EUR = "KXEURUSD15M-26OCT131530-30"
SYMBOL = "FX.EUR/USD"
WINDOW = LL.MarketWindow(EUR, "KXEURUSD15M", T0, T0 + 900)


def polls(moves: dict[float, float] | None = None, start: float = T0 + 0.3, end: float = T0 + 900,
          base: float = 50.0, skip: tuple[float, float] | None = None) -> Any:
    """Polls received every second at .3 (requested 0.1 s earlier); ``moves``: from this receive time on, this mid."""
    out = LL.Polls()
    at, mid = start, base
    while at < end:
        for when_, value in (moves or {}).items():
            if at >= when_:
                mid = value
        if skip is None or not skip[0] <= at < skip[1]:
            out.add(at - 0.1, at, mid)
        at = round(at + 1.0, 6)
    return out


def event(at: float = T0 + 100, direction: int = 1) -> Any:
    return LL.Event("KXEURUSD15M", SYMBOL, at, direction, 1.2 * direction, 1.16)


TICKS = [(T0 + 99.0, 1.16), (T0 + 100.0, 1.16014)]


# ---------------------------------------------------------------------- the definitions
def test_new_york_time_and_hours() -> None:
    assert LL.new_york(T0) == datetime(2026, 10, 13, 15, 15, tzinfo=UTC).replace(tzinfo=None)
    assert LL.new_york(datetime(2026, 12, 1, 12, tzinfo=UTC).timestamp()) == datetime(2026, 12, 1, 7,
                                                                                         tzinfo=UTC).replace(tzinfo=None)
    assert LL.maintenance(datetime(2026, 10, 15, 7, 30, tzinfo=UTC).timestamp())  # Thursday 3:30 am EDT
    assert not LL.fx_hours(datetime(2026, 10, 17, 12, tzinfo=UTC).timestamp())  # Saturday
    assert not LL.fx_hours(datetime(2026, 10, 16, 21, 30, tzinfo=UTC).timestamp())  # Friday 5:30 pm EDT
    assert LL.fx_hours(datetime(2026, 10, 18, 21, 30, tzinfo=UTC).timestamp())  # Sunday 5:30 pm EDT


def test_pyth_events_use_a_one_second_lookback_and_a_refractory_period() -> None:
    ticks = [(T0 + i * 0.25, 1.16) for i in range(8)] + [(T0 + 2.0, 1.16012), (T0 + 2.5, 1.16030),
                                                            (T0 + 8.0, 1.16030), (T0 + 8.5, 1.16010)]
    events = LL.pyth_events(ticks, "KXEURUSD15M", SYMBOL, 1.0)
    assert [(e.at, e.direction) for e in events] == [(T0 + 2.0, 1), (T0 + 8.5, -1)]  # 2.5 falls in the 5 s quiet
    assert round(events[0].move_bps, 3) == round(1e4 * __import__("math").log(1.16012 / 1.16), 3)


@pytest.mark.parametrize(("moved_at", "warn", "w_lo", "w_hi"), [
    (T0 + 101.3, False, 0.2, 1.3),  # the poll answered 0.3 s after the update was still stale; the next showed it
    (T0 + 102.3, True, 1.2, 2.3),  # a poll begun 1.2 s after the update still showed the stale book
])
def test_warning_is_interval_censored_and_conservative(moved_at: float, warn: bool, w_lo: float,
                                                       w_hi: float) -> None:
    row = LL.measure(event(), WINDOW, polls({moved_at: 50.5}), TICKS)
    assert row["excluded"] is None and row["response"] == "same"
    assert (row["warn05"], row["w_lo"], row["w_hi"]) == (warn, pytest.approx(w_lo), pytest.approx(w_hi))
    assert row["kalshi_first"] is False and row["mid_move"] == 0.5 and row["m0"] == 50.0


def test_opposite_none_and_kalshi_first() -> None:
    assert LL.measure(event(), WINDOW, polls({T0 + 101.3: 49.5}), TICKS)["response"] == "opposite"
    assert LL.measure(event(), WINDOW, polls(), TICKS)["response"] == "none"
    first = LL.measure(event(), WINDOW, polls({T0 + 99.3: 50.5}), TICKS)
    assert first["response"] == "same" and first["kalshi_first"] is True and first["w_hi"] < 0


@pytest.mark.parametrize(("case", "reason"), [("edge", "window_edge"), ("late", "window_edge"),
                                              ("baseline", "no_baseline"), ("extreme", "baseline_extreme"),
                                              ("gap", "coverage"), ("one_sided", "one_sided_book"),
                                              ("window", "no_window"), ("maintenance", "maintenance")])
def test_exclusions_are_counted_with_their_reason(case: str, reason: str) -> None:
    at, book, window = T0 + 100, polls({T0 + 101.3: 50.5}), WINDOW
    if case == "edge":
        at = T0 + 10
    elif case == "late":
        at = T0 + 880
    elif case == "baseline":
        book = LL.Polls()
    elif case == "extreme":
        book = polls(base=97.0)
    elif case == "gap":
        book = polls(skip=(T0 + 102, T0 + 106))
    elif case == "one_sided":
        book = polls()
        book.mid[book.received.index(T0 + 100.3)] = None
    elif case == "window":
        window = None
    elif case == "maintenance":
        at = datetime(2026, 10, 15, 7, 30, tzinfo=UTC).timestamp()
        window = LL.MarketWindow(EUR, "KXEURUSD15M", at - 100, at + 800)
        book = polls(start=at - 99.7, end=at + 800)
    assert LL.measure(event(at), window, book, TICKS)["excluded"] == reason


# ---------------------------------------------------------------------- the statistic and the rule
def rows_for(warns: list[bool], windows: int = 4, opposite: int = 0) -> list[dict[str, Any]]:
    out = [{"window": f"w{i % windows}", "excluded": None, "response": "same", "warn05": warn, "w_lo": 0.6 if warn
            else 0.1, "w_hi": 1.0, "kalshi_first": False, "move_bps": 1.0, "pyth_move_at_response_bps": 1.0}
           for i, warn in enumerate(warns)]
    out += [{"window": "w0", "excluded": None, "response": "opposite", "move_bps": 1.0}] * opposite
    return out + [{"window": "w0", "excluded": "coverage", "move_bps": 1.0}]


def test_summary_counts_shares_and_a_reproducible_bootstrap() -> None:
    rows = rows_for([True, False, True, True], opposite=1)
    first, second = LL.summarize(rows), LL.summarize(rows)
    assert first == second  # seeded
    assert (first["events"], first["kept"], first["same"], first["opposite"], first["none"]) == (6, 5, 4, 1, 0)
    assert first["excluded"] == {"coverage": 1} and first["S"] == 0.75 and first["P_same"] == 0.8
    low, high = first["S_range95"]
    assert 0 <= low <= 0.75 <= high <= 1
    assert first["w_lo"]["p50"] == 0.6 and sum(item["n"] for item in first["w_lo_histogram"]) == 4


def primary(same: int = 400, windows: int = 150, p_low: float = 0.7, s: tuple[float, float] = (0.6, 0.7)) -> dict:
    return {"same": same, "windows_with_same": windows, "P_same_range95": [p_low, 0.9], "S_range95": list(s)}


FAST = {"FX.EUR/USD": {"median_ms": 50.0}, "FX.GBP/USD": {"median_ms": 60.0}}
SLOW = {"FX.EUR/USD": {"median_ms": 1000.0}}


@pytest.mark.parametrize(("data", "intervals", "source", "verdict"), [
    (primary(), FAST, "kalshi_live_data", "DESCRIPTIVE"),
    (primary(same=299), FAST, "pyth_hermes", "INSUFFICIENT"),
    (primary(windows=99), FAST, "pyth_hermes", "INSUFFICIENT"),
    (primary(p_low=0.54), FAST, "pyth_hermes", "INCONCLUSIVE"),
    (primary(s=(0.50, 0.6)), SLOW, "pyth_hermes", "CONTINUE"),
    (primary(s=(0.05, 0.24)), FAST, "pyth_hermes", "STOP"),
    (primary(s=(0.05, 0.24)), SLOW, "pyth_hermes", "STOP_THIS_SOURCE_ONLY"),
    (primary(s=(0.2, 0.55)), FAST, "pyth_hermes", "MARGINAL"),
])
def test_the_pre_registered_decision(data: dict, intervals: dict, source: str, verdict: str) -> None:
    assert LL.decide(data, intervals, source)["verdict"] == verdict


def test_the_numbers_of_the_rule_are_prereg_s() -> None:
    assert (LL.PRIMARY_K, LL.LOOKBACK_S, LL.REFRACTORY_S, LL.HORIZON_S, LL.WARN_S) == (1.0, 1.0, 5.0, 10.0, 0.5)
    assert (LL.MIN_SAME, LL.MIN_WINDOWS, LL.P_SAME_FLOOR, LL.CONTINUE_LOW, LL.STOP_HIGH) == (300, 100, 0.55, 0.5,
                                                                                             0.25)
    assert (LL.BOOTSTRAP_B, LL.SEED, LL.FAST_SOURCE_MS) == (2000, 20261014, 250.0)
    assert LL.SPLIT == {"TRAIN": (0, 2), "VAL": (2, 4), "TEST": (4, 8)}
    assert LL.prereg_hash_ok(), "PREREG.md no longer matches PREREG.sha256"


# ---------------------------------------------------------------------- the split and the freeze
def covered_day(data: Any, day: str, hours: int) -> None:
    start = datetime.fromisoformat(day).replace(tzinfo=UTC).timestamp()
    for series in LL.FX_SERIES:
        symbol = SERIES[series].pyth_symbol
        window = LL.MarketWindow(f"{series}-{day}", series, start, start + 86_400)
        data.windows.setdefault(series, []).append(window)
        book = data.polls.setdefault(window.ticker, LL.Polls())
        ticks = data.ticks.setdefault("pyth_hermes", {}).setdefault(symbol, [])
        for minute in range(hours * 60):
            book.add(start + minute * 60 + 1, start + minute * 60 + 1, 50.0)
            ticks.append((start + minute * 60 + 2, 1.0))


def test_fx_days_and_the_split() -> None:
    data = LL.Data()
    days = ["2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19", "2026-10-20",
            "2026-10-21", "2026-10-22"]
    for day in days:
        covered_day(data, day, 16)
    covered_day(data, "2026-10-23", 6)  # too short
    listing = LL.fx_days(data, "pyth_hermes")
    assert [row["day"] for row in listing if row["fx_day"]] == days
    split = LL.split(listing)
    assert split == {"TRAIN": days[:2], "VAL": days[2:4], "TEST": days[4:8]}
    assert LL.split(listing, 5)["TEST"] == days[4:9]
    assert LL.fx_days(data, "pyth_pro") == []


def test_test_is_refused_without_a_matching_freeze_and_after_one_look(tmp_path: Path) -> None:
    freeze, result = tmp_path / "FREEZE.json", tmp_path / "TEST_RESULT.json"
    days = ["2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21"]
    assert any("missing" in problem for problem in LL.check_freeze("pyth_hermes", days, freeze, result))
    good = {"prereg_sha256": hashlib.sha256(LL.PREREG.read_bytes()).hexdigest(), "source": "pyth_hermes",
            "test_days": days,
            "leadlag_sha256": hashlib.sha256((ROOT / "research/kalshi_rewards/leadlag.py").read_bytes()).hexdigest()}
    freeze.write_text(json.dumps(good), encoding="utf-8")
    assert LL.check_freeze("pyth_hermes", days, freeze, result) == []
    assert LL.check_freeze("kalshi_pyth_value", days, freeze, result)
    assert LL.check_freeze("pyth_hermes", days[:3] + ["2026-10-22"], freeze, result)
    freeze.write_text(json.dumps({**good, "leadlag_sha256": "0" * 64}), encoding="utf-8")
    assert any("changed" in problem for problem in LL.check_freeze("pyth_hermes", days, freeze, result))
    freeze.write_text(json.dumps(good), encoding="utf-8")
    result.write_text("{}", encoding="utf-8")
    assert any("already" in problem for problem in LL.check_freeze("pyth_hermes", days, freeze, result))


# ---------------------------------------------------------------------- end to end on recorder files
def _iso(at: float) -> str:
    return datetime.fromtimestamp(at, UTC).isoformat().replace("+00:00", "Z")


def recorder(root: Path) -> None:
    """One EUR/USD window: the program, books polled every second (the mid steps up 2.3 s after each Pyth up-move),
    and Pyth updates every 200 ms with three 1.2 bp moves."""
    seq = 0

    def nxt() -> int:
        nonlocal seq
        seq += 1
        return seq

    lip = [{"seq": nxt(), "lane": "lip", "kind": "programs", "at": T0 - 600, "full": True, "rows": [{
        "incentive_type": "liquidity", "market_ticker": EUR, "start_date": _iso(T0), "end_date": _iso(T0 + 900),
        "period_reward": 500000, "target_size_fp": "300.00", "discount_factor_bps": 5000, "id": "p"}]}]
    books, pyth = [], []
    jumps = (T0 + 100.0, T0 + 300.0, T0 + 500.0)
    price, rows = 1.16, []
    at = T0 + 0.2
    while at < T0 + 900:
        for jump in jumps:
            if jump <= at < jump + 0.2:
                price *= 1.00012
        rows.append([SERIES["KXEURUSD15M"].hermes_id, str(round(price * 1e5)), "1", -5, int(at), int(at) - 1,
                     round(at, 3)])
        if len(rows) == 5:
            pyth.append({"seq": nxt(), "lane": "pyth", "kind": "updates", "at": round(at, 3), "stream": "fx",
                         "channel": "fixed_rate@200ms",
                         "columns": ["id", "price", "conf", "expo", "publish_time", "prev_publish_time",
                                     "received_at"], "rows": rows})
            rows = []
        at += 0.2
    mid_yes = 40
    for second in range(900):
        received = T0 + second + 0.3
        stepped = sum(1 for jump in jumps if received >= jump + 2.3)
        target = 40 + stepped
        changed = target != mid_yes or second == 0
        if changed:
            mid_yes = target
            books.append({"seq": nxt(), "lane": "books_lip", "kind": "book", "at": received, "ticker": EUR,
                          "requested_at": received - 0.1, "received_at": received,
                          "orderbook_fp": {"yes_dollars": [[f"0.{mid_yes:02d}", "100"]],
                                           "no_dollars": [[f"0.{100 - mid_yes - 2:02d}", "100"]]}})
        lip.append({"seq": nxt(), "lane": "lip", "kind": "book_call", "at": received, "requested_at": received - 0.1,
                    "received_at": received, "status": 200, "tickers": [EUR], "changed": [EUR] if changed else [],
                    "unchanged": [] if changed else [EUR], "missing": []})
    for lane, rows_ in (("lip", lip), ("books_lip", books), ("pyth", pyth)):
        rows_.sort(key=lambda row: row["seq"])
        write_segment(root / "segments" / lane / "2026-10-13" / f"{lane}-20261013T180000Z-{rows_[0]['seq']:012d}"
                      ".jsonl.gz", rows_)


def test_end_to_end_on_recorder_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    recorder(tmp_path)
    out = tmp_path / "report.json"
    code = LL.main(["run", "--recorder-dir", str(tmp_path), "--source", "pyth_hermes", "--start",
                    "2026-10-13T19:00:00", "--end", "2026-10-13T20:00:00", "--out", str(out)])
    assert code == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    cell = report["cells"]["FX|k1"]
    assert (cell["events"], cell["same"], cell["opposite"]) == (3, 3, 0)
    # the poll begun about 1.2 s after each move still showed the stale book: all three warned >= 0.5 s
    assert cell["S"] == 1.0 and cell["w_lo"]["p50"] == pytest.approx(1.2, abs=0.25)
    assert report["rule"]["verdict"] == "INSUFFICIENT" and "reading only" in report["rule"]["note"]
    assert report["intervals"]["FX.EUR/USD"]["median_ms"] == pytest.approx(200.0, abs=1)
    assert "FX|k1 source pyth_hermes" in capsys.readouterr().out
    assert LL.main(["days", "--recorder-dir", str(tmp_path), "--source", "pyth_hermes"]) == 0
