# X1 pre-registration: follow early holders whose earlier picks paid a follower (version `x1-v1`)

- **Written:** 2026-10-09, before any X1 run on TRAIN, VAL, TEST, CONFIRM or FINAL data. TRAIN was still being
  backfilled. The only run allowed today is the debug run on the census TRAIN third (§14): counts only, returns
  hidden, no parameter chosen there. The grid (§7) was fixed in this file **before** the debug run.
- **Code:** `research/lab2/x1.py`, on the shared foundation `research/lab2/common.py`. Tests:
  `research/lab2/tests/test_x1.py`.
- **Spec it implements:** the wave-2 sweep's designer x1 ("smart-money follow"), under PLAN §3 (protocol), §6.6
  (wallet-reputation leakage rules) and §8 (stop rules). It is the cheap, B2-only version of PLAN W1 (wallet
  reputation), with W1 stage 1's persistence question as a stop rule (§8).
- **Name.** The ledger hypothesis is `X1` (the sweep's designer id), plus `X1-persist` for the gate. This is **not**
  PLAN §4.1's X1 fill engine. If that engine is ever logged in `trials.json`, it must use another family name: one-shot
  looks are counted per family.
- **Freeze.** The first official TRAIN run hashes this file into `X1/prereg.lock`. After that, `x1.py` refuses every
  stage if this file has changed. Any change is a new version (`x1-v2`) in `X1/AMENDMENTS.md`, and its configs are new
  trials.

## 1. Hypothesis and mechanism

**Claim.** Some wallets that buy a fresh PumpSwap pool in its first 5 minutes, and still hold at g + 5 min, pick coins
that keep rising afterwards. If that skill persists, a coin whose early holders include a wallet whose **earlier**
picks (already resolved) would have paid a follower is worth buying right after the BOOST window.

**Why it could beat costs** (round trip 1.4-5.1 % at $20 by market cap, `common.round_trip_pct`):

1. **Information.** Early pool buyers include people tied to the team or its marketing, KOL networks, and skilled
   discretionary traders. When they buy and hold, they expect demand over the next hour. A minute-bar chart cannot
   show *who* bought; wave 1 found nothing on charts alone (`research/lab/RESULTS.md`).
2. **Delayed followers.** Copy-trade bots and "smart money" alert channels act on the same wallets with a lag. A
   wallet's reputation draws in buyers after its own buy, which is the drift a follower can take.
3. **Who loses.** Late buyers who arrive after the follower flow, and the holders who sell to us during the follow
   window. The informed wallet does not pay us; the later crowd does.

**Why it could fail** (the prior is weak, and the experience file G11 says "never follow a smart wallet"):

- skill may not persist from coin to coin: PLAN W1 stage 1 has never been run;
- reputable wallets may be the ones that dump on followers;
- with thousands of wallets, a wallet with 3-6 good picks can be pure luck; shrinkage (§3) and the persistence gate
  (§8) are there for this;
- by g + 7-8 min the price may already contain the information;
- the entry sits inside the first 30 minutes after graduation, where the census lab measured the worst losses
  (random entries: −15.7 % instant, −10.0 % slow; `docs/EXPERIENCE_GROUNDED.md` N5). The registry is exactly
  the test of whether reputable wallets pick the coins that survive that window.

**Not duplicated.** G1 gates classes and reports `repeat_migbuyer_share_2m` (how *often* a wallet appears, never how
its coins *ended*). S1 measures insider supply, D1 dips, M1 mechanical bids (OPERATOR coins). X1 scores wallets by
the realized outcome of their earlier picks and trades only the coins G1 would call neither FACTORY nor OPERATOR.

## 2. Data and instrument

- Tables: `graduates`, `b2_coins`, `b2_bars`, through `common.load()` (SOL-quoted, not Mayhem, virtual reserve known,
  complete B2 window). **B1 raw trades are not used** (they skip instant graduates and may arrive later).
- The only wallet data is B2's `w300_top10`: the top 10 pool buyers of [g, g + 300 s) by buy SOL, as
  `[wallet, buy_sol, sell_sol]`. Pooled program accounts (`common.POOLED_ACCOUNTS`) are removed when the coin is loaded;
  the AGENT (BOOST) is removed through `AsOf.top_buyers(exclude_agent=True)`, which is legal only once AGENT presence
  is decided (τ ≥ g + 420 s or its 4th buy).
- **Limits of the instrument:** a smart wallet that buys less than the 10th-largest early buyer is invisible; only
  the first 5 minutes are seen, so later smart buying is invisible; when [g, g + 330 s) straddles a chain hour the
  stored list covers only the first part (README §7). That is a partial list, never a later one.

## 3. Definitions (all features through `common.AsOf`; labels are outcomes, never features)

| Name | Definition |
|---|---|
| **Decision time** `t_d` | The first grid time (minute boundary + 20 s) with τ = t − 20 s ≥ g + 420 s: k_d = ⌈(g + 420 − m0) / 60⌉, t_d = m0 + 60·k_d + 20. Age at decision is in [440, 500) s. One decision per coin |
| **Class** | PLAN §4.2 rules, in order: OPERATOR if w120 buy SOL ex-AGENT ≥ 500 and w120 buyers ex-AGENT ≤ 30; FACTORY if `grad_delay_s` ≤ 5 and the w120 top-5 share ex-AGENT ≥ 0.85; OTHER otherwise. NULL input → NULL class (skipped). An unscanned creation uses `grad_delay_lb_s` (1,800 s), so it is never instant. Same rules as M1 §3, re-implemented in `x1.x1_class` so an M1 amendment cannot move X1 |
| **Eligible** | Class OTHER **and** `alive` at t_d (`AsOf.alive()`: ≥ $1.5k USD volume over 15 min and market cap ≥ $6k; this also drops coins at the ~17.6 SOL price floor) |
| **Early holders** E(c) | Wallets in c's `w300_top10` at t_d, pooled accounts and the AGENT removed, with buy SOL > 0 and window sell SOL ≤ 0.5 × buy SOL (`HOLD_FRAC`): they bought and still hold, so following them is following a holder, not a flipper |
| **Base follow trade** of c | A $20 entry decided at t_d(c) (landing 30 s later, worst fill = max(open, high) of the landing bar), exits as in §6, fills as in §7. Simulated by common's engine (`_simulate_coin` with a forced entry) |
| **Label** y(c) | log(max(1 + ret_net, 0.01)) of the base follow trade. Defined only for eligible coins |
| **Resolution time** r(c) | The end of the bar in which the base follow trade's exit filled (≤ g + 63 min). The label exists for decisions with τ ≥ r(c) only |
| **Registry entry** | (w, r(c), y(c), c) for every eligible history coin c (§9 history splits) and every w ∈ E(c) |
| **Wallet record at τ** | Entries with r ≤ τ and coin ≠ the coin being decided: n_w(τ) and the mean label m_w(τ) |
| **Skill** s_w(τ) | m_w × n_w / (n_w + 10) (PLAN §6.6 rule 3 shrinkage) |
| **Known wallet** | n_w ≥ N_MIN |
| **Reputable wallet** | Known and s_w > θ |
| **Lead wallet** | The reputable early holder with the highest skill (ties: larger n, then address order) |

## 4. Leakage rules (PLAN §6.6, enforced in code and tested)

1. **Strictly the past:** an entry counts at τ only when r(c) ≤ τ, and never for the coin being decided. Since the
   coin's own trade resolves after its decision, its own outcome can never score its own wallets.
2. **No open positions:** a label is a closed, simulated trade. Nothing is marked to a later price; no "it rugged".
3. **Shrinkage** as in §3. θ and N_MIN come from the pre-registered grid; the choice among them is made on TRAIN
   only (§9).
4. **Roles when knowable:** the early-holder list is read at the coin's own t_d (τ ≥ g + 420 s, after w300 and the
   AGENT are legal).
