# Independent review of the bounded pair-completion correction

Reviewed at 2026-10-16 20:21:32 UTC / 1:21:32 PM PDT.

Result: no remaining blocking issue found in the reviewed money-source patch.
Release still requires the integration owner's complete checks and exact live
deployment/runtime verification. This review does not establish profitability.

Base: `530f8a6`.
Six-file implementation patch SHA-256:
`1a0663e6c65e0fca61dfd091464c324818fe17a4b127b5fd6f4763403c669405`.
The exact patch is retained as `reviewed_implementation.patch` in this directory.
It includes the three execution/risk/completion source files and three changed
test files, including new files. Root-owned documentation and page-status
disclosure propagation are not part of this six-file approval.

Source SHA-256:

- `speeddesk_live.py`: `e0adc85f35beca0c7d4597149b66687828418dbec94398ef815832462a7e8cd7`
- `speeddesk_live_model.py`: `3da6deec395aca24956e3c8754954cff4c1c86d0e89b488a50b54e1247831173`
- `speeddesk_live_completion.py`: `e19d9448e7c15ccea8e0f13d075a910fb8a6e884de1f491eb9272d4b26e664f4`

Independently executed 17 adversarial cases plus 25 implementation regression
cases: **42 passed**. Original baseline controller checks exposed six expected
feature/safety failures; three existing-limit cases passed. One overly broad
test expectation was corrected: an absent opposite book blocks that first side,
not a valid maker quote on the other side.

The independent checks cover ordinary window/open limits, fee-inclusive pair
cap, early hedging despite an adverse directional fair, whole visible depth,
post-journal depth/classification changes, partial starter cancellation without
reservation release, filled-plus-remaining starter depth, stale own depth after
partial fill and terminal cancellation, overlapping pending claims, invalid
raw-maker-price fallback, unaffordable IOC replacement, cancellation write room,
and unchanged existing daily/lifetime stop latches and financial history.
Implementation tests additionally cover marker persistence, restart mismatch,
send-time fee/cash/clip/cap/mode changes, and capped-maker queue retention.

Review findings corrected before approval: raw maker crossing checks before cap
fallback; replacing a valid maker with an unaffordable IOC; active-only own-depth
subtraction; partial-starter depth checking only its remainder; early IOC
bypassing cancellation write-room protection. Native status now explicitly
marks practice policy comparisons noncomparable. The page projection originally
dropped these flags; root owns the follow-up propagation and its verification.

The original-order-size subtraction is deliberately conservative and can remove
genuine outside liquidity at previously used prices. Visible liquidity can
disappear before a first fill, and a fill can race cancellation. The patch does
not provide atomic pairing. Fake test fills and synthetic timing benchmarks
are neither venue execution evidence nor profit estimates. No live orders,
credentials, production settings, monetary-cap changes, or sealed TEST data
were accessed by this reviewer.

## Follow-up: page disclosure and final source/test bundle

The page projection change is approved. It accepts only an actual boolean
comparability marker, emits a fixed explanation rather than arbitrary stored
text, suppresses the current comparison only when explicitly false, and leaves
the raw source and historical `week_before` projection intact. Legacy missing
or nonboolean markers remain unknown. The modified existing page assertions
match this behavior. Independently ran the six new page cases plus 59 existing
pull cases: **65 passed**. The three money-source file hashes remain identical
to the initial approval above.

The synthetic helper benchmark has no runtime registration or production I/O.
Its constructed ledger states and timings are computational fixtures, not valid
venue histories, fill simulations, or a production latency measurement. The
warm-index qualification in its output is appropriate.

Extended nine-file patch versus `530f8a6`:
`f48ab9a06eb3895dff926fbe5275ed07f13e52d11f2957b0e8caa41e30a89210`.
Retained as `reviewed_extended.patch`; individual file hashes and paths are in
`extended_manifest.json`. This bundle adds `pagestate.py`, its new tests, and
the benchmark to the initial source/test scope, and includes the later page
assertion changes in the existing pull tests. Administrative documentation
remains outside this hash and review approval. Required complete checks and
exact production verification still belong to the integration owner.

## Final candidate after full-regression findings

The full regression run uncovered two additional behavior issues after the
earlier conditional reviews: moving the raw maker crossing check had broadened
first-entry opportunities, and early completion could bypass a held pull. The
final candidate restores raw-crossing exclusion for empty-inventory starters
while preserving lower-price fallback for confirmed-inventory hedges. It checks
the pull hold at early-completion decision, admission, and transport. The late
lock path remains unchanged. These deltas were inspected and independently
tested, not approved by assumption.

The balancing fixture now reconciles the original fill and moves the ask before
the next decision, so it tests a resting hedge under a later stop without
accidentally taking the earlier cheap hedge. The crash fixture seeds one actual
fake-account order/fill before its unchanged randomized beats; all restart
equality, risk monotonicity, reservation, and nonvacuity assertions remain.

Independent review caught a vacuous new transport-pull test: a missing required
`count` keyword raised a fake-transport exception, which the controller correctly
retained as uncertainty, but the weak no-create assertion passed. The initial
independent batch exposed two fixture TypeErrors. Both test implementations now
provide the keyword; the main transport tests additionally require definitive
guard rejection, released reservations, no uncertainty, no fatal state, and zero
errors. The independent test checks decision, admission, and transport stages.

Final selected run: **104 passed**, comprising 21 independent adversarial cases
and the crash, protected-pair, and completion regression files. Earlier page and
pull checks remain separately recorded above; counts are not presented as a
single disjoint whole-suite total.

Final reviewed 11-file candidate patch versus `530f8a6`:
`3dcfe32a07a90bd708ae14f5404cae9660ffac39e27b3d2f9f1c3065ff9b6e29`.
Stored as `reviewed_final_candidate.patch` and `final_candidate_manifest.json`.
`speeddesk_live.py` is now
`65c18358c0cd2ae8a3592bcc8d2280c51a5b4a26f61a2929a11968851a91f674`;
model, completion-helper, and page source hashes are unchanged. This approval
supersedes earlier candidate hashes for release purposes. No blocking issue
remains in this inspected candidate; complete root checks and exact production
verification are still required. Administrative documentation remains outside
the code/test/benchmark patch hash.

## Publication wrapper

Root stores the final exact patch losslessly as `reviewed_final_candidate.patch.gz`
to preserve unified-diff context whitespace. Decompressed bytes match the final
reviewed SHA-256 above. This packaging does not change the reviewed source.
