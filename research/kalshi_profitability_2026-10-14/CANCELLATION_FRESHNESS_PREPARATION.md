# Cancellation freshness correction — tested candidate, not deployed

Prepared October 15, 2026, **4:46 AM PDT** (11:46 UTC). This preserves progress on the owner's
active Kalshi loss task. The intervening TJR queue reminder is a separate bounded documentation
check; it does not authorize a production change or clear either task.

## Demonstrated defect and correction

`KalshiLiveDesk._cancel_unsafe` captures prices and time before iterating resting bids. A venue
cancellation awaits I/O; prices, feed freshness or the window cutoff can change during that wait.
The next bid previously used the pre-wait inputs and could remain resting despite becoming unsafe.

The standalone fix refreshes snapshot/time at the next iteration after `_cancel` returns. It keeps
the initial priority ordering and adds no snapshot read when no cancellation occurs or after the final
intent. Cancel acknowledgement is still separate from terminal reconciliation; reservations remain
counted. Existing lock exceptions, guards, error propagation, accounting, thresholds, caps and stops
are preserved. This is six source insertions plus a new regression test file.

- Local candidate commit: `9d69d95f2d001984e4cdb3c35f0c1f2947529eff`, branch `codex/cancel-freshness`.
- Base: `3c757ba369a0f2b5ca010f617d39c61eea3e5a66`.
- Reviewed complete patch SHA256: `537035a4a6d49714b930a4c3001841020cc13619978ceb676eb4008d00daf3a4`.
- Source SHA256: `2253d3ce64de8da30ab7a1e60c3a78d2d74a10920ee6733786884f43a07c9221`.
- New test SHA256: `fbc301f08218f794b33684079d927f5f672a7bfc9ffb286fc3909fc96cd8d870`.
- Candidate remains local; no source branch push, PR merge, deployment, variable, order or financial
  control change was performed for it. The prior seven-file ledger diagnostic remains separate.

## Checks on exact bytes

Root full `pytest -q`: **5,582 passed, 14 existing skips, 317.97 seconds, captured exit 0**.
Source/test hashes match before and after the run. Root mypy passed all **127 source files**;
Ruff passed both changed Python files. Scope/diff and bounded credential-pattern checks passed.
Independent Astra review accepted the exact patch and passed 70 focused tests. Sol's separate
183 targeted/existing tests also passed. The original method reproduces eight missed-cancellation
failures covering price reversal, aging, cutoff and a missing window.

Tests use actual controller/model methods with fake venue I/O. They exercise unchanged markets,
initial sorting, locks/shutdown, final-cancel callback behavior, raised cancellation and reservation
retention as well as the defect. The `.03` variants directly reserve `.48` bids with recorded `.50`
fair; they do not prove issuance through `_send` at that edge. The feasible `.02` fixture establishes
the regression. An initial independent command named a nonexistent test path and ran no tests;
its corrected command passed. Skipped network/cache tests are not claimed as exercised.

[Exact patch, manifests, full logs, exit/hash receipts and independent review](CANCELLATION_FRESHNESS_PREPARATION.zip)
are retained in a 14-member archive. Its [external receipt](CANCELLATION_FRESHNESS_PREPARATION_ARCHIVE.json)
records SHA256 `fe1afcc356de10fdcda0734ae9f98ab6aa13879b96473917a05999eea8ffee9e`;
CRC, member hashes/lengths and bytes were verified. No quantified saved loss or production timing
benefit follows from these offline checks.

## Newer loss evidence — available windows only

The [immutable forensics archive](kalshi-loss-20261015-forensics.zip) preserves original queries,
errors, v1/v2 reports, joins and deferred synthetic profiling with an
[external manifest](kalshi-loss-20261015-forensics.manifest.json). SHA256
`52dd7460f9ce2f8d4fc59d70dfeac3cba1be27cc37c139cc0fd2198e4f15da19`, 59 members,
1,532,592 bytes. Root independently verified CRC, every member's name/hash/length, and exact
source-byte equality. Earlier broad log queries failed; later precise original logger/event queries
succeeded. Capped parent responses remain preserved, excluded and replaced by uncapped subdivisions.

Fixed bounds: October 14 **10:30 PM** to October 15 **4:15 AM PDT** (05:30–11:15 UTC), tail through
4:18 AM PDT. Exact source `1e8d0be07b280292fa873a2f5da9b22dd02f28c3`, deployment
`fc0a73e9-f052-435a-94b2-ce7b1272f36e`. Fifteen of 23 expected slots have original settlements;
**eight slots from midnight to 2:00 AM PDT are unknown**, not zero activity or zero P&L.

The 15 observed settlements reconcile to **82 real fills**, $128.4794 cost, $0.2538 fees, $129 payout:
**+$0.2668 net**, split **−$0.11155 locked / +$0.37835 directional**. Nine positive/six negative;
worst window **−$2.2962**, last three observed windows **−$4.0818**. All six losing windows finish
balanced but cost more than their payout. Seventy-four distinct accepted orders filled out of 972
accepted orders (7.61%); this is an order fill rate, not 82 fill events divided by orders.

Static same-recorded-fill accounting attributes +$5.4506 to maker inventory and −$5.1838 to actual
completion-lock legs. This is not a maker-only backtest: locks affect later inventory/admission and
cushioned five of the six observed losses. Do not remove hedges or infer a profitable alternative from
that allocation. The 10:30–10:45 UTC exception has five winning Down maker shares at `.40`, five losing
Up lock shares at `.961`, $0.0132 fees, and −$1.8182 net. Preserve the actual sides and all losses.

The independently parsed 15-window result is a partial cohort, not a profitable-day result or proof
that stale inputs caused any specific historical loss. The dated 4:21:57 AM PDT status reports cash
$34.9622 versus cumulative settled **−$13.5942**; neither is a fresh account check from this preparation.

## Remaining work

EXEC stays open and the original/inverse/no-trade comparison stays unstarted. A later authorized
active-work release needs current instructions/head, exact source identity, safe merge timing,
Railway SUCCESS on the exact merge, normal Polymarket LIVE startup, bounded errors and financial
restart reconciliation including intervening fills, settlements and retained stop/resume history.
Do not treat a merge or first stale startup status as completion.

For post-release evidence, freeze the first two full 15-minute windows beginning strictly after
verified startup, exclude the startup partial, and close collection at the fixed second end plus a
two-minute publication tail. Assign collection only after the exact deployment is known; make no
source release during that capture. Preserve every outcome and missing event, separate real/practice,
join original orders/fills/settlements, subdivide capped responses and keep producer/freshness limits.
Unknown outcomes stay unknown rather than extending the sample after seeing P&L. Code correctness
and startup health alone do not certify profitability or resolve broader feed-delay attribution.
