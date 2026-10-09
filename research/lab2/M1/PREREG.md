# M1 pre-registration: ride mechanical bids, and exit when their rhythm breaks

- **Version:** `m1-v1`.
- **Written:** 2026-10-09, before any run on TRAIN, VAL, TEST, CONFIRM or FINAL data. No TRAIN data existed when
  this was written. The only run so far is the debug run on the census TRAIN third (§13): counts only, returns
  hidden.
- **Code:** `research/lab2/m1.py`, on the shared foundation `research/lab2/common.py`. Tests:
  `research/lab2/tests/test_m1.py`.
- **Spec this implements:** PLAN §4.5, plus §3 (shared protocol) and §8 (stop rules).
- **Splits:** the lead's revised splits (TRAIN 10-01 → 10-05, VAL 10-05 → 10-06 12:00, TEST 10-06 12:00 →
  10-07 19:37, CONFIRM 09-16 → 10-01, FINAL = census day).
- **Freeze.** The first official TRAIN run hashes this file into `M1/prereg.lock`. After that, `m1.py` refuses every
  stage if this file has changed. Any change is a new version (`m1-v2`) recorded in `M1/AMENDMENTS.md`, and every
  config it adds counts as new trials.

## 1. Hypothesis and mechanism

Some buyers ignore price and buy on a timer: volume and "trending" bots, and the ticker-clone operator whose steady
bid lifted the lab's F3 "drifter" coins by +0.3% to +5% per hour. A buyer that ignores price makes a predictable
upward drift. A net inflow ΔX into a pool with pricing reserve X moves the price by ((X + ΔX) / X)².

- The operator pays for the drift as marketing and later rugs. F3 found the rugs roughly cancel the drift.
- **What M1 adds is the exit.** It leaves when the bid's rhythm breaks or when a distribution precursor appears,
  instead of absorbing the rug.
- **Who loses:** the operator's marketing budget, and holders who stay through the rug.

BOOST (the AGENT) is a mechanical bid, but it ends by about g + 6 min. M1 trades from g + 30 min and **excludes
AGENT buys** from every MECH quantity, as PLAN §4.5 does.

## 2. Instrument: why the detector is bar-level

1. **PLAN §4.5's detector is wallet-level.** Minute bars carry no wallet ids.
2. **Backfill P4 (B1 raw trades) skips instant graduates** (`grad_delay_s ≤ 5`, `research/flow/backfill.py`).
   These are the factory, operator and ticker-clone coins, which are exactly the "drifter" coins M1 exists for. B1
   will therefore **never** cover M1's main target, even when it arrives.
3. **B2 minute bars cover every graduate**, for [g, g + 180 min).

So the pre-registered instrument is **MECH-bar** (§3), a minute-bar mapping of the PLAN's wallet test.

- The PLAN-verbatim wallet detector (**MECH-wallet**) is implemented and tested in `m1.mech_wallets`, on
  `snap.trades`.
- It is a **diagnostic only**: where B1 trades exist, it reports how often a PLAN MECH wallet is present when
  MECH-bar fires.
- It is **not a strategy variant**, so M1 stays at the PLAN §3.4 limit of 4 variants.

## 3. Features, as of τ = t − 20 s (all through `common.AsOf`)

**The MECH window** is the last 30 completed minute bars (PLAN: (τ − 30 min, τ]). Each window minute i has:

- `b_i`: buy SOL **minus AGENT buy SOL**. The AGENT column is NaN before `agent_known_at`; nothing is subtracted
  then.
- `n_i`: buyers with ≥ 0.01 SOL.
- `r_{i−1}`: the previous minute's return, close / close before − 1.
- The detector needs ≥ 32 completed bars.

