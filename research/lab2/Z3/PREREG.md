# Z3 pre-registration: buy the dead-cat bounce after a single-seller crash (expected: no edge)

- **Version:** `z3-v1`.
- **Written:** 2026-10-09, before any run on TRAIN, VAL, TEST, CONFIRM or FINAL data. TRAIN is still being
  backfilled. Every constant and the whole grid (§6), the controls (§10) and the predictions (§7) were fixed in this
  file **before** the debug run on the census TRAIN third (§14), which reports counts only: returns hidden, no
  parameter chosen there.
- **Code:** `research/lab2/z3.py`, on the shared foundation `research/lab2/common.py` (every feature through
  `common.AsOf`). Tests: `research/lab2/tests/test_z3.py`.
- **Data:** `graduates`, `b2_coins`, `b2_bars` only (B2 minute bars to g + 180 min). No B1, no B3, no CryptoHouse
  queries.
- **Splits:** common.py's (TRAIN 10-01 → 10-05, VAL 10-05 → 10-06 12:00, TEST 10-06 12:00 → 10-07 19:37:30,
  CONFIRM 09-16 → 10-01, FINAL = census day; the census TRAIN third is debug only).
- **Freeze.** The first official TRAIN run hashes this file into `Z3/prereg.lock`. After that `z3.py` refuses every
  stage if this file changed. A change is a new version (`z3-v2`) in `Z3/AMENDMENTS.md`, and its configs are new
  trials.

## 1. Hypothesis and mechanism

**Claim.** When one completed minute bar closes **≥ 70 % below** where it started, and the minute's sell flow proves
that **one wallet** sold a large slice of the pool (a rug, §3), buying right after the crash and holding 5-60 minutes
captures a dead-cat bounce larger than the round trip, at the fee tier such a crashed coin trades in.

**Why it could beat costs.**

1. **The post-crash pool is thin, so small buying makes a big bounce.** A 70-95 % one-minute crash leaves the pricing
   reserve X = x + v at 22-55 % of what it was: a fresh graduate's X ≈ 85 SOL becomes ≈ 19-47 SOL. In a constant
   product pool a net inflow ΔX lifts the price by ((X + ΔX) / X)² − 1, so +20 % needs only ΔX ≈ 0.095 X ≈ 2-4.5 SOL
   (≈ $200-450) of net buying. Dip-buyer bots, holders averaging down and "community takeover" buyers plausibly bring
   that much within minutes of a crash that the whole chart shows.
2. **The crash seller is price-insensitive.** A rugger empties its stack in one swap and accepts 86-93 % impact
   (`research/lab/RESULTS.md` A3: all 9 census rugs were one sell of 9-13 % of supply). A trade that ignores its own
   impact overshoots any price at which the remaining holders would sell, the classic case for partial reversal of a
   liquidity shock.
3. **Our own costs stay bounded.** At the post-crash state the pool fee is the **floor-level top tier, 1.25 % per
   side** (market cap < 420 SOL), plus 10 bps Ultra and 20 bps buffer; a $20 ticket's impact on X = 20-47 SOL is
   0.4-1 % per side. `common.round_trip_pct` gives a **4.1-5.2 % round trip** at X = 47 → 20 SOL (5.4 % at the 17.6
   SOL floor; 6.1-7.6 % at costs × 1.5). A bounce worth trading must clear that **plus** the worst-fill haircut
   (entry at the landing bar's high, exits at the next bar's low).

**Who would pay us:** the holders who panic-sell into the crash low after we buy, and the late bounce buyers we sell to.

**Why we expect it to fail (stated before any data; the honest prior is strongly negative):**

- **The crash is informed.** The seller is an insider or farm wallet leaving a coin it made; its exit is news that the
  coin's sponsor is gone. Informed impact is permanent, not temporary.
- **Second rugs.** Farm rugs come in **equal stacks** (A3: "the same sizes repeating"), so one rug is often followed by
  the next wallet's identical dump. The catastrophe stop fills on the next bar at its low.
