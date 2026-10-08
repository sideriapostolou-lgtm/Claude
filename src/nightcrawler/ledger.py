"""SQLite ledger + hash-chained receipts (owner: O6). Single source of truth.

Storage: one SQLite file (``settings.db_path`` = ``DATA_DIR/nightcrawler.db``),
WAL mode, ``check_same_thread=False`` guarded by one ``threading.RLock`` (the
engine writes from its thread; the dashboard reads from HTTP threads).

Tables (columns are a suggestion; the public methods are the contract):

* ``kv(key TEXT PRIMARY KEY, value TEXT JSON, updated_at REAL)``
* ``candidates(mint PK, data JSON, first_seen REAL, last_seen REAL)``
* ``safety(mint, checked_at, passed INT, data JSON)``
* ``decisions(id INTEGER PK, ts, mint, action, reason, data JSON, receipt_seq)``
* ``fills(id TEXT PK, ts, mode, side, mint, position_id, data JSON, receipt_seq)``
* ``positions(id TEXT PK, mint, status, opened_at, closed_at, data JSON)``
* ``equity(ts REAL, equity_lamports INT, sol_usd REAL, equity_usd REAL, data JSON)``
* ``receipts(seq INTEGER PK, ts REAL, kind TEXT, payload TEXT canonical JSON,
  prev_hash TEXT, hash TEXT UNIQUE)``

RECEIPTS (hindsight-proof): :meth:`Ledger.append_receipt` computes
``hash = sha256(prev_hash + canonical_json({seq, ts, kind, payload}))`` with
``nightcrawler.hashing`` (payload normalized first; ``ts`` rounded to ms),
inside the same transaction that reads the previous head, so the chain can
never fork. The engine appends a receipt for every Decision and every Fill
IMMEDIATELY - before any later price is fetched. ``record_decision`` and
``record_fill`` write the row and its receipt atomically.

Well-known kv keys (JSON values): ``paper.sol_lamports``, ``paper.tokens``,
``paper.rent``, ``paper.start_lamports``, ``paper.start_sol_usd``,
``live.start_lamports``, ``risk.halted``, ``risk.peak_reset_ts``,
``engine.heartbeat``, ``engine.started_at``, ``engine.status`` (dict),
``engine.kill_mode``, ``engine.last_error``, ``judge.cost_usd_total``,
``judge.cost_usd_day``, ``judge.calls``, ``wallet.pubkey``.
"""

from __future__ import annotations

import os
from typing import Any, Iterator, Sequence

from nightcrawler.models import (
    Decision,
    EquityPoint,
    Fill,
    Position,
    Receipt,
    SafetyReport,
    TokenCandidate,
)

__all__ = ["Ledger", "LedgerError"]


class LedgerError(Exception):
    """Storage failure or a broken invariant (e.g. a receipt write that would fork the chain)."""


