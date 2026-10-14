"""Pin existing serializer/storage behavior before any scalar fast-path change."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path, PurePath
from typing import Any

import pytest
from fakes import FakeClock

from nightcrawler.hashing import GENESIS_HASH, canonical_json, normalize_payload
from nightcrawler.ledger import Ledger
from nightcrawler.models import to_jsonable


@pytest.mark.parametrize("value", [None, False, True, 0, -(2**100), 2**100, .125, -0.0,
                                   "", "Ω snowman ☃\x00\n", float("nan"), float("inf"), -float("inf")])
def test_native_scalars_keep_identity_without_normalizing_values(value: Any) -> None:
    assert to_jsonable(value) is value
    if isinstance(value, float) and value == 0:
        assert math.copysign(1, to_jsonable(value)) == -1


def test_primitive_subclasses_keep_identity_but_enums_still_convert() -> None:
    class Number(int):
        pass

    class Real(float):
        pass

    class Text(str):
        pass

    class NumericEnum(IntEnum):
        ONE = 1

    class TextEnum(str, Enum):
        READY = "ready"

    values = [Number(7), Real(-0.0), Text("Ω")]
    result = to_jsonable(values)
    assert result is not values
    assert all(converted is original for converted, original in zip(result, values, strict=True))
    assert to_jsonable(NumericEnum.ONE) is NumericEnum.ONE.value
    assert to_jsonable(TextEnum.READY) is TextEnum.READY.value


def test_dataclass_string_subclass_is_a_record_and_nested_paths_convert() -> None:
    @dataclass
    class Label(str):
        label: str

    @dataclass
    class Record:
        label: Label
        paths: tuple[PurePath, ...]
        flag: bool

    value = Record(Label("tag"), (Path("relative/file"), PurePath("other")), True)
    assert to_jsonable(value) == {"label": {"label": "tag"}, "paths": ["relative/file", "other"], "flag": True}
    assert to_jsonable(Record) is Record  # A dataclass definition is not an instance.


@pytest.mark.parametrize("behavior", ["unhashable", "hash_raises", "equality_raises"])
def test_unknown_instance_never_hashes_or_compares_its_metaclass(behavior: str) -> None:
    consulted: list[str] = []

    class Meta(type):
        def __hash__(cls) -> int:
            consulted.append("hash")
            if behavior == "hash_raises":
                raise AssertionError("Class hashing is not part of value conversion")
            return hash(int)  # Force a collision if someone uses a set of builtin types.

        def __eq__(cls, other: object) -> bool:
            consulted.append("equality")
            raise AssertionError("Class equality is not part of value conversion")

    if behavior == "unhashable":
        Meta.__hash__ = None  # type: ignore[assignment]

    class Unknown(metaclass=Meta):
        pass

    item = Unknown()
    result = to_jsonable({"item": item})
    assert result["item"] is item
    assert consulted == []


def test_dictionary_key_conversion_collision_and_container_copy_contract() -> None:
    class Key:
        def __str__(self) -> str:
            return "named"

    item = object()
    original = {1: "first", "1": "last", Key(): (item, {2, 3}, frozenset({4, 5}))}
    converted = to_jsonable(original)
    assert list(converted) == ["1", "named"]
    assert converted["1"] == "last"
    assert isinstance(converted["named"], list)
    assert converted["named"][0] is item
    assert set(converted["named"][1]) == {2, 3}
    assert set(converted["named"][2]) == {4, 5}
    assert original[1] == "first"
    converted["named"].append("new")
    assert len(original[next(key for key in original if isinstance(key, Key))]) == 3


def test_unknown_object_and_enum_value_are_not_recursively_reinterpreted() -> None:
    class ContainerEnum(Enum):
        PAYLOAD = {1: (2, 3)}  # noqa: RUF012 - deliberately pin non-recursive enum-value conversion.

    unknown = object()
    raw_bytes = b"bytes"
    assert to_jsonable(unknown) is unknown
    assert to_jsonable(raw_bytes) is raw_bytes
    assert to_jsonable(ContainerEnum.PAYLOAD) is ContainerEnum.PAYLOAD.value
    assert isinstance(to_jsonable(ContainerEnum.PAYLOAD)[1], tuple)


@pytest.mark.parametrize("kind", ["list", "dict", "dataclass"])
def test_cycles_preserve_recursion_failure(kind: str) -> None:
    @dataclass
    class Node:
        child: Any = None

    value: Any
    if kind == "list":
        value = []
        value.append(value)
    elif kind == "dict":
        value = {}
        value["self"] = value
    else:
        value = Node()
        value.child = value
    with pytest.raises(RecursionError):
        to_jsonable(value)


def test_failed_key_conversion_preserves_exception_identity() -> None:
    failure = ValueError("synthetic key conversion failure")

    class Key:
        def __str__(self) -> str:
            raise failure

    with pytest.raises(ValueError) as caught:
        to_jsonable({Key(): 1})
    assert caught.value is failure


def test_ledger_bytes_receipt_hash_and_reopened_values_remain_exact(tmp_path: Path) -> None:
    @dataclass
    class Payload:
        text: str
        amount: int
        negative_zero: float
        items: tuple[Any, ...]

    value = Payload("Ω", 2**100, -0.0, (None, True, Path("relative")))
    expected = {"text": "Ω", "amount": 2**100, "negative_zero": -0.0, "items": [None, True, "relative"]}
    path = tmp_path / "serialization.db"
    stamp = 1_700_000_000.125
    with Ledger(path, clock=FakeClock()) as ledger:
        with ledger.transaction():
            ledger.set_kv("state", value)
            receipt = ledger.append_receipt("serialization_probe", to_jsonable(value), ts=stamp)
        expected_body = json.dumps({"seq": 1, "ts": stamp, "kind": "serialization_probe", "payload": expected},
                                   sort_keys=True, separators=(",", ":"))
        assert receipt.hash == hashlib.sha256((GENESIS_HASH + expected_body).encode()).hexdigest()
        assert ledger.verify_chain() == (True, None)
    with sqlite3.connect(path) as connection:
        raw = connection.execute("SELECT value FROM kv WHERE key = 'state'").fetchone()[0]
    assert raw == json.dumps(expected, separators=(",", ":"))
    with Ledger(path, clock=FakeClock()) as reopened:
        assert reopened.get_kv("state") == expected
        assert math.copysign(1, reopened.get_kv("state")["negative_zero"]) == -1
        assert reopened.receipts() == [receipt]
        assert reopened.verify_chain() == (True, None)


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_kv_stays_permitted_but_receipt_rejection_rolls_back(tmp_path: Path, nonfinite: float) -> None:
    path = tmp_path / "nonfinite.db"
    converted = to_jsonable({"nested": [nonfinite]})
    assert converted["nested"][0] is nonfinite
    with Ledger(path, clock=FakeClock()) as ledger:
        ledger.set_kv("baseline", converted)
        retained = ledger.get_kv("baseline")["nested"][0]
        assert math.isnan(retained) if math.isnan(nonfinite) else retained == nonfinite
        before = ledger.head()
        with pytest.raises(ValueError), ledger.transaction():
            ledger.set_kv("new", {"ok": True})
            ledger.append_receipt("would_rollback", {"ok": True})
            ledger.append_receipt("invalid", converted)
        assert ledger.get_kv("new") is None
        assert ledger.head() == before
        assert ledger.verify_chain() == (True, None)
    with pytest.raises(ValueError):
        normalize_payload(converted)
    assert "NaN" in canonical_json(converted) if math.isnan(nonfinite) else "Infinity" in canonical_json(converted)


def test_unknown_value_string_failure_does_not_leave_partial_ledger_commit(tmp_path: Path) -> None:
    failure = RuntimeError("synthetic unknown object cannot stringify")

    class Unknown:
        def __str__(self) -> str:
            raise failure

    item = Unknown()
    assert to_jsonable(item) is item
    with Ledger(tmp_path / "rollback.db", clock=FakeClock()) as ledger:
        ledger.set_kv("stable", 7)
        with pytest.raises(RuntimeError) as caught, ledger.transaction():
            ledger.set_kv("stable", 8)
            ledger.append_receipt("would_rollback", {"known": 1})
            ledger.set_kv("invalid", {"value": item})
        assert caught.value is failure
        assert ledger.get_kv("stable") == 7
        assert ledger.get_kv("invalid") is None
        assert ledger.head() == (0, GENESIS_HASH)
        assert ledger.verify_chain() == (True, None)