- **Speed.** Dip-buy bots act within seconds. We see the crash only when its minute ends, decide 20 s later and land
  30 s after that, at the landing bar's high. Whatever bounce happens inside the crash minute or the next is not ours.
- **Craft rule G35** ("never wait for a bounce") and the wave-1 dip strategies (F1 lost on every split) point the
  same way.

### 1.1 Not a duplicate of D1, Z1, Z2, M1 or wave 1

| Hypothesis | What it conditions on | Z3 differs by |
|---|---|---|
| D1 E2 | one **oversized** sell of ≥ 4 % of x (≈ 8 % drop) by an **organic** capitulating seller (B1 wallet roles), take profit at half recovery in 5 min, ORGANIC slow coins only | Z3 is the extreme tail D1 would never buy: a ≥ 70 % one-minute crash, i.e. the rug itself (D1's DIST-single). Bars only, every usable coin, instant graduates included |
| Z1 | sellers running out while the price **holds** (Z1 never enters while dd15 ≥ 0.25) | disjoint by construction: every Z3 entry sits ≥ 70 % under its high |
| Z2 | a single large **buy** | Z3 is a single large **sell** |
| M1 | a steady mechanical buy floor; a dump is an exit precursor | Z3 buys after the dump |
| wave-1 F1 | candle dips with a rebound confirmation | Z3 needs the sell-flow proof of one large seller and a ≥ 70 % one-bar close drop, not a candle pattern |

## 2. Data and universe

- **Tables:** `graduates`, `b2_coins`, `b2_bars` through `common.load()`.
- **Universe:** every usable coin of the split per `common.load` (SOL-quoted, not Mayhem, virtual reserve known,
  complete B2 window [g, g + 180 min)). No class gate and no `alive` gate: a crashed coin is the point, and the crash
  minute itself carries its volume.
- **Tag** (reports only, never a filter): the crash depth bin of the entry signal, `d70` (70-80 %), `d80` (80-90 %),
  `d90` (≥ 90 %).

## 3. Features, as of τ = t − 20 s (completed minute bars only, through `common.AsOf`)

For a completed bar j (index from the graduation minute; dense bars, untraded minutes carry the last close):

| Symbol | Definition |
|---|---|
| ref_j | max(open_j, close_{j−1}): the price where the minute started |
| drop_j | 1 − close_j / ref_j |
| X_{j−1} | pricing reserve x + v after bar j − 1 (just before the crash minute) |
| big_j | sell_sol_j / max(n_sellers_j, 1): by pigeonhole, at least one wallet (≥ 0.01 SOL) sold this much SOL in minute j |

**CRASH(j)**: j ≥ 2, bar j traded, and drop_j ≥ **0.70**. The drop is measured on the **close**, so a crash that
already bounced back inside its own minute is not an event (that bounce was never ours to trade).

**SINGLE-SELLER CRASH(j)**: CRASH(j) **and** big_j ≥ **0.25 × X_{j−1}**. A 70 % drop needs a net SOL outflow of at
least 1 − √0.30 = 0.452 of X; 0.25 X is more than half of that, so one wallet's sells alone supplied the majority of
the minimum outflow the crash required (and alone would move the price ≥ 44 %). A stampede of many small sellers fails
this bound and is not a Z3 event.

**POST-CRASH STATE** (the drawdown-matched control's eligibility, §10): at least 3 completed bars; the last close is
≤ 0.30 × the highest open or close of all completed bars (≥ 70 % under the high, the same depth as a signal); **and**
no CRASH bar (any seller pattern) among the last 15 completed bars.

All thresholds are round numbers taken from the mechanism (the task's 70 %, half the required outflow, the medium
hold for "recent"), not from data.

## 4. Entry rule

Decisions run on common.py's grid (minute boundary + 20 s). Let k be the number of completed bars at τ. The entry
is taken at the first decision where the condition of the config's **entry mode** holds; at most one entry per coin:

| Entry mode | Condition at τ |
|---|---|
| `now` | bar k − 1 (the minute that just ended) is a SINGLE-SELLER CRASH |
| `confirm` | bar k − 2 is a SINGLE-SELLER CRASH **and** bar k − 1 traded and closed **above** bar k − 2's close (the first green minute: the cascade paused, a bounce began) |

- Decision age t − g in **[7, 120] min**. The lower bound (g + 420 s) is the end of the BOOST/AGENT window: BOOST
  keeps buying on its 12 s timer whatever the price, a separate mechanical bid (S1 / M1 territory) that would prop a
  bounce during the first 6 minutes. The upper bound leaves ≥ 58 min of hold data before the registered deadline.
- The order lands at t + 30 s in the next bar at the bar's **worst** price, max(open, high).

## 5. Exits (all mechanical; no signal exit)

| Exit | Rule |
|---|---|
| Time | hold H ∈ {5, 15, 60} min (§6) from the landing; fills on the **next** bar at min(open, low) |
| Catastrophe stop | −50 % from the entry fill, checked on every bar including the entry bar; fills on the **next** bar at min(open, low). It exists for the second rug; a tighter stop on a post-crash pool is whipsawed by the worst-fill convention (craft rule G24 tests −35 % to −50 %) |
| Deadline | sell no later than **g + 178 min** (`exit_by_age_s`): fills by g + 179 min, inside the data, so no trade is censored |

## 6. The TRAIN grid: exactly 6 configurations, every one a trial

**entry mode ∈ {`now`, `confirm`} × hold H ∈ {5, 15, 60} min.**

| Axis | Values | Why |
|---|---|---|
| entry mode | `now`, `confirm` | `now` catches a bounce that starts at once (if bots have not taken it); `confirm` waits for proof that the cascade stopped and pays for it with a later, higher entry. Which one is right is the open economic question |
| hold H | 5, 15, 60 min | the three time scales of a dead-cat bounce: dip-buy bots (minutes), human reaction (≈ 15 min), a community-takeover drift (an hour) |

Fixed for every config (in each params dict, so any change is a new trial): CRASH 0.70 on the close, single seller
0.25 X, post-crash state (0.70 under the high, no crash in 15 bars), age [7, 120] min, stop 50 %, deadline g + 178
min, $20, the fill model, the version.

- **Grid size: 6** (the cap is 12; nothing padded). Z3 has **6 trials** in total: VAL, TEST, CONFIRM and FINAL re-run
  shortlisted params with the same fills, which common.py counts as the same trials. The debug run is never counted.
- **Fills** (`common.FillConfig(exit_delay_bars=1)`): $20, latency 30 s, entry at max(open, high) of the landing
  bar, exits at min(open, low), stops and time exits filled on the **next** bar, entry-bar stop checks on, costs =
  PumpSwap tier by date and market cap (1.25 % at the post-crash market cap) + 10 bps Ultra + 20 bps buffer + network
  fees, impact on X = x + v.
- **Stress and sensitivity** (same call, never used to select): costs × 1.5; rent $0.22; same-bar exits
  (`exit_delay_bars = 0`); **optimistic open fills** (entry at the landing bar's open, exits at the next bar's open,
  stops at the level): a diagnostic of how much of any gross bounce the worst-fill convention eats.

## 7. Pre-registered predictions (the falsifiable bar)

Written before any data. They are scored in the TRAIN report and change no decision.

| ID | Prediction | Falsified if (TRAIN) |
|---|---|---|
| P1 | No tradable bounce: every config's mean net (worst fills) ≤ 0 | any config's mean net > 0 |
| P2 | Not even with optimistic fills: every config's mean net under open fills < +3 % (the PLAN bar) | any config ≥ +3 % under open fills |
| P3 | The crash timing adds nothing tradable: every config beats the drawdown-matched control by < 6 points | any config's control `mean_diff` ≥ +6 points |

**The decision bar is §8's, not the predictions.** Z3 is an **entry rule** that earns "EDGE" only through the whole
PLAN §3.5 chain (TRAIN shortlist → VAL → TEST → CONFIRM → FINAL). **Z3 is dead** at the first of: NO_CONFIG or
UNDERPOWERED_TRAIN on TRAIN, FAIL_VAL / UNDERPOWERED_VAL on VAL, TEST mean ≤ 0 on ≥ 5 trades, CONFIRM not PASS,
FINAL mean ≤ 0.

**By-product (report only, never a trial):** a config whose drawdown-matched `mean_diff` 95 % CI lies entirely
below −10 points is reported as evidence for the existing craft rule G35 ("never buy a crash bounce").

## 8. TRAIN shortlist rule (≤ 2 configs)

A config **qualifies** on TRAIN when all hold:

| Requirement | Bar |
|---|---|
| Sample | ≥ 60 trades from ≥ 40 coins (PLAN §3.5 item 1 sizes) |
| Mean net | > 0 |
| Mean without the top 2 trades | > 0 |
| Drawdown-matched control (§10, the placebo) `mean_diff` | > 0 |
| Unmatched control (§10) `mean_diff` | > 0 |
| Censored share | ≤ 10 % |

- **Ranking:** the coin-bootstrap 90 % CI lower bound, highest first; ties go to the higher mean, then the shorter
  hold, then `now` before `confirm`.
- **Shortlist** = the top 2 qualifiers (or the only one), in rank order, written with `common.write_shortlist` before
  the first VAL run.
- **Nothing qualifies:** **NO_CONFIG** (Z3 fails on TRAIN) when at least one config met the sample bar, else
  **UNDERPOWERED_TRAIN**. Both stop Z3.
- A decision on complete TRAIN is final. A re-run needs `--rerun-reason` naming a data correction; the previous
  result is archived as `train_prev_<ts>.*`. `--allow-partial` runs a **PROVISIONAL** TRAIN on partial data that
  writes `train_prelim.*`, never a shortlist or a lock, and never unlocks VAL.

## 9. Later stages (`python research/lab2/z3.py --stage …`)

**Every stage** refuses unless `Z3/PREREG.md` exists (and matches `prereg.lock` once locked), PLAN §8 rule 1 holds
for the split (V1-V4 via `common.validation_gates`), the split's coverage is complete (every chain hour scanned, ≤ 5 %
of tradeable coins missing B2, no mid-run hour, SOL/USD covering the split; FINAL reports its end-of-data coins
instead), and the guarded splits have their flags (`LAB2_ALLOW_TEST`, `LAB2_ALLOW_CONFIRM`, `LAB2_ALLOW_FINAL`, which
`z3.py` never sets).

### VAL (the shortlist, once)

Each shortlisted config runs once, with the placebo, the control and the stress runs. Per config:

| Decision | Condition |
|---|---|
| UNDERPOWERED_VAL | n < 5 |
| FAIL_VAL | n ≥ 5 and (mean ≤ 0 or mean without the top 2 ≤ 0) |
| SELECTED_UNDERPOWERED | 5 ≤ n < 15, mean > 0 and mean without the top 2 > 0 |
| SELECTED | n ≥ 15, mean > 0 and mean without the top 2 > 0 |

- **Candidate** = the TRAIN rank-1 config if it is SELECTED or SELECTED_UNDERPOWERED; else the rank-2 config if it
  is; else Z3 stops (**FAIL_VAL** if any config failed, else **UNDERPOWERED_VAL**). VAL is a filter, never a ranking.

### TEST (one look, `common.one_shot_session`)

- The candidate runs once as `Z3`, with the placebo, the control and the stress runs.
- **Verdict** = `common.verdict_entry(test, val=VAL candidate, min_mean=0.03)`: PLAN §3.5 items 1-8 (+3 % mean; item
  5 = the drawdown-matched control by ≥ +6 points), item 10 (≤ 10 % censored) and the §3.6 auto-rejections. Item 9
  (FINAL mean > 0) is judged after FINAL, so a missing FINAL never makes TEST or CONFIRM incomplete.
  REJECTED > UNDERPOWERED > FAIL > INCOMPLETE > PASS.
- With a 1.3-day TEST, **UNDERPOWERED is likely** if Z3 gets that far.

### CONFIRM (09-16 → 10-01; one look, never searched)

- **Precondition:** TEST not REJECTED, and TEST mean > 0 or TEST n < 5. Otherwise Z3 failed TEST and CONFIRM is not
  spent.
- Same run and verdict as TEST. CONFIRM is the powered out-of-sample test.

### FINAL (the census day; only after TEST)

- The candidate runs once on all of FINAL (one session; FINAL consumes its thirds).
- **Criterion 9 (mean > 0) is judged on the census VAL and TEST thirds only.** The census TRAIN third hosted the debug
  run (§14), so its trades are reported apart.

### Overall Z3 verdict

**EDGE** requires TRAIN SHORTLISTED, VAL SELECTED or SELECTED_UNDERPOWERED, TEST not REJECTED with (mean > 0 or
n < 5), CONFIRM PASS and FINAL (judged thirds) mean > 0. Otherwise **NO EDGE** or **UNDERPOWERED** (TRAIN, VAL or
CONFIRM), with the stage named.

## 10. Controls

- **Drawdown-matched random control = the placebo** (PLAN §3.4, `common.backtest`): 20 draws per signal, random
  coins of the same split in the **POST-CRASH STATE** (§3: ≥ 70 % under their high, no crash in the last 15 bars),
  decision age within ±120 s of the signal's, the same exits. It is the same kind of coin (thin pool, top fee tier,
  same age) at a random time, so it isolates the claim that the **moment right after the crash** is special. It
  feeds PLAN §3.5 item 5 (≥ +6 points) and the TRAIN shortlist.
