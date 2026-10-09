# Y1 pre-registration: buy post-BOOST only from deployers with a good as-of record

- **Version:** `y1-v1`.
- **Written:** 2026-10-09, before any Y1 run on TRAIN, VAL, TEST, CONFIRM or FINAL data. TRAIN was still being
  backfilled. Every constant and the whole grid (§7) were fixed in this file **before** the debug run on the census
  TRAIN third (§14). That run reports counts only: returns hidden, and no parameter chosen there.
- **Code:** `research/lab2/y1.py`, on the shared foundation `research/lab2/common.py`. Tests:
  `research/lab2/tests/test_y1.py`.
- **Protocol:** PLAN §3 (shared protocol), §3.5 (entry and veto bars), §3.6 (automatic rejections), §6.6
  (reputation leakage rules) and §8 (stop rules), through common.py's `AsOf`, `backtest`, placebo, `describe`,
  `verdict_entry`, `verdict_veto`, trial ledger, shortlists and one-shot sessions. Stage gating and CLI follow
  `m1.py`.
- **Splits:** common.py's (TRAIN 10-01 → 10-05, VAL → 10-06 12:00, TEST → 10-07 19:37:30, CONFIRM 09-16 → 10-01,
  FINAL = census day).
- **Not a duplicate.** G1's SERIAL flag counts a creator's earlier graduates; X1 scores early *holders*. Y1 scores
  the *deployer* by the post-migration outcomes of its earlier graduates.
- **Freeze.** The first official TRAIN run hashes this file into `Y1/prereg.lock`. After that, `y1.py` refuses every
  stage if this file has changed. A change is a new version (`y1-v2`) in `Y1/AMENDMENTS.md`, and its configs are new
  trials.
- **Review amendments (2026-10-09, before the lock and before any TRAIN, VAL, TEST, CONFIRM or FINAL run).** Three
  review findings changed this file and `y1.py`; nothing had run on a non-debug split, and no TRAIN return was seen:
  - **Y1-1** (§5, §7): the primary fill model is now next-bar exits (`FillConfig(exit_delay_bars=1)`), as in Y2-Y5;
    same-bar exits are a stress run. The trial identities changed with the fill model.
  - **Y1-2** (§9, §14): an explicit **fixed path** for the expected underpowered TRAIN, so that CONFIRM, the only split
    that can power Y1, is reachable.
  - **Y1-3** (§14, debug output): the debug run no longer reports trade tags, GOOD-config counts or veto flag counts,
    which are signs of earlier coins' records.

## 1. Hypothesis and mechanism

A deployer runs a playbook, and it runs the same playbook on every coin it launches:

- An **operator** that pays for post-migration support (market-making, volume bots, a steady bid, paid calls) pays
  for it on each of its coins. That support is a marketing budget, so the post-migration path of its previous
  coin predicts the next one. The counterparty is the operator's budget, the same one M1 rides.
- A **rug farm** dumps every coin it launches. Its buyers lose on each coin.
- So coin outcomes should correlate **within a deployer**. If they do, a deployer's as-of record sorts the next
  coin before its post-BOOST path is visible.

**Why the market might leave it on the table.**

- Post-migration buying in the first minutes is mostly bots keyed on flow.
- "Dev history" tools show launch and migration counts, not the 30-minute post-migration path of the last coin.
- A record needs a cross-coin outcome database, built forward in time.

**Why it may fail**, all of which this design measures rather than assumes:

- **Persistence may be absent.** It is tested before any P&L (§8). If it fails, Y1 dies.
- **It may already be priced in.** A good-record operator may pump at migration, so the post-BOOST path mean-reverts.
- **Most creators are new.** Only 12 of 450 usable coins on the census TRAIN third had an earlier usable graduate by
  the same creator in that 12.5-hour window (§14). Y1 trades a small subset and may be underpowered.
- **Costs.** A $20 round trip costs 1.4-5.1% by market cap. PLAN §3.5 asks for ≥ +3% net per trade.
- **Launchpads and shared deployers.** A creator key can stand for many unrelated users. These keys are excluded
  (§2.2).

