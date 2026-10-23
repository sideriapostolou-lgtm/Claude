# Wave 2 results (as of 2026-10-09 05:20 UTC)

Data: CryptoHouse pump.fun graduates 2026-10-01 → 10-09 (curve + B2 minute bars, audited; bar-0 pricing
corrected 10-09). Splits by coin creation: TRAIN 10-01..10-05, VAL 10-05..10-06 12:00, TEST ..10-07 19:37 (one
look, not yet spent by anyone), CONFIRM 09-16..10-01 (not backfilled), FINAL census day. Every config is a
counted trial (ledger: 2,631 after G1 VAL). Fills: worst-side entries, next-bar stops, fee tiers by date.

## Baseline (G1 TRAIN, 3,863 usable coins over 4 days)

| Host | n | mean net per trade | 95% CI |
|---|---:|---:|---|
| Random alive entry at 30-115 min (R0) | 914 | -19.9% | [-23.9, -15.6] |
| The bot's dip-rebound rule | 155 | -25.1% | [-29.6, -20.6] |

By class at R0 (TRAIN): FACTORY -46.3%, COMPLETED -35.5%, ORGANIC -28.3%, OPERATOR -3.0% [-6.5, +0.4],
UNRESOLVED +3.9% [-11.0, +25.3]. On VAL (314 R0 trades) OPERATOR read +23.3% [-10.1, +84.7] (n 79): a
post-hoc observation, NOT a result; it would need its own pre-registered hypothesis.

## Verdicts

