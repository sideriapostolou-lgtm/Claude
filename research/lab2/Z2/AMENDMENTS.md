# Z2 amendments

Changes to the Z2 pre-registration after the text was first fixed. `PREREG.md` carries the amended text; this file
is the audit trail.

## A1 (`z2-v2`): a whale bar must lift the pricing reserve net of the minute's sells

- **Recorded:** 2026-10-09, before any Z2 TRAIN run (no `Z2/prereg.lock`; no Z2 entry in `research/lab2/trials.json`).
  The grid (q, H, exit set) is unchanged. The version moves to `z2-v2`, so every config has a new params hash; no
  `z2-v1` trial was ever logged outside the scratch debug ledger.
- **Before (`z2-v1`).** Bar j is a whale bar for size q when it starts at or after g + 420 s, traded, and
  `whale_lb_j / X_before_j ≥ q`.
- **After (`z2-v2`).** The same, **and** `X_j − X_before_j ≥ 0.5 · q · X_before_j` (`MIN_NET_LIFT_Q = 0.5`,
  `z2.whale_at`). q is unchanged. The debug counts (`event_counts`) use the same rule.
- **Why (review finding Z2-1).** PREREG §1's construct is "an urgent buyer who paid the impact". The size test alone
  fires on minutes in which the whale was netted out by the same minute's sellers. The review's probe of the debug
  split (bar flows of the signal bar only, all known at the decision; no returns computed) found, among the 47
  q = 0.03 entries, 16 with same-minute sell SOL ≥ 0.8 × whale_lb; 7 of those raised X by less than 0.5 × whale_lb and
  5 were net-negative minutes (for example 1 buy of 0.86 SOL against 6 sells of 1.58 SOL; a churn minute of 162 buys
  and 176 sells, where the bound of 1.49 SOL is just the mean buy). Over all 77 whale bars, 18 had
  dX < 0.5 × whale_lb. For those entries the old §3 sentence "the single trade lifted the price by ≥ 6.1 %" was true of
  the trade but not of the bar, so an INFORMED or EXIT_LIQUIDITY reading could not be attributed to single-order
  whales.
- **Why it is a definition fix, not a parameter choice.** The threshold is half of the size test's own q (a whale of
  size q·X lifts X by q·X when it prints alone), fixed from the construct, not tuned; no return, exit reason or
  placebo outcome was looked at. Between 5 and 18 of the 77 debug whale bars fail it.
- **Not changed.** The judged matched control (speed, depth) and its eligibility (the last completed bar started after
  BOOST and traded). The review's lesser remedy, a jump-matched diagnostic control, was not added: with A1 every whale
  bar is an up-bar by construction, and the comparison with equally large up-bars without a single dominant trade
  remains a possible follow-up.
