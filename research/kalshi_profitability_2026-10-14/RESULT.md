# Profitability investigation, October 14

**No profitable replacement strategy established. Execution/data defects were reproduced and corrected;
the first deployment exposed an additional arena capacity problem. Reversing the signal remains untested.**

PR #45 deployed as `18e180f` at 14:50 UTC. Its new diagnostics show local scheduling delays and persistent arena
overflow, so that deployment did not establish usable practice coverage. The bounded follow-up increases the
encoding CPU budget for real-depth books and removes streaming JSON overhead; exact running commits and
production outcomes belong in the newest WORKLOG receipts, not a claim that local benchmarks prove success.

The independent [loss audit](LOSS_AUDIT.md) reconciles 29 historical windows to **-$11.9154**. Buying both sides
was already common (28/29 windows), yet cheap maker fills were often on the eventual losing side. Successfully
matched maker pairs were profitable in hindsight; that subset cannot be selected in advance from these rows.
Locks reduced the loss on the same fixed maker inventory by $0.8246, so simply removing them is unsupported.

The [execution audit](EXECUTION_AUDIT.md) reproduced a stale-quote cancellation blackout during a slow account
GET. The correction keeps accounting single-writer, lets cancellation checks proceed during reads, and gives
GETs and serialized writes separate connections while preserving rate limits and all new-order admission rules.
The [arena repair](ARENA_FEED_CHECK.md) retains delayed frames and event order rather than losing evidence or
silently treating gaps as fills. Strict missing/late-data invalidation remains. Production verification belongs
in the newest WORKLOG receipt; a local performance test alone cannot establish live speed or coverage.

The fixed 14:05-14:25 UTC log capture contains 50 accepted-order receipts and 11 fill receipts. Across 49 timed
acceptances, median decision-to-ack was 121.6 ms and p95 1.690 s; 51 cancellation receipts had median 487.9 ms,
p95 6.703 s and maximum 9.922 s. Cancel timing includes scheduling and client work, not just exchange response.
[live_audit.py](live_audit.py) reproduces the aggregate and reconciles the captured completed window. The next
window's settlement occurred outside that capture: first two post-restart results were -$1.0167 and +$1.4933,
net +$0.4766. They predate this source fix and do not establish an edge.

Later receipts add +$2.3811 for 14:30-14:45 UTC and -$0.1524 for 14:45-15:00 UTC. The latter straddled PR #45's
restart. All four restarted windows total +$2.7053 after fees; lifetime realized P&L remains -$7.2868. Neither the
recent gain nor the mixed-code window establishes causality or sustained profitability.

The [prospective comparison](COMPARISON_PROTOCOL.md) fixes original, inverted-fair and no-trade arms, realistic
cancellation delay, independent accounting, common coverage and a future endpoint. **It is a specification,
not a running experiment.** The [design](SHADOW_DESIGN.md) explains why the existing practice model cannot yet
stand in for exact live risk and execution. Sealed existing TEST data was not accessed. Inverse P&L is explicitly
null in the audits because executable opposite-side evidence is absent.

Public Coinbase/Kraken capture was enabled on the separate recorder's existing tested code at 14:32 UTC.
Startup confirms READ_ONLY_PUBLIC with spot=True; persisted segment completeness cannot be checked through the
currently available Railway tools. One-Hz REST books remain lower-fidelity evidence and cannot prove a subsecond
sniping edge. [shadow_sufficiency.py](shadow_sufficiency.py) checks exported metadata without reading TEST data
or pretending metadata proves profitability.

Next: measure post-deploy cancellation stages and complete arena windows, verify recorder spot segments through
an authorized volume-read mechanism, then implement and independently validate the frozen comparison. Existing
live limits and loss-budget anchor stay unchanged; no strategy inversion or further budget reset is implied.
