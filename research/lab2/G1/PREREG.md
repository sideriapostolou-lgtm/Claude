# G1 pre-registration: a gate for factory, "completed" and operator coins (when NOT to trade)

Written 2026-10-08, before any G1 run on any split (including the census debug run). Code: `research/lab2/g1.py`.
Tests: `research/lab2/tests/test_g1.py`. Foundation: `research/lab2/common.py`.

**Freeze.** The first `--stage train` run writes `G1/prereg.lock` with this file's SHA-256. Every later stage refuses
to run if this file changed. Any change after that goes into `G1/AMENDMENTS.md`, dated, with the reason. The
amendment must say whether it was made before or after seeing results.

## 1. Question

The PLAN (§4.2) asks this question: at g + 2 min, can on-chain features sort fresh graduates into classes so that
later entries skip the coins that are about −95% at the median? Does that beat the simple time-to-graduate rule?

The task adds three things to measure:

- the audit's airdrop dump;
- serial deployers;
- **how much each class loses** for the bot's current strategy and for random entries.

G1 is a gate. It can only make a strategy lose less. No G1 result is ever an entry signal.

## 2. Data, splits, universe

**Data.** CryptoHouse Parquet in `FLOW`, read-only: `graduates`, `b2_coins` and `b2_bars`. B1 and B3 (wallet trades
and positions) do not exist, so nothing here needs wallet roles beyond the stored first-2-min top-10 lists.

**Splits.** Coins are split by `created_ts` (`common.SPLIT_BOUNDS`) and never shuffled:

| Split | Window (UTC) | Use |
|---|---|---|
| TRAIN | 10-01 00:00 → 10-05 00:00 | Measure all 3 variants |
| VAL | 10-05 00:00 → 10-06 12:00 | The ≤ 2 shortlisted variants; the PLAN 4.2 pass decision |
| TEST | 10-06 12:00 → 10-07 19:37:30 | One run of the single shipped variant |
| CONFIRM | 09-16 → 10-01 | One run of the shipped variant, after TEST; never searched |
| FINAL | the census day | One run after TEST; report the sign and n. The census TRAIN third was used for debugging only |

**Universe.** `common.load`: SOL-quoted, not Mayhem, virtual reserve known, and a complete 180-minute B2 window.

**Coverage rule.** A stage runs only when every chain hour of its split is scanned for curve and B2, and at most
5% of tradeable coins lack a complete B2 window. TRAIN alone may run on partial data with `--allow-partial`. That
run is marked **provisional** and writes **no shortlist**.

## 3. Features (all through `common.AsOf`; NULL stays None, never 0)

Classes are computed at **t = g + 140 s** (τ = g + 120 s).

| Feature | Definition | Legal from |
|---|---|---|
| `grad_delay_s` | g − created. NULL when creation is unknown; then `grad_delay_lb_s` = 1,800 s is a lower bound | g |
| `instant`, `fast120` | grad_delay ≤ 5 s, ≤ 120 s. The lower bound decides them only when it exceeds the threshold | g |
| `bundle_share` | `z_buy_tok` / 793.1e6 | created + 120 s |
| `creator_in_bundle` | `z_n_buyers` > `z_n_buyers_noncreator` | created + 120 s |
| `curve_top1_share`, `curve_top3_share` | `curve_top{1,3}_buy_sol` / `curve_buy_sol` | g |
| `completer_share` | `completer_sol` / 30 | g |
| `n_curve_buyers` | `curve_n_buyers` | g |
| `amm_buy_sol_2m` | `w120_buy_sol` − the AGENT's w120 SOL (when it is detected and in the stored top 10; otherwise an upper bound) | g + 120 |
| `amm_buyers_2m` | `w120_n_buyers` − 1 if the AGENT is detected and bought in the first 120 s | g + 120 |
| `amm_top5_share_2m` | `snap.top_share("w120", 5, exclude_agent = AGENT presence decided)`. Pooled accounts are never a buyer | g + 120 |
| `amm_sell_buy_2m` | `w120_sell_sol` / `w120_buy_sol` | g + 120 |
| `airdrop_seen` | In completed minute bars up to τ, ≤ 2 consecutive clock minutes with ≥ 1,000 sell trades (dust included), and at least 3× as many sell trades as buy trades | each minute's end |
| `serial_prior`, `serial` | Other graduates with the same `creator` that graduated in (τ − 24 h, τ]; SERIAL means ≥ 2 | τ |
| `repeat_migbuyer_share_2m` | Descriptive only. w120 buy SOL from wallets that were top-5 pool buyers in the first 2 min of ≥ 3 other graduates within (τ − 24 h, τ], divided by `amm_buy_sol_2m`. A lower bound (top 10 only) | g + 120 |

