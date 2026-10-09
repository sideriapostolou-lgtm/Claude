"""Lab 6 engine: the sports specialist (research/lab6/PLAN.md). Polymarket game moneylines against Pinnacle's
no-vig fair probability.

Pure functions over lab 4's cached Polymarket markets and tapes and lab 6's cached Pinnacle snapshots. Nothing here
talks to the network.

* League tables: which Polymarket event-slug prefix (``mlb``, ``epl``, ...) maps to which Odds API sport keys, and
  which tennis tournaments (question prefix) The Odds API covers.
* :func:`build_games`: one row per Polymarket game (a 2-way moneyline ``A vs. B``, or a soccer game's
  home / draw / away Yes-No markets) and one row per tradable side (market, outcome) with its settlement price.
* Matching: :func:`name_sim` (accent-, case- and filler-word-insensitive token match plus an alias table) and
  :func:`match_games` (same sport key, Pinnacle ``commence_time`` within :data:`MATCH_TOL_S` of Polymarket's
  ``gameStartTime``, both teams matched).
* No-vig: :func:`novig_multiplicative` (the declared method) and :func:`novig_power` (the declared alternative).
* Alignment: :func:`snapshot_index` picks the last Pinnacle snapshot at or BEFORE a print, within the declared
  staleness, and strictly before the game; never a later one.
* :func:`side_candidates` / :func:`cell_bets`: the entry rule (buy a side whose print price plus one tick plus the
  taker fee is below the fair probability by more than the margin; one bet per game, the earliest signal);
  :func:`summarize` reuses lab 4's readings and adds closing-line value; :func:`qualifies` is lab 4's bar.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
LEDGER = HERE / "trials.json"
SIBLING_LEDGERS = tuple(
    HERE.parent / lab / "trials.json" for lab in ("lab2", "lab3", "lab4", "lab5")
)


def _load_lab4_core() -> Any:
    """Lab 4's engine, loaded under its own name so lab 6 uses the SAME fee model, splits, readings and bar."""
    spec = importlib.util.spec_from_file_location(
        "lab4_core", HERE.parent / "lab4" / "core.py"
    )
    assert spec is not None and spec.loader is not None
    if "lab4_core" in sys.modules:
        return sys.modules["lab4_core"]
    mod = importlib.util.module_from_spec(spec)
    sys.modules["lab4_core"] = mod  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(mod)
    return mod


L4 = _load_lab4_core()

SPLITS = L4.SPLITS  # lab 4's split on closedTime (UTC)
TICKET_USD = 20.0
TICK = 0.01  # polymarket.com's tick for 0.04 <= p <= 0.96 (pre-game moneylines live there)
MAX_EXEC = 0.99
STALENESS_S = 30 * 60  # PLAN: a snapshot is usable for 30 minutes after its timestamp
CLOSE_MAX_AGE_S = 30 * 60  # the closing line must be a snapshot within 30 min of the start
MATCH_TOL_S = 3 * 3600  # Pinnacle commence_time vs Polymarket gameStartTime
WINDOWS_H = (24.0, 6.0, 1.0)
MARGINS = (0.01, 0.02, 0.03, 0.05)
METHODS = ("mult", "power")
SELECTABLE_METHODS = ("mult",)
MIN_N = 100
SHORTLIST = 2

# --- league tables (PLAN §1) -------------------------------------------------------------------------------------

