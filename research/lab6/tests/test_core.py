"""Tests for research/lab6/core.py: the no-vig math (multiplicative and power), the no-lookahead snapshot
alignment and the closing line, the name matching and the game matcher, the game builder (2-way and soccer 3-way,
sides, settlement prices, fee family), the side -> Pinnacle mapping, buyable prints, and the entry rule's fees,
settlement, margin, window and one-bet-per-game logic."""

import json
import math

import core as C
import numpy as np
import pandas as pd
import pytest

T0 = 1_785_000_000.0  # 2026-07-25, inside lab 4's TRAIN split


# --- no-vig --------------------------------------------------------------------------------------------------------


def test_multiplicative_removes_margin_in_proportion():
    p = C.novig_multiplicative(np.array([1.9, 1.9]))
    assert p == pytest.approx([0.5, 0.5])
    odds = np.array([1.5, 2.8])
    q = 1 / odds
    p = C.novig_multiplicative(odds)
    assert p.sum() == pytest.approx(1.0)
    assert p == pytest.approx(q / q.sum())
    assert C.overround(odds) == pytest.approx(q.sum() - 1)


def test_power_sums_to_one_and_shades_the_longshot_more():
    odds = np.array([1.25, 4.6])  # a 4 % overround
    pm, pp = C.novig_multiplicative(odds), C.novig_power(odds)
    assert pp.sum() == pytest.approx(1.0, abs=1e-9)
    assert pp[1] < pm[1] and pp[0] > pm[0]  # the longshot carries more of the margin under power
    q = 1 / odds
    k = math.log(pp[0]) / math.log(q[0])
    assert k > 1 and pp[1] == pytest.approx(q[1] ** k, rel=1e-6)
    three = np.array([2.1, 3.4, 3.6])
    assert C.novig_power(three).sum() == pytest.approx(1.0, abs=1e-9)
    fair = np.array([2.0, 2.0])  # no margin: both methods return the implied probabilities
    assert C.novig_power(fair) == pytest.approx([0.5, 0.5])


# --- alignment (no lookahead) --------------------------------------------------------------------------------------


def test_snapshot_index_never_uses_a_later_snapshot():
    snaps = np.array([T0, T0 + 600, T0 + 1200])
    commence = T0 + 3600
    t = np.array([T0 - 1, T0, T0 + 599, T0 + 600, T0 + 601, T0 + 1199, T0 + 1200 + 1800, T0 + 1200 + 1801])
    j = C.snapshot_index(snaps, t, commence, staleness_s=1800)
    assert j.tolist() == [-1, 0, 0, 1, 1, 1, 2, -1]  # at-or-before only; 30 min staleness
    # a snapshot at or after the start is never used, even for a print before it
    j = C.snapshot_index(np.array([T0, T0 + 3600]), np.array([T0 + 3599]), commence=T0 + 3600, staleness_s=10**6)
    assert j.tolist() == [0]
    j = C.snapshot_index(np.array([T0 + 3600]), np.array([T0 + 3700]), commence=T0 + 3600, staleness_s=10**6)
    assert j.tolist() == [-1]


def test_closing_index_is_the_last_snapshot_before_the_start():
    snaps = np.array([T0, T0 + 3000, T0 + 3500, T0 + 3600])
    assert C.closing_index(snaps, T0 + 3600) == 2
    assert C.closing_index(np.array([T0]), T0 + 3600, max_age_s=1800) == -1  # too old to be a close


# --- matching ------------------------------------------------------------------------------------------------------


def test_name_sim_handles_nicknames_fillers_accents_and_aliases():
    assert C.name_sim("Jets", "New York Jets") == 1.0
    assert C.name_sim("Real Betis Balompié", "Real Betis") == 1.0
    assert C.name_sim("FC Bayern München", "Bayern Munich") == 1.0
    assert C.name_sim("CA Mineiro", "Atletico Mineiro") == 1.0
    assert C.name_sim("São Paulo FC", "Sao Paulo") == 1.0
    assert C.name_sim("Kansas City Royals", "Minnesota Twins") < C.MIN_SIM
    assert C.name_sim("Manchester United FC", "Manchester City") < 1.0


