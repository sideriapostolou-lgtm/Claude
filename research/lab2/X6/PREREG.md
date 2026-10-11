# X6 pre-registration: buy the coins whose organic buyers take over when BOOST stops

- **Version:** `x6-v1`.
- **Written:** 2026-10-09, before any X6 run on TRAIN, VAL, TEST, CONFIRM or FINAL data. TRAIN was still being
  backfilled. Every constant, the whole grid (§6), the gate (§7), the controls (§9) and the decision rules (§8) were
  fixed in this file **before** the debug run on the census TRAIN third (§13). That run reports counts only: returns,
  gate labels, exit reasons and fill prices hidden, and no parameter chosen there.
- **Code:** `research/lab2/x6.py`, on the shared foundation `research/lab2/common.py` (every feature through
  `common.AsOf`). Tests: `research/lab2/tests/test_x6.py`.
- **Data:** `graduates`, `b2_coins`, `b2_bars` only (B2 minute bars to g + 180 min). No B1 trades, no B3 positions,
  no CryptoHouse queries.
- **Protocol:** PLAN §3 (shared protocol), §3.5 (entry pass bars), §3.6 (automatic rejections) and §8 (stop rules),
  through common.py's `backtest`, matched-timing placebo, `describe`, `verdict_entry`, trial ledger, shortlists and
  one-shot sessions. Stage gating and CLI follow `m1.py`.
- **Splits:** common.py's (TRAIN 10-01 → 10-05, VAL → 10-06 12:00, TEST → 10-07 19:37:30, CONFIRM 09-16 → 10-01,
  FINAL = the census day in its lab thirds; the census TRAIN third is debug only).
- **Freeze.** The first official TRAIN run hashes this file into `X6/prereg.lock`. After that, `x6.py` refuses every
  stage if this file changed. A change is a new version (`x6-v2`) in `X6/AMENDMENTS.md`, and its configs are new
  trials.
- **Amendment 1** (end of file, before any official TRAIN run, from debug **counts** only): the REPLACE level was
  dropped from the grid (it duplicated CONSTANT); the grid is 4 configs. Sections 3, 6, 7 and 13 carry the change.

## 1. Hypothesis and mechanism

**BOOST is a natural experiment that withdraws a mechanical bid at a known time.** On every 2026-10 graduate the
protocol's AGENT buys exactly 17.5845 SOL, fee-free, in 29-30 slices every 12 s, from g + 1-4 s to g + 330-353 s
(`research/flow/README.md`, AUDIT §3.2). It ignores price. While it runs, a coin's other buy flow mixes two things:

- **reflexive flow** that exists because the AGENT is lifting the price (momentum bots, migration buyers, holders who
  hold *because* it is rising), and
- **demand that does not depend on the AGENT** (people who want the coin).

When the AGENT stops, reflexive flow stops with it; demand does not. So a coin whose **non-AGENT buy rate in the K
minutes after the AGENT's last slice is at least its non-AGENT rate during BOOST**, with buyers absorbing every sell
(net inflow ≥ 0) and with as many distinct buyers as before, shows demand that survived the withdrawal of the bid. A
coin whose non-AGENT buying halves shows that its buying was reflexive ("flow dies").

**The claim tested.** Among slow graduates outside the operator and factory classes, the coins that pass this
takeover test at BOOST end + K minutes earn a net return above a $20 round trip over the next 30-60 minutes, and
above a random entry at the same age in the same kind of coin.

**Why it could beat costs** (round trip 1.4-5.1% of a $20 ticket by market cap, `common.round_trip_pct`; ~3.5-4.2%
on a fresh pool at 60-1,000 SOL):

1. **Order flow is persistent** (Lillo and Farmer 2004), and the post-BOOST minutes are the first in which a coin's
   own demand is visible without the protocol's bid on top of it.
2. **A constant-product pool turns persistent net inflow straight into price.** A net inflow ΔX on a pricing reserve
   X moves the price by ((X + ΔX) / X)² − 1. X6 requires ≥ 1 SOL per minute of non-AGENT buying. If only a tenth of
   that is net inflow for 30 minutes, ΔX = 3 SOL; on X ≈ 100 SOL that is +6%, above the round trip.