- **Unmatched control** (TRAIN qualifier, reported everywhere): any usable coin at the same age ±120 s (PLAN §3.4's
  plain random entry).

## 11. Metric, statistics and diagnostics

- Unit: net return per $20 trade (`ret_net`), one entry per coin per config.
- Coin-bootstrap 90 / 95 % CIs (10,000 draws) and the 6-hour block bootstrap (common.py); the mean without the top 2
  trades; top-coin share; halves; the $100 / 5-slot portfolio; costs × 1.5; the deflated Sharpe ratio counting every
  trial in the ledger; per crash-depth tag; exit reasons (non-debug splits only).
- **Cost decomposition** (non-debug only): the mean gross move between the worst-fill prices (`ret_mid`), the mean
  cost (`ret_mid − ret_net`), and the side bps paid at entry (`fee_bps_in` = pool tier + Ultra + buffer; 155 at the
  floor-level tier), so a "bounce exists but costs eat it" result is visible as such.

## 12. Kill criteria and declarations

| Rule | How Z3 applies it |
|---|---|
| PLAN §8 rule 1 (data first) | V1-V4 must pass for the split; stages refuse otherwise |
| Rule 2 (fills) | minute-bar worst fills with next-bar exits until X1's replayed fills exist. If replayed fills move the result by ≥ 1 point, the frozen candidate is re-run before any promotion, with no new search. Rugs gap: minute bars cannot show the sub-minute path, and the worst fill is the honest default |
| Rule 8 (count everything) | 6 trials (§6), logged in `research/lab2/trials.json` |
| TRAIN | NO_CONFIG or UNDERPOWERED_TRAIN stops Z3 |
| VAL | FAIL_VAL stops Z3 (a PLAN §8 rule 7 input) |

