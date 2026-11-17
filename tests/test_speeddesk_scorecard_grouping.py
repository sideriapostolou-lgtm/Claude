"""Compare local scorecard grouping with the immutable pre-change method."""
from __future__ import annotations

import copy
import dataclasses
import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import nightcrawler.speeddesk_live as live_module
from nightcrawler.speeddesk_live import Intent, KalshiLiveDesk
from nightcrawler.speeddesk_live_model import LiveIntent, LiveRiskBook
from nightcrawler.speeddesk_model import PracticeDesk, Window

BASE = '1ef0f9270c079ca29b6074360918838fe26f8cff'
ROOT = Path(__file__).resolve().parents[1]
# Exact scorecard method from BASE; no historical Git object is needed to run tests.
SOURCE = (ROOT / 'tests/fixtures/speeddesk_scorecard_baseline.py.txt').read_text()
assert hashlib.sha256(SOURCE.encode()).hexdigest() == '25d1270b5eb2c2ebaa29ad80ebb02df7cfa3d2dd020015ee5684e006c5e90f79'
NAMESPACE = dict(vars(live_module))
exec(compile(SOURCE, '<pinned-scorecard>', 'exec'), NAMESPACE)  # noqa: S102 - frozen local baseline.
BASELINE = NAMESPACE['scorecard']
NOW = 1792016160.0
DAY = '2026-10-14'


class Evidence:
    def __init__(self) -> None:
        self.fills: list[Any] = []
        self.last_coverage: dict[str, bool | None] = {}

    def coverage(self, windows: list[dict[str, Any]]) -> dict[str, bool | None]:
        self.last_coverage = {w['slug']: True for w in windows}
        return self.last_coverage

    def complete_kalshi_day(self, *_args: Any) -> bool:
        return False

    def availability(self, _windows: Any) -> dict[str, Any]:
        return {}


def desk() -> KalshiLiveDesk:
    out = object.__new__(KalshiLiveDesk)
    out.clock = lambda: NOW
    out.book = LiveRiskBook()
    for slug in ('KXBTC15M-a', 'KXBTC15M-b'):
        out.book.add_window(Window(slug, NOW - 1000, NOW - 100, 80000, venue='kalshi'))
    out.twin = PracticeDesk()
    out.evidence = Evidence()  # type: ignore[assignment]
    out.intents = {}
    out.ledger = SimpleNamespace(receipts=[])
    return out


def add(out: KalshiLiveDesk, key: str, slug: str, *, terminal: bool = True,
        uncertain: bool = False, reservation: bool = False, missing: bool = False) -> None:
    out.intents[key] = Intent(key, slug, 'up', 'rest', .4, 1, .5, NOW - 900,
                              terminal=terminal, uncertain=uncertain)
    if not missing:
        out.book.intents[key] = LiveIntent(key, slug, 'up', 'rest', .4, 1, NOW - 900, .4,
                                          reservation_active=reservation)


def result(fn: Any, out: KalshiLiveDesk, *, twin: bool = False) -> Any:
    try:
        return ('ok', fn(out, DAY, twin=twin), out.evidence.last_coverage, out.ledger.receipts)
    except Exception as exc:  # noqa: BLE001 - compare exact baseline error and state.
        return ('error', type(exc), exc.args, out.evidence.last_coverage, out.ledger.receipts)


@pytest.mark.parametrize('case', ['terminal', 'active', 'uncertain', 'reserved', 'missing',
    'unrelated_missing', 'early_active', 'window_error_order', 'interleaved'])