| Hypothesis | Stage | Verdict | Why |
|---|---|---|---|
| G1 insider-coin gate | VAL | **KILL** | precision 0.849 (< 0.90), missed winners 0.165 (> 0.05), chain gate below the time gate on R0 by -5.3% [-9.5, -1.5] |
| M1 mechanical-bid riding | TRAIN | **KILLED** | model check: slope -0.023 (need >= 0.5), R^2 0.01 |
| X1 smart-money follow | TRAIN | **KILLED** | wallet skill does not persist (persistence gate) |
| X2 cross-sectional breadth | TRAIN | **KILLED** | dose-response gate failed |
| X5 market regime gate | TRAIN | NO EDGE | nothing qualified |
| X6 post-BOOST organic takeover | TRAIN | **KILLED** | takeover does not separate from flow-dies |
| Y4 round-number levels | TRAIN | NO EDGE | nothing qualified |
| Z1 seller exhaustion | TRAIN | NO EDGE | nothing qualified |
| Z2 whale follow | TRAIN | NO EDGE | nothing qualified |
| Z4 narrative/theme momentum | TRAIN | NO EDGE | neither momentum nor exhaustion |
| X3 depth-aware mean reversion | TRAIN | UNDERPOWERED | too few deep-pool climaxes |
| X4 floor lottery | TRAIN | UNDERPOWERED | too few floor signals |
| Y3 volatility breakout | TRAIN | UNDERPOWERED | too few trades |
| Z3 rug bounce | TRAIN | UNDERPOWERED | too few trades |
| Y2 curve-phase organic share (rank vs a 24 h reference pool; selectors T3 / T5 / PE11) | TRAIN | **NO EDGE (NO_CONFIG)** | Ran 10:43 UTC after the 17 missing 2026-09-30 curve hours were fetched. 1,420 eligible (slow-curve) coins, 492 alive at g+30 min. Every selector loses 29-41 %: T3 -39.6 % / -41.0 %, T5 -41.4 % / -35.8 %, PE11 -29.0 % [CI low -38.6] / -38.0 %; placebo diffs -6.4..+4.1 pp; the mechanism check holds only for PE11, which still fails the mean bar |
| Y1 creator reputation (repeat deployers' past outcomes; next-bar exits per review Y1-1) | TRAIN | **NO EDGE (NO_CONFIG)** | 135 eligible coins from 108 creators (33.8/day). Persistence gate PASSED weakly (Spearman record->next 30 min 0.17, cluster CI [0.01, 0.29]) but no config qualifies: good-record creators -29.8% (T30) / -26.7% (T60), +5..+9 pp vs matched random with cluster CIs far below 0; bad-record veto FAILS (flagged -43..-50% vs unflagged -27..-30%, i.e. the record separates bad from worse, not winners from losers) |
| Y5 time-of-day, Z5 fee-tier optimizer | held | — | pinned M1 as host (M1 killed); re-spec needed |
| O1 operator-backed graduates (post-hoc lead; PREREG discloses) | VAL | **FAIL_VAL** | TRAIN: all 6 configs beat same-age random entries by +13..+33 pp (CIs well above 0) but sit at -3.0%..+0.4% absolute; VAL candidate t60|tight -2.2% [-6.2, +1.4], +19.8 pp vs random. Operator coins do not bleed; they do not pay either |
| K1 the Desk (Claude panel: scout / skeptic / risk memos on Haiku -> Sonnet decider; solo Sonnet; solo Haiku; one as-of brief per alive coin at g+30 min; decisions cached and budgeted; PREREG k1-v1, Amendments 1-2) | TRAIN | **UNDERPOWERED (TRAIN): the Desk never bought.** All three configs said `skip` on every one of the 1,408 TRAIN coins alive at g+30 min (4,224 decisions; mean confidence 0.12 panel, 0.17 solo-Sonnet, 0.14 solo-Haiku); 0 trades, nothing to score; shortlist empty, so no VAL / TEST | Cost $10.32 of the $25 credit (panel $6.99, solo-Sonnet $3.17, solo-Haiku $0.16). Reading: given a brief that shows a typical graduate at +30 min (down ~50 % from its high, net outflow, unresolved class, no name / curve fields in the TRAIN brief), the models decline to trade at all. This is consistent with the other wave-2 studies (no edge at g+30 min) and says nothing about whether a desk with a different brief or decision time would buy; that would be a new pre-registered study (K2), not a re-run. Decisions and memos are committed under K1/decisions/ for anyone to read |
| Q11 the value of speed (measurement: $20 at graduation + L s, held H s, real fee tiers + impact + tip; 1,420 TRAIN coins with per-trade tapes = slow graduations only, instant migrations excluded) | TRAIN | **NO EDGE AT ANY SPEED** | Every cell of the 10 latencies x 8 holds surface is <= 0 after costs: at 1 s latency -1.7 % (5 s hold) .. +0.3 % [-4.4, +5.3] (300 s hold), -28 % (900 s), -29 % (1800 s); at 60 s latency -3.5 % .. -33 %. Speed is worth something RELATIVE (1 s beats 60 s by +2 to +13 pp depending on the hold, CI > 0 for 5 s, 15 s, 300 s, 900 s holds) but it only shrinks the loss: the first minutes are flat (costs only) and the collapse comes at 5-15 minutes whoever you are. Edge frontier: none for any hold. Caveat: the coins snipers target hardest (instant / synthetic migrations, 2,208 of 3,863) have no per-trade tape here; their money is made on the bonding curve before graduation and in the migration block, a game of co-location and bundles |
| Q10 LP1 "be the house" (deposit $20 of liquidity in busy fresh PumpSwap pools: V15 >= M x x_real, mcap >= 420 SOL, |R15| <= 20 %; collect the 20 bps LP fee; G0 protocol gate passed from pump-public-docs) | TRAIN | **NO EDGE (NO_CONFIG, dead)** | 540-599 LP positions per config. Every config loses: M6|D0.7 -27.8 % [-30.2, -25.4], D0.5 -36.0 %, deadline-only -48.2 %; 5 of 6 WORSE_THAN_RANDOM vs matched LP deposits in any alive coin. Decomposition on the same entries: token mid return -36 % to -47 % (busy pools are post-spike dumps), 50/50 hold without fees -19 % to -25 %, estimated LP fee income only +0.8 % to +2.0 % of the ticket, LP minus 50/50 gap -9 to -24 pp (the +17.6 SOL migration boost levers the LP's downside; fees are 10x too small). The only mechanism in the pile that does not bet on direction is also dead on this market |
| S1 smart-wallet dose-response (B1 wallet trades, 1420/1420 coins covered) | TRAIN | **GATE_FAIL (dead, stop rule 3)** | 30-min holds by smart-wallet-flow quintile show no monotone ordering: g+10 min Q1 -56.0% ... Q5 -50.8% (2 inversions, Q1-Q5 -5.2 pp); g+30 min Q1 -31.2% ... Q5 -38.5% (2 inversions, +7.3 pp). The entry grid was never run |
| D1 capitulation-vs-distribution dips (B1 wallet trades) | VAL, judged | **FAIL (judge: no TEST look)** | TRAIN: every variant -30% to -50%, none beats matched random (V1 -29.9%, V2 -30.6%; shortlisted by D1's sign-less top-2 rule). VAL: its rule 'SELECTED' V1 at **-32.1% [-35.6, -28.4]**, -4.6 pp vs random (V2 -33.4%, -3.4 pp); CAP-vs-DIST contrast +17.1 pp [-4.6, +39.8] (capitulation dips lose less than distribution dips, but both lose 25-40%). Judge verdict under PLAN 3.5: a config with a negative mean and a CI entirely below zero earns no TEST look; the module's selection rule lacks the lab's +3 % bar and is noted as a defect. S1 and D1 are closed; the B1 wallet-trade data (train/val/test complete) stays for future hypotheses |
| S1 insider supply spent, D1 capitulation dips | waiting | — | need B1 wallet trades (P4b fetch running) |
| q1-q12 idea-mill queue | parked | — | designers cut off by the agent weekly limit; resume after 2026-10-13 |

## Reading

Nothing passed. The one robust relative finding: OPERATOR-class graduates (>= 500 SOL non-agent buying from <= 30 buyers in the first 120 s) lose far less than every other class at 30-115 min (break-even vs -20%); that is a candidate universe filter for any future entry idea, not an edge. On this window the market drifts about -20% per trade for an outside buyer at seconds of
latency; the per-minute-bar ideas did not find a pocket that beats that plus 1.4-5.1% costs. The open leads
are wallet-level (S1, D1), the operator-class observation above, and the idea-mill queue.
