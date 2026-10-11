# Z4 debug

- **Split:** `final_train`; usable coins: 450; span: 0.52 days.
- **History:** outcome records from splits ['final_train'] (450 records of 450 usable coins); structural pool 708 graduates (585 with a creator and a theme token, 753 distinct tokens); first structural graduation 2026-10-07 19:37:30 UTC.
- **Written:** 2026-10-09 03:23:40 UTC; runtime 5.4 s; PREREG sha256 `16d14b16f51c`; trials in the ledger: 2575.
- **Overall Z4 status:** PENDING (no official TRAIN run).

**Debug run on the census TRAIN third: mechanics and counts only. Returns, exit reasons, record values and placebo outcomes are hidden, and no parameter was chosen here.**

## Event counts at the decision (first grid time ≥ g + 30 min; no returns)

- Coins: 450; alive at the decision: 137.

| N | status (all coins) | coins with ≥ 1 member | HOST entries (eligible, alive) | per day | MOM θ=0.25 | MOM θ=1 | crowded (k ≥ 3) | exact clone | instant | warm-up | keys |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 3h | {'solo': 287, 'eligible': 118, 'unknown': 32, 'pending': 13} | 131 | 41 | 78.8 | 2 | 1 | 7 | 30 | 33 | 7 | 32 |
| 12h | {'solo': 228, 'eligible': 178, 'unknown': 32, 'pending': 12} | 190 | 55 | 105.7 | 4 | 0 | 23 | 42 | 42 | 54 | 39 |

- Top primary keys of HOST entries, N = 3h: {'oil': 4, 'fund': 3, 'gta': 2, 'nvidia': 2, 'digital': 2, 'apple': 2, 'craft': 1, 'muse': 1, 'human': 1, 'cat': 1, 'fish': 1, 'nyt': 1}.
- Top primary keys of HOST entries, N = 12h: {'oil': 4, 'cat': 3, 'nvidia': 3, 'fund': 3, 'apple': 3, 'evernorthxrp': 2, 'gta': 2, 'tank': 2, 'states': 2, 'american': 2, 'craft': 1, 'muse': 1}.

## Configs

| config | trades | coins | keys | tags | exact clone | instant | placebo draws/signal | horizon exits | entries/day |
|---|---:|---:|---:|---|---:|---:|---:|---:|---:|
| mom|N3h|th0.25 | 2 | 2 | 2 | {'hot|few': 2} | 2 | 2 | 19.0 | 0 | 3.8 |
| mom|N3h|th1 | 1 | 1 | 1 | {'hot|few': 1} | 1 | 1 | 18.0 | 0 | 1.9 |
| mom|N12h|th0.25 | 4 | 4 | 4 | {'hot|few': 3, 'hot|crowd': 1} | 4 | 3 | 20.0 | 0 | 7.7 |
| mom|N12h|th1 | 0 | 0 | 0 | {} | 0 | 0 | n/a | 0 | 0.0 |
| host|N3h | 41 | 41 | 32 | {'cold|few': 32, 'cold|crowd': 7, 'hot|few': 2} | 30 | 33 | 17.4 | 0 | 78.8 |
| host|N12h | 55 | 55 | 39 | {'cold|few': 29, 'cold|crowd': 22, 'hot|few': 3, 'hot|crowd': 1} | 42 | 42 | 19.2 | 0 | 105.7 |

## Exhaustion veto (the inverse, PREREG 6)

- host|N3h: host trades 41, flagged (hot) 2, unflagged 39.
- host|N12h: host trades 55, flagged (hot) 4, unflagged 51.

## Decision

- **DEBUG**.
- mechanics and counts only; returns hidden
