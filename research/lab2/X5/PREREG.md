# X5 pre-registration: R1, a market regime gate (trade only when the whole fresh-graduate market is hot)

- **Version:** `x5-v1`.
- **Written:** 2026-10-09, before any X5 run on TRAIN, VAL, TEST, CONFIRM or FINAL data. TRAIN was still being
  backfilled. Every constant, the three signals, the gate, the hosts, the grid (§6), the model check (§7) and every
  decision rule (§8-§9) were fixed in this file **before** the debug run on the census TRAIN third (§14). That run
  reports counts only: returns, label rates and outcome statistics are hidden, and no parameter was chosen there.
- **Code:** `research/lab2/x5.py`, on the shared foundation `research/lab2/common.py` (every feature, including every
  other coin's record that enters the regime, is read through `common.AsOf`). Tests:
  `research/lab2/tests/test_x5.py`.
- **Data:** `graduates`, `b2_coins`, `b2_bars` only, plus the SOL/USD minute series common.py loads. No B1, no B3,
  no CryptoHouse queries.
- **Spec this implements:** PLAN R1 (merge map, score 20: "market regime gate"; §8 stop rule 7 names it as the next
  wave's gate), with PLAN §3 (shared protocol), §3.5 (entry and veto bars), §3.6 (automatic rejections), §6.6
  (cross-coin leakage rules) and §8 (stop rules), through common.py's `AsOf`, `backtest`, matched placebo,
  `describe`, `verdict_entry`, `verdict_veto`, trial ledger, shortlists and one-shot sessions. Stage gating and CLI
  follow `m1.py` / `z1.py`.
- **Splits:** common.py's (TRAIN 10-01 → 10-05, VAL → 10-06 12:00, TEST → 10-07 19:37:30, CONFIRM 09-16 → 10-01,
  FINAL = census day; the census TRAIN third is debug only).
- **Freeze.** The first official TRAIN run hashes this file into `X5/prereg.lock`. After that `x5.py` refuses every
  stage if this file changed. A change is a new version (`x5-v2`) in `X5/AMENDMENTS.md`, and its configs are new
  trials.

## 1. Hypothesis, mechanism, and an honest prior

**Claim.** A fresh graduate's next hour depends on the state of the whole fresh-graduate market, not only on the
coin. When the market is hot (many graduations, much SOL flowing through fresh pools, most fresh coins still alive
half an hour after migration), a host's entries do better than the same host's entries when the market is cold.
A gate that switches the host on only in a hot market keeps the good half and drops the bad half.

**Why it could beat costs.**

1. **The buyer pool is shared.** Every fresh coin sells to the same pool of speculators, bots and copy-traders.
   After migration a coin's price on PumpSwap moves by ((X + dX) / X)² for a net inflow dX into its pricing
   reserve X = x + v. The inflow a random coin receives scales with how much speculative SOL is circulating in
   fresh pools at that time, so a market-wide variable can shift every coin's drift at once.
2. **The cost side does not scale with the regime.** The $20 round trip costs 1.4-5.1 % by market cap
   (`research/lab2/common.py`, `round_trip_pct`): fees by tier, Ultra, the 20 bps buffer, network fees and
   impact at the pool's own k. A hot regime that adds a few points of drift per hour goes straight to the net.
3. **The regime is observable live, cheaply and causally**: graduation counts, the volume of every fresh pool and
   survival at g + 30 min are all public on-chain facts with a known time stamp.

**Who pays.** In a cold market, late buyers of fresh coins become exit liquidity for insiders and factories with no
one behind them; the gate stops us from being those buyers. In a hot market the next wave of buyers arrives
sooner than the distribution finishes.

**Why it is probably weak (stated before any run).**

- A gate cannot make money on its own (PLAN §0.1). It only selects among a host's trades. The random-entry host is
  expected to lose clearly after costs, so the ON half must beat costs by itself: the regime effect would need to
  be on the order of 10+ points per trade. That is large for a market-wide variable.
- **Wave 1 found no stable time structure.** `docs/EXPERIENCE_GROUNDED.md` G37: the lab's by-hour means swing from
  -59 % to +26 % with no pattern across splits, hour clustering was inconclusive (3 of 8 seeds), and the hourly
  ICC of returns is about 0. If returns have no hourly cluster component, no regime variable can sort them.
- **Expected outcome: NO EDGE.** The realistic best case is a LOSS REDUCER (§8.6): a veto that passes PLAN §3.5's
  veto bar, which makes a losing host lose less but is not an edge.

**What X5 does not duplicate.** G1 sorts coins by their own launch class, S1/D1 by wallet roles in the coin, M1 by
the coin's own mechanical bid. X5 uses no fact about the traded coin except its host's entry decision; every
regime input is an aggregate over the market, with the traded coin itself removed (§2.4).

## 2. The three regime signals (all causal, trailing windows only)

### 2.1 Grid and window

- The regime is evaluated on a **15-minute grid**: at a decision with cutoff τ = t − 20 s, the regime point is
  s = ⌊τ / 900⌋ · 900 ≤ τ. A live bot recomputes it every 15 minutes.
- Every signal S(s) aggregates the records whose **known time** κ lies in the trailing window **(s − N, s]**, with
  **N = 2 h** (fixed). Two hours is the cohort of coins that graduated alongside a host coin aged 30-120 min.

### 2.2 Signals

| Signal | Record per coin j (read through `common.AsOf`) | Known time κ | S(s) |
|---|---|---|---|
| **GR** graduation rate | one tradeable graduation: `sol_quoted` and not `mayhem` (G_COLS, legal at g) | g_j | count in the window / 2 h (graduations per hour) |
| **AV** aggregate post-graduation volume | every completed B2 minute bar of coin j that starts at age ≥ 10 min: buy SOL + sell SOL (`snap.bars`) | bar start + 60 s | sum in the window / 2 h (SOL per hour) |
| **SV** survival share | `AsOf(j, g_j + 1800 s + 20 s).alive()`: common's alive filter (≥ $1.5k USD volume in 15 min, market cap ≥ $6k) at age 30 min | g_j + 1800 s | mean of the records in the window (share alive); UNKNOWN with < 10 records |

- **Direction (fixed): hot = high** for all three. No signal is flipped in this version.
- AV excludes the first 10 minutes of every pool (BOOST ends by g + 6 min; the factory and operator pumps of the
  first minutes are not market attention). It is in SOL, not USD, so it has no SOL/USD dependency.
- AV is a sum, so it moves with GR; SV is a per-coin rate. The three are reported with their pairwise rank
  correlations (diagnostic).

### 2.3 Record pools (PLAN §6.6 rules 1, 2, 4; precedents `g1.Registry`, `y1.HISTORY_SPLITS`)

- **GR (structure known at g).** Every graduate in `graduates.parquet` created before the end of the split being
  run (`g1.registry_from_frames`' rule: later splits never feed an earlier one; earlier splits may, because a
  graduation time stamp is not an outcome). Coverage: every curve hour overlapping (s − N, s] is fully scanned
  (`common.Completeness.curve_hours`), and s < the stage split's creation end (later-created coins that graduated
  before s are not in the pool, so later points are UNKNOWN).