Declarations passed to `common.auto_rejections`: `uses_organic_flow = False`, `uses_wallet_reputation = False`,
`uses_truncated_windows = False`, `uses_current_state_fields = False`.

## 13. Limits, stated up front

| Area | Limit |
|---|---|
| "Single seller" | a pigeonhole bound from per-minute totals (B2 has no wallet ids): it proves one wallet sold ≥ big_j, never who. A rug followed in the same minute by many panic sellers can fail the bound (missed event, never a false one) |
| Crash timing | minute resolution: a crash in the last second of a minute and one in the first second look alike; our decision comes 20-80 s after the swap |
| Fills | minute bars, worst side, next-bar exits; no sub-minute replay (X1). A real bot with websocket latency (5 s) could act earlier; this test does not cover it |
| Hold | B2 ends at g + 180 min; holds are capped at g + 178 min |
| Floor | near the supply floor (all circulating tokens back in the pool) the downside is bounded by AMM math; Z3 does not condition on that distance (one mechanism per designer) |
| SOL/USD | the series must cover the split before any non-debug stage (`common.coverage_problems`) |

## 14. Debug run (census TRAIN third, counts only)

`python research/lab2/z3.py --debug` writes `Z3/debug.md` and `Z3/debug.json`. Returns, exit reasons and placebo
outcomes are hidden; its trials go to a scratch ledger, never to `trials.json`. Results are appended below after the
run; **no constant above may change because of them.**

