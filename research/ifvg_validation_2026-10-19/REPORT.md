# Sweep / one-minute IFVG: first historical result

**Verdict: this fixed version lost in the available sample. Do not fund it on this evidence.**

Completed October 19, 2026 at 3:05 PM PDT. This is an offline exploratory replay of a publicly offered MNQ-root sample, using one hypothetical MNQ contract. Individual contract identity, adjustment and roll mapping are not verified. These are simulated results from historical prices, not actual fills or money earned/lost. The exact unidentified trader’s rules and earnings remain unknown; we tested [our explicit v1](../ifvg_intake_2026-10-19/V1_RULES.md).

## Result after assumed trading costs

| Baseline: $1 per side + two adverse ticks | Result |
| --- | ---: |
| Interior sessions, October 2–16 | 11 |
| Completed trades | 2 |
| Wins / losses | 1 / 1 |
| Gross after modeled fill friction | −$168.50 |
| Assumed fees, both sides of both trades | $4.00 |
| Simulated trading net | **−$172.50** |
| First five sessions | +$114.00 |
| Later six sessions, unchanged rules | −$286.50 |
| Worst trade / day | −$286.50 |
| Maximum drawdown at session ends | $286.50 |
| Net without best day | −$286.50 |
| Required unresolved interior sessions / ambiguous trades | 0 / 0 |

The nine other-session decisions are six days without a qualifying sweep and three rejected attempts. They remain in the denominator. October 1 is separately **unresolved**, because the sample lacks all 240 prior-evening Asian-range minutes. It is not a zero-return day; P&L for the whole downloaded span stays unknown. Interior completeness means the specified timestamp/price checks passed, not independently certified exchange/feed completeness.

## The two modeled trades

| Date | Direction | Entry (Pacific) | Exit interval (Pacific) | Planned entry-to-stop risk | Outcome | Trading net |
| --- | --- | --- | --- | ---: | --- | ---: |
| 2026-10-08 | LONG | 6:59 AM | 7:18 AM–7:19 AM | $58.00 | TARGET | $114.00 |
| 2026-10-15 | LONG | 6:40 AM | 6:53 AM–6:54 AM | $283.50 | STOP | −$286.50 |

The losing trade’s structural stop risked $283.50 before exit friction/fees; the winner risked $58.00. Keeping one contract did **not** keep the dollar risk constant. The winner reached 2R, but the much larger dollar loss outweighed it. A 2R target alone does not control dollars at risk. Equal-dollar-risk sizing, a stop-distance filter or changing the pattern would be a different strategy; none is backtested or declared profitable here. Do not use this one loss to tune away the losing trade.

## Every predeclared cost case

Friction includes spread. It is applied adversely on market entries, stops and time exits; targets require one tick of trade-through, receive no favorable price improvement, and still pay fees. No second spread charge.

| Fee per side | Adverse ticks | First five sessions | Later six sessions | Total net | Total fees |
| ---: | ---: | ---: | ---: | ---: | ---: |
| $0.50 | 1 | $114.00 | −$284.50 | −$170.50 | $2.00 |
| $0.50 | 2 | $115.00 | −$285.50 | −$170.50 | $2.00 |
| $0.50 | 4 | $117.00 | −$287.50 | −$170.50 | $2.00 |
| $1.00 | 1 | $113.00 | −$285.50 | −$172.50 | $4.00 |
| $1.00 | 2 | $114.00 | −$286.50 | −$172.50 | $4.00 |
| $1.00 | 4 | $116.00 | −$288.50 | −$172.50 | $4.00 |
| $1.50 | 1 | $112.00 | −$286.50 | −$174.50 | $6.00 |
| $1.50 | 2 | $113.00 | −$287.50 | −$174.50 | $6.00 |
| $1.50 | 4 | $115.00 | −$289.50 | −$174.50 | $6.00 |

All nine cases lose: **−$170.50 to −$174.50**. Identical totals across the three friction settings at each fee are a coincidence of these two outcomes: a worse entry moves the fixed 2R target farther away, and that farther target is still reached here; its extra modeled gain offsets the extra loss on the stop. This does not mean slippage is harmless or that execution is robust.

## Every session retained

