# Q7 (PS1) pre-registration: is a mint without the "pump" suffix a coin to skip?

- **Version:** `ps1-v1`. Ledger hypothesis names: `PS1` (the four veto configs), `PS1.R0` and `PS1.R30` (the two
  fixed host runs). All three are the family `PS1`.
- **Queue item:** q7 · PS1 in `scratchpad/ideas/mill/QUEUE.md` (status NEW, kind veto, merged raw idea RS-R3). The
  QUEUE's shared rules 1-8 apply; this file states only what PS1 adds or fixes.
- **Written:** 2026-10-09, before any PS1 run on TRAIN, VAL, TEST, CONFIRM or FINAL data. Every constant, the grid
  (§5), the placebo (§6) and the decision rules (§8) were fixed here **before** the debug run on the census TRAIN
  third (§13). That run reports counts only: returns hidden, no parameter chosen there.
- **Code:** `research/lab2/q7.py`, on the shared foundation `research/lab2/common.py` (every feature through
  `common.AsOf`). Tests: `research/lab2/tests/test_q7.py`.
- **Data:** `graduates` (the mint string and the CreateEvent fields `creator`, `create_user`), `b2_coins`, `b2_bars`.
  No B1, no B3, no CryptoHouse queries. **Readiness: READY.**
- **Protocol:** PLAN §3 (shared protocol), §3.5 (the veto bar, `common.verdict_veto`), §3.6, §8 (stop rules), through
  common.py's `AsOf`, `backtest`, `describe`, `verdict_veto`, trial ledger, shortlists and one-shot sessions. Stage
  gating, the CLI and the veto branch follow `g1.py` (host trades annotated at the decision) and `z4.py` (the EXH
  veto branch: VAL in sample, TEST out of sample, CONFIRM on itself).
- **Splits:** common.py's (TRAIN 10-01 → 10-05, VAL → 10-06 12:00, TEST → 10-07 19:37:30, CONFIRM 09-16 → 10-01,
  FINAL = census day; the census TRAIN third is debug only).
- **Global blocker:** the lab2 bar-0 price fix (task #26) must land before any TRAIN or VAL run (QUEUE shared rule 8).
  PS1 does not edit `common.py`; every stage records `common.py`'s sha256 so the version that ran is visible.
- **Freeze.** The first official TRAIN run hashes this file into `Q7/prereg.lock`. After that `q7.py` refuses every
  stage if this file changed. A change is a new version (`ps1-v2`) in `Q7/AMENDMENTS.md`, and its configs are new
  trials.

## 1. Hypothesis and mechanism

**Claim** (Meme Coin Factories, CMU / EPFL / ETH, 15.2 M coins, https://arxiv.org/html/2609.10246v1):

- the pump.fun app grinds a vanity mint address that ends in `pump`;
- a mint without the suffix was created by a script or a custom contract, the tooling of large "factories";
- copycats lack the suffix 26.5 % of the time against a 16.05 % baseline.

**Mechanism.** Creating outside the app takes tooling. Tooling marks an automated operator with many wallets and a
planned exit; its coins are supply to be sold into later buyers. A buyer at g + 30 min to g + 2 h is that later buyer.

**Who would pay, and why a veto could help.** If suffix-less coins are operator coins, their post-graduation path is
an exit: a random entry into them (the R0 / R30 hosts) loses more than a random entry into app-made coins, and
skipping them makes the host lose less. A veto can only make a losing host lose less (PLAN §0); it is not an edge on
its own.

**Why it may fail** (the honest prior: plausibility 2 of 5, expected FAIL):

- **The suffix is now common outside factories.** On TRAIN 32.1 % of usable graduates lack it (QUEUE structure
  check), double the paper's 16 % baseline. Much of that is probably third-party launch tooling (trading terminals'
  "create" and relaunch features, bots) used by ordinary deployers, not factories.
- **G1 already sees the factories.** G1's FACTORY / OPERATOR / COMPLETED classes (pool flow in the first 2 min, curve
  concentration, instant graduation) may carry everything the suffix carries. Config 2 (§5) and the class-stratified
  placebo (§6) measure what the suffix adds beyond G1.
- **The creation path says nothing about the post-graduation hour** once the operator's dump is priced in by
  g + 30 min.

