# Company town implementation — October 19, 2026

## Status

Implemented and independently reviewed in isolated local commit
`dcfca4536c49b6464259a4e6b17e9421a8ef6b39`, based on deploy-branch commit
`9c2c776bfc4492b2ccf7e2b93122a07dc2025041`. **Not deployed.** Source remains a local
release candidate, preserved privately with its patch, exact files and manifest.
The town product/acceptance obligation and ECOM-001 launch remain open.

## What changed

- Company is the default view, with one Trading switch. Six departments show
  prepared work, missing evidence and the next task: Research, Product, Creative,
  Store, Marketing and Support. The preparation clock is fixed at October19,
  6:03PM PDT; polls do not advance it or fabricate work.
- Original product drafts, three scripts and support drafts are represented as
  preparation. No rendered ad, store, payment connection, campaign, support inbox,
  sales or continuing worker is claimed. Revenue/spend say Not connected; the
  proposed $50 ceiling is not an actual expenditure or active campaign limit.
- Trading retains its account/P&L/source-time and real/practice projections.
  Company suppresses trading receipts, earned gardens, working lamps, the cash
  sign and account activity lights. Returning to Trading restores render layers
  while preserving the latest values and visibility. Auth loss closes details.
- Campus HQ, cutaway frames, paths and workstations are updated using procedural
  geometry. Thirty merged console meshes replace approximately 210 small ones.
  Company overview fits the whole plot. Phone, tablet and desktop layouts differ;
  long-label collisions and short landscape overlaps found in review are fixed.

## Verification and limitations

One full repository run on the final candidate completed at October19,6:38:36PM
PDT: **6,336 passed,2 failed,14 skipped in398.43seconds**. The two previously
documented arena performance failures remain: busy-flush CPU p99 **0.684ms**
against the required<0.5ms, and production-depth700/0.3s backlog case **1,728
dropped events** against required zero. Neither file changed in this town task.
No favorable rerun, threshold change, skip or waiver was used. Therefore the
repository-wide release gate is **not green**; no application source was pushed
to the deploy branch or any remote review branch. The full failed output is
preserved privately with the candidate. Existing skips include opt-in network,
one opt-in wall-clock check and an unavailable historical lab cache.

Changed-file Ruff, full mypy (136 source files) and diff checks passed. Root's
final focused company/control/camera run passed38 tests. Earlier independent
review passed53 tests and found a finance-prop crossover that was fixed and given
a real Three.js regression. Final source review found no remaining blocker.
These counts overlap and must not be added together.

Local browser checks covered390x844,320x740,820x900,1440x1000 and1280x400. Mode
switches, department opening, keyboard activation, returning and scrolling were
exercised; no JavaScript errors or horizontal overflow. A first320px check hid a
Support marker; the saved final regression shows all six. The full run used
existing `lite=1`, reduced motion and a harness-only250ms animation scheduling
delay because unthrottled software-WebGL desktop capture timed out. The initial
390px normal-mode controls worked. No actual-phone frame-rate or signed-in
production acceptance is claimed. Fixtures contain no live financial data.

Eight changed application/test files were scanned for credential patterns, with
no matches. Saved patch SHA256:
`f5ff4d43132ba850186093e466bcde217c12e36528efe66df7c2464f321bf2b3`.
It matches the committed diff byte-for-byte and passes reverse-apply checking.
The included source manifest independently binds all eight final files.

## Production evidence and release gate

Read-only inspection at **October19,6:33:13PM PDT** reports bot deployment
`43f14443-2d07-4985-b879-3a2515fb8d2c` online1/1, unchanged from PR76. Recorder
deployment `8453f919-b891-4aa7-8478-6fcf6b9c24ee` is also online1/1. The bot's
latest disk metric is **4.997726208GB**, against the previously verified5GB
volume; the preceding hour's maximum is4.997906432GB. Metric sample timestamps
and actual filesystem free bytes/inodes are not supplied. A bounded native-status
and state-save-error query for6:00–6:33PM PDT returns0rows, not proof of trading
health, zero trades or current account state. No current balance is certified.

The town and trading process share a service. A watched application-source push
restarts it. Existing disk-full, failed authoritative-state writes and missing
fresh venue reconciliation remain unresolved. Ordinary Railway SSH access was
previously refused; this task's network policy still grants no TCP destinations,
and the connected tools expose status but no volume read/remote-command path.
No alternate tunnel, service, credential copy or access-control bypass was used.

Next: supported read-only volume access, coherent financial state/history export,
filesystem assessment and fresh venue reconciliation; finish the existing recovery
and required release checks. Then release the reviewed exact town source in a safe
merge minute and verify the exact deployment and authenticated runtime. A healthy
web container, successful docs commit or preview does not satisfy that acceptance.

No production configuration, restart, deployment, order, financial limit, stop,
resume budget, paid ad/service or customer message was changed. Existing losses
and unfinished handoff/recorder/research obligations remain preserved.
