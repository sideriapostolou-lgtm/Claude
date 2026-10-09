# Z1 pre-registration: buy when the sellers run out while the price holds

- **Version:** `z1-v1`.
- **Written:** 2026-10-09, before any run on TRAIN, VAL, TEST, CONFIRM or FINAL data. TRAIN was still being
  backfilled. Every constant and the whole grid (§6) were fixed in this file **before** the debug run on the census
  TRAIN third (§13), which reports counts only: returns hidden, no parameter chosen there.
- **Code:** `research/lab2/z1.py`, on the shared foundation `research/lab2/common.py`. Tests:
  `research/lab2/tests/test_z1.py`.
- **Protocol:** PLAN §3 (shared protocol), §3.5 (pass bars), §3.6 (automatic rejections) and §8 (stop rules),
  through common.py's `AsOf`, `backtest`, placebo, `describe`, `verdict_entry`, trial ledger, shortlists and
  one-shot sessions. Stage gating and CLI follow `m1.py`.
- **Splits:** common.py's (TRAIN 10-01 → 10-05, VAL → 10-06 12:00, TEST → 10-07 19:37:30, CONFIRM 09-16 → 10-01,
  FINAL = census day).
- **Freeze.** The first official TRAIN run hashes this file into `Z1/prereg.lock`. After that, `z1.py` refuses every
  stage if this file has changed. A change is a new version (`z1-v2`) recorded in `Z1/AMENDMENTS.md`, and every
  config it adds is a new trial.

## 1. Hypothesis and mechanism

**Claim.** At 30-120 min after graduation, a minute-bar window in which **sell SOL per minute and sellers per minute
both fall by at least half, sells shrink faster than buys, and the price holds flat or higher** marks the end of a
selling wave. Buying the next bar and holding 30-60 min earns more than the round trip.

**Why it could beat costs** (round trip 1.4-5.1 % of a $20 ticket by market cap, `common.round_trip_pct`):

1. **The overhang is the main force, and it is finite.** At migration the pool holds ~207 M tokens; the other
   ~793 M sit with curve buyers (snipers, bundlers, insiders, retail) who mostly paid less than the pool price. Their
   exits dominate the first hours: random entries at 30-120 min lost about -7 % per trade on the census day (wave 1,
   bot exits), and "most of these coins are dumped within the first hour" (`research/lab/RESULTS.md`). Each holder
   can sell only its own stack, so the selling wave is front-loaded and runs out.
2. **Its depletion is observable in B2 bars.** A falling count of sellers per minute (wallets ≥ 0.01 SOL) together
   with falling sell SOL means the population still wanting out is shrinking. Those who remain have higher
   reservation prices.
3. **A constant-product pool turns the net flow straight into price.** With no market maker leaning against it, a
   net inflow ΔX moves the price by ((X + ΔX) / X)² − 1. At a pricing reserve X ≈ 100 SOL, +1.5 SOL of net buying is
   +3 %. If buyers keep arriving at the pre-exhaustion rate (the window already shows buys shrinking less than sells,
   and the price holding), the next 30-60 min carry a positive drift that a $20 ticket can capture.
4. **Why it might not be priced in.** These pools have no inventory-holding arbitrageur. Participants see a chart,
   transaction counts and "makers" totals; the *trend* of distinct sellers per minute inside a 10-20 minute window is
   not on those screens. Order-flow persistence is well documented in other markets (Lillo and Farmer 2004); Z1 bets
   on the persistence of seller **depletion**, not on price momentum.

**What would make it fail** (stated before any data):

- **A dying coin**: both sides leave. Guarded (not cured) by the sell-share rule (§3) and the `alive` gate.
- **A lull before an insider dump**: big holders wait, small sellers are gone. Rugs are one swap (wave 1 A3); the
  stop fills on the next bar at the bar's low.
- **Noise**: halving between two 5-minute halves happens by chance. The activity minimums (§3) and the matched
  controls (§9) are there to measure that.
- **Too small**: a real drift below the 1.4-5.1 % round trip.

**Honest prior:** low. The PLAN bar (+3 % net per trade, ≥ 6 points over a matched random entry) asks the signal to
move the outcome about 10 points against the census random-entry baseline.

**Who pays us:** the buyers who keep arriving after the sellers have run out, i.e. buy flow that moves the pool price
above our fill before we sell into it.

### 1.1 Not a duplicate of D1, S1, M1, X2 or wave 1

