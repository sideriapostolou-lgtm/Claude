# Learner input chronology — local correction, not deployed

Base `91250c6598f4b866d7601ac0ead3e66ba55996cd`. The owner requested feed repairs and a Claude-to-Codex
takeover, then explicitly required read-only production for the daily inspection. This candidate is prepared
locally in `codex/kalshi-feed-learning`; it is **not pushed as application source, merged or deployed**.
Real Kalshi remains stopped; no variables, limits, budgets, consumed controls, orders or real trading rules change.

## Demonstrated defect and bounded correction

Actual-child fake-clock tests reproduce this sequence: a late book/print for a future window arrives before
its start. The learner correctly ignores that early event, while the practice simulator retains sticky
degradation history. At the later fresh forecast slot, passing that untimed simulator map into the learner
incorrectly excludes the window. The initial healthy control forecasts; the false-exclusion case does not.

The candidate keeps the simulator's degradation, voids and accounting intact. Learner exclusion uses its
existing time-qualified, persisted pre/post-gap state. Child hooks also route global loss to every bounded
pending learner window, including those absent from simulator inventory; new same-frame admissions replay
the original drop observation time. Same-frame missing-ladder failure is replayed after discovery at that
frame's original time. No additional persistent cache, parent work, I/O cadence or checkpoint guarantee.

Only two files change: `kalshi_arena.py` child hooks (20 added /4 removed lines), and a new22-case regression
file. Pure learner/model/protocol bytes, all actual active V1 gap rejection, official-label scoring, history,
unknowns and real decision/control paths are unchanged. Tests compare non-learning practice state and save
times, retain old exclusions, test post-forecast losses/restart and out-of-order official labels exactly once.
No prediction is reconstructed after the fact.

The reviewed full patch SHA256 is
`f90a860d89700e09d4351fc585ebfe807cee9dc41b65405160dc7fb788dff427`.
Arena file SHA256 `1fb07bf1d530b51620647dfa7b1b4afc1164eeeb095521b11a9eb2b8220d47ca`;
new test SHA256 `31281d37de5f0da440c15348d80aa38fa6401540843fcef0106249fc813801fb`.
Root and independent Astra recomputed exact bytes and protected-source equality.

The algorithm fingerprint remains `b6112b7ef8955b20af734157c1e7f5ec533bf98f70e034558f06670578c391f2`:
it hashes the pure learner/model, **not the entire upstream/arena input pipeline**. A future release must
record this input-path correction's exact source/deployment identity separately. Old observations keep
their original identity; no mismatch override, reset or history migration is introduced.

## Checks and retained failures

Independent source review accepts the exact patch. **Full pytest: 5,695 passed /14 existing skips in
318.17 seconds, captured exit0**, with reviewed source/test bytes unchanged. Targeted tests: **85 passed**,
including all22 new chronology cases; full mypy **128 source files**, Ruff **two changed Python files** pass.
The independent reviewer read the targeted/type/lint receipts and did not rerun tests; the later full-suite
receipt is preserved separately. Root rechecked exact hashes, protected source and original logs.

The earlier180-test target run/one existing wall-clock skip preceded later regression additions. The
intentional missing-ladder regression failed before repair; a separate initial comparison fixture failed
on legitimate random town IDs and was corrected. Both failures and their actual exits remain preserved.
No failed run is counted as green. Root separately reproduced the original bug and upstream quiet-maker /
delayed-gap mechanisms on the unchanged base with offline fakes, no orders or network.

The [preparation archive](INPUT_CHRONOLOGY_PREPARATION.zip) and
[exact member/hash/check receipt](INPUT_CHRONOLOGY_PREPARATION.json) preserve the full patch, frozen two-file
source, original failed/successful check logs and independent review. This is repository evidence under a
research path, not a production application update. Earlier release/preparation archives remain unchanged.

## What remains unresolved

- The five initial production exclusions and sixth later one have only generic `pregap` receipts; the exact
  producer causes are unjoined. Local proof does not establish that this defect caused those observations.
- The gap wire has no producer occurrence timestamp. A gap/recovery before start, drained after start, can
  still exclude. This candidate does not alter the wire or claim that producer-time problem is fixed.
- Maker eligibility requires a recent trade. Quiet-print expiry can therefore exclude a probability
  observation even with fresh books/Bitcoin. V1 retains that rule; narrowing required probability inputs
  needs an explicit prospective protocol/history design, not a hidden relaxation to obtain forecasts.
- An unknown-slug missing ladder in an earlier separate frame at exactly the same start clock is not
  cached. Base also loses that malformed edge; the actual parent announces windows before encoded events,
  and later first admission is startup-unknown. No broader robustness claim is made.
- Actual production forecasts, official-label updates, better accuracy, profitability, full coverage and
  EXEC completion are still unverified. The inverse comparison remains unstarted.

Next: preserve this tested candidate; under any later explicit source-release scope, integrate current
branch contents, recheck exact bytes/checks, use safe minutes and verify exact deployment/account state.
Then collect a future frozen forecast and official same-terms label without deleting gaps or losses.
The current daily inspection grants no such deployment or real-money resume authority.