| Session | Decision | Reason | Baseline net |
| --- | --- | --- | ---: |
| 2026-10-01 | Unresolved boundary | Missing prior Asian range | Unknown |
| 2026-10-02 | NO_TRADE | NO_SWEEP | $0.00 |
| 2026-10-05 | REJECTED | NO_ELIGIBLE_GAP | $0.00 |
| 2026-10-06 | NO_TRADE | NO_SWEEP | $0.00 |
| 2026-10-07 | NO_TRADE | NO_SWEEP | $0.00 |
| 2026-10-08 | TRADE | CLOSED_TARGET | $114.00 |
| 2026-10-09 | REJECTED | OPPOSITE_SWEEP | $0.00 |
| 2026-10-12 | NO_TRADE | NO_SWEEP | $0.00 |
| 2026-10-13 | REJECTED | NO_ELIGIBLE_GAP | $0.00 |
| 2026-10-14 | NO_TRADE | NO_SWEEP | $0.00 |
| 2026-10-15 | TRADE | CLOSED_STOP | −$286.50 |
| 2026-10-16 | NO_TRADE | NO_SWEEP | $0.00 |

## What was fixed before returns

- Metadata identified 16,200 one-minute data records and 11 complete interior weekdays. Final simulator/rules, dates, chronology and all nine costs were frozen before the first attempt. The first attempt failed immediately on a header that the data audit had mislabeled as absent; no OHLC or return had been read. Original source, manifest and failure are retained in [first_attempt](first_attempt/FAILURE.json).
- Independently confirmed exact header, added strict header validation, retained unchanged data/rules/dates/costs/simulator, and froze [corrected manifest](RUN_MANIFEST_CORRECTED.json) at 3:05:00 PM PDT. The one successful replay evaluated both fixed chronological segments without tuning, completed at 3:05:01 PM. No old TJR/Family A TEST was read. Downloaded bytes were available before the split; no physical holdout isolation is claimed.
- Final pre-replay check: 108 tests and 72 parameterized subtests passed; changed research Python Ruff passed; standalone simulator/runner mypy passed. Independent pre-price review includes 62 synthetic tests plus 12 strict-header probes. These check mechanics, not an edge. The prior lint/fixture/type issues and failed header attempt remain recorded.
- Initial implementation/source review: [implementation](IMPLEMENTATION.json), [independent review](INDEPENDENT_REVIEW.md), [header correction review](HEADER_CORRECTION_REVIEW.md). Independent historical verification passes **2,433 assertions** across all 99 scenario-day records and 27 summaries, directly reconstructing signals and trade arithmetic from the raw sample without importing the simulator or runner. Historical result verification is recorded separately in [independent result review](RESULTS_INDEPENDENT_REVIEW.md) and [root receipt](ROOT_VALIDATION.json). Application release gates are not tested or cleared by this standalone study.

## Limits and next decision

**No demonstrated profitable edge.** Eleven days and only two trades cannot reliably estimate long-run expectancy, and this proxy is not verified actual-contract MNQ. The underlying provider offers several adjustment methods; the sample does not identify which. Cash-calendar classification was checked, but independent CME halt history was not. Next-open entries and minute-bar exits do not verify latency, quotes, queue priority or real fills. Actual account commissions, platform/data costs and operating net are unknown. Reported fee/slippage values are assumptions. No income projection, percentage return, scaling or live recommendation follows.

Highest-value next evidence step, if continuing this idea: obtain a licensed, verified individual-contract MNQ dataset with full overnight/morning coverage, exchange-calendar/roll mapping and actual account-cost evidence; freeze a substantially broader chronological validation before prices. Any new dollar-risk policy must be specified separately before that validation, with losses and rejected versions retained. A minimum one-MNQ position may itself exceed a small risk budget. No paid access, brokerage, paper service or real trading was started.

The implementation and this exploratory check are complete; actual-contract validation and prospective paper evidence remain unfinished. Existing Kalshi storage recovery and other operating work stay open. No application source, production deployment, money limits, loss stops, variables, orders or account funding changed.

## Reproduce this exact exploratory replay

Raw sample stays private. [Data provenance](DATA_FEASIBILITY.md), [metadata correction](DATA_CORRECTION.md), [frozen evaluation](EVALUATION.md), [all derived outcomes](RESULTS_CORRECTED.json). Verify CSV SHA256 `6dc53ce719b935022c668f36bd2532887a6548b83a7b28d6ac5df0b4f79ee83b`; do not publish raw CSV/ZIP. Use a fresh output path because prior evidence cannot be overwritten.

```bash
python research/ifvg_validation_2026-10-19/run_study.py \
  --data /private/path/MNQ_1min_sample.csv \
  --manifest research/ifvg_validation_2026-10-19/RUN_MANIFEST_CORRECTED.json \
  --output /private/path/ifvg_reproduction.json
```
