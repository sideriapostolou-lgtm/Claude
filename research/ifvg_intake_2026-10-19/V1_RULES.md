# A testable version of the owner's sweep/IFVG idea

Version: OWNER_SWEEP_IFVG_MNQ_v1. Drafted October 19, 2026, 2:51 PM PDT.
Status: explicit research rules; implementation and historical results not yet
available. These are our engineering choices from the owner's description. No
video, trader identity or proof of another trader's earnings is required to
build this version. They are not attributed to that unidentified trader.

The owner's core is retained: Asian/London highs and lows, a sweep after the
9:30 open, a one-minute inverse fair value gap, and a two-to-one profit target.

## Choices made so the first test is reproducible

| Item | Version 1 choice |
| --- | --- |
| Instrument | Actual Micro E-mini Nasdaq-100 futures (MNQ); exact contract must match vendor metadata. This choice builds on the existing futures test infrastructure. It is not a Kalshi trading rule. |
| Price units | Integer 0.25-point ticks; $0.50 per tick per contract. One simulated contract is an accounting unit, not live sizing authorization. |
| Clock | IANA America/New_York for every rule, with its historical daylight-saving offset. 09:30 NY is 06:30 Pacific. |
| Asian reference | Prior calendar day's 20:00 through current day's 00:00 NY, start included/end excluded. A chosen chart-session convention, not the local opening hours of every Asian exchange. |
| London reference | Current day 02:00 through 05:00 NY, start included/end excluded. Also a chosen NY-clock convention; it does not follow London's separate DST dates. |
| Levels | High and low from each complete reference interval, on the same actual contract as the signal. Freeze all four levels before 09:30. |
| Observation/entry window | Sweep bars start at or after 09:30; entries must be before 11:00 NY. Close remaining simulated position at 11:30. |
| Attempts | First qualifying sweep consumes the only attempt that day. At most one simulated filled trade. No re-entry, averaging, partial exits or moving to break-even. |
| Filters | No discretionary trend, news, higher-timeframe or other-instrument filters in this baseline. Their absence is explicit, not evidence they are unnecessary. |

Use only independently verified regular cash-open days with both overnight
intervals and the required subsequent bars present on that contract. Sunday
overnight and exchange maintenance/holiday schedules need the actual exchange
calendar. Do not manufacture missing bars, silently replace a session, or join
different contracts across reference/entry intervals. Verified shortened/closed
days are exclusions with reasons; unknown/incomplete days are unresolved.

## Signal rules

All decisions use finalized one-minute OHLC bars. A bar's data are known only at
its close. Its timestamp convention must be established by the provider.

1. **Sweep and reclaim.** A bearish candidate requires a bar high at least one
   tick above an Asian or London high, and that bar's close at or below that same
   reference high. A bullish candidate requires a low at least one tick below a
   reference low and a close at or above it. A touch alone is insufficient. The
   first bar qualifying in either direction is the attempt; if both directions
   qualify in that bar, reject the attempt as ambiguous. If multiple levels in
   the same direction qualify, log all of them; they do not create extra trades.
   This version allows levels previously crossed before 09:30; adding a fresh-
   level restriction would be a separately recorded change.
2. **Pre-existing gap.** Number the three consecutive forming bars a,b,c. A
   bullish FVG exists if low(c) > high(a); its boundaries are high(a), low(c).
   A bearish FVG exists if high(c) < low(a); boundaries are high(c), low(a).
   Require a gap of at least one tick. There is no extra middle-candle size/body
   rule. Gap c must be one of the ten bars immediately before the sweep bar.
   No missing or nonconsecutive bars may form a gap.
   These are scheduled minute slots, never the latest available rows. Require
   all twelve preceding minute slots so every candidate's a,b,c is known.
3. **Choose before confirmation.** Eligible gaps must not have inverted on any
   finalized bar after c and before the sweep bar. Among those eligible gaps,
   choose the most recently formed bullish gap for a high sweep, or the most
   recently formed bearish gap for a low sweep. Other touches/partial fills do
   not retire a gap in this version.
   If no such gap exists, reject the day's attempt. Freeze the chosen gap; do
   not later replace it with whichever gap produces a favorable outcome.
4. **Inversion.** After a high sweep, a candle must close strictly below the
   chosen bullish gap's lower boundary: short signal. After a low sweep, it
   must close strictly above the bearish gap's upper boundary: long signal.
   The sweep candle itself can confirm because both conditions are known at
   its close. Otherwise allow the next ten consecutive one-minute bars, inclusive
   of the tenth. Wicks and equal-boundary closes do not confirm. An opposite-
   direction qualifying sweep before or on confirmation rejects this attempt.
   Check that rejection first, then use the first qualifying inversion close;
   never wait for a later qualifying close to improve the entry or stop.
   Reject if confirmation cannot lead to entry before 11:00.
