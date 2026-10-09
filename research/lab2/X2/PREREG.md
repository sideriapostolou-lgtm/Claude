# X2 pre-registration: buy the broadest buying among concurrent graduates

- **Version:** `x2-v1`.
- **Written:** 2026-10-09, before any run on TRAIN, VAL, TEST, CONFIRM or FINAL data. The only run so far is the
  debug run on the census TRAIN third (§15): counts only, returns hidden, no parameter chosen there.
- **Code:** `research/lab2/x2.py`, on the shared foundation `research/lab2/common.py`. Tests:
  `research/lab2/tests/test_x2.py`.
- **Protocol:** PLAN §3 (shared protocol), §3.5 (pass bars), §3.6 (rejections) and §8 (stop rules), through
  common.py's `backtest`, `placebo`, `describe`, `verdict_entry`, trial ledger and shortlists.
- **Splits:** common.py's (TRAIN 10-01 → 10-05, VAL → 10-06 12:00, TEST → 10-07 19:37:30, CONFIRM 09-16 → 10-01,
  FINAL = census day).
- **Freeze.** The first official TRAIN run hashes this file into `X2/prereg.lock`. After that, `x2.py` refuses every
  stage if this file changed. A change is a new version (`x2-v2`) in `X2/AMENDMENTS.md`, and its configs are new
  trials.

## 1. Hypothesis and mechanism

**Attention is rivalrous across concurrent graduates.** About 36 tradeable coins graduate per hour. Traders cannot
watch them all, so they look at rankings: trending lists, "movers", Telegram trackers. Those lists rank coins
*against each other at the same moment*, and the coin on top gets the next wave of eyeballs whatever the market's
absolute level is. Individual-investor attention buying is documented in equities (Barber and Odean 2008: net buying
concentrates in attention-grabbing names). The claim tested here:

> At a fixed age after graduation, the coins whose **buyer breadth** (distinct buyers per minute, ex-AGENT) is in the
> **top decile of the coins that reached the same age in the last 3 hours** keep attracting net buying for the next
> 30-60 minutes, enough to beat a $20 round trip and a random pick of the same age.

- **Why breadth and not volume.** Volume is cheap to paint (one wallet churning, dust bots). Breadth counts wallets
  with ≥ 0.01 SOL in the minute, so one wallet adds at most 1 per minute however much it trades. Many distinct buyers
  is the visible footprint of attention.
- **Why cross-sectional and not an absolute threshold.** An absolute breadth bar fires on every coin in a hot hour
  and on none in a quiet one. The rank keeps the comparison inside one market regime (SOL moves, launch heat) and
  matches how attention is allocated (top of a list). Wave 1 tested only absolute, per-coin rules.
- **Why net flow > 0 is required.** High breadth with net selling is many small buyers absorbing a few large sellers:
  insiders distributing into attention. S1 and D1 both treat that as the losing case. X2 requires the window's net
  flow to be positive.
- **Who loses.** The later attention buyers we sell to, and holders who sell into the rising cohort early. If the
  attention wave is already priced by faster bots at our 30 s latency, nobody loses to us and X2 fails.

**Why it could beat costs.** A $20 round trip costs 1.4-5.1% by market cap (`common.round_trip_pct` gives 3.5-4.2%
at 60-1,000 SOL on a fresh pool), plus the worst-fill spread (entry at the landing bar's high, exits at the next bar's
low). Coins in the top breadth decile trade at higher market caps (lower fee tier, deeper pool), and an attention
wave on a 100-200 SOL pricing reserve moves price by tens of percent: 10 SOL of extra net buying on X = 100 SOL is
+21% (price ∝ X² on a constant-product pool).

**Why it may not (stated before any data).** Wave 1 found that momentum entries (breakouts, "early strength")
lose *before* costs because most coins rug to the ~17.6 SOL floor within an hour. Breadth at g + 30 may be the
crowd arriving just before the insiders sell. My prior that X2 passes TEST is about 10%.

## 2. Instrument: why bar-level breadth, and why net flow is not the ranking score

