# Kalshi losses, other markets and leveraged perpetuals

Read-only review, October 15, 2026, Pacific time. Financial evidence captured at 11:17:56–11:17:58 PM PDT; latest financial sample is 11:16:56 PM. Public market samples were taken afterward and are separately timestamped. **The current strategy remains net losing. No profitable replacement or larger-size authorization is established.**

## What the latest update actually achieved

The bot is still on PR69 source `66d122b58000bdea98c95368bee5df912a9666bf`, deployment `2af8d2be-77f7-4738-ab67-33c37c09b86b`, online 1/1. That change protects a confirmed, profitable, fully balanced pair from ordinary new directional risk. It does not make the first unmatched buy safe. The new losses below never reached that protected state.

| Window ended October 15 PDT | Actual settled result, after fees | Actual inventory |
|---|---:|---|
|9:15 PM|−$0.3515|Inherited Up1 at40c; late Down1 at94.8c|
|9:30 PM|+$0.12|Up1 at32c, Down1 at56c|
|9:45 PM|+$0.23|Up1 at41c, Down1 at36c|
|10:00 PM|+$0.06|Up1 at52c, Down1 at42c|
|10:15 PM|$0|No shares; not a traded win|
|10:30 PM|−$0.7726|Up2 at48c, late Down2 at90c, fee1.26c|
|10:45 PM|+$0.01|Down1 at44c, Up1 at55c|
|11:00 PM|−$0.44|Down1 at44c, no opposite fill; Up settled the winner|

Six wholly new traded windows total **−$0.7926**: four gains total42c; two losses total$1.2126. Including inherited exposure, all eight settlement receipts total **−$1.1441**. The latter includes one zero-share receipt and seven traded windows. Twelve unique owned fills and eight unique settlements reconcile against the warm baseline's P&L, fee and count changes. Captured fees total$0.0161. Cash decreased$0.7441 rather than$1.1441 because the inherited40c entry had already been paid before that baseline. Paired credits are counted once.

For the 10:30 loss, the late hedge reduced the actual losing Up position's worst-case loss from96c to77.26c, a benefit of18.74c. Removing that hedge would not have improved this outcome. The remaining problem is the initial directional exposure and whether our first fills have predictive value, including adverse selection. The money-only stream cannot establish why a quote failed, which cancellation would have succeeded, or an executable alternative profit.

At **11:16:56 PM PDT**, the bot ledger reports cash **$25.1219**, cumulative settled P&L **−$24.6195**, and current UTC-day P&L **−$5.1277**. Cash is not profit. The current UTC day began October15 at5PM PDT and is incomplete. Reported open risk, principal, reservations, positions and orders are zero. Caps remain$10/window,$20/open,$6/day,$10/total, clip5, ladder0; no increase or reset occurred.

The exact stop receipt is **11:00:08.547061860 PM PDT**: the daily stop latched, and subsequent panels say PRACTICE with new risk disabled (`trading_now=false`). The stop still permits strictly balancing hedges/locks; the latest samples have no remaining exposure. This is the existing minimum-entry floor: $5.1277 used plus the unchanged98c floor exceeds$6. The remaining87.23c does not admit that floor. It does not mean settled losses exceeded$6. The configured setting is still live; no Railway variable was changed. The stop's existing UTC rollover behavior is unchanged.

Coverage matters: the partial scorecard's−$0.153 describes14 complete windows out of26 eligible, with12 gap windows. It is not the day's−$5.1277 trading result. Session fill diagnostics have only8 measured horizons out of36 requested, with28 gaps; these are not realized exits. One broad stop-log request failed with `Transport closed`; the successful narrower stop receipt is separately preserved. Healthy service state is not complete volume/account coverage.

## Other markets checked

**Monthly crypto far-strike NO:** current books do offer liquidity. BTC October above$97,500 NO was97c with8,014.27 displayed contracts; BTC above$100,000 NO was98c with5,569.14. ETH above$3,250 NO was97c with1,350.52. These are single-time displayed asks inferred correctly from opposing bids, not our fills. At an illustrative current standard direct-account one-contract/one-fill taker charge, buying97c risks97.21c to earn2.79c if right. A99c purchase can lose even with a99% true win probability after fees. True probabilities, prior-touch index state and historical queue fills are unverified. Current monthly prose and the linked CF-statistic PDF remain inconsistent. The existing TRAIN audit includes a losing January and four NO losses at96c or above; its verdict remains INSUFFICIENT DATA. Its VAL/TEST data were not opened here.

