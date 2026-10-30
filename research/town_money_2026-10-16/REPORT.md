# Town money loading and workflow release — October 16, 2026

## Problem and implementation

The owner's Kalshi balance/profit could wait on the full company page, whose ledger assembly is serialized. In a bounded two-hour Railway sample read about11:29 AM PDT, `/api/page` had seven requests across three populated buckets. Returned bucket p95 latencies included15,881ms and14,472ms; these sparse bucket statistics are not a full request distribution. Source review also found that a missing/malformed practice report could hide the independent real Kalshi status panel.

Authenticated `/api/town` now reads the real display mirror directly and independently of the practice/full-page path. It validates the whole bounded real book before calculating profit or truncating lists. Browser polling is single-flight,5s cadence/8s timeout for money and30s/20s for the full company page. Once available, the direct money stream owns Kalshi fields; a later full-page reply cannot overwrite it with an older checkpoint. Original source ages remain unchanged, and401 clears private data and invalidates older in-flight responses.

The interface has a navy/teal campus, larger cutaway workstations and a visible Observe → Check → Order → Settle flow. Checks repeat throughout; an order is not a fill and a fill is not profit. Stage labels and the current waiting reason lead; characters remain display guides. The layout separates account cash, Pacific-day settled bot result, validated cumulative bot result, recorded gross fill cost and reservations. Cumulative losses remain visible. Polymarket stays separate; practice never supplies real numbers or growth. Exchange-index funding has its own clock and cooldown expiry; no missing account-reconciliation time is fabricated.

## Verification

- Final frozen-source full suite: **6248 passed, 14 skipped in 295.10s**. The14 intentional skips are network/performance/cache-dependent checks; no live-order test was enabled. An earlier run loaded a pre-edit copy assertion while edits were finishing and had one failure; the final frozen-source run is green.
- Mypy:134 source files clean. Ruff:all18 changed/new Python files clean.
- Independent money/auth/transport review: no release blocker;144 targeted tests passed.
- [Browser receipt](BROWSER_CHECKS.json): local signed-in simulation, **all account figures synthetic**, no browser errors. Verified fast money while fullpage is blocked, stale cash independent of current profit, incomplete books hiding profit while keeping valid cash,401 clearing/recovery, negative cumulative result from the validated book rather than the injected wrong panel total, separate Polymarket details and no horizontal overflow at320×640,390×844 and1440×960. Focused station controls do not obscure the phone's central scene.
- Local source experiment: a500-settlement774,754-byte book built the fast response in63.9ms. This is not a production latency measurement or a service-level guarantee. The8MiB saved-source cap still returns unknown for oversized records.
- Diff whitespace/secret scan: clean; an unchanged synthetic credential fixture was identified and excluded from claims about new credentials. No actual credential was read or added.

## Scope and remaining evidence

This changes read-only presentation and data transport. It changes no trading rules, caps, stops, reset/resume tokens, Railway variables or paid services; no direct order/transfer API action was issued. The shared app was restarted under the owner's standing release approval after a safe-minute merge and its startup was verified. It does not demonstrate a strategy improvement or profitability.

Production release/endpoint/auth/health evidence is saved in [RELEASE.json](RELEASE.json): PR74/e72f4b8b/a717faa1 reached SUCCESS at11:50:25.620AM PDT; both services online, normal Polymarket LIVE startup and Kalshi prior losses/caps retained. New unauthenticated route returns401 and health returns200. No successful authenticated money-route latency buckets were returned by the bounded check. A signed-in production account session is not currently available to this worker; local simulations do not prove what the owner's current account page renders or its authenticated request latency. The complete operating handoff, raw-state/backups/capacity concerns, service registries and owner acceptance of the whole-town product remain on their existing unfinished records. The unwanted TJR reminder stays disabled and research stays last.
