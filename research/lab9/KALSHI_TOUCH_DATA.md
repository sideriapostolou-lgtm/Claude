# Kalshi monthly crypto touch data and rules audit

2026-10-12. Public, unauthenticated GETs only. This is an acquisition and contract audit,
not a backtest return or a claim that we could have received the recorded trades.

## Coverage verdict

**The four requested monthly series do not expose 12 completed months.** Exhausting both
live and historical market cursors, and separately exhausting their event cursors, finds
January–October 2026 listings. January–September supplies at most nine completed calendar
months; the first January contracts started partway through the month. No earlier event in
these named series was returned. This does not prove that differently named predecessor
products never existed. Annual markets are inventoried separately and do not replace
missing monthly observations. That separate census contains 32 BTC maximum, 28 BTC minimum
and 25 ETH maximum annual markets, including 2024 predecessor ticker names; no annual
returns or historical-rule equivalence are asserted here.

| Series | Unique markets | Finalized at capture | Still active | First creation | Event months |
| --- | ---: | ---: | ---: | --- | --- |
| KXBTCMAXMON | 100 | 93 | 7 | 2026-01-06 | Jan–Oct |
| KXBTCMINMON | 93 | 85 | 8 | 2026-01-15 | Jan–Oct |
| KXETHMAXMON | 80 | 72 | 8 | 2026-01-06 | Jan–Oct |
| KXETHMINMON | 66 | 59 | 7 | 2026-01-15 | Jan–Feb, Apr–Oct |

There are **339 unique monthly markets, 309 finalized and 30 active**. The finalized count
includes early touches in unfinished October ladders: it is not the number of markets in
completed-month evaluation. The complete census retains zero-volume markets, all returned
statuses, already-touched losers and all raw market versions. The only returned statuses
were `finalized` and `active`; an absent void/cancellation is not an assumed zero payout.
Four census markets have zero recorded volume. Inventory capture began
**2026-10-12 22:26:45.209831 UTC**, with fixed print cutoff **1791844005**.

The archive's reported `market_settled_ts` and `trades_created_ts` cutoff was
**2026-08-12T00:00:00Z**. Current `/markets` alone misses earlier data. The collector reads
`/markets` and `/historical/markets`, then `/markets/trades` and `/historical/trades` for
every finalized market, with a frozen maximum print timestamp. Live/archive market overlap
is retained in the raw census; trade IDs are deduplicated only when their entire records
agree. Conflicting duplicate trade records halt collection. An empty cursor, not a short
page or guessed page count, establishes exhaustion.

Collection completed at **2026-10-12 22:37:33 UTC**: all **309 finalized-market tapes**,
**337,889 unique prints**, with **9,168 identical observations** deduplicated across the
storage tiers. The 952 logged collection requests all returned HTTP 200; no retry or 429
occurred. A final uncached cutoff read matched the initial cutoff. No return was computed
to choose a sample or stop acquisition. Reserved TEST months remain unscored by this
acquisition module.

| Series | Finalized tapes | Unique prints | First returned execution | Last returned execution |
| --- | ---: | ---: | --- | --- |
| BTC maximum monthly | 93 | 196,737 | Jan 6, 22:12:22 UTC | Oct 1, 18:32:36 UTC |
| BTC minimum monthly | 85 | 93,508 | Jan 15, 06:35:22 UTC | Oct 1, 03:56:09 UTC |
| ETH maximum monthly | 72 | 34,937 | Jan 6, 22:11:43 UTC | Oct 1, 02:57:29 UTC |
| ETH minimum monthly | 59 | 12,707 | Jan 15, 17:51:12 UTC | Oct 8, 15:19:49 UTC |

Quality checks found no returned block-trade flags set, missing block/direction fields,
nonpositive sizes, or YES/NO price-complement violations. Three finalized tapes are empty;
they are retained, not dropped. **Three June tapes do not reconcile to published market
volume**, despite both trade cursors being exhausted:

| Ticker | Sum of unique print contracts | Published `volume_fp` | Unexplained difference |
| --- | ---: | ---: | ---: |
| `KXBTCMAXMON-BTC-26JUN30-8500000` | 86,495.85 | 90,093.45 | 3,597.60 |
| `KXBTCMINMON-BTC-26JUN30-5750000` | 912,076.17 | 912,116.17 | 40.00 |
| `KXETHMAXMON-ETH-26JUN30-225000` | 89,922.45 | 90,044.53 | 122.08 |