| Feature | Definition | PLAN analog |
|---|---|---|
| `floor` | 3rd-lowest `b_i` in the window. A price-ignoring buyer present in ≥ 28 of 30 minutes puts a floor under every minute; organic flow only adds to it | MECH buys ≥ 6 in 30 min, regular gaps |
| `quiet_buyers` | median `n_i` over the 6 minutes with the lowest `b_i` | one wallet (MECH is a single wallet) |
| `cv` | coefficient of variation of the 30 `b_i` | CV of buy sizes < 0.5 (and regular gaps) |
| `spearman` | Spearman(`b_i`, `r_{i−1}`) over the window minutes that carry the bid (`b_i` ≥ 0.5 × `floor`); 0 when undefined (constant series) | \|Spearman(size, 1-min return before)\| < 0.3, over the MECH wallet's buys |
| **MECH-bar fires** | `floor` ≥ 0.01 SOL/min **and** `quiet_buyers` ≤ 2 **and** `cv` < 0.5 **and** \|`spearman`\| < 0.3 | MECH wallet exists |
| `mech_bid_h` | 60 × `floor` (SOL per hour) | 2 × Σ MECH buy SOL over 30 min |
| `drift_pred60` | ((X + `mech_bid_h`) / X)² − 1, where X = pricing reserve x + v after the last completed bar | ((x + `mech_bid_h` + `org_net_h`) / x)² − 1 |
| `bid_alive` | one of the last 2 completed minutes has `b` ≥ 0.5 × `floor` | last MECH buy within max(3 × gap, 120 s) |
| `mech_age` | minutes from the start of the current run of bid-carrying minutes (`b` ≥ 0.5 × `floor`, ≤ 2 misses) to τ | minutes since the MECH wallet's first buy |
| precursor `dump` | a completed minute with sell SOL ≥ 0.04 × X(before) × max(n_sellers, 1). By pigeonhole, at least one wallet sold ≥ 4% of the pricing reserve (≈ 8% price) in that minute | creator-linked wallets net sold ≥ 0.5% of supply |
| precursor `lp` | token conservation breaks downward: y < y(before) − buy_tok + sell_tok by > 0.5% of y. Tokens left the pool outside trades, i.e. a liquidity withdrawal. Conservation holds to 1e-6 on all 24,261 census-third bar transitions | any PumpSwap liquidity withdrawal |
| `round_trip` | `costs.py` round trip of a $20 ticket at the current pool state: fee tier by date and market cap, + Ultra 10 bps, + 20 bps buffer, impact on the pool's own k = X·y, network fees (`common.round_trip_pct`) | `round_trip_cost(mcap)` |

**Class** (PLAN §4.2 rules that M1 needs, applied in PLAN order):

1. **OPERATOR** if w120 buy SOL ex-AGENT ≥ 500 and w120 buyers ex-AGENT ≤ 30.
2. **FACTORY** if `grad_delay_s` ≤ 5 and the w120 top-5 share ex-AGENT ≥ 0.85.
3. **OTHER** otherwise. OTHER covers ORGANIC, NEWS and COMPLETED, which are all allowed.

How NULLs are handled:

- An unscanned creation (`grad_delay_s` NULL) uses the lower bound `grad_delay_lb_s` = 1,800 s, so it is not
  instant.
- A NULL input that decides the class makes the class NULL, and the coin is skipped. **NULL is never 0.**
- **Allowed classes:** OPERATOR and OTHER.

**Not available, and not faked:**

- the wallet-level `org_net_h`: drift is predicted from the mechanical floor alone, without extrapolating other net
  flow (§12);
- `orphan_share10` and creator-linked transfers. Precursors are the two bar proxies above.

## 4. Entry rule

Decisions run on common.py's grid (minute boundary + 20 s). The entry is taken at the first decision time where
every condition holds, at most once per coin:

- age in [30, 120] min. The upper bound exists because B2 bars end at g + 180 min, and it leaves ≥ 60 min of hold
  data;
- class ∈ {OPERATOR, OTHER};
- MECH-bar fires, `bid_alive`, and `mech_age` ≥ 10 min;
- no precursor (`dump` or `lp`) in the 30-minute MECH window;
- `drift_pred60` ≥ m × `round_trip`.

## 5. Exits

Sell at the first of:

| Exit | Rule |
|---|---|
| Rhythm break | the last 2 completed minutes after the entry decision both have `b` < 0.5 × the entry `floor` |
| Precursor | **exit set `rhythm+prec` only**: a `dump` or `lp` flag in any minute completed after the entry decision |
| Stop | −10% from the entry fill (mechanical) |
| Time | 6 h. The data horizon g + 179 min truncates it; such exits are labelled `horizon` and reported |

