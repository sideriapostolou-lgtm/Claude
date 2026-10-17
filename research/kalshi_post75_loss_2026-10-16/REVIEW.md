# Independent containment review

Reviewed against base `826fd0e`. **Source and frozen-file review complete; final
release qualification is pending the integration owner's full required check
results.** No live deployment, order, financial setting or credential operation
was performed by this reviewer.

The exact 37-file Python manifest is [CANDIDATE_FILES.json](CANDIDATE_FILES.json),
SHA-256 `639247920c0dacb8b7a35785b2bc9c84e966c0dc592b90f8a8d2988c332d7dc3`.
All 37 current file hashes independently matched that manifest. Application source
`src/nightcrawler/speeddesk_live.py` is
`c228433baa997e8b12a35c7e1074c18d2a37306c9c43b34eaceccbcbe41c58b6`.
The manifest binds source, modified test fixtures, historical-policy helper,
independent adversarial tests and arithmetic script; it does not hash this review
or every prose/raw-evidence artifact.

The ordinary production order path checks confirmed unmatched inventory before
reservation and checks aggregate remaining claims again at transport. Empty and
balanced positions cannot start another leg. Cancellation covers recovered and
partially filled nonbalancing remainders while retaining reservations until
reconciliation. The decision loop limits candidate sides and quantity to actual
inventory. Existing late protective locks and the original financial, mode,
account, ownership, funding, price and feed guards remain. No new configuration
switch, persisted entry permission, automatic expiry or automatic resume exists.
This policy lasts while this source is deployed; an older application rollback
would need a separate entry-policy review.

One concrete review finding was fixed: an acknowledged reduction-only cancellation
could be sent repeatedly after the retry interval while order-list reconciliation
lagged. The final source suppresses those repeated confirmed cancels without
releasing liability. The implementation tests cover both successful and 404
acknowledgments. Initial test-harness defects were also corrected: a competing
partial fill now belongs to an older order rather than an impossible first-send
fill of the prospective order; restart assertions respect completed reconciliation.
There is no unresolved source finding in the reviewed candidate.

Independent verification:

- The production-default containment suites passed **68 tests**: 44 implementation
  cases plus 24 separately authored cases in
  [test_containment_adversarial.py](review_checks/test_containment_adversarial.py).
  These are overlapping with any subsequent full-suite counts, not additive claims
  about unique total tests. The independent file also passed Ruff.
- The independent suite asserts the exact production controller class and uses no
  containment-helper overrides. It covers genuine negative-margin balanced pairs,
  invalid/excess amounts, unit cost at least $1, aggregate partial/uncertain/
  cancel-requested claims, cross-window and cross-venue isolation, legacy recovered
  starters, and late-lock book/ownership/time gates. Fake confirmed fills establish
  existing obligations; no synthetic result is presented as a real fill or profit.
- The four-method historical test subclass restores only the prior entry-policy
  predicates. Its admission helper returns true because the new predicate did not
  previously exist; original reserve/risk checks remain outside that seam. Its
  intent/cancel predicates preserve prior protected-window behavior. Factories are
  explicitly named, production defaults remain the real controller, and there is
  no global fixture override. Historical tests establish mechanism regressions,
  not permission to initiate new production positions.
- An independent AST comparison of assertions in every modified existing test
  module found no removed prior assertions. One entry-sizing test is explicitly
  renamed historical. Additional actual-fill setup assertions were added in cash
  and stop-controller fixtures. The seeded current-policy stop, lock freshness,
  cash and transport cases remain distinct from historical first-entry fixtures.
- The arithmetic script reproduced **74 checks** in an isolated temporary copy;
  its generated `ANALYSIS.json` was byte-identical, SHA-256
  `285b02bb6d10cd67da00a7f82579740dbc382a48475bac21f79092e4212ae2f8`.
  Receipt arithmetic independently confirms new settled net **-$0.3126**, inherited
  **+$0.0600**, and deployment-period settled change **-$0.2526**. Cash changed from
  $47.3599 to $47.0698 (**-$0.2901**), consistent with settled change plus recorded
  gross open cost moving from $0.94 to $0.9775. This is a bounded consistency check,
  not certification of every account cash flow.