def test_native_decisions_and_lazy_errors_match_pinned_method(case: str) -> None:
    out = desk()
    if case == 'interleaved':
        for key, slug in (('b0', 'KXBTC15M-b'), ('a0', 'KXBTC15M-a'), ('b1', 'KXBTC15M-b'), ('a1', 'KXBTC15M-a')):
            add(out, key, slug, reservation=key == 'b1')
    elif case == 'window_error_order':
        add(out, 'b-missing', 'KXBTC15M-b', missing=True)
        add(out, 'a-missing', 'KXBTC15M-a', missing=True)
    elif case == 'early_active':
        add(out, 'first', 'KXBTC15M-a', terminal=False, missing=True)
        add(out, 'later', 'KXBTC15M-a', missing=True)
    elif case == 'unrelated_missing':
        add(out, 'other', 'unrelated', missing=True)
    else:
        add(out, 'first', 'KXBTC15M-a', terminal=case != 'active', uncertain=case == 'uncertain',
            reservation=case == 'reserved', missing=case == 'missing')
    reference = copy.deepcopy(out)
    before = (copy.deepcopy(out.book.to_state()), copy.deepcopy(out.intents))
    assert result(KalshiLiveDesk.scorecard, out) == result(BASELINE, reference)
    assert (out.book.to_state(), out.intents) == before


def test_mutations_rebind_and_same_length_updates_are_fresh_each_call() -> None:
    out = desk()
    add(out, 'first', 'KXBTC15M-a')
    for mutate in (
        lambda: None,
        lambda: setattr(out.intents['first'], 'terminal', False),
        lambda: setattr(out.intents['first'], 'window', 'KXBTC15M-b'),
        lambda: setattr(out.intents['first'], 'terminal', True),
        lambda: setattr(out.book.intents['first'], 'reservation_active', True),
        lambda: out.intents.__setitem__('first', dataclasses.replace(out.intents['first'], window='KXBTC15M-a')),
        lambda: setattr(out, 'intents', dict(out.intents)),
        lambda: out.intents.clear(),
    ):
        mutate()
        assert result(KalshiLiveDesk.scorecard, out) == result(BASELINE, copy.deepcopy(out))


class Unscannable(dict[str, Intent]):
    def values(self) -> Any:
        raise AssertionError('intents must not be inspected')


@pytest.mark.parametrize('case', ['twin', 'no_windows', 'integrity'])
def test_short_circuits_do_not_touch_intents(case: str) -> None:
    out = desk()
    out.intents = Unscannable()
    if case == 'no_windows':
        out.book.windows.clear()
    if case == 'integrity':
        out.book.integrity_error = 'latched'
    assert result(KalshiLiveDesk.scorecard, out, twin=case == 'twin') == result(
        BASELINE, copy.deepcopy(out), twin=case == 'twin')


@pytest.mark.parametrize('kind', ['slug', 'intent', 'mapping', 'key', 'truth', 'book'])
def test_exotic_hooks_match_original_without_new_hash_or_property_calls(kind: str) -> None:
    def build() -> tuple[KalshiLiveDesk, list[str]]:
        out, calls = desk(), []
        class HookStr(str):
            def __hash__(self) -> int:
                calls.append('hash')
                return super().__hash__()
            def __eq__(self, other: object) -> bool:
                calls.append('eq')
                return super().__eq__(other)
        class HookIntent(Intent):
            def __getattribute__(self, name: str) -> Any:
                if name in ('window', 'terminal', 'uncertain'):
                    calls.append(name)
                return super().__getattribute__(name)
        class HookMap(dict[str, Intent]):
            def values(self) -> Any:
                calls.append('values')
                return super().values()
        class HookTruth:
            def __bool__(self) -> bool:
                calls.append('bool')
                return False
        add(out, 'first', 'KXBTC15M-a')
        if kind == 'slug':
            out.intents['first'].window = HookStr('KXBTC15M-a')
        elif kind == 'intent':
            out.intents['first'] = HookIntent(**dataclasses.asdict(out.intents['first']))
        elif kind == 'mapping':
            out.intents = HookMap(out.intents)
        elif kind == 'key':
            out.book.intents = {HookStr('first'): out.book.intents['first']}
        elif kind == 'truth':
            out.intents['first'].uncertain = HookTruth()  # type: ignore[assignment]
        elif kind == 'book':
            out.book = SimpleNamespace(**vars(out.book))  # type: ignore[assignment]
        calls.clear()
        return out, calls
    out, actual_calls = build()
    reference, reference_calls = build()
    assert result(KalshiLiveDesk.scorecard, out) == result(BASELINE, reference)
    assert actual_calls == reference_calls
