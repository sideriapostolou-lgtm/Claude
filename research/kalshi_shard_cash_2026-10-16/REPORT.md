# Kalshi exchange-index cash and refusal backoff

October 16, 2026. Times below are Pacific daylight time (UTC−7).

## Result and scope

Code correction implemented and required checks passed; exact deployment and
runtime verification remain pending at this pre-release checkpoint. This is an execution-eligibility repair, not
evidence of a profitable strategy or of a funded account.

The old cash check used aggregate cash even though Bitcoin orders route to the
exchange index on the exact market. A public read of the rejected market identified
index 2. Its actual available primary-account balance has not been verified.
The prior process also allowed successful reconciliation to erase the short pause
after a definite insufficient-balance rejection, causing repeated attempts.

The patch reads exact primary-subaccount/index cash, reserves outstanding orders
and actual post-snapshot fill costs/fees, and fails closed on unknown cash/routing
or unresolved foreign resting orders. Definite insufficient-balance refusals pause
creates for 60/120/240/300 seconds, survive successful reads and restart, and are
durably recorded with terminal rejection. Existing uncertain-order reconciliation
and cancellation remain available. Aggregate cash stays an additional ceiling.

No transfer, standing allocation, funding, manual/test order, financial-control,
variable, cap, loss reset, live activation or new strategy is included. Kalshi stays
PAPER. The other live desk's code and controls are untouched. Public API contracts
and limitations are in [API_REVIEW.md](API_REVIEW.md), the independent implementation
review in [INDEPENDENT_REVIEW.md](INDEPENDENT_REVIEW.md), and implementation checks
in [IMPLEMENTATION_HANDOFF.md](IMPLEMENTATION_HANDOFF.md).

## Frozen source and validation

- Latest source/test patch SHA-256:
  `c8c2289cee038a32613ede4b9f28c30e38a2a5199ab277ed62078cdcc6579be2`.
  Thirteen Python source/test files relative to `8aa66a7d`; this hash excludes
  documentation and evidence. Original implementation base `9110d5d`, followed by
  a docs-only fast-forward preserving the source patch.
- Initial full run: **6,223 passed, 2 failed, 14 skipped**, 310.71 seconds.
  Both failures are retained as limitations of that run: a restart fixture did
  not deliver fresh public market routing, and a trace expectation omitted the
  newly required subaccount-balances read. Source behavior was unchanged by their
  corrections. The affected complete test files then passed **44 tests**.
- Final full rerun: **6,225 passed, 14 skipped in 293.51 seconds**.
  Network/real-order tests were not enabled. See [CHECKS.json](CHECKS.json) for
  exact skip reasons and original log hashes.
- Root mypy: **133 source files clean**. Root Ruff: **13 changed Python files
  clean**. The separate evidence comparator also passes Ruff.
- Independent exact-patch review: no blocking defect. Initial review executed
  **153 pytest cases and 32 separate offline assertions**; final fixture delta
  review executed **95 tests**. These overlap and must not be summed as distinct
  application coverage. No production/account endpoint was exercised by tests.
- Full original initial log and final-rerun log remain in the execution workspace;
  published check receipts record their hashes/results rather than copying bulky
  simulated account logs into the public repository.

Tests cover cash units/account/index scope, malformed/missing balances, fresh local
receipt versus old venue mutation time, fills/fees/reservations/foreign rests,
ordinary and lock send guards, successful-read cooldown persistence, restart/crash
atomicity, routing refresh and old-source serialization compatibility. Rollback
must remain PAPER: old code can read preserved state but lacks the new cash gate
and cooldown.

## Production evidence

[BEFORE.json](BEFORE.json) preserves selected native status fields from deployment
`07e8627b-7700-4dff-8e84-fd2d90ac669e`, source
`275392733de1458692211506228f7dd30e60c693`. Query began 6:55 AM; the provider
returned three rows for a requested limit of two. Latest receipt was
**6:58:16.272988420 AM PDT**. The query is bounded provider evidence, not a full
volume/ledger or account-hold certificate.

- Configured/effective PAPER, authenticated false, cash unknown in this process.
- Current UTC-day settled P&L **−$5.1277**; lifetime settled P&L **−$24.6195**.
- No reported bot open risk, reservations, orders or positions.
- Caps **$10/window, $20 open, $6 daily, existing $10 total-loss allowance,
  clip 5**. Daily and total halt flags false; integrity error null.

Exact release commit/deployment, normal Polymarket startup, bounded traceback
inspection and comparison of selected controls/losses remain pending. The
[verify_restart.py](verify_restart.py) script compares before/after status fields
without any account access or financial action. It cannot certify raw budget
anchors, credential values, continuous coverage or every persisted byte.

## Unfinished work and next evidence

1. Complete exact release and selected runtime retention checks, keeping paper.
2. Obtain authorized read-only primary-account/index cash and commitment evidence.
   The patch deliberately does not instantiate a trading client during flat paper
   startup just to populate this evidence. Missing data remains unknown.
3. Any cash movement or standing allocation is a separate financial action. No
   code for it is shipped here. After any owner funding/activation, verify actual
   accepted/rejected orders, fees and fills separately; don't infer them from a
   healthy process or API documentation. Keep the refusal backoff and all losses.
4. Execution-delay/queue/first-entry evidence, recorder raw-volume/retention/cost
   and the operating handoff remain open. The previously invalidated fixed future
   cohort stays invalidated; no favorable replacement hour or sealed TEST is used.

TJR/MNQ remains LAST and queued. Current coordination/work-order/AGENTS/worklog and
PR47's API plus its separate deployment/follow-up record were rechecked. PR47's
historical release is complete; it does not clear current higher-priority work.
No Pages, duplicated MNQ research, paper/live start or automation change occurred.