| Hypothesis | What it conditions on | Z1 differs by |
|---|---|---|
| D1 | a candle dip (dd15 ≥ 25 %) classified by **who** sells (B1 wallets, insiders vs capitulators) | Z1 needs **no dip** and no wallet identity. It is barred from D1's territory by rule: no Z1 entry while dd15 ≥ 0.25 (D1's E1 threshold) |
| S1 | insiders' remaining inventory, from B1 wallet ledgers | Z1 uses aggregate seller counts per minute from B2 bars, on every usable coin (instant graduates too) |
| M1 | a steady price-ignoring **buy** floor on operator coins | Z1 is a **sell-side** condition, any coin class |
| X2 | buyer breadth ranked across concurrent graduates | Z1 is within-coin, seller-side |
| wave-1 F1/F2 | candles only (dips, momentum, breakouts) | Z1 reads flow columns (sellers, sell SOL, buy SOL) that candles do not carry |

## 2. Data and universe

- **Tables:** `graduates`, `b2_coins`, `b2_bars` only, through `common.load()`. No B1, no B3, no CryptoHouse
  queries.
- **Universe:** every usable coin of the split per `common.load` (SOL-quoted, not Mayhem, virtual reserve known,
  complete B2 window [g, g + 180 min)). No class gate: one mechanism, applied everywhere.
- **Stratum** (for the placebo and reports only, never an entry filter): `instant` when `grad_delay_s` ≤ 5 s
  (known at g), else `slow`. A NULL `grad_delay_s` (creation not scanned) means creation > 30 min before g, i.e.
  `slow`.

## 3. Features, as of τ = t − 20 s (all through `common.AsOf`)

Decisions run on common.py's grid (minute boundary + 20 s). Let k be the number of completed minute bars at τ, K the
window length (§6) and h = K / 2. The window is the last K completed bars:

- **early half** E = bars [k − K, k − h);
- **late half** L = bars [k − h, k).

Per half (sums over its bars):

| Symbol | Definition |
|---|---|
| S_E, S_L | sell SOL (`sell_sol`, user-side) |
| N_E, N_L | **seller-minutes**: Σ of per-minute `n_sellers` (distinct wallets selling ≥ 0.01 SOL in that minute). A wallet selling in 3 minutes counts 3 times; B2 has no wallet ids. Both halves are counted the same way |
| B_E, B_L | buy SOL minus AGENT buy SOL (the AGENT column is NaN before `agent_known_at`; nothing is subtracted then; at ages ≥ 30 min BOOST is long over) |
| share_E, share_L | S / (S + B) of the half; undefined when S + B = 0 |

Plus:

| Feature | Definition |
|---|---|
| X_ref | pricing reserve X = x + v after bar k − K − 1 (just before the window) |
| ret_K | close(k − 1) / close(k − K − 1) − 1 |
| dd15 | 1 − close(k − 1) / max(high over the last 15 completed bars): D1's E1 drawdown |
| alive | `AsOf.alive()`: USD volume over 15 min ≥ $1.5k and market cap ≥ $6k |

**EXHAUSTED** (all must hold; k ≥ max(K + 1, 15)):

1. **active early half** (a real selling wave to be exhausted): S_E ≥ 0.01 × X_ref (alone it would move the price
   ~2 %) **and** N_E ≥ 1 × (K − h) (at least one seller per minute on average);
2. **sellers fell:** S_L ≤ 0.5 × S_E **and** N_L ≤ 0.5 × N_E;
3. **sells shrank faster than buys:** share_L < share_E, both defined. Rules out "everyone left" (both sides
   halving keeps the share);
4. **price held:** ret_K ≥ 0;
5. **not a dip:** dd15 < 0.25 (never in D1's E1 state).

All thresholds are round numbers chosen from the mechanism above, not from data.

## 4. Entry rule

Take the first decision time t at which all of these hold; at most one entry per coin:

- age t − g in [30, 120] min. The lower bound is the lab's "no entries in the first 30 min" (BOOST and the first
  dumps are over); the upper bound leaves ≥ 58 min of hold data before the registered deadline (§5);
- `alive`;
- EXHAUSTED.