**The secondary flag `CU`** (`create_user ≠ creator` in the CreateEvent): the wallet that signed and paid for the
creation is not the wallet named creator (the creator-fee recipient). Creation on someone else's behalf is another
tooling marker (QUEUE: "check meaning on 20 coins first"; §2.3 and §13).

### 1.1 Not a duplicate

| Hypothesis | What it uses | PS1 differs by |
|---|---|---|
| G1 (FACTORY, OPERATOR, COMPLETED, G-time) | pool flow, curve concentration, creation-to-graduation delay | PS1's flag is the creation **path** (mint suffix, signer vs creator); reported inside every G1 class (§7) |
| Y1 / craft G17 | the same creator's earlier outcomes | no cross-coin information at all |
| Z4, q2 (copycats) | name / symbol links between coins | the paper's copycat statistic is the motivation only; PS1 reads no names |
| M1, X-, Y-, Z- entries | the coin's own bars and wallets | PS1 is a static coin fact known at creation |

## 2. Flags (features), all through `common.AsOf`

### 2.1 SFX0

`SFX0 = not mint.endswith("pump")`. The mint is legal at every τ (`common._legal_from("mint") = −∞`). Case-sensitive,
exactly the four lowercase letters. Never NULL.

### 2.2 CU

`CU = create_user ≠ creator`, both read through `AsOf` (CREATE_COLS: legal from the exact creation time, else from
g). NULL or empty `creator` or `create_user` → CU is **unknown** (NULL is never 0). A slow graduate whose CreateEvent
was not scanned (`has_create = 0`) is unknown. Unknown trades are **not** in CU's evaluation set and are counted
(§7); a deployed CU veto would keep them.

### 2.3 CU meaning check (the QUEUE's "check on 20 coins first")

Structure only, on the census TRAIN third (the debug run), before TRAIN:

- list up to 20 CU coins: mint, `creator`, `create_user`, how many usable coins of the third each of the two
  addresses appears on (as signer, as creator), whether the signer is another coin's creator, SFX0, `grad_delay_s`,
  instant, `token_program`, G1 class;
- **withdrawal rule (pre-registered):** config 4 is withdrawn before TRAIN (grid = 3) only if CU is degenerate on the
  third: true for < 2 % or > 98 % of the coins whose CU is known. No other outcome of the check changes anything.

### 2.4 What the flags are not

- Both flags are coin facts fixed at creation. They are read at the host's decision time `t_dec` (exactly what a
  live veto would see) and are identical at every τ ≥ creation.
- No cross-coin registry, no outcome of any other coin: PLAN §6.6 registries do not arise. The leakage unit test
  still runs (garbage after τ in the coin's own data leaves every flag and class unchanged, §10).

## 3. Hosts (fixed, never searched)

| Host | Definition | Source |
|---|---|---|
| **R0** | at a seeded random age in [30, 115] min (sha256 of `0:<mint>`), enter if `alive` (≥ $1.5k volume in 15 min and market cap ≥ $6k), else never; catastrophe stop −50 %, time exit 60 min after the fill | `g1.host_r0` with `g1.R0_PARAMS` (params hash pinned `27a79bc60126`) |
| **R30** | at the first decision ≥ g + 30 min, enter if `alive`, else never; −50 % stop, 60 min hold, registered deadline g + 178 min (never binds) | `y5.host_r30` with `y5.R30_PARAMS` (params hash pinned `a995b4907d17`) |

- `q7.py` imports both functions; a changed host (params hash) makes every stage refuse. A changed host is a new
  PS1 version.
- **Fills** (QUEUE shared rule 2): `common.FillConfig(exit_delay_bars=1)`: $20, latency 30 s, entry at max(open,
  high) of the landing bar, exits at min(open, low), stops checked from the entry bar, every triggered exit fills in
  the next bar at its adverse side; PumpSwap fee tier by date + 10 bps Ultra + 20 bps buffer, network fees, pricing on
  X = x + v. R0's latest exit fills by about g + 178 min, inside the B2 window; censored trades are reported and
  bounded (§8).
- **Stress** (same call, never used to select): costs × 1.5. The veto's flagged − unflagged difference is reported
  under it.
- Hosts run **without** the matched-timing entry placebo: PS1's control is the random veto (§6).

## 4. G1 classes (reporting and config 2)

The class of every coin is G1's (PLAN §4.2, `g1.classify(g1.g1_features(AsOf(g + 140 s)))`, imported): OPERATOR >
FACTORY > COMPLETED > UNRESOLVED > ORGANIC, read at g + 140 s (τ = g + 120 s) as QUEUE shared rule 4 asks. Instant
(graduated ≤ 5 s after creation) is G1's `instant` at the same time (NULL when the creation is unknown and the lower
bound does not decide). Every host decision is at ≥ g + 30 min, so both are known at the decision.

