# Y2 pre-registration: buy the graduates whose curve was filled organically

- **Version:** `y2-v1`.
- **Written:** 2026-10-09, before any Y2 run on any split. TRAIN is still being backfilled. The only run allowed
  before the first official TRAIN run is the debug run on the census TRAIN third (§12): counts only, returns hidden,
  and no parameter below was chosen from it.
- **Code:** `research/lab2/y2.py`, on `research/lab2/common.py`. Tests: `research/lab2/tests/test_y2.py`.
- **Splits:** common.py's (TRAIN 10-01 → 10-05, VAL 10-05 → 10-06 12:00, TEST 10-06 12:00 → 10-07 19:37:30,
  CONFIRM 09-16 → 10-01, FINAL = the census day in its lab thirds).
- **Freeze.** The first official TRAIN run hashes this file into `Y2/prereg.lock`. From then on `y2.py` refuses every
  stage if this file changed. A change is a new version (`y2-v2`) in `Y2/AMENDMENTS.md`, and its configs are new
  trials.

## 1. Mechanism, and why it could beat costs

**What the curve tells us.** A pump.fun curve sells 793.1M tokens for about 85 SOL. Who bought them decides who holds
cheap inventory at graduation:

- **Insider-filled curve.** The creator and a creation-slot bundle buy first, sniper bots buy in the first 60 s, one
  whale finishes the last 30 SOL, and three wallets pay most of the SOL. A few wallets then hold most of the float at
  a low average cost. They sell it into whatever demand arrives after migration. That is a predictable supply overhang
  over the first hours after g. The lab measured its footprint: random alive entries 30-120 min after g lose about 7-9%
  (EXPERIENCE_GROUNDED N5), and the losses come from distribution (A3: rugs were one sell of 9-13% of supply).
- **Organically filled curve.** Many small buyers paid the 85 SOL. The curve price is convex, so most SOL was paid
  late, near the graduation price: there is little cheap inventory left to dump. A broad holder base is also the
  population that brings the next buyers (each holder is a potential promoter).

**Where an edge would come from.** Every graduate migrates at the same price whatever filled its curve, and the
composition is public but takes work to read. If the drift after g + 30 min differs by curve composition and the
market has not priced it by then, the most organic graduates should outperform the eligible average.

**Why it could beat costs, and why it probably will not.**