3. **Why the market may leave it.** Separating the AGENT's buys from everyone else's needs the BOOST fingerprint
   (12 s cadence, no sells, fee-free); screens show total volume and transaction counts, which BOOST's 29-30 slices
   inflate, and after BOOST every coin's volume falls. The within-coin comparison "non-AGENT rate after vs during
   BOOST" is not on any screen we know of.

**Who loses if it works:** curve holders who sell into the post-BOOST lull, and later buyers we sell to.

**Why it may fail (stated before any data).**

- **The first 30 minutes are where the losses are.** On the census day, random entries 0-30 min after graduation lost
  -10.0% per trade on slow graduates and -15.7% on instant ones (`docs/EXPERIENCE_GROUNDED.md` N5); the lab's rule is
  "no entries in the first 30 minutes". X6 enters at about g + 11-18 min **on purpose**, because that is where the
  mechanism lives. Its filter has to overcome a strongly negative baseline, and the matched placebo (§9) measures that
  baseline at the same age.
- **"Organic" is not identifiable on bars.** Bots, wash, MECH wallets, repeat migration buyers and pooled accounts are
  inside `b2_bars`. X6 removes only the AGENT, declares `uses_organic_flow = False` and calls the flow "non-AGENT".
- **Takeover flow may be exit liquidity.** Snipers and insiders still hold cheap curve inventory (S1's thesis); they
  sell into any demand, so a takeover coin may be exactly where they distribute next.
- **It may be momentum in disguise.** Net inflow ≥ 0 means the price did not fall after BOOST. Wave 1 found momentum
  entries lose before costs. The momentum control (§9) asks whether the rate, breadth and dispersion conditions add
  anything beyond "the price held after BOOST"; X6 must beat it.
- **Faster bots.** The persistence may be traded away before a 30 s order lands at the bar's high.

My prior that X6 passes TEST is about 5-10%.

**Not a duplicate.**

| Other test | What it does | Why X6 is different |
|---|---|---|
| M1 | rides one steady, price-ignoring bid (MECH-bar: ≤ 2 buyers in the quiet minutes, CV < 0.5) at ages ≥ 30 min, OPERATOR and OTHER coins | X6 is anchored to the **end** of the protocol's own mechanical bid and trades at g + 11-18 min. It excludes OPERATOR coins and requires breadth (≥ 3 buyers a minute, not falling) and dispersion (no minute > 50% of the window's buying), the opposite of a single-actor bid. MECH-bar needs 32 completed bars and cannot fire at any X6 decision |
| S1 | wallet-level insider inventory on B1 trades; `boost_absorb` = organic B − S during [g, g + 300] | X6 uses no wallet roles and no inventory, only bar flows, and measures the **change** in non-AGENT buying across the BOOST end |
| G1 | classifies coins at g + 2 min (a gate) | X6 reuses the M1 / G1 class rules only to exclude OPERATOR and FACTORY |
| D1 | buys dips (sell events) | X6 requires net inflow ≥ 0, never a dip |
| Z2 / X2 / Z1 / Y3 / X4 | one whale after g + 420 s / cross-sectional breadth rank at 30-60 min / seller exhaustion at 30-120 min / breakouts after g + 60 / the floor | none is anchored on the BOOST end or compares a coin with its own BOOST-time flow |

## 2. Data and instrument

1. **Bars.** `b2_bars` per clock minute: `buy_sol`, `sell_sol` (user side), `n_buyers` (wallets with ≥ 0.01 SOL of
   buys in the minute), `agent_buy_sol`, and the pool state. Bar 0 is the graduation minute (partial). Through
   `common.AsOf` a bar is visible once it has ended (τ = t − 20 s), and `agent_buy_sol` is NaN until the AGENT's 4th
   buy (`agent_known_at`).