## 5. The grid: 4 veto configs, every one a counted trial

| # | Config key | Host | Evaluation set (host trades) | Flag |
|---|---|---|---|---|
| 1 | `R0\|SFX0\|ALL` | R0 | all | SFX0 |
| 2 | `R0\|SFX0\|ORGANIC` | R0 | G1-ORGANIC coins only (the suffix's value beyond G1) | SFX0 |
| 3 | `R30\|SFX0\|ALL` | R30 | all; plus the SFX0 × instant dose report (§7) | SFX0 |
| 4 | `R0\|CU\|ALL` | R0 | CU known | CU |

- Each config's params carry the version, the host's params and pinned hash, the flag, the subset, the fills and
  every constant of §6-§8. Any change is a new trial.
- **Ledger entries:** the 4 veto configs (`PS1`) plus the 2 fixed host runs (`PS1.R0`, `PS1.R30`), each logged once
  per split under the same identity. **PS1's whole life adds 6 entries** to `research/lab2/trials.json` (the QUEUE
  budgets 4 configs; the 2 host runs are the looks that produce them and are counted too). Later stages re-run the
  same identities and add no trials.
- Config 3 is the QUEUE's "dose-response: R30 by SFX0 × instant (one run)". Its decisive part is the SFX0 veto on a
  second host (an earlier, fixed decision age); the 2 × 2 dose table is the pre-registered mechanism report (§7, §9),
  never decisive.

## 6. Placebo: a random veto at the same rate, stratified by G1 class

For a config's evaluation set (returns r, flags f, G1 class s of each trade):

- one draw: inside every class stratum, flag exactly as many trades as f flags there, chosen at random (a within-
  stratum permutation of f); compute d_b = mean(r | flagged) − mean(r | unflagged);
