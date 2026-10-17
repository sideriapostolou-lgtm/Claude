# Independent replay primitive review

Scope: Sol's own new standard-library replay.py and test_replay.py against published protocol SHA25691ff9c423b9b0ea4a594db9815ff0dc654a447baef23be63fa5b98338b64707b / declaration commit4ab0ab7425bb107198c4f670db4fecffef5a5548. No publisher code imported/executed. No historical data, confirmation candles/features/outcomes or sealed project TEST read. This review may execute only our newly written code with synthetic fixtures.

## Findings and corrections reviewed

- Missing opposite side price originally passed Quote.crossed and could certify a buy with missing bid or a sell with missing ask. Independent fake cases failed. Sol added complete_side validation at signal, target trigger and delayed execution. Both independent cases now pass.
- Initial source silently sorted reversed receipt clocks. Raised to Sol; the actual execution-prefix receipt order is now checked before accepting a fill, while future malformed observations cannot change earlier decisions. Independent reversed-clock case now passes.
- Root found fractional fee-only rounding did not align total signed balance change: .5contract at.3333 previously produced a non-.0001-aligned debit. Reviewed the correction to cumulative signed gross minus model fees, rounded toward negative infinity at4dp, with6dp model fee and per-order accumulator. Independent partial buy and sale examples pass. This matters to general fee semantics; the one-contract4dp primary already had aligned gross.
- Unknown attempted entry retains its original decision limit and conservative full-cost fee-inclusive lower bound. Own.55limit case gives−.5674, never zero merely because no known position exists.

Preserved initial source snapshot and initial failing run in replay_initial_snapshot.py / initial-code/replay.py / initial_fake_results.txt. Review-owned test_independent_replay.py has11synthetic tests and does not read historical fixtures.

## Checked behavior

Full primitive source read plus reviewed edits; official NOask complements reverse high/low, first-five Coinbase labels use actual completion,32complete quarter-hour closes and fixed first-close seed, all480warmup minute bars required, prior missing signal bars reject rather than ordinal relabel, causal bar guards and source minute10cutoff, one attempt after first qualifying candidate, initial ask limit and unit size, first delayed arrival only, execution-gap/timeout checks, no postclose fills, cross-ticker isolation, conditional target retry, unknown exit retained despite winning official label, settlement full loss with fees counted once, hold policy takes the same Position object, and no network/account/trading adapter in core.

Independent fixtures include nonconstant32-close EMA at an actual UTC-midnight boundary, .5contract signed buy/sell rounding, failed first-arrival depth despite later sufficient quote, missing delayed book, and explicit unknown bounds. They supplement rather than replace Sol's suite.

## Integration scope still pending

Core is a set of primitives. No approval here covers root's downloader/adapter, raw file identities/digest checks, partition/universe completeness, official-label joins, six policy/delay cohorts, day bootstrap, screen denominator/bounds calculations, data publication or economic conclusions. Runner must load rulecards with Decimal, preserve raw quote order, freeze exact policy guard1000/quoteage2000/arrivalwait2000/gap3000/EMA32/allpriorTrue, and not use sampled feature bars instead of official bars. Known unavailable signal candidates and unknown attempted fills are distinct counts. Entirely missing windows must remain in planned/coverage denominators. Confirmation must stay sealed until the complete implementation path is reviewed and hashed.

One execution endpoint clarification remains with root: core rejects price0/1 as nontradable, while frozen OHLC[0,1] is permissible; quote/order validity must be documented against the venue grid or aligned explicitly with the literal sampled-sale rule before final freeze. Final exact-code hash acceptance pending Sol's manifest and root's endpoint decision.

## Final exact core approval

Root chose strict0<p<1 as a declared proxy execution-validity assumption, expressly NOT a verified venue endpoint prohibition, with OHLC[0,1] still accepted. Renewed design approval sent for the separate pre-confirmation amendment. No strategy P&L was inspected to make this choice.

APPROVED CORE PRIMITIVES ONLY at:

- replay.py SHA256 **4bb43b0848b3fd3ad2eba73d90f9786f5ef4119ca4e60887d98dc3ab32be93da**.
- test_replay.py SHA256 **9841af1f2c18a4313c9b0112ca35d1f0061e8d95acf985eb389f22b705ce401b**.
- FREEZE_MANIFEST.json SHA256 **d9a85d4e472031e32a6086b474980672fcb33d81ac4047837065c61069a9de4d**; all five listed file digests independently matched, including frozen config/interface/check receipt.

Independently reran all43Sol synthetic tests successfully and all12reviewer-owned synthetic tests successfully. Own suite expanded to pin explicit endpoint assumption. Sol's recorded mypy/isolated Ruff lint/format successes were inspected, not represented as independently rerun. Final own test/manifest verification saved CORE_APPROVAL.json. Initial source SHA2267f074bd780ebe4730bcad9abf72a9e9380652faf6515fa5be0781a1ab837a and its failed fake result remain preserved.

No outstanding blocker in these exact primitive bytes. This does not authorize confirmation unsealing by itself: root's run_partition.py/test_runner.py, ingestion/provenance, cohort aggregation and reporting path are not yet reviewed. All prior scope limits remain.
