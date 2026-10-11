# D1 debug (census TRAIN third, counts only)

- Coins created over 0.52 days; usable 450; universe {'instant': 277, 'eligible': 133, 'g1_completed': 19, 'no_creation_data': 21}
- Real-bar E1 events: 1953 on 64 coins; first-event age quartiles (min) [10.2, 10.6, 10.9]
- Per day: {'eligible_coins': 255.6, 'e1_events': 3753.4, 'coins_with_e1': 123.0, 'coins_cap_feasible_ub_strict': 119.2, 'coins_cap_feasible_ub_loose': 121.1}
- CAP-feasible upper bound (bars): strict 62 coins, loose 63 coins
- Real B1 coins in this split: 0

## Pipeline on SYNTHETIC B1 (mechanics only)

| run | trades | coins | placebo | tags | horizon exits | wall s |
|---|---:|---:|---:|---|---:|---:|
| V1 | 25 | 25 | 431 | {'CAP': 25} | 0 | 4.98 |
| V2 | 26 | 26 | 449 | {'CAP': 26} | 0 | 3.53 |
| V3 | 25 | 25 | 431 | {'CAP': 25} | 0 | 6.89 |
| CAP@15 | 25 | 25 | 431 | {'CAP': 25} | 0 | 3.41 |
| CAP@30 | 25 | 25 | 431 | {'CAP': 25} | 0 | 3.24 |
| CAP@60 | 25 | 25 | 431 | {'CAP': 25} | 0 | 3.59 |
| CAP_LOOSE@15 | 26 | 26 | 449 | {'CAP': 26} | 0 | 3.22 |
| CAP_LOOSE@30 | 26 | 26 | 449 | {'CAP': 26} | 0 | 3.31 |
| CAP_LOOSE@60 | 26 | 26 | 449 | {'CAP': 26} | 0 | 3.29 |
| DIST@15 | 12 | 12 | 177 | {'DIST': 12} | 0 | 5.59 |
| DIST@30 | 12 | 12 | 177 | {'DIST': 12} | 0 | 4.18 |
| DIST@60 | 12 | 12 | 177 | {'DIST': 12} | 0 | 4.42 |
| MIXED@15 | 62 | 62 | 1011 | {'MIXED': 62} | 0 | 2.13 |
| MIXED@30 | 62 | 62 | 1011 | {'MIXED': 62} | 0 | 2.05 |
| MIXED@60 | 62 | 62 | 1011 | {'MIXED': 62} | 0 | 2.46 |
| ALL@15 | 64 | 64 | 1054 | {'MIXED': 60, 'CAP': 2, 'DIST': 2} | 0 | 2.29 |
| ALL@30 | 64 | 64 | 1054 | {'MIXED': 60, 'CAP': 2, 'DIST': 2} | 0 | 2.28 |
| ALL@60 | 64 | 64 | 1054 | {'MIXED': 60, 'CAP': 2, 'DIST': 2} | 0 | 2.33 |
