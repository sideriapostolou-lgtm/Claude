# Y3 pre-registration: buy a broad-buying breakout from a quiet range (g + 60 → g + 180 min)

- **Version:** `y3-v1`.
- **Written:** 2026-10-09, before any Y3 run on TRAIN, VAL, TEST, CONFIRM or FINAL data. TRAIN was still being
  backfilled. Every constant and the whole grid (§6) were fixed in this file **before** the debug run on the census
  TRAIN third (§13). That run reports counts only: returns hidden, and no parameter chosen there.
- **Code:** `research/lab2/y3.py`, on the shared foundation `research/lab2/common.py` (every feature through
  `common.AsOf`). Tests: `research/lab2/tests/test_y3.py`.
- **Data:** `graduates`, `b2_coins`, `b2_bars` only (B2 minute bars to g + 180 min). No B1, no B3, no CryptoHouse
  queries.
- **Protocol:** PLAN §3 (shared protocol), §3.5 (pass bars), §3.6 (automatic rejections) and §8 (stop rules), through
  common.py's `backtest`, placebo, `describe`, `verdict_entry`, trial ledger, shortlists and one-shot sessions. Stage
  gating and CLI follow `m1.py` / `z1.py`.
- **Splits:** common.py's (TRAIN 10-01 → 10-05, VAL → 10-06 12:00, TEST → 10-07 19:37:30, CONFIRM 09-16 → 10-01,
  FINAL = census day; the census TRAIN third is debug only).
- **Freeze.** The first official TRAIN run hashes this file into `Y3/prereg.lock`. After that, `y3.py` refuses every
  stage if this file has changed. A change is a new version (`y3-v2`) in `Y3/AMENDMENTS.md`, and its configs are new
  trials.

## 1. Hypothesis and mechanism

**Claim.** In the second and third hour after graduation (g + 60 → g + 180 min), a coin whose last N completed minute
bars traded in a **narrow price range** and whose next bar **breaks above that range on broad buying** (many distinct
wallets, not one or two large buyers, net buying) keeps rising for the next half hour by more than a $20 round trip.

**Why it could beat costs** (round trip 2.9-4.0 % of a $20 ticket at pricing reserves X = 40-400 SOL by
`common.round_trip_pct`; 1.4-5.1 % over all market caps):

1. **Attention arrives in waves, not at once.** A call in a Telegram group, a post by a KOL, a DexScreener trending
   slot or a "new high" alert reaches its audience over minutes: the first readers buy, the price move puts the coin
   on the next screen (movers lists, trending ranks), and that brings the next buyers. The first minute of a cascade
   is visible as **breadth**: many distinct wallets paying ≥ 0.01 SOL in one minute. On a constant-product pool there
   is no market maker to absorb that flow; net inflow ΔX moves the price by ((X + ΔX) / X)² − 1, so 5 SOL of follow-on
   net buying on X = 60 SOL is +17 %.
2. **The quiet range is the clean baseline.** By g + 60 min the post-migration distribution wave has mostly run
   (EXPERIENCE N5: stop-out rates of instant coins fall from 43 % at 0-30 min to 8 % at 30-120 min). A coin that
   then trades in a narrow range has its sellers and buyers roughly in balance. A breadth jump out of that state is
   new information (new participants), not the continuation of a dump or of a pump already in progress. The same
   breadth on a noisy coin is indistinguishable from its usual churn.
3. **The range gives a cheap thesis stop.** If the breakout fails, the price falls back through the range; a close
   below the range low means the new buyers did not hold it. Exiting there bounds the loss of a failed breakout at
   about the range width + the breakout bar + costs (§5), while a real cascade pays several round trips. The edge,
   if any, is that asymmetry, not a high hit rate.
4. **Why it might not be priced in.** Screens show candles, volume and transaction counts. Distinct wallets per
   minute against the coin's own quiet baseline is not on them, and the pool has no inventory-holding arbitrageur.

**What would make it fail** (stated before any data):

- **Wave 1 F2 already killed the chart-only version.** Its `squeeze` family (narrow range, then a close above it with
  a volume surge; 96 configs) and its breakouts (464 configs) had **negative gross returns** on the census day
  (`research/lab/reports/f2-momentum.md`). Y3 must show that the flow condition adds what the chart lacked. The grid
  carries the chart-only twin of every config (§6) to measure exactly that.
