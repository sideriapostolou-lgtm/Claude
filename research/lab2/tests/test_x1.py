"""Tests for research/lab2/x1.py: early-holder features, the causal wallet registry (strictly past, never the traded
coin, invariant to future garbage), the label = the trade X1 takes, the persistence gate (stop rule), the
pre-registered decision rules and the stage refusals."""

import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import common as C
import x1 as X
from conftest import V0, VALID_ALL as VALID, make_frames, real_flow_available
from test_common import _garble

SOL = C.SolUsd(fallback=100.0)
X0, Y0 = 84.990359, 206.9e6
N_MIN = 186
POOLED = next(iter(C.POOLED_ACCOUNTS))
GOOD = [f"GOOD{i}" for i in range(6)]
BAD = [f"BAD{i}" for i in range(6)]


# =========================================================================== synthetic markets


def path_bars(g: int, mint: str, pool: str, mult: float, wick: float = 0.005) -> pd.DataFrame:
    """Deterministic bars: flat to minute 9, then a geometric path reaching ``mult`` x the start at minute 62, flat
    after. k = X * y is constant; 3 SOL of buys and sells every minute (alive)."""
    m0 = int(g) // 60 * 60
    rows, prev = [], X0 / Y0
    for j in range(N_MIN):
        f = 1.0 if j < 9 else mult ** (min(j - 9, 53) / 53.0)
        X, y = X0 * math.sqrt(f), Y0 / math.sqrt(f)
        p = X / y
        rows.append({"minute_ts": m0 + 60 * j, "n_buys": 6, "n_sells": 4, "n_dust": 0, "buy_sol": 3.0, "sell_sol": 3.0,
                     "buy_tok": 1e6, "sell_tok": 1e6, "n_buyers": 4, "n_sellers": 3, "top5_buy_sol": 3.0,
                     "open": prev, "high": max(prev, p) * (1 + wick), "low": min(prev, p) * (1 - wick), "close": p,
                     "x_close": X - V0, "y_close": y, "mint": mint, "pool": pool, "g_ts": g, "minute_idx": j,
                     "agent_buy_sol": 0.0, "price_repaired": 0})
        prev = p
    return pd.DataFrame(rows)


def market_frames(n: int, t0: int, seed: int, informative: bool = True, spacing: int = 600, up: float = 1.4,
                  down: float = 0.75):
    """n coins, half "good" (2 early holders drawn from 6 GOOD wallets) and half "bad" (2 from 6 BAD wallets), plus a
    flipper, a pooled account and (every 3rd coin) its AGENT in the w300 list. ``informative``: good coins rise (x up
    by g + 62 min) and bad coins fall (x down); otherwise up / down is a coin flip."""
    g, c, _ = make_frames(n=n, seed=seed, t0=t0, spacing=spacing, n_minutes=2)
    rng = np.random.default_rng(seed + 1000)
    lists, bars = [], []
    for r in g.itertuples(index=False):
        good = bool(rng.random() < 0.5)
        hold = list(rng.choice(GOOD if good else BAD, size=2, replace=False))
        rises = good if informative else bool(rng.random() < 0.5)
        lst = [[POOLED, 20.0, 0.0], [hold[0], 6.0, 0.5], [hold[1], 4.0, 1.0], ["FLIPPER", 5.0, 4.0]]
        ci = c.index[c["mint"] == r.mint][0]
        if bool(c.at[ci, "agent_present"]):
            lst.append([c.at[ci, "agent_wallet"], 17.5, 0.0])
        lists.append(json.dumps(lst))
        bars.append(path_bars(int(r.g_ts), r.mint, r.pool, up if rises else down))
    c = c.copy()
    c["w300_top10"] = lists
    return g, c, pd.concat(bars, ignore_index=True)


def ds_of(frames, split: str) -> C.Dataset:
    return C.Dataset.from_frames(split, *frames, census=C.Census.empty(), sol=SOL, guard=False)


def market(split: str, t0: int, n: int, seed: int, **kw) -> C.Dataset:
    ds = ds_of(market_frames(n, t0, seed, **kw), split)
    assert len(ds) == n or split == "final"
    return ds


T_TRAIN = C.utc_ts("2026-10-01 00:30")


@pytest.fixture(scope="module")
def train_ds():
    return market("train", T_TRAIN, 260, 1)


