# Z4 pre-registration: theme momentum (and its inverse, theme exhaustion)

- **Version:** `z4-v1`.
- **Written:** 2026-10-09, before any Z4 run on TRAIN, VAL, TEST, CONFIRM or FINAL data. TRAIN was still being
  backfilled. Every constant, the tokenizer and stop-word list (§2.3), the grid (§7), the controls (§10) and the
  decision rules (§9) were fixed in this file **before** the debug run on the census TRAIN third (§14). That run
  reports counts only: returns hidden, no parameter chosen there.
- **Code:** `research/lab2/z4.py`, on the shared foundation `research/lab2/common.py` (every feature through
  `common.AsOf`). Tests: `research/lab2/tests/test_z4.py`.
- **Data:** `graduates`, `b2_coins`, `b2_bars` only (B2 minute bars to g + 180 min). No B1, no B3, no CryptoHouse
  queries.
- **Protocol:** PLAN §3 (shared protocol), §3.5 (entry and veto bars), §3.6 (automatic rejections), §6.6 (leakage
  rules for cross-coin outcomes) and §8 (stop rules), through common.py's `AsOf`, `backtest`, placebo, `describe`,
  `verdict_entry`, `verdict_veto`, trial ledger, shortlists and one-shot sessions. Stage gating and CLI follow
  `m1.py`; the cross-coin registry follows `y1.py`'s causal pattern.
- **Splits:** common.py's (TRAIN 10-01 → 10-05, VAL → 10-06 12:00, TEST → 10-07 19:37:30, CONFIRM 09-16 → 10-01,
  FINAL = census day; the census TRAIN third is debug only).
- **Freeze.** The first official TRAIN run hashes this file into `Z4/prereg.lock`. After that `z4.py` refuses every
  stage if this file changed. A change is a new version (`z4-v2`) in `Z4/AMENDMENTS.md`, and its configs are new
  trials.

## 1. Hypothesis and mechanism

**Claim (momentum).** When other deployers' coins whose name or symbol shares a theme token with a fresh graduate
(e.g. `claude`, `gemini`, `oil`) graduated in the previous N hours **and did well after migration**, the fresh
graduate, bought at g + 30 min while it is alive, outperforms a matched random entry and clears the round trip.

**Why it could beat costs.**

1. **Attention is the only demand a memecoin has, and it moves by theme.** A theme member that ran is seen on
   trending lists, in "next X" posts and in keyword search (Barber and Odean's search problem: buyers pick from what
   they can find). Searchers for the theme find the other members. That flow is cross-coin information: it is not
   in the coin's own chart, which is all wave 1's rules (and most single-coin bots) condition on.
