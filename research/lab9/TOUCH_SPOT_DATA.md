# Causal spot inputs and touch-index coverage

Checked 2026-10-12. This is a data audit, not a return or profitability result.

## Coinbase spot and volatility

`touch_spot_data.py` collects public BTC-USD and ETH-USD hourly candles from
`https://api.exchange.coinbase.com/products/{product}/candles?granularity=3600`.
It reuses the Lucas history collector's response envelopes and extends the range
back to December 2024. Raw data remains outside git.

| Input | BTC-USD | ETH-USD |
|---|---:|---:|
| Requested hourly grid | 2024-12-01 00:00 to 2026-10-12 19:00 UTC exclusive | Same |
| Expected hours | 16,339 | 16,339 |
| Observed hours | 16,329 | 16,329 |
| Missing hours | 10 | 10 |
| Longest missing run | 5 hours | 5 hours |
| Hours with all 721 trailing closes present | 14,169 | 14,169 |

Both assets are missing 2025-10-25 16:00–20:00 UTC and 2026-05-08 02:00–06:00 UTC,
inclusive. Narrow follow-up requests confirm both gaps. We do not fill them.
Consequently, a thirty-day volatility window crossing a gap is ineligible, even
though the overall archive is more than 99.9% populated.

The feature uses exactly 720 adjacent one-hour log returns from 721 closes.
`sigma_hour` is their population standard deviation; annualized volatility is
`sigma_hour * sqrt(24 * 365)`. The newest usable candle is the latest one whose
start plus 3,600 seconds plus a five-second delay is no later than the decision.
The candle's start timestamp never makes its close available early. Missing latest
hours, missing interior hours, inconsistent duplicates, invalid OHLC, or zero
volatility reject the feature. No return jumps across a missing hour.

Five seconds is a preregistered availability assumption, not measured historical
publication latency. Today's backfill does not prove when Coinbase first published
or later revised a historical candle. These features are explicitly a spot proxy;
they do not prove a Kalshi contract was still untouched.

Raw evidence: `/tmp/lab9-lucas/candles/{BTC,ETH}/` and
`/tmp/lab9-touch-spot/coinbase/{BTC-USD,ETH-USD}/`. Gap checks are under
`/tmp/lab9-touch-spot/gap-check/`. Combined coverage manifests list every source
file and SHA-256 under `/tmp/lab9-touch-spot/`:

- `BTC-combined-coverage.json`: `949e5cd098ab5fde9a10d690510f4d740f5aea52543d6a669e8503da29a338af`
- `ETH-combined-coverage.json`: `7ecadbec405849b9218b12b46b0160f8954651edd61395e290e566a75e515f13`

These session files are temporary, not a promise of durable storage. Rebuild a
standalone archive with:

```bash
python research/lab9/touch_spot_data.py --directory /tmp/lab9-touch-rebuild \
  --start 2024-12-01 --end 2026-10-13
```

An end beyond the retrieval time does not certify future completeness: candles
still open at request time are discarded and coverage reports the missing hours.
For reproducible completed-period work, use an end already in the past.

## CF Benchmarks is a separate, missing history input

The public [BRTI](https://www.cfbenchmarks.com/data/indices/BRTI) and
[ETHUSD_RTI](https://www.cfbenchmarks.com/data/indices/ETHUSD_RTI) pages returned
HTTP 200. Their summary charts contained 24 hourly points at the 22:30 UTC check;
that is not a twelve-month archive of the within-minute index observations.
Both pages say, “Use and distribution of the CF Benchmarks data requires a license
from CF Benchmarks or its authorized licensing agents,” and direct users seeking
historic service data to their licensing contact. No signup, credential, paid feed,
or undocumented authenticated interface was used. A suitable unlicensed archive
has **not been established**; this is not a proof none exists anywhere.

This matters independently of volatility. The Kalshi data audit found materially
different wording between the current contract PDF and archived market secondary
rules: trimming the top/bottom 20% within each minute versus cumulative/full-period
wording. Read `KALSHI_TOUCH_DATA.md` for the exact evidence and limitations. The
operative rules version must be resolved for each event. Then its named CF index
and sampling/trimmed-average rule must show that the barrier was not already hit
before an entry. Coinbase hourly highs/lows, a far-away current spot price, and an
event's eventual YES/NO result cannot establish that historical entry fact.

The collector therefore always labels `touch_history_verified=false`. No practice
desk should be approved on the basis of these spot features alone.