**Placebo positions** carry no state. Their floor is recomputed from the bars completed at their own decision time,
so they run the same rule. A placebo coin with no floor (< 0.01 SOL/min) cannot have a rhythm break.

## 6. The TRAIN grid: exactly 4 configurations, every one a trial

**m ∈ {1, 2} × exit set ∈ {`rhythm`, `rhythm+prec`}.** This is PLAN §4.5's grid, the whole of its §3.4 M1 limit
of 4.

- Each config's params dict carries every constant in §3-§5, the fill model and the version. Any change is a new
  trial.
- **Model check:** one more trial, `M1-modelcheck`.
- **Twin:** the TEST / CONFIRM / FINAL run of the twin is logged as `M1-twin` (§8), adding 1 more.
- **M1's total is 6 trials**, on top of the lab's 2,575 in `research/lab2/trials.json`.

**Fills and costs** come from common.py's `FillConfig()` defaults:

| Setting | Value |
|---|---|
| Size | $20 |
| Latency | 30 s |
| Entry fill | `"worst"`: the max of the landing bar's open and high |
| Exit fill | `"worst"`: the min of open and low |
| Entry-bar exits | on |
| Costs | PumpSwap tier by date, + 10 bps Ultra, + 20 bps buffer, network fees, pricing on X = x + v |

**Stress and sensitivity runs** come from the same call, and are never used to select:

- costs × 1.5;
- rent of $0.22;
- `entry_bar_exits=False` with `exit_delay_bars=1`.

## 7. Model check, stop rule 5 (TRAIN, before any P&L)

**Observations:**

- Allowed-class TRAIN coins.
- Decision times: the last grid time ≤ g + a min, for a ∈ {35, 45, …, 115}. The detector needs 32 completed
  bars, so it cannot fire before about g + 33 min, and the 60-minute label must end inside the g + 179 min window.
- Kept where MECH-bar fires, `bid_alive` holds and `mech_age` ≥ 10 min.

**Label:** the realized 60-minute mid-price change, close(τ + 60 min) / close(τ) − 1. It is read through AsOf
60 minutes later and is never a feature.

**Fit:** OLS of the label on `drift_pred60` over all observations, equally weighted. The decision is the PLAN rule
on the point estimates:

| Result | Condition | Consequence |
|---|---|---|
| **UNDERPOWERED** | < 30 coins or < 100 observations | M1 halts; the grid is not run |
| **KILL** | slope < 0.5 or R² < 0.05 | **M1 is dead** (stop rule 5). The grid is never run, and every later stage refuses |
| **PASS** | otherwise | continue |

**Reported, never decisive:**

- the slope's coin-bootstrap 95% CI;
- the fit with one observation per coin;
- the fit with the label winsorized at 5-95%;
- a log-log fit;
- the fit without windows that contain a rug;
- the share of rug windows;
- MECH-wallet agreement, where B1 exists.

## 8. Procedure by stage (`python research/lab2/m1.py --stage …`)

### Every stage

A stage refuses to run unless:

- `M1/PREREG.md` exists, and matches `prereg.lock` once locked;
- PLAN §8 rule 1 holds: gates V1-V4 pass in `FLOW/validation.json`;
- the split's coverage is complete: every chain hour is scanned for curve and B2, and ≤ 5% of tradeable coins lack a
  complete B2 window. FINAL is exempt: its end-of-data coins are reported, not blocking;
- the guarded splits have their flags: `LAB2_ALLOW_TEST`, `LAB2_ALLOW_CONFIRM`, `LAB2_ALLOW_FINAL`. `m1.py` never
  sets them.

### TRAIN (all searching)

1. Run the model check (§7).
2. On PASS, run the 4 configs, each with the matched random control (§9) and the stress runs.
3. **Shortlist rule** (≤ 2 configs):
   - **The candidate exit set is fixed: `rhythm+prec`.** The precursor exit is M1's thesis, and the PLAN's
     rug-hit criterion compares it with the no-precursor version.
   - For each m, the candidate (m, `rhythm+prec`) qualifies on TRAIN if all of these hold:

     | Requirement | Bar |
     |---|---|
     | Sample | ≥ 30 trades from ≥ 3 operator clusters (§10) |
     | Mean net | > 0 |
     | Mean without the top 2 trades | > 0 |
     | Matched-control `mean_diff` | > 0 |

   - m* is the qualifying m with the higher coin-bootstrap 90% CI lower bound. Ties go to the higher mean, then to
     m = 2.
   - **Shortlist = the pair** (m*, `rhythm`) and (m*, `rhythm+prec`). It is written with `common.write_shortlist`
     and frozen at the first VAL run.
