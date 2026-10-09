# Z2 pre-registration: follow a single large buy after BOOST, or learn that whales are exit liquidity

- **Version:** `z2-v1`.
- **Written:** 2026-10-09, before any run on TRAIN, VAL, TEST, CONFIRM or FINAL data. TRAIN is still being
  backfilled. The only run so far is the debug run on the census TRAIN third (§13): counts only, returns hidden, no
  parameter chosen there.
- **Code:** `research/lab2/z2.py`, on the shared foundation `research/lab2/common.py` (every feature through
  `common.AsOf`). Tests: `research/lab2/tests/test_z2.py`.
- **Data:** `graduates`, `b2_coins`, `b2_bars` only (B2 minute bars to g + 180 min). No B1 trades, no B3 positions,
  no CryptoHouse queries.
- **Splits:** common.py's (TRAIN 10-01 → 10-05, VAL 10-05 → 10-06 12:00, TEST 10-06 12:00 → 10-07 19:37:30,
  CONFIRM 09-16 → 10-01, FINAL = census day; the census TRAIN third is debug only).
- **Freeze.** The first official TRAIN run hashes this file into `Z2/prereg.lock`. After that `z2.py` refuses every
  stage if this file changed. A change is a new version (`z2-v2`) in `Z2/AMENDMENTS.md`, and its configs are new
  trials.

## 1. Hypothesis and mechanism

**Claim.** After the BOOST window (g + 420 s), one buyer who puts a single large order into a fresh PumpSwap pool,
large relative to the pool's pricing reserve, carries information about the next 15-60 minutes. Either:

- **INFORMED.** The whale knows something the tape does not yet show: a KOL call or alpha-group post it is about to
  make or has been tipped about, a paid DexScreener boost, a listing, its own plan to keep buying. Then the price
  keeps rising after its print, and a follower who buys on the next bar earns the continuation; or
- **EXIT LIQUIDITY.** The "whale" is the operator painting a green candle to recruit followers, or a late FOMO buyer
  whom insiders sell into. Then the price mean-reverts after the print and every follower loses.

