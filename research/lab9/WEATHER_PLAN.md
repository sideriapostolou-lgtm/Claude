# Weather decided-bucket measurement — frozen plan

Frozen 2026-10-12, before this worker fetched outcomes or trade prints. This is a
public-data measurement, not a trading strategy or a claim that a fill was available.
No weather desk will be built in this task.

## Cohort and sampling

Use all settled daily-high contracts for market dates 2026-10-05 through
2026-10-11 inclusive in six series, selected before fetching: KXHIGHNY,
KXHIGHCHI, KXHIGHMIA, KXHIGHLAX, KXHIGHAUS and KXHIGHDEN. Include quiet markets
and city-days without qualifying observations. Preserve missing data and API
failures as unknown. This recent cohort is descriptive; it is neither a strategy
training set nor an unseen profitability test. Do not select a winning subset.

Read each series' current contract rules, market rules and settlement-source
metadata. Verify the climate station rather than substituting the airport used
by Polymarket. Use each market date's local **standard-time** midnight-to-midnight
climate day only if supported by its rules/source documentation. Flag uncertain
station, calendar or historical-rule continuity and exclude from any executable
verdict. The planned mapping, subject to explicit verification, is NYC/Central
Park (-5), MDW/Chicago Midway (-6), MIA (-5), LAX (-8), AUS (-6), DEN (-7).

## Observation proxy and timing

Download IEM ASOS METAR/SPECI rows with UTC observation time, tmpf and raw METAR.
Use only explicit current-temperature `T`-group values (0.1 C precision), and
require the raw station to match. Do not mistake a six-hour max group for the
current observation. For conservative integer-F bucket comparisons use the
lowest nearest-integer F compatible with the reported 0.1 C rounding interval.
Reject missing/invalid/nonfinite readings; never forward fill across days.
Use the first qualifying observation for every NO lock candidate: a bounded
bucket is exceeded, or a strictly-less-than bucket has been reached. Unsupported
strike semantics remain unknown. No upper-tail YES trade is in this cohort.

IEM's `valid` timestamp is observation time, **not receipt or publication time**.
Call this an observation-time proxy, not a tradable lock. No historical record in
this plan proves when our Railway server could have received that report.
Report zero, 30, 60 and 120 second assumed-arrival stresses, without treating any
as measured latency; the primary window is [observation, observation+180 seconds).
Report minute bins [0,60), [60,120), [120,180). Fetch [observation-60,
observation+180] to expose accidental pre-observation leakage, but exclude
negative delays from all after-lock totals. Do not optimize delays after results.

## Print measurement, integrity and output

Use Kalshi public trade prints, exhaustive cursor pagination within each locked
market's time interval, deduplicated by trade ID. No keys. At most one request
per second for this worker and at least 0.5 seconds between workers through the
shared `/tmp/lab9-kalshi-rate.lock` plus timestamp file. Honor 429 Retry-After and
back off. Record successful coverage, incomplete pages and errors separately.

For every market and minute bin report print count, contract size, NO price,
weighted average/min/max, exact 0.97 and 0.98 quantities, and quantities below,
within and above [0.97,0.98]. Split by whether taker_side is NO (a NO buyer took)
or YES (a NO bid was hit), with unknown roles separate. Prices and sizes use
fixed-point dollars/count fields, validated for positivity and complement
consistency. Prints are completed transactions between other traders. They do
not reveal the book, remaining depth, queue position, order-entry time or whether
our hypothetical resting bid would fill. Therefore **achievable fills and P&L
remain unknown**, even if target-price prints are present. No backtest profit
will be imputed from print volume.

Audit every proxy against Kalshi's settled result and expiration value. Report
contradictions and compare the day's raw and conservative METAR maximum with the
published climate high. A zero observed contradiction rate cannot establish the
scout's universal assertion that a climate report is never below METAR. Document
rounding, revisions, station and day-boundary caveats. Show all six cities and
all seven days, including zero-count cells, in the saved derived artifact.

Raw source responses and request metadata go to `/tmp/lab9-weather/`; publish a
reproducible script, fake-only tests and `WEATHER_WINDOW.md` with source URLs,
counts, hashes, exclusions and a plain-words build/no-build verdict. This task
cannot establish a build gate from historical prints alone; actual public
receipt-time capture plus executable book/queue evidence would be required.
