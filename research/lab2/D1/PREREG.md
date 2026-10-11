# D1 pre-registration: buy capitulation dips, not distribution dips (version `d1-v1`)

Written 2026-10-09, **before any TRAIN run**. At writing time no TRAIN, VAL, TEST or CONFIRM data existed (the
backfill was still adding days), and no B1 trade table existed for any split. The only data touched was the census
TRAIN third (`final_train`), and only to debug code and count events. No return was looked at, by parameter or
otherwise.

This file is frozen at the first TRAIN run: `d1.py` writes `D1/prereg_lock.json` (SHA-256 of this file) and every
later stage refuses to run if this file changed. Changing anything below is a **new version** (new `VERSION`
string, new trials counted, a new lock), never an edit.

Code: `research/lab2/d1.py`. Tests: `research/lab2/tests/test_d1.py`. Plan: PLAN §4.4 (D1), §3 (protocol),
§8 stop rule 4.

---

## 1. Question and mechanism

Two kinds of dip look identical on candles:

- **Distribution.** Insiders still holding inventory bought 10x below the price keep selling. The dip continues.
- **Capitulation.** Late organic holders sell at a loss and empty their positions. Their selling runs out fast.

**Question.** After all costs, at $20 per trade, does buying a candle dip *only when the sellers look like
capitulators* make money, and do capitulation dips beat distribution dips by a margin worth trading?

The wave-1 lab's candle-only dip strategies (F1) lost on every split (RESULTS.md). D1 tests whether **who is
selling** rescues the idea.

## 2. Data and universe

**Tables.** All are read through `common.load()`:

- `graduates.parquet`;
- `b2_coins.parquet`;
- `b2_bars.parquet` (minute bars);
- `b1_trades.parquet` (B1, backfill phase P4): non-dust trades of [created, g + 120 min], curve and PumpSwap,
  with wallets as `cityHash64`.

Every feature goes through `common.AsOf` (cutoff τ = t − 20 s). Bars come from completed minutes only, static
fields are read at their legal time, and B1 rows are those with `ts ≤ τ`.

**Universe.** A coin must pass every one of these, in order. Each condition is a coin-level fact known by
g + 420 s:

1. **Usable and tradeable** per `common.load` (SOL-quoted, not Mayhem, virtual reserve known, full B2 window).
2. **Creation scanned** (`curve_partial` is False). Insider roles need the curve phase from creation.
3. **Not an instant graduate:** `grad_delay_s` > 5 s. P4 collects no B1 for instant graduates.
4. **G1-chain class ORGANIC** (§2.1).
5. **B1 rows present** for the coin.

### 2.1 G1-chain class (PLAN §4.2 on-chain rules, applied in this order)

| Order | Class | Rule |
|---:|---|---|
| 1 | OPERATOR | `amm_buy_sol_2m` ≥ 500 and `amm_buyers_2m` ≤ 30 |
| 2 | FACTORY | `grad_delay_s` ≤ 5 and `amm_top5_share_2m` ≥ 0.85 (other instant graduates are INSTANT) |
| 3 | COMPLETED | `grad_delay_s` > 5 and any of: `completer_sol`/30 ≥ 0.6, `curve_top3_buy_sol`/`curve_buy_sol` ≥ 0.6, `curve_n_buyers` < 15 |
| 4 | UNRESOLVED | A rule above needs a NULL input. The coin is excluded (fail closed) |
| 5 | ORGANIC | Everything else |

How the inputs are built:

- `amm_buy_sol_2m` = `w120_buy_sol` minus the AGENT's own w120 buys (taken from the stored top-10 list).
- `amm_buyers_2m` = `w120_n_buyers` minus 1 when the AGENT bought.
- `amm_top5_share_2m` = `snap.top_share("w120", 5, exclude_agent=True)`.
- **NEWS** needs IPFS metadata, which we do not have, so it is merged into ORGANIC.