The order lands at t + 30 s in the next bar (common.py's `FillConfig`), at the bar's **worst** price: max(open, high).

## 5. Exits

| Exit | Rule |
|---|---|
| Stop | −25 % from the entry fill, checked on every bar including the entry bar; fills on the **next** bar at min(open, low) (`exit_delay_bars = 1`) |
| Time | hold limit H (30 or 60 min, §6) from the landing; fills on the next bar at min(open, low) |
| Deadline | **sell no later than g + 178 min** (`exit_by_age_s`): fills by g + 179 min, inside the data, so no trade is censored at the data horizon |
| Sellers return | exit set `sret60` only (§6): once ≥ h bars have completed after the entry decision, exit when the last h completed bars have sell SOL ≥ S_E **or** seller-minutes ≥ N_E of the entry window (the selling wave is back). Fills at min(open, low) of the bar the order lands in |

**Placebo positions** carry no state: their S_E and N_E are recomputed from the bars completed at their own decision
time (the same window rule). When that recomputed early half fails the activity minimum (§3 rule 1), the
sellers-return exit is off for that position (it has no selling wave to compare with), and it keeps the stop, time
and deadline exits.

## 6. The TRAIN grid: exactly 6 configurations, every one a trial

**K ∈ {10, 20} × exit set ∈ {`t30`, `t60`, `sret60`}.**

| Axis | Values | Why |
|---|---|---|
| K (window, bars) | 10, 20 | the two time scales on which a post-graduation selling wave plausibly ends (5 vs 5 and 10 vs 10 minutes) |
| exit set | `t30` = stop + 30 min; `t60` = stop + 60 min; `sret60` = stop + sellers-return + 60 min cap | how long the post-exhaustion drift lasts is the open question; `sret60` is the mechanism's own thesis exit |

Fixed for every config (in each params dict, so any change is a new trial): decline ratio 0.5, activity minimums
(0.01 × X_ref, 1 seller-minute per minute), ret_K ≥ 0, dd15 < 0.25, age [30, 120] min, `alive`, stop 25 %,
deadline g + 178 min, $20, the fill model, the version.

- **Grid size: 6** (the task cap is 12; nothing was padded). Z1 has **6 trials** in total: VAL, TEST, CONFIRM and
  FINAL re-run shortlisted params with the same fills, which common.py counts as the same trials.
- **Fills** (`common.FillConfig(exit_delay_bars=1)`): $20, latency 30 s, entry at max(open, high) of the landing
  bar, exits at min(open, low), stops and time exits filled on the **next** bar, entry-bar stop checks on, costs =
  PumpSwap tier by date and market cap + 10 bps Ultra + 20 bps buffer + network fees, impact on X = x + v.
- **Stress and sensitivity** (same call, never used to select): costs × 1.5; rent $0.22; same-bar exits
  (`exit_delay_bars = 0`, the harness-compatible optimistic reference).

## 7. TRAIN shortlist rule (≤ 2 configs)

A config **qualifies** on TRAIN when all hold:

| Requirement | Bar |
|---|---|
| Sample | ≥ 60 trades from ≥ 40 coins (PLAN §3.5 item 1 sizes; TRAIN is 4 days) |
| Mean net | > 0 |
| Mean without the top 2 trades | > 0 |
| Matched placebo (§9, stratum-matched) `mean_diff` | > 0 |
| Price-matched control (§9) `mean_diff` | > 0: the seller part must add something beyond "price held, no dip" |
| Censored share | ≤ 10 % |

- **Ranking:** the coin-bootstrap 90 % CI lower bound, highest first; ties go to the higher mean, then the smaller K,
  then the exit order `t30`, `t60`, `sret60`.
- **Shortlist** = the top 2 qualifiers (or the only one), in rank order, written with `common.write_shortlist`
  before the first VAL run.
- **Nothing qualifies:** **NO_CONFIG** (Z1 fails on TRAIN) when at least one config met the sample bar, else
  **UNDERPOWERED_TRAIN**.
- A decision on complete TRAIN is final. A re-run needs `--rerun-reason` naming a data correction; the previous
  result is archived as `train_prev_<ts>.*`. `--allow-partial` runs a **PROVISIONAL** TRAIN on partial data that
  writes `train_prelim.*`, never a shortlist or a lock, and never unlocks VAL.

## 8. Later stages (`python research/lab2/z1.py --stage …`)

**Every stage** refuses unless `Z1/PREREG.md` exists (and matches `prereg.lock` once locked), PLAN §8 rule 1 holds
for the split (V1-V4 via `common.validation_gates`), the split's coverage is complete (every chain hour scanned, ≤ 5 %
of tradeable coins missing B2, no mid-run hour, SOL/USD covering the split; FINAL reports its end-of-data coins
instead), and the guarded splits have their flags (`LAB2_ALLOW_TEST`, `LAB2_ALLOW_CONFIRM`, `LAB2_ALLOW_FINAL`, which
`z1.py` never sets).

### VAL (the shortlist, once)

Each shortlisted config runs once, with the placebo, the controls and the stress runs. Per config:

| Decision | Condition |
|---|---|
| UNDERPOWERED_VAL | n < 5 |
| FAIL_VAL | n ≥ 5 and (mean ≤ 0 or mean without the top 2 ≤ 0) |
| SELECTED_UNDERPOWERED | 5 ≤ n < 15, mean > 0 and mean without the top 2 > 0 |
| SELECTED | n ≥ 15, mean > 0 and mean without the top 2 > 0 |

- **Candidate** = the TRAIN rank-1 config if it is SELECTED or SELECTED_UNDERPOWERED; else the rank-2 config if it
  is; else Z1 stops (**FAIL_VAL** if any config failed, else **UNDERPOWERED_VAL**). VAL is a filter, never a ranking.

### TEST (one look, `common.one_shot_session`)

