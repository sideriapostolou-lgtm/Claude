# Real versus practice maker fills: evidence and bounded diagnostics

Prepared October 15, 2026, 7:40 PM PDT (October 16 UTC). Release and forward evidence are separate requirements; see RELEASE.md when available. **No trading policy or simulation-fill rule changes. Profitability remains unproved.**

## What the old window establishes

Frozen `KXBTC15M-26OCT152030-30`, October 15 **5:15–5:30 PM PDT**, with separate tail to 5:32. Exact running source `0520f7468174d6a37f0ee7dfe64284b1a6921439`, Railway `d32c256b-618d-4927-b44a-f182d569977b`. The [previous release report](../kalshi_checkpoint_inputs_2026-10-15/RELEASE.md) preserves the original seven actual maker fill receipts on six orders: Up10 cost$4.09, Down10 cost$5.80, fees$0, official YES, **+$0.11 matched / $0 directional**. Main practice and live practice twin each recorded zero fills. This is not proof that practice should have filled.

A newly recovered deployment-scoped native query contains 100 parseable practice-twin events: **50 rests, 50 cancels, zero fills**. Independent split queries return73+27 exact rows; their union agrees in every timestamp/message pair, without overlap/additions/omissions. These unsaturated bounded logger queries do not certify complete raw feed, account or queue coverage.

Exact decision time, side, price, size, kind and fair-value joins map all50 twin placements uniquely to50of53 real intents. Three real intents have unknown twin-copy outcomes; all53 real acknowledgements are known, and one of the three real orders filled Down3@55c. The old source suppresses practice skips, so absence cannot distinguish a skip, exception or missing logging. All50 recorded twin orders were cancelled:39reprice,9venue-feed-gap,1Bitcoin-stale,1cutoff.

| Real filled quantity | Practice twin | Recorded cancellation UTC | Cancel minus venue-reported first fill |
|---|---:|---|---:|
| Up5@40c, split1.04+3.96 |8779|00:15:16.912989 / feed gap|−2.204739s|
| Down5@59c |8782|00:15:57.2089145 / reprice|+0.0782385s|
| Down3@55c |unknown placement|unknown|unknown|
| Up1@49c |8788|00:17:40.7557288 / reprice|+1.7294548s|
| Up4@40c |8793|00:18:10.2127998 / reprice|+0.7963197s|
| Down2@60c |8797|00:18:23.2801375 / reprice|+0.0142355s|

Five of six filled orders, or six of seven fill receipts, now have directly observed twin placement/cancellation associations. Venue fill clocks and local cancellation clocks are different populations; the differences above do not establish public-print arrival timing or fill causality. The first twin disappeared before the real fill. The others still need accepted-print, activation, queue and callback evidence. All17 earlier truncated81,920-byte combined-practice JSON strings remain invalid and unrepaired.

## Why an immediate cancellation-policy change was rejected

Current source deliberately uses approximate window-wide twin cancellation except for pull-control kept bids. One real-side reprice can therefore cancel its sibling twin. A synthetic case demonstrates queue loss/reset and a different later simulated fill; it does not prove historical P&L. Conversely, changing only to identity-specific cancellation can leave a practice order orphaned after a real30-second expiry because the practice model has no corresponding default TTL. The original behavior is documented, not a newly proved regression. Neither rule is changed here.

The first twin's feed-gap cancellation also does not prove a required real cancellation was missed. Real cancellation later checks then-current recovered books; no explicit contract requiring an irrevocable cancellation after every recovered transient gap was found. The historical intervening snapshots and loop times are unavailable. Do not change live cancellation rules or manufacture practice fills from account receipts to force agreement.

## What the new records add

`speeddesk_twin_trace` version1 records actual real/client↔twin identities and placement skips; initial queue and activation; cancellation parent/scope and pre-removal queue where the existing loop exposes it; and exact matching current or observed-terminal twin state when a new real fill is reconciled. Unknown, evicted or restarted mappings remain unknown. An absent order after a partial IOC fill is `terminal_after_fill`, with unknown residual, not a fabricated full fill.

Real-fill observations explicitly use `fills_batch_return`, `snapshot_time_exact=false` and `snapshot_during_reconcile_not_venue_fill_time`. Initial queue is never substituted for current queue. Whole-window/global events without known parents retain that limitation. This phase does not log every public trade or determine whether accepted prints depleted the queue.

