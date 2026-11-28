# PR75 outcome and reduction-only containment

Evidence cutoff: **October 16, 2026, 4:25 PM PDT** (23:25 UTC). Native counter
cross-check: **4:27:17.661 PM PDT**. Source: `2f0bba487b4c88fa39299924b7a112e8413cb933`,
Railway deployment `7582010e-5681-41bb-964b-951e8b3c6767`, released at 1:34:33 PM PDT.
These outcomes supersede the earlier release's absence of new-policy fills. They
do not change the original release record or erase any losses.

The updated strategy is **still negative in this bounded cohort**. Eight new
traded settled windows produced seven wins totaling **+$0.1092** and one
**-$0.4218** loss: **-$0.3126 net after fees**. Two more newly settled windows had
zero fills. The inherited pre-release pair contributed **+$0.0600**, so the whole
deployment interval's settled change is **-$0.2526**. Two current-window fills
remain unsettled at the cutoff and are excluded from settled profit.

All 29 original money log rows (18 fills, 11 settlements) are retained in
[MONEY_LOGS.json](MONEY_LOGS.json). The query returned fewer than its requested
300-row limit. [analyze.py](analyze.py) checks unique identities, actual fill cost,
side quantities, actual fees, payouts, locked/directional sums, and native counter
deltas; its output is [ANALYSIS.json](ANALYSIS.json). It does not generate orders,
replacement fills, a backtest, or a fitted strategy.

## What actually failed

The window ending **3:15 PM PDT**, `KXBTC15M-26OCT161815-15`, followed this path:

| Time PDT | Recorded event |
| --- | --- |
| 3:00:17.250 | Submit Down maker intent: 1 contract at $0.49; model fair $0.540919. |
| 3:00:17.308 | Venue acknowledgment of Down order. |
| 3:00:18.718 | Actual Down fill at $0.49, no maker fee. |
| 3:00:18.890 | Reprice cancellation returns 404: already no longer resting. |
| 3:00:20.157 | Complete fill batch returned, 1.4396 seconds after venue fill. |
| 3:00:21.144 | First balancing Up maker intent at $0.49. |
| Through 3:10:57 | 39 ordinary Up hedge intents total: one at $0.49, 38 at $0.50; none filled. |
| 3:11:00.273 | Late protective Up lock intent with $0.94 limit. |
| 3:11:00.359 | Actual Up fill at $0.927 plus $0.0048 taker fee. |
| 3:15:09.403 log receipt | Official Up outcome; $1 payout minus $1.417 cost and $0.0048 fees = **-$0.4218**. |

[TARGET_ORDERS.json](TARGET_ORDERS.json) has 148 bounded rows, including 118 for
this target; the rest concern the next window. The target has 42 intents including
an earlier unfilled Up starter, the filled Down starter, 39 ordinary Up hedges and
the late lock. There are 21 reprice and 11 stale-book cancel receipts. Keeping
those bids in queue is not proved to have produced any fill. [START_TRACE.json](START_TRACE.json)
separates venue fill, batch return and local processing; provider log arrival is
not used as order-execution time.

Removing only the actual late hedge, keeping the observed official outcome and
first fill, would have lost **$0.49**, which is **$0.0682 worse**. The late hedge
reduced this actual loss. It did not originate the one-sided exposure. An earlier
profitable executable hedge is not established by these records.

Displayed depth does not establish a fill-time pair: on Kalshi's binary order book, the opposite ask is the
complement of a bid on the starter's own side. If our Down bid is `p` and the
visible Up hedge costs `q`, the bid providing that hedge is `1-q`. Requiring
`p+q+fees <= .99` places our Down bid below that better Down bid. Under normal
price priority, the better bid can be consumed or withdrawn before our lower bid
fills. Thus the displayed hedge depth is ahead of us in the same queue, not a
reserved second leg. See `parse_books` in `src/nightcrawler/speeddesk_kalshi.py`
at the released source. An entry-time depth test cannot turn this into an atomic
pair or guarantee any profit. The current evidence does not establish that the
controller violated its PR75 admission rule.

## Coverage and money limits

Native cumulative settled P&L is **-$27.6941**, versus **-$27.4415** at the prior
release check. Locked total is **+$8.5897323**, directional **-$36.2838323**. The
new negative pair is classified as locked after both sides fill; that label does
not mean profitable. Current UTC-day native P&L and cash remain separate from this
source-specific cohort. Cash **$47.0698** is not profit and is affected by unsettled
positions/netting. The cash decrease is $0.2901: the new settled cohort's
-$0.3126 plus the current pair's $0.0225 netted margin matches that change. The
inherited $0.06 pair margin was already in cash before release. The current pair
still has $0.9775 recorded gross cost including fees and remains excluded from
official-settlement P&L. This arithmetic is not a complete account cash-flow audit.

The 18 new fill count, 11 settlement count, **$0.0731** total new fees (including
unsettled fills), and **-$0.2526** settled change agree with native counter deltas.
This supports the bounded cohort, not whole-day or lifetime ledger certification.
The standalone recorder's raw volume has not been inspected as part of this task.

All three 1/5/30-second post-fill markouts for the initial losing fill are invalid:
`book_stale`, `observation_late`, `book_stale` respectively. These are missing
execution evidence, not zero losses or valid exit prices. The initial broad target
query saturated at 501 returned rows despite a 500 limit; it is retained solely
as incomplete diagnostic material. Financial conclusions use the separate
unsaturated exact money and order queries. Full minute-aligned account scans can
temporarily produce stale status; three sampled stale reports do not establish
continuous unavailability. Practice is not comparable with the new policy.

## Correction and acceptance

The evidence supports **containment**, not a claim that a profitable replacement
has been found. Normal maker and taker orders must only reduce confirmed unmatched
inventory; a balanced or empty position must not start a new leg. Check before
reservation and again after asynchronous waits at transport. Cancel outstanding
nonbalancing remainders, retaining their reservation until venue reconciliation.
Preserve existing protective hedges, locks, account reconciliation and settlement.

No automatic resume or expiry; no new runtime switch. Existing caps **$20/window,
$40 open, $12/day loss, $10 total loss, clip 5**, consumed controls, previous
losses and ordinary safety checks remain. No Railway variables, funding transfer,
new desk, direct test order, recorder change or Polymarket strategy change.

Required before claiming release: meaningful production-default containment tests,
historical mechanism regressions explicitly labeled, full required tests/mypy/
changed-file Ruff, independent exact-source review, safe-minute merge, exact
Railway deployment and native policy/counter/cancel evidence. Existing exposure
can still lose before it settles. Absence of new orders must not be called profit.

**At this report's initial preparation, containment is not deployed yet.** The
release receipt will record the actual final state separately. The next economic
step is a fresh, frozen evaluation using fill-time execution evidence, including
missed fills, fees and losing tails. No threshold tuning to this observed loss,
sealed Family A TEST consumption or risk increase is part of this correction.
