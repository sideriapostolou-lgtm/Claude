"""Offline paired checkpoint benchmark; never edits repository source or contacts a venue.

Run with the repository's development Python environment:
python research/kalshi_profitability_2026-10-14/checkpoint_scalar_benchmark.py --output-dir /tmp/scalar-benchmark

The source/fixture imports follow the derived repository root. Assertions are
benchmark correctness gates. exec compiles only the pinned Git function and its
explicit three-line candidate; subprocess invokes only local read-only Git.
"""
# ruff: noqa: S102
from __future__ import annotations

import argparse
import ast
import dataclasses
import difflib
import enum
import hashlib
import json
import logging
import platform
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]

from fakes import FakeClock
from test_speeddesk_runtime import LocalFeeds

import nightcrawler.ledger as ledger_module
from nightcrawler import models
from nightcrawler.config import Settings
from nightcrawler.speeddesk import STATE_KEY, SpeedRunner
from nightcrawler.speeddesk_model import Window, utc_day

OUT: Path
PAIRS = 15
BASE_SHA = '0d93fe3c764d2ac743661e681ca1911ec1bf81a9'
MODEL_SOURCE = subprocess.check_output(['git', 'show', f'{BASE_SHA}:src/nightcrawler/models.py'], cwd=ROOT, text=True)
NODE = next(node for node in ast.parse(MODEL_SOURCE).body if isinstance(node, ast.FunctionDef) and node.name == 'to_jsonable')
SOURCE = ast.get_source_segment(MODEL_SOURCE, NODE) + '\n'
baseline_namespace = dict(models.__dict__)
exec(compile(SOURCE, '<immutable-baseline-to-jsonable>', 'exec'), baseline_namespace)
BASELINE = baseline_namespace['to_jsonable']
NEEDLE = '    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):\n'
FASTPATH = (
    '    kind = type(obj)\n'
    '    if obj is None or kind is str or kind is int or kind is float or kind is bool:\n'
    '        return obj\n'
)
assert SOURCE.count(NEEDLE) == 1
CANDIDATE_SOURCE = SOURCE.replace(NEEDLE, FASTPATH + NEEDLE, 1)
namespace = dict(models.__dict__)
exec(compile(CANDIDATE_SOURCE, '<offline-scalar-prototype>', 'exec'), namespace)
CANDIDATE = namespace['to_jsonable']


def install(candidate: bool) -> None:
    function = CANDIDATE if candidate else BASELINE
    models.to_jsonable = ledger_module.to_jsonable = function


