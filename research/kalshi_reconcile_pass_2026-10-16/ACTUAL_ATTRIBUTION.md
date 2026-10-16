# Actual fill attribution — completed October 15 UTC cohort

The 45 profitable windows earned **$24.4509** (average $0.5434); the 24 losing windows lost **$29.5056** (average $1.2294). The average losing window was about 2.26 times the average winning window. Actual total for the 69 day-filled windows: **−$5.0547**, excluding the inherited +$0.01 pair and the zero-share settlement already separated in the frozen audit.

The following is additive attribution of actual purchased contracts' winning-side gross settlement payout minus their actual cost and fee. It is **not the return of a strategy without locks, without balancing orders, or holding only first fills**. Removing orders would change later inventory, caps, decisions and risk. Early paired cash credits and final residual cash are counted only once through gross payout; the table does not identify when cash was credited.

| Actual joined order type | Fill events | Contracts | Cost | Fees | Gross payout | Attributed P&L |
|---|---:|---:|---:|---:|---:|---:|
| Ordinary maker | 262 | 662.69 | $310.0192 | $0 | $310.77 | +$0.7508 |
| Ordinary take | 0 | 0 | $0 | $0 | $0 | $0 |
| Lock | 40 | 121.00 | $74.9600 | $0.8455 | $70.00 | −$5.8055 |
| Unknown kind | 0 | 0 | $0 | $0 | $0 | $0 |
| Total | 302 | 783.69 | $384.9792 | $0.8455 | $380.77 | −$5.0547 |

All kinds join through one exact client-ID durable intent with matching side/window. All maker fills have native `is_taker=false`; all lock fills have `is_taker=true`. Forty lock fills occurred in 39 windows; this is not a contradiction with the panel's 39 filled lock orders. One order can fill more than once. Every fill has its own window's final outcome, and every window's quantities/cost/fees/payout reconcile to its settlement.

## First fill and inventory role

| Allocation of actual fills | Contracts | Cost | Fees | Gross payout | Attributed P&L |
|---|---:|---:|---:|---:|---:|
| First actual fill in each window (69 events) | 195.84 | $93.1032 | $0 | $96.98 | +$3.8768 |
| Subsequent fills (233 events) | 587.85 | $291.8760 | $0.8455 | $283.79 | −$8.9315 |
| Every fill on same side as first fill | 403.34 | $195.1682 | $0.3953 | $211.77 | +$16.2065 |
| Every fill opposite the first fill | 380.35 | $189.8110 | $0.4502 | $169.00 | −$21.2612 |

Each pair of rows is a separate partition of the same actual total; do not add across partitions. The same-side partition includes later orders and may include balancing fills. “Opposite first side” does not mean “balancing” when the inventory direction has changed. First-fill size varies, so its positive dollar attribution is compatible with only 32 of 69 first sides winning expiry. Neither fact establishes a first-fill trading policy's profitability.

For a separate running-inventory partition, sort observed fills by venue timestamp. Allocate each fill's quantity toward equality up to the prefill opposite-minus-own quantity; any remainder starts or extends an imbalance. This is **observed venue-fill sequence**, not the controller's decision-time inventory, pending liability, or guard decision. Batch reconciliation and publication can differ from venue chronology.

| Observed quantity role | Contracts | Cost | Fees | Gross payout | Attributed P&L |
|---|---:|---:|---:|---:|---:|
| From equality or extending imbalance | 405.00 | $188.0961 | $0 | $189.43 | +$1.3339 |
| Toward equal inventory | 373.69 | $192.4331 | $0.8112 | $186.34 | −$6.9043 |
| Unknown ordering: two same-timestamp fills | 5.00 | $4.4500 | $0.0343 | $5.00 | +$0.5157 |

The known balancing quantity comprises ordinary maker attribution −$0.5831 and lock attribution −$6.3212. Two tied lock fills remain unknown for this role, with +$0.5157 attribution. A single fill may cross equality; its actual fee is allocated pro rata. Consequently per-role fill counts overlap and cannot be summed as distinct events. No tied timestamp is broken into claimed venue execution order.

## Worst five actual windows

Side costs below exclude fees; all-in pair unit cost includes fees and uses final per-side average cost. This is the same additive accounting convention as settlement, not chronological matching of individual contracts.

| Window suffix | Final Up/Down qty | Up/Down cost | Fee | Payout | Actual P&L | Pairs / all-in pair unit cost | Pair / residual P&L |
|---|---:|---:|---:|---:|---:|---:|---:|
| `26OCT150745-45` | 5 / 5 | $4.750 / $3.000 | $0.0167 | $5 | −$2.7667 | 5 / $1.55334 | −$2.7667 / $0 |
| `26OCT150030-30` | 0 / 5 | $0 / $2.450 | $0 | $0 | −$2.4500 | 0 / n/a | $0 / −$2.4500 |
| `26OCT150215-15` | 5 / 5 | $4.835 / $2.450 | $0.0112 | $5 | −$2.2962 | 5 / $1.45924 | −$2.2962 / $0 |
| `26OCT142315-15` | 5 / 5 | $2.300 / $4.830 | $0.0115 | $5 | −$2.1415 | 5 / $1.42830 | −$2.1415 / $0 |
| `26OCT150045-45` | 0 / 5 | $0 / $1.850 | $0 | $0 | −$1.8500 | 0 / n/a | $0 / −$1.8500 |

All tickers have the `KXBTC15M-` prefix. The three paired examples began on the ultimately losing side. Their actual winning-side late lock legs contribute **+$0.2333, +$0.1538 and +$0.1585**, respectively; their initial losing sides contribute −$3.00, −$2.45 and −$2.30. Thus even the cohort's negative aggregate lock attribution cannot be used to say that locks caused these worst losses. The other two windows retained unmatched Down inventory and lost it at expiry. The JSON preserves each worst window's full fill sequence, intent kind, side quantity, cost, fee, outcome and pair/residual allocation.

## Verification and bounds

`audit_actual_attribution.py` independently parses all 92 saved native structured wrappers and writes only `ACTUAL_ATTRIBUTION.json`. **889 checks pass**, including exact kind/identity joins, all per-window financial totals and every attribution partition's additive total. No unknown kinds or missing final outcomes exist within these 302 observed fills. The frozen earlier cohort audit is unchanged.

Coverage remains the prior bounded publication-day, mixed earlier-source development cohort. Native counter concordance is not a full book/account history certificate. First-fill and subsequent-role arithmetic does not establish an edge, calibration, causal adverse selection, or executable counterfactual. This analysis supplies no new policy, sizing, stop-reset or production authorization, and performs no threshold search or sealed TEST read.
