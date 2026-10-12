# Skipwatch prospective plan: timing amendment before analysis

## 2026-10-12 amendment: automatic strategy inference paused

The official [Data API v2 OpenAPI](https://data-api.polymarket.com/v2/openapi.json)
describes `Trade.timestamp` as **"Block
timestamp of the fill, epoch seconds"** and `transaction_hash` as **"Hash of the
settling transaction."** A block timestamp is not an execution timestamp.
The features immediately before that block second may therefore occur AFTER
the actual trade. Local receipt causality alone does not repair this error.

This amendment is registered before any training, validation or test metric was
computed on the prospective production tape. A separate public timing diagnostic
found settling-transaction-linked CLOB events earlier than wallet block times;
that limited diagnostic is not strategy evidence and supplies no new lag cutoff.

Production now reports `awaiting_verified_execution_time` and keeps recording.
It refreshes the runtime RULES.md with this pending warning, without reading
previous strategy artifacts. It neither scans the archive for fitting nor
generates an execution-rule verdict at 48 or 72 hours. The original observation origin and raw tape remain
unchanged; the original split timestamps are historical planned boundaries,
not promised verdict dates. Existing artifacts are preserved, never silently
retuned or overwritten.

Before causal fitting can resume, a separate preregistered protocol must establish
execution-time semantics, reliable matching and clock/lag uncertainty bounds,
and conservative treatment of unmatched/ambiguous fills and negative examples.
Same transaction alone does not identify a unique fill. Complementary outcomes,
aggregated prints and maker fragments require explicit validation. No matching
rule or timing tolerance will be selected to improve a strategy score.

The Python research machinery is retained behind the explicitly named
`block_publication_research=True` argument, with no production CLI bypass.
Such outputs are **noncausal block-publication associations only**: their
features can follow execution, and their scores cannot identify triggers,
constitute a trading rule or enable money. A new causal protocol must be
registered before any execution-label model selection or held-out evaluation.

## Original version 1 proposal, retained for audit

The causal execution interpretation of the target below is withdrawn by the
amendment above. The original clock is preserved; this text is not permission
to run automatic strategy inference on block-time labels.

Registered before prospective observations or returns are analyzed. The older
2,000-fill sample in READING.md motivates hypotheses only; it is never training
or test data. No return, profitability or exact private strategy is established.

## Question and limits

Can a small, fixed family of rules predict which side the public wallet buys in
the next complete timestamp second, better than simple baselines, on a future
day? Public fills reveal executions, not order placement, cancellation, queue
position, private signals or execution milliseconds. Maker/taker identity stays
unknown unless separately supported; price/size/time matches are inferred.
Coinbase price, opening and fair probability are explanatory proxies. These
international five-minute markets settle on Chainlink's specified 60-second
TWAP, not the Coinbase proxy. We do not trade on this international venue.
Research volatility is the root mean square of at least 300 actually observed
adjacent one-second log returns from the trailing hour; missing seconds never
become invented zero returns. This distinct research feature does not alter the
live desk's 3,000-return warm-up. Missing fair value remains missing coverage.
The research opening proxy is the most recent actual Coinbase tick at or before
the window start, no more than three seconds old and already received by that
start. Its age and method are recorded. It is not a backfilled or true oracle
opening, and does not change any financial estimator.

## Prospective clock and coverage

The durable watcher's original `session_started_at` is the immutable origin.
TRAIN is its first 48 elapsed hours: the first 36 hours fit quantities and
baselines, and hours 36–48 are chronological validation. TEST is hours 48–72,
one look after its end. These are complete elapsed 24-hour periods, not partial
UTC calendar dates. UTC filenames do not determine split membership.

One scheduled opportunity per window/side/second records only information
already received. Its target is the next complete public timestamp second:
`[floor(feature_at)+1, floor(feature_at)+2)`. A BUY with integer venue timestamp
inside that second is the target. The resulting lead is between zero and one
second; this does not locate the wallet's private decision or execution in
milliseconds. Repeated same-second snapshots use the first observation.

A row needs finite causal fair/quotes/depth/moves/inventory, fresh Bitcoin and
book, and wallet/trade coverage. Wallet coverage must remain established across
the target and a fixed 30-second reporting grace. The target plus grace must
finish before its split boundary. Missing seconds, discovery outages, delayed
fills beyond grace, ambiguous timestamp precision and corrupt/truncated JSONL
are explicit exclusions or blockers, never quiet periods or zero fills. A
negative means no BUY in the covered public record after grace, not proof that
no private order was submitted. Every split reports raw/eligible opportunities,
missing coverage and positive/negative counts. No resampling fills into fake
market observations is permitted.

## Fixed candidate grid: 24, no expansion after seeing data

Cross three proxy edges (0, 0.02, 0.04 dollars), two remaining-time cutoffs
(30, 60 seconds), and four fixed templates:

1. Fair probability minus best ask exceeds the edge.
2. Fair probability minus best bid exceeds the edge.
3. Template 2, and the side reduces the observed share imbalance or the observed
   absolute share imbalance is at most 25%.
4. Template 2, at least 25 shares displayed at the best bid, and the signed
   five-second Coinbase move points toward this side.

The bid templates are hypotheses about cheap quotes, not observations of the
wallet's resting bids. Report fixed negative/zero/positive buckets for moves at
1, 5 and 30 seconds, depth below/above 25, side, time and prior imbalance.
These descriptive buckets are not additional model selection searches.

Fit-period median positive-bin BUY quantity supplies the fixed sizing baseline.
Report held-out sizing absolute error, observed per-fill and per-bin sizes,
predicted versus observed quiet intervals, observed share imbalance, and both
side coverage. Do not treat fills as submitted order size.

## Selection and baselines

Rank candidates by validation F1, then precision, then fewer predicted buys,
then stable candidate identifier. Baselines are never-buy, always-buy, and a
deterministic hash prediction at the fit-period BUY prevalence. Report TP/FP/FN/TN,
precision, recall, F1 and prediction rate, including all covered negatives.
Undefined precision/recall stays null. A candidate is only provisionally useful
if validation precision and F1 both exceed always-buy and hash baselines.

Require at least 90% wallet-covered seconds in each split, at least 2,000/500/500
eligible fit/validation/test opportunities, at least 50/20/20 positive bins, and
at least 30/20/20 distinct windows respectively. Below this, report insufficient
evidence. If no rule beats baselines, report NO PREDICTIVE EDGE. Thresholds and
grid are fixed before analysis; no best-of-new-grids search after failure.
Also require at least 80% eligible feature coverage against the two side-seconds
per second in the continuous BTC five-minute universe, after the fixed boundary
grace. Discovery failures, absent openings and missing quotes therefore cannot
silently select a convenient subset. TRAIN that fails these gates leaves TEST
unread rather than spending the holdout on an unsupported rule.

## Freeze, one look and fees

At 48 hours the offline worker writes an immutable training artifact with the
protocol hash, input digest, chosen rule, baseline prevalence, sizing estimate,
coverage and validation metrics before any TEST evaluation. An overdue worker
still filters strictly to records observed before hour 48 and records that the
freeze was late. TEST is then evaluated once after hour 72; a saved test artifact
is returned unchanged on later runs. Protocol/input mismatches fail closed.
Integrity/format failures leave an immutable `blocked.json` marker, so an
unattended process does not repeatedly scan a broken multi-day archive. Review
the underlying evidence before any manual retry; do not retune on a failed
holdout. Temporary filesystem failures request at least one hour before retry.

This is fill prediction, not a tradable backtest. Public wallet fills do not
give our achievable queue position, private fees, maker rebates, capital or
latency. Therefore net returns and profitability remain unavailable. Report
known fee coverage separately; proxy gross quote edges must never be described
as fee-adjusted trading profits. A later tradable experiment needs a separate
preregistered plan, proven venue fees, honest fill simulation and fresh holdout.

## Destination and decisions

RULES.md is pending until actual prospective evidence exists. A future report
may suggest hypotheses for the existing Kalshi fifteen-minute desk; converting
five-minute seconds to time fractions, changing fair-value opening/settlement
sources, fees, liquidity and queue behavior is untested transfer, not validation.
Neither this fitter nor its runtime hook can import an order client, alter money
settings, promote a rule or enable live trading. Existing $2/window, $4 open,
$3/day and $5 total risk limits remain in force.
