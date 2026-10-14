"""The recorder-file reader of the practice LIP desk and the lead-lag analyzer (nightcrawler.lip_feed): every record
shape it accepts, and the incremental tail of segments the recorder is still writing."""

from __future__ import annotations

import gzip
import hashlib
import json
import zlib
from pathlib import Path
from typing import Any

import pytest

from nightcrawler import lip_feed as F

T0 = 1_791_918_900.0  # 2026-10-13 19:15:00 UTC
EUR = "KXEURUSD15M-26OCT131530-30"
EUR_ID = F.SERIES["KXEURUSD15M"].hermes_id


def book(ticker: str = EUR, at: float = T0, yes: Any = None, no: Any = None, **extra: Any) -> dict[str, Any]:
    return {"kind": "book", "lane": "books_lip", "at": at, "seq": int(at), "ticker": ticker, "requested_at": at - 0.1,
            "received_at": at, "orderbook_fp": {"yes_dollars": yes if yes is not None else [["0.4000", "100.00"]],
                                                "no_dollars": no if no is not None else [["0.5500", "200.00"]]},
            **extra}


def test_series_table_matches_the_research() -> None:
    assert F.FX_SERIES == ("KXEURUSD15M", "KXGBPUSD15M", "KXUSDJPY15M", "KXAUDUSD15M", "KXUSDCAD15M")
    assert F.SERIES["KXUSDJPY15M"].round_digits == 3 and F.SERIES["KXCOPPER15M"].shard == 2
    assert F.SERIES["KXCRYPTOLEAD15M"].pyth_symbol is None
    assert F.HERMES_SYMBOL[EUR_ID or ""] == "FX.EUR/USD" and F.PRO_SYMBOL[3265] == "Commodities.Index.NATGAS/USD"
    assert F.series_of(EUR) == "KXEURUSD15M" and F.series_of("KXBTC15M-26OCT131530-30") is None


def test_numbers_times_and_cents() -> None:
    assert F.number("0.4000") == 0.4 and F.number(True) is None and F.number("nan") is None
    assert F.when("2026-10-13T19:15:00Z") == T0 and F.when(T0 * 1000) == T0 and F.when(T0) == T0
    assert F.cents("0.4000") == 40 and F.cents("0.405") is None and F.cents("1.00") is None
    assert F.levels_from([["0.39", "5"], ["0.40", "10"], ["0.40", "1"], ["0.405", "9"], ["0.30", "0"]]) == (
        (40, 11.0), (39, 5.0))


def test_book_and_call_records() -> None:
    snap = F.book_from_record(book())
    assert snap is not None and snap.best_yes == 40 and snap.best_no == 55 and snap.mid == 42.5
    assert snap.requested_at == T0 - 0.1 and snap.received_at == T0
    assert F.book_from_record({"kind": "trades"}) is None
    one_sided = F.book_from_record(book(no=[]))
    assert one_sided is not None and one_sided.mid is None
    call = F.call_from_record({"kind": "book_call", "requested_at": T0, "received_at": T0 + 0.2, "status": 200,
                               "changed": [EUR], "unchanged": ["X"], "missing": [], "tickers": [EUR, "X"]})
    assert call is not None and call.changed == (EUR,) and call.unchanged == ("X",) and call.ok
    assert not F.call_from_record({"kind": "book_call", "received_at": T0, "status": 503, "error": "x"}).ok  # type: ignore[union-attr]


def test_prints_side_mapping() -> None:
    rows = [{"ticker": EUR, "trade_id": "a", "created_time": "2026-10-13T19:15:01.5Z", "count_fp": "2.00",
             "taker_outcome_side": "no", "yes_price_dollars": "0.4000", "no_price_dollars": "0.6000"},
            {"ticker": EUR, "trade_id": "b", "created_time": "2026-10-13T19:15:02Z", "count_fp": "3.00",
             "taker_side": "yes", "yes_price_dollars": "0.4600", "no_price_dollars": "0.5400",
             "is_block_trade": True},
            {"ticker": EUR, "trade_id": "c", "created_time": "bad", "count_fp": "1", "taker_outcome_side": "no",
             "yes_price_dollars": "0.40"}]
    prints = F.prints_from_record({"kind": "trades", "rows": rows})
    assert [(p.trade_id, p.side, p.price, p.size, p.block) for p in prints] == [
        ("a", F.YES, 40, 2.0, False), ("b", F.NO, 54, 3.0, True)]
    assert prints[0].at == T0 + 1.5


