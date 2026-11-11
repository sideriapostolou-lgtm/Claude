# D1 VAL (d1-v1)

**Status: SELECTED** (gate WEAK: CAP - DIST = +17.1%, 95% CI [-4.6, +39.8], n 75 / 42)

| run | trades | coins | mean | median | 90% CI | mean w/o top 2 | vs placebo |
|---|---:|---:|---:|---:|---|---:|---:|
| CAP@30 | 75 | 75 | -24.3% | -48.8% | [-37.8, -9.0] | -33.4% | +7.3% |
| DIST@30 | 42 | 42 | -41.4% | -53.6% | [-55.2, -26.4] | -49.4% | -7.4% |
| V1 | 75 | 75 | -32.1% | -30.7% | [-35.6, -28.4] | -33.5% | -4.6% |
| V2 | 83 | 83 | -33.4% | -34.1% | [-36.7, -30.0] | -34.7% | -3.4% |

Selection: {'status': 'SELECTED', 'selected': 'V1', 'params': {'version': 'd1-v1', 'study': 'strategy', 'variant': 'V1', 'entry_class': 'CAP', 'cap_def': 'strict', 'exit_set': 'bracket'}, 'why': 'higher VAL mean among shortlisted configs with >= 15 VAL trades', 'gate_status': 'WEAK'}
