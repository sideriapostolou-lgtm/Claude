"""As-of discipline of the experience inputs (docs/EXPERIENCE.md §4.5, §4.6, §6.5, §11 ``test_experience_asof``).

On recorder-shaped fixture tapes (``learn_world.record_coin`` plus DexScreener snapshots and engine decision rows):

* for 200 random (coin, t) pairs, every candle minute with ``m + 60 + L_obs > t``, every state row fetched after t
  and every decision row after t is replaced by garbage: member verdicts, cell keys and feature values are unchanged;
* prefix invariance: the tape truncated at t (only what was visible at t) gives the same results at every t' <= t;
* labels are outcomes: they cannot be read before ``label_ready_ts`` and never need data after it.
"""

from __future__ import annotations

import copy
import random
from typing import Any

import pytest

from learn_world import DAY0, make_coins
from nightcrawler.experience import features as feat
from nightcrawler.experience.constants import FEATURE_IDS
from nightcrawler.learn import labels
from nightcrawler.learn.tape import DEFAULT_L_OBS_S, TapeView
from nightcrawler.models import Candle

L_OBS = DEFAULT_L_OBS_S


def _snap(mint: str, ts: float, age_min: int, rng: random.Random) -> dict[str, Any]:
    buys, sells = rng.randint(0, 400), rng.randint(0, 300)
    return {"v": 1, "ts": ts, "mint": mint, "src": {"dexscreener": [ts, 200]}, "age_min": age_min,
            "pair": {"txns": {"m5": {"buys": buys, "sells": sells}}, "volume": {"m5": rng.uniform(0, 3000.0)}}}


def _decision(mint: str, ts: float, decision: str, rng: random.Random) -> dict[str, Any]:
    warnings = [w for w in ("[copycat] ticker shared", "[no_socials] none listed", "[low_holders] 40 holders")
                if rng.random() < 0.4]
    passed = decision != "reject_cocoon"
    safety = {"passed": passed, "hard_fail_reasons": [] if passed else ["[top10] top 10 hold 52%"],
              "warnings": warnings, "unverified": []}
    verdict = None
    if decision in ("enter", "reject_judge"):
        verdict = {"decision": "no" if decision == "reject_judge" else "yes", "confidence": 0.7, "source": "claude"}
    return {"ts": ts, "mint": mint, "decision": decision, "reason": decision, "signal": None, "snapshot": None,
            "candle_source": "pumpfun", "safety": safety, "verdict": verdict}


@pytest.fixture(scope="module")
def world() -> dict[str, dict[str, Any]]:
    """12 coins: candles as the recorder stores them, snapshots at the recorder's ages, a few engine decisions."""
    rng = random.Random(7)
    coins = make_coins(12, seed=5, start=DAY0 + 3600, spacing_s=900.0)
    for k, (mint, coin) in enumerate(coins.items()):
        seen = coin["rows"]["universe"][0]["first_seen_ts"]
        coin["rows"]["snaps"] = [_snap(mint, seen + age * 60 + rng.uniform(0, 30), age, rng)
                                 for age in (5, 15, 30, 60, 120, 240, 360)]
        kinds = ["watch", "reject_radar", "enter"] if k % 3 == 0 else ["reject_cocoon"] if k % 3 == 1 else ["watch"]
        coin["evals"] = [_decision(mint, seen + 1200 * (i + 1) + rng.uniform(0, 60), d, rng)
                         for i, d in enumerate(kinds)]
        coin["seen"] = seen
    return coins