**Weather:** the checked late Los Angeles/Denver apparently discarded buckets had large99c NO bid queues, but no opposing YES bids creating purchasable NO asks. A waiting buyer queue is not stock available to buy. Current binding terms name The Weather Company and specific stations; METAR/NWS observations alone do not establish guaranteed settlement. Finish the existing source-qualified stopwatch before claiming arrival-time opportunities. No new weather observer or live desk was started.

**Slower daily commodities/financial markets:** a separate current-book review checks WTI, S&P and Nasdaq daily contracts. These remain hypotheses, not strategies to activate. The current WTI event carries DIRECNET and the index events MECNET; the frozen Family A rule U8 requires an empty collateral-return type. Thus the checked examples cannot be admitted by silently relaxing that protocol. Any linked-market extension needs explicit scenario/accounting mapping and a separately frozen future experiment. The original Family A test remains unchanged.

The strongest prior empirical lead is still passive favorite-side bids in slower markets. The authors' [Kalshi study](https://www.karlwhelan.com/Papers/Kalshi.pdf) reports an average2.6% return for makers buying50c or more, with33% return standard deviation, in a sample endingApril2025 before maker fees and restricted to markets open at least24hours. This is an old observed-fill association, not a forecast, our attainable queue fills or evidence for15-minute crypto. Current fees, capital lockup and all failed entries must be measured prospectively.

The earlier [reclaim-bot evaluation](../kalshi_reclaim_validation_2026-10-16/REPORT.md) also remains a failed adoption screen: its separate confirmation lost46.74c on its only trade. No negative result was erased and no old holdout was retuned.

## Leverage exists, but it is another product

The owner is correct: Kalshi now offers [perpetual futures](https://kalshi.com/perpetuals/learn), including Bitcoin. They follow continuous asset prices rather than a15-minute fixed$1 outcome. A new margin account, account approval and different accounting are required; this owner's account access is unverified. [Official access requirements](https://help.kalshi.com/en/articles/15357656-applying-for-perpetuals-access), [API overview](https://docs.kalshi.com/margin).

Public leverage displays and educational pages differ and may change; none is an entitlement for this account. [Fees](https://help.kalshi.com/en/articles/16071417-perps-fees-explained) apply to the full notional on opening and closing, with separate funding payments. The fee table's search index rendered rates, but direct page extraction returned only an iframe: account-specific effective fees remain unverified. Detailed [risk disclosures](https://kalshi.com/perpetuals/learn/leverage-trading) explicitly allow negative balances/additional money owed after extreme moves; isolated margin and liquidation are not guaranteed loss caps. The existing binary-bot dollar limits do not automatically protect a new leveraged account. No application, transfer, margin setting or order was made.

## Concrete next step, without duplicating research

Keep EXEC-DELAY-001 open: finish the existing venue queue/practice-input validation, then predeclare a fresh multi-window entry-risk comparison. Count the first unmatched entry, expensive hedges, failed pairs, fees, gaps and forgone winners. The existing natural stop is not reset for data collection; public/shadow observation can proceed without new real losses.

For other markets, finish the already running Family A **Phase0** recorder evidence and the existing weather stopwatch's source/arrival evidence; do not build another collector or call these brief snapshots a backtest. Obtain permitted non-TEST status/verify/volume exports and measured cost, establish actually admissible markets, quote survival/depth at its frozen simulated$25/$2cluster/$4outstanding budget, then follow the frozen TRAIN/VAL/future TEST sequence. Its protocol hash remains`40ccfe87ed86b3fd62ee16ebba9862f8be8bbc66a229cfdc7f138ee26a305040`. Today’s different live caps do not replace those research caps. Recorder retention fit beforeOctober20, operating transfer and other obligations remain open; TJR/MNQ stays last.

Final follow-up, retrieved at11:24:11PM PDT: three further status samples through **11:23:57.994754437PM PDT** retain the same cash/P&L, zero reported risk/reservations/orders/positions, caps and daily-stop PRACTICE state. This does not extend the money-event query beyond11:18PM or certify whole-account coverage. The bot-branch recorder guide returned404; the correct guide and unchanged Family A protocol were successfully fetched at the exact running recorder commit`a0782b743a31369fe25ddf6d2eea96df8511cd8d`, matching the existing checkpoint rather than inventing a successful branch read.

This bounded loss/market/product review is complete. Profitable strategy validation, full execution evidence and any live extension are not complete. No source, production deployment, trading rule, order, variable, budget, resume token, storage or paid service changed. Docs-only publication does not restart the bot. Original financial receipts, independent114-check audit and timestamped public research are retained in the accompanying evidence archive; these checks verify arithmetic/provenance, not profit.