5. **Built forward in time** from resolution times; never rebuilt with later data.
6. **No outside labels:** no KOL lists, leaderboards or "smart money" tags.
7. **The registry runs forward through the splits** (§9 table): a stage uses only splits that are earlier in time and
   already had their look.
8. **Warm-up flag:** decisions within 24 h of the stage's first history graduation are flagged; results are reported
   with and without them (diagnostic, never decisive).
9. **Leakage test** (`tests/test_x1.py`): replacing every datum after T with garbage, for every coin, leaves every
   registry answer and every decision at τ ≤ T unchanged.

## 5. Entry rule

At t_d, at most once per coin:

- the coin is eligible (§3);
- at least one early holder is reputable under (θ, N_MIN).

Otherwise the coin is skipped for good (`SKIP`). The tag of each trade is its lead wallet.

## 6. Exits (fixed, not searched)

| Exit | Rule |
|---|---|
| Stop | −30 % from the entry fill (mechanical) |
| Time | sell at coin age g + 60 min (`exit_by_age_s` = 3,600: a registered deadline inside the data, so no trade is censored). It triggers at the first bar starting at or after g + 60 min and, like the stop, fills at the adverse side of the next bar (by g + 63 min) |

No take-profit, no trailing stop, no signal exit. The trade X1 takes on a coin **is** that coin's base follow trade,
so the reputation measures exactly the P&L that following the wallet would have made.

