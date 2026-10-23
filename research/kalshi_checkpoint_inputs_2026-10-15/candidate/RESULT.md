# Checkpoint-local Settlement conversion candidate

Implemented offline candidate in `src/nightcrawler/speeddesk.py`, plus one new focused differential test file. No commit, push, network/API/production call, source-epoch alteration or financial-setting change. Root retains review, full checks, integration and any later release/runtime verification.

Exact conventional complete patch: `COMPLETE.patch`, SHA256 **475dc5aa1177815292b91d16bebb2a093692b1e38b0169578ed66fb3ac040b78**. Source SHA256 **eb9146263a881ba2ef6645c03585ca78c7bc0e1d9f03cb5177028d483e403ef4**; new test SHA256 **3eb15e8f138cbe47ef99b5b6fa76ac6ce6db4751bcba7e76b1d0d5585e13ca30**. The main matrix source/harness hashes remained unchanged before every child and after all runs. `matrix_manifest.json` also carries a separately labelled source-diff-plus-new-test-bytes digest; the conventional patch digest above is the integration/review reference.

## Change and semantics

Only the existing Settlement list-comprehension element conversion is replaced. First native row visit lazily checks the eleven canonical fields in original order, immediately falls back to original `asdict` for a missing/exotic field, and caches the original conversion with strong references to the row and validated exact builtin scalar values. Later visits check each current field by object identity against those retained immutable values. First change/missing field invalidates the entry and immediately invokes original asdict. Exact-class checks and identity comparisons never invoke an exotic metaclass hash/equality. Every consumer receives a new list and separate flat row dictionaries, preserving duplicates and preventing cache poisoning.

The cache exists only during one checkpoint; `try/finally` restores the previous context for nested checkpoints and all failures. Standalone summaries use original asdict each visit. All summary hooks/arguments, window filtering/conversion, independent clocks, report chronology/corrections, state/receipt transaction order, first FULL/NORMAL transition, pending-clear/mirror/last-checkpoint boundaries and persistence schemas remain in their original positions. No Window cache, prefilter, frozen clock, cross-checkpoint cache, retention change, new queue/writer or real-controller/journal edit.

The new focused file compares against exact original summary/checkpoint method source copied from immutable f77e1ad, pinned by SHA256, rather than a reimplementation of the cache. Forty cases cover full persisted KV/mirror/receipt parity, scripted advancing/reversing clocks, actual window-close/midnight/30-day cutoffs, duplicate/order/replacement/mutation/rebind inputs, zero/one histories, hostile metaclass hash-call parity, subclass/exotic/missing/fallback repair/error behavior, poisoned consumer containers, standalone freshness, nested success/failure restoration, late settlement/carry first partial correction, and daily/state/FULL/receipt/KV/COMMIT/NORMAL/log/mirror/replace failures plus retries. A field-order test pins the guard to canonical dataclasses.fields(Settlement).

Focused plus existing practice persistence suites: **69 passed**, including the 40 new cases. Changed-file Ruff passes; mypy for speeddesk.py passes. Full repository pytest/mypy and independent exact review are root-owned and remain required; this report does not claim them complete.

## Main paired matrix

58 successful measurement children, seven fixed synthetic fixtures, sequential alternating baseline/candidate order. Original source baseline is executed from immutable f77e1ad methods; fixture generation is copied exactly from the frozen baseline harness. Three fresh timing processes per variant/fixture, five warm samples per operation/process. Separate count/allocation processes for original four fixtures. Each child uses a clean environment, explicit worktree PYTHONPATH, inert paper feed/companion factories, no credential/environment reads and active socket/client denial guards.

| Fixture | Steady checkpoint wall median baseline → candidate ms | Change | CPU median baseline → candidate ms | Wall p95 baseline → candidate ms |
|---|---:|---:|---:|---:|
| Zero settlements / 4 windows / 1 day | 1.752 → 1.841 | **+5.05%** | 1.752 → 1.828 | 2.191 → 2.431 |
| One settlement / 4 windows / 1 day | 1.942 → 1.836 | −5.48% | 1.932 → 1.836 | 2.108 → 2.231 |
| 1 day / 50 windows / 46 settlements | 4.731 → 4.711 | −0.41% | 4.731 → 4.711 | 6.458 → 6.708 |
| 7 report days / fixed 50 windows, 46 settlements | 10.268 → 9.419 | −8.27% | 10.268 → 9.369 | 12.363 → 9.957 |
| 7 days / 338 windows, 322 settlements | 49.417 → 42.246 | −14.51% | 49.404 → 42.244 | 50.883 → **62.762** |
| 31 days / 1,490 windows, 1,426 settlements | 618.280 → 502.984 | −18.65% | 618.232 → 502.937 | 664.685 → 555.657 |
| 35 older days / 562 windows, 490 settlements | 261.092 → 212.407 | −18.65% | 261.083 → 212.382 | 280.662 → 225.585 |

