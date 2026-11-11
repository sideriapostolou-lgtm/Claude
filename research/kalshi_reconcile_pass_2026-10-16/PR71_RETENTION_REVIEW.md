# PR71 selected restart-retention review

Independent reparse of the supplied original structured native wrappers: **90/90 checks pass**. The root audit's 86 selected-field checks are independently reproduced, plus four expected money/stop assertions. No original, source or production writes; the private replay script emits only `PR71_RETENTION_ANALYSIS.json`.

Compared platform publication timestamps **07:33:21.316526563 UTC before** and **07:41:06.400271921 UTC after**, October 16, 2026. Exact field lists and each result are retained in the analysis. Selected financial, fee precision, authentication, mode/status, pair protection, integrity, cleanup, caps, scalar daily/cumulative counters and selected ladder configuration fields match. Cash is $25.1219, cumulative P&L −$24.6195 and day P&L −$5.1277; daily stop remains latched, exposure/reservations/orders zero. Limits remain $10/window, $20/open, $6/day, $10/total, clip 5; ladder rung remains 0.

Three native controls explicitly report their already-used values ignored: resume, day reset and integrity reset. Epoch ordinal 2 and both archived metadata objects match exactly, along with retained-active, legacy hash and source fingerprint fields. This is metadata equality, not a full archive-body or pending-forecast-body retention certificate.

Observer remains diagnostic, enabled, no error, no in-flight request or buffered result, no candidate 56, and zero starts (no `started` counter). Thus it has no populated queue/request-execution evidence. Its lack of starts does not independently establish every account order's absence.

The analysis preserves each request, returned/matched row counts, retrieval times, original hashes and nonmatching rows. No completeness claim is inferred from row counts or search results. These are selected snapshots, not a raw ledger, full private volume, continuous source or time-interval certificate. Exact PR71 deployment/source binding and startup/health are root release evidence and were not independently replayed here. The pending pre-restart forecast's later scored body was not part of this bounded check.
