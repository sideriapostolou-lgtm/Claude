"""``learn.db``: the learning loop's SQLite store (docs/LEARNING.md §3.3). ADVISORY ONLY.

Nothing the engine trades is read from here: the champion and the live gate are a pure fold over
``learn`` receipts on the ledger's chain (phase 2). This file holds the working state of the
recorder (coins, fetch queue), the learner (variants cache, evidence, scoreboard, lease) and the
OUTBOX through which learner results reach the chain.

Concurrency: WAL, a busy timeout, ``BEGIN IMMEDIATE`` transactions and one ``RLock`` per
connection. The recorder thread, the learner subprocess and the engine's ``learn`` stage each open
their own :class:`LearnStore`; the dashboard opens it ``readonly=True`` (it never creates the file).

Tables (``PRAGMA user_version`` = :data:`SCHEMA_VERSION`):

* ``coins(mint PK, created_ts, first_seen_ts, day, pool, quote_mint, mayhem, late, launch JSON,
  status open|closed|incomplete, fetches_done, mark JSON)`` - ``mark``: the recorder's candle state per coin.
* ``fetch_queue((mint, kind, due_ts) PK, attempts, next_try_ts, done_ts, failed)`` - resumes exactly
  after a restart.
* ``variants(hash PK, name, family, params JSON, procedure JSON, source, register_seq, t0, alpha,
  threshold, promotable, status, created_ts)`` - a cache of ``register`` receipts; ``t0`` stays NULL
  until the engine has receipted the registration (the forward-only rule needs it).
* ``evidence((variant_hash, mint, pricing) PK, entry_ts, exit_ts, x, x_raw, x_stress, gross, cost,
  sim_hash, cost_scale_ver)`` and ``replayed((variant_hash, mint) PK, outcome, sim_hash, ts)``.
* ``scoreboard((day, variant_hash) PK, data JSON, updated_ts)``.
* ``outbox(id PK, event, payload JSON, created_ts, receipt_seq, receipt_ts)``.
* ``trials(day, family, n)`` (starts at the lab's 2,800), ``lease(name PK, pid, ts)``, ``meta(key PK, value)``.

EXACTLY ONCE (invariant S2): :func:`drain_outbox` turns each outbox row into one ``learn`` receipt
whose payload carries ``event``, ``outbox_id`` and ``store`` (this file's random uid, so a recreated
learn.db whose ids restart at 1 is never mistaken for an old one). Each row is handled in its own
``BEGIN IMMEDIATE`` transaction (two drainers queue on it); before appending, the chain is searched
for the row's receipt, so a crash between the append and the mark is healed on the next drain.
"""

from __future__ import annotations

import contextlib
import json
import secrets
import sqlite3
import threading
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

__all__ = ["SCHEMA_VERSION", "BUSY_TIMEOUT_S", "RECEIPT_KIND", "LAB_TRIALS", "LearnStore", "LearnStoreError",
           "learn_dir", "db_path", "drain_outbox"]

