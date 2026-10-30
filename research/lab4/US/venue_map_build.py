"""Venue map for the Polymarket US desk: what it trades, and whether polymarket.com history exists for it.

Research only (no key, no order, no network here: every input is a file fetched earlier from PUBLIC endpoints).
Inputs (``$CLAUDE_SCRATCHPAD`` by default, the same scratch area as the rest of lab 4):

* ``venue_dl/ev_20261010/{desk,window}_NN.json``  gateway ``/events?categories=sports`` pages, 2026-10-10 18:18 UTC:
  ``desk`` = the desk's own query (start in the last 12 h .. now + 5 min, 5 pages), ``window`` = the same widened to
  now + 24 h (live now plus scheduled in the next day).
* ``venue_dl/books*.jsonl``  gateway ``/markets/{slug}/book`` stats (shares and dollars traded over the market's life,
  high / low price, settlement) for the real and paper bets, the 2026-10-09 snapshot and the markets live now.
* ``lab4/us/{markets.json,settlements.json,bbo/2026-10-09.csv}``  the lab 4 recorder's snapshot of 2026-10-09.
* ``desk/history.json``  the desk's state and receipts (``/api/polydesk``), 2026-10-10 17:50 UTC.
* ``lab4/markets.parquet``, ``lab4/p6_meta.parquet``, ``lab4/manifest.json``  the polymarket.com history (markets
  with >= $20,000 volume closed 2026-07-01 .. 2026-10-09; game facts; tape sizes).

Output: ``research/lab4/US/venue_map.json`` (prefix -> league, sport, history counts, venue readings, flags, notes)
and the tables printed for ``venue_map.md``.

    python research/lab4/US/venue_map_build.py
"""

from __future__ import annotations

import csv
import glob
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "P6"))
from sports import sport_of  # lab 4's fixed sport map (Amendment 5)

SCRATCH = Path(
    os.environ.get(
        "CLAUDE_SCRATCHPAD",
        "/tmp/claude-0/-home-user-Claude/05bcdce0-3f75-5784-bd4b-6b2d4ca643ba/scratchpad",
    )
)
EV_DIR = SCRATCH / "venue_dl" / "ev_20261010"
US_SNAP = SCRATCH / "lab4" / "us"
HIST = SCRATCH / "lab4"
DESK = SCRATCH / "desk" / "history.json"
OUT = HERE / "venue_map.json"

THETA, MAX_SPREAD, MAX_PRICE, US_TAKER = 0.97, 0.03, 0.999, 0.0695
WINNER_V2 = ("SPORTS_MARKET_TYPE_MONEYLINE", "SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME")
NOT_LIVE_PERIODS = {
    "NS",
    "",
    "CAN",
    "SUS",
    "PST",
    "FT",
    "AOT",
    "FINAL",
    "ENDED",
}  # polydesk.NOT_LIVE_PERIODS
SPORTS_CAP = 150
TRAIN_END = datetime(2026, 8, 15, 23, 59, 59, tzinfo=UTC).timestamp()
VAL_END = datetime(2026, 9, 15, 23, 59, 59, tzinfo=UTC).timestamp()
TEST_END = datetime(2026, 10, 8, 23, 59, 59, tzinfo=UTC).timestamp()
MIN_FILLS = 50
NON_SPORTS = ("crypto", "weather")
CURRENT_RULE = "2026-10-09b|t0.970|h1|s0.03"  # polydesk.rule_id() of the rule live since 2026-10-09 evening

# --------------------------------------------------------------------------------------------- the slug prefixes
#: The first word of a Polymarket US slug says what kind of contract it is (read off the gateway's own
#: ``marketType`` / ``sportsMarketTypeV2`` for every market listed on 2026-10-10).
PREFIXES: dict[str, str] = {
    "aec": "two-way game winner (moneyline: either team / player); sportsMarketTypeV2 MONEYLINE - the desk buys these",
    "atc": "a YES/NO team contract: in soccer and e-soccer the three legs of the 3-way result (home win / draw / away "
    "win; DRAWABLE_OUTCOME - the desk buys these), elsewhere props such as 'wins the 4th quarter' (PROP - not bought)",
    "asc": "spread (handicap) contracts (SPREAD) - not bought",
    "tsc": "totals, over / under (TOTAL) - not bought",
    "astatc": "player and game stat props (PROP) - not bought",
    "tec": "futures: tournament / race winner (FUTURE) - not bought",
    "arankc": "futures: finishing position, e.g. top-3 (FUTURE) - not bought",
    "aachc": "futures: achievement, e.g. fastest lap (FUTURE) - not bought",
    "cpc": "crypto price contracts (BTC up/down, above / range at an hour or a day) - non-sports, bought in their "
    "last hour",
    "tc": "weather contracts (city high-temperature brackets) - non-sports, bought in their last hour",
}