## 7. The TRAIN grid: exactly 4 configurations, every one a trial

**θ ∈ {0.00, 0.10} × N_MIN ∈ {3, 6}.**

- θ = 0: the wallet's shrunk mean log return is positive (its earlier picks paid a follower on average).
  θ = 0.10: clearly positive (n = 3 needs a mean log return above 0.43; n = 6 above 0.27).
- N_MIN = 3 / 6: the evidence depth.
- Each config's params carry every constant in §3-§6, the fill model and the version. Any change is a new trial.
- **Trials:** 4 configs + the persistence gate (`X1-persist`) = **5**, on top of the lab's 2,575 in `trials.json`.
  The sweep's cap is 12.

**Fills** (the task asks for worst fills and next-bar stops): `common.FillConfig(exit_delay_bars=1)`.

| Setting | Value |
|---|---|
| Size | $20 |
| Latency | 30 s |
| Entry fill | max(open, high) of the landing bar |
| Exit fill | a stop or time exit triggered in bar j fills at min(open, low) of bar **j + 1** |
| Entry-bar stop check | on (high first, then low) |
| Costs | PumpSwap tier by date and market cap, + 10 bps Ultra, + 20 bps buffer, network fees, pricing on X = x + v |

**Stress and sensitivity runs** come from the same call and are never used to select: costs × 1.5; rent $0.22;
same-bar exits (`FillConfig()` default). The registry labels always use the primary fills.

## 8. Persistence gate (stop rule; TRAIN, before any P&L)

This is PLAN W1 stage 1's question ("does wallet skill persist?") asked at the coin level, causally.

- **Observations:** every eligible TRAIN coin with at least one early holder known at N = 3 (n_w ≥ 3) at its t_d.
- **Score:** rep(c) = the highest skill among its known early holders, as of τ_d.
- **Label:** y(c), its base follow trade (§3), read after the trade resolved.
- **Statistic:** Spearman ρ(rep, y), its one-sided p (normal approximation z = ρ·√(n − 1)), and a 6-hour block
  bootstrap 90 % CI (two levels: blocks of decision time, then coins in a block; 2,000 draws).

| Result | Condition | Consequence |
|---|---|---|
| **UNDERPOWERED** | < 200 observations | X1 halts; the grid is not run |
| **KILL** | ρ < 0.10, or p ≥ 0.01, or the block 90 % CI lower bound ≤ 0 | **X1 is dead.** The grid is never run; every later stage refuses |
| **PASS** | otherwise | continue |

**Reported, never decisive:** label means by tercile of rep; coins with ≥ 1 reputable holder (θ = 0, N = 3) vs coins
with only non-reputable known holders vs coins with no known holder; ρ without warm-up decisions; how many distinct
wallets carry the scores.

