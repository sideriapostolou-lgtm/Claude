# S1 pre-registration: buy once the insiders' cheap inventory is spent

- **Version:** `s1-v1`.
- **Written:** 2026-10-08, before any run on TRAIN, VAL, TEST, CONFIRM or FINAL data. No TRAIN data existed when
  this was written.
- **Code:** `research/lab2/s1.py`, on the shared foundation `research/lab2/common.py`.
- **Spec this implements:** PLAN §4.3, plus §3 (shared protocol) and §8 (stop rules).
- **Splits:** the lead's revised splits.
- **Freeze.** The first official TRAIN run hashes this file into `S1/prereg.lock`. After that, `s1.py` refuses to
  run VAL, TEST, CONFIRM or FINAL if the file has changed. Any later change is a new version, and every config it
  adds counts as new trials.

## 1. Hypothesis and mechanism

Insiders hold inventory bought 10-100x below the pool price, and they sell into rallies. The insiders are the
creator, the bundle, snipers, the completer, and wallets that sell tokens they never bought. While that inventory
exists, buyers are exit liquidity.

Once the inventory is spent, and while organic wallets are still net buyers, the remaining sellers sit at a loss
and the buyers are real. S1 buys at that moment.

BOOST (the protocol's fee-free buyer) plays a minor role:

- It makes 29-30 slices, spends 17.58 SOL, buys every ~12 s and starts ~2 s after g.
- It is used only to ask whether organic wallets absorbed supply alongside it (`boost_absorb`).
- AGENT identity is used only from its 4th buy (`agent_known_at`).

## 2. Data prerequisites: a stage refuses to run without them

1. **B1 raw trades are required.**
   - Source: `b1_trades.parquet` from backfill phase P4, non-dust trades ≥ 0.01 SOL over [created, g + 120 min].
   - Coverage: at least **95%** of the split's S1-universe coins (§3).
   - Why: every S1 feature is wallet-level. Minute bars carry no wallet roles. From bars, `insider_rem` is only
     bounded by how far the price sits above its floor, which is the killed FL1 idea, not S1. So **no bar-only
     proxy is run under the S1 name.**
2. **The split's B2/curve coverage must be complete:**
   - every chain hour scanned (`chain_hours_scanned_frac ≥ 0.999`);
   - no partial day.
   - **TRAIN exception:** `--allow-partial` runs TRAIN as a **PRELIMINARY** run. It writes `train_prelim.*`, never
     writes a shortlist, and its gate verdict is not official.
3. **Guarded splits** need the environment flag set by whoever runs the judge:
   - TEST: `LAB2_ALLOW_TEST=1`;
   - CONFIRM: `LAB2_ALLOW_CONFIRM=1`;
   - FINAL: `LAB2_ALLOW_FINAL=1`.

   `s1.py` never sets these flags itself.

## 3. Universe (S1-universe)

A coin is in the S1-universe if it meets all of these:

- It is a common.py usable coin: SOL-quoted, not Mayhem, virtual reserve known, and a complete B2 window.
- `curve_partial = False`: the CreateEvent was scanned, so the creation-slot trades are in B1.
- `created_exact`.
- `grad_delay_s > 5`. Instant graduates are the factory class, and P4 does not fetch them.
- It has B1 trades.

**Truncation.**

- A coin whose B1 prefix at τ already holds 20,000 trades (P4's `max_trades`) may be missing trades.
- Its features are NULL from that point on.
- This test is causal: it uses only the prefix length at τ.

**Horizon.**

- B1 ends at g + 7,200 s, and features are NULL for τ ≥ g + 7,200.
- After that point an open position keeps only its mechanical exits: the trail and the time limit.

## 4. Roles, as of τ = t − 20 s

All roles come from `snap.trades`, which holds B1 rows with ts ≤ τ.

| Item | Rule |
|---|---|
| Wallet key | `wallet_h`, the ClickHouse `cityHash64` of the 32-byte key. The creator's base58 address is hashed with a pure-Python port, checked on 917/917 real pairs |
| Pooled accounts | `common.POOLED_ACCOUNTS` plus `pooled_accounts.json`, and the `pooled` column when present. Excluded from every role, ledger, count and orphan computation. Their SOL still counts in pool totals |
| Ledger | Per wallet, in chain order: `pos` = tokens bought − sold; `peak` = max `pos`; average-cost `cost` |
| `orphan_part` | max(0, sell − max(pos_before, 0)). It counts only above **2% of the sell**, a tolerance for the dust that B1 drops |
| CREATOR | `snap["creator"]`, hashed |
| BUNDLE | Curve buys in `c_slot` |
| SNIPER | First curve buy at ≤ c_ts + 60 s, or among the first 20 distinct curve buyers. Usable from max(c_ts + 60, min(arrival of the 20th buyer, g)) |
| COMPLETER | The wallet with the most curve-buy SOL (user SOL − fees) inside the real-SOL band [55, 85]. Real SOL is the virtual SOL before the trade minus `vsol0` |
| TRANSFEREE | Any wallet with an orphan sell at or before τ. Token transfers are not available |
| INSIDER (INS) | CREATOR ∪ BUNDLE ∪ SNIPER ∪ COMPLETER ∪ TRANSFEREE, minus AGENT and pooled accounts |
| AGENT | `research/flow/features.detect_agent(rule="robust")`, run on pool buys in [g, g + 420 s) by wallets with no sell in the prefix. Known from its 4th buy |
| BOT | ≥ 4 trades, and either a median buy→sell hold under 10 s or ≥ 3 buy→sell round trips within 60 s. The registry part of the PLAN's rule is not available |
| WASH | Any opposite-side pair within 60 s whose token sizes differ by less than 5% of the larger |
| MECH | PLAN §4.5, over pool trades in (τ − 30 min, τ]. Not AGENT and not CREATOR. ≥ 6 buys; sells ≤ 10% of buy SOL; CV of buy gaps < 0.25; CV of buy sizes < 0.5; \|Spearman(size, 1-minute return before the buy)\| < 0.3 |
| DUST | Absent: B1 drops trades under 0.01 SOL |
| ORGANIC | Not pooled, INS, AGENT, BOT, WASH or MECH |

## 5. Features at τ, exactly as in PLAN §4.3

All features use positive positions only, pos⁺ = max(pos, 0).

**Venues.**

- The flow windows (`org_*`, `orphan_share10`, `boost_absorb`, `insider_into_boost`) use **PumpSwap pool trades
  only**. At g + 6 min, the window (τ − 600, τ] would otherwise reach back into the bonding curve.
- Creator sells and every position count **all venues**.

| Feature | Definition |
|---|---|
| `insider_rem` | Σ_{w∈INS(τ)} pos⁺_w(τ) / max over s ≤ τ of Σ_{w∈INS(τ)} pos⁺_w(s). The insider set is fixed at τ. NULL when the denominator is 0 |
| `overhang` | Σ_INS pos⁺ / circ(τ), where circ = 1e9 − y(τ) − AGENT tokens. BOOST burns what it buys; there is no burn data, so AGENT tokens stand in. Diagnostic only |
| `insider_mult` | p(τ) / (Σ_INS cost / Σ_INS pos⁺). Diagnostic only |
| `boost_absorb` | B_ORG − S_ORG over pool trades in [g, g + 300]. NULL before τ ≥ g + 300 |
| `insider_into_boost` | S_INS[g, g + 300] / max(B_AGENT[g, g + 300], 0.1). Diagnostic only |
| `org_net10` | B_ORG − S_ORG over (τ − 600, τ] |
| `org_buyers10` | Distinct ORGANIC buyers over (τ − 600, τ] |
| `org_net5` | Like `org_net10`, over (τ − 300, τ]. Used by an exit |
| `orphan_share10` | Σ orphan_part / Σ sell tokens over (τ − 600, τ]. 0 when there are no sells |
| `creator_sold_frac` | Creator tokens sold / creator peak. 0 if the creator never held and never sold; ∞ if it never held but sold |
| `creator_sold10` | Creator tokens sold in (τ − 600, τ] / creator peak. Same 0 / ∞ rule |
| `completer_pos_frac` | COMPLETER pos⁺ / its peak |
| `alive` | common.py `snap.alive()`: USD volume over 15 minutes ≥ $1.5k and market cap ≥ $6k |

**G1 class: the on-chain "G-chain" variant**, computed from B1 rows with ts ≤ g + 120 and AGENT as known then.
Rules apply in this order:

1. **OPERATOR** if `amm_buy_sol_2m` ≥ 500 and `amm_buyers_2m` ≤ 30.
2. **FACTORY** if `grad_delay_s` ≤ 5 and `amm_top5_share_2m` ≥ 0.85. This class is empty in the S1-universe.
3. **COMPLETED** if `grad_delay_s` > 5 and any of:
   - `completer_share` ≥ 0.6;
   - `curve_top3_buy_sol / curve_buy_sol` ≥ 0.6;
   - `curve_n_buyers` < 15.
4. **ORGANIC** otherwise. NEWS needs metadata we do not have; it is allowed anyway, so it merges into ORGANIC.

**Allowed classes:** ORGANIC and COMPLETED. A NULL input makes the class NULL, and the coin is skipped. **NULL is
never 0**, and a NULL condition never passes.

## 6. Decision times

The PLAN's checkpoints are t ∈ {g + 6, 8, 10, 15, 20, 30, 45, 60, 90, 120} min.

- On common.py's minute grid (minute boundary + 20 s), checkpoint c is the **last grid time ≤ g + c min**. Rounding
  down keeps the 120-minute checkpoint inside B1.
- Entry is taken at the first checkpoint where every condition holds, and at most once per coin.

## 7. Dose-response gate (stop rule 3)

**Population and measurement:**

- **Checkpoints:** cp ∈ {10, 30} min.
- **Eligible coins:** S1-universe coins with `ok` features, allowed class, `alive`, and `insider_rem` not NULL.
- **Trade:** enter at the checkpoint, hold 30 minutes (`ExitSpec(max_hold_s=1800)`), net of all costs, with the
  §8 fills.
- **Quintiles:** rank `insider_rem` ascending; ties break by decision time, then mint. Q = ⌊5·rank / n⌋ + 1, so
  Q1 = spent and Q5 = full.

**TRAIN, at both checkpoints:**

| Requirement | Bar |
|---|---|
| Eligible coins | ≥ 100 |
| Adjacent inversions, mean(Q_{i+1}) > mean(Q_i) | ≤ 1 |
| Q1 vs Q5 | mean(Q1) > mean(Q5) |

- If both checkpoints meet the bars, the gate passes on TRAIN.
- If a checkpoint has < 100 coins, the result is **GATE_UNDERPOWERED** and S1 halts.
- Otherwise the result is **GATE_FAIL**: **S1 is dead** (stop rule 3), and the entry grid is never run.

**VAL, at both checkpoints, before any VAL run of the entry rule:**

| Requirement | Bar |
|---|---|
| Eligible coins | ≥ 50 |
| mean(Q1) − mean(Q5) | ≥ 0.05 (5 points) |

- If a checkpoint has fewer than 50 coins, the result is GATE_VAL_UNDERPOWERED and S1 halts.
- If the gap is < 0.05 at either checkpoint, the result is GATE_VAL_FAIL and S1 is dead.

Coin-bootstrap CIs on Q1 − Q5 are reported. They are not part of the bar.

## 8. Entry rule, the grid (every point is a trial), exits, fills and costs

**Conditions.** Every one must hold at the checkpoint:

- class ∈ {ORGANIC, COMPLETED}; a COMPLETED coin also needs `completer_pos_frac` ≤ 0.10;
- `alive`;
- `insider_rem` ≤ θ_rem;
- `org_net10` > 0;
- `org_buyers10` ≥ θ_buy;
- `orphan_share10` < 0.15;
- `creator_sold10` < 0.20;
- if `absorb_req`: `boost_absorb` > 0.

**TRAIN grid: exactly 8 configurations.** θ_rem ∈ {0.10, 0.25} × θ_buy ∈ {10, 20} × `absorb_req` ∈ {yes, no}.

- This uses the whole of PLAN §3.4's S1 limit of 8.
- Every config's params dict includes every fixed constant and the version, so any change is a new trial.

**Exits.** These are fixed, not searched. Sell at the first of:

- a 30% trailing stop from the peak since entry;
- 90 minutes;
- `org_net5` ≤ −1 SOL;
- `orphan_share10` > 0.25;
- the creator has sold ≥ 20% of its peak since entry;
- insider holdings, Σ_INS pos⁺, have grown by > 2% of supply (20M tokens) since entry.

How the exits run:

- The entry baseline for the last two exits is recomputed at τ_entry from the trade prefix. Placebos are therefore
  treated exactly like signals.
- Flow exits stop when the B1 horizon ends. The trail and the time limit then remain.
- Exits are checked at every decision minute.

**Fills and costs** come from common.py's `FillConfig()` defaults:

| Setting | Value |
|---|---|
| Size | $20 |
| Latency | 30 s |
| Entry fill | `"worst"`: the max of the landing bar's open and high |
| Exit fill | `"worst"`: the min of open and low |
| Entry-bar exits | on |
| Costs | PumpSwap tier by date (costs.py), + 10 bps Ultra, + 20 bps buffer, network fee, pricing on X = x + v |

**Not available until X1 exists:** replayed trade-level fills and the D_exit = 2 s variant. Stop rule 2 applies: if
X1 finds minute-bar fills off by ≥ 1 point, the frozen config must be re-run with replayed fills, with no new
search, before any promotion.

**Sensitivity runs.** These are reported and never used for selection or verdicts:

- `entry_bar_exits=False`;
- `exit_delay_bars=1`;
- `latency_s=5`;
- rent stress of $0.22.

## 9. Controls

- **Control 1, the population control** (hypothesis key `S1-control1`, one config), **time-matched** (amendment 1).
  - PLAN §4.3: "the same coins at the same t without the flow conditions". At EVERY checkpoint cp, every coin that is
    `ok`, in an allowed class and `alive` at cp is entered at cp (`s1.control1_entries`, run through
    `common.run_entries`: several entries per coin, one per checkpoint). Same universe, class filter and exits.
    **No flow conditions.**
  - It is compared at the same ages: mean(S1) − Σ_cp w_cp · mean(control 1 at cp), with w_cp = S1's share of trades
    at checkpoint cp (`s1.matched_control_diff`). The 95% / 90% CIs come from a JOINT coin bootstrap (a coin in
    both sets carries its trades in both). A checkpoint where S1 traded but control 1 has no trade leaves the
    difference undefined (`None`).
- **Control 2, the matched random control** (PLAN §3.4).
  - `common.backtest` placebo: 20 draws per signal; random S1-eligible coins (`ok`, allowed class, `alive`); a
    decision age within ±120 s; the same exits.
  - It feeds §3.5 criterion 5.

## 10. Metric, statistics and trial counting

**Metric and statistics:**

- The unit is the net return per $20 trade (`ret_net`), at most one entry per coin per rule.
- CIs come from coin bootstraps (10,000 draws, at 90% and 95%).
- Also reported: drop-top-2, top-coin share, halves, the $100 / 5-slot portfolio, and costs × 1.5.

**Trials and the deflated Sharpe ratio:**

- The ledger is `research/lab2/trials.json`.
- Its baseline is the lab's **2,575** logged configurations.
- S1 adds 8 (`S1`) + 2 (`S1-gate`) + 1 (`S1-control1`) = **11** trials.
- Debug runs on the census TRAIN third are logged as debug and do not count.

## 11. Procedure by stage (`python research/lab2/s1.py --stage …`)

### TRAIN (all searching)

1. Run the gate on TRAIN (§7). Then:
   - on GATE_FAIL, S1 is dead, and the grid is never run;
   - on GATE_UNDERPOWERED, S1 halts.
2. Run the 8 configs, each with control 2, plus control 1.
3. **Shortlist rule.** A config qualifies if all of these hold on TRAIN:

   | Requirement | Bar |
   |---|---|
   | Sample | ≥ 30 trades from ≥ 20 coins |
   | Mean | > 0 |
   | Mean without the top 2 trades | > 0 |
   | Mean − control-1 mean | ≥ +0.06 |
   | Control-2 `mean_diff` | > 0 |

4. Rank the qualifying configs:
   - by their coin-bootstrap 90% CI lower bound, descending;
   - ties by mean, then by `params_hash`.
5. Keep the top 2, or 1 if only one qualifies.
6. Write the frozen shortlists `S1` (those configs), `S1-gate` (both gate checkpoints) and `S1-control1`.
7. If nothing qualifies:
   - **NO_CONFIG** (S1 fails on TRAIN) when at least one config had ≥ 30 trades from ≥ 20 coins;
   - **UNDERPOWERED_TRAIN** otherwise.
8. **A kill on complete TRAIN is final.** GATE_FAIL and NO_CONFIG are not re-rolled.
   - A re-run needs `--rerun-reason`, naming the data correction that justifies it.
   - The previous result is archived as `train_prev_<ts>.json`.

### VAL (at most 2 configs, from the shortlist written before the run)

1. Run the gate's VAL check first (§7).
2. Run each shortlisted config once, with control 2 and costs × 1.5, plus control 1.
3. **Selection for TEST.** A config qualifies if, on VAL:
   - n ≥ 15;
   - mean > 0, the same sign as TRAIN;
   - mean − control-1 mean ≥ +0.06.
4. Pick by the higher VAL 90% CI lower bound, then by the higher mean.
5. The outcome is one of:
   - **SELECTED**;
   - **UNDERPOWERED_VAL**, when every shortlisted config has < 15 VAL trades;
   - **FAIL_VAL**, which feeds stop rule 7.

### TEST (one run per hypothesis)

1. Run the selected config once, with control 2 and costs × 1.5, plus one run of control 1.
2. The verdict is `common.verdict_entry(test, val=VAL)`, i.e. PLAN §3.5 criteria 1-8, plus:
   - the PLAN §3.6 auto-rejections, from the declarations in §12;
   - control-1 margin ≥ +0.06 when control 1 has ≥ 20 trades.
3. With the revised 1.3-day TEST, an **UNDERPOWERED** verdict is expected.

### CONFIRM (2026-09-16 → 10-01; one run, never searched)

- **Precondition:** TEST mean > 0 and TEST not REJECTED. Otherwise S1 has failed and CONFIRM is not spent.
- Run the same frozen config once, with control 2 and costs × 1.5, plus control 1.
- The verdict is `verdict_entry(confirm, val=VAL)` plus the control-1 margin ≥ +0.06.
- CONFIRM is the powered out-of-sample test: its 15 days should give 75-375 signals.

### FINAL (the census day)

- Allowed only after TEST.
- Run the frozen config once on all of FINAL.
- Report the sign and n overall and per lab third.
- The census TRAIN third was used for debugging only, with returns hidden.

### Overall S1 verdict

**EDGE** requires every one of:

- the TRAIN gate and the VAL gate pass;
- the VAL outcome is SELECTED;
- TEST: mean > 0, the same sign as VAL, no auto-rejection, and the control-1 margin ≥ +0.06 when control 1 has
  ≥ 20 trades;
- CONFIRM: `verdict_entry` is PASS and the control-1 margin ≥ +0.06;
- FINAL mean > 0.

Otherwise the verdict is one of:

- **UNDERPOWERED**, when CONFIRM has < 60 trades or < 40 coins and nothing has failed;
- **NO EDGE**, in every other case.

## 12. Kill criteria and declarations (PLAN §8 and §3.6)

**Kill criteria:**

- **Stop rule 1 (data first).** `s1.check_data` calls `common.validation_gates(split)`: V1, V2 (≥ 99%) and V4 must
  pass on raw trades FROM THE SPLIT'S OWN DATES, validated after that data was fetched, plus V3 (census sample).
  The census-day run of 2026-10-08 21:55 covers no EXT split and predates the post-audit re-fetch, so every
  non-debug stage refuses until the split's dates are validated. Stages also refuse when B1 coverage is under 95%,
  the split is incomplete, a B2 hour is mid-run, or the SOL/USD series starts after the split's coins
  (`common.coverage_problems`).
- **Stop rule 2.** The fill-model caveat in §8.
- **Stop rule 3.** GATE_FAIL on TRAIN kills S1 before VAL. GATE_VAL_FAIL kills it before the entry rule's VAL run.
- **Stop rule 7.** FAIL_VAL is reported to the lead. If S1, D1 and M1 all fail VAL, entries on fresh graduates
  stop.
- **Stop rule 8.** Every config counts, as set out in §10.

**Declarations passed to `auto_rejections`:**

```
uses_organic_flow = True
organic_excludes = [AGENT, BOT, WASH, DUST, MECH]
uses_wallet_reputation = False
uses_truncated_windows = False
uses_current_state_fields = False
```

## 13. Deviations from the PLAN, stated up front

- **Splits** are the lead's revised ones:
  - TRAIN: 4 days;
  - VAL: 1.5 days;
  - TEST: 1.3 days;
  - CONFIRM: 15 days.

  The gate and the selection minimums are therefore sized for 4 / 1.5 days.
- **G1** is the on-chain variant only. NEWS merges with ORGANIC, and FACTORY's metadata tests are absent.
- **TRANSFEREE** comes from orphan sells only, without `token_transfers`.
- **BOT** has no registry part.
- **Burned tokens** are approximated by AGENT tokens.
- **Fills** are minute-bar "worst" fills, not replayed fills.
- **Exits after g + 120 min** are mechanical only.
- **The orphan rule** has a 2% dust tolerance.
- **Checkpoints** are rounded down to the minute grid.

## 14. Expected sample (from the debug run on the census TRAIN third, counts only)

These counts come from `S1/debug.md`: real bars and graduation columns over 12.5 h of creations, with no returns
looked at.

| Measure | Census TRAIN third (12.5 h) | Per day | TRAIN (4 d) | VAL (1.5 d) |
|---|---:|---:|---:|---:|
| S1-universe coins | 152 | ≈ 292 | ≈ 1,170 | ≈ 440 |
| Alive at g + 6 min | 142 | ≈ 273 | | |
| Alive at g + 10 min (gate population) | 85 | ≈ 163 | ≈ 650 | ≈ 245 |
| Alive at g + 30 min (gate population) | 47 | ≈ 90 | ≈ 360 | ≈ 135 |
| Ceiling on S1 entries: control 1, one per coin | 143 | ≈ 275 | ≈ 1,100 | ≈ 410 |

- The gate populations clear the §7 minimums: 100 per checkpoint on TRAIN and 50 on VAL.
- The rate at which the flow conditions pass is unknown until B1 exists. The synthetic-B1 debug run cannot measure
  it.
- PLAN prior: 5-25 signals a day, which gives:

  | Split | Expected signals |
  |---|---:|
  | TRAIN | 20-100 |
  | VAL | 8-38 |
  | TEST | 7-33 |
  | CONFIRM | 75-375 |

- With these numbers TEST is expected to be **UNDERPOWERED** against the 60-trade bar. CONFIRM is the powered
  out-of-sample test.

## Amendment 1 (2026-10-09, review findings; before any official TRAIN run, no `prereg.lock` existed)

All changes come from a code review of `common.py` / `s1.py`, not from any outcome. No parameter changed.

1. **Control 1 is time-matched (§9).** Before, control 1 entered at the FIRST eligible checkpoint, which is almost
   always g + 6 min (debug run: 142 of 143 control trades at cp6), while S1 signals spread over cp6-cp30, so the
   "≥ 6 points better than control 1" bar compared different entry ages (g + 6 sits right after the BOOST cliff,
   PLAN §6.7). Control 1 now enters every eligible coin at every checkpoint and is compared at S1's checkpoint mix,
   with a joint coin bootstrap. The bar (≥ +0.06 on VAL and TEST; the TRAIN shortlist rule) is unchanged.
2. **Shared protocol fixes that apply to S1** (`common.py`): criterion 3 needs the 90% CI lower bound > 0 under both
   the coin bootstrap and a 6-hour block bootstrap (PLAN §3.4 "also resample by day blocks"); a verdict with more
   than 10% of trades closed by the data horizon (g + 179 min: S1 entries after g + 89 min with a 90-min hold) is
   INCOMPLETE, never PASS; TEST / CONFIRM / FINAL are ONE look per hypothesis family (S1, S1-gate, S1-control1
   and the fill-sensitivity runs share one `common.one_shot_session`), every VAL / TEST look is logged (the
   sensitivity runs are now trials: the ledger identity includes the fill config), and FINAL consumes the
   census thirds.
