# Separate probability observer: exact preparation

Prepared October 15, 2026, 12:09 PM PDT. Source is tested and independently reviewed, **not yet deployed**. The old V1 simulator-quality observer remains unchanged. A new separately identified V2 asks whether conditional Bitcoin probabilities calibrate to official outcomes; it does not certify market-data continuity or executable trading returns.

The actual source reproductions distinguish quiet-maker expiry (legitimate V1 exclusion), an untimed prestart gap delayed across start, and a REST failure arriving after independent WebSocket recovery. None uniquely attributes the recorded production gap. The latter two timing defects remain separate unresolved work. This release changes neither producer nor wire and makes no upstream repair claim.

## Checks and preserved findings

Full pytest **5,884 passed / 14 existing skips**, captured exit zero. Mypy all129source files and Ruff all7changed Python files pass. Hashes before and after the complete run match the exact independent review. V1 fingerprint remains b6112b7e; V2's separate fingerprint is e7989706 and covers observer, input qualification and child admission source.

Independent baseline comparison matches49state checkpoints and98write payload/order/durability observations across six scenarios after removing only the new optional field. All177other existing source files and the parent link AST are unchanged. Constructor isolation, initial raw-sequence loss and contradictory restored forecast/history cases were corrected before the accepted checks. Initial page contract failure, unused-import failures, superseded runs, the parent timing failure and a resource-harness clock fixture error are retained as originals rather than counted as passes.

The first parent timing run exceeded its p99limit:0.535ms against0.5ms. Serial quiescent unchanged-base/candidate reruns both passed without changing thresholds; candidate max2.058ms remains an outlier in its original. No causal speedup claimed. Independent local child-resource checks pass the declared envelope: mean extra CPU0.008552ms steady/0.105375ms with512records, max32due p95extra2.191713ms/max4.323603ms. The populated capacity fixture serializes73,288bytes; largest measured event910bytes. These are local measured fixtures, not maximum real-world latency or continuous coverage guarantees.

## Preserved behavior and next gate

Live controller/model/risk/fees/ledger/ladder/config/feeds/Polymarket/build files, financial limits, stops, budgets and Railway variables remain untouched. The new observer has no order/client/promotion interface. Fixed prestart admission, first300–305second attempt, fresh accepted Bitcoin, verified matching venue strike, qualified sigma, complete fresh raw batch, raw sequence/drop integrity, strict labels/terms and score-before-train are in the frozen protocol. Maker/trade simulation exclusions remain V1 history; no sample is relabeled or backfilled.

Source release will restart the existing real bots under the owner's standing approval, only during safe minutes. Verify exact successful deployment, normal Polymarket startup, intended mode, retained losses/caps/consumed controls and service health; then freeze a future full window before its start and retain original forecast and official-score evidence. No production forecast, scoring, better accuracy, profitableedge, all-EXEC completion or trading promotion is claimed by preparation. TJR's authentic-data/cost blocker and the recorder's existing3:45PM Pacific checkpoint remain open.