@pytest.fixture(scope="module")
def train_reg(train_ds):
    return X.build_registry([train_ds])


# =========================================================================== features


def test_decision_time_is_the_first_grid_time_after_the_boost_window(train_ds):
    for m in train_ds.mints[:40]:
        cd = train_ds.coin(m)
        t = X.decision_time(cd)
        tau = t - C.DECISION_LAG_S
        assert tau >= cd.g + 420 and tau - 60 < cd.g + 420
        assert 440 <= t - cd.g < 500
        assert (t - C.GRID_OFFSET_S - cd.m0) % 60 == 0
    cd = SimpleNamespace(g=1_000_020.0, m0=1_000_020)          # graduation exactly on a minute boundary
    assert X.decision_index(cd) == 7


def test_class_rules_and_nulls(train_ds):
    m = train_ds.mints[0]
    snap = train_ds.asof(m, X.decision_time(train_ds.coin(m)))
    assert X.x1_class(snap) == "OTHER" and X.eligible(snap)
    early = train_ds.asof(m, train_ds.coin(m).g + 200)      # AGENT presence undecided, no AGENT yet -> NULL
    if not early.agent_detected:
        assert X.x1_class(early) is None


def _snap_with(top: list, agent: str | None = None, t_off: float = 460):
    g, c, b = market_frames(3, T_TRAIN, 5)
    c = c.copy()
    c["w300_top10"] = c["w300_top10"].astype(object)
    c.at[0, "w300_top10"] = json.dumps(top)
    if agent is not None:
        c.at[0, "agent_present"], c.at[0, "agent_wallet"], c.at[0, "agent_known_at"] = True, agent, float(g.at[0, "g_ts"] + 40)
    ds = ds_of((g, c, b), "train")
    m = g.at[0, "mint"]
    return ds.asof(m, ds.coin(m).g + t_off)


def test_early_holders_drop_pooled_agent_flippers_and_zero_buys():
    top = [[POOLED, 9.0, 0.0], ["A", 5.0, 2.5], ["B", 4.0, 2.6], ["AG", 17.0, 0.0], ["Z", 0.0, 0.0], ["C", 1.0, 0.0]]
    snap = _snap_with(top, agent="AG")
    assert X.early_holders(snap) == ("A", "C")          # B sold > 50 %, AG is the AGENT, Z bought nothing


def test_early_holders_not_knowable_before_the_window():
    snap = _snap_with([["A", 5.0, 0.0]], t_off=250)        # tau < g + 300: w300 not legal yet
    assert X.early_holders(snap) is None


# =========================================================================== registry: strictly past, never the coin


def _reg(entries: dict) -> X.Registry:
    w = {k: (np.array([e[0] for e in v], float), np.array([e[1] for e in v], float), np.array([e[2] for e in v], object))
         for k, v in entries.items()}
    return X.Registry(coins=pd.DataFrame(columns=["mint", "split", "g", "t_d", "eligible", "n_holders", "label",
                                                  "ret_net", "resolve_ts"]), wallets=w, t0=0.0)


def test_registry_counts_only_resolved_entries_of_other_coins():
    reg = _reg({"W": [(100.0, 0.5, "a"), (200.0, -0.1, "b"), (300.0, 0.3, "c")]})
    assert reg.record("W", 99.0, "x") == (0, None)
    assert reg.record("W", 100.0, "x") == (1, pytest.approx(0.5))         # resolved at tau exactly: usable
    assert reg.record("W", 250.0, "x") == (2, pytest.approx(0.2))
    assert reg.record("W", 1e9, "b") == (2, pytest.approx(0.4))           # the coin itself never scores its wallets
    n, s = reg.skill("W", 1e9, "x")
    assert n == 3 and s == pytest.approx(np.mean([0.5, -0.1, 0.3]) * 3 / 13)
    assert reg.record("NOBODY", 1e9, "x") == (0, None)


