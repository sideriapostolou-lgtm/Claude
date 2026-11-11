"""Tests for research/lab2/y5.py: the calendar (session and day-type boundaries, exposure hours, which splits hold
weekends), the pre-registered grid and the pinned M1 host, the R30 host (entry at g + 30 min if alive, next-bar
exits), the gate as an exact filter of its host (R30 and M1), no lookahead (synthetic and real census bars), the
per-signal placebo diffs, session-day and host-relative statistics, the decision rules, and the full stage pipeline
with every refusal."""

import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from conftest import V0, make_frames, real_flow_available
from conftest import VALID_ALL as VALID
from test_common import _garble

import common as C
import m1 as M1
import y5 as Y

SOL = C.SolUsd(fallback=100.0)
X0, Y0 = 84.990359, 206.9e6
N_MIN = 186
ts = C.utc_ts


# =========================================================================== synthetic calendar markets


def cal_bars(g: int, mint_: str, pool: str, drift: float, start: int = 32, dead_from: int | None = None,
             n_buyers: int = 5) -> pd.DataFrame:
    """Hand-built bars: 1 SOL bought and 1 SOL sold every minute (flat price, alive: $3,000 of volume per 15 min at
    $100/SOL), then from minute ``start`` the pricing reserve X moves by ``drift`` SOL a minute (y = k / X). From
    ``dead_from`` on there are no trades (not alive)."""
    m0 = int(g) // 60 * 60
    X, y = X0, Y0
    k = X * y
    rows = []
    for j in range(N_MIN):
        if dead_from is not None and j >= dead_from:
            break
        b, s = 1.0, 1.0
        if j >= start:
            b, s = (1.0 + drift, 1.0) if drift >= 0 else (1.0, 1.0 - drift)
        X1 = X + b - s
        y1 = k / X1
        bt, st = (y - y1, 0.0) if y1 < y else (0.0, y1 - y)
        p0, p1 = X / y, X1 / y1
        rows.append({"minute_ts": m0 + 60 * j, "n_buys": 5, "n_sells": 5, "n_dust": 0, "buy_sol": b, "sell_sol": s,
                     "buy_tok": bt + 1e5, "sell_tok": st + 1e5, "n_buyers": n_buyers, "n_sellers": 5,
                     "top5_buy_sol": b, "open": p0, "high": max(p0, p1), "low": min(p0, p1), "close": p1,
                     "x_close": X1 - V0, "y_close": y1, "mint": mint_, "pool": pool, "g_ts": g, "minute_idx": j,
                     "agent_buy_sol": 0.0, "price_repaired": 0})
        X, y = X1, y1
    return pd.DataFrame(rows)


def cal_frames(spec: list[tuple], tag: str = "A"):
    """spec = [(g_ts, drift[, dead_from])]. FACTORY-class coins (instant, top-5 share 0.9) so the M1 host skips them
    fast; distinct creators / symbols / early buyers (one operator cluster each)."""
    g0, c0, _ = make_frames(n=1, slow_every=0, agent_every=0)
    gt, ct = g0.iloc[0].to_dict(), c0.iloc[0].to_dict()
    grads, coins, bars = [], [], []
    for i, sp in enumerate(spec):
        g, d = int(sp[0]), float(sp[1])
        dead = sp[2] if len(sp) > 2 else None
        mt, pool = f"CAL{tag}{i:04d}pump", f"CALPOOL{tag}{i:04d}"
        grads.append(dict(gt, mint=mt, pool=pool, g_ts=g, c_ts=g - 3, g_slot=1000 + i, c_slot=900 + i,
                          pool_slot=1001 + i, pool_ts=g + 2, creator=f"CR{tag}{i}", create_user=f"CU{tag}{i}",
                          symbol=f"S{tag}{i}", name=f"N{tag}{i}", completer=f"COMP{i}", completer30=f"COMP{i}",
                          grad_delay_s=3.0))
        coins.append(dict(ct, mint=mt, pool=pool, g_ts=g,
                          w120_top10=json.dumps([[f"W{tag}{i}a", 26.0, 0.0], [f"W{tag}{i}b", 1.0, 0.0]]),
                          w300_top10=json.dumps([[f"W{tag}{i}a", 26.0, 0.0]])))
        bars.append(cal_bars(g, mt, pool, d, dead_from=dead))
    return pd.DataFrame(grads), pd.DataFrame(coins), pd.concat(bars, ignore_index=True)


def day_spec(day: str, n_asia: int, n_eu: int, n_us: int, asia=0.3, eu=-0.3, us=-0.3) -> list[tuple]:
    """Coins whose g + 30 min falls in ASIA (g from 00:05), EU (from 09:00) and US (from 17:00), 10 minutes apart."""
    d0 = ts(day)
    out = [(d0 + 300 + 600 * i + 7, asia) for i in range(n_asia)]
    out += [(d0 + 9 * 3600 + 600 * i + 7, eu) for i in range(n_eu)]
    out += [(d0 + 17 * 3600 + 600 * i + 7, us) for i in range(n_us)]
    return out


def ds_of(frames, split: str = "train") -> C.Dataset:
    return C.Dataset.from_frames(split, *frames, census=C.Census.empty(), sol=SOL, guard=False)


def trades(ds: C.Dataset, p: dict, cfg: C.FillConfig = Y.FILL) -> pd.DataFrame:
    return C.run_trades(ds, Y.strategy, p, cfg)


def key(t: pd.DataFrame) -> list:
    return sorted(zip(t["mint"], t["t_dec"], t["t_in"], t["t_out"], np.round(t["ret_net"], 12)))


# =========================================================================== the calendar


@pytest.mark.parametrize("s,want", [("2026-10-02 00:00:00", "ASIA"), ("2026-10-02 07:59:59", "ASIA"),
                                    ("2026-10-02 08:00:00", "EU"), ("2026-10-02 15:59:59", "EU"),
                                    ("2026-10-02 16:00:00", "US"), ("2026-10-02 23:59:59", "US"),
                                    ("2026-10-03 00:00:00", "ASIA")])
