# Y5 pre-registration: a causal calendar gate (UTC session and day type) on two simple hosts

- **Version:** `y5-v1`.
- **Written:** 2026-10-09, before any run on TRAIN, VAL, TEST, CONFIRM or FINAL data. TRAIN was still being
  backfilled (69 % of its chain hours scanned at writing). The only run so far is the debug run on the census TRAIN
  third (§13): counts only, returns hidden.
- **Code:** `research/lab2/y5.py`, on the shared foundation `research/lab2/common.py`. Tests:
  `research/lab2/tests/test_y5.py`.
- **Protocol:** PLAN §3 (shared protocol: splits, fills, statistics, §3.5 pass bars, §3.6 auto-rejections) and §8
  (stop rules), with the lab2 splits (TRAIN 10-01 → 10-05, VAL 10-05 → 10-06 12:00, TEST 10-06 12:00 → 10-07 19:37,
  CONFIRM 09-16 → 10-01, FINAL = census day).
- **Freeze.** The first official TRAIN run hashes this file into `Y5/prereg.lock`. After that, `y5.py` refuses every
  stage if this file has changed. Any change is a new version (`y5-v2`) recorded in `Y5/AMENDMENTS.md`, and every
  config it adds counts as new trials.

## 1. Mechanism, why it could beat costs, and why it probably will not

