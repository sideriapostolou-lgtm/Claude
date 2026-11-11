# Independent historical result reconciliation

**The reported exploratory loss reconciles to the raw sample and frozen rules.**
The baseline is +$114.00 and −$286.50, totaling **−$172.50** after the declared
hypothetical trading costs. All nine cases lose, from −$170.50 to −$174.50.
This finding concerns the declared root-series proxy only; it does not establish
actual-contract MNQ performance or long-run expectancy.

The standalone `RESULTS_INDEPENDENT_REVIEW.py` imports neither the simulator nor
the runner. It independently parses the private CSV, reconstructs references,
first sweeps, eligible gaps, first inversion/rejection events, entries and exits,
and recomputes financial summaries. **2,433 assertions passed**, covering all
99 interior scenario/day records and 27 early/later/interior summary blocks.
Ruff passed on the verification script. No reconciliation assertion failed and
no strategy source was modified. The existing header failure remains preserved
in `first_attempt/` and was not overwritten.

Checks bind the exact raw-data, corrected manifest, result and source hashes;
the frozen timestamp precedes the result timestamp. Required per-phase and
unique coverage counts match the raw timestamps. October1's 240 missing Asian
minutes remain unresolved in every case; the whole downloaded-span total stays
null. The subsequent 11 dates are complete under the declared checks, not an
independent certification of feed or exchange completeness.

The two baseline trades were verified causally using New York times:

| Date | First sweep | Latest eligible gap c | First inversion | Entry | Exit minute interval | Planned risk | Net |
| --- | --- | --- | --- | --- | --- | ---: | ---: |
| Oct 8 | 09:57 | 09:55 | 09:58 | 09:59 | 10:18–10:19, target | $58.00 | +$114.00 |
| Oct 15 | 09:33 | 09:23 | 09:39 | 09:40 | 09:53–09:54, stop | $283.50 | −$286.50 |

For each, the audit checked no earlier qualifying sweep, the most recent eligible
pre-sweep gap, no disqualifying earlier inversion/opposite sweep, the first
confirming close, next-open entry with adverse friction, the structural stop,
exact 2R target and earliest eligible exit. Target trade-through and stop-first
precedence were checked against every intervening bar. Neither historical trade
has ambiguous stop/target ordering under the defined OHLC rules. The intervals
above do not claim exact intrabar execution timestamps.

Six no-sweep dates reconcile: October2,6,7,12,14,16. October5 and13 reject because
no eligible pre-sweep gap remains. October9's first low sweep is at09:30; the
opposite sweep at09:35 rejects before confirmation. The sole daily attempt is
consumed; these days are retained as non-trading decisions.

The independent arithmetic confirms gross after modeled friction −$168.50,
baseline commissions $4.00, session-end drawdown $286.50 and net excluding the
best day −$286.50. The baseline planned risks differ substantially: the one-
contract rule does not equalize dollar risk. Equal-risk sizing or stop filters
were not evaluated and cannot be inferred profitable from this check.

Friction cancellation is also reconciled. For an adverse-friction assumption
of `f` ticks, the winner's 2R gross is `114 + f` dollars because its entry-to-stop
distance and target move. The stop trade's gross is `−282.50 − f` dollars because
both its entry and stop fill worsen. Both outcomes remain reached in this
sample, so their sum is −$168.50 for f=1,2,4. Four per-side fees across the two
round trips produce the reported three net totals. This is a property of these
two modeled paths and movable targets, not evidence that slippage is harmless
or execution is robust.

The current `REPORT.md` numeric statements, session table, sensitivity table,
Pacific entry/exit times, preserved initial failure and proxy/cost limitations
were reviewed against this reconciliation. No correction was required. The
negative sample result supports no profitable-edge claim, live funding decision,
income projection or parameter tuning.

Exact evidence hashes are recorded in `RESULTS_INDEPENDENT_REVIEW.json`:

- Corrected results: `1277f713102bd856ea2bcb45028ad4741b2fe5defa63218d6c4393280289df7a`.
- Corrected manifest: `5334775bf3d55d6dbdeb011b27c90b5b2a7ce33ddb0c3279d8f549ff27e61467`.
- Raw private CSV: `6dc53ce719b935022c668f36bd2532887a6548b83a7b28d6ac5df0b4f79ee83b`.
- Independent script: `d0ca3a712e6256dc10fa28ccbfc9f7168cbed10e9d810930fc246b427fa8ff6b`.

Actual contract identity, adjustment and roll mapping, account costs, independent
CME halt history and operating net remain unverified. Only 11 days and two trades
were observed. The raw archive was read locally for this authorized reconciliation
and was not redistributed. No old TEST, network, production, accounts or orders
were accessed.
