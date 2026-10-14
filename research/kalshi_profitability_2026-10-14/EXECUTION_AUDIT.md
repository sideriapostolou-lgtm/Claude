# Kalshi execution audit, 2026-10-14

Audited checkout: `decf002f68aa706ad09caabb1299e5c69bef59d1` (application code from the deployed speed-part-2 integration). This was a source review and offline fake reproduction: no live order, account credential, Railway variable, cap or resume marker was touched. Live measurements below were supplied by the coordinating session and are distinguished from reproduced software behavior.

## Finding and recommended next change

**The audited pre-patch controller cannot cancel a newly unsafe quote while an account read is in flight.** That version checks cancellation between complete account operations, not during them or between their pages. A slow history request therefore leaves a quote exposed even though Bitcoin ticks are still arriving. This is reproducible without a network connection.

The smallest functional correction is a narrow part of deferred speed-plan step 5:

1. Keep the existing single controller and serialized accounting. While that controller awaits a read-only HTTP worker in `_read`, check its existing cancellation rules on a short bounded timer. Apply the returned account rows only after the complete read succeeds. Do not run a second decision or reconciliation controller.
2. Give authenticated GETs and writes separate kept-alive HTTP connections and transport locks. Keep **all writes** serialized through one lock, including their rate-budget wait and final send guard. Synchronize the shared rate state and global 429 cooldown separately; do not sleep while holding a global budget mutex that would again block the other lane.
3. Keep the current three-second account/feed gates, all reservations, the post-create reconcile requirement, partial-page rejection, conservative cash, ambiguity handling and startup/shutdown behavior.
4. Add request-stage timing so the remaining long cancel acknowledgements can be assigned to worker queue, transport lock, rate budget, HTTP response and event-loop resumption. Report bounded numeric timings and operation names only, never headers or request/response bodies.

This correction can reduce stale-quote exposure; **it is not evidence that the strategy becomes profitable**. It also does not prove that a cancellation with a measured 9.922-second acknowledgement would become fast: that delay starts after the history call has already returned.

## Evidence, with code locations

| Mechanism | Location | Consequence |
|---|---|---|
| Controller is one awaited `step()`; tick wake is consumed after step returns | `src/nightcrawler/speeddesk_live.py:2258-2266` | A wake does not preempt a slow reconciliation. The event loop may be healthy while order decisions and cancellation checks wait. |
| `_read` awaits the whole worker, then checks cancellation | `speeddesk_live.py:612-624` | Mid-read stale feed, cutoff, fair-value change or shutdown signal is not acted on until callback completion. |
| Callback `_pages` reads every page before returning | `src/nightcrawler/speeddesk_kalshi_client.py:226-249` | Two order pages form one blind interval. The comment about prioritizing cancels between reads does not mean between pages. |
| Same transport lock encloses GET and write budget wait, signing, network and JSON parse | `speeddesk_kalshi_client.py:180-224` | Merely scheduling a concurrent cancel coroutine does not fix it: cancel still queues behind the slow GET. |
| One `requests.Session`, retained across calls | `speeddesk_kalshi_client.py:128-137` | Connection reuse already exists. Recommending it as a new fix would be wrong; sharing one concurrently without separate transport/session ownership would be unsafe. |
| Read and write quotas separate, but under same transport lock | `speeddesk_kalshi_client.py:144-155,187-188` | Read quota itself is not charged to writes, but a read sleeping for its quota holds the common lock. |
| Any 429 starts global backoff, up to 30 s | `speeddesk_kalshi_client.py:207-211` | A later cancel can intentionally wait behind shared backoff. Current logs do not prove that this caused the observed long cancel. Preserve rate compliance; make wait observable. |
| Timeout `(3.05,10.0)` | `speeddesk_kalshi_client.py:38,198-203` | The read timeout is an inter-byte inactivity timeout, not a total request deadline. Do not describe it as a hard 10-second end-to-end bound. Shortening it alone would create more ambiguous cancels without solving reconciliation architecture. |
| Full history once/minute, startup and window opening | `speeddesk_live.py:626-636`; constants `:70-74` | Recent-read optimization is already shipped. Every full read still downloads all orders twice; it cannot safely be removed because it discovers old unknown orders and owner activity. |
| Reconcile: orders, fills, orders, positions, optional settlements, balance | `speeddesk_live.py:1400,1428-1429,1457,1498,1505-1507,1559` | All operations are serial; large order pages and historical fills dominate full scans. Two order reads bracket fill reconciliation intentionally. |
| Slow reconcile invalidates account freshness | `speeddesk_live.py:1564-1575` | A reconcile over 3 s keeps new buys blocked, then the next step retries because `account_at is None`. This is correct conservative behavior, not a reason to enlarge freshness limits. |
| Cancel measures `sending` before `_io` | `speeddesk_live.py:1267-1326` | Cancel `send_to_ack_ms` includes worker scheduling, client lock/quota, network and coroutine resumption. It is not pure Kalshi wire RTT. |
| Create measures send inside the final client guard | `speeddesk_live.py:1770-1798`; client `:188-199` | Create's `send_to_ack_ms` excludes most worker/lock/quota time, unlike cancel's field with the same name. Direct comparisons can mislead. |
| Cancel keeps reservation through acknowledged response and 404 | `speeddesk_live.py:1285-1318` | Preserve this. A successful cancel is not proof that no fill raced it. |
| Any create invalidates account freshness | `speeddesk_live.py:1844-1847` | This deliberately stops a second buy until fresh account proof. Removing this is a larger accounting change, not necessary for the narrow cancel fix. |
| HTTP workers are shielded; shutdown waits them | `speeddesk_live.py:606-610,2273-2278` | A coroutine timeout does not stop an in-flight `requests` worker. A proposed timeout/retry must never send duplicate creates or release reservations. |