def deny_network(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError('offline benchmark attempted a network connection')


socket.create_connection = deny_network
socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
logging.disable(logging.CRITICAL)


class Stop:
    def is_set(self) -> bool:
        return False


def fixture(path: Path) -> tuple[SpeedRunner, FakeClock]:
    start = datetime(2026, 10, 11, tzinfo=UTC).timestamp()
    now = start + 3 * 86400 + 12 * 3600
    clock = FakeClock(now)
    # Freeze only constructor diagnostic session identity. Actual measured spans use the real clock below.
    runner = SpeedRunner(Settings(data_dir=path), Stop(), clock=clock, monotonic=lambda: 0.0, feed_factory=LocalFeeds)
    runner.monotonic = runner.work_trace.monotonic = time.monotonic
    if runner.live is not None:
        runner.live.monotonic = time.monotonic
        runner.live.work_trace.monotonic = time.monotonic
    runner.started_at = start
    runner.metrics.started_at = runner.evidence.started_at = start
    for index in range(288):
        finish = start + (index + 1) * 900
        venue = ('kalshi', 'polymarket_us')[index % 2]
        window = Window(f'KXBTC15M-SYNTHETIC-{index}', finish - 900, finish,
                        80_000.0, venue_start_price=80_000.0, venue=venue)
        runner.desk.add_window(window)
        runner.desk.settle(window.slug, index % 2 == 0, finish)
    # Three days x two venues x two metrics x 3,000 values = exactly 36,000 values.
    for day_index in range(3):
        day = utc_day(start + day_index * 86400)
        runner.observed[day] = 86400.0
        runner.metrics.days[day] = {
            venue: {
                name: {'values': [float(i % 100) / 10 for i in range(3000)],
                       'observations': 3000, 'samples': 3000, 'missing': 0,
                       'invalid': 0, 'errors': 0, 'timeouts': 0}
                for name in ('btc_exchange_to_decision', 'btc_receipt_to_decision')
            } for venue in ('kalshi', 'polymarket_us')
        }
    assert len(runner.desk.closed) == 288
    assert sum(len(bucket['values']) for scopes in runner.metrics.days.values()
               for metrics in scopes.values() for bucket in metrics.values()) == 36000
    return runner, clock


def capture(runner: SpeedRunner) -> dict[str, Any]:
    rows = runner.ledger._rows('SELECT value, updated_at FROM kv WHERE key=?', (STATE_KEY,))
    raw, updated_at = rows[0]
    receipt_rows = [dataclasses.asdict(receipt) for receipt in runner.ledger.receipts()]
    mirror = runner.path.read_text()
    return {'raw': raw, 'decoded': json.loads(raw), 'updated_at': updated_at,
            'receipts': receipt_rows, 'receipts_raw': json.dumps(receipt_rows, separators=(',', ':')),
            'mirror': mirror, 'mirror_decoded': json.loads(mirror),
            'chain': runner.ledger.verify_chain()}


def compatibility() -> dict[str, bool]:
    class IntSubtype(int):
        pass

    class FloatSubtype(float):
        pass

    class StrSubtype(str):
        pass

    class Number(enum.IntEnum):
        ONE = 1

    class Text(enum.StrEnum):
        WORD = 'word'

    class NoHashEquality(type):
        def __hash__(cls) -> int:
            raise AssertionError('type hashing must not be introduced')

        def __eq__(cls, other: object) -> bool:
            raise AssertionError('type equality must not be introduced')

    class Unknown(metaclass=NoHashEquality):
        pass

    class HostileInt(int, metaclass=NoHashEquality):
        pass

    @dataclasses.dataclass
    class Data:
        number: int
        things: tuple[Any, ...]

    unknown = Unknown()
    cases = {
        'native_scalars': [None, True, False, 0, 2**90, -0.0, 'snowman \u2603'],
        'subclasses': [IntSubtype(2), FloatSubtype(2.5), StrSubtype('s'), HostileInt(7)],
        'enums': [Number.ONE, Text.WORD],
        'paths': [Path('/offline/fake/path')],
        'sets_tuples': ({2, 3}, frozenset({4, 5})),
        'dataclasses': Data(3, (Number.ONE, Path('/offline'), {4, 5})),
        'dataclass_class': Data,
        'unknown': unknown,
        'decimal': Decimal('0.123400'),
        'dictionary_key_coercion': {None: 'none', True: 'true', 2.5: 'float'},
    }
    results = {}
    for name, value in cases.items():
        outputs = []
        for candidate in (False, True):
            install(candidate)
            result = models.to_jsonable(value)
            outputs.append((result, json.dumps(result, separators=(',', ':'), default=str)))
        assert outputs[0][1] == outputs[1][1], name
        if name in ('unknown', 'decimal', 'dataclass_class'):
            assert outputs[0][0] is value and outputs[1][0] is value
        if name == 'subclasses':
            assert all(type(a) is type(b) for a, b in zip(outputs[0][0], outputs[1][0]))
        results[name] = True
    for number in (float('nan'), float('inf'), float('-inf')):
        encodings = []
        for candidate in (False, True):
            install(candidate)
            assert models.to_jsonable(number) is number
            encodings.append(ledger_module._dumps({'x': number}))
        assert encodings[0] == encodings[1]
    results['nonfinite_identity_and_generic_serialization'] = True
    cyclic_list: list[Any] = []
    cyclic_list.append(cyclic_list)
    cyclic_dict: dict[str, Any] = {}
    cyclic_dict['self'] = cyclic_dict
    for value in (cyclic_list, cyclic_dict):
        errors = []
        for candidate in (False, True):
            install(candidate)
            try:
                models.to_jsonable(value)
            except RecursionError as error:
                errors.append(type(error).__name__)
        assert errors == ['RecursionError', 'RecursionError']
    results['cycles_keep_recursion_error'] = True
    install(False)
    return results


def main() -> None:
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='Write synthetic results and candidate source outside production data')
    options = parser.parse_args()
    OUT = options.output_dir.resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    equivalence = compatibility()
    paired = []
    digest_pairs = []
    with tempfile.TemporaryDirectory(prefix='exec-delay-scalar-data-', dir=OUT) as directory:
        baseline, baseline_clock = fixture(Path(directory) / 'baseline')
        candidate, candidate_clock = fixture(Path(directory) / 'candidate')
        try:
            # First FULL-synchronous saves and initial report generation are outside steady-state samples.
            for is_candidate, runner, clock in ((False, baseline, baseline_clock), (True, candidate, candidate_clock)):
                install(is_candidate)
                runner.checkpoint(clock.now())
            for iteration in range(PAIRS):
                samples = {}
                output = {}
                order = [False, True] if iteration % 2 == 0 else [True, False]
                for is_candidate in order:
                    runner, clock = (candidate, candidate_clock) if is_candidate else (baseline, baseline_clock)
                    install(is_candidate)
                    runner.record('speeddesk_status', {'at': clock.now(), 'synthetic': True,
                                                       'benchmark_iteration': iteration,
                                                       'summary': [None, True, 1, .25, 'offline']})
                    cpu_start = time.thread_time_ns()
                    wall_start = time.perf_counter_ns()
                    runner.checkpoint(clock.now())
                    wall_end = time.perf_counter_ns()
                    cpu_end = time.thread_time_ns()
                    label = 'candidate' if is_candidate else 'baseline'
                    samples[label] = {'wall_ms': (wall_end - wall_start) / 1e6,
                                      'cpu_ms': (cpu_end - cpu_start) / 1e6}
                    output[label] = capture(runner)
                left, right = output['baseline'], output['candidate']
                for field in ('raw', 'decoded', 'updated_at', 'receipts', 'receipts_raw', 'mirror', 'mirror_decoded', 'chain'):
                    if left[field] != right[field] and field == 'raw':
                        def differences(a: Any, b: Any, path: str = '') -> list[Any]:
                            if isinstance(a, dict) and isinstance(b, dict):
                                return [item for key in a.keys() | b.keys() for item in differences(a.get(key), b.get(key), path + '.' + str(key))]
                            if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
                                return [item for index, (av, bv) in enumerate(zip(a, b)) for item in differences(av, bv, path + '.' + str(index))]
                            return [] if a == b else [(path, a, b)]
                        print('synthetic state differences', differences(left['decoded'], right['decoded'])[:10])
                    assert left[field] == right[field], f'pair {iteration}: {field} differs'
                assert left['chain'] == (True, None)
                digest_pairs.append({'iteration': iteration, 'equal': True,
                                     'state_sha256': hashlib.sha256(left['raw'].encode()).hexdigest(),
                                     'mirror_sha256': hashlib.sha256(left['mirror'].encode()).hexdigest(),
                                     'receipts_sha256': hashlib.sha256(left['receipts_raw'].encode()).hexdigest()})
                paired.append({'iteration': iteration, 'order': ['candidate' if value else 'baseline' for value in order], **samples})
        finally:
            install(False)
            baseline.close()
            candidate.close()
    summary = {}
    for metric in ('wall_ms', 'cpu_ms'):
        baseline_median = statistics.median(row['baseline'][metric] for row in paired)
        candidate_median = statistics.median(row['candidate'][metric] for row in paired)
        summary[metric] = {'baseline_median': baseline_median, 'candidate_median': candidate_median,
                           'paired_delta_median': statistics.median(row['candidate'][metric] - row['baseline'][metric] for row in paired),
                           'median_reduction_pct': 100 * (baseline_median - candidate_median) / baseline_median,
                           'median_paired_reduction_pct': statistics.median(100 * (row['baseline'][metric] - row['candidate'][metric]) / row['baseline'][metric] for row in paired)}
    result = {'synthetic': True, 'no_network': True, 'no_started_threads': True, 'repository_edits': False,
              'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'immutable_baseline_sha': BASE_SHA,
              'python': platform.python_version(), 'pairs': PAIRS, 'fixture': {'settled_empty_windows': 288,
              'metric_values': 36000, 'metric_days': 3, 'venues': 2, 'metrics_per_venue': 2,
              'values_per_bucket': 3000, 'clock': 'fixed fake 2026-10-14 12:00 UTC',
              'timing': 'unprofiled synchronous practice checkpoint; setup/first FULL save outside samples'},
              'baseline_function_sha256': hashlib.sha256(SOURCE.encode()).hexdigest(),
              'candidate_function_sha256': hashlib.sha256(CANDIDATE_SOURCE.encode()).hexdigest(),
              'summary': summary, 'compatibility': equivalence, 'paired_samples': paired,
              'artifact_equalities': digest_pairs,
              'limits': ['Synthetic workload, not production timings or causal attribution.',
                         'Same fixture dimensions as the earlier cProfile run; that script was not preserved, so exact historical fixture identity is unverified.',
                         'Separate identical local ledgers; AB/BA order alternates; no cProfile overhead.',
                         'Only primitive dispatch changes. Nonprimitive branch bodies remain byte-identical.',
                         'Actual production interval attribution gates any source change.']}
    (OUT / 'exec-delay-scalar-results.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    (OUT / 'exec-delay-scalar-candidate.py').write_text(CANDIDATE_SOURCE)
    (OUT / 'exec-delay-scalar-source.patch').write_text(''.join(difflib.unified_diff(SOURCE.splitlines(keepends=True), CANDIDATE_SOURCE.splitlines(keepends=True), fromfile='models.to_jsonable.baseline', tofile='models.to_jsonable.candidate')))
    print(json.dumps({'summary': summary, 'compatibility_cases': len(equivalence),
                      'paired_state_mirror_receipt_equalities': len(digest_pairs),
                      'results': str(OUT / 'exec-delay-scalar-results.json')}, indent=2))


if __name__ == '__main__':
    main()
