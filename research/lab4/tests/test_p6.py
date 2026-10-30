"""Tests for research/lab4/P6 (Amendment 5): the league -> sport map, the YES-only / either-team outcome rule, the
in-play window (no buy before the start or after the final whistle), the US fee, the tennis finish heuristic and the
TRAIN verdict rule, on a tiny synthetic universe."""

import json
import sys
from pathlib import Path

import core as C
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "P6"))

import p6 as P
from sports import league_of, sport_of

T0 = 1_783_000_000.0  # 2026-07-02, inside TRAIN


def test_sport_map_codes_patterns_and_tags():
    assert sport_of("atp-tiafoe-bublik-2026-07-04") == "tennis"
    assert sport_of("itfwo-a-b-2026-10-10") == "tennis"
    assert sport_of("setkameua-denys-deny-2026-07-25") == "table tennis"
    assert sport_of("ebfsa-bol-juv-2026-10-10") == "e-soccer"
    assert sport_of("cs2-g2a-navij1-2026-10-09") == "esports"
    assert (
        sport_of("lec-tol-mon-2026-08-01") == "soccer"
    )  # Leagues Cup on polymarket.com
    assert sport_of("crict20blast-ham-not-2026-07-10") == "cricket"
    assert sport_of("bkfibaw-usa-fra-2026-08-01") == "basketball"
    assert sport_of("del-ein-mun-2026-10-09") == "hockey"
    assert sport_of("f1-bahrain-gp") == "other" and sport_of(None) == "other"
    assert (
        sport_of("pdc-cob-udc-2026-10-10", tags=["sports", "soccer", "pdc"]) == "soccer"
    )
    assert sport_of("x", tags=["sports", "efootball", "ebattles"]) == "e-soccer"
    assert sport_of("x", tags=["table-tennis", "setka"]) == "table tennis"
    assert league_of("EPL-ars-che") == "epl"


def test_allowed_outcomes():
    assert P.allowed_outcomes('["Yes","No"]') == (0,)
    assert P.allowed_outcomes('["No","Yes"]') == (1,)
    assert P.allowed_outcomes('["Roma","Lazio"]') == (0, 1)
    assert P.allowed_outcomes('["Roma","Lazio"]', first_only=True) == (0,)


def _market(mid, outcomes, winner, start, finished, closed, slug="atp-a-b-2026-07-02"):
    return {
        "id": mid,
        "event_slug": slug,
        "question": "Q",
        "outcomes": outcomes,
        "winner_index": winner,
        "closed_time": closed,
        "end_date": closed + 7 * 86400,
        "start": start,
        "finished": finished,
        "family": "sports",
        "rate": 0.05,
        "sport": sport_of(slug),
        "league": league_of(slug),
        "event_score": "6-4, 6-3",
        "end": finished,
        "end_kind": P.WHISTLE,
    }


def _tape(rows):
    ts, p0, buy0 = zip(*rows, strict=True)
    return pd.DataFrame({"ts": ts, "p0": p0, "buy0": buy0, "size": [10.0] * len(ts)})


def test_in_play_window_yes_only_latency_and_us_fee():
    start, fin, closed = T0, T0 + 7200, T0 + 9000
    # m1: Yes/No market; outcome 0 (YES) prints 0.98 BEFORE the start (ignored), then 0.975 in play, filled at 0.98.
    # The NO side at 0.99 earlier in play must be ignored (YES only).
    t1 = _tape(
        [
            (start - 600, 0.98, True),
            (
                start + 100,
                0.01,
                False,
            ),  # a SELL on YES at 0.01 = a buyable NO at 0.99: not allowed
            (start + 3000, 0.975, True),
            (start + 3012, 0.98, True),
            (fin + 60, 0.999, True),
        ]
    )
    # m2: two-team market; only print >= 0.97 comes after the final whistle: no trade.
    t2 = _tape(
        [(start + 100, 0.6, True), (fin + 30, 0.995, True), (fin + 50, 0.996, True)]
    )
    # m3: two-team market; outcome 1 (team B) buyable at 0.97 in play (a SELL on token 0 at 0.03), loses.
    t3 = _tape(
        [
            (start + 500, 0.03, False),
            (start + 520, 0.02, False),
            (start + 4000, 0.9, True),
        ]
    )
    markets = pd.DataFrame(
        [
            _market("m1", '["Yes","No"]', 0, start, fin, closed),
            _market("m2", '["A","B"]', 1, start, fin, closed),
            _market(
                "m3", '["A","B"]', 0, start, fin, closed, slug="atp-c-d-2026-07-02"
            ),
        ]
    )
    ds = C.Dataset("train", markets, {"m1": t1, "m2": t2, "m3": t3})
    tr = P.p6_trades(ds, 0.97).set_index("id")
    assert set(tr.index) == {"m1", "m3"}
    r1 = tr.loc["m1"]
    assert (
        r1["outcome"] == 0
        and r1["p_signal"] == 0.975
        and r1["p_exec"] == 0.98
        and bool(r1["won"])
    )
    shares = 20.0 / 0.98
    fee = shares * 0.0695 * 0.98 * 0.02
    assert np.isclose(r1["net"], (shares - fee - 20.0) / 20.0)
    assert np.isclose(
        r1["net_com"], (shares - shares * 0.05 * 0.98 * 0.02 - 20.0) / 20.0
    )
    assert np.isclose(r1["cents_per_contract"], 100 * (1 - 0.98 - 0.0695 * 0.98 * 0.02))
    r3 = tr.loc["m3"]
    assert r3["outcome"] == 1 and np.isclose(r3["p_exec"], 0.98) and not bool(r3["won"])
    s = P.reading(tr.reset_index(), "train", B=200)
    assert s["n"] == 2 and s["losses"] == 1 and s["n_events"] == 2


