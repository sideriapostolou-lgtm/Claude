# Arena recovery, October 19 2026 (offline only)

Scope: isolated `/workspace/nightcrawler-arena-oct19`, branch `codex/arena-recovery-oct19`, base `6fcfee9`. No production, credentials, financial rules, budgets, thresholds or GC settings in scope. No commit/push. Parent integration owner retains release and production work.

Read AGENTS, COORDINATION current ownership/queue, HANDOFF, MODEL_WORKFLOW, CONTINUITY_INDEX, newest WORKLOG, storage REPORT, ARENA_FAILURE_TRIAGE and ARENA_BLOCK_SCAN_REVIEW. Prior equality candidate is rejected; prior identity scratch is not accepted.

Initial credible candidate (proposed to root before source edits): exact-identity mismatch mask for same-length ladders. `bytes(map(operator.is_not, levels, sent))` evaluates only object identity; `.find(b'\1')` and `.rfind(b'\1')` find the exact first/last changed positions. Keep existing path for unequal lengths, where aligned suffix comparison differs. Existing `levels is sent` and `sent is None` paths retained. Same-length recreated tuples with identical members must return `(length,length,())`, exactly as before. No comparison of Level values or numeric equality.

Concrete cost: existing matching uses two iterator chains of count/compress/map/tuple iterators plus reversed iterators and per-level index generation. Byte mask needs one map and two tuple iterators; mask is untracked bytes, and finds run in C. Initial standalone 15,000-call/3-pass median thread-time microbenchmark, ns original→mask: depth3 1491→1034,depth25 1966→1767,depth111 5563→4137,depth168 6087→5352. Values are diagnostic and machine-specific, not acceptance tests. Scratch artifact `/workspace/arena-oct19-scan.py` also retained a slower list-mask alternative; list-mask is rejected.

Source not yet edited at initial note; awaiting integration scope record. Test thresholds, budgets and GC unchanged.

## Source scope and first result

Root recorded scope before source editing at 19:10 UTC; source edits started only after that message. Initial implementation changed only equal-length `ladder_change`; tuple-identity early return and unequal-length original path remain. Focused exact-identity tests passed13 in0.59s. The first attempted pytest invocation failed because system `pytest` was absent; all real checks used `/workspace/nightcrawler-daily/.venv/bin/python` (Python3.12.14), with `PYTHONPATH=src` and import verified to the isolated worktree.

Original unchanged two performance nodes, run once on mask-only source: **2 FAILED in12.35s**. Busy median0.133819ms,p990.948126ms,max1.108ms; no dropped/pending,200frames. Deep700 case0drops/5264pending against required<1500. Raw `/workspace/arena-oct19-performance.log` SHA256`34bacff5b09a0c0b15e0522c7cf5828a89c9ee5993cd48afdbbf412f0964fa23`. Failed initial source patch retained `/workspace/arena-oct19-mask-only.patch`. No favorable reruns.

## Authorized final bounded change and stop

Root authorized one final direct-payload optimization after the first failure. The common one-Level payload now emits `((level.price, level.size),)` directly, avoiding the one-element tuple slice and `_levels` temporary list. Empty payload returns`()`. Multi-Level and initial snapshot payloads retain `_levels`; no thresholds, encoding budgets, global GC or tests were relaxed.

Final frozen focused exact-output tests passed13 in0.50s. They cover0/1/15/16/17/31/32/33/111/168depth; every replacement/insertion/deletion boundary; empty ladders; same tuple and recreated tuple/member cases; signedzero/intfloat/same/distinctNaN/infinities; Level/float subclasses whose equality raises;2,000random edits;50sequential exact marshal frame comparisons with timestamps/sequence/source/request timestamps. Field identity checks avoid equality hiding representation changes. Ruff on both changed files passes; `git diff --check` passes.

Exactly one unchanged two-node run after this meaningful source change: **1 FAILED,1 PASSED in11.95s**. Busy median0.135336ms,p990.9815ms,max23.216ms;0drops/0pending,200frames. Original deep700event/0.3step node passed. Raw `/workspace/arena-oct19-performance-final.log` SHA256`ffbce4486118e6575a5f246255ff12316a4179df37fb02380b43f6853712938b`. No profiling/GC callbacks/GC setting changes during either acceptance attempt. The23ms excursion resembles the previously documented GC cost but its cause was NOT instrumented in this final run; do not assert a newly proved cause.

**STOP: candidate is NOT READY and remains unintegrated/uncommitted. Busy own-thread p99 still fails. No full suite run; original storage repair0f7eba1 untouched; original combined full gate remains failed.** No production/credential/network/provider/settings/trading/financial changes or deploy. No sealed FamilyA TEST.

Concrete partial diagnosis: current exact-identity scans allocate two iterator chains and counter indexes per compared Level; bytes mask reduces that scan overhead in microbenchmarks. The direct one-level payload removes two temporary containers. Deep final throughput gate passes, but one sample does not establish a reliable improvement, and busy p99 failure is unresolved. Existing prior profile shows some large GC pauses plus excursions without collections; the exact remaining p99 source in the final candidate has not been proved. Further progress would require a separately scoped diagnostic of complete busy-flush stages/allocations, not repeated acceptance timing runs or changing GC/thresholds.

## Frozen patch and paths

- Source: `/workspace/nightcrawler-arena-oct19/src/nightcrawler/kalshi_arena.py` SHA256`7c2169d43c8f3b0dea38db9639e0c94510065734690377f142c8029bdc11eccf`.
- New focused tests: `/workspace/nightcrawler-arena-oct19/tests/test_kalshi_arena_identity_delta.py` SHA256`0da3b1ee4748cb39c38937e9913f44c51c236fba8e41a5d2cbdf3010914edc94`.
- Source-only patch: `/workspace/arena-oct19-final-source.patch` SHA256`aa9f579a25d622438ca98776388891d2d5a93603fa4909c6ba6e086c3f5be4c3`.
- Complete source+new-test patch: `/workspace/arena-oct19-final-complete.patch` SHA256`e83efdc2e1a1471f32eac077f8641a45856c7de39691b4f68de786e597b0bdf1`.
- Target-source mypy: `/workspace/arena-oct19-mypy.log`, success1sourcefile. This is not the root-required full135file result.
- Initial existing transport subset:38passed/5deselected in15.26s, `/workspace/arena-oct19-transport.log`. This process began on the mask-only source; final direct-payload source edit occurred while it was running, so do not call this final-frozen full coverage. Final-frozen rerun is separately retained below.

Final-frozen transport+new focused coverage: **51passed/5deselected in16.79s**, `/workspace/arena-oct19-final-transport.log`. Five deselections are busy-flush (already failed once at final bytes), both parameterizations of production-depth (700 already passed once at final bytes;150not rerun), the separate1ms-loop wallbenchmark and live-loop overhead timing. This is correctness/subset evidence, not a passing release gate. No source edits followed the final performance run. No other tests/GC/budgets/thresholds modified. Worktree HEAD remains6fcfee9; only authorized source and new focused test file are dirty/untracked, no commit/push.
