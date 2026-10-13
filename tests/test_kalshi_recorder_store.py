"""Rotating, compressed, hashed storage with a cap that never deletes unscored Family A evidence."""

from __future__ import annotations

import base64
import gzip
import json
import os
from pathlib import Path

import pytest

from nightcrawler.kalshi_recorder_store import (
    LEVEL_OK,
    LEVEL_PAUSED,
    LEVEL_SHED,
    RecorderStore,
    file_sha256,
    iter_records,
    load_index,
)

MB = 1024 * 1024
T0 = 1_791_900_000.0  # 2026-10-13 14:00 UTC, on an hour boundary


class Clock:
    def __init__(self, at: float = T0) -> None:
        self.at = at

    def __call__(self) -> float:
        return self.at


def store(tmp_path: Path, clock: Clock, **kwargs: object) -> RecorderStore:
    options: dict[str, object] = {"max_bytes": 64 * MB, "min_free_bytes": 0, "clock": clock,
                                  "disk_free": lambda path: 10 ** 12, "headroom_bytes": 16 * 1024}
    options.update(kwargs)
    return RecorderStore(tmp_path, **options)  # type: ignore[arg-type]


def test_records_rotate_hourly_into_sealed_hashed_gzip_segments(tmp_path: Path) -> None:
    clock = Clock()
    box = store(tmp_path, clock)
    for minute in range(0, 120, 10):
        box.append("books", "book", {"ticker": "A", "n": minute}, T0 + minute * 60)
    clock.at = T0 + 2 * 3600 + 1
    box.seal_hour(clock.at)
    segments = load_index(tmp_path)
    assert [segment.records for segment in segments] == [6, 6]
    for segment in segments:
        path = tmp_path / segment.path
        assert path.name.endswith(".jsonl.gz") and file_sha256(path) == segment.sha256
    assert segments[1].prev_sha256 == segments[0].sha256  # a per-lane chain that may start at any segment
    rows = list(iter_records(tmp_path, frozenset({"books"})))
    assert [row["n"] for row in rows] == list(range(0, 120, 10))
    assert [row["seq"] for row in rows] == list(range(1, 13))
    box.close()


def test_a_tampered_segment_is_refused(tmp_path: Path) -> None:
    clock = Clock()
    box = store(tmp_path, clock)
    box.append("trades", "trades", {"rows": [1]}, T0)
    box.close()
    segment = load_index(tmp_path)[0]
    with gzip.open(tmp_path / segment.path, "wb") as stream:
        stream.write(b'{"seq":1,"lane":"trades","kind":"trades","at":1,"rows":[2]}\n')
    with pytest.raises(ValueError, match="index hash"):
        list(iter_records(tmp_path, frozenset({"trades"})))


def test_a_crash_keeps_complete_lines_drops_the_torn_tail_and_reports_it(tmp_path: Path) -> None:
    clock = Clock()
    box = store(tmp_path, clock)
    for index in range(5):
        box.append("books", "book", {"n": index}, T0 + index)
    box.flush()
    part = next(tmp_path.rglob("*.part"))
    raw = part.read_bytes()
    box._lock_file.close()  # simulate the process dying without sealing
    part.write_bytes(raw[:-3])  # tear the gzip stream mid-member
    again = store(tmp_path, clock)
    recovered = again.recovered[0]
    assert recovered["lane"] == "books" and recovered["records"] >= 1
    assert not list(tmp_path.rglob("*.part"))
    rows = list(iter_records(tmp_path, frozenset({"books"})))
    assert [row["n"] for row in rows] == list(range(len(rows)))
    seq = again.append("books", "book", {"n": 99}, T0 + 10)
    assert seq is not None and seq > max(row["seq"] for row in rows)
    again.close()


def test_one_writer_per_directory(tmp_path: Path) -> None:
    box = store(tmp_path, Clock())
    with pytest.raises(RuntimeError, match="Another recorder"):
        store(tmp_path, Clock())
    box.close()


def _fill(box: RecorderStore, lane: str, hours: int, start: float, size: int = 150_000) -> None:
    for hour in range(hours):
        blob = base64.b64encode(os.urandom(size)).decode()  # incompressible, so sizes are real
        box.append(lane, "blob", {"blob": blob, "hour": hour}, start + hour * 3600)


def test_protect_policy_deletes_only_old_btc15m_then_sheds_then_pauses(tmp_path: Path) -> None:
    clock = Clock()
    box = store(tmp_path, clock, max_bytes=40 * MB, btc15m_retention_s=3600.0)
    _fill(box, "books_btc15m", 6, T0)
    _fill(box, "books", 6, T0)
    clock.at = T0 + 7 * 3600
    box.seal_hour(clock.at)
    familya_before = {segment.path for segment in load_index(tmp_path) if segment.lane == "books"}
    box.max_bytes = int(box.used_bytes() * 0.9)  # tighten the cap below what is stored
    status = box.enforce()
    assert "btc15m_older_than_retention" in status.reasons
    assert {segment.path for segment in load_index(tmp_path) if segment.lane == "books"} == familya_before
    deleted = [json.loads(line) for line in (tmp_path / "index.jsonl").read_text().splitlines()
               if json.loads(line)["kind"] == "deleted"]
    assert deleted and all(row["lane"] == "books_btc15m" for row in deleted)
    # Far below what Family A alone needs: every old KXBTC15M segment goes, Family A stays, capture pauses.
    box.max_bytes = int(box.used_bytes() * 0.5)
    assert box.enforce().level == LEVEL_PAUSED
    assert {segment.lane for segment in load_index(tmp_path)} == {"books"}
    assert {segment.path for segment in load_index(tmp_path) if segment.lane == "books"} == familya_before
    # Family A alone is over the soft cap: KXBTC15M/spot are shed (refused), Family A still records.
    box.max_bytes = int(box.used_bytes() / 0.97)
    assert box.enforce().level == LEVEL_SHED
    assert box.append("books_btc15m", "book", {}, clock.at) is None
    assert box.append("books", "book", {}, clock.at) is not None
    # At the hard cap everything pauses; nothing of Family A was deleted to make room.
    box.max_bytes = box.used_bytes() + 1024
    assert box.enforce().level == LEVEL_PAUSED
    assert box.append("books", "book", {}, clock.at) is None
    assert {segment.path for segment in load_index(tmp_path) if segment.lane == "books"} >= familya_before
    box.close()


