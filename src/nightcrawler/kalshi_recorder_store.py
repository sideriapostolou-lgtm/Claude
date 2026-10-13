"""Bounded, rotating, compressed storage for the public Kalshi recorder.

Layout under ``DATA_DIR/kalshi_recorder/``::

    segments/<lane>/<YYYY-MM-DD>/<lane>-<YYYYMMDDTHHMMSSZ>-<first seq>.jsonl.gz   sealed, hashed
    segments/<lane>/<YYYY-MM-DD>/...jsonl.gz.part                                   the open hour
    index.jsonl          append-only: every sealed segment (sha256, records, times) and every deletion
    state.json           the next local sequence number and the storage level, written atomically

Every record is one JSON line with a local sequence number. Segments rotate every UTC hour (or at
8 MiB uncompressed) and are sealed with gzip; the index keeps a per-lane hash chain
(``prev_sha256``) that may start at any retained segment, so old segments can be deleted without
breaking verification of the rest. A crash leaves a ``.part`` file; on restart its complete lines
are kept (streamed, so recovery needs memory for one line, not one hour), the torn tail is dropped
and counted, and a gap is reported. Nothing is fabricated.

The cap counts every file under the root (segments, index, state, status, manifests), not only
the segments.

The cap (default 2 GiB) is enforced in the order of PROTOCOL.md section 12. Under the default
``protect`` policy the recorder never deletes unscored Family A evidence: it first deletes
KXBTC15M (and optional spot) segments older than their retention, then sheds those lanes, then
pauses. ``rotate`` (a plain ring buffer, for use outside the protocol) deletes the oldest
segments of any class. Family A segments older than an owner-set ``release_before`` date may
be deleted under either policy.
"""

from __future__ import annotations

import contextlib
import fcntl
import gzip
import hashlib
import json
import os
import shutil
import threading
import time
import zlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

# Which retention class every lane belongs to. Family A evidence is "familya"; operations logs that
# coverage depends on are "ops" and are protected like Family A.
LANE_CLASS = {
    "books": "familya", "book_calls": "familya", "trades": "familya", "trade_coverage": "familya",
    "discovery": "familya", "admissions": "familya", "markets": "familya", "fees": "familya",
    "settlement": "familya", "other": "familya",
    "books_btc15m": "btc15m", "trades_btc15m": "btc15m", "btc15m_meta": "btc15m",
    "spot": "spot",
    "requests": "ops", "gaps": "ops", "telemetry": "ops",
}
SHEDDABLE = frozenset({"btc15m", "spot"})
RESERVED = frozenset({"seq", "lane", "kind", "at"})
SEGMENT_RAW_BYTES = 8 * 1024 * 1024  # small segments keep crash recovery and replay reads cheap
SALVAGE_OUT_BYTES = 1024 * 1024
FLUSH_EVERY_S = 5.0
HEADROOM_BYTES = 16 * 1024 * 1024
SOFT_CAP = 0.95
LEVEL_OK, LEVEL_SHED, LEVEL_PAUSED = 0, 1, 2


