# Independent actual-loss review — October 16, 2026

**Strongest supported finding: the desk takes an initial one-sided position, and losses when cheap opposite fills fail outweigh its paired gains.** This identifies the economic leak. The available records do not establish a single deeper cause such as model miscalibration, stale quotes or queue adverse selection, or prove that a particular alternative entry/exit rule would profit.

## Fresh evidence, through 12:20 PM PDT

The selected native status was published **October 16 at 12:20:25.319917 PM PDT**. The saved fill/settlement query covers October 15 at 5 PM through October 16 at 12:22 PM PDT (the incomplete October 16 UTC day). Independently parsing the standalone event records with Decimal gives:

- **42 settlements: −$6.0789**, allocated to **+$4.993183 paired / −$11.072083 directional**, with **$0.3981 fees**. Every sum agrees with the selected native status within numerical tolerance. These accounting components are not independently tradable strategies.
- **30 nonempty balanced settlements: +$3.2539**. **Nine unequal-inventory settlements: −$9.3328**, with zero fees on those nine. Three additional settlements have zero shares and are not traded wins.
- **23 profitable settlements: +$10.9087; 16 losing settlements: −$16.9876**. All adverse outcomes are retained.
- **119 unique fill events** include **116 fills across 39 settled traded windows** and three fills in the not-yet-settled 12:15–12:30 PM window. All 39 settled windows' side quantities, cost, fees, gross payout and P&L reconcile to their actual fills. No P&L from the unfinished window is booked in the settlement total.

The three fully unmatched cases below are joined to exact original durable intents, acknowledgements, fills and settlements. They are illustrative adverse cases, not a randomly selected expectancy sample:

| Window closed, PDT | Actual fill | Opposite fill | Fees | Settled loss |
|---|---|---|---|---:|
|10:15 AM|Up 5 at 33¢|None|$0|−$1.65|
|10:45 AM|Down 5 at 35¢|None|$0|−$1.75|
|11:00 AM|Up 4 at 36¢|None|$0|−$1.44|

Combined loss **$4.84**, about **79.6% of the incomplete day's net loss**. That ratio is a descriptive comparison, not the profit that would have resulted from a rule excluding these retrospectively chosen windows.

Their recorded decision-to-acknowledgement times were **90.75 / 39.98 / 66.02 ms**, and accepted BTC input ages **66.06 / 46.78 / 76.50 ms**. Venue fills followed the respective durable intents by **1.821 / 1.232 / 6.023 seconds**. Thus these cases do not by themselves prove that the initial order was slow to send. Queue wait, changing fair value after decision, feed validity and missed hedge opportunities require separate evidence. The recorded decision fairs (36.51%, 38.99%, 39.87%) are not verified true win probabilities.

The current total snapshot reports **−$25.5707** lifetime settled P&L, allocated **+$8.673132 paired / −$34.243832 directional**. It is a reported cumulative summary, not an independently reconstructed lifetime ledger. Cash **$49.5007** is not trading profit.

## Completed prior day cross-check

I also independently decompressed and verified all **143 files** in the existing October 15 UTC evidence archive, then reparsed its **92 saved native wrappers** without executing the archived scripts. Its **302 unique fills / 71 settlements** produce **−$5.0447** including an inherited +1¢ pair; the 69 day-filled windows alone lost **$5.0547**. All **647** independent financial and intent checks passed, with no conflicting identity payloads or exact-event parse errors.

Of those 69 traded windows, **57 finished balanced, net +$1.7225**; **12 finished unequal, net −$6.7772**. Their total accounting decomposition is +$4.491151 paired / −$9.545851 directional; the inherited pair adds another 1¢ to the whole-day paired figure. Without the day's $0.8455 fees, the whole-day result would still be **−$4.1992**.

There is a historical prose error: `research/kalshi_reconcile_pass_2026-10-16/OCT15_COHORT_REVIEW.md:22` says 43 balanced windows / 14 negative balanced windows. The hashed native originals independently show **57 / 17**, matching `OCT15_COHORT_ANALYSIS.json`. The financial totals remain consistent. This review records the correction without rewriting the original evidence.

## Interpretation and next evidence

Fees and cash-loading problems do not explain the dominant settled losses in these cohorts. A completed pair can still lose when its all-in cost exceeds $1. Conversely, the negative additive attribution of late lock fills is not proof that removing locks helps: the prior day's three worst paired losses began on the losing side and their eventual winning-side locks reduced the losses.

The most valuable next evidence is a fixed, prospective first-entry assessment: for every real initial fill, preserve the exact decision and fill clocks, original fair, observable queue, fixed 1/5/30-second market markouts, all attempted opposite fills and the final result. Separately mark missing/gapped data and stopped/no-fill windows. This can distinguish weak entry pricing from execution-induced adverse selection without inventing a fill that never happened. No new entry threshold, automatic learning promotion, stop reset, cap change or profitable counterfactual is established by this audit.

Current independent artifact `HISTORY_INDEPENDENT_AUDIT.json` contains source SHA-256s, selected exact joins and **252/252 checks passed**. The `.py.txt` companion reproduces it using only these saved evidence files. An initial historical script expected a derived manifest omitted from the archive and failed; the successful run enumerated the 92 actual saved native wrappers directly. An intermediate message incorrectly suggested the unfinished window's fills followed the status; inspection corrected this immediately: all three fills precede 12:20, form equal 3/3 inventory and remain un-settled. Zero reported venue positions does not by itself prove no pending bookkeeping outcome.

The raw service-log query spans earlier source revisions. Healthy deployment metadata and selected snapshot concordance do not certify continuous full account/book coverage or assign every event to the current deployment. This independent review made no source, production, account, order or financial-control changes, and read no sealed TEST data.