def test_rotate_policy_is_a_plain_ring_buffer(tmp_path: Path) -> None:
    clock = Clock()
    box = store(tmp_path, clock, policy="rotate", max_bytes=40 * MB)
    _fill(box, "books", 8, T0)
    clock.at = T0 + 9 * 3600
    box.seal_hour(clock.at)
    oldest = min(load_index(tmp_path), key=lambda segment: segment.first_at).path
    box.max_bytes = int(box.used_bytes() * 0.8)
    status = box.enforce()
    assert status.level == LEVEL_OK and "rotate_oldest" in status.reasons
    assert oldest not in {segment.path for segment in load_index(tmp_path)}
    box.close()


def test_owner_release_date_frees_old_family_a_segments_under_protect(tmp_path: Path) -> None:
    clock = Clock()
    box = store(tmp_path, clock, max_bytes=40 * MB, release_before=T0 + 2 * 3600)
    _fill(box, "books", 6, T0)
    clock.at = T0 + 7 * 3600
    box.seal_hour(clock.at)
    box.max_bytes = int(box.used_bytes() * 0.9)
    status = box.enforce()
    assert "released_by_owner" in status.reasons
    assert min(segment.first_at for segment in load_index(tmp_path)) >= T0 + 3600
    box.close()


def test_the_disk_reserve_pauses_capture(tmp_path: Path) -> None:
    free = {"bytes": 10 ** 12}
    box = store(tmp_path, Clock(), min_free_bytes=100 * MB, disk_free=lambda path: free["bytes"])
    assert box.enforce().level == LEVEL_OK
    free["bytes"] = 50 * MB
    assert box.enforce().level == LEVEL_PAUSED
    assert box.append("books", "book", {}) is None
    box.close()


def test_unknown_lanes_are_refused(tmp_path: Path) -> None:
    box = store(tmp_path, Clock())
    with pytest.raises(ValueError, match="Unknown recorder lane"):
        box.append("orders", "x", {})
    box.close()


def test_recovering_a_large_part_streams_it_in_bounded_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review F4: recovery decompressed a whole hour and copied it twice (687 MiB peak for a 63 MiB part)."""
    import tracemalloc

    from nightcrawler import kalshi_recorder_store

    monkeypatch.setattr(kalshi_recorder_store, "SEGMENT_RAW_BYTES", 1 << 31)  # one big part, as 64 MiB rotation allowed
    clock = Clock()
    box = store(tmp_path, clock, max_bytes=1 << 33)
    levels = [[f"0.{index:02d}00", f"{index * 7}.00"] for index in range(1, 99)]
    written = 0
    while box.open.get("books_btc15m") is None or box.open["books_btc15m"].raw_bytes < 12 * MB:
        box.append("books_btc15m", "book", {"ticker": "KXBTC15M-X", "orderbook_fp": {"yes_dollars": levels,
                                                                                     "no_dollars": levels}},
                   T0 + written * 0.001)
        written += 1
    box.flush()
    box._lock_file.close()  # the process died without sealing
    tracemalloc.start()
    try:
        again = store(tmp_path, clock, max_bytes=1 << 33)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert again.recovered[0]["records"] == written and again.recovered[0]["dropped_bytes"] == 0
    assert peak < 6 * MB, f"recovery peaked at {peak / MB:.1f} MiB for a 12 MiB part"
    assert sum(1 for _ in iter_records(tmp_path, frozenset({"books_btc15m"}))) == written
    again.close()


def test_segments_rotate_at_eight_mib_so_one_crash_loses_little() -> None:
    from nightcrawler.kalshi_recorder_store import SEGMENT_RAW_BYTES

    assert SEGMENT_RAW_BYTES == 8 * MB


def test_the_cap_counts_every_file_under_the_root_and_rotate_prunes_old_manifests(tmp_path: Path) -> None:
    """Review F7: manifests, state and status files were outside the cap."""
    clock = Clock()
    box = store(tmp_path, clock, policy="rotate", max_bytes=40 * MB)
    before = box.used_bytes()
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "coverage-2026-10-13T12.json").write_bytes(b"x" * MB)  # an hour before any segment
    (manifests / "coverage-2026-10-13T15.json").write_bytes(b"y" * 1024)
    assert box.used_bytes() >= before + MB
    _fill(box, "books", 3, T0)
    clock.at = T0 + 4 * 3600
    box.seal_hour(clock.at)
    status = box.enforce()
    assert "manifest_older_than_retained_segments" in status.reasons
    assert sorted(path.name for path in manifests.iterdir()) == ["coverage-2026-10-13T15.json"]
    box.close()
