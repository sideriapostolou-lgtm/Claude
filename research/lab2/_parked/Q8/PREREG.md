# Q8 pre-registration: conviction accumulators (repeat buyers who never sell)

- **Version:** `q8-v1`. Queue item q8, code CA1 (`scratchpad/ideas/mill/queue.json`, QUEUE.md §1 q8).
- **Written:** 2026-10-09, before any run on TRAIN, VAL, TEST, CONFIRM or FINAL data. B1 wallet trades do not exist
  yet (830 TRAIN coins selected, 0 fetched), so no TRAIN data could have been seen. The only run so far is the debug
  run on the census TRAIN third (§12): real bar counts, synthetic wallet tapes, returns hidden.
- **Code:** `research/lab2/q8.py`, on the shared foundation `research/lab2/common.py` (every feature through
  `common.AsOf`). Tests: `research/lab2/tests/test_q8.py`.
- **Shared rules:** QUEUE.md "Shared rules for every spec" 1-8 apply. This file states only how Q8 meets them.
- **Freeze.** The first official TRAIN run hashes this file into `Q8/prereg.lock`. After that `q8.py` refuses every
  stage if this file has changed. Any change is a new version (`q8-v2`) recorded in `Q8/AMENDMENTS.md`, and every
  config it adds counts as new trials.

## 1. Hypothesis, mechanism and why it could matter

**Claim (public).** An audit of Ansem's calls found that coins he backed repeatedly all gained, while coins he
mentioned once or twice all lost (median first-mention return −55 %). Nansen reads consistent buying through drops
as conviction.

**Mechanism.** A wallet that keeps adding without ever selling reveals conviction or information, and it removes
float: its tokens are not for sale. One-off buys are noise, promotion or flippers. If several such wallets are
accumulating, the coin's buy side is held by people who are not about to dump on us.

**Who loses.** Holders who sell to the accumulators early, and late buyers who chase coins whose buying is one-off.

**Why it could matter.** This is the only wallet-identity entry in the queue that needs no cross-coin registry: it
reads the traded coin's own pool trades up to τ. If repeat *identity* carries information beyond the *number* of
buys, the shuffled-wallet control (§7) shows it directly, and the rule is a minute-scale decision (latency score 4).

**Material difference from M1.** M1's MECH-wallet is a machine: regular gaps, regular sizes, price-blind. Q8 keeps
discretionary repeat buyers and **removes** M1's MECH wallets. D1's organic-buyer features are related but count
buyers in a 3-minute window, not repeat buying since graduation.

## 2. Data and universe

| Item | Rule |
|---|---|
| Universe | The B1 universe = `s1.universe_mask` = `b1_select.py`'s selection: common.py usable (SOL-quoted, not Mayhem, virtual reserve known, B2 window complete) ∧ creation scanned ∧ `created_exact` ∧ `grad_delay_s` > 5 s (slow, non-factory graduates). Checked per coin through AsOf (`curve_partial`, `created_exact`, `grad_delay_s`), and the coin must have B1 rows |
| Wallet trades | B1 (`b1_trades.parquet`) through `snap.trades`: PumpSwap rows (`venue` = 1) with g ≤ ts ≤ τ. B1 covers [c, g + 120 min) |
| Bars | B2 minute bars through `snap.bars`, `snap.price`, `snap.alive()` |
| Readiness | **B1.** Every stage except the debug run refuses until `b1_trades.parquet` exists and covers ≥ 95 % of the split's B1-universe coins (S1/D1's minimum). `--allow-partial` waives incomplete B2 coverage on TRAIN only, never the B1 minimum |
| Bar 0 | Q8 decides from g + 10 min. It reads bar 0 only through `alive()`'s 15-minute volume (SOL flow, not price). The concurrent bar-0 price fix (task #26) is still a global blocker for TRAIN / VAL (QUEUE shared rule 8) |
| Registries | None. Q8 uses no cross-coin registry, so PLAN §6.6 / AO-6 has nothing to apply to. The traded coin's own trades are read only up to τ |

## 3. Features as of τ = t − 20 s (all through `common.AsOf`)

**Excluded wallets** (never members of A):