- A $20 round trip costs 1.4-5.1% at the pool (fee tier by market cap, Ultra, buffer, impact, network;
  `common.round_trip_pct`). The worst-fill model (entry at the bar high, exits at the next bar's low) adds more.
- The base rate is negative: an average alive non-instant graduate at g + 30 loses money. The selection has to lift
  the top group by roughly 10 points to clear the PLAN bar of +3% mean net and +6 points over the matched control.
- That is a large cross-sectional effect for a static, public feature. Tools (GMGN, Axiom) already display bundle,
  sniper and top-holder shares. **Honest prior: below 10% that a config passes TEST.** The idea is cheap to test,
  covers every graduate whose creation was scanned (no B1 needed), and a clean NO EDGE is informative for S1 and D1.

**Who loses if it works:** early curve buyers who take profit around g + 30 min (selling to us below where later
attention takes the price), and a market that prices every graduate alike.

**Known ways it can fool itself:**

- A bundler can fake breadth with many wallets. The bundle (C4) and sniper (C5) components partly counter this; the
  aggregate columns cannot separate one operator's 40 wallets from 40 people.
- "Organic" here is a rank of curve dispersion. It is **not** PLAN §3.2 ORGANIC flow (that needs B1 wallet roles):
  bots and wash wallets on the curve count as buyers in `curve_n_buyers`.

## 2. How Y2 differs from G1, S1, D1 and M1

| Module | What it is | Overlap with Y2 |
|---|---|---|
| G1 | A **veto gate**: fixed classes (OPERATOR / FACTORY / COMPLETED) skip host trades | Y2 uses no G1 class and no post-g flow feature in its score. It is an **entry selector** on the organic side: a continuous rank inside the non-instant universe, and it asks whether the top of that rank is profitable in absolute terms against a matched control in the same universe |
| S1 | Wallet-level insider inventory spent, from B1 ledgers, re-evaluated at checkpoints | Y2 uses graduation-time aggregates only (`graduates`), static after g |
| D1 | Dip classification (capitulation vs distribution) | None |
| M1 | Mechanical bids on OPERATOR coins | None (M1 lives on instant/operator coins, which Y2 excludes) |

Y2's PE11 selector is the "fast organic" cell of craft rule PE-11 (`EXPERIENCE_GROUNDED.md` G04), which G04 records
as **not in G1**. Its thresholds are PE-11's own (5 s - 5 min, ≥ 15 buyers, top-3 share < 0.6), not ours.

## 3. Data and universe

**Data:** `graduates`, `b2_coins`, `b2_bars` through `common.load`. No B1, no B3, no CryptoHouse query. Every feature is
read through `common.AsOf`.

**Usable coins:** `common.load`'s universe (SOL-quoted, not Mayhem, virtual reserve known, complete 180-min B2 window).

**Eligible (the Y2 universe)**, all at g:

- `curve_partial` is False: the CreateEvent was scanned, so the curve-life columns cover the whole curve;
- `grad_delay_s` > 5 s: not instant. An instant graduate's curve is one creator buy; it has no organic side;
- every component input in §4 is non-NULL and `curve_buy_sol` > 0. **NULL is never 0**: a NULL makes the coin
  ineligible.

**Data limitation, stated up front.** Coins whose CreateEvent lay before the curve scan's 30-minute lookback
(`has_create = 0`, about 17% of non-instant graduates per AUDIT 3.3) have NULL curve columns and are excluded. The
eligible universe is therefore biased towards curves that lived less than roughly 30-90 minutes. The slowest organic
graduations are not tested.

## 4. Features and the organic rank (as of τ = t − 20 s)

**Components**, all legal at g (curve-life columns at g; `z_*` and `sn60_*` at min(created + 120 s, g)):

| ID | Component | Definition | Organic side |
|---|---|---|---|
| C1 | breadth | `curve_n_buyers` (distinct wallets ≥ 0.01 SOL) | higher |
| C2 | concentration | `curve_top3_buy_sol / curve_buy_sol` | lower |
| C3 | completer | `completer_sol / 30` (largest buyer of the last 30 SOL) | lower |
| C4 | bundle | `z_buy_tok / 793.1e6` (creation-slot buys, creator included) | lower |
| C5 | snipers | `sn60_buy_sol / curve_buy_sol` (non-creator buys in the first 60 s) | lower |

**Reference pool R(τ)** for a candidate coin c: every graduate other than c that

- graduated in (τ − 24 h, τ] (its features are knowable at its own g ≤ τ, read through AsOf at τ = g);
- was created before the end of the split being run (later splits never feed an earlier one, as in G1's registry);
- is eligible at g (§3) and SOL-quoted, not Mayhem. B2 completeness is not required: only features at g are used.

24 h covers one full daily cycle, so the rank is not biased by time-of-day composition.

**Organic rank** (no fitted weights):

1. S = R ∪ {c}. For each component k and each coin s in S, p_k(s) = the mid-rank percentile of s's oriented value
   among the other coins of S: (#{worse} + ½ #{tied}) / (|S| − 1).
2. Composite q(s) = the mean of p_1..p_5 (equal weights).
3. Organic rank of c = (#{r ∈ R: q(r) < q(c)} + ½ #{q(r) = q(c)}) / |R|.
4. **Tercile:** top if rank ≥ 2/3, bottom if rank < 1/3, else mid. **Top quintile:** rank ≥ 0.8.

**Cold rank.** The rank is undefined ("cold") when |R| < 50, or when fewer than 99% of the clock hours overlapping
(τ − 24 h, τ] are fully scanned for graduates (`Completeness.curve_hours`). A cold coin is never entered by T3 or T5.

**PE11 cell** (PE-11 verbatim): 5 s < `grad_delay_s` ≤ 300 s, `curve_n_buyers` ≥ 15, top-3 share < 0.6. It needs no
reference pool.

## 5. Entry

- **One decision per coin**, at the first decision-grid time with age ≥ 30 min (t ∈ [g + 1,800, g + 1,860) s).
  Waiting for a better moment would add a timing search; Y2 is a selector.
- **Enter** when the coin is eligible, its selector holds, and it is **alive** (`AsOf.alive()`: 15-minute USD volume
  ≥ $1.5k and market cap ≥ $6k; the F3 / PLAN R0 rule). Otherwise the coin is skipped for good.
- **Selectors:** `T3` = top tercile (warm rank); `T5` = top quintile (warm rank); `PE11` = the PE-11 cell.
- **ALL** (diagnostic, §7): every eligible alive coin, tagged by tercile (top / mid / bottom / cold) and PE11 flag.

## 6. Exits and fills

Mechanical only; no signal exits.

| Exit set | Rule |
|---|---|
| `X60` | stop −50% from the entry fill (catastrophe), time exit 60 min after landing (PLAN X1 exit 6) |
| `H178` | stop −50%, sell at g + 178 min (`exit_by_age_s`, the registered deadline inside B2; holds ≈ 147 min) |

**Fills (primary):** `common.FillConfig(exit_delay_bars=1)`: $20, 30 s latency, entry at max(open, high) of the
landing bar; stops are checked on the entry bar too, and every triggered exit (stop or time) fills at min(open, low)
of the **next** bar. Costs: PumpSwap tier by date and market cap, + Ultra 10 bps, + 20 bps buffer, network fees,
pricing on X = x + v. No trade can end on the data horizon (the deadlines fill by g + 179 min), so nothing is censored.

**Stress and sensitivity** (same call, reported, never selected on): costs × 1.5; rent $0.22; `same_bar_exits` =
`FillConfig()` (exits in the trigger bar: the optimistic harness reference).

## 7. The grid: 6 configs + 1 diagnostic = 7 trials

**Selectors {T3, T5, PE11} × exit sets {X60, H178} = 6 configs**, each a counted trial. Plus **ALL** (H178), the
dose-response diagnostic: it is counted as a trial, run on TRAIN, TEST, CONFIRM and FINAL, and **never shortlisted**.

- T3 vs T5 is the dose-response inside the score (a stricter selection should do better if the mechanism is real).
- PE11 tests the external fast-organic claim.
- X60 vs H178 tests the mechanism's time profile (an overhang effect accumulates over hours).
- Every constant in §3-§6 is in each config's params dict, with the version and the fill model. Any change is a new
  trial. Nothing is tuned: the 24 h lookback, 50 coins, tercile/quintile, −50% stop and the hold lengths are set
  above by reasoning; PE11's thresholds are PE-11's.

**Y2's total: 7 trials**, on top of the ledger (2,575 wave-1 configs + every wave-2 config).

## 8. Controls

- **Matched random control** (PLAN §3.4, `common.backtest` placebo): 20 draws per signal, random coins of the same
  split that are **eligible (§3) and alive** at the drawn time, decision age within ±120 s, same exits. It isolates
  the selection from "being an alive non-instant graduate at g + 30". It feeds PLAN §3.5 item 5 and the TRAIN rule.
- **Unmatched control** (any usable alive coin, instant included): reported as `placebo_unmatched`, never judged.
- **Dose-response** from ALL: mean by tercile, top − bottom with a coin-bootstrap CI, PE11 cell vs the rest.

## 9. Procedure by stage (`python research/lab2/y2.py --stage …`)

**Every stage** refuses unless `Y2/PREREG.md` exists (and matches `prereg.lock` once locked), PLAN §8 rule 1 holds
for the split (`common.validation_gates`), the split's coverage is complete (FINAL exempt, as in M1), and the guarded
splits have the judge's flags (`LAB2_ALLOW_TEST`, `LAB2_ALLOW_CONFIRM`, `LAB2_ALLOW_FINAL`; y2.py never sets them).

### TRAIN (all searching)

Run the 6 configs (matched control + stress) and ALL. A config **qualifies** when all hold:

| Requirement | Bar |
|---|---|
| Sample | ≥ 30 trades |
| Mean net | > 0 |
| Mean without the top 2 trades | > 0 |
| Matched-control `mean_diff` | > 0 |
| Mechanism consistency (from ALL on TRAIN) | T3, T5: mean(top tercile) > mean(bottom tercile). PE11: mean(PE11 cell) > mean(rest of eligible) |

**Shortlist** = up to 2 qualifying configs with the highest coin-bootstrap 90% CI lower bound (ties: higher mean, then
grid order), written with `common.write_shortlist` and frozen at the first VAL run. Otherwise **NO_CONFIG** (some
config met the sample bar) or **UNDERPOWERED_TRAIN**. A decision on complete TRAIN is final (a re-run needs
`--rerun-reason` naming a data correction; the old result is archived). `--allow-partial` gives a PROVISIONAL TRAIN
(`train_prelim.*`) that never writes a shortlist or a lock.

### VAL (the ≤ 2 shortlisted configs, once)

Each shortlisted config passes VAL when n ≥ 5, mean > 0 and mean without the top 2 > 0. The **candidate** is the
passing config with the higher VAL coin-bootstrap 90% CI lower bound (ties: TRAIN order).

| Decision | Condition |
|---|---|
| UNDERPOWERED_VAL | every shortlisted config has n < 5 |
| FAIL_VAL | none passes (PLAN §8 rule 7 input) |
| SELECTED_UNDERPOWERED | the candidate has 5 ≤ n < 15 |
| SELECTED | the candidate has n ≥ 15 |

### TEST (one look, `common.one_shot_session`)

Run the candidate and ALL once. **Verdict** = `common.verdict_entry(candidate, val=VAL candidate)` (PLAN §3.5 items
1-8 and 10 with the default bars: +3% mean, +6 points over the matched control; §3.6 auto-rejections) **plus Y2.1**:
the candidate's mechanism-consistency check (§9 TRAIN table) on the TEST run of ALL. Y2.1 is blocking (False → FAIL,
missing → INCOMPLETE). Combined: REJECTED, else UNDERPOWERED (item 1), else FAIL, else INCOMPLETE, else PASS. Item 9
(FINAL mean > 0) is judged in the overall verdict. With 1.3 days of TEST, UNDERPOWERED is likely.

### CONFIRM (09-16 → 10-01; one look, never searched)

Precondition: TEST not REJECTED, and TEST mean > 0 or TEST n < 5. Run the candidate and ALL once; same verdict.

### FINAL (census day; one look after TEST)

Run the candidate and ALL once on all of FINAL. Criterion 9 (mean > 0) is judged on the census VAL and TEST thirds
only; the TRAIN third was used for debugging (§12) and is reported apart.

### Overall verdict

**EDGE** needs TRAIN SHORTLISTED, VAL SELECTED or SELECTED_UNDERPOWERED, TEST not REJECTED and (mean > 0 or n < 5),
CONFIRM PASS, and FINAL mean > 0. Otherwise UNDERPOWERED (TRAIN / VAL / CONFIRM) or NO EDGE.

## 10. Statistics

Unit: net return per $20 trade (`ret_net`), one entry per coin per config. Coin-bootstrap CIs (10,000 draws, 90% and
95%) and the 6-hour block bootstrap (common), mean without the top 2, top-coin share, halves, the $100 / 5-slot
portfolio, costs × 1.5, the deflated Sharpe ratio over every trial in the ledger, exits by reason (not on debug).

## 11. Kill criteria and declarations

- **Stop rule 1:** V1-V4 per split; stages refuse otherwise.
- **Stop rule 2:** minute-bar worst fills with next-bar exits until X1 replays fills; if X1 finds them off by ≥ 1 point,
  the frozen candidate is re-run with replayed fills before any promotion (no new search).
- **Stop rule 7:** FAIL_VAL is reported to the lead.
- **Stop rule 8:** every config counts (§7).

Declarations passed to `auto_rejections`: `uses_organic_flow = False` (the rank is curve dispersion, not PLAN
ORGANIC flow; see §1), `uses_wallet_reputation = False`, `uses_truncated_windows = False`,
`uses_current_state_fields = False`.

## 12. Debug run (census TRAIN third; counts only)

`python research/lab2/y2.py --debug` writes `Y2/debug.md` and `Y2/debug.json`: usable, eligible and warm coins,
tercile counts, selector and alive counts, entries per config and per day, placebo counts. Returns, exit reasons and
stress results are hidden. Its trials go to a scratch ledger. The counts are appended below before the first
official TRAIN run; they only size the expected samples.

### 12.1 Debug counts (census TRAIN third, 2026-10-09; counts only, written before any TRAIN data existed)

`python research/lab2/y2.py --debug` on 450 usable coins created over 0.52 days. Returns, exit reasons and stress
results were never computed into the report; no parameter was chosen or changed after this run.

| Measure | Census TRAIN third (0.52 d) | Per day | TRAIN (4 d) | VAL (1.5 d) | TEST (1.32 d) | CONFIRM (15 d) |
|---|---:|---:|---:|---:|---:|---:|
| Eligible (non-instant, curve scanned) | 152 (277 instant, 21 creation not scanned) | ≈ 292 | ≈ 1,170 | ≈ 440 | ≈ 385 | ≈ 4,400 |
| Eligible and alive at g + 30 | 47 | ≈ 90 | ≈ 360 | ≈ 135 | ≈ 120 | ≈ 1,350 |
| T3 entries | 14 | ≈ 27 | ≈ 108 | ≈ 40 | ≈ 36 | ≈ 400 |
| T5 entries | 7 | ≈ 13 | ≈ 54 | ≈ 20 | ≈ 18 | ≈ 200 |
| PE11 entries | 16 | ≈ 31 | ≈ 123 | ≈ 46 | ≈ 41 | ≈ 460 |
| ALL entries (dose) | 47 (14 top / 19 mid / 14 bottom tercile) | ≈ 90 | ≈ 360 | | | |

The extrapolations assume the census day's composition holds on other days.

**What the counts imply (structure, not outcomes):**

- **The reference pool is warm everywhere:** median 307 eligible graduates in the trailing 24 h (minimum 299), and
  every lookback hour is a fully scanned curve hour. Cold ranks will only occur at the start of the backfilled data.
- **Two thirds of eligible coins are dead at g + 30** (152 → 47 alive). The selectors act on the alive third.
- **PE11 and T3 select nearly disjoint coins.** Of the 16 alive PE11 coins, 12 are in the bottom organic tercile and
  4 in the middle; none is in the top. Graduations in 5 s - 5 min are bundle- and sniper-heavy, which the composite
  ranks low, and PE-11's breadth and top-3 thresholds (≥ 15 buyers, < 0.6) are lax. So the grid holds a natural
  contrast: if PE11 beats T3, graduation speed matters more than curve dispersion; if T3 beats PE11, the reverse.
- **TEST will be UNDERPOWERED** for every config (≈ 18-41 entries against the 60-trade bar). VAL can reach the 15-trade
  SELECTED bar for T3 and PE11, not reliably for T5. CONFIRM (15 days) is the powered out-of-sample look.
- **Matched-control draws:** about 10% of random (coin, time) draws are eligible and alive, so `common.run_placebo`'s
  200 tries per signal yield ≈ 19 of the 20 draws on average (266 for 14 T3 signals; 301 for 16 PE11 signals).
- No trade ended on the data horizon (0 `horizon` exits in every config), as designed.