4. If nothing qualifies:
   - **NO_CONFIG** (M1 fails on TRAIN) when at least one candidate met the sample bar;
   - **UNDERPOWERED_TRAIN** otherwise.
5. **A decision on complete TRAIN is final.** A re-run needs `--rerun-reason` naming a data correction. The previous
   result is archived as `train_prev_<ts>.*`.
6. `--allow-partial` runs a **PROVISIONAL** TRAIN on partial data:
   - it writes `train_prelim.*`;
   - it never writes a shortlist or a lock;
   - it never unlocks VAL.

### VAL (≤ 2 configs, the shortlist written before the run)

Run both shortlisted configs once, with the matched control and the stress runs. The decision uses the candidate's
VAL trades:

| Decision | Condition | Consequence |
|---|---|---|
| **UNDERPOWERED_VAL** | n < 5 | stop |
| **FAIL_VAL** | n ≥ 5 and (mean ≤ 0 or mean without the top 2 ≤ 0) | stop (PLAN §8 rule 7 input) |
| **SELECTED_UNDERPOWERED** | 5 ≤ n < 15, mean > 0 and mean without the top 2 > 0 | proceed, flagged |
| **SELECTED** | n ≥ 15, mean > 0 and mean without the top 2 > 0 | proceed |

### TEST (one run per hypothesis)

- Run the candidate once as `M1` and the twin once as `M1-twin`, each with the matched control and the stress runs.
- **Verdict** = `common.verdict_entry(test, val=VAL candidate, min_mean=0.02)`. That is PLAN §3.5 items 1-8 with
  M1's +2% mean bar, plus the §3.6 auto-rejections. Item 9 (FINAL mean > 0) is judged in the overall verdict once
  FINAL has run, so a missing FINAL never makes TEST or CONFIRM "incomplete".
- **Plus PLAN §4.5's extras:**

  | ID | Criterion |
  |---|---|
  | M1.1 power | ≥ 60 trades from ≥ 3 operator clusters |
  | M1.2 | the 90% CI lower bound > 0 when resampling operator clusters (and coins, item 3) |
  | M1.3 | mean > 0 without the largest cluster |
  | M1.4 | the candidate's rug-hit rate < ½ of the twin's. Vacuous, and non-blocking, when the twin has no rug hit |

- **How they combine:**
  - REJECTED if `verdict_entry` rejects;
  - UNDERPOWERED if it is underpowered or M1.1 fails;
  - FAIL if any criterion fails;
  - INCOMPLETE if any criterion is missing;
  - PASS otherwise.
- With a 1.3-day TEST, **UNDERPOWERED is expected.**

### CONFIRM (09-16 → 10-01; one run, never searched)

- **Precondition:** TEST is not REJECTED, and either TEST mean > 0 or TEST n < 5 (no evidence either way).
  Otherwise M1 has failed TEST, and CONFIRM is not spent.
- Run the same pair once, with the same verdict as TEST.
- CONFIRM is the powered out-of-sample test.

### FINAL (the census day)

- It runs only after TEST.
- Run the candidate and the twin once on all of FINAL.
- Report the sign and n overall and per census third. The TRAIN third was used for debugging only, with returns
  hidden.

### Overall M1 verdict

**EDGE** requires every one of:

- the model check PASS;
- VAL SELECTED or SELECTED_UNDERPOWERED;
- TEST not REJECTED, and (TEST mean > 0 or n < 5);
- the CONFIRM verdict PASS;
- FINAL mean > 0.

Otherwise the verdict is one of:

- **KILLED** (stop rule 5);
- **UNDERPOWERED** (TRAIN, VAL or CONFIRM);
- **NO EDGE**.

## 9. Controls

**Matched random control** (PLAN §3.4): `common.backtest`'s placebo.