def _garbage(rows: dict[str, list], evals: list, t: float, rng: random.Random) -> tuple[dict[str, list], list]:
    """Everything NOT visible at t replaced by random values (shapes kept)."""
    out = copy.deepcopy(rows)
    for fetch in out["candles"]:
        for r in fetch["rows"]:
            if r[0] + 60 + L_OBS > t:
                price = rng.uniform(1e-6, 1.0)
                r[1:5] = [price, price * 3, price / 3, price * rng.uniform(0.2, 2.0)]
                r[5] = rng.uniform(0, 1e6)
    for stream in ("snaps", "universe"):
        for r in out.get(stream, ()):
            if r["ts"] > t:
                r["pair"] = {"txns": {"m5": {"buys": rng.randint(0, 9999), "sells": rng.randint(0, 9)}},
                             "volume": {"m5": rng.uniform(0, 1e7)}}
                r["launch"] = {"supply": rng.uniform(1, 1e12)}
    bad_evals = copy.deepcopy(evals)
    for r in bad_evals:
        if r["ts"] > t:
            r["decision"] = rng.choice(["reject_cocoon", "watch", "reject_radar", "reject_judge"])
            r["safety"] = {"passed": rng.random() < 0.5, "hard_fail_reasons": ["[garbage] x"],
                           "warnings": ["[impersonation] x", "[paid_promo] y"], "unverified": ["rugcheck"]}
            r["verdict"] = {"decision": "no", "confidence": 1.0, "source": "claude"}
    return out, bad_evals


def _truncate(rows: dict[str, list], evals: list, t: float) -> tuple[dict[str, list], list]:
    """Only what was visible at t: later candle minutes, state rows and decisions removed."""
    out = copy.deepcopy(rows)
    for fetch in out["candles"]:
        fetch["rows"] = [r for r in fetch["rows"] if r[0] + 60 + L_OBS <= t]
    out["snaps"] = [r for r in out.get("snaps", ()) if r["ts"] <= t]
    out["universe"] = [r for r in out["universe"] if r["ts"] <= t] or out["universe"][:1]
    return out, [r for r in evals if r["ts"] <= t]


def _everything(rows: dict[str, list], evals: list, mint: str, t: float) -> dict[str, Any]:
    view = TapeView(mint, as_of=t, rows=rows, l_obs=L_OBS)
    context = {"heat_high": True, "breadth_m15": -0.25, "sol_usd_now": 100.0, "sol_usd_15m": 104.0}
    return {"cell": feat.cell_at(view, t), "features": feat.features_at(view, t, evals=evals, context=context),
            "verdicts": feat.verdicts_at(evals, t)}


def test_garbage_after_t_changes_no_verdict_cell_or_feature(world) -> None:
    rng = random.Random(11)
    mints = sorted(world)
    for _ in range(200):
        mint = rng.choice(mints)
        coin = world[mint]
        t = coin["seen"] + rng.uniform(0, 7 * 3600)
        clean = _everything(coin["rows"], coin["evals"], mint, t)
        rows, evals = _garbage(coin["rows"], coin["evals"], t, rng)
        assert _everything(rows, evals, mint, t) == clean, (mint, t)


def test_prefix_invariance(world) -> None:
    rng = random.Random(12)
    mints = sorted(world)
    for _ in range(40):
        mint = rng.choice(mints)
        coin = world[mint]
        t = coin["seen"] + rng.uniform(600, 7 * 3600)
        rows, evals = _truncate(coin["rows"], coin["evals"], t)
        for t_prime in (t, t - rng.uniform(0, 600), coin["seen"] + 1.0):
            assert _everything(rows, evals, mint, t_prime) == _everything(coin["rows"], coin["evals"], mint, t_prime)


def test_every_catalogue_feature_is_reported_with_its_first_flag_time(world) -> None:
    mint = sorted(world)[0]
    coin = world[mint]
    t = coin["seen"] + 5 * 3600
    view = TapeView(mint, as_of=t, rows=coin["rows"], l_obs=L_OBS)
    out = feat.features_at(view, t, evals=coin["evals"])
    assert set(out) == set(FEATURE_IDS)
    for name, item in out.items():
        assert set(item) == {"value", "first_flag_ts"}, name
        assert item["value"] in (True, False, None)
        if item["first_flag_ts"] is not None:
            assert item["value"] is True and item["first_flag_ts"] <= t
    # history-only features are unknown forward; context features unknown without context
    assert out["dust_burst"]["value"] is None and out["airdrop_seen"]["value"] is None
    assert out["heat_high"]["value"] is None and out["sol_drop"]["value"] is None