**Run 2026-10-09 02:58 UTC, 52 s** (`Z3/debug.md`). 450 usable coins created over 0.52 days; 50,864 decision minutes
at ages 7-120 min. **No constant above was changed after it ran, and no definition needed a fix.**

| Count (no outcomes) | Census TRAIN third |
|---|---:|
| CRASH bars (≥ 70 % close drop in one minute) at ages 7-120 min | 363 bars on 252 coins |
| ... of which SINGLE-SELLER (the Z3 event) | **3 bars on 3 coins** |
| ... of which a stampede (fails the 0.25 X bound) | 360 |
| CRASH bars before g + 7 min (excluded by the BOOST rule) | 128 bars on 106 coins |
| `confirm` condition met | 1 |
| coin-minutes in the POST-CRASH STATE (control pool) | 35,261 of 50,864 (403 coins) |
| entries `now` / `confirm` (each hold) | 3 / 1 |
| placebo draws (drawdown-matched), `now` / `confirm` | 57 of 60 / 15 of 20 |
| exits at the data horizon | 0 |

**Structure of the crash minutes** (decision-time features only): 307 of the 363 crash bars are on **instant
graduates**; median age 12.8 min; median depth 95 %; median **669 sellers and 1,052 sell trades in the crash
minute**; the pigeonhole bound on the largest seller is median 0.001 X (90th percentile 0.056 X). These are the
factory airdrop dumps (craft rule G14: thousands of wallets each holding ~0.04 % of supply), not single-wallet rugs.
Only 4 crash bars had ≤ 3 sellers, 22 had ≤ 10.