1. **Data.** Only `graduates`, `b2_coins` and `b2_bars` are used (B1 raw trades are not required, and nothing
   depends on them). B2 bars cover [g, g + 180 min) of every graduate.
2. **Breadth.** `b2_bars.n_buyers` counts wallets with ≥ 0.01 SOL of buys in one clock minute. Over a window X2 uses
   the **mean per minute** ("buyer-minutes per minute"). It double-counts a wallet that buys in several minutes (a
   wallet buying every minute adds 1 to every minute); distinct buyers over the window lie between the mean and
   10 × the mean. That is a property of the instrument, applied identically to every coin.
3. **AGENT and pooled accounts.** The AGENT (BOOST) is removed as one buyer in every minute where its known buys are
   ≥ 0.01 SOL, and its SOL is removed from flows. It ends by about g + 6 min, so it never falls inside a window that
   starts at g + 20 min, but the rule is implemented and tested. Pooled program accounts (`ARu4n5mF…`) cannot be
   removed from bar counts. They count as **one** buyer per minute although several users sign through them, so they
   can only understate breadth.
4. **Not "organic".** Bots, wash and MECH wallets with ≥ 0.01 SOL are inside `n_buyers`; only B1 can remove them.
   X2 therefore never calls its breadth organic (PLAN §3.6 rejects counting those roles as organic) and declares
   `uses_organic_flow = False`.
5. **Why net flow per unit of market cap is not the score.** On a constant-product pool the window's net SOL flow,
   minus fees, *is* the change of the pricing reserve X = x + v, and price = X² / k. So net flow / X (or / market cap)
   is a monotone function of the window's own price return: ranking by it is cross-sectional chart momentum, which
   wave 1's F2 found negative before costs. Net flow enters X2 only as the entry gate (net flow > 0) and as a
   **diagnostic** ranking (`pressure` = net flow / X) in the dose-response table (§8), where it shows whether breadth
   adds anything beyond the price path. The debug run checks the identity on real bars (§15).

## 3. Features at a decision time t, as of τ = t − 20 s (all through `common.AsOf`)

The **window** is the last 10 completed minute bars (bars ending at or before τ). Per minute m: `n_buyers`,
`buy_sol`, `sell_sol`, `agent_buy_sol` (NaN, i.e. 0, before the AGENT is knowable).

| Feature | Definition |
|---|---|
| `breadth` | mean over the 10 window minutes of max(`n_buyers` − 1[`agent_buy_sol` ≥ 0.01], 0) |
| `netflow` | Σ (`buy_sol` − `agent_buy_sol` − `sell_sol`) over the window, SOL |
| `pressure` | `netflow` / X, X = pricing reserve after the last completed bar (diagnostic only) |
| `alive` | `AsOf.alive()`: USD volume over 15 min ≥ $1,500 and market cap ≥ $6,000 (PLAN / F3 rule) |
| `class` | PLAN §4.2 rules as in M1: OPERATOR (w120 buy SOL ex-AGENT ≥ 500 and ≤ 30 buyers ex-AGENT), FACTORY (`grad_delay_s` ≤ 5 and w120 top-5 share ex-AGENT ≥ 0.85), else OTHER; NULL inputs give NULL (§11 X2.1, controls). Never an entry condition |

## 4. The cross-sectional rank (the only new ingredient)

- **Checkpoint.** For a checkpoint c (minutes), a coin's checkpoint time t_c is the first decision-grid time
  (minute boundary + 20 s) with age ≥ c min. This is exactly the engine's first decision at that age.
- **Reference pool of coin i** at its checkpoint time t_i: every **other** usable coin j of the same split that was
  `alive` at **its own** checkpoint time t_j, with t_i − 3 h < t_j ≤ t_i. Its score is coin j's `breadth` at t_j.
  Every input therefore became knowable at τ_j ≤ τ_i: no coin graduating after coin i, and no datum after τ_i,
  enters coin i's rank (unit-tested by garbling every coin's data after τ_i).
