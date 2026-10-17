"""Tests for research/lab2/k1.py (the Desk): the 3-config grid, the decision time, the cache-reading strategy and the
desk's exits, deliberation <-> backtest agreement and cache reproducibility, the no-lookahead brief on real census
bars (debug third), stage refusals (fake desk on official stages, no client, budget) and the debug hide."""

import json
import math
import shutil
from types import MappingProxyType, SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import common as C
import desk_core as D
import k1 as K
from conftest import make_frames, real_flow_available
from test_common import _garble

SOL = C.SolUsd(fallback=100.0)
HERE = C.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _never_the_real_decision_caches(monkeypatch, tmp_path):
    """Tests never read or write research/lab2/K1/decisions*: the real cache is the exam record."""
    monkeypatch.setattr(K, "CACHE", D.DecisionCache(tmp_path / "never_real"))
    monkeypatch.setattr(K, "FAKE_CACHE", D.DecisionCache(tmp_path / "never_fake"))
    prev = K._ACTIVE[0]
    K._ACTIVE[0] = K.CACHE
    K._UNDECIDED.clear()
    yield
    K._ACTIVE[0] = prev
    K._UNDECIDED.clear()


def test_grid_is_three_distinct_trials():
    assert len(K.GRID) == 3 <= 12 and [K.config_key(p) for p in K.GRID] == list(K.CONFIG_ORDER)
    assert len({C.params_hash(p) for p in K.GRID}) == 3
    for p in K.GRID:
        for k, v in K.FIXED.items():
            assert p[k] == v
        assert p["decider_model"] == D.CONFIGS[p["config"]]["decider_model"]
    assert K.PRIMARY_PARAMS in K.GRID and K.config_key(K.PRIMARY_PARAMS) == "panel"
    assert K.make_params("panel")["roles"] == list(D.CONFIGS["panel"]["roles"])
    assert K.make_params("solo-haiku")["roles"] == []
    assert K.DECL["uses_llm_decisions"] and K.DECL["llm_prompt_version"] == D.PROMPT_VERSION
    with pytest.raises(ValueError):
        K.make_params("duo")


def test_decision_time_is_the_first_grid_slot_at_or_after_30_min():
    for g, m0 in ((1000.0, 940.0), (1000.0, 1000.0), (1234.5, 1180.0), (5000.0, 4999.0)):
        t = K.decision_time(SimpleNamespace(g=g, m0=m0))
        assert K.DECISION_AGE_S <= t - g < K.DECISION_AGE_S + 60.0
        j = (t - C.GRID_OFFSET_S - m0) / 60.0
        assert abs(j - round(j)) < 1e-9


def _snap(age_s: float, mint: str = "M") -> SimpleNamespace:
    return SimpleNamespace(age_s=age_s, mint=mint)


def _dec(config, action="buy", stop=0.4, hold=90, conf=0.7, bh="h"):
    return D.Decision(action=action, confidence=conf, size_usd=20.0 if action == "buy" else 0.0, stop_pct=stop,
                      max_hold_min=hold, reason="", config=config, prompt_version=D.PROMPT_VERSION, brief_hash=bh,
                      models=(), cost_usd=0.0, memos={}, raw="")


def test_strategy_reads_the_cache_and_takes_the_desks_exits(tmp_path, monkeypatch):
    p = K.make_params("panel")
    brief = {"class": "OPERATOR", "alive": True}
    bh = D.brief_hash(brief)
    monkeypatch.setattr(K, "alive", lambda s: True)
    monkeypatch.setattr(D, "build_brief", lambda s: brief)
    monkeypatch.setattr(K, "speed_of", lambda s: "instant")
    cache = D.DecisionCache(tmp_path / "dec")
    with K.using_cache(cache):
        assert K.strategy(_snap(1700), p, None) is None                        # before 30 min: wait
        assert K.strategy(_snap(1800), p, None) is C.SKIP and ("panel", "M") in K._UNDECIDED   # no decision yet
        K._UNDECIDED.clear()
        cache.put(_dec("panel", "skip", bh=bh))
        assert K.strategy(_snap(1800), p, None) is C.SKIP and not K._UNDECIDED
        cache.put(_dec("panel", "buy", stop=0.4, hold=90, bh=bh))
        e = K.strategy(_snap(1800), p, None)
        assert isinstance(e, C.Enter) and e.exits.stop_pct == 0.4 and e.exits.max_hold_s == 5400.0
        assert e.exits.exit_by_age_s == K.EXIT_BY_AGE_S and e.tag == "OPERATOR"
        assert e.state == {"confidence": 0.7, "size_usd": 20.0, "speed": "instant"}
        assert K.strategy(_snap(1800), K.make_params("solo-haiku"), None) is C.SKIP    # its own decision, not panel's
        assert ("solo-haiku", "M") in K._UNDECIDED
        K._UNDECIDED.clear()
        monkeypatch.setattr(K, "alive", lambda s: False)
        assert K.strategy(_snap(1800), p, None) is C.SKIP and not K._UNDECIDED       # dead: never briefed
        assert K.strategy(_snap(5000), p, SimpleNamespace()) is None                   # no discretionary exits
    assert K._ACTIVE[0] is K.CACHE
    assert K.placebo_ok(_snap(1800)) is False                                          # control universe = alive


