# Y1 debug

- **Split:** `final_train`; usable coins: 450; span: 0.52 days.
- **History** (outcome records): splits ['final_train']; 450 coins, 429 records from 417 creators; structural pool 708 graduates; first history graduation 2026-10-07 19:37:30 UTC.
- **Written:** 2026-10-09 02:44:31 UTC; runtime 4.3 s; PREREG sha256 `a147fa7935b4`; trials in the ledger: 2575.
- **Overall Y1 status:** PENDING (no official TRAIN run).

**Debug run on the census TRAIN third: mechanics and counts only. Returns are hidden and no parameter was chosen here.**

## Event counts (no returns)

- Status at the first post-BOOST decision: {'new': 417, 'unknown': 21, 'eligible': 7, 'pending': 5}; shared keys by rule: {}.
- Coins eligible inside the entry window (repeat deployer, ≥ 1 resolved record): 12 (23.1 per day) from 11 creators; median eligible age 7.9 min; resolved records at eligibility: {'1': 11, '2': 1}.

## Persistence gate (stop rule, PREREG 8)

- Observations: 12 from 11 creators in 10 deployer clusters (need ≥ 60 and ≥ 20); warm-up observations: 12.
- Decision: **HIDDEN (debug split: no outcome statistics)**.

## Configs

| config | trades | coins | clusters | tags | placebo draws/signal | horizon exits | entries/day |
|---|---:|---:|---:|---|---:|---:|---:|
| good|th0|T30 | 3 | 3 | 3 | {'good': 3} | 2.0 | 0 | 5.8 |
| good|th0|T60 | 3 | 3 | 3 | {'good': 3} | 2.0 | 0 | 5.8 |
| good|th0.1|T30 | 1 | 1 | 1 | {'good': 1} | 1.0 | 0 | 1.9 |
| good|th0.1|T60 | 1 | 1 | 1 | {'good': 1} | 1.0 | 0 | 1.9 |
| host|T30 | 12 | 12 | 10 | {'bad': 9, 'good': 3} | 3.2 | 0 | 23.1 |
| host|T60 | 12 | 12 | 10 | {'bad': 9, 'good': 3} | 3.2 | 0 | 23.1 |

## Bad-record veto (PREREG 6)

- host|T30: host trades 12, flagged 9, unflagged 3.
- host|T60: host trades 12, flagged 9, unflagged 3.

## Decision

- **DEBUG**.
- mechanics only; returns hidden
