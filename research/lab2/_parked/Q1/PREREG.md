# Q1 pre-registration: veto R0 entries whose early pool buyers are "dump-cluster" wallets (version `q1-v1`)

- **Written:** 2026-10-09, before any Q1 run on TRAIN, VAL, TEST, CONFIRM or FINAL data. Every constant, the grid
  (§7), the kill gate (§6), the controls (§8) and the decision rules (§9) were fixed in this file **before** the debug
  run on the census TRAIN third (§14). That run reports counts only: returns, labels and gate statistics hidden, no
  parameter chosen there.
- **Code:** `research/lab2/q1.py`, on the shared foundation `research/lab2/common.py` (every feature through
  `common.AsOf`). Tests: `research/lab2/tests/test_q1.py`.
- **Spec it implements:** idea-mill queue item **q1 · DC1 · Dump-cluster early-wallet veto**
  (`scratchpad/ideas/mill/QUEUE.md` §1 and `queue.json`, id `q1`), under the queue's shared rules 1-8, PLAN §3
  (protocol), §3.5 (veto bar), §3.6 (automatic rejections), §6.6 (leakage rules for cross-coin outcome registries) and
  §8 (stop rules). Status: VARIANT-OF-x1 / G10 (PE-14).
- **Data readiness:** **READY.** `graduates`, `b2_coins` (`w120_top10`, `w300_top10`, `agent_wallet`,
  `agent_known_at`), `b2_bars`. No B1 raw trades, no B3, no CryptoHouse queries. The B1 arm (OA8 arm B) is **not**
  part of this version (§13).
- **Names.** Ledger hypotheses: `Q1` (the 9 veto configs), `Q1.R0` (the fixed host), `Q1-gate` (the kill gate). One
  family (`Q1`): TEST / CONFIRM / FINAL are one look each for all three.
- **Freeze.** The first official TRAIN run hashes this file into `Q1/prereg.lock`. After that `q1.py` refuses every
  stage if this file has changed. Any change is a new version (`q1-v2`) in `Q1/AMENDMENTS.md`, and its configs are new
  trials.

## 1. Hypothesis and mechanism

**Claim (public, merged raw ideas OC-OA1, TD-T9, RS-R16 method, OC-OA8 arm B later).** MadeOnSol (14-day out of
sample): tokens whose top-20 early buyers include ≥ 3 known dump-cluster wallets "dumped" (peaked < 15 min after
deploy) 93 % of the time against a 71 % base; for ≥ 1 such wallet 85 % (n = 2,683). GMGN tags "Scammer" wallets and
publishes a "rug probability"; Cupsey estimates ~80 % of runners are coordinated groups reusing wallets.

**Mechanism.** Extraction operators reuse the same wallets as early pool buyers across coins. Their presence marks
the same playbook (buy the fresh pool early, dump into the followers), so an entry into such a coin makes us their
exit liquidity. A veto can only make a losing host lose less (PLAN §0); Q1 asks whether it does so by **more** than a
random veto and by more than "a busy wallet" does.

**Who loses** (the named loser the veto lets us avoid being): late buyers of a coin whose early buyers have a record
of rugging, who buy the dump.

**Why it may fail** (the honest prior: plausibility 4 of 5 for the outside evidence, but the evidence is about
*graduation-era* dumps, and Q1 trades 30-115 min after graduation):

- **Wallet reuse is everywhere** (QUEUE structure check, TRAIN, no outcomes): only 16 % of usable coins have no
  `w300_top10` wallet that sat in ≥ 3 earlier coins' top-10 lists; the busiest top-10 wallets sit on 830-1,681 of
  ~8.7k pools (`ARu4n5…` the known pooled account, `BwWK17…` the suspect PDA). "A reused wallet" alone carries no
  information. The rug **label**, the **ubiquity filter** and the **label-permuted placebo** (§8) carry the test.
- **The dump may already have happened.** By R0's entry (30-115 min) a dump-cluster coin may have finished dumping;
  what is left could be no worse than any other survivor.
- **The public numbers are about the first 15 minutes** (peak < 15 min after deploy); Q1's label (§3) is the first
  post-BOOST half hour, and Q1 acts 30-115 min after graduation.
- **Only the stored top-10 is visible**: a dump wallet that bought less than the 10th-largest early buyer is
  invisible (a lower bound on k).

### 1.1 Not a duplicate

