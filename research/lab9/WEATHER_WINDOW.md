# Weather runner-up: prices exist, achievable fills remain unproved

2026-10-12. **Measure only; do not build a weather desk yet.** Across the frozen
seven-day, six-city cohort, other traders exchanged **1,062 contracts at 97–98c**
within three minutes of a conservative METAR observation proxy. Those trades
occurred in only **5 of 92** candidate contract windows. We have neither historical
public arrival times nor order-book/queue evidence showing that we could buy them.

There is a material correction to the scout: **all 252 sampled Kalshi markets
name The Weather Company (TWC), not the NWS daily climate report, as their primary
settlement source.** METAR readings therefore do not establish an irrevocable
contract result. The contract itself warns about rounding, preliminary values and
material errors. This measurement does not pass the owner's “we'd get filled at
0.97–0.98” build gate. No app code, practice desk or real trading was added.

## Frozen measurement and data coverage

The preregistration is [WEATHER_PLAN.md](WEATHER_PLAN.md), SHA256
`97227b25b22267ed99534a4196a1b5cb088c5659ceff190781aefef22a4d2f9e`.
No parameter was selected after reading these new outcomes.

- Dates: **2026-10-05 through 2026-10-11**, seven climate dates, all six preregistered cities.
- **252 settled contracts**, 42 city-days, six brackets per city-day; zero missing cohort cells.
- **1,394 valid current-temperature T-group observations** in the wider downloaded
  Oct 4–12 archive; 15 rows excluded for absent/invalid current T-group. Every
  cohort city-day had 24–40 accepted observations. This is METAR/SPECI sampling,
  not the full minute-by-minute ASOS sensor history.
- **92 conservative NO proxies**, clustered in 36 city-days. These are first
  observed lower-bound integer-F values beyond a finite bucket or at a strictly
  less-than bucket's boundary. Upper-tail YES contracts were excluded as planned.
- **92/92 bounded public trade queries exhausted their cursors**, with no query
  failures, wrong tickers, conflicting IDs or invalid price/size records.
- **193 after-proxy prints**, **11,331.57 contracts**, in 24 of the 92 windows;
  68 candidate windows had no print in the first three minutes. Another 67
  fetched prints fell outside the fixed interval and were excluded.
- **110 cached public responses**: six series descriptions, six market listings,
  six IEM archives and 92 trade queries. No keys or authenticated endpoints.

Rows with no prints remain zero; unknown achievable fills do not become zero
fills or a zero-profit strategy. The complete 42-cell table is
[WEATHER_daily.csv](WEATHER_daily.csv). All 193 observed prints, with their
individual timing, price, quantity and taker direction, are in
[WEATHER_prints.csv](WEATHER_prints.csv).

## What traded in the first three minutes

Times below are measured from the METAR's **observation timestamp**. They are not
latency from a published signal or a simulated fill time.

| Observation delay | Prints | Contracts | Size-weighted NO price | NO price range | Contracts at 97–98c |
|---|---:|---:|---:|---:|---:|
| 0–60 seconds | 35 | 925.16 | 97.29c | 84–99c | 10 |
| 60–120 seconds | 76 | 6,968.43 | 98.84c | 89–99c | 493 |
| 120–180 seconds | 82 | 3,437.98 | 97.77c | 83–99c | 559 |
| Total | 193 | 11,331.57 | — | 83–99c | **1,062** |

Of those 1,062 target-price contracts, **314 traded at 97c** and **748 at 98c**,
in 32 prints. **997 had NO as the taker side**: someone bought NO from a resting
YES-side counterparty. Only **65 had YES as the taker side**, the orientation
consistent with someone hitting an existing NO bid. The latter is still not proof
that our bid could have beaten the existing queue. No taker roles were missing.
There were also 983.77 contracts below 97c and 9,285.80 at 99c; cheap prints do not
prove a final or contemporaneously public weather result.

| Series / verified rule station | Contracts sampled | NO proxies | Windows with any print | Contracts printed | Contracts at 97–98c | Windows with 97–98c prints |
|---|---:|---:|---:|---:|---:|---:|
| KXHIGHNY / CLINYC (Central Park) | 42 | 4 | 2 | 504.70 | 92 | 1 |
| KXHIGHCHI / CLIMDW (Midway) | 42 | 19 | 10 | 4,324.54 | 601 | 3 |
| KXHIGHMIA / CLIMIA | 42 | 17 | 1 | 205.73 | 0 | 0 |
| KXHIGHLAX / CLILAX | 42 | 14 | 5 | 4,879.86 | 0 | 0 |
| KXHIGHAUS / CLIAUS | 42 | 22 | 6 | 1,416.74 | 369 | 1 |
| KXHIGHDEN / CLIDEN | 42 | 16 | 0 | 0 | 0 | 0 |

Target-price prints were concentrated in five contracts:
`KXHIGHNY-26OCT10-T66` (92), `KXHIGHCHI-26OCT10-B77.5` (10),
`KXHIGHCHI-26OCT08-B70.5` (410), `KXHIGHCHI-26OCT06-B72.5` (181), and
`KXHIGHAUS-26OCT06-B88.5` (369). There is no inference that other cities or dates
would have worked, or that these volumes scale to a new participant.

The frozen arrival stresses retain only prints after an **assumed**, unmeasured
arrival delay and before the original observation+180s endpoint:

| Assumed arrival delay | Remaining prints | Remaining total contracts | Remaining 97–98c contracts | NO taker | YES taker |
|---|---:|---:|---:|---:|---:|
| 0s | 193 | 11,331.57 | 1,062 | 997 | 65 |
| 30s | 169 | 10,675.73 | 1,062 | 997 | 65 |
| 60s | 158 | 10,406.41 | 1,052 | 997 | 55 |
| 120s | 82 | 3,437.98 | 559 | 559 | 0 |

## Rules, rounding and the supposed lock

The six public series descriptions point to the current
[GLOBALTEMPERATURE contract terms](https://assets.kalshi.com/contract_terms/GLOBALTEMPERATURE.pdf),
whose source hierarchy is TWC first, then NWS, then the relevant national weather
service. They define “above” as strict `>`, “below” as strict `<`, “between” as
inclusive, and settlement at the source's full published precision. The first
official non-preliminary report is used; later or materially erroneous reports
can invoke the exchange's review provisions. Generic source links alone would
not establish historical rules, so **every sampled market's actual primary and
secondary rule text was also retained**. All 252 explicitly say TWC and include
the expected CLI station token; Central Park is not LaGuardia, and Midway is not
O'Hare. This report makes no claim about when older series changed source.

For example, the [Oct 11 NYC market](https://api.elections.kalshi.com/trade-api/v2/markets/KXHIGHNY-26OCT11-T69)
states that preliminary Weather Company data can have rounding/conversion
differences from the final value, and even a “Final” label does not preclude a
material-error review. The [TWC source page](https://weather.com/kalshi) is the
contract-designated source; the IEM METAR archive is a secondary observation feed.

**Zero of the 92 proxies contradicted the eventual NO settlement**, but this is a
small, dependent, retrospectively observed cohort. It does not prove a universal
lock or a live win rate. Seven of 42 city-days had raw Celsius-to-Fahrenheit
T-group maxima **0.02–0.08 F above** the settled integer value. For example, NYC
Oct 6 was 60.08 F versus a settled 60.00 F, and Denver Oct 5 was 87.08 F versus
87.00 F. No conservative lower-integer maximum exceeded settlement. That explains
why the scout's literal “climate high is never below METAR” assertion is unsafe:
precision and rounding alone can make it false without a substantive weather error.

The parser requires an actual current `T` remark, not an integer-looking converted
`tmpf`, and bounds its 0.1 C rounding uncertainty before forming an integer-F
proxy. **That integer comparison is a deliberately labeled NWS-style proxy, not
an assumption that TWC's full-precision contractual value follows it.** The fixed
local-standard-time climate-day convention is also flagged as unproved for these
TWC markets; matching station identifiers do not establish identical collection,
publication, revision or day-boundary rules. A definitive executable signal
requires the designated source's applicable conventions, not a convenient proxy.

Two proxy observations carry `COR` correction flags (Miami Oct 7 and Oct 10);
neither had target-price prints. Historical archive records can be amended, and
the original public receipt times were not recovered for any observation. The
IEM `valid` field dates the weather observation. It cannot establish when a
reader or our server could first know it, or whether a printed trade preceded
publication. Those unknowns cannot be repaired by assigning a made-up delay.

## Reproduction, integrity and next step

```bash
python research/lab9/weather_window.py --output /tmp/lab9-weather
python -m pytest -q tests/test_lab9_weather_window.py
ruff check research/lab9/weather_window.py tests/test_lab9_weather_window.py
mypy research/lab9/weather_window.py
```

The script makes public GETs only, uses fixed-point prices/sizes, preserves all
cohort cells, applies half-open timing bins, deduplicates exact trade IDs and
fails a window on conflicting duplicates. Each cached body must match its full
URL, HTTP status and saved SHA256 before use. It shares the cross-worker Kalshi
rate limiter, remains at most one request per second itself, and respects 429
backoff. A server-requested cooldown over one minute aborts that query rather
than querying early. All **19 fake-only tests**, changed-file Ruff and script
mypy passed. No profitability result was computed or optimized.

Source requests include `/series/{series}`, paginated
`/markets?series_ticker={series}&status=settled`, and
`/markets/trades?ticker={ticker}&min_ts={observation-60}&max_ts={observation+180}`.
IEM request documentation: <https://mesonet.agron.iastate.edu/request/download.phtml>;
CSV endpoint: <https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py>.
Full request URLs, UTC retrieval times and response hashes are saved alongside
raw bodies in `/tmp/lab9-weather/raw/`. These temporary raw files are outside git
and may disappear with this workspace; rerunning later can encounter source
revisions. The portable derived evidence is committed with these hashes:

- `WEATHER_daily.csv`: `f26fdfcdf743e46ac609aa3fa372716f38c0dbc58b9e90fefe5928f76d775d86`
- `WEATHER_prints.csv`: `71ff655d7944c8a329f0b1a38f3f1431661afbf5853f6c667f345e68cb419500`
- Raw-derived `summary.json`: `5223d8495b61e37d5f21c3c26c31e9e321bf1679814f389775ba3c0a0ee4da3d`

**Recommendation:** keep weather at measurement only. The next evidence needed
is synchronized live public receipt timestamps from the contract-designated
weather source, applicable source/day/rounding rules, and market books/trades
showing price persistence and queues after that receipt. Historical prints are
encouraging evidence that 97–98c transactions sometimes occur, but they do not
establish that this bot can get them or make money after costs.