def _utc(at: float) -> datetime:
    return datetime.fromtimestamp(at, UTC)


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(256 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class Salvage:
    """What a streamed pass over a possibly torn gzip JSONL file found (complete lines only)."""

    records: int = 0
    raw_bytes: int = 0
    dropped_bytes: int = 0
    first_seq: int | None = None
    last_seq: int | None = None
    first_at: float | None = None
    last_at: float | None = None

    def take(self, line: bytes) -> bool:
        """Count one line; False when it is not a complete recorder record (everything after it is dropped)."""
        try:
            record = json.loads(line)
            seq, at = int(record["seq"]), float(record["at"])
        except (ValueError, TypeError, KeyError, RecursionError):
            return False
        self.records += 1
        self.raw_bytes += len(line)
        self.first_seq = seq if self.first_seq is None else min(self.first_seq, seq)
        self.last_seq = seq if self.last_seq is None else max(self.last_seq, seq)
        self.first_at = at if self.first_at is None else min(self.first_at, at)
        self.last_at = at if self.last_at is None else max(self.last_at, at)
        return True


def salvage(path: Path, sink: Callable[[bytes], Any] | None = None) -> Salvage:
    """Stream the complete JSON lines of a possibly torn gzip file, optionally passing each one to ``sink``.

    Memory stays at one chunk plus one line: the file is decompressed incrementally and nothing is kept.
    The first torn or unreadable line ends the salvage; it and everything after it count as dropped bytes.
    """
    out = Salvage()
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    pending = b""
    total = 0
    stopped = False

    def feed(data: bytes) -> None:
        nonlocal pending, stopped
        pending += data
        start = 0
        while (end := pending.find(b"\n", start)) >= 0:
            line = pending[start:end + 1]
            if not out.take(line):
                stopped = True
                pending = b""
                return
            if sink is not None:
                sink(line)
            start = end + 1
        pending = pending[start:]

    torn = False
    with path.open("rb") as stream:
        while not torn and not decompressor.eof and (chunk := stream.read(64 * 1024)):
            while chunk and not decompressor.eof:
                try:  # at most 1 MiB out per call: book segments compress about 100 to 1
                    data = decompressor.decompress(chunk, SALVAGE_OUT_BYTES)
                except zlib.error:
                    torn = True
                    break
                chunk = decompressor.unconsumed_tail
                total += len(data)  # counted even after a bad line, so the dropped tail is exact
                if not stopped:
                    feed(data)
    with contextlib.suppress(zlib.error):
        tail = decompressor.flush()
        total += len(tail)
        if not stopped:
            feed(tail)
    out.dropped_bytes = total - out.raw_bytes
    return out


def read_complete_lines(path: Path) -> tuple[list[bytes], int]:
    """Lines of a possibly torn gzip file and the dropped byte count (small files and tests only)."""
    import io

    buffer = io.BytesIO()
    found = salvage(path, buffer.write)
    return buffer.getvalue().splitlines(keepends=True), found.dropped_bytes


@dataclass
class _Open:
    lane: str
    path: Path
    raw: BinaryIO
    gz: gzip.GzipFile
    hour: str
    first_seq: int
    first_at: float
    last_at: float
    last_seq: int = 0
    records: int = 0
    raw_bytes: int = 0
    flushed_at: float = 0.0


@dataclass
class Segment:
    path: str
    lane: str
    klass: str
    first_seq: int
    last_seq: int
    first_at: float
    last_at: float
    records: int
    raw_bytes: int
    gz_bytes: int
    sha256: str
    prev_sha256: str | None
    recovered: bool = False
    dropped_bytes: int = 0

    def row(self) -> dict[str, Any]:
        return {"kind": "segment", **self.__dict__}


@dataclass
class StoreStatus:
    level: int
    used_bytes: int
    cap_bytes: int
    free_bytes: int
    deleted_segments: int
    deleted_bytes: int
    reasons: list[str] = field(default_factory=list)


class RecorderStore:
    """Single-writer store (an exclusive file lock); thread-safe appends."""

    def __init__(self, root: Path, *, max_bytes: int, min_free_bytes: int, policy: str = "protect",
                 btc15m_retention_s: float = 72 * 3600.0, release_before: float | None = None,
                 clock: Callable[[], float] = time.time,
                 disk_free: Callable[[Path], int] | None = None, headroom_bytes: int = HEADROOM_BYTES) -> None:
        if policy not in ("protect", "rotate"):
            raise ValueError("Storage policy must be protect or rotate")
        if max_bytes <= headroom_bytes * 2:
            raise ValueError("Storage cap is too small to hold a segment")
        self.headroom = headroom_bytes
        self.root = root
        self.segments_dir = root / "segments"
        self.segments_dir.mkdir(parents=True, exist_ok=True)
        self.max_bytes, self.min_free_bytes, self.policy = max_bytes, min_free_bytes, policy
        self.btc15m_retention_s, self.release_before = btc15m_retention_s, release_before
        self.clock = clock
        self._disk_free = disk_free or (lambda path: shutil.disk_usage(path).free)
        self._mutex = threading.RLock()
        self._lock_file = (root / "recorder.lock").open("a", encoding="utf-8")
        try:
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock_file.close()
            raise RuntimeError("Another recorder process owns this data directory") from None
        self.index_path = root / "index.jsonl"
        self.state_path = root / "state.json"
        self.segments: dict[str, Segment] = {}
        self.chain: dict[str, str] = {}
        self.open: dict[str, _Open] = {}
        self.level = LEVEL_OK
        self.deleted_segments = self.deleted_bytes = 0
        self.recovered: list[dict[str, Any]] = []
        self.next_seq = 1
        self._load()
        self._recover_parts()
        self.sealed_bytes = sum(segment.gz_bytes for segment in self.segments.values())

    # ------------------------------------------------------------------ startup
    def _load(self) -> None:
        if self.state_path.exists():
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or state.get("version") != 1:
                raise ValueError("Unreadable recorder state; inspect it before recording again")
            self.next_seq = int(state["next_seq"])
        if self.index_path.exists():
            raw = self.index_path.read_bytes()
            if raw and not raw.endswith(b"\n"):
                # A torn last index row (crash mid-write): cut it; its segment is adopted below.
                with self.index_path.open("r+b") as stream:
                    stream.truncate(raw.rfind(b"\n") + 1)
            with self.index_path.open("r", encoding="utf-8") as stream:
                for number, line in enumerate(stream, 1):
                    row = json.loads(line)
                    if row.get("kind") == "segment":
                        segment = Segment(**{key: value for key, value in row.items() if key != "kind"})
                        self.segments[segment.path] = segment
                        self.chain[segment.lane] = segment.sha256
                        self.next_seq = max(self.next_seq, segment.last_seq + 1)
                    elif row.get("kind") == "deleted":
                        self.segments.pop(row["path"], None)
                    else:
                        raise ValueError(f"Unknown recorder index row at line {number}")
        for path, segment in list(self.segments.items()):
            if not (self.root / path).exists():  # deleted, but the crash came before its index row
                self._index({"kind": "deleted", "path": path, "lane": segment.lane, "reason": "missing_on_load",
                             "at": self.clock(), "sha256": segment.sha256})
                self.segments.pop(path)
        for orphan in sorted(self.segments_dir.rglob("*.jsonl.gz")):
            relative = str(orphan.relative_to(self.root))
            if relative not in self.segments:  # sealed, but the crash came before its index row
                self._adopt(orphan, orphan.parent.parent.name, keep=True)

    @staticmethod
    def _reseal(source: Path, destination: Path) -> Salvage:
        """Copy the complete lines of ``source`` into a fresh sealed gzip at ``destination`` (streamed)."""
        temporary = destination.with_name(destination.name + ".tmp")
        with temporary.open("wb") as raw:
            with gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=6, mtime=0) as gz:
                found = salvage(source, gz.write)
            raw.flush()
            os.fsync(raw.fileno())
        if found.records:
            os.replace(temporary, destination)
        else:
            temporary.unlink()
        return found

    def _adopt(self, source: Path, lane: str, *, keep: bool) -> None:
        """Index the complete lines of a ``.part`` file (re-sealed) or an unindexed sealed segment."""
        relative = str(source.relative_to(self.root))
        destination = source.with_name(source.name.removesuffix(".part").removesuffix(".jsonl.gz") + ".jsonl.gz")
        if keep:
            found = salvage(source)  # an intact sealed orphan is indexed as it is
            if found.records and found.dropped_bytes:
                found = self._reseal(source, destination)
        else:
            found = self._reseal(source, destination)
        if not found.records:
            source.unlink(missing_ok=True)
            self.recovered.append({"lane": lane, "path": relative, "records": 0, "dropped_bytes": found.dropped_bytes})
            return
        if source != destination:
            source.unlink(missing_ok=True)
        _fsync_dir(destination.parent)
        assert found.first_seq is not None and found.last_seq is not None
        assert found.first_at is not None and found.last_at is not None
        segment = Segment(str(destination.relative_to(self.root)), lane, LANE_CLASS.get(lane, "familya"),
                          found.first_seq, found.last_seq, found.first_at, found.last_at, found.records,
                          found.raw_bytes, destination.stat().st_size, file_sha256(destination), self.chain.get(lane),
                          True, found.dropped_bytes)
        self._index(segment.row())
        self.segments[segment.path] = segment
        self.chain[lane] = segment.sha256
        self.next_seq = max(self.next_seq, segment.last_seq + 1)
        self.recovered.append({"lane": lane, "path": segment.path, "records": segment.records,
                               "dropped_bytes": found.dropped_bytes, "last_at": segment.last_at})

    def _recover_parts(self) -> None:
        for leftover in self.segments_dir.rglob("*.jsonl.gz.tmp"):  # a crash during an earlier recovery
            leftover.unlink(missing_ok=True)
        for part in sorted(self.segments_dir.rglob("*.jsonl.gz.part")):
            self._adopt(part, part.parent.parent.name, keep=False)
        self._save_state()

    # ------------------------------------------------------------------ writing
    def _index(self, row: dict[str, Any]) -> None:
        with self.index_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def _save_state(self) -> None:
        atomic_json(self.state_path, {"version": 1, "next_seq": self.next_seq, "level": self.level,
                                      "saved_at": self.clock()})

    def lane_allowed(self, lane: str) -> bool:
        klass = LANE_CLASS.get(lane, "familya")
        return self.level == LEVEL_OK or (self.level == LEVEL_SHED and klass not in SHEDDABLE)

    def append(self, lane: str, kind: str, payload: dict[str, Any], at: float | None = None) -> int | None:
        """Write one record; returns its sequence number, or None when the cap paused or shed this lane."""
        if lane not in LANE_CLASS:
            raise ValueError(f"Unknown recorder lane {lane!r}")
        if payload.keys() & RESERVED:
            raise ValueError(f"Record payloads may not set {sorted(payload.keys() & RESERVED)}")
        with self._mutex:
            if not self.lane_allowed(lane):
                return None
            when = self.clock() if at is None else at
            seq = self.next_seq
            record = {"seq": seq, "lane": lane, "kind": kind, "at": when, **payload}
            line = (json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n").encode()
            handle = self._handle(lane, when, seq)
            handle.gz.write(line)
            handle.records += 1
            handle.raw_bytes += len(line)
            handle.last_seq, handle.last_at = seq, max(handle.last_at, when)
            self.next_seq = seq + 1
            if when - handle.flushed_at >= FLUSH_EVERY_S:
                handle.gz.flush(zlib.Z_SYNC_FLUSH)
                handle.raw.flush()
                handle.flushed_at = when
            if handle.raw_bytes >= SEGMENT_RAW_BYTES:
                self._seal(lane)
            return seq

    def _handle(self, lane: str, at: float, seq: int) -> _Open:
        hour = _utc(at).strftime("%Y-%m-%dT%H")
        handle = self.open.get(lane)
        if handle is not None and handle.hour != hour:
            self._seal(lane)
            handle = None
        if handle is None:
            stamp = _utc(at)
            directory = self.segments_dir / lane / stamp.strftime("%Y-%m-%d")
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{lane}-{stamp.strftime('%Y%m%dT%H%M%SZ')}-{seq:012d}.jsonl.gz.part"
            raw = path.open("xb")
            gz = gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=6, mtime=0)
            handle = _Open(lane, path, raw, gz, hour, seq, at, at, flushed_at=at)
            self.open[lane] = handle
        return handle

    def _seal(self, lane: str) -> Segment | None:
        handle = self.open.pop(lane, None)
        if handle is None:
            return None
        handle.gz.close()
        handle.raw.flush()
        os.fsync(handle.raw.fileno())
        handle.raw.close()
        if handle.records == 0:
            handle.path.unlink()
            return None
        destination = handle.path.with_name(handle.path.name[:-len(".part")])
        os.replace(handle.path, destination)
        _fsync_dir(destination.parent)
        segment = Segment(str(destination.relative_to(self.root)), lane, LANE_CLASS[lane], handle.first_seq,
                          handle.last_seq, handle.first_at, handle.last_at, handle.records, handle.raw_bytes,
                          destination.stat().st_size, file_sha256(destination), self.chain.get(lane))
        self._index(segment.row())
        self.segments[segment.path] = segment
        self.chain[lane] = segment.sha256
        self.sealed_bytes += segment.gz_bytes
        self._save_state()
        return segment

    def seal_hour(self, now: float) -> list[Segment]:
        """Seal every open segment from an earlier UTC hour (called each minute by the recorder)."""
        hour = _utc(now).strftime("%Y-%m-%dT%H")
        with self._mutex:
            sealed = [self._seal(lane) for lane, handle in list(self.open.items()) if handle.hour != hour]
            return [segment for segment in sealed if segment is not None]

    def flush(self) -> None:
        with self._mutex:
            for handle in self.open.values():
                handle.gz.flush(zlib.Z_SYNC_FLUSH)
                handle.raw.flush()
                os.fsync(handle.raw.fileno())
            self._save_state()

    def close(self) -> None:
        with self._mutex:
            try:
                for lane in list(self.open):
                    self._seal(lane)
                self._save_state()
            finally:
                self._lock_file.close()

    # ------------------------------------------------------------------ the cap
    def _other_bytes(self) -> int:
        """Every file under the root outside ``segments/``: index, state, status, manifests and leftovers."""
        total = 0
        stack = [self.root]
        while stack:
            with contextlib.suppress(OSError), os.scandir(stack.pop()) as entries:
                for entry in entries:
                    with contextlib.suppress(OSError):
                        if entry.is_dir(follow_symlinks=False):
                            if Path(entry.path) != self.segments_dir:
                                stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
        return total

    def used_bytes(self, other: int | None = None) -> int:
        """Bytes this store occupies: sealed and open segments plus every other file under the root."""
        with self._mutex:
            open_bytes = sum(handle.raw.tell() for handle in self.open.values())
            return self.sealed_bytes + open_bytes + (self._other_bytes() if other is None else other)

    def _prune_manifests(self, before: float, reason: str) -> list[str]:
        """Delete hourly manifests for hours ending before ``before`` (their hashes stay in the telemetry lane)."""
        removed: list[str] = []
        for path in sorted((self.root / "manifests").glob("coverage-*.json")):
            try:
                hour = datetime.strptime(path.name[len("coverage-"):len("coverage-") + 13] + "+0000", "%Y-%m-%dT%H%z")
            except ValueError:
                continue
            if hour.timestamp() + 3600 <= before:
                path.unlink(missing_ok=True)
                removed.append(reason)
        return removed

    def _delete(self, segment: Segment, reason: str) -> None:
        path = self.root / segment.path
        size = path.stat().st_size if path.exists() else 0
        if path.exists():
            path.unlink()
        self._index({"kind": "deleted", "path": segment.path, "lane": segment.lane, "reason": reason,
                     "at": self.clock(), "sha256": segment.sha256})
        self.segments.pop(segment.path, None)
        self.sealed_bytes -= segment.gz_bytes
        self.deleted_segments += 1
        self.deleted_bytes += size

    def _deletable(self, now: float) -> list[tuple[Segment, str]]:
        ordered = sorted(self.segments.values(), key=lambda segment: (segment.last_at, segment.path))
        out: list[tuple[Segment, str]] = []
        for segment in ordered:
            if segment.klass in SHEDDABLE and segment.last_at < now - self.btc15m_retention_s:
                out.append((segment, f"{segment.klass}_older_than_retention"))
            elif (self.release_before is not None and segment.klass not in SHEDDABLE
                  and segment.last_at < self.release_before):
                out.append((segment, "released_by_owner"))
        if self.policy == "rotate":
            chosen = {segment.path for segment, _ in out}
            out.extend((segment, "rotate_oldest") for segment in ordered if segment.path not in chosen)
        return out

    def enforce(self) -> StoreStatus:
        """Delete what the policy allows, then set the level: OK, shed KXBTC15M/spot, or paused."""
        with self._mutex:
            now = self.clock()
            reasons: list[str] = []
            soft = int(self.max_bytes * SOFT_CAP)
            other = self._other_bytes()
            for segment, reason in self._deletable(now):
                if self.used_bytes(other) < soft and self._disk_free(self.root) > self.min_free_bytes + self.headroom:
                    break
                self._delete(segment, reason)
                reasons.append(reason)
            # Manifests follow the segments they describe: under rotate, those older than every retained
            # segment go; under protect, only those before the owner's release date.
            if self.policy == "rotate" and self.segments:
                reasons += self._prune_manifests(min(segment.first_at for segment in self.segments.values()),
                                                 "manifest_older_than_retained_segments")
            elif self.release_before is not None:
                reasons += self._prune_manifests(self.release_before, "manifest_released_by_owner")
            used, free = self.used_bytes(), self._disk_free(self.root)
            if used + self.headroom >= self.max_bytes or free <= self.min_free_bytes:
                level = LEVEL_PAUSED
            elif used >= soft or free <= self.min_free_bytes + 4 * self.headroom:
                level = LEVEL_SHED
            else:
                level = LEVEL_OK
            if level != self.level:
                self.level = level
                self._save_state()
            return StoreStatus(self.level, used, self.max_bytes, free, self.deleted_segments, self.deleted_bytes,
                               sorted(set(reasons)))