**Registry.** Creators and top-5 buyers of other graduates are read through `AsOf` at their own legal time:

- a creator at that coin's g;
- top-5 buyers at its g + 120 s, or at g + 420 s when the AGENT was not yet decided.

The pool is every graduate of any quote currency and any Mayhem flag that was created before the end of the split
being run. Queries exclude the coin itself. A decision is **cold** when fewer than 99% of the 24 lookback hours were
scanned. Registry-dependent results are reported with and without cold decisions (PLAN §6.6 rule 8).

**Forbidden and never read:** `n_chunks`, `n_pools`, `virt_sol`, `w_exact`, current-state fields, and every other
column that `common` forbids.

## 4. Classes and the three variants (fixed; the PLAN 3.4 limit for G1 is 3)

**Exclusive classes**, in PLAN order. The thresholds are PLAN §4.2's.

1. **OPERATOR:** `amm_buy_sol_2m` ≥ 500 and `amm_buyers_2m` ≤ 30.
2. **FACTORY:** `instant` and `amm_top5_share_2m` ≥ 0.85.
3. **COMPLETED:** not `instant`, and any of:
   - `completer_share` ≥ 0.6;
   - `curve_top3_share` ≥ 0.6;
   - `n_curve_buyers` < 15.
4. **UNRESOLVED:** none of the above is true, and one of them cannot be evaluated because an input is NULL (mostly
   coins without creation data). These coins are **never flagged**: the gate needs evidence.
5. **ORGANIC:** everything else.

NEWS (tweet or image metadata) and PLAN's **G-full** need IPFS metadata (about 27k fetches, PLAN §6.1) that we do
not have, so they are **not tested**. Their slot goes to G-chain+.

| Variant | Gate set (host trades skipped) | Dead set (for the dead60 precision) |
|---|---|---|
| **G-time** | `fast120` | `fast120` |
| **G-chain** | OPERATOR ∪ FACTORY ∪ COMPLETED | FACTORY ∪ COMPLETED |
| **G-chain+** | G-chain ∪ AIRDROP ∪ SERIAL | FACTORY ∪ COMPLETED ∪ AIRDROP ∪ SERIAL |

OPERATOR is skipped by the gate but not called "dead": PLAN routes OPERATOR coins to M1.

**When the gate is applied:**

- On **host trades**, it is evaluated **at each trade's decision time**: what a live gate would see then, including
  an airdrop dump that already happened.
- For the **labels**, it is evaluated at g + 140 s. AIRDROP cannot fire that early.

## 5. Hosts (fixed baselines; not searched)

### G1.dip: the bot's CURRENT default dip-rebound

This is `nightcrawler.strategy.entry_signal` with `snapshot=None` and the StrategyParams defaults, as
`research/lab/baseline.py` runs it. It is re-implemented on AsOf completed traded minutes. A test checks logic parity
with the real function on 400 random candle paths.

Snapshot hashes at pre-registration:

- `src/nightcrawler/strategy.py`: SHA-256 `9028aa01…0815`;
- `models.py`: SHA-256 `0d373405…c291`.

**Entry**, all of:

- age since creation ≥ 60 min (the exact age, or its lower bound) and ≤ 48 h;
- market cap $100k-$5M;
- a dip ≥ 55% from the high of the traded bars;
- last close ≤ 72.5% of that high;
- ≥ 2 green closes;
- a breakout over the prior high, or rising volume.

**Exits:**

- stop −18%;
- take-profit +40%;
- 120 min.