def test_direction_reading():
    assert K.direction({"n": 10, "placebo": {"diff_ci95": (0.1, 0.2)}}) == "UNDERPOWERED"
    assert K.direction({"n": 40, "placebo": {"diff_ci95": (0.1, 0.2)}}) == "BEATS_RANDOM"
    assert K.direction({"n": 40, "placebo": {"diff_ci95": (-0.2, -0.1)}}) == "WORSE_THAN_RANDOM"
    assert K.direction({"n": 40, "placebo": {"diff_ci95": (-0.1, 0.1)}}) == "NEITHER"
    assert K.direction({"n": 40, "placebo": None}) == "NEITHER"


def _ev(n, mean, ci_lo, mw2, pdiff, p=None):
    return {"n": n, "mean": mean, "ci90": None if ci_lo is None else (ci_lo, ci_lo + 0.2), "mean_without_top2": mw2,
            "placebo": None if pdiff is None else {"mean_diff": pdiff, "diff_ci95": None},
            "params_hash": C.params_hash(p) if p else "h", "config": K.config_key(p) if p else "c", "direction": None}


def test_decide_train_top_two_rule_and_config_order_tie_break():
    evals = {K.config_key(p): _ev(50, -0.01, -0.05, -0.02, -0.01, p) for p in K.GRID}
    assert K.decide_train(evals)["verdict"] == "NO_CONFIG"
    low = {K.config_key(p): _ev(29, 0.2, 0.1, 0.1, 0.1, p) for p in K.GRID}
    d = K.decide_train(low)
    assert d["verdict"] == "UNDERPOWERED_TRAIN" and d["shortlist"] == []
    panel, sonnet, haiku = (K.make_params(c) for c in ("panel", "solo-sonnet", "solo-haiku"))
    good = dict(evals)
    good["solo-haiku"] = _ev(40, 0.05, 0.02, 0.03, 0.04, haiku)
    good["solo-sonnet"] = _ev(90, 0.04, 0.02, 0.03, 0.04, sonnet)      # same CI low, lower mean -> 2nd
    good["panel"] = _ev(90, 0.09, 0.01, 0.03, -0.01, panel)            # fails the judged control
    d = K.decide_train(good)
    assert d["verdict"] == "SHORTLISTED" and d["shortlist_keys"] == ["solo-haiku", "solo-sonnet"]
    assert d["shortlist_hashes"] == [C.params_hash(haiku), C.params_hash(sonnet)]
    assert d["primary_direction"]["config"] == "panel"
    tie = dict(evals)
    tie["solo-haiku"] = _ev(40, 0.05, 0.02, 0.03, 0.04, haiku)
    tie["panel"] = _ev(40, 0.05, 0.02, 0.03, 0.04, panel)
    assert K.decide_train(tie)["shortlist_keys"] == ["panel", "solo-haiku"]   # CONFIG_ORDER breaks the tie


def test_decide_val_picks_the_higher_mean_and_judges_it():
    p1, p2 = K.make_params("panel"), K.make_params("solo-sonnet")
    d = K.decide_val({"sl1": _ev(20, 0.01, 0, 0.005, 0, p1), "sl2": _ev(20, 0.04, 0, 0.02, 0, p2)}, ["sl1", "sl2"])
    assert d["candidate_role"] == "sl2" and d["twin_role"] == "sl1" and d["verdict"] == "SELECTED"
    d = K.decide_val({"sl1": _ev(4, 0.3, 0, 0.3, 0, p1)}, ["sl1"])
    assert d["verdict"] == "UNDERPOWERED_VAL" and not d["proceed"]
    d = K.decide_val({"sl1": _ev(40, -0.01, 0, -0.02, 0, p1)}, ["sl1"])
    assert d["verdict"] == "FAIL_VAL"
    d = K.decide_val({"sl1": _ev(10, 0.02, 0, 0.01, 0, p1)}, ["sl1"])
    assert d["verdict"] == "SELECTED_UNDERPOWERED" and d["proceed"]


class AlwaysBuy(D.FakeDeskClient):
    """Fake desk that buys everything it is shown (exits 0.30 / 45 min): every alive coin becomes a trade."""

    def create(self, **request):
        r = super().create(**request)
        if (request.get("output_config") or {}).get("format") is not None:
            r.content[0].text = json.dumps({"action": "buy", "confidence": 0.9, "size_usd": 20, "stop_pct": 0.3,
                                            "max_hold_min": 45, "reason": "always"})
        return r


