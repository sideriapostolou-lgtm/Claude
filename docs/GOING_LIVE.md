# Going live with $100 of real money

This page is the exact path from paper trading to real money. It's written for a phone:
the Phantom app, the Coinbase app, and the Railway website.

> **Before anything else.** Live mode can lose every dollar you put in, quickly. Memecoins
> rug, pools empty out, prices gap past stop-losses, and fees eat 1-3 % of every position on
> every round trip. The viral posts this project was built to check did not hold up
> ([FACTCHECK.md](FACTCHECK.md)). On the very nights those posts showed off, the bot's own
> default strategy lost money ([backtests/README.md](backtests/README.md)). Only continue
> with money you are fully prepared to lose. Nothing here is financial or tax advice.

---

## Fund the bot from Phantom (no keys needed)

The easy way, and the safer one: the bot makes **its own wallet** and keeps the key to itself.
Nobody ever sees, copies or pastes a private key: not you, not an AI assistant, not a chat.
You only ever copy a public address, which is safe to share.

**Set it up once (Railway, in paper mode):**

1. **Turn on the volume's backups first.** In Railway open the volume (the one at `/data`),
   **Backups**, and choose a daily schedule (if your plan offers it). **The volume is the
   wallet**: the bot's key exists only on it and nobody has a copy. A deleted or broken volume
   without a backup loses the SOL in the wallet for good.
2. Railway, your nightcrawler service, **Variables**, **New Variable**: name `BOT_WALLET_MODE`,
   value `generated`. If a `BOT_WALLET_SECRET` variable exists, delete it (the bot refuses to
   start with both). The volume must be attached at `/data` with `DATA_DIR=/data`
   ([RAILWAY.md](RAILWAY.md), step 3): the bot refuses to make a wallet anywhere a redeploy
   would wipe it, and it never makes a second one next to a wallet already on the volume.
   Never change `DATA_DIR` afterwards. Press **Deploy**.
3. Open your dashboard link. The **Bot wallet** card shows the bot's address and a
   **Copy address** button.

**Put money in (Phantom only):**

