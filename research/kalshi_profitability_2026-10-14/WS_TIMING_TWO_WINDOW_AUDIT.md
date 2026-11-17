# Independent closed two-window audit

The predetermined **04:15–04:30 and 04:30–04:45 UTC** windows on 2026-10-15 both lost: **−$2.45 and −$1.85**, totaling **−$4.30 directional PnL, $0 locked gain, and $0 reported fees**. Both losses remain in the result. The collector completed its fixed 04:47 publication tail and stopped at 04:47:18.296358 UTC. This closes this finite evidence capture, **not EXEC-DELAY-001** or the source-freshness problem.

## Evidence receipt

Immutable input `/workspace/shared/ws-timing-two-window-audit-input.json`: **10,266,692 bytes**, SHA256 **`fd12946730ac7847d4436caa99d6de94f3e86d370e226d03c97ecde43fb915ba`**, identical to the root's `ws-timing-production-closed-complete.json`. The parser required `complete=true`, collector jobs stopped, the 04:47 tail present, contiguous query ranges, and the exact deployment cohort before creating this copy.

Thirteen original queries contain **486 unique rows**, no duplicate rows, no parse errors, and no API errors. Per-query counts are 61, 59, 74, 21, 32, 18, 16, 42, 20, 20, 26, 18, 79, all below 500. Every saved query-artifact hash matches. The first eight original responses exactly match the earlier immutable first-window input, and its financial result remains unchanged. No production calls or repository edits were made by this audit.

All observations belong to deployed source **`10f7f9d88a9acd51aba041345d569cd9972c4b6c`**, deployment **`86dabbf2-bedb-4686-b6ed-857955e0b521`**. Interpretation-source hashes are computed from `git show 10f7f9d:<path>`, not a later checkout. PR58's subsequent merge/deployment is outside this evidence. Startup before 04:15 and the 04:45–04:47 tail remain separate populations except where explicitly used for covering intervals, financial publication, and counter accounting.

Independent reparsing agrees with collector originals: first window 161 raw versus 146 retained derived rows, second 126 versus 111; in each case the only difference is 15 intentionally excluded `speeddesk_status` rows. No other original event is missing or extra. The collector-derived snapshot hash is `fd85329a3bbf9fcddb4f790046681df88faebc04abfb997c3ba4f80c0976e063`. Unique heuristic warning/diagnostic matches are not treated as proof of producer identity.

## Real financial cohorts

| Fixed UTC window | Exact ticker | Intents / accepted orders | Real fills | Final position | Cost | Fees | Locked | Directional / total |
|---|---|---:|---:|---|---:|---:|---:|---:|
| 04:15–04:30 | KXBTC15M-26OCT150030-30 | 5 / 5 | 2 | Down 5, up 0 | $2.45 | $0 | $0 | −$2.45 |
| 04:30–04:45 | KXBTC15M-26OCT150045-45 | 3 / 3 | 2 | Down 5, up 0 | $1.85 | $0 | $0 | −$1.85 |
| Combined | Both fixed tickers | 8 / 8 | 4 | Separate settled markets | $4.30 | $0 | $0 | **−$4.30** |

First-window fills are down 1.22 and 3.78 at $0.49. Second-window fills are down 4.08 and 0.92 at $0.37, both on durable client `nc-speed-d341b9be8b8a4713a9cf70ee7d06728e` and accepted order `01a13dd3-14b0-74cf-8df8-8d9940adf95f`. All four unique fills join to the correct durable client and accepted order; accepted-client identity, intent side/price, and aggregate quantity within the intended five shares are checked. No conflicting fill IDs appear. Both markets settled up, so each payout and paired credit is zero. Decimal cost/fee/PnL recomputation and settlement quantities/decompositions agree.

First settlement log: `04:30:05.506879203Z`, venue time `04:30:04.136249Z`. Second: `04:45:08.294392432Z`, venue time `04:45:04.131845Z`, observed at `04:45:06.256811Z`. Worst settled fixed-window result is **−$2.45**. Both were unpaired directional exposure; neither locked a positive return. Eight cancellation observations are retained; reservation-preserving 404/requested outcomes are not interpreted as fills or premature reserve releases.