**The gate variant.** "Avoid bad-record deployers" can only make a losing host lose less. It is therefore tested as a
**veto on a host** (§6, PLAN §3.5 veto bar), never as a standalone entry rule.

## 2. Data and the registry

Only `graduates`, `b2_coins` and `b2_bars` (to g + 180 min) are used, through `common.load` / `common.AsOf`.
CryptoHouse is never queried.

### 2.1 Which coins feed the registry ("history"), by stage

The registry runs forward through the splits. A stage reads outcomes only from splits that are earlier in time and
already open at that stage. CONFIRM's outcomes therefore never reach a TRAIN decision.

| Stage | History splits (outcome records) |
|---|---|
| debug | `final_train` only |
| TRAIN | `train` only (CONFIRM is sealed) |
| VAL | `train`, `val` |
| TEST | `train`, `val`, `test` (VAL already ran) |
| CONFIRM | `confirm` only (nothing earlier exists) |
| FINAL | `train`, `val`, `test`, the three census thirds |

**Structural pool** (who deployed what, never outcomes): every graduate of any quote or Mayhem flag created in
[first history split start, stage split end). Its `creator` and `create_user` are read through `AsOf` at
g + 20 s (legal from creation or g) and used only at τ ≥ that graduate's g.

### 2.2 Deployer key and shared-deployer exclusion

The deployer key is `CreateEvent.creator`. It is NULL when the creation was not scanned (`has_create = 0`). Such
coins are skipped, and NULL is never 0.

A creator is **shared**, and every coin it deployed is skipped, when, as of τ, using graduates with g ≤ τ (the
current coin included):

| Rule | Condition | Why |
|---|---|---|
| `pooled` | the key is in `common.POOLED_ACCOUNTS` or `pooled_accounts.json` | a program account that signs for many people |
| `signs_for_others` | the key is the `create_user` (signer) of a graduate whose `creator` is another key | a launch-service or launchpad wallet |
| `multi_signer` | ≥ 2 distinct `create_user` signers deployed under this key | one fee key, several deployers |
| `factory_volume` | ≥ 24 graduates under this key in the 24 h before τ | a deployment service, not one playbook |

These thresholds are structural, not tuned. On the census TRAIN third, 3 creators sign for others, none has 2
signers, and the busiest key has 8 graduates in 12.5 h (all Mayhem).

### 2.3 Outcome record of one earlier coin (a label, never a feature of that coin)

For an earlier **usable** graduate p of the same creator:

- t_ref(p) = the first decision-grid time (minute boundary + 20 s) at or after g_p + 420 s. This is post-BOOST:
  BOOST's last slice lands by g + 353 s.
- t_end(p) = t_ref(p) + 30 min.
- r(p) = `AsOf(p, t_end).price / AsOf(p, t_ref).price − 1`. This is the mid-price change, with no costs.
- **Resolved at decision time t** only when t_end(p) ≤ t. Then every bar r(p) reads ended before τ = t − 20 s.

## 3. Features at decision time t (τ = t − 20 s)

| Feature | Definition |
|---|---|
| `creator` | `snap["creator"]` (AsOf) |
| status | `unknown` (NULL creator), `shared` (§2.2), `new` (no earlier usable graduate of this creator in history), `pending` (earlier ones exist, none resolved), `eligible` (≥ 1 resolved) |
| `record_mean` S | mean r(p) over the **most recent 3** resolved earlier graduates (by g), excluding the traded mint |
| `n_resolved` | resolved earlier graduates of the creator |

"Earlier" means g_p < g of the traded coin. Its own outcome can never score its own creator.

## 4. Entry rules (one entry per coin; decisions on common.py's grid)

The entry window is age ∈ [420 s, 60 min]. The 420 s start is the AGENT window end, so BOOST is over.

- **GOOD(θ)** (hypothesis `Y1`): enter at the first decision in the window where status = eligible and S ≥ θ.
  - Skip the coin when status is unknown, shared or new, or when every earlier graduate has resolved and S < θ.
  - Wait while earlier graduates are still pending.
- **HOST** (hypothesis `Y1-host`): enter at the first decision in the window where status = eligible, whatever the
  record. Each trade is tagged `bad` when S < 0 at entry, else `good`.