## 9. Procedure by stage (`python research/lab2/x1.py --stage …`)

### History splits (the registry pool of each stage)

| Stage | Traded split | Registry history (eligible coins of) | Why |
|---|---|---|---|
| debug | `final_train` | `final_train` | debug only |
| train | `train` | `train` | the earliest split X1 may search; CONFIRM (earlier in time) is sealed |
| val | `val` | `train`, `val` | TRAIN is past and open |
| test | `test` | `train`, `val`, `test` | VAL had its look before TEST may run |
| confirm | `confirm` | `confirm` | nothing earlier exists; later splits would be the future |
| final | `final` (all census thirds) | `train`, `val`, `test`, `final` | TEST had its look before FINAL may run |

History splits other than the traded one are read with `common.coverage_dataset` (no guard): they feed the registry
and are **never traded or scored**. Each must pass the same coverage check as the traded split (complete, no future
SOL price); FINAL is exempt for its own end-of-data coins, as in M1.

### Every stage

A stage refuses unless: `X1/PREREG.md` exists and matches `prereg.lock` once locked; PLAN §8 rule 1 holds for the
traded split (`common.validation_gates`); coverage is complete (TRAIN alone may run `--allow-partial`, which is
PROVISIONAL: no shortlist, no lock, never unlocks VAL); the guarded splits have their flags (`LAB2_ALLOW_TEST`,
`LAB2_ALLOW_CONFIRM`, `LAB2_ALLOW_FINAL`). `x1.py` never sets them.

### TRAIN (all searching)

1. The persistence gate (§8). On KILL or UNDERPOWERED the grid is not run.
2. On PASS, run the 4 configs, each with the matched control (§10) and the stress runs.
3. **A config qualifies** if all hold: ≥ 30 trades; ≥ 3 distinct lead wallets; mean net > 0; mean without the top
   2 trades > 0; matched-control `mean_diff` > 0.
4. **Shortlist = one config:** the qualifying config with the highest coin-bootstrap 90 % CI lower bound (ties: higher
   mean, then θ = 0.10, then N_MIN = 6). Written with `common.write_shortlist`; frozen at the first VAL run.
5. Nothing qualifies: **NO_CONFIG** when a config had ≥ 30 trades, else **UNDERPOWERED_TRAIN**. X1 stops.
6. A decision on complete TRAIN is final; a re-run needs `--rerun-reason` naming a data correction (the old result is
   archived as `train_prev_<ts>.*`).

### VAL (the shortlisted config, once)

| Decision | Condition | Consequence |
|---|---|---|
| UNDERPOWERED_VAL | n < 5 | stop |
| FAIL_VAL | n ≥ 5 and (mean ≤ 0 or mean without the top 2 ≤ 0) | stop (PLAN §8 rule 7 input) |
| SELECTED_UNDERPOWERED | 5 ≤ n < 15, both > 0 | proceed, flagged |
| SELECTED | n ≥ 15, both > 0 | proceed |

### TEST (one run, `common.one_shot_session`)

- Verdict = `common.verdict_entry(test, val=VAL trades, min_mean=0.03)`: PLAN §3.5 items 1-8 with the default +3 %
  bar, plus the §3.6 auto-rejections. Item 9 (FINAL mean > 0) is judged in the overall verdict after FINAL.
- **Plus X1's extras** (one wallet's luck must not carry the result):

  | ID | Criterion | Blocking |
  |---|---|---|
  | X1.1 | power: ≥ 5 distinct lead wallets | yes (UNDERPOWERED) |
  | X1.2 | 90 % CI lower bound > 0 resampling lead wallets | yes |
  | X1.3 | mean > 0 without the trades of the most frequent lead wallet | yes |
  | X1.4 | beats the known-not-reputable control (§10): `mean_diff` > 0 | no (mechanism diagnostic) |

