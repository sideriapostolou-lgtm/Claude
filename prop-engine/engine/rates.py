"""Rate providers: the pregame inputs to every MLB pricing model.

Two implementations of the same interface so live pricing and the backtest
share one pricing code path:
  - LiveRates: current-season stats from the MLB Stats API
  - CorpusRates: rates accumulated from the PBP corpus strictly BEFORE a
    given date (walk-forward, no leakage)

Player/pitcher rates are regressed to league mean with pseudo-PA priors so a
hot week doesn't produce insane prices.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Optional, Protocol

import requests

BASE = "https://statsapi.mlb.com/api/v1"
ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "data" / "corpus" / "mlb"

PLAYER_HR_PRIOR_PA = 200      # league-average PAs blended into hitter HR/PA
PLAYER_HIT_PRIOR_PA = 100
PITCHER_PRIOR_PA = 150
PITCHER_FACTOR_CLAMP = (0.60, 1.60)
LEAGUE_HIT_PA = 0.220
LEAGUE_K_PA = 0.222


class Rates(Protocol):
    league_hr_pa: float

    def team_hr_pa(self, team_id: int) -> tuple[float, float]: ...
    def pitcher_hr_factor(self, pitcher_id: Optional[int]) -> tuple[float, float]: ...
    def player_hr_pa(self, player_id: int) -> tuple[float, float]: ...
    def player_hit_pa(self, player_id: int) -> tuple[float, float]: ...
    def pitcher_k_pa(self, pitcher_id: Optional[int]) -> tuple[float, float]: ...


def _regress(successes: float, trials: float, league_rate: float, prior_pa: float) -> tuple[float, float]:
    """Return (regressed rate, effective sample size)."""
    rate = (successes + prior_pa * league_rate) / (trials + prior_pa)
    return rate, trials + prior_pa


class LiveRates:
    """Season-to-date rates from the MLB Stats API."""

    def __init__(self, season: int, session: Optional[requests.Session] = None):
        self.season = season
        self.s = session or requests.Session()
        self.s.headers.update({"User-Agent": "prop-engine"})
        self._teams: dict[int, tuple[float, float]] = {}
        self._team_pitching: dict[int, tuple[float, float]] = {}
        self._players: dict[int, dict] = {}
        self._pitchers: dict[int, dict] = {}
        self.league_hr_pa = 0.030
        self._load_teams()
        self._load_team_pitching()

    def _load_teams(self):
        ts = self.s.get(f"{BASE}/teams/stats",
                        params={"sportIds": 1, "group": "hitting",
                                "stats": "season", "season": self.season},
                        timeout=30).json()
        total_hr = total_pa = 0.0
        for blk in ts.get("stats", []):
            for sp in blk.get("splits", []):
                st = sp.get("stat", {})
                hr = float(st.get("homeRuns", 0) or 0)
                pa = float(st.get("plateAppearances", 0) or 0)
                if pa > 0:
                    self._teams[sp["team"]["id"]] = (hr, pa)
                    total_hr += hr
                    total_pa += pa
        if total_pa:
            self.league_hr_pa = total_hr / total_pa

    def _load_team_pitching(self):
        try:
            ts = self.s.get(f"{BASE}/teams/stats",
                            params={"sportIds": 1, "group": "pitching",
                                    "stats": "season", "season": self.season},
                            timeout=30).json()
            for blk in ts.get("stats", []):
                for sp in blk.get("splits", []):
                    st = sp.get("stat", {})
                    hr = float(st.get("homeRuns", 0) or 0)
                    bf = float(st.get("battersFaced", 0) or 0)
                    if bf > 0:
                        self._team_pitching[sp["team"]["id"]] = (hr, bf)
        except Exception:
            pass

    def team_hr_pa(self, team_id: int) -> tuple[float, float]:
        hr, pa = self._teams.get(team_id, (0.0, 0.0))
        if pa == 0:
            return self.league_hr_pa, 0.0
        return hr / pa, hr

    def team_bullpen_hr_factor(self, team_id: int) -> float:
        """Bullpen HR suppression proxy: team pitching HR/BF vs league.

        Uses full-staff numbers (staff HR/BF is dominated by relievers in the
        innings this factor applies to); splitting out starters is a v2 item.
        """
        hr, bf = self._team_pitching.get(team_id, (0.0, 0.0))
        if bf < 500:
            return 1.0
        factor = (hr / bf) / self.league_hr_pa
        lo, hi = PITCHER_FACTOR_CLAMP
        return min(max(factor, lo), hi)

    def _fetch_person(self, pid: int, group: str) -> dict:
        cache = self._players if group == "hitting" else self._pitchers
        if pid in cache:
            return cache[pid]
        stat = {}
        try:
            r = self.s.get(
                f"{BASE}/people/{pid}",
                params={"hydrate": f"stats(group=[{group}],type=[season],season={self.season})"},
                timeout=30).json()
            stat = r["people"][0]["stats"][0]["splits"][0]["stat"]
        except Exception:
            pass
        cache[pid] = stat
        return stat

    def player_hr_pa(self, player_id: int) -> tuple[float, float]:
        st = self._fetch_person(player_id, "hitting")
        hr = float(st.get("homeRuns", 0) or 0)
        pa = float(st.get("plateAppearances", 0) or 0)
        return _regress(hr, pa, self.league_hr_pa, PLAYER_HR_PRIOR_PA)

    def player_hit_pa(self, player_id: int) -> tuple[float, float]:
        st = self._fetch_person(player_id, "hitting")
        hits = float(st.get("hits", 0) or 0)
        pa = float(st.get("plateAppearances", 0) or 0)
        return _regress(hits, pa, LEAGUE_HIT_PA, PLAYER_HIT_PRIOR_PA)

    def _pitcher_counts(self, pid: int) -> tuple[float, float, float]:
        st = self._fetch_person(pid, "pitching")
        bf = float(st.get("battersFaced", 0) or 0)
        hr = float(st.get("homeRuns", 0) or 0)
        so = float(st.get("strikeOuts", 0) or 0)
        return hr, so, bf

    def pitcher_hr_factor(self, pitcher_id: Optional[int]) -> tuple[float, float]:
        if pitcher_id is None:
            return 1.0, 0.0
        hr, _, bf = self._pitcher_counts(pitcher_id)
        rate, n = _regress(hr, bf, self.league_hr_pa, PITCHER_PRIOR_PA)
        lo, hi = PITCHER_FACTOR_CLAMP
        return min(max(rate / self.league_hr_pa, lo), hi), n

    def pitcher_k_pa(self, pitcher_id: Optional[int]) -> tuple[float, float]:
        if pitcher_id is None:
            return LEAGUE_K_PA, 0.0
        _, so, bf = self._pitcher_counts(pitcher_id)
        return _regress(so, bf, LEAGUE_K_PA, PITCHER_PRIOR_PA)


class CorpusRates:
    """Rates from the PBP corpus using only games strictly before `as_of`.

    This is the walk-forward provider: identical interface, zero leakage.
    """

    def __init__(self, as_of: str, season_start: Optional[str] = None):
        self.as_of = as_of
        self.season = as_of[:4]
        self._team = defaultdict(lambda: [0, 0])      # team -> [hr, pa]
        self._batter = defaultdict(lambda: [0, 0, 0])  # batter -> [hr, hits(unknown->0), pa]
        self._pitcher = defaultdict(lambda: [0, 0, 0])  # pitcher -> [hr, k, bf]
        self.league_hr_pa = 0.030
        self._load()

    def _load(self):
        total_hr = total_pa = 0
        HIT_EVENTS = {"single", "double", "triple", "home_run"}
        for f in sorted(CORPUS_DIR.glob("plays_*.csv")):
            day = f.stem.replace("plays_", "")
            if not day.startswith(self.season) or day >= self.as_of:
                continue
            for r in csv.DictReader(open(f)):
                team = r["bat_team_id"]
                ev = r["event_type"]
                is_hr = ev == "home_run"
                is_hit = ev in HIT_EVENTS
                is_k = ev in ("strikeout", "strikeout_double_play")
                self._team[team][0] += is_hr
                self._team[team][1] += 1
                b = self._batter[r["batter_id"]]
                b[0] += is_hr
                b[1] += is_hit
                b[2] += 1
                p = self._pitcher[r["pitcher_id"]]
                p[0] += is_hr
                p[1] += is_k
                p[2] += 1
                total_hr += is_hr
                total_pa += 1
        if total_pa:
            self.league_hr_pa = total_hr / total_pa
        self.total_pa = total_pa

    def team_hr_pa(self, team_id: int) -> tuple[float, float]:
        hr, pa = self._team.get(str(team_id), (0, 0))
        if pa < 200:
            return self.league_hr_pa, float(hr)
        return hr / pa, float(hr)

    def player_hr_pa(self, player_id: int) -> tuple[float, float]:
        hr, _, pa = self._batter.get(str(player_id), (0, 0, 0))
        return _regress(hr, pa, self.league_hr_pa, PLAYER_HR_PRIOR_PA)

    def player_hit_pa(self, player_id: int) -> tuple[float, float]:
        _, hits, pa = self._batter.get(str(player_id), (0, 0, 0))
        return _regress(hits, pa, LEAGUE_HIT_PA, PLAYER_HIT_PRIOR_PA)

    def pitcher_hr_factor(self, pitcher_id: Optional[int]) -> tuple[float, float]:
        if pitcher_id is None:
            return 1.0, 0.0
        hr, _, bf = self._pitcher.get(str(pitcher_id), (0, 0, 0))
        rate, n = _regress(hr, bf, self.league_hr_pa, PITCHER_PRIOR_PA)
        lo, hi = PITCHER_FACTOR_CLAMP
        return min(max(rate / self.league_hr_pa, lo), hi), n

    def pitcher_k_pa(self, pitcher_id: Optional[int]) -> tuple[float, float]:
        if pitcher_id is None:
            return LEAGUE_K_PA, 0.0
        _, so, bf = self._pitcher.get(str(pitcher_id), (0, 0, 0))
        return _regress(so, bf, LEAGUE_K_PA, PITCHER_PRIOR_PA)
