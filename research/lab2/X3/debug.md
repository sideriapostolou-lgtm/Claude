# X3 debug

- **Split:** `final_train`; usable coins: 450; span: 0.52 days.
- **Written:** 2026-10-09 03:06:33 UTC; runtime 6.5 s; PREREG sha256 `6210e5a6a39b`; trials in the ledger: 2575.
- **Overall X3 status:** PENDING (no official TRAIN run).

**Debug run on the census TRAIN third: mechanics and counts only. Returns, exit reasons and gate labels are hidden, and no parameter was chosen here.**

## Reversion gate (PREREG 8)

- Deep `now` events (m = 2): 1 from 1 coins (with matched draws: 1, mean draws per event 16.0); need ≥ 50 and ≥ 30 coins; by depth bucket {'d1470': 1}.
- Diagnostics: deep `confirm` events 1, shallow (100-1,470 SOL) events 16.
- Decision: **HIDDEN (debug split: no outcome statistics)**; passing horizons: [10, 30].

## Event counts (features only, no returns)

- Classes at g + 60 min: {'FACTORY': 183, 'OTHER': 233, 'OPERATOR': 34}.
- OTHER coins ever deep (≥ 1,470 SOL) in g + 60 → 145 min: 13 (and alive: 13); deep coin-decisions: 451; climax bars seen at deep decisions: 1; coins with a deep climax: {'now': 1, 'confirm': 1}.

| gate events | n | coins | by bucket | mcap SOL p10/p50/p90 | rt % p10/p50/p90 | tp % p10/p50/p90 | climax drop % p10/p50/p90 | age min p10/p50/p90 |
|---|---:|---:|---|---|---|---|---|---|
| deep | 1 | 1 | {'d1470': 1} | 1844/1844/1844 | 3.29/3.29/3.29 | 11.7/11.7/11.7 | 19.5/19.5/19.5 | 100/100/100 |
| deep_confirm | 1 | 1 | {'d1470': 1} | 1856/1856/1856 | 3.29/3.29/3.29 | 11.0/11.0/11.0 | 19.5/19.5/19.5 | 101/101/101 |
| shallow | 16 | 15 | {'shallow': 16} | 146/250/934 | 3.47/3.81/3.97 | 8.7/14.4/23.2 | 15.1/23.1/33.0 | 68/102/125 |

## Configs

| config | trades | coins | depth buckets | mean rt | mean tp | placebo trades (matched / any depth) | horizon exits | entries/day |
|---|---:|---:|---|---:|---:|---|---:|---:|
| m2|now|h10 | 1 | 1 | {'d1470': 1} | 3.29% | 11.7% | 16 / 20 | 0 | 1.9 |
| m2|now|h30 | 1 | 1 | {'d1470': 1} | 3.29% | 11.7% | 16 / 20 | 0 | 1.9 |
| m2|confirm|h10 | 1 | 1 | {'d1470': 1} | 3.29% | 11.0% | 17 / 20 | 0 | 1.9 |
| m2|confirm|h30 | 1 | 1 | {'d1470': 1} | 3.29% | 11.0% | 17 / 20 | 0 | 1.9 |
| m4|now|h10 | 0 | 0 | {} | n/a | n/a | 0 / 0 | 0 | 0.0 |
| m4|now|h30 | 0 | 0 | {} | n/a | n/a | 0 / 0 | 0 | 0.0 |
| m4|confirm|h10 | 0 | 0 | {} | n/a | n/a | 0 / 0 | 0 | 0.0 |
| m4|confirm|h30 | 0 | 0 | {} | n/a | n/a | 0 / 0 | 0 | 0.0 |

## Decision

- **DEBUG**.
- mechanics only; returns hidden