| Wallet | How it is known at τ |
|---|---|
| AGENT | `agent_wallet` once `snap.agent_detected` (always resolved at τ ≥ g + 420 s; Q8 decides from g + 10 min), hashed to B1's `wallet_h` (cityHash64) |
| Completer | `completer` (legal at g), hashed |
| Creator | `creator` (legal at creation), hashed |
| Pooled accounts | `common.POOLED_ACCOUNTS` + `pooled_accounts.json` (hashed), and rows that `common.load` marks `pooled` |
| MECH | M1's MECH-wallet test (`m1.mech_wallets` constants, reproduced exactly and cross-checked in the tests): over pool trades in (c − 30 min, c], ≥ 6 buys, sells ≤ 10 % of buy SOL, CV of buy gaps < 0.25, CV of buy sizes < 0.5, \|Spearman(size, price change over the 60 s before the buy)\| < 0.3. A wallet is excluded at τ when the test flags it at **any minute cutoff c with g < c ≤ τ** (a timer bot that stopped is still a timer bot) |

**Features:**

| Feature | Definition |
|---|---|
| A | Non-excluded wallets with **≥ 3 pool buys in distinct clock minutes** since g, **Σ buy SOL ≥ 0.3**, and **no pool sell** since g (rows g ≤ ts ≤ τ). "No orphan sells" is implied: an orphan sell is a sell |
| `count_A` | \|A\| |
| `share_A` | Σ buy SOL of A since g / Σ buy SOL since g of every wallet except the AGENT (pooled, creator, completer and MECH buys stay in the denominator). NULL when the denominator is 0 |

SOL is the user-side `usol` of each B1 row. B1 holds no dust (< 0.01 SOL) trades.

## 4. Entry rule

Decisions run on common.py's grid (minute boundary + 20 s). The entry is the **first** decision with:

- decision age t − g in [10, 60] min (after 60 min the coin is skipped);
- the coin in the B1 universe with B1 rows;
- `count_A` ≥ K and `share_A` ≥ X (a NULL share never passes);
- `snap.alive()`: ≥ $1.5k volume over 15 min and market cap ≥ $6k.

One entry per coin per config. The entry stores the cohort A (its wallet ids) and τ_e.

## 5. Exits

Both exit sets also carry a **−30 % stop** (mechanical, from the entry fill) and the **g + 118 min deadline**
(`exit_by_age_s` = 7,080 s, QUEUE shared rule 2 for specs reading B1).

| Exit | Rule |
|---|---|
| **E1, cohort** | In a completed clock minute after τ_e, ≥ 2 distinct members of the entry cohort A have a pool sell. The decision at the end of that minute exits; the order lands in the next bar (worst fill) |
| **E2, close trail** | The last completed close ≤ 75 % of the highest close since the entry fill bar (that bar included). Evaluated at each decision on completed bars, so it also fills in the next bar |

**Fills:** `common.FillConfig(exit_delay_bars=1)`: $20, latency 30 s, entry at max(open, high) of the landing bar,
exits at min(open, low), entry-bar stop checks on, a mechanical stop or the deadline fills one bar after it
triggers. Costs: PumpSwap tier by date and market cap, + Ultra 10 bps, + 20 bps buffer, network fees, pricing on
X = x + v. Flow exits never read B1 at τ ≥ g + 120 min (the deadline fires first).

**Placebo positions carry no state.** Their cohort is recomputed from the placebo coin's own trades at the
placebo's decision time, so they run the same E1 rule (a placebo with fewer than 2 members cannot have a cohort
exit). E2 needs no state.

## 6. The TRAIN grid: exactly 12 configurations, every one a trial

