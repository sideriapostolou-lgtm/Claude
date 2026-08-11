"""Build the self-contained phone demo page.

Prices tonight's real slate with the live engine, grades yesterday's board
from official play-by-play, and injects everything into the template. Runs
standalone (scheduled) or by hand:

    python -m web.build_phone_demo [output.html]

Writes data/demo_history/{date}.json so the next day's build can settle
today's markets and extend the running P&L record.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.base import GameInfo  # noqa: E402
from engine.odds import american  # noqa: E402
from engine.pricing import price  # noqa: E402
from engine.rates import LiveRates, modal_slots_from_corpus  # noqa: E402
from engine.risk import RiskEngine  # noqa: E402
from parser.propspec import Constraints, PropSpec  # noqa: E402

BASE = "https://statsapi.mlb.com/api/v1"
SEASON = 2026
HISTORY_DIR = ROOT / "data" / "demo_history"
TEMPLATE = ROOT / "web" / "phone_template.html"

STARS = ["Aaron Judge", "Juan Soto", "Shohei Ohtani", "Kyle Schwarber", "Bryce Harper",
         "Salvador Perez", "Bobby Witt Jr.", "Elly De La Cruz", "Gunnar Henderson",
         "Rafael Devers", "Julio Rodríguez", "Pete Alonso", "Francisco Lindor",
         "Corey Seager", "Vladimir Guerrero Jr.", "José Ramírez", "Yordan Alvarez",
         "Mookie Betts", "Freddie Freeman", "Ronald Acuña Jr."]


def fetch_slate(day: str, s: requests.Session):
    sched = s.get(f"{BASE}/schedule",
                  params={"sportId": 1, "date": day,
                          "hydrate": "probablePitcher,team,lineups"}, timeout=30).json()
    raw = [g for d in sched.get("dates", []) for g in d.get("games", [])
           if g.get("gameType") == "R"]
    games = []
    for g in raw:
        lineups = {}
        lu = g.get("lineups") or {}
        for side_key in ("awayPlayers", "homePlayers"):
            for slot, p in enumerate(lu.get(side_key) or [], start=1):
                lineups[p["id"]] = slot
        games.append((g, GameInfo(
            gamePk=g["gamePk"],
            away_id=g["teams"]["away"]["team"]["id"],
            home_id=g["teams"]["home"]["team"]["id"],
            away_name=g["teams"]["away"]["team"]["name"],
            home_name=g["teams"]["home"]["team"]["name"],
            venue_name=g.get("venue", {}).get("name", ""),
            away_sp_id=(g["teams"]["away"].get("probablePitcher") or {}).get("id"),
            home_sp_id=(g["teams"]["home"].get("probablePitcher") or {}).get("id"),
            lineups=lineups)))
    return games


def grade_yesterday(day: str, s: requests.Session) -> dict | None:
    """Settle yesterday's saved board at $10 flat and show what actually hit."""
    hist_file = HISTORY_DIR / f"{day}.json"
    saved = json.loads(hist_file.read_text()) if hist_file.exists() else None
    sched = s.get(f"{BASE}/schedule", params={"sportId": 1, "date": day}, timeout=30).json()
    finals = [g for d in sched.get("dates", []) for g in d.get("games", [])
              if g.get("gameType") == "R" and g["status"]["abstractGameState"] == "Final"]
    if not finals:
        return None
    results, pnl, settled = [], 0.0, 0
    saved_by_pk = {g["gamePk"]: g for g in (saved or {}).get("board", [])} if saved else {}
    for g in finals:
        pk = g["gamePk"]
        try:
            pbp = s.get(f"{BASE}/game/{pk}/playByPlay", timeout=30).json()
        except Exception:
            continue
        hr_innings = sorted({p["about"]["inning"] for p in pbp.get("allPlays", [])
                             if p["result"].get("eventType") == "home_run"})
        row = {"matchup": f'{g["teams"]["away"]["team"]["name"]} @ '
                          f'{g["teams"]["home"]["team"]["name"]}',
               "hrInnings": [i for i in hr_innings if i <= 9]}
        prior = saved_by_pk.get(pk)
        if prior:
            marks = []
            for i, q in enumerate(prior["innings"], start=1):
                won = i in hr_innings
                dec = 1.0 / q["bookProb"] if q.get("bookProb") else None
                if dec:
                    pnl += -10 * (dec - 1) if won else 10.0
                    settled += 1
                marks.append({"inning": i, "book": q["book"], "hit": won})
            row["markets"] = marks
        results.append(row)
    out = {"date": day, "games": results}
    if settled:
        out["pnl"] = {"settled": settled, "bookPnl": round(pnl, 2),
                      "handle": settled * 10,
                      "holdPct": round(100 * pnl / (settled * 10), 2)}
    return out


