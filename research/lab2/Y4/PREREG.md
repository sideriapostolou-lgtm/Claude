# Y4 pre-registration: do coins react at round USD market caps? (expected: no edge)

- **Version:** `y4-v1`.
- **Written:** 2026-10-09, before any Y4 run on TRAIN, VAL, TEST, CONFIRM or FINAL data. TRAIN was still being
  backfilled. Every constant, both level sets, the whole grid (§6), the event study (§7), the controls (§10) and the
  predictions (§7.3) were fixed in this file **before** the debug run on the census TRAIN third (§14). That run reports
  counts only: returns, forward moves, exit reasons and placebo outcomes hidden, and no parameter chosen there.
- **Code:** `research/lab2/y4.py`, on the shared foundation `research/lab2/common.py` (every feature through
  `common.AsOf`). Tests: `research/lab2/tests/test_y4.py`.
- **Data:** `graduates`, `b2_coins`, `b2_bars` only (B2 minute bars to g + 180 min), plus the SOL/USD minute series
  common.py loads. No B1, no B3, no CryptoHouse queries.
- **Protocol:** PLAN §3 (shared protocol), §3.5 (pass bars), §3.6 (automatic rejections) and §8 (stop rules), through
  common.py's `AsOf`, `backtest`, matched placebo, `describe`, `verdict_entry`, trial ledger, shortlists and one-shot
  sessions. Stage gating and CLI follow `m1.py` / `z3.py`.
- **Splits:** common.py's (TRAIN 10-01 → 10-05, VAL → 10-06 12:00, TEST → 10-07 19:37:30, CONFIRM 09-16 → 10-01,
  FINAL = census day; the census TRAIN third is debug only).
- **Freeze.** The first official TRAIN run hashes this file into `Y4/prereg.lock`. After that, `y4.py` refuses every
  stage if this file has changed. A change is a new version (`y4-v2`) in `Y4/AMENDMENTS.md`, and its configs are new
  trials.

## 1. Hypothesis and mechanism