**Simplification:** the bot sells 50% at +40% and trails the rest by 15%. The engine has no partial exits, so the
whole position exits at +40%. The matched-timing placebo uses 20 draws, restricted to the bot's universe (age and
market cap).

### G1.R0: PLAN R0 random entries

- **Entry age:** seeded at random from `sha256(seed:mint)`, uniform in [30, 115] min.
- **Rule:** enter at that minute if the coin is alive (15-minute USD volume ≥ $1.5k and market cap ≥ $6k), otherwise
  never. One entry per coin, seed 0.
- **Exit:** PLAN X1 exit 6, a −50% catastrophe stop plus a 60-minute time limit. X1's "best exit" does not exist
  yet.
- **No placebo:** R0 is itself the random control.

### Fills and costs (`common` defaults)

- $20 positions, 30 s latency, `"worst"` minute-bar fills.
- `costs.py` fee tiers as of the trade date, PumpSwap pricing with the virtual reserve.
- **Stress runs, from the same call:**
  - costs × 1.5;
  - rent +$0.22;
  - `alt_fill` (no stop checks on the entry bar, exits one bar later).

These are reported, never selected on.

## 6. Labels (outcomes; never features)

- **`dead60`:** no clock minute with ≥ $100 of volume in [g + 60, g + 75) min. SOL/USD outside 10-07 09:00 → 10-08
  18:15 uses the edge price.
- **`winner`:** a high ≥ 2× the close at g + 15 min, within the following 2 h.

## 7. TRAIN grid and trial accounting

The TRAIN grid is exactly **3 gate configs**, `{"gate": "G-time"}`, `{"gate": "G-chain"}` and `{"gate": "G-chain+"}`,
each evaluated on the **2 fixed hosts**. **No threshold is searched.** Every number in §3-§6 is fixed above.

The trials ledger (`research/lab2/trials.json`) gains exactly **5 configs**:

- `G1` × 3;
- `G1.dip` × 1;
- `G1.R0` × 1.

Re-running a stage adds runs, not configs. Every deflated Sharpe ratio uses the ledger total, which already holds
the lab's 2,575 configurations.

## 8. Metrics

**Primary (PLAN §4.2):**

1. Precision of the dead set for `dead60`, with the number of coins flagged.
2. Missed-winner rate = winners among dead-flagged coins / dead-flagged coins.
3. On R0: the mean net return of trades the variant keeps, minus the same for G-time. This uses a coin-bootstrap
   95% CI that resamples coins, with 10,000 draws.

**Secondary (reported, never decisive):**

- **Per host and variant:**
  - flagged minus unflagged mean, with a coin-bootstrap 95% CI;
  - the PLAN §3.5 veto bar (`verdict_veto`);
  - the share of winning profit removed;
  - the gated host's stats, deflated Sharpe ratio and §3.6 auto-rejections.
- **Per class and overlay flag:**
  - for each host: n, mean, CI and P&L in $ (the "how much each class loses" table);
  - for each class of coins: the dead60 and winner rates.
- **Host and control checks:** the host's placebo comparison, stress runs and $100 portfolio.

## 9. VAL shortlist rule (written automatically by a complete TRAIN run)

The shortlist is `[G-time, best chain]`, where best chain is whichever of G-chain and G-chain+ has the higher R0
kept-trade mean on TRAIN. A tie, or missing data, picks G-chain. The hosts' VAL shortlists hold their single fixed
config. `common.write_shortlist` freezes all of them at the first VAL run.

## 10. VAL decision (one VAL run, the PLAN 4.2 pass bar)

The criteria apply to the shortlisted chain variant:

- **c1:** dead-set precision ≥ 90%, with ≥ 200 coins flagged;
- **c2:** missed winners ≤ 5%;
- **c3:** the R0 kept-trade mean beats G-time by ≥ 2 points per trade, with the 95% CI above 0.

| Outcome | Verdict | What happens next |
|---|---|---|
| c1, c2 and c3 all hold | **PASS_CHAIN** | Ship the chain variant |
| Only c1 and c2 hold | **SHIP_G_TIME** | Ship G-time (PLAN: "ship G-time, the simplest version") |
| Fewer than 200 dead-flagged coins | **UNDERPOWERED** | No ship |
| Anything else | **KILL** | No ship |

