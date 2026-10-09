# Z5 pre-registration: the fee-tier cost optimizer (expected: no edge)

- **Version:** `z5-v1`.
- **Written:** 2026-10-09, before any Z5 run on TRAIN, VAL, TEST, CONFIRM or FINAL data. TRAIN was still being
  backfilled. Every constant, both hosts, the whole grid (§6), the decomposition (§7) and the predictions (§7.3) were
  fixed in this file **before** the debug run on the census TRAIN third (§13). That run reports counts and
  decision-time costs only: returns, exit reasons, fill prices and placebo outcomes hidden, and no parameter chosen
  there. Two robustness additions came **after** it, from counts only, and are listed in §13: the concentration check
  (§9, Z5.4) and the class-matched diagnostic control (§8). Neither touches the grid.
- **Code:** `research/lab2/z5.py`, on the shared foundation `research/lab2/common.py` (every feature through
  `common.AsOf`). Tests: `research/lab2/tests/test_z5.py`.
- **Data:** `graduates`, `b2_coins`, `b2_bars` only (B2 minute bars to g + 180 min). No B1, no B3, no CryptoHouse
  queries.
- **Protocol:** PLAN §3 (shared protocol), §3.5 (entry and veto bars), §3.6 (automatic rejections) and §8 (stop rules),
  through common.py's `backtest`, matched-timing placebo, `describe`, `verdict_entry`, `verdict_veto`, trial ledger,
  shortlists and one-shot sessions. Stage gating and CLI follow `m1.py`.
- **Splits:** common.py's (TRAIN 10-01 → 10-05, VAL → 10-06 12:00, TEST → 10-07 19:37:30, CONFIRM 09-16 → 10-01,
  FINAL = census day; the census TRAIN third is debug only).
- **Freeze.** The first official TRAIN run hashes this file into `Z5/prereg.lock`. After that, `z5.py` refuses every
  stage if this file changed. A change is a new version (`z5-v2`) in `Z5/AMENDMENTS.md`, and its configs are new
  trials.

## 1. Question and mechanism

**Claim.** pump.fun's PumpSwap pool fee falls with market cap (125 bps a side below 420 SOL, 120 to 1,470, 115 to
2,460, 110 to 3,440, 105 to 4,420, 100 to 9,820, … 30 bps from 98,240 SOL; `common.fee_bps_at`), and the price impact
of a $20 ticket falls with the pricing reserve X = x + v ≈ √(k·p). Both are known exactly at the decision from the
pool state. A host strategy restricted to entries whose $20 round trip is in the cheapest tiers, with exits that sell
before the price falls into a more expensive tier, pays less of the house's take on every trade. **Is that cost
saving alone enough to turn any host positive?**

**Why it could beat costs (the economic reason).** It is not an edge against a counterparty; it is a smaller transfer
to the fee recipients (protocol, LP, creator) and less self-inflicted impact. A host whose gross move is positive but
smaller than its costs would be flipped by a large enough saving. Nobody else loses.

**Why it should fail (stated before any data; my prior that Z5 passes TEST is about 3 %).**

1. **The reachable saving is small** (§2). Between a fresh graduate (3.70 %) and the 115-bps tier (3.32 %) the round
   trip falls by 0.38 points; to the 100-bps tier (2.94 %) by 0.76 points. Only against floor-level alive pools
   (4.39 % at the $6k alive floor) does the saving reach 1.1-1.5 points.