def _events(rows):
    return pd.DataFrame(rows, columns=["sport_key", "event_id", "home", "away", "commence"])


def _game(gid, a, b, start, keys=("americanfootball_nfl",), league="nfl", kind="2way"):
    return {"game_id": gid, "league": league, "kind": kind, "sport_keys": json.dumps(list(keys)), "team_a": a,
            "team_b": b, "game_start": start}


def test_match_games_pairs_teams_either_way_within_the_time_tolerance():
    games = pd.DataFrame([
        _game("nfl-nyj-pit", "Jets", "Steelers", T0),
        _game("nfl-dal-nyg", "Cowboys", "Giants", T0),
        _game("nfl-far", "Bears", "Lions", T0, keys=("americanfootball_ncaaf",)),
        _game("mlb-x", "Kansas City Royals", "Minnesota Twins", T0, keys=(), league="lol"),
        _game("nfl-bad", "Packers", "Vikings", T0),
    ])
    events = _events([
        ("americanfootball_nfl", "e1", "Pittsburgh Steelers", "New York Jets", T0 + 300),
        ("americanfootball_nfl", "e2", "Dallas Cowboys", "New York Giants", T0 - 600),
        ("americanfootball_ncaaf", "e3", "Chicago Bears", "Detroit Lions", T0 + 5 * 3600),  # outside 3 h
        ("americanfootball_nfl", "e4", "Green Bay Packers", "Chicago Bears", T0),  # one team only
    ])
    res = C.match_games(games, events)
    m = res.games.set_index("game_id")
    assert set(m.index) == {"nfl-nyj-pit", "nfl-dal-nyg"}
    assert m.loc["nfl-nyj-pit", "event_id"] == "e1" and not m.loc["nfl-nyj-pit", "a_is_home"]
    assert m.loc["nfl-dal-nyg", "a_is_home"]
    reasons = res.failures.set_index("game_id")["reason"].to_dict()
    assert reasons["nfl-far"] == "no Pinnacle event near the start time"
    assert reasons["mlb-x"] == "league not covered"
    assert reasons["nfl-bad"] == "team names do not match"


def test_sport_keys_split_by_date_and_format():
    assert C.sport_keys_for("nfl", "Jets vs. Steelers", "2way", C._ts("2026-08-20")) == ("americanfootball_nfl_preseason",)
    assert C.sport_keys_for("nfl", "Jets vs. Steelers", "2way", C._ts("2026-09-20")) == ("americanfootball_nfl",)
    assert C.sport_keys_for("ucl", "", "3way", C._ts("2026-08-20")) == ("soccer_uefa_champs_league_qualification",)
    assert C.sport_keys_for("crint", "ODI Series England vs India: England vs India", "2way", T0) == ("cricket_odi",)
    assert C.sport_keys_for("crint", "Asian Games Men: India vs Afghanistan", "2way", T0) == ()
    assert C.sport_keys_for("atp", "US Open ATP: A vs B", "2way", T0) == ("tennis_atp_us_open",)
    assert C.sport_keys_for("atp", "US Open, Qualification ATP: A vs B", "2way", T0) == ()
    assert C.sport_keys_for("cs2", "Counter-Strike: A vs B", "2way", T0) == ()


# --- the game builder ----------------------------------------------------------------------------------------------


def market(mid, slug, event_slug, question, outcomes, prices, closed=T0 + 4 * 3600, title=None, fee="sports_fees_v3"):
    return {"id": str(mid), "slug": slug, "event_slug": event_slug, "event_title": title or question,
            "question": question, "outcomes": json.dumps(outcomes), "outcome_prices": json.dumps(prices),
            "winner_index": prices.index(1.0) if 1.0 in prices else -1, "closed_time": closed,
            "fee_type": fee, "fees_enabled": True, "n_outcomes": len(outcomes)}