TWO_WAY: dict[str, tuple[str, ...]] = {
    "mlb": ("baseball_mlb",),
    "wnba": ("basketball_wnba",),
    "nfl": ("americanfootball_nfl", "americanfootball_nfl_preseason"),
    "cfb": ("americanfootball_ncaaf",),
    "nhl": ("icehockey_nhl", "icehockey_nhl_preseason"),
    "nba": ("basketball_nba", "basketball_nba_preseason"),
    "nbasl": ("basketball_nba_summer_league",),
    "kbo": ("baseball_kbo",),
    "npb": ("baseball_npb",),
    "ufc": ("mma_mixed_martial_arts",),
    "zuffa": ("boxing_boxing",),
    "boxing": ("boxing_boxing",),
    "euroleague": ("basketball_euroleague",),
    "bknbl": ("basketball_nbl",),
    "cfl": ("americanfootball_cfl",),
    "afl": ("aussierules_afl",),
    "rlnrl": ("rugbyleague_nrl",),
    "crict20blast": ("cricket_t20_blast",),
    "crichundred": ("cricket_the_hundred",),
    "crichundredw": ("cricket_the_hundred_womens",),
    "criccpl": ("cricket_caribbean_premier_league",),
    "crint": ("cricket_international_t20", "cricket_odi", "cricket_test_match"),
}
TENNIS: dict[tuple[str, str], str] = {
    ("atp", "US Open ATP"): "tennis_atp_us_open",
    ("wta", "US Open WTA"): "tennis_wta_us_open",
    ("atp", "Wimbledon ATP"): "tennis_atp_wimbledon",
    ("wta", "Wimbledon WTA"): "tennis_wta_wimbledon",
    ("atp", "Cincinnati Open"): "tennis_atp_cincinnati_open",
    ("wta", "Cincinnati Open"): "tennis_wta_cincinnati_open",
    ("atp", "National Bank Open"): "tennis_atp_canadian_open",
    ("atp", "Canadian Open"): "tennis_atp_canadian_open",
    ("wta", "National Bank Open"): "tennis_wta_canadian_open",
    ("atp", "Mubadala Citi DC Open"): "tennis_atp_washington_open",
    ("wta", "Mubadala Citi DC Open"): "tennis_wta_washington_open",
    ("atp", "Shanghai Rolex Masters"): "tennis_atp_shanghai_masters",
    ("atp", "China Open"): "tennis_atp_china_open",
    ("wta", "China Open"): "tennis_wta_china_open",
    ("atp", "Japan Open Tennis Championships"): "tennis_atp_japan_open",
    ("wta", "Guadalajara Open Akron"): "tennis_wta_guadalajara_open",
    ("wta", "Monterrey Open"): "tennis_wta_monterrey_open",
    ("wta", "Singapore Open"): "tennis_wta_singapore_open",
    ("wta", "Wuhan Open"): "tennis_wta_wuhan_open",
}
SOCCER: dict[str, tuple[str, ...]] = {
    "fifwc": ("soccer_fifa_world_cup",),
    "unl": ("soccer_uefa_nations_league",),
    "ucl": ("soccer_uefa_champs_league", "soccer_uefa_champs_league_qualification"),
    "uel": ("soccer_uefa_europa_league",),
    "col": ("soccer_uefa_europa_conference_league",),
    "uwcl": ("soccer_uefa_champs_league_women",),
    "epl": ("soccer_epl",),
    "elc": ("soccer_efl_champ",),
    "el1": ("soccer_england_league1",),
    "el2": ("soccer_england_league2",),
    "efl": ("soccer_england_efl_cup",),
    "lal": ("soccer_spain_la_liga",),
    "es2": ("soccer_spain_segunda_division",),
    "sea": ("soccer_italy_serie_a",),
    "itsb": ("soccer_italy_serie_b",),
    "itc": ("soccer_italy_coppa_italia",),
    "bun": ("soccer_germany_bundesliga",),
    "bl2": ("soccer_germany_bundesliga2",),
    "dfb": ("soccer_germany_dfb_pokal",),
    "fl1": ("soccer_france_ligue_one",),
    "fr2": ("soccer_france_ligue_two",),
    "ere": ("soccer_netherlands_eredivisie",),
    "por": ("soccer_portugal_primeira_liga",),
    "bel1": ("soccer_belgium_first_div",),
    "sui": ("soccer_switzerland_superleague",),
    "aut": ("soccer_austria_bundesliga",),
    "tur": ("soccer_turkey_super_league",),
    "gre1": ("soccer_greece_super_league",),
    "grc": ("soccer_greece_super_league",),
    "rus": ("soccer_russia_premier_league",),
    "pol": ("soccer_poland_ekstraklasa",),
    "den": ("soccer_denmark_superliga",),
    "swe": ("soccer_sweden_allsvenskan",),
    "swe2": ("soccer_sweden_superettan",),
    "nor": ("soccer_norway_eliteserien",),
    "fin1": ("soccer_finland_veikkausliiga",),
    "irl1": ("soccer_league_of_ireland",),
    "scop": ("soccer_spl",),
    "mls": ("soccer_usa_mls",),
    "mex": ("soccer_mexico_ligamx",),
    "lec": ("soccer_concacaf_leagues_cup",),
    "arg": ("soccer_argentina_primera_division",),
    "bra": ("soccer_brazil_campeonato",),
    "bra2": ("soccer_brazil_serie_b",),
    "chi1": ("soccer_chile_campeonato",),
    "lib": ("soccer_conmebol_copa_libertadores",),
    "sud": ("soccer_conmebol_copa_sudamericana",),
    "spl": ("soccer_saudi_arabia_pro_league",),
    "chi": ("soccer_china_superleague",),
    "jap": ("soccer_japan_j_league",),
    "kor": ("soccer_korea_kleague1",),
}

_WIN = re.compile(r"^Will (.+) win on (\d{4}-\d{2}-\d{2})\?$")
_DRAW = re.compile(r"^Will (.+?) vs\.? (.+) end in a draw\?$")


def league_of(event_slug: Any) -> str:
    return str(event_slug or "").split("-")[0]


def _ts(day: str) -> float:
    return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()


def sport_keys_for(
    league: str, question: str, kind: str, start: float | None = None
) -> tuple[str, ...]:
    """The Odds API sport keys a Polymarket game may live under; () = not covered (esports, minor tennis, club
    friendlies, ...). Leagues with a preseason or qualifying key are split by date so no snapshot is paid twice:
    NFL preseason before 2026-09-05; NHL preseason before 2026-10-03 (both keys after, the season opens then);
    NBA preseason only (the regular season starts after this study); Champions League qualification before
    2026-09-01; international cricket by the format in the question (ODI / Test / T20), else not covered."""
    if kind == "3way":
        keys = SOCCER.get(league, ())
        if league == "ucl" and start is not None and not math.isnan(start):
            return (keys[1],) if start < _ts("2026-09-01") else (keys[0],)
        return keys
    if league in ("atp", "wta"):
        key = TENNIS.get((league, question.split(":")[0].strip()))
        return (key,) if key else ()
    if league == "crint":
        head = question.split(":")[0]
        if re.search(r"\bODIs?\b", head):
            return ("cricket_odi",)
        if re.search(r"\bTests?\b", head):
            return ("cricket_test_match",)
        if "T20" in head:
            return ("cricket_international_t20",)
        return ()
    keys = TWO_WAY.get(league, ())
    if start is None or math.isnan(start):
        return keys
    if league == "nfl":
        return (keys[1],) if start < _ts("2026-09-05") else (keys[0],)
    if league == "nhl":
        return (keys[1],) if start < _ts("2026-10-03") else keys
    if league == "nba":
        return (keys[1],)
    return keys


# --- Polymarket games (PLAN §1) ------------------------------------------------------------------------------------


def _outcomes(value: Any) -> list[str]:
    try:
        out = json.loads(value) if isinstance(value, str) else list(value)
    except (TypeError, ValueError):
        return []
    return [str(o) for o in out]


