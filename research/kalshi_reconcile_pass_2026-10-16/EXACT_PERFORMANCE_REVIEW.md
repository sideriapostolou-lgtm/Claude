# Independent exact performance-patch acceptance

**ACCEPT**, subject to root's full required suite and exact deployment/restart checks. No blocking finding in the frozen patch. This is local redundant-work reduction; it does not establish an entry edge, justify larger positions or resolve multi-second account/network reconciliation.

Base `d1ee16f728612275fedb0d08846e127b0ad9b88d`; complete two-file patch SHA256 `367397773be56b752d72cc84c06fd86484da5079095d39cb41e04fcefaad64ee`. Independently recomputed patch and both file hashes match Sol's receipt:

- `speeddesk_live.py`: `3968b78a5fcb8bcdf40415d811cbf0947b2e64fe5750afee74de06eb2cae46bd`.
- `test_speeddesk_live_settlement_pass.py`: `96e4a0e14536505b5091fd0d43003be79c209572b4ef4b97384db3c1ecf0dfc6`.

The complete source diff is one local active-window set after `_release_unsent`, and replacement of repeated active-list traversal with membership in that set. No financial condition, fee arithmetic, schema, query/page/cadence, trading setting, observer, model or stop is altered. Source/file bindings are in EXACT_PERFORMANCE_HASHES.json.

## Independent execution checks

Command: `PYTHONPATH=/workspace/nightcrawler-profit-next/src:/workspace/nightcrawler-profit-next/tests /workspace/shared/nightcrawler-venv/bin/python -m pytest -q <private-astra>/test_settlement_snapshot_independent.py tests/test_speeddesk_live_settlement_pass.py tests/test_speeddesk_live_history.py tests/test_speeddesk_live_full_scan.py tests/test_speeddesk_live_reads.py`.

Result: **30 passed in1.87s**: eight private independent cases, ten implementation cases, twelve existing history/full-scan/read cases. No independent test failed. All real client construction, requests, socket connection and DNS entry points are denied; fake accounts only. Sol separately reports214focused/mypy132/Ruff2 passing, and its reconstructed-original run has two expected bounded-traversal failures/eight other passes. Sol's first fixture's incorrect assumption that integrity cleanup sends no cancels is preserved and corrected; no production logic was changed to satisfy it. Root full suite was pending at this report time.

The private reference method reverses only the two-line optimization. Its AST was independently compared with the actual base method from `git show` and matches exactly; reference equivalence does not rely merely on naming a candidate baseline. Seven paired scenarios compare candidate against that reference:

1. Three real synthetic settlements with actual fees, gains/loss and retained inventory.
2. Losing settlements that latch daily/total stops, consume a pending resume fingerprint, retain used-control history, and notify the ladder.
3. An uncertain open liability while other inactive windows settle.
4. An acknowledged but unlisted liability while other windows settle.
5. The second full read releases a never-sent intent and settles its window in that same pass.
6. A wrong payout aborts before balance, preserving identical preceding financial effects.
7. An invalid settlement timestamp aborts before balance, preserving identical preceding financial effects.

Compared objects include the full risk-book state, all controller intents, ladder, practice twin, pull state, final/foreign/changed outcomes, pending receipts, cash/account/auth fields, archive parts/chunks, creates/cancels, exact fake API call sequence/arguments and exceptions. Financial receipts are compared; `speeddesk_live_status` and `speeddesk_fill_markout_status` are excluded because they include nonfinancial runtime/session diagnostics. No claim of full receipt-stream byte identity follows. The eighth independent case structurally verifies that capture follows `_release_unsent`, the following settlement loop has no await, and it no longer calls `_active` per window.

The implementation's additional tests exercise large finalized history and integrity fallback, active/uncertain/never-sent/unlisted deferral, older settled-fill fee correction and payout-error abort. Existing whole-read/correction regressions remain passing. Review of actual callees confirms `book.settle` removes only an already-inactive window from the index and stop callbacks update ladder/stop bookkeeping, not active Intent membership. No cross-await or cross-reconcile cache is introduced.

## Limits and next gate

Reported performance timings are Sol's inspected synthetic results, not independently rerun here: the integrity case avoids roughly109ms repeated local work, ordinary21day history about15.6ms, and a fresh case is slightly slower. Call-count reduction is deterministic; production incidence, CPU benefit, tail latency, fill outcomes and profitability remain unproved. Other full-history/network costs persist.

Root should retain original full-suite/check logs, verify exact released source and all financial/history/control state after restart, and explicitly invalidate/redeclare the PR70 future primary source promise before a changed-source release. No test order, stop reset, cap/clip increase or new financial permission is implied. The completed-day actual-first-fill cohort remains a separate evidence task, with all losers/missing data retained and no unjoined forecast attributes attached to fills.

Reviewer wrote only private tests/reports/results. No repository edits, network/account calls, credentials, financial changes or sealed research data were used.
