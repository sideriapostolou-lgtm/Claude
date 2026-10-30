# Y2 train

- **Split:** `train`; usable coins: 3863; span: 4.00 days.
- **Written:** 2026-10-09 10:43:44 UTC; runtime 53.6 s; PREREG sha256 `c0ff817c7364`; trials in the ledger: 2678.
- **Reference-pool lookback** (24 h before the split start, PREREG 8): all 24 curve hours scanned.
- **Overall Y2 status:** NO EDGE (nothing qualified on TRAIN).

## Universe at the decision (g + 30 min; counts only)

- Usable 3863; eligible 1420 (ineligible by reason: {'instant': 2208, 'curve_partial': 235}).
- Eligible with a warm rank: 1420; terciles {'mid': 484, 'top': 474, 'bottom': 462}; reference pool median 342.0 coins (min 297); pool 1736 eligible of 6766 graduates read; hour coverage from raw_curve_chunks.
- Eligible and alive: 492. Selector coins {'T3': 474, 'T5': 278, 'PE11': 689}; selected and alive {'T3': 150, 'T5': 83, 'PE11': 169, 'ALL': 492}.

## Configs

| role | config | n | mean | median | 90% CI coin | 90% CI 6-h block | w/o top 2 | placebo diff (eligible) | placebo diff (unmatched) | costs ×1.5 | same-bar exits |
|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|
| T3|X60 | T3|X60 | 150 | -39.6% | -52.0% | [-44.0, -34.9] | [-46.0, -32.4] | -41.4% | -6.4% | -5.9% | -40.8% | -39.8% |
| T3|H178 | T3|H178 | 150 | -41.0% | -52.9% | [-46.7, -34.5] | [-48.4, -32.2] | -44.3% | -5.2% | -1.5% | -42.2% | -41.1% |
| T5|X60 | T5|X60 | 83 | -41.4% | -52.5% | [-46.8, -35.7] | [-48.4, -33.5] | -43.4% | -5.9% | -6.4% | -42.5% | -41.8% |
| T5|H178 | T5|H178 | 83 | -35.8% | -52.6% | [-45.2, -25.3] | [-47.5, -21.5] | -41.6% | +4.1% | +5.4% | -37.1% | -36.2% |
| PE11|X60 | PE11|X60 | 169 | -29.0% | -51.7% | [-38.6, -17.7] | [-40.3, -16.3] | -35.8% | +3.7% | +4.9% | -30.4% | -28.9% |
| PE11|H178 | PE11|H178 | 169 | -38.0% | -53.1% | [-44.7, -30.9] | [-45.9, -29.5] | -41.0% | -2.9% | +2.2% | -39.2% | -38.3% |
| dose | ALL|H178 | 492 | -40.4% | -53.6% | [-44.5, -36.0] | [-45.9, -34.4] | -42.1% | n/a | n/a | n/a | n/a |

## Dose-response (ALL, H178)

- Trades by tercile: {'mid': 194, 'top': 150, 'bottom': 148}; PE11 169, rest 323.
- Mean by tercile: {'top': '-41.0%', 'bottom': '-39.6%', 'mid': '-40.5%'}; top − bottom -1.4% [-15.3, +11.9]; PE11 − rest +3.7% [-6.7, +14.6]; consistency {'T': False, 'PE11': True}.

## Decision

- **NO_CONFIG**.
- T3|X60: n 150, mean -39.6%, w/o top 2 -41.4%, 90% CI low -44.0%, placebo diff -6.4%, mechanism False, qualifies False.
- T3|H178: n 150, mean -41.0%, w/o top 2 -44.3%, 90% CI low -46.7%, placebo diff -5.2%, mechanism False, qualifies False.
- T5|X60: n 83, mean -41.4%, w/o top 2 -43.4%, 90% CI low -46.8%, placebo diff -5.9%, mechanism False, qualifies False.
- T5|H178: n 83, mean -35.8%, w/o top 2 -41.6%, 90% CI low -45.2%, placebo diff +4.1%, mechanism False, qualifies False.
- PE11|X60: n 169, mean -29.0%, w/o top 2 -35.8%, 90% CI low -38.6%, placebo diff +3.7%, mechanism True, qualifies False.
- PE11|H178: n 169, mean -38.0%, w/o top 2 -41.0%, 90% CI low -44.7%, placebo diff -2.9%, mechanism True, qualifies False.
- Shortlist written: False .
- Reason: a powered config failed the mean / top-2 / matched-control / mechanism bars.