- **2,000 draws** (seed 0); the real difference d is compared with them:
  **placebo p = (1 + #{d_b ≤ d}) / (1 + 2,000)**, one-sided;
- also reported: the draws' mean and 5th percentile, the strata and their flag counts.

This answers "does the flag pick worse trades than a random veto with the same class composition?" A flag that is
only a G1-class proxy gets p ≈ 0.5 or larger (its whole raw difference reappears in the draws). For config 2 there is
one stratum (a plain random veto).

## 7. Statistics and reports (every non-debug stage)

- **Unit:** `ret_net` per $20 host trade, one trade per coin per host.
- **Veto bar** (`common.verdict_veto`, PLAN §3.5, QUEUE shared rule 6): (1) flagged mean ≤ unflagged mean − 10 points
  with the coin-bootstrap 95 % CI of the difference excluding 0; (2) out of sample, removing the flagged trades raises
  net profit; (3) the veto removes < 25 % of the host's winning profit; UNDERPOWERED with < 30 flagged or < 30
  unflagged trades.
- **Per config:** n host trades, n in the evaluation set, n unknown flags (CU), flagged share and flagged trades per
  day, flagged / unflagged / host means, the difference with a coin-bootstrap 95 % CI, winning profit removed, $ P&L of
  the host and of the gated host, `describe` of the kept trades, censored share, the costs × 1.5 difference, the
  placebo (§6).
- **By G1 class** (QUEUE shared rule 4): flagged and unflagged n and mean inside each class.
- **Dose report** (configs 1 and 3; pre-registered prediction on config 3): the 2 × 2 cells SFX0 × instant (n, mean),
  instant-unknown trades apart; dose D = SFX0 + instant ∈ {0, 1, 2} with its means and whether they are monotone
  (D0 ≥ D1 ≥ D2); the interaction (SFX0 gap among instant − SFX0 gap among slow) with a coin-bootstrap 95 % CI.
- **CU structure** (§2.3) on every stage: counts and the CU × SFX0 table.

## 8. Procedure by stage (`python research/lab2/q7.py --stage …`)

### Every stage

A stage refuses to run unless:

- `Q7/PREREG.md` exists, and matches `prereg.lock` once locked;
- stop rule 1 holds: `common.validation_gates` passes for the split;
- coverage is complete: every chain hour scanned, ≤ 5 % of tradeable coins miss B2, no mid-run hour, SOL/USD covers
  the split (FINAL is exempt from the completeness part);
- both host pins hold (§3);
- guarded splits have the judge's flag (`LAB2_ALLOW_TEST`, `LAB2_ALLOW_CONFIRM`, `LAB2_ALLOW_FINAL`); `q7.py` never
  sets it.

### TRAIN (all searching)

Run R0 and R30 once each, annotate their trades, evaluate the 4 configs. A config **qualifies** when all hold:

| Requirement | Bar |
|---|---|
| Sample | ≥ 30 flagged and ≥ 30 unflagged trades in its evaluation set |
| Veto criterion 1 | flagged ≤ unflagged − 10 points, 95 % CI upper bound < 0 |
| Veto criterion 3 | removes < 25 % of the winning profit |
| Placebo | p ≤ 0.05 (§6) |
| Censored | ≤ 10 % of the host's trades end on the data horizon |

- **Shortlist** (≤ 2, written with `common.write_shortlist` before VAL, frozen at the first VAL run): the qualifying
  configs ranked by the 95 % CI upper bound of the difference (lower first), ties → grid order; the top 2. The host
  shortlists `PS1.R0` / `PS1.R30` hold the fixed host params of the hosts the shortlist needs.
- **TRAIN decision:** SHORTLISTED if a config qualifies; else NO_CONFIG if some config met the sample bar; else
  UNDERPOWERED_TRAIN. A complete TRAIN's decision is final (a re-run needs `--rerun-reason` naming a data correction;
  the previous result is archived). `--allow-partial` runs a PROVISIONAL TRAIN that never writes a lock or a shortlist
  and never unlocks VAL.

### VAL (the shortlisted configs, once)

Run the hosts the shortlist needs once; each shortlisted config gets:

| Decision | Condition |
|---|---|
| UNDERPOWERED_VAL | < 5 flagged trades (or an empty side) |
| FAIL_VAL | flagged mean ≥ unflagged mean, or (≥ 30 flagged and ≥ 30 unflagged and criterion 1 fails) |
| SELECTED_UNDERPOWERED | flagged mean < unflagged mean with < 30 flagged or < 30 unflagged trades |
| SELECTED | ≥ 30 / ≥ 30 and criterion 1 holds |

**One candidate** goes on: among SELECTED, else SELECTED_UNDERPOWERED, configs, the lower VAL difference; ties → grid
order. No candidate → PS1 stops (stop rule 7: FAIL_VAL is reported).

### TEST (one `common.one_shot_session` for the PS1 family)

