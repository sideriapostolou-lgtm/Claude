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

## 0. The checklist: all of these must be true first

- [ ] **Paper mode ran on Railway for at least 1-2 weeks,** with the dashboard's heartbeat
      green most of the time.
- [ ] **Paper results beat costs over many trades.** Run `nightcrawler report` ("Closed
      trades: ... SOL"), or read the dashboard's "Since start" tile: it is the bot's own result,
      counted **in SOL** and shown at today's SOL price. Do not judge by the big dollar number:
      over a week or two, SOL's own price moves far more than the bot's results, and the page
      lists that "price of SOL" effect separately. The SOL result should be positive *after* fees, over at least 20-30 closed
      trades, and not just thanks to one lucky trade. If it isn't, stop here. A losing paper
      bot will be a losing live bot. (Paper fills already assume 1 % worse than the quote,
      `PAPER_SLIPPAGE_BPS=100`, because real swaps land below the quote.)
- [ ] **Receipts verify.** The dashboard shows "verified", or `nightcrawler receipts verify`
      says OK.
- [ ] **The audit is clean.** `nightcrawler report` says `Result: OK` (exit code 0).
- [ ] **`DASHBOARD_TOKEN` is set** to a long random password, so strangers can't look at your bot.
      Live mode refuses to start without it (unless the dashboard only listens on `127.0.0.1`).
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

## 4. Switch to live mode

**First, close the paper positions.** Set `KILL_SWITCH=sell_all` (still in paper mode), deploy,
and wait until the dashboard shows no open positions. A live bot never sells, counts or values
paper positions (they are not in your wallet); it notes them in the receipts and leaves them
alone, so they would just sit there.

Then, in the same **Variables** tab, set:

| Variable | Value |
|---|---|
| `TRADING_MODE` | `live` |
| `LIVE_CONFIRM` | `I_ACCEPT_REAL_MONEY_RISK` (exactly, capital letters) |
| `KILL_SWITCH` | `off` (it was `sell_all` for the paper close-out) |
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
  Its "Ready for real money?" checklist should already have said "Ready" (all six steps done).
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
and deploy.

## 6. How to stop and take your money back

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
  The stop-loss sells at whatever price is left.
- **Gaps.** Prices jump past the -18 % stop. Losses per trade can be much bigger than 18 %.
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