Thus `complete=true` means the requested API cursors finished; it does **not** certify an
independently reconciled economic tape. The cause of these volume differences is unknown.
They must remain visible in any downstream coverage claim. Raw data-quality calculations
are saved as `quality_summary.json`; this audit did not compute strategy returns. Four
additional public audit requests under `volume-audit/` confirmed the same fresh market
volumes and zero block-only prints for each discrepant ticker, so neither a refreshed
metadata value nor a block-only lookup reconciled them. Those four audit requests are
separate from the 952 collection requests and do not change the frozen manifest.

## Contract definitions: a material text inconsistency

Official sources fetched:

* [Series metadata](https://docs.kalshi.com/api-reference/market/get-series): every series
  names CF Benchmarks, `CRYPTOMINMAX` contract terms and the same certification document.
* [Operative contract PDF](https://assets.kalshi.com/contract_terms/CRYPTOMINMAX.pdf).
* [Product certification, July 18, 2025](https://assets.kalshi.com/regulatory/product-certifications/CRYPTOMINMAX.pdf),
  which also includes the per-minute definition below.
* Each market's unmodified `rules_primary`, `rules_secondary`, `strike_type`, strike values,
  scheduled dates, actual close, settlement timestamp, result and settlement-value fields
  are saved in `inventory.json` and the raw response pages.

The PDF defines the underlying as the specified CF cryptocurrency index. Its exact key
passage says the price is a simple average of the cryptocurrency values **“for each minute”**,
**“ignoring the top 20% and the bottom 20% of values for each minute.”** BTC market metadata
identifies **CF BRTI**; ETH identifies **CF ETHUSD_RTI**. Ordinary Coinbase highs/lows or
individual CF spikes are not this settlement measurement. The PDF does not provide an
unrestricted historical sample feed or pin an intraminute sampling cadence in that passage.

The comparative terms are explicit: **above is strictly greater; below is strictly less**.
Equality alone does not trigger these above/below contracts. Measurement starts at issuance
and ends at the contract's stated calendar deadline. If required data is unavailable or
incomplete at expiration, the PDF says affected strikes resolve NO. Revisions after
expiration are not used. A qualifying event can move expiration earlier; market-outcome
review contingencies remain in the rules.

The API prose is not consistently equivalent to that PDF:

1. Seven January BTC maximum markets and seven January ETH maximum markets describe
   trimming minute averages over the **entire period into a final average**, rather than
   checking each trimmed minute.
2. Later secondary text describes trimming a **cumulative dataset** at each minute and
   resolving YES if any such trimmed mean crosses the threshold. That is also not the
   PDF's explicit within-each-minute wording.
3. **59 BTC minimum and 44 ETH minimum market records say “above the threshold” in their
   secondary text while their primary condition and strike direction say below.** The
   remaining current-tier minimum records use “below.”

These are saved text inconsistencies, not evidence that we know when the venue changed its
legal rule. Current/historical API objects are not an as-of version history. Do not silently
repair them, infer a switch date from archive placement, or use final outcomes to pick the
interpretation that produces a profitable result. Before a rules-faithful replay is
qualified, the operative version and the CF observations must establish prior touches.
See `TOUCH_SPOT_DATA.md` for the separate index-history availability audit.

For days remaining, use the scheduled observation deadline (`occurrence_datetime` when
present, otherwise verify `expected_expiration_time` against the primary rule and event
deadline). **Do not use an early `close_time` or shortened actual expiration:** that would
put the future touch into the signal. Calendar end is 11:59 PM America/New_York in these
markets, so its UTC offset changes with daylight saving time. Listing/issuance may be later
than the beginning of that calendar month, and later-added strikes have their own issue
times.

## Fees: current evidence is not a complete historical rounding archive

The [official fee schedule PDF](https://kalshi.com/docs/kalshi-fee-schedule.pdf) fetched in
this session is marked **last updated and effective July 7, 2026**. Its general taker model
is `M × 0.07 × C × P × (1−P)`. Maker charges use `M × 0.0175 × C × P × (1−P)` only for
products assigned maker fees; the default maker multiplier is zero. No settlement fee.

All four monthly series currently return `fee_type="quadratic"`, `fee_multiplier=1`.
`/series/fee_changes?show_historical=true` returns no changes for each, and the event-level
fee-change cursors return no overrides for all 39 monthly events. This supports the current
ordinary quadratic taker/no-maker schedule. It does not prove the fee-change endpoint is a
complete record of every older platform-wide rounding rule.

[Official rounding documentation](https://docs.kalshi.com/getting_started/fee_rounding)
specifies direct-member balances at **$0.0001** precision and non-direct balances at $0.01.
Model trade fees first round up to $0.000001; an additional balance-alignment charge and
per-order rounding accumulator/rebate determine the net fee. The owner confirmed a direct
Kalshi account. Integer contracts at cent prices with zero maker model fee create no
balance-alignment charge. Historical taker replay must establish the contemporaneous fee
and rounding rule or explicitly label a conservative assumption/sensitivity. The current
July schedule cannot silently be backdated over January–June.

## What prints do and do not establish

Raw prints retain `trade_id`, `ticker`, exact `created_time`, decimal strings
`yes_price_dollars`, `no_price_dollars`, `count_fp`, `taker_outcome_side`,
`taker_book_side`, legacy `taker_side`, `is_block_trade` and any future unknown fields.
The canonical taker outcome describes direction, not whether the source participant
submitted an opening buy versus an economically equivalent sell. Do not invent an action,
maker identity or account inventory from it.

A print proves another trade occurred. It is not historical BBO/depth and does not reveal
our hypothetical queue position, cancellation, accepted resting order or available maker
fill. Block/RFQ prints are identified separately and cannot be treated as displayed-book
liquidity. The standard documented historical API exposes markets, trades and candles,
not historical order-book snapshots/deltas. Current books cannot reconstruct old queues.
Positive print-conditioned outcomes therefore cannot satisfy an executable maker backtest
gate by themselves.

## Reproduction and provenance

```bash
python research/lab9/kalshi_touch_data.py --output /tmp/lab9-kalshi-touch --workers 4
```

The default is one worker. Up to four workers share the same file-locked limiter with the
weather collector, spacing request starts at least 0.55 seconds apart in aggregate.
HTTP 429/5xx retries are bounded, honor numeric/HTTP-date `Retry-After`, and stop resumably
instead of retrying early when the server requests a wait longer than 60 seconds. No
redirects, private endpoints, authentication headers, key reads or order methods exist in
this collector.

Raw evidence lives outside git at `/tmp/lab9-kalshi-touch/`:

* `inventory.json`: all monthly/annual metadata, series fees, event fee history and fixed
  collection cutoff. `inventory.partial.json` is a progress checkpoint, not final evidence.
* `pages/<request-sha256>.json`: exact response text, its checksum and request identity.
  Cache reuse verifies the stored response checksum and identity.
* `requests.jsonl`: attempt, route, parameters, status/error and clocks.
* `trades/<ticker>.jsonl`: unique full trade records, chronologically ordered.
* `manifest.json`: per-ticker page counts, tape checksums and earliest/latest exchange
  timestamps; only `complete=true` establishes that all selected cursors finished. A final
  uncached archive-cutoff read flags whether the tier boundary changed during the pull;
  neither the public scan nor its metadata is an atomic as-of exchange snapshot.
* `docs/`: downloaded documentation Markdown, fee/rule PDFs and text extraction.

The initial single-worker acquisition version called its **request-start** timestamp
`captured_at` (and journal `at`); it is not a response receipt time. That was corrected
during collection: new pages separately record `requested_at` before HTTP and `received_at`
after HTTP, with `captured_at=received_at`. Old cached pages retain their original evidence
and meaning; no source exchange timestamps were altered. This clock correction changes no
historical trade prices or times, but the legacy capture fields must not be used as precise
data-arrival latency. Raw `/tmp` evidence is session-local and must be copied/re-fetched if
the workspace is replaced.

Validation: public-transport fakes pin route restrictions, cursor exhaustion and failures,
exact decimal preservation, duplicate identity conflicts, retry delays, redirect refusal,
cache integrity and source/receipt clock separation. No live account request or simulated
trade is part of these tests.

Stable source-document checksums (SHA-256):

| File | SHA-256 |
| --- | --- |
| `inventory.json` | `be00843ead22f0039bd7bee8ade289e60b4674415ede815208607af135a07a70` |
| `manifest.json` | `1f29b41b4372be5f1a2a1426982e0e1e4af9995fb763f018e42f29b3fa970d28` |
| `docs/terms.pdf` | `fdad29833d5bf0d377dce7936c16cd33a24907aa175f54c3def171f739419159` |
| `docs/certification.pdf` | `592db54397eba4ffc66c69727985917ef48747f6afdce59991220d67cf4c1423` |
| `docs/fees.pdf` | `c326a69f596a11e8f8be2620402d39a8d4823920c21cc97c93a114d862699601` |
