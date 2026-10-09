# Y4 debug

- **Split:** `final_train`; usable coins: 450; span: 0.52 days.
- **Written:** 2026-10-09 03:15:10 UTC; runtime 43.3 s; PREREG sha256 `7bd47ae03b72`; trials in the ledger: 2575.
- **Overall Y4 status:** PENDING (no official TRAIN run).

**Debug run on the census TRAIN third: mechanics and counts only. Returns and forward moves are hidden and no parameter was chosen here.**

## Event counts (no outcomes)

- Coins 450; decision minutes at ages 10-115 min: 47264.

| set | touches BREAK / HOLD / REJECT | touch coins | BREAK events (bars, coins) | RETEST events (bars, coins) |
|---|---|---:|---|---|
| round | 35 / 55 / 46 | 90 | 71, 47 | 35, 26 |
| shifted | 38 / 71 / 45 | 92 | 69, 48 | 28, 21 |

- round: BREAK events by level {'500k': 2, '100k': 12, '250k': 13, '10k': 13, '25k': 11, '50k': 17, '1M': 3}; RETEST events by level {'500k': 1, '100k': 9, '250k': 7, '10k': 8, '25k': 4, '50k': 6}.
- shifted: BREAK events by level {'320k': 9, '12.8k': 11, '640k': 11, '128k': 13, '32k': 13, '64k': 10, '1.28M': 2}; RETEST events by level {'320k': 4, '32k': 8, '12.8k': 6, '128k': 7, '640k': 1, '64k': 2}.
- At each coin's first round BREAK (decision-time state, no later price): market cap median $56,891 (IQR $20,608-$122,851, n 47); age median 39 min (IQR 22 min-51 min, n 47); $20 round trip median 3.56% (IQR 3.45%-3.92%, n 47); fee tier (bps, one side) {'100': 4, '120': 19, '125': 18, '115': 6}.

## Event study (PREREG 7: the folklore, gross mid-price moves)

- Observations 290 from 116 coins.

- Touch counts {'round|BREAK': 35, 'round|HOLD': 55, 'round|REJECT': 46, 'shifted|BREAK': 38, 'shifted|HOLD': 71, 'shifted|REJECT': 45}; statistics hidden on the debug split (forward moves are outcomes).

## Configs

| config | trades | coins | levels | entry age (min) | placebo trades | controls | horizon exits | entries/day |
|---|---:|---:|---|---|---:|---|---:|---:|
| break|h15|round | 47 | 47 | {'10k': 12, '50k': 11, '100k': 8, '25k': 6, '250k': 6, '500k': 2, '1M': 2} | {'10-30': 19, '30-60': 17, '60-90': 5, '90-116': 6} | 341 | {'unmatched': 940} | 0 | 90.3 |
| break|h60|round | 47 | 47 | {'10k': 12, '50k': 11, '100k': 8, '25k': 6, '250k': 6, '500k': 2, '1M': 2} | {'10-30': 19, '30-60': 17, '60-90': 5, '90-116': 6} | 341 | {'unmatched': 940} | 0 | 90.3 |
| retest|h15|round | 26 | 26 | {'10k': 8, '100k': 7, '50k': 4, '25k': 3, '250k': 3, '500k': 1} | {'10-30': 9, '30-60': 12, '60-90': 2, '90-116': 3} | 171 | {'unmatched': 520} | 0 | 50.0 |
| retest|h60|round | 26 | 26 | {'10k': 8, '100k': 7, '50k': 4, '25k': 3, '250k': 3, '500k': 1} | {'10-30': 9, '30-60': 12, '60-90': 2, '90-116': 3} | 171 | {'unmatched': 520} | 0 | 50.0 |
| break|h15|shifted | 48 | 48 | {'12.8k': 10, '640k': 9, '32k': 9, '320k': 8, '128k': 7, '64k': 3, '1.28M': 2} | {'10-30': 21, '30-60': 18, '60-90': 8, '90-116': 1} | 416 | {'unmatched': 960} | 0 | 92.3 |
| break|h60|shifted | 48 | 48 | {'12.8k': 10, '640k': 9, '32k': 9, '320k': 8, '128k': 7, '64k': 3, '1.28M': 2} | {'10-30': 21, '30-60': 18, '60-90': 8, '90-116': 1} | 416 | {'unmatched': 960} | 0 | 92.3 |
| retest|h15|shifted | 21 | 21 | {'32k': 6, '12.8k': 5, '128k': 5, '320k': 4, '64k': 1} | {'10-30': 4, '30-60': 9, '60-90': 6, '90-116': 2} | 100 | {'unmatched': 420} | 0 | 40.4 |
| retest|h60|shifted | 21 | 21 | {'32k': 6, '12.8k': 5, '128k': 5, '320k': 4, '64k': 1} | {'10-30': 4, '30-60': 9, '60-90': 6, '90-116': 2} | 100 | {'unmatched': 420} | 0 | 40.4 |

## Decision

- **DEBUG**.
- mechanics and counts only; returns hidden
