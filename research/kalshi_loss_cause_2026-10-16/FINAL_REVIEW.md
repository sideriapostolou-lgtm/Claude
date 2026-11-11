# Final independent diagnostic review

**Verdict: PASS for the bounded retrospective diagnosis and docs/research publication. No blocking corrections found. This is not approval of a trading-policy change or a claim of profitable future performance.**

The strongest supported answer is that initially unmatched exposure loses more than paired inventory earns when opposite fills fail to complete. The report properly leaves the deeper predictive-versus-execution cause unresolved. Model miscalibration, queue adverse selection, cancellation timing and missing affordable liquidity are not separately identified by this evidence.

## Verified evidence

- Re-executed the reviewed `audit.py` with its output write replaced by an equality assertion against the existing `AUDIT.json`: all **960 checks passed**, with exact generated-artifact agreement. No audit artifact was rewritten.
- Independently recomputed matched accounting from each side's actual fill quantities, prices and allocated fees for all **42 settlements**. Every allocation agreed within $0.000000001. Confirmed **119 unique fills**, **116** belonging to settled windows, with the remaining three in the unfinished window.
- Verified **$172 payout − $177.6808 purchase cost − $0.3981 fees = −$6.0789**, and **+$4.993183 matched − $11.072083 directional**. Confirmed the separate grouping of **30 nonempty balanced settlements +$3.2539**, **nine unequal settlements −$9.3328**, and **three zero-share settlements**. Accounting components are not standalone tradeable strategies.
- Reviewed original current-day standalone messages and the three exact intent/acknowledgement/fill joins: Up5@33¢, Down5@35¢ and Up4@36¢ each settled with no opposite fills and total **−$4.84**. These are explicitly selected losing examples; neither the report nor this review treats excluding them as an achievable counterfactual.
- Checked the projected status and late-tail evidence: the cited pair-cap and lock-price/no-ask observations are present, with intermittent stale-book observations in the last example. These are controller observations, not a complete historical book. Current-session markouts show five observed fills and fifteen missing horizons.
- Inspected the normal-CDF proxy, sequential starter guard, hedge-budget sizing, ordinary pair-cap check, size-only candidate loop and late lock path in the referenced source. The three reviewed trading files have no diff between deployed source `e72f4b8b86dc812ab333a45d54151ae44f8c713f` and review base `1a061bed3d833138769ebad3422e941a109cbb68`.
- Cross-checked prior-day reported totals and the corrected **57 balanced / 17 balanced losing** counts against the existing `OCT15_COHORT_ANALYSIS.json`, and reviewed `HISTORY_INDEPENDENT_REVIEW.md`. The full historical archive reconstruction is the preceding independent review's work; this final reviewer did not repeat that archive decompression and should not be represented as having done so.

## Scope and limits

The evidence cutoff is **October 16, 2026, 12:20:25 PM PDT / 19:20:25 UTC**, with bounded service-log queries through 19:22 UTC. It is an incomplete day spanning source/cap changes. Absence of a provider-limit hit does not certify full account coverage. Cumulative P&L is a reported snapshot. The unfinished balanced window stays outside settled P&L, and zero venue positions alone does not certify that bookkeeping is complete.

The report correctly avoids inferring that faster initial sends would prevent these losses, that disabling protective locks would help, that every balanced trade wins, or that more budget establishes a profitable hedge. Removing fees arithmetically leaves a loss. The next prospective evidence step is appropriately framed as research, with conservative fill evidence and all missed wins/losses retained. No sealed TEST was accessed.

This reviewer used saved local evidence and source only. No production, account, order, deployment or financial-control access/change occurred. The saved caps of $20/window, $40/open, $12/day, $10 total allowance and clip5 were observed only and confer no authority to replay or change them. Only this `FINAL_REVIEW.md` was written. Integration documentation and publication remain the root agent's responsibility; no application tests or deployment verification are claimed for this diagnostic review.

Workflow-requested review role/model: **independent money-sensitive reviewer / GPT-6 Astra**, per `docs/MODEL_WORKFLOW.md`. This delegated review completed successfully, but the task/role name is not independent runtime attestation of the exact serving model. No model billing or token-cost proof was available.

## Reviewed revision

Base source SHA: `1a061bed3d833138769ebad3422e941a109cbb68`.
The following SHA-256 manifest fixes the complete diagnostic evidence/report set reviewed before this review file was added. Any material change to these findings or evidence needs renewed review. Root's operating-document edits and eventual publication commit are outside this file-set verdict.

Review recorded UTC: 2026-10-16T19:25:20.815848+00:00.

Manifest SHA-256: `31daf2ebd6b21cfeffa5d5f688939afee41a8713d5086224c2f5e87099359d55`.

```text
74a872c32233ab37aeb52dbc482f80196bbc7fe3a3bc5670c7091f166ed7e3a0  AUDIT.json
4eecfe011d56dd92e893f1d97c625e7f20277a4db39e7fbbe590669e22cfde46  DEPLOYMENT.json
4c151c64407e1976116322e8686926a80981153392e4ef36275ec748eab7f44e  HISTORY_INDEPENDENT_AUDIT.json
099c98998f7042c5da92448beb0d80c2789f46178c4c055fb2b5db4db9a45a4c  HISTORY_INDEPENDENT_AUDIT.py.txt
814ab9b408d43702a1a30010b06f50ed4c2c10bc07580d9c69c500578d90125a  HISTORY_INDEPENDENT_REVIEW.md
0f1e84bb9415891cd077024eeac1b266dd247e4626ed456801231afdce11d8a6  LOSS_TAIL_1315_PROJECTION.json
24eb777a1a5009b8486751b1cf9b8be06591e70c38c6940f5f56aa24afe0559e  LOSS_TAIL_1345_PROJECTION.json
220dfe63f5ea4401bfb8568b6f35ab604b79aae45a98de993338e4cd8d4a24fb  LOSS_TAIL_1400_PROJECTION.json
049f78831797adb5a56c260b73dc73a0f7876db5d3493d6d898333a870a4e53c  REPORT.md
f7c5481a74ea6f12edec4574a7ab06cbe98d268b39dc644b284a1479cfbfad22  STATUS_PROJECTION.json
315892661794bb1be33f90f7643fda0e45dbe6d449eed5b1d03e7621d2e287c4  audit.py
301904f36cf4f75ec3f9bd7ff6160310ded99b9eb34e48a74df22ce77a551637  fills.json
70ed14a13fe7ba497392cb764629b775d4ecde169e9d5b2bafcadb69fe85237f  orders_1700.json
8122334ac48499604fb366f7f343740652f21d616f26e1157ad30bbd5f2ab98c  orders_1730.json
3ffa607730f682a66dacf6d00063f388f97df8508f25ca2c7c137386a6ba5b31  settlements.json
```