- **Painted breakouts.** An operator or a group of sybil wallets can paint a broad green minute to recruit followers
  and sell into them. Minute bars cannot tell five sybil wallets from five people. The top-5 concentration rule (§3)
  removes only the whale-driven kind.
- **Rugs.** Coins still get dumped after g + 60 min (the brand-ticker farm dumped "at a time only the operator
  knows"). Rugs are one swap (wave 1 A3); the catastrophe stop fills on the next bar at its low (§5).
- **The worst fill eats the move.** We enter at the high of the bar after the breakout (§4). If the cascade is
  mostly inside the breakout minute, the remainder is below costs.
- **Too rare.** Quiet coins with a ≥ 5-wallet breakout minute may be rare; TRAIN may be UNDERPOWERED (§13).

**Honest prior:** low, about 10 % that Y3 passes TEST. Breakout continuation is folklore that F2 measured as negative
on these coins; Y3 is the one variant F2 could not test (flow per wallet count, later ages).

**Who pays us:** the later waves of the attention cascade, who buy after our fill and before our exit.

### 1.1 Not a duplicate

| Hypothesis | What it conditions on | Y3 differs by |
|---|---|---|
| wave-1 F2 `squeeze` / breakout | candles and raw volume, ages from g | Y3 needs **wallet breadth** and low top-5 concentration on the breakout minute (volume is never used: G15, dust and wash paint it), ages ≥ g + 60 min only, next-bar worst fills. Its chart-only twins re-run F2's idea under Y3's rules as the control |
| X2 | breadth **ranked across** concurrent graduates at a fixed checkpoint (g + 30 / 60) | Y3 is a within-coin **event**: a breadth jump against the coin's own quiet baseline, at a breakout out of a measured range, at any minute of g + 71 → g + 130 |
| Z1 | sellers per minute falling while the price holds | Y3 is a buy-side event out of a narrow range; no seller condition |
| Z2 | one large buy (a whale) | Y3 requires the opposite: the breakout must **not** be concentrated in the top 5 buyers |
| M1 | a steady price-ignoring bid on operator coins | Y3 needs a quiet range and a one-minute breadth jump; a steady bid is not a breakout |
| D1, S1 | dips; insiders' inventory (B1 wallets) | Y3 buys strength out of a range, B2 only |

## 2. Data and universe

- **Tables:** `graduates`, `b2_coins`, `b2_bars`, through `common.load()`.
- **Universe:** every usable coin of the split per `common.load` (SOL-quoted, not Mayhem, virtual reserve known,
  complete B2 window [g, g + 180 min)). No class gate: one mechanism, applied everywhere.
- **Stratum** (placebo matching and reports only, never an entry filter): `instant` when `grad_delay_s` ≤ 5 s (known
  at g), else `slow`. A NULL `grad_delay_s` (creation not scanned) means creation > 30 min before g: `slow`.

## 3. Features, as of τ = t − 20 s (all through `common.AsOf`)

Decisions run on common.py's grid (minute boundary + 20 s). Let k be the number of completed minute bars at τ. The
**breakout bar** is the last completed bar, b = k − 1. The **box** is the N bars before it, [b − N, b). Dense bars:
a minute without trades carries the last close (o = h = l = c) and zero flow; `traded` marks minutes with ≥ 1 trade.

| Feature | Definition |
|---|---|
| `in_window` | the box's first minute starts at or after g + 60 min |
| `box_hi`, `box_lo` | max high and min low over the box |
| `r_box` | `box_hi` / `box_lo` − 1 (range relative to price) |
| `traded_frac` | share of box minutes with ≥ 1 trade |
| `ret_bo` | close(b) / close(b − 1) − 1 |
| `nb_bo` | `n_buyers`(b) (wallets buying ≥ 0.01 SOL in the minute; dust never counts), minus 1 when the AGENT bought ≥ 0.01 SOL in it (the AGENT column is NaN, i.e. nothing removed, before `agent_known_at`; BOOST ends by about g + 6 min, so this never binds at these ages) |
| `nb_box` | mean over the box of the same AGENT-adjusted `n_buyers` |
| `top5_share` | `top5_buy_sol`(b) / `buy_sol`(b); undefined when `buy_sol`(b) = 0 |
| `net_bo` | `buy_sol`(b) − `agent_buy_sol`(b) − `sell_sol`(b) |
| `mcap_usd` | `AsOf.mcap_usd`: last completed close × 1e9 × SOL/USD of the last closed minute |

**Conditions** (k ≥ N + 1):

1. **COMPRESSED:** `in_window` **and** `r_box` ≤ θ **and** `traded_frac` ≥ 0.5 (a real quiet market, not a frozen
   one: a minute without trades has zero range by construction).
2. **BREAKOUT:** close(b) > `box_hi` **and** `ret_bo` ≥ 0.03 (the bar alone moves the price by about one round trip:
   the cost we pay to follow it).
3. **BROAD** (the bar proxy of organic flow, §11): `nb_bo` ≥ max(5, 2 × `nb_box`) **and** `top5_share` < 0.85 (G1's
   concentration bar: the top 5 buyers did not supply ≥ 85 % of the minute's buying, so the move is not one or two
   whales) **and** `net_bo` > 0.
4. **ELIGIBLE:** `mcap_usd` ≥ $6,000 (the floor guard of `AsOf.alive`). The 15-minute volume floor of `alive` is
   **not** used: it contradicts a quiet box by design, and the breadth rule is the activity requirement.

**SETUP** = COMPRESSED and BREAKOUT and (flow mode `broad`: BROAD; flow mode `chart`: nothing more) and ELIGIBLE.

All thresholds are round numbers chosen from the mechanism and the cost model above, not from data. θ and N are the
only searched quantities (§6).

## 4. Entry rule

At the first decision time t at which SETUP holds, at most one entry per coin:

- age t − g ≤ 130 min (the box condition already forces t − g ≥ 60 + N + 1 min). The cap leaves ≥ 47 min of data
  after the entry, so the 30-minute hold (§5) always ends inside B2;
- buy $20. The order lands at t + 30 s in the bar after the breakout bar and fills at that bar's **worst** price,
  max(open, high) (`common.FillConfig`).

## 5. Exits

| Exit | Rule |
|---|---|
| Box stop (thesis) | at a decision where the last completed bar, completed **after** the entry decision, **closed below `box_lo`** (the breakout failed and the range broke down), sell. The order lands 30 s later in the next bar and fills at min(open, low) (EXPERIENCE G22 / G25: confirmed on a closed bar, filled on the next bar at its worst) |
| Catastrophe stop | −25 % from the entry fill, checked intrabar on every bar including the entry bar; fills on the **next** bar at min(open, low) (`exit_delay_bars = 1`) |
| Time | 30 min from the landing; fills on the next bar at min(open, low) |
| Deadline | sell no later than g + 178 min (`exit_by_age_s`). With entries ≤ g + 130 min and a 30-min hold it never binds, so no trade can be censored at the data horizon |

**Placebo positions** carry no state: their `box_lo` is recomputed from the N bars before the last bar completed at
their own decision (the same indexes as a signal's box), so they run the same box stop.

## 6. The TRAIN grid: exactly 8 configurations, every one a trial

**N ∈ {10, 20} bars × θ ∈ {0.06, 0.12} × flow ∈ {`broad`, `chart`}.**

| Axis | Values | Why |
|---|---|---|
| N (box length) | 10, 20 | two time scales of a quiet market: a 10-minute pause and a 20-minute range |
| θ (max box range) | 0.06, 0.12 | 0.06 ≈ 1.5-2 round trips (a failed breakout costs about 3 round trips with the box stop); 0.12 ≈ 3-4 round trips (more setups, larger failure loss). At X = 40-120 SOL one 1-SOL trade moves the price 1.7-5 %, so both are quiet relative to typical trade impact |
| flow | `broad` (§3 rule 3), `chart` (no flow rule) | `broad` is the hypothesis. **`chart` configs are pre-registered controls, never selectable:** each is F2's squeeze idea under Y3's ages, fills and exits, so `broad − chart` measures what the flow rule adds |

Fixed for every config (in each params dict, so any change is a new trial): `ret_bo` ≥ 0.03, breadth ≥ max(5, 2 ×
box mean), top-5 share < 0.85, net buy > 0, traded share ≥ 0.5, box start ≥ g + 60 min, entry age ≤ 130 min,
`mcap_usd` ≥ $6,000, box stop, catastrophe stop 25 %, hold 30 min, deadline g + 178 min, $20, the fill model, the
version.

- **Grid size: 8** (the task cap is 12; nothing padded: 4 selectable configs and their 4 chart twins). Y3 has
  **8 trials** in total: VAL, TEST, CONFIRM and FINAL re-run shortlisted params with the same fills, which common.py
  counts as the same trials.
- **Fills** (`common.FillConfig(exit_delay_bars=1)`): $20, latency 30 s, entry at max(open, high) of the landing
  bar, exits at min(open, low), catastrophe and time exits filled on the **next** bar, entry-bar stop checks on,
  costs = PumpSwap tier by date and market cap + 10 bps Ultra + 20 bps buffer + network fees, impact on X = x + v.
- **Stress and sensitivity** (same call, never used to select): costs × 1.5; rent $0.22; same-bar exits
  (`exit_delay_bars = 0`, the optimistic reference).

## 7. TRAIN shortlist rule (a pair)

A `broad` config **qualifies** on TRAIN when all hold:

| Requirement | Bar |
|---|---|
| Sample | ≥ 60 trades from ≥ 40 coins (PLAN §3.5 item 1 sizes) |
| Mean net | > 0 |
| Mean without the top 2 trades | > 0 |
| Matched placebo (§9, stratum-matched) `mean_diff` | > 0 |
| Compression-matched control (§9) `mean_diff` | > 0: the breakout and flow must add something beyond "a quiet coin" |
| Mean − its `chart` twin's mean | > 0: the flow rule must add something beyond F2's chart squeeze |
| Censored share | ≤ 10 % |

- **Ranking:** the coin-bootstrap 90 % CI lower bound, highest first; ties go to the higher mean, then the smaller N,
  then the smaller θ.
- **Shortlist** = the **pair** (rank-1 `broad` config, its `chart` twin), written with `common.write_shortlist` before
  the first VAL run. The twin rides along so VAL / TEST / CONFIRM can report `broad − chart` out of sample; it is
  never the candidate.
- **Nothing qualifies:** **NO_CONFIG** (Y3 fails on TRAIN) when at least one `broad` config met the sample bar, else
  **UNDERPOWERED_TRAIN**. Either stops Y3.
- A decision on complete TRAIN is final. A re-run needs `--rerun-reason` naming a data correction; the previous
  result is archived as `train_prev_<ts>.*`. `--allow-partial` runs a **PROVISIONAL** TRAIN on partial data that
  writes `train_prelim.*`, never a shortlist or a lock, and never unlocks VAL.

## 8. Later stages (`python research/lab2/y3.py --stage …`)

**Every stage** refuses unless `Y3/PREREG.md` exists (and matches `prereg.lock` once locked), PLAN §8 rule 1 holds
for the split (V1-V4 via `common.validation_gates`), the split's coverage is complete (every chain hour scanned, ≤ 5 %
of tradeable coins missing B2, no mid-run hour, SOL/USD covering the split; FINAL reports its end-of-data coins
instead), and the guarded splits have their flags (`LAB2_ALLOW_TEST`, `LAB2_ALLOW_CONFIRM`, `LAB2_ALLOW_FINAL`, which
`y3.py` never sets).

### VAL (the shortlisted pair, once)

Both configs run once, with the placebo, the controls and the stress runs. The decision uses the candidate's trades:

| Decision | Condition |
|---|---|
| UNDERPOWERED_VAL | n < 5 |
| FAIL_VAL | n ≥ 5 and (mean ≤ 0 or mean without the top 2 ≤ 0) |
| SELECTED_UNDERPOWERED | 5 ≤ n < 15, mean > 0 and mean without the top 2 > 0 |
| SELECTED | n ≥ 15, mean > 0 and mean without the top 2 > 0 |

### TEST (one look, `common.one_shot_session`)

- The candidate and its twin run once each inside the family's one session, with the placebo, the controls and the
  stress runs.
- **Verdict** on the candidate = `common.verdict_entry(test, val=VAL candidate, min_mean=0.03)`: PLAN §3.5 items 1-8
  (+3 % mean), item 10 (≤ 10 % censored) and the §3.6 auto-rejections. Item 9 (FINAL mean > 0) is judged after FINAL.
  REJECTED > UNDERPOWERED > FAIL > INCOMPLETE > PASS.
- **Reported, never judged:** `broad − chart` (candidate mean minus twin mean).
- With a 1.3-day TEST, **UNDERPOWERED is likely.**

### CONFIRM (09-16 → 10-01; one look, never searched)

- **Precondition:** TEST not REJECTED, and TEST mean > 0 or TEST n < 5. Otherwise Y3 failed TEST and CONFIRM is not
  spent.
- Same pair, same verdict as TEST. CONFIRM is the powered out-of-sample test.

### FINAL (the census day; only after TEST)

- The pair runs once on all of FINAL (one session; FINAL consumes its thirds).
- **Criterion 9 (mean > 0) is judged on the census VAL and TEST thirds only.** The census TRAIN third hosted the debug
  run (§13), so its trades are reported apart.

### Overall Y3 verdict

**EDGE** requires TRAIN SHORTLISTED, VAL SELECTED or SELECTED_UNDERPOWERED, TEST not REJECTED with (mean > 0 or
n < 5), CONFIRM PASS and FINAL (judged thirds) mean > 0. Otherwise **NO EDGE** or **UNDERPOWERED** (TRAIN, VAL or
CONFIRM), with the stage named.

## 9. Controls

- **Primary matched random control** (PLAN §3.4, `common.backtest` placebo): 20 draws per signal, random coins of the
  same split that are ELIGIBLE (`mcap_usd` ≥ $6,000) and in the **signal's stratum** (instant / slow), decision age
  within ±120 s of the signal's, the same exits. It feeds PLAN §3.5 item 5 (≥ +6 points) and the TRAIN shortlist.
- **Compression-matched control** (judged on TRAIN only, reported everywhere): the same, but the random entry must
  also be COMPRESSED (§3 rule 1, with the config's N and θ) at its decision. It isolates the breakout-and-flow part.
- **Chart twin** (judged on TRAIN, reported later): the same config without the flow rule (§6). It isolates the flow
  part.
- **Unmatched control** (reported, never judged): ELIGIBLE coins of any stratum.

## 10. Metric and statistics

- Unit: net return per $20 trade (`ret_net`), one entry per coin per config.
- Coin-bootstrap 90 / 95 % CIs (10,000 draws) and the 6-hour block bootstrap (common.py); the mean without the top 2
  trades; top-coin share; halves; the $100 / 5-slot portfolio; costs × 1.5; the deflated Sharpe ratio counting every
  trial in the ledger; per stratum; exit reasons (non-debug splits only).

## 11. Kill criteria and declarations

| Rule | How Y3 applies it |
|---|---|
| PLAN §8 rule 1 (data first) | V1-V4 must pass for the split; stages refuse otherwise |
| Rule 2 (fills) | minute-bar worst fills with next-bar stops until X1's replayed fills exist; if replayed fills move the result by ≥ 1 point, the frozen candidate is re-run before any promotion, with no new search |
| Rule 8 (count everything) | 8 trials (§6), logged in `research/lab2/trials.json` |
| TRAIN | NO_CONFIG or UNDERPOWERED_TRAIN stops Y3 |
| VAL | FAIL_VAL stops Y3 (a PLAN §8 rule 7 input) |

**"Organic" on bars.** The task asks for organic buy flow. B2 bars carry no wallet ids, so bots, wash traders and MECH
wallets paying ≥ 0.01 SOL are inside `n_buyers`; only B1 could remove them, and B1 skips instant graduates. Y3
therefore uses the **bar proxy** (breadth ≥ 5 wallets and ≥ 2 × the box baseline, dust excluded by the 0.01 SOL count,
AGENT removed, top-5 share < 0.85, net buying) and **never calls it organic in the PLAN §3.2 sense** (PLAN §3.6 rejects
counting those roles as organic). Like X2, M1 and Z1 it declares `uses_organic_flow = False`.

Declarations passed to `common.auto_rejections`: `uses_organic_flow = False`, `uses_wallet_reputation = False`,
`uses_truncated_windows = False`, `uses_current_state_fields = False`.

## 12. Limits, stated up front

| Area | Limit |
|---|---|
| Breadth | per-minute distinct wallets; sybil wallets look like people; a pooled program account counts as one buyer (understates breadth) |
| Concentration | only the top-5 SOL of the minute is stored; a minute with ≤ 5 buyers has top-5 share 1 and can never pass, so BROAD needs ≥ 6 buyers in practice |
| AGENT in `top5_share` | the AGENT's SOL cannot be removed from the stored top-5 sum; BOOST ends by ~g + 6 min, decades of minutes before any Y3 box |
| Fills | minute bars, worst side, next-bar stops; no sub-minute replay (X1 engine) |
| Hold | B2 ends at g + 180 min; entries ≤ g + 130 min, holds 30 min |
| SOL/USD | the series must cover the split before any non-debug stage (`common.coverage_problems`) |

## 13. Debug run (census TRAIN third, counts only)

To be filled in after `python research/lab2/y3.py --debug` (counts only: returns, exit reasons and placebo outcomes
hidden; trials go to a scratch ledger, never to `trials.json`). No constant above may change after it.