The count variables `order_reads` and `orders_read` are deliberately different: an attempted second-order read receives a generation before fetching (`:1455-1457`), and the completed generation is published only after reconciliation (`:1495`). Cancellation failures use the attempted generation (`:1308`) and retry only after a later completed generation (`:1003-1004`). Do not merge these names as a cosmetic cleanup.

## What the live measurements do and do not show

The coordinating session reported a 14:00 UTC full reconcile of **16,729.4 ms**: first order list **9,168.2 ms**, fills **5,812 ms**, second order list **1,605.1 ms**, positions **42.2 ms**, balance **64 ms**. The order list had **1,678 rows / two pages / about 1.327 MB**. This is direct evidence that long awaited account callbacks exist in production; it does not isolate server response time from worker scheduling or other local delay.

It also reported a cancellation at **9.922 s**, with accepted create acknowledgements as low as **58-83 ms** and others near **1.9 s**. Cancels are checked after each callback returns, so the preceding history callback cannot by itself explain the cancellation's recorded acknowledgement interval. The code supplies no separate lock-wait, rate-wait, worker-queue or transport timer. Attribute this tail as **unresolved**, not automatically “Kalshi is slow” or “history is slow.”

The speed-plan estimate of sub-second end-to-end behavior remains unverified. The previous plan explicitly classifies off-loop reconciliation as medium/high risk and warns against parallel writes. The recommended narrower change retains serialized writes and accounting.

## Local implementation and validation

The authorized local patch implements the narrow correction in `speeddesk_live.py` and `speeddesk_kalshi_client.py`: cancellation checks every 50 ms while a read worker is pending, independent retained GET/write connections, serialized writes, a brief shared rate-state lock, and shared 429 cooldown that an already-running success cannot erase. The same controller applies all account results; new buys still require complete fresh account proof. Shutdown drains any in-flight write first, cancels known bids before waiting for history GETs, then drains those workers and reconciles. Worker failures remain tracked/observed.

Diagnostics directly measure worker-queue and event-loop-resume delay by operation in the existing `loop` summary, plus lock wait, quota wait, signing/guard preparation, HTTP and decoding in the new `requests` summary. Samples are bounded; no URL, body, signing material or exception text is collected. Existing cancel `send_to_ack_ms` retains its historical meaning, so compare it with these components rather than relabeling the old field.