The helper is optional, session-only and bounded:128 staged rows,128 diagnostic rows already added to pending and retained behind a failed checkpoint,256 terminal entries,40 scalar fields per row,128characters per text field, finite numeric values and explicit drop/eviction/failure counts. A complete batch is validated before insertion into authoritative pending receipts. Guarded extraction, callbacks, publication and status failures cannot change the underlying financial action. No new save trigger, persisted financial-state/KV schema, clock read on the financial path, latest-event displacement, per-trade hook, order scan or network operation. One additional UUID identifies the diagnostic session. Existing real/practice orders, cancellations, fills, fees, stops, caps and budgets are unchanged.

## Verification and cost

Frozen integration base `ef1f3d38a49332bb19c69a8b1770abc56d83eb56`; source hashes and exact complete patch are in the archived implementation manifest. Independent review accepted the exact three-file patch after **72 focused checks:48 independent and24 implementation cases**. Seven scenarios compare complete financial/twin/account/regular-receipt state against the frozen baseline, with tracing enabled/disabled and injected failures. Five initial malformed-result failures are preserved, corrected and tested: bad iterator, unencodable object, missing/nonfinite timestamp and invalid status shape. Removed-partial-IOC semantics are tested separately. Full repository checks and exact deployment/runtime remain root-owned gates, recorded in RELEASE.md rather than inferred from this review.

[Local overhead measurements](OVERHEAD.json):32 interleaved enabled/disabled fake-account runs per scenario, timing step/action/checkpoint with identical existing local SQLite/fsync and serialization work. Logging output is disabled; constructor/close and log-handler IO are excluded. The quiet scenario includes an initial placement followed by a quiet step. Median wall ms:quiet7.741→8.023;cancel6.559→6.720;partial-fill8.601→8.979. Enabled p95 respectively8.945/7.443/9.342ms; disabled11.063/7.495/9.278ms. Noise and shared-host timing prevent a universal regression or improvement claim. These are not production network/decision latency. New payload bytes per scenario are582/1,205/1,250; SQLite indexes/receipt hashing/log envelopes are additional.

10,000 synthetic cancellation observations under tracemalloc take409.037ms wall/408.803ms CPU, peak259,560bytes, retaining128pending/256terminal and explicitly reporting9,872drops/9,744evictions. This pressure run establishes bounds, not acceptable loss of future evidence. Its retained batch serializes68,225payload bytes. Measured production CPU/storage/cost remain unverified; daily totals cannot be inferred without event rates. Preserve separate recorder storage/retention obligations.

## What remains open

Ship only after full pytest, mypy, changed-file Ruff, credential/diff scan and exact-byte review; verify the exact auto-deployment, Polymarket startup and preservation of all losses, controls, reservations and distinct probability histories. This patch does not change the probability observer's input/source fingerprint and must not reset its current epoch.

Then predeclare the earliest eligible complete future quarter-hour with at least120seconds after actual readiness; freeze source/settings through its separate two-minute tail. Report every real/practice result and missing record without substituting a later winning window. Check new trace-session identity, drops/failures and real-fill link coverage. A clean release or one profitable window does not complete EXEC-DELAY-001 or establish an edge.

Next causal evidence still needs accepted/rejected public prints and queue progression at the actual decision/cancel/reconcile boundary. Full account-scan delay/count-only exports, recorder raw-volume verify/retention fit before October20/measured cost, and operating takeover remain open on existing records. TJR/MNQ stays last; FamilyA/toxicity/MNQ TEST remain unopened; the separate reclaim confirmation is already consumed and is not retuned. No financial limits, loss budgets, stops/resume tokens, Railway variables, orders by the operator, paid services or storage changes.

## Reproduce

[EVIDENCE_MANIFEST.json](EVIDENCE_MANIFEST.json) lists15 original evidence/review files and ordered base64/XZ text parts. Concatenate parts, verify the combined hash, base64-decode, `lzma.decompress`, parse JSON, and verify every `files[].utf8` hash against its safe relative name. Original bytes roundtrip exactly. The earlier status-tail reconstruction remains distinct from its later full-event supplement.

Independent differential and cancellation-proof harnesses are saved as `.py.txt`; copy to a scratch directory with their original `.py` names, supply frozen baseline controller bytes from the integration base as `baseline_speeddesk_live.py`, and use project `src`/`tests` on PYTHONPATH. The cancellation harness deliberately retains the stronger-contract failing assertion; it is a research counterexample, not a passing app test. The benchmark is the original exact-run script; adjust only scratch checkout/output paths when reproducing. Fakes only; never enable local live variables or use actual keys.