def iter_segment(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rb") as stream:
        for line in stream:
            yield json.loads(line)


def load_index(root: Path) -> list[Segment]:
    """The retained sealed segments in index order (deleted ones removed)."""
    segments: dict[str, Segment] = {}
    index = root / "index.jsonl"
    if not index.exists():
        return []
    with index.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.endswith("\n"):
                break
            row = json.loads(line)
            if row.get("kind") == "segment":
                segment = Segment(**{key: value for key, value in row.items() if key != "kind"})
                segments[segment.path] = segment
            elif row.get("kind") == "deleted":
                segments.pop(row["path"], None)
    return list(segments.values())


def iter_records(root: Path, lanes: set[str] | frozenset[str], *, start: float = float("-inf"),
                 end: float = float("inf"), verify: bool = True) -> Iterator[dict[str, Any]]:
    """Records of the named lanes from sealed segments whose times overlap [start, end], segment by segment.

    Each segment's SHA-256 is checked against the index before it is read (``verify``); a mismatch raises.
    Within a lane, records come in write (receive-time) order.
    """
    chosen = sorted((segment for segment in load_index(root)
                     if segment.lane in lanes and segment.last_at >= start and segment.first_at <= end),
                    key=lambda segment: (segment.first_at, segment.first_seq))
    for segment in chosen:
        path = root / segment.path
        if verify and file_sha256(path) != segment.sha256:
            raise ValueError(f"Recorder segment {segment.path} does not match its index hash")
        for record in iter_segment(path):
            if start <= float(record["at"]) <= end:
                yield record