| Hypothesis | What it uses | Q1 differs by |
|---|---|---|
| X1 (smart-money follow) | the **follower's return** of early holders' earlier picks, an entry | Q1 uses a **rug** label of early buyers' earlier coins, as a **veto** on R0 |
| G10 (PE-14) | P3, waits on `b3_positions` (0 coins) | Q1 runs now on the `w120_top10` / `w300_top10` lists |
| G1 | `repeat_migbuyer_share_2m` counts how **often** a wallet appears | Q1 conditions on how those wallets' earlier coins **ended**, and removes busy wallets (ubiquity) |
| Z4 (theme exhaustion) | outcomes of earlier coins sharing a **name token** | Q1 links coins through shared **early buyers** |
| q12 / GH-12 | the positive mirror (copy-trading) | not built here |

## 2. Data and history

### 2.1 Outcome history (RUG labels), by stage

The registry runs forward through the splits; a stage reads outcomes only from splits earlier in time and already
open at that stage (as X1 / Z4):

| Stage | History splits (RUG labels) |
|---|---|
| debug | `final_train` only |
| TRAIN | `train` only (CONFIRM is sealed) |
| VAL | `train`, `val` |
| TEST | `train`, `val`, `test` |
| CONFIRM | `confirm` only |
| FINAL | `train`, `val`, `test`, the three census thirds |

A history split other than the stage's own must pass the same coverage check (§9) or the stage refuses.

### 2.2 Structural pool (early-buyer lists, never outcomes)

