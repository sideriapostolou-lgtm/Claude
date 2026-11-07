# Handoff addendum: Claude -> Codex (ChatGPT), Friday Oct 16, 2026, written ~10:00 AM PT

This adds to the complete handoff file the owner gave you on Oct 15 (`HANDOFF_FOR_CHATGPT_2026-10-15.txt`:
Part 1 business and code, Part 2 connections and everything else, Part 3 the two shipping skills). Read that
first. This file covers everything that happened after it, the operating facts you need today, and the thing the
owner is asking for most: **a plain map of how the auto-trading business actually runs, stage by stage, so the town
can show the real workflow instead of decoration.** The owner's words today: "that town should be running exactly
how my whole auto trading business is actually happening, it should explain the whole workflow."

Times are Pacific (PT) with UTC in brackets where it matters. Names only for secrets.

---

## 1. What happened since the Oct 15 file (newest last)

### 1.1 Your own merges (deploy branch `claude/nightcrawler-memecoin-bot-Gwnb1S`)
PR #61 learner input chronology; #62 Kalshi input causes; #63 Kalshi live correction; #64 Kalshi probability
learning (observe only, in the arena child); #65 preserve recovered feeds after REST failures; #66 preserve
probability epochs and financial stops; #67 practice checkpoint report; #68 twin comparison; #69 protect completed
profitable pairs from renewed directional exposure; #70 own-order queue diagnostics; #71 reuse Kalshi settlement
membership (perf, touches real money); **#72 shard cash and refusal backoff** (the fix that mattered today);
**#73 town team workflow** (futuristic workstations, `worldtycoon_workflow.py`, `TYCOON_WORKFLOW`).

### 1.2 Thursday evening to Friday morning: the Kalshi "insufficient balance" day
- Kalshi stopped the desk Thursday at the $6 daily stop (7:00 AM PT settlement, one Up contract, -$0.56).
- You offered the owner a one-time fresh $6 daily allowance through `SPEEDDESK_KALSHI_DAY_RESET_TOKEN`; the owner
  accepted and had Claude apply it. **6:21 AM PT Friday**: fresh token value set, redeploy of the last good build;
  reset receipt "fresh daily budget from now until 00:00 UTC; caps and lifetime stop unchanged", counted from -$5.13.
- **6:32 to 6:38 AM**: every real order (4 contracts, bids 14 to 26 cents) came back HTTP 400 `insufficient_balance`
  while the balance read said $25.12. The bot retried every 1.5 to 3 seconds (about 40 refusals). Zero fills.