def test_session_boundaries(s, want):
    assert Y.session_of(ts(s)) == want
    assert Y.session_of(ts(s) + 0.5) == want


@pytest.mark.parametrize("s,want", [("2026-10-02 23:59:59", "WEEKDAY"), ("2026-10-03 00:00:00", "WEEKEND"),
                                    ("2026-10-04 23:59:59", "WEEKEND"), ("2026-10-05 00:00:00", "WEEKDAY"),
                                    ("2026-09-19 12:00:00", "WEEKEND"), ("2026-10-07 12:00:00", "WEEKDAY")])
def test_day_type(s, want):
    assert Y.day_type(ts(s)) == want


def test_every_hour_has_exactly_one_session_and_the_partition_is_8_8_8():
    got = [Y.session_of(ts("2026-10-02") + 3600 * h + 1800) for h in range(24)]
    assert got == ["ASIA"] * 8 + ["EU"] * 8 + ["US"] * 8


def test_session_exposure_hours():
    e = Y.session_exposure_h(ts("2026-10-02 07:30"), ts("2026-10-02 09:00"))
    assert e == {"ASIA": pytest.approx(0.5), "EU": pytest.approx(1.0), "US": 0.0}
    e = Y.session_exposure_h(ts("2026-10-01"), ts("2026-10-03"))
    assert e == {"ASIA": pytest.approx(16), "EU": pytest.approx(16), "US": pytest.approx(16)}
    assert Y.per_session_day({"ASIA": 10, "EU": 1, "US": 0}, {"ASIA": 4.0, "EU": 1.0, "US": 8.0}) == \
        {"ASIA": pytest.approx(20.0), "EU": None, "US": 0.0}


def test_only_train_and_confirm_hold_weekend_hours():
    """PREREG 6: VAL, TEST and FINAL contain no weekend coin (weekday cannot be a gate dimension)."""
    def types(lo, hi):
        return {Y.day_type(t) for t in range(int(lo), int(hi), 3600)}
    assert types(*C.SPLIT_BOUNDS["val"]) == {"WEEKDAY"}
    assert types(*C.SPLIT_BOUNDS["test"]) == {"WEEKDAY"}
    assert types(C.FINAL_LO, C.FINAL_LO + 86400) == {"WEEKDAY"}
    assert types(*C.SPLIT_BOUNDS["train"]) == {"WEEKDAY", "WEEKEND"}
    assert types(*C.SPLIT_BOUNDS["confirm"]) == {"WEEKDAY", "WEEKEND"}
    tr = C.SPLIT_BOUNDS["train"]
    n_we = sum(Y.day_type(t) == "WEEKEND" for t in range(tr[0], tr[1], 3600))
    assert n_we == 48                              # Sat 10-03 and Sun 10-04: two of TRAIN's four days


# =========================================================================== grid and the pinned host


def test_grid_is_the_registered_11():
    keys = [Y.config_key(p) for p in Y.GRID]
    assert keys == ["R30|ASIA", "R30|EU", "R30|US", "R30|ASIA+EU", "R30|ASIA+US", "R30|EU+US", "R30|ALL",
                    "M1|ASIA", "M1|EU", "M1|US", "M1|ALL"]
    assert len({C.params_hash(p) for p in Y.GRID}) == 11
    assert [Y.config_key(p) for p in Y.GRID if not Y.is_candidate(p)] == ["R30|ALL", "M1|ALL"]
    for p in Y.GRID:
        assert p["version"] == "y5-v1" and p["session_hours_utc"] == {"ASIA": [0, 8], "EU": [8, 16], "US": [16, 24]}
        assert C.params_hash(json.loads(json.dumps(p))) == C.params_hash(p)     # shortlist round trip keeps the hash
        assert Y.host_config(p) == Y.make_params(p["host"], Y.SESSIONS)
    m1p = Y.make_params("M1", ["US"])
    assert m1p["host_params"] == M1.make_params(1.0, "rhythm+prec") and m1p["host_version"] == "m1-v1"
    assert C.params_hash(m1p["host_params"]) == Y.M1_REG_HASH
    assert Y.make_params("R30", ["EU", "ASIA"]) == Y.make_params("R30", ["ASIA", "EU"])


@pytest.mark.parametrize("host,ss", [("R30", ["ASIA", "ASIA"]), ("R30", ["MARS"]), ("R30", []), ("M1", ["ASIA", "EU"]),
                                     ("X6", ["ASIA"])])
def test_unregistered_configs_raise(host, ss):
    with pytest.raises(ValueError):
        Y.make_params(host, ss)


def test_m1_code_pin(monkeypatch, st):
    """Review Y5-3: the M1 host is also pinned by m1.py's sha256 (a code change that keeps VERSION and the params);
    the M1-host configs carry the registered pin, the R30 ones do not."""
    assert len(Y.M1_REG_SHA256) == 64 and Y.host_problems() == []
    assert all(p["host_code_sha256"] == Y.M1_REG_SHA256 for p in Y.GRID if p["host"] == "M1")
    assert all("host_code_sha256" not in p for p in Y.GRID if p["host"] == "R30")
    monkeypatch.setattr(Y, "M1_REG_SHA256", "0" * 64)
    assert any("m1.py" in x for x in Y.host_problems())
    with pytest.raises(Y.Y5Refused, match="M1 host"):
        _check("debug", st)


ENV_ALL = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}


def _m1_pair_shortlisted(d) -> None:
    """A TRAIN result that shortlisted the pair (M1|US, M1|ALL) (written directly: the gate is a prerequisite)."""
    cand = Y.make_params("M1", ["US"])
    pair = [cand, Y.host_config(cand)]
    C.write_shortlist("Y5", pair, path=d.sl, ledger_path=d.ledger)
    (d.out / "train.json").write_text(json.dumps({"stage": "train", "provisional": False, "decision": {
        "verdict": "SHORTLISTED", "shortlist_hashes": [C.params_hash(x) for x in pair]}}))