def test_features_before_the_coin_was_seen_are_unknown(world) -> None:
    mint = sorted(world)[1]
    coin = world[mint]
    t = coin["seen"] - 30.0
    view = TapeView(mint, as_of=t, rows=coin["rows"], l_obs=L_OBS)
    assert all(v["value"] is None for v in feat.features_at(view, t, evals=coin["evals"]).values())
    assert feat.cell_at(view, t) == {"speed": "unknown", "age_band": "unknown", "mcap_tier": "unknown"}


def test_cells_follow_the_frozen_bands() -> None:
    assert feat.speed_of(1000.0, 1000.0 + 600) == "fast" and feat.speed_of(1000.0, 1000.0 + 601) == "slow"
    assert feat.speed_of(1000.0, 1060.0, source="history") == "fast"
    assert feat.speed_of(1000.0, 1061.0, source="history") == "slow"
    assert feat.speed_of(None, 1000.0) == "unknown"
    assert [feat.age_band(m * 60) for m in (0, 29.9, 30, 119, 120, 359, 360, 900)] == \
        ["0-30", "0-30", "30-120", "30-120", "120-360", "120-360", ">360", ">360"]
    assert feat.age_band(-1) == "unknown" and feat.age_band(None) == "unknown"
    assert [feat.mcap_tier(v) for v in (99_999, 100_000, 499_999, 500_000, None)] == \
        ["<100k", "100k-500k", "100k-500k", ">=500k", "unknown"]


def test_verdicts_count_only_decisions_at_or_before_t() -> None:
    rng = random.Random(3)
    evals = [_decision("M", 100.0, "watch", rng), _decision("M", 200.0, "reject_radar", rng),
             _decision("M", 300.0, "reject_cocoon", rng)]
    assert feat.verdicts_at(evals, 50.0) == {"cocoon": "unchecked", "cocoon_rules": [], "cocoon_ts": None,
                                             "radar_pre": "n/a", "jev": "n/a"}
    at_150 = feat.verdicts_at(evals, 150.0)
    assert at_150["cocoon"] == "pass" and at_150["cocoon_ts"] == 100.0 and at_150["radar_pre"] == "n/a"
    assert feat.verdicts_at(evals, 250.0)["radar_pre"] == "flag"
    at_350 = feat.verdicts_at(evals, 350.0)
    assert at_350["cocoon"] == "fail" and at_350["cocoon_rules"] == ["top10"] and at_350["cocoon_ts"] == 300.0
    judged = [_decision("M", 100.0, "enter", rng)]
    assert feat.verdicts_at(judged, 100.0)["jev"] == "yes" and feat.verdicts_at(judged, 100.0)["radar_pre"] == "pass"
    off = [{**judged[0], "verdict": {"decision": "yes", "confidence": 1.0, "source": "rules"}}]
    assert feat.verdicts_at(off, 100.0)["jev"] == "n/a"  # the judge is off: no verdict to grade


def test_an_unavailable_source_is_a_fail_closed_block_and_named() -> None:
    row = {"ts": 10.0, "mint": "M", "decision": "reject_cocoon", "safety": {
        "passed": False, "hard_fail_reasons": ["source unavailable: rugcheck (HTTP 500)"], "warnings": [],
        "unverified": ["rugcheck"]}, "verdict": None}
    out = feat.verdicts_at([row], 10.0)
    assert out["cocoon"] == "fail" and out["cocoon_rules"] == ["source_unavailable:rugcheck"]


# --------------------------------------------------------------------------- labels


def _bars(closes: list[float], start: int = 0, lows: list[float] | None = None) -> list[Candle]:
    out = []
    for i, c in enumerate(closes):
        low = lows[i] if lows else c
        out.append(Candle(start + 60 * i, c, max(c, low), low, c, 1.0))
    return out