# ----------------------------------------------------------------------------------------------- the league codes
# code -> (league, sport, polymarket.com history codes, title filter for those codes or None, background tags)
# Background tags are what is publicly known about the KIND of competition, not something our data showed:
#   made-for-betting: a league run around the clock for betting and streaming (Setka Cup, Czech Liga Pro,
#     eBattles e-soccer, the 3x3 "BSKT Cup", MODUS darts);
#   low-tier tennis: the ITF World Tennis Tour (M15-M25 / W15-W100) and the UTR Pro Tour, where the tennis
#     integrity agency's sanctions concentrate;
#   youth/amateur/low tier: U20/U23, college, regional and third-tier-or-lower football.
MB, LT, YT = "made-for-betting", "low-tier tennis", "youth/amateur/low-tier"
L: dict[str, tuple[str, str, list[str], str | None, list[str]]] = {
    # tennis
    "atp": ("ATP Tour and ATP Challenger, men's singles", "tennis", ["atp"], None, []),
    "wta": ("WTA Tour (incl. WTA 125), women's singles", "tennis", ["wta"], None, []),
    "atpdb": ("ATP men's doubles", "tennis", [], None, []),
    "wtadb": ("WTA women's doubles", "tennis", [], None, []),
    "itfme": (
        "ITF World Tennis Tour, men (M15/M25)",
        "tennis",
        ["itf"],
        r"\bM(?:15|25)\b|ITF MEN|\bmen'?s\b",
        [LT],
    ),
    "itfwo": (
        "ITF World Tennis Tour, women (W15-W100)",
        "tennis",
        ["itf"],
        r"\bW(?:15|35|50|75|100)\b|ITF WOMEN|women",
        [LT],
    ),
    "utr": ("UTR Pro Tennis Tour", "tennis", [], None, [LT]),
    # table tennis
    "setkameua": ("Setka Cup Ukraine, men", "table tennis", ["setkameua"], None, [MB]),
    "setkawoua": ("Setka Cup Ukraine, women", "table tennis", [], None, [MB]),
    "setkamecz": ("Setka Cup Czechia, men", "table tennis", ["setkamecz"], None, [MB]),
    "setkamemd": ("Setka Cup Moldova, men", "table tennis", [], None, [MB]),
    "czechligapro": ("Czech Liga Pro (table tennis)", "table tennis", [], None, [MB]),
    "wtt": (
        "World Table Tennis (WTT) tour",
        "table tennis",
        ["wttwom", "wttmen", "wtt"],
        None,
        [],
    ),
    # e-soccer (EA FC video-game matches between players, a few minutes each)
    "ebfsa": ("eBattles e-soccer: Serie A", "e-soccer", [], None, [MB]),
    "ebfpl": ("eBattles e-soccer: Premier League", "e-soccer", [], None, [MB]),
    "ebfwca": ("eBattles e-soccer: World Cup A", "e-soccer", [], None, [MB]),
    "ebfwcb": ("eBattles e-soccer: World Cup B", "e-soccer", [], None, [MB]),
    "ebfcwc": ("eBattles e-soccer: Club World Cup", "e-soccer", [], None, [MB]),
    # esports
    "cs2": ("Counter-Strike 2 (all tiers)", "esports", ["cs2"], None, []),
    "lol": ("League of Legends", "esports", ["lol"], None, []),
    "dota2": ("Dota 2", "esports", ["dota2"], None, []),
    "valorant": ("Valorant", "esports", ["val"], None, []),
    "r6": ("Rainbow Six Siege", "esports", ["r6siege"], None, []),
    "ow": ("Overwatch", "esports", [], None, []),
    # ice hockey
    "nhl": ("NHL", "ice hockey", ["nhl"], None, []),
    "ahl": ("AHL (North American minor league)", "ice hockey", [], None, []),
    "khl": ("KHL (Russia)", "ice hockey", ["khl"], None, []),
    "shl": ("SHL (Sweden)", "ice hockey", ["shl"], None, []),
    "del": ("DEL, Deutsche Eishockey Liga (Germany)", "ice hockey", [], None, []),
    "snhl": ("National League (Switzerland)", "ice hockey", [], None, []),
    "liiga": ("Liiga (Finland)", "ice hockey", [], None, []),
    "cehl": ("Czech Extraliga", "ice hockey", [], None, []),
    # basketball
    "nba": ("NBA", "basketball", ["nba"], None, []),
    "wnba": ("WNBA", "basketball", ["wnba"], None, []),
    "eurolg": ("EuroLeague", "basketball", ["euroleague"], None, []),
    "acb": ("Liga ACB (Spain)", "basketball", ["bkligend"], None, []),
    "lba": ("Lega Basket Serie A (Italy)", "basketball", ["bkseriea"], None, []),
    "bbl": ("Basketball Bundesliga (Germany)", "basketball", ["bkbbl"], None, []),
    "jpbl": ("B.League (Japan)", "basketball", ["bkjpn"], None, []),
    "kbl": ("KBL (South Korea)", "basketball", ["bkkbl"], None, []),
    "nbl": ("NBL (Australia)", "basketball", ["bknbl"], None, []),
    "vtb": ("VTB United League", "basketball", [], None, []),
    "aba": ("ABA League (Adriatic)", "basketball", [], None, []),
    "bsl": ("Basketbol Super Ligi (Turkey)", "basketball", [], None, []),
    "lnb": ("LNB Pro A / Betclic Elite (France)", "basketball", [], None, []),
    "fra2": ("LNB Pro B (France, 2nd tier)", "basketball", [], None, []),
    "ita2": ("Serie A2 (Italy, 2nd tier)", "basketball", [], None, []),
    "gbl": ("Greek Basket League", "basketball", [], None, []),
    "lkl": ("LKL (Lithuania)", "basketball", [], None, []),
    "cznbl": ("NBL (Czechia)", "basketball", [], None, []),
    "svkbl": ("Slovak basketball league", "basketball", [], None, []),
    "slnbl": ("Slovenian basketball league", "basketball", [], None, []),
    "hunbl": ("NB I (Hungary)", "basketball", [], None, []),
    "autbl": ("Basketball Superliga (Austria)", "basketball", [], None, []),
    "denbl": ("Basketligaen (Denmark)", "basketball", [], None, []),
    "koris": ("Korisliiga (Finland)", "basketball", [], None, []),
    "slb": ("Super League Basketball (UK)", "basketball", [], None, []),
    "bskt3x3": (
        "BSKT Cup 3x3 (3-on-3 basketball series)",
        "basketball",
        [],
        None,
        [MB],
    ),
    # baseball
    "mlb": ("MLB", "baseball", ["mlb"], None, []),
    "kbo": ("KBO (South Korea)", "baseball", ["kbo"], None, []),
    "npb": ("NPB (Japan)", "baseball", ["npb"], None, []),
    # american football
    "nfl": ("NFL", "american football", ["nfl"], None, []),
    "cfb": (
        "College football (NCAA FBS and FCS)",
        "american football",
        ["cfb"],
        None,
        [],
    ),
    # combat
    "ufc": ("UFC", "mma", ["ufc"], None, []),
    "boxing": ("Boxing", "boxing", ["boxing", "zuffa"], None, []),
    # cricket
    "t20icr": (
        "Men's T20 internationals",
        "cricket",
        ["crint"],
        r"^(?!.*Women).*T20",
        [],
    ),
    "t20iwcr": (
        "Women's T20 internationals",
        "cricket",
        ["crint"],
        r"^(?=.*Women).*T20",
        [],
    ),
    "odicr": (
        "Men's ODIs (incl. A-team tours)",
        "cricket",
        ["crint"],
        r"^(?!.*Women).*ODI",
        [],
    ),
    "odiwcr": ("Women's ODIs", "cricket", ["crint"], r"^(?=.*Women).*ODI", []),
    "testcr": ("Test cricket", "cricket", ["crint"], r"\bTest", []),
    # darts, rugby, pickleball
    "pdcdarts": ("PDC darts", "darts", [], None, []),
    "modus": ("MODUS Super Series (online darts)", "darts", [], None, [MB]),
    "prem": ("Premiership Rugby (England)", "rugby", [], None, []),
    "urc": ("United Rugby Championship", "rugby", [], None, []),
    "top14": ("Top 14 (France)", "rugby", [], None, []),
    "ppa": ("PPA Tour (pickleball)", "pickleball", [], None, []),
    # soccer: top flights
    "epl": ("Premier League (England)", "soccer", ["epl"], None, []),
    "lal": ("La Liga (Spain)", "soccer", ["lal"], None, []),
    "sea": ("Serie A (Italy)", "soccer", ["sea"], None, []),
    "bun": ("Bundesliga (Germany)", "soccer", ["bun"], None, []),
    "lg1": ("Ligue 1 (France)", "soccer", ["fl1"], None, []),
    "ere": ("Eredivisie (Netherlands)", "soccer", ["ere"], None, []),
    "ligpor": ("Liga Portugal", "soccer", ["por"], None, []),
    "bel1": ("Belgian Pro League", "soccer", ["bel1"], None, []),
    "scp": ("Scottish Premiership", "soccer", ["scop"], None, []),
    "tsl": ("Super Lig (Turkey)", "soccer", ["tur"], None, []),
    "rpl": ("Russian Premier League", "soccer", ["rus"], None, []),
    "ekst": ("Ekstraklasa (Poland)", "soccer", ["pol"], None, []),
    "flc": ("Czech First League (Fortuna / Chance Liga)", "soccer", ["cze1"], None, []),
    "hnl": ("HNL (Croatia)", "soccer", ["hr1"], None, []),
    "slr": ("SuperLiga (Romania)", "soccer", ["rou1"], None, []),
    "grsl": ("Super League Greece", "soccer", ["grc", "gre1"], None, []),
    "atbl": ("Austrian Bundesliga", "soccer", ["aut"], None, []),
    "swsl": ("Swiss Super League", "soccer", ["sui"], None, []),
    "sld": ("Superliga (Denmark)", "soccer", ["den"], None, []),
    "alsv": ("Allsvenskan (Sweden)", "soccer", ["swe"], None, []),
    "els": ("Eliteserien (Norway)", "soccer", ["nor"], None, []),
    "vkl": ("Veikkausliiga (Finland)", "soccer", ["fin1"], None, []),
    "nb1": ("NB I (Hungary)", "soccer", ["hun"], None, []),
    "nls": ("Nike Liga (Slovakia)", "soccer", ["svk1"], None, []),
    "svnp": ("PrvaLiga (Slovenia)", "soccer", ["slo"], None, []),
    "pvl": ("Parva Liga (Bulgaria)", "soccer", ["bul"], None, []),
    "cyp1": ("Cyprus First Division", "soccer", [], None, []),
    "isl1": ("Besta deild (Iceland)", "soccer", [], None, []),
    "spl": ("Saudi Pro League", "soccer", ["spl"], None, []),
    "egpl": ("Egyptian Premier League", "soccer", ["egy1"], None, []),
    "btla": ("Botola Pro (Morocco)", "soccer", ["mar1"], None, []),
    "ghpl": ("Ghana Premier League", "soccer", [], None, []),
    "ngnpfl": ("Nigeria NPFL", "soccer", [], None, []),
    "uzb1": ("Uzbekistan Superliga", "soccer", ["uzb1"], None, []),
    "j1": ("J1 League (Japan)", "soccer", ["jap"], None, []),
    "kl1": ("K League 1 (South Korea)", "soccer", ["kor"], None, []),
    "csl": ("Chinese Super League", "soccer", ["chi"], None, []),
    "idnsl": ("Indonesia Super League", "soccer", ["idn1"], None, []),
    "thai1": ("Thai League 1", "soccer", ["tha1"], None, []),
    "mls": ("MLS", "soccer", ["mls"], None, []),
    "lmx": ("Liga MX", "soccer", ["mex"], None, []),
    "lpc": ("Liga Promerica (Costa Rica)", "soccer", ["fpd"], None, []),
    "lng": ("Liga Nacional (Guatemala)", "soccer", ["gtm"], None, []),
    "bra": ("Brasileirao Serie A", "soccer", ["bra"], None, []),
    "lpa": ("Liga Profesional (Argentina)", "soccer", ["arg"], None, []),
    "pdc": ("Primera Division (Chile)", "soccer", ["chi1"], None, []),
    "lco": ("Primera A (Colombia)", "soccer", ["col1"], None, []),
    "uru1": ("Primera Division (Uruguay)", "soccer", ["uru1"], None, []),
    "ecu1": ("LigaPro (Ecuador)", "soccer", ["ecu1"], None, []),
    "pl1": ("Liga 1 (Peru)", "soccer", ["per1"], None, []),
    "lpb": ("Division Profesional (Bolivia)", "soccer", ["bol1"], None, []),
    "par1": ("Primera Division (Paraguay)", "soccer", [], None, []),
    "irlp": ("League of Ireland Premier Division", "soccer", ["irl1"], None, []),
    "uwwcq": ("UEFA Women's World Cup qualifying", "soccer", [], None, []),
    # soccer: second tiers
    "eflch": ("EFL Championship (England)", "soccer", ["elc"], None, []),
    "lal2": ("LaLiga 2 (Spain)", "soccer", ["es2"], None, []),
    "srb": (
        "Serie B (ITALY - not Serbia; polymarket.com 'srb' is Serbia)",
        "soccer",
        ["itsb"],
        None,
        [],
    ),
    "bun2": ("2. Bundesliga (Germany)", "soccer", ["bl2"], None, []),
    "lig2": ("Ligue 2 (France)", "soccer", ["fr2"], None, []),
    "tff1": ("TFF 1. Lig (Turkey)", "soccer", ["tur2"], None, []),
    "j2": ("J2 League (Japan)", "soccer", ["ja2"], None, []),
    "nor1": ("OBOS-ligaen (Norway)", "soccer", ["nor2"], None, []),
    "swe2": ("Superettan (Sweden)", "soccer", ["swe2"], None, []),
    "swcl": ("Challenge League (Switzerland)", "soccer", [], None, []),
    "fnl": ("Czech National Football League (2nd tier)", "soccer", [], None, []),
    "den1": ("Danish 1st Division", "soccer", [], None, []),
    "ykk": ("Ykkosliiga (Finland, 2nd tier)", "soccer", [], None, []),
    "uslc": ("USL Championship (USA, 2nd tier)", "soccer", ["uslc"], None, []),
    "lexp": ("Liga de Expansion MX (2nd tier)", "soccer", [], None, []),
    "arg2": ("Primera Nacional (Argentina, 2nd tier)", "soccer", ["argpn"], None, []),
    "brc": ("Brasileirao Serie C (3rd tier)", "soccer", ["bra3"], None, [YT]),
    "engnl": ("National League (England, 5th tier)", "soccer", ["enl"], None, []),
    "irl1": (
        "League of Ireland First Division (polymarket.com 'irl1' is the PREMIER Division)",
        "soccer",
        [],
        None,
        [],
    ),
    "par2": ("Division Intermedia (Paraguay, 2nd tier)", "soccer", [], None, [YT]),
    "ven2": ("Segunda Division (Venezuela)", "soccer", [], None, [YT]),
    "gtasc": (
        "Primera Division de Ascenso (Guatemala, 2nd tier)",
        "soccer",
        [],
        None,
        [YT],
    ),
    "mne2": ("Second League (Montenegro)", "soccer", [], None, [YT]),
    "svk2": ("2. Liga (Slovakia)", "soccer", [], None, [YT]),
    # soccer: third tier and below, youth, women's regional, college
    "serca": ("Serie C Girone A (Italy, 3rd tier)", "soccer", [], None, [YT]),
    "sercb": ("Serie C Girone B (Italy, 3rd tier)", "soccer", [], None, [YT]),
    "sercc": ("Serie C Girone C (Italy, 3rd tier)", "soccer", [], None, [YT]),
    "be1acff": ("Belgian Nationale 1 ACFF (3rd tier)", "soccer", [], None, [YT]),
    "be1vv": ("Belgian Nationale 1 VV (3rd tier)", "soccer", [], None, [YT]),
    "ch1cl": ("Swiss 1. Liga Classic (4th tier)", "soccer", [], None, [YT]),
    "ilaln": ("Liga Alef North (Israel, 3rd tier)", "soccer", [], None, [YT]),
    "caru20": ("Carioca U20 (Brazil, youth)", "soccer", [], None, [YT]),
    "peu20": ("Pernambucano U20 (Brazil, youth)", "soccer", [], None, [YT]),
    "gaub": ("Gaucho Serie B U23 (Brazil, youth)", "soccer", [], None, [YT]),
    "minw": ("Campeonato Mineiro, women (Brazil, state)", "soccer", [], None, [YT]),
    "ncaaws": ("NCAA women's soccer (US college)", "soccer", [], None, [YT]),
    "ncaams": ("NCAA men's soccer (US college)", "soccer", [], None, [YT]),
    # non-sports
    "btc": ("Bitcoin price contracts", "crypto", ["btc", "bitcoin"], None, []),
    "temp": (
        "City high-temperature brackets",
        "weather",
        ["highest"],
        r"(?i)highest temperature",
        [],
    ),
}
#: The four leagues where the desk's codes and polymarket.com's codes collide or differ in a misleading way.
CODE_TRAPS = {
    "srb": "US 'srb' = Italian Serie B; polymarket.com 'srb' = Serbian SuperLiga. History is read from 'itsb'.",
    "irl1": "US 'irl1' = League of Ireland First Division; polymarket.com 'irl1' = the Premier Division (US 'irlp').",
    "pdc": "US 'pdc' = Chilean Primera Division (soccer); US 'pdcdarts' = PDC darts.",
    "bbl": "US 'bbl' = German basketball (tags say basketball); not cricket's Big Bash League.",
}


