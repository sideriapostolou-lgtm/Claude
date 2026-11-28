# Historical first-fill intent evidence: October16 UTC

All **55/55** first executed venue orders in the existing October16 UTC
settled-traded cohort now join to an original standalone pre-fill decision
intent and an accepted-order receipt with the exact venue order ID. This replaces
the earlier selected 5/55 intent coverage. It is an exploratory development
diagnostic, conditional on an actual first fill. It is not a preregistered test,
a backtest, a profitable entry policy, or a sample of all eligible opportunities.

The logged decision fairs overpredicted these first-side outcomes: equal weight
per market window gives **−8.8940 percentage points** for official outcome minus
decision fair; weighting by the actual 165.56 filled contracts gives **−13.6189
percentage points**. Applying each logged fair to its actual partial-fill sizes,
prices and fees gives model-implied cashflow **+$6.20472977**, versus actual first
order cashflow **−$16.3428**: a **−$22.54752977** residual. This conditions on actual
fills and quantities; it does not establish their unconditional expected value.

| Descriptive complete traded-settlement cohort | Value |
|---|---:|
| First orders with exact pre-fill intent / accepted venue ID | 55/55 / 55/55 |
| First-order partial-fill receipts / distinct orders | 58 / 55 |
| Actual first-order filled quantity | 165.56 contracts |
| First-side official wins / losses | 24 / 31 |
| Equal-window official winning rate | 43.6364% |
| Equal-window logged decision fair | 52.5304% |
| Equal-window chosen maker limit | 48.7455c |
| Equal-window quoted fair minus maker limit | +3.7849c |
| Equal-window actual first-order cashflow per contract | −5.1091c |
| Official outcome minus decision fair, equal-window | −8.8940pp |
| Official outcome minus decision fair, actual-quantity-weighted | −13.6189pp |
| Model-implied cashflow at actual fills and actual fees | +$6.20472977 |
| Actual first-order cashflow | −$16.3428 |
| All other actual-fill cashflow | +$8.1730 |
| Original actual net, retained | **−$8.1698** |

All first-order receipts are maker fills, with actual fees 0 and fill prices equal
to their intended limits. Three first orders have multiple partial-fill receipts;
all their partials remain attributed to the original first venue order. The
positive later-fill term is cashflow attribution of fixed receipts, not an
independently executable strategy.

There are 60 original settlements: 55 traded and 5 empty. The 5 empty windows remain
listed in `ENTRY_EVIDENCE.json` and have no first fill to calibrate. The original 149
day fill receipts also contain the two-fill next-day carry
`KXBTC15M-26OCT162000-00`, which settles +$0.0127 on October 17 UTC. The carry stays
excluded from the October16 settlement-day calibration/net. The earlier completed
PR75 cohort remains 11 traded windows: ten wins +$0.1544 and one −$0.4218, net −$0.2674
including that next-day carry. No original loss is removed.

## Coverage and provenance

The target list came from every first-client ID in the existing published 55-row
actual-fill decomposition, without selection by outcome. Seven bounded Railway
service-scoped log requests were made: an initial exact-ID probe followed by six
batches. Each request omits deploymentId, names the existing bot service and
production environment, uses limit 500, and includes explicit UTC start/end dates.
The first begins October 15 at 23:59 UTC, one minute before the earliest market open;
batches end 10 minutes after their last first fill to allow deferred publication.

| Request | Original returned provider rows | Limit | Direct order rows |
|---|---:|---:|---:|
| probe | 2 | 500 | 2 |
| batch01 | 25 | 500 | 20 |
| batch02 | 74 | 500 | 20 |
| batch03 | 78 | 500 | 20 |
| batch04 | 25 | 500 | 20 |
| batch05 | 26 | 500 | 20 |
| batch06 | 29 | 500 | 10 |
| Total | 259 | — | 112 |

All requests are unsaturated. Exactly 2 identical probe events deduplicate,
leaving 110 unique direct order events: 55 ordinary `state="durable intent"` and 55
`state="accepted; waiting for real fills"`. Every intent matches client ID,
window and side; every acceptance matches the actual venue order ID. No conflicts,
missing target IDs or payload clocks after the first fill were observed.