def _prices(value: Any) -> list[float]:
    try:
        return [float(p) for p in (json.loads(value) if isinstance(value, str) else value)]
    except (TypeError, ValueError):
        return []


def _split_title(title: str) -> tuple[str, str] | None:
    parts = re.split(r"\s+vs\.?\s+", str(title or ""), maxsplit=1)
    if len(parts) != 2:
        return None
    return parts[0].strip(), parts[1].strip()


def classify(m: Any) -> str | None:
    """'ml2' = a 2-way game moneyline (slug == event slug, two named outcomes); 'win3' / 'draw3' = a soccer game's
    "Will X win on <date>?" / "Will X vs. Y end in a draw?" Yes-No market; None otherwise."""
    outs = _outcomes(m.outcomes)
    if len(outs) != 2:
        return None
    q = str(m.question or "")
    if outs == ["Yes", "No"]:
        if _WIN.match(q):
            return "win3"
        if _DRAW.match(q):
            return "draw3"
        return None
    if m.slug == m.event_slug and "(Doubles)" not in q and " O/U " not in q:
        return "ml2"
    return None


def build_games(
    markets: pd.DataFrame, meta: pd.DataFrame | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Polymarket game moneylines in covered leagues -> (games, sides).

    ``markets`` is lab 4's ``markets.parquet`` (fee family from ``fee_type``); ``meta`` holds Gamma's
    ``game_start`` per market id (unix s). A game is one event slug. Sides: a 2-way market's outcome 0 and 1 (team
    names), a soccer market's Yes (o=0, the result happens) and No (o=1). ``final`` is the side's settlement price
    (1, 0, or 0.5 on a split resolution); markets whose prices do not sum to one are not tradable."""
    sp = markets[markets["fee_type"].fillna("").str.startswith("sports")].copy()
    sp["kind_m"] = [classify(m) for m in sp.itertuples(index=False)]
    sp = sp[sp["kind_m"].notna()].copy()
    sp["league"] = sp["event_slug"].map(league_of)
    starts = (
        dict(zip(meta["id"].astype(str), meta["game_start"], strict=True))
        if meta is not None and len(meta)
        else {}
    )
    games: list[dict[str, Any]] = []
    sides: list[dict[str, Any]] = []
    for slug, g in sp.groupby("event_slug", sort=True):
        kinds = set(g["kind_m"])
        if "ml2" in kinds:
            if len(g) != 1 or kinds != {"ml2"}:
                continue
            kind = "2way"
        elif kinds <= {"win3", "draw3"}:
            kind = "3way"
        else:
            continue
        first = g.iloc[0]
        league = str(first["league"])
        gstarts = [starts.get(str(i)) for i in g["id"]]
        gstarts = [float(s) for s in gstarts if s is not None and not pd.isna(s)]
        game_start = min(gstarts) if gstarts else float("nan")
        keys = sport_keys_for(league, str(first["question"]), kind, game_start)
        if kind == "2way":
            teams = _outcomes(first["outcomes"])
            home_away = None
        else:
            ha = _split_title(str(first["event_title"]))
            if ha is None:
                continue
            teams = list(ha)
            home_away = ha
        game = {
            "game_id": str(slug),
            "league": league,
            "kind": kind,
            "sport_keys": json.dumps(list(keys)),
            "team_a": teams[0],
            "team_b": teams[1],
            "question": str(first["question"]),
            "game_start": game_start,
            "closed_time": float(g["closed_time"].min()),
            "n_markets": len(g),
            "clean": True,
        }
        for m in g.itertuples(index=False):
            prices = _prices(m.outcome_prices)
            ok = len(prices) == 2 and abs(sum(prices) - 1.0) < 1e-6
            game["clean"] = game["clean"] and ok and int(m.winner_index) in (0, 1)
            if not ok:
                continue
            rate = L4.fee_rate(m.fee_type, bool(m.fees_enabled))
            fam = L4.fee_family(m.fee_type, bool(m.fees_enabled))
            if m.kind_m == "ml2":
                outs = _outcomes(m.outcomes)
                for o in (0, 1):
                    sides.append(
                        {
                            "game_id": str(slug),
                            "market_id": str(m.id),
                            "o": o,
                            "result": "team",
                            "team": outs[o],
                            "yes": True,
                            "final": prices[o],
                            "rate": rate,
                            "family": fam,
                        }
                    )
                continue
            if m.kind_m == "draw3":
                result, team = "draw", None
            else:
                mm = _WIN.match(str(m.question))
                team = mm.group(1) if mm else None
                assert home_away is not None
                result = (
                    "home"
                    if team is not None
                    and name_sim(team, home_away[0]) >= name_sim(team, home_away[1])
                    else "away"
                )
            for o in (0, 1):
                sides.append(
                    {
                        "game_id": str(slug),
                        "market_id": str(m.id),
                        "o": o,
                        "result": result,
                        "team": team,
                        "yes": o == 0,
                        "final": prices[o],
                        "rate": rate,
                        "family": fam,
                    }
                )
        games.append(game)
    gdf = pd.DataFrame(games)
    sdf = pd.DataFrame(sides)
    if len(gdf):
        gdf["split"] = [split_of(t) for t in gdf["closed_time"]]
    return gdf, sdf


def split_of(closed_time: float) -> str | None:
    for name in SPLITS:
        lo, hi = L4.split_bounds(name)
        if lo <= closed_time < hi:
            return name
    return None


# --- name matching (PLAN §1) ---------------------------------------------------------------------------------------

FILLER = {
    "fc", "cf", "sc", "ac", "afc", "cd", "ca", "club", "de", "del", "la", "el", "the", "sk", "fk", "if", "ik",
    "bk", "rcd", "ssc", "as", "us", "sv", "vfb", "vfl", "tsg", "fsv", "sd", "ud", "cs", "ec", "cr", "se", "ss",
    "calcio", "futbol", "football", "clube", "saudi", "1", "e", "y", "and", "of", "hd", "ii",
}
ALIASES: dict[str, str] = {
    "bayern munchen": "bayern munich",
    "fc bayern munchen": "bayern munich",
    "internazionale milano": "inter milan",
    "fc internazionale milano": "inter milan",
    "athletic club": "athletic bilbao",
    "sport lisboa e benfica": "benfica",
    "paris saint germain fc": "paris saint germain",
    "wolverhampton wanderers fc": "wolverhampton wanderers",
    "brighton hove albion fc": "brighton and hove albion",
    "tottenham hotspur fc": "tottenham hotspur",
    "ca mineiro": "atletico mineiro",
    "club atletico de madrid": "atletico madrid",
    "rc celta de vigo": "celta vigo",
    "deportivo alaves": "alaves",
    "real betis balompie": "real betis",
    "ulsan hd fc": "ulsan hyundai",
    "manchester united fc": "manchester united",
    "manchester city fc": "manchester city",
    "newcastle united fc": "newcastle united",
    "west ham united fc": "west ham united",
    "utah": "utah mammoth",
    "athletics": "athletics",
}


def _ascii(text: str) -> str:
    norm = unicodedata.normalize("NFKD", str(text))
    return "".join(c for c in norm if not unicodedata.combining(c))


def normalize(name: str) -> str:
    s = _ascii(name).lower().replace("&", " and ").replace("ø", "o").replace("ß", "ss")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return ALIASES.get(s, s)


def tokens(name: str) -> set[str]:
    toks = set(normalize(name).split())
    core = toks - FILLER
    return core or toks


def name_sim(a: str, b: str) -> float:
    """1.0 when one name's core tokens contain the other's ("Jets" / "New York Jets"), else the larger of the token
    containment and a character ratio on the sorted core tokens; 0..1."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    cont = inter / min(len(ta), len(tb))
    seq = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    return max(cont, seq)


