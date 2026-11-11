# Z3 amendments

Changes to the Z3 pre-registration after the text was first fixed. `PREREG.md` carries the amended text; this file
is the audit trail.

## A1 (`z3-v2`): the single-seller bound is per sell trade, not per wallet

- **Recorded:** 2026-10-09, before any Z3 TRAIN run (no `Z3/prereg.lock`; no Z3 entry in `research/lab2/trials.json`).
  The grid (entry mode × hold) and every threshold are unchanged (0.70 drop, 0.25 X). The version moves to `z3-v2` and
  the params carry the bound's definition (`big_seller_bound`), so every config has a new params hash; no `z3-v1` trial
  was ever logged outside the scratch debug ledger.
- **Before (`z3-v1`).** `big_j = sell_sol_j / max(n_sellers_j, 1)`.
- **After (`z3-v2`).** `big_j = (sell_sol_j − 0.01 · d) / (n_sells_j − d)` with `d = max(0, n_dust_j − n_buys_j)`,
  never below the plain mean per sell trade, 0 without sells (`z3.sell_trade_lb`, the vectorised `z2.trade_lb`; a test
  checks the two agree). SINGLE-SELLER CRASH stays `big_j ≥ 0.25 · X_{j−1}`.
- **Why (review finding Z3-1).** In `sql/b2.sql`, `n_sellers` counts event users with ≥ 0.01 SOL sold per minute.
  Audit §3.6 shows a pooled program account (`ARu4n5mF…`) is the event user for trades signed by many wallets, and
  `common.POOLED_ACCOUNTS` is removed only from the w120 / w300 top-10 lists, not from bar counts. So a pooled
  account's same-minute sells by many users could pass "one wallet sold ≥ 0.25 X", contrary to PREREG §13's "missed
  event, never a false one". Z2 PREREG §2 rejects wallet-level bounds for exactly this reason.
- **Why it is a definition fix, not a parameter choice.** The threshold is unchanged; only the instrument now matches
  the PREREG's own claim. It was found by review, not from outcomes. Rugs are one swap (wave-1 RESULTS A3), so genuine
  single-seller crashes keep passing; the review counted 3 events on the debug third, and pooled trades are 0.05-0.34 %
  of all trades, so the practical effect is expected to be small.
