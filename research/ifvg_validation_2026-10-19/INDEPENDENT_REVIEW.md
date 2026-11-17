# Independent simulator and runner review

No blocking simulator or runner finding. **62 independent synthetic checks and
12 root runner checks pass**; Ruff passes on the independent test file. This verifies the bounded replay
behavior, not profitability, real fills or a complete research pipeline.

The reviewer prepared the initial 39 specification-derived checks before reading
the simulator source. Those all passed. Source inspection and additional boundary
fixtures increased the suite to 55; all passed without changes to the simulator.
The first Ruff run found four test-style issues (import grouping, two timezone
aliases and an unnecessary timestamp string replacement). Those were corrected
only in `independent_test.py`; no financial expectations changed. Final rerun:
`55 passed in 0.30s`; Ruff: `All checks passed!`.

Root subsequently requested explicit exit-time precision metadata. The implementer
added `OPEN` versus `INTRABAR_INTERVAL` with an interval end for intrabar exits;
signal and accounting rules did not change. Two independent metadata checks were
added and all 57 checks passed against the final source below, in 0.28s. Ruff
passed again. The original simulator hash and initial check outcomes are retained
in the JSON record.

The subsequent bounded runner review reproduced its 12 parser/accounting tests
and added five independent accounting and manifest/output-guard checks. All 74
checks passed in 0.33s. Initial lint of these additions found four unnecessary
Decimal string conversions; fixing test style left all financial expectations
unchanged, and the final lint passed.

Before replay, root's standalone mypy found four annotation errors. The implementer
added typed gap/attempt records and a typed result dictionary. The reviewer
inspected that refinement and reran the 74 tests against the final hash below:
all passed in 0.30s; independent-test Ruff passed. Signal, accounting and serialized
results were unchanged. The implementation receipt retains that initial mypy failure.

Exact reviewed files:

- `simulator.py`: SHA256 `69caef01eb392211342524b2fc3bc695f5cb31eab9d6d64763a4fc4503c2615b`.
- `independent_test.py`: SHA256 `ba343c3fa98251317398fcdf60766be0b185ed1cc1996b1e9c99f8a0918aba81`.
- `../ifvg_intake_2026-10-19/V1_RULES.md`: SHA256 `59e43db6904ce48ff0da9e0c4e144a11e160c9c577c86339963c9e1b51aa6d18`.
- `run_study.py`: SHA256 `6e9d820aabc18776d7c6a316e9016dd24a94d87238f0f92a058eda5ce03fe76e`.
- `EVALUATION.md`: SHA256 `274ee2edc8ad1dc687c96bfed8e7b05d805d5681d2031650570f8a9861f0dbe6`.

The checks cover causal next-open entry, sweep self-confirmation, long/short
symmetry, all nine fee/friction scenarios, exact net accounting, newest eligible
gap selection, strict first inversion, gap/confirmation age limits, opposite-sweep
precedence and entry cutoff. They also exercise opening stops and targets,
trade-through requirements, ambiguous intrabar exits, the 11:30 time exit, DST,
required missing bars, preserved known closed losses and invariance to later
price changes. See `INDEPENDENT_REVIEW.json` for the full retained check history.

Reproduce from the repository root:

```bash
/workspace/nightcrawler-daily/.venv/bin/python -m pytest -q research/ifvg_validation_2026-10-19/independent_test.py research/ifvg_validation_2026-10-19/test_study.py
/workspace/nightcrawler-daily/.venv/bin/ruff check research/ifvg_validation_2026-10-19/independent_test.py
```

The API accepts `REGULAR` as the caller's calendar attestation. It does not prove
contract identity, vendor timestamp convention, exchange calendar status, complete
period coverage or proper evaluation partitioning. Those remain runner/data
responsibilities. Intrabar exit timestamps identify a modeled minute, not an
observed exact execution time. Synthetic DST fixtures do not attest that their
dates were independently verified exchange sessions.

Runner inspection confirms exact CSV/source/declaration hash gates, the declared
16,200-row count, six-field schema, 20,000-row parser limit, October1–16 start-
minute Eastern timestamps, strict ordering/duplicates, finite positive aligned
OHLC, valid extrema and integral nonnegative volume. Exact data hash enforcement
binds the metadata's first/last timestamps and rows; the parser does not silently
round prices or manufacture candles. The runner keeps the boundary diagnostic,
fixed five/six-day segments and all nine cost scenarios. It creates output
exclusively. Independent guards confirmed rejection of existing output, a bad or
incomplete manifest and changed sources before data access.

Summary inspection and synthetic cases reconcile known closed gross/net/fees,
unknown open-entry fees, drawdown, loss streak, ambiguity and removal of the best
day. Unresolved periods retain null total/drawdown; operating net remains null.
The loss-streak field expressly measures the known closed-trade sequence, and
drawdown is at session ends. No physical holdout isolation or actual-cost proof
is claimed. The source and declaration are ready to freeze for their explicitly
limited exploratory study; this review does not report its outcomes.

If available public prices are continuous or their contract identity is unverified,
any resulting analysis must be identified as an exploratory proxy before examining
returns. It cannot establish performance under the registered actual-contract MNQ
protocol. This review did not inspect prices, TEST, datasets, financial statistics,
production, accounts, credentials or network resources. No live authorization or
profitability conclusion follows.