def test_program_records_in_every_shape() -> None:
    row = {"incentive_type": "liquidity", "market_ticker": EUR, "start_date": "2026-10-13T19:15:00Z",
           "end_date": "2026-10-13T19:30:00Z", "period_reward": 500000, "target_size_fp": "300.00",
           "discount_factor_bps": 5000, "id": "p1"}
    volume = {**row, "incentive_type": "volume", "id": "p2"}
    raw = F.programs_from_record({"kind": "incentives", "body": {"incentive_programs": [row, volume]}})
    assert [(p.ticker, p.start, p.end, p.reward, p.target, p.discount_factor) for p in raw] == [
        (EUR, T0, T0 + 900, 50.0, 300.0, 0.5)]
    full = F.programs_from_record({"kind": "programs", "lane": "lip", "full": True, "rows": [row]})
    diff = F.programs_from_record({"kind": "programs", "lane": "lip", "full": False, "added": [row], "changed": [],
                                   "removed": ["old"]})
    assert full == raw and diff == raw
    assert F.programs_from_record({"kind": "book"}) == []


def test_market_rows_merge_full_dyn_and_raw() -> None:
    facts = F.MarketFacts(EUR)
    for record in ({"kind": "sweep", "rows": [{"ticker": EUR, "full": {"open_time": "2026-10-13T19:15:00Z",
                                                                       "close_time": "2026-10-13T19:30:00Z",
                                                                       "floor_strike": 1.16, "status": "active"}}]},
                   {"kind": "sweep", "rows": [{"ticker": EUR, "dyn": {"status": "closed"}}]},
                   {"kind": "settlement", "lane": "lip", "rows": [{"ticker": EUR, "result": "yes",
                                                                   "expiration_value": "1.16021",
                                                                   "settlement_ts": "2026-10-13T19:30:14Z"}]}):
        for ticker, row in F.market_rows_from_record(record):
            assert ticker == EUR
            facts.merge(row)
    assert (facts.open_ts, facts.close_ts, facts.floor_strike, facts.result, facts.status) == (
        T0, T0 + 900, 1.16, "yes", "closed")
    assert facts.expiration_value == 1.16021 and facts.settlement_ts == T0 + 914


def test_pyth_shapes() -> None:
    columnar = {"kind": "updates", "lane": "pyth", "at": T0 + 5, "stream": "fx", "channel": "real_time",
                "columns": ["id", "price", "conf", "expo", "publish_time", "prev_publish_time", "received_at"],
                "rows": [[EUR_ID, "116021", "3", -5, int(T0), int(T0) - 1, T0 + 0.25],
                         ["unknown", "1", "1", 0, int(T0), int(T0), T0 + 0.3],
                         [EUR_ID, "116022"]]}
    ticks = F.parse_pyth(columnar)
    assert [(t.symbol, t.at, round(t.price, 5), t.source) for t in ticks] == [
        ("FX.EUR/USD", T0 + 0.25, 1.16021, "pyth_hermes")]
    hermes = {"kind": "sse", "received_at": T0 + 1, "parsed": [
        {"id": EUR_ID, "price": {"price": "116030", "expo": -5, "publish_time": int(T0)}}]}
    kalshi = {"kind": "pyth_value", "received_at": T0 + 2, "msg": {"underlying_ticker": "Metal.XPT/USD",
                                                                    "value_usd": "1612.50000000",
                                                                    "source_ts_ms": int(T0 * 1000)}}
    pro = {"kind": "lazer", "received_at": T0 + 3, "timestampUs": int(T0 * 1e6),
           "priceFeeds": [{"priceFeedId": 327, "price": "116040", "exponent": -5}]}
    flat = {"kind": "price", "at": T0 + 4, "symbol": "FX.GBP/USD", "price": 1.3254}
    got = [(t.symbol, t.at, round(t.price, 5), t.source) for record in (hermes, kalshi, pro, flat)
           for t in F.parse_pyth(record)]
    assert got == [("FX.EUR/USD", T0 + 1, 1.1603, "pyth_hermes"), ("Metal.XPT/USD", T0 + 2, 1612.5, "kalshi_pyth_value"),
                   ("FX.EUR/USD", T0 + 3, 1.1604, "pyth_pro"), ("FX.GBP/USD", T0 + 4, 1.3254, "pyth")]
    assert F.parse_pyth({"kind": "book", "at": T0, "ticker": EUR}) == []


def test_free_series_in_both_shapes() -> None:
    lane = {"kind": "series", "lane": "lip", "series": "KXEURUSD15M", "event_ticker": "KXEURUSD15M-26OCT131530",
            "new": [[int(T0 * 1000), 1.16021], [int(T0 * 1000) + 1000, 1.16022]], "revised": []}
    raw = {"kind": "live", "body": {"live_data": {"details": {"event_ticker": "KXGBPUSD15M-26OCT131530",
                                                              "timeseries": [{"t": int(T0 * 1000), "v": 1.32544}]}}}}
    assert [(p.series, p.label, p.value) for p in F.live_points_from_record(lane)] == [
        ("KXEURUSD15M", T0, 1.16021), ("KXEURUSD15M", T0 + 1, 1.16022)]
    assert [(p.series, p.value) for p in F.live_points_from_record(raw)] == [("KXGBPUSD15M", 1.32544)]


