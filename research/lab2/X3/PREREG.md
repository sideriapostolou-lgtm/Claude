# X3 pre-registration: buy the exhaustion of a selling climax, only in deep pools, later in the coin's life

- **Version:** `x3-v1`.
- **Written:** 2026-10-09, before any X3 run on TRAIN, VAL, TEST, CONFIRM or FINAL data. TRAIN was still being
  backfilled. Every constant and the whole grid (§7) were fixed in this file **before** the debug run on the census
  TRAIN third (§14). That run reports counts only: returns, exit reasons and gate labels hidden, no parameter chosen
  there.
- **Code:** `research/lab2/x3.py`, on the shared foundation `research/lab2/common.py`. Tests:
  `research/lab2/tests/test_x3.py`.
- **Protocol:** PLAN §3 (shared protocol), §3.5 (entry pass bars), §3.6 (automatic rejections) and §8 (stop rules),
  through common.py's `AsOf`, `backtest`, matched-timing placebo, `describe`, `verdict_entry`, trial ledger,
  shortlists and one-shot sessions. Stage gating and CLI follow `m1.py`.
- **Splits:** common.py's (TRAIN 10-01 → 10-05, VAL → 10-06 12:00, TEST → 10-07 19:37:30, CONFIRM 09-16 → 10-01,
  FINAL = census day).
- **Freeze.** The first official TRAIN run hashes this file into `X3/prereg.lock`. After that, `x3.py` refuses every
  stage if this file has changed. A change is a new version (`x3-v2`) in `X3/AMENDMENTS.md`, and its configs are new
  trials.

## 1. Hypothesis and mechanism

**Claim.** In the later part of a surviving coin's first three hours (g + 60 → g + 145 min), when its pool is
**deep** (market cap ≥ 1,470 SOL at the decision, the pump.fun fee-tier boundary), a one-minute **selling climax**
(the largest selling minute of the last half hour, ≥ 3 × the coin's median minute volume, a net outflow that moved the
price down) is followed by a partial reversion. Buying that exhaustion and selling into the rebound returns more than
a $20 round trip at the pool's own, cheaper cost, and more than a random entry into a deep pool of the same age.

**Why a reversion should exist** (the economic reason):

1. **A constant-product pool has no market maker.** An impatient seller who dumps a large position in one minute pays
   the full curve impact: an outflow ΔX from a pricing reserve X moves the price by ((X − ΔX) / X)². Nobody absorbs the
   flow at a quoted price; the price only comes back when new buyers arrive. Whoever buys after the dump is the
   liquidity provider to the impatient seller, and in order-book markets that role earns the short-term reversal
   (short-horizon reversal returns are compensation for supplying liquidity, larger when liquidity is scarce).
2. **Later and deeper is where the dump is least likely to be information.** By g + 60 min the factory airdrop dumps
   (creation + 16 min), the BOOST bid (g + 6 min) and the worst rug window (g + 15-30 min, `EXPERIENCE_GROUNDED.md` N5)
   are over. A coin still worth ≥ 1,470 SOL (≈ 3.6 × its graduation price, ≈ $170k at the census SOL price) has an
   active crowd of dip buyers and attention traders; a one-minute dump there is more likely one holder's exit than the
   end of the coin. A rug that empties the pool lands near the ~17.6 SOL floor and fails the depth gate by
   construction.
3. **Our cost is lowest exactly there.** The fee tier falls with market cap and our $20 has almost no impact on a
   pricing reserve of 160+ SOL. The required rebound is computed from the pool's **own reserves** at the decision
   (the exact round trip from X, y, the dated fee tier, SOL/USD and network fees), so the rule asks the rebound to beat
   the cheap cost of that pool, not the lab's average cost.
4. **Exact impact from reserves.** The climax outflow is read from the pricing reserve X = x + v after each bar
   (exact in B2), and the rebound target is the price at which half of that outflow has come back:
   P* = close_c × ((X_c + ½ ΔX) / X_c)². No candle heuristic is involved.

**Who loses.** The impatient climax seller (pays the impact we later collect) and the late sellers of the next
minutes who sell into the rebound we exit into.

**What a $20 round trip really costs in this universe** (`common.round_trip_pct`, census SOL/USD 116.1, 2026-10 fee
schedule, Ultra 10 bps, 20 bps buffer, 2 network fees; no rent):

