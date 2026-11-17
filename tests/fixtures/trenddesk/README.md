# tests/fixtures/trenddesk

`candles_1d.csv` (41 KB) feeds `tests/test_trenddesk.py`: the parity test against lab 3's own code
(`research/lab3/core.py`, `hypotheses.py`) and the desk's runtime tests (served through a fake Coinbase).

| Column | Meaning |
|---|---|
| `day` | The UTC day of the bar (it opens at 00:00 UTC and closes at the next 00:00 UTC) |
| `coin` | `BTC`, `ETH` or `SOL` (Coinbase products `BTC-USD`, `ETH-USD`, `SOL-USD`) |
| `close` | The bar's close in USD, as Coinbase served it |
| `volume` | The bar's volume in base units, rounded to 4 decimals |

Real data: 400 completed days, 2025-09-04 to 2026-10-08, for each coin (1,200 rows, no gaps), taken read-only from
lab 3's cache of Coinbase Exchange public daily candles (`$SCRATCH/lab3/candles_1d.parquet`, written by
`research/lab3/data.py` on 2026-10-09). The cache's last bar (2026-10-09) was still open when it was fetched, so it is
left out. Lab 3's universe needs 200 earlier bars, so in this window it holds all three coins from 2026-03-23 on; the
parity test starts its forward runs on or after that day. Gaps are made in the tests themselves (a bar deleted),
never in the file.

The builder script is `build_fixture.py` in the session scratchpad (`trenddesk/`): it reads the cache with pandas,
keeps the three coins' last 400 completed days and writes `day, coin, close, volume`.