class Ledger:
    """Thread-safe SQLite ledger. Use as a context manager or call :meth:`close`."""

    def __init__(self, path: str | os.PathLike[str], clock: Any | None = None) -> None:
        """Open/create the database at ``path`` (parent dirs created), enable WAL, create tables.

        ``path=":memory:"`` is allowed (tests). ``clock`` (default RealClock)
        supplies receipt/kv timestamps when none is passed explicitly.
        """
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def __enter__(self) -> "Ledger":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ kv
    def get_kv(self, key: str, default: Any = None) -> Any:
        """JSON-decoded value or ``default``."""
        raise NotImplementedError

    def set_kv(self, key: str, value: Any) -> None:
        """Store a JSON-serializable value (upsert)."""
        raise NotImplementedError

    def transaction(self) -> Any:
        """Context manager: one atomic SQLite transaction holding the lock (re-entrant).

        Used e.g. by PaperBroker to update balances and record a fill atomically.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------ receipts
    def append_receipt(self, kind: str, payload: dict[str, Any], ts: float | None = None) -> Receipt:
        """Append one receipt (see module docstring). ``kind`` in ``models.ReceiptKind``.

        Raises ``ValueError`` for NaN/inf in the payload and :class:`LedgerError` on storage failure.
        """
        raise NotImplementedError

    def head(self) -> tuple[int, str]:
        """``(last_seq, last_hash)``; ``(0, GENESIS_HASH)`` for an empty chain."""
        raise NotImplementedError

    def receipt_count(self) -> int:
        raise NotImplementedError

    def receipts(self, after_seq: int = 0, limit: int | None = None) -> list[Receipt]:
        """Receipts with ``seq > after_seq`` in ascending order."""
        raise NotImplementedError

    def iter_receipts(self, batch: int = 1000) -> Iterator[Receipt]:
        """All receipts ascending, streamed in batches (for verify/export of long chains)."""
        raise NotImplementedError

    def verify_chain(self) -> tuple[bool, int | None]:
        """Re-walk the whole chain with ``hashing.verify_receipts`` -> ``(ok, first_bad_seq)``."""
        raise NotImplementedError

    def export_receipts(self, path: str | os.PathLike[str]) -> int:
        """Write all receipts as JSONL (one ``Receipt.to_dict()`` per line, ascending); return count."""
        raise NotImplementedError

    # ------------------------------------------------------------------ records
    def record_candidate(self, candidate: TokenCandidate) -> None:
        """Upsert by mint (keeps ``first_seen``). No receipt (too noisy)."""
        raise NotImplementedError

    def record_safety(self, report: SafetyReport) -> None:
        """Append a safety report row. No receipt (the decision that uses it is receipted)."""
        raise NotImplementedError

    def record_decision(self, decision: Decision) -> Decision:
        """Insert + ``decision`` receipt atomically; returns a copy with ``receipt_hash`` set."""
        raise NotImplementedError

    def record_fill(self, fill: Fill) -> Fill:
        """Insert + ``fill`` receipt atomically; returns a copy with ``receipt_hash`` set.

        Raises :class:`LedgerError` if ``fill.id`` already exists.
        """
        raise NotImplementedError

    def record_swap_failure(self, payload: dict[str, Any]) -> Receipt:
        """``swap_failed`` receipt (quote summary, error, outcome 'failed'|'unknown')."""
        raise NotImplementedError

    def upsert_position(self, position: Position) -> None:
        """Insert or replace by id (positions change over time; fills/receipts are the audit trail)."""
        raise NotImplementedError

    def get_position(self, position_id: str) -> Position | None:
        raise NotImplementedError

    def open_positions(self) -> list[Position]:
        """Open positions ordered by ``opened_at``."""
        raise NotImplementedError

    def positions(self, status: str | None = None, limit: int | None = None) -> list[Position]:
        """Positions newest first, optionally filtered by status."""
        raise NotImplementedError

    def last_closed_at(self, mint: str) -> float | None:
        """Most recent ``closed_at`` of a position in ``mint`` (cooldown)."""
        raise NotImplementedError

    def fills(self, limit: int | None = 50, mint: str | None = None, since: float | None = None,
              position_id: str | None = None) -> list[Fill]:
        """Fills newest first with optional filters."""
        raise NotImplementedError

    def decisions(self, limit: int = 50, actions: Sequence[str] | None = None) -> list[Decision]:
        """Decisions newest first, optionally filtered by action."""
        raise NotImplementedError

    def decision_counts(self, since: float | None = None) -> dict[str, int]:
        """``{action: count}`` (dashboard rejection summary)."""
        raise NotImplementedError

    def record_equity(self, point: EquityPoint) -> None:
        raise NotImplementedError

    def equity_series(self, since: float | None = None, limit: int | None = None) -> list[EquityPoint]:
        """Equity points ascending by ts (downsampling is the caller's job)."""
        raise NotImplementedError

    def latest_equity(self) -> EquityPoint | None:
        raise NotImplementedError
