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
