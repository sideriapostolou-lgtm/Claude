# Independent final review — shard funding and refusal cooldown

Reviewed 2026-10-16. Base: `9110d5d`. Frozen source/test patch: `/workspace/shard-source.patch`.

Requested reviewer configuration, as supplied by the integration owner: `gpt-6-astra`, reasoning `high`. This independent agent actually completed the review and tool-backed checks reported below; the runtime does not expose a separate model-identity attestation to this agent. During final review the integration owner fast-forwarded docs-only base changes to `8aa66a7`; the frozen source/test patch hash remained unchanged.

**Current SHA-256: `c8c2289cee038a32613ede4b9f28c30e38a2a5199ab277ed62078cdcc6579be2`.**

Previous reviewed patch: `5bd2d195dd122d6fbe2e326076a91994dbc84d0bd5ad5d1b6437be12d693ead2`. The final delta adds only two test corrections described below; implementation source is unchanged.

The staged `git diff --cached --binary` matched the respective hashes during both review passes. No unstaged tracked source differences were present. Thirteen staged files, including the new cash helper and tests, were reviewed after the two-file final delta. This review did not alter source/tests, call account APIs, place orders, change production settings, transfer cash, configure allocation, or access research TEST data.

## Verdict

**No blocking defect found in the frozen patch.** The earlier six-decimal parsing, malformed external-order handling, and old-source rollback serialization concerns are addressed. This approves the bounded implementation, not live activation, account funding, or the claim that shard distribution is the proven cause of the observed rejection.

## Independent verification

Using `/workspace/shared/nightcrawler-venv/bin/python` with `PYTHONPATH=src:tests`:

- `pytest -q tests/test_speeddesk_live_cash.py tests/test_speeddesk_live_killpoints.py tests/test_speeddesk_live_desk_property.py`: **57 passed in 29.02s**.
- `pytest -q tests/test_speeddesk_kalshi_client.py`: **96 passed in 0.33s**.
- Separate inline offline fakes/assertions, independent of the new test module: **32 passed**. Covered six-decimal microdollar parsing; rejection of overflow, whitespace, exponent-like/plus/unsupported precision strings; old venue mutation timestamps with fresh local receipt; backwards local clock refusal; changed shard refusal; malformed/unknown-status external rows surviving recent empty scans and clearing only on complete clean scans; actual old Window field-set compatibility from `git show 9110d5d`; no retry before cooldown expiry; successful eligible create at expiry resetting count/deadline; reset surviving checkpoint/restart.

Total independently executed: **153 pytest cases plus 32 additional assertions**. These use fake account/transport implementations, temporary ledgers and local source reads only. Parent owns full-suite/mypy/Ruff release checks; their reported results are not represented as independently rerun here.

### Final test-only delta and exact-hash revalidation

The integration owner reported the first full run as **6,223 passed, 14 skipped, two failed**. Those failures were retained and reviewed, not dismissed as a clean full run:

- `test_refused_lock_is_not_retried_without_resync_and_new_identity[True]` manually reconstructed the live desk but omitted the fresh public-window callback now required after routing metadata is deliberately excluded from persisted windows. The fix calls `desk.on_windows(list(snapshot().windows))` before retry assertions. This models actual fresh discovery: `KalshiAdapter.discover` parses public market metadata and calls `on_windows`; `SpeedDesk.on_windows` installs the fresh windows, refreshes its live snapshot, and forwards the same metadata to `KalshiLiveDesk.on_windows`. `PracticeDesk.add_window` replaces its old window with the fresh one. The existing new unknown-route test still asserts that restored routing is unknown and blocks before this callback. The fixture change therefore represents the real recovery path rather than weakening a safety assertion.
- `test_real_fill_trace_is_once_and_records_checkpoint_without_extra_reads` expected the old account-read sequence. Its expected trace now includes `subaccount_balances` after `balance`, reflecting the required new funding read. No trace-only request or change to financial logic was added. The fake's separate numeric `reads` counter intentionally counts only its pre-existing endpoints; the explicit ordered trace assertion accounts for the new call.

Independent rerun on exact current patch `c8c2289c...6579be2`:

`pytest -q tests/test_speeddesk_lock_send_freshness.py tests/test_speeddesk_readtrace.py tests/test_speeddesk_live_cash.py` — **95 passed in 1.47s**.

This reruns the 51 cash tests already counted above and adds coverage of both complete affected files (44 tests), so it is not 95 additional distinct tests. Across both review passes, 197 distinct pytest cases passed, with 248 successful pytest executions, plus the 32 independent inline assertions. The integration owner's final full-suite rerun remains separately tracked; it was still running when this delta review was completed. **Final verdict remains no blocking defect for the exact current hash.**

## Findings checked

### API identity and units

