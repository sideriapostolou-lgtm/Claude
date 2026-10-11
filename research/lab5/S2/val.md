# S2 up-or-down windows (5m, 15m, 1h, 4h, 1d): VAL (val, lab5-v1)

Run 2026-10-09T20:39:28+00:00; PLAN.md sha256 45f1000dd793; markets 0 in the split; decision lag 10 s; Chainlink basis sd 0.000075; trials so far across labs 2-5: 2999.

| cell | n | clusters | /day | win rate | losses | mean price paid | mean model q | mean model edge | mean net | CI95 (clusters) | worst case (rule of 3) | $/bet | $/day | worst $ | latency-stress net (n) | US-fee net |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

**Decision:** NOT RUN: TRAIN shortlisted no cell

Readings per PLAN §4. One bet per market per cell: the first buyable print inside the entry window whose model edge (model probability of that side minus the price paid, print + 0.01, minus the taker fee per share) exceeds the margin; $20 tickets held to settlement; 'net' = profit per $1 staked after fees; CI by cluster bootstrap (bets settled by one price draw resample together); 'latency stress' = the same signal executed at lab 4's rule (first buyable print for the side >= 10 s later, + 0.01); 'US-fee net' = re-costed at Polymarket US's 0.0695. Nothing here is a live trade.