def ts_iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d %H:%M")


def parse_iso(v):
    if not v or not isinstance(v, str):
        return None
    try:
        return datetime.fromisoformat(
            v
        ).timestamp()  # Python 3.11+ reads the trailing Z
    except ValueError:
        return None


def num(v):
    if isinstance(v, dict):
        v = v.get("value")
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def league_of_slug(slug: str) -> str:
    parts = slug.split("-")
    return parts[1] if len(parts) > 1 else ""


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 4) if xs else None


# ------------------------------------------------------------------------------------------------- gateway pages
def load_pages(name: str):
    events, markets = {}, []
    for f in sorted(glob.glob(str(EV_DIR / f"{name}_*.json"))):
        doc = json.loads(Path(f).read_text())
        for ev in doc["events"]:
            if ev["slug"] in events:
                continue
            events[ev["slug"]] = {
                "start": parse_iso(ev.get("startTime") or ev.get("startDate")),
                "period": str(ev.get("period") or "").upper(),
                "live": ev.get("live"),
                "ended": ev.get("ended"),
                "tags": [
                    str(t.get("slug") if isinstance(t, dict) else t).lower()
                    for t in ev.get("tags") or []
                ],
                "series": ev.get("seriesSlug"),
            }
            for m in ev.get("markets") or []:
                markets.append(
                    {
                        "event": ev["slug"],
                        "slug": m["slug"],
                        "prefix": m["slug"].split("-", 1)[0],
                        "league": league_of_slug(m["slug"]),
                        "smt2": m.get("sportsMarketTypeV2"),
                        "kind": str(
                            m.get("sportsMarketTypeV2") or m.get("marketType") or ""
                        ).upper(),
                        "closed": m.get("closed"),
                        "bid": num(m.get("bestBidQuote")),
                        "ask": num(m.get("bestAskQuote")),
                    }
                )
    return events, markets