def build() -> str:
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    s = requests.Session()
    s.headers.update({"User-Agent": "prop-engine-demo-builder"})
    games = fetch_slate(today, s)
    rates = LiveRates(SEASON)
    risk = RiskEngine(quote_log=HISTORY_DIR / "demo_quotes.jsonl")
    slots = modal_slots_from_corpus(str(SEASON))

    def quote(spec, gi=None, player_id=None, player_slot=None, keep_prob=False):
        r = price(spec, game=gi, rates=rates, player_id=player_id, player_slot=player_slot)
        q = risk.quote(spec, r, game_pk=gi.gamePk if gi else None)
        d = {"fair": round(r.fair_prob, 5), "fairOdds": american(r.fair_prob),
             "book": q.book_odds, "tier": q.tier, "stake": q.max_stake}
        if keep_prob:
            d["bookProb"] = round(q.book_prob, 5)
        return d

    board = []
    for raw, gi in games:
        row = {"gamePk": gi.gamePk, "matchup": f"{gi.away_name} @ {gi.home_name}",
               "venue": gi.venue_name, "away": gi.away_name, "home": gi.home_name,
               "innings": [], "teamInnings": {"away": [], "home": []},
               "lineupsPosted": bool(gi.lineups)}
        for i in range(1, 10):
            spec = PropSpec(sport="MLB", market_family="inning_event", event="home_run",
                            scope="either_team", constraints=Constraints(inning=i))
            row["innings"].append(quote(spec, gi, keep_prob=True))
        for side, nm in (("away", gi.away_name), ("home", gi.home_name)):
            for i in range(1, 10):
                spec = PropSpec(sport="MLB", market_family="inning_event",
                                event="home_run", scope="team", team=nm,
                                constraints=Constraints(inning=i))
                row["teamInnings"][side].append(quote(spec, gi))
        board.append(row)

    extras = []
    if games:
        for i in range(10, 13):
            spec = PropSpec(sport="MLB", market_family="inning_event", event="home_run",
                            scope="either_team", constraints=Constraints(inning=i),
                            flags=["extra_innings"])
            extras.append(quote(spec, games[0][1]))

    messi_exact, messi_atleast = {}, {}
    for d in range(6, 46):
        spec = PropSpec(sport="soccer", market_family="coordinate_event", event="goal",
                        scope="player", player="Lionel Messi",
                        constraints=Constraints(distance_yards=d, tolerance=0.5,
                                                comparator="exactly"))
        r = price(spec)
        q = risk.quote(spec, r)
        messi_exact[d] = {"fair": round(r.fair_prob, 5), "fairOdds": american(r.fair_prob),
                          "book": q.book_odds, "tier": q.tier, "stake": q.max_stake,
                          "shots": r.inputs_used["player_shots_in_band"],
                          "goals": r.inputs_used["player_goals_in_band"]}
    for d in range(10, 41):
        spec = PropSpec(sport="soccer", market_family="coordinate_event", event="goal",
                        scope="player", player="Lionel Messi",
                        constraints=Constraints(distance_yards=d, comparator="at_least"))
        r = price(spec)
        q = risk.quote(spec, r)
        messi_atleast[d] = {"fair": round(r.fair_prob, 5), "fairOdds": american(r.fair_prob),
                            "book": q.book_odds, "tier": q.tier, "stake": q.max_stake,
                            "shots": r.inputs_used["player_shots_in_band"],
                            "goals": r.inputs_used["player_goals_in_band"]}

    # hitters: stars on rosters + everyone in a posted lineup (slots 1-5)
    from parser.validate import fetch_context
    ctx = fetch_context(today)
    wanted: dict[str, int] = {}
    for name in STARS:
        pid = ctx.rosters.get(name.lower())
        if pid:
            wanted[name] = pid
    id_to_name = {v: k for k, v in ctx.rosters.items()}
    for raw, gi in games:
        for pid, slot in gi.lineups.items():
            if slot <= 5 and pid in id_to_name and len(wanted) < 60:
                wanted.setdefault(id_to_name[pid].title(), pid)

    players = {}
    for name, pid in wanted.items():
        team_id = ctx.player_team.get(name.lower())
        gi = next((g for _, g in games if team_id in (g.away_id, g.home_id)), None)
        if gi is None:
            continue
        team_name = gi.away_name if team_id == gi.away_id else gi.home_name
        slot = gi.lineups.get(pid) or slots.get(pid)
        ent = {"team": team_name, "game": f"{gi.away_name} @ {gi.home_name}",
               "slot": slot, "slotSource": "lineup" if pid in gi.lineups else "prior"}
        try:
            sp = PropSpec(sport="MLB", market_family="player_event", event="home_run",
                          scope="player", player=name, team=team_name)
            ent["hrAny"] = quote(sp, gi, player_id=pid, player_slot=slot)
            for k, key in ((2, "hits2"), (3, "hits3")):
                sp2 = PropSpec(sport="MLB", market_family="count_event", event="hit",
                               scope="player", player=name, team=team_name,
                               constraints=Constraints(count=k, comparator="at_least"))
                ent[key] = quote(sp2, gi, player_id=pid, player_slot=slot)
            ent["hrInn"] = []
            for i in range(1, 10):
                sp3 = PropSpec(sport="MLB", market_family="inning_event", event="home_run",
                               scope="player", player=name, team=team_name,
                               constraints=Constraints(inning=i))
                ent["hrInn"].append(quote(sp3, gi, player_id=pid, player_slot=slot))
            players[name] = ent
        except Exception:
            continue

    # probable pitchers: strikeout ladders 4+..10+
    pitchers = {}
    for raw, gi in games:
        for side, opp in (("away", "home"), ("home", "away")):
            pp = raw["teams"][side].get("probablePitcher")
            if not pp:
                continue
            name = pp["fullName"]
            ent = {"game": f"{gi.away_name} @ {gi.home_name}", "ks": {}}
            try:
                for k in range(4, 11):
                    sp = PropSpec(sport="MLB", market_family="count_event",
                                  event="strikeout", scope="player", player=name,
                                  constraints=Constraints(count=k, comparator="at_least"))
                    ent["ks"][k] = quote(sp, gi, player_id=pp["id"])
                pitchers[name] = ent
            except Exception:
                continue

    graded = grade_yesterday(yesterday, s)

    data = {"date": today,
            "builtAt": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
            "board": board, "extras": extras,
            "messiExact": messi_exact, "messiAtLeast": messi_atleast,
            "players": players, "pitchers": pitchers, "yesterday": graded}

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    (HISTORY_DIR / f"{today}.json").write_text(json.dumps(
        {"date": today, "board": [{"gamePk": g["gamePk"], "matchup": g["matchup"],
                                   "innings": g["innings"]} for g in board]}))

    html = TEMPLATE.read_text()
    payload = json.dumps(data).replace("</", "<\\/")
    return html.replace("__DATA__", payload)


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "web" / "phone_demo_built.html"
    out.write_text(build())
    print(f"built {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
