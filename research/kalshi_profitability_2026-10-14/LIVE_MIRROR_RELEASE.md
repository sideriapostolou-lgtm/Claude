# Mirror correction released; active-window verification pending

October14,2026,9:56PM Pacific (October15,04:56UTC).

PR58 merged at **9:47:47PM PDT**, after the previous fixed collector closed and
stopped at9:47:18.296PM. Exact source **1e8d0be07b280292fa873a2f5da9b22dd02f28c3**
matches reviewed four-file bundle0faa0c5d9a1fd07c4824f51b323ec5a4d068837d6d0fdf64fb4ea6cee7eccac2.
Railway **fc0a73e9-f052-435a-94b2-ce7b1272f36e** reachedSUCCESS9:48:49.546PM;
Polymarket logged normalLIVE startup9:48:47.145PM. Both services wereonline1/1
with no reportedissues/failures. The bounded startup query through9:49:50PM
returned no traceback; this is not continuous/global error coverage.

The one-write display correction retains financial ledger authority, commit and
mirror ordering, save cadence, risk/order rules and all loss history. No Railway
variables, caps, stop/resume budgets or Polymarket code changed. Full required
checks passed:5,564tests/14existing skips/exit0, mypy127/Ruff4; exact independent
123targets. Synthetic speed and allocation limits remain in
[the correction scope](LIVE_MIRROR_CORRECTION.md).

## Restart accounting

[Independent restart audit](LIVE_MIRROR_RESTART_AUDIT.md) checks53selected fields:
37equal/16changed, zero missing. The final old status9:47:48.941PM and first new
9:49:34.105PM are not identical financial snapshots. One real old-process fill,
Down5at$0.36/zero fee, joins its durable intent and accepted order. ExistingUp5
at$0.46 plus this$1.80purchase yields$4.10gross cost and zero paired worst-case
risk. Cash$33.7994→$36.9994 is arithmetically consistent with$5pairnetting credit
minus$1.80; this is not an independently exported venue cash transaction.
Fills631→632, makerorders4757→4762 match retained late events. Pending404cancel
responses retained reservation uncertainty until reconciliation; they were not
treated as proven cancellation before that fill.

Cumulative settledP&L **−$13.642**, fees$2.70752, effective10/20/6/10caps/clip5,
stop latches and selected ladder fields remain equal. Integrity/day/resume controls
all logged ignored-already-used. No raw ledger/stop-anchor export is available;
absolute historical P&L is not a substitute for anchored budget consumption.
The first new status is account-data-stale/trading_now=false, so it establishes
no trading-readiness claim. Later periodic status is a distinct observation.

## Closed pre-change windows and unchanged losses

[Independent two-window audit](WS_TIMING_TWO_WINDOW_AUDIT.md), with
[31-member original archive](ws_timing_closed_two_window_evidence.zip) and
[manifest](ws_timing_closed_two_window_manifest.json), preserves the fixed
9:15–9:30/9:30–9:45PM windows plus9:47PM publication tail:

- Two windows lost **$2.45/$1.85**, **−$4.30combined**, entirely directional;
  lockedP&L0, fees0,4real fills/8intents/8acceptedorders. Prior+$1.7001 and the
  next ticker's exposure are separate, not used to hide those losses.
- Selected27actualaccount reads max279.354ms;31unique coveringloop intervals
  max1075.9ms. This does not establish all-read/subsecond timing or pooled quantiles.
-28shared-producer source warnings differ from29gap diagnostics. Positive main
  WorkTrace identifies two exact local residences2769.481/3120.903ms. Five other
  known receipts have unknown producers;22overflowed receipts remain unknown.
  Old session numbers cannot be joined across WeatherWS/main readers.
- Finalpublication1393cycles=1383quiet+10reported; all10original reported rows
  match, suppression/buffer/drop0. Omitted slow-span details and coverage limits
  remain explicit. No claim of complete causal attribution or profitability.

## Frozen post-change assignment

Verified Bitcoin runner startup9:49:28.288PM precedes the assigned first two full
windows **10:00–10:15PM and10:15–10:30PM PDT**, with a fixed **10:32PM tail**.
The startup partial9:49:27–10:00PM stays separate. Read-only collector uses the
exact new deployment, original-only parsing, bounded past-time queries and explicit
reader/process/instance/session identity. No source release during collection.

Apply the original3000msactualaccount-resumption/covering-main-loop-lag criterion
with publication/counter/retention checks. Reader-specific source freshness is a
separate surface, not replaced by those account timings. Startup partial already
has a known main2931.768mslocalwait overlapping checkpoint/ledger work; the fix
has not eliminated the issue. Neither this partial nor an offline benchmark is a
full-window improvement or task-completion result.

The [offline callback profile](feed_hotpath_preparation.zip),
[manifest](feed_hotpath_preparation_manifest.json),
[limits](feed_hotpath_preparation_summary.json) and
[architecture analysis](PRACTICE_ADVANCE_ANALYSIS.md) preserve another measured
synthetic history cost. A no-orders early return, pruning or mutable-history cache
would change current save/recheck behavior; none was selected or implemented.

EXEC-DELAY-001 remainsopen; original/inverse/no-trade comparisonunstarted. TJR
authentic-data/cost blocker and disabled paper/live state are unchanged. Next:
finish/audit the assigned post-change windows and attribute any remaining main
backlog without relaxing freshness, accounting or risk rules.

[Machine-readable release receipt](live_mirror_release.json),
[release evidence](live_mirror_release_evidence.zip),
[release manifest](live_mirror_release_manifest.json).