| Market cap (SOL) | Pricing reserve X (SOL) | Pool fee / side | Round trip at $20 |
|---:|---:|---:|---:|
| 400 (fresh graduate) | 84 | 1.25 % | 3.70 % |
| 1,470 | 161 | 1.15 % | 3.32 % |
| 3,000 | 230 | 1.10 % | 3.16 % |
| 5,000 | 297 | 1.00 % | 2.93 % |
| 20,000 | 593 | 0.85 % | 2.58 % |
| 100,000 | 1,326 | 0.30 % | 1.46 % |

The task's "1.4-2.9 %" holds only above ≈ 5,000 SOL. Between 1,470 and 5,000 SOL, where most deep fresh graduates
will sit, the round trip is 2.9-3.3 %, only 0.4 points cheaper than a fresh pool. The worst-fill spread (entry at the
landing bar's high, exits at the next bar's low) comes on top and is probably larger than the fee saving after a
climax. **The edge has to come from the size of the rebound, not from the cost saving.**

**Why it may fail** (stated before any data; my prior that X3 passes TEST is about 10 %):

- Wave 1's candle dip rules (F1) lost on every split and every stress test; dips on fresh graduates continued more
  often than they reverted.
- A climax in a deep pool may be the first leg of a distribution (insiders selling into the crowd in several waves),
  which is D1's DIST class. X3 cannot see wallets, so it cannot tell the two apart; it relies on the late window and
  the depth gate.
- Fast bots may already buy every climax within seconds; our 30 s latency and the worst fill (the landing bar's
  high) then pay away the rebound.
- With next-bar exits, a take-profit touched by a wick fills at the next bar's low (§6): rebounds that last less than
  a minute are worth nothing to us.
- Deep coins in g + 60 → g + 145 min may be few: X3 may be underpowered (§14).

**Not a duplicate.**

- **G1** is a gate at g + 2 min; it never trades.
- **S1** needs B1 wallet ledgers (insider inventory) and trades from g + 6 min.
- **D1** classifies the *sellers* of a dip with B1 wallet data (cost basis, insider share), trades ORGANIC slow
  graduates only, from age 10 min, with no depth condition. X3 uses no wallet data, trades instant and slow
  non-factory, non-operator coins alike, only after g + 60 min and only in deep pools, and its trigger is a volume
  climax measured against the coin's own volume and the pool's reserves, not a 15-minute drawdown.