- **6:38 AM**: Claude set `SPEEDDESK_KALSHI_MODE=paper` to stop the hammering (code may turn real money off).
- **Root cause (confirmed from Kalshi's public market data and docs)**: Kalshi now runs separate **exchange
  indexes** ("shards"). The live window `KXBTC15M-26OCT160945-45` carries `exchange_index: 2` (Crypto and
  Commodities). The owner's cash sat on index 0. Collateral checks run on the market's shard. Orders placed in the
  Kalshi app or website auto-transfer money between shards; **API orders do not**. `GET /portfolio/balance` without
  `exchange_index` totals all shards, so both sides were "right". New Bitcoin events started landing on index 2
  after Thursday's fills, which is why it worked through Thursday and failed Friday.
- **7:20 AM**: your PR #72 merged and deployed: per-shard cash check from `GET /portfolio/subaccounts/balances`,
  persistent funding-refusal cooldown; status gained `shard_funding` (balances per index, refusal) and
  `create_funding_cooldown`.
- **8:03 AM**: owner had Claude set `SPEEDDESK_KALSHI_MODE=live`; came up on PR #72. Status showed index 0 $25.00,
  index 1 $0.00, index 2 $0.12; the bot correctly placed nothing (no storm).
- The owner found Kalshi's page for this on the website: **kalshi.com/account/exchange-indexes**, titled
  "Advance shard settings". It lists Exchange 0 (Default), 1 (Combos), 2 (Crypto & Commodities), 3 (Tennis,
  Baseball, Basketball), with a **Min Requirement** column per exchange and a toggle "Disable balance management
  (Advanced Usage Only)" which stays OFF. Setting Min Requirement on Exchange 2 makes Kalshi keep that much there.
  The owner set it and also deposited $25 more.
- **By 9:50 AM**: index 2 held **$52.68**, index 0 and 1 $0.00. The desk had been trading since about 8:15 AM:
  101 fills over 30 windows today, day P&L since the reset **-$3.42**, settled UTC-day -$10.00, fees $0.36, status
  reasons cycling through "Window has not started" and "pair_protected". The bot has no live profit record yet.
- **9:53 AM**: the owner, in their own words: "this new updated bot seems profitable so before everything double
  our size u have full approval double it." Claude set `SPEEDDESK_KALSHI_WINDOW_USD=20`, `_OPEN_USD=40`,
  `_DAY_STOP_USD=12` (the ceilings the owner pre-authorized on Oct 13 "when it's winning"). Clip stays 5 contracts
  per order (owner's standing rule "keep 5 at every rung"). The lifetime stop stays $10: it is a code ceiling
  (`hi=10`), so raising it needs a code change plus the owner's explicit word. Claude told the owner the bot is
  down today, not up, and that the doubling is their call; it stands unless they say otherwise.

### 1.3 Documentation already in the repo for you
`docs/COORDINATION.md` inbox entries from Claude on Oct 15 (Part 2 pointer) and Oct 16 (13:45, 13:55, 15:15 UTC:
the reject storm, the shard root cause with the exact Kalshi endpoints, and the request that the bot fund its own
shard). `docs/WORKLOG.md` has the matching entries. Your own entries cover the rest of the day.

## 2. Operating facts you need today

- **Railway bot service** (project `nightcrawler`, service `bot`, us-east4): variables by name only. Changed today:
  `SPEEDDESK_KALSHI_DAY_RESET_TOKEN` (spent; a future reset needs a new value), `SPEEDDESK_KALSHI_MODE` (live),
  `SPEEDDESK_KALSHI_WINDOW_USD` 20, `SPEEDDESK_KALSHI_OPEN_USD` 40, `SPEEDDESK_KALSHI_DAY_STOP_USD` 12. Unchanged:
  `SPEEDDESK_KALSHI_TOTAL_STOP_USD` 10 (default), clip 5 (default), `SPEEDDESK_TAKE_EDGE` 1.0 (no takes),
  `SPEEDDESK_KALSHI_PULL`, Polymarket desk variables, `MARCO_REAL`.
- A variable change restarts the bot (Railway redeploys the running image). A docs-only push does not rebuild
  (watch patterns: `src/**`, `pyproject.toml`, `Dockerfile`, `railway.json`, `README.md`).
- Safe minutes for any restart or code deploy: :02 to :10, :17 to :25, :32 to :40, :47 to :55. Never within 2 minutes
  of :00/:15/:30/:45 and never in the last 4 minutes of a window.
- **Kalshi shards**: the bot sends `exchange_index: -1` (auto-route by ticker). Market objects carry
  `exchange_index`. Per-shard cash: `GET /portfolio/subaccounts/balances`. To move money by API:
  `POST /portfolio/intra_exchange_instance_transfer` (`source`/`destination` `event_contract`,
  `source_exchange_shard`, `destination_exchange_shard`, `amount` in centicents, optional `client_transfer_id`) or
  `POST /portfolio/target_balance_allocation` (`allocations` summing to 100 percent, `resting_margin_reservation`
  `sum`/`max`/`none`; Kalshi rebalances every 10 s). The owner's Min Requirement on the website does this for now;
  the bot should still be able to do it itself (Claude's inbox request, 15:15 UTC).
- **Recorder** (`kalshi-recorder`, us-west2): your 15:26 UTC note says memory nearly full; volume fills about
  1 GB/day; grow it in the Railway dashboard before Oct 20; the 48-hour report was due Thursday 3:45 PM PT.
- **Claude Routines**: only the weekly "Marco's loves watcher" is enabled (Tue to Fri 7:53 AM PT; pushes data and
  redeploys the bot when there is a new episode). Nothing else automatic runs outside the bot.
- **Claude's role from here**: the owner uses Claude only for hard problems on request. You own the repo, the
  town, operations and the daily reporting. Post in `docs/COORDINATION.md`; the owner reads WORKLOG summaries.

## 3. The workflow map: how the business actually runs (what the town must show)

The owner wants the town to be a truthful live diagram of this. Every stage below has live numbers in `/api/page`
today (or should). Show REAL and PRACTICE as separate lanes, show which stage is blocked and the exact reason
string the bot reports, and never animate something that did not happen.

### 3.1 The money lane (Kalshi, real money, the only desk that earns or loses right now)

1. **Watch the market.** Two feeds: Coinbase Bitcoin trades (primary, Advanced Trade failover) and Kalshi's order
   book over WebSocket for the current 15-minute window (`KXBTC15M-...`). Numbers: Bitcoin price, tick age in ms,
   feed gaps. Town role: Voss at the observatory.
2. **Price the window.** Fair probability that Bitcoin ends above the strike = Phi(ln(S/K) / (sigma sqrt(t))),
   sigma from the recent tape, t = seconds to close. Numbers: fair, Kalshi best bid/ask, edge after fees.
3. **Place maker bids.** Rest a bid at floor(fair - 3 cents), post-only, up to 5 contracts per order (clip), within
   the window budget. Pull the bid if fair moves 1 cent within 5 seconds (the practice twin never pulls: it is
   the control). Numbers: resting orders, pulls today, decision-to-ack ms. Town role: Jet, the order desk.
4. **Get filled, then balance.** After a fill, bid the other side so a pair costs at most 99 cents (a locked pair
   pays $1 at settlement); from 240 s before close the bot may pay up to 97 cents to complete a pair; completed
   profitable pairs are protected from new directional exposure (PR #69). Numbers: fills, pairs, locked value,
   directional exposure, "pair_protected" reason.
5. **Settle.** Kalshi settles on the 60-second BRTI average at the close; P&L and fees are booked; every order,
   fill and receipt is hash-chained. Numbers: settled windows, P&L today and lifetime, fees. Town role: Mote,
   the records desk.
6. **Guard.** Before every order: window cap ($20), open cap ($40), day stop ($12 since 9:53 AM PT, counted from
   the owner's reset), lifetime stop ($10, latched for good), reconciliation (orders and positions match Kalshi,
   else an integrity stop), **shard cash** (the market's exchange index must hold the money), refusal cooldowns,
   safe-minute rules for deploys. Numbers: caps, room left before each stop, latch states, shard balances,
   cooldowns. Town role: Rook, the safeguards desk. This is the stage that blocked trading today.
7. **Earn size.** The ladder: rung 0 is the owner's floor; after 96+ windows with a statistically real gain,
   house money, no stop for 24 h and cash, the next rung adds $5 a window (open 2x, day stop 60 percent); clip
   stays 5; giveback demotes. Code ceiling $20 a window, which today's doubling already reaches. Numbers: rung,
   windows counted, gain needed vs gain so far, promotion blockers.
8. **Learn.** The practice twin (same bids, no pulls) is the A/B control; the arena runs 12 practice residents in
   a separate process; your observe-only probability learner reads the arena feed; the recorder on its own
   service captures Kalshi books for the Family A protocol (TRAIN from Oct 20). None of this moves real money.
   Numbers: twin vs real P&L, arena leaderboard, learner coverage, recorder capture hours.
9. **Report.** A status line every minute (mode, reason, cash, caps, stops, shard balances), `/api/page` for the
   town, `docs/WORKLOG.md` entries from you, inbox in `docs/COORDINATION.md`, the weekly Routine's push.
10. **Owner controls.** Railway variables (mode, live confirm, caps, one-time tokens for day reset, integrity reset
    and resume), the Kalshi website page for shard minimums, deposits. Only the owner turns real money on or up.

### 3.2 The second money lane (Polymarket US, real money, small)
Rule 2026-10-10a: no sports except Marco's loves (`MARCO_REAL=1`), one bet per game or question, stops count money
at risk; caps 10 contracts, $30 a day, $40 total. Flow: candidate from a desk -> rule check -> order -> fill
reconcile -> settlement -> daily/total stop. Show it as its own lane with its own cash and stops, never mixed
into Kalshi's numbers.

### 3.3 The practice lanes (no money)
Kalshi practice twin, Kalshi arena (12 residents), coins desk (ETH/SOL/XRP/DOGE), trend desk, Marco's desk and NHL
loves, the public-wallet "no-lose" watcher, the weather-markets observer, the memecoin night shift. Each is a
pipeline of the same shape (watch, decide, pretend-trade, score) and should be shown as practice, with its
scorecard, not as money.

### 3.4 The people and the machines
Owner (decisions, money, phone); Codex (you: repo, town, ops, reports); Claude (hard problems on request); the
Marco Routine (weekly, automatic); Railway (bot service, recorder service); Kalshi and Polymarket US (venues);
Coinbase (price feed). The town can show this as the org chart it really is.

### 3.5 Truth rules for the town (the owner's standard)
- Real vs practice never share a number, a color or a celebration.
- Every stage shows its live blocker string when blocked ("Daily loss stop", "Insufficient shard balance",
  "pair_protected", "Window has not started", "Kalshi account data stale") and goes quiet when idle.
- Money shown is money read from the venue, with its age; cash is not profit; today means since 12:00 AM Pacific
  except the Kalshi day stop, which counts from the owner's reset when one was applied.
- Nothing animates from practice events, repeated old chatter or elapsed time.
- The owner reads it on a phone; one screen, big numbers, plain words.

## 4. Decisions the owner still owns (put these to them plainly, one at a time)
- Lifetime stop $10: raise it (code change) or leave it. Today's doubling did not touch it.
- Clip 5 per order: double to 10 or keep the standing rule.
- Recorder volume before Oct 20; Dec 1 move off `railway.json`.
- The weekly Marco Routine: keep, move, or disable (it redeploys the bot at an uncontrolled minute).
- Whether "profitable" is true: as of 9:50 AM PT today the Kalshi desk is -$10.00 on the UTC day and -$3.42 since
  the reset; the twin and the scorecards are the evidence, not the feeling.

## 5. Rules of the road (unchanged)
Only the owner turns real money on or up, by naming the numbers; code may only turn it off or down. No keys,
tokens, phone numbers or personal e-mails in the repo (it is public). Safe minutes for restarts. Secret-scan every
diff. One WORKLOG entry per working session. Talk to the owner in Pacific time, 12-hour clock, plain words.