def test_m1_host_pair_waits_for_m1s_own_look(st, monkeypatch, tmp_path):
    """Review Y5-1: Y5's M1 host (m = 1, rhythm+prec) IS M1's candidate whenever M1's TRAIN picks m* = 1, so an
    M1-host pair may look at VAL / TEST / CONFIRM / FINAL only after the M1 family spent its own look there (trials
    ledger), or once M1's own written decisions forbid M1 that stage."""
    for k in ENV_ALL:
        monkeypatch.setenv(k, "1")
    m1_out = tmp_path / "M1"
    m1_out.mkdir()

    def chk(stage):
        return _check(stage, st, env=ENV_ALL, m1_out_dir=m1_out)
    _m1_pair_shortlisted(st)
    with pytest.raises(Y.Y5Refused, match="M1 has not spent its own val look"):
        chk("val")
    C.record_run("M1", M1.GRID[1], "val", {"n": 3, "mean": 0.0}, path=st.ledger)          # M1's VAL look
    assert chk("val")["m1_host_gate"].startswith("M1 spent")
    (st.out / "val.json").write_text(json.dumps({"stage": "val", "decision": {"verdict": "SELECTED"}}))
    with pytest.raises(Y.Y5Refused, match="M1 has not spent its own test look"):
        chk("test")
    with C.one_shot_session("M1", "test", st.ledger):                                    # M1's one TEST look
        pass
    chk("test")
    (st.out / "test.json").write_text(json.dumps({"stage": "test", "verdict": {"verdict": "UNDERPOWERED"},
                                                  "configs": {"candidate": {"n": 3, "mean": 0.1}}}))
    with pytest.raises(Y.Y5Refused, match="confirm"):
        chk("confirm")
    # M1's own TEST failed, so M1 never spends CONFIRM: nothing left to protect there
    (m1_out / "train.json").write_text(json.dumps({"provisional": False, "decision": {"verdict": "SHORTLISTED"}}))
    (m1_out / "val.json").write_text(json.dumps({"decision": {"verdict": "SELECTED"}}))
    (m1_out / "test.json").write_text(json.dumps({"verdict": {"verdict": "FAIL"},
                                                  "configs": {"candidate": {"n": 20, "mean": -0.1}}}))
    assert "never spends" in chk("confirm")["m1_host_gate"]
    with pytest.raises(Y.Y5Refused, match="final"):
        chk("final")                                                  # M1 may still run FINAL after its TEST
    with C.one_shot_session("M1", "final", st.ledger):
        pass
    chk("final")


def test_m1_host_pair_runs_when_m1_stopped_before_the_split(st, tmp_path):
    m1_out = tmp_path / "M1"
    m1_out.mkdir()
    _m1_pair_shortlisted(st)
    (m1_out / "train.json").write_text(json.dumps({"provisional": False,
                                                   "decision": {"verdict": "UNDERPOWERED_TRAIN"}}))
    assert "never spends" in _check("val", st, m1_out_dir=m1_out)["m1_host_gate"]
    (m1_out / "train.json").write_text(json.dumps({"provisional": True, "decision": {"verdict": "UNDERPOWERED_TRAIN"}}))
    with pytest.raises(Y.Y5Refused, match="M1 has not spent"):
        _check("val", st, m1_out_dir=m1_out)                         # a provisional M1 TRAIN decides nothing
    assert Y.m1_host_gate("val", st.ledger, m1_out) is not None and Y.m1_host_gate("train", st.ledger, m1_out) is None


def test_x5_overlap_counts_are_counts_only(tmp_path):
    """Review Y5-2: X5 gates the same pinned M1 host by a (diurnal) market regime. Y5 reports, counts only, how X5's
    M1-host TRAIN trades spread over X5's states and Y5's sessions."""
    p = tmp_path / "train_trades.csv"
    rows = [("host-M1", "2026-10-02 03:00:20", "ON"), ("host-M1", "2026-10-02 18:00:20", "ON"),
            ("host-M1", "2026-10-02 10:00:20", "OFF"), ("host-M1", "2026-10-02 20:00:20", None),
            ("host-R0", "2026-10-02 03:00:20", "ON"), ("candidate", "2026-10-02 18:00:20", "ON")]
    pd.DataFrame([{"role": r, "t_dec": ts(t), "ret_net": 0.5, "mean": 1.0, "st_GR_q0.5": s, "st_GR_q0.8": "OFF",
                   "st_SV_q0.5": "UNKNOWN"} for r, t, s in rows]).to_csv(p, index=False)
    out = Y.x5_overlap_counts(p)
    assert out["available"] and out["n_host_trades"] == 4
    assert out["by_state_and_session"]["st_GR_q0.5"] == {"ON": {"ASIA": 1, "EU": 0, "US": 1},
                                                         "OFF": {"ASIA": 0, "EU": 1, "US": 0},
                                                         "UNKNOWN": {"ASIA": 0, "EU": 0, "US": 1}}
    assert set(out["by_state_and_session"]) == {"st_GR_q0.5", "st_SV_q0.5"}            # q = 0.5 only
    assert "ret_net" not in json.dumps(out) and "mean" not in json.dumps(out)
    assert Y.x5_overlap_counts(tmp_path / "missing.csv")["available"] is False


def test_m1_host_change_is_refused(monkeypatch, st):
    assert Y.host_problems() == []
    monkeypatch.setattr(M1, "VERSION", "m1-v2")
    assert Y.host_problems() and "m1-v2" in Y.host_problems()[0]
    with pytest.raises(Y.Y5Refused, match="M1 host"):
        _check("debug", st)
    monkeypatch.setattr(M1, "VERSION", "m1-v1")
    monkeypatch.setattr(M1, "STOP_PCT", 0.2)
    monkeypatch.setattr(M1, "FIXED", {**M1.FIXED, "stop_pct": 0.2})
    assert any("hash" in x for x in Y.host_problems())


