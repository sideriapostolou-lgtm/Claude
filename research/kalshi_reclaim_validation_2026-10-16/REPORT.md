# Reclaim-bot validation: do not promote on this evidence

As of October 15, 2026, 7:15 PM PDT. We tested the **two current** J0shusmc/Kalshi-BTC rules pinned to d5a55bf10c02ddc2b429eec78b1fd847fa1b6760. **Profitability is not established.** The fixed primary proxy made just **+$0.1007 after fees on four hypothetical one-contract trades over nine evaluation days**. Its separately unopened three-day confirmation lost **−$0.4674 on its only trade**. It fails the preregistered research screen. Do not copy this into live trading or claim the source's published+$78.134 proves its current rules work.

## What actually ran

We independently reconstructed the source's YES70c and NO80c reclaim lanes; never imported, installed or executed the third-party bot. This is a **sampled-taker proxy of the signals**, not its actual GTC resting-order strategy. Prices are tested after fixed1s/3s delays with displayed unit size, spread/quote integrity, current modeled taker fees, actual completed minute bars and official settlement results. Every entered losing trade remains. No compounding, size search, threshold tuning or winning-secondary selection.

Original [protocol](PROTOCOL.md) was published in4ab0ab7 before validation results. [Endpoint/scoring clarification](PROTOCOL_AMENDMENT_1.md), exact sources,95fake checks and independent reviews were frozen in **[7555aed](https://github.com/sideriapostolou-lgtm/Claude/commit/7555aedafccdcd214e9c8231ae641deb60b87587)** and all26public files read back exactly before confirmation access. [Manifest](CONFIRMATION_FREEZE.json) and [publication receipt](FREEZE_PUBLICATION_RECEIPT.json): complete hash/path verification at October15 **7:08:51.341PM PDT**; first confirmation download completed **7:08:56.662PM**; all collection completed **7:09:43.004PM**. Confirmation was not downloaded/read earlier by these workers. Historical data publishers/others may have seen it; this is local historical confirmation, not genuinely future evidence.

VAL summary was disclosed to the independent reviewer after core freeze while integration review was pending. After VAL, only fake-test type narrowing and collector-local metadata-path cleanup changed; no threshold, lane, execution rule or data-eligibility setting was optimized. Original failed fake cases, cached-byte-bound defect, receipt-file glob defect and initial strict-typecheck failure are retained in [checks](CHECKS.json) and reviews.

## Primary result: one contract,1second delay,70/80c targets

| Fixed cohort | Planned windows | Official markets | Known fills / attempts | Fees | Net after fees |
|---|---:|---:|---:|---:|---:|
| VAL, October4–9UTC |576|568|3/4|$0.0919|+$0.5681|
| Confirmation, October10–12UTC |288|288|1/1|$0.0174|−$0.4674|
| Pooled evaluation, DEV excluded |864|856|4/5|$0.1093|+$0.1007|

VAL runs October3 **5PM** through October9 **5PM PDT**; confirmation October9 **5PM** through October12 **5PM PDT**. Windows are attributed to their UTC opening day; those day boundaries differ from local midnight. These hypothetical gains are not real account receipts, cash balances or the live bot's P&L.

Four trades: three positive, one negative; only **four distinct traded UTC days**. The conditional observed-snapshot entry fill rate is4/5=80%, not a verified exchange/GTC fill rate. Net gross before fees is$0.21; fees consume$0.1093. Worst window and known-only peak-to-trough drawdown are **$0.4674**. Largest win$0.2115 exceeds the entire pooled net. The declared9calendar-day block bootstrap gives **−$1.1907 to+$1.0698**, descriptive/unstable with this sample, not a credible durable-edge certification. Locked P&L is$0by construction; net is directional/exit-rule P&L.

The preregistered positive screen requires pooled and confirmation net>0, at least30known filled windows across7distinct traded UTC days, no unresolved entered outcomes and conservative unknown-entry bounds. It fails confirmation, sample-count and traded-days requirements. `NEGATIVE_TESTED_PROXY` is the frozen screen's label because the complete confirmation all-attempt upper bound is negative. **One held-out loss cannot establish a statistically negative expected return either.** The defensible adoption verdict is **not proven; no live promotion**.

## The loss, with the actual observed path

October11 **2:45–3:00PM PDT** market KXBTC15M-26OCT111800-00: the YES reclaim fired after a−$18.31first-five-minute Bitcoin move and a−$116.3030distance below the frozen EMA. At **2:52:02.295PM** the delayed sample showed YES ask45c with sufficient displayed unit size. One-contract modeled entry fee$0.0174 made total risk$0.4674. Among465subsequent sampled bids before close, the highest YES bid was **62c**, below the fixed70c target; no target exit attempt occurred. Official Kalshi result was **NO**. The proxy therefore loses the complete **$0.4674**, with no invented sale, cash refund or erased expiry loss. [Case](LOSS_CASE.json) and [all attempted trade rows](TRADE_LEDGER.json).

The two independently preregistered exit controls also lose this confirmation trade. Lowering the exit target after seeing62c would be a new, fitted hypothesis; we did not do that. This case shows that the chosen bounce/EMA filter can select the losing direction and never reach its target. It does not demonstrate a repeatable predictive edge or prove that another fitted exit would have been executable/profitable prospectively.

## All six fixed comparisons, without selecting a winner

| Delay / exit policy | Pooled fills | Pooled net | Confirmation net |
|---|---:|---:|---:|
|1s/current70–80c, **primary**|4|+$0.1007|−$0.4674|
|1s/70c both|4|+$0.0074|−$0.4674|
|1s/hold to settlement|4|−$0.0997|−$0.4674|
|3s/current70–80c|5|+$0.3323|−$0.4875|
|3s/70c both|5|+$0.2387|−$0.4875|
|3s/hold to settlement|5|+$0.3428|−$0.4875|

Exit-policy controls share identical entries within each delay cohort. The3scohort recomputes entry availability and has a different set of five fills; its higher pooled number does not show slower execution improves expected returns. All policies have negative confirmation. See [comparisons](COMPARISONS.json); never promote a secondary cell as the primary result.

## Coverage and what remains unknown

- Of864planned windows,856have official metadata;816have any selected BTC book samples. The eight absent official-response windows are October8 **midnight–2AM PDT** (07:00–09:00UTC), with88markets/cursor empty in the preserved response. Cause unknown; do not claim a venue outage. Forty confirmation markets lack entire book coverage; the October12 file stops around7:21AM PDT (14:21UTC), rather than covering the full day.
- VAL has480,132BTC book rows and202same-market gaps>3s, maximum573.962s. Confirmation has206,785rows and35gaps>3s, maximum628.078s. Those are sampled records, not continuously captured duration. Missing YES ask rows13,880/5,692; unusable official side-bar counts1,078/546. Counts are not independent window populations.
- There are64pooled pre-signal unobservable windows, **policy abstentions, not proven economic no-signals**;787observed no-signal windows and one observed unfilled attempt remain separately counted. Zero attempted unknown entries and zero entered unknown outcomes in primary do not make missing windows complete or certify the entire market path.
- All required Coinbase minutes are present in VAL/confirmation. DEV has only58/96book markets and one missing Bitcoin minute (October2 **9:47AM PDT**); DEV's hypothetical results are excluded from every pooled/confirmation conclusion. Publisher settlement labels that are present have zero disagreements with official results; absence of a publisher label does not replace the venue result.
- Book files are third-party REST-normalized public samples with verified release digests, not authenticated exchange sequence/order/fill evidence. Producer provenance and raw-data license remain unresolved; raw market files are private and not redistributed. Historical APIs can revise data and do not prove bar first visibility. Minute-end+1s publication and execution delays are explicit assumptions.
- A quote available at a later sample is **not continuous quote survival**. Actual GTC queue placement, maker fill rate, partial-fill ordering and order acknowledgement latency remain unavailable. No paid account, keys or live orders were used. One-contract numbers cannot be multiplied into a trustworthy larger-budget projection.
- Public acquisition recorded no429s in VAL/confirmation. Initial DEV bulk-candle request exceeded the API aggregate bound and returned400; collector batch bounds were corrected before VAL, failure retained. [Coverage](COVERAGE.json), full partition results and input hashes retain omissions and errors.

## Decision and next evidence

The bounded historical evaluation is complete; a profitable, faithfully executable bot is **not** established. Its sparse sample and losing confirmation do not justify switching our live strategy, increasing caps, resetting stops or taking another real-money test merely to make the evidence look better.

First resume the existing EXEC real7/practice0 maker-receipt/queue/data reconciliation; those execution gaps still prevent trustworthy strategy comparisons. Any future reclaim investigation needs a separately frozen prospective **read-only/paper** record of actual bar first visibility, causal quote/size availability and honest order assumptions, with enough events to evaluate the rule without reusing this confirmation for tuning. Preserve this result and loss as prior evidence; no funded probe is required to establish whether the signal itself is predictive. The source's operational faults remain separate NO-GO issues; do not wholesale install it.

No live application code, deployment, Railway setting, trading rule, account, order, cap, stop, loss budget or resume token changed. Prior real/practice losses remain untouched. Recorder raw-volume/retention/cost, operating takeover and broader EXEC/profitability stay open. TJR/MNQ stays last. [Reproduction](REPRODUCTION.md), [evaluation](EVALUATION.json), [checks](CHECKS.json) and independent reviews preserve the exact implementation and limitations.

[Independent result review](astra-review/RESULT_REVIEW.md) and [2,094 result checks](astra-review/RESULT_CHECKS.json) separately verify arithmetic, exact clocks/cohorts, selected raw entry/exit receipts, fees and retained losses. These are result-audit checks, not additional profitability observations or synthetic pytest cases.