- Combination as M1: REJECTED if `verdict_entry` rejects; UNDERPOWERED if it is underpowered or X1.1 fails; FAIL if
  any blocking criterion fails; INCOMPLETE if one is missing; PASS otherwise. With a 1.3-day TEST, UNDERPOWERED is
  likely.

### CONFIRM (09-16 → 10-01; one run, never searched)

Precondition: TEST not REJECTED and (TEST mean > 0 or TEST n < 5). Same config, same verdict as TEST. The registry
warms up inside CONFIRM itself (§9 table); CONFIRM is the powered out-of-sample test.

### FINAL (the census day; after TEST)

One run on all census thirds (one session). **Criterion 9 is judged on `final_val` + `final_test` only**: the
`final_train` third was used to debug the code (§14), so its trades are reported apart.

### Overall X1 verdict

**EDGE** needs: gate PASS, VAL SELECTED(_UNDERPOWERED), TEST not REJECTED with (mean > 0 or n < 5), CONFIRM PASS and
FINAL mean > 0. Otherwise KILLED (gate), UNDERPOWERED (TRAIN, VAL or CONFIRM) or NO EDGE.

## 10. Controls

- **Matched random control** (PLAN §3.4, decides criterion 5 and the TRAIN `placebo_diff`): `common.backtest`'s
  placebo, 20 draws per signal, random **eligible** coins (class OTHER and alive at the draw) of the same split,
  decision age within ±120 s of the signal's, the same exits.
- **Known-not-reputable control** (X1.4, diagnostic): the same draw, restricted to eligible coins that have ≥ 1 known
  early holder under the config's N_MIN and **no** reputable one (registry read at the draw's own τ). It separates
  "the wallet's record" from "a repeat wallet is present at all".

## 11. Metric and statistics

- Unit: net return per $20 trade (`ret_net`), one entry per coin per config.
- Coin-bootstrap and 6-hour block-bootstrap CIs (10,000 / 5,000 draws, 90 % and 95 %), mean without the top 2, top-coin
  share, halves, $100 / 5-slot portfolio, costs × 1.5, the deflated Sharpe ratio over every trial in the ledger.
- **Lead-wallet clusters:** trades that share a lead wallet are one cluster for X1.2 and X1.3 (a grouping, never a
  feature).
- Warm-up: mean with and without warm-up decisions (§4 rule 8).

## 12. Kill criteria and declarations

| Rule | X1 |
|---|---|
| PLAN §8 rule 1 (data first) | V1-V4 for the traded split; stages refuse otherwise |
| Rule 2 (fills) | minute-bar worst fills with next-bar exits until the fill engine exists; if it finds them off by ≥ 1 point, the frozen config is re-run with replayed fills, no new search |
| Persistence gate (§8) | KILL stops X1 before any P&L |
| Rule 7 | FAIL_VAL is reported to the lead |
| Rule 8 | every config counts (§7) |

Declarations passed to `common.auto_rejections`:

```
uses_wallet_reputation = True
reputation_excludes_traded_coin = True
uses_organic_flow = False
uses_truncated_windows = False
uses_current_state_fields = False
```

## 13. Deviations from the PLAN, stated up front

| Area | Deviation |
|---|---|
| Registry source | B2 first-5-minute top-10 lists, not B3 positions or B1 trades (B3 is not built; B1 skips instant coins). The PLAN's reputation is the wallet's own realized P&L; X1's is the outcome a **follower** would have had on the wallet's picks, the quantity a follow rule needs |
| Skill thresholds | PLAN §6.6 rule 3 suggests > +0.2 with n ≥ 8; that is too rare for top-10 lists over 4 TRAIN days. X1 pre-registers θ ∈ {0, 0.10}, N_MIN ∈ {3, 6} |
| W1 stage 1 | asked at the coin level, causally (§8), not as a split-half wallet correlation |
| Splits | the lead's revised splits; the registry warms up inside TRAIN (and inside CONFIRM) |
| Fills | minute-bar worst fills, next-bar exits; no replayed fills |
| Pooled accounts | only `common.POOLED_ACCOUNTS`; the suspected one-bot PDA (`BwWK17cb…`) is kept as one entity |