# =========================================================================== R30 host


def test_r30_enters_at_g30_when_alive_and_never_when_dead():
    # coin 0 alive; coin 1 (earlier, so coin 0's bars cover its B2 hours) has no trade after minute 20
    spec = [(ts("2026-10-02 01:05:07"), 0.0), (ts("2026-10-02 00:05:07"), 0.0, 20)]
    ds = ds_of(cal_frames(spec))
    alive_m, dead_m = "CALA0000pump", "CALA0001pump"
    assert set(ds.mints) == {alive_m, dead_m}
    t = trades(ds, Y.make_params("R30", Y.SESSIONS))
    assert list(t["mint"]) == [alive_m]
    cd = ds.coin(alive_m)
    assert t["t_dec"].iloc[0] == Y.r30_decision_time(cd)
    assert 1800 <= t["age_dec_s"].iloc[0] < 1860
    assert t["reason"].iloc[0] == "time" and t["t_out"].iloc[0] - t["t_in"].iloc[0] >= 3600
    # dead coin: SKIP at the decision, so the strategy is never asked again
    cd1 = ds.coin(dead_m)
    snap = ds.asof(dead_m, Y.r30_decision_time(cd1))
    assert Y.strategy(snap, Y.make_params("R30", Y.SESSIONS), None) is C.SKIP
    snap_early = ds.asof(dead_m, Y.r30_decision_time(cd1) - 60)
    assert Y.strategy(snap_early, Y.make_params("R30", Y.SESSIONS), None) is None


def test_r30_time_exit_and_stop_fill_on_the_next_bar():
    spec = [(ts("2026-10-02 00:05:07"), 0.0), (ts("2026-10-02 00:15:07"), -2.0)]    # coin 1 crashes after entry
    ds = ds_of(cal_frames(spec))
    flat_m, crash_m = "CALA0000pump", "CALA0001pump"
    t = trades(ds, Y.make_params("R30", Y.SESSIONS)).set_index("mint")
    flat, crash = t.loc[flat_m], t.loc[crash_m]
    cd = ds.coin(flat_m)
    j_trig = math.ceil((flat["t_in"] + 3600 - cd.m0) / 60)                         # first bar starting >= t_in + 1 h
    assert flat["reason"] == "time" and cd.bar_of(flat["t_out"]) == j_trig + 1      # next-bar time exit
    assert crash["reason"] == "stop" and crash["ret_mid"] < -0.5
    cdc = ds.coin(crash_m)
    a = cdc.arr
    jo = cdc.bar_of(crash["t_out"])
    assert crash["exit_price"] == pytest.approx(min(a["o"][jo], a["l"][jo]))
    assert a["l"][jo - 1] <= crash["entry_price"] * 0.5                              # triggered one bar earlier
    same = C.run_trades(ds, Y.strategy, Y.make_params("R30", Y.SESSIONS), C.FillConfig()).set_index("mint")
    assert same.loc[crash_m, "t_out"] < crash["t_out"]                              # same-bar fill is earlier


# =========================================================================== the gate is a filter


def _day_market(seed_days=("2026-10-02", "2026-10-03")) -> C.Dataset:
    spec = []
    for d in seed_days:
        spec += day_spec(d, 8, 6, 6)
        # g 07:29:00-07:29:45: the decision (first grid time >= g + 30 min) is 07:59:20 for two, 08:00:20 for two
        spec += [(ts(d) + 7 * 3600 + 29 * 60 + 15 * i, 0.1) for i in range(4)]
    return ds_of(cal_frames(spec))


def test_gate_is_an_exact_filter_of_the_r30_host():
    ds = _day_market()
    full = Y.with_calendar(trades(ds, Y.make_params("R30", Y.SESSIONS)))
    assert set(full["session"]) == set(Y.SESSIONS) and set(full["day_type"]) == set(Y.DAY_TYPES)
    for ss in Y.R30_SETS:
        g = trades(ds, Y.make_params("R30", ss))
        assert key(g) == key(full[full["session"].isin(list(ss))]), ss
    by = {s: len(trades(ds, Y.make_params("R30", (s,)))) for s in Y.SESSIONS}
    assert sum(by.values()) == len(full) and all(v > 0 for v in by.values())


def test_gate_reads_the_decision_clock_only():
    ds = _day_market()
    p_all = Y.make_params("R30", Y.SESSIONS)
    for m in ds.mints[:12]:
        cd = ds.coin(m)
        snap = ds.asof(m, Y.r30_decision_time(cd))
        a = Y.strategy(snap, p_all, None)
        for ss in Y.R30_SETS:
            b = Y.strategy(snap, Y.make_params("R30", ss), None)
            if Y.session_of(snap.t) in ss:
                assert b == a
            else:
                assert b is C.SKIP or (a is C.SKIP and b is C.SKIP)


def test_gate_is_an_exact_filter_of_the_m1_host():
    """Pure-bot coins (M1 fires) graduating 05:00-10:30, so M1's entries straddle ASIA / EU."""
    from test_m1 import market
    ds = market("train", ts("2026-10-02 05:00"), 12, 2, 1)
    full = Y.with_calendar(trades(ds, Y.make_params("M1", Y.SESSIONS)))
    assert len(full) >= 8 and {"ASIA", "EU"} <= set(full["session"])
    own = C.run_trades(ds, M1.strategy, Y.m1_host_params(), Y.FILL)
    assert key(own) == key(full)                                      # the host is M1 itself
    for s in Y.SESSIONS:
        g = trades(ds, Y.make_params("M1", (s,)))
        assert key(g) == key(full[full["session"] == s])