**The folklore.** Memecoin traders talk in USD market caps ("it broke 100k", "rejected at 250k", "next stop a
million"). The claim is that round USD market caps act as levels: a **clean break above** a round level is followed by
continuation, while a **touch that closes back below** it is a rejection followed by a fall.

**Y4 tests it twice** (§6, §7):

1. **Event study (the folklore itself, gross of costs).** At every first contact of a level from below, does the
   price move after a clean break differ from the move after a rejection, and is either reaction stronger at round
   levels than at non-round levels placed the same way?
2. **Trading test (net of costs).** Buy the clean break (or its first retest) of a round level, exit when the USD
   market cap closes back below the level or after a fixed hold. Each config has a **shifted-level twin**: the
   identical rule on levels that are not round (×1.28, §3.1). Round minus twin is the roundness effect; the twin
   alone is a plain breakout of an arbitrary level (wave 1 F2's idea).

**Why it could beat costs** (a $20 round trip costs 2.9-4.2 % at $10k-$1M by `common.round_trip_pct`: 4.2 % at
$10k, 3.6 % at $50k, 3.5 % at $100k, 3.3 % at $250k, 2.9 % at $1M; X = 40-410 SOL):

1. **Orders cluster at round numbers.** Trading terminals (Axiom, Photon, BullX, GMGN, Jupiter trigger orders) let
   users set take-profit and limit orders as a USD market cap, and people type round numbers. In FX, Osler (2000,
   2003) found take-profit orders cluster **at** round numbers (so trends stall there) and stop orders cluster just
   **beyond** them (so trends accelerate once crossed). On a pump.fun pool there are no stop-buy orders from shorts,
   but the take-profit supply resting at the level is real: once a buying wave has absorbed it, the next cluster is
   the next round level, 2-2.5× higher, and the path in between is thinner.
2. **Milestone attention.** Alert bots and call channels post milestones ("X just hit $100k"). A clean break is the
   moment those posts go out; the readers who buy arrive over the next minutes. On a constant-product pool there is
   no market maker: a net inflow ΔX on a pricing reserve X moves the price by ((X + ΔX) / X)² − 1, so 5 SOL of
   follow-on net buying at the $100k level (X ≈ 125 SOL) is +8 %, two round trips.
3. **The level is a cheap thesis stop.** If the USD market cap closes back below the level, the break failed and Y4
   sells. The loss of a failed break is about the margin (3 %) plus the next-bar fill and costs; a real continuation
   to the next level pays many round trips. The edge, if any, is that asymmetry.

**What would make it fail** (stated before any data):

- **Wave 1 F2 measured chart breakouts as negative gross** on the census day (`research/lab/reports/f2-momentum.md`,
  464 breakout configs). A round level is still a chart level; Y4 needs roundness to add what F2 lacked.
- **Take-profit bots fill instantly.** If the resting supply at the level is executed in the same minute as the break
  (bots, not humans), the minute bar already contains both the break and the selling: the next minute is the
  rejection, and our worst-side entry buys its top.
- **"The" USD market cap is not one number.** Each platform converts with its own SOL price and some show FDV, so a
  level is blurred by ±1-2 %. A blur that wide removes most of a level's precision.
- **Worst fills.** We enter at the high of the bar after the break bar and exit at the low of the bar after the
  trigger (§5). The continuation must exceed both plus a round trip.
- **Rugs** after the break (wave 1 A3: a rug is one swap); the catastrophe stop fills at the next bar's low.
- **Graduation sits at $42-49k** (410.8 SOL at SOL $103-118) and BOOST pushes most coins to about $62-71k by
  g + 6 min. The $50k level (and the $64k twin level) are crossed mechanically during BOOST; Y4 decides only from
  g + 10 min, so its $50k events are re-takes after a fall below.

**Honest prior:** about 5 % that the candidate passes TEST, and about 15 % that the event study shows a roundness
effect of either sign. The expected result is "round levels behave like any other level, and breakouts do not beat
costs" (§7.3).

**Who would pay us:** the late buyers who arrive on the milestone posts after our fill and before our exit.

### 1.1 Not a duplicate

| Hypothesis | What it conditions on | Y4 differs by |
|---|---|---|
| wave-1 F2 breakouts | the price relative to the coin's own recent highs | Y4 conditions on **absolute round USD market caps**, and carries a shifted-level twin to isolate roundness |
| Y3 | a quiet range, then a breakout bar with broad wallet buying | Y4 has no range or flow condition: the level alone is the mechanism (chart-only on purpose) |
| X2, Z1, Z2, M1, X3, X4 | cross-sectional breadth, sellers running out, a whale print, a mechanical bid, selling climaxes, floor revivals | none of them uses USD market-cap levels |
| D1, S1, Y1, X1 | dips, insiders' inventory, deployer records, early holders | Y4 is B2 bars plus SOL/USD only |

## 2. Data and universe

- **Tables:** `graduates`, `b2_coins`, `b2_bars`, through `common.load()`; SOL/USD through `common.load_sol_usd()`.
- **Universe:** every usable coin of the split per `common.load` (SOL-quoted, not Mayhem, virtual reserve known,
  complete B2 window [g, g + 180 min)). No class gate.
- **Stratum** (placebo matching and reports only, never an entry filter): the **market-cap band**, the number of
  round levels (§3.1) at or below the current USD market cap (0 below $10k, 1 for [$10k, $25k), …, 10 at ≥ $10M).

## 3. Levels and features, as of τ = t − 20 s (all through `common.AsOf`)

Decisions run on common.py's grid (minute boundary + 20 s). Let k be the number of completed minute bars at τ and
b = k − 1 the last completed bar. Dense bars: a minute without trades carries the last close (o = h = l = c) and
zero flow; `traded` marks minutes with ≥ 1 trade. Bar 0 (the partial graduation minute, whose open and low are
rebuilt by common.py) is never used: every window starts at bar ≥ 1.

### 3.1 The two level sets (fixed here, not from data)

| Set | Levels (USD market cap) | Why |
|---|---|---|
| `round` | $10k, $25k, $50k, $100k, $250k, $500k, $1M, $2.5M, $5M, $10M | the 1-2.5-5 sequence: the gridlines chart scales use and the numbers people type |
| `shifted` (twin) | `round` × 1.28: $12.8k, $32k, $64k, $128k, $320k, $640k, $1.28M, $3.2M, $6.4M, $12.8M | the same count and the same 2-2.5× spacing, but non-round |

**Why 1.28.** Over factors 1.10-1.90 in steps of 0.005, 1.28 maximizes the smallest log-distance between every
shifted level's break zone [L, 1.03 L] and the salient numbers {1, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 7.5, 8, 9} × 10ⁿ
(≈ 6 %). A factor like 1.37 or 1.4 would put the twin's break zone on 70k, 350k or 700k, which are round too. The
choice used arithmetic only, no data.

**USD conversion.** A USD level L becomes a price in SOL per token as L / (`AsOf.sol_usd` × 1e9): `sol_usd` is the
SOL/USD close of the last minute that ended before τ. All levels at one decision use that one SOL price (over a
10-15-minute window SOL moves far less than the 3 % margin). `mcap_usd` = `AsOf.mcap_usd` (last completed close ×
1e9 × the same SOL price).

### 3.2 Events

Constants: N = 10 bars (approach window), m = 0.03 (break margin), W = 15 bars (retest window), ρ = 0.03 (retest
band).

| Event at bar b (or r) | Definition (levels of the config's set, converted at the decision's SOL price) |
|---|---|
| **BREAK** at b | b traded; L\* = the highest level with L\* × (1 + m) ≤ close(b); and every close of the N bars before b is < L\* (an approach from below, not a level the coin was sitting on). b − N ≥ 1 |
| **RETEST** at r | the most recent BREAK bar b in [r − W, r − 1] (at level L\*) has every close of bars b + 1 … r ≥ L\* (the level never lost), every low of bars b + 1 … r − 1 > L\* (1 + ρ) (no earlier retest), r traded, and low(r) ≤ L\* (1 + ρ): the price came back to the level and closed on or above it |
| **TOUCH** at b (event study only) | b traded; L = the highest level with high(b) ≥ L and every high of the N bars before b < L (the first contact from below in N minutes). Its class: **BREAK** when close(b) ≥ L (1 + m), **HOLD** when L ≤ close(b) < L (1 + m), **REJECT** when close(b) < L |

All thresholds are round numbers fixed from the mechanism and the cost model, not from data: N = 10 minutes is "the
coin has been below for a while"; m = 3 % is about one round trip ("clean"); W = 15 minutes and ρ = 3 % are the
usual "break and retest" picture at minute resolution.

## 4. Entry rule

At the first decision time t at which the config's event holds on the last completed bar (BREAK at b = k − 1, or
RETEST at r = k − 1), at most one entry per coin:

- decision age t − g ∈ [10, 115] min. The lower bound is after BOOST (≈ g + 6 min) and the AGENT window (g + 7 min);
  the approach window also forces t − g ≳ 12 min. The upper bound leaves ≥ 60 min of hold inside the data;
- buy $20. The order lands at t + 30 s in the bar after the event bar and fills at that bar's **worst** price,
  max(open, high) (`common.FillConfig`).
- The trade is tagged with its level (e.g. `100k`, `128k`), which is reported, never selected on.

## 5. Exits

| Exit | Rule |
|---|---|
| Level lost (thesis) | at a decision whose last completed bar was completed **after** the entry decision, sell when `mcap_usd` < L\* (the USD market cap closed back below the level). The order lands 30 s later in the next bar and fills at min(open, low) |
| Catastrophe stop | −25 % from the entry fill, checked intrabar on every bar including the entry bar; fills on the **next** bar at min(open, low) (`exit_delay_bars = 1`) |
| Time | H min from the landing (H ∈ {15, 60}, §6); fills on the next bar at min(open, low) |
| Deadline | sell no later than g + 178 min (`exit_by_age_s`). With entries ≤ g + 115 min and holds ≤ 60 min it practically never binds, and no trade can be censored at the data horizon |

**Placebo positions** carry no state. Their reference level is recomputed from the bar completed at their own
decision: break configs use the highest level with L (1 + m) ≤ that close, retest configs the highest level ≤ that
close (for a BREAK or RETEST signal this is L\* itself, except a retest bar that closed above the next level).
Because the placebo's decision-time SOL price is not visible to the exit rule, the placebo converts that close at the
current SOL price; this changes its level only when the close lies within the SOL drift since the decision of a
level boundary. A placebo with no level below its decision close has no thesis stop.

## 6. The TRAIN grid: exactly 8 configurations, every one a trial (+ 1 event-study trial)

**entry ∈ {`break`, `retest`} × hold H ∈ {15, 60} min × levels ∈ {`round`, `shifted`}.**

| Axis | Values | Why |
|---|---|---|
| entry | `break`, `retest` | the folklore's two versions: buy the clean break, or buy the first successful retest ("old resistance becomes support"), whose thesis stop is tighter |
| H | 15, 60 min | the two time scales of the mechanism: a milestone-alert cascade (minutes) and a run toward the next level (an hour) |
| levels | `round` (§3.1), `shifted` | `round` is the hypothesis. **`shifted` configs are pre-registered controls, never selectable**: each is the identical rule on non-round levels, so round − shifted measures what roundness adds |

Fixed for every config (in each params dict, so any change is a new trial): both level sets, N = 10, m = 0.03,
W = 15, ρ = 0.03, the decision ages [10, 115] min, the level-lost exit, the catastrophe stop 25 %, the deadline
g + 178 min, $20, the fill model, the placebo design, the version.

- **Grid size: 8** (the task cap is 12; nothing padded: 4 selectable configs and their 4 twins). With the event study
  (§7) Y4 has **9 trials** in total. VAL, TEST, CONFIRM and FINAL re-run shortlisted params with the same fills,
  which common.py counts as the same trials.
- **Fills** (`common.FillConfig(exit_delay_bars=1)`): $20, latency 30 s, entry at max(open, high) of the landing
  bar, exits at min(open, low), stop and time exits filled on the **next** bar, entry-bar stop checks on, costs =
  PumpSwap tier by date and market cap + 10 bps Ultra + 20 bps buffer + network fees, impact on X = x + v.
- **Stress and sensitivity** (same call, never used to select): costs × 1.5; rent $0.22; same-bar exits
  (`exit_delay_bars = 0`); open fills (the optimistic reference).

## 7. The event study (the folklore test; TRAIN; reported, never decisive)

Logged as one trial, `Y4-eventstudy`, before the grid runs.

### 7.1 Observations and labels

- Every TOUCH (§3.2) of either level set at a decision age in [10, 115] min (one observation per set per touch bar).
- **Labels** (outcomes, read through `AsOf` 15 and 60 minutes later, never features): the mid-price change
  close(b + H) / close(b) − 1 for H = 15 and 60 bars, when b + H is inside the data. Also reported at each touch:
  the $20 round trip at the decision state (the cost hurdle).

### 7.2 Statistics

- Per (set, class, H): n, coins, mean, median, coin-bootstrap 95 % CI.
- **Roundness effect** per class and H: mean(round) − mean(shifted), with a joint coin-bootstrap 95 % CI (coins are
  resampled once and both sets' observations of the drawn coins are used).
- **Reaction spread** per set and H: mean(BREAK) − mean(REJECT); and its round − shifted difference.
- Per-level counts and means (diagnostic).

### 7.3 Pre-registered predictions (scored on TRAIN; reports, never decisive)

| ID | Folklore says | Y4 expects | Scored as "folklore supported" when |
|---|---|---|---|
| P1 | continuation is stronger after breaking a round level | no roundness effect | the BREAK roundness effect at H = 15 has a 95 % CI above 0 |
| P2 | rejection is stronger at a round level | no roundness effect | the REJECT roundness effect at H = 15 has a 95 % CI below 0 |
| P3 | a clean round break pays for itself | it does not | the round BREAK mean at H = 15 exceeds the median round trip at those touches |
| P4 | (trading test) | no round config qualifies on TRAIN | `decide_train` returns SHORTLISTED |

## 8. TRAIN shortlist rule (a pair)

A `round` config **qualifies** on TRAIN when all hold:

| Requirement | Bar |
|---|---|
| Sample | ≥ 60 trades from ≥ 40 coins (PLAN §3.5 item 1 sizes) |
| Mean net | > 0 |
| Mean without the top 2 trades | > 0 |
| Matched placebo (§10, band-matched) `mean_diff` | > 0 |
| Mean − its `shifted` twin's mean | > 0 (undefined when the twin has no trade: then it does not qualify) |
| Censored share | ≤ 10 % |

- **Ranking:** the coin-bootstrap 90 % CI lower bound, highest first; ties go to the higher mean, then `break` before
  `retest`, then the shorter hold.
- **Shortlist** = the **pair** (rank-1 `round` config, its `shifted` twin), written with `common.write_shortlist`
  before the first VAL run. The twin rides along so VAL / TEST / CONFIRM can report round − shifted out of sample; it
  is never the candidate.
- **Nothing qualifies:** **NO_CONFIG** (Y4 fails on TRAIN) when at least one `round` config met the sample bar, else
  **UNDERPOWERED_TRAIN**. Either stops Y4.
- A decision on complete TRAIN is final. A re-run needs `--rerun-reason` naming a data correction; the previous
  result is archived as `train_prev_<ts>.*`. `--allow-partial` runs a **PROVISIONAL** TRAIN on partial data that
  writes `train_prelim.*`, never a shortlist or a lock, and never unlocks VAL.

## 9. Later stages (`python research/lab2/y4.py --stage …`)

**Every stage** refuses unless `Y4/PREREG.md` exists (and matches `prereg.lock` once locked), PLAN §8 rule 1 holds
for the split (V1-V4 via `common.validation_gates`), the split's coverage is complete (every chain hour scanned, ≤ 5 %
of tradeable coins missing B2, no mid-run hour, SOL/USD covering the split; FINAL reports its end-of-data coins
instead), and the guarded splits have their flags (`LAB2_ALLOW_TEST`, `LAB2_ALLOW_CONFIRM`, `LAB2_ALLOW_FINAL`, which
`y4.py` never sets).

### VAL (the shortlisted pair, once)

Both configs run once, with the placebo, the controls and the stress runs. The decision uses the candidate's trades:

| Decision | Condition |
|---|---|
| UNDERPOWERED_VAL | n < 5 |
| FAIL_VAL | n ≥ 5 and (mean ≤ 0 or mean without the top 2 ≤ 0) |
| SELECTED_UNDERPOWERED | 5 ≤ n < 15, mean > 0 and mean without the top 2 > 0 |
| SELECTED | n ≥ 15, mean > 0 and mean without the top 2 > 0 |

### TEST (one look, `common.one_shot_session`)

- The candidate and its twin run once each inside the family's one session, with the placebo, the controls and the
  stress runs.
- **Verdict** on the candidate = `common.verdict_entry(test, val=VAL candidate, min_mean=0.03)`: PLAN §3.5 items 1-8
  (+3 % mean), item 10 (≤ 10 % censored) and the §3.6 auto-rejections. Item 9 (FINAL mean > 0) is judged after FINAL.
  REJECTED > UNDERPOWERED > FAIL > INCOMPLETE > PASS.
- **Reported, never judged:** round − shifted (candidate mean minus twin mean).

### CONFIRM (09-16 → 10-01; one look, never searched)

- **Precondition:** TEST not REJECTED, and TEST mean > 0 or TEST n < 5. Otherwise Y4 failed TEST and CONFIRM is not
  spent.
- Same pair, same verdict as TEST. CONFIRM is the powered out-of-sample test.

### FINAL (the census day; only after TEST)

- The pair runs once on all of FINAL (one session; FINAL consumes its thirds).
- **Criterion 9 (mean > 0) is judged on the census VAL and TEST thirds only.** The census TRAIN third hosted the debug
  run (§14), so its trades are reported apart.

### Overall Y4 verdict

**EDGE** requires TRAIN SHORTLISTED, VAL SELECTED or SELECTED_UNDERPOWERED, TEST not REJECTED with (mean > 0 or
n < 5), CONFIRM PASS and FINAL (judged thirds) mean > 0. Otherwise **NO EDGE** or **UNDERPOWERED** (TRAIN, VAL or
CONFIRM), with the stage named. The event study's answer to the folklore (§7) is reported next to it whatever the
trading verdict.

## 10. Controls

- **Primary matched random control** (PLAN §3.4, `common.backtest` placebo): 20 draws per signal, random coins of the
  same split with `mcap_usd` ≥ $10k, in the **signal's market-cap band** (§2, always the `round` bands so round and
  shifted configs share one matching), decision age within ±120 s of the signal's, the same exits (§5). It feeds PLAN
  §3.5 item 5 (≥ +6 points) and the TRAIN shortlist.
