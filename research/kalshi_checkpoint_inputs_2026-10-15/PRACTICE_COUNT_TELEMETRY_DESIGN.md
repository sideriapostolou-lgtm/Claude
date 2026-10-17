# Practice retained-size measurement: design only

Private read-only design,2026-10-16UTC. No production/account call, protected TEST data read, volume read, environment access, source/test edit or live observer added. Source remains frozen through00:32tail. This is a missing operational export, not evidence of the actual retained size.

Existing `speeddesk.py:588–623` already constructs checkpoint state with `model`, `window_evidence`, and reports. `speeddesk_model.py:1208–1236` materializes retained windows, closed Settlement rows, orders, inventory and other history; `speeddesk_metrics.py:200–204` returns evidence including fills. The practice heartbeat `speeddesk.py:663–669` strips reports. Current saved FRESH_STATUS is the separate real companion status and cannot identify the practice collections. Practice scorecard settled-window counts are filtered/traded cohorts; real companion195 settlements is not practice C. No inspected current status proves the required D/W/C/F.

## Smallest future count-only export

At the existing checkpoint preparation, derive scalar counts with len() from the already-built state, without additional history iterations, copy/serialization, volume read, or clock call:

- W = len(state.model.windows): ALL retained windows, including unresolved/future/carry-over, across venues.
- C = len(state.model.closed): ALL retained Settlement rows, including duplicates; not today's scored count.
- F = len(state.window_evidence.fills): retained detailed observation fills; this is not real-account fills or all lifetime fills.
- D = max(0,(UTC date(now)−UTC date(started_at)).days): completed-date summary loop count from daily_reports. Reuse those existing loop-bound dates if practical. Separate reports_retained=len(state.reports) because old stored report keys need not equal D.
- Useful constant-time companions: len(model.orders), len(model.inventory), len(evidence.seconds), len(evidence.fresh_seconds), len(evidence.first_seen), len(model.bitcoin.prices), len(model.bitcoin.first_prices), and len(existing pending) **at explicitly named prep stage** if needed. Do not emit IDs/outcomes/financial values.

Per-venue W/C/F cannot be derived from total len() without a scan or new maintained counters. If useful, len(windows) at each EXISTING venue-summary list construction `speeddesk.py:402–408` yields that call's eligible ended-window count (under its existing per-row clock reads), not all retained per-venue W. Label it accurately; never add a full grouping walk just for telemetry. Existing D+1 summaries ×V is only a conversion-count model for stable clocks/no hooks; don't report it as measured work.

Expose only last-successful-checkpoint counts and its existing now/updated_at in the existing diagnostic heartbeat. Publish after current mirror success/last_checkpoint update; retain previous snapshot on commit/pending-log/mirror failure, never claim uncommitted/mirror-failed state successful. Avoid adding these observer fields to the persisted financial/model state or changing schema/save cadence/durability/receipt order merely to export counts. The evidence state contains aliased fill containers: take scalar len() at prep immediately, not after await/mutation. All operations are synchronous today; do not introduce a worker reading mutable practice collections.

State byte count is optional: `_atomic_json`70–78 already creates one compact JSON string and writes it. A future approved observer could reuse the existing string/write return length instead of another dumps/hash/stat/read. Default ensure_ascii=True means encoded content ASCII; count equals UTF8 byte count. Record previous successful mirror bytes externally/next heartbeat to avoid self-reference. Do not change its return/error behavior without explicit tests. Minimal D/W/C/F export needs no byte instrumentation.

## Fastest honest runtime demonstration

First obtain one permitted count-only operational export of these exact paths from the **practice** saved state/KV, or add the above tiny observer in a separately reviewed source scope after capture. Current connected tools/status do not provide that export; no further inference from real total or protected TEST can fill it. A one-time authorized local-to-production helper should print only scalars and snapshot timestamp, never raw outcome rows, environment or credentials; no such helper is executed here.

Then freeze synthetic controls with precisely those sizes and benchmark exact PR67 before/after separately using the existing no-network harness and hard resource bounds. This is size-matched synthetic evidence, not actual production runtime. For actual runtime evidence, compare existing practice checkpoint spans in declared before/after windows with observed collection counts, workload/clock/receipt differences disclosed. Post-release spans alone cannot establish counterfactual speedup or a profit gain. No broad test rerun or source change is warranted for this design.