This is D1's own fixed copy of the PLAN rules. It does not import `g1.py`, so a later G1 change cannot move D1's
universe.

### 2.2 Data readiness

A stage refuses to run (exit code 2) unless all of these hold:

- the split's B2 coverage is `complete` per `common.coverage_report`;
- B1 covers **≥ 95 %** of the split's usable coins with creation scanned and `grad_delay_s` > 5;
- `FLOW/validation.json` shows V1-V4 PASS (PLAN stop rule 1).

`--stage train --allow-partial` runs on incomplete data as a **preview**. It writes no shortlist, so it cannot feed
VAL. Its trials still count (the configs are the same as the full run's, so a later full run adds no new trials).

### 2.3 Decision window and data limits

- **Decisions** run on the common grid: t = minute boundary + 20 s.
- **Entries need all of:**
  - age at the minute close τ − g ≥ 10 min;
  - t − g ≤ 120 min (B1 ends at g + 120 min);
  - a complete B1 window for the coin. P4b (research/flow/b1c.py) has no per-coin trade cap
    (`B1_MAX_TRADES = None`), so no prefix is truncated; coins without a complete B1 window are not scored.
    (Amended 2026-10-09 before any TRAIN run: the earlier text described P4's 20,000-trade cap.)
- **Exits** may run to the end of the 180-minute B2 window. A position still open there closes at the horizon.

## 3. Event E1: the candle dip (PLAN §4.4, unchanged)

E1 is evaluated at the minute close τ. All of these must hold:

- `dd15` = 1 − close / max(high over the 15 completed minutes ending at τ) ≥ **0.25**;
- close ≥ **3 × p_floor**, where:
  - p_floor = k / (1e9 − burned)²;
  - k = X·y after the last completed minute, with X = the pricing reserve x + v;
  - burned ≈ AGENT tokens bought, because BOOST burns what it buys. This is estimated per minute as the AGENT's
    SOL × that minute's tokens per SOL over all buys;
- age (τ − g) ≥ **10 min**;
- USD volume over the last 15 completed minutes ≥ **$1,500**.

**A known property, seen in debug counts only.** On the census TRAIN third the first E1 of most universe coins fires
at age 10.2-10.9 min (quartiles), because the post-graduation spike is still inside the 15-minute window. E1 then
holds for long stretches: 1,957 event-minutes on 64 coins. In practice D1 is therefore "the flow class decides
when, inside a coin that is ≥ 25 % off its recent high". E1 stays exactly as the PLAN wrote it. Changing it on
the strength of census data would be a search on FINAL data.

## 4. Roles and seller features

All of these are computed on the B1 prefix up to τ, replayed in chain order.

### 4.1 Ledger conventions

- **pos_w** = tokens bought − tokens sold. It may go negative.
- **Average-cost basis.**
  - A buy adds its user-side SOL to the wallet's cost. If the position was negative, only the part of the buy
    that does not cover the short is added.
  - A sell removes cost × covered / held, where held = max(pos_before, 0) and covered = min(tokens sold, held).
- **Orphan part** = tokens sold − covered. It costs 0, and it counts only when it is > 2 % of the sell, because B1
  dropped dust buys.
- **Peak** is the running maximum of pos_w.
- **Pooled accounts** (`common.POOLED_ACCOUNTS` plus `pooled_accounts.json`, and the `pooled` flag from
  `wallet_dict`) are excluded from every role and every feature, in both numerators and denominators.

### 4.2 Roles as of τ (PLAN §3.2)

| Role | Rule |
|---|---|
| CREATOR | `cityHash64(creator)` |
| BUNDLE | A curve buy in the creation slot `c_slot` |
| SNIPER | First curve buy ≤ created + 60 s, or among the first 20 distinct (non-dust) curve buyers |
| COMPLETER | `cityHash64(completer30)` |
| TRANSFEREE | Any sell with an effective orphan part at or before τ. Transfers are not used (no B4 table) |
| INSIDER | The union of the five roles above, minus pooled accounts |
| AGENT | `cityHash64(agent_wallet)` once `agent_known_at` ≤ τ |
| BOT | In-coin rule only (no registry): ≥ 4 trades, and either a median hold < 10 s (hold = sell time − that wallet's last buy) or ≥ 3 sells within 60 s of a buy |
| WASH | Any trade that follows the same wallet's opposite-side trade within 60 s with a token size within 5 % |
| MECH | PLAN §4.5, on pool trades in (τ − 30 min, τ]: not AGENT or CREATOR; ≥ 6 buys; sells ≤ 10 % of buy SOL; CV of the gaps between buys < 0.25; CV of buy sizes < 0.5 (population SD); \|Spearman(size, 60 s pool return before each buy)\| < 0.3. A constant series counts as ignoring price |
| ORGANIC | Everyone not INSIDER, AGENT, BOT, WASH, MECH or pooled. DUST does not exist in B1 |

### 4.3 Features over the sells in (τ − 180 s, τ]

| Feature | Definition |
|---|---|
| `sopr3` | Σ SOL received / Σ cost basis of the tokens sold. +∞ if the basis is 0 and SOL > 0. NULL if there are no sells |
| `ins_sell_share3` | SOL from INSIDER sells / all sell SOL. NULL if there are no sells |
| `n_sellers3` | Distinct sellers |
| `full_exit_share3` | SOL of sells that left pos ≤ 1 % of the seller's peak / all sell SOL. Reported only, never used in a rule |
| `insider_rem` | Σ_{w∈INS(τ)} pos⁺_w(τ) / max over s ≤ τ of the same sum. The running sum is over chain order. NULL if insiders never held anything |
| `org_buyers3` | Distinct ORGANIC buyers in (τ − 180 s, τ] |

## 5. Classes (PLAN §4.4)

| Class | Conditions |
|---|---|
| CAP (strict) | `sopr3` < 0.8, `ins_sell_share3` < 0.2, `n_sellers3` ≥ 8, `insider_rem` < 0.15 and `org_buyers3` ≥ 5 |
| CAP (loose) | Same as strict, except `sopr3` < 1.0 and `n_sellers3` ≥ 5 |
| DIST | `sopr3` > 2 and `ins_sell_share3` > 0.5 |
| MIXED | Anything else, including "no sells in the last 3 min" |

A NULL input never satisfies a condition (fail closed).

## 6. Strategy, fills, costs and controls

**Entry.** One entry per coin per run. Take the **first** decision at which E1 holds and the class equals the
config's `entry_class`. The class `ALL` takes any class.

**Exits:**

| Exit set | Rule |
|---|---|
| `bracket` (PLAN E1 exit) | Take profit +25 %, stop −15 %, time limit 30 min, all relative to the entry fill |
| `s1` (PLAN §4.3 exit set) | A 30 % trail plus 90 min (mechanical), plus flow exits checked at every decision (see below) |
| event study | A fixed hold of 15, 30 or 60 min; time exit only, no stop |

The flow exits of the `s1` set fire on any of these:

- `org_net5` ≤ −1 SOL (ORGANIC buys − sells over (τ − 300 s, τ]);
- `orphan_share10` > 0.25;
- the creator has sold ≥ 20 % of its peak since the entry decision;
- insider holdings, for the INS(τ) set, have grown by > 2 % of supply since the entry decision.

Placebo positions get the same rule; it needs only their decision time.

**Fills and costs** are `common`'s defaults:

- `FillConfig()`: $20, 30 s latency, "worst" minute-bar fills (entry at the high side of the landing bar, exits at
  the adverse side, stops checked on the entry bar);
- PumpSwap pricing on X = x + v;
- `costs.py` fee tiers as of the trade date, plus Ultra 10 bps, a 20 bps haircut and network fees.

Sensitivity runs report the same config under: `entry_bar_exits=False`, `exit_delay_bars=1`, "open" fills, and
rent $0.22. They are never used to choose.

**Controls:**

1. **Matched placebo (PLAN §3.4).** For every signal, 20 random entries in random universe coins of the same split,
   at a decision age within ±2 min of the signal's, with the same exits. A placebo entry must meet every **non-dip**
   E1 filter (age, floor multiple, 15-minute volume) inside the decision window. It comes from the same
   `backtest()` call.
2. **Candle-only control.** The `ALL` event class: the first E1 event per coin, whatever its flow class. This is the
   F1-like trigger on the same coins, so CAP − ALL is what the trade-flow data adds.

**Same-coin random times are not used.** Choosing coins because they later have an event, then drawing a random time
in them, leaks the future into the control.

## 7. The TRAIN grid: 18 trials, all logged

Every (hypothesis, params) below is one trial in `research/lab2/trials.json`. Every params dict also carries
`"version": "d1-v1"`.

**Hypothesis `D1`: 3 strategy variants.** The PLAN allows 6. The 3 E2 variants are deferred (§12).

| Variant | Entry class | CAP definition | Exit set |
|---|---|---|---|
| V1 | CAP | strict | `bracket` |
| V2 | CAP | loose | `bracket` |
| V3 | CAP | strict | `s1` |

**Hypothesis `D1-event`: 15 event-study cells.** The classes are CAP (strict), CAP_LOOSE, DIST, MIXED (under the
strict CAP) and ALL. The fixed holds are 15, 30 and 60 min. Each cell is the first event of that class per coin.

**Metric.** Per-trade net return `ret_net` (a fraction of the $20), with "worst" fills and every cost included.
Statistics resample by coin (10,000 draws). The deflated Sharpe ratio counts every trial in the ledger, including
the lab's 2,575 configurations.

TRAIN also reports these contrasts at 15, 30 and 60 min, each with a coin-clustered bootstrap CI that resamples
coins jointly:

- CAP − DIST;
- CAP_LOOSE − DIST;
- CAP − ALL.

**VAL shortlist rule (≤ 2 configs).** It is written by the TRAIN stage, to `shortlists/D1.json` and
`shortlists/D1-event.json`:

1. **Qualifying variants** have ≥ 30 TRAIN trades from ≥ 20 coins.
2. **Pick.** Shortlist the top 2 qualifying variants by TRAIN mean `ret_net`; ties go to the lower variant number.
   If only one qualifies, shortlist that one.
3. **None qualifies.** Shortlist [V1, V2], the PLAN's primary rule and its loose version. Status is
   `SHORTLISTED_UNDERPOWERED`.
4. **`D1-event`** gets 2 configs: CAP at 30 min (the loose CAP if the first shortlisted variant is V2), and DIST at
   30 min.

A `--allow-partial` TRAIN run writes no shortlist.

## 8. VAL: the stop-rule gate, then selection

**Primary horizon: 30 min.** That is the E1 bracket's time limit, fixed here before any data.

**Gate (PLAN §4.4 and stop rule 4).** Compute CAP@30 − DIST@30 on VAL. These are two `D1-event` runs from the
shortlist, and the CI is coin-clustered (95 %).

| Status | Condition | Consequence |
|---|---|---|
| UNDERPOWERED | Either class has < 20 trades | The rule is not evaluated. D1 is not killed, and it cannot PASS |
| KILL | Difference < **5 points** | **D1 dies.** No TEST, CONFIRM or FINAL |
| PASS | Difference ≥ **10 points** and the 95 % CI lower bound > 0 | The gate part of the D1 pass bar is met |
| WEAK | Anything else | Not killed, but D1 cannot PASS |

**Strategy runs.** Run the ≤ 2 shortlisted `D1` configs on VAL. The costs × 1.5 stress is automatic.

**Selection for TEST** (skipped on KILL):

- the shortlisted config with the higher VAL mean, among those with ≥ 15 VAL trades;
- ties go to shortlist order;
- if none has 15 trades, the first shortlisted config.

## 9. TEST, CONFIRM and FINAL

**TEST** (`LAB2_ALLOW_TEST=1`, exactly one run of the selected config):

- `common.verdict_entry` with the VAL trades gives the PLAN §3.5 entry bar:
  - ≥ 60 trades from ≥ 40 coins, otherwise UNDERPOWERED;
  - mean ≥ +3 %;
  - 90 % CI lower bound > 0;
  - mean > 0 without the top 2 trades;
  - ≥ 6 points over the matched placebo;
  - VAL and TEST have the same sign;
  - costs × 1.5 mean > 0;
  - $100 portfolio above $100 with drawdown < 50 %;
  - plus the §3.6 automatic rejections.
- **D1 verdict:**
  - PASS only if the entry bar passes **and** the VAL gate is PASS;
  - an entry PASS with an UNDERPOWERED gate is INCOMPLETE;
  - an entry PASS with a WEAK gate is FAIL;
  - otherwise the entry verdict (FAIL, UNDERPOWERED or REJECTED).

**CONFIRM** (09-16 → 10-01; `LAB2_ALLOW_CONFIRM=1`):

- one run of the same config, after TEST, never searched;
- `confirm_consistent` means mean > 0;
- a CONFIRM mean ≤ 0 downgrades a TEST PASS to FAIL.

**FINAL** (the census day: all three thirds, `split="final"`; `LAB2_ALLOW_FINAL=1`):

- one run of the same config, never before TEST;
- it feeds PLAN §3.5 criterion 9 (FINAL mean > 0, with n reported);
- the D1 verdict is recomputed with it.

## 10. Stage prerequisites (enforced in code)

| Stage | Refused when |
|---|---|
| `train` | No PREREG; this file changed after the lock; D1 has already run on VAL (TRAIN is then closed) |
| `val` | The PREREG lock is missing or does not match; `train.json` is not SHORTLISTED or SHORTLISTED_UNDERPOWERED; a shortlist file is missing; VAL already ran |
| `test` | VAL is missing or not SELECTED (e.g. KILLED); TEST already ran (`test.json` or the ledger); `LAB2_ALLOW_TEST` is not 1 |
| `confirm` | TEST has not run; CONFIRM already ran; `LAB2_ALLOW_CONFIRM` is not 1 |
| `final` | TEST has not run ("never FINAL before TEST"); FINAL already ran; `LAB2_ALLOW_FINAL` is not 1 |
| any | Data not ready (§2.2), except `train --allow-partial` |

On top of these, `common.backtest` enforces the VAL shortlist (≤ 2 configs, frozen at the first VAL run) and the
one-run rule on TEST, CONFIRM and FINAL.

## 11. Kill criteria (PLAN §8)

- **Stop rule 1.** If V1-V4 fail, no stage runs.
- **Stop rule 4.** If CAP − DIST < 5 points on VAL (with ≥ 20 trades in each class), D1 dies.
- **Stop rule 7.** If S1, D1 and M1 all fail VALIDATION, declare "no entry edge from trade flow on fresh graduates
  at these costs". This is the lead's call, across hypotheses.
- **Stop rule 8.** Every trial counts. The real-money bar (PT1) does not relax.
- **Automatic rejections (PLAN §3.6).** Reject the result if:
  - it disappears without the top 2 trades;
  - it scores a wallet with its trades in the traded coin (D1 uses no reputation);
  - it counts AGENT, BOT, WASH, DUST or MECH as organic (declared and excluded);
  - it uses truncated windows (P4b has no trade cap; coins without a complete B1 window are not scored);
  - it uses current-state fields (none are used);
  - it uses more variants than the PLAN limit (D1 uses 3 of 6).
- **An honest result.** "Underpowered" and "no edge" are valid outcomes, and will be reported as such.

## 12. Deviations from the PLAN and known limitations

1. **E2 is deferred** (the single oversized sell, D = 2 s or 30 s, the 0.06 × x threshold). The common engine decides
   on a minute grid only (boundary + 20 s), so a "+2 s" decision cannot be simulated. E2 waits for the X1
   trade-replay engine. Its 3 PLAN variant slots stay unused, so D1 ever runs at most 6 variants.
2. **The "lab F1 exit, for comparison" is replaced by the `ALL` candle-only class.** That class compares the same
   trigger without the flow filter on identical coins, which is the comparison the lens proposed.
3. **NEWS (G1) needs metadata.** It is merged into ORGANIC.
4. **BOT has no registry part, and TRANSFEREE has no transfer part.** There are no B3 or B4 tables.
5. **`burned` is estimated** from AGENT minute flow; it only moves p_floor by a few percent.
6. **Fills are minute-bar "worst" until X1 exists.** If X1 later shows minute-bar fills are off by ≥ 1 point
   (stop rule 2), a D1 result is re-quoted only with replayed fills.
7. **SOL/USD** covers only 10-07 09:00 → 10-08 18:15. Earlier dates use the edge price, which affects only the
   $20 → SOL sizing and the $1,500 volume filter. This is recorded in every coverage block.
8. **Instant graduates are excluded** because P4 has no B1 for them. D1 is about slower, non-factory graduates
   only.
9. **"Worst" fills against a −15 % stop.** On the debug split (synthetic B1 entries, counts only, no returns
   looked at), 19 of the 26 V1 trades were stopped out **on their entry bar**. "Worst" mode buys at the minute's high and checks the
   stop against the same minute's low, so the bracket mostly measures intra-minute ranges.
   - With `entry_bar_exits=False`, none of the 26 is stopped on its entry bar.
   - Every variant's fill-sensitivity table is reported.
   - The verdict uses only the default "worst" fills, as pre-registered.
   - X1's replayed fills supersede these results (stop rule 2).
10. **Placebo draws can fall short of 20 per signal.** `common.run_placebo` tries at most 200 random (coin, time)
    draws per signal. D1's universe is narrow (about 30 % of usable coins), so some signals get fewer than 20; the
    debug run averaged about 17. `n_placebo` is reported.

## 13. Expected sample (debug counts only, census TRAIN third)

These numbers come from the census TRAIN third (`final_train`): 450 usable coins created over 0.52 days. No
returns were looked at.

| Count | Value | Per day |
|---|---:|---:|
| D1-universe coins (B1 not required here) | 133 | ~255 |
| Coins with ≥ 1 E1 event | 64 | ~123 |
| Coins with an E1 event that passes the bar **upper bounds** of the CAP sample-size conditions (Σ per-minute sellers ≥ 8 and Σ buyers ≥ 5 over the last 3 minutes) | 62 | ~119 |

The other CAP conditions cannot be counted without B1: `sopr3` < 0.8, insider share < 0.2 and `insider_rem` < 0.15.
So ~120 coins a day is a loose **upper bound** on D1 trades a day. The lens estimated 5-15 a day.

Over TRAIN's 4 days, the strategy runs need ≥ 30 trades (the shortlist minimum). The PLAN bar needs ≥ 60 on TEST
(~1.3 days). TEST is therefore likely UNDERPOWERED unless CAP fires on ≥ ~45 coins a day.

## 14. Commands

```bash
python research/lab2/d1.py --stage status                     # coverage, prerequisites, trials (no returns)
python research/lab2/d1.py --stage debug                      # census TRAIN third: counts only
python research/lab2/d1.py --stage train [--allow-partial]    # writes D1/train.json/.md + shortlists
python research/lab2/d1.py --stage val                        # gate + selection
LAB2_ALLOW_TEST=1    python research/lab2/d1.py --stage test
LAB2_ALLOW_CONFIRM=1 python research/lab2/d1.py --stage confirm
LAB2_ALLOW_FINAL=1   python research/lab2/d1.py --stage final
python -m pytest -q research/lab2/tests/test_d1.py
```
