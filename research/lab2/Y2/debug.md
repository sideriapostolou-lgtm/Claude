# Y2 debug

- **Split:** `final_train`; usable coins: 450; span: 0.52 days.
- **Written:** 2026-10-09 02:52:30 UTC; runtime 5.3 s; PREREG sha256 `23acd7b4364a`; trials in the ledger: 2575.
- **Overall Y2 status:** PENDING (no official TRAIN run).

**Debug run on the census TRAIN third: mechanics and counts only. Returns are hidden and no parameter was chosen here.**

## Universe at the decision (g + 30 min; counts only)

- Usable 450; eligible 152 (ineligible by reason: {'instant': 277, 'curve_partial': 21}).
- Eligible with a warm rank: 152; terciles {'mid': 52, 'bottom': 56, 'top': 44}; reference pool median 307.0 coins (min 299); pool 473 eligible of 2089 graduates read; hour coverage from raw_curve_chunks.
- Eligible and alive: 47. Selector coins {'T3': 44, 'T5': 26, 'PE11': 77}; selected and alive {'T3': 14, 'T5': 7, 'PE11': 16, 'ALL': 47}.

## Configs

| role | config | trades | coins | terciles | placebo trades | horizon exits | entries/day |
|---|---|---:|---:|---|---:|---:|---:|
| T3|X60 | T3|X60 | 14 | 14 | {'top': 14} | 266 | 0 | 26.9 |
| T3|H178 | T3|H178 | 14 | 14 | {'top': 14} | 266 | 0 | 26.9 |
| T5|X60 | T5|X60 | 7 | 7 | {'top': 7} | 134 | 0 | 13.5 |
| T5|H178 | T5|H178 | 7 | 7 | {'top': 7} | 134 | 0 | 13.5 |
| PE11|X60 | PE11|X60 | 16 | 16 | {'bottom': 12, 'mid': 4} | 301 | 0 | 30.8 |
| PE11|H178 | PE11|H178 | 16 | 16 | {'bottom': 12, 'mid': 4} | 301 | 0 | 30.8 |
| dose | ALL|H178 | 47 | 47 | {'mid': 19, 'top': 14, 'bottom': 14} | 0 | 0 | 90.3 |

## Dose-response (ALL, H178)

- Trades by tercile: {'mid': 19, 'top': 14, 'bottom': 14}; PE11 16, rest 31.

## Decision

- **DEBUG**.
- mechanics and counts only; returns hidden