def _dataset(split="final_train"):
    """Synthetic coins; for the census TRAIN third (the debug split) a synthetic census puts every coin in it."""
    g, c, b = make_frames()
    cen = C.Census.empty()
    if split == "final_train":
        created = g["c_ts"] if "c_ts" in g else g["g_ts"] - 600.0
        cts = {str(m): float(t) for m, t in zip(g["mint"], created, strict=True)}
        cts = {m: (t if t == t else float(g.loc[g["mint"] == m, "g_ts"].iloc[0]) - 600.0) for m, t in cts.items()}
        cen = C.Census(MappingProxyType({m: "final_train" for m in cts}), MappingProxyType(cts), math.inf, math.inf,
                       float(C.FINAL_LO), float(C.FINAL_LO))
    ds = C.Dataset.from_frames(split, g, c, b, census=cen, sol=SOL)
    assert len(ds) >= 10, (split, len(ds))
    return ds


def _out(tmp_path):
    out = tmp_path / "K1"
    out.mkdir()
    shutil.copy(HERE / "K1" / "PREREG.md", out / "PREREG.md")
    return out


def test_deliberation_and_backtest_agree_and_the_cache_reproduces(tmp_path, monkeypatch):
    monkeypatch.setattr(K, "alive", lambda s: True)                    # every synthetic coin is briefed
    ds = _dataset()
    cache = D.DecisionCache(tmp_path / "dec")
    cl = AlwaysBuy()
    out = K.deliberate_split(ds, list(K.CONFIG_ORDER), cl, D.Budget(max_usd=1.0), cache)
    n = out["alive_at_decision"]
    assert n >= 10 and out["decided"] == out["new_calls"] == 3 * n and out["undecided"] == 0
    assert out["buys"] == {c: n for c in K.CONFIG_ORDER} and out["spent_usd"] > 0
    assert cache.count("panel") == cache.count("solo-haiku") == n
    again = K.deliberate_split(ds, list(K.CONFIG_ORDER), cl, D.Budget(max_usd=1.0), cache)
    assert again["new_calls"] == 0 and again["decided"] == 3 * n and again["spent_usd"] == 0.0   # reproducible
    doc = K.run_stage("debug", out_dir=_out(tmp_path), ds=ds, ledger_path=tmp_path / "dbg.json", B=50,
                      n_placebo=2, client=cl, decision_cache=cache)
    assert doc["deliberation"]["new_calls"] == 0 and doc["deliberation"]["client"] == "AlwaysBuy"
    assert "undecided_in_backtest" not in doc                          # the strategy met only briefs the desk saw
    for c in K.CONFIG_ORDER:
        assert doc["configs"][c]["n"] == out["buys"][c] == n           # every buy became exactly one trade
        assert doc["event_counts"]["per_config"][c] == {"cached": n, "buys": n}
        assert "mean" not in doc["configs"][c]
    assert K._ACTIVE[0] is K.CACHE


def test_fake_desk_decisions_never_enter_the_real_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(K, "alive", lambda s: True)
    ds = _dataset()
    doc = K.run_stage("debug", out_dir=_out(tmp_path), ds=ds, ledger_path=tmp_path / "dbg.json", B=50,
                      n_placebo=2, fake_client=True)
    assert doc["deliberation"]["client"] == "FakeDeskClient" and doc["deliberation"]["decided"] > 0
    assert K.CACHE.count("panel") == 0 and K.FAKE_CACHE.count("panel") == doc["deliberation"]["decided"] // 3


def test_official_stage_refuses_fake_desk_and_incomplete_exam(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "validation_gates", lambda split, flow=None: (True, []))
    monkeypatch.setattr(C, "check_sol_coverage", lambda ds: None)
    monkeypatch.setattr(K, "alive", lambda s: True)
    ds = _dataset("train")
    out = _out(tmp_path)
    with pytest.raises(K.K1Refused, match="fake-client"):
        K.run_stage("train", out_dir=out, ds=ds, ledger_path=tmp_path / "l.json", fake_client=True, B=50,
                    n_placebo=2, _skip_coverage=True)
    with pytest.raises(K.K1Refused, match="ANTHROPIC_API_KEY"):      # no key, no client: never scored
        K.run_stage("train", out_dir=out, ds=ds, ledger_path=tmp_path / "l.json", env={}, B=50, n_placebo=2,
                    decision_cache=D.DecisionCache(tmp_path / "empty"), _skip_coverage=True)
    assert not (tmp_path / "l.json").exists() and not (out / "train.json").exists()
    assert K.client_from_env(False, {}) is None and isinstance(K.client_from_env(True, {}), D.FakeDeskClient)