- **Shifted-level twin** (judged on TRAIN, reported later): §6. It isolates roundness from "a breakout".
- **Unmatched control** (reported, never judged): any coin with `mcap_usd` ≥ $10k at the same age.

## 11. Metric and statistics

- Unit: net return per $20 trade (`ret_net`), one entry per coin per config.
- Coin-bootstrap 90 / 95 % CIs (10,000 draws) and the 6-hour block bootstrap (common.py); the mean without the top 2
  trades; top-coin share; halves; the $100 / 5-slot portfolio; costs × 1.5; the deflated Sharpe ratio counting every
  trial in the ledger; per level; the gross move at worst fills and the cost; exit reasons (non-debug splits only).

## 12. Kill criteria and declarations

| Rule | How Y4 applies it |
|---|---|
| PLAN §8 rule 1 (data first) | V1-V4 must pass for the split; stages refuse otherwise |
| Rule 2 (fills) | minute-bar worst fills with next-bar stops until X1's replayed fills exist; if replayed fills move the result by ≥ 1 point, the frozen candidate is re-run before any promotion, with no new search |
| Rule 8 (count everything) | 9 trials (§6, §7), logged in `research/lab2/trials.json` |
| TRAIN | NO_CONFIG or UNDERPOWERED_TRAIN stops Y4 |
| VAL | FAIL_VAL stops Y4 (a PLAN §8 rule 7 input) |

