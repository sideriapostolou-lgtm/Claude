"""Classify a Polymarket (international) market by slug / eventSlug / title into a family.

Families (and whether a twin exists for the owner):
  crypto_5m        BTC/ETH/SOL/XRP up/down 5-minute     -> no twin (Kalshi has 15m only; PM US never listed 5m)
  crypto_15m       up/down 15-minute                     -> Kalshi KXBTC15M/KXETH15M/..., PM US BTC 15m
  crypto_1h        up/down hourly                        -> Kalshi KX*D hourly directional? PM US BTC 1h
  crypto_4h        up/down 4-hour                        -> none
  crypto_daily_ud  up/down on a day                      -> none exact (Kalshi daily above/below is a strike)
  crypto_level     above / price-range / hit-price ladders (hourly, daily, weekly, monthly)
                                                          -> Kalshi KXBTCD/KXBTC/KXETHD/..., PM US hourly above
  weather          highest/lowest temperature, rain, snow -> Kalshi KXHIGH*/KXLOW* (city-dependent)
  econ             Fed, CPI, jobs, GDP, unemployment       -> Kalshi Economics (check owner's access)
  finance          indices, stocks up/down, close above, FX, yields -> Kalshi Financials (index ones)
  commodity        gold, silver, oil, natgas               -> Kalshi Commodities
  sports           games, futures, props                   -> PM US (sports)
  politics         elections, government, geopolitics     -> blocked
  other            everything else (culture, mentions, tech, misc)
"""
import re

SPORT_PREFIX = re.compile(r"^[a-z0-9]{2,7}-[a-z0-9]+-[a-z0-9]+-20\d\d-\d\d-\d\d")
COINS = r"(?<![a-z])(btc|eth|sol|xrp|bitcoin|ethereum|solana|ripple|doge|dogecoin|bnb|hype|hyperliquid)(?![a-z])"

WEATHER = re.compile(r"(highest-temperature|lowest-temperature|temperature-in|temperature-increase|"
                     r"precipitation|(?<![a-z])rain(?![a-z])|inches-of-rain|snowfall|inches-of-snow|"
                     r"hottest|global-temperature|named-storm|hurricane-(season|landfall|category)|"
                     r"heat-index|(?<![a-z])weather(?![a-z]))")
LEAGUE = re.compile(r"(?<![a-z])(nfl|nba|mlb|nhl|wnba|ncaa|cfb|cbb|epl|mls|ufc|atp|wta|f1|"
                    r"vs|boxing)(?![a-z])")
ECON = re.compile(r"(fed-|fomc|interest-rate|rate-cut|rate-hike|inflation|cpi|pce|jobs-report|nonfarm|"
                  r"unemployment|jobless|gdp|recession|payroll|bps-|basis-points|powell)")
COMMODITY = re.compile(r"(?<![a-z])(gold|silver|crude|oil|wti|brent|natural-gas|natgas|copper|platinum)(?![a-z])")
FINANCE = re.compile(r"(spx|s-p-500|sp-500|s&p|nasdaq|ndx|dow-jones|djia|russell-2000|"
                     r"close-above|close-at|closes-above|(?<![a-z])(nvda|tsla|aapl|msft|amzn|googl|qqq|spy)(?![a-z])|"
                     r"usd-jpy|eur-usd|usdjpy|eurusd|treasury|10-year|(?<![a-z])vix(?![a-z])|stock-price|"
                     r"up-or-down-on)")
CORP = re.compile(r"(ipo|market-cap|largest-company|earnings|eps|revenue|valuation)")
POLITICS = re.compile(r"(election|president|trump|biden|harris|senate|house|governor|mayor|"
                      r"parliament|prime-minister|minister|congress|democrat|republican|vote|"
                      r"primary|nominee|cabinet|impeach|war|ukraine|russia|israel|iran|gaza|china|"
                      r"tariff|supreme-court|pope|ceasefire|nato|putin|zelensky|xi-|government|"
                      r"shutdown|midterm|balance-of-power|deport|executive-order|approval-rating)")
