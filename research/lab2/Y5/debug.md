# Y5 debug

- **Split:** `final_train`; usable coins: 450; span: 0.52 days.
- **Written:** 2026-10-09 03:29:09 UTC; runtime 96.6 s; PREREG sha256 `5d36ec39af26`; trials in the ledger: 2575; M1 host m1-v1 `9c0a14afb895`.
- **Overall Y5 status:** PENDING (no official TRAIN run).

**Debug run on the census TRAIN third: mechanics and counts only. Returns are hidden and no parameter was chosen here.**

## Event counts (no outcomes)

- Coins 450; creation window shifted to g + 30 min: ['2026-10-07 20:07:30', '2026-10-08 08:36:46']; session exposure hours {'ASIA': 8.0, 'EU': 0.6127777777777778, 'US': 3.875}.
- R30 decisions (g + 30 min) by session {'ASIA': 265, 'EU': 18, 'US': 167}; alive (= R30 entries) {'ASIA': 92, 'EU': 6, 'US': 39}; by day type {'WEEKDAY': 450, 'WEEKEND': 0}.
- R30 decisions by UTC hour: {'0': 48, '1': 40, '2': 36, '3': 36, '4': 33, '5': 21, '6': 28, '7': 23, '8': 16, '9': 1, '12': 1, '16': 1, '20': 42, '21': 41, '22': 35, '23': 48}.

## Configs

| config | trades | coins | by session | by day type | placebo | controls | horizon exits | entries/day | entries per session-day |
|---|---:|---:|---|---|---:|---|---:|---:|---|
| R30|ASIA | 92 | 92 | {'ASIA': 92, 'EU': 0, 'US': 0} | {'WEEKDAY': 92, 'WEEKEND': 0} | 1840 | {} | 0 | 176.8 | {'ASIA': 92.0, 'EU': None, 'US': 0.0} |
| R30|EU | 6 | 6 | {'ASIA': 0, 'EU': 6, 'US': 0} | {'WEEKDAY': 6, 'WEEKEND': 0} | 120 | {} | 0 | 11.5 | {'ASIA': 0.0, 'EU': None, 'US': 0.0} |
| R30|US | 39 | 39 | {'ASIA': 0, 'EU': 0, 'US': 39} | {'WEEKDAY': 39, 'WEEKEND': 0} | 780 | {} | 0 | 75.0 | {'ASIA': 0.0, 'EU': None, 'US': 80.5} |
| R30|ASIA+EU | 98 | 98 | {'ASIA': 92, 'EU': 6, 'US': 0} | {'WEEKDAY': 98, 'WEEKEND': 0} | 1960 | {} | 0 | 188.3 | {'ASIA': 92.0, 'EU': None, 'US': 0.0} |
| R30|ASIA+US | 131 | 131 | {'ASIA': 92, 'EU': 0, 'US': 39} | {'WEEKDAY': 131, 'WEEKEND': 0} | 2620 | {} | 0 | 251.8 | {'ASIA': 92.0, 'EU': None, 'US': 80.5} |
| R30|EU+US | 45 | 45 | {'ASIA': 0, 'EU': 6, 'US': 39} | {'WEEKDAY': 45, 'WEEKEND': 0} | 900 | {} | 0 | 86.5 | {'ASIA': 0.0, 'EU': None, 'US': 80.5} |
| R30|ALL | 137 | 137 | {'ASIA': 92, 'EU': 6, 'US': 39} | {'WEEKDAY': 137, 'WEEKEND': 0} | 2740 | {} | 0 | 263.3 | {'ASIA': 92.0, 'EU': None, 'US': 80.5} |
| M1|ASIA | 18 | 18 | {'ASIA': 18, 'EU': 0, 'US': 0} | {'WEEKDAY': 18, 'WEEKEND': 0} | 217 | {'unmatched': 360} | 0 | 34.6 | {'ASIA': 18.0, 'EU': None, 'US': 0.0} |
| M1|EU | 2 | 2 | {'ASIA': 0, 'EU': 2, 'US': 0} | {'WEEKDAY': 2, 'WEEKEND': 0} | 26 | {'unmatched': 40} | 0 | 3.8 | {'ASIA': 0.0, 'EU': None, 'US': 0.0} |
| M1|US | 4 | 4 | {'ASIA': 0, 'EU': 0, 'US': 4} | {'WEEKDAY': 4, 'WEEKEND': 0} | 52 | {'unmatched': 80} | 0 | 7.7 | {'ASIA': 0.0, 'EU': None, 'US': 8.3} |
| M1|ALL | 24 | 24 | {'ASIA': 18, 'EU': 2, 'US': 4} | {'WEEKDAY': 24, 'WEEKEND': 0} | 300 | {'unmatched': 480} | 0 | 46.1 | {'ASIA': 18.0, 'EU': None, 'US': 8.3} |

## Decision

- **DEBUG**.
- mechanics and counts only; returns hidden