- **AV and SV (outcomes of other coins).** Only usable coins (`common.load` universe) of the stage's history
  splits, which are earlier in time and already opened at that stage:

  | Stage | History splits (records of other coins) |
  |---|---|
  | debug | final_train |
  | train | train |
  | val | train, val |
  | test | train, val, test |
  | confirm | confirm |
  | final | train, val, test, final_train, final_val, final_test |

  CONFIRM is never read before the CONFIRM stage, TEST never before TEST, and so on.
- **Coverage of the pool at s.** Let [lo, hi) be the creation range of the history splits. A coin created before lo
  can still graduate after lo; with **SLACK = 6 h** (fixed a priori) the window's graduations must lie in
  [lo + SLACK, hi):

  | Signal | Graduations the window needs | Known iff |
  |---|---|---|
  | SV | g ∈ (s − N − 30 min, s − 30 min] | s − N − 30 min ≥ lo + SLACK and s − 30 min < hi |
  | AV | g ∈ (s − N − 180 min, s − 10 min] (B2 holds [g, g + 180 min)) | s − N − 180 min ≥ lo + SLACK and s − 10 min < hi |

  The share of graduates with grad_delay > 6 h is reported in the debug run (§14) as a check on SLACK.
- Non-debug stages refuse when a history split fails the coverage check (curve and B2 hours, ≤ 5 % missing B2,
  SOL/USD lookahead), as for the stage's own split; TRAIN `--allow-partial` relaxes this for a provisional run only.

