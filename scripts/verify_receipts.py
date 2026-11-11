#!/usr/bin/env python3
"""Verify a nightcrawler receipts export on its own: Python 3 standard library only.

    python3 verify_receipts.py receipts.jsonl [--head HASH]

``nightcrawler receipts export PATH`` writes one receipt per line with ``seq``, ``ts``,
``kind``, ``payload``, ``prev_hash``, ``hash`` and ``body`` - the exact text that was hashed.
The chain rule (docs/DESIGN.md, section 5)::

    body = canonical_json({"seq": seq, "ts": ts, "kind": kind, "payload": payload})
    hash = sha256_hex(prev_hash + body)
    canonical_json(x) = json.dumps(x, sort_keys=True, separators=(",", ":"), default=str)

``seq`` starts at 1 and grows by exactly 1; ``prev_hash`` of seq 1 is 64 zeros. For every
line this script checks, in order: the line is JSON; ``body`` is a JSON object of exactly
``seq, ts, kind, payload``; its ``seq`` is the next number; ``prev_hash`` is the previous
receipt's ``hash``; ``sha256(prev_hash + body) == hash``; ``body`` is canonical JSON; and the
line's own ``seq/ts/kind/payload`` (what people read) say exactly what ``body`` says.
Lines without ``body`` (older exports) are hashed from their fields.

``--head HASH``: a head hash published earlier (dashboard, ``nightcrawler receipts head``)
must be one of the chain's hashes - proof that everything up to it is unchanged. Without
it, a forger who rewrote one receipt and re-linked all later ones would still pass.

Exit codes: 0 chain intact, 1 broken (the first bad receipt is printed), 2 usage/file error.
This file deliberately imports nothing from nightcrawler.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable

GENESIS_HASH = "0" * 64
BODY_KEYS = ("seq", "ts", "kind", "payload")


class Broken(Exception):
    """The chain breaks at ``seq`` (line ``line`` of the file)."""

    def __init__(self, seq: int, line: int, reason: str) -> None:
        super().__init__(reason)
        self.seq, self.line, self.reason = seq, line, reason


def canonical_json(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def check_line(text: str, line: int, seq: int, prev_hash: str) -> str:
    """Verify one exported line as receipt number ``seq``; returns its hash (the next prev_hash)."""
    try:
        row = json.loads(text)
    except ValueError:
        raise Broken(seq, line, "not JSON") from None
    if not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in ("prev_hash", "hash")):
        raise Broken(seq, line, "not a receipt (needs prev_hash and hash)")
    body = row.get("body")
    if body is None:  # an export written before lines carried their hashed text
        if not all(k in row for k in BODY_KEYS):
            raise Broken(seq, line, "not a receipt (needs body, or seq, ts, kind and payload)")
        body = canonical_json({k: row[k] for k in BODY_KEYS})
    if not isinstance(body, str):
        raise Broken(seq, line, "body is not a string")
    try:
        hashed = json.loads(body)
    except ValueError:
        raise Broken(seq, line, "body is not JSON") from None
    if not isinstance(hashed, dict) or sorted(hashed) != sorted(BODY_KEYS):
        raise Broken(seq, line, "body is not a JSON object of exactly seq, ts, kind, payload")
    found = hashed["seq"]
    if type(found) is not int or found != seq:
        raise Broken(seq, line, f"expected seq {seq}, found {found!r} (gap, duplicate or reordering)")
    if row["prev_hash"] != prev_hash:
        raise Broken(seq, line, "prev_hash does not match the previous receipt's hash")
    digest = hashlib.sha256((prev_hash + body).encode("utf-8")).hexdigest()
    if digest != row["hash"]:
        raise Broken(seq, line, f"hash mismatch: sha256(prev_hash + body) = {digest}, the line says {row['hash']}")
    if canonical_json(hashed) != body:
        raise Broken(seq, line, "body is not canonical JSON (sorted keys, no spaces)")
    for key in BODY_KEYS:
        if key in row and canonical_json(row[key]) != canonical_json(hashed[key]):
            raise Broken(seq, line, f"the line's {key} differs from the hashed body")
    return digest


def verify(lines: Iterable[str], published_head: str | None = None) -> tuple[int, str, int | None]:
    """Walk the chain -> ``(receipts, head hash, seq of published_head or None)``; raises :class:`Broken`."""
    count, prev_hash, head_seq = 0, GENESIS_HASH, None
    for line, text in enumerate(lines, start=1):
        if not text.strip():
            continue
        prev_hash = check_line(text, line, count + 1, prev_hash)
        count += 1
        if prev_hash == published_head:
            head_seq = count
    return count, prev_hash, head_seq


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a nightcrawler receipts export (JSONL).")
    parser.add_argument("path", help="file written by `nightcrawler receipts export PATH`")
    parser.add_argument("--head", metavar="HASH", help="a head hash published earlier; it must be in the chain")
    args = parser.parse_args(argv)
    head = args.head.strip().lower() if args.head else None
    try:
        with open(args.path, encoding="utf-8") as fh:
            count, last, head_seq = verify(fh, head)
    except OSError as exc:
        print(f"cannot read {args.path}: {exc.strerror or exc}", file=sys.stderr)
        return 2
    except UnicodeDecodeError:
        print(f"cannot read {args.path}: not UTF-8 text", file=sys.stderr)
        return 2
    except Broken as exc:
        print(f"BROKEN at seq {exc.seq} (line {exc.line}): {exc.reason}")
        intact = f"receipts 1..{exc.seq - 1} are intact" if exc.seq > 1 else "no receipt is intact"
        print(f"{intact}; nothing from seq {exc.seq} on can be trusted")
        return 1
    if head is not None and head_seq is None:
        print(f"BROKEN: published head {head} is not in this chain (history rewritten, or another ledger)")
        return 1
    print(f"OK: {count} receipts, chain intact" + ("" if count else " (empty)"))
    if count:
        print(f"head seq {count} hash {last}")
    if head_seq is not None:
        print(f"published head found at seq {head_seq}: everything up to it is unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
