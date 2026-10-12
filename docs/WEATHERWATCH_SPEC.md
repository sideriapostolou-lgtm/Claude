# Weather lock stopwatch: prospective measurement protocol

Frozen 2026-10-12, before this worker collects a live trial. This is a read-only
observation experiment, not a weather trading desk. No orders, portfolio reads,
account balance reads, capital allocation or money switches belong to it. The
owner must separately name amounts before any future real-order implementation.

The question is: **after a useful weather reading actually reaches this server,
what prices and size can we observe, and what remains unknown about buying them?**
Run for at least three days after verified Railway startup. Elapsed time is not
complete coverage; report missing stations, unavailable feeds, restarts and
partial days. Do not change thresholds after seeing returns. Any later strategy
selection needs its own preregistered held-out evaluation.

## 1. What the earlier scout did not establish

[The historical audit](../research/lab9/WEATHER_WINDOW.md) found 1,062 contracts
printed at 97–98c in five of 92 candidate observation windows. Trade prints were
not our fills, and their delay was measured from the weather observation's valid
time, not its public arrival. All 252 sampled Kalshi contracts named **The Weather
Company**, not NWS CLI, as their primary settlement source. Station, rounding,
day boundaries, preliminary readings and later corrections can matter.

Two agreeing METAR readings strengthen an observation proxy; they do not prove
that TWC's final contractual result must agree. Keep these quantities separate:

- a candidate threshold crossing;
- a confirmed observation proxy;
- an applicable official CLI report and any contradiction;
- the actual venue settlement and any contradiction;
- displayed depth and a conditional quote-persistence scenario;
- an executable, source-qualified result, which remains **unknown** in this trial.

Do not call any scenario a guaranteed lock, a real fill, account profit or a
measured amount of achievable cents per day.

## 2. Market and station coverage

Discover all series beginning `KXHIGH`, `KXLOWT` and `KXRAIN`. Retain each market's
actual rules, source, strike boundaries, inclusivity, station evidence, period,
fees and settlement. Never assign a Kalshi station from a Polymarket city label.
Station mappings require the identifier in that venue's own rules. Central Park
and Midway must not become LaGuardia and O'Hare.

The inventory includes international, inactive and non-daily series. Unknown
station mappings, ambiguous rules, unsupported periods and unavailable markets
remain explicit coverage gaps; discovering a series does not mean observing it.
Local standard-time daily boundaries, where available, are labeled **proxies**
until the designated settlement source's actual day convention is established.

The 2026-10-12 local public discovery check inspected all 126 matching Kalshi
series with no failed series queries; 58 had no open market. The frozen responses
contained 944 markets: 642 supported daily Kalshi markets, 60 supported daily
Polymarket US markets and 242 explicitly unsupported markets. Of the latter,
241 had non-daily/custom or unparsed periods (32 also lacked a station mapping);
one Paris market had conflicting rule/event dates and an unknown day boundary.
These are metadata/parser coverage counts, not Railway feed or executable-lock
coverage. Discovery remains dynamic and reports later additions or failures.

Independently discover the Polymarket US high-temperature families
`tc-temp-nychigh`, `tc-temp-mdwhigh`, `tc-temp-miahigh`, `tc-temp-laxhigh` and
`tc-temp-sfohigh`. Parse their own rule prose and boundaries rather than assuming
that a slug or similarly named Kalshi market has identical semantics.

## 3. Weather feeds and clocks

Record raw reports and normalized precision/QC evidence from NWS station latest
observations, aviationweather.gov METAR and MADIS ASOS-HFM. Retain source, station,
observation identity, valid time, request time, our first receipt time, monotonic receipt
clock/domain and later model-dispatch time. Provider publication/receipt fields,
where present, remain separate from our receipt time.

