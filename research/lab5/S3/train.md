# S3 touch: reach / dip to a barrier inside a period: TRAIN (train, lab5-v1)

Run 2026-10-09T20:35:30+00:00; PLAN.md sha256 45f1000dd793; markets 483 in the split; decision lag 10 s; Chainlink basis sd 0.000075; trials so far across labs 2-5: 2999.

| cell | n | clusters | /day | win rate | losses | mean price paid | mean model q | mean model edge | mean net | CI95 (clusters) | worst case (rule of 3) | $/bet | $/day | worst $ | latency-stress net (n) | US-fee net |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| m0.02|near|vol1d | 203 | 46 | 4.41 | 0.562 | 89 | 0.568 | 0.637 | 0.061 | -0.2581 | [-0.3995, -0.1315] | 0.3421 | -5.16 | -22.78 | -21.38 | -0.2406 (103) | -0.2579 |
| m0.05|near|vol1d | 151 | 45 | 3.28 | 0.530 | 71 | 0.507 | 0.606 | 0.088 | -0.1803 | [-0.3576, -0.0198] | 0.5614 | -3.61 | -11.84 | -21.38 | -0.1916 (92) | -0.1801 |
| m0.1|near|vol1d | 100 | 41 | 2.17 | 0.490 | 51 | 0.450 | 0.599 | 0.138 | -0.0255 | [-0.3136, 0.3197] | 0.9811 | -0.51 | -1.11 | -21.38 | -0.1724 (64) | -0.0253 |
| m0.02|near|vol7d | 191 | 46 | 4.15 | 0.529 | 90 | 0.541 | 0.622 | 0.072 | -0.2651 | [-0.4150, -0.1206] | 0.4133 | -5.30 | -22.02 | -21.38 | -0.2450 (111) | -0.2649 |
| m0.05|near|vol7d | 147 | 46 | 3.20 | 0.476 | 77 | 0.462 | 0.572 | 0.099 | -0.2279 | [-0.4142, -0.0294] | 0.6450 | -4.56 | -14.57 | -21.38 | -0.2421 (98) | -0.2277 |
| m0.1|near|vol7d | 84 | 36 | 1.83 | 0.357 | 54 | 0.333 | 0.495 | 0.149 | -0.1662 | [-0.4881, 0.1899] | 1.3450 | -3.32 | -6.07 | -21.38 | -0.0831 (53) | -0.1658 |
| m0.02|far|vol1d | 104 | 8 | 2.26 | 0.606 | 41 | 0.567 | 0.643 | 0.068 | -0.0516 | [-0.3142, 0.2689] | 0.5557 | -1.03 | -2.33 | -21.38 | 0.1429 (42) | -0.0514 |
| m0.05|far|vol1d | 84 | 8 | 1.83 | 0.536 | 39 | 0.466 | 0.582 | 0.105 | 0.0687 | [-0.3717, 0.6234] | 0.9713 | 1.37 | 2.51 | -21.37 | -0.1207 (41) | 0.0690 |
| m0.1|far|vol1d | 62 | 8 | 1.35 | 0.532 | 29 | 0.426 | 0.606 | 0.169 | 0.2880 | [-0.5038, 1.1291] | 1.3494 | 5.76 | 7.76 | -21.37 | -0.1955 (40) | 0.2882 |
| m0.02|far|vol7d | 99 | 8 | 2.15 | 0.667 | 33 | 0.592 | 0.672 | 0.071 | 0.0777 | [-0.2477, 0.4121] | 0.5943 | 1.55 | 3.34 | -21.37 | 0.2350 (42) | 0.0779 |
| m0.05|far|vol7d | 72 | 8 | 1.57 | 0.611 | 28 | 0.494 | 0.620 | 0.115 | 0.1876 | [-0.2735, 0.6329] | 0.8959 | 3.75 | 5.87 | -21.37 | 0.3136 (38) | 0.1878 |
| m0.1|far|vol7d | 47 | 8 | 1.02 | 0.660 | 16 | 0.484 | 0.684 | 0.186 | 0.7596 | [-0.1496, 1.6578] | 1.5210 | 15.19 | 15.52 | -21.37 | 0.4645 (24) | 0.7598 |

