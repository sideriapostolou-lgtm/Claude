"""The forward tape (docs/LEARNING.md §3.1-3.5): append-only JSONL written BEFORE outcomes are known.

Layout: ``<root>/<YYYY-MM-DD>/<stream>.jsonl`` where the day is the UTC day a coin was FIRST SEEN
(:func:`tape_day`). Every row is one canonical JSON object per line with ``v`` (schema version),
``ts`` (when it was fetched or emitted), ``mint`` and, per source, ``src: {name: [fetched_ts, status]}``.
Source fields are stored RAW, so they can be re-featurized forever.

* :class:`TapeWriter` - appends (``fsync`` every :data:`FSYNC_EVERY_LINES` lines or
  :data:`FSYNC_EVERY_S` seconds), cuts a torn last line when it reopens a file (counted in
  ``torn_repaired``), hashes the byte ranges appended since the last root (:meth:`TapeWriter.segments`,
  :func:`segment_root`; the caller receipts them hourly through the outbox) and SEALS a finished day:
  ``X.jsonl.gz.tmp`` -> fsync -> rename -> ``MANIFEST.json`` (sha256 per file + root) -> [caller
  writes the ``tape_seal`` outbox row] -> :meth:`TapeWriter.finish_seal` deletes the ``.jsonl``.
  Every step is idempotent and deterministic (gzip with mtime 0), so a crash anywhere is finished
  by simply running the seal again.
* :class:`TapeReader` - reads ``X.jsonl`` while it exists, else ``X.jsonl.gz`` (never both), skips a
  torn last line or an undecodable line (counted in ``skipped``) and NEVER modifies the tape (the
  recorder may be appending while the learner reads).
* :class:`TapeView` - the learner's only window on one coin, as of a time ``t`` (visibility rules):
  a candle minute ``m`` is visible from ``m + 60 + L_obs``; a state row (``universe`` state, ``snaps``,
  ...) from its ``ts`` (fetch time); launch fields from ``created_ts``.

CANDLE FETCH ROWS (:func:`candle_fetch_row`): pump.fun returns the newest <= ``limit`` minutes THAT
HAD TRADES. A row stores only CLOSED minutes (``m + 60 <= fetched_ts``) not stored before, as
``[ts_s, open, high, low, close, volume]`` with the raw values, plus ``cover = [from, to)``: the minutes
this response determines (``from`` = its first minute when the ``limit`` was hit, else None = since
the start; ``to`` = the fetch's last closed minute boundary). A closed minute whose value differs
from what was stored before - or a trade in a minute already known to be empty - is a REVISION:
stored under ``revised`` and counted, never used (the FIRST value wins). Minutes inside the covered
range without a trade are flat zero-volume candles at the previous close; a gap between covers is
a HOLE and coverage (``TapeView.covered_until``) ends there.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

from nightcrawler.models import Candle

__all__ = [
    "SCHEMA_V",
    "STREAMS",
    "FSYNC_EVERY_LINES",
    "FSYNC_EVERY_S",
    "MANIFEST",
    "DEFAULT_L_OBS_S",
    "CANDLE_LIMIT",
    "TAIL_MINUTES",
    "TapeSealed",
    "tape_day",
    "canonical_line",
    "segment_root",
    "verify_segments",
    "candle_fetch_row",
    "candle_mark",
    "LAUNCH_FIELDS",
    "universe_row",
    "TapeWriter",
    "TapeReader",
    "TapeView",
]

SCHEMA_V = 1
STREAMS = ("universe", "candles", "snaps", "evals", "fills", "lag")
FSYNC_EVERY_LINES = 100
FSYNC_EVERY_S = 5.0
MANIFEST = "MANIFEST.json"
#: Observation lag until the ``lag`` stream has >= 500 samples (docs/LEARNING.md §3.2).
DEFAULT_L_OBS_S = 60.0
#: pump.fun's candle page size (``limit``); a response this long may be truncated.
CANDLE_LIMIT = 1000
#: Stored minutes kept per coin to detect revisions of recently closed minutes.
TAIL_MINUTES = 30
_MINUTE = 60


class TapeSealed(Exception):
    """The day's partition is sealed; nothing may be appended to it."""