**The 3 single-seller crashes** (1-2 sellers, 73-96 % drop, one wallet ≥ 0.40 X) left the pool at the supply floor:
X after the crash 17.8-20.6 SOL (≈ the virtual reserve: almost no real SOL left), market cap ≈ $2.1-2.7k, pool fee
125 bps (the floor-level top tier), $20 round trip **5.0-5.1 %** (7.4-7.6 % at costs × 1.5): the hurdle any bounce
must clear before the worst-fill haircut.

**Expected samples**, if other days look like the census day (≈ 5.8 `now` signals a day, ≈ 1.9 `confirm`): TRAIN
(4 d) ≈ 23 `now` / ≈ 8 `confirm` trades per config, VAL ≈ 9 / 3, TEST ≈ 8 / 3, CONFIRM (15 d) ≈ 87 / 29.

**What the counts imply, before any TRAIN data:**

- **Z3 as registered is expected to be UNDERPOWERED_TRAIN** (≈ 23 trades against the 60-trade / 40-coin bar), which
  stops it before VAL (§8). That is the pre-registered answer, not a code failure: single-wallet ≥ 70 % crashes are
  rare in the 7-120 min window. Running TRAIN still spends 6 trials.
- **The common ≥ 70 % one-minute crash is a many-wallet stampede on instant graduates**, which the single-seller
  bound excludes by design. A "stampede-crash bounce" is a different mechanism (a coordinated distribution through
  many wallets, not one price-insensitive seller). It would need its own pre-registration and its own trials; it is
  **not** an amendment of Z3, because it would be chosen from these counts.
- The drawdown-matched control is plentiful (69 % of coin-minutes are ≥ 70 % under their high), so the placebo is not
  the binding constraint.
