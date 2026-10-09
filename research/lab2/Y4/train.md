# Y4 train

- **Split:** `train`; usable coins: 3863; span: 4.00 days.
- **Written:** 2026-10-09 04:53:48 UTC; runtime 391.1 s; PREREG sha256 `44fd9154d882`; trials in the ledger: 2603.
- **Overall Y4 status:** NO EDGE (nothing qualified on TRAIN).

## Event counts (no outcomes)

- Coins 3863; decision minutes at ages 10-115 min: 405670.

| set | touches BREAK / HOLD / REJECT | touch coins | BREAK events (bars, coins) | RETEST events (bars, coins) |
|---|---|---:|---|---|
| round | 489 / 581 / 501 | 1021 | 831, 601 | 330, 271 |
| shifted | 552 / 666 / 488 | 1121 | 864, 617 | 316, 247 |

- round: BREAK events by level {'250k': 121, '500k': 91, '50k': 130, '10k': 94, '25k': 127, '100k': 153, '1M': 102, '10M': 1, '2.5M': 10, '5M': 2}; RETEST events by level {'250k': 57, '50k': 63, '10k': 34, '100k': 67, '25k': 60, '500k': 37, '1M': 11, '2.5M': 1}.
- shifted: BREAK events by level {'320k': 110, '640k': 172, '1.28M': 75, '64k': 124, '12.8k': 93, '32k': 131, '128k': 146, '3.2M': 10, '6.4M': 2, '12.8M': 1}; RETEST events by level {'320k': 54, '12.8k': 32, '64k': 50, '32k': 59, '640k': 32, '128k': 83, '1.28M': 5, '3.2M': 1}.
- At each coin's first round BREAK (decision-time state, no later price): market cap median $109,644 (IQR $30,990-$359,066, n 601); age median 27 min (IQR 16 min-47 min, n 601); $20 round trip median 3.47% (IQR 3.16%-3.78%, n 601); fee tier (bps, one side) {'115': 71, '100': 116, '120': 194, '125': 167, '105': 21, '35': 1, '85': 5, '110': 22, '95': 3, '65': 1}.

## Event study (PREREG 7: the folklore, gross mid-price moves)

- Observations 3277 from 1335 coins.

| set | class | H | n | coins | mean | median | 95% CI |
|---|---|---:|---:|---:|---:|---:|---|
| round | BREAK | 15 | 489 | 401 | -13.50% | -17.72% | [-20.7, -6.4] |
| round | BREAK | 60 | 489 | 401 | -29.10% | -59.36% | [-43.8, -8.7] |
| round | HOLD | 15 | 581 | 463 | -19.32% | -10.51% | [-24.9, -13.5] |
| round | HOLD | 60 | 581 | 463 | -61.56% | -99.78% | [-71.2, -50.6] |
| round | REJECT | 15 | 501 | 387 | -13.30% | -18.89% | [-19.0, -7.8] |
| round | REJECT | 60 | 501 | 387 | -36.05% | -48.18% | [-42.3, -29.6] |
| shifted | BREAK | 15 | 552 | 463 | -14.18% | -20.87% | [-21.2, -7.5] |
| shifted | BREAK | 60 | 552 | 463 | -39.20% | -70.18% | [-51.0, -23.6] |
| shifted | HOLD | 15 | 666 | 527 | -14.87% | +0.12% | [-20.2, -9.3] |
| shifted | HOLD | 60 | 666 | 527 | -60.52% | -99.67% | [-68.6, -51.4] |
| shifted | REJECT | 15 | 488 | 387 | -13.50% | -18.72% | [-19.4, -7.1] |
| shifted | REJECT | 60 | 488 | 387 | -32.86% | -51.57% | [-42.9, -20.0] |

| roundness effect (round − shifted) | diff | 95% CI |
|---|---:|---|
| BREAK|h15 | +0.69% | [-6.2, +7.6] |
| BREAK|h60 | +10.10% | [-0.1, +19.9] |
| HOLD|h15 | -4.45% | [-11.7, +2.3] |
| HOLD|h60 | -1.04% | [-10.0, +8.9] |
| REJECT|h15 | +0.20% | [-7.4, +6.9] |
| REJECT|h60 | -3.19% | [-15.3, +7.3] |
| spread BREAK − REJECT round|h15 | -0.20% | [-8.5, +8.6] |
| spread BREAK − REJECT shifted|h15 | -0.68% | [-9.8, +8.0] |
| spread BREAK − REJECT round|h60 | +6.95% | [-8.7, +27.3] |
| spread BREAK − REJECT shifted|h60 | -6.34% | [-22.3, +11.7] |
| spread round − shifted h15 | +0.48% | [-9.9, +11.8] |
| spread round − shifted h60 | +13.29% | [-2.8, +31.3] |