- 20 draws per signal.
- Random coins of the same split that are in an allowed class and `alive` (≥ $1.5k of volume in 15 min, market
  cap ≥ $6k).
- The decision age is within ±120 s of the signal's.
- The exits are the same (§5).
- It feeds PLAN §3.5 item 5 (≥ +6 points) and the TRAIN shortlist (`mean_diff` > 0).

## 10. Metric, statistics and operator clusters

**Metric and statistics:**

- The unit is the net return per $20 trade (`ret_net`), one entry per coin per config.
- CIs come from coin bootstraps (10,000 draws, at 90% and 95%).
- Also reported:
  - the mean without the top 2 trades;
  - the top-coin share;
  - halves;
  - the $100 / 5-slot portfolio;
  - costs × 1.5;
  - the deflated Sharpe ratio, counting every trial in the ledger;
  - per class (OPERATOR / OTHER);
  - `horizon` exits;
  - the rug-hit rate (a > 50% one-minute drop during the hold).

**Operator clusters** follow the PLAN's idea of linking operators by co-appearing wallets, using what B2 has.

- They are the connected components of allowed-class coins that share any of:
  - a creator;
  - an upper-cased symbol (ticker clones are relaunched under the same symbol);
  - a wallet among their top-5 early (w120) pool buyers, with AGENT and pooled accounts excluded.
- The fields are read through AsOf at the end of each coin's window. Other coins are their own cluster.
- Clusters are a grouping for the bootstrap and the concentration checks, never a feature.
- **Over-merging only widens the cluster CIs, which is conservative. Under-merging would narrow them.** The
  creator/symbol links alone gave 17-18 "clusters" for 20-24 debug entries. One wallet is a top-5 early buyer on 26
  of the 34 OPERATOR coins of the census TRAIN third, so the wallet link is needed (§13).

## 11. Kill criteria (PLAN §8) and declarations

**Kill criteria:**

| Rule | How M1 applies it |
|---|---|
| **Stop rule 1 (data first)** | V1-V4 must pass; stages refuse otherwise |
| **Stop rule 2** | Fills are minute-bar "worst" fills until X1 exists. If X1 finds them off by ≥ 1 point, the frozen pair is re-run with replayed fills, with no new search, before any promotion |
| **Stop rule 5** | The model check fails (slope < 0.5 or R² < 0.05): M1 dies before any P&L |
| **Stop rule 7** | FAIL_VAL is reported to the lead. If S1, D1 and M1 all fail VAL, entries on fresh graduates stop |
| **Stop rule 8** | Every config counts (§6) |

**Declarations passed to `auto_rejections`:**

```
uses_organic_flow = False
uses_wallet_reputation = False
uses_truncated_windows = False
uses_current_state_fields = False
```

M1 counts no flow as organic. Its drift uses only the mechanical floor, with AGENT buys removed.

## 12. Deviations from the PLAN, stated up front