5. **Entry and stop.** Earliest modeled entry is the next bar's open, adjusted
   adversely for the declared friction scenario. This is an OHLC approximation,
   not proof of executable zero-latency fills. Freeze the stop one tick beyond
   the most adverse high (short) or low (long) from the sweep through confirmation,
   inclusive. Reject if the next open is at/beyond that stop or the adjusted entry
   leaves nonpositive distance to the stop. No signal may fill within the candle
   that first made it knowable. Missing entry bars block the attempt.
6. **Target.** From the modeled entry, place the target exactly twice that
   entry-to-stop distance away in the favorable direction. Gross target is 2R;
   commissions and adverse stop execution can make the realized payoff worse.

## Simulation requirements before any performance result

Process each bar's opening gap before its intrabar extrema. Marketable stops
execute at the worse of their stop or the opening price, plus adverse friction.
Resting targets require one tick of trade-through and get target price only,
with no favorable price improvement. At 11:30 process any marketable resting
exit at the open before the time exit; a target needs its same trade-through
criterion. Otherwise close at the open with adverse friction. When intrabar
stop/target order cannot be known, assume the stop first and flag ambiguity.
The 11:30 bar's later extrema cannot affect a position already closed at its open.
These conservative conventions do not prove exchange queue fills.

Retain missing/gapped days, all no-trade days, rejected attempts, every known
loss and unresolved positions. An incomplete required outcome is unknown, not
zero P&L. Full-period results remain null if required sessions/outcomes are
unresolved; report any known closed trades separately.
Required coverage includes both reference ranges, the twelve scheduled minutes
before any candidate sweep, the entire observation from 09:30 until the first
attempt (or entry cutoff when no attempt occurs), every intervening inversion
check, and the necessary entry/outcome interval. A required hole makes the day
unresolved; do not resume after it as if an earlier first sweep, inversion or
exit were known. Missing coverage is not a rejected signal or a no-trade day.

Reuse the saved test infrastructure where its behavior matches these rules;
the old cash-session-only runner needs overnight support and an IFVG engine.
Keep the existing TJR source, results and sealed holdout unchanged. Test long/
short symmetry, midnight/DST boundaries, first-attempt consumption, gap age and
inversion, causal entry, opening gaps, ambiguous exits and missing data.

For an initial sensitivity study, predeclare per-side hypothetical fees of
$0.50/$1.00/$1.50 crossed with 1/2/4 ticks of adverse friction on market entries,
stops and time exits; resting targets still pay the fee. Here friction includes
spread, so do not add a second spread charge. Preserve all nine cases. They are
assumptions, not observed fees/fills. Select an actual-cost primary case from
independent account/feed evidence before viewing returns, if available. Data,
platform and other operating costs must be reported separately; none is assumed
to be zero. Report sensitivity-only status if actual costs remain unknown.

## Data and evaluation are still separate prerequisites

Rules above can be implemented without another owner clarification. Freeze the
exact actual-contract dataset, date range, calendar, code hash and chronological
development/holdout split using metadata before inspecting price outcomes. An
old TJR holdout is not a free validation set for a different strategy. A small
sample may test ingestion but cannot establish durable profitability. No dates,
historical results, paper runtime or paid data entitlement are invented here.

Report after-cost expectancy, drawdown, worst day/trade, loss streak, ambiguous
trades, sample coverage, profit concentration and uncertainty. Do not optimize
the session hours, gap age or confirmation window against a final test. Preserve
rejected versions. Promising historical results support a separate prospective
paper study with verified start/evidence; they do not enable live trading.

Next executable substep: implement and test this separate v1 signal/replay
module while obtaining a verified overnight-capable MNQ dataset. The missing
trader video is no longer a dependency. No broker connection, production change,
real order, new funding, limit change or paid purchase is part of this version.

## Review and existing data evidence

Astra independently reviewed this specification without prices, TEST or execution.
Clarifications incorporated: filter eligible gaps before selection; use the first
inversion; preserve scheduled-minute coverage and unresolved gaps; ignore later
11:30 extrema after an opening exit. This is a specification review, not software
test results or profitability evidence.

The Sol metadata inventory used the existing October14 receipts, with no fresh
network request: FirstRate's sample lacks verified individual contract identity
and per-session coverage; Portara's declared MNQ2026M sample starts09:04 NY on
June15 and ends00:59 June16, so neither morning has all the needed ranges and
entry interval. Complete licensed actual-contract overnight data remains to be
obtained. Documented provider routes exist; no paid entitlement is assumed.