The source review supports **containment only**. The target's $0.49 losing Down
entry preceded its cancellation acknowledgment; 39 capped ordinary Up hedge
intents did not fill. The observed late hedge reduced that particular official-Up
loss by $0.0682. No executable earlier profitable hedge, queue-retention profit,
or positive strategy expectation was established. Invalid 1/5/30-second markouts,
the saturated diagnostic query and unsettled current pair remain limitations.
Existing exposure can still lose, and no-new-orders evidence is not profit.

Full pytest/mypy/changed-file Ruff results, exact safe-minute integration,
deployment identity and bounded native runtime acceptance remain the integration
owner's release gates. This review does not mark those unfinished steps complete.

## Later check and startup qualification, October 16, 4:53 PM PDT

This dated qualification supersedes the pending full-check status above. The
final uncontended full run passed **6,325 tests, 14 existing skips in 290.73s**;
mypy passed 135 source files and changed-file Ruff passed. The retained first run
had 6,324 passes, 14 skips and one unchanged arena timing failure: added mean
0.0382297416ms exceeded its 0.02ms threshold, while p99 0.017332ms passed its
0.5ms threshold. The same test passed alone in 0.72s and in the full rerun; no
threshold or source/test bytes changed between those runs. Concurrent earlier
test work is a possible interference source, not a proven explanation.

Independently verified merge `f370c3c252927f659472ee160eb92fac2458ee51` at
**4:49:22 PM PDT**, a permitted merge minute. It and tested feature
`83ab53868edbc7567e3d2088904f7bcc285f8ca4` have identical tree
`cfdad49e5fabe3b936b4f654428d71ea55420d22`. All 37 files in the committed manifest
match the reviewed hashes. Deployment
`43f14443-2d07-4985-b879-3a2515fb8d2c` identifies that exact merge and reports
SUCCESS at **23:50:35.236 UTC** in [DEPLOYMENT.json](DEPLOYMENT.json).

[RUNTIME.json](RUNTIME.json), as reviewed at SHA-256
`16ce4c1cacafc5163e70c3aa91dfef10aaa1c3340510aa3fd3b8d06dcaedd223`, supports bounded
startup acceptance. The first native status at 23:52:06 was account-stale after a
4,770.7ms full scan. At **23:53:06.830 UTC**, authentication is true and the last
recent reconciliation is 758.8ms with no checks or failure; waiting is specifically
reduction-only, not stale account. Native policy version 2 disables starters,
automatic resume and expiry. `trading_now=false` is correct for the absence of
unmatched holdings under this policy. A 3,292.6ms full scan also remains in the
interval; this is not evidence that periodic account delays were eliminated.

Thirteen selected financial/cap/state fields, including the complete retained
`total` dictionary, match [PREDEPLOY.json](PREDEPLOY.json) exactly. Cash is $47.0925,
cumulative settled P&L -$27.6616, fills 975, settlements 255 and fees $3.61602;
reserved/unmatched risk and active orders are zero. Caps remain $20/$40/$12/$10,
clip 5. All seven retained `today` financial fields also match; the runtime
artifact projects those fields, so this is not an equality claim for the complete
native daily analytics object. Startup receipts show rung 0 restored and all
three consumed controls ignored. This verifies the selected receipts, not a
byte-for-byte inspection of all stop anchors or consumed-token hashes.

The zero-risk status still contains **$0.9873 gross paired inventory**.
[INHERITED_ROLLFORWARD.json](INHERITED_ROLLFORWARD.json) records Down 1 at $0.41
and Up 1 at $0.56 plus $0.0173 fee before containment deployment. Its eventual
$0.0127 settlement margin belongs to the earlier policy. The runtime order query
returned no rows but was requested before its stated end; its disclosed effective
coverage ends no later than **23:52:57 UTC**. Do not extend that query's coverage
through the later fresh snapshot or attribute an inherited settlement to the guard.

