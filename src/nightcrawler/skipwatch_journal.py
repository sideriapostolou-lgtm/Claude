"""Lossless, hash-chained JSONL batches with sealed gzip segments.

Only a short durable-boundary snapshot is locked for readers. Active files
remain append-only; fitting never stalls observation while scanning old data.
"""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import os
import re
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GENESIS = "0" * 64
MAX_LINE = 4 * 1024 * 1024
BATCH_BYTES = 512 * 1024
SEGMENT_BYTES = 4 * 1024 * 1024
PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}(?:-\d{20})?\.jsonl(?:\.gz)?$")


def record_hash(record: dict[str, Any]) -> str:
    value = {key: item for key, item in record.items() if key != "hash"}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False, ensure_ascii=True).encode()).hexdigest()


def source_paths(directory: Path) -> list[Path]:
    paths = [path for path in directory.iterdir() if path.is_file() and PATTERN.fullmatch(path.name)]
    # Publication is gzip rename, then raw unlink. A crash between them leaves
    # equivalent copies; the sealed copy is authoritative only after validation.
    compressed = {path.name[:-3] for path in paths if path.suffix == ".gz"}
    return sorted((path for path in paths if path.suffix == ".gz" or path.name not in compressed),
                  key=lambda path: (path.name[:10], int(path.name[11:31]) if path.name[10] == "-" else 0))


