"""A tiny end-to-end fixture with fake odds: a lab-4-shaped cache (markets.parquet, tapes) and a lab-6 data
directory (gamma_meta, pregame, matches, pinnacle) built from synthetic games whose Polymarket price sits
below or above a fake Pinnacle line. Runs TRAIN and VAL through run.py and checks the stage files, the
shortlist / selection logic, the TEST gate and the ledger."""

import json
import os

import core as C
import data as D
import numpy as np
import pandas as pd
import pytest
import run as R

HOUR = 3600.0


def _fixture(tmp_path, n_train=160, n_val=140, cheap_wins=0.80, seed=0):
    """Games whose team A is priced at 0.40 on Polymarket while Pinnacle makes it ~0.50 (a 10-point discount).
    Team A wins ``cheap_wins`` of the time (an edge when > 0.40 + fee), the rest of the market is at fair value."""
    rng = np.random.default_rng(seed)
    lab4 = tmp_path / "lab4"
    (lab4 / "trades").mkdir(parents=True)
    data = tmp_path / "lab6data"
    data.mkdir()
    markets, meta, pre, matches, pin = [], [], [], [], []
    mid = 0
    for split, n in (("train", n_train), ("val", n_val)):
        lo, hi = C.L4.split_bounds(split)
        for k in range(n):
            mid += 1
            start = lo + 86400.0 + k * (hi - lo - 2 * 86400.0) / n
            closed = start + 4 * HOUR
            a_wins = rng.random() < cheap_wins
            slug = f"mlb-a{mid}-b{mid}-2026-01-01"
            markets.append({
                "id": str(mid), "condition_id": f"0x{mid:064x}", "question": f"Team A{mid} vs. Team B{mid}",
                "slug": slug, "event_slug": slug, "event_title": f"Team A{mid} vs. Team B{mid}",
                "outcomes": json.dumps([f"Team A{mid}", f"Team B{mid}"]),
                "outcome_prices": json.dumps([1.0, 0.0] if a_wins else [0.0, 1.0]),
                "token_ids": json.dumps(["1", "2"]), "n_outcomes": 2, "winner_index": 0 if a_wins else 1,
                "closed_time": closed, "end_date": closed, "start_date": start - 7 * 86400, "volume": 50_000.0,
                "liquidity": 0.0, "fees_enabled": True, "taker_base_fee": 1000, "maker_base_fee": 0,
                "fee_type": "sports_fees_v3", "neg_risk": False, "resolution_status": "resolved", "resolved_by": "x",
            })
            meta.append({"id": str(mid), "game_start": start, "sports_market_type": "moneyline", "slug": slug})
            # prints: team A buyable at 0.40 from 50 min before the start, big enough; team B at 0.61
            ts = [start - 50 * 60 + 30 * i for i in range(20)]
            tape = pd.DataFrame({
                "ts": ts, "price": [0.40 if i % 2 == 0 else 0.61 for i in range(20)], "size": 100.0,
                "side": "BUY", "outcome_index": [0 if i % 2 == 0 else 1 for i in range(20)],
                "asset": "1", "tx": [f"0x{i}" for i in range(20)],
            })
            tape.to_parquet(lab4 / "trades" / f"{mid}.parquet", index=False)
            pre.append({"game_id": slug, "tapes": 1, "markets": 1, "prints_24h": 20})
            matches.append({"game_id": slug, "sport_key": "baseball_mlb", "event_id": f"e{mid}", "commence": start,
                            "home": f"Team B{mid} Full", "away": f"Team A{mid} Full", "a_is_home": False,
                            "sim": 1.0, "dt_start_s": 0.0})
            for snap in (start - 6 * HOUR, start - 70 * 60, start - 20 * 60, start - 4 * 60):
                pin.append({"sport_key": "baseball_mlb", "requested": snap, "snap_ts": snap, "event_id": f"e{mid}",
                            "commence": start, "home": f"Team B{mid} Full", "away": f"Team A{mid} Full",
                            "last_update": snap, "names": json.dumps([f"Team B{mid} Full", f"Team A{mid} Full"]),
                            "prices": json.dumps([1.95, 1.95])})
    pd.DataFrame(markets).to_parquet(lab4 / "markets.parquet", index=False)
    pd.DataFrame(meta).to_parquet(data / "gamma_meta.parquet", index=False)
    pd.DataFrame(pre).to_parquet(data / "pregame.parquet", index=False)
    pd.DataFrame(matches).to_parquet(data / "matches.parquet", index=False)
    pd.DataFrame(pin).to_parquet(data / "pinnacle.parquet", index=False)
    pd.DataFrame(columns=["game_id", "league", "reason", "team_a", "team_b", "best_home", "best_away", "sim"]
                 ).to_parquet(data / "match_failures.parquet", index=False)
    return lab4, data


