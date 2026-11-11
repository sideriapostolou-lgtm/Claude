# Late REST failure versus recovered WebSocket: correction

Prepared October 15, 2026. This addresses a reproduced feed correctness defect;
it does not establish the cause of historic losses or a profitable strategy.
Deployment/runtime verification is pending until recorded separately.

## What was wrong and what changes

A public REST book/tape request could remain pending while the same ticker's
WebSocket recovered. When that older REST request later failed, its unconditional
gap cleared both recovered books through the actual `SpeedRunner.on_status` path.
The same status could advertise healthy WS makers while erasing their books. This
can block real sends/balancing locks or trigger resting-bid safety cancellation.
It does not by itself prove a real cancellation or release a live reservation.

The correction requires current ticker admission, delivered `websocket` transport
and actual current same-ticker WS authority before suppressing the obsolete error.
Books require fresh receipt and source timestamps; tape additionally requires an
actual fresh trade. Cached `_ws_status` lists cannot authorize suppression. A retired
request cannot change current health or revive old cursors. Incomplete REST tape
never advances the cursor or emits partial prints after recovery. Original errors
remain logged with `invalidated=true/false`; only genuine active failures invalidate.

Freshness predicates/report share one captured clock instant. Three seconds stays
inclusive; later expiry, missing/future/nonfinite timestamps, disconnects, removed
state, another ticker, undelivered books, REST transport and book-only tape recovery
all remain fail-closed. Earlier genuine gap/exclusion history is not erased.

No live strategy, order/risk/accounting code, fees, caps, stops, budgets, settings,
variables, Polymarket code, parent/wire, V1/V2 protocol or observer history changes.
Successful REST response handling and request-rate accounting remain unchanged.

## Exact source and independent review

Only `speeddesk_kalshi.py`, `speeddesk_kalshi_ws.py` and one focused fake-test file
change. [Frozen source/hash receipt](recovery-v2.json) and [exact patch](recovery-v2.patch)
identify accepted bytes; patch SHA-256 is
`d956bf9e5b98fec667a47beb24332af9448131e1c54e94ac9337690bd0775b0a` (18,750 bytes).
The local docs base has the same tree as public scope commit `51c5656`; remote
integration must retain latest branch contents rather than pushing the local history.

Original unchanged-source reproduction ran 11 deterministic scenarios. Recovered
timeout/malformed-book/tape cases reproduce books **2 → 0**. Corrected independent
replay keeps **2 → 2**, with genuine failures still invalidating. The original code
also fails all 16 selected new recovery/retirement regressions, as intended.

Implementation focused checks: 133 passed, including 55 new cases. Independent
review: 169 focused checks plus the adapted 11 source scenarios and direct BTC/
inherited WeatherWS clock tests; exact corrected source accepted without blockers.
[Independent review](candidate_v2_review.json) and
[freeze acceptance](candidate_v2_root_freeze_acceptance.json) retain limits.

Full suite completed at **1:42:09 PM Pacific**: **5,939 passed / 14 existing skips**,
captured exit zero, 321.89 seconds including wrapper overhead. All three source/test
hashes are unchanged. [Receipt](FULL_PYTEST_RECEIPT.json) and
[complete output](FULL_PYTEST.stdout.txt) retain the actual result and skip reasons.
Root mypy passed all 129 source files and Ruff all three changed Python files;
[actual command receipts](TYPE_LINT_RECEIPT.json) and [scope/hash checks](CHECKS_SUMMARY.json)
are preserved. Other tracked application files and all build files are byte-equal.
Green local checks are not deployed behavior. A separate local frozen-state report
benchmark measured added median 0.000931 ms for two tickers / 0.093501 ms for 512,
within bounds fixed before running; it does not establish production speed. See
[FRESHNESS_BENCHMARK.json](FRESHNESS_BENCHMARK.json).

## Preserved failures and limits

The first candidate passed its focused tests but independent moving-clock tests
found inconsistent book/print authority. Its patch/receipt and failing clock output
remain separate; v2 fixes it before release. A default-interpreter missing-requests
failure is retained before the successful established-venv baseline run. Independent
review also records an initial fake-cancel keyword fixture error and nonexistent
test-path invocation; those are not counted as passing application checks. Some
early worker tool outputs are transcript-only, not claimed as complete archive files.
Verbatim audit scripts are retained as `.py.txt`; review hash labels refer to their
original filenames. No source credential or private handoff content is included.

Current pre-task evidence remains a bounded snapshot: at **1:27:41 PM Pacific**
the bot reported cash **$30.4496**, cumulative settled trading P&L **−$18.8909**,
reported risk **$0.4009**, caps **$10/window, $20 open, $6 day, $10 total, clip five**.
Reported totals split **+$3.800849 locked / −$22.691749 directional**. Coverage is
partial; cash is not profit, and the complete-window subset is not the full ledger.
The probability observer had three official scores and one pending forecast; its
small-sample Brier comparison is not trading or profitability evidence.

The [postrelease plan](POSTRELEASE_PLAN.md) fixes selection and capture rules before
seeing a future outcome. Real/practice data, prior/next partials, missing results,
all losses and used controls remain distinct. Broader execution gaps, untimed parent
chronology and strategy validation stay open. Other business/transfer work remains
on existing records, deferred; TJR/MNQ is last. Recorder checkpoint remains 3:45 PM
Pacific, with storage review before October 20. No new financial authority follows.