2. **The hosts are far below zero.** Wave 1's random entry (nightcrawler exits) made −6.4 % per trade
   (CI [−10.7, −2.1], `research/lab/RESULTS.md`). Wave 1's best finalist, F4-#1, was −5.4 % on TEST with model costs,
   −3.1 % with the cheapest measured cost (0.40 %) on every trade and **−2.6 % with zero costs** (RESULTS A4: "costs are
   not what kills it"). A 0.4-1.5 point saving cannot close a 3-6 point gap.
3. **The cheap tier is a selection, not a free lunch.** Restricting to deep pools selects coins that already ran 3.6×
   or more from graduation. Any difference in their gross move is a momentum / survivorship effect, not the fee. §7
   separates the two exactly; a Z5 "pass" carried by selection would be another hypothesis (X3 already tests one deep-
   pool rule), not this one.
4. **The tier guard (§4.2) saves at most one 5-bps step per tier crossed on the exit side**, and it is a stop at a
   price level the market does not care about. Its effect on returns is the stop's, not the fee's (P4, §7.3).

## 2. What a $20 round trip costs (`common.round_trip_pct`)

Census SOL/USD 116.1, fee schedule "Last Updated 20 May 2026" (`common.FEE_SCHEDULES`), Ultra 10 bps, 20 bps
slippage/MEV buffer, two network fees (0.000205 SOL each), no rent, migration pool k = 84.99 SOL × 206.9 M tokens:

| Market cap (SOL) | Pricing reserve X (SOL) | Pool fee / side (bps) | Round trip |
|---:|---:|---:|---:|
| 52 (the $6k alive floor) | 30.2 | 125 | 4.39 % |
| 200 | 59.3 | 125 | 3.87 % |
| 411 (graduation) | 85.0 | 125 | 3.70 % |
| 800 | 118.6 | 120 | 3.49 % |
| 1,469 | 160.7 | 120 | 3.42 % |
| **1,470** | 160.8 | **115** | **3.32 %** |
| 2,460 | 208.0 | 110 | 3.18 % |
| 3,440 | 245.9 | 105 | 3.05 % |
| 4,419 | 278.8 | 105 | 3.04 % |
| **4,420** | 278.8 | **100** | **2.94 %** |
| 9,820 | 415.5 | 95 | 2.80 % |
| 20,000 | 593.0 | 85 | 2.58 % |

**The two thresholds are tier boundaries.** For SOL/USD anywhere in $100-140 and the standard migration k:

- **c = 3.40 %** separates 1,469 SOL (3.42-3.43 %) from 1,470 SOL (3.32-3.34 %): "the 115-bps tier or cheaper";
- **c = 3.00 %** separates 4,419 SOL (3.02-3.07 %) from 4,420 SOL (2.93-2.97 %): "the 100-bps tier or cheaper".

The thresholds are on the exact round trip, not on the tier, so a pool whose k drifted is judged on its own cost.
The worst-fill spread (entry at the landing bar's high, exits at the next bar's low) comes on top of these numbers in
every trade; it is not part of `rt`.

## 3. Hosts (fixed; no host parameter is searched)

| Host | Definition | Pinned |
|---|---|---|
| **R0** | PLAN §4.1 R0, exactly as `g1.host_r0` / `g1.R0_PARAMS`: per coin a seeded random age U[30, 115] min (sha256 of `"0:<mint>"`); at the first decision at or after it, enter if the coin is alive (15-min volume ≥ $1.5k and market cap ≥ $6k), else never. Exits: −50 % stop, 60-min time exit (PLAN X1 exit 6) | params hash `27a79bc60126`. Re-implemented in `z5.py` (a test asserts decision-for-decision identity with `g1.host_r0`) |
| **M1** | `m1.strategy` at **m = 1, exit set `rhythm+prec`** (`m1-v1`): MECH-bar entry at ages 30-120 min with `drift_pred60` ≥ 1 × round trip, no precursor; exits rhythm break, precursor, −10 % stop, deadline g + 178 min | `m1.VERSION == "m1-v1"` and params hash `9c0a14afb895`; `z5.py` refuses every stage if either changes |

- **Why these two.** R0 is the null host: if the cost saving cannot flip random entry, the cost was never the problem.
  M1 is the one host with an a-priori positive-drift thesis whose entry already compares the drift with the round
  trip, so it is the host most likely to sit near breakeven. m = 1 is the more permissive of M1's two m values (more
  trades); `rhythm+prec` is M1's own pre-registered candidate exit. Both were chosen without any M1 result (none
  existed).
