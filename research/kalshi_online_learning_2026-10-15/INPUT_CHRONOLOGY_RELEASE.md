# Learner input chronology release and bounded Kalshi resume

October 15, 2026. Times below are Pacific daylight time (UTC−7).

PR [61](https://github.com/sideriapostolou-lgtm/Claude/pull/61) deployed exact
`153a12214f8763b9bf9382697fe6d6810ab04860` on Railway deployment
`e641cdf8-f9e1-43b2-9309-56fd70827d25`, SUCCESS at **8:57:51.700 AM**.
The first observed full market after this release settled **+$0.12 after fees**.
The learner still has **zero forecasts and zero scored samples**: its 9:05 AM slot was rejected for a
pre-forecast gap. This release does not establish a profitable strategy or working online training.

## Exact source and checks

The source PR merged at 8:54 AM, a permitted minute. Its `src`, `tests` and build-config objects equal
candidate `82175d99a2e1da4d88822d3e1820712ee2844208`. The only application change is the reviewed child
observer chronology correction in `kalshi_arena.py`; the new test file adds 22 fake-clock cases.
Real controller/client/config/feed/model/ledger/ladder/Polymarket/build files are unchanged.
The [immutable preparation](INPUT_CHRONOLOGY_PREPARATION.md) retains the exact patch
`f90a860d89700e09d4351fc585ebfe807cee9dc41b65405160dc7fb788dff427`, original failures, source and checks.

Full pytest: **5,695 passed /14 existing skips**, captured exit0; mypy **128 source files** and Ruff
**both changed Python files** pass. Independent exact-source/integration review accepted the patch;
reviewers did not independently rerun the full suite. Original Polymarket startup at 8:57:47.720 AM
shows LIVE, ten contracts per order. Application tests were not repeated for this docs-only evidence.

## Authorized resume and preserved losses

The owner confirmed the named existing limits. Codex explicitly stated a fresh $10 total test budget:
**$10/window, $20 open, $6 daily loss, five-contract clip, fresh $10 total-loss budget**.
Only one fresh single-use `SPEEDDESK_KALSHI_RESUME_TOKEN` was written, with `skipDeploys:true`, immediately
before the source merge. Its value was not read back or saved in this evidence. Existing configured mode
was already live. No cap increase, day/integrity reset, guard removal or other variable change occurred.

One original resume event applies at cumulative P&L **−$19.0510** and anchors the new total budget there.
The already-used day and integrity controls are ignored. The original resume log is dated 8:58:36 AM;
its payload clock is 8:58:35.861 and Railway publication is 8:58:42.722. These clock meanings remain distinct.
The original 7:00:10 AM stop separately reports daily risk $4.6039 with no open risk; the retained daily
loss is not erased by the total resume. Existing stops may bind early to leave room for a hedge.

Independent restart audit checks **67 selected fields:66 exactly equal, one 1.776e−15 display difference**
within an explicit 1e−10 tolerance. At original 8:59:42.611 AM: live/authenticated/trading, empty waiting
reason, account age0.039s/cash age0.896s, no positions/orders/reserve/risk, no integrity error.
Cash **$30.6904** differs from cumulative settled trading P&L **−$19.0510**, fees **$3.10792**,
782 fills/173 settlement counter and UTC-day P&L **−$4.6039**. Caps and prior history remain.
This is selected status/control evidence, not a full native cash ledger, persisted-state or control-history export.

## Fixed 9:00–9:15 AM window

Ticker **KXBTC15M-26OCT151215-15**. Public unauthenticated market metadata independently confirms
16:00–16:15 UTC. The fixed publication tail ends9:17 AM; it was not extended to rescue an outcome.
All fourteen exact retrospective log queries completed after the tail without error or a capped response.
Collection is finite and closed; no continuous collector was started. Startup, next partial and practice
activity are separate. Raw originals, declaration, markers and both parser versions remain in the archive.

The strict declaration required root verification before9:00 AM. Although the original healthy account
row is from8:59:42, root finished verifying it at **9:00:09 AM**. That declared gate **FAILED**;
healthy retrospective evidence does not make that gate timely. Bounds were not shifted. Actual accounting
below is independently reportable, while complete venue/source coverage remains uncertified.

| Actual real fills | Shares | Price | Recorded fees |
| --- | ---: | ---: | ---: |
| Up, two partial fills | 0.22 +0.78 | $0.41 | $0 |
| Down, one fill | 1.00 | $0.47 | $0 |

All three maker fills join to two accepted orders and their durable intents, matching ticker/side/price/size.
Twenty-four intents =22 accepted +two explicitly not sent; zero rejected/unresolved intents, orphan
acks, fill-join errors, lifecycle conflicts or settlement arithmetic mismatches in this fixed extraction.
Two filled orders/22 accepted orders =9.09%; three fills includes a partial fill and is a different denominator.
No IOC order or taker fill occurred. These are this window's counts, not a full-day rate.

Cost **$0.88**, gross payout **$1**, recorded fees **$0**, net **+$0.12**: all **locked-pair P&L**, directional
**$0**, worst/only audited window **+$0.12**. One pair was credited before settlement; paired credit$1 and
net payout$0 are distinct from gross payout$1 and must not be added twice. Official settlement venue time
9:15:01.828 AM; observed9:15:06.485/published9:15:06.979. No remaining unmatched shares in this window.

Accepted regular decision→ack: n22, median83.570ms/p95374.488ms/max554.195ms. Two other timing receipts
carry error/null and correspond to the explicitly not-sent decisions; they are outside those22accepted samples. Accepted Coinbase callback
age: median171.434ms/p95565.906ms; exchange-age308.964/594.648ms. These exclude rejected-source traffic
and are not a proven trigger-reaction speed. Twenty-one cancel receipts include17 reprice, three requested
for stale books and one stale-book404; request→reply timing is not terminal cancellation or freed liability.
The actual later reconciled account is checked separately.

The sampled main reader still has **six known rejected-gap local residence intervals**, all within the
window, maximum **3,345.957ms**. There are54 main-gap and five main-status overflow observations of unknown
interval over the fixed query/publication-tail population; these are not zeros or54 additional known delays.
Ten contained reconcile traces/50 reads have maximum worker-complete→resume586.729ms, no reported omitted
reads/new fills in those selected traces. Quiet cycles/full causal attribution remain unverified.
Seventy-four original plaintext gap warnings publish in-window and four in the tail; they are publication
counts, not measured durations or a causal join to the learner's generic exclusion. **EXEC remains open.**

The first offline parser mistakenly treated the78 valid plaintext gap warnings as malformed JSON.
Its original source/manifest/audit and failed flags remain preserved. A narrow reviewed parser amendment
recognizes only the exact source text format; all fourteen raw response hashes and financial/latency/gate
results remain unchanged. An independent original reparse agrees with all financial joins, fees, payout, timing denominators and exclusions.
The corrected extraction has no row/join/arithmetic flags, while the declaration
still fails and source coverage is still uncertified. Parser exit0 does not imply those gates passed.

## Later account, learner and recorder

Original **9:17:50.058 AM**: live/authenticated/trading, reasonpair_cap, no integrity error or latched stop;
cash **$30.3804**, cumulative settled P&L **−$18.9310**, UTC-day P&L **−$4.4839**, fees **$3.10792**,
786 fills/174 settlement counter. The next partial has one Up share costing/risking **$0.43**,
no reserve/resting orders; its outcome is not part of the completed trial. Selected cash arithmetic:
30.6904 +0.12 −0.43 =30.3804. This is not a full native account/cash ledger reconciliation.

The learner retains the reported prior counts and history identities: startup0forecasts/0scored/9unknown; 9:05AM becomes0/0/10unknown
(one startup/nine pregap), both Brier scoresnull, enabled observe-only/errornull. No trained update,
accuracy gain, live application or profit edge. Unchanged b6112b7e algorithm fingerprint covers pure learner
and fair model, not arena input hooks; exact new release identity is recorded separately. The remaining
exclusion cause cannot be uniquely joined from generic logs. The [next diagnostic design](INPUT_CHRONOLOGY_NEXT_EVIDENCE.md)
preserves V1 inputs/history and records available causes/timing before any prospective V2 quality protocol.

At9:18AM both services remain online1/1, no reported warnings/recent failures. Recorder deployment
8453f919/sourcea0782b7 is unchanged. Bounded new-bot Traceback query and recorder storage/error-warning
query return zero; neither proves future health, full storage contents, raw hashes or all data coverage.
A local exec transport disconnection recovered on the next command; it did not fail a production data query.
An initial gh metadata command used an unsupported field and was corrected before merge; the failed command
is retained. No financial action was retried, and no create-order request was made by this session.

## Continuity and next evidence

The9:19AM repeated TJR reminder re-read current connected GitHub records at153a122. PR47 release/restart
is separately complete; broader EXEC and the original/inverse comparison are not. Prior offline TJR priority
persists, but authentic MNQ development bars/costs remain missing: historicaltrades0/P&Lnull, holdoutunopened,
paper not started/live off. Existing saved source/65 reproduced synthetic checks are historical evidence;
no duplicate Page/data/test work or routine unchanged notification. Queue and automation stay unfinished/enabled.

Owner-held private handoff Part2 and two shipping skill files remain unavailable/unread. The external Claude
routine is reported, not independently verified or disabled. No complete session/credential/volume migration
is claimed. Current private inventory is not copied into this public repository.

Next: implement and check a bounded observation-only rejection diagnostic, preserving the exact input
quality protocol and old unknowns, then collect a genuinely frozen forecast/official-label score-before-update
receipt. Preserve continuing main-reader delay, all losses and every unverified interval. Trading decisions
remain the existing deterministic rules under the approved caps; neither a small winning window nor this
release supports a cap raise or self-learning success claim.

[Raw evidence archive](INPUT_CHRONOLOGY_RELEASE.zip) · [member hashes and receipt](INPUT_CHRONOLOGY_RELEASE.json).
