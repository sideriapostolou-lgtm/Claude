"""Offline, interleaved actual-child benchmark. No clients, production data or orders.

Run from the repository with PYTHONPATH=src and the verified dev venv. Baseline
source is exported from the immutable base into a temporary directory, never
installed or used in production. Fake clocks and in-memory log sinks are explicit.
"""
from __future__ import annotations

import gc
import hashlib
import importlib.util
import json
import logging
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from nightcrawler import kalshi_arena as current
from nightcrawler.speeddesk_model import Window

BASE = '3ce8a0b92f53916768a3e1c09cac700281d3c1cd'
TRIALS = 45


class Sink(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def size(value: Any, seen: set[int] | None = None) -> int:
    seen = set() if seen is None else seen
    if id(value) in seen:
        return 0
    seen.add(id(value))
    total = sys.getsizeof(value)
    if isinstance(value, dict):
        total += sum(size(k, seen) + size(v, seen) for k, v in value.items())
    elif isinstance(value, (list, tuple, set, frozenset)):
        total += sum(size(v, seen) for v in value)
    return total


def setup(module: Any, directory: Path, enabled: bool, count: int) -> tuple[Any, Any, list[float]]:
    clock = [900.0]
    view = module.WireView()
    view.bitcoin_price, view.sigma, view.bitcoin_at = 100.0, .001, 900.0
    town = module.KalshiArena(module.ArenaConfig(directory, population=12), lambda: view, clock=lambda: clock[0])
    if not enabled and hasattr(town, '_diagnostic'):
        town._diagnostic = None
    view.windows = tuple(Window((f'KXBTC15M-bench-{i}-'+'x'*128)[:128], 1000+i, 1900+i, 100, venue='kalshi') for i in range(count))
    # Suppress disk work and resident evaluation equally, without monkeypatching step.
    town.dirty = False
    town.saved_at = town.status_at = 900.0
    town.step(900.0)
    clock[0] = view.bitcoin_at = 1100.0
    town.saved_at = town.status_at = 1100.0
    for resident in town.residents.values():
        resident.last_eval = 1100.0
    if hasattr(town, '_diagnostic_frame'):
        town._diagnostic_frame = (10**15, 1099.123456789, 1099.567891234)
    town.feed_gap(tuple(w.slug for w in view.windows), False, False)
    town.step(1100.0)
    assert len(town.learning.pending) == count
    return town, view, clock


def quantiles(rows: list[float]) -> dict[str, float]:
    ordered = sorted(rows)
    return {'median_ms': statistics.median(rows), 'p95_ms': ordered[int(.95*(len(rows)-1))], 'max_ms': max(rows)}


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    target = Path(__file__).with_name('BENCHMARK.json')
    source = (root/'src/nightcrawler/kalshi_arena.py').read_bytes()
    sink = Sink()
    logger = logging.getLogger('nightcrawler.kalshi_arena')
    old_handlers, old_level, old_propagate = logger.handlers[:], logger.level, logger.propagate
    logger.handlers, logger.propagate, logger.level = [sink], False, logging.INFO
    logging.getLogger('nightcrawler.kalshi_online_learning').setLevel(logging.CRITICAL)
    results: dict[str, Any] = {}
    max_bytes = max_retained = 0
    try:
        with tempfile.TemporaryDirectory(prefix='kalshi-diagnostic-bench-') as temp:
            directory = Path(temp)
            base_path = directory/'arena_base.py'
            base_path.write_bytes(subprocess.check_output(['git','show',BASE+':src/nightcrawler/kalshi_arena.py'],cwd=root))
            spec = importlib.util.spec_from_file_location('nightcrawler._diagnostic_base',base_path)
            assert spec is not None and spec.loader is not None
            baseline = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = baseline
            spec.loader.exec_module(baseline)
            for scenario in ('normal_gap', 'burst_due'):
                for count in (1, 32):
                    samples = {key: [] for key in ('base','disabled','enabled')}
                    for trial in range(TRIALS):
                        variants = ['base','disabled','enabled']
                        if trial % 2:
                            variants.reverse()
                        for variant in variants:
                            module = baseline if variant=='base' else current
                            town, view, clock = setup(module,directory/f'{scenario}-{count}-{trial}-{variant}',variant=='enabled',count)
                            at = 1101.0 if scenario=='normal_gap' else 1331.0
                            clock[0] = view.bitcoin_at = at
                            town.saved_at = town.status_at = at
                            for resident in town.residents.values():
                                resident.last_eval = at
                            if scenario=='normal_gap':
                                town.feed_gap(tuple(w.slug for w in view.windows), False, False)
                            sink.messages.clear()
                            gc.collect()
                            cpu0, wall0 = time.process_time_ns(), time.perf_counter_ns()
                            town.step(at)
                            cpu, wall = time.process_time_ns()-cpu0, time.perf_counter_ns()-wall0
                            samples[variant].append({'cpu_ms':cpu/1e6,'wall_ms':wall/1e6})
                            if variant=='enabled':
                                diag = town._diagnostic
                                max_retained = max(max_retained,size(vars(diag)))
                                messages=[m.split(' ',1)[1] for m in sink.messages if m.startswith('kalshi_learning_input_diagnostic ')]
                                max_bytes=max(max_bytes,max((len(m.encode()) for m in messages),default=0))
                                if scenario=='burst_due':
                                    assert len(messages)==count,(len(messages),count)
                    key=f'{scenario}_{count}'
                    results[key]={'samples':samples,'distribution':{v:{k:quantiles([r[k] for r in rows]) for k in ('cpu_ms','wall_ms')} for v,rows in samples.items()}}
            normal=results['normal_gap_32']['distribution']
            burst=results['burst_due_32']['distribution']
            normal_delta=normal['enabled']['cpu_ms']['median_ms']-normal['disabled']['cpu_ms']['median_ms']
            burst_delta=burst['enabled']['cpu_ms']['median_ms']-burst['disabled']['cpu_ms']['median_ms']
            old_item=('gap',('x',),False,False)
            context=(10**15,1099.123456789,1099.567891234)
            new_item=(*old_item,context)
            metadata={'per_queued_event_tuple_increment_bytes':sys.getsizeof(new_item)-sys.getsizeof(old_item),'deep_frame_context_bytes':size(context),'sharing':'One immutable context tuple shared by records in a decoded frame. No second queue; worst one context per frame. Not included in diagnostic object size; total depends on original queued frames/events. Parent PENDING_MAX16384 is not a child-inbox RSS proof.'}
            envelope={'maximum_observed_synthetic_json_bytes':max_bytes,'retained_diagnostic_bytes':max_retained,'normal_32_incremental_median_cpu_ms':normal_delta,'burst_32_incremental_median_cpu_ms':burst_delta}
            passed=max_bytes<=8192 and max_retained<=262144 and normal_delta<=2 and burst_delta<=20
            payload={'source_sha256':hashlib.sha256(source).hexdigest(),'base':BASE,'trials_per_variant_scenario':TRIALS,'residents':12,'method':'Actual child step; fake clocks and 1/32synthetic pending windows, interleaved base/disabled/enabled; disk/status/resident evaluation not due; in-memory arena log handler; GC collected before each timed step. Normal scenario drains1gap; burst advances all pending past slot.','measurement':envelope,'queued_metadata':metadata,'predeclared_envelope_passed':passed,'results':results,'limitations':'Local synthetic CPU/wall benchmark with128-character slugs, full finite frame clocks/sequence, first/last effective causes. Maximum JSON size is observed fixture size, not a formal schema upper bound. Diagnostic object size excludes added inbox tuples/frame contexts, reported separately. Does not measure production contention, stdout/backpressure, network, full parent overhead or peak server load; base comparison measures actual unchanged source alongside observerdisabled/enabled. No profit or production latency proof.'}
            target.write_text(json.dumps(payload,indent=2)+'\n')
            print(json.dumps({'file':str(target),'envelope':envelope,'pass':passed}))
            assert passed,envelope
    finally:
        logger.handlers, logger.level, logger.propagate = old_handlers, old_level, old_propagate


if __name__=='__main__':
    main()