- The candidate runs once as `Z1`, with the placebo, the controls and the stress runs.
- **Verdict** = `common.verdict_entry(test, val=VAL candidate, min_mean=0.03)`: PLAN §3.5 items 1-8 (+3 % mean), item
  10 (≤ 10 % censored) and the §3.6 auto-rejections. Item 9 (FINAL mean > 0) is judged after FINAL, so a missing FINAL
  never makes TEST or CONFIRM incomplete. REJECTED > UNDERPOWERED > FAIL > INCOMPLETE > PASS.
- With a 1.3-day TEST, **UNDERPOWERED is likely.**

### CONFIRM (09-16 → 10-01; one look, never searched)

- **Precondition:** TEST not REJECTED, and TEST mean > 0 or TEST n < 5. Otherwise Z1 failed TEST and CONFIRM is not
  spent.
- Same run and verdict as TEST. CONFIRM is the powered out-of-sample test.

### FINAL (the census day; only after TEST)

- The candidate runs once on all of FINAL (one session; FINAL consumes its thirds).
- **Criterion 9 (mean > 0) is judged on the census VAL and TEST thirds only.** The census TRAIN third was used for the
  debug run (§13), so its trades are reported apart.

### Overall Z1 verdict

**EDGE** requires TRAIN SHORTLISTED, VAL SELECTED or SELECTED_UNDERPOWERED, TEST not REJECTED with (mean > 0 or
n < 5), CONFIRM PASS and FINAL (judged thirds) mean > 0. Otherwise **NO EDGE** or **UNDERPOWERED** (TRAIN, VAL or
CONFIRM), with the stage named.

## 9. Controls

- **Primary matched random control** (PLAN §3.4, `common.backtest` placebo): 20 draws per signal, random coins of the
  same split that are `alive` and in the **signal's stratum** (instant / slow), decision age within ±120 s of the
  signal's, the same exits. It feeds PLAN §3.5 item 5 (≥ +6 points) and the TRAIN shortlist.
- **Price-matched control** (judged on TRAIN only, reported everywhere): the same, but the random entry must also
  satisfy the price part of §3 (ret_K ≥ 0 and dd15 < 0.25, with the config's K). It isolates the seller-side part of
  the signal.
- **Unmatched control** (reported, never judged): `alive` coins of any stratum.

## 10. Metric and statistics

- Unit: net return per $20 trade (`ret_net`), one entry per coin per config.
- Coin-bootstrap 90 / 95 % CIs (10,000 draws) and the 6-hour block bootstrap (common.py); the mean without the top 2
  trades; top-coin share; halves; the $100 / 5-slot portfolio; costs × 1.5; the deflated Sharpe ratio counting every
  trial in the ledger; per stratum; exit reasons (non-debug splits only).

## 11. Kill criteria and declarations

| Rule | How Z1 applies it |
|---|---|
| PLAN §8 rule 1 (data first) | V1-V4 must pass for the split; stages refuse otherwise |
| Rule 2 (fills) | minute-bar worst fills with next-bar stops until X1's replayed fills exist; if replayed fills move the result by ≥ 1 point, the frozen candidate is re-run before any promotion, with no new search |
| Rule 8 (count everything) | 6 trials (§6), logged in `research/lab2/trials.json` |
| TRAIN | NO_CONFIG or UNDERPOWERED_TRAIN stops Z1 |
| VAL | FAIL_VAL stops Z1 (a PLAN §8 rule 7 input) |

Declarations passed to `common.auto_rejections`: `uses_organic_flow = False` (nothing is labelled organic; B is
non-AGENT buy SOL), `uses_wallet_reputation = False`, `uses_truncated_windows = False`,
`uses_current_state_fields = False`.

## 12. Limits, stated up front

| Area | Limit |
|---|---|
| Sellers | B2 counts distinct sellers **per minute**; seller-minutes over a half double-count repeat sellers. A few wallets selling every minute look like many sellers |
| Who sells | no wallet identity (that is D1 / S1); an insider pausing looks like exhaustion |
| Fills | minute bars, worst side, next-bar stops; no sub-minute replay (X1 engine) |
| Hold | B2 ends at g + 180 min; holds are capped at g + 178 min |
| Fees | the pool fee inside user-side buy SOL (≤ 1.25 %) stays in B (it scales both halves alike) |
| SOL/USD | the series must cover the split before any non-debug stage (`common.coverage_problems`) |

## 13. Debug run (census TRAIN third, counts only)

`python research/lab2/z1.py --debug` writes `Z1/debug.md` and `Z1/debug.json`. Returns, exit reasons and placebo
outcomes are hidden; its trials go to a scratch ledger, never to `trials.json`. No constant above was changed after
it ran. Results: see the amendment-free addendum below, written after the run (counts only).