Respect `Cache-Control`, `Expires`, `Age`, documented limits and `Retry-After`.
Do not add cache-busting parameters or bypass throttling. Probe responses on
2026-10-12 advertised 60-second AWC and 300-second NWS cache lifetimes; these are
observed response policies, not promises that all reports have those latencies.
AWC documents 100 requests/minute. NWS does not publish a fixed quota. The worker
also bounds requests per origin and reports the actual next permitted poll.

MADIS documents a public ASOS One Minute Observations (OMO) product, processed
every five minutes into hourly files. One-minute measurement resolution therefore
does not imply one-minute publication or delivery. The anonymous XML endpoint's
verified `ASOS-HFM` provider returned **five-minute**, not one-minute, observations
in the local probe. Integrate that source as `madis_hfm`, preserve its actual
300-second resolution and measured arrival lag, and never set its independent
one-minute confirmation flag. Two distinct qualifying readings remain necessary.
Native one-minute OMO access/coverage has not been verified in this worker.
The HFM reader queries the public guest XML endpoint for each exact station's
last 30 minutes, no faster than once per station per 60 seconds and one request
per second overall, also honoring cache/cooldown responses. A 23:11:14 UTC local
probe on 2026-10-12 advertised a 60-second cache lifetime; its latest accepted
KMDW reading was valid at 22:55, a **974.07-second (16.2-minute) observed lag**.
That is one local sample, not a Railway measurement or a guarantee for other
stations. The public guest path's quota is undocumented; do not claim it is the
fastest possible weather source. The reader checks MADIS QC
flags and preserves the primary temperature's whole-Celsius uncertainty; printed
Kelvin decimal places do not establish extra sensor precision. Its bootstrap
records are left-censored, and it does not supply precipitation measurements.
IEM's separate one-minute product is an NCEI archive with monthly ingestion,
not a minute-by-minute live feed. Neither repeated METAR polling nor a historical
one-minute row substitutes for a verified current observation.

The first report seen after startup/reconnection may already have been public:
flag that sample as left-censored. `first_receipt - valid_time` is an observed
age, not proof of original publication latency. Preserve deduplication and trial
origin across restarts. Report startup/capture gaps separately rather than
backdating a signal to a report's valid time.

## 4. Candidates and confirmation

Reject suspect, maintenance-flagged, corrected/conflicting, invalid-time or
unusable-precision readings from confirmation. Preserve raw evidence and the
reason for rejection. Bound Celsius-to-Fahrenheit rounding uncertainty; a
rounded display value cannot be treated as an exact temperature.

- **High:** a conservative measured lower bound beyond a bracket's upper edge
  can create a NO proxy, respecting strict/inclusive contract boundaries.
- **Low:** a conservative upper bound below a bracket's lower edge can create
  the corresponding NO proxy. The running daily minimum only moves downward.
- **Rain:** use the largest conservative lower bound from a single verified,
  positive, complete accumulation interval wholly inside the applicable day.
  A normal hourly report at :53 or :56 can qualify without inventing a midnight
  report. Never sum overlapping rolling totals. Missing earlier hours, trace,
  resets and unknown intervals are not zero rain; the full-day total remains
  unknown. Crossing an upper bracket can imply NO; crossing a rain-above
  threshold can instead imply YES. Keep the actual side explicit, and still
  require two distinct qualifying readings. Unsupported periods stay uncovered.

The first accepted crossing starts a 600-second capture immediately. Confirmation
requires two distinct consecutive valid readings supporting the same side, or a
separately verified independent one-minute observation. NWS and AWC echoing the
same station/report/time count as one reading. An intervening invalid or
contradictory reading breaks the confirmation sequence. Confirmation extends
capture to at least 600 seconds after its actual model-dispatch time.

The scenario decision clock begins at confirmation, including measured feed and
dispatch delay. Never pretend we could act at the first unconfirmed crossing or
at an observation's historical valid time.

## 5. Books, trades and conditional scenarios