Every graduate (any quote, Mayhem included) that has a `b2_coins` row and was created in [first history split start,
stage split end) (Z4's bounds). Its two lists are read through `AsOf` at τ = g + 420 s (§3) and are used only for the
ubiquity filter (§3), never for labels.

## 3. Features and labels (features through `common.AsOf`; labels are outcomes, never features)

| Name | Definition |
|---|---|
| **List** A(q, W), W ∈ {w300, w120} | q's `W_top10` read through `AsOf(q, g_q + 440)` (τ = g_q + 420 s: the list is legal from g + 300 s / g + 120 s and AGENT presence is decided), via `AsOf.top_buyers(W, exclude_agent=True)`; then minus `POOLED_ACCOUNTS ∪ SUSPECT_PDA_ACCOUNTS` (pooled accounts are already dropped at load), minus entries with buy SOL ≤ 0 or NULL, duplicates removed. NULL list → NULL (never empty) |
| **List time** | g_q + 420 s. A list exists at τ only when g_q + 420 ≤ τ |
| **UBIQUITOUS(τ, W)** | Wallets in A(q, W) of ≥ 5 % (and ≥ 2) of the structural graduates q with g_q ∈ (τ − 24 h, τ − 420 s] and a non-NULL list. The coin being decided is left out of both the count and the denominator |
| **L(c, τ, W)** | A(c, W) read at the decision through `AsOf` (same rule as above), minus UBIQUITOUS(τ, W) |
| **t_ref(p)** | The first decision-grid time (minute boundary + 20 s) at or after g_p + 420 s (post-BOOST) |
| **RUG(p)** | 1 if `AsOf(p, t_lab).price ≤ 0.20 × AsOf(p, t_ref).price`, else 0, with **t_lab(p) = t_ref(p) + 30 min + 20 s** (T9's "−80 % within 30 min after BOOST"). Defined for **usable** history coins (common's universe) whose label window lies inside B2 |
| **Registry entry** | (w, p) for every labelled history coin p and every w ∈ A(p, W), per list variant W |
| **Usable at decision t** | the entry's coin p has t_lab(p) ≤ t (every bar read ended at or before τ), g_p < g_c, and p ≠ the traded mint (PLAN §6.6 rules 1-2) |
| `n_w`, `d_w` | the wallet's usable entries at t, and their mean RUG |
| **DUMP(w)** | n_w ≥ N and d_w ≥ D |
| **k(c, τ, W)** | the number of DUMP wallets in L(c, τ, W). NULL list → k NULL → the veto does not fire (a NULL never passes; NULL is reported) |
| **G1 class** | `g1.classify(g1.g1_features(AsOf(c, g + 140 s)))`: OPERATOR / FACTORY / COMPLETED / UNRESOLVED / ORGANIC (report only) |

The same list variant W is used for the registry entries, the ubiquity filter and L(c).

## 4. Host and veto rule

- **Host `Q1.R0`** = `g1.host_r0` with `g1.R0_PARAMS` (pinned: params hash `27a79bc60126`; a changed g1 host makes
  every Q1 stage refuse): at a seeded random age in [30, 115] min (sha256 of `0:<mint>`), enter if `alive`
  (≥ $1.5k volume over 15 min, market cap ≥ $6k), else never; −50 % catastrophe stop, 60-minute time exit. Q1 adds the
  shared deadline `exit_by_age_s` = g + 178 min (it never binds for R0: the last time exit fills by ≈ g + 179 min).
- **Veto Q1(W, N, D, K):** flag an R0 host trade when k(c, τ, W) ≥ K at the trade's decision time (τ = t_dec − 20 s).
  R0 decides at ages ≥ 30 min, always after g + 420 s, so the lists are always legal.
- **Not run in this version:** the veto on x6 or M1 (only if they pass their own gates; that is a later amendment with
  its own trials).

## 5. Exits and fills (fixed)

The host's own exits (−50 % stop, 60 min, deadline g + 178 min). Fills `common.FillConfig(exit_delay_bars=1)`: $20,
latency 30 s, entry at max(open, high) of the landing bar, exits at min(open, low), stops checked from the entry bar,
every triggered exit fills in the next bar at its adverse side; PumpSwap fee tier by date + 10 bps Ultra + 20 bps
buffer, network fees, pricing on X = x + v. Stress (same call, never used to select): costs × 1.5.

## 6. Kill gate (stop rule; TRAIN, before any P&L)

- **Observations:** every TRAIN coin where R0 enters (its R0 decision time, alive), with a non-NULL `w300` list.
- **Score:** k at the gate registry **W = w300, N = 3, D = 0.6** (the most inclusive DUMP set of the grid: every other
  w300 (N, D) set is a subset of it, so it has the most power). Buckets {0, 1-2, ≥ 3}.
- **Label:** the coin's own 60-minute forward mid change, `AsOf(c, t_dec + 60 min).price / AsOf(c, t_dec).price − 1`
  (an outcome, read 60 minutes later; never a feature).
- **Decision:** Δ = mean(k ≥ 1) − mean(k = 0).
  - **UNDERPOWERED_GATE** if < 30 coins with k ≥ 1 or < 30 with k = 0: Q1 halts, the grid is not run.
  - **PASS** if Δ ≤ −0.05 **and** the coin-bootstrap 90 % CI upper bound of Δ < 0 (one observation per coin, so the
    coin bootstrap is the cluster bootstrap).
  - **KILL** otherwise: Q1 is dead; the grid is never run and every later stage refuses.
- Reported, never decisive: the bucket means {0, 1-2, ≥ 3}, Δ without the warm-up day, Δ by G1 class.
- Logged as one trial (`Q1-gate`).

## 7. The grid: every configuration is a counted trial (11 ledger configs, limit 12)

| Hypothesis | Configs | Count |
|---|---|---:|
| `Q1` on `w300` | N ∈ {3, 5} × D ∈ {0.6, 0.8} × K ∈ {1, 3} | 8 |
| `Q1` on `w120` | the TRAIN-best (N, D, K) (§9) | 1 |
| `Q1.R0` | the fixed host | 1 |
| `Q1-gate` | the kill gate (§6) | 1 |
| **Total** | | **11** |

- The queue's count (9 veto configs) is unchanged; the host and the gate are logged as their own trials because they
  are looks at the data. Nothing else is searched: the ubiquity share, the RUG threshold, the label window and the
  exits are fixed.
- **N:** 3 = the claim's own "≥ 3 earlier appearances"; 5 = a stricter record. **D:** 0.6 / 0.8 = a majority / a
  large majority of earlier coins rugged. **K:** 1 / 3 = the claim's k ≥ 1 and k ≥ 3.
- Each params dict carries every constant of §3-§5 and §8, the host params hash, the fill model and the version. Any
  change is a new trial.

## 8. Controls (placebos)

1. **Random veto at the same rate** on the same host trades: 200 draws flag the same number of trades at random; the
   share of draws whose flagged-minus-unflagged gap is ≤ the real gap is reported (a one-sided permutation p). It is
   the same comparison as `verdict_veto` criterion 1's CI, so it is reported, not separately decisive.
2. **Label-permuted registry** (decisive on TRAIN and CONFIRM): the same wallets, entries, appearance counts and
   ubiquity filter, with the RUG labels permuted across the labelled history coins **inside each 6-hour block of
   g_p** (20 permutations, seeds 0-19). It separates "rug history" from "busy wallet". The real registry must beat the
   permuted ones by ≥ 5 points on the flagged-minus-unflagged gap: gap(real) ≤ mean gap(permuted) − 0.05 (a
   permutation where a side is empty is skipped; none valid → the criterion fails).

## 9. Procedure by stage (`python research/lab2/q1.py --stage …`)

### Every stage

A stage refuses to run unless:

- `Q1/PREREG.md` exists, and matches `prereg.lock` once locked;
- the R0 host is the pinned one (§4);
- stop rule 1 holds: `common.validation_gates` passes for the split;
- coverage is complete: every chain hour scanned (curve and B2), ≤ 5 % of tradeable coins missing B2, no mid-run hour,
  SOL/USD covers the split (FINAL is exempt from the completeness part); history splits too (§2.1);
- guarded splits have the judge's flag (`LAB2_ALLOW_TEST`, `LAB2_ALLOW_CONFIRM`, `LAB2_ALLOW_FINAL`); `q1.py` never
  sets it.
- **Global blocker (queue shared rule 8):** the lab2 bar-0 price fix (task #26) must land before any TRAIN / VAL run.
  `q1.py` cannot detect it; the operator checks it. Q1 itself reads no bar-0 price (labels start ≥ g + 7 min, R0
  decides ≥ g + 30 min), but the host's fills share the engine.

### TRAIN (all searching)

1. Kill gate (§6). Anything but PASS stops TRAIN (decision `KILLED_GATE` / `UNDERPOWERED_GATE`; the host is not run).
2. Run the host `Q1.R0` once (no matched placebo: a veto's control is §8), with the costs × 1.5 stress run.
3. Evaluate the 8 w300 configs on the host trades. A config **qualifies** when all hold:

   | Requirement | Bar |
   |---|---|
   | Sample | ≥ 30 flagged and ≥ 30 unflagged trades |
   | `verdict_veto` criterion 1 | flagged mean ≤ unflagged mean − 10 points, coin-bootstrap 95 % CI upper bound < 0 |
   | `verdict_veto` criterion 3 | removes < 25 % of the host's winning profit |
   | Label-permuted placebo (§8.2) | gap(real) ≤ mean gap(permuted) − 0.05 |

4. **TRAIN-best w300 config:** the qualifying config with the lowest 95 % CI upper bound of the gap; if none
   qualifies, the powered config (≥ 30 / ≥ 30) with the lowest CI upper bound; if none is powered, (N 3, D 0.6, K 1)
   (the most inclusive). Ties → higher N → higher D → higher K.
5. Evaluate **w120 at the TRAIN-best (N, D, K)** with the same bars (the 9th config).
6. **Shortlist** (≤ 2, written with `common.write_shortlist` before VAL, frozen at the first VAL run):
   `Q1` = [the TRAIN-best w300 config if it qualifies] + [the w120 config if it qualifies], in that order;
   `Q1.R0` = [the host].
7. **TRAIN decision:** SHORTLISTED if the shortlist is non-empty; else NO_CONFIG if any of the 9 was powered, else
   UNDERPOWERED_TRAIN. A complete TRAIN's decision is final (a re-run needs `--rerun-reason` naming a data correction;
   the old result is archived). `--allow-partial` runs a PROVISIONAL TRAIN that never writes a lock or a shortlist.

### VAL (shortlisted configs only, once)

Run the host once; evaluate each shortlisted config (in sample, VAL only):

| Decision | Condition |
|---|---|
| UNDERPOWERED_VAL | < 5 flagged trades |
| FAIL_VAL | flagged mean ≥ unflagged mean, or (≥ 30 / ≥ 30 and criterion 1 fails) |
| SELECTED_UNDERPOWERED | < 30 flagged or unflagged, flagged mean < unflagged mean |
| SELECTED | ≥ 30 / ≥ 30 and criterion 1 holds |

The **candidate** is the first shortlisted config (w300 before w120) whose decision is SELECTED or
SELECTED_UNDERPOWERED. No candidate → Q1 stops (stop rule 7 input).

### TEST (one `common.one_shot_session` for the Q1 family; the candidate only)

- `common.verdict_veto(VAL host, VAL flags, oos_host = TEST host, oos_flagged = TEST flags)` (PLAN §3.5: criteria 1
  and 3 on VAL, criterion 2 out of sample on TEST; UNDERPOWERED below 30 / 30 on VAL).
- **Q1.T (sign out of sample):** with ≥ 5 flagged TEST trades, the TEST flagged mean must be < the TEST unflagged mean.
  A reversed sign makes the TEST decision FAIL (criterion 2 alone is weak on a losing host: removing any losing
  subset raises net profit).
- Reported: the TEST label-permuted gap, the random-veto p, by G1 class, costs × 1.5.
- UNDERPOWERED is expected on a 1.3-day TEST.

### CONFIRM (09-16 → 10-01; one run, never searched)

- Runs only when the TEST decision is not FAIL.
- `verdict_veto` with all three criteria on CONFIRM itself, **and** the label-permuted placebo (§8.2) on CONFIRM.
  PASS needs both; UNDERPOWERED below 30 / 30.
- CONFIRM (15 days, ≈ 2,700 host trades) is the only split that can power the veto.

### FINAL (the census day; after TEST)

The candidate once, as one session. Criterion 9: flagged mean < unflagged mean on `final_val` + `final_test`;
`final_train` was the debug third and is reported apart.

### Overall Q1 verdict

**VETO** only with: gate PASS, TRAIN SHORTLISTED, a VAL candidate, TEST not FAIL, CONFIRM PASS, FINAL flagged mean <
unflagged mean. Otherwise KILLED (gate), UNDERPOWERED (gate, TRAIN, VAL or CONFIRM) or NO VETO.

## 10. Metric, statistics and reporting

- Unit: `ret_net` per $20 R0 trade, one entry per coin. Gap = flagged mean − unflagged mean; coin-bootstrap CIs
  (`verdict_veto`, 4,000 draws); winning profit removed; net P&L host vs vetoed host ($).
- **Every result by G1 class** (at g + 140 s), and the gap on the **G1-ORGANIC** trades with its 95 % CI (the
  incremental value beyond G1). Reported, never decisive.
- **Warm-up (PLAN §6.6 rule 8):** decisions within 24 h of the first history graduation are flagged; every gap is
  also reported without them.
- Also reported: the gap on the costs × 1.5 host trades; NULL-list trades; ubiquity-removed wallets per trade; k
  distribution; the random-veto p (§8.1); the permuted-gap distribution (§8.2).

## 11. Leakage rules (PLAN §6.6 / AO-6), enforced in code and tested

1. **Strictly past and resolved:** an entry counts at decision t only when t_lab(p) ≤ t and g_p < g_c; never the
   traded mint.
2. **No marking to a later price:** a label is a closed 30-minute window read through `AsOf`.
3. **Forward in time:** history splits only (§2.1); structural lists count only when g_q + 420 s ≤ τ.
4. **Leakage test** (`tests/test_q1.py`): garbage after T in every coin's bars, and rewritten early-buyer lists of
   graduates whose lists are not yet known at T, leave every L(c), ubiquity set, k and veto flag at τ ≤ T unchanged
   (synthetic markets; real census-third coins when the FLOW tables are present).
5. **Declarations** to `auto_rejections`:

   ```
   uses_wallet_reputation = True
   reputation_excludes_traded_coin = True
   uses_organic_flow = False
   uses_truncated_windows = False
   uses_current_state_fields = False
   ```

## 12. Kill criteria and deviations

**Kill criteria:** stop rule 1 (data first); the kill gate (§6); stop rule 7 (FAIL_VAL reported); stop rule 8 (every
config counts, §7).

| Area | Deviation from the claim |
|---|---|
| Early buyers | B2's top-10 **pool** buyers of [g, g + 300 s) (or + 120 s), not the top-20 curve buyers |
| "Dump" label | −80 % in the first post-BOOST half hour (T9), not "peaked < 15 min after deploy" |
| Dump wallets | learned from our own resolved history (≥ 3 / ≥ 5 appearances), not a vendor's list |
| Scope | R0 decides 30-115 min after graduation; the claim is about the first minutes |
| Fills | minute-bar worst fills with next-bar exits, not replayed fills |
| Ubiquity | 5 % of the trailing 24 h of graduates with a known list (and ≥ 2 lists), the coin itself left out |

## 13. Not in this version

- **B1 arm (OA8 arm B):** "≥ 3 pro early buyers (first-20 curve buyer on ≥ 3 earlier graduates) still hold ≥ 50 % of
  their curve tokens at τ" needs B1 wallet trades (`b1_trades.parquet` does not exist yet). It is a later amendment
  (`q1-v2`) with its own trials, which must refuse its TRAIN until B1 covers its minimum, as `s1.py` / `d1.py` do.
- The veto on x6 / M1 hosts (only if they pass their own gates).
- `run_all.sh` discovers `g1 m1 s1 d1 x* y* z*` only; `q1.py` is run by hand (or the script's glob is extended by its
  owner).

## 14. Debug findings and expected sample (census TRAIN third, counts only)

Filled in after the debug run (below), before any TRAIN data was read. Nothing in §1-§13 was changed by it.