def _segment(root: Path, lane: str, start: float, first_seq: int, rows: list[dict[str, Any]], *,
             sealed: bool = True) -> Path:
    from datetime import UTC, datetime

    stamp = datetime.fromtimestamp(start, UTC)
    name = f"{lane}-{stamp.strftime('%Y%m%dT%H%M%SZ')}-{first_seq:012d}.jsonl.gz" + ("" if sealed else ".part")
    path = root / "segments" / lane / stamp.strftime("%Y-%m-%d") / name
    F.write_segment(path, rows, sealed=sealed)
    return path


def test_read_records_orders_checks_hashes_and_reads_open_segments(tmp_path: Path) -> None:
    sealed = _segment(tmp_path, "books_lip", T0, 1, [book(at=T0 + 1, seq=1), book(at=T0 + 3, seq=3)])
    _segment(tmp_path, "lip", T0, 2, [{"kind": "book_call", "at": T0 + 2, "seq": 2, "received_at": T0 + 2}],
             sealed=False)
    rows = F.read_records(tmp_path, ("books_lip", "lip"))
    assert [row["seq"] for row in rows] == [1, 2, 3]
    assert [row["seq"] for row in F.read_records(tmp_path, ("books_lip", "lip"), start=T0 + 1.5)] == [2, 3]
    assert F.read_records(tmp_path, ("books_lip",), parts=False)[0]["seq"] == 1
    relative = str(sealed.relative_to(tmp_path))
    index = {"kind": "segment", "path": relative, "sha256": hashlib.sha256(sealed.read_bytes()).hexdigest()}
    (tmp_path / "index.jsonl").write_text(json.dumps(index) + "\n", encoding="utf-8")
    assert len(F.read_records(tmp_path, ("books_lip",))) == 2
    (tmp_path / "index.jsonl").write_text(json.dumps({**index, "sha256": "0" * 64}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        F.read_records(tmp_path, ("books_lip",))
    assert len(F.read_records(tmp_path, ("books_lip",), verify=False)) == 2


def test_a_torn_open_segment_keeps_its_complete_lines(tmp_path: Path) -> None:
    path = _segment(tmp_path, "books_lip", T0, 1, [book(at=T0 + 1, seq=1), book(at=T0 + 2, seq=2)], sealed=False)
    path.write_bytes(path.read_bytes() + b"\x00garbage")
    assert [row["seq"] for row in F.read_records(tmp_path, ("books_lip",))] == [1, 2]


class Writer:
    """An open segment the way the recorder writes it: one gzip stream, Z_SYNC_FLUSH after each batch, sealed by
    finishing the stream and renaming it."""

    def __init__(self, path: Path) -> None:
        self.path, self.encoder = path, zlib.compressobj(6, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")

    def add(self, rows: list[dict[str, Any]]) -> None:
        data = b"".join((json.dumps(row) + "\n").encode() for row in rows)
        with self.path.open("ab") as stream:
            stream.write(self.encoder.compress(data) + self.encoder.flush(zlib.Z_SYNC_FLUSH))

    def seal(self) -> Path:
        with self.path.open("ab") as stream:
            stream.write(self.encoder.flush())
        final = self.path.with_name(self.path.name.removesuffix(".part"))
        self.path.rename(final)
        return final


def test_tail_reads_new_lines_once_across_the_seal(tmp_path: Path) -> None:
    tail = F.RecorderTail(tmp_path, ("books_lip",), start=T0)
    assert tail.poll() == []
    rows = [book(at=T0 + i, seq=i) for i in range(1, 4)]
    writer = Writer(tmp_path / "segments" / "books_lip" / "2026-10-13"
                    / "books_lip-20261013T191500Z-000000000001.jsonl.gz.part")
    writer.add(rows[:2])
    assert [row["seq"] for row in tail.poll()] == [1, 2]
    assert tail.poll() == []
    writer.add(rows[2:])
    assert [row["seq"] for row in tail.poll()] == [3]
    sealed = writer.seal()  # sealed under its final name: read again from its start, nothing returned twice
    assert tail.poll() == []
    _segment(tmp_path, "books_lip", T0 + 3600, 4, [book(at=T0 + 3601, seq=4)])
    assert [row["seq"] for row in tail.poll()] == [4]
    with gzip.open(sealed, "rt", encoding="utf-8") as stream:
        assert len(stream.read().splitlines()) == 3


def test_tail_starts_at_the_segment_holding_its_start(tmp_path: Path) -> None:
    _segment(tmp_path, "books_lip", T0 - 7200, 1, [book(at=T0 - 7000, seq=1)])
    _segment(tmp_path, "books_lip", T0 - 3600, 2, [book(at=T0 - 3000, seq=2), book(at=T0 + 10, seq=3)])
    tail = F.RecorderTail(tmp_path, ("books_lip",), start=T0)
    assert [row["seq"] for row in tail.poll()] == [2, 3]
