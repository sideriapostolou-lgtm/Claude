# Y1 debug

- **Split:** `final_train`; usable coins: 450; span: 0.52 days.
- **History** (outcome records): splits ['final_train']; 450 coins, 429 records from 417 creators; structural pool 708 graduates; first history graduation 2026-10-07 19:37:30 UTC.
- **Written:** 2026-10-09 04:11:39 UTC; runtime 6.3 s; PREREG sha256 `15301aa0ed49`; trials in the ledger: 2575.
- **Overall Y1 status:** PENDING (no official TRAIN run).

**Debug run on the census TRAIN third: mechanics and counts only. Returns are hidden and no parameter was chosen here.**

## Event counts (no returns)

- Status at the first post-BOOST decision: {'new': 417, 'unknown': 21, 'eligible': 7, 'pending': 5}; shared keys by rule: {}.
- Coins eligible inside the entry window (repeat deployer, ≥ 1 resolved record): 12 (23.1 per day) from 11 creators; median eligible age 7.9 min; resolved records at eligibility: {'1': 11, '2': 1}.

## Persistence gate (stop rule, PREREG 8)

- Observations: 12 from 11 creators in 10 deployer clusters (need ≥ 60 and ≥ 20); warm-up observations: 12.
- Decision: **HIDDEN (debug split: no outcome statistics)**.

## Configs

| config | trades | coins | clusters | placebo draws/signal | horizon exits | entries/day |
|---|---:|---:|---:|---:|---:|---:|
| good|th0|T30 | hidden | hidden | hidden | hidden | hidden | hidden |
| good|th0|T60 | hidden | hidden | hidden | hidden | hidden | hidden |
| good|th0.1|T30 | hidden | hidden | hidden | hidden | hidden | hidden |
| good|th0.1|T60 | hidden | hidden | hidden | hidden | hidden | hidden |
| host|T30 | 12 | 12 | 10 | 3.2 | 0 | 23.1 |
| host|T60 | 12 | 12 | 10 | 3.2 | 0 | 23.1 |

GOOD-config counts, trade tags and veto flags are hidden on the debug split: each is the sign of an earlier coin's record (review Y1-3).

## Bad-record veto (PREREG 6)

- host|T30: host trades 12; flags hidden on the debug split.
- host|T60: host trades 12; flags hidden on the debug split.

## Decision

- **DEBUG**.
- mechanics only; returns hidden