def _run(tmp_path, stage, lab4, data):
    here = tmp_path / "lab6"
    here.mkdir(exist_ok=True)
    return R.run_stage(stage, B=200, here=here, data_dir=data, lab4=lab4, ledger=here / "trials.json")


def test_universe_and_candidates_from_the_fixture(tmp_path):
    lab4, data = _fixture(tmp_path, n_train=20, n_val=10)
    u = R.universe("train", data, lab4)
    assert len(u.games) == 20 and len(u.sides) == 40 and len(u.lines) == 20
    c = C.all_candidates(u, "mult", 24 * HOUR)
    # team A at 0.40 (+ tick) against a fair of 0.50: edge 0.09 - fee ~0.078; team B at 0.62 against 0.50: no edge
    a = c[c["o"] == 0]
    assert len(a) and np.allclose(a["fair"], 0.5)
    assert (a["edge"] > 0.07).all() and (c[c["o"] == 1]["edge"] < 0).all()
    # the snapshot used is at or before each print: the T-70 min one for prints before T-20 min
    early = a[a["t"] < a["game_id"].map(u.games.set_index("game_id")["commence"]) - 20 * 60]
    assert (early["snap_ts"] == early["game_id"].map(u.games.set_index("game_id")["commence"]) - 70 * 60).all()


def test_train_shortlists_val_selects_on_an_edge(tmp_path, monkeypatch):
    lab4, data = _fixture(tmp_path, cheap_wins=0.80)
    out = _run(tmp_path, "train", lab4, data)
    h1 = out["H1"]
    assert h1["decision"].startswith("SHORTLIST") and 1 <= len(h1["shortlist"]) <= C.SHORTLIST
    assert all(s["method"] == "mult" for s in h1["shortlist"])  # the alternative method is never selectable
    best = h1["cells"][0]["summary"]
    assert best["n"] == 160 and best["win_rate"] == pytest.approx(0.8, abs=0.1)
    assert out["H2"]["baseline"]["W1h"]["n"] == 320
    here = tmp_path / "lab6"
    assert (here / "H1" / "train.md").exists() and (here / "H2" / "train.md").exists()
    assert (here / "RESULTS.md").read_text().count("SHORTLIST") == 1
    ledger = json.loads((here / "trials.json").read_text())
    assert len(ledger) == len(C.METHODS) * len(C.WINDOWS_H) * len(C.MARGINS)
    val = _run(tmp_path, "val", lab4, data)["H1"]
    assert val["decision"].startswith("SELECTED") and val["selected"]["key"] == h1["shortlist"][0]["key"]
    assert val["cells"][0]["placebo"]["real_percentile"] >= R.PLACEBO_PCT
    assert "latency" in val["cells"][0]
    monkeypatch.delenv("LAB6_ALLOW_TEST", raising=False)
    with pytest.raises(PermissionError):
        _run(tmp_path, "test", lab4, data)


def test_no_edge_when_the_discount_is_not_real(tmp_path):
    lab4, data = _fixture(tmp_path, cheap_wins=0.40)  # team A wins exactly as often as its price says
    out = _run(tmp_path, "train", lab4, data)
    assert out["H1"]["decision"].startswith("NO EDGE")
    val = _run(tmp_path, "val", lab4, data)["H1"]
    assert val["decision"].startswith("NOT RUN") and val["cells"] == []


def test_inventory_counts_from_the_fixture(tmp_path):
    lab4, data = _fixture(tmp_path, n_train=12, n_val=8)
    here = tmp_path / "lab6"
    here.mkdir()
    doc = R.inventory(data, lab4, here, ledger=tmp_path / "credits.json")
    assert doc["games"] == 20 and doc["matched_games"] == 20 and doc["verdict_data"] == "NO_DATA"
    assert (here / "INVENTORY.md").exists()


def test_main_refuses_test_without_the_flag(monkeypatch):
    monkeypatch.delenv("LAB6_ALLOW_TEST", raising=False)
    with pytest.raises(PermissionError):
        R.check_split_allowed("test")
    monkeypatch.setenv("LAB6_ALLOW_TEST", "1")
    R.check_split_allowed("test")
    assert os.environ["LAB6_ALLOW_TEST"] == "1"
    assert D.CREDIT_CAP == 2_000_000
