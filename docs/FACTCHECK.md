# Fact-check: the "Grok bots + Jev" overnight memecoin posts

*Checked 2026-10-08. All times are UTC. "Market cap" means token price x 1 billion tokens
unless noted.*

Two posts by [@savipww](https://x.com/savipww) on X went viral:

- **Night 4 (HIGGS):** [post](https://x.com/savipww/status/2107046764897333499), Oct 5 at 09:54 UTC, about 1.19M views.
- **Night 5 (HOOKI):** [post](https://x.com/savipww/status/2107411099477832032), Oct 6 at 10:02 UTC, about 612K views.

Both tell the same story. An AI judge ("Jev") picks memecoins, "Grok bots" click buy and
sell, and a "crawler" watches wallets. The bots trade one coin overnight while the author
sleeps, and they beat buy-and-hold by a wide margin. Each post ends by pointing to a "free
setup" link below.

We checked every number we could against real minute-by-minute price data. This page doesn't
reproduce the poster's images, video or article; it links to the originals.

**Contents**

1. [Verdict in short](#1-verdict-in-short)
2. [What we checked and how](#2-what-we-checked-and-how)
3. [Night 4: HIGGS](#3-night-4-higgs)
4. [Night 5: HOOKI](#4-night-5-hooki)
5. [Where the money actually goes](#5-where-the-money-actually-goes)
6. [What an honest bot made on the same charts](#6-what-an-honest-bot-made-on-the-same-charts)
7. [Base rates and real costs](#7-base-rates-and-real-costs)
8. [Red flags checklist](#8-red-flags-checklist-for-the-next-viral-bot-post)
9. [Fairness: what we can't prove](#9-fairness-what-we-cant-prove)

---

## 1. Verdict in short

- **The coins and the charts are real, and the clock is UTC.** At 22:00 UTC, HIGGS was
  9.57 hours old and traded at $2.12M-$2.25M (the post says $2.23M). HOOKI was 3.02 hours old
  at $460K (the post says $460K). The big moves the posts describe really happened.
- **The night-5 (HOOKI) trade log is not a record of real trades.** The poster's own video
  is a replay made after the night ended: its 22:00 UTC frame already shows the final
  buy-and-hold result, -39.73%. Every fill is an exact 5-minute candle close with no fees or
  slippage per trade. Three of its orders were bigger than everything the coin's only pool
  traded in the minutes around them. The last four trades buy and sell at the night's exact
  turning points.
- **The night-4 (HIGGS) log is unverified, and its profit is likely overstated.** Every
  price traded within a few minutes of its stated time. The profit math, though, assumes zero
  costs. The trades don't add up to the stated bankroll. Its video is also a replay: the
  22:28 UTC frame already shows the final buy-and-hold result.
- **Neither night adds up, and there is no wallet.** On night 4 the listed trades sum to
  $5,479, but the bankroll grew $5,447. On night 5 they sum to $6,585, but it grew $6,271. No
  wallet address or transaction was ever shown, so nothing can be checked on-chain.
- **The "free setup" is a referral funnel, and it carries a security risk.** The link
  below each post is a FOMO app referral link, which pays the poster a commission on your
  trading volume. His setup guide tells you to paste it into your coding agent, and it has
  the agent read your logged-in FOMO session out of Chrome. Copycat accounts post the same
  template with other referral codes.
- **Simple, honest bots did far worse on the same charts.** On HIGGS, 315 variations of a
  simple rule made -$632 to +$3,916 (typically about +$1,000), even before price impact. The
  post claims +$5,479. On HOOKI, the same kind of rule lost $2,158, and nine variations ranged
  from -$2,158 to +$734. The post claims +$6,271. This repo's own backtester lost money on
  both nights.

**How sure are we?** High confidence on HOOKI. Medium confidence on HIGGS, where a
skeptical second review found that lagged timestamps could explain most of the timing
problems. See [section 9](#9-fairness-what-we-cant-prove).

### Why this repo exists

nightcrawler, the bot in this repo, was built to measure claims like these honestly, not
to repeat them. It runs in paper mode by default. It prices every simulated fill from a live
Jupiter quote at the real trade size, and it charges fees and price impact. It writes each
decision to a tamper-evident hash chain before later prices are known, so results can't be
edited with hindsight. Its backtester never looks ahead, and when in doubt it assumes the
worse fill. **No profit is promised or implied.** On these two nights its default strategy
lost money ([backtests/README.md](backtests/README.md)), and the base rates in section 7
suggest most setups will lose to fees. Nothing here is financial advice.

---

## 2. What we checked and how

**The posts.** X blocks most automated reading, so we read the posts, replies and the
setup guide through the public [fxtwitter](https://github.com/FixTweet/FxTwitter) API. We
pulled still frames from the poster's two dashboard videos to read the numbers on screen.

**The prices.** We used 1-minute OHLCV candles (open, high, low, close and volume) from
[GeckoTerminal](https://www.geckoterminal.com/) for every pool that traded each coin:

| Coin | Mint (token address) | Pools used |
|---|---|---|
| HIGGS | [`DoVAV...pump`](https://solscan.io/token/DoVAVzViX8Bjy3r15nwikSaSbzE6dV4ovd28aWpJpump) | Main: [PumpSwap `BFrSZ...6Ru`](https://www.geckoterminal.com/solana/pools/BFrSZakeqNzVtM3EFhroo4eRhagmmWN8BRntiQKFH6Ru). Cross-checks: [Meteora `DQyG...Em1`](https://www.geckoterminal.com/solana/pools/DQyGMAGx8nB6ykixotLNFC6eVVQjrMqz7AkRyinNkEm1) and a third Meteora pool (`B8wh...`) |
| HOOKI | [`3ykv...R3R`](https://solscan.io/token/3ykvcjrzbb5nyJRnzHVEA12sQsZfnTijwxUusN4f8R3R) | Its only pool: [Meteora DBC `Bht2...MaR`](https://www.geckoterminal.com/solana/pools/Bht2py3CDiGuNwjdaVRX8ryi2GScveWxU48ZSfB4tMaR). HOOKI never left its bonding curve, so every HOOKI trade went through this pool. |

The candles we used are in this repo: [`data/samples/higgs_1m.json`](../data/samples/higgs_1m.json)
and [`data/samples/hooki_1m.json`](../data/samples/hooki_1m.json).

**Two independent passes.** A first analyst replayed every claim. Then an adversarial
reviewer re-downloaded the data with separate scripts, added a third HIGGS pool, and tried
to argue the poster's side. The two data pulls matched on every minute but one for each
coin, and those two minutes didn't change anything. Where the two passes disagree, this page uses the reviewer's
correction (see [section 9](#9-fairness-what-we-cant-prove)).

**When each coin launched (on-chain).**

- HIGGS: created on pump.fun at 12:26:34 UTC on Oct 4 (the
  [bonding-curve account](https://solscan.io/account/G75N69MfK1vYeqqZPdo6JQTsLwRGf3ka2oTyyU489zZx)'s
  first transaction). It graduated to PumpSwap at 12:36:16 UTC.
- HOOKI: its pool was created at 18:59:05-18:59:12 UTC on Oct 5.

### Proof the posts use UTC

"10pm" only fits both coins if it means 22:00 UTC:

| If "10pm" means... | HIGGS ("9 h old, $2.23M") | HOOKI ("3 h old, $460K") |
|---|---|---|
| **UTC** (22:00 UTC) | 9.57 h old, traded $2.124M-$2.247M. **Fits.** | 3.02 h old, traded $460.1K-$460.4K. **Fits.** |
| UK summer time (21:00 UTC) | 8.57 h old, $2.434M-$2.600M. Off. | Traded $370K-$405K. Off. |
| US Eastern (02:00 UTC) | 13.57 h old, about $1.0M. Off by 54%. | 7.02 h old, $416.8K. Off. |
| US Pacific (05:00 UTC) | 16.57 h old, about $1.03M. Off by 53%. | 10.02 h old, $376.0K. Off. |

Across all the timed prices, UTC misses by about 3% on average for HIGGS and about 1% for
HOOKI. US Eastern misses by 50-80%. The reviewer also tested every whole-hour offset, and
UTC fit best by far. The dashboards in the poster's own images and videos are labelled
"UTC" as well.

---

## 3. Night 4: HIGGS

Oct 4, 22:00 to Oct 5, 06:00 UTC. The post claims the bankroll went from $12,161 to $17,608
(+44.8%).

| Post says (UTC) | Chart shows | Verdict |
|---|---|---|
| 22:00: coin is 9 h old, $2.23M | 9.57 h old. The 22:00 minute traded $2.124M-$2.247M. | **Matches** |
| 22:35: bought at $1.97M | 22:35 traded $2.108M-$2.312M. $1.97M first traded at 22:40-22:41 (22:41 close: $1.971M). | **Real price, but it came 5-6 min later** |
| Sold at $2.29M, +$435 (no time given) | $2.29M traded from 22:54 onward. | **Possible** |
| 23:35: a fake bounce, -$106 | No prices given. A pop to $2.19M at 23:36, then a drop to $2.03M at 23:41, fits a ~4% loss. | **Can't check** |
| 02:25: coin hit $708K, holders down 68%, buy. (Dashboard: 02:26 UTC, filled at 708.4K.) | 02:25-02:26 traded $762K-$798K. $708K first traded at 02:27 (a wick to $659K) and 02:28. | **Real price, but it came 2-3 min later** |
| 03:10: sold at $899K, +$746 | 03:10 traded $894K-$928K. | **Matches** |
| 04:15: second bottom at $716K, buy | 04:15 traded $739K-$817K. The bottom came at 04:19 on two smaller pools and at 04:20-04:21 on the main pool ($715K). | **Real price, but it came 4-6 min later** |
| 05:50: sold at $1.69M, +$4,404 | 05:50 traded $1.560M-$1.717M. A spike to $1.94M came one minute later. | **Matches** |
| Holding from 10pm lost you 24% | $2.23M to $1.69M is -24.2%, but that stops at the bot's own best exit. From the 22:00 close it was -28.7% at 06:00 and -42.3% at 07:00. | **True, but flattering** |
| Bots made +44.8% ($12,161 to $17,608) | The listed trades add up to $5,479 (+45.05%). The bankroll grew $5,447. That's a $32 gap. | **Doesn't add up** |

**What stands out on night 4**

- **Every time is on a 5-minute mark** (22:35, 23:35, 02:25, 03:10, 04:15, 05:50). On the
  main pool, three of the priced buys (22:35, 02:25, 04:15) did not trade in their stated
  minute. They traded 2-6 minutes later, near the local lows. The sells were tradable in
  their minutes, and they are not perfect tops: they came 4-13% below the nearby highs.
- **The profit math has no costs in it.** Divide each profit by its price move and you get
  position sizes of $2,678, $2,765 and $3,237. Those only work with zero fees and zero
  slippage. The dashboard's "SIZE $2,767" matches the zero-fee number.
- **Real costs would bite.** The reviewer roughly estimates that on the main pool alone,
  $2.7K-$3.5K orders moved the price 3-6% per side, and the final $7.6K sale about 9%.
  Splitting orders across pools might halve that. Either way it would cut roughly
  $700-$1,400 from the claimed $5,479.
- **Even a perfect replay falls short.** Take the stated minutes and the best price inside
  each one, and the trades make $4,997 before fees ($4,724 after 1% per side). That's still
  below $5,479. (Section 9 covers the reviewer's objection to this test.)
- **The video is a replay, not a live screen.** *Our own reading of the poster's video.*
  Its first frame, at 22:28 UTC, already shows "HOLD -24.04%". That is the move from 22:00
  to 05:50 on 5-minute closes (-24.05%), which hadn't happened yet. At 22:28 the coin was at
  $2.146M, only about 4% below 10pm. So the video was made after 05:50. That alone doesn't
  prove the trades are fake, because it could replay real logs. It does mean the video is
  not evidence of live trading.
- **The post leaves a trade out.** *Also our reading of blurry, enlarged video frames.* The
  video shows a fifth trade the post doesn't list: in at $1.09M (on screen at 01:28), out at
  $1.13M for +$86. That explains the dashboard's "2W 1L" (two wins, one loss) at 02:26, which
  didn't match the post's list. With that trade added, the trades total about $5,564,
  against the $5,447 bankroll change.
- **The bankroll story doesn't fit the sizing.** The claimed run is $100, then $2,197,
  $4,962, $12,161, $17,608 and $23,879. Night 1 alone is x21.97. With the ~22% position sizes
  shown on night 4, that would need about +9,000% on the money actually in trades.

---

## 4. Night 5: HOOKI

Oct 5, 22:00 to Oct 6, about 07:00 UTC. The post claims the bankroll went from $17,608 to
$23,879 (+35.6%).

| Post says (UTC) | Chart shows | Verdict |
|---|---|---|
| 22:00: coin is 3 h old, $460K | 3.02 h old. The 22:00 minute traded $460.1K-$460.4K. | **Matches** |
| 22:20: first entry was too early, -$271 | No price in the post. The video shows a $2,351 ticket sold at $364.1K, which is the 22:30 five-minute close. A loss fits the chart. | **Plausible** |
| 23:15: crashed to $150K, holders down 67% | 23:15 traded $176.6K-$209.3K. $150.3K is the close of the 23:15-23:19 five-minute bar. The real low was $139.7K at 23:22 (-69.6%). | **A 5-min close, not the stated minute** |
| 23:20: buyers came back, bought at $366K | 23:20 traded $141K-$150K. $365.7K is that 5-min bar's close (23:24). | **A 5-min close** |
| 23:55: sold at $718K, +$2,008 | 23:55 traded $737K-$894K. $718.2K is the 5-min close (23:59). The peak was $980.3K at 23:54. | **A 5-min close** |
| 01:45: "night's bottom" at $279K, buy | 01:45 traded $306.9K-$310.5K. $278.9K is the 5-min close (01:49). It wasn't the night's bottom: the low was $139.7K at 23:22, and the post's own $150K and $224K lines are lower. | **Wrong label** |
| Sold at $558K, +$2,188 (no time given) | The 02:25 bar closed at $557.6K, exactly 2x the entry. It was the highest 5-min close from 00:15 to the end of our data (17:59 UTC). | **Real price, perfectly timed** |
| 06:15: bought at $224K | The price printed ($221.1K-$226.7K). But the ~$3,130 buy is more than the whole pool traded from 06:15 to 06:24 ($2,025, buys and sells together). | **Price yes, size no** |
| Out on the 06:50 close, +$750 | The 06:50 bar closed at $277.3K. The ~$3,880 sale is more than the whole pool traded from 06:50 to 06:59 ($3,020). That bar's last minute traded $22. | **Size doesn't fit** |
| "Two smaller wins," +$1,910 | No details in the post. The video shows them: $295.4K to $427.2K (+$1,152) and $321.6K to $394.8K (+$758). Both are the best possible trades in their time windows. | **Perfect timing** |
| Holding from 10pm left you 40% poorer | $460.1K to $277.3K is -39.73%. | **Matches** |
| Bots up 35.6% ($17,608 to $23,879) | The listed trades add up to +$6,585 (+37.4%). The $314 difference is exactly a flat ~2% round-trip cost on each ticket, charged only to the bankroll. | **Per-trade figures are before costs** |

**What stands out on night 5**

- **The video was made after the night ended.** Its frame stamped 22:00 UTC shows:
  - a balance of $17,608.72 and bot P&L of $0.00;
  - "HOLD -39.73%", which is the 22:00 to 06:50 result and hadn't happened yet;
  - "$HOOKI MC $500.3K", which is the close of the 22:00-22:04 bar. At 22:00 itself the price
    was $460.1K.

  A live dashboard can't know either number at 22:00. The video was rendered after 06:55 UTC
  from 5-minute data.
- **Every fill is a 5-minute close.** All 12 buy and sell prices across the six trades
  match exact 5-minute candle closes.
- **No costs per trade.** Each trade's profit equals its size times the move between two
  5-minute closes, to within $1-2. A flat ~2% is taken off only at the bankroll level. That
  looks like a simulator's bookkeeping. Real swaps take their costs out of each trade.
- **Some orders were bigger than the market.** HOOKI traded in only one pool. In 6 of the
  12 legs, no single minute from 5 minutes before to 10 minutes after the candle close traded
  as much as the order. In 3 legs, the order was bigger than everything the pool traded in
  the whole 10-minute window around it. For example, the $3,130 buy at 06:15 compares with
  $2,025 traded from 06:15 to 06:24. (This assumes GeckoTerminal recorded every
  trade. Its 24-hour volume matched DexScreener's within about 3%.)
- **The last four trades hit the exact turning points.** All 8 of their buys and sells land
  on the night's swing lows and highs. The buy at $223.7K was the lowest 5-minute close in 9
  hours. Knowing a swing has ended takes hindsight.
- **"Limits only, all night" doesn't fit.** The dashboard says it used only limit orders.
  But a resting buy at $366K, placed while the price sat at $141K-$150K, would have filled
  right away near $150K.
- **The on-screen balance drifts** by up to about $280 while no position is open. It isn't
  reading a ledger.
- **With realistic costs**, meaning 1% fees per side plus the pool's measured price impact,
  the same six trades make about +$3,770 (+21%), not +$6,271.

---

## 5. Where the money actually goes

**The link "below."** Within minutes of each post, the poster replied with the same
three links ([night 4 reply](https://x.com/savipww/status/2107047843080864062),
[night 5 reply](https://x.com/savipww/status/2107411860115030289)):

- a "trading here" link, `fomo.family/r/savipww`, which is a referral link to the FOMO trading
  app (we're not linking it here);
- a Telegram channel (175 subscribers) whose description repeats the same link;
- a GitHub account where projects are "soon."

The "free setup" itself is an X article,
["Megabrain (Jev) & Six Grok Bots That Already Made Me Six Figures (Setup Guide)"](https://x.com/savipww/status/2102720919185617314)
(Sep 23, about 2.85M views).

**How referral links pay.** [FOMO's affiliate page](https://fomo.family/affiliates) says
referrers earn a commission on trades made through their link, and FOMO's
[terms](https://fomo.family/legal/terms) (section 8) cover the program. The poster's invite
page offers 10% off fees with his code. His guides
([Sep 2](https://x.com/savipww/status/2095171104004575708) and Sep 23) say all fills go
through FOMO, including the ones your bots place, so every bot trade counts toward his
referral.

The key point: **a referrer earns on your trading volume, not your profit.** A bot that
trades all night pays fees whether it wins or loses, and the referrer gets a share either way.
We didn't find FOMO's exact commission rate. For scale, here are similar programs:

- [Axiom](https://docs.axiom.trade/getting-started/referral-program.md) pays 30% of the net
  fee. Its own example: one referral trading $10K a day pays the referrer $30 a day.
- [Trojan](https://docs.trojan.com/trojan-arena/referral-system.md) pays 27.5-47.5% across 5
  levels.
- [GMGN](https://docs.gmgn.ai/index/cooperation-referral-refer-friends-to-earn-rebate-30-rebates-easily-earn-over-usd8000-monthly.md)
  pays 10-30%.

**The security problem in the guide.** The setup article:

- tells you to "PASTE THIS ENTIRE GUIDE INTO YOUR CODING AGENT";
- says FOMO has no public API, "so the collector reads your own logged in session";
- has its code import a `fomo_api` module, described as pulling a "Privy bearer out of Chrome
  over CDP," and that module is never provided;
- puts the judge server on the public internet through a `cloudflared` tunnel.

In plain terms, your coding agent would be asked to pull your FOMO login token out of
Chrome. (Privy is a sign-in and wallet provider; CDP is Chrome's remote-control debugging
connection.) Whoever holds that token can act as you in the app, and the code that handles
it isn't shown. That has the same shape as the wallet-stealing "free bot" scams in
[section 7](#scams-that-use-free-bot-posts). A
[third-party review](https://x.com/FarVisionNetwks/status/2106476635298120164) flagged the
same three problems.

**What's real here.** Jev is a real decision model from TypeSafe AI
([Bitcoin.com News](https://news.bitcoin.com/this-ai-cant-chat-but-crypto-traders-are-already-putting-it-to-work/)),
and it doesn't trade on its own. Grok Bot is a real xAI agent product with its own cloud
computer ([KuCoin News](https://www.kucoin.com/news/flash/xai-launches-grok-bot-ai-agent-with-its-own-computer-for-cross-app-task-automation),
[xAI docs](https://docs.x.ai/grok-bot/get-started)). Bots clicking in an app is possible.
The profits are what's unshown.

**Other context**

- **Bankroll resets with no withdrawals shown:** $68,024 (Sep 20), then a "new run" at
  $1,000 (Sep 22), $101,607 (Oct 1), and a $100 "restart" (Oct 2).
- **The guide's own rule isn't followed.** It caps each trade at "6% of the book," but the
  night-5 tickets were 10.8-14.8% of the bank.
- **An earlier coin push.** On Aug 31 he posted a community coin's contract address
  ([post](https://x.com/savipww/status/2094373039177978205)). On Sep 1 he said his bank was
  "locked in" it ([post](https://x.com/savipww/status/2094653163332890751)). GeckoTerminal
  now shows no price for it and $0 of daily volume.
- **No Community Notes** were on either post when we checked. Some replies called the posts
  referral farming or a motion graphic
  ([1](https://x.com/hassaniazii/status/2107424858149658881),
  [2](https://x.com/Sateloid/status/2107569798993604919),
  [3](https://x.com/Stopwydd/status/2107315040865202434)).

### The same template, other accounts

- [@bl888m_eth](https://x.com/bl888m_eth/status/2107499822626603454) runs the same series
  with other coins: a "$100 restart" that grows each night, using the same closing lines
  ([another post](https://x.com/bl888m_eth/status/2107819855546331573)). It pushes a private
  Telegram instead of a FOMO link.
- Word-for-word copies of the night-5 post:
  [@konig0000](https://x.com/konig0000/status/2107667383980806311) and
  [@Edenwoodfilm](https://x.com/Edenwoodfilm/status/2107596173137891748) (account created
  Aug 2026).
- A Chinese-language version pushes a different FOMO referral code:
  [1](https://x.com/laoyingkhq/status/2100904920543056012),
  [2](https://x.com/qkl2058/status/2106562951163326701),
  [3](https://x.com/Cjsw03/status/2107043618376831158). One of them says outright that its
  executor only does paper fills.
- Several new, tiny accounts reply within seconds or minutes with praise or "thanks for
  helping me set it up" testimonials. This looks coordinated to us, but we can't prove it.

---

## 6. What an honest bot made on the same charts

To see what a bot without hindsight gets, we fixed simple rules before running them,
replayed them on the same minutes, and charged costs.

- **The rule:** buy when the price is at least 50% below the night's high and the last two
  1-minute candles are green. Take profit at +40% and stop out at -20%.
- **Trading assumptions:** about $2,500-$2,700 per trade, one trade at a time, and a 1% cost
  per side. If a candle hits both the target and the stop, the stop counts. (The details
  differ slightly between the two nights.)

| Approach | HIGGS night | HOOKI night |
|---|---|---|
| **The post's claim** | **+$5,479** | **+$6,271** |
| The post's own trades, with realistic costs | +$4,242 (the post's stated minutes at real prices, 1% per side). Price impact would take more. | about +$3,770 (1% per side plus measured price impact) |
| The simple rule above | +$844 (4 trades) | -$2,158 (4 trades, 0 wins) |
| The same rule, 9 setting variations | +$262 to +$1,658 (median about $943) | -$2,158 to +$734 (median -$811; 2 of 9 positive) |
| A wider search (315 variations), before price impact | -$632 to +$3,916 (median $1,084). None reach $5,479. | (not run) |
| Buy at 22:00 and hold | -25% to -42%, depending on when you sell | -$1,023 on $2,500 |
| nightcrawler backtester, post's bankroll, fees + impact | **-$1,529.45** | **-$4,686.68** |
| nightcrawler backtester, zero costs (an impossible best case) | -$99.03 | -$3,169.02 |

A few notes on these runs:

- On HOOKI, the simple rule was stopped out at $281K at 01:49, the very bottom the post
  says it bought.
- On the same night, the same rule with price impact lost $2,726. On 5-minute candles it
  lost $149.
- Our own backtester's runs, including the default $100 runs (HIGGS -$2.08, HOOKI -$25.79),
  are in [backtests/README.md](backtests/README.md), with every trade in
  [backtests/samples.json](backtests/samples.json). It never looks ahead, fills at the next
  candle's open, charges 1% fees plus price impact per side, and fills exits the way a bot
  polling every 10 seconds could (no stop at the exact level of a candle that closed below
  it, no take-profit on a one-minute wick).

**What this proves and doesn't.** A simple rule can't show that some other strategy, or an
AI judge, never made these trades. It shows what bots without hindsight typically get on these
exact charts once costs are counted. On HIGGS that's a small gain, not $5,479. On HOOKI it's
a loss.

---

## 7. Base rates and real costs

### How often these coins survive

| Fact | Number | Source |
|---|---|---|
| pump.fun tokens whose last trade was on launch day | 68.7% (12.8M of 18.67M). Only 4.55% still traded after 90 days. | [CoinGecko](https://www.coingecko.com/research/publications/average-lifespan-of-pumpfun-tokens) (Jun 2026) |
| pump.fun tokens classed as pump-and-dump (liquidity fell under $1K) | 98.6% of 7M+ | [Solidus Labs](https://www.soliduslabs.com/reports/solana-rug-pulls-pump-dumps-crypto-compliance) (May 2025) |
| Tokens that graduate off the bonding curve | ~1.4% all-time, 0.4-0.6% by mid-2026 | [Solana Compass](https://solanacompass.com/news/pumpfun-launched-42000-tokens-in-one-day-fewer-than-2-will-ever-reach-a-dex) (Jun 2026), [The Block](https://theblock.co/post/409815/pump-fun-token-graduation-rate-jumps-boost-changes-launch-incentives) (Jul 2026) |
| Tokens above a $1M market cap at a given moment | 89 of ~2M (2024); 96 of 11.9M (Jun 2026) | [Decrypt](https://decrypt.co/249107/fewer-than-100-pump-fun-tokens-above-1m-market-cap-amid-meme-coin-lull), [Solana Compass](https://solanacompass.com/news/pumpfun-launched-42000-tokens-in-one-day-fewer-than-2-will-ever-reach-a-dex) |
| New Orca, Raydium and Meteora tokens that were rug pulls (H1 2025) | 76,469 of 100,063 | [arXiv 2603.24625](https://arxiv.org/abs/2603.24625) |
| Memecoins up >100% that showed manipulation | 82.8% | [arXiv 2507.01963](https://arxiv.org/abs/2507.01963) |
| Wallets that had realized >$10K (Jan 2025) | 0.41% of 13.55M | [Decrypt](https://decrypt.co/300403/pump-fun-traders-millionaires) |
| Profitable wallets in a good month (Apr 2026) | 73.3%, but 65% of all wallets made only $1-$500, and 5.4% made over $1K | [CoinGecko](https://www.coingecko.com/research/publications/pump-fun-traders-are-making-a-comeback) |

HIGGS graduated and reached $6M at its peak, which puts it in a tiny fraction of launches.
Picking it out in advance is the hard part, and the posts skip that.

### What a real bot pays

- **Platform fees:** pump.fun's bonding curve charges 1.25% per trade, and PumpSwap charges
  0.30-1.25% ([pump.fun fees](https://pump.fun/docs/fees)).
- **Trading-app fees:** about 1% per side at
  [GMGN](https://docs.gmgn.ai/index/gmgn-fees-settings.md), 0.75-0.95% at
  [Axiom](https://docs.axiom.trade/getting-started/fees/axiom-fees.md), and about 1% at Photon
  ([ComparEdge](https://comparedge.com/tools/photon-sol/pricing)).
- **Network and priority fees:** about 0.001-0.005 SOL per trade
  ([Axiom](https://docs.axiom.trade/getting-started/fees/solana-fees.md)).
- **Slippage:** GMGN recommends 30-35% slippage tolerance, and 50% or more for new tokens. A
  sandwich bot can take up to that much of your trade.
- **Price impact on these exact pools:** on HOOKI overnight, each $1K traded moved the
  price about 3%, and these orders were $2K-$4K. HIGGS is estimated at 3-6% per side for
  $3K orders on its main pool.
- **What this adds up to:** one round trip on a $100 position costs about 4.4-5.6% before
  any slippage. A bot with no edge keeps only about 32-40% of its money after 20 round trips,
  and 6-10% after 50.
- **Sandwich attacks (MEV):** an estimated $370M-$500M was taken from Solana users between
  Jan 2024 and May 2025
  ([Solana Compass](https://solanacompass.com/learn/accelerate-25/scale-or-die-at-accelerate-2025-the-state-of-solana-mev)).
  16 of the 20 most-sandwiched tokens in one study were pump.fun tokens
  ([Helius](https://www.helius.dev/blog/solana-mev-report)).

### Can AI pick these trades?

- **The closest test to this exact claim:** 3,505 AI agents traded memecoins with real money
  for 21 days. They showed no directional edge, and 49% of the positions that went up 3% or
  more still closed at a loss ([arXiv 2609.05663](https://arxiv.org/abs/2609.05663), Sep
  2026). The authors run the platform they studied.
- **A head-to-head contest:** in Alpha Arena Season 1, four of six top AI models lost about
  30-63% trading crypto
  ([Forklog](https://forklog.com/en/four-out-of-six-ai-models-suffer-losses-in-trading-tournament/)).
- **Signals fade fast:** a model that predicted pump.fun winners well in its test month fell
  to coin-flip accuracy over the next 14 days
  ([arXiv 2607.02823](https://arxiv.org/abs/2607.02823)).
- **Stocks too:** most models fail to beat buy-and-hold
  ([StockBench](https://arxiv.org/abs/2510.02209),
  [FINSABER](https://arxiv.org/abs/2505.07078)).
- **Speed:** an AI model takes seconds to answer, while Solana makes a block about every 0.4
  seconds. An AI-judged bot is always late to a launch.

### Scams that use "free bot" posts

- **Fake GitHub bots that steal wallet keys**
  ([Cointelegraph/SlowMist](https://cointelegraph.com/news/solana-trading-bot-github-malware-scam)).
  [SlowMist](https://slowmist.medium.com/slowmist-2025-q3-misttrack-stolen-funds-analysis-639cbcefdf6f)
  found that every victim it examined in Q3 2025 had used a malicious GitHub project.
- **Fake code packages that send keys out:**
  [The Hacker News](https://thehackernews.com/2025/01/hackers-deploy-malicious-npm-packages.html)
  and [BleepingComputer](https://bleepingcomputer.com/news/security/gitvenom-attacks-abuse-hundreds-of-github-repos-to-steal-crypto)
  reported these.
- **YouTube "MEV bot" contracts** that drain whatever you fund them with
  ([SentinelLABS](https://www.sentinelone.com/labs/smart-contract-scams-ethereum-drainers-pose-as-trading-bots-to-steal-crypto/)).
- **Trading bots that hold your keys and get hacked.** DEXX lost about $21-30M
  ([Cointelegraph](https://cointelegraph.com/news/solana-dexx-hack-november-2024-suspicious-wallets)).
- **Bought X accounts with AI personas** that farm views and then push a coin
  ([Cointelegraph on ZachXBT](https://cointelegraph.com/news/zachxbt-fake-war-posts-x-crypto-scam-network)).
  Profit screenshots are easy to fake
  ([Cointelegraph](https://cointelegraph.com/news/crypto-analyst-accused-of-photoshopping-trade-screenshots)).

### Taxes (US; not tax advice)

- **Every swap is taxable.** The IRS treats crypto as property, so every swap is a taxable
  sale ([IRS](https://www.irs.gov/filing/digital-assets)). A bot doing hundreds of trades
  creates hundreds of tax records.
- **Your exchange may not report it.** DEX trades may not show up on a Form 1099-DA, but
  they're still taxable ([Fenwick](https://www.fenwick.com/insights/publications/trump-signs-joint-resolution-repealing-defi-broker-reporting)).
- **Little legal protection.** SEC staff say memecoins generally aren't securities
  ([SEC](https://www.sec.gov/newsroom/speeches-statements/staff-statement-meme-coins)).

---

## 8. Red flags checklist for the next viral bot post

**The proof**
- [ ] No wallet address and no transaction links. (A real track record takes one link to
      share.)
- [ ] A "dashboard" video instead of on-chain records.
- [ ] The video shows end-of-night numbers (like a final "HOLD -39.73%") at the start of
      the night.

**The numbers**
- [ ] Every trade time is on a 5-minute mark, and every price equals a candle close.
- [ ] Each profit equals size x price change exactly, with no fees or slippage.
- [ ] The individual trades don't add up to the headline.
- [ ] Order sizes are bigger than the coin's trading volume at that time. (Check the pool on
      GeckoTerminal.)
- [ ] Buys at the exact bottom and sells at the exact top, again and again.
- [ ] "Holding would have lost X%" is measured to the bot's own best exit.
- [ ] Growth that doesn't fit the stated position size (x22 in one night).
- [ ] Bankroll "restarts" with no withdrawals shown.

**The pitch**
- [ ] A "free setup" link that turns out to be a referral link (`/r/`, `?ref=`, invite
      codes).
- [ ] "Paste this into your coding agent."
- [ ] Any request for your private key, seed phrase, browser session or cookies.
- [ ] Missing modules or code you can't read.
- [ ] Tunnels that put your computer on the internet.
- [ ] The same text appearing on other accounts.
- [ ] Brand-new accounts posting testimonials within seconds.

**Check it yourself in five minutes**
1. Look the coin up on [GeckoTerminal](https://www.geckoterminal.com/) and switch the chart
   to 1-minute candles in UTC.
2. Check whether each claimed price traded in its stated minute, and how much volume
   traded around it.
3. Ask for the wallet address. Then compare its fills on [Solscan](https://solscan.io/) with
   the claims.

---

## 9. Fairness: what we can't prove

Two people checked these posts. The first analyst built the case. The reviewer then
re-checked it on separate data and argued the poster's side as hard as possible. Where they
disagree, we go with the reviewer.

### Night 4 (HIGGS): the reviewer pulled the verdict back

| Point | First pass said | Reviewer found (what we use) |
|---|---|---|
| Market-cap basis | Price x 1 billion tokens fits best. | About 31.8M HIGGS were burned at some point, and chart sites now use the on-chain supply (968.2M). The first pass picked 1 billion because it fit the claims, then used it to show the buys sat on the bottoms. That's circular. |
| The 04:15 buy at $716K | Not traded in that minute (3.2% away). | On the on-chain supply basis, it did trade: $739.0K x 0.9682 = $715.5K. |
| "Buys sit exactly on the bottoms" | 0.1-0.3% from the lows | Only on the 1-billion basis. On the on-chain basis, the buys were 3-11% above the lows. That's good trading, not impossible trading. |
| All times on 5-minute marks | Odds of 0.006% by chance | People round times, and a bot on 5-minute candles logs 5-minute labels. With a 3-4 minute clock lag and a ~0.975 supply basis, all six prices trade in their exact minute. No random time shift did that in 200 tries. |
| The dashboard shows $708.4K at 02:26 | A fill before the price existed | Weak evidence. That price traded the very next minute, so display lag explains it. |
| "No costs in the P&L" | Proven | Only one reading. If the logged prices are actual fill prices, costs are already inside, and the $32 gap could be network fees. Realistic price impact still isn't in anyone's numbers. |
| "A buy signal has to come after the bottom" | Yes | No. The 04:13-04:14 candles were green, so a signal could fire at 04:15, before the 04:20 low. |
| "The best-tick replay caps the profit" | Yes | Only if the stated minute was the trade minute. With a few minutes of lag, the whole sequence was tradable, before costs. |
| Grid of simple rules | -$583 to +$1,658 | +$262 to +$1,658. The -$583 came from a separate variant. |
| Overall | "Almost certainly written from the finished chart" | **"Not proven real, and the P&L is likely overstated net of costs."** Medium confidence. |

What still counts against night 4 after the reviewer's corrections:

- no wallet and no transactions;
- trades that don't add up to the bankroll;
- realistic price impact of 2-6% per side, which would cut roughly $700-$1,400;
- night 1's x21.97, which doesn't fit the sizing;
- no simple rule that reaches the claimed result;
- the same engagement-bait template across many accounts.

Two of our own video readings came after the reviewer's pass, so the reviewer didn't
check them:

- **"HOLD -24.04%" at 22:28 UTC.** This shows the video is a replay. It could still be a
  replay of real logs.
- **The unlisted +$86 trade.** This supports the reviewer's view that "2W 1L" came from a
  trade the post left out. It also means the post's trade list is incomplete.

### Night 5 (HOOKI): the reviewer made the case stronger, with corrections

| Point | First pass said | Reviewer found (what we use) |
|---|---|---|
| "Two smaller wins" | Can't be checked | Can be checked: the video shows both, and they are the best possible trades in their windows. |
| The $314 gap | An arithmetic mismatch | A flat ~2% cost per ticket, charged at the bankroll level. It reproduces $23,879.40 to within $0.77. The books are internally consistent, like a simulator's. |
| First trade (-$271) | Rebuilt as $2,229 or $2,669 | The video shows $2,351, sold at $364.1K. |
| 23:55 sale | Fits a ~20% trailing stop | Doesn't. Only a 15-19.6% trail fits. |
| Price-impact model | The 06:15 trade turns into a -$29 loss | Too harsh. That trade is roughly break-even to slightly positive (+$216). All six trades come to about +$3,770, not a loss. |
| 5-minute labels prove chart-reading | Yes | Overstated. Bots that act on candle closes log exactly this way. The decisive evidence is the replay video, the volume checks and the 8-of-8 turning-point fills. |
| The 10pm price | A 5-min close | It's the bar's open. The other six prices are closes. |
| Overall | Written from the chart after the fact | Agreed, more strongly: **a simulation on 5-minute UTC candles, evaluated after the fact; not real swaps.** High confidence. |

**The most charitable reading** of night 5 is that a paper-trading bot ran live on 5-minute
UTC candles. It logged candle-close prices instead of real fills, charged a flat 2% for
costs, and happened to call four swing bottoms and tops in a row. We can't rule that out
completely. But it would need 8 of 8 perfect turning-point fills, and it would still be
paper money, not real money. With realistic costs, even that version makes about +21%, not
+35.6%.

### Limits that apply to everything here

- **We can't see the poster's wallet.** One wallet address would settle every question in
  minutes on Solscan.
- **The price and volume data come from GeckoTerminal**, a third-party indexer. The volume
  argument assumes it recorded every trade. It agreed with DexScreener's 24-hour volume
  within about 3%.
- **A replay video could have been made from real logs.** It proves the video isn't live,
  not that the trades never happened.
- **Simple-rule backtests can't prove** that a different strategy didn't make these trades.
- **We didn't open the poster's GitHub** or read his private Telegram.
- **The coordinated-boosting point is an inference.** We present it as one.
- **Video readings come from compressed, blurry frames.** We enlarged them, and we flag the
  numbers that rest on them.
