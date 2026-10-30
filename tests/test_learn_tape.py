"""The forward tape: torn-line repair, crash-safe sealing, hourly segment roots, first value wins,
coverage holes and the visibility rules of TapeView (docs/LEARNING.md §3.1-3.5)."""

from __future__ import annotations

import gzip
import hashlib
import json

import pytest

from nightcrawler.learn import tape as tape_mod
from nightcrawler.learn.tape import (
    MANIFEST,
    TapeReader,
    TapeSealed,
    TapeView,
    TapeWriter,
    candle_fetch_row,
    segment_root,
    tape_day,
    verify_segments,
)
from nightcrawler.models import Candle

DAY = "2026-10-08"
T = 1_791_475_200  # 2026-10-08T16:00:00Z
MINT = "Mint1111111111111111111111111111111111pump"


def rows(n: int, stream: str = "universe") -> list[dict]:
    return [{"v": 1, "ts": T + i, "mint": f"M{i}", "src": {"test": [T + i, 200]}, "i": i, "stream": stream}
            for i in range(n)]


@pytest.fixture
def root(tmp_path):
    return tmp_path / "learn" / "tape"


def test_tape_day_is_the_utc_day() -> None:
    assert tape_day(T) == DAY and tape_day(T + 8 * 3600 - 1) == DAY and tape_day(T + 8 * 3600) == "2026-10-09"


# --------------------------------------------------------------------------- torn lines


def test_a_torn_last_line_is_cut_on_open_and_counted(root) -> None:
    with TapeWriter(root) as w:
        for r in rows(3):
            w.append("universe", DAY, r)
    path = root / DAY / "universe.jsonl"
    with path.open("ab") as fh:
        fh.write(b'{"v": 1, "ts": 17914')  # the process died mid-line
    assert TapeReader(root).rows(DAY, "universe") == rows(3)  # readers skip it...
    reader = TapeReader(root)
    list(reader.rows(DAY, "universe"))
    assert reader.skipped == 1  # ...and count it
    with TapeWriter(root) as w:  # the writer cuts it when it opens the file again
        w.append("universe", DAY, rows(4)[3])
        assert w.torn_repaired == 1
    assert TapeReader(root).rows(DAY, "universe") == rows(4)
    assert path.read_bytes().endswith(b"\n") and path.read_bytes().count(b"\n") == 4


def test_fsync_every_100_lines_or_5_seconds(root, monkeypatch) -> None:
    synced: list[int] = []
    monkeypatch.setattr(tape_mod.os, "fsync", lambda fd: synced.append(fd))
    clock = {"t": 0.0}
    with TapeWriter(root, monotonic=lambda: clock["t"]) as w:
        for r in rows(99):
            w.append("universe", DAY, r)
        assert synced == []
        w.append("universe", DAY, rows(100)[99])
        assert len(synced) == 1
        clock["t"] = 5.0
        w.append("universe", DAY, rows(101)[100])
        assert len(synced) == 2


# --------------------------------------------------------------------------- hourly segment roots


def test_segment_roots_match_their_bytes_and_chain_by_offset(root) -> None:
    with TapeWriter(root) as w:
        for r in rows(5):
            w.append("universe", DAY, r)
        w.append("candles", DAY, {"v": 1, "ts": T, "mint": MINT, "rows": []})
        first = w.segments({})
        assert [s["file"] for s in first] == [f"{DAY}/candles.jsonl", f"{DAY}/universe.jsonl"]
        assert verify_segments(root, first)
        for s in first:
            data = (root / s["file"]).read_bytes()[s["start"]:s["end"]]
            assert s["start"] == 0 and hashlib.sha256(data).hexdigest() == s["sha256"] and data.endswith(b"\n")
        offsets = {s["file"]: s["end"] for s in first}
        assert w.segments(offsets) == []  # nothing new since the last root
        for r in rows(7)[5:]:
            w.append("universe", DAY, r)
        second = w.segments(offsets)
        universe = f"{DAY}/universe.jsonl"
        assert [(s["file"], s["start"]) for s in second] == [(universe, offsets[universe])]
        assert verify_segments(root, second)
    assert segment_root(first) == segment_root(json.loads(json.dumps(first)))  # canonical
    assert segment_root(first) != segment_root(second)
    path = root / DAY / "universe.jsonl"
    data = bytearray(path.read_bytes())
    data[3] ^= 1  # one changed byte breaks the receipted root
    path.write_bytes(bytes(data))
    assert not verify_segments(root, first)


# --------------------------------------------------------------------------- sealing


def _write_day(root) -> dict[str, list[dict]]:
    content = {"universe": rows(4), "candles": rows(6, "candles")}
    with TapeWriter(root) as w:
        for stream, items in content.items():
            for r in items:
                w.append(stream, DAY, r)
    return content