The prior ticker `KXBTC15M-26OCT150015-15` settled **+$1.7001 locked** at 04:15:07 and is excluded. The following ticker `KXBTC15M-26OCT150100-00` acquired up 5 at $0.46, cost $2.30, in a fill logged 04:45:34; it is also excluded. These boundaries prevent cumulative snapshots from substituting for the two exact ticker cohorts.

At `04:46:48.535506513Z`, the cumulative status reports **PnL −$13.642000000000003**, cash **$33.7994**, cumulative fees $2.70752, 631 fills, locked $6.198809260739254 and directional −$19.840809260739256. These are historical totals, distinct from fixed-window **−$4.30**. Historical worst remains −$2.9792. Open cost/risk $2.30, reserved $2.45, one position and one open order belong to the next market, not the closed windows. No stop-budget failure is inferred from absolute historical PnL; consumed resume anchors are not exported by this evidence.

Thirty-two status observations from 04:15 through the retained tail show unchanged effective caps: window $10, open $20, day stop $6, clip 5, total stop $10. Authentication and fee precision remain verified; real orders available; total/day latches false; integrity error null; cleanup pending false. These are observations, not a continuous state proof. Existing exception-lock and reservation semantics are retained; the audit supplies no basis to raise caps or alter policy.

## Account resumption and publication coverage

First-window reported cycles 114/123/265 contain 16 reads. Second-window cycles 712/715 contain 11 reads. Across **five unique selected cycles and 27 reads**, all required worker/scheduler/wrapper marks are present, with zero reads omitted. Actual worker-completion→coroutine-resumption maxima are **248.933 ms** in the first window and **279.354 ms** in the second. The combined maximum is cycle 715 `balance`: completed offset 467.203 ms, resumed 746.557 ms, wrapper returned 746.711 ms. Worker completion means the entire client callback, not first-byte receipt. Cycle 712's 3672.095 ms elapsed duration is not a 3672 ms resumption stall.

Quiet cycles have no per-read detail. Source `speeddesk_readtrace.py` emits failed/new-fill cycles or cycles ≥3000 ms. Original report counts reconcile at each relevant status cohort:

| Status log UTC | Begun cycles | Quiet | Reported and original rows | Suppressed / buffered / dropped |
|---|---:|---:|---:|---:|
| 04:14:43 | 101 | 98 | 3 | 0 / 0 / 0 |
| 04:29:44 | 699 | 693 | 6 | 0 / 0 / 0 |
| 04:30:45 | 740 | 732 | 8 | 0 / 0 / 0 |
| 04:44:48 | 1306 | 1298 | 8 | 0 / 0 / 0 |
| 04:45:48 | 1349 | 1339 | 10 | 0 / 0 / 0 |
| 04:46:48 | 1393 | 1383 | 10 | 0 / 0 / 0 |

All are enabled and completed counts equal begun counts. The three startup reports and two after-04:45 reports are retained for publication accounting, excluded from selected fixed-window read maxima. Under these observed counters and selection rule, there is no evidence of a missing ≥3-second account-resumption cycle across the covering cohorts. This does not recover a distribution of quiet reads or establish a permanent latency bound.

There are **31 unique reset loop-stat intervals** covering both windows, after deduplicating the shared boundary interval. Each window has 16 covering intervals, 14 wholly contained. Overall coverage is approximately 04:14:42.791752–04:45:48.132425; status construction/reset timestamps are approximate boundaries. Covering-interval lag maxima are **1075.9 ms** first and **866.3 ms** second; overall **1075.9 ms**. No reported metric reaches its 8192 sample cap. Boundary intervals are retained, so these are conservative covering-interval populations, not exactly clipped point samples. No medians/quantiles are pooled and no cumulative maxima are subtracted.

Whole-cycle work-detail omissions are 30 first-window and 37 second-window (67 across distinct cycles). Read-resumption detail omissions are 0 and 1 respectively; that single omitted detail belongs to cycle 712's 184.426 ms balance-resumption interval. All work queries are enabled; neither slow-span nor full-bin retention loss is reported. Second-window cycle full-bin coverage is 117/117 and 26/26, with synchronous lower bounds 2472.915 and 591.244 ms. These overlapping work scopes and nested spans are not added to one another. Uninstrumented waiting, boundary time, and quiet-span CPU limits remain.

