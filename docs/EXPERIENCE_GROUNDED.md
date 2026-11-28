# The 91 craft rules, grounded against code and data

Written 2026-10-09 ~00:30 UTC. Sources:

- **Code:** `src/nightcrawler/{cocoon,radar,strategy,risk,engine,judge,crawler}.py`, plus `config.py`, `backtest.py`,
  `broker/`, `readiness.py`, `teamroom.py` and `learn/`. The Coach's phase-1 package is being merged into `main` as
  this is written; it is also on worktree `wf_4007eb01-37f-1`.
- **Lab results:** `research/lab/RESULTS.md` (census lab, judge and audit), and `research/lab2/` (`common.py`,
  `G1/` and `S1/` PREREG and debug).
- **Plans and audits:** `scratchpad/ideas/PLAN.md`, `scratchpad/flow/AUDIT.md`, `research/flow/README.md` and
  `scratchpad/learning/LEARNING.md`.
- **Scratch outputs:** `scratchpad/experience/{dp,risk,rug,exit}_scripts`.
- **Backfill state:** `FLOW/manifest.json` at 23:58 UTC.

Nothing in the repository was changed.

## In plain words (for the owner)

- **What "experienced" can honestly mean for a bot.** It has four parts:
  1. how many independent situations it has studied with known outcomes;
  2. which rules survived a test on coins they had never seen;
  3. whether every trade is graded and the lesson changes behaviour;
  4. a skill score per team member that says "no measurable skill yet" until it has earned more.
- **Where the 91 rules stand today:**
  - 6 already exist in the bot;
  - 33 exist in part;
  - 52 are missing.
  - None of them is an edge on its own. A rule that refuses bad trades only makes a losing strategy lose less.
- **The most valuable fixes are cheap and need no new data:**
  - stop booking rug losses at the stop price;
  - measure a coin's age from graduation, not creation;
  - skip Mayhem coins and other launchpads nobody has tested;
  - get out when the price feed goes blind;
  - size for the -90% gap, not the -18% stop;
  - fix the "20-30 good paper trades" go-live rule.
- **The ideas that could make money (S1, insider supply spent) are blocked.** They need wallet-level trade data
  that has not been downloaded yet.

---

## Notes that change how the 91 rules can be tested (read first)

**N1. The rules use the wrong split dates.** The JSON's test designs use PLAN's EXT splits:

- TRAIN 09-16 → 09-27;
- VAL 09-28 → 10-01;
- TEST 10-02 → 10-07.

The code that will run them, `research/lab2/common.py` `SPLIT_BOUNDS`, uses different ones:

| Split | Dates (UTC) | Use |
|---|---|---|
| train | 10-01 → 10-05 | Search |
| val | 10-05 → 10-06 12:00 | ≤ 2 configs, from a shortlist written before the run |
| test | 10-06 12:00 → 10-07 19:37:30 | One run, behind an environment guard |
| confirm | 09-16 → 10-01 | One run, never searched |
| final | the census day | Holdout |

**Running any rule's "EXT-TRAIN 09-16..09-27" search would burn the sealed CONFIRM split.** Every design below is
re-keyed to the lab2 splits.

What this does to sample sizes:

- **VAL is 1.5 days.** At the G1 debug rates (~865 usable coins a day, 180 R0 and 25 dip-rule host trades a day),
  that is ~1,300 coins, ~270 R0 trades and ~37 trades for the bot's own dip rule.
- **Use R0 as the veto host.** Veto bars such as "≥ 100 vetoes on VAL" are reachable only on the R0
  random-alive-entry host, not on the bot's dip rule. PLAN already does this.
- **TRAIN has only 4 days.** Day-level heterogeneity tests (DP-17) are weak until more days are opened.

**N2. What data actually exists now.** No rule can be tested on EXT outcomes today. The data codes used below:

| Code | Meaning | State on 10-09 00:00 UTC |
|---|---|---|
| D0 | Code change, unit test or simulation on existing scratch data | Available |
| D1 | Census day: lab TRAIN and VAL thirds (448 + 150 coins, swap-api minute bars, half or worst fills), plus the 36 audit swap windows (274,857 swaps). One day. The census TEST third is spent | Available |
| D2 | lab2 TRAIN graduates and B2 bars | Pending: about 300 more queries, roughly 4 h of quota |
| D3 | B1 raw trades (P4) and B3 positions (P3) | **0 coins**. About 1,500 queries (≈ 17 h) for the lab2 windows, or about 55 h for the full 22 days |
| D4 | New CryptoHouse queries: `token_transfers`, funder SOL transfers, wallet first-seen | Not written |
| D5 | Forward only: the tape, the paper/live ledger and Railway logs | Weeks |

- **Consolidated tables.** `graduates.parquet` holds 1,783 graduates from 10-06 17:00 to 10-08 19:59. That is lab2
  TEST plus FINAL, both sealed for searching.
- **Raw backfill.** It has reached curve hours from 10-05 18:00 and B2 hours from 10-05 21:00 (4,037 graduates),
  still inside VAL and TEST.
- **Not done yet.** lab2 TRAIN, B1 and B3.
- **"~27k coins over 22 days" is the target,** not the current state.

**N3. The bot trades a universe that nobody has tested.** The crawler admits:

- every Jupiter launchpad (`launchpad_deployer` lists bags.fun and launch services);
- Mayhem coins (no Mayhem check anywhere in `src/`, except Coach replay and `costs.py`);
- slow graduates at graduation time (N5, G12).

Every result we have covers pump.fun graduates that are SOL-quoted and not Mayhem. That includes the lab census,
CryptoHouse, lab2 and the Coach replay. Until something is validated elsewhere, the experienced move is to trade
only that universe (G01, G02).

**N4. Folklore already inside the bot that our data contradicts:**

1. **The Cocoon's hard fails as a rug shield.**
   - On genuine graduates, mint, freeze, extensions and LP pass 100% (F1, F2), so they carry no information.
   - The factory airdrop gives 2,200 wallets 0.036% each, which passes the concentration caps.
   - Farm rugs came from 9-13% holders, below the 10% cap or only just over it (G02, G07).
2. **The address-based serial-launcher rule.** Only 7 of 1,145 creators were reused, and `devMints` counts
   platforms (G06).
3. **Creator-watch as a rug alarm.** 0 of 9 rugs came from the creator (G20).
4. **Paintable entry confirmation.** The strategy confirms on raw candle volume rising and on DexScreener's 5-minute
   buy/sell transaction-count ratio, both of which dust bots paint (G15, G16).
5. **Stop fills at min(level, close)** in `backtest.py` and the Coach's shadow book (G22).
6. **The "positive over 20-30 closed trades" go-live gate** in `docs/GOING_LIVE.md` §0 (G39).
7. **20% sizing ≈ full Kelly, and the daily loss limit is not a bound** (G38, G39).
8. **Jev is told to weigh socials and paid promotion** (G09).
9. **The default dip-rebound itself.** It made 1 TEST trade (-22.1%), and the F1 dip strategies lost on every
   split and every stress test.

**N5. Where the losses avoided actually are.** These are census random entries with the bot's exits (half fills;
"instant" here means graduated ≤ 60 s after creation; `dp_results.json`):

| Age since graduation | Instant graduates | Slow graduates |
|---|---|---|
| 0-30 min | **-15.7%**, stopped out 43% of the time | -10.0%, stopped out 49% |
| 30-120 min | -6.9% | -8.6% |
| 2-6 h | -4.7% | -6.9% |

The big measured losses all sit **before** the bot's window:

- buying at graduation and holding 1 h: -68%;
- farm rugs 13-24 min after graduation: -84% to -97%.

The bot's window starts at ≥ 60 min after creation, which for instant coins is about g + 60 min. So most "avoid"
rules protect future hosts that enter between g + 6 and g + 120 min (S1, D1, M1). For today's bot they help only
through the age bug (G12). Inside the bot's window, instant coins were *not* worse than slow ones on the census day.

**N6. The trial budget is limited.** Every veto or exit test adds configurations to `research/lab2/trials.json`, and
the deflated Sharpe ratio already counts 2,575.

- Schedule about 15 tests (the P0 and P1 rows below), not 91.
- Run folklore checks only as counted, descriptive tables on hosts that run anyway: EX-08, EX-09, PE-12(b), PE-18
  and R15.

**N7. As-of rules referenced in the table:**