@pytest.mark.parametrize("seed", range(3))
def test_decisions_unchanged_by_own_future_garbage(seed):
    frames = cal_frames(day_spec("2026-10-02", 6, 3, 3))
    clean = ds_of(frames)
    rng = np.random.default_rng(50 + seed)
    for _ in range(8):
        m = clean.mints[int(rng.integers(len(clean.mints)))]
        cd = clean.coin(m)
        t = Y.r30_decision_time(cd) + 60 * int(rng.integers(-2, 3))
        dirty = ds_of(_garble(frames, m, t - C.DECISION_LAG_S, rng))
        if m not in dirty.mints:      # garbage may delete a whole B2 hour -> universe rule, never features
            continue
        for p in Y.GRID[:7]:
            a = Y.strategy(clean.asof(m, t), p, None)
            b = Y.strategy(dirty.asof(m, t), p, None)
            assert a == b


@pytest.mark.skipif(not real_flow_available(), reason="FLOW parquet not available")
def test_no_lookahead_real_census_train():
    """Y5 decisions (both hosts, every gate) unchanged when the coin's data after tau is garbage: real census bars."""
    f = C.flow_dir()
    frames = tuple(pd.read_parquet(f / n) for n in ("graduates.parquet", "b2_coins.parquet", "b2_bars.parquet"))
    cen = C.Census.load()
    full_ds = C.Dataset.from_frames("final_train", *frames, census=cen, sol=C.load_sol_usd())
    rng = np.random.default_rng(5)
    pick = [full_ds.mints[int(i)] for i in rng.choice(len(full_ds.mints), size=14, replace=False)]
    sub = tuple(x[x["mint"].isin(pick)] for x in frames)
    sol = C.load_sol_usd()
    clean = C.Dataset.from_frames("final_train", *sub, census=cen, sol=sol)
    n = 0
    for m in clean.mints:
        cd = clean.coin(m)
        for t in (Y.r30_decision_time(cd), cd.g + float(rng.uniform(2000, 7000))):
            t = float(cd.m0 + 60 * math.floor((t - C.GRID_OFFSET_S - cd.m0) / 60) + C.GRID_OFFSET_S)
            dirty = C.Dataset.from_frames("final_train", *_garble(sub, m, t - C.DECISION_LAG_S, rng), census=cen,
                                          sol=sol)
            if m not in dirty.mints:
                continue
            for p in Y.GRID:
                assert Y.strategy(clean.asof(m, t), p, None) == Y.strategy(dirty.asof(m, t), p, None)
            n += 1
    assert n >= 20


# =========================================================================== statistics helpers


def _t(rets, dates=None, sessions=None, mints=None) -> pd.DataFrame:
    n = len(rets)
    return pd.DataFrame({"mint": mints or [f"m{i}" for i in range(n)], "ret_net": rets,
                         "date": dates or ["2026-10-02"] * n, "session": sessions or ["ASIA"] * n})


def test_signal_diffs_match_each_trade_with_its_own_draws():
    t = _t([0.1, -0.2, 0.05])
    pl = pd.DataFrame({"signal": [0, 0, 2], "ret_net": [0.0, 0.2, -0.05]})
    d = Y.signal_diffs(t, pl)
    assert d[0] == pytest.approx(0.0) and math.isnan(d[1]) and d[2] == pytest.approx(0.1)
    assert np.isnan(Y.signal_diffs(t, pl.iloc[0:0])).all()


def test_session_days_rule():
    dates = ["2026-10-02"] * 10 + ["2026-10-03"] * 10 + ["2026-10-04"] * 10 + ["2026-10-05"] * 3
    t = _t([0.0] * 33, dates=dates)
    diffs = np.array([0.1] * 10 + [0.1] * 10 + [-0.1] * 10 + [5.0] * 3)
    sd = Y.session_days(t, diffs)
    assert sd["qualifying_days"] == 3 and sd["positive_days"] == 2 and sd["need_positive"] == 2 and sd["pass"] is True
    sd = Y.session_days(t, np.array([0.1] * 10 + [-0.1] * 20 + [5.0] * 3))
    assert sd["pass"] is False
    one = Y.session_days(_t([0.0] * 30, dates=["2026-10-02"] * 30), np.full(30, 1.0))
    assert one["qualifying_days"] == 1 and one["pass"] is None             # one session-day can never pass


def test_host_rel_is_against_the_hosts_out_of_set_trades():
    cfg = _t([0.10, 0.20], mints=["a", "b"])
    host = _t([0.10, 0.20, -0.30, -0.10, 0.5], sessions=["ASIA", "ASIA", "US", "EU", "ASIA"],
              mints=["a", "b", "c", "d", "e"])
    hr = Y.host_rel(cfg, host, ["ASIA"], B=500)
    assert hr["n_out"] == 2 and hr["mean_out"] == pytest.approx(-0.2) and hr["diff"] == pytest.approx(0.35)
    assert hr["diff_ci95"] is not None and hr["diff_ci95"][0] <= 0.35 <= hr["diff_ci95"][1]
    assert Y.host_rel(cfg, host, ["ASIA", "EU", "US"], B=100)["diff"] is None
    assert Y.host_rel(cfg, None, ["ASIA"], B=100) is None


def test_group_table_by_day_type():
    t = _t([0.1, 0.3, -0.2]).assign(day_type=["WEEKDAY", "WEEKDAY", "WEEKEND"])
    g = Y.group_table(t, np.array([0.05, np.nan, -0.1]), "day_type", Y.DAY_TYPES)
    assert g["WEEKDAY"] == {"n": 2, "n_coins": 2, "mean": pytest.approx(0.2), "placebo_diff": pytest.approx(0.05),
                            "n_matched": 1}
    assert g["WEEKEND"]["placebo_diff"] == pytest.approx(-0.1)


# =========================================================================== decision rules


