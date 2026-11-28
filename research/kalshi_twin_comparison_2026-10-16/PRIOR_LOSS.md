# Prior losing window: actual receipts and bounded conclusions

Target `KXBTC15M-26OCT152245-45`: October15,2026 **7:30–7:45PM PDT**, equivalent October16 **02:30–02:45UTC**. App `0520f7468174d6a37f0ee7dfe64284b1a6921439`, deployment `d32c256b-618d-4927-b44a-f182d569977b`; pre-PR68 trading rules. This is a selected, already observed historical loss, not a new heldout test.

**Confirmed loss: $5 payout − $6.23 cost − $0 fees = −$1.23.** Three actual maker-fill IDs join three exact client/order IDs and match the supplied authoritative bot-settlement quantities. The first two fills completed5Up/5Down pairs for a then-locked+$0.30. A newly submitted Down3 order later filled, leaving5Up/8Down. Up officially won; the extra Down exposure lost.

Only supplied native files were read. No production/network query, source/test change, new strategy, threshold fitting, sealed TEST or counterfactual fill simulation occurred. The separate declared03:00–03:15UTC/tail03:17 future capture/source freeze is untouched. Exact original hashes,23intent joins, raw target settlement and Decimal arithmetic are preserved in PRIOR_LOSS_REVIEW.json.

## Actual fills and exposure sequence

The time column uses **venue execution time** from each fill payload, not its later reconciliation/log publication time. ID suffixes are abbreviated here; the JSON retains full exact IDs.

| Venue execution UTC (PDT is seven hours earlier) | Client suffix / order suffix | Actual fill | Cost | Inventory afterward |
|---|---|---|---:|---|
|02:30:13.721327|c3d1aac8 / c5cd9970|Down5@49c|$2.45|Up0/Down5|
|02:30:39.717268|a6f5f258 / 52a2b546|Up5@45c|$2.25|Up5/Down5, cost$4.70, five complete pairs|
|02:31:18.834001|6c31e9a5 / 9b93da86|Down3@51c|$1.53|Up5/Down8, cost$6.23, three unmatched Down|

All three receipts explicitly say `is_taker=false` and fee0. The fourth supplied fill belongs to the next ticker and is excluded. The68order rows contain45target rows:23durable intents,22acknowledgements and one unacknowledged target intent subsequently given a definite venue400refusal. The23target intents comprise17Up/6Down. Acknowledgement is not a fill; the many unfilled Up requests cannot be counted as hedges.

Final Up average cost is$2.25/5=$0.45; Down average is$3.98/8=$0.4975. The venue-style average-cost decomposition is:

- Matched component: `5 × (1 − .45 − .4975) = +.2625`.
- Directional component: `−1.23 − .2625 = −1.4925`, also the average cost of three unmatched Down contracts.

The matched component differs from the initial+$0.30 because the later51cDown fill changes the average cost allocated across all8Down contracts. The decomposition does not mean a separate directional debit was charged. The producer's trailing floating-point artifacts agree with exact Decimal results within$1e−12. Settlement reports$5paired credit and$0additional net payout: do not add the paired credit again to the$5total payout.

## The third order was submitted after the pair was complete

The exact third order is client `nc-speed-c3deb3c77c06488e834f2c2f6c31e9a5`, venue order `01a1428c-89c8-744b-85d4-fe9b9b93da86`.

| Named clock | UTC value |
|---|---|
|First completed-pair fill, venue execution|02:30:39.717268|
|Native timestamp of that Up5 fill log|02:30:40.815721742|
|Third Down order decision metric clock|02:31:09.560570|
|Third Down durable-intent receipt clock|02:31:09.560675|
|Third Down accepted-order local receipt clock|02:31:09.6542997|
|Third Down fill, venue execution|02:31:18.834001|

The third decision is29.843302s after the first-pair venue execution; its intent receipt is29.843407s after and its ack receipt29.9370317s after. Those comparisons cross local/venue clock domains and are sequencing evidence, not exact execution-latency estimates. The two venue executions are39.116733s apart. The native logging timestamp is not the old missing exact fill-reconciliation callback clock. Nevertheless, the additional Down intent was newly created long after the pair's fill had been logged; it was **not an already-resting order left over from before balance**.