def soccer_markets(slug="epl-liv-not-2026-07-25", home_wins=True):
    title = "Liverpool FC vs. Nottingham Forest FC"
    hw, aw = ([1.0, 0.0], [0.0, 1.0]) if home_wins else ([0.0, 1.0], [1.0, 0.0])
    return [
        market(11, f"{slug}-liv", slug, "Will Liverpool FC win on 2026-07-25?", ["Yes", "No"], hw, title=title),
        market(12, f"{slug}-not", slug, "Will Nottingham Forest FC win on 2026-07-25?", ["Yes", "No"], aw, title=title),
        market(13, f"{slug}-draw", slug, "Will Liverpool FC vs. Nottingham Forest FC end in a draw?", ["Yes", "No"],
               [0.0, 1.0], title=title),
        market(14, f"{slug}-total-2pt5", slug, "Liverpool FC vs. Nottingham Forest FC: O/U 2.5", ["Over", "Under"],
               [1.0, 0.0], title=title),
    ]


def test_build_games_two_way_and_three_way():
    rows = [
        market(1, "mlb-kc-min-2026-07-25", "mlb-kc-min-2026-07-25", "Kansas City Royals vs. Minnesota Twins",
               ["Kansas City Royals", "Minnesota Twins"], [0.0, 1.0]),
        market(2, "mlb-kc-min-2026-07-25-total-8pt5", "mlb-kc-min-2026-07-25", "Kansas City Royals vs. Minnesota "
               "Twins: O/U 8.5", ["Over", "Under"], [1.0, 0.0]),
        market(3, "cs2-a-b-2026-07-25", "cs2-a-b-2026-07-25", "Counter-Strike: A vs B (BO3)", ["A", "B"], [0.5, 0.5]),
        *soccer_markets(),
    ]
    meta = pd.DataFrame({"id": ["1", "11", "12", "13"], "game_start": [T0, T0, T0, T0 + 60]})
    games, sides = C.build_games(pd.DataFrame(rows), meta)
    g = games.set_index("game_id")
    assert g.loc["mlb-kc-min-2026-07-25", "kind"] == "2way"
    assert json.loads(g.loc["mlb-kc-min-2026-07-25", "sport_keys"]) == ["baseball_mlb"]
    assert json.loads(g.loc["cs2-a-b-2026-07-25", "sport_keys"]) == []
    assert not g.loc["cs2-a-b-2026-07-25", "clean"]  # a 50/50 resolution
    s3 = g.loc["epl-liv-not-2026-07-25"]
    assert s3["kind"] == "3way" and s3["team_a"] == "Liverpool FC" and s3["game_start"] == T0
    sd = sides[sides["game_id"] == "epl-liv-not-2026-07-25"].set_index(["market_id", "o"])
    assert sd.loc[("11", 0), "result"] == "home" and sd.loc[("12", 0), "result"] == "away"
    assert sd.loc[("13", 0), "result"] == "draw" and sd.loc[("13", 1), "final"] == 1.0
    assert sd.loc[("11", 0), "final"] == 1.0 and not sd.loc[("11", 1), "yes"]
    assert (sides["rate"] == 0.05).all() and (sides["family"] == "sports").all()
    two = sides[sides["game_id"] == "mlb-kc-min-2026-07-25"].set_index("o")
    assert two.loc[0, "team"] == "Kansas City Royals" and two.loc[1, "final"] == 1.0
    assert games.set_index("game_id").loc["mlb-kc-min-2026-07-25", "split"] == "train"


