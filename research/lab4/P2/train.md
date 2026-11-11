# P2 late-game sports: TRAIN (train, lab4-v1 + Amendments 1-3)

Run 2026-10-09T18:00:50+00:00; PLAN.md sha256 6785d8d2b857; markets in split 39644 (families: {'crypto': 18226, 'sports': 18064, 'weather': 1544, 'culture': 628, 'none': 393, 'finance': 275, 'politics': 250, 'tech': 143, 'economics': 87, 'mentions': 34}); trials so far across labs 2-4: 2867.

Tape coverage: 40350 of 40350 eligible markets (100.0 %).

| cell | n | events | missed | /day | win rate | losses | mean p | gap | mean net | CI95 (events) | worst case (rule of 3) | bid-side share (old rule) | $/trade | worst $ | streak | lock h | daily Sharpe | DD $ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| theta0.95|H0.25 (oracle-timed, not selectable) | 507 | 160 | 111 | 11.02 | 0.972 | 14 | 0.973 | -0.001 | -0.0024 | [-0.0187, 0.0120] | 0.0199 | 0.545 | -0.05 | -20.13 | 1 | 2.55 | -0.87 | -94.57 |
| theta0.95|H0.5 (oracle-timed, not selectable) | 531 | 173 | 155 | 11.54 | 0.966 | 18 | 0.973 | -0.007 | -0.0088 | [-0.0271, 0.0075] | 0.0202 | 0.496 | -0.18 | -20.13 | 2 | 2.80 | -2.86 | -164.64 |
| theta0.95|H1 (oracle-timed, not selectable) | 561 | 192 | 203 | 12.20 | 0.977 | 13 | 0.973 | 0.004 | 0.0025 | [-0.0110, 0.0153] | 0.0208 | 0.501 | 0.05 | -20.13 | 2 | 3.32 | 1.07 | -61.38 |
| theta0.95|H2 (oracle-timed, not selectable) | 728 | 333 | 302 | 15.83 | 0.977 | 17 | 0.969 | 0.008 | 0.0065 | [-0.0051, 0.0178] | 0.0264 | 0.478 | 0.13 | -20.16 | 2 | 4.16 | 2.97 | -105.74 |
| theta0.95|Hinf | 14255 | 7437 | 3574 | 309.89 | 0.932 | 966 | 0.944 | -0.012 | -0.0153 | [-0.0206, -0.0099] | 0.0566 | 0.420 | -0.31 | -20.99 | 5 | 2.16 | -13.49 | -4194.95 |
| theta0.97|H0.25 (oracle-timed, not selectable) | 313 | 101 | 74 | 6.80 | 0.984 | 5 | 0.985 | -0.001 | -0.0018 | [-0.0173, 0.0107] | 0.0047 | 0.514 | -0.04 | -20.03 | 1 | 2.52 | -0.93 | -54.61 |
| theta0.97|H0.5 (oracle-timed, not selectable) | 335 | 107 | 102 | 7.28 | 0.982 | 6 | 0.985 | -0.003 | -0.0033 | [-0.0220, 0.0114] | 0.0059 | 0.478 | -0.07 | -20.03 | 1 | 2.76 | -1.45 | -66.54 |
| theta0.97|H1 (oracle-timed, not selectable) | 358 | 130 | 143 | 7.78 | 0.986 | 5 | 0.984 | 0.002 | 0.0021 | [-0.0109, 0.0139] | 0.0078 | 0.501 | 0.04 | -20.03 | 1 | 3.29 | 1.14 | -41.97 |
| theta0.97|H2 (oracle-timed, not selectable) | 524 | 269 | 229 | 11.39 | 0.985 | 8 | 0.978 | 0.007 | 0.0058 | [-0.0056, 0.0166] | 0.0156 | 0.495 | 0.12 | -20.23 | 2 | 4.06 | 2.46 | -83.71 |
| theta0.97|Hinf | 13276 | 7118 | 4301 | 288.61 | 0.954 | 615 | 0.964 | -0.010 | -0.0121 | [-0.0167, -0.0074] | 0.0360 | 0.475 | -0.24 | -20.99 | 5 | 2.11 | -13.57 | -3160.97 |
| theta0.99|H0.25 (oracle-timed, not selectable) | 133 | 61 | 42 | 2.89 | 1.000 | 0 | 0.994 | 0.006 | 0.0059 | [0.0051, 0.0068] | -0.0168 | 0.469 | 0.12 | 0.02 | 0 | 2.52 | 23.90 | 0.00 |
| theta0.99|H0.5 (oracle-timed, not selectable) | 150 | 70 | 57 | 3.26 | 0.993 | 1 | 0.994 | -0.000 | -0.0005 | [-0.0175, 0.0074] | -0.0139 | 0.435 | -0.01 | -20.01 | 1 | 2.76 | -0.27 | -19.12 |
| theta0.99|H1 (oracle-timed, not selectable) | 176 | 89 | 79 | 3.83 | 0.994 | 1 | 0.993 | 0.001 | 0.0010 | [-0.0120, 0.0079] | -0.0104 | 0.471 | 0.02 | -20.01 | 1 | 3.26 | 0.60 | -19.30 |
| theta0.99|H2 (oracle-timed, not selectable) | 281 | 174 | 173 | 6.11 | 0.993 | 2 | 0.991 | 0.002 | 0.0018 | [-0.0092, 0.0097] | -0.0018 | 0.559 | 0.04 | -20.02 | 1 | 3.72 | 1.02 | -24.56 |
| theta0.99|Hinf | 10168 | 5878 | 5581 | 221.04 | 0.980 | 200 | 0.983 | -0.003 | -0.0042 | [-0.0075, -0.0013] | 0.0156 | 0.573 | -0.08 | -20.97 | 3 | 2.05 | -6.92 | -911.76 |

**Decision:** NO EDGE on TRAIN (no cell qualifies)

Readings per PLAN §4 and Amendment 3. 'gap' = win rate minus mean execution price (the gross edge before fees); 'net' = profit per $1 at risk after the venue's taker fee; one trade per market per cell, $20 tickets, 10 s latency, buyable prints only; CI by event bootstrap; 'worst case' = (1 - 3/n) x mean win - 3/n; 'bid-side share' = how often the old side-blind rule would have filled at a price no buyer could get. Nothing here is a live trade.