def desk_list(events, markets, now):
    """polydesk.live_sports_markets on the saved pages: started, live period, winner kind, newest SPORTS_CAP."""
    out = []
    for m in markets:
        e = events[m["event"]]
        if e["start"] is None or e["start"] > now or e["period"] in NOT_LIVE_PERIODS:
            continue
        if (
            not any(w in m["kind"] for w in ("MONEYLINE", "DRAWABLE_OUTCOME"))
            or m["closed"]
        ):
            continue
        out.append(dict(m, start=e["start"], period=e["period"]))
    out.sort(key=lambda m: -m["start"])
    return out[:SPORTS_CAP], out[SPORTS_CAP:]


# ------------------------------------------------------------------------------------------- polymarket.com history
def history_counts():
    df = pd.read_parquet(HIST / "markets.parquet")
    meta = pd.read_parquet(HIST / "p6_meta.parquet")
    manifest = json.loads(Path(HIST / "manifest.json").read_text())["markets"]
    df["code"] = df["event_slug"].fillna("").str.split("-").str[0].str.lower()
    df["fills"] = df["id"].map(lambda i: (manifest.get(str(i)) or {}).get("rows", 0))
    df = df.merge(
        meta[
            ["id", "sports_market_type", "event_start", "event_finished", "description"]
        ],
        on="id",
        how="left",
    )
    df["text"] = (
        df["event_title"].fillna("")
        + " || "
        + df["description"].fillna("").str.slice(0, 300)
    )
    df["moneyline"] = df["sports_market_type"].eq("moneyline")
    df["has_end"] = (
        df["event_finished"].notna()
        & df["event_start"].notna()
        & (df["event_start"] < df["event_finished"])
        & (df["event_finished"] <= df["closed_time"])
    )
    df["split"] = pd.cut(
        df["closed_time"],
        [0, TRAIN_END, VAL_END, TEST_END, 1e12],
        labels=["TRAIN", "VAL", "TEST", "after"],
    ).astype(str)
    out = {}
    for code, (_name, _sport, com, rx, _tags) in L.items():
        if not com:
            out[code] = None
            continue
        sel = df[df["code"].isin(com)]
        if rx:
            sel = sel[sel["text"].str.contains(re.compile(rx), regex=True)]
        ml = sel[sel["moneyline"]]
        mlu = ml[ml["fills"] >= MIN_FILLS]

        def games(x):
            return int(x["event_slug"].nunique())

        out[code] = {
            "markets_all_types": len(sel),
            "events": games(sel),
            "game_winner_markets": len(ml),
            "game_winner_games": games(ml),
            "game_winner_games_50fills": games(mlu),
            "games_50fills_with_recorded_end": games(mlu[mlu["has_end"]]),
            "by_split_games_50fills_with_end": {
                s: games(mlu[(mlu["split"] == s) & mlu["has_end"]])
                for s in ("TRAIN", "VAL", "TEST")
            },
            "by_split_games_50fills": {
                s: games(mlu[mlu["split"] == s]) for s in ("TRAIN", "VAL", "TEST")
            },
            "example_titles": sel.drop_duplicates("event_slug")["event_title"]
            .head(3)
            .tolist(),
        }
    return out