Use the existing narrow Kalshi market-WebSocket signer for book/trade channels
only. It may read `KALSHI_KEY_ID` and `KALSHI_PRIVATE_KEY` from Railway; it has no
portfolio or order methods. Never record credentials or authentication headers.
Public REST discovery/settlement/depth requests are separately bounded. Missing
keys or a failed stream produce visible degraded coverage, not an order fallback.

Polymarket US capture uses the public gateway. Its documented market WebSocket
requires authentication; no documented anonymous ordinary trade tape was found.
Report public REST depth at its actual cadence and trade capture as unavailable.
Do not invent prints from last-trade prices. The weather reader's aggregate US
REST budget is four requests/second, leaving capacity for existing desks;
second-by-second fresh depth for every concurrent market is not guaranteed.

Sample each accepted watch once per second for ten minutes while preserving
the book's original receipt/source age, snapshot/delta status and sequence gaps.
Repeated samples of one old quote are not new liquidity. A Kalshi snapshot
without exchange time is useful raw evidence but does not prove fresh executable
depth. Capacity limits and missing seconds remain visible.

Freeze two **alternative one-contract-per-market** scenarios: entry ask at or
below **$0.97** and at or below **$0.98**. The first eligible complete book after
confirmation records displayed depth once. Do not sum the same depth every
second or cherry-pick a later cheap quote after the initial assessment fails.

For a conditional entry, at least one contract must still be offered at no worse
than the initial price in a distinct fresh observation after a minimum **250 ms**
delay. Both local receipt and the REST request/exchange timestamp must establish
that the later quote is post-delay; book age must be at most three seconds. This
is quote-persistence evidence, not a promise that an IOC would fill. The delay is
a fixed model assumption; no actual weather order latency is measured.

Evaluate two separate exits from that entry:

1. Sell into an observed bid of at least $0.99 with one displayed contract,
   subject to the same fresh post-delay quote check, charging a taker fee.
2. Hold for the venue's actual settlement; unresolved, void, revised or missing
   settlements remain separately identified and are never presumed wins.

Neither a trade print nor a resting $0.99 ask grants a maker fill. Do not combine
the two thresholds or the two exit alternatives into one P&L, simulate unlimited
capital recycling, or multiply displayed size into an achievable profit claim.

Fees use the applicable documented venue schedule. For the owner's confirmed
Direct Kalshi account, the standard taker coefficient is `0.07 * p * (1-p)`;
the one-contract cost-plus-fee calculation rounds upward to $0.0001. Unknown
series multipliers/fee types must not silently inherit that schedule. Standard
Polymarket US non-combo taker fees use the market coefficient (normally 0.0695)
and per-fill half-even cent rounding. Charge both entry and sale fees, use no
unverified rebate, and leave an unsupported fee case unknown. This trial models
no maker fills, so a zero maker schedule does not create free exits.

## 6. Persistence, reports and operational bounds

The independent worker writes a hash-chained journal under
`DATA_DIR/weatherwatch` (`/data/weatherwatch` on Railway), seals source segments
with compression, and atomically checkpoints state and the panel. Journal raw
inputs before deriving scenarios. Replay recovers deduplication and origin but
does not replay network watches or create new current entries. Restart invalidates
old book freshness and records a gap.

Defaults: enabled, 512 MiB maximum evidence storage, 128 MiB free-disk reserve,
300-second discovery interval and 20 concurrent watches. Source evidence is not
silently deleted to make the trial look continuous: exhausted storage pauses
capture and records the reason. `WEATHERWATCH_RETENTION_DAYS=7` retains daily
report summaries (minimum four days), not permission to truncate the source chain.
The callback queue is bounded at 256 events and 4 MiB, with a 256 KiB per-event
limit. Overflow pauses capture with an explicit gap. Model-dispatch timestamps
include actual queue delay. The worker's requests, storage and shutdown are also
bounded to isolate observation work from the existing financial desks. Full
journal replay has a local benchmark of 52,570 synthetic events across 20 markets
in 3.632 seconds (about 674 KB compressed); that is not a latency guarantee for a
full 512 MiB journal or the Railway host.

