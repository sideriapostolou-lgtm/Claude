# G1 val (val)

Run 2026-10-09 05:17:44 UTC, 18.0 s. PREREG sha256 `08d68682eb90`. Trials in the ledger: 2631.

## Counts

- Usable coins: 1278 over 1.50 days of creation.
- Classes at g + 140 s: {'ORGANIC': 612, 'FACTORY': 442, 'OPERATOR': 97, 'UNRESOLVED': 85, 'COMPLETED': 42}.
- Flagged at g + 140 s: {'G-time': 838, 'G-chain': 581, 'G-chain+': 593}. SERIAL: 17. Airdrop dump by the window end: 434.
- Host trades: {'dip': 62, 'R0': 314} (per day dip 41.3, R0 209.3; per 100 coins dip 4.9, R0 24.6).
- Host trades by class: {'dip': {'ORGANIC': 46, 'FACTORY': 8, 'UNRESOLVED': 4, 'COMPLETED': 4}, 'R0': {'ORGANIC': 131, 'OPERATOR': 79, 'FACTORY': 44, 'UNRESOLVED': 43, 'COMPLETED': 17}}.
- Registry: {'coins': 3086, 'creators': 2418, 'wallets': 5537, 'warm_share_at_g140': 1.0}.

## Hosts (ungated)

| Host | n | coins | mean | 95% CI | placebo diff | costs x1.5 | alt fill |
|---|---:|---:|---:|---|---:|---:|---:|
| dip | 62 | 62 | -22.6% | [-29.5, -15.3] | -0.6% | -24.0% | -27.6% |
| R0 | 314 | 314 | -18.6% | [-29.8, -1.2] | n/a | -19.7% | -18.4% |

## How much each class loses (host trades classified at their decision time)

| Host | Class | n | mean | 95% CI | P&L $ |
|---|---|---:|---:|---|---:|
| dip | FACTORY | 8 | -23.6% | [-59.2, +10.9] | -38 |
| dip | COMPLETED | 4 | -1.3% | [-27.0, +24.5] | -1 |
| dip | UNRESOLVED | 4 | -29.2% | [-34.9, -23.4] | -23 |
| dip | ORGANIC | 46 | -23.7% | [-30.4, -16.9] | -218 |
| dip | flag:SERIAL | 1 | -23.2% | n/a | -5 |
| dip | flag:INSTANT | 24 | -31.4% | [-44.5, -18.6] | -151 |
| dip | flag:FAST120 | 31 | -27.5% | [-39.3, -15.6] | -171 |
| R0 | OPERATOR | 79 | +23.3% | [-10.1, +84.7] | +369 |
| R0 | FACTORY | 44 | -48.4% | [-66.7, -28.3] | -426 |
| R0 | COMPLETED | 17 | -20.0% | [-41.6, +3.9] | -68 |
| R0 | UNRESOLVED | 43 | -28.6% | [-39.6, -16.6] | -246 |
| R0 | ORGANIC | 131 | -30.3% | [-38.4, -21.0] | -795 |
| R0 | flag:SERIAL | 6 | -26.1% | [-45.4, -7.2] | -31 |
| R0 | flag:INSTANT | 148 | -10.4% | [-32.1, +23.0] | -308 |
| R0 | flag:FAST120 | 166 | -13.4% | [-32.8, +17.3] | -445 |

## Gate variants

| Variant | flagged coins (dead set) | precision dead60 | missed winners | R0 flagged - unflagged [95% CI] | R0 kept mean | dip flagged - unflagged |
|---|---:|---:|---:|---|---:|---:|
| G-time | 838 | 78.2% | 12.4% | +11.0% [-11.0, +43.8] | -24.4% | -9.8% (n 31/31) |
| G-chain+ | 496 | 84.9% | 16.5% | +24.2% [+0.2, +61.5] | -29.7% | +7.5% (n 13/49) |
- G-chain+ vs G-time on R0's kept trades: -5.3% [-9.5, -1.5].

## Decision

```
{
 "verdict": "KILL",
 "ship": null,
 "chain_variant": "G-chain+",
 "criteria": {
  "c1_precision": {
   "value": 0.8487903225806451,
   "n_flagged": 496,
   "need": ">= 0.9 with >= 200",
   "pass": false
  },
  "c2_missed_winners": {
   "value": 0.16532258064516128,
   "need": "<= 0.05",
   "pass": false
  },
  "c3_chain_beats_time_R0": {
   "value": -0.05298114315178862,
   "ci95": [
    -0.09528645906793672,
    -0.0152911454332762
   ],
   "need": ">= 0.02, CI > 0",
   "pass": false
  }
 }
}
```
