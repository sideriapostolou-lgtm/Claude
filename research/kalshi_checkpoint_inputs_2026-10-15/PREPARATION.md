# Practice report preparation: bounded execution-delay work

Status at 3:24 PM PDT October 15 (22:24 UTC): baseline accepted; candidate implementation/testing in progress. No source release or production speed/profit improvement is claimed here.

## Concrete finding and scope

The unchanged application performs repeated dataclass conversion of retained practice settlements for each day and venue inside a synchronous checkpoint on the market event loop. In the fixed sparse synthetic fixtures, clean checkpoint median is 48.10 ms at seven completed days and 617.89 ms at 31 days. Report conversion counts are 5,152 and 91,264 settlements per checkpoint. Count instrumentation adds overhead; its attributed timings are not projected savings. See [baseline observations and limitations](RESULT.md), [raw summary](SUMMARY.json), [run manifest](matrix_manifest.json) and [independent baseline acceptance](ASTRA_BASELINE_ACCEPTANCE.md).

The candidate changes only practice settlement input conversion at the existing report call site. It leaves mutable windows and all clock/filter/coverage/correction evaluations in place. A lazy cache exists only during one checkpoint, rechecks each exact-native scalar field at every row visit, falls back to the original conversion for unusual inputs, and provides independent containers. Nested calls and every failure exit must restore the prior context. This proposal does not change checkpoint cadence, persistence/schema, fees, thresholds, source identity, decision rules or the live order/accounting controller.

Original pre-send FULL journal, atomic receipt/state/archive/journal clearing, startup/shutdown saves, practice first-FULL/ordinary-NORMAL boundary, receipt ordering, display mirror and last-checkpoint failure semantics remain required. Source speeddesk.py changes naturally require a distinct existing-versioned probability epoch; no calibration transfer, alias, loss deletion or stop reset.

## Measurement limits

The four fixture shapes are 1/7/31 days with 24 sparse windows per venue per day, and 35 days with eight per venue per day, plus carry windows. They do not certify complete daily observation. The real companion's published 195 settlements are not a verified count of the practice desk being profiled. Its practice retained size is unavailable; no actual-size equivalence or production cost extrapolation is established.

All twenty accepted baseline children exited zero, within 60 seconds, 256 MiB RSS/address-space and 100 MiB scratch bounds. The supervisor exited one at its final broad hash assertion because coordination documentation alone changed concurrently; application, helper and frozen harness bytes stayed exact. That failure and the superseded pilot/import-guard/fixture errors are retained, not called green. Baseline mirror/KV lengths agree; stronger byte/hash equality must be established by the candidate differential run. This distinction is preserved in BASELINE_CORRECTION.json. The inert live companion excludes actual live display and storage contention costs.

## Separate observer evidence

On unchanged app0c30491/source23e2, a later opportunistic forecast at 3:05 PM PDT assigned Up90.8437%; the official market finalized YES at 3:15 PM. The original score published at 3:15:29 PM is independently linked to the frozen forecast and public official result, Brier0.008383692762115782. The forecast log published about8.05 seconds after its payload decision time. This is one later recorded prediction, not a replacement for the failed predeclared 2:50 PM target, an accuracy estimate, a profitable trade, or permission to use the learner live. Latest supplement has two forecasts, one score, two unknowns and one pending. Full raw production bin/checkpoint export remains unavailable. See [independent linkage, source version and limitations](observer-supplement/INDEPENDENT_OBSERVER_ACCEPTANCE.md).

## Completion requirements

Candidate needs exact baseline/candidate persisted bytes, complete ordered receipts/hash chains, clock and boundary/failure equivalence, independent frozen-byte review, resource-bounded paired timing without material regression, full pytest/mypy/changed-file Ruff and secret scan. Then standing release approval allows a safe-minute deployment with exact-commit health/stop/history verification and separately declared prospective runtime evidence. None of those follows from the baseline alone.

Existing EXEC-DELAY-001 and Kalshi learning/profitability work remain open. Existing 3:45 PM recorder/storage check is retained. Money caps, stops/resume/day budgets, Railway variables, real orders and Polymarket source are outside this change. Operating takeover/business work remains unfinished/deferred and TJR/MNQ last/blocked.

The two `.py.txt` files are unchanged frozen measurement-source artifacts, retained byte-for-byte under an archival extension; original commands/filenames remain in the run manifest. They are not imported application code. Adjusting absolute reproduction paths creates a new harness version and must be recorded.