## 5. Exits (mechanical, fixed)

| Exit set | Rule |
|---|---|
| `T30` | time exit 30 min after the entry fill (the record's horizon), catastrophe stop −50% |
| `T60` | time exit 60 min after the entry fill, catastrophe stop −50% |

- Both also carry `exit_by_age_s` = g + 178 min. It never binds: the last entry is at age 60 min, plus a 60-minute
  hold.
- No trade can end on the data horizon. Criterion 10 (≤ 10% censored) is still checked.
- Fills use `common.FillConfig(exit_delay_bars=1)` (`y1.FILL`): $20, latency 30 s, entry at max(open, high), stops
  checked from the entry bar, and **next-bar exits**: a stop or time exit triggered in bar j fills at min(open, low) of
  bar j + 1. Costs: PumpSwap tier by date + 10 bps Ultra + 20 bps buffer, network fees, pricing on X = x + v.
- The harness's same-bar exits (`FillConfig()`, the stop filling inside its trigger bar) are only a stress run (§7).

## 6. The bad-record veto (the gate variant)

- **Host:** HOST (§4) with the shortlisted exit.
- **Flag:** `bad` = record S < 0 at the host's entry. This is the complement of GOOD(0), not a new threshold.
- **Verdict:** `common.verdict_veto` (PLAN §3.5 veto bar).
  1. Flagged mean ≤ unflagged mean − 10 points, with the coin-bootstrap CI excluding 0 (on VAL).
  2. Out of sample, removing the flagged trades raises net profit (TEST).
  3. It removes < 25% of the host's winning profit.
- UNDERPOWERED with < 30 flagged or < 30 unflagged trades.
- On CONFIRM (never searched), all three criteria are computed on CONFIRM itself.
- The veto is reported next to the entry verdict and never changes it.

## 7. The grid: every configuration is a counted trial (9 in all, limit 12)

| Hypothesis | Configs | Count |
|---|---|---:|
| `Y1` GOOD | θ ∈ {0, +0.10} × exit ∈ {`T30`, `T60`} | 4 |
| `Y1-host` HOST | exit ∈ {`T30`, `T60`} | 2 |
| `Y1-veto` | the §6 veto on each TRAIN host (descriptive on TRAIN) | 2 |
| `Y1-persist` | the persistence gate (§8) | 1 |
| **Total** | | **9** |

- θ = 0 asks only for a non-negative record. θ = +0.10 asks for a record that would have beaten the round trip by a
  margin.
- Each params dict carries every constant in §2-§6, the fill model and the version. Any change is a new trial.
- TEST / CONFIRM / FINAL re-run shortlisted configs under the same identities, adding no new trials.

**Stress runs** (same call, never used to select), all on the next-bar model unless named: costs × 1.5; rent $0.22;
`entry_bar_exits=False`; same-bar exits (`FillConfig()`, `exit_delay_bars=0`).

## 8. Persistence gate (stop rule; TRAIN, before any P&L)

This asks PLAN W1 stage 1's question ("does skill persist?") of deployers.

- **Observations:** every usable TRAIN coin that becomes eligible inside the entry window. It is observed at its
  first eligible decision t_e.
- **Score:** S(t_e).
- **Label:** its own mid-price change from t_e to t_e + 30 min, read through AsOf at t_e + 30 min.
- **Statistic:** Spearman ρ(S, label), with a 90% CI from a bootstrap that resamples deployer clusters (§10,
  2,000 draws).

| Result | Condition | Consequence |
|---|---|---|
| **UNDERPOWERED** | < 60 observations or < 20 deployer clusters | Y1 halts; the grid is not run |
| **KILL** | ρ ≤ 0, or the cluster 90% CI lower bound ≤ 0 | **Y1 is dead.** The grid is never run, and every later stage refuses |
| **PASS** | otherwise | continue |

**Reported, never decisive:**

- the mean label by record sign;
- ρ without warm-up observations (those within 24 h of the first history graduation);
- the number of distinct creators carrying the observations.

## 9. Procedure by stage (`python research/lab2/y1.py --stage …`)

### Every stage

A stage refuses to run unless:

- `Y1/PREREG.md` exists, and matches `prereg.lock` once locked;
- stop rule 1 holds: `common.validation_gates` passes for the split;
- coverage is complete: every chain hour is scanned, ≤ 5% of tradeable coins miss B2, no mid-run hour, and the
  SOL/USD series covers the split. FINAL is exempt from the completeness part;
- guarded splits have the judge's flag. `y1.py` never sets it.

### TRAIN

1. Run the persistence gate (§8).
2. On PASS, run the 6 configs, each with the matched controls (§10) and the stress runs. Log the 2 veto
   evaluations.
3. **A GOOD config qualifies** when all of these hold:

   | Requirement | Bar |
   |---|---|
   | Sample | ≥ 30 trades from ≥ 10 deployer clusters |
   | Mean net | > 0 |
   | Mean without the top 2 trades | > 0 |
   | Matched control `mean_diff` (eligible-coin placebo) | > 0 |

4. **Choice:** the qualifying config with the highest deployer-cluster bootstrap 90% CI lower bound. Ties go to the
   higher mean, then θ = 0.10, then `T30`.
5. **Shortlists**, written before VAL:
   - `Y1` = [the chosen GOOD config];
   - `Y1-host` = [HOST with the same exit], for the veto.
6. If nothing qualifies: **NO_CONFIG** when some GOOD config met the sample bar (powered evidence against: Y1
   stops). Otherwise no GOOD config is powered, and Y1 takes the **fixed path** (decision `SHORTLISTED_FIXED`):
   - The shortlists are `Y1` = [GOOD(θ = 0) / `T30`] and `Y1-host` = [HOST / `T30`]. They are **fixed a priori in
     this file, never chosen from TRAIN returns**: θ = 0 is the complement of the veto flag (§6), and `T30` is the
     record's own horizon (§2.3). Both are already TRAIN trials, so the fixed path adds no trial.
   - VAL and TEST run once each, in the usual order, and are **reported only**: a FAIL_VAL, an UNDERPOWERED_VAL or a
     TEST mean ≤ 0 never stops the fixed path. A TEST `REJECTED` (a structural §3.6 rejection) still does.
   - **CONFIRM is the judged look** (the only split that can power Y1, §14), with the same entry verdict. FINAL as
     usual. The overall EDGE rule is unchanged: persistence PASS, CONFIRM PASS, FINAL mean > 0.
   - Why this is not a search: the persistence gate (§8) is the only TRAIN outcome the fixed path reads, and it is a
     pre-registered stop rule. Without this path the expected TRAIN outcome (§14) would end Y1 with no verdict,
     because every later stage needs a TRAIN shortlist.
   - An UNDERPOWERED persistence gate (< 60 observations or < 20 clusters) still halts Y1 before the grid: then Y1
     ends **UNDERPOWERED** with no verdict.
7. A complete TRAIN's decision is final. A re-run needs `--rerun-reason` naming a data correction.
8. `--allow-partial` runs a PROVISIONAL TRAIN. It writes `train_prelim.*`, and never a lock or a shortlist.

### VAL

Run both shortlisted configs once. The decision uses the candidate:

| Decision | Condition | Consequence |
|---|---|---|
| UNDERPOWERED_VAL | n < 5 | stop |
| FAIL_VAL | mean ≤ 0, or mean without the top 2 ≤ 0 | stop |
| SELECTED_UNDERPOWERED | 5 ≤ n < 15 | proceed |
| SELECTED | n ≥ 15 | proceed |

The VAL host trades and flags are saved for the veto. On the fixed path (TRAIN step 6) the VAL decision is reported
and never stops Y1.

### TEST (one `common.one_shot_session` for the Y1 family)

- Run the candidate as `Y1` and the host as `Y1-host`.
- **Entry verdict:** `common.verdict_entry(test, val=VAL candidate, min_mean=0.03)`, which is PLAN §3.5 items 1-8
  plus §3.6. Item 9 is judged after FINAL. Plus these extras:

  | ID | Criterion |
  |---|---|
  | Y1.1 power | ≥ 60 trades from ≥ 10 deployer clusters |
  | Y1.2 | deployer-cluster bootstrap 90% CI lower bound > 0 |
  | Y1.3 | mean > 0 without the largest deployer cluster |

  They combine as in M1: REJECTED > UNDERPOWERED > FAIL > INCOMPLETE > PASS.
- **Veto verdict** (§6): VAL host as in-sample, TEST host as out of sample.
- UNDERPOWERED is expected on a 1.3-day TEST.

### CONFIRM

- **Precondition:** TEST not REJECTED, and either TEST mean > 0 or TEST n < 5. On the fixed path only the first
  part applies (TEST is reported only).
- Run the same pair once, with the same entry verdict.
- Veto on CONFIRM itself.
- This is the powered test.

### FINAL

- It runs only after TEST.
- Run the candidate and the host once on all three census thirds, as one session.
- **Criterion 9 (mean > 0) is judged on `final_val` + `final_test` only.** `final_train` was the debug third, and
  is reported apart.
- **Overall EDGE** requires all of: persistence PASS, VAL selected, TEST not failed, CONFIRM PASS, and FINAL mean > 0.
  On the fixed path: persistence PASS, TEST not REJECTED, CONFIRM PASS and FINAL mean > 0 (VAL and TEST reported).

## 10. Controls

- **Matched control (judged):** `common.backtest`'s placebo.
  - 20 draws per signal, at a decision age within ±120 s, and post-BOOST (age ≥ 420 s).
  - **Stratum = eligible**: draws come only from coins whose creator has a resolved earlier usable graduate at the
    draw's own time.
  - This isolates the **record** from the "repeat deployer / operator coin" effect.
  - With few eligible coins, fewer than 20 draws per signal may succeed in 200 tries. That count is reported.
- **Unmatched control (reported):** any usable coin, post-BOOST, same age.
- **HOST** is itself the natural comparison for GOOD.

## 11. Metric, statistics and clusters

**Metric and statistics:**

- The unit is `ret_net` per $20 trade.
- Statistics come from `common.describe`: coin and 6-hour block bootstrap CIs, mean without the top 2, halves, top-coin
  share, censored share, and a deflated Sharpe ratio over every ledger trial.
- Also reported: the $100 / 5-slot portfolio.

**Deployer clusters** are the connected components of coins that share a `creator` or an upper-cased `symbol`
(ticker clones). Fields are read through `AsOf` at g + 20 s.

- Trades of one deployer are correlated by hypothesis, so CIs also resample clusters.
- Over-merging only widens them.
- Early-buyer wallet links are **not** used: a few migration bots buy nearly every pool, and linking through them
  would merge the universe.

## 12. Leakage rules (PLAN §6.6), enforced in code and tested

1. **Strictly past:** a record counts only when t_end(p) ≤ t, and only for g_p < g. Never the traded mint.
2. **No marking to a later price:** a record is a closed 30-minute window.
3. **Forward in time:** the registry is built from history splits that are already open (§2.1), never from a later
   split.
4. **Leakage test** (`tests/test_y1.py`): garbage after T, in every coin, leaves every registry answer and every
   decision at τ ≤ T unchanged.
5. **Declarations** to `auto_rejections`:

   ```
   uses_wallet_reputation = True
   reputation_excludes_traded_coin = True
   uses_organic_flow = False
   uses_truncated_windows = False
   uses_current_state_fields = False
   ```

## 13. Kill criteria and deviations

**Kill criteria:**

- Stop rule 1 (data first).
- Stop rule 5 analog: the persistence gate (§8).
- Stop rule 7: report FAIL_VAL.
- Stop rule 8: every config counts (§7).

**Deviations:**

| Area | Deviation |
|---|---|
| Record | Only **graduates** are seen. A creator's failed curves are invisible, so the "record" is the post-migration path of its earlier graduates |
| Usable priors only | Earlier coins must be usable (SOL-quoted, not Mayhem, complete B2). That is a data-collection filter on other coins; the contract keeps the missing share ≤ 5% |
| Deployer identity | By `creator` key, not by funder cluster (PLAN G06 wants funder clusters, which we lack) |
| Fills | Minute-bar "worst" fills, not replayed fills (X1 engine) |

## 14. Debug findings and expected sample (census TRAIN third, counts only)

**The run.** `python research/lab2/y1.py --debug` writes `Y1/debug.md` and `Y1/debug.json`.

- 450 usable coins, created over 12.5 h (0.52 days).
- History is that same third only (§2.1): 429 records from 417 creators; the structural pool has 708 graduates.
- The persistence statistic, returns, exit reasons and the veto means are hidden. Since review Y1-3 the debug run
  also hides trade tags, GOOD-config counts and veto flag counts (see the disclosure below).
- Its trials go to a scratch ledger, never to `trials.json`.
- **Nothing in §2-§10 changed after this run.**

**Counts:**

| Measure | Census TRAIN third (0.52 d) | Per day |
|---|---:|---:|
| Status at the first post-BOOST decision | new 417, unknown (creation not scanned) 21, pending 5, eligible 7, shared 0 | |
| Coins eligible inside the entry window | 12, from 11 creators, 10 deployer clusters | 23 |
| Median age at eligibility | 7.9 min (5 of 12 waited for a pending record) | |
| Resolved records at eligibility | one: 11 coins; two: 1 coin | |
| Persistence-gate observations | 12 (all within 24 h of the first history graduation: warm-up) | 23 |
| HOST entries (each exit set) | 12 (tags: 3 `good`, 9 `bad`; disclosed, see below) | 23 |
| GOOD(θ = 0) entries | 3 (disclosed, see below) | 5.8 |
| GOOD(θ = 0.10) entries | 1 (disclosed, see below) | 1.9 |
| Matched-placebo draws per signal | 1-3 (of 20 asked: the eligible pool is tiny) | |
| Trades ending on the data horizon | 0 | |

**Disclosure (review Y1-3).** The first debug output also reported the HOST trade tags, the GOOD-config counts and
the veto flagged / unflagged counts (marked "disclosed" above). Each is the sign of an earlier coin's record: the
30-minute post-BOOST mid change of a census TRAIN-third coin, which is return information. They were seen after §2-§10
were fixed, nothing was chosen from them, and the census TRAIN third is never judged (FINAL criterion 9 uses
`final_val` and `final_test` only). It does feed FINAL's history as records, so this is stated here rather than
hidden. The debug output no longer reports them: on the debug split Y1 reports status and eligibility counts only
(HOST entries are eligibility counts, since HOST enters every eligible coin).

**What these counts imply, before any TRAIN data.** The debug history covers only 12.5 hours. On TRAIN it grows to
4 days, so deployers that launched on earlier days also become eligible. The rate per day should therefore be **at
least** 23. How much higher it gets is unknown, and is not estimated from sealed splits.

If TRAIN looks like this third:

- **Persistence gate:** about 90 observations. It needs ≥ 60 observations from ≥ 20 clusters, so it is reachable.
- **GOOD(0):** about a quarter of eligible coins on this third (a disclosed count, see above), so about 23 TRAIN
  trades. That is below the 30-trade bar, so **no GOOD config is powered on TRAIN is the most likely outcome**. With
  the persistence gate passed, Y1 then takes the **fixed path** (§9 TRAIN step 6): GOOD(0) / `T30`, fixed a priori,
  to one judged CONFIRM look.
- **VAL and TEST:** about 9 and 8 GOOD(0) trades. Both are underpowered; on the fixed path they are reported only.
- **CONFIRM:** at 15 days, about 85 GOOD(0) trades. It is the only split that could power Y1, and the fixed path is
  what makes it reachable. If the persistence gate is UNDERPOWERED on TRAIN instead, Y1 ends UNDERPOWERED with no
  verdict.
- **The veto:** underpowered on VAL. It needs ≥ 30 flagged and ≥ 30 unflagged VAL host trades, and VAL should give
  about 35 host trades in all.
- **The matched control:** few draws per signal, so it is noisy. HOST, the same entry on every eligible coin, is
  the cleaner comparison, and it is always reported next to GOOD.