## 14. Debug findings and expected sample (census TRAIN third, counts only)

**The run.** `python research/lab2/x1.py --debug` writes `X1/debug.md` and `X1/debug.json` (runtime ~3 s). Returns,
labels, skills and the gate statistic are hidden; its trials go to a scratch ledger, never to `trials.json`. **No
definition or parameter was changed after it.** By construction the signal and gate-group counts depend on labels
(reputation is built from outcomes), so they say a little about `final_train` outcomes; that third is never judged
(§9 FINAL).

| Count (450 usable coins created over 0.52 days) | Value |
|---|---:|
| Class at t_d: FACTORY / OTHER / OPERATOR | 183 / 233 / 34 |
| Eligible (OTHER and alive at g + 7-8 min) | 145 (88 OTHER coins were already dead: the ~17.6 SOL floor, or no volume) |
| Eligible coins with ≥ 1 early holder | 136 (4.2 holders per eligible coin) |
| Registry: early-holder wallets / entries | 552 / 613 |
| Wallets with ≥ 2 / ≥ 3 / ≥ 6 entries | 45 / 10 / 1 (the most for one wallet: 6) |
| Eligible coins with a holder known at the decision (n ≥ 3 / n ≥ 6) | 5 / 0 |
| Persistence-gate observations | 5 (need 200) |
| Signals, every config | 0 |

**What these counts imply, before any TRAIN data:**

- **12.5 hours is all warm-up.** A wallet needs 3 resolved eligible picks, each resolving about an hour after its
  decision. Among tradeable coins, early holders rarely repeat: 552 wallets for 145 coins.
- **The registry densifies with time (counts only).** Within eligible coins, wallets with ≥ 2 / ≥ 3 entries grew
  from 21 / 3 (first 81 eligible coins) to 34 / 9 (120) and 45 / 10 (145). The few regular holders appear on about
  0.02-0.04 of eligible coins. At ~280 eligible coins a day (if the census day is typical), TRAIN has ~1,100 eligible
  coins, enough for each regular holder to become known within hours and sit on ~20-45 coins. That is an
  extrapolation from one day: **whether TRAIN reaches 200 gate observations is unknown, and UNDERPOWERED_GATE (X1
  halts) is a plausible pre-registered outcome.**
- **Repeat early buyers live mostly in coins X1 excludes.** Over all usable coins, 1,271 holder wallets include 130
  with ≥ 3 entries and 66 with ≥ 6, against 10 and 1 among eligible coins: the repeats come mostly from FACTORY,
  OPERATOR and already-dead coins (bots and operator wallets). X1 keeps those coins out of the registry and the
  universe by design (§3: factory dumps, M1's domain, untradeable floors).
- **Later stages are denser.** VAL and TEST inherit TRAIN's registry (§9); CONFIRM warms up inside its 15 days.

| Expected eligible coins (census-day rate) | TRAIN (4 d) | VAL (1.5 d) | TEST (1.32 d) | CONFIRM (15 d) |
|---|---:|---:|---:|---:|
| Eligible coins | ≈ 1,100 | ≈ 420 | ≈ 370 | ≈ 4,200 |
| Signals | unknown (0 on the census third) | | | |

## 15. Commands

```bash
python research/lab2/x1.py --debug                                   # census TRAIN third: counts only
python research/lab2/x1.py --stage train [--allow-partial]           # gate, then the 4 configs, shortlist
python research/lab2/x1.py --stage val                               # the shortlisted config, once
LAB2_ALLOW_TEST=1 python research/lab2/x1.py --stage test            # judge only
LAB2_ALLOW_CONFIRM=1 python research/lab2/x1.py --stage confirm      # judge only, after TEST
LAB2_ALLOW_FINAL=1 python research/lab2/x1.py --stage final          # judge only, after TEST
python research/lab2/x1.py --stage <stage> --check                   # prerequisites only
python -m pytest -q research/lab2/tests/test_x1.py
```
