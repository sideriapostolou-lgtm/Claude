"""SQLite ledger + hash-chained receipts (owner: O6). Single source of truth.

Storage: one SQLite file (``settings.db_path`` = ``DATA_DIR/nightcrawler.db``),
WAL mode, ``check_same_thread=False`` guarded by one ``threading.RLock`` (the
engine writes from its thread; the dashboard reads from HTTP threads). Every
read and write holds the lock, so a reader never sees another thread's
uncommitted transaction. Writes use ``BEGIN IMMEDIATE`` plus a busy timeout,
so a second process on the same file (the CLI, a dashboard-only process)
queues behind the writer instead of forking the chain.

Tables (columns are a suggestion; the public methods are the contract):

* ``kv(key TEXT PRIMARY KEY, value TEXT JSON, updated_at REAL)``
* ``candidates(mint PK, data JSON, first_seen REAL, last_seen REAL)``
* ``safety(mint, checked_at, passed INT, reasons JSON, data JSON)``
* ``decisions(id INTEGER PK, ts, mint, action, reason, data JSON, receipt_seq)``
* ``fills(id TEXT PK, ts, mode, side, mint, position_id, data JSON, receipt_seq)``
* ``positions(id TEXT PK, mint, status, opened_at, closed_at, data JSON, wallet TEXT)`` -
  ``wallet``: pubkey of the wallet holding a LIVE position's tokens (NULL for paper; a nullable
  column added to older ledgers on open - their live rows default to kv ``wallet.pubkey``, the last
  live boot's wallet - without a schema version bump, so older builds still open the ledger).
  Written with :meth:`Ledger.set_position_wallet`, read with :meth:`Ledger.position_wallets`.
* ``equity(ts REAL, equity_lamports INT, sol_usd REAL, equity_usd REAL, mode, data JSON)``
* ``receipts(seq INTEGER PK, ts REAL, kind TEXT, payload TEXT canonical JSON,
  prev_hash TEXT, hash TEXT UNIQUE)``

RECEIPTS (hindsight-proof): :meth:`Ledger.append_receipt` computes
``hash = sha256(prev_hash + canonical_json({seq, ts, kind, payload}))`` with
``nightcrawler.hashing`` (payload normalized first; ``ts`` rounded to ms),
inside the same transaction that reads the previous head, so the chain can
never fork. The engine appends a receipt for every Decision and every Fill
IMMEDIATELY - before any later price is fetched. ``record_decision`` and
``record_fill`` write the row and its receipt atomically (receipt ``ts`` =
the record's own ``ts``; ``receipt_hash`` is ``None`` inside the payload).

Well-known kv keys (JSON values): ``paper.sol_lamports``, ``paper.tokens``,
``paper.rent``, ``paper.start_lamports``, ``paper.start_sol_usd``,
``live.start_lamports``, ``risk.halted``, ``risk.peak_reset_ts``,
``engine.heartbeat``, ``engine.started_at``, ``engine.status`` (dict),
``engine.kill_mode``, ``engine.last_error``, ``judge.cost_usd_total``,
``judge.cost_usd_day``, ``judge.calls``, ``wallet.pubkey``, ``engine.watchlist``,
``engine.cocoon_queue`` and ``crawler.nursery`` (``{saved_at, items}``, resumed after a
redeploy), ``engine.safe_mode``
(banner, None outside safe mode), ``engine.foreign_positions`` (live positions of another wallet).

Helpers beyond the core contract (used by the auditor and the dashboard):
:meth:`Ledger.last_receipt`, :meth:`Ledger.fills_after_seq`,
:meth:`Ledger.equity_curve`, :meth:`Ledger.safety_failures`,
:meth:`Ledger.candidate_count`, :meth:`Ledger.latest_safety` (engine).
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import sqlite3
import threading
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from nightcrawler.clock import RealClock
from nightcrawler.hashing import (
    GENESIS_HASH,
    canonical_json,
    normalize_payload,
    receipt_hash,
    verify_receipts,
)
from nightcrawler.models import (
    Decision,
    EquityPoint,
    Fill,
    Position,
    Receipt,
    SafetyReport,
    TokenCandidate,
    to_jsonable,
)

__all__ = ["BUSY_TIMEOUT_S", "SCHEMA_VERSION", "Ledger", "LedgerError"]

#: ``PRAGMA user_version`` of the layout below; bump it (with a migration) only for a change OLDER builds
#: cannot read - every build refuses a newer version, so a bump breaks a rollback to an earlier image.
#: A backward-compatible addition keeps it and is detected instead: ``positions.wallet`` (the wallet a
#: LIVE position's tokens are in, NULL for paper) is a nullable column v1 builds read and write unharmed.
SCHEMA_VERSION = 1
#: Written by the builds that briefly bumped the version for ``positions.wallet``: v1 plus that column.
#: Opened as v1 and marked v1 again, so earlier images open the ledger too.
_V1_WITH_WALLET = 2
#: How long a write waits for another process holding the write lock.
BUSY_TIMEOUT_S = 10.0

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS kv (
        key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS candidates (
        mint TEXT PRIMARY KEY, data TEXT NOT NULL, first_seen REAL NOT NULL, last_seen REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS safety (
        id INTEGER PRIMARY KEY, mint TEXT NOT NULL, checked_at REAL NOT NULL, passed INTEGER NOT NULL,
        reasons TEXT NOT NULL, data TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS safety_checked_at ON safety(checked_at)",
    "CREATE INDEX IF NOT EXISTS safety_mint ON safety(mint, checked_at)",
    """CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY, ts REAL NOT NULL, mint TEXT NOT NULL, action TEXT NOT NULL,
        reason TEXT NOT NULL, data TEXT NOT NULL, receipt_seq INTEGER NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS decisions_ts ON decisions(ts)",
    """CREATE TABLE IF NOT EXISTS fills (
        id TEXT PRIMARY KEY, ts REAL NOT NULL, mode TEXT NOT NULL, side TEXT NOT NULL, mint TEXT NOT NULL,
        position_id TEXT, data TEXT NOT NULL, receipt_seq INTEGER NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS fills_ts ON fills(ts)",
    "CREATE INDEX IF NOT EXISTS fills_mint ON fills(mint)",
    "CREATE INDEX IF NOT EXISTS fills_position ON fills(position_id)",
    "CREATE INDEX IF NOT EXISTS fills_receipt_seq ON fills(receipt_seq)",
    """CREATE TABLE IF NOT EXISTS positions (
        id TEXT PRIMARY KEY, mint TEXT NOT NULL, status TEXT NOT NULL, opened_at REAL NOT NULL,
        closed_at REAL, data TEXT NOT NULL, wallet TEXT)""",
    "CREATE INDEX IF NOT EXISTS positions_status ON positions(status, opened_at)",
    "CREATE INDEX IF NOT EXISTS positions_mint ON positions(mint, closed_at)",
    """CREATE TABLE IF NOT EXISTS equity (
        id INTEGER PRIMARY KEY, ts REAL NOT NULL, equity_lamports INTEGER NOT NULL, sol_usd REAL NOT NULL,
        equity_usd REAL NOT NULL, mode TEXT NOT NULL, data TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS equity_ts ON equity(ts)",
    """CREATE TABLE IF NOT EXISTS receipts (
        seq INTEGER PRIMARY KEY, ts REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
        prev_hash TEXT NOT NULL, hash TEXT NOT NULL UNIQUE)""",
    "CREATE INDEX IF NOT EXISTS receipts_kind ON receipts(kind, seq)",
)