def _ev(p, n=80, coins=70, mean=0.05, mw2=0.04, ci_lo=0.01, pc=0.03, hr=0.04, wk=(30, 0.02), we=(30, 0.02),
        cs=0.0, clusters=None):
    return {"config": Y.config_key(p), "host": p["host"], "candidate": Y.is_candidate(p), "n": n, "n_coins": coins,
            "n_clusters": clusters, "mean": mean, "mean_without_top2": mw2, "ci90": (ci_lo, 0.1),
            "placebo": {"mean_diff": pc}, "host_rel": {"diff": hr}, "censored_share": cs,
            "by_day_type": {"WEEKDAY": {"n": wk[0], "placebo_diff": wk[1]},
                            "WEEKEND": {"n": we[0], "placebo_diff": we[1]}}}


def _evals(**over):
    ev = {Y.config_key(p): _ev(p, mean=-0.05) for p in Y.GRID}
    for k, kw in over.items():
        p = next(q for q in Y.GRID if Y.config_key(q) == k)
        ev[k] = _ev(p, **kw)
    return ev


def test_decide_train_pair_rule_and_ranking():
    d = Y.decide_train(_evals(**{"R30|US": {}, "R30|ASIA+EU": {"ci_lo": 0.02}}))
    assert d["verdict"] == "SHORTLISTED" and d["candidate"] == "R30|ASIA+EU" and d["ranked"] == ["R30|ASIA+EU",
                                                                                                  "R30|US"]
    assert [Y.config_key(x) for x in d["shortlist"]] == ["R30|ASIA+EU", "R30|ALL"]
    assert d["shortlist_hashes"] == [C.params_hash(x) for x in d["shortlist"]]
    d = Y.decide_train(_evals(**{"R30|US": {}, "R30|EU": {}}))            # tie -> registry order
    assert d["candidate"] == "R30|EU"


def test_ungated_hosts_are_never_candidates():
    d = Y.decide_train(_evals(**{"R30|ALL": {"mean": 0.5}, "M1|ALL": {"mean": 0.5}}))
    assert d["verdict"] == "NO_CONFIG" and all(r["config"] not in ("R30|ALL", "M1|ALL") for r in d["rows"])


@pytest.mark.parametrize("kw", [{"we": (30, -0.01)}, {"wk": (10, 0.5)}, {"we": (30, None)}, {"hr": -0.01},
                                {"hr": None}, {"pc": 0.0}, {"mw2": -0.01}, {"cs": 0.2}, {"n": 59}, {"coins": 39}])
def test_each_train_bar_is_required(kw):
    d = Y.decide_train(_evals(**{"R30|ASIA": kw}))
    assert d["verdict"] in ("NO_CONFIG", "UNDERPOWERED_TRAIN") and not d["shortlist"]


def test_m1_candidates_need_three_clusters():
    assert Y.decide_train(_evals(**{"M1|US": {"clusters": 2}}))["verdict"] == "NO_CONFIG"
    d = Y.decide_train(_evals(**{"M1|US": {"clusters": 3}}))
    assert d["candidate"] == "M1|US" and [Y.config_key(x) for x in d["shortlist"]] == ["M1|US", "M1|ALL"]
    allu = {k: dict(v, n=10) for k, v in _evals().items()}
    assert Y.decide_train(allu)["verdict"] == "UNDERPOWERED_TRAIN"


def test_decide_val_and_confirm_rules():
    assert Y.decide_val({"n": 4, "mean": 1.0})["verdict"] == "UNDERPOWERED_VAL"
    assert Y.decide_val({"n": 20, "mean": 0.1, "mean_without_top2": 0.05, "host_rel": {"diff": -0.01}})["verdict"] \
        == "FAIL_VAL"
    assert Y.decide_val({"n": 20, "mean": 0.1, "mean_without_top2": 0.05, "host_rel": None})["verdict"] == "FAIL_VAL"
    assert Y.decide_val({"n": 10, "mean": 0.1, "mean_without_top2": 0.05, "host_rel": {"diff": 0.02}})["verdict"] \
        == "SELECTED_UNDERPOWERED"
    assert Y.decide_val({"n": 20, "mean": 0.1, "mean_without_top2": 0.05, "host_rel": {"diff": 0.02}})["proceed"]
    ok = Y.confirm_allowed({"verdict": {"verdict": "UNDERPOWERED"}, "configs": {"candidate": {"n": 30, "mean": 0.01}}})
    assert ok[0]
    assert not Y.confirm_allowed({"verdict": {"verdict": "FAIL"}, "configs": {"candidate": {"n": 30, "mean": -0.01}}})[0]
    assert Y.confirm_allowed({"verdict": {"verdict": "FAIL"}, "configs": {"candidate": {"n": 3, "mean": -0.5}}})[0]
    assert not Y.confirm_allowed({"verdict": {"verdict": "REJECTED"}, "configs": {"candidate": {"n": 3}}})[0]


def test_extras_and_combine_verdict():
    def base(passes, rej=()):
        crit = [{"id": i, "pass": passes.get(i, True)} for i in range(1, 11)]
        return {"criteria": crit, "auto_rejections": list(rej)}
    ev = {"host": "R30", "host_rel": {"diff": 0.07}, "session_days": {"pass": True, "qualifying_days": 3}}
    ex = Y.y5_extras(ev)
    assert [e["id"] for e in ex] == ["Y5.1", "Y5.2", "Y5.3"] and ex[0]["pass"] and ex[1]["pass"] and ex[2]["pass"] is None
    assert Y.combine_verdict(base({9: None}), ex) == "PASS"                 # FINAL is judged later; Y5.3 n/a for R30
    assert Y.combine_verdict(base({}, ["x"]), ex) == "REJECTED"
    assert Y.combine_verdict(base({1: False}), ex) == "UNDERPOWERED"
    assert Y.combine_verdict(base({5: False}), ex) == "FAIL"
    assert Y.combine_verdict(base({10: False}), ex) == "INCOMPLETE"         # > 10 % censored
    assert Y.combine_verdict(base({}), Y.y5_extras(dict(ev, host_rel={"diff": 0.05}))) == "FAIL"
    assert Y.combine_verdict(base({}), Y.y5_extras(dict(ev, session_days={"pass": None}))) == "INCOMPLETE"
    m1ev = dict(ev, host="M1", clusters={"n_clusters": 2, "mean_without_largest": 0.1})
    assert Y.combine_verdict(base({}), Y.y5_extras(m1ev)) == "FAIL"
    m1ev["clusters"] = {"n_clusters": 4, "mean_without_largest": 0.1}
    assert Y.combine_verdict(base({}), Y.y5_extras(m1ev)) == "PASS"


