# Q2 pre-registration: copycat order (veto) and original spillover (entry)

Idea-mill queue item **q2 · CC1** (`scratchpad/ideas/mill/QUEUE.md` §1, `queue.json` id `q2`).

- **Version:** `q2-v1`.
- **Written:** 2026-10-09, before any Q2 run on TRAIN, VAL, TEST, CONFIRM or FINAL data. Every constant, the key
  function (§2.2), the grid (§7), the controls (§8) and the decision rules (§9) were fixed here **before** the debug
  run on the census TRAIN third (§13). That run reports counts only: returns hidden, no parameter chosen there.
- **Code:** `research/lab2/q2.py`, on the shared foundation `research/lab2/common.py` (every feature through
  `common.AsOf`). Tests: `research/lab2/tests/test_q2.py`.
- **Data:** `graduates` (name, symbol, creator, g_ts), `b2_coins`, `b2_bars` (B2 minute bars to g + 180 min). No B1,
  no B3, no CryptoHouse queries. Readiness: **READY** (subject to the global blocker in §12).
- **Protocol:** PLAN §3 (shared protocol), §3.5 (entry and veto bars), §3.6 (automatic rejections), §6.6 (leakage
  rules), §8 (stop rules), and the mill's shared rules (QUEUE.md "Shared rules for every spec"), through common.py's
  `AsOf`, `backtest`, placebo, `run_entries`, `describe`, `verdict_entry`, `verdict_veto`, trial ledger, shortlists
  and one-shot sessions. Stage gating and CLI follow `m1.py`; the two-branch layout follows `z4.py`; the veto host
  is `g1.host_r0` verbatim.
- **Splits:** common.py's (TRAIN 10-01 → 10-05, VAL → 10-06 12:00, TEST → 10-07 19:37:30, CONFIRM 09-16 → 10-01,
  FINAL = census day; the census TRAIN third is debug only).
- **Freeze.** The first official TRAIN run hashes this file into `Q2/prereg.lock`. After that `q2.py` refuses every
  stage if this file changed. A change is a new version (`q2-v2`) in `Q2/AMENDMENTS.md`, and its configs are new
  trials.

## 1. Hypothesis and mechanism

**Claims (public, merged raw ideas RS-R5, TD-T22, RD-R14, RD-R15, TW-14, TD-E2):**

- *Meme Coin Factories* (arXiv 2609.10246): about 10 % of pump.fun coins are copycats; originals graduate 9.20 % of
  the time against 0.86 % for copies.
- Axiom "OG Mode": the oldest, highest-cap token of a name is "often a pump target".
- Reddit: a niche moment with 1-2 tokens is cleaner than a trend with 30 copycats.
- The Defiant: new liquidity goes to the category leader first.

**Two testable consequences after graduation, where we trade:**