Declarations passed to `common.auto_rejections`: `uses_organic_flow = False`, `uses_wallet_reputation = False`,
`uses_truncated_windows = False`, `uses_current_state_fields = False`. Y4 reads no flow and no wallet at all.

## 13. Limits, stated up front

| Area | Limit |
|---|---|
| Levels | minute closes, highs and lows; a level crossed and lost inside one minute is a TOUCH (event study) but never a BREAK |
| USD | one SOL/USD minute series (Coinbase/Binance closes via `common.load_sol_usd`); platforms differ by ±1-2 % |
| Placebo level | converted at the SOL price of the exit check, not of the decision (§5) |
| Fills | minute bars, worst side, next-bar stops; no sub-minute replay (X1 engine) |
| Hold | B2 ends at g + 180 min; entries ≤ g + 115 min, holds ≤ 60 min; levels reached later are not observed |
| Graduation zone | $50k and $64k are crossed by BOOST for most coins (§1); events there are re-takes from below after g + 10 min |
| SOL/USD | the series must cover the split before any non-debug stage (`common.coverage_problems`) |

## 14. Debug run (census TRAIN third, counts only)

**The run.** `python research/lab2/y4.py --debug` (2026-10-09 03:15 UTC, 43 s) wrote `Y4/debug.md` and
`Y4/debug.json`: 450 usable coins created over 12.5 h (0.52 days), 47,264 decision minutes at ages 10-115 min.
Returns, forward moves, exit reasons and placebo outcomes are hidden; its trials went to a scratch ledger
(`scratchpad/lab2_debug/y4_debug_trials.json`), never to `trials.json`. **No constant, level, grid value or rule above
was changed after it** (no definition correction was needed: the tests, not this run, fixed the code).