At02:31:09.1364071 decision time the bot had also requested Up3@42c, client suffix`1c820994`, acknowledged locally02:31:09.2315314 as venue order`01a1428c-89c8-7c22-bbac-be77b6ac9a34`. The Down3 decision followed that ack by about329ms. The supplied files lack that Up order's complete cancel/expiration lifecycle and source-time book/queue. Therefore it is only a recently acknowledged Up bid, **not a certified still-resting hedge at the Down decision or fill**. Earlier Down3@54c,57c,61c requests also occurred after the first pair. None may be treated as a fill.

A proposal to **stop submitting fresh directional exposure after reaching positive fully paired inventory** would concern new decisions such as this later Down3. It is distinct from cancelling orders already resting at the balance event, and distinct again from cancellation acknowledgement/fill races. This example motivates measuring that distinction prospectively; it does not establish a generally profitable rule or authorize implementation. It also does not prove that cancelling some earlier bid would have prevented every later loss.

## What the caps and rejections actually establish

The source deliberately allows new inventory within its imbalance/pair-cost/budget constraints after an initial pair. It is not an invariant that every later purchase strictly balances existing contracts. See immutable baseline [inventory guard](https://github.com/sideriapostolou-lgtm/Claude/blob/ef1f3d38a49332bb19c69a8b1770abc56d83eb56/src/nightcrawler/speeddesk_live_model.py#L549) and [ordinary-buy checks](https://github.com/sideriapostolou-lgtm/Claude/blob/ef1f3d38a49332bb19c69a8b1770abc56d83eb56/src/nightcrawler/speeddesk_live_model.py#L623). Pending legs are checked as independently fillable, not treated as inventory already bought. From a5/5pair, one independently filled additional3Down produces3/13=23.0769%quantity imbalance, below the25%limit. That bounded risk is permitted; the later losing outcome does not itself prove a guard breach.

The supplied native reject file proves **one target venue rejection**: Down3@53c, client`nc-speed-911d9e5416af40039a30535202851181`, durable intent02:31:06.7592337, venue400`invalid_order` refusal at02:31:06.8355021. Its opaque detail does not identify a pair-cap, imbalance, cash or price-movement cause. The other reject is next-window and excluded. Do not call this a rejected Up hedge.

Local risk refusals are not individually recorded in these files. Subsequent actual Up requests narrow from5contracts at45–47c to4@54c,2@59c and1@65–68c. Conditional average-cost arithmetic with the final5Up/8Down inventory and no other pending/cash/stop effects is consistent with the existing99c pair cap:4Up@54c gives98.75caverage pair cost whereas5would give99.25c;2Up@59c gives98.75c whereas3would give100c;1Up@65c givesabout98.0833c whereas2would giveabout100.4643c. These are explanations of constraints at **observed request prices**, not logged rejection counts, executable opportunities or a complete replay of reservations/account freshness. The JSON explicitly labels them conditional. No new clipped quote or threshold is proposed from this loss.

The first supplied final-status tail corroborates actual reprice-cancel acknowledgements for the last Up1@65c andUp1@68c bids, with `reduced_by=1.00`. Later source-clock notes say at02:41:00.0293763 the controller was waiting to complete3Up with reason`lock_price`, then02:43:53.9156127 reason`no_ask`. Under the existing late-lock path, ordinary pair caps and loss stops are not themselves the lock gate; the lock still requires permitted price, an actual ask, fresh/reconciled conditions and the existing size/clock rules ([lock contract](https://github.com/sideriapostolou-lgtm/Claude/blob/ef1f3d38a49332bb19c69a8b1770abc56d83eb56/src/nightcrawler/speeddesk_live_model.py#L676)). `no_ask` is the controller's available snapshot, not proof the entire venue had no liquidity continuously. These isolated notes cannot certify a cheaper earlier maker bid would have filled.

## Strongest next prospective evidence requirement

For the already declared future fixed window, join exact client/twin IDs and named decision, submission, acknowledgement, cancel/expiry, venue fill and reconciliation-observation clocks. At each first positive full-pair event, distinguish **new directional submissions afterward** from **existing resting residuals and cancel races**; preserve remaining reservations and eventual losses. Phase1diagnostics can improve those identity joins and state-at-reconcile evidence, but cannot reconstruct source-time books, actual queue ahead, cancelled orders ahead or every accepted public trade.

Before any later policy comparison, freeze a fresh read-only/paper protocol that includes **all** subsequent wins, losses, missed profitable rounds and unknowns, with no tuning to this consumed losing example. Verify causal book/print/queue/opportunity evidence before assigning hypothetical fills. The actual loss is established; the profitability of stopping after a pair, changing a quote or any alternative execution rule remains unproved. Live source, settings, caps/stops and the current capture stay unchanged.