def test_sealing_compresses_writes_a_manifest_and_refuses_new_rows(root) -> None:
    content = _write_day(root)
    with TapeWriter(root) as w:
        manifest = w.seal(DAY)
        w.finish_seal(DAY)
        with pytest.raises(TapeSealed):
            w.append("universe", DAY, rows(1)[0])
    names = sorted(p.name for p in (root / DAY).iterdir())
    assert names == sorted([MANIFEST, "candles.jsonl.gz", "universe.jsonl.gz"])
    reader = TapeReader(root)
    assert reader.sealed(DAY) and reader.manifest(DAY) == manifest
    for stream, items in content.items():
        assert reader.rows(DAY, stream) == items
        entry = next(f for f in manifest["files"] if f["file"] == f"{stream}.jsonl")
        raw = gzip.decompress((root / DAY / f"{stream}.jsonl.gz").read_bytes())
        assert entry["sha256"] == hashlib.sha256(raw).hexdigest() and entry["bytes"] == len(raw)
    assert manifest["root"] == segment_root(manifest["files"])


@pytest.mark.parametrize("crash_at", ["gz_tmp_written", "gz_renamed", "manifest_tmp_written", "manifest_written",
                                      "jsonl_deleted"])
def test_the_seal_survives_a_crash_at_every_step(tmp_path, crash_at, monkeypatch) -> None:
    clean_root, root = tmp_path / "clean", tmp_path / "crashy"
    _write_day(clean_root)
    with TapeWriter(clean_root) as w:
        clean = w.seal(DAY)
        w.finish_seal(DAY)
    content = _write_day(root)

    def crash(self, name):
        if name == crash_at:
            raise RuntimeError(f"killed at {name}")

    monkeypatch.setattr(TapeWriter, "_step", crash)
    with pytest.raises(RuntimeError), TapeWriter(root) as w:
        w.seal(DAY)
        w.finish_seal(DAY)
    # whatever the crash left behind, a reader sees every row exactly once
    for stream, items in content.items():
        assert TapeReader(root).rows(DAY, stream) == items
    monkeypatch.undo()
    with TapeWriter(root) as w:  # the next run finishes the job idempotently
        again = w.seal(DAY)
        w.finish_seal(DAY)
    assert again == clean
    assert sorted(p.name for p in (root / DAY).iterdir()) == sorted(p.name for p in (clean_root / DAY).iterdir())
    for stream, items in content.items():
        assert TapeReader(root).rows(DAY, stream) == items


# --------------------------------------------------------------------------- candles: first value wins, coverage


def api(ts: int, o: float, c: float | None = None, v: float = 10.0) -> dict:
    c = o if c is None else c
    return {"timestamp": ts * 1000, "open": str(o), "high": str(max(o, c) * 1.01), "low": str(min(o, c) * 0.99),
            "close": str(c), "volume": str(v)}


def test_candle_fetch_rows_keep_new_closed_minutes_and_count_revisions() -> None:
    m0 = T - T % 60
    first = candle_fetch_row(MINT, [api(m0, 1.0), api(m0 + 60, 1.1), api(m0 + 120, 1.2)], fetched_ts=m0 + 150,
                             previous=None, status=200)
    assert [r[0] for r in first["rows"]] == [m0, m0 + 60]  # the minute still open at fetch time is not stored
    assert first["cover"] == [None, m0 + 120] and first["revised"] == []
    second = candle_fetch_row(MINT, [api(m0, 1.0), api(m0 + 60, 9.9), api(m0 + 120, 1.2), api(m0 + 180, 1.3)],
                              fetched_ts=m0 + 250, previous=first, status=200)
    assert [r[0] for r in second["rows"]] == [m0 + 120, m0 + 180]  # only minutes not stored before
    assert [r[0] for r in second["revised"]] == [m0 + 60]  # a CHANGED closed minute: a counted revision
    view = TapeView(MINT, as_of=m0 + 10_000, rows={"candles": [first, second]}, l_obs=60)
    assert [c.c for c in view.candles()][:3] == [1.0, 1.1, 1.2]  # the FIRST value wins
    assert view.revisions == 1


def test_malformed_api_rows_are_skipped_never_raised() -> None:
    m0 = T - T % 60
    junk = [{"timestamp": "soon"}, None, "x", {**api(m0, 1.0), "volume": "lots"}, {**api(m0 + 60, 1.0), "open": "-1"},
            api(m0 + 120, 1.2)]
    row = candle_fetch_row(MINT, junk, fetched_ts=m0 + 600, previous=None, status=200, limit=len(junk))
    assert [r[0] for r in row["rows"]] == [m0, m0 + 120] and row["rows"][0][5] == "0"  # bad volume -> 0
    assert row["cover"] == [m0, m0 + 600]  # the row cap was hit: coverage starts at the first usable minute
    empty = candle_fetch_row(MINT, [{"timestamp": None}] * 3, fetched_ts=m0 + 600, previous=None, limit=3)
    assert empty["rows"] == [] and empty["cover"] == [m0 + 600, m0 + 600]  # truncated and unusable: nothing known
    assert TapeView(MINT, as_of=m0 + 10_000, rows={"candles": [row]}).candles()[0].v == 0.0