2. **Non-AGENT flow.** Per minute: `org_buy` = `buy_sol` − `agent_buy_sol`, `org_buyers` = max(`n_buyers` −
   1[`agent_buy_sol` ≥ 0.01], 0). The AGENT buys every 12 s, so it is one of the minute's buyers in every BOOST minute.
3. **Universe of decisions.** `common.load` (SOL-quoted, not Mayhem, virtual reserve known, complete B2 window), plus:
   - **slow graduates only**: `grad_delay_s` > 5 s, or creation not scanned (`grad_delay_lb_s` = 1,800 s). Instant
     graduates are excluded by rule: 63% of them are factory coins, their airdrop dumps land at creation + 16 min,
     i.e. inside an X6 hold, and farm rugs land 13-24 min after graduation (EXPERIENCE N4, N5, G14; AUDIT §4). A
     slow graduate had a curve phase with its own buyers, the community that could take over;
   - **class OTHER** under the M1 / G1 rules (OPERATOR if w120 buy SOL ex-AGENT ≥ 500 and w120 buyers ex-AGENT ≤ 30;
     FACTORY if `grad_delay_s` ≤ 5 and the w120 top-5 share ex-AGENT ≥ 0.85; NULL inputs give NULL, which is
     skipped). OPERATOR coins are M1's; FACTORY coins are instant anyway;
   - **a measurable BOOST**: the AGENT was detected and BOOST lasted into bar 4 (§3).
4. **What is not used:** B1, B3, wallet identities, current-state fields, any column without a legality rule in
   common.py.

## 3. Features at the decision (all through `common.AsOf`)

Let m0 be the graduation minute's start and bar j = [m0 + 60j, m0 + 60j + 60).

