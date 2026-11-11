"""Adversarial observational parity with the pinned pre-grouping scorecard."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

import pytest
from test_speeddesk_scorecard_grouping import BASELINE, DAY, add, desk, result

from nightcrawler.speeddesk_live import Intent, KalshiLiveDesk
from nightcrawler.speeddesk_live_model import LiveIntent, LiveRiskBook

A, B = "KXBTC15M-a", "KXBTC15M-b"


def caught(function: Callable[..., Any], out: KalshiLiveDesk) -> BaseException:
    try:
        function(out, DAY)
    except Exception as exc:  # noqa: BLE001 - the original exception object is the contract.
        return exc
    raise AssertionError("expected original business failure")


def test_reservation_property_failure_preserves_exact_exception_and_read_order() -> None:
    failure = LookupError("original reservation failure")

    def build() -> tuple[KalshiLiveDesk, list[str]]:
        out, reads = desk(), []

        class Reservation(LiveIntent):
            def __getattribute__(self, name: str) -> Any:
                if name == "reservation_active":
                    reads.append("reservation")
                    raise failure
                return super().__getattribute__(name)

        add(out, "first", A)
        out.book.intents["first"] = Reservation(**dataclasses.asdict(out.book.intents["first"]))
        return out, reads

    current, current_reads = build()
    baseline, baseline_reads = build()
    assert caught(KalshiLiveDesk.scorecard, current) is failure
    assert caught(BASELINE, baseline) is failure
    assert current_reads == baseline_reads == ["reservation"]


@pytest.mark.parametrize("field", ["window", "client_order_id", "terminal", "uncertain"])
def test_unreachable_malformed_intent_remains_unobserved(field: str) -> None:
    def build() -> KalshiLiveDesk:
        out = desk()
        out.book.windows.pop(B)
        add(out, "first", A, terminal=False, missing=True)
        add(out, "unreachable", A, missing=True)
        delattr(out.intents["unreachable"], field)
        return out

    assert result(KalshiLiveDesk.scorecard, build()) == result(BASELINE, build())


@pytest.mark.parametrize("where", ["uncertain", "reservation", "book_key"])
def test_exotic_predicate_mutation_uses_fresh_window_values_in_original_order(where: str) -> None:
    def build() -> tuple[KalshiLiveDesk, list[str]]:
        out, calls = desk(), []
        add(out, "first", A)
        add(out, "moved", A, terminal=False, missing=True)

        class MoveOnTruth:
            def __bool__(self) -> bool:
                calls.append("truth")
                out.intents["moved"].window = B
                return False

        class MoveOnEquality(str):
            def __hash__(self) -> int:
                calls.append("hash")
                return super().__hash__()

            def __eq__(self, other: object) -> bool:
                calls.append("equality")
                out.intents["moved"].window = B
                return super().__eq__(other)

        if where == "uncertain":
            out.intents["first"].uncertain = MoveOnTruth()  # type: ignore[assignment]
        elif where == "reservation":
            out.book.intents["first"].reservation_active = MoveOnTruth()  # type: ignore[assignment]
        else:
            out.book.intents = {MoveOnEquality("first"): out.book.intents["first"]}
        calls.clear()
        return out, calls

    current, current_calls = build()
    baseline, baseline_calls = build()
    assert result(KalshiLiveDesk.scorecard, current) == result(BASELINE, baseline)
    assert current_calls == baseline_calls
    assert current.evidence.last_coverage == {A: True, B: None}


def test_integrity_truth_is_called_only_in_original_window_order() -> None:
    failure = ArithmeticError("second integrity check")

    def build() -> tuple[KalshiLiveDesk, list[int]]:
        out, calls = desk(), []

        class ChangingIntegrity:
            def __bool__(self) -> bool:
                calls.append(len(calls) + 1)
                if len(calls) == 2:
                    raise failure
                return False

        out.book.integrity_error = ChangingIntegrity()  # type: ignore[assignment]
        return out, calls

    current, current_calls = build()
    baseline, baseline_calls = build()
    assert caught(KalshiLiveDesk.scorecard, current) is failure
    assert caught(BASELINE, baseline) is failure
    assert current_calls == baseline_calls == [1, 2]


def test_exotic_book_has_no_additional_property_reads() -> None:
    def build() -> tuple[KalshiLiveDesk, list[str]]:
        out, calls = desk(), []

        class ObservedBook(LiveRiskBook):
            def __getattribute__(self, name: str) -> Any:
                if name in ("integrity_error", "intents"):
                    calls.append(name)
                return super().__getattribute__(name)

        book = ObservedBook()
        book.__dict__.update(vars(out.book))
        out.book = book
        calls.clear()
        return out, calls

    current, current_calls = build()
    baseline, baseline_calls = build()
    assert result(KalshiLiveDesk.scorecard, current) == result(BASELINE, baseline)
    assert current_calls == baseline_calls == ["integrity_error", "integrity_error"]


def test_native_aliases_and_distinct_mapping_keys_keep_client_id_lookup_semantics() -> None:
    def build() -> KalshiLiveDesk:
        out = desk()
        out.book.windows["duplicate-a"] = dataclasses.replace(out.book.windows[A])
        add(out, "client-id", A)
        intent = out.intents.pop("client-id")
        out.intents["different-mapping-key"] = intent
        out.intents["same-object-again"] = intent
        out.book.intents["client-id"].reservation_active = True
        return out

    current, baseline = build(), build()
    assert result(KalshiLiveDesk.scorecard, current) == result(BASELINE, baseline)
    assert current.evidence.last_coverage == {A: None, B: True}


def test_intent_subclass_property_raises_original_exception_without_guard_access() -> None:
    failure = ValueError("window property failure")

    def build() -> tuple[KalshiLiveDesk, list[str]]:
        out, calls = desk(), []

        class FaultyIntent(Intent):
            def __getattribute__(self, name: str) -> Any:
                if name == "window":
                    calls.append(name)
                    raise failure
                return super().__getattribute__(name)

        add(out, "first", A)
        out.intents["first"] = FaultyIntent(**dataclasses.asdict(out.intents["first"]))
        return out, calls

    current, current_calls = build()
    baseline, baseline_calls = build()
    assert caught(KalshiLiveDesk.scorecard, current) is failure
    assert caught(BASELINE, baseline) is failure
    assert current_calls == baseline_calls == ["window"]