Validation before the coordinating session's full repository run:

- Broad existing live/client suite plus the initial new cases: **603 passed in 120.17 s**.
- Final focused client/read/timing/stale-bid/new-response/adversarial suite, including two additional partial-fill races (successful cancel and 404): **126 passed in 2.23 s**.
- Mypy: **122 source files clean**. Ruff: both changed source files and both new cancellation test files clean. `git diff --check` clean.
- The independent adversarial reviewer added the three cases in `test_speeddesk_cancel_adversarial.py`: stale resting response after cancel acknowledgement retains reservation; failed cancel cannot retry without new order evidence; cancelled controller shutdown cancels its known order while GET is still blocked.

These are offline correctness results, not production latency or economic results. No runtime setting, cap, budget anchor, order-selection rule, market-data threshold or Polymarket file changed in this execution patch. The coordinating session owns full validation, safe-minute shipping and deployment verification.

## Offline reproduction

Two temporary tests, using only fake account responses and throwaway in-memory signing keys, reproduced the old behavior before the correction:

1. Create one fake resting quote, block its next account read, advance fake time until Bitcoin/books are stale, and explicitly wake the controller. No cancellation is attempted until the read is released. Reservation remains present, and no second create occurs.
2. Start a blocked GET on the authenticated client, then attempt cancellation from another worker. Cancellation does not reach the fake HTTP transport until GET releases its lock.

Baseline command (the temporary reproduction is retired; the new regression tests require the corrected behavior):

```text
PYTHONPATH=src:tests /workspace/shared/nightcrawler-venv/bin/pytest -q research/kalshi_profitability_2026-10-14/execution_reproduction.py
```

Result on the audited source: **2 passed in 0.50 s**, Ruff clean. Their corrected expectations are covered by `tests/test_speeddesk_cancel_responsiveness.py`; independent cancellation/reservation/shutdown attacks are in `tests/test_speeddesk_cancel_adversarial.py`. No intentionally failing baseline tests remain in the checkout.

## Required fake tests for a correction

- With a GET blocked, a stale feed, fair-value drop, cutoff, owner mode-off or stop signal must send the appropriate owned cancellation before GET completes. No create may run while account evidence is pending.
- If the GET is the second page, all-or-error pagination remains unchanged. A failed last page must never publish a partial account or release a reservation.
- Two concurrent writes must remain serialized. The create final guard runs after quota wait, and a move during the wait still rejects before transport. No parallel creates under any scheduler interleaving.
- A fill racing a successful cancel or a 404 must be booked exactly once from the real fill response; reservation remains until consistent order/fill/position proof. A stale read showing resting after cancel acknowledgement must not send cancel storms or free money.
- Shared 429 cooldown applies to both read and write lanes. GET saturation must not consume write quota; concurrent lanes must not exceed existing 10-read/5-write rolling limits. Validate with a synchronized fake clock and no network.
- Cancellation exception, timeout or 5xx retains uncertainty and reservation. No repeat create; a retry of cancellation still requires the current generation/proof conditions.
- Shutdown during a GET waits or cancels/drains every shielded worker safely, closes both sessions only after workers end, and reconciles any fill that raced shutdown. Startup still cancels unknown prior owned orders.
- Numeric timing breakdown must cover successes and failures and distinguish the actual transport start from scheduling/lock/quota wait. No secret-bearing fields, raw URLs, bodies or headers may enter logs.
- Run existing crash/killpoint/property, late-fill/full-scan, stop/balancing, send-guard and practice-isolation tests, then the full required pytest/mypy/changed-file Ruff checks before a source push.

## Changes to avoid in this patch

- Do not relax freshness, hide full-history scans, treat missing rows as proof, clear uncertainty, or relax pair/loss limits to get more orders.
- Do not blindly retry a timed-out create, or introduce an async timeout that forgets a still-running thread.
- Do not move accounts/regions, raise caps, reset budgets, add market subscriptions, change maker/taker selection, or touch Polymarket.
- Do not imply that removing late cancels or reversing a losing signal establishes an edge. Economic evaluation needs independent periods and actual executable prices/fees/fills.