MIN_SIM = 0.6


@dataclass
class MatchResult:
    games: pd.DataFrame  # game_id, event_id, sport_key, commence, home, away, sim, dt_start_s, status
    failures: pd.DataFrame  # game_id, reason, best candidate


def match_games(
    games: pd.DataFrame, events: pd.DataFrame, tol_s: float = MATCH_TOL_S
) -> MatchResult:
    """Match each Polymarket game to one Pinnacle event: a sport key listed for its league, ``commence`` within
    ``tol_s`` of Polymarket's ``game_start`` (or, without one, on the slug's date +- 1 day), both teams with
    :func:`name_sim` >= MIN_SIM under the better of the two pairings; the best total wins. ``events``: one row
    per (sport_key, event_id) with home, away, commence (the LAST pre-game snapshot's values)."""
    by_key = {k: v for k, v in events.groupby("sport_key")} if len(events) else {}
    rows: list[dict[str, Any]] = []
    fails: list[dict[str, Any]] = []
    for g in games.itertuples(index=False):
        keys = json.loads(g.sport_keys)
        if not keys:
            fails.append({"game_id": g.game_id, "league": g.league, "reason": "league not covered"})
            continue
        cands = [by_key[k] for k in keys if k in by_key]
        if not cands:
            fails.append({"game_id": g.game_id, "league": g.league, "reason": "no Pinnacle events for the sport keys"})
            continue
        ev = pd.concat(cands, ignore_index=True)
        if not math.isnan(g.game_start):
            near = ev[(ev["commence"] - g.game_start).abs() <= tol_s]
        else:
            day = _slug_date(g.game_id)
            near = (
                ev[(ev["commence"] >= day - 86400) & (ev["commence"] < day + 2 * 86400)]
                if day is not None
                else ev.iloc[0:0]
            )
        best: tuple[float, Any, bool, float, float] | None = None
        for e in near.itertuples(index=False):
            s_ah, s_bw = name_sim(g.team_a, e.home), name_sim(g.team_b, e.away)
            s_aw, s_bh = name_sim(g.team_a, e.away), name_sim(g.team_b, e.home)
            straight = min(s_ah, s_bw) >= min(s_aw, s_bh)
            lo, tot = (min(s_ah, s_bw), s_ah + s_bw) if straight else (min(s_aw, s_bh), s_aw + s_bh)
            if best is None or tot > best[3]:
                best = (lo, e, straight, tot, lo)
        if best is None:
            fails.append({"game_id": g.game_id, "league": g.league, "reason": "no Pinnacle event near the start time",
                          "team_a": g.team_a, "team_b": g.team_b})
            continue
        lo, e, straight, tot, _ = best
        if lo < MIN_SIM:
            fails.append({"game_id": g.game_id, "league": g.league, "reason": "team names do not match",
                          "team_a": g.team_a, "team_b": g.team_b, "best_home": e.home, "best_away": e.away,
                          "sim": round(lo, 3)})
            continue
        rows.append(
            {
                "game_id": g.game_id,
                "sport_key": e.sport_key,
                "event_id": e.event_id,
                "commence": float(e.commence),
                "home": e.home,
                "away": e.away,
                "a_is_home": bool(straight),
                "sim": float(lo),
                "dt_start_s": float(e.commence - g.game_start) if not math.isnan(g.game_start) else float("nan"),
            }
        )
    mcols = ["game_id", "sport_key", "event_id", "commence", "home", "away", "a_is_home", "sim", "dt_start_s"]
    fcols = ["game_id", "league", "reason", "team_a", "team_b", "best_home", "best_away", "sim"]
    mdf = pd.DataFrame(rows, columns=mcols)
    # one Pinnacle event serves one Polymarket game (a duplicate slug, e.g. a re-listed game, keeps the first)
    mdf = mdf.drop_duplicates("event_id", keep="first").reset_index(drop=True)
    return MatchResult(mdf, pd.DataFrame(fails, columns=fcols))