- **Percentile** of coin i: pct = (#{ref < s_i} + ½ #{ref = s_i}) / n_ref.
- **Warm-up.** No decision when n_ref < 30 (the first ~1-2 h of a split, and thin hours). These are counted.
- **Same split only.** The pool holds coins of the split being run, so a run never reads another split's bars. FINAL
  is one dataset (its three census thirds are contiguous and ranked together).

## 5. Entry rule

At the coin's checkpoint time t_c, once per coin and config:

1. `alive`;
2. `netflow` > 0;
3. n_ref ≥ 30;
4. **pct ≥ 0.90** (top decile; fixed, never searched).

If all hold, buy $20; otherwise never trade this coin under this config (`SKIP`).

## 6. Exits (relative to the entry fill; fills per §7)

| Exit | Rule |
|---|---|
| Time | hold H minutes from landing (`max_hold_s`) |
| Catastrophe stop | −50% from the entry fill (PLAN X1 exit 6; a tight stop on these coins is noise, and rugs gap through any stop) |
| Fade (exit set `time+fade` only) | at a decision with ≥ 5 completed bars after the entry decision: `breadth` over the last 5 completed bars < 0.5 × the entry `breadth` **and** `netflow` over those 5 bars < 0 (EXPERIENCE G31 / EX-11: attention gone and sellers dominate) |
| Registered deadline | sell no later than g + 178 min (`exit_by_age_s`). With c + H ≤ 120 min it never binds, so no trade can end on the data horizon |

**Placebo positions** carry no state: their entry `breadth` is recomputed from the bars completed at their own
decision, so they run the same fade rule.

## 7. The TRAIN grid: exactly 8 configurations, every one a trial

**checkpoint c ∈ {30, 60} min × hold H ∈ {30, 60} min × exit set ∈ {`time`, `time+fade`}.**

| Dimension | Why each value |
|---|---|
| c = 30 | the earliest the lab allows (no entries in the first 30 min; losses concentrate there) |
| c = 60 | after the factory farms' crash window (g + 15-30 min) and the airdrop dumps; "second-wave" attention |
| H = 30, 60 | the mechanism does not pin how long attention persists |
| `time` / `time+fade` | the plain hold against the thesis exit that leaves when breadth collapses |

Every constant of §3-§6, the fill model and the version are inside each config's params, so any change is a new
trial. **X2's trials:** 8 configs + 1 dose-response check (`X2-dose`, §8) = **9**, on top of the ledger's count.
TEST, CONFIRM and FINAL run the single candidate inside the family's one `common.one_shot_session`.

**Fills and costs** (`common.FillConfig(exit_delay_bars=1)`):

| Setting | Value |
|---|---|
| Size | $20 |
| Latency | 30 s: the order lands in the bar after the decision |
| Entry fill | worst: max(open, high) of the landing bar |
| Exits | **next-bar**: a stop, time or fade exit triggered in bar j fills at min(open, low) of bar j + 1 |
| Entry-bar exits | on (the stop is checked against the entry bar too) |
| Costs | PumpSwap tier by date and market cap, + 10 bps Ultra, + 20 bps buffer, impact on the pool's own k, network fees |

**Stress runs** from the same call, never used to select: costs × 1.5; rent $0.22; latency 60 s.

## 8. Dose-response gate (TRAIN, before any strategy P&L; a stop rule)

- **Observations.** Every TRAIN coin at each checkpoint c ∈ {30, 60} that meets entry conditions 1-3 (alive, net
  flow > 0, n_ref ≥ 30), with its causal breadth percentile (§4).
- **Label** (an outcome, never a feature): the net return of a $20 entry at that decision with the fills of §7, a
  60-minute hold and the −50% stop (`time` exit), via `common.run_entries`.
- **Bins** by percentile: [0, 0.5), [0.5, 0.8), [0.8, 0.9), [0.9, 1.0]; the last bin is exactly the traded decile.
- **Per checkpoint:**

  | Result | Condition |
  |---|---|
  | UNDERPOWERED | fewer than 30 coins in the top bin |
  | PASS | mean(top bin) > mean(all observations) **and** the four bin means rise with at most one adjacent inversion |
  | FAIL | otherwise |

- **X2:** **KILL** when no checkpoint passes and at least one FAILs (stop: the rank carries no forward information,
  the grid is never run, every later stage refuses); **UNDERPOWERED** when none passes and none fails (halt);
  otherwise the grid runs **only for the passing checkpoints**.
- **Reported, never decisive:** the same table for the `pressure` rank (§2.5); Spearman(percentile, label); counts
  per bin and class.

## 9. Procedure by stage (`python research/lab2/x2.py --stage …`)

### Every stage

A stage refuses unless: `X2/PREREG.md` exists (and matches `prereg.lock` once locked); PLAN §8 rule 1 holds for
the split (`common.validation_gates`: V1/V2/V4 on the split's own dates, V3); the split's coverage is complete
(every chain hour scanned, no mid-run B2 hour, ≤ 5% of tradeable coins missing B2, a SOL/USD series that starts
before the coins; FINAL's end-of-data coins are reported, not blocking); the guarded splits have their flags
(`LAB2_ALLOW_TEST`, `LAB2_ALLOW_CONFIRM`, `LAB2_ALLOW_FINAL`), which `x2.py` never sets.

### TRAIN (all searching)

1. Dose-response gate (§8).
2. On PASS, the configs of the passing checkpoints, each with the matched random control (§10) and the stress runs.
3. **Shortlist rule.** A config qualifies when, on TRAIN: ≥ 30 trades; mean net > 0; mean without the top 2 trades
   > 0; matched-control `mean_diff` > 0. The candidate is the qualifier with the highest coin-bootstrap 90% CI lower
   bound (ties: higher mean, then grid order). **The shortlist is that one config** (`common.write_shortlist`, frozen
   at the first VAL run). Nothing is selected on VAL.
4. Nothing qualifies: **NO_CONFIG** if some config had ≥ 30 trades, else **UNDERPOWERED_TRAIN**. X2 stops.
5. A decision on complete TRAIN is final; a re-run needs `--rerun-reason` naming a data correction (the previous
   result is archived). `--allow-partial` runs a **provisional** TRAIN (`train_prelim.*`): no shortlist, no lock, no
   VAL.

### VAL (the shortlisted candidate, once)

| Decision | Condition | Consequence |
|---|---|---|
| UNDERPOWERED_VAL | n < 10 | stop |
| FAIL_VAL | n ≥ 10 and (mean ≤ 0, or mean without top 2 ≤ 0, or matched-control `mean_diff` ≤ 0 or missing) | stop (PLAN §8 rule 7 input) |
| SELECTED_UNDERPOWERED | 10 ≤ n < 30, all three > 0 | proceed, flagged |
| SELECTED | n ≥ 30, all three > 0 | proceed |

### TEST (one run)

The candidate once, with the matched control and the stress runs. **Verdict** = `common.verdict_entry(test,
val = VAL trades, min_mean = 0.03)`: PLAN §3.5 items 1-8 (≥ 60 trades from ≥ 40 coins; mean ≥ +3%; 90% CI lower
bound > 0 under the coin AND the 6-hour block bootstrap; mean without top 2 > 0; ≥ +6 points over the matched
control; VAL/TEST same sign; costs × 1.5 > 0; $100 portfolio > $100 with drawdown < 50%; ≤ 10% censored) and the
§3.6 rejections, **plus X2.1** (§11). REJECTED / UNDERPOWERED / FAIL / INCOMPLETE / PASS combine as in M1. Item 9
(FINAL) is judged in the overall verdict.

### CONFIRM (09-16 → 10-01; one run, never searched)

Only when TEST is not REJECTED and (TEST mean > 0 or TEST n < 5). Same verdict as TEST. The powered test.

### FINAL (census day; after TEST)

The candidate once on all of FINAL. **Criterion 9 (mean > 0) is judged on the census VAL and TEST thirds only**:
the TRAIN third was used to debug the code (§15) and is reported apart.

### Overall

**EDGE** needs: dose gate PASS; VAL SELECTED(_UNDERPOWERED); TEST not REJECTED and (mean > 0 or n < 5); CONFIRM
PASS; FINAL mean > 0. Otherwise KILLED, UNDERPOWERED (TRAIN, VAL or CONFIRM) or NO EDGE.

## 10. Controls

- **Matched random control** (`common.backtest` placebo; the task's "same checkpoint random pick"): 20 draws per
  signal from random coins of the same split that are `alive` with `netflow` > 0 at a decision age within ±120 s of
  the signal's, same exits. It measures exactly what the rank adds over the entry gate. It feeds PLAN §3.5 item 5
  and the shortlist / VAL `mean_diff`.
- **Class-matched control** (diagnostic, never judged): the same, drawn only from coins of the signal's class, to
  show how much of any gap is class composition (organic vs factory coins), which a G1 gate could deliver alone.

## 11. Metric, statistics, extras

- Unit: net return per $20 trade (`ret_net`), one entry per coin per config. Coin-bootstrap 90/95% CIs (10,000
  draws), 6-hour block bootstrap, mean without top 2, top-coin share, halves, $100 / 5-slot portfolio, costs × 1.5,
  deflated Sharpe ratio over every ledger trial, per class.
- **X2.1 (blocking at TEST and CONFIRM): positive outside FACTORY coins.** ≥ 10 trades in non-FACTORY coins with a
  mean > 0. Wave 1's only TRAIN "edges" were one launch farm's brand-ticker coins; a breadth edge that lives only
  in factory coins is that farm again.

## 12. Kill criteria and declarations

| Rule | X2 |
|---|---|
| Stop rule 1 (data first) | stages refuse without V1-V4 for the split |
| Stop rule 2 (fills) | minute-bar worst fills with next-bar exits until X1 exists; if X1 finds them off by ≥ 1 point, the frozen candidate is re-run with replayed fills before any promotion (no new search) |
| Dose gate (§8) | KILL before any strategy P&L |
| Stop rule 7 | FAIL_VAL is reported to the lead |
| Stop rule 8 | 9 trials (§7), all in `trials.json` |

Declarations to `auto_rejections`: `uses_organic_flow = False`, `uses_wallet_reputation = False`,
`uses_truncated_windows = False`, `uses_current_state_fields = False`.

## 13. Not a duplicate of G1, S1, D1 or M1

| Module | What it uses | X2's difference |
|---|---|---|
| G1 | per-coin class at g + 2 min, a gate (never an entry) | X2 is an entry; it ranks coins against each other; classes are diagnostics only |
| S1 | wallet roles from B1 (insider inventory spent), absolute thresholds | X2 uses bars only and no wallet roles; its condition is relative to the cohort |
| D1 | dips and the sellers' cost basis | X2 buys strength in breadth, not dips |
| M1 | one price-ignoring bid (few buyers, steady) | X2 needs many distinct buyers; MECH coins have breadth ≤ 2 and rank low |

## 14. Deviations and limits, stated up front

| Area | Deviation |
|---|---|
| Breadth | per-minute distinct buyers (B2), not distinct buyers over the window; bots/wash/MECH ≥ 0.01 SOL included; pooled accounts count as one buyer (§2) |
| Score | breadth only; net flow / market cap is a monotone function of the window return on an AMM (§2.5): gate and diagnostic only |
| Reference pool | usable coins only (complete B2 window). The backfill's given-up pools (`b2_pool_error`) are the most active coins, so the pool can miss some top coins; the coverage gate caps all missing B2 at 5% of tradeable coins |
| Warm-up | no decisions while fewer than 30 reference coins (start of each split; the pool never crosses splits) |
| Fills | minute-bar worst fills with next-bar exits, not replayed fills (X1) |
| SOL/USD | every non-debug stage refuses until the series covers the split (`common.coverage_problems`) |

## 15. Debug findings and expected sample (census TRAIN third, counts only)

Filled in from `python research/lab2/x2.py --debug` (writes `X2/debug.md`, `X2/debug.json`). No returns, exit
reasons or bin means are shown there, and no parameter above was chosen or changed after it.