def test_predictions_are_reports():
    ev = _evals()
    for k in ("R30|ASIA", "R30|EU", "R30|US"):
        ev[k]["by_day_type"] = {"WEEKDAY": {"n": 30, "placebo_diff": 0.01}, "WEEKEND": {"n": 30, "placebo_diff": 0.02}}
        ev[k]["host_rel"] = {"diff": 0.01}
    pr = Y.score_predictions(ev)
    assert pr["P1_no_candidate_mean_net_above_0"]["held"] and pr["P2_r30_session_premium_within_6pts"]["held"]
    assert pr["P3_no_stable_sign_across_sessions_and_day_types"]["held"] is False


# =========================================================================== stages


@pytest.fixture
def st(tmp_path, monkeypatch):
    d = SimpleNamespace(out=tmp_path / "Y5", flow=tmp_path / "flow", ledger=tmp_path / "trials.json",
                        sl=tmp_path / "shortlists")
    monkeypatch.setenv("LAB2_TRIALS", str(d.ledger))     # one-shot looks go to the canonical ledger only
    d.out.mkdir()
    d.flow.mkdir()
    (d.out / "PREREG.md").write_text("# Y5 test prereg\n")
    (d.flow / "validation.json").write_text(json.dumps(VALID))
    # the pin is checked against today's m1.py by the CLI; tests of the pipeline must not break when M1's team edits
    # m1.py (test_m1_code_pin checks the refusal itself)
    monkeypatch.setattr(Y, "M1_REG_SHA256", Y.m1_code_sha256())
    monkeypatch.setattr(Y, "X5_TRADES", tmp_path / "X5" / "train_trades.csv")
    return d


def _run(stage, d, ds, env=None, **kw):
    return Y.run_stage(stage, out_dir=d.out, ds=ds, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, B=200,
                       n_placebo=2, env=env or {}, _skip_coverage=kw.pop("_skip_coverage", True), **kw)


def _check(stage, d, env=None, **kw):
    return Y.check_prereqs(stage, d.out, flow=d.flow, ledger_path=d.ledger, shortlist_path=d.sl, env=env or {}, **kw)


def market(split: str, days: list[str], n_asia: int, n_other: int, tag: str) -> C.Dataset:
    spec = []
    for d in days:
        spec += day_spec(d, n_asia, n_other, n_other)
    ds = ds_of(cal_frames(spec, tag=tag), split)
    assert len(ds) == len(spec)
    return ds


def test_full_pipeline_and_every_refusal(st, monkeypatch):
    env_all = {"LAB2_ALLOW_TEST": "1", "LAB2_ALLOW_CONFIRM": "1", "LAB2_ALLOW_FINAL": "1"}
    for k in env_all:            # common enforces the real env flags; y5's ``env=`` drives y5's own checks
        monkeypatch.setenv(k, "1")
    with pytest.raises(Y.Y5Refused, match="no TRAIN result"):
        _check("val", st)
    # ---- TRAIN: ASIA coins drift up after g + 30, EU / US coins drift down; Fri 10-02 (weekday) + Sat 10-03 (weekend)
    tr = _run("train", st, market("train", ["2026-10-02", "2026-10-03"], 32, 8, "T"))
    assert set(tr["configs"]) == {Y.config_key(p) for p in Y.GRID}
    assert tr["configs"]["R30|ALL"]["n"] == 2 * 48 and tr["configs"]["M1|ALL"]["n"] == 0      # FACTORY: M1 skips
    assert tr["decision"]["verdict"] == "SHORTLISTED" and tr["decision"]["candidate"] == "R30|ASIA"
    assert tr["decision"]["shortlist_written"] and (st.out / "prereg.lock").exists()
    row = next(r for r in tr["decision"]["rows"] if r["config"] == "R30|ASIA")
    assert row["day_type_ok"] == {"WEEKDAY": True, "WEEKEND": True} and row["host_rel_diff"] > 0.5
    assert set(tr["veto_by_product"]) == {"R30", "M1"} and "predictions" in tr
    led = json.loads(st.ledger.read_text())
    assert sum(1 for v in led["configs"].values() if v["hypothesis"] == "Y5") == 11
    assert led["n_trials_total"] == 2575 + 11
    assert tr["common_sha256"] == Y.common_sha256() and tr["m1_host"]["code_sha256"] == Y.m1_code_sha256()
    assert tr["x5_overlap"]["available"] is False                       # X5 has not written TRAIN trades here
    with pytest.raises(Y.Y5Refused, match="final"):
        _check("train", st)                                               # a decision on complete TRAIN is final
    # PREREG frozen
    (st.out / "PREREG.md").write_text("# edited\n")
    with pytest.raises(Y.Y5Refused, match="changed"):
        _check("val", st)
    (st.out / "PREREG.md").write_text("# Y5 test prereg\n")
    with pytest.raises(Y.Y5Refused, match="no VAL result"):
        _check("test", st, env=env_all)
    with pytest.raises(Y.Y5Refused, match="before TEST|no VAL"):
        _check("final", st, env=env_all)
    sl = (st.sl / "Y5.json").read_text()
    (st.sl / "Y5.json").unlink()
    with pytest.raises(Y.Y5Refused, match="shortlist"):
        _check("val", st)
    (st.sl / "Y5.json").write_text(sl)
    # ---- VAL (Mon 10-05); common.py "changed" since TRAIN: flagged, not refused (review Y5-3)
    monkeypatch.setattr(Y, "common_sha256", lambda: "f" * 64)
    va = _run("val", st, market("val", ["2026-10-05"], 20, 5, "V"))
    assert va["common_changed_since_train"] is True and "changed since TRAIN" in (st.out / "val.md").read_text()
    assert set(va["configs"]) == {"candidate", "host"} and va["decision"]["verdict"] == "SELECTED"
    assert va["configs"]["candidate"]["config"] == "R30|ASIA" and va["configs"]["host"]["config"] == "R30|ALL"
    assert va["decision"]["host_rel_diff"] > 0.5 and va["veto_by_product"]["flagged_sessions"] == ["EU", "US"]
    with pytest.raises(Y.Y5Refused, match="VAL already ran"):
        _check("val", st)
    # ---- TEST: locked without the judge's flag, then once only (one ASIA session-day: never PASS)
    ds_test = market("test", ["2026-10-07"], 30, 5, "E")
    with pytest.raises(Y.Y5Refused, match="LAB2_ALLOW_TEST"):
        _run("test", st, ds_test)
    te = _run("test", st, ds_test, env=env_all)
    assert te["verdict"]["verdict"] == "UNDERPOWERED"                       # < 60 trades
    assert [e["id"] for e in te["verdict"]["y5_extras"]] == ["Y5.1", "Y5.2", "Y5.3"]
    assert te["verdict"]["y5_extras"][1]["pass"] is None                    # one session-day
    with pytest.raises(Y.Y5Refused, match="already ran"):
        _check("test", st, env=env_all)
    (st.out / "test.json").rename(st.out / "test_moved.json")
    with pytest.raises(Y.Y5Refused, match="one test look"):
        _check("test", st, env=env_all)                                     # the ledger remembers
    (st.out / "test_moved.json").rename(st.out / "test.json")
    # ---- CONFIRM (powered, two ASIA session-days, one of them a weekend): the machinery CAN say PASS
    co = _run("confirm", st, market("confirm", ["2026-09-20", "2026-09-21"], 40, 12, "C"), env=env_all)
    assert co["verdict"]["verdict"] == "PASS", co["verdict"]
    assert co["configs"]["candidate"]["by_day_type"]["WEEKEND"]["n"] == 40
    assert co["overall"] == "PENDING FINAL"
    # ---- FINAL (census day thirds: synthetic coins land in final_test)
    fi = _run("final", st, market("final", ["2026-10-08"], 12, 3, "F"), env=env_all)
    assert fi["decision"]["n"] == 12 and fi["decision"]["mean_positive"] is True and fi["overall"] == "EDGE"
    with pytest.raises(Y.Y5Refused, match="already ran"):
        _check("final", st, env=env_all)
    led = json.loads(st.ledger.read_text())
    assert len(led["configs"]) == 11                                        # VAL..FINAL reuse the two TRAIN configs
    for name in ("train", "val", "test", "confirm", "final"):
        assert (st.out / f"{name}.md").exists() and json.loads((st.out / f"{name}.json").read_text())["stage"] == name


