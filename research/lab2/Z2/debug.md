# Z2 debug

- **Split:** `final_train`; usable coins: 450; span: 0.52 days.
- **Written:** 2026-10-09 02:43:53 UTC; runtime 21.6 s; PREREG sha256 `18a30e2bc860`; trials in the ledger: 2575.
- **Overall Z2 status:** PENDING (no official TRAIN run).

**Debug run on the census TRAIN third: mechanics and counts only. Returns, exit reasons and placebo outcomes are hidden, and no parameter was chosen here.**

## Event counts (no returns)

- Coins: 450; speed: {'instant': 277, 'slow': 173}; traded bars inside the entry window (start ≥ g + 7 min, decision ≤ g + 120 min): 16583.

| q | whale bars | coins with one | strata of the first whale bar |
|---|---:|---:|---|
| q0.03 | 77 | 47 | {'instant|X<50': 11, 'slow|X<50': 28, 'slow|X>=100': 1, 'slow|50-100': 6, 'instant|X>=100': 1} |
| q0.06 | 19 | 11 | {'slow|X<50': 3, 'instant|X>=100': 1, 'instant|X<50': 6, 'slow|50-100': 1} |

## Configs

| config | trades | coins | strata | placebo trades | horizon exits | entries/day |
|---|---:|---:|---|---:|---:|---:|
| q0.03|h15|time | 47 | 47 | {'slow|X<50': 28, 'instant|X<50': 11, 'slow|50-100': 6, 'slow|X>=100': 1, 'instant|X>=100': 1} | 725 | 0 | 90.3 |
| q0.03|h15|seller | 47 | 47 | {'slow|X<50': 28, 'instant|X<50': 11, 'slow|50-100': 6, 'slow|X>=100': 1, 'instant|X>=100': 1} | 725 | 0 | 90.3 |
| q0.03|h60|time | 47 | 47 | {'slow|X<50': 28, 'instant|X<50': 11, 'slow|50-100': 6, 'slow|X>=100': 1, 'instant|X>=100': 1} | 725 | 0 | 90.3 |
| q0.03|h60|seller | 47 | 47 | {'slow|X<50': 28, 'instant|X<50': 11, 'slow|50-100': 6, 'slow|X>=100': 1, 'instant|X>=100': 1} | 725 | 0 | 90.3 |
| q0.06|h15|time | 11 | 11 | {'instant|X<50': 6, 'slow|X<50': 3, 'instant|X>=100': 1, 'slow|50-100': 1} | 151 | 0 | 21.1 |
| q0.06|h15|seller | 11 | 11 | {'instant|X<50': 6, 'slow|X<50': 3, 'instant|X>=100': 1, 'slow|50-100': 1} | 151 | 0 | 21.1 |
| q0.06|h60|time | 11 | 11 | {'instant|X<50': 6, 'slow|X<50': 3, 'instant|X>=100': 1, 'slow|50-100': 1} | 151 | 0 | 21.1 |
| q0.06|h60|seller | 11 | 11 | {'instant|X<50': 6, 'slow|X<50': 3, 'instant|X>=100': 1, 'slow|50-100': 1} | 151 | 0 | 21.1 |

## Decision

- **DEBUG**.
- mechanics and counts only; returns hidden