def iter_records(directory: Path) -> Iterator[dict[str, Any]]:
    with (directory / "journal.lock").open("a", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
        snapshot = [(path, path.stat().st_size) for path in source_paths(directory)]
        # Open before releasing the lock: sealing may unlink the raw pathname,
        # but these descriptors still point to the validated immutable prefix.
        streams = [(path, size, path.open("rb") if path.suffix != ".gz" else None) for path, size in snapshot]
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    seq, previous, batch_seq, anchor = 0, GENESIS, 0, None
    try:
        for path, size, pinned in streams:
            # A sealed gzip file cannot grow. Plain files are restricted to the
            # complete prefix captured while no append was in progress.
            raw = path.open("rb") if pinned is None else pinned
            stream: Any = gzip.GzipFile(fileobj=raw, mode="rb") if path.suffix == ".gz" else raw
            consumed = 0
            try:
                while path.suffix == ".gz" or consumed < size:
                    line = stream.readline(MAX_LINE + 1)
                    if not line:
                        break
                    consumed += len(line)
                    if len(line) > MAX_LINE or not line.endswith(b"\n") or (path.suffix != ".gz" and consumed > size):
                        raise ValueError("Truncated or oversized watcher journal record")
                    envelope = json.loads(line)
                    if (envelope.get("prev_hash") != previous
                            or envelope.get("hash") != record_hash(envelope)):
                        raise ValueError("Watcher journal hash integrity mismatch")
                    if anchor is None:
                        anchor = envelope["session_started_at"]
                    if envelope["session_started_at"] != anchor:
                        raise ValueError("Watcher session anchor changed")
                    if envelope.get("schema") == 1:
                        if envelope.get("seq") != seq + 1:
                            raise ValueError("Watcher journal sequence integrity mismatch")
                        seq = envelope["seq"]
                        yield envelope
                    elif envelope.get("schema") == 2:
                        rows = envelope.get("records")
                        if (not isinstance(rows, list) or not rows or envelope.get("batch_seq") != batch_seq + 1
                                or envelope.get("first_seq") != seq + 1
                                or envelope.get("last_seq") != seq + len(rows)):
                            raise ValueError("Watcher journal batch integrity mismatch")
                        batch_seq += 1
                        for row in rows:
                            if not isinstance(row, dict) or set(row) != {"kind", "at", "observed_at", "payload"}:
                                raise ValueError("Invalid watcher event shape")
                            seq += 1
                            yield {"schema": 1, "seq": seq, "session_started_at": anchor, **row,
                                   "hash": envelope["hash"], "prev_hash": envelope["prev_hash"],
                                   "source_batch_seq": batch_seq, "source_batch_last_seq": envelope["last_seq"]}
                    else:
                        raise ValueError("Unsupported watcher journal schema")
                    previous = envelope["hash"]
            finally:
                if stream is not raw:
                    stream.close()
                if pinned is None:
                    raw.close()
    finally:
        for _, _, stream in streams:
            if stream is not None:
                stream.close()


class ObservationJournal:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.seq, self.durable_seq, self.batch_seq = 0, 0, 0
        self.previous_hash = GENESIS
        self.pending: list[dict[str, Any]] = []
        self.pending_bytes = 0
        self.pending_day: str | None = None
        self.active: Path | None = None
        self.recovered_tail = False
        self.lock = (directory / "journal.lock").open("a", encoding="utf-8")
        self._repair_tail()
        self.storage_bytes = self._size()

    def _size(self) -> int:
        return sum(path.stat().st_size for path in self.directory.iterdir()
                   if path.is_file() and (PATTERN.fullmatch(path.name) or path.suffix == ".bin"))

    def _repair_tail(self) -> None:
        paths = source_paths(self.directory)
        if not paths or paths[-1].suffix == ".gz":
            return
        path = paths[-1]
        size = path.stat().st_size
        with path.open("rb") as stream:
            stream.seek(max(0, size - MAX_LINE))
            tail = stream.read()
        if not tail or tail.endswith(b"\n"):
            return
        boundary = tail.rfind(b"\n")
        if boundary < 0 and size > MAX_LINE:
            raise ValueError("Oversized watcher tail cannot be recovered safely")
        partial = tail[boundary + 1:]
        quarantine = self.directory / (path.name + ".partial.bin")
        with quarantine.open("xb") as stream:
            stream.write(partial)
            stream.flush()
            os.fsync(stream.fileno())
        with path.open("r+b") as stream:
            stream.truncate(size - len(partial))
            stream.flush()
            os.fsync(stream.fileno())
        self.recovered_tail = True

    def recover_record(self, record: dict[str, Any]) -> None:
        self.seq = self.durable_seq = int(record["seq"])
        self.previous_hash = str(record["hash"])
        self.batch_seq = int(record.get("source_batch_seq", self.batch_seq))

    def append(self, kind: str, payload: dict[str, Any], at: float, observed_at: float,
               anchor: float) -> None:
        day = datetime.fromtimestamp(observed_at, UTC).date().isoformat()
        if self.pending and day != self.pending_day:
            self.flush(anchor)
        if self.active is not None and not self.active.name.startswith(day):
            self.seal()
        self.pending_day = day
        event = {"kind": kind, "at": at, "observed_at": observed_at, "payload": payload}
        length = len(json.dumps(event, allow_nan=False, separators=(",", ":")))
        if length > 256 * 1024:
            raise ValueError("Watcher public event is oversized")
        self.pending.append(event)
        self.pending_bytes += length
        self.seq += 1
        if self.pending_bytes >= BATCH_BYTES:
            self.flush(anchor)

    def flush(self, anchor: float) -> None:
        if not self.pending:
            return
        envelope: dict[str, Any] = {"schema": 2, "batch_seq": self.batch_seq + 1,
                                    "first_seq": self.durable_seq + 1, "last_seq": self.seq,
                                    "session_started_at": anchor, "records": self.pending,
                                    "prev_hash": self.previous_hash}
        envelope["hash"] = record_hash(envelope)
        encoded = (json.dumps(envelope, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        if len(encoded) > MAX_LINE:
            raise ValueError("Watcher batch exceeded its bounded record size")
        if self.active is None:
            self.active = self.directory / f"{self.pending_day}-{self.durable_seq + 1:020d}.jsonl"
        fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX)
        try:
            with self.active.open("ab", buffering=0) as stream:
                view = memoryview(encoded)
                while view:
                    written = stream.write(view)
                    if written is None or written <= 0:
                        raise OSError("Watcher batch append did not finish")
                    view = view[written:]
                os.fsync(stream.fileno())
            self.storage_bytes += len(encoded)
            self.durable_seq = self.seq
            self.previous_hash = str(envelope["hash"])
            self.batch_seq += 1
            self.pending, self.pending_bytes = [], 0
        finally:
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_UN)
        if self.active.stat().st_size >= SEGMENT_BYTES:
            self.seal()

    def seal(self) -> None:
        if self.active is None:
            return
        source = self.active
        destination = source.with_suffix(".jsonl.gz")
        temporary = destination.with_suffix(".gz.tmp")
        with source.open("rb") as incoming, temporary.open("wb") as outgoing:
            with gzip.GzipFile(filename="", fileobj=outgoing, mode="wb", compresslevel=6, mtime=0) as compressed:
                shutil.copyfileobj(incoming, compressed)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        # Compare the uncompressed stream before publishing/removing anything.
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            while chunk := stream.read(128 * 1024):
                digest.update(chunk)
        check = hashlib.sha256()
        with gzip.open(temporary, "rb") as stream:
            while chunk := stream.read(128 * 1024):
                check.update(chunk)
        if check.digest() != digest.digest():
            raise ValueError("Watcher compression verification failed")
        fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX)
        try:
            os.replace(temporary, destination)
            directory_fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            source.unlink()
            self.active = None
            self.storage_bytes = self._size()
        finally:
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_UN)

    def close(self) -> None:
        self.lock.close()
