# Independent completed-day actual-fill review

The bounded native evidence reconciles to a loss, and does not support increasing size or changing an entry threshold. Recommended next strategy step: preserve this complete development cohort, then predeclare a prospective, unchanged-policy first-fill assessment with exact intent/fill joins and explicit markout/queue coverage. Keep the daily stop and money limits unchanged. The separate synchronous settlement snapshot performance patch has its own exact review; it does not establish a trading edge.

## Scope and independent method

`audit_oct15_cohort.py` reads the 92 original native wrappers named by the extraction manifest, directly parses their structured standalone event messages, deduplicates by native identity/time, and checks conflicting variants. It does not use the manifest's financial calculations or fair joins. It separately reads the two native endpoint status wrappers. All 1,105 checks pass. It reads only these local files and writes only `astra/OCT15_COHORT_ANALYSIS.json`; this review and the run log are separate generated artifacts. No account/network calls, source changes, secrets or sealed research TEST data.

The capture is the half-open publication interval October 15, 2026 00:00 UTC through October 16 00:00 UTC. Event payload times remain distinct. There are 302 unique fills, 7,252 order events, 71 settlements, no conflicting identity payloads and no exact-header parse failures. All 302 fills have exactly one joined durable intent with matching side/window and an acknowledged order ID; 262 intent events contain fair. This extraction concerns actual owned orders and fills, not simulated fills.

## Accounting

| Cohort | Cost | Fees | Payout | Actual P&L |
|---|---:|---:|---:|---:|
| 69 windows with observed day fills | $384.9792 | $0.8455 | $380.7700 | −$5.0547 |
| Inherited `KXBTC15M-26OCT142000-00` pair, no day fill | $0.9900 | $0 | $1.0000 | +$0.0100 |
| `KXBTC15M-26OCT151415-15`, zero-share settlement | $0 | $0 | $0 | $0 |
| All 71 settlements | $385.9692 | $0.8455 | $381.7700 | −$5.0447 |

For every one of the 69 filled windows, observed fill cost, fees and both side quantities match its own final settlement. Settlement payout minus cost and fees matches reported P&L. The two no-fill settlements must remain separate: assigning their payout to the 302 observed fills creates a spurious $1 difference.

The 45 positive traded windows earned $24.4509; the 24 negative windows lost $29.5056. All losses are retained. Forty-three windows ended with equal side quantities, including 14 negative-P&L windows: completion of a pair does not imply positive pair economics. No claim that an alternative hedge or cancel would have filled.

All-settlement accounting decomposition is locked +$4.501150769 and directional −$9.545850769, totaling −$5.0447. These components are not independently tradable strategy returns. The 69-window decomposition excludes the inherited pair's +$0.01 locked amount.

Native status fill counters move 524→826 cumulatively and 0→302 for the day. First status at 00:00:13.540524065 UTC already contains the inherited +$0.01 settlement; last captured status at 23:59:46.348372228 UTC reports day −$5.0447. Consequently cumulative P&L change is −$5.0547, not the full day's −$5.0447. These are counter/snapshot concordance checks, not certification of every account event.

## First-fill findings and limits

For each of the 69 traded windows, the earliest observed venue fill timestamp is unique; all are maker fills linked to `rest` intents. All 69 first fills have exact-client-ID decision-side fair and a final outcome. No forecast probability, spot or volatility is carried from another record.

- First filled side won expiry in 32/69 windows (46.38%); it lost in 37/69.
- Mean recorded side fair at the first filled order's decision was 50.38%; mean first fill price was 46.64%.
- Actual whole-window outcomes were 45 positive and 24 negative, because later fills and paired settlement matter.

These are unweighted per-window descriptions. The first side's eventual expiry result is not that fill's realized return, and mean fair is from decision time rather than fill time. The selection is orders that actually filled; the record does not establish the outcome distribution of unfilled quotes. A 69-window, mixed-version, single-day development cohort cannot establish miscalibration, queue adverse selection, a profitable alternative threshold, or a causal effect of later PR69/PR70 protections. No hypothetical held-first-leg P&L, resimulated fills or threshold search was performed.

A suitable followup freezes the policy/source and a future interval before viewing outcomes, joins actual initial fills to their own intents, and reports both measured and missing fixed-horizon markouts. Queue observations can characterize queue conditions only where actually sampled; absence cannot be reconstructed. Include every traded window and stopped/no-fill windows separately, and retain gaps. Any discovered rule requires a separately declared validation plan before live application; this audit is not authority to resume or enlarge the desk.

## Capture limitations

The native wrappers are service-scoped; latest deployment metadata is not per-event deployment attribution. The day precedes the later protections and spans earlier changes. The extractor preserves three invalid `T24:00Z` request errors and the corrected recaptures; saturated parent order intervals were split. This audit independently re-parses all saved messages but does not independently certify provider search completeness or that every intended query had perfect coverage.

The panel scorecard is a different, coverage-filtered population: its −$10.0028 must not replace the full actual settlement sum. Root reports 29 complete of 88 discovered and 59 gaps for that scorecard; those counters are not a claim that only 29 of the 69 observed traded windows reconcile financially. The latest endpoint remains before UTC midnight and labels the day open. Counter concordance and per-window financial reconciliation do not certify all-day market discovery, full book/queue history, venue tape freshness, or calibration coverage. No p/spot/sigma snapshot was requested in this capture.