def _slug_date(slug: str) -> float | None:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", slug)
    if not m:
        return None
    return datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=UTC).timestamp()


# --- no-vig fair probability (PLAN §2) -----------------------------------------------------------------------------


def implied(decimal_odds: np.ndarray) -> np.ndarray:
    return 1.0 / np.asarray(decimal_odds, dtype=float)


def novig_multiplicative(decimal_odds: np.ndarray) -> np.ndarray:
    """The declared method: implied probabilities 1/d scaled to sum to one (the margin removed in proportion)."""
    q = implied(decimal_odds)
    return q / q.sum()


def novig_power(decimal_odds: np.ndarray, tol: float = 1e-12) -> np.ndarray:
    """The declared alternative: p_i = q_i^k with k chosen so the p_i sum to one (bisection; k > 1 when the book
    is overround). Shades longshots more than the multiplicative method."""
    q = implied(decimal_odds)
    if abs(q.sum() - 1.0) < tol:
        return q / q.sum()
    lo, hi = 0.01, 50.0
    for _ in range(200):
        k = 0.5 * (lo + hi)
        s = float((q**k).sum())
        if abs(s - 1.0) < tol:
            break
        if s > 1.0:
            lo = k
        else:
            hi = k
    p = q**k
    return p / p.sum()


NOVIG = {"mult": novig_multiplicative, "power": novig_power}


def overround(decimal_odds: np.ndarray) -> float:
    return float(implied(decimal_odds).sum() - 1.0)


# --- Pinnacle snapshots per event ----------------------------------------------------------------------------------


@dataclass
class EventLine:
    """One event's Pinnacle h2h history: snapshot times (sorted) and the fair probability per result per method."""

    snap_ts: np.ndarray
    fair: dict[str, dict[str, np.ndarray]]  # method -> result key ('home'/'away'/'draw') -> fair per snapshot
    overround: np.ndarray


def event_lines(pin: pd.DataFrame) -> dict[str, EventLine]:
    """``pin``: one row per (event_id, snap_ts) with home, away, and the h2h outcome names / decimal prices
    (``names``, ``prices`` JSON lists). Rows whose outcomes do not cover home and away (and the draw, when
    priced) are dropped. Results are keyed home / away / draw so a Polymarket side maps by role."""
    out: dict[str, EventLine] = {}
    for eid, g in pin.sort_values("snap_ts").groupby("event_id", sort=False):
        ts: list[float] = []
        fairs: dict[str, dict[str, list[float]]] = {m: {"home": [], "away": [], "draw": []} for m in METHODS}
        ors: list[float] = []
        for r in g.itertuples(index=False):
            names = json.loads(r.names)
            prices = np.array(json.loads(r.prices), dtype=float)
            if len(names) not in (2, 3) or (prices <= 1.0).any():
                continue
            role: dict[str, int] = {}
            for i, n in enumerate(names):
                if n == r.home:
                    role["home"] = i
                elif n == r.away:
                    role["away"] = i
                elif str(n).lower() == "draw":
                    role["draw"] = i
            if "home" not in role or "away" not in role or len(role) != len(names):
                continue
            ts.append(float(r.snap_ts))
            ors.append(overround(prices))
            for meth in METHODS:
                p = NOVIG[meth](prices)
                for key in ("home", "away", "draw"):
                    fairs[meth][key].append(float(p[role[key]]) if key in role else float("nan"))
        if ts:
            out[str(eid)] = EventLine(
                snap_ts=np.array(ts),
                fair={m: {k: np.array(v) for k, v in d.items()} for m, d in fairs.items()},
                overround=np.array(ors),
            )
    return out


def snapshot_index(
    snap_ts: np.ndarray, t: np.ndarray, commence: float, staleness_s: float = STALENESS_S
) -> np.ndarray:
    """For each print time ``t``: the index of the last snapshot taken AT OR BEFORE ``t`` (never after), strictly
    before ``commence``, and at most ``staleness_s`` old; -1 when there is none."""
    t = np.asarray(t, dtype=float)
    j = np.searchsorted(snap_ts, t, side="right") - 1
    ok = j >= 0
    jj = np.where(ok, j, 0)
    ok &= snap_ts[jj] < commence
    ok &= (t - snap_ts[jj]) <= staleness_s
    return np.where(ok, j, -1)


def closing_index(snap_ts: np.ndarray, commence: float, max_age_s: float = CLOSE_MAX_AGE_S) -> int:
    """The closing line: the last snapshot strictly before ``commence`` and no older than ``max_age_s``; -1 if none."""
    j = int(np.searchsorted(snap_ts, commence, side="left")) - 1
    if j < 0 or commence - snap_ts[j] > max_age_s:
        return -1
    return j


def pinnacle_role(result: str, a_is_home: bool, team_is_a: bool | None = None) -> str:
    """Which Pinnacle result a Polymarket side is about. Polymarket's team A is its outcome 0 (2-way) or the first
    team of the event title (soccer); ``a_is_home`` says whether Pinnacle lists team A as home."""
    if result == "team":
        assert team_is_a is not None
        return "home" if team_is_a == a_is_home else "away"
    if result == "home":
        return "home" if a_is_home else "away"
    if result == "away":
        return "away" if a_is_home else "home"
    return "draw"


