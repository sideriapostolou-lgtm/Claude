"""
PROP ENGINE v0 — AI micro-prop pricing prototype
Prices: "Home run in inning N" (either team / specific team) for tonight's real MLB slate.
Data: MLB Stats API (free, official). Model: Poisson on HR intensity per team-inning.
lambda(team, inning) = teamHR_perPA * expPA_inning * pitcherFactor * parkFactor * inningFactor

Kept verbatim as the proven v0 reference + regression baseline
(ran successfully 2026-07-06 against the live slate).
"""
import requests, math, json, sys
from datetime import date

S = requests.Session()
S.headers.update({"User-Agent": "prop-engine-v0"})
BASE = "https://statsapi.mlb.com/api/v1"
SEASON = 2026
TODAY = "07/06/2026"

def get(url, params=None):
    r = S.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def main():
    # ---------- 1. Tonight's slate + probable pitchers ----------
    sched = get(f"{BASE}/schedule", {"sportId": 1, "date": TODAY, "hydrate": "probablePitcher,team"})
    games = []
    for d in sched.get("dates", []):
        for g in d.get("games", []):
            if g.get("gameType") != "R":
                continue
            games.append(g)
    print(f"SLATE {TODAY}: {len(games)} regular-season games\n")
    if not games:
        sys.exit("No games today — rerun with tomorrow's date.")

    # ---------- 2. Team hitting rates (HR per PA) ----------
    team_rates = {}
    try:
        ts = get(f"{BASE}/teams/stats", {"sportIds": 1, "group": "hitting", "stats": "season", "season": SEASON})
        for blk in ts.get("stats", []):
            for sp in blk.get("splits", []):
                t = sp.get("team", {})
                st = sp.get("stat", {})
                hr = float(st.get("homeRuns", 0) or 0)
                pa = float(st.get("plateAppearances", 0) or 0)
                if pa > 0:
                    team_rates[t.get("id")] = {"name": t.get("name"), "hr_pa": hr / pa, "hr": hr, "pa": pa}
    except Exception as e:
        print("team stats fetch failed:", e)

    league_hr_pa = (sum(v["hr"] for v in team_rates.values()) / sum(v["pa"] for v in team_rates.values())) if team_rates else 0.030
    print(f"League HR/PA: {league_hr_pa:.4f}  (teams loaded: {len(team_rates)})")

    # ---------- 3. Probable pitcher HR-suppression factors ----------
    pids = []
    for g in games:
        for side in ("away", "home"):
            pp = g["teams"][side].get("probablePitcher")
            if pp:
                pids.append(str(pp["id"]))
    pitch_factor = {}
    LEAGUE_HR9 = 1.10
    if pids:
        try:
            pp = get(f"{BASE}/people", {"personIds": ",".join(sorted(set(pids))),
                                         "hydrate": f"stats(group=[pitching],type=[season],season={SEASON})"})
            for person in pp.get("people", []):
                try:
                    st = person["stats"][0]["splits"][0]["stat"]
                    ip_raw = str(st.get("inningsPitched", "0"))
                    whole, _, frac = ip_raw.partition(".")
                    ip = float(whole) + (int(frac) / 3.0 if frac else 0.0)
                    hr = float(st.get("homeRuns", 0) or 0)
                    if ip >= 20:
                        f = (9.0 * hr / ip) / LEAGUE_HR9
                        pitch_factor[person["id"]] = max(0.60, min(1.60, f))
                except Exception:
                    pass
        except Exception as e:
            print("pitcher stats fetch failed:", e)

    # ---------- 4. Park + inning shape (v0 priors; v1 fits these empirically) ----------
    PARK = {"Coors": 1.12, "Great American": 1.28, "Yankee": 1.18, "Citizens Bank": 1.12,
            "Dodger": 1.05, "Oracle": 0.82, "T-Mobile": 0.88, "Kauffman": 0.85,
            "Petco": 0.92, "Fenway": 0.95, "loanDepot": 0.88, "Camden": 1.05}
    def park_factor(venue):
        for k, v in PARK.items():
            if k.lower() in venue.lower():
                return v
        return 1.00
    # HRs skew toward inning 1 (top of order guaranteed); slight fades late
    INNING_F = {1: 1.15, 2: 0.92, 3: 1.00, 4: 1.03, 5: 1.00, 6: 1.00, 7: 0.95, 8: 0.95, 9: 0.85}
    EXP_PA_INNING = 4.25
    MARGIN = 1.12  # 12% vig on exotics

    def american(p):
        p = min(max(p, 0.001), 0.985)
        return f"-{round(100*p/(1-p))}" if p >= 0.5 else f"+{round(100*(1-p)/p)}"

    def price_inning_hr(g, inning):
        venue = g.get("venue", {}).get("name", "")
        pf = park_factor(venue)
        lams = {}
        for side, opp in (("away", "home"), ("home", "away")):
            team = g["teams"][side]["team"]
            rate = team_rates.get(team["id"], {}).get("hr_pa", league_hr_pa)
            opp_pp = g["teams"][opp].get("probablePitcher")
            ptf = pitch_factor.get(opp_pp["id"], 1.0) if opp_pp else 1.0
            ptf = ptf if inning <= 5 else 1.0  # starter innings only; bullpen ~ league in v0
            lams[side] = rate * EXP_PA_INNING * ptf * pf * INNING_F.get(inning, 1.0)
        p_side = {s: 1 - math.exp(-l) for s, l in lams.items()}
        p_either = 1 - math.exp(-(lams["away"] + lams["home"]))
        return lams, p_side, p_either

    rows = []
    for g in games:
        away = g["teams"]["away"]["team"]["name"]
        home = g["teams"]["home"]["team"]["name"]
        lams, p_side, p_e = price_inning_hr(g, 3)
        app = g["teams"]["away"].get("probablePitcher", {}).get("fullName", "TBD")
        hpp = g["teams"]["home"].get("probablePitcher", {}).get("fullName", "TBD")
        rows.append({"match": f"{away} @ {home}", "sp": f"{app} v {hpp}",
                     "p": p_e, "fair": american(p_e), "book": american(min(p_e * MARGIN, 0.985)),
                     "p_home": p_side["home"], "home": home,
                     "venue": g.get("venue", {}).get("name", "")})

    rows.sort(key=lambda r: -r["p"])
    print("\n=== MARKET: 'Home run in the 3rd inning' (either team) ===")
    for r in rows:
        print(f"{r['match']:<42} P={r['p']*100:4.1f}%  fair {r['fair']:>5}  BOOK {r['book']:>5}")

    print("\n=== Hottest single-team 3rd-inning HR markets ===")
    team_rows = []
    for g in games:
        lams, p_side, _ = price_inning_hr(g, 3)
        for side in ("away", "home"):
            nm = g["teams"][side]["team"]["name"]
            team_rows.append((nm, p_side[side], g["teams"]["away"]["team"]["name"] + " @ " + g["teams"]["home"]["team"]["name"]))
    team_rows.sort(key=lambda x: -x[1])
    for nm, p, m in team_rows[:5]:
        print(f"{nm:<28} P={p*100:4.1f}%  fair {american(p):>5}  BOOK {american(min(p*MARGIN,0.985)):>5}   ({m})")

    # ---------- 5. The "you say it, we price it" flow ----------
    print("\n=== SPOKEN PROP -> STRUCTURED -> PRICED (demo) ===")
    if rows:
        top = rows[0]
        demo = {"utterance": "hey I think third inning home run",
                "parsed": {"sport": "MLB", "market_family": "inning_event", "event": "home_run",
                           "inning": 3, "scope": "either_team", "game": top["match"]},
                "fair_prob": round(top["p"], 4), "book_odds": top["book"]}
        print(json.dumps(demo, indent=1))
    print(json.dumps({"utterance": "Messi to score from exactly 29 yards out",
                      "parsed": {"sport": "soccer", "market_family": "coordinate_event", "player": "Lionel Messi",
                                 "event": "goal", "distance_yards": 29, "tolerance": 0.5},
                      "status": "needs shot-coordinate model — StatsBomb open data has Messi's entire "
                                "La Liga career with x/y shot coords, FREE. Pipeline specced in build doc."}, indent=1))

if __name__ == "__main__":
    main()