- **M1** rides mechanical bids on OPERATOR coins. X3 excludes OPERATOR coins (PLAN §4.2: "OPERATOR coins go only to
  M1") and buys against a sell burst, not with a steady bid.
- **X1 / X2** (wave-2 siblings) follow wallets and rank buyer breadth across coins; X3 is single-coin, sell-side and
  contrarian.

## 2. Data and instrument

- Tables: `graduates`, `b2_coins`, `b2_bars`, through `common.load()` (SOL-quoted, not Mayhem, virtual reserve known,
  complete B2 window [g, g + 180 min)). **B1 raw trades are not used**, now or later. CryptoHouse is never queried.
- Every feature is read through `common.AsOf` (cutoff τ = t − 20 s; completed minute bars only).
- **Reserves.** `bars.X` is the pricing reserve x + v after each completed minute (exactly close × y_close in B2) and
  `bars.y` the token reserve. On a constant-product pool price = X / y = X² / k, so the climax outflow and the rebound
  target are exact functions of X.
- **Liquidity events.** A bar where tokens leave or enter the pool outside trades (y differs from
  y_prev − buy_tok + sell_tok by more than 0.5 % of y_prev, M1's token-conservation test) changes k; its "outflow" is
  not a sell climax, so no climax is read there.

## 3. Universe and class

A decision considers a coin only when all of these hold at the decision time t (τ = t − 20 s):

1. **Age** t − g in [60, 145] min. The upper bound leaves room for the 30-minute hold inside the registered deadline
   g + 178 min (§6), so no trade is cut by the data horizon.
2. **Class OTHER** under the PLAN §4.2 on-chain rules M1 uses, in PLAN order:
   - OPERATOR if w120 buy SOL ex-AGENT ≥ 500 and w120 buyers ex-AGENT ≤ 30 → **excluded** (M1's universe);
   - FACTORY if `grad_delay_s` ≤ 5 and the w120 top-5 share ex-AGENT ≥ 0.85 → **excluded** (airdrop dumps);
   - OTHER otherwise (ORGANIC, COMPLETED, NEWS and instant non-factory coins).
   - An unscanned creation uses `grad_delay_lb_s` (1,800 s, not instant). A NULL input that decides the class makes
     it NULL and the coin is skipped (fail closed). NULL is never 0.
3. **Alive** (`AsOf.alive`): ≥ $1.5k USD volume over the last 15 min and market cap ≥ $6k.
4. **Deep:** market cap at the last completed close ≥ **1,470 SOL**. Fixed at the fee-tier boundary the task names;
   never searched.

## 4. Features (all through `common.AsOf`, completed bars only)

Bar indices: the decision sees completed bars 0 … k − 1. The **climax bar** is c = k − 1 (timing `now`) or
c = k − 2 (timing `confirm`, §5). `vol_j` = buy_sol_j + sell_sol_j (user-side SOL).

| Feature | Definition |
|---|---|
| `base_vol` | median of `vol` over bars c − 30 … c − 1 (minutes without trades count as 0), floored at 0.05 SOL |
| `climax` | all of: sell_sol_c ≥ 3 × `base_vol`; sell_sol_c ≥ every sell_sol of bars c − 30 … c − 1 (the largest selling minute of the last half hour); sell_sol_c > buy_sol_c; close_c < close_{c−1}; X_c < X_{c−1}; no liquidity event in bar c (§2); one-minute drop 1 − close_c / close_{c−1} ≤ 50 % (a larger drop is a rug, M1's label) |
| `outflow` ΔX | X_{c−1} − X_c (SOL that left the pricing reserve in the climax minute) |
| `target` P* | close_c × ((X_c + ½ ΔX) / X_c)²: the price once half of the outflow has returned |
| `tp` | P* / close_{k−1} − 1, the rebound still available from the last completed close |
| `rt` | exact $20 round trip at the decision state: `common.round_trip_pct` on k = X_{k−1} · y_{k−1}, price close_{k−1}, the dated fee tier, SOL/USD of the last minute before τ, 2 network fees |
| `exhausted` (timing `confirm` only) | bar k − 1 after the climax has sell_sol ≤ ⅓ sell_sol_c and close_{k−1} ≥ close_c (selling dried up, no lower close) |

The climax needs bars c − 31 … c, so it is defined from age ≈ 32 min; the window starts at 60 min.

## 5. Entry rule

At the first decision time (common.py grid: minute boundary + 20 s) where every condition holds, at most once per
coin per config:

- §3 universe (age, class OTHER, alive, deep);
- `climax` at bar c;
- timing `now`: c = k − 1 (the order lands in the minute after the climax);
  timing `confirm`: c = k − 2 and `exhausted` (the order lands two minutes after the climax);
- **cost condition:** `tp` ≥ m × `rt`.

## 6. Exits (sell at the first of)

| Exit | Rule |
|---|---|
| Rebound target | take-profit at +`tp` from the entry fill (the target's distance from the decision close, applied to the fill) |
| Stop | −15 % from the entry fill (PLAN D1 / X1 grid level) |
| Time | H minutes after the entry fill (H ∈ {10, 30}) |
| Deadline | no later than g + 178 min (never binds: decisions stop at g + 145 min) |

All exits are mechanical (`common.ExitSpec`), so the matched placebo runs the same exits with the signal's own
`tp`, stop and H.

**Fills** (the task's "worst fills, next-bar stops"): `common.FillConfig(exit_delay_bars=1)`.

- Entry: the landing bar's max(open, high), 30 s after the decision.
- Every exit (target, stop, time) triggered in bar j fills at bar j + 1's min(open, low). A target touched only by a
  wick therefore earns nothing.
- Stops are checked on the entry bar too (entry at its high, then its low).
- Costs: dated PumpSwap tier by market cap, + 10 bps Ultra, + 20 bps buffer, network fees; impact on the pool's own
  k, pricing on X = x + v.

## 7. The TRAIN grid: exactly 8 configurations, every one a trial

**m ∈ {2, 4} × timing ∈ {`now`, `confirm`} × H ∈ {10, 30} min.**

- m = 2: the rebound left must be at least twice the pool's exact round trip; m = 4: four times. At the census SOL
  price and 1,470-5,000 SOL this is a half-outflow rebound of ≥ 6-7 % or ≥ 12-13 %, i.e. climax drops of roughly
  ≥ 12 % or ≥ 21 %.
- `now` buys the minute after the climax (catches the earliest rebound, risks a cascade); `confirm` waits one minute
  for the selling to dry up (avoids cascades, pays part of the rebound).
- H = 10 min (fast liquidity rebound) or 30 min (PLAN D1-E1's bracket horizon).
- Fixed in every config, never searched: depth 1,470 SOL, age window [60, 145] min, climax multiple 3, 30-bar
  baseline, half-outflow target, stop 15 %, the class rule, alive, the fill model, $20.
- Each config's params dict carries every constant above, the fill model and the version: any change is a new trial.
- **Gate:** one more trial, `X3-gate` (§8).
- **X3's total is 9 trials**, on top of the ledger's 2,575 wave-1 configurations.

**Stress and sensitivity runs** come from every `backtest` call and are never used to select:

- costs × 1.5;
- rent of $0.22;
- latency 60 s;
- `same_bar_exits` = `FillConfig()` (exits fill in the trigger bar: the optimistic reference).

## 8. Reversion gate (stop rule, TRAIN, before any P&L)

**Question.** Does a climax in a deep pool predict a rebound, beyond what any deep pool does at that age, by more than
the pool's own round trip, before fills? If not, no exit rule can rescue X3.

**Events.** TRAIN coins; every decision where the entry rule for (m = 2, timing `now`) holds (the loosest config);
after an event, the coin's next 30 minutes are skipped so labels never overlap.

**Label** (an outcome, never a feature): the mid-price change close(t + H) / close(t) − 1 for H ∈ {10, 30} min, read
through AsOf H minutes later.

**Matched random control.** For each event, up to 20 random decisions (seeded rejection sampling, at most 2,000 tries
per event) in TRAIN coins of the same split with decision age within ± 120 s, eligible as the placebo (§10: age window,
class OTHER, alive, deep), with the same label.

**Statistic.** excess_H = mean over events of (label − mean label of its matched draws).

| Result | Condition | Consequence |
|---|---|---|
| **UNDERPOWERED** | < 50 events or < 30 coins | X3 halts; the grid is not run |
| **KILL** | excess_H < mean `rt` of the events for both H | **X3 is dead.** The grid is never run, and every later stage refuses |
| **PASS** | excess_H ≥ mean `rt` for at least one H | continue with the configs of the passing H only |

**Reported, never decisive:** the coin-bootstrap 95 % CI of each excess; the raw mean labels of events and draws;
excess by depth bucket (1,470-3,440, 3,440-9,820, ≥ 9,820 SOL: fee-tier boundaries); the same statistic for
**shallow** pools (market cap 100-1,470 SOL at the decision, their own shallow matched draws), which is the
"depth-aware" contrast; the `confirm` subset.

## 9. Procedure by stage (`python research/lab2/x3.py …`)

### Every stage

A stage refuses to run unless:

- `X3/PREREG.md` exists, and matches `prereg.lock` once locked;
- PLAN §8 rule 1 holds for its split (`common.validation_gates`: V1/V2/V4 on the split's dates, validated after the
  data was fetched; V3 on the census sample). The debug stage only reports it;
- the split's coverage is complete: every chain hour scanned for curve and B2, no B2 hour mid-run, ≤ 5 % of tradeable
  coins lacking a complete B2 window, a SOL/USD series that starts before the split's coins. FINAL is exempt from the
  completeness part;
- TEST / CONFIRM / FINAL have their flags (`LAB2_ALLOW_TEST`, `LAB2_ALLOW_CONFIRM`, `LAB2_ALLOW_FINAL`). `x3.py` never
  sets them.

### TRAIN (all searching)

1. Run the reversion gate (§8). On KILL or UNDERPOWERED, stop.
2. Run the configs whose H passed, each with the matched control (§10) and the stress runs.
3. **Shortlist rule (one config).** A config qualifies when it has ≥ 30 trades from ≥ 20 coins, mean > 0, mean
   without the top 2 trades > 0 and matched-control `mean_diff` > 0. The shortlist is the qualifier with the highest
   coin-bootstrap 90 % CI lower bound (ties: higher mean, then grid order), written with `common.write_shortlist` and
   frozen at the first VAL run.
4. Nothing qualifies: **NO_CONFIG** if some config had ≥ 30 trades from ≥ 20 coins, **UNDERPOWERED_TRAIN** otherwise.
5. A decision on complete TRAIN is final. A re-run needs `--rerun-reason` naming a data correction; the previous
   result is archived as `train_prev_<ts>.*`.
6. `--allow-partial` runs a PROVISIONAL TRAIN on partial data: it writes `train_prelim.*`, never a shortlist or a lock,
   and never unlocks VAL.

### VAL (the one shortlisted config, once)

| Decision | Condition | Consequence |
|---|---|---|
| **UNDERPOWERED_VAL** | n < 5 | stop |
| **FAIL_VAL** | n ≥ 5 and (mean ≤ 0 or mean without the top 2 ≤ 0 or matched-control `mean_diff` ≤ 0) | stop (PLAN §8 rule 7 input) |
| **SELECTED_UNDERPOWERED** | 5 ≤ n < 15, all three > 0 | proceed, flagged |
| **SELECTED** | n ≥ 15, all three > 0 | proceed |

### TEST (one run, one `common.one_shot_session`)

- **Verdict** = `common.verdict_entry(test, val=VAL trades, min_mean=0.03, control_margin=0.06)`: PLAN §3.5 items 1-8,
  criterion 10 (≤ 10 % of trades closed by the data horizon) and the §3.6 auto-rejections. Item 9 (FINAL mean > 0) is
  judged in the overall verdict after FINAL.
- REJECTED if auto-rejected; UNDERPOWERED if < 60 trades or < 40 coins; FAIL if any criterion fails; INCOMPLETE if
  any is missing or > 10 % censored; PASS otherwise.
- With a 1.3-day TEST, **UNDERPOWERED is likely** (§14).

### CONFIRM (09-16 → 10-01; one run, never searched)

- Precondition: TEST is not REJECTED, and TEST mean > 0 or TEST n < 5 (no evidence either way).
- Same config, same verdict as TEST. CONFIRM is the powered out-of-sample test.

### FINAL (census day; only after TEST)

- One run on all of FINAL (FINAL consumes its thirds). **Criterion 9 is judged on the census VAL and TEST thirds
  only**; the TRAIN third (used to debug the code) is reported apart.

### Overall X3 verdict

**EDGE** needs: gate PASS; a shortlisted config; VAL SELECTED or SELECTED_UNDERPOWERED; TEST not REJECTED with
(TEST mean > 0 or n < 5); CONFIRM PASS; FINAL mean > 0. Otherwise **KILLED** (gate), **UNDERPOWERED** (gate, TRAIN,
VAL or CONFIRM) or **NO EDGE**.

## 10. Controls

- **Matched random control** (PLAN §3.4, judged): common.py's matched-timing placebo (`run_placebo`, the function
  `backtest` uses), 20 draws per signal, random coins of the same split at a decision age within ± 120 s, **eligible = age window, class OTHER, alive and deep (≥ 1,470 SOL)** at
  the draw's own decision, the signal's own exits (target %, stop, H). It isolates the climax timing from the
  "deep survivors" effect. Feeds §3.5 item 5 (≥ +6 points), the TRAIN shortlist and VAL.
- **`any_depth` control** (reported, never judged): the same without the depth condition. Signal − `any_depth` minus
  signal − matched shows how much of the result is just "deep coins".
- Both are `common.run_placebo` (same eligibility, seeds and exits as `backtest`'s internal call), run right after the
  logged `backtest` look with `max_tries` = 2,000 per signal instead of backtest's 200: deep coins are rare, and at 200
  tries the one debug signal got 3 of 20 matched draws (§14, fix 2). The draw count is reported.

## 11. Metric and statistics

- Unit: `ret_net` per $20 trade, one entry per coin per config.
- Coin-bootstrap and 6-hour block-bootstrap CIs (10,000 / 5,000 draws), mean without the top 2, top-coin share,
  halves, the $100 / 5-slot portfolio, costs × 1.5, the deflated Sharpe ratio counting every trial in the ledger,
  exit reasons, mean `rt` and mean `tp` of the trades, `horizon` exits.

## 12. Kill criteria and declarations

| Rule | How X3 applies it |
|---|---|
| Stop rule 1 (data first) | stages refuse until V1-V4 pass for the split |
| Stop rule 2 (fills) | minute-bar worst fills with next-bar exits until the PLAN X1 fill engine exists. If it finds them off by ≥ 1 point, the frozen config is re-run with replayed fills, no new search |
| Reversion gate (§8) | KILL before any P&L |
| Stop rule 7 | FAIL_VAL is reported to the lead |
| Stop rule 8 | every config counts (§7) |

Declarations passed to `auto_rejections`: `uses_organic_flow = False`, `uses_wallet_reputation = False`,
`uses_truncated_windows = False`, `uses_current_state_fields = False`. X3 counts no flow as organic.

## 13. Deviations and limits, stated up front

| Area | Limit |
|---|---|
| Instrument | One-minute bars: a climax and its rebound inside one minute are invisible; a climax split across two minutes may fail the "largest minute" test. Minute sums mix the climax seller with everyone else |
| Sellers | No wallet data: X3 cannot tell a capitulating holder from an insider distributing in waves (D1's question) |
| Fills | Minute-bar worst fills with next-bar exits, not replayed fills. Both sides pay a bar's range |
| Horizon | B2 ends at g + 180 min: decisions stop at g + 145 min, holds end by g + 178 min |
| Depth | Market cap from the last completed close; k changes only by liquidity events (excluded in the climax bar) and LP fees (≤ 0.2 % per hour), so X² / k is exact to that |
| SOL/USD | Every non-debug stage refuses until the series covers the split (`common.coverage_problems`) |

## 14. Debug findings and expected sample (census TRAIN third, counts only)

**The run.** `python research/lab2/x3.py --debug` writes `X3/debug.md` and `X3/debug.json` (trials go to a scratch
ledger, never `trials.json`). 450 usable coins created over 12.5 h (0.52 days). Returns, exit reasons, fill prices and
gate labels are hidden. The grid and every threshold above were fixed before this run; nothing was changed after it
except the two sampling fixes below.

**Fixes made while debugging** (mechanics only, from counts, before any TRAIN data; no trading rule changed):

1. The gate's matched draws use up to 2,000 tries per event (was 200): with 13 deep coins among 450, 200 tries gave
   too few eligible draws. Now 16 of 20 per event.
2. The strategy's matched placebo and the `any_depth` control call `common.run_placebo` with `max_tries` = 2,000
   after the logged `backtest` look (§10). The one debug signal got 3 of 20 matched draws at 200 tries, 16-17 now.

**Counts** (features only):

| Measure | Census TRAIN third (0.52 d) |
|---|---:|
| Classes at g + 60 min | FACTORY 183, OPERATOR 34, OTHER 233 |
| OTHER coins ever deep (≥ 1,470 SOL) at a decision in g + 60 → 145 min | **13** (all alive) |
| Deep coin-decisions (OTHER, in the window) | 451 |
| Deep `now` climax events (m = 2), i.e. gate events | **1** (1 coin; 1,844 SOL; rt 3.29 %; tp 11.7 %; climax drop 19.5 %; age 100 min) |
| Deep `confirm` events (m = 2) | 1 (the same climax) |
| m = 4 entries | 0 |
| Shallow (100-1,470 SOL) climax events (diagnostic) | 16 from 15 coins (median 250 SOL, rt 3.8 %) |
| Entries per config | m = 2: 1 each (≈ 1.9 a day); m = 4: 0 |

**Why so few** (a feature-only check of the detector, `scratchpad/x3/debug_detector.py`): at the 451 deep
decisions every last bar traded and no bar had a liquidity event, so the detector reads the data as intended. Deep
coins are busy: their median minute volume is 58 SOL (p10 2.6, p90 204). One-minute drops of ≥ 12 % happened at 27 of
the 451 deep decisions, but only 8 decisions had a selling minute ≥ 3 × the median volume, and only 1 of the large
drops was a volume climax. **In deep pools, large one-minute drops mostly come without a volume spike.** The
pre-registered trigger is a volume climax, so it is rare there by construction.

**Expected sample if the census rate holds** (≈ 1.9 deep climax events a day):

| Split | Days | Gate events / m = 2 entries | m = 4 entries |
|---|---:|---:|---:|
| TRAIN | 4 | ≈ 8 | ≈ 0 |
| VAL | 1.5 | ≈ 3 | ≈ 0 |
| TEST | 1.32 | ≈ 2.5 | ≈ 0 |
| CONFIRM | 15 | ≈ 29 | ≈ 0 |

**What this implies, stated before any TRAIN data:**

- The gate needs ≥ 50 events from ≥ 30 coins. TRAIN is expected to give about 8, so **the expected outcome is
  UNDERPOWERED_GATE: X3 halts on TRAIN without a P&L.** Even CONFIRM-sized data (≈ 29) would not reach the bar.
- That is the pre-registered answer, not a code failure. I do **not** relax the trigger: doing so after these counts
  would be choosing a parameter on FINAL data.
- If the lead wants the deep-pool question answered anyway, the candidate is a **new** hypothesis (`x3-v2`, new
  trials): a net-outflow drop in a deep pool **without** the volume-spike condition (≈ 27 large drops per 451 deep
  decisions here, before the cost condition). It overlaps D1's candle dip E1 (minus D1's wallet classes and organic
  universe), which is why it is not added to this grid.