def side_fair(
    line: EventLine, method: str, result: str, yes: bool, a_is_home: bool, team_is_a: bool | None = None
) -> np.ndarray:
    """The fair probability of one Polymarket side per snapshot: the mapped Pinnacle result's probability for a
    team outcome or a Yes, one minus it for a No."""
    p = line.fair[method][pinnacle_role(result, a_is_home, team_is_a)]
    return p if yes else 1.0 - p


# --- the entry rule (PLAN §3) -------------------------------------------------------------------------------------


def buyable_prints(tape: pd.DataFrame, o: int) -> pd.DataFrame:
    """Prints a buyer of outcome ``o`` could have hit (lab 4 Amendment 3): a BUY on o's token at p, or a SELL on
    the other token at q (= o at 1 - q). Columns ts, price (of o), size (shares)."""
    oi = tape["outcome_index"].to_numpy()
    side = tape["side"].astype(str).str.upper().to_numpy()
    price = tape["price"].to_numpy(dtype=float)
    mine = (oi == o) & (side == "BUY")
    other = (oi == 1 - o) & (side == "SELL")
    keep = mine | other
    p = np.where(mine, price, 1.0 - price)
    out = pd.DataFrame({"ts": tape["ts"].to_numpy(dtype=float)[keep], "price": p[keep],
                        "size": tape["size"].to_numpy(dtype=float)[keep]})
    out = out[(out["price"] > 0.0) & (out["price"] < 1.0)]
    return out.sort_values("ts", kind="stable").reset_index(drop=True)


CAND_COLS = [
    "game_id", "market_id", "o", "result", "yes", "t", "p_print", "size", "snap_ts", "fair", "p_exec", "fee_ps",
    "edge", "final", "rate", "family", "close_fair", "method",
]


def side_candidates(
    game: Any,
    side: Any,
    tape: pd.DataFrame,
    line: EventLine,
    method: str,
    max_window_s: float,
    ticket: float = TICKET_USD,
    tick: float = TICK,
    staleness_s: float = STALENESS_S,
) -> pd.DataFrame:
    """Every print that could trigger an entry on one side: buyable, inside ``[commence - max_window, cutoff)``
    (cutoff = the earlier of Pinnacle's commence and Polymarket's gameStartTime), with a usable snapshot, and big
    enough for the ticket (print size >= our shares). ``edge`` = fair - (print + one tick) - taker fee per share."""
    commence = float(game.commence)
    cutoff = min(commence, float(game.game_start)) if not math.isnan(game.game_start) else commence
    bp = buyable_prints(tape, int(side.o))
    bp = bp[(bp["ts"] >= commence - max_window_s) & (bp["ts"] < cutoff)]
    if bp.empty:
        return pd.DataFrame(columns=CAND_COLS)
    j = snapshot_index(line.snap_ts, bp["ts"].to_numpy(), commence, staleness_s)
    bp = bp[j >= 0].copy()
    j = j[j >= 0]
    if bp.empty:
        return pd.DataFrame(columns=CAND_COLS)
    team_is_a = (int(side.o) == 0) if side.result == "team" else None  # 2-way: team A is outcome 0
    fair_all = side_fair(line, method, side.result, bool(side.yes), bool(game.a_is_home), team_is_a)
    fair = fair_all[j]
    p_exec = np.round(bp["price"].to_numpy() + tick, 6)
    fee_ps = side.rate * p_exec * (1.0 - p_exec)
    shares = ticket / np.maximum(p_exec, 1e-9)
    ok = (p_exec <= MAX_EXEC) & np.isfinite(fair) & (bp["size"].to_numpy() >= shares)
    ci = closing_index(line.snap_ts, commence)
    close_fair = float(fair_all[ci]) if ci >= 0 else float("nan")
    out = pd.DataFrame(
        {
            "game_id": game.game_id,
            "market_id": side.market_id,
            "o": int(side.o),
            "result": side.result,
            "yes": bool(side.yes),
            "t": bp["ts"].to_numpy(),
            "p_print": bp["price"].to_numpy(),
            "size": bp["size"].to_numpy(),
            "snap_ts": line.snap_ts[j],
            "fair": fair,
            "p_exec": p_exec,
            "fee_ps": fee_ps,
            "edge": fair - p_exec - fee_ps,
            "final": float(side.final),
            "rate": float(side.rate),
            "family": side.family,
            "close_fair": close_fair,
            "method": method,
        }
    )
    return out[ok].reset_index(drop=True)


BET_COLS = [
    "id", "event", "family", "league", "question", "closed_time", "day", "t_signal", "t_exec", "p_exec", "fair",
    "edge", "close_fair", "clv", "won", "push", "net", "fee_usd", "pnl_usd", "lock_h", "missed",
    "old_rule_bid_side", "result", "yes", "o",
]


