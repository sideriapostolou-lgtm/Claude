# First historical test: declared scope before returns

Declared October19, 2:59 PM PDT, before any strategy return or sample OHLC value
was inspected. Owner explicitly requests testing profitability. No new money,
production code or broker connection is part of this study.

## Two distinct questions

Actual-contract `OWNER_SWEEP_IFVG_MNQ_v1` validation remains blocked on verified
contract identity, adjustment/roll history, exchange calendar and actual costs.
Do not relabel a root-symbol sample as a verified actual MNQ contract.

The executable first study is `OWNER_SWEEP_IFVG_ROOT_SAMPLE_EXPLORATORY_v1`:
apply the same price-pattern rules to FirstRate's publicly offered MNQ-root
sample, using hypothetical MNQ tick value and the already declared nine cost
cases. Root/continuous-series and adjustment uncertainty are explicit. Results
are exploratory simulated dollars, not fills, money earned or proven live edge.
No data or parameter choice may be selected for favorable results.

## Dataset, dates and partition

- Source: https://frd001.s3.us-east-2.amazonaws.com/frd_sample_futures_MNQ.zip
- Downloaded ZIP SHA256: `c97b6273b8eb577c88ca92e82f465a81e598aebc5926c520942c7ffa23036fa7`.
- CSV SHA256: `6dc53ce719b935022c668f36bd2532887a6548b83a7b28d6ac5df0b4f79ee83b`.
- Metadata-only inspection: 16,200 rows, October1 00:00 to October16 16:59 NY;
  one exact header followed by 16,200 data records, six columns
  timestamp/open/high/low/close/volume. Provider readme
  specifies Eastern time and interval-start labels. Keep originals private;
  publish provenance and derived results, not the raw price archive.
- Evaluated interior interval: **October2–16, 2026**, all 11 regular cash weekdays,
  chosen from metadata before returns because the leading October1 boundary
  lacks all 240 previous Asian-range minutes. October1 is also run/reported as
  an unresolved boundary diagnostic, never a zero-return day. Whole downloaded-
  span P&L remains unknown; the interior-window total has its own explicit scope.
- First chronological segment: October2,5,6,7,8 (five days).
- Later chronological segment: October9,12,13,14,15,16 (six days).
- Freeze final reviewed simulator/runner/rules hashes before the first price
  replay. Run both fixed segments exactly once in order with no tuning between
  them; preserve both regardless of sign. These tiny segments cannot establish
  independent long-term validity. Bytes were downloaded before the split, but
  only timestamps/metadata were inspected; do not claim physical holdout isolation.
- Existing TJR/FamilyA TEST partitions are not accessed or reused.

The official Nasdaq calendar verifies the cash-open classification, not CME
halt history or feed completeness. All 11 interior days have the expected
reference/prewindow/outcome timestamps in the metadata audit. Price validity,
tick alignment and simulator-required coverage are checked during ingestion.
Never round prices onto ticks or fill missing candles to obtain a pass.

## Costs and reporting

Report every combination of assumed per-side fees $0.50/$1.00/$1.50 and 1/2/4
adverse ticks on entries, stops and time exits. Friction includes spread; no
second spread charge. Targets pay fees and require the frozen trade-through.
The middle case ($1 per side, two ticks) is the descriptive baseline, selected
now before outcomes; it is not an actual account-cost estimate. Price-move gross
is measured from modeled fills and already includes friction. Deduct commissions
once. Real data/platform/broker costs are unknown; operating net stays unknown.

For each scenario/segment and the complete interior interval report every day's
decision/reason, known closed trades, wins/losses, trading net, commissions,
planned entry risk, worst trade/day, consecutive losses, session-end drawdown,
intrabar ambiguity and coverage. Show the net without the best day. Do not use a
return percentage without a capital denominator or equate one simulated contract
with an approved live position size. Keep unresolved outcomes null.

With only 11 days, no precision confidence interval, monthly income estimate or
scaling recommendation is justified. A positive result is only a reason to
obtain verified broader actual-contract data and run a separate unchanged-rule
validation. A negative result must be reported plainly. Software checks prove
tested mechanics, not historical profitability or real execution.

### Recorded pre-price ingestion correction

The first frozen attempt on October19 at3:04PM PDT stopped at the first CSV
record because metadata incorrectly described it as headerless. No OHLC record
or return was parsed. Original runner, declaration, manifest and tests are kept
in `first_attempt/` with `FAILURE.json`; DATA_CORRECTION records the independently
checked exact header and16,201 total records. Corrected ingestion requires and
skips exactly `timestamp,open,high,low,close,volume`. Rules, dates, nine cost cases,
source bytes and simulator stay unchanged. Refreeze the corrected runner before
the next attempt; retain both manifests and all resulting evidence.

## Reproduction and no outcome-driven changes

The final run manifest binds the exact CSV, reviewed simulator, runner, saved
rules and this declaration. Outputs are created exclusively and cannot overwrite
a prior run. Keep the initial output and any failures. Any bug discovered after
returns requires a labeled new run with prior output retained; evaluated dates
cannot regain an untouched label. No parameter optimization in this campaign.