#: "Thin venue market": the median settled winner market of the league traded less than this many dollars over its
#: whole life on Polymarket US (a plain round cut, chosen after a few leagues' numbers had been seen: a description of
#: the venue, not a test; under it a $1 ticket is more than 1/1000 of all that changed hands and one stale order can
#: set the printed price).
THIN_DOLLARS = 1000.0


def history_level(h) -> str:
    """How far polymarket.com history can judge the league's game-winner markets (lab 4 rules: >= 50 fills; P6 needs
    >= 30 TRAIN games with a recorded end for a sport):
    none (no game with a tape) / thin (1-29 games) / no recorded end (>= 30 games, none with a recorded end: P6 can
    only ever BLOCK on those) / some (>= 30 games, < 30 in TRAIN with a recorded end) / judgeable (>= 30 in TRAIN)."""
    if not h or h["game_winner_games_50fills"] == 0:
        return "none"
    if h["game_winner_games_50fills"] < 30:
        return "thin"
    if h["games_50fills_with_recorded_end"] == 0:
        return "no recorded end"
    if h["by_split_games_50fills_with_end"]["TRAIN"] < 30:
        return "some"
    return "judgeable"


# ------------------------------------------------------------------------------------------------ the desk's record
def desk_record():
    d = json.loads(Path(DESK).read_text())
    rec = d["receipts"]
    buys = {}
    for a in rec:
        if a["kind"] in ("polydesk_order_filled", "polydesk_position_adopted"):
            buys.setdefault(a["payload"]["slug"], a)
    real = defaultdict(
        lambda: {
            "settled": 0,
            "won": 0,
            "pnl_usd": 0.0,
            "hours_utc": Counter(),
            "adopted": 0,
        }
    )
    for a in rec:
        if a["kind"] != "polydesk_settled":
            continue
        slug = a["payload"]["slug"]
        r = real[league_of_slug(slug)]
        r["settled"] += 1
        r["won"] += int(a["payload"]["pnl_usd"] > 0)
        r["pnl_usd"] += a["payload"]["pnl_usd"]
        b = buys.get(slug)
        if b:
            r["hours_utc"][datetime.fromtimestamp(b["ts"], UTC).hour] += 1
            r["adopted"] += int(b["kind"] == "polydesk_position_adopted")
    # paper rows kept in the state (the newest 200 closed rows, paper and real): the CURRENT rule apart from older
    paper = defaultdict(
        lambda: {
            "current_rule": {
                "settled": 0,
                "won": 0,
                "pnl_usd": 0.0,
                "hours_utc": Counter(),
                # paper may buy the NO side ("short", at 1 - bid); real money buys the YES side only
                "sides": Counter(),
            },
            "older_rules": {"settled": 0, "won": 0, "pnl_usd": 0.0},
        }
    )
    for c in d["state"]["closed"]:
        if c.get("live"):
            continue
        p = paper[league_of_slug(c["slug"])][
            "current_rule" if c.get("rule") == CURRENT_RULE else "older_rules"
        ]
        p["settled"] += 1
        p["won"] += int(bool(c.get("won")))
        p["pnl_usd"] += float(c.get("pnl_usd") or 0)
        if c.get("t_in") and "hours_utc" in p:
            p["hours_utc"][datetime.fromtimestamp(c["t_in"], UTC).hour] += 1
        if "sides" in p:
            p["sides"][str(c.get("side") or "long")] += 1
    return real, paper, d