def cell_bets(
    cands: pd.DataFrame,
    games: pd.DataFrame,
    window_h: float,
    margin: float,
    ticket: float = TICKET_USD,
) -> pd.DataFrame:
    """One bet per game: the earliest candidate inside ``[commence - window_h, cutoff)`` whose edge exceeds
    ``margin`` (ties at the same second: the larger edge). Settled at the side's final price."""
    if cands.empty:
        return pd.DataFrame(columns=BET_COLS)
    gi = games.set_index("game_id")
    c = cands.join(gi[["commence", "league", "question", "closed_time"]], on="game_id")
    c = c[(c["t"] >= c["commence"] - window_h * 3600.0) & (c["edge"] > margin)]
    if c.empty:
        return pd.DataFrame(columns=BET_COLS)
    c = c.sort_values(["game_id", "t", "edge"], ascending=[True, True, False], kind="stable")
    first = c.groupby("game_id", sort=False).head(1)
    p = first["p_exec"].to_numpy(dtype=float)
    shares = ticket / p
    fee = shares * first["rate"].to_numpy() * p * (1.0 - p)
    final = first["final"].to_numpy(dtype=float)
    pnl = shares * final - fee - ticket
    closed = first["closed_time"].to_numpy(dtype=float)
    out = pd.DataFrame(
        {
            "id": first["market_id"].to_numpy(),
            "event": first["game_id"].to_numpy(),
            "family": first["family"].to_numpy(),
            "league": first["league"].to_numpy(),
            "question": first["question"].to_numpy(),
            "closed_time": closed,
            "day": [datetime.fromtimestamp(x, UTC).strftime("%Y-%m-%d") for x in closed],
            "t_signal": first["t"].to_numpy(),
            "t_exec": first["t"].to_numpy(),
            "p_exec": p,
            "fair": first["fair"].to_numpy(),
            "edge": first["edge"].to_numpy(),
            "close_fair": first["close_fair"].to_numpy(),
            "clv": first["close_fair"].to_numpy() - p,
            "won": final > 0.5,
            "push": np.isclose(final, 0.5),
            "net": pnl / ticket,
            "fee_usd": fee,
            "pnl_usd": pnl,
            "lock_h": (closed - first["t"].to_numpy()) / 3600.0,
            "missed": False,
            "old_rule_bid_side": False,
            "result": first["result"].to_numpy(),
            "yes": first["yes"].to_numpy(),
            "o": first["o"].to_numpy(),
        }
    )
    return out.reset_index(drop=True)


def clv_reading(bets: pd.DataFrame, B: int = L4.BOOTSTRAP_B) -> dict[str, Any]:
    """H2 (diagnostic): closing-line value of the entries, close_fair - p_exec, in probability points; the share
    that beat the close; event-bootstrap CI."""
    b = bets[np.isfinite(bets["clv"].to_numpy(dtype=float))] if len(bets) else bets
    if len(b) == 0:
        return {"n": 0, "mean": None, "ci95": [None, None], "beat_share": None}
    v = b["clv"].to_numpy(dtype=float)
    ci = L4.event_bootstrap_ci(v, b["event"].to_numpy(), B=B)
    return {"n": len(b), "mean": float(v.mean()), "ci95": [ci[0], ci[1]], "beat_share": float((v > 0).mean())}


def summarize(bets: pd.DataFrame, split: str, B: int = L4.BOOTSTRAP_B) -> dict[str, Any]:
    """Lab 4's readings (n, win rate, mean net with event-bootstrap CI, worst case, daily Sharpe, drawdown, by
    family) plus lab 6's: mean fair, mean edge at entry, model-expected net, pushes, CLV, by league."""
    s = L4.summarize(bets, split, B=B)
    if len(bets) == 0:
        return {**s, "mean_fair": None, "mean_edge": None, "model_net": None, "pushes": 0,
                "clv": clv_reading(bets, B), "by_league": {}}
    p = bets["p_exec"].to_numpy(dtype=float)
    model_net = bets["fair"].to_numpy() / p - 1.0 - bets["fee_usd"].to_numpy() / TICKET_USD
    by_league = {}
    for lg, g in bets.groupby("league"):
        by_league[str(lg)] = {"n": len(g), "win_rate": float(g["won"].mean()), "mean_p_exec": float(g["p_exec"].mean()),
                              "mean_net": float(g["net"].mean()), "total_usd": float(g["pnl_usd"].sum())}
    return {
        **s,
        "mean_fair": float(bets["fair"].mean()),
        "mean_edge": float(bets["edge"].mean()),
        "model_net": float(model_net.mean()),
        "pushes": int(bets["push"].sum()),
        "clv": clv_reading(bets, B),
        "by_league": by_league,
    }


def qualifies(s: dict[str, Any], min_n: int = MIN_N) -> bool:
    """Lab 4's bar, unchanged (core.qualifies): n >= min_n, mean > 0, event-bootstrap CI95 lower bound > 0, at least
    one loss, rule-of-three guard under five losses."""
    return bool(L4.qualifies(s, min_n))


def calibration_placebo(bets: pd.DataFrame, draws: int = L4.BOOTSTRAP_B, seed: int = 1) -> dict[str, Any]:
    return dict(L4.calibration_placebo(bets, draws=draws, seed=seed))


# --- trial ledger --------------------------------------------------------------------------------------------------


def trials_count() -> int:
    n = 0
    for path in (*SIBLING_LEDGERS, LEDGER):
        if path.exists():
            try:
                n += L4._ledger_size(json.loads(path.read_text()))
            except ValueError:
                continue
    return n


def record_run(entry: dict[str, Any], ledger: Path | None = None) -> int:
    """Upsert one trial in research/lab6/trials.json keyed on (lab, hyp, cell, split, stage); returns the running
    count across labs 2-6."""
    path = ledger or LEDGER
    doc = json.loads(path.read_text()) if path.exists() else []
    key = tuple(entry.get(k) for k in ("lab", "hyp", "cell", "split", "stage"))
    doc = [e for e in doc if tuple(e.get(k) for k in ("lab", "hyp", "cell", "split", "stage")) != key]
    doc.append({**entry, "utc": datetime.now(UTC).isoformat(timespec="seconds"), "t": time.time()})
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return trials_count()


@dataclass
class Universe:
    """A split's matched games, their sides, tapes and Pinnacle lines, ready for :func:`all_candidates`."""

    split: str
    games: pd.DataFrame
    sides: pd.DataFrame
    lines: dict[str, EventLine]
    tapes: dict[str, pd.DataFrame] = field(default_factory=dict)


