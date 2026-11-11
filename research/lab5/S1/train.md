# S1 threshold / range at a Binance close (above, below, between): TRAIN (train, lab5-v1)

Run 2026-10-09T20:35:29+00:00; PLAN.md sha256 45f1000dd793; markets 774 in the split; decision lag 10 s; Chainlink basis sd 0.000075; trials so far across labs 2-5: 2975.

| cell | n | clusters | /day | win rate | losses | mean price paid | mean model q | mean model edge | mean net | CI95 (clusters) | worst case (rule of 3) | $/bet | $/day | worst $ | latency-stress net (n) | US-fee net |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| m0.02|near|vol1d | 274 | 42 | 5.96 | 0.573 | 117 | 0.565 | 0.613 | 0.039 | -0.0054 | [-0.2530, 0.2973] | 0.7527 | -0.11 | -0.64 | -21.37 | 0.0319 (196) | -0.0052 |
| m0.05|near|vol1d | 199 | 42 | 4.33 | 0.578 | 84 | 0.597 | 0.675 | 0.068 | -0.1247 | [-0.3442, 0.1411] | 0.5232 | -2.49 | -10.79 | -21.36 | -0.1927 (150) | -0.1245 |
| m0.1|near|vol1d | 90 | 32 | 1.96 | 0.478 | 47 | 0.540 | 0.678 | 0.126 | -0.2984 | [-0.5491, -0.0254] | 0.4656 | -5.97 | -11.67 | -21.33 | -0.3091 (74) | -0.2981 |
| m0.02|near|vol7d | 278 | 42 | 6.04 | 0.554 | 124 | 0.569 | 0.612 | 0.034 | -0.0808 | [-0.3535, 0.2642] | 0.6807 | -1.62 | -9.76 | -21.38 | 0.0098 (215) | -0.0805 |
| m0.05|near|vol7d | 198 | 42 | 4.30 | 0.540 | 91 | 0.587 | 0.659 | 0.063 | -0.2514 | [-0.4328, -0.0713] | 0.4022 | -5.03 | -21.65 | -21.36 | -0.2065 (164) | -0.2512 |
| m0.1|near|vol7d | 97 | 33 | 2.11 | 0.412 | 57 | 0.503 | 0.632 | 0.118 | -0.2821 | [-0.5940, 0.1184] | 0.7488 | -5.64 | -11.90 | -21.35 | -0.2540 (86) | -0.2818 |
| m0.02|far|vol1d | 530 | 42 | 11.52 | 0.489 | 271 | 0.542 | 0.600 | 0.049 | -0.2855 | [-0.3895, -0.1757] | 0.5047 | -5.71 | -65.78 | -21.37 | -0.2302 (152) | -0.2852 |
| m0.05|far|vol1d | 372 | 41 | 8.09 | 0.487 | 191 | 0.545 | 0.639 | 0.084 | -0.3040 | [-0.4392, -0.1638] | 0.4679 | -6.08 | -49.16 | -21.37 | -0.1601 (119) | -0.3037 |
| m0.1|far|vol1d | 161 | 40 | 3.50 | 0.522 | 77 | 0.568 | 0.721 | 0.141 | -0.2512 | [-0.4248, -0.0573] | 0.4462 | -5.02 | -17.59 | -21.37 | -0.2240 (55) | -0.2510 |
| m0.02|far|vol7d | 432 | 41 | 9.39 | 0.433 | 245 | 0.448 | 0.495 | 0.037 | -0.1654 | [-0.3078, -0.0376] | 0.9836 | -3.31 | -31.07 | -21.38 | -0.2382 (144) | -0.1651 |
| m0.05|far|vol7d | 202 | 34 | 4.39 | 0.401 | 121 | 0.411 | 0.498 | 0.076 | -0.1463 | [-0.4032, 0.1296] | 1.1739 | -2.93 | -12.85 | -21.37 | -0.2104 (78) | -0.1460 |
| m0.1|far|vol7d | 60 | 20 | 1.30 | 0.467 | 32 | 0.429 | 0.580 | 0.139 | -0.2812 | [-0.6284, 0.0983] | 0.5216 | -5.62 | -7.33 | -21.37 | -0.3320 (32) | -0.2809 |

