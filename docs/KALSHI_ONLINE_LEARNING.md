# Kalshi learning: forecast first, score after settlement

This first slice measures whether an outcome-trained probability estimate improves on the existing Bitcoin
model. It runs in the existing practice arena's child process. It cannot send orders, change live probabilities,
promote a strategy, raise limits or reset stops. It uses no language-model calls or additional market subscriptions.

**Release status:** PR60 exact `933a43d` deployed successfully October 15 at **6:52 AM PDT**. Original
startup and 6:58 AM periodic logs verify enabled **observe-only** learning: **0 forecasts, 0 scored,
1 startup-partial exclusion, null Brier scores**. No trained-sample, accuracy or profitability result yet.
The implementation passed independent review, 5,673 tests / 14 existing skips, mypy and changed-file Ruff.
[Exact preparation](../research/kalshi_online_learning_2026-10-15/PREPARATION.md) and
[release/account verification with coverage limits](../research/kalshi_online_learning_2026-10-15/RELEASE.md).
These dated counts are evidence timestamps, not a continuously updated dashboard reading.

**Forward check, October 15 at 8:09 AM PDT:** still 0 forecasts / 0 scored. Five full forecast slots were
excluded for pre-forecast feed gaps, plus one startup partial. The learner is running but has no usable
training observations yet; the data path needs diagnosis. [Original observations and limits](../research/kalshi_online_learning_2026-10-15/OBSERVATION_2026-10-15_0812_PDT.json).

**Forward diagnostic, October 15 at 10:35 AM PDT:** PR62's unchanged-V1 diagnostic joins the target rejection to explicit window-gap messages. Aggregate trade/Coinbase flags are true and the forecast-time BTC input is 0.245 seconds old, but earlier pregap is retained. The upstream branch and producer clock remain unavailable. At **10:45:18 AM**, counts are still **0 forecasts / 0 scored / 16 unknown**, null Brier scores. The fixed real window separately earns $0.11; that is not learned predictive skill. [Originals, losses and remaining cause evidence](../research/kalshi_input_causes_2026-10-15/RELEASE_CAPTURE.md).

## What already learns

The live fair-value model uses current Bitcoin prices and rolling volatility. Its volatility input changes
with the market, but its probability formula does not fit itself to realized outcomes. The existing arena
mutates practice strategies and flags candidates for further research; a lucky candidate is not proof of an edge.
The separate `learn/` engine concerns memecoins and does not train Kalshi probabilities.

No learning process can become perfect at predicting uncertain markets. A better directional forecast can
still lose money when prices, spreads, fills, fees or reaction times are unfavorable. Known multisecond
market-feed processing delays remain a separate open task, EXEC-DELAY-001.

## Fixed prospective procedure

1. Use only future, fully admitted Kalshi **KXBTC15M** windows of 900 seconds. Include quiet/untraded windows;
   do not select observations because the bot traded, won or lost. Startup partials, invalid inputs and
   explicit pre-forecast gaps remain counted exclusions.
2. At **300 seconds after the start**, allow at most a **5-second** observation grace. Record the actual
   child observation time, never pretend a late prediction happened at its scheduled target. A missed slot
   is unknown, not a prediction reconstructed from later data. Use finite, fresh Bitcoin inputs, valid
   window terms and nonnegative sigma, including its supported zero-volatility boundary. Bitcoin age
   must be between zero and three seconds. A future listing may acquire its first known opening price
   before forecasting; changing an already known strike is a distinct data defect.
3. Freeze the current normal-CDF Up probability, including the existing Kalshi final-minute averaging
   adjustment. Also freeze a challenger probability from **previously settled** observations in one of
   ten fixed probability bins:

   `challenger = (previous_bin_wins + 20 × baseline_probability) / (previous_bin_count + 20)`.

   With no observations in a bin, challenger equals baseline. This simple, fixed shrinkage procedure has
   no parameter search, breeding or best-performing-model selection. Save the feature values, bin counts,
   window identity/terms and protocol/source fingerprint with the frozen predictions.
