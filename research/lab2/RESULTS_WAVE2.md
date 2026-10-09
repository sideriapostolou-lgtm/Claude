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
| Y2 curve-phase organic share | TRAIN | REFUSED | needs 17 more curve hours of 2026-09-30 (24 h lookback) |
| Y1 creator reputation | held | — | review finding Y1-1 (same-bar stops) not yet applied |
| Y5 time-of-day, Z5 fee-tier optimizer | held | — | pinned M1 as host (M1 killed); re-spec needed |
| O1 operator-backed graduates (post-hoc lead; PREREG discloses) | VAL | **FAIL_VAL** | TRAIN: all 6 configs beat same-age random entries by +13..+33 pp (CIs well above 0) but sit at -3.0%..+0.4% absolute; VAL candidate t60|tight -2.2% [-6.2, +1.4], +19.8 pp vs random. Operator coins do not bleed; they do not pay either |
| K1 the Desk (Claude panel: scout / skeptic / risk memos on Haiku -> Sonnet decider; solo Sonnet; solo Haiku; one as-of brief per alive coin at g+30 min; decisions cached and budgeted; PREREG k1-v1) | DEBUG | **PENDING: needs `ANTHROPIC_API_KEY`** | Debug third (counts only): 450 coins, 137 alive at the decision time, 3 configs x 137 decisions with the fake desk, every buy became exactly one trade (deliberation <-> backtest agreement). Fake decisions are kept apart from the exam cache. TRAIN runs the moment the key is in the cloud environment: budget $40, then VAL $15, then one TEST look $15 |
| S1 insider supply spent, D1 capitulation dips | waiting | — | need B1 wallet trades (P4b fetch running) |
| q1-q12 idea-mill queue | parked | — | designers cut off by the agent weekly limit; resume after 2026-10-13 |

## Reading

Nothing passed. The one robust relative finding: OPERATOR-class graduates (>= 500 SOL non-agent buying from <= 30 buyers in the first 120 s) lose far less than every other class at 30-115 min (break-even vs -20%); that is a candidate universe filter for any future entry idea, not an edge. On this window the market drifts about -20% per trade for an outside buyer at seconds of
latency; the per-minute-bar ideas did not find a pocket that beats that plus 1.4-5.1% costs. The open leads
are wallet-level (S1, D1), the operator-class observation above, and the idea-mill queue.