| Feature | Definition |
|---|---|
| `j_w` | the last bar that starts before g + 420 s (the end of the AGENT window). BOOST is known to be over once bar `j_w` has completed (then τ ≥ g + 420 and the AGENT's presence is decided) |
| `j_b` | BOOST's last bar: the last bar j ≤ `j_w` with `agent_buy_sol` > 0. No AGENT, or no AGENT bar: no BOOST, coin skipped. An AGENT-wallet buy after the window never moves `j_b` |
| baseline bars | bars 3 … `j_b`: the BOOST minutes that lie entirely after the w120 migration burst (bar 3 starts after g + 120 s whatever the second of graduation). Fewer than 2 such bars (`j_b` < 4): coin skipped |
| `r_org_B`, `r_tot_B` | baseline `org_buy` and `buy_sol` (AGENT included) per minute |
| `nb_B` | baseline `org_buyers` per minute |
| post window | the K bars `j_b` + 1 … `j_b` + K, i.e. the first K minutes after BOOST's last slice |
| `r_P` | post-window `org_buy` per minute |
| `r_last` | `org_buy` per minute over the last ⌈K/2⌉ bars of the post window |
| `net_P` | Σ (`org_buy` − `sell_sol`) over the post window |
| `nb_P` | post-window `org_buyers` per minute |
| `top_P` | the largest post-window minute's `org_buy` / Σ `org_buy` (None when Σ = 0) |
| `alive` | `AsOf.alive()`: USD volume over 15 min ≥ $1,500 and market cap ≥ $6,000 |

**Decision time.** Exactly one decision per coin and K: the grid time at which bar `j_b` + K has just completed
(k = `j_b` + 1 + K completed bars), about g + 11 min for K = 5 and g + 16 min for K = 10. No decision after g + 25 min.

**TAKEOVER at level L** (threshold T: `CONSTANT` → T = `r_org_B`; `REPLACE` → T = `r_tot_B`, i.e. the non-AGENT
buyers alone now bid as much as the whole BOOST-era book did, AGENT included). All of:

1. **rate holds:** `r_P` ≥ T and `r_last` ≥ T (constant or rising over the whole window and in its second half, not a
   burst that already died);
2. **real size:** `r_P` ≥ 1.0 SOL per minute (about ten $20 tickets a minute; a third of BOOST's own ~3 SOL a minute);
3. **absorbing:** `net_P` ≥ 0 (buyers took every sell);
4. **breadth holds:** `nb_P` ≥ max(`nb_B`, 3);
5. **dispersed:** `top_P` ≤ 0.5 (no single minute, i.e. no single whale print, carries the window: not Z2);
6. `alive`.

REPLACE implies CONSTANT (`r_tot_B` ≥ `r_org_B`). **Only CONSTANT is traded** (amendment 1); REPLACE is computed
and reported. **DIES:** `r_P` < 0.5 × `r_org_B` (non-AGENT buying at least halved
after BOOST). **MIDDLE:** every other decision. DIES and MIDDLE are used only by the gate (§7) and the reports.

## 4. Entry rule

At the coin's decision (§3), once per coin and config: if TAKEOVER (level CONSTANT) holds, buy $20; otherwise
never trade this coin under this config (`SKIP`). Before the decision the strategy waits; a coin outside the universe
(§2.3) is skipped as soon as that is knowable (at the end of bar `j_w`).

## 5. Exits (relative to the entry fill; fills per §6)

| Exit | Rule |
|---|---|
| Stop | −30% from the entry fill. Fresh coins gap through any stop; a rug costs what it costs (worst, next-bar fill) |
| `hold30` | time exit 30 min after landing |
| `fade60` | at a decision with ≥ 3 completed bars after the entry decision: `org_buy` over the last 3 completed bars < 0.5 × 3 × the entry `r_P` **and** net flow (`org_buy` − `sell_sol`) over them < 0 → sell (the takeover ended and sellers dominate; EXPERIENCE G31). Time cap 60 min after landing |
| Registered deadline | sell no later than g + 178 min (`exit_by_age_s`). Entries end by g + 25 min and holds by +60 min, so it never binds and no trade can end on the data horizon |

**Placebo positions** carry no state: their reference `r_P` is recomputed as the `org_buy` per minute over the K bars
before their own decision, the same formula the signal used, so they run the same fade rule.

## 6. The TRAIN grid: exactly 4 configurations, every one a trial

**K ∈ {5, 10} × exit ∈ {`hold30`, `fade60`}**, level CONSTANT (amendment 1; the first draft also crossed level ∈
{CONSTANT, REPLACE}, 8 configs).

| Dimension | Why each value |
|---|---|
| K = 5 / 10 | how long the takeover must persist before we believe it; longer is more evidence and a later, dearer entry |
| `hold30` / `fade60` | a plain hold against the thesis exit that leaves when the takeover ends |

Every constant of §2-§5, the fill model and the version are inside each config's params, so any change is a new
trial. **X6's trials:** 4 configs + 1 gate (`X6-sep`, §7) = **5 at most**, on top of the ledger's count. If the gate
passes only one K, only that K's 2 configs run (unrun configs are no trials). TEST, CONFIRM and FINAL run the single
VAL candidate inside the family's one `common.one_shot_session`.

**Fills and costs** (`common.FillConfig(exit_delay_bars=1)`):

| Setting | Value |
|---|---|
| Size | $20 |
| Latency | 30 s: the order lands in the bar after the decision |
| Entry fill | worst: max(open, high) of the landing bar |
| Exits | **next bar**: a stop, time or fade exit triggered in bar j fills at min(open, low) of bar j + 1 |
| Entry-bar stop | on (the stop is checked against the entry bar too) |
| Costs | PumpSwap tier by date and market cap, + 10 bps Ultra, + 20 bps buffer, impact on the pool's own k, network fees |

**Stress runs** from the same call, never used to select: costs × 1.5; rent $0.22; same-bar exits; latency 60 s.

## 7. Separation gate (TRAIN, before any P&L; a stop rule)

- **Observations.** For each K: every universe coin (§2.3) at its decision (§3) that is `alive` and whose 30-minute
  label lies inside the data. One observation per coin and K.
- **Groups.** TAKEOVER (level CONSTANT, conditions 1-5), DIES, MIDDLE.
- **Label** (an outcome, never a feature): the realized 30-minute mid-price change, close(τ + 30 min) / close(τ) − 1,
  read through AsOf 30 minutes later.
- **Per K:**

  | Result | Condition |
  |---|---|
  | UNDERPOWERED | fewer than 30 TAKEOVER coins or fewer than 30 DIES coins |
  | PASS | mean(TAKEOVER) − mean(DIES) ≥ +5 points, the 90% CI of that difference above 0 (coins resampled within each group, 2,000 draws), **and** mean(TAKEOVER) > 0 |
  | FAIL | powered, not PASS |

- **X6:** **KILL** when no K passes and at least one FAILs (the takeover carries no forward information; the grid is
  never run; every later stage refuses). **UNDERPOWERED** when no K passes and none fails (halt). Otherwise the grid
  runs **only for the passing K**.
- **Reported, never decisive:** medians; the means winsorized at 5-95%; MIDDLE; the REPLACE subset; the "momentum"
  subset (`net_P` ≥ 0, not TAKEOVER).

## 8. Procedure by stage (`python research/lab2/x6.py --stage …`)

### Every stage

A stage refuses unless: `X6/PREREG.md` exists (and matches `prereg.lock` once locked); PLAN §8 rule 1 holds for the
split (`common.validation_gates`); the split's coverage is complete (every chain hour scanned, no mid-run B2 hour,
≤ 5% of tradeable coins missing B2, a SOL/USD series that starts before the coins; FINAL's end-of-data coins are
reported, not blocking); the guarded splits have their flags (`LAB2_ALLOW_TEST`, `LAB2_ALLOW_CONFIRM`,
`LAB2_ALLOW_FINAL`), which `x6.py` never sets.

### TRAIN (all searching)

1. The gate (§7).
2. On PASS, the configs of the passing K, each with the matched placebo, the controls (§9) and the stress runs.
3. **Shortlist rule.** A config qualifies when, on TRAIN: ≥ 30 trades from ≥ 30 coins; mean net > 0; mean without the
   top 2 trades > 0; matched-placebo `mean_diff` > 0; momentum-control `mean_diff` > 0; censored share ≤ 10%. Rank the
   qualifiers by the coin-bootstrap 90% CI lower bound (ties: higher mean, then grid order). **Shortlist = the top 2**
   (`common.write_shortlist`, frozen at the first VAL run).
4. Nothing qualifies: **NO_CONFIG** if some config had ≥ 30 trades from ≥ 30 coins, else **UNDERPOWERED_TRAIN**. X6
   stops.
5. A decision on complete TRAIN is final; a re-run needs `--rerun-reason` naming a data correction (the previous
   result is archived). `--allow-partial` runs a **provisional** TRAIN (`train_prelim.*`): no shortlist, no lock, no
   VAL.

### VAL (both shortlisted configs, once; a filter, never a ranking)

Per config: **UNDERPOWERED_VAL** n < 5; **FAIL_VAL** n ≥ 5 and (mean ≤ 0 or mean without the top 2 ≤ 0);
**SELECTED_UNDERPOWERED** 5 ≤ n < 15 and both > 0; **SELECTED** n ≥ 15 and both > 0. The candidate is the TRAIN rank-1
config if it proceeds, else rank 2. If neither proceeds, X6 stops (FAIL_VAL if either failed, else UNDERPOWERED_VAL).

### TEST (the candidate, once)

- **Verdict** = `common.verdict_entry(test, val=VAL candidate, min_mean=0.03)`: PLAN §3.5 items 1-8 and 10 (censoring)
  plus the §3.6 auto-rejections, **plus X6.1**: the candidate beats the momentum control (`mean_diff` > 0), blocking.
- **How they combine:** REJECTED if `verdict_entry` rejects; UNDERPOWERED if item 1 fails; FAIL if any item or X6.1
  fails; INCOMPLETE if any is missing or > 10% of trades are censored; else PASS. Item 9 (FINAL mean > 0) is judged in
  the overall verdict once FINAL ran.
- With a 1.3-day TEST, UNDERPOWERED is likely.

### CONFIRM (09-16 → 10-01; once, never searched)

Precondition: TEST not REJECTED, and TEST mean > 0 or TEST n < 5 (no evidence either way). Same verdict as TEST.

### FINAL (the census day)

Only after TEST. The candidate once on all of FINAL (one `common.one_shot_session`). **Criterion 9 is judged on the
census VAL and TEST thirds only**; the TRAIN third hosted the debug run and is reported apart.

### Overall X6 verdict

**EDGE** requires: the gate PASS; a qualifying TRAIN config; VAL SELECTED or SELECTED_UNDERPOWERED; TEST not REJECTED
and (TEST mean > 0 or n < 5); CONFIRM PASS; FINAL mean > 0. Otherwise **KILLED**, **UNDERPOWERED** (at the stage that
was) or **NO EDGE**.

## 9. Controls

All from the same `common.backtest` call (20 draws per signal, decision age within ±120 s of the signal's, same exits,
same split):

| Control | Eligible draws | Use |
|---|---|---|
| **matched placebo** | universe coins (§2.3: slow, OTHER, measurable BOOST), BOOST over (bar `j_w` completed), `alive` | PLAN §3.5 item 5 (≥ +6 points); TRAIN qualification (> 0) |
| **momentum** | the matched placebo's coins with net non-AGENT flow ≥ 0 over the K bars before the drawn decision | X6.1 (> 0, blocking on TEST / CONFIRM; TRAIN qualification). Does takeover add anything beyond "the price held after BOOST"? |
| **unmatched** | any usable coin | reported, never judged |

## 10. Metric and statistics

- The unit is the net return per $20 trade (`ret_net`), one entry per coin per config.
- Coin-bootstrap CIs (10,000 draws, 90% and 95%) and the 6-hour block bootstrap (`common.describe`).
- Also reported: mean without the top 2 trades; top-coin share; halves; the $100 / 5-slot portfolio; the stress runs;
  the deflated Sharpe ratio counting every trial in the ledger; entry ages; the decision's `r_P / r_org_B` and
  `nb_P`; censored share.

## 11. Kill criteria and declarations

| Rule | How X6 applies it |
|---|---|
| Stop rule 1 (data first) | V1-V4 must pass per split; stages refuse otherwise |
| Stop rule 2 | minute-bar worst fills with next-bar exits until X1's replayed fills exist. If they differ by ≥ 1 point, the frozen candidate is re-run with replayed fills, no new search |
| Gate (§7) | KILL stops X6 before any P&L |
| Stop rule 7 | FAIL_VAL is reported to the lead |
| Stop rule 8 | every config counts (§6) |

**Declarations passed to `auto_rejections`:** `uses_organic_flow = False` (the flow is non-AGENT, not organic),
`uses_wallet_reputation = False`, `uses_truncated_windows = False`, `uses_current_state_fields = False`.

## 12. Deviations from the PLAN, stated up front

| Area | Deviation |
|---|---|
| Entry age | X6 enters at g + 11-18 min, inside the lab's "no entries in the first 30 min" window; the placebo at the same age measures that baseline |
| "Organic" | non-AGENT bar flow; bots, wash, MECH and pooled accounts stay inside it |
| Fills | minute-bar worst fills with next-bar exits, not replayed fills |
| Universe | slow graduates and class OTHER only (§2.3) |
| SOL/USD | stages refuse while the series starts after the split's coins (`common.coverage_problems`) |

## 13. Debug run (census TRAIN third, counts only)

`python research/lab2/x6.py --debug` writes `X6/debug.md` and `X6/debug.json`. Its trials go to a scratch ledger
(`scratchpad/lab2_debug/x6_debug_trials.json`), never to `trials.json`. Returns, gate labels, exit reasons and fill
prices are hidden. No threshold, window or exit was changed because of these counts; the one structural change is
amendment 1.

**Structure** (450 usable coins over 0.52 days):

- Universe funnel: 277 instant graduates excluded, **173 in the universe** (every slow coin was class OTHER, had a
  detected AGENT and a BOOST reaching bar 4).
- BOOST's last bar `j_b`: bar 5 on 155 coins, bar 6 on 290, bar 7 on 5 (as documented: last slice at g + 330-353 s).
  Baseline bars: 3 on 40 universe coins, 4 on 128, 5 on 5.
- **BOOST is a small part of the BOOST-time bid**: non-AGENT buying during BOOST (bars 3 … `j_b`) has a median of
  24 SOL per minute (p25 8.4, p75 62) from a median of 62 buyers per minute, against the AGENT's ~3 SOL per minute.
- At the K = 5 decision (g + 11.2-12.1 min) only **96 of 173** universe coins are `alive`: the rest already sit at
  the ~17.6 SOL price floor (market cap < $6k), as the census-day finding (147 of 450 coins at the floor 10 min after
  graduation) predicts. At K = 10 (g + 16.2-17.1 min): 75 of 173.
- Non-AGENT buying usually falls after BOOST: the post / BOOST rate ratio has median 0.60 at K = 5 (p75 0.87, p90
  1.49) and 0.57 at K = 10.

**Group counts at the decision (alive coins only):**

| K | alive | TAKEOVER | (REPLACE subset) | DIES | MIDDLE | momentum (net ≥ 0, not TAKEOVER) |
|---:|---:|---:|---:|---:|---:|---:|
| 5 | 96 | 6 | 5 | 38 | 52 | 30 |
| 10 | 75 | 4 | 4 | 31 | 40 | 31 |

Conditions passed (of 173 decisions): rate 21 / 13 (K = 5 / 10), size 126 / 122, absorb 41 / 41, **breadth 22 / 19**,
dispersed 99 / 116, alive 96 / 75. The rate and breadth conditions bind.

**Entries and expected samples** (extrapolations assume the other days look like the census day):

| Config | Census TRAIN third (0.52 d) | Per day | TRAIN (4 d) | VAL (1.5 d) | TEST (1.32 d) | CONFIRM (15 d) |
|---|---:|---:|---:|---:|---:|---:|
| K = 5 (`hold30`, `fade60`) | 6 | ≈ 11.5 | ≈ 46 | ≈ 17 | ≈ 15 | ≈ 173 |
| K = 10 (`hold30`, `fade60`) | 4 | ≈ 7.7 | ≈ 31 | ≈ 12 | ≈ 10 | ≈ 115 |
| DIES coins (gate contrast) | 38 / 31 | ≈ 73 / 60 | ≈ 290 / 240 | | | |

**What these counts imply, before any TRAIN data:**

- **The gate is powered for K = 5 and borderline for K = 10** (≥ 30 TAKEOVER coins needed; ≈ 46 and ≈ 31 expected).
- **TEST will be UNDERPOWERED** (≈ 15 trades against the 60-trade bar). The powered out-of-sample test is CONFIRM
  (≈ 115-173 trades).
- TAKEOVER is rare (6 of 96 alive coins at K = 5): if it carries information, it is about a small minority of slow
  graduates; most coins' non-AGENT buying falls when BOOST stops.
- Debug placebo draws: 20 per signal for the matched placebo and the unmatched control; 113 of 120 for the momentum
  control (fewer eligible coins).

## Amendment 1 (2026-10-09, after the debug run, from counts only; before any official TRAIN run, no `prereg.lock`)

**Change.** The REPLACE level is removed from the grid; the traded level is CONSTANT. The grid shrinks from 8 configs
(K × level × exit) to **4** (K × exit); X6's trial budget from 9 to **5**. REPLACE is still computed and reported (gate
table, debug counts).

**Why.** The REPLACE threshold is the CONSTANT threshold plus the AGENT's rate. The PLAN already reported that BOOST is a
median 3.4% of first-minutes pool buying; the debug counts confirm that the BOOST-time non-AGENT bid (median 24 SOL a
minute) dwarfs the AGENT's ~3 SOL a minute, so the two levels almost coincide: 5 of 6 TAKEOVER coins at K = 5 and 4 of 4
at K = 10 pass both. Keeping REPLACE would add 4 near-duplicate configs: trials that cost deflated-Sharpe budget and add
a choice between nearly identical trade sets. The change uses condition counts only (no return, label, exit reason or
fill price was seen), removes options and adds none.