| Rule | Statement |
|---|---|
| AO-1 | The cutoff is τ = t − 20 s. Use only events with block_time ≤ τ (lab2 `AsOf`) |
| AO-2 | A `b2_bars` minute m is visible only when `minute_ts + 60 ≤ τ` (`bars_asof`) |
| AO-3 | `graduates` curve and completion columns are known at g; `z_*` and `l_*` at created + 120 s. All are NULL, never 0, when `has_create = 0` (17% of non-instant coins) |
| AO-4 | `w120_*` from t ≥ g + 140; `w300_*` from t ≥ g + 320. AGENT identity only from `agent_known_at` (its 4th slice), via `detect_agent(as_of=τ)`. Window totals only after g + 420 s. `agent_buy_sol` is NaN before then |
| AO-5 | A B3 row summarizes [created, g + 60 min]. For other coins, use it only from the window end + 20 s. For the coin itself, only at t ≥ g + 60 min + 20 s. An open position (`end_tok` > 1% of peak) is censored and contributes nothing |
| AO-6 | Registries (creator, completer, funder, wallet) use only coins whose window closed before t − 20 s, and never the traded mint. They are built forward in time, with thresholds fitted on TRAIN only, a warm-up flag and the PLAN §6.6 rule 9 leakage unit test |
| AO-7 | Current-state fields (RugCheck, Jupiter organic and holder fields, DexScreener profile, RPC holders) are valid only when logged at decision time (tape `safety`, FW1). Never use them on historical coins |
| AO-8 | Outcomes are labels, never features. `label_ready_ts` = t + L + h + 10 min. A post-mortem may read outcomes of the graded coin only |
| AO-9 | B1 (P4) holds non-dust trades (≥ 0.01 SOL) over [created, g + 120 min], **for non-factory coins only** (graduated more than 5 s after creation). Price before a trade = (x0 + virt_ksol × 1000) / y0. Failed transactions and pooled accounts are excluded. Features are NULL at τ ≥ g + 7,200 |
| AO-10 | Use SOL/USD from closed minutes only (the `SolUsd.at` lookahead found in RESULTS A1) |
| AO-11 | Use lab2 splits and guards (N1) |

**N8. Priority.** Priority combines expected value per trade with feasibility.

- **Value per trade** is the loss avoided or the edge gained, in percentage points (pp), from the cited evidence.
- **Feasibility** is the data code (N2) plus the size of the code change.

| Priority | Meaning |
|---|---|
| **P0** | Do now. D0 or D1, and it either removes a measured misstatement of ≥ 5 pp per trade or closes a safety gap with a total-loss tail |
| **P1** | Next 1-3 days, on D1 or D2. Plausible value ≥ 2 pp per trade, or needed by other tests |
| **P2** | Blocked on D3 or D4, or worth ≤ 2 pp per trade |
| **P3** | Forward-only or live-only, low incidence, or a folklore check whose prior is rejection |

Status codes in the table:

| Code | Meaning |
|---|---|
| AI | Already implemented |
| P | Partial |
| M | Missing |
| C | Contradicted by our data |
| U | Untestable |

When an existing behaviour in the bot is the folklore our data contradicts, the cell says so.

---

## The table (91 rules → 62 rows; merged IDs share a row)

### Safety and universe

| # | IDs | Grounded rule [owner] | Status | Where in code today | Already covered by | Data + as-of | Priority (value × feasibility) |
|---|---|---|---|---|---|---|---|
| G01 | RA-02 | [Cocoon] Skip Mayhem coins: CreateEvent or bonding-curve flag, supply > 1e9, or real SOL at completion < 80. Supply ≤ 1e9 does not prove non-Mayhem | **M.** No Mayhem check in engine, cocoon or crawler. lab2 `load` and the Coach replay already exclude Mayhem, so the live bot trades coins no test covered | `cocoon._check_mint_account` gets `supply` from `solana_rpc.mint_info` and never reads it; `sources/pumpfun.py` returns `mayhem_state` | Lab census and lab2 universes; F3: 410 of 1,783 graduates (23%); F4 supply signature (25/25, 50/50) | Live: RPC supply / 10^decimals at check, plus pump.fun `mayhem_state` (immutable). Historical: `graduates.is_mayhem`, `rsol_complete`, `mayhem` at g. The detection confusion matrix can be built now on the 1,783 graduates. The current supply is valid evidence, because the > 1e9 test is one-sided | **P0.** Value in pp unknown. It removes a 23% slice where fills and features are invalid. About 5 lines of code (D0) |
| G02 | RA-01 | [Cocoon] Provenance invariant: a coin of pump.fun origin must be Token-2022 with exactly {metadataPointer, tokenMetadata} and null mint, freeze and update authority, or it fails. Keep the blacklist for other launchpads. "Is Token-2022" carries no information | **P.** The authority checks and the dangerous-extension blacklist exist, and Token-2022 is correctly never penalised. The exact-set invariant and a launchpad check are missing | `cocoon._check_mint_account`, `DANGEROUS_EXTENSIONS`, `_apply_rug_report`; the crawler accepts every Jupiter launchpad | F1: 1,542 of 1,548 graduates are Token-2022; F2: 100/100 by live RPC | RPC `getAccountInfo` jsonParsed at check; `graduates.token_program` and `pool` at g. Sweeping ~27k mints takes ~270 `getMultipleAccounts` calls | **P2.** About 0 pp on genuine graduates, since it never fires there. Its real job is the non-pump coins the crawler admits (N3) |
| G03 | RA-15 | [Broker] Measure liquidity, price and crash risk on the canonical pool only. Route exits through it unless another route is strictly better at the exact size | **P.** The cocoon fails a DLMM or CLMM candidate pool. The Broker passes no dex restriction to Ultra | `cocoon._check_lp`, `_lp_locked_pct`; `broker/live.py` | PLAN C1 engineering track (not started) | `graduates.pool` (canonical, g + 0-6 s). `n_pools` is never a feature (it encodes later pools). FW2 route per quote (D5) | **P3.** 13 of 1,783 graduates have more than one pool. RESULTS A4: Pack's second venue cut its round trip to 0.40%, so a blanket restriction can cost money |

### Coin-class gates

