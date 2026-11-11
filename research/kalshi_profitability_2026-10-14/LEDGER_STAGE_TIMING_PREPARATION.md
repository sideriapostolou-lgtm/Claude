# Ledger stage timing: checked local candidate, not deployed

Recorded October 14, 2026, 10:38 PM PDT. This preserves work already in progress when the TJR queue reminder arrived. The reminder authorizes no production mutation; none was performed for this follow-up. The running source remains the separately verified PR58 source `1e8d0be07b280292fa873a2f5da9b22dd02f28c3`.

The isolated seven-file candidate measures checkpoint conversion, JSON encoding, outer lock acquisition, BEGIN, SQL and COMMIT wall/thread CPU. It does not change orders, strategy, caps, losses, resume history, save cadence, serialization options, transaction/rollback order or durability. WorkTrace publication follows the original successful save barriers. Values overlap existing checkpoint spans and must not be added to those spans. Practice panel values explicitly describe the previous successful save. Latest-only retention cannot prove that earlier work did not occur.

This is measurement preparation, not a speed fix or a profitable strategy. Production incidents include substantial practice panel/state CPU as well as ledger wall time; no serialization-only explanation has been established. No async writer, mutable-history cache, durability reduction or financial-rule change was selected.

## Exact candidate and checks

- Seven-file path/NUL/bytes/NUL bundle in manifest order: `668ba5b47e8ba142d0f61bc00953e264163b4b2d282acd58a8015dec59de78e9`.
- Patch SHA256: `dda8bf2e65a4c8a565e25535b64229e476f6b3a8d652b26d38b45b8db02ea143`.
- Base HEAD `86013da3cabb28d56a829c99b0771ebdbd54b047`; application baseline is unchanged from `a165f34`/PR58. Worktree: `/workspace/nightcrawler-ledger-timing`, branch `codex/ledger-stage-timing`.
- Full pytest captured exit zero: **5,625 passed, 14 existing skips, 320.08 seconds**, finished October 14 **10:32:26 PM PDT**. The exact process-exit receipt and full skip explanations are archived. Skips include opt-in network/performance checks and an unavailable old lab cache; they are not counted as passes.
- Root mypy passed on **all 128 source files**, captured exit zero. Ruff passed all **seven changed Python files**, captured exit zero.
- Independent Astra review accepted the exact v2 bundle; its 60 focused cases passed. The implementation's broader targeted matrix passed 175 tests. Root rechecked all seven file hashes after the full suite.
- The original v1 freeze and review findings remain preserved and explicitly superseded. The corrected v2 test first establishes nonempty span/bin evidence before injecting observer failures. Static original-plumbing fixtures preserve receipt evaluation, lock, SQL, rollback and failure-order comparisons; unchanged initialization/hash helpers are shared, so this is not a second entirely independent ledger implementation.

The candidate has measurable overhead. Local file-backed synthetic FULL/WAL saves with a 1,000-row payload had median wall times of 4.228 ms original, 4.225 ms unobserved candidate and 4.505 ms observed candidate. Fixed trial order, local filesystem/cache effects, synthetic payloads and omitted publication/rendering costs prevent a production performance inference. Raw scripts/results and smaller-payload measurements remain in the archive.

## Saved bytes and remaining work

[Preparation archive](ledger-stage-final-preparation.zip): 313,671 bytes, SHA256 `e3d0f35ac1408e4cd997e7d015eb1b377fe18842ce5992efddc76e2a0c308a0a`. Its [manifest](ledger-stage-final-preparation.manifest.json) lists 34 members, including exact source/tests/patch, both preserved freezes, independent review, overhead inputs/results and final check logs/exit receipts. Root verified CRC, member names, byte equality and hashes against every original. Absolute paths inside preserved receipts identify their original location; archive member paths identify the portable copies. Older readiness prose predates the final checks; the completed receipts above supersede its pending-check wording.

No candidate source was committed, pushed, merged or deployed during this queue follow-up. Saving code under this research archive does not install it. The isolated source files remain unchanged. Any later release must use current instructions and branch contents, preserve the exact reviewed bytes or obtain review of revisions, respect safe merge minutes, and verify the exact deployment/startup/restart accounting. This document is not a deployment receipt or an additional permission grant.

Next evidence step: finish publishing the predetermined post-PR58 capture/audit, then resume the existing execution-delay task under its own scope. If the diagnostic is subsequently released, join completed stage snapshots to identified main-reader residence intervals; preserve latest-slot omissions and overlapping wall/CPU populations. EXEC-DELAY-001 remains open, the original/inverse/no-trade comparison remains unstarted, and TJR remains blocked on authentic MNQ inputs.