def _line(home_odds, away_odds, draw_odds=None, ts=(T0 - 3600, T0 - 60)):
    names = ["Home", "Away"] + (["Draw"] if draw_odds else [])
    rows = []
    for t in ts:
        prices = [home_odds, away_odds] + ([draw_odds] if draw_odds else [])
        rows.append({"event_id": "e", "snap_ts": t, "home": "Home", "away": "Away", "names": json.dumps(names),
                     "prices": json.dumps(prices)})
    return C.event_lines(pd.DataFrame(rows))["e"]


def test_side_fair_maps_each_polymarket_side_to_the_right_pinnacle_result():
    line = _line(2.0, 4.0, 3.6)
    p = C.novig_multiplicative(np.array([2.0, 4.0, 3.6]))
    # soccer: Polymarket's home is Pinnacle's home when a_is_home, else Pinnacle's away
    assert C.side_fair(line, "mult", "home", True, True)[0] == pytest.approx(p[0])
    assert C.side_fair(line, "mult", "home", True, False)[0] == pytest.approx(p[1])
    assert C.side_fair(line, "mult", "away", False, True)[0] == pytest.approx(1 - p[1])
    assert C.side_fair(line, "mult", "draw", True, True)[0] == pytest.approx(p[2])
    two = _line(1.5, 2.8)
    q = C.novig_multiplicative(np.array([1.5, 2.8]))
    assert C.side_fair(two, "mult", "team", True, a_is_home=False, team_is_a=True)[0] == pytest.approx(q[1])
    assert C.side_fair(two, "mult", "team", True, a_is_home=True, team_is_a=False)[0] == pytest.approx(q[1])


def test_event_lines_drops_rows_that_do_not_cover_both_teams():
    rows = [{"event_id": "e", "snap_ts": T0, "home": "Home", "away": "Away", "names": json.dumps(["Home", "Other"]),
             "prices": json.dumps([1.9, 1.9])},
            {"event_id": "e", "snap_ts": T0 + 1, "home": "Home", "away": "Away", "names": json.dumps(["Home", "Away"]),
             "prices": json.dumps([1.9, 1.0])}]
    assert C.event_lines(pd.DataFrame(rows)) == {}


# --- the entry rule ------------------------------------------------------------------------------------------------


def test_buyable_prints_maps_the_other_token_sells():
    tape = pd.DataFrame({"ts": [1, 2, 3, 4], "price": [0.40, 0.62, 0.41, 0.60], "size": [50, 50, 50, 50],
                         "side": ["BUY", "SELL", "SELL", "BUY"], "outcome_index": [0, 1, 0, 1]})
    b0 = C.buyable_prints(tape, 0)
    assert b0["ts"].tolist() == [1, 2] and b0["price"].tolist() == pytest.approx([0.40, 0.38])
    b1 = C.buyable_prints(tape, 1)
    assert b1["ts"].tolist() == [3, 4] and b1["price"].tolist() == pytest.approx([0.59, 0.60])


def _two_way_universe(prints, home_odds=1.5, away_odds=2.8, final=(1.0, 0.0), snaps=None):
    """One MLB game: team A (outcome 0) is Pinnacle's away team. ``prints``: (ts, price, size, side, outcome)."""
    commence = T0
    games = pd.DataFrame([{"game_id": "g1", "league": "mlb", "kind": "2way", "team_a": "A", "team_b": "B",
                           "game_start": commence, "commence": commence, "event_id": "e", "a_is_home": False,
                           "closed_time": commence + 4 * 3600, "question": "A vs. B", "split": "train"}])
    sides = pd.DataFrame([{"game_id": "g1", "market_id": "m1", "o": o, "result": "team", "team": t, "yes": True,
                           "final": final[o], "rate": 0.05, "family": "sports"} for o, t in ((0, "A"), (1, "B"))])
    snaps = snaps or (commence - 7 * 3600, commence - 3600, commence - 120)
    rows = [{"event_id": "e", "snap_ts": s, "home": "Home", "away": "Away", "names": json.dumps(["Home", "Away"]),
             "prices": json.dumps([home_odds, away_odds])} for s in snaps]
    tape = pd.DataFrame(prints, columns=["ts", "price", "size", "side", "outcome_index"])
    return C.Universe("train", games, sides, C.event_lines(pd.DataFrame(rows)), {"m1": tape})