**Why it could beat a 1.4-5.1 % round trip.** The tell is *urgency*. A buy of size ΔX into pricing reserve X moves
the price by ((X + ΔX) / X)² − 1, so a buyer with a single order of 3 % of X pays about 3 % of average impact
plus a 1.25 % pool fee, and lifts the price by about 6 %. A patient buyer would split the order and pay a fraction
of that. Paying the impact is rational only if the buyer expects a move well above 3-6 % within a short time
(microstructure: impatient large orders are the informed ones, Kyle 1985 / Easley-O'Hara 1987). If those moves are
of the size memecoin information events produce (tens of percent within an hour), a $20 follower, whose own impact
is ≈ 0.2 %, can pay its 1.4-5.1 % round trip and the worst-fill haircut and keep the rest.

**Who pays if INFORMED:** the sellers into the whale's continuation (holders and insiders selling too early).
**Who pays if EXIT LIQUIDITY:** the followers, us included.

**Both directions are informative.** A long follower beating its matched random control by ≥ 6 points is an entry
rule (PLAN §3.5). A follower losing to its control with a CI that excludes 0 says "whales are exit liquidity": a
candidate *veto* for every other entry rule ("never buy within N minutes after a whale print"), to be pre-registered
separately (§8). Craft rule G11 ("never enter because a KOL or smart wallet bought") is exactly the prior Z2 tests.

## 2. Instrument: a pigeonhole bound on one trade, from minute bars

Minute bars carry no wallet ids, and the data contract for Z2 is B2 only. Z2 therefore detects whales with a bound
that needs no wallet identity:

- In bar j, `n_buys` counts every buy trade (dust included), `n_dust` counts dust trades (< 0.01 SOL) of both sides,
  `buy_sol` sums user-side buy SOL.
- At least `d_min = max(0, n_dust − n_sells)` of the buys are dust, each < 0.01 SOL. The other buys hold
  > `buy_sol − 0.01 · d` SOL in `n_buys − d` trades. The largest single buy trade is at least their mean, which is
  smallest at `d = d_min` whenever the mean buy is ≥ 0.01 SOL. So
  **`whale_lb = (buy_sol − agent_buy_sol − 0.01 · d_min) / (n_buys − d_min)`** is a provable lower bound on the
  largest single buy trade of the minute (0 when every buy is dust).
- **Non-pooled by construction.** One trade is one order of one signer, even when the event `user` is a pooled
  program account such as `ARu4n5mF…` (audit 3.6). A wallet-level bound (`top5_buy_sol / min(5, n_buyers)`) would
  count a pooled account's many users as one buyer, so it is not used.
- **Non-AGENT by construction.** Only bars that *start* at or after g + 420 s (`common.AGENT_WINDOW_S`) count; BOOST
  ends by g + 341-353 s. AGENT buy SOL is still subtracted (NaN before `agent_known_at` → 0); its trades are not
  removed from `n_buys`, which can only lower the bound.

**Blind spots, stated up front.** The bound sees a whale only when its order dominates the minute's buy *trades*: one
3 SOL buy among three 0.05 SOL buys gives a bound of 0.79 SOL. Whales inside a busy minute (including the minute a
copy-trading swarm piles in) and whales who split one decision into many trades are invisible. The whales Z2 sees
are the ones that printed alone: the ones a 30-second poller could still follow before copy bots. The bound uses
user-side SOL (pool fee included), so the whale's real ΔX is up to 1.25 % smaller than counted.

## 3. Features, as of τ = t − 20 s (all through `common.AsOf`)

| Feature | Definition |
|---|---|
| `whale_lb_j` | §2, on the last completed bar j = k − 1 (bars complete only when `minute_ts + 60 ≤ τ`) |
| `X_before_j` | pricing reserve X = x + v after bar j − 1 (`bars.X[j − 1]`), i.e. the depth the whale hit |
| `size_ratio_j` | `whale_lb_j / X_before_j` |
| **whale bar** | bar j starts ≥ g + 420 s, traded, and `size_ratio_j ≥ q` (q from the grid). q = 0.03 → the single trade lifted the price by ≥ 6.1 %; q = 0.06 → ≥ 12.4 % |
| `X_dec` | pricing reserve after the last completed bar at the decision |
| `depth` | bucket of `X_dec`: `X<50` (drained: < 59 % of the ≈ 85 SOL migration reserve), `50-100` (near migration), `X>=100` (grown) |
| `speed` | `instant` if `grad_delay_s` ≤ 5 s (factory / operator style launch), else `slow`. NULL `grad_delay_s` (creation not scanned) uses `grad_delay_lb_s` = 1,800 s → `slow`. Known at g |
| `sell_lb_j` | the same bound for the largest single **sell** trade: `(sell_sol − 0.01 · ds_min) / (n_sells − ds_min)`, `ds_min = max(0, n_dust − n_buys)` |

No current-state field, no wallet reputation, no truncated window, no flow counted as organic.

## 4. Entry rule

At each decision time t of common.py's grid (minute boundary + 20 s), while flat:

1. decision age ≤ 120 min (`AGE_MAX_S` = 7,200 s; leaves ≥ 57 min of data before the g + 178 min deadline); past it
   the coin is skipped;
2. the last completed bar is a whale bar for the config's q.

The entry is the **first** such decision: the order lands 30 s later in the next bar ("follow on the next bar") and
fills at the worst price of that bar, max(open, high). At most one entry per coin per config (common.backtest).

## 5. Exits

| Exit | Rule |
|---|---|
| Time | `max_hold_s` = H minutes after the landing (H from the grid) |
| Deadline | **sell no later than g + 178 min** (`exit_by_age_s`; fills by g + 179 min, inside the data: no censored trade) |
| Stop | −35 % from the entry fill: a catastrophe stop (craft rule G24's −35 % to −50 % band). Not gridded |
| Big seller | **exit set `seller` only.** Exit at the next decision when any bar completed after the entry decision has `sell_lb ≥ 0.5 × q × X_dec`: a single sell at least half the smallest order that would have counted as a whale at entry depth. If the whale was informed it holds; a seller of its size means it (or an insider of its size) is leaving |

**Fills (PLAN §3.3, craft rule G22):** `common.FillConfig(exit_delay_bars=1)`: $20, latency 30 s, entry at
max(open, high) of the landing bar, every exit at min(open, low), and a stop, time or deadline exit triggered in bar
j fills at min(open, low) of bar j + 1 (next-bar stops). Stops are also checked on the entry bar (entry at the high,
stop against the low). Costs: PumpSwap tier by date and market cap + 10 bps Ultra + 20 bps buffer, network fees,
pricing on X = x + v (common.py).

**Placebo positions** run the same exits. The big-seller threshold uses q and the placebo's own `X_dec`, so it is the
identical rule.

## 6. The TRAIN grid: exactly 8 configurations, every one a trial

**q ∈ {0.03, 0.06} × H ∈ {15, 60} min × exit set ∈ {`time`, `seller`}.**

- q: two whale sizes relative to depth (single-trade price impact ≥ 6 % or ≥ 12 %), the core quantity.
- H: a fast information event (a call or post, minutes) against a slower one (an hour). Urgency predicts the
  short end.
- exit set: mechanical only, or also leave when a seller of whale size appears (§5).
- Each params dict carries every constant of §3-§5, the fill model and the version, so any change is a new trial.
- **Z2's total is 8 trials** on top of the ledger's baseline; TEST / CONFIRM / FINAL rerun shortlisted params and add
  none. 8 ≤ the orchestrator's cap of 12. No padding: no stop, age or depth variants.

**Stress and sensitivity runs** come from the same call and never select:

| Name | FillConfig |
|---|---|
| `costs_x1.5` | every cost component × 1.5 (PLAN §3.5 item 7) |
| `rent_0.22` | + $0.22 token-account rent per coin |
| `same_bar_exits` | `FillConfig()` default: exits fill in the trigger bar (the older, optimistic harness) |
| `no_entry_bar_exits` | next-bar exits, but no stop check on the entry bar |

## 7. Controls

**Matched random control** (PLAN §3.4, `common.backtest`'s placebo): 20 draws per signal, random coins of the same
split at a decision age within ± 120 s of the signal's, the same exits (§5).

- **Eligible:** the last completed bar starts at or after g + 420 s and traded (as every signal's does).
- **Matched on the stratum** `(speed, depth)` of §3 at the decision. The size ratio favours thin pools and instant
  (operator, factory) coins behave differently, so an unmatched control would measure "thin instant coins against
  the average coin" instead of the whale's timing.
- The unmatched control (eligible only) is reported next to it as `placebo_unmatched`, never judged.

## 8. Direction reading (TRAIN, diagnostic; decides nothing)

For every config, from the matched-control difference (signal minus its matched placebo mean, coin-bootstrap 95 %
CI, `common.placebo_compare`):

| Label | Condition |
|---|---|
| UNDERPOWERED | < 30 signals |
| INFORMED | CI lower bound > 0 |
| EXIT_LIQUIDITY | CI upper bound < 0 |
| NEITHER | otherwise |

The **primary direction config** is (q = 0.03, H = 60, `time`): the most signals, the longest horizon, no extra exit.
If it reads EXIT_LIQUIDITY, Z2 recommends a separate pre-registration (`Z2V`, a veto: flag host entries within 15 min
after a whale bar) judged by `common.verdict_veto` on VAL on the G1.R0 random-alive host. Z2 does not run it, and
the reading never changes Z2's own decisions.

## 9. Procedure by stage (`python research/lab2/z2.py --stage …`)

### Every stage

A stage refuses to run unless:

- `Z2/PREREG.md` exists, and matches `prereg.lock` once locked;
- PLAN §8 rule 1 holds for the stage's split (`common.validation_gates`: V1/V2/V4 on the split's dates, validated after
  the data was fetched, V3 on the census sample);
- the split's coverage is complete: every chain hour scanned for curve and B2, no B2 hour mid-run, ≤ 5 % of
  tradeable coins missing B2, and a SOL/USD series that starts before the split's coins (`common.coverage_problems`).
  FINAL is exempt from the hour checks (end-of-data coins are reported), never from the SOL/USD rule;
- the guarded splits have their flags (`LAB2_ALLOW_TEST`, `LAB2_ALLOW_CONFIRM`, `LAB2_ALLOW_FINAL`). `z2.py` never
  sets them.

### TRAIN (all searching)

1. Run the 8 configs, each with the matched control, the unmatched control and the stress runs.
2. **Shortlist rule** (≤ 2 configs). A config qualifies when all hold:

   | Requirement | Bar |
   |---|---|
   | Sample | ≥ 30 trades (one per coin) |
   | Mean net | > 0 |
   | Mean without the top 2 trades | > 0 |
   | Matched-control `mean_diff` | > 0 |

   Qualifying configs are ranked by the coin-bootstrap 90 % CI lower bound of the mean, then the higher mean, then the
   smaller q, then the shorter H, then `time` before `seller`. **Shortlist = the top 2** (1 if only one qualifies),
   written with `common.write_shortlist` and frozen at the first VAL run.
3. If nothing qualifies: **NO_CONFIG** (Z2 fails on TRAIN) when at least one config met the sample bar, else
   **UNDERPOWERED_TRAIN**.
4. A decision on complete TRAIN is final. A re-run needs `--rerun-reason` naming a data correction; the previous
   result is archived as `train_prev_<ts>.*`.
5. `--allow-partial` runs a **PROVISIONAL** TRAIN on partial data: it writes `train_prelim.*`, never a shortlist or a
   lock, and never unlocks VAL.

### VAL (the ≤ 2 shortlisted configs, once)

Run both with the controls and stress runs. **Candidate** = the shortlisted config with the higher VAL mean (VAL
chooses among ≤ 2, PLAN §3.1; ties go to the TRAIN rank); the other is the **twin**, reported only.

| Decision | Condition | Consequence |
|---|---|---|
| UNDERPOWERED_VAL | candidate n < 5 | stop |
| FAIL_VAL | n ≥ 5 and (mean ≤ 0 or mean without the top 2 ≤ 0) | stop (PLAN §8 rule 7 input) |
| SELECTED_UNDERPOWERED | 5 ≤ n < 15, mean > 0, mean without the top 2 > 0 | proceed, flagged |
| SELECTED | n ≥ 15, mean > 0, mean without the top 2 > 0 | proceed |

### TEST (one look per family, `common.one_shot_session`)

- Run the candidate and the twin once, inside one session, with the controls and stress runs.
- **Verdict** = `common.verdict_entry(test, val=VAL candidate, min_mean=0.03)`: PLAN §3.5 items 1-8 at the default
  +3 % bar, criterion 10 (> 10 % censored → INCOMPLETE) and the §3.6 auto-rejections. Item 9 (FINAL mean > 0) is
  judged in the overall verdict once FINAL ran. Combination: REJECTED if rejected; UNDERPOWERED if < 60 trades or
  < 40 coins; FAIL if any judged criterion fails; INCOMPLETE if one is missing; PASS otherwise.
- With a 1.3-day TEST, UNDERPOWERED is likely (§13).

### CONFIRM (09-16 → 10-01; one look, never searched)

- **Precondition:** TEST not REJECTED, and TEST mean > 0 or TEST n < 5. Otherwise Z2 failed TEST and CONFIRM is not
  spent.
- Run the same pair once; same verdict as TEST. CONFIRM is the powered out-of-sample test.

### FINAL (the census day)

- Only after TEST. Run the candidate and the twin once on all of FINAL (one session: FINAL consumes its thirds).
- **Criterion 9 (FINAL mean > 0) is judged on the census VAL and TEST thirds only.** The census TRAIN third hosted the
  debug run (§13), so its trades are reported apart.

### Overall verdict

**EDGE** requires: TRAIN SHORTLISTED; VAL SELECTED or SELECTED_UNDERPOWERED; TEST not REJECTED and (TEST mean > 0 or
n < 5); CONFIRM PASS; FINAL mean > 0. Otherwise UNDERPOWERED (TRAIN, VAL or CONFIRM) or NO EDGE.

## 10. Metric and statistics

- Unit: net return per $20 trade (`ret_net`), one entry per coin per config.
- Coin-bootstrap CIs (10,000 draws; 90 % and 95 %) and the 6-hour block bootstrap (common.describe).
- Also reported: mean without the top 2 trades, top-coin share, halves, the $100 / 5-slot portfolio, costs × 1.5,
  the deflated Sharpe ratio over every trial in the ledger, censored share (0 by construction), exit reasons, and
  counts and means by stratum (`speed|depth` tag).

## 11. Kill criteria (PLAN §8) and declarations

| Rule | How Z2 applies it |
|---|---|
| Stop rule 1 (data first) | per-split V1-V4 gates and coverage; stages refuse otherwise |
| Stop rule 2 (fills) | minute-bar worst fills with next-bar exits until X1 exists. If X1 finds them off by ≥ 1 point, the frozen shortlist is re-run with replayed fills, with no new search, before any promotion |
| Stop rule 7 | FAIL_VAL is reported to the lead |
| Stop rule 8 | every config counts (§6) |

Declarations passed to `common.auto_rejections`: `uses_organic_flow = False`, `uses_wallet_reputation = False`,
`uses_truncated_windows = False`, `uses_current_state_fields = False`.

## 12. Deviations and limits, stated up front

| Area | Deviation or limit |
|---|---|
| Whale identity | A trade-level lower bound on bars (§2), not a wallet. Whales in busy minutes and split orders are invisible; a whale's later sells cannot be attributed to it (the `seller` exit is a size proxy) |
| "Top buyer share" | Not used: the bar's `top5_buy_sol` cannot exclude pooled accounts, and `w120/w300_top10` lie inside the BOOST window |
| Splits | common.py's revised splits. The TRAIN sample bar is 30 trades, the PLAN's 60 trades / 40 coins is judged on TEST and CONFIRM |
| Fills | Minute-bar worst fills (next-bar exits), not replayed trades (X1) |
| Horizon | Holds end by g + 178 min (B2 ends at g + 180 min); entries stop at g + 120 min |
| SOL/USD | Non-debug stages refuse while the series starts after a split's coins (a later price would be lookahead) |

## 13. Debug findings and expected sample (census TRAIN third, counts only)

To be filled from `python research/lab2/z2.py --debug` (`Z2/debug.md`, `Z2/debug.json`) before any TRAIN run.
Returns, exit reasons and placebo outcomes are hidden on that split; its trials go to a scratch ledger.