1. **Copy order is a dose (arm A, a veto; arm C, the dose-response).** The k-th graduate of a name within a week is
   mostly a factory launch (wave 1's F4 brand-ticker farm rugged at g + 15-30 min). Its buyers are split across k
   copies and the deployer dumps. Prediction: R0 / R30 host returns fall with `pos` (the number of earlier same-name
   graduates), so skipping `pos ≥ P` removes losers.
2. **Spillover to the original (arm B, an entry).** When a copy graduates, it is trending; searchers for the name
   find the original too (Barber-Odean search problem; "liquidity goes to the leader"). Prediction: buying the
   cluster's original (OG) shortly after a copy graduates beats a matched random entry **and** the same OG bought at
   a quiet time.

**Who loses:** buyers of the 2nd, 3rd ... copy (factory exit liquidity) for arm A; late spillover buyers of the OG
for arm B.

**Why it may fail** (the honest prior: arm A is a filter that at best makes a losing host lose less; arm B most
likely fails):

- Only **graduates** are visible. "Original" means the first *graduate* of the name in 7 days, not the first launch
  (launches that never graduated need D4). Copies that died on the curve are invisible.
- Graduation already prices the theme; spillover may be taken in the first seconds by bots keyed on names.
- G1's FACTORY class (instant + top-5 share) and its RA-03 ticker-reuse amendment may already capture arm A. Every
  result is therefore reported by G1 class, and the random veto is also drawn **within** G1 class (§8).
- Generic names (e.g. `PEPE`, `TRUMP`) cluster unrelated coins; exact-key matching (not tokens) limits this.

### 1.1 Not a duplicate

| Hypothesis / rule | What it uses | Q2 differs by |
|---|---|---|
| Z4 (theme momentum / exhaustion) | shared name **tokens**, other creators only, conditioned on the theme's **outcomes** (heat) | Q2 uses the **exact** name or symbol key, any creator, and only **structure** (order and timing), no outcomes |
| G1 / craft G04 (RA-03) | FACTORY flag if a ticker is reused ≥ 3 times in 48 h (a counted G1 amendment, not yet in `g1.py`) | Q2 measures the order as a dose (0, 1, 2, ≥ 3 within 7 d) and adds an original-spillover **entry** |
| bot `[copycat]` warning (`cocoon._add_name_warnings`) | ticker seen on another mint within 6 h; a warning only | Q2 tests whether such a flag predicts post-graduation returns |
| PLAN N1 (H3) | buys the theme leader when a copy graduates | the closest prior idea; Q2 is its exact-key, structure-only, latency-honest version |

## 2. Data and the structural registry

### 2.1 Structural pool

Every graduate in `graduates.parquet` (any quote, Mayhem included: all of them are copies competing for the name)
**created before the end of the split being run** (g1's registry rule: a later split never feeds an earlier one;
`created_for_split`, common.py's exact-or-upper-bound creation time). Its `name`, `symbol` and `creator` are read
through `AsOf` at g + 20 s (legal from creation or g). There is no lower bound: the names and graduation times of
coins created before the split (the CONFIRM period included) are **structure**, never outcomes. No outcome of any
other coin is read anywhere in Q2.

Stage → pool end: TRAIN, VAL, TEST, CONFIRM = their split end; debug = the census TRAIN third's end; FINAL = none.

### 2.2 Keys (frozen)

`key(s)`: NULL or empty → NULL; else NFKD-normalize, drop combining marks, case-fold, keep the characters for which
Python's `str.isalnum()` is true; an empty result → NULL. So `$PEPE`, `pepe` and `ＰＥＰＥ` share the key `pepe`;
`Pepe Coin` is `pepecoin`; `🐸` is NULL. Each coin has `sym_key = key(symbol)` and `name_key = key(name)`.

Two coins **match** when their `sym_key`s are equal and non-NULL **or** their `name_key`s are equal and non-NULL
(same field; no cross-field matching).

### 2.3 Cluster, position and original of a coin c

| Feature | Definition |
|---|---|
| `cluster(c)` | pool graduates p ≠ c with g_c − 7 d ≤ g_p < g_c that match c |
| `pos(c)` | \|cluster(c)\|: the number of earlier same-key graduates in 7 days. **NULL** when both of c's keys are NULL (creation not scanned: `has_create = 0`, about 15 % of graduates). NULL is never 0 |
| `OG(c)` | the earliest member of `cluster(c)` (by g, then mint) |
| `copies(o)` | pool graduates m with OG(m) = o (o is the original from m's point of view) |
| link | `symbol`, `name` or `both` (diagnostic) |

`pos(c)` is fixed at g_c: graduates after g_c never change it. It is legal at any decision τ ≥ g_c.

### 2.4 Lookback coverage (a known limitation, reported, never a filter)

`graduates.parquet` starts at **2026-09-30 17:01 UTC**. The 7-day lookback is therefore truncated for every TRAIN
coin (7 h of history at the start of TRAIN, 4.3 days at its end), nearly full on VAL and TEST, full on the census day
(debug, FINAL), and missing for CONFIRM until the graduates backfill reaches 09-09. Missing CreateEvents (NULL keys)
also hide pool members. **`pos` is a lower bound**: an undercount moves copies into lower bins and dilutes any
dose-response (a bias toward finding nothing). For each decision coin Q2 reports `lookback_cov` = share of the 168
hours of [g − 7 d, g) that were scanned (curve hours of the snapshot), and every veto and dose result is also split
by `lookback_cov ≥ 0.99` ("full") vs "partial" (diagnostic only).

## 3. Hosts and the G1 class

- **R0** (arm A): `g1.host_r0` with `g1.R0_PARAMS` verbatim (params hash pinned `27a79bc60126`; stages refuse if it
  changes): at a seeded random age in [30, 115] min, enter if `alive`, else never; −50 % stop, 60 min hold.
- **R30** (arm C): the first decision-grid time ≥ g + 30 min; enter if `alive`, else never; −50 % stop, 60 min hold,
  registered deadline g + 178 min (y5's host).
- **G1 class** of every coin at g + 140 s: `g1.classify(g1.g1_features(AsOf(c, g + 140 s), None))` (OPERATOR, FACTORY,
  COMPLETED, ORGANIC, UNRESOLVED). Legal at every Q2 decision (τ ≥ g + 120 s).
- `alive` = `AsOf.alive()` defaults: ≥ $1.5k volume in 15 min and market cap ≥ $6k.
- **Fills** (all arms): `common.FillConfig(exit_delay_bars=1)`: $20, latency 30 s, entry at max(open, high) of the
  landing bar, exits at min(open, low), stops checked from the entry bar, every triggered exit fills in the next bar.
  PumpSwap fee tier by date + 10 bps Ultra + 20 bps buffer, network fees, pricing on X = x + v.

## 4. Arm A: the copy-order veto (`Q2-veto` on host `Q2-host` = R0)

- **Flag:** `pos(c) ≥ P` at the R0 entry, P ∈ {1, 3}.
- **Population:** R0 trades with known `pos`. Trades with NULL `pos` are counted and reported, never flagged, never
  in the verdict.
- **Verdict:** `common.verdict_veto` (PLAN §3.5): (1) flagged mean ≤ unflagged mean − 10 points with the coin-bootstrap
  95 % CI of the difference excluding 0; (2) out of sample, removing flagged trades raises net profit; (3) the veto
  removes < 25 % of the host's winning profit. UNDERPOWERED with < 30 flagged or < 30 unflagged.

## 5. Arm B: original spillover (`Q2`)

- **Event:** a copy m of o graduates (m ∈ copies(o), g_m − g_o ≤ W).
- **Decision:** at the first decision-grid time t ≥ g_m + 420 s (after m's BOOST window). τ = t − 20 s ≥ g_m + 400 s:
  m's graduation and every graduate defining OG(m) are known.
- **Entry:** buy o at t if o is `alive` and aged ≥ 30 min at t. Otherwise this event passes; a later copy's event may
  still trigger. One entry per coin (common.backtest).
- **W ∈ {60, 150} min.** W ≤ 150 min because o's B2 bars end at g_o + 180 min.
- **Exits:** −50 % stop, plus either `hold60` (60 min after the entry fill) or `deadline` (no hold limit), and in both
  the registered deadline g_o + 178 min (`exit_by_age_s`; it binds for late entries under `hold60`).
- **Tags** (diagnostic): `copy1` when m is o's first copy, `copy2+` otherwise.

## 6. Arm C: dose-response (`Q2-dose` on R30)

R30 trades grouped by `pos` bin ∈ {0, 1, 2, ≥ 3} (and NULL), by G1 class: n, mean, coin-bootstrap 95 % CI per bin;
the dose statistic ρ = Spearman(bin, `ret_net`) over known-`pos` trades with a coin-bootstrap 95 % CI.

| Dose reading | Condition |
|---|---|
| UNDERPOWERED | fewer than 30 trades in bin 0 or in bin ≥ 3 |
| NEGATIVE | ρ's 95 % CI upper bound < 0 |
| NONE | otherwise |

The dose reading is **reported at every stage it runs and never decides** anything (no branch, no shortlist).

## 7. The grid: every configuration is a counted trial (8 in all, limit 12)

| Hypothesis | Configs | Count |
|---|---|---:|
| `Q2` arm B | W ∈ {60, 150} min × exit ∈ {`hold60`, `deadline`} | 4 |
| `Q2-veto` arm A | P ∈ {1, 3} (evaluations on the R0 host trades, logged with `common.record_run`) | 2 |
| `Q2-dose` arm C | the R30 run with the §6 analysis | 1 |
| `Q2-host` | the R0 host run itself (fixed, never searched) | 1 |
| **Total** | QUEUE.md's 7 grid configs + the host run | **8** |

- Each params dict carries every constant in §2-§6, the fill model and the version. Any change is a new trial. VAL,
  TEST, CONFIRM and FINAL re-run shortlisted configs under the same identities.
- The event-time placebo (§8) runs through `common.run_entries` under its config's own identity: no new trial.
- **Stress runs** (same call, never used to select): arm B: costs × 1.5, rent $0.22, same-bar exits
  (`exit_delay_bars=0`); hosts: costs × 1.5 (the veto difference under stress is reported).

## 8. Controls

**Arm A, random veto at the same rate (reported at every stage, never decisive):** 2,000 random relabelings of the
flag over the same known-`pos` host trades, keeping the flagged count: `p_random` = share of random vetoes whose
flagged − unflagged difference is ≤ the observed one. Also **within G1 class** (flags shuffled inside each class):
`p_within_g1` answers "does copy order add anything beyond G1's class?".

**Arm B, matched-timing random entry (judged: PLAN §3.5 item 5 and the TRAIN bar):** `common.backtest`'s placebo,
20 draws per signal, a random `alive` coin of the same split at a decision age within ±120 s, same exits, **same G1
class** (`placebo_strata` = class at g + 140 s). The unmatched control (alive, any class) is reported.

**Arm B, event-time placebo (judged: the TRAIN bar and extra Q2.1):** for each signal (o, t), up to 5 random
decision-grid times t′ of the **same coin o** (seeded by the config and the signal index, without replacement) with
age(t′) ∈ [30 min, W + 8 min] (arm B's own decision ages), o `alive` at t′, and **no graduate matching o with
g_o < g_m in (t′ − 60 min, t′]** (no copy graduated in the previous hour). Same exits. Paired difference: signal
return − mean of its placebo returns, coin-bootstrap 95 % CI. A signal without an eligible t′ is unmatched. The
comparison needs ≥ 10 matched signals; with fewer it is "not computable".

## 9. Procedure by stage (`python research/lab2/q2.py --stage …`)

### Every stage

A stage refuses to run unless:

- `Q2/PREREG.md` exists, and matches `prereg.lock` once locked;
- the R0 host params hash is the pinned `27a79bc60126`;
- stop rule 1 holds: `common.validation_gates` passes for the split;
- coverage is complete: every chain hour scanned (curve and B2), ≤ 5 % of tradeable coins miss B2, no mid-run hour,
  SOL/USD covers the split (FINAL is exempt from the completeness part);
- guarded splits have the judge's flag (`LAB2_ALLOW_TEST`, `LAB2_ALLOW_CONFIRM`, `LAB2_ALLOW_FINAL`); `q2.py` never
  sets it.

Two **branches** run and stop independently: **ENTRY** (arm B) and **VETO** (arm A). Arm C runs with them (§6).

### TRAIN (all searching)

Run the 4 arm-B configs (with the matched and unmatched controls, the event-time placebo and the stress runs), the
R0 host, the R30 host, and log the 2 veto evaluations.

**ENTRY branch.** An arm-B config qualifies when all hold:

| Requirement | Bar |
|---|---|
| Sample | ≥ 30 trades |
| Mean net | > 0 |
| Mean without the top 2 trades | > 0 |
| Matched-control `mean_diff` (G1-class matched) | > 0 |
| Event-time placebo | ≥ 10 matched signals and `mean_diff` > 0 |

Choice: the qualifying config with the highest coin-bootstrap 90 % CI lower bound; ties → higher mean → W = 60 →
`hold60`.

**VETO branch.** P qualifies when ≥ 30 flagged and ≥ 30 unflagged R0 trades (known `pos`) and veto criteria 1 **and**
3 hold on TRAIN. Choice: the P with the lower CI upper bound of the difference; ties → P = 3 (the narrower veto).

**Shortlists** (written before VAL with `common.write_shortlist`, frozen at the first VAL run):

- `Q2` = [the chosen arm-B config] (ENTRY branch only);
- `Q2-host` = [the R0 host] (VETO branch only);
- `Q2-dose` = [the R30 run] (whenever either branch qualifies, so arm C runs alongside).

**TRAIN decision:** SHORTLISTED (branches listed) if either branch qualifies; otherwise NO_CONFIG if some arm-B config
or some P met its sample bar, else UNDERPOWERED_TRAIN. A complete TRAIN's decision is final (a re-run needs
`--rerun-reason` naming a data correction). `--allow-partial` runs a PROVISIONAL TRAIN that never writes a lock or a
shortlist.

### VAL (shortlisted configs only, once)

| Branch | Decision |
|---|---|
| ENTRY | UNDERPOWERED_VAL (n < 5) / FAIL_VAL (mean ≤ 0 or mean without top 2 ≤ 0) / SELECTED_UNDERPOWERED (5 ≤ n < 15) / SELECTED |
| VETO | UNDERPOWERED_VAL (< 5 flagged) / FAIL_VAL (flagged not worse, or powered and criterion 1 fails) / SELECTED_UNDERPOWERED (< 30 flagged or unflagged, flagged worse) / SELECTED (criterion 1 holds) |

A branch proceeds on SELECTED or SELECTED_UNDERPOWERED.

### TEST (one `common.one_shot_session` for the Q2 family; live branches only)

- **ENTRY:** `common.verdict_entry(test, val=VAL candidate, min_mean=0.03)` (PLAN §3.5 items 1-8 and 10, §3.6) plus:

  | ID | Criterion |
  |---|---|
  | Q2.1 | beats the event-time placebo: ≥ 10 matched signals and `mean_diff` > 0 (fewer matched: not computable → INCOMPLETE) |
  | Q2.2 | mean > 0 without the most profitable OG creator (one operator cannot carry the result) |

  Combined as in M1 / Z4: REJECTED > UNDERPOWERED > FAIL > INCOMPLETE > PASS. Item 9 is judged after FINAL.
- **VETO:** `verdict_veto` with the VAL R0 trades in sample (criteria 1, 3) and the TEST R0 trades out of sample
  (criterion 2).
- UNDERPOWERED is expected on a 1.3-day TEST.

### CONFIRM (one run, never searched; live branches only)

- ENTRY is live when TEST was not REJECTED and (TEST mean > 0 or TEST n < 5). VETO is live when the TEST veto verdict is
  not FAIL. CONFIRM refuses when no branch is live.
- ENTRY: the TEST verdict rules. VETO: `verdict_veto` with all three criteria on CONFIRM itself.
- CONFIRM also needs the graduates backfill before 09-30 (§2.4); until then its coverage check refuses.

### FINAL (the census day; after TEST)

Live branches once, as one session. Criterion 9 (ENTRY mean > 0; VETO flagged mean < unflagged mean) is judged on
`final_val` + `final_test`; `final_train` was the debug third and is reported apart.

**Overall:** ENTRY = EDGE only with VAL selected, TEST not failed, CONFIRM PASS and FINAL mean > 0. VETO = VETO only
with VAL selected, TEST veto not FAIL, CONFIRM veto PASS and FINAL flagged < unflagged. Otherwise UNDERPOWERED or NO
EDGE / NO VETO per branch. The arm C dose reading is printed next to it.

## 10. Metric and statistics

- Unit: `ret_net` per $20 trade, one entry per coin per config. `common.describe`: coin and 6-hour block bootstrap
  CIs, mean without the top 2, halves, top-coin share, censored share, deflated Sharpe over every ledger trial; the
  $100 / 5-slot portfolio; stress means.
- **By G1 class, always** (QUEUE shared rule 4): veto flagged / unflagged means per class; dose bins per class; arm-B
  trades by the OG's class.
- **Arm-B diagnostics, never decisive:** by tag (`copy1` / `copy2+`), by lag (g_m − g_o ≤ 30 min or more), by the OG's
  own `pos` (0 or ≥ 1), by link (symbol / name / both), number of OG creators, mean without the best creator.
- **Arm-A diagnostics, never decisive:** by link, by lookback coverage (full / partial), the veto difference under
  costs × 1.5, the random-veto p-values (§8).

## 11. Leakage rules (PLAN §6.6), enforced in code and tested

1. **Strictly past:** `pos`, `cluster` and `OG` use graduates with g_p < g_c only; never the coin itself. An arm-B
   event needs g_m + 420 s ≤ t (so g_m ≤ τ − 400 s), and OG(m) uses graduates before g_m.
2. **Structure only:** names, symbols, creators and graduation times. No other coin's price, volume or outcome is
   read.
3. **Forward in splits:** the pool holds graduates created before the end of the split being run.
4. **Leakage test** (`tests/test_q2.py`): garbage after T in every coin's bars, and new or renamed graduates after T,
   leave every `pos`, every OG, every arm-B event and every decision at τ ≤ T unchanged (synthetic, and real
   census-third structure when the FLOW snapshot is present).
5. **Declarations** to `auto_rejections`:

   ```
   uses_wallet_reputation = False      # a structural registry (names, order, timing), no outcome records
   uses_organic_flow = False
   uses_truncated_windows = False
   uses_current_state_fields = False
   ```

## 12. Kill criteria and deviations

**Global blocker (QUEUE shared rule 8):** the lab2 bar-0 price fix (task #26) must land in `common.py` before any
TRAIN or VAL run. `q2.py` has no machine check for it; the operator must not run `--stage train` before it lands.

**Kill criteria:** stop rule 1 (data first); stop rule 7 (report FAIL_VAL per branch); stop rule 8 (every config
counts, §7). There is no model-check stop: the R0 host is the built-in null for arm A, and the matched and
event-time placebos are the nulls for arm B.

| Area | Deviation |
|---|---|
| "Original" | the first **graduate** of the key in 7 days, not the first launch (non-graduated launches need D4) |
| Lookback | 7 days as specified, truncated on TRAIN by the graduates table's start (§2.4); `pos` is a lower bound there |
| NULL names | about 15 % of graduates lack a CreateEvent (`has_create = 0`): their `pos` is NULL (not in the veto verdict) and they are invisible as pool members (another undercount) |
| Pool edge | a copy created after the split's end never triggers an arm-B event for an OG of that split (pool rule §2.1); this touches OGs that graduated in the split's last ~2.5 h |
| Matching | exact key equality per field; no fuzzy, cross-field or image matching |
| Arm C | descriptive; it never decides (QUEUE: "one counted run") |
| Fills | minute-bar "worst" fills with next-bar exits, not replayed fills (X1 engine) |

## 13. Debug findings and expected sample (census TRAIN third, counts only)

To be filled from `python research/lab2/q2.py --debug` (`Q2/debug.md`, `Q2/debug.json`). Returns, exit reasons and
placebo outcomes are hidden; its trials go to a scratch ledger, never to `trials.json`. **Nothing in §1-§12 may change
after this run** except through a dated amendment that adds no outcome-based choice.