def test_entry_rule_fee_tick_and_settlement():
    # Pinnacle: home 1.5 / away 2.8 -> fair(away = team A) = (1/2.8) / (1/1.5 + 1/2.8)
    fair_a = (1 / 2.8) / (1 / 1.5 + 1 / 2.8)
    prints = [(T0 - 3000, 0.30, 100.0, "BUY", 0)]  # 50 min before the start, 10 min after the T-60 snapshot
    u = _two_way_universe(prints)
    cands = C.all_candidates(u, "mult", 24 * 3600)
    assert len(cands) == 1
    c = cands.iloc[0]
    assert c["p_exec"] == pytest.approx(0.31) and c["fair"] == pytest.approx(fair_a)
    assert c["edge"] == pytest.approx(fair_a - 0.31 - 0.05 * 0.31 * 0.69)
    bets = C.cell_bets(cands, u.games, 1.0, 0.02)
    assert len(bets) == 1
    b = bets.iloc[0]
    shares = 20 / 0.31
    fee = shares * 0.05 * 0.31 * 0.69
    assert b["fee_usd"] == pytest.approx(fee)
    assert b["pnl_usd"] == pytest.approx(shares - fee - 20) and b["won"]
    assert b["clv"] == pytest.approx(fair_a - 0.31)
    lose = _two_way_universe(prints, final=(0.0, 1.0))
    lb = C.cell_bets(C.all_candidates(lose, "mult", 24 * 3600), lose.games, 1.0, 0.02).iloc[0]
    assert lb["pnl_usd"] == pytest.approx(-fee - 20) and not lb["won"]
    push = _two_way_universe(prints, final=(0.5, 0.5))
    pb = C.cell_bets(C.all_candidates(push, "mult", 24 * 3600), push.games, 1.0, 0.02).iloc[0]
    assert pb["pnl_usd"] == pytest.approx(0.5 * shares - fee - 20) and pb["push"]


def test_entry_rule_margin_window_size_staleness_and_one_bet_per_game():
    fair_a = (1 / 2.8) / (1 / 1.5 + 1 / 2.8)  # ~0.349
    prints = [
        (T0 - 7 * 3600 + 60, 0.30, 100.0, "BUY", 0),  # inside 24 h / outside 6 h: first signal for W24
        (T0 - 3 * 3600, 0.20, 100.0, "BUY", 0),  # 4 h after the last snapshot: stale, ignored
        (T0 - 3000, 0.32, 5.0, "BUY", 0),  # too small for a $20 ticket
        (T0 - 2900, 0.33, 100.0, "SELL", 1),  # = A at 0.67: no edge
        (T0 - 2800, 0.30, 100.0, "BUY", 0),  # first W1 signal (edge ~0.028)
        (T0 - 100, 0.20, 100.0, "BUY", 0),  # a later, bigger edge never replaces the first
        (T0 + 60, 0.10, 100.0, "BUY", 0),  # after the start: never
    ]
    u = _two_way_universe(prints)
    cands = C.all_candidates(u, "mult", 24 * 3600)
    assert T0 - 3 * 3600 not in cands["t"].tolist() and T0 + 60 not in cands["t"].tolist()
    assert T0 - 3000 not in cands["t"].tolist()
    b24 = C.cell_bets(cands, u.games, 24.0, 0.01)
    assert b24["t_signal"].tolist() == [T0 - 7 * 3600 + 60]
    b1 = C.cell_bets(cands, u.games, 1.0, 0.01)
    assert b1["t_signal"].tolist() == [T0 - 2800]
    assert b1.iloc[0]["edge"] == pytest.approx(fair_a - 0.31 - 0.05 * 0.31 * 0.69)
    b1m = C.cell_bets(cands, u.games, 1.0, 0.03)  # the 0.30 print's edge is below 3 points: the later one
    assert b1m["t_signal"].tolist() == [T0 - 100]
    assert C.cell_bets(cands, u.games, 1.0, 0.5).empty


