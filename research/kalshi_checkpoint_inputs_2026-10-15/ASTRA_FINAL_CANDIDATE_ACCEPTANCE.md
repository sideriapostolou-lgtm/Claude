# Exact candidate acceptance — qualified

Accept exact source/test patch **475dc5aa1177815292b91d16bebb2a093692b1e38b0169578ed66fb3ac040b78** for integration, subject to root's required full checks and release/runtime verification. Source eb9146263a881ba2ef6645c03585ca78c7bc0e1d9f03cb5177028d483e403ef4; new test3eb15e8f138cbe47ef99b5b6fa76ac6ce6db4751bcba7e76b1d0d5585e13ca30. No blocking code finding. This acceptance has explicit performance limitations; it does not declare every original gate or latency percentile passed.

## Independent checks

Recomputed conventional patch hash from tracked source diff plus untracked new test diff. Rechecked unchanged runtime/helper hashes, original checkpoint/summary AST and embedded baseline, as documented in ASTRA_FROZEN_SOURCE_AST_REVIEW.json. One source file changes, with no model/fees/strategy/scorecard/controller/ledger/cadence/schema change. Native field identity reuse, original-path fallback, copied containers, per-row mutation checks, nested cleanup and strong-reference identity safety remain sound on review.

Independent focused execution after benchmarks ended: **268 passed in5.13s, exit0**. Suites include new differential cache tests, practice runtime/FULL/atomic mirror/history, scorecard and independent grouping, live mirror/save cadence, probability epochs and learning. Exact command is in the acceptance JSON. Root runs the full suite/mypy/Ruff independently; this reviewer did not duplicate the full suite or run another benchmark.

Independently verified **78 corrected measurement children** (58 main+20 extension), all exit0 with raw stdout/stderr hashes matching. Recomputed clean medians and extension process-pair ratios directly from raw samples. Decompressed and compared **72 complete byte pairs**: first/correction/steady KV, mirror and ordered receipts for7 fixtures plus zero extension. All agree exactly. All child output-phase hashes, repeated steady outputs, clock-call counts and forbidden-runtime-attempt counts agree as expected. Counter checks show report Settlement asdict calls reduce toC per checkpoint while model serialization remainsC; windows/report evaluations are unchanged. Original pre-checkpoint input hashes were not recorded; shared fixture code and equal input sizes plus exact first/correction/steady persisted bytes support parity, without pretending a missing input hash exists.

## Measured benefit and retained adverse evidence

| Synthetic history | Baseline/candidate checkpoint median wall ms | Change |
|---|---:|---:|
|1day|4.7306 /4.7112|−0.4%|
|Fixed W/C,7report days|10.2680 /9.4190|−8.3%|
|7days|49.4168 /42.2458|−14.5%|
|31days|618.2799 /502.9838|−18.6%|
|Sparse35days|261.0919 /212.4069|−18.6%|

The multi-day benefit repeats across all3 timing-process pairs and has matching thread-CPU direction. This is enough evidence for a narrow computation optimization, not for a promise of the same production improvement. Sparse synthetic history, inert live panel/empty volatility tape and local disk omit real workload components. No profitable strategy or causal link to actual feed gaps follows.

**Initial zero-history gate remains FAILED/inconclusive:** pooled median1.752094→1.840510ms (+5.0463%);2/3 process pairs exceeded5%. Keep SUMMARY.status=failed_regression_gate and the rejected slower first candidate pilot. These results are not erased or renamed successful.

The root-authorized **single preregistered extension** used20 children,10 per variant,25 warmed checkpoints each, fixed ABBA/BAAB order, unchanged source/fixture and analysis pinned before execution. Independent primary calculation: median paired process ratio **0.987370 wall /0.990906 CPU**; only2/10 pairs exceed1.05. Median of process medians1.7760545→1.7775275ms (+0.083%). Thus the extension's predefined primary gate passes, and the larger order-balanced sample does not show a repeatable>5% central slowdown. This additional evidence supports acceptance; it is not a retroactive pass of the original3-pair gate, and no further retries were used.