All values are descriptive synthetic observations; n=15 p95 is the maximum and is not a production percentile. The seven-day candidate has an observed high tail despite a lower median. The zero-settlement initial control **fails the conservative initial regression gate**: two of three paired process medians exceed 5%. `SUMMARY.json` deliberately retains `failed_regression_gate`; this is not relabelled as an all-green matrix.

Settlement report conversions/checkpoint fall from 184→46, 5,152→322, 91,264→1,426 and 35,280→490 in the original four fixtures, exactly one conversion per retained native Settlement, while every original row visit still validates current contents. Separate model.to_state conversions remain C, and Window conversions/clock counts remain equal. Outside checkpoint, daily_reports and summary remain uncached; their full raw timing/count distributions are retained and not claimed to improve.

## One preregistered zero-control extension

After the original gate concern, root authorized exactly one further extension, with no source change: twenty isolated children in fixed `ABBA BAAB ABBA BAAB ABBA` order (A baseline/B candidate), ten children per variant, 25 warm checkpoint samples each. `ZERO_EXTENSION_PLAN.json` was written and hashed before execution. All twenty exited zero, with full output/receipt/clock/guard parity; no further reruns were made.

Median of ten per-process wall medians: baseline **1.77605 ms**, candidate **1.77753 ms** (**+0.083%**). Median paired candidate/baseline ratios: wall **0.98737** (−1.26%), CPU **0.99091** (−0.91%); two of ten pairs exceed 5%. Thus this extension's preregistered primary paired-median threshold does not reproduce a >5% median regression. Pooled 250-sample p95 remains higher: **2.093→2.348 ms wall**, **2.077→2.338 ms CPU**. Full process/pair distributions remain in `ZERO_EXTENSION_SUMMARY.json`.

The extension does not erase the original failure or establish a tail improvement. Root/Astra must assess these combined observations against the no-repeatable-regression requirement; the report does not waive a gate or approve release.

## Parity and resource evidence

For every main-matrix pair and every extension child, first FULL/report creation, correction, and steady phase KV/mirror/ordered normalized receipt hashes match. The children directly assert raw KV bytes equal raw mirror bytes. For first timing process per variant/fixture, all three phase KV/mirror/ordered receipt byte streams are retained as deterministic gzip artifacts; the parent decompresses and compares complete bytes, not just lengths. Every receipt field, order and hash participates. All histories/fees/losses/unresolved rows/coverage and four published older-report days are retained; no steady output/receipt change occurs. Scripted differential tests separately compare exact clock return sequences and failure-state snapshots.

Main matrix longest child **10.822 s**, maximum sampled whole private experiment disk **15,345,281 bytes**; largest RSS **82,888 KiB (80.95 MiB)** baseline versus candidate max **81,664 KiB (79.75 MiB)**. No fixture exceeds the +10% RSS gate. Every child and supervisor enforce <=60 s, <=256 MiB RSS/address-space and <=100 MiB whole experiment disk; no cap abort occurred. The extension maximum child time is 0.471 s, RSS 50,460 KiB and whole-disk 7,126,740 bytes.

Tracemalloc reveals a memory tradeoff even with the observed RSS gate passing: 31-day warmed checkpoint peak **7,970,917→9,490,613 bytes (+19.1%)**; older-history **3,734,804→4,454,875 bytes (+19.3%)**. This is temporary checkpoint-local allocation, not a proven production RSS reduction. Count/tracemalloc instrumentation overhead is reported separately in SUMMARY.json; timing observations use neither. The common FakeClock.now counter adds the same small overhead in both variants.

Import-time urllib3 IPv6 capability socket probes are blocked before construction and retained separately. Runtime forbidden-attempt counters are dynamically zero in all 78 corrected children; production client constructors are denied. No actual client/socket construction, remote connection, credential access or production state access is inferred from mere paper settings.

## Preserved failures and remaining work

- The first implementation's valid seven-day parity pilot regressed 48.13→59.95 ms; source and raw outputs are retained under rejected-v1/pilot artifacts. It was refined within the authorized identity-guard design; no Window or broader algorithm change.
- Initial focused test attempts had scripted-clock/commit-injection/exception-expectation/metaclass fixture failures. Raw v1/v2/v4 failures remain; the corrected focused cases pass. They were not application failures and no Ledger/controller change was made to accommodate them.
- First main-matrix attempt stopped on a one-settlement control harness variable shadowing the result metadata. Six zero controls succeeded and the one-control baseline failed before checkpoint. Complete failed harness/manifest/raws are preserved in `failed-matrix-v1`; the corrected full matrix was rerun with stable hashes. The frozen baseline artifact failures remain separately preserved.
- Actual retained PRACTICE state size is unverified. A separately reported 195 settlements belongs to the REAL companion and cannot establish practice checkpoint size or savings. Empty volatility tape and inert live panel understate actual total work; no extrapolation, production causality, tail guarantee or profit claim.
- Root-owned independent exact review/full repository checks and any eventual source-fingerprint/versioned-epoch preservation, release and production/runtime evidence remain pending. Existing V1/V2 history cannot be aliased/reset/relabelled; no trading setting/rule/cap/stop/resume/control changed. EXEC and profitability remain open.