SCHEMA_VERSION = 1
BUSY_TIMEOUT_S = 10.0
#: ``models.ReceiptKind`` value of every learning receipt (the chain format is unchanged).
RECEIPT_KIND = "learn"
#: Strategy configurations the lab already tried (research/lab/RESULTS.md): the trial counter starts here.
LAB_TRIALS = 2800

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS coins (
        mint TEXT PRIMARY KEY, created_ts REAL NOT NULL, first_seen_ts REAL NOT NULL, day TEXT NOT NULL,
        pool TEXT, quote_mint TEXT, mayhem INTEGER NOT NULL DEFAULT 0, late INTEGER NOT NULL DEFAULT 0,
        launch TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', fetches_done INTEGER NOT NULL DEFAULT 0,
        mark TEXT)""",
    "CREATE INDEX IF NOT EXISTS coins_day ON coins(day, status)",
    """CREATE TABLE IF NOT EXISTS fetch_queue (
        mint TEXT NOT NULL, kind TEXT NOT NULL, due_ts REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        next_try_ts REAL NOT NULL, done_ts REAL, failed INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (mint, kind, due_ts))""",
    "CREATE INDEX IF NOT EXISTS fetch_queue_due ON fetch_queue(done_ts, next_try_ts)",
    """CREATE TABLE IF NOT EXISTS variants (
        hash TEXT PRIMARY KEY, name TEXT NOT NULL, family TEXT NOT NULL, params TEXT NOT NULL, procedure TEXT,
        source TEXT NOT NULL, register_seq INTEGER, t0 REAL, alpha REAL NOT NULL, threshold REAL NOT NULL,
        promotable INTEGER NOT NULL, status TEXT NOT NULL, created_ts REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS evidence (
        variant_hash TEXT NOT NULL, mint TEXT NOT NULL, pricing TEXT NOT NULL, entry_ts REAL NOT NULL,
        exit_ts REAL NOT NULL, x REAL NOT NULL, x_raw REAL NOT NULL, x_stress REAL NOT NULL, gross REAL NOT NULL,
        cost REAL NOT NULL, sim_hash TEXT NOT NULL, cost_scale_ver INTEGER NOT NULL,
        PRIMARY KEY (variant_hash, mint, pricing))""",
    "CREATE INDEX IF NOT EXISTS evidence_order ON evidence(variant_hash, pricing, exit_ts, mint)",
    """CREATE TABLE IF NOT EXISTS replayed (
        variant_hash TEXT NOT NULL, mint TEXT NOT NULL, outcome TEXT NOT NULL, sim_hash TEXT NOT NULL,
        ts REAL NOT NULL, PRIMARY KEY (variant_hash, mint))""",
    """CREATE TABLE IF NOT EXISTS scoreboard (
        day TEXT NOT NULL, variant_hash TEXT NOT NULL, data TEXT NOT NULL, updated_ts REAL NOT NULL,
        PRIMARY KEY (day, variant_hash))""",
    """CREATE TABLE IF NOT EXISTS outbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT, event TEXT NOT NULL, payload TEXT NOT NULL,
        created_ts REAL NOT NULL, receipt_seq INTEGER, receipt_ts REAL)""",
    """CREATE TABLE IF NOT EXISTS trials (
        day TEXT NOT NULL, family TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY (day, family))""",
    """CREATE TABLE IF NOT EXISTS lease (name TEXT PRIMARY KEY, pid INTEGER NOT NULL, ts REAL NOT NULL)""",
)


class LearnStoreError(Exception):
    """learn.db cannot be used (e.g. written by a newer schema)."""


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def learn_dir(data_dir: str | Path) -> Path:
    """``DATA_DIR/learn``: holds ``learn.db`` and ``tape/``."""
    return Path(data_dir) / "learn"


def db_path(data_dir: str | Path) -> Path:
    return learn_dir(data_dir) / "learn.db"


class LearnStore:
    """One connection to ``learn.db`` (see the module docstring). Use as a context manager."""

    def __init__(self, path: str | Path, *, readonly: bool = False, busy_timeout_s: float = BUSY_TIMEOUT_S) -> None:
        self.path = Path(path)
        self.readonly = readonly
        if readonly:
            if not self.path.exists():
                raise FileNotFoundError(str(self.path))
            uri = f"{self.path.resolve().as_uri()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=busy_timeout_s, check_same_thread=False,
                                   isolation_level=None)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.path), timeout=busy_timeout_s, check_same_thread=False,
                                   isolation_level=None)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        self._conn: sqlite3.Connection | None = conn
        self._lock = threading.RLock()
        self._depth = 0
        if not readonly:
            self._migrate()
        #: random id of this learn.db (written once at creation), carried by every outbox receipt
        self.uid: str = self.get_meta("store_uid") or ""

    # ------------------------------------------------------------------ plumbing
    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> "LearnStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise LearnStoreError("learn.db is closed")
        return self._conn

    @contextlib.contextmanager
    def transaction(self) -> Iterator["LearnStore"]:
        """``BEGIN IMMEDIATE`` ... ``COMMIT`` (ROLLBACK on error); nested calls join the outer one."""
        with self._lock:
            outer = self._depth == 0
            if outer:
                self.conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self
            except BaseException:
                self._depth -= 1
                if outer:
                    with contextlib.suppress(sqlite3.Error):
                        self.conn.execute("ROLLBACK")
                raise
            self._depth -= 1
            if outer:
                self.conn.execute("COMMIT")

    def _rows(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    def _write(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> int:
        with self.transaction():
            return self.conn.execute(sql, params).rowcount

    def _migrate(self) -> None:
        with self.transaction():
            version = self.conn.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise LearnStoreError(f"learn.db schema v{version} is newer than this code (v{SCHEMA_VERSION})")
            for statement in _SCHEMA:
                self.conn.execute(statement)
            if self.get_meta("store_uid") is None:
                self.set_meta("store_uid", secrets.token_hex(8))
                self.conn.execute("INSERT OR IGNORE INTO trials(day, family, n) VALUES ('lab', 'all', ?)",
                                  (LAB_TRIALS,))
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    # ------------------------------------------------------------------ meta
    def get_meta(self, key: str, default: Any = None) -> Any:
        rows = self._rows("SELECT value FROM meta WHERE key = ?", (key,))
        return json.loads(rows[0][0]) if rows else default

    def set_meta(self, key: str, value: Any) -> None:
        self._write("INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, _dumps(value)))

    # ------------------------------------------------------------------ coins
    def add_coin(self, mint: str, *, created_ts: float, first_seen_ts: float, day: str, pool: str | None = None,
                 quote_mint: str | None = None, mayhem: bool = False, late: bool = False,
                 launch: Mapping[str, Any] | None = None) -> bool:
        """Enrol a coin once; False if it is already known (first sighting wins)."""
        return self._write(
            "INSERT OR IGNORE INTO coins(mint, created_ts, first_seen_ts, day, pool, quote_mint, mayhem, late, launch)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (mint, float(created_ts), float(first_seen_ts), day, pool, quote_mint, int(bool(mayhem)),
             int(bool(late)), _dumps(dict(launch or {})))) == 1

    @staticmethod
    def _coin(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        out["launch"] = json.loads(out["launch"])
        out["mark"] = None if out["mark"] is None else json.loads(out["mark"])
        out["mayhem"], out["late"] = bool(out["mayhem"]), bool(out["late"])
        return out

    def coin(self, mint: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM coins WHERE mint = ?", (mint,))
        return self._coin(rows[0]) if rows else None

    def coins(self, day: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        where, params = [], []
        if day is not None:
            where.append("day = ?")
            params.append(day)
        if status is not None:
            where.append("status = ?")
            params.append(status)
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        return [self._coin(r) for r in self._rows(f"SELECT * FROM coins{clause} ORDER BY created_ts, mint", params)]

    def set_coin_status(self, mint: str, status: str) -> None:
        self._write("UPDATE coins SET status = ? WHERE mint = ?", (status, mint))

    def set_coin_mark(self, mint: str, mark: Mapping[str, Any]) -> None:
        """The recorder's per-coin candle state between fetches (``tape.candle_mark``)."""
        self._write("UPDATE coins SET mark = ? WHERE mint = ?", (_dumps(dict(mark)), mint))

    def day_counts(self, day: str) -> dict[str, int]:
        """``{"coins": n, "open": .., "closed": .., "incomplete": ..}`` for a first-seen day."""
        counts = {"coins": 0, "open": 0, "closed": 0, "incomplete": 0}
        for status, n in self._rows("SELECT status, COUNT(*) FROM coins WHERE day = ? GROUP BY status", (day,)):
            counts[status] = n
            counts["coins"] += n
        return counts

    def days(self) -> list[str]:
        return [r[0] for r in self._rows("SELECT DISTINCT day FROM coins ORDER BY day")]

    def newest_created(self, day: str) -> float | None:
        """Creation time of the newest coin first seen on ``day`` (None for an empty day)."""
        return self._rows("SELECT MAX(created_ts) FROM coins WHERE day = ?", (day,))[0][0]

    def summary(self) -> dict[str, Any]:
        """Counts for ``nightcrawler learn status``: coins per status, days, the fetch queue, variants,
        evidence rows and the outbox."""
        coins = {"open": 0, "closed": 0, "incomplete": 0}
        coins.update(dict(self._rows("SELECT status, COUNT(*) FROM coins GROUP BY status")))
        fetches = {"pending": 0, "done": 0, "failed": 0}
        fetches.update(dict(self._rows(
            "SELECT CASE WHEN done_ts IS NULL THEN 'pending' WHEN failed THEN 'failed' ELSE 'done' END, COUNT(*) "
            "FROM fetch_queue GROUP BY 1")))
        rows, receipted = self._rows("SELECT COUNT(*), COUNT(receipt_seq) FROM outbox")[0]
        return {"coins": {"total": sum(coins.values()), **coins}, "days": self.days(), "fetches": fetches,
                "variants": self._rows("SELECT COUNT(*) FROM variants")[0][0],
                "evidence": self._rows("SELECT COUNT(*) FROM evidence")[0][0],
                "outbox": {"rows": rows, "receipted": receipted, "pending": rows - receipted}}

    # ------------------------------------------------------------------ fetch queue
    def schedule(self, mint: str, kind: str, due_ts: float) -> None:
        self._write("INSERT OR IGNORE INTO fetch_queue(mint, kind, due_ts, next_try_ts) VALUES (?, ?, ?, ?)",
                    (mint, kind, float(due_ts), float(due_ts)))

    def due(self, now: float, kind: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        """Open fetches whose (retry) time has come, oldest due first."""
        sql = "SELECT * FROM fetch_queue WHERE done_ts IS NULL AND next_try_ts <= ?"
        params: list[Any] = [float(now)]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY due_ts, mint, kind"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [dict(r) for r in self._rows(sql, params)]

    def retry_fetch(self, mint: str, kind: str, due_ts: float, next_try_ts: float) -> int:
        """Count a failed attempt and try again at ``next_try_ts``; returns the attempts so far."""
        with self.transaction():
            self.conn.execute("UPDATE fetch_queue SET attempts = attempts + 1, next_try_ts = ? "
                              "WHERE mint = ? AND kind = ? AND due_ts = ?", (float(next_try_ts), mint, kind, due_ts))
            rows = self._rows("SELECT attempts FROM fetch_queue WHERE mint = ? AND kind = ? AND due_ts = ?",
                              (mint, kind, due_ts))
        return int(rows[0][0]) if rows else 0

    def postpone_fetch(self, mint: str, kind: str, due_ts: float, next_try_ts: float) -> None:
        """Try again later WITHOUT counting an attempt (the host, not the coin, was unavailable)."""
        self._write("UPDATE fetch_queue SET next_try_ts = ? WHERE mint = ? AND kind = ? AND due_ts = ?",
                    (float(next_try_ts), mint, kind, due_ts))

    def finish_fetch(self, mint: str, kind: str, due_ts: float, now: float) -> None:
        with self.transaction():
            changed = self.conn.execute("UPDATE fetch_queue SET done_ts = ? WHERE mint = ? AND kind = ? AND due_ts = ?"
                                        " AND done_ts IS NULL", (float(now), mint, kind, due_ts)).rowcount
            if changed:
                self.conn.execute("UPDATE coins SET fetches_done = fetches_done + 1 WHERE mint = ?", (mint,))

    def fail_fetch(self, mint: str, kind: str, due_ts: float, now: float) -> None:
        self._write("UPDATE fetch_queue SET done_ts = ?, failed = 1 WHERE mint = ? AND kind = ? AND due_ts = ?",
                    (float(now), mint, kind, due_ts))

    def open_fetches(self, mint: str, kind: str | None = None) -> int:
        sql, params = "SELECT COUNT(*) FROM fetch_queue WHERE mint = ? AND done_ts IS NULL", [mint]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind)
        return int(self._rows(sql, params)[0][0])

    def fetches(self, mint: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._rows("SELECT * FROM fetch_queue WHERE mint = ? ORDER BY due_ts, kind", (mint,))]

    # ------------------------------------------------------------------ variants
    def add_variant(self, variant_hash: str, *, family: str, params: Mapping[str, Any], source: str, alpha: float,
                    threshold: float, promotable: bool, name: str, now: float,
                    procedure: Mapping[str, Any] | None = None, status: str = "testing") -> bool:
        """Cache a registration and queue its ``register`` receipt (one transaction). False if known.
        ``t0`` is set when the receipt is written (:meth:`mark_outbox`)."""
        with self.transaction():
            inserted = self.conn.execute(
                "INSERT OR IGNORE INTO variants(hash, name, family, params, procedure, source, alpha, threshold, "
                "promotable, status, created_ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (variant_hash, name, family, _dumps(dict(params)), None if procedure is None else _dumps(procedure),
                 source, float(alpha), float(threshold), int(bool(promotable)), status, float(now))).rowcount == 1
            if inserted:
                self.add_outbox("register", {
                    "variant_hash": variant_hash, "name": name, "family": family, "params": dict(params),
                    "procedure": procedure, "source": source, "alpha": alpha, "threshold": threshold,
                    "promotable": bool(promotable), "trials_total": self.trials_total()}, now)
        return inserted

    @staticmethod
    def _variant(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        out["params"] = json.loads(out["params"])
        out["procedure"] = None if out["procedure"] is None else json.loads(out["procedure"])
        out["promotable"] = bool(out["promotable"])
        return out

    def variant(self, variant_hash: str) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM variants WHERE hash = ?", (variant_hash,))
        return self._variant(rows[0]) if rows else None

    def variants(self, status: str | None = None) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM variants", []
        if status is not None:
            sql += " WHERE status = ?"
            params.append(status)
        return [self._variant(r) for r in self._rows(sql + " ORDER BY created_ts, hash", params)]

    def set_variant_status(self, variant_hash: str, status: str) -> None:
        self._write("UPDATE variants SET status = ? WHERE hash = ?", (status, variant_hash))

    def trials_total(self) -> int:
        return int(self._rows("SELECT COALESCE(SUM(n), 0) FROM trials")[0][0])

    # ------------------------------------------------------------------ evidence
    _EVIDENCE = ("variant_hash", "mint", "pricing", "entry_ts", "exit_ts", "x", "x_raw", "x_stress", "gross", "cost",
                 "sim_hash", "cost_scale_ver")

    def put_evidence(self, row: Mapping[str, Any]) -> None:
        """Insert or replace one (variant, coin, pricing) observation."""
        cols = ", ".join(self._EVIDENCE)
        self._write(f"INSERT OR REPLACE INTO evidence({cols}) VALUES ({', '.join('?' * len(self._EVIDENCE))})",
                    [row[k] for k in self._EVIDENCE])

    def evidence(self, variant_hash: str, pricing: str = "replay") -> list[dict[str, Any]]:
        """A variant's observations in evidence ORDER: ``(exit_ts, mint)``."""
        return [dict(r) for r in self._rows("SELECT * FROM evidence WHERE variant_hash = ? AND pricing = ? "
                                            "ORDER BY exit_ts, mint", (variant_hash, pricing))]

    def evidence_mints(self, variant_hash: str, pricing: str = "replay") -> set[str]:
        return {r[0] for r in self._rows("SELECT mint FROM evidence WHERE variant_hash = ? AND pricing = ?",
                                         (variant_hash, pricing))}

    def mark_replayed(self, variant_hash: str, mint: str, outcome: str, sim_hash: str, now: float) -> None:
        self._write("INSERT OR REPLACE INTO replayed(variant_hash, mint, outcome, sim_hash, ts) VALUES (?, ?, ?, ?, ?)",
                    (variant_hash, mint, outcome, sim_hash, float(now)))

    def replayed(self, variant_hash: str, sim_hash: str | None = None) -> dict[str, str]:
        """``{mint: outcome}`` of finished (variant, coin) replays (under ``sim_hash`` when given)."""
        sql, params = "SELECT mint, outcome FROM replayed WHERE variant_hash = ?", [variant_hash]
        if sim_hash is not None:
            sql += " AND sim_hash = ?"
            params.append(sim_hash)
        return {r[0]: r[1] for r in self._rows(sql, params)}

    # ------------------------------------------------------------------ scoreboard
    def put_scoreboard(self, day: str, variant_hash: str, data: Mapping[str, Any], now: float) -> None:
        self._write("INSERT OR REPLACE INTO scoreboard(day, variant_hash, data, updated_ts) VALUES (?, ?, ?, ?)",
                    (day, variant_hash, _dumps(dict(data)), float(now)))

    def latest_scoreboard_day(self) -> str | None:
        rows = self._rows("SELECT MAX(day) FROM scoreboard")
        return rows[0][0] if rows else None

    def scoreboard(self, day: str) -> list[dict[str, Any]]:
        return [{"day": r["day"], "variant_hash": r["variant_hash"], **json.loads(r["data"]),
                 "updated_ts": r["updated_ts"]}
                for r in self._rows("SELECT * FROM scoreboard WHERE day = ? ORDER BY variant_hash", (day,))]

    # ------------------------------------------------------------------ outbox
    def add_outbox(self, event: str, payload: Mapping[str, Any], now: float) -> int:
        with self.transaction():
            cur = self.conn.execute("INSERT INTO outbox(event, payload, created_ts) VALUES (?, ?, ?)",
                                    (event, _dumps(dict(payload)), float(now)))
            return int(cur.lastrowid)

    @staticmethod
    def _outbox(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        out["payload"] = json.loads(out["payload"])
        return out

    def next_outbox(self) -> dict[str, Any] | None:
        rows = self._rows("SELECT * FROM outbox WHERE receipt_seq IS NULL ORDER BY id LIMIT 1")
        return self._outbox(rows[0]) if rows else None

    def outbox(self, limit: int | None = None, pending: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM outbox" + (" WHERE receipt_seq IS NULL" if pending else "") + " ORDER BY id"
        params: list[Any] = []
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [self._outbox(r) for r in self._rows(sql, params)]

    def mark_outbox(self, outbox_id: int, receipt_seq: int, receipt_ts: float) -> None:
        """Record the row's receipt; a ``register`` row also fixes its variant's ``t0`` (= receipt ts)."""
        with self.transaction():
            self.conn.execute("UPDATE outbox SET receipt_seq = ?, receipt_ts = ? WHERE id = ? AND receipt_seq IS NULL",
                              (int(receipt_seq), float(receipt_ts), int(outbox_id)))
            rows = self._rows("SELECT event, payload FROM outbox WHERE id = ?", (int(outbox_id),))
            if rows and rows[0][0] == "register":
                variant_hash = json.loads(rows[0][1]).get("variant_hash")
                self.conn.execute("UPDATE variants SET t0 = ?, register_seq = ? WHERE hash = ? AND t0 IS NULL",
                                  (float(receipt_ts), int(receipt_seq), variant_hash))

    # ------------------------------------------------------------------ lease (one learner at a time, S6)
    def acquire_lease(self, name: str, pid: int, now: float, stale_s: float) -> bool:
        """Take (or renew) the lease ``name`` for ``pid``; a lease older than ``stale_s`` is taken over."""
        with self.transaction():
            rows = self._rows("SELECT pid, ts FROM lease WHERE name = ?", (name,))
            if rows and rows[0][0] != pid and now - rows[0][1] <= stale_s:
                return False
            self.conn.execute("INSERT OR REPLACE INTO lease(name, pid, ts) VALUES (?, ?, ?)",
                              (name, int(pid), float(now)))
            return True

    def release_lease(self, name: str, pid: int) -> None:
        self._write("DELETE FROM lease WHERE name = ? AND pid = ?", (name, int(pid)))


def _receipted(ledger: Any, store_uid: str, outbox_id: int) -> Any:
    """The chain's receipt of outbox row ``outbox_id`` of this learn.db, or None.

    Rows are receipted in id order, so the NEWEST ``learn`` receipt answers almost every call
    without a scan: it is this row's receipt, or it belongs to this store with a smaller id (this row
    was never appended). Anything else (another store, an unexpected order) falls back to a search.
    """
    newest = ledger.last_receipt(RECEIPT_KIND)
    if newest is None:
        return None
    if newest.payload.get("store") == store_uid:
        newest_id = newest.payload.get("outbox_id")
        if newest_id == outbox_id:
            return newest
        if isinstance(newest_id, int) and newest_id < outbox_id:
            return None
    return ledger.last_receipt(RECEIPT_KIND, where={"store": store_uid, "outbox_id": outbox_id})


def drain_outbox(store: LearnStore, ledger: Any, limit: int = 10) -> int:
    """Append up to ``limit`` pending outbox rows to ``ledger`` as ``learn`` receipts, exactly once each
    (see the module docstring). Returns the rows handled. Called by the engine's ``learn`` stage only."""
    handled = 0
    while handled < limit:
        with store.transaction():
            row = store.next_outbox()
            if row is None:
                break
            receipt = _receipted(ledger, store.uid, row["id"])
            if receipt is None:
                payload = {**row["payload"], "event": row["event"], "outbox_id": row["id"], "store": store.uid}
                receipt = ledger.append_receipt(RECEIPT_KIND, payload)
            store.mark_outbox(row["id"], receipt.seq, receipt.ts)
        handled += 1
    return handled