def test_label_is_the_trade_x1_takes_and_resolves_after_the_decision(train_ds, train_reg):
    lab = train_reg.coins[train_reg.coins["label"].notna()]
    assert len(lab) >= 200
    assert (lab["resolve_ts"] >= lab["t_d"] + 60).all()
    assert (lab["resolve_ts"] <= lab["g"] + 3600 + 3 * 60).all()
    p = X.make_params(0.0, 3)
    t = C.run_trades(train_ds, X.make_strategy(train_reg), p, X.CFG)
    assert len(t) > 50
    by = lab.set_index("mint")
    for r in t.itertuples(index=False):
        assert r.ret_net == pytest.approx(by.at[r.mint, "ret_net"], abs=1e-12)    # same entry, exits and fills
        assert r.t_dec == pytest.approx(by.at[r.mint, "t_d"])
        assert r.reason in ("time", "stop")
    for r in lab.itertuples(index=False):
        tr = X.base_follow_trade(train_ds.coin(r.mint), train_ds.sol)
        assert X.label_of(tr["ret_net"]) == pytest.approx(r.label)


def test_registry_entries_are_eligible_holders_only(train_ds, train_reg):
    for w in ("FLIPPER", POOLED):
        assert w not in train_reg.wallets
    assert not any(w.startswith("AGENT") for w in train_reg.wallets)
    assert set(train_reg.wallets) <= set(GOOD + BAD)


def test_strategy_follows_good_wallets_and_waits_for_history(train_ds, train_reg):
    p = X.make_params(0.0, 3)
    t = C.run_trades(train_ds, X.make_strategy(train_reg), p, X.CFG)
    assert set(t["tag"]) <= set(GOOD)                       # BAD wallets' picks lost: never reputable
    first = sorted(train_ds.mints, key=lambda m: train_ds.coin(m).g)[:5]
    assert not set(first) & set(t["mint"])                  # nothing is known before the first labels resolve
    assert (t["ret_net"] > 0).all()


# =========================================================================== no lookahead (PLAN 6.6 rule 9)


def test_registry_and_decisions_unchanged_by_future_garbage():
    frames = market_frames(70, T_TRAIN, 3)
    clean = ds_of(frames, "train")
    reg_c = X.build_registry([clean])
    gt = sorted(clean.coin(m).g for m in clean.mints)
    T = gt[45]
    rng = np.random.default_rng(5)
    dirty_frames = frames
    for m in clean.mints:
        dirty_frames = _garble(dirty_frames, m, T, rng)
    dirty = ds_of(dirty_frames, "train")
    reg_d = X.build_registry([dirty])
    taus = np.linspace(gt[0], T, 25)
    n_known = 0
    for w in GOOD + BAD + ["FLIPPER", "GARBAGE"]:
        for tau in taus:
            a, b = reg_c.skill(w, float(tau), ""), reg_d.skill(w, float(tau), "")
            assert a == b
            n_known += a[0] >= 3
    assert n_known > 50
    n_dec = 0
    for p in X.GRID:
        for m in clean.mints:
            t_d = X.decision_time(clean.coin(m))
            if t_d - C.DECISION_LAG_S > T or m not in dirty.mints:
                continue
            assert X.signal(clean.asof(m, t_d), reg_c, p) == X.signal(dirty.asof(m, t_d), reg_d, p)
            n_dec += 1
    assert n_dec > 100


