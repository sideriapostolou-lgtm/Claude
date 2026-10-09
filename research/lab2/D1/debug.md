# D1 debug (census TRAIN third, counts only)

- Coins created over 0.52 days; usable 450; universe {'instant': 277, 'eligible': 133, 'g1_completed': 19, 'no_creation_data': 21}
- Real-bar E1 events: 1957 on 64 coins; first-event age quartiles (min) [10.2, 10.6, 10.9]
- Per day: {'eligible_coins': 255.6, 'e1_events': 3761.1, 'coins_with_e1': 123.0, 'coins_cap_feasible_ub_strict': 119.2, 'coins_cap_feasible_ub_loose': 121.1}
- CAP-feasible upper bound (bars): strict 62 coins, loose 63 coins
- Real B1 coins in this split: 0

## Pipeline on SYNTHETIC B1 (mechanics only)

| run | trades | coins | placebo | tags | exit reasons | wall s |
|---|---:|---:|---:|---|---|---:|
| V1 | 26 | 26 | 449 | {'CAP': 26} | {'stop': 25, 'take_profit': 1} | 5.27 |
| V2 | 27 | 27 | 483 | {'CAP': 27} | {'stop': 27} | 3.34 |
| V3 | 26 | 26 | 449 | {'CAP': 26} | {'trail': 23, 'signal:org_net5': 3} | 6.31 |
| CAP@15 | 26 | 26 | 449 | {'CAP': 26} | {'time': 26} | 3.71 |
| CAP@30 | 26 | 26 | 449 | {'CAP': 26} | {'time': 26} | 3.58 |
| CAP@60 | 26 | 26 | 449 | {'CAP': 26} | {'time': 26} | 3.67 |
| CAP_LOOSE@15 | 27 | 27 | 483 | {'CAP': 27} | {'time': 27} | 3.29 |
| CAP_LOOSE@30 | 27 | 27 | 483 | {'CAP': 27} | {'time': 27} | 3.49 |
| CAP_LOOSE@60 | 27 | 27 | 483 | {'CAP': 27} | {'time': 27} | 3.89 |
| DIST@15 | 12 | 12 | 174 | {'DIST': 12} | {'time': 12} | 5.7 |
| DIST@30 | 12 | 12 | 174 | {'DIST': 12} | {'time': 12} | 4.4 |
| DIST@60 | 12 | 12 | 174 | {'DIST': 12} | {'time': 12} | 4.5 |
| MIXED@15 | 63 | 63 | 1053 | {'MIXED': 63} | {'time': 63} | 2.5 |
| MIXED@30 | 63 | 63 | 1053 | {'MIXED': 63} | {'time': 63} | 2.44 |
| MIXED@60 | 63 | 63 | 1053 | {'MIXED': 63} | {'time': 63} | 2.51 |
| ALL@15 | 64 | 64 | 1060 | {'MIXED': 61, 'DIST': 2, 'CAP': 1} | {'time': 64} | 2.33 |
| ALL@30 | 64 | 64 | 1060 | {'MIXED': 61, 'DIST': 2, 'CAP': 1} | {'time': 64} | 2.52 |
| ALL@60 | 64 | 64 | 1060 | {'MIXED': 61, 'DIST': 2, 'CAP': 1} | {'time': 64} | 2.48 |