**Decision:** NO EDGE on TRAIN (no cell qualifies)

Who knows better (PLAN §4; one print per market, the first in the entry window with a model value):

| window | markets | Brier model | Brier market price |
|---|---|---|---|
| far | 705 | 0.1099 | 0.1059 |
| near | 706 | 0.0559 | 0.0558 |

Per contract type (breakdown, not a cell):

| cell | type | n | win rate | mean price | mean q | mean net | total $ |
|---|---|---|---|---|---|---|---|
| m0.02|near|vol1d | above | 159 | 0.610 | 0.601 | 0.643 | 0.0001 | 0.25 |
| m0.02|near|vol1d | between | 115 | 0.522 | 0.516 | 0.572 | -0.0129 | -29.67 |
| m0.05|near|vol1d | above | 106 | 0.651 | 0.647 | 0.721 | -0.0911 | -193.05 |
| m0.05|near|vol1d | between | 93 | 0.495 | 0.539 | 0.624 | -0.1631 | -303.45 |
| m0.1|near|vol1d | above | 44 | 0.523 | 0.594 | 0.726 | -0.2482 | -218.38 |
| m0.1|near|vol1d | between | 46 | 0.435 | 0.488 | 0.631 | -0.3464 | -318.66 |
| m0.02|near|vol7d | above | 164 | 0.622 | 0.612 | 0.651 | -0.0313 | -102.58 |
| m0.02|near|vol7d | between | 114 | 0.456 | 0.506 | 0.556 | -0.1519 | -346.41 |
| m0.05|near|vol7d | above | 105 | 0.581 | 0.605 | 0.675 | -0.1784 | -374.65 |
| m0.05|near|vol7d | between | 93 | 0.495 | 0.566 | 0.642 | -0.3339 | -621.04 |
| m0.1|near|vol7d | above | 46 | 0.457 | 0.508 | 0.630 | -0.0939 | -86.34 |
| m0.1|near|vol7d | between | 51 | 0.373 | 0.498 | 0.634 | -0.4518 | -460.85 |
| m0.02|far|vol1d | above | 387 | 0.514 | 0.549 | 0.605 | -0.2815 | -2178.91 |
| m0.02|far|vol1d | between | 143 | 0.420 | 0.523 | 0.587 | -0.2962 | -847.09 |
| m0.05|far|vol1d | above | 272 | 0.526 | 0.567 | 0.657 | -0.2905 | -1580.42 |
| m0.05|far|vol1d | between | 100 | 0.380 | 0.486 | 0.593 | -0.3405 | -681.02 |
| m0.1|far|vol1d | above | 111 | 0.586 | 0.621 | 0.767 | -0.2742 | -608.70 |
| m0.1|far|vol1d | between | 50 | 0.380 | 0.449 | 0.618 | -0.2003 | -200.27 |
| m0.02|far|vol7d | above | 307 | 0.459 | 0.461 | 0.507 | -0.1513 | -928.94 |
| m0.02|far|vol7d | between | 125 | 0.368 | 0.415 | 0.463 | -0.2000 | -500.12 |
| m0.05|far|vol7d | above | 131 | 0.405 | 0.402 | 0.491 | -0.1956 | -512.38 |
| m0.05|far|vol7d | between | 71 | 0.394 | 0.428 | 0.513 | -0.0555 | -78.76 |
| m0.1|far|vol7d | above | 36 | 0.500 | 0.466 | 0.621 | -0.3490 | -251.28 |
| m0.1|far|vol7d | between | 24 | 0.417 | 0.374 | 0.518 | -0.1794 | -86.12 |

Readings per PLAN §4. One bet per market per cell: the first buyable print inside the entry window whose model edge (model probability of that side minus the price paid, print + 0.01, minus the taker fee per share) exceeds the margin; $20 tickets held to settlement; 'net' = profit per $1 staked after fees; CI by cluster bootstrap (bets settled by one price draw resample together); 'latency stress' = the same signal executed at lab 4's rule (first buyable print for the side >= 10 s later, + 0.01); 'US-fee net' = re-costed at Polymarket US's 0.0695. Nothing here is a live trade.