**Claim.** After BOOST and the first insider exits (g + 30 min), a pump.fun graduate's price path depends on whether
new marginal buyers keep arriving. Those buyers are people, and people follow their regional clock: the Asian, European
and American retail cohorts are awake and trading in different UTC hours. If the supply of fresh graduates (the
competition for those buyers' attention) does not scale one-for-one with the buyer cohort that is awake, then the
**per-coin arrival rate of new buyers differs by session**, and so does the expected drift of a coin bought at
g + 30 min. A calendar gate is causal by construction: the clock at the decision time is known exactly, uses no market
data and cannot leak.

- **Who pays:** in the thin session, holders who need to sell into fewer arriving buyers; in the rich session, late
  buyers who arrive after the gate's entry.
- **Why it could beat costs.** A gate does not create return; it selects the host's trades. It beats the $20 round
  trip (1.4-5.1 % by market cap, `common.round_trip_pct`) only if the host's mean inside the gated sessions is above
  about +3 % net. The census-day random-entry reference was about −6.4 % per trade (`research/lab/RESULTS.md`), so a
  session must carry a premium of roughly +9 points over the host's average to pass. That is the size of edge this
  test can detect (PLAN §3.5 item 5: ≥ +6 points over the matched control).
- **Why it probably will not.** (a) Graduation supply itself follows the clock (more coins graduate when more buyers
  are awake), which cancels the per-coin effect. (b) Wave 1 found by-hour means swinging from −59 % to +26 % with no
  pattern that held across splits, and an hourly intraclass correlation of about 0 (`research/lab/RESULTS.md`; craft
  rule G37 in `docs/EXPERIENCE_GROUNDED.md`: "trade the US session" is weakly contradicted). **The expected answer is
  NO EDGE.** The useful by-product is a measured session premium with honest uncertainty, which settles the bot's
  "trade the US session" folklore either way.

## 2. Instrument: the calendar, as of the decision time t

The clock is the **UTC time of the decision t** (minute boundary + 20 s on common.py's grid). Nothing else is read.
The feature cutoff τ = t − 20 s does not apply to the clock: the clock is always known.

**Sessions** (a partition of the 24 UTC hours into three 8-hour blocks; each is a region's local working day; all data
09-16 → 10-08 lies inside both US and EU summer time, which end 2026-11-01 and 2026-10-25):

| Session | UTC hours | Local time |
|---|---|---|
| **ASIA** | [00:00, 08:00) | 08:00-16:00 Beijing / Hong Kong / Singapore (UTC+8), 09:00-17:00 Tokyo / Seoul (UTC+9) |
| **EU** | [08:00, 16:00) | 09:00-17:00 London (BST, UTC+1), 10:00-18:00 Berlin / Paris (CEST, UTC+2) |
| **US** | [16:00, 24:00) | 12:00-20:00 New York (EDT, UTC−4), 09:00-17:00 Los Angeles (PDT, UTC−7) |

The boundaries are the natural 8-hour partition, not tuned. Known overlap: US late evening (20:00-24:00 New York) falls
in the ASIA block.

**Day type:** WEEKEND = Saturday or Sunday (UTC date of t); WEEKDAY otherwise.

## 3. Hosts

### 3.1 R30: alive entry at g + 30 min (the powered host)

- At the first decision time t with t − g ≥ 30 min: enter if the coin is **alive** (`AsOf.alive()`: USD volume over
  the last 15 completed minutes ≥ $1,500 and market cap ≥ $6,000), otherwise never trade the coin (SKIP).
- One entry per coin. No signal: the entry is a "random" entry at a fixed age, the lab's R0 idea at a fixed age so
  that the clock, not the age, is the only thing the gate varies.
- **Exits:** catastrophe stop −50 % and a 60-minute time exit (PLAN X1 exit 6, as G1's R0 host), and a registered
  deadline of g + 178 min (never binds).

### 3.2 M1: the mechanical-bid host (present at writing)

- `m1.strategy` with `m1.make_params(1.0, "rhythm+prec")`: M1 version `m1-v1`, params hash `9c0a14afb895`. m = 1 is
  the PLAN's lowest drift-over-cost bar (the most entries); `rhythm+prec` is M1's own candidate exit set.
- This is **fixed now**, not taken from M1's TRAIN selection, so that Y5 never inherits a search on TRAIN outcomes.
- `y5.py` refuses every stage if `m1.VERSION` or that params hash changes (the host would no longer be the registered
  one).
- M1's entries mostly come from one operator cluster (M1 PREREG §13). A calendar gate on M1 therefore largely measures
  one operator's daily schedule. Y5 keeps M1's cluster checks for M1-host candidates (§9, Y5.3).

### 3.3 x6 (post-BOOST organic takeover): not a host in y5-v1

`research/lab2/x6.py` did not exist when this file was first written; it appeared at 03:30 UTC, after Y5's grid was
fixed and while its debug ran. It is **not** a y5-v1 host, for three reasons that do not depend on any outcome:

1. **Power.** X6's own debug run (census TRAIN third) made 4-6 entries in 0.52 days, about 8-12 a day, so about 3-4 per
   session-day. A session-gated X6 config would hold about 12-16 trades on TRAIN, far under the 60-trade bar. Its
   configs could never qualify: they would be padding.
2. **The 12-config cap.** X6 would need at least 4 configs (3 sessions + its ungated comparator), taking Y5 to 15.
3. **It is still moving.** X6 had not run TRAIN, its own pre-P&L gate can KILL it before any trade, and its grid was
   still changing. A pinned host must be frozen.

Adding X6 as a host is a new version (`y5-v2`) once X6's shortlist is frozen, with its own counted configs.

## 4. The gate is a filter

When the host returns an entry at decision time t and the session of t is **not** in the config's session set, the
gated strategy returns SKIP: the coin is never traded. The gate never delays an entry into a later session (that would
change the entry age and confound age with the clock). So **every gated config's trades are exactly the subset of its
host's trades whose decision time lies in the set** (tested). Exits pass through to the host unchanged.

## 5. Fills and costs

`common.FillConfig(exit_delay_bars=1)` for every config:

| Setting | Value |
|---|---|
| Size | $20 |
| Latency | 30 s |
| Entry fill | `"worst"`: the max of the landing bar's open and high |
| Exit fill | `"worst"`: the min of open and low |
| Mechanical exits | a stop or time exit triggered in bar j fills at the adverse side of bar j + 1 (next-bar exits) |
| Entry-bar stop checks | on |
| Costs | PumpSwap tier by date and market cap, + 10 bps Ultra, + 20 bps buffer, network fees, impact on the pool's own k = X·y |

**Stress and sensitivity runs** come from the same call and are never used to select: costs × 1.5; rent $0.22;
same-bar exits (`exit_delay_bars=0`); open fills.

## 6. The grid: exactly 11 configurations, every one a trial

| # | Config | Host | Sessions | Role |
|---:|---|---|---|---|
| 1 | `R30\|ASIA` | R30 | ASIA | candidate |
| 2 | `R30\|EU` | R30 | EU | candidate |
| 3 | `R30\|US` | R30 | US | candidate |
| 4 | `R30\|ASIA+EU` | R30 | ASIA, EU (= avoid US) | candidate |
| 5 | `R30\|ASIA+US` | R30 | ASIA, US (= avoid EU) | candidate |
| 6 | `R30\|EU+US` | R30 | EU, US (= avoid ASIA) | candidate |
| 7 | `R30\|ALL` | R30 | all (ungated) | comparator, never a candidate |
| 8 | `M1\|ASIA` | M1 | ASIA | candidate |
| 9 | `M1\|EU` | M1 | EU | candidate |
| 10 | `M1\|US` | M1 | US | candidate |
| 11 | `M1\|ALL` | M1 | all (ungated) | comparator, never a candidate |

- **Why both singletons and pairs on R30.** The sign is unknown a priori (§1: attention vs competition). "Session b is
  better" gives the singleton; "session b is worse" gives the pair that avoids it. On M1 the pairs are omitted: M1 is
  thin per session and dominated by one operator, and 3 more correlated trials would buy nothing.
- **Why the ungated hosts are configs.** Their returns are looked at (the host-relative comparison, §7), so they are
  trials. They can never be shortlisted as a candidate: an edge of the ungated host is not a calendar effect (and R30
  itself is G1's R0 question).
- **Weekday is not a gate dimension, on purpose.** VAL (Mon-Tue), TEST (Tue-Wed) and FINAL (Wed-Thu) contain **no
  weekend coin**. A "weekend" config gets 0 trades on every holdout, and a "weekdays only" config is identical to its
  session config there; both would be padding that can never pass. Day type enters as a pre-registered **conditioning
  check** instead (§8 TRAIN rule: the effect must hold on TRAIN's two weekdays and on its two weekend days
  separately) and is reported at every stage (CONFIRM holds 11 weekdays and 4 weekend days).
- Each config's params dict carries the version, the host and its full params (incl. M1's version and hash), the
  session set and bounds, the fill model and the exits. Any change is a new trial.
- **Y5's total is 11 trials**, on top of the ledger in `research/lab2/trials.json`. Debug runs never count.

## 7. Controls

1. **Matched-timing random control** (PLAN §3.4, `common.backtest`'s placebo): 20 draws per signal, random coins of the
   same split at a decision age within ±120 s of the signal's, same exits, **at any clock time**. This is exactly the
   calendar null: "the same kind of entry at the same age, but not chosen by the clock".
   - R30 configs: placebo coins must be alive at their decision.
   - M1 configs: M1's own class-matched control (allowed class and alive, same M1 class); the unmatched control (any
     allowed class) is reported next to it, never judged.
2. **Host-relative comparison** (`host_rel_diff`): mean net return of the config's trades minus the mean of its own
   host's trades **outside** the config's session set (from the ungated host's run on the same split). This is the
   calendar effect on the host itself, free of the placebo's coin mix. For R30 the two controls nearly coincide.
3. **Veto by-product (reported, never decisive for EDGE):** `common.verdict_veto` (PLAN §3.5 veto bar) on the host's
   trades with "flagged" = in a given session (TRAIN: every session, descriptive; VAL/TEST: the sessions the shortlisted
   candidate avoids, with TEST as the out-of-sample half).

## 8. Procedure by stage (`python research/lab2/y5.py --stage …`)

### Every stage

A stage refuses to run unless:

- `Y5/PREREG.md` exists, and matches `prereg.lock` once locked;
- the M1 host is the registered one (`m1.VERSION` = `m1-v1`, params hash `9c0a14afb895`);
- PLAN §8 rule 1 holds for the split (`common.validation_gates`: V1-V4 on the split's dates);
- the split's coverage is complete (every chain hour scanned for curve and B2, no mid-run B2 hour, ≤ 5 % of tradeable
  coins without a complete B2 window, SOL/USD covering the split). FINAL is exempt from the completeness check, never
  from the SOL/USD check;
- the guarded splits have their flags (`LAB2_ALLOW_TEST`, `LAB2_ALLOW_CONFIRM`, `LAB2_ALLOW_FINAL`); `y5.py` never sets
  them.

### TRAIN (all searching; the 11 configs)

1. Run all 11 configs, each with its placebo, the stress runs and a ledger entry.
2. A **candidate** config (1-6, 8-10) **qualifies** when every one of these holds on TRAIN:

   | Requirement | Bar |
   |---|---|
   | Sample | ≥ 60 trades from ≥ 40 coins (PLAN §3.5 item 1); M1-host configs also ≥ 3 operator clusters (`m1.cluster_table`) |
   | Mean net | > 0 |
   | Mean without the top 2 trades | > 0 |
   | Matched-control `mean_diff` | > 0 |
   | Host-relative diff (§7.2) | > 0 |
   | **Day-type conditioning** | on WEEKDAY trades and on WEEKEND trades separately: ≥ 20 trades each, and the per-signal mean of (trade − its placebo mean) > 0 in each |
   | Censored (closed by the data horizon) | ≤ 10 % |

3. **Rank** the qualifiers by the coin-bootstrap 90 % CI lower bound of the mean (higher first); ties go to the higher
   mean, then to the registry order of §6.
4. **Shortlist = the pair** (rank-1 candidate, its ungated host), written with `common.write_shortlist` and frozen at
   the first VAL run. The host rides along so VAL and TEST can measure the host-relative diff and the veto by-product.
5. If nothing qualifies: **NO_CONFIG** when at least one candidate met the sample bar, **UNDERPOWERED_TRAIN** otherwise.
   Y5 stops before VAL.
6. **A decision on complete TRAIN is final.** A re-run needs `--rerun-reason` naming a data correction; the previous
   result is archived as `train_prev_<ts>.*`. `--allow-partial` runs a **PROVISIONAL** TRAIN on partial data: it
   writes `train_prelim.*`, never a shortlist or a lock, and never unlocks VAL.

### VAL (the pair, once)

| Decision | Condition on the candidate's VAL trades | Consequence |
|---|---|---|
| **UNDERPOWERED_VAL** | n < 5 | stop |
| **FAIL_VAL** | n ≥ 5 and (mean ≤ 0, or mean without the top 2 ≤ 0, or host-relative diff ≤ 0 or undefined) | stop (PLAN §8 rule 7 input) |
| **SELECTED_UNDERPOWERED** | 5 ≤ n < 15, and none of the above | proceed, flagged |
| **SELECTED** | n ≥ 15, and none of the above | proceed |

### TEST (one look for the family; the pair inside one `common.one_shot_session`)

- **Base verdict** = `common.verdict_entry(test, val=VAL candidate, min_mean=0.03)`: PLAN §3.5 items 1-8 and 10 (item
  3 = 90 % CI lower bound > 0 under the coin AND the 6-hour block bootstrap) plus the §3.6 auto-rejections. Item 9
  (FINAL mean > 0) is judged in the overall verdict after FINAL.
- **Y5 extras:**

  | ID | Criterion | Missing value |
  |---|---|---|
  | Y5.1 | Host-relative diff ≥ +6 points (PLAN's control margin, against the host's own out-of-set trades) | blocking (INCOMPLETE) |
  | Y5.2 | **Not one session-day.** Let D = the UTC dates (of t) with ≥ 10 candidate trades. Need D ≥ 2, and the per-signal mean of (trade − its placebo mean) > 0 on at least ⌈2D/3⌉ of them | blocking (INCOMPLETE) when D < 2 |
  | Y5.3 | M1-host candidates only: ≥ 3 operator clusters among the trades, and mean > 0 without the largest cluster | not applicable to R30 |

  Y5.2 exists because the sampling unit of a calendar effect is the session-day, not the coin: one session spans one
  or two 6-hour blocks a day, so with 2-3 blocks the block bootstrap of item 3 is lenient. A calendar effect seen on a
  single day is that day's news.
- **Combination:** REJECTED if `verdict_entry` rejects; UNDERPOWERED if item 1 fails; FAIL if any judged criterion or
  extra fails; INCOMPLETE if any is missing (blocking) or > 10 % of trades are censored; PASS otherwise.
- With a 1.3-day TEST, an ASIA candidate has one session-day (10-07): **INCOMPLETE at best, by design.** CONFIRM is the
  powered test.

### CONFIRM (09-16 → 10-01; one run, never searched)

- **Precondition:** TEST not REJECTED, and either TEST mean > 0 or TEST n < 5 (no evidence either way). Otherwise Y5
  failed TEST and CONFIRM is not spent.
- The same pair, the same verdict as TEST. Reported apart: the candidate's WEEKDAY vs WEEKEND results (4 weekend days).

### FINAL (the census day; after TEST)

- The pair once on all of FINAL (one `common.one_shot_session`). **Criterion 9 (FINAL mean > 0) is judged on the
  census VAL and TEST thirds only**: the TRAIN third hosted the debug run (§13), so its trades are reported apart.

### Overall Y5 verdict

**EDGE** requires: a shortlist on complete TRAIN; VAL SELECTED or SELECTED_UNDERPOWERED; TEST not REJECTED and (TEST
mean > 0 or n < 5); the CONFIRM verdict PASS; FINAL mean > 0. Otherwise **UNDERPOWERED** (TRAIN, VAL or CONFIRM) or
**NO EDGE**.

## 9. Metric and statistics

- The unit is the net return per $20 trade (`ret_net`), one entry per coin per config.
- `common.describe`: mean, median, win rate, coin-bootstrap 90/95 % CIs (10,000 draws), 6-hour block-bootstrap CIs,
  top-coin share, mean without the top 2 trades, chronological halves, censored share, deflated Sharpe ratio counting
  every trial in the ledger, the $100 / 5-slot portfolio.
- Y5 adds: per-session and per-day-type means of every config and its placebo diff, `host_rel_diff` with a
  coin-bootstrap 95 % CI, the session-day table (Y5.2), operator clusters for M1-host configs, and the cost
  decomposition (gross move at worst fills vs costs).
- **Not reported, on purpose:** hour-by-hour means. 24 hourly means are a fishing net; only the three registered
  sessions are evaluated. Hourly **counts** are reported.

## 10. Kill criteria (PLAN §8) and declarations

| Rule | How Y5 applies it |
|---|---|
| Stop rule 1 (data first) | V1-V4 per split; stages refuse otherwise |
| Stop rule 2 | Minute-bar worst fills with next-bar exits until X1 exists; if X1 finds them off by ≥ 1 point, the frozen pair is re-run with replayed fills, with no new search |
| Stop rule 7 | FAIL_VAL is reported to the lead |
| Stop rule 8 | Every config counts (§6) |

Declarations passed to `auto_rejections`: `uses_organic_flow = False`, `uses_wallet_reputation = False`,
`uses_truncated_windows = False`, `uses_current_state_fields = False`. The gate reads only the clock.

## 11. Deviations and limitations, stated up front

| Area | Deviation or limitation |
|---|---|
| Weekday | Untestable on VAL, TEST and FINAL (no weekend coin). Used as a TRAIN conditioning check (2 + 2 days, so weak) and reported on CONFIRM |
| Sampling unit | Session-days: TRAIN holds 4 per session, VAL 1-2, TEST 1-2, CONFIRM 15. Y5.2 guards against one-day effects; the coin and block bootstraps alone would not |
| Splits | The lab2 splits, not PLAN's EXT splits. TRAIN's shortlist bar uses PLAN's 60-trade / 40-coin sample |
| Hosts | R30 at a fixed age (g + 30 min), not R0's random age, so the clock is the only varied input. M1 pinned at m = 1, `rhythm+prec` |
| Fills | Minute-bar worst fills with next-bar mechanical exits, not replayed fills |
| One market regime | 22 days of one pump.fun regime; a session effect can move with the regime (holidays, US news cycle) |

## 12. Pre-registered predictions (scored on TRAIN; reports, never decisive)

- **P1.** No candidate config has a TRAIN mean net return > 0.
- **P2.** Every R30 session's host-relative diff lies within ±6 points (no session premium of the size that could pass).
- **P3.** The three R30 singleton sessions' placebo diffs do not all share one sign on both day types (no stable
  calendar effect).

## 13. Debug findings and expected sample (census TRAIN third, counts only)

**The run.** `python research/lab2/y5.py --debug` wrote `Y5/debug.md` and `Y5/debug.json` (2026-10-09 03:29 UTC,
97 s).

- 450 usable coins, created 10-07 19:37:30 → 10-08 08:06:46 UTC (Wednesday night to Thursday morning). Their R30
  decisions (g + 30 min) span 20:07 → 08:37: **3.9 h of the US session, all 8 h of ASIA, 0.6 h of EU, no weekend.**
- Returns, exit reasons, placebo outcomes and cluster outcomes are hidden. Its trials went to a scratch ledger, never to
  `trials.json`.
- **No definition was changed after the debug run.** The grid, sessions, hosts and rules above were written before it.

**Counts:**

| Measure | ASIA | EU | US | All |
|---|---:|---:|---:|---:|
| R30 decisions (coins at g + 30 min) | 265 | 18 | 167 | 450 |
| Alive at the decision (= R30 entries) | 92 | 6 | 39 | 137 |
| R30 entries per 8-hour session-day (entries / hours observed × 8) | ≈ 92 | not measurable (0.6 h) | ≈ 80 | ≈ 263 a day |
| M1-host entries | 18 | 2 | 4 | 24, **all OPERATOR, one operator cluster** |

- Every gated config's count equals its host's in-set count (the filter property, also tested on synthetic bars).
- Decisions by UTC hour: 33-48 coins an hour from 20:00 to 04:00, 21-28 from 05:00 to 07:00.

**Expected sample per R30 singleton config** (assumes other days resemble the census day; EU taken as ≈ 80 per
session-day, the US rate, because the debug saw only 0.6 h of it):

| Split | Session-days (ASIA / EU / US) | R30 trades (ASIA / EU / US) |
|---|---|---|
| TRAIN (4 d, Thu-Sun) | 4 / 4 / 4 | ≈ 370 / 320 / 320, of which about half on the weekend days |
| VAL (1.5 d, Mon-Tue) | 2 / 1.5 / 1 | ≈ 185 / 120 / 80 |
| TEST (1.32 d, Tue-Wed) | 1 / 1.5 / 1.5 | ≈ 92 / 120 / 115 |
| CONFIRM (15 d) | 15 / 15 / 15 | ≈ 1,300 each |

**What these counts imply, before any TRAIN data:**

- **R30 configs are powered on TRAIN** (≫ 60 trades from ≫ 40 coins), and each TRAIN day type holds ≫ 20 trades.
- **An ASIA candidate cannot PASS TEST**: TEST holds one ASIA session-day (10-07), so Y5.2 is missing and the verdict
  is INCOMPLETE at best. EU and US candidates have two TEST dates. CONFIRM is the powered test for all three.
- **M1-host configs will most likely miss the TRAIN sample bar**: on the census day every M1-host entry came from one
  operator cluster, and the bar needs ≥ 3 (about 72 ASIA and 33 US M1-host trades are expected on TRAIN). That is the registered answer to "is this one operator's daily
  schedule?", not a code failure.
- **Fills dominate.** R30 holds 60 minutes at worst fills with next-bar exits; the cost decomposition (gross move vs
  cost) is reported for every config so a session premium can be read against the 1.4-5.1 % round trip.