- $20 round trip at round BREAK touches: median 3.47% (IQR 2.94%-3.80%, n 489).

## Configs

| role | config | n | coins | mean | 90% CI coin | 90% CI 6-h block | w/o top 2 | band-matched diff | unmatched diff | costs ×1.5 | open fills | gross move | cost | censored |
|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| break|h15|round | break|h15|round | 601 | 601 | -29.4% | [-32.6, -26.1] | [-33.7, -24.9] | -30.4% | -4.6% | -8.2% | -30.7% | -15.7% | -26.8% | +2.6% | +0% |
| break|h60|round | break|h60|round | 601 | 601 | -35.5% | [-40.7, -28.9] | [-42.7, -25.2] | -39.5% | +1.3% | -4.0% | -36.7% | -25.2% | -33.1% | +2.5% | +0% |
| retest|h15|round | retest|h15|round | 271 | 271 | -22.9% | [-25.4, -20.4] | [-26.4, -19.0] | -23.8% | +2.2% | -3.6% | -24.3% | -5.6% | -20.0% | +2.9% | +0% |
| retest|h60|round | retest|h60|round | 271 | 271 | -25.6% | [-28.2, -22.8] | [-29.0, -22.0] | -27.0% | +4.0% | +2.6% | -26.9% | -14.9% | -22.8% | +2.8% | +0% |
| break|h15|shifted | break|h15|shifted | 617 | 617 | -32.3% | [-35.9, -28.7] | [-37.2, -27.5] | -33.5% | -7.4% | -10.6% | -33.5% | -18.6% | -29.9% | +2.4% | +0% |
| break|h60|shifted | break|h60|shifted | 617 | 617 | -41.0% | [-47.3, -33.5] | [-50.1, -29.3] | -46.3% | -1.5% | -8.9% | -42.1% | -29.9% | -38.8% | +2.3% | +0% |
| retest|h15|shifted | retest|h15|shifted | 247 | 247 | -26.0% | [-29.9, -21.7] | [-31.3, -19.7] | -28.5% | -2.0% | -8.5% | -27.3% | -7.4% | -23.2% | +2.7% | +0% |
| retest|h60|shifted | retest|h60|shifted | 247 | 247 | -24.7% | [-31.6, -14.8] | [-33.0, -9.5] | -30.6% | +3.9% | +1.9% | -26.1% | -7.9% | -21.8% | +2.8% | +0% |

## Pre-registered predictions (PREREG 7.3; reports, never decisive)

- P1_round_break_continues_more: folklore supported = False.
- P2_round_reject_falls_more: folklore supported = False.
- P3_round_break_pays_for_costs: folklore supported = False.
- P4_a_round_config_qualifies: folklore supported = False.
- Y4 expected: no roundness effect, breaks do not pay for costs, nothing qualifies (all False).

## Decision

- **NO_CONFIG**.
- break|h15|round: n 601, coins 601, mean -29.4%, 90% CI low -32.6%, band-matched diff -4.6%, round − shifted +2.9% (twin n 617), qualifies False.
- break|h60|round: n 601, coins 601, mean -35.5%, 90% CI low -40.7%, band-matched diff +1.3%, round − shifted +5.5% (twin n 617), qualifies False.
- retest|h15|round: n 271, coins 271, mean -22.9%, 90% CI low -25.4%, band-matched diff +2.2%, round − shifted +3.1% (twin n 247), qualifies False.
- retest|h60|round: n 271, coins 271, mean -25.6%, 90% CI low -28.2%, band-matched diff +4.0%, round − shifted -0.9% (twin n 247), qualifies False.
- Shortlist written: False (candidate None, twin None).
- Reason: a powered round config failed the mean / top-2 / placebo / twin / censoring bars.