def test_history_splits_never_include_a_later_split():
    order = {"confirm": 0, "train": 1, "val": 2, "test": 3, "final_train": 4, "final": 4}
    for stage, hist in X.HISTORY_SPLITS.items():
        traded = X.STAGE_SPLIT[stage]
        assert traded in hist
        assert all(order[h] <= order[traded] for h in hist), stage
    assert X.HISTORY_SPLITS["confirm"] == ("confirm",) and X.HISTORY_SPLITS["train"] == ("train",)


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_real_census_train_registry_is_causal():
    ds = C.load("final_train")
    reg = X.build_registry([ds])
    lab = reg.coins[reg.coins["label"].notna()]
    assert len(lab) > 50
    assert (lab["resolve_ts"] >= lab["t_d"] + 60).all() and (lab["resolve_ts"] <= lab["g"] + 3600 + 180).all()
    ages = reg.coins["t_d"] - reg.coins["g"]
    assert ages.between(440, 500, inclusive="left").all()
    pooled = set(C.POOLED_ACCOUNTS)
    assert not pooled & set(reg.wallets)
    # brute-force check of the as-of query on real entries
    rng = np.random.default_rng(0)
    ws = [w for w, v in reg.wallets.items() if len(v[0]) >= 2]
    for w in rng.choice(ws, size=min(30, len(ws)), replace=False):
        ts, ys, ms = reg.wallets[w]
        tau = float(ts[len(ts) // 2])
        keep = (ts <= tau) & (ms != ms[0])
        n, mean = reg.record(w, tau, ms[0])
        assert n == int(keep.sum()) and (mean is None or mean == pytest.approx(ys[keep].mean()))


# =========================================================================== persistence gate


def _gate_obs(n: int, rho: float, seed: int = 0, span_h: float = 72.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=n)
    y = rho * x + math.sqrt(max(1 - rho ** 2, 1e-9)) * rng.normal(size=n)
    t = 1.79e9 + np.sort(rng.uniform(0, span_h * 3600, n))
    return pd.DataFrame({"mint": [f"M{i}" for i in range(n)], "t_d": t, "label": y, "n_holders": 2, "n_known": 1,
                         "rep": x, "best_wallet": [f"W{i % 17}" for i in range(n)],
                         "group": ["reputable" if v > 0 else "known_not_reputable" for v in x], "warmup": t < t[0] + 86400})


@pytest.mark.parametrize("n,rho,want", [(600, 0.5, "PASS"), (600, 0.0, "KILL"), (150, 0.6, "UNDERPOWERED")])
def test_gate_decision(n, rho, want):
    g = X.gate_decision(_gate_obs(n, rho), B=300)
    assert g["decision"] == want
    if want == "PASS":
        assert g["rho"] > 0.4 and g["p_one_sided"] < 1e-6 and g["ci90_block"][0] > 0.3


def test_gate_hidden_on_debug():
    g = X.gate_decision(_gate_obs(600, 0.5), hide=True)
    assert g["decision"].startswith("HIDDEN") and "rho" not in g and "diagnostics" not in g


def test_gate_hidden_reports_only_the_outcome_free_holder_split():
    """Review X1-DEBUG-LABELS: on the debug split the gate reports holders known at n >= N_GATE vs unknown only. The
    reputable / known-not-reputable split (and which wallet scores) is the sign of earlier coins' labels."""
    o = _gate_obs(600, 0.5)
    o.loc[o.index[:100], ["rep", "best_wallet"]] = None
    o.loc[o.index[:100], ["group", "n_known"]] = ["unknown", 0]
    g = X.gate_decision(o, hide=True)
    assert "groups" not in g and "n_score_wallets" not in g and "reputable" not in json.dumps(g)
    assert g["holder_split"] == {"known": 500, "unknown": 100} and g["n_obs"] == 500
    flipped = o.assign(label=-o["label"], rep=-o["rep"],
                       group=np.where(o["rep"].isna(), "unknown",
                                      np.where(-o["rep"] > 0, "reputable", "known_not_reputable")),
                       best_wallet=o["best_wallet"].where(o["best_wallet"].isna(), "W0"))
    assert X.gate_decision(flipped, hide=True) == g                 # every label and skill flipped: same report


def test_gate_obs_on_market(train_ds, train_reg):
    obs = X.gate_obs(train_ds, train_reg)
    assert len(obs) == int(train_reg.coins["label"].notna().sum())
    o = obs[obs["rep"].notna()]
    assert len(o) >= 200 and X.spearman(o["rep"], o["label"]) > 0.5


# =========================================================================== grid and pre-registered decisions


def test_grid_is_the_preregistered_grid():
    assert len(X.GRID) == 4
    assert {(p["theta"], p["n_min"]) for p in X.GRID} == {(0.0, 3), (0.0, 6), (0.1, 3), (0.1, 6)}
    assert len({C.params_hash(p) for p in X.GRID}) == 4
    assert all(p["stop_pct"] == 0.30 and p["exit_by_age_s"] == 3600.0 and p["version"] == X.VERSION for p in X.GRID)
    with pytest.raises(ValueError):
        X.make_params(0.2, 3)
    assert X.CFG.exit_delay_bars == 1 and X.CFG.entry_fill == "worst" and X.CFG.exit_fill == "worst"
    assert X.DECL["uses_wallet_reputation"] and X.DECL["reputation_excludes_traded_coin"]


def _ev(n, leads, mean, mw2, pc, ci_lo):
    return {"n": n, "n_leads": leads, "mean": mean, "mean_without_top2": mw2, "placebo": {"mean_diff": pc},
            "ci90": (ci_lo, ci_lo + 0.1)}


def test_decide_train_rules():
    evals = {X.config_key(p): _ev(10, 5, 0.1, 0.1, 0.1, 0.01) for p in X.GRID}
    assert X.decide_train(evals)["verdict"] == "UNDERPOWERED_TRAIN"
    evals = {X.config_key(p): _ev(40, 5, -0.01, 0.1, 0.1, -0.1) for p in X.GRID}
    assert X.decide_train(evals)["verdict"] == "NO_CONFIG"
    evals[X.config_key(X.make_params(0.0, 3))] = _ev(40, 2, 0.05, 0.04, 0.02, 0.01)     # too few lead wallets
    assert X.decide_train(evals)["verdict"] == "NO_CONFIG"
    evals[X.config_key(X.make_params(0.0, 6))] = _ev(40, 4, 0.05, 0.04, 0.02, 0.01)
    evals[X.config_key(X.make_params(0.1, 6))] = _ev(35, 4, 0.06, 0.04, 0.02, 0.02)
    d = X.decide_train(evals)
    assert d["verdict"] == "SHORTLISTED" and d["best"] == "th0.1|n6" and len(d["shortlist"]) == 1


def test_decide_val_and_confirm_rules():
    assert X.decide_val({"n": 3, "mean": 0.2})["verdict"] == "UNDERPOWERED_VAL"
    assert X.decide_val({"n": 8, "mean": -0.01})["verdict"] == "FAIL_VAL"
    assert X.decide_val({"n": 8, "mean": 0.1, "mean_without_top2": 0.02})["verdict"] == "SELECTED_UNDERPOWERED"
    assert X.decide_val({"n": 20, "mean": 0.1, "mean_without_top2": -0.01})["verdict"] == "FAIL_VAL"
    assert X.decide_val({"n": 20, "mean": 0.1, "mean_without_top2": 0.02})["verdict"] == "SELECTED"
    assert X.confirm_allowed({"verdict": {"verdict": "REJECTED"}})[0] is False
    assert X.confirm_allowed({"verdict": {"verdict": "UNDERPOWERED"}, "configs": {"candidate": {"n": 3}}})[0]
    assert not X.confirm_allowed({"verdict": {}, "configs": {"candidate": {"n": 30, "mean": -0.02}}})[0]


def test_extras_and_combined_verdict():
    ok8 = [True] * 8

    def base(passes, rej=()):
        crit = [{"id": i + 1, "pass": v} for i, v in enumerate(passes)] + [{"id": 9, "pass": None},
                                                                          {"id": 10, "pass": True}]
        return {"criteria": crit, "auto_rejections": list(rej)}

    good = {"n_leads": 6, "leads": {"ci90_lead": (0.01, 0.2), "mean_without_top_lead": 0.05},
            "control": {"mean_diff": -0.01}}
    ex = X.x1_extras(good)
    assert [e["id"] for e in ex] == ["X1.1", "X1.2", "X1.3", "X1.4"] and ex[3]["pass"] is False
    assert X.combine_verdict(base(ok8), ex) == "PASS"                  # X1.4 is a diagnostic, never blocking
    assert X.combine_verdict(base(ok8, ["x"]), ex) == "REJECTED"
    assert X.combine_verdict(base([False] + ok8[1:]), ex) == "UNDERPOWERED"
    assert X.combine_verdict(base(ok8), X.x1_extras({**good, "n_leads": 3})) == "UNDERPOWERED"
    bad = {**good, "leads": {"ci90_lead": (-0.01, 0.2), "mean_without_top_lead": 0.05}}
    assert X.combine_verdict(base(ok8), X.x1_extras(bad)) == "FAIL"
    miss = {**good, "leads": {"ci90_lead": None, "mean_without_top_lead": 0.05}}
    assert X.combine_verdict(base(ok8), X.x1_extras(miss)) == "INCOMPLETE"


# =========================================================================== stages: end to end and refusals


@pytest.fixture
def st(tmp_path, monkeypatch):
    d = SimpleNamespace(out=tmp_path / "X1", flow=tmp_path / "flow", ledger=tmp_path / "trials.json",
                        sl=tmp_path / "shortlists")
    monkeypatch.setenv("LAB2_TRIALS", str(d.ledger))
    d.out.mkdir()
    d.flow.mkdir()
    (d.out / "PREREG.md").write_text("# X1 test prereg\n")
    (d.flow / "validation.json").write_text(json.dumps(VALID))
    return d


def _run(stage, d, ds, history=None, env=None, **kw):
    return X.run_stage(stage, out_dir=d.out, ds=ds, history=history if history is not None else [ds], flow=d.flow,
                       ledger_path=d.ledger, shortlist_path=d.sl, B=200, n_placebo=2, env=env or {},
                       _skip_coverage=kw.pop("_skip_coverage", True), **kw)


def _check(stage, d, env=None, **kw):
    return X.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {}, **kw)


def test_gate_kill_stops_x1(st):
    ds = market("train", T_TRAIN, 260, 2, informative=False)
    doc = _run("train", st, ds)
    assert doc["gate"]["decision"] == "KILL", doc["gate"]
    assert doc["decision"]["verdict"] == "KILLED_GATE" and "configs" not in doc
    assert doc["overall"].startswith("KILLED")
    runs = json.loads(st.ledger.read_text())["runs"]
    assert [r["hypothesis"] for r in runs] == ["X1-persist"]
    assert not (st.sl / "X1.json").exists()
    for stage in ("val", "test", "confirm", "final"):
        with pytest.raises(X.X1Refused, match="persistence gate"):
            _check(stage, st, env={"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"})
    with pytest.raises(X.X1Refused, match="final"):
        _run("train", st, ds)


def test_underpowered_gate_halts(st):
    doc = _run("train", st, market("train", T_TRAIN, 40, 1))
    assert doc["decision"]["verdict"] == "UNDERPOWERED_GATE"
    with pytest.raises(X.X1Refused, match="UNDERPOWERED_GATE"):
        _check("val", st)


def test_provisional_train_never_unlocks_val(st, train_ds):
    with pytest.raises(X.X1Refused, match="incomplete"):
        _run("train", st, train_ds, _skip_coverage=False)
    doc = _run("train", st, train_ds, _skip_coverage=False, allow_partial=True)
    assert doc["provisional"] and (st.out / "train_prelim.json").exists() and not (st.out / "train.json").exists()
    assert not (st.out / "prereg.lock").exists() and not (st.sl / "X1.json").exists()
    with pytest.raises(X.X1Refused, match="no TRAIN result"):
        _check("val", st)


def test_full_pipeline_and_every_refusal(st, train_ds, monkeypatch):
    env_all = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}
    for k in env_all:
        monkeypatch.setenv(k, "1")
    with pytest.raises(X.X1Refused, match="no TRAIN result"):
        _check("val", st)
    # ---- TRAIN: gate PASS, 4 configs, one shortlisted config
    tr = _run("train", st, train_ds)
    assert tr["gate"]["decision"] == "PASS" and tr["gate"]["rho"] > 0.5
    assert set(tr["configs"]) == {X.config_key(p) for p in X.GRID}
    assert tr["decision"]["verdict"] == "SHORTLISTED" and tr["decision"]["shortlist_written"]
    assert (st.out / "prereg.lock").exists() and (st.out / "train.md").exists()
    led = json.loads(st.ledger.read_text())
    assert sum(1 for v in led["configs"].values() if v["hypothesis"] == "X1") == 4
    assert led["n_trials_total"] == 2575 + 5
    # PREREG frozen
    (st.out / "PREREG.md").write_text("# edited\n")
    with pytest.raises(X.X1Refused, match="changed"):
        _check("val", st)
    (st.out / "PREREG.md").write_text("# X1 test prereg\n")
    with pytest.raises(X.X1Refused, match="no VAL result"):
        _check("test", st, env=env_all)
    with pytest.raises(X.X1Refused, match="before TEST"):
        _check("final", st, env=env_all)
    with pytest.raises(X.X1Refused, match="before TEST"):
        _check("confirm", st, env=env_all)
    sl = (st.sl / "X1.json").read_text()
    (st.sl / "X1.json").unlink()
    with pytest.raises(X.X1Refused, match="shortlist"):
        _check("val", st)
    (st.sl / "X1.json").write_text(sl)
    # ---- VAL: history = TRAIN + VAL
    va_ds = market("val", C.utc_ts("2026-10-05 02:00"), 60, 2)
    va = _run("val", st, va_ds, history=[train_ds, va_ds])
    assert va["history_splits"] == ["train", "val"]
    assert va["decision"]["verdict"] == "SELECTED" and set(va["configs"]) == {"candidate"}
    with pytest.raises(X.X1Refused, match="VAL already ran"):
        _check("val", st)
    # ---- TEST: locked without the judge's flag, then once only
    te_ds = market("test", C.utc_ts("2026-10-06 13:00"), 40, 3)
    with pytest.raises(X.X1Refused, match="LAB2_ALLOW_TEST"):
        _run("test", st, te_ds, history=[train_ds, va_ds, te_ds])
    te = _run("test", st, te_ds, history=[train_ds, va_ds, te_ds], env=env_all)
    assert te["verdict"]["verdict"] == "UNDERPOWERED"                    # < 60 trades: never PASS / FAIL
    assert {c["id"] for c in te["verdict"]["x1_extras"]} == {"X1.1", "X1.2", "X1.3", "X1.4"}
    with pytest.raises(X.X1Refused, match="already ran"):
        _check("test", st, env=env_all)
    (st.out / "test.json").rename(st.out / "test_moved.json")
    with pytest.raises(X.X1Refused, match="one test run"):
        _check("test", st, env=env_all)
    (st.out / "test_moved.json").rename(st.out / "test.json")
    # ---- CONFIRM (powered, registry warms up inside CONFIRM): the machinery CAN say PASS
    co_ds = market("confirm", C.utc_ts("2026-09-20 00:00"), 180, 4)
    co = _run("confirm", st, co_ds, env=env_all)
    assert co["verdict"]["verdict"] == "PASS", co["verdict"]
    assert co["overall"] == "PENDING FINAL"
    with pytest.raises(X.X1Refused, match="already ran"):
        _check("confirm", st, env=env_all)
    # ---- FINAL
    fi = _run("final", st, market("final", C.FINAL_LO + 3600, 60, 5), env=env_all)
    assert fi["decision"]["n"] > 0 and fi["decision"]["mean_positive"] is True
    assert fi["overall"] == "EDGE"
    with pytest.raises(X.X1Refused, match="already ran"):
        _check("final", st, env=env_all)
    for name in ("train", "val", "test", "confirm", "final"):
        assert (st.out / f"{name}.md").exists() and json.loads((st.out / f"{name}.json").read_text())["stage"] == name