# ------------------------------------------------------------------------------------- the 2026-10-09 venue snapshot
def snapshot():
    mk = json.loads(Path(US_SNAP / "markets.json").read_text())
    st = json.loads(Path(US_SNAP / "settlements.json").read_text())
    rows = defaultdict(list)
    with open(US_SNAP / "bbo" / "2026-10-09.csv") as fh:
        for r in csv.DictReader(fh):
            if r["category"] != "sports":
                continue
            rows[r["slug"]].append(r)
    spread = defaultdict(list)
    one_sided = Counter()
    polls = Counter()
    shadow = defaultdict(
        lambda: {
            "bought": 0,
            "settled": 0,
            "won": 0,
            "net": 0.0,
            "hours_utc": Counter(),
        }
    )
    legs_by_event_ts = defaultdict(lambda: defaultdict(list))
    for slug, rs in rows.items():
        m = mk.get(slug) or {}
        lg = league_of_slug(slug)
        start = m.get("game_start")
        bought = False
        for r in rs:
            t = float(r["ts"])
            bid = float(r["best_bid"]) if r["best_bid"] else None
            ask = float(r["best_ask"]) if r["best_ask"] else None
            in_play = start is None or t >= start
            if slug.startswith("atc-") and m.get("event"):
                legs_by_event_ts[m["event"]][t].append((slug, bid, ask, in_play))
            if not in_play:
                continue
            polls[lg] += 1
            if bid is None or ask is None:
                one_sided[lg] += 1
            else:
                spread[lg].append(ask - bid)
            if (
                not bought
                and ask is not None
                and bid is not None
                and THETA <= ask <= MAX_PRICE
                and ask - bid <= MAX_SPREAD + 1e-9
            ):
                bought = True
                s = shadow[lg]
                s["bought"] += 1
                s["hours_utc"][datetime.fromtimestamp(t, UTC).hour] += 1
                settle = (st.get(slug) or {}).get("settlement")
                if settle is not None:
                    s["settled"] += 1
                    s["won"] += int(settle >= 0.5)
                    s["net"] += settle - ask - US_TAKER * ask * (1 - ask)
    # 3-way games whose book cannot be honest at some poll. A game has three YES/NO legs (home, draw, away) and
    # exactly one pays $1, so the three YES bids can never sum to more than $1 in a sane book:
    #   crossed     - the three best bids sum to more than 1.02 (any poll, before or during the game);
    #   two_hot     - in play, two or three legs at once show a near-certain price (ask >= 0.97 or bid >= 0.96);
    #   two_buyable - in play, two or three legs at once pass the desk's own buy test (ask 0.97-0.999, spread <= 0.03).
    broken = {
        "crossed": defaultdict(set),
        "two_hot": defaultdict(set),
        "two_buyable": defaultdict(set),
    }
    three_way_events = Counter()
    for event, by_ts in legs_by_event_ts.items():
        lg = league_of_slug(next(iter(by_ts.values()))[0][0])
        three_way_events[lg] += 1
        for legs in by_ts.values():
            bids = [b for _s, b, _a, _p in legs]
            if len(legs) >= 3 and all(b is not None for b in bids) and sum(bids) > 1.02:
                broken["crossed"][lg].add(event)
            live = [(b, a) for _s, b, a, p in legs if p]
            hot = sum(
                1
                for b, a in live
                if (a is not None and a >= THETA) or (b is not None and b >= 0.96)
            )
            buyable = sum(
                1
                for b, a in live
                if a is not None
                and b is not None
                and THETA <= a <= MAX_PRICE
                and a - b <= MAX_SPREAD + 1e-9
            )
            if hot >= 2:
                broken["two_hot"][lg].add(event)
            if buyable >= 2:
                broken["two_buyable"][lg].add(event)
    counts = Counter(
        league_of_slug(s) for s, v in mk.items() if v.get("category") == "sports"
    )
    return {
        "markets": counts,
        "median_spread": {lg: med(v) for lg, v in spread.items()},
        "one_sided_share": {
            lg: round(one_sided[lg] / polls[lg], 3) for lg in polls if polls[lg]
        },
        "shadow": shadow,
        "three_way_events": three_way_events,
        "broken": {
            k: {lg: sorted(v) for lg, v in d.items()} for k, d in broken.items()
        },
        "span": (
            min(float(r["ts"]) for rs in rows.values() for r in rs),
            max(float(r["ts"]) for rs in rows.values() for r in rs),
        ),
    }