SPORTS_WORDS = re.compile(r"(nfl|nba|mlb|nhl|ncaa|cfb|cbb|epl|premier-league|champions-league|uefa|"
                          r"fifa|world-cup|super-bowl|stanley-cup|world-series|la-liga|serie-a|"
                          r"bundesliga|ligue-1|ufc|boxing|tennis|wimbledon|us-open|french-open|"
                          r"australian-open|f1|formula-1|grand-prix|golf|masters|pga|nascar|"
                          r"olympic|mvp|heisman|cy-young|ballon-dor|top-scorer|champion|playoffs|"
                          r"draft|esports|lol-|cs2-|dota|valorant|cricket|ipl|vs-|-vs-)")


def classify(slug, event_slug="", title=""):
    s = (slug or "").lower()
    e = (event_slug or "").lower()
    t = (title or "").lower().replace(" ", "-")
    blob = f"{s} {e} {t}"
    if SPORT_PREFIX.match(s) or SPORT_PREFIX.match(e):
        return "sports"
    # crypto short windows
    if re.search(COINS + r"-updown-5m", blob) or re.search(r"up-or-down.*5-?min", blob):
        return "crypto_5m"
    if re.search(COINS + r"-updown-15m", blob) or re.search(r"up-or-down.*15-?min", blob):
        return "crypto_15m"
    if re.search(COINS + r"-updown-4h", blob) or re.search(r"up-or-down.*4-?h", blob):
        return "crypto_4h"
    if re.search(COINS + r"-updown-1h", blob) or (
            re.search(COINS + r".*up-or-down", blob) and re.search(r"\d{1,2}(am|pm)-et", blob)):
        return "crypto_1h"
    if re.search(COINS + r".*up-or-down", blob):
        return "crypto_daily_ud"
    if re.search(COINS, blob) and re.search(
            r"(above|below|price-|hit|reach|dip-to|between|"
            r"-\d+k|all-time-high|ath|close)", blob):
        # daily-or-shorter ladders name a single day (or an hour); long ones name a month/week/year
        if re.search(r"(in-(january|february|march|april|may|june|july|august|september|october|"
                     r"november|december)|in-20\d\d|before-20\d\d|by-|wen|-\d+-\d+-20\d\d$|"
                     r"(january|february|march|april|may|june|july|august|september|october|november|"
                     r"december)-\d+-\d+-20\d\d|week|all-time-high)", s or e):
            return "crypto_level_long"
        return "crypto_level"
    if LEAGUE.search(blob) and not re.search(r"temperature", blob):
        return "sports"
    if WEATHER.search(blob):
        return "weather"
    if COMMODITY.search(blob):
        return "commodity"
    if ECON.search(blob):
        return "econ"
    if CORP.search(blob):
        return "corporate"
    if FINANCE.search(blob):
        return "finance"
    if SPORT_PREFIX.match(s) or SPORT_PREFIX.match(e) or SPORTS_WORDS.search(blob):
        return "sports"
    if POLITICS.search(blob):
        return "politics"
    if re.search(COINS, blob):
        return "crypto_other"
    return "other"


# Families with a tradable twin for the owner (Kalshi open categories or Polymarket US)
TWIN = {
    "crypto_15m": "Kalshi KXBTC15M/KXETH15M (+SOL/XRP/DOGE 15m); PM US BTC 15m",
    "crypto_1h": "PM US BTC 1h up/down; Kalshi hourly directional (KXSOLD/KXBNBD...) and KXBTCD strikes",
    "crypto_level_long": "Kalshi KXBTCMAXW/KXBTCMAXY-type max/min series (weekly/monthly/annual)",
    "crypto_level": "Kalshi KXBTCD/KXETHD hourly above/below, KXBTC/KXETH range, BTCD/ETHD daily; PM US BTC hourly above",
    "weather": "Kalshi KXHIGH*/KXLOW* daily (US + many intl cities) -- station/city must match",
    "commodity": "Kalshi KXGOLDD/KXWTI/KXSILVERD/KXNATGASD...",
    "finance": "Kalshi Financials (KXINX/KXINXU S&P, KXNASDAQ100...), only for index-type markets",
    "econ": "Kalshi Economics (KXFED, KXCPI, KXPAYROLLS...) -- Economics not in owner's listed open set; verify",
    "sports": "Polymarket US sports (thin books); Kalshi sports BLOCKED",
}
