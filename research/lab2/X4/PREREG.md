# X4 pre-registration: the floor lottery, bought only when a dispersed revival starts at the floor

- **Version:** `x4-v1`.
- **Written:** 2026-10-09, before any X4 run on TRAIN, VAL, TEST, CONFIRM or FINAL data. TRAIN was still being
  backfilled. Every constant and the whole grid (§8) were fixed in this file **before** the debug run on the census
  TRAIN third (§15). That run reports counts only: returns, labels and fill prices hidden, no parameter chosen there.
- **Code:** `research/lab2/x4.py`, on the shared foundation `research/lab2/common.py` (every feature through
  `common.AsOf`). Tests: `research/lab2/tests/test_x4.py`.
- **Data:** `graduates`, `b2_coins`, `b2_bars` only (B2 minute bars to g + 180 min). No B1 trades, no B3 positions,
  no CryptoHouse queries.
- **Protocol:** PLAN §3 (shared protocol), §3.5 (pass bars), §3.6 (automatic rejections) and §8 (stop rules),
  through common.py's `backtest`, matched placebo, `describe`, `verdict_entry`, trial ledger, shortlists and one-shot
  sessions. Stage gating and CLI follow `m1.py` / `z1.py`.
- **Splits:** common.py's (TRAIN 10-01 → 10-05, VAL → 10-06 12:00, TEST → 10-07 19:37:30, CONFIRM 09-16 → 10-01,
  FINAL = census day in the lab's thirds; the census TRAIN third is debug only).
- **Freeze.** The first official TRAIN run hashes this file into `X4/prereg.lock`. After that, `x4.py` refuses every
  stage if this file changed. A change is a new version (`x4-v2`) in `X4/AMENDMENTS.md`, and its configs are new
  trials.

## 1. Mechanism, why it could beat costs, and why it probably will not

**The floor.** A PumpSwap migration pool prices on X = x + v (real SOL plus a virtual reserve v ≈ 17.58 SOL) with
X·y = k ≈ 85 × 206.9 M. When every outside token is sold back, x → 0 and the price hits the **floor**
p_f = v² / k: a market cap of ≈ 17.6 SOL (≈ $2,000), 1/23 of the migration price. BOOST's ~35 M tokens never come
back, so a fully dumped coin sits slightly above it. The as-of distance to the floor is exact on bars:

> **fm = p / p_f = (X / v)²**, with X = close × y and v = X − x_real from the last completed bar.

