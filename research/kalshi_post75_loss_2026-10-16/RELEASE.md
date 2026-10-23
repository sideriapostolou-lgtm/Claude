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

**Final-source checks are green as of October 16, 4:48 PM PDT.** The uncontended full rerun passed
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

[PR76](https://github.com/sideriapostolou-lgtm/Claude/pull/76) merged at
**October 16, 4:49:22 PM PDT**, inside the safe release window. Tested feature
`83ab53868edbc7567e3d2088904f7bcc285f8ca4` and merged source
`f370c3c252927f659472ee160eb92fac2458ee51` have the identical tree
`cfdad49e5fabe3b936b4f654428d71ea55420d22`. Railway deployment
`43f14443-2d07-4985-b879-3a2515fb8d2c` reached SUCCESS at
**4:50:35.236 PM PDT** ([deployment receipt](DEPLOYMENT.json)).

[Native runtime evidence](RUNTIME.json) first shows policy2/reduction-only at
**4:52:06.567 PM PDT**, authenticated REAL MONEY mode with starters disabled.
That first snapshot waited on a slow account read (4,770.7ms). At
**4:53:06.830 PM PDT**, the account read was fresh (758.8ms, no checks) and
waiting specifically said reduction-only/no new first legs; `trading_now=false`.
Cash$47.0925, cumulative settled−$27.6616,975fills/255settlements/$3.61602fees,
risk/reserve/orders0 and caps20/40/12/10clip5 match [predeployment](PREDEPLOY.json).
Three already-used reset/resume controls were ignored. This is selected native
state retention, not a fresh complete account-ledger audit.

Normal Polymarket LIVE10 startup is recorded at4:50:31.645PM. BTC startup appeared
at4:52:00 after about89seconds of pre-run initialization. The unchanged constructor
verifies the receipt chain/restores archives before that log; no spans establish
which part caused the delay. Preserve this startup/full-scan latency obligation.
The legacy learning recorder still reports `low_disk free_mb=165`; this is distinct
from the unchanged standalone Kalshi recorder deployment8453f919, online1/1. Platform
health is not raw-volume, backup, retained-data or profitability certification.

The paired inventory with gross cost$.9873 was acquired at4:45–4:46PM by PR75,
before this release ([original fill receipts](INHERITED_ROLLFORWARD.json)). Its
settlement at **5:00:11.243 PM PDT** booked **+$0.0127** and stays with that earlier
policy. It is the sole financial event in the new deployment's bounded query;
there were no new order, cancel or fill rows. The query covers **4:50:25–5:01:25 PM
PDT** and was requested at **5:01:47 PM**, after its end. The new Kalshi window
`KXBTC15M-26OCT162015-15` was observed at **5:00:11.717 PM PDT**. This shared-feed
opening record is market discovery, not a real or practice trade.

At **5:01:13.679 PM PDT**, fresh native status still reports reduction-only waiting,
disabled starters, no automatic resume or expiry, and `trading_now=false`.
Cash is **$47.0925**, cumulative settled P&L **−$27.6489**, with **zero unmatched
risk, reservations, gross open cost and open orders**. Fill count975, fees$3.61602
and maker/take/lock attempt counters are unchanged; settlements increased to256
solely through the inherited pair. Latest recent reconciliation took368.3ms with
no checks. The UTC day changed naturally at5PM Pacific; that inherited result
does not become new-strategy profit because of the date boundary.

[Next-window receipts](NEXT_WINDOW.json) and [175 reproducible checks](RUNTIME_VERIFICATION.json)
are independently reviewed. Run [verify_runtime.py](verify_runtime.py) offline to
reproduce the result. The completed PR75 new-trade cohort is **11 traded settled
windows: ten wins totaling+$0.1544 and one−$0.4218 loss, net−$0.2674 after fees**,
plus two empty settlements. This roll-forward supplements the original fixed
4:25PM report without replacing its earlier cutoff or losses.

**Exact deployment and bounded next-window acceptance are complete.** No new
orders is containment evidence only. Cancellation and protective hedge branches
were not naturally exercised live during this release because exposure was flat;
their acceptance relies on reviewed source and production-default fake tests.
No direct test orders were placed. Selected logs do not certify continuous health
or a complete account ledger. Five of ten minute-spaced native samples waited on
stale account data; that sample ratio is not an uptime fraction. Periodic full-scan
delays remain. [Health evidence](HEALTH.json) preserves the low-disk warning and
the unusable saturated broad error query; precise bounded traceback/error-header
queries returned zero. Healthy platform status does not clear storage recovery.

Standing approval covered this tested code release. There is no authority here to
resume new entries, increase money, reset budgets or enable another desk.
Do not roll back to the old first-entry policy merely to clear a release problem;
use a compatible forward correction preserving containment and financial state.
Profitable-entry evidence, recorder storage/recovery, periodic full-scan delay,
town acceptance and operating takeover remain unfinished on their existing queue.