def test_summarize_and_bar_use_lab4_readings():
    rng = np.random.default_rng(0)
    n = 150
    bets = pd.DataFrame({
        "id": [f"m{i}" for i in range(n)], "event": [f"g{i}" for i in range(n)], "family": "sports",
        "league": "mlb", "question": "q", "closed_time": T0 + np.arange(n) * 3600.0,
        "day": [f"2026-07-{1 + i // 10:02d}" for i in range(n)], "t_signal": T0, "t_exec": T0 + np.arange(n),
        "p_exec": 0.5, "fair": 0.56, "edge": 0.0475, "close_fair": 0.55, "clv": 0.05, "won": rng.random(n) < 0.7,
        "push": False, "fee_usd": 0.5, "missed": False, "old_rule_bid_side": False, "result": "team", "yes": True,
        "o": 0, "lock_h": 2.0,
    })
    bets["pnl_usd"] = np.where(bets["won"], 40.0, 0.0) - 0.5 - 20.0
    bets["net"] = bets["pnl_usd"] / 20.0
    s = C.summarize(bets, "train", B=300)
    assert s["n"] == n and s["clv"]["mean"] == pytest.approx(0.05) and s["clv"]["beat_share"] == 1.0
    assert s["model_net"] == pytest.approx(0.56 / 0.5 - 1 - 0.5 / 20)
    assert C.qualifies(s) == (s["mean_net"] > 0 and s["ci95"][0] > 0)
    assert not C.qualifies({**s, "n": 99})


def test_latency_exec_fills_at_the_next_buyable_print():
    prints = [(T0 - 3000, 0.30, 100.0, "BUY", 0), (T0 - 2995, 0.29, 100.0, "BUY", 0),
              (T0 - 2985, 0.33, 100.0, "BUY", 0)]
    u = _two_way_universe(prints)
    bets = C.cell_bets(C.all_candidates(u, "mult", 24 * 3600), u.games, 1.0, 0.0)
    lat = C.latency_exec(bets, u)
    assert lat.iloc[0]["p_exec"] == pytest.approx(0.33) and not lat.iloc[0]["missed"]
    u2 = _two_way_universe(prints[:1])
    lat2 = C.latency_exec(C.cell_bets(C.all_candidates(u2, "mult", 24 * 3600), u2.games, 1.0, 0.0), u2)
    assert bool(lat2.iloc[0]["missed"])


def test_clv_baseline_buys_every_side_at_the_window_open():
    prints = [(T0 - 3000, 0.30, 100.0, "BUY", 0), (T0 - 2990, 0.69, 100.0, "BUY", 1)]
    u = _two_way_universe(prints)
    base = C.clv_baseline(u, "mult", 1.0)
    assert len(base) == 2
    fair_a = (1 / 2.8) / (1 / 1.5 + 1 / 2.8)
    r = base.set_index("o")
    assert r.loc[0, "clv"] == pytest.approx(fair_a - 0.31) and r.loc[1, "clv"] == pytest.approx(1 - fair_a - 0.70)
    assert C.baseline_reading(base, B=100)["n"] == 2


def test_record_run_upserts(tmp_path):
    led = tmp_path / "trials.json"
    C.record_run({"lab": "lab6", "hyp": "H1", "cell": "x", "split": "train", "stage": "train", "n": 1}, led)
    C.record_run({"lab": "lab6", "hyp": "H1", "cell": "x", "split": "train", "stage": "train", "n": 2}, led)
    doc = json.loads(led.read_text())
    assert len(doc) == 1 and doc[0]["n"] == 2