Only PASS_CHAIN and SHIP_G_TIME open TEST.

## 11. TEST, CONFIRM, FINAL

Each stage evaluates the single shipped variant once (`LAB2_ALLOW_TEST`, `LAB2_ALLOW_CONFIRM` or
`LAB2_ALLOW_FINAL` = 1), with both hosts.

**Confirmation rule:**

- dead-set precision ≥ 80% (the PLAN's live auto-disable floor);
- R0 flagged-trade mean below the unflagged mean (the same sign as VAL).

| Outcome | Verdict |
|---|---|
| Fewer than 30 R0 trades on either side | UNDERPOWERED |
| Both conditions hold | CONFIRMED |
| Otherwise | NOT_CONFIRMED |

**Order:**

- CONFIRM needs TEST.
- FINAL needs TEST ("never FINAL before TEST").
- CONFIRM and FINAL never feed back into any choice.
- FINAL reports R0 flagged and unflagged results per census third. `final_val` and `final_test` are the unseen part.

## 12. Stop rules (PLAN §8 and §4.2)

1. **Data first:** every stage refuses unless `FLOW/validation.json` passes:
   - V1;
   - V2 ≥ 99%;
   - V3 ≥ 95%;
   - V4.
2. **VAL** needs a complete, non-provisional TRAIN result and the three shortlists. VAL runs once.
3. **KILL or UNDERPOWERED at VAL** stops G1: TEST, CONFIRM and FINAL are not spent.
4. **TEST, CONFIRM and FINAL** run once each. This is enforced by the stage's JSON file and by the trials ledger.
5. **No stage runs** if this file changed after the lock.
6. **X1 caveat (PLAN §8 rule 2):** every return here uses minute-bar "worst" fills. If X1 later finds minute-bar
   fills off by ≥ 1 point, G1's return-based numbers (c3 and the class-loss tables) are re-run on replayed fills,
   with no new configs. The label-based c1 and c2 do not depend on fills.
7. **Live monitoring (PLAN §4.2):** disable a shipped gate if its precision falls below 80% on two days in a row.

## 13. Known limits (stated before seeing data)

- **Minute bars carry no wallet roles,** so ORGANIC means "none of the gate classes" and is not wallet-organic. G1
  declares `uses_organic_flow = False`.
- **Wallet identity:**
  - `ARu4n5mF…` is excluded from top-buyer lists.
  - `BwWK17cb…` (one bot) is kept.
  - The stored AGENT identity can be wrong on about 1 coin in 140.
- **Airdrop dump:** the bar signature only sees the dump. The equal-amount transfers need `token_transfers` (B4).
  Dumps before graduation, on the curve, are not seen.
- **SERIAL** uses `CreateEvent.creator`, which is NULL without creation data. Mayhem and non-SOL graduates count in
  the registry. A creator that rotates wallets is not caught.
- **Census day vs TRAIN days:** the regime may differ. TRAIN numbers say nothing about FINAL beyond what FINAL
  itself shows.
- **Parquet version:** files consolidated before the audit patches price with a constant virtual reserve (bias up
  to 0.42%) and use the 330 s AGENT window. A re-consolidation is picked up automatically, and the run records the
  data file timestamps.

## 14. Commands

```bash
python research/lab2/g1.py --debug                         # census TRAIN third, counts only
python research/lab2/g1.py --stage train --check           # prerequisites only (any stage)
python research/lab2/g1.py --stage train                   # needs complete TRAIN data
python research/lab2/g1.py --stage train --allow-partial   # provisional, no shortlist
python research/lab2/g1.py --stage val
LAB2_ALLOW_TEST=1 python research/lab2/g1.py --stage test
LAB2_ALLOW_CONFIRM=1 python research/lab2/g1.py --stage confirm
LAB2_ALLOW_FINAL=1 python research/lab2/g1.py --stage final
python -m pytest -q research/lab2/tests/test_g1.py
```
