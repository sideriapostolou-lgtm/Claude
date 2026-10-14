# Quiet callback measurements and remaining execution work

Recorded October 14, 2026, 3:50 PM Pacific (PDT, UTC−7). This is execution evidence,
not a profitable-strategy result. EXEC-DELAY-001 remains open; the subsequent
original/inverse/no-trade experiment has not started.

## Exact release and retained money state

PR #54 deployed commit `89b7b6db8b7c887f8398d604c8b3bfe8ce9d16cc` as
`af3e9f29-2124-4849-8c02-33e91dc46fdb`, SUCCESS at 3:33:15.252 PM PDT.
Polymarket's normal LIVE startup was logged at 3:33:12.604 PM. Bot and recorder
were each online, one replica of one; the recorder did not restart.
[Release, original trace messages and checks](quiet_bins_release.json).

Compared snapshots at 3:32:04 and 3:33:46 PM retain cash $34.9543, filled cost/risk
$0.49, zero reservations, 514 actual fills, $2.27122 fees and cumulative settled
bot P&L **−$14.2971**. Limits remain $10/window, $20 open, $6/day, $10 total and
five-contract clips. Stop latches remain false; no loss budget or resume history
was reset. Attempt counters changed with ordinary activity. These are dated
receipts, not the current balance. Cash is not profit.

The bounded error inspection through 3:36:15 PM found no exact traceback, but did
return application warnings: pump.fun HTTP 403/backoff and its learning breaker,
plus weatherwatch pausing at 3:35:22 PM because its callback queue exceeded
capacity. That is a weather capture gap, not proof of failure of the separate
Kalshi recorder. Healthy platform replicas do not establish complete capture.

## A completed window after the scalar correction

The 3:15–3:30 PM window `KXBTC15M-26OCT141830-30` ran entirely after PR #53's
restart. There were 41 unique intents and 41 accepted order IDs, but only two
actual one-contract fills: Down at $0.59 and Up at $0.043. At settlement:

`$1 payout − $0.633 purchases − $0.0029 fees = +$0.3641`.

This was locked-pair profit; directional residual is floating-point noise. It
does not erase the cumulative losses or establish strategy profitability.
[Closed window receipt](scalar_postfix_window_evidence.json) preserves parsed
events and query limits. An [independent reread](scalar_window_original_messages_check.json)
retains 85 original target order/fill/settlement messages and exact-prefix parser
rules, reconciling identities and arithmetic. It is not full raw market capture.

Four selected diagnostic cycles contain 20 account reads, including two new-fill
cycles. The longest worker-completion-to-controller-resumption gap was
4,757.837 ms. Slow-span coverage left up to 4,206.756 ms unattributed; 81 work
details were omitted. No read/fill detail omission or queried retention loss was
reported. This is selected diagnostic evidence, not a representative latency
distribution or a causal before/after comparison.

## The new bins expose accumulated short work

PR #54 retains bounded occupancy for completed top-level synchronous callbacks,
including those below the earlier 5 ms detail threshold. In cycle 14's fills read:

| Quantity | Milliseconds |
| --- | ---: |
| Worker-completion-to-resumption interval | 1,028.850 |
| Older retained slow-span union | 100.915 |
| Fully contained bins' wall lower bound | 756.031 |
| Whole contained spans' thread-CPU lower bound | 568.158 |
| Unattributed or boundary time | 272.819 |

The slow and all-work populations overlap: **never add them**. CPU is not
prorated across boundaries. Edges, active work, omissions and retention remain
explicit; these early observations are in a partial restart window. This proves
that observed synchronous work contributes to the pause, not that every remaining
millisecond or financial loss is explained.

All 5,471 tests passed, with 14 existing skips; source mypy checked 126 files and
Ruff passed on all four changed Python files. Independent review accepted bundle
`db8dfd78384b96cf1c251cdb2614b628767392263287419a16b8e8a52c8ff135`.
The helper changes observation only; order policy and persistence cadence remain.

## Offline density probe and next correction

The [fakes-only profile](quiet_callback_profile.json) used actual practice and
paper-gated live callbacks, with sockets and thread starts prohibited. Increasing
invented settled history to 200 windows and terminal intents to 316 changed the
unprofiled book/trade-pair median from 71.129 to 128.722 microseconds. Four
PracticeDesk.advance calls per pair repeatedly rebuild membership and scan history.
The exact final script/results and hashes are [archived](quiet_callback_profile_evidence.zip).
The script's post-run import cleanup is recorded; it was not rerun after cleanup.

This is one coupled small/dense sequence with empty historical inventories, no
active maker orders, no arena, no real account reads and no loop contention. It
cannot attribute a production pause or prove a fix. A proposed active-window
cache was rejected: mutable Window.slug and arbitrary public list mutations can
invalidate it without an observable version change. No such cache was implemented.

The next bounded investigation targets already measured checkpoint/panel work.
The live scorecard scans all intents for every ended window. Profile that actual
path with populated fakes; if material, group intents locally within one call,
preserving the existing coverage checks and their ordering. This is a proposal,
not shipped code. Any correction still needs equivalence tests, independent
review, full checks, exact deployment verification and repeated active-window
observations before the execution task can close.

[Resource observations](resource_check_2026-10-14_1528_PDT.json) are 30-second
summaries spanning releases. They cannot identify short stalls, GIL ownership or
throttling. The requested five-second sampling was rejected; the documentation
full-page fetch also failed. No infrastructure or sizing change followed.