**Decision:** NO EDGE on TRAIN (no cell qualifies)

Who knows better (PLAN §4; one print per market, the first in the entry window with a model value):

| window | markets | Brier model | Brier market price |
|---|---|---|---|
| far | 215 | 0.0369 | 0.0379 |
| near | 382 | 0.0598 | 0.0525 |

Per contract type (breakdown, not a cell):

| cell | type | n | win rate | mean price | mean q | mean net | total $ |
|---|---|---|---|---|---|---|---|
| m0.02|near|vol1d | down | 94 | 0.628 | 0.641 | 0.704 | -0.2327 | -437.40 |
| m0.02|near|vol1d | up | 109 | 0.505 | 0.505 | 0.580 | -0.2801 | -610.56 |
| m0.05|near|vol1d | down | 68 | 0.618 | 0.631 | 0.726 | -0.1944 | -264.45 |
| m0.05|near|vol1d | up | 83 | 0.458 | 0.407 | 0.508 | -0.1688 | -280.20 |
| m0.1|near|vol1d | down | 42 | 0.548 | 0.521 | 0.665 | -0.1617 | -135.83 |
| m0.1|near|vol1d | up | 58 | 0.448 | 0.398 | 0.552 | 0.0730 | 84.73 |
| m0.02|near|vol7d | down | 88 | 0.614 | 0.613 | 0.685 | -0.1885 | -331.69 |
| m0.02|near|vol7d | up | 103 | 0.456 | 0.480 | 0.568 | -0.3306 | -681.01 |
| m0.05|near|vol7d | down | 67 | 0.552 | 0.537 | 0.640 | -0.1587 | -212.70 |
| m0.05|near|vol7d | up | 80 | 0.412 | 0.399 | 0.515 | -0.2859 | -457.45 |
| m0.1|near|vol7d | down | 35 | 0.400 | 0.388 | 0.542 | -0.1873 | -131.11 |
| m0.1|near|vol7d | up | 49 | 0.327 | 0.295 | 0.461 | -0.1511 | -148.07 |
| m0.02|far|vol1d | down | 52 | 0.788 | 0.730 | 0.798 | 0.0675 | 70.16 |
| m0.02|far|vol1d | up | 52 | 0.423 | 0.405 | 0.488 | -0.1707 | -177.52 |
| m0.05|far|vol1d | down | 40 | 0.725 | 0.598 | 0.712 | 0.1209 | 96.74 |
| m0.05|far|vol1d | up | 44 | 0.364 | 0.347 | 0.463 | 0.0212 | 18.66 |
| m0.1|far|vol1d | down | 30 | 0.600 | 0.483 | 0.659 | 0.0817 | 49.02 |
| m0.1|far|vol1d | up | 32 | 0.469 | 0.373 | 0.557 | 0.4813 | 308.05 |
| m0.02|far|vol7d | down | 51 | 0.784 | 0.691 | 0.759 | 0.0778 | 79.32 |
| m0.02|far|vol7d | up | 48 | 0.542 | 0.487 | 0.580 | 0.0777 | 74.55 |
| m0.05|far|vol7d | down | 38 | 0.737 | 0.587 | 0.707 | 0.1817 | 138.06 |
| m0.05|far|vol7d | up | 34 | 0.471 | 0.390 | 0.522 | 0.1942 | 132.08 |
| m0.1|far|vol7d | down | 25 | 0.760 | 0.575 | 0.765 | 0.3633 | 181.65 |
| m0.1|far|vol7d | up | 22 | 0.545 | 0.381 | 0.591 | 1.2099 | 532.35 |

Readings per PLAN §4. One bet per market per cell: the first buyable print inside the entry window whose model edge (model probability of that side minus the price paid, print + 0.01, minus the taker fee per share) exceeds the margin; $20 tickets held to settlement; 'net' = profit per $1 staked after fees; CI by cluster bootstrap (bets settled by one price draw resample together); 'latency stress' = the same signal executed at lab 4's rule (first buyable print for the side >= 10 s later, + 0.01); 'US-fee net' = re-costed at Polymarket US's 0.0695. Nothing here is a live trade.