def latency_exec(
    bets: pd.DataFrame,
    u: Universe,
    latency_s: float = L4.LATENCY_S,
    window_s: float = L4.EXEC_WINDOW_S,
    ticket: float = TICKET_USD,
) -> pd.DataFrame:
    """Robustness reading (not a decision input): the same signals filled the lab 4 way, at the first buyable
    print for the same side ``latency_s`` or more after the signal (within ``window_s`` and before the cutoff), at
    that print's price with no extra tick; signals with no such print are marked missed."""
    if bets.empty:
        return bets.copy()
    gi = u.games.set_index("game_id")
    sides = u.sides.set_index(["market_id", "o"])
    rows = []
    for b in bets.itertuples(index=False):
        g = gi.loc[b.event]
        o = int(b.o)
        tape = u.tapes.get(str(b.id))
        cutoff = min(float(g["commence"]), float(g["game_start"])) if not math.isnan(g["game_start"]) else float(
            g["commence"])
        row = b._asdict()
        bp = buyable_prints(tape, o) if tape is not None else pd.DataFrame(columns=["ts", "price", "size"])
        bp = bp[(bp["ts"] >= b.t_signal + latency_s) & (bp["ts"] <= b.t_signal + window_s) & (bp["ts"] < cutoff)]
        if bp.empty:
            row.update({"missed": True, "net": None, "pnl_usd": None, "fee_usd": None, "p_exec": None, "won": None,
                        "t_exec": None, "lock_h": None})
            rows.append(row)
            continue
        p = min(float(bp["price"].iloc[0]), MAX_EXEC)
        s = sides.loc[(str(b.id), o)]
        shares = ticket / p
        fee = shares * float(s["rate"]) * p * (1.0 - p)
        pnl = shares * float(s["final"]) - fee - ticket
        row.update({"missed": False, "p_exec": p, "fee_usd": fee, "pnl_usd": pnl, "net": pnl / ticket,
                    "t_exec": float(bp["ts"].iloc[0]), "won": float(s["final"]) > 0.5,
                    "lock_h": (float(b.closed_time) - float(bp["ts"].iloc[0])) / 3600.0,
                    "clv": b.close_fair - p})
        rows.append(row)
    return pd.DataFrame(rows, columns=list(bets.columns))


def clv_baseline(
    u: Universe, method: str, window_h: float, ticket: float = TICKET_USD, tick: float = TICK
) -> pd.DataFrame:
    """H2's no-skill baseline: for every matched game and every side, buy at the first buyable print (big enough
    for the ticket) at or after ``commence - window_h``, at print + one tick, no fair-value filter. Returns one row
    per (game, side) with the closing-line value and the settled net."""
    rows: list[dict[str, Any]] = []
    sides_by_game = {k: v for k, v in u.sides.groupby("game_id")}
    for g in u.games.itertuples(index=False):
        line = u.lines.get(str(g.event_id))
        if line is None:
            continue
        ci = closing_index(line.snap_ts, float(g.commence))
        if ci < 0:
            continue
        cutoff = min(float(g.commence), float(g.game_start)) if not math.isnan(g.game_start) else float(g.commence)
        for s in sides_by_game.get(g.game_id, pd.DataFrame()).itertuples(index=False):
            tape = u.tapes.get(str(s.market_id))
            if tape is None or tape.empty:
                continue
            bp = buyable_prints(tape, int(s.o))
            p_exec = np.round(bp["price"].to_numpy() + tick, 6)
            ok = ((bp["ts"].to_numpy() >= float(g.commence) - window_h * 3600.0) & (bp["ts"].to_numpy() < cutoff)
                  & (p_exec <= MAX_EXEC) & (bp["size"].to_numpy() >= ticket / np.maximum(p_exec, 1e-9)))
            if not ok.any():
                continue
            k = int(np.argmax(ok))
            p = float(p_exec[k])
            team_is_a = (int(s.o) == 0) if s.result == "team" else None
            close_fair = float(side_fair(line, method, s.result, bool(s.yes), bool(g.a_is_home), team_is_a)[ci])
            shares = ticket / p
            fee = shares * float(s.rate) * p * (1.0 - p)
            pnl = shares * float(s.final) - fee - ticket
            rows.append({"event": g.game_id, "league": g.league, "market_id": s.market_id, "o": int(s.o),
                         "t": float(bp["ts"].iloc[k]), "p_exec": p, "close_fair": close_fair,
                         "clv": close_fair - p, "net": pnl / ticket})
    return pd.DataFrame(rows, columns=["event", "league", "market_id", "o", "t", "p_exec", "close_fair", "clv",
                                       "net"])


def baseline_reading(base: pd.DataFrame, B: int = L4.BOOTSTRAP_B) -> dict[str, Any]:
    if base.empty:
        return {"n": 0}
    ev = base["event"].to_numpy()
    clv = base["clv"].to_numpy(dtype=float)
    net = base["net"].to_numpy(dtype=float)
    return {"n": len(base), "games": int(base["event"].nunique()), "mean_clv": float(clv.mean()),
            "clv_ci95": list(L4.event_bootstrap_ci(clv, ev, B=B)), "beat_share": float((clv > 0).mean()),
            "mean_net": float(net.mean()), "net_ci95": list(L4.event_bootstrap_ci(net, ev, B=B)),
            "mean_abs_gap": float(np.abs(clv).mean())}


def all_candidates(u: Universe, method: str, max_window_s: float) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    sides_by_game = {k: v for k, v in u.sides.groupby("game_id")}
    for g in u.games.itertuples(index=False):
        line = u.lines.get(str(g.event_id))
        if line is None:
            continue
        for s in sides_by_game.get(g.game_id, pd.DataFrame()).itertuples(index=False):
            tape = u.tapes.get(str(s.market_id))
            if tape is None or tape.empty:
                continue
            c = side_candidates(g, s, tape, line, method, max_window_s)
            if len(c):
                parts.append(c)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=CAND_COLS)