**Tail caveat stays adverse:** pooled250-sample p95 grows2.093165→2.348005ms (**+12.17% wall**, CPU+12.54%). These samples are nested in10 processes, not250 independent experiments. This observation cannot be discarded because the primary median is favorable; the review does not establish no tail regression. The task's gate addressed repeatable checkpoint central wall/CPU cost, with tails separately reported. Acceptance is an engineering assessment of repeatable multi-day savings plus the completed preregistered central-cost check, with this tail limitation retained. Do not claim every latency improved.

**Memory cost is real:**31day traced peak7,970,917→9,490,613bytes (+19.1%, roughly1.52MB), reflecting retained row conversions/references during the checkpoint. Process RSS in that allocation run82,888→81,664KiB; main per-fixture RSS maxima do not grow. The original10%memory gate was peakRSS, not tracemalloc, so it is not violated by the separate traced allocation increase. This is not permission to hide the allocation cost or generalize bounded-memory behavior to arbitrary history sizes.

All observed child elapsed/RSS/disk remain comfortably within60s/256MiB/100MiB. Main max child10.8222s, sampledRSS81,356KiB, experiment disk15,345,281bytes; child self-reported RSS peaks additionally capture82,888KiB. Extension max child0.471s/sampleRSS50,460KiB. Resource sampling is periodic and RLIMIT_AS/file-size are distinct bounds; no claim of an instantaneous aggregate disk quota. No cap-triggered child is silently excluded. Failed harness-only matrix and first slower candidate evidence remain retained; final comparisons use the corrected frozen harness and exact source.

## Release conditions and limits

No source edits by reviewer. Root's fullpytest/mypy/Ruff/secret scan and final exact-byte recheck still required; source changed later requires renewed review. Safe-minute release, exact deployment and actual runtime/financial-history checks are separate completion gates. This review accepts the local change, not completion of EXEC.

speeddesk.py changes the observer fingerprint normally. Archive the ACTUAL latest predecessor epoch dictionaries/counts/pending state at release, not an earlier assumed0score/2unknown snapshot. The later one-score supplement already shows why fixed assumptions are unsafe. Preserve old five-score archive, current-source history, V1 and strictV2, with a distinct new source epoch under existing rules. No source alias, calibration transfer, history reset, strategy/fee/cap/stop/resume/variable change, real restart or new-money authority follows from this release review.

Broader feed delays, continuous coverage, prediction accuracy and profitability remain OPEN. The zero-control tail and allocation observations belong in the release evidence and subsequent runtime assessment, not hidden behind the larger-history averages.

## All main-matrix checkpoint tail comparisons (descriptive)

These pooled n=15 nearest-rank p95 values equal each observed maximum, not a stable production percentile. All are retained, including adverse tails outside the zero control.

|Fixture|Wall p95 baseline→candidate ms|Change|CPU p95 change|
|---|---:|---:|---:|
|zero|2.190869→2.430811|+10.95%|+15.45%|
|one|2.108384→2.230824|+5.81%|+5.73%|
|1day|6.457942→6.707691|+3.87%|+3.66%|
|fixed7days|12.362925→9.957231|-19.46%|-19.18%|
|7days|50.882647→62.762400|+23.35%|+23.31%|
|31days|664.684968→555.656841|-16.40%|-16.40%|
|older35days|280.662388→225.585220|-19.62%|-19.64%|

In particular7day wall maximum/p95 rises50.882647→62.762400ms (+23.35%) despite the favorable median and all three process-median pairs. One-row and one-day tails also rise. These prevent any universal no-regression/tail guarantee. Acceptance is limited to the measured multi-day median/thread-CPU saving with disclosed tail/allocation tradeoffs. Actual practice settlement/history size is unknown; the separate real-book195-settlement count is not a proxy or a production extrapolation input.