def test_budget_refusal_is_resumable(tmp_path, monkeypatch):
    monkeypatch.setattr(K, "alive", lambda s: True)
    ds = _dataset()
    cache = D.DecisionCache(tmp_path / "dec")
    out = _out(tmp_path)
    with pytest.raises(K.K1Refused, match="re-run to resume"):
        K.run_stage("debug", out_dir=out, ds=ds, ledger_path=tmp_path / "dbg.json", B=50, n_placebo=2,
                    client=AlwaysBuy(), decision_cache=cache, budget_usd=0.0005)
    paid = cache.count("panel")
    assert paid >= 1                                                   # what was paid for is kept
    doc = K.run_stage("debug", out_dir=out, ds=ds, ledger_path=tmp_path / "dbg.json", B=50, n_placebo=2,
                      client=AlwaysBuy(), decision_cache=cache)
    assert doc["deliberation"]["new_calls"] == doc["deliberation"]["decided"] - paid
    assert doc["deliberation"]["budget_usd"] == K.BUDGET_USD["debug"]


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_no_lookahead_real_census_train():
    """The brief (everything the desk sees) and the alive gate are unchanged when the coin's data after tau is
    garbage: real bars, census TRAIN third (the debug split)."""
    f = C.flow_dir()
    frames = tuple(pd.read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    cen = C.Census.load()
    full = C.Dataset.from_frames("final_train", *frames, census=cen, sol=SOL)
    rng = np.random.default_rng(29)
    pick = [full.mints[int(i)] for i in rng.choice(len(full.mints), size=16, replace=False)]
    sub = tuple(x[x["mint"].isin(pick)] for x in frames)
    clean = C.Dataset.from_frames("final_train", *sub, census=cen, sol=SOL)
    n = 0
    for m in clean.mints:
        cd = clean.coin(m)
        for t in (K.decision_time(cd), K.decision_time(cd) + 600.0, cd.g + float(rng.uniform(4000, 6900))):
            dirty = C.Dataset.from_frames("final_train", *_garble(sub, m, t - C.DECISION_LAG_S, rng), census=cen,
                                          sol=SOL)
            if m not in dirty.mints:
                continue
            a, b = clean.asof(m, t), dirty.asof(m, t)
            assert (D.build_brief(a), K.alive(a)) == (D.build_brief(b), K.alive(b))
            n += 1
    assert len(clean.mints) >= 12 and n >= 30


def test_stage_refusals(tmp_path, monkeypatch):
    out = tmp_path / "K1"
    out.mkdir()
    with pytest.raises(K.K1Refused, match="PREREG.md missing"):
        K.check_prereqs("debug", out)
    shutil.copy(HERE / "K1" / "PREREG.md", out / "PREREG.md")
    assert K.check_prereqs("debug", out)["stage"] == "debug"
    monkeypatch.setattr(C, "validation_gates", lambda split, flow=None: (True, []))
    with pytest.raises(K.K1Refused, match="no TRAIN result"):
        K.check_prereqs("val", out)
    (out / "prereg.lock").write_text(json.dumps({"sha256": "0" * 64}))
    with pytest.raises(K.K1Refused, match="PREREG.md changed"):
        K.check_prereqs("train", out)
    (out / "prereg.lock").unlink()
    (out / "train.json").write_text(json.dumps({"provisional": False, "decision": {"verdict": "NO_CONFIG"}}))
    with pytest.raises(K.K1Refused, match="TRAIN decision NO_CONFIG"):
        K.check_prereqs("val", out)
    with pytest.raises(K.K1Refused, match="already ran on complete data"):
        K.check_prereqs("train", out)
    monkeypatch.setattr(C, "validation_gates", lambda split, flow=None: (False, ["V2 failed"]))
    with pytest.raises(K.K1Refused, match="data first"):
        K.check_prereqs("train", out)


def test_debug_stage_hides_returns(tmp_path, monkeypatch):
    monkeypatch.setattr(K, "alive", lambda s: True)
    ds = _dataset()
    out = _out(tmp_path)
    doc = K.run_stage("debug", out_dir=out, ds=ds, ledger_path=tmp_path / "dbg.json", B=50, n_placebo=2,
                      fake_client=True)
    assert doc["debug_only"] and doc["decision"]["verdict"] == "DEBUG"
    for e in doc["configs"].values():
        assert "mean" not in e and e["returns"].startswith("hidden")
    md = (out / "debug.md").read_text()
    assert (out / "debug.md").exists() and "hidden" in md and "decisions cached" in md
    led = json.loads((tmp_path / "dbg.json").read_text())
    assert all(r["debug"] and r["mean"] is None for r in led["runs"])