**Counts, and extrapolations that assume the census day's rate (≈ 865 usable coins a day) holds on other days:**

| Measure | Census TRAIN third (0.52 d) | Per day | TRAIN (4 d) | VAL (1.5 d) | TEST (1.32 d) | CONFIRM (15 d) |
|---|---:|---:|---:|---:|---:|---:|
| `break` trades, round (= coins) | 47 | ≈ 90 | ≈ 360 | ≈ 135 | ≈ 120 | ≈ 1,350 |
| `retest` trades, round | 26 | ≈ 50 | ≈ 200 | ≈ 75 | ≈ 66 | ≈ 750 |
| `break` trades, shifted twin | 48 | ≈ 92 | ≈ 370 | ≈ 140 | ≈ 120 | ≈ 1,380 |
| `retest` trades, shifted twin | 21 | ≈ 40 | ≈ 160 | ≈ 60 | ≈ 53 | ≈ 600 |
| Event-study touches, round (BREAK / HOLD / REJECT) | 136 (35 / 55 / 46), 90 coins | ≈ 260 | ≈ 1,045 (≈ 270 / 420 / 355) | | | |
| Event-study touches, shifted (BREAK / HOLD / REJECT) | 154 (38 / 71 / 45), 92 coins | ≈ 295 | ≈ 1,185 | | | |