def test_tennis_finish():
    assert P.tennis_finish("6-4, 6-7(5-7), 6-7(11-13), 6-4, 3-6") == "completed"
    assert P.tennis_finish("6-4, 6-3") == "completed"
    assert P.tennis_finish("6-4, 3-6, 10-8") == "completed"
    assert P.tennis_finish("6-4, 2-1") == "unfinished"
    assert P.tennis_finish("6-4, 2-1 ret.") == "unfinished"
    assert P.tennis_finish("") == "unknown" and P.tennis_finish(None) == "unknown"


def test_classify():
    base = {
        "n": 400,
        "n_events": 300,
        "mean_net": 0.004,
        "ci95": [0.001, 0.007],
        "losses": 8,
        "worst_case_net": 0.001,
        "gap_ci95": [0.0, 0.01],
    }
    assert P.classify("tennis", base) == "ALLOWED"
    assert P.classify("other", base).startswith("NOT ALLOWED: mixed")
    assert P.classify("tennis", {**base, "n_events": 29}).startswith(
        "BLOCKED: no proof"
    )
    assert P.classify(
        "tennis",
        {
            **base,
            "mean_net": -0.02,
            "ci95": [-0.03, -0.01],
            "gap_ci95": [-0.02, -0.005],
        },
    ).startswith("BLOCKED: proven loser")
    assert P.classify("tennis", {**base, "ci95": [-0.001, 0.007]}).startswith(
        "NOT ALLOWED: unknown"
    )
    assert P.classify("tennis", {**base, "losses": 0}).startswith(
        "NOT ALLOWED: unknown"
    )
    json.dumps(base)


def test_fallback_can_block_but_not_allow():
    good = {
        "n": 400,
        "n_events": 300,
        "mean_net": 0.004,
        "ci95": [0.001, 0.007],
        "losses": 8,
        "worst_case_net": 0.001,
        "gap_ci95": [0.0, 0.01],
    }
    bad = {**good, "gap_ci95": [-0.02, -0.005]}
    assert P.classify("tennis", good, bad).startswith(
        "BLOCKED: proven loser (in its games without"
    )
    assert P.classify("tennis", None, good).startswith("BLOCKED: no proof")
    assert P.classify("tennis", good, {**bad, "n_events": 10}) == "ALLOWED"


def test_end_bound_whistle_or_fallback():
    base = {
        "event_slug": "atp-a-b",
        "closed_time": T0 + 10_000,
        "game_start": T0,
        "event_start": T0,
    }
    markets = pd.DataFrame(
        [
            {**base, "id": "a"},
            {**base, "id": "b", "event_slug": "cs2-x-y"},
            {**base, "id": "c"},
        ]
    )
    meta = pd.DataFrame(
        [
            {
                "id": "a",
                "sports_market_type": "moneyline",
                "game_start": T0,
                "event_start": T0,
                "event_finished": T0 + 6000,
                "event_score": "",
                "description": "",
            },
            {
                "id": "b",
                "sports_market_type": "moneyline",
                "game_start": T0,
                "event_start": T0,
                "event_finished": None,
                "event_score": "",
                "description": "",
            },
            {
                "id": "c",
                "sports_market_type": "moneyline",
                "game_start": T0,
                "event_start": T0,
                "event_finished": T0 + 20_000,
                "event_score": "",
                "description": "",
            },  # after closedTime: invalid
        ]
    )
    m = P.with_game_facts(
        markets.drop(columns=["game_start", "event_start"]), meta
    ).set_index("id")
    assert m.loc["a", "end_kind"] == P.WHISTLE and m.loc["a", "end"] == T0 + 6000
    assert (
        m.loc["b", "end_kind"] == P.FALLBACK
        and m.loc["b", "end"] == T0 + 10_000 - 139 * 60
    )
    assert (
        m.loc["c", "end_kind"] == P.FALLBACK
        and m.loc["c", "end"] == T0 + 10_000 - 38 * 60
    )
    assert P.is_universe(m.reset_index()).all()
