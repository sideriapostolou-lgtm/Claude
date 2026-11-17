# PR #47 deployment and bounded production evidence

Owner-facing times are Pacific daylight time (UTC−7), 2026-10-14.

## Release and restart

- Owner granted standing approval to deploy finished, tested improvements. Recorded in AGENTS.md and
  COORDINATION.md. This removes repeated release confirmation; financial settings and safeguards remain.
- PR #47 merged at 09:21:48 AM PDT (16:21:48 UTC), inside the existing safe merge interval.
- Exact merge `e8db34ee34d95411ac7f695f704ceb82ef8e32d5`; Railway bot deployment
  `f707494f-1b45-4610-9488-def9796b5923`, SUCCESS at 09:24:05 AM PDT (16:24:05.418 UTC).
- `/healthz` succeeded 16:24:00.361 UTC. Polymarket reported its normal LIVE startup at
  16:23:59.109 UTC. Kalshi reported REAL MONEY at 16:24:11.297 UTC.
- Full tested application version: 5,301 passed / 14 existing skips; mypy 122 files; changed-file Ruff clean.
  Later commits only changed documentation. No Railway variables, trading rules, caps or resume markers changed.

## Financial state preserved across restart

The saved BEFORE/AFTER receipts compare top-level real-controller logs at 09:20:58 and 09:24:11 AM PDT.
Every compared cash, exposure, P&L, count, cap and stop field matches. Cash $40.9508, open cost $9.88,
modeled open risk $1.88, one position and zero resting orders; lifetime settled P&L −$6.9106,
current incomplete UTC-day settled P&L +$3.0315. Cash is not profit.

Caps remain $10 ordinary window budget / $20 open / $6 UTC-day stop / $10 total stop, first clip five.
The existing end-of-window risk-reducing lock exemption is unchanged; these are not guarantees that gross
settled window cost cannot exceed the ordinary window budget. Stop latches were false. The old resume marker
was explicitly ignored as already used, and no loss budget was reset. All prior losses remain recorded.

## Runtime evidence and limitations

Local benchmarks are in PRACTICE_WORK_REVIEW.md; they measure CPU, not trading profitability.
The early post-deploy samples are in PR47_POSTDEPLOY_SAMPLES.json. They span the partial restart window,
mostly near its cutoff, with heavy coalescing when no practice order needed intermediate books.

- At 09:25:09 AM PDT: 104,740 received / zero dropped / 136 late, pass p99 2.966 ms.
- At 09:28:25 AM PDT: 508,022 received / zero dropped / 53,649 late, pass p99 3.549 ms.
- Complete arena windows remain zero. Historical void counts are preserved; new process counters restart.
  Zero overflow since restart does not erase lateness or certify complete evidence.
- At 09:28:16 AM PDT, ordinary live step median was 1.1 ms, while recent reconciliation max was
  3,176.3 ms and event-loop lag max 1,365.6 ms. Fast median calculations do not establish subsecond
  end-to-end execution; account freshness checks still correctly block stale decisions.
- A real lock buy of five Up at $0.79 at 09:26:04 AM PDT cost $3.95 plus $0.0581 fees. Decision-to-send
  was 54.9 ms and send-to-acknowledgement 180.9 ms. This is one order, not a reaction-time distribution.

The restarted partial window settled at 09:30:07 AM PDT: 13 Up / 13 Down, $13.83 contract cost,
$0.0581 fee, $13 payout, −$0.8881 locked P&L and approximately zero directional P&L. Most inventory
predated PR #47. This loss is retained and cannot establish the release's causal effect.

## First active-window sample

PR47_ACTIVE_WINDOW.json retains the independent allowlisted audit. From 09:30 to 09:31:15 AM PDT,
12 maker orders were accepted, 11 repriced orders were cancelled, and zero fills were observed.
Bitcoin receipt-to-decision median was 92.6 ms / maximum 605.9 ms; decision-to-ack median 82.6 ms /
maximum 269.8 ms; cancel-to-ack median 78.5 ms / maximum 285.8 ms. With only 12 or 11 samples,
nearest-rank p95 equals the maximum. These are bounded observations, not stable tail estimates.

At 09:31:17 AM PDT, cash was $41.9427, no filled position/open cost, $2.50 reserved in one resting order;
lifetime settled P&L −$7.7987 and incomplete current UTC-day +$2.1434. Limits and stop state remained unchanged.
This active minute still had a 2.080 s reconciliation and 711 ms maximum event-loop lag.

Arena pass p99 was 115.330 ms at 09:31:11 and 113.645 ms at 09:32:18 AM PDT, with no added drop/late
counts between these samples. This supports lower observed processing cost under active load; it does not
prove a complete window or quantify a causal speedup against different traffic before restart.

## First completed window and recorder release

The 09:30-09:45 AM PDT real window settled at 09:45:05.880 (venue time 09:45:04.288): five Down
at $0.43, zero maker fees, Up won, −$2.15 directional P&L and zero locked P&L. At 09:45:20,
lifetime settled P&L was −$9.9487, current UTC-day −$0.0066, cash $39.7927, no filled exposure,
and $2.50 reserved in one next-window order. The later 09:46:21 snapshot shows a new position:
cash $37.3427, filled cost/risk $2.45, $2.30 reserved in one order, modeled worst-case risk $2.45.
The existing risk model evaluates pending balancing buys rather than adding every reservation to filled loss.
Its status was waiting to reconcile an uncertain order; it refused new orders during that uncertainty.
The 09:47:30.917 log (state as of 09:47:21.227) confirms that wait cleared: no resting orders or reservations,
same $37.3427 cash / $2.45 filled risk, no integrity error, and the ordinary pair-cap rule remains active.
PR47_CLOSING_STATUS.json preserves this later status rather than leaving the transient wait as current.

Do not confuse lifetime loss with the existing resumed loss budget: the earlier owner-authorized 06:49 AM
PDT restart retained stop anchor −$9.9921. This release did not reset it. Both stop latches and all caps
remained unchanged. The separate ladder P&L anchor is not the loss-budget anchor.

At 09:46:07 AM PDT the arena reported **one completed accepted window**, from zero; historical voids
stayed 69 / feed voids 60, with zero dropped and 53,649 late, unchanged since before this window opened.
This is one window accepted by the existing arena checks, not certification of all raw data or a profitable
strategy. The aggregate status does not name the accepted market or resident returns.
PR47_FIRST_COMPLETED_WINDOW.json preserves the bounded independent evidence.

PR #48 deployed the separate collector as `a0782b743a31369fe25ddf6d2eea96df8511cd8d` at 09:38:15 AM
PDT, deployment `8453f919-b891-4aa7-8478-6fcf6b9c24ee`. Its first saved-manifest receipt is in
RECORDER_SAVED_MANIFEST_RECEIPT.json. Full checks passed: 5,077 tests / 13 skips, mypy 126 modules,
changed-file Ruff and independent review. It reads metadata only; existing raw data, replay hashes and
research protocol were unchanged. Collector restart gaps are retained.

Remaining evidence work: local scheduling/account-read tails, sustained complete-window evidence, and
bounded raw/per-venue recorder verification. No strategy promotion, profitability claim, complete replay
or inspection of sealed TEST results is implied. TJR-MNQ-001 remains queued behind these prerequisites.