- **Levels of the round `break` trades:** $10k 12, $25k 6, $50k 11, $100k 8, $250k 6, $500k 2, $1M 2. Only 18 of 47
  (38 %) are at the folklore's headline levels (≥ $100k); the per-level table (§11) reports them apart.
- **At each coin's first round BREAK:** market cap median $56.9k (IQR $20.6k-$122.9k), age median 39 min (IQR
  22-51), $20 round trip median 3.56 % (IQR 3.45-3.92 %), fee tier 1.25 % (18 coins) / 1.20 % (19) / 1.15 % (6) /
  1.00 % (4).
- **No trade reached the data horizon** (0 horizon exits in every config): the deadline design holds.
- **The band-matched placebo** found 341 draws for 47 `break` signals (≈ 7 of the 20 per signal within common.py's
  200 tries) and 171 for 26 `retest` signals: high bands have few coins at a given age. The comparison is still per
  signal (`placebo_compare`); fewer draws only widen its CI.

**What these counts imply, before any TRAIN data:**

- Every config is expected to be **powered on TRAIN** (≥ 60 trades from ≥ 40 coins) and the `break` configs even on
  TEST (≈ 120 expected trades). An UNDERPOWERED verdict is not the likely outcome; a clean NO_CONFIG or FAIL is.
- The event study is expected to hold ≈ 270 round BREAK and ≈ 355 round REJECT touches on TRAIN, enough to see a
  roundness effect of a few points at H = 15 if one exists.
- `break|h15` and `break|h60` (and the two `retest` configs) share their entries by construction: the hold is the
  only difference, so their trial count overstates the independent looks (the ledger counts them anyway).