Run the candidate's host once. **Formal veto verdict:** `common.verdict_veto(VAL trades, VAL flags, oos_host = TEST
trades, oos_flagged = TEST flags)` (criteria 1 and 3 on VAL, criterion 2 on TEST), plus:

| ID | Criterion |
|---|---|
| PS1.1 | TEST sign: flagged mean < unflagged mean on TEST (no evidence, never FAIL, with < 5 trades on a side) |

Combined: FAIL if the formal verdict is FAIL or PS1.1 fails; else UNDERPOWERED if the formal verdict is; else
INCOMPLETE if anything is missing; else PASS. UNDERPOWERED is expected on a 1.3-day TEST.

### CONFIRM (09-16 → 10-01; one run, never searched)

Spent only when the TEST verdict is not FAIL. Run the candidate's host once; `verdict_veto` with all three criteria
on CONFIRM itself, plus:

| ID | Criterion |
|---|---|
| PS1.2 | placebo p ≤ 0.05 on CONFIRM (§6) |
| PS1.3 | ≤ 10 % of the host's CONFIRM trades censored |

Combined as on TEST. CONFIRM is the powered test.

### FINAL (the census day; after TEST, and after a PASS at CONFIRM when CONFIRM ran)

The candidate's host once on all of FINAL (one session). Judged: flagged mean < unflagged mean on `final_val` +
`final_test`; `final_train` was the debug third and is reported apart.

### Overall

**VETO** (config named) only with TRAIN SHORTLISTED, VAL SELECTED or SELECTED_UNDERPOWERED, TEST not FAIL, CONFIRM
PASS and FINAL flagged worse. Otherwise UNDERPOWERED (the stage that lacked power) or NO VETO (the stage that failed).
A VETO is a filter for a host that is still losing money: it never turns R0 or R30 into a strategy.

## 9. Predictions (reported, never decisive)

| ID | Prediction |
|---|---|
| P1 | No PS1 config reaches VETO (prior: plausibility 2) |
| P2 | Mechanism (config 3): if SFX0 marks factory tooling, its gap is more negative among instant graduates than among slow ones (interaction < 0) |
| P3 | If SFX0 is mostly a G1-class proxy, config 1's placebo p > 0.05 even when its raw difference is negative |
| P4 | CU flags < 10 % of R0 trades: config 4 is UNDERPOWERED on VAL at best |

## 10. Leakage and declarations

- **No lookahead** (`tests/test_q7.py`): garbage after τ in a coin's bars and B2 row leaves SFX0, CU, the G1 class at
  g + 140 s, instant and every host decision at τ unchanged (synthetic coins, and real census-third bars when the
  data is present).
- No registry, no other coin's data: PLAN §6.6 does not apply beyond that test.
- **Declarations** to `auto_rejections`:

  ```
  uses_organic_flow = False
  uses_wallet_reputation = False
  uses_truncated_windows = False
  uses_current_state_fields = False
  ```

## 11. Kill criteria and deviations

**Kill criteria:** stop rule 1 (data first); stop rule 7 (FAIL_VAL is reported); stop rule 8 (every config counts,
§5). There is no model check: the flags are static coin facts and the random veto (§6) is the built-in null.

| Area | Deviation |
|---|---|
| Factory label | The paper labels factories by deployer clusters; PS1 has only the suffix and the signer / creator pair |
| Copycats | The paper's 26.5 % vs 16.05 % copycat statistic is motivation only; PS1 does not test copycats (q2 does) |
| Hosts | R0 and R30 are random entries, not a strategy; a passing veto makes them lose less |
| Fills | Minute-bar "worst" fills with next-bar exits, not replayed fills |
| G1 class | Read at g + 140 s as QUEUE rule 4 asks (G1 itself annotates its hosts at the decision time) |

## 12. Expected sample (from the debug counts in §13, before any TRAIN data)

The census TRAIN third covers 0.52 days. The rates below assume other days resemble it. On TRAIN the QUEUE's
structure check found 32.1 % of usable graduates without the suffix against 24.0 % here, so the SFX0 counts may be
higher.

| Config | flagged / unflagged: TRAIN (4 d) | VAL (1.5 d) | TEST (1.32 d) | CONFIRM (15 d) |
|---|---:|---:|---:|---:|
| `R0\|SFX0\|ALL` | ≈ 146 / 577 | ≈ 55 / 216 | ≈ 48 / 190 | ≈ 548 / 2,162 |
| `R0\|SFX0\|ORGANIC` | ≈ 69 / 154 | ≈ 26 / 58 | ≈ 23 / 51 | ≈ 259 / 577 |
| `R30\|SFX0\|ALL` | ≈ 192 / 861 | ≈ 72 / 323 | ≈ 63 / 284 | ≈ 721 / 3,229 |
| `R0\|CU\|ALL` | ≈ 77 / 569 | ≈ 29 / 213 | ≈ 25 / 187 | ≈ 288 / 2,133 |
| Host trades R0 / R30 | ≈ 723 / 1,053 | ≈ 271 / 395 | ≈ 238 / 347 | ≈ 2,710 / 3,949 |

- **Every config is powered on TRAIN** (≥ 30 / 30).
- **On VAL,** configs 2 and 4 sit at or below the 30-flagged bar: SELECTED_UNDERPOWERED at best.
- **On TEST,** the formal verdict takes its sample criteria from VAL, so a powered VAL candidate can be judged.
  PS1.1 (the TEST sign) has ≈ 25-63 flagged trades.
- **Power note** (the per-trade SD is unknown here, because returns are hidden): with ≈ 146 / 577 trades on TRAIN,
  a −10 point gap clears criterion 1 only if the per-trade SD is below about 0.55. With VAL's ≈ 55 / 216, the SD must
  be below about 0.33.

## 13. Debug findings (census TRAIN third, counts only)

**The run.** `python research/lab2/q7.py --debug` writes `Q7/debug.md` and `Q7/debug.json` (runtime 6 s).

- 450 usable coins, created over 0.52 days.
- Returns, exit reasons, placebo draws and every mean are hidden. The trials went to a scratch ledger, never to
  `trials.json`.
- **Nothing in §1-§11 changed after this run.** No flag, threshold, host, grid, placebo or decision rule was edited.

**Structure (coins):**

| Measure | Count |
|---|---:|
| SFX0 (no `pump` suffix) | 108 of 450 (24.0 %) |
| SFX0 among instant graduates | 63 of 277 (22.7 %) |
| SFX0 among slow graduates | 45 of 173 (26.0 %) |
| SFX0 by G1 class | OPERATOR 0 / 34; FACTORY 60 / 183; COMPLETED 5 / 19; UNRESOLVED 10 / 21; ORGANIC 33 / 193 |
| CU known / CU true | 429 / 28 (6.5 % of known; 21 unknown = unscanned CreateEvents) |
| CU among SFX0 vs `pump` coins | 12 of 98 known (12 %) vs 16 of 331 known (5 %) |

**CU meaning check (§2.3), 28 CU coins:**

- 26 of the 28 have a signer that signed no other usable coin of the third. The other 2 share one signer; their
  creators differ and both lack the suffix. That signer looks like a launch service.
- No signer is another coin's creator, and each creator appears once.
- 27 of the 28 are slow graduates (44-3,036 s from creation to graduation). The one instant graduate used the legacy
  Token program, the only legacy-program CU coin.
- So **CU means "a one-off wallet signed and paid for a creation that names a different, also one-off, creator"**:
  creation on someone's behalf (a tool or a second wallet), mostly on slow, organic-looking launches.
- **Withdrawal rule:** the share is 6.5 %, inside [2 %, 98 %]. **Config 4 stays.**

**Host trades** (alive at the decision; flags read at the decision):

| | R0 | R30 |
|---|---:|---:|
| Trades (per day) | 94 (180.7) | 137 (263.3) |
| Median decision age | 57.4 min | 30.4 min |
| SFX0 flagged | 19 (20 %) | 25 (18 %) |
| … of which instant graduates | **2** | **2** |
| … of which slow graduates | 17 | 23 |
| CU true / false / unknown | 10 / 74 / 10 | 15 / 109 / 13 |
| Horizon exits | 0 | 0 |

**What these counts imply, before any TRAIN data:**

- **The `alive` filter already removes almost every instant suffix-less coin.**
  - At g + 30 min only 2 of the 63 instant SFX0 coins are alive (R30 entries), against 75 of the 214 instant `pump`
    coins.
  - So at our hosts **SFX0 flags slow graduates** (17 of 19 R0 flags, 23 of 25 R30 flags). The paper's "factory"
    coins are exactly the instant ones, and they are gone before any host decides.
  - **PS1 therefore effectively tests a different claim:** are slow graduates made with third-party tooling worse
    after g + 30 min?
  - The dose report's SFX0 × instant cells will be thin: about 15 TRAIN trades in the `sfx0|instant` cell. **P2 (§9)
    will probably be unmeasurable.** Its interaction CI is reported, or `n/a`, never decisive.
- **OPERATOR coins never lack the suffix** (0 of 34). The ticker-clone operator uses the app or grinds the suffix, so
  PS1 cannot see it.
- **FACTORY trades are rarely flagged** (1 of 19 R0 FACTORY trades). The class-stratified placebo (§6) therefore
  mostly compares SFX0 inside ORGANIC, UNRESOLVED and COMPLETED trades.
- **CU flags 12 % of the R0 trades whose CU is known** (twice its coin share). CU coins are slow graduates, and those
  are more often alive at the decision. Config 4 is powered on TRAIN and borderline on VAL (§12).
