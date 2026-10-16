# Reduction-only Kalshi release

The owner reported that PR75 was still losing money and asked to continue the
fix. [The actual-loss report](REPORT.md) shows why further new first legs are
being contained. This release does **not** establish a profitable strategy.

## Exact behavior

Only the Kalshi controller changes. Every ordinary maker/taker proposal must fit
confirmed unmatched inventory on its light side. That condition is checked before
reservation and again at the actual transport boundary, including aggregate
pending/uncertain/cancel-requested reservations. Empty and balanced inventory
cannot open another leg. Nonbalancing resting remainders are canceled; confirmed
cancellation acknowledgments are not spammed while their reservations await
reconciliation. Partial fills and restart recovery retain their liabilities.

Existing early completion and late protective locks remain available under their
original budget, cash, feed, ownership, mode, stop and reconciliation checks.
Nothing sells or transfers funds as part of this patch. It does not erase losses,
reset financial stops, change caps, alter Railway variables or affect Polymarket
or the standalone recorder. Existing exposure can still lose before settlement.

Native `pair_execution.version=2` identifies `policy=reduction_only`, disabled
starters, no automatic resume and no expiry. A flat desk with fresh account data
and no higher-priority blocker reports reduction-only waiting and
`trading_now=false`; configured live mode remains explicit because
existing positions may still receive real-money protective hedges. Practice is
separate and noncomparable. An observation of no new orders is not profit.

## Verification scope

The production-default containment suite has 44 cases. The independent suite adds
24 adversarial cases; root reproduced all **68** together. These use fake account
data with actual-fill-shaped pre-existing obligations, without disabling the
production policy. Current production hedge/stop/funding/transport tests also
seed existing obligations directly.

Old tests that specifically need historical first-entry behavior use the explicit
tests-only `HistoricalEntryDesk` factory. Its four overrides restore only the old
entry-policy predicates; original accounting, risk, fees, journal and transport
checks remain. `make_desk` still defaults to the production class. Historical
regression passes must not be described as current admission or profit evidence.
The complete generic risk-model tests remain unchanged.

The frozen 37-Python-file manifest is [CANDIDATE_FILES.json](CANDIDATE_FILES.json),
SHA-256 `639247920c0dacb8b7a35785b2bc9c84e966c0dc592b90f8a8d2988c332d7dc3`.
The production source SHA-256 is
`c228433baa997e8b12a35c7e1074c18d2a37306c9c43b34eaceccbcbe41c58b6`.
[Independent review](REVIEW.md) covers these bytes. Changed-file Ruff passes all
37 Python files and mypy passes 135 source files. Financial evidence reproduces
74 independent identity/arithmetic/counter checks, with gaps explicitly retained.

**Final-source checks are green as of October 16, 4:48 PM PDT; release/runtime
verification is pending at this receipt.** The uncontended full rerun passed
**6,325 tests with 14 existing skips in 290.73s** ([complete output](FULL_TESTS.txt)).
The skips retain optional live-network, opt-in performance and missing historical
cache requirements; none was added to bypass containment checks.

The first full run finished with 6,324 passed,
14 existing skips and one unchanged arena timing-test failure in 296.03s;
[the complete failed result is retained](FULL_ATTEMPT1.txt). Measured added mean
was 0.03823ms against the existing 0.02ms limit; added p99 was 0.017332ms against
0.5ms. Another worker's regression run overlapped the early part of this run;
that is a possible interference source, not a proved diagnosis. The identical
test then [passed alone](TIMING_ISOLATED.txt) in 0.72s. The full successful rerun
had no other test workers. No source/test/threshold was changed
between these runs, and no failed check is waived.

## Deployment and remaining evidence

No containment deployment is recorded yet. Standing owner approval covers the
finished tested code release, subject to safe merge minutes and exact runtime
verification. There is no authority here to resume new entries, increase money,
reset budgets or enable another desk.

After deployment, verify the exact source/deployment, normal startup, preserved
limits/cumulative losses/consumed controls, new reduction-only identity and actual
order/cancel/fill evidence. Keep pre-existing and post-release fills separate.
Do not roll back to the old first-entry policy merely to clear a release problem;
use a compatible forward correction preserving containment and financial state.
Profitable-entry evidence, recorder storage/recovery, periodic full-scan delay,
town acceptance and operating takeover remain unfinished on their existing queue.
