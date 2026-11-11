# Venues for a small-ticket desk: what the research found (2026-10-09)

A ten-agent research sweep (five researchers, five fact-checkers who re-opened every cited page) on the venues a
$5-$100 paper desk could use for many small profits a day. Facts as read on 2026-10-09; fee pages change, so the
date of the page is given where it states one. Corrections from the fact-checkers are folded in.

## Prediction markets

**polymarket.com (international).** Taker-only fee `shares x rate x p x (1 - p)`: crypto 0.07, sports 0.05,
economics / culture / weather / other 0.05, finance / politics / mentions / tech 0.04, geopolitics 0; makers pay
nothing and earn a rebate (https://docs.polymarket.com/trading/fees). The United States, United Kingdom, France,
Germany, Italy, Australia, Singapore, Canada (several provinces) and others are **close-only on the site and the
API** (no new positions); a VPN violates the terms (https://docs.polymarket.com/api-reference/geoblock,
help-centre article updated 2026-08-14). Public data: Gamma (market lists, resolutions), CLOB (books, prices,
1,500 req/10 s), Data API (trades; `/v2/prices-history` with 1-minute buckets kept at least 7 days, 5-minute
60 days, 30-minute 90 days, 3-hour and 12-hour permanently; 200 req/10 s). Minimum order 5 shares; ticks per
market. Resolution through UMA: $750 bond, 2-hour challenge window, about 2 hours after the proposal when
undisputed, 4-6 days when disputed; $1 per winning share, no redemption deadline.

**Polymarket US (polymarket.us, QCX LLC, CFTC-regulated).** The owner's venue. Taker fee `0.0695 x shares x p x
(1 - p)`, maker rebate `0.0125 x ...` (https://docs.polymarket.us/fees, effective 2026-10-01). Public market data
at `gateway.polymarket.us` (markets, books, best bid / offer, settlement, price history; 20 req/s per IP); the key
(key id + Ed25519 secret) is only for orders, positions and balances; no sandbox. On 2026-10-09: 5,000 open
markets, 88 % sports; ~3,000 settlements a day, ~2,900 of them sports; the recorder found 537 non-sports markets
ending within 48 hours (477 hourly / weekly crypto strike markets, 60 daily city-temperature brackets).

**Kalshi (CFTC-regulated DCM).** Taker fee `round up(0.07 x contracts x P x (1 - P))`, maker fee 0 on 14,570 of
14,765 series (fee schedule effective 2026-07-07). Public REST v2 (markets, settled markets with
`min_settled_ts`, candlesticks up to 5,000 per call, trades); anonymous reads throttle quickly (HTTP 429), a free
account key lifts the limit. **Washington State:** a King County court ordered Kalshi in August 2026 to stop
offering sports, elections, politics, entertainment, culture, technology / science and "mentions" contracts to
people in the state, with geofencing due 2026-09-02, so Kalshi is not a path for this owner.

## The arithmetic that decides the grind

A contract pays at most $1, so a $20 ticket bought at price p can gross at most `20 x (1 - p) / p`: **$0.50 on a
$20 ticket is impossible above 97.6c and $1.00 above 95.2c.** A 98c contract on $100 grosses $2.04 before a fee of
about $0.14 (US venue). Small tickets must take lower prices (more risk per trade) or bigger tickets.

## Evidence on buying near-certain outcomes (favourite-longshot bias)

- Cardozo & Rivero-Wildemauwe, arXiv 2609.12878 (Sept 2026), 561 M Polymarket purchases, $22.5 B, 2022-11 to
  2026-03: buying at >= 90c returned **+0.28 % per dollar equal-weighted (CI 0.24-0.31) and +0.83 % dollar-weighted,
  before fees**; longshots under 10c lost 6-19 %. By category (equal / dollar weighted): crypto +0.64 % / +0.54 %,
  politics +1.04 % / +1.42 %, **sports -0.23 % / +0.14 %**, finance +0.09 % / +1.83 %, weather +0.50 % / +0.03 %,
  culture +0.74 % / +0.83 %, tech +0.82 % / +0.85 %.
- Burgi, Deng & Whelan, GWU WP 2026-001 (Kalshi, 2021 to 2025-04, hourly crypto excluded): contracts under 10c
  lose > 60 %; small positive post-fee returns only above ~70c; the gains accrue mostly to makers.
- A public backtest (wcsmars, results 2026-10-01): buying 90-99c favourites 7 days out, 626 trades, 94.7 % wins,
  +0.28 % mean net per contract; 30 days out, 328 trades, 96.6 % wins, +0.65 %.
- Current fixed-horizon calibration (d-o-g-e warehouse, 72.7 K resolved markets with > $10 K volume): the 90-100c
  bucket 24 hours before resolution resolves Yes **95.7 % of the time at an average price of 97.1c**, i.e. slightly
  worse than priced.
- 2026 US primaries (Bitquery): Polymarket favourites at 95c+ won 141 / 143; 90-95c won 36 / 39; five of 182
  favourites priced >= 90c lost.
- Kalshi's own Aug 2026 calibration study (2.24 M resolved markets): Brier below 0.02 at close, 97.2 % naive
  accuracy; third-party Kalshi political buckets look slightly under-confident (90-100 % bucket +5 pp).

Reading: the edge is real on average, tiny (fractions of a percent per dollar), concentrated in crypto and
politics, absent in sports, and the most recent calibration shows no room at 97c once fees are paid. The lab's
P4 (non-sports) is the hypothesis that matters for the owner's venue.

## Stocks and crypto for later desks

- **The US pattern-day-trader rule is gone**: FINRA Rule 4210 amendments (SEC-approved 2026-04-14, effective
  2026-06-04) deleted the designation and the $25,000 minimum; brokers may phase in until 2027-10-20
  (https://www.finra.org/rules-guidance/notices/26-10). Alpaca switched on 2026-06-04 and removed the day-trade
  counters.
- **Alpaca paper trading** is free (email sign-up, no deposit, $100 K paper balance, separate paper keys, base
  `https://paper-api.alpaca.markets`, headers `APCA-API-KEY-ID` / `APCA-API-SECRET-KEY`), fills against NBBO with
  IEX-only data and random 10 % partial fills; free data is IEX real-time (30 websocket symbols, 200 historical
  calls / minute). Real stocks: $0 commission, SEC fee $20.60 per $1 M sold, CAT $0.000003 per share. Alpaca crypto:
  0.15 % maker / 0.25 % taker (tier 1), 24/7, not under the margin framework.
- **Round-trip cost of a $20 taker ticket and the move needed to net $0.50**: Coinbase Advanced (US entry tier
  0.50 % / 0.90 % since 2026-09-16) $0.36, 4.3 %; Kraken Pro (0.40 / 0.80) $0.32, 4.1 %; Alpaca crypto $0.10,
  3.0 %; Hyperliquid perps (0.015 / 0.045 + funding) $0.02, 2.6 %; Binance.US (0 / 0.019 %) $0.008, 2.5 %; Alpaca
  stocks about $0.0004, 2.5 %. For $100 tickets: Coinbase 2.3 %, Kraken 2.1 %, Alpaca crypto 1.0 %, Hyperliquid
  0.6 %, Binance.US 0.5 %, Alpaca stocks 0.5 %. Cheapest for a repeated grind: Binance.US for crypto, Alpaca for
  stocks; Coinbase Advanced is now the most expensive of the eight for a small US trader.

## What this means for the town

1. Prediction markets: the near-certain grind is a thin-edge, tail-risk business. Lab 4 measures it on history,
   P4 for the owner's venue, before any paper desk exists.
2. Stocks: with the day-trade rule gone and Alpaca paper free, a stocks desk is feasible later at near-zero fees;
   the edge still has to be found and tested like every other desk.
3. Crypto majors: lab 3's trend sleeve is the slow-money track; a fast grind on Coinbase is cost-prohibitive.
