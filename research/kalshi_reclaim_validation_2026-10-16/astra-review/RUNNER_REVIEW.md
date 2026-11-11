# Independent ingestion, runner and research-screen review

APPROVED exact root-owned bytes recorded in RUNNER_APPROVAL.json, with checks in RUNNER_CHECKS.json. This is an implementation/integration approval, not an economic result or data authenticity certification. Confirmation remains sealed until root validates and publishes the complete freeze manifest/readback and the pending type-only core test revision receives its new hash approval.

## Scope and fixes

Read complete initial and revised run_partition.py, root-data/fetch_data.py, verify_data.py, evaluate.py and their fake tests. Confirmed collector is bounded public GET-only with no credential/account/configuration mutations. Coinbase windows are capped before partition end; prehistory is exactly required8h; future-returned rows stop rather than silently become valid input. Release book/settle digests are checked at acquisition; cached byte bounds and identities are checked. Data verification recomputes raw receipt hashes/sizes and derives normalized official metadata/Bitcoin bars from the preserved responses. Receipt-file glob overlap was corrected and tested.

Initially runner only hashed consumed files without checking their identity chain. Root added verify_data.py and tests before confirmation. Initially mutually contradictory YES/NO redundant quote fields could pass side-local validation. Root added price and size complement checks, preserving invalid timestamped frames rather than deleting them. Receipt order, duplicates, gaps, out-of-window rows and missing files remain visible.

Initially evaluate.combine accepted arbitrary policy rows and duplicate tickers within a partition. Review identified potential six-cell double counting or selecting a secondary policy. It now requires exactly1000ms_current_targets and delay1000, unique ticker/open timestamp per partition, disjoint tickers and valid calendar partitions. Passing a secondary cell or duplicate window raises. Unknown attempted entry full-limit-plus-fee loss bounds remain in both aggregate and confirmation checks. Unknown entered outcomes block positive screen. A negative verdict requires a negative all-attempt upper bound in pooled or confirmation; an unresolved sign stays insufficient.

Pre-signal unobservability is reported separately from attempted-order uncertainty. Policy abstention on missing input is not proof there was no economic signal. Planned denominators864pooled/288confirmation and all calendar days remain even with missing metadata or no observed trades. Bootstrap, net and drawdown are explicitly known-only; missing outcomes cannot be promoted to known profits. Coverage limitations remain essential when interpreting any conditional positive screen.

## Independent execution evidence

All fake-only checks rerun on unchanged exact reviewed bytes:19root runner/identity/evaluator,19collector,12own core cases and2own integration cases passed. Own end-to-end generated one entirely synthetic market, official-style15OHLC bars,480+5BTC bars, quote receipts and settlement labels, then invoked actual runner main with actual data verification and actual core. Only source rulecard construction was replaced by equivalent explicit fake rules; no verification/core/network path was mocked. It produced six policy/timing cells, preserved identical entries across exits within each delay, produced distinct1s/3s entry cohorts, and kept the same-entry hold-control full loss−.5175while target exits were positive. Planned96windows with95missingmetadata remained. Second own case preserves unknown-entry lower-bound loss despite positive known P&L.

Core protocol assumptions persist: final historical candle publication at end+1s is assumed, REST quote snapshots are not verified exchange arrival/queue/fill records, execution endpoints require0<p<1 as an explicit proxy convention, and settlement visibility fallback is a scoring assumption. No live/P&L certification follows from passing fakes.

## Exact reviewed root identities

- run_partition.py:99543027428a048227691579e82fda20ae34f673a171b01aa848acf280060fee
- verify_data.py:cf5460292896392955d9ba360c7b9d36d96936fc6617287b524b94a6d3a1a52e
- evaluate.py:8bb3100c77c4fa3889e2b3f7691b55988b23df13ac44f10d0d96bbdfc02c9ca1
- fetch_data.py:44be31050f66d11cba338f4c8e9215bf02a63cce6a2e96676aa4007367229a64

All test/config/protocol/rulecard/reviewer-test hashes are in RUNNER_APPROVAL.json. Core implementation4bb43b0848b3fd3ad2eba73d90f9786f5ef4119ca4e60887d98dc3ab32be93da remains separately approved; Sol's test-only type narrowing requires renewed test hash approval.

## Final gate requirements and exposure disclosure

RUNNER_APPROVAL.json lists the complete expected implementation/test/protocol/cards/review path set. Runtime gate checks supplied hashes but does not enforce path-set completeness; root must explicitly reject empty/partial/duplicate file lists and verify required files before unsealing. This operational validation and publication/readback are required conditions of approval. Do not describe the current gate as an independently enforced security boundary.

Reviewer opened no historical dataset or strategy-result file and no confirmation observation/outcome. During review, parent disclosed the VAL summary3primaryfills+$0.5681 after core freeze. That summary is known to reviewer; no strategy parameter or data eligibility change was requested from it. Subsequent work is code/fake verification and test-only type fixes. Previous failed fakes, the preliminary typecheck failure, original declaration and amendment must remain recorded.

## Final non-strategy renewals approved

Collector now loads experiment-local RELEASE_METADATA.json; its bytes exactly match prior public release inventory SHA697a426dab1a9155fc696c71654149869c711fe85b02101cce2eb0966fa9750d. Approved collector SHA **9cf50ddba2ab5c86d30971f6f30801149d92f4cd429f33ee1527eb732c23024f** supersedes44be3105 above. Core implementation unchanged; corrected test_replay.py SHA **6bfec48f5941eb929d3a8ff2dfd0806adfe225a18cf41388997874a47a493143** independently reruns43tests successfully. Collector19tests and own end-to-end2tests rerun successfully after this path change.

Reviewer-owned tests received import organization/formatting only:12+2synthetic checks still pass, isolated Ruff lint/format passes, default mypy with follow-imports=silent passes2files. Earlier14Ruff formatting/import findings are recorded, not hidden. New reviewer test hashes: test_independent_replay.py **1181da327a53a6b6a1f5228ea5b20184db5af4e6b1a5cbfd8b0c13f434049b49**; test_independent_runner.py **743ddd5b51277b10e59c91bc063197e9115ac564b865fb9c7fd6c47b3854fc03**. Final exact check/approval details in FINAL_CODE_RENEWAL.json.

Public-facing check receipts redact private experiment paths to<experiment> and Python executable paths to<python>; original receipts remain privately preserved. This changes no result, code hash or assertion. All source/runner review blockers are resolved for the final recorded bytes; root's complete required-path manifest validation, publication and readback remain the final confirmation-unsealing condition. No further implementation changes are requested.
