# Independent TJR validation review

Reviewed **October 14, 2026, 11:57 AM PDT** (18:57 UTC). Scope: the preserved
`MAIN_HANDOFF.md` and `MNQ_PROTOTYPE.md`, plus the new `sources.mjs`, `run.mjs`
and `test.mjs`. The reviewer did not edit the implementation or inspect historical
market outcomes.

The final runner passed **58/58 synthetic checks** in an independent Node
v24.19.0 run. These include reproduction of the unchanged prototype's **65/65**
checks and the separate feature harness's **26/26** checks. These counts describe
synthetic code checks, not independent market samples or evidence of profit.

Two reporting findings were corrected and rechecked:

1. A rejected supplied bundle no longer automatically asserts that the holdout
   was unopened. Its exposure is unverified and no holdout replay is claimed.
2. Known closed-trade losses on incomplete days now have explicit gross, fee and
   net totals. Complete-session totals remain separately labeled; whole-campaign
   P&L remains null when any required session is unresolved.

The versioned calendar correction is limited to blocking unknown calendar status
instead of treating it as a planned exclusion. Original source is preserved.
The runner retains all 30 scheduled development sessions, verifies their previous
session links, retains missing-data cases and all nine frozen cost scenarios, and
keeps execution disabled. No additional blocking signal-causality defect was
found within this review's scope. This is not a guarantee against every defect.

**Verdict: no real-money TJR trial.** Continue historical research, then consider a
separately specified forward shadow/paper trial if the evidence supports it.
Historical trades tested remain **zero**; paper trading has **not started**.

Remaining limitations:

- Authentic actual-contract MNQ December 2025 bars, independently reviewed data
  provenance and permission, and measured account/execution costs are missing.
  Hashes and manifest flags preserve asserted identity; they cannot independently
  authenticate the vendor or license.
- OHLC fills and bar availability are assumptions. Limit-order queues, actual
  delivery latency and intrabar equity drawdown are not established. Nine fee
  scenarios are sensitivity cases on the same sample, not nine confirmations.
- Development has only 30 sessions and at most one trade per session. Even a
  positive development/holdout result would need uncertainty, loss concentration
  and cost robustness reported. Freeze promotion criteria before seeing returns.
- This is a BC23-inspired engineering subset, not TJR's complete current strategy
  or an equivalent Kalshi strategy. No complete audiovisual decision corpus or
  independently verified TJR trading ledger establishes fidelity or returns.
- The historical contract is expired. A forward trial still needs a verified
  current contract/roll policy, authorized feed and persistent observation runtime.
  One MNQ contract is $0.50 per tick; its variable stop risk does not inherit the
  Kalshi desk's dollar caps. Live execution remains disabled.