Daily artifacts are `/data/weatherwatch/daily/YYYY-MM-DD.json` and `.md`.
The page has a separate **MEASURE ONLY** panel; these amounts never enter venue
cash, the town's real profit or an existing desk's stops. Every daily report must
retain:

- candidate and confirmed proxy counts; station/series/source coverage and gaps;
- valid-time-to-first-receipt median/p95, confirmation/dispatch delays and actual
  quote timing, with censored or missing samples disclosed;
- per venue and per threshold: one-time displayed size, assessed/unknown cases,
  conditional entries and capital, unresolved cases, fee-inclusive conditional
  sell/hold results, and actual settlement/CLI disagreements;
- the distinction between elapsed time and recorded coverage, and the explicit
  **unknown** achievable cents/day verdict while source or execution is unproved.

NWS CLI product discovery uses `/products/types/CLI/locations/{location}` and
the returned `/products/{uuid}`. Require the exact CLI station token in the
product, its climate date and a complete daily report; publication date is not
necessarily the climate date. An afternoon “VALID TODAY AS OF” report is partial,
not final. Check product indexes no faster than every 300 seconds and recheck
known products for revisions no faster than hourly, sharing the NWS cache/rate
budget. Missing, partial and corrected reports stay visible. CLI comparison is
separate from the actual venue settlement comparison. Zero observed contradictions
with missing CLI coverage is not “zero CLI disagreements.”

A later session copies verified daily findings into `docs/WORKLOG.md`; Railway
does not write to GitHub automatically. A three-day report cannot be produced on
deployment day. Keep collecting, then state the observed opportunities, limits
and cents-per-day uncertainty in plain words before proposing any trading work.

## 7. Evidence and release checks

Source documentation checked during implementation:

- [AWC API limits/cache products](https://aviationweather.gov/data/api/) and
  [schema](https://aviationweather.gov/data/schema/openapi.yaml).
- [NWS API guidance](https://www.weather.gov/documentation/services-web-api),
  [MADIS quality-control flags](https://madis.ncep.noaa.gov/madis_sfc_qc_notes.shtml)
  [MADIS OMO description](https://madis.ncep.noaa.gov/madis_OMO.shtml) and
  [IEM one-minute archive](https://mesonet.agron.iastate.edu/request/asos/1min.phtml).
- [MADIS public guest interface](https://madis-data.ncep.noaa.gov/public/sfcdumpguest.shtml),
  [provider selection](https://madis-data.ncep.noaa.gov/providerSelection.html),
  [time selection](https://madis-data.ncep.noaa.gov/timeSelection.html) and
  [primary versus remark temperature precision](https://madis.ncep.noaa.gov/sfc_OMO_variable_list.shtml).
- [Kalshi source hierarchy and contract terms](https://assets.kalshi.com/contract_terms/GLOBALTEMPERATURE.pdf),
  each market's retained actual rules, and
  [Kalshi fee rounding](https://docs.kalshi.com/getting_started/fee_rounding).
- [Polymarket US market WebSocket authentication](https://docs.polymarket.us/api-reference/websocket/markets.md)
  and [shared API rate limits](https://docs.polymarket.us/api-reference/rate-limits.md).

Fake-only tests cover source quality/precision, independent confirmation, correct
station/day/side, replay and clock gaps, honest quote scenarios, fees, settlement,
bounded failure and isolation from order clients. Run the full tests, mypy and
changed-file ruff before pushing. A watched-path merge restarts the live bot:
verify the exact deployed commit, observer startup and existing desk startup in
Railway logs, including `weatherwatch_status mode=MEASURE_ONLY real_orders=false`,
source/venue coverage and no tracebacks. Platform success or HTTP health alone
does not prove feed capture.
