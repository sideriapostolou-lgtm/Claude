# Exact native-scalar conversion shortcut

Prepared October 14, 2026. This is an execution correction, not a new strategy,
fee rule, fill simulator, risk budget or order authority. EXEC-DELAY-001 remains
open until its post-release evidence gates are met.

## Why this change

The [production measurement receipt](shared_loop_trace_release.json) establishes
that practice checkpoint/ledger work overlaps actual live account-read resumption
gaps. It does not isolate the converter's production CPU or explain all the delay.
At 2:56 PM Pacific a ledger span took 76.078 ms wall /39.415 ms full-span thread CPU;
at 3 PM another took 227.757 ms wall /45.371 ms CPU. Nested work is nonadditive and
substantial time remains uncovered.

The ledger recursively converts the state to JSON-compatible values. Exact native
None/bool/int/float/str values already require no conversion. Return them before
the dataclass/container/enum/path checks. Type identity checks preserve subclass
behavior and never hash/compare an unknown object's metaclass. Every nonprimitive
branch retains its prior behavior. No save is skipped, coalesced, moved to a thread
or reordered. SQLite durability, mirror order and receipt hashes remain intact.

The touched file had existing Ruff findings. Required cleanup sorts the same 37
export names and uses existing future-annotation/Self conventions. Both numeric
int casts remain under narrow RUF046 comments; no currency calculation changed.

## Reproducible offline comparison

[Benchmark script](checkpoint_scalar_benchmark.py) pins the original converter to
Git commit 0d93fe3c764d2ac743661e681ca1911ec1bf81a9, then constructs only the scalar
shortcut in an isolated namespace. It runs no worker threads or network requests;
all ledgers/data directories are temporary. The command requires an explicit
output directory, e.g. with the existing development Python:

```bash
PYTHONPATH=src:tests python research/kalshi_profitability_2026-10-14/checkpoint_scalar_benchmark.py --output-dir /tmp/checkpoint-scalar-benchmark
```

[Exact saved results](checkpoint_scalar_benchmark_results.json): 15 alternating
AB/BA pairs, 288 settled empty synthetic windows and 36,000 metric values. Median
wall 53.192619 -> 39.946575 ms, 24.902% lower; CPU 53.19324 -> 39.947686 ms. All 15 pairs
retain identical ledger JSON, updated_at, mirror bytes/decoded values, receipt
rows/serialization and valid hash chains. Constructor diagnostic session identity
is frozen only during fixture creation; measured spans use the real clock.

These are invented inputs, not production timings, market returns or a promised
latency reduction. The earlier cProfile fixture has matching dimensions but was
not preserved; exact identity with that earlier run is not established. It must
not be used as the unprofiled baseline.

## Compatibility and independent review

29 independent contract cases passed on the original converter before the change
and on the candidate. 107 combined scalar/model/ledger/hashing checks passed.
They pin native identity, NaN/infinity/signed zero/large integers/unicode,
primitive subclasses, enums and dataclasses, hostile metaclasses, key collisions,
sets, cyclic failures, exception identity, exact stored JSON/receipt hashes,
reopened state and transaction rollback. Source mypy 125 files and changed-file
Ruff passed. These correctness cases are not trading samples.

Astra accepted source/test bundle
`1861501781778aad10f9aa7f83c1f2f02f12ce2b287a5d9ab99e06a743bce835`,
computed from sorted paths +NUL+ exact bytes +NUL for models.py and the new scalar
contract test. After actual joined production records arrived, the reviewer
supported it as a partial correction subject to unchanged full-suite green and
exact release verification. No claim that the entire pause is solved.

## Retained timing-test failure and controlled investigation

The first candidate full run had 5,455 passing tests, 14 existing skips and one
unchanged arena-flush CPU-tail failure: median 0.108953 ms (<0.25),p99 0.805634 ms
(>0.5), max1.762 ms. All 4,200 events/200 frames were retained; zero drops/slicing.
Its cause is unknown. Thread CPU includes GC and kernel work, so ordinary wall
descheduling alone cannot explain it. The failure is retained; no gate is waived.

Controlled fresh-process baseline/candidate ABBA runs all pass the unchanged
gates, with identical arena source and normalized inputs. Parent flush invokes
to_jsonable zero times. In a second staged ABBA, baseline CPU p99 .347/.330 ms and
candidate .203/.318 ms; all delivery gates pass. Baseline itself reaches 1.088 ms
CPU, .969 ms inside encoding, without GC overlap. This demonstrates variability
in unchanged code; it does not diagnose the original failure or substitute for
a complete pytest pass. No test, threshold, GC setting or production source was
modified by the diagnostic wrappers.

Separate callback experiments find observer overhead around 16-19 microseconds
per book/trade pair, largely canceled by the arena-on/off comparison. It remains
a real measurement cost, not evidence that observation is free. The trace ring
and output remain bounded.

The declared serialized full rerun after this investigation passed: **5,456
passed /14 existing skips in300.22 seconds**. Source mypy125 files and Ruff on
all3 changed Python files passed. No source/test changed after the reviewed
bundle above. The [diagnostic receipt](scalar_diagnostic_receipt.json) records
hashes; [the archive](scalar_diagnostic_evidence.zip) preserves all raw samples,
exact session scripts and both failed/successful full logs. Those diagnostic
scripts retain their session-specific paths; the separate paired checkpoint
benchmark is the portable reproduction.

Release commit and actual post-release timings belong in WORKLOG and a dated
receipt. These checks support a release, not deployment or completion claims.
