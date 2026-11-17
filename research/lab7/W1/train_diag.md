# Lab 7 W1, TRAIN: why the convergence trade loses (post-hoc reading)

Written by `W1/diag.py` AFTER the TRAIN result was read. It re-reads two cells already in the ledger, decides nothing and adds no trial. Cents are per contract; CLV = Pinnacle's closing fair minus the entry price.

## `m0.05|tp0.05|slnone|tcutoff|taker` (115 round trips)

- gap at the signal (fair - print): median 5.7c, 90th percentile 7.9c; above 15c: 0.9 % of signals (no sign of sides mapped to the wrong team)
- the entries beat Pinnacle's close by +2.34c on average, yet the round trips lost -1.33c before fees, and the US fee took another 3.25c
- at the start, the last ASK for the bought side was still +2.53c below Pinnacle's closing fair: Polymarket's price did not converge to Pinnacle before the game

| exit | n | gross c | CLV c | close - exit price c |
|---|---|---|---|---|
| time | 85 | -2.92 | +1.79 | +4.26 |
| fair | 21 | +1.48 | +1.52 | +0.05 |
| tp | 9 | +7.08 | +9.11 | +2.03 |

| market kind, outcome | n | mean net | gross c | CLV c |
|---|---|---|---|---|
| 2way o=0 | 29 | -0.0901 | -0.40 | +3.10 |
| 2way o=1 | 44 | -0.0834 | -1.02 | +4.99 |
| 3way o=0 | 20 | -0.1399 | -2.53 | -1.55 |
| 3way o=1 | 22 | -0.1012 | -2.09 | +0.08 |

## `m0.02|tp0.02|sl0.03|tcutoff|taker` (764 round trips)

- gap at the signal (fair - print): median 2.7c, 90th percentile 6.1c; above 15c: 1.2 % of signals (no sign of sides mapped to the wrong team)
- the entries beat Pinnacle's close by +0.77c on average, yet the round trips lost -1.15c before fees, and the US fee took another 3.19c
- at the start, the last ASK for the bought side was still +1.01c below Pinnacle's closing fair: Polymarket's price did not converge to Pinnacle before the game

| exit | n | gross c | CLV c | close - exit price c |
|---|---|---|---|---|
| time | 306 | -1.17 | +1.13 | +2.30 |
| sl | 219 | -3.62 | -1.62 | +1.94 |
| tp | 144 | +1.71 | +3.58 | +1.91 |
| fair | 95 | +0.28 | +1.01 | +0.73 |

| market kind, outcome | n | mean net | gross c | CLV c |
|---|---|---|---|---|
| 2way o=0 | 197 | -0.1039 | -1.06 | +1.36 |
| 2way o=1 | 218 | -0.0972 | -1.03 | +2.13 |
| 3way o=0 | 131 | -0.1305 | -1.86 | -1.55 |
| 3way o=1 | 218 | -0.0856 | -0.93 | +0.39 |

Soccer markets: o=0 is Yes, o=1 is No. 2-way markets: o=0 is the first-listed team.
