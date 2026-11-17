# "dangerously-skip-permissions": what its public trades show (read 2026-10-12 ~18:30 UTC)

Polymarket (international) profile `dangerously-skip-permissions` (proxy wallet
0xc53375ff94e96100f2b30a4b5775db35218d69a9), shown in a social post with +$279k all-time over 86 days. Source: the
public data API (`data-api.polymarket.com/trades?user=...`, maker and taker fills; `pull.py`), the newest 2,000 fills,
which cover 3.2 hours (2026-10-12 ~14:15-17:26 UTC). Analysis: `an.py`. The fills, the markets and the numbers come
from the venue; the post's profit figure is not checked here.

| what | measured |
|---|---|
| markets | only "Bitcoin Up or Down" 5-minute windows (`btc-updown-5m-*`), 38 windows in 3.2 h (every window) |
| sides | 2,000 BUYs, 0 SELLs: it holds everything to the window's settlement |
| both outcomes | it bought BOTH Up and Down in 37 of 38 windows, nearly balanced (median share imbalance 13 %) |
| prices | spread over 0.1-0.9 (most 0.3-0.7): it buys whichever side is cheap at the moment, not near-certain sides |
| timing | fills spread evenly over the first ~4 minutes of each 5-minute window; almost none in the last minute |
| size | median fill 24 shares, about 3,500 shares (~$1,800) per window, every 5 minutes |
| pair cost | average Up price + average Down price per window: median 0.98; under $1 in 65 % of windows |

Reading: this is two-sided accumulation, close to market making. As Bitcoin swings inside a window, each side gets
cheap in turn, and the bot (most likely with resting bids, since the API counts maker fills) buys both, so that a
matched Up+Down pair costs a little under $1 and pays $1 whatever happens. The locked part is about 2c a pair. The
unmatched rest (about 13 %) is a directional bet, and in about a third of windows the pair cost more than $1. So it is
not risk free per window. It makes money at scale: thin edges, 288 windows a day, about $1,800 each, plus whatever the
venue pays makers on these markets.

For our account: Polymarket US lists the 5-minute series but has never listed a window (research/lab8/us_venue.md).
It has 15-minute and 1-hour Up/Down windows with thin books, and the desk only sends immediate orders, not resting
bids. A US copy needs resting two-sided orders, a matched-pair cost cap under $1 after fees, an imbalance limit, and
a test on practice money first. Polymarket international is not open to US accounts.
