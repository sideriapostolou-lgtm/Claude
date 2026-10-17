# S1 debug run on the census TRAIN third (counts only; returns hidden)

- B1 source: **SYNTHETIC (made-up wallets; flow-condition counts are meaningless)**.
- 450 usable coins; S1-universe 152; 0.52 days; 226105 B1 rows.
- Timing (s): {'synth_or_load': 7.3, 'gate': 1.2, 'grid_plus_control': 14.6}.

## Gate populations

- g + 10 min: 85 coins, quintile sizes [17, 17, 17, 17, 17].
- g + 30 min: 47 coins, quintile sizes [10, 9, 10, 9, 9].

## Grid signal counts (synthetic flows if so marked: meaningless for S1's rate)

| Config | n | Coins | By checkpoint |
|---|---:|---:|---|
| rem0.10_buy10_absY | 0 | 0 | {} |
| rem0.10_buy10_absN | 0 | 0 | {} |
| rem0.10_buy20_absY | 0 | 0 | {} |
| rem0.10_buy20_absN | 0 | 0 | {} |
| rem0.25_buy10_absY | 18 | 18 | {'cp10': 2, 'cp15': 8, 'cp20': 1, 'cp30': 1, 'cp6': 4, 'cp8': 2} |
| rem0.25_buy10_absN | 18 | 18 | {'cp10': 2, 'cp15': 8, 'cp20': 1, 'cp30': 1, 'cp6': 5, 'cp8': 1} |
| rem0.25_buy20_absY | 18 | 18 | {'cp10': 2, 'cp15': 8, 'cp20': 1, 'cp30': 1, 'cp6': 4, 'cp8': 2} |
| rem0.25_buy20_absN | 18 | 18 | {'cp10': 2, 'cp15': 8, 'cp20': 1, 'cp30': 1, 'cp6': 5, 'cp8': 1} |

Control 1: {'n': 628, 'checkpoints': {'cp10': 85, 'cp120': 25, 'cp15': 66, 'cp20': 59, 'cp30': 47, 'cp45': 40, 'cp6': 142, 'cp60': 32, 'cp8': 103, 'cp90': 29}}.

## Real non-flow counts (bars + graduation columns)

- Alive at each checkpoint: {6: 142, 8: 103, 10: 85, 15: 66, 20: 59, 30: 47, 45: 40, 60: 32, 90: 29, 120: 25}.
- Per day: {6: 272.9, 8: 198.0, 10: 163.4, 15: 126.8, 20: 113.4, 30: 90.3, 45: 76.9, 60: 61.5, 90: 55.7, 120: 48.0}.
- Upper bound on entries (alive and ≥ θ_buy buyers in 10 min, first checkpoint): {10: 141, 20: 141} → per day {10: 271.0, 20: 271.0}.
- Feature availability at g + 10 min: {'why_at_g+10': {'ok': 152}, 'g1_class_at_g+10': {'ORGANIC': 144, 'COMPLETED': 8}}.
