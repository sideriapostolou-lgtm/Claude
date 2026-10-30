# F3 Lifecycle / time-structure: no strategy beats costs out of sample

**Verdict.** No F3 configuration passes the VALIDATION gate, so there are **no finalists**:
`finalists/f3-lifecycle.json` is `[]`. Nothing from this family should go to the judge for TEST.

- **Searched on TRAIN:**
  - 487 configurations in 5 entry families;
  - 13 logged event-study cuts (149 groups), plus 3 unlogged descriptive drill-downs.
- **Checked on VALIDATION:** 8 configurations. These are the 7 picked by the pre-declared shortlist rule
  (3 of them behave identically) and 1 declared family center.
- **TRAIN:** 19 configurations had a coin-bootstrap CI above 0. All of them are one family (the "late
  drifter"), and all of their trades are in one launch cluster: the ticker-clone coins F2 already flagged.
  If the configs were independent, about 11 would pass by chance.
- **VALIDATION:** the best of them make **5-6 trades**, and every CI crosses 0. All other families lose 10-19%
  per trade, with CIs entirely below 0.

**The robust, useful result is a set of "when not to trade" rules** (see "Findings" below). They describe the
lifecycle. They are not a profitable strategy.

## Entry families (all causal; decided at bar i's close, filled at the next open)

Every configuration ran in the portfolio simulator: default cost model, $100 start, 20% sizing clamped to
$5-$25, at most 3 positions, `wick_fill="half"`. Each was also run per coin at $20.

| Family | Idea | TRAIN configs | ≥ 15 trades on ≥ 10 coins | Mean > 0 | CI low > 0 | Median of means | Best mean |
|---|---|---:|---:|---:|---:|---:|---:|
| `runner` | buy a survivor of the first-hour die-off, at a fixed age window after graduation, by class (organic / instant) and position vs the post-graduation peak | 153 | 147 | 13 | 0 | -11.5% | +5.4% |
| `second_leg` | after a first dump of ≥ 50-70% from the graduation high, a quiet base (range ≤ 1.4-2x over 20-45 bars, ≥ $3k volume), then a close above the base on a volume surge | 65 | 65 | 0 | 0 | -6.9% | -3.0% |
| `base_bounce` | same base; buy a green bar in the bottom 20-35% of the range; target the base top | 97 | 97 | 0 | 0 | -4.1% | -0.5% |
| `gated_dip` | the bot's own dip-rebound, allowed only inside a lifecycle window (class, 30 min-24 h after graduation, volume not decayed) | 49 | 32 | 1 | 0 | -8.2% | +0.9% |
| `drifter` | the late, calm phase: an instant graduate at ≥ $1M graduation market cap, ≥ 1-8 h old, with a tight 30-120-bar range, held 1-6 h | 123 | 113 | 78 | 19 | +1.8% | +10.3% |
| **total** | | **487** | 454 | 92 | 19 | | |

**Exits tested:**

- fixed stop (5-30%), or a structure stop just below the base low;
- take-profit (15-50%, or the base top) and a partial take-profit;
- trail (10-30%);
- time stop (30-360 min);
- a lifecycle exit that sells when volume dies (the last 10-30 bars hold less than $0.5-2k).

**Search stages:**

| Stage | Configs | What it covered |
|---|---:|---|
| smoke | 5 | one config per family |
| stage 1 | 424 | the grid above |
| stage 2 | 58 new (12 repeats) | one-parameter neighbourhoods around the two drifter centers; a falsification test of the same "calm base" on organic coins; the dying-volume exit on the best runner and gated configs |

Every run is in `LAB/f3/runs.jsonl`. `python research/lab/f3_lifecycle_search.py count` reproduces the counts.

## Findings

### 1. When NOT to trade (TRAIN, descriptive)

The drift map shows the gross return over the next 30 minutes, from the next open. It covers "alive" coins
only: 15-bar volume ≥ $1.5k and market cap ≥ $6k.

| Minutes after graduation | Mean | Median | Coins |
|---|---:|---:|---:|
| 0-10 | **-52.0%** | **-95.3%** | 446 |
| 10-30 | -18.5% | -22.9% | 182 |
| 30-60 | -4.4% | -0.0% | 136 |
| 60-120 | -10.4% | +0.2% | 105 |
| 120-240 | -2.7% | +0.8% | 72 |
| 240-480 | -0.1% | +0.8% | 62 |
| 480+ | +0.1% | +0.7% | 53 |

- **First 10 minutes after graduation:**
  - instant graduates below $100k: mean -76.8%;
  - instant graduates at $100k-$1M: mean -62.4%;
  - organic graduates: mean -45.9%.
- **Survivor "runners" bought 10-30 minutes after graduation:** all 36 configs lose, at **-10% to -52% per
  trade** after costs.
- **Dead coins** (not alive by the rule above) drift about 0% gross, so buying them only pays the about 5% round
  trip.
- **Practical rules for the bot:**
  - no entries in the first 30 minutes after graduation;
  - no instant graduate below $1M in its first 2 hours;
  - no coin whose last 15 minutes traded less than about $1.5k.

  These rules avoid the worst losses. They do not create profit.

### 2. The "second leg" does not exist on average

- **Breakouts from a post-dump base (event study):** gross -2% to -8% at 15-120 minutes; median -10% to -24%
  at 30-120 minutes.
- **In the harness:** all 65 configs lose (best -3.0%).
- **Buying the bottom of the base** (`base_bounce`, 97 configs): all lose (best -0.5%).
- **Revivals after dormancy** (an hour or more of near-zero volume, then a spike) almost never happen: 1 event in
  448 TRAIN coins.

### 3. Organic survivors are lottery tickets

Organic graduates still alive 30-60 minutes after graduation have a mean of +15.6% over the next 30 minutes,
but a median of -29%.

- One coin (TINCAN, +1,986%) makes the whole mean. Without it the mean is -4.7%.
- The two runner configs that reached VALIDATION carried 172-219% of their TRAIN profit in the single best
  coin. On VALIDATION they lost **-17.8% and -19.4% per trade**, with CIs of [-31.8, -4.6] and [-34.0, -5.7].

### 4. Lifecycle gates do not rescue the bot's dip-rebound

- 49 configs of lifecycle windows (class, age, volume decay) on the nightcrawler entry: the median config
  loses -8.2% per trade.
- The single positive one (+0.9%, 13 coins, best coin 267% of profit) lost **-9.7%** on VALIDATION, with a CI
  of [-22.4, -4.8].

### 5. The late "drifter" is one cluster, and its rugs are priced in

- **Who the trades are:** every drifter trade is in the ticker-clone cluster.
  - These coins graduate instantly at absurd market caps ($1.6M-$700M).
  - Tickers repeat as separate mints: USDP, XRPN, WSOS, ATFS, XBC, WOSE, IOF, DAWS.
  - Steady bot bids lift them **+0.3% to +5% per hour**.
- **Their rugs on TRAIN:** 15 of these 40 coins rugged (a one-bar drop of more than 50%), 10 of them more than
  60 minutes after graduation. That is about 1.8% per coin-hour, so the drift roughly pays for the rug risk.
- **Why some configs show a CI above 0 on TRAIN:** their holding windows happened to contain no rug.
  - Center 6f57468754 (t ≥ 240 min, hold 120 min) makes **+2.5% on 20 trades**, CI [+1.6, +3.4].
  - Moving the entry age to 120, 300, 360 or 480 minutes adds one rug, and the mean falls to -0.2%, -0.3%,
    -0.5% and -1.5%.
  - Lengthening the hold to 180-360 minutes also adds a rug, and the CI crosses 0.
  - The neighbour median of the t=180 variant is -0.41%. That is a spike, not a plateau.
- **Falsification test:** the same calm-base rule on **organic** coins loses about -5% per trade (12 trades).
  So this is not a lifecycle law; it is one operator's bot.

## The 8 VALIDATION looks

Per trade at $20; portfolio from $100.

| ID | Config | TRAIN trades | TRAIN avg % [CI] | TRAIN portfolio / DD | VAL trades | VAL win % | VAL avg % [CI] | VAL portfolio / DD | Best coin share (VAL) |
|---|---|---:|---|---|---:|---:|---|---|---:|
| 5b02e1ff28 | drifter, t ≥ 180 min, range ≤ 1.03 over 60 bars, grad ≥ $5M, hold 120 min, stop 10% | 20 | +2.48 [+1.7, +3.3] | +8.2% / 0.9% | 5 | 40 | +0.52 [-1.5, +3.1] | +0.5% / 1.3% | 225% |
| 6f57468754 | same, t ≥ 240 min | 20 | +2.53 [+1.6, +3.4] | +7.0% / 1.5% | 5 | 40 | **-1.05** [-2.4, +0.2] | -1.1% / 1.6% | n/a |
| e038759d53, a625d9406c | same as 6f57468754 with a volume floor of $5k or $1k (identical trades) | 20 | +2.53 | +7.0% / 1.5% | 5 | 40 | -1.05 | -1.1% / 1.6% | n/a |
| d51828bc55 | drifter, t ≥ 120 min, range ≤ 1.08, grad ≥ $5M, hold 360 min, stop 10% (declared family center) | 22 | +7.94 [-2.5, +16.0] | +2.4% / 11.4% | 6 | 67 | +7.10 [-2.6, +21.4] | +5.8% / 1.4% | 95% |
| 039fa46a64 | runner: organic, 120-360 min, ≤ 0.4x peak, hold 30 min, dying-volume exit | 40 | +2.72 [-10.0, +17.0] | +8.1% / 35.6% | 13 | 31 | **-17.84** [-31.8, -4.6] | -41.9% / 48.9% | n/a |
| 8a5fa8cd03 | same, without the volume exit | 40 | +2.13 [-10.7, +16.9] | +44.5% / 31.8% | 13 | 38 | **-19.38** [-34.0, -5.7] | -42.2% / 48.9% | n/a |
| a3d1e6299d | gated dip-rebound, organic, 60-600 min, mcap $100k-$5M | 26 | +0.86 [-10.1, +12.2] | +1.2% / 34.0% | 8 | 25 | **-9.67** [-22.4, -4.8] | -15.3% / 24.9% | n/a |

**Shortlist rule.** It was declared in `f3_lifecycle_search.py` before any VALIDATION run:

- TRAIN: ≥ 15 trades on ≥ 10 coins, mean > 0 and portfolio return > 0;
- ranked by the CI low;
- at most 4 per family and 12 in total.

d51828bc55 was added afterwards as the drifter's second declared center, and is counted as a look.

## Robustness on VALIDATION (the three drifter candidates; all rejected)

Per-trade average %. Full data, including the trades' launch clusters, is in
`reports/f3-lifecycle-rejected.json` and `LAB/f3/robustness_validation.json`.

| Variant | 5b02e1ff28 | 6f57468754 | d51828bc55 |
|---|---:|---:|---:|
| base | +0.52 (portfolio +0.5%) | -1.05 (-1.1%) | +7.10 (+5.8%) |
| costs x1.5 | -0.21 | -1.76 | +6.33 |
| costs x2 | -0.93 | -2.48 | +5.57 |
| +1 bar latency | +0.65 | -1.20 | +7.04 |
| `wick_fill="worst"` / rug-aware fills | +0.52 | -1.05 | +7.10 (no stop was hit on VAL) |
| $10 positions | +0.30 (portfolio +0.1%) | -1.26 | +6.88 (+2.8%) |
| $40 positions | +0.61 (portfolio 0.0%) | -0.96 | +7.19 (+12.8%) |
| without the best coin | -0.81 | -1.48 | **+0.41** (USDP removed) |
| first half / second half of VAL | -0.87 (2 trades) / +1.44 (3 trades) | -2.80 / +0.12 | +10.11 / +4.09 (3 trades each) |

- **Worst wicks and rug-aware fills on TRAIN** take d51828bc55 from +7.94% to **+3.92%**, with a CI of
  [-12.4, +16.0]. Its 2 TRAIN rugs become about -100%.
- **d51828bc55's VALIDATION profit:**
  - 3 of its 6 VALIDATION trades end `end_of_data`, because they are right-censored.
  - One coin, **USDP, makes +40.6%** and carries 95% of the profit. In F2's trend family the same coin also
    carried most of the profit.

**Lookahead audit:** `audit_lookahead` is clean for all 6 distinct validated configs on all 448 TRAIN and 150
VALIDATION coins, with 2 random cuts per coin.

## Why it might work

These are the arguments for the hypothesis, recorded for completeness.

- **Survivorship inside the coin's life.** About 69% of graduates are dead within an hour. A coin still trading
  after the first dump has passed a filter: the creator's supply is out and the remaining holders chose to
  stay. A second leg from a quiet base is the classic chart pattern.
- **The late phase is cheap.** Coins above about $10M pay the 0.30% pool tier, so a round trip costs about 1%,
  and steady bot bids make a drift of 1-5% per hour. In principle a 2-6 hour hold clears costs.
- **Time structure is mechanical.** Launch farms run on schedules. If an operator's rug timing were stable, the
  age after graduation would be informative.

## Strongest reasons it is fooling us, and why everything is rejected

1. **One actor, not a lifecycle law.**
   - Every positive configuration trades one cluster of ticker-clone coins, and the same tickers are relaunched
     as new mints. The real sample is a handful of operator decisions, not 20 independent coins, so the coin
     bootstrap CI is too narrow.
   - The same calm-base rule on organic coins loses money.
2. **Short volatility.**
   - Win rates are 80-91% and medians positive, but a rug costs -56% (with "half" fills) to -100% (realistic
     fills).
   - The TRAIN CI is above 0 only in parameter cells whose holding windows missed every rug. One step to a
     neighbouring age or hold flips the sign.
3. **Multiple testing.**
   - 487 configs plus about 150 event-study groups. 19 of the 454 configs with enough trades have a CI above 0;
     about 11 would by chance if they were independent. Here they are not: all 19 are one cluster.
   - On VALIDATION, 0 of 8 pass.
4. **Too few out-of-sample trades.**
   - The drifter makes 5-6 VALIDATION trades. The positive one depends on one coin (USDP) and on three
     right-censored exits.
   - With splits by creation time, no TRAIN effect of this kind can be confirmed on VALIDATION.
5. **Lottery payoffs elsewhere.**
   - The organic-survivor results are driven by 1-3 coins (TINCAN +1,986%). They fail without the top coins on
     TRAIN, and lose 18-19% per trade on VALIDATION.
6. **Even if it were real, it is tiny.**
   - The best drifter portfolio makes +0.5% to +8% per day on $100. Its left tail is a one-transaction rug that
     no stop can catch.
   - At most 3 positions with multi-hour holds caps the throughput: thousands of signals were rejected for lack
     of a free slot.
7. **One day, one regime.** All of this is 22.5 hours of launches. The operator can change its schedule at
   will, and F2 already saw this happen within the same day.

## Files and reproduction

**Files:**

- Strategy: `research/lab/strategies/f3-lifecycle.py`.
  - `F3Params` holds the parameters; `F3Lifecycle` is the strategy; `factory(params)` builds the zero-argument
    factory.
  - The file name has a hyphen, so load it with importlib (see `f3_lifecycle_search.load_f3`).
- Search, shortlist, validation, robustness and counts: `research/lab/f3_lifecycle_search.py`.
- Event studies on TRAIN only: `research/lab/f3_eda.py`. Cuts are logged to `LAB/f3/eda_log.jsonl`.
- Tests: `research/lab/tests/test_f3_lifecycle.py` (31 tests). They cover:
  - the truncation audit and garbage-future invariance for all 6 entry and exit variants on synthetic lifecycle
    coins;
  - identical lifecycle state on truncated copies;
  - no class-level state;
  - no entry before graduation;
  - `max_entries` holding when a trade is stopped out inside its fill bar (with a negative control);
  - the audit on 60 real TRAIN coins.
- Finalists: `research/lab/finalists/f3-lifecycle.json` is `[]`. The rejected candidates use the same schema
  and are in `research/lab/reports/f3-lifecycle-rejected.json`.
- Data (not committed), under `LAB/f3/`: `runs.jsonl`, `eda_log.jsonl` and `robustness_validation.json`.

**Commands:**

```bash
cd /home/user/Claude
python research/lab/f3_eda.py checkpoints | events | drift      # TRAIN event studies
python research/lab/f3_lifecycle_search.py smoke                # 5
python research/lab/f3_lifecycle_search.py stage1               # 424
python research/lab/f3_lifecycle_search.py stage2               # 70 (58 new)
python research/lab/f3_lifecycle_search.py shortlist
python research/lab/f3_lifecycle_search.py validate             # pre-declared shortlist -> VALIDATION
python research/lab/f3_lifecycle_search.py validate d51828bc55  # declared family center
python research/lab/f3_lifecycle_search.py robust 5b02e1ff28 6f57468754 d51828bc55
python research/lab/f3_lifecycle_search.py count
python -m pytest -q research/lab/tests/test_f3_lifecycle.py
```