def test_a_truncated_fetch_leaves_a_hole_and_coverage_stops_there() -> None:
    m0 = T - T % 60
    first = candle_fetch_row(MINT, [api(m0 + 60 * i, 1.0 + i / 100) for i in range(10)], fetched_ts=m0 + 600,
                             previous=None, status=200, limit=1000)
    later = [api(m0 + 60 * i, 2.0) for i in range(20, 30)]  # the API's 1000-row cap hit: minutes 10-19 unknown
    second = candle_fetch_row(MINT, later, fetched_ts=m0 + 1800, previous=first, status=200, limit=len(later))
    assert second["cover"] == [m0 + 1200, m0 + 1800]
    view = TapeView(MINT, as_of=m0 + 10_000, rows={"candles": [first, second]}, l_obs=60)
    assert view.covered_until == m0 + 600 and view.complete_from_start
    assert view.candles()[-1].ts == m0 + 540  # nothing after the hole is ever used


def test_no_trade_minutes_are_flat_until_the_coverage_end() -> None:
    m0 = T - T % 60
    fetch = candle_fetch_row(MINT, [api(m0, 1.0, 1.5), api(m0 + 180, 2.0)], fetched_ts=m0 + 600, previous=None,
                             status=200)
    view = TapeView(MINT, as_of=m0 + 10_000, rows={"candles": [fetch]}, l_obs=60)
    got = view.candles()
    assert [c.ts for c in got] == [m0 + 60 * i for i in range(10)]  # extended flat to the fetch's last closed minute
    assert got[1] == Candle(m0 + 60, 1.5, 1.5, 1.5, 1.5, 0.0) and got[-1] == Candle(m0 + 540, 2.0, 2.0, 2.0, 2.0, 0.0)


def test_a_late_trade_in_a_covered_empty_minute_is_a_revision_not_a_value() -> None:
    m0 = T - T % 60
    first = candle_fetch_row(MINT, [api(m0, 1.0)], fetched_ts=m0 + 300, previous=None, status=200)
    second = candle_fetch_row(MINT, [api(m0, 1.0), api(m0 + 120, 5.0), api(m0 + 300, 1.1)], fetched_ts=m0 + 600,
                              previous=first, status=200)
    assert [r[0] for r in second["revised"]] == [m0 + 120]
    view = TapeView(MINT, as_of=m0 + 10_000, rows={"candles": [first, second]}, l_obs=60)
    assert view.candles()[2] == Candle(m0 + 120, 1.0, 1.0, 1.0, 1.0, 0.0)  # it was "no trade" first


# --------------------------------------------------------------------------- visibility


def test_view_hides_candles_until_m_plus_60_plus_l_obs_and_state_until_fetched() -> None:
    m0 = T - T % 60
    fetch = candle_fetch_row(MINT, [api(m0 + 60 * i, 1.0 + i) for i in range(10)], fetched_ts=m0 + 3600,
                             previous=None, status=200)
    snap = {"v": 1, "ts": m0 + 500.0, "mint": MINT, "age_min": 5, "pair": {"priceUsd": "1"}}
    universe = {"v": 1, "ts": m0 + 30.0, "mint": MINT, "created_ts": m0 - 600.0, "launch": {"symbol": "X"}}
    rows_ = {"candles": [fetch], "snaps": [snap], "universe": [universe]}
    view = TapeView(MINT, as_of=m0 + 60 * 5 + 60 + 90, rows=rows_, l_obs=90)
    assert [c.ts for c in view.candles()] == [m0 + 60 * i for i in range(6)]  # minute 5 visible exactly now
    assert view.state("snaps") == []  # fetched after as_of
    assert TapeView(MINT, as_of=m0 + 500, rows=rows_, l_obs=90).state("snaps") == [snap]
    assert view.launch == {"symbol": "X"} and view.created_ts == m0 - 600
    assert TapeView(MINT, as_of=m0 - 700, rows=rows_).launch is None  # not created yet


def test_reader_groups_a_days_rows_by_mint(root) -> None:
    with TapeWriter(root) as w:
        w.append("universe", DAY, {"v": 1, "ts": T, "mint": "A"})
        w.append("universe", DAY, {"v": 1, "ts": T, "mint": "B"})
        w.append("candles", DAY, {"v": 1, "ts": T, "mint": "A", "rows": []})
    grouped = TapeReader(root).coins(DAY)
    assert sorted(grouped) == ["A", "B"] and len(grouped["A"]["candles"]) == 1 and grouped["B"]["candles"] == []
    assert TapeReader(root).days() == [DAY]