| # | IDs | Grounded rule [owner] | Status | Where in code today | Already covered by | Data + as-of | Priority |
|---|---|---|---|---|---|---|---|
| G04 | PE-11, RA-03, RA-04 | [Crawler/Strategy] G1 class at g + 140 s. OPERATOR (≥ 500 SOL of pool buys and ≤ 30 buyers in 2 min) goes to M1 only. FACTORY: instant (≤ 5 s) with top-5 share ≥ 0.85, or a ticker reused ≥ 3 times in 48 h. COMPLETED: completer or top-3 share ≥ 0.6, or < 15 buyers. "Fast fill = strong" holds only for many-wallet fills | **P.** PE-11 and RA-04 are missing; RA-03 is partial. The bot has only `[copycat]` (ticker seen on another mint within 6 h) and `[impersonation]` **warnings**, passed to Jev. It has no graduation delay (it never reads Jupiter `graduatedAt`) and no pool-flow class. The "fast fill = strong" folklore is C for instant coins (63% are factory) | `cocoon._add_name_warnings`, `normalize_ticker`; `crawler.launchpad_deployer` | lab2 G1 PREREG with 3 variants (G-time, G-chain, G-chain+) and the G1.dip and G1.R0 hosts. Debug, counts only, 450 census coins: FACTORY 183, OPERATOR 34, COMPLETED 19, ORGANIC 193, UNRESOLVED 21. RA-03's ticker variant and PE-11's "fast organic" cell are **not** in G1; adding them is a counted amendment | `graduates.grad_delay_s`, `completer_sol`, `curve_top3_buy_sol / curve_buy_sol`, `curve_n_buyers` (AO-3). A causal ticker count over **all** CreateEvents with c_ts < τ, needing creates of non-graduates too (D4). `b2_coins.w120_*` (AO-4) | **P1** (D2). Large where it applies: random entries in instant coins 0-30 min after g lose -15.7% per trade; buying at g loses -68%. Inside the bot's ≥ 60-min window it may be worth about 0 (N5). Required as the S1/D1 universe filter |
| G05 | RA-10 | [Strategy] On a repeat-completer coin (completer bought ≥ 60% of the last 30 SOL, or has ≥ 3 earlier completions in a past-only registry), enter only after its position is ≤ 10% of its peak | **M** in the bot | — | lab2 S1 entry: a COMPLETED coin needs `completer_pos_frac` ≤ 0.10. There is no repeat-completer registry | `graduates.completer`, `completer_sol` (g); registry per AO-6; completer position from B1 (AO-9). F9: 24.8% of non-instant graduates (an in-sample count) | **P2** (D3) |
| G06 | PE-05, RA-12 | [Cocoon] Judge a creator by its funder cluster's earlier launches (all CreateEvents, 1-2 hops, exchanges excluded), not by its address | **P, address part C.** `[serial_launcher]` (Jupiter `devMints` > 20, plus RugCheck's creator rug history) exists. Our data contradicts it as a factory detector: F8 found 7 of 1,145 creators reused; `devMints` counts platforms (170k-191k); lab2 debug flagged SERIAL on 1 of 450 coins | `cocoon._check_jupiter_audit`, `_apply_rug_report`; `crawler.prefilter`, `KNOWN_LAUNCHPAD_DEPLOYERS` | lab2 G1 `serial` (by address, 24 h) in G-chain+ | D4: system-program SOL transfers into `creator` / `create_user` in the 7 days before c_ts (`err = ''`), and all CreateEvents per creator. Outcomes per AO-6 | **P2.** Value unknown. Kill it if fewer than 20% of creators resolve to a funder. Keep the cheap address rule until G08 has graded it |
| G07 | PE-04 | [Cocoon] Top-10 and single-holder caps stay hard fails only if they beat "no cap" out of sample; otherwise they become logged features | **AI, unvalidated.** Hard fails exist: top-10 > 30%, single holder > 10%, creator > 5%, insiders > 15% (with ≥ 5 graph insiders). Their protection is **C** for factory and farm coins (N4.1) | `cocoon._check_concentration`, `_check_creator`, `_check_insiders`; `COCOON_*` settings | none | Historical holder balances need a B1 replay plus `token_transfers`, and factory coins are not in P4. **U historically, so the test is forward only:** the tape's `safety` rows (AO-7), graded by G08 | **P2.** Do not remove a fail-closed rule without evidence. Keeping it costs only missed trades |
| G08 | PE-17 | [Coach] Log every Cocoon and Radar veto with a shadow outcome. Grade it weekly: precision against the base loss rate, missed winners, and paired improvement with an e-process. Demote it after ≥ 200 vetoes if it shows no value; raise a drift alarm | **P.** Reject receipts carry stable rule ids (`[top10]`…), and the tape's `evals` stream logs `reject_*` decisions (phase 1). There are no per-rule shadow outcomes and no grading | `cocoon._fail`; engine receipts; `learn/` tape | The LEARNING shadow book grades strategies, not vetoes | Tape `evals` (rule id and value at the decision), phase-2 `safety` stream, shadow replay outcomes after `label_ready_ts` (AO-8) | **P1** (D5, cheap on the tape). It is the only way to grade current-state rules (G07, RugCheck, Shield) |
| G09 | PE-13 | [Jev] Socials, "DEX paid", boosts and profiles are not entry evidence unless a test shows ≥ +5 pp. Test a recent boost as a veto | **M: the code does the opposite.** Jev's system prompt says to weigh "presence and plausibility of socials; paid promotion". Its features include social flags and `paid_promo`, and the cocoon warns `[no_socials]` and `[paid_promo]` | `judge.STATIC_SYSTEM_PROMPT`, `build_features`; `cocoon._add_candidate_warnings`; `crawler._remember_promotions` | PLAN P1 (DexScreener orders, an 18-min pull, not run). G1 NEWS and G-full are not tested (no IPFS metadata) | `graduates.uri` → IPFS (immutable, known at creation); DexScreener `/orders/v1/solana/{mint}` `paymentTimestamp` + 5 min display lag ≤ t; FW5 forward | **P1.** Cheap prompt change now: say socials and paid promotion are not evidence. Then test with the P1 pull (D2 plus about 1,100 calls) |
| G10 | PE-14 | [Cocoon] Veto when wallets with a learned rug habit (≥ 10 prior coins, ≥ 80% dead) hold or buy a large share | **M** | — | PLAN W1 stage 1 (does wallet skill persist?) is the go/no-go for every registry rule | `b3_positions` (P3: 0 coins), AO-5 and AO-6; death labels of earlier coins only; pooled accounts excluded | **P3** (D3). It must beat the G1 class, which probably explains most of it |
| G11 | PE-09 | [Strategy] Never enter because a KOL or "smart" wallet bought. ≥ 3 tracked wallets buying within 5 min is a crowding veto | **P.** "Never follow" already holds, because no wallet-follow trigger exists. The crowding veto is missing | — | PLAN W1 stage 1. PLAN §6.6 rule 6 bans undated KOL lists and PnL leaderboards | Registry from `b3_positions`, frozen at the end of **lab2 train**; B1 buy timestamps on val. **U for KOL labels:** we have no dated pre-09-16 lists | **P3** |

### Entry and flow

