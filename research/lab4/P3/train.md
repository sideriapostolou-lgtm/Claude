# P3 crypto up/down, last minutes: TRAIN (train, lab4-v1 + Amendments 1-3)

Run 2026-10-09T18:01:21+00:00; PLAN.md sha256 6785d8d2b857; markets in split 39644 (families: {'crypto': 18226, 'sports': 18064, 'weather': 1544, 'culture': 628, 'none': 393, 'finance': 275, 'politics': 250, 'tech': 143, 'economics': 87, 'mentions': 34}); trials so far across labs 2-4: 2873.

Tape coverage: 40350 of 40350 eligible markets (100.0 %).

| cell | n | events | missed | /day | win rate | losses | mean p | gap | mean net | CI95 (events) | worst case (rule of 3) | bid-side share (old rule) | $/trade | worst $ | streak | lock h | daily Sharpe | DD $ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| theta0.95|H0.0166667 | 10448 | 10439 | 3403 | 227.13 | 0.960 | 421 | 0.959 | 0.001 | -0.0013 | [-0.0062, 0.0041] | 0.0410 | 0.312 | -0.03 | -21.37 | 3 | 0.02 | -1.66 | -808.71 |
| theta0.95|H0.0833333 | 14131 | 14115 | 2093 | 307.20 | 0.949 | 726 | 0.950 | -0.001 | -0.0052 | [-0.0098, -0.0007] | 0.0490 | 0.281 | -0.10 | -21.37 | 4 | 0.04 | -6.91 | -1666.98 |
| theta0.97|H0.0166667 | 9185 | 9178 | 4313 | 199.67 | 0.970 | 271 | 0.969 | 0.001 | -0.0011 | [-0.0055, 0.0031] | 0.0294 | 0.326 | -0.02 | -21.39 | 3 | 0.02 | -1.42 | -483.73 |
| theta0.97|H0.0833333 | 12718 | 12702 | 3131 | 276.48 | 0.965 | 441 | 0.966 | -0.001 | -0.0023 | [-0.0073, 0.0036] | 0.0336 | 0.289 | -0.05 | -21.39 | 4 | 0.03 | -2.43 | -803.76 |
| theta0.99|H0.0166667 | 6097 | 6094 | 6564 | 132.54 | 0.980 | 122 | 0.978 | 0.002 | 0.0010 | [-0.0037, 0.0058] | 0.0213 | 0.408 | 0.02 | -21.39 | 2 | 0.02 | 1.17 | -207.31 |
| theta0.99|H0.0833333 | 9066 | 9054 | 5931 | 197.09 | 0.979 | 190 | 0.980 | -0.001 | -0.0000 | [-0.0052, 0.0071] | 0.0213 | 0.399 | -0.00 | -21.39 | 2 | 0.03 | -0.01 | -377.92 |

**Decision:** NO EDGE on TRAIN (no cell qualifies)

Readings per PLAN §4 and Amendment 3. 'gap' = win rate minus mean execution price (the gross edge before fees); 'net' = profit per $1 at risk after the venue's taker fee; one trade per market per cell, $20 tickets, 10 s latency, buyable prints only; CI by event bootstrap; 'worst case' = (1 - 3/n) x mean win - 3/n; 'bid-side share' = how often the old side-blind rule would have filled at a price no buyer could get. Nothing here is a live trade.
