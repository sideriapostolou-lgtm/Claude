# PR67 fixed runtime observation

Declared 2026-10-16 00:11:50 UTC (5:11 PM PDT October 15). This declaration must be committed and read back before the start; otherwise report it as retrospective.

## Fixed identity and window

Source **0520f7468174d6a37f0ee7dfe64284b1a6921439**, tree **d9eae74b5c76b28b74c85b3617ff3d2266969321**.
Railway bot deployment **d32c256b-618d-4927-b44a-f182d569977b**, project75750847-85c0-41a3-a2a7-b7f2201a51e9, production17f7b0e0-104c-4903-9484-0106748b3cdb.
SUCCESS observed5:07:55PM, actual terminal update5:07:45.558PM. Fresh original live status5:10:56.873PM was retrieved5:11:15PM: authenticated, trading_now=true, waiting empty, integrity null, cleanup false, same caps and cumulative losses. Cold/stale originals5:08:54 and5:09:56 remain recorded; this is not an always-fresh claim.

**Target [2026-10-16T00:15:00Z,00:30:00Z)** = October15 **5:15–5:30PM PDT**.
**Tail [00:30:00Z,00:32:00Z)** = **5:30–5:32PM PDT**, separate.
This is the earliest full quarter-hour starting more than60s after actual readiness verification. The restart-spanning5:00–5:15window is excluded from runtime performance attribution, but every actual fill/fee/settlement/loss remains recorded separately. Do not substitute another window because of its outcome.

Freeze source and all policies/variables/limits/stop-resume controls through the tail. No new strategy implementation or promotion during this capture. Existing automatic UTC-day behavior is not a manual resume.

## Forecast/history question

Expected new observer fingerprint f2652c6b9f5f4732b5ac865d72c4748df250ad73b38d493387f9dfc478dcff6c; existing fixed five-minute-into-window forecast at **5:20PM**, outcome after5:30PM. Preserve exact probability/time/inputs/eligible flags and independently received official label. Report invalid/pregap/late/missing predictions as failures/unknowns, never backfill or reselect.

Predecessor23e2 archive9forecasts/8scores/2unknown/1pending/Briers0.21951097364308783 and0.21989732433315107, plus separate older5-score archive, are retained. Pending old-source forecast is frozen unresolved, not silently relabelled by the new epoch. New epoch begins separate at0. Current-source score is an observation, not an accuracy or profitability estimate.

## Runtime and financial evidence

After the fixed tail, query exact deployment originals with actual before/after UTC retrieval receipts and full native wrappers. Limits500 per query; split any saturated ranges while retaining failed/saturated parent attempts. Deduplicate exact(timestamp,message); never repair or claim complete parsing of truncated message strings.

Required original event families: real order/fill/cancel/reject/settlement/status, practice window/status, probability forecast/unknown/scored/status, and the three original main-reader timing/gap/unavailable prefixes in RECURRENCE_DECLARATION.md. Keep raw filters/request bounds. Unfiltered or broad filters are supplements, not proof every event was returned. A zero is bounded by the filter and interval.

Use the unchanged thirteen-check existing recurrence analyzer/declaration rules: separate main(reader speeddesk, instance1/process1) and derived readers; gap vs status, target vs tail, known vs overflow/unavailable/invalid. Known accepted→recv_call durations over1000ms/3000ms establish local post-acceptance buffering in this logged sample, not CPU saturation/network latency or a unique culprit. Do not add nested CPU/wall spans or overlap populations. Checkpoint spans are descriptive completed shown spans with source/session identity; actual practice C/W/D history sizes remain unavailable. Do not claim production improvement from synthetic medians or different pre/post workloads.

Financials: reconcile real fills/order IDs/fees and official settlement for the exact target ticker if discovered, keeping receipt-day vs settlement/window-end cohorts explicit. Separate locked vs directional and real vs practice. Keep all adverse outcomes and other windows separate. No fills means no trade-P&L observation, not a profitable no-loss strategy. Practice quotes/fills must retain existing latency/queue rules. A mismatched fee/result, uncertain order, source change, malformed/truncated required evidence or missing coverage keeps conclusions incomplete.

Root will receive public official Kalshi market data read-only, no account credentials or real orders. Financial/latency coverage is conditional on original evidence; this does not certify full ledgers/volume or future TEST. Family A and all other holdouts remain unopened. Broader EXEC/profitability, operating transfer and recorder feasibility are not cleared by one window.

## Next decision

Complete the declared observation, publish the actual result, then prioritize proven remaining delays or the source-pinned cap-clipped hedge hypothesis. That hypothesis has only a synthetic admitted-quote proof; it is not live and has no counterfactual P&L. Existing original/inverse/no-trade study and its prerequisite/multiplicity gates remain unchanged.
