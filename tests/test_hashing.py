"""Foundation tests: receipt hash format and chain verification."""

from __future__ import annotations

import hashlib
import math

import pytest

from nightcrawler.hashing import GENESIS_HASH, canonical_json, normalize_payload, receipt_hash, verify_receipts
from nightcrawler.models import Receipt


def build_chain(n: int) -> list[dict]:
    chain, prev = [], GENESIS_HASH
    for seq in range(1, n + 1):
        payload = normalize_payload({"i": seq, "price": 0.0001 * seq, "tags": ("a", "b")})
        ts = round(1_791_475_200.0 + seq * 1.2345, 3)
        h = receipt_hash(prev, seq, ts, "decision", payload)
        chain.append({"seq": seq, "ts": ts, "kind": "decision", "payload": payload, "prev_hash": prev, "hash": h})
        prev = h
    return chain


def test_canonical_json_is_sorted_and_compact() -> None:
    assert canonical_json({"b": 1, "a": [1, 2], "c": {"z": None, "y": True}}) == \
        '{"a":[1,2],"b":1,"c":{"y":true,"z":null}}'
    assert canonical_json({"x": object}) .startswith('{"x":"<class')  # default=str


def test_receipt_hash_matches_documented_formula() -> None:
    payload = {"mint": "abc", "action": "enter"}
    body = '{"kind":"decision","payload":{"action":"enter","mint":"abc"},"seq":1,"ts":1791475200.123}'
    expected = hashlib.sha256((GENESIS_HASH + body).encode()).hexdigest()
    assert receipt_hash(GENESIS_HASH, 1, 1791475200.123, "decision", payload) == expected


def test_normalize_payload() -> None:
    assert normalize_payload({"t": (1, 2)}) == {"t": [1, 2]}
    with pytest.raises(ValueError):
        normalize_payload({"x": math.nan})
    with pytest.raises(ValueError):
        normalize_payload({"x": [math.inf]})


def test_verify_good_chain_and_objects() -> None:
    chain = build_chain(5)
    assert verify_receipts(chain) == (True, None)
    assert verify_receipts([Receipt(**r) for r in chain]) == (True, None)
    assert verify_receipts([]) == (True, None)


@pytest.mark.parametrize("mutate,bad", [
    (lambda c: c[2]["payload"].__setitem__("price", 9.99), 3),  # edited payload (hindsight!)
    (lambda c: c[3].__setitem__("ts", c[3]["ts"] + 1), 4),  # edited time
    (lambda c: c.pop(1), 2),  # deleted receipt -> seq gap
    (lambda c: c[0].__setitem__("hash", "0" * 64), 1),
    (lambda c: c[4].__setitem__("prev_hash", GENESIS_HASH), 5),
])
def test_verify_detects_tampering(mutate, bad) -> None:
    chain = build_chain(5)
    mutate(chain)
    assert verify_receipts(chain) == (False, bad)


def test_normalize_payload_accepts_mixed_int_and_str_keys() -> None:
    from nightcrawler.hashing import normalize_payload

    assert normalize_payload({1: "a", "b": {2: [3]}}) == {"1": "a", "b": {"2": [3]}}