_RECEIPT_COLUMNS = "seq, ts, kind, payload, prev_hash, hash"


class LedgerError(Exception):
    """Storage failure or a broken invariant (e.g. a receipt write that would fork the chain)."""


def _dumps(value: Any) -> str:
    """Compact JSON for row data and kv values (dataclasses converted first)."""
    return json.dumps(to_jsonable(value), separators=(",", ":"), default=str)


def _receipt_from_row(row: Sequence[Any]) -> Receipt:
    seq, ts, kind, payload, prev_hash, digest = row
    return Receipt(seq=seq, ts=ts, kind=kind, payload=json.loads(payload), prev_hash=prev_hash, hash=digest)


def _limit_clause(limit: int | None) -> tuple[str, list[Any]]:
    return ("", []) if limit is None else (" LIMIT ?", [int(limit)])


class Ledger:
    """Thread-safe SQLite ledger. Use as a context manager or call :meth:`close`."""

    def __init__(self, path: str | os.PathLike[str], clock: Any | None = None) -> None:
        """Open/create the database at ``path`` (parent dirs created), enable WAL, create tables.

        ``path=":memory:"`` is allowed (tests). ``clock`` (default RealClock)
        supplies receipt/kv timestamps when none is passed explicitly.
        """
        self.clock = clock if clock is not None else RealClock()
        self.path = str(path)
        self._lock = threading.RLock()
        self._depth = 0
        self._conn: sqlite3.Connection | None = None
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_S, check_same_thread=False,
                                         isolation_level=None)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._migrate()
        except (sqlite3.Error, LedgerError) as exc:
            self.close()
            raise LedgerError(f"cannot open ledger {self.path}: {exc}{self._permission_hint()}") from exc

    def _permission_hint(self) -> str:
        """Explain the usual cause on Railway: a root-owned volume and a non-root process."""
        folder = Path(self.path).parent
        if self.path == ":memory:" or os.access(folder, os.W_OK):
            return ""
        return (f" (this user cannot write to {folder}; on Railway set the service variable "
                "RAILWAY_RUN_UID=0, locally fix the folder's owner)")

    def _migrate(self) -> None:
        with self.transaction(), self._locked() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION and version != _V1_WITH_WALLET:
                raise LedgerError(f"ledger schema v{version} is newer than this nightcrawler (v{SCHEMA_VERSION})")
            for statement in _SCHEMA:
                conn.execute(statement)
            self._migrate_position_wallets(conn)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def _migrate_position_wallets(self, conn: sqlite3.Connection) -> None:
        """A ledger without ``positions.wallet`` (written before it existed) gets the column; its LIVE
        rows default to kv ``wallet.pubkey`` (the wallet of the last live boot, which opened them), else
        stay NULL (unknown). Nothing to do when the column exists."""
        columns = {row[1] for row in conn.execute("PRAGMA table_info(positions)")}
        if "wallet" in columns:
            return
        conn.execute("ALTER TABLE positions ADD COLUMN wallet TEXT")
        row = conn.execute("SELECT value FROM kv WHERE key = 'wallet.pubkey'").fetchone()
        pubkey = json.loads(row[0]) if row is not None else None
        if not isinstance(pubkey, str) or not pubkey:
            return
        rows = conn.execute("SELECT data FROM positions WHERE wallet IS NULL").fetchall()
        live = [p.id for p in self._load_positions(rows) if p.mode == "live"]
        conn.executemany("UPDATE positions SET wallet = ? WHERE id = ?", [(pubkey, pid) for pid in live])

    def close(self) -> None:
        """Close the connection (idempotent). Later calls raise :class:`LedgerError`."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> Ledger:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ plumbing
    @contextlib.contextmanager
    def _locked(self) -> Iterator[sqlite3.Connection]:
        """Hold the lock and translate sqlite errors into :class:`LedgerError`."""
        with self._lock:
            if self._conn is None:
                raise LedgerError("ledger is closed")
            try:
                yield self._conn
            except sqlite3.Error as exc:
                raise LedgerError(f"sqlite error: {exc}") from exc

    def _rows(self, sql: str, params: Sequence[Any] = ()) -> list[Any]:
        with self._locked() as conn:
            return conn.execute(sql, params).fetchall()

    def _write(self, sql: str, params: Sequence[Any] = ()) -> None:
        with self.transaction(), self._locked() as conn:
            conn.execute(sql, params)

    def _now(self) -> float:
        return float(self.clock.now())

    # ------------------------------------------------------------------ kv
    def get_kv(self, key: str, default: Any = None) -> Any:
        """JSON-decoded value or ``default``."""
        rows = self._rows("SELECT value FROM kv WHERE key = ?", (key,))
        return json.loads(rows[0][0]) if rows else default

    def set_kv(self, key: str, value: Any) -> None:
        """Store a JSON-serializable value (upsert)."""
        self._write("INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                    (key, _dumps(value), self._now()))

    @contextlib.contextmanager
    def transaction(self) -> Iterator[Ledger]:
        """Context manager: one atomic SQLite transaction holding the lock (re-entrant).

        Used e.g. by PaperBroker to update balances and record a fill atomically.
        Nested blocks are SAVEPOINTs: an exception rolls back that block (and,
        if it propagates, everything up to the outermost block).
        """
        with self._lock:
            begin, commit, rollback = self._tx_statements(self._depth)
            with self._locked() as conn:
                conn.execute(begin)
            self._depth += 1
            try:
                yield self
            except BaseException:
                self._depth -= 1
                self._run_quietly(rollback)
                raise
            self._depth -= 1
            try:
                with self._locked() as conn:
                    conn.execute(commit)
            except LedgerError:
                self._run_quietly(rollback)
                raise

    @staticmethod
    def _tx_statements(depth: int) -> tuple[str, str, tuple[str, ...]]:
        """``(begin, commit, rollback)`` SQL: a real transaction at depth 0, else a savepoint."""
        if depth == 0:
            return "BEGIN IMMEDIATE", "COMMIT", ("ROLLBACK",)
        name = f"nc_{depth}"
        return f"SAVEPOINT {name}", f"RELEASE {name}", (f"ROLLBACK TO {name}", f"RELEASE {name}")

    def _run_quietly(self, statements: Sequence[str]) -> None:
        """Best-effort rollback: the original error matters more than a failed cleanup."""
        with self._lock, contextlib.suppress(sqlite3.Error):
            if self._conn is not None:
                for statement in statements:
                    self._conn.execute(statement)

    # ------------------------------------------------------------------ receipts
    def append_receipt(self, kind: str, payload: dict[str, Any], ts: float | None = None) -> Receipt:
        """Append one receipt (see module docstring). ``kind`` in ``models.ReceiptKind``.

        Raises ``ValueError`` for NaN/inf in the payload and :class:`LedgerError` on storage failure.
        """
        normalized = normalize_payload(payload)
        stamp = round(float(self._now() if ts is None else ts), 3)
        with self.transaction(), self._locked() as conn:
            seq, prev = self._head(conn)
            seq += 1
            digest = receipt_hash(prev, seq, stamp, kind, normalized)
            conn.execute(f"INSERT INTO receipts({_RECEIPT_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
                         (seq, stamp, kind, canonical_json(normalized), prev, digest))
        return Receipt(seq=seq, ts=stamp, kind=kind, payload=normalized, prev_hash=prev, hash=digest)

    @staticmethod
    def _head(conn: sqlite3.Connection) -> tuple[int, str]:
        row = conn.execute("SELECT seq, hash FROM receipts ORDER BY seq DESC LIMIT 1").fetchone()
        return (0, GENESIS_HASH) if row is None else (row[0], row[1])

    def head(self) -> tuple[int, str]:
        """``(last_seq, last_hash)``; ``(0, GENESIS_HASH)`` for an empty chain."""
        with self._locked() as conn:
            return self._head(conn)

    def receipt_count(self) -> int:
        return self._rows("SELECT COUNT(*) FROM receipts")[0][0]

    def receipts(self, after_seq: int = 0, limit: int | None = None) -> list[Receipt]:
        """Receipts with ``seq > after_seq`` in ascending order."""
        clause, extra = _limit_clause(limit)
        rows = self._rows(f"SELECT {_RECEIPT_COLUMNS} FROM receipts WHERE seq > ? ORDER BY seq{clause}",
                          [after_seq, *extra])
        return [_receipt_from_row(r) for r in rows]

    def iter_receipts(self, batch: int = 1000) -> Iterator[Receipt]:
        """All receipts ascending, streamed in batches (for verify/export of long chains).

        The lock is released between batches, so a long walk never stalls the
        engine; receipts appended meanwhile are simply included (append-only).
        """
        after = 0
        while True:
            chunk = self.receipts(after_seq=after, limit=batch)
            yield from chunk
            if len(chunk) < batch:
                return
            after = chunk[-1].seq

    def last_receipt(self, kind: str, where: Mapping[str, Any] | None = None) -> Receipt | None:
        """Newest receipt of ``kind`` whose payload contains every ``where`` item (e.g. a
        ``note`` with ``{"event": "paper_reset"}``), or None. Meant for rare kinds."""
        with self._locked() as conn:
            cursor = conn.execute(f"SELECT {_RECEIPT_COLUMNS} FROM receipts WHERE kind = ? ORDER BY seq DESC",
                                  (kind,))
            for row in cursor:
                receipt = _receipt_from_row(row)
                if all(receipt.payload.get(k) == v for k, v in (where or {}).items()):
                    return receipt
        return None

    def verify_chain(self) -> tuple[bool, int | None]:
        """Re-walk the whole chain with ``hashing.verify_receipts`` -> ``(ok, first_bad_seq)``."""
        return verify_receipts(self.iter_receipts())

    def export_receipts(self, path: str | os.PathLike[str]) -> int:
        """Write all receipts as JSONL (one ``Receipt.to_dict()`` per line, ascending); return count.

        Each line also carries ``body``: the EXACT text that was hashed
        (``canonical_json({seq, ts, kind, payload})``), so a verifier in any language checks
        ``sha256(prev_hash + body) == hash`` without re-encoding JSON (other encoders write
        ``100.0`` as ``100``, ``1e-05`` as ``0.00001``, escape unicode differently and lose
        integers above 2**53). Parse ``body`` only to display it.
        Written to a temporary file first and renamed, so a reader never sees half a file.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        count = 0
        try:
            with tmp.open("w", encoding="utf-8", newline="\n") as fh:
                for receipt in self.iter_receipts():
                    body = canonical_json({"seq": receipt.seq, "ts": receipt.ts, "kind": receipt.kind,
                                           "payload": receipt.payload})
                    fh.write(canonical_json({**receipt.to_dict(), "body": body}) + "\n")
                    count += 1
            os.replace(tmp, target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return count

    # ------------------------------------------------------------------ records
    def record_candidate(self, candidate: TokenCandidate) -> None:
        """Upsert by mint (keeps ``first_seen``). No receipt (too noisy)."""
        now = self._now()
        first_seen = candidate.discovered_at if candidate.discovered_at is not None else now
        self._write("INSERT INTO candidates(mint, data, first_seen, last_seen) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(mint) DO UPDATE SET data = excluded.data, last_seen = excluded.last_seen",
                    (candidate.mint, _dumps(candidate), first_seen, now))

    def candidate_count(self, since: float | None = None) -> int:
        """Distinct mints first seen at/after ``since`` (all when None)."""
        return self._rows("SELECT COUNT(*) FROM candidates WHERE first_seen >= ?",
                          (float("-inf") if since is None else since,))[0][0]

    def record_safety(self, report: SafetyReport) -> None:
        """Append a safety report row. No receipt (the decision that uses it is receipted)."""
        checked_at = report.checked_at or self._now()
        self._write("INSERT INTO safety(mint, checked_at, passed, reasons, data) VALUES (?, ?, ?, ?, ?)",
                    (report.mint, checked_at, int(report.passed), _dumps(report.hard_fail_reasons), _dumps(report)))

    def safety_failures(self, since: float | None = None) -> dict[str, list[str]]:
        """``{mint: hard_fail_reasons}`` for mints whose LATEST report since ``since`` failed."""
        rows = self._rows("SELECT mint, passed, reasons FROM safety WHERE checked_at >= ? ORDER BY checked_at, id",
                          (float("-inf") if since is None else since,))
        latest = {mint: (passed, reasons) for mint, passed, reasons in rows}
        return {mint: json.loads(reasons) for mint, (passed, reasons) in latest.items() if not passed}

    def latest_safety(self, mint: str) -> SafetyReport | None:
        """The newest stored :class:`SafetyReport` for ``mint`` (engine restarts reuse its wallets)."""
        rows = self._rows("SELECT data FROM safety WHERE mint = ? ORDER BY checked_at DESC, id DESC LIMIT 1", (mint,))
        return SafetyReport.from_dict(json.loads(rows[0][0])) if rows else None

    def record_decision(self, decision: Decision) -> Decision:
        """Insert + ``decision`` receipt atomically; returns a copy with ``receipt_hash`` set."""
        payload = {**decision.to_dict(), "receipt_hash": None}
        with self.transaction(), self._locked() as conn:
            receipt = self.append_receipt("decision", payload, ts=decision.ts)
            stored = dataclasses.replace(decision, receipt_hash=receipt.hash)
            conn.execute("INSERT INTO decisions(ts, mint, action, reason, data, receipt_seq) VALUES (?, ?, ?, ?, ?, ?)",
                         (decision.ts, decision.mint, decision.action, decision.reason, _dumps(stored), receipt.seq))
        return stored

    def record_fill(self, fill: Fill) -> Fill:
        """Insert + ``fill`` receipt atomically; returns a copy with ``receipt_hash`` set.

        Raises :class:`LedgerError` if ``fill.id`` already exists.
        """
        payload = {**fill.to_dict(), "receipt_hash": None}
        with self.transaction(), self._locked() as conn:
            if conn.execute("SELECT 1 FROM fills WHERE id = ?", (fill.id,)).fetchone():
                raise LedgerError(f"duplicate fill id {fill.id}")
            receipt = self.append_receipt("fill", payload, ts=fill.ts)
            stored = dataclasses.replace(fill, receipt_hash=receipt.hash)
            conn.execute("INSERT INTO fills(id, ts, mode, side, mint, position_id, data, receipt_seq) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (fill.id, fill.ts, fill.mode, fill.side, fill.mint, fill.position_id, _dumps(stored),
                          receipt.seq))
        return stored

    def record_swap_failure(self, payload: dict[str, Any]) -> Receipt:
        """``swap_failed`` receipt (quote summary, error, outcome 'failed'|'unknown')."""
        return self.append_receipt("swap_failed", payload)

    def upsert_position(self, position: Position) -> None:
        """Insert or replace by id (positions change over time; fills/receipts are the audit trail)."""
        self._write("INSERT INTO positions(id, mint, status, opened_at, closed_at, data) VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET mint = excluded.mint, status = excluded.status, "
                    "opened_at = excluded.opened_at, closed_at = excluded.closed_at, data = excluded.data",
                    (position.id, position.mint, position.status, position.opened_at, position.closed_at,
                     _dumps(position)))

    def mark_position(self, position_id: str, *, peak_price_usd: float, last_price_usd: float,
                      last_marked_at: float) -> bool:
        """Store a new mark (peak/last price) on an OPEN position, touching nothing else.

        Read-modify-write inside one transaction, so a stale in-memory copy can never write
        back an old ``status``/``token_amount`` (e.g. after ``nightcrawler sell-all`` closed it
        from another process). Returns False when the position is no longer open.
        """
        with self.transaction(), self._locked() as conn:
            row = conn.execute("SELECT data FROM positions WHERE id = ? AND status = 'open'",
                               (position_id,)).fetchone()
            if row is None:
                return False
            data = json.loads(row[0])
            data.update(peak_price_usd=float(peak_price_usd), last_price_usd=float(last_price_usd),
                        last_marked_at=float(last_marked_at))
            conn.execute("UPDATE positions SET data = ? WHERE id = ?", (_dumps(data), position_id))
        return True

    def update_open_position(self, position: Position, expected_token_amount: int) -> None:
        """Write ``position`` only if the stored row is still OPEN with ``expected_token_amount``
        tokens (what the caller read before its sell); else raise :class:`LedgerError` and change
        nothing - another process sold or closed it meanwhile."""
        with self.transaction(), self._locked() as conn:
            row = conn.execute("SELECT status, data FROM positions WHERE id = ?", (position.id,)).fetchone()
            stored = json.loads(row[1]).get("token_amount") if row is not None else None
            if row is None or row[0] != "open" or stored != expected_token_amount:
                raise LedgerError(f"position {position.id} changed concurrently (stored "
                                  f"{row[0] if row else 'missing'}/{stored}, expected open/{expected_token_amount})")
            self.upsert_position(position)

    def set_position_wallet(self, position_id: str, wallet: str | None) -> None:
        """Record the wallet (pubkey) that holds a LIVE position's tokens; kept by later writes."""
        self._write("UPDATE positions SET wallet = ? WHERE id = ?", (wallet, position_id))

    def position_wallets(self, position_ids: Sequence[str] | None = None) -> dict[str, str | None]:
        """``{position_id: wallet or None}`` for ``position_ids`` (default: every OPEN position)."""
        if position_ids is None:
            return dict(self._rows("SELECT id, wallet FROM positions WHERE status = 'open' ORDER BY opened_at, rowid"))
        ids = list(dict.fromkeys(position_ids))
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        return dict(self._rows(f"SELECT id, wallet FROM positions WHERE id IN ({marks})", ids))

    def get_position(self, position_id: str) -> Position | None:
        rows = self._rows("SELECT data FROM positions WHERE id = ?", (position_id,))
        return self._load_positions(rows)[0] if rows else None

    def open_positions(self, mode: str | None = None) -> list[Position]:
        """Open positions ordered by ``opened_at`` (only those of ``mode`` when given)."""
        rows = self._rows("SELECT data FROM positions WHERE status = 'open' ORDER BY opened_at, rowid")
        return [p for p in self._load_positions(rows) if mode is None or p.mode == mode]

    def positions(self, status: str | None = None, limit: int | None = None,
                  mode: str | None = None) -> list[Position]:
        """Positions newest first, optionally filtered by status and trading mode."""
        where, params = ("", []) if status is None else (" WHERE status = ?", [status])
        clause, extra = _limit_clause(limit if mode is None else None)
        rows = self._rows(f"SELECT data FROM positions{where} ORDER BY opened_at DESC, rowid DESC{clause}",
                          [*params, *extra])
        out = [p for p in self._load_positions(rows) if mode is None or p.mode == mode]
        return out if limit is None else out[:limit]

    def _load_positions(self, rows: Sequence[Any]) -> list[Position]:
        """Rows -> Positions; ``mode`` of rows written before it existed comes from their fills
        (the first entry fill, else any fill linked by ``position_id``)."""
        positions = [Position.from_dict(json.loads(r[0])) for r in rows]
        unknown = {p.entry_fill_ids[0] for p in positions if p.mode is None and p.entry_fill_ids}
        if unknown:
            marks = ",".join("?" for _ in unknown)
            modes = dict(self._rows(f"SELECT id, mode FROM fills WHERE id IN ({marks})", sorted(unknown)))
            for p in positions:
                if p.mode is None and p.entry_fill_ids:
                    p.mode = modes.get(p.entry_fill_ids[0])  # type: ignore[assignment]
        orphans = {p.id for p in positions if p.mode is None}
        if orphans:
            marks = ",".join("?" for _ in orphans)
            linked = dict(self._rows(f"SELECT position_id, MIN(mode) FROM fills WHERE position_id IN ({marks}) "
                                     "GROUP BY position_id", sorted(orphans)))
            for p in positions:
                if p.mode is None:
                    p.mode = linked.get(p.id)  # type: ignore[assignment]
        return positions

    def last_closed_at(self, mint: str) -> float | None:
        """Most recent ``closed_at`` of a position in ``mint`` (cooldown)."""
        return self._rows("SELECT MAX(closed_at) FROM positions WHERE mint = ?", (mint,))[0][0]

    def fills(self, limit: int | None = 50, mint: str | None = None, since: float | None = None,
              position_id: str | None = None) -> list[Fill]:
        """Fills newest first with optional filters (``since`` inclusive)."""
        conditions, params = [], []
        for column, op, value in (("mint", "=", mint), ("ts", ">=", since), ("position_id", "=", position_id)):
            if value is not None:
                conditions.append(f"{column} {op} ?")
                params.append(value)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        clause, extra = _limit_clause(limit)
        rows = self._rows(f"SELECT data FROM fills{where} ORDER BY ts DESC, receipt_seq DESC{clause}",
                          [*params, *extra])
        return [Fill.from_dict(json.loads(r[0])) for r in rows]

    def fill_receipts(self) -> list[tuple[str, dict[str, Any], dict[str, Any] | None, str | None]]:
        """``[(fill_id, row data, its 'fill' receipt payload or None, that receipt's hash)]`` in chain
        order, so an auditor can prove each (editable) fill row still says what was hash-chained."""
        rows = self._rows("SELECT f.id, f.data, r.payload, r.hash FROM fills f LEFT JOIN receipts r "
                          "ON r.seq = f.receipt_seq AND r.kind = 'fill' ORDER BY f.receipt_seq")
        return [(fid, json.loads(data), json.loads(payload) if payload is not None else None, digest)
                for fid, data, payload, digest in rows]

    def fills_after_seq(self, after_seq: int, mode: str | None = None) -> list[Fill]:
        """Fills whose receipt ``seq > after_seq`` in chain order (optionally one mode only)."""
        where, params = ("", []) if mode is None else (" AND mode = ?", [mode])
        rows = self._rows(f"SELECT data FROM fills WHERE receipt_seq > ?{where} ORDER BY receipt_seq",
                          [after_seq, *params])
        return [Fill.from_dict(json.loads(r[0])) for r in rows]

    def decisions(self, limit: int = 50, actions: Sequence[str] | None = None) -> list[Decision]:
        """Decisions newest first, optionally filtered by action."""
        where, params = "", []
        if actions:
            where = f" WHERE action IN ({', '.join('?' for _ in actions)})"
            params = list(actions)
        rows = self._rows(f"SELECT data FROM decisions{where} ORDER BY ts DESC, id DESC LIMIT ?", [*params, limit])
        return [Decision.from_dict(json.loads(r[0])) for r in rows]

    def decision_counts(self, since: float | None = None) -> dict[str, int]:
        """``{action: count}`` (dashboard rejection summary)."""
        rows = self._rows("SELECT action, COUNT(*) FROM decisions WHERE ts >= ? GROUP BY action ORDER BY action",
                          (float("-inf") if since is None else since,))
        return {action: count for action, count in rows}

    def record_equity(self, point: EquityPoint) -> None:
        self._write("INSERT INTO equity(ts, equity_lamports, sol_usd, equity_usd, mode, data) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (point.ts, point.equity_lamports, point.sol_usd, point.equity_usd, point.mode, _dumps(point)))

    def equity_series(self, since: float | None = None, limit: int | None = None) -> list[EquityPoint]:
        """Equity points ascending by ts (``since`` inclusive; downsampling is the caller's job).

        ``limit`` keeps the FIRST ``limit`` points of that ascending series (the
        oldest ones at/after ``since``), not the latest; use :meth:`latest_equity`
        or :meth:`equity_curve` for recent history.
        """
        clause, extra = _limit_clause(limit)
        rows = self._rows(f"SELECT data FROM equity WHERE ts >= ? ORDER BY ts, id{clause}",
                          [float("-inf") if since is None else since, *extra])
        return [EquityPoint.from_dict(json.loads(r[0])) for r in rows]

    def latest_equity(self) -> EquityPoint | None:
        rows = self._rows("SELECT data FROM equity ORDER BY ts DESC, id DESC LIMIT 1")
        return EquityPoint.from_dict(json.loads(rows[0][0])) if rows else None

    def equity_curve(self, since: float | None = None, max_points: int = 300,
                     mode: str | None = None) -> list[tuple[float, float]]:
        """``[(ts, equity_usd)]`` ascending, downsampled in SQL to at most ``max_points``
        (the last point of each time bucket, so the newest point is always included)."""
        where = "ts >= ?" + ("" if mode is None else " AND mode = ?")
        params: list[Any] = [float("-inf") if since is None else since] + ([] if mode is None else [mode])
        first, last, count = self._rows(f"SELECT MIN(ts), MAX(ts), COUNT(*) FROM equity WHERE {where}", params)[0]
        if count <= max_points:
            rows = self._rows(f"SELECT ts, equity_usd FROM equity WHERE {where} ORDER BY ts, id", params)
        elif last == first or max_points < 2:
            rows = self._rows(f"SELECT ts, equity_usd FROM equity WHERE {where} ORDER BY ts DESC, id DESC LIMIT 1",
                              params)
        else:
            width = (last - first) / (max_points - 1)
            # SQLite returns the bare columns of the row holding MAX(ts) in each group.
            rows = self._rows(f"SELECT MAX(ts), equity_usd FROM equity WHERE {where} "
                              f"GROUP BY CAST((ts - ?) / ? AS INTEGER) ORDER BY 1", [*params, first, width])
        return [(float(ts), float(usd)) for ts, usd in rows]
