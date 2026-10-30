"""Hash-chain primitives for hindsight-proof receipts (foundation, shared).

Receipt hash (the contract every verifier must reproduce)::

    body = canonical_json({"seq": seq, "ts": ts, "kind": kind, "payload": payload})
    hash = sha256((prev_hash + body).encode("utf-8")).hexdigest()

* ``canonical_json`` = ``json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)``
  (``ensure_ascii`` left at its default ``True``).
* ``seq`` starts at 1 and increments by exactly 1.
* ``prev_hash`` of seq 1 is :data:`GENESIS_HASH` (64 zeros).
* ``ts`` is epoch seconds UTC rounded to milliseconds (``round(ts, 3)``).
* ``payload`` MUST be JSON-native (dict/list/str/int/float/bool/None). Pass it
  through :func:`normalize_payload` before hashing *and* storing, so that what
  is stored is byte-for-byte what was hashed (tuples become lists, unknown
  objects become ``str(obj)``). Floats must be finite (no NaN/inf).

:mod:`nightcrawler.ledger` owns storage; this module only defines the math so
the CLI ``receipts verify`` command, the dashboard and external auditors share
one implementation.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Iterable, Mapping

__all__ = [
    "GENESIS_HASH",
    "canonical_json",
    "normalize_payload",
    "receipt_hash",
    "verify_receipts",
]

GENESIS_HASH = "0" * 64


def canonical_json(obj: Any) -> str:
    """Deterministic JSON text used for hashing (see module docstring)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _check_finite(obj: Any) -> None:
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise ValueError("receipt payloads must not contain NaN or infinity")
    elif isinstance(obj, dict):
        for v in obj.values():
            _check_finite(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _check_finite(v)


def _str_keys(obj: Any) -> Any:
    """Copy with every dict key turned into ``str`` (JSON does that anyway, but ``sort_keys``
    cannot compare a mix of int and str keys)."""
    if isinstance(obj, dict):
        return {str(k): _str_keys(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_str_keys(v) for v in obj]
    return obj


def normalize_payload(payload: Any) -> Any:
    """Round-trip ``payload`` through canonical JSON.

    Returns the JSON-native structure that will be hashed and stored.
    Raises ``ValueError`` on NaN/inf floats (they are not portable JSON).
    Dict keys become strings first (so a mix of int and str keys is fine).
    Dataclasses should be converted first with ``models.to_jsonable``;
    otherwise ``default=str`` turns them into their ``repr`` string.
    """
    _check_finite(payload)
    return json.loads(canonical_json(_str_keys(payload)))


def receipt_hash(prev_hash: str, seq: int, ts: float, kind: str, payload: Any) -> str:
    """sha256 hex digest of ``prev_hash + canonical_json({seq, ts, kind, payload})``."""
    body = canonical_json({"seq": seq, "ts": ts, "kind": kind, "payload": payload})
    return hashlib.sha256((prev_hash + body).encode("utf-8")).hexdigest()


def verify_receipts(receipts: Iterable[Mapping[str, Any]] | Iterable[Any]) -> tuple[bool, int | None]:
    """Re-walk a chain in seq order.

    ``receipts`` yields mappings or objects with ``seq, ts, kind, payload,
    prev_hash, hash``. Returns ``(True, None)`` when every link and hash checks
    out (an empty chain is valid), else ``(False, first_bad_seq)``: the
    expected seq where numbering breaks (gap/duplicate/reorder), or the first
    receipt whose ``prev_hash`` or ``hash`` does not match.
    """
    expected_prev = GENESIS_HASH
    expected_seq = 1
    for r in receipts:
        get: Any = r.get if isinstance(r, Mapping) else (lambda k, _r=r: getattr(_r, k))
        seq = get("seq")
        if seq != expected_seq:  # gap, duplicate or reordering: the chain breaks here
            return False, expected_seq
        if get("prev_hash") != expected_prev:
            return False, seq
        h = receipt_hash(get("prev_hash"), seq, get("ts"), get("kind"), get("payload"))
        if h != get("hash"):
            return False, seq
        expected_prev = h
        expected_seq += 1
    return True, None