def test_data_gates_and_missing_prereg_refuse(st):
    (st.flow / "validation.json").write_text(json.dumps({**VALID, "V2": {"chain_ok": 90, "transitions": 100}}))
    with pytest.raises(X.X1Refused, match="data first"):
        _check("train", st)
    (st.flow / "validation.json").write_text(json.dumps(VALID))
    (st.out / "PREREG.md").unlink()
    with pytest.raises(X.X1Refused, match="pre-register"):
        _check("train", st)


def test_debug_stage_hides_returns(st, train_ds):
    ds = market("train", T_TRAIN, 120, 6)
    ds.split = "final_train"
    ds.debug_only = True
    doc = X.run_stage("debug", out_dir=st.out, ds=ds, history=[ds], flow=st.flow, ledger_path=st.ledger, B=200,
                      n_placebo=2, env={})
    assert doc["gate"]["decision"].startswith("HIDDEN") and "rho" not in doc["gate"]
    assert doc["decision"]["verdict"] == "DEBUG"
    for e in doc["configs"].values():
        for k in ("mean", "ci90", "placebo", "control", "stress", "portfolio", "reasons", "leads", "warmup"):
            assert k not in e
        assert e["returns"].startswith("hidden")
    assert doc["event_counts"]["eligible"] == 120
    # review X1-DEBUG-LABELS: no reputable split; the per-config signal counts are flagged as label-dependent
    assert "groups" not in doc["gate"] and set(doc["gate"]["holder_split"]) == {"known", "unknown"}
    assert all(e.get("label_dependent_counts") for e in doc["configs"].values())
    md = (st.out / "debug.md").read_text()
    assert "Spearman" not in md and "mean" not in md.lower()
    assert "reputable" not in md.split("## Persistence gate")[1].split("\n## ")[0]
    assert "label-dependent" in md.split("## Configs")[1]
    assert all(r["debug"] for r in json.loads(st.ledger.read_text())["runs"])
