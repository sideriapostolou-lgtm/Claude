# G1 train (train)

Run 2026-10-09 04:43:20 UTC, 46.7 s. PREREG sha256 `08d68682eb90`. Trials in the ledger: 2581.

## Counts

- Usable coins: 3863 over 4.00 days of creation.
- Classes at g + 140 s: {'ORGANIC': 1870, 'FACTORY': 1336, 'OPERATOR': 287, 'UNRESOLVED': 235, 'COMPLETED': 135}.
- Flagged at g + 140 s: {'G-time': 2568, 'G-chain': 1758, 'G-chain+': 1794}. SERIAL: 43. Airdrop dump by the window end: 1290.
- Host trades: {'dip': 155, 'R0': 914} (per day dip 38.8, R0 228.5; per 100 coins dip 4.0, R0 23.7).
- Host trades by class: {'dip': {'ORGANIC': 115, 'UNRESOLVED': 23, 'FACTORY': 11, 'COMPLETED': 6}, 'R0': {'ORGANIC': 382, 'OPERATOR': 233, 'FACTORY': 137, 'UNRESOLVED': 136, 'COMPLETED': 26}}.
- Registry: {'coins': 5891, 'creators': 4266, 'wallets': 8672, 'warm_share_at_g140': 0.8389852446285271}.

## Hosts (ungated)

| Host | n | coins | mean | 95% CI | placebo diff | costs x1.5 | alt fill |
|---|---:|---:|---:|---|---:|---:|---:|
| dip | 155 | 155 | -25.1% | [-29.6, -20.6] | -10.0% | -26.4% | -27.2% |
| R0 | 914 | 914 | -19.9% | [-23.9, -15.6] | n/a | -21.2% | -20.3% |

## How much each class loses (host trades classified at their decision time)

| Host | Class | n | mean | 95% CI | P&L $ |
|---|---|---:|---:|---|---:|
| dip | FACTORY | 11 | -51.7% | [-82.2, -21.3] | -114 |
| dip | COMPLETED | 6 | -20.5% | [-30.4, -6.0] | -25 |
| dip | UNRESOLVED | 23 | -22.8% | [-31.5, -12.7] | -105 |
| dip | ORGANIC | 115 | -23.2% | [-27.7, -18.6] | -534 |
| dip | flag:AIRDROP | 1 | +35.4% | n/a | +7 |
| dip | flag:SERIAL | 3 | +2.5% | [-26.8, +21.7] | +1 |
| dip | flag:INSTANT | 46 | -30.2% | [-42.4, -18.3] | -277 |
| dip | flag:FAST120 | 60 | -27.6% | [-37.8, -18.4] | -331 |
| R0 | OPERATOR | 233 | -3.0% | [-6.5, +0.4] | -138 |
| R0 | FACTORY | 137 | -46.3% | [-56.7, -35.2] | -1269 |
| R0 | COMPLETED | 26 | -35.5% | [-51.4, -16.4] | -184 |
| R0 | UNRESOLVED | 136 | +3.9% | [-11.0, +25.3] | +106 |
| R0 | ORGANIC | 382 | -28.3% | [-33.3, -22.9] | -2158 |
| R0 | flag:AIRDROP | 1 | +0.8% | n/a | +0 |
| R0 | flag:SERIAL | 13 | -28.9% | [-43.6, -10.8] | -75 |
| R0 | flag:INSTANT | 448 | -20.5% | [-25.3, -15.7] | -1837 |
| R0 | flag:FAST120 | 499 | -21.2% | [-25.6, -16.8] | -2116 |

## Gate variants

| Variant | flagged coins (dead set) | precision dead60 | missed winners | R0 flagged - unflagged [95% CI] | R0 kept mean | dip flagged - unflagged |
|---|---:|---:|---:|---|---:|---:|
| G-time | 2568 | 78.3% | 14.1% | -2.8% [-11.6, +5.2] | -18.4% | -4.0% (n 60/95) |
| G-chain | 1471 | 88.4% | 17.7% | -0.3% [-8.4, +7.3] | -19.8% | -17.5% (n 17/138) |
| G-chain+ | 1507 | 87.4% | 17.8% | -0.7% [-8.8, +6.9] | -19.6% | -13.2% (n 19/136) |
- G-chain vs G-time on R0's kept trades: -1.4% [-4.3, +1.5].
- G-chain+ vs G-time on R0's kept trades: -1.2% [-4.1, +1.8].

## Decision

```
{
 "shortlist": [
  {
   "gate": "G-time"
  },
  {
   "gate": "G-chain+"
  }
 ],
 "rule": "G-time + the chain variant whose kept R0 trades have the higher mean (tie -> G-chain)",
 "shortlist_written": true
}
```