2. **Fresh pools are levered to flow.** At g + 30 min the pricing reserve X = x + v is typically 50-200 SOL. A net
   inflow ΔX lifts the price by ((X + ΔX) / X)² − 1, so 10 SOL (≈ $1-2k) of spillover buying into X = 100 SOL is
   +21 %. A $20 round trip costs 1.4-5.1 % by market cap (`research/lab2/common.py`, fee tier by date + Ultra 10 bps
   + 20 bps buffer + impact on the pool's own k + network fees). The bet needs a spillover of a few SOL per coin.
3. **Who pays:** later theme buyers who arrive after the spillover starts (they buy from us), and the decay that
   copies otherwise suffer is offset only if the theme flow is real.

**The inverse (exhaustion).** A hot theme attracts copy deployers. Each new member is new supply, dumped by its
deployer; attention is finite and concentrates on the leader, the Schelling point (PLAN N1 / behaviour lens H3,
whose sanity check expects "buy the new copy" to be strongly negative). Under exhaustion, **new members of a theme
that just ran do worse** than other theme members. A long-only bot cannot short them, so exhaustion is useful only
as a **filter** ("skip new members of themes that just ran"), and a filter can only make a host lose less (PLAN §0).
It is therefore tested as a **veto on a host** with PLAN §3.5's veto bar (§6), on the same observable as the
momentum claim, with the opposite sign. Both cannot pass.

**Why it may fail** (the honest prior is that momentum fails and exhaustion, if anything, holds):

- **The theme premium is taken on the curve.** Sniper bots key on trending names at creation. A copy that graduated
  probably graduated *because* of the theme; by g + 30 min its premium is already in the price and decaying.
- **Attention goes to the leader, not the copies** (H3).
- **Copies are dumped** by their deployers; at g + 30 min some of that supply is still coming.
- **Generic tokens make fake themes** (`cat`, `dog`, `trump`, `fund`): they link unrelated coins. The heat uses only
  the 3 most recent resolved members (a broad token gets no bonus for having many members), results are bootstrapped
  by theme key, and the pass bar requires ≥ 10 keys, ≥ 5 profitable keys and a positive mean without the best key.
- **Factory ticker clones** (one operator relaunching a symbol from different keys) can masquerade as a theme. Links
  between coins of the **same creator are excluded** (that is Y1's signal), and exact-symbol clones are reported
  apart (§11). They are not excluded: excluding them would be a post-hoc choice either way.

### 1.1 Not a duplicate

| Hypothesis | What it uses | Z4 differs by |
|---|---|---|
| Y1 | outcomes of the **same creator's** earlier graduates | Z4 links **different** creators only, through name / symbol tokens |
| PLAN N1 (H3) | buys the theme **leader** when a copy graduates | Z4 buys the **new member**, conditioned on the theme's resolved outcomes; N1's "buy the copy" sanity check is Z4's exhaustion mirror |
| G1 / craft G04 (RA-03 ticker reuse) | counts of ticker reuse as a FACTORY flag | Z4 conditions on the **outcomes** of theme members; counts are a diagnostic only |
| X1 (smart money), X2 (breadth rank), Y2 (organic curve), Z1-Z3, M1, S1, D1 | wallets, flow, bars of the coin itself | Z4's only signal is other coins' names and outcomes |

## 2. Data and the registry

### 2.1 History (outcome records), by stage

The registry runs forward through the splits; a stage reads outcomes only from splits earlier in time and already
open at that stage (as Y1):

| Stage | History splits (outcome records) |
|---|---|
| debug | `final_train` only |
| TRAIN | `train` only (CONFIRM is sealed) |
| VAL | `train`, `val` |
| TEST | `train`, `val`, `test` |
| CONFIRM | `confirm` only |
| FINAL | `train`, `val`, `test`, the three census thirds |

**Structural pool** (names, never outcomes): every graduate of any quote or Mayhem flag created in [first history
split start, stage split end). Its `name`, `symbol` and `creator` are read through `AsOf` at g + 20 s (legal from
creation or g) and used only for a coin with g_p < g of the coin being decided (< τ). The first N hours of each
history range have a truncated lookback; those decisions are counted as warm-up (reported, not removed).

### 2.2 Outcome record of an earlier member (a label of that coin, never its feature)

For an earlier **usable** graduate p (SOL-quoted, not Mayhem, complete B2; common.py's universe):

- t_ref(p) = the first decision-grid time (minute boundary + 20 s) at or after g_p + 420 s (post-BOOST).
- t_end(p) = t_ref(p) + 30 min.
- r(p) = `AsOf(p, t_end).price / AsOf(p, t_ref).price − 1`: the mid-price change over its first post-BOOST half
  hour, no costs. This is "performed well after migration".
- **Resolved at decision time t** only when t_end(p) ≤ t (every bar it reads ended before τ = t − 20 s).

### 2.3 Theme tokens (frozen)

`tokens(name, symbol)`:

1. Each of `name` and `symbol` (NULL or empty → nothing) is NFKD-normalized and combining marks are dropped
   (`Pokémon` → `Pokemon`; full-width letters → ASCII).
2. Split into runs of Unicode letters and digits (`[^\W_]+`; emoji, spaces and punctuation separate).
3. Each run gives its case-folded self, plus its camelCase / letter-digit parts
   (`ClaudeCat` → `claudecat`, `claude`, `cat`; `GROK4` → `grok4`, `grok`).
4. A token is kept when it is not all digits, not a stop word, and has ≥ 3 characters (ASCII) or ≥ 2 characters
   (any non-ASCII character: CJK names are short).

**Stop words** (generic English, crypto boilerplate, hype words and launch venues; frozen here, never extended from
data):

```
the and for but not you your are was were will can has have had with this that these those from into onto over
all any its his her him she they them our out off get got just now new one two who why what how when where here
there than then very more most much many some only also too yes let lets like make made back big top best real
true first last next ever never every day today time year world life way thing really still
coin coins token tokens sol solana crypto pump pumpfun pumpswap fun meme memes memecoin memecoins inu official
community cto dao launch swap dex chain onchain mint holder holders airdrop presale wallet
moon lambo wagmi ngmi degen gem gems send based alpha ath rich money cash buy sell hold hodl bull bear
fomo family bags bonk letsbonk raydium jupiter
```

(`bonk` is listed as the letsbonk launch venue; animals, people, products, places and companies are **not** stop
words: they are what themes are made of.)

### 2.4 Theme members of coin i at decision time t (τ = t − 20 s)

- i's own `name`, `symbol`, `creator` through `AsOf` (legal from creation or g). NULL creator, or no token → status
  **unknown** (NULL is never 0; slow graduates without a scanned CreateEvent have NULL names).
- **Members** M(i, t): structural-pool graduates p with g_p ∈ [t − N, g_i), p ≠ i, `creator_p` known and **≠
  creator_i**, and tokens(p) ∩ tokens(i) ≠ ∅.
- **Crowding** k = |M(i, t)| (every quote, Mayhem included: all of them are supply competing for the theme).
- **Resolved records** R = r(p) for usable members with t_end(p) ≤ t, ordered by g_p.

## 3. Features at the decision (all as of τ)

| Feature | Definition |
|---|---|
| status | `unknown` (§2.4), `solo` (k = 0), `pending` (k ≥ 1, no resolved record), `eligible` (≥ 1 resolved record) |
| `heat` H | mean r(p) over the **most recent 3** resolved members (by g_p). A broad token gets no bonus for size |
| `k` | crowding (§2.4) |
| primary key | the shared token with the most members (ties: alphabetical). The theme cluster for bootstraps (§11) |
| exact clone | some member has the same case-folded alphanumeric symbol as i (diagnostic) |
| `alive` | `AsOf.alive()`: ≥ $1.5k volume in 15 min and market cap ≥ $6k |

## 4. Entry rules (one decision per coin)

The decision time is the first decision-grid time at or after **g + 30 min** (age 30:00-30:59). Nothing is entered
earlier or later; there is no waiting for a better moment.

- **MOM(N, θ)** (hypothesis `Z4`): enter when status = eligible, `alive`, and H ≥ θ. Otherwise skip the coin.
- **HOST(N)** (hypothesis `Z4-host`): enter when status = eligible and `alive`, whatever H. MOM(N, θ) is exactly the
  subset of HOST(N) trades with H ≥ θ.

Each trade is tagged `hot` / `cold` (H ≥ 0.25 or not) and `few` / `crowd` (k ≤ 2 or k ≥ 3).

## 5. Exits and fills (fixed, one exit set)

- Time exit **60 min** after the entry fill; catastrophe stop **−50 %**; registered deadline g + 178 min
  (`exit_by_age_s`, never binds: the last entry fills by g + 32 min).
- Fills: `common.FillConfig(exit_delay_bars=1)`: $20, latency 30 s, entry at max(open, high) of the landing bar,
  exits at min(open, low), stops checked from the entry bar, **every triggered exit fills in the next bar** at its
  adverse side. PumpSwap fee tier by date + 10 bps Ultra + 20 bps buffer, network fees, pricing on X = x + v.
- No trade can end on the data horizon; criterion 10 (≤ 10 % censored) is still checked.

## 6. The inverse: the exhaustion veto (`Z4-exh`)

- **Host:** HOST(N).
- **Flag:** `hot` = H ≥ 0.25 at the host entry (the lower θ; no new threshold).
- **Verdict:** `common.verdict_veto` (PLAN §3.5 veto bar): (1) flagged mean ≤ unflagged mean − 10 points with the
  coin-bootstrap 95 % CI of the difference excluding 0; (2) out of sample, removing flagged trades raises net
  profit; (3) it removes < 25 % of the host's winning profit. UNDERPOWERED with < 30 flagged or < 30 unflagged.
- **Diagnostic only:** the flagged-minus-unflagged difference split by crowding (`few` / `crowd`). Exhaustion's story
  predicts the drag is larger when k ≥ 3.

## 7. The grid: every configuration is a counted trial (8 in all, limit 12)

| Hypothesis | Configs | Count |
|---|---|---:|
| `Z4` MOM | N ∈ {3 h, 12 h} × θ ∈ {+0.25, +1.0} | 4 |
| `Z4-host` HOST | N ∈ {3 h, 12 h} | 2 |
| `Z4-exh` | the §6 veto on each TRAIN host | 2 |
| **Total** | | **8** |

- **N:** 3 h is a fresh spillover (PLAN N1 clusters over 3 h); 12 h is a meta's day.
- **θ:** +0.25 = the theme's recent members rose a quarter in their first post-BOOST half hour (several round trips);
  +1.0 = they doubled on average (a visible trending run). Neither was chosen from data.
- One exit set (§5), fixed a priori, so the grid does not multiply.
- Each params dict carries every constant in §2-§6, the stop words' hash, the fill model and the version. Any change
  is a new trial. TEST / CONFIRM / FINAL re-run shortlisted configs under the same identities.
- **Stress runs** (same call, never used to select): costs × 1.5; rent $0.22; same-bar exits (`FillConfig()`).

## 8. No separate model check

Z4 has no structural prediction to fit before P&L (unlike M1's drift model). The HOST (every eligible theme
member) is the built-in null for MOM, and the matched control (§10) isolates heat from theme membership. A
dose-response statistic, Spearman(H, `ret_net`) over HOST trades, is reported on every non-debug stage and never
decides.

## 9. Procedure by stage (`python research/lab2/z4.py --stage …`)

### Every stage

A stage refuses to run unless:

- `Z4/PREREG.md` exists, and matches `prereg.lock` once locked;
- stop rule 1 holds: `common.validation_gates` passes for the split;
- coverage is complete: every chain hour scanned, ≤ 5 % of tradeable coins miss B2, no mid-run hour, SOL/USD covers
  the split (FINAL is exempt from the completeness part);
- guarded splits have the judge's flag (`LAB2_ALLOW_TEST`, `LAB2_ALLOW_CONFIRM`, `LAB2_ALLOW_FINAL`); `z4.py` never
  sets it.

Two **branches** run in parallel and stop independently: **MOM** (entry rule) and **EXH** (veto).

### TRAIN (all searching)

Run the 6 configs, each with the matched controls (§10) and stress runs; log the 2 veto evaluations.

**MOM branch.** A MOM config qualifies when all hold:

| Requirement | Bar |
|---|---|
| Sample | ≥ 30 trades from ≥ 10 theme keys |
| Mean net | > 0 |
| Mean without the top 2 trades | > 0 |
| Matched-control `mean_diff` (eligible-member placebo) | > 0 |

Choice: the qualifying config with the highest theme-key bootstrap 90 % CI lower bound; ties → higher mean → θ = 1.0
→ N = 3 h.

**EXH branch.** HOST(N)'s veto qualifies when ≥ 30 flagged and ≥ 30 unflagged trades, and veto criterion 1 holds on
TRAIN (flagged ≤ unflagged − 10 points, 95 % CI upper bound < 0). Choice: the N with the lower CI upper bound;
ties → N = 3 h.

**Shortlists** (written before VAL with `common.write_shortlist`, frozen at the first VAL run):

- `Z4` = [the chosen MOM config] (MOM branch only);
- `Z4-host` = [HOST(N) for the MOM choice's N and/or the EXH choice's N] (1 or 2 configs).

**TRAIN decision:** SHORTLISTED (branches listed) if either branch qualifies; otherwise NO_CONFIG if some MOM config
or veto met its sample bar, else UNDERPOWERED_TRAIN. A complete TRAIN's decision is final (a re-run needs
`--rerun-reason` naming a data correction). `--allow-partial` runs a PROVISIONAL TRAIN that never writes a lock or a
shortlist.

### VAL (shortlisted configs only, once)

| Branch | Decision |
|---|---|
| MOM | UNDERPOWERED_VAL (n < 5) / FAIL_VAL (mean ≤ 0 or mean without top 2 ≤ 0) / SELECTED_UNDERPOWERED (5 ≤ n < 15) / SELECTED |
| EXH | UNDERPOWERED_VAL (< 5 flagged) / FAIL_VAL (flagged not worse, or powered and criterion 1 fails) / SELECTED_UNDERPOWERED (< 30 flagged or unflagged, flagged worse) / SELECTED (criterion 1 holds) |

A branch proceeds on SELECTED or SELECTED_UNDERPOWERED.

### TEST (one `common.one_shot_session` for the Z4 family; live branches only)

- **MOM:** `common.verdict_entry(test, val=VAL candidate, min_mean=0.03)` (PLAN §3.5 items 1-8 and 10, §3.6) plus:

  | ID | Criterion |
  |---|---|
  | Z4.1 power | ≥ 60 trades from ≥ 10 theme keys |
  | Z4.2 | theme-key bootstrap 90 % CI lower bound > 0 |
  | Z4.3 | mean > 0 without the most profitable key |
  | Z4.4 | ≥ 5 distinct keys with positive summed net profit |

  Combined as in M1 / Y1: REJECTED > UNDERPOWERED > FAIL > INCOMPLETE > PASS. Item 9 is judged after FINAL.
- **EXH:** `verdict_veto` with the VAL host (EXH N) in sample and the TEST host out of sample.
- UNDERPOWERED is expected on a 1.3-day TEST.

### CONFIRM (one run, never searched; live branches only)

- MOM is live when TEST was not REJECTED and (TEST mean > 0 or TEST n < 5). EXH is live when the TEST veto verdict is
  not FAIL. CONFIRM refuses when no branch is live.
- MOM: the TEST verdict rules. EXH: `verdict_veto` with all three criteria on CONFIRM itself.

### FINAL (the census day; after TEST)

Live branches once, as one session. Criterion 9 (MOM mean > 0; EXH flagged mean < unflagged mean) is judged on
`final_val` + `final_test`; `final_train` was the debug third and is reported apart.

**Overall:** MOM = EDGE only with VAL selected, TEST not failed, CONFIRM PASS and FINAL mean > 0. EXH = VETO only with
VAL selected, TEST veto not FAIL, CONFIRM veto PASS and FINAL flagged < unflagged. Otherwise UNDERPOWERED or NO EDGE
per branch.

## 10. Controls

- **Matched control (judged, §3.5 item 5 and the TRAIN bar):** `common.backtest`'s placebo, 20 draws per signal at a
  decision age within ±120 s, `alive`, and **stratum = eligible theme member** at the draw's own time for the config's
  N. This isolates **heat** from "being a theme member". With a thin stratum, fewer than 20 draws may succeed in 200
  tries; the draws per signal are reported.
- **Unmatched control (reported):** any alive coin at the same age.
- **HOST** is the cleanest comparison for MOM (same coins, same time, H < θ removed) and is always reported next to it.

## 11. Metric, statistics, theme-key clusters

- Unit: `ret_net` per $20 trade, one entry per coin per config. `common.describe`: coin and 6-hour block bootstrap
  CIs, mean without the top 2, halves, top-coin share, censored share, deflated Sharpe over every ledger trial; the
  $100 / 5-slot portfolio; stress means.
- **Theme-key clusters:** each trade's primary key (§3). Trades of one theme share its news and its buyers, so CIs
  also resample keys (H3: "bootstrap by key-cluster"). Mean without the most profitable key; number of profitable keys.
- **Diagnostics, never decisive:** by tag (`hot|few`, `hot|crowd`, `cold|…`), exact-clone links vs token-only links,
  instant (≤ 5 s) vs slow graduates, warm-up decisions, the top keys by trade count, Spearman(H, `ret_net`).

## 12. Leakage rules (PLAN §6.6), enforced in code and tested

1. **Strictly past:** a record counts only when t_end(p) ≤ t and g_p < g_i; never the traded mint.
2. **No marking to a later price:** a record is a closed 30-minute window.
3. **Forward in time:** history splits only (§2.1); the structural pool's names are used only for g_p < g_i.
4. **Leakage test** (`tests/test_z4.py`): garbage after T in every coin's bars, and new / renamed graduates after T,
   leave every registry answer and every decision at τ ≤ T unchanged (synthetic, and real census-third bars).
5. **Declarations** to `auto_rejections` (the theme record is a reputation of a token built from other coins):

   ```
   uses_wallet_reputation = True        # cross-coin outcome registry (themes, not wallets)
   reputation_excludes_traded_coin = True
   uses_organic_flow = False
   uses_truncated_windows = False
   uses_current_state_fields = False
   ```

## 13. Kill criteria and deviations

**Kill criteria:** stop rule 1 (data first); stop rule 7 (report FAIL_VAL per branch); stop rule 8 (every config
counts, §7). There is no model-check stop (§8).

| Area | Deviation |
|---|---|
| Themes | Name / symbol tokens only. No tweet ids, no IPFS metadata (descriptions, links), no images: the PLAN's H3 keys on tweet ids too |
| Records | Only **graduates** (and only usable ones) carry outcomes; failed curves of the theme are invisible |
| "Performed well" | The first post-BOOST half hour's mid change, not a market cap, volume or trending rank |
| Universe | Every usable coin; FACTORY / OPERATOR coins are not removed (reported by instant / slow and exact clone) |
| Fills | Minute-bar "worst" fills with next-bar exits, not replayed fills (X1 engine) |

## 14. Debug findings and expected sample (census TRAIN third, counts only)

**The run.** `python research/lab2/z4.py --debug` writes `Z4/debug.md` and `Z4/debug.json` (runtime 5 s).

- 450 usable coins, created over 12.5 h (0.52 days). History is that same third only (§2.1): 450 records; the
  structural pool has 708 graduates, 585 of them with a creator and a theme token (753 distinct tokens).
- Returns, exit reasons, record values, placebo outcomes and the veto means are hidden. Its trials go to a scratch
  ledger, never to `trials.json`.
- **Nothing in §1-§13 changed after this run**: no tokenizer, stop-word, threshold or grid edit.

**Counts at the decision (first grid time ≥ g + 30 min):**

| Measure | N = 3 h | N = 12 h |
|---|---:|---:|
| Alive at the decision (all N) | 137 of 450 | 137 of 450 |
| Status of all 450 coins | solo 287, eligible 118, unknown 32, pending 13 | solo 228, eligible 178, unknown 32, pending 12 |
| HOST entries (eligible and alive) | 41 (78.8 / day) from 32 keys | 55 (105.7 / day) from 39 keys |
| … linked through an exact-symbol clone (other creator) | 30 | 42 |
| … instant graduates (≤ 5 s) | 33 | 42 |
| … crowded (k ≥ 3) | 7 | 23 |
| … warm-up (lookback truncated by the third's start) | 7 | 54 |
| MOM θ = 0.25 entries = `hot` flags | 2 (3.8 / day) | 4 (7.7 / day) |
| MOM θ = 1.0 entries | 1 (1.9 / day) | 0 |
| Matched-placebo draws per signal (HOST) | 17.4 of 20 | 19.2 of 20 |
| Trades ending on the data horizon | 0 | 0 |

Top HOST keys (N = 3 h): `oil` 4, `fund` 3, `gta` 2, `nvidia` 2, `digital` 2, `apple` 2, then single coins (`craft`,
`muse`, `human`, `cat`, `fish`, `nyt`, …).

**What these counts imply, before any TRAIN data** (assuming other days resemble this third):

- **On this third, "themes" are mostly ticker-clone series.** About 3 in 4 HOST entries share an exact symbol with an
  earlier graduate from a **different** creator key, and about 4 in 5 are instant graduates. Narrative tokens (`oil`,
  `gta`, `nvidia`, `apple`) exist but are the minority. The pre-registered link split (§11, exact clone vs token-only)
  is therefore the diagnostic that says which mechanism any result belongs to. It never decides, and the universe is
  not changed (§13).
- **Generic words still form keys** (`digital`, `fund`, `human`, `states`, `american`). The stop-word list stays
  frozen (§2.3); the key-cluster bootstrap, the ≥ 5 profitable keys bar and "without the best key" carry that risk.
- **Hot themes are rare.** Only 2-4 of 41-55 HOST entries have heat ≥ +25 %: most theme members' first post-BOOST half
  hour is negative, as for graduates in general.
- **Expected power:**

  | | TRAIN (4 d) | VAL (1.5 d) | TEST (1.32 d) | CONFIRM (15 d) |
  |---|---:|---:|---:|---:|
  | HOST, N = 3 h / 12 h | ≈ 315 / ≥ 420 | ≈ 120 / ≥ 160 | ≈ 105 / ≥ 140 | ≈ 1,180 / ≥ 1,590 |
  | MOM θ = 0.25 (= veto flags), N = 3 h / 12 h | ≈ 15 / ≥ 31 | ≈ 6 / ≥ 12 | ≈ 5 / ≥ 10 | ≈ 57 / ≥ 115 |
  | MOM θ = 1.0 | ≈ 8 / ≈ 0 | ≈ 3 / 0 | | |

  N = 12 h rates are lower bounds: 54 of 55 of its decisions on this third had a truncated lookback.
- **The most likely TRAIN outcome is UNDERPOWERED_TRAIN or a single borderline config** (MOM θ = 0.25, N = 12 h,
  near the 30-trade / 10-key bar). The EXH veto needs ≥ 30 flagged trades: borderline on TRAIN at N = 12 h, out of
  reach at N = 3 h, and underpowered on VAL (SELECTED_UNDERPOWERED at best). **CONFIRM (15 days) is the only split that
  could power either branch.** These are the pre-registered answers, not code failures.