### 2.4 The traded coin is removed from its own regime

Every S at the decision point, and every baseline sample in §3, is computed **without the records of the coin being
decided** (PLAN §6.6 rule 1, "mint ≠ the coin being traded"). Its own volume, survival and graduation never vote
for its own entry. (Without this, a hot coin's own volume could be 10-20 % of AV and the gate would partly be "the
coin itself is hot".)

## 3. The gate

- **Baseline:** the 96 samples S(s − 900·i), i = 1 … 96: the same signal at every 15-minute point of the previous
  24 hours (one full daily cycle, so the threshold is not biased by the time of day). All 96 and S(s) must be
  known; otherwise the state is **UNKNOWN**.
- **ON** iff S(s) ≥ the q-quantile of the 96 samples (numpy linear interpolation). **OFF** otherwise.
  - q = 0.5: the market is at least as hot as its median of the last day (ON about half the time);
  - q = 0.8: the market is in its top quintile of the last day (ON about a fifth of the time).
- **Percentile** (model check only): pct = (#samples < S + ½ · #samples = S) / 96.
- **The gate is a pure filter on the host's FIRST entry signal.** When the host returns `Enter` at t, the gated rule
  enters with the host's own order (exits, tag, state) iff the state at t is ON; OFF and UNKNOWN return `SKIP`
  (fail closed: never enter that coin). So the gated trades are exactly the host trades whose decision fell in an ON
  regime, and the OFF trades are the rest of the known-regime host trades. Exits are the host's, unchanged.

## 4. Hosts

| Host | Ledger name | Rule |
|---|---|---|
| **R0**, random entry | `X5.host-R0` | `g1.host_r0` with `g1.R0_PARAMS` verbatim (PLAN 4.1 R0): at a seeded random age in [30, 115] min, enter if the coin is `alive`, else never; −50 % catastrophe stop, 60 min time exit |
| **M1**, mechanical bids | `X5.host-M1` | `m1.strategy` with `m1.make_params(1.0, "rhythm+prec")` verbatim: PLAN 4.5's fixed candidate exit set at the looser m. It does not wait for M1's own TRAIN choice of m |
| D1 | — | **Not available.** D1 needs B1 raw trades (`d1.py` refuses without them). Adding D1 as a host is a new version (`x5-v2`) with new trials |

- **Placebo** (PLAN §3.4, common's matched-timing control, 20 draws per signal, decision age ± 120 s): R0-hosted
  configs draw random **alive** coins of the same split; M1-hosted configs use M1's own placebo (allowed class and
  alive, matched on the M1 class). Placebo entries ignore the regime, so the control is a **random-regime entry at
  the same age**: `placebo diff` measures exactly what the gate adds.

## 5. Fills, exits and costs (all runs, hosts included)

- `common.FillConfig(exit_delay_bars=1)`: $20, latency 30 s, entry at max(open, high) of the landing bar, stops
  checked on the entry bar, **every stop and time exit fills on the NEXT bar at min(open, low)**; costs from
  `costs.py` by date and market cap, + Ultra 10 bps, + 20 bps buffer, network fees, impact at the pool's own k.
- **Stress** (same call, never used to select): costs × 1.5; rent $0.22; same-bar exits (`exit_delay_bars=0`).
- No trade can be censored by the data horizon: R0 enters by g + 116 min and exits within 60 min (+ 1 bar);
  M1's registered deadline is g + 178 min. A verdict with > 10 % `horizon` exits is INCOMPLETE (common).

## 6. The grid: 12 trials in all, every one logged

| # | Hypothesis | Config |
|---:|---|---|
| 1 | `X5-modelcheck` | the stop rule of §7 (one trial, before any P&L) |
| 2 | `X5.host-R0` | R0, ungated (the host baseline and the OFF arm) |
| 3 | `X5.host-M1` | M1 host, ungated |
| 4-9 | `X5` | R0 gated by signal ∈ {GR, AV, SV} × q ∈ {0.5, 0.8} |
| 10-12 | `X5` | M1 gated by signal ∈ {GR, AV, SV} at q = 0.5 (M1 makes ~46 entries a day: q = 0.8 cannot be powered) |

- Each params dict carries every constant of §2-§5, the host's own params, the fill model and the version.
- **Fixed, not searched:** N = 2 h, the 15-minute grid, the 24-hour baseline, SLACK, the 10-minute AV age floor,
  the 30-minute SV age, the direction, the hosts.
- Signals that fail the model check (§7) are **not run** and add no trial. Nothing else is added later; TEST /
  CONFIRM / FINAL run only shortlisted configs (no new trial ids).

## 7. Model check (stop rule, TRAIN, before any P&L)

- **Observations:** one per TRAIN coin: the R0 decision (the first grid time at or after g + the seeded target
  age) where the coin is `alive` (R0 would enter) and the signal's state is known.
- **Label:** the realized 60-minute mid-price change, close(τ + 60 min) / close(τ) − 1, read through AsOf 60 minutes
  later. Never a feature.
- **Statistic:** Spearman ρ(pct of the signal, label) over the observations; its 6-hour block-bootstrap 90 % CI is
  reported, not decisive (regime observations are correlated in time).
- **Per signal:** UNDERPOWERED with < 200 observations; **FAIL** when ρ ≤ 0 (a hot market does not even rank the
  next hour of a random alive coin above a cold one); **PASS** otherwise. Only PASS signals enter the grid.
- **X5 halts** before any P&L when no signal passes: KILLED_MODEL_CHECK if at least one signal was powered,
  UNDERPOWERED_MODEL_CHECK otherwise.
- **Diagnostics (never decisive):** the regime's persistence, Spearman of S over (s − N, s] with S over (s, s + N]
  at non-overlapping 2-hour steps; the known share of TRAIN decisions; the pairwise rank correlations of the three
  signals; ρ per host-coin class is not computed (no subgroup search).

## 8. Procedure by stage (`python research/lab2/x5.py --stage …`)

### 8.1 Every stage

A stage refuses unless: `X5/PREREG.md` exists and matches `prereg.lock` once locked; PLAN §8 rule 1 (V1-V4 on the
split's own dates via `common.validation_gates`); the split and every history split pass the coverage check (every
chain hour scanned for curve and B2, ≤ 5 % of tradeable coins lack B2, no mid-run hour, SOL/USD covers the coins;
FINAL reports end-of-data coins instead); TEST / CONFIRM / FINAL have the judge's flag (`LAB2_ALLOW_TEST`,
`LAB2_ALLOW_CONFIRM`, `LAB2_ALLOW_FINAL`), which `x5.py` never sets, and run once per family inside one
`common.one_shot_session`. The debug stage writes only to a scratch ledger.

### 8.2 TRAIN (all searching)

1. The model check (§7).
2. On PASS: the two host baselines, then every gated config of a PASS signal, each through `common.backtest` with
   the placebo and the stress runs. Every host trade is labelled ON / OFF / UNKNOWN per (signal, q) at its decision.
3. **Per gated config** report: n, coins, mean, median, coin and 6-h block 90 % CIs, mean without the top 2,
   placebo diff, costs × 1.5, the **contrast** (ON mean − OFF mean over the host's known-regime trades) with its
   6-h block-bootstrap 90 % CI, and the known share.
4. **EDGE qualification** (all must hold): ≥ 60 trades from ≥ 40 coins; mean > 0; mean without the top 2 > 0;
   placebo diff > 0; contrast > 0; censored share ≤ 10 %. Rank qualifiers by the 6-h block-bootstrap 90 % CI lower
   bound of the mean (the regime is time-clustered), then the mean, then q = 0.5 before 0.8, R0 before M1, and
   GR, AV, SV in that order. **Shortlist = the top 2** → `SHORTLISTED_EDGE`.
5. **Else VETO qualification:** ≥ 60 ON and ≥ 60 OFF host trades, and contrast ≥ +5 points. Rank by the contrast's
   block CI lower bound, then the contrast. **Shortlist = the top 1** → `SHORTLISTED_VETO` (a loss-reducer track:
   it can never become an edge).
6. Else **NO_CONFIG** if some config was powered (≥ 60 trades from ≥ 40 coins), **UNDERPOWERED_TRAIN** otherwise.
7. The shortlist is written with `common.write_shortlist("X5", …)` together with the fixed host shortlist(s)
   (`X5.host-R0` / `X5.host-M1`) of the shortlisted configs' hosts, and frozen at the first VAL run.
8. A decision on complete TRAIN is final; a re-run needs `--rerun-reason` naming a data correction and archives the
   previous result. `--allow-partial` writes a PROVISIONAL `train_prelim.*` that never writes a shortlist or a lock
   and never unlocks VAL.

### 8.3 VAL (the shortlist only, once)

Run each shortlisted config and its host baseline once.

- **EDGE track.** Per config, in TRAIN rank order: n < 5 → UNDERPOWERED_VAL; mean ≤ 0 or mean without the top 2 ≤ 0
  → FAIL_VAL; n < 15 → SELECTED_UNDERPOWERED; else SELECTED. The candidate is the first that proceeds (VAL is a
  filter, never a ranking).
- **VETO track.** `common.verdict_veto(VAL host trades with a known regime, flagged = OFF)`: criteria 1 (flagged
  ≥ 10 points worse, CI excludes 0) and 3 (removes < 25 % of the winning profit) → VETO_SELECTED; an UNDERPOWERED
  veto → VETO_UNDERPOWERED; else VETO_FAIL_VAL.

### 8.4 TEST (one look, `LAB2_ALLOW_TEST=1`)

Run the candidate and its host baseline inside one `X5` session.

- **EDGE track:** `common.verdict_entry(test, val = VAL candidate, min_mean = 0.03)` (PLAN §3.5 items 1-8 and 10,
  §3.6) plus:

  | ID | Criterion |
  |---|---|
  | X5.1 | contrast ON − OFF > 0 with its 6-h block-bootstrap 90 % CI lower bound > 0 (None with < 10 trades in an arm) |
  | X5.2 | power in time: the ON trades fall in ≥ 6 distinct 6-hour blocks |

  REJECTED if `verdict_entry` rejects; UNDERPOWERED if it is underpowered or X5.2 fails; FAIL if any criterion
  fails; INCOMPLETE if any is missing; PASS otherwise. Item 9 (FINAL) is judged in the overall verdict.
- **VETO track:** `common.verdict_veto(VAL host, VAL OFF, oos_host = TEST host, oos_flagged = TEST OFF)`.
- With a 1.3-day TEST (≈ 5 blocks), **UNDERPOWERED is expected** on the EDGE track.

### 8.5 CONFIRM (09-16 → 10-01, one look) and FINAL (census day, one look)

- **CONFIRM precondition:** TEST not REJECTED, and (EDGE: TEST mean > 0 or TEST n < 5; VETO: the TEST veto verdict
  is not FAIL). Same run and verdict as TEST. CONFIRM is the powered test (15 days, ≈ 60 blocks); its first
  ≈ 1.5 days are UNKNOWN by §2.3 (the warm-up) and are reported.
- **FINAL** runs only after TEST: the candidate and its host on all of FINAL in one session (FINAL consumes its
  thirds). Criterion 9 (EDGE: mean > 0; VETO: contrast > 0) is judged on the census VAL and TEST thirds only; the
  TRAIN third hosted the debug run and is reported apart.

### 8.6 Overall verdict

- **EDGE** needs: model check PASS; TRAIN SHORTLISTED_EDGE; VAL SELECTED or SELECTED_UNDERPOWERED; TEST not REJECTED
  and (mean > 0 or n < 5); CONFIRM PASS; FINAL mean > 0.
- **LOSS REDUCER (veto, not an edge)** needs: TRAIN SHORTLISTED_VETO; VAL VETO_SELECTED; TEST veto not FAIL;
  CONFIRM veto PASS; FINAL contrast > 0. It lowers a host's losses; it does not make the bot profitable.
- Otherwise **KILLED** (§7), **UNDERPOWERED** (TRAIN, VAL or CONFIRM) or **NO EDGE**.

## 9. Controls

- **Matched random control** (§4): random-regime entries at the same age; PLAN §3.5 item 5 (≥ +6 points) and the
  TRAIN bar (> 0).
- **The OFF arm** (the host's own known-regime OFF trades): the contrast, the veto bar, X5.1.
- **The ungated host** itself is reported next to every gated config (same coins, same exits).

## 10. Metric and statistics

- The unit is the net return per $20 trade (`ret_net`), one entry per coin per config.
- Coin-bootstrap CIs (10,000 draws) and **6-hour block bootstraps** (common's two-level one) for the mean; the
  contrast's block bootstrap resamples 6-hour blocks of host trades (then trades within blocks) and recomputes
  ON mean − OFF mean. Regime trades share their hours, so the block CI is the honest one.
- Also reported: median, win rate, top-coin share, mean without the top 2, halves, the $100 / 5-slot portfolio,
  costs × 1.5, the deflated Sharpe ratio over every trial in the ledger, the ON share and the UNKNOWN share.

## 11. Kill criteria (PLAN §8) and declarations

| Rule | How X5 applies it |
|---|---|
| Stop rule 1 (data first) | V1-V4 per split; stages refuse otherwise |
| Stop rule 2 (fills) | minute-bar worst fills with next-bar exits until X1 exists; a frozen config is re-run with replayed fills before any promotion |
| Model check | §7: no signal with ρ > 0 → X5 dies before any P&L |
| Stop rule 7 | FAIL_VAL / VETO_FAIL_VAL are reported to the lead |
| Stop rule 8 | every config counts (§6) |

Declarations for `common.auto_rejections`: `uses_organic_flow = False`, `uses_wallet_reputation = False`,
`uses_truncated_windows = False`, `uses_current_state_fields = False`. The regime is a cross-coin registry of
**other** coins' outcomes (survival, volume), built under PLAN §6.6's rules: strictly the past (κ ≤ s ≤ τ), the
traded coin removed, no open positions marked to a later price (a record exists only once its known time passed),
history splits only.

## 12. Deviations from the PLAN, stated up front

| Area | Deviation |
|---|---|
| R1 inputs | PLAN §6.5's `regime_30m` lists factory/operator shares, organic net SOL, a migration-bot P&L index and the SOL return. X5 uses the three signals the lead specified (graduation rate, aggregate post-graduation volume, survival at g + 30) from B2 alone. Organic flow and bot P&L need B1/B3 (not available); SOL/USD does not cover TRAIN-CONFIRM |
| Thresholds | relative to the signal's own trailing 24 hours (self-normalizing), not absolute: an absolute threshold fitted on TRAIN would mis-gate CONFIRM if activity drifted over three weeks |
| Hosts | R0 and M1; D1 needs B1 (§4) |
| Fills | minute-bar worst fills with next-bar exits, not replayed fills |
| Warm-up | AV and SV are UNKNOWN for the first ≈ 35 h of TRAIN and of CONFIRM (pool start + SLACK 6 h + B2 window + N + 24 h baseline) and for the whole census TRAIN third (§14); GR has no warm-up (structure from earlier splits) |

## 13. Expected sample (extrapolated from G1's and M1's census-third counts; activity on other days may differ)

| Measure | Census third (0.52 d) | Per day | TRAIN known (≈ 2.5 d for AV/SV) | VAL (1.5 d) | TEST (1.3 d) | CONFIRM (≈ 13.5 d known) |
|---|---:|---:|---:|---:|---:|---:|
| R0 host trades | 94 | ≈ 181 | ≈ 450 | ≈ 270 | ≈ 240 | ≈ 2,400 |
| R0 ON trades, q = 0.5 | | ≈ 90 | ≈ 225 | ≈ 135 | ≈ 120 | ≈ 1,200 |
| R0 ON trades, q = 0.8 | | ≈ 36 | ≈ 90 | ≈ 54 | ≈ 48 | ≈ 490 |
| M1 host trades | 24 | ≈ 46 | ≈ 115 | ≈ 69 | ≈ 61 | ≈ 620 |
| M1 ON trades, q = 0.5 | | ≈ 23 | ≈ 58 | ≈ 35 | ≈ 30 | ≈ 310 |

- q = 0.8 and every M1-hosted config are expected to be UNDERPOWERED on TEST (< 60 trades) and X5.2 (≥ 6 blocks)
  is borderline on TEST; CONFIRM is the powered test.
- M1's entries come from one operator cluster on the census day, so an M1-hosted regime effect would be confounded
  with that operator's schedule; the M1-hosted configs are included because the lead asked for it, not because
  they are expected to be informative.

## 14. Debug run (census TRAIN third, counts only)

Filled in after `python research/lab2/x5.py --debug`, before any TRAIN data exists. Returns, alive rates, signal
values and every outcome statistic stay hidden; only counts are reported. No parameter is chosen there.
