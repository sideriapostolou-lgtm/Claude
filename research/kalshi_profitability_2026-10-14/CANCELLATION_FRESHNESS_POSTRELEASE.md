# Cancellation fix deployed; first two full windows lost $0.8917

October 15, 2026. All owner-facing times below are Pacific daylight time (UTC−7).
The standalone cancellation correction is deployed and its bounded release verification is complete.
It fixes stale inputs between awaited cancellations; it does not establish a profitable strategy.
The wider **EXEC-DELAY-001 remains open**, and the original/inverse strategy comparison is unstarted.

## Exact release and controls

- [PR59](https://github.com/sideriapostolou-lgtm/Claude/pull/59), exact source
  `1bd8f2217025b098adfd2a0e8a9ca3bbe45c97da`, merged at **5:05:19 AM** within the safe interval.
- Railway bot `cdf0d895-6eed-403b-9594-4679692a4499` reached SUCCESS at **5:06:44.265 AM**.
  Normal Polymarket startup remained LIVE, 10 contracts/order. Fresh Kalshi account status at
  5:08:37.957 AM independently verified authenticated/live/trading enabled; the first cold stale
  account status was excluded from readiness. Both services were online 1/1 at the final **5:47 AM** check.
- Six source insertions in `speeddesk_live.py` refresh snapshot/time before the next remaining bid
  after a cancellation await. Initial sorting, thresholds, locks, reservations, uncertain-order handling,
  stop controls and accounting were retained. No source release occurred during the fixed capture.
- Exact tested patch `537035a4a6d49714b930a4c3001841020cc13619978ceb676eb4008d00daf3a4`:
  **5,582 passed / 14 existing skips**, captured exit 0; mypy 127 source files / Ruff 2 changed files passed.
  Independent review accepted the integrated application/test/build bytes. The old method reproduced
  eight missed-cancellation failures. See the unchanged [preparation](CANCELLATION_FRESHNESS_PREPARATION.md)
  and [initial release/restart evidence](CANCELLATION_FRESHNESS_RELEASE.md).
- No variables, limits, stop/resume budgets, new live desk, manual orders or `polydesk.py` changes.
  Ordinary caps remain **$10/window, $20 open, $6 UTC-day stop, $10 total stop, clip 5; ladder rung 0**.
  An existing risk-reducing completion-lock exception can admit gross window cost above the ordinary
  budget. That budget is not a guarantee of gross cost ≤$10; no cap increase is claimed here.

## Fixed real-money outcomes

The predeclared windows were **5:15–5:30 and 5:30–5:45 AM** (12:15–12:45 UTC), with publication
tail ending **5:47 AM**. Collector stopped at **5:47:23.654 AM**. Startup partial, next partial and
practice are excluded from the following results. Every loss remains included.

| Pacific trading window / exact ticker | Fill events | Filled accepted orders / accepted | Up / Down | Cost | Fees | Gross payout | Net P&L |
|---|---:|---:|---:|---:|---:|---:|---:|
|5:15–5:30 AM / `KXBTC15M-26OCT150830-30`|10|9 / 69 (13.04%)|13 / 13|$14.0000|$0.0517|$13.00|**−$1.0517**|
|5:30–5:45 AM / `KXBTC15M-26OCT150845-45`|2|2 / 85 (2.35%)|1 / 1|$0.8400|$0|$1.00|**+$0.1600**|
|Both|12|11 / 154 (7.14%)|14 / 14|$14.8400|$0.0517|$14.00|**−$0.8917**|

All net P&L allocates to matched inventory: locked **−$0.8917**, directional **$0** at venue precision;
the worst window was **−$1.0517**. Both sides filled in both windows; final residual imbalance was zero,
which does not describe imbalance throughout the window. Fee-inclusive average matched-pair cost was
**$1.06369**, above the $1 payout. Eleven maker / one taker fill events are distinct from order counts.

Independent Astra and root reparses join every fill to original durable intent, exact accepted order,
ticker, side and settlement. **164 intents = 154 accepted + 8 explicitly not sent after price moves +
2 explicit rejects**. No unresolved intents, orphan/conflicting acknowledgements or fill-join errors
in these responses. Twelve events come from eleven filled order IDs because of partial fills.

For the first window only, static decomposition of these same recorded fills assigns **−$1.90**
to recorded maker inventory and **+$0.8483** to the actual completion lock, summing to **−$1.0517**.
This is not a maker-only policy/backtest or evidence of alternative fills; it does not justify removing
completion hedges. Correctness tests demonstrate the stale-input defect; these windows do not measure
its causal profit effect or avoided losses.

## Latency and remaining issue

| Actual regular decision → acknowledged order | 5:15–5:30 AM | 5:30–5:45 AM |
|---|---:|---:|
|Samples / eligible regular accepted orders|67 / 67|85 / 85|
|Median|88.487 ms|101.544 ms|
|p95, nearest rank|356.732 ms|628.353 ms|
|Maximum|541.896 ms|1,337.875 ms|
|Accepted completion-lock acknowledgements, metric not applicable|2|0|

These include durable decision, journal/queue and HTTP acknowledgement. Resting time until a fill is a
different metric. No pooled percentile is inferred. Durable ordinary-intent Bitcoin exchange → decision
ages have 70/92 samples, medians **272.446/198.988 ms**, p95 **793.225/780.539 ms**; callback receipt →
decision medians **223.067/97.501 ms**, p95 **750.853/565.303 ms**. Those populations include later
not-sent/rejected ordinary orders and exclude rejected source messages; clock and callback-boundary
limitations remain. Ten deduplicated error/timing originals are retained separately from successful acks.

Main reader `speeddesk/instance1/process1` still shows **11 known rejected-message local residence
intervals**, maximum **3,122.473 ms**, with explicit boundaries contained within the fixed windows.
Another **81 overflow gap receipts** have window-contained apply points but unknown full delay intervals.
Do not turn unknowns into zero, pool separate status populations, reuse cumulative maxima as a window
measurement or mix other reader/session identities. Three known and five unknown tail gaps remain separate.

Selected contained reconciliation diagnostics cover **17/12 cycles, 86/61 reads**, with maximum
worker-complete → coroutine-resume **579.081/1,035.267 ms**. Reported read/new-fill omissions are zero
in these selected groups; this is not every quiet cycle or complete work attribution. Nested CPU/wall
spans are not additive. The cancellation fix is not a feed-delay correction, and freshness has not passed.

**Next evidence step:** continue existing EXEC attribution using exact main-reader intervals and the
preserved offline replay/profile. Separate practice panel/state CPU from ledger elapsed stages before
choosing a correction. Keep the already-reviewed seven-file ledger diagnostic separate; do not infer
that releasing measurements itself removes latency. No sealed TEST or original/inverse fitting was opened.

## Cash, P&L and health at the recorded endpoint

Original status at **5:46:55.573 AM**: Kalshi REAL MONEY, authenticated, `trading_now=true`,
`reason=balancing_only`, empty waiting reason and no integrity error. **Cash $30.9116** differs from
**cumulative settled trading P&L −$18.4098**; cumulative fees **$3.10572**, 774 fills / 168 settlements.
Open filled cost/risk **$0.42** plus **$0.56 reserved**, one position / one resting order, belong to the
next partial window and are excluded from the two-window performance table. Total/day latches were false;
caps and rung retained. Cumulative lifetime P&L is not the current stop budget; raw stop anchors were not exported.

Selected cash arithmetic independently agrees at venue precision:

`$31.7933 + $0.43 prior-partial net settlement − $1.0517 + $0.16 − $0.42 next-partial buy = $30.9116`.

The prior settlement's gross payout was $2, of which $1.57 was already credited as paired collateral;
only net payout $0.42999999999999994 is added. Cumulative P&L independently reconciles
`−$17.7029 + $0.1848 prior-partial result − $0.8917 = −$18.4098`. Raw floating representation and an
explicit $0.0000001 absolute comparison tolerance are preserved. This is selected original bot evidence,
not a full native cash-transaction, terminal-order or stop-anchor ledger export.

The status reports 44 settlements / −$3.9627 in the current UTC day, while its stricter scorecard has
21 complete / 44 eligible windows with 23 gaps and −$9.3128. These different coverage populations
must not be substituted for a complete daily result. No prior-completed-day or practice profitability
claim is made by this bounded release audit.

Final Railway health at **5:47 AM**: bot and recorder online 1/1, zero reported issues/recent failures;
exact source deployment still SUCCESS. Initial docs commit `0960bf4` was SKIPPED, so it did not restart
the bot. Exact new-deployment `Traceback` query covering **5:15–5:47 AM** returned zero rows; this is a
bounded query, not a future guarantee. The old zero-change staged environment patch remains untouched.

Recorder's **5:00:10.273 AM** publication reports the **4–5 AM** hour: 60/60 fresh and trade-tape
minutes, zero reported gaps, storage **463,646,282 / 4,831,838,208 bytes**, warning level 0, no deletions.
`coverage_certified=false`; raw hashes and per-venue spot ticks remain unverified. These are reported
manifest/storage counters, not free-disk or complete-source certification. The later recorder feasibility
checkpoint remains pending.

## Preserved evidence and limitations

- [Final originals, audits, independent review and stopped collector](CANCELLATION_FRESHNESS_POSTRELEASE.zip):
  **44 members**, 971,282 bytes, SHA256
  `23d8e4a39d0f8821ab2a7bb51ad6a558a691073f428dd1c623602c7cc44c6994`.
  [Member hashes and checks](CANCELLATION_FRESHNESS_POSTRELEASE_ARCHIVE.json).
- [Supplemental monitor/health/cash/recorder and historical point evidence](CANCELLATION_FRESHNESS_SUPPLEMENT.zip):
  **24 members**, 243,059 bytes, SHA256
  `1c16eb4b0a783658802e8443b17ef4de7e760469cadb21229078891ca7f4704b`.
  [Member hashes and checks](CANCELLATION_FRESHNESS_SUPPLEMENT_ARCHIVE.json).

All 18 original event queries succeeded below the requested 500-row limit; 156 identical overlap rows
are retained and deduplicated without conflicts. Response scope, timestamp/signature, CRC, exact member
bytes/hashes and current source equality were checked. No source-tape completeness certification follows.
The original and corrected predata collectors, interim first-window report, stop markers and reviews remain.
The initial root reparse omitted the lock-intent state, failed before producing a result and was corrected;
failed parser and note are retained, never presented as a pass. All packages passed a bounded private
credential-pattern scan, which cannot prove recognition of every possible secret format.

Separate eight-point recovery of old historical gaps succeeded and is in the supplement. All eight sampled
statuses report 676 fills / 152 settlements, −$15.0099 cumulative P&L and $34.7991 cash. Publication and
event times remain distinct. These points do not fill the eight unknown intervals, establish continuous
coverage or prove no between-sample activity. The earlier failed local `btoa` extraction remains preserved.

Extract initial RELEASE, POSTRELEASE and SUPPLEMENT archives to the same directory for offline
reproduction. Run `cancel-postrelease-20261015/audit.py`, `timing_audit.py`, then
`cancel-release-20261015/audit_final_root.py`; use no network or keys. Initial preparation/release archives
remain unchanged. TJR-MNQ-001 remains blocked on genuine development bars/costs, paper not started/live
disabled; no duplicate research or routine unchanged notification. No automation is marked complete.