def tape_day(ts: float) -> str:
    """UTC day ``YYYY-MM-DD`` of epoch seconds ``ts`` (the partition of a coin first seen at ``ts``)."""
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d")


def canonical_line(row: Mapping[str, Any]) -> bytes:
    """One tape line: canonical JSON (sorted keys, no spaces, ASCII) plus a newline. NaN/inf refused."""
    return (json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")


def segment_root(segments: Sequence[Mapping[str, Any]]) -> str:
    """sha256 over the canonical JSON of a segment (or manifest file) list: what a receipt commits to."""
    text = json.dumps(list(segments), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_bytes(root: Path, rel: str) -> bytes | None:
    path = root / rel
    if path.exists():
        return path.read_bytes()
    gz = path.with_name(path.name + ".gz")
    return gzip.decompress(gz.read_bytes()) if gz.exists() else None


def verify_segments(root: str | Path, segments: Iterable[Mapping[str, Any]]) -> bool:
    """True when every segment's byte range (of the ``.jsonl`` or, once sealed, its ``.gz``) still hashes
    to its ``sha256``."""
    root = Path(root)
    for seg in segments:
        data = _file_bytes(root, seg["file"])
        if data is None or len(data) < seg["end"]:
            return False
        if hashlib.sha256(data[seg["start"]:seg["end"]]).hexdigest() != seg["sha256"]:
            return False
    return True


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:  # pragma: no cover - platforms without directory fds
        return
    try:
        os.fsync(fd)
    except OSError:  # pragma: no cover
        pass
    finally:
        os.close(fd)


# --------------------------------------------------------------------------- universe rows

#: Census fields fixed at creation (pump.fun metadata is immutable at launch). Every other census field
#: is CURRENT STATE: kept in ``raw`` and visible only from the row's fetch time.
LAUNCH_FIELDS = ("name", "symbol", "creator", "program", "protocol", "token_program", "quote_mint", "base_decimals",
                 "quote_decimals", "nsfw", "is_cashback_enabled", "transfer_fee_bps", "bonding_curve",
                 "pump_swap_pool", "total_supply")


def universe_row(census_row: Mapping[str, Any], *, fetched_ts: float, offset: int, late: bool,
                 status: int = 200) -> dict[str, Any] | None:
    """The ``universe`` tape row of a coin's first sighting in the census (None if the row has no mint
    or creation time). ``launch`` adds ``mayhem`` (opted in at launch; its current state is outcome-only)
    and ``supply`` (whole tokens, for market caps)."""
    mint = census_row.get("mint")
    try:
        created = float(census_row["created_timestamp"]) / 1000.0
    except (KeyError, TypeError, ValueError):
        return None
    if not isinstance(mint, str) or not mint or not math.isfinite(created) or created <= 0:
        return None
    launch = {k: census_row.get(k) for k in LAUNCH_FIELDS}
    launch["mayhem"] = census_row.get("mayhem_state") is not None
    try:
        launch["supply"] = float(census_row["total_supply"]) / 10 ** int(census_row.get("base_decimals") or 6)
    except (KeyError, TypeError, ValueError):
        launch["supply"] = None
    return {"v": SCHEMA_V, "ts": float(fetched_ts), "mint": mint, "src": {"pumpfun": [float(fetched_ts), int(status)]},
            "created_ts": created, "first_seen_ts": float(fetched_ts), "late": bool(late), "offset": int(offset),
            "launch": launch, "raw": dict(census_row)}


# --------------------------------------------------------------------------- candle fetch rows


def _compact(row: Any) -> list[Any] | None:
    """API candle row -> ``[ts_s, open, high, low, close, volume]`` (raw values) or None if unusable."""
    if not isinstance(row, Mapping):
        return None
    try:
        ts = int(float(row["timestamp"])) // 1000
        values = [row["open"], row["high"], row["low"], row["close"]]
        if any(not math.isfinite(float(v)) or float(v) <= 0 for v in values):
            return None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    volume = row.get("volume")
    try:
        usable = volume is not None and math.isfinite(float(volume)) and float(volume) >= 0
    except (TypeError, ValueError, OverflowError):
        usable = False
    return [ts, *values, volume if usable else "0"]


def candle_fetch_row(mint: str, api_rows: Sequence[Any], *, fetched_ts: float, previous: Mapping[str, Any] | None,
                     status: int = 200, limit: int = CANDLE_LIMIT, fetch_no: int | None = None) -> dict[str, Any]:
    """The ``candles`` tape row for one pump.fun response (see the module docstring).

    ``previous`` is the coin's :func:`candle_mark` (or its previous fetch row), None for the first fetch.
    """
    closed = sorted({c[0]: c for c in map(_compact, api_rows) if c is not None and c[0] + _MINUTE <= fetched_ts}
                    .values())
    to = int(fetched_ts // _MINUTE) * _MINUTE
    truncated = len(api_rows) >= limit  # the newest ``limit`` traded minutes: older ones may be missing
    cover_from = (closed[0][0] if closed else to) if truncated else None
    prev_to = previous["cover"][1] if previous else None
    tail = {r[0]: r for r in (previous or {}).get("rows", [])}
    tail_from = (previous or {}).get("tail_from", (previous or {}).get("cover", [None])[0])
    new, revised = [], []
    for c in closed:
        if prev_to is None or c[0] >= prev_to:
            new.append(c)
        elif (tail_from is None or c[0] >= tail_from) and tail.get(c[0]) != c:
            revised.append(c)  # changed value, or a trade in a minute that was known to be empty
    return {"v": SCHEMA_V, "ts": float(fetched_ts), "mint": mint, "src": {"pumpfun": [float(fetched_ts), int(status)]},
            "fetch": fetch_no, "n": len(api_rows), "limit": int(limit), "cover": [cover_from, to], "rows": new,
            "revised": revised}


def candle_mark(row: Mapping[str, Any], previous: Mapping[str, Any] | None) -> dict[str, Any]:
    """What the recorder remembers per coin between fetches: the coverage end and the last
    :data:`TAIL_MINUTES` stored minutes (``tail_from``: from where that tail is complete)."""
    rows = [*(previous or {}).get("rows", []), *row["rows"]]
    tail_from = (previous or {}).get("tail_from", (previous or {}).get("cover", [row["cover"][0]])[0])
    if row["cover"][0] is not None and (previous is None or row["cover"][0] > previous["cover"][1]):
        rows, tail_from = list(row["rows"]), row["cover"][0]  # a hole: nothing before it is known
    if len(rows) > TAIL_MINUTES:
        rows = rows[-TAIL_MINUTES:]
        tail_from = rows[0][0]
    to = max(row["cover"][1], previous["cover"][1]) if previous else row["cover"][1]
    return {"cover": [None, to], "rows": rows, "tail_from": tail_from,
            "fetches": int((previous or {}).get("fetches", 0)) + 1}


# --------------------------------------------------------------------------- writer


class _Open:
    __slots__ = ("fh", "lines", "synced_at")

    def __init__(self, fh: BinaryIO, now: float) -> None:
        self.fh = fh
        self.lines = 0
        self.synced_at = now


class TapeWriter:
    """Appends tape rows; see the module docstring. Thread-safe; one writer per process."""

    def __init__(self, root: str | Path, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        self.root = Path(root)
        self.monotonic = monotonic
        self.torn_repaired = 0
        self._files: dict[Path, _Open] = {}
        self._lock = threading.RLock()

    def __enter__(self) -> "TapeWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _step(self, name: str) -> None:
        """Called after each sealing step (tests inject crashes here)."""

    def _path(self, stream: str, day: str) -> Path:
        if stream not in STREAMS or "/" in day or ".." in day:
            raise ValueError(f"bad tape partition {day}/{stream}")
        return self.root / day / f"{stream}.jsonl"

    def sealed(self, day: str) -> bool:
        return (self.root / day / MANIFEST).exists()

    def append(self, stream: str, day: str, row: Mapping[str, Any]) -> None:
        """Append one row to ``<day>/<stream>.jsonl`` (raises :class:`TapeSealed` for a sealed day)."""
        line = canonical_line(row)
        with self._lock:
            path = self._path(stream, day)
            handle = self._files.get(path)
            if handle is None:
                if self.sealed(day):
                    raise TapeSealed(day)
                handle = self._files[path] = _Open(self._open(path), self.monotonic())
            handle.fh.write(line)
            handle.fh.flush()
            handle.lines += 1
            now = self.monotonic()
            if handle.lines >= FSYNC_EVERY_LINES or now - handle.synced_at >= FSYNC_EVERY_S:
                self._sync(handle, now)

    def _open(self, path: Path) -> BinaryIO:
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(path, "a+b")  # noqa: SIM115 - kept open for appends
        size = fh.seek(0, os.SEEK_END)
        if size:
            fh.seek(max(0, size - 65536))
            tail = fh.read()
            if not tail.endswith(b"\n"):
                cut = tail.rfind(b"\n")
                keep = size - len(tail) + cut + 1 if cut >= 0 else (0 if size <= 65536 else self._last_newline(fh))
                fh.truncate(keep)
                fh.flush()
                os.fsync(fh.fileno())
                self.torn_repaired += 1
            fh.seek(0, os.SEEK_END)
        return fh

    @staticmethod
    def _last_newline(fh: BinaryIO) -> int:
        """Position after the last newline of a file whose last 64 KiB hold none (very long torn line)."""
        fh.seek(0)
        data = fh.read()
        return data.rfind(b"\n") + 1

    def _sync(self, handle: _Open, now: float) -> None:
        os.fsync(handle.fh.fileno())
        handle.lines, handle.synced_at = 0, now

    def flush(self) -> None:
        """fsync every open file now."""
        with self._lock:
            now = self.monotonic()
            for handle in self._files.values():
                handle.fh.flush()
                self._sync(handle, now)

    def close(self) -> None:
        with self._lock:
            for handle in self._files.values():
                handle.fh.flush()
                os.fsync(handle.fh.fileno())
                handle.fh.close()
            self._files.clear()

    def _close_day(self, day: str) -> None:
        with self._lock:
            for path in [p for p in self._files if p.parent.name == day]:
                handle = self._files.pop(path)
                handle.fh.flush()
                os.fsync(handle.fh.fileno())
                handle.fh.close()

    # ---------------------------------------------------------------- hourly roots
    def segments(self, offsets: Mapping[str, int]) -> list[dict[str, Any]]:
        """Byte ranges of every UNSEALED ``.jsonl`` appended since ``offsets`` (``{"DAY/stream.jsonl": end}``),
        each ``{file, start, end, sha256}`` and ending on a newline. The caller receipts
        :func:`segment_root` of them and stores the new ends in the same transaction."""
        self.flush()
        out = []
        for path in sorted(self.root.glob("*/*.jsonl")):
            rel = f"{path.parent.name}/{path.name}"
            start = int(offsets.get(rel, 0))
            with path.open("rb") as fh:
                fh.seek(start)
                data = fh.read()
            end = start + data.rfind(b"\n") + 1
            if end > start:
                out.append({"file": rel, "start": start, "end": end,
                            "sha256": hashlib.sha256(data[:end - start]).hexdigest()})
        return out

    # ---------------------------------------------------------------- sealing
    def seal(self, day: str) -> dict[str, Any]:
        """Steps 1-2 of sealing ``day`` (idempotent): every ``X.jsonl`` -> ``X.jsonl.gz`` (tmp, fsync,
        rename), then ``MANIFEST.json``. Returns the manifest; the caller writes the ``tape_seal``
        outbox row, then calls :meth:`finish_seal`."""
        self._close_day(day)
        folder = self.root / day
        for path in sorted(folder.glob("*.jsonl")):
            data = path.read_bytes()
            data = data[:data.rfind(b"\n") + 1]  # a torn last line is never sealed
            tmp = path.with_name(path.name + ".gz.tmp")
            with tmp.open("wb") as fh:
                with gzip.GzipFile(filename="", mode="wb", fileobj=fh, mtime=0) as gz:
                    gz.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            self._step("gz_tmp_written")
            os.replace(tmp, path.with_name(path.name + ".gz"))
            _fsync_dir(folder)
            self._step("gz_renamed")
        files = []
        for gz_path in sorted(folder.glob("*.jsonl.gz")):
            gz_bytes = gz_path.read_bytes()
            raw = gzip.decompress(gz_bytes)
            files.append({"file": gz_path.name[:-3], "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                          "gz_sha256": hashlib.sha256(gz_bytes).hexdigest()})
        manifest = {"v": SCHEMA_V, "day": day, "files": files, "root": segment_root(files)}
        tmp = folder / (MANIFEST + ".tmp")
        tmp.write_bytes(canonical_line(manifest))
        with tmp.open("rb") as fh:
            os.fsync(fh.fileno())
        self._step("manifest_tmp_written")
        os.replace(tmp, folder / MANIFEST)
        _fsync_dir(folder)
        self._step("manifest_written")
        return manifest

    def raw_left(self, day: str) -> bool:
        """True when a SEALED day still has a ``.jsonl`` next to its ``.gz`` (:meth:`finish_seal` did not run)."""
        folder = self.root / day
        return self.sealed(day) and any(p.with_name(p.name + ".gz").exists() for p in folder.glob("*.jsonl"))

    def finish_seal(self, day: str) -> None:
        """Last sealing step: delete the ``.jsonl`` (and stray ``.tmp``) files once their ``.gz`` and the
        manifest exist. Safe to repeat."""
        folder = self.root / day
        if not (folder / MANIFEST).exists():
            raise TapeSealed(f"{day} has no manifest yet")
        for path in sorted(folder.glob("*.jsonl")):
            if path.with_name(path.name + ".gz").exists():
                path.unlink()
                self._step("jsonl_deleted")
        for tmp in folder.glob("*.tmp"):
            tmp.unlink()
        _fsync_dir(folder)


# --------------------------------------------------------------------------- reader


class TapeReader:
    """Read-only access to the tape (see the module docstring)."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        #: torn or undecodable lines skipped so far
        self.skipped = 0

    def days(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and len(p.name) == 10)

    def sealed(self, day: str) -> bool:
        return (self.root / day / MANIFEST).exists()

    def manifest(self, day: str) -> dict[str, Any] | None:
        path = self.root / day / MANIFEST
        return json.loads(path.read_text(encoding="ascii")) if path.exists() else None

    def rows(self, day: str, stream: str) -> list[dict[str, Any]]:
        data = _file_bytes(self.root / day, f"{stream}.jsonl")
        if not data:
            return []
        lines = data.split(b"\n")
        if lines[-1]:
            self.skipped += 1  # torn last line (a writer died mid-line, or is writing right now)
        out = []
        for line in lines[:-1]:
            try:
                out.append(json.loads(line))
            except ValueError:
                self.skipped += 1
        return out

    def coins(self, day: str, streams: Iterable[str] = ("universe", "candles", "snaps")) -> dict[str, dict[str, list]]:
        """``{mint: {stream: [rows in file order]}}`` for one day (each stream file read once)."""
        streams = tuple(streams)
        grouped: dict[str, dict[str, list]] = defaultdict(lambda: {s: [] for s in streams})
        for stream in streams:
            for row in self.rows(day, stream):
                mint = row.get("mint")
                if isinstance(mint, str):
                    grouped[mint][stream].append(row)
        return dict(grouped)


# --------------------------------------------------------------------------- view


class TapeView:
    """One coin's tape as of ``as_of`` (visibility rules in the module docstring). Pure and read-only."""

    def __init__(self, mint: str, as_of: float, rows: Mapping[str, Sequence[Mapping[str, Any]]],
                 l_obs: float = DEFAULT_L_OBS_S) -> None:
        self.mint = mint
        self.as_of = float(as_of)
        self.l_obs = float(l_obs)
        self._rows = rows
        universe = sorted(rows.get("universe", ()), key=lambda r: r.get("ts", 0.0))
        self._universe = universe[0] if universe else None
        self.revisions = 0
        #: end (exclusive minute boundary) of the coverage that is contiguous from the first fetch
        self.covered_until: int | None = None
        #: False when the first fetch was truncated (the coin's early history is unknown)
        self.complete_from_start = True
        self._values = self._determine(rows.get("candles", ()))

    # ---------------------------------------------------------------- launch / state
    @property
    def first_seen_ts(self) -> float | None:
        """When the recorder first saw the coin in the GRADUATED census: from then on it is known to have
        graduated (it graduated at or before this time)."""
        u = self._universe
        return float(u.get("first_seen_ts", u["ts"])) if u else None

    @property
    def created_ts(self) -> float | None:
        u = self._universe
        return float(u["created_ts"]) if u and u.get("created_ts") is not None else None

    @property
    def launch(self) -> dict[str, Any] | None:
        """Immutable launch fields, visible from ``created_ts``."""
        created = self.created_ts
        if self._universe is None or created is None or created > self.as_of:
            return None
        return dict(self._universe.get("launch") or {})

    def state(self, stream: str) -> list[dict[str, Any]]:
        """Rows of a state stream fetched at or before ``as_of``."""
        return [dict(r) for r in self._rows.get(stream, ()) if float(r.get("ts", math.inf)) <= self.as_of]

    # ---------------------------------------------------------------- candles
    def _determine(self, fetches: Iterable[Mapping[str, Any]]) -> dict[int, list[Any]]:
        values: dict[int, list[Any]] = {}
        to: int | None = None
        for f in sorted(fetches, key=lambda r: float(r.get("ts", 0.0))):
            cover_from, cover_to = f["cover"]
            self.revisions += len(f.get("revised") or ())
            if to is None:
                self.complete_from_start = cover_from is None
            elif cover_from is not None and cover_from > to:
                break  # a hole: coverage ends at ``to``
            for r in f.get("rows") or ():
                if r[0] < cover_to and r[0] not in values and (to is None or r[0] >= to):
                    values[r[0]] = r
            to = cover_to if to is None else max(to, cover_to)
        self.covered_until = to
        return values

    def candles(self) -> list[Candle]:
        """Visible 1m candles, ascending: traded minutes (first value), flat zero-volume minutes in between
        and after the last trade up to the coverage end; nothing after a hole."""
        if self.covered_until is None or not self._values:
            return []
        last_visible = math.floor((self.as_of - _MINUTE - self.l_obs) / _MINUTE) * _MINUTE
        end = min(last_visible, self.covered_until - _MINUTE)
        out: list[Candle] = []
        prev: Candle | None = None
        for ts in range(min(self._values), int(end) + 1, _MINUTE):
            raw = self._values.get(ts)
            if raw is not None:
                prev = Candle(ts, float(raw[1]), float(raw[2]), float(raw[3]), float(raw[4]), float(raw[5] or 0.0))
            elif prev is not None:
                prev = Candle(ts, prev.c, prev.c, prev.c, prev.c, 0.0)
            if prev is not None:
                out.append(prev)
        return out