- **Hosts not used.** X3 already requires market cap ≥ 1,470 SOL, so the c = 3.40 % filter is a no-op on it by
  construction. X4 trades at the floor (round trip ≈ 5 %), so the filter removes every X4 entry by construction.
  X1, X2, the Y and Z modules were being edited at writing time (uncommitted changes), so they cannot be pinned. G1's
  `dip` host (the bot's default dip rule) is outside this brief. Adding any host later is an amendment with new trials.

## 4. Features (as of τ = t − 20 s, all through `common.AsOf`)

### 4.1 The cost filter (a veto at the host's own entry decision)

- **`rt`**: the exact $20 round trip at the decision, `common.round_trip_pct(20 / SOL_USD, price, k, t)` with SOL/USD of
  the last minute that ended before τ, price = the last completed bar's close, k = X·y after that bar, the fee schedule
  as of t, two network fees, no rent. The same function `m1.round_trip_frac` uses.
- **Rule.** When the host returns `Enter` at decision t: enter if `rt` ≤ c, otherwise **SKIP the coin** (never enter it
  later). An unknown `rt` (no completed bar, X or y not positive) vetoes. NULL never passes.
- **Consequence.** Every filtered trade is one of the host's own trades, with the same decision time and entry; with the
  host's exits it is the same trade. The comparison with the host (§7) is exact and paired, never a re-timed entry.

### 4.2 The tier guard (exits timed to avoid crossing into a higher-fee tier)

- `M_in` = entry fill price × 10⁹ (the market cap at which the buy paid its fee tier).
- `G` = the largest fee-schedule boundary B (420, 1,470, 2,460, 3,440, 4,420, 9,820, … SOL) with B ≤ `M_in` / 1.05.
  No such boundary: no guard.
- **Exit signal** at the first decision whose last completed close has market cap < 1.02 × `G`. The sell lands 30 s
  later at the worst price of its bar (§5).
- `ARM` = 5 %: no guard on the boundary within 5 % below the entry (an immediate whipsaw would pay a full round trip to
  save one 5-bps step). `MARGIN` = 2 %: sell before, not after, the crossing. Both fixed here, never tuned.
- The guard runs before the host's own exit logic; either can close the position. Placebo positions compute `G` from
  their own fill.

## 5. Fills and exits

- `common.FillConfig(exit_delay_bars=1)`: $20; the order lands at t + 30 s; entry at the landing bar's max(open, high);
  every exit at min(open, low). A stop or time exit triggered in bar j fills in bar j + 1 at its low (next-bar stops);
  signal exits (rhythm, precursor, tier guard) land at t + 30 s at the bar's worst price. Stops are also checked on the
  entry bar.
- Exits are the host's (§3) plus the guard (§4.2) in the guard configs. No exit is censored by construction: R0 holds
  ≤ 60 min from ≤ g + 116 min, M1 sells by g + 178 min. A verdict with > 10 % censored trades is INCOMPLETE anyway.
- **Stress and sensitivity** (same call, never used to select): costs × 1.5; rent $0.22; same-bar exits
  (`exit_delay_bars = 0`); open fills.

## 6. The grid: 8 configurations, every one a counted trial

| # | Host | c (max `rt`) | Exit | Role |
|---:|---|---|---|---|
| 1 | R0 | none | host | host baseline (the twin) |
| 2 | R0 | 3.40 % | host | candidate |
| 3 | R0 | 3.00 % | host | candidate |
| 4 | R0 | 3.40 % | host + tier guard | candidate |
| 5 | M1 | none | host | host baseline (the twin) |
| 6 | M1 | 3.40 % | host | candidate |
| 7 | M1 | 3.00 % | host | candidate |
| 8 | M1 | 3.40 % | host + tier guard | candidate |

- Each params dict carries the version, the host's full params, c, the guard flag and constants, the filter semantics
  and the fill model; any change is a new trial.
- The baselines are needed to answer the question (§7). The guard runs once per host, at c = 3.40 % (its larger
  sample, and the tier range where boundaries are closest).
- The twin's TEST / CONFIRM / FINAL run is logged as `Z5` with the TRAIN params (the same ledger config), inside Z5's
  one-shot session. **Z5's total is 8 trials** on top of the ledger.

## 7. The decomposition (the answer to the question)

### 7.1 Per filtered config f against its host baseline b (same split, same fills)

Per trade: net = `ret_net`; gross = `ret_mid` (exit fill / entry fill − 1, worst fills); **cost rate** = 1 − (1 + net) /
(1 + gross), the share of the gross outcome lost to the pool fee, Ultra, buffer, impact and network. (gross − net is
not used: a winner pays its exit fee on a larger amount, so gross − net grows with the price move and would confound
the saving with selection.) Trades are matched on (mint, decision time).

| Quantity | Definition |
|---|---|
| kept share | n(f) / n(b) |
| net gain | mean net(f) − mean net(b) |
| **cost saving** | mean cost rate(b) − mean cost rate(f) |
| selection | mean gross(f) − mean gross(b) |
| ex-ante saving | mean `rt` at decision of b − of f (quoted, before fills) |
| **cost-alone counterfactual** | (1 + mean gross(b)) × (1 − mean cost rate(f)) − 1: the host's own trades at the filtered set's cost rate |
| **cost alone flips the host** | mean net(b) ≤ 0 **and** cost-alone counterfactual > 0 (a positive host has nothing to flip) |
| attribution label | "host already positive" if mean net(b) > 0; else "cost" if the counterfactual > 0; else "selection, not cost" |
| veto view | `common.verdict_veto(b, flagged = trades the filter vetoed)` (PLAN §3.5 veto bars; diagnostic) |

For the guard configs the same is reported against b, plus a paired comparison with the same-c host-exit config (same
entries): the mean exit-side fee saving ((fee_bps_out(host exit) − fee_bps_out(guard)) / 10⁴), the net difference, the
share of trades the guard closed, and how often a guard sale filled at or above `G`.

### 7.2 What answers "is the cost saving alone enough?"

**No**, for a host, when its cost-alone counterfactual is ≤ 0. **Yes** only when the host is ≤ 0, the counterfactual
is > 0 **and** the candidate also passes the verdict of §9. A candidate that passes with cost alone ≤ 0 is labelled
"selection, not cost": a tradeable result, but not this mechanism. One that passes on a host already positive is
labelled "host already positive": the edge is the host's.

### 7.3 Predictions (scored on TRAIN, reports only, never decisive)

| ID | Prediction (held = the expected negative result) |
|---|---|
| P0 | Sanity: the R0 baseline's judged-control difference has a 95 % CI containing 0 (random vs random) |
| P1 | No filtered config has mean net > 0 |
| P2 | Every filtered config's measured cost saving is < 1.5 points |
| P3 | Cost alone flips no host: the cost-alone counterfactual is ≤ 0 for every filtered config |
| P4 | The guard's mean exit-side fee saving against the same-c host-exit config is < 0.10 point, for both hosts |

## 8. Controls (PLAN §3.4 matched random control: 20 draws per signal, decision age ± 120 s, same exits)

| Host | Judged control (criterion 5, TRAIN qualifier) | Diagnostic controls (never judged) |
|---|---|---|
| R0 | random **alive** coins of the same split (R0's own universe; for a filtered config this measures cost saving + selection together) | `class_matched` (every R0 config): alive draws of the signal's PLAN 4.2 class (`m1.m1_class`: OPERATOR / FACTORY / OTHER), separating class selection from cost (§13); `cost_band` (filtered configs): alive draws whose `rt` ≤ c at their decision (timing inside the cheap band; ≈ 0 expected for a random host) |
| M1 | M1's class-matched alive control (`m1.placebo_ok`, `m1.placebo_stratum`), as M1 registers it | `unmatched` (any allowed class, alive); `cost_band` (class-matched and `rt` ≤ c) |

Placebo positions run the same exits (host logic with `is_placebo`, the guard from their own fill).

## 9. Procedure by stage (`python research/lab2/z5.py --stage …`)

### Every stage

A stage refuses unless: `Z5/PREREG.md` exists and matches `prereg.lock` once locked; the M1 host pin holds (§3);
PLAN §8 rule 1 holds (`common.validation_gates` for the split; the debug stage only reports it); the split's coverage
is complete (FINAL exempt), with no B2 hour mid-run and no SOL/USD lookahead; the guarded splits have their flags
(`LAB2_ALLOW_TEST`, `LAB2_ALLOW_CONFIRM`, `LAB2_ALLOW_FINAL`), which `z5.py` never sets.

**Host-first rule.** Running M1's entries on VAL, TEST, CONFIRM or FINAL would show M1's result there before M1's own
look. So a stage whose shortlist holds the M1 host refuses until M1 has had its own look at that split group (trials
ledger), or M1 can no longer reach it (its TRAIN decision was not SHORTLISTED; its VAL decision did not proceed; for
CONFIRM, M1's `confirm_allowed` is false). R0 is a parameter-free null host with no look to protect.

### TRAIN (all searching)

1. Run the 8 configs, each with its judged control, diagnostic controls and stress runs.
2. Compute §7 for every filtered config and score §7.3.
3. **A filtered config qualifies** when all hold:

   | Requirement | Bar |
   |---|---|
   | Sample | ≥ 60 trades from ≥ 40 coins; for the M1 host also ≥ 3 operator clusters (`m1.cluster_table`, M1's own bar) |
   | Mean net | > 0 |
   | Mean without the top 2 trades | > 0 |
   | **Concentration** | R0 host: mean > 0 on the trades whose class at the entry decision is not OPERATOR; M1 host: mean > 0 without the largest operator cluster (M1's own check) |
   | Judged-control `mean_diff` | > 0 |
   | Censored share | ≤ 10 % |
   | **The filter adds** | mean net(f) − mean net(b) > 0 |

4. **Shortlist = the pair** (best qualifier, its host baseline). Best = the higher coin-bootstrap 90 % CI lower bound,
   then the higher mean, then grid order. Written with `common.write_shortlist`, frozen at the first VAL run.
5. Nothing qualifies: **NO_CONFIG** if any filtered config met the sample bar, else **UNDERPOWERED_TRAIN**. Z5 stops.
6. A decision on complete TRAIN is final (a re-run needs `--rerun-reason` naming a data correction; the old result is
   archived). `--allow-partial` writes a PROVISIONAL `train_prelim.*` that never writes a shortlist or a lock.

### VAL (the pair, once)

| Decision | Condition (candidate's VAL trades) | Consequence |
|---|---|---|
| UNDERPOWERED_VAL | n < 5 | stop |
| FAIL_VAL | n ≥ 5 and (mean ≤ 0, or mean without the top 2 ≤ 0, or mean ≤ the twin's mean) | stop |
| SELECTED_UNDERPOWERED | 5 ≤ n < 15, otherwise good | proceed, flagged |
| SELECTED | n ≥ 15, otherwise good | proceed |

### TEST (one look: candidate and twin inside one `common.one_shot_session`)

- **Base verdict** = `common.verdict_entry(candidate, val = VAL candidate, min_mean = 0.03)`: PLAN §3.5 items 1-8 and 10
  plus the §3.6 auto-rejections. Item 9 (FINAL mean > 0) is judged in the overall verdict after FINAL.
- **Z5 extras:**

  | ID | Criterion | Blocking |
  |---|---|---|
  | Z5.1 | the filter adds: candidate mean − twin mean > 0 | yes (FAIL) |
  | Z5.2 | M1 host only: ≥ 3 operator clusters among the candidate's trades | yes (UNDERPOWERED) |
  | Z5.3 | attribution (§7): cost saving, selection, cost-alone counterfactual | no (label) |
  | Z5.4 | concentration: the TRAIN qualifier's check (R0: mean > 0 without OPERATOR-class coins; M1: mean > 0 without the largest operator cluster) | yes (FAIL) |

- REJECTED if `verdict_entry` rejects; UNDERPOWERED if it is underpowered or Z5.2 fails; FAIL if any criterion fails;
  INCOMPLETE if any is missing or > 10 % of trades are censored; PASS otherwise. At census-day rates (§13) an R0
  candidate would have ≈ 130 TEST trades (powered); an M1-host candidate is underpowered on clusters (one operator).

### CONFIRM (09-16 → 10-01; one look, never searched)

Spent only when TEST was not REJECTED and (TEST mean > 0 or TEST n < 5). The same pair, the same verdict. CONFIRM is the
powered out-of-sample test.

### FINAL (the census day, after TEST)

The pair once on all of FINAL (one session). Criterion 9 is judged on the census VAL and TEST thirds only; the census
TRAIN third hosted the debug run and is reported apart.

### Overall Z5 verdict

**EDGE** needs: TRAIN SHORTLISTED, VAL proceeds, TEST not REJECTED and (mean > 0 or n < 5), CONFIRM PASS, FINAL mean
> 0 — labelled with the CONFIRM attribution (§7.1: "cost", "selection, not cost" or "host already positive").
Otherwise UNDERPOWERED (TRAIN, VAL or CONFIRM) or NO EDGE.

## 10. Statistics, declarations and kill criteria

- Unit: net return per $20 trade (`ret_net`), one entry per coin per config. Coin-bootstrap CIs (10,000 draws, 90 % and
  95 %) and the 6-hour block bootstrap (`common.describe`); mean without the top 2; top-coin share; halves; the $100 /
  5-slot portfolio; deflated Sharpe counting every ledger trial; per-tag means.
- **Classes and clusters** (groupings, never features): every trade carries its PLAN 4.2 class at the entry decision
  (`m1.m1_class`, read through AsOf at t_dec) and its operator cluster (`m1.cluster_table`: coins linked by creator,
  symbol or a top-5 early pool buyer). Both are reported per config (counts on the debug split, means otherwise). The
  concentration check (§9) uses the class for R0 and the cluster for M1 (§13 says why).
- **Declarations** to `auto_rejections`: `uses_organic_flow = False`, `uses_wallet_reputation = False`,
  `uses_truncated_windows = False`, `uses_current_state_fields = False`.
- **Stop rules (PLAN §8):** rule 1 (data first) per split; rule 2 (fills are minute-bar worst fills until replayed fills
  exist; if those differ by ≥ 1 point the frozen pair is re-run with them, no new search); rule 7 (FAIL_VAL is
  reported); rule 8 (every config counts, §6).

## 11. Deviations and limits, stated up front

| Area | Deviation |
|---|---|
| Cost model | `rt` is the pool model (costs.py). Live Ultra quotes matched it within 0.0-0.35 points when routed through PumpSwap only; a second venue can be cheaper (RESULTS A4: 0.40 % on one coin). Z5 cannot see other venues |
| Fee schedule | One dated schedule (2026-05-20). The 2026-10-08 page update the lens reports cite quotes the same totals; if a diff is found, `common.FEE_SCHEDULES` gains a row and Z5 is re-run as a new version |
| Tier at the fill | The filter quotes the tier at the last close; the buy pays the tier at its fill price (worst fill, the landing bar's high). An entry quoted just below a boundary can pay the next cheaper tier, never a dearer one on a rising bar |
| Guard | Judged on minute closes; the sale lands 30 s later at the bar's worst price and can fill below `G` (reported) |
| Hosts | Two frozen hosts only (§3). R0's random age and alive test are G1's; M1's detector is bar-level (M1 PREREG §2) |
| Horizon | B2 ends at g + 180 min; neither host holds past it |

## 12. Expected sample (before the debug run)

From the published debug counts of the hosts' own modules (counts only): G1.R0 made 94 entries on the census TRAIN third
(0.52 days, ≈ 180 a day: ≈ 720 on TRAIN, ≈ 270 on VAL, ≈ 235 on TEST, ≈ 2,700 on CONFIRM); M1 at m = 1 made 24 (≈ 46 a
day), all in one operator cluster (M1 PREREG §13). The share of those entries in the cheap tiers is unknown before §13.

## 13. Debug run (census TRAIN third, counts and decision-time costs only)

**The run.** `python research/lab2/z5.py --debug` writes `Z5/debug.md` and `Z5/debug.json`: 450 usable coins created
over 12.5 h (0.52 days), 145 s. Returns, exit reasons, fill prices, the cost decomposition and placebo outcomes are
hidden; the trials go to a scratch ledger, never to `trials.json`. The grid (§6), c, the guard constants and the hosts
were fixed before it and did not change.

**Counts** (the round trip, market cap, fee tier and class are DECISION-time states, not outcomes):

| | R0 host | M1 host |
|---|---:|---:|
| Host entries (per day) | 94 (181) | 24 (46) |
| Quoted `rt` at the decision, median (IQR) | 3.29 % (1.79-3.73 %) | 1.76 % (1.44-1.96 %) |
| Market cap at the decision, median (IQR), SOL | 1,956 (334-67,471) | 69,129 (55,219-1,096,115) |
| Kept at c = 3.40 % / 3.00 % | 53 (56 %) / 44 (47 %) | 24 (100 %) / 24 (100 %) |
| Ex-ante saving quoted at c = 3.40 % / 3.00 % | 0.67 / 0.88 points | 0 / 0 |
| Class of the kept entries at c = 3.40 % | 29 OPERATOR, 17 FACTORY, 7 OTHER | 24 OPERATOR |
| Class of the vetoed entries | 39 OTHER, 2 FACTORY | none |
| Operator clusters among the kept entries (largest) | 21 (33 trades) | 1 (24) |
| Filtered trades a subset of the host's / guard entries identical | yes / yes | yes / yes |

**What the counts say, before any TRAIN data:**

1. **The cheap tiers are a coin-class proxy.** On the census third, every R0 entry quoted at ≤ 3.00 % is an
   OPERATOR (29), FACTORY (13) or OTHER (2) coin, and 39 of the 41 vetoed entries are OTHER (organic) coins. Operator
   and factory pools hold hundreds to thousands of SOL (market caps to 10⁶ SOL), so their fee tier is 30-100 bps. Any
   "net gain" of the filter is therefore expected to be class selection; the decomposition (§7) and the class-matched
   control (§8) measure exactly that.
2. **The saving is small, as §2 predicted.** The quoted saving is 0.67-0.88 points per trade; wave 1's random-entry
   host lost −6.4 %. P2 and P3 are expected to hold.
3. **The filter is a no-op on the M1 host.** All 24 M1 entries already sit in ≤ 85-bps tiers (M1 rides operator
   coins), so the three M1-host filtered configs equal the M1 baseline trade for trade, the filter cannot add, and they
   cannot qualify (§9). They stay in the grid because it was frozen before this run; they are three honestly spent
   trials, and they confirm that the cost of M1's trades is already the floor of the fee schedule.
4. **The guard's reach depends on the tier.** Above 4,420 SOL the fee boundaries are every ≈ 4,900 SOL (2.5-5 bps
   steps), so for an operator coin at 50,000 SOL the guard is a 5-15 % stop; between 420 and 4,420 SOL the boundaries
   are 1,000 SOL apart (a 25-60 % stop).

**Definition changes made while debugging** (from structure and counts, never from outcomes; before any TRAIN data,
no `prereg.lock` existed):

1. **The concentration check** (§9, Z5.4). Item 1 means a cheap-tier R0 result could rest on one operator: all 29
   OPERATOR entries are one operator cluster (as M1 PREREG §13 found). M1's cluster linking cannot be used for R0: its
   shared-early-buyer link merges 66 of the 94 R0 entries (37 OTHER + 29 OPERATOR) into one component through common
   early-buyer bots, so "without the largest cluster" would judge an arbitrary third of the trades. So R0 is judged
   without OPERATOR-class coins (24 of the 53 kept census entries remain: ≈ 185 expected on TRAIN), and M1 keeps its
   own cluster check.
2. **The class-matched diagnostic control** for R0 configs (§8), for the same reason.
3. **Cost rate instead of gross − net** (§7.1), found by a unit test while writing the code, before this run: a winner
   pays its exit fee on a larger amount, so gross − net would have confounded the saving with selection.

**Expected sample if the other days resemble the census day** (the operator can change its schedule at any time):

| Config | Per day | TRAIN (4 d) | VAL (1.5 d) | TEST (1.32 d) | CONFIRM (15 d) |
|---|---:|---:|---:|---:|---:|
| R0 baseline | ≈ 181 | ≈ 720 | ≈ 270 | ≈ 240 | ≈ 2,700 |
| R0, c = 3.40 % (of which not OPERATOR) | ≈ 102 (≈ 46) | ≈ 410 (≈ 185) | ≈ 150 (≈ 70) | ≈ 135 (≈ 60) | ≈ 1,500 (≈ 690) |
| R0, c = 3.00 % (of which not OPERATOR) | ≈ 85 (≈ 29) | ≈ 340 (≈ 115) | ≈ 125 (≈ 45) | ≈ 110 (≈ 38) | ≈ 1,270 (≈ 435) |
| M1 baseline = every M1-host config | ≈ 46, 1 cluster | ≈ 185 | ≈ 69 | ≈ 61 | ≈ 690 |