| Hypothesis | Configs | Values |
|---|---:|---|
| `Q8` | 8 | K ∈ {3, 5} × X ∈ {0, 0.2} × exit ∈ {E1, E2} (the queue spec's grid) |
| `Q8-shuffle` | 4 | K ∈ {3, 5} × X ∈ {0, 0.2}, shuffled wallet ids (§7), exit E2, seed 0 |

- Each params dict carries every constant of §2-§5, the fill model and the version. Any change is a new trial.
- **Q8's total is 12 trials**, on top of the ledger's 2,576. VAL / TEST / CONFIRM / FINAL rerun shortlisted params
  only, so they add none. No model check (the queue spec registers no kill gate).
- **Stress:** costs × 1.5 from the same call, reported, never used to select.

## 7. Controls

**Matched random control** (`common.backtest`'s placebo, PLAN §3.4): 20 draws per signal, random coins of the same
split that are in the B1 universe with B1 rows and alive, **in the signal's own G1 class at g + 140 s**
(`g1.classify(g1.g1_features(...))`, QUEUE shared rule 4), at a decision age within ±120 s of the signal's, with
the same exits. It feeds PLAN §3.5 item 5 (≥ +6 points) and the TRAIN shortlist (`mean_diff` > 0).

**Shuffled-wallet control** (`Q8-shuffle`): does repeat *identity* matter, or only the number of buys?

- At each decision, take the pool trades since g of non-excluded wallets (the exclusions of §3, computed on the real
  ids). Each wallet gets a code 0 … W − 1.
- **Within each clock minute**, replace every code by its image under an independent random permutation of
  0 … W − 1 (seeded by the seed, the mint and the minute). A wallet's rows inside one minute stay together; across
  minutes the identity is broken. Every minute keeps its number of buyers, sellers, buys and sizes.
- `count_A` and `share_A` are recomputed on the relabelled rows (same denominator); the entry rule is unchanged; the
  exit is E2 (identity-free) with the same stop and deadline. Its matched placebo is drawn as above.
- The identity comparison is **entry-level**: Q8 (K, X, E2) against Q8-shuffle (K, X), with a coin-clustered
  bootstrap CI of the difference (`d1.diff_ci`). E1 configs share their entries with the E2 config of the same
  (K, X). Only E2 is shuffled because the grid is capped at 12 trials.

## 8. Procedure by stage (`python research/lab2/q8.py --stage …`)

### Every stage

A stage refuses (exit code 2) unless:

- `Q8/PREREG.md` exists, and matches `prereg.lock` once locked;
- PLAN §8 rule 1 holds for the split (V1/V2/V4 on its dates, `common.validation_gates`);
- **B1:** `b1_trades.parquet` exists and covers ≥ 95 % of the split's B1-universe coins;
- the split's B2 coverage is complete (every chain hour scanned, no mid-run hour, ≤ 5 % of tradeable coins missing
  B2, SOL/USD covers the split). FINAL reports end-of-data coins instead of blocking on them;
- the guarded splits have their flags (`LAB2_ALLOW_TEST`, `LAB2_ALLOW_CONFIRM`, `LAB2_ALLOW_FINAL`); `q8.py` never
  sets them.

### TRAIN (all searching)

1. Run the 12 configs, each with the matched control and the costs × 1.5 stress.
2. **Shortlist rule.** For each entry definition (K, X):

   | Requirement | Bar |
   |---|---|
   | Power | its E2 config has ≥ 30 trades from ≥ 20 coins (E1 has the same entries) |
   | Identity | mean(Q8 K, X, E2) − mean(Q8-shuffle K, X) > 0. **Vacuous** (passes, flagged) when the shuffled control has < 10 trades: then the entries exist only because of identity |
   | Candidate exit | among E1 and E2, those with mean > 0, mean without the top 2 trades > 0 and matched-control `mean_diff` > 0; the candidate is the one with the higher coin-bootstrap 90 % CI lower bound (ties: higher mean, then E2) |

   (K*, X*) is the qualifying entry definition with the highest candidate CI lower bound (ties: higher mean, then
   the larger K, then the larger X). **Shortlists** (written with `common.write_shortlist`, frozen at the first VAL
   run): `Q8` = the candidate (K*, X*, exit*) and its twin (K*, X*, other exit); `Q8-shuffle` = (K*, X*).
3. If nothing qualifies: **NO_CONFIG** when some (K, X) met the power bar, **UNDERPOWERED_TRAIN** otherwise.
4. **A decision on complete TRAIN is final.** A re-run needs `--rerun-reason` naming a data correction; the previous
   result is archived as `train_prev_<ts>.*`.
5. `--allow-partial` (B2 coverage partial, B1 still ≥ 95 %) writes a **PROVISIONAL** `train_prelim.*`: no shortlist,
   no lock, never unlocks VAL.

### VAL (≤ 2 configs from the written shortlist, plus its shuffled control)

Run the candidate, the twin and the shuffled control once. The decision uses the candidate's VAL trades:

| Decision | Condition | Consequence |
|---|---|---|
| **UNDERPOWERED_VAL** | n < 5 | stop |
| **FAIL_VAL** | n ≥ 5 and (mean ≤ 0 or mean without the top 2 ≤ 0) | stop |
| **SELECTED_UNDERPOWERED** | 5 ≤ n < 15, mean > 0 and mean without the top 2 > 0 | proceed, flagged |
| **SELECTED** | n ≥ 15, mean > 0 and mean without the top 2 > 0 | proceed |

The identity difference on VAL is reported, never decisive.

### TEST (one look for the family, `common.one_shot_session`)

- Run the candidate, the twin and the shuffled control once, inside one session.
- **Verdict** = `common.verdict_entry(test, val=VAL candidate)`: PLAN §3.5 items 1-8 and 10 (mean ≥ +3 %, 90 % CI
  lower bound > 0 under the coin AND the 6-h block bootstrap, without the top 2 > 0, ≥ +6 points over the matched
  control, VAL and TEST same sign, costs × 1.5 > 0, $100 portfolio, ≤ 10 % censored), plus the §3.6
  auto-rejections, plus **Q8.1 identity**: mean(K*, X*, E2) − mean(shuffle) > 0 on TEST (vacuous and non-blocking
  when the shuffled control has < 10 trades). Item 9 (FINAL mean > 0) is judged in the overall verdict.
- **Combination:** REJECTED if `verdict_entry` rejects; UNDERPOWERED if < 60 trades or < 40 coins; FAIL if any
  criterion fails; INCOMPLETE if any is missing; PASS otherwise. With a 1.3-day TEST, UNDERPOWERED is likely.

### CONFIRM (09-16 → 10-01; one look, never searched)

- **Precondition:** TEST is not REJECTED, and TEST mean > 0 or TEST n < 5. Otherwise Q8 failed TEST and CONFIRM is
  not spent.
- Same runs and verdict as TEST. Today CONFIRM has no usable coins and no B1; the stage refuses until it does.

### FINAL (the census day)

- Only after TEST. Candidate, twin and shuffled control once on all census thirds (one session).
- **Criterion 9 (FINAL mean > 0) is judged on the census VAL and TEST thirds only.** The census TRAIN third was the
  debug third (§12); its trades are reported apart.

### Overall Q8 verdict

**EDGE** requires VAL SELECTED or SELECTED_UNDERPOWERED, TEST not REJECTED with (mean > 0 or n < 5), CONFIRM PASS
and FINAL mean > 0. Otherwise **UNDERPOWERED** (TRAIN, VAL or CONFIRM), **NO EDGE**, or **PENDING**.

## 9. Metric, statistics and reporting

- The unit is the net return per $20 trade (`ret_net`), one entry per coin per config.
- Coin-bootstrap CIs (10,000 draws, 90 % and 95 %), the 6-hour block bootstrap, the mean without the top 2 trades,
  the top-coin share, halves, the $100 / 5-slot portfolio, costs × 1.5, the deflated Sharpe ratio counting every
  trial in the ledger, exit reasons, censored (horizon) exits.
- **Every result is reported by G1 class at g + 140 s** (ORGANIC, COMPLETED, OPERATOR, UNRESOLVED; FACTORY and
  INSTANT cannot occur in the B1 universe), so Q8's value beyond the G1 gate is visible.
- Also reported: the cohort size at entry, the number of MECH wallets excluded, and the identity difference per
  (K, X) with its CI.

## 10. Kill criteria (PLAN §8) and declarations

| Rule | How Q8 applies it |
|---|---|
| Stop rule 1 (data first) | V1-V4 and the B1 minimum; stages refuse otherwise |
| Stop rule 2 | Minute-bar worst fills until X1 exists. If X1 finds them off by ≥ 1 point, the frozen pair is re-run with replayed fills before any promotion, with no new search |
| Stop rule 7 | FAIL_VAL is reported to the lead |
| Stop rule 8 | Every config counts (§6) |

**Declarations passed to `auto_rejections`:**

```
uses_organic_flow = True, organic_excludes = [AGENT, BOT, WASH, DUST, MECH]
uses_wallet_reputation = False
uses_truncated_windows = False
uses_current_state_fields = False
```

BOT and WASH are excluded by construction: an A member has no pool sell since g, so it has no buy→sell round trip
and no opposite-side trade. DUST is absent from B1. A is an in-coin flow feature of the coin's own trades up to τ,
not a cross-coin reputation.

## 11. Deviations from the queue spec, stated up front

| Area | Deviation |
|---|---|
| "No orphan sells" | Implied by "no sells" (an orphan sell is a sell). Curve-phase sells before g are allowed, as the spec says "since g" |
| MECH exclusion | "Flagged by M1's MECH-wallet test" is read as flagged at any minute cutoff since g, with M1's 30-minute window, not only at τ |
| E2 | A trail on **closes**, checked on completed bars at each decision, so it fills one bar later; common's mechanical trail uses highs and is not used |
| E1 for placebos | Cohort recomputed at the placebo's own decision (no state crosses to a placebo) |
| Shuffled control | E2 exit only, 4 configs (budget of 12). "Relabelling within each minute" is an independent per-minute permutation over the coin's whole eligible wallet set; a permutation over the minute's own buyers would leave every wallet's distinct-minute count unchanged |
| Placebo | Also requires `alive` and B1 rows (the signal requires both) |
| FINAL | Criterion 9 on the census VAL and TEST thirds; the TRAIN third was debugged on |
| Hold | The g + 118 min deadline caps holds at 58-108 min (entries at g + 10-60 min). The rule is the one Q8 can simulate inside B1 |

## 12. Debug findings and expected sample (census TRAIN third, counts only)

To be filled from `python research/lab2/q8.py --debug` before any official run.