4. Tap **Copy address** on the dashboard.
5. In **Phantom**, tap **Send**, choose **SOL**, paste the address, type the amount and send.
   Send a small test first (say $5, at least 0.01 SOL) and wait until the card shows it ("In it
   now: ... SOL", checked about every 10 minutes), then send the rest. Keep it under
   `MAX_WALLET_USD` ($150). Send from the Phantom account you want the money back in: the bot
   only ever sends everything back to an address that sent it SOL.

That is step 3 of the dashboard's "Ready for real money?" checklist. Skip sections 1-3 below.

**Take everything back:**

6. In Phantom, tap **Receive**, choose **Solana** and copy **your** address (the account you
   sent the SOL from).
7. Railway **Variables**: `WITHDRAW_TO` = paste it. While it is set the bot buys nothing, sells
   every coin it holds, closes the empty coin accounts it opened (each gives back about 0.002
   SOL), then sends **all** its SOL to that address minus the network fee (0.000005 SOL), waits
   until the network confirms it and records it in the receipts.
   - In **paper** mode it only shows what it *would* send (a yellow "Practice mode" banner).
     To really send it, also set **all three** of `TRADING_MODE=live`,
     `LIVE_CONFIRM=I_ACCEPT_REAL_MONEY_RISK` and `DASHBOARD_TOKEN` (a password of at least 24
     random characters; live mode refuses to start without one, see [RAILWAY.md](RAILWAY.md)
     step 4). With `WITHDRAW_TO` set it still buys nothing.
   - Press **Deploy**. A red banner shows the **full** address it will send to and waits 10
     minutes before sending anything: compare every character with Phantom's Receive screen.
     Wrong? Delete `WITHDRAW_TO` and **Deploy** within those 10 minutes: nothing is sent.
   - Then "Withdrawal done: ... SOL went to ...". Check Phantom.
8. **Always do this afterwards:** delete `WITHDRAW_TO` and `LIVE_CONFIRM`, set
   `TRADING_MODE=paper`, then **Deploy**. Until the bot has run in paper mode once, it buys
   nothing with real money after a withdrawal, so a later deposit is never traded by surprise.
   Going live again later is the normal checklist below.

Good to know:

- **Never delete the Railway volume or the service while SOL is in the bot wallet**: the key
  lives only on that volume (keep its backups on). Withdraw first. The bot refuses to start
  rather than replace or re-make a wallet it already had.
- `WITHDRAW_TO` must be an existing wallet that sent the bot at least 0.01 SOL in one go. A
  mistyped, cut-off or look-alike address is refused and the banner says why: Solana addresses
  have no typo check, so this is what keeps a typo from sending everything to nobody. Sent from
  that wallet long ago? Send 0.01 SOL again from it and wait 10 minutes.
- A coin nobody will buy cannot hold your SOL back: after 30 minutes the bot sends all but a
  small reserve (about 0.006 SOL, enough to pay for selling what is left) and keeps trying to
  sell; once nothing is left, the reserve follows. The banner says how many coins are left.
- Less than about 0.0009 SOL cannot be sent (a Solana rule); the banner then says "Nothing to
  withdraw".
- `WITHDRAW_TO` must be a plain wallet address. The bot refuses its own address, token
  accounts and program addresses, and says so on the page.

---

## 0. The checklist: all of these must be true first

- [ ] **Paper mode ran on Railway for at least 1-2 weeks,** with the dashboard's heartbeat
      green most of the time.
- [ ] **The paper trades proved an edge: the Coach's stage 2 passed** (the dashboard's checklist
      ticks step 2 only then). That takes **at least 150 paper trades over at least 14 days**, and
      an anytime-valid lower bound on their average result after every cost that is **above 0**
      (an e-value of at least 200 on fresh paper fills for the first attempt, more for later ones;
      [LEARNING.md](LEARNING.md) §5.4). "Positive over a few dozen trades" is not proof: memecoin
      results swing so much that a strategy with no edge at all is positive over 30 trades about
      half the time, while this gate lets one through well under 1 % of the time. Judge the bot's
      own result **in SOL** (`nightcrawler report`,
      "Closed trades: ... SOL", or the dashboard's "Since start" tile), never by the big dollar
      number: SOL's own price moves far more than the bot's results. If stage 2 has not passed,
      stop here: a losing paper bot will be a losing live bot. (Paper fills already assume 1 %
      worse than the quote, `PAPER_SLIPPAGE_BPS=100`, because real swaps land below the quote.)
- [ ] **The stake is at most a quarter of Kelly at that lower bound** (computed on a return
      distribution that includes rugs), never the edge's point estimate. At $100 that means the
      minimum ticket: set `POSITION_PCT=0.05` ($5 tickets) for at least the first 50 live trades.
      Every ticket is also sized as if a rug could take 95 % of it, so one day can lose at most
      `DAILY_RISK_BUDGET_PCT` (15 %) of its starting money even if every open coin rugs.
- [ ] **Receipts verify.** The dashboard shows "verified", or `nightcrawler receipts verify`
      says OK.
- [ ] **The audit is clean.** `nightcrawler report` says `Result: OK` (exit code 0).
- [ ] **`DASHBOARD_TOKEN` is set** to a long random password (at least 24 characters, not the
      example from RAILWAY.md), so strangers can't look at your bot. Live mode refuses to start
      without one, or with a short or guessable one (unless the dashboard only listens on `127.0.0.1`).
- [ ] **The volume is attached** at `/data`, with `DATA_DIR=/data` and `RAILWAY_RUN_UID=0`
      (see [RAILWAY.md](RAILWAY.md)). Without it, the bot forgets its positions on every redeploy.
- [ ] **`RAILWAY_DEPLOYMENT_DRAINING_SECONDS=30` is set** (see [RAILWAY.md](RAILWAY.md)). Railway's
      default gives a stopping bot 0 seconds, so a redeploy could cut a swap in half.
- [ ] **You know how to stop it** (section 6) and have tried `KILL_SWITCH=stop` once in paper mode.
- [ ] **You accept** that edges on memecoins, if any, fade within weeks, and that the bot can
      lose everything you deposit.
- [ ] Optional but recommended: a free [Helius](https://www.helius.dev/) RPC key in
      `SOLANA_RPC_URL`. The public Solana RPC is slow and rate-limited.

---

## 1. Create a NEW account in Phantom, just for the bot

*Sections 1-3 are the older way, with a private key you paste yourself (`BOT_WALLET_SECRET`).
With `BOT_WALLET_MODE=generated` ([above](#fund-the-bot-from-phantom-no-keys-needed)) skip them.*

Never use your main wallet. The bot needs the private key, and a key that sits in a server
setting is only as safe as that server. A separate account means the worst case is losing the
~$100 in it, not your savings.

1. Open the **Phantom** app. Tap your account name at the top, then **Add / Connect Wallet**,
   then **Create New Account**.
2. Name it something obvious, like **nightcrawler bot**.
3. Make sure that new account is selected. Tap the address at the top to copy it. It's a
   long string of letters and numbers, and it's public, so it's safe to share.

Phantom accounts you create this way all come from your same recovery phrase. That's fine.
Only *this* account's private key ever goes to Railway.

## 2. Buy about $100 of SOL on Coinbase and send it to that address

1. In **Coinbase**, buy about **$100 of SOL** (Solana).
2. Tap **Send**, choose **SOL**, and paste the bot account's address from step 1.
3. When asked for the network, pick **Solana**.
4. If you've never sent crypto before, send a small test amount first (say $5) and check it
   arrives in Phantom before you send the rest.
5. Wait until Phantom shows the SOL in the **nightcrawler bot** account (usually under a minute).

Keep the total under **`MAX_WALLET_USD`** (default **$150**). If the wallet holds more than
that, the bot refuses to open new positions. That's a tripwire against pasting the wrong
key (your main wallet) by mistake.

The bot always keeps **0.02 SOL** (about $2) unspent for fees and token-account deposits,
so roughly $98 is tradable.

## 3. Copy the bot account's private key into Railway

1. In Phantom: **Settings**, then **Manage Accounts**, then pick **nightcrawler bot**, then
   **Show Private Key**. Enter your password and copy the key.
2. In Railway, open your nightcrawler service, go to **Variables**, then **New Variable**:
   - name: `BOT_WALLET_SECRET`
   - value: paste the key
3. **Don't paste the key anywhere else.** Not in a chat, not in an AI assistant, not in a
   "setup guide", not in a screenshot. Anyone who has it can empty the account.

The bot never prints, logs or displays this key, and it never sends it anywhere. Jupiter
gets only signed transactions, never the key itself.

Deploy (still in paper mode). Within about 10 minutes the dashboard's "Ready for real money?"
card shows step 3 ticked, with the start of the wallet's address and its SOL: the bot reads that
balance every 10 minutes, so you can check the address matches the one in Phantom.

## 4. Switch to live mode

**First, check the dashboard.** Its "Ready for real money?" card should say **"Ready to switch
on"**: steps 1-5 ticked, all of them doable in paper mode (sections 1-3 above are its step 3,
and `KEYS_ROTATED_ON`, a date like `2026-10-09`, is its step 4). If it doesn't, the unticked step
says what is missing. It never says Ready while a banner is up (kill switch, halt, a silent bot).

**Then, close the paper positions.** Set `KILL_SWITCH=sell_all` (still in paper mode), deploy,
and wait until the dashboard shows no open positions. A live bot never sells, counts or values
paper positions (they are not in your wallet); it notes them in the receipts and leaves them
alone, so they would just sit there.

Then, in the same **Variables** tab, set:

| Variable | Value |
|---|---|
| `TRADING_MODE` | `live` |
| `LIVE_CONFIRM` | `I_ACCEPT_REAL_MONEY_RISK` (exactly, capital letters) |
| `KILL_SWITCH` | `off` (it was `sell_all` for the paper close-out) |
| `POSITION_PCT` | `0.05`: $5 tickets, a quarter of Kelly at most (section 0), for at least the first 50 live trades |
| `MAX_WALLET_USD` | `150` (leave the default unless you know why) |
| `SOLANA_RPC_URL` | your Helius URL (optional, recommended) |

Then press **Deploy** (Railway shows your variable edits as staged changes until you deploy).

If anything is missing or wrong, the bot **refuses to start** and the logs say why:
the confirmation phrase, the wallet key, or the `live` extra (the Docker image already
includes it). That's on purpose.

What changes in live mode: the bot asks Jupiter Ultra for a quote **for your wallet**, signs
the returned transaction, checks it by simulating it on Solana, then sends it through Jupiter
(which handles priority fees and MEV protection). It records the **actual** amounts it got.
Everything else, including the filters, the strategy, the limits and the receipts, is
identical to paper mode.

Your paper history stays in the same ledger. Risk limits, the dashboard and `nightcrawler report`
only count live equity, positions and trades from now on, and the switch is noted in the
receipts. Before its first live trade the bot records the wallet's starting SOL, so the audit
can compare every later balance with the books.

## 5. Watch it: the dashboard and Phantom

- **The dashboard** (your Railway link with `?token=...`) now shows a red **LIVE** tag and
  "Real money". Check that no red banner shows, the team rows, open positions and recent trades.
  Before you switched (step 4), its "Ready for real money?" card should have said "Ready to
  switch on" (steps 1-5 ticked); now it says "Ready — real money is on".
- **Phantom** (the nightcrawler bot account) shows the same swaps as the dashboard. Every
  swap shows up in Phantom's activity tab.
- `nightcrawler report` (if you can run commands) compares the books with the real wallet
  and flags any difference.

Expect long stretches with **no trades**. The filters are strict on purpose.

**If something looks off,** for example a swap in Phantom that's not on the dashboard, a red
error, an "outcome is unknown" or a "wallet doesn't match" banner: set `KILL_SWITCH=stop`
first and investigate after. When a live swap's outcome is unknown (say the network dropped
mid-send, or the bot was restarted in the middle of one), the bot stops all new buys by itself,
waits 90 seconds, reads the wallet, and records what actually happened in the receipts. It
never sends a new swap for it. Every 5 minutes it also compares the wallet's coins with its
books; if they differ (a coin sold by hand in Phantom, say), it stops buying until they match
again.

**If it says "Halted":** equity fell 50 % from its peak. Take that seriously before
resuming. To resume anyway, set `RESET_HALT_TOKEN` to a new value (for example today's date)
and deploy. Before that point the bot already buys less: a new ticket must leave the money above
the halt line even if every open coin rugs (`[cushion]` in the receipts), the day's worst case
must fit in `DAILY_RISK_BUDGET_PCT` (`[risk_budget]`), and all open tickets together may risk at
most `MAX_AT_RISK_PCT` of the money (`[at_risk]`). These only ever shrink or refuse a buy; sells
are never blocked.

## 6. How to stop and take your money back

With the bot's own wallet (`BOT_WALLET_MODE=generated`) there is no key to take to Phantom: set
`WITHDRAW_TO` to your Phantom address instead ([above](#fund-the-bot-from-phantom-no-keys-needed)).
It sells everything and sends all the SOL back by itself. The steps below are for `BOT_WALLET_SECRET`.

1. In Railway **Variables**, set `KILL_SWITCH` = `sell_all` and **Deploy**. The bot sells
   every open position (accepting more slippage than usual, so it can't get stuck in a thin
   pool) and then stops buying.
2. Wait until the dashboard shows **no open positions**, and check Phantom too.
3. Set `KILL_SWITCH` = `stop`. To be fully safe, also set `TRADING_MODE` = `paper` and delete
   `BOT_WALLET_SECRET`, then **Deploy**.
4. In Phantom, in the **nightcrawler bot** account, tap **Send** and send the SOL back to your
   Coinbase SOL deposit address (in Coinbase: **Receive**, then **SOL**, then network **Solana**)
   or to your main wallet. Leave about 0.001 SOL behind for the fee.
5. Optional: leftover dust tokens still hold small deposits (~0.002 SOL each). Phantom can
   burn or close empty token accounts to get those back.

To stop new buys **without** selling, use `KILL_SWITCH=stop`. Open positions keep being
managed by their normal exits.

---

## What can still go wrong (even with every guardrail)

- **Rugs faster than the stop.** A pool can be emptied between two checks, ten seconds apart.
  The stop-loss sells at whatever price is left. When the price feeds go quiet on a coin (Jupiter
  drops coins it flags right after a rug), the bot asks Jupiter for a sell quote of the whole
  position after 30 seconds and uses that as the price; two failed quotes in a row and it sells,
  trying again every 10 seconds.
- **Gaps.** Prices jump past the -18 % stop. Losses per trade can be much bigger than 18 %: the
  rugs we measured took 84-97 % in one sell. That is why the risk limits count 95 % of every
  ticket: a refused buy whose reason starts "worst case today" means exactly that.
- **Fees and slippage** on every trade, plus MEV (Jupiter Ultra reduces it but can't remove it).
- **Outages.** Jupiter, RugCheck, GeckoTerminal or Railway can go down. The bot fails closed
  (no new buys), but it can't sell if Jupiter can't quote.
- **Strategy decay.** Even a setup that worked last month may not work now.

## Taxes

In the US, and in many other countries, **every swap is a taxable event**: swapping SOL for a
token, or a token back to SOL, is a sale of the thing you gave up. Short-term gains are taxed
as ordinary income, and losses may offset gains. A bot can make many swaps. Keep records:
`nightcrawler report --json`, `nightcrawler receipts export receipts.jsonl`, and your Coinbase
history. Ask a tax professional. This is not tax advice.
