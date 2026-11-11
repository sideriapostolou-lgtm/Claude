# X5 debug

- **Split:** `final_train`; usable coins: 450; span: 0.52 days.
- **Written:** 2026-10-09 04:25:18 UTC; runtime 6.6 s; PREREG sha256 `8b8bce32d761`; trials in the ledger: 2575.
- **Overall X5 status:** PENDING (no official TRAIN run).

**Debug run on the census TRAIN third: mechanics and counts only. Returns, alive rates, signal values and every outcome statistic are hidden; no parameter was chosen here.**

## Regime coverage (counts)

- Grid ['2026-10-06 19:15:00', '2026-10-08 18:30:00'] (190 points of 15 min). GR pool: tradeable graduates created before 2026-10-08 08:06:47. AV/SV pool: 450 usable coins of ['final_train'] created in ['2026-10-07 19:37:30', '2026-10-08 08:06:47'].
- Records: {'GR': 1498, 'AV': 20003, 'SV': 450}; known grid points: {'GR': 148, 'AV': 7, 'SV': 18}; first known point: {'GR': '2026-10-06 19:15:00', 'AV': '2026-10-08 06:45:00', 'SV': '2026-10-08 04:15:00'}.
- Share of the split's coins with a known regime at g + 60 min (current point and its 24-h baseline): {'GR': 0.949, 'AV': 0.0, 'SV': 0.0}.
- SLACK check (PREREG 2.3), graduation delays: {'exact': 450, 'over_6h': 2, 'over_1h': 20, 'unscanned_creation': 0}.

## Model check (stop rule, PREREG 7)

- Coins alive at their R0 decision: 94 (need ≥ 200 observations with a known state per signal).
- GR: 88 observations; **HIDDEN (debug split: no outcome statistics)**.
- AV: 0 observations; **HIDDEN (debug split: no outcome statistics)**.
- SV: 0 observations; **HIDDEN (debug split: no outcome statistics)**.
- Decision: **HIDDEN**; signals in the grid: ['GR', 'AV', 'SV'].

## Hosts (ungated)

- R0: 94 trades from 94 coins; by tag {'R0': 94}; per day 180.65664205000445.

## Gated configs

| config | gated trades | coins | host states ON/OFF/UNKNOWN | known share | ON blocks | placebo trades | signals/day | gate == host ∩ ON |
|---|---:|---:|---|---:|---:|---:|---:|---|
| R0|GR|q0.5 | 43 | 43 | 43/45/6 | 0.936 | 2 | 860 | 82.6 | True |
| R0|GR|q0.8 | 12 | 12 | 12/76/6 | 0.936 | 2 | 240 | 23.1 | True |
| R0|AV|q0.5 | 0 | 0 | 0/0/94 | 0.0 | 0 | 0 | 0.0 | True |
| R0|AV|q0.8 | 0 | 0 | 0/0/94 | 0.0 | 0 | 0 | 0.0 | True |
| R0|SV|q0.5 | 0 | 0 | 0/0/94 | 0.0 | 0 | 0 | 0.0 | True |
| R0|SV|q0.8 | 0 | 0 | 0/0/94 | 0.0 | 0 | 0 | 0.0 | True |

## Decision

- **DEBUG**.
- mechanics and counts only; returns hidden