| # | IDs | Grounded rule [owner] | Status | Where in code today | Already covered by | Data + as-of | Priority |
|---|---|---|---|---|---|---|---|
| G12 | PE-10, RA-09 | [Strategy] The earliest entry is the delay after which waiting no longer improves net returns. Never enter before the BOOST bid ends (about g + 6 min). Lab rule: no entries in the first 30 min after graduation | **P.** `MIN_AGE_MIN` (60) is measured from token **creation**, so instant graduates are entered at ≥ g + 60. A slow graduate created more than 60 min before it graduated **can be entered at g + 0**, inside BOOST and inside the lab's 30-min ban. Jupiter `graduatedAt` is documented in `sources/jupiter.py` but never mapped | `crawler.prefilter`, `crawler._age_min`, `engine._universe_problem`, `sources/jupiter.token_to_candidate` | RESULTS "when not to trade" (no entries in the first 30 min). PLAN §6.7 diagnostic 3 (the BOOST cliff) has not run. S1 checkpoints start at g + 6 | `graduates.g_ts` (exact to the second); `b2_bars` `minute_idx` with AO-2. Live: Jupiter `graduatedAt` or GeckoTerminal launchpad `completed_at` | **P0 for the code** (map `graduatedAt` and require ≥ 30 min since graduation). Census slow graduates: -10.0% at 0-30 min against -8.6% at 30-120 min and -6.9% at 2-6 h (stopped out 49%), so about 1-3 pp per affected entry. **P1** for the delay-curve test (D2) |
| G13 | PE-01, PE-03, RA-13 | [Strategy] Enter only when the cheap insider inventory (creator, bundle, snipers, completer, transferees) is mostly spent and organic net flow is positive: this is S1. The launch bundle share is a logged feature, not a gate | **M.** The nearest thing is cocoon `[insiders]` (RugCheck's current insider-network share > 15%), a current-state proxy that cannot be backtested. **The vendor-band hard gate (PE-01) is C on selectivity:** F11 puts the median creation-slot share on non-instant coins at 0.42 (IQR 0.26-0.59), so the "> 30% engineered" band flags about two-thirds of them | `cocoon._check_insiders` | lab2 S1 PREREG. Its dose-response gate is exactly the PE-03 and RA-13 test, with 8 variants. Its debug ran on **synthetic** B1 only. RA-13's comparison (`bundle_share` quintiles on the same coins) is not in S1: add it as a counted descriptive | B1 roles per S1 PREREG §5 at τ (AO-9); `graduates` `z_buy_tok / 793.1e6`, `sn60_*`, `first20_buy_sol`, `completer*` (AO-3). TRANSFEREE comes from orphan sells only, because B1 has no `token_transfers` | **P2.** The best-specified entry idea (PLAN bar: ≥ 6 pp over control), but blocked on P4 (D3). Highest priority among the blocked rows |
| G14 | PE-02, RA-07 | [Cocoon/Radar] Zero-cost supply. Refuse while transfer-in holdings or orphan sells are material. Treat identical-balance holders (≥ 10 of the top 20, or ≥ 100 identical transfers from one authority) as one holder, and the coin as FACTORY | **M** in the bot; the caps miss it by design | — | lab2 G1 `airdrop_seen` (≥ 1,000 sell trades within ≤ 2 consecutive minutes, ≥ 3× sells to buys) in G-chain+, the bar-level proxy. S1 entry requires `orphan_share10` < 0.15. **Timing:** the Coinbase dump came at creation + 16 min, so for instant coins it is already over by the bot's entry | Proxy: `b2_bars` `n_sells`, `n_buys` (dust included; AO-2). `b3` `orphan_tok`, `n_orphan_sellers` (AO-5). Live: RPC `getTokenLargestAccounts` or RugCheck `topHolders` at check (AO-7). `token_transfers` (D4; it includes failed transactions, so use it as a prefilter only) | **P1** for the bar proxy (D2, inside G1). **P2** for the transfer and orphan share (D3, D4) |
| G15 | PE-06, RA-05 | [Radar/Strategy] Painted volume is not demand. If more than half of the last 10 minutes' trades are dust at more than 300 trades/min, or wash wallets dominate, refuse entries triggered by volume or momentum | **M: the code does the opposite.** Dip-rebound confirms on "last candle volume > previous" (raw volume) and on DexScreener `buy_sell_ratio_m5` ≥ 1.2, a ratio of transaction **counts**. Dust bots paint both | `strategy.entry_signal` (`volume_up`, `ratio_m5`); `MIN_BUY_SELL_RATIO` | F7: dust share 0.80 on instant clones against 0.09 on slow coins; 184 of 324 instant clones were over the threshold against 0 of 304 slow coins. The F4 "winner" learned paint (A3). Partly covered by G1 FACTORY | `b2_bars` `n_dust`, `n_buys`, `n_sells`, `buy_sol` (AO-2). Live proxy: the DexScreener snapshot's `volume_m5 / txns_m5` (average trade size), already fetched. Wash scores need B1, which excludes dust and factory coins | **P1** (D2). It must add value beyond G1 (RA-05's own falsifier) |
| G16 | PE-07, RA-14 | [Crawler/Strategy] Measure demand as distinct organic net buyers paying ≥ 0.01 SOL. Raw holders, trades, volume or trending rank may nominate a coin, never confirm it | **M: the code uses raw counts.** `ratio_m5` counts transactions; `[low_holders]` warns below 100 holders; `MIN_ORGANIC_SCORE` exists but is 0 (off). GMGN's trade-count rule is **C** (factories run a median 341 trades/min) | `strategy.entry_signal`; `cocoon._add_candidate_warnings`; `crawler.prefilter` | lab2 S1 `org_buyers10` and `org_net10` (B1) | Proxy: `b2_bars` `n_buyers` (a sum of per-minute counts double-counts wallets), and `buy_sol − agent_buy_sol` (AO-4). FW1 Jupiter `numOrganicBuyers` forward only (AO-7) | **P1** (D2 proxy). It only improves an input of a host that has shown no edge |
| G17 | PE-12 | [Radar] (a) No entry within 10 min of a creator or creator-funded sell of ≥ 20% of the creator's peak. (b) "Dev fully sold" is not a buy signal unless it tests positive | **P.** (a) Before an entry the radar rejects any creator sell ≥ $300 in the last 15 min (GeckoTerminal trades), matched by address only. (b) Nothing treats a dev exit as bullish, which is correct | `radar.Radar.evaluate`; engine entry path | S1 entry `creator_sold10` < 0.20, and its exit on a creator sell ≥ 20% of peak | `graduates` `creator_*_tok`, `l_creator_*` (AO-3); B1 for sells after g; D4 transfers to tell "sold" from "moved" | **P3.** Rare inside the bot's window: F10 has 31.5% of slow creators selling within 120 s of launch, instant creators sell 0% on the curve, and 0 of 9 farm rugs came from the creator. Part (b) is testable on `graduates` columns once D2 lands |
| G18 | PE-08 | [Cocoon] Refuse when wallets younger than 24 h, or wallets sharing one funder, carry a large share of recent buying or of the top holdings | **M.** `[insiders]`, via RugCheck's graph, is a current-state proxy | `cocoon._check_insiders` | none | D4: each wallet's first signed transaction (`solana.transactions`) and first inbound SOL transfer; AO-1; exchange hot wallets excluded | **P3.** Expensive per-wallet queries, and it must survive a control for G1 and G14 |
| G19 | PE-16, EX-15 | [Broker/Coach] Know our speed. Measure decision-to-fill latency (p50 and p90) and each rule's value of speed Δ(D). Reject edges that need faster fills. Build a websocket feed only if Δ(2 s) ≥ +2 pp | **P** for PE-16, **M** for EX-15. The tape's `lag` stream and timestamped receipts exist. Paper fills have no landing latency. Δ(D) is not computed | Engine receipts; `learn/` lag stream; `POSITION_INTERVAL_S` 10, `WATCH_INTERVAL_S` 60 | PLAN X1 output 2 and its decision rule. RESULTS A3 and A5: 1-5 s replays were identical on farm coins, entries 1-2 min later were no worse; "latency is not the weak point" | B1 replay at D from 0.5 to 60 s (non-factory coins only, AO-9). Factory and farm coins only through swap-api (D1) or B2 bar delays. Paper ledger timestamps | **P1** to measure our own p50/p90 (cheap). **P2** for Δ(D) (D3) |
| G20 | RA-11, RA-08, EX-10 | [Radar] Label a big sell by where its tokens came from (bundle, sniper, completer, transferee or orphan seller, early top-5 pool buyer), not by the creator address. Exit at once on a distribution wave: orphan share ≥ 25% of the last 60-120 s; ≥ 20 near-identical sellers within a few slots; or SOPR3 > 2 with insider share > 0.5. While SOPR3 < 0.8 (capitulation), do not stop out on price unless the catastrophe level is hit | **P** for RA-11, **M** for RA-08 and EX-10. The radar reads GeckoTerminal trades ≥ $300 over a 15-min window and attributes them creator > RugCheck insider > RugCheck top holder. It flags creator sells, insider sells ≥ $500, and big sells ≥ 10% of liquidity. A dump of 2,200 small sells is invisible to it, because each is far below $300. **The creator-watch premise is C** (0 of 9 rugs) | `radar.Radar.evaluate`, `_role`; `RADAR_*` settings | PLAN V1, folded into the S1 exits (`orphan_share10` > 0.25). D1's DIST/CAP classes (module in progress, task #20) | B1 wallet ledger: position, average cost, `orphan_part`, and SOPR3 over (τ − 180, τ] (AO-9). Factory coins need B3 or `token_transfers`. **Live, it needs parsed pool trades with signers, which today's sources do not provide** | **P2** (D3, plus a missing live source). It must also pass G21 |
| G21 | EX-13 | [Radar/Coach] A danger signal counts as an exit only if it leads the crash by more than our exit latency on ≥ 50% of crashes and its paired effect is positive. Otherwise demote it to an entry veto and a post-mortem label. Exit signals that are kept must run at the 10 s price cadence | **M.** Every radar flag exits, whatever its lead time (`exit_signal` checks the radar first). The radar re-scans every 180 s with a 60 s cache: about 240 s worst case, plus GeckoTerminal's lag | `strategy.exit_signal`; `engine._manage_one`; `RADAR_INTERVAL_S` 180, `RADAR_CACHE_S` 60 | RESULTS A3: farm rugs are one swap, which no signal can lead. AUDIT: the factory dump was over in 26 s | B1 and B2 crash times (one trade or one minute falling ≥ 50%); signal inputs at τ | **P2** (D3). It frames every exit-on-signal rule |

### Exits and fills

| # | IDs | Grounded rule [owner] | Status | Where in code today | Already covered by | Data + as-of | Priority |
|---|---|---|---|---|---|---|---|
| G22 | EX-01 | [Coach] A stop is a market order. Every simulator fills stops, trails and time exits at the first trade at or after trigger + latency (B1), or at min(open, low) of the bar after the trigger bar. Never fill at the level. Log the gap slippage of every exit | **P.** lab2 `FillConfig` "worst" (min(open, low)) has `exit_delay_bars`, defaulting to 0. `backtest.py`'s default `stop_fill="close"` fills at min(level, close), **and the Coach's shadow book (`learn/replay.py`) inherits it** | `backtest.py` `CostModel.stop_fill`; `learn/replay.py` exit fill; `research/lab2/common.py` `FillConfig` | RESULTS A3: rug stops booked at -51% to -59% were really -84% to -97%; F4 on TEST went from -5.4% to -17.7% per trade; rug-aware finalists lost -17% to -32%. X1 output 1 | B1 (AO-9), but **P4 excludes factory coins, which are the ones that gap**. For them, use B2 next-bar fills or swap-api (36 audit windows, D1) | **P0.** About 12 pp per trade of misstatement on rug-exposed hosts. Set the shadow book and backtest default to next-bar min(open, low) now, and label older numbers "optimistic". Calibrate on the 36 audit windows |
| G23 | R01, RA-06, PE-15 | [Risk] Per-trade risk = ticket × L_max, where L_max = max(0.95, p95 single-swap rug loss, crash capacity 1 − (y / (y + H))²). H is the largest non-pool holder, with clusters merged. Skip the coin if its crash capacity is ≥ 0.75; refuse thin real pool SOL | **M** for R01 and RA-06, **P** for PE-15. Sizing is 20% of equity (cap $25, minimum $5) with no gap term. There is no crash-capacity check, only a $30k liquidity floor and the 10% single-holder cap | `risk.size_position_usd`, `RiskManager.size_position`; `POSITION_PCT`, `MIN_LIQUIDITY_USD`; `cocoon._check_concentration` | RESULTS A3: 9 of 9 rugs were one sell of 9-13% of supply, falling 86-93% in one swap. `dist_kelly`: P(r ≤ −80%) = 2.2% in the worst-fill null | Live: RPC `getTokenLargestAccounts` (pool vaults and burns excluded), plus pool vaults x, y and signed v, at decision and every tick (AO-7). Historical: `b2` `x_close`, `y_close` (AO-2) for depth; H from B1 positions (non-factory only) | **P0** for using L_max = 0.95 in all risk arithmetic (D0): at 20% sizing a rug costs about 19% of equity, not the 3.6% the stop implies. **P1** for depth buckets (D2). **P2** for crash capacity (D3 or live RPC) |
| G24 | EX-02, EX-09 | [Strategy] Test a wide catastrophe stop (-35% to -50%) plus a time stop against today's -18%. Test breakeven stops but do not adopt them (prior: rejection) | **M** for the EX-02 test. **AI** for EX-09: there is no breakeven stop, which matches the prior | `STOP_LOSS_PCT` 0.18; `strategy.exit_signal` | PLAN X1 exit grid (-15%, -25%, catastrophe -50% with 60 min) and E1; lab2 G1.R0 uses X1 exit 6. F1 lost 7-8 of its 10 TEST trades to stops | `b2_bars` with worst fills and `exit_delay_bars` = 1 (G22); hosts R0 (5 seeds) and the dip rule; AO-10 | **P1** (D2). It touches every trade. At most 2 shortlisted cells |
| G25 | EX-03 | [Strategy] Confirm ordinary stops on a closed bar or two polls; fire a catastrophe stop (about -40%) on touch. Only if ≥ 30% of wick breaches recover | **M.** Stops trigger on touch of the 10 s Jupiter price | `strategy.exit_signal`; `engine._manage_one` | PLAN X1 output 4 (stop regret) | B1 per-trade prices (AO-9); a minute-bar regret proxy on B2 | **P2** (D3); the bar proxy is **P1** |
| G26 | EX-04 | [Strategy] Set each class's maximum hold from the crash hazard h(age, class), so that the cumulative crash probability over the hold stays ≤ 10%. Never hold through a known clock window | **M.** The time stop is a fixed 120 min | `MAX_HOLD_MIN` 120 | Census: the stop-out rate for instant coins falls from 43% (0-30 min) to 8% (30-120 min) to 1.2% (2-6 h). The farm's crashes cluster at g + 15-30 min | `b2_bars` cover only [g, g + 180). The bot enters at ≥ creation + 60 min and holds 120 min, so most of its trades end beyond that. Use the tape's 50 h of candles (D5), or extend B2 to g + 6 h for a sample | **P1** (D2). The steep age gradient argues for age gates (G12) more than for shorter holds |
| G27 | EX-05 | [Strategy] Stale-trade exit: if the best gain (MFE) is below Y after T minutes, exit | **M** | — | Census: 7,631 of 9,434 random trades ended at the time stop with a median of -5.1%, about the round-trip cost. An earlier exit cannot refund costs already paid | `b2` highs and closes, closed bars only (AO-2) | **P2** |
| G28 | EX-06 | [Strategy] Prefer a fixed target set from the host's TRAIN distribution of best gains. Keep a trailing stop only if it beats that target out of sample. Also test measuring the peak from closes instead of wick highs | **P.** Today the bot sells 50% at +40%, then trails 15% from a peak taken from the **highs** of closed candles | `strategy.exit_signal`, `exit_levels`; `TAKE_PROFIT_PCT`, `TRAIL_PCT` | RESULTS A3: every take-profit filled at +26% on real swaps. X1 grid | `b2` OHLC; a take-profit fills at the level only if the bar closes above it (lab2) | **P1** (D2) |
| G29 | EX-07 | [Strategy] While in profit, sell into bursts of organic buying | **M** | — | none | `b2` `buy_sol − agent_buy_sol`, `n_buyers` (AO-2, AO-4) | **P2.** Exploratory |
| G30 | EX-08 | [Strategy] Keep "sell half at +X" only if it beats both a full exit and no partial out of sample. Never leave a remainder under $5 | **AI, untested.** The bot sells 50% at +40% (adopted folklore) with no floor on the remainder. lab2 has no partial exits | `PARTIAL_TP_FRACTION` 0.5; `engine._exit` | none | `b2` bars; $0.022 network fee per swap. Rent is never refunded, even on a full exit, so a partial adds one fee, not rent | **P2.** About ±0.5 pp. It needs partial exits in lab2 |
| G31 | EX-11 | [Strategy] Exit when organic buying collapses: organic buy SOL over the last 5 closed minutes < 30% of the 5 minutes before entry, and distinct buyers < 50% | **M** | — | S1 exit `org_net5` ≤ -1 SOL | `b2` `buy_sol`, `n_buyers`, minus AGENT (AO-2, AO-4) | **P2.** Run the D2 dose-response first |
| G32 | EX-12 | [Strategy] Thesis stop: exit when the reason for the trade flips. For dip-rebound, that is the rebound low L taken out by a closed bar | **M** for dip-rebound. `metrics.low` and `low_ts` are computed at entry and never used at exit | `strategy.entry_signal` metrics | The PLAN and S1 PREREG exit specs for S1, D1 and M1 | `b2` bars; B1 for the S1/D1/M1 states | **P2.** The dip-rebound host has no edge |
| G33 | EX-14 | [Broker] Blind means out. If there is no price, or the price is older than 30 s, use an Ultra sell quote for the whole position as the price. Two failed quotes force an exit, retried every interval | **M.** In `engine._manage_one`, a missing price leaves only the time stop (up to 120 min) and logs `position_unpriced`. `_prices` already falls back to DexScreener | `engine._prices`, `_manage_one` | Jupiter Price v3 drops tokens it flags for "market health", which is the state just after a rug | Railway logs (`position_unpriced`, `price_feed_failed`); the Ultra quote is the executable price at t | **P0.** A cheap safety rule (a unit test plus a replay check). The blind state coincides with rugs. Cost: one Ultra call per blind position every 10 s |
| G34 | EX-16 | [Risk] Add a server-side -50% stop (Jupiter Trigger) only if the losses in unmanaged gaps exceed its fee plus the cancel-and-withdraw latency it adds to every exit | **M.** Live only | Engine stage budget; `unresolved` mints | PLAN X1 output 5 | Railway heartbeat and stage logs; the ledger keeps only `last_marked_at` | **P3.** Measure the unmanaged share first |
| G35 | EX-20 | [Broker] At $20, sell in one swap; never slice, never wait for a bounce. A quote above 3% impact means the wrong route or pool: re-quote on the canonical pool and alert | **AI.** Exits are one swap; forced exits accept up to 25% impact. The alert and re-quote are missing. Caveat: pump.fun's docs say v can be negative since Sep 30, and the pipeline reads v only when 0 < v < 100 SOL (G48) | `engine._exit`, `EXIT_MAX_IMPACT_PCT` | `impact_bound.py`: 0.18% at X = 102.6 SOL, 1.03% at 17.6 | Paper sell quotes (impact, route); the sign of `b1.virt_ksol` | **P3** |
| G36 | EX-19 | [Coach] Exit skill = rule minus placebo exits drawn from the rule's own holding-time distribution (same entries, fills and costs). No exit rule is adopted with skill ≤ 0. Report the bot's current exits first | **M.** lab2 has a matched-timing placebo for entries only; the Coach has a random-entry placebo family | `research/lab2/common.backtest`; `learn/families/placebo.py` | RESULTS random-entry reference: -6.4% per trade | `b2` with G22's fills; `t_in`, `t_out` | **P1** (D2, cheap). It is the honest "exit experience" number for G58 |
| G37 | EX-17, R11, PE-18 | [Risk/Radar] Regime gate (PLAN R1). Halve or stand down when the trailing 6-h single-swap rug rate is in its top 20%. Cut everything when the meme market breaks (median 15-min return ≤ -20% with > 50% of coins down, or SOL -3% in 15 min). Trade on launch heat, not the clock | **M.** There is no regime logic. The "trade the US session" folklore is weakly C: the lab's by-hour means swing from -59% to +26% with no pattern that holds across splits | — | PLAN R1 (next wave, score 20). Hour clustering was inconclusive (3 of 8 seeds at p < 0.01); the hourly ICC is about 0 | Causal `g_ts` counts; `b2` cross-section at τ; outcomes only of coins whose 60-min window has closed (AO-6); AO-10 | **P3.** Weak prior |

### Risk and sizing

| # | IDs | Grounded rule [owner] | Status | Where in code today | Already covered by | Data + as-of | Priority |
|---|---|---|---|---|---|---|---|
| G38 | R05, R06, R09 | [Risk] Budget limits on Σ open ticket × L_max: a daily budget (realized + marked + open × L_max + new × L_max ≤ 15%), a drawdown floor (exposure ≤ the cushion above (1 − D) × peak), and a total-at-risk cap instead of 3 positions | **P** for R05 and R06, **M** for R09. The daily loss limit checks marked equity before entries only. The drawdown halt is a 50% cliff. Three positions at 20% each put about 57% of equity at gap risk | `risk.can_open`, `_daily_loss_rule`, `_drawdown_rule`, `_positions_rules` | `policy_mc`: the 90th-percentile worst day is 41-43% against a nominal 20%, and 13-14% with the budget rule. The cliff can end at about 78% drawdown | Ledger `equity_series` (mode-filtered), open positions, `day_start_equity`; L_max from G23 | **P1** (D0: simulations and unit tests). It binds once real money moves, and it makes paper risk numbers honest now |
| G39 | R02, R03, R16, R17 | [Risk/Coach] Real stake = 0 until an anytime-valid lower bound on mean net return is above 0 (the stage-2 gate: ≥ 150 paper trades over ≥ 14 days). Then at most ¼ Kelly at that bound, and at most the risk-constrained Kelly fraction on a rug-aware distribution. No funding when the trades needed to prove the edge (n*) exceed the trades available before it decays. Never go live on "20-30 positive trades" | **P** for R02 and R16, **M** for R03 and R17. The bot is paper-only today, so the stake is 0 in effect. `readiness.py` requires a champion that passed a locked test. `learn/gate.py` has `S2_MIN_N` 150, `S2_MIN_DAYS` 14 and `LIVE_PROBATION_TRADES` 50; phase 2 is not built. **`docs/GOING_LIVE.md` §0 still says "positive after fees over at least 20-30 closed trades", which is C:** a zero-edge strategy passes about half the time at n = 30. `POSITION_PCT` 0.20 is about full Kelly at a +3% edge with 10% rugs | `readiness.py`; `learn/gate.py`; `docs/GOING_LIVE.md` §0 | LEARNING §5.4 and §5.10; `sim2` and `sim3`; `rck.py` | `learn.db` evidence and scoreboard; `null_trades.json` | **P0** for the GOING_LIVE §0 text (D0). **P2** for RCK and n* sizing, which matter only once an edge exists |
| G40 | R04 | [Broker] Reclaim token-account rent (close the account in the sell, or batch-close empty accounts) before moving to smaller tickets. Minimum ticket s_min = 4F/μ | **M.** Paper books rent and never refunds it (`paper.py`). Live books Ultra's `rentFeeLamports` on buys. No close-account instruction exists | `broker/paper.py` `KV_RENT`; `broker/live.py` | PLAN C1 ("close the token account in the sell transaction regardless"), not started | `rent_lamports` on fills, kv `paper.rent`; RPC `getTokenAccountsByOwner` | **P1.** A certain gain: +1.1 pp per $20 round trip ($0.216 rent), +4.3 pp at $5 (D0, broker change) |
| G41 | R08 | [Risk] At most one open position per operator cluster (creator, funder, factory or airdrop family, completer, or normalized ticker family), and its stake counts once | **P.** Only `[already_open]` per mint and a 30-min per-mint cooldown | `risk._positions_rules`, `_cooldown_rule`; the cocoon's ticker memory (`normalize_ticker`) | RESULTS §2.6: all 12 F4 TEST trades were one farm. `cocrash.py`: 1.23× for factory pairs against 0.75× for organic pairs (one day, weak) | `graduates` `creator`, `completer`, `symbol`, `grad_delay_s` (g). Live: the cocoon's 6-h normalized ticker memory. Funder links later (D4) | **P1.** The ticker-family proxy is cheap live; test it on D2 |
| G42 | R10 | [Broker] Cap entry impact at about 0.75%, and at ≤ ¼ of the expected edge. Skip quotes whose impact is more than 2× the constant-product prediction from the reserves | **P.** `MAX_PRICE_IMPACT_PCT` is 3.0; there is no cross-check against reserves | `MAX_PRICE_IMPACT_PCT`; `broker/base.py` | `ticket_costs.py`; RESULTS A4 (quotes within 0.0-0.35 pp of the model) | Tape quotes (phase 2), paper quotes; `b2` `x_close`, `y_close` | **P3.** At $100k+ a $20 trade moves the price ~0.1-0.3%, so the cap rarely binds |
| G43 | R12 | [Risk] Live ladder: start at the minimum ticket and step up ×1.5 per 50 live trades, only while the paper-live twin gap is ≥ -1 pp, the CUSUM is quiet, and G39 allows | **P.** `LIVE_PROBATION_TRADES` and `TWIN_DEMOTE_PP` are constants; there is no ladder | `learn/gate.py` | LEARNING §5.4 and §7 | Live and twin paper fills (FW2) | **P3.** Only after an edge exists |
| G44 | R13 | [Risk] Sweep equity above about $125 to the owner and never refill after losses. Base the wallet tripwire on equity attributed to the bot, not a fixed $150 | **P.** `MAX_WALLET_USD` 150 refuses new live entries once the wallet is worth more than $150, so success stops the bot. The sweep is not built (task #6) | `risk._wallet_cap_rule` | `sim2` part c (sweeping: median $111; compounding: $92, decaying edge) | Ledger deposit and sweep receipts; wallet value | **P2.** Live only |
| G45 | R07 | [Coach] Judge edge decay with the CUSUM / e-process on per-trade returns, which does not depend on sizing. Set the equity backstop from the current sizing, so that a real edge hits it with ≤ 5% probability | **P.** The CUSUM constants (reference -1%, c 14 and 10) and `VARIANT_DD_DEMOTE` 0.35 exist; phase 2 is pending. The risk halt is fixed at 50% | `learn/gate.py`; `risk._drawdown_rule` | LEARNING §5.5; `sim2` (at 20% sizing, a real +3% edge hits a 30% drawdown 100% of the time) | Champion evidence; σ̂ frozen in the promote receipt | **P2** |
| G46 | R15, DP-07 | [Risk/Coach] No tilt, equity-curve or anti-martingale sizing unless a streak effect is shown | **AI.** There are no such rules; the 30-min per-mint cooldown is harmless. The census day supports this: after 3 losses the next trade averaged -6.7% against -6.5% overall; lag-1 autocorrelation was 0.019 (SE 0.041); a matched re-entry after a stop was -0.4 pp [-1.8, +1.1] | `risk._cooldown_rule` | `dp_results.json`, `reentry_results.json` | Time-ordered trades; streaks count only trades with exit_ts < the next entry_ts | **P3.** Keep. Re-check on D2, because this is one day of evidence |

### Jev

| # | IDs | Grounded rule [owner] | Status | Where in code today | Already covered by | Data + as-of | Priority |
|---|---|---|---|---|---|---|---|
| G47 | RA-19, DP-08 | [Jev] Jev keeps its veto only if, on coins that passed every deterministic rule, its "no" votes land on later rugs and losers more often than a random veto at the same rate, net of API cost. Its confidence must be calibrated and its verdicts repeatable (≥ 80%). It sees numeric fingerprints (class, crash capacity, dust share, orphan share, `insider_rem`), never just names | **M.** Jev is veto-only and fail-closed, with a $1/day cap, at the default temperature. Its confidence is parsed and clamped but never scored. Vetoed coins are not followed up. Its features lack every fingerprint above, because none exists yet | `judge.Judge.decide`, `build_features`, `STATIC_SYSTEM_PROMPT` | none | Offline: 400 situations with names masked, rebuilt as of decision time from lab2 train bars (AO-1, AO-2), using coins after the model's training cutoff; about $6. Forward: tape `evals` plus shadow outcomes (AO-8) | **P1** (D2 plus $6). A veto without value costs API money and blocks trades at random |

### Coach and the experience process

| # | IDs | Grounded rule [owner] | Status | Where in code today | Already covered by | Data + as-of | Priority |
|---|---|---|---|---|---|---|---|
| G48 | RA-16 | [Coach] Evidence hygiene before any wallet or flow rule: drop failed transactions; exclude pooled accounts; read `has_create = 0` as NULL; price at (x + v) / y with v per trade; handle PostCompleteBuyEvent | **P**; mostly done in research. The SQL keeps `err = ''`. lab2 `POOLED_ACCOUNTS` has 1 address (BwWK17cb is only flagged as a suspect). `AsOf` applies the NULL rule. v is carried per trade, and the AGENT window is 420 s. **Missing:** a signer-checked exclusion list for the ~50 most frequent top buyers (about 2 queries); a PostCompleteBuy scan; negative-v handling (v is read only when 0 < v < 100, so those coins drop out as `virt_unknown`, a survivorship risk) | `research/flow/sql/*.sql`, `features.py`; `research/lab2/common.py` | AUDIT fixes 1-6, tested | Signers from `solana.transactions` accounts; pump instruction discriminators; the sign of `b1.virt_ksol` | **P1.** Cheap, and a prerequisite for every B1/B3 rule (G05, G13, G14, G20) |
| G49 | RA-18 | [Coach] Protocol-constant tripwires: BOOST (17.5845 SOL, 29-30 slices), migration reserves (85 SOL / 206.9M), curve supply (793.1M), the sign of v, the Mayhem share, event lengths and a fee-page hash. On a breach, freeze promotions and re-validate every detector that depends on it | **P.** `validate.py` V7 checks BOOST presence. The FW4 monitors are planned, not running | `research/flow/validate.py` | AUDIT §3.2 and §3.7 (PumpSwap events grew 8 bytes on 10-03); RESULTS (the farm's timing drifted) | Daily constants from the backfill and the tape | **P2.** Cheap once D2 lands |
| G50 | RA-17, EX-18, DP-05 | [Coach] Post-mortem every closed trade within 24 h: paper, live, and shadow trades with a ≥ 50% drawdown. Record: the class (C3-C14, or ordinary bleed), with the earliest second it was knowable against our decision second; best and worst points (MFE/MAE), exit efficiency, gap slippage and stop regret; and an additive P&L split (selection, timing, exit, execution, residual) assigned to the member that controls each part. Thresholds fixed in advance open re-tests; they never change parameters automatically | **M** | Receipts in `ledger.py` | RESULTS: 9 labelled rug exits and 36 F4 swap windows | Receipts and shadow trades; CryptoHouse `raw.sql` over [entry − 30 min, exit + 10 min] for the graded coin only (AO-8) | **P1.** Start now on the 36 audit trades and all paper losses (D1, D5). That the parts sum to the trade's return is a unit test |
| G51 | DP-06, DP-11 | [Coach] Compare a suspected mistake only with trades in the same situation (speed class, age band, G1 class, market-cap tier, regime). A mistake becomes a candidate rule only with ≥ 10 instances, ≥ 5 operators, ≥ 3 days, and a matched gap whose CI excludes 0. Adoption needs PLAN §3.5's veto bar. A single loss never patches the bot, except for pipeline bugs (G52) | **M.** The method has been shown in scratch | — | `reentry_results.json`: re-entry after a stop looked -4.6 pp worse raw and -0.4 pp [-1.8, +1.1] matched. The apparent "mistake" was coin age | G50's components; situation features at decision time; operator keys | **P2.** After G50 |
| G52 | DP-12 | [Coach] An unusually bad loss (below the 1% quantile of the variant's replay distribution) starts with a bug hunt: decision fidelity, data freshness, price, fills against quotes, costs, lookahead. A pipeline fault is the only kind of mistake fixed after a single instance | **P.** The LEARNING auditors exist as constants in `learn/gate.py`: the placebo must lose (`PLACEBO_MAX_MEAN` -1%), decision fidelity ≥ 95%, the twin gap, and a `sim_hash` freeze. Phase-2 enforcement is pending | `learn/gate.py`, `learn/replay.py` (`sim_hash`) | So far, every material error the lab audits found was a pipeline error: the half fill, the SOL/USD lookahead, a constant v, the truncated AGENT window, NULL read as 0 | Scoreboard; tape `lag`, `evals` and `fills`; receipts | **P1.** Fault-injection tests are cheap (D0) |
| G53 | DP-01 | [Coach] Count experience as the effective number of independent, outcome-known episodes per situation cell: n_eff = n / (1 + (m̄ − 1) × ICC), by coin, operator and day. Do not call a member "experienced" in a cell below the n needed to detect a 5 pp effect | **M** | — | `dp_results`: coin ICC 0.13, so 16 random entries per coin are worth about 5.4 independent ones. F4's 12 TEST trades amount to about 1 operator | Cluster keys known at g (mint, creator, normalized ticker, c_ts, UTC day); cells at g + 140 s; outcomes after `label_ready_ts` | **P1** (D1 now, D2 next). It is the honest denominator for every report card |
| G54 | DP-17 | [Coach] Practise only on learnable cells: the sign holds across days and operators (I² < 50%, ≥ 75% of days with the same sign) and feedback is fast. Cells driven by one operator get vetoes only | **M** | — | RESULTS: the farm's 15-30-min crash share moved from 22-24% to 33% between splits | Day-level cell means. lab2 train has 4 days and CONFIRM's 15 days allow one run, so I² is weak for now (N1) | **P2** |
| G55 | DP-02 | [Coach] Grade decisions by the out-of-sample expected value of their (rule, cell), never by win rate or by one outcome | **P.** The page and the team room show no win rate (good), and the Coach scoreboard uses means and e-values. There is no per-cell EV grading | `pagestate.py`, `teamroom.py`, `learn/card.py` | `dp_results`: a zero-edge rule wins 79% of single trades; a +5% rule loses 14%; cells explain 4.7% of single-trade variance | Evidence with exit_ts < the decision time | **P1** (D1) |
| G56 | DP-03 | [Strategy/Coach] Seal a numeric plan in each entry receipt, and each shadow skip or veto, before the fill: rule hash, cell, thesis features, invalidation, horizon, size, assumed rug-aware worst loss, P(take-profit before stop), P(single-swap drop ≥ 50%), and expected net return with its CI | **P.** Decision receipts already carry the reason, metrics, rule ids, quote, sizing and verdict. Forecasts, invalidation and worst loss are missing | Engine `_decide` inputs; `models.Decision` | `brier_results`: a trivial cell forecast of stop-outs reached Brier skill 0.19 [0.15, 0.23] from census TRAIN to VAL, but was miscalibrated (forecast 0.16, observed 0.29 in one bin) | Cell tables from evidence with exit_ts < the decision time (AO-8) | **P1.** Cheap code (D0), and it turns every later post-mortem into a plan-versus-actual check |
| G57 | DP-09, DP-16 | [Coach] Practise on a simulator with sealed exams: search on train, VAL from a shortlist written in advance, one TEST pass, every configuration logged and deflated (DSR, CSCV/PBO). Every claim that a **member** is skilled (turning Jev on, trusting a Cocoon forecast, a new exit) spends α like a strategy does | **P.** lab2 has guarded splits, shortlists, `trials.json` and the deflated Sharpe ratio. LEARNING has the α ledger (`PAPER_ALPHA` 0.005, 4 registrations per ISO week). Missing: CSCV/PBO and α-spending for member claims | `research/lab2/common.py` (`GUARD_ENV`, `write_shortlist`, `deflated_sharpe`); `learn/gate.py` | RESULTS: F4 made +14% in practice, -5.4% on the exam and -17.7% on real swaps | `trials.json`; split guards | **P1.** See N1 |
| G58 | DP-04, R14 | [Coach] One report card per member against a no-skill baseline, with an anytime-valid CI. Crawler: G60. Cocoon: pass-minus-reject shadow return against a random veto at the same rate (and per rule via G08). Strategy: against a matched random entry. Radar: G21. Jev: G47. Broker: G59. Risk: limit breaches, gap ratio, rug-rate calibration, realistic drawdowns. Exits: G36. Coach: the placebo loses, a planted edge is found, false promotions stay in bound. A card says "skilled" only when its lower bound beats the baseline | **P** for DP-04, **M** for R14. The team room shows activity status and counts only. The Coach card shows the placebo and the top variants | `teamroom.py`, `pagestate.py`, `learn/card.py` | LEARNING §9 | The same coins and the same as-of data per member; outcomes after `label_ready_ts` | **P1.** This is the owner's "experienced team" made measurable. Strategy and gate cards can run on D1 and D2 now; Crawler, Jev and Broker need forward logs |
| G59 | DP-13 | [Broker] Score each fill by its implementation shortfall against the mid at decision time: delay, impact plus fees, and the opportunity cost of missed signals. Compare paper with its replay twin, and later live with paper | **P.** Fills record the quote's output against the expected amount, and the tape's `fills` stream logs impact. There is no decomposition | Ledger fills; `learn/` `fills` stream | RESULTS A1 and A3: entry drift averaged +0.2% at 2 s (at most 0.9%). Rug stops are structural, a Risk and Cocoon problem, not an execution one | Decision time, quote and fill; mid from `b1` `x0`, `y0` and v (non-factory) | **P2** |
| G60 | DP-14 | [Crawler] Coverage: recall of tradeable graduates within 5, 15 and 60 min against CryptoHouse CompleteEvents, the median lag, and the reason for each miss. Check that the shadow returns of missed coins match those of seen ones | **M.** The engine watches at most 15 coins and fetches candles for about 3 a minute, out of about 1,200 graduates a day. The recorder's `universe` stream logs `first_seen` (phase 1) | `WATCHLIST_MAX` 15; `learn/recorder.py` | none | One forward week of ledger and tape, joined to CryptoHouse graduates for the same week (D5, plus backfill catch-up) | **P2** |
| G61 | DP-15 | [Cocoon/Radar] State probabilities. Cocoon: P(single-swap drop ≥ 50% or airdrop dump during the hold). Radar: P(drop ≥ 30% in 5 min). Score them by Brier and log loss, and recalibrate weekly on past weeks only. Hard fails stay fail-closed | **M.** Pass/fail only | `cocoon.check`, `radar.scan` | The G56 demo | Features as of the check (tape `safety`; B1 and B3 later); labels after t + hold + 10 min | **P2** |
| G62 | DP-10 | [Coach] Give part of the 4 weekly registrations to the weakest learnable cell (ranked by G50's attribution), judged forward only. Keep this only if it beats a uniform allocation | **M.** The nightly search is phase 3 | `learn/gate.py` `REG_PER_ISO_WEEK` | Census: instant coins 0-30 min after graduation lost -15.7% per random entry, stopped out 43% of the time (a cell the bot never trades) | Per-cell attribution; the trial counter | **P3** |

---

## Status count (per original rule, 91)

| Status | Count | IDs |
|---|---:|---|
| Already implemented | 6 | PE-04 (unvalidated), EX-08 (untested folklore), EX-09 and R15 and DP-07 (correctly absent), EX-20 |
| Partial | 33 | RA-01, RA-03, RA-09, RA-11, RA-12, RA-15, RA-16, RA-18, PE-05, PE-09, PE-10, PE-12, PE-15, PE-16, PE-17, R02, R05, R06, R07, R08, R10, R12, R13, R16, EX-01, EX-06, DP-02, DP-03, DP-04, DP-09, DP-12, DP-13, DP-16 |
| Missing | 52 | all the others |

- **Contradicted by our data.** No proposed rule is itself contradicted. What our data contradicts is folklore that
  is already inside the bot (N4), plus the vendor-band version of PE-01, address-based serial-launcher checks
  (PE-05 and RA-12), GMGN's trade-count rule (PE-07), and "fast fill = strong" for instant coins (PE-11).
- **Untestable historically, so forward only:** PE-04 and PE-17, and every RugCheck, Jupiter-organic or holder-list
  field (AO-7).
- **Untestable with what we have:** dated KOL labels (PE-09).
- **One caution.** Inside the bot's window, the census day shows instant coins no worse than slow ones (N5). RA-03's
  "skip entirely" must therefore be measured on the bot's own host (G1.dip) before it is called valuable there.

## Work order

**P0: now, no new data (about a day of engineering in total)**

1. **G22 (EX-01).**
   - Make the stop fill realistic in `backtest.py` and the Coach shadow book: next bar's min(open, low).
   - Set lab2 `exit_delay_bars` to 1 by default.
   - Calibrate on the 36 audit swap windows.
   - Label every earlier "half-fill" number as optimistic.
2. **G12 (PE-10, RA-09).** Map Jupiter `graduatedAt`, and require ≥ 30 min since **graduation**, not creation.
3. **G01 (RA-02) with N3.** Skip Mayhem coins (supply > 1e9, `mayhem_state`). Trade only pump.fun SOL-quoted
   graduates until anything else is validated.
4. **G33 (EX-14).** When the price is blind, use the sell quote as the price; two failed quotes force an exit.
5. **G23 (R01).** Use L_max = 0.95 in every risk calculation, and show "per-rug loss ≈ 19% of equity" on the Risk
   card.
6. **G39 (R16).** Rewrite `docs/GOING_LIVE.md` §0 around the stage-2 gate (≥ 150 paper trades, ≥ 14 days, E ≥ 1/α),
   not 20-30 trades.

**P1: next 1-3 days (D1, or D2 once lab2 train lands; about 300 queries)**

7. **G48.** Build the signer-checked pooled-account list (about 2 queries) before any B1/B3 rule.
8. **G04.** Run G1 on lab2 train with both hosts. Add RA-03's ticker variant as a counted, dated amendment, and the
   G14 bar proxy (`airdrop_seen`).
9. **Exit grid on the B2 worst-fill engine:** G24, G28, G26, G36. Include placebo exits and a ≤ 2-cell shortlist for
   VAL.
10. **G15 and G16.** Dust and organic-buyer proxies on D2, plus the live proxy (`volume_m5 / txns_m5`). They replace
    the paintable `volume_up` and `ratio_m5` inputs only if they pass.
11. **Jev.**
    - **G09:** a neutral prompt now, then the P1 orders pull.
    - **G47:** a 400-situation masked audit (about $6).
12. **Coach basics:**
    - G50: post-mortems of the 36 audit trades, the 9 rugs and paper losses;
    - G53: n_eff;
    - G55: cell-EV grading;
    - G56: plan fields in receipts;
    - G58: report cards, where "no measurable skill yet" is the honest default;
    - G52: fault-injection tests;
    - G57: CSCV/PBO.
13. **G08.** Per-rule veto grading on the tape.
14. **Risk and Broker:**
    - G40: reclaim rent (+1.1 pp per $20 round trip, certain);
    - G41: one position per ticker family;
    - G38: budgets on Σ ticket × L_max.
15. **G19.** Measure our own p50/p90 decision-to-fill latency.

**P2: blocked on B1/B3 or new queries**

- **G13, S1** (PE-01, PE-03, RA-13): the first thing to run when P4 lands. Add the bundle-share quintiles as RA-13's
  control.
- G14 (transfer and orphan share), G20 and G21 (radar provenance and lead time), G05, G06, G23 (crash capacity), G25,
  G19 (Δ(D)), G59, G60, G61, G49, G51, G54, and the rest of the risk items.

**P3: park, or run only as counted descriptives**

- G03, G10, G11, G17, G18, G34, G35, G37, G42, G43, G46, G62.

## What "highly experienced" will mean on the dashboard (measurable, not hype)

1. **Situations studied.**
   - **Today:** one census day (598 coins in TRAIN and VAL, coin ICC 0.13) and 36 swap-replayed trades.
   - **After D2/D3:** about 6.8 more days.
   - Show n_eff per cell (G53), not raw rep counts.
2. **Rules that survived unseen coins.**
   - **Today:** 0 entry rules. The lab's 2,575 configurations produced no winner.
   - **Pending:** G1 (gate), S1 (entry) and the exit grid, each counted in `trials.json`.
3. **Graded practice that changes behaviour:**
   - a post-mortem for every trade (G50), compared with its sealed plan (G56);
   - a mistake library with matched evidence thresholds (G51);
   - per-rule veto grading (G08).
4. **Honest skill scores.**
   - One card per member against a dumb baseline (G58), with "no measurable skill yet" until the lower bound clears
     the baseline.
   - A skill claim spends error budget (G57), so practising forever cannot promote a lucky member.