## Source age and identified local residence

Across log timestamps in [04:15,04:45), there are **36 shared-logger gap warnings**: **28 source-age**, three market-set changes, five timeouts. Source domains are seven snapshot-network, twenty delta-network, and one book-engine. Separately there are **80 timing rows: 51 periodic samples and 29 rejected-message diagnostics**. Of rejected diagnostics, two have known main-reader receipts, five have known receipts but unidentified producers, and **22 are unknown from metadata overflow**. These warning and diagnostic populations must remain distinct.

The one book-engine warning is 3.000 s rounded; its candidate diagnostic has sending age 2.993313 s and engine age 3.000313 s. This illustrates why the engine and sending fields must stay typed and separate. Its unknown receipt and old shared-logger context do not support a stronger causal attribution or exact cross-row producer join.

`WeatherWS` inherits the deployed base receiver and shares its logger; old session numbers are instance-local. Therefore the 28 source warnings are not 28 proven BTC warnings. A missing `local_work` field does not identify Weather. The only positive main attribution here is a valid `local_work` query under verified main-only wiring. Later producer labels cannot retroactively resolve old rows.

| Identified main diagnostic log | Exact native residence | Accepted→apply interval | Full-bin sync lower bound | Full bins retained | Slow overlap/details omitted |
|---|---:|---:|---:|---:|---:|
| 04:22:44.832596083 | 2769.481 ms | 2769.534 ms | 2157.406 ms | 88 / 88 | 60 / 52 |
| 04:35:42.848563523 | **3120.903 ms** | 3120.947 ms | **2335.513 ms** | 99 / 99 | 54 / 46 |

The second original event is `b0581f983a25fc2b3df22d6045617c0ef1e0dfd4f31d79c82a9693a5c90e57e7`, ordinal 172371. Complete-message acceptance monotonic 3570045.958900996 and successful public receipt 3570049.079803811 establish **over three seconds locally after protocol acceptance**, independent of provider timestamp interpretation. Sending age at apply is 3.260336 s; engine age 3.267336 s. Return→apply is only 0.028550 ms. This excludes earlier kernel/TLS/network/provider waiting, and the remaining wall-clock age is not proven network delay.

The second interval fully contains a **520.629 ms live checkpoint / 305.329 ms thread CPU**, including **249.122 ms live mirror / 188.193 ms thread CPU**. It also contains practice checkpoint/ledger work and a feed-status callback that performs a practice checkpoint. Slow-span union coverage is 1735.849 ms; independent full-bin synchronous coverage is 2335.513 ms, leaving 785.434 ms unattributed/boundary. Contained single-bin top-level CPU is 696.444 ms under its explicit omission rules. Nested costs and alternative coverage measures are not additive; the omitted 46 details prevent exhaustive named attribution.

These two incidents positively establish substantial main-reader buffering overlapping synchronous main-loop work. The second fixed-window incident independently supports the narrow mirror-cost target previously seen during startup. It does not show that mirror work is the sole cause, quantify a scheduler amplification effect, or prove the proposed serialization change fixes freshness. The five other known incidents, periodic cumulative maxima, and overflow counters remain producer-limited; they are not pooled into a BTC causal estimate.

## Disposition

The closed capture preserves both losing windows and shows materially shorter selected account resumption than the original coarse starvation symptom, while **source freshness remains unresolved and known main-reader local residence exceeds three seconds**. Existing stale-data guards remain necessary. The mirror change is a focused reduction of demonstrated synchronous work with offline validation; any benefit requires a separately frozen post-change capture with the new explicit producer identities.

Machine-readable audit: `/workspace/shared/ws-timing-two-window-audit.json`. Reproducible parser: `/workspace/shared/ws-timing-two-window-audit.py`. The first-window immutable input, JSON and report remain unchanged. No production configuration, financial policy, order action, release action, or source edit was performed by this audit. There is no retrospective shadow producer inference, no counterfactual profitability estimate, and no claim that EXEC-DELAY-001 is cleared.