The Railway filter also matches event/ID strings inside long account status
messages. The 147 excluded returned rows comprise 78 top-level status messages and 69
fragments/other unparseable top-level messages. They never supply a join or fair.
`captures/` contains only complete original standalone order rows, original query
metadata/counts, original-envelope and response hashes, and per-selected-row hashes
and original row indices. It omits duplicated MCP text content and broad status
payloads. Full original envelopes are privately preserved under
`/workspace/entry-evidence-oct19/raw/`; the selection boundary is explicit in every
minimized capture. These selected files are not a complete provider archive.
Independent original-to-selection verification requires the private originals.

`ENTRY_EVIDENCE.csv` is the complete 55-row joined table. JSON retains original
payloads, timing metrics, source indices, accepted venue IDs, all original
cashflows, coverage proof and SHA-256 source manifest. Unsaturated provider receipts
cover all requested IDs; they do not certify durable-volume or journal completeness.

## Clock and interpretation limits

The source `_record` records local payload time and queues the event; checkpoint
publication occurs later. Nine intent provider timestamps follow the first fill,
although all 55 original intent payload clocks precede it. The analyzer uses the
payload clock and retains the provider clock. Payload local and venue fill clocks
are different clock domains; offset/uncertainty prevents an exact latency claim.
The event's `timing` clocks are preserved independently.

All 55 intents retain both BTC age metrics with `status="ok"`. These are
exploratory completeness summaries; no age threshold or causal relationship was
tested. The intent-to-first-fill interval approximates quote age, includes clock
uncertainty, and is not a pure venue resting-duration measurement.

| Logged metric | Minimum | Median | Maximum |
|---|---:|---:|---:|
| Intent-to-first-fill interval (seconds) | 0.1217 | 2.5117 | 18.7815 |
| BTC exchange-to-decision age (milliseconds) | 9.0275 | 196.2685 | 2170.5779 |
| BTC receipt-to-decision age (milliseconds) | 1.7617 | 120.4002 | 2151.5113 |

The metrics source labels exchange age as accepted Coinbase input age subject to
exchange/local clock uncertainty; receipt age begins at the strategy callback,
not pure computation or proven trigger reaction.

The recovered probability is **decision fair before the fill**, not fill-time fair.
Without fill-time fair, this evidence cannot distinguish unconditional model
error from a fair becoming stale or fills arriving under adverse selection.
Coinbase exchange/receipt-to-decision age metrics survive as logged, but complete
historical source snapshots, both-side book ages, dispatch-depth/queue survival and
fill-time fair are unavailable. These observations cannot establish a staleness or
adverse-selection cause. No late row, status snapshot or lock fair is imputed.

Forty-five older intents omit `completion`; those fields remain unknown/null.
Ten later intents explicitly sayfalse. No per-row historical model version or
deployment identity is proven. The connector's service metadata identifies the
latest deployment, which must not be assigned to old rows; a current source hash
corroborates event semantics only. The day already mixes releases, pauses and caps.

For a secondary descriptive score, equal-window decision-fair Brier is 0.23284971;
the chosen maker-limit **own bid proxy** scores 0.22724545 (difference+0.00560426).
The own bid proxy is not an independent venue probability forecast or market
midpoint. This comparison has no significance test and establishes no superiority
or executable alternative.

No strata or thresholds were searched; no confidence interval or profit proof is
claimed. Nonfills, canceled decisions and all eligible opportunities are outside
this first-filled cohort. A prospective policy still needs its own frozen protocol,
complete opportunity accounting and independent future validation. PR76 containment
and all losses, stops, budgets and settings remain in force. No code, configuration,
production state, money limit, order endpoint or sealed recorder TEST was changed
or accessed by this evidence task. Runtime/storage recovery remains separate.

## Reproduction

From the repository root:

```bash
python research/kalshi_entry_calibration_2026-10-19/analyze_entry_evidence.py --output-dir /tmp/entry-evidence-review
```

The portable analyzer reads only the minimized captures, target request plan and
the existing published `LOSS_MECHANISM.json` and `DAY_MONEY_LOGS.json` under the
repository (override with `--repo` when needed). It performs 1,554 assertions and writes JSON/CSV to the chosen
output directory. Original full-archive extraction/analyzer remains private. Source
hashes cover all minimized inputs, original money/decomposition sources, the
analyzer and the currently inspected event source. The public selection hashes
must be compared with private originals for independent provenance verification.