def test_crash50_needs_a_half_drop_that_persists_five_minutes() -> None:
    flat = [1.0] * 30
    wick = _bars(flat, lows=[1.0] * 10 + [0.4] + [1.0] * 19)  # a sandwich wick: recovered at once
    assert labels.crash50(wick, 0.0, 1200).crashed is False
    closes = [1.0] * 10 + [0.45] * 20
    crash = _bars(closes, lows=[1.0] * 10 + [0.4] * 20)
    got = labels.crash50(crash, 0.0, 1200)
    assert got.crashed is True and got.t_crash == 600
    assert labels.crash50(crash, 660.0, 900).crashed is False  # after the crash minute: nothing new falls
    assert labels.crash50(crash, 0.0, 300).crashed is False  # the crash minute is past the horizon
    shallow = _bars([1.0] * 10 + [0.55] * 20, lows=[1.0] * 10 + [0.51] * 20)
    assert labels.crash50(shallow, 0.0, 1200).crashed is False


def test_crash50_is_unknown_when_the_data_ends_too_early() -> None:
    closes = [1.0] * 10 + [0.45] * 3
    bars = _bars(closes, lows=[1.0] * 10 + [0.4] * 3)
    assert labels.crash50(bars, 0.0, 700).crashed is None  # the 5-minute confirmation is past the data
    assert labels.crash50(_bars([1.0] * 5), 0.0, 3600).crashed is None  # the window itself is not covered


def test_dead_compares_the_last_close_at_the_horizon_with_the_price_at_t() -> None:
    bars = _bars([1.0] * 5 + [0.19] * 10)
    assert labels.dead(bars, 300.0, 600) is True
    assert labels.dead(_bars([1.0] * 5 + [0.21] * 10), 300.0, 600) is False
    assert labels.dead(bars, 300.0, 6000) is None  # not covered
    assert labels.is_bad(True, False) and labels.is_bad(None, True) and labels.is_bad(False, False) is False
    assert labels.is_bad(None, False) is None and labels.is_good(0.01) and labels.is_good(0.0) is False


def test_excursions_use_closes_and_wicks_inside_the_hold() -> None:
    bars = _bars([1.0, 1.0, 1.3, 0.8, 1.1, 2.0], lows=[1.0, 1.0, 1.2, 0.5, 1.0, 2.0])
    ex = labels.excursions(bars, 60.0, 300.0, entry_price=1.0)
    assert ex is not None
    assert ex.mfe == pytest.approx(0.3) and ex.mae == pytest.approx(-0.2) and ex.mae_wick == pytest.approx(-0.5)
    assert labels.excursions(bars, 60.0, 300.0, entry_price=None).mfe == pytest.approx(0.3)


def test_the_labels_module_is_standard_library_only() -> None:
    import ast
    import sys

    tree = ast.parse(open(labels.__file__, encoding="utf-8").read())
    roots = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    roots |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert roots <= set(sys.stdlib_module_names) | {"__future__"}, roots


def test_net_return_clips_x_and_keeps_x_raw() -> None:
    assert labels.net_return(21.0, 20.0) == (pytest.approx(0.05), pytest.approx(0.05))
    x, x_raw = labels.net_return(80.0, 20.0)
    assert x == 1.0 and x_raw == pytest.approx(3.0)


def test_labels_cannot_be_read_before_they_are_ready(world) -> None:
    mint = sorted(world)[2]
    coin = world[mint]
    t = coin["seen"] + 3600
    ready = labels.label_ready_ts(t)
    assert ready == t + labels.HORIZON_S + labels.LABEL_DELAY_S
    with pytest.raises(labels.LabelNotReady):
        labels.require_ready(ready, ready - 1)
    labels.require_ready(ready, ready)
    # a label never needs data after label_ready_ts: the view as of then gives the same answer as the full tape
    full = TapeView(mint, as_of=t + 100 * 86400, rows=coin["rows"], l_obs=L_OBS).candles()
    then = TapeView(mint, as_of=ready, rows=coin["rows"], l_obs=L_OBS).candles()
    assert labels.coin_labels(then, t) == labels.coin_labels(full, t)
    assert labels.coin_labels(full, t)["label_ready_ts"] == ready