| Area | Deviation |
|---|---|
| Splits | The lead's revised ones: TRAIN 4 days, VAL 1.5, TEST 1.3, CONFIRM 15. The shortlist sample bar is 30 trades, not 60. PLAN §4.5's "≥ 60 trades from ≥ 3 clusters" is checked on TEST and CONFIRM (M1.1) |
| Detector | MECH-bar instead of wallet MECH (§2). Bots slower than one buy per minute, and price-ignoring bids hidden under heavy organic flow, are invisible to it. CREATOR exclusion is impossible on bars; AGENT is excluded. The PLAN's two regularity tests (gap CV < 0.25, size CV < 0.5) become one: the CV of the minute sums < 0.5 |
| `org_net_h` | Not identifiable on bars. `drift_pred60` uses the mechanical floor alone |
| Precursors | Bar proxies: the `dump` pigeonhole bound and the `lp` token-conservation break. `orphan_share10` and creator-linked transfers are not available |
| Operator clusters | Shared creator, symbol or top-5 early pool buyer (B2's w120 list), not co-appearance of MECH or creation-slot wallets |
| Hold | 6 h is truncated at g + 179 min by B2. Entries stop at g + 120 min |
| Fills | Minute-bar "worst" fills, not replayed fills. No 2-second exit variant (X1) |
| Rugs | "One-trade drop > 50%" is measured as a one-minute drop > 50% (an upper bound on one-trade drops) |
| Fees | The pool fee inside user-side buy SOL (≤ 1.25%) is not removed from `mech_bid_h` (overstates the drift by ≤ 2.5% of itself) |
| SOL/USD | Covers 10-07 09:00 → 10-08 18:15 only. Earlier dates use the edge price. This affects the $20 → SOL sizing (impact) and the placebo's `alive` filter, not M1's entry conditions |

## 13. Debug findings and expected sample (census TRAIN third, counts only)

**The run.** `python research/lab2/m1.py --debug` writes `M1/debug.md` and `M1/debug.json`.

- 450 usable coins, created over 12.5 h (0.52 days).
- Returns, rug hits and model-check fits are hidden.
- No parameter was chosen on these coins.
- Its trials go to a scratch ledger, never to `trials.json`.

**Definition corrections made while debugging.** All four came from structure or unit tests, never from outcomes,
and all were made before any TRAIN data existed:

1. **The steadiness test (`cv` < 0.5) was added.**
   - Without it, MECH-bar fired on decaying organic coins. Their quietest minutes have 1-2 buyers, while their
     normal minutes have 15-80.
   - With it, MECH-bar fires on OPERATOR coins only: about 60 buys a minute from 2-4 wallets, at a stable
     0.8-1.4 SOL a minute. That is the steady operator bid behind F3's "drifters".
   - The threshold is the PLAN's size-CV threshold, 0.5, not a tuned one.
2. **Spearman is computed over the minutes that carry the bid.** A unit test showed that a steady synthetic bot
   which skips two minutes gets Spearman 0.43 from its own price impact.
3. **Clusters also link coins through shared top-5 early pool buyers** (§10).
4. **The model-check grid starts at 35 min**, because the detector needs 32 completed bars.

**Counts, and extrapolations that assume the operator's activity on other days resembles the census day.** The
operator can change its schedule at any time.

| Measure | Census TRAIN third (0.52 d) | Per day | TRAIN (4 d) | VAL (1.5 d) | TEST (1.32 d) | CONFIRM (15 d) |
|---|---:|---:|---:|---:|---:|---:|
| Allowed-class coins | 267 (34 OPERATOR, 233 OTHER) | ≈ 513 | ≈ 2,050 | ≈ 770 | ≈ 675 | ≈ 7,700 |
| Coins where MECH-bar fires (ages 30-120 min) | 26 (all OPERATOR) | ≈ 50 | ≈ 200 | ≈ 75 | ≈ 66 | ≈ 750 |
| Model-check observations | 131, from 24 coins | ≈ 250, from ≈ 46 coins | ≈ 1,000, from ≈ 185 coins | | | |
| Entries, m = 1 | 24 | ≈ 46 | ≈ 185 | ≈ 69 | ≈ 61 | ≈ 690 |
| Entries, m = 2 | 20 | ≈ 38 | ≈ 155 | ≈ 58 | ≈ 51 | ≈ 575 |
| Operator clusters among the entries | **1** | | | | | |

**What these counts imply, before any TRAIN data:**

- **Concentration is the binding constraint, not the trade count.**
  - Every debug entry and model-check observation belongs to **one operator cluster**. One wallet is a top-5 early
    buyer on 26 of the 34 OPERATOR coins.
  - If TRAIN looks like the census day, the shortlist rule (≥ 3 clusters) returns **UNDERPOWERED_TRAIN**, and M1
    stops before VAL. That is the pre-registered answer to "is this one operator's schedule?", not a code failure.
- **Holds mostly end at the data horizon.**
  - 20 of 24 debug holds (m = 1) end at g + 179 min. The bid does not break inside the B2 window.
  - So the P&L largely measures "ride to g + 179 min". The rhythm and precursor exits rarely fire.
  - No precursor fired on the census third, so each twin pair had identical trades there. Expect M1.4 (rug rate) to
    be vacuous unless precursors fire on TRAIN, VAL or TEST.
- **The model check is powered.** It needs 30 coins and 100 observations, and TRAIN is expected to give about
  185 coins and 1,000 observations, all from OPERATOR coins.
- **TEST will be underpowered on the cluster count** (M1.1). Its expected trade count (≈ 51-61) sits at the 60-trade
  bar.