The helper reads exact `(subaccount_number=0, exchange_index=<market>)` cash via the existing `GET /portfolio/subaccounts/balances` method. USD is a strict nonnegative decimal string with up to six fractional digits; aggregate cents are never substituted. Other subaccounts, missing target shards, duplicate pairs, invalid shape/type, nonfinite amount and absent routing cannot fund the order. Public market `exchange_index=0` is valid; boolean/string/negative/float values remain unknown. Existing V2 writes retain documented `exchange_index=-1` ticker auto-routing.

`list_orders` is also primary-subaccount scoped. Although `_filters` does not set the account, **`KalshiClient._pages` unconditionally adds `subaccount: 0`** before sending every paginated account request. Tests pin this actual wire query. `exchange_index` is omitted deliberately so these primary-subaccount rows cover all shards. Official Get Orders docs say omitted subaccount means all accounts, but that omission does not occur in this client.

Sources: https://docs.kalshi.com/api-reference/portfolio/get-all-subaccount-balances.md ; https://docs.kalshi.com/api-reference/orders/get-orders.md ; https://docs.kalshi.com/api-reference/orders/create-order-v2.md . The fuller API review is `/workspace/shard-api-review.md`.

### Reservations, fills, freshness and external orders

Shard headroom subtracts own outstanding reservations, including the already-reserved intent at final send, and newly booked fill cost plus actual fee debits for the same shard. Unknown commitment routing blocks rather than being charged to another shard. Cancellation requests do not release reservations. A successful complete cash refresh resets aggregate and per-window debit accumulators together. Existing aggregate cash/caps/stops remain additional restrictions.

Cash freshness uses the local successful read receipt; it does not reject merely because venue `updated_ts` marks an old unchanged cash mutation. Parse/read failure invalidates shard availability, and the enclosing reconciliation/error path also prevents new orders through account freshness. Receipt freshness remains bounded by the existing slow-reconciliation check.

External resting orders on any primary-subaccount shard block new creation conservatively. Recent empty scans cannot erase old external commitments. Unknown-status rows with an ID stay cached; invalid/missing IDs mark an unresolved external commitment. Full scans clear the old cache before evaluating returned rows, so malformed/unknown returned rows immediately block again. A non-dictionary page fails at the client/outer reconciliation boundary. Both order reads contribute evidence; a foreign order appearing on the second read blocks admission. This neither cancels nor otherwise manages owner orders.

### Cooldown and durable rejection

Only a definite eligible 4xx with structured code `insufficient_balance` triggers the new 60/120/240/300-second cooldown; uncertain creates retain reservations and remain under the existing recovery rules. Cooldown is enforced before admission and in both ordinary and lock transport guards. Reconciliation/cancellation continue during the cooldown, and successful reads cannot clear it. Only an acknowledged permitted create resets the consecutive refusal count/deadline.

The refusal path calls `checkpoint(durable=True)` after changing the refused intent to terminal and setting the cooldown. `checkpoint` uses SQLite `synchronous=FULL` and one transaction for receipts, state, archive updates when needed, and journal clearing. Crash before this commit leaves the previously durable unresolved reservation; crash after it restores terminal refusal and cooldown together. Existing pre-send journal persistence remains intact. Crash/restart tests exercise both sides.

### Rollback and paper behavior

`persisted_window` removes `exchange_index` from live window parts (including archive chunks), practice state, and pre-send journal windows. Those nested payloads retain the exact old Window field set. The runtime field is reacquired only from fresh metadata for that ticker after restart. Unknown old unresolved liabilities can conservatively block new trades until reconciled, rather than silently selecting shard zero.

Flat paper startup does not construct the client or read shard cash. Existing paper recovery for previous live exposure still reconciles/cancels intentionally. No strategy coefficients, money caps, stop/reset settings, order size settings, transfer endpoint or allocation setting were changed.

## Limits and release conditions

- Public documentation does not establish complete venue hold/collateral semantics or the actual account's shard balances. The balance is a cash ceiling, not a guarantee of order acceptance. Local cash/risk arithmetic remains the repository's existing float convention with a very small comparison tolerance.
- An external manual order can arrive after the last account snapshot. The bounded fresh snapshot, conservative foreign-order gate and venue rejection cooldown reduce this risk; they cannot provide an atomic account-wide collateral reservation against other clients.
- The foreign-order gate intentionally blocks even when the foreign rest is on a different shard. This is conservative availability loss, not unauthorized spending.
- Rollback reads the state without an unknown-field failure, but old source ignores the new top-level cooldown and does not provide shard-aware protection. Rollback must remain PAPER; serialization compatibility is not a claim that old source implements the new safety behavior.
- Fresh market metadata is deliberately not persisted. Restart can temporarily block if historical active commitments lack current routing. Startup cancellation/reconciliation still runs.
- Exact deployed commit, startup/stop/cap retention and natural runtime evidence remain the integration owner's release obligations. No live activation, cash movement, successful account read, accepted live order or profitability is established by this review.
