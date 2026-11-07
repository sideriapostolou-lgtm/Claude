# Lock orders: recheck account and cash before sending

Owner requested a concrete bot correction on October15. Base `beea7bf09be5405612cd11e4fcd7ee6c5678d469`. This change fixes a reproduced submission defect; it is not a demonstrated profitable strategy or a complete execution-delay fix.

## Defect and correction

`_lock` admitted a balancing IOC while account and cash were fresh. After journaling and worker/transport/rate waits, `_lock_guard` checked current books, cutoff and remaining inventory but omitted account/authentication and cash freshness. An independent fake transport reproduced actual creates with fresh books but account age4seconds or cash age6seconds.

The six-line correction rechecks authentication and existing account readiness, then risk-book cash presence and its per-window nonnegative freshness limit immediately before send. It leaves the current3second account and5second cash limits intact. It does not rerun `can_lock`: the already journaled intent owns a reservation, so that would reject valid locks as `order_pending`. Fresh strictly balancing hedges still work through day/total loss stops. No cap, financial stop, budget/resume/day reset, variable, strategy threshold, model, fee, journal/durability, learner history/protocol or Polymarket change.

Guard refusal uses the existing definite-unsent path: release this reservation, retain the terminal journal state and require account resynchronization before a new order with a different client ID. It never blindly retries a create. Requiring fresh account/cash can defer a hedge; it is not a promise of higher returns in every window.

## Exact validation

Frozen source SHA256 `2471adff4eca63ee6abba73031da75793ae5e1b3cb0468e30e1e2d6b9934efd5`, new test SHA256 `e170bbc84e4b986ef370cbf267acd4a4dee9da45547042609ba858c4418f314c`, complete two-file patch `0e8a034b60529c871b5c6f1f612bdc33df26a7f34d1f147b5232f930f4243878`. Only `_lock_guard` changes in the application AST;15protected source/build objects remain byte-identical.

There are28new fake regressions: delayed transport, missing/future/nonfinite account/cash clocks, lost authentication/startup/reconciliation uncertainty, inclusive3s/5s boundaries, window-specific cash limits, own reservation, financial-stop balancing exceptions, durable unsent release, resynchronization/new identity and restart. Focused157tests, mypy128source files and Ruff2files pass. Injecting the exact original method into the two delayed-send regressions yields2expected failures/26deselected; original logs remain retained. Four initial test-fixture failures were corrected and retained, never reported as passing product checks. Independent exact review accepted the patch. Root full pytest passed **5,772 tests /14 existing skips in316.58seconds**, captured exit0, with identical before/after source/test hashes. Original receipts are retained.

## What the actual losing window says

Originals join across the old and new deployments: Down1@33c maker at10:15:16AM Pacific, later Up1@96.4c taker with0.25cfee at10:26:01AM, then a1dollar gross payout. Total cost1.294+fee.0025 gives **−$0.2965**. This is the configured loss-reducing late lock, not by itself a bug. The locked order's observed decision-to-send was9.8569ms and send-to-ack321.6094ms; it does not demonstrate the reproduced stale-authority defect.

Static arithmetic for the first fill alone under the known outcome is−$0.33: the hedge improved that particular fixed-fill result by3.35c. This is not an executable alternative-policy backtest. All losses and previous partial coverage remain; no dollars saved are attributed to this patch.

## Release and remaining work

Release only after the full suite, exact review and privacy checks pass, then at a safe merge minute. Verify exact successful Railway source, normal Polymarket LIVE startup, fresh original Kalshi mode/account status, retained selected financial/cap/control history, unchanged recorder and bounded error/status evidence. No manual trade or new financial controls.

Actual source deployment and post-restart verification are pending until recorded in the release receipt. Synthetic tests do not certify continuous production coverage, profitability or prior-loss attribution. Existing EXEC/input-gap/zero-sample learning evidence remains open; metadata optimization and acknowledged-cancel duplication are held separately, not bundled. TJR remains blocked on authentic bars/costs, paper/live off; recorder3:45PM Pacific checkpoint remains due.