At fm = 1.25 all outside holders together can extract ≤ 2.1 SOL (≈ $240) by selling everything: the coin is
economically dead and **its insider overhang is gone by construction** (S1's precondition holds for free).

**Payoff shape.** Entered at fm, the price cannot fall below the floor while LP is burned, so the loss before costs
is bounded by 1 − 1/fm (17 % at fm = 1.2, 33 % at 1.5). The pool is thin: a net inflow ΔX multiplies the price by
((X + ΔX) / X)², so ≈ 8 SOL of net buying (≈ $900) doubles a coin at the floor. Bounded downside, convex upside: a
lottery ticket.

**Costs.** At fm 1.0-1.5 the market cap is 18-26 SOL: pool tier 1.25 %/side + Ultra 10 bps + 20 bps buffer, and a
$20 ticket (≈ 0.17-0.19 SOL) is ~1 % of X. `common.round_trip_pct` gives **5.3 % at fm 1.03, 5.1 % at 1.25, 4.95 %
at 1.5** (the top of the lab's 1.4-5.1 % range), plus 1.1 % if the $0.22 rent is never refunded.

**The prior is negative.** The execution lens's H12 (`scratchpad/ideas/exec/floor_lottery.py`) bought every census
TRAIN-third coin sitting ≤ 1.5× the floor ≥ 1 h after graduation (n = 274): 1.1 % reached 1.5× and 0.4 % reached 3×
within 12 h; take-profit-at-3× gross mean −0.8 % against ~5 % cost. **Killed.** The unconditional floor lottery is
dead; X4 does not re-test it as a strategy (it is X4's control, §11).

**What X4 adds: buy only when a revival has started, while the price is still near the floor.** Revivals at the
floor are not random draws. They begin with new distinct wallets buying a dead coin (a community takeover, the dev
re-buying, a call in a group, a paid DexScreener profile). On a dead coin even small buying shows as a large
percentage move, and the tools traders scan (DexScreener "gainers", pump.fun movers, Telegram trackers) rank by
percentage change and buyer counts, so a revival that has started can feed itself for a while. B2 shows the
footprint as-of: distinct buyers per minute and net SOL inflow. X4 asks whether either **separates** the floor
coins that revive from the ones that stay dead, by enough to pay 5 % plus the loss back to the floor.

**The bar that must be cleared.** Entering at a worst fill around fm ≈ 1.35, a revival that fails returns to
fm ≈ 1.1 (−18 % mid, about −23 % net). A +100 % take-profit filled on the next bar's low nets maybe +75 %. Break-even
needs P(take-profit) ≈ 23/(23 + 75) ≈ **24 % within 60 minutes**, against an unconditional base of ~1 % for 1.5×
in 12 h. The signal would have to raise the revival rate by about 20×. **My prior that any X4 config passes TEST
and CONFIRM is below 5 %.** X4 is worth running because it is cheap, uses a universe no other hypothesis touches
(§2), and turns "is there anything at the floor?" into a pre-registered no.

**Who loses if it works:** late revival buyers, whose net inflow lifts the coin we already hold; and the rare
holder who sells into the first minutes of a revival.

## 2. Not a duplicate

- **Universe.** X4 trades only coins at fm ≤ 1.5, i.e. a market cap ≤ 26.4 SOL ≈ $3k. `common.AsOf.alive()` needs
  a market cap ≥ $6k, so **no X4 entry is `alive`**: X4 is disjoint from every alive-gated hypothesis (S1, Z1, X1,
  X2 and the bot's universe). D1 requires close ≥ 3 × p_floor (fm ≥ 3): disjoint. M1 rides operator coins at ≥ $1M.
  G1 is a gate, never an entry.
- **Z2 (single large buy after BOOST).** Z2 found most of its whale bars in drained pools. X4's revival must be
  **dispersed**: no single minute may carry more than half of the window's buy SOL (§4), so a revival made of one
  whale print is excluded, and X4 additionally requires the coin to have sat at the floor for the 20 minutes before.
- **Wave 1 FL1 / H12.** Unconditional; killed. It is X4's matched control (§11), not a strategy.

## 3. Data and universe

- **Coins:** `common.load(split)` usable coins: SOL-quoted, not Mayhem, virtual reserve known, complete B2 window.
  Every class is allowed (a factory coin that was dumped to the floor holds no airdrop inventory any more).
- **Decision grid:** common's (minute boundary + 20 s; features use completed bars with τ = t − 20 s).
- **Ages:** entries at decision ages **30-150 min** (no entries in the first 30 min after graduation, EXPERIENCE_GROUNDED
  G12; ≥ 28 minutes of data left for every hold).
- **Strata (reports and nothing else):** `instant` (grad_delay_s ≤ 5 s) or `slow` (incl. creation not scanned).

## 4. Features, as of τ (all through `common.AsOf`; W = 10 completed bars, PRE = 20 bars before them)

With k completed bars: the **window** is bars [k − 10, k), the **pre-window** is [k − 30, k − 10), the **previous
window** is [k − 20, k − 10). Needs k ≥ 30.

| Feature | Definition |
|---|---|
| `fm_j` | (X_j / v_j)², v_j = X_j − x_real_j, for completed bar j. Undefined (None) when v_j ≤ 0 or a value is missing: no virtual reserve, no floor |
| `fm_now` | `fm` of bar k − 1 |
| `fm_pre_med` | median of `fm` over the pre-window (every value must be defined) |
| `dead_before` | `fm_pre_med` ≤ **1.25** (FM_FLOOR: outside holders can extract ≤ 2.1 SOL; above BOOST's fm ≈ 1.07) |
| `cheap_now` | `fm_now` ≤ **1.5** (FM_MAX: loss to the floor ≤ 33 % before costs) |
| **`at_floor`** | `dead_before` and `cheap_now`. This is the placebo's eligibility (§11) |
| `BM` | Σ `n_buyers` over the window (buyer-minutes: wallets ≥ 0.01 SOL per minute) |
| `BM_prev` | Σ `n_buyers` over the previous window |
| `peak` | max `n_buyers` in one window minute |
| `buy_w`, `NI` | window buy SOL ex-AGENT (AGENT buy SOL subtracted once knowable; it is 0 after g + 6 min), and net inflow = buy_w − window sell SOL |
| `top_min_share` | max minute buy SOL / `buy_w` |
| `dispersed` | `buy_w` > 0 and `top_min_share` ≤ **0.5** |

## 5. Signals (one mechanism, two footprints and their intersection)

All three require `at_floor` and `dispersed`.

| Signal | Extra conditions | Reason |
|---|---|---|
| **BREADTH** | `BM` ≥ 12, `peak` ≥ 2, `BM` ≥ 2 × `BM_prev`, `NI` > 0 | More than one distinct buyer a minute (one bot can make at most 10 buyer-minutes in 10 minutes), at least one minute with two wallets, buyer activity at least doubled against the previous 10 minutes (not steady churn), and net buying |
| **FLOW** | `NI` ≥ **1.0 SOL**, `BM` ≥ 3 | ≈ $115 of net buying: +11 % on a pool at the floor, twice the round trip; from at least 3 buyer-minutes |
| **BOTH** | BREADTH and FLOW | |

## 6. Entry

At the first decision with age in [30, 150] min where the config's signal fires; at most one entry per coin. The
order fills at the worst price of the landing bar (`max(open, high)`, 30 s latency): a revival's spike is paid in
full.

## 7. Exits (all mechanical, all filled on the NEXT bar at its worst price)

`FILL = common.FillConfig(exit_delay_bars=1)`: an exit triggered in bar j fills in bar j + 1 at `min(open, low)`
(30 s polling + 30 s landing). That applies to the take-profit too.

| Exit set | Take-profit | Max hold | Always |
|---|---|---|---|
| **TP2X** | +100 % from the fill | 60 min | disaster stop −60 %; deadline g + 178 min |
| **RUN** | none (pure lottery shape) | 90 min | the same stop and deadline |

The −60 % stop means "the floor broke": from a fill at fm ≤ 2.5 the floor bound is ≤ 60 %, so only an LP withdrawal
or a virtual-reserve change can reach it (or a worst fill more than 1.67× above a decision at fm 1.5).

No ordinary stop: **the floor is the stop.** Entries end at g + 150 min and every hold ends by g + 178 min (fills by
g + 179 min), so no trade is censored by the data horizon. The exit logic needs no state, so the placebo runs the
identical exits.

## 8. The grid: exactly 6 configurations (+ 1 gate trial)

**signal ∈ {BREADTH, FLOW, BOTH} × exit ∈ {TP2X, RUN}.** Every config's params dict carries every constant above,
the fill model and the version; any change is a new trial. Plus one counted trial for the separation gate
(`X4-sep`, §9). **X4's total is at most 7 trials** on top of the ledger's.

Fixed, not searched: W = 10, PRE = 20, FM_FLOOR = 1.25, FM_MAX = 1.5, the dispersion share 0.5, the BREADTH counts
(12 / 2 / 2×), the FLOW inflow (1.0 SOL / 3), the stop (−60 %), the take-profit (+100 %), the holds (60 / 90 min),
the age window (30-150 min), $20 tickets. They come from the pool arithmetic in §1 and §4, not from data.

**Sensitivity runs** (same call, never used to select, not trials): costs × 1.5; rent $0.22; same-bar exits
(`exit_delay_bars=0`); a **$10 ticket** (the execution lens's cost-minimising ticket at the floor is ≈ $7: impact
falls, the network fee share rises).

## 9. The separation gate (stop rule, TRAIN, before any P&L)

Does any signal separate the floor coins that revive?

- **Observations:** every usable TRAIN coin, decisions at the last grid time ≤ g + a min for a ∈ {30, 35, …, 115},
  kept where `at_floor` holds. (A label needs 60 bars inside the data window.)
- **Label (an outcome, never a feature):** `revive60` = the max close over the 60 completed bars after τ ≥ 2 × the
  decision price (mid prices, no costs; read through AsOf 60 minutes later).
- **Per signal s:** `rate_s` = mean `revive60` where s fires; `rate_0` = mean `revive60` where **no** signal fires;
  diff = `rate_s` − `rate_0`, with a 90 % coin-bootstrap CI (2,000 draws, coins resampled with all their
  observations).
- **s PASSES** when it has ≥ 30 observations from ≥ 15 coins **and** `rate_s` ≥ 2 × `rate_0` **and** diff ≥ 0.05
  **and** the CI's lower bound > 0. **s is UNDERPOWERED** below 30 observations or 15 coins.
- **Decision:** PASS if any signal passes; else **KILL** if any signal was powered; else **UNDERPOWERED**. On KILL or
  UNDERPOWERED, X4 stops: the grid is never run and every later stage refuses. On PASS, the grid runs **only the
  configs of the signals that passed** (unrun configs are never trials).
- Reported, never decisive: the rate of a 1.5× revival, the mean of the 60-minute max close ratio, both per signal.

## 10. Procedure by stage (`python research/lab2/x4.py --stage …`)

**Every stage** refuses unless `X4/PREREG.md` exists (and matches `prereg.lock` once locked); PLAN §8 rule 1 holds
for the split (`common.validation_gates`); the split's coverage is complete (every chain hour scanned for curve and
B2, ≤ 5 % of tradeable coins missing B2, no B2 hour mid-run, the SOL/USD series covers the split); the guarded
splits have their flags (`LAB2_ALLOW_TEST`, `LAB2_ALLOW_CONFIRM`, `LAB2_ALLOW_FINAL`; `x4.py` never sets them).

**TRAIN (all searching).**

1. The separation gate (§9). KILL or UNDERPOWERED stops X4 here.
2. The configs of the passing signals, each with the floor-matched control, the unmatched control and the
   sensitivity runs.
3. **Qualifies:** ≥ 40 trades from ≥ 40 coins (one entry per coin); mean net > 0; mean without the top 2 trades > 0;
   floor-matched control `mean_diff` > 0; censored share ≤ 10 %.
4. **Shortlist:** the qualifiers ranked by the coin-bootstrap 90 % CI lower bound (ties: higher mean, then signal
   order BREADTH, FLOW, BOTH, then exit order TP2X, RUN); the top 2, written with `common.write_shortlist` and frozen
   at the first VAL run.
5. Nothing qualifies: **NO_CONFIG** if a config met the sample bar, else **UNDERPOWERED_TRAIN**. X4 stops.
6. A decision on complete TRAIN is final; a re-run needs `--rerun-reason` naming a data correction (the previous
   result is archived). `--allow-partial` runs a PROVISIONAL TRAIN on partial data: `train_prelim.*`, never a
   shortlist or a lock, never unlocks VAL.

**VAL (≤ 2 configs, a filter, never a ranking).** Both shortlisted configs run once. Each gets UNDERPOWERED_VAL
(n < 5), FAIL_VAL (mean ≤ 0 or mean without the top 2 ≤ 0), SELECTED_UNDERPOWERED (5 ≤ n < 15) or SELECTED. The
candidate is the TRAIN rank-1 config if it proceeds, else rank 2; else X4 stops (PLAN §8 rule 7 input).

**TEST (one run).** The candidate once, with both controls and the sensitivity runs. Verdict =
`common.verdict_entry(test, val=VAL candidate, min_mean=0.03)`: PLAN §3.5 items 1-8 and the censoring item 10, plus
the §3.6 auto-rejections (incl. "disappears when the top 2 trades are removed", which is exactly the failure mode of
a lottery). REJECTED / UNDERPOWERED / FAIL / INCOMPLETE / PASS as in `z1.combine_verdict`. Item 9 (FINAL mean > 0) is
judged in the overall verdict. With a 1.3-day TEST, **UNDERPOWERED is expected.**

**CONFIRM (09-16 → 10-01; one run, never searched).** Spent only when TEST is not REJECTED and (TEST mean > 0 or
TEST n < 5). Same verdict. CONFIRM is the powered out-of-sample test.

**FINAL (the census day).** After TEST; the candidate once on all of FINAL (one `common.one_shot_session`).
Criterion 9 is judged on the census **VAL and TEST thirds only**: the census TRAIN third hosted this debug run and,
before it, the execution lens's unconditional floor-lottery measurement (§1), so its trades are reported apart.

**Overall X4 verdict.** EDGE requires: the gate PASS, VAL SELECTED or SELECTED_UNDERPOWERED, TEST not REJECTED and
(TEST mean > 0 or n < 5), CONFIRM PASS, FINAL mean > 0. Otherwise KILLED (gate), UNDERPOWERED (gate, TRAIN, VAL or
CONFIRM) or NO EDGE.

## 11. Controls

- **Floor-matched random control (judged, PLAN §3.4 "the same eligible coins").** `common.backtest`'s placebo:
  20 draws per signal, random usable coins of the same split that are **`at_floor` at the drawn decision**, decision
  age within ±120 s of the signal's, identical exits. This is the unconditional floor lottery at the same age and
  depth band: it isolates what the revival signal adds. It feeds PLAN §3.5 item 5 (≥ +6 points) and the TRAIN
  qualifier (`mean_diff` > 0).
- **Unmatched control (reported, never judged):** any usable coin at the same age, identical exits.

## 12. Metric and statistics

The unit is the net return per $20 trade (`ret_net`), one entry per coin per config. CIs: coin bootstrap (10,000
draws, 90 % and 95 %) and the 6-hour block bootstrap; the mean without the top 2 trades; top-coin share; halves;
the $100 / 5-slot portfolio; the deflated Sharpe ratio counting every trial in the ledger. Also reported (never
decisive): per stratum; the decision-time `fm`; the **floor bound** of each trade (1 − p_f / fill price, the loss to
the floor before costs); the take-profit hit rate; exit reasons; the sensitivity runs.

## 13. Kill criteria (PLAN §8) and declarations

| Rule | How X4 applies it |
|---|---|
| Stop rule 1 (data first) | V1-V4 for the split's dates; stages refuse otherwise |
| Stop rule 2 | Minute-bar worst fills until replayed fills exist. If they turn out ≥ 1 point off, the frozen shortlist is re-run with replayed fills before any promotion |
| X4's own stop rule | The separation gate (§9): KILL or UNDERPOWERED ends X4 before any P&L |
| Stop rule 7 | FAIL_VAL is reported to the lead |
| Stop rule 8 | Every config counts (§8) |

Declarations passed to `auto_rejections`: `uses_organic_flow = False` (buyer counts are all wallets ≥ 0.01 SOL; X4
never calls anything organic), `uses_wallet_reputation = False`, `uses_truncated_windows = False`,
`uses_current_state_fields = False`.

## 14. Deviations and limitations, stated up front

| Area | Deviation or limitation |
|---|---|
| Horizon | B2 ends at g + 180 min; holds are ≤ 90 min and entries end at g + 150 min. Wave 1's H12 used 12 h. Revivals that take hours (most community takeovers) are invisible to X4 |
| Fills | Minute-bar worst fills (entry at the landing bar's high, exits at the next bar's low), not replayed trades. On a thin floor pool one minute can hold the whole revival; the worst fill charges it in full |
| Floor | Exact only while v is stable and the LP is burned. v drifts slightly (audit 3.1); pump.fun's docs say v can be negative since 09-30 (EXPERIENCE_GROUNDED G35): fm is then undefined and the coin is never at the floor. The −60 % stop is the registered response to a broken floor |
| Distinct buyers | `n_buyers` is distinct per minute, not over the window: one wallet buying every minute counts 10. The BREADTH conditions (≥ 12, a minute with ≥ 2, doubling) are the bar-level guard. Bots and wash are not removed (no wallet ids on bars) |
| Quotes | A dead coin may not route on Jupiter at all; the fills assume the canonical pool is reachable |
| Size | $20 tickets (protocol). The $10 run is a sensitivity, never a selection |
| SOL/USD | Every non-debug stage refuses until the series covers the split (`common.coverage_problems`) |

## 15. Debug findings and expected sample (census TRAIN third, counts only)

Filled in after the debug run below; nothing above this section was changed after it.