Polymarket startup retains LIVE 10 contracts. Platform receipts show both services
online, including the unchanged standalone recorder deployment. The separate
`nightcrawler.learn.recorder` startup warning remains `low_disk`, free_mb=165;
platform status does not establish that all recording is healthy. The interval
before the Kalshi startup receipt remains an availability limitation without exact
causal attribution.

**Next-window acceptance is still pending.** This review has not yet observed the
5:00 PM PDT opening, its inherited settlement, or the requested bounded absence
of new entry orders. Startup qualification does not complete the profitability,
recorder, periodic full-scan or other retained operating work.

## Next-window qualification, October 16, 5:01 PM PDT

The bounded next-window acceptance above is now complete. Independently reviewed
[NEXT_WINDOW.json](NEXT_WINDOW.json), SHA-256
`164d227c3ff36b1ab5ebdd7a437933cd181dd6af289b8e91be15da1fc6fd49cf`. All three queries
identify the new deployment and cover **23:50:25 UTC October 16 through 00:01:25
UTC October 17**, requested at **00:01:47 UTC**, after the interval ended. The
money query includes the exact order/cancel/fill/settlement headers. Its one row,
the ten selected native statuses and the three raw shared-feed opening rows are
each below their query limits. Parsed opening rows independently match the raw
opening receipts. Only one is Kalshi: `KXBTC15M-26OCT162015-15`, observed at
**00:00:11.717 UTC**. This is a shared-feed discovery record marked practice,
not a real trade or proof of a hypothetical entry opportunity.

At **00:01:13.679 UTC**, the native real-money controller is authenticated and
reports reduction-only waiting, starters disabled, no automatic resume/expiry,
and `trading_now=false`. Its latest recent reconciliation took **368.3ms**, failed
false, with no checks. Open cost, unmatched risk, reservations and open orders are
zero. Cash remains **$47.0925**, fills **975**, fees **$3.61602**, and order/take/lock
attempt counters are unchanged from predeployment. Caps and stop/integrity flags
remain unchanged. The interval still includes a **3,929.1ms full scan**; no general
latency improvement is claimed.

The queried money stream contains **one inherited settlement and no new order,
cancel or fill rows**. Its actual receipt is the predeployment `2000` pair's
**+$0.0127**, bringing cumulative settled P&L to **-$27.6489** and settlement count
to **256**. New UTC-day P&L includes that inherited result with zero new fills;
the day boundary does not make it containment profit. Earlier PR75 receipts plus
this settlement yield **11 traded settled windows, 10 wins totaling +$0.1544,
one -$0.4218 loss, net -$0.2674**, with two additional zero-fill settlements. This
roll-forward supplements, rather than replaces, the report's fixed 23:25 cohort.

The strengthened [verify_runtime.py](verify_runtime.py), SHA-256
`8a1bad239e9e47c47f10ed1609a77bfc1f9d02a572a25ad8bde2ec61e79bf6f5`, reproduced
**175 checks** in an isolated temporary copy. Its output was byte-identical to
[RUNTIME_VERIFICATION.json](RUNTIME_VERIFICATION.json), SHA-256
`006c97424b9dc39203838528648de8ceb9a9fddc3b8de92579202b727baa67bc`. This additional
offline evidence script is outside the original frozen 37-file source/test
manifest; it does not change runtime policy.

The exact tested deployment and this bounded no-new-entry observation are
accepted. Cancellation, early-completion and protective-lock branches were not
naturally exercised after deployment because no unmatched exposure remained;
their acceptance relies on reviewed source and production-default fake tests.
Selected logs and native counter continuity are not complete account certification
or continuous health proof. No profitable replacement, causal trading gain, new
live strategy or completion of the retained research/recording/operating work is
established.