4. Wait for an official finalized market result. The existing public Kalshi adapter checks ticker,
   `status=finalized`, yes/no result and matching settlement value. That result travels through the existing
   snapshot; its route through a practice object's closed list does not make its simulated money real.
   Never infer a label from Bitcoin's final spot, markouts, a practice profit, a void or a missing result.
5. Score both **saved, pre-outcome** predictions once, then update the matching bin. The score is
   **Brier loss**, `(predicted_up_probability − actual_up)^2`: lower is better. The current result must
   never affect its own prediction. Repeated/out-of-order labels cannot double-train; conflicting labels
   and changed terms are explicit data defects. Official labels must first reach the child no later than
   two hours after close; timely queued labels can be processed later. A late/missing result stays unknown.

Gaps after a forecast do not justify deleting an already frozen losing prediction. Retain their coverage
flags and score a valid same-terms official label when it arrives. If terms change or the label remains
unavailable, retain an explicit unknown result. Report that observed forecasts are conditional on the
admission/data-quality rules; they are not certified coverage of every market window.

## Persistence and operational boundary

The learner has bounded pending forecasts, recent receipts and fixed-size aggregate bin statistics. Its
forecast/score/count/dedup state is an optional, independently validated field in the arena's existing
atomic snapshot. Restore uses the latest available existing checkpoint, with its existing durability
limits; there is no new fsync or power-failure guarantee. It uses the existing child checkpoint cadence,
with no new live-loop writer, per-tick
serialization or synchronous live-ledger I/O. Pending forecasts already persisted survive restart even
when the practice arena voids its open simulated inventories. A forecast lost before persistence remains
missing; it is never rebuilt after the fact.

Malformed or incompatible learner state disables only learning. It must not reset residents, practice
money, the real account or any consumed stop/resume history. A protocol/source mismatch cannot silently
combine histories or restart counts from zero. Running implementation and retained history have separate
identities when they differ; disabled old evidence is never relabeled as newly learned results.
Source/protocol identities are computed once, not per tick.

Child isolation does not make shared CPU/disk cost disappear. Required checks include bounded work/state
size, source/decision isolation, fault/restart cases and measured overhead. Deployment uses the existing
test/review/safe-minute/exact-commit verification process. There are no Railway-variable changes.

## Reading the evidence

The compact `kalshi_online_learning_status` logs and optional page-feed `kalshi_arena.learning` block
report observe-only mode, protocol/source identity, counts, pending/unknown observations, baseline and
challenger Brier scores, fixed exclusion-reason counts and a learning-only error. Live application and profitability-proven flags are
always false. Older, missing or disabled arena feeds may have no learning block; absence is not zero results.
Structured forecast/result receipts preserve the causal inputs and saved predictions. State keeps at most
32 admitted windows and 64 recent receipts/labels, plus aggregate bin counts. It is not a complete historical
training tape. Long-run independent replay requires retained original logs; their availability is not certified
by this release. Aggregate statistics never substitute for an invented trading history or verified profits.

The following claims require separate evidence:

- **“It has learned”:** real prospective forecasts followed by official labels, a reproducible update and
  retained gaps. Passing synthetic tests establishes implementation behavior, not real predictive skill.
- **“Its probabilities improved”:** sustained forward comparison of the frozen challenger against baseline,
  with sample size, exclusions, uncertainty, regime changes and correlated windows reported. Sparse bins
  learn slowly; a short favorable run is not reliable evidence or a guarantee of future improvement.
- **“It makes money”:** a separately frozen prospective strategy/execution test with obtainable prices,
  honest queues/delays, fees, every loss, stops and complete coverage. Brier scores do not measure P&L.

No automatic real-money promotion is part of this release. Existing original/inverse/no-trade and sealed
research partitions stay separate and unopened. Real execution continues to use its existing deterministic
rules and safeguards. Financial caps, ladder and loss budgets remain outside the learner's control.
