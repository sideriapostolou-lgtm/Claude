# X4 debug

- **Split:** `final_train`; usable coins: 450; span: 0.52 days.
- **Written:** 2026-10-09 03:02:19 UTC; runtime 112.3 s; PREREG sha256 `bd6798dcc334`; trials in the ledger: 2575.
- **Overall X4 status:** PENDING (no official TRAIN run).

**Debug run on the census TRAIN third: mechanics and counts only. Returns, labels and fill prices are hidden and no parameter was chosen here.**

## Separation gate (PREREG 9)

- AT_FLOOR observations: 3955 from 258 coins; with no signal: 3955 (need ≥ 30 signal observations from ≥ 15 coins).
- Decision: **HIDDEN (debug split: no outcome statistics)**.

| signal | obs | coins |
|---|---:|---:|
| BREADTH | 0 | 0 |
| FLOW | 0 | 0 |
| BOTH | 0 | 0 |

## Event counts and structure (no returns)

- Coins 450 (strata {'instant': 277, 'slow': 173}); decision minutes at ages 30-150: 54014.
- Coins AT_FLOOR at age 30 / 60 / 90 / 120 / 150 min: {'30': 64, '60': 218, '90': 241, '120': 254, '150': 120}.
- fm at AT_FLOOR decision minutes: {'p10': 1.0274577958722528, 'p25': 1.0310889245319739, 'p50': 1.0418651970531185, 'p75': 1.0954680826922285, 'p90': 1.17897965899944}.
- Min fm per coin over ages 30-150 min: {'p5': 1.026738715097993, 'p10': 1.0294265532386349, 'p25': 1.0368268239217933, 'p50': 1.1376473761881851, 'p75': 1.6402155938459002}; coins whose min fm ≤ 1.25: 265.
- Virtual reserve v (SOL) at age 60 min (mechanics check): {'p1': 17.482968912232252, 'p10': 17.582843826336575, 'p50': 17.584504706854585, 'p90': 17.58450577115155, 'p99': 17.584617044531925}.

| condition | coins | coin-minutes |
|---|---:|---:|
| dead_before | 262 | 28297 |
| cheap_now | 327 | 36770 |
| at_floor | 262 | 28293 |
| dispersed_at_floor | 1 | 19 |
| bm12_at_floor | 0 | 0 |
| ni1_at_floor | 2 | 5 |
| BREADTH | 0 | 0 |
| FLOW | 0 | 0 |
| BOTH | 0 | 0 |

## Configs

| config | trades | coins | strata | entry age (min) | decision fm | placebo trades | controls | horizon exits | entries/day |
|---|---:|---:|---|---|---|---:|---|---:|---:|
| BREADTH|TP2X | 0 | 0 | {} | {'30-60': 0, '60-90': 0, '90-120': 0, '120-151': 0} | None | 0 | {} | 0 | 0.0 |
| BREADTH|RUN | 0 | 0 | {} | {'30-60': 0, '60-90': 0, '90-120': 0, '120-151': 0} | None | 0 | {} | 0 | 0.0 |
| FLOW|TP2X | 0 | 0 | {} | {'30-60': 0, '60-90': 0, '90-120': 0, '120-151': 0} | None | 0 | {} | 0 | 0.0 |
| FLOW|RUN | 0 | 0 | {} | {'30-60': 0, '60-90': 0, '90-120': 0, '120-151': 0} | None | 0 | {} | 0 | 0.0 |
| BOTH|TP2X | 0 | 0 | {} | {'30-60': 0, '60-90': 0, '90-120': 0, '120-151': 0} | None | 0 | {} | 0 | 0.0 |
| BOTH|RUN | 0 | 0 | {} | {'30-60': 0, '60-90': 0, '90-120': 0, '120-151': 0} | None | 0 | {} | 0 | 0.0 |

## Decision

- **DEBUG**.
- mechanics and counts only; returns hidden