def books():
    out = {}
    for f in sorted(glob.glob(str(SCRATCH / "venue_dl" / "books*.jsonl"))):
        for line in Path(f).read_text().splitlines():
            r = json.loads(line)
            if r.get("stats") is not None:
                out[r["slug"]] = r
    return out


# --------------------------------------------------------------------------------------------------------- build
def main() -> None:
    meta = json.loads(Path(EV_DIR / "meta.json").read_text())
    now = meta["now"]
    ev_w, mk_w = load_pages("window")
    ev_d, mk_d = load_pages("desk")
    kept, dropped = desk_list(ev_d, mk_d, now)
    winners_w = [m for m in mk_w if m["smt2"] in WINNER_V2]
    hist = history_counts()
    real, paper, desk = desk_record()
    snap = snapshot()
    bk = books()
    prefixes_seen = Counter(m["prefix"] for m in mk_w)
    # the slug prefixes each league's BOUGHT-KIND markets carry: winner markets listed now, the 2026-10-09 snapshot
    # (winner markets and the non-sports ladders), and every slug the desk bought (real or paper)
    prefix_sets: dict[str, set] = defaultdict(set)
    bought_slugs = [
        a["payload"]["slug"]
        for a in desk["receipts"]
        if "slug" in (a.get("payload") or {})
    ]
    bought_slugs += [c["slug"] for c in desk["state"]["closed"]]
    snap_slugs = list(json.loads(Path(US_SNAP / "markets.json").read_text()))
    for m in winners_w:
        prefix_sets[m["league"]].add(m["prefix"])
    for slug in snap_slugs + bought_slugs:
        prefix_sets[league_of_slug(slug)].add(slug.split("-", 1)[0])

    # the same impossible-book test on the one listing fetched now (quotes as printed in the event listing)
    legs_now: dict[str, list] = defaultdict(list)
    for m in winners_w:
        if m["smt2"] == "SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME" and not m["closed"]:
            legs_now[m["event"]].append((m["bid"], m["ask"]))
    crossed_now, hot_now = defaultdict(list), defaultdict(list)
    for event, legs in legs_now.items():
        lg = league_of_slug(next(m["slug"] for m in winners_w if m["event"] == event))
        bids = [b for b, _a in legs]
        if len(legs) >= 3 and all(b is not None for b in bids) and sum(bids) > 1.02:
            crossed_now[lg].append(event)
        if (
            sum(
                1
                for b, a in legs
                if (a is not None and a >= THETA) or (b is not None and b >= 0.96)
            )
            >= 2
        ):
            hot_now[lg].append(event)

    tags_by_league: dict[str, Counter] = defaultdict(Counter)
    for m in winners_w:
        tags_by_league[m["league"]].update(ev_w[m["event"]]["tags"])

    # notional traded over the market's life, settled winner markets only (2026-10-09 snapshot + desk's bets)
    notional = defaultdict(list)
    for slug, r in bk.items():
        stt = r.get("stats") or {}
        if (
            r.get("state") or ""
        ) != "MARKET_STATE_EXPIRED" and "settlementPx" not in stt:
            continue
        notional[league_of_slug(slug)].append(num(stt.get("notionalTraded")))

    leagues = sorted(
        set(L)
        | {m["league"] for m in winners_w}
        | set(snap["markets"])
        | set(real)
        | set(paper)
    )
    out_leagues = {}
    for lg in leagues:
        name, sport, com, rx, tags = L.get(
            lg, ("UNKNOWN - not mapped", "unknown", [], None, [])
        )
        ws = [m for m in winners_w if m["league"] == lg]
        three_way = any(
            m["smt2"] == "SPORTS_MARKET_TYPE_DRAWABLE_OUTCOME" for m in ws
        ) or sport in ("soccer", "e-soccer")
        r = real.get(lg)
        p = paper.get(lg)
        sh = snap["shadow"].get(lg)
        h = hist.get(lg)
        flags = list(tags)
        if three_way:
            flags.append("3-way")
        if any(lg in snap["broken"][k] for k in snap["broken"]):
            flags.append("impossible 3-way book seen 2026-10-09")
        level = (
            history_level(h)
            if sport not in NON_SPORTS
            else "non-sports (lab 4 P4, not this map's question)"
        )
        if level in ("none", "thin") and sport not in NON_SPORTS:
            flags.append(f"{level} history")
        nt = med(notional.get(lg, []))
        if nt is not None and nt < THIN_DOLLARS:
            flags.append("thin venue market")
        sp_now = med(
            [
                m["ask"] - m["bid"]
                for m in kept
                if m["league"] == lg and m["ask"] is not None and m["bid"] is not None
            ]
        )
        rec = {
            "league": name,
            "sport": sport,
            "p6_sport": sport_of(lg, list(tags_by_league.get(lg, {})))
            if sport not in ("crypto", "weather")
            else None,
            "us_slug_prefixes": sorted(prefix_sets.get(lg, ())) or None,
            "three_way": bool(three_way),
            "polymarket_com_codes": com,
            "polymarket_com_title_filter": rx,
            "history_markets": h["markets_all_types"] if h else 0,
            "history_level": level,
            "history": h,
            "venue_now": {
                "winner_markets_next_24h_window": len(ws),
                "games_next_24h_window": len({m["event"] for m in ws}),
                "in_desk_list_now": sum(1 for m in kept if m["league"] == lg),
                "live_but_cut_by_cap_now": sum(1 for m in dropped if m["league"] == lg),
                "median_spread_in_desk_list_now": sp_now,
                "impossible_3way_books_at_fetch": {
                    "crossed": crossed_now.get(lg, []),
                    "two_hot": hot_now.get(lg, []),
                },
            },
            "venue_2026_10_09": {
                "winner_markets_recorded": snap["markets"].get(lg, 0),
                "median_spread_in_play": snap["median_spread"].get(lg),
                "share_of_polls_one_sided": snap["one_sided_share"].get(lg),
                "median_dollars_traded_per_settled_winner_market": nt,
                "n_settled_markets_with_book_stats": len(
                    [x for x in notional.get(lg, []) if x is not None]
                ),
                "would_have_bought_on_recorded_quotes": (
                    {
                        k: (
                            dict(v)
                            if isinstance(v, Counter)
                            else (round(v, 4) if isinstance(v, float) else v)
                        )
                        for k, v in sh.items()
                    }
                    if sh
                    else None
                ),
                "three_way_games_recorded": snap["three_way_events"].get(lg, 0),
                "impossible_3way_books": {
                    k: snap["broken"][k].get(lg, []) for k in snap["broken"]
                },
            },
            "real": (
                {
                    "settled": r["settled"],
                    "won": r["won"],
                    "pnl_usd": round(r["pnl_usd"], 4),
                    "adopted": r["adopted"],
                    "buy_hours_utc": dict(sorted(r["hours_utc"].items())),
                }
                if r
                else None
            ),
            "paper": (
                {
                    "current_rule": {
                        "settled": p["current_rule"]["settled"],
                        "won": p["current_rule"]["won"],
                        "pnl_usd_20usd_tickets": round(p["current_rule"]["pnl_usd"], 4),
                        "sides": dict(p["current_rule"]["sides"]),
                        "buy_hours_utc": dict(
                            sorted(p["current_rule"]["hours_utc"].items())
                        ),
                    },
                    "older_rules": {
                        k: round(v, 4) for k, v in p["older_rules"].items()
                    },
                }
                if p
                else None
            ),
            "flags": flags,
            "notes": CODE_TRAPS.get(lg),
        }
        out_leagues[lg] = rec

    # which sports fill the desk's buys, by UTC hour: real buys, paper buys under the current rule, and what is
    # scheduled to start in the next 24 h (winner markets)
    def sport_code(lg):
        return L.get(lg, ("", "unknown", [], None, []))[1]

    by_hour = {
        "real_buys": defaultdict(Counter),
        "paper_buys_current_rule": defaultdict(Counter),
        "winner_markets_starting_next_24h": defaultdict(Counter),
    }
    for lg, r in real.items():
        for h, n in r["hours_utc"].items():
            by_hour["real_buys"][h][sport_code(lg)] += n
    for lg, p in paper.items():
        for h, n in p["current_rule"]["hours_utc"].items():
            by_hour["paper_buys_current_rule"][h][sport_code(lg)] += n
    for m in winners_w:
        st = ev_w[m["event"]]["start"]
        if st is not None and st >= now:
            by_hour["winner_markets_starting_next_24h"][
                datetime.fromtimestamp(st, UTC).hour
            ][sport_code(m["league"])] += 1
    by_hour = {
        k: {h: dict(c.most_common()) for h, c in sorted(v.items())}
        for k, v in by_hour.items()
    }

    doc = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "sources": {
            "gateway_events_fetched_utc": meta["now_iso"],
            "gateway_window": "sports events started in the last 12 h or starting in the next 24 h, open",
            "desk_record": f"desk/history.json generated {ts_iso(desk['generated_at'])} UTC",
            "venue_snapshot": f"lab4 recorder, {ts_iso(snap['span'][0])} .. {ts_iso(snap['span'][1])} UTC",
            "history": "polymarket.com markets with >= $20,000 volume closed 2026-07-01 .. 2026-10-09 (lab 4 cache)",
        },
        "prefixes": PREFIXES,
        "prefix_counts_next_24h": dict(prefixes_seen.most_common()),
        "desk_list_now": {
            "live_winner_markets": len(kept) + len(dropped),
            "kept": len(kept),
            "cut_by_cap": len(dropped),
            "oldest_kept_started_h_ago": round((now - kept[-1]["start"]) / 3600, 2)
            if kept
            else None,
        },
        "by_hour_utc": by_hour,
        # the lookup the desk can use directly: the first two words of a slug -> what it is
        "by_slug_prefix": {
            f"{pfx}-{lg}": {
                "league_code": lg,
                "league": rec["league"],
                "sport": rec["sport"],
                "three_way": rec["three_way"],
                "history_markets": rec["history_markets"],
                "history_level": rec["history_level"],
                "flags": rec["flags"],
                "notes": rec["notes"],
            }
            for lg, rec in sorted(out_leagues.items())
            for pfx in rec["us_slug_prefixes"] or ()
        },
        "leagues": out_leagues,
    }
    OUT.write_text(
        json.dumps(doc, indent=1, sort_keys=False, default=lambda o: dict(o))
    )
    print(f"wrote {OUT} ({len(out_leagues)} league codes)")


if __name__ == "__main__":
    main()
