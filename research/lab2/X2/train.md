# X2 train

- **Split:** `train`; usable coins: 3863; span: 4.00 days; reference sizes (alive coins at their checkpoint): {'breadth@30': 1408, 'breadth@60': 931, 'pressure@30': 1408, 'pressure@60': 931}.
- **Written:** 2026-10-09 05:18:03 UTC; runtime 15.9 s; PREREG sha256 `d05337e31cec`; trials in the ledger: 2632.
- **Overall X2 status:** KILLED (dose-response gate failed on TRAIN).

## Dose-response gate (PREREG 8)

- Decision: **KILL**; passing checkpoints: [].

| checkpoint | obs | coins per bin [0-.5, .5-.8, .8-.9, .9-1] | bin means | top − all | inversions | decision | pressure-rank bin means (diagnostic) |
|---|---:|---|---|---:|---:|---|---|
| 30 min | 922 | [439, 301, 79, 103] | ['-19.2%', '-46.8%', '-52.2%', '-49.2%'] | -14.8% | 2 | FAIL | ['-5.8%', '-39.6%', '-76.1%', '-36.1%'] |
| 60 min | 283 | [141, 82, 29, 31] | ['-10.0%', '-22.7%', '-45.0%', '-24.3%'] | -5.5% | 2 | FAIL | ['-9.3%', '-15.1%', '-46.7%', '-16.3%'] |

## Decision

- **KILLED_DOSE**.
- Shortlist written: False.
- PREREG 8: the dose-response gate precedes any strategy P&L; the grid was not run