def test_nothing_qualifies_stops_before_val(st):
    tr = _run("train", st, market("train", ["2026-10-02", "2026-10-03"], 10, 4, "N"))
    assert tr["decision"]["verdict"] == "UNDERPOWERED_TRAIN" and not (st.sl / "Y5.json").exists()
    assert tr["overall"] == "UNDERPOWERED (TRAIN)"
    with pytest.raises(Y.Y5Refused, match="UNDERPOWERED_TRAIN"):
        _check("val", st)


def test_provisional_train_never_unlocks_val(st):
    ds = market("train", ["2026-10-02"], 6, 2, "P")
    with pytest.raises(Y.Y5Refused, match="incomplete"):
        _run("train", st, ds, _skip_coverage=False)
    doc = _run("train", st, ds, _skip_coverage=False, allow_partial=True)
    assert doc["provisional"] and (st.out / "train_prelim.json").exists() and not (st.out / "train.json").exists()
    assert not (st.out / "prereg.lock").exists() and not (st.sl / "Y5.json").exists()
    with pytest.raises(Y.Y5Refused, match="no TRAIN result"):
        _check("val", st)


def test_data_gates_and_missing_prereg_refuse(st):
    (st.flow / "validation.json").write_text(json.dumps({**VALID, "V2": {"chain_ok": 90, "transitions": 100}}))
    with pytest.raises(Y.Y5Refused, match="data first"):
        _check("train", st)
    _check("debug", st)                                                     # debug only reports the gates
    (st.flow / "validation.json").write_text(json.dumps(VALID))
    (st.out / "PREREG.md").unlink()
    with pytest.raises(Y.Y5Refused, match="pre-register"):
        _check("train", st)


def test_debug_stage_hides_returns(st):
    ds = market("train", ["2026-10-02"], 8, 3, "D")
    ds.split = "final_train"                    # the debug path is keyed by stage; the data is synthetic here
    ds.debug_only = True
    doc = Y.run_stage("debug", out_dir=st.out, ds=ds, flow=st.flow, ledger_path=st.ledger, B=200, n_placebo=2, env={})
    assert doc["decision"]["verdict"] == "DEBUG"
    hidden = ("mean", "ci90", "placebo", "stress", "portfolio", "reasons", "by_session", "by_day_type", "host_rel",
              "session_days", "clusters", "cost_decomposition")
    for e in doc["configs"].values():
        assert not any(k in e for k in hidden) and e["returns"].startswith("hidden")
    ec = doc["event_counts"]
    assert ec["r30_decisions_by_session"] == {"ASIA": 8, "EU": 3, "US": 3}
    assert sum(ec["r30_alive_by_session"].values()) == doc["configs"]["R30|ALL"]["n"] == 14
    assert doc["configs"]["R30|ASIA"]["by_session_n"] == {"ASIA": 8, "EU": 0, "US": 0}
    assert "veto_by_product" not in doc and "predictions" not in doc
    assert all(r["debug"] and r["mean"] is None for r in json.loads(st.ledger.read_text())["runs"])
    assert "hidden" in (st.out / "debug.md").read_text().lower()
